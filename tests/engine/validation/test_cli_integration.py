"""CLI integration tests for `cobuilder pipeline validate`.

These tests invoke the CLI via typer's test client (no subprocess) and verify:
- Exit code 0 on valid DOT
- Exit code 1 on DOT with errors
- Exit code 2 on missing file / DOT parse error
- --json flag produces valid JSON with expected keys
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

# ---------------------------------------------------------------------------
# Sample DOT content
# ---------------------------------------------------------------------------

VALID_DOT = """
digraph test_valid {
    start   [shape=Mdiamond  label="Start"]
    impl    [shape=box       label="Implement" prompt="Write the code" sd_path=".taskmaster/docs/SD-TEST.md" worker_type="backend-solutions-engineer"]
    validate [shape=hexagon  label="Validate" handler="wait_cobuilder" gate_type="e2e" summary_ref=".claude/evidence/summary.md" bead_id="bd-test"]
    human   [shape=hexagon   label="Human Review" handler="wait_human" mode="e2e-review"]
    done    [shape=Msquare   label="Done"]

    start   -> impl
    impl    -> validate
    validate -> human
    human   -> done
}
"""

INVALID_DOT_NO_START = """
digraph test_no_start {
    impl [shape=box     label="Impl"]
    done [shape=Msquare label="Done"]
    impl -> done
}
"""

WARNING_ONLY_DOT = """
digraph test_warnings {
    start   [shape=Mdiamond  label="Start"]
    impl    [shape=box       label="" prompt="Write the code" sd_path=".taskmaster/docs/SD-TEST.md" worker_type="backend-solutions-engineer"]
    validate [shape=hexagon  label="Validate" handler="wait_cobuilder" gate_type="e2e" summary_ref=".claude/evidence/summary.md" bead_id="bd-test"]
    human   [shape=hexagon   label="Human Review" handler="wait_human" mode="e2e-review"]
    done    [shape=Msquare   label="Done"]

    start   -> impl
    impl    -> validate
    validate -> human
    human   -> done
}
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli_app():
    # Import here to avoid issues if cli has heavy side-effects at import time.
    from cobuilder.cli import app
    return app


@pytest.fixture
def valid_dot_file(tmp_path):
    f = tmp_path / "valid.dot"
    f.write_text(VALID_DOT)
    return str(f)


@pytest.fixture
def invalid_dot_file(tmp_path):
    f = tmp_path / "invalid.dot"
    f.write_text(INVALID_DOT_NO_START)
    return str(f)


@pytest.fixture
def warning_dot_file(tmp_path):
    f = tmp_path / "warnings.dot"
    f.write_text(WARNING_ONLY_DOT)
    return str(f)


# ---------------------------------------------------------------------------
# Exit code tests
# ---------------------------------------------------------------------------

class TestCLIExitCodes:
    def test_exit_0_on_valid_graph(self, runner, cli_app, valid_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", valid_dot_file])
        assert result.exit_code == 0, f"Expected 0, got {result.exit_code}\n{result.output}"

    def test_exit_1_on_graph_with_errors(self, runner, cli_app, invalid_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", invalid_dot_file])
        assert result.exit_code == 1, f"Expected 1, got {result.exit_code}\n{result.output}"

    def test_exit_2_on_missing_file(self, runner, cli_app):
        result = runner.invoke(cli_app, ["pipeline", "validate", "/nonexistent/path/test.dot"])
        assert result.exit_code == 2, f"Expected 2, got {result.exit_code}\n{result.output}"

    def test_exit_0_on_warnings_only(self, runner, cli_app, warning_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", warning_dot_file])
        # Warnings do not block → exit 0
        assert result.exit_code == 0, f"Expected 0, got {result.exit_code}\n{result.output}"


# ---------------------------------------------------------------------------
# JSON output tests
# ---------------------------------------------------------------------------

class TestCLIJsonOutput:
    def test_json_output_valid_graph(self, runner, cli_app, valid_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", valid_dot_file, "--json"])
        assert result.exit_code == 0

        data = json.loads(result.output)
        assert "valid" in data
        assert "error_count" in data
        assert "warning_count" in data
        assert "violations" in data
        assert isinstance(data["violations"], list)
        assert data["valid"] is True
        assert data["error_count"] == 0

    def test_json_output_invalid_graph(self, runner, cli_app, invalid_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", invalid_dot_file, "--json"])
        assert result.exit_code == 1

        data = json.loads(result.output)
        assert data["valid"] is False
        assert data["error_count"] >= 1
        # Violations list is non-empty
        assert len(data["violations"]) >= 1
        # Each violation has required keys
        for v in data["violations"]:
            assert "rule_id" in v
            assert "severity" in v
            assert "message" in v
            assert "fix_hint" in v

    def test_json_pipeline_id_key(self, runner, cli_app, valid_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", valid_dot_file, "--json"])
        data = json.loads(result.output)
        assert "pipeline_id" in data


# ---------------------------------------------------------------------------
# Output text tests
# ---------------------------------------------------------------------------

class TestCLITextOutput:
    def test_valid_message_in_stdout(self, runner, cli_app, valid_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", valid_dot_file])
        assert "VALID" in result.output

    def test_invalid_message_in_stdout(self, runner, cli_app, invalid_dot_file):
        result = runner.invoke(cli_app, ["pipeline", "validate", invalid_dot_file])
        output_upper = result.output.upper()
        assert "INVALID" in output_upper or "ERROR" in output_upper
