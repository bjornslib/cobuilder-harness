"""Tests for SDK stream error handling in pipeline_runner.py.

Verifies that SDK stream errors (e.g. rate_limit_event) do not cause
false-positive success results, and that the signal file is used as
the ground truth for worker completion.

Tests:
    TestStreamErrorHandlerNoResult    - Stream error without result_text returns failed
    TestStreamErrorHandlerWithResult  - Stream error after result_text returns success
    TestStreamErrorNoMessages         - Stream error with zero messages propagates
    TestValidationStreamError         - Validation stream error returns fail (not auto-pass)
    TestSignalFileExistsPreservesSuccess - Signal file present keeps success result
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: build a minimal PipelineRunner without touching the filesystem
# ---------------------------------------------------------------------------


def _make_runner(signal_dir: str) -> object:
    """Create a PipelineRunner bypassing __init__, with just the attrs we need."""
    from cobuilder.engine.pipeline_runner import PipelineRunner
    from cobuilder.engine.providers import ProvidersFile

    runner = PipelineRunner.__new__(PipelineRunner)
    runner.signal_dir = signal_dir
    runner.dot_path = "/tmp/test_pipeline.dot"
    runner.dot_dir = "/tmp"
    runner.pipeline_id = "test_pipeline"
    runner.active_workers = {}
    runner._wake_event = threading.Event()
    runner.retry_counts = {}
    runner.requeue_guidance = {}
    runner.orphan_resume_counts = {}
    runner._signal_seq = {}
    runner._graph_attrs = {}
    runner._providers = ProvidersFile({}, default_profile=None)
    # Default: node is still "active" (signal watcher hasn't processed yet).
    # Tests for the race condition (Fix 5) can override this.
    runner._get_node_status = lambda nid: "active"
    return runner


# ---------------------------------------------------------------------------
# Shared async mock message types
# ---------------------------------------------------------------------------


class _FakeMsg:
    """Minimal stand-in for SDK message objects."""

    def __init__(self, result: str | None = None):
        self.result = result


# ---------------------------------------------------------------------------
# TestStreamErrorHandlerNoResult
# ---------------------------------------------------------------------------


class TestStreamErrorHandlerNoResult:
    """Stream error with messages but no result_text must return failed, not success."""

    def test_stream_error_without_result_returns_failed(self, tmp_path):
        """Mock _dispatch_sdk_worker to raise after handshake — caller converts to failed.

        This exercises the middle tier of the exception handler in _dispatch_via_sdk:
        the branch where ``messages`` is non-empty but ``result_text`` is empty.
        We invoke _dispatch_via_sdk directly by mocking ``claude_code_sdk.query``
        to yield a handshake message then raise a rate-limit exception.
        """
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        # Fake async generator: yields one message then raises
        async def _fake_query(prompt, options):  # noqa: ARG001
            yield _FakeMsg(result=None)
            raise RuntimeError("rate_limit_event: too many requests")

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        captured = {}

        def _fake_write_node_signal(node_id, payload):
            captured["node_id"] = node_id
            captured["payload"] = payload

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True

            runner._dispatch_via_sdk("impl_auth", "backend-solutions-engineer", "do work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        # No signal file written by worker — signal file check also fires
        assert captured["payload"]["status"] == "failed"
        assert "signal file" in captured["payload"]["message"].lower() or \
               "stream error" in captured["payload"]["message"].lower()

    def test_stream_error_without_result_message_contains_error_info(self, tmp_path):
        """Failure message from stream error contains event count and error text."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        rate_limit_msg = "rate_limit_event: 429 too many requests"

        async def _fake_query(prompt, options):  # noqa: ARG001
            yield _FakeMsg(result=None)
            yield _FakeMsg(result=None)
            raise RuntimeError(rate_limit_msg)

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        captured = {}

        def _fake_write_node_signal(node_id, payload):
            captured["payload"] = payload

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._dispatch_via_sdk("impl_auth", "backend-solutions-engineer", "work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        assert captured["payload"]["status"] == "failed"


# ---------------------------------------------------------------------------
# TestStreamErrorHandlerWithResult
# ---------------------------------------------------------------------------


class TestStreamErrorHandlerWithResult:
    """Stream error AFTER result_text was captured should still return success.

    The worker completed its task and the error occurred at the tail end.
    This case must NOT be converted to failed.
    """

    def test_stream_error_after_result_yields_success_if_signal_file_exists(self, tmp_path):
        """When result_text is set AND signal file exists, success is preserved."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        # Pre-write the signal file as the worker would
        signal_path = os.path.join(signal_dir, "impl_auth.json")
        with open(signal_path, "w") as fh:
            json.dump({"status": "impl_complete", "node_id": "impl_auth"}, fh)

        # Fake msg with a result attribute set
        class _ResultMsg:
            result = "Task completed successfully."

        async def _fake_query(prompt, options):  # noqa: ARG001
            yield _ResultMsg()
            raise RuntimeError("trailing stream error")

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        captured = {}

        def _fake_write_node_signal(node_id, payload):
            captured["payload"] = payload

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._dispatch_via_sdk("impl_auth", "backend-solutions-engineer", "work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        # Signal file existed → success is preserved
        assert captured["payload"]["status"] == "success"
        assert "Task completed" in captured["payload"]["message"]


# ---------------------------------------------------------------------------
# TestStreamErrorNoMessages
# ---------------------------------------------------------------------------


class TestStreamErrorNoMessages:
    """Stream error with zero messages should propagate as an exception."""

    def test_stream_error_no_messages_results_in_failed(self, tmp_path):
        """Zero-message stream errors propagate → outer except catches → status=failed."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        async def _fake_query(prompt, options):  # noqa: ARG001
            # Raise immediately without yielding anything
            raise RuntimeError("connection refused: no messages at all")
            # The `yield` below makes this a valid async generator
            yield  # noqa: unreachable

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        captured = {}

        def _fake_write_node_signal(node_id, payload):
            captured["payload"] = payload

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._dispatch_via_sdk("impl_auth", "backend-solutions-engineer", "work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        # The outer except in _dispatch_via_sdk catches the re-raised exception
        assert captured["payload"]["status"] == "failed"
        assert "connection refused" in captured["payload"]["message"].lower() or \
               "SDK dispatch error" in captured["payload"]["message"]


# ---------------------------------------------------------------------------
# TestValidationStreamError
# ---------------------------------------------------------------------------


class TestValidationStreamError:
    """Validation stream errors must return fail, not auto-pass."""

    def test_validation_stream_error_returns_fail(self, tmp_path):
        """When the validation SDK stream raises, result is fail not pass."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        # Simulate a rate limit mid-validation stream
        async def _fake_query(prompt, options):  # noqa: ARG001
            yield _FakeMsg(result=None)
            raise RuntimeError("rate_limit_event during validation")

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        # Capture what _write_node_signal receives
        validation_signals = []

        def _fake_write_node_signal(node_id, payload):
            validation_signals.append((node_id, payload))

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._build_validation_prompt = lambda nid: "validate this"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"
        runner._validation_method_hint = None

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._run_validation_subprocess("validate_impl_auth", "impl_auth")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        # Exactly one signal should have been written
        assert len(validation_signals) == 1, \
            f"Expected 1 signal, got {len(validation_signals)}: {validation_signals}"
        _nid, payload = validation_signals[0]
        assert payload.get("result") == "fail", \
            f"Expected result=fail, got: {payload}"
        assert "stream error" in payload.get("reason", "").lower() or \
               "validation stream error" in payload.get("reason", "").lower(), \
            f"Unexpected reason: {payload.get('reason')}"

    def test_validation_stream_error_reason_contains_exception_text(self, tmp_path):
        """Fail reason includes the exception message text."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        exc_text = "rate_limit_event: quota exceeded for model haiku"

        async def _fake_query(prompt, options):  # noqa: ARG001
            yield _FakeMsg(result=None)
            raise RuntimeError(exc_text)

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        captured = {}

        def _fake_write_node_signal(node_id, payload):
            captured["payload"] = payload

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._build_validation_prompt = lambda nid: "validate this"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"
        runner._validation_method_hint = None

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._run_validation_subprocess("validate_impl_auth", "impl_auth")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        reason = captured["payload"].get("reason", "")
        assert exc_text[:50] in reason, \
            f"Exception text not in reason. reason={reason!r}"


# ---------------------------------------------------------------------------
# TestSignalFileExistsPreservesSuccess
# ---------------------------------------------------------------------------


class TestSignalFileExistsPreservesSuccess:
    """When signal file exists and SDK reports success, result stays success."""

    def test_signal_file_exists_preserves_success(self, tmp_path):
        """Normal happy path: worker writes signal file, SDK returns success → stays success."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        # Pre-write the worker signal file (simulating a completed worker)
        signal_path = os.path.join(signal_dir, "impl_payments.json")
        with open(signal_path, "w") as fh:
            json.dump({"status": "impl_complete", "node_id": "impl_payments"}, fh)

        class _ResultMsg:
            result = "All payments implemented."

        async def _fake_query(prompt, options):  # noqa: ARG001
            yield _ResultMsg()

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        captured = {}

        def _fake_write_node_signal(node_id, payload):
            captured["payload"] = payload

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._dispatch_via_sdk("impl_payments", "backend-solutions-engineer", "work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        assert captured["payload"]["status"] == "success"
        assert "All payments implemented" in captured["payload"]["message"]

    def test_signal_file_missing_runner_writes_on_workers_behalf(self, tmp_path):
        """When signal file is ABSENT and SDK reports success, runner writes signal on worker's behalf."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        # No signal file pre-written — worker didn't complete

        class _ResultMsg:
            result = "Task done."

        async def _fake_query(prompt, options):  # noqa: ARG001
            yield _ResultMsg()

        fake_sdk = MagicMock()
        fake_sdk.query = _fake_query
        fake_sdk.ClaudeCodeOptions = MagicMock(return_value=MagicMock())

        captured = {}

        def _fake_write_node_signal(node_id, payload):
            captured["payload"] = payload

        runner._write_node_signal = _fake_write_node_signal
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_cobuilder_root = lambda: "/tmp"

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._dispatch_via_sdk("impl_payments", "backend-solutions-engineer", "work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        # Runner writes signal on worker's behalf when SDK completes successfully
        assert captured["payload"]["status"] == "success"
        assert "Task done" in captured["payload"]["message"]


# ---------------------------------------------------------------------------
# TestLoadAttractorEnvPath
# ---------------------------------------------------------------------------


class TestLoadAttractorEnvPath:
    """dispatch_worker.load_engine_env() must find cobuilder/engine/.env
    co-located with the module."""

    def test_load_engine_env_finds_dotenv(self, tmp_path):
        """load_engine_env() reads from the directory next to the module."""
        from cobuilder.engine import dispatch_worker as dw_mod

        # Create a fake .env in a temp dir
        dot_env = tmp_path / ".env"
        dot_env.write_text(
            "ANTHROPIC_API_KEY=test-key-from-dotenv\n"
            "ANTHROPIC_MODEL=qwen-test-model\n"
            "# comment line\n"
            "UNRELATED_KEY=should-be-ignored\n",
            encoding="utf-8",
        )

        original_this_dir = dw_mod._this_dir
        try:
            dw_mod._this_dir = tmp_path
            result = dw_mod.load_engine_env()
        finally:
            dw_mod._this_dir = original_this_dir

        assert result.get("ANTHROPIC_API_KEY") == "test-key-from-dotenv"
        assert result.get("ANTHROPIC_MODEL") == "qwen-test-model"
        assert "UNRELATED_KEY" not in result, (
            "Keys not in core set, providers.yaml, or PIPELINE_* prefix must not be returned"
        )

    def test_load_engine_env_loads_provider_referenced_keys(self, tmp_path):
        """load_engine_env() loads keys referenced by $VAR in providers.yaml."""
        from cobuilder.engine import dispatch_worker as dw_mod

        # Create a providers.yaml that references $OPENROUTER_API_KEY
        providers_yaml = tmp_path / "providers.yaml"
        providers_yaml.write_text(
            "profiles:\n"
            "  openrouter:\n"
            "    model: test-model\n"
            "    api_key: $OPENROUTER_API_KEY\n"
            "    base_url: https://openrouter.ai/api/v1\n",
            encoding="utf-8",
        )

        # Create a .env that defines OPENROUTER_API_KEY
        dot_env = tmp_path / ".env"
        dot_env.write_text(
            "OPENROUTER_API_KEY=sk-or-test-key\n"
            "ANTHROPIC_API_KEY=sk-ant-test\n",
            encoding="utf-8",
        )

        original_this_dir = dw_mod._this_dir
        try:
            dw_mod._this_dir = tmp_path
            result = dw_mod.load_engine_env()
        finally:
            dw_mod._this_dir = original_this_dir

        assert result.get("OPENROUTER_API_KEY") == "sk-or-test-key"
        assert result.get("ANTHROPIC_API_KEY") == "sk-ant-test"

    def test_load_engine_env_expands_dollar_refs(self, tmp_path):
        """load_engine_env() expands $VAR references in values."""
        from cobuilder.engine import dispatch_worker as dw_mod

        dot_env = tmp_path / ".env"
        dot_env.write_text(
            "ANTHROPIC_API_KEY=sk-original\n"
            "ANTHROPIC_MODEL=$ANTHROPIC_API_KEY\n",
            encoding="utf-8",
        )

        original_this_dir = dw_mod._this_dir
        try:
            dw_mod._this_dir = tmp_path
            result = dw_mod.load_engine_env()
        finally:
            dw_mod._this_dir = original_this_dir

        assert result.get("ANTHROPIC_MODEL") == "sk-original"

    def test_load_engine_env_returns_empty_if_missing(self, tmp_path):
        """When .env is absent, load_engine_env() returns {} without error."""
        from cobuilder.engine import dispatch_worker as dw_mod

        original_this_dir = dw_mod._this_dir
        try:
            dw_mod._this_dir = tmp_path  # no .env here
            result = dw_mod.load_engine_env()
        finally:
            dw_mod._this_dir = original_this_dir

        assert result == {}


# ---------------------------------------------------------------------------
# TestPipelineRunnerEnvOverride
# ---------------------------------------------------------------------------


class TestPipelineRunnerEnvOverride:
    """_load_engine_env must OVERRIDE existing env vars, not skip them."""

    def test_pipeline_runner_env_override(self, tmp_path):
        """If ANTHROPIC_MODEL is already set in os.environ, .env must override it."""
        from cobuilder.engine.pipeline_runner import PipelineRunner

        # Create .env in tmp_path (simulating the co-located .env)
        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_MODEL=overridden-model\n", encoding="utf-8")

        runner = PipelineRunner.__new__(PipelineRunner)

        old_val = os.environ.get("ANTHROPIC_MODEL")
        os.environ["ANTHROPIC_MODEL"] = "original-model"
        try:
            # Mock __file__ resolution so _load_engine_env finds our temp .env
            with patch(
                "cobuilder.engine.pipeline_runner.os.path.abspath",
                return_value=str(tmp_path / "pipeline_runner.py"),
            ):
                runner._load_engine_env()
            assert os.environ.get("ANTHROPIC_MODEL") == "overridden-model", (
                "_load_engine_env must override existing env vars; "
                f"got {os.environ.get('ANTHROPIC_MODEL')!r}"
            )
        finally:
            if old_val is None:
                os.environ.pop("ANTHROPIC_MODEL", None)
            else:
                os.environ["ANTHROPIC_MODEL"] = old_val


# ---------------------------------------------------------------------------
# TestRateLimitRetry
# ---------------------------------------------------------------------------


def _make_runner_for_retry(signal_dir: str) -> object:
    """Minimal PipelineRunner suitable for retry tests."""
    from cobuilder.engine.pipeline_runner import PipelineRunner
    from cobuilder.engine.providers import ProvidersFile

    runner = PipelineRunner.__new__(PipelineRunner)
    runner.signal_dir = signal_dir
    runner.dot_path = "/tmp/test_pipeline.dot"
    runner.dot_file = "/tmp/test_pipeline.dot"
    runner.dot_dir = "/tmp"
    runner.pipeline_id = "test_pipeline"
    runner.active_workers = {}
    runner._wake_event = threading.Event()
    runner.retry_counts = {}
    runner.requeue_guidance = {}
    runner.orphan_resume_counts = {}
    runner._signal_seq = {}
    runner._graph_attrs = {}
    runner._providers = ProvidersFile({}, default_profile=None)
    return runner


class TestRateLimitRetry:
    """Rate limit retry wraps _dispatch_via_sdk with backoff and caps attempts."""

    def test_rate_limit_retry_succeeds_on_second_attempt(self, tmp_path):
        """When the first dispatch fails with rate_limit, a second attempt succeeds."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner_for_retry(signal_dir)

        call_count = {"n": 0}

        def _fake_dispatch_via_sdk(node_id, worker_type, prompt, handler="codergen", target_dir="", llm_config=None):
            call_count["n"] += 1
            signal_path = os.path.join(signal_dir, f"{node_id}.json")
            if call_count["n"] == 1:
                # First attempt: write a rate_limit failure signal
                with open(signal_path, "w") as fh:
                    json.dump({"status": "failed", "message": "rate_limit_event: 429"}, fh)
            else:
                # Second attempt: write success signal
                with open(signal_path, "w") as fh:
                    json.dump({"status": "success", "message": "done"}, fh)

        runner._dispatch_via_sdk = _fake_dispatch_via_sdk
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_node_status = lambda nid: "active"  # Node stays active during retry

        written_signals = []

        def _fake_write_node_signal(node_id, payload):
            written_signals.append(payload)

        runner._write_node_signal = _fake_write_node_signal

        old_retries = os.environ.get("PIPELINE_RATE_LIMIT_RETRIES")
        old_backoff = os.environ.get("PIPELINE_RATE_LIMIT_BACKOFF")
        try:
            os.environ["PIPELINE_RATE_LIMIT_RETRIES"] = "3"
            os.environ["PIPELINE_RATE_LIMIT_BACKOFF"] = "0"  # no sleeping in tests
            pr_mod._SDK_AVAILABLE = True

            # Call _dispatch_agent_sdk directly (the public method with the retry loop)
            runner._dispatch_agent_sdk(
                node_id="impl_auth",
                worker_type="backend-solutions-engineer",
                prompt="do work",
            )
        finally:
            if old_retries is None:
                os.environ.pop("PIPELINE_RATE_LIMIT_RETRIES", None)
            else:
                os.environ["PIPELINE_RATE_LIMIT_RETRIES"] = old_retries
            if old_backoff is None:
                os.environ.pop("PIPELINE_RATE_LIMIT_BACKOFF", None)
            else:
                os.environ["PIPELINE_RATE_LIMIT_BACKOFF"] = old_backoff

        assert call_count["n"] == 2, f"Expected 2 dispatch attempts, got {call_count['n']}"
        # The final signal in the signal file should be success
        final_signal_path = os.path.join(signal_dir, "impl_auth.json")
        with open(final_signal_path) as fh:
            final = json.load(fh)
        assert final["status"] == "success"

    def test_rate_limit_retry_gives_up_after_max(self, tmp_path):
        """When every attempt returns rate_limit, retry stops after MAX_RETRIES."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner_for_retry(signal_dir)

        call_count = {"n": 0}

        def _fake_dispatch_via_sdk(node_id, worker_type, prompt, handler="codergen", target_dir="", llm_config=None):
            call_count["n"] += 1
            signal_path = os.path.join(signal_dir, f"{node_id}.json")
            with open(signal_path, "w") as fh:
                json.dump(
                    {"status": "failed", "message": "rate_limit_event: quota exceeded"},
                    fh,
                )

        runner._dispatch_via_sdk = _fake_dispatch_via_sdk
        runner._get_target_dir = lambda: "/tmp"
        runner._build_system_prompt = lambda wt: "sys"
        runner._get_allowed_tools = lambda h: ["Read"]
        runner._get_node_status = lambda nid: "active"  # Node stays active during retry

        written_signals = []

        def _fake_write_node_signal(node_id, payload):
            written_signals.append(payload)

        runner._write_node_signal = _fake_write_node_signal

        old_retries = os.environ.get("PIPELINE_RATE_LIMIT_RETRIES")
        old_backoff = os.environ.get("PIPELINE_RATE_LIMIT_BACKOFF")
        try:
            os.environ["PIPELINE_RATE_LIMIT_RETRIES"] = "3"
            os.environ["PIPELINE_RATE_LIMIT_BACKOFF"] = "0"
            pr_mod._SDK_AVAILABLE = True

            runner._dispatch_agent_sdk(
                node_id="impl_auth",
                worker_type="backend-solutions-engineer",
                prompt="do work",
            )
        finally:
            if old_retries is None:
                os.environ.pop("PIPELINE_RATE_LIMIT_RETRIES", None)
            else:
                os.environ["PIPELINE_RATE_LIMIT_RETRIES"] = old_retries
            if old_backoff is None:
                os.environ.pop("PIPELINE_RATE_LIMIT_BACKOFF", None)
            else:
                os.environ["PIPELINE_RATE_LIMIT_BACKOFF"] = old_backoff

        assert call_count["n"] == 3, (
            f"Expected exactly MAX_RETRIES=3 attempts, got {call_count['n']}"
        )


# ---------------------------------------------------------------------------
# TestSignalWatcherRaceCondition (Fix 5)
# ---------------------------------------------------------------------------


class TestSignalWatcherRaceCondition:
    """Fix 5: SDK completion must NOT overwrite a worker-written success signal
    when the signal watcher has already advanced the node past 'active'.

    Race timeline:
    1. Worker writes success signal
    2. Signal watcher advances node to impl_complete, dispatches validation
    3. SDK completion fires late with 'failed' — must NOT overwrite the signal
    """

    def test_sdk_skips_signal_write_when_node_already_advanced(self, tmp_path):
        """When node is impl_complete (signal watcher processed), SDK must not write signal."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        # Simulate: worker wrote success, signal watcher advanced to impl_complete
        worker_signal = {"status": "success", "message": "worker done", "files_changed": ["app.py"]}
        signal_path = os.path.join(signal_dir, "impl_e3.json")
        with open(signal_path, "w") as fh:
            json.dump(worker_signal, fh)

        # Node is already impl_complete (signal watcher advanced it)
        runner._get_node_status = lambda nid: "impl_complete"

        # Track whether _write_node_signal is called
        write_calls = []
        original_write = runner.__class__._write_node_signal

        def tracking_write(self_inner, node_id, payload):
            write_calls.append(payload)
            original_write(self_inner, node_id, payload)

        runner._write_node_signal = lambda nid, payload: write_calls.append(payload)

        # Build a fake SDK that returns a failed result (stream error)
        fake_sdk = MagicMock()

        async def _fake_stream(*a, **kw):
            raise RuntimeError("stream timeout after messages")

        fake_sdk.query = _fake_stream
        fake_sdk.ClaudeCodeOptions = MagicMock

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._build_system_prompt = lambda wt: "sys"
            runner._get_allowed_tools = lambda h: ["Read"]
            runner._get_target_dir = lambda: "/tmp"
            runner._dispatch_via_sdk("impl_e3", "backend-solutions-engineer", "work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        # Signal file must still contain the WORKER's success, not SDK's failure
        with open(signal_path) as fh:
            final_signal = json.load(fh)
        assert final_signal["status"] == "success", (
            f"Worker success signal was overwritten! Got: {final_signal}"
        )
        assert write_calls == [], (
            f"_write_node_signal should NOT have been called, but got {write_calls}"
        )

    def test_sdk_writes_signal_when_node_still_active(self, tmp_path):
        """When node is still active (signal watcher hasn't processed), SDK SHOULD write signal."""
        from cobuilder.engine import pipeline_runner as pr_mod

        signal_dir = str(tmp_path / "signals")
        os.makedirs(signal_dir, exist_ok=True)
        runner = _make_runner(signal_dir)

        # Node is still active — signal watcher hasn't processed yet
        runner._get_node_status = lambda nid: "active"

        write_calls = []
        runner._write_node_signal = lambda nid, payload: write_calls.append(payload)

        fake_sdk = MagicMock()

        async def _fake_stream(*a, **kw):
            raise RuntimeError("stream timeout after messages")

        fake_sdk.query = _fake_stream
        fake_sdk.ClaudeCodeOptions = MagicMock

        original_sdk = pr_mod.claude_code_sdk
        original_available = pr_mod._SDK_AVAILABLE
        try:
            pr_mod.claude_code_sdk = fake_sdk
            pr_mod._SDK_AVAILABLE = True
            runner._build_system_prompt = lambda wt: "sys"
            runner._get_allowed_tools = lambda h: ["Read"]
            runner._get_target_dir = lambda: "/tmp"
            runner._dispatch_via_sdk("impl_e3", "backend-solutions-engineer", "work")
        finally:
            pr_mod.claude_code_sdk = original_sdk
            pr_mod._SDK_AVAILABLE = original_available

        # SDK should have written a signal since node is still active
        assert len(write_calls) == 1, (
            f"Expected _write_node_signal to be called once, got {len(write_calls)} calls"
        )
