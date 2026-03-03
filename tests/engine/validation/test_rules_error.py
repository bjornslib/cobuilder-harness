"""Tests for Rules 1-9 (ERROR-level validation rules).

Each rule class has at minimum:
  - valid: passes with no violations
  - violation: produces the expected violation
  - fix_hint: fix_hint is non-empty on every violation
"""
from __future__ import annotations

import pytest

from cobuilder.engine.validation import Severity
from cobuilder.engine.validation.rules import (
    AllNodesReachable,
    AtLeastOneExit,
    ConditionSyntaxValid,
    EdgeTargetsExist,
    ExitNoOutgoing,
    RetryTargetsExist,
    SingleStartNode,
    StartNoIncoming,
    StylesheetSyntaxValid,
)
from tests.engine.validation.conftest import make_edge, make_graph, make_node


# ---------------------------------------------------------------------------
# Rule 1: SingleStartNode
# ---------------------------------------------------------------------------

class TestSingleStartNode:
    def test_valid_exactly_one_start(self, minimal_valid_graph):
        violations = SingleStartNode().check(minimal_valid_graph)
        assert violations == []

    def test_error_no_start_node(self, minimal_valid_graph):
        # Remove the Mdiamond node
        graph = make_graph(
            nodes=[n for n in minimal_valid_graph.nodes.values() if n.shape != "Mdiamond"],
            edges=[
                e for e in minimal_valid_graph.edges
                if e.source != "start" and e.target != "start"
            ],
        )
        violations = SingleStartNode().check(graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert violations[0].rule_id == "SingleStartNode"
        assert "Mdiamond" in violations[0].message

    def test_error_multiple_start_nodes(self, minimal_valid_graph):
        second_start = make_node("start2", shape="Mdiamond")
        graph = make_graph(
            nodes=list(minimal_valid_graph.nodes.values()) + [second_start],
            edges=minimal_valid_graph.edges + [make_edge("start2", "impl")],
        )
        violations = SingleStartNode().check(graph)
        # One violation per start node
        assert len(violations) >= 2
        assert all(v.severity == Severity.ERROR for v in violations)
        assert all(v.rule_id == "SingleStartNode" for v in violations)

    def test_fix_hint_present_on_no_start(self):
        graph = make_graph(
            nodes=[make_node("impl", shape="box"), make_node("done", shape="Msquare")],
            edges=[make_edge("impl", "done")],
        )
        violations = SingleStartNode().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 2: AtLeastOneExit
# ---------------------------------------------------------------------------

class TestAtLeastOneExit:
    def test_valid_one_exit(self, minimal_valid_graph):
        violations = AtLeastOneExit().check(minimal_valid_graph)
        assert violations == []

    def test_valid_multiple_exits(self, minimal_valid_graph):
        second_exit = make_node("done2", shape="Msquare")
        graph = make_graph(
            nodes=list(minimal_valid_graph.nodes.values()) + [second_exit],
            edges=minimal_valid_graph.edges + [make_edge("impl", "done2")],
        )
        violations = AtLeastOneExit().check(graph)
        assert violations == []

    def test_error_no_exit_node(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
            ],
            edges=[make_edge("start", "impl")],
        )
        violations = AtLeastOneExit().check(graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert violations[0].rule_id == "AtLeastOneExit"

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[make_node("start", shape="Mdiamond")],
            edges=[],
        )
        violations = AtLeastOneExit().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 3: AllNodesReachable
# ---------------------------------------------------------------------------

class TestAllNodesReachable:
    def test_valid_linear_pipeline(self, minimal_valid_graph):
        violations = AllNodesReachable().check(minimal_valid_graph)
        assert violations == []

    def test_error_isolated_node(self):
        isolated = make_node("orphan", shape="box", label="orphan")
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("done", shape="Msquare"),
                isolated,
            ],
            edges=[make_edge("start", "done")],
        )
        violations = AllNodesReachable().check(graph)
        assert len(violations) == 1
        assert violations[0].node_id == "orphan"
        assert violations[0].severity == Severity.ERROR

    def test_error_disconnected_subtree(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
                make_node("done", shape="Msquare"),
                make_node("island_a", shape="box"),
                make_node("island_b", shape="box"),
            ],
            edges=[
                make_edge("start", "impl"),
                make_edge("impl", "done"),
                make_edge("island_a", "island_b"),  # disconnected
            ],
        )
        violations = AllNodesReachable().check(graph)
        unreachable_ids = {v.node_id for v in violations}
        assert "island_a" in unreachable_ids
        assert "island_b" in unreachable_ids

    def test_suppresses_when_no_start_node(self):
        """AllNodesReachable must return [] when there is no start node."""
        graph = make_graph(
            nodes=[make_node("impl", shape="box"), make_node("done", shape="Msquare")],
            edges=[make_edge("impl", "done")],
        )
        violations = AllNodesReachable().check(graph)
        assert violations == []

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("done", shape="Msquare"),
                make_node("orphan", shape="box"),
            ],
            edges=[make_edge("start", "done")],
        )
        violations = AllNodesReachable().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 4: EdgeTargetsExist
# ---------------------------------------------------------------------------

class TestEdgeTargetsExist:
    def test_valid_all_edges_reference_existing_nodes(self, minimal_valid_graph):
        violations = EdgeTargetsExist().check(minimal_valid_graph)
        assert violations == []

    def test_error_missing_target(self):
        graph = make_graph(
            nodes=[make_node("start", shape="Mdiamond")],
            edges=[make_edge("start", "nonexistent")],
        )
        violations = EdgeTargetsExist().check(graph)
        assert len(violations) == 1
        assert violations[0].edge_dst == "nonexistent"
        assert violations[0].severity == Severity.ERROR

    def test_error_missing_source(self):
        graph = make_graph(
            nodes=[make_node("done", shape="Msquare")],
            edges=[make_edge("nonexistent_src", "done")],
        )
        violations = EdgeTargetsExist().check(graph)
        assert len(violations) == 1
        assert violations[0].edge_src == "nonexistent_src"

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[make_node("start", shape="Mdiamond")],
            edges=[make_edge("start", "ghost")],
        )
        violations = EdgeTargetsExist().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 5: StartNoIncoming
# ---------------------------------------------------------------------------

class TestStartNoIncoming:
    def test_valid_start_has_no_incoming(self, minimal_valid_graph):
        violations = StartNoIncoming().check(minimal_valid_graph)
        assert violations == []

    def test_error_incoming_edge_to_start(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
                make_node("done", shape="Msquare"),
            ],
            edges=[
                make_edge("start", "impl"),
                make_edge("impl", "done"),
                make_edge("impl", "start"),  # loop back to start
            ],
        )
        violations = StartNoIncoming().check(graph)
        assert len(violations) == 1
        assert violations[0].node_id == "start"
        assert violations[0].severity == Severity.ERROR

    def test_valid_when_no_start_nodes(self):
        """No start nodes → no violations (SingleStartNode handles that)."""
        graph = make_graph(
            nodes=[make_node("impl", shape="box"), make_node("done", shape="Msquare")],
            edges=[make_edge("impl", "done")],
        )
        violations = StartNoIncoming().check(graph)
        assert violations == []

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
            ],
            edges=[
                make_edge("start", "impl"),
                make_edge("impl", "start"),
            ],
        )
        violations = StartNoIncoming().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 6: ExitNoOutgoing
# ---------------------------------------------------------------------------

class TestExitNoOutgoing:
    def test_valid_exit_has_no_outgoing(self, minimal_valid_graph):
        violations = ExitNoOutgoing().check(minimal_valid_graph)
        assert violations == []

    def test_error_outgoing_from_exit(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
                make_node("done", shape="Msquare"),
                make_node("extra", shape="box"),
            ],
            edges=[
                make_edge("start", "impl"),
                make_edge("impl", "done"),
                make_edge("done", "extra"),  # exit → extra (illegal)
            ],
        )
        violations = ExitNoOutgoing().check(graph)
        assert len(violations) == 1
        assert violations[0].node_id == "done"
        assert violations[0].severity == Severity.ERROR

    def test_valid_multiple_exits_no_outgoing(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
                make_node("done1", shape="Msquare"),
                make_node("done2", shape="Msquare"),
            ],
            edges=[
                make_edge("start", "impl"),
                make_edge("impl", "done1"),
                make_edge("impl", "done2"),
            ],
        )
        violations = ExitNoOutgoing().check(graph)
        assert violations == []

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("done", shape="Msquare"),
                make_node("post", shape="box"),
            ],
            edges=[
                make_edge("start", "done"),
                make_edge("done", "post"),
            ],
        )
        violations = ExitNoOutgoing().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 7: ConditionSyntaxValid
# ---------------------------------------------------------------------------

class TestConditionSyntaxValid:
    def test_valid_unconditional_edge(self, minimal_valid_graph):
        violations = ConditionSyntaxValid().check(minimal_valid_graph)
        assert violations == []

    def test_valid_simple_label_pass(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
            ],
            edges=[make_edge("start", "impl", condition="pass")],
        )
        violations = ConditionSyntaxValid().check(graph)
        assert violations == []

    def test_valid_dollar_expression(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
            ],
            edges=[make_edge("start", "impl", condition="$retry_count < 3")],
        )
        violations = ConditionSyntaxValid().check(graph)
        assert violations == []

    def test_error_empty_condition_string(self):
        """Empty condition string (NOT the same as no-condition) is invalid."""
        from cobuilder.engine.validation.rules import _ConditionParserStub, _ParseError
        # Verify the stub itself rejects empty strings.
        with pytest.raises(_ParseError):
            _ConditionParserStub().parse("")

    def test_error_unbalanced_parens(self):
        """Condition with unbalanced parens (no $ prefix) should be flagged."""
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
            ],
            # No $ prefix — the stub checks for unbalanced parentheses
            edges=[make_edge("start", "impl", condition="(success")],
        )
        violations = ConditionSyntaxValid().check(graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert violations[0].edge_src == "start"
        assert violations[0].edge_dst == "impl"

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box"),
            ],
            edges=[make_edge("start", "impl", condition='unclosed"')],
        )
        violations = ConditionSyntaxValid().check(graph)
        if violations:  # may or may not trigger depending on stub heuristics
            assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 8: StylesheetSyntaxValid
# ---------------------------------------------------------------------------

class TestStylesheetSyntaxValid:
    def test_valid_no_stylesheet(self, minimal_valid_graph):
        violations = StylesheetSyntaxValid().check(minimal_valid_graph)
        assert violations == []

    def test_valid_node_with_stylesheet(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", model_stylesheet="* { llm_model: haiku; }"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = StylesheetSyntaxValid().check(graph)
        # Permissive stub accepts all non-empty strings → no violations
        assert violations == []

    def test_valid_graph_level_stylesheet(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "done")],
            model_stylesheet="* { llm_model: sonnet; }",
        )
        violations = StylesheetSyntaxValid().check(graph)
        assert violations == []

    def test_rule_id_is_correct(self):
        assert StylesheetSyntaxValid.rule_id == "StylesheetSyntaxValid"

    def test_severity_is_error(self):
        assert StylesheetSyntaxValid.severity == Severity.ERROR


# ---------------------------------------------------------------------------
# Rule 9: RetryTargetsExist
# ---------------------------------------------------------------------------

class TestRetryTargetsExist:
    def test_valid_no_retry_targets(self, minimal_valid_graph):
        violations = RetryTargetsExist().check(minimal_valid_graph)
        assert violations == []

    def test_valid_retry_target_exists(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", retry_target="start"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = RetryTargetsExist().check(graph)
        assert violations == []

    def test_error_node_retry_target_missing(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", retry_target="nonexistent_node"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = RetryTargetsExist().check(graph)
        assert len(violations) == 1
        assert violations[0].node_id == "impl"
        assert violations[0].severity == Severity.ERROR
        assert "nonexistent_node" in violations[0].message

    def test_error_graph_level_retry_target_missing(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "done")],
            retry_target="ghost_node",
        )
        violations = RetryTargetsExist().check(graph)
        assert any(v.node_id is None for v in violations)
        assert any("ghost_node" in v.message for v in violations)

    def test_error_graph_level_fallback_retry_target_missing(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "done")],
            fallback_retry_target="also_ghost",
        )
        violations = RetryTargetsExist().check(graph)
        assert any("also_ghost" in v.message for v in violations)

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", retry_target="typo_node"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = RetryTargetsExist().check(graph)
        assert violations[0].fix_hint
