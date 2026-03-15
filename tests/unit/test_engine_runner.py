"""Tests for cobuilder.engine.runner — EngineRunner execution loop.

Coverage targets (from SD E1.3 acceptance criteria):
- runner.py  ≥ 85%

Test structure:
- Unit tests use a synthetic DOT string (no file I/O beyond tmp_path).
- HandlerRegistry is injected with mock handlers to avoid real I/O.
- Checkpoints are written to tmp_path so tests are hermetic.

Async tests use pytest-asyncio with @pytest.mark.asyncio.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cobuilder.engine.checkpoint import CheckpointManager, EngineCheckpoint
from cobuilder.engine.context import PipelineContext
from cobuilder.engine.exceptions import HandlerError, LoopDetectedError, NoEdgeError
from cobuilder.engine.graph import Node
from cobuilder.engine.handlers import HandlerRegistry
from cobuilder.engine.handlers.base import HandlerRequest
from cobuilder.engine.outcome import Outcome, OutcomeStatus
from cobuilder.engine.runner import EngineRunner


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_handler(status: OutcomeStatus = OutcomeStatus.SUCCESS, **kw) -> Any:
    """Return a mock handler that returns a fixed Outcome."""
    outcome = Outcome(status=status, **kw)
    h = MagicMock()
    h.execute = AsyncMock(return_value=outcome)
    return h


def _build_registry(*shape_pairs: tuple[str, Any]) -> HandlerRegistry:
    """Build a HandlerRegistry with injected mock handlers."""
    reg = HandlerRegistry()
    for shape, handler in shape_pairs:
        reg.register(shape, handler)
    return reg


def _write_dot(tmp_path: Path, content: str, name: str = "pipeline") -> Path:
    """Write a DOT file to *tmp_path* and return its path."""
    p = tmp_path / f"{name}.dot"
    p.write_text(content, encoding="utf-8")
    return p


# ── Minimal valid DOT files ────────────────────────────────────────────────────

# 3-node pipeline: start → work → exit
_DOT_3NODE = """
digraph pipeline {
    start [shape=Mdiamond];
    work  [shape=box];
    done  [shape=Msquare];
    start -> work;
    work  -> done;
}
"""

# 2-node: start directly to exit
_DOT_2NODE = """
digraph pipeline {
    s [shape=Mdiamond];
    e [shape=Msquare];
    s -> e;
}
"""

# Loop pipeline: start → loop_body → loop_body (self-loop for loop detection)
_DOT_LOOP = """
digraph pipeline {
    s    [shape=Mdiamond];
    body [shape=box];
    done [shape=Msquare];
    s    -> body;
    body -> body;
    body -> done [label=exit];
}
"""


# ──────────────────────────────────────────────────────────────────────────────
# TestEngineRunnerFreshRun
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineRunnerFreshRun:
    """Tests for a fresh (non-resume) pipeline run."""

    @pytest.mark.asyncio
    async def test_completes_3node_pipeline(self, tmp_path: Path) -> None:
        """3-node pipeline runs start→work→exit and returns a checkpoint."""
        dot_file = _write_dot(tmp_path, _DOT_3NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_3NODE lacks sd_path and wait.cobuilder
        )
        checkpoint = await runner.run()

        assert checkpoint.pipeline_id == "pipeline"
        assert checkpoint.completed_nodes == ["start", "work", "done"]
        assert checkpoint.total_node_executions == 3

    @pytest.mark.asyncio
    async def test_completes_2node_pipeline(self, tmp_path: Path) -> None:
        """Minimal start-to-exit pipeline works."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_2NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()
        assert checkpoint.completed_nodes == ["s", "e"]
        assert checkpoint.total_node_executions == 2

    @pytest.mark.asyncio
    async def test_run_dir_is_created(self, tmp_path: Path) -> None:
        """A run directory is created under pipelines_dir."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        runs_dir = tmp_path / "runs"
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=runs_dir,
            handler_registry=registry,
            skip_validation=True,  # _DOT_2NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()

        run_dir = Path(checkpoint.run_dir)
        assert run_dir.exists()
        assert run_dir.parent == runs_dir
        assert (run_dir / "checkpoint.json").exists()

    @pytest.mark.asyncio
    async def test_checkpoint_json_is_written(self, tmp_path: Path) -> None:
        """checkpoint.json is present and parseable after completion."""
        import json

        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_2NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()

        raw = (Path(checkpoint.run_dir) / "checkpoint.json").read_text()
        data = json.loads(raw)
        assert data["pipeline_id"] == "pipeline"
        assert data["schema_version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_context_updates_applied(self, tmp_path: Path) -> None:
        """context_updates from a handler are visible in the final checkpoint."""
        dot_file = _write_dot(tmp_path, _DOT_3NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS, context_updates={"my_key": "hello"})),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()
        assert checkpoint.context.get("my_key") == "hello"

    @pytest.mark.asyncio
    async def test_last_status_in_context(self, tmp_path: Path) -> None:
        """$last_status is updated after each node."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_2NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()
        assert checkpoint.context.get("$last_status") == "success"

    @pytest.mark.asyncio
    async def test_node_records_populated(self, tmp_path: Path) -> None:
        """node_records contains one entry per completed node."""
        dot_file = _write_dot(tmp_path, _DOT_3NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()

        assert len(checkpoint.node_records) == 3
        record_ids = [r.node_id for r in checkpoint.node_records]
        assert record_ids == ["start", "work", "done"]

    @pytest.mark.asyncio
    async def test_initial_context_injected(self, tmp_path: Path) -> None:
        """initial_context values are visible to handlers via PipelineContext."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)

        captured: dict = {}

        async def _capture(request: HandlerRequest) -> Outcome:
            captured["ctx"] = request.context.snapshot()
            return Outcome(status=OutcomeStatus.SKIPPED)

        async def _exit(request: HandlerRequest) -> Outcome:
            return Outcome(status=OutcomeStatus.SUCCESS)

        start_h = MagicMock()
        start_h.execute = AsyncMock(side_effect=_capture)
        exit_h = MagicMock()
        exit_h.execute = AsyncMock(side_effect=_exit)

        registry = _build_registry(("Mdiamond", start_h), ("Msquare", exit_h))
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            initial_context={"seed_key": "seed_val"},
            skip_validation=True,  # _DOT_2NODE lacks Epic 2 requirements
        )
        await runner.run()
        assert captured["ctx"]["seed_key"] == "seed_val"

    @pytest.mark.asyncio
    async def test_tokens_used_aggregated(self, tmp_path: Path) -> None:
        """total_tokens_used is summed from outcome.metadata['tokens_used']."""
        dot_file = _write_dot(tmp_path, _DOT_3NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS, metadata={"tokens_used": 42})),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS, metadata={"tokens_used": 8})),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()
        assert checkpoint.total_tokens_used == 50

    @pytest.mark.asyncio
    async def test_visit_counts_in_checkpoint(self, tmp_path: Path) -> None:
        """visit_counts mirrors $node_visits.* from context."""
        dot_file = _write_dot(tmp_path, _DOT_3NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()
        assert checkpoint.visit_counts == {"start": 1, "work": 1, "done": 1}


# ──────────────────────────────────────────────────────────────────────────────
# TestEngineRunnerResume
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineRunnerResume:
    """Tests for resume (--resume) behaviour."""

    @pytest.mark.asyncio
    async def test_resume_skips_completed_nodes(self, tmp_path: Path) -> None:
        """On resume, nodes in completed_nodes are not re-executed."""
        dot_file = _write_dot(tmp_path, _DOT_3NODE, name="pipeline")

        start_h = MagicMock()
        start_h.execute = AsyncMock(return_value=Outcome(status=OutcomeStatus.SKIPPED))
        work_h = MagicMock()
        work_h.execute = AsyncMock(return_value=Outcome(status=OutcomeStatus.SUCCESS))
        exit_h = MagicMock()
        exit_h.execute = AsyncMock(return_value=Outcome(status=OutcomeStatus.SUCCESS))

        # Run once to get run_dir.
        registry = _build_registry(
            ("Mdiamond", start_h),
            ("box", work_h),
            ("Msquare", exit_h),
        )
        runner1 = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        checkpoint1 = await runner1.run()
        run_dir = checkpoint1.run_dir
        total_calls_first_run = work_h.execute.call_count

        # Resume from the completed run — nothing should be re-executed.
        work_h2 = MagicMock()
        work_h2.execute = AsyncMock(return_value=Outcome(status=OutcomeStatus.SUCCESS))

        # Tamper: write a checkpoint that says only 'start' is completed
        # (simulates crash after start but before work).
        from cobuilder.engine.checkpoint import ENGINE_CHECKPOINT_VERSION

        import json
        cp_path = Path(run_dir) / "checkpoint.json"
        cp_data = json.loads(cp_path.read_text())
        cp_data["completed_nodes"] = ["start"]
        cp_data["current_node_id"] = "work"
        cp_data["node_records"] = [r for r in cp_data["node_records"] if r["node_id"] == "start"]
        cp_path.write_text(json.dumps(cp_data, indent=2))

        registry2 = _build_registry(
            ("Mdiamond", start_h),
            ("box", work_h2),
            ("Msquare", exit_h),
        )
        runner2 = EngineRunner(
            dot_path=dot_file,
            run_dir=run_dir,
            handler_registry=registry2,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        checkpoint2 = await runner2.run()

        # work node should execute exactly once in resume run
        assert work_h2.execute.call_count == 1
        assert "work" in checkpoint2.completed_nodes
        assert "done" in checkpoint2.completed_nodes

    @pytest.mark.asyncio
    async def test_resume_restores_context(self, tmp_path: Path) -> None:
        """Context accumulated before crash is restored on resume."""
        import json

        dot_file = _write_dot(tmp_path, _DOT_3NODE, name="pipeline")

        # First run: inject context in work handler
        work_h = _make_handler(
            OutcomeStatus.SUCCESS, context_updates={"persisted": "value"}
        )
        registry1 = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", work_h),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner1 = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry1,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        checkpoint1 = await runner1.run()
        run_dir = checkpoint1.run_dir

        # Simulate crash: set completed_nodes to start+work but NOT done.
        cp_path = Path(run_dir) / "checkpoint.json"
        cp_data = json.loads(cp_path.read_text())
        cp_data["completed_nodes"] = ["start", "work"]
        cp_data["current_node_id"] = "done"
        cp_data["node_records"] = [r for r in cp_data["node_records"] if r["node_id"] != "done"]
        cp_path.write_text(json.dumps(cp_data, indent=2))

        # On resume, the exit handler should see the persisted context key.
        captured_ctx: dict = {}

        async def _capture_exit(request: HandlerRequest) -> Outcome:
            captured_ctx.update(request.context.snapshot())
            return Outcome(status=OutcomeStatus.SUCCESS)

        exit_h2 = MagicMock()
        exit_h2.execute = AsyncMock(side_effect=_capture_exit)

        registry2 = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", work_h),
            ("Msquare", exit_h2),
        )
        runner2 = EngineRunner(
            dot_path=dot_file,
            run_dir=run_dir,
            handler_registry=registry2,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        await runner2.run()
        assert captured_ctx.get("persisted") == "value"


# ──────────────────────────────────────────────────────────────────────────────
# TestEngineRunnerErrorHandling
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineRunnerErrorHandling:
    """Tests for error conditions: loops, missing edges, handler errors."""

    @pytest.mark.asyncio
    async def test_loop_detected_error(self, tmp_path: Path) -> None:
        """LoopDetectedError is raised when a node is visited > max_node_visits."""
        # Use a self-loop: body -> body always (condition=false on exit edge)
        dot_loop = """
digraph pipeline {
    s    [shape=Mdiamond];
    body [shape=box];
    done [shape=Msquare];
    s    -> body;
    body -> body [condition="false"];
    body -> done [condition="false"];
}
"""
        dot_file = _write_dot(tmp_path, dot_loop)
        # The edge selector will pick the first edge (body→body) because
        # both conditions evaluate to false and it falls through to Step 5 (first outgoing).
        # We expect LoopDetectedError with max_node_visits=3.
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            max_node_visits=3,
            skip_validation=True,  # condition="false" is not valid syntax; test is for loop detection
        )
        with pytest.raises(LoopDetectedError) as exc_info:
            await runner.run()
        assert exc_info.value.node_id == "body"
        assert exc_info.value.max_retries == 3

    @pytest.mark.asyncio
    async def test_no_edge_error_for_non_exit_node(self, tmp_path: Path) -> None:
        """NoEdgeError is raised when a non-exit node has no outgoing edges."""
        # Create a DOT with a dangling box node (no outgoing edge)
        dot_dangling = """
digraph pipeline {
    s    [shape=Mdiamond];
    work [shape=box];
    done [shape=Msquare];
    s -> work;
}
"""
        dot_file = _write_dot(tmp_path, dot_dangling)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # bypass Epic 2 validator; this test targets NoEdgeError
        )
        with pytest.raises(NoEdgeError) as exc_info:
            await runner.run()
        assert exc_info.value.node_id == "work"

    @pytest.mark.asyncio
    async def test_handler_error_propagates(self, tmp_path: Path) -> None:
        """HandlerError from a handler propagates out of runner.run()."""
        dot_file = _write_dot(tmp_path, _DOT_3NODE)

        async def _fail(request: HandlerRequest) -> Outcome:
            raise HandlerError("deliberate failure", node_id=request.node.id)

        failing_work_h = MagicMock()
        failing_work_h.execute = AsyncMock(side_effect=_fail)

        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", failing_work_h),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
        )
        with pytest.raises(HandlerError) as exc_info:
            await runner.run()
        assert "deliberate failure" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError is raised for a missing DOT file."""
        runner = EngineRunner(
            dot_path=tmp_path / "nonexistent.dot",
            pipelines_dir=tmp_path / "runs",
        )
        with pytest.raises(FileNotFoundError):
            await runner.run()

    @pytest.mark.asyncio
    async def test_default_max_visits_is_10(self, tmp_path: Path) -> None:
        """Default max_node_visits is 10."""
        runner = EngineRunner(
            dot_path=tmp_path / "dummy.dot",
            pipelines_dir=tmp_path / "runs",
        )
        assert runner.max_node_visits == 10


# ──────────────────────────────────────────────────────────────────────────────
# TestEngineRunnerCheckpointIntegration
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineRunnerCheckpointIntegration:
    """Tests verifying checkpoint save semantics during the traversal loop."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_before_and_after_node(self, tmp_path: Path) -> None:
        """Checkpoint is written before execution (current_node_id set) and after."""
        import json

        dot_file = _write_dot(tmp_path, _DOT_3NODE)

        saved_states: list[dict] = []

        original_save = CheckpointManager.save

        def _spy_save(self_mgr, checkpoint, **kwargs):
            original_save(self_mgr, checkpoint, **kwargs)
            raw = (self_mgr.checkpoint_path).read_text()
            saved_states.append(json.loads(raw))

        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("box", _make_handler(OutcomeStatus.SUCCESS)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )

        with patch.object(CheckpointManager, "save", _spy_save):
            runner = EngineRunner(
                dot_path=dot_file,
                pipelines_dir=tmp_path / "runs",
                handler_registry=registry,
                skip_validation=True,  # _DOT_3NODE lacks Epic 2 requirements
            )
            await runner.run()

        # Should have at least 6 saves: pre+post for each of 3 nodes.
        assert len(saved_states) >= 6

        # Pre-execute saves: current_node_id set but node NOT yet in completed_nodes.
        pre_saves = [
            s for s in saved_states
            if s["current_node_id"] is not None
            and s["current_node_id"] not in s["completed_nodes"]
        ]
        assert len(pre_saves) >= 1  # At least the start node

    @pytest.mark.asyncio
    async def test_checkpoint_context_excludes_graph_object(self, tmp_path: Path) -> None:
        """$graph (non-serializable) is excluded from checkpoint.context."""
        import json

        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # _DOT_2NODE lacks Epic 2 requirements
        )
        checkpoint = await runner.run()

        # Verify JSON doesn't contain "$graph" (would fail to serialize if present)
        raw = (Path(checkpoint.run_dir) / "checkpoint.json").read_text()
        data = json.loads(raw)
        assert "$graph" not in data.get("context", {})


# ──────────────────────────────────────────────────────────────────────────────
# TestEngineRunnerPreferredLabelRouting
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineRunnerPreferredLabelRouting:
    """Tests verifying edge selection integration with outcome.preferred_label."""

    @pytest.mark.asyncio
    async def test_preferred_label_routes_to_correct_branch(self, tmp_path: Path) -> None:
        """outcome.preferred_label routes to the matching edge label."""
        dot_branching = """
digraph pipeline {
    s      [shape=Mdiamond];
    gate   [shape=diamond];
    pass_n [shape=box; label="pass"];
    fail_n [shape=box; label="fail"];
    done   [shape=Msquare];
    s      -> gate;
    gate   -> pass_n [label=pass];
    gate   -> fail_n [label=fail];
    pass_n -> done;
    fail_n -> done;
}
"""
        dot_file = _write_dot(tmp_path, dot_branching)

        visited_nodes: list[str] = []

        async def _tracking(request: HandlerRequest) -> Outcome:
            visited_nodes.append(request.node.id)
            if request.node.id == "gate":
                return Outcome(status=OutcomeStatus.SUCCESS, preferred_label="pass")
            return Outcome(status=OutcomeStatus.SUCCESS)

        async def _skipped(request: HandlerRequest) -> Outcome:
            visited_nodes.append(request.node.id)
            return Outcome(status=OutcomeStatus.SKIPPED)

        start_h = MagicMock()
        start_h.execute = AsyncMock(side_effect=_skipped)
        gate_h = MagicMock()
        gate_h.execute = AsyncMock(side_effect=_tracking)
        box_h = MagicMock()
        box_h.execute = AsyncMock(side_effect=_tracking)
        exit_h = MagicMock()
        exit_h.execute = AsyncMock(side_effect=_tracking)

        registry = _build_registry(
            ("Mdiamond", start_h),
            ("diamond", gate_h),
            ("box", box_h),
            ("Msquare", exit_h),
        )
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,  # Branching DOT lacks Epic 2 requirements
        )
        await runner.run()

        assert "pass_n" in visited_nodes
        assert "fail_n" not in visited_nodes


# ──────────────────────────────────────────────────────────────────────────────
# TestEngineRunnerHelpers
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineRunnerHelpers:
    """Tests for static helper methods."""

    def test_serializable_context_excludes_graph(self) -> None:
        """_serializable_context strips $graph."""
        from cobuilder.engine.runner import EngineRunner as ER
        from cobuilder.engine.graph import Graph, Node

        ctx = PipelineContext(initial={
            "$graph": object(),  # non-serializable sentinel
            "custom_key": "value",
            "$last_status": "success",
        })
        result = ER._serializable_context(ctx)
        assert "$graph" not in result
        assert result["custom_key"] == "value"
        assert result["$last_status"] == "success"

    def test_extract_visit_counts(self) -> None:
        """_extract_visit_counts returns {node_id: count} dict."""
        from cobuilder.engine.runner import EngineRunner as ER

        ctx = PipelineContext(initial={
            "$node_visits.alpha": 2,
            "$node_visits.beta": 1,
            "other_key": "ignored",
        })
        result = ER._extract_visit_counts(ctx)
        assert result == {"alpha": 2, "beta": 1}
        assert "other_key" not in result

    def test_resolve_start_node_fresh_run(self, tmp_path: Path) -> None:
        """_resolve_start_node returns start_node when checkpoint is empty."""
        import json

        from cobuilder.engine.parser import parse_dot_string
        from cobuilder.engine.runner import EngineRunner as ER
        from cobuilder.engine.checkpoint import EngineCheckpoint, ENGINE_CHECKPOINT_VERSION

        graph = parse_dot_string(_DOT_2NODE)
        now = datetime.now(timezone.utc)
        checkpoint = EngineCheckpoint(
            pipeline_id="test",
            dot_path="test.dot",
            run_dir=str(tmp_path),
            started_at=now,
            last_updated_at=now,
        )
        node = ER._resolve_start_node(graph, checkpoint)
        assert node.is_start

    def test_resolve_start_node_resume_in_progress(self, tmp_path: Path) -> None:
        """_resolve_start_node returns in-progress node on resume."""
        from cobuilder.engine.parser import parse_dot_string
        from cobuilder.engine.runner import EngineRunner as ER
        from cobuilder.engine.checkpoint import EngineCheckpoint

        graph = parse_dot_string(_DOT_3NODE)
        now = datetime.now(timezone.utc)
        # 'work' is current but not yet in completed_nodes (crash during execution)
        checkpoint = EngineCheckpoint(
            pipeline_id="test",
            dot_path="test.dot",
            run_dir=str(tmp_path),
            started_at=now,
            last_updated_at=now,
            completed_nodes=["start"],
            current_node_id="work",
        )
        node = ER._resolve_start_node(graph, checkpoint)
        assert node.id == "work"


# ──────────────────────────────────────────────────────────────────────────────
# TestEngineRunnerValidation
# ──────────────────────────────────────────────────────────────────────────────

class TestEngineRunnerValidation:
    """Tests for pre-execution validation wiring in EngineRunner."""

    @pytest.mark.asyncio
    async def test_validation_runs_before_execution(self, tmp_path: Path) -> None:
        """Epic 2 Validator raises ValidationError on invalid graphs before execution."""
        from cobuilder.engine.validation import ValidationError

        # A graph with no start node → SingleStartNode rule fires → ValidationError raised
        dot_no_start = """
digraph pipeline {
    impl [shape=box];
    done [shape=Msquare];
    impl -> done;
}
"""
        dot_file = _write_dot(tmp_path, dot_no_start)
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
        )
        with pytest.raises(ValidationError) as exc_info:
            await runner.run()

        # The ValidationError must carry a ValidationResult with errors
        assert exc_info.value.result is not None
        assert not exc_info.value.result.is_valid
        assert len(exc_info.value.result.errors) >= 1

    @pytest.mark.asyncio
    async def test_skip_validation_bypasses_validator(self, tmp_path: Path) -> None:
        """When skip_validation=True, Epic 2 Validator is not called."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )
        with patch("cobuilder.engine.validation.validator.Validator") as mock_validator:
            runner = EngineRunner(
                dot_path=dot_file,
                pipelines_dir=tmp_path / "runs",
                handler_registry=registry,
                skip_validation=True,
            )
            await runner.run()

        mock_validator.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_warnings_dont_block(self, tmp_path: Path) -> None:
        """Validation warnings are logged but do not prevent execution."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )

        # The actual valid graph (_DOT_2NODE) passes all rules but may produce
        # LlmNodesHavePrompts warnings (box node without prompt).
        # Execution must proceed regardless of warnings.
        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
        )
        checkpoint = await runner.run()

        assert checkpoint.pipeline_id == "pipeline"
        assert "e" in checkpoint.completed_nodes


# ──────────────────────────────────────────────────────────────────────────────
# TestHandlerErrorCrashSignal
# ──────────────────────────────────────────────────────────────────────────────

class TestHandlerErrorCrashSignal:
    """Verify that HandlerError triggers an ORCHESTRATOR_CRASHED signal file."""

    @pytest.mark.asyncio
    async def test_handler_error_writes_crash_signal(self, tmp_path: Path) -> None:
        """When a handler raises HandlerError, a crash signal file is written to run_dir."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)

        # Handler that raises HandlerError on execute
        crashing_handler = MagicMock()
        crashing_handler.execute = AsyncMock(
            side_effect=HandlerError("simulated crash")
        )
        registry = _build_registry(
            ("Mdiamond", crashing_handler),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,
        )

        # Patch write_signal to write into our signals_dir
        import cobuilder.engine.runner as runner_module
        from cobuilder.pipeline.signal_protocol import write_signal as real_write_signal

        written_paths: list[str] = []

        def _capturing_write_signal(source, target, signal_type, payload, signals_dir=None):
            path = real_write_signal(
                source=source,
                target=target,
                signal_type=signal_type,
                payload=payload,
                signals_dir=str(tmp_path / "signals"),
            )
            written_paths.append(path)
            return path

        with patch.object(runner_module, "write_signal", side_effect=_capturing_write_signal):
            with patch.object(runner_module, "_SIGNAL_PROTOCOL_AVAILABLE", True):
                with pytest.raises(HandlerError):
                    await runner.run()

        # Assert that at least one signal file matching *ORCHESTRATOR_CRASHED* was written
        crash_signals = list((tmp_path / "signals").glob("*ORCHESTRATOR_CRASHED*"))
        assert len(crash_signals) >= 1, (
            f"Expected at least one ORCHESTRATOR_CRASHED signal file in {tmp_path / 'signals'}, "
            f"but found none. Written paths: {written_paths}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# TestLogfireSpans
# ──────────────────────────────────────────────────────────────────────────────

class TestLogfireSpans:
    """Verify that direct logfire spans are created in runner._run_loop."""

    @pytest.mark.asyncio
    async def test_logfire_spans_created(self, tmp_path: Path) -> None:
        """Running a 2-node pipeline creates pipeline.run and node.execute logfire spans."""
        dot_file = _write_dot(tmp_path, _DOT_2NODE)
        registry = _build_registry(
            ("Mdiamond", _make_handler(OutcomeStatus.SKIPPED)),
            ("Msquare", _make_handler(OutcomeStatus.SUCCESS)),
        )

        runner = EngineRunner(
            dot_path=dot_file,
            pipelines_dir=tmp_path / "runs",
            handler_registry=registry,
            skip_validation=True,
        )

        import cobuilder.engine.runner as runner_module

        span_calls: list[tuple] = []

        class _MockSpanCtx:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def _mock_span(name, **kwargs):
            span_calls.append((name, kwargs))
            return _MockSpanCtx()

        mock_logfire = MagicMock()
        mock_logfire.span = MagicMock(side_effect=_mock_span)

        with patch.object(runner_module, "_logfire", mock_logfire):
            with patch.object(runner_module, "_LOGFIRE_AVAILABLE", True):
                await runner.run()

        span_names = [c[0] for c in span_calls]
        assert "pipeline.run" in span_names, (
            f"Expected 'pipeline.run' span but got: {span_names}"
        )
        assert "node.execute" in span_names, (
            f"Expected 'node.execute' span but got: {span_names}"
        )
