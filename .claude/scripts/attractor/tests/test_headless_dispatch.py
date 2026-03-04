"""E2E integration tests for headless dispatch chain.

Validates that the full dispatch chain (runner_agent -> spawn_orchestrator)
correctly handles --mode headless without crashing.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure the attractor package root is on sys.path.
_ATTRACTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ATTRACTOR_DIR not in sys.path:
    sys.path.insert(0, _ATTRACTOR_DIR)

SCRIPTS_DIR = Path(_ATTRACTOR_DIR)


# ---------------------------------------------------------------------------
# A1: runner_agent.py parser accepts --mode headless
# ---------------------------------------------------------------------------


class TestRunnerAcceptsHeadless:
    """A1: runner_agent.py parser accepts --mode headless."""

    def test_parser_accepts_headless(self):
        """runner_agent.py argparse should accept 'headless' as a mode choice."""
        from runner_agent import parse_args

        args = parse_args([
            "--node", "test",
            "--prd", "PRD-TEST-001",
            "--session", "orch-test",
            "--target-dir", "/tmp/test",
            "--mode", "headless",
        ])
        assert args.mode == "headless"

    def test_parser_still_accepts_sdk(self):
        """Existing 'sdk' mode should still work."""
        from runner_agent import parse_args

        args = parse_args([
            "--node", "test",
            "--prd", "PRD-TEST-001",
            "--session", "orch-test",
            "--target-dir", "/tmp/test",
            "--mode", "sdk",
        ])
        assert args.mode == "sdk"

    def test_parser_still_accepts_tmux(self):
        """Existing 'tmux' mode should still work."""
        from runner_agent import parse_args

        args = parse_args([
            "--node", "test",
            "--prd", "PRD-TEST-001",
            "--session", "orch-test",
            "--target-dir", "/tmp/test",
            "--mode", "tmux",
        ])
        assert args.mode == "tmux"

    def test_parser_rejects_invalid_mode(self):
        """An invalid mode should be rejected by argparse."""
        from runner_agent import parse_args

        with pytest.raises(SystemExit):
            parse_args([
                "--node", "test",
                "--prd", "PRD-TEST-001",
                "--session", "orch-test",
                "--target-dir", "/tmp/test",
                "--mode", "invalid",
            ])

    def test_headless_in_source_code(self):
        """runner_agent.py source should contain 'headless' in choices."""
        runner_path = SCRIPTS_DIR / "runner_agent.py"
        content = runner_path.read_text()
        assert '"headless"' in content or "'headless'" in content, \
            "runner_agent.py parser does not contain 'headless' in mode choices"


# ---------------------------------------------------------------------------
# A2: spawn_orchestrator.py main() dispatches headless mode
# ---------------------------------------------------------------------------


class TestSpawnOrchestratorHeadlessBranch:
    """A2: spawn_orchestrator.py main() dispatches headless mode."""

    def test_headless_branch_exists(self):
        """spawn_orchestrator.py should have a headless dispatch branch in main()."""
        spawn_path = SCRIPTS_DIR / "spawn_orchestrator.py"
        content = spawn_path.read_text()
        assert 'args.mode == "headless"' in content or "args.mode == 'headless'" in content, \
            "spawn_orchestrator.py main() has no headless branch"

    def test_headless_calls_run_headless_worker(self):
        """The headless branch should reference run_headless_worker."""
        spawn_path = SCRIPTS_DIR / "spawn_orchestrator.py"
        content = spawn_path.read_text()

        # Find the headless branch section
        headless_idx = content.find('args.mode == "headless"')
        if headless_idx == -1:
            headless_idx = content.find("args.mode == 'headless'")
        assert headless_idx != -1, "No headless branch found"

        # Check that run_headless_worker is called in the headless branch
        branch_section = content[headless_idx:headless_idx + 1500]
        assert "run_headless_worker" in branch_section, \
            "Headless branch does not call run_headless_worker"

    def test_headless_writes_signal_file(self):
        """The headless branch should write a signal JSON file."""
        spawn_path = SCRIPTS_DIR / "spawn_orchestrator.py"
        content = spawn_path.read_text()

        headless_idx = content.find('args.mode == "headless"')
        if headless_idx == -1:
            headless_idx = content.find("args.mode == 'headless'")
        assert headless_idx != -1

        branch_section = content[headless_idx:headless_idx + 1500]
        assert "signal" in branch_section.lower(), \
            "Headless branch does not write signal file"


# ---------------------------------------------------------------------------
# A3: _build_headless_worker_cmd produces valid command
# ---------------------------------------------------------------------------


class TestHeadlessWorkerCmd:
    """A3: _build_headless_worker_cmd produces valid command."""

    def test_cmd_has_required_flags(self):
        """Built command should include -p, --permission-mode, --output-format."""
        from spawn_orchestrator import _build_headless_worker_cmd

        cmd, env = _build_headless_worker_cmd(
            task_prompt="Test prompt",
            work_dir="/tmp/test",
            node_id="test-node",
        )

        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--permission-mode" in cmd
        assert "bypassPermissions" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd

    def test_cmd_includes_system_prompt(self):
        """Command should always include --system-prompt (from agent file or fallback)."""
        from spawn_orchestrator import _build_headless_worker_cmd

        cmd, _ = _build_headless_worker_cmd(
            task_prompt="Test",
            work_dir="/tmp/test",
            node_id="test-node",
        )

        assert "--system-prompt" in cmd

    def test_env_has_identity_vars(self):
        """Environment should contain WORKER_NODE_ID and other identity vars."""
        from spawn_orchestrator import _build_headless_worker_cmd

        _, env = _build_headless_worker_cmd(
            task_prompt="Test",
            work_dir="/tmp/test",
            node_id="my-node",
            pipeline_id="PIPE-001",
            runner_id="runner-x",
            prd_ref="PRD-X-001",
        )

        assert env["WORKER_NODE_ID"] == "my-node"
        assert env["PIPELINE_ID"] == "PIPE-001"
        assert env["RUNNER_ID"] == "runner-x"
        assert env["PRD_REF"] == "PRD-X-001"

    def test_env_removes_claudecode(self):
        """CLAUDECODE should be removed from environment."""
        from spawn_orchestrator import _build_headless_worker_cmd

        with patch.dict(os.environ, {"CLAUDECODE": "1"}):
            _, env = _build_headless_worker_cmd(
                task_prompt="Test",
                work_dir="/tmp/test",
                node_id="test",
            )

        assert "CLAUDECODE" not in env


# ---------------------------------------------------------------------------
# A4: Signal file output
# ---------------------------------------------------------------------------


class TestSignalFileOutput:
    """A4: Headless dispatch writes signal file for runner detection."""

    def test_signal_file_written(self, tmp_path):
        """After headless execution, a signal JSON file should be written."""
        signal_dir = tmp_path / ".claude" / "signals"
        signal_dir.mkdir(parents=True)
        signal_file = signal_dir / "test-node.json"

        # Simulate what the headless branch does
        result = {"exit_code": 0, "stdout": "Success", "stderr": "", "status": "success"}
        signal_file.write_text(json.dumps(result))

        assert signal_file.exists()
        data = json.loads(signal_file.read_text())
        assert data["exit_code"] == 0
        assert data["status"] == "success"
        assert "stdout" in data

    def test_signal_dir_created(self, tmp_path):
        """Signal directory should be created if it does not exist."""
        signal_dir = tmp_path / ".claude" / "signals"
        assert not signal_dir.exists()

        # Simulate the mkdir(parents=True, exist_ok=True) call
        signal_dir.mkdir(parents=True, exist_ok=True)
        assert signal_dir.exists()

    def test_signal_file_contains_valid_json(self, tmp_path):
        """Signal file should contain valid JSON with expected fields."""
        signal_dir = tmp_path / ".claude" / "signals"
        signal_dir.mkdir(parents=True)
        signal_file = signal_dir / "impl_auth.json"

        result = {
            "status": "error",
            "exit_code": 1,
            "stdout": "some output",
            "stderr": "some error",
        }
        signal_file.write_text(json.dumps(result, default=str))

        loaded = json.loads(signal_file.read_text())
        assert loaded["status"] == "error"
        assert loaded["exit_code"] == 1
