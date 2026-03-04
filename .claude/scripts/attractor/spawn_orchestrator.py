"""spawn_orchestrator.py — Create tmux session with Claude Code orchestrator.

Usage:
    python spawn_orchestrator.py --node <node_id> --prd <prd_ref>
        --repo-root <path> [--session-name <name>] [--prompt <text>]
        [--max-respawn <n>]

Creates a tmux session named orch-<node_id> (or --session-name) starting
in the repo root directory. Launches Claude Code with --worktree <node_id>
which creates an isolated worktree at .claude/worktrees/<node_id>/ with
branch worktree-<node_id>. Sets the orchestrator output style via slash
command, then sends the prompt.

Output (stdout, JSON):
    {"status": "ok", "session": "<name>", "tmux_cmd": "<command run>", "respawn_count": 0}

On error:
    {"status": "error", "message": "<error>"}
    exits with code 1
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shlex
import subprocess
import sys
import os
import time
from pathlib import Path

# Ensure this file's directory is importable regardless of invocation CWD.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import identity_registry
import hook_manager

logger = logging.getLogger(__name__)


def _build_headless_worker_cmd(
    task_prompt: str,
    work_dir: str,
    worker_type: str = "backend-solutions-engineer",
    model: str = "claude-sonnet-4-6",
    node_id: str = "",
    pipeline_id: str = "",
    runner_id: str = "",
    prd_ref: str = "",
) -> tuple[list[str], dict[str, str]]:
    """Build a headless worker command using ``claude -p``.

    Three-Layer Context:
      Layer 1 (ROLE): ``--system-prompt`` from ``.claude/agents/{worker_type}.md``
      Layer 2 (TASK): ``-p`` argument (*task_prompt*)
      Layer 3 (IDENTITY): env vars (``WORKER_NODE_ID``, ``PIPELINE_ID``, etc.)

    Args:
        task_prompt: The task description sent as the ``-p`` argument.
        work_dir: Working directory for the worker process.
        worker_type: Agent type — filename stem under ``.claude/agents/``.
        model: Claude model identifier.
        node_id: Pipeline node identifier.
        pipeline_id: Pipeline identifier string.
        runner_id: Runner identifier (for traceability).
        prd_ref: PRD reference (e.g., PRD-AUTH-001).

    Returns:
        Tuple of (command list, environment dict).
    """
    # Read Layer 1: ROLE from .claude/agents/{worker_type}.md
    agents_dir = Path(work_dir) / ".claude" / "agents"
    role_file = agents_dir / f"{worker_type}.md"
    if role_file.exists():
        role_content = role_file.read_text()
        # Strip frontmatter if present
        if role_content.startswith("---"):
            _, _, rest = role_content.partition("---")
            _, _, role_content = rest.partition("---")
        role_content = role_content.strip()
    else:
        role_content = f"You are a specialist agent ({worker_type}). Implement features directly."

    cmd = [
        "claude",
        "-p", task_prompt,
        "--system-prompt", role_content,
        "--permission-mode", "bypassPermissions",
        "--output-format", "json",
        "--model", model,
        # Bypass all MCP server initialization for headless workers.
        # Without this, 11+ MCP servers from .mcp.json cause extreme
        # startup delays (30s+) or hangs in subprocess mode.
        "--mcp-config", '{"mcpServers":{}}',
        "--strict-mcp-config",
    ]

    # Layer 3: IDENTITY as env vars (zero context token cost)
    env = dict(os.environ)
    env.update({
        "WORKER_NODE_ID": node_id,
        "PIPELINE_ID": pipeline_id,
        "RUNNER_ID": runner_id,
        "PRD_REF": prd_ref,
    })
    # Remove CLAUDECODE to prevent nested session detection
    env.pop("CLAUDECODE", None)

    return cmd, env


async def run_headless_worker(
    cmd: list[str],
    env: dict[str, str],
    work_dir: str,
    timeout_seconds: int = 1800,
) -> dict:
    """Run a headless worker via subprocess, capture JSON output.

    Args:
        cmd: Command list (typically from :func:`_build_headless_worker_cmd`).
        env: Environment dict for the subprocess.
        work_dir: Working directory for the subprocess.
        timeout_seconds: Maximum wall-clock time before killing the worker.

    Returns:
        Dict with ``status`` (``"success"``, ``"error"``, or ``"timeout"``),
        plus output or error details.
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode == 0:
            # Parse JSON output
            try:
                output = json.loads(result.stdout)
                return {"status": "success", "output": output, "exit_code": 0}
            except json.JSONDecodeError:
                return {"status": "success", "output": result.stdout, "exit_code": 0}
        else:
            return {
                "status": "error",
                "exit_code": result.returncode,
                "stdout": result.stdout[-2000:],  # Last 2K chars
                "stderr": result.stderr[-2000:],
            }
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "timeout_seconds": timeout_seconds}


def _build_claude_cmd(node_id: str, prd: str, mode: str) -> str:
    """Build direct claude invocation with explicit env vars.

    Replaces the ccorch shell function. Only sets documented/working env vars.
    Output style is set separately via /output-style slash command.

    Args:
        node_id: Node identifier (used for --worktree name).
        prd: PRD reference (e.g., PRD-AUTH-001).
        mode: Launch mode — "sdk" (no --worktree) or "tmux" (default, with --worktree).

    Returns:
        Shell command string to launch Claude Code with correct env vars.
    """
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    env_vars = " ".join([
        "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1",
        "CLAUDE_CODE_ENABLE_TASKS=true",
        f"CLAUDE_CODE_TASK_LIST_ID={shlex.quote(prd)}",
        f"CLAUDE_SESSION_ID=orch-{shlex.quote(prd)}-{timestamp}",
        "CLAUDE_ENFORCE_BO=false",
    ])

    worktree_flag = "" if mode == "sdk" else f" --worktree {shlex.quote(node_id)}"

    return (
        f"unset CLAUDECODE && env {env_vars} "
        f"claude --chrome --model claude-sonnet-4-6"
        f" --dangerously-skip-permissions{worktree_flag}"
    )


def _tmux_send(session: str, text: str, pause: float = 2.0, post_pause: float = 0.0) -> None:
    """Send text to tmux with Enter as separate call (Pattern 1 from MEMORY.md).

    Args:
        session:    tmux session target.
        text:       Text to type into the pane.
        pause:      Seconds between text paste and Enter key (render time).
        post_pause: Seconds after Enter key (processing time for commands
                    like /output-style that need to complete before next input).
    """
    subprocess.run(
        ["tmux", "send-keys", "-t", session, text],
        check=True, capture_output=True, text=True,
    )
    time.sleep(pause)
    subprocess.run(
        ["tmux", "send-keys", "-t", session, "Enter"],
        check=True, capture_output=True, text=True,
    )
    if post_pause > 0.0:
        time.sleep(post_pause)


def check_orchestrator_alive(session: str) -> bool:
    """Check if a tmux session exists.

    Args:
        session: tmux session name to check.

    Returns:
        True if the session exists (exit code 0), False otherwise.
    """
    result = subprocess.run(
        ["tmux", "has-session", "-t", session],
        capture_output=True,
    )
    return result.returncode == 0


def respawn_orchestrator(
    session_name: str,
    work_dir: str,
    node_id: str,
    prompt: str | None,
    respawn_count: int,
    max_respawn: int,
    mode: str = "tmux",
    prd: str = "",
) -> dict:
    """Attempt to respawn a dead orchestrator tmux session.

    Args:
        session_name: tmux session name to (re)create.
        work_dir: Repo root directory for the new session.
        node_id: Node identifier (used for --worktree name).
        prompt: Optional initial prompt to send after launching Claude.
        respawn_count: Current number of respawn attempts made so far.
        max_respawn: Maximum allowed respawn attempts.
        mode: Launch mode — ``"sdk"`` (no --worktree) or ``"tmux"`` (default, with --worktree).
        prd: PRD reference (e.g., PRD-AUTH-001) for env var injection.

    Returns:
        Dict with status:
            - ``{"status": "already_alive", "session": session_name}`` if session exists.
            - ``{"status": "error", "message": "Max respawn limit reached (...)"}`` if limit exceeded.
            - ``{"status": "respawned", "session": session_name, "respawn_count": respawn_count + 1}``
              on successful respawn.
    """
    if check_orchestrator_alive(session_name):
        return {"status": "already_alive", "session": session_name}

    if respawn_count >= max_respawn:
        return {
            "status": "error",
            "message": f"Max respawn limit reached ({respawn_count}/{max_respawn})",
        }

    # Inject wisdom from previous session hook before sending the prompt
    existing_hook = hook_manager.read_hook("orchestrator", node_id)
    if existing_hook:
        wisdom_block = hook_manager.build_wisdom_prompt_block(existing_hook)
        prompt = f"{wisdom_block}\n\n{prompt}" if prompt else wisdom_block

    # Recreate the tmux session using the same config as main()
    tmux_cmd = [
        "tmux", "new-session",
        "-d",
        "-s", session_name,
        "-c", work_dir,
        "-x", "220",
        "-y", "50",
        "exec zsh",
    ]
    subprocess.run(tmux_cmd, check=True, capture_output=True, text=True)

    time.sleep(2)
    _tmux_send(session_name, _build_claude_cmd(node_id, prd, mode), pause=8.0)
    _tmux_send(session_name, "/output-style orchestrator", pause=3.0, post_pause=5.0)
    if prompt:
        _tmux_send(session_name, prompt, pause=2.0)

    # Register new identity for the respawned instance
    worktree = "" if mode == "sdk" else f".claude/worktrees/{node_id}"
    identity = identity_registry.create_identity(
        role="orchestrator",
        name=node_id,
        session_id=session_name,
        worktree=worktree,
        predecessor_id=None,  # caller may set via --predecessor-id if needed
    )

    # Create or update hook for this orchestrator
    hook = hook_manager.create_hook(
        role="orchestrator",
        name=node_id,
    )

    return {
        "status": "respawned",
        "session": session_name,
        "respawn_count": respawn_count + 1,
        "hook_id": hook.get("hook_id"),
    }


def cleanup_orchestrator(
    session_name: str,
    repo_name: str,
    work_dir: str,
    *,
    project_root: str | None = None,
) -> dict:
    """Run post-completion cleanup for an orchestrator session.

    Discovers files changed during the session via git diff (HEAD~50..HEAD),
    refreshes the RepoMap baseline for those files, and returns a summary.
    Non-fatal — never raises.

    Args:
        session_name: tmux session name (used for log messages).
        repo_name: Repo name in .repomap/config.yaml.
        work_dir: Working directory of the orchestrator session (git repo root).
        project_root: Optional override for the project root path.

    Returns:
        Dict with: changed_files (list), refreshed_nodes (int), duration_seconds (float)
    """
    _project_root = Path(project_root or work_dir)

    # Get files changed by this session
    try:
        result = subprocess.run(
            ["git", "-C", work_dir, "diff", "--name-only", "HEAD~50..HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        changed_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except subprocess.SubprocessError as exc:
        logger.warning("cleanup_orchestrator: git diff failed: %s", exc)
        changed_files = []

    if not changed_files:
        logger.info("cleanup_orchestrator[%s]: no changed files detected", session_name)
        return {"changed_files": [], "refreshed_nodes": 0, "duration_seconds": 0.0}

    try:
        from cobuilder.bridge import scoped_refresh
        refresh_result = scoped_refresh(
            name=repo_name,
            scope=changed_files,
            project_root=_project_root,
        )
        logger.info(
            "cleanup_orchestrator[%s]: refreshed %d nodes in %.1fs",
            session_name,
            refresh_result.get("refreshed_nodes", 0),
            refresh_result.get("duration_seconds", 0.0),
        )
        return {
            "changed_files": changed_files,
            **refresh_result,
        }
    except Exception as exc:
        logger.error("cleanup_orchestrator[%s]: refresh failed: %s", session_name, exc)
        return {"changed_files": changed_files, "refreshed_nodes": 0, "error": str(exc)}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="spawn_orchestrator.py",
        description="Create a tmux session running Claude Code as orchestrator.",
    )
    parser.add_argument("--node", required=True, help="Node identifier")
    parser.add_argument("--prd", required=True, help="PRD reference (e.g., PRD-AUTH-001)")
    parser.add_argument("--worktree", required=False, help="DEPRECATED: use --repo-root instead")
    parser.add_argument("--repo-root", required=False, dest="repo_root",
                        help="Repo root directory (Claude creates worktree internally)")
    parser.add_argument("--session-name", default=None, dest="session_name",
                        help="tmux session name (default: orch-<node>)")
    parser.add_argument("--prompt", default=None,
                        help="Initial prompt to send after launching Claude")
    parser.add_argument("--max-respawn", type=int, default=3, dest="max_respawn",
                        help="Maximum respawn attempts if session dies (default: 3)")
    parser.add_argument("--predecessor-id", default=None, dest="predecessor_id",
                        help="agent_id of the previous orchestrator instance (for respawn tracking)")
    parser.add_argument("--on-cleanup", action="store_true", dest="on_cleanup",
                        help="Run cleanup mode (refresh baseline for session-changed files) instead of spawning")
    parser.add_argument("--repo-name", default="", dest="repo_name",
                        help="Repo name in .repomap/config.yaml (required for --on-cleanup)")
    parser.add_argument("--promise-id", default="", dest="promise_id",
                        help="Completion promise ID to inject baseline freshness AC into")
    parser.add_argument("--mode", choices=["sdk", "tmux", "headless"], default="tmux", dest="mode",
                        help="Launch mode: sdk (no --worktree, guardian already in worktree), "
                             "tmux (default, ccorch creates --worktree <node_id>), "
                             "or headless (claude -p CLI, structured JSON output)")

    args = parser.parse_args()

    # --on-cleanup: refresh RepoMap for session-changed files, then exit.
    if args.on_cleanup:
        cleanup_session = getattr(args, "session_name", None) or "unknown"
        result = cleanup_orchestrator(
            session_name=cleanup_session,
            repo_name=args.repo_name,
            work_dir=args.repo_root or str(Path.cwd()),
        )
        print(json.dumps(result))
        return

    session_name = args.session_name or f"orch-{args.node}"
    # Support both --repo-root (new) and --worktree (deprecated, same meaning now)
    work_dir = args.repo_root or args.worktree
    if not work_dir:
        print(json.dumps({
            "status": "error",
            "message": "Either --repo-root or --worktree (deprecated) is required",
        }))
        sys.exit(1)

    # Warn if work_dir does not contain a .claude/ directory.
    # Usually means --repo-root points at git root instead of project subdirectory.
    _claude_dir = Path(work_dir) / ".claude"
    if not _claude_dir.is_dir():
        print(
            json.dumps({
                "warning": (
                    f"--repo-root '{work_dir}' does not contain a .claude/ directory. "
                    "Claude Code may not find its project configuration or may create "
                    "worktrees in the wrong location. "
                    "Ensure --repo-root points to the directory containing .claude/ "
                    "(e.g., 'agencheck/' in a monorepo, not the monorepo root)."
                )
            }),
            file=sys.stderr,
        )

    # Validate session name: reject reserved s3-live- prefix
    if re.match(r"s3-live-", session_name):
        print(json.dumps({
            "status": "error",
            "message": (
                f"Session name '{session_name}' uses reserved 's3-live-' prefix. "
                "Use 'orch-' or 'runner-' prefix."
            ),
        }))
        sys.exit(1)

    # --- Headless mode: run claude -p inline, no tmux ---
    if args.mode == "headless":
        import asyncio

        # Build the prompt from --prompt arg (required for headless)
        full_prompt = args.prompt or f"Implement node {args.node} for {args.prd}"

        cmd, env = _build_headless_worker_cmd(
            task_prompt=full_prompt,
            work_dir=work_dir,
            node_id=args.node,
            pipeline_id=args.prd,
            runner_id=f"runner-{args.node}",
            prd_ref=args.prd,
        )

        timeout = 900
        result = asyncio.run(run_headless_worker(
            cmd=cmd,
            env=env,
            work_dir=work_dir,
            timeout_seconds=timeout,
        ))

        # Write result signal for runner_agent.py to detect
        signal_dir = Path(work_dir) / ".claude" / "signals"
        signal_dir.mkdir(parents=True, exist_ok=True)
        signal_file = signal_dir / f"{args.node}.json"
        signal_file.write_text(json.dumps(result, default=str))

        exit_code = result.get("exit_code", 1)
        print(json.dumps({
            "status": "ok" if exit_code == 0 else "error",
            "session": session_name,
            "mode": "headless",
            "exit_code": exit_code,
            "worker_result": result,
        }))
        sys.exit(0 if exit_code == 0 else 1)

    # tmux new-session — start a clean shell IN the target directory via -c.
    # We use "exec zsh" (not "claude" directly) because:
    # 1. CLAUDECODE env var must be unset to avoid nested-session error
    # 2. Shell environment (PATH, etc.) must be properly initialized
    tmux_cmd = [
        "tmux", "new-session",
        "-d",               # detached
        "-s", session_name,
        "-c", work_dir,     # tmux starts IN target dir
        "-x", "220",        # width
        "-y", "50",         # height
        "exec zsh",         # clean shell (ccorch pattern from MEMORY.md)
    ]

    try:
        subprocess.run(
            tmux_cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.strip() if exc.stderr else str(exc)
        print(json.dumps({
            "status": "error",
            "message": f"Failed to create tmux session: {error_msg}",
        }))
        sys.exit(1)
    except FileNotFoundError:
        print(json.dumps({
            "status": "error",
            "message": "tmux not found. Please install tmux.",
        }))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)

    # Wait for shell to initialize
    time.sleep(2)

    # Alive check: attempt respawn if session died immediately after creation
    respawn_count = 0
    if not check_orchestrator_alive(session_name):
        respawn_result = respawn_orchestrator(
            session_name=session_name,
            work_dir=work_dir,
            node_id=args.node,
            prompt=args.prompt,
            respawn_count=respawn_count,
            max_respawn=args.max_respawn,
            mode=args.mode,
            prd=args.prd,
        )
        if respawn_result["status"] == "error":
            print(json.dumps(respawn_result))
            sys.exit(1)
        respawn_count = respawn_result.get("respawn_count", 0)
        # Session was respawned with Claude and prompt already sent; output and return.
        print(json.dumps({
            "status": "ok",
            "session": session_name,
            "tmux_cmd": " ".join(shlex.quote(c) for c in tmux_cmd),
            "respawn_count": respawn_count,
        }))
        return

    # Launch Claude Code directly with explicit env vars (replaces ccorch shell function).
    # In sdk mode, guardian already runs in a worktree — no --worktree needed.
    # In tmux mode (default), Claude creates .claude/worktrees/<node_id>/ via --worktree.
    claude_launch_cmd = _build_claude_cmd(args.node, args.prd, args.mode)
    try:
        _tmux_send(
            session_name,
            claude_launch_cmd,
            pause=8.0,
        )
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.strip() if exc.stderr else str(exc)
        print(json.dumps({
            "status": "error",
            "message": f"Session created but failed to launch Claude: {error_msg}",
        }))
        sys.exit(1)

    # Set output style via slash command (not CLI flag)
    try:
        _tmux_send(session_name, "/output-style orchestrator", pause=3.0, post_pause=5.0)
    except subprocess.CalledProcessError as exc:
        error_msg = exc.stderr.strip() if exc.stderr else str(exc)
        print(json.dumps({
            "status": "error",
            "message": f"Session created but failed to set output style: {error_msg}",
        }))
        sys.exit(1)

    # Register agent identity after successful launch
    # In sdk mode, guardian already runs in a worktree so no separate worktree is created.
    orch_worktree = "" if args.mode == "sdk" else f".claude/worktrees/{args.node}"
    identity = identity_registry.create_identity(
        role="orchestrator",
        name=args.node,
        session_id=session_name,
        worktree=orch_worktree,
        predecessor_id=getattr(args, "predecessor_id", None),
    )

    # Create persistent hook for this orchestrator
    hook = hook_manager.create_hook(
        role="orchestrator",
        name=args.node,
    )

    # Send initial prompt if provided
    if args.prompt:
        try:
            _tmux_send(session_name, args.prompt, pause=2.0)
        except subprocess.CalledProcessError as exc:
            error_msg = exc.stderr.strip() if exc.stderr else str(exc)
            print(json.dumps({
                "status": "error",
                "message": f"Session created but failed to send prompt: {error_msg}",
            }))
            sys.exit(1)

    # Inject baseline freshness AC into completion promise if requested.
    if getattr(args, "promise_id", ""):
        cs_bin = Path(work_dir) / ".claude" / "scripts" / "completion-state" / "cs-promise"
        cs_cmd = [str(cs_bin)] if cs_bin.exists() else ["cs-promise"]  # fallback to PATH
        subprocess.run([
            *cs_cmd, "--add-ac", args.promise_id,
            "RepoMap baseline refreshed for all validated nodes (scoped_refresh called after each validated transition)",
        ], check=False)

    print(json.dumps({
        "status": "ok",
        "session": session_name,
        "tmux_cmd": " ".join(shlex.quote(c) for c in tmux_cmd),
        "respawn_count": respawn_count,
        "predecessor_id": getattr(args, "predecessor_id", None),
        "hook_id": hook.get("hook_id"),
    }))


if __name__ == "__main__":
    main()
