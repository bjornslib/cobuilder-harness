"""Tests for signal file cleanup on pending transition (AC-5).

Tests the _cleanup_stale_signals function and apply_transition signal cleanup
functionality as required by:
  - AC-5: apply_transition() cleans signal files when new_status=pending
  - AC-5: Signal files matching node_id are moved from active to processed/
  - AC-5: Works with signals directory convention (.pipelines/pipelines/signals/{pipeline_id}/)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from cobuilder.engine.transition import apply_transition


def create_sample_dot(pipeline_id: str = "test-pipeline-001") -> str:
    """Create a sample DOT file with a pipeline_id."""
    return f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    node1 [
        shape=box
        handler="codergen"
        status="pending"
        fillcolor="lightyellow"
        style="filled"
    ];
}}
'''


def create_signals_structure(tmp_path: Path, pipeline_id: str) -> tuple[str, str]:
    """Create signals directory structure and return (signals_dir, processed_dir)."""
    signals_dir = tmp_path / "signals" / pipeline_id
    processed_dir = signals_dir / "processed"
    signals_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)
    return str(signals_dir), str(processed_dir)


class TestSignalCleanupHelper:
    """Tests for _cleanup_stale_signals helper function."""

    def test_cleanup_moves_signal_files_to_processed(self, tmp_path: Path) -> None:
        """Test that signal files for a node are moved to processed/ on pending transition."""
        pipeline_id = "test-001"
        signals_dir, processed_dir = create_signals_structure(tmp_path, pipeline_id)

        # Create test signal files
        signal1 = Path(signals_dir) / "20260101T120000Z-node1.json"
        signal2 = Path(signals_dir) / "node1-result.json"
        signal1.write_text(json.dumps({"status": "failed", "reason": "timeout"}))
        signal2.write_text(json.dumps({"status": "failed"}))

        # Create DOT file with node in 'failed' status
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    node1 [
        shape=box
        handler="codergen"
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}}
'''
        dot_file = str(tmp_path / "test.dot")
        Path(dot_file).write_text(dot_content)

        # Apply transition to pending (should cleanup signals)
        updated, _ = apply_transition(dot_content, "node1", "pending", dot_file=dot_file)

        # Verify signals were moved to processed/
        assert not signal1.exists(), f"Signal file should have been moved: {signal1}"
        assert not signal2.exists(), f"Signal file should have been moved: {signal2}"
        assert (Path(processed_dir) / signal1.name).exists(), "Signal should be in processed/"
        assert (Path(processed_dir) / signal2.name).exists(), "Signal should be in processed/"

    def test_cleanup_ignores_other_node_signals(self, tmp_path: Path) -> None:
        """Test that signals for other nodes are not moved."""
        pipeline_id = "test-002"
        signals_dir, processed_dir = create_signals_structure(tmp_path, pipeline_id)

        # Create signal files for node1 and node2
        node1_signal = Path(signals_dir) / "node1-result.json"
        node2_signal = Path(signals_dir) / "node2-result.json"
        node1_signal.write_text(json.dumps({"status": "failed"}))
        node2_signal.write_text(json.dumps({"status": "failed"}))

        # Create DOT file with both nodes in 'failed' status
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    node1 [
        shape=box
        handler="codergen"
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];

    node2 [
        shape=box
        handler="codergen"
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}}
'''
        dot_file = str(tmp_path / "test.dot")
        Path(dot_file).write_text(dot_content)

        # Transition node1 to pending
        apply_transition(dot_content, "node1", "pending", dot_file=dot_file)

        # node1 signal should be moved, node2 should remain
        assert not node1_signal.exists(), "node1 signal should be moved"
        assert node2_signal.exists(), "node2 signal should remain in active"
        assert (Path(processed_dir) / node1_signal.name).exists()

    def test_cleanup_skipped_for_non_pending_transitions(self, tmp_path: Path) -> None:
        """Test that signal cleanup only happens for pending transitions."""
        pipeline_id = "test-003"
        signals_dir, _ = create_signals_structure(tmp_path, pipeline_id)

        # Create signal file
        signal = Path(signals_dir) / "node1-result.json"
        signal.write_text(json.dumps({"status": "failed"}))

        # Create DOT file with node in 'active' status
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    node1 [
        shape=box
        handler="codergen"
        status="active"
        fillcolor="lightblue"
        style="filled"
    ];
}}
'''
        dot_file = str(tmp_path / "test.dot")
        Path(dot_file).write_text(dot_content)

        # Transition to 'impl_complete' (not pending) - should not cleanup signals
        apply_transition(dot_content, "node1", "impl_complete", dot_file=dot_file)

        # Signal should still be in active directory
        assert signal.exists(), "Signal should not be moved for non-pending transition"

    def test_cleanup_gracefully_handles_missing_signals_dir(self, tmp_path: Path) -> None:
        """Test that cleanup gracefully handles missing signals directory."""
        pipeline_id = "test-004"
        # Create DOT with node in 'failed' status
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    node1 [
        shape=box
        handler="codergen"
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}}
'''
        dot_file = str(tmp_path / "test.dot")
        Path(dot_file).write_text(dot_content)

        # Don't create signals directory
        # Should not raise, just silently return
        try:
            updated, log_msg = apply_transition(
                dot_content, "node1", "pending", dot_file=dot_file
            )
            assert updated is not None, "Should return updated DOT"
            assert "pending" in log_msg, "Should log the transition"
        except Exception as e:
            pytest.fail(f"Should not raise exception for missing signals dir: {e}")

    def test_cleanup_gracefully_handles_missing_pipeline_id(self, tmp_path: Path) -> None:
        """Test that cleanup gracefully handles DOT without pipeline_id."""
        # Create DOT without pipeline_id, but with node in 'failed' status
        dot_content = '''digraph pipeline {
    node1 [
        shape=box
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}
'''
        dot_file = str(tmp_path / "test.dot")
        Path(dot_file).write_text(dot_content)

        # Should not raise, just silently return
        try:
            updated, log_msg = apply_transition(dot_content, "node1", "pending", dot_file=dot_file)
            assert updated is not None
            assert "pending" in log_msg
        except Exception as e:
            pytest.fail(f"Should not raise exception for missing pipeline_id: {e}")

    def test_cleanup_creates_processed_dir_if_missing(self, tmp_path: Path) -> None:
        """Test that processed/ directory is created if it doesn't exist."""
        pipeline_id = "test-005"
        signals_dir = tmp_path / "signals" / pipeline_id
        signals_dir.mkdir(parents=True, exist_ok=True)
        # Don't create processed/ subdirectory

        # Create signal file
        signal = signals_dir / "node1-result.json"
        signal.write_text(json.dumps({"status": "failed"}))

        # Create DOT file with node in 'failed' status
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    node1 [
        shape=box
        handler="codergen"
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}}
'''
        dot_file = str(tmp_path / "test.dot")
        Path(dot_file).write_text(dot_content)

        # Transition to pending - should create processed/ and move signal
        apply_transition(dot_content, "node1", "pending", dot_file=dot_file)

        # Verify processed dir was created and signal moved
        processed_dir = signals_dir / "processed"
        assert processed_dir.exists(), "processed/ should be created"
        assert not signal.exists(), "Signal should be moved"
        assert (processed_dir / signal.name).exists(), "Signal should be in processed/"

    def test_no_cleanup_when_dot_file_not_provided(self, tmp_path: Path) -> None:
        """Test that cleanup is skipped when dot_file parameter is not provided."""
        pipeline_id = "test-006"
        signals_dir, _ = create_signals_structure(tmp_path, pipeline_id)

        # Create signal file
        signal = Path(signals_dir) / "node1-result.json"
        signal.write_text(json.dumps({"status": "failed"}))

        # Create DOT content with node in 'failed' status (without providing dot_file path)
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    node1 [
        shape=box
        handler="codergen"
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}}
'''

        # Transition without dot_file - signals should not be cleaned up
        updated, _ = apply_transition(dot_content, "node1", "pending")

        # Signal should remain (since dot_file was not provided)
        assert signal.exists(), "Signal should not be moved when dot_file is not provided"


class TestApplyTransitionIntegration:
    """Integration tests for apply_transition with signal cleanup."""

    def test_full_workflow_with_signal_cleanup(self, tmp_path: Path) -> None:
        """Test a complete workflow: transition node through states with signal cleanup."""
        pipeline_id = "integration-001"
        signals_dir, processed_dir = create_signals_structure(tmp_path, pipeline_id)

        # Create initial DOT
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="{pipeline_id}"]

    impl [
        shape=box
        handler="codergen"
        status="pending"
        fillcolor="lightyellow"
        style="filled"
    ];
}}
'''
        dot_file = str(tmp_path / "pipeline.dot")
        Path(dot_file).write_text(dot_content)

        # Simulate: pending -> active
        dot_content, _ = apply_transition(dot_content, "impl", "active", dot_file=dot_file)
        assert 'status="active"' in dot_content
        assert 'fillcolor="lightblue"' in dot_content

        # Add signal file (simulating worker failure)
        signal = Path(signals_dir) / "impl-result.json"
        signal.write_text(json.dumps({"status": "failed", "error": "timeout"}))
        assert signal.exists()

        # Simulate: active -> impl_complete -> failed
        dot_content, _ = apply_transition(dot_content, "impl", "impl_complete", dot_file=dot_file)
        dot_content, _ = apply_transition(dot_content, "impl", "failed", dot_file=dot_file)

        # Simulate: failed -> pending (with signal cleanup)
        dot_content, _ = apply_transition(dot_content, "impl", "pending", dot_file=dot_file)

        # Verify:
        # 1. Node is back to pending
        assert 'status="pending"' in dot_content
        assert 'fillcolor="lightyellow"' in dot_content

        # 2. Old signal was cleaned up
        assert not signal.exists(), "Old signal should be cleaned up"
        assert (Path(processed_dir) / signal.name).exists(), "Signal should be in processed/"

    def test_status_color_updates_with_pending(self, tmp_path: Path) -> None:
        """Test that fillcolor is correctly updated when transitioning to pending."""
        dot_content = f'''digraph pipeline {{
    graph [pipeline_id="test-color"]

    node1 [
        shape=box
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}}
'''
        dot_file = str(tmp_path / "test.dot")
        Path(dot_file).write_text(dot_content)

        # Create signals dir (so cleanup can proceed)
        signals_dir = tmp_path / "signals" / "test-color"
        signals_dir.mkdir(parents=True, exist_ok=True)

        # Transition failed -> pending
        updated, _ = apply_transition(dot_content, "node1", "pending", dot_file=dot_file)

        # Verify both status and color are updated
        assert 'status="pending"' in updated
        assert 'fillcolor="lightyellow"' in updated


class TestExistingTransitionTests:
    """Ensure existing transition tests still pass (regression tests)."""

    def test_basic_transition_without_signal_file_param(self) -> None:
        """Test that apply_transition works when dot_file is not provided."""
        dot_content = '''digraph test {
    node1 [
        shape=box
        status="pending"
        fillcolor="lightyellow"
        style="filled"
    ];
}
'''
        updated, log_msg = apply_transition(dot_content, "node1", "active")
        assert 'status="active"' in updated
        assert 'fillcolor="lightblue"' in updated
        assert "pending -> active" in log_msg

    def test_finalize_gate_check(self) -> None:
        """Test that finalize gate checks still work."""
        dot_content = '''digraph test {
    hex1 [shape=hexagon status="pending"];
    impl [shape=box status="impl_complete"];
    finish [shape=Msquare status="pending"];
}
'''
        # Should not be able to activate finalize with pending hexagon
        with pytest.raises(ValueError, match="Finalize gate blocked"):
            apply_transition(dot_content, "finish", "active")

    def test_invalid_transitions_still_rejected(self) -> None:
        """Test that invalid transitions are still rejected."""
        dot_content = '''digraph test {
    node1 [shape=box status="accepted"];
}
'''
        # accepted is terminal, should not be able to transition from it
        with pytest.raises(ValueError, match="Illegal transition"):
            apply_transition(dot_content, "node1", "active")
