"""Unit tests for guardian.py — Layer 0 Terminal-to-Guardian Bridge.

Tests:
    TestParseArgs                    - parse_args() with various CLI combinations
    TestBuildSystemPrompt            - build_system_prompt() delegates to guardian_agent
    TestBuildInitialPrompt           - build_initial_prompt() delegates to guardian_agent
    TestBuildEnvConfig               - build_env_config() returns {"CLAUDECODE": ""}
    TestResolveScriptsDir            - resolve_scripts_dir() returns valid path
    TestLaunchGuardianDryRun         - guardian() dry_run mode (no SDK call)
    TestLaunchMultipleGuardians      - launch_multiple_guardians() parallel launch (mocked)
    TestMonitorGuardian              - monitor_guardian() signal detection (mocked)
    TestHandleEscalation             - handle_escalation() payload formatting
    TestHandlePipelineComplete       - handle_pipeline_complete() completion summary
    TestCLIIntegrationDryRun         - CLI --dry-run mode output
    TestCLIMultiMode                 - CLI --multi mode output
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure the attractor package root is on sys.path (mirrors conftest.py).

import cobuilder.engine.guardian as guardian  # noqa: E402
from cobuilder.engine.guardian import (  # noqa: E402
    build_env_config,
    build_initial_prompt,
    build_system_prompt,
    handle_escalation,
    handle_pipeline_complete,
    handle_validation_complete,
    monitor_guardian,
    parse_args,
    resolve_scripts_dir,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TURNS,
    DEFAULT_MODEL,
    DEFAULT_MONITOR_TIMEOUT,
    DEFAULT_SIGNAL_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DOT_PATH = "/path/to/pipeline.dot"
_PIPELINE_ID = "my-pipeline-001"
_PROJECT_ROOT = "/path/to/project"
_SCRIPTS_DIR = "/path/to/scripts"


def _make_escalation_signal(**overrides) -> dict:
    """Return a minimal valid escalation signal dict."""
    base = {
        "source": "guardian",
        "target": "terminal",
        "signal_type": "ESCALATE",
        "timestamp": "20260224T120000Z",
        "payload": {
            "pipeline_id": _PIPELINE_ID,
            "issue": "Human review needed for node impl_auth",
            "options": ["retry", "skip"],
        },
    }
    base.update(overrides)
    return base


def _make_complete_signal(**overrides) -> dict:
    """Return a minimal valid PIPELINE_COMPLETE signal dict."""
    base = {
        "source": "guardian",
        "target": "terminal",
        "signal_type": "PIPELINE_COMPLETE",
        "timestamp": "20260224T130000Z",
        "payload": {
            "pipeline_id": _PIPELINE_ID,
            "issue": "PIPELINE_COMPLETE: all nodes validated",
            "node_statuses": {
                "impl_auth": "validated",
                "impl_payments": "validated",
            },
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# TestParseArgs
# ---------------------------------------------------------------------------


class TestParseArgs(unittest.TestCase):
    """Tests for parse_args()."""

    def test_dot_and_pipeline_id_required(self) -> None:
        args = parse_args(["--dot", "/some/pipeline.dot", "--pipeline-id", "pipe-001"])
        self.assertEqual(args.dot, "/some/pipeline.dot")
        self.assertEqual(args.pipeline_id, "pipe-001")

    def test_defaults_with_dot(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1"])
        self.assertEqual(args.max_turns, DEFAULT_MAX_TURNS)
        self.assertEqual(args.signal_timeout, DEFAULT_SIGNAL_TIMEOUT)
        self.assertEqual(args.max_retries, DEFAULT_MAX_RETRIES)
        self.assertEqual(args.model, DEFAULT_MODEL)
        self.assertIsNone(args.project_root)
        self.assertIsNone(args.signals_dir)
        self.assertFalse(args.dry_run)

    def test_full_single_args(self) -> None:
        args = parse_args([
            "--dot", "/tmp/pipeline.dot",
            "--pipeline-id", "PRD-PIPE-007",
            "--project-root", "/tmp/project",
            "--max-turns", "300",
            "--model", "claude-opus-4-6",
            "--signals-dir", "/tmp/signals",
            "--signal-timeout", "300.5",
            "--max-retries", "5",
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

    def test_missing_dot_and_multi_exits(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--pipeline-id", "p1"])

    def test_dot_without_pipeline_id_exits(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--dot", "/p.dot"])

    def test_missing_all_required_exits(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_multi_flag_accepted(self) -> None:
        args = parse_args(["--multi", "/tmp/configs.json"])
        self.assertEqual(args.multi, "/tmp/configs.json")
        self.assertIsNone(args.dot)

    def test_dot_and_multi_mutually_exclusive(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--dot", "/p.dot", "--pipeline-id", "p1", "--multi", "/cfg.json"])

    def test_max_turns_type(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1", "--max-turns", "150"])
        self.assertIsInstance(args.max_turns, int)
        self.assertEqual(args.max_turns, 150)

    def test_signal_timeout_type(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1", "--signal-timeout", "120.0"])
        self.assertIsInstance(args.signal_timeout, float)
        self.assertEqual(args.signal_timeout, 120.0)

    def test_max_retries_type(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1", "--max-retries", "7"])
        self.assertIsInstance(args.max_retries, int)
        self.assertEqual(args.max_retries, 7)

    def test_dry_run_default_false(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1"])
        self.assertFalse(args.dry_run)

    def test_dry_run_flag_true(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_project_root_optional(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1",
                           "--project-root", "/my/root"])
        self.assertEqual(args.project_root, "/my/root")

    def test_signals_dir_optional(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1",
                           "--signals-dir", "/my/signals"])
        self.assertEqual(args.signals_dir, "/my/signals")

    def test_default_max_turns_is_200(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1"])
        self.assertEqual(args.max_turns, 200)

    def test_default_signal_timeout_is_600(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1"])
        self.assertEqual(args.signal_timeout, 600.0)

    def test_default_max_retries_is_3(self) -> None:
        args = parse_args(["--dot", "/p.dot", "--pipeline-id", "p1"])
        self.assertEqual(args.max_retries, 3)


# ---------------------------------------------------------------------------
# TestBuildSystemPrompt
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt(unittest.TestCase):
    """Tests for build_system_prompt() — delegates to guardian_agent."""

    def test_returns_string(self) -> None:
        result = build_system_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        self.assertIsInstance(result, str)

    def test_contains_dot_path(self) -> None:
        result = build_system_prompt(
            dot_path="/custom/my_pipeline.dot",
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        self.assertIn("/custom/my_pipeline.dot", result)

    def test_contains_pipeline_id(self) -> None:
        result = build_system_prompt(
            dot_path=_DOT_PATH,
            pipeline_id="PRD-FEAT-042",
            scripts_dir=_SCRIPTS_DIR,
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        self.assertIn("PRD-FEAT-042", result)

    def test_contains_scripts_dir(self) -> None:
        result = build_system_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir="/custom/scripts",
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        self.assertIn("/custom/scripts", result)

    def test_substantial_length(self) -> None:
        result = build_system_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        self.assertGreater(len(result), 1000)

    def test_contains_layer_1_description(self) -> None:
        result = build_system_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        self.assertIn("Layer 1", result)

    def test_matches_guardian_agent_output(self) -> None:
        """build_system_prompt is in merged guardian module."""
        import cobuilder.engine.guardian as guardian

        expected = guardian.build_system_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        actual = build_system_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
            signal_timeout=DEFAULT_SIGNAL_TIMEOUT,
            max_retries=DEFAULT_MAX_RETRIES,
        )
        self.assertEqual(actual, expected)


# ---------------------------------------------------------------------------
# TestBuildInitialPrompt
# ---------------------------------------------------------------------------


class TestBuildInitialPrompt(unittest.TestCase):
    """Tests for build_initial_prompt() — delegates to guardian_agent."""

    def test_returns_string(self) -> None:
        result = build_initial_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
        )
        self.assertIsInstance(result, str)

    def test_contains_dot_path(self) -> None:
        result = build_initial_prompt(
            dot_path="/custom/pipe.dot",
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
        )
        self.assertIn("/custom/pipe.dot", result)

    def test_contains_pipeline_id(self) -> None:
        result = build_initial_prompt(
            dot_path=_DOT_PATH,
            pipeline_id="PRD-PIPE-999",
            scripts_dir=_SCRIPTS_DIR,
        )
        self.assertIn("PRD-PIPE-999", result)

    def test_contains_scripts_dir(self) -> None:
        result = build_initial_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir="/my/scripts",
        )
        self.assertIn("/my/scripts", result)

    def test_reasonable_length(self) -> None:
        result = build_initial_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
        )
        self.assertGreater(len(result), 50)
        self.assertLess(len(result), 5000)

    def test_matches_guardian_agent_output(self) -> None:
        """build_initial_prompt is in merged guardian module."""
        import cobuilder.engine.guardian as guardian

        expected = guardian.build_initial_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
        )
        actual = build_initial_prompt(
            dot_path=_DOT_PATH,
            pipeline_id=_PIPELINE_ID,
            scripts_dir=_SCRIPTS_DIR,
        )
        self.assertEqual(actual, expected)


# ---------------------------------------------------------------------------
# TestBuildEnvConfig
# ---------------------------------------------------------------------------


class TestBuildEnvConfig(unittest.TestCase):
    """Tests for build_env_config()."""

    def test_returns_dict(self) -> None:
        result = build_env_config()
        self.assertIsInstance(result, dict)

    def test_claudecode_stripped(self) -> None:
        """Epic 4: CLAUDECODE is stripped from the environment."""
        result = build_env_config()
        self.assertNotIn("CLAUDECODE", result)

    def test_claude_session_id_stripped(self) -> None:
        """Epic 4: CLAUDE_SESSION_ID is stripped from the environment."""
        result = build_env_config()
        self.assertNotIn("CLAUDE_SESSION_ID", result)

    def test_claude_output_style_stripped(self) -> None:
        """Epic 4: CLAUDE_OUTPUT_STYLE is stripped from the environment."""
        result = build_env_config()
        self.assertNotIn("CLAUDE_OUTPUT_STYLE", result)

    def test_sets_pipeline_vars_when_provided(self) -> None:
        """Epic 4: PIPELINE_SIGNAL_DIR and PROJECT_TARGET_DIR are set when provided."""
        result = build_env_config(signals_dir="/my/signals", target_dir="/my/target")
        self.assertEqual(result["PIPELINE_SIGNAL_DIR"], "/my/signals")
        self.assertEqual(result["PROJECT_TARGET_DIR"], "/my/target")


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

    def test_contains_launch_guardian_itself(self) -> None:
        result = resolve_scripts_dir()
        self.assertTrue(
            os.path.exists(os.path.join(result, "guardian.py")),
            f"cobuilder.engine.guardian.py not found in {result}",
        )

    def test_contains_guardian_agent(self) -> None:
        result = resolve_scripts_dir()
        self.assertTrue(
            os.path.exists(os.path.join(result, "guardian.py")),
            f"cobuilder.engine.guardian.py not found in {result}",
        )

    def test_contains_signal_protocol(self) -> None:
        result = resolve_scripts_dir()
        self.assertTrue(
            os.path.exists(os.path.join(result, "signal_protocol.py")),
            f"cobuilder.engine.signal_protocol.py not found in {result}",
        )

    def test_consistent_across_calls(self) -> None:
        result1 = resolve_scripts_dir()
        result2 = resolve_scripts_dir()
        self.assertEqual(result1, result2)


# ---------------------------------------------------------------------------
# TestLaunchGuardianDryRun
# ---------------------------------------------------------------------------


class TestLaunchGuardianDryRun(unittest.TestCase):
    """Tests for guardian() in dry_run mode (no SDK invocation)."""

    def _call_dry(self, **kwargs) -> dict:
        return guardian.launch_guardian(
            dot_path="/tmp/pipeline.dot",
            project_root="/tmp/project",
            pipeline_id="test-pipe-001",
            dry_run=True,
            **kwargs,
        )

    def test_returns_dict(self) -> None:
        result = self._call_dry()
        self.assertIsInstance(result, dict)

    def test_dry_run_true_in_result(self) -> None:
        result = self._call_dry()
        self.assertTrue(result["dry_run"])

    def test_dot_path_in_result(self) -> None:
        result = self._call_dry()
        self.assertIn("dot_path", result)
        self.assertTrue(os.path.isabs(result["dot_path"]))

    def test_pipeline_id_in_result(self) -> None:
        result = self._call_dry()
        self.assertEqual(result["pipeline_id"], "test-pipe-001")

    def test_model_in_result(self) -> None:
        result = self._call_dry()
        self.assertIn("model", result)
        self.assertEqual(result["model"], DEFAULT_MODEL)

    def test_max_turns_in_result(self) -> None:
        result = self._call_dry()
        self.assertIn("max_turns", result)
        self.assertEqual(result["max_turns"], DEFAULT_MAX_TURNS)

    def test_signal_timeout_in_result(self) -> None:
        result = self._call_dry()
        self.assertIn("signal_timeout", result)
        self.assertEqual(result["signal_timeout"], DEFAULT_SIGNAL_TIMEOUT)

    def test_max_retries_in_result(self) -> None:
        result = self._call_dry()
        self.assertIn("max_retries", result)
        self.assertEqual(result["max_retries"], DEFAULT_MAX_RETRIES)

    def test_project_root_in_result(self) -> None:
        result = self._call_dry()
        self.assertEqual(result["project_root"], "/tmp/project")

    def test_scripts_dir_in_result(self) -> None:
        result = self._call_dry()
        self.assertIn("scripts_dir", result)
        self.assertTrue(os.path.isabs(result["scripts_dir"]))

    def test_system_prompt_length_positive(self) -> None:
        result = self._call_dry()
        self.assertIn("system_prompt_length", result)
        self.assertGreater(result["system_prompt_length"], 0)

    def test_initial_prompt_length_positive(self) -> None:
        result = self._call_dry()
        self.assertIn("initial_prompt_length", result)
        self.assertGreater(result["initial_prompt_length"], 0)

    def test_custom_model_respected(self) -> None:
        result = self._call_dry(model="claude-opus-4-6")
        self.assertEqual(result["model"], "claude-opus-4-6")

    def test_custom_max_turns_respected(self) -> None:
        result = self._call_dry(max_turns=50)
        self.assertEqual(result["max_turns"], 50)

    def test_does_not_call_run_agent(self) -> None:
        """dry_run must never invoke _run_agent()."""
        with patch("cobuilder.engine.guardian._run_agent") as mock_run:
            self._call_dry()
            mock_run.assert_not_called()

    def test_signals_dir_optional_none(self) -> None:
        result = self._call_dry()
        self.assertIn("signals_dir", result)

    def test_signals_dir_custom(self) -> None:
        result = self._call_dry(signals_dir="/tmp/custom_signals")
        self.assertEqual(result["signals_dir"], "/tmp/custom_signals")


# ---------------------------------------------------------------------------
# TestLaunchMultipleGuardians
# ---------------------------------------------------------------------------


class TestLaunchMultipleGuardians(unittest.TestCase):
    """Tests for launch_multiple_guardians() with mocked SDK."""

    def _make_cfg(self, pipeline_id: str = "pipe-1", **kwargs) -> dict:
        return {
            "dot_path": "/tmp/pipeline.dot",
            "project_root": "/tmp/project",
            "pipeline_id": pipeline_id,
            "dry_run": True,
            **kwargs,
        }

    def test_empty_configs_returns_empty_list(self) -> None:
        result = guardian.launch_multiple_guardians([])
        self.assertEqual(result, [])

    def test_single_config_returns_single_result(self) -> None:
        results = guardian.launch_multiple_guardians([self._make_cfg()])
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)

    def test_multiple_configs_returns_multiple_results(self) -> None:
        configs = [
            self._make_cfg("pipe-1"),
            self._make_cfg("pipe-2"),
            self._make_cfg("pipe-3"),
        ]
        results = guardian.launch_multiple_guardians(configs)
        self.assertEqual(len(results), 3)

    def test_each_result_has_pipeline_id(self) -> None:
        configs = [self._make_cfg("pipe-A"), self._make_cfg("pipe-B")]
        results = guardian.launch_multiple_guardians(configs)
        pipeline_ids = {r["pipeline_id"] for r in results}
        self.assertIn("pipe-A", pipeline_ids)
        self.assertIn("pipe-B", pipeline_ids)

    def test_dry_run_results_have_dry_run_true(self) -> None:
        results = guardian.launch_multiple_guardians([self._make_cfg()])
        self.assertTrue(results[0]["dry_run"])

    def test_individual_failure_does_not_stop_others(self) -> None:
        """An exception in one task should not prevent others from completing."""
        import asyncio

        async def fake_launch(**kwargs):
            pipeline_id = kwargs.get("pipeline_id", "")
            if pipeline_id == "bad-pipe":
                raise RuntimeError("Simulated failure")
            return {"status": "ok", "pipeline_id": pipeline_id, "dot_path": ""}

        configs = [
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "good-pipe", "dry_run": False},
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "bad-pipe", "dry_run": False},
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "another-good", "dry_run": False},
        ]

        with patch("cobuilder.engine.guardian._launch_guardian_async", side_effect=fake_launch):
            results = guardian.launch_multiple_guardians(configs)

        self.assertEqual(len(results), 3)

        statuses = {r["pipeline_id"]: r["status"] for r in results}
        self.assertEqual(statuses["good-pipe"], "ok")
        self.assertEqual(statuses["bad-pipe"], "error")
        self.assertEqual(statuses["another-good"], "ok")

    def test_failed_result_has_error_key(self) -> None:
        async def always_fail(**kwargs):
            raise RuntimeError("always fails")

        configs = [{"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "fail-pipe"}]
        with patch("cobuilder.engine.guardian._launch_guardian_async", side_effect=always_fail):
            results = guardian.launch_multiple_guardians(configs)

        self.assertEqual(results[0]["status"], "error")
        self.assertIn("error", results[0])

    def test_results_are_list_of_dicts(self) -> None:
        configs = [self._make_cfg("p1"), self._make_cfg("p2")]
        results = guardian.launch_multiple_guardians(configs)
        for r in results:
            self.assertIsInstance(r, dict)


# ---------------------------------------------------------------------------
# TestMonitorGuardian
# ---------------------------------------------------------------------------


class TestMonitorGuardian(unittest.TestCase):
    """Tests for monitor_guardian() with mocked signal_protocol."""

    def _call_monitor(self, signal_data=None, timeout_error=False, **kwargs) -> dict:
        def mock_wait_for_signal(**wait_kwargs):
            if timeout_error:
                raise TimeoutError("No signal within 1s")
            return signal_data

        with patch("cobuilder.engine.guardian.wait_for_signal", mock_wait_for_signal):
            return monitor_guardian(
                guardian_process=None,
                dot_path="/tmp/pipeline.dot",
                **kwargs,
            )

    def test_pipeline_complete_signal_returns_complete_status(self) -> None:
        signal = _make_complete_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertEqual(result["status"], "complete")

    def test_escalation_signal_returns_escalation_status(self) -> None:
        signal = _make_escalation_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertEqual(result["status"], "escalation")

    def test_timeout_returns_timeout_status(self) -> None:
        result = self._call_monitor(timeout_error=True)
        self.assertEqual(result["status"], "timeout")

    def test_timeout_result_has_dot_path(self) -> None:
        result = self._call_monitor(timeout_error=True)
        self.assertEqual(result["dot_path"], "/tmp/pipeline.dot")

    def test_timeout_result_has_null_signal_data(self) -> None:
        result = self._call_monitor(timeout_error=True)
        self.assertIsNone(result["signal_data"])

    def test_complete_result_has_pipeline_id(self) -> None:
        signal = _make_complete_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertIn("pipeline_id", result)

    def test_escalation_result_has_issue(self) -> None:
        signal = _make_escalation_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertIn("issue", result)

    def test_exception_in_wait_returns_error_status(self) -> None:
        def mock_wait(**kwargs):
            raise OSError("disk error")

        with patch("cobuilder.engine.guardian.wait_for_signal", mock_wait):
            result = monitor_guardian(None, "/tmp/pipeline.dot")

        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)

    def test_issue_text_pipeline_complete_triggers_complete(self) -> None:
        """A signal with PIPELINE_COMPLETE in the issue field is treated as complete."""
        signal = {
            "source": "guardian",
            "target": "terminal",
            "signal_type": "ESCALATE",
            "timestamp": "20260224T120000Z",
            "payload": {
                "pipeline_id": "p1",
                "issue": "PIPELINE_COMPLETE: all nodes validated",
            },
        }
        result = self._call_monitor(signal_data=signal)
        self.assertEqual(result["status"], "complete")

    def test_signal_type_pipeline_complete_triggers_complete(self) -> None:
        signal = {
            "source": "guardian",
            "target": "terminal",
            "signal_type": "PIPELINE_COMPLETE",
            "timestamp": "20260224T120000Z",
            "payload": {"pipeline_id": "p2", "issue": "Done"},
        }
        result = self._call_monitor(signal_data=signal)
        self.assertEqual(result["status"], "complete")


# ---------------------------------------------------------------------------
# TestHandleEscalation
# ---------------------------------------------------------------------------


class TestHandleEscalation(unittest.TestCase):
    """Tests for handle_escalation()."""

    def test_returns_dict(self) -> None:
        result = handle_escalation(_make_escalation_signal())
        self.assertIsInstance(result, dict)

    def test_status_is_escalation(self) -> None:
        result = handle_escalation(_make_escalation_signal())
        self.assertEqual(result["status"], "escalation")

    def test_pipeline_id_extracted(self) -> None:
        result = handle_escalation(_make_escalation_signal())
        self.assertEqual(result["pipeline_id"], _PIPELINE_ID)

    def test_issue_extracted(self) -> None:
        result = handle_escalation(_make_escalation_signal())
        self.assertIn("issue", result)
        self.assertIsNotNone(result["issue"])

    def test_options_extracted(self) -> None:
        result = handle_escalation(_make_escalation_signal())
        self.assertEqual(result["options"], ["retry", "skip"])

    def test_timestamp_extracted(self) -> None:
        result = handle_escalation(_make_escalation_signal())
        self.assertEqual(result["timestamp"], "20260224T120000Z")

    def test_source_extracted(self) -> None:
        result = handle_escalation(_make_escalation_signal())
        self.assertEqual(result["source"], "guardian")

    def test_raw_signal_preserved(self) -> None:
        signal = _make_escalation_signal()
        result = handle_escalation(signal)
        self.assertEqual(result["raw"], signal)

    def test_missing_payload_fields_handled_gracefully(self) -> None:
        """handle_escalation must not raise on minimal/empty signal."""
        minimal_signal = {
            "source": "guardian",
            "target": "terminal",
            "signal_type": "ESCALATE",
            "timestamp": "20260224T120000Z",
            "payload": {},
        }
        result = handle_escalation(minimal_signal)
        self.assertEqual(result["status"], "escalation")
        self.assertEqual(result["pipeline_id"], "unknown")
        self.assertIn("issue", result)

    def test_completely_empty_signal_handled(self) -> None:
        result = handle_escalation({})
        self.assertEqual(result["status"], "escalation")

    def test_signal_type_preserved(self) -> None:
        signal = _make_escalation_signal()
        result = handle_escalation(signal)
        self.assertEqual(result["signal_type"], "ESCALATE")

    def test_options_none_when_absent(self) -> None:
        signal = _make_escalation_signal()
        signal["payload"].pop("options", None)
        result = handle_escalation(signal)
        self.assertIsNone(result["options"])


# ---------------------------------------------------------------------------
# TestHandlePipelineComplete
# ---------------------------------------------------------------------------


class TestHandlePipelineComplete(unittest.TestCase):
    """Tests for handle_pipeline_complete()."""

    def test_returns_dict(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertIsInstance(result, dict)

    def test_status_is_complete(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertEqual(result["status"], "complete")

    def test_pipeline_id_extracted(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertEqual(result["pipeline_id"], _PIPELINE_ID)

    def test_dot_path_in_result(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertEqual(result["dot_path"], _DOT_PATH)

    def test_node_statuses_extracted(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertIn("node_statuses", result)
        ns = result["node_statuses"]
        self.assertEqual(ns.get("impl_auth"), "validated")
        self.assertEqual(ns.get("impl_payments"), "validated")

    def test_timestamp_in_result(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertEqual(result["timestamp"], "20260224T130000Z")

    def test_source_in_result(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertEqual(result["source"], "guardian")

    def test_raw_signal_preserved(self) -> None:
        signal = _make_complete_signal()
        result = handle_pipeline_complete(signal, _DOT_PATH)
        self.assertEqual(result["raw"], signal)

    def test_issue_in_result(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), _DOT_PATH)
        self.assertIn("issue", result)
        self.assertIn("PIPELINE_COMPLETE", result["issue"])

    def test_missing_node_statuses_falls_back_to_issue(self) -> None:
        """When no node_statuses in payload, derive from issue string."""
        signal = {
            "source": "guardian",
            "target": "terminal",
            "signal_type": "PIPELINE_COMPLETE",
            "timestamp": "20260224T140000Z",
            "payload": {
                "pipeline_id": "p3",
                "issue": "PIPELINE_COMPLETE: all nodes validated",
            },
        }
        result = handle_pipeline_complete(signal, "/tmp/p.dot")
        self.assertIn("node_statuses", result)
        # Fallback sets a "summary" key with the issue text
        self.assertIn("summary", result["node_statuses"])

    def test_completely_empty_signal_handled(self) -> None:
        result = handle_pipeline_complete({}, "/tmp/p.dot")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["pipeline_id"], "unknown")

    def test_custom_dot_path(self) -> None:
        result = handle_pipeline_complete(_make_complete_signal(), "/custom/path.dot")
        self.assertEqual(result["dot_path"], "/custom/path.dot")


# ---------------------------------------------------------------------------
# TestCLIIntegrationDryRun
# ---------------------------------------------------------------------------


class TestCLIIntegrationDryRun(unittest.TestCase):
    """Integration tests for CLI --dry-run mode."""

    def _run_dry(self, extra_args: list[str] | None = None) -> str:
        """Run main() in dry-run mode and capture stdout."""
        base_args = [
            "--dot", "/tmp/pipe.dot",
            "--pipeline-id", "test-pipe-001",
            "--target-dir", "/tmp",
            "--dry-run",
        ]
        if extra_args:
            base_args.extend(extra_args)

        buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            with redirect_stdout(buf):
                guardian.main(base_args)

        self.assertEqual(cm.exception.code, 0)
        return buf.getvalue()

    def test_dry_run_exits_zero(self) -> None:
        self._run_dry()  # assertion is inside _run_dry

    def test_dry_run_prints_valid_json(self) -> None:
        output = self._run_dry()
        data = json.loads(output)
        self.assertIsInstance(data, dict)

    def test_dry_run_has_dry_run_true(self) -> None:
        data = json.loads(self._run_dry())
        self.assertTrue(data["dry_run"])

    def test_dry_run_has_pipeline_id(self) -> None:
        data = json.loads(self._run_dry())
        self.assertEqual(data["pipeline_id"], "test-pipe-001")

    def test_dry_run_has_dot_path(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("dot_path", data)
        self.assertTrue(os.path.isabs(data["dot_path"]))

    def test_dry_run_has_model(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("model", data)
        self.assertEqual(data["model"], DEFAULT_MODEL)

    def test_dry_run_has_max_turns(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("max_turns", data)
        self.assertEqual(data["max_turns"], DEFAULT_MAX_TURNS)

    def test_dry_run_has_signal_timeout(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("signal_timeout", data)
        self.assertEqual(data["signal_timeout"], DEFAULT_SIGNAL_TIMEOUT)

    def test_dry_run_has_max_retries(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("max_retries", data)
        self.assertEqual(data["max_retries"], DEFAULT_MAX_RETRIES)

    def test_dry_run_has_scripts_dir(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("scripts_dir", data)
        self.assertTrue(os.path.isabs(data["scripts_dir"]))

    def test_dry_run_has_prompt_lengths(self) -> None:
        data = json.loads(self._run_dry())
        self.assertIn("system_prompt_length", data)
        self.assertIn("initial_prompt_length", data)
        self.assertGreater(data["system_prompt_length"], 0)
        self.assertGreater(data["initial_prompt_length"], 0)

    def test_dry_run_does_not_call_run_agent(self) -> None:
        """Dry-run must never invoke the SDK _run_agent()."""
        with patch("cobuilder.engine.guardian._run_agent") as mock_run:
            buf = io.StringIO()
            with self.assertRaises(SystemExit):
                with redirect_stdout(buf):
                    guardian.main([
                        "--dot", "/tmp/p.dot",
                        "--pipeline-id", "p",
                        "--target-dir", "/tmp",
                        "--dry-run",
                    ])
            mock_run.assert_not_called()

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


# ---------------------------------------------------------------------------
# TestCLIMultiMode
# ---------------------------------------------------------------------------


class TestCLIMultiMode(unittest.TestCase):
    """Tests for CLI --multi mode with JSON config files."""

    def _write_configs(self, configs: list[dict]) -> str:
        """Write configs to a temp file and return path."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump(configs, fh)
            return fh.name

    def _run_multi(self, configs: list[dict], extra_args: list[str] | None = None) -> str:
        cfg_path = self._write_configs(configs)
        try:
            args = ["--multi", cfg_path]
            if extra_args:
                args.extend(extra_args)

            buf = io.StringIO()
            with redirect_stdout(buf):
                guardian.main(args)
            return buf.getvalue()
        finally:
            os.unlink(cfg_path)

    def test_multi_returns_list_json(self) -> None:
        configs = [
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "p1", "dry_run": True},
        ]
        output = self._run_multi(configs)
        data = json.loads(output)
        self.assertIsInstance(data, list)

    def test_multi_result_count_matches_config_count(self) -> None:
        configs = [
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "p1", "dry_run": True},
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "p2", "dry_run": True},
        ]
        output = self._run_multi(configs)
        data = json.loads(output)
        self.assertEqual(len(data), 2)

    def test_multi_dry_run_flag_propagated(self) -> None:
        """--dry-run on CLI should propagate to all configs."""
        configs = [
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "p1"},
        ]
        cfg_path = self._write_configs(configs)
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                guardian.main(["--multi", cfg_path, "--dry-run"])
            data = json.loads(buf.getvalue())
            self.assertTrue(data[0]["dry_run"])
        finally:
            os.unlink(cfg_path)

    def test_multi_missing_file_exits_nonzero(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            guardian.main(["--multi", "/nonexistent/path.json"])
        self.assertNotEqual(cm.exception.code, 0)

    def test_multi_invalid_json_exits_nonzero(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            fh.write("not valid json {{{{")
            bad_path = fh.name
        try:
            with self.assertRaises(SystemExit) as cm:
                guardian.main(["--multi", bad_path])
            self.assertNotEqual(cm.exception.code, 0)
        finally:
            os.unlink(bad_path)

    def test_multi_non_list_json_exits_nonzero(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump({"not": "a list"}, fh)
            bad_path = fh.name
        try:
            with self.assertRaises(SystemExit) as cm:
                guardian.main(["--multi", bad_path])
            self.assertNotEqual(cm.exception.code, 0)
        finally:
            os.unlink(bad_path)

    def test_multi_each_result_has_pipeline_id(self) -> None:
        configs = [
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "alpha", "dry_run": True},
            {"dot_path": "/tmp/p.dot", "project_root": "/tmp", "pipeline_id": "beta", "dry_run": True},
        ]
        output = self._run_multi(configs)
        data = json.loads(output)
        pipeline_ids = {r["pipeline_id"] for r in data}
        self.assertIn("alpha", pipeline_ids)
        self.assertIn("beta", pipeline_ids)


# ---------------------------------------------------------------------------
# TestHandleValidationComplete (AC-4)
# ---------------------------------------------------------------------------


def _make_validation_complete_signal(**overrides) -> dict:
    """Return a minimal valid VALIDATION_COMPLETE signal dict from a Runner."""
    base = {
        "source": "runner",
        "target": "terminal",
        "signal_type": "VALIDATION_COMPLETE",
        "timestamp": "20260224T140000Z",
        "payload": {
            "node_id": "impl_auth",
            "pipeline_id": _PIPELINE_ID,
            "summary": "Node impl_auth validated",
        },
    }
    base.update(overrides)
    return base


class TestHandleValidationComplete(unittest.TestCase):
    """Tests for handle_validation_complete() — AC-4."""

    def test_returns_dict(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertIsInstance(result, dict)

    def test_status_is_validation_complete(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertEqual(result["status"], "validation_complete")

    def test_node_id_extracted(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertEqual(result["node_id"], "impl_auth")

    def test_pipeline_id_extracted(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertEqual(result["pipeline_id"], _PIPELINE_ID)

    def test_dot_path_preserved(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertEqual(result["dot_path"], _DOT_PATH)

    def test_summary_extracted(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertEqual(result["summary"], "Node impl_auth validated")

    def test_timestamp_extracted(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertEqual(result["timestamp"], "20260224T140000Z")

    def test_source_extracted(self) -> None:
        result = handle_validation_complete(_make_validation_complete_signal(), _DOT_PATH)
        self.assertEqual(result["source"], "runner")

    def test_raw_signal_preserved(self) -> None:
        signal = _make_validation_complete_signal()
        result = handle_validation_complete(signal, _DOT_PATH)
        self.assertEqual(result["raw"], signal)

    def test_missing_node_id_defaults_to_unknown(self) -> None:
        signal = _make_validation_complete_signal()
        signal["payload"].pop("node_id", None)
        result = handle_validation_complete(signal, _DOT_PATH)
        self.assertEqual(result["node_id"], "unknown")

    def test_missing_pipeline_id_defaults_to_empty(self) -> None:
        signal = _make_validation_complete_signal()
        signal["payload"].pop("pipeline_id", None)
        result = handle_validation_complete(signal, _DOT_PATH)
        self.assertEqual(result["pipeline_id"], "")

    def test_empty_signal_handled_gracefully(self) -> None:
        result = handle_validation_complete({}, "/tmp/p.dot")
        self.assertEqual(result["status"], "validation_complete")
        self.assertEqual(result["node_id"], "unknown")

    def test_custom_dot_path(self) -> None:
        result = handle_validation_complete(
            _make_validation_complete_signal(), "/custom/pipeline.dot"
        )
        self.assertEqual(result["dot_path"], "/custom/pipeline.dot")


class TestMonitorGuardianValidationComplete(unittest.TestCase):
    """Tests for monitor_guardian() handling VALIDATION_COMPLETE signals — AC-4."""

    def _call_monitor(self, signal_data=None, **kwargs) -> dict:
        def mock_wait_for_signal(**wait_kwargs):
            return signal_data

        with patch("cobuilder.engine.guardian.wait_for_signal", mock_wait_for_signal):
            return monitor_guardian(
                guardian_process=None,
                dot_path="/tmp/pipeline.dot",
                **kwargs,
            )

    def test_validation_complete_signal_returns_validation_complete_status(self) -> None:
        """monitor_guardian must return validation_complete status for VALIDATION_COMPLETE."""
        signal = _make_validation_complete_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertEqual(result["status"], "validation_complete")

    def test_validation_complete_has_node_id(self) -> None:
        signal = _make_validation_complete_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertIn("node_id", result)
        self.assertEqual(result["node_id"], "impl_auth")

    def test_validation_complete_has_dot_path(self) -> None:
        signal = _make_validation_complete_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertEqual(result["dot_path"], "/tmp/pipeline.dot")

    def test_validation_complete_not_treated_as_escalation(self) -> None:
        """VALIDATION_COMPLETE must NOT route through handle_escalation."""
        signal = _make_validation_complete_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertNotEqual(result["status"], "escalation")

    def test_validation_complete_not_treated_as_pipeline_complete(self) -> None:
        """VALIDATION_COMPLETE must NOT route through handle_pipeline_complete."""
        signal = _make_validation_complete_signal()
        result = self._call_monitor(signal_data=signal)
        self.assertNotEqual(result["status"], "complete")


# ---------------------------------------------------------------------------
# TestIdentityRegistration (Epic 2 — Hook Manager Lifecycle Integration)
# ---------------------------------------------------------------------------


class TestIdentityRegistration(unittest.TestCase):
    """Tests that guardian.main() registers a Layer 0 identity before launching."""

    def _make_dot_file(self, tmp_dir: str) -> str:
        """Create a minimal DOT file for testing."""
        import tempfile
        dot_content = (
            'digraph pipeline {\n'
            '    graph [target_dir="/tmp/project"];\n'
            '    impl_auth [type="codergen", prd="PRD-AUTH-001"];\n'
            '}\n'
        )
        dot_path = os.path.join(tmp_dir, "pipeline.dot")
        with open(dot_path, "w") as fh:
            fh.write(dot_content)
        return dot_path

    def test_identity_registry_create_called_before_launch(self) -> None:
        """main() must call identity_registry.create_identity before launching the Guardian."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            dot_path = self._make_dot_file(tmp_dir)
            argv = [
                "--dot", dot_path,
                "--pipeline-id", "test-pipeline",
                "--target-dir", tmp_dir,
            ]
            with patch("cobuilder.engine.guardian.launch_guardian") as mock_launch, \
                 patch("cobuilder.engine.guardian.identity_registry") as mock_registry:
                mock_launch.return_value = {"status": "ok", "pipeline_id": "test-pipeline", "dot_path": dot_path}
                buf = io.StringIO()
                try:
                    with redirect_stdout(buf):
                        guardian.main(argv)
                except SystemExit:
                    pass
            mock_registry.create_identity.assert_called_once()

    def test_identity_registered_as_launch_role(self) -> None:
        """Identity must be registered with role='launch'."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            dot_path = self._make_dot_file(tmp_dir)
            argv = [
                "--dot", dot_path,
                "--pipeline-id", "test-pipeline",
                "--target-dir", tmp_dir,
            ]
            with patch("cobuilder.engine.guardian.launch_guardian") as mock_launch, \
                 patch("cobuilder.engine.guardian.identity_registry") as mock_registry:
                mock_launch.return_value = {"status": "ok", "pipeline_id": "test-pipeline", "dot_path": dot_path}
                buf = io.StringIO()
                try:
                    with redirect_stdout(buf):
                        guardian.main(argv)
                except SystemExit:
                    pass
            call_kwargs = mock_registry.create_identity.call_args
            # Check role argument (positional or keyword)
            if call_kwargs.kwargs:
                self.assertEqual(call_kwargs.kwargs.get("role"), "launch")
            else:
                self.assertEqual(call_kwargs.args[0], "launch")

    def test_identity_registered_with_guardian_name(self) -> None:
        """Identity must be registered with name='guardian'."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            dot_path = self._make_dot_file(tmp_dir)
            argv = [
                "--dot", dot_path,
                "--pipeline-id", "test-pipeline",
                "--target-dir", tmp_dir,
            ]
            with patch("cobuilder.engine.guardian.launch_guardian") as mock_launch, \
                 patch("cobuilder.engine.guardian.identity_registry") as mock_registry:
                mock_launch.return_value = {"status": "ok", "pipeline_id": "test-pipeline", "dot_path": dot_path}
                buf = io.StringIO()
                try:
                    with redirect_stdout(buf):
                        guardian.main(argv)
                except SystemExit:
                    pass
            call_kwargs = mock_registry.create_identity.call_args
            if call_kwargs.kwargs:
                self.assertEqual(call_kwargs.kwargs.get("name"), "guardian")

    def test_identity_not_registered_in_dry_run(self) -> None:
        """Dry-run mode should exit before identity registration."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            dot_path = self._make_dot_file(tmp_dir)
            argv = [
                "--dot", dot_path,
                "--pipeline-id", "test-pipeline",
                "--target-dir", tmp_dir,
                "--dry-run",
            ]
            with patch("cobuilder.engine.guardian.identity_registry") as mock_registry:
                buf = io.StringIO()
                with self.assertRaises(SystemExit):
                    with redirect_stdout(buf):
                        guardian.main(argv)
            # In dry-run, we exit before identity registration
            mock_registry.create_identity.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
