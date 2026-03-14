"""Unit tests for signal_protocol.py.

Tests:
    TestWriteSignal      - write_signal() creates correctly named file with correct content
    TestReadSignal       - read_signal() parses file correctly
    TestWaitForSignal    - wait_for_signal() returns immediately when signal exists,
                           raises TimeoutError when timeout < poll interval
    TestMoveToProcessed  - move_to_processed() moves file to processed/ subdir
    TestListSignals      - list_signals() returns correct files, filters by target
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

# Ensure attractor package is importable

from cobuilder.engine.signal_protocol import (  # noqa: E402
    AGENT_CRASHED,
    AGENT_REGISTERED,
    AGENT_TERMINATED,
    RUNNER_EXITED,
    list_signals,
    move_to_processed,
    read_signal,
    wait_for_signal,
    write_agent_crashed,
    write_agent_registered,
    write_agent_terminated,
    write_runner_exited,
    write_signal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_test_signal(signals_dir: str, source: str = "runner",
                        target: str = "guardian",
                        signal_type: str = "NEEDS_REVIEW",
                        payload: dict = None) -> str:
    """Write a signal and return the path."""
    return write_signal(
        source=source,
        target=target,
        signal_type=signal_type,
        payload=payload or {"node_id": "test_node"},
        signals_dir=signals_dir,
    )


# ---------------------------------------------------------------------------
# TestWriteSignal
# ---------------------------------------------------------------------------

class TestWriteSignal:
    """Tests for write_signal()."""

    def test_creates_file(self, tmp_path):
        """write_signal() creates a .json file in the signals directory."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "NEEDS_REVIEW",
                            {"node_id": "impl_auth"}, signals_dir=signals_dir)
        assert os.path.exists(path)

    def test_filename_format(self, tmp_path):
        """Signal filename follows {timestamp}-{source}-{target}-{signal_type}.json."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "NEEDS_REVIEW",
                            {"node_id": "impl_auth"}, signals_dir=signals_dir)
        fname = os.path.basename(path)
        assert fname.endswith(".json")
        # Should have at least 4 dash-separated parts after the timestamp
        # Format: 20260224T120000Z-runner-guardian-NEEDS_REVIEW.json
        parts = fname[:-5].split("-")  # strip .json
        assert len(parts) >= 4, f"Unexpected filename format: {fname}"
        # timestamp is first segment (no dashes, ends with Z)
        assert parts[0].endswith("Z"), f"Timestamp segment: {parts[0]}"
        assert parts[1] == "runner"
        assert parts[2] == "guardian"
        assert parts[3] == "NEEDS_REVIEW"

    def test_correct_json_content(self, tmp_path):
        """Signal file contains correct JSON with all required fields."""
        signals_dir = str(tmp_path / "signals")
        payload = {"node_id": "impl_auth", "commit_hash": "abc123"}
        path = write_signal("runner", "guardian", "NEEDS_REVIEW",
                            payload, signals_dir=signals_dir)

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["source"] == "runner"
        assert data["target"] == "guardian"
        assert data["signal_type"] == "NEEDS_REVIEW"
        assert "timestamp" in data
        assert data["payload"]["node_id"] == "impl_auth"
        assert data["payload"]["commit_hash"] == "abc123"

    def test_atomic_no_tmp_file_left(self, tmp_path):
        """No .tmp file is left behind after write_signal()."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "NEEDS_REVIEW",
                            {"node_id": "impl_auth"}, signals_dir=signals_dir)
        tmp_path_check = path + ".tmp"
        assert not os.path.exists(tmp_path_check), ".tmp file should be removed"

    def test_creates_signals_dir_if_not_exists(self, tmp_path):
        """write_signal() creates the signals directory if it does not exist."""
        signals_dir = str(tmp_path / "nested" / "deep" / "signals")
        assert not os.path.exists(signals_dir)
        write_signal("runner", "guardian", "TEST", {}, signals_dir=signals_dir)
        assert os.path.isdir(signals_dir)

    def test_creates_processed_subdir(self, tmp_path):
        """write_signal() creates the processed/ subdirectory."""
        signals_dir = str(tmp_path / "signals")
        write_signal("runner", "guardian", "TEST", {}, signals_dir=signals_dir)
        assert os.path.isdir(os.path.join(signals_dir, "processed"))

    def test_returns_absolute_path(self, tmp_path):
        """write_signal() returns an absolute path."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "TEST", {}, signals_dir=signals_dir)
        assert os.path.isabs(path)

    def test_different_sources_and_targets(self, tmp_path):
        """write_signal() handles different source/target combinations."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("guardian", "runner", "APPROVED",
                            {"node_id": "n1"}, signals_dir=signals_dir)
        data = json.loads(open(path).read())
        assert data["source"] == "guardian"
        assert data["target"] == "runner"
        assert data["signal_type"] == "APPROVED"


# ---------------------------------------------------------------------------
# TestReadSignal
# ---------------------------------------------------------------------------

class TestReadSignal:
    """Tests for read_signal()."""

    def test_reads_and_parses_correctly(self, tmp_path):
        """read_signal() returns the full signal dict from file."""
        signals_dir = str(tmp_path / "signals")
        payload = {"node_id": "impl_auth", "evidence_path": "/tmp/ev"}
        path = write_signal("runner", "guardian", "NEEDS_REVIEW",
                            payload, signals_dir=signals_dir)

        data = read_signal(path)

        assert data["source"] == "runner"
        assert data["target"] == "guardian"
        assert data["signal_type"] == "NEEDS_REVIEW"
        assert data["payload"]["node_id"] == "impl_auth"
        assert data["payload"]["evidence_path"] == "/tmp/ev"
        assert "timestamp" in data

    def test_raises_file_not_found(self, tmp_path):
        """read_signal() raises FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            read_signal(str(tmp_path / "nonexistent.json"))

    def test_raises_json_decode_error_for_invalid_json(self, tmp_path):
        """read_signal() raises json.JSONDecodeError for invalid JSON."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            read_signal(str(bad_file))


# ---------------------------------------------------------------------------
# TestWaitForSignal
# ---------------------------------------------------------------------------

class TestWaitForSignal:
    """Tests for wait_for_signal()."""

    def test_returns_immediately_when_signal_exists(self, tmp_path):
        """wait_for_signal() returns immediately when a matching signal exists."""
        signals_dir = str(tmp_path / "signals")
        payload = {"node_id": "impl_auth"}
        write_signal("runner", "guardian", "NEEDS_REVIEW",
                     payload, signals_dir=signals_dir)

        start = time.monotonic()
        data = wait_for_signal("guardian", timeout=30.0, signals_dir=signals_dir,
                               poll_interval=1.0)
        elapsed = time.monotonic() - start

        assert data["source"] == "runner"
        assert data["target"] == "guardian"
        assert data["signal_type"] == "NEEDS_REVIEW"
        assert elapsed < 2.0, f"Should return quickly, took {elapsed:.2f}s"

    def test_raises_timeout_error_when_no_signal(self, tmp_path):
        """wait_for_signal() raises TimeoutError when no signal appears."""
        signals_dir = str(tmp_path / "signals")

        with pytest.raises(TimeoutError):
            wait_for_signal("guardian", timeout=0.1, signals_dir=signals_dir,
                            poll_interval=0.05)

    def test_moves_signal_to_processed_after_reading(self, tmp_path):
        """wait_for_signal() moves the signal file to processed/ after consuming it."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "NEEDS_REVIEW",
                            {"node_id": "n1"}, signals_dir=signals_dir)

        wait_for_signal("guardian", timeout=5.0, signals_dir=signals_dir,
                        poll_interval=0.1)

        # Original file should be gone
        assert not os.path.exists(path)
        # Should be in processed/
        processed_dir = os.path.join(signals_dir, "processed")
        processed_files = os.listdir(processed_dir)
        assert len(processed_files) == 1

    def test_returns_correct_signal_content(self, tmp_path):
        """wait_for_signal() returns the correct signal data."""
        signals_dir = str(tmp_path / "signals")
        payload = {"node_id": "impl_auth", "commit_hash": "deadbeef"}
        write_signal("runner", "guardian", "NEEDS_REVIEW",
                     payload, signals_dir=signals_dir)

        data = wait_for_signal("guardian", timeout=5.0, signals_dir=signals_dir,
                               poll_interval=0.1)

        assert data["payload"]["node_id"] == "impl_auth"
        assert data["payload"]["commit_hash"] == "deadbeef"

    def test_timeout_less_than_poll_interval_raises(self, tmp_path):
        """wait_for_signal() raises TimeoutError even when timeout < poll_interval."""
        signals_dir = str(tmp_path / "signals")

        with pytest.raises(TimeoutError):
            # timeout=0.01 is less than poll_interval=1.0
            wait_for_signal("guardian", timeout=0.01, signals_dir=signals_dir,
                            poll_interval=1.0)

    def test_filters_by_target_layer(self, tmp_path):
        """wait_for_signal() only picks up signals for the requested target."""
        signals_dir = str(tmp_path / "signals")
        # Write a signal for "runner", not "guardian"
        write_signal("guardian", "runner", "APPROVED",
                     {"node_id": "n1"}, signals_dir=signals_dir)

        # Waiting for "guardian" should timeout since only "runner" signal exists
        with pytest.raises(TimeoutError):
            wait_for_signal("guardian", timeout=0.1, signals_dir=signals_dir,
                            poll_interval=0.05)


# ---------------------------------------------------------------------------
# TestMoveToProcessed
# ---------------------------------------------------------------------------

class TestMoveToProcessed:
    """Tests for move_to_processed()."""

    def test_moves_file_to_processed_subdir(self, tmp_path):
        """move_to_processed() moves signal file to processed/ subdirectory."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "TEST",
                            {"node_id": "n1"}, signals_dir=signals_dir)

        new_path = move_to_processed(path)

        assert not os.path.exists(path), "Original file should be gone"
        assert os.path.exists(new_path), "File should exist at new path"
        assert "processed" in new_path

    def test_returns_new_path(self, tmp_path):
        """move_to_processed() returns the new path in processed/."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "TEST",
                            {"node_id": "n1"}, signals_dir=signals_dir)

        new_path = move_to_processed(path)

        expected_dir = os.path.join(signals_dir, "processed")
        assert os.path.dirname(new_path) == expected_dir

    def test_content_preserved_after_move(self, tmp_path):
        """File content is unchanged after move_to_processed()."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "TEST",
                            {"node_id": "n1", "key": "value"}, signals_dir=signals_dir)

        new_path = move_to_processed(path)
        data = read_signal(new_path)

        assert data["payload"]["key"] == "value"

    def test_creates_processed_dir_if_missing(self, tmp_path):
        """move_to_processed() creates the processed/ dir if it doesn't exist."""
        signals_dir = str(tmp_path / "signals")
        os.makedirs(signals_dir)

        # Manually create a signal file without the processed/ dir
        path = os.path.join(signals_dir, "20260224T000000Z-a-b-TEST.json")
        with open(path, "w") as fh:
            json.dump({"source": "a", "target": "b", "signal_type": "TEST",
                       "timestamp": "20260224T000000Z", "payload": {}}, fh)

        processed_dir = os.path.join(signals_dir, "processed")
        assert not os.path.exists(processed_dir)

        move_to_processed(path)
        assert os.path.isdir(processed_dir)


# ---------------------------------------------------------------------------
# TestListSignals
# ---------------------------------------------------------------------------

class TestListSignals:
    """Tests for list_signals()."""

    def test_returns_empty_for_missing_dir(self, tmp_path):
        """list_signals() returns [] if the signals directory does not exist."""
        signals_dir = str(tmp_path / "nonexistent")
        result = list_signals(signals_dir=signals_dir)
        assert result == []

    def test_returns_all_signals_when_no_filter(self, tmp_path):
        """list_signals() returns all .json files when no target_layer filter."""
        signals_dir = str(tmp_path / "signals")
        write_signal("runner", "guardian", "NEEDS_REVIEW",
                     {"node_id": "n1"}, signals_dir=signals_dir)
        write_signal("guardian", "runner", "APPROVED",
                     {"node_id": "n2"}, signals_dir=signals_dir)

        result = list_signals(signals_dir=signals_dir)
        assert len(result) == 2

    def test_filters_by_target_layer(self, tmp_path):
        """list_signals() filters by target_layer in filename."""
        signals_dir = str(tmp_path / "signals")
        write_signal("runner", "guardian", "NEEDS_REVIEW",
                     {"node_id": "n1"}, signals_dir=signals_dir)
        write_signal("guardian", "runner", "APPROVED",
                     {"node_id": "n2"}, signals_dir=signals_dir)
        write_signal("runner", "guardian", "STUCK",
                     {"node_id": "n3"}, signals_dir=signals_dir)

        guardian_signals = list_signals(target_layer="guardian", signals_dir=signals_dir)
        runner_signals = list_signals(target_layer="runner", signals_dir=signals_dir)

        assert len(guardian_signals) == 2
        assert len(runner_signals) == 1

    def test_does_not_include_processed_dir(self, tmp_path):
        """list_signals() does not recurse into processed/."""
        signals_dir = str(tmp_path / "signals")
        path = write_signal("runner", "guardian", "TEST",
                            {"node_id": "n1"}, signals_dir=signals_dir)
        move_to_processed(path)

        result = list_signals(signals_dir=signals_dir)
        assert len(result) == 0

    def test_does_not_include_tmp_files(self, tmp_path):
        """list_signals() does not include .tmp files."""
        signals_dir = str(tmp_path / "signals")
        os.makedirs(signals_dir, exist_ok=True)
        tmp_file = os.path.join(signals_dir, "20260224T000000Z-a-b-TEST.json.tmp")
        with open(tmp_file, "w") as fh:
            fh.write("{}")

        result = list_signals(signals_dir=signals_dir)
        assert len(result) == 0

    def test_returns_absolute_paths(self, tmp_path):
        """list_signals() returns absolute paths."""
        signals_dir = str(tmp_path / "signals")
        write_signal("runner", "guardian", "TEST",
                     {"node_id": "n1"}, signals_dir=signals_dir)

        result = list_signals(signals_dir=signals_dir)
        for path in result:
            assert os.path.isabs(path), f"Expected absolute path: {path}"

    def test_sorted_chronologically(self, tmp_path):
        """list_signals() returns files sorted chronologically (by filename)."""
        signals_dir = str(tmp_path / "signals")
        # Write signals with small delays to get different timestamps
        p1 = write_signal("runner", "guardian", "FIRST",
                          {"node_id": "n1"}, signals_dir=signals_dir)
        time.sleep(0.01)
        p2 = write_signal("runner", "guardian", "SECOND",
                          {"node_id": "n2"}, signals_dir=signals_dir)

        result = list_signals(signals_dir=signals_dir)
        assert len(result) == 2
        # Earlier file should come first
        assert result[0] == p1 or os.path.basename(result[0]) <= os.path.basename(result[1])


# ---------------------------------------------------------------------------
# TestAgentLifecycleSignals
# ---------------------------------------------------------------------------

class TestAgentLifecycleSignals:
    """Tests for write_agent_registered(), write_agent_crashed(), write_agent_terminated()."""

    def test_write_agent_registered_creates_file(self, tmp_path):
        """write_agent_registered() creates a signal file."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_registered(
            agent_id="orchestrator-auth-20260226T120000Z",
            role="orchestrator",
            name="auth",
            session_id="orch-auth",
            worktree=".claude/worktrees/auth",
            signals_dir=signals_dir,
        )
        assert os.path.exists(path)

    def test_write_agent_registered_correct_signal_type(self, tmp_path):
        """write_agent_registered() uses AGENT_REGISTERED signal type."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_registered(
            agent_id="orchestrator-auth-20260226T120000Z",
            role="orchestrator",
            name="auth",
            session_id="orch-auth",
            worktree=".claude/worktrees/auth",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        assert data["signal_type"] == AGENT_REGISTERED
        assert data["target"] == "guardian"
        assert data["source"] == "orchestrator"

    def test_write_agent_registered_correct_payload(self, tmp_path):
        """write_agent_registered() embeds correct payload fields."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_registered(
            agent_id="runner-n1-20260226T120000Z",
            role="runner",
            name="n1",
            session_id="runner-n1",
            worktree="",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        payload = data["payload"]
        assert payload["agent_id"] == "runner-n1-20260226T120000Z"
        assert payload["role"] == "runner"
        assert payload["name"] == "n1"
        assert payload["session_id"] == "runner-n1"
        assert payload["worktree"] == ""

    def test_write_agent_crashed_creates_file(self, tmp_path):
        """write_agent_crashed() creates a signal file."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_crashed(
            agent_id="runner-n1-20260226T120000Z",
            role="runner",
            name="n1",
            crashed_at="2026-02-26T12:30:00Z",
            signals_dir=signals_dir,
        )
        assert os.path.exists(path)

    def test_write_agent_crashed_correct_signal_type(self, tmp_path):
        """write_agent_crashed() uses AGENT_CRASHED signal type."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_crashed(
            agent_id="runner-n1-20260226T120000Z",
            role="runner",
            name="n1",
            crashed_at="2026-02-26T12:30:00Z",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        assert data["signal_type"] == AGENT_CRASHED
        assert data["source"] == "runner"
        assert data["target"] == "guardian"

    def test_write_agent_crashed_correct_payload(self, tmp_path):
        """write_agent_crashed() embeds correct payload fields."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_crashed(
            agent_id="runner-n1-20260226T120000Z",
            role="runner",
            name="n1",
            crashed_at="2026-02-26T12:30:00Z",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        payload = data["payload"]
        assert payload["agent_id"] == "runner-n1-20260226T120000Z"
        assert payload["role"] == "runner"
        assert payload["name"] == "n1"
        assert payload["crashed_at"] == "2026-02-26T12:30:00Z"

    def test_write_agent_terminated_creates_file(self, tmp_path):
        """write_agent_terminated() creates a signal file."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_terminated(
            agent_id="guardian-pipeline-1-20260226T120000Z",
            role="guardian",
            name="pipeline-1",
            terminated_at="2026-02-26T13:00:00Z",
            signals_dir=signals_dir,
        )
        assert os.path.exists(path)

    def test_write_agent_terminated_correct_signal_type(self, tmp_path):
        """write_agent_terminated() uses AGENT_TERMINATED signal type."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_terminated(
            agent_id="guardian-pipeline-1-20260226T120000Z",
            role="guardian",
            name="pipeline-1",
            terminated_at="2026-02-26T13:00:00Z",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        assert data["signal_type"] == AGENT_TERMINATED
        assert data["source"] == "guardian"
        assert data["target"] == "guardian"

    def test_write_agent_terminated_correct_payload(self, tmp_path):
        """write_agent_terminated() embeds correct payload fields."""
        signals_dir = str(tmp_path / "signals")
        path = write_agent_terminated(
            agent_id="guardian-pipeline-1-20260226T120000Z",
            role="guardian",
            name="pipeline-1",
            terminated_at="2026-02-26T13:00:00Z",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        payload = data["payload"]
        assert payload["agent_id"] == "guardian-pipeline-1-20260226T120000Z"
        assert payload["role"] == "guardian"
        assert payload["name"] == "pipeline-1"
        assert payload["terminated_at"] == "2026-02-26T13:00:00Z"

    def test_agent_constants_have_correct_values(self):
        """AGENT_REGISTERED, AGENT_CRASHED, AGENT_TERMINATED constants are correct strings."""
        assert AGENT_REGISTERED == "AGENT_REGISTERED"
        assert AGENT_CRASHED == "AGENT_CRASHED"
        assert AGENT_TERMINATED == "AGENT_TERMINATED"


# ---------------------------------------------------------------------------
# TestRunnerExitedSignal (Task #2 — RUNNER_EXITED constant + write_runner_exited)
# ---------------------------------------------------------------------------


class TestRunnerExitedSignal:
    """Tests for RUNNER_EXITED constant and write_runner_exited()."""

    def test_runner_exited_constant_value(self):
        """RUNNER_EXITED constant must be the string 'RUNNER_EXITED'."""
        assert RUNNER_EXITED == "RUNNER_EXITED"

    def test_write_runner_exited_creates_file(self, tmp_path):
        """write_runner_exited() creates a signal file in the signals directory."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        assert os.path.exists(path)

    def test_write_runner_exited_returns_absolute_path(self, tmp_path):
        """write_runner_exited() returns an absolute path."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        assert os.path.isabs(path)

    def test_write_runner_exited_signal_type(self, tmp_path):
        """write_runner_exited() writes a signal with type RUNNER_EXITED."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        assert data["signal_type"] == RUNNER_EXITED

    def test_write_runner_exited_source_is_runner(self, tmp_path):
        """write_runner_exited() writes a signal sourced from 'runner'."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        assert data["source"] == "runner"

    def test_write_runner_exited_target_is_guardian(self, tmp_path):
        """write_runner_exited() targets the guardian layer."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        assert data["target"] == "guardian"

    def test_write_runner_exited_payload_fields(self, tmp_path):
        """write_runner_exited() embeds all required payload fields."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_payments",
            prd_ref="PRD-PAY-007",
            mode="MONITOR",
            reason="runner_exited_without_complete",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        payload = data["payload"]
        assert payload["node_id"] == "impl_payments"
        assert payload["prd_ref"] == "PRD-PAY-007"
        assert payload["mode"] == "MONITOR"
        assert payload["reason"] == "runner_exited_without_complete"

    def test_write_runner_exited_mode_complete(self, tmp_path):
        """write_runner_exited() works with any mode string including COMPLETE."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="COMPLETE",
            reason="unexpected_complete_in_safety_net",
            signals_dir=signals_dir,
        )
        data = read_signal(path)
        assert data["payload"]["mode"] == "COMPLETE"

    def test_write_runner_exited_filename_contains_runner_exited(self, tmp_path):
        """Signal filename should contain RUNNER_EXITED signal type."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        fname = os.path.basename(path)
        assert "RUNNER_EXITED" in fname

    def test_write_runner_exited_no_tmp_file_left(self, tmp_path):
        """No .tmp file is left behind after write_runner_exited()."""
        signals_dir = str(tmp_path / "signals")
        path = write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        assert not os.path.exists(path + ".tmp")

    def test_write_runner_exited_creates_processed_subdir(self, tmp_path):
        """write_runner_exited() creates the processed/ subdirectory."""
        signals_dir = str(tmp_path / "signals")
        write_runner_exited(
            node_id="impl_auth",
            prd_ref="PRD-AUTH-001",
            mode="FAILED",
            reason="max_cycles_exceeded",
            signals_dir=signals_dir,
        )
        assert os.path.isdir(os.path.join(signals_dir, "processed"))
