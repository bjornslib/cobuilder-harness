"""Tests for cobuilder/pipeline/transition.py — E2 divergence fixes.

Covers:
- validated → accepted transition (new)
- failed → pending transition (new)
- accepted as terminal state
- check_finalize_gate accepts both validated and accepted
- STATUS_COLORS includes accepted
"""

import pytest

from cobuilder.pipeline.transition import (
    VALID_TRANSITIONS,
    STATUS_COLORS,
    check_transition,
    apply_transition,
    check_finalize_gate,
)


# --- VALID_TRANSITIONS structure tests ---

class TestValidTransitions:
    def test_validated_to_accepted(self):
        assert "accepted" in VALID_TRANSITIONS["validated"]

    def test_failed_to_pending(self):
        assert "pending" in VALID_TRANSITIONS["failed"]

    def test_failed_to_active(self):
        """Existing transition must still work."""
        assert "active" in VALID_TRANSITIONS["failed"]

    def test_accepted_is_terminal(self):
        assert VALID_TRANSITIONS["accepted"] == set()

    def test_accepted_color_exists(self):
        assert "accepted" in STATUS_COLORS


# --- check_transition tests ---

class TestCheckTransition:
    def test_validated_to_accepted_valid(self):
        ok, _ = check_transition("validated", "accepted")
        assert ok

    def test_failed_to_pending_valid(self):
        ok, _ = check_transition("failed", "pending")
        assert ok

    def test_accepted_to_anything_invalid(self):
        ok, _ = check_transition("accepted", "active")
        assert not ok

    def test_validated_to_failed_invalid(self):
        """validated can only go to accepted."""
        ok, _ = check_transition("validated", "failed")
        assert not ok


# --- apply_transition with DOT content ---

MINIMAL_DOT = '''digraph test {
    node1 [
        shape=box
        label="Test Node"
        handler="codergen"
        status="validated"
        fillcolor="lightgreen"
        style="filled"
    ];
}
'''

FAILED_DOT = '''digraph test {
    node1 [
        shape=box
        label="Test Node"
        handler="codergen"
        status="failed"
        fillcolor="lightcoral"
        style="filled"
    ];
}
'''


class TestApplyTransition:
    def test_apply_validated_to_accepted(self):
        updated, log_msg = apply_transition(MINIMAL_DOT, "node1", "accepted")
        assert 'status="accepted"' in updated
        assert 'fillcolor="palegreen"' in updated
        assert "validated -> accepted" in log_msg

    def test_apply_failed_to_pending(self):
        updated, log_msg = apply_transition(FAILED_DOT, "node1", "pending")
        assert 'status="pending"' in updated
        assert 'fillcolor="lightyellow"' in updated
        assert "failed -> pending" in log_msg

    def test_apply_accepted_to_active_fails(self):
        dot = MINIMAL_DOT.replace('status="validated"', 'status="accepted"')
        dot = dot.replace('fillcolor="lightgreen"', 'fillcolor="palegreen"')
        with pytest.raises(ValueError, match="Illegal transition"):
            apply_transition(dot, "node1", "active")


# --- check_finalize_gate tests ---

HEXAGON_VALIDATED_DOT = '''digraph test {
    hex1 [shape=hexagon status="validated"];
    hex2 [shape=hexagon status="accepted"];
    box1 [shape=box status="active"];
}
'''

HEXAGON_MIXED_DOT = '''digraph test {
    hex1 [shape=hexagon status="validated"];
    hex2 [shape=hexagon status="active"];
}
'''


class TestCheckFinalizeGate:
    def test_gate_open_with_validated_and_accepted(self):
        """Gate should pass when hexagons are either validated or accepted."""
        ok, blocked = check_finalize_gate(HEXAGON_VALIDATED_DOT)
        assert ok
        assert blocked == []

    def test_gate_blocked_with_active_hexagon(self):
        ok, blocked = check_finalize_gate(HEXAGON_MIXED_DOT)
        assert not ok
        assert "hex2" in blocked
