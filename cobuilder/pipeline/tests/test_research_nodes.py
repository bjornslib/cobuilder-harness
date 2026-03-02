"""Tests for research node support in validator and graph modules."""

import pytest


class TestValidatorResearchHandler:
    """Verify validator.py accepts research nodes and enforces their schema."""

    def test_validator_accepts_research_handler(self):
        """Research handler is in VALID_HANDLERS."""
        from cobuilder.pipeline.validator import VALID_HANDLERS

        assert "research" in VALID_HANDLERS

    def test_handler_shape_map_research(self):
        """Research handler maps to 'tab' shape."""
        from cobuilder.pipeline.validator import HANDLER_SHAPE_MAP

        assert HANDLER_SHAPE_MAP["research"] == "tab"

    def test_required_attrs_research(self):
        """Research nodes require label, handler, downstream_node, solution_design."""
        from cobuilder.pipeline.validator import REQUIRED_ATTRS

        required = REQUIRED_ATTRS["research"]
        assert "label" in required
        assert "handler" in required
        assert "downstream_node" in required
        assert "solution_design" in required

    def test_warning_attrs_research(self):
        """research_queries is a recommended attribute for research nodes."""
        from cobuilder.pipeline.validator import WARNING_ATTRS

        assert "research_queries" in WARNING_ATTRS["research"]

    def test_validator_rejects_research_missing_solution_design(self):
        """Research node without solution_design should produce an error."""
        from cobuilder.pipeline.validator import validate

        data = {
            "nodes": [
                {
                    "id": "start",
                    "attrs": {
                        "shape": "Mdiamond",
                        "handler": "start",
                        "label": "Start",
                    },
                },
                {
                    "id": "research_auth",
                    "attrs": {
                        "shape": "tab",
                        "handler": "research",
                        "label": "Research Auth",
                        "downstream_node": "impl_auth",
                        # solution_design intentionally missing
                    },
                },
                {
                    "id": "exit",
                    "attrs": {
                        "shape": "Msquare",
                        "handler": "exit",
                        "label": "Exit",
                    },
                },
            ],
            "edges": [
                {"src": "start", "dst": "research_auth", "attrs": {}},
                {"src": "research_auth", "dst": "exit", "attrs": {}},
            ],
            "graph_attrs": {},
        }

        issues = validate(data)
        error_msgs = [i.message for i in issues if i.level == "error"]
        assert any("solution_design" in m and "research" in m for m in error_msgs)

    def test_validator_rejects_research_missing_downstream_node(self):
        """Research node without downstream_node should produce an error."""
        from cobuilder.pipeline.validator import validate

        data = {
            "nodes": [
                {
                    "id": "start",
                    "attrs": {
                        "shape": "Mdiamond",
                        "handler": "start",
                        "label": "Start",
                    },
                },
                {
                    "id": "research_auth",
                    "attrs": {
                        "shape": "tab",
                        "handler": "research",
                        "label": "Research Auth",
                        "solution_design": "docs/sds/SD-AUTH-001.md",
                        # downstream_node intentionally missing
                    },
                },
                {
                    "id": "exit",
                    "attrs": {
                        "shape": "Msquare",
                        "handler": "exit",
                        "label": "Exit",
                    },
                },
            ],
            "edges": [
                {"src": "start", "dst": "research_auth", "attrs": {}},
                {"src": "research_auth", "dst": "exit", "attrs": {}},
            ],
            "graph_attrs": {},
        }

        issues = validate(data)
        error_msgs = [i.message for i in issues if i.level == "error"]
        assert any("downstream_node" in m and "research" in m for m in error_msgs)

    def test_validator_accepts_valid_research_node(self):
        """A fully-specified research node should pass validation without errors."""
        from cobuilder.pipeline.validator import validate

        data = {
            "nodes": [
                {
                    "id": "start",
                    "attrs": {
                        "shape": "Mdiamond",
                        "handler": "start",
                        "label": "Start",
                    },
                },
                {
                    "id": "research_auth",
                    "attrs": {
                        "shape": "tab",
                        "handler": "research",
                        "label": "Research Auth",
                        "downstream_node": "impl_auth",
                        "solution_design": "docs/sds/SD-AUTH-001.md",
                        "research_queries": "fastapi,pydantic",
                        "status": "pending",
                    },
                },
                {
                    "id": "exit",
                    "attrs": {
                        "shape": "Msquare",
                        "handler": "exit",
                        "label": "Exit",
                    },
                },
            ],
            "edges": [
                {"src": "start", "dst": "research_auth", "attrs": {}},
                {"src": "research_auth", "dst": "exit", "attrs": {}},
            ],
            "graph_attrs": {},
        }

        issues = validate(data)
        errors = [i for i in issues if i.level == "error"]
        assert len(errors) == 0, f"Unexpected errors: {[str(e) for e in errors]}"

    def test_validator_warns_missing_research_queries(self):
        """Missing research_queries should produce a warning, not an error."""
        from cobuilder.pipeline.validator import validate

        data = {
            "nodes": [
                {
                    "id": "start",
                    "attrs": {
                        "shape": "Mdiamond",
                        "handler": "start",
                        "label": "Start",
                    },
                },
                {
                    "id": "research_auth",
                    "attrs": {
                        "shape": "tab",
                        "handler": "research",
                        "label": "Research Auth",
                        "downstream_node": "impl_auth",
                        "solution_design": "docs/sds/SD-AUTH-001.md",
                        # research_queries intentionally missing
                    },
                },
                {
                    "id": "exit",
                    "attrs": {
                        "shape": "Msquare",
                        "handler": "exit",
                        "label": "Exit",
                    },
                },
            ],
            "edges": [
                {"src": "start", "dst": "research_auth", "attrs": {}},
                {"src": "research_auth", "dst": "exit", "attrs": {}},
            ],
            "graph_attrs": {},
        }

        issues = validate(data)
        warnings = [i for i in issues if i.level == "warning"]
        assert any("research_queries" in w.message for w in warnings)

    def test_shape_handler_consistency_research(self):
        """Research node with wrong shape should produce an error."""
        from cobuilder.pipeline.validator import validate

        data = {
            "nodes": [
                {
                    "id": "start",
                    "attrs": {
                        "shape": "Mdiamond",
                        "handler": "start",
                        "label": "Start",
                    },
                },
                {
                    "id": "research_auth",
                    "attrs": {
                        "shape": "box",  # Wrong shape for research handler
                        "handler": "research",
                        "label": "Research Auth",
                        "downstream_node": "impl_auth",
                        "solution_design": "docs/sds/SD-AUTH-001.md",
                    },
                },
                {
                    "id": "exit",
                    "attrs": {
                        "shape": "Msquare",
                        "handler": "exit",
                        "label": "Exit",
                    },
                },
            ],
            "edges": [
                {"src": "start", "dst": "research_auth", "attrs": {}},
                {"src": "research_auth", "dst": "exit", "attrs": {}},
            ],
            "graph_attrs": {},
        }

        issues = validate(data)
        errors = [i for i in issues if i.level == "error"]
        assert any("shape" in e.message.lower() and "research" in e.message for e in errors)


class TestGraphResearchSupport:
    """Verify graph.py supports research node shape and properties."""

    def test_tab_shape_maps_to_research(self):
        """SHAPE_TO_HANDLER maps 'tab' to 'research'."""
        from cobuilder.engine.graph import SHAPE_TO_HANDLER

        assert SHAPE_TO_HANDLER["tab"] == "research"

    def test_tab_in_llm_node_shapes(self):
        """'tab' shape is in LLM_NODE_SHAPES (research nodes invoke LLM)."""
        from cobuilder.engine.graph import LLM_NODE_SHAPES

        assert "tab" in LLM_NODE_SHAPES

    def test_node_handler_type_research(self):
        """Node with shape='tab' reports handler_type='research'."""
        from cobuilder.engine.graph import Node

        node = Node(id="research_auth", shape="tab", label="Research Auth")
        assert node.handler_type == "research"

    def test_node_downstream_property(self):
        """Node.downstream_node returns the downstream_node attr."""
        from cobuilder.engine.graph import Node

        node = Node(
            id="research_auth",
            shape="tab",
            label="Research Auth",
            attrs={"downstream_node": "impl_auth"},
        )
        assert node.downstream_node == "impl_auth"

    def test_node_downstream_property_default(self):
        """Node.downstream_node returns empty string when not set."""
        from cobuilder.engine.graph import Node

        node = Node(id="research_auth", shape="tab", label="Research Auth")
        assert node.downstream_node == ""

    def test_node_research_queries_property(self):
        """Node.research_queries parses comma-separated string into list."""
        from cobuilder.engine.graph import Node

        node = Node(
            id="research_auth",
            shape="tab",
            label="Research Auth",
            attrs={"research_queries": "fastapi, pydantic, supabase"},
        )
        assert node.research_queries == ["fastapi", "pydantic", "supabase"]

    def test_node_research_queries_empty(self):
        """Node.research_queries returns empty list when not set."""
        from cobuilder.engine.graph import Node

        node = Node(id="research_auth", shape="tab", label="Research Auth")
        assert node.research_queries == []

    def test_node_research_queries_single(self):
        """Node.research_queries handles single value without comma."""
        from cobuilder.engine.graph import Node

        node = Node(
            id="research_auth",
            shape="tab",
            label="Research Auth",
            attrs={"research_queries": "fastapi"},
        )
        assert node.research_queries == ["fastapi"]
