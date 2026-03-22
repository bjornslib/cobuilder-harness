"""Unit tests for post-validation hook helpers in cobuilder/pipeline/transition.py.

Tests cover E4-T1 (F4.4):
    1. _extract_node_scope — file_path, folder_path, no attrs
    2. _extract_graph_repo_name — present and absent
    3. _infer_project_root — finds .repomap/ walking up
    4. _fire_post_validated_hook — calls scoped_refresh, handles failures non-fatally
    5. _cmd_transition integration — hook fires on 'validated', not on other statuses
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cobuilder.pipeline.transition import (
    _extract_graph_repo_name,
    _extract_node_scope,
    _fire_post_validated_hook,
    _infer_project_root,
)


# ---------------------------------------------------------------------------
# Minimal DOT fixture helpers
# ---------------------------------------------------------------------------

def _dot_with_file_path(node_id: str, file_path: str, repo_name: str = "myrepo") -> str:
    return textwrap.dedent(f"""\
        digraph pipeline {{
            graph [repo_name="{repo_name}" label="test"];
            {node_id} [
                handler="codergen"
                file_path="{file_path}"
                status="active"
                fillcolor="lightblue"
                style="filled"
            ];
        }}
    """)


def _dot_with_folder_path(node_id: str, folder_path: str, repo_name: str = "myrepo") -> str:
    return textwrap.dedent(f"""\
        digraph pipeline {{
            graph [repo_name="{repo_name}" label="test"];
            {node_id} [
                handler="codergen"
                folder_path="{folder_path}"
                status="active"
                fillcolor="lightblue"
                style="filled"
            ];
        }}
    """)


def _dot_without_paths(node_id: str, repo_name: str = "myrepo") -> str:
    return textwrap.dedent(f"""\
        digraph pipeline {{
            graph [repo_name="{repo_name}" label="test"];
            {node_id} [
                handler="codergen"
                status="active"
                fillcolor="lightblue"
                style="filled"
            ];
        }}
    """)


def _dot_without_repo_name(node_id: str) -> str:
    return textwrap.dedent(f"""\
        digraph pipeline {{
            graph [label="test"];
            {node_id} [
                handler="codergen"
                file_path="cobuilder/bridge.py"
                status="active"
                fillcolor="lightblue"
                style="filled"
            ];
        }}
    """)


# ---------------------------------------------------------------------------
# TestExtractNodeScope
# ---------------------------------------------------------------------------


class TestExtractNodeScope:
    def test_file_path_single(self):
        dot = _dot_with_file_path("N1", "cobuilder/bridge.py")
        result = _extract_node_scope(dot, "N1")
        assert result == ["cobuilder/bridge.py"]

    def test_file_path_multiple_comma_separated(self):
        dot = _dot_with_file_path("N1", "cobuilder/bridge.py,cobuilder/cli.py")
        result = _extract_node_scope(dot, "N1")
        assert result == ["cobuilder/bridge.py", "cobuilder/cli.py"]

    def test_file_path_with_spaces_around_comma(self):
        dot = _dot_with_file_path("N1", "cobuilder/bridge.py , cobuilder/cli.py")
        result = _extract_node_scope(dot, "N1")
        assert result == ["cobuilder/bridge.py", "cobuilder/cli.py"]

    def test_folder_path(self):
        dot = _dot_with_folder_path("N1", "cobuilder/")
        result = _extract_node_scope(dot, "N1")
        assert result == ["cobuilder/"]

    def test_no_file_path_or_folder_path_returns_empty(self):
        dot = _dot_without_paths("N1")
        result = _extract_node_scope(dot, "N1")
        assert result == []

    def test_unknown_node_returns_empty(self):
        dot = _dot_with_file_path("N1", "cobuilder/bridge.py")
        result = _extract_node_scope(dot, "DOES_NOT_EXIST")
        assert result == []


# ---------------------------------------------------------------------------
# TestExtractGraphRepoName
# ---------------------------------------------------------------------------


class TestExtractGraphRepoName:
    def test_repo_name_present(self):
        dot = _dot_with_file_path("N1", "cobuilder/bridge.py", repo_name="my-project")
        result = _extract_graph_repo_name(dot)
        assert result == "my-project"

    def test_repo_name_default(self):
        dot = _dot_with_file_path("N1", "cobuilder/bridge.py", repo_name="myrepo")
        result = _extract_graph_repo_name(dot)
        assert result == "myrepo"

    def test_repo_name_absent(self):
        dot = _dot_without_repo_name("N1")
        result = _extract_graph_repo_name(dot)
        assert result is None

    def test_no_graph_block_returns_none(self):
        dot = "digraph pipeline { N1 [status=\"active\"]; }"
        result = _extract_graph_repo_name(dot)
        assert result is None


# ---------------------------------------------------------------------------
# TestInferProjectRoot
# ---------------------------------------------------------------------------


class TestInferProjectRoot:
    def test_finds_repomap_in_parent(self, tmp_path: Path):
        # Create structure: tmp_path/.repomap/  and  tmp_path/sub/pipeline/file.dot
        repomap = tmp_path / ".repomap"
        repomap.mkdir()
        pipeline_dir = tmp_path / "sub" / "pipeline"
        pipeline_dir.mkdir(parents=True)
        dot_file = pipeline_dir / "test.dot"
        dot_file.write_text("digraph {}")

        result = _infer_project_root(str(dot_file))
        assert result is not None
        assert result.resolve() == tmp_path.resolve()

    def test_finds_repomap_in_same_dir(self, tmp_path: Path):
        repomap = tmp_path / ".repomap"
        repomap.mkdir()
        dot_file = tmp_path / "test.dot"
        dot_file.write_text("digraph {}")

        result = _infer_project_root(str(dot_file))
        assert result is not None
        assert result.resolve() == tmp_path.resolve()

    def test_returns_none_when_no_repomap(self, tmp_path: Path):
        # No .repomap/ anywhere under tmp_path
        pipeline_dir = tmp_path / "pipeline"
        pipeline_dir.mkdir()
        dot_file = pipeline_dir / "test.dot"
        dot_file.write_text("digraph {}")

        result = _infer_project_root(str(dot_file))
        # Result is None because we won't find .repomap/ within 8 levels
        # (tmp_path is shallow, but no .repomap exists)
        assert result is None


# ---------------------------------------------------------------------------
# TestFirePostValidatedHook
# ---------------------------------------------------------------------------


class TestFirePostValidatedHook:
    def _make_dot_file(self, tmp_path: Path, content: str) -> Path:
        dot_file = tmp_path / "pipeline.dot"
        dot_file.write_text(content)
        return dot_file

    def test_calls_scoped_refresh_with_correct_args(self, tmp_path: Path, monkeypatch):
        """Hook should call scoped_refresh with repo_name, scope, and project_root."""
        # Create .repomap/ so _infer_project_root succeeds
        (tmp_path / ".repomap").mkdir()
        dot_file = self._make_dot_file(tmp_path, _dot_with_file_path("N1", "cobuilder/bridge.py", repo_name="myrepo"))

        mock_refresh = MagicMock(return_value={"skipped": False, "refreshed_nodes": 5, "duration_seconds": 0.1, "baseline_hash": "abc"})
        monkeypatch.setattr("cobuilder.bridge.scoped_refresh", mock_refresh)

        result = _fire_post_validated_hook(
            dot_file=str(dot_file),
            node_id="N1",
            updated_content=dot_file.read_text(),
        )

        assert result is True
        mock_refresh.assert_called_once()
        call_args = mock_refresh.call_args
        assert call_args[0][0] == "myrepo"
        assert call_args[0][1] == ["cobuilder/bridge.py"]
        assert "project_root" in call_args[1]

    def test_explicit_project_root_used_directly(self, tmp_path: Path, monkeypatch):
        """When project_root is supplied explicitly, _infer_project_root is not called."""
        dot_file = self._make_dot_file(tmp_path, _dot_with_file_path("N1", "cobuilder/bridge.py", repo_name="myrepo"))

        mock_refresh = MagicMock(return_value={"skipped": False, "refreshed_nodes": 0, "duration_seconds": 0.0, "baseline_hash": ""})
        monkeypatch.setattr("cobuilder.bridge.scoped_refresh", mock_refresh)

        result = _fire_post_validated_hook(
            dot_file=str(dot_file),
            node_id="N1",
            updated_content=dot_file.read_text(),
            project_root=str(tmp_path),
        )

        assert result is True
        mock_refresh.assert_called_once()
        assert mock_refresh.call_args[1]["project_root"] == Path(str(tmp_path))

    def test_no_file_path_returns_false(self, tmp_path: Path):
        """Node without file_path or folder_path should skip and return False."""
        dot_file = self._make_dot_file(tmp_path, _dot_without_paths("N1"))

        result = _fire_post_validated_hook(
            dot_file=str(dot_file),
            node_id="N1",
            updated_content=dot_file.read_text(),
            project_root=str(tmp_path),
        )

        assert result is False

    def test_no_repo_name_returns_false(self, tmp_path: Path):
        """DOT without repo_name graph attribute should skip and return False."""
        dot_file = self._make_dot_file(tmp_path, _dot_without_repo_name("N1"))

        result = _fire_post_validated_hook(
            dot_file=str(dot_file),
            node_id="N1",
            updated_content=dot_file.read_text(),
            project_root=str(tmp_path),
        )

        assert result is False

    def test_no_project_root_inferred_none_returns_false(self, tmp_path: Path):
        """When .repomap/ cannot be found and no project_root given, returns False."""
        # No .repomap/ in tmp_path or parents (relies on tmp_path being isolated)
        dot_file = self._make_dot_file(tmp_path, _dot_with_file_path("N1", "cobuilder/bridge.py", repo_name="myrepo"))

        # We need a path where _infer_project_root returns None.
        # The tmp_path won't have .repomap unless we create it.
        result = _fire_post_validated_hook(
            dot_file=str(dot_file),
            node_id="N1",
            updated_content=dot_file.read_text(),
            # No project_root — must infer
        )

        # Should return False since no .repomap found
        assert result is False

    def test_bridge_raises_returns_false(self, tmp_path: Path, monkeypatch):
        """When scoped_refresh raises any exception, hook returns False (never raises)."""
        (tmp_path / ".repomap").mkdir()
        dot_file = self._make_dot_file(tmp_path, _dot_with_file_path("N1", "cobuilder/bridge.py", repo_name="myrepo"))

        def _boom(*args, **kwargs):
            raise RuntimeError("scoped_refresh exploded")

        monkeypatch.setattr("cobuilder.bridge.scoped_refresh", _boom)

        result = _fire_post_validated_hook(
            dot_file=str(dot_file),
            node_id="N1",
            updated_content=dot_file.read_text(),
        )

        assert result is False

    def test_import_error_returns_false(self, tmp_path: Path, monkeypatch):
        """ImportError during bridge import is caught — hook returns False."""
        (tmp_path / ".repomap").mkdir()
        dot_file = self._make_dot_file(tmp_path, _dot_with_file_path("N1", "cobuilder/bridge.py", repo_name="myrepo"))

        # Patch cobuilder.bridge to trigger ImportError when accessed
        import sys
        original = sys.modules.get("cobuilder.bridge")
        sys.modules["cobuilder.bridge"] = None  # type: ignore[assignment]

        try:
            result = _fire_post_validated_hook(
                dot_file=str(dot_file),
                node_id="N1",
                updated_content=dot_file.read_text(),
            )
        finally:
            if original is None:
                sys.modules.pop("cobuilder.bridge", None)
            else:
                sys.modules["cobuilder.bridge"] = original

        assert result is False


# ---------------------------------------------------------------------------
# TestCmdTransitionHookIntegration
# ---------------------------------------------------------------------------


import sys as _sys
import cobuilder.pipeline.parser as _pipeline_parser


def _install_bare_parser_shim():
    """Install 'parser' in sys.modules so bare `from parser import parse_dot` works.

    The transition.py module uses bare `from parser import parse_dot` in its
    inner functions (a pattern designed for standalone script execution).
    When imported as a module during tests, Python 3 does NOT find 'parser'
    on the path unless we provide this shim.

    This shim is installed at import time for the integration test class so
    the module-level import of cobuilder.pipeline.transition resolves correctly.
    """
    if "parser" not in _sys.modules:
        _sys.modules["parser"] = _pipeline_parser  # type: ignore[assignment]


_install_bare_parser_shim()


class TestCmdTransitionHookIntegration:
    """Integration tests verifying the hook is wired correctly in _cmd_transition."""

    def _build_impl_complete_dot(self, tmp_path: Path, repo_name: str = "myrepo") -> Path:
        """Create a minimal DOT file with a node at impl_complete status."""
        content = textwrap.dedent(f"""\
            digraph pipeline {{
                graph [repo_name="{repo_name}" label="test"];
                N1 [
                    handler="codergen"
                    file_path="cobuilder/bridge.py"
                    status="impl_complete"
                    fillcolor="lightsalmon"
                    style="filled"
                ];
            }}
        """)
        dot_file = tmp_path / "pipeline.dot"
        dot_file.write_text(content)
        return dot_file

    def test_hook_fires_on_validated_transition(self, tmp_path: Path, monkeypatch):
        """_cmd_transition should call _fire_post_validated_hook when new_status='validated'."""
        (tmp_path / ".repomap").mkdir()
        dot_file = self._build_impl_complete_dot(tmp_path)

        hook_calls = []

        def _mock_hook(dot_file, node_id, updated_content, **kwargs):
            hook_calls.append((dot_file, node_id))
            return True

        monkeypatch.setattr(
            "cobuilder.pipeline.transition._fire_post_validated_hook",
            _mock_hook,
        )

        import argparse
        from cobuilder.pipeline.transition import _cmd_transition

        args = argparse.Namespace(
            file=str(dot_file),
            node_id="N1",
            new_status="validated",
            dry_run=False,
            output="text",
            session_id="",
        )
        _cmd_transition(args, dot_file.read_text())

        assert len(hook_calls) == 1
        assert hook_calls[0][1] == "N1"

    def test_hook_does_not_fire_on_non_validated_transition(self, tmp_path: Path, monkeypatch):
        """_cmd_transition should NOT call _fire_post_validated_hook for non-validated statuses."""
        dot_content = textwrap.dedent("""\
            digraph pipeline {
                graph [label="test"];
                N1 [
                    handler="codergen"
                    file_path="cobuilder/bridge.py"
                    status="active"
                    fillcolor="lightblue"
                    style="filled"
                ];
            }
        """)
        dot_file = tmp_path / "pipeline.dot"
        dot_file.write_text(dot_content)

        hook_calls = []

        def _mock_hook(dot_file, node_id, updated_content, **kwargs):
            hook_calls.append((dot_file, node_id))
            return True

        monkeypatch.setattr(
            "cobuilder.pipeline.transition._fire_post_validated_hook",
            _mock_hook,
        )

        import argparse
        from cobuilder.pipeline.transition import _cmd_transition

        args = argparse.Namespace(
            file=str(dot_file),
            node_id="N1",
            new_status="impl_complete",
            dry_run=False,
            output="text",
            session_id="",
        )
        _cmd_transition(args, dot_file.read_text())

        assert len(hook_calls) == 0

    def test_hook_not_fired_on_dry_run(self, tmp_path: Path, monkeypatch):
        """In dry-run mode the hook must NOT fire (no file write, no side effects)."""
        (tmp_path / ".repomap").mkdir()
        dot_file = self._build_impl_complete_dot(tmp_path)

        hook_calls = []

        def _mock_hook(dot_file, node_id, updated_content, **kwargs):
            hook_calls.append((dot_file, node_id))
            return True

        monkeypatch.setattr(
            "cobuilder.pipeline.transition._fire_post_validated_hook",
            _mock_hook,
        )

        import argparse
        from cobuilder.pipeline.transition import _cmd_transition

        args = argparse.Namespace(
            file=str(dot_file),
            node_id="N1",
            new_status="validated",
            dry_run=True,
            output="text",
            session_id="",
        )
        _cmd_transition(args, dot_file.read_text())

        assert len(hook_calls) == 0
