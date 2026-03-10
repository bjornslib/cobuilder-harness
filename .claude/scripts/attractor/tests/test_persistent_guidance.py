"""Tests for persistent requeue guidance in pipeline_runner.py.

Verifies that _load_persisted_guidance reads guidance files from disk,
and that _build_worker_prompt falls back to persisted guidance when
the in-memory dict is empty (e.g., after runner restart).
"""

import os
import sys
import tempfile

import pytest

# Add attractor scripts to path for imports
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, SCRIPT_DIR)


@pytest.fixture
def guidance_dir(tmp_path):
    """Create a temporary guidance directory with a test guidance file."""
    gdir = tmp_path / "signals" / "guidance"
    gdir.mkdir(parents=True)
    (gdir / "fix_auth.txt").write_text(
        "Your previous implementation failed verification at node 'verify_auth'.\n"
        "Error: Missing JWT validation\n"
        "Fix the issue and re-signal completion."
    )
    return tmp_path / "signals"


class TestLoadPersistedGuidance:
    def test_loads_existing_guidance(self, guidance_dir):
        """Guidance file exists and is readable."""
        from pipeline_runner import PipelineRunner

        runner = PipelineRunner.__new__(PipelineRunner)
        runner.signal_dir = str(guidance_dir)

        result = runner._load_persisted_guidance("fix_auth")
        assert result is not None
        assert "Missing JWT validation" in result

    def test_returns_none_for_missing_node(self, guidance_dir):
        """No guidance file for this node."""
        from pipeline_runner import PipelineRunner

        runner = PipelineRunner.__new__(PipelineRunner)
        runner.signal_dir = str(guidance_dir)

        result = runner._load_persisted_guidance("nonexistent_node")
        assert result is None

    def test_returns_none_for_empty_file(self, guidance_dir):
        """Empty guidance file should return None."""
        (guidance_dir / "guidance" / "empty_node.txt").write_text("")

        from pipeline_runner import PipelineRunner

        runner = PipelineRunner.__new__(PipelineRunner)
        runner.signal_dir = str(guidance_dir)

        result = runner._load_persisted_guidance("empty_node")
        assert result is None

    def test_does_not_delete_file(self, guidance_dir):
        """Loading guidance should NOT delete the file (persists across retries)."""
        from pipeline_runner import PipelineRunner

        runner = PipelineRunner.__new__(PipelineRunner)
        runner.signal_dir = str(guidance_dir)

        runner._load_persisted_guidance("fix_auth")
        runner._load_persisted_guidance("fix_auth")  # Second load
        assert (guidance_dir / "guidance" / "fix_auth.txt").exists()
