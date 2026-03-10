"""Hook Manager — Persistent work state hooks for session resilience.

Provides atomic file-based hook records that persist an agent's work state
across session boundaries. Hooks capture the current phase, last committed
node, and resumption instructions so that a new agent instance can resume
from exactly where the previous one left off.

Hook files are JSON documents written atomically using the write-then-rename
pattern (same as signal_protocol.py and identity_registry.py). They are
stored per-agent in {state_dir}/{role}-{name}.json.

Hook File Schema:
    {
        "hook_id": "{role}-{name}-{timestamp}",
        "role": "orchestrator",
        "name": "impl_auth",
        "phase": "planning",
        "last_committed_node": null,
        "resumption_instructions": "",
        "predecessor_hook_id": null,
        "created_at": "2026-02-26T12:00:00Z",
        "updated_at": "2026-02-26T12:00:00Z",
        "merged_at": null
    }

Valid phases:
    planning, executing, impl_complete, validating, merged

Directory Resolution (in order of precedence):
    1. Explicit ``state_dir`` argument
    2. ``ATTRACTOR_STATE_DIR`` environment variable (hooks/ subdirectory)
    3. ``{git_root}/.claude/state/hooks/`` (found via .git walk)
    4. ``~/.claude/state/hooks/`` (fallback)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Valid phase values
# ---------------------------------------------------------------------------

VALID_PHASES = frozenset([
    "planning",
    "executing",
    "impl_complete",
    "validating",
    "merged",
])


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


def _hooks_dir(state_dir: Optional[str] = None) -> str:
    """Resolve the hooks state directory.

    Resolution order:
    1. Explicit ``state_dir`` argument (used as-is)
    2. ``ATTRACTOR_STATE_DIR`` env var + /hooks/ subdirectory
    3. ``{git_root}/.claude/state/hooks/``
    4. ``~/.claude/state/hooks/`` (fallback)

    Args:
        state_dir: Explicit state directory override.

    Returns:
        Absolute path to the hooks directory.
    """
    if state_dir is not None:
        return state_dir

    env_dir = os.environ.get("ATTRACTOR_STATE_DIR")
    if env_dir:
        return os.path.join(env_dir, "hooks")

    git_root = _find_git_root(os.getcwd())
    if git_root:
        return os.path.join(git_root, ".claude", "state", "hooks")

    return os.path.join(os.path.expanduser("~"), ".claude", "state", "hooks")


def _hook_path(role: str, name: str, state_dir: Optional[str] = None) -> str:
    """Return the path for a hook file."""
    return os.path.join(_hooks_dir(state_dir), f"{role}-{name}.json")


def _now_iso() -> str:
    """Return current UTC datetime as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_hook_id(role: str, name: str) -> str:
    """Generate a unique hook ID from role, name, and current timestamp."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{role}-{name}-{ts}"


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def _write_hook(data: dict, path: str) -> None:
    """Write hook data to path atomically (write to .tmp, then rename).

    Args:
        data: Hook dict to serialise.
        path: Destination path for the hook JSON file.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(tmp_path, path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_hook(
    role: str,
    name: str,
    phase: str = "planning",
    predecessor_hook_id: Optional[str] = None,
    state_dir: Optional[str] = None,
) -> dict:
    """Create a new hook record for an agent.

    Writes a new hook file at ``{state_dir}/{role}-{name}.json``.
    Overwrites any existing hook with the same role+name.

    Args:
        role: Agent role (e.g., "orchestrator", "runner").
        name: Agent name / node identifier (e.g., "impl_auth").
        phase: Initial work phase (default: "planning").
        predecessor_hook_id: hook_id of the previous instance's hook (for respawn tracking).
        state_dir: Override the default hooks directory.

    Returns:
        The created hook dict.

    Raises:
        ValueError: If phase is not a valid phase value.
    """
    if phase not in VALID_PHASES:
        raise ValueError(
            f"Invalid phase '{phase}'. Valid phases: {sorted(VALID_PHASES)}"
        )

    now = _now_iso()
    data = {
        "hook_id": _make_hook_id(role, name),
        "role": role,
        "name": name,
        "phase": phase,
        "last_committed_node": None,
        "resumption_instructions": "",
        "predecessor_hook_id": predecessor_hook_id,
        "created_at": now,
        "updated_at": now,
        "merged_at": None,
    }
    path = _hook_path(role, name, state_dir)
    _write_hook(data, path)
    return data


def read_hook(
    role: str,
    name: str,
    state_dir: Optional[str] = None,
) -> Optional[dict]:
    """Read an existing hook record.

    Args:
        role: Agent role.
        name: Agent name.
        state_dir: Override the default hooks directory.

    Returns:
        Hook dict, or None if the file does not exist.
    """
    path = _hook_path(role, name, state_dir)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def update_phase(
    role: str,
    name: str,
    phase: str,
    state_dir: Optional[str] = None,
) -> dict:
    """Update the work phase of a hook record.

    Args:
        role: Agent role.
        name: Agent name.
        phase: New phase value.
        state_dir: Override the default hooks directory.

    Returns:
        Updated hook dict.

    Raises:
        FileNotFoundError: If no hook file exists for this role+name.
        ValueError: If phase is not a valid phase value.
    """
    if phase not in VALID_PHASES:
        raise ValueError(
            f"Invalid phase '{phase}'. Valid phases: {sorted(VALID_PHASES)}"
        )

    path = _hook_path(role, name, state_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No hook found for {role}/{name}. Call create_hook() first."
        )

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["phase"] = phase
    data["updated_at"] = _now_iso()
    _write_hook(data, path)
    return data


def update_resumption_instructions(
    role: str,
    name: str,
    instructions: str,
    last_committed_node: Optional[str] = None,
    state_dir: Optional[str] = None,
) -> dict:
    """Update resumption instructions and optionally the last committed node.

    Used by agents to record the exact point they reached so a successor
    can resume from the same position.

    Args:
        role: Agent role.
        name: Agent name.
        instructions: Human-readable instructions for resuming work.
        last_committed_node: Optional node ID of the last successfully committed node.
        state_dir: Override the default hooks directory.

    Returns:
        Updated hook dict.

    Raises:
        FileNotFoundError: If no hook file exists for this role+name.
    """
    path = _hook_path(role, name, state_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No hook found for {role}/{name}. Call create_hook() first."
        )

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["resumption_instructions"] = instructions
    if last_committed_node is not None:
        data["last_committed_node"] = last_committed_node
    data["updated_at"] = _now_iso()
    _write_hook(data, path)
    return data


def mark_merged(
    role: str,
    name: str,
    state_dir: Optional[str] = None,
) -> dict:
    """Mark a hook as merged (branch successfully merged into main).

    Sets phase to "merged" and records merged_at timestamp.

    Args:
        role: Agent role.
        name: Agent name.
        state_dir: Override the default hooks directory.

    Returns:
        Updated hook dict.

    Raises:
        FileNotFoundError: If no hook file exists for this role+name.
    """
    path = _hook_path(role, name, state_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No hook found for {role}/{name}. Call create_hook() first."
        )

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["phase"] = "merged"
    data["merged_at"] = _now_iso()
    data["updated_at"] = _now_iso()
    _write_hook(data, path)
    return data


def build_wisdom_prompt_block(hook: dict) -> str:
    """Generate skip instructions from hook state for respawned orchestrator.

    Args:
        hook: Hook dict as returned by read_hook() or create_hook().

    Returns:
        A formatted string block suitable for injection into an orchestrator's
        system prompt to guide it toward the correct resumption point.
    """
    phase = hook.get("phase", "planning")
    instructions = hook.get("resumption_instructions", "")
    last_node = hook.get("last_committed_node", "")

    lines = ["## RESUMPTION CONTEXT (from previous session)"]
    lines.append(f"Previous phase reached: {phase}")
    if last_node:
        lines.append(f"Last committed node: {last_node}")
    if phase in ("executing", "impl_complete", "validating"):
        lines.append(f"SKIP planning phase — go directly to {phase}")
    if instructions:
        lines.append(f"Resumption notes: {instructions}")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Hook Manager CLI")
    subparsers = parser.add_subparsers(dest="command")

    # update-phase
    p_up = subparsers.add_parser("update-phase", help="Update hook phase")
    p_up.add_argument("role")
    p_up.add_argument("name")
    p_up.add_argument("phase", choices=["planning", "executing", "impl_complete", "validating", "merged"])

    # read
    p_rd = subparsers.add_parser("read", help="Read hook JSON")
    p_rd.add_argument("role")
    p_rd.add_argument("name")

    # update-resumption
    p_ur = subparsers.add_parser("update-resumption", help="Update resumption instructions")
    p_ur.add_argument("role")
    p_ur.add_argument("name")
    p_ur.add_argument("instructions")

    args = parser.parse_args()

    if args.command == "update-phase":
        try:
            data = update_phase(args.role, args.name, args.phase)
            print(json.dumps({"status": "ok", "phase": data["phase"]}))
            sys.exit(0)
        except (FileNotFoundError, ValueError) as e:
            print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
            sys.exit(1)

    elif args.command == "read":
        data = read_hook(args.role, args.name)
        if data is None:
            print(json.dumps({"status": "error", "message": f"No hook for {args.role}/{args.name}"}), file=sys.stderr)
            sys.exit(1)
        print(json.dumps(data))
        sys.exit(0)

    elif args.command == "update-resumption":
        try:
            data = update_resumption_instructions(args.role, args.name, args.instructions)
            print(json.dumps({"status": "ok"}))
            sys.exit(0)
        except FileNotFoundError as e:
            print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
            sys.exit(1)

    else:
        parser.print_help()
        sys.exit(1)
