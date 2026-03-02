#!/usr/bin/env python3
"""Guardian Agent (Layer 1) — Guardian Architecture.

Invokes Claude via the claude_code_sdk to drive pipeline execution autonomously:
reading the DOT graph, spawning Runners for each codergen node, handling signals
from Runners, and transitioning node statuses to completion.

Architecture:
    guardian_agent.py (Python process)
        │
        ├── Parse CLI args
        ├── build_system_prompt()    → pipeline execution instructions for Claude
        ├── build_initial_prompt()   → first user message with pipeline context
        ├── build_options()          → ClaudeCodeOptions (Bash only, max_turns, model)
        └── asyncio.run(_run_agent())
               │
               └── async for message in query(initial_prompt, options=options):
                       # Claude uses Bash to run CLI tools in scripts_dir
                       pass

CLAUDECODE environment note:
    The Guardian may be launched from inside a Claude Code session. To avoid
    nested-session conflicts, we pass env={"CLAUDECODE": ""} as a workaround
    to suppress the variable. The definitive fix (subprocess.Popen with a
    cleaned env) lives in spawn_runner.py and will be implemented in a later epic.

Usage:
    python guardian_agent.py \\
        --dot <path_to_pipeline.dot> \\
        --pipeline-id <id> \\
        [--project-root <path>] \\
        [--max-turns <n>] \\
        [--model <model_id>] \\
        [--signals-dir <path>] \\
        [--signal-timeout <seconds>] \\
        [--max-retries <n>] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure this file's directory is importable regardless of invocation CWD.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import identity_registry

# Import merge_queue so it is available in the Guardian process for signal handling
try:
    import merge_queue  # noqa: F401  (imported for side-effects / availability)
except ImportError:
    pass  # merge_queue not available in test-only environments

# ---------------------------------------------------------------------------
# Logfire instrumentation (required)
# ---------------------------------------------------------------------------
import logfire

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
    scrubbing=logfire.ScrubbingOptions(callback=lambda m: m.value),
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TURNS = 200          # more turns than runner; guardian runs longer
DEFAULT_SIGNAL_TIMEOUT = 600     # 10 minutes per wait cycle
DEFAULT_MAX_RETRIES = 3          # max retries per node before escalating


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
- python3 {scripts_dir}/spawn_runner.py --node <id> --prd <prd_ref> [--acceptance <text>] [--bead-id <id>] --mode sdk{target_dir_flag}  # Launch runner

## Pipeline Execution Flow

### Phase 1: Initialize
1. Parse the DOT file:
   python3 {scripts_dir}/cli.py parse {dot_path} --output json
2. Validate the pipeline:
   python3 {scripts_dir}/cli.py validate {dot_path} --output json
3. Get current status:
   python3 {scripts_dir}/cli.py status {dot_path} --json

### Phase 2: Dispatch Ready Nodes
4. Find ready nodes (pending + dependencies met):
   python3 {scripts_dir}/cli.py status {dot_path} --filter=pending --deps-met --json
5. For each ready codergen node:
   a. Transition to active:
      python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> active
   b. Save checkpoint:
      python3 {scripts_dir}/cli.py checkpoint save {dot_path}
   c. Spawn Runner:
      python3 {scripts_dir}/spawn_runner.py --node <node_id> --prd <prd_ref> --acceptance "<ac>" --bead-id <bead_id> --mode sdk{target_dir_flag}
6. For each ready wait.human node:
   a. Determine if you can validate autonomously (technical gate) or need human (business/manual gate)
   b. If autonomous: transition directly to validated after reviewing acceptance criteria
   c. If human needed: escalate to Terminal

### Phase 3: Wait and Handle Signals
7. After spawning all ready runners, wait for a signal:
   python3 {scripts_dir}/wait_for_signal.py --target guardian --timeout {signal_timeout}
8. Parse the signal to determine node and signal type
9. Handle based on signal type:

   NEEDS_REVIEW (node implementation complete, needs validation):
   - Review the evidence provided in the signal
   - Check the DOT node's acceptance criteria
   - Make a validation decision using your intelligence
   - If PASSING:
     * Transition node to impl_complete
     * Transition node to validated
     * Save checkpoint
     * Respond: python3 {scripts_dir}/respond_to_runner.py VALIDATION_PASSED --node <id>
   - If FAILING:
     * Check retry count (max {max_retries} retries per node)
     * If retries remain: python3 {scripts_dir}/respond_to_runner.py VALIDATION_FAILED --node <id> --feedback "<specific feedback>"
     * If max retries exceeded: escalate to Terminal

   NEEDS_INPUT (orchestrator needs a decision):
   - Read the question from the signal payload
   - Use your judgment to make the decision (you ARE the "user" for Layer 3)
   - Respond: python3 {scripts_dir}/respond_to_runner.py INPUT_RESPONSE --node <id> --response "<decision>"

   VIOLATION (orchestrator violated guard rails):
   - Log the violation
   - Decide: warn (send GUIDANCE) or abort (send KILL_ORCHESTRATOR)
   - Minor violation: python3 {scripts_dir}/respond_to_runner.py GUIDANCE --node <id> --message "Please delegate, do not implement directly"
   - Major violation: python3 {scripts_dir}/respond_to_runner.py KILL_ORCHESTRATOR --node <id> --reason "<reason>"

   ORCHESTRATOR_STUCK (no progress):
   - Review the last output provided in signal
   - Send targeted guidance: python3 {scripts_dir}/respond_to_runner.py GUIDANCE --node <id> --message "<specific unstick advice>"

   ORCHESTRATOR_CRASHED (tmux session died):
   - Check if retry is possible
   - If retries remain: re-spawn runner (increment retry count)
   - If max retries exceeded: escalate to Terminal

   NODE_COMPLETE (node finished and committed):
   - Transition node to impl_complete:
     python3 {scripts_dir}/cli.py transition {dot_path} transition <node_id> impl_complete
   - Save checkpoint
   - Respond: python3 {scripts_dir}/respond_to_runner.py VALIDATION_PASSED --node <id>

   RUNNER_EXITED (state machine runner exited without completing):
   - Read payload.mode to understand why: FAILED, MONITOR (unexpected exit mid-cycle)
   - Read payload.reason for human-readable explanation
   - Check payload.node_id against the current pipeline state
   - Determine if retry is safe:
     * If retries remain: re-spawn runner with same parameters
       python3 {scripts_dir}/spawn_runner.py --node <node_id> --prd <prd_ref> --mode sdk --target-dir {target_dir_flag.strip()}
     * If max retries exceeded: escalate to Terminal
       python3 {scripts_dir}/escalate_to_terminal.py --pipeline {pipeline_id} --issue "Runner exited in mode <mode>: <reason>"
   - If mode=FAILED and the node is genuinely failed in the DOT file:
     * Escalate to Terminal immediately with context about what failed

   MERGE_READY (node branch is ready for sequential merge into main):
   - Call the merge queue to process the next pending entry:
     ```python
     import merge_queue, signal_protocol
     result = merge_queue.process_next()
     ```
   - If result["success"] is True and result["entry"] is not None:
     * Write MERGE_COMPLETE signal back to runner:
       signal_protocol.write_signal(
           source="guardian", target="runner",
           signal_type="MERGE_COMPLETE",
           payload={{"node_id": result["entry"]["node_id"],
                    "branch": result["entry"]["branch"],
                    "entry_id": result["entry"]["entry_id"]}},
       )
   - If result["success"] is False:
     * Write MERGE_FAILED signal back to runner:
       signal_protocol.write_signal(
           source="guardian", target="runner",
           signal_type="MERGE_FAILED",
           payload={{"node_id": result["entry"]["node_id"],
                    "branch": result["entry"]["branch"],
                    "error": result["error"]}},
       )
     * Log the failure and escalate if repeated failures occur

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

## Merge Queue Integration
When you receive a MERGE_READY signal from a runner, process the merge queue directly:
```bash
python3 -c "
import sys; sys.path.insert(0, '{scripts_dir}')
from merge_queue import process_next
from signal_protocol import write_signal
import json
result = process_next()
if result.get('success'):
    entry = result.get('entry', {{}})
    write_signal('guardian', 'runner', 'MERGE_COMPLETE', {{'node_id': entry.get('node_id', '')}})
    print('MERGE_COMPLETE: ' + json.dumps(entry))
else:
    entry = result.get('entry', {{}})
    error = result.get('error', 'unknown error')
    write_signal('guardian', 'runner', 'MERGE_FAILED', {{'node_id': entry.get('node_id', ''), 'error': error}})
    print('MERGE_FAILED: ' + error)
"
```

## Identity Scanning
Periodically scan for stale agents using:
  python3 {scripts_dir}/identity_registry.py --find-stale --timeout 300

Stale active agents may indicate crashed orchestrators or runners. Use this
information alongside signal monitoring to decide when to escalate or respawn.

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
    warnings (the authoritative fix is in spawn_runner.py using Popen).

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
            allowed_tools=["Bash"],
            system_prompt=system_prompt,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            # Suppress CLAUDECODE env var to avoid nested-session conflicts.
            # Definitive fix (subprocess.Popen with cleaned env) is in spawn_runner.py.
            env={"CLAUDECODE": ""},
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for guardian_agent.py.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="guardian_agent.py",
        description="Guardian Agent (Layer 1): drives pipeline execution via claude_code_sdk.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python guardian_agent.py --dot /path/to/pipeline.dot --pipeline-id my-pipeline

  python guardian_agent.py --dot /path/to/pipeline.dot --pipeline-id my-pipeline \\
      --project-root /my/project --max-turns 300 --signal-timeout 300 --dry-run
        """,
    )
    parser.add_argument("--dot", required=True,
                        help="Path to pipeline .dot file")
    parser.add_argument("--pipeline-id", required=True, dest="pipeline_id",
                        help="Unique pipeline identifier")
    parser.add_argument("--project-root", default=None, dest="project_root",
                        help="Working directory for the agent (default: cwd)")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        dest="max_turns",
                        help=f"Max SDK turns (default: {DEFAULT_MAX_TURNS})")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help=f"Claude model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--signals-dir", default=None, dest="signals_dir",
                        help="Override signals directory path")
    parser.add_argument("--signal-timeout", type=float, default=DEFAULT_SIGNAL_TIMEOUT,
                        dest="signal_timeout",
                        help=f"Seconds to wait per signal wait cycle (default: {DEFAULT_SIGNAL_TIMEOUT})")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                        dest="max_retries",
                        help=f"Max retries per node before escalating (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Log config without spawning the SDK agent (for testing)")
    parser.add_argument("--target-dir", required=True, dest="target_dir",
                        help="Target implementation repo directory")

    return parser.parse_args(argv)


def resolve_scripts_dir() -> str:
    """Return the absolute path to the attractor scripts directory.

    Resolution order:
    1. The directory containing this file (guardian_agent.py is inside attractor/).
    2. Falls back to current working directory if for some reason _THIS_DIR is unavailable.

    Returns:
        Absolute path string.
    """
    return _THIS_DIR


def build_env_config() -> dict[str, str]:
    """Return environment overrides that suppress the CLAUDECODE variable.

    We cannot *delete* env keys via ClaudeCodeOptions.env (it only adds/overrides),
    so we override CLAUDECODE to an empty string. The authoritative fix is in
    spawn_runner.py which uses subprocess.Popen with a fully cleaned environment.

    Returns:
        Dict of env var overrides to pass to ClaudeCodeOptions.
    """
    return {"CLAUDECODE": ""}


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
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse arguments, build prompts/options, and run the Guardian agent."""
    args = parse_args(argv)

    with logfire.span("guardian.main", pipeline_id=args.pipeline_id, model=args.model, dry_run=args.dry_run):
        dot_path = os.path.abspath(args.dot)
        # project_root defaults to cwd (agent process dir); target_dir is mandatory
        cwd = args.project_root or os.getcwd()
        scripts_dir = resolve_scripts_dir()

        system_prompt = build_system_prompt(
            dot_path=dot_path,
            pipeline_id=args.pipeline_id,
            scripts_dir=scripts_dir,
            signal_timeout=args.signal_timeout,
            max_retries=args.max_retries,
            target_dir=args.target_dir,
        )

        initial_prompt = build_initial_prompt(
            dot_path=dot_path,
            pipeline_id=args.pipeline_id,
            scripts_dir=scripts_dir,
            target_dir=args.target_dir,
        )

        options = build_options(
            system_prompt=system_prompt,
            cwd=cwd,
            model=args.model,
            max_turns=args.max_turns,
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
                "target_dir": args.target_dir,
                "scripts_dir": scripts_dir,
                "system_prompt_length": len(system_prompt),
                "initial_prompt_length": len(initial_prompt),
            }
            print(json.dumps(config, indent=2))
            sys.exit(0)

        # Register guardian identity before starting the agent loop
        guardian_name = args.pipeline_id
        identity_registry.create_identity(
            role="guardian",
            name=guardian_name,
            session_id=f"guardian-{guardian_name}",
            worktree="",
        )

        # Live run: invoke the Agent SDK.
        try:
            asyncio.run(_run_agent(initial_prompt, options))
            # Clean shutdown
            try:
                identity_registry.mark_terminated(role="guardian", name=guardian_name)
            except Exception:
                pass
        except KeyboardInterrupt:
            print("[Guardian] Interrupted by user.", flush=True)
            try:
                identity_registry.mark_terminated(role="guardian", name=guardian_name)
            except Exception:
                pass
            sys.exit(130)
        except Exception as exc:
            print(f"[Guardian error] {exc}", file=sys.stderr, flush=True)
            try:
                identity_registry.mark_crashed(role="guardian", name=guardian_name)
            except Exception:
                pass
            sys.exit(1)


if __name__ == "__main__":
    main()
