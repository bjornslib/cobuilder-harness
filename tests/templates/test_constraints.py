"""Tests for cobuilder.templates.constraints — static constraint validation."""
from __future__ import annotations

import pytest

from cobuilder.templates.constraints import validate_static_constraints


# A simple DOT pipeline where box passes through hexagon before Msquare
_VALID_DOT = '''
digraph "test" {
    start [shape=Mdiamond handler="start" status="pending"];
    impl [shape=box handler="codergen" status="pending"];
    gate [shape=hexagon handler="wait_human" status="pending"];
    finalize [shape=Msquare handler="exit" status="pending"];

    start -> impl;
    impl -> gate;
    gate -> finalize;
}
'''

# DOT where box goes directly to Msquare (no hexagon gate)
_INVALID_PATH_DOT = '''
digraph "test" {
    start [shape=Mdiamond handler="start" status="pending"];
    impl [shape=box handler="codergen" status="pending"];
    finalize [shape=Msquare handler="exit" status="pending"];

    start -> impl;
    impl -> finalize;
}
'''

# DOT with component but no tripleoctagon fan-in
_INVALID_TOPO_DOT = '''
digraph "test" {
    start [shape=Mdiamond handler="start" status="pending"];
    par [shape=component handler="parallel" status="pending"];
    impl_a [shape=box handler="codergen" status="pending"];
    impl_b [shape=box handler="codergen" status="pending"];
    finalize [shape=Msquare handler="exit" status="pending"];

    start -> par;
    par -> impl_a;
    par -> impl_b;
    impl_a -> finalize;
    impl_b -> finalize;
}
'''


@pytest.fixture
def path_constraint_manifest():
    """Manifest with a path constraint."""
    from cobuilder.templates.manifest import Manifest, PathConstraint

    return Manifest(
        name="test",
        path_constraints=[
            PathConstraint(
                name="require_gate",
                from_shape="box",
                must_pass_through=["hexagon"],
                before_reaching=["Msquare"],
            )
        ],
    )


@pytest.fixture
def topology_constraint_manifest():
    """Manifest with a topology constraint."""
    from cobuilder.templates.manifest import Manifest, TopologyConstraint

    return Manifest(
        name="test",
        topology_constraints=[
            TopologyConstraint(
                name="balanced_par",
                every_node_shape="component",
                must_have_downstream_shape="tripleoctagon",
                max_hops=10,
            )
        ],
    )


class TestPathConstraints:
    def test_valid_path_passes(self, path_constraint_manifest) -> None:
        errors = validate_static_constraints(_VALID_DOT, path_constraint_manifest)
        assert errors == []

    def test_invalid_path_detected(self, path_constraint_manifest) -> None:
        errors = validate_static_constraints(_INVALID_PATH_DOT, path_constraint_manifest)
        assert len(errors) > 0
        assert "hexagon" in errors[0]

    def test_no_constraints_passes(self) -> None:
        from cobuilder.templates.manifest import Manifest

        m = Manifest(name="empty")
        errors = validate_static_constraints(_INVALID_PATH_DOT, m)
        assert errors == []


class TestTopologyConstraints:
    def test_valid_topology_passes(self, topology_constraint_manifest) -> None:
        dot = '''
        digraph "test" {
            par [shape=component handler="parallel" status="pending"];
            a [shape=box handler="codergen" status="pending"];
            join [shape=tripleoctagon handler="fan_in" status="pending"];
            par -> a;
            a -> join;
        }
        '''
        errors = validate_static_constraints(dot, topology_constraint_manifest)
        assert errors == []

    def test_missing_fan_in_detected(self, topology_constraint_manifest) -> None:
        errors = validate_static_constraints(
            _INVALID_TOPO_DOT, topology_constraint_manifest
        )
        assert len(errors) > 0
        assert "tripleoctagon" in errors[0]
