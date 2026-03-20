"""Tests for _create_path_guard module-level function.

This verifies that _create_path_guard is a module-level function
and can be imported directly (not just as a method).
"""

import os
import tempfile
import pytest

from cobuilder.engine.pipeline_runner import _create_path_guard


class TestPathGuard:
    """Tests for _create_path_guard module-level function."""

    def test_create_path_guard_returns_dict(self):
        """_create_path_guard returns a dictionary with required keys."""
        guard = _create_path_guard("/tmp/target", "/tmp/signals")

        assert isinstance(guard, dict)
        assert "cwd" in guard
        assert "permission_mode" in guard
        assert "env" in guard

    def test_create_path_guard_cwd_is_target_dir(self):
        """The 'cwd' in path guard matches the target_dir."""
        target = "/tmp/test_target"
        guard = _create_path_guard(target, "/tmp/signals")

        assert guard["cwd"] == target

    def test_create_path_guard_permission_mode(self):
        """The permission_mode is set to bypassPermissions."""
        guard = _create_path_guard("/tmp/target", "/tmp/signals")

        assert guard["permission_mode"] == "bypassPermissions"

    def test_create_path_guard_env_contains_signal_dir(self):
        """The env dict contains PIPELINE_SIGNAL_DIR."""
        signal_dir = "/tmp/test_signals"
        guard = _create_path_guard("/tmp/target", signal_dir)

        assert "PIPELINE_SIGNAL_DIR" in guard["env"]
        assert guard["env"]["PIPELINE_SIGNAL_DIR"] == signal_dir

    def test_create_path_guard_env_contains_target_dir(self):
        """The env dict contains PROJECT_TARGET_DIR."""
        target = "/tmp/test_target"
        guard = _create_path_guard(target, "/tmp/signals")

        assert "PROJECT_TARGET_DIR" in guard["env"]
        assert guard["env"]["PROJECT_TARGET_DIR"] == target

    def test_create_path_guard_removes_claudecode_env(self):
        """The env dict excludes CLAUDECODE variable."""
        # Set CLAUDECODE for this test
        os.environ["CLAUDECODE"] = "test_value"
        try:
            guard = _create_path_guard("/tmp/target", "/tmp/signals")
            assert "CLAUDECODE" not in guard["env"]
        finally:
            del os.environ["CLAUDECODE"]

    def test_create_path_guard_preserves_other_env_vars(self):
        """The env dict preserves PATH and other environment variables."""
        guard = _create_path_guard("/tmp/target", "/tmp/signals")

        # PATH should be preserved from os.environ
        if "PATH" in os.environ:
            assert "PATH" in guard["env"]

    def test_create_path_guard_with_absolute_paths(self):
        """_create_path_guard works with absolute paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = os.path.join(tmpdir, "target")
            signal_dir = os.path.join(tmpdir, "signals")
            os.makedirs(target_dir)
            os.makedirs(signal_dir)

            guard = _create_path_guard(target_dir, signal_dir)

            assert guard["cwd"] == target_dir
            assert guard["env"]["PIPELINE_SIGNAL_DIR"] == signal_dir
            assert guard["env"]["PROJECT_TARGET_DIR"] == target_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
