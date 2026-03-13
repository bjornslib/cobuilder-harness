"""Tests for cobuilder.templates.instantiator — template rendering."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def template_dir(tmp_path: Path) -> Path:
    """Create a minimal template directory for testing."""
    tmpl_dir = tmp_path / "templates" / "test-tmpl"
    tmpl_dir.mkdir(parents=True)

    manifest = {
        "template": {
            "name": "test-tmpl",
            "version": "1.0",
            "description": "Test template",
            "topology": "linear",
        },
        "parameters": {
            "prd_ref": {"type": "string", "required": True},
            "label": {"type": "string", "required": False, "default": "Default Label"},
        },
        "constraints": {},
    }
    (tmpl_dir / "manifest.yaml").write_text(yaml.dump(manifest))

    template_content = '''// Generated from test-tmpl
digraph "{{ prd_ref }}" {
    graph [
        prd_ref="{{ prd_ref }}"
        _template="test-tmpl"
        _template_version="1.0"
    ];

    start [
        shape=Mdiamond
        label="PARSE\\n{{ prd_ref }}"
        handler="start"
        status="pending"
    ];

    impl [
        shape=box
        label="{{ label }}"
        handler="codergen"
        status="pending"
    ];

    finalize [
        shape=Msquare
        label="FINALIZE"
        handler="exit"
        status="pending"
    ];

    start -> impl [label="begin"];
    impl -> finalize [label="done"];
}
'''
    (tmpl_dir / "template.dot.j2").write_text(template_content)
    return tmp_path / "templates"


class TestInstantiateTemplate:
    def test_renders_basic_template(self, template_dir: Path) -> None:
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "test-tmpl",
            {"prd_ref": "PRD-TEST-001"},
            templates_dir=template_dir,
            validate=False,
        )
        assert 'prd_ref="PRD-TEST-001"' in result
        assert '_template="test-tmpl"' in result
        assert "PARSE" in result

    def test_applies_defaults(self, template_dir: Path) -> None:
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "test-tmpl",
            {"prd_ref": "PRD-TEST-001"},
            templates_dir=template_dir,
            validate=False,
        )
        assert "Default Label" in result

    def test_overrides_defaults(self, template_dir: Path) -> None:
        from cobuilder.templates.instantiator import instantiate_template

        result = instantiate_template(
            "test-tmpl",
            {"prd_ref": "PRD-TEST-001", "label": "Custom Label"},
            templates_dir=template_dir,
            validate=False,
        )
        assert "Custom Label" in result
        assert "Default Label" not in result

    def test_writes_output_file(self, template_dir: Path, tmp_path: Path) -> None:
        from cobuilder.templates.instantiator import instantiate_template

        output = tmp_path / "output.dot"
        instantiate_template(
            "test-tmpl",
            {"prd_ref": "PRD-TEST-001"},
            output_path=output,
            templates_dir=template_dir,
            validate=False,
        )
        assert output.exists()
        assert "PRD-TEST-001" in output.read_text()

    def test_missing_required_param_raises(self, template_dir: Path) -> None:
        from cobuilder.templates.instantiator import instantiate_template

        with pytest.raises(ValueError, match="prd_ref"):
            instantiate_template(
                "test-tmpl",
                {},
                templates_dir=template_dir,
                validate=False,
            )

    def test_missing_template_raises(self, template_dir: Path) -> None:
        from cobuilder.templates.instantiator import instantiate_template

        with pytest.raises(FileNotFoundError):
            instantiate_template(
                "nonexistent",
                {"prd_ref": "X"},
                templates_dir=template_dir,
            )


class TestListTemplates:
    def test_lists_available_templates(self, template_dir: Path) -> None:
        from cobuilder.templates.instantiator import list_templates

        templates = list_templates(template_dir)
        assert len(templates) == 1
        assert templates[0]["name"] == "test-tmpl"

    def test_empty_dir(self, tmp_path: Path) -> None:
        from cobuilder.templates.instantiator import list_templates

        templates = list_templates(tmp_path / "empty")
        assert templates == []
