"""Pipeline Runner Tool Definitions and Implementations.

Provides the TOOLS list (Anthropic API tool definitions) and the _TOOL_DISPATCH
dict (tool name → callable) for the production Pipeline Runner Agent.

Builds on the POC's 4 read-only tools and adds the execution tools needed
for Phase 2: transition, checkpoint, spawn, validate, approve, modify.

Tools:
    Read-only (from POC):
        get_pipeline_status    — attractor status --json
        get_pipeline_graph     — attractor parse --output json
        get_node_details       — parse + filter by node_id
        check_checkpoint       — find and read checkpoint file

    Execution (Phase 2 new):
        get_dispatchable_nodes — attractor status --filter=pending --deps-met --json
        transition_node        — attractor transition <file> <node> <status>
        save_checkpoint        — attractor checkpoint save <file>
        spawn_orchestrator     — tmux new-session + ccorch --worktree
        dispatch_validation    — subprocess validation-test-agent call
        send_approval_request  — write to channel adapter (signal only in CLI mode)
        modify_node            — attractor node <file> modify <node> --set key=value

Usage:
    from cobuilder.attractor.runner_tools import TOOLS, get_tool_dispatch

    dispatch = get_tool_dispatch(pipeline_path="/path/to/pipeline.dot")
    result = dispatch["get_pipeline_status"]({"pipeline_path": pipeline_path})
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure local module imports work regardless of invocation directory

CLI_PATH = os.path.join(_THIS_DIR, "cli.py")

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic API format)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------
    # Read-only tools (POC-compatible)
    # ------------------------------------------------------------------
    {
        "name": "get_pipeline_status",
        "description": (
            "Run 'attractor status --json' on the pipeline DOT file. "
            "Returns JSON with node statuses, summary counts, and prd_ref."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                }
            },
            "required": ["pipeline_path"],
        },
    },
    {
        "name": "get_pipeline_graph",
        "description": (
            "Parse the DOT file and return full node/edge structure as JSON. "
            "Includes handler types, acceptance criteria, worker_type, bead_id, "
            "and all other node attributes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                }
            },
            "required": ["pipeline_path"],
        },
    },
    {
        "name": "get_node_details",
        "description": (
            "Get all attributes for a specific node by ID. "
            "Use this when you need detailed information about a single node, "
            "including its handler type, worker_type, acceptance criteria, and bead_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                },
                "node_id": {
                    "type": "string",
                    "description": "The node identifier (e.g., 'impl_backend').",
                },
            },
            "required": ["pipeline_path", "node_id"],
        },
    },
    {
        "name": "check_checkpoint",
        "description": (
            "Check if a checkpoint exists for the pipeline and return its contents. "
            "Checkpoints record the last known state and enable crash recovery."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                }
            },
            "required": ["pipeline_path"],
        },
    },
    # ------------------------------------------------------------------
    # Execution tools (Phase 2 new)
    # ------------------------------------------------------------------
    {
        "name": "get_dispatchable_nodes",
        "description": (
            "Find nodes that are ready to be dispatched: status=pending with all "
            "upstream dependencies in 'validated' state. "
            "Returns a JSON list of nodes ready for action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                }
            },
            "required": ["pipeline_path"],
        },
    },
    {
        "name": "transition_node",
        "description": (
            "Advance a node's status through the pipeline lifecycle: "
            "pending→active→impl_complete→validated (or →failed→active for retry). "
            "Writes the change directly to the DOT file with file locking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                },
                "node_id": {
                    "type": "string",
                    "description": "Node identifier to transition.",
                },
                "new_status": {
                    "type": "string",
                    "enum": ["active", "impl_complete", "validated", "failed"],
                    "description": "Target status for the node.",
                },
                "reason": {
                    "type": "string",
                    "description": "Human-readable reason for this transition (for audit trail).",
                },
            },
            "required": ["pipeline_path", "node_id", "new_status"],
        },
    },
    {
        "name": "save_checkpoint",
        "description": (
            "Save the current pipeline state to a JSON checkpoint file. "
            "Call this after every node transition to enable crash recovery. "
            "Returns the path of the saved checkpoint file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file to checkpoint.",
                }
            },
            "required": ["pipeline_path"],
        },
    },
    {
        "name": "spawn_orchestrator",
        "description": (
            "Spawn an orchestrator in a new tmux session for a codergen node. "
            "The node must have handler=codergen and status=pending with deps met. "
            "Returns the tmux session name and expected session_id. "
            "In --plan-only mode, returns a dry-run description without spawning."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                },
                "node_id": {
                    "type": "string",
                    "description": "The codergen node ID to spawn an orchestrator for.",
                },
                "worker_type": {
                    "type": "string",
                    "description": "Worker type from node attributes (e.g., 'backend-solutions-engineer').",
                },
                "bead_id": {
                    "type": "string",
                    "description": "Bead ID for the work item (from node attributes).",
                },
                "acceptance_criteria": {
                    "type": "string",
                    "description": "Acceptance criteria text from node's promise_ac attribute.",
                },
            },
            "required": ["pipeline_path", "node_id"],
        },
    },
    {
        "name": "dispatch_validation",
        "description": (
            "Dispatch a validation-test-agent for a node that has reached impl_complete. "
            "Runs the agent synchronously and returns validation results. "
            "In --plan-only mode, returns a dry-run description without dispatching."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                },
                "node_id": {
                    "type": "string",
                    "description": "Node ID to validate.",
                },
                "validation_mode": {
                    "type": "string",
                    "enum": ["technical", "business", "e2e"],
                    "description": "Validation mode to use (from node's gate attribute or 'technical' default).",
                },
                "bead_id": {
                    "type": "string",
                    "description": "Bead ID for the work item (passed to validation agent).",
                },
            },
            "required": ["pipeline_path", "node_id"],
        },
    },
    {
        "name": "send_approval_request",
        "description": (
            "Send an approval request signal for a business gate (wait.human node). "
            "In CLI mode, prints the request to stdout and writes to state file. "
            "In GChat mode, sends a card to the configured channel. "
            "Runner pauses at this node until approval is received."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                },
                "node_id": {
                    "type": "string",
                    "description": "The business gate node requiring approval.",
                },
                "gate_type": {
                    "type": "string",
                    "enum": ["technical", "business", "e2e"],
                    "description": "Type of validation gate.",
                },
                "acceptance_criteria": {
                    "type": "string",
                    "description": "The acceptance criteria that must be approved.",
                },
                "evidence_summary": {
                    "type": "string",
                    "description": "Summary of evidence produced so far.",
                },
            },
            "required": ["pipeline_path", "node_id"],
        },
    },
    {
        "name": "modify_node",
        "description": (
            "Update one or more attributes on a pipeline node. "
            "Use this to write evidence_path after successful validation, "
            "or to update any other node attribute. "
            "Attributes are specified as key=value pairs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pipeline_path": {
                    "type": "string",
                    "description": "Path to the .dot pipeline file.",
                },
                "node_id": {
                    "type": "string",
                    "description": "Node identifier to modify.",
                },
                "attributes": {
                    "type": "object",
                    "description": "Dict of attribute key→value pairs to set on the node.",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["pipeline_path", "node_id", "attributes"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _run_cli(*args: str, timeout: int = 30) -> str:
    """Run the attractor CLI and return stdout.

    Args:
        *args: Arguments to pass after the Python executable and CLI path.
        timeout: Maximum seconds to wait for the CLI to complete.

    Returns:
        CLI stdout as a string (JSON or plain text depending on command).
    """
    cmd = [sys.executable, CLI_PATH] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return json.dumps({
                "error": result.stderr.strip() or f"CLI exited with code {result.returncode}",
                "command": " ".join(args),
            })
        return result.stdout
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "CLI command timed out", "command": " ".join(args)})
    except FileNotFoundError as exc:
        return json.dumps({"error": f"CLI not found at {CLI_PATH}: {exc}"})


def _tool_get_pipeline_status(pipeline_path: str) -> str:
    """Tool: get_pipeline_status."""
    return _run_cli("status", pipeline_path, "--json")


def _tool_get_pipeline_graph(pipeline_path: str) -> str:
    """Tool: get_pipeline_graph."""
    return _run_cli("parse", pipeline_path, "--output", "json")


def _tool_get_node_details(pipeline_path: str, node_id: str) -> str:
    """Tool: get_node_details — parse graph and extract the requested node."""
    raw = _run_cli("parse", pipeline_path, "--output", "json")
    try:
        data = json.loads(raw)
        if "error" in data:
            return raw
        for node in data.get("nodes", []):
            if node["id"] == node_id:
                return json.dumps({"node_id": node_id, "attrs": node["attrs"]}, indent=2)
        return json.dumps({"error": f"Node not found: {node_id}", "pipeline": pipeline_path})
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"JSON parse error: {exc}", "raw": raw[:500]})


def _get_cobuilder_state_dir() -> Path:
    """Resolve the CoBuilder state directory, preferring cobuilder.dirs if available."""
    try:
        from cobuilder.dirs import get_state_dir
        return get_state_dir(create=False)
    except ImportError:
        # Fallback when cobuilder package isn't installed
        return Path.home() / ".claude" / "attractor" / "state"


def _tool_check_checkpoint(pipeline_path: str) -> str:
    """Tool: check_checkpoint — look for a checkpoint JSON file."""
    pipeline_dir = os.path.dirname(pipeline_path)
    pipeline_name = os.path.splitext(os.path.basename(pipeline_path))[0]

    candidates = [
        os.path.join(pipeline_dir, f"{pipeline_name}-checkpoint.json"),
        os.path.join(
            os.path.dirname(pipeline_dir),
            "state",
            f"{pipeline_name}-checkpoint.json",
        ),
        os.path.join(
            str(_get_cobuilder_state_dir()),
            f"{pipeline_name}-checkpoint.json",
        ),
    ]

    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                return json.dumps({"found": True, "path": path, "checkpoint": data}, indent=2)
            except (OSError, json.JSONDecodeError) as exc:
                return json.dumps({"found": False, "error": str(exc)})

    return json.dumps({"found": False, "checked_paths": candidates})


def _tool_get_dispatchable_nodes(pipeline_path: str) -> str:
    """Tool: get_dispatchable_nodes — nodes pending with all deps satisfied.

    Falls back to parsing the status output and filtering manually if the CLI
    does not support --filter=pending --deps-met flags.
    """
    # Try the full filter flags first
    raw = _run_cli("status", pipeline_path, "--json", "--filter=pending", "--deps-met")
    try:
        data = json.loads(raw)
        if "error" not in data:
            return raw
    except json.JSONDecodeError:
        pass

    # Fallback: get full status and filter manually
    raw = _run_cli("status", pipeline_path, "--json")
    try:
        data = json.loads(raw)
        if "error" in data:
            return raw

        nodes = data.get("nodes", [])
        validated_ids = {n["id"] for n in nodes if n.get("status") == "validated"}

        dispatchable = []
        for node in nodes:
            if node.get("status") != "pending":
                continue
            deps = node.get("dependencies", [])
            if all(d in validated_ids for d in deps):
                dispatchable.append(node)

        return json.dumps({"dispatchable_nodes": dispatchable, "count": len(dispatchable)})
    except (json.JSONDecodeError, KeyError) as exc:
        return json.dumps({"error": f"Failed to filter nodes: {exc}", "raw": raw[:500]})


def _tool_transition_node(
    pipeline_path: str,
    node_id: str,
    new_status: str,
    reason: str = "",
) -> str:
    """Tool: transition_node — advance a node's status via the CLI."""
    result_raw = _run_cli("transition", pipeline_path, node_id, new_status)

    # Parse the original status for the audit entry
    try:
        result_data = json.loads(result_raw)
        if "error" in result_data:
            return result_raw
        # Enrich with reason for audit trail
        result_data["reason"] = reason
        return json.dumps(result_data)
    except (json.JSONDecodeError, AttributeError):
        # CLI may return plain text — wrap it
        if "error" in result_raw.lower() or "invalid" in result_raw.lower():
            return json.dumps({"error": result_raw.strip(), "node_id": node_id, "new_status": new_status})
        return json.dumps({
            "success": True,
            "node_id": node_id,
            "new_status": new_status,
            "message": result_raw.strip(),
            "reason": reason,
        })


def _tool_save_checkpoint(pipeline_path: str) -> str:
    """Tool: save_checkpoint — save pipeline state to JSON."""
    result_raw = _run_cli("checkpoint", "save", pipeline_path)

    try:
        data = json.loads(result_raw)
        return json.dumps(data)
    except (json.JSONDecodeError, AttributeError):
        # CLI returns plain text "Checkpoint saved: <path>"
        if "saved" in result_raw.lower() or "checkpoint" in result_raw.lower():
            return json.dumps({"success": True, "message": result_raw.strip()})
        return json.dumps({"error": result_raw.strip()})


def _tool_spawn_orchestrator(
    pipeline_path: str,
    node_id: str,
    worker_type: str = "",
    bead_id: str = "",
    acceptance_criteria: str = "",
    *,
    plan_only: bool = False,
) -> str:
    """Tool: spawn_orchestrator — launch an orchestrator in tmux.

    In plan_only mode, returns a description without executing.
    In execute mode, creates a new tmux session with ccorch --worktree.
    """
    session_name = f"orch-{node_id}-{os.getpid()}"

    if plan_only:
        return json.dumps({
            "plan_only": True,
            "would_spawn": {
                "session_name": session_name,
                "node_id": node_id,
                "worker_type": worker_type or "general",
                "bead_id": bead_id,
                "pipeline_path": pipeline_path,
            },
            "message": (
                f"Would spawn orchestrator session '{session_name}' "
                f"for node '{node_id}' (worker_type={worker_type or 'general'}, bead_id={bead_id})"
            ),
        })

    # Build the Claude --worktree launch sequence:
    # 1. tmux creates session in repo root with zsh
    # 2. unset CLAUDECODE + launch Claude with --worktree (creates .claude/worktrees/<node>/)
    # 3. Set output style + send prompt via _tmux_send pattern
    repo_root = os.path.dirname(os.path.abspath(pipeline_path))

    try:
        cmd = [
            "tmux", "new-session",
            "-d",             # detached
            "-s", session_name,  # session name
            "-c", repo_root,  # start in repo root
            "-x", "220",     # width
            "-y", "50",      # height
            "exec zsh",       # clean shell
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)

        if result.returncode != 0:
            return json.dumps({
                "error": result.stderr.strip() or f"tmux exited with code {result.returncode}",
                "node_id": node_id,
                "session_name": session_name,
            })

        # Wait for shell to initialize, then launch Claude with --worktree
        time.sleep(2)

        # Pattern 1: text and Enter as separate send-keys calls
        def _send(text: str, pause: float = 2.0) -> None:
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, text],
                check=True, capture_output=True, text=True,
            )
            time.sleep(pause)
            subprocess.run(
                ["tmux", "send-keys", "-t", session_name, "Enter"],
                check=True, capture_output=True, text=True,
            )

        node_quoted = shlex.quote(node_id)
        _send(f"unset CLAUDECODE && ccorch --worktree {node_quoted}", pause=8.0)
        _send("/output-style orchestrator", pause=3.0)

        # Send scoped prompt telling the orchestrator what to work on
        ac_text = acceptance_criteria or "See the Solution Design document for this node."
        scoped_prompt = (
            f"You are assigned to implement pipeline node {shlex.quote(node_id)}.\n"
            f"\n"
            f"## Scope\n"
            f"- Node: {node_id}\n"
            f"- Worker type: {worker_type or 'general'}\n"
            f"- Bead: {bead_id or 'N/A'}\n"
            f"\n"
            f"## Acceptance Criteria\n"
            f"{ac_text}\n"
            f"\n"
            f"## IMPORTANT\n"
            f"You are responsible for THIS NODE ONLY. Do not work on other pipeline nodes.\n"
            f"Focus exclusively on meeting the acceptance criteria above.\n"
            f"Use the orchestrator-multiagent skill to delegate implementation to workers."
        )
        _send(scoped_prompt, pause=2.0)

        return json.dumps({
            "success": True,
            "session_name": session_name,
            "session_id": session_name,
            "node_id": node_id,
            "worker_type": worker_type or "general",
            "bead_id": bead_id,
            "worktree": f".claude/worktrees/{node_id}",
            "message": f"Spawned orchestrator session '{session_name}' for node '{node_id}' with --worktree",
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "tmux spawn timed out", "node_id": node_id})
    except FileNotFoundError:
        return json.dumps({
            "error": "tmux not found — cannot spawn orchestrator in non-tmux environment",
            "node_id": node_id,
            "plan_only_fallback": True,
            "would_spawn": session_name,
        })


def _tool_dispatch_validation(
    pipeline_path: str,
    node_id: str,
    validation_mode: str = "technical",
    bead_id: str = "",
    *,
    plan_only: bool = False,
) -> str:
    """Tool: dispatch_validation — run validation-test-agent for a node.

    In plan_only mode, returns a description without executing.
    In execute mode, runs validation-test-agent as a subprocess.
    """
    if plan_only:
        return json.dumps({
            "plan_only": True,
            "would_validate": {
                "node_id": node_id,
                "mode": validation_mode,
                "bead_id": bead_id,
                "pipeline_path": pipeline_path,
            },
            "message": (
                f"Would dispatch validation-test-agent for node '{node_id}' "
                f"(mode={validation_mode}, bead_id={bead_id})"
            ),
        })

    # Build validation command
    # validation-test-agent is invoked via claude CLI in the project
    cmd_parts = [
        sys.executable, "-m", "validation_runner",
        f"--mode={validation_mode}",
        f"--task_id={node_id}",
    ]
    if bead_id:
        cmd_parts.append(f"--prd={bead_id}")

    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max for validation
            cwd=os.path.dirname(pipeline_path),
        )
        passed = result.returncode == 0
        return json.dumps({
            "success": True,
            "passed": passed,
            "node_id": node_id,
            "mode": validation_mode,
            "returncode": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500] if result.stderr else "",
        })
    except subprocess.TimeoutExpired:
        return json.dumps({
            "error": "Validation timed out after 300s",
            "node_id": node_id,
            "passed": False,
        })
    except FileNotFoundError:
        # Validation runner not available — return structured failure
        return json.dumps({
            "error": "validation_runner module not found — validation not available",
            "node_id": node_id,
            "passed": False,
            "plan_only_fallback": True,
        })


def _tool_send_approval_request(
    pipeline_path: str,
    node_id: str,
    gate_type: str = "business",
    acceptance_criteria: str = "",
    evidence_summary: str = "",
) -> str:
    """Tool: send_approval_request — signal business gate requires approval."""
    payload = {
        "signal": "AWAITING_APPROVAL",
        "node_id": node_id,
        "gate_type": gate_type,
        "acceptance_criteria": acceptance_criteria,
        "evidence_summary": evidence_summary,
        "pipeline_path": pipeline_path,
    }
    print(f"\n[APPROVAL REQUIRED] Node '{node_id}' requires {gate_type} approval.")
    if acceptance_criteria:
        print(f"  Criteria: {acceptance_criteria}")
    if evidence_summary:
        print(f"  Evidence: {evidence_summary}")
    print("  Waiting for approval signal... (send APPROVE or REJECT)")

    return json.dumps({
        "success": True,
        "node_id": node_id,
        "gate_type": gate_type,
        "status": "awaiting_approval",
        "message": f"Approval request sent for node '{node_id}' (gate_type={gate_type})",
    })


def _tool_modify_node(
    pipeline_path: str,
    node_id: str,
    attributes: dict[str, str],
) -> str:
    """Tool: modify_node — update node attributes via CLI."""
    if not attributes:
        return json.dumps({"error": "No attributes provided to modify"})

    # Build --set args: key=value pairs
    set_args = []
    for key, value in attributes.items():
        set_args.extend(["--set", f"{key}={value}"])

    result_raw = _run_cli("node", pipeline_path, "modify", node_id, *set_args)

    try:
        data = json.loads(result_raw)
        if "error" in data:
            return result_raw
        return json.dumps({
            "success": True,
            "node_id": node_id,
            "modified_attrs": attributes,
            "message": f"Node '{node_id}' attributes updated",
        })
    except json.JSONDecodeError:
        if "error" in result_raw.lower():
            return json.dumps({"error": result_raw.strip(), "node_id": node_id})
        return json.dumps({
            "success": True,
            "node_id": node_id,
            "modified_attrs": attributes,
            "message": result_raw.strip(),
        })


# ---------------------------------------------------------------------------
# Tool dispatch factory
# ---------------------------------------------------------------------------


def get_tool_dispatch(
    *,
    plan_only: bool = False,
) -> dict[str, Any]:
    """Return the tool dispatch table for the runner.

    Args:
        plan_only: If True, execution tools (spawn, validate) will return
            dry-run descriptions instead of executing.

    Returns:
        Dict mapping tool name → callable(tool_input: dict) → str.
    """
    return {
        # Read-only tools
        "get_pipeline_status": lambda inp: _tool_get_pipeline_status(inp["pipeline_path"]),
        "get_pipeline_graph": lambda inp: _tool_get_pipeline_graph(inp["pipeline_path"]),
        "get_node_details": lambda inp: _tool_get_node_details(
            inp["pipeline_path"], inp["node_id"]
        ),
        "check_checkpoint": lambda inp: _tool_check_checkpoint(inp["pipeline_path"]),
        # Execution tools
        "get_dispatchable_nodes": lambda inp: _tool_get_dispatchable_nodes(inp["pipeline_path"]),
        "transition_node": lambda inp: _tool_transition_node(
            inp["pipeline_path"],
            inp["node_id"],
            inp["new_status"],
            inp.get("reason", ""),
        ),
        "save_checkpoint": lambda inp: _tool_save_checkpoint(inp["pipeline_path"]),
        "spawn_orchestrator": lambda inp: _tool_spawn_orchestrator(
            inp["pipeline_path"],
            inp["node_id"],
            inp.get("worker_type", ""),
            inp.get("bead_id", ""),
            inp.get("acceptance_criteria", ""),
            plan_only=plan_only,
        ),
        "dispatch_validation": lambda inp: _tool_dispatch_validation(
            inp["pipeline_path"],
            inp["node_id"],
            inp.get("validation_mode", "technical"),
            inp.get("bead_id", ""),
            plan_only=plan_only,
        ),
        "send_approval_request": lambda inp: _tool_send_approval_request(
            inp["pipeline_path"],
            inp["node_id"],
            inp.get("gate_type", "business"),
            inp.get("acceptance_criteria", ""),
            inp.get("evidence_summary", ""),
        ),
        "modify_node": lambda inp: _tool_modify_node(
            inp["pipeline_path"],
            inp["node_id"],
            inp.get("attributes", {}),
        ),
    }


def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    dispatch: dict[str, Any],
) -> str:
    """Execute a tool from the dispatch table.

    Args:
        tool_name: Name of the tool to execute.
        tool_input: Parameters for the tool.
        dispatch: Tool dispatch table from get_tool_dispatch().

    Returns:
        Tool result as a JSON string.
    """
    fn = dispatch.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        return fn(tool_input)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Tool execution failed: {type(exc).__name__}: {exc}"})
