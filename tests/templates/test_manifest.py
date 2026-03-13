"""Tests for cobuilder.templates.manifest — manifest parsing and validation."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_manifest(tmp_path: Path) -> Path:
    """Create a temporary manifest.yaml for testing."""
    manifest = {
        "template": {
            "name": "test-template",
            "version": "1.0",
            "description": "A test template",
            "topology": "linear",
        },
        "parameters": {
            "prd_ref": {"type": "string", "required": True},
            "count": {"type": "integer", "required": False, "default": 5},
            "enabled": {"type": "boolean", "default": True},
            "workers": {
                "type": "list",
                "required": True,
                "min_length": 1,
                "max_length": 3,
            },
        },
        "constraints": {
            "codergen_sm": {
                "type": "node_state_machine",
                "description": "Test state machine",
                "applies_to": {"shape": "box", "handler": "codergen"},
                "states": ["pending", "active", "completed", "failed"],
                "transitions": [
                    {"from": "pending", "to": "active"},
                    {"from": "active", "to": "completed"},
                    {"from": "active", "to": "failed"},
                    {"from": "failed", "to": "active"},
                ],
                "initial": "pending",
                "terminal": ["completed", "failed"],
            },
            "path_check": {
                "type": "path_constraint",
                "description": "Must pass through hexagon before exit",
                "rule": {
                    "from_shape": "box",
                    "must_pass_through": ["hexagon"],
                    "before_reaching": ["Msquare"],
                },
            },
            "loop_bound": {
                "type": "loop_constraint",
                "rule": {
                    "max_per_node_visits": 3,
                    "max_pipeline_visits": 20,
                },
            },
        },
    }
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(yaml.dump(manifest, default_flow_style=False))
    return manifest_path


class TestLoadManifest:
    def test_loads_metadata(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        assert m.name == "test-template"
        assert m.version == "1.0"
        assert m.topology == "linear"

    def test_loads_parameters(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        assert "prd_ref" in m.parameters
        assert m.parameters["prd_ref"].required is True
        assert m.parameters["count"].default == 5
        assert m.parameters["workers"].min_length == 1

    def test_loads_state_machine_constraints(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        assert len(m.state_machine_constraints) == 1
        sm = m.state_machine_constraints[0]
        assert sm.name == "codergen_sm"
        assert sm.applies_to_shape == "box"
        assert sm.applies_to_handler == "codergen"
        assert len(sm.transitions) == 4

    def test_loads_path_constraints(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        assert len(m.path_constraints) == 1
        pc = m.path_constraints[0]
        assert pc.from_shape == "box"
        assert "hexagon" in pc.must_pass_through

    def test_loads_loop_constraints(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        assert len(m.loop_constraints) == 1
        lc = m.loop_constraints[0]
        assert lc.max_per_node_visits == 3

    def test_file_not_found(self, tmp_path: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "nonexistent.yaml")


class TestManifestValidation:
    def test_valid_params(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        errors = m.validate_params({
            "prd_ref": "PRD-TEST-001",
            "workers": [{"label": "test"}],
        })
        assert errors == []

    def test_missing_required_param(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        errors = m.validate_params({"workers": ["a"]})
        assert any("prd_ref" in e for e in errors)

    def test_wrong_type(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        errors = m.validate_params({
            "prd_ref": 123,  # Should be string
            "workers": ["a"],
        })
        assert any("string" in e for e in errors)

    def test_list_too_short(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        errors = m.validate_params({
            "prd_ref": "PRD-TEST",
            "workers": [],
        })
        assert any("at least 1" in e for e in errors)

    def test_resolve_defaults(self, tmp_manifest: Path) -> None:
        from cobuilder.templates.manifest import load_manifest

        m = load_manifest(tmp_manifest)
        resolved = m.resolve_params({
            "prd_ref": "PRD-TEST",
            "workers": ["a"],
        })
        assert resolved["count"] == 5
        assert resolved["enabled"] is True
