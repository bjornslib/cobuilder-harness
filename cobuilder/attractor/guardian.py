#!/usr/bin/env python3
"""guardian.py — Guardian Agent + Terminal Bridge (Layers 0 & 1).

Merged from guardian_agent.py (Layer 1) and launch_guardian.py (Layer 0).

Provides the interactive terminal (ccsystem3 / Layer 0) with the ability to
launch one or more Headless Guardian agents (Layer 1) via the claude_code_sdk,
monitor them for terminal-targeted signals, and handle escalations or
completion events.

Architecture:
    guardian.py (Layer 0/1 — launch bridge + Guardian agent process)
        │
        ├── parse_args()                → CLI argument parsing (--dot | --multi)
        ├── build_system_prompt()       → pipeline execution instructions for Claude
        ├── build_initial_prompt()      → first user message with pipeline context
        ├── build_options()             → ClaudeCodeOptions (Bash only, max_turns, model)
        ├── launch_guardian()           → Single guardian launch via Agent SDK query()
        ├── launch_multiple_guardians() → Parallel launch via asyncio.gather
        ├── monitor_guardian()          → Health-check loop watching terminal signals
        ├── handle_escalation()         → Format + forward Guardian escalation to user
        └── handle_pipeline_complete()  → Finalize and summarise a completed pipeline

CLAUDECODE environment note:
    The Guardian may be launched from inside a Claude Code session. To avoid
    nested-session conflicts we pass env={"CLAUDECODE": ""} as a workaround
    to suppress the variable. The definitive fix (subprocess.Popen with a
    cleaned env) lives in runner.py (spawn mode).

Usage:
    # Single guardian
    python guardian.py \\
        --dot <path_to_pipeline.dot> \\
        --pipeline-id <id> \\
        [--project-root <path>] \\
        [--model <model_id>] \\
        [--max-turns <n>] \\
        [--signal-timeout <seconds>] \\
        [--max-retries <n>] \\
        [--signals-dir <path>] \\
        [--dry-run]

    # Parallel launch from JSON config
    python guardian.py --multi <configs.json>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Ensure this file's directory is importable regardless of invocation CWD.

import cobuilder.attractor.identity_registry as identity_registry
from cobuilder.attractor.dispatch_worker import load_attractor_env

# Import signal_protocol at module level so tests can patch
# ``guardian.wait_for_signal`` directly via unittest.mock.patch.
from cobuilder.attractor.signal_protocol import wait_for_signal  # noqa: E402

# Import merge_queue so it is available in the Guardian process for signal handling
try:
    import cobuilder.attractor.merge_queue as merge_queue  # noqa: F401  (imported for side-effects / availability)
except ImportError:
    pass  # merge_queue not available in test-only environments

# ---------------------------------------------------------------------------
# Logfire instrumentation (required)
# ---------------------------------------------------------------------------
import logfire

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# Gracefully handle missing Logfire project credentials:
# When running in an impl repo without .logfire/, logfire.configure()
# triggers an interactive prompt that crashes non-interactive contexts.
_send_to_logfire_env = os.environ.get("LOGFIRE_SEND_TO_LOGFIRE", "").lower()
if _send_to_logfire_env == "false":
    _logfire_enabled = False
elif _send_to_logfire_env == "true":
    _logfire_enabled = True
else:
    _logfire_enabled = (
        Path(".logfire").is_dir()
        or bool(os.environ.get("LOGFIRE_TOKEN"))
    )

logfire.configure(
    send_to_logfire=_logfire_enabled,
    inspect_arguments=False,
    scrubbing=False,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_TURNS = 200          # more turns than runner; guardian runs longer
DEFAULT_SIGNAL_TIMEOUT = 600     # 10 minutes per wait cycle
DEFAULT_MAX_RETRIES = 3          # max retries per node before escalating
DEFAULT_MONITOR_TIMEOUT = 3600   # 1 hour total monitor timeout
DEFAULT_MODEL = "claude-sonnet-4-6"  # default Claude model for guardian


# ---------------------------------------------------------------------------
# Public helper functions (importable for testing)
# ---------------------------------------------------------------------------


def build_system_prompt(
    dot_path: str,
    pipeline_id: str,
    scripts_dir: str,
    signal_timeout: float,
    max_retries: int,
    target_dir: str = "",
) -> str:
    """Return the system prompt that instructs the Claude Guardian how to run the pipeline.

    Args:
        dot_path: Absolute path to the pipeline DOT file.
        pipeline_id: Unique pipeline identifier string.
        scripts_dir: Absolute path to the attractor scripts directory.
        signal_timeout: Seconds to wait per signal wait cycle.
        max_retries: Maximum retries allowed per node before escalation.
        target_dir: Target implementation repo directory.

    Returns:
        Formatted system prompt string.
    """
    with logfire.span("guardian.build_system_prompt", pipeline_id=pipeline_id):
        target_dir_line = f"- Target directory: {target_dir}"
        target_dir_flag = f" --target-dir {target_dir}"
        return f"""\
You are a Headless Guardian agent (Layer 1) in a 4-layer pipeline execution system.

Your role: Drive pipeline execution autonomously by reading the DOT graph, spawning
Runners for each codergen node, handling signals, and transitioning node statuses.

## Your Assignment
- Pipeline DOT: {dot_path}
- Pipeline ID: {pipeline_id}
- Scripts directory: {scripts_dir}
- Signal timeout: {signal_timeout}s per wait cycle
- Max retries per node: {max_retries}
{target_dir_line}

## Tools Available (via Bash — use python3 to invoke)
All scripts are in {scripts_dir}:

### Attractor CLI (pipeline management)
- python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json    # Find ready nodes
- python3 {scripts_dir}/cli.py status {dot_path} --json                                  # Full status
- python3 {scripts_dir}/cli.py parse {dot_path} --output json                            # Full graph
- python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> <new_status>  # Advance status
- python3 {scripts_dir}/cli.py checkpoint save {dot_path}                                # Save checkpoint

### Signal Tools
- python3 {scripts_dir}/wait_for_signal.py --target guardian --timeout {signal_timeout}  # Wait for runner
- python3 {scripts_dir}/read_signal.py <signal_path>                                      # Read signal
- python3 {scripts_dir}/respond_to_runner.py VALIDATION_PASSED --node <id>               # Approve
- python3 {scripts_dir}/respond_to_runner.py VALIDATION_FAILED --node <id> --feedback <text>  # Reject
- python3 {scripts_dir}/respond_to_runner.py INPUT_RESPONSE --node <id> --response <text>     # Decide
- python3 {scripts_dir}/respond_to_runner.py GUIDANCE --node <id> --message <text>            # Guide
- python3 {scripts_dir}/respond_to_runner.py KILL_ORCHESTRATOR --node <id> --reason <text>    # Abort
- python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue <text>   # Escalate
- python3 {scripts_dir}/runner.py --spawn --node <id> --prd <prd_ref> [--acceptance <text>] [--bead-id <id>] --mode sdk{target_dir_flag} --dot-file {dot_path}  # Launch runner (SDK mode)
- python3 {scripts_dir}/runner.py --spawn --node <id> --prd <prd_ref> [--acceptance <text>] [--bead-id <id>] --mode tmux{target_dir_flag} --dot-file {dot_path}  # Launch runner (tmux interactive mode)

## Pipeline Execution Flow

### Phase 1: Initialize
1. Parse the DOT file:
   python3 {scripts_dir}/cli.py parse {dot_path} --output json
2. Validate the pipeline:
   python3 {scripts_dir}/cli.py validate {dot_path} --output json
3. Get current status:
   python3 {scripts_dir}/cli.py status {dot_path} --json

### Phase 2a: Dispatch Research Nodes (BEFORE codergen)
4a. Find ready research nodes:
    python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json
    Filter output for nodes with handler="research".
4b. For each ready research node:
   a. Transition to active:
      python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
   b. Save checkpoint:
      python3 {scripts_dir}/cli.py checkpoint save {dot_path}
   c. Run research agent (synchronous — completes in seconds):
      python3 {scripts_dir}/run_research.py --node <node_id> --prd <prd_ref> \
          --solution-design <solution_design_attr> --target-dir {target_dir} \
          --frameworks <research_queries_attr> \
          --prd-path <prd_path_attr if present>
   d. Parse the JSON output from stdout
   e. If status=ok and sd_updated=true:
      - The SD has been updated with validated patterns
      - Transition research node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
      - Log: "Research validated N frameworks, updated SD at <sd_path>"
   f. If status=ok and sd_updated=false:
      - SD was already current — no changes needed
      - Transition research node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
   g. If status=error:
      - Transition to failed:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> failed
      - Escalate: python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Research failed for <node_id>: <error>"

Research nodes are dispatched BEFORE codergen nodes. The downstream codergen node's dependency
on the research node is enforced by DOT edges — it won't appear in --deps-met until research
is validated.

### Phase 2a.5: Dispatch Refine Nodes (AFTER research, BEFORE codergen)
4c. Find ready refine nodes:
    python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json
    Filter output for nodes with handler="refine".
4d. For each ready refine node:
   a. Transition to active:
      python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
   b. Save checkpoint:
      python3 {scripts_dir}/cli.py checkpoint save {dot_path}
   c. Run refine agent (synchronous — uses Sonnet, takes ~30-60s):
      python3 {scripts_dir}/run_refine.py --node <node_id> --prd <prd_ref> \
          --solution-design <solution_design_attr> --target-dir {target_dir} \
          --evidence-path <evidence_path_attr> \
          --prd-path <prd_path_attr if present>
   d. Parse the JSON output from stdout
   e. If status=ok and sd_updated=true:
      - The SD has been rewritten with research findings as first-class content
      - All inline research annotations have been removed
      - Transition refine node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
      - Log: "Refine completed: rewrote N sections, patched M sections, removed K annotations"
   f. If status=ok and sd_updated=false:
      - SD needed no refinement beyond what research already did
      - Transition refine node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      - Save checkpoint
   g. If status=error:
      - Transition to failed:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> failed
      - Escalate: python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Refine failed for <node_id>: <error>"

Refine nodes run AFTER research and BEFORE codergen. They transform inline research
annotations into production-quality SD content. The downstream codergen node's dependency
on the refine node is enforced by DOT edges — it won't appear in --deps-met until refine
is validated.

### Phase 2b: Dispatch Ready Codergen Nodes
4. Find ready nodes (pending + dependencies met):
   python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json
5. For each ready codergen node:
   a. Transition to active:
      python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
   b. Save checkpoint:
      python3 {scripts_dir}/cli.py checkpoint save {dot_path}
   c. Spawn Runner:
      python3 {scripts_dir}/runner.py --spawn --node <node_id> --prd <prd_ref> --acceptance "<ac>" --bead-id <bead_id> --solution-design <solution_design_attr> --mode sdk{target_dir_flag} --dot-file {dot_path}
      Note: Extract solution_design_attr from the node's "solution_design" attribute in the parsed DOT JSON.
      If the node has no solution_design attribute, omit --solution-design entirely.
6. For each ready wait.human node:
   a. Determine if you can validate autonomously (technical gate) or need human (business/manual gate)
   b. If autonomous: transition directly to validated after reviewing acceptance criteria
   c. If human needed: escalate to Terminal

### Phase 3: Wait for Runner Completion (PID polling)
7. After spawning a runner, parse runner_pid from the JSON output of the spawn command.
8. Poll until the runner process exits (check every 30 seconds):
   ```bash
   while ps -p <runner_pid> > /dev/null 2>&1; do
       sleep 30
   done
   ```
   You may also check status mid-poll for progress logging:
   python3 {scripts_dir}/cli.py status {dot_path} --json

9. Once the PID exits, check the node status:
   python3 {scripts_dir}/cli.py status {dot_path} --json

10. Handle based on node status:

    NODE IS impl_complete (runner finished successfully):
    - The runner completed and transitioned the node.
    - Validate against acceptance criteria from the DOT node attributes.
    - If PASSING:
      * Transition node to validated:
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> validated
      * Save checkpoint:
        python3 {scripts_dir}/cli.py checkpoint save {dot_path}
    - If FAILING (acceptance criteria not met):
      * Check retry count (max {max_retries} retries per node).
      * If retries remain:
        - Transition back to active: python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
        - Re-spawn runner: python3 {scripts_dir}/runner.py --spawn --node <node_id> --prd <prd_ref> --acceptance "<ac>" --bead-id <bead_id> --solution-design <solution_design_attr> --mode sdk{target_dir_flag} --dot-file {dot_path}
        - Return to step 7 (poll new PID)
      * If max retries exceeded: escalate
        python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Node <node_id> failed validation after {max_retries} retries"

    NODE IS failed (runner crashed or reported failure):
    - Check runner stderr log for diagnostics:
      cat {target_dir_flag.strip() or "."}/. claude/attractor/runner-state/*-stderr.log 2>/dev/null | tail -50
    - Check retry count (max {max_retries} retries per node).
    - If retries remain:
      * Transition node to active (failed -> active is a valid transition):
        python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
      * Re-spawn runner: python3 {scripts_dir}/runner.py --spawn --node <node_id> --prd <prd_ref> --acceptance "<ac>" --bead-id <bead_id> --solution-design <solution_design_attr> --mode sdk{target_dir_flag} --dot-file {dot_path}
      * Return to step 7 (poll new PID)
    - If max retries exceeded: escalate
      python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Runner failed for <node_id> after {max_retries} retries"

    NODE IS still active (PID died without updating node state):
    - The runner crashed before it could transition the node.
    - Check runner stderr log:
      cat {target_dir_flag.strip() or "."}/. claude/attractor/runner-state/*-stderr.log 2>/dev/null | tail -50
    - Treat as "NODE IS failed" above (retry or escalate).

11. After validating a node, check for newly unblocked nodes:
    python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json
    Dispatch any newly ready nodes (return to Phase 2b).

12. Pipeline complete when all non-start/exit nodes are validated:
    python3 {scripts_dir}/cli.py status {dot_path} --json
    If summary shows all nodes "validated" → save final checkpoint and exit successfully.

### Phase 4: Check Pipeline Progress
10. After handling the signal, check for new ready nodes (go to Phase 2)
11. If all nodes are validated:
    - Signal completion to Layer 0: python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "PIPELINE_COMPLETE: all nodes validated"
12. If pipeline is stuck (no ready nodes, no active nodes):
    - Escalate to Terminal: python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "PIPELINE_STUCK: no progress possible"

## Retry Tracking
Track retries per node in memory (dict). When a node exceeds {max_retries} retries, do not
spawn again — escalate to Terminal with full context.

## Hook Phase Tracking
Update pipeline phase at lifecycle transitions:

When beginning validation of a pipeline node:
```bash
python3 {scripts_dir}/hook_manager.py update-phase guardian {pipeline_id} validating
```

After successful merge of a node:
```bash
python3 {scripts_dir}/hook_manager.py update-phase guardian {pipeline_id} merged
```

## Important Rules
- NEVER use Edit or Write tools — you are a coordinator, not an implementer
- NEVER guess at node status — always read from the DOT file via CLI
- ALWAYS checkpoint after every status transition
- When in doubt about a validation decision, err on the side of VALIDATION_FAILED with specific feedback
- Escalate to Terminal (Layer 0) only when you cannot resolve without human input
"""


def build_initial_prompt(
    dot_path: str,
    pipeline_id: str,
    scripts_dir: str,
    target_dir: str = "",
) -> str:
    """Return the first user message sent to Claude to start the pipeline execution loop.

    Args:
        dot_path: Absolute path to the pipeline DOT file.
        pipeline_id: Unique pipeline identifier string.
        scripts_dir: Absolute path to the attractor scripts directory.
        target_dir: Target implementation repo directory.

    Returns:
        Formatted initial prompt string.
    """
    with logfire.span("guardian.build_initial_prompt", pipeline_id=pipeline_id):
        target_dir_line = f"Target directory: {target_dir}\n" if target_dir else ""
        return (
            f"You are the Headless Guardian for pipeline '{pipeline_id}'.\n\n"
            f"Pipeline DOT file: {dot_path}\n"
            f"Scripts directory: {scripts_dir}\n"
            f"{target_dir_line}\n"
            f"Begin by:\n"
            f"1. Parsing the pipeline to understand the full graph\n"
            f"2. Validating the pipeline structure\n"
            f"3. Getting current node statuses\n\n"
            f"Then proceed with Phase 2 (dispatch ready nodes) of the execution flow.\n\n"
            f"If the pipeline is already partially complete (some nodes are already validated),\n"
            f"skip those nodes and continue from the current state.\n"
        )


def build_options(
    system_prompt: str,
    cwd: str,
    model: str,
    max_turns: int,
) -> Any:
    """Construct a ClaudeCodeOptions instance for the Guardian agent.

    The Guardian is restricted to Bash only — it must not call Edit/Write/etc.
    CLAUDECODE is overridden to an empty string to suppress nested session
    warnings (the authoritative fix is in runner.py spawn mode using Popen).

    Args:
        system_prompt: Pipeline execution instructions for Claude.
        cwd: Working directory for the agent (project root).
        model: Claude model identifier.
        max_turns: Maximum turns before the SDK stops the conversation.

    Returns:
        Configured ClaudeCodeOptions instance.
    """
    with logfire.span("guardian.build_options", model=model):
        from claude_code_sdk import ClaudeCodeOptions

        return ClaudeCodeOptions(
            allowed_tools=["Bash", "Read", "Write", "Edit", "Glob"],
            system_prompt=system_prompt,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            # Suppress CLAUDECODE env var to avoid nested-session conflicts.
            # Definitive fix (subprocess.Popen with cleaned env) is in runner.py spawn mode.
            env={"CLAUDECODE": ""},
        )


def resolve_scripts_dir() -> str:
    """Return the absolute path to the attractor scripts directory.

    Resolution order:
    1. The directory containing this file (guardian.py is inside attractor/).
    2. Falls back to current working directory if for some reason _THIS_DIR is unavailable.

    Returns:
        Absolute path string.
    """
    return _THIS_DIR


def build_env_config() -> dict[str, str]:
    """Return environment overrides that suppress the CLAUDECODE variable.

    We cannot *delete* env keys via ClaudeCodeOptions.env (it only adds/overrides),
    so we override CLAUDECODE to an empty string. The authoritative fix is in
    runner.py (spawn mode) which uses subprocess.Popen with a fully cleaned environment.

    Returns:
        Dict of env var overrides to pass to ClaudeCodeOptions.
    """
    return {"CLAUDECODE": ""}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for guardian.py.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="guardian.py",
        description=(
            "Guardian Agent (Layers 0/1): launch Guardian agents and "
            "monitor pipeline execution via claude_code_sdk."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python guardian.py --dot /path/to/pipeline.dot --pipeline-id my-pipeline

  python guardian.py --dot /path/to/pipeline.dot --pipeline-id my-pipeline \\
      --project-root /my/project --max-turns 300 --signal-timeout 300 --dry-run

  python guardian.py --multi /path/to/configs.json
        """,
    )

    # Mutually exclusive groups: single-launch vs multi-launch
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dot", dest="dot",
                       help="Path to pipeline .dot file (single guardian mode)")
    group.add_argument("--multi", dest="multi",
                       help="Path to JSON file containing a list of pipeline configs")

    parser.add_argument("--pipeline-id", dest="pipeline_id", default=None,
                        help="Unique pipeline identifier (required with --dot)")
    parser.add_argument("--project-root", default=None, dest="project_root",
                        help="Working directory for the agent (default: cwd)")
    parser.add_argument("--target-dir", default=None, dest="target_dir",
                        help="Target implementation repo directory (overrides DOT graph attr)")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        dest="max_turns",
                        help=f"Max SDK turns (default: {DEFAULT_MAX_TURNS})")
    _default_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    parser.add_argument("--model", default=_default_model,
                        help=f"Claude model to use (default: {_default_model})")
    parser.add_argument("--signals-dir", default=None, dest="signals_dir",
                        help="Override signals directory path")
    parser.add_argument("--signal-timeout", type=float, default=DEFAULT_SIGNAL_TIMEOUT,
                        dest="signal_timeout",
                        help=f"Seconds to wait per signal wait cycle (default: {DEFAULT_SIGNAL_TIMEOUT})")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                        dest="max_retries",
                        help=f"Max retries per node before escalating (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Log configuration without invoking the SDK (for testing)")

    ns = parser.parse_args(argv)

    # Validate --dot requires --pipeline-id
    if ns.dot is not None and ns.pipeline_id is None:
        parser.error("--pipeline-id is required when using --dot")

    return ns


# ---------------------------------------------------------------------------
# Async agent runner
# ---------------------------------------------------------------------------


async def _run_agent(initial_prompt: str, options: Any) -> None:
    """Stream messages from the claude_code_sdk query and log them.

    Each SDK message type is logged to Logfire as a structured event so that
    tool calls, assistant text, tool results, and session completion are all
    visible in the Logfire dashboard.

    Args:
        initial_prompt: The first user message to send to Claude.
        options: Configured ClaudeCodeOptions instance.
    """
    import time as _time

    from claude_code_sdk import (
        query,
        AssistantMessage,
        UserMessage,
        ResultMessage,
        TextBlock,
        ThinkingBlock,
        ToolUseBlock,
        ToolResultBlock,
    )

    turn_count = 0
    tool_call_count = 0
    start_time = _time.time()

    with logfire.span("guardian.run_agent") as agent_span:
        async for message in query(prompt=initial_prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn_count += 1
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_preview = block.text[:300] if block.text else ""
                        logfire.info(
                            "guardian.assistant_text",
                            turn=turn_count,
                            text_length=len(block.text) if block.text else 0,
                            text_preview=text_preview,
                        )
                        print(f"[Guardian] {block.text}", flush=True)

                    elif isinstance(block, ToolUseBlock):
                        tool_call_count += 1
                        input_preview = json.dumps(block.input)[:500]
                        logfire.info(
                            "guardian.tool_use",
                            tool_name=block.name,
                            tool_use_id=block.id,
                            tool_input_preview=input_preview,
                            turn=turn_count,
                            tool_call_number=tool_call_count,
                        )
                        print(f"[Guardian tool] {block.name}: {input_preview[:200]}", flush=True)

                    elif isinstance(block, ThinkingBlock):
                        logfire.info(
                            "guardian.thinking",
                            turn=turn_count,
                            thinking_length=len(block.thinking) if block.thinking else 0,
                            thinking_preview=(block.thinking or "")[:200],
                        )

            elif isinstance(message, UserMessage):
                # UserMessage carries tool results back from tool execution
                if isinstance(message.content, list):
                    for block in message.content:
                        if isinstance(block, ToolResultBlock):
                            content_preview = ""
                            content_length = 0
                            if isinstance(block.content, str):
                                content_preview = block.content[:500]
                                content_length = len(block.content)
                            elif isinstance(block.content, list):
                                content_preview = json.dumps(block.content)[:500]
                                content_length = len(json.dumps(block.content))
                            logfire.info(
                                "guardian.tool_result",
                                tool_use_id=block.tool_use_id,
                                is_error=block.is_error or False,
                                content_length=content_length,
                                content_preview=content_preview,
                                turn=turn_count,
                            )

            elif isinstance(message, ResultMessage):
                elapsed = _time.time() - start_time
                logfire.info(
                    "guardian.result",
                    session_id=message.session_id,
                    is_error=message.is_error,
                    num_turns=message.num_turns,
                    duration_ms=message.duration_ms,
                    duration_api_ms=message.duration_api_ms,
                    total_cost_usd=message.total_cost_usd,
                    usage=message.usage,
                    result_preview=(message.result or "")[:300],
                    wall_time_seconds=round(elapsed, 2),
                    total_tool_calls=tool_call_count,
                )
                print(f"[Guardian done] turns={message.num_turns} cost=${message.total_cost_usd} tools={tool_call_count}", flush=True)


# ---------------------------------------------------------------------------
# Core public API (launch/monitor functions)
# ---------------------------------------------------------------------------


async def _launch_guardian_async(
    dot_path: str,
    project_root: str,
    pipeline_id: str,
    *,
    model: str = "claude-sonnet-4-6",
    max_turns: int = DEFAULT_MAX_TURNS,
    signal_timeout: float = DEFAULT_SIGNAL_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    signals_dir: Optional[str] = None,
    dry_run: bool = False,
    target_dir: str = "",
) -> dict[str, Any]:
    """Async implementation of launch_guardian().

    Args:
        dot_path: Absolute path to the pipeline DOT file.
        project_root: Working directory for the agent.
        pipeline_id: Unique pipeline identifier string.
        model: Claude model identifier.
        max_turns: Maximum SDK turns.
        signal_timeout: Seconds to wait per signal wait cycle.
        max_retries: Maximum retries per node before escalation.
        signals_dir: Override signals directory path.
        dry_run: If True, return config dict without invoking SDK.
        target_dir: Target implementation repo directory.

    Returns:
        Dict with status and pipeline metadata.
    """
    scripts_dir = resolve_scripts_dir()

    system_prompt = build_system_prompt(
        dot_path=dot_path,
        pipeline_id=pipeline_id,
        scripts_dir=scripts_dir,
        signal_timeout=signal_timeout,
        max_retries=max_retries,
        target_dir=target_dir,
    )

    initial_prompt = build_initial_prompt(
        dot_path=dot_path,
        pipeline_id=pipeline_id,
        scripts_dir=scripts_dir,
        target_dir=target_dir,
    )

    config: dict[str, Any] = {
        "dry_run": dry_run,
        "dot_path": dot_path,
        "pipeline_id": pipeline_id,
        "model": model,
        "max_turns": max_turns,
        "signal_timeout": signal_timeout,
        "max_retries": max_retries,
        "project_root": project_root,
        "signals_dir": signals_dir,
        "scripts_dir": scripts_dir,
        "target_dir": target_dir,
        "system_prompt_length": len(system_prompt),
        "initial_prompt_length": len(initial_prompt),
    }

    if dry_run:
        return config

    options = build_options(
        system_prompt=system_prompt,
        cwd=project_root,
        model=model,
        max_turns=max_turns,
    )

    try:
        await _run_agent(initial_prompt, options)
        return {
            "status": "ok",
            "pipeline_id": pipeline_id,
            "dot_path": dot_path,
        }
    except Exception as exc:
        return {
            "status": "error",
            "pipeline_id": pipeline_id,
            "dot_path": dot_path,
            "error": str(exc),
        }


def launch_guardian(
    dot_path: str,
    project_root: str,
    pipeline_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Launch a single Guardian agent via the Agent SDK.

    Constructs ClaudeCodeOptions with allowed_tools=["Bash"] and
    env={"CLAUDECODE": ""}, then streams the SDK conversation until
    the Guardian completes or errors.

    Args:
        dot_path: Path to the pipeline .dot file.
        project_root: Working directory for the agent.
        pipeline_id: Unique pipeline identifier string.
        **kwargs: Optional overrides — model, max_turns, signal_timeout,
                  max_retries, signals_dir, dry_run.

    Returns:
        Dict with ``status`` ("ok" | "error"), ``pipeline_id``, ``dot_path``,
        and optionally ``error`` on failure.  In dry_run mode returns the
        full config dict with ``dry_run: True``.
    """
    dot_path = os.path.abspath(dot_path)
    return asyncio.run(
        _launch_guardian_async(
            dot_path=dot_path,
            project_root=project_root,
            pipeline_id=pipeline_id,
            **kwargs,
        )
    )


async def _launch_multiple_async(
    pipeline_configs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Async implementation of launch_multiple_guardians().

    Args:
        pipeline_configs: List of config dicts, each with at minimum
            dot_path, project_root, pipeline_id.

    Returns:
        List of result dicts, one per config.
    """
    tasks = [
        _launch_guardian_async(
            dot_path=os.path.abspath(cfg["dot_path"]),
            project_root=cfg.get("project_root", os.getcwd()),
            pipeline_id=cfg["pipeline_id"],
            model=cfg.get("model", "claude-sonnet-4-6"),
            max_turns=cfg.get("max_turns", DEFAULT_MAX_TURNS),
            signal_timeout=cfg.get("signal_timeout", DEFAULT_SIGNAL_TIMEOUT),
            max_retries=cfg.get("max_retries", DEFAULT_MAX_RETRIES),
            signals_dir=cfg.get("signals_dir"),
            dry_run=cfg.get("dry_run", False),
            target_dir=cfg.get("target_dir", ""),
        )
        for cfg in pipeline_configs
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Normalise exceptions to error dicts so callers receive a uniform type.
    output: list[dict[str, Any]] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            cfg = pipeline_configs[i]
            output.append({
                "status": "error",
                "pipeline_id": cfg.get("pipeline_id", "unknown"),
                "dot_path": cfg.get("dot_path", "unknown"),
                "error": str(result),
            })
        else:
            output.append(result)  # type: ignore[arg-type]

    return output


def launch_multiple_guardians(
    pipeline_configs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Launch multiple Guardian agents concurrently.

    Uses asyncio.gather with return_exceptions=True so an individual
    failure does not abort the remaining launches.

    Args:
        pipeline_configs: List of config dicts, each with:
            - dot_path (str, required)
            - project_root (str, required)
            - pipeline_id (str, required)
            - model, max_turns, signal_timeout, max_retries,
              signals_dir, dry_run (all optional)

    Returns:
        List of result dicts (one per config).  Any individual failure
        is represented as ``{"status": "error", ...}`` rather than
        raising an exception.
    """
    return asyncio.run(_launch_multiple_async(pipeline_configs))


def monitor_guardian(
    guardian_process: Any,
    dot_path: str,
    signals_dir: Optional[str] = None,
    *,
    timeout: float = DEFAULT_MONITOR_TIMEOUT,
    poll_interval: float = 5.0,
) -> dict[str, Any]:
    """Watch for terminal-targeted signals from a running Guardian.

    Polls the signals directory for signals with target="terminal" until
    either a PIPELINE_COMPLETE or terminal-escalation signal arrives, or
    the timeout is reached.

    Args:
        guardian_process: The guardian process handle (may be None for
            signal-only monitoring).  Currently unused but reserved for
            future process health checks.
        dot_path: Absolute path to the pipeline DOT file (used for
            metadata in returned dicts).
        signals_dir: Override the default signals directory.
        timeout: Maximum seconds to wait for a terminal signal.
        poll_interval: Seconds between directory polls.

    Returns:
        Dict with ``status`` ("complete" | "escalation" | "timeout") and
        the received ``signal_data`` (if any).
    """
    try:
        signal_data = wait_for_signal(
            target_layer="terminal",
            timeout=timeout,
            signals_dir=signals_dir,
            poll_interval=poll_interval,
        )
    except TimeoutError:
        return {
            "status": "timeout",
            "dot_path": dot_path,
            "signal_data": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "dot_path": dot_path,
            "error": str(exc),
            "signal_data": None,
        }

    signal_type = signal_data.get("signal_type", "")

    if "PIPELINE_COMPLETE" in signal_type or (
        signal_data.get("payload", {}).get("issue", "").startswith("PIPELINE_COMPLETE")
    ):
        return handle_pipeline_complete(signal_data, dot_path)

    if "VALIDATION_COMPLETE" in signal_type:
        return handle_validation_complete(signal_data, dot_path)

    # Any other terminal-targeted signal is treated as an escalation.
    return handle_escalation(signal_data)


def handle_validation_complete(
    signal_data: dict[str, Any],
    dot_path: str,
) -> dict[str, Any]:
    """Handle VALIDATION_COMPLETE signal from a Runner via terminal.

    Args:
        signal_data: Parsed signal dict from the Runner.
        dot_path: Absolute path to the pipeline DOT file.

    Returns:
        Dict with validation complete details.
    """
    payload = signal_data.get("payload", {})
    return {
        "status": "validation_complete",
        "node_id": payload.get("node_id", "unknown"),
        "pipeline_id": payload.get("pipeline_id", ""),
        "dot_path": dot_path,
        "summary": payload.get("summary", ""),
        "timestamp": signal_data.get("timestamp"),
        "source": signal_data.get("source"),
        "raw": signal_data,
    }


def handle_escalation(signal_data: dict[str, Any]) -> dict[str, Any]:
    """Forward a Guardian escalation signal to the terminal user.

    Reads the escalation signal payload and formats it for terminal
    display as a JSON dict.

    Args:
        signal_data: Parsed signal dict with fields source, target,
            signal_type, timestamp, payload.

    Returns:
        Dict with escalation details formatted for terminal display:
        ``{"status": "escalation", "signal_type": ..., "pipeline_id": ...,
           "issue": ..., "options": ..., "timestamp": ..., "raw": ...}``
    """
    payload = signal_data.get("payload", {})

    result: dict[str, Any] = {
        "status": "escalation",
        "signal_type": signal_data.get("signal_type", "ESCALATE"),
        "pipeline_id": payload.get("pipeline_id", "unknown"),
        "issue": payload.get("issue", "No issue description provided"),
        "options": payload.get("options"),
        "timestamp": signal_data.get("timestamp"),
        "source": signal_data.get("source"),
        "raw": signal_data,
    }

    return result


def handle_pipeline_complete(
    signal_data: dict[str, Any],
    dot_path: str,
) -> dict[str, Any]:
    """Finalise a pipeline after receiving PIPELINE_COMPLETE signal.

    Reads the PIPELINE_COMPLETE signal payload and produces a completion
    summary with node statuses.

    Args:
        signal_data: Parsed signal dict from the Guardian.
        dot_path: Absolute path to the pipeline DOT file.

    Returns:
        Dict with completion summary:
        ``{"status": "complete", "pipeline_id": ..., "dot_path": ...,
           "node_statuses": ..., "timestamp": ..., "raw": ...}``
    """
    payload = signal_data.get("payload", {})

    # Extract node statuses from payload if available (Guardian may include them).
    node_statuses = payload.get("node_statuses", {})

    # Parse issue string to extract structured data if node_statuses not present.
    issue = payload.get("issue", "")
    if not node_statuses and issue:
        node_statuses = {"summary": issue}

    result: dict[str, Any] = {
        "status": "complete",
        "pipeline_id": payload.get("pipeline_id", "unknown"),
        "dot_path": dot_path,
        "node_statuses": node_statuses,
        "issue": issue,
        "timestamp": signal_data.get("timestamp"),
        "source": signal_data.get("source"),
        "raw": signal_data,
    }

    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and launch one or multiple Guardian agents."""
    # Load attractor-specific API credentials before any SDK call.
    # claude_code_sdk.query() reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL from
    # os.environ, so this must happen before argparse or SDK initialisation.
    os.environ.update(load_attractor_env())

    args = parse_args(argv)

    # -----------------------------------------------------------------------
    # Multi-launch mode: --multi <configs.json>
    # -----------------------------------------------------------------------
    if args.multi is not None:
        multi_path = os.path.abspath(args.multi)
        try:
            with open(multi_path, encoding="utf-8") as fh:
                configs = json.load(fh)
        except FileNotFoundError:
            print(json.dumps({
                "status": "error",
                "message": f"Config file not found: {multi_path}",
            }))
            sys.exit(1)
        except json.JSONDecodeError as exc:
            print(json.dumps({
                "status": "error",
                "message": f"Invalid JSON in {multi_path}: {exc}",
            }))
            sys.exit(1)

        if not isinstance(configs, list):
            print(json.dumps({
                "status": "error",
                "message": "--multi JSON file must contain a list of config dicts",
            }))
            sys.exit(1)

        # Propagate top-level dry_run flag to all configs that don't set it.
        if args.dry_run:
            for cfg in configs:
                cfg.setdefault("dry_run", True)

        results = launch_multiple_guardians(configs)
        print(json.dumps(results, indent=2))
        return

    # -----------------------------------------------------------------------
    # Single guardian mode: --dot + --pipeline-id
    # -----------------------------------------------------------------------
    dot_path = os.path.abspath(args.dot)
    cwd = args.project_root or os.getcwd()
    scripts_dir = resolve_scripts_dir()

    # Read target_dir from DOT graph_attrs (CLI arg overrides DOT value).
    graph_target_dir = ""
    if os.path.exists(dot_path):
        from cobuilder.attractor.parser import parse_dot  # noqa: PLC0415 (lazy import — intentional)
        with open(dot_path, encoding="utf-8") as _fh:
            dot_data = parse_dot(_fh.read())
        graph_target_dir = dot_data.get("graph_attrs", {}).get("target_dir", "")
    target_dir = args.target_dir or graph_target_dir
    if not target_dir:
        print(json.dumps({
            "status": "error",
            "message": "target_dir is required: set in DOT graph attrs or pass --target-dir",
        }))
        sys.exit(1)

    system_prompt = build_system_prompt(
        dot_path=dot_path,
        pipeline_id=args.pipeline_id,
        scripts_dir=scripts_dir,
        signal_timeout=args.signal_timeout,
        max_retries=args.max_retries,
        target_dir=target_dir,
    )

    initial_prompt = build_initial_prompt(
        dot_path=dot_path,
        pipeline_id=args.pipeline_id,
        scripts_dir=scripts_dir,
        target_dir=target_dir,
    )

    # Dry-run: log config and exit without calling the SDK.
    if args.dry_run:
        config: dict[str, Any] = {
            "dry_run": True,
            "dot_path": dot_path,
            "pipeline_id": args.pipeline_id,
            "model": args.model,
            "max_turns": args.max_turns,
            "signal_timeout": args.signal_timeout,
            "max_retries": args.max_retries,
            "project_root": cwd,
            "signals_dir": args.signals_dir,
            "target_dir": target_dir,
            "scripts_dir": scripts_dir,
            "system_prompt_length": len(system_prompt),
            "initial_prompt_length": len(initial_prompt),
        }
        print(json.dumps(config, indent=2))
        sys.exit(0)

    # Register Layer 0/1 (guardian) identity before starting the agent loop.
    identity_registry.create_identity(
        role="launch",
        name="guardian",
        session_id="launch-guardian",
        worktree=os.getcwd(),
    )

    # Live run: launch the Guardian agent with retry loop.
    # If the guardian SDK session crashes or times out, retry up to max_retries times.
    guardian_retries = args.max_retries
    attempt = 0
    while True:
        attempt += 1
        print(f"[Layer 0] Launching guardian (attempt {attempt}/{guardian_retries + 1})", flush=True)
        result = launch_guardian(
            dot_path=dot_path,
            project_root=cwd,
            pipeline_id=args.pipeline_id,
            model=args.model,
            max_turns=args.max_turns,
            signal_timeout=args.signal_timeout,
            max_retries=args.max_retries,
            signals_dir=args.signals_dir,
            target_dir=target_dir,
        )
        print(json.dumps(result, indent=2))

        status = result.get("status", "error")
        if status == "ok":
            break  # Guardian completed successfully

        # Check if we should retry
        if attempt > guardian_retries:
            print(f"[Layer 0] Guardian failed after {attempt} attempts. Giving up.", file=sys.stderr, flush=True)
            sys.exit(1)

        # Retry on timeout or error (guardian SDK crash)
        print(f"[Layer 0] Guardian returned status={status}. Retrying in 5s...", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
