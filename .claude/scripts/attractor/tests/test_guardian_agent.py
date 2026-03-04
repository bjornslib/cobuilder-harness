"""Unit tests for guardian.py — Layer 1 Guardian Agent.

Tests:
    TestParseArgs               - parse_args() with various CLI combinations
    TestBuildSystemPrompt       - build_system_prompt() content and format
    TestBuildInitialPrompt      - build_initial_prompt() content and format
    TestBuildOptions            - build_options() returns correct ClaudeCodeOptions
    TestDryRunMode              - --dry-run exits 0 and prints JSON config
    TestEnvConfig               - build_env_config() handles CLAUDECODE correctly
    TestResolveScriptsDir       - resolve_scripts_dir() returns valid path
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

# Ensure the attractor package root is on sys.path (mirrors conftest.py).
_ATTRACTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ATTRACTOR_DIR not in sys.path:
    sys.path.insert(0, _ATTRACTOR_DIR)

import guardian  # noqa: E402
from guardian import (  # noqa: E402
    build_env_config,
    build_initial_prompt,
    build_options,
    build_system_prompt,
    parse_args,
    resolve_scripts_dir,
    DEFAULT_MAX_TURNS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_SIGNAL_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DOT_PATH = "/path/to/pipeline.dot"
_PIPELINE_ID = "my-pipeline-001"
_SCRIPTS_DIR = "/path/to/scripts"
_SIGNAL_TIMEOUT = 600.0
_MAX_RETRIES = 3


def _make_system_prompt(**overrides) -> str:
    kwargs = dict(
        dot_path=_DOT_PATH,
        pipeline_id=_PIPELINE_ID,
        scripts_dir=_SCRIPTS_DIR,
        signal_timeout=_SIGNAL_TIMEOUT,
        max_retries=_MAX_RETRIES,
    )
    kwargs.update(overrides)
    return build_system_prompt(**kwargs)


def _make_initial_prompt(**overrides) -> str:
    kwargs = dict(
        dot_path=_DOT_PATH,
        pipeline_id=_PIPELINE_ID,
        scripts_dir=_SCRIPTS_DIR,
    )
    kwargs.update(overrides)
    return build_initial_prompt(**kwargs)


# ---------------------------------------------------------------------------
# TestParseArgs
# ---------------------------------------------------------------------------


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args()."""

    # Minimum required args now include --target-dir (made required in AC-3)
    _MIN_ARGS = ["--dot", "/p.dot", "--pipeline-id", "p1", "--target-dir", "/tmp/target"]

    def test_required_args_only(self) -> None:
        args = parse_args([
            "--dot", "/some/pipeline.dot", "--pipeline-id", "pipe-001",
            "--target-dir", "/tmp/target",
        ])
        self.assertEqual(args.dot, "/some/pipeline.dot")
        self.assertEqual(args.pipeline_id, "pipe-001")

    def test_defaults(self) -> None:
        args = parse_args(self._MIN_ARGS)
        self.assertEqual(args.max_turns, DEFAULT_MAX_TURNS)
        self.assertEqual(args.signal_timeout, DEFAULT_SIGNAL_TIMEOUT)
        self.assertEqual(args.max_retries, DEFAULT_MAX_RETRIES)
        self.assertEqual(args.model, DEFAULT_MODEL)
        self.assertIsNone(args.project_root)
        self.assertIsNone(args.signals_dir)
        self.assertFalse(args.dry_run)

    def test_full_args(self) -> None:
        args = parse_args([
            "--dot", "/tmp/pipeline.dot",
            "--pipeline-id", "PRD-PIPE-007",
            "--project-root", "/tmp/project",
            "--max-turns", "300",
            "--model", "claude-opus-4-6",
            "--signals-dir", "/tmp/signals",
            "--signal-timeout", "300.5",
            "--max-retries", "5",
            "--target-dir", "/tmp/target",
            "--dry-run",
        ])
        self.assertEqual(args.dot, "/tmp/pipeline.dot")
        self.assertEqual(args.pipeline_id, "PRD-PIPE-007")
        self.assertEqual(args.project_root, "/tmp/project")
        self.assertEqual(args.max_turns, 300)
        self.assertEqual(args.model, "claude-opus-4-6")
        self.assertEqual(args.signals_dir, "/tmp/signals")
        self.assertEqual(args.signal_timeout, 300.5)
        self.assertEqual(args.max_retries, 5)
        self.assertTrue(args.dry_run)

    def test_missing_required_dot_exits(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--pipeline-id", "p1", "--target-dir", "/tmp/target"])

    def test_missing_required_pipeline_id_exits(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--dot", "/p.dot", "--target-dir", "/tmp/target"])

    def test_missing_target_dir_defaults_none(self) -> None:
        """--target-dir is optional in merged guardian.py; omitting it yields None."""
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1"])
        self.assertIsNone(args.target_dir)

    def test_missing_all_required_exits(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_max_turns_type(self) -> None:
        args = parse_args(self._MIN_ARGS + ["--max-turns", "150"])
        self.assertIsInstance(args.max_turns, int)
        self.assertEqual(args.max_turns, 150)

    def test_signal_timeout_type(self) -> None:
        args = parse_args(self._MIN_ARGS + ["--signal-timeout", "120.0"])
        self.assertIsInstance(args.signal_timeout, float)
        self.assertEqual(args.signal_timeout, 120.0)

    def test_max_retries_type(self) -> None:
        args = parse_args(self._MIN_ARGS + ["--max-retries", "7"])
        self.assertIsInstance(args.max_retries, int)
        self.assertEqual(args.max_retries, 7)

    def test_dry_run_default_false(self) -> None:
        args = parse_args(self._MIN_ARGS)
        self.assertFalse(args.dry_run)

    def test_dry_run_flag_true(self) -> None:
        args = parse_args(self._MIN_ARGS + ["--dry-run"])
        self.assertTrue(args.dry_run)

    def test_project_root_optional(self) -> None:
        args = parse_args(self._MIN_ARGS + ["--project-root", "/my/root"])
        self.assertEqual(args.project_root, "/my/root")

    def test_signals_dir_optional(self) -> None:
        args = parse_args(self._MIN_ARGS + ["--signals-dir", "/my/signals"])
        self.assertEqual(args.signals_dir, "/my/signals")

    def test_default_max_turns_is_200(self) -> None:
        args = parse_args(self._MIN_ARGS)
        self.assertEqual(args.max_turns, 200)

    def test_default_signal_timeout_is_600(self) -> None:
        args = parse_args(self._MIN_ARGS)
        self.assertEqual(args.signal_timeout, 600.0)

    def test_default_max_retries_is_3(self) -> None:
        args = parse_args(self._MIN_ARGS)
        self.assertEqual(args.max_retries, 3)


# ---------------------------------------------------------------------------
# TestBuildSystemPrompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt(unittest.TestCase):
    """Tests for build_system_prompt()."""

    def test_returns_string(self) -> None:
        result = _make_system_prompt()
        self.assertIsInstance(result, str)

    def test_contains_dot_path(self) -> None:
        result = _make_system_prompt(dot_path="/custom/my_pipeline.dot")
        self.assertIn("/custom/my_pipeline.dot", result)

    def test_contains_pipeline_id(self) -> None:
        result = _make_system_prompt(pipeline_id="PRD-FEAT-042")
        self.assertIn("PRD-FEAT-042", result)

    def test_contains_scripts_dir(self) -> None:
        result = _make_system_prompt(scripts_dir="/custom/scripts")
        self.assertIn("/custom/scripts", result)

    def test_contains_signal_timeout(self) -> None:
        result = _make_system_prompt(signal_timeout=300.0)
        self.assertIn("300", result)

    def test_contains_max_retries(self) -> None:
        result = _make_system_prompt(max_retries=5)
        self.assertIn("5", result)

    def test_contains_all_signal_handler_names(self) -> None:
        result = _make_system_prompt()
        for signal_type in [
            "NEEDS_REVIEW",
            "NEEDS_INPUT",
            "VIOLATION",
            "ORCHESTRATOR_STUCK",
            "ORCHESTRATOR_CRASHED",
            "NODE_COMPLETE",
        ]:
            self.assertIn(signal_type, result, f"Missing signal handler: {signal_type}")

    def test_contains_all_respond_to_runner_types(self) -> None:
        result = _make_system_prompt()
        for response_type in [
            "VALIDATION_PASSED",
            "VALIDATION_FAILED",
            "INPUT_RESPONSE",
            "KILL_ORCHESTRATOR",
            "GUIDANCE",
        ]:
            self.assertIn(response_type, result, f"Missing response type: {response_type}")

    def test_contains_cli_status_command(self) -> None:
        result = _make_system_prompt()
        self.assertIn("cli.py status", result)

    def test_contains_cli_transition_command(self) -> None:
        result = _make_system_prompt()
        self.assertIn("cli.py transition", result)

    def test_contains_cli_checkpoint_command(self) -> None:
        result = _make_system_prompt()
        self.assertIn("cli.py checkpoint", result)

    def test_contains_spawn_runner(self) -> None:
        result = _make_system_prompt()
        self.assertIn("runner.py --spawn", result)

    def test_contains_wait_for_signal(self) -> None:
        result = _make_system_prompt()
        self.assertIn("wait_for_signal.py", result)

    def test_contains_escalate_to_terminal(self) -> None:
        result = _make_system_prompt()
        self.assertIn("escalate_to_terminal.py", result)

    def test_contains_never_edit_or_write(self) -> None:
        result = _make_system_prompt()
        self.assertIn("NEVER use Edit or Write", result)

    def test_contains_checkpoint_after_every(self) -> None:
        result = _make_system_prompt()
        self.assertIn("checkpoint after every", result)

    def test_contains_phase_1(self) -> None:
        result = _make_system_prompt()
        self.assertIn("Phase 1", result)

    def test_contains_phase_2(self) -> None:
        result = _make_system_prompt()
        self.assertIn("Phase 2", result)

    def test_contains_phase_3(self) -> None:
        result = _make_system_prompt()
        self.assertIn("Phase 3", result)

    def test_contains_phase_4(self) -> None:
        result = _make_system_prompt()
        self.assertIn("Phase 4", result)

    def test_substantial_length(self) -> None:
        result = _make_system_prompt()
        self.assertGreater(len(result), 2000)

    def test_contains_respond_to_runner_script(self) -> None:
        result = _make_system_prompt()
        self.assertIn("respond_to_runner.py", result)

    def test_contains_layer_1_description(self) -> None:
        result = _make_system_prompt()
        self.assertIn("Layer 1", result)


# ---------------------------------------------------------------------------
# TestBuildInitialPrompt
# ---------------------------------------------------------------------------


class TestBuildInitialPrompt(unittest.TestCase):
    """Tests for build_initial_prompt()."""

    def test_returns_string(self) -> None:
        result = _make_initial_prompt()
        self.assertIsInstance(result, str)

    def test_contains_dot_path(self) -> None:
        result = _make_initial_prompt(dot_path="/custom/pipe.dot")
        self.assertIn("/custom/pipe.dot", result)

    def test_contains_pipeline_id(self) -> None:
        result = _make_initial_prompt(pipeline_id="PRD-PIPE-999")
        self.assertIn("PRD-PIPE-999", result)

    def test_contains_scripts_dir(self) -> None:
        result = _make_initial_prompt(scripts_dir="/my/scripts")
        self.assertIn("/my/scripts", result)

    def test_contains_parsing_instruction(self) -> None:
        result = _make_initial_prompt()
        self.assertIn("Parsing the pipeline", result)

    def test_contains_dispatch_ready_nodes_or_phase2(self) -> None:
        result = _make_initial_prompt()
        self.assertTrue(
            "dispatch ready nodes" in result or "Phase 2" in result,
            "Initial prompt should reference Phase 2 or dispatching ready nodes",
        )

    def test_contains_validate_structure(self) -> None:
        result = _make_initial_prompt()
        # Should mention validation of the pipeline structure
        lower = result.lower()
        self.assertIn("validat", lower)

    def test_reasonable_length(self) -> None:
        result = _make_initial_prompt()
        self.assertGreater(len(result), 100)
        self.assertLess(len(result), 2000)

    def test_contains_partially_complete_guidance(self) -> None:
        result = _make_initial_prompt()
        # Should mention handling already-validated nodes
        lower = result.lower()
        self.assertTrue(
            "already" in lower or "partial" in lower or "current state" in lower,
            "Initial prompt should mention partially complete pipeline handling",
        )


# ---------------------------------------------------------------------------
# TestBuildOptions
# ---------------------------------------------------------------------------


class TestBuildOptions(unittest.TestCase):
    """Tests for build_options()."""

    def _build(self, **overrides) -> object:
        kwargs = dict(
            system_prompt="Test system prompt",
            cwd="/tmp",
            model=DEFAULT_MODEL,
            max_turns=DEFAULT_MAX_TURNS,
        )
        kwargs.update(overrides)
        return build_options(**kwargs)

    def test_returns_claude_code_options(self) -> None:
        from claude_code_sdk import ClaudeCodeOptions
        opts = self._build()
        self.assertIsInstance(opts, ClaudeCodeOptions)

    def test_allowed_tools_bash_only(self) -> None:
        opts = self._build()
        self.assertEqual(opts.allowed_tools, ["Bash"])

    def test_system_prompt_set(self) -> None:
        opts = self._build(system_prompt="Guardian instructions here")
        self.assertEqual(opts.system_prompt, "Guardian instructions here")

    def test_cwd_set(self) -> None:
        opts = self._build(cwd="/project/root")
        self.assertEqual(str(opts.cwd), "/project/root")

    def test_model_set(self) -> None:
        opts = self._build(model="claude-opus-4-6")
        self.assertEqual(opts.model, "claude-opus-4-6")

    def test_max_turns_set(self) -> None:
        opts = self._build(max_turns=200)
        self.assertEqual(opts.max_turns, 200)

    def test_env_contains_claudecode_override(self) -> None:
        opts = self._build()
        self.assertIn("CLAUDECODE", opts.env)
        self.assertEqual(opts.env["CLAUDECODE"], "")

    def test_default_model(self) -> None:
        opts = self._build(model=DEFAULT_MODEL)
        self.assertEqual(opts.model, DEFAULT_MODEL)


# ---------------------------------------------------------------------------
# TestDryRunMode
# ---------------------------------------------------------------------------


class TestDryRunMode(unittest.TestCase):
    """Tests for --dry-run: should exit 0 and print JSON config."""

    def _run_dry(self, extra_args: list[str] | None = None) -> str:
        """Run main() in dry-run mode and capture stdout as a string."""
        import io
        from contextlib import redirect_stdout

        base_args = ["--dot", "/tmp/pipe.dot", "--pipeline-id", "test-pipe-001",
                     "--target-dir", "/tmp", "--dry-run"]
        if extra_args:
            base_args.extend(extra_args)

        buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(buf):
                guardian.main(base_args)

        self.assertEqual(cm.exception.code, 0)
        return buf.getvalue()

    def test_dry_run_exits_zero(self) -> None:
        # _run_dry already asserts exit code 0
        self._run_dry()

    def test_dry_run_prints_json(self) -> None:
        output = self._run_dry()
        data = json.loads(output)  # must not raise
        self.assertIsInstance(data, dict)

    def test_dry_run_json_has_dry_run_true(self) -> None:
        data = json.loads(self._run_dry())
        self.assertTrue(data["dry_run"])

    def test_dry_run_json_has_dot_path(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("dot_path", data)
        # dot_path is resolved to absolute
        self.assertTrue(os.path.isabs(data["dot_path"]))

    def test_dry_run_json_has_pipeline_id(self) -> None:
        data = json.loads(self._run_dry())
        self.assertEqual(data["pipeline_id"], "test-pipe-001")

    def test_dry_run_json_has_model(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("model", data)
        self.assertEqual(data["model"], DEFAULT_MODEL)

    def test_dry_run_json_has_max_turns(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("max_turns", data)
        self.assertEqual(data["max_turns"], DEFAULT_MAX_TURNS)

    def test_dry_run_json_has_signal_timeout(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("signal_timeout", data)
        self.assertEqual(data["signal_timeout"], DEFAULT_SIGNAL_TIMEOUT)

    def test_dry_run_json_has_max_retries(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("max_retries", data)
        self.assertEqual(data["max_retries"], DEFAULT_MAX_RETRIES)

    def test_dry_run_json_has_scripts_dir(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("scripts_dir", data)
        self.assertTrue(os.path.isabs(data["scripts_dir"]))

    def test_dry_run_json_has_prompt_lengths(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("system_prompt_length", data)
        self.assertIn("initial_prompt_length", data)
        self.assertGreater(data["system_prompt_length"], 0)
        self.assertGreater(data["initial_prompt_length"], 0)

    def test_dry_run_system_prompt_length_positive(self) -> None:
        data = json.loads(self._run_dry())
        self.assertGreater(data["system_prompt_length"], 0)

    def test_dry_run_accepts_optional_args(self) -> None:
        extra = [
            "--project-root", "/tmp",
            "--max-turns", "300",
            "--signal-timeout", "120.0",
            "--max-retries", "5",
        ]
        data = json.loads(self._run_dry(extra))
        self.assertEqual(data["project_root"], "/tmp")
        self.assertEqual(data["max_turns"], 300)
        self.assertEqual(data["signal_timeout"], 120.0)
        self.assertEqual(data["max_retries"], 5)

    def test_dry_run_does_not_call_run_agent(self) -> None:
        """Dry-run must never invoke the SDK _run_agent()."""
        import io
        from contextlib import redirect_stdout

        with patch("guardian._run_agent") as mock_run:
            buf = io.StringIO()
            with self.assertRaises(SystemExit):
                with redirect_stdout(buf):
                    guardian.main(
                        ["--dot", "/tmp/p.dot", "--pipeline-id", "p",
                         "--target-dir", "/tmp", "--dry-run"]
                    )
            mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# TestResolveScriptsDir
# ---------------------------------------------------------------------------


class TestResolveScriptsDir(unittest.TestCase):
    """Tests for resolve_scripts_dir()."""

    def test_returns_string(self) -> None:
        result = resolve_scripts_dir()
        self.assertIsInstance(result, str)

    def test_returns_absolute_path(self) -> None:
        result = resolve_scripts_dir()
        self.assertTrue(os.path.isabs(result), f"Expected absolute path, got: {result}")

    def test_path_exists(self) -> None:
        result = resolve_scripts_dir()
        self.assertTrue(os.path.isdir(result), f"Scripts dir does not exist: {result}")

    def test_contains_guardian_agent_itself(self) -> None:
        result = resolve_scripts_dir()
        self.assertTrue(
            os.path.exists(os.path.join(result, "guardian.py")),
            f"guardian.py not found in {result}",
        )

    def test_contains_wait_for_signal(self) -> None:
        result = resolve_scripts_dir()
        expected = os.path.join(result, "wait_for_signal.py")
        self.assertTrue(
            os.path.exists(expected),
            f"Expected wait_for_signal.py in {result}",
        )

    def test_consistent_across_calls(self) -> None:
        result1 = resolve_scripts_dir()
        result2 = resolve_scripts_dir()
        self.assertEqual(result1, result2)

    def test_contains_runner_agent(self) -> None:
        result = resolve_scripts_dir()
        self.assertTrue(
            os.path.exists(os.path.join(result, "runner.py")),
            f"runner.py not found in {result}",
        )


# ---------------------------------------------------------------------------
# TestEnvConfig
# ---------------------------------------------------------------------------


class TestEnvConfig(unittest.TestCase):
    """Tests for build_env_config()."""

    def test_returns_dict(self) -> None:
        result = build_env_config()
        self.assertIsInstance(result, dict)

    def test_claudecode_key_present(self) -> None:
        result = build_env_config()
        self.assertIn("CLAUDECODE", result)

    def test_claudecode_value_is_empty_string(self) -> None:
        """We suppress CLAUDECODE by overriding to empty string."""
        result = build_env_config()
        self.assertEqual(result["CLAUDECODE"], "")

    def test_does_not_contain_arbitrary_env(self) -> None:
        """build_env_config should only return intentional overrides."""
        result = build_env_config()
        self.assertNotIn("PATH", result)
        self.assertNotIn("HOME", result)

    def test_build_options_env_matches_env_config(self) -> None:
        """build_options env should contain the same CLAUDECODE key."""
        env_config = build_env_config()
        opts = build_options(
            system_prompt="test",
            cwd="/tmp",
            model=DEFAULT_MODEL,
            max_turns=DEFAULT_MAX_TURNS,
        )
        self.assertEqual(opts.env.get("CLAUDECODE"), env_config["CLAUDECODE"])

    def test_build_options_env_claudecode_is_empty(self) -> None:
        opts = build_options(
            system_prompt="test",
            cwd="/tmp",
            model=DEFAULT_MODEL,
            max_turns=DEFAULT_MAX_TURNS,
        )
        self.assertEqual(opts.env["CLAUDECODE"], "")


# ---------------------------------------------------------------------------
# TestLogfireInstrumentation
# ---------------------------------------------------------------------------


class TestLogfireInstrumentation(unittest.TestCase):
    """Tests that logfire instrumentation is present and doesn't break functionality."""

    def test_logfire_is_imported(self):
        """guardian should import logfire directly (required dependency)."""
        import logfire as _lf
        self.assertTrue(hasattr(_lf, 'span'))

    def test_build_system_prompt_works_with_logfire(self):
        """build_system_prompt should work regardless of logfire availability."""
        result = _make_system_prompt()
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 100)

    def test_build_options_works_with_logfire(self):
        """build_options should work regardless of logfire availability."""
        opts = build_options(
            system_prompt="test",
            cwd="/tmp",
            model=DEFAULT_MODEL,
            max_turns=DEFAULT_MAX_TURNS,
        )
        self.assertEqual(opts.allowed_tools, ["Bash"])


# ---------------------------------------------------------------------------
# TestHookPhaseTracking (Epic 2 — Hook Manager Lifecycle Integration)
# ---------------------------------------------------------------------------


class TestHookPhaseTracking(unittest.TestCase):
    """Tests that build_system_prompt() includes hook phase tracking instructions."""

    def test_contains_hook_phase_tracking_section(self) -> None:
        """System prompt must contain Hook Phase Tracking section header."""
        result = _make_system_prompt()
        self.assertIn("Hook Phase Tracking", result)

    def test_contains_validating_phase_command(self) -> None:
        """System prompt must instruct guardian to call update-phase validating."""
        result = _make_system_prompt()
        self.assertIn("validating", result)
        self.assertIn("update-phase", result)

    def test_contains_merged_phase_command(self) -> None:
        """System prompt must instruct guardian to call update-phase merged."""
        result = _make_system_prompt()
        self.assertIn("merged", result)

    def test_hook_phase_uses_scripts_dir(self) -> None:
        """Hook phase commands should reference the scripts_dir."""
        result = _make_system_prompt(scripts_dir="/custom/scripts")
        # The hook manager command should use the scripts_dir
        self.assertIn("hook_manager.py", result)

    def test_hook_phase_uses_pipeline_id(self) -> None:
        """Hook phase commands should reference the pipeline_id."""
        result = _make_system_prompt(pipeline_id="my-pipeline-999")
        self.assertIn("my-pipeline-999", result)

    def test_contains_merge_queue_integration_section(self) -> None:
        """System prompt must contain Merge Queue Integration section."""
        result = _make_system_prompt()
        self.assertIn("Merge Queue Integration", result)

    def test_merge_queue_contains_process_next(self) -> None:
        """Merge Queue section must reference process_next function."""
        result = _make_system_prompt()
        self.assertIn("process_next", result)

    def test_merge_queue_contains_write_signal(self) -> None:
        """Merge Queue section must reference write_signal function."""
        result = _make_system_prompt()
        self.assertIn("write_signal", result)

    def test_merge_queue_contains_merge_complete(self) -> None:
        """Merge Queue section must include MERGE_COMPLETE signal."""
        result = _make_system_prompt()
        self.assertIn("MERGE_COMPLETE", result)

    def test_merge_queue_contains_merge_failed(self) -> None:
        """Merge Queue section must include MERGE_FAILED signal."""
        result = _make_system_prompt()
        self.assertIn("MERGE_FAILED", result)

    def test_merge_queue_uses_scripts_dir(self) -> None:
        """Merge Queue python3 invocation should reference the scripts_dir."""
        result = _make_system_prompt(scripts_dir="/scripts/path")
        self.assertIn("/scripts/path", result)

    def test_hook_phase_section_before_identity_scanning(self) -> None:
        """Hook Phase Tracking section should appear before Identity Scanning section."""
        result = _make_system_prompt()
        hook_pos = result.find("Hook Phase Tracking")
        identity_pos = result.find("Identity Scanning")
        self.assertGreater(hook_pos, 0, "Hook Phase Tracking section not found")
        self.assertGreater(identity_pos, 0, "Identity Scanning section not found")
        self.assertLess(hook_pos, identity_pos,
                        "Hook Phase Tracking should appear before Identity Scanning")


if __name__ == "__main__":
    unittest.main(verbosity=2)
