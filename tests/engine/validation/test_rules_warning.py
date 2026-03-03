"""Tests for Rules 10-13 (WARNING-level validation rules).

Rules 10-13 produce ADVISORY violations that do not block execution.
"""
from __future__ import annotations

import pytest

from cobuilder.engine.validation import Severity
from cobuilder.engine.validation.rules import (
    FidelityValuesValid,
    GoalGatesHaveRetry,
    LlmNodesHavePrompts,
    NodeTypesKnown,
    KNOWN_SHAPES,
    VALID_FIDELITY,
)
from tests.engine.validation.conftest import make_edge, make_graph, make_node


# ---------------------------------------------------------------------------
# Rule 10: NodeTypesKnown
# ---------------------------------------------------------------------------

class TestNodeTypesKnown:
    def test_valid_all_known_shapes(self, minimal_valid_graph):
        violations = NodeTypesKnown().check(minimal_valid_graph)
        assert violations == []

    def test_valid_all_registered_shapes(self):
        """Every shape in KNOWN_SHAPES should produce no violations."""
        for shape in KNOWN_SHAPES:
            graph = make_graph(
                nodes=[
                    make_node("start", shape="Mdiamond"),
                    make_node("worker", shape=shape),
                    make_node("done", shape="Msquare"),
                ],
                edges=[
                    make_edge("start", "worker"),
                    make_edge("worker", "done"),
                ],
            )
            violations = NodeTypesKnown().check(graph)
            assert violations == [], f"Unexpected violation for known shape '{shape}'"

    def test_warning_unknown_shape(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("weird", shape="unknown_shape"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "weird"), make_edge("weird", "done")],
        )
        violations = NodeTypesKnown().check(graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert violations[0].rule_id == "NodeTypesKnown"
        assert violations[0].node_id == "weird"
        assert "unknown_shape" in violations[0].message

    def test_warning_is_not_error(self):
        """Unknown shape produces WARNING, not ERROR — execution not blocked."""
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("exotic", shape="cloud"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "exotic"), make_edge("exotic", "done")],
        )
        violations = NodeTypesKnown().check(graph)
        assert all(v.severity == Severity.WARNING for v in violations)

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[make_node("node", shape="alien_shape")],
            edges=[],
        )
        violations = NodeTypesKnown().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 11: FidelityValuesValid
# ---------------------------------------------------------------------------

class TestFidelityValuesValid:
    def test_valid_fidelity_full(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", fidelity="full"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = FidelityValuesValid().check(graph)
        assert violations == []

    def test_valid_fidelity_checkpoint(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", fidelity="checkpoint"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = FidelityValuesValid().check(graph)
        assert violations == []

    def test_valid_no_fidelity_attribute(self, minimal_valid_graph):
        """Absence of fidelity attribute is valid (optional field)."""
        violations = FidelityValuesValid().check(minimal_valid_graph)
        assert violations == []

    def test_warning_invalid_fidelity_value(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", fidelity="partial"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = FidelityValuesValid().check(graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert violations[0].node_id == "impl"
        assert "partial" in violations[0].message

    def test_warning_multiple_invalid_fidelity(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl1", shape="box", fidelity="snapshot"),
                make_node("impl2", shape="box", fidelity="incremental"),
                make_node("done", shape="Msquare"),
            ],
            edges=[
                make_edge("start", "impl1"),
                make_edge("impl1", "impl2"),
                make_edge("impl2", "done"),
            ],
        )
        violations = FidelityValuesValid().check(graph)
        assert len(violations) == 2

    def test_valid_fidelity_values_set(self):
        assert "full" in VALID_FIDELITY
        assert "checkpoint" in VALID_FIDELITY

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[make_node("impl", shape="box", fidelity="bad")],
            edges=[],
        )
        violations = FidelityValuesValid().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 12: GoalGatesHaveRetry
# ---------------------------------------------------------------------------

class TestGoalGatesHaveRetry:
    def test_valid_non_goal_gate_nodes(self, minimal_valid_graph):
        violations = GoalGatesHaveRetry().check(minimal_valid_graph)
        assert violations == []

    def test_valid_goal_gate_with_node_retry(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("gate", shape="box", goal_gate="true", retry_target="start"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "gate"), make_edge("gate", "done")],
        )
        violations = GoalGatesHaveRetry().check(graph)
        assert violations == []

    def test_valid_goal_gate_with_graph_retry(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("gate", shape="box", goal_gate="true"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "gate"), make_edge("gate", "done")],
            retry_target="start",
        )
        violations = GoalGatesHaveRetry().check(graph)
        assert violations == []

    def test_valid_goal_gate_with_fallback_retry(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("gate", shape="box", goal_gate="true"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "gate"), make_edge("gate", "done")],
            fallback_retry_target="start",
        )
        violations = GoalGatesHaveRetry().check(graph)
        assert violations == []

    def test_warning_goal_gate_no_retry(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("gate", shape="box", goal_gate="true"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "gate"), make_edge("gate", "done")],
        )
        violations = GoalGatesHaveRetry().check(graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert violations[0].node_id == "gate"

    def test_no_violation_for_non_goal_gate_without_retry(self):
        """Regular nodes don't need retry_target."""
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("regular", shape="box"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "regular"), make_edge("regular", "done")],
        )
        violations = GoalGatesHaveRetry().check(graph)
        assert violations == []

    def test_fix_hint_present(self):
        graph = make_graph(
            nodes=[make_node("gate", shape="box", goal_gate="true")],
            edges=[],
        )
        violations = GoalGatesHaveRetry().check(graph)
        assert violations[0].fix_hint


# ---------------------------------------------------------------------------
# Rule 13: LlmNodesHavePrompts
# ---------------------------------------------------------------------------

class TestLlmNodesHavePrompts:
    def test_valid_box_with_prompt(self, minimal_valid_graph):
        """The minimal_valid_graph already has prompt on the box node."""
        violations = LlmNodesHavePrompts().check(minimal_valid_graph)
        assert violations == []

    def test_valid_box_with_label_only(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", label="Implement feature"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        violations = LlmNodesHavePrompts().check(graph)
        assert violations == []

    def test_warning_box_with_no_prompt_and_no_label(self):
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("impl", shape="box", label=""),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "impl"), make_edge("impl", "done")],
        )
        # Override label to empty in attrs
        impl_node = graph.nodes["impl"]
        # Rebuild with truly empty label
        from cobuilder.engine.graph import Node
        empty_impl = Node(id="impl", shape="box", label="", attrs={"shape": "box"})
        graph.nodes["impl"] = empty_impl

        violations = LlmNodesHavePrompts().check(graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING
        assert violations[0].node_id == "impl"

    def test_no_violation_for_non_llm_shapes(self):
        """Non-LLM shapes (diamond, hexagon, etc.) don't need prompts."""
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                make_node("gate", shape="diamond"),
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "gate"), make_edge("gate", "done")],
        )
        violations = LlmNodesHavePrompts().check(graph)
        assert violations == []

    def test_warning_tab_node_without_prompt_or_label(self):
        """Tab (research) nodes are also LLM nodes and need prompt or label."""
        from cobuilder.engine.graph import Node
        empty_tab = Node(id="research", shape="tab", label="", attrs={"shape": "tab"})
        graph = make_graph(
            nodes=[
                make_node("start", shape="Mdiamond"),
                empty_tab,
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("start", "research"), make_edge("research", "done")],
        )
        violations = LlmNodesHavePrompts().check(graph)
        assert any(v.node_id == "research" for v in violations)

    def test_fix_hint_present(self):
        from cobuilder.engine.graph import Node
        empty_node = Node(id="empty", shape="box", label="", attrs={"shape": "box"})
        graph = make_graph(nodes=[empty_node], edges=[])
        violations = LlmNodesHavePrompts().check(graph)
        assert violations[0].fix_hint
