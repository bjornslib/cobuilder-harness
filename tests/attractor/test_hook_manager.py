"""Unit tests for hook_manager.py.

Tests:
    TestCreateHook               - create_hook() writes correct file with correct schema
    TestReadHook                 - read_hook() returns None if missing, parses if present
    TestUpdatePhase              - update_phase() transitions correctly, validates phase
    TestUpdateResumptionInstructions - update_resumption_instructions() stores instructions
    TestMarkMerged               - mark_merged() sets phase and merged_at timestamp
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

# Ensure attractor package is importable

from cobuilder.attractor.hook_manager import (  # noqa: E402
    VALID_PHASES,
    create_hook,
    mark_merged,
    read_hook,
    update_phase,
    update_resumption_instructions,
)


# ---------------------------------------------------------------------------
# TestCreateHook
# ---------------------------------------------------------------------------

class TestCreateHook:
    """Tests for create_hook()."""

    def test_creates_file(self, tmp_path):
        """create_hook() creates a JSON file in the state directory."""
        state_dir = str(tmp_path / "hooks")
        create_hook(role="orchestrator", name="impl_auth", state_dir=state_dir)
        expected_path = os.path.join(state_dir, "orchestrator-impl_auth.json")
        assert os.path.exists(expected_path)

    def test_returns_correct_schema(self, tmp_path):
        """create_hook() returns dict with all required fields."""
        state_dir = str(tmp_path / "hooks")
        result = create_hook(role="orchestrator", name="impl_auth", state_dir=state_dir)
        assert result["role"] == "orchestrator"
        assert result["name"] == "impl_auth"
        assert result["phase"] == "planning"
        assert result["last_committed_node"] is None
        assert result["resumption_instructions"] == ""
        assert result["predecessor_hook_id"] is None
        assert "hook_id" in result
        assert "created_at" in result
        assert "updated_at" in result
        assert result["merged_at"] is None

    def test_hook_id_contains_role_and_name(self, tmp_path):
        """hook_id starts with role-name-."""
        state_dir = str(tmp_path / "hooks")
        result = create_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["hook_id"].startswith("orchestrator-auth-")

    def test_default_phase_is_planning(self, tmp_path):
        """Default phase is 'planning'."""
        state_dir = str(tmp_path / "hooks")
        result = create_hook("runner", "n1", state_dir=state_dir)
        assert result["phase"] == "planning"

    def test_custom_phase_stored(self, tmp_path):
        """Custom phase is stored when provided."""
        state_dir = str(tmp_path / "hooks")
        result = create_hook("orchestrator", "auth", phase="executing", state_dir=state_dir)
        assert result["phase"] == "executing"

    def test_invalid_phase_raises(self, tmp_path):
        """create_hook() raises ValueError for invalid phase."""
        state_dir = str(tmp_path / "hooks")
        with pytest.raises(ValueError, match="Invalid phase"):
            create_hook("orchestrator", "auth", phase="invalid_phase", state_dir=state_dir)

    def test_predecessor_hook_id_stored(self, tmp_path):
        """predecessor_hook_id is stored when provided."""
        state_dir = str(tmp_path / "hooks")
        result = create_hook(
            "orchestrator", "auth",
            predecessor_hook_id="orchestrator-auth-20260101T000000Z",
            state_dir=state_dir,
        )
        assert result["predecessor_hook_id"] == "orchestrator-auth-20260101T000000Z"

    def test_overwrites_existing(self, tmp_path):
        """create_hook() overwrites any existing hook for the same role+name."""
        state_dir = str(tmp_path / "hooks")
        first = create_hook("orchestrator", "auth", state_dir=state_dir)
        time.sleep(1.05)  # hook_id timestamp has 1s granularity
        second = create_hook("orchestrator", "auth", state_dir=state_dir)
        assert first["hook_id"] != second["hook_id"]
        # File on disk should reflect the second
        on_disk = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert on_disk["hook_id"] == second["hook_id"]

    def test_creates_dir_if_missing(self, tmp_path):
        """create_hook() creates the state directory if it does not exist."""
        state_dir = str(tmp_path / "nested" / "hooks")
        assert not os.path.exists(state_dir)
        create_hook("runner", "n1", state_dir=state_dir)
        assert os.path.isdir(state_dir)

    def test_no_tmp_file_left_behind(self, tmp_path):
        """No .tmp file is left behind after create_hook()."""
        state_dir = str(tmp_path / "hooks")
        create_hook("runner", "n1", state_dir=state_dir)
        for f in os.listdir(state_dir):
            assert not f.endswith(".tmp"), f"Found leftover .tmp file: {f}"

    def test_file_content_matches_return_value(self, tmp_path):
        """The written file content matches the returned dict."""
        state_dir = str(tmp_path / "hooks")
        result = create_hook("runner", "n1", state_dir=state_dir)
        path = os.path.join(state_dir, "runner-n1.json")
        with open(path, encoding="utf-8") as fh:
            on_disk = json.load(fh)
        assert on_disk == result

    def test_all_valid_phases_accepted(self, tmp_path):
        """create_hook() accepts all valid phase values."""
        state_dir = str(tmp_path / "hooks")
        for i, phase in enumerate(sorted(VALID_PHASES)):
            result = create_hook(f"runner", f"n{i}", phase=phase, state_dir=state_dir)
            assert result["phase"] == phase


# ---------------------------------------------------------------------------
# TestReadHook
# ---------------------------------------------------------------------------

class TestReadHook:
    """Tests for read_hook()."""

    def test_returns_none_if_missing(self, tmp_path):
        """read_hook() returns None when no file exists."""
        state_dir = str(tmp_path / "hooks")
        result = read_hook("orchestrator", "nonexistent", state_dir=state_dir)
        assert result is None

    def test_returns_dict_when_present(self, tmp_path):
        """read_hook() returns the hook dict when the file exists."""
        state_dir = str(tmp_path / "hooks")
        created = create_hook("orchestrator", "auth", state_dir=state_dir)
        read_back = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert read_back == created

    def test_correct_fields_returned(self, tmp_path):
        """read_hook() returns all hook fields correctly."""
        state_dir = str(tmp_path / "hooks")
        create_hook("runner", "n1", state_dir=state_dir)
        result = read_hook("runner", "n1", state_dir=state_dir)
        assert result["role"] == "runner"
        assert result["name"] == "n1"
        assert result["phase"] == "planning"


# ---------------------------------------------------------------------------
# TestUpdatePhase
# ---------------------------------------------------------------------------

class TestUpdatePhase:
    """Tests for update_phase()."""

    def test_updates_phase(self, tmp_path):
        """update_phase() changes the phase field."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        update_phase("orchestrator", "auth", "executing", state_dir=state_dir)
        result = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["phase"] == "executing"

    def test_updates_updated_at(self, tmp_path):
        """update_phase() bumps updated_at timestamp."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        original = read_hook("orchestrator", "auth", state_dir=state_dir)
        time.sleep(1.05)
        update_phase("orchestrator", "auth", "executing", state_dir=state_dir)
        updated = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert updated["updated_at"] != original["updated_at"]

    def test_raises_for_invalid_phase(self, tmp_path):
        """update_phase() raises ValueError for invalid phase."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        with pytest.raises(ValueError, match="Invalid phase"):
            update_phase("orchestrator", "auth", "not_a_phase", state_dir=state_dir)

    def test_raises_if_missing(self, tmp_path):
        """update_phase() raises FileNotFoundError if no hook exists."""
        state_dir = str(tmp_path / "hooks")
        with pytest.raises(FileNotFoundError):
            update_phase("orchestrator", "nonexistent", "executing", state_dir=state_dir)

    def test_returns_updated_dict(self, tmp_path):
        """update_phase() returns the updated hook dict."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        result = update_phase("orchestrator", "auth", "impl_complete", state_dir=state_dir)
        assert result["phase"] == "impl_complete"


# ---------------------------------------------------------------------------
# TestUpdateResumptionInstructions
# ---------------------------------------------------------------------------

class TestUpdateResumptionInstructions:
    """Tests for update_resumption_instructions()."""

    def test_stores_instructions(self, tmp_path):
        """update_resumption_instructions() stores the instructions string."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        update_resumption_instructions(
            "orchestrator", "auth",
            instructions="Continue from step 3: implement login endpoint",
            state_dir=state_dir,
        )
        result = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["resumption_instructions"] == "Continue from step 3: implement login endpoint"

    def test_stores_last_committed_node(self, tmp_path):
        """update_resumption_instructions() stores last_committed_node when provided."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        update_resumption_instructions(
            "orchestrator", "auth",
            instructions="Resume after impl_auth_db",
            last_committed_node="impl_auth_db",
            state_dir=state_dir,
        )
        result = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["last_committed_node"] == "impl_auth_db"

    def test_last_committed_node_optional(self, tmp_path):
        """update_resumption_instructions() works without last_committed_node."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        update_resumption_instructions(
            "orchestrator", "auth",
            instructions="Resume from start",
            state_dir=state_dir,
        )
        result = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["last_committed_node"] is None

    def test_raises_if_missing(self, tmp_path):
        """update_resumption_instructions() raises FileNotFoundError if no hook exists."""
        state_dir = str(tmp_path / "hooks")
        with pytest.raises(FileNotFoundError):
            update_resumption_instructions(
                "orchestrator", "nonexistent",
                instructions="test",
                state_dir=state_dir,
            )

    def test_returns_updated_dict(self, tmp_path):
        """update_resumption_instructions() returns the updated hook dict."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        result = update_resumption_instructions(
            "orchestrator", "auth",
            instructions="test instructions",
            state_dir=state_dir,
        )
        assert result["resumption_instructions"] == "test instructions"


# ---------------------------------------------------------------------------
# TestMarkMerged
# ---------------------------------------------------------------------------

class TestMarkMerged:
    """Tests for mark_merged()."""

    def test_sets_phase_to_merged(self, tmp_path):
        """mark_merged() sets phase to 'merged'."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        mark_merged("orchestrator", "auth", state_dir=state_dir)
        result = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["phase"] == "merged"

    def test_sets_merged_at(self, tmp_path):
        """mark_merged() populates merged_at with a timestamp."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        mark_merged("orchestrator", "auth", state_dir=state_dir)
        result = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["merged_at"] is not None

    def test_updates_updated_at(self, tmp_path):
        """mark_merged() also bumps updated_at."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        original = read_hook("orchestrator", "auth", state_dir=state_dir)
        time.sleep(1.05)
        mark_merged("orchestrator", "auth", state_dir=state_dir)
        result = read_hook("orchestrator", "auth", state_dir=state_dir)
        assert result["updated_at"] != original["updated_at"]

    def test_raises_if_missing(self, tmp_path):
        """mark_merged() raises FileNotFoundError if no hook exists."""
        state_dir = str(tmp_path / "hooks")
        with pytest.raises(FileNotFoundError):
            mark_merged("orchestrator", "nonexistent", state_dir=state_dir)

    def test_returns_updated_dict(self, tmp_path):
        """mark_merged() returns the updated hook dict."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "auth", state_dir=state_dir)
        result = mark_merged("orchestrator", "auth", state_dir=state_dir)
        assert result["phase"] == "merged"
        assert result["merged_at"] is not None
