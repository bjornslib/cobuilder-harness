"""E2E test: Run simple-pipeline.dot through the full engine with mock codergen.

Exercises all 5 implemented epics:
- E1: DOT parser + graph model + handler dispatch + edge selector + checkpoint
- E2: 13-rule validator (pre-run)
- E3: Condition expression evaluation (edges without conditions = unconditional)
- E4: Event bus (JSONL + NullEmitter)
- E5: Loop detection (visit counter, no loops in linear pipeline)

The codergen handler is injected with a mock spawner that returns SUCCESS
immediately, so no real orchestrator is spawned.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cobuilder.engine.events.emitter import EventBusConfig
from cobuilder.engine.handlers.codergen import CodergenHandler
from cobuilder.engine.handlers.registry import HandlerRegistry
from cobuilder.engine.parser import parse_dot_file
from cobuilder.engine.runner import EngineRunner

SIMPLE_PIPELINE = Path(__file__).resolve().parents[2] / ".claude" / "attractor" / "examples" / "simple-pipeline.dot"


async def _mock_spawner(node_id: str, prd: str, repo_root: str, **kwargs) -> dict:
    """Mock spawner that completes immediately with SUCCESS."""
    return {"exit_code": 0, "node_id": node_id}


async def _mock_signal_poller(target_layer: str, timeout: float, signals_dir: str, poll_interval: float) -> dict:
    """Mock signal poller that returns success immediately."""
    return {
        "signal_type": "complete",
        "node_id": "impl_task",
        "status": "success",
    }


def _build_test_registry() -> HandlerRegistry:
    """Build handler registry with mock codergen that completes instantly."""
    from cobuilder.engine.handlers.conditional import ConditionalHandler
    from cobuilder.engine.handlers.exit import ExitHandler
    from cobuilder.engine.handlers.fan_in import FanInHandler
    from cobuilder.engine.handlers.manager_loop import ManagerLoopHandler
    from cobuilder.engine.handlers.parallel import ParallelHandler
    from cobuilder.engine.handlers.start import StartHandler
    from cobuilder.engine.handlers.tool import ToolHandler
    from cobuilder.engine.handlers.wait_human import WaitHumanHandler

    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    # Inject mock spawner + signal poller into CodergenHandler
    registry.register(
        "box",
        CodergenHandler(
            spawner=_mock_spawner,
            signal_poller=_mock_signal_poller,
            timeout_s=10,
            poll_interval_s=0.1,
        ),
    )
    registry.register("diamond", ConditionalHandler())
    registry.register("hexagon", WaitHumanHandler())
    registry.register("component", ParallelHandler())
    registry.register("tripleoctagon", FanInHandler())
    registry.register("parallelogram", ToolHandler())
    registry.register("house", ManagerLoopHandler())
    return registry


class TestSimplePipelineE2E:
    """End-to-end tests for simple-pipeline.dot through the full engine."""

    def test_pipeline_file_exists(self):
        """Verify the test fixture exists."""
        assert SIMPLE_PIPELINE.exists(), f"Missing: {SIMPLE_PIPELINE}"

    def test_parse_and_validate(self):
        """E1+E2: Parse DOT file and run 13-rule validator."""
        # E1: Parse DOT file directly
        graph = parse_dot_file(str(SIMPLE_PIPELINE))

        # Verify graph structure
        assert graph is not None
        assert len(graph.nodes) == 3
        assert graph.prd_ref == "PRD-EXAMPLE-001"

        # Check node IDs
        node_ids = set(graph.nodes.keys())
        assert node_ids == {"start", "impl_task", "finalize"}

        # E2: Run validator (should pass without errors)
        from cobuilder.engine.validation.validator import Validator
        Validator(graph).run_or_raise()  # Should not raise

    def test_full_pipeline_run(self, tmp_path):
        """E1-E5: Full pipeline execution with mock codergen handler."""
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        events_file = tmp_path / "events.jsonl"

        runner = EngineRunner(
            dot_path=str(SIMPLE_PIPELINE),
            run_dir=str(run_dir),
            handler_registry=_build_test_registry(),
            event_bus_config=EventBusConfig(
                logfire_enabled=False,
                signal_bridge_enabled=False,
                jsonl_path=str(events_file),
            ),
        )

        checkpoint = asyncio.run(runner.run())

        # Verify pipeline completed
        assert checkpoint is not None
        # Pipeline is done when completed_nodes contains at least start + impl_task
        assert len(checkpoint.completed_nodes) >= 2, f"Expected >= 2 completed nodes, got {checkpoint.completed_nodes}"
        assert "start" in checkpoint.completed_nodes
        assert "impl_task" in checkpoint.completed_nodes

        # Verify run dir still exists
        assert run_dir.exists()

    def test_events_emitted(self, tmp_path):
        """E4: Verify JSONL events are emitted during pipeline run."""
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True, exist_ok=True)
        events_file = tmp_path / "events.jsonl"

        runner = EngineRunner(
            dot_path=str(SIMPLE_PIPELINE),
            run_dir=str(run_dir),
            handler_registry=_build_test_registry(),
            event_bus_config=EventBusConfig(
                logfire_enabled=False,
                signal_bridge_enabled=False,
                jsonl_path=str(events_file),
            ),
        )

        asyncio.run(runner.run())

        # Verify JSONL file was written with events
        assert events_file.exists(), "JSONL events file should exist"
        lines = events_file.read_text().strip().split("\n")
        assert len(lines) >= 3, f"Expected at least 3 events, got {len(lines)}"

        # Verify each line is valid JSON
        for i, line in enumerate(lines):
            event = json.loads(line)
            assert "event_type" in event or "type" in event, f"Line {i} missing event type: {line}"

    def test_checkpoint_saved(self, tmp_path):
        """E1: Verify checkpoint is saved after pipeline run."""
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True, exist_ok=True)

        runner = EngineRunner(
            dot_path=str(SIMPLE_PIPELINE),
            run_dir=str(run_dir),
            handler_registry=_build_test_registry(),
            event_bus_config=EventBusConfig(
                logfire_enabled=False,
                signal_bridge_enabled=False,
            ),
        )

        checkpoint = asyncio.run(runner.run())

        # Check checkpoint file exists in run directory
        checkpoint_files = list(run_dir.rglob("checkpoint*.json"))
        assert len(checkpoint_files) >= 1, "Expected at least one checkpoint file"

    def test_no_loop_detection_on_linear_pipeline(self, tmp_path):
        """E5: Linear pipeline should not trigger loop detection."""
        run_dir = tmp_path / "run"
        run_dir.mkdir(parents=True, exist_ok=True)

        runner = EngineRunner(
            dot_path=str(SIMPLE_PIPELINE),
            run_dir=str(run_dir),
            handler_registry=_build_test_registry(),
            max_node_visits=3,  # Low threshold — should still pass for linear
            event_bus_config=EventBusConfig(
                logfire_enabled=False,
                signal_bridge_enabled=False,
            ),
        )

        # Should complete without LoopDetectedError
        checkpoint = asyncio.run(runner.run())
        assert checkpoint is not None
