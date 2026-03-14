"""Tests for merge_queue.py — Sequential Merge Queue.

Tests use a temporary directory for state isolation. Git operations in
rebase_and_test and merge_branch are mocked via unittest.mock.patch so
the test suite does not require a real git repository.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Locate the attractor package so we can import without installing it.
# ---------------------------------------------------------------------------
import sys

from cobuilder.engine.merge_queue import (  # noqa: E402
    _empty_queue,
    _find_git_root,
    _queue_path,
    _read_queue,
    _write_queue,
    dequeue_next,
    enqueue,
    merge_branch,
    process_next,
    rebase_and_test,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state_dir(tmp_path):
    """Return a temporary directory to use as the state_dir override."""
    d = tmp_path / "state"
    d.mkdir()
    return str(d)


def _make_entry(node_id="impl_auth", branch="worktree-impl_auth", repo_root="/repo"):
    return {"node_id": node_id, "branch": branch, "repo_root": repo_root}


# ---------------------------------------------------------------------------
# _find_git_root
# ---------------------------------------------------------------------------


def test_find_git_root_finds_parent(tmp_path):
    """_find_git_root should walk up to find a .git directory."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert _find_git_root(str(nested)) == str(tmp_path)


def test_find_git_root_returns_none_when_missing(tmp_path):
    """_find_git_root should return None if there's no .git anywhere."""
    # Use /tmp as a start — no .git there (in practice)
    assert _find_git_root("/nonexistent_path_xyz_abc") is None


# ---------------------------------------------------------------------------
# _queue_path
# ---------------------------------------------------------------------------


def test_queue_path_with_state_dir(state_dir):
    path = _queue_path(state_dir=state_dir)
    assert path == os.path.join(state_dir, "merge-queue.json")


def test_queue_path_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("PIPELINE_MERGE_QUEUE_DIR", str(tmp_path))
    path = _queue_path()
    assert path == os.path.join(str(tmp_path), "merge-queue.json")
    monkeypatch.delenv("PIPELINE_MERGE_QUEUE_DIR")


# ---------------------------------------------------------------------------
# _read_queue / _write_queue
# ---------------------------------------------------------------------------


def test_read_queue_returns_empty_when_missing(state_dir):
    data = _read_queue(state_dir=state_dir)
    assert data["entries"] == []
    assert "last_updated" in data


def test_write_and_read_queue_roundtrip(state_dir):
    data = _empty_queue()
    data["entries"].append({"entry_id": "mq-test-1", "node_id": "test"})
    _write_queue(data, state_dir=state_dir)

    loaded = _read_queue(state_dir=state_dir)
    assert len(loaded["entries"]) == 1
    assert loaded["entries"][0]["node_id"] == "test"


def test_write_queue_creates_parent_dirs(tmp_path):
    deep_dir = str(tmp_path / "a" / "b" / "c")
    data = _empty_queue()
    _write_queue(data, state_dir=deep_dir)
    assert os.path.isfile(os.path.join(deep_dir, "merge-queue.json"))


def test_read_queue_returns_empty_on_corrupt_json(state_dir):
    path = os.path.join(state_dir, "merge-queue.json")
    with open(path, "w") as f:
        f.write("NOT VALID JSON {{{")
    data = _read_queue(state_dir=state_dir)
    assert data["entries"] == []


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------


def test_enqueue_adds_entry(state_dir):
    entry = enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    assert entry["node_id"] == "impl_auth"
    assert entry["branch"] == "worktree-impl_auth"
    assert entry["status"] == "pending"
    assert entry["started_at"] is None
    assert entry["completed_at"] is None
    assert entry["error"] is None
    assert entry["entry_id"].startswith("mq-impl_auth-")


def test_enqueue_persists_to_file(state_dir):
    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    data = _read_queue(state_dir=state_dir)
    assert len(data["entries"]) == 1
    assert data["entries"][0]["node_id"] == "impl_auth"


def test_enqueue_multiple_entries(state_dir):
    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    enqueue("impl_api", branch="worktree-impl_api", repo_root="/repo", state_dir=state_dir)
    data = _read_queue(state_dir=state_dir)
    assert len(data["entries"]) == 2


def test_enqueue_idempotent_same_node_id(state_dir):
    """Calling enqueue twice with the same node_id should not duplicate."""
    e1 = enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    e2 = enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    assert e1["entry_id"] == e2["entry_id"]
    data = _read_queue(state_dir=state_dir)
    assert len(data["entries"]) == 1


# ---------------------------------------------------------------------------
# dequeue_next
# ---------------------------------------------------------------------------


def test_dequeue_next_returns_none_when_empty(state_dir):
    result = dequeue_next(state_dir=state_dir)
    assert result is None


def test_dequeue_next_returns_oldest_pending(state_dir):
    """FIFO order: first-enqueued entry should be dequeued first."""
    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    time.sleep(0.01)  # Ensure different timestamps
    enqueue("impl_api", branch="worktree-impl_api", repo_root="/repo", state_dir=state_dir)

    entry = dequeue_next(state_dir=state_dir)
    assert entry["node_id"] == "impl_auth"


def test_dequeue_next_marks_entry_in_progress(state_dir):
    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    entry = dequeue_next(state_dir=state_dir)
    assert entry["status"] == "in_progress"
    assert entry["started_at"] is not None


def test_dequeue_next_persists_status_change(state_dir):
    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    dequeue_next(state_dir=state_dir)
    data = _read_queue(state_dir=state_dir)
    assert data["entries"][0]["status"] == "in_progress"


def test_dequeue_next_skips_in_progress_entries(state_dir):
    """dequeue_next should skip non-pending entries and return next pending."""
    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    enqueue("impl_api", branch="worktree-impl_api", repo_root="/repo", state_dir=state_dir)

    # Claim the first entry
    first = dequeue_next(state_dir=state_dir)
    assert first["node_id"] == "impl_auth"

    # Next call should return the second entry
    second = dequeue_next(state_dir=state_dir)
    assert second["node_id"] == "impl_api"

    # No more pending entries
    third = dequeue_next(state_dir=state_dir)
    assert third is None


# ---------------------------------------------------------------------------
# rebase_and_test (with mocked subprocess)
# ---------------------------------------------------------------------------


def _make_proc(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_rebase_and_test_success(mock_run):
    """All subprocess calls succeed → success=True."""
    mock_run.return_value = _make_proc(returncode=0)
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    result = rebase_and_test(entry)
    assert result["success"] is True
    assert result["error"] is None


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_rebase_and_test_checkout_failure(mock_run):
    """Checkout failure → success=False, abort not called."""
    mock_run.return_value = _make_proc(returncode=1, stderr="branch not found")
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    result = rebase_and_test(entry)
    assert result["success"] is False
    assert "checkout" in result["error"]


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_rebase_and_test_rebase_failure_calls_abort(mock_run):
    """Rebase failure → abort is called, returns success=False."""
    # checkout succeeds, rebase fails, abort succeeds
    mock_run.side_effect = [
        _make_proc(returncode=0),                     # git checkout
        _make_proc(returncode=1, stderr="conflict"),  # git rebase main
        _make_proc(returncode=0),                     # git rebase --abort
    ]
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    result = rebase_and_test(entry)
    assert result["success"] is False
    assert "rebase" in result["error"]
    # Verify abort was called
    abort_call = mock_run.call_args_list[2]
    assert "--abort" in abort_call[0][0]


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_rebase_and_test_pytest_failure(mock_run):
    """Pytest failure → success=False with pytest output in error."""
    mock_run.side_effect = [
        _make_proc(returncode=0),                      # git checkout
        _make_proc(returncode=0),                      # git rebase main
        _make_proc(returncode=1, stdout="FAILED test_foo.py"),  # pytest
    ]
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    result = rebase_and_test(entry)
    assert result["success"] is False
    assert "pytest" in result["error"]


# ---------------------------------------------------------------------------
# merge_branch (with mocked subprocess)
# ---------------------------------------------------------------------------


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_merge_branch_success(mock_run):
    mock_run.return_value = _make_proc(returncode=0)
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    result = merge_branch(entry)
    assert result["success"] is True
    assert result["error"] is None


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_merge_branch_checkout_main_failure(mock_run):
    mock_run.return_value = _make_proc(returncode=1, stderr="no main branch")
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    result = merge_branch(entry)
    assert result["success"] is False
    assert "checkout main" in result["error"]


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_merge_branch_merge_failure(mock_run):
    mock_run.side_effect = [
        _make_proc(returncode=0),                         # git checkout main
        _make_proc(returncode=1, stderr="merge conflict"),  # git merge
    ]
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    result = merge_branch(entry)
    assert result["success"] is False
    assert "merge" in result["error"]


@patch("cobuilder.engine.merge_queue.subprocess.run")
def test_merge_branch_uses_no_ff(mock_run):
    """Verify --no-ff flag is passed to git merge."""
    mock_run.return_value = _make_proc(returncode=0)
    entry = {
        "node_id": "impl_auth",
        "branch": "worktree-impl_auth",
        "repo_root": "/repo",
    }
    merge_branch(entry)
    merge_call = mock_run.call_args_list[1]
    assert "--no-ff" in merge_call[0][0]


# ---------------------------------------------------------------------------
# process_next (full pipeline)
# ---------------------------------------------------------------------------


def test_process_next_returns_none_entry_when_queue_empty(state_dir):
    result = process_next(state_dir=state_dir)
    assert result["success"] is True
    assert result["entry"] is None
    assert result["error"] is None


@patch("cobuilder.engine.merge_queue.rebase_and_test")
@patch("cobuilder.engine.merge_queue.merge_branch")
def test_process_next_success_path(mock_merge, mock_rebase, state_dir):
    mock_rebase.return_value = {"success": True, "error": None}
    mock_merge.return_value = {"success": True, "error": None}

    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    result = process_next(state_dir=state_dir)

    assert result["success"] is True
    assert result["entry"]["node_id"] == "impl_auth"
    assert result["error"] is None

    # Entry should be marked completed in queue
    data = _read_queue(state_dir=state_dir)
    assert data["entries"][0]["status"] == "completed"


@patch("cobuilder.engine.merge_queue.rebase_and_test")
@patch("cobuilder.engine.merge_queue.merge_branch")
def test_process_next_rebase_failure_marks_failed(mock_merge, mock_rebase, state_dir):
    mock_rebase.return_value = {"success": False, "error": "rebase conflict"}
    mock_merge.return_value = {"success": True, "error": None}

    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    result = process_next(state_dir=state_dir)

    assert result["success"] is False
    assert "rebase" in result["error"]

    # merge_branch should NOT have been called
    mock_merge.assert_not_called()

    # Entry should be marked failed
    data = _read_queue(state_dir=state_dir)
    assert data["entries"][0]["status"] == "failed"
    assert data["entries"][0]["error"] == "rebase conflict"


@patch("cobuilder.engine.merge_queue.rebase_and_test")
@patch("cobuilder.engine.merge_queue.merge_branch")
def test_process_next_merge_failure_marks_failed(mock_merge, mock_rebase, state_dir):
    mock_rebase.return_value = {"success": True, "error": None}
    mock_merge.return_value = {"success": False, "error": "merge conflict"}

    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    result = process_next(state_dir=state_dir)

    assert result["success"] is False
    assert "merge" in result["error"]

    data = _read_queue(state_dir=state_dir)
    assert data["entries"][0]["status"] == "failed"


@patch("cobuilder.engine.merge_queue.rebase_and_test")
@patch("cobuilder.engine.merge_queue.merge_branch")
def test_process_next_processes_fifo(mock_merge, mock_rebase, state_dir):
    """process_next should process entries in FIFO order."""
    mock_rebase.return_value = {"success": True, "error": None}
    mock_merge.return_value = {"success": True, "error": None}

    enqueue("impl_auth", branch="worktree-impl_auth", repo_root="/repo", state_dir=state_dir)
    time.sleep(0.01)
    enqueue("impl_api", branch="worktree-impl_api", repo_root="/repo", state_dir=state_dir)

    result1 = process_next(state_dir=state_dir)
    assert result1["entry"]["node_id"] == "impl_auth"

    result2 = process_next(state_dir=state_dir)
    assert result2["entry"]["node_id"] == "impl_api"
