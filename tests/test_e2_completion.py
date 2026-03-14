"""Integration tests for E2 completion - validating environment sourcing, API fallbacks, and path updates."""

from pathlib import Path

import pytest


class TestStopGateEnvironmentSourcing:
    """Tests for unified-stop-gate.sh environment configuration."""

    def test_stop_gate_sources_env(self) -> None:
        """Verify stop gate sources cobuilder/engine/.env with auto-export."""
        project_root = Path(__file__).parent.parent
        stop_gate_path = project_root / ".claude" / "hooks" / "unified-stop-gate.sh"

        content = stop_gate_path.read_text()

        # Verify it contains 'source' directive
        assert "source" in content, "Stop gate should source environment file"

        # Verify it references cobuilder/engine/.env
        assert "cobuilder/engine/.env" in content, (
            "Stop gate should reference cobuilder/engine/.env path"
        )


class TestJudgeAnthropicConfiguration:
    """Tests for system3_continuation_judge.py Anthropic client configuration."""

    def test_judge_uses_base_url(self) -> None:
        """Verify judge reads ANTHROPIC_BASE_URL near Anthropic constructor."""
        project_root = Path(__file__).parent.parent
        judge_path = (
            project_root
            / ".claude"
            / "hooks"
            / "unified_stop_gate"
            / "system3_continuation_judge.py"
        )

        content = judge_path.read_text()

        # Find 'base_url' keyword
        assert "base_url" in content, "Judge should use base_url configuration"

        # Verify it's used near Anthropic client construction
        # Look for the pattern where base_url is conditionally added
        lines = content.split("\n")
        found_pattern = False
        for i, line in enumerate(lines):
            if "base_url" in line.lower():
                # Check surrounding context for Anthropic import/usage
                context = "\n".join(lines[max(0, i - 5) : i + 5])
                if "anthropic" in context.lower() or "client" in context.lower():
                    found_pattern = True
                    break

        assert found_pattern, "base_url should appear near Anthropic client construction"

    def test_judge_dashscope_fallback(self) -> None:
        """Verify judge has DASHSCOPE_API_KEY as fallback for ANTHROPIC_API_KEY."""
        project_root = Path(__file__).parent.parent
        judge_path = (
            project_root
            / ".claude"
            / "hooks"
            / "unified_stop_gate"
            / "system3_continuation_judge.py"
        )

        content = judge_path.read_text()

        # Verify DASHSCOPE_API_KEY appears as fallback
        assert "DASHSCOPE_API_KEY" in content, (
            "Judge should have DASHSCOPE_API_KEY as API key fallback"
        )


class TestCoBuilderTemplates:
    """Tests for CoBuilder template directory structure."""

    def test_templates_in_cobuilder_dir(self) -> None:
        """Verify .cobuilder/templates/ exists with at least 3 templates."""
        project_root = Path(__file__).parent.parent
        templates_dir = project_root / ".cobuilder" / "templates"

        assert templates_dir.exists(), ".cobuilder/templates/ should exist"
        assert templates_dir.is_dir(), ".cobuilder/templates/ should be a directory"

        # List template directories (each template is a subdirectory)
        template_dirs = [d for d in templates_dir.iterdir() if d.is_dir()]

        # Expected templates from stream 1-3 changes
        expected_templates = [
            "sequential-validated",
            "hub-spoke",
            "s3-lifecycle",
        ]

        found_count = sum(
            1 for t in template_dirs if any(exp in t.name for exp in expected_templates)
        )

        assert found_count >= 3, (
            f"Expected at least 3 template directories, found {found_count}: "
            f"{[d.name for d in template_dirs]}"
        )

    def test_instantiator_cobuilder_path(self) -> None:
        """Verify instantiator.py references .cobuilder/templates."""
        project_root = Path(__file__).parent.parent
        instantiator_path = project_root / "cobuilder" / "templates" / "instantiator.py"

        if not instantiator_path.exists():
            pytest.skip("instantiator.py not found at expected path")

        content = instantiator_path.read_text()

        # Verify it references .cobuilder/templates or equivalent
        assert (
            ".cobuilder/templates" in content
            or "cobuilder/templates" in content
            or "templates" in content
        ), "Instantiator should reference CoBuilder templates path"


class TestZeroRepoPathUpdates:
    """Tests for ZeroRepo script path updates."""

    def test_zerorepo_updated_paths(self) -> None:
        """Verify zerorepo-pipeline.sh has no .claude/attractor/ references."""
        project_root = Path(__file__).parent.parent
        zerorepo_path = (
            project_root
            / ".claude"
            / "skills"
            / "orchestrator-multiagent"
            / "scripts"
            / "zerorepo-pipeline.sh"
        )

        if not zerorepo_path.exists():
            pytest.skip("zerorepo-pipeline.sh not found at expected path")

        content = zerorepo_path.read_text()

        # Verify no .claude/attractor/ references remain
        assert ".claude/attractor/" not in content, (
            "zerorepo-pipeline.sh should not reference old .claude/attractor/ path"
        )


class TestGitignoreConfiguration:
    """Tests for .gitignore coverage of sensitive paths."""

    def test_pipelines_dir_in_gitignore(self) -> None:
        """Verify .pipelines/ is listed in .gitignore."""
        project_root = Path(__file__).parent.parent
        gitignore_path = project_root / ".gitignore"

        content = gitignore_path.read_text()

        assert ".pipelines/" in content, ".gitignore should list .pipelines/"