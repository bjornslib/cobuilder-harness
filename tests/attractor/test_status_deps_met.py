"""Tests for build_predecessors() cycle-exclusion fix and deps-met filter.

Verifies that retry back-edges (condition=fail or style=dashed) are excluded
from the predecessor graph so that cycles don't prevent nodes from ever
satisfying "all predecessors validated".
"""
from __future__ import annotations

import pytest

from cobuilder.engine.status import build_predecessors, get_status_table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data(nodes: list[dict], edges: list[dict]) -> dict:
    """Build a minimal parsed-DOT data dict."""
    return {"nodes": nodes, "edges": edges}


def _node(node_id: str, status: str = "pending", handler: str = "codergen") -> dict:
    return {"id": node_id, "attrs": {"status": status, "handler": handler}}


def _edge(src: str, dst: str, **attrs) -> dict:
    return {"src": src, "dst": dst, "attrs": attrs}


# ---------------------------------------------------------------------------
# build_predecessors() — exclusion tests
# ---------------------------------------------------------------------------

class TestBuildPredecessors:
    def test_excludes_condition_fail_edges(self):
        """Edges with condition=fail must NOT be added to the predecessor map."""
        data = _make_data(
            nodes=[_node("a"), _node("b")],
            edges=[_edge("b", "a", condition="fail")],  # retry back-edge
        )
        preds = build_predecessors(data)
        # a should NOT see b as a predecessor
        assert "b" not in preds["a"]
        assert preds["a"] == set()

    def test_excludes_style_dashed_edges(self):
        """Edges with style=dashed must NOT be added to the predecessor map."""
        data = _make_data(
            nodes=[_node("a"), _node("b")],
            edges=[_edge("b", "a", style="dashed")],
        )
        preds = build_predecessors(data)
        assert preds["a"] == set()

    def test_excludes_style_dashed_dotted_combo(self):
        """style containing 'dashed' (even as part of a compound string) is excluded."""
        data = _make_data(
            nodes=[_node("x"), _node("y")],
            edges=[_edge("y", "x", style="bold dashed")],
        )
        preds = build_predecessors(data)
        assert preds["x"] == set()

    def test_keeps_normal_forward_edges(self):
        """Normal (non-retry) edges MUST be kept."""
        data = _make_data(
            nodes=[_node("start"), _node("task_a")],
            edges=[_edge("start", "task_a", label="pass")],
        )
        preds = build_predecessors(data)
        assert "start" in preds["task_a"]

    def test_keeps_edges_with_condition_pass(self):
        """Edges with condition=pass are forward edges — must be kept."""
        data = _make_data(
            nodes=[_node("a"), _node("b")],
            edges=[_edge("a", "b", condition="pass")],
        )
        preds = build_predecessors(data)
        assert "a" in preds["b"]

    def test_keeps_edges_with_no_attrs(self):
        """Edges with empty attrs are forward edges — must be kept."""
        data = _make_data(
            nodes=[_node("a"), _node("b")],
            edges=[{"src": "a", "dst": "b", "attrs": {}}],
        )
        preds = build_predecessors(data)
        assert "a" in preds["b"]

    def test_mixed_edges_only_excludes_retry(self):
        """With both normal and retry edges, only retry edges are excluded."""
        data = _make_data(
            nodes=[_node("start"), _node("worker"), _node("fail_handler")],
            edges=[
                _edge("start", "worker", label="begin"),          # forward — keep
                _edge("worker", "start", condition="fail"),        # retry back-edge — exclude
                _edge("worker", "fail_handler", style="dashed"),   # retry — exclude
            ],
        )
        preds = build_predecessors(data)
        # start is predecessor of worker via the forward edge
        assert "start" in preds["worker"]
        # worker is NOT predecessor of start (condition=fail excluded)
        assert "worker" not in preds["start"]
        # worker is NOT predecessor of fail_handler (style=dashed excluded)
        assert "worker" not in preds["fail_handler"]

    def test_no_edges_returns_empty_sets(self):
        """Nodes with no edges should have empty predecessor sets."""
        data = _make_data(nodes=[_node("a"), _node("b")], edges=[])
        preds = build_predecessors(data)
        assert preds["a"] == set()
        assert preds["b"] == set()


# ---------------------------------------------------------------------------
# get_status_table(deps_met=True) — cycle-free deps-met filter
# ---------------------------------------------------------------------------

class TestGetStatusTableDepsMet:
    def test_returns_pending_node_when_forward_deps_all_validated(self):
        """A pending codergen node is returned when all forward predecessors are validated,
        even if there are retry back-edges that would create a cycle."""
        # Graph: validated_start -> pending_task <-(retry back-edge, condition=fail)-- pending_task
        # The back-edge creates a self-referencing cycle; it must be ignored.
        data = _make_data(
            nodes=[
                _node("validated_start", status="validated"),
                _node("pending_task", status="pending"),
            ],
            edges=[
                _edge("validated_start", "pending_task", label="pass"),  # forward edge
                _edge("pending_task", "validated_start", condition="fail"),  # retry — excluded
            ],
        )
        rows = get_status_table(data, deps_met=True)
        node_ids = [r["node_id"] for r in rows]
        assert "pending_task" in node_ids
        assert "validated_start" not in node_ids  # already validated, excluded

    def test_does_not_return_node_with_unvalidated_predecessor(self):
        """A pending node whose forward predecessor is NOT yet validated is excluded."""
        data = _make_data(
            nodes=[
                _node("not_yet_validated", status="active"),
                _node("blocked_task", status="pending"),
            ],
            edges=[
                _edge("not_yet_validated", "blocked_task", label="pass"),
            ],
        )
        rows = get_status_table(data, deps_met=True)
        node_ids = [r["node_id"] for r in rows]
        assert "blocked_task" not in node_ids

    def test_retry_cycle_does_not_block_deps_met(self):
        """A retry cycle (A->B->A via fail edge) must not prevent B from appearing
        when A is validated and the only forward predecessor."""
        data = _make_data(
            nodes=[
                _node("node_a", status="validated"),
                _node("node_b", status="pending"),
            ],
            edges=[
                _edge("node_a", "node_b"),                  # forward — keep
                _edge("node_b", "node_a", style="dashed"),  # retry — exclude
            ],
        )
        rows = get_status_table(data, deps_met=True)
        assert any(r["node_id"] == "node_b" for r in rows)

    def test_node_with_no_predecessors_always_passes_deps_met(self):
        """A pending node with NO predecessors trivially satisfies 'all deps validated'."""
        data = _make_data(
            nodes=[_node("orphan", status="pending")],
            edges=[],
        )
        rows = get_status_table(data, deps_met=True)
        assert any(r["node_id"] == "orphan" for r in rows)

    def test_validated_nodes_excluded_from_deps_met(self):
        """Nodes already at status=validated are never in the deps_met result."""
        data = _make_data(
            nodes=[
                _node("done_node", status="validated"),
                _node("start", status="validated"),
            ],
            edges=[_edge("start", "done_node")],
        )
        rows = get_status_table(data, deps_met=True)
        assert rows == []

    def test_chain_partial_validation(self):
        """In a chain A->B->C, if A is validated but B is pending, C must NOT appear."""
        data = _make_data(
            nodes=[
                _node("a", status="validated"),
                _node("b", status="pending"),
                _node("c", status="pending"),
            ],
            edges=[
                _edge("a", "b"),
                _edge("b", "c"),
            ],
        )
        rows = get_status_table(data, deps_met=True)
        node_ids = [r["node_id"] for r in rows]
        assert "b" in node_ids   # b's only dep (a) is validated
        assert "c" not in node_ids  # c's dep (b) is not validated
