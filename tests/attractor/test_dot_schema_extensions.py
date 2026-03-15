"""Tests for DOT schema extensions: prd_ref, prd_section, solution_design, target_dir.

The validate() function returns list[Issue]. Each Issue has:
    .level   - "error" or "warning"
    .rule    - int rule number
    .message - str description
    .node    - str node ID (may be empty)

The parse_dot() function returns a dict with keys:
    graph_name, graph_attrs, nodes, edges, defaults
"""

import os
import sys

import pytest


from cobuilder.engine.dispatch_parser import parse_dot
from cobuilder.engine.validator import validate, WARNING_ATTRS, VALID_HANDLERS, HANDLER_SHAPE_MAP, REQUIRED_ATTRS

# ---------------------------------------------------------------------------
# Test fixtures (DOT strings)
# ---------------------------------------------------------------------------

DOT_WITH_NEW_ATTRS = '''
digraph "test_pipeline" {
    graph [
        prd_ref="PRD-AUTH-001"
        label="Test Pipeline"
        promise_id=""
    ];
    start [
        handler="start"
        shape=Mdiamond
        label="Start"
        status="validated"
        style=filled
        fillcolor=lightgreen
    ]
    impl_auth [
        handler="codergen"
        shape=box
        label="Implement Auth"
        status="pending"
        bead_id="AUTH-042"
        worker_type="backend-solutions-engineer"
        prd_ref="PRD-AUTH-001"
        prd_section="Epic 2: JWT Authentication"
        solution_design=".claude/documentation/SOLUTION-DESIGN-AUTH.md"
        target_dir="zenagent/agencheck/agencheck-support-agent"
        acceptance="JWT auth with refresh tokens"
        style=filled
        fillcolor=lightyellow
    ]
    validate_auth [
        handler="wait.human"
        shape=hexagon
        label="Validate Auth"
        gate="technical"
        mode="technical"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ]
    decision_auth [
        handler="conditional"
        shape=diamond
        label="Auth Result?"
    ]
    finish [
        handler="exit"
        shape=Msquare
        label="Finish"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ]

    start -> impl_auth
    impl_auth -> validate_auth
    validate_auth -> decision_auth
    decision_auth -> finish [label="pass" condition="pass"]
    decision_auth -> impl_auth [label="fail" condition="fail"]
}
'''

DOT_WITHOUT_PRD_REF = '''
digraph "legacy_pipeline" {
    graph [
        label="Legacy Pipeline"
        promise_id=""
    ];
    start [
        handler="start"
        shape=Mdiamond
        label="Start"
        status="validated"
        style=filled
        fillcolor=lightgreen
    ]
    impl_feature [
        handler="codergen"
        shape=box
        label="Implement Feature"
        status="pending"
        bead_id="FEAT-001"
        worker_type="backend-solutions-engineer"
        sd_path="docs/sds/SD-FEAT.md"
        style=filled
        fillcolor=lightyellow
    ]
    validate_unit [
        handler="wait.cobuilder"
        shape=hexagon
        label="Unit Test Gate"
        gate_type="unit"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ]
    validate_feature [
        handler="wait.human"
        shape=hexagon
        label="Validate Feature"
        gate="technical"
        mode="technical"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ]
    decision_feature [
        handler="conditional"
        shape=diamond
        label="Feature Result?"
    ]
    finish [
        handler="exit"
        shape=Msquare
        label="Finish"
        status="pending"
        style=filled
        fillcolor=lightyellow
    ]

    start -> impl_feature
    impl_feature -> validate_unit
    validate_unit -> validate_feature
    validate_feature -> decision_feature
    decision_feature -> finish [label="pass" condition="pass"]
    decision_feature -> impl_feature [label="fail" condition="fail"]
}
'''


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


def test_parser_extracts_prd_ref():
    """prd_ref on a codergen node is extracted by the generic attr parser."""
    result = parse_dot(DOT_WITH_NEW_ATTRS)
    impl_node = next(n for n in result["nodes"] if n["id"] == "impl_auth")
    assert impl_node["attrs"]["prd_ref"] == "PRD-AUTH-001"


def test_parser_extracts_prd_section():
    """prd_section on a codergen node is extracted by the generic attr parser."""
    result = parse_dot(DOT_WITH_NEW_ATTRS)
    impl_node = next(n for n in result["nodes"] if n["id"] == "impl_auth")
    assert impl_node["attrs"]["prd_section"] == "Epic 2: JWT Authentication"


def test_parser_extracts_solution_design():
    """solution_design attribute is extracted by the generic attr parser."""
    result = parse_dot(DOT_WITH_NEW_ATTRS)
    impl_node = next(n for n in result["nodes"] if n["id"] == "impl_auth")
    assert "solution_design" in impl_node["attrs"]
    assert impl_node["attrs"]["solution_design"] == ".claude/documentation/SOLUTION-DESIGN-AUTH.md"


def test_parser_extracts_target_dir():
    """target_dir attribute is extracted by the generic attr parser."""
    result = parse_dot(DOT_WITH_NEW_ATTRS)
    impl_node = next(n for n in result["nodes"] if n["id"] == "impl_auth")
    assert "target_dir" in impl_node["attrs"]
    assert impl_node["attrs"]["target_dir"] == "zenagent/agencheck/agencheck-support-agent"


def test_parser_extracts_all_four_new_attributes():
    """All four new schema attributes are extracted in a single parse pass."""
    result = parse_dot(DOT_WITH_NEW_ATTRS)
    impl_node = next(n for n in result["nodes"] if n["id"] == "impl_auth")
    for attr in ("prd_ref", "prd_section", "solution_design", "target_dir"):
        assert attr in impl_node["attrs"], f"Expected attribute '{attr}' to be extracted"


def test_parser_extracts_graph_level_prd_ref():
    """prd_ref set at the graph level (in graph [...]) is accessible via graph_attrs."""
    result = parse_dot(DOT_WITH_NEW_ATTRS)
    assert result["graph_attrs"].get("prd_ref") == "PRD-AUTH-001"


def test_parser_graph_attrs_absent_when_not_set():
    """When graph-level prd_ref is absent, graph_attrs should not have the key."""
    result = parse_dot(DOT_WITHOUT_PRD_REF)
    assert "prd_ref" not in result["graph_attrs"]


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------


def test_validator_accepts_pipeline_with_prd_ref():
    """A codergen node WITH prd_ref should produce no prd_ref-related warnings."""
    data = parse_dot(DOT_WITH_NEW_ATTRS)
    issues = validate(data)
    prd_warnings = [
        i for i in issues
        if i.level == "warning" and "prd_ref" in i.message
    ]
    assert len(prd_warnings) == 0, (
        f"Expected no prd_ref warnings when prd_ref is present, got: {prd_warnings}"
    )


def test_validator_warns_on_missing_prd_ref():
    """A codergen node WITHOUT prd_ref should generate a warning (not an error)."""
    data = parse_dot(DOT_WITHOUT_PRD_REF)
    issues = validate(data)

    prd_errors = [
        i for i in issues
        if i.level == "error" and "prd_ref" in i.message
    ]
    assert len(prd_errors) == 0, (
        f"Missing prd_ref must produce a warning, not an error. Got errors: {prd_errors}"
    )

    prd_warnings = [
        i for i in issues
        if i.level == "warning" and "prd_ref" in i.message
    ]
    assert len(prd_warnings) >= 1, (
        f"Expected at least one warning about missing prd_ref, got: {[str(i) for i in issues]}"
    )


def test_validator_warns_on_missing_acceptance():
    """A codergen node WITHOUT acceptance should generate a warning."""
    data = parse_dot(DOT_WITHOUT_PRD_REF)
    issues = validate(data)
    ac_warnings = [
        i for i in issues
        if i.level == "warning" and "acceptance" in i.message
    ]
    assert len(ac_warnings) >= 1, (
        f"Expected warning about missing 'acceptance', got: {[str(i) for i in issues]}"
    )


def test_backward_compatibility_no_errors():
    """Legacy DOT without new attributes should produce ZERO errors (backward compat)."""
    data = parse_dot(DOT_WITHOUT_PRD_REF)
    issues = validate(data)
    errors = [i for i in issues if i.level == "error"]
    assert len(errors) == 0, (
        f"Legacy DOT without new optional attrs should have no errors. Got: {errors}"
    )


def test_validator_issue_level_for_missing_prd_ref_is_warning():
    """Verify the Issue.level is exactly 'warning' (not 'error') for missing prd_ref."""
    data = parse_dot(DOT_WITHOUT_PRD_REF)
    issues = validate(data)
    prd_issues = [i for i in issues if "prd_ref" in i.message]
    assert len(prd_issues) >= 1
    for issue in prd_issues:
        assert issue.level == "warning", (
            f"Missing prd_ref must be a warning, got level='{issue.level}'"
        )


def test_warning_attrs_constant_includes_codergen():
    """WARNING_ATTRS must define recommended attrs for codergen handler."""
    assert "codergen" in WARNING_ATTRS
    assert "prd_ref" in WARNING_ATTRS["codergen"]
    assert "acceptance" in WARNING_ATTRS["codergen"]


def test_validator_no_extra_errors_for_new_attrs():
    """Nodes with new optional attrs should not trigger any errors related to them."""
    data = parse_dot(DOT_WITH_NEW_ATTRS)
    issues = validate(data)
    errors = [i for i in issues if i.level == "error"]
    # Only check that no error mentions the new optional attributes
    for attr in ("prd_section", "solution_design", "target_dir"):
        attr_errors = [e for e in errors if attr in e.message]
        assert len(attr_errors) == 0, (
            f"Attribute '{attr}' should never produce errors, got: {attr_errors}"
        )


def test_validator_warning_node_id_matches_codergen_node():
    """The warning Issue.node should reference the codergen node that is missing prd_ref."""
    data = parse_dot(DOT_WITHOUT_PRD_REF)
    issues = validate(data)
    prd_warnings = [
        i for i in issues
        if i.level == "warning" and "prd_ref" in i.message
    ]
    assert len(prd_warnings) >= 1
    # The node field should reference the codergen node
    assert prd_warnings[0].node == "impl_feature", (
        f"Expected warning node to be 'impl_feature', got '{prd_warnings[0].node}'"
    )


# ---------------------------------------------------------------------------
# Research and Refine handler tests
# ---------------------------------------------------------------------------

DOT_WITH_RESEARCH_AND_REFINE = '''
digraph "test_research_refine" {
    graph [
        label="Research-Refine Pipeline"
        prd_ref="PRD-TEST-002"
        promise_id=""
    ];
    start [
        handler="start"
        shape=Mdiamond
        label="Start"
        status="validated"
    ]
    research_g1 [
        shape=tab
        handler="research"
        label="Research\\nG1 Patterns"
        solution_design="docs/sds/SD-TEST.md"
        research_queries="nextjs,supabase"
        prd_ref="PRD-TEST-002"
        status="pending"
    ]
    refine_g1 [
        shape=note
        handler="refine"
        label="Refine\\nG1 Patterns"
        solution_design="docs/sds/SD-TEST.md"
        evidence_path=".claude/evidence/research_g1/research-findings.json"
        prd_ref="PRD-TEST-002"
        status="pending"
    ]
    impl_g1 [
        handler="codergen"
        shape=box
        label="Implement G1"
        status="pending"
        bead_id="G1-001"
        worker_type="backend-solutions-engineer"
        prd_ref="PRD-TEST-002"
        sd_path="docs/sds/SD-TEST.md"
        acceptance="G1 works correctly"
    ]
    validate_unit_g1 [
        handler="wait.cobuilder"
        shape=hexagon
        label="Unit Test G1"
        gate_type="unit"
        status="pending"
    ]
    validate_g1 [
        handler="wait.human"
        shape=hexagon
        label="Validate G1"
        gate="technical"
        mode="technical"
        status="pending"
    ]
    decision_g1 [
        handler="conditional"
        shape=diamond
        label="G1 Result?"
    ]
    finish [
        handler="exit"
        shape=Msquare
        label="Finish"
        status="pending"
    ]

    start -> research_g1
    research_g1 -> refine_g1 [label="research_complete"]
    refine_g1 -> impl_g1 [label="refine_complete"]
    impl_g1 -> validate_unit_g1
    validate_unit_g1 -> validate_g1
    validate_g1 -> decision_g1
    decision_g1 -> finish [label="pass" condition="pass"]
    decision_g1 -> impl_g1 [label="fail" condition="fail"]
}
'''

DOT_WITH_REFINE_MISSING_EVIDENCE_PATH = '''
digraph "test_refine_missing" {
    graph [label="Missing evidence_path" promise_id=""];
    start [handler="start" shape=Mdiamond label="Start" status="validated"]
    refine_bad [
        shape=note
        handler="refine"
        label="Refine\\nBad"
        solution_design="docs/sds/SD-TEST.md"
        status="pending"
    ]
    finish [handler="exit" shape=Msquare label="Finish" status="pending"]
    start -> refine_bad
    refine_bad -> finish
}
'''

DOT_WITH_REFINE_WRONG_SHAPE = '''
digraph "test_refine_shape" {
    graph [label="Wrong shape" promise_id=""];
    start [handler="start" shape=Mdiamond label="Start" status="validated"]
    refine_bad [
        shape=box
        handler="refine"
        label="Refine\\nBad"
        solution_design="docs/sds/SD-TEST.md"
        evidence_path=".claude/evidence/research/findings.json"
        status="pending"
    ]
    finish [handler="exit" shape=Msquare label="Finish" status="pending"]
    start -> refine_bad
    refine_bad -> finish
}
'''


def test_valid_handlers_includes_research_and_refine():
    """VALID_HANDLERS constant includes research and refine."""
    assert "research" in VALID_HANDLERS
    assert "refine" in VALID_HANDLERS


def test_handler_shape_map_research_tab():
    """research handler maps to tab shape."""
    assert HANDLER_SHAPE_MAP["research"] == "tab"


def test_handler_shape_map_refine_note():
    """refine handler maps to note shape."""
    assert HANDLER_SHAPE_MAP["refine"] == "note"


def test_required_attrs_research():
    """research handler requires label, handler, solution_design."""
    assert "research" in REQUIRED_ATTRS
    assert "label" in REQUIRED_ATTRS["research"]
    assert "handler" in REQUIRED_ATTRS["research"]
    assert "solution_design" in REQUIRED_ATTRS["research"]


def test_required_attrs_refine():
    """refine handler requires label, handler, solution_design, evidence_path."""
    assert "refine" in REQUIRED_ATTRS
    assert "label" in REQUIRED_ATTRS["refine"]
    assert "handler" in REQUIRED_ATTRS["refine"]
    assert "solution_design" in REQUIRED_ATTRS["refine"]
    assert "evidence_path" in REQUIRED_ATTRS["refine"]


def test_warning_attrs_research():
    """research handler has prd_ref and research_queries as warning attrs."""
    assert "research" in WARNING_ATTRS
    assert "prd_ref" in WARNING_ATTRS["research"]
    assert "research_queries" in WARNING_ATTRS["research"]


def test_warning_attrs_refine():
    """refine handler has prd_ref as warning attr."""
    assert "refine" in WARNING_ATTRS
    assert "prd_ref" in WARNING_ATTRS["refine"]


def test_validator_accepts_research_refine_codergen_chain():
    """A pipeline with research -> refine -> codergen chain produces no errors."""
    data = parse_dot(DOT_WITH_RESEARCH_AND_REFINE)
    issues = validate(data)
    errors = [i for i in issues if i.level == "error"]
    assert len(errors) == 0, (
        f"Expected no errors for research->refine->codergen chain, got: "
        f"{[str(e) for e in errors]}"
    )


def test_validator_errors_on_refine_missing_evidence_path():
    """A refine node without evidence_path produces an error."""
    data = parse_dot(DOT_WITH_REFINE_MISSING_EVIDENCE_PATH)
    issues = validate(data)
    evidence_errors = [
        i for i in issues
        if i.level == "error" and "evidence_path" in i.message
    ]
    assert len(evidence_errors) >= 1, (
        f"Expected error about missing evidence_path, got: {[str(i) for i in issues]}"
    )


def test_validator_errors_on_refine_wrong_shape():
    """A refine node with shape=box (instead of note) produces an error."""
    data = parse_dot(DOT_WITH_REFINE_WRONG_SHAPE)
    issues = validate(data)
    shape_errors = [
        i for i in issues
        if i.level == "error" and "shape" in i.message.lower() and "refine" in i.message
    ]
    assert len(shape_errors) >= 1, (
        f"Expected shape mismatch error for refine node, got: {[str(i) for i in issues]}"
    )
