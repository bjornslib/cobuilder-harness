"""Sequential Merge Queue — Guardian Architecture.

Provides an atomic, FIFO merge queue for serializing branch merges into main.
Each pipeline node that reaches impl_complete is enqueued; merges are processed
one at a time: rebase-on-main → test → fast-forward merge.

Queue file: {git_root}/.claude/state/merge-queue.json
  (override via PIPELINE_MERGE_QUEUE_DIR env var or explicit state_dir arg)

Entry lifecycle:
    pending → in_progress → completed | failed

Usage:
    from cobuilder.engine.merge_queue import enqueue, dequeue_next, process_next

    # When a node reaches impl_complete:
    entry = enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/path/to/repo")

    # Guardian calls this to advance the queue:
    result = process_next()  # returns {"success": bool, "entry": {...}, "error": str | None}
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from typing import Optional


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


def _queue_path(state_dir: Optional[str] = None) -> str:
    """Resolve path to merge-queue.json.

    Resolution order:
    1. Explicit ``state_dir`` argument
    2. ``PIPELINE_MERGE_QUEUE_DIR`` environment variable
    3. ``{git_root}/.claude/state/merge-queue.json``
    4. ``~/.claude/state/merge-queue.json`` (fallback)

    Args:
        state_dir: Optional override for the state directory.

    Returns:
        Absolute path to merge-queue.json.
    """
    if state_dir is not None:
        return os.path.join(state_dir, "merge-queue.json")

    env_dir = os.environ.get("PIPELINE_MERGE_QUEUE_DIR")
    if env_dir:
        return os.path.join(env_dir, "merge-queue.json")

    git_root = _find_git_root(os.getcwd())
    if git_root:
        return os.path.join(git_root, ".claude", "state", "merge-queue.json")

    # Fallback to home directory
    return os.path.join(os.path.expanduser("~"), ".claude", "state", "merge-queue.json")


def _empty_queue() -> dict:
    """Return the canonical empty queue structure."""
    return {
        "entries": [],
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


def _read_queue(state_dir: Optional[str] = None) -> dict:
    """Read queue JSON file. If missing or corrupt, return empty queue.

    Args:
        state_dir: Optional override for the state directory.

    Returns:
        Queue dict with ``entries`` list and ``last_updated`` timestamp.
    """
    path = _queue_path(state_dir)
    if not os.path.isfile(path):
        return _empty_queue()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        # Ensure required keys exist
        if "entries" not in data:
            data["entries"] = []
        if "last_updated" not in data:
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_queue()


def _write_queue(data: dict, state_dir: Optional[str] = None) -> None:
    """Atomically write queue JSON to disk using tmp+rename pattern.

    The file is only visible to readers once fully written, preventing
    partial reads during concurrent access.

    Args:
        data: Queue dict to serialise.
        state_dir: Optional override for the state directory.
    """
    path = _queue_path(state_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"

    data["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())

    os.rename(tmp_path, path)


# ---------------------------------------------------------------------------
# Public queue operations
# ---------------------------------------------------------------------------


def enqueue(
    node_id: str,
    branch: str,
    repo_root: str,
    state_dir: Optional[str] = None,
) -> dict:
    """Add a new pending entry to the merge queue.

    If an entry for the same ``node_id`` already exists (in any status),
    it is returned as-is without creating a duplicate.

    Args:
        node_id: Pipeline node identifier (e.g., ``impl_auth``).
        branch: Git branch name to merge (e.g., ``worktree-impl_auth``).
        repo_root: Absolute path to the repository root.
        state_dir: Optional override for the state directory.

    Returns:
        The newly created (or existing) entry dict.
    """
    data = _read_queue(state_dir)

    # Idempotent: do not add duplicate entries for the same node_id
    for existing in data["entries"]:
        if existing["node_id"] == node_id:
            return existing

    timestamp = datetime.now(timezone.utc).isoformat()
    entry_id = f"mq-{node_id}-{int(time.time())}"

    entry = {
        "entry_id": entry_id,
        "node_id": node_id,
        "branch": branch,
        "repo_root": repo_root,
        "enqueued_at": timestamp,
        "status": "pending",
        "started_at": None,
        "completed_at": None,
        "error": None,
    }

    data["entries"].append(entry)
    _write_queue(data, state_dir)
    return entry


def dequeue_next(state_dir: Optional[str] = None) -> Optional[dict]:
    """Return the oldest pending entry and mark it in_progress.

    If no pending entries exist, returns None. The queue file is updated
    atomically before returning.

    Args:
        state_dir: Optional override for the state directory.

    Returns:
        The in_progress entry dict, or None if the queue is empty.
    """
    data = _read_queue(state_dir)

    for entry in data["entries"]:
        if entry["status"] == "pending":
            entry["status"] = "in_progress"
            entry["started_at"] = datetime.now(timezone.utc).isoformat()
            _write_queue(data, state_dir)
            return entry

    return None


def _update_entry(
    entry_id: str,
    status: str,
    error: Optional[str] = None,
    state_dir: Optional[str] = None,
) -> None:
    """Update an entry's status and optional error message in the queue file.

    Args:
        entry_id: The entry_id to update.
        status: New status value (``completed`` or ``failed``).
        error: Optional error string for failed entries.
        state_dir: Optional override for the state directory.
    """
    data = _read_queue(state_dir)
    for entry in data["entries"]:
        if entry["entry_id"] == entry_id:
            entry["status"] = status
            entry["completed_at"] = datetime.now(timezone.utc).isoformat()
            entry["error"] = error
            break
    _write_queue(data, state_dir)


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------


def rebase_and_test(entry: dict) -> dict:
    """Rebase the node branch onto main and run the attractor test suite.

    Operations performed (in order):
    1. ``git rebase main`` in the repo_root
    2. On rebase failure: ``git rebase --abort`` and return failure
    3. ``pytest .claude/scripts/attractor/tests/ -x -q``
    4. On test failure: return failure with output

    Args:
        entry: Queue entry dict (must have ``branch`` and ``repo_root`` keys).

    Returns:
        Dict with keys:
          - ``success`` (bool): True if both rebase and tests passed.
          - ``error`` (str | None): Error message on failure, None on success.
    """
    repo_root = entry["repo_root"]
    branch = entry["branch"]

    # Step 1: Ensure we're on the right branch
    checkout_result = subprocess.run(
        ["git", "checkout", branch],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout_result.returncode != 0:
        return {
            "success": False,
            "error": (
                f"git checkout {branch} failed: "
                f"{checkout_result.stderr.strip()}"
            ),
        }

    # Step 2: Rebase onto main
    rebase_result = subprocess.run(
        ["git", "rebase", "main"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if rebase_result.returncode != 0:
        # Abort the rebase to restore clean state
        subprocess.run(
            ["git", "rebase", "--abort"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "success": False,
            "error": (
                f"git rebase main failed: "
                f"{rebase_result.stderr.strip() or rebase_result.stdout.strip()}"
            ),
        }

    # Step 3: Run tests
    test_dir = os.path.join(repo_root, ".claude", "scripts", "attractor", "tests")
    pytest_result = subprocess.run(
        ["python", "-m", "pytest", test_dir, "-x", "-q"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if pytest_result.returncode != 0:
        output = (pytest_result.stdout + pytest_result.stderr).strip()
        return {
            "success": False,
            "error": f"pytest failed:\n{output}",
        }

    return {"success": True, "error": None}


def merge_branch(entry: dict) -> dict:
    """Merge the node branch into main using --no-ff.

    Assumes the branch has already been rebased onto main via
    ``rebase_and_test``.

    Operations performed (in order):
    1. ``git checkout main``
    2. ``git merge --no-ff {branch} -m "Merge {branch}: {node_id}"``

    Args:
        entry: Queue entry dict (must have ``branch``, ``node_id``, and
            ``repo_root`` keys).

    Returns:
        Dict with keys:
          - ``success`` (bool): True if merge succeeded.
          - ``error`` (str | None): Error message on failure, None on success.
    """
    repo_root = entry["repo_root"]
    branch = entry["branch"]
    node_id = entry["node_id"]

    # Step 1: Switch to main
    checkout_result = subprocess.run(
        ["git", "checkout", "main"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout_result.returncode != 0:
        return {
            "success": False,
            "error": (
                f"git checkout main failed: "
                f"{checkout_result.stderr.strip()}"
            ),
        }

    # Step 2: Merge the node branch
    commit_msg = f"Merge {branch}: {node_id}"
    merge_result = subprocess.run(
        ["git", "merge", "--no-ff", branch, "-m", commit_msg],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if merge_result.returncode != 0:
        return {
            "success": False,
            "error": (
                f"git merge --no-ff {branch} failed: "
                f"{merge_result.stderr.strip() or merge_result.stdout.strip()}"
            ),
        }

    return {"success": True, "error": None}


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def process_next(state_dir: Optional[str] = None) -> dict:
    """Process the next pending entry in the merge queue.

    Full pipeline:
    1. dequeue_next() — claim oldest pending entry
    2. rebase_and_test(entry) — rebase onto main and run tests
    3. merge_branch(entry) — merge into main
    4. Mark entry completed or failed in the queue file

    Args:
        state_dir: Optional override for the state directory.

    Returns:
        Dict with keys:
          - ``success`` (bool): True if the full pipeline succeeded.
          - ``entry`` (dict | None): The processed entry, or None if queue empty.
          - ``error`` (str | None): Error message on failure, None on success.
    """
    entry = dequeue_next(state_dir)
    if entry is None:
        return {"success": True, "entry": None, "error": None}

    # Step 1: Rebase and test
    rebase_result = rebase_and_test(entry)
    if not rebase_result["success"]:
        _update_entry(
            entry["entry_id"],
            status="failed",
            error=rebase_result["error"],
            state_dir=state_dir,
        )
        return {
            "success": False,
            "entry": entry,
            "error": rebase_result["error"],
        }

    # Step 2: Merge into main
    merge_result = merge_branch(entry)
    if not merge_result["success"]:
        _update_entry(
            entry["entry_id"],
            status="failed",
            error=merge_result["error"],
            state_dir=state_dir,
        )
        return {
            "success": False,
            "entry": entry,
            "error": merge_result["error"],
        }

    # Success
    _update_entry(entry["entry_id"], status="completed", state_dir=state_dir)
    return {"success": True, "entry": entry, "error": None}
