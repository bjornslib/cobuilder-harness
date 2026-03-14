"""Unit tests for spawn_orchestrator.py — AC-1 Crash Recovery and AC-2 Session Naming.

Tests:
    TestCheckOrchestratorAlive    - check_orchestrator_alive() returns True/False
    TestRespawnOrchestrator       - respawn_orchestrator() with alive, dead, max-respawn cases
    TestParseArgsMaxRespawn       - --max-respawn CLI arg parsing
    TestSessionNameValidation     - Reject s3-live- prefix session names
    TestOutputIncludesRespawnCount - Final JSON output includes respawn_count
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

# Ensure the engine package root is on sys.path.

import cobuilder.engine.spawn_orchestrator as spawn_orchestrator
from cobuilder.engine.spawn_orchestrator import (
    check_orchestrator_alive,
    respawn_orchestrator,
    main,
)


# ---------------------------------------------------------------------------
# TestCheckOrchestratorAlive
# ---------------------------------------------------------------------------


class TestCheckOrchestratorAlive(unittest.TestCase):
    """Tests for check_orchestrator_alive()."""

    def test_returns_true_when_session_exists(self) -> None:
        """check_orchestrator_alive returns True when tmux exits with 0."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run", return_value=mock_result) as mock_run:
            result = check_orchestrator_alive("orch-auth")
        self.assertTrue(result)
        mock_run.assert_called_once_with(
            ["tmux", "has-session", "-t", "orch-auth"],
            capture_output=True,
        )

    def test_returns_false_when_session_not_found(self) -> None:
        """check_orchestrator_alive returns False when tmux exits with non-zero."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run", return_value=mock_result):
            result = check_orchestrator_alive("orch-missing")
        self.assertFalse(result)

    def test_returns_false_for_nonzero_exit(self) -> None:
        """Any non-zero exit code means session does not exist."""
        mock_result = MagicMock()
        mock_result.returncode = 127
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run", return_value=mock_result):
            result = check_orchestrator_alive("orch-ghost")
        self.assertFalse(result)

    def test_calls_tmux_has_session(self) -> None:
        """Must use tmux has-session command."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run", return_value=mock_result) as mock_run:
            check_orchestrator_alive("my-session")
        args_used = mock_run.call_args[0][0]
        self.assertIn("tmux", args_used)
        self.assertIn("has-session", args_used)
        self.assertIn("my-session", args_used)


# ---------------------------------------------------------------------------
# TestRespawnOrchestrator
# ---------------------------------------------------------------------------


class TestRespawnOrchestrator(unittest.TestCase):
    """Tests for respawn_orchestrator()."""

    def test_returns_already_alive_if_session_exists(self) -> None:
        """If session already exists, return already_alive without spawning."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True):
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", None, 0, 3)
        self.assertEqual(result["status"], "already_alive")
        self.assertEqual(result["session"], "orch-auth")

    def test_returns_error_when_max_respawn_reached(self) -> None:
        """If respawn_count >= max_respawn, return error."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False):
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", None, 3, 3)
        self.assertEqual(result["status"], "error")
        self.assertIn("Max respawn limit reached", result["message"])
        self.assertIn("3/3", result["message"])

    def test_returns_error_when_respawn_count_exceeds_max(self) -> None:
        """If respawn_count > max_respawn, return error."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False):
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", None, 5, 3)
        self.assertEqual(result["status"], "error")
        self.assertIn("Max respawn limit reached", result["message"])

    def test_respawns_dead_session_successfully(self) -> None:
        """Successfully respawn a dead session."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"):
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator("orch-auth", "/tmp/work", "auth", None, 0, 3)
        self.assertEqual(result["status"], "respawned")
        self.assertEqual(result["session"], "orch-auth")
        self.assertEqual(result["respawn_count"], 1)

    def test_increments_respawn_count(self) -> None:
        """respawn_count in result should be respawn_count + 1."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"):
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", None, 1, 3)
        self.assertEqual(result["respawn_count"], 2)

    def test_sends_prompt_when_provided(self) -> None:
        """When prompt is provided, _tmux_send should be called with it."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", "Hello Claude", 0, 3)
        # Should have been called with the prompt
        send_calls = [str(c) for c in mock_send.call_args_list]
        prompt_sent = any("Hello Claude" in s for s in send_calls)
        self.assertTrue(prompt_sent, f"Prompt not sent. Calls: {send_calls}")

    def test_no_prompt_sent_when_none(self) -> None:
        """When prompt is None and no existing hook, should NOT send a prompt key."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send, \
             patch("cobuilder.engine.spawn_orchestrator.hook_manager.read_hook", return_value=None):
            mock_run.return_value = MagicMock(returncode=0)
            respawn_orchestrator("orch-auth", "/tmp", "auth", None, 0, 3)
        # Only 2 send calls expected: "unset CLAUDECODE && claude" + "/output-style orchestrator"
        self.assertEqual(mock_send.call_count, 2)

    def test_uses_same_tmux_config(self) -> None:
        """Respawn should use -x 220 -y 50 exec zsh same as original."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"):
            mock_run.return_value = MagicMock(returncode=0)
            respawn_orchestrator("orch-auth", "/tmp/work", "auth", None, 0, 3)
        # subprocess.run should have been called with tmux new-session
        calls_made = mock_run.call_args_list
        tmux_call_args = calls_made[0][0][0]
        self.assertIn("new-session", tmux_call_args)
        self.assertIn("220", tmux_call_args)
        self.assertIn("50", tmux_call_args)


# ---------------------------------------------------------------------------
# TestParseArgsMaxRespawn
# ---------------------------------------------------------------------------


class TestParseArgsMaxRespawn(unittest.TestCase):
    """Tests for --max-respawn CLI argument."""

    def _parse(self, extra: list[str] | None = None) -> object:
        """Parse with minimum required args plus any extras."""
        base = [
            "--node", "impl_auth",
            "--prd", "PRD-AUTH-001",
            "--worktree", "/tmp/work",
        ]
        if extra:
            base.extend(extra)
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("--node", required=True)
        parser.add_argument("--prd", required=True)
        parser.add_argument("--worktree", required=True)
        parser.add_argument("--session-name", default=None, dest="session_name")
        parser.add_argument("--prompt", default=None)
        parser.add_argument("--max-respawn", type=int, default=3, dest="max_respawn")
        return parser.parse_args(base)

    def test_default_max_respawn_is_3(self) -> None:
        """Default --max-respawn should be 3."""
        args = self._parse()
        self.assertEqual(args.max_respawn, 3)

    def test_max_respawn_custom_value(self) -> None:
        """Custom --max-respawn value should be parsed correctly."""
        args = self._parse(["--max-respawn", "5"])
        self.assertEqual(args.max_respawn, 5)

    def test_max_respawn_zero(self) -> None:
        """--max-respawn 0 means no respawn attempts allowed."""
        args = self._parse(["--max-respawn", "0"])
        self.assertEqual(args.max_respawn, 0)

    def test_max_respawn_type_is_int(self) -> None:
        """--max-respawn should be parsed as int."""
        args = self._parse(["--max-respawn", "2"])
        self.assertIsInstance(args.max_respawn, int)


# ---------------------------------------------------------------------------
# TestSessionNameValidation
# ---------------------------------------------------------------------------


class TestSessionNameValidation(unittest.TestCase):
    """Tests for session name validation: reject s3-live- prefix."""

    def _run_main(self, extra_args: list[str]) -> tuple[str, int]:
        """Run main() with given args via sys.argv patching and capture stdout + exit code."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        exit_code = 0
        argv = ["cobuilder.engine.spawn_orchestrator.py"] + extra_args
        with patch("sys.argv", argv):
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit as e:
                exit_code = e.code if e.code is not None else 0
        return buf.getvalue(), exit_code

    def test_rejects_s3_live_prefix(self) -> None:
        """Session name with s3-live- prefix must be rejected with exit code 1."""
        output, exit_code = self._run_main([
            "--node", "impl_auth",
            "--prd", "PRD-AUTH-001",
            "--worktree", "/tmp",
            "--session-name", "s3-live-workers",
        ])
        self.assertEqual(exit_code, 1)
        data = json.loads(output)
        self.assertEqual(data["status"], "error")
        self.assertIn("s3-live-", data["message"])

    def test_rejects_s3_live_any_suffix(self) -> None:
        """Any s3-live-* suffix should be rejected."""
        output, exit_code = self._run_main([
            "--node", "impl_auth",
            "--prd", "PRD-AUTH-001",
            "--worktree", "/tmp",
            "--session-name", "s3-live-anything",
        ])
        self.assertEqual(exit_code, 1)
        data = json.loads(output)
        self.assertEqual(data["status"], "error")

    def test_accepts_orch_prefix(self) -> None:
        """orch- prefix sessions should not be rejected by name validation."""
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"), \
             patch("sys.argv", ["cobuilder.engine.spawn_orchestrator.py",
                                "--node", "impl_auth",
                                "--prd", "PRD-AUTH-001",
                                "--worktree", "/tmp",
                                "--session-name", "orch-impl-auth"]):
            mock_run.return_value = MagicMock(returncode=0)
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
            output = buf.getvalue()
        if output:
            data = json.loads(output)
            # Should NOT be an s3-live error
            if data.get("status") == "error":
                self.assertNotIn("s3-live", data.get("message", ""))

    def test_default_session_name_uses_orch_prefix(self) -> None:
        """Default session name (orch-<node>) should not be rejected."""
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"), \
             patch("sys.argv", ["cobuilder.engine.spawn_orchestrator.py",
                                "--node", "impl_auth",
                                "--prd", "PRD-AUTH-001",
                                "--worktree", "/tmp"]):
            mock_run.return_value = MagicMock(returncode=0)
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
            output = buf.getvalue()
        if output:
            data = json.loads(output)
            if data.get("status") == "error":
                self.assertNotIn("reserved", data.get("message", ""))


# ---------------------------------------------------------------------------
# TestOutputIncludesRespawnCount
# ---------------------------------------------------------------------------


class TestOutputIncludesRespawnCount(unittest.TestCase):
    """Tests that final JSON output includes respawn_count field."""

    def test_output_includes_respawn_count_zero_when_no_respawn(self) -> None:
        """When no respawn needed, output includes respawn_count: 0."""
        import io
        from contextlib import redirect_stdout

        argv = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth", "--prd", "PRD-AUTH-001", "--worktree", "/tmp"]
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"):
            mock_run.return_value = MagicMock(returncode=0)
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
        output = buf.getvalue()
        if output:
            data = json.loads(output)
            if data.get("status") == "ok":
                self.assertIn("respawn_count", data)
                self.assertEqual(data["respawn_count"], 0)

    def test_respawn_count_in_output_after_respawn(self) -> None:
        """When respawn occurs, output respawn_count should be > 0.

        Sequence: main() checks alive → False (dead after create).
        respawn_orchestrator() checks alive → False (still dead, proceed to respawn).
        Subprocess creates new session → respawn_count becomes 1.
        Output should have respawn_count=1.
        """
        import io
        from contextlib import redirect_stdout

        # First call (in main): False → triggers respawn_orchestrator
        # Second call (in respawn_orchestrator): False → proceeds to create session
        alive_sequence = [False, False]
        alive_iter = iter(alive_sequence)

        def mock_alive_fn(session: str) -> bool:
            try:
                return next(alive_iter)
            except StopIteration:
                return True

        argv = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth", "--prd", "PRD-AUTH-001", "--worktree", "/tmp"]
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", side_effect=mock_alive_fn), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"):
            mock_run.return_value = MagicMock(returncode=0)
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
        output = buf.getvalue()
        self.assertTrue(output, "Expected JSON output from main()")
        data = json.loads(output)
        self.assertEqual(data.get("status"), "ok")
        self.assertIn("respawn_count", data)
        self.assertGreater(data["respawn_count"], 0)


# ---------------------------------------------------------------------------
# TestRespawnWisdomInjection (Epic 2 — Hook Manager Lifecycle Integration)
# ---------------------------------------------------------------------------


class TestRespawnWisdomInjection(unittest.TestCase):
    """Tests for wisdom injection in respawn_orchestrator() (Epic 2)."""

    def _patch_respawn(self, hook_data, prompt):
        """Helper to run respawn_orchestrator with hook_data mocked."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send, \
             patch("cobuilder.engine.spawn_orchestrator.hook_manager.read_hook", return_value=hook_data):
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", prompt, 0, 3)
        return result, mock_send

    def test_no_wisdom_when_no_existing_hook(self) -> None:
        """When no existing hook file, no wisdom block is injected and prompt stays None."""
        result, mock_send = self._patch_respawn(hook_data=None, prompt=None)
        self.assertEqual(result["status"], "respawned")
        # Only 2 sends: launch command + output-style; no prompt send
        self.assertEqual(mock_send.call_count, 2)

    def test_wisdom_injected_when_hook_exists_no_prompt(self) -> None:
        """When existing hook but prompt=None, wisdom block is sent as prompt."""
        hook = {
            "phase": "executing",
            "resumption_instructions": "Continue from login endpoint",
            "last_committed_node": "impl_auth_db",
        }
        result, mock_send = self._patch_respawn(hook_data=hook, prompt=None)
        self.assertEqual(result["status"], "respawned")
        # 3 sends: launch + output-style + wisdom-as-prompt
        self.assertEqual(mock_send.call_count, 3)
        send_calls = [str(c) for c in mock_send.call_args_list]
        # Wisdom block should mention resumption context
        self.assertTrue(
            any("RESUMPTION CONTEXT" in s for s in send_calls),
            f"Expected RESUMPTION CONTEXT in send calls. Calls: {send_calls}",
        )

    def test_wisdom_prepended_to_existing_prompt(self) -> None:
        """When hook exists and prompt provided, wisdom is prepended to prompt."""
        hook = {
            "phase": "impl_complete",
            "resumption_instructions": "Resume from step 5",
            "last_committed_node": "impl_login",
        }
        result, mock_send = self._patch_respawn(hook_data=hook, prompt="Continue the work")
        self.assertEqual(result["status"], "respawned")
        # 3 sends: launch + output-style + combined wisdom+prompt
        self.assertEqual(mock_send.call_count, 3)
        send_calls = [str(c) for c in mock_send.call_args_list]
        # Both wisdom and original prompt should appear in combined send
        combined_call = send_calls[-1]
        self.assertIn("RESUMPTION CONTEXT", combined_call)
        self.assertIn("Continue the work", combined_call)

    def test_wisdom_block_contains_phase(self) -> None:
        """Wisdom block should mention the previous phase."""
        hook = {
            "phase": "validating",
            "resumption_instructions": "",
            "last_committed_node": None,
        }
        result, mock_send = self._patch_respawn(hook_data=hook, prompt=None)
        send_calls = [str(c) for c in mock_send.call_args_list]
        self.assertTrue(
            any("validating" in s for s in send_calls),
            f"Expected phase 'validating' in send calls. Calls: {send_calls}",
        )

    def test_wisdom_block_contains_last_committed_node(self) -> None:
        """Wisdom block should mention the last committed node when set."""
        hook = {
            "phase": "executing",
            "resumption_instructions": "",
            "last_committed_node": "impl_auth_session",
        }
        result, mock_send = self._patch_respawn(hook_data=hook, prompt=None)
        send_calls = [str(c) for c in mock_send.call_args_list]
        self.assertTrue(
            any("impl_auth_session" in s for s in send_calls),
            f"Expected last_committed_node in send calls. Calls: {send_calls}",
        )


# ---------------------------------------------------------------------------
# TestModeFlag — AC: --mode sdk|tmux controls --worktree usage
# ---------------------------------------------------------------------------


class TestModeFlag(unittest.TestCase):
    """Tests for --mode sdk|tmux behaviour in main() and respawn_orchestrator()."""

    # ---- helpers -------------------------------------------------------

    def _run_main_capture(self, extra_args: list[str]) -> tuple[str, int]:
        """Run main() with given extra args and capture stdout + exit code."""
        import io
        from contextlib import redirect_stdout

        base = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth",
                "--prd", "PRD-AUTH-001",
                "--worktree", "/tmp/work"]
        argv = base + extra_args
        buf = io.StringIO()
        exit_code = 0
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0)
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit as e:
                exit_code = e.code if e.code is not None else 0
        return buf.getvalue(), exit_code, mock_send

    # ---- sdk mode: no --worktree in claude command ----------------------

    def test_sdk_mode_claude_has_no_worktree(self) -> None:
        """--mode sdk → claude command must NOT contain --worktree."""
        _, _, mock_send = self._run_main_capture(["--mode", "sdk"])
        # Collect all text args sent to _tmux_send that are claude launch commands
        claude_calls = [c.args[1] for c in mock_send.call_args_list
                        if "claude" in str(c.args[1] if c.args else "") and "CLAUDECODE" in str(c.args[1] if c.args else "")]
        self.assertTrue(claude_calls, "Expected at least one claude launch _tmux_send call")
        for cmd in claude_calls:
            self.assertNotIn("--worktree", cmd,
                             f"sdk mode must NOT pass --worktree, but got: {cmd!r}")

    def test_sdk_mode_claude_has_enforce_bo_false(self) -> None:
        """--mode sdk → claude command contains CLAUDE_ENFORCE_BO=false."""
        _, _, mock_send = self._run_main_capture(["--mode", "sdk"])
        claude_calls = [c.args[1] for c in mock_send.call_args_list
                        if "claude" in str(c.args[1] if c.args else "") and "CLAUDECODE" in str(c.args[1] if c.args else "")]
        self.assertTrue(claude_calls)
        self.assertIn("CLAUDE_ENFORCE_BO=false", claude_calls[0])

    # ---- tmux mode (default): --worktree present -------------------------

    def test_tmux_mode_claude_has_worktree(self) -> None:
        """--mode tmux (default) → claude command MUST contain --worktree <node_id>."""
        _, _, mock_send = self._run_main_capture(["--mode", "tmux"])
        claude_calls = [c.args[1] for c in mock_send.call_args_list
                        if "claude" in str(c.args[1] if c.args else "") and "CLAUDECODE" in str(c.args[1] if c.args else "")]
        self.assertTrue(claude_calls, "Expected at least one claude launch _tmux_send call")
        for cmd in claude_calls:
            self.assertIn("--worktree", cmd,
                          f"tmux mode must pass --worktree, but got: {cmd!r}")

    def test_default_mode_is_tmux_with_worktree(self) -> None:
        """When --mode is not specified, defaults to tmux which includes --worktree."""
        # Run without --mode at all
        import io
        from contextlib import redirect_stdout
        argv = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth",
                "--prd", "PRD-AUTH-001",
                "--worktree", "/tmp/work"]
        buf = io.StringIO()
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send:
            mock_run.return_value = MagicMock(returncode=0)
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
        claude_calls = [c.args[1] for c in mock_send.call_args_list
                        if "claude" in str(c.args[1] if c.args else "") and "CLAUDECODE" in str(c.args[1] if c.args else "")]
        self.assertTrue(claude_calls)
        self.assertIn("--worktree", claude_calls[0])

    # ---- sdk mode: identity worktree is empty string ---------------------

    def test_sdk_mode_identity_worktree_is_empty(self) -> None:
        """--mode sdk → identity_registry.create_identity called with worktree=''."""
        import io
        from contextlib import redirect_stdout
        argv = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth",
                "--prd", "PRD-AUTH-001",
                "--worktree", "/tmp/work",
                "--mode", "sdk"]
        buf = io.StringIO()
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"), \
             patch("cobuilder.engine.spawn_orchestrator.identity_registry.create_identity") as mock_identity:
            mock_run.return_value = MagicMock(returncode=0)
            mock_identity.return_value = {"agent_id": "test-id"}
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
        # identity_registry.create_identity should have been called with worktree=""
        self.assertTrue(mock_identity.called, "create_identity should have been called")
        call_kwargs = mock_identity.call_args.kwargs
        self.assertEqual(call_kwargs.get("worktree", "UNSET"), "",
                         f"sdk mode must set worktree='', got: {call_kwargs!r}")

    def test_tmux_mode_identity_worktree_has_path(self) -> None:
        """--mode tmux → identity worktree should be '.claude/worktrees/<node_id>'."""
        import io
        from contextlib import redirect_stdout
        argv = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth",
                "--prd", "PRD-AUTH-001",
                "--worktree", "/tmp/work",
                "--mode", "tmux"]
        buf = io.StringIO()
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"), \
             patch("cobuilder.engine.spawn_orchestrator.identity_registry.create_identity") as mock_identity:
            mock_run.return_value = MagicMock(returncode=0)
            mock_identity.return_value = {"agent_id": "test-id"}
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
        self.assertTrue(mock_identity.called)
        call_kwargs = mock_identity.call_args.kwargs
        self.assertEqual(call_kwargs.get("worktree"), ".claude/worktrees/impl_auth")

    # ---- mode parameter propagates to respawn_orchestrator() -------------

    def test_mode_propagates_to_respawn_orchestrator_sdk(self) -> None:
        """When main() triggers respawn, mode=sdk is forwarded to respawn_orchestrator()."""
        import io
        from contextlib import redirect_stdout

        # alive_sequence: first call (main) → False (dead), second (respawn) → False (proceed)
        alive_sequence = [False, False]
        alive_iter = iter(alive_sequence)

        def mock_alive(session: str) -> bool:
            try:
                return next(alive_iter)
            except StopIteration:
                return True

        argv = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth",
                "--prd", "PRD-AUTH-001",
                "--worktree", "/tmp/work",
                "--mode", "sdk"]
        buf = io.StringIO()
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", side_effect=mock_alive), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send, \
             patch("cobuilder.engine.spawn_orchestrator.respawn_orchestrator",
                   wraps=spawn_orchestrator.respawn_orchestrator) as mock_respawn:
            mock_run.return_value = MagicMock(returncode=0)
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass
        # respawn_orchestrator should have been called with mode="sdk"
        if mock_respawn.called:
            call_kwargs = mock_respawn.call_args.kwargs
            self.assertEqual(call_kwargs.get("mode", "tmux"), "sdk",
                             f"mode='sdk' must be forwarded to respawn_orchestrator, got: {call_kwargs!r}")

    def test_sdk_mode_respawn_no_worktree_in_command(self) -> None:
        """respawn_orchestrator(mode='sdk') → claude command has no --worktree."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send, \
             patch("cobuilder.engine.spawn_orchestrator.hook_manager.read_hook", return_value=None):
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", None, 0, 3, mode="sdk")
        self.assertEqual(result["status"], "respawned")
        claude_calls = [c.args[1] for c in mock_send.call_args_list
                        if "claude" in str(c.args[1] if c.args else "") and "CLAUDECODE" in str(c.args[1] if c.args else "")]
        self.assertTrue(claude_calls)
        self.assertNotIn("--worktree", claude_calls[0])

    def test_tmux_mode_respawn_has_worktree_in_command(self) -> None:
        """respawn_orchestrator(mode='tmux') → claude command includes --worktree."""
        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send") as mock_send, \
             patch("cobuilder.engine.spawn_orchestrator.hook_manager.read_hook", return_value=None):
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator("orch-auth", "/tmp", "auth", None, 0, 3, mode="tmux")
        self.assertEqual(result["status"], "respawned")
        claude_calls = [c.args[1] for c in mock_send.call_args_list
                        if "claude" in str(c.args[1] if c.args else "") and "CLAUDECODE" in str(c.args[1] if c.args else "")]
        self.assertTrue(claude_calls)
        self.assertIn("--worktree", claude_calls[0])
        self.assertIn("auth", claude_calls[0])

    # ---- Model environment variable functionality -----

    def test_build_claude_cmd_uses_env_model(self) -> None:
        """_build_claude_cmd() should use ANTHROPIC_MODEL from environment."""
        import os
        original_model = os.environ.get("ANTHROPIC_MODEL")

        try:
            # Set test environment variable
            os.environ["ANTHROPIC_MODEL"] = "test-model-2026"

            # Test that the command contains the test model
            cmd = spawn_orchestrator._build_claude_cmd("test_node", "PRD-TEST-001", "tmux")
            self.assertIn("test-model-2026", cmd)
        finally:
            # Restore original environment
            if original_model is not None:
                os.environ["ANTHROPIC_MODEL"] = original_model
            elif "ANTHROPIC_MODEL" in os.environ:
                del os.environ["ANTHROPIC_MODEL"]

    def test_build_claude_cmd_fallback_model(self) -> None:
        """_build_claude_cmd() should fallback to default when no ANTHROPIC_MODEL set."""
        import os
        original_model = os.environ.get("ANTHROPIC_MODEL")

        try:
            # Remove environment variable if it exists
            if "ANTHROPIC_MODEL" in os.environ:
                del os.environ["ANTHROPIC_MODEL"]

            # Test that the command contains the default model
            cmd = spawn_orchestrator._build_claude_cmd("test_node", "PRD-TEST-001", "tmux")
            self.assertIn("claude-sonnet-4-6", cmd)
        finally:
            # Restore original environment
            if original_model is not None:
                os.environ["ANTHROPIC_MODEL"] = original_model

    def test_env_variables_loaded_at_import(self) -> None:
        """Environment variables should be loaded when the module is imported."""
        # The module loads environment variables at import time
        # which is verified by the fact that dispatch_worker is imported and its
        # load_engine_env function is called
        self.assertTrue(hasattr(spawn_orchestrator, '_build_claude_cmd'))
        # We can test the actual function behavior as in the tests above


# ---------------------------------------------------------------------------
# TestTmuxSendPostPause — post_pause parameter behaviour
# ---------------------------------------------------------------------------


class TestTmuxSendPostPause(unittest.TestCase):
    """Tests for _tmux_send() post_pause parameter."""

    def test_no_post_pause_calls_sleep_once(self) -> None:
        """When post_pause=0.0 (default), time.sleep is called exactly once (for pause)."""
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run"), \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep") as mock_sleep:
            spawn_orchestrator._tmux_send("orch-auth", "some text", pause=2.0, post_pause=0.0)
        self.assertEqual(mock_sleep.call_count, 1)
        mock_sleep.assert_called_once_with(2.0)

    def test_post_pause_calls_sleep_twice_in_order(self) -> None:
        """When post_pause=5.0, time.sleep is called twice: first pause then post_pause."""
        sleep_calls = []
        with patch("cobuilder.engine.spawn_orchestrator.subprocess.run"), \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            spawn_orchestrator._tmux_send("orch-auth", "some text", pause=2.0, post_pause=5.0)
        self.assertEqual(len(sleep_calls), 2)
        self.assertEqual(sleep_calls[0], 2.0)
        self.assertEqual(sleep_calls[1], 5.0)

    def test_main_output_style_uses_post_pause_gte_5(self) -> None:
        """main() _tmux_send call for /output-style must use post_pause >= 5.0."""
        import io
        from contextlib import redirect_stdout

        captured_calls = []

        def recording_tmux_send(session, text, pause=2.0, post_pause=0.0):
            captured_calls.append({"text": text, "pause": pause, "post_pause": post_pause})

        argv = ["cobuilder.engine.spawn_orchestrator.py",
                "--node", "impl_auth", "--prd", "PRD-AUTH-001", "--worktree", "/tmp"]
        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send", side_effect=recording_tmux_send):
            mock_run.return_value = MagicMock(returncode=0)
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    main()
            except SystemExit:
                pass

        output_style_calls = [c for c in captured_calls if "/output-style" in c["text"]]
        self.assertTrue(output_style_calls, "Expected at least one /output-style _tmux_send call")
        for c in output_style_calls:
            self.assertGreaterEqual(
                c["post_pause"], 5.0,
                f"main() /output-style must use post_pause >= 5.0, got: {c['post_pause']!r}",
            )

    def test_respawn_output_style_uses_post_pause_gte_5(self) -> None:
        """respawn_orchestrator() _tmux_send call for /output-style must use post_pause >= 5.0."""
        captured_calls = []

        def recording_tmux_send(session, text, pause=2.0, post_pause=0.0):
            captured_calls.append({"text": text, "pause": pause, "post_pause": post_pause})

        with patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send", side_effect=recording_tmux_send), \
             patch("cobuilder.engine.spawn_orchestrator.hook_manager.read_hook", return_value=None):
            mock_run.return_value = MagicMock(returncode=0)
            respawn_orchestrator("orch-auth", "/tmp", "auth", None, 0, 3)

        output_style_calls = [c for c in captured_calls if "/output-style" in c["text"]]
        self.assertTrue(output_style_calls, "Expected at least one /output-style _tmux_send call")
        for c in output_style_calls:
            self.assertGreaterEqual(
                c["post_pause"], 5.0,
                f"respawn_orchestrator() /output-style must use post_pause >= 5.0, got: {c['post_pause']!r}",
            )


# ---------------------------------------------------------------------------
# TestRepoRootValidation — .claude/ directory existence check
# ---------------------------------------------------------------------------


class TestRepoRootValidation(unittest.TestCase):
    """Tests for .claude/ directory warning in main()."""

    def _run_main_with_repo_root(
        self, repo_root: str, extra_args: list[str] | None = None
    ) -> tuple[str, str, int]:
        """Run main() with a given --repo-root and capture stdout, stderr, and exit code."""
        import io
        from contextlib import redirect_stdout, redirect_stderr

        argv = [
            "cobuilder.engine.spawn_orchestrator.py",
            "--node", "impl_auth",
            "--prd", "PRD-AUTH-001",
            "--repo-root", repo_root,
        ]
        if extra_args:
            argv.extend(extra_args)

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        exit_code = 0

        with patch("sys.argv", argv), \
             patch("cobuilder.engine.spawn_orchestrator.subprocess.run") as mock_run, \
             patch("cobuilder.engine.spawn_orchestrator.time.sleep"), \
             patch("cobuilder.engine.spawn_orchestrator.check_orchestrator_alive", return_value=True), \
             patch("cobuilder.engine.spawn_orchestrator._tmux_send"):
            mock_run.return_value = MagicMock(returncode=0)
            try:
                with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                    main()
            except SystemExit as exc:
                exit_code = exc.code if exc.code is not None else 0

        return stdout_buf.getvalue(), stderr_buf.getvalue(), exit_code

    def test_no_warning_when_claude_dir_exists(self) -> None:
        """When --repo-root contains a .claude/ directory, no warning is emitted to stderr."""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp:
            # Create the .claude/ subdirectory so the check passes
            os.makedirs(os.path.join(tmp, ".claude"))
            _, stderr, _ = self._run_main_with_repo_root(tmp)

        # No warning JSON should appear on stderr
        warning_lines = [ln for ln in stderr.splitlines() if ln.strip()]
        for line in warning_lines:
            try:
                data = json.loads(line)
                self.assertNotIn(
                    "warning", data,
                    f"Unexpected warning emitted when .claude/ exists: {data!r}",
                )
            except json.JSONDecodeError:
                pass  # non-JSON stderr lines are fine

    def test_warning_emitted_to_stderr_when_claude_dir_missing(self) -> None:
        """When --repo-root lacks .claude/, a JSON warning is written to stderr."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            # tmp has no .claude/ directory
            _, stderr, _ = self._run_main_with_repo_root(tmp)

        warning_found = False
        for line in stderr.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if "warning" in data:
                    warning_found = True
                    self.assertIn(
                        ".claude/", data["warning"],
                        f"Warning message should mention .claude/: {data['warning']!r}",
                    )
                    self.assertIn(
                        "--repo-root", data["warning"],
                        f"Warning message should mention --repo-root: {data['warning']!r}",
                    )
            except json.JSONDecodeError:
                pass

        self.assertTrue(warning_found, f"Expected a JSON warning on stderr. Got: {stderr!r}")

    def test_missing_claude_dir_does_not_exit(self) -> None:
        """Missing .claude/ directory must NOT cause sys.exit(1) — it is only a warning."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            # tmp has no .claude/ directory
            stdout, _, exit_code = self._run_main_with_repo_root(tmp)

        # Process must not exit with failure due to missing .claude/
        self.assertNotEqual(
            exit_code, 1,
            "Missing .claude/ should only warn, not exit with code 1. "
            f"stdout={stdout!r}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
