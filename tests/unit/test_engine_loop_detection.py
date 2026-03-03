"""Tests for cobuilder/engine/loop_detection.py — Epic 5 acceptance criteria.

Covers:
  E5-AC1:  check() increments visit count; count is 1-indexed
  E5-AC2:  check() returns allowed=True when count <= per_node_max
  E5-AC3:  check() returns allowed=False, reason="per_node_limit_exceeded"
  E5-AC4:  check() returns allowed=False, reason="pipeline_limit_exceeded"
  E5-AC9:  sync_to_context() writes $node_visits.<node_id>
  E5-AC10: sync_to_context() writes $retry_count (0-indexed)
  E5-AC11: serialize() → from_checkpoint() round-trip
  E5-AC13: resolve_retry_target returns node-level value
  E5-AC14: resolve_retry_target returns graph-level value
  E5-AC15: resolve_retry_target returns None when no target
  E5-AC16: apply_loop_restart preserves graph.* and $node_visits.* keys
  E5-AC17: apply_loop_restart removes per-run keys
  E5-AC18: apply_loop_restart does NOT reset visit counts
  E5-AC12: check() continues counting from persisted count after from_checkpoint()

Additional:
  - resolve_loop_policy() with/without node and attributes
  - per-node limit override via node_max_retries parameter
  - outcome_status stored in VisitRecord.outcomes
  - timestamps recorded correctly
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from cobuilder.engine.context import PipelineContext
from cobuilder.engine.exceptions import NoRetryTargetError
from cobuilder.engine.loop_detection import (
    LoopDetectionResult,
    LoopDetector,
    LoopPolicy,
    VisitRecord,
    apply_loop_restart,
    resolve_loop_policy,
    resolve_retry_target,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_detector(per_node_max: int = 4, pipeline_max: int = 50) -> LoopDetector:
    return LoopDetector(LoopPolicy(per_node_max=per_node_max, pipeline_max=pipeline_max))


def make_graph(default_max_retry: int | None = None, **extra_attrs):
    graph = MagicMock()
    attrs = dict(extra_attrs)
    if default_max_retry is not None:
        attrs["default_max_retry"] = default_max_retry
    graph.attrs = attrs
    return graph


def make_node(max_retries: int | None = None, **extra_attrs):
    node = MagicMock()
    attrs = dict(extra_attrs)
    if max_retries is not None:
        attrs["max_retries"] = max_retries
    node.attrs = attrs
    return node


# ---------------------------------------------------------------------------
# E5-AC1: visit count is 1-indexed, increments on each call
# ---------------------------------------------------------------------------


class TestVisitCountIncrement:
    def test_first_call_returns_count_1(self):
        """E5-AC1: first check() returns visit_count=1."""
        d = make_detector()
        result = d.check("node_a")
        assert result.visit_count == 1

    def test_second_call_returns_count_2(self):
        """E5-AC1: second check() on same node returns visit_count=2."""
        d = make_detector()
        d.check("node_a")
        result = d.check("node_a")
        assert result.visit_count == 2

    def test_different_nodes_track_independently(self):
        """Each node has its own counter."""
        d = make_detector()
        d.check("node_a")
        d.check("node_a")
        r_a = d.check("node_a")
        r_b = d.check("node_b")
        assert r_a.visit_count == 3
        assert r_b.visit_count == 1

    def test_total_executions_increments(self):
        """Pipeline-wide execution counter increments for each check."""
        d = make_detector()
        d.check("node_a")
        d.check("node_b")
        d.check("node_a")
        assert d._total_executions == 3

    def test_execution_history_records_order(self):
        """Execution history records all node IDs in call order."""
        d = make_detector()
        d.check("node_a")
        d.check("node_b")
        d.check("node_a")
        assert d._execution_history == ["node_a", "node_b", "node_a"]


# ---------------------------------------------------------------------------
# E5-AC2: allowed=True when count <= per_node_max
# ---------------------------------------------------------------------------


class TestAllowedWithinLimit:
    def test_first_visit_is_allowed(self):
        """E5-AC2: first visit always allowed."""
        d = make_detector(per_node_max=4)
        result = d.check("node_a")
        assert result.allowed is True
        assert result.reason == "ok"

    def test_visit_at_per_node_max_is_allowed(self):
        """E5-AC2: visit exactly at per_node_max is allowed."""
        d = make_detector(per_node_max=4)
        for _ in range(3):
            d.check("node_a")
        result = d.check("node_a")  # count = 4 == per_node_max
        assert result.allowed is True
        assert result.reason == "ok"
        assert result.visit_count == 4

    def test_node_id_in_result(self):
        """Result contains the correct node_id."""
        d = make_detector()
        result = d.check("impl_auth")
        assert result.node_id == "impl_auth"


# ---------------------------------------------------------------------------
# E5-AC3: per_node_limit_exceeded
# ---------------------------------------------------------------------------


class TestPerNodeLimitExceeded:
    def test_exceeds_per_node_max(self):
        """E5-AC3: visit_count > per_node_max → allowed=False."""
        d = make_detector(per_node_max=4)
        for _ in range(4):
            d.check("node_a")
        result = d.check("node_a")  # count = 5 > 4
        assert result.allowed is False
        assert result.reason == "per_node_limit_exceeded"
        assert result.visit_count == 5

    def test_per_node_limit_is_reported(self):
        """E5-AC3: limit field reports the effective limit."""
        d = make_detector(per_node_max=4)
        for _ in range(4):
            d.check("node_a")
        result = d.check("node_a")
        assert result.limit == 4

    def test_per_node_override_via_node_max_retries(self):
        """node_max_retries overrides policy.per_node_max."""
        d = make_detector(per_node_max=10)  # policy says 10
        # node says max_retries=2 → effective limit = 3
        d.check("node_a", node_max_retries=2)
        d.check("node_a", node_max_retries=2)
        d.check("node_a", node_max_retries=2)  # count = 3 == effective limit
        result = d.check("node_a", node_max_retries=2)  # count = 4 > 3
        assert result.allowed is False
        assert result.reason == "per_node_limit_exceeded"
        assert result.limit == 3

    def test_node_max_retries_zero_allows_one_visit(self):
        """node_max_retries=0 → effective limit = 1 → second visit fails."""
        d = make_detector()
        r1 = d.check("node_a", node_max_retries=0)  # count=1 == 1, ok
        assert r1.allowed is True
        r2 = d.check("node_a", node_max_retries=0)  # count=2 > 1, fail
        assert r2.allowed is False
        assert r2.reason == "per_node_limit_exceeded"


# ---------------------------------------------------------------------------
# E5-AC4: pipeline_limit_exceeded
# ---------------------------------------------------------------------------


class TestPipelineLimitExceeded:
    def test_exceeds_pipeline_max(self):
        """E5-AC4: total_executions > pipeline_max → pipeline_limit_exceeded."""
        d = make_detector(per_node_max=100, pipeline_max=3)
        d.check("a")
        d.check("b")
        d.check("c")  # total = 3 == pipeline_max, ok
        result = d.check("d")  # total = 4 > 3, fail
        assert result.allowed is False
        assert result.reason == "pipeline_limit_exceeded"

    def test_pipeline_limit_reported_in_limit_field(self):
        """Pipeline limit is reported in result.limit."""
        d = make_detector(per_node_max=100, pipeline_max=3)
        for ch in "abcd":
            result = d.check(ch)
        assert result.limit == 3  # type: ignore[possibly-undefined]

    def test_pipeline_limit_checked_before_per_node(self):
        """Pipeline limit takes priority over per-node limit."""
        d = make_detector(per_node_max=2, pipeline_max=2)
        d.check("a")
        d.check("a")  # total=2, per-node count=2 (both at limit, ok)
        result = d.check("a")  # total=3 > 2 → pipeline, not per-node
        assert result.reason == "pipeline_limit_exceeded"


# ---------------------------------------------------------------------------
# Outcome status and timestamps
# ---------------------------------------------------------------------------


class TestOutcomeAndTimestamps:
    def test_outcome_status_stored_in_visit_record(self):
        """outcome_status is appended to VisitRecord.outcomes."""
        d = make_detector()
        d.check("node_a", outcome_status="SUCCESS")
        d.check("node_a", outcome_status="FAILURE")
        record = d._visit_records["node_a"]
        assert record.outcomes == ["SUCCESS", "FAILURE"]

    def test_no_outcome_status_does_not_append(self):
        """When outcome_status is None, outcomes list stays empty."""
        d = make_detector()
        d.check("node_a")
        record = d._visit_records["node_a"]
        assert record.outcomes == []

    def test_timestamps_set_on_first_visit(self):
        """first_visit_ts and last_visit_ts are set on first call."""
        before = time.time()
        d = make_detector()
        d.check("node_a")
        after = time.time()
        record = d._visit_records["node_a"]
        assert before <= record.first_visit_ts <= after
        assert before <= record.last_visit_ts <= after

    def test_last_visit_ts_updated_on_subsequent_visits(self):
        """last_visit_ts is updated on each call; first_visit_ts unchanged."""
        ts1 = 1_000_000.0
        ts2 = 2_000_000.0
        d = make_detector()
        d.check("node_a", ts=ts1)
        d.check("node_a", ts=ts2)
        record = d._visit_records["node_a"]
        assert record.first_visit_ts == ts1
        assert record.last_visit_ts == ts2

    def test_custom_ts_parameter_is_used(self):
        """Explicit ts parameter overrides time.time()."""
        d = make_detector()
        d.check("node_a", ts=12345.0)
        record = d._visit_records["node_a"]
        assert record.first_visit_ts == 12345.0
        assert record.last_visit_ts == 12345.0


# ---------------------------------------------------------------------------
# E5-AC9: sync_to_context writes $node_visits.<node_id>
# ---------------------------------------------------------------------------


class TestSyncToContext:
    def test_writes_node_visits_key(self):
        """E5-AC9: sync_to_context writes $node_visits.impl_auth after 2nd check."""
        d = make_detector()
        ctx = PipelineContext()
        d.check("impl_auth")
        d.check("impl_auth")
        d.sync_to_context(ctx)
        assert ctx.get("$node_visits.impl_auth") == 2

    def test_writes_multiple_nodes(self):
        """All tracked nodes are written to context."""
        d = make_detector()
        ctx = PipelineContext()
        d.check("node_a")
        d.check("node_b")
        d.check("node_a")
        d.sync_to_context(ctx)
        assert ctx.get("$node_visits.node_a") == 2
        assert ctx.get("$node_visits.node_b") == 1

    # E5-AC10: sync_to_context writes $retry_count (0-indexed)
    def test_writes_retry_count_zero_indexed(self):
        """E5-AC10: $retry_count is 0-indexed (count - 1) for most recent node."""
        d = make_detector()
        ctx = PipelineContext()
        d.check("impl_auth")  # count=1 → retry_count=0
        d.check("impl_auth")  # count=2 → retry_count=1
        d.sync_to_context(ctx)
        assert ctx.get("$retry_count") == 1

    def test_retry_count_first_visit_is_zero(self):
        """After first visit, $retry_count = 0."""
        d = make_detector()
        ctx = PipelineContext()
        d.check("node_a")
        d.sync_to_context(ctx)
        assert ctx.get("$retry_count") == 0

    def test_retry_count_reflects_last_checked_node(self):
        """$retry_count reflects the most recently checked node, not another."""
        d = make_detector()
        ctx = PipelineContext()
        d.check("node_a")
        d.check("node_a")
        d.check("node_a")  # count=3 for node_a
        d.check("node_b")  # count=1 for node_b — this is last
        d.sync_to_context(ctx)
        # Last checked is node_b (count=1), so retry_count = 0
        assert ctx.get("$retry_count") == 0

    def test_no_context_update_when_no_checks(self):
        """sync_to_context on fresh detector doesn't write node_visits or retry_count."""
        d = make_detector()
        ctx = PipelineContext()
        d.sync_to_context(ctx)
        assert ctx.get("$retry_count") is None
        assert len(ctx) == 0


# ---------------------------------------------------------------------------
# E5-AC11 + E5-AC12: serialize / from_checkpoint round-trip
# ---------------------------------------------------------------------------


class TestSerializeRoundTrip:
    def test_serialize_structure(self):
        """serialize() returns dict with expected top-level keys."""
        d = make_detector()
        d.check("node_a")
        data = d.serialize()
        assert "visit_records" in data
        assert "total_executions" in data
        assert "execution_history" in data

    def test_serialize_visit_records_content(self):
        """serialize() captures all VisitRecord fields."""
        d = make_detector()
        d.check("node_a", outcome_status="SUCCESS", ts=1_000_000.0)
        data = d.serialize()
        vr = data["visit_records"]["node_a"]
        assert vr["node_id"] == "node_a"
        assert vr["count"] == 1
        assert vr["outcomes"] == ["SUCCESS"]
        assert vr["first_visit_ts"] == 1_000_000.0

    def test_round_trip_produces_identical_state(self):
        """E5-AC11: from_checkpoint after serialize() reproduces identical state."""
        d = make_detector(per_node_max=5, pipeline_max=20)
        d.check("node_a", outcome_status="SUCCESS", ts=1.0)
        d.check("node_b", ts=2.0)
        d.check("node_a", outcome_status="FAILURE", ts=3.0)

        data = d.serialize()
        policy = LoopPolicy(per_node_max=5, pipeline_max=20)
        d2 = LoopDetector.from_checkpoint(data, policy)

        assert d2._total_executions == d._total_executions
        assert d2._execution_history == d._execution_history
        assert set(d2._visit_records.keys()) == set(d._visit_records.keys())

        for nid in d._visit_records:
            r1 = d._visit_records[nid]
            r2 = d2._visit_records[nid]
            assert r2.node_id == r1.node_id
            assert r2.count == r1.count
            assert r2.outcomes == r1.outcomes
            assert r2.first_visit_ts == r1.first_visit_ts
            assert r2.last_visit_ts == r1.last_visit_ts

    def test_check_continues_from_persisted_count(self):
        """E5-AC12: after from_checkpoint, check() increments from persisted count."""
        d = make_detector()
        d.check("node_a")
        d.check("node_a")  # count = 2

        data = d.serialize()
        d2 = LoopDetector.from_checkpoint(data, LoopPolicy())
        result = d2.check("node_a")  # should be count = 3
        assert result.visit_count == 3
        assert result.allowed is True

    def test_from_checkpoint_empty_data(self):
        """from_checkpoint with empty data produces clean detector."""
        d = LoopDetector.from_checkpoint({}, LoopPolicy())
        assert d._total_executions == 0
        assert d._execution_history == []
        assert d._visit_records == {}


# ---------------------------------------------------------------------------
# resolve_loop_policy
# ---------------------------------------------------------------------------


class TestResolveLoopPolicy:
    def test_defaults_without_node(self):
        """Without node, per_node_max=4 and pipeline_max=50 by default."""
        graph = make_graph()
        policy = resolve_loop_policy(graph)
        assert policy.per_node_max == 4
        assert policy.pipeline_max == 50

    def test_pipeline_max_from_graph_attr(self):
        """pipeline_max derived from graph's default_max_retry attribute."""
        graph = make_graph(default_max_retry=100)
        policy = resolve_loop_policy(graph)
        assert policy.pipeline_max == 100

    def test_per_node_max_from_node_max_retries(self):
        """per_node_max = node.max_retries + 1 when node is provided."""
        graph = make_graph()
        node = make_node(max_retries=5)
        policy = resolve_loop_policy(graph, node)
        assert policy.per_node_max == 6  # 5 + 1

    def test_per_node_max_default_when_node_has_no_max_retries(self):
        """per_node_max = 3+1=4 when node has no max_retries attribute."""
        graph = make_graph()
        node = make_node()  # no max_retries key → defaults to 3
        policy = resolve_loop_policy(graph, node)
        assert policy.per_node_max == 4

    def test_both_graph_and_node_attrs(self):
        """Both attributes resolved correctly together."""
        graph = make_graph(default_max_retry=200)
        node = make_node(max_retries=7)
        policy = resolve_loop_policy(graph, node)
        assert policy.pipeline_max == 200
        assert policy.per_node_max == 8

    def test_node_max_retries_zero(self):
        """max_retries=0 → per_node_max=1 (initial attempt only)."""
        graph = make_graph()
        node = make_node(max_retries=0)
        policy = resolve_loop_policy(graph, node)
        assert policy.per_node_max == 1

    def test_graph_default_max_retry_string_converted(self):
        """default_max_retry stored as string is converted to int."""
        graph = MagicMock()
        graph.attrs = {"default_max_retry": "75"}
        policy = resolve_loop_policy(graph)
        assert policy.pipeline_max == 75


# ---------------------------------------------------------------------------
# VisitRecord dataclass smoke tests
# ---------------------------------------------------------------------------


class TestVisitRecordDataclass:
    def test_default_values(self):
        vr = VisitRecord(node_id="x")
        assert vr.count == 0
        assert vr.first_visit_ts == 0.0
        assert vr.last_visit_ts == 0.0
        assert vr.outcomes == []

    def test_outcomes_is_independent_per_instance(self):
        """Default factory ensures outcomes lists are not shared."""
        vr1 = VisitRecord(node_id="a")
        vr2 = VisitRecord(node_id="b")
        vr1.outcomes.append("X")
        assert vr2.outcomes == []


# ---------------------------------------------------------------------------
# E5-AC13/14/15: resolve_retry_target
# ---------------------------------------------------------------------------


def _node_with_attrs(**attrs):
    n = MagicMock()
    n.attrs = attrs
    return n


def _graph_with_attrs(**attrs):
    g = MagicMock()
    g.attrs = attrs
    return g


class TestResolveRetryTarget:
    def test_node_level_retry_target_wins(self):
        """E5-AC13: node-level retry_target returned when set."""
        node = _node_with_attrs(retry_target="retry_node")
        graph = _graph_with_attrs(retry_target="graph_retry", fallback_retry_target="fallback")
        assert resolve_retry_target(node, graph) == "retry_node"

    def test_graph_level_retry_target_when_node_lacks(self):
        """E5-AC14: graph-level retry_target used when node has none."""
        node = _node_with_attrs()  # no retry_target
        graph = _graph_with_attrs(retry_target="graph_retry")
        assert resolve_retry_target(node, graph) == "graph_retry"

    def test_fallback_retry_target_when_no_graph_retry(self):
        """fallback_retry_target used when graph has no retry_target."""
        node = _node_with_attrs()
        graph = _graph_with_attrs(fallback_retry_target="fallback_node")
        assert resolve_retry_target(node, graph) == "fallback_node"

    def test_returns_none_when_no_target(self):
        """E5-AC15: None returned when neither node nor graph has retry_target."""
        node = _node_with_attrs()
        graph = _graph_with_attrs()
        assert resolve_retry_target(node, graph) is None

    def test_empty_string_node_attr_falls_through_to_graph(self):
        """Empty string retry_target on node falls through to graph attr."""
        node = _node_with_attrs(retry_target="")
        graph = _graph_with_attrs(retry_target="graph_retry")
        assert resolve_retry_target(node, graph) == "graph_retry"

    def test_empty_string_graph_falls_through_to_fallback(self):
        """Empty string graph retry_target falls through to fallback."""
        node = _node_with_attrs()
        graph = _graph_with_attrs(retry_target="", fallback_retry_target="fallback")
        assert resolve_retry_target(node, graph) == "fallback"


# ---------------------------------------------------------------------------
# E5-AC16/17/18: apply_loop_restart
# ---------------------------------------------------------------------------


class TestApplyLoopRestart:
    def _make_context(self, data: dict) -> PipelineContext:
        return PipelineContext(data)

    def test_preserves_graph_prefix_keys(self):
        """E5-AC16: keys starting with 'graph.' are preserved."""
        ctx = self._make_context({
            "graph.input": "value",
            "graph.config": 42,
            "run_data": "dropped",
        })
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        assert result.get("graph.input") == "value"
        assert result.get("graph.config") == 42

    def test_preserves_pipeline_prefix_keys(self):
        """E5-AC16: keys starting with 'pipeline_' are preserved."""
        ctx = self._make_context({
            "pipeline_id": "run-001",
            "pipeline_start": 1234.5,
            "impl_auth.status": "dropped",
        })
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        assert result.get("pipeline_id") == "run-001"
        assert result.get("pipeline_start") == 1234.5

    def test_preserves_node_visits_with_dollar_prefix(self):
        """E5-AC16: $node_visits.* keys are preserved."""
        ctx = self._make_context({
            "$node_visits.impl_auth": 2,
            "$node_visits.val_auth": 1,
            "impl_auth.output": "dropped",
        })
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        assert result.get("$node_visits.impl_auth") == 2
        assert result.get("$node_visits.val_auth") == 1

    def test_removes_per_run_keys(self):
        """E5-AC17: per-run keys like 'impl_auth.status' are dropped."""
        ctx = self._make_context({
            "impl_auth.status": "SUCCESS",
            "val_auth.result": {"foo": "bar"},
            "graph.input": "kept",
        })
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        assert result.get("impl_auth.status") is None
        assert result.get("val_auth.result") is None
        assert result.get("graph.input") == "kept"

    def test_does_not_reset_visit_counts(self):
        """E5-AC18: visit counts survive loop restart."""
        d = make_detector()
        ctx = PipelineContext()
        d.check("impl_auth")
        d.check("impl_auth")
        d.sync_to_context(ctx)
        # Add some per-run data
        ctx.update({"impl_auth.output": "data", "pipeline_id": "p-001"})
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        # Visit counts preserved
        assert result.get("$node_visits.impl_auth") == 2
        # per-run data dropped
        assert result.get("impl_auth.output") is None
        # pipeline_ preserved
        assert result.get("pipeline_id") == "p-001"

    def test_returns_new_context_not_original(self):
        """apply_loop_restart returns a NEW context, does not modify original."""
        ctx = self._make_context({"impl_auth.status": "x", "graph.x": 1})
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        # Original still has the key
        assert ctx.get("impl_auth.status") == "x"
        # Result does not
        assert result.get("impl_auth.status") is None

    def test_empty_context_returns_empty_context(self):
        """apply_loop_restart on empty context returns empty context."""
        ctx = PipelineContext()
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        assert len(result) == 0

    def test_preserves_legacy_node_visits_key(self):
        """Legacy '$node_visits' top-level key is preserved."""
        ctx = self._make_context({"$node_visits": {"a": 1}, "run_data": "x"})
        graph = MagicMock()
        result = apply_loop_restart(ctx, graph)
        assert result.get("$node_visits") == {"a": 1}
        assert result.get("run_data") is None


# ---------------------------------------------------------------------------
# NoRetryTargetError
# ---------------------------------------------------------------------------


class TestNoRetryTargetError:
    def test_raises_with_correct_message(self):
        """NoRetryTargetError message includes node_id and pipeline_id."""
        err = NoRetryTargetError(node_id="impl_auth", pipeline_id="my-pipeline")
        assert "impl_auth" in str(err)
        assert "my-pipeline" in str(err)

    def test_attributes_set(self):
        """node_id and pipeline_id attributes set correctly."""
        err = NoRetryTargetError(node_id="node_x", pipeline_id="pipe-1")
        assert err.node_id == "node_x"
        assert err.pipeline_id == "pipe-1"

    def test_default_pipeline_id_is_empty(self):
        """pipeline_id defaults to empty string."""
        err = NoRetryTargetError(node_id="node_x")
        assert err.pipeline_id == ""

    def test_is_engine_error(self):
        """NoRetryTargetError is a subclass of EngineError."""
        from cobuilder.engine.exceptions import EngineError
        assert isinstance(NoRetryTargetError("x"), EngineError)

    def test_is_catchable_as_exception(self):
        """Can be raised and caught as a standard exception."""
        with pytest.raises(NoRetryTargetError) as exc_info:
            raise NoRetryTargetError("impl_auth", "test-pipeline")
        assert exc_info.value.node_id == "impl_auth"
