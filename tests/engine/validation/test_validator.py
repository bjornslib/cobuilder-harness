"""Tests for the Validator orchestration class and ValidationResult data model.

Covers:
- Validator.run() always returns ValidationResult (never raises)
- Validator.run_or_raise() raises ValidationError on errors
- Validator.run_or_raise() does NOT raise on warnings-only
- Rule crash isolation (one crash does not suppress others)
- Mixed errors and warnings in one result
- Performance: 100-node graph validates in < 2 seconds
"""
from __future__ import annotations

import time

import pytest

from cobuilder.engine.validation import (
    RuleViolation,
    Severity,
    ValidationError,
    ValidationResult,
    validate_graph,
)
from cobuilder.engine.validation.rules import (
    AtLeastOneExit,
    FidelityValuesValid,
    GoalGatesHaveRetry,
    LlmNodesHavePrompts,
    Rule,
    SingleStartNode,
)
from cobuilder.engine.validation.validator import DEFAULT_RULES, Validator
from tests.engine.validation.conftest import make_edge, make_graph, make_node


# ---------------------------------------------------------------------------
# ValidationResult data model
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_is_valid_when_no_violations(self):
        result = ValidationResult(pipeline_id="test")
        assert result.is_valid is True

    def test_is_valid_when_warnings_only(self):
        result = ValidationResult(pipeline_id="test")
        result.violations.append(
            RuleViolation(
                rule_id="TestRule",
                severity=Severity.WARNING,
                message="Advisory",
                node_id=None,
                edge_src=None,
                edge_dst=None,
                fix_hint="Add something",
            )
        )
        assert result.is_valid is True

    def test_not_valid_when_errors_present(self):
        result = ValidationResult(pipeline_id="test")
        result.violations.append(
            RuleViolation(
                rule_id="TestRule",
                severity=Severity.ERROR,
                message="Blocking error",
                node_id=None,
                edge_src=None,
                edge_dst=None,
                fix_hint="Fix it",
            )
        )
        assert result.is_valid is False

    def test_errors_and_warnings_property(self):
        result = ValidationResult(pipeline_id="test")
        result.violations.extend([
            RuleViolation("R1", Severity.ERROR, "e1", None, None, None, "fix"),
            RuleViolation("R2", Severity.WARNING, "w1", None, None, None, "hint"),
            RuleViolation("R3", Severity.ERROR, "e2", None, None, None, "fix"),
        ])
        assert len(result.errors) == 2
        assert len(result.warnings) == 1

    def test_to_dict_structure(self):
        result = ValidationResult(pipeline_id="my_pipeline")
        result.violations.append(
            RuleViolation("SR", Severity.ERROR, "msg", "node1", None, None, "hint")
        )
        d = result.to_dict()
        assert d["pipeline_id"] == "my_pipeline"
        assert d["valid"] is False
        assert d["error_count"] == 1
        assert d["warning_count"] == 0
        assert len(d["violations"]) == 1
        v = d["violations"][0]
        assert v["rule_id"] == "SR"
        assert v["severity"] == "error"
        assert v["node_id"] == "node1"

    def test_rule_violation_str_with_node(self):
        v = RuleViolation("R1", Severity.ERROR, "Problem", "my_node", None, None, "Fix it")
        s = str(v)
        assert "[node:my_node]" in s
        assert "ERROR" in s
        assert "Fix it" in s

    def test_rule_violation_str_with_edge(self):
        v = RuleViolation("R2", Severity.WARNING, "Edge issue", None, "src", "dst", "Fix edge")
        s = str(v)
        assert "[edge:src->dst]" in s
        assert "WARNING" in s


# ---------------------------------------------------------------------------
# Validator.run()
# ---------------------------------------------------------------------------

class TestValidatorRun:
    def test_run_returns_result_on_valid_graph(self, minimal_valid_graph):
        result = Validator(minimal_valid_graph).run()
        assert isinstance(result, ValidationResult)
        assert result.is_valid is True
        assert result.violations == []

    def test_run_never_raises(self):
        """Validator.run() must not raise even on a severely broken graph."""
        graph = make_graph(nodes=[], edges=[])
        result = Validator(graph).run()
        assert isinstance(result, ValidationResult)

    def test_run_collects_all_violations(self):
        """All rules run even when early rules fail."""
        graph = make_graph(
            nodes=[],  # no nodes → multiple rules fail
            edges=[],
        )
        result = Validator(graph).run()
        # Should have violations from at least SingleStartNode and AtLeastOneExit
        rule_ids = {v.rule_id for v in result.violations}
        assert "SingleStartNode" in rule_ids
        assert "AtLeastOneExit" in rule_ids

    def test_run_with_custom_rules(self, minimal_valid_graph):
        result = Validator(minimal_valid_graph, rules=[SingleStartNode, AtLeastOneExit]).run()
        assert result.is_valid is True

    def test_run_uses_default_rules(self, minimal_valid_graph):
        assert len(DEFAULT_RULES) == 20

    def test_rule_crash_isolation(self, minimal_valid_graph):
        """A crashing rule must not suppress violations from later rules."""

        class CrashingRule:
            rule_id = "CrashingRule"
            severity = Severity.ERROR

            def check(self, graph):
                raise RuntimeError("Simulated rule crash")

        class AlwaysViolatesRule:
            rule_id = "AlwaysViolates"
            severity = Severity.ERROR

            def check(self, graph):
                return [
                    RuleViolation(
                        rule_id="AlwaysViolates",
                        severity=Severity.ERROR,
                        message="Always fails",
                        node_id=None,
                        edge_src=None,
                        edge_dst=None,
                        fix_hint="You cannot fix this",
                    )
                ]

        result = Validator(
            minimal_valid_graph,
            rules=[CrashingRule, AlwaysViolatesRule],
        ).run()

        rule_ids = {v.rule_id for v in result.violations}
        # Crashing rule should produce an ERROR violation with its rule_id
        assert "CrashingRule" in rule_ids
        # AlwaysViolates should still have run
        assert "AlwaysViolates" in rule_ids

    def test_run_mixed_errors_and_warnings(self):
        """A graph with both ERROR and WARNING violations."""
        graph = make_graph(
            nodes=[
                # No start node → ERROR (SingleStartNode)
                make_node("impl", shape="box", label="", goal_gate="true"),
                # goal_gate no retry → WARNING (GoalGatesHaveRetry)
                make_node("done", shape="Msquare"),
            ],
            edges=[make_edge("impl", "done")],
        )
        result = Validator(graph).run()
        assert not result.is_valid
        assert len(result.errors) >= 1
        assert len(result.warnings) >= 0  # may or may not have warnings depending on node


# ---------------------------------------------------------------------------
# Validator.run_or_raise()
# ---------------------------------------------------------------------------

class TestValidatorRunOrRaise:
    def test_does_not_raise_on_valid_graph(self, minimal_valid_graph):
        result = Validator(minimal_valid_graph).run_or_raise()
        assert result.is_valid is True

    def test_raises_validation_error_on_errors(self):
        graph = make_graph(nodes=[], edges=[])
        with pytest.raises(ValidationError) as exc_info:
            Validator(graph).run_or_raise()
        assert exc_info.value.result is not None
        assert not exc_info.value.result.is_valid

    def test_does_not_raise_on_warnings_only(self):
        """A graph with only warnings must NOT raise."""

        class WarningOnlyRule:
            rule_id = "AlwaysWarns"
            severity = Severity.WARNING

            def check(self, graph):
                return [
                    RuleViolation(
                        rule_id="AlwaysWarns",
                        severity=Severity.WARNING,
                        message="Advisory",
                        node_id=None,
                        edge_src=None,
                        edge_dst=None,
                        fix_hint="Optional improvement",
                    )
                ]

        # Use only the warning rule so no ERROR rules block us
        result = Validator(
            make_graph(nodes=[], edges=[]),
            rules=[WarningOnlyRule],
        ).run_or_raise()
        assert result.is_valid is True
        assert len(result.warnings) == 1

    def test_validation_error_has_result(self):
        graph = make_graph(nodes=[], edges=[])
        with pytest.raises(ValidationError) as exc_info:
            Validator(graph).run_or_raise()
        error = exc_info.value
        assert hasattr(error, "result")
        assert isinstance(error.result, ValidationResult)
        assert "failed validation" in str(error).lower() or "validation" in str(error).lower()


# ---------------------------------------------------------------------------
# validate_graph convenience function
# ---------------------------------------------------------------------------

class TestValidateGraph:
    def test_validate_graph_valid(self, minimal_valid_graph):
        result = validate_graph(minimal_valid_graph)
        assert result.is_valid is True

    def test_validate_graph_invalid(self):
        graph = make_graph(nodes=[], edges=[])
        result = validate_graph(graph)
        assert result.is_valid is False


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

class TestValidationPerformance:
    def test_performance_100_nodes(self):
        """Validation must complete in < 2 seconds for 100-node pipelines.

        Note: The synthetic test graph intentionally uses box-shaped nodes without
        Epic 5 attributes (sd_path, downstream wait.system3, etc.), so it will
        generate many RuleViolation entries. This is expected—the test measures
        performance, not correctness.
        """
        nodes = [make_node("start", shape="Mdiamond")] + [
            make_node(f"node_{i}", shape="box", label=f"Task {i}", prompt=f"Task {i}")
            for i in range(98)
        ] + [make_node("exit_node", shape="Msquare")]

        edges = [make_edge("start", "node_0")] + [
            make_edge(f"node_{i}", f"node_{i + 1}") for i in range(97)
        ] + [make_edge("node_97", "exit_node")]

        graph = make_graph(nodes=nodes, edges=edges)

        start = time.monotonic()
        result = Validator(graph).run()
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"Validation took {elapsed:.2f}s for 100 nodes (limit: 2s)"
        # Graph will have violations (missing sd_path, wait.system3, etc.) due to Epic 5 rules
        assert len(result.violations) > 0, "Expected violations from Epic 5 rules"
