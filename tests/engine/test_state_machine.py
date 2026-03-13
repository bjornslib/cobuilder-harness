"""Tests for cobuilder.engine.state_machine — NodeStateMachine."""
from __future__ import annotations

import pytest

from cobuilder.engine.state_machine import ConstraintViolation, NodeStateMachine


@pytest.fixture
def codergen_sm() -> NodeStateMachine:
    """A typical codergen state machine."""
    return NodeStateMachine(
        name="codergen_transitions",
        applies_to_shape="box",
        applies_to_handler="codergen",
        states=frozenset(["pending", "active", "impl_complete", "validated", "failed"]),
        transitions={
            "pending": frozenset(["active"]),
            "active": frozenset(["impl_complete", "failed"]),
            "impl_complete": frozenset(["validated", "failed"]),
            "failed": frozenset(["active"]),
        },
        initial_state="pending",
        terminal_states=frozenset(["validated", "failed"]),
    )


class TestCanTransition:
    def test_allowed_transition(self, codergen_sm: NodeStateMachine) -> None:
        assert codergen_sm.can_transition("pending", "active") is True

    def test_disallowed_transition(self, codergen_sm: NodeStateMachine) -> None:
        assert codergen_sm.can_transition("pending", "validated") is False

    def test_unknown_from_state(self, codergen_sm: NodeStateMachine) -> None:
        assert codergen_sm.can_transition("unknown", "active") is False

    def test_retry_from_failed(self, codergen_sm: NodeStateMachine) -> None:
        assert codergen_sm.can_transition("failed", "active") is True


class TestValidateTransition:
    def test_valid_raises_nothing(self, codergen_sm: NodeStateMachine) -> None:
        codergen_sm.validate_transition("node1", "pending", "active")

    def test_invalid_raises_violation(self, codergen_sm: NodeStateMachine) -> None:
        with pytest.raises(ConstraintViolation) as exc_info:
            codergen_sm.validate_transition("node1", "pending", "validated")
        assert exc_info.value.node_id == "node1"
        assert exc_info.value.from_state == "pending"
        assert exc_info.value.to_state == "validated"

    def test_same_state_noop(self, codergen_sm: NodeStateMachine) -> None:
        # Same state transitions should always be allowed (no-op)
        codergen_sm.validate_transition("node1", "active", "active")


class TestMatchesNode:
    def test_matches_shape_and_handler(self, codergen_sm: NodeStateMachine) -> None:
        assert codergen_sm.matches_node("box", "codergen") is True

    def test_wrong_shape(self, codergen_sm: NodeStateMachine) -> None:
        assert codergen_sm.matches_node("diamond", "codergen") is False

    def test_wrong_handler(self, codergen_sm: NodeStateMachine) -> None:
        assert codergen_sm.matches_node("box", "tool") is False

    def test_shape_only_machine(self) -> None:
        sm = NodeStateMachine(
            name="any_box",
            applies_to_shape="box",
            applies_to_handler=None,
        )
        assert sm.matches_node("box", "codergen") is True
        assert sm.matches_node("box", "tool") is True
        assert sm.matches_node("diamond") is False


class TestFromManifestConstraint:
    def test_builds_from_constraint(self) -> None:
        from cobuilder.templates.manifest import StateMachineConstraint

        sc = StateMachineConstraint(
            name="test_sm",
            applies_to_shape="hexagon",
            applies_to_handler="wait_human",
            states=["pending", "active", "passed", "failed"],
            transitions=[
                {"from": "pending", "to": "active"},
                {"from": "active", "to": "passed"},
                {"from": "active", "to": "failed"},
            ],
            initial="pending",
            terminal=["passed", "failed"],
        )
        sm = NodeStateMachine.from_manifest_constraint(sc)
        assert sm.name == "test_sm"
        assert sm.applies_to_shape == "hexagon"
        assert sm.can_transition("pending", "active")
        assert sm.can_transition("active", "passed")
        assert not sm.can_transition("pending", "passed")
        assert sm.terminal_states == frozenset(["passed", "failed"])
