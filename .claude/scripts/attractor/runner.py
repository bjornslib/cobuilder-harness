#!/usr/bin/env python3
"""runner.py — Runner Agent (Layer 2) + Spawn entrypoint.

Merged from runner_agent.py (monitoring agent) and spawn_runner.py (fire-and-forget
subprocess launcher). Canonical Layer 2 file.

Direct usage (monitoring agent):
    python runner.py \\
        --node <node_id> \\
        --prd <prd_ref> \\
        --session <tmux_session_name> \\
        [--dot-file <path_to_pipeline.dot>] \\
        [--solution-design <path>] \\
        [--acceptance <text>] \\
        [--target-dir <path>] \\
        [--bead-id <id>] \\
        [--check-interval <seconds>] \\
        [--stuck-threshold <seconds>] \\
        [--max-turns <n>] \\
        [--model <model_id>] \\
        [--signals-dir <path>] \\
        [--dry-run]

Spawn usage (fire-and-forget subprocess):
    python runner.py --spawn \\
        --node <node_id> \\
        --prd <prd_ref> \\
        --target-dir <path> \\
        [--solution-design <path>] \\
        [--acceptance <text>] \\
        [--bead-id <id>] \\
        [--mode sdk|tmux|headless] \\
        [--dot-file <path>]

Architecture:
    runner.py (Python process)
        │
        ├── Parse CLI args
        ├── build_system_prompt()    → monitoring instructions for Claude
        ├── build_initial_prompt()   → first user message with immediate context
        ├── build_options()          → ClaudeCodeOptions (Bash only, max_turns, model)
        └── asyncio.run(_run_agent())
               │
               └── async for message in query(initial_prompt, options=options):
                       # Claude uses Bash to run CLI tools in scripts_dir
                       pass

    spawn() function — fire-and-forget subprocess:
        - Registers identity + hook for runner
        - Launches runner.py (itself) as a detached subprocess with cleaned environment
        - Writes a state file with the PID using the atomic tmp+rename pattern
        - Outputs JSON confirming the launch

Output when --spawn (stdout, JSON):
    {
        "status": "ok",
        "node": "<node_id>",
        "prd": "<prd_ref>",
        "runner_pid": <pid>,
        "state_file": "<path>",
        "identity_file": "<path>",
        "hook_file": "<path>"
    }

CLAUDECODE environment note:
    The Runner may be launched from inside a Claude Code session. To avoid
    nested-session conflicts, we pass env={"CLAUDECODE": ""} as a workaround
    to suppress the variable. The definitive fix (subprocess.Popen with a
    cleaned env) lives in the spawn() function in this file.
"""

from __future__ import annotations

import argparse
import asyncio
import enum
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import warnings
from typing import Any

# Ensure this file's directory is importable regardless of invocation CWD.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import identity_registry
import hook_manager
from dispatch_worker import load_attractor_env

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

DEFAULT_CHECK_INTERVAL = 30      # seconds between polling cycles
DEFAULT_STUCK_THRESHOLD = 300    # seconds before declaring "stuck"
DEFAULT_MAX_TURNS = 100          # enough turns for a long monitoring loop


# ---------------------------------------------------------------------------
# JSONL event emitter
# ---------------------------------------------------------------------------


def emit_event(event_type: str, **payload) -> None:
    """Emit a structured JSONL event to stdout.

    Each line is valid JSON with 'type' and 'ts' fields plus any extra payload.
    Consumers can parse runner progress in real-time by reading stdout line by line.

    Args:
        event_type: Dot-namespaced event identifier (e.g. ``runner/started``).
        **payload:  Arbitrary key-value pairs included in the JSON object.
    """
    event = {
        "type": event_type,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        **payload,
    }
    print(json.dumps(event, default=str), flush=True)


# ---------------------------------------------------------------------------
# Public helper functions (importable for testing)
# ---------------------------------------------------------------------------


def build_system_prompt(
    node_id: str,
    prd_ref: str,
    session_name: str,
    acceptance: str,
    scripts_dir: str,
    check_interval: int,
    stuck_threshold: int,
    mode: str = "tmux",
) -> str:
    """Return the system prompt that instructs the Claude agent how to monitor.

    Args:
        node_id: Pipeline node identifier (e.g., ``impl_auth``).
        prd_ref: PRD reference string (e.g., ``PRD-AUTH-001``).
        session_name: tmux session name hosting the orchestrator.
        acceptance: Human-readable acceptance criteria text.
        scripts_dir: Absolute path to the attractor scripts directory.
        check_interval: Polling interval in seconds.
        stuck_threshold: Seconds of no progress before raising ORCHESTRATOR_STUCK.
        mode: Launch mode the orchestrator was started with (``"sdk"`` or ``"tmux"``).

    Returns:
        Formatted system prompt string.
    """
    with logfire.span("runner.build_system_prompt", node_id=node_id, prd_ref=prd_ref):
        return f"""\
You are a Runner agent (Layer 2) in a 4-layer pipeline execution system.

Your role: Monitor an orchestrator tmux session and signal the Guardian at decision points.

## Your Assignment
- Node ID: {node_id}
- PRD Reference: {prd_ref}
- tmux Session: {session_name}
- Acceptance Criteria: {acceptance or "See DOT file"}
- Orchestrator mode: {mode} ({"sdk: guardian runs in worktree, no nested --worktree created" if mode == "sdk" else "tmux: ccorch created .claude/worktrees/" + node_id})

## Tools Available (via Bash)
All tool scripts are in {scripts_dir}:
- capture_output.py --session <name> [--lines <n>]    # Read tmux pane content
- check_orchestrator_alive.py --session <name>         # Check if session exists
- signal_guardian.py <TYPE> --node <id> [--evidence <path>] [--question <text>]  # Signal Guardian
- wait_for_guardian.py --node <id> [--timeout <s>]     # Wait for Guardian response
- send_to_orchestrator.py --session <name> --message <text>  # Send to orchestrator

## Monitoring Loop
1. Check if orchestrator is alive: `python {scripts_dir}/capture_output.py --session {session_name} --lines 5`
2. If not alive: signal ORCHESTRATOR_CRASHED to Guardian
3. Capture recent output: `python {scripts_dir}/capture_output.py --session {session_name} --lines 100`
4. Interpret the output with your intelligence (not regex):
   - Has the orchestrator completed the node implementation?
   - Is it asking a question or waiting for input?
   - Is it stuck (no meaningful progress)?
   - Has it violated guard rails (using Edit/Write directly)?
5. Signal the Guardian if a decision point is reached
6. Wait for Guardian response and relay it to the orchestrator if needed
7. Repeat from step 1 (with {check_interval}s sleep between iterations)

## Signal Types
Signal the Guardian using: python {scripts_dir}/signal_guardian.py <TYPE> --node {node_id} [options]

- NEEDS_REVIEW: Implementation appears complete, needs validation
  Use: signal_guardian.py NEEDS_REVIEW --node {node_id} --commit <hash> --summary <text>

- NEEDS_INPUT: Orchestrator is asking a question or waiting for decision
  Use: signal_guardian.py NEEDS_INPUT --node {node_id} --question "<text>" --options '<json>'

- VIOLATION: Orchestrator violated guard rails (used Edit/Write directly)
  Use: signal_guardian.py VIOLATION --node {node_id} --reason "<description>"

- ORCHESTRATOR_STUCK: No meaningful progress for {stuck_threshold}s
  Use: signal_guardian.py ORCHESTRATOR_STUCK --node {node_id} --duration <seconds> --last-output "<text>"

- ORCHESTRATOR_CRASHED: tmux session no longer exists
  Use: signal_guardian.py ORCHESTRATOR_CRASHED --node {node_id} --last-output "<text>"

- NODE_COMPLETE: Node finished with committed work
  Use: signal_guardian.py NODE_COMPLETE --node {node_id} --commit <hash> --summary <text>

## After Signaling
After signaling NEEDS_REVIEW, NEEDS_INPUT, or VIOLATION, wait for Guardian:
  python {scripts_dir}/wait_for_guardian.py --node {node_id} --timeout 600

The Guardian response will have signal_type one of:
- VALIDATION_PASSED: Node validated, work is done → exit
- VALIDATION_FAILED: Re-work needed → relay feedback to orchestrator and continue monitoring
- INPUT_RESPONSE: Guardian made a decision → relay via send_to_orchestrator
- KILL_ORCHESTRATOR: Guardian wants to abort → exit with appropriate code
- GUIDANCE: Guardian sending proactive guidance → relay to orchestrator

After receiving VALIDATION_PASSED, also notify the terminal layer:
  python {scripts_dir}/signal_guardian.py VALIDATION_COMPLETE --node {node_id} --target terminal --summary "Node {node_id} validated"
  Then exit normally.

## Merge Queue Integration
When a node is marked impl_complete, enqueue it for sequential merging and signal the Guardian:

```python
import merge_queue, signal_protocol
# Enqueue the branch for sequential merge
merge_queue.enqueue(
    node_id="{node_id}",
    branch="worktree-{node_id}",
    repo_root="<repo_root>",
)
# Notify Guardian that the branch is ready to merge
signal_protocol.write_signal(
    source="runner",
    target="guardian",
    signal_type="MERGE_READY",
    payload={{"node_id": "{node_id}", "branch": "worktree-{node_id}"}},
)
```

The Guardian will call `merge_queue.process_next()` and respond with MERGE_COMPLETE or MERGE_FAILED.

## Hook Phase Tracking
Update your work phase at each lifecycle transition so that respawned sessions can resume correctly.

When you start an orchestrator session (after running spawn_orchestrator.py):
```bash
python3 {scripts_dir}/spawn_orchestrator.py --node {node_id} --prd {prd_ref} --repo-root <repo_root> --mode {mode}
python3 {scripts_dir}/hook_manager.py update-phase runner {node_id} executing
```

When the orchestrator signals NODE_COMPLETE or IMPL_COMPLETE:
```bash
python3 {scripts_dir}/hook_manager.py update-phase runner {node_id} impl_complete
```

Update resumption instructions before any planned pause:
```bash
python3 {scripts_dir}/hook_manager.py update-resumption runner {node_id} "Brief description of where to resume"
```

## Liveness Tracking
This runner's identity is tracked in .claude/state/identities/runner-{node_id}.json.
Call update_liveness periodically via:
  python {scripts_dir}/identity_registry.py --update-liveness runner {node_id}

## Completion
- Exit normally when you receive VALIDATION_PASSED or KILL_ORCHESTRATOR
- Exit with error code if orchestrator crashes and Guardian cannot recover

## Indicators to Watch For

Completion indicators:
- "All tasks complete", "Implementation done", "Committed", git commit messages
- Orchestrator reporting completion via its own signals

Input needed indicators:
- AskUserQuestion dialogs in Claude's output
- "Do you want to...", "Should I...", "Awaiting your input"
- Long pauses with no output change

Violation indicators:
- "Editing file...", "Writing to...", direct file modification by orchestrator (it should delegate)
- Edit/Write tool usage in orchestrator's output

Stuck indicators:
- Same output for multiple polling cycles
- Repeated identical tool calls
- Error loops (same error repeating)
"""


def build_initial_prompt(
    node_id: str,
    prd_ref: str,
    session_name: str,
    acceptance: str,
    scripts_dir: str,
    check_interval: int,
    stuck_threshold: int,
) -> str:
    """Return the first user message sent to Claude to start the monitoring loop.

    Args:
        node_id: Pipeline node identifier.
        prd_ref: PRD reference string.
        session_name: tmux session name hosting the orchestrator.
        acceptance: Acceptance criteria text.
        scripts_dir: Absolute path to the attractor scripts directory.
        check_interval: Polling interval in seconds.
        stuck_threshold: Seconds of no progress before declaring stuck.

    Returns:
        Formatted initial prompt string.
    """
    with logfire.span("runner.build_initial_prompt", node_id=node_id, prd_ref=prd_ref):
        return (
            f"You are monitoring orchestrator in tmux session '{session_name}' "
            f"implementing node '{node_id}' for {prd_ref}.\n\n"
            f"Your assignment:\n"
            f"- Node: {node_id}\n"
            f"- PRD: {prd_ref}\n"
            f"- Session: {session_name}\n"
            f"- Acceptance criteria: {acceptance or 'See DOT file'}\n"
            f"- Check interval: {check_interval}s\n"
            f"- Stuck threshold: {stuck_threshold}s\n\n"
            f"Start by checking if the orchestrator is alive, then begin the monitoring loop.\n"
            f"Scripts directory: {scripts_dir}\n"
        )


def build_options(
    system_prompt: str,
    cwd: str,
    model: str,
    max_turns: int,
) -> Any:
    """Construct a ClaudeCodeOptions instance for the Runner agent.

    The Runner is restricted to Bash only — it must not call Edit/Write/etc.
    CLAUDECODE is overridden to an empty string to suppress nested session
    warnings (the authoritative fix is in spawn() in this file using Popen).

    Args:
        system_prompt: Monitoring instructions for Claude.
        cwd: Working directory for the agent (project root).
        model: Claude model identifier.
        max_turns: Maximum turns before the SDK stops the conversation.

    Returns:
        Configured ClaudeCodeOptions instance.
    """
    with logfire.span("runner.build_options", model=model):
        from claude_code_sdk import ClaudeCodeOptions

        return ClaudeCodeOptions(
            allowed_tools=["Bash"],
            system_prompt=system_prompt,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            # Suppress CLAUDECODE env var to avoid nested-session conflicts.
            # Definitive fix (subprocess.Popen with cleaned env) is in spawn().
            env={"CLAUDECODE": ""},
        )


def build_worker_system_prompt(
    node_id: str,
    prd_ref: str,
    acceptance: str,
    target_dir: str,
) -> str:
    """Return the system prompt for a direct SDK worker agent (task execution).

    Unlike build_system_prompt() which instructs a monitoring agent, this
    prompt configures an agent that directly implements the task.

    Args:
        node_id: Pipeline node identifier.
        prd_ref: PRD reference string.
        acceptance: Acceptance criteria text.
        target_dir: Working directory for the agent.

    Returns:
        Formatted system prompt string.
    """
    with logfire.span("runner.build_worker_system_prompt", node_id=node_id, prd_ref=prd_ref):
        return (
            f"You are a software engineer implementing a pipeline task directly.\n\n"
            f"Your assignment:\n"
            f"- Node: {node_id}\n"
            f"- PRD: {prd_ref}\n"
            f"- Working directory: {target_dir}\n\n"
            f"Acceptance criteria:\n"
            f"{acceptance or 'Implement the feature as described in the initial prompt.'}\n\n"
            f"Work directly in {target_dir}. Use available tools to read, write, and "
            f"edit files as needed.\n"
            f"When finished, ensure all acceptance criteria are satisfied.\n\n"
            f"## Tool Usage Reference\n\n"
            f"**Creating new files** — prefer Bash heredoc:\n"
            f"  Bash: cat > path/to/file.py << 'EOF'\\ncontent\\nEOF\n\n"
            f"  Or Write tool (parameter is `file_path`, not `path`):\n"
            f"  Write(file_path=\"src/main.py\", content=\"...\")\n\n"
            f"**Editing existing files**:\n"
            f"  1. Read(file_path=\"...\") — get current content\n"
            f"  2. Edit(file_path=\"...\", old_string=\"exact match\", new_string=\"replacement\")\n"
            f"  Note: old_string must match the file exactly (including whitespace).\n"
            f"  Note: replace_all is boolean true/false, not the string 'True'/'False'.\n\n"
            f"**Do not attempt to use beads or other MCP tools** — they are not available in this context.\n"
        )


def build_worker_initial_prompt(
    node_id: str,
    prd_ref: str,
    acceptance: str,
    solution_design: str | None = None,
    bead_id: str = "",
    target_dir: str = "",
) -> str:
    """Return the initial task prompt for a direct SDK worker agent.

    Args:
        node_id: Pipeline node identifier.
        prd_ref: PRD reference string.
        acceptance: Acceptance criteria text.
        solution_design: Optional path to a solution design document.
        bead_id: Optional bead/task identifier.
        target_dir: Working directory for resolving relative solution_design paths.

    Returns:
        Formatted initial prompt string.
    """
    with logfire.span("runner.build_worker_initial_prompt", node_id=node_id, prd_ref=prd_ref):
        parts: list[str] = [
            f"## Task: {node_id}",
            f"",
            f"**PRD Reference**: {prd_ref}",
        ]
        if bead_id:
            parts.append(f"**Bead ID**: {bead_id}")
        parts += [
            f"",
            f"## Acceptance Criteria",
            f"{acceptance or 'Implement the feature. Ensure the code works correctly.'}",
        ]
        if solution_design:
            sd_path = Path(solution_design)
            if sd_path.is_absolute():
                sd_abs = sd_path
            else:
                sd_abs = Path(target_dir) / sd_path if target_dir else sd_path
            try:
                sd_content = sd_abs.read_text()
                parts += [
                    "",
                    "## Solution Design",
                    sd_content,
                ]
            except (OSError, FileNotFoundError):
                parts += [
                    "",
                    "## Solution Design",
                    f"(Could not read {solution_design} — implement from acceptance criteria only)",
                ]
        parts += [
            f"",
            f"Please implement this task now, working in the project directory.",
        ]
        return "\n".join(parts)


def build_worker_options(
    system_prompt: str,
    cwd: str,
    model: str,
    max_turns: int,
) -> Any:
    """Build ClaudeCodeOptions for a direct SDK worker with full toolset.

    Unlike build_options() which restricts to Bash only (for monitoring),
    this gives the worker unrestricted tool access for implementation work.

    Args:
        system_prompt: Task execution instructions for Claude.
        cwd: Working directory for the agent (project root).
        model: Claude model identifier.
        max_turns: Maximum turns before the SDK stops the conversation.

    Returns:
        Configured ClaudeCodeOptions instance.
    """
    with logfire.span("runner.build_worker_options", model=model):
        from claude_code_sdk import ClaudeCodeOptions

        return ClaudeCodeOptions(
            allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "MultiEdit"],
            system_prompt=system_prompt,
            cwd=cwd,
            model=model,
            max_turns=max_turns,
            env={"CLAUDECODE": ""},
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for runner.py.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="runner.py",
        description="Runner Agent (Layer 2): monitors orchestrator via claude_code_sdk. "
                    "Use --spawn for fire-and-forget subprocess launch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Direct agent (monitoring loop):
  python runner.py --node impl_auth --prd PRD-AUTH-001 --session orch-auth --target-dir /path/to/repo

  python runner.py --node impl_auth --prd PRD-AUTH-001 --session orch-auth \\
      --acceptance "Auth module passes all tests" --check-interval 60 --dry-run

  # Spawn (fire-and-forget subprocess):
  python runner.py --spawn --node impl_auth --prd PRD-AUTH-001 --target-dir /path/to/repo
        """,
    )

    # Spawn mode flag — when set, runs the fire-and-forget subprocess launcher
    parser.add_argument("--spawn", action="store_true", default=False,
                        help="Fire-and-forget: register identity/hook, launch runner.py as "
                             "a detached subprocess, write state file, and output JSON")

    parser.add_argument("--node", required=True, help="Pipeline node identifier")
    parser.add_argument("--prd", required=True, help="PRD reference (e.g. PRD-AUTH-001)")
    parser.add_argument("--session", default=None,
                        help="tmux session name for orchestrator (required in direct mode; "
                             "auto-derived from --node in --spawn mode)")
    parser.add_argument("--dot-file", default=None, dest="dot_file",
                        help="Path to pipeline .dot file")
    parser.add_argument("--solution-design", default=None, dest="solution_design",
                        help="Path to solution design document")
    parser.add_argument("--acceptance", default=None,
                        help="Acceptance criteria text")
    parser.add_argument("--target-dir", required=True, dest="target_dir",
                        help="Working directory for the agent")
    parser.add_argument("--bead-id", default=None, dest="bead_id",
                        help="Beads issue/task identifier")
    parser.add_argument("--check-interval", type=int, default=DEFAULT_CHECK_INTERVAL,
                        dest="check_interval",
                        help=f"Seconds between polling cycles (default: {DEFAULT_CHECK_INTERVAL})")
    parser.add_argument("--stuck-threshold", type=int, default=DEFAULT_STUCK_THRESHOLD,
                        dest="stuck_threshold",
                        help=f"Seconds of no progress before ORCHESTRATOR_STUCK (default: {DEFAULT_STUCK_THRESHOLD})")
    parser.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS,
                        dest="max_turns",
                        help=f"Max SDK turns (default: {DEFAULT_MAX_TURNS})")
    _default_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    parser.add_argument("--model", default=_default_model,
                        help=f"Claude model to use (default: {_default_model})")
    parser.add_argument("--signals-dir", default=None, dest="signals_dir",
                        help="Override signals directory path")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Log config without spawning the SDK agent (for testing)")
    parser.add_argument("--mode", choices=["sdk", "tmux", "headless"], default="tmux", dest="mode",
                        help="Orchestrator launch mode: sdk (no --worktree) or tmux (default)")

    args = parser.parse_args(argv)

    # Warn if session name uses reserved s3-live- prefix (runner monitors an existing
    # session, doesn't create one, so we warn but don't block).
    if args.session and re.match(r"s3-live-", args.session):
        warnings.warn(
            f"Session name '{args.session}' uses reserved 's3-live-' prefix. "
            "Expected prefix is 'orch-' for orchestrator sessions.",
            UserWarning,
            stacklevel=2,
        )

    return args


def resolve_scripts_dir() -> str:
    """Return the absolute path to the attractor scripts directory.

    Resolution order:
    1. The directory containing this file (runner.py is inside attractor/).
    2. Falls back to current working directory if for some reason _THIS_DIR is unavailable.

    Returns:
        Absolute path string.
    """
    return _THIS_DIR


def build_env_config() -> dict[str, str]:
    """Return environment overrides that suppress the CLAUDECODE variable.

    We cannot *delete* env keys via ClaudeCodeOptions.env (it only adds/overrides),
    so we override CLAUDECODE to an empty string. The authoritative fix is in
    spawn() which uses subprocess.Popen with a fully cleaned environment.

    Returns:
        Dict of env var overrides to pass to ClaudeCodeOptions.
    """
    return {"CLAUDECODE": ""}


# ---------------------------------------------------------------------------
# Mode-switching runner — RunnerMode + RunnerStateMachine
# ---------------------------------------------------------------------------


class RunnerMode(str, enum.Enum):
    """Operational modes for RunnerStateMachine.

    Each member is also a ``str`` so comparisons with plain string literals
    (e.g. ``mode == "MONITOR"``) continue to work without callers needing to
    import the enum.

    Modes represent the lifecycle state of the runner:
        INIT         — initial state before monitoring begins
        RUNNER       — running the orchestrator monitoring loop
        MONITOR      — active monitoring cycle, querying LLM about pipeline status
        WAIT_GUARDIAN — waiting for guardian response after signaling
        VALIDATE     — validation phase, checking node completion criteria
        COMPLETE     — terminal success state; node validated
        FAILED       — terminal failure state; node failed or max cycles exceeded
    """

    INIT = "INIT"
    RUNNER = "RUNNER"
    MONITOR = "MONITOR"
    WAIT_GUARDIAN = "WAIT_GUARDIAN"
    VALIDATE = "VALIDATE"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


def build_monitor_prompt(
    node_id: str,
    session_name: str,
    scripts_dir: str,
) -> str:
    """Build the monitoring analysis prompt for the RunnerStateMachine.

    Constructs a user-turn prompt that asks the LLM to inspect the
    orchestrator tmux session and output a STATUS: line indicating whether
    the target node has completed, failed, or is still in progress.

    Args:
        node_id: Pipeline node identifier being monitored.
        session_name: tmux session name hosting the orchestrator.
        scripts_dir: Absolute path to the attractor scripts directory.

    Returns:
        Formatted prompt string ready for the SDK query() call.
    """
    with logfire.span("runner.build_monitor_prompt", node_id=node_id, session_name=session_name):
        return f"""\
You are monitoring tmux session '{session_name}' for pipeline node '{node_id}'.

## Your ONLY job
1. Run: python {scripts_dir}/capture_output.py --session {session_name} --lines 100
2. Analyse the output and respond in EXACTLY this format (no other text):

STATUS: <COMPLETED|STUCK|CRASHED|WORKING|NEEDS_INPUT>
EVIDENCE: <one-line summary of what you observed>
COMMIT: <7+ hex char git commit hash if visible, else NONE>
OUTPUT_TAIL: <last 3 lines of captured output>

## DEFINITIVE completion signals → STATUS: COMPLETED
Report COMPLETED immediately when you see ANY of these:
- Git commit hash in output: `a7a8647`, `[abc1234 feat: ...]`, `[worktree-impl_auth abc1234]`
- Push confirmation: "pushed to", "→ refs/heads/worktree-", "Branch 'worktree-"
- PR prompt: "Would you like to create a pull request?"
- Claude session result JSON: {{"session_id":, "num_turns":, "total_cost_usd":
- Claude turn completion: "Completed turn N of N", "Human turn 0"

## PROBABLE completion — poll twice before reporting COMPLETED
- Shell prompt idle: line ending with `$ `, `% `, or `❯ ` with no change across 2 checks

## Other statuses
- STATUS: STUCK      — same output unchanged for multiple polls, repeated identical errors
- STATUS: CRASHED    — tmux session no longer exists (capture_output.py returns error)
- STATUS: WORKING    — active tool calls, file edits, LLM text streaming visible
- STATUS: NEEDS_INPUT — AskUserQuestion dialog, "Do you want to...", "Should I..."

## POST-REMEDIATION round-trip (IMPORTANT)
After VALIDATION_FAILED feedback is relayed to the orchestrator, it will fix issues
and produce NEW commits. You will re-enter MONITOR mode. Watch for the SAME completion
indicators above and report STATUS: COMPLETED again when you see them.
This round-trip is NORMAL — expect it and handle it correctly.

Capture the output now and report your STATUS.
"""


class RunnerStateMachine:
    """Mode-switching runner that uses the Claude Code SDK for pipeline monitoring.

    The state machine transitions between MONITOR and terminal modes based on
    LLM analysis of the pipeline .dot file. It integrates with the signal
    protocol to notify the guardian of unexpected exits (RUNNER_EXITED).

    Attributes:
        mode: Current operational mode (RunnerMode constant).
    """

    def __init__(
        self,
        node_id: str,
        prd_ref: str,
        session_name: str,
        target_dir: str,
        dot_file: str | None = None,
        signals_dir: str | None = None,
        model: str = "claude-sonnet-4-6",
        max_turns: int = DEFAULT_MAX_TURNS,
        max_cycles: int = 10,
    ) -> None:
        """Initialise the state machine.

        Args:
            node_id: Pipeline node identifier being monitored.
            prd_ref: PRD reference string (e.g. "PRD-AUTH-001").
            session_name: tmux session name (used for monitor prompt context).
            target_dir: Working directory for the SDK agent.
            dot_file: Optional path to the pipeline .dot file; when provided,
                enables pipeline-state-aware monitoring via the CLI tools.
            signals_dir: Override for the signal protocol directory.
            model: Claude model to use for monitoring queries.
            max_turns: Maximum SDK turns per monitor cycle.
            max_cycles: Maximum monitoring cycles before exiting as FAILED.
        """
        import signal_protocol as _sp
        self._signal_protocol = _sp

        self.node_id = node_id
        self.prd_ref = prd_ref
        self.session_name = session_name
        self.target_dir = target_dir
        self.dot_file = dot_file
        self.signals_dir = signals_dir
        self.model = model
        self.max_turns = max_turns
        self.max_cycles = max_cycles
        self.mode: str = RunnerMode.MONITOR
        self._scripts_dir = resolve_scripts_dir()

    def _do_monitor_mode(self) -> str:
        """Run one SDK monitoring cycle and return the status string.

        Uses asyncio.run() with the Claude Code SDK to query the LLM using
        the monitor prompt. Text blocks from all AssistantMessage turns are
        accumulated into a single string and scanned for a STATUS: line.

        Returns:
            One of "COMPLETED", "FAILED", or "IN_PROGRESS".
        """
        prompt = build_monitor_prompt(
            node_id=self.node_id,
            session_name=self.session_name,
            scripts_dir=self._scripts_dir,
        )

        system_prompt = (
            "You are a pipeline monitoring assistant. Analyse the pipeline "
            "state and output a STATUS: line as instructed. Be concise."
        )
        options = build_options(
            system_prompt=system_prompt,
            cwd=self.target_dir,
            model=self.model,
            max_turns=self.max_turns,
        )

        # Accumulate text blocks by reference — the inner coroutine populates
        # this list so we can read it after asyncio.run() returns.
        text_blocks: list[str] = []

        async def _run_with_capture() -> None:
            """Run SDK query and accumulate LLM text blocks."""
            from claude_code_sdk import (
                query,
                AssistantMessage,
                TextBlock,
            )
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text:
                            text_blocks.append(block.text)

        asyncio.run(_run_with_capture())

        full_text = "\n".join(text_blocks)
        if "STATUS: COMPLETED" in full_text:
            return "COMPLETED"
        if "STATUS: FAILED" in full_text:
            return "FAILED"
        return "IN_PROGRESS"

    def _write_safety_net_if_needed(self) -> None:
        """Write a RUNNER_EXITED signal if the mode is not COMPLETE.

        Called from the finally block in run() to ensure the guardian always
        learns when the runner exits without completing its work. Signal
        write failures are silently swallowed to prevent masking the original
        exception.
        """
        if self.mode != RunnerMode.COMPLETE:
            try:
                self._signal_protocol.write_runner_exited(
                    node_id=self.node_id,
                    prd_ref=self.prd_ref,
                    mode=self.mode,
                    reason="runner_exited_without_complete",
                    signals_dir=self.signals_dir,
                )
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> str:
        """Run the state machine until completion or failure.

        Iterates the MONITOR cycle until the LLM reports COMPLETED or FAILED,
        or until max_cycles is exceeded. A try/finally ensures the safety net
        signal is always written unless the mode reaches COMPLETE.

        Returns:
            Final mode string (RunnerMode.COMPLETE or RunnerMode.FAILED).
        """
        emit_event("runner/started", node=self.node_id, prd=self.prd_ref)
        try:
            cycles = 0
            while self.mode == RunnerMode.MONITOR:
                cycles += 1
                emit_event(
                    "runner/cycle_start",
                    cycle=cycles,
                    max_cycles=self.max_cycles,
                    node=self.node_id,
                )
                if cycles > self.max_cycles:
                    self.mode = RunnerMode.FAILED
                    emit_event("runner/state_change", node=self.node_id, to=self.mode)
                    break

                status = self._do_monitor_mode()
                emit_event(
                    "runner/cycle_end",
                    cycle=cycles,
                    status=status,
                    node=self.node_id,
                )
                if status == "COMPLETED":
                    self.mode = RunnerMode.COMPLETE
                    emit_event("runner/state_change", node=self.node_id, to=self.mode)
                elif status == "FAILED":
                    self.mode = RunnerMode.FAILED
                    emit_event("runner/state_change", node=self.node_id, to=self.mode)
                # else: IN_PROGRESS — continue monitoring

        finally:
            self._write_safety_net_if_needed()
            emit_event("runner/completed", node=self.node_id, final_mode=self.mode)

        return self.mode


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

    with logfire.span("runner.run_agent") as agent_span:
        async for message in query(prompt=initial_prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn_count += 1
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text_preview = block.text[:300] if block.text else ""
                        logfire.info(
                            "runner.assistant_text",
                            turn=turn_count,
                            text_length=len(block.text) if block.text else 0,
                            text_preview=text_preview,
                        )
                        print(f"[Runner] {block.text}", flush=True)

                    elif isinstance(block, ToolUseBlock):
                        tool_call_count += 1
                        input_preview = json.dumps(block.input)[:500]
                        logfire.info(
                            "runner.tool_use",
                            tool_name=block.name,
                            tool_use_id=block.id,
                            tool_input_preview=input_preview,
                            turn=turn_count,
                            tool_call_number=tool_call_count,
                        )
                        print(f"[Runner tool] {block.name}: {input_preview[:200]}", flush=True)

                    elif isinstance(block, ThinkingBlock):
                        logfire.info(
                            "runner.thinking",
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
                                "runner.tool_result",
                                tool_use_id=block.tool_use_id,
                                is_error=block.is_error or False,
                                content_length=content_length,
                                content_preview=content_preview,
                                turn=turn_count,
                            )

            elif isinstance(message, ResultMessage):
                elapsed = _time.time() - start_time
                logfire.info(
                    "runner.result",
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
                print(f"[Runner done] turns={message.num_turns} cost=${message.total_cost_usd} tools={tool_call_count}", flush=True)


# ---------------------------------------------------------------------------
# Spawn helpers (from spawn_runner.py)
# ---------------------------------------------------------------------------


def _find_git_root(start: str):
    """Walk up directory tree to find .git root."""
    current = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _runner_state_dir() -> str:
    """Resolve the runner state directory."""
    git_root = _find_git_root(os.getcwd())
    if git_root:
        return os.path.join(git_root, ".claude", "attractor", "runner-state")
    return os.path.join(os.path.expanduser("~"), ".claude", "attractor", "runner-state")


def spawn(args: argparse.Namespace) -> None:
    """Fire-and-forget subprocess launcher for runner.py.

    Registers identity and hook for the runner, then launches runner.py as a
    detached subprocess with a cleaned environment (CLAUDECODE removed). Writes
    a state file with the PID using the atomic tmp+rename pattern and outputs
    JSON confirming the launch.

    Args:
        args: Parsed CLI arguments from parse_args() with --spawn flag set.
    """
    # 1. Register identity for runner
    try:
        identity_registry.create_identity(
            role="runner",
            name=args.node,
            session_id=f"runner-{args.node}",
            worktree=args.target_dir,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "message": f"Identity registration failed: {exc}"}))
        sys.exit(1)

    # 2. Create hook for runner
    try:
        hook_manager.create_hook(
            role="runner",
            name=args.node,
            phase="planning",
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "message": f"Hook creation failed: {exc}"}))
        sys.exit(1)

    # 3. Build runner command — launch runner.py (this file) directly
    runner_script = os.path.join(_THIS_DIR, "runner.py")
    cmd = [sys.executable, runner_script,
           "--node", args.node,
           "--prd", args.prd,
           "--session", f"orch-{args.node}",
           "--target-dir", args.target_dir,
           "--mode", args.mode,
           "--model", args.model]

    if args.solution_design:
        cmd += ["--solution-design", args.solution_design]
    if args.bead_id:
        cmd += ["--bead-id", args.bead_id]
    if args.dot_file:
        cmd += ["--dot-file", args.dot_file]

    # 4. Launch with cleaned environment (no CLAUDECODE token)
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)

    # Redirect runner stdout/stderr to log files instead of PIPE to avoid
    # pipe buffer deadlock (PIPE is never read since we detach immediately).
    try:
        log_dir = _runner_state_dir()
        os.makedirs(log_dir, exist_ok=True)
        timestamp_log = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stdout_log_path = os.path.join(log_dir, f"{timestamp_log}-{args.node}-stdout.log")
        stderr_log_path = os.path.join(log_dir, f"{timestamp_log}-{args.node}-stderr.log")
        stdout_log = open(stdout_log_path, "w", encoding="utf-8")
        stderr_log = open(stderr_log_path, "w", encoding="utf-8")
    except Exception:
        # Fallback to DEVNULL if log files can't be created
        stdout_log_path = None
        stderr_log_path = None
        stdout_log = subprocess.DEVNULL
        stderr_log = subprocess.DEVNULL

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=args.target_dir,
            stdout=stdout_log,
            stderr=stderr_log,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "message": f"Failed to launch runner: {exc}"}))
        sys.exit(1)

    # 5. Write state file with PID (atomic tmp+rename pattern)
    try:
        state_dir = _runner_state_dir()
        os.makedirs(state_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        state_filename = f"{timestamp}-{args.node}-{args.prd}.json"
        state_path = os.path.join(state_dir, state_filename)

        state_data = {
            "spawned_at": timestamp,
            "status": "running",
            "runner_pid": proc.pid,
            "node_id": args.node,
            "prd_ref": args.prd,
            "target_dir": args.target_dir,
            "identity_file": f".claude/state/identities/runner-{args.node}.json",
            "hook_file": f".claude/state/hooks/runner-{args.node}.json",
            "runner_config": {
                "node_id": args.node,
                "prd_ref": args.prd,
                "solution_design": args.solution_design,
                "acceptance_criteria": args.acceptance,
                "target_dir": args.target_dir,
                "bead_id": args.bead_id,
                "dot_file": args.dot_file,
            },
            "stdout_log": stdout_log_path,
            "stderr_log": stderr_log_path,
        }

        tmp_path = state_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(state_data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp_path, state_path)

        print(json.dumps({
            "status": "ok",
            "node": args.node,
            "prd": args.prd,
            "runner_pid": proc.pid,
            "state_file": state_path,
            "identity_file": state_data["identity_file"],
            "hook_file": state_data["hook_file"],
            "runner_config": state_data["runner_config"],
        }))

    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and route to spawn() or monitoring agent."""
    # Load attractor-specific API credentials before any SDK call.
    # claude_code_sdk.query() reads ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL from
    # os.environ, so this must happen before argparse or SDK initialisation.
    os.environ.update(load_attractor_env())

    args = parse_args(argv)

    # --spawn mode: fire-and-forget subprocess launch
    if args.spawn:
        spawn(args)
        return

    # Direct agent mode: monitoring loop
    with logfire.span("runner.main", node_id=args.node, prd_ref=args.prd,
                      session=args.session, dry_run=args.dry_run):
        cwd = args.target_dir
        scripts_dir = resolve_scripts_dir()

        # --session defaults to orch-{node} in direct mode if not provided
        session_name = args.session or f"orch-{args.node}"

        system_prompt = build_system_prompt(
            node_id=args.node,
            prd_ref=args.prd,
            session_name=session_name,
            acceptance=args.acceptance or "",
            scripts_dir=scripts_dir,
            check_interval=args.check_interval,
            stuck_threshold=args.stuck_threshold,
            mode=args.mode,
        )

        initial_prompt = build_initial_prompt(
            node_id=args.node,
            prd_ref=args.prd,
            session_name=session_name,
            acceptance=args.acceptance or "",
            scripts_dir=scripts_dir,
            check_interval=args.check_interval,
            stuck_threshold=args.stuck_threshold,
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
                "node_id": args.node,
                "prd_ref": args.prd,
                "session_name": session_name,
                "dot_file": args.dot_file,
                "solution_design": args.solution_design,
                "acceptance": args.acceptance,
                "target_dir": cwd,
                "bead_id": args.bead_id,
                "check_interval": args.check_interval,
                "stuck_threshold": args.stuck_threshold,
                "max_turns": args.max_turns,
                "model": args.model,
                "mode": args.mode,
                "signals_dir": args.signals_dir,
                "scripts_dir": scripts_dir,
                "system_prompt_length": len(system_prompt),
                "initial_prompt_length": len(initial_prompt),
            }
            print(json.dumps(config, indent=2))
            sys.exit(0)

        # Register runner identity before starting the agent loop
        node_id = args.node
        try:
            identity_registry.create_identity(
                role="runner",
                name=node_id,
                session_id=f"runner-{node_id}",
                worktree="",
            )
        except Exception as exc:
            print(f"[Runner error] Identity registration failed: {exc}", file=sys.stderr, flush=True)
            sys.exit(1)

        try:
            # Create a persistent hook for this runner
            hook_manager.create_hook(role="runner", name=node_id)
        except Exception as exc:
            print(f"[Runner error] Hook creation failed: {exc}", file=sys.stderr, flush=True)
            try:
                identity_registry.mark_crashed(role="runner", name=node_id)
            except Exception:
                pass
            sys.exit(1)

        # Live run: choose execution path based on mode and dot-file presence.
        if args.dot_file and args.mode == "sdk":
            # SDK direct execution: runner IS the worker — no monitoring loop.
            # Build task prompts (not monitoring prompts), run the agent directly,
            # then transition the dot node state on completion.
            cli_script = os.path.join(_THIS_DIR, "cli.py")
            emit_event(
                "runner/init",
                node=node_id,
                prd=args.prd,
                dot_file=args.dot_file,
                mode="sdk_direct",
            )

            worker_system_prompt = build_worker_system_prompt(
                node_id=node_id,
                prd_ref=args.prd,
                acceptance=args.acceptance or "",
                target_dir=cwd,
            )
            worker_initial_prompt = build_worker_initial_prompt(
                node_id=node_id,
                prd_ref=args.prd,
                acceptance=args.acceptance or "",
                solution_design=args.solution_design,
                bead_id=args.bead_id or "",
                target_dir=cwd,
            )
            worker_options = build_worker_options(
                system_prompt=worker_system_prompt,
                cwd=cwd,
                model=args.model,
                max_turns=args.max_turns,
            )

            try:
                asyncio.run(_run_agent(worker_initial_prompt, worker_options))
                # Success: transition node to impl_complete
                subprocess.run(
                    [sys.executable, cli_script, "transition",
                     args.dot_file, "transition", node_id, "impl_complete"],
                    cwd=cwd,
                    check=False,
                )
                emit_event("runner/exit", node=node_id, final_mode="COMPLETE")
                try:
                    identity_registry.mark_terminated(role="runner", name=node_id)
                except Exception:
                    pass
            except KeyboardInterrupt:
                subprocess.run(
                    [sys.executable, cli_script, "transition",
                     args.dot_file, "transition", node_id, "failed"],
                    cwd=cwd,
                    check=False,
                )
                try:
                    identity_registry.mark_terminated(role="runner", name=node_id)
                except Exception:
                    pass
                sys.exit(130)
            except Exception as exc:
                # Failure: transition node to failed
                subprocess.run(
                    [sys.executable, cli_script, "transition",
                     args.dot_file, "transition", node_id, "failed"],
                    cwd=cwd,
                    check=False,
                )
                emit_event("runner/exit", node=node_id, final_mode="FAILED", error=str(exc))
                try:
                    identity_registry.mark_crashed(role="runner", name=node_id)
                except Exception:
                    pass
                sys.exit(1)

        elif args.dot_file:
            # Mode-switching path (tmux/headless): use RunnerStateMachine for pipeline-aware monitoring.
            emit_event(
                "runner/init",
                node=node_id,
                prd=args.prd,
                dot_file=args.dot_file,
                mode=args.mode,
            )
            try:
                machine = RunnerStateMachine(
                    node_id=node_id,
                    prd_ref=args.prd,
                    session_name=session_name,
                    target_dir=cwd,
                    dot_file=args.dot_file,
                    signals_dir=args.signals_dir,
                    model=args.model,
                    max_turns=args.max_turns,
                )
                final_mode = machine.run()
                emit_event("runner/exit", node=node_id, final_mode=final_mode)
                try:
                    identity_registry.mark_terminated(role="runner", name=node_id)
                except Exception:
                    pass
            except KeyboardInterrupt:
                print("[Runner] Interrupted by user.", flush=True)
                try:
                    identity_registry.mark_terminated(role="runner", name=node_id)
                except Exception:
                    pass
                sys.exit(130)
            except Exception as exc:
                print(f"[Runner error] {exc}", file=sys.stderr, flush=True)
                try:
                    identity_registry.mark_crashed(role="runner", name=node_id)
                except Exception:
                    pass
                sys.exit(1)
        else:
            # Legacy tmux monitoring path: invoke the Agent SDK loop.
            try:
                asyncio.run(_run_agent(initial_prompt, options))
                # Clean shutdown
                try:
                    identity_registry.mark_terminated(role="runner", name=node_id)
                except Exception:
                    pass
            except KeyboardInterrupt:
                print("[Runner] Interrupted by user.", flush=True)
                try:
                    identity_registry.mark_terminated(role="runner", name=node_id)
                except Exception:
                    pass
                sys.exit(130)
            except Exception as exc:
                print(f"[Runner error] {exc}", file=sys.stderr, flush=True)
                try:
                    identity_registry.mark_crashed(role="runner", name=node_id)
                except Exception:
                    pass
                sys.exit(1)


if __name__ == "__main__":
    main()
