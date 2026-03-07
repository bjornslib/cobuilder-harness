#!/usr/bin/env python3
"""POC Pipeline Runner Agent.

Phase 2 proof-of-concept for the Attractor execution engine.

This agent reads a DOT pipeline file and produces a RunnerPlan describing
what actions to take next. In POC mode, it PLANS but does NOT execute.
This validates the agent's graph reasoning without risk.

The agent loop uses anthropic.Anthropic().messages.create() with tool use.
Model: claude-sonnet-4-5-20250929

Architecture:
    1. Load pipeline from DOT file via attractor status + parse CLI
    2. Run the tool-use loop until the agent produces a final RunnerPlan
    3. Print the plan to stdout and emit signals via the channel adapter
    4. In --execute mode (Phase 2 production), actions are actually performed

Usage:
    # POC: plan only, no execution
    python3 poc_pipeline_runner.py .claude/attractor/examples/simple-pipeline.dot

    # With explicit channel (default: stdout)
    python3 poc_pipeline_runner.py pipeline.dot --channel stdout

    # Show debug tool calls
    python3 poc_pipeline_runner.py pipeline.dot --verbose

    # Production mode (Phase 2, not implemented in POC)
    python3 poc_pipeline_runner.py pipeline.dot --execute

    python3 poc_pipeline_runner.py --help

Files:
    poc_pipeline_runner.py          This file
    adapters/                       Channel adapter implementations
    .claude/attractor/examples/     Test DOT files for poc_test_scenarios.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from typing import Any

import anthropic

# Ensure adapter imports work regardless of invocation directory
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from adapters import ChannelAdapter, create_adapter  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Load environment variables from .claude/attractor/.env
try:
    from dispatch_worker import load_attractor_env
    os.environ.update(load_attractor_env())
except ImportError:
    # If dispatch_worker is not available in this context, that's OK
    pass

def _get_default_model():
    """Get the default model from environment or fallback to hardcoded value."""
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


CLI_PATH = os.path.join(_THIS_DIR, "cli.py")
MODEL = _get_default_model()

SYSTEM_PROMPT = """\
You are a Pipeline Runner agent. Your job is to analyze an Attractor-style
DOT pipeline graph and determine the NEXT ACTIONS to take.

Rules:
1. Always call get_pipeline_status first to understand current node states.
2. Then call get_pipeline_graph to understand the topology (dependencies).
3. Identify nodes that are "pending" with all upstream dependencies satisfied.
4. For each ready node, determine the action based on handler type:
   - handler=start       → no action needed if already validated, otherwise "initialize"
   - handler=codergen    → "spawn_orchestrator" with worker_type from node attrs
   - handler=wait.human  → "dispatch_validation" with mode from node attrs
   - handler=tool        → "execute_tool" with command from node attrs
   - handler=conditional → "evaluate_condition"
   - handler=parallel    → "sync_parallel" (fan-out or fan-in)
   - handler=exit        → "signal_finalize" only if ALL predecessors are validated

5. Order actions by pipeline dependency (upstream before downstream).
6. NEVER propose validating a node that has NOT reached impl_complete or validated status.
7. NEVER propose spawning a worker for a node whose dependencies are not validated.
8. If no actions are possible and pipeline is not at exit: report blocked_nodes with reasons.
9. A node with status "validated" is COMPLETE — do not propose actions for it.
10. Nodes with status "active" or "impl_complete" are in progress — propose validation.
11. When proposing "signal_finalize" for an exit node (all predecessors validated), set "pipeline_complete": true in the plan.

Produce a JSON RunnerPlan with this exact structure:
{
  "pipeline_id": "<graph_name>",
  "prd_ref": "<prd_ref from graph attrs>",
  "current_stage": "PARSE|VALIDATE|INITIALIZE|EXECUTE|FINALIZE",
  "summary": "<1-2 sentence description of current state and next steps>",
  "actions": [
    {
      "node_id": "<node_id>",
      "action": "spawn_orchestrator|dispatch_validation|execute_tool|signal_finalize|signal_stuck|initialize|sync_parallel|evaluate_condition",
      "reason": "<why this action>",
      "dependencies_satisfied": ["<dep1>", "<dep2>"],
      "worker_type": "<worker type or null>",
      "validation_mode": "<technical|business|e2e or null>",
      "priority": "high|normal|low"
    }
  ],
  "blocked_nodes": [
    {
      "node_id": "<node_id>",
      "reason": "<why blocked>",
      "missing_deps": ["<dep_id>"]
    }
  ],
  "completed_nodes": ["<node_id>", ...],
  "pipeline_complete": false  // Set to true when proposing signal_finalize for exit node
}

When you have gathered all information needed to produce the plan, output ONLY the JSON object
(no markdown, no explanation). The plan will be parsed directly.
"""

# ---------------------------------------------------------------------------
# Tool definitions for the Anthropic messages.create() API
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
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
            "Use this when you need detailed information about a single node."
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
]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _run_cli(*args: str) -> str:
    """Run the attractor CLI and return stdout."""
    cmd = [sys.executable, CLI_PATH] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
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


def _get_pipeline_status(pipeline_path: str) -> str:
    """Tool: get_pipeline_status."""
    return _run_cli("status", pipeline_path, "--json")


def _get_pipeline_graph(pipeline_path: str) -> str:
    """Tool: get_pipeline_graph."""
    return _run_cli("parse", pipeline_path, "--output", "json")


def _get_node_details(pipeline_path: str, node_id: str) -> str:
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


def _check_checkpoint(pipeline_path: str) -> str:
    """Tool: check_checkpoint — look for a checkpoint JSON file."""
    # Derive checkpoint path from pipeline path
    pipeline_dir = os.path.dirname(pipeline_path)
    pipeline_name = os.path.splitext(os.path.basename(pipeline_path))[0]

    # Try standard checkpoint locations
    candidates = [
        os.path.join(pipeline_dir, f"{pipeline_name}-checkpoint.json"),
        os.path.join(
            os.path.dirname(pipeline_dir),
            "state",
            f"{pipeline_name}-checkpoint.json",
        ),
        os.path.join(
            os.path.expanduser("~/.claude/attractor/state"),
            f"{pipeline_name}-checkpoint.json",
        ),
    ]

    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                return json.dumps({
                    "found": True,
                    "path": path,
                    "checkpoint": data,
                }, indent=2)
            except (OSError, json.JSONDecodeError) as exc:
                return json.dumps({"found": False, "error": str(exc)})

    return json.dumps({"found": False, "checked_paths": candidates})


# Dispatch table: tool name -> callable
_TOOL_DISPATCH = {
    "get_pipeline_status": lambda inp: _get_pipeline_status(inp["pipeline_path"]),
    "get_pipeline_graph": lambda inp: _get_pipeline_graph(inp["pipeline_path"]),
    "get_node_details": lambda inp: _get_node_details(
        inp["pipeline_path"], inp["node_id"]
    ),
    "check_checkpoint": lambda inp: _check_checkpoint(inp["pipeline_path"]),
}


def _execute_tool(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Dispatch and execute a tool call."""
    fn = _TOOL_DISPATCH.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
    try:
        return fn(tool_input)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"Tool execution failed: {type(exc).__name__}: {exc}"})


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------


def run_runner_agent(
    pipeline_path: str,
    *,
    adapter: ChannelAdapter,
    verbose: bool = False,
    max_iterations: int = 20,
) -> dict[str, Any]:
    """Run the Pipeline Runner agent loop.

    Uses anthropic.Anthropic().messages.create() with tool use.
    Iterates until the model produces a final text response (the RunnerPlan JSON).

    Args:
        pipeline_path: Absolute or relative path to the .dot pipeline file.
        adapter: Channel adapter for signaling upstream.
        verbose: If True, print tool call details to stderr.
        max_iterations: Safety limit on tool-use iterations.

    Returns:
        The parsed RunnerPlan dict.

    Raises:
        RuntimeError: If the agent exceeds max_iterations or produces malformed output.
    """
    client = anthropic.Anthropic()

    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                f"Analyze the pipeline at: {pipeline_path}\n\n"
                "Produce a RunnerPlan as a JSON object. "
                "Call the available tools to gather all necessary information first."
            ),
        }
    ]

    adapter.send_signal("RUNNER_STARTED", payload={"pipeline_path": pipeline_path})

    for iteration in range(max_iterations):
        if verbose:
            print(f"[agent] Iteration {iteration + 1}/{max_iterations}", file=sys.stderr)

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if verbose:
            print(
                f"[agent] stop_reason={response.stop_reason} "
                f"content_blocks={len(response.content)}",
                file=sys.stderr,
            )

        # Append assistant response to conversation
        messages.append({"role": "assistant", "content": response.content})

        # If the model produced a final text response, we're done
        if response.stop_reason == "end_turn":
            # Extract the final text block
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text = block.text.strip()
                    break

            if not final_text:
                raise RuntimeError("Agent produced end_turn but no text content.")

            # Parse the JSON plan
            try:
                plan = json.loads(final_text)
            except json.JSONDecodeError:
                # Try to extract JSON from the text (model may add commentary)
                import re
                m = re.search(r"\{.*\}", final_text, re.DOTALL)
                if m:
                    plan = json.loads(m.group(0))
                else:
                    raise RuntimeError(
                        f"Agent output is not valid JSON:\n{final_text[:500]}"
                    )

            # Signal completion or stuck state
            if plan.get("pipeline_complete"):
                adapter.send_signal(
                    "RUNNER_COMPLETE",
                    payload={"pipeline_id": plan.get("pipeline_id")},
                )
            elif not plan.get("actions"):
                adapter.send_signal(
                    "RUNNER_STUCK",
                    payload={
                        "pipeline_id": plan.get("pipeline_id"),
                        "blocked_nodes": plan.get("blocked_nodes", []),
                    },
                )

            return plan

        # Handle tool_use stop reason
        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if verbose:
                        print(
                            f"[tool] {block.name}({json.dumps(block.input, separators=(',', ':'))})",
                            file=sys.stderr,
                        )
                    result_content = _execute_tool(block.name, block.input)
                    if verbose:
                        print(
                            f"[tool] → {result_content[:200]}{'...' if len(result_content) > 200 else ''}",
                            file=sys.stderr,
                        )
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_content,
                        }
                    )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason
        raise RuntimeError(
            f"Unexpected stop_reason: {response.stop_reason} at iteration {iteration + 1}"
        )

    raise RuntimeError(
        f"Agent exceeded max_iterations ({max_iterations}) without producing a plan."
    )


# ---------------------------------------------------------------------------
# Plan display
# ---------------------------------------------------------------------------


def print_plan(plan: dict[str, Any]) -> None:
    """Pretty-print the RunnerPlan to stdout."""
    pipeline_id = plan.get("pipeline_id", "unknown")
    prd_ref = plan.get("prd_ref", "")
    stage = plan.get("current_stage", "UNKNOWN")
    summary = plan.get("summary", "")
    actions = plan.get("actions", [])
    blocked = plan.get("blocked_nodes", [])
    completed = plan.get("completed_nodes", [])
    pipeline_complete = plan.get("pipeline_complete", False)

    print(f"\n{'=' * 60}")
    print(f"  PIPELINE RUNNER PLAN")
    print(f"{'=' * 60}")
    print(f"  Pipeline:  {pipeline_id}")
    if prd_ref:
        print(f"  PRD:       {prd_ref}")
    print(f"  Stage:     {stage}")
    print(f"  Summary:   {summary}")

    if pipeline_complete:
        print("\n  *** PIPELINE COMPLETE — All nodes validated ***")

    if completed:
        print(f"\n  Completed nodes ({len(completed)}):")
        for nid in completed:
            print(f"    ✓ {nid}")

    if actions:
        print(f"\n  Actions ({len(actions)}):")
        for i, action in enumerate(actions, 1):
            prio = action.get("priority", "normal")
            prio_tag = f" [{prio.upper()}]" if prio != "normal" else ""
            print(
                f"  {i:2}. [{action.get('action', '?')}]{prio_tag} {action.get('node_id', '?')}"
            )
            print(f"      Reason: {action.get('reason', '')}")
            deps = action.get("dependencies_satisfied", [])
            if deps:
                print(f"      Deps:   {', '.join(deps)}")
            if action.get("worker_type"):
                print(f"      Worker: {action['worker_type']}")
            if action.get("validation_mode"):
                print(f"      Mode:   {action['validation_mode']}")
    else:
        print("\n  No actions proposed.")

    if blocked:
        print(f"\n  Blocked nodes ({len(blocked)}):")
        for b in blocked:
            node_id = b if isinstance(b, str) else b.get("node_id", "?")
            reason = "" if isinstance(b, str) else b.get("reason", "")
            missing = [] if isinstance(b, str) else b.get("missing_deps", [])
            print(f"    ✗ {node_id}: {reason}")
            if missing:
                print(f"      Missing: {', '.join(missing)}")

    print(f"\n{'=' * 60}\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="POC Pipeline Runner — analyze an Attractor DOT pipeline and produce a plan.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 poc_pipeline_runner.py .claude/attractor/examples/simple-pipeline.dot
  python3 poc_pipeline_runner.py pipeline.dot --verbose
  python3 poc_pipeline_runner.py pipeline.dot --json
        """,
    )
    ap.add_argument("pipeline", help="Path to the .dot pipeline file.")
    ap.add_argument(
        "--channel",
        default="stdout",
        choices=["stdout", "native_teams"],
        help="Communication channel adapter (default: stdout).",
    )
    ap.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print tool call details to stderr.",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw RunnerPlan JSON instead of formatted display.",
    )
    ap.add_argument(
        "--max-iterations",
        type=int,
        default=20,
        help="Maximum tool-use iterations (default: 20).",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="(Phase 2) Execute actions in addition to planning. NOT implemented in POC.",
    )
    # Channel-specific options
    ap.add_argument(
        "--team-name", default="s3-live-workers", help="Native teams team name."
    )
    ap.add_argument("--session-id", default="pipeline-runner-poc", help="Runner session ID.")

    args = ap.parse_args()

    if args.execute:
        print(
            "Warning: --execute is not implemented in POC mode. Planning only.",
            file=sys.stderr,
        )

    # Resolve pipeline path
    pipeline_path = os.path.abspath(args.pipeline)
    if not os.path.exists(pipeline_path):
        print(f"Error: Pipeline file not found: {pipeline_path}", file=sys.stderr)
        sys.exit(1)

    # Create channel adapter
    channel_kwargs: dict[str, Any] = {}
    if args.channel == "native_teams":
        channel_kwargs = {"team_name": args.team_name}

    adapter = create_adapter(args.channel, **channel_kwargs)

    # Derive pipeline ID for registration
    pipeline_id = os.path.splitext(os.path.basename(pipeline_path))[0]
    adapter.register(args.session_id, pipeline_id)

    try:
        plan = run_runner_agent(
            pipeline_path,
            adapter=adapter,
            verbose=args.verbose,
            max_iterations=args.max_iterations,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        adapter.send_signal("RUNNER_ERROR", payload={"error": str(exc)})
        sys.exit(1)
    except anthropic.APIError as exc:
        print(f"Anthropic API error: {exc}", file=sys.stderr)
        adapter.send_signal("RUNNER_ERROR", payload={"error": str(exc)})
        sys.exit(1)
    finally:
        adapter.unregister()

    if args.json_output:
        print(json.dumps(plan, indent=2))
    else:
        print_plan(plan)


if __name__ == "__main__":
    main()
