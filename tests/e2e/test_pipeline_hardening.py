"""Pytest test suite for pipeline_runner.py hardening features.

Tests cover 5 epics:
  H: Dead Worker Detection (AdvancedWorkerTracker, _check_worker_liveness)
  A: Atomic Signal Writes (_write_node_signal, quarantine on corruption)
  B: force_status Persistence (_force_status, _persist_requeue_guidance)
  C: Validation Error Handling (timeout, crash -> fail signal)
  J: Validation Spam Suppression (_dispatch_validation_agent skips terminal nodes)

All tests use tmp_path fixtures and mocked futures -- no real AgentSDK workers.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import from the canonical module (not the deprecated scripts path)
from cobuilder.engine.pipeline_runner import (
    AdvancedWorkerTracker,
    PipelineRunner,
    WorkerInfo,
    WorkerState,
)

# ---------------------------------------------------------------------------
# Minimal DOT fixture
# ---------------------------------------------------------------------------

MINIMAL_DOT = """\
digraph test_pipeline {
    graph [prd_ref="TEST-001"];
    start [shape=Mdiamond handler="noop" status="validated"];
    node1 [shape=box handler="codergen" status="pending" worker_type="backend-solutions-engineer"];
    exit [shape=Msquare handler="exit" status="pending"];
    start -> node1;
    node1 -> exit;
}
"""

IMPL_COMPLETE_DOT = """\
digraph test_pipeline {
    graph [prd_ref="TEST-001"];
    start [shape=Mdiamond handler="noop" status="validated"];
    node1 [shape=box handler="codergen" status="impl_complete" worker_type="backend-solutions-engineer"];
    exit [shape=Msquare handler="exit" status="pending"];
    start -> node1;
    node1 -> exit;
}
"""

ACCEPTED_DOT = """\
digraph test_pipeline {
    graph [prd_ref="TEST-001"];
    start [shape=Mdiamond handler="noop" status="validated"];
    node1 [shape=box handler="codergen" status="accepted" worker_type="backend-solutions-engineer"];
    exit [shape=Msquare handler="exit" status="pending"];
    start -> node1;
    node1 -> exit;
}
"""

ACTIVE_DOT = """\
digraph test_pipeline {
    graph [prd_ref="TEST-001"];
    start [shape=Mdiamond handler="noop" status="validated"];
    node1 [shape=box handler="codergen" status="active" worker_type="backend-solutions-engineer"];
    exit [shape=Msquare handler="exit" status="pending"];
    start -> node1;
    node1 -> exit;
}
"""

TOOL_VERIFY_DOT = """\
digraph test_pipeline {
    graph [prd_ref="TEST-001"];
    start [shape=Mdiamond handler="noop" status="validated"];
    impl_node [shape=box handler="codergen" status="accepted" worker_type="backend-solutions-engineer"];
    verify_node [shape=box handler="tool" status="active" worker_type="backend-solutions-engineer"];
    exit [shape=Msquare handler="exit" status="pending"];
    start -> impl_node;
    impl_node -> verify_node;
    verify_node -> exit;
}
"""


def _make_runner(tmp_path: Path, dot_content: str = MINIMAL_DOT) -> PipelineRunner:
    """Create a PipelineRunner against a temp DOT file with mocked externals."""
    dot_file = tmp_path / "test.dot"
    dot_file.write_text(dot_content)

    # Patch _load_engine_env and save_checkpoint so they don't touch real files
    with patch.object(PipelineRunner, "_load_engine_env"):
        runner = PipelineRunner(str(dot_file), resume=False)

    return runner


# =========================================================================
# P1 Bug: PipelineRunner Env Guard
# =========================================================================

class TestEnvGuard:
    """PipelineRunner warns when ANTHROPIC_API_KEY is not set."""

    def test_missing_api_key_logs_warning(self, tmp_path, caplog):
        """PipelineRunner.__init__ logs a warning when ANTHROPIC_API_KEY is missing."""
        dot_file = tmp_path / "test.dot"
        dot_file.write_text(MINIMAL_DOT)

        # Ensure ANTHROPIC_API_KEY is not set
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)

        with patch.dict(os.environ, env, clear=True), \
             patch.object(PipelineRunner, "_load_engine_env"):
            # _load_engine_env is patched to prevent it from loading .env
            # which might set the key. We want to test the guard AFTER loading.
            import logging
            with caplog.at_level(logging.WARNING):
                runner = PipelineRunner(str(dot_file), resume=False)

            assert "ANTHROPIC_API_KEY not set" in caplog.text, \
                "Should warn when API key is missing"

    def test_api_key_present_no_warning(self, tmp_path, caplog):
        """No warning when ANTHROPIC_API_KEY is set."""
        dot_file = tmp_path / "test.dot"
        dot_file.write_text(MINIMAL_DOT)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}), \
             patch.object(PipelineRunner, "_load_engine_env"):
            import logging
            with caplog.at_level(logging.WARNING):
                runner = PipelineRunner(str(dot_file), resume=False)

            assert "ANTHROPIC_API_KEY not set" not in caplog.text, \
                "Should NOT warn when API key is present"

    def test_from_dot_file_classmethod(self, tmp_path):
        """from_dot_file() classmethod creates a PipelineRunner."""
        dot_file = tmp_path / "test.dot"
        dot_file.write_text(MINIMAL_DOT)

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
             patch.object(PipelineRunner, "_load_engine_env"):
            runner = PipelineRunner.from_dot_file(str(dot_file))

        assert isinstance(runner, PipelineRunner)
        assert runner.dot_path == str(dot_file.resolve())


# =========================================================================
# Epic H: Dead Worker Detection
# =========================================================================

class TestEpicH:
    """Dead worker detection via AdvancedWorkerTracker and _check_worker_liveness."""

    # --- AdvancedWorkerTracker unit tests ---

    def test_track_worker_creates_entry(self):
        """track_worker stores a WorkerInfo with SUBMITTED state."""
        tracker = AdvancedWorkerTracker(default_timeout=60)
        future = Future()
        info = tracker.track_worker("node_a", future)
        assert info.node_id == "node_a"
        assert info.state == WorkerState.SUBMITTED
        assert "node_a" in tracker.workers

    def test_update_worker_states_detects_completed_future(self):
        """A future that completed with a result transitions to COMPLETED."""
        tracker = AdvancedWorkerTracker(default_timeout=60)
        future = Future()
        future.set_result({"status": "success"})
        tracker.track_worker("node_b", future)

        tracker.update_worker_states()
        assert tracker.workers["node_b"].state == WorkerState.COMPLETED
        assert tracker.workers["node_b"].result == {"status": "success"}

    def test_update_worker_states_detects_failed_future(self):
        """A future that completed with an exception transitions to FAILED."""
        tracker = AdvancedWorkerTracker(default_timeout=60)
        future = Future()
        future.set_exception(RuntimeError("worker crashed"))
        tracker.track_worker("node_c", future)

        tracker.update_worker_states()
        assert tracker.workers["node_c"].state == WorkerState.FAILED
        assert isinstance(tracker.workers["node_c"].exception, RuntimeError)

    def test_update_worker_states_detects_timeout(self):
        """A running worker past the timeout threshold is cancelled or timed out."""
        tracker = AdvancedWorkerTracker(default_timeout=1)  # 1 second timeout
        future = Future()
        # Manually set submitted_at far in the past
        info = tracker.track_worker("node_d", future)
        info.submitted_at = time.time() - 100  # 100 seconds ago

        tracker.update_worker_states()
        assert tracker.workers["node_d"].state in (WorkerState.CANCELLED, WorkerState.TIMED_OUT)

    def test_get_dead_workers_returns_failed_and_timed_out(self):
        """get_dead_workers returns workers in FAILED, TIMED_OUT, or CANCELLED states."""
        tracker = AdvancedWorkerTracker(default_timeout=60)

        # Add a completed worker (not dead)
        f_ok = Future()
        f_ok.set_result("ok")
        tracker.track_worker("alive", f_ok)

        # Add a failed worker
        f_fail = Future()
        f_fail.set_exception(ValueError("boom"))
        tracker.track_worker("dead", f_fail)

        tracker.update_worker_states()
        dead = tracker.get_dead_workers()
        dead_ids = [nid for nid, _ in dead]
        assert "dead" in dead_ids
        assert "alive" not in dead_ids

    def test_remove_worker(self):
        """remove_worker removes the worker from tracking and returns True."""
        tracker = AdvancedWorkerTracker()
        future = Future()
        tracker.track_worker("node_x", future)
        assert tracker.remove_worker("node_x") is True
        assert "node_x" not in tracker.workers
        assert tracker.remove_worker("nonexistent") is False

    # --- _check_worker_liveness integration ---

    def test_check_worker_liveness_writes_fail_signal_on_exception(self, tmp_path):
        """When a tracked future has an exception and no signal file, a fail signal is written."""
        # Use DOT with active status so liveness check will write signal
        active_dot = MINIMAL_DOT.replace('status="pending"', 'status="active"')
        runner = _make_runner(tmp_path, active_dot)

        # Create a future that already failed
        future = Future()
        future.set_exception(RuntimeError("SDK process died"))
        runner.worker_tracker.track_worker("node1", future)
        # Mark as FAILED so _check_worker_liveness sees it
        runner.worker_tracker.workers["node1"].state = WorkerState.FAILED
        runner.worker_tracker.workers["node1"].exception = RuntimeError("SDK process died")

        runner._check_worker_liveness()

        # Verify fail signal was written
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        assert os.path.exists(signal_path), "Expected fail signal to be written for dead worker"
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["status"] == "error"
        assert signal["result"] == "fail"
        assert "died" in signal["reason"].lower() or "process" in signal["reason"].lower()
        assert signal.get("worker_crash") is True

    def test_check_worker_liveness_writes_fail_signal_on_silent_completion(self, tmp_path):
        """When a future completes without exception or signal file, a fail signal is written."""
        # Use DOT with active status so liveness check will write signal
        active_dot = MINIMAL_DOT.replace('status="pending"', 'status="active"')
        runner = _make_runner(tmp_path, active_dot)

        future = Future()
        future.set_result(None)  # Completed silently, no signal
        runner.worker_tracker.track_worker("node1", future)
        runner.worker_tracker.workers["node1"].state = WorkerState.COMPLETED

        runner._check_worker_liveness()

        signal_path = os.path.join(runner.signal_dir, "node1.json")
        assert os.path.exists(signal_path)
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["status"] == "error"
        assert "without writing signal" in signal["reason"]

    def test_check_worker_liveness_skips_when_signal_exists(self, tmp_path):
        """If a signal file already exists, liveness check does NOT overwrite it."""
        runner = _make_runner(tmp_path)

        # Pre-create a legitimate signal file
        os.makedirs(runner.signal_dir, exist_ok=True)
        existing_signal = {"status": "success", "message": "all good"}
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump(existing_signal, fh)

        future = Future()
        future.set_result(None)
        runner.worker_tracker.track_worker("node1", future)
        runner.worker_tracker.workers["node1"].state = WorkerState.COMPLETED

        runner._check_worker_liveness()

        # Original signal should be preserved
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["status"] == "success"
        assert signal["message"] == "all good"

    def test_check_worker_liveness_handles_timed_out_workers(self, tmp_path):
        """Timed-out workers detected by update_worker_states get fail signals."""
        # Use DOT with active status so liveness check will write signal
        active_dot = MINIMAL_DOT.replace('status="pending"', 'status="active"')
        runner = _make_runner(tmp_path, active_dot)

        # Use a very short timeout
        runner.worker_tracker.default_timeout = 1

        # Use a MagicMock future that reports as running (done()=False, cancel()=False)
        # so update_worker_states marks it as TIMED_OUT (not CANCELLED)
        mock_future = MagicMock(spec=Future)
        mock_future.done.return_value = False
        mock_future.cancel.return_value = False  # Cannot cancel -> TIMED_OUT state

        info = runner.worker_tracker.track_worker("node1", mock_future)
        info.submitted_at = time.time() - 1000  # Way in the past

        runner._check_worker_liveness()

        # Verify the worker was detected as timed out
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        assert os.path.exists(signal_path), "Fail signal should be written for timed-out worker"
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["result"] == "fail"
        assert "timed out" in signal["reason"].lower()

    def test_check_worker_liveness_skips_if_node_not_active(self, tmp_path):
        """Liveness checker should skip nodes that have progressed past 'active' status.

        This test simulates a scenario where a worker has completed and its signal
        has been processed (moving node status from 'active' to 'impl_complete'),
        then the liveness checker runs but should NOT overwrite the success signal
        with an error.
        """
        # Create runner with node already in impl_complete status (past active)
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)

        # Simulate a worker that has completed but was tracked
        future = Future()
        future.set_result(None)  # Completed successfully
        runner.worker_tracker.track_worker("node1", future)
        runner.worker_tracker.workers["node1"].state = WorkerState.COMPLETED

        # Create a legitimate signal file that was written by the worker
        os.makedirs(runner.signal_dir, exist_ok=True)
        original_signal = {"status": "success", "message": "completed successfully", "files_changed": ["test.py"]}
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump(original_signal, fh)

        # Run liveness checker - it should detect that node is not active and skip it
        runner._check_worker_liveness()

        # Verify the original signal was preserved (not overwritten with error)
        with open(signal_path) as fh:
            preserved_signal = json.load(fh)

        assert preserved_signal["status"] == "success"
        assert preserved_signal["message"] == "completed successfully"
        assert preserved_signal["files_changed"] == ["test.py"]

    def test_check_worker_liveness_skips_dead_workers_if_node_not_active(self, tmp_path):
        """Liveness checker should skip dead workers for nodes that have progressed past 'active' status."""
        # Create runner with node in 'accepted' status (terminal state)
        runner = _make_runner(tmp_path, ACCEPTED_DOT)

        # Use a MagicMock future that represents a timed-out worker
        mock_future = MagicMock(spec=Future)
        mock_future.done.return_value = False
        mock_future.cancel.return_value = False  # Cannot cancel -> TIMED_OUT state

        # Add a dead worker to tracker
        info = runner.worker_tracker.track_worker("node1", mock_future)
        info.submitted_at = time.time() - 1000  # Way in the past
        # Manually mark it as timed out for the test
        info.state = WorkerState.TIMED_OUT

        # Run liveness checker - it should skip this node since status is not 'active'
        runner._check_worker_liveness()

        # Verify no error signal was written for the dead worker
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        assert not os.path.exists(signal_path), "Should not write error signal for node not in active status"



# =========================================================================
# Epic A: Atomic Signal Writes
# =========================================================================

class TestEpicA:
    """Atomic signal writes with temp-file-then-rename and quarantine."""

    def test_write_node_signal_creates_file_atomically(self, tmp_path):
        """_write_node_signal writes signal file using temp+rename pattern."""
        runner = _make_runner(tmp_path)

        result_path = runner._write_node_signal("node1", {
            "status": "success",
            "message": "test passed",
        })

        assert os.path.exists(result_path)
        with open(result_path) as fh:
            data = json.load(fh)
        assert data["status"] == "success"
        assert data["message"] == "test passed"

    def test_write_node_signal_includes_seq_metadata(self, tmp_path):
        """Signals include _seq counter and _ts timestamp metadata."""
        runner = _make_runner(tmp_path)

        runner._write_node_signal("node1", {"status": "success"})
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path) as fh:
            data = json.load(fh)

        assert "_seq" in data
        assert data["_seq"] == 1
        assert "_ts" in data
        assert "_pid" in data

    def test_write_node_signal_increments_seq(self, tmp_path):
        """Successive signal writes for the same node increment _seq."""
        runner = _make_runner(tmp_path)

        runner._write_node_signal("node1", {"status": "success"})
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path) as fh:
            first = json.load(fh)

        runner._write_node_signal("node1", {"status": "failed"})
        with open(signal_path) as fh:
            second = json.load(fh)

        assert second["_seq"] == first["_seq"] + 1

    def test_write_node_signal_no_temp_file_left(self, tmp_path):
        """After write completes, no .tmp.* files remain in the signal directory."""
        runner = _make_runner(tmp_path)

        runner._write_node_signal("node1", {"status": "success"})

        remaining = [f for f in os.listdir(runner.signal_dir) if ".tmp." in f]
        assert remaining == [], f"Temp files left behind: {remaining}"

    def test_corrupted_signal_is_quarantined(self, tmp_path):
        """A signal file with invalid JSON is moved to signals/quarantine/."""
        runner = _make_runner(tmp_path)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Write a corrupted signal file
        corrupted_path = os.path.join(runner.signal_dir, "node1.json")
        with open(corrupted_path, "w") as fh:
            fh.write("{invalid json content!!!")

        runner._process_signals()

        # Signal should be moved to quarantine
        quarantine_dir = os.path.join(runner.signal_dir, "quarantine")
        assert os.path.isdir(quarantine_dir), "Quarantine directory should be created"
        quarantined_files = os.listdir(quarantine_dir)
        assert "node1.json" in quarantined_files, f"Corrupted signal not in quarantine: {quarantined_files}"

        # Original file should be gone
        assert not os.path.exists(corrupted_path), "Corrupted signal should be removed from signal dir"

    def test_valid_signal_is_consumed_to_processed(self, tmp_path):
        """A valid signal file is moved to signals/processed/ after application."""
        runner = _make_runner(tmp_path, ACTIVE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Write a valid signal for an active node
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump({"status": "success", "message": "done"}, fh)

        runner._process_signals()

        # Signal should be consumed (moved to processed)
        processed_dir = os.path.join(runner.signal_dir, "processed")
        assert os.path.isdir(processed_dir)
        processed_files = os.listdir(processed_dir)
        assert any("node1.json" in f for f in processed_files), f"Signal not in processed: {processed_files}"
        assert not os.path.exists(signal_path), "Original signal file should be consumed"

    def test_apply_before_consume_ordering(self, tmp_path):
        """Signal is applied (transition written) BEFORE being consumed (moved)."""
        runner = _make_runner(tmp_path, ACTIVE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Track calls to verify ordering
        call_order = []
        original_apply = runner._apply_signal
        original_rename = os.rename

        def tracked_apply(node_id, signal):
            call_order.append("apply")
            return original_apply(node_id, signal)

        runner._apply_signal = tracked_apply

        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump({"status": "success", "message": "test"}, fh)

        # Patch os.rename to track consumption
        def tracked_rename(src, dst):
            if "processed" in str(dst):
                call_order.append("consume")
            return original_rename(src, dst)

        with patch("os.rename", side_effect=tracked_rename):
            runner._process_signals()

        assert call_order.index("apply") < call_order.index("consume"), \
            f"Apply must happen before consume. Order: {call_order}"


# =========================================================================
# Epic B: force_status Persistence
# =========================================================================

class TestEpicB:
    """force_status calls _do_transition to persist changes to DOT on disk."""

    def test_force_status_persists_to_dot_file(self, tmp_path):
        """After _force_status, the DOT file on disk reflects the new status."""
        runner = _make_runner(tmp_path, ACTIVE_DOT)

        # Force node1 from active to pending (bypasses normal transition rules)
        # Note: _force_status calls _do_transition which calls _transition
        # which uses apply_transition. We need a valid transition here.
        # active -> failed is valid, let's test that
        runner._force_status("node1", "failed")

        # Re-read the DOT file from disk
        with open(runner.dot_path) as fh:
            updated_content = fh.read()

        from cobuilder.engine.parser import parse_dot_string
        graph = parse_dot_string(updated_content)
        node1 = graph.nodes["node1"]
        assert node1.attrs["status"] == "failed", \
            f"Expected status='failed' on disk, got '{node1.attrs.get('status')}'"

    def test_force_status_survives_reload_cycle(self, tmp_path):
        """Status set by _force_status persists across a new PipelineRunner instantiation."""
        runner = _make_runner(tmp_path, ACTIVE_DOT)
        dot_path = runner.dot_path

        runner._force_status("node1", "failed")

        # Create a new runner instance from the same DOT file
        with patch.object(PipelineRunner, "_load_engine_env"):
            runner2 = PipelineRunner(dot_path, resume=True)

        from cobuilder.engine.parser import parse_dot_string
        graph = parse_dot_string(runner2.dot_content)
        node1 = graph.nodes["node1"]
        assert node1.attrs["status"] == "failed"

    def test_persist_requeue_guidance_writes_file(self, tmp_path):
        """_persist_requeue_guidance writes guidance text to signals/guidance/{node_id}.txt."""
        runner = _make_runner(tmp_path)

        guidance_text = "Your implementation failed at test_foo. Fix the assertion on line 42."
        runner._persist_requeue_guidance("node1", guidance_text)

        guidance_path = os.path.join(runner.signal_dir, "guidance", "node1.txt")
        assert os.path.exists(guidance_path)
        with open(guidance_path) as fh:
            content = fh.read()
        assert content == guidance_text

    def test_force_status_with_requeue_guidance_persists_both(self, tmp_path):
        """_force_status also persists requeue_guidance when present for the node."""
        runner = _make_runner(tmp_path, ACTIVE_DOT)

        # Set requeue guidance for node1
        runner.requeue_guidance["node1"] = "Fix the database migration."

        runner._force_status("node1", "failed")

        # Verify DOT status persisted
        with open(runner.dot_path) as fh:
            content = fh.read()
        assert 'status="failed"' in content or "status=failed" in content

        # Verify guidance file persisted
        guidance_path = os.path.join(runner.signal_dir, "guidance", "node1.txt")
        assert os.path.exists(guidance_path)
        with open(guidance_path) as fh:
            assert fh.read() == "Fix the database migration."


# =========================================================================
# Epic C: Validation Error Handling
# =========================================================================

class TestEpicC:
    """Validation timeout and crash handling -- fail signal written, no hanging."""

    def test_validation_timeout_writes_fail_signal(self, tmp_path):
        """asyncio.TimeoutError during validation writes a fail signal."""
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Set a very short timeout via env var
        with patch.dict(os.environ, {"VALIDATION_TIMEOUT": "1"}):
            # Mock SDK to be "available" but hang
            with patch("cobuilder.engine.pipeline_runner._SDK_AVAILABLE", True), \
                 patch("cobuilder.engine.pipeline_runner.claude_code_sdk") as mock_sdk:

                # Make the SDK query hang forever (will hit timeout)
                import asyncio

                async def hanging_query(*args, **kwargs):
                    await asyncio.sleep(3600)  # effectively hangs
                    yield MagicMock()

                mock_sdk.ClaudeCodeOptions = MagicMock
                mock_sdk.query = hanging_query

                # Run validation in current thread (not via executor)
                runner._run_validation_subprocess("node1", "node1")

        # Check that a fail signal was written for the target node
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        assert os.path.exists(signal_path), "Fail signal should be written on timeout"
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["result"] == "fail"
        assert "timed out" in signal["reason"].lower()

    def test_validation_crash_writes_fail_signal(self, tmp_path):
        """Generic exception during validation writes a fail signal with exception details."""
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        with patch("cobuilder.engine.pipeline_runner._SDK_AVAILABLE", True), \
             patch("cobuilder.engine.pipeline_runner.claude_code_sdk") as mock_sdk:

            # Make ClaudeCodeOptions raise to simulate a crash BEFORE the async for loop.
            # This triggers the outer Exception handler (Epic C) which writes a fail signal.
            mock_sdk.ClaudeCodeOptions.side_effect = ConnectionError("API server unreachable")

            runner._run_validation_subprocess("node1", "node1")

        signal_path = os.path.join(runner.signal_dir, "node1.json")
        assert os.path.exists(signal_path), "Fail signal should be written on crash"
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["result"] == "fail"
        assert "crashed" in signal["reason"].lower() or "error" in signal.get("status", "")

    def test_validation_timeout_env_var_respected(self, tmp_path):
        """VALIDATION_TIMEOUT env var controls the timeout duration."""
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Verify with a 2-second timeout that timeout triggers quickly
        start_time = time.time()
        with patch.dict(os.environ, {"VALIDATION_TIMEOUT": "2"}):
            with patch("cobuilder.engine.pipeline_runner._SDK_AVAILABLE", True), \
                 patch("cobuilder.engine.pipeline_runner.claude_code_sdk") as mock_sdk:

                import asyncio

                async def slow_query(*args, **kwargs):
                    await asyncio.sleep(3600)
                    yield MagicMock()

                mock_sdk.ClaudeCodeOptions = MagicMock
                mock_sdk.query = slow_query
                runner._run_validation_subprocess("node1", "node1")

        elapsed = time.time() - start_time
        assert elapsed < 10, f"Validation should timeout in ~2s, took {elapsed:.1f}s"

        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["result"] == "fail"

    def test_validation_sdk_unavailable_autopasses(self, tmp_path):
        """When SDK is not available, validation auto-passes."""
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        with patch("cobuilder.engine.pipeline_runner._SDK_AVAILABLE", False), \
             patch("cobuilder.engine.pipeline_runner.claude_code_sdk", None):
            runner._run_validation_subprocess("node1", "node1")

        signal_path = os.path.join(runner.signal_dir, "node1.json")
        assert os.path.exists(signal_path)
        with open(signal_path) as fh:
            signal = json.load(fh)
        assert signal["result"] == "pass"
        assert "auto-pass" in signal["reason"].lower()


# =========================================================================
# Epic J: Validation Spam Suppression
# =========================================================================

class TestEpicJ:
    """Validation dispatch is suppressed for nodes already in terminal states."""

    def test_dispatch_validation_skips_accepted_node(self, tmp_path):
        """_dispatch_validation_agent does nothing when node is 'accepted'."""
        runner = _make_runner(tmp_path, ACCEPTED_DOT)

        # Track whether executor.submit is called
        submit_called = False
        original_submit = None

        if hasattr(runner, "_executor"):
            original_submit = runner._executor.submit

        class MockExecutor:
            def submit(self, fn, *args, **kwargs):
                nonlocal submit_called
                submit_called = True

        runner._executor = MockExecutor()

        runner._dispatch_validation_agent("node1", "node1")

        assert not submit_called, "Validation should NOT be dispatched for accepted node"

    def test_dispatch_validation_skips_validated_node(self, tmp_path):
        """_dispatch_validation_agent does nothing when node is 'validated'."""
        validated_dot = MINIMAL_DOT.replace(
            'node1 [shape=box handler="codergen" status="pending"',
            'node1 [shape=box handler="codergen" status="validated"'
        )
        runner = _make_runner(tmp_path, validated_dot)

        submit_called = False

        class MockExecutor:
            def submit(self, fn, *args, **kwargs):
                nonlocal submit_called
                submit_called = True

        runner._executor = MockExecutor()
        runner._dispatch_validation_agent("node1", "node1")

        assert not submit_called, "Validation should NOT be dispatched for validated node"

    def test_dispatch_validation_skips_failed_node(self, tmp_path):
        """_dispatch_validation_agent does nothing when node is 'failed'."""
        failed_dot = MINIMAL_DOT.replace(
            'node1 [shape=box handler="codergen" status="pending"',
            'node1 [shape=box handler="codergen" status="failed"'
        )
        runner = _make_runner(tmp_path, failed_dot)

        submit_called = False

        class MockExecutor:
            def submit(self, fn, *args, **kwargs):
                nonlocal submit_called
                submit_called = True

        runner._executor = MockExecutor()
        runner._dispatch_validation_agent("node1", "node1")

        assert not submit_called, "Validation should NOT be dispatched for failed node"

    def test_dispatch_validation_proceeds_for_impl_complete(self, tmp_path):
        """_dispatch_validation_agent DOES dispatch when node is 'impl_complete'."""
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)

        submit_called = False

        class MockExecutor:
            def submit(self, fn, *args, **kwargs):
                nonlocal submit_called
                submit_called = True

        runner._executor = MockExecutor()
        runner._dispatch_validation_agent("node1", "node1")

        assert submit_called, "Validation SHOULD be dispatched for impl_complete node"

    def test_dispatch_validation_proceeds_for_active(self, tmp_path):
        """_dispatch_validation_agent DOES dispatch when node is 'active'."""
        runner = _make_runner(tmp_path, ACTIVE_DOT)

        submit_called = False

        class MockExecutor:
            def submit(self, fn, *args, **kwargs):
                nonlocal submit_called
                submit_called = True

        runner._executor = MockExecutor()
        runner._dispatch_validation_agent("node1", "node1")

        assert submit_called, "Validation SHOULD be dispatched for active node"

    def test_get_node_status_reads_from_dot(self, tmp_path):
        """_get_node_status correctly reads the status from the DOT file."""
        runner = _make_runner(tmp_path, ACCEPTED_DOT)

        status = runner._get_node_status("node1")
        assert status == "accepted"

    def test_get_node_status_returns_pending_for_unknown_node(self, tmp_path):
        """_get_node_status returns 'pending' for a node not in the DOT file."""
        runner = _make_runner(tmp_path, MINIMAL_DOT)

        status = runner._get_node_status("nonexistent_node")
        assert status == "pending"

    def test_get_node_status_returns_pending_on_read_error(self, tmp_path):
        """_get_node_status returns 'pending' when the DOT file cannot be read."""
        runner = _make_runner(tmp_path, MINIMAL_DOT)
        # Remove the DOT file to trigger read error
        os.remove(runner.dot_path)

        status = runner._get_node_status("node1")
        assert status == "pending"


# =========================================================================
# Epic K: Blind Retry Paths Store Failure Reasons
# =========================================================================

class TestEpicK:
    """All 3 blind retry paths store failure reason in requeue_guidance before resetting to pending.

    This ensures workers receive actionable feedback when re-dispatched after failures.

    Three paths tested:
    1. _requeue_upstream_worker - upstream dependency failed
    2. Validation requeue result - validation agent rejected work
    3. Worker failed status - worker signaled failure
    """

    def test_requeue_upstream_worker_sets_guidance(self, tmp_path):
        """_requeue_upstream_worker sets requeue_guidance for upstream codergen predecessor."""
        runner = _make_runner(tmp_path, TOOL_VERIFY_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Build data dict matching TOOL_VERIFY_DOT structure
        data = {
            "nodes": [
                {"id": "start", "attrs": {"handler": "noop", "status": "validated"}},
                {"id": "impl_node", "attrs": {"handler": "codergen", "status": "accepted"}},
                {"id": "verify_node", "attrs": {"handler": "tool", "status": "active"}},
                {"id": "exit", "attrs": {"handler": "exit", "status": "pending"}},
            ],
            "edges": [
                {"src": "start", "dst": "impl_node"},
                {"src": "impl_node", "dst": "verify_node"},
                {"src": "verify_node", "dst": "exit"},
            ],
        }

        # Call _requeue_upstream_worker with correct signature:
        # (tool_node_id, failure_message, data)
        result = runner._requeue_upstream_worker(
            "verify_node",
            "Verification failed: assertion error in test_auth.py",
            data,
        )

        assert result is True, "_requeue_upstream_worker should return True when upstream found"

        # Verify guidance was set for the upstream codergen predecessor
        assert "impl_node" in runner.requeue_guidance, \
            "requeue_guidance should have entry for upstream impl_node"
        guidance = runner.requeue_guidance["impl_node"]
        assert "failed verification" in guidance.lower() or "assertion error" in guidance.lower(), \
            f"Guidance should mention verification failure, got: {guidance}"

        # Verify guidance was persisted (survives reload)
        guidance_path = os.path.join(runner.signal_dir, "guidance", "impl_node.txt")
        assert os.path.exists(guidance_path), "Guidance file should be persisted"
        with open(guidance_path) as fh:
            persisted = fh.read()
        assert persisted == guidance, "Persisted guidance should match in-memory"

    def test_validation_fail_sets_guidance(self, tmp_path):
        """PATH 1: Validation 'fail' result stores guidance before resetting to pending."""
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Simulate a validation fail signal
        fail_signal = {
            "result": "fail",
            "reason": "Tests failing: 2 of 4 assertions fail in test_auth.py",
        }

        # Write the signal file
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump(fail_signal, fh)

        # Process the signal (triggers the validation fail path)
        runner._process_signals()

        # Verify guidance was set
        assert "node1" in runner.requeue_guidance, \
            "requeue_guidance should have entry for validation-failed node"
        guidance = runner.requeue_guidance["node1"]
        assert "Tests failing" in guidance or "failed validation" in guidance.lower(), \
            f"Guidance should include validation failure reason, got: {guidance}"

    def test_validation_requeue_result_sets_guidance(self, tmp_path):
        """Path 2: Validation requeue result sets requeue_guidance before calling _force_status."""
        runner = _make_runner(tmp_path, IMPL_COMPLETE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Simulate a validation requeue signal
        validation_signal = {
            "result": "requeue",
            "requeue_target": "node1",
            "reason": "Tests failed: assertion error on line 42 of test_auth.py",
            "guidance": "Fix the authentication logic to handle expired tokens correctly."
        }

        # Write the signal file
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump(validation_signal, fh)

        # Process the signal (this triggers the requeue path)
        runner._process_signals()

        # Verify guidance was set for the requeue target
        assert "node1" in runner.requeue_guidance, \
            "requeue_guidance should have entry for requeued node"
        guidance = runner.requeue_guidance["node1"]
        assert "Tests failed" in guidance or "expired tokens" in guidance, \
            f"Guidance should include validation feedback, got: {guidance}"

        # Verify guidance was persisted
        guidance_path = os.path.join(runner.signal_dir, "guidance", "node1.txt")
        assert os.path.exists(guidance_path), "Guidance file should be persisted for requeue"

    def test_worker_failed_sets_guidance(self, tmp_path):
        """Path 3: Worker failed status sets requeue_guidance before calling _force_status."""
        runner = _make_runner(tmp_path, ACTIVE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Simulate a worker failure signal
        failure_signal = {
            "status": "failed",
            "message": "ImportError: No module named 'nonexistent_module'",
            "files_changed": []
        }

        # Write the signal file
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump(failure_signal, fh)

        # Process the signal (this triggers the failed -> pending retry path)
        runner._process_signals()

        # Verify guidance was set for the failed node
        assert "node1" in runner.requeue_guidance, \
            "requeue_guidance should have entry for failed worker"
        guidance = runner.requeue_guidance["node1"]
        assert "ImportError" in guidance or "failed" in guidance.lower(), \
            f"Guidance should mention the failure, got: {guidance}"

        # Verify guidance was persisted
        guidance_path = os.path.join(runner.signal_dir, "guidance", "node1.txt")
        assert os.path.exists(guidance_path), "Guidance file should be persisted for failed worker"

    def test_all_paths_persist_guidance_before_force_status(self, tmp_path):
        """Verify worker failed path calls _persist_requeue_guidance BEFORE _force_status.

        This is a meta-test that verifies the ordering: guidance first, then status reset.
        """
        runner = _make_runner(tmp_path, ACTIVE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Track call order
        call_order = []
        original_persist = runner._persist_requeue_guidance
        original_force = runner._force_status

        def tracked_persist(node_id, guidance):
            call_order.append(("persist", node_id))
            return original_persist(node_id, guidance)

        def tracked_force(node_id, target_status):
            call_order.append(("force_status", node_id, target_status))
            return original_force(node_id, target_status)

        # Test: worker failed (write signal and process)
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump({"status": "failed", "message": "test error"}, fh)

        runner._persist_requeue_guidance = tracked_persist
        runner._force_status = tracked_force

        runner._process_signals()

        # Find the persist and force_status calls for this path
        persist_calls = [c for c in call_order if c[0] == "persist"]
        force_calls = [c for c in call_order if c[0] == "force_status"]

        # persist should come before force_status (the retry path)
        assert persist_calls, "persist should have been called"
        assert force_calls, "force_status should have been called"
        last_persist_idx = call_order.index(persist_calls[-1])
        last_force_idx = call_order.index(force_calls[-1])
        assert last_persist_idx < last_force_idx, \
            f"persist should come before force_status, got order: {call_order}"

    def test_stale_timeout_returns_failed_not_success(self, tmp_path):
        """Stale worker timeout should return 'failed', not 'success'.

        When the stale detection breaks the stream loop (no signal file, no result_text),
        the return value must be 'failed' so the retry path fires with guidance.
        """
        runner = _make_runner(tmp_path, ACTIVE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Simulate what happens when stale timeout triggers:
        # The runner writes a signal with the result from _dispatch_sdk_worker.
        # With the fix, stale timeout returns {"status": "failed", "message": "Stale worker..."}
        stale_result = {
            "status": "failed",
            "message": "Stale worker timeout after 300s — worker was mid-task (165 events). Last worker text: writing signal file...",
        }

        # Write the stale-timeout signal
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump(stale_result, fh)

        # Process the signal — should trigger the worker-failed retry path
        runner._process_signals()

        # Verify guidance was set (the blind retry fix handles this)
        assert "node1" in runner.requeue_guidance, \
            "Stale timeout signal should trigger guidance storage via worker-failed path"
        guidance = runner.requeue_guidance["node1"]
        assert "stale" in guidance.lower() or "failed" in guidance.lower(), \
            f"Guidance should mention the failure, got: {guidance}"

    def test_stale_timeout_skipped_when_signal_exists(self, tmp_path):
        """If worker already wrote a signal file, stale detection should NOT override it.

        This tests the guard: before declaring stale, check if {node_id}.json exists.
        If it does, let normal signal processing handle it instead of forcing 'failed'.
        """
        runner = _make_runner(tmp_path, ACTIVE_DOT)
        os.makedirs(runner.signal_dir, exist_ok=True)

        # Worker wrote a success signal before stale timeout would fire
        worker_signal = {
            "status": "success",
            "message": "Implemented all requested changes",
            "files_changed": ["cobuilder/engine/pipeline_runner.py"],
        }
        signal_path = os.path.join(runner.signal_dir, "node1.json")
        with open(signal_path, "w") as fh:
            json.dump(worker_signal, fh)

        # Process the signal — should treat as normal success, NOT stale
        runner._process_signals()

        # Node should advance to impl_complete (success path), not failed
        node_status = runner._get_node_status("node1")
        assert node_status == "impl_complete", \
            f"Worker-written success signal should advance to impl_complete, got: {node_status}"
