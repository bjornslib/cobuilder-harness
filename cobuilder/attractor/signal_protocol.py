"""Signal Protocol Library — Guardian Architecture Inter-Layer Communication.

Provides atomic signal file I/O for communication between Guardian (System 3),
Runner (Orchestrator), and Terminal (User) layers.

Signal files are JSON documents written atomically using a write-then-rename
pattern. They are stored in the signals directory and moved to processed/ once
consumed by the target layer.

Signal Naming Convention:
    {timestamp}-{source}-{target}-{signal_type}.json
    e.g.: 20260224T120000Z-runner-guardian-NEEDS_REVIEW.json

Signal File Format:
    {
        "source": "runner",
        "target": "guardian",
        "signal_type": "NEEDS_REVIEW",
        "timestamp": "20260224T120000Z",
        "payload": {"node_id": "impl_auth", "evidence_path": "/path", ...}
    }

Directory Resolution (in order of precedence):
    1. Explicit ``signals_dir`` argument
    2. ``ATTRACTOR_SIGNALS_DIR`` environment variable
    3. ``{git_root}/.claude/attractor/signals/`` (found via .git walk)
    4. ``~/.claude/attractor/signals/`` (fallback)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Signal type constants
# ---------------------------------------------------------------------------

# Runner → Guardian signals
NEEDS_REVIEW       = "NEEDS_REVIEW"       # payload: {node_id, commit, summary}
NEEDS_INPUT        = "NEEDS_INPUT"        # payload: {node_id, question, options}
VIOLATION          = "VIOLATION"          # payload: {node_id, reason}
ORCHESTRATOR_STUCK = "ORCHESTRATOR_STUCK" # payload: {node_id, duration, last_output}
ORCHESTRATOR_CRASHED = "ORCHESTRATOR_CRASHED"  # payload: {node_id, last_output}
NODE_COMPLETE      = "NODE_COMPLETE"      # payload: {node_id, commit, summary}
VALIDATION_COMPLETE = "VALIDATION_COMPLETE"  # payload: {node_id, summary}

# Guardian → Runner signals
VALIDATION_PASSED  = "VALIDATION_PASSED"  # payload: {node_id}
VALIDATION_FAILED  = "VALIDATION_FAILED"  # payload: {node_id, feedback}
INPUT_RESPONSE     = "INPUT_RESPONSE"     # payload: {node_id, response}
KILL_ORCHESTRATOR  = "KILL_ORCHESTRATOR"  # payload: {node_id, reason}
GUIDANCE           = "GUIDANCE"           # payload: {node_id, message}

# Merge queue signals (Runner → Guardian, Guardian → Runner)
MERGE_READY    = "MERGE_READY"    # payload: {node_id, branch}
MERGE_COMPLETE = "MERGE_COMPLETE" # payload: {node_id, branch, entry_id}
MERGE_FAILED   = "MERGE_FAILED"   # payload: {node_id, branch, error}

# Runner lifecycle signals (runner → guardian) — Epic: Mode-Switching Runner
RUNNER_EXITED  = "RUNNER_EXITED"  # payload: {node_id, prd_ref, mode, reason}

# Agent lifecycle signals (any → guardian) — Epic 1: Identity Registry
AGENT_REGISTERED = "AGENT_REGISTERED"  # payload: {agent_id, role, name, session_id, worktree}
AGENT_CRASHED    = "AGENT_CRASHED"     # payload: {agent_id, role, name, crashed_at}
AGENT_TERMINATED = "AGENT_TERMINATED"  # payload: {agent_id, role, name, terminated_at}


# ---------------------------------------------------------------------------
# Directory resolution
# ---------------------------------------------------------------------------

def _find_git_root(start: str) -> Optional[str]:
    """Walk up directory tree to find .git root. Returns None if not found."""
    current = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def _default_signals_dir() -> str:
    """Resolve the default signals directory using env var or git root."""
    env_dir = os.environ.get("ATTRACTOR_SIGNALS_DIR")
    if env_dir:
        return env_dir

    git_root = _find_git_root(os.getcwd())
    if git_root:
        return os.path.join(git_root, ".claude", "attractor", "signals")

    # Fallback to home directory
    return os.path.join(os.path.expanduser("~"), ".claude", "attractor", "signals")


def _resolve_signals_dir(signals_dir: Optional[str]) -> str:
    """Return signals_dir if provided, otherwise resolve default."""
    return signals_dir if signals_dir is not None else _default_signals_dir()


def _ensure_dirs(signals_dir: str) -> None:
    """Create signals_dir and signals_dir/processed/ if they don't exist."""
    os.makedirs(signals_dir, exist_ok=True)
    os.makedirs(os.path.join(signals_dir, "processed"), exist_ok=True)


# ---------------------------------------------------------------------------
# Core signal functions
# ---------------------------------------------------------------------------

def write_signal(
    source: str,
    target: str,
    signal_type: str,
    payload: dict,
    signals_dir: Optional[str] = None,
) -> str:
    """Write signal file atomically. Returns path to signal file.

    Uses a write-to-.tmp-then-rename pattern to ensure atomic visibility.
    The signal file is only visible to readers once fully written.

    Args:
        source: Source layer identifier (e.g., "runner", "guardian").
        target: Target layer identifier (e.g., "guardian", "runner", "terminal").
        signal_type: Signal type constant (e.g., "NEEDS_REVIEW", "APPROVED").
        payload: Arbitrary dict with signal-specific data.
        signals_dir: Override the default signals directory.

    Returns:
        Absolute path to the written signal file.
    """
    resolved_dir = _resolve_signals_dir(signals_dir)
    _ensure_dirs(resolved_dir)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{timestamp}-{source}-{target}-{signal_type}.json"
    final_path = os.path.join(resolved_dir, filename)
    tmp_path = final_path + ".tmp"

    content = {
        "source": source,
        "target": target,
        "signal_type": signal_type,
        "timestamp": timestamp,
        "payload": payload,
    }

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(content, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())

    os.rename(tmp_path, final_path)
    return final_path


def read_signal(path: str) -> dict:
    """Parse signal file. Returns dict with source, target, signal_type, timestamp, payload.

    Args:
        path: Absolute or relative path to the signal JSON file.

    Returns:
        Parsed signal dict.

    Raises:
        FileNotFoundError: If the path does not exist.
        json.JSONDecodeError: If the file contains invalid JSON.
    """
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def move_to_processed(path: str) -> str:
    """Move signal file to processed/ subdirectory. Returns new path.

    Args:
        path: Absolute path to the signal file to move.

    Returns:
        New absolute path inside the processed/ subdirectory.
    """
    signals_dir = os.path.dirname(path)
    processed_dir = os.path.join(signals_dir, "processed")
    os.makedirs(processed_dir, exist_ok=True)

    filename = os.path.basename(path)
    new_path = os.path.join(processed_dir, filename)
    os.rename(path, new_path)
    return new_path


def list_signals(
    target_layer: Optional[str] = None,
    signals_dir: Optional[str] = None,
) -> list:
    """List signal files, optionally filtered by target_layer.

    Only lists files in the top-level signals directory (not processed/).
    Files are sorted by name (which sorts chronologically due to timestamp prefix).

    Args:
        target_layer: If provided, only return signals with this target in the filename.
        signals_dir: Override the default signals directory.

    Returns:
        List of absolute paths to matching signal files.
    """
    resolved_dir = _resolve_signals_dir(signals_dir)
    if not os.path.isdir(resolved_dir):
        return []

    results = []
    try:
        entries = os.listdir(resolved_dir)
    except OSError:
        return []

    for fname in sorted(entries):
        # Only include .json files, skip the processed subdir
        if not fname.endswith(".json"):
            continue
        if fname.endswith(".tmp"):
            continue

        if target_layer is not None:
            # Filename pattern: {ts}-{source}-{target}-{type}.json
            # We match on the target segment.
            parts = fname[:-5].split("-", 3)  # strip .json, split max 4 parts
            # Handle timestamps like 20260224T120000Z which contain no dashes
            # Full pattern: {ts}-{source}-{target}-{signal_type}
            # We need to check if target_layer appears as the target segment
            # The timestamp has no dashes (e.g., 20260224T120000Z)
            # So split gives: [timestamp, source, target, signal_type]
            if len(parts) >= 3 and parts[2] != target_layer:
                continue

        results.append(os.path.join(resolved_dir, fname))

    return results


def wait_for_signal(
    target_layer: str,
    timeout: float = 300.0,
    signals_dir: Optional[str] = None,
    poll_interval: float = 5.0,
) -> dict:
    """Block until a signal for target_layer appears. Returns signal dict.

    Polls the signals directory at ``poll_interval`` second intervals until
    a signal file matching ``target_layer`` appears or ``timeout`` is reached.
    After reading, moves the signal file to processed/.

    Args:
        target_layer: The target layer to wait for (e.g., "guardian", "runner").
        timeout: Maximum seconds to wait before raising TimeoutError.
        signals_dir: Override the default signals directory.
        poll_interval: Seconds between directory polls.

    Returns:
        Parsed signal dict from the first matching signal file.

    Raises:
        TimeoutError: If no signal appears within ``timeout`` seconds.
    """
    resolved_dir = _resolve_signals_dir(signals_dir)
    _ensure_dirs(resolved_dir)

    deadline = time.monotonic() + timeout

    while True:
        signals = list_signals(target_layer=target_layer, signals_dir=resolved_dir)
        if signals:
            # Take the first (oldest) signal
            signal_path = signals[0]
            try:
                data = read_signal(signal_path)
                move_to_processed(signal_path)
                return data
            except (FileNotFoundError, json.JSONDecodeError):
                # File may have been consumed by another process; continue polling
                pass

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"No signal for target '{target_layer}' within {timeout}s"
            )

        sleep_time = min(poll_interval, remaining)
        if sleep_time <= 0:
            raise TimeoutError(
                f"No signal for target '{target_layer}' within {timeout}s"
            )
        time.sleep(sleep_time)


# ---------------------------------------------------------------------------
# Agent lifecycle signal helpers
# ---------------------------------------------------------------------------


def write_runner_exited(
    node_id: str,
    prd_ref: str,
    mode: str,
    reason: str,
    signals_dir: Optional[str] = None,
) -> str:
    """Write a RUNNER_EXITED signal to the guardian.

    Called by RunnerStateMachine's safety net (try/finally) when the runner
    exits without reaching the COMPLETE mode. This allows the guardian to
    detect and handle unexpected runner terminations.

    Args:
        node_id: Pipeline node identifier being monitored by the runner.
        prd_ref: PRD reference string (e.g., "PRD-AUTH-001").
        mode: Final mode the runner was in when it exited (e.g., "FAILED").
        reason: Human-readable reason for the exit (e.g., "max_cycles_exceeded").
        signals_dir: Override the default signals directory.

    Returns:
        Absolute path to the written signal file.
    """
    return write_signal(
        source="runner",
        target="guardian",
        signal_type=RUNNER_EXITED,
        payload={
            "node_id": node_id,
            "prd_ref": prd_ref,
            "mode": mode,
            "reason": reason,
        },
        signals_dir=signals_dir,
    )


def write_agent_registered(
    agent_id: str,
    role: str,
    name: str,
    session_id: str,
    worktree: str,
    signals_dir: Optional[str] = None,
) -> str:
    """Write an AGENT_REGISTERED signal to the guardian.

    Args:
        agent_id: Unique agent identifier (from identity_registry).
        role: Agent role (e.g., "orchestrator", "runner", "guardian").
        name: Agent name / node identifier.
        session_id: Session identifier string.
        worktree: Worktree path for the agent.
        signals_dir: Override the default signals directory.

    Returns:
        Absolute path to the written signal file.
    """
    return write_signal(
        source=role,
        target="guardian",
        signal_type=AGENT_REGISTERED,
        payload={
            "agent_id": agent_id,
            "role": role,
            "name": name,
            "session_id": session_id,
            "worktree": worktree,
        },
        signals_dir=signals_dir,
    )


def write_agent_crashed(
    agent_id: str,
    role: str,
    name: str,
    crashed_at: str,
    signals_dir: Optional[str] = None,
) -> str:
    """Write an AGENT_CRASHED signal to the guardian.

    Args:
        agent_id: Unique agent identifier (from identity_registry).
        role: Agent role.
        name: Agent name.
        crashed_at: ISO 8601 timestamp string of when the crash occurred.
        signals_dir: Override the default signals directory.

    Returns:
        Absolute path to the written signal file.
    """
    return write_signal(
        source=role,
        target="guardian",
        signal_type=AGENT_CRASHED,
        payload={
            "agent_id": agent_id,
            "role": role,
            "name": name,
            "crashed_at": crashed_at,
        },
        signals_dir=signals_dir,
    )


def write_agent_terminated(
    agent_id: str,
    role: str,
    name: str,
    terminated_at: str,
    signals_dir: Optional[str] = None,
) -> str:
    """Write an AGENT_TERMINATED signal to the guardian.

    Args:
        agent_id: Unique agent identifier (from identity_registry).
        role: Agent role.
        name: Agent name.
        terminated_at: ISO 8601 timestamp string of when termination occurred.
        signals_dir: Override the default signals directory.

    Returns:
        Absolute path to the written signal file.
    """
    return write_signal(
        source=role,
        target="guardian",
        signal_type=AGENT_TERMINATED,
        payload={
            "agent_id": agent_id,
            "role": role,
            "name": name,
            "terminated_at": terminated_at,
        },
        signals_dir=signals_dir,
    )
