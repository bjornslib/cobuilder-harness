"""Tests for cobuilder.engine.handlers.manager_loop — ManagerLoopHandler."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cobuilder.engine.context import PipelineContext
from cobuilder.engine.graph import Node
from cobuilder.engine.handlers.base import HandlerRequest
from cobuilder.engine.handlers.manager_loop import ManagerLoopHandler
from cobuilder.engine.outcome import OutcomeStatus


def _make_request(
    node_id: str = "test_node",
    attrs: dict | None = None,
    run_dir: str = "",
    context_data: dict | None = None,
) -> HandlerRequest:
    """Create a HandlerRequest for testing."""
    if attrs is None:
        attrs = {}
    node = Node(
        id=node_id,
        shape="house",
        label="Test Node",
        attrs={"handler": "manager_loop", **attrs},
    )
    ctx = PipelineContext(initial=context_data or {})
    return HandlerRequest(
        node=node,
        context=ctx,
        run_dir=run_dir,
    )


class TestManagerLoopHandler:
    @pytest.mark.asyncio
    async def test_max_depth_exceeded(self) -> None:
        handler = ManagerLoopHandler()
        request = _make_request(
            attrs={"mode": "spawn_pipeline"},
            context_data={"$manager_depth": 10},
        )
        outcome = await handler.execute(request)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata["error_type"] == "MAX_DEPTH_EXCEEDED"

    @pytest.mark.asyncio
    async def test_spawn_pipeline_no_dot_path(self, tmp_path: Path) -> None:
        handler = ManagerLoopHandler()
        request = _make_request(
            attrs={"mode": "spawn_pipeline"},
            run_dir=str(tmp_path),
        )
        outcome = await handler.execute(request)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata["error_type"] == "NO_DOT_PATH"

    @pytest.mark.asyncio
    async def test_spawn_pipeline_with_sub_pipeline(self, tmp_path: Path) -> None:
        """Test that a valid sub_pipeline attribute resolves the DOT path."""
        handler = ManagerLoopHandler()

        # Create a dummy DOT file
        dot_file = tmp_path / "child.dot"
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        request = _make_request(
            attrs={
                "mode": "spawn_pipeline",
                "sub_pipeline": str(dot_file),
            },
            run_dir=str(tmp_path),
        )

        # Mock the subprocess to avoid actually spawning
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_proc.communicate = AsyncMock(return_value=(b"done", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_spawn_pipeline_with_params_file(self, tmp_path: Path) -> None:
        """Test resolution from pipeline_params_file JSON."""
        handler = ManagerLoopHandler()

        # Create child DOT file
        dot_file = tmp_path / "pipelines" / "child.dot"
        dot_file.parent.mkdir(parents=True)
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        # Create params JSON
        params_file = tmp_path / "state" / "plan.json"
        params_file.parent.mkdir(parents=True)
        params_file.write_text(json.dumps({
            "dot_path": str(dot_file),
            "template": "hub-spoke",
        }))

        request = _make_request(
            attrs={
                "mode": "spawn_pipeline",
                "pipeline_params_file": str(params_file),
            },
            run_dir=str(tmp_path),
        )

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.pid = 12345
        mock_proc.communicate = AsyncMock(return_value=(b"done", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_supervisor_mode_without_sub_pipeline(self) -> None:
        handler = ManagerLoopHandler()
        request = _make_request(attrs={})  # No mode, no sub_pipeline

        with pytest.raises(NotImplementedError, match="supervisor mode"):
            await handler.execute(request)

    @pytest.mark.asyncio
    async def test_child_failure_returns_failure(self, tmp_path: Path) -> None:
        handler = ManagerLoopHandler()

        dot_file = tmp_path / "child.dot"
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        request = _make_request(
            attrs={
                "mode": "spawn_pipeline",
                "sub_pipeline": str(dot_file),
            },
            run_dir=str(tmp_path),
        )

        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.pid = 12345
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error occurred"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata["child_returncode"] == 1
