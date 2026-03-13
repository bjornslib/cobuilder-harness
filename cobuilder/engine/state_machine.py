"""NodeStateMachine — finite state machines for node status transitions.

Loaded from template manifest constraints and enforced at runtime by
ConstraintMiddleware. Each state machine governs the allowed status
transitions for nodes matching a specific shape/handler combination.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ConstraintViolation(Exception):
    """Raised when a node status transition violates a state machine constraint."""

    def __init__(
        self,
        node_id: str,
        machine: str,
        from_state: str,
        to_state: str,
        allowed: set[str],
    ) -> None:
        self.node_id = node_id
        self.machine = machine
        self.from_state = from_state
        self.to_state = to_state
        self.allowed = allowed
        super().__init__(
            f"Constraint violation on node '{node_id}': "
            f"transition '{from_state}' -> '{to_state}' is not allowed by "
            f"state machine '{machine}'. "
            f"Allowed transitions from '{from_state}': {sorted(allowed) if allowed else 'none'}"
        )


@dataclass(frozen=True)
class NodeStateMachine:
    """Finite state machine governing allowed status transitions for a node.

    Loaded from manifest.yaml constraint definitions. Applied by
    ConstraintMiddleware before each handler execution.

    Attributes:
        name:              Constraint name from the manifest.
        applies_to_shape:  DOT shape string this machine applies to.
        applies_to_handler: Handler type (optional). None = all handlers
                            with matching shape.
        states:            Set of all valid states.
        transitions:       Dict mapping from_state -> set of allowed to_states.
        initial_state:     The state nodes start in.
        terminal_states:   States that represent completion (no further transitions).
    """

    name: str
    applies_to_shape: str
    applies_to_handler: str | None = None
    states: frozenset[str] = field(default_factory=frozenset)
    transitions: dict[str, frozenset[str]] = field(default_factory=dict)
    initial_state: str = "pending"
    terminal_states: frozenset[str] = field(default_factory=frozenset)

    def can_transition(self, from_state: str, to_state: str) -> bool:
        """Return True if the transition from_state -> to_state is allowed."""
        allowed = self.transitions.get(from_state, frozenset())
        return to_state in allowed

    def validate_transition(
        self, node_id: str, from_state: str, to_state: str
    ) -> None:
        """Raise ConstraintViolation if the transition is disallowed."""
        if from_state == to_state:
            return  # No-op transitions always allowed
        if not self.can_transition(from_state, to_state):
            raise ConstraintViolation(
                node_id=node_id,
                machine=self.name,
                from_state=from_state,
                to_state=to_state,
                allowed=set(self.transitions.get(from_state, frozenset())),
            )

    def matches_node(self, shape: str, handler: str | None = None) -> bool:
        """Return True if this state machine applies to a node with given shape/handler."""
        if self.applies_to_shape != shape:
            return False
        if self.applies_to_handler is not None and handler is not None:
            return self.applies_to_handler == handler
        return True

    @classmethod
    def from_manifest_constraint(
        cls, constraint: "StateMachineConstraint",
    ) -> "NodeStateMachine":
        """Build a NodeStateMachine from a parsed manifest constraint.

        Args:
            constraint: StateMachineConstraint from manifest parser.

        Returns:
            Fully constructed NodeStateMachine.
        """
        # Build transition map: from_state -> frozenset of to_states
        transition_map: dict[str, set[str]] = {}
        for t in constraint.transitions:
            from_s = t.get("from", "")
            to_s = t.get("to", "")
            if from_s and to_s:
                transition_map.setdefault(from_s, set()).add(to_s)

        frozen_transitions = {k: frozenset(v) for k, v in transition_map.items()}

        return cls(
            name=constraint.name,
            applies_to_shape=constraint.applies_to_shape,
            applies_to_handler=constraint.applies_to_handler,
            states=frozenset(constraint.states),
            transitions=frozen_transitions,
            initial_state=constraint.initial,
            terminal_states=frozenset(constraint.terminal),
        )
