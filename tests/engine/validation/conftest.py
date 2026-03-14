"""Pytest fixtures for the Epic 2 validation test suite.

All fixtures work with the actual Graph model from cobuilder.engine.graph,
so tests run without any DOT files on disk or LLM calls.
"""
from __future__ import annotations

import pytest

from cobuilder.engine.graph import Edge, Graph, Node


# ---------------------------------------------------------------------------
# Node factory
# ---------------------------------------------------------------------------

def make_node(node_id: str, shape: str = "box", label: str = "", **attrs) -> Node:
    """Factory for test nodes with minimal required fields.

    Args:
        node_id: Node identifier.
        shape:   DOT shape attribute value.
        label:   Node label (defaults to node_id if empty).
        **attrs: Additional node attributes stored in ``node.attrs``.
    """
    return Node(
        id=node_id,
        shape=shape,
        label=label or node_id,
        attrs={"shape": shape, **attrs},
    )


# ---------------------------------------------------------------------------
# Edge factory
# ---------------------------------------------------------------------------

def make_edge(src: str, dst: str, condition: str = "", **attrs) -> Edge:
    """Factory for test edges.

    Args:
        src:       Source node ID.
        dst:       Target node ID.
        condition: Condition expression string.  Empty means unconditional.
        **attrs:   Additional edge attributes.
    """
    return Edge(source=src, target=dst, condition=condition, attrs=attrs)


# ---------------------------------------------------------------------------
# Graph factory
# ---------------------------------------------------------------------------

def make_graph(nodes: list[Node], edges: list[Edge], **graph_attrs) -> Graph:
    """Build a Graph with computed adjacency maps.

    Args:
        nodes:       List of ``Node`` objects.
        edges:       List of ``Edge`` objects.
        **graph_attrs: Graph-level attribute dict entries.
    """
    return Graph(
        name="test_pipeline",
        attrs=dict(graph_attrs),
        nodes={n.id: n for n in nodes},
        edges=edges,
    )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_valid_graph() -> Graph:
    """Minimal valid pipeline: start → at_writer → codergen → wait.system3 → wait.human → exit.

    This graph passes all 20 validation rules including Epic 5 rules:
    - acceptance-test-writer upstream of codergen (Rule 18)
    - codergen has sd_path attribute (Rule 14)
    - codergen has downstream wait.system3 (Rule 17)
    - wait.system3 has downstream wait.human with mode='e2e-review' (Rules 16, 17)
    """
    start = make_node("start", shape="Mdiamond", label="Start")
    at_writer = make_node(
        "at_writer",
        shape="tab",
        label="Write Tests",
        handler="acceptance_test_writer",
        prd_ref=".taskmaster/docs/PRD-TEST.md",
    )
    work = make_node(
        "impl",
        shape="box",
        label="Do work",
        prompt="Implement feature X",
        sd_path=".taskmaster/docs/SD-TEST.md",
        worker_type="backend-solutions-engineer",
    )
    wait_system3 = make_node(
        "validate",
        shape="hexagon",
        label="Validate",
        handler="wait_system3",
        gate_type="e2e",
        summary_ref=".claude/evidence/summary.md",
        bead_id="bd-test",
    )
    wait_human = make_node(
        "review",
        shape="hexagon",
        label="Human Review",
        handler="wait_human",
        mode="e2e-review",
    )
    exit_ = make_node("done", shape="Msquare", label="Done")
    return make_graph(
        nodes=[start, at_writer, work, wait_system3, wait_human, exit_],
        edges=[
            make_edge("start", "at_writer"),
            make_edge("at_writer", "impl"),
            make_edge("impl", "validate"),
            make_edge("validate", "review"),
            make_edge("review", "done"),
        ],
    )


# Expose factory functions as fixtures for use in test functions that need
# them as arguments (parametrize-friendly).

@pytest.fixture
def make_node_fixture():
    """Return the ``make_node`` factory function as a fixture."""
    return make_node


@pytest.fixture
def make_edge_fixture():
    """Return the ``make_edge`` factory function as a fixture."""
    return make_edge


@pytest.fixture
def make_graph_fixture():
    """Return the ``make_graph`` factory function as a fixture."""
    return make_graph
