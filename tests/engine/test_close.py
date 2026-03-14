"""Tests for cobuilder.engine.handlers.close — CloseHandler."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cobuilder.engine.context import PipelineContext
from cobuilder.engine.graph import Node
from cobuilder.engine.handlers.base import HandlerRequest
from cobuilder.engine.handlers.close import CloseHandler
from cobuilder.engine.outcome import OutcomeStatus


def _make_request(
    node_id: str = "close_node",
    attrs: dict | None = None,
    run_dir: str = "",
    context_data: dict | None = None,
) -> HandlerRequest:
    """Create a HandlerRequest for testing."""
    if attrs is None:
        attrs = {}
    node = Node(
        id=node_id,
        shape="octagon",
        label="Close Node",
        attrs={"handler": "close", **attrs},
    )
    ctx = PipelineContext(initial=context_data or {})
    return HandlerRequest(
        node=node,
        context=ctx,
        run_dir=run_dir,
    )


class TestCloseHandlerHelpers:
    """Tests for CloseHandler private helper methods."""

    def test_is_git_repo_true(self, tmp_path: Path) -> None:
        """Test _is_git_repo returns True when .git exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        handler = CloseHandler()
        assert handler._is_git_repo(tmp_path) is True

    def test_is_git_repo_false(self, tmp_path: Path) -> None:
        """Test _is_git_repo returns False when .git does not exist."""
        handler = CloseHandler()
        assert handler._is_git_repo(tmp_path) is False

    def test_is_gh_available_true(self) -> None:
        """Test _is_gh_available returns True when gh is found."""
        handler = CloseHandler()
        with patch("shutil.which", return_value="/usr/bin/gh"):
            assert handler._is_gh_available() is True

    def test_is_gh_available_false(self) -> None:
        """Test _is_gh_available returns False when gh is not found."""
        handler = CloseHandler()
        with patch("shutil.which", return_value=None):
            assert handler._is_gh_available() is False

    def test_get_current_branch_success(self, tmp_path: Path) -> None:
        """Test _get_current_branch returns branch name on success."""
        handler = CloseHandler()

        mock_result = MagicMock()
        mock_result.stdout = "  feature-branch  \n"

        with patch("subprocess.run", return_value=mock_result):
            branch = handler._get_current_branch(tmp_path)
            assert branch == "feature-branch"

    def test_get_current_branch_failure(self, tmp_path: Path) -> None:
        """Test _get_current_branch raises CalledProcessError on failure."""
        handler = CloseHandler()

        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
            with pytest.raises(subprocess.CalledProcessError):
                handler._get_current_branch(tmp_path)

    def test_push_branch_success(self, tmp_path: Path) -> None:
        """Test _push_branch returns dict on success."""
        handler = CloseHandler()

        mock_result = MagicMock()
        mock_result.stdout = "Branch 'feature' set up to track remote branch 'feature'."

        with patch("subprocess.run", return_value=mock_result):
            result = handler._push_branch(tmp_path, "feature")
            assert result["branch"] == "feature"

    def test_push_branch_failure(self, tmp_path: Path) -> None:
        """Test _push_branch raises CalledProcessError on failure."""
        handler = CloseHandler()

        error = subprocess.CalledProcessError(1, "git", stderr=b"remote rejected")
        with patch("subprocess.run", side_effect=error):
            with pytest.raises(subprocess.CalledProcessError):
                handler._push_branch(tmp_path, "feature")

    def test_create_pr_success(self, tmp_path: Path) -> None:
        """Test _create_pr returns parsed JSON on success."""
        handler = CloseHandler()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "url": "https://github.com/org/repo/pull/42",
            "number": 42,
            "title": "My PR",
            "state": "open",
        })

        with patch("subprocess.run", return_value=mock_result):
            result = handler._create_pr(
                tmp_path, "feature", "main", "My PR", "Body text"
            )
            assert result["url"] == "https://github.com/org/repo/pull/42"
            assert result["number"] == 42

    def test_create_pr_with_custom_title_body(self, tmp_path: Path) -> None:
        """Test _create_pr passes custom title and body to gh."""
        handler = CloseHandler()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "url": "https://github.com/org/repo/pull/42",
            "number": 42,
        })

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            handler._create_pr(
                tmp_path, "feature", "main", "Custom Title", "Custom Body"
            )
            call_args = mock_run.call_args[0][0]
            assert "--title" in call_args
            assert "Custom Title" in call_args
            assert "--body" in call_args
            assert "Custom Body" in call_args

    def test_create_pr_failure(self, tmp_path: Path) -> None:
        """Test _create_pr raises CalledProcessError on gh failure."""
        handler = CloseHandler()

        error = subprocess.CalledProcessError(1, "gh", stderr=b"no commits")
        with patch("subprocess.run", side_effect=error):
            with pytest.raises(subprocess.CalledProcessError):
                handler._create_pr(tmp_path, "feature", "main", None, None)

    def test_write_success_signal(self, tmp_path: Path) -> None:
        """Test _write_success_signal creates correct file."""
        handler = CloseHandler()
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        handler._write_success_signal(
            signals_dir, "close_node", "feature", "https://github.com/pr/42", 42
        )

        signal_path = signals_dir / "CLOSE_COMPLETE.signal"
        assert signal_path.exists()

        data = json.loads(signal_path.read_text())
        assert data["node_id"] == "close_node"
        assert data["branch"] == "feature"
        assert data["pr_url"] == "https://github.com/pr/42"
        assert data["pr_number"] == 42
        assert data["status"] == "success"

    def test_write_error_signal(self, tmp_path: Path) -> None:
        """Test _write_error_signal creates correct file."""
        handler = CloseHandler()
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        handler._write_error_signal(
            signals_dir, "close_node", "Push failed", {"error_type": "PUSH_FAILED"}
        )

        signal_path = signals_dir / "CLOSE_FAILED.signal"
        assert signal_path.exists()

        data = json.loads(signal_path.read_text())
        assert data["node_id"] == "close_node"
        assert data["error"] == "Push failed"
        assert data["status"] == "failed"
        assert data["error_type"] == "PUSH_FAILED"


class TestCloseHandlerExecute:
    """Tests for CloseHandler.execute() full flow."""

    @pytest.mark.asyncio
    async def test_not_git_repo_returns_failure(self, tmp_path: Path) -> None:
        """Test execute returns FAILURE when target is not a git repo."""
        handler = CloseHandler()
        request = _make_request(
            attrs={"target_dir": str(tmp_path)},
            run_dir=str(tmp_path),
        )

        outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "NOT_GIT_REPO"

    @pytest.mark.asyncio
    async def test_gh_not_available_returns_failure(self, tmp_path: Path) -> None:
        """Test execute returns FAILURE when gh CLI is not available."""
        # Create .git directory to pass git check
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={"target_dir": str(tmp_path)},
            run_dir=str(tmp_path),
        )

        with patch("shutil.which", return_value=None):
            outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "GH_NOT_AVAILABLE"

    @pytest.mark.asyncio
    async def test_get_branch_failure_returns_failure(self, tmp_path: Path) -> None:
        """Test execute returns FAILURE when git branch fails."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={"target_dir": str(tmp_path)},
            run_dir=str(tmp_path),
        )

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "GIT_ERROR"

    @pytest.mark.asyncio
    async def test_push_failure_returns_failure(self, tmp_path: Path) -> None:
        """Test execute returns FAILURE when git push fails."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={"target_dir": str(tmp_path)},
            run_dir=str(tmp_path),
        )

        def mock_run(cmd, *_args, **_kwargs):
            if "branch" in cmd:
                result = MagicMock()
                result.stdout = "feature-branch"
                return result
            elif "push" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr=b"remote rejected")
            return MagicMock()

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=mock_run):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "PUSH_FAILED"

    @pytest.mark.asyncio
    async def test_pr_create_failure_returns_failure(self, tmp_path: Path) -> None:
        """Test execute returns FAILURE when gh pr create fails."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={"target_dir": str(tmp_path)},
            run_dir=str(tmp_path),
        )

        call_count = [0]

        def mock_run(cmd, *_args, **_kwargs):
            call_count[0] += 1
            result = MagicMock()
            if "branch" in cmd:
                result.stdout = "feature-branch"
            elif "push" in cmd:
                result.stdout = "pushed"
            elif "pr" in cmd:
                raise subprocess.CalledProcessError(1, cmd, stderr=b"no commits")
            return result

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=mock_run):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "PR_CREATE_FAILED"

    @pytest.mark.asyncio
    async def test_success_returns_success_with_signal(self, tmp_path: Path) -> None:
        """Test execute returns SUCCESS and writes signal on happy path."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={"target_dir": str(tmp_path)},
            run_dir=str(tmp_path),
        )

        def mock_run(cmd, *_args, **_kwargs):
            result = MagicMock()
            if "branch" in cmd:
                result.stdout = "feature-branch"
            elif "push" in cmd:
                result.stdout = "pushed"
            elif "pr" in cmd:
                result.stdout = json.dumps({
                    "url": "https://github.com/org/repo/pull/42",
                    "number": 42,
                    "title": "Auto PR",
                    "state": "open",
                })
            return result

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=mock_run):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.metadata.get("pr_url") == "https://github.com/org/repo/pull/42"
        assert outcome.metadata.get("pr_number") == 42
        assert outcome.metadata.get("branch") == "feature-branch"

        # Check signal file
        signal_path = tmp_path / "nodes" / "close_node" / "signals" / "CLOSE_COMPLETE.signal"
        assert signal_path.exists()

    @pytest.mark.asyncio
    async def test_custom_pr_title_body(self, tmp_path: Path) -> None:
        """Test execute uses custom PR title and body from node attrs."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={
                "target_dir": str(tmp_path),
                "pr_title": "Custom Title",
                "pr_body": "Custom Body",
            },
            run_dir=str(tmp_path),
        )

        def mock_run(cmd, *_args, **_kwargs):
            result = MagicMock()
            if "branch" in cmd:
                result.stdout = "feature-branch"
            elif "push" in cmd:
                result.stdout = "pushed"
            elif "pr" in cmd:
                # Verify custom title/body were passed
                assert "--title" in cmd
                assert "Custom Title" in cmd
                assert "--body" in cmd
                assert "Custom Body" in cmd
                result.stdout = json.dumps({
                    "url": "https://github.com/org/repo/pull/42",
                    "number": 42,
                })
            return result

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=mock_run):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_custom_base_branch(self, tmp_path: Path) -> None:
        """Test execute uses custom base branch from node attrs."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={
                "target_dir": str(tmp_path),
                "base_branch": "develop",
            },
            run_dir=str(tmp_path),
        )

        def mock_run(cmd, *_args, **_kwargs):
            result = MagicMock()
            if "branch" in cmd:
                result.stdout = "feature-branch"
            elif "push" in cmd:
                result.stdout = "pushed"
            elif "pr" in cmd:
                # Verify base branch was passed
                assert "develop" in cmd
                result.stdout = json.dumps({
                    "url": "https://github.com/org/repo/pull/42",
                    "number": 42,
                })
            return result

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=mock_run):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.metadata.get("base_branch") == "develop"

    @pytest.mark.asyncio
    async def test_default_target_dir_fallback(self, tmp_path: Path) -> None:
        """Test execute uses current directory when target_dir not specified."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        # Don't set target_dir - should fallback to "."
        request = _make_request(
            run_dir=str(tmp_path),
        )

        def mock_run(cmd, *_args, **_kwargs):
            result = MagicMock()
            if "branch" in cmd:
                result.stdout = "feature-branch"
            elif "push" in cmd:
                result.stdout = "pushed"
            elif "pr" in cmd:
                result.stdout = json.dumps({
                    "url": "https://github.com/org/repo/pull/42",
                    "number": 42,
                })
            return result

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=mock_run):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_context_updates_on_success(self, tmp_path: Path) -> None:
        """Test execute adds correct context updates on success."""
        (tmp_path / ".git").mkdir()

        handler = CloseHandler()
        request = _make_request(
            attrs={"target_dir": str(tmp_path)},
            run_dir=str(tmp_path),
        )

        def mock_run(cmd, *_args, **_kwargs):
            result = MagicMock()
            if "branch" in cmd:
                result.stdout = "feature-branch"
            elif "push" in cmd:
                result.stdout = "pushed"
            elif "pr" in cmd:
                result.stdout = json.dumps({
                    "url": "https://github.com/org/repo/pull/42",
                    "number": 42,
                })
            return result

        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", side_effect=mock_run):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates.get("$close_node.branch") == "feature-branch"
        assert outcome.context_updates.get("$close_node.pr_url") == "https://github.com/org/repo/pull/42"
        assert outcome.context_updates.get("$close_node.pr_number") == 42

    @pytest.mark.asyncio
    async def test_handler_isinstance_handler(self) -> None:
        """Test CloseHandler satisfies Handler protocol."""
        from cobuilder.engine.handlers.base import Handler

        handler = CloseHandler()
        assert isinstance(handler, Handler)


class TestCloseHandlerTimeout:
    """Tests for CloseHandler timeout configuration."""

    def test_custom_timeout(self) -> None:
        """Test handler accepts custom timeout."""
        handler = CloseHandler(timeout_s=600.0)
        assert handler._timeout_s == 600.0

    def test_default_timeout(self) -> None:
        """Test handler uses default timeout."""
        handler = CloseHandler()
        assert handler._timeout_s == 300.0

    def test_custom_default_branch(self) -> None:
        """Test handler accepts custom default branch."""
        handler = CloseHandler(default_branch="develop")
        assert handler._default_branch == "develop"