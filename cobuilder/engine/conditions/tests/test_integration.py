"""Integration tests for E3.3 — Edge Selector + Validation Rule 7 wired to
the real conditions package (Epic 3).

Acceptance criteria covered:
- EdgeSelector uses the real evaluate_condition by default (no stub injection)
- Conditioned edge is selected when its expression evaluates True
- EdgeSelector falls through to Step 2 when no condition matches (Step 1 miss)
- EdgeSelector catches ConditionEvalError / parse errors and skips the edge
- Validator Rule 7 uses the real parser — catches genuinely invalid syntax
- Validator Rule 7 produces WARNING violation for bare-word conditions (AMD-5)
- End-to-end: graph with ``$retry_count < 3`` condition, context retry_count=1
  → the conditioned edge is selected
"""
from __future__ import annotations

import warnings

import pytest

from cobuilder.engine.conditions import ConditionEvalError, ConditionParseError
from cobuilder.engine.context import PipelineContext
from cobuilder.engine.edge_selector import EdgeSelector, _stub_condition_evaluator
from cobuilder.engine.exceptions import NoEdgeError
from cobuilder.engine.graph import Edge, Graph, Node
from cobuilder.engine.outcome import Outcome, OutcomeStatus
from cobuilder.engine.validation import Severity
from cobuilder.engine.validation.rules import ConditionSyntaxValid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph(edges: list[Edge], nodes: dict[str, Node] | None = None) -> Graph:
    """Build a minimal Graph with the given edges.

    If *nodes* is not supplied, Node stubs are created from the edge
    source/target IDs so that adjacency indices are populated correctly.
    """
    if nodes is None:
        node_ids: set[str] = set()
        for edge in edges:
            node_ids.add(edge.source)
            node_ids.add(edge.target)
        nodes = {nid: Node(id=nid, shape="box") for nid in node_ids}

    return Graph(name="test", nodes=nodes, edges=edges)


def _outcome(label: str = "", suggested: str = "") -> Outcome:
    """Build a minimal Outcome suitable for edge selection."""
    return Outcome(
        status=OutcomeStatus.SUCCESS,
        preferred_label=label,
        suggested_next=suggested,
    )


def _ctx(**kwargs) -> PipelineContext:
    """Build a PipelineContext with ``$``-prefixed keys."""
    return PipelineContext({f"${k}": v for k, v in kwargs.items()})


# ---------------------------------------------------------------------------
# EdgeSelector — real conditions evaluator wired by default
# ---------------------------------------------------------------------------

class TestEdgeSelectorRealEvaluator:
    """EdgeSelector uses the Epic 3 conditions package as its default evaluator."""

    def test_conditioned_edge_selected_when_expression_true(self):
        """Step 1: condition ``$status = "success"`` matches a context with status=success."""
        edges = [
            Edge(source="A", target="B", condition='$status = "success"'),
            Edge(source="A", target="C"),
        ]
        graph = _make_graph(edges)
        ctx = PipelineContext({"$status": "success"})
        sel = EdgeSelector()  # uses real evaluator by default

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx)

        assert selected.target == "B"

    def test_unconditioned_edge_falls_through_to_step5_when_no_condition_matches(self):
        """Step 1 miss: condition is False → fallthrough to Step 5 default edge."""
        edges = [
            Edge(source="A", target="B", condition='$status = "failure"'),
            Edge(source="A", target="C"),  # unlabeled default
        ]
        graph = _make_graph(edges)
        ctx = PipelineContext({"$status": "success"})
        sel = EdgeSelector()

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx)

        assert selected.target == "C"

    def test_numeric_comparison_condition(self):
        """Step 1: ``$retry_count < 3`` selects retry edge when count is 1."""
        retry_edge = Edge(source="A", target="retry", condition="$retry_count < 3")
        done_edge = Edge(source="A", target="done")
        graph = _make_graph([retry_edge, done_edge])
        ctx = _ctx(retry_count=1)
        sel = EdgeSelector()

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx)

        assert selected.target == "retry"

    def test_numeric_comparison_falls_through_when_count_exceeds_threshold(self):
        """Step 1 miss: ``$retry_count < 3`` is False when count is 5 → fallthrough."""
        retry_edge = Edge(source="A", target="retry", condition="$retry_count < 3")
        done_edge = Edge(source="A", target="done")
        graph = _make_graph([retry_edge, done_edge])
        ctx = _ctx(retry_count=5)
        sel = EdgeSelector()

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx)

        assert selected.target == "done"

    def test_step2_preferred_label_used_when_no_condition_matches(self):
        """With no condition match, Step 2 preferred_label wins."""
        edges = [
            Edge(source="A", target="X", condition='$flag = "yes"'),
            Edge(source="A", target="Y", label="pass"),
            Edge(source="A", target="Z", label="fail"),
        ]
        graph = _make_graph(edges)
        ctx = PipelineContext({"$flag": "no"})
        sel = EdgeSelector()

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(label="pass"), ctx)

        assert selected.target == "Y"

    def test_malformed_condition_is_skipped_no_crash(self):
        """A condition that fails to parse is logged and skipped — no exception raised."""
        malformed = Edge(source="A", target="B", condition="$x >>>>> invalid garbage")
        fallback = Edge(source="A", target="C")
        graph = _make_graph([malformed, fallback])
        ctx = _ctx(x=1)
        sel = EdgeSelector()

        # Must not raise; malformed edge is skipped → fallback selected.
        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx)

        assert selected.target == "C"

    def test_condition_evaluator_injected_stub(self):
        """Backward compat: injecting ``_stub_condition_evaluator`` still works."""
        edges = [
            Edge(source="A", target="B", condition="true"),
            Edge(source="A", target="C"),
        ]
        graph = _make_graph(edges)
        ctx = _ctx()
        sel = EdgeSelector(condition_evaluator=_stub_condition_evaluator)

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx)

        assert selected.target == "B"

    def test_no_outgoing_edges_raises_no_edge_error(self):
        """NoEdgeError is raised when the current node has no outgoing edges."""
        nodes = {
            "start": Node(id="start", shape="Mdiamond"),
            "exit": Node(id="exit", shape="Msquare"),
        }
        graph = Graph(name="test", nodes=nodes, edges=[])
        ctx = _ctx()
        sel = EdgeSelector()

        with pytest.raises(NoEdgeError):
            sel.select(graph, nodes["exit"], _outcome(), ctx)

    def test_dict_context_wrapped_in_pipeline_context(self):
        """EdgeSelector accepts a plain dict snapshot as context (snapshot path)."""
        edges = [
            Edge(source="A", target="B", condition='$env = "prod"'),
            Edge(source="A", target="C"),
        ]
        graph = _make_graph(edges)
        # Pass a raw dict (as if from context.snapshot())
        ctx_dict = {"$env": "prod"}
        sel = EdgeSelector()

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx_dict)

        assert selected.target == "B"


# ---------------------------------------------------------------------------
# Validation Rule 7 — real parser + AMD-5 bare-word warnings
# ---------------------------------------------------------------------------

class TestRule7WithRealParser:
    """ConditionSyntaxValid uses the real conditions parser via validate_condition_syntax."""

    def _make_conditioned_graph(self, condition: str) -> Graph:
        """Minimal valid graph with one conditioned edge A → B and a default A → C."""
        nodes = {
            "A": Node(id="A", shape="Mdiamond"),
            "B": Node(id="B", shape="box"),
            "C": Node(id="C", shape="Msquare"),
        }
        edges = [
            Edge(source="A", target="B", condition=condition),
            Edge(source="A", target="C"),
        ]
        return Graph(name="test", nodes=nodes, edges=edges)

    def test_valid_condition_no_violations(self):
        """A well-formed condition string produces zero violations."""
        graph = self._make_conditioned_graph('$retry_count < 3')
        rule = ConditionSyntaxValid()
        violations = rule.check(graph)
        assert violations == []

    def test_truly_invalid_syntax_produces_error_violation(self):
        """Genuinely invalid syntax (not just bare-word) produces an ERROR violation."""
        graph = self._make_conditioned_graph("$x >>>> garbage")
        rule = ConditionSyntaxValid()
        violations = rule.check(graph)

        assert len(violations) >= 1
        error_vs = [v for v in violations if v.severity == Severity.ERROR]
        assert error_vs, "Expected at least one ERROR violation for invalid syntax"
        assert error_vs[0].rule_id == "ConditionSyntaxValid"

    def test_bare_word_condition_produces_warning_violation_amd5(self):
        """Bare-word RHS (AMD-5) produces a WARNING-level violation, not an error."""
        # '$status = success' uses unquoted 'success' — a bare-word DeprecationWarning
        graph = self._make_conditioned_graph("$status = success")
        rule = ConditionSyntaxValid()
        violations = rule.check(graph)

        # Should be warnings only — no hard errors.
        error_vs = [v for v in violations if v.severity == Severity.ERROR]
        warning_vs = [v for v in violations if v.severity == Severity.WARNING]

        assert not error_vs, f"Bare-word condition should not produce ERROR: {error_vs}"
        assert warning_vs, "Bare-word condition must produce at least one WARNING violation"
        assert warning_vs[0].rule_id == "ConditionSyntaxValid"
        # Message should reference AMD-5 or deprecated/bare-word
        msg = warning_vs[0].message.lower()
        assert any(kw in msg for kw in ("bare", "unquoted", "deprecated")), (
            f"WARNING message should mention bare-word deprecation, got: {warning_vs[0].message}"
        )

    def test_unconditional_edge_no_violations(self):
        """Edges without conditions are always valid — no violations."""
        nodes = {
            "A": Node(id="A", shape="Mdiamond"),
            "B": Node(id="B", shape="Msquare"),
        }
        graph = Graph(
            name="test",
            nodes=nodes,
            edges=[Edge(source="A", target="B")],  # no condition
        )
        rule = ConditionSyntaxValid()
        assert rule.check(graph) == []

    def test_multiple_edges_both_valid_no_violations(self):
        """Multiple conditioned edges all valid → empty violation list."""
        nodes = {
            "A": Node(id="A", shape="Mdiamond"),
            "B": Node(id="B", shape="box"),
            "C": Node(id="C", shape="Msquare"),
        }
        edges = [
            Edge(source="A", target="B", condition='$score >= 80'),
            Edge(source="A", target="C", condition='$score < 80'),
        ]
        graph = Graph(name="test", nodes=nodes, edges=edges)
        rule = ConditionSyntaxValid()
        assert rule.check(graph) == []

    def test_edge_location_captured_in_violation(self):
        """Violation includes edge source/target for precise error reporting."""
        graph = self._make_conditioned_graph("$x >>>")
        rule = ConditionSyntaxValid()
        violations = rule.check(graph)

        assert violations
        v = violations[0]
        assert v.edge_src == "A"
        assert v.edge_dst == "B"


# ---------------------------------------------------------------------------
# End-to-end: graph traversal with real condition evaluation
# ---------------------------------------------------------------------------

class TestEndToEndConditionedGraph:
    """Full end-to-end: build a graph, set context, run EdgeSelector."""

    def test_retry_loop_graph_selects_retry_edge_when_below_threshold(self):
        """
        Graph: start -> process -> [retry_edge cond=$retry_count < 3, done_edge]
        Context: retry_count=1  →  retry_edge selected.
        """
        nodes = {
            "start": Node(id="start", shape="Mdiamond"),
            "process": Node(id="process", shape="box"),
            "retry": Node(id="retry", shape="box"),
            "done": Node(id="done", shape="Msquare"),
        }
        edges = [
            Edge(source="start", target="process"),
            Edge(source="process", target="retry", condition="$retry_count < 3"),
            Edge(source="process", target="done"),
        ]
        graph = Graph(name="retry_loop", nodes=nodes, edges=edges)
        ctx = _ctx(retry_count=1)
        sel = EdgeSelector()  # real evaluator

        selected = sel.select(graph, nodes["process"], _outcome(), ctx)

        assert selected.target == "retry"

    def test_retry_loop_graph_exits_when_above_threshold(self):
        """
        Same graph but retry_count=5 → done_edge selected (condition False).
        """
        nodes = {
            "start": Node(id="start", shape="Mdiamond"),
            "process": Node(id="process", shape="box"),
            "retry": Node(id="retry", shape="box"),
            "done": Node(id="done", shape="Msquare"),
        }
        edges = [
            Edge(source="start", target="process"),
            Edge(source="process", target="retry", condition="$retry_count < 3"),
            Edge(source="process", target="done"),
        ]
        graph = Graph(name="retry_loop", nodes=nodes, edges=edges)
        ctx = _ctx(retry_count=5)
        sel = EdgeSelector()

        selected = sel.select(graph, nodes["process"], _outcome(), ctx)

        assert selected.target == "done"

    def test_compound_condition_and_operator(self):
        """``$score >= 80 && $approved = "yes"`` — both conditions must be true."""
        nodes = {
            "A": Node(id="A", shape="box"),
            "B": Node(id="B", shape="box"),
            "C": Node(id="C", shape="box"),
        }
        edges = [
            Edge(source="A", target="B", condition='$score >= 80 && $approved = "yes"'),
            Edge(source="A", target="C"),
        ]
        graph = Graph(name="compound", nodes=nodes, edges=edges)

        # Both conditions true → B selected
        ctx_pass = PipelineContext({"$score": 90, "$approved": "yes"})
        sel = EdgeSelector()
        assert sel.select(graph, nodes["A"], _outcome(), ctx_pass).target == "B"

        # One condition false → C selected
        ctx_fail = PipelineContext({"$score": 70, "$approved": "yes"})
        assert sel.select(graph, nodes["A"], _outcome(), ctx_fail).target == "C"

    def test_missing_variable_defaults_to_false_no_crash(self):
        """Missing context variable causes condition to yield False — no exception."""
        edges = [
            Edge(source="A", target="B", condition='$missing_key = "value"'),
            Edge(source="A", target="C"),
        ]
        graph = _make_graph(edges)
        ctx = PipelineContext({})  # empty context
        sel = EdgeSelector()

        selected = sel.select(graph, Node(id="A", shape="box"), _outcome(), ctx)

        assert selected.target == "C"  # condition False → fallthrough to default
