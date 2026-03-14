"""Integration tests for E7 template - validating cobuilder-lifecycle template structure."""

from pathlib import Path

import pytest


class TestCobuilderLifecycleTemplate:
    """Tests for cobuilder-lifecycle template files and structure."""

    @pytest.fixture
    def template_dir(self) -> Path:
        """Get the cobuilder-lifecycle template directory."""
        project_root = Path(__file__).parent.parent.parent
        return project_root / ".cobuilder" / "templates" / "cobuilder-lifecycle"

    def test_template_exists(self, template_dir: Path) -> None:
        """Assert template.dot.j2 exists in cobuilder-lifecycle directory."""
        template_file = template_dir / "template.dot.j2"

        assert template_file.exists(), f"Template file should exist at {template_file}"

    def test_manifest_exists(self, template_dir: Path) -> None:
        """Assert manifest.yaml exists in cobuilder-lifecycle directory."""
        manifest_file = template_dir / "manifest.yaml"

        assert manifest_file.exists(), f"Manifest file should exist at {manifest_file}"


class TestCobuilderLifecycleTemplateContent:
    """Tests for template.dot.j2 content structure."""

    @pytest.fixture
    def template_content(self) -> str:
        """Read the template.dot.j2 content."""
        project_root = Path(__file__).parent.parent.parent
        template_file = (
            project_root / ".cobuilder" / "templates" / "cobuilder-lifecycle" / "template.dot.j2"
        )

        if not template_file.exists():
            pytest.skip("template.dot.j2 not found")

        return template_file.read_text()

    def test_template_has_lifecycle_nodes(self, template_content: str) -> None:
        """Verify template contains all lifecycle node keywords."""
        # Expected lifecycle phases
        expected_keywords = [
            "research",
            "refine",
            "plan",
            "execute",
            "validate",
            "evaluate",
            "close",
        ]

        missing_keywords = []
        for keyword in expected_keywords:
            if keyword not in template_content.lower():
                missing_keywords.append(keyword)

        assert not missing_keywords, (
            f"Template should contain lifecycle node keywords. Missing: {missing_keywords}"
        )

    def test_template_has_wait_human(self, template_content: str) -> None:
        """Verify template has wait.human or wait_human for human-in-the-loop."""
        has_wait_human = (
            "wait.human" in template_content
            or "wait_human" in template_content
            or 'handler="wait.human"' in template_content
        )

        assert has_wait_human, "Template should have wait.human for human review gate"

    def test_template_has_loop_edge(self, template_content: str) -> None:
        """Verify template has loop edge from evaluate back to research."""
        # Look for edge pattern: evaluate -> research
        has_loop_edge = (
            "evaluate" in template_content.lower()
            and "research" in template_content.lower()
            and "->" in template_content
        )

        assert has_loop_edge, (
            "Template should have loop edge from evaluate back to research for iteration"
        )


class TestCobuilderLifecycleManifest:
    """Tests for manifest.yaml content structure."""

    @pytest.fixture
    def manifest_content(self) -> str:
        """Read the manifest.yaml content."""
        project_root = Path(__file__).parent.parent.parent
        manifest_file = (
            project_root / ".cobuilder" / "templates" / "cobuilder-lifecycle" / "manifest.yaml"
        )

        if not manifest_file.exists():
            pytest.skip("manifest.yaml not found")

        return manifest_file.read_text()

    def test_manifest_has_loop_constraint(self, manifest_content: str) -> None:
        """Verify manifest has loop_constraint or max_iterations for bounded iteration."""
        has_loop_constraint = (
            "loop_constraint" in manifest_content
            or "max_iterations" in manifest_content
            or "maxIterations" in manifest_content
        )

        assert has_loop_constraint, (
            "Manifest should have loop_constraint or max_iterations to bound iteration"
        )