"""Validator — runs all 13 validation rules against a parsed Graph.

Usage
-----
From the engine runner (auto-validate before execution)::

    from cobuilder.engine.validation.validator import Validator
    from cobuilder.engine.validation import ValidationError

    validator = Validator(graph)
    try:
        result = validator.run_or_raise()
    except ValidationError as exc:
        # Handle validation failure; exc.result has full details.
        raise

From the CLI validate subcommand::

    from cobuilder.engine.validation.validator import Validator
    result = Validator(graph).run()
    # render result.to_dict() or str(violation) for each violation

Design invariants
-----------------
- ``Validator.run()`` **never raises**.  Rule crashes become ERROR violations
  in the result so that all rules still run.
- All 13 rules **always run** (no early termination).  The single exception
  is the noise-suppression heuristic in ``AllNodesReachable``.
- ``RuleViolation`` is **frozen** (immutable).  Rules cannot modify violations
  after returning them.
- Rules are **stateless**.  A single rule instance can be called on multiple
  graphs.
"""
from __future__ import annotations

import logging

from cobuilder.engine.graph import Graph
from cobuilder.engine.validation import RuleViolation, Severity, ValidationError, ValidationResult
from cobuilder.engine.validation.rules import (
    AllNodesReachable,
    AtLeastOneExit,
    ConditionSyntaxValid,
    EdgeTargetsExist,
    ExitNoOutgoing,
    FidelityValuesValid,
    GoalGatesHaveRetry,
    LlmNodesHavePrompts,
    NodeTypesKnown,
    RetryTargetsExist,
    Rule,
    SingleStartNode,
    StartNoIncoming,
    StylesheetSyntaxValid,
)
from cobuilder.engine.validation.advanced_rules import (
    SdPathOnCodergen,
    WorkerTypeRegistry,
    WaitHumanAfterWaitSystem3,
    FullClusterTopology,
    WaitSystem3Requirements,
    CodergenWithoutUpstreamAT,
    MissingSkillReference,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical rule ordering — ERROR rules first, WARNING rules second.
# Do not change ordering without updating the SD.
# ---------------------------------------------------------------------------

DEFAULT_RULES: list[type] = [
    # Error-level (1-9): block execution
    SingleStartNode,
    AtLeastOneExit,
    AllNodesReachable,
    EdgeTargetsExist,
    StartNoIncoming,
    ExitNoOutgoing,
    ConditionSyntaxValid,
    StylesheetSyntaxValid,
    RetryTargetsExist,
    # Warning-level (10-13): advisory
    NodeTypesKnown,
    FidelityValuesValid,
    GoalGatesHaveRetry,
    LlmNodesHavePrompts,
    # Advanced rules - warning level
    CodergenWithoutUpstreamAT,
    MissingSkillReference,
    # Advanced rules - error level
    SdPathOnCodergen,
    WorkerTypeRegistry,
    WaitHumanAfterWaitSystem3,
    FullClusterTopology,
    WaitSystem3Requirements,
]


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class Validator:
    """Runs the full 13-rule validation suite against a parsed ``Graph``.

    Args:
        graph: Parsed and post-initialised ``Graph`` object.  The graph's
               adjacency indices must be built (``Graph.__post_init__``
               handles this automatically).
        rules: Override the default rule set.  Useful for testing individual
               rules in isolation.  Defaults to ``DEFAULT_RULES``.
    """

    def __init__(
        self,
        graph: Graph,
        rules: list[type] | None = None,
    ) -> None:
        self.graph = graph
        self._rules: list[Rule] = [cls() for cls in (rules or DEFAULT_RULES)]

    def run(self) -> ValidationResult:
        """Execute all rules and return a ``ValidationResult``.

        Rules run in order.  All rules run even when early rules fail, so the
        caller gets a complete picture of all violations.

        A rule that raises an unexpected exception (implementation bug) is
        caught and surfaced as an ERROR violation so that the remaining rules
        still run.

        Returns:
            ``ValidationResult`` with all violations across all rules.
            This method **never raises**.
        """
        result = ValidationResult(pipeline_id=self.graph.name)
        for rule in self._rules:
            try:
                violations = rule.check(self.graph)
                result.violations.extend(violations)
            except Exception as exc:
                # A rule crash is itself an error — surface it so the report
                # is complete and the author can investigate the offending
                # DOT file.
                logger.exception(
                    "Rule '%s' raised unexpectedly: %s", rule.rule_id, exc
                )
                result.violations.append(
                    RuleViolation(
                        rule_id=rule.rule_id,
                        severity=Severity.ERROR,
                        message=f"Rule check crashed unexpectedly: {exc!r}",
                        node_id=None,
                        edge_src=None,
                        edge_dst=None,
                        fix_hint=(
                            "This is a validator bug. "
                            "Report the DOT file that triggered it."
                        ),
                    )
                )
        return result

    def run_or_raise(self) -> ValidationResult:
        """Execute all rules; raise ``ValidationError`` if any errors are found.

        Used by the engine runner to block execution on ERROR violations.
        WARNING violations are present in the result but do not raise.

        Returns:
            ``ValidationResult`` when ``result.is_valid`` is ``True``.

        Raises:
            ValidationError: If ``result.is_valid`` is ``False`` (i.e. any
                             ERROR-level violations were found).
        """
        result = self.run()
        if not result.is_valid:
            raise ValidationError(result)
        # Log any warnings so they appear in execution logs.
        for warning in result.warnings:
            logger.warning(
                "[WARNING] %s: %s",
                warning.rule_id,
                warning.message,
            )
        return result


__all__ = [
    "DEFAULT_RULES",
    "Validator",
]
