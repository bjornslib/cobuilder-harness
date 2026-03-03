"""EdgeSelector — 5-step edge selection algorithm.

Priority order (highest to lowest):
    1. Condition truth  — edge.condition evaluates True against context
    2. Preferred label  — edge.label matches outcome.preferred_label
    3. Suggested node   — edge.target matches outcome.suggested_next
    4. Edge weight      — numeric edge.weight (highest wins)
    5. Default edge     — unlabeled, unconditioned edge; or first outgoing edge

The condition evaluator is provided as an injectable callable so that
alternative evaluators can be substituted in tests without touching
this class.  The default evaluator uses the full Epic 3 conditions package.
"""
from __future__ import annotations

import logging

from cobuilder.engine.conditions import evaluate_condition as _real_evaluate_condition
from cobuilder.engine.exceptions import NoEdgeError
from cobuilder.engine.graph import Edge, Graph, Node
from cobuilder.engine.outcome import Outcome

_log = logging.getLogger(__name__)


def _default_condition_evaluator(condition: str, context, outcome: Outcome) -> bool:
    """Real condition evaluator using the conditions package (Epic 3).

    Wraps :func:`~cobuilder.engine.conditions.evaluate_condition` with
    error isolation so that a malformed condition string never crashes the
    edge-selection loop — it simply causes the edge to be skipped.
    """
    from cobuilder.engine.conditions import (
        ConditionEvalError,
        ConditionLexError,
        ConditionParseError,
    )

    try:
        from cobuilder.engine.context import PipelineContext

        if isinstance(context, dict):
            ctx = PipelineContext(context)
        else:
            ctx = context
        return _real_evaluate_condition(condition, ctx, missing_var_default=False)
    except (ConditionEvalError, ConditionParseError, ConditionLexError) as exc:
        _log.warning("condition_eval_error edge=%s error=%s", condition, exc)
        return False
    except Exception as exc:  # pragma: no cover — unexpected errors
        _log.warning("condition_eval_unexpected_error: %s", exc)
        return False


class EdgeSelector:
    """Selects the next edge using the community-standard 5-step algorithm.

    Args:
        condition_evaluator: Optional callable with signature
                             ``(condition: str, context, outcome: Outcome) -> bool``.
                             Defaults to :func:`_default_condition_evaluator`
                             which uses the full Epic 3 conditions package.
                             Pass :func:`_stub_condition_evaluator` in tests
                             that need the legacy simple evaluator.
    """

    def __init__(self, condition_evaluator=None) -> None:
        self._evaluate = condition_evaluator or _default_condition_evaluator

    def select(
        self,
        graph: Graph,
        node: Node,
        outcome: Outcome,
        context: "Any",  # PipelineContext — avoid circular import
    ) -> Edge:
        """Select the next edge from *node*'s outgoing edges.

        Args:
            graph:   The full pipeline graph (for edge lookup).
            node:    Current node whose outgoing edges are selected from.
            outcome: The handler's returned outcome.
            context: Current pipeline context (snapshot taken internally).

        Returns:
            The selected Edge.

        Raises:
            NoEdgeError: If no step produces a result.
        """
        outgoing: list[Edge] = graph.edges_from(node.id)
        if not outgoing:
            raise NoEdgeError(
                node_id=node.id,
                available_edges="(none)",
            )

        # Use a snapshot so condition evaluation sees a stable view
        ctx_snapshot = context.snapshot() if hasattr(context, "snapshot") else dict(context)

        # Step 1: Condition match
        for edge in outgoing:
            if edge.condition and self._evaluate(edge.condition, ctx_snapshot, outcome):
                return edge

        # Step 2: Preferred label match
        if outcome.preferred_label:
            for edge in outgoing:
                if edge.label == outcome.preferred_label:
                    return edge

        # Step 3: Suggested next node
        if outcome.suggested_next:
            for edge in outgoing:
                if edge.target == outcome.suggested_next:
                    return edge

        # Step 4: Weight-based selection (highest weight wins)
        weighted = [e for e in outgoing if e.weight is not None]
        if weighted:
            return max(weighted, key=lambda e: e.weight)  # type: ignore[return-value]

        # Step 5: Default — first unlabeled/unconditioned edge, then first outgoing
        unlabeled = [e for e in outgoing if not e.label and not e.condition]
        return unlabeled[0] if unlabeled else outgoing[0]


from typing import Any  # noqa: E402


def _stub_condition_evaluator(
    condition: str,
    context: dict,
    outcome: Outcome,
) -> bool:
    """Epic 1 stub: handles only literal 'true'/'false' and simple equality.

    Epic 3 replaces this with a full recursive-descent evaluator.

    Supported syntax:
    - ``"true"`` / ``"false"``  (case-insensitive)
    - ``"outcome = success"``   (compare against outcome.status.value)
    - ``"$key = value"``        (compare context key against literal value)
    """
    stripped = condition.strip().lower()
    if stripped == "true":
        return True
    if stripped == "false":
        return False

    # Simple equality: "$key = value" or "outcome = success"
    if "=" in stripped and "==" not in stripped:
        parts = stripped.split("=", 1)
        lhs, rhs = parts[0].strip(), parts[1].strip()
        if lhs == "outcome":
            return str(outcome.status.value).lower() == rhs
        if lhs.startswith("$"):
            key = lhs  # keep the $ prefix for context lookup
            val = context.get(key, context.get(lhs[1:], None))
            return str(val).lower() == rhs if val is not None else False

    return False
