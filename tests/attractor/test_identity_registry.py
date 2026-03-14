"""Unit tests for identity_registry.py.

Tests:
    TestCreateIdentity   - create_identity() writes correct file with correct schema
    TestReadIdentity     - read_identity() returns None if missing, parses if present
    TestUpdateLiveness   - update_liveness() updates last_heartbeat, raises if missing
    TestMarkCrashed      - mark_crashed() sets status and crashed_at
    TestMarkTerminated   - mark_terminated() sets status and terminated_at
    TestListAll          - list_all() returns all records, handles missing dir
    TestFindStale        - find_stale() returns only active agents past timeout
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

# Ensure attractor package is importable

from cobuilder.engine.identity_registry import (  # noqa: E402
    create_identity,
    find_stale,
    list_all,
    mark_crashed,
    mark_terminated,
    read_identity,
    update_liveness,
)


# ---------------------------------------------------------------------------
# TestCreateIdentity
# ---------------------------------------------------------------------------

class TestCreateIdentity:
    """Tests for create_identity()."""

    def test_creates_file(self, tmp_path):
        """create_identity() creates a JSON file in the state directory."""
        state_dir = str(tmp_path / "identities")
        result = create_identity(
            role="orchestrator",
            name="impl_auth",
            session_id="orch-impl_auth",
            worktree=".claude/worktrees/impl_auth",
            state_dir=state_dir,
        )
        expected_path = os.path.join(state_dir, "orchestrator-impl_auth.json")
        assert os.path.exists(expected_path)

    def test_returns_correct_schema(self, tmp_path):
        """create_identity() returns dict with all required fields."""
        state_dir = str(tmp_path / "identities")
        result = create_identity(
            role="runner",
            name="impl_auth",
            session_id="runner-impl_auth",
            worktree="",
            state_dir=state_dir,
        )
        assert result["role"] == "runner"
        assert result["name"] == "impl_auth"
        assert result["session_id"] == "runner-impl_auth"
        assert result["worktree"] == ""
        assert result["status"] == "active"
        assert "agent_id" in result
        assert "created_at" in result
        assert "last_heartbeat" in result
        assert result["crashed_at"] is None
        assert result["terminated_at"] is None
        assert result["predecessor_id"] is None
        assert result["metadata"] == {}

    def test_agent_id_contains_role_and_name(self, tmp_path):
        """agent_id starts with role-name-."""
        state_dir = str(tmp_path / "identities")
        result = create_identity("orchestrator", "auth", "orch-auth", "", state_dir=state_dir)
        assert result["agent_id"].startswith("orchestrator-auth-")

    def test_predecessor_id_stored(self, tmp_path):
        """predecessor_id is stored when provided."""
        state_dir = str(tmp_path / "identities")
        result = create_identity(
            "orchestrator", "auth", "orch-auth", "",
            predecessor_id="orchestrator-auth-20260101T000000Z",
            state_dir=state_dir,
        )
        assert result["predecessor_id"] == "orchestrator-auth-20260101T000000Z"

    def test_metadata_stored(self, tmp_path):
        """metadata dict is stored when provided."""
        state_dir = str(tmp_path / "identities")
        result = create_identity(
            "runner", "n1", "runner-n1", "",
            metadata={"prd": "PRD-001"},
            state_dir=state_dir,
        )
        assert result["metadata"]["prd"] == "PRD-001"

    def test_overwrites_existing(self, tmp_path):
        """create_identity() overwrites any existing identity for the same role+name."""
        state_dir = str(tmp_path / "identities")
        first = create_identity("orchestrator", "auth", "orch-auth", "", state_dir=state_dir)
        time.sleep(1.05)  # agent_id timestamp has 1s granularity
        second = create_identity("orchestrator", "auth", "orch-auth", "", state_dir=state_dir)
        assert first["agent_id"] != second["agent_id"]
        # File on disk should reflect the second
        on_disk = read_identity("orchestrator", "auth", state_dir=state_dir)
        assert on_disk["agent_id"] == second["agent_id"]

    def test_creates_dir_if_missing(self, tmp_path):
        """create_identity() creates the state directory if it does not exist."""
        state_dir = str(tmp_path / "nested" / "identities")
        assert not os.path.exists(state_dir)
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        assert os.path.isdir(state_dir)

    def test_no_tmp_file_left_behind(self, tmp_path):
        """No .tmp file is left behind after create_identity()."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        for f in os.listdir(state_dir):
            assert not f.endswith(".tmp"), f"Found leftover .tmp file: {f}"

    def test_file_content_matches_return_value(self, tmp_path):
        """The written file content matches the returned dict."""
        state_dir = str(tmp_path / "identities")
        result = create_identity("runner", "n1", "runner-n1", "/wt", state_dir=state_dir)
        path = os.path.join(state_dir, "runner-n1.json")
        with open(path, encoding="utf-8") as fh:
            on_disk = json.load(fh)
        assert on_disk == result


# ---------------------------------------------------------------------------
# TestReadIdentity
# ---------------------------------------------------------------------------

class TestReadIdentity:
    """Tests for read_identity()."""

    def test_returns_none_if_missing(self, tmp_path):
        """read_identity() returns None when no file exists."""
        state_dir = str(tmp_path / "identities")
        result = read_identity("orchestrator", "nonexistent", state_dir=state_dir)
        assert result is None

    def test_returns_dict_when_present(self, tmp_path):
        """read_identity() returns the identity dict when the file exists."""
        state_dir = str(tmp_path / "identities")
        created = create_identity("orchestrator", "auth", "orch-auth", "/wt", state_dir=state_dir)
        read_back = read_identity("orchestrator", "auth", state_dir=state_dir)
        assert read_back == created

    def test_correct_fields_returned(self, tmp_path):
        """read_identity() returns all identity fields correctly."""
        state_dir = str(tmp_path / "identities")
        create_identity("guardian", "main", "guardian-main", "", state_dir=state_dir)
        result = read_identity("guardian", "main", state_dir=state_dir)
        assert result["role"] == "guardian"
        assert result["name"] == "main"
        assert result["status"] == "active"


# ---------------------------------------------------------------------------
# TestUpdateLiveness
# ---------------------------------------------------------------------------

class TestUpdateLiveness:
    """Tests for update_liveness()."""

    def test_updates_last_heartbeat(self, tmp_path):
        """update_liveness() changes last_heartbeat timestamp."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        original = read_identity("runner", "n1", state_dir=state_dir)
        time.sleep(1.05)  # ensure timestamp changes (1s resolution)
        update_liveness("runner", "n1", state_dir=state_dir)
        updated = read_identity("runner", "n1", state_dir=state_dir)
        assert updated["last_heartbeat"] != original["last_heartbeat"]

    def test_does_not_change_status(self, tmp_path):
        """update_liveness() preserves the status field."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        update_liveness("runner", "n1", state_dir=state_dir)
        result = read_identity("runner", "n1", state_dir=state_dir)
        assert result["status"] == "active"

    def test_raises_if_missing(self, tmp_path):
        """update_liveness() raises FileNotFoundError if no identity exists."""
        state_dir = str(tmp_path / "identities")
        with pytest.raises(FileNotFoundError):
            update_liveness("runner", "nonexistent", state_dir=state_dir)

    def test_returns_updated_dict(self, tmp_path):
        """update_liveness() returns the updated identity dict."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        result = update_liveness("runner", "n1", state_dir=state_dir)
        assert result["role"] == "runner"
        assert "last_heartbeat" in result


# ---------------------------------------------------------------------------
# TestMarkCrashed
# ---------------------------------------------------------------------------

class TestMarkCrashed:
    """Tests for mark_crashed()."""

    def test_sets_status_to_crashed(self, tmp_path):
        """mark_crashed() sets status to 'crashed'."""
        state_dir = str(tmp_path / "identities")
        create_identity("orchestrator", "auth", "orch-auth", "", state_dir=state_dir)
        mark_crashed("orchestrator", "auth", state_dir=state_dir)
        result = read_identity("orchestrator", "auth", state_dir=state_dir)
        assert result["status"] == "crashed"

    def test_sets_crashed_at(self, tmp_path):
        """mark_crashed() populates crashed_at with a timestamp."""
        state_dir = str(tmp_path / "identities")
        create_identity("orchestrator", "auth", "orch-auth", "", state_dir=state_dir)
        mark_crashed("orchestrator", "auth", state_dir=state_dir)
        result = read_identity("orchestrator", "auth", state_dir=state_dir)
        assert result["crashed_at"] is not None

    def test_raises_if_missing(self, tmp_path):
        """mark_crashed() raises FileNotFoundError if no identity exists."""
        state_dir = str(tmp_path / "identities")
        with pytest.raises(FileNotFoundError):
            mark_crashed("orchestrator", "nonexistent", state_dir=state_dir)

    def test_returns_updated_dict(self, tmp_path):
        """mark_crashed() returns the updated identity dict."""
        state_dir = str(tmp_path / "identities")
        create_identity("orchestrator", "auth", "orch-auth", "", state_dir=state_dir)
        result = mark_crashed("orchestrator", "auth", state_dir=state_dir)
        assert result["status"] == "crashed"


# ---------------------------------------------------------------------------
# TestMarkTerminated
# ---------------------------------------------------------------------------

class TestMarkTerminated:
    """Tests for mark_terminated()."""

    def test_sets_status_to_terminated(self, tmp_path):
        """mark_terminated() sets status to 'terminated'."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        mark_terminated("runner", "n1", state_dir=state_dir)
        result = read_identity("runner", "n1", state_dir=state_dir)
        assert result["status"] == "terminated"

    def test_sets_terminated_at(self, tmp_path):
        """mark_terminated() populates terminated_at with a timestamp."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        mark_terminated("runner", "n1", state_dir=state_dir)
        result = read_identity("runner", "n1", state_dir=state_dir)
        assert result["terminated_at"] is not None

    def test_raises_if_missing(self, tmp_path):
        """mark_terminated() raises FileNotFoundError if no identity exists."""
        state_dir = str(tmp_path / "identities")
        with pytest.raises(FileNotFoundError):
            mark_terminated("runner", "nonexistent", state_dir=state_dir)

    def test_returns_updated_dict(self, tmp_path):
        """mark_terminated() returns the updated identity dict."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        result = mark_terminated("runner", "n1", state_dir=state_dir)
        assert result["status"] == "terminated"


# ---------------------------------------------------------------------------
# TestListAll
# ---------------------------------------------------------------------------

class TestListAll:
    """Tests for list_all()."""

    def test_returns_empty_for_missing_dir(self, tmp_path):
        """list_all() returns [] when state directory does not exist."""
        state_dir = str(tmp_path / "nonexistent")
        result = list_all(state_dir=state_dir)
        assert result == []

    def test_returns_all_identities(self, tmp_path):
        """list_all() returns all identity records."""
        state_dir = str(tmp_path / "identities")
        create_identity("orchestrator", "auth", "orch-auth", "", state_dir=state_dir)
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        result = list_all(state_dir=state_dir)
        assert len(result) == 2

    def test_skips_tmp_files(self, tmp_path):
        """list_all() does not include .tmp files."""
        state_dir = str(tmp_path / "identities")
        os.makedirs(state_dir)
        tmp_file = os.path.join(state_dir, "runner-n1.json.tmp")
        with open(tmp_file, "w") as fh:
            fh.write("{}")
        result = list_all(state_dir=state_dir)
        assert result == []

    def test_returns_list_of_dicts(self, tmp_path):
        """list_all() returns a list of dicts, not file paths."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        result = list_all(state_dir=state_dir)
        assert isinstance(result[0], dict)
        assert "agent_id" in result[0]


# ---------------------------------------------------------------------------
# TestFindStale
# ---------------------------------------------------------------------------

class TestFindStale:
    """Tests for find_stale()."""

    def test_returns_empty_when_no_agents(self, tmp_path):
        """find_stale() returns [] when no identity files exist."""
        state_dir = str(tmp_path / "identities")
        result = find_stale(timeout_seconds=300, state_dir=state_dir)
        assert result == []

    def test_returns_empty_when_heartbeat_recent(self, tmp_path):
        """find_stale() returns [] when agents have recent heartbeats."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        result = find_stale(timeout_seconds=300, state_dir=state_dir)
        assert result == []

    def test_finds_stale_active_agents(self, tmp_path):
        """find_stale() returns active agents past the timeout threshold."""
        state_dir = str(tmp_path / "identities")
        # Create and immediately mark as stale by using a past timestamp
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        # Manually backdate the heartbeat
        path = os.path.join(state_dir, "runner-n1.json")
        with open(path) as fh:
            data = json.load(fh)
        data["last_heartbeat"] = "2020-01-01T00:00:00Z"  # very old
        with open(path, "w") as fh:
            json.dump(data, fh)

        result = find_stale(timeout_seconds=300, state_dir=state_dir)
        assert len(result) == 1
        assert result[0]["name"] == "n1"

    def test_ignores_crashed_agents(self, tmp_path):
        """find_stale() ignores agents with status 'crashed'."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        mark_crashed("runner", "n1", state_dir=state_dir)
        # Backdate heartbeat for good measure
        path = os.path.join(state_dir, "runner-n1.json")
        with open(path) as fh:
            data = json.load(fh)
        data["last_heartbeat"] = "2020-01-01T00:00:00Z"
        with open(path, "w") as fh:
            json.dump(data, fh)

        result = find_stale(timeout_seconds=300, state_dir=state_dir)
        assert result == []

    def test_ignores_terminated_agents(self, tmp_path):
        """find_stale() ignores agents with status 'terminated'."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        mark_terminated("runner", "n1", state_dir=state_dir)
        path = os.path.join(state_dir, "runner-n1.json")
        with open(path) as fh:
            data = json.load(fh)
        data["last_heartbeat"] = "2020-01-01T00:00:00Z"
        with open(path, "w") as fh:
            json.dump(data, fh)

        result = find_stale(timeout_seconds=300, state_dir=state_dir)
        assert result == []

    def test_only_returns_active_stale(self, tmp_path):
        """find_stale() returns only active agents past threshold."""
        state_dir = str(tmp_path / "identities")
        # Active, recent (not stale)
        create_identity("runner", "n1", "runner-n1", "", state_dir=state_dir)
        # Active, stale
        create_identity("runner", "n2", "runner-n2", "", state_dir=state_dir)
        path = os.path.join(state_dir, "runner-n2.json")
        with open(path) as fh:
            data = json.load(fh)
        data["last_heartbeat"] = "2020-01-01T00:00:00Z"
        with open(path, "w") as fh:
            json.dump(data, fh)

        result = find_stale(timeout_seconds=300, state_dir=state_dir)
        assert len(result) == 1
        assert result[0]["name"] == "n2"
