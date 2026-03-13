"""ConstraintMiddleware — enforces node state machine constraints at runtime.

Inserted into the middleware chain. Intercepts handler outcomes and validates
that the resulting node status transition is allowed by any applicable
NodeStateMachine loaded from the template manifest.

Position in chain:
    Logfire -> TokenCounting -> Retry -> **Constraint** -> Audit -> Handler
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from cobuilder.engine.outcome import OutcomeStatus
from cobuilder.engine.state_machine import ConstraintViolation, NodeStateMachine

if TYPE_CHECKING:
    from cobuilder.engine.handlers.base import HandlerRequest
    from cobuilder.engine.outcome import Outcome

logger = logging.getLogger(__name__)

# Mapping from OutcomeStatus to the node status it implies
_OUTCOME_TO_NODE_STATUS: dict[OutcomeStatus, str] = {
    OutcomeStatus.SUCCESS: "validated",
    OutcomeStatus.FAILURE: "failed",
    OutcomeStatus.PARTIAL_SUCCESS: "impl_complete",
    OutcomeStatus.WAITING: "active",
    OutcomeStatus.SKIPPED: "validated",
}


class ConstraintMiddleware:
    """Middleware that enforces node state machine constraints.

    After a handler executes and returns an Outcome, this middleware:
    1. Looks up the applicable NodeStateMachine for the node's shape/handler.
    2. Maps the OutcomeStatus to a node status string.
    3. Validates that the transition from current status to new status is allowed.
    4. Raises ConstraintViolation if the transition is disallowed.

    If no state machine applies to the node, the handler result passes through.

    Args:
        machines: List of NodeStateMachine instances to enforce.
    """

    def __init__(self, machines: list[NodeStateMachine]) -> None:
        self._machines = machines

    def wrap(
        self, handler_fn: Callable[..., Any]
    ) -> Callable[..., Any]:
        """Wrap a handler function with constraint checking.

        Args:
            handler_fn: The next handler in the middleware chain.

        Returns:
            Wrapped async callable.
        """
        machines = self._machines

        async def _constrained_handler(request: "HandlerRequest") -> "Outcome":
            # Find applicable state machine
            machine = _resolve_machine(machines, request.node)

            # Execute the actual handler
            outcome = await handler_fn(request)

            # If no machine applies, pass through
            if machine is None:
                return outcome

            # Determine current and new status
            current_status = request.node.attrs.get("status", "pending")
            new_status = _outcome_to_status(outcome, request.node)

            if new_status and new_status != current_status:
                try:
                    machine.validate_transition(
                        request.node.id, current_status, new_status
                    )
                except ConstraintViolation:
                    logger.error(
                        "Constraint violation on node '%s': %s -> %s "
                        "(machine: %s)",
                        request.node.id,
                        current_status,
                        new_status,
                        machine.name,
                    )
                    raise

            return outcome

        return _constrained_handler


def _resolve_machine(
    machines: list[NodeStateMachine],
    node: Any,
) -> NodeStateMachine | None:
    """Find the most specific matching state machine for a node."""
    shape = node.shape
    handler = node.attrs.get("handler", node.handler_type)

    # Prefer exact shape+handler match, fall back to shape-only
    shape_handler_match = None
    shape_only_match = None

    for m in machines:
        if m.matches_node(shape, handler):
            if m.applies_to_handler is not None:
                shape_handler_match = m
            else:
                shape_only_match = m

    return shape_handler_match or shape_only_match


def _outcome_to_status(outcome: "Outcome", node: Any) -> str | None:
    """Map an Outcome to a node status string.

    Uses explicit context_updates first (if a $<node_id>.status key is set),
    then falls back to the default mapping.
    """
    # Check if handler explicitly set a status
    explicit_key = f"${node.id}.status"
    if outcome.context_updates and explicit_key in outcome.context_updates:
        return str(outcome.context_updates[explicit_key])

    return _OUTCOME_TO_NODE_STATUS.get(outcome.status)
