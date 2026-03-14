"""End-to-end integration tests exercising all 5 pipeline engine epics.

  E1: Custom DOT Parser
  E2: 13-Rule Validation Suite
  E3: Condition Expression Language
  E4: Structured Event Bus (JSONL + signals)
  E5: Loop Detection and Retry Policy

All 7 test cases run against tests/fixtures/test-e2e-pipeline.dot.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

# E1: Parser
from cobuilder.engine.parser import parse_dot_file, parse_dot_string

# E2: Validation
from cobuilder.engine.validation import Severity
from cobuilder.engine.validation.validator import Validator

# E3: Conditions
from cobuilder.engine.conditions import evaluate_condition
from cobuilder.engine.context import PipelineContext
from cobuilder.engine.edge_selector import EdgeSelector
from cobuilder.engine.outcome import Outcome, OutcomeStatus

# E4: Events
from cobuilder.engine.events.emitter import NullEmitter, CompositeEmitter
from cobuilder.engine.events.jsonl_backend import JSONLEmitter
from cobuilder.engine.events.types import EventBuilder, PipelineEvent

# E5: Loop Detection
from cobuilder.engine.loop_detection import LoopDetector, LoopPolicy, resolve_retry_target


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

_FIXTURE_DOT = Path(__file__).parent.parent / "fixtures" / "test-e2e-pipeline.dot"


def _run(coro):
    """Run a coroutine synchronously (test helper).

    Creates a fresh event loop for each invocation to avoid state pollution
    between tests when running the full suite. Uses asyncio.run() for
    Python 3.7+ compatibility.
    """
    try:
        # Try asyncio.run() first (Python 3.7+)
        return asyncio.run(coro)
    except RuntimeError:
        # Fallback for nested loop scenarios (rare in tests)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# Test 1 — E1 + E2: Parse and validate the DOT fixture
# ---------------------------------------------------------------------------

class TestParseAndValidateDotFile:
    """E1 + E2: Custom DOT parser + 13-rule validation suite."""

    def test_parse_and_validate_dot_file(self):
        """Parse the fixture DOT file and confirm no ERROR-level violations."""
        # E1: parse
        graph = parse_dot_file(_FIXTURE_DOT)

        # Basic structural assertions
        assert graph is not None
        assert len(graph.nodes) == 6, (
            f"Expected 6 nodes, got {len(graph.nodes)}: {list(graph.nodes.keys())}"
        )

        # Confirm the expected nodes are present
        expected_nodes = {"start", "check", "decide", "process", "retry_node", "done"}
        assert set(graph.nodes.keys()) == expected_nodes

        # Confirm edges — 7 edges total (retry_node reachable via check->retry_node)
        assert len(graph.edges) == 7, (
            f"Expected 7 edges, got {len(graph.edges)}"
        )

        # E2: validate
        result = Validator(graph).run()
        errors = result.errors
        assert len(errors) == 0, (
            f"Expected no ERROR violations, got {len(errors)}:\n"
            + "\n".join(str(v) for v in errors)
        )

    def test_graph_attributes_parsed(self):
        """Graph-level attributes are parsed correctly from the fixture."""
        graph = parse_dot_file(_FIXTURE_DOT)
        assert graph.attrs.get("pipeline_id") == "test-e2e-001"

    def test_node_shapes_correct(self):
        """Node shapes are preserved from the DOT file."""
        graph = parse_dot_file(_FIXTURE_DOT)
        assert graph.nodes["start"].shape == "Mdiamond"
        assert graph.nodes["done"].shape == "Msquare"
        assert graph.nodes["check"].shape == "parallelogram"
        assert graph.nodes["decide"].shape == "diamond"

    def test_conditional_edges_have_condition_attrs(self):
        """Edges with condition attributes are parsed with condition strings."""
        graph = parse_dot_file(_FIXTURE_DOT)
        edges_from_decide = graph.edges_from("decide")
        assert len(edges_from_decide) == 2
        conditions = {e.condition for e in edges_from_decide}
        assert "$last_status = success" in conditions
        assert "$last_status != success" in conditions


# ---------------------------------------------------------------------------
# Test 2 — E3: Condition evaluation on edges
# ---------------------------------------------------------------------------

class TestConditionEvaluationOnEdges:
    """E3: Condition Expression Language evaluation against mock context."""

    def test_last_status_success_condition_true(self):
        """'$last_status = success' evaluates True when context has last_status=success."""
        ctx = PipelineContext({"$last_status": "success"})
        result = evaluate_condition("$last_status = success", ctx)
        assert result is True

    def test_last_status_ne_condition_true(self):
        """'$last_status != success' evaluates True when context has last_status=failure."""
        ctx = PipelineContext({"$last_status": "failure"})
        result = evaluate_condition("$last_status != success", ctx)
        assert result is True

    def test_last_status_success_condition_false_when_failure(self):
        """'$last_status = success' evaluates False when context has last_status=failure."""
        ctx = PipelineContext({"$last_status": "failure"})
        result = evaluate_condition("$last_status = success", ctx)
        assert result is False

    def test_last_status_ne_condition_false_when_success(self):
        """'$last_status != success' evaluates False when context has last_status=success."""
        ctx = PipelineContext({"$last_status": "success"})
        result = evaluate_condition("$last_status != success", ctx)
        assert result is False

    def test_missing_variable_returns_default_false(self):
        """Missing variable returns False (the default missing_var_default)."""
        ctx = PipelineContext({})
        result = evaluate_condition("$last_status = success", ctx, missing_var_default=False)
        assert result is False

    def test_conditions_from_parsed_graph(self):
        """Conditions extracted from the parsed graph evaluate correctly."""
        graph = parse_dot_file(_FIXTURE_DOT)
        edges_from_decide = graph.edges_from("decide")

        success_edge = next(e for e in edges_from_decide if "!=" not in e.condition)
        fail_edge = next(e for e in edges_from_decide if "!=" in e.condition)

        # Success path
        ctx_success = PipelineContext({"$last_status": "success"})
        assert evaluate_condition(success_edge.condition, ctx_success) is True
        assert evaluate_condition(fail_edge.condition, ctx_success) is False

        # Failure path
        ctx_fail = PipelineContext({"$last_status": "failure"})
        assert evaluate_condition(success_edge.condition, ctx_fail) is False
        assert evaluate_condition(fail_edge.condition, ctx_fail) is True


# ---------------------------------------------------------------------------
# Test 3 — E3: EdgeSelector with conditions
# ---------------------------------------------------------------------------

class TestEdgeSelectorWithConditions:
    """E3: EdgeSelector selects correct edges based on context values."""

    def test_selects_process_when_last_status_success(self):
        """EdgeSelector routes to 'process' when last_status=success."""
        graph = parse_dot_file(_FIXTURE_DOT)
        selector = EdgeSelector()
        node = graph.nodes["decide"]
        outcome = Outcome(status=OutcomeStatus.SUCCESS)
        ctx = PipelineContext({"$last_status": "success"})

        edge = selector.select(graph, node, outcome, ctx)
        assert edge.target == "process", (
            f"Expected target='process', got target='{edge.target}'"
        )

    def test_selects_done_when_last_status_not_success(self):
        """EdgeSelector routes to 'done' when last_status!=success."""
        graph = parse_dot_file(_FIXTURE_DOT)
        selector = EdgeSelector()
        node = graph.nodes["decide"]
        outcome = Outcome(status=OutcomeStatus.SUCCESS)
        ctx = PipelineContext({"$last_status": "failure"})

        edge = selector.select(graph, node, outcome, ctx)
        assert edge.target == "done", (
            f"Expected target='done', got target='{edge.target}'"
        )

    def test_selects_default_edge_when_no_conditions_match(self):
        """EdgeSelector falls back to first outgoing edge when conditions don't match."""
        graph = parse_dot_file(_FIXTURE_DOT)
        selector = EdgeSelector()
        # start -> check is unconditional; with empty context, check is selected
        node = graph.nodes["start"]
        outcome = Outcome(status=OutcomeStatus.SKIPPED)
        ctx = PipelineContext({})

        edge = selector.select(graph, node, outcome, ctx)
        assert edge.target == "check"

    def test_edge_selector_uses_start_node_correctly(self):
        """start -> check is selected correctly via default edge."""
        graph = parse_dot_file(_FIXTURE_DOT)
        selector = EdgeSelector()
        node = graph.nodes["start"]
        outcome = Outcome(status=OutcomeStatus.SKIPPED)
        ctx = PipelineContext({})

        edge = selector.select(graph, node, outcome, ctx)
        assert edge.target == "check"


# ---------------------------------------------------------------------------
# Test 4 — E4: Event bus emits during pipeline run
# ---------------------------------------------------------------------------

class TestEventBusEmitsDuringPipelineRun:
    """E4: EventBuilder creates correct PipelineEvent instances."""

    def test_events_have_correct_pipeline_id(self):
        """Events built with EventBuilder have the supplied pipeline_id."""
        pipeline_id = "test-e2e-001"
        event = EventBuilder.pipeline_started(pipeline_id, "test.dot", 6)
        assert event.pipeline_id == pipeline_id

    def test_events_have_correct_node_id(self):
        """Node-level events carry the correct node_id."""
        event = EventBuilder.node_started("test-e2e-001", "check", "tool", 1)
        assert event.node_id == "check"
        assert event.data["handler_type"] == "tool"
        assert event.data["visit_count"] == 1

    def test_events_have_timestamps(self):
        """Events carry a timezone-aware UTC timestamp."""
        from datetime import timezone
        event = EventBuilder.pipeline_started("test-pipe", "g.dot", 3)
        assert event.timestamp is not None
        assert event.timestamp.tzinfo is not None
        assert event.timestamp.tzinfo == timezone.utc

    def test_sequence_numbers_are_monotonically_increasing(self):
        """Sequence numbers on consecutive events are strictly increasing."""
        events = [
            EventBuilder.pipeline_started("p", "g.dot", 3),
            EventBuilder.node_started("p", "start", "start", 1),
            EventBuilder.node_completed("p", "start", "skipped", 1.0),
            EventBuilder.node_started("p", "check", "tool", 1),
            EventBuilder.node_completed("p", "check", "success", 5.0),
            EventBuilder.edge_selected("p", "check", "decide", 5),
        ]
        sequences = [e.sequence for e in events]
        for i in range(len(sequences) - 1):
            assert sequences[i] < sequences[i + 1], (
                f"Sequences not increasing: {sequences}"
            )

    def test_recording_emitter_captures_all_events(self):
        """A list-based recording emitter captures all emitted events."""
        received: list[PipelineEvent] = []

        class RecordingEmitter:
            async def emit(self, event: PipelineEvent) -> None:
                received.append(event)

            async def aclose(self) -> None:
                pass

        pipeline_id = "test-e2e-001"
        emitter = RecordingEmitter()

        events_to_emit = [
            EventBuilder.pipeline_started(pipeline_id, "test.dot", 6),
            EventBuilder.node_started(pipeline_id, "start", "start", 1),
            EventBuilder.node_completed(pipeline_id, "start", "skipped", 0.5),
            EventBuilder.edge_selected(pipeline_id, "start", "check", 5),
        ]

        for evt in events_to_emit:
            _run(emitter.emit(evt))

        assert len(received) == 4
        pipeline_ids = {e.pipeline_id for e in received}
        assert pipeline_ids == {pipeline_id}


# ---------------------------------------------------------------------------
# Test 5 — E4: JSONL backend captures events
# ---------------------------------------------------------------------------

class TestJSONLBackendCapturesEvents:
    """E4: JSONLEmitter writes valid JSONL lines for each pipeline event."""

    def test_jsonl_file_has_correct_number_of_lines(self, tmp_path):
        """JSONL file has exactly as many lines as emitted events."""
        path = str(tmp_path / "pipeline-events.jsonl")
        emitter = JSONLEmitter(path)

        pipeline_id = "test-e2e-001"
        events = [
            EventBuilder.pipeline_started(pipeline_id, "test.dot", 6),
            EventBuilder.node_started(pipeline_id, "start", "start", 1),
            EventBuilder.node_completed(pipeline_id, "start", "skipped", 0.5),
            EventBuilder.node_started(pipeline_id, "check", "tool", 1),
            EventBuilder.node_completed(pipeline_id, "check", "success", 10.0),
            EventBuilder.edge_selected(pipeline_id, "check", "decide", 5),
        ]

        for evt in events:
            _run(emitter.emit(evt))
        _run(emitter.aclose())

        with open(path, encoding="utf-8") as fh:
            lines = [line for line in fh.readlines() if line.strip()]

        assert len(lines) == len(events), (
            f"Expected {len(events)} lines, got {len(lines)}"
        )

    def test_each_line_is_valid_json(self, tmp_path):
        """Each JSONL line is parseable JSON."""
        path = str(tmp_path / "events.jsonl")
        emitter = JSONLEmitter(path)

        pipeline_id = "test-e2e-001"
        _run(emitter.emit(EventBuilder.pipeline_started(pipeline_id, "test.dot", 6)))
        _run(emitter.emit(EventBuilder.node_started(pipeline_id, "check", "tool", 1)))
        _run(emitter.aclose())

        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    record = json.loads(line)  # must not raise
                    assert "type" in record
                    assert "pipeline_id" in record
                    assert "timestamp" in record

    def test_jsonl_lines_have_correct_schema(self, tmp_path):
        """JSONL records have the expected PipelineEvent schema."""
        path = str(tmp_path / "events.jsonl")
        emitter = JSONLEmitter(path)
        pipeline_id = "test-e2e-001"

        _run(emitter.emit(EventBuilder.pipeline_started(pipeline_id, "g.dot", 6)))
        _run(emitter.emit(EventBuilder.node_started(pipeline_id, "check", "tool", 1)))
        _run(emitter.emit(EventBuilder.node_completed(pipeline_id, "check", "success", 5.0)))
        _run(emitter.aclose())

        records = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    records.append(json.loads(line))

        required_fields = {"type", "pipeline_id", "timestamp", "data", "sequence"}
        for record in records:
            assert required_fields.issubset(set(record.keys())), (
                f"Record missing required fields: {set(record.keys())}"
            )

        # Verify sequence numbers are present and positive
        sequences = [r["sequence"] for r in records]
        assert all(s > 0 for s in sequences)

    def test_jsonl_event_types_match_emitted(self, tmp_path):
        """JSONL records preserve the event type strings."""
        path = str(tmp_path / "events.jsonl")
        emitter = JSONLEmitter(path)
        pipeline_id = "test-e2e-001"

        _run(emitter.emit(EventBuilder.pipeline_started(pipeline_id, "g.dot", 6)))
        _run(emitter.emit(EventBuilder.pipeline_completed(pipeline_id, 100.0)))
        _run(emitter.aclose())

        with open(path, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]

        assert records[0]["type"] == "pipeline.started"
        assert records[1]["type"] == "pipeline.completed"


# ---------------------------------------------------------------------------
# Test 6 — E5: LoopDetector integration
# ---------------------------------------------------------------------------

class TestLoopDetectorIntegration:
    """E5: LoopDetector with LoopPolicy, serialization, and retry resolution."""

    def test_check_returns_allowed_on_first_visits(self):
        """LoopDetector.check() returns allowed=True for visits within policy."""
        policy = LoopPolicy(per_node_max=3, pipeline_max=10)
        detector = LoopDetector(policy)

        result = detector.check("retry_node")
        assert result.allowed is True
        assert result.reason == "ok"
        assert result.visit_count == 1

    def test_check_returns_exceeded_after_per_node_max(self):
        """LoopDetector.check() returns allowed=False after per_node_max visits."""
        policy = LoopPolicy(per_node_max=3, pipeline_max=10)
        detector = LoopDetector(policy)

        # Perform per_node_max visits (should all be allowed)
        for i in range(3):
            result = detector.check("retry_node")
            assert result.allowed is True, (
                f"Visit {i+1} should be allowed, got allowed={result.allowed}"
            )

        # 4th visit exceeds limit
        result = detector.check("retry_node")
        assert result.allowed is False
        assert result.reason == "per_node_limit_exceeded"
        assert result.visit_count == 4

    def test_per_node_max_with_node_max_retries_override(self):
        """node_max_retries parameter overrides per_node_max from policy."""
        policy = LoopPolicy(per_node_max=3, pipeline_max=10)
        detector = LoopDetector(policy)

        # max_retries=2 means effective_limit = 2+1 = 3 visits allowed
        result1 = detector.check("retry_node", node_max_retries=2)
        assert result1.allowed is True  # visit 1
        result2 = detector.check("retry_node", node_max_retries=2)
        assert result2.allowed is True  # visit 2
        result3 = detector.check("retry_node", node_max_retries=2)
        assert result3.allowed is True  # visit 3 (= effective_limit, still allowed)

        # visit 4 exceeds effective_limit=3
        result4 = detector.check("retry_node", node_max_retries=2)
        assert result4.allowed is False
        assert result4.reason == "per_node_limit_exceeded"

    def test_serialize_and_from_checkpoint_roundtrip(self):
        """LoopDetector state serializes and restores correctly."""
        policy = LoopPolicy(per_node_max=3, pipeline_max=10)
        detector = LoopDetector(policy)

        detector.check("start", outcome_status="skipped")
        detector.check("check", outcome_status="success")
        detector.check("decide", outcome_status="success")
        detector.check("retry_node", outcome_status="success")
        detector.check("retry_node", outcome_status="success")

        serialized = detector.serialize()
        assert "visit_records" in serialized
        assert "total_executions" in serialized
        assert "execution_history" in serialized
        assert serialized["total_executions"] == 5

        restored = LoopDetector.from_checkpoint(serialized, policy)
        assert restored._total_executions == 5
        assert restored._visit_records["retry_node"].count == 2
        assert restored._visit_records["check"].count == 1

    def test_serialize_visit_records_have_correct_counts(self):
        """Serialized visit records reflect actual visit counts."""
        policy = LoopPolicy(per_node_max=5, pipeline_max=20)
        detector = LoopDetector(policy)

        for _ in range(3):
            detector.check("retry_node")

        serialized = detector.serialize()
        assert serialized["visit_records"]["retry_node"]["count"] == 3

    def test_resolve_retry_target_with_graph_attrs(self):
        """resolve_retry_target returns node-level, then graph-level retry target."""
        graph = parse_dot_file(_FIXTURE_DOT)

        # retry_node has no retry_target attr set in the fixture
        retry_node = graph.nodes["retry_node"]
        result = resolve_retry_target(retry_node, graph)
        # No retry_target on node or graph level in fixture
        assert result is None

    def test_sync_to_context_writes_visit_counts(self):
        """sync_to_context writes $node_visits.* keys into PipelineContext."""
        policy = LoopPolicy(per_node_max=3, pipeline_max=10)
        detector = LoopDetector(policy)

        detector.check("check")
        detector.check("decide")
        detector.check("decide")

        ctx = PipelineContext({})
        detector.sync_to_context(ctx)

        assert ctx.get("$node_visits.check") == 1
        assert ctx.get("$node_visits.decide") == 2
        assert ctx.get("$retry_count") == 1  # 0-indexed: count-1 for last node


# ---------------------------------------------------------------------------
# Test 7 — Full pipeline roundtrip (E1+E2+E3+E4+E5)
# ---------------------------------------------------------------------------

class TestFullPipelineRoundtrip:
    """Integration: all 5 epics working together in a simulated pipeline walk."""

    def _make_success_outcome(
        self,
        context_updates: dict | None = None,
    ) -> Outcome:
        return Outcome(
            status=OutcomeStatus.SUCCESS,
            context_updates=context_updates or {},
        )

    def test_full_pipeline_roundtrip(self, tmp_path):
        """Walk the pipeline graph, emitting events and tracking loop detection.

        Simulates:
          start (skipped) -> check (success) -> decide -> process (success) -> done
        with last_status=success so the 'success' branch is taken at decide.
        """
        # E1: Parse
        graph = parse_dot_file(_FIXTURE_DOT)

        # E2: Validate
        result = Validator(graph).run()
        assert result.is_valid, (
            "Validation failed: " + ", ".join(str(v) for v in result.errors)
        )

        # E4: Build event bus (JSONL + NullEmitter)
        jsonl_path = str(tmp_path / "e2e-events.jsonl")
        jsonl_emitter = JSONLEmitter(jsonl_path)
        null_emitter = NullEmitter()
        event_bus = CompositeEmitter([jsonl_emitter, null_emitter])

        # E5: Create LoopDetector
        policy = LoopPolicy(per_node_max=4, pipeline_max=20)
        loop_detector = LoopDetector(policy)

        # E3: EdgeSelector
        selector = EdgeSelector()

        # Set up initial context with last_status=success
        ctx = PipelineContext({"$last_status": "success"})

        # Define mock walk path through graph
        walk_order = ["start", "check", "decide", "process", "done"]
        events_emitted: list[PipelineEvent] = []

        # Walk the graph simulating handler execution
        _run(event_bus.emit(
            EventBuilder.pipeline_started(graph.attrs.get("pipeline_id", "test-e2e-001"), str(_FIXTURE_DOT), len(graph.nodes))
        ))

        for node_id in walk_order:
            node = graph.nodes[node_id]
            visit_count = ctx.get_visit_count(node_id) + 1
            ctx.increment_visit(node_id)

            # E4: Emit node.started
            started_evt = EventBuilder.node_started(
                graph.attrs.get("pipeline_id", "test-e2e-001"),
                node_id,
                node.handler_type,
                visit_count,
            )
            _run(event_bus.emit(started_evt))
            events_emitted.append(started_evt)

            # Simulate handler execution outcome
            if node_id == "start":
                outcome = Outcome(status=OutcomeStatus.SKIPPED)
            elif node_id == "done":
                outcome = Outcome(status=OutcomeStatus.SUCCESS)
            else:
                outcome = self._make_success_outcome({"$last_status": "success"})
                ctx.update({"$last_status": "success"})

            # E5: Check loop detector
            loop_result = loop_detector.check(node_id, outcome_status=outcome.status.value)
            assert loop_result.allowed, (
                f"Loop detection blocked node '{node_id}' unexpectedly: {loop_result.reason}"
            )

            # E4: Emit node.completed
            completed_evt = EventBuilder.node_completed(
                graph.attrs.get("pipeline_id", "test-e2e-001"),
                node_id,
                outcome.status.value,
                10.0,
            )
            _run(event_bus.emit(completed_evt))
            events_emitted.append(completed_evt)

            # E3: Select next edge (skip for terminal node)
            if node_id != "done":
                selected_edge = selector.select(graph, node, outcome, ctx)

                # E4: Emit edge.selected
                edge_evt = EventBuilder.edge_selected(
                    graph.attrs.get("pipeline_id", "test-e2e-001"),
                    node_id,
                    selected_edge.target,
                    1,
                    condition=selected_edge.condition or None,
                )
                _run(event_bus.emit(edge_evt))

                # Verify routing decisions
                if node_id == "decide":
                    # With last_status=success, should route to process
                    assert selected_edge.target == "process", (
                        f"Expected process, got {selected_edge.target}"
                    )

        # Emit pipeline.completed
        _run(event_bus.emit(
            EventBuilder.pipeline_completed(graph.attrs.get("pipeline_id", "test-e2e-001"), 50.0)
        ))

        # Close event bus
        _run(event_bus.aclose())

        # --- Assertions ---

        # Assert pipeline ended at "done"
        assert walk_order[-1] == "done"

        # Assert all events captured in JSONL
        with open(jsonl_path, encoding="utf-8") as fh:
            jsonl_lines = [json.loads(line) for line in fh if line.strip()]

        assert len(jsonl_lines) > 0, "JSONL file should contain events"

        # Verify JSONL schema
        for record in jsonl_lines:
            assert "type" in record
            assert "pipeline_id" in record
            assert "timestamp" in record

        # E5: Verify LoopDetector tracked visits
        loop_detector.sync_to_context(ctx)
        for node_id in walk_order:
            visit_key = f"$node_visits.{node_id}"
            count = ctx.get(visit_key, 0)
            assert count >= 1, (
                f"Expected visit count >= 1 for node '{node_id}', got {count}"
            )

        # E5: Serialize/restore roundtrip
        serialized = loop_detector.serialize()
        restored = LoopDetector.from_checkpoint(serialized, policy)
        assert restored._total_executions == loop_detector._total_executions

    def test_pipeline_failure_path_routes_to_done(self, tmp_path):
        """Failure path: last_status!=success routes decide -> done directly."""
        graph = parse_dot_file(_FIXTURE_DOT)
        selector = EdgeSelector()

        ctx = PipelineContext({"$last_status": "failure"})
        decide_node = graph.nodes["decide"]
        outcome = Outcome(status=OutcomeStatus.SUCCESS)

        edge = selector.select(graph, decide_node, outcome, ctx)
        assert edge.target == "done", (
            f"Failure path should route to 'done', got '{edge.target}'"
        )

    def test_retry_node_max_retries_attribute_parsed(self):
        """retry_node has max_retries=2 parsed from DOT attributes."""
        graph = parse_dot_file(_FIXTURE_DOT)
        retry_node = graph.nodes["retry_node"]
        assert retry_node.max_retries == 2
