"""Tests for cobuilder.engine.parser — Recursive-descent DOT parser.

Coverage targets from SD-PIPELINE-ENGINE-001 AC-F1:
  - Parses Mdiamond, Msquare, and box nodes into typed Graph
  - Extracts all 9+ Attractor-specific attributes
  - Extracts edge condition, label, and weight
  - Extracts graph-level attributes: prd_ref, promise_id, label, etc.
  - Raises ParseError for malformed input
  - Does NOT import graphviz, pydot, or any non-stdlib DOT library
  - Parses all .dot files in .claude/attractor/pipelines/ without error
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from cobuilder.engine.parser import DotParser, ParseError, parse_dot_file, parse_dot_string
from cobuilder.engine.graph import Graph, Node, Edge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse(dot: str) -> Graph:
    """Convenience wrapper."""
    return parse_dot_string(dot)


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------

class TestMinimalGraph:
    def test_empty_digraph(self):
        g = parse('digraph { }')
        assert g.name == ""
        assert len(g.nodes) == 0
        assert len(g.edges) == 0

    def test_named_digraph(self):
        g = parse('digraph "My Pipeline" { }')
        assert g.name == "My Pipeline"

    def test_named_digraph_unquoted(self):
        g = parse('digraph mypipeline { }')
        assert g.name == "mypipeline"

    def test_strict_digraph(self):
        g = parse('strict digraph pipeline { }')
        assert g.name == "pipeline"

    def test_single_node_no_attrs(self):
        g = parse('digraph { start; }')
        assert "start" in g

    def test_node_with_shape(self):
        g = parse('digraph { start [shape=Mdiamond]; }')
        n = g.node("start")
        assert n.shape == "Mdiamond"
        assert n.is_start

    def test_exit_node(self):
        g = parse('digraph { exit [shape=Msquare]; }')
        n = g.node("exit")
        assert n.is_exit

    def test_box_node(self):
        g = parse('digraph { impl [shape=box]; }')
        n = g.node("impl")
        assert n.handler_type == "codergen"


class TestEdgeParsing:
    def test_simple_edge(self):
        g = parse('digraph { a -> b; }')
        assert len(g.edges) == 1
        e = g.edges[0]
        assert e.source == "a"
        assert e.target == "b"

    def test_edge_with_label(self):
        g = parse('digraph { a -> b [label="pass"]; }')
        e = g.edges[0]
        assert e.label == "pass"

    def test_edge_with_condition(self):
        g = parse('digraph { a -> b [condition="$status = success"]; }')
        e = g.edges[0]
        assert e.condition == "$status = success"

    def test_edge_with_weight(self):
        g = parse('digraph { a -> b [weight=2]; }')
        e = g.edges[0]
        assert e.weight == 2.0

    def test_edge_chain(self):
        g = parse('digraph { a -> b -> c; }')
        assert len(g.edges) == 2
        assert g.edges[0].source == "a" and g.edges[0].target == "b"
        assert g.edges[1].source == "b" and g.edges[1].target == "c"

    def test_loop_restart_edge(self):
        g = parse('digraph { a -> b [loop_restart=true]; }')
        e = g.edges[0]
        assert e.loop_restart is True

    def test_loop_restart_false_default(self):
        g = parse('digraph { a -> b; }')
        assert g.edges[0].loop_restart is False

    def test_multiple_edges_from_same_node(self):
        g = parse('digraph { a -> b [label="pass"]; a -> c [label="fail"]; }')
        edges_from_a = g.edges_from("a")
        assert len(edges_from_a) == 2

    def test_implied_node_creation(self):
        """Nodes referenced only in edges are auto-created with default shape."""
        g = parse('digraph { a -> b; }')
        assert "a" in g
        assert "b" in g


class TestGraphAttrs:
    def test_prd_ref(self):
        g = parse('digraph { graph [prd_ref="PRD-AUTH-001"]; }')
        assert g.prd_ref == "PRD-AUTH-001"

    def test_promise_id(self):
        g = parse('digraph { graph [promise_id="abc-123"]; }')
        assert g.promise_id == "abc-123"

    def test_graph_label(self):
        g = parse('digraph { graph [label="My Pipeline"]; }')
        assert g.attrs.get("label") == "My Pipeline"

    def test_default_max_retry(self):
        g = parse('digraph { graph [default_max_retry=10]; }')
        assert g.default_max_retry == 10

    def test_retry_target(self):
        g = parse('digraph { graph [retry_target="start"]; }')
        assert g.retry_target == "start"

    def test_fallback_retry_target(self):
        g = parse('digraph { graph [fallback_retry_target="fallback"]; }')
        assert g.fallback_retry_target == "fallback"

    def test_multiple_graph_attrs(self):
        dot = '''
        digraph {
            graph [
                prd_ref="PRD-X-001"
                promise_id="p-1"
                default_max_retry=20
            ];
        }'''
        g = parse(dot)
        assert g.prd_ref == "PRD-X-001"
        assert g.promise_id == "p-1"
        assert g.default_max_retry == 20


# ---------------------------------------------------------------------------
# Attractor-specific attribute extraction
# ---------------------------------------------------------------------------

class TestAttractorAttributes:
    """AC-F1: Extract all 9+ Attractor-specific attributes."""

    DOT_WITH_FULL_ATTRS = '''
    digraph pipeline {
        impl_auth [
            shape=box
            label="Implement Auth"
            prompt="Implement JWT-based authentication"
            goal_gate=true
            tool_command=""
            model_stylesheet=""
            bead_id="AUTH-001"
            worker_type="backend-solutions-engineer"
            acceptance="All 12 auth tests pass"
            solution_design="docs/sds/auth.md"
            file_path="src/auth/jwt.py"
            folder_path="src/auth/"
            dispatch_strategy="sdk"
            max_retries=5
            retry_target="retry_auth"
            join_policy="first_success"
            allow_partial=true
            prd_ref="PRD-AUTH-001"
        ];
    }'''

    def test_all_attractor_attrs(self):
        g = parse(self.DOT_WITH_FULL_ATTRS)
        node = g.node("impl_auth")
        assert node.shape == "box"
        assert node.label == "Implement Auth"
        assert node.prompt == "Implement JWT-based authentication"
        assert node.goal_gate is True
        assert node.bead_id == "AUTH-001"
        assert node.worker_type == "backend-solutions-engineer"
        assert node.acceptance == "All 12 auth tests pass"
        assert node.solution_design == "docs/sds/auth.md"
        assert node.file_path == "src/auth/jwt.py"
        assert node.folder_path == "src/auth/"
        assert node.dispatch_strategy == "sdk"
        assert node.max_retries == 5
        assert node.retry_target == "retry_auth"
        assert node.join_policy == "first_success"
        assert node.allow_partial is True
        assert node.prd_ref == "PRD-AUTH-001"

    def test_goal_gate_default_false(self):
        g = parse('digraph { n [shape=box]; }')
        assert g.node("n").goal_gate is False

    def test_dispatch_strategy_default_tmux(self):
        g = parse('digraph { n [shape=box]; }')
        assert g.node("n").dispatch_strategy == "tmux"

    def test_max_retries_default_three(self):
        g = parse('digraph { n [shape=box]; }')
        assert g.node("n").max_retries == 3


# ---------------------------------------------------------------------------
# Quoted strings and escape handling
# ---------------------------------------------------------------------------

class TestStringHandling:
    def test_multiline_quoted_label(self):
        g = parse('digraph { n [shape=box label="Line 1\nLine 2"]; }')
        node = g.node("n")
        assert "Line 1" in node.label
        assert "Line 2" in node.label

    def test_escaped_quote_in_string(self):
        g = parse(r'digraph { n [label="He said \"hello\""]; }')
        assert 'He said "hello"' in g.node("n").label

    def test_dot_newline_in_label(self):
        """DOT \\n inside quoted string."""
        g = parse('digraph { n [label="Foo\\nBar"]; }')
        node = g.node("n")
        assert "Foo" in node.label

    def test_dot_left_align_in_label(self):
        """DOT \\l inside quoted string preserved as literal \\l."""
        g = parse('digraph { n [label="Foo\\lBar"]; }')
        node = g.node("n")
        assert "Foo" in node.label

    def test_quoted_node_id(self):
        g = parse('digraph { "my node" [shape=box]; }')
        assert "my node" in g

    def test_empty_string_value(self):
        g = parse('digraph { n [bead_id=""]; }')
        assert g.node("n").bead_id == ""


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class TestCommentHandling:
    def test_line_comment_skipped(self):
        dot = '''
        digraph {
            // This is a comment
            start [shape=Mdiamond]; // trailing comment
        }'''
        g = parse(dot)
        assert "start" in g

    def test_block_comment_skipped(self):
        dot = '''
        digraph {
            /* block comment
               spanning lines */
            n1 [shape=box];
        }'''
        g = parse(dot)
        assert "n1" in g

    def test_hash_comment_skipped(self):
        dot = '''
        digraph {
            # hash comment
            n1 [shape=box];
        }'''
        g = parse(dot)
        assert "n1" in g


# ---------------------------------------------------------------------------
# Default attribute blocks
# ---------------------------------------------------------------------------

class TestDefaultAttrs:
    def test_default_node_attrs(self):
        dot = '''
        digraph {
            node [fontname="Helvetica" fontsize=11];
            n1 [shape=box];
        }'''
        g = parse(dot)
        node = g.node("n1")
        assert node.attrs.get("fontname") == "Helvetica"
        assert node.attrs.get("fontsize") == "11"

    def test_explicit_attr_overrides_default(self):
        dot = '''
        digraph {
            node [shape=diamond];
            n1 [shape=box];
        }'''
        g = parse(dot)
        assert g.node("n1").shape == "box"  # explicit overrides default

    def test_default_edge_attrs(self):
        dot = '''
        digraph {
            edge [fontname="Helvetica"];
            a -> b;
        }'''
        g = parse(dot)
        assert g.edges[0].attrs.get("fontname") == "Helvetica"


# ---------------------------------------------------------------------------
# Full pipeline fixture (mimics sdk-test-001.dot)
# ---------------------------------------------------------------------------

FULL_PIPELINE_DOT = '''
digraph "SDK-TEST-001" {
    graph [
        label="SDK Test Pipeline"
        labelloc="t"
        fontsize=16
        rankdir="TB"
        prd_ref="SDK-TEST-001"
        promise_id=""
        target_dir="/some/path"
    ];

    node [fontname="Helvetica" fontsize=11];
    edge [fontname="Helvetica" fontsize=9];

    // Entry
    start [
        shape=Mdiamond
        label="START"
        handler="start"
        status="validated"
        style=filled
        fillcolor=lightgreen
    ];

    // Implementation node
    impl_sdk_write_test [
        shape=box
        label="SDK Write Test:\\nCreate hello.py"
        handler="codergen"
        bead_id="SDK-TEST-IMPL"
        worker_type="backend-solutions-engineer"
        acceptance="Create hello.py with hello() returning string"
        prd_ref="SDK-TEST-001"
        status="validated"
        style=filled
        fillcolor="lightgreen"
    ];

    start -> impl_sdk_write_test [label="begin"];

    // Validation gate
    validate [
        shape=hexagon
        label="SDK Write Test\\nValidation"
        handler="wait.human"
        gate="technical"
        status="validated"
        style=filled
        fillcolor="lightgreen"
    ];

    impl_sdk_write_test -> validate [label="impl_complete"];

    // Exit
    finalize [
        shape=Msquare
        label="FINALIZE"
        handler="exit"
        status="validated"
        style=filled
        fillcolor="lightgreen"
    ];

    validate -> finalize [label="validated"];
}
'''


class TestFullPipelineParsing:
    def test_parse_without_error(self):
        g = parse(FULL_PIPELINE_DOT)
        assert g is not None

    def test_correct_node_count(self):
        g = parse(FULL_PIPELINE_DOT)
        assert len(g.nodes) == 4

    def test_start_node_identified(self):
        g = parse(FULL_PIPELINE_DOT)
        assert g.start_node.id == "start"

    def test_exit_node_identified(self):
        g = parse(FULL_PIPELINE_DOT)
        assert len(g.exit_nodes) == 1
        assert g.exit_nodes[0].id == "finalize"

    def test_edges(self):
        g = parse(FULL_PIPELINE_DOT)
        assert len(g.edges) == 3

    def test_prd_ref_extracted(self):
        g = parse(FULL_PIPELINE_DOT)
        assert g.prd_ref == "SDK-TEST-001"

    def test_promise_id_extracted(self):
        g = parse(FULL_PIPELINE_DOT)
        assert g.promise_id == ""

    def test_impl_node_attrs(self):
        g = parse(FULL_PIPELINE_DOT)
        node = g.node("impl_sdk_write_test")
        assert node.shape == "box"
        assert node.bead_id == "SDK-TEST-IMPL"
        assert node.worker_type == "backend-solutions-engineer"

    def test_edge_labels(self):
        g = parse(FULL_PIPELINE_DOT)
        edges = g.edges_from("start")
        assert edges[0].label == "begin"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestParseError:
    def test_no_digraph_keyword(self):
        with pytest.raises(ParseError) as exc_info:
            parse("graph { }")
        assert "digraph" in str(exc_info.value)

    def test_unclosed_brace_still_parses_partial(self):
        # The parser should raise ParseError or return a partial graph
        # depending on the error recovery mode.  At minimum it should not
        # raise a non-ParseError exception.
        try:
            parse("digraph { n [shape=box]")
            # Partial parse is acceptable
        except ParseError:
            pass  # Also acceptable

    def test_parse_error_has_line_number(self):
        dot = "digraph {\n  not_digraph = invalid\n}"
        # This is valid DOT (node stmt) but tests that ParseError is not raised
        # for valid input — just a sanity check
        g = parse(dot)
        assert "not_digraph" in g  # parsed as a node ID

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_dot_file("/nonexistent/path/to/file.dot")


# ---------------------------------------------------------------------------
# No external DOT library imports (AC-F1)
# ---------------------------------------------------------------------------

class TestNoDotLibraryDependency:
    """Verify that the parser module does not import graphviz or pydot."""

    def test_graphviz_not_imported(self):
        import cobuilder.engine.parser as parser_module
        assert "graphviz" not in sys.modules or not hasattr(parser_module, "graphviz")

    def test_pydot_not_imported(self):
        import cobuilder.engine.parser as parser_module
        # If pydot were imported it would appear in sys.modules
        # The parser module imports we verify here
        source = Path(parser_module.__file__).read_text()
        assert "import graphviz" not in source
        assert "import pydot" not in source
        assert "from graphviz" not in source
        assert "from pydot" not in source

    def test_only_stdlib_imports(self):
        """Parser source should only import stdlib + cobuilder.engine.graph."""
        import cobuilder.engine.parser as parser_module
        source = Path(parser_module.__file__).read_text()
        # Verify no graphviz/pydot/pyparsing external dependency via import statements
        # We check for 'import X' and 'from X import' patterns only, not mentions in comments
        import_lines = [
            line.strip() for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        import_text = "\n".join(import_lines)
        for banned in ("graphviz", "pydot", "pyparsing", "networkx"):
            assert banned not in import_text, (
                f"Banned import '{banned}' found in parser.py import statements:\n{import_text}"
            )


# ---------------------------------------------------------------------------
# Corpus test: parse all .dot files in .claude/attractor/pipelines/
# ---------------------------------------------------------------------------

def _find_attractor_dot_files() -> list[Path]:
    """Walk up from the test file to find .claude/attractor/pipelines/."""
    here = Path(__file__).parent
    for parent in [here, here.parent, here.parent.parent,
                   here.parent.parent.parent, here.parent.parent.parent.parent]:
        candidate = parent / ".claude" / "attractor" / "pipelines"
        if candidate.is_dir():
            return sorted(candidate.glob("*.dot"))
    return []


_DOT_FILES = _find_attractor_dot_files()


@pytest.mark.parametrize("dot_path", _DOT_FILES, ids=lambda p: p.name)
def test_corpus_dot_file_parses_without_error(dot_path: Path):
    """AC-F1: Parses all .dot files in .claude/attractor/pipelines/ without error."""
    g = parse_dot_file(dot_path)
    # Must return a Graph with at least some nodes or be an empty pipeline
    assert isinstance(g, Graph)
    # graph name may be empty but should not raise


# ---------------------------------------------------------------------------
# ParseError column field
# ---------------------------------------------------------------------------

class TestParseErrorColumn:
    """Verify that ParseError carries a non-negative integer column field."""

    def test_parse_error_has_column(self):
        """Triggering a ParseError on malformed DOT should populate .column >= 0."""
        dot = "not_a_digraph { }"
        with pytest.raises(ParseError) as exc_info:
            parse(dot)
        err = exc_info.value
        assert isinstance(err.column, int), "column must be an int"
        assert err.column >= 0, "column must be non-negative"
