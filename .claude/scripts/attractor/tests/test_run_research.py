"""Tests for run_research.py — Research Node Agent."""

import json
import os
import sys

import pytest

# Ensure the attractor scripts directory is importable
_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from run_research import build_research_prompt, parse_args


class TestBuildResearchPrompt:
    """Verify prompt construction for the research agent."""

    def test_prompt_includes_node_id(self):
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD-AUTH-001.md",
            frameworks=["fastapi"],
            evidence_dir="/path/to/evidence",
        )
        assert "research_auth" in prompt

    def test_prompt_includes_sd_path(self):
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD-AUTH-001.md",
            frameworks=[],
            evidence_dir="/path/to/evidence",
        )
        assert "/path/to/SD-AUTH-001.md" in prompt

    def test_prompt_includes_frameworks(self):
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD.md",
            frameworks=["fastapi", "pydantic"],
            evidence_dir="/path/to/evidence",
        )
        assert "fastapi" in prompt
        assert "pydantic" in prompt

    def test_prompt_includes_edit_instruction(self):
        """Prompt must instruct agent to use Edit tool to update SD."""
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD.md",
            frameworks=["fastapi"],
            evidence_dir="/path/to/evidence",
        )
        assert "Edit" in prompt

    def test_prompt_includes_evidence_path(self):
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD.md",
            frameworks=[],
            evidence_dir="/tmp/evidence/research_auth",
        )
        assert "/tmp/evidence/research_auth" in prompt
        assert "research-findings.json" in prompt

    def test_prompt_no_frameworks_section_when_empty(self):
        """When no frameworks given, the frameworks section should be absent."""
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD.md",
            frameworks=[],
            evidence_dir="/path/to/evidence",
        )
        assert "Frameworks to Research" not in prompt

    def test_prompt_includes_prd_ref(self):
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD.md",
            frameworks=[],
            evidence_dir="/path/to/evidence",
        )
        assert "PRD-AUTH-001" in prompt


class TestDryRunMode:
    """Verify --dry-run outputs prompt without running SDK."""

    def test_dry_run_exits_zero(self, tmp_path, capsys):
        """--dry-run should output JSON with prompt and exit 0."""
        sd_file = tmp_path / "SD-TEST.md"
        sd_file.write_text("# Test SD\n")

        with pytest.raises(SystemExit) as exc_info:
            from run_research import main
            main([
                "--node", "test_node",
                "--prd", "PRD-TEST-001",
                "--solution-design", str(sd_file),
                "--target-dir", str(tmp_path),
                "--frameworks", "fastapi,pydantic",
                "--dry-run",
            ])

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["dry_run"] is True
        assert result["node"] == "test_node"
        assert result["frameworks"] == ["fastapi", "pydantic"]
        assert "prompt" in result
        assert len(result["prompt"]) > 100

    def test_dry_run_creates_evidence_dir(self, tmp_path, capsys):
        """--dry-run should still create the evidence directory."""
        sd_file = tmp_path / "SD-TEST.md"
        sd_file.write_text("# Test SD\n")

        with pytest.raises(SystemExit):
            from run_research import main
            main([
                "--node", "test_node",
                "--prd", "PRD-TEST-001",
                "--solution-design", str(sd_file),
                "--target-dir", str(tmp_path),
                "--dry-run",
            ])

        evidence_dir = tmp_path / ".claude" / "evidence" / "test_node"
        assert evidence_dir.is_dir()


class TestEvidenceJsonSchema:
    """Verify the evidence JSON structure documented in the prompt."""

    def test_evidence_schema_in_prompt(self):
        """The prompt must describe the expected evidence JSON structure."""
        prompt = build_research_prompt(
            node_id="research_auth",
            prd_ref="PRD-AUTH-001",
            sd_path="/path/to/SD.md",
            frameworks=["fastapi"],
            evidence_dir="/path/to/evidence",
        )
        # Key fields that must be documented in the prompt
        for field in [
            "node_id",
            "downstream_codergen",
            "timestamp",
            "sd_path",
            "sd_updated",
            "frameworks_queried",
            "findings",
            "sd_changes_summary",
            "gotchas",
        ]:
            assert field in prompt, f"Evidence schema field '{field}' not in prompt"


class TestParseArgs:
    """Verify argument parsing."""

    def test_required_args(self):
        args = parse_args([
            "--node", "research_auth",
            "--prd", "PRD-AUTH-001",
            "--solution-design", "/path/to/SD.md",
            "--target-dir", "/path/to/target",
        ])
        assert args.node == "research_auth"
        assert args.prd == "PRD-AUTH-001"
        assert args.solution_design == "/path/to/SD.md"
        assert args.target_dir == "/path/to/target"

    def test_default_model(self):
        # Temporarily set environment variable to a known value for testing
        original_model = os.environ.get("ANTHROPIC_MODEL")
        os.environ["ANTHROPIC_MODEL"] = "claude-haiku-4-5-20251001"

        try:
            args = parse_args([
                "--node", "x", "--prd", "y",
                "--solution-design", "z", "--target-dir", "w",
            ])
            assert args.model == "claude-haiku-4-5-20251001"
        finally:
            # Restore original environment
            if original_model is not None:
                os.environ["ANTHROPIC_MODEL"] = original_model
            else:
                os.environ.pop("ANTHROPIC_MODEL", None)

    def test_default_model_fallback(self):
        # Temporarily remove the environment variable to test fallback
        original_model = os.environ.get("ANTHROPIC_MODEL")
        if "ANTHROPIC_MODEL" in os.environ:
            del os.environ["ANTHROPIC_MODEL"]

        try:
            args = parse_args([
                "--node", "x", "--prd", "y",
                "--solution-design", "z", "--target-dir", "w",
            ])
            assert args.model == "claude-haiku-4-5-20251001"  # Default fallback
        finally:
            # Restore original environment
            if original_model is not None:
                os.environ["ANTHROPIC_MODEL"] = original_model

    def test_default_max_turns(self):
        args = parse_args([
            "--node", "x", "--prd", "y",
            "--solution-design", "z", "--target-dir", "w",
        ])
        assert args.max_turns == 15

    def test_frameworks_parsing(self):
        args = parse_args([
            "--node", "x", "--prd", "y",
            "--solution-design", "z", "--target-dir", "w",
            "--frameworks", "fastapi,pydantic,supabase",
        ])
        assert args.frameworks == "fastapi,pydantic,supabase"

    def test_dry_run_flag(self):
        args = parse_args([
            "--node", "x", "--prd", "y",
            "--solution-design", "z", "--target-dir", "w",
            "--dry-run",
        ])
        assert args.dry_run is True
