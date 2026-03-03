"""spawn_runner.py — Launch Runner as Agent SDK subprocess.

Usage:
    python spawn_runner.py --node <node_id> --prd <prd_ref>
        [--solution-design <path>] [--acceptance <text>]
        [--target-dir <path>] [--bead-id <id>]

This is the Runner launch entrypoint. Registers identity and hook for the
runner, then launches runner_agent.py as a detached subprocess with a
cleaned environment (CLAUDECODE removed). Writes a state file with the PID
using the atomic tmp+rename pattern and outputs JSON confirming the launch.

Output (stdout, JSON):
    {
        "status": "ok",
        "node": "<node_id>",
        "prd": "<prd_ref>",
        "runner_pid": <pid>,
        "state_file": "<path>",
        "identity_file": "<path>",
        "hook_file": "<path>"
    }

On error:
    {"status": "error", "message": "<error>"}
    exits with code 1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

import identity_registry  # noqa: E402 — must follow sys.path setup
import hook_manager  # noqa: E402 — must follow sys.path setup


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


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="spawn_runner.py",
        description="Launch runner_agent.py as a subprocess with identity and hook registration.",
    )
    parser.add_argument("--node", required=True, dest="node_id", help="Node identifier")
    parser.add_argument("--prd", required=True, dest="prd_ref", help="PRD reference (e.g., PRD-AUTH-001)")
    parser.add_argument("--solution-design", default=None, dest="solution_design",
                        help="Path to solution design document")
    parser.add_argument("--acceptance", default=None,
                        help="Acceptance criteria text")
    parser.add_argument("--target-dir", required=True, dest="target_dir",
                        help="Target working directory for the runner")
    parser.add_argument("--bead-id", default=None, dest="bead_id",
                        help="Beads issue/task identifier")
    parser.add_argument("--mode", choices=["sdk", "tmux", "headless"], default="tmux", dest="mode",
                        help="Launch mode forwarded to runner_agent.py and spawn_orchestrator.py "
                             "(sdk: no --worktree; tmux: default with --worktree; "
                             "headless: claude -p CLI with JSON output)")
    parser.add_argument("--dot-file", default=None, dest="dot_file",
                        help="Path to pipeline .dot file; enables state machine monitoring mode")

    args = parser.parse_args()

    # 1. Register identity for runner
    try:
        identity_registry.create_identity(
            role="runner",
            name=args.node_id,
            session_id=f"runner-{args.node_id}",
            worktree=args.target_dir,
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "message": f"Identity registration failed: {exc}"}))
        sys.exit(1)

    # 2. Create hook for runner
    try:
        hook_manager.create_hook(
            role="runner",
            name=args.node_id,
            phase="planning",
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "message": f"Hook creation failed: {exc}"}))
        sys.exit(1)

    # 3. Build runner command
    # runner_agent.py accepts: --node, --prd, --session, --target-dir,
    #   --solution-design, --bead-id (confirmed by reading parse_args())
    runner_script = os.path.join(_DIR, "runner_agent.py")
    cmd = [sys.executable, runner_script,
           "--node", args.node_id,
           "--prd", args.prd_ref,
           "--session", f"orch-{args.node_id}",
           "--target-dir", args.target_dir,
           "--mode", args.mode]

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
        stdout_log_path = os.path.join(log_dir, f"{timestamp_log}-{args.node_id}-stdout.log")
        stderr_log_path = os.path.join(log_dir, f"{timestamp_log}-{args.node_id}-stderr.log")
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
        state_filename = f"{timestamp}-{args.node_id}-{args.prd_ref}.json"
        state_path = os.path.join(state_dir, state_filename)

        state_data = {
            "spawned_at": timestamp,
            "status": "running",
            "runner_pid": proc.pid,
            "node_id": args.node_id,
            "prd_ref": args.prd_ref,
            "target_dir": args.target_dir,
            "identity_file": f".claude/state/identities/runner-{args.node_id}.json",
            "hook_file": f".claude/state/hooks/runner-{args.node_id}.json",
            "runner_config": {
                "node_id": args.node_id,
                "prd_ref": args.prd_ref,
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
            "node": args.node_id,
            "prd": args.prd_ref,
            "runner_pid": proc.pid,
            "state_file": state_path,
            "identity_file": state_data["identity_file"],
            "hook_file": state_data["hook_file"],
            "runner_config": state_data["runner_config"],
        }))

    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
