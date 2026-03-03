"""Public API for the Epic 2 Pre-Execution Validation Suite.

Consumers should import from this module:

    from cobuilder.engine.validation import (
        Severity,
        RuleViolation,
        ValidationResult,
        ValidationError,
        validate_graph,
    )

The ``Validator`` class itself lives in ``cobuilder.engine.validation.validator``
and is exposed here as a convenience re-export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """Severity levels for validation rule violations."""

    ERROR = "error"
    """Execution-blocking violation.  Engine will not proceed."""

    WARNING = "warning"
    """Advisory violation.  Execution continues; warning is logged."""


# ---------------------------------------------------------------------------
# RuleViolation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuleViolation:
    """A single validation rule check failure.

    Attributes:
        rule_id:   Identifier of the rule that produced this violation
                   (e.g. ``"SingleStartNode"``).
        severity:  ``ERROR`` blocks execution; ``WARNING`` is advisory.
        message:   Human-readable description of the problem.
        node_id:   Node that triggered the violation, or ``None`` for
                   graph-level violations.
        edge_src:  Source node ID of the offending edge (``None`` when
                   violation is not edge-related).
        edge_dst:  Target node ID of the offending edge (``None`` when
                   violation is not edge-related).
        fix_hint:  One-sentence suggestion for how to resolve the violation.
    """

    rule_id: str
    severity: Severity
    message: str
    node_id: str | None
    edge_src: str | None
    edge_dst: str | None
    fix_hint: str

    def __str__(self) -> str:
        loc = ""
        if self.node_id:
            loc = f" [node:{self.node_id}]"
        elif self.edge_src and self.edge_dst:
            loc = f" [edge:{self.edge_src}->{self.edge_dst}]"
        return (
            f"  {self.severity.value.upper():7s} [{self.rule_id}]{loc}: "
            f"{self.message}\n"
            f"          Fix: {self.fix_hint}"
        )


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Aggregate result from a full validation run against a ``Graph``.

    Attributes:
        pipeline_id:  DOT graph name (from ``Graph.name``).
        violations:   All ``RuleViolation`` objects collected across all rules.
    """

    pipeline_id: str
    violations: list[RuleViolation] = field(default_factory=list)

    @property
    def errors(self) -> list[RuleViolation]:
        """Violations with ``Severity.ERROR`` (execution-blocking)."""
        return [v for v in self.violations if v.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[RuleViolation]:
        """Violations with ``Severity.WARNING`` (advisory)."""
        return [v for v in self.violations if v.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        """``True`` when there are no ERROR-level violations."""
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        """Serialise to a JSON-compatible dict.

        Keys: ``pipeline_id``, ``valid``, ``error_count``, ``warning_count``,
        ``violations`` (list of violation dicts).
        """
        return {
            "pipeline_id": self.pipeline_id,
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity.value,
                    "message": v.message,
                    "node_id": v.node_id,
                    "edge_src": v.edge_src,
                    "edge_dst": v.edge_dst,
                    "fix_hint": v.fix_hint,
                }
                for v in self.violations
            ],
        }


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised by the engine when ERROR-level violations block execution.

    The ``result`` attribute carries the full ``ValidationResult`` so callers
    can inspect individual violations.

    Attributes:
        result: The ``ValidationResult`` whose ``errors`` blocked execution.
    """

    def __init__(self, result: ValidationResult) -> None:
        self.result = result
        error_count = len(result.errors)
        super().__init__(
            f"Pipeline '{result.pipeline_id}' failed validation with "
            f"{error_count} error(s). Run 'cobuilder pipeline validate "
            f"<file>.dot' for details."
        )


# ---------------------------------------------------------------------------
# Convenience re-exports
# ---------------------------------------------------------------------------

def validate_graph(graph: "Graph") -> ValidationResult:  # type: ignore[name-defined]
    """Run the full 13-rule validation suite against *graph*.

    Convenience wrapper around ``Validator(graph).run()``.

    Args:
        graph: Parsed and post-initialised ``Graph`` object.

    Returns:
        ``ValidationResult`` with all violations.  Never raises.
    """
    from cobuilder.engine.validation.validator import Validator
    return Validator(graph).run()


__all__ = [
    "Severity",
    "RuleViolation",
    "ValidationResult",
    "ValidationError",
    "validate_graph",
]
