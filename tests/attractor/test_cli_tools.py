"""Integration tests for CLI tools in signal_protocol suite.

Tests run CLI scripts as subprocesses and verify JSON output.

Tests:
    TestSignalGuardianCLI       - signal_guardian.py
    TestReadSignalCLI           - read_signal.py
    TestWaitForSignalCLI        - wait_for_signal.py (timeout path)
    TestCaptureOutputCLI        - capture_output.py (error path)
    TestCheckOrchestratorCLI    - check_orchestrator_alive.py
    TestSpawnRunnerCLI          - runner.py
    TestRespondToRunnerCLI      - respond_to_runner.py
    TestEscalateToTerminalCLI   - escalate_to_terminal.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

import pytest
import cobuilder.attractor as _attractor_pkg

# Directory containing the CLI scripts
_ATTRACTOR_DIR = os.path.dirname(os.path.abspath(_attractor_pkg.__file__))
# Project root (parent of cobuilder/) for PYTHONPATH injection in subprocesses
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_ATTRACTOR_DIR))


def _run_cli(script_name: str, args: list, env_overrides: dict = None,
             timeout: int = 30) -> tuple:
    """Run a CLI script and return (returncode, stdout, stderr).

    Args:
        script_name: Filename of the script (e.g., "signal_guardian.py")
        args: List of CLI arguments
        env_overrides: Dict of environment variable overrides
        timeout: Subprocess timeout in seconds

    Returns:
        Tuple of (returncode, stdout_str, stderr_str)
    """
    script_path = os.path.join(_ATTRACTOR_DIR, script_name)
    cmd = [sys.executable, script_path] + args

    env = os.environ.copy()
    # Ensure cobuilder package is importable in subprocess
    existing_pythonpath = env.get("PYTHONPATH", "")
    if existing_pythonpath:
        env["PYTHONPATH"] = f"{_PROJECT_ROOT}{os.pathsep}{existing_pythonpath}"
    else:
        env["PYTHONPATH"] = _PROJECT_ROOT
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _parse_json_output(stdout: str) -> dict:
    """Parse JSON from stdout, raising AssertionError with context on failure."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Expected JSON output, got: {stdout!r}") from exc


# ---------------------------------------------------------------------------
# TestSignalGuardianCLI
# ---------------------------------------------------------------------------

class TestSignalGuardianCLI:
    """Tests for signal_guardian.py."""

    def test_needs_review_creates_signal(self, tmp_path):
        """signal_guardian.py NEEDS_REVIEW --node ... creates a signal file."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "impl_auth", "--evidence", "/tmp/ev"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )

        assert rc == 0, f"Expected exit 0, got {rc}. stdout={stdout}"
        data = _parse_json_output(stdout)
        assert data["status"] == "ok"
        assert data["signal_type"] == "NEEDS_REVIEW"
        assert "signal_file" in data
        assert os.path.exists(data["signal_file"])

    def test_signal_file_has_correct_content(self, tmp_path):
        """signal_guardian.py writes signal with correct source/target/payload."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "impl_auth",
             "--commit", "abc123", "--summary", "auth module complete"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        signal_path = data["signal_file"]

        with open(signal_path) as fh:
            signal = json.load(fh)

        assert signal["source"] == "runner"
        assert signal["target"] == "guardian"
        assert signal["signal_type"] == "NEEDS_REVIEW"
        assert signal["payload"]["node_id"] == "impl_auth"
        assert signal["payload"]["commit_hash"] == "abc123"
        assert signal["payload"]["summary"] == "auth module complete"

    def test_stuck_signal_type(self, tmp_path):
        """signal_guardian.py accepts STUCK signal type."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["STUCK", "--node", "impl_auth", "--reason", "cannot proceed"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc == 0
        data = _parse_json_output(stdout)
        assert data["status"] == "ok"
        assert data["signal_type"] == "STUCK"

    def test_with_options_json(self, tmp_path):
        """signal_guardian.py --options JSON is parsed and stored in payload."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "n1",
             "--options", '{"retry": true, "strategy": "A"}'],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc == 0
        data = _parse_json_output(stdout)
        with open(data["signal_file"]) as fh:
            signal = json.load(fh)
        assert signal["payload"]["options"]["retry"] is True
        assert signal["payload"]["options"]["strategy"] == "A"

    def test_invalid_options_json_exits_with_error(self, tmp_path):
        """signal_guardian.py with invalid --options JSON exits with code 1."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "n1", "--options", "not valid json"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc == 1
        data = _parse_json_output(stdout)
        assert data["status"] == "error"

    def test_missing_node_exits_with_error(self, tmp_path):
        """signal_guardian.py without --node exits with non-zero code."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, stderr = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        # argparse error: exits with code 2
        assert rc != 0

    def test_target_terminal_writes_signal_with_target_terminal(self, tmp_path):
        """AC-4: signal_guardian.py --target terminal writes signal with target=terminal."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["VALIDATION_COMPLETE", "--node", "impl_auth",
             "--summary", "Node impl_auth validated",
             "--target", "terminal"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc == 0, f"Expected exit 0, got {rc}. stdout={stdout}"
        data = _parse_json_output(stdout)
        assert data["status"] == "ok"
        assert data["signal_type"] == "VALIDATION_COMPLETE"

        # Verify the signal file has target=terminal
        with open(data["signal_file"]) as fh:
            signal = json.load(fh)
        assert signal["target"] == "terminal"
        assert signal["source"] == "runner"
        assert signal["signal_type"] == "VALIDATION_COMPLETE"

    def test_target_guardian_is_default(self, tmp_path):
        """AC-4: signal_guardian.py without --target defaults to target=guardian."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "impl_auth"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc == 0
        data = _parse_json_output(stdout)

        with open(data["signal_file"]) as fh:
            signal = json.load(fh)
        assert signal["target"] == "guardian"

    def test_target_invalid_choice_exits_with_error(self, tmp_path):
        """signal_guardian.py --target invalid rejects with non-zero exit."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, stderr = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "impl_auth", "--target", "invalid_target"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc != 0

    def test_target_guardian_explicit_writes_to_guardian(self, tmp_path):
        """AC-4: Explicitly passing --target guardian writes signal with target=guardian."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "impl_auth", "--target", "guardian"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc == 0
        data = _parse_json_output(stdout)

        with open(data["signal_file"]) as fh:
            signal = json.load(fh)
        assert signal["target"] == "guardian"


# ---------------------------------------------------------------------------
# TestReadSignalCLI
# ---------------------------------------------------------------------------

class TestReadSignalCLI:
    """Tests for read_signal.py."""

    def test_reads_valid_signal_file(self, tmp_path):
        """read_signal.py <path> returns the signal JSON."""
        signals_dir = str(tmp_path / "signals")

        # First create a signal file via signal_guardian.py
        _, create_stdout, _ = _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "impl_auth"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        signal_path = _parse_json_output(create_stdout)["signal_file"]

        # Now read it
        rc, stdout, _ = _run_cli("read_signal.py", [signal_path])

        assert rc == 0, f"Expected exit 0, stdout={stdout}"
        data = _parse_json_output(stdout)
        assert data["source"] == "runner"
        assert data["target"] == "guardian"
        assert data["signal_type"] == "NEEDS_REVIEW"

    def test_nonexistent_file_exits_with_error(self, tmp_path):
        """read_signal.py with nonexistent path exits with code 1 and JSON error."""
        nonexistent = str(tmp_path / "ghost.json")
        rc, stdout, _ = _run_cli("read_signal.py", [nonexistent])

        assert rc == 1
        data = _parse_json_output(stdout)
        assert data["status"] == "error"

    def test_invalid_json_file_exits_with_error(self, tmp_path):
        """read_signal.py with invalid JSON file exits with code 1."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json", encoding="utf-8")

        rc, stdout, _ = _run_cli("read_signal.py", [str(bad_file)])

        assert rc == 1
        data = _parse_json_output(stdout)
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# TestWaitForSignalCLI
# ---------------------------------------------------------------------------

class TestWaitForSignalCLI:
    """Tests for wait_for_signal.py."""

    def test_timeout_produces_json_error(self, tmp_path):
        """wait_for_signal.py --timeout 0.1 produces JSON error on timeout."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "wait_for_signal.py",
            ["--target", "guardian", "--timeout", "0.1", "--poll", "0.05"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
            timeout=10,
        )

        assert rc == 1
        data = _parse_json_output(stdout)
        assert data["status"] == "error"
        assert "timeout" in data["message"].lower() or "signal" in data["message"].lower()

    def test_returns_signal_when_present(self, tmp_path):
        """wait_for_signal.py returns signal JSON when signal exists."""
        signals_dir = str(tmp_path / "signals")

        # Pre-create a signal
        _run_cli(
            "signal_guardian.py",
            ["NEEDS_REVIEW", "--node", "impl_auth"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )

        rc, stdout, _ = _run_cli(
            "wait_for_signal.py",
            ["--target", "guardian", "--timeout", "5.0", "--poll", "0.1"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
            timeout=15,
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        assert data["target"] == "guardian"
        assert data["signal_type"] == "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# TestCaptureOutputCLI
# ---------------------------------------------------------------------------

class TestCaptureOutputCLI:
    """Tests for capture_output.py."""

    def test_nonexistent_session_exits_with_error(self):
        """capture_output.py with nonexistent session produces JSON error."""
        rc, stdout, _ = _run_cli(
            "capture_output.py",
            ["--session", "nonexistent-session-xyz-12345"],
        )

        # Should exit with error code
        assert rc == 1
        data = _parse_json_output(stdout)
        assert data["status"] == "error"
        assert "message" in data

    def test_help_flag_works(self):
        """capture_output.py --help exits with code 0."""
        rc, stdout, _ = _run_cli("capture_output.py", ["--help"])
        # argparse help exits with 0
        assert rc == 0


# ---------------------------------------------------------------------------
# TestCheckOrchestratorCLI
# ---------------------------------------------------------------------------

class TestCheckOrchestratorCLI:
    """Tests for check_orchestrator_alive.py."""

    def test_nonexistent_session_returns_alive_false(self):
        """check_orchestrator_alive.py returns alive=false for nonexistent session."""
        rc, stdout, _ = _run_cli(
            "check_orchestrator_alive.py",
            ["--session", "nonexistent-session-xyz-12345"],
        )

        assert rc == 0, f"Expected exit 0, stdout={stdout}"
        data = _parse_json_output(stdout)
        assert data["alive"] is False
        assert data["session"] == "nonexistent-session-xyz-12345"

    def test_output_includes_session_name(self):
        """check_orchestrator_alive.py always includes session name in output."""
        session_name = "test-orch-99999"
        rc, stdout, _ = _run_cli(
            "check_orchestrator_alive.py",
            ["--session", session_name],
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        assert data["session"] == session_name

    def test_help_flag_works(self):
        """check_orchestrator_alive.py --help exits with code 0."""
        rc, stdout, _ = _run_cli("check_orchestrator_alive.py", ["--help"])
        assert rc == 0


# ---------------------------------------------------------------------------
# TestSpawnRunnerCLI
# ---------------------------------------------------------------------------

class TestSpawnRunnerCLI:
    """Tests for runner.py."""

    def test_basic_invocation_succeeds(self, tmp_path):
        """cobuilder.attractor.session_runner.py --node ... --prd ... outputs valid JSON."""
        # Use a custom git root to avoid writing to real repo
        rc, stdout, _ = _run_cli(
            "session_runner.py",
            ["--spawn", "--node", "impl_auth", "--prd", "PRD-TEST-001",
             "--target-dir", str(tmp_path)],
            env_overrides={
                "ATTRACTOR_SIGNALS_DIR": str(tmp_path / "signals"),
            },
        )

        assert rc == 0, f"Expected exit 0, stdout={stdout}"
        data = _parse_json_output(stdout)
        assert data["status"] == "ok"
        assert data["node"] == "impl_auth"
        assert data["prd"] == "PRD-TEST-001"

    def test_runner_config_in_output(self, tmp_path):
        """cobuilder.attractor.session_runner.py includes runner_config in output."""
        rc, stdout, _ = _run_cli(
            "session_runner.py",
            ["--spawn", "--node", "impl_auth", "--prd", "PRD-TEST-001",
             "--target-dir", str(tmp_path),
             "--solution-design", "/tmp/design.md",
             "--bead-id", "BEAD-42"],
            env_overrides={
                "ATTRACTOR_SIGNALS_DIR": str(tmp_path / "signals"),
            },
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        assert "runner_config" in data
        cfg = data["runner_config"]
        assert cfg["node_id"] == "impl_auth"
        assert cfg["prd_ref"] == "PRD-TEST-001"
        assert cfg["solution_design"] == "/tmp/design.md"
        assert cfg["bead_id"] == "BEAD-42"

    def test_all_optional_fields(self, tmp_path):
        """cobuilder.attractor.session_runner.py accepts all optional arguments."""
        rc, stdout, _ = _run_cli(
            "session_runner.py",
            ["--spawn", "--node", "impl_auth", "--prd", "PRD-TEST-001",
             "--acceptance", "All tests pass",
             "--target-dir", str(tmp_path)],
            env_overrides={
                "ATTRACTOR_SIGNALS_DIR": str(tmp_path / "signals"),
            },
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        assert data["runner_config"]["acceptance_criteria"] == "All tests pass"
        assert data["runner_config"]["target_dir"] == str(tmp_path)

    def test_missing_required_args_exits_nonzero(self, tmp_path):
        """cobuilder.attractor.session_runner.py without required args exits with non-zero code."""
        rc, stdout, stderr = _run_cli("session_runner.py", ["--node", "impl_auth"])
        # Missing --prd
        assert rc != 0

    def test_help_flag_works(self):
        """cobuilder.attractor.session_runner.py --help exits with code 0."""
        rc, stdout, _ = _run_cli("session_runner.py", ["--help"])
        assert rc == 0


# ---------------------------------------------------------------------------
# TestRespondToRunnerCLI
# ---------------------------------------------------------------------------

class TestRespondToRunnerCLI:
    """Tests for respond_to_runner.py."""

    def test_approved_signal_created(self, tmp_path):
        """respond_to_runner.py APPROVED writes signal with source=guardian."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "respond_to_runner.py",
            ["APPROVED", "--node", "impl_auth", "--feedback", "Looks good"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        assert data["status"] == "ok"
        assert data["signal_type"] == "APPROVED"

        with open(data["signal_file"]) as fh:
            signal = json.load(fh)

        assert signal["source"] == "guardian"
        assert signal["target"] == "runner"
        assert signal["payload"]["node_id"] == "impl_auth"
        assert signal["payload"]["feedback"] == "Looks good"

    def test_rejected_with_reason(self, tmp_path):
        """respond_to_runner.py REJECTED --reason stores reason in payload."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "respond_to_runner.py",
            ["REJECTED", "--node", "impl_auth",
             "--reason", "Tests are failing", "--new-status", "blocked"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        with open(data["signal_file"]) as fh:
            signal = json.load(fh)

        assert signal["payload"]["reason"] == "Tests are failing"
        assert signal["payload"]["new_status"] == "blocked"


# ---------------------------------------------------------------------------
# TestEscalateToTerminalCLI
# ---------------------------------------------------------------------------

class TestEscalateToTerminalCLI:
    """Tests for escalate_to_terminal.py."""

    def test_escalation_creates_signal(self, tmp_path):
        """escalate_to_terminal.py creates an ESCALATE signal targeting terminal."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "escalate_to_terminal.py",
            ["--pipeline", "PRD-AUTH-001", "--issue", "Blocked on credentials"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        assert data["status"] == "ok"
        assert "signal_file" in data

        with open(data["signal_file"]) as fh:
            signal = json.load(fh)

        assert signal["source"] == "guardian"
        assert signal["target"] == "terminal"
        assert signal["signal_type"] == "ESCALATE"
        assert signal["payload"]["pipeline_id"] == "PRD-AUTH-001"
        assert signal["payload"]["issue"] == "Blocked on credentials"

    def test_with_options_json(self, tmp_path):
        """escalate_to_terminal.py --options JSON is stored in payload."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "escalate_to_terminal.py",
            ["--pipeline", "PRD-AUTH-001", "--issue", "Need decision",
             "--options", '["retry", "skip", "abort"]'],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )

        assert rc == 0
        data = _parse_json_output(stdout)
        with open(data["signal_file"]) as fh:
            signal = json.load(fh)

        assert signal["payload"]["options"] == ["retry", "skip", "abort"]

    def test_invalid_options_exits_with_error(self, tmp_path):
        """escalate_to_terminal.py with invalid --options JSON exits with error."""
        signals_dir = str(tmp_path / "signals")
        rc, stdout, _ = _run_cli(
            "escalate_to_terminal.py",
            ["--pipeline", "PRD-AUTH-001", "--issue", "test",
             "--options", "not valid json"],
            env_overrides={"ATTRACTOR_SIGNALS_DIR": signals_dir},
        )
        assert rc == 1
        data = _parse_json_output(stdout)
        assert data["status"] == "error"
