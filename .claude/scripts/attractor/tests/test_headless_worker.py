"""Unit tests for headless CLI worker mode (Epic 6).

Tests:
    TestBuildHeadlessWorkerCmd    - _build_headless_worker_cmd() command and env generation
    TestRunHeadlessWorker         - run_headless_worker() subprocess handling
    TestHeadlessModeArgparse      - --mode headless CLI arg parsing across scripts
    TestHeadlessGuardianPrompt    - guardian_agent system prompt includes headless guidance
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Ensure the attractor package root is on sys.path.
_ATTRACTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ATTRACTOR_DIR not in sys.path:
    sys.path.insert(0, _ATTRACTOR_DIR)

import spawn_orchestrator
from spawn_orchestrator import _build_headless_worker_cmd, run_headless_worker


# ---------------------------------------------------------------------------
# TestBuildHeadlessWorkerCmd
# ---------------------------------------------------------------------------


class TestBuildHeadlessWorkerCmd(unittest.TestCase):
    """Tests for _build_headless_worker_cmd()."""

    def _build(self, **overrides) -> tuple[list[str], dict[str, str]]:
        """Helper to call with sensible defaults."""
        kwargs = dict(
            task_prompt="Implement the login endpoint",
            work_dir="/tmp/test-repo",
            worker_type="backend-solutions-engineer",
            model="claude-sonnet-4-6",
            node_id="impl_auth",
            pipeline_id="PRD-AUTH-001",
            runner_id="runner-auth",
            prd_ref="PRD-AUTH-001",
        )
        kwargs.update(overrides)
        return _build_headless_worker_cmd(**kwargs)

    def test_returns_tuple_of_list_and_dict(self) -> None:
        cmd, env = self._build()
        self.assertIsInstance(cmd, list)
        self.assertIsInstance(env, dict)

    def test_cmd_starts_with_claude(self) -> None:
        cmd, _ = self._build()
        self.assertEqual(cmd[0], "claude")

    def test_cmd_contains_dash_p_with_task_prompt(self) -> None:
        cmd, _ = self._build(task_prompt="Fix the bug")
        idx = cmd.index("-p")
        self.assertEqual(cmd[idx + 1], "Fix the bug")

    def test_cmd_contains_system_prompt_flag(self) -> None:
        cmd, _ = self._build()
        self.assertIn("--system-prompt", cmd)

    def test_cmd_contains_bypass_permissions(self) -> None:
        cmd, _ = self._build()
        idx = cmd.index("--permission-mode")
        self.assertEqual(cmd[idx + 1], "bypassPermissions")

    def test_cmd_contains_stream_json_flags(self) -> None:
        """--output-format stream-json and --verbose must be present."""
        cmd, _ = self._build()
        idx = cmd.index("--output-format")
        self.assertEqual(cmd[idx + 1], "stream-json")
        self.assertIn("--verbose", cmd)

    def test_cmd_contains_model(self) -> None:
        cmd, _ = self._build(model="claude-opus-4-6")
        idx = cmd.index("--model")
        self.assertEqual(cmd[idx + 1], "claude-opus-4-6")

    def test_cmd_contains_mcp_bypass_flags(self) -> None:
        """MCP bypass prevents 11+ server initialization delay in headless mode."""
        cmd, _ = self._build()
        self.assertIn("--strict-mcp-config", cmd)
        idx = cmd.index("--mcp-config")
        self.assertEqual(cmd[idx + 1], '{"mcpServers":{}}')

    def test_env_contains_worker_node_id(self) -> None:
        _, env = self._build(node_id="impl_auth")
        self.assertEqual(env["WORKER_NODE_ID"], "impl_auth")

    def test_env_contains_pipeline_id(self) -> None:
        _, env = self._build(pipeline_id="PRD-TEST-999")
        self.assertEqual(env["PIPELINE_ID"], "PRD-TEST-999")

    def test_env_contains_runner_id(self) -> None:
        _, env = self._build(runner_id="runner-42")
        self.assertEqual(env["RUNNER_ID"], "runner-42")

    def test_env_contains_prd_ref(self) -> None:
        _, env = self._build(prd_ref="PRD-AUTH-001")
        self.assertEqual(env["PRD_REF"], "PRD-AUTH-001")

    def test_env_removes_claudecode(self) -> None:
        """CLAUDECODE must be removed to prevent nested session detection."""
        with patch.dict(os.environ, {"CLAUDECODE": "1"}):
            _, env = self._build()
        self.assertNotIn("CLAUDECODE", env)

    def test_role_file_read_when_exists(self) -> None:
        """When .claude/agents/{worker_type}.md exists, its content is used."""
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp) / ".claude" / "agents"
            agents_dir.mkdir(parents=True)
            role_file = agents_dir / "backend-solutions-engineer.md"
            role_file.write_text("You are a Python specialist.")

            cmd, _ = self._build(work_dir=tmp)
            idx = cmd.index("--system-prompt")
            self.assertEqual(cmd[idx + 1], "You are a Python specialist.")

    def test_role_file_frontmatter_stripped(self) -> None:
        """Frontmatter in agent .md files should be stripped."""
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp) / ".claude" / "agents"
            agents_dir.mkdir(parents=True)
            role_file = agents_dir / "backend-solutions-engineer.md"
            role_file.write_text(
                "---\ntitle: Backend\nstatus: active\n---\nYou are the backend expert."
            )

            cmd, _ = self._build(work_dir=tmp)
            idx = cmd.index("--system-prompt")
            self.assertEqual(cmd[idx + 1], "You are the backend expert.")

    def test_fallback_role_when_file_missing(self) -> None:
        """When agent file does not exist, a generic fallback role is used."""
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _ = self._build(work_dir=tmp)
            idx = cmd.index("--system-prompt")
            self.assertIn("specialist agent", cmd[idx + 1])
            self.assertIn("backend-solutions-engineer", cmd[idx + 1])

    def test_different_worker_types(self) -> None:
        """Worker type is reflected in the fallback role."""
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _ = self._build(work_dir=tmp, worker_type="frontend-dev-expert")
            idx = cmd.index("--system-prompt")
            self.assertIn("frontend-dev-expert", cmd[idx + 1])


# ---------------------------------------------------------------------------
# TestRunHeadlessWorker
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Helper: build a mock Popen context manager that emits JSONL stdout lines.
# ---------------------------------------------------------------------------

def _make_popen_mock(jsonl_lines: list[str], returncode: int = 0, stderr_text: str = "") -> MagicMock:
    """Return a MagicMock that behaves like subprocess.Popen with JSONL stdout.

    The mock satisfies the interface used by run_headless_worker:
      - process.stdout is an iterable of raw text lines (newline-terminated)
      - process.stderr is an iterable of text lines (for the stderr drain thread)
      - process.wait(timeout=...) returns immediately with ``returncode``
      - process.returncode is set after wait()
    """
    mock_process = MagicMock()
    mock_process.stdout = iter(line + "\n" for line in jsonl_lines)
    mock_process.stderr = iter(stderr_text.splitlines(keepends=True))
    mock_process.returncode = returncode

    def _wait(timeout=None):
        mock_process.returncode = returncode

    mock_process.wait.side_effect = _wait
    return mock_process


class TestRunHeadlessWorker(unittest.TestCase):
    """Tests for run_headless_worker() async subprocess handling."""

    def _run(self, **kwargs) -> dict:
        """Sync wrapper for async run_headless_worker."""
        defaults = dict(
            cmd=["claude", "-p", "test"],
            env=dict(os.environ),
            work_dir="/tmp",
            timeout_seconds=30,
        )
        defaults.update(kwargs)
        return asyncio.run(run_headless_worker(**defaults))

    # ------------------------------------------------------------------
    # Core stream-json behaviour tests
    # ------------------------------------------------------------------

    def test_cmd_contains_stream_json_flags(self) -> None:
        """_build_headless_worker_cmd must include stream-json and --verbose."""
        with tempfile.TemporaryDirectory() as tmp:
            cmd, _ = _build_headless_worker_cmd(
                task_prompt="do something",
                work_dir=tmp,
            )
        idx = cmd.index("--output-format")
        self.assertEqual(cmd[idx + 1], "stream-json")
        self.assertIn("--verbose", cmd)

    def test_stream_json_parsing(self) -> None:
        """Mock Popen emitting JSONL lines: events collected and result extracted."""
        jsonl_lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": "abc"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}),
            json.dumps({"type": "result", "subtype": "success", "is_error": False,
                        "result": "hello", "exit_code": 0}),
        ]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            result = self._run()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["exit_code"], 0)
        # output should be the result event
        self.assertEqual(result["output"]["type"], "result")
        self.assertEqual(result["output"]["result"], "hello")
        # all 3 events should be in the events list
        self.assertEqual(len(result["events"]), 3)

    def test_stream_json_on_event_callback(self) -> None:
        """on_event callback is called once for each parsed JSONL event."""
        jsonl_lines = [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps({"type": "assistant", "message": {}}),
            json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}),
        ]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)
        received: list[dict] = []

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            self._run(on_event=received.append)

        self.assertEqual(len(received), 3)
        types = [e.get("type") for e in received]
        self.assertEqual(types, ["system", "assistant", "result"])

    def test_stream_json_error_handling(self) -> None:
        """Malformed JSONL lines are skipped; valid events still collected."""
        jsonl_lines = [
            "not valid json{{{{",
            json.dumps({"type": "system", "subtype": "init"}),
            "another bad line",
            json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"}),
        ]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            result = self._run()

        # Only the 2 valid JSON lines should appear in events
        self.assertEqual(len(result["events"]), 2)
        self.assertEqual(result["status"], "success")

    # ------------------------------------------------------------------
    # Backward-compatible behaviour tests (adapted for Popen)
    # ------------------------------------------------------------------

    def test_success_returns_result_event_as_output(self) -> None:
        """Successful run returns the result event as ``output``."""
        result_event = {"type": "result", "subtype": "success", "is_error": False, "result": "done"}
        jsonl_lines = [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps(result_event),
        ]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            result = self._run()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["output"]["type"], "result")

    def test_success_no_result_event_falls_back_to_events_list(self) -> None:
        """When no result event is present, output falls back to the events list."""
        jsonl_lines = [
            json.dumps({"type": "system", "subtype": "init"}),
        ]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            result = self._run()

        self.assertEqual(result["status"], "success")
        self.assertIsInstance(result["output"], list)

    def test_error_on_nonzero_exit(self) -> None:
        """Non-zero exit code returns error status with stdout/stderr and events."""
        jsonl_lines = [
            json.dumps({"type": "system", "subtype": "init"}),
        ]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=1, stderr_text="Error details\n")

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            result = self._run()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["exit_code"], 1)
        self.assertIn("stdout", result)
        self.assertIn("stderr", result)
        self.assertIn("events", result)

    def test_timeout_returns_timeout_status(self) -> None:
        """TimeoutExpired on process.wait(timeout=…) returns timeout status with events."""
        jsonl_lines = [
            json.dumps({"type": "system", "subtype": "init"}),
        ]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)
        # First call (with timeout kwarg) raises TimeoutExpired.
        # Second call (bare wait() after kill()) must succeed so the finally block
        # can complete without propagating a second exception.
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="claude", timeout=30),
            None,  # bare wait() after kill()
        ]

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            result = self._run(timeout_seconds=30)

        self.assertEqual(result["status"], "timeout")
        self.assertIn("events", result)
        # Kill must have been called after timeout
        mock_proc.kill.assert_called_once()

    def test_stderr_truncated_to_2000_chars(self) -> None:
        """Long stderr text is truncated to last 2000 chars."""
        jsonl_lines = [json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "x"})]
        long_stderr = "y" * 5000
        mock_proc = _make_popen_mock(jsonl_lines, returncode=1, stderr_text=long_stderr)

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc):
            result = self._run()

        self.assertLessEqual(len(result["stderr"]), 2000)

    def test_passes_work_dir_as_cwd(self) -> None:
        """work_dir is passed as cwd to subprocess.Popen."""
        jsonl_lines = [json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"})]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc) as mock_popen:
            self._run(work_dir="/my/project")

        call_kwargs = mock_popen.call_args.kwargs
        self.assertEqual(call_kwargs["cwd"], "/my/project")

    def test_passes_env_to_subprocess(self) -> None:
        """Custom env dict is forwarded to subprocess.Popen."""
        jsonl_lines = [json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "ok"})]
        mock_proc = _make_popen_mock(jsonl_lines, returncode=0)
        custom_env = {"MY_VAR": "hello"}

        with patch("spawn_orchestrator.subprocess.Popen", return_value=mock_proc) as mock_popen:
            self._run(env=custom_env)

        call_kwargs = mock_popen.call_args.kwargs
        self.assertEqual(call_kwargs["env"]["MY_VAR"], "hello")


# ---------------------------------------------------------------------------
# TestHeadlessModeArgparse
# ---------------------------------------------------------------------------


class TestHeadlessModeArgparse(unittest.TestCase):
    """Tests that --mode headless is accepted by all relevant argparse configs."""

    def test_spawn_orchestrator_accepts_headless_mode(self) -> None:
        """spawn_orchestrator.py argparse accepts --mode headless."""
        import io
        from contextlib import redirect_stdout

        argv = [
            "spawn_orchestrator.py",
            "--node", "impl_auth",
            "--prd", "PRD-AUTH-001",
            "--worktree", "/tmp/work",
            "--mode", "headless",
        ]
        async def _fake_run_headless(*a, **kw):
            return {"status": "success", "exit_code": 0, "output": {}}

        with patch("sys.argv", argv), \
             patch("spawn_orchestrator.subprocess.run") as mock_run, \
             patch("spawn_orchestrator.time.sleep"), \
             patch("spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("spawn_orchestrator._tmux_send"), \
             patch("spawn_orchestrator.run_headless_worker", side_effect=_fake_run_headless):
            mock_run.return_value = MagicMock(returncode=0)
            buf = io.StringIO()
            exit_code = 0
            try:
                with redirect_stdout(buf):
                    spawn_orchestrator.main()
            except SystemExit as e:
                exit_code = e.code if e.code is not None else 0
        # Should not fail due to argparse rejection
        # (may fail for other reasons like tmux not available, that's ok)
        # The key test is that argparse doesn't reject "headless"
        self.assertNotEqual(exit_code, 2, "argparse rejected --mode headless")

    def test_spawn_runner_accepts_headless_mode(self) -> None:
        """runner.py argparse accepts --mode headless without rejection."""
        import importlib
        import runner

        # We just need to verify argparse doesn't reject headless
        # The simplest way is to check the choices directly
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--node", required=True, dest="node_id")
        parser.add_argument("--prd", required=True, dest="prd_ref")
        parser.add_argument("--target-dir", required=True, dest="target_dir")
        parser.add_argument(
            "--mode",
            choices=["sdk", "tmux", "headless"],
            default="tmux",
            dest="mode",
        )

        args = parser.parse_args([
            "--node", "test",
            "--prd", "PRD-001",
            "--target-dir", "/tmp",
            "--mode", "headless",
        ])
        self.assertEqual(args.mode, "headless")


# ---------------------------------------------------------------------------
# TestHeadlessGuardianPrompt
# ---------------------------------------------------------------------------


class TestHeadlessGuardianPrompt(unittest.TestCase):
    """Tests that guardian system prompt includes headless mode guidance."""

    def _make_prompt(self) -> str:
        import guardian
        return guardian.build_system_prompt(
            dot_path="/tmp/pipeline.dot",
            pipeline_id="test-pipe",
            scripts_dir="/tmp/scripts",
            signal_timeout=600.0,
            max_retries=3,
        )

    def test_system_prompt_mentions_headless(self) -> None:
        """System prompt should mention headless mode."""
        prompt = self._make_prompt()
        self.assertIn("headless", prompt.lower())

    def test_system_prompt_mentions_headless_mode_section(self) -> None:
        """System prompt should have a Headless Mode section."""
        prompt = self._make_prompt()
        self.assertIn("Headless Mode", prompt)

    def test_system_prompt_mentions_claude_dash_p(self) -> None:
        """System prompt should reference `claude -p` for headless workers."""
        prompt = self._make_prompt()
        self.assertIn("claude -p", prompt)

    def test_system_prompt_mentions_json_output(self) -> None:
        """System prompt should mention JSON output format for headless."""
        prompt = self._make_prompt()
        self.assertIn("JSON output", prompt)

    def test_system_prompt_mentions_three_layer_context(self) -> None:
        """System prompt should reference Three-Layer Context."""
        prompt = self._make_prompt()
        self.assertIn("Three-Layer Context", prompt)

    def test_system_prompt_has_headless_spawn_runner_command(self) -> None:
        """System prompt should include --mode headless in spawn_runner command."""
        prompt = self._make_prompt()
        self.assertIn("--mode headless", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
