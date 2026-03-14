"""Integration tests for E5 publication - validating repository publication readiness."""

from pathlib import Path
import re

import pytest


class TestPublicationFiles:
    """Tests for required publication files."""

    def test_license_exists(self) -> None:
        """Assert LICENSE file exists at repo root."""
        project_root = Path(__file__).parent.parent
        license_path = project_root / "LICENSE"

        assert license_path.exists(), "LICENSE file should exist at repo root"

    def test_contributing_exists(self) -> None:
        """Assert CONTRIBUTING.md exists at repo root."""
        project_root = Path(__file__).parent.parent
        contributing_path = project_root / "CONTRIBUTING.md"

        assert contributing_path.exists(), "CONTRIBUTING.md should exist at repo root"

    def test_env_example_exists(self) -> None:
        """Assert cobuilder/engine/.env.example exists."""
        project_root = Path(__file__).parent.parent
        env_example_path = project_root / "cobuilder" / "engine" / ".env.example"

        assert env_example_path.exists(), "cobuilder/engine/.env.example should exist"

    def test_ci_workflow_exists(self) -> None:
        """Assert .github/workflows/ci.yml exists."""
        project_root = Path(__file__).parent.parent
        ci_path = project_root / ".github" / "workflows" / "ci.yml"

        assert ci_path.exists(), ".github/workflows/ci.yml should exist"

    def test_mcp_json_example_exists(self) -> None:
        """Assert .mcp.json.example exists."""
        project_root = Path(__file__).parent.parent
        mcp_example_path = project_root / ".mcp.json.example"

        assert mcp_example_path.exists(), ".mcp.json.example should exist"


class TestSecurityConfiguration:
    """Tests for security-related configuration."""

    def test_mcp_json_no_plaintext_secrets(self) -> None:
        """Verify .mcp.json has no plaintext API keys."""
        project_root = Path(__file__).parent.parent
        mcp_path = project_root / ".mcp.json"

        if not mcp_path.exists():
            pytest.skip(".mcp.json not found - may not be created yet")

        content = mcp_path.read_text()

        # Patterns that indicate plaintext secrets
        secret_patterns = [
            r"sk-ant-[a-zA-Z0-9_-]+",  # Anthropic API keys
            r"pplx-[a-zA-Z0-9]+",  # Perplexity API keys
        ]

        for pattern in secret_patterns:
            match = re.search(pattern, content)
            assert match is None, (
                f".mcp.json should not contain plaintext secrets. "
                f"Found pattern matching: {pattern}"
            )

    def test_gitignore_covers_sensitive(self) -> None:
        """Verify .gitignore covers all sensitive paths."""
        project_root = Path(__file__).parent.parent
        gitignore_path = project_root / ".gitignore"

        content = gitignore_path.read_text()

        required_entries = [
            ".pipelines/",
            ".logfire/",
            "cobuilder/engine/.env",
        ]

        missing_entries = []
        for entry in required_entries:
            if entry not in content:
                missing_entries.append(entry)

        assert not missing_entries, (
            f".gitignore should cover sensitive paths. Missing: {missing_entries}"
        )