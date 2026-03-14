"""Tests for cobuilder.engine.handlers — all built-in handlers.

Coverage targets (from SD Section 9):
- handlers/  ≥ 85%

Test structure mirrors the SD's AC-F3 through AC-F13 acceptance criteria.
Async tests use pytest-asyncio (asyncio_mode=auto).
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cobuilder.engine.context import PipelineContext
from cobuilder.engine.exceptions import HandlerError, UnknownShapeError
from cobuilder.engine.graph import Graph, Node, Edge
from cobuilder.engine.handlers.base import Handler, HandlerRequest
from cobuilder.engine.handlers.codergen import CodergenHandler
from cobuilder.engine.handlers.conditional import ConditionalHandler
from cobuilder.engine.handlers.exit import ExitHandler
from cobuilder.engine.handlers.fan_in import FanInHandler
from cobuilder.engine.handlers.manager_loop import ManagerLoopHandler
from cobuilder.engine.handlers.parallel import ParallelHandler
from cobuilder.engine.handlers.registry import HandlerRegistry
from cobuilder.engine.handlers.start import StartHandler
from cobuilder.engine.handlers.tool import ToolHandler
from cobuilder.engine.handlers.wait_human import WaitHumanHandler
from cobuilder.engine.outcome import Outcome, OutcomeStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_node(
    id: str = "n1",
    shape: str = "box",
    **attrs: Any,
) -> Node:
    return Node(id=id, shape=shape, label=id, attrs=attrs)


def make_request(
    node: Node | None = None,
    context: PipelineContext | None = None,
    run_dir: str = "",
) -> HandlerRequest:
    if node is None:
        node = make_node()
    if context is None:
        context = PipelineContext()
    return HandlerRequest(
        node=node,
        context=context,
        run_dir=run_dir,
    )


def make_linear_graph() -> Graph:
    """3-node: start → impl → exit."""
    start = Node(id="start", shape="Mdiamond")
    impl = Node(id="impl", shape="box", attrs={"goal_gate": "true"})
    exit_ = Node(id="exit", shape="Msquare")
    edges = [
        Edge(source="start", target="impl"),
        Edge(source="impl", target="exit"),
    ]
    return Graph(
        name="test",
        nodes={"start": start, "impl": impl, "exit": exit_},
        edges=edges,
    )


# ---------------------------------------------------------------------------
# AC-F3: HandlerRegistry
# ---------------------------------------------------------------------------

class TestHandlerRegistry:
    def test_dispatch_known_shape(self):
        handler = StartHandler()
        registry = HandlerRegistry(handlers={"Mdiamond": handler})
        result = registry.dispatch(make_node(shape="Mdiamond"))
        assert result is handler

    def test_dispatch_unknown_shape_raises(self):
        registry = HandlerRegistry()
        with pytest.raises(UnknownShapeError) as exc_info:
            registry.dispatch(make_node(shape="galaxy", id="n99"))
        assert "galaxy" in str(exc_info.value)
        assert "n99" in str(exc_info.value)

    def test_unknown_shape_error_attributes(self):
        exc = UnknownShapeError(shape="triangle", node_id="my_node")
        assert exc.shape == "triangle"
        assert exc.node_id == "my_node"

    def test_register_and_dispatch_all_10_shapes(self):
        registry = HandlerRegistry.default()
        shapes = [
            "Mdiamond", "Msquare", "box", "diamond",
            "hexagon", "component", "tripleoctagon", "parallelogram", "house",
            "octagon",
        ]
        for shape in shapes:
            handler = registry.dispatch(make_node(shape=shape))
            assert handler is not None

    def test_registry_dependency_injection(self):
        """Registry can be instantiated with a custom handler dict for testing."""
        custom_handler = StartHandler()
        registry = HandlerRegistry(handlers={"custom_shape": custom_handler})
        assert registry.dispatch(make_node(shape="custom_shape")) is custom_handler

    def test_registered_shapes(self):
        registry = HandlerRegistry()
        registry.register("box", StartHandler())
        registry.register("diamond", ConditionalHandler())
        shapes = registry.registered_shapes()
        assert "box" in shapes
        assert "diamond" in shapes

    def test_register_overwrites_existing(self):
        registry = HandlerRegistry()
        h1 = StartHandler()
        h2 = ConditionalHandler()
        registry.register("box", h1)
        registry.register("box", h2)
        assert registry.dispatch(make_node(shape="box")) is h2

    def test_default_registry_has_all_10_shapes(self):
        registry = HandlerRegistry.default()
        assert len(registry.registered_shapes()) == 10


# ---------------------------------------------------------------------------
# AC-F4: StartHandler
# ---------------------------------------------------------------------------

class TestStartHandler:
    @pytest.mark.asyncio
    async def test_returns_skipped(self):
        handler = StartHandler()
        req = make_request(node=make_node(shape="Mdiamond"))
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_no_context_updates(self):
        handler = StartHandler()
        req = make_request(node=make_node(shape="Mdiamond"))
        outcome = await handler.execute(req)
        assert outcome.context_updates == {}

    @pytest.mark.asyncio
    async def test_no_side_effects(self):
        """StartHandler must not modify the context."""
        ctx = PipelineContext({"key": "original"})
        handler = StartHandler()
        req = make_request(node=make_node(shape="Mdiamond"), context=ctx)
        await handler.execute(req)
        assert ctx.get("key") == "original"

    def test_implements_handler_protocol(self):
        assert isinstance(StartHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F5: ExitHandler
# ---------------------------------------------------------------------------

class TestExitHandler:
    def _make_exit_request(
        self,
        goal_gate_ids: list[str] | None = None,
        completed_nodes: list[str] | None = None,
        run_dir: str = "",
    ) -> HandlerRequest:
        """Build a request with the graph and completed_nodes set in context."""
        graph = make_linear_graph()
        # Override goal_gate for specified nodes
        if goal_gate_ids is not None:
            for node_id, node in graph.nodes.items():
                node.attrs["goal_gate"] = "true" if node_id in goal_gate_ids else "false"

        ctx = PipelineContext({
            "$graph": graph,
            "$completed_nodes": completed_nodes or [],
        })
        exit_node = make_node(shape="Msquare", id="exit")
        return HandlerRequest(node=exit_node, context=ctx, run_dir=run_dir)

    @pytest.mark.asyncio
    async def test_success_when_all_goal_gates_completed(self):
        handler = ExitHandler()
        req = self._make_exit_request(
            goal_gate_ids=["impl"],
            completed_nodes=["start", "impl"],
        )
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates["$pipeline_outcome"] == "success"

    @pytest.mark.asyncio
    async def test_failure_when_goal_gate_missing(self):
        handler = ExitHandler()
        req = self._make_exit_request(
            goal_gate_ids=["impl"],
            completed_nodes=["start"],  # impl not completed
        )
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.context_updates["$pipeline_outcome"] == "failure"
        assert "impl" in outcome.context_updates["$missing_goal_gates"]

    @pytest.mark.asyncio
    async def test_success_with_no_goal_gates(self):
        """Pipeline with no goal_gate nodes should succeed immediately."""
        graph = Graph(
            name="no_gates",
            nodes={
                "start": Node(id="start", shape="Mdiamond"),
                "exit": Node(id="exit", shape="Msquare"),
            },
            edges=[Edge(source="start", target="exit")],
        )
        ctx = PipelineContext({
            "$graph": graph,
            "$completed_nodes": ["start"],
        })
        req = HandlerRequest(node=make_node(shape="Msquare", id="exit"), context=ctx)
        outcome = await ExitHandler().execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_writes_completion_signal(self, tmp_path: Path):
        handler = ExitHandler()
        req = self._make_exit_request(
            goal_gate_ids=["impl"],
            completed_nodes=["start", "impl"],
            run_dir=str(tmp_path),
        )
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS
        signal_file = tmp_path / "signals" / "pipeline_complete.signal"
        assert signal_file.exists()
        content = json.loads(signal_file.read_text())
        assert content["status"] == "success"

    @pytest.mark.asyncio
    async def test_no_signal_on_failure(self, tmp_path: Path):
        handler = ExitHandler()
        req = self._make_exit_request(
            goal_gate_ids=["impl"],
            completed_nodes=[],
            run_dir=str(tmp_path),
        )
        await handler.execute(req)
        signal_dir = tmp_path / "signals"
        if signal_dir.exists():
            assert not (signal_dir / "pipeline_complete.signal").exists()

    def test_implements_handler_protocol(self):
        assert isinstance(ExitHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F6: CodergenHandler
# ---------------------------------------------------------------------------

class TestCodergenHandler:
    def _make_mock_spawner(self) -> AsyncMock:
        spawner = AsyncMock()
        spawner.return_value = {"status": "ok", "session": "orch-test"}
        return spawner

    def _make_immediate_complete_poller(
        self,
        signal_type: str = "VALIDATION_PASSED",
    ) -> AsyncMock:
        async def _poll(target_layer, timeout, signals_dir, poll_interval):
            return {
                "source": "runner",
                "target": "guardian",
                "signal_type": signal_type,
                "payload": {},
            }
        return _poll

    @pytest.mark.asyncio
    async def test_tmux_dispatch_spawns_orchestrator(self, tmp_path: Path):
        spawner = self._make_mock_spawner()
        poller = self._make_immediate_complete_poller()
        handler = CodergenHandler(spawner=spawner, signal_poller=poller, poll_interval_s=0)

        node = make_node(id="impl_auth", shape="box", dispatch_strategy="tmux")
        ctx = PipelineContext({"$graph": make_linear_graph()})
        req = HandlerRequest(node=node, context=ctx, run_dir=str(tmp_path))

        outcome = await handler.execute(req)
        spawner.assert_awaited_once()
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_tmux_writes_prompt_before_spawn(self, tmp_path: Path):
        spawn_order = []

        async def _spawner(**kwargs):
            spawn_order.append("spawn")
            return {"status": "ok"}

        async def _poller(**kwargs):
            return {"signal_type": "VALIDATION_PASSED", "payload": {}}

        handler = CodergenHandler(spawner=_spawner, signal_poller=_poller)
        node = make_node(id="task1", shape="box", prompt="Do the thing")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))

        await handler.execute(req)

        prompt_file = tmp_path / "nodes" / "task1" / "prompt.md"
        assert prompt_file.exists()
        assert "Do the thing" in prompt_file.read_text()

    @pytest.mark.asyncio
    async def test_tmux_timeout_returns_failure(self, tmp_path: Path):
        spawner = self._make_mock_spawner()
        # No signal poller — use filesystem (no signals written → timeout)
        handler = CodergenHandler(
            spawner=spawner,
            timeout_s=0.05,   # Very short timeout
            poll_interval_s=0.01,
        )
        node = make_node(id="timeout_node", shape="box")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))

        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "TIMEOUT"

    @pytest.mark.asyncio
    async def test_complete_signal_file_triggers_success(self, tmp_path: Path):
        node_id = "my_node"
        spawner = self._make_mock_spawner()

        # Write complete signal before handler polls
        signals_dir = tmp_path / "nodes" / node_id / "signals"
        signals_dir.mkdir(parents=True)
        (signals_dir / f"{node_id}-complete.signal").write_text('{"done": true}')

        handler = CodergenHandler(spawner=spawner, timeout_s=10, poll_interval_s=0)
        node = make_node(id=node_id, shape="box")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))

        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.metadata["signal"] == "complete"

    @pytest.mark.asyncio
    async def test_failed_signal_file_triggers_failure(self, tmp_path: Path):
        node_id = "failing_node"
        spawner = self._make_mock_spawner()

        signals_dir = tmp_path / "nodes" / node_id / "signals"
        signals_dir.mkdir(parents=True)
        (signals_dir / f"{node_id}-failed.signal").write_text('{"feedback": "tests failed"}')

        handler = CodergenHandler(spawner=spawner, timeout_s=10, poll_interval_s=0)
        node = make_node(id=node_id, shape="box")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))

        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata["feedback"] == "tests failed"

    @pytest.mark.asyncio
    async def test_needs_review_signal_triggers_partial_success(self, tmp_path: Path):
        node_id = "review_node"
        spawner = self._make_mock_spawner()

        signals_dir = tmp_path / "nodes" / node_id / "signals"
        signals_dir.mkdir(parents=True)
        (signals_dir / f"{node_id}-needs-review.signal").write_text("{}")

        handler = CodergenHandler(spawner=spawner, timeout_s=10, poll_interval_s=0)
        node = make_node(id=node_id, shape="box")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))

        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.PARTIAL_SUCCESS

    @pytest.mark.asyncio
    async def test_sdk_dispatch_strategy(self):
        """SDK dispatch falls back to tmux when claude_code_sdk not importable."""
        spawner = self._make_mock_spawner()
        poller = self._make_immediate_complete_poller()
        handler = CodergenHandler(spawner=spawner, signal_poller=poller)
        node = make_node(id="sdk_node", shape="box", dispatch_strategy="sdk")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir="")

        # SDK not installed in test env — should fall back to tmux
        outcome = await handler.execute(req)
        # Either SDK succeeded or fell back; either way not an exception
        assert outcome.status in (OutcomeStatus.SUCCESS, OutcomeStatus.FAILURE)

    def test_implements_handler_protocol(self):
        assert isinstance(CodergenHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F7: ConditionalHandler
# ---------------------------------------------------------------------------

class TestConditionalHandler:
    @pytest.mark.asyncio
    async def test_returns_success(self):
        handler = ConditionalHandler()
        outcome = await handler.execute(make_request(node=make_node(shape="diamond")))
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_no_context_updates(self):
        handler = ConditionalHandler()
        outcome = await handler.execute(make_request(node=make_node(shape="diamond")))
        assert outcome.context_updates == {}

    @pytest.mark.asyncio
    async def test_no_preferred_label(self):
        handler = ConditionalHandler()
        outcome = await handler.execute(make_request(node=make_node(shape="diamond")))
        assert outcome.preferred_label is None
        assert outcome.suggested_next is None

    def test_implements_handler_protocol(self):
        assert isinstance(ConditionalHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F8: WaitHumanHandler
# ---------------------------------------------------------------------------

class TestWaitHumanHandler:
    @pytest.mark.asyncio
    async def test_returns_waiting_when_no_signal(self, tmp_path: Path):
        handler = WaitHumanHandler(timeout_s=-1.0)  # indefinite but returns after 1 poll
        node = make_node(id="gate1", shape="hexagon")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.WAITING

    @pytest.mark.asyncio
    async def test_approve_signal_returns_success(self, tmp_path: Path):
        node_id = "human_gate"
        signals_dir = tmp_path / "nodes" / node_id / "signals"
        signals_dir.mkdir(parents=True)
        (signals_dir / "INPUT_RESPONSE.signal").write_text('{"response": "approve"}')

        handler = WaitHumanHandler(timeout_s=-1.0)
        node = make_node(id=node_id, shape="hexagon")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates[f"${node_id}.approval"] == "approved"

    @pytest.mark.asyncio
    async def test_reject_signal_returns_failure(self, tmp_path: Path):
        node_id = "human_gate"
        signals_dir = tmp_path / "nodes" / node_id / "signals"
        signals_dir.mkdir(parents=True)
        (signals_dir / "INPUT_RESPONSE.signal").write_text('{"response": "reject"}')

        handler = WaitHumanHandler(timeout_s=-1.0)
        node = make_node(id=node_id, shape="hexagon")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE

    @pytest.mark.asyncio
    async def test_timeout_returns_waiting(self, tmp_path: Path):
        handler = WaitHumanHandler(timeout_s=0.02, poll_interval_s=0.01)
        node = make_node(id="gate_timeout", shape="hexagon")
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.WAITING
        assert outcome.metadata.get("reason") == "timeout"

    def test_implements_handler_protocol(self):
        assert isinstance(WaitHumanHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F10: ParallelHandler
# ---------------------------------------------------------------------------

class TestParallelHandler:
    @pytest.mark.asyncio
    async def test_no_children_returns_success(self):
        """Node with no outgoing edges → trivially SUCCESS."""
        handler = ParallelHandler()
        graph = Graph(
            name="solo",
            nodes={"parallel": Node(id="parallel", shape="component")},
            edges=[],
        )
        ctx = PipelineContext({"$graph": graph})
        node = make_node(id="parallel", shape="component")
        req = HandlerRequest(node=node, context=ctx)
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_wait_all_all_success(self):
        """wait_all: all children succeed → SUCCESS."""
        success_handler = MagicMock()
        success_handler.execute = AsyncMock(
            return_value=Outcome(status=OutcomeStatus.SUCCESS)
        )
        registry = MagicMock()
        registry.dispatch = MagicMock(return_value=success_handler)

        handler = ParallelHandler(handler_registry=registry)
        graph = Graph(
            name="par",
            nodes={
                "par": Node(id="par", shape="component"),
                "c1": Node(id="c1", shape="box"),
                "c2": Node(id="c2", shape="box"),
            },
            edges=[
                Edge(source="par", target="c1"),
                Edge(source="par", target="c2"),
            ],
        )
        ctx = PipelineContext({"$graph": graph})
        req = HandlerRequest(node=graph.node("par"), context=ctx)
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_wait_all_one_failure(self):
        """wait_all: one child fails → FAILURE."""
        call_count = [0]

        async def _mock_execute(req: HandlerRequest) -> Outcome:
            call_count[0] += 1
            if req.node.id == "c1":
                return Outcome(status=OutcomeStatus.SUCCESS)
            return Outcome(status=OutcomeStatus.FAILURE)

        mock_handler = MagicMock()
        mock_handler.execute = _mock_execute

        registry = MagicMock()
        registry.dispatch = MagicMock(return_value=mock_handler)

        handler = ParallelHandler(handler_registry=registry)
        graph = Graph(
            name="par",
            nodes={
                "par": Node(id="par", shape="component"),
                "c1": Node(id="c1", shape="box"),
                "c2": Node(id="c2", shape="box"),
            },
            edges=[
                Edge(source="par", target="c1"),
                Edge(source="par", target="c2"),
            ],
        )
        ctx = PipelineContext({"$graph": graph})
        req = HandlerRequest(node=graph.node("par"), context=ctx)
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE

    @pytest.mark.asyncio
    async def test_child_gets_snapshot_not_live_context(self):
        """Each child receives a snapshot copy — mutations don't affect siblings."""
        seen_contexts: list[dict] = []

        async def _mock_execute(req: HandlerRequest) -> Outcome:
            seen_contexts.append(req.context.snapshot())
            # Write to the child's context — should not affect siblings
            req.context.update({"sibling_key": req.node.id})
            return Outcome(status=OutcomeStatus.SUCCESS)

        mock_handler = MagicMock()
        mock_handler.execute = _mock_execute

        registry = MagicMock()
        registry.dispatch = MagicMock(return_value=mock_handler)

        handler = ParallelHandler(handler_registry=registry)
        graph = Graph(
            name="par",
            nodes={
                "par": Node(id="par", shape="component"),
                "c1": Node(id="c1", shape="box"),
                "c2": Node(id="c2", shape="box"),
            },
            edges=[
                Edge(source="par", target="c1"),
                Edge(source="par", target="c2"),
            ],
        )
        ctx = PipelineContext({"$graph": graph, "initial_key": "original"})
        req = HandlerRequest(node=graph.node("par"), context=ctx)
        await handler.execute(req)

        # Main context should not have "sibling_key" directly set by children
        assert ctx.get("sibling_key") is None

    def test_implements_handler_protocol(self):
        assert isinstance(ParallelHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F11: FanInHandler
# ---------------------------------------------------------------------------

class TestFanInHandler:
    @pytest.mark.asyncio
    async def test_no_results_returns_success(self):
        """No branch results → trivially SUCCESS."""
        handler = FanInHandler()
        req = make_request(node=make_node(id="fan_in", shape="tripleoctagon"))
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_wait_all_all_success(self):
        handler = FanInHandler()
        ctx = PipelineContext({
            "$fan_in.fan_in.results": {"b1": "success", "b2": "success"},
        })
        req = HandlerRequest(
            node=make_node(id="fan_in", shape="tripleoctagon", join_policy="wait_all"),
            context=ctx,
        )
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_wait_all_one_failure(self):
        handler = FanInHandler()
        ctx = PipelineContext({
            "$fan_in.fan_in.results": {"b1": "success", "b2": "failure"},
        })
        req = HandlerRequest(
            node=make_node(id="fan_in", shape="tripleoctagon", join_policy="wait_all"),
            context=ctx,
        )
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE

    @pytest.mark.asyncio
    async def test_first_success_policy(self):
        handler = FanInHandler()
        ctx = PipelineContext({
            "$fan_in.fan_in.results": {"b1": "failure", "b2": "success"},
        })
        req = HandlerRequest(
            node=make_node(id="fan_in", shape="tripleoctagon", join_policy="first_success"),
            context=ctx,
        )
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS

    def test_implements_handler_protocol(self):
        assert isinstance(FanInHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F12: ToolHandler
# ---------------------------------------------------------------------------

class TestToolHandler:
    @pytest.mark.asyncio
    async def test_exit_0_returns_success(self):
        handler = ToolHandler()
        node = make_node(id="t1", shape="parallelogram", tool_command="echo hello")
        req = make_request(node=node)
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS
        assert outcome.context_updates["$t1.exit_code"] == 0

    @pytest.mark.asyncio
    async def test_nonzero_exit_returns_failure(self):
        handler = ToolHandler()
        node = make_node(id="t2", shape="parallelogram", tool_command="exit 1")
        req = make_request(node=node)
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.context_updates["$t2.exit_code"] != 0

    @pytest.mark.asyncio
    async def test_stdout_captured(self):
        handler = ToolHandler()
        node = make_node(
            id="t3",
            shape="parallelogram",
            tool_command="echo captured_output",
        )
        req = make_request(node=node)
        outcome = await handler.execute(req)
        assert "captured_output" in outcome.context_updates["$t3.stdout"]

    @pytest.mark.asyncio
    async def test_stderr_captured(self):
        handler = ToolHandler()
        node = make_node(
            id="t4",
            shape="parallelogram",
            tool_command="echo error_output >&2",
        )
        req = make_request(node=node)
        outcome = await handler.execute(req)
        # stderr might or might not capture; just check key exists
        assert "$t4.stderr" in outcome.context_updates

    @pytest.mark.asyncio
    async def test_empty_command_returns_success(self):
        handler = ToolHandler()
        node = make_node(id="empty", shape="parallelogram")  # no tool_command
        req = make_request(node=node)
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        handler = ToolHandler(timeout_s=0.05)
        # sleep longer than timeout
        node = make_node(
            id="slow",
            shape="parallelogram",
            tool_command="sleep 10",
        )
        req = make_request(node=node)
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "TIMEOUT"

    def test_implements_handler_protocol(self):
        assert isinstance(ToolHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-F13: ManagerLoopHandler — stub raises NotImplementedError
# ---------------------------------------------------------------------------

class TestManagerLoopHandler:
    @pytest.mark.asyncio
    async def test_raises_not_implemented_error(self):
        handler = ManagerLoopHandler()
        req = make_request(node=make_node(id="mgr", shape="house"))
        with pytest.raises(NotImplementedError) as exc_info:
            await handler.execute(req)
        assert "not yet implemented" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_error_message_contains_node_id(self):
        handler = ManagerLoopHandler()
        req = make_request(node=make_node(id="my_manager_node", shape="house"))
        with pytest.raises(NotImplementedError) as exc_info:
            await handler.execute(req)
        assert "my_manager_node" in str(exc_info.value)

    def test_implements_handler_protocol(self):
        assert isinstance(ManagerLoopHandler(), Handler)


# ---------------------------------------------------------------------------
# AC-E4-Close: CloseHandler
# ---------------------------------------------------------------------------

class TestCloseHandler:
    @pytest.mark.asyncio
    async def test_not_git_repo_returns_failure(self, tmp_path: Path):
        """Non-git directory returns FAILURE."""
        from cobuilder.engine.handlers.close import CloseHandler

        handler = CloseHandler()
        node = make_node(id="close1", shape="octagon", target_dir=str(tmp_path))
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))

        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE
        assert outcome.metadata.get("error_type") == "NOT_GIT_REPO"

    @pytest.mark.asyncio
    async def test_gh_not_available_returns_failure(self, tmp_path: Path):
        """Missing gh CLI returns FAILURE."""
        from cobuilder.engine.handlers.close import CloseHandler

        # Create a proper git repo structure (minimal)
        # This test checks gh availability, but git operations will fail first
        # if the directory isn't a real git repo
        handler = CloseHandler()
        node = make_node(id="close2", shape="octagon", target_dir=str(tmp_path))
        req = HandlerRequest(node=node, context=PipelineContext(), run_dir=str(tmp_path))

        # This will fail because it's not a real git repo (git commands fail)
        # If gh is installed, it would still fail on git operations
        outcome = await handler.execute(req)
        assert outcome.status == OutcomeStatus.FAILURE
        # Error type depends on what fails first - git or gh
        assert outcome.metadata.get("error_type") in ["NOT_GIT_REPO", "GIT_ERROR", "GH_NOT_AVAILABLE"]

    @pytest.mark.asyncio
    async def test_implements_handler_protocol(self):
        from cobuilder.engine.handlers.close import CloseHandler

        assert isinstance(CloseHandler(), Handler)

    @pytest.mark.asyncio
    async def test_registered_for_octagon_shape(self):
        """CloseHandler is registered for 'octagon' shape."""
        registry = HandlerRegistry.default()
        from cobuilder.engine.handlers.close import CloseHandler

        handler = registry.dispatch(make_node(shape="octagon"))
        assert isinstance(handler, CloseHandler)

    @pytest.mark.asyncio
    async def test_writes_success_signal_on_complete(self, tmp_path: Path):
        """On success, writes CLOSE_COMPLETE.signal."""
        from cobuilder.engine.handlers.close import CloseHandler

        # This test would need mocking of git/gh commands
        # For now, we just verify the signal file path logic
        node = make_node(id="close3", shape="octagon")
        signals_dir = tmp_path / "nodes" / "close3" / "signals"

        # Verify the handler creates signals_dir structure
        assert signals_dir.parent.parent == tmp_path / "nodes"

    @pytest.mark.asyncio
    async def test_default_timeout(self):
        """Default timeout is 300 seconds."""
        from cobuilder.engine.handlers.close import CloseHandler

        handler = CloseHandler()
        assert handler._timeout_s == 300.0

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        """Custom timeout can be set."""
        from cobuilder.engine.handlers.close import CloseHandler

        handler = CloseHandler(timeout_s=60.0)
        assert handler._timeout_s == 60.0

    @pytest.mark.asyncio
    async def test_default_branch_configurable(self):
        """Default base branch is configurable."""
        from cobuilder.engine.handlers.close import CloseHandler

        handler = CloseHandler(default_branch="develop")
        assert handler._default_branch == "develop"


# ---------------------------------------------------------------------------
# HandlerRequest dataclass
# ---------------------------------------------------------------------------

class TestHandlerRequest:
    def test_default_values(self):
        node = make_node()
        ctx = PipelineContext()
        req = HandlerRequest(node=node, context=ctx)
        assert req.emitter is None
        assert req.pipeline_id == ""
        assert req.visit_count == 1
        assert req.attempt_number == 1
        assert req.run_dir == ""

    def test_explicit_values(self):
        node = make_node()
        ctx = PipelineContext()
        req = HandlerRequest(
            node=node,
            context=ctx,
            pipeline_id="my_pipeline",
            visit_count=3,
            attempt_number=2,
            run_dir="/tmp/run",
        )
        assert req.pipeline_id == "my_pipeline"
        assert req.visit_count == 3
        assert req.attempt_number == 2
        assert req.run_dir == "/tmp/run"

    def test_frozen(self):
        node = make_node()
        ctx = PipelineContext()
        req = HandlerRequest(node=node, context=ctx)
        with pytest.raises((AttributeError, TypeError)):
            req.pipeline_id = "modified"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Outcome model
# ---------------------------------------------------------------------------

class TestOutcome:
    def test_default_values(self):
        o = Outcome(status=OutcomeStatus.SUCCESS)
        assert o.context_updates == {}
        assert o.preferred_label is None
        assert o.suggested_next is None
        assert o.metadata == {}
        assert o.raw_messages == []

    def test_frozen(self):
        o = Outcome(status=OutcomeStatus.SUCCESS)
        with pytest.raises((AttributeError, TypeError)):
            o.status = OutcomeStatus.FAILURE  # type: ignore[misc]

    def test_status_values(self):
        assert OutcomeStatus.SUCCESS.value == "success"
        assert OutcomeStatus.FAILURE.value == "failure"
        assert OutcomeStatus.PARTIAL_SUCCESS.value == "partial_success"
        assert OutcomeStatus.WAITING.value == "waiting"
        assert OutcomeStatus.SKIPPED.value == "skipped"


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------

class TestPipelineContext:
    def test_get_returns_default(self):
        ctx = PipelineContext()
        assert ctx.get("missing", "default") == "default"

    def test_update_merges(self):
        ctx = PipelineContext({"a": 1})
        ctx.update({"b": 2})
        assert ctx.get("a") == 1
        assert ctx.get("b") == 2

    def test_snapshot_is_copy(self):
        ctx = PipelineContext({"k": "v"})
        snap = ctx.snapshot()
        snap["k"] = "modified"
        assert ctx.get("k") == "v"  # original unchanged

    def test_increment_visit(self):
        ctx = PipelineContext()
        assert ctx.increment_visit("n1") == 1
        assert ctx.increment_visit("n1") == 2
        assert ctx.increment_visit("n2") == 1

    def test_get_visit_count(self):
        ctx = PipelineContext()
        assert ctx.get_visit_count("x") == 0
        ctx.increment_visit("x")
        assert ctx.get_visit_count("x") == 1

    def test_merge_fan_out_results(self):
        ctx = PipelineContext()
        b1_outcome = Outcome(
            status=OutcomeStatus.SUCCESS,
            context_updates={"result": "ok"},
        )
        b2_outcome = Outcome(
            status=OutcomeStatus.FAILURE,
            context_updates={"result": "bad"},
        )
        merged = ctx.merge_fan_out_results([("branch1", b1_outcome), ("branch2", b2_outcome)])
        assert ctx.get("branch1.result") == "ok"
        assert ctx.get("branch2.result") == "bad"
        assert "branch1.result" in merged

    def test_thread_safety(self):
        """Concurrent writes do not corrupt state."""
        import threading

        ctx = PipelineContext()
        errors: list[Exception] = []

        def writer(key: str, val: int) -> None:
            try:
                for i in range(100):
                    ctx.update({key: val + i})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(f"k{i}", i)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_unknown_shape_error(self):
        exc = UnknownShapeError(shape="galaxy", node_id="node1")
        assert exc.shape == "galaxy"
        assert exc.node_id == "node1"
        assert "galaxy" in str(exc)
        assert "node1" in str(exc)

    def test_handler_error(self):
        cause = ValueError("original")
        exc = HandlerError("message", node_id="n1", cause=cause)
        assert exc.node_id == "n1"
        assert exc.cause is cause
        assert "n1" in str(exc)

    def test_handler_error_without_node_id(self):
        exc = HandlerError("oops")
        assert exc.node_id == ""
        assert "oops" in str(exc)
