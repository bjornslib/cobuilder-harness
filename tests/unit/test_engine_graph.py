"""Tests for cobuilder.engine.graph — Graph, Node, Edge dataclasses."""
from __future__ import annotations

import pytest
from cobuilder.engine.graph import (
    GOAL_GATE_SHAPES,
    LLM_NODE_SHAPES,
    SHAPE_TO_HANDLER,
    Edge,
    Graph,
    Node,
)


# ---------------------------------------------------------------------------
# SHAPE_TO_HANDLER
# ---------------------------------------------------------------------------

class TestShapeToHandlerMapping:
    def test_all_shapes_present(self):
        expected_shapes = {
            "Mdiamond", "Msquare", "box", "diamond", "hexagon",
            "component", "tripleoctagon", "parallelogram", "house",
            "tab",
        }
        assert set(SHAPE_TO_HANDLER.keys()) == expected_shapes

    def test_handler_types_correct(self):
        assert SHAPE_TO_HANDLER["Mdiamond"] == "start"
        assert SHAPE_TO_HANDLER["Msquare"] == "exit"
        assert SHAPE_TO_HANDLER["box"] == "codergen"
        assert SHAPE_TO_HANDLER["diamond"] == "conditional"
        assert SHAPE_TO_HANDLER["hexagon"] == "wait_human"
        assert SHAPE_TO_HANDLER["component"] == "parallel"
        assert SHAPE_TO_HANDLER["tripleoctagon"] == "fan_in"
        assert SHAPE_TO_HANDLER["parallelogram"] == "tool"
        assert SHAPE_TO_HANDLER["house"] == "manager_loop"
        assert SHAPE_TO_HANDLER["tab"] == "research"

    def test_llm_node_shapes(self):
        assert "box" in LLM_NODE_SHAPES

    def test_goal_gate_shapes(self):
        assert "box" in GOAL_GATE_SHAPES
        assert "hexagon" in GOAL_GATE_SHAPES
        assert "component" in GOAL_GATE_SHAPES


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

class TestEdge:
    def make_edge(self, **kwargs) -> Edge:
        defaults = {"source": "a", "target": "b"}
        defaults.update(kwargs)
        return Edge(**defaults)

    def test_id_property(self):
        e = self.make_edge(source="src", target="dst")
        assert e.id == "src->dst"

    def test_default_values(self):
        e = self.make_edge()
        assert e.label == ""
        assert e.condition == ""
        assert e.weight is None
        assert e.loop_restart is False
        assert e.attrs == {}

    def test_explicit_values(self):
        e = Edge(
            source="x",
            target="y",
            label="pass",
            condition="$status = success",
            weight=2.5,
            loop_restart=True,
            attrs={"custom": "val"},
        )
        assert e.label == "pass"
        assert e.condition == "$status = success"
        assert e.weight == 2.5
        assert e.loop_restart is True
        assert e.attrs["custom"] == "val"


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class TestNode:
    def make_node(self, shape: str = "box", **attrs) -> Node:
        return Node(id="n1", shape=shape, label="Test", attrs=attrs)

    def test_handler_type_known_shapes(self):
        for shape, expected in SHAPE_TO_HANDLER.items():
            node = Node(id="x", shape=shape)
            assert node.handler_type == expected

    def test_handler_type_unknown(self):
        node = Node(id="x", shape="galaxy")
        assert node.handler_type == "unknown"

    def test_is_start(self):
        assert Node(id="s", shape="Mdiamond").is_start is True
        assert Node(id="s", shape="box").is_start is False

    def test_is_exit(self):
        assert Node(id="e", shape="Msquare").is_exit is True
        assert Node(id="e", shape="box").is_exit is False

    def test_prompt_property(self):
        assert self.make_node(prompt="Do the thing").prompt == "Do the thing"
        assert self.make_node().prompt == ""

    def test_goal_gate_truthy_values(self):
        assert self.make_node(goal_gate="true").goal_gate is True
        assert self.make_node(goal_gate="True").goal_gate is True
        assert self.make_node(goal_gate="TRUE").goal_gate is True

    def test_goal_gate_falsy_values(self):
        assert self.make_node(goal_gate="false").goal_gate is False
        assert self.make_node().goal_gate is False  # default

    def test_dispatch_strategy_default(self):
        assert self.make_node().dispatch_strategy == "tmux"

    def test_dispatch_strategy_explicit(self):
        assert self.make_node(dispatch_strategy="sdk").dispatch_strategy == "sdk"

    def test_max_retries_default(self):
        assert self.make_node().max_retries == 3

    def test_max_retries_explicit(self):
        assert self.make_node(max_retries="5").max_retries == 5

    def test_max_retries_invalid_falls_back(self):
        assert self.make_node(max_retries="oops").max_retries == 3

    def test_retry_target_none_if_empty(self):
        assert self.make_node(retry_target="").retry_target is None
        assert self.make_node().retry_target is None

    def test_retry_target_set(self):
        assert self.make_node(retry_target="retry_node").retry_target == "retry_node"

    def test_join_policy_default(self):
        assert self.make_node().join_policy == "wait_all"

    def test_allow_partial_false_default(self):
        assert self.make_node().allow_partial is False

    def test_attractor_attributes(self):
        node = Node(
            id="impl_auth",
            shape="box",
            label="Impl auth",
            attrs={
                "bead_id": "AUTH-001",
                "worker_type": "backend-solutions-engineer",
                "acceptance": "All tests pass",
                "solution_design": "docs/sds/auth.md",
                "file_path": "src/auth.py",
                "folder_path": "src/",
                "prd_ref": "PRD-AUTH-001",
                "tool_command": "",
                "model_stylesheet": "",
            },
        )
        assert node.bead_id == "AUTH-001"
        assert node.worker_type == "backend-solutions-engineer"
        assert node.acceptance == "All tests pass"
        assert node.solution_design == "docs/sds/auth.md"
        assert node.file_path == "src/auth.py"
        assert node.folder_path == "src/"
        assert node.prd_ref == "PRD-AUTH-001"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _make_linear_graph() -> Graph:
    """A minimal 3-node linear pipeline: start → impl → exit."""
    start = Node(id="start", shape="Mdiamond", label="START")
    impl = Node(id="impl", shape="box", label="Impl", attrs={"goal_gate": "true"})
    exit_ = Node(id="finalize", shape="Msquare", label="DONE")

    edges = [
        Edge(source="start", target="impl", label="begin"),
        Edge(source="impl", target="finalize", label="pass"),
    ]

    return Graph(
        name="test_pipeline",
        attrs={"prd_ref": "PRD-TEST-001"},
        nodes={"start": start, "impl": impl, "finalize": exit_},
        edges=edges,
    )


class TestGraph:
    def test_edges_from(self):
        g = _make_linear_graph()
        edges = g.edges_from("start")
        assert len(edges) == 1
        assert edges[0].target == "impl"

    def test_edges_to(self):
        g = _make_linear_graph()
        edges = g.edges_to("finalize")
        assert len(edges) == 1
        assert edges[0].source == "impl"

    def test_edges_from_nonexistent(self):
        g = _make_linear_graph()
        assert g.edges_from("nonexistent") == []

    def test_start_node(self):
        g = _make_linear_graph()
        assert g.start_node.id == "start"

    def test_start_node_raises_if_multiple(self):
        g = _make_linear_graph()
        g.nodes["start2"] = Node(id="start2", shape="Mdiamond")
        with pytest.raises(ValueError, match="exactly one start node"):
            _ = g.start_node

    def test_start_node_raises_if_none(self):
        g = Graph(name="empty", nodes={}, edges=[])
        with pytest.raises(ValueError):
            _ = g.start_node

    def test_exit_nodes(self):
        g = _make_linear_graph()
        exits = g.exit_nodes
        assert len(exits) == 1
        assert exits[0].id == "finalize"

    def test_goal_gate_nodes(self):
        g = _make_linear_graph()
        ggs = g.goal_gate_nodes
        assert len(ggs) == 1
        assert ggs[0].id == "impl"

    def test_prd_ref(self):
        g = _make_linear_graph()
        assert g.prd_ref == "PRD-TEST-001"

    def test_prd_ref_missing(self):
        g = Graph(name="x", attrs={}, nodes={}, edges=[])
        assert g.prd_ref == ""

    def test_default_max_retry(self):
        g = Graph(name="x", attrs={}, nodes={}, edges=[])
        assert g.default_max_retry == 50

    def test_default_max_retry_explicit(self):
        g = Graph(name="x", attrs={"default_max_retry": "10"}, nodes={}, edges=[])
        assert g.default_max_retry == 10

    def test_retry_targets_none_by_default(self):
        g = Graph(name="x", attrs={}, nodes={}, edges=[])
        assert g.retry_target is None
        assert g.fallback_retry_target is None

    def test_node_lookup(self):
        g = _make_linear_graph()
        assert g.node("impl").shape == "box"

    def test_node_lookup_missing_raises(self):
        g = _make_linear_graph()
        with pytest.raises(KeyError):
            g.node("nonexistent")

    def test_contains(self):
        g = _make_linear_graph()
        assert "impl" in g
        assert "unknown" not in g

    def test_len(self):
        g = _make_linear_graph()
        assert len(g) == 3

    def test_all_node_ids(self):
        g = _make_linear_graph()
        ids = g.all_node_ids()
        assert set(ids) == {"start", "impl", "finalize"}

    def test_adjacency_rebuilt_after_post_init(self):
        """Adjacency dicts are built in __post_init__ and are correct."""
        g = _make_linear_graph()
        assert g.edges_from("impl")[0].target == "finalize"
        assert g.edges_to("impl")[0].source == "start"

    def test_promise_id(self):
        g = Graph(name="x", attrs={"promise_id": "abc-123"}, nodes={}, edges=[])
        assert g.promise_id == "abc-123"

    def test_promise_id_default(self):
        g = Graph(name="x", attrs={}, nodes={}, edges=[])
        assert g.promise_id == ""
