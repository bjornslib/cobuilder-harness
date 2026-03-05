"""dispatch_worker.py — Headless worker dispatch via ``claude -p``.

Extracted from spawn_orchestrator.py to consolidate the 3-layer architecture:
    Guardian → Runner → dispatch_worker.py → claude -p --output-format stream-json

Provides two functions:
    _build_headless_worker_cmd()  — Build the CLI command and environment
    run_headless_worker()         — Execute the worker subprocess with JSONL streaming

Usage (programmatic):
    from dispatch_worker import _build_headless_worker_cmd, run_headless_worker

    cmd, env = _build_headless_worker_cmd(
        task_prompt="Implement auth module",
        work_dir="/path/to/repo",
        node_id="impl_auth",
        pipeline_id="PRD-AUTH-001",
    )
    result = await run_headless_worker(cmd, env, work_dir="/path/to/repo")
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Keys that load_attractor_env() is permitted to return.
_ATTRACTOR_ENV_KEYS = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"})


def load_attractor_env() -> dict[str, str]:
    """Load Anthropic credentials from ``.claude/attractor/.env``.

    Walks up from this script's location to find the ``.claude/attractor/.env``
    file and parses lines in the forms::

        export KEY=VALUE
        KEY=VALUE
        KEY="VALUE"
        KEY='VALUE'

    Only keys in ``_ATTRACTOR_ENV_KEYS`` (``ANTHROPIC_API_KEY``,
    ``ANTHROPIC_BASE_URL``, ``ANTHROPIC_MODEL``) are returned; all other
    lines are silently ignored.

    Returns:
        Dict of allowed credential keys → values.  Returns ``{}`` if the
        file is missing or any parse error occurs.
    """
    # Resolve .claude/attractor/.env relative to this script's parent tree.
    # This script lives at .claude/scripts/attractor/dispatch_worker.py, so:
    #   script_dir           = .claude/scripts/attractor/
    #   script_dir.parent    = .claude/scripts/
    #   script_dir.parent.parent = .claude/
    # Therefore the .env path is script_dir.parent.parent / "attractor" / ".env"
    script_dir = Path(__file__).resolve().parent
    env_path = script_dir.parent.parent / "attractor" / ".env"

    if not env_path.exists():
        logger.debug("load_attractor_env: %s not found, skipping", env_path)
        return {}

    result: dict[str, str] = {}
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip leading "export "
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key not in _ATTRACTOR_ENV_KEYS:
                continue
            # Strip surrounding quotes (" or ')
            value = value.strip()
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            result[key] = value
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_attractor_env: failed to parse %s: %s", env_path, exc)
        return {}

    logger.debug("load_attractor_env: loaded keys %s", list(result))
    return result


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
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        # Bypass all MCP server initialization for headless workers.
        # Without this, 11+ MCP servers from .mcp.json cause extreme
        # startup delays (30s+) or hangs in subprocess mode.
        "--mcp-config", '{"mcpServers":{}}',
        "--strict-mcp-config",
    ]

    # Layer 3: IDENTITY as env vars (zero context token cost)
    env = dict(os.environ)
    # Overlay attractor-specific credentials for headless workers.
    env.update(load_attractor_env())
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
    on_event: Callable[[dict], None] | None = None,
) -> dict:
    """Run a headless worker via subprocess, streaming JSONL output line-by-line.

    Uses ``subprocess.Popen`` with ``--output-format stream-json`` to read JSONL
    events in real time.  Each line is a JSON object with a ``type`` field.  The
    final ``{"type": "result", ...}`` line carries the same payload that the old
    ``--output-format json`` returned, so the return value remains backward
    compatible.

    Args:
        cmd: Command list (typically from :func:`_build_headless_worker_cmd`).
        env: Environment dict for the subprocess.
        work_dir: Working directory for the subprocess.
        timeout_seconds: Maximum wall-clock time before killing the worker.
        on_event: Optional callback invoked for every successfully parsed JSONL
            event.  Receives the parsed ``dict``.  Exceptions raised inside the
            callback are logged and suppressed.

    Returns:
        Dict with ``status`` (``"success"``, ``"error"``, or ``"timeout"``),
        plus output or error details, plus ``events`` (list of all parsed events).

        On success:
            ``{"status": "success", "output": <result_event>, "exit_code": 0,
               "events": [...]}``
        On error:
            ``{"status": "error", "exit_code": N, "stdout": "...",
               "stderr": "...", "events": [...]}``
        On timeout:
            ``{"status": "timeout", "events": [...]}``
    """
    events: list[dict] = []
    stderr_lines: list[str] = []

    process = subprocess.Popen(
        cmd,
        cwd=work_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Drain stderr in a background thread to prevent the pipe from blocking
    # when the subprocess writes more than the OS pipe buffer allows.
    def _drain_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stderr_lines.append(line)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    timed_out = False
    assert process.stdout is not None
    try:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("run_headless_worker: skipping non-JSON line: %.200s", line)
                continue

            events.append(event)

            if on_event is not None:
                try:
                    on_event(event)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("run_headless_worker: on_event callback raised: %s", exc)

            # Check wall-clock timeout after each event to allow early detection.
            # process.poll() is non-blocking; None means still running.
    except Exception:  # noqa: BLE001
        pass
    finally:
        # Enforce hard timeout: if the process is still running after
        # ``timeout_seconds`` the caller's wall-clock limit has been exceeded.
        # We use communicate(timeout=...) only if the process hasn't exited yet
        # so that we don't re-read stdout (already consumed above).
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            process.wait()

    stderr_thread.join(timeout=5)
    stderr_combined = "".join(stderr_lines)

    if timed_out:
        return {"status": "timeout", "events": events}

    exit_code = process.returncode

    # Locate the final result event (last event with type=="result")
    result_event: dict | None = None
    for event in reversed(events):
        if event.get("type") == "result":
            result_event = event
            break

    if exit_code == 0:
        # Use the result event when present; fall back to the whole events list.
        output: object = result_event if result_event is not None else events
        return {"status": "success", "output": output, "exit_code": 0, "events": events}
    else:
        stdout_tail = "".join(
            json.dumps(e) for e in events[-10:]
        )[-2000:]
        return {
            "status": "error",
            "exit_code": exit_code,
            "stdout": stdout_tail,
            "stderr": stderr_combined[-2000:],
            "events": events,
        }
