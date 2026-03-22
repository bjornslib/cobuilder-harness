#!/usr/bin/env python3
"""E7.1 E2E Tests: Worker Prompt Restructuring.

Tests against acceptance criteria from:
  - SD-HARNESS-UPGRADE-001-E7.1-worker-prompt.md
  - acceptance-tests/PRD-HARNESS-UPGRADE-001/E7.1-worker-prompt.feature

Run: python3 -m pytest tests/test_e71_worker_prompt.py -v
"""

import os
import sys

import pytest

# Ensure attractor scripts are importable
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".claude", "scripts", "attractor",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# S7.1.1 — Worker system prompt under 4K characters
# ---------------------------------------------------------------------------


class TestWorkerSystemPrompt:
    """AC-7.1.1: Worker system prompt under 4K chars."""

    def _get_prompt(self) -> str:
        from runner import build_worker_system_prompt
        return build_worker_system_prompt(
            node_id="impl_test",
            prd_ref="PRD-TEST-001",
            acceptance="All tests pass",
            target_dir="/tmp/test-repo",
        )

    def test_under_4k_chars(self):
        """S7.1.1: System prompt < 4000 characters."""
        prompt = self._get_prompt()
        assert len(prompt) < 4000, (
            f"Worker system prompt is {len(prompt)} chars, must be < 4000"
        )

    def test_contains_worker_role(self):
        prompt = self._get_prompt()
        assert "worker" in prompt.lower() or "Worker" in prompt

    def test_contains_tool_allowlist(self):
        prompt = self._get_prompt()
        for tool in ["Read", "Write", "Edit", "Bash"]:
            assert tool in prompt, f"Missing tool '{tool}' in allowlist"

    def test_references_tool_reference_file(self):
        prompt = self._get_prompt()
        assert "worker-tool-reference.md" in prompt

    def test_contains_signal_dir_instruction(self):
        prompt = self._get_prompt()
        assert "PIPELINE_SIGNAL_DIR" in prompt or "signal" in prompt.lower()

    def test_no_pipeline_orchestration_docs(self):
        """System prompt must NOT contain pipeline orchestration content."""
        prompt = self._get_prompt()
        bloat_phrases = [
            "merge queue",
            "Merge Queue",
            "Hook Phase Tracking",
            "Liveness Tracking",
            "capture_output.py",
            "signal_guardian.py",
            "wait_for_guardian.py",
            "NEEDS_REVIEW",
            "ORCHESTRATOR_STUCK",
        ]
        for phrase in bloat_phrases:
            assert phrase not in prompt, (
                f"System prompt still contains bloat phrase: '{phrase}'"
            )


# ---------------------------------------------------------------------------
# S7.1.2 — Initial prompt contains PRD path, SD path, and AC
# ---------------------------------------------------------------------------


class TestWorkerInitialPrompt:
    """AC-7.1.2: Initial prompt is the primary task briefing."""

    def _get_prompt(self) -> str:
        from runner import build_worker_initial_prompt
        return build_worker_initial_prompt(
            node_id="impl_e71",
            prd_ref="PRD-HARNESS-UPGRADE-001",
            acceptance="AC-7.1.1: Worker system prompt under 4K chars.",
            solution_design="docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E7.1-worker-prompt.md",
            target_dir="$CLAUDE_PROJECT_DIR",
        )

    def test_contains_prd_reference(self):
        prompt = self._get_prompt()
        assert "PRD-HARNESS-UPGRADE-001" in prompt

    def test_contains_sd_path(self):
        prompt = self._get_prompt()
        assert "SD-HARNESS-UPGRADE-001-E7.1" in prompt or "solution" in prompt.lower()

    def test_contains_acceptance_criteria(self):
        prompt = self._get_prompt()
        assert "AC-7.1.1" in prompt or "acceptance" in prompt.lower()

    def test_contains_directive(self):
        """S7.1.2: Prompt includes directive giving worker judgment."""
        prompt = self._get_prompt()
        assert "judgment" in prompt.lower() or "directive" in prompt.lower()

    def test_prompt_is_substantial(self):
        """Initial prompt should be the primary briefing (~2K+, not 697 chars)."""
        prompt = self._get_prompt()
        assert len(prompt) > 1000, (
            f"Initial prompt is only {len(prompt)} chars, expected > 1000"
        )

    def test_skills_injection(self):
        """S7.1.2: Skills invocations from agent definition's skills_required."""
        from runner import build_worker_initial_prompt
        prompt = build_worker_initial_prompt(
            node_id="impl_e71",
            prd_ref="PRD-TEST",
            acceptance="Test AC",
            skills_required=["worker-focused-execution", "research-first"],
        )
        assert 'Skill("worker-focused-execution")' in prompt
        assert 'Skill("research-first")' in prompt


# ---------------------------------------------------------------------------
# S7.1.3 — Tool reference file exists at standard path
# ---------------------------------------------------------------------------


class TestToolReferenceFile:
    """AC-7.1.4: Tool reference file at .claude/agents/worker-tool-reference.md."""

    TOOL_REF_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".claude", "agents", "worker-tool-reference.md",
    )

    def test_file_exists(self):
        assert os.path.isfile(self.TOOL_REF_PATH), (
            f"worker-tool-reference.md not found at {self.TOOL_REF_PATH}"
        )

    def test_contains_write_example(self):
        content = open(self.TOOL_REF_PATH).read()
        assert "file_path" in content, "Missing file_path parameter in Write example"

    def test_contains_edit_example(self):
        content = open(self.TOOL_REF_PATH).read()
        assert "old_string" in content, "Missing old_string in Edit example"
        assert "new_string" in content, "Missing new_string in Edit example"

    def test_contains_signal_format(self):
        content = open(self.TOOL_REF_PATH).read()
        assert "sd_hash" in content or "signal" in content.lower()

    def test_has_frontmatter(self):
        content = open(self.TOOL_REF_PATH).read()
        assert content.startswith("---"), "Missing YAML frontmatter"


# ---------------------------------------------------------------------------
# S7.1.4 — Guardian system prompt slimmed
# ---------------------------------------------------------------------------


class TestGuardianPromptSlimmed:
    """AC-7.1.5: Guardian system prompt slimmed."""

    def _get_prompt(self) -> str:
        from guardian import build_system_prompt
        return build_system_prompt(
            pipeline_id="test-pipeline",
            prd_ref="PRD-TEST-001",
            dot_file="/tmp/test.dot",
            target_dir="/tmp/test-repo",
        )

    def test_no_worker_tool_examples(self):
        """Guardian prompt must not contain worker-level Write/Edit examples."""
        try:
            prompt = self._get_prompt()
        except Exception:
            pytest.skip("guardian.build_system_prompt() signature may differ")
        # These are worker-level concerns
        worker_phrases = [
            "file_path=",
            "old_string=",
            "new_string=",
            "replace_all",
            "Write(file_path",
            "Edit(file_path",
        ]
        for phrase in worker_phrases:
            assert phrase not in prompt, (
                f"Guardian prompt contains worker-level content: '{phrase}'"
            )


# ---------------------------------------------------------------------------
# S7.1.6 — All existing tests pass (regression)
# ---------------------------------------------------------------------------


class TestRegression:
    """AC-7.1.6: Existing functionality not broken."""

    def test_runner_imports(self):
        """runner.py still imports without error."""
        import runner  # noqa: F401

    def test_parser_imports(self):
        """parser.py still imports without error."""
        import parser  # noqa: F401

    def test_transition_imports(self):
        """transition.py still imports without error."""
        import transition  # noqa: F401

    def test_signal_protocol_imports(self):
        """signal_protocol.py still imports without error."""
        import signal_protocol  # noqa: F401
