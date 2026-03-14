"""Tests for cleanup_orchestrator() in spawn_orchestrator.py (F4.5).

Covers:
    TestCleanupOrchestrator — cleanup_orchestrator() with various subprocess and
                              bridge.scoped_refresh outcomes.
"""

from __future__ import annotations

import subprocess
import sys
import os
import unittest
from unittest.mock import MagicMock, patch, call

# Add the engine package root so spawn_orchestrator is importable.
_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    ".claude",
    "scripts",
    "engine",
)
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from spawn_orchestrator import cleanup_orchestrator


class TestCleanupOrchestrator(unittest.TestCase):
    """Tests for cleanup_orchestrator() — non-fatal RepoMap refresh after session."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_git_result(self, filenames: list[str]) -> MagicMock:
        """Build a mock subprocess.CompletedProcess whose stdout lists filenames."""
        mock = MagicMock()
        mock.stdout = "\n".join(filenames) + ("\n" if filenames else "")
        mock.returncode = 0
        return mock

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_cleanup_calls_scoped_refresh_with_changed_files(self, tmp_path=None) -> None:
        """scoped_refresh is called with the exact file list returned by git diff."""
        if tmp_path is None:
            import tempfile
            tmp_path = tempfile.mkdtemp()

        changed = ["src/auth.py", "src/api.py", "tests/test_auth.py"]
        git_result = self._make_git_result(changed)

        mock_refresh = MagicMock(return_value={"refreshed_nodes": 3, "duration_seconds": 1.5})

        with patch("spawn_orchestrator.subprocess.run", return_value=git_result), \
             patch.dict("sys.modules", {"cobuilder.bridge": MagicMock(scoped_refresh=mock_refresh)}):
            result = cleanup_orchestrator(
                session_name="orch-auth",
                repo_name="myrepo",
                work_dir=str(tmp_path),
            )

        mock_refresh.assert_called_once()
        call_kwargs = mock_refresh.call_args
        # scope must contain all three changed files
        scope_arg = call_kwargs[1].get("scope") or call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["scope"]
        self.assertEqual(sorted(scope_arg), sorted(changed))
        self.assertEqual(result["changed_files"], changed)
        self.assertEqual(result["refreshed_nodes"], 3)

    # ------------------------------------------------------------------
    # git diff failure path
    # ------------------------------------------------------------------

    def test_cleanup_git_diff_fails_returns_empty(self) -> None:
        """When git diff raises SubprocessError, return empty result without raising."""
        with patch(
            "spawn_orchestrator.subprocess.run",
            side_effect=subprocess.SubprocessError("git not found"),
        ):
            result = cleanup_orchestrator(
                session_name="orch-auth",
                repo_name="myrepo",
                work_dir="/tmp/fake",
            )

        self.assertEqual(result["changed_files"], [])
        self.assertEqual(result["refreshed_nodes"], 0)
        # Must not raise — result must be a dict
        self.assertIsInstance(result, dict)

    def test_cleanup_git_diff_subprocess_error_no_exception_propagates(self) -> None:
        """SubprocessError must be swallowed — cleanup_orchestrator must not raise."""
        try:
            with patch(
                "spawn_orchestrator.subprocess.run",
                side_effect=subprocess.SubprocessError("timeout"),
            ):
                cleanup_orchestrator(
                    session_name="orch-timeout",
                    repo_name="repo",
                    work_dir="/tmp",
                )
        except subprocess.SubprocessError:
            self.fail("cleanup_orchestrator raised SubprocessError — it must be non-fatal")

    # ------------------------------------------------------------------
    # scoped_refresh failure path
    # ------------------------------------------------------------------

    def test_cleanup_scoped_refresh_raises_returns_error_dict(self) -> None:
        """When scoped_refresh raises, return a dict with 'error' key instead of raising."""
        changed = ["src/main.py", "src/db.py", "src/api.py"]
        git_result = self._make_git_result(changed)

        mock_bridge = MagicMock()
        mock_bridge.scoped_refresh.side_effect = RuntimeError("baseline not initialised")

        with patch("spawn_orchestrator.subprocess.run", return_value=git_result), \
             patch.dict("sys.modules", {"cobuilder.bridge": mock_bridge}):
            result = cleanup_orchestrator(
                session_name="orch-db",
                repo_name="myrepo",
                work_dir="/tmp/fake",
            )

        self.assertIn("error", result, "Expected 'error' key in result when scoped_refresh raises")
        self.assertIn("baseline not initialised", result["error"])
        self.assertEqual(result["changed_files"], changed)
        self.assertEqual(result["refreshed_nodes"], 0)

    def test_cleanup_scoped_refresh_raises_no_exception_propagates(self) -> None:
        """RuntimeError from scoped_refresh must never propagate out of cleanup_orchestrator."""
        changed = ["src/main.py"]
        git_result = self._make_git_result(changed)

        mock_bridge = MagicMock()
        mock_bridge.scoped_refresh.side_effect = RuntimeError("crash")

        try:
            with patch("spawn_orchestrator.subprocess.run", return_value=git_result), \
                 patch.dict("sys.modules", {"cobuilder.bridge": mock_bridge}):
                cleanup_orchestrator(
                    session_name="orch-crash",
                    repo_name="repo",
                    work_dir="/tmp",
                )
        except RuntimeError:
            self.fail("cleanup_orchestrator raised RuntimeError — it must be non-fatal")

    # ------------------------------------------------------------------
    # No changed files path
    # ------------------------------------------------------------------

    def test_cleanup_no_changed_files_returns_early(self) -> None:
        """When git diff returns empty output, return early without calling scoped_refresh."""
        git_result = self._make_git_result([])

        mock_bridge = MagicMock()

        with patch("spawn_orchestrator.subprocess.run", return_value=git_result), \
             patch.dict("sys.modules", {"cobuilder.bridge": mock_bridge}):
            result = cleanup_orchestrator(
                session_name="orch-noop",
                repo_name="myrepo",
                work_dir="/tmp/fake",
            )

        mock_bridge.scoped_refresh.assert_not_called()
        self.assertEqual(result["changed_files"], [])
        self.assertEqual(result["refreshed_nodes"], 0)
        self.assertIn("duration_seconds", result)

    def test_cleanup_no_changed_files_refreshed_nodes_zero(self) -> None:
        """refreshed_nodes must be 0 when there are no changed files."""
        git_result = self._make_git_result([])

        with patch("spawn_orchestrator.subprocess.run", return_value=git_result):
            result = cleanup_orchestrator(
                session_name="orch-zero",
                repo_name="repo",
                work_dir="/tmp",
            )

        self.assertEqual(result["refreshed_nodes"], 0)

    # ------------------------------------------------------------------
    # Return shape
    # ------------------------------------------------------------------

    def test_cleanup_result_contains_required_keys_on_success(self) -> None:
        """Successful result must contain changed_files, refreshed_nodes, duration_seconds."""
        changed = ["src/x.py"]
        git_result = self._make_git_result(changed)

        mock_refresh = MagicMock(return_value={"refreshed_nodes": 1, "duration_seconds": 0.5})

        with patch("spawn_orchestrator.subprocess.run", return_value=git_result), \
             patch.dict("sys.modules", {"cobuilder.bridge": MagicMock(scoped_refresh=mock_refresh)}):
            result = cleanup_orchestrator(
                session_name="orch-ok",
                repo_name="repo",
                work_dir="/tmp",
            )

        self.assertIn("changed_files", result)
        self.assertIn("refreshed_nodes", result)

    def test_cleanup_passes_repo_name_to_scoped_refresh(self) -> None:
        """scoped_refresh must receive the correct repo name."""
        changed = ["src/x.py"]
        git_result = self._make_git_result(changed)

        mock_refresh = MagicMock(return_value={"refreshed_nodes": 1, "duration_seconds": 0.2})

        with patch("spawn_orchestrator.subprocess.run", return_value=git_result), \
             patch.dict("sys.modules", {"cobuilder.bridge": MagicMock(scoped_refresh=mock_refresh)}):
            cleanup_orchestrator(
                session_name="orch-ok",
                repo_name="special-repo",
                work_dir="/tmp",
            )

        call_kwargs = mock_refresh.call_args
        name_arg = (
            call_kwargs.kwargs.get("name")
            or (call_kwargs.args[0] if call_kwargs.args else None)
        )
        self.assertEqual(name_arg, "special-repo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
