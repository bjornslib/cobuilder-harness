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


class TestGateSignalDetection:
    """Tests for gate signal detection and handling."""

    @pytest.mark.asyncio
    async def test_detect_gate_signal_cobuilder(self, tmp_path: Path) -> None:
        """Test detection of GATE_WAIT_COBUILDER signal."""
        from cobuilder.engine.handlers.manager_loop import GateType
        from cobuilder.engine.signal_protocol import (
            GATE_WAIT_COBUILDER,
            write_signal,
        )

        handler = ManagerLoopHandler()

        # Create signals directory
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir(parents=True)

        # Write a cobuilder gate signal
        write_signal(
            source="child",
            target="parent",
            signal_type=GATE_WAIT_COBUILDER,
            payload={"node_id": "validate_node", "gate_type": "wait.cobuilder"},
            signals_dir=str(signals_dir),
        )

        # Detect the gate signal
        gate = handler._detect_gate_signal(signals_dir)

        assert gate is not None
        assert gate.gate_type == GateType.COBUILDER
        assert gate.node_id == "validate_node"

    @pytest.mark.asyncio
    async def test_detect_gate_signal_human(self, tmp_path: Path) -> None:
        """Test detection of GATE_WAIT_HUMAN signal."""
        from cobuilder.engine.handlers.manager_loop import GateType
        from cobuilder.engine.signal_protocol import (
            GATE_WAIT_HUMAN,
            write_signal,
        )

        handler = ManagerLoopHandler()

        # Create signals directory
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir(parents=True)

        # Write a human gate signal
        write_signal(
            source="child",
            target="parent",
            signal_type=GATE_WAIT_HUMAN,
            payload={"node_id": "approval_node", "gate_type": "wait.human"},
            signals_dir=str(signals_dir),
        )

        # Detect the gate signal
        gate = handler._detect_gate_signal(signals_dir)

        assert gate is not None
        assert gate.gate_type == GateType.HUMAN
        assert gate.node_id == "approval_node"

    @pytest.mark.asyncio
    async def test_detect_no_gate_signal(self, tmp_path: Path) -> None:
        """Test that _detect_gate_signal returns None when no gate signals exist."""
        handler = ManagerLoopHandler()

        # Create empty signals directory
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir(parents=True)

        # No gate signals present
        gate = handler._detect_gate_signal(signals_dir)

        assert gate is None

    @pytest.mark.asyncio
    async def test_handle_cobuilder_gate_auto_approve(self, tmp_path: Path) -> None:
        """Test that cobuilder gates are auto-approved and response signal written."""
        from cobuilder.engine.handlers.manager_loop import GateSignal, GateType

        handler = ManagerLoopHandler()

        # Create signals directory
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir(parents=True)

        # Create a gate signal
        gate = GateSignal(
            gate_type=GateType.COBUILDER,
            node_id="validate_node",
            prd_ref="PRD-TEST-001",
            signal_path=signals_dir / "test-signal.json",
        )

        # Create a mock node
        node = MagicMock()
        node.id = "parent_node"

        # Handle the gate
        result = await handler._handle_gate(
            gate=gate,
            signals_dir=str(signals_dir),
            node=node,
        )

        assert result.get("handled") is True

        # Verify response signal was written
        response_files = list(signals_dir.glob("*GATE_RESPONSE*.json"))
        assert len(response_files) >= 1

    @pytest.mark.asyncio
    async def test_handle_human_gate_not_handled(self, tmp_path: Path) -> None:
        """Test that human gates return not handled (requires external intervention)."""
        from cobuilder.engine.handlers.manager_loop import GateSignal, GateType

        handler = ManagerLoopHandler()

        # Create signals directory
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir(parents=True)

        # Create a gate signal
        gate = GateSignal(
            gate_type=GateType.HUMAN,
            node_id="approval_node",
            prd_ref="PRD-TEST-001",
            signal_path=signals_dir / "test-signal.json",
        )

        # Create a mock node
        node = MagicMock()
        node.id = "parent_node"

        # Handle the gate
        result = await handler._handle_gate(
            gate=gate,
            signals_dir=str(signals_dir),
            node=node,
        )

        assert result.get("handled") is False
        assert "human_intervention_required" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_child_pipeline_with_cobuilder_gate(self, tmp_path: Path) -> None:
        """Test that child hitting wait.cobuilder gate is handled correctly."""
        from cobuilder.engine.signal_protocol import (
            GATE_WAIT_COBUILDER,
            RUNNER_EXITED,
            write_signal,
        )

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

        # Mock subprocess that stays alive while gate is processed
        mock_proc = AsyncMock()
        mock_proc.returncode = None  # Process is running
        mock_proc.pid = 12345
        mock_proc.communicate = AsyncMock(return_value=(b"done", b""))

        signals_dir = tmp_path / "nodes" / "test_node" / "sub-run" / "signals"

        call_count = 0

        async def mock_sleep(_interval: float) -> None:
            nonlocal call_count
            call_count += 1

            # On first call, write a cobuilder gate signal
            if call_count == 1:
                signals_dir.mkdir(parents=True, exist_ok=True)
                write_signal(
                    source="child",
                    target="parent",
                    signal_type=GATE_WAIT_COBUILDER,
                    payload={"node_id": "child_gate", "prd_ref": "PRD-001"},
                    signals_dir=str(signals_dir),
                )

            # On third call, write completion signal and set returncode
            if call_count == 3:
                mock_proc.returncode = 0
                write_signal(
                    source="runner",
                    target="parent",
                    signal_type=RUNNER_EXITED,
                    payload={"status": "completed"},
                    signals_dir=str(signals_dir),
                )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.SUCCESS


class TestResolveChildDotPath:
    """Tests for _resolve_child_dot_path edge cases."""

    @pytest.mark.asyncio
    async def test_resolve_absolute_path(self, tmp_path: Path) -> None:
        """Test resolving an absolute DOT path."""
        handler = ManagerLoopHandler()

        # Create DOT file at absolute path
        dot_file = tmp_path / "absolute" / "child.dot"
        dot_file.parent.mkdir(parents=True)
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"sub_pipeline": str(dot_file)}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result == dot_file

    @pytest.mark.asyncio
    async def test_resolve_relative_path(self, tmp_path: Path) -> None:
        """Test resolving a relative DOT path."""
        handler = ManagerLoopHandler()

        # Create DOT file at relative path from run_dir
        dot_file = tmp_path / "pipelines" / "child.dot"
        dot_file.parent.mkdir(parents=True)
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"sub_pipeline": "pipelines/child.dot"}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result == dot_file

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_path_returns_none(self, tmp_path: Path) -> None:
        """Test that nonexistent path returns None."""
        handler = ManagerLoopHandler()

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"sub_pipeline": "/nonexistent/path.dot"}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_from_params_file_absolute_dot_path(self, tmp_path: Path) -> None:
        """Test resolving DOT path from params file with absolute path."""
        handler = ManagerLoopHandler()

        # Create DOT file
        dot_file = tmp_path / "child.dot"
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        # Create params file with absolute dot_path
        params_file = tmp_path / "params.json"
        params_file.write_text(json.dumps({"dot_path": str(dot_file)}))

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"pipeline_params_file": str(params_file)}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result == dot_file

    @pytest.mark.asyncio
    async def test_resolve_from_params_file_relative_dot_path(self, tmp_path: Path) -> None:
        """Test resolving DOT path from params file with relative path."""
        handler = ManagerLoopHandler()

        # Create DOT file at relative path
        dot_file = tmp_path / "pipelines" / "child.dot"
        dot_file.parent.mkdir(parents=True)
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        # Create params file with relative dot_path
        params_file = tmp_path / "params.json"
        params_file.write_text(json.dumps({"dot_path": "pipelines/child.dot"}))

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"pipeline_params_file": str(params_file)}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result == dot_file

    @pytest.mark.asyncio
    async def test_resolve_params_file_relative_path(self, tmp_path: Path) -> None:
        """Test resolving params file itself from relative path."""
        handler = ManagerLoopHandler()

        # Create DOT file
        dot_file = tmp_path / "child.dot"
        dot_file.write_text('digraph test { start [shape=Mdiamond]; }')

        # Create params file at relative location
        params_dir = tmp_path / "state"
        params_dir.mkdir()
        params_file = params_dir / "params.json"
        params_file.write_text(json.dumps({"dot_path": str(dot_file)}))

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"pipeline_params_file": "state/params.json"}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result == dot_file

    @pytest.mark.asyncio
    async def test_resolve_invalid_json_params_returns_none(self, tmp_path: Path) -> None:
        """Test that invalid JSON in params file returns None."""
        handler = ManagerLoopHandler()

        params_file = tmp_path / "params.json"
        params_file.write_text("not valid json")

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"pipeline_params_file": str(params_file)}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_missing_dot_path_key_returns_none(self, tmp_path: Path) -> None:
        """Test that params file without dot_path returns None."""
        handler = ManagerLoopHandler()

        params_file = tmp_path / "params.json"
        params_file.write_text(json.dumps({"template": "hub-spoke"}))

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"pipeline_params_file": str(params_file)}

        result = await handler._resolve_child_dot_path(node, tmp_path)
        assert result is None


class TestLaunchSummarizer:
    """Tests for _launch_summarizer."""

    @pytest.mark.asyncio
    async def test_launch_summarizer_success(self, tmp_path: Path) -> None:
        """Test successful summarizer launch."""
        handler = ManagerLoopHandler()

        dot_path = tmp_path / "child.dot"
        dot_path.write_text('digraph test {}')
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        mock_proc = AsyncMock()
        mock_proc.pid = 54321

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await handler._launch_summarizer(dot_path, str(signals_dir), tmp_path)

        assert result is not None
        assert result.pid == 54321

    @pytest.mark.asyncio
    async def test_launch_summarizer_failure_returns_none(self, tmp_path: Path) -> None:
        """Test that summarizer launch failure returns None."""
        handler = ManagerLoopHandler()

        dot_path = tmp_path / "child.dot"
        dot_path.write_text('digraph test {}')
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        with patch("asyncio.create_subprocess_exec", side_effect=OSError("Failed")):
            result = await handler._launch_summarizer(dot_path, str(signals_dir), tmp_path)

        assert result is None


class TestMonitorChildProcess:
    """Tests for _monitor_child_process edge cases."""

    @pytest.mark.asyncio
    async def test_monitor_timeout_kills_child(self, tmp_path: Path) -> None:
        """Test that monitor kills child process on timeout."""
        handler = ManagerLoopHandler()

        mock_proc = AsyncMock()
        mock_proc.returncode = None  # Process never exits
        mock_proc.pid = 12345
        mock_proc.kill = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"timeout": "0.1"}  # Very short timeout

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        # Sleep counter to limit iterations
        sleep_count = [0]

        async def limited_sleep(interval: float) -> None:
            sleep_count[0] += 1
            if sleep_count[0] > 5:  # Limit iterations
                raise RuntimeError("Test limit reached")

        with patch("asyncio.sleep", side_effect=limited_sleep):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.time.return_value = 0.0
                # Simulate time passing
                time_val = [0.0]
                def increment_time():
                    time_val[0] += 1.0
                    return time_val[0]
                mock_loop.return_value.time.side_effect = increment_time

                result = await handler._monitor_child_process(mock_proc, node, str(signals_dir))

        assert result["status"] == "failed"
        assert result["error"] == "timeout"
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_monitor_handles_runner_exited_signal(self, tmp_path: Path) -> None:
        """Test that monitor detects RUNNER_EXITED signal."""
        import datetime
        from cobuilder.engine.signal_protocol import RUNNER_EXITED

        handler = ManagerLoopHandler()

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        node = MagicMock()
        node.id = "test_node"
        node.attrs = {"timeout": "300"}

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        # Write completion signal in the format the handler expects (flat structure)
        # The handler reads: sig_data.get("checkpoint_path", "")
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        signal_file = signals_dir / f"{timestamp}-runner-parent-{RUNNER_EXITED}.json"
        signal_file.write_text(json.dumps({
            "status": "completed",
            "checkpoint_path": "/tmp/checkpoint.json",
        }))

        call_count = [0]

        async def single_sleep(_interval: float) -> None:
            call_count[0] += 1
            if call_count[0] > 1:
                raise RuntimeError("Should have exited")

        with patch("asyncio.sleep", side_effect=single_sleep):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.time.return_value = 0.0
                result = await handler._monitor_child_process(mock_proc, node, str(signals_dir))

        assert result["status"] == "completed"
        assert result["checkpoint_path"] == "/tmp/checkpoint.json"


class TestSpawnFailure:
    """Tests for subprocess spawn failure handling."""

    @pytest.mark.asyncio
    async def test_spawn_failure_returns_failure(self, tmp_path: Path) -> None:
        """Test that subprocess spawn failure returns FAILURE outcome."""
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

        with patch("asyncio.create_subprocess_exec", side_effect=OSError("Cannot spawn")):
            outcome = await handler.execute(request)

        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "SPAWN_FAILED"


class TestGateSignalEdgeCases:
    """Tests for gate signal edge cases."""

    @pytest.mark.asyncio
    async def test_detect_gate_signal_malformed_json(self, tmp_path: Path) -> None:
        """Test that malformed gate signal JSON is ignored."""
        from cobuilder.engine.signal_protocol import GATE_WAIT_COBUILDER

        handler = ManagerLoopHandler()

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        # Write malformed signal file
        malformed_signal = signals_dir / f"source_target_{GATE_WAIT_COBUILDER}.json"
        malformed_signal.write_text("not valid json")

        gate = handler._detect_gate_signal(signals_dir)
        assert gate is None

    @pytest.mark.asyncio
    async def test_detect_gate_signal_missing_payload(self, tmp_path: Path) -> None:
        """Test gate signal with missing payload uses defaults."""
        from cobuilder.engine.signal_protocol import GATE_WAIT_COBUILDER, write_signal

        handler = ManagerLoopHandler()

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        # Write signal without node_id in payload
        write_signal(
            source="child",
            target="parent",
            signal_type=GATE_WAIT_COBUILDER,
            payload={},  # Missing node_id
            signals_dir=str(signals_dir),
        )

        gate = handler._detect_gate_signal(signals_dir)

        assert gate is not None
        assert gate.node_id == "unknown"  # Default value
        assert gate.prd_ref == ""  # Default value

    @pytest.mark.asyncio
    async def test_handle_gate_write_failure(self, tmp_path: Path) -> None:
        """Test that failure to write gate response returns handled=False."""
        from cobuilder.engine.handlers.manager_loop import GateSignal, GateType

        handler = ManagerLoopHandler()

        # Create a signals dir that will fail writes
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        gate = GateSignal(
            gate_type=GateType.COBUILDER,
            node_id="validate_node",
            prd_ref="PRD-TEST-001",
            signal_path=signals_dir / "test-signal.json",
        )

        node = MagicMock()
        node.id = "parent_node"

        # Make write_gate_response fail
        with patch(
            "cobuilder.engine.handlers.manager_loop.write_gate_response",
            side_effect=OSError("Write failed"),
        ):
            result = await handler._handle_gate(
                gate=gate,
                signals_dir=str(signals_dir),
                node=node,
            )

        assert result.get("handled") is False
        assert result.get("error") == "response_write_failed"
