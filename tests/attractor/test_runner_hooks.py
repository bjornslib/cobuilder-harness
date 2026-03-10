"""Unit tests for runner_hooks.py — guard rail enforcement.

Tests:
    TestForbiddenToolGuard          - Edit/Write/MultiEdit blocked by pre_tool_use
    TestRetryLimitGuard             - ATTRACTOR_MAX_RETRIES enforced
    TestEvidenceStalenessGuard      - Stale evidence blocked pre-validation
    TestAuditChain                  - ChainedAuditWriter integration via post_tool_use
    TestImplementerSeparation       - Self-validation detection
    TestSpotCheckIntegration        - Spot-check audit entry written on validated
    TestOnStop                      - on_stop writes audit entry
    TestEnvVarMaxRetries            - ATTRACTOR_MAX_RETRIES env var respected
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest

# Ensure attractor package is importable

from cobuilder.attractor.runner_hooks import RunnerHookError, RunnerHooks  # noqa: E402
from cobuilder.attractor.runner_models import AuditEntry, RunnerState  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(pipeline_id: str = "test-pipe") -> RunnerState:
    return RunnerState(
        pipeline_id=pipeline_id,
        pipeline_path=f"/tmp/{pipeline_id}.dot",
        session_id="sess-test",
    )


def _make_hooks(
    state: RunnerState | None = None,
    *,
    audit_path: str | None = None,
    session_id: str = "sess-test",
    verbose: bool = False,
    spot_check_rate: float = 0.0,  # Disable spot-checks by default in tests
    evidence_max_age: int = 300,
) -> RunnerHooks:
    """Convenience factory for RunnerHooks with controlled defaults."""
    if state is None:
        state = _make_state()
    if audit_path is None:
        # Use a temp file; caller responsible for cleanup
        audit_path = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
    return RunnerHooks(
        state=state,
        audit_path=audit_path,
        session_id=session_id,
        verbose=verbose,
        spot_check_rate=spot_check_rate,
        evidence_max_age=evidence_max_age,
    )


def _read_audit_entries(path: str) -> list[dict]:
    """Parse all JSONL entries from an audit file."""
    if not os.path.exists(path):
        return []
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped:
                entries.append(json.loads(stripped))
    return entries


# ---------------------------------------------------------------------------
# Forbidden tool guard
# ---------------------------------------------------------------------------


class TestForbiddenToolGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit = os.path.join(self._tmp, "audit.jsonl")
        self._hooks = _make_hooks(audit_path=self._audit)

    def test_edit_blocked(self) -> None:
        with self.assertRaises(RunnerHookError) as ctx:
            self._hooks.pre_tool_use("Edit", {"file_path": "/foo", "old": "", "new": ""})
        self.assertIn("GUARD RAIL VIOLATION", str(ctx.exception))
        self.assertIn("Edit", str(ctx.exception))

    def test_write_blocked(self) -> None:
        with self.assertRaises(RunnerHookError):
            self._hooks.pre_tool_use("Write", {"file_path": "/foo", "content": ""})

    def test_multiedit_blocked(self) -> None:
        with self.assertRaises(RunnerHookError):
            self._hooks.pre_tool_use("MultiEdit", {})

    def test_notebook_edit_blocked(self) -> None:
        with self.assertRaises(RunnerHookError):
            self._hooks.pre_tool_use("NotebookEdit", {})

    def test_allowed_tool_passes(self) -> None:
        """transition_node should not raise from the forbidden-tool guard."""
        # Does not raise (retry check is separate, and node has 0 retries)
        self._hooks.pre_tool_use(
            "transition_node", {"node_id": "n1", "new_status": "active"}
        )

    def test_get_pipeline_status_passes(self) -> None:
        self._hooks.pre_tool_use("get_pipeline_status", {})


# ---------------------------------------------------------------------------
# Retry limit guard
# ---------------------------------------------------------------------------


class TestRetryLimitGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit = os.path.join(self._tmp, "audit.jsonl")
        self._state = _make_state()
        self._hooks = _make_hooks(state=self._state, audit_path=self._audit)

    def _set_retries(self, node_id: str, count: int) -> None:
        self._state.retry_counts[node_id] = count

    def test_below_limit_allowed(self) -> None:
        """Retrying a node below MAX_RETRIES must not raise."""
        self._set_retries("node-x", 2)
        # Should not raise (2 < 3)
        self._hooks.pre_tool_use(
            "transition_node", {"node_id": "node-x", "new_status": "active"}
        )

    def test_at_limit_blocked(self) -> None:
        """Retrying a node at MAX_RETRIES must raise RunnerHookError."""
        self._set_retries("node-x", 3)
        with self.assertRaises(RunnerHookError) as ctx:
            self._hooks.pre_tool_use(
                "transition_node", {"node_id": "node-x", "new_status": "active"}
            )
        self.assertIn("RETRY LIMIT", str(ctx.exception))
        self.assertIn("node-x", str(ctx.exception))

    def test_above_limit_blocked(self) -> None:
        """Retrying a node above MAX_RETRIES must raise."""
        self._set_retries("node-y", 10)
        with self.assertRaises(RunnerHookError):
            self._hooks.pre_tool_use(
                "transition_node", {"node_id": "node-y", "new_status": "active"}
            )

    def test_transition_to_other_status_not_blocked(self) -> None:
        """Transitioning to 'failed' or 'validated' must not trigger retry guard."""
        self._set_retries("node-z", 99)
        # 'failed' and 'validated' transitions are allowed even if retries are high
        self._hooks.pre_tool_use(
            "transition_node", {"node_id": "node-z", "new_status": "failed"}
        )
        self._hooks.pre_tool_use(
            "transition_node", {"node_id": "node-z", "new_status": "validated"}
        )


# ---------------------------------------------------------------------------
# Evidence staleness guard
# ---------------------------------------------------------------------------


class TestEvidenceStalenessGuard(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit = os.path.join(self._tmp, "audit.jsonl")
        # Very short max-age so we can create stale timestamps easily
        self._hooks = _make_hooks(audit_path=self._audit, evidence_max_age=60)

    def _ts(self, delta_s: float) -> str:
        dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            seconds=delta_s
        )
        return dt.isoformat()

    def test_fresh_evidence_allowed(self) -> None:
        """Fresh evidence on validated transition must pass."""
        self._hooks.pre_tool_use(
            "transition_node",
            {
                "node_id": "n1",
                "new_status": "validated",
                "evidence_timestamp": self._ts(-5),
            },
        )

    def test_stale_evidence_blocked(self) -> None:
        """Stale evidence timestamp must raise RunnerHookError."""
        with self.assertRaises(RunnerHookError) as ctx:
            self._hooks.pre_tool_use(
                "transition_node",
                {
                    "node_id": "n1",
                    "new_status": "validated",
                    "evidence_timestamp": self._ts(-120),  # 120s old, max=60
                },
            )
        self.assertIn("EVIDENCE STALENESS", str(ctx.exception))

    def test_future_evidence_blocked(self) -> None:
        """Future evidence timestamp must raise RunnerHookError."""
        with self.assertRaises(RunnerHookError):
            self._hooks.pre_tool_use(
                "transition_node",
                {
                    "node_id": "n1",
                    "new_status": "validated",
                    "evidence_timestamp": self._ts(+30),
                },
            )

    def test_no_timestamp_not_blocked(self) -> None:
        """Missing evidence_timestamp must not block the transition."""
        self._hooks.pre_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "validated"},
        )

    def test_empty_timestamp_not_blocked(self) -> None:
        """Empty evidence_timestamp string must not block."""
        self._hooks.pre_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "validated", "evidence_timestamp": ""},
        )

    def test_impl_complete_checked_too(self) -> None:
        """impl_complete transitions also undergo staleness checks."""
        with self.assertRaises(RunnerHookError):
            self._hooks.pre_tool_use(
                "transition_node",
                {
                    "node_id": "n1",
                    "new_status": "impl_complete",
                    "evidence_timestamp": self._ts(-120),
                },
            )


# ---------------------------------------------------------------------------
# Audit chain integration
# ---------------------------------------------------------------------------


class TestAuditChain(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit = os.path.join(self._tmp, "audit.jsonl")
        self._hooks = _make_hooks(audit_path=self._audit)

    def test_transition_writes_audit_entry(self) -> None:
        """post_tool_use for transition_node must write an audit entry."""
        result = json.dumps({"previous_status": "pending", "evidence": ""})
        self._hooks.post_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "active"},
            result,
        )
        entries = _read_audit_entries(self._audit)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["node_id"], "n1")
        self.assertEqual(entries[0]["to_status"], "active")

    def test_chain_is_intact_after_multiple_transitions(self) -> None:
        """Audit chain must verify successfully after several transitions."""
        result = json.dumps({"previous_status": "pending"})
        for i in range(5):
            self._hooks.post_tool_use(
                "transition_node",
                {"node_id": f"node-{i}", "new_status": "active"},
                result,
            )
        ok, msg = self._hooks.verify_audit_chain()
        self.assertTrue(ok, f"Chain should be valid but: {msg}")

    def test_on_stop_writes_audit_entry(self) -> None:
        """on_stop must write a final audit entry."""
        self._hooks.on_stop(plan=None, reason="test_stop")
        entries = _read_audit_entries(self._audit)
        self.assertGreater(len(entries), 0)
        last = entries[-1]
        self.assertEqual(last["node_id"], "__runner__")
        self.assertEqual(last["to_status"], "test_stop")

    def test_audit_entry_has_prev_hash_field(self) -> None:
        """Every written audit entry must have a 'prev_hash' key."""
        result = json.dumps({"previous_status": "pending"})
        self._hooks.post_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "active"},
            result,
        )
        entries = _read_audit_entries(self._audit)
        self.assertIn("prev_hash", entries[0])

    def test_first_entry_prev_hash_empty(self) -> None:
        """The first audit entry must have prev_hash=''."""
        result = json.dumps({"previous_status": "pending"})
        self._hooks.post_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "active"},
            result,
        )
        entries = _read_audit_entries(self._audit)
        self.assertEqual(entries[0]["prev_hash"], "")

    def test_retry_counter_incremented_on_failed(self) -> None:
        """Failed transition must increment state retry_counts."""
        state = _make_state()
        hooks = _make_hooks(state=state, audit_path=self._audit)
        result = json.dumps({"previous_status": "active"})
        hooks.post_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "failed"},
            result,
        )
        self.assertEqual(state.retry_counts.get("n1", 0), 1)

    def test_retry_counter_reset_on_validated(self) -> None:
        """Validated transition must reset the retry counter."""
        state = _make_state()
        state.retry_counts["n1"] = 2
        hooks = _make_hooks(state=state, audit_path=self._audit)
        result = json.dumps({"previous_status": "impl_complete"})
        hooks.post_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "validated"},
            result,
        )
        self.assertNotIn("n1", state.retry_counts)


# ---------------------------------------------------------------------------
# Implementer separation
# ---------------------------------------------------------------------------


class TestImplementerSeparation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit = os.path.join(self._tmp, "audit.jsonl")
        self._state = _make_state()
        self._hooks = _make_hooks(state=self._state, audit_path=self._audit)

    def test_same_agent_blocked(self) -> None:
        """The same session that implemented cannot validate."""
        self._state.record_implementer("node-auth", "sess-implementer")
        with self.assertRaises(RunnerHookError) as ctx:
            self._hooks.check_implementer_separation("node-auth", "sess-implementer")
        self.assertIn("ANTI-GAMING VIOLATION", str(ctx.exception))
        self.assertIn("sess-implementer", str(ctx.exception))

    def test_different_agent_allowed(self) -> None:
        """A different session may validate without restriction."""
        self._state.record_implementer("node-auth", "sess-implementer")
        # Should not raise
        self._hooks.check_implementer_separation("node-auth", "sess-validator")

    def test_unknown_node_allowed(self) -> None:
        """If no implementer is recorded, any session may validate."""
        # No record for 'node-unknown'
        self._hooks.check_implementer_separation("node-unknown", "sess-validator")

    def test_spawn_tracking_records_implementer(self) -> None:
        """post_tool_use for spawn_orchestrator must record the spawned session."""
        result = json.dumps({"session_id": "sess-worker-1"})
        self._hooks.post_tool_use(
            "spawn_orchestrator",
            {"node_id": "node-backend"},
            result,
        )
        self.assertEqual(
            self._state.implementer_map.get("node-backend"), "sess-worker-1"
        )


# ---------------------------------------------------------------------------
# Spot-check integration
# ---------------------------------------------------------------------------


class TestSpotCheckIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit = os.path.join(self._tmp, "audit.jsonl")

    def test_spot_check_writes_extra_entry(self) -> None:
        """With rate=1.0, every validated node should get a spot-check entry."""
        hooks = _make_hooks(
            audit_path=self._audit,
            spot_check_rate=1.0,  # Always spot-check
        )
        result = json.dumps({"previous_status": "impl_complete"})
        hooks.post_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "validated"},
            result,
        )
        entries = _read_audit_entries(self._audit)
        # Expect: transition entry + spot_check_flagged entry
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[1]["to_status"], "spot_check_flagged")

    def test_no_spot_check_with_rate_zero(self) -> None:
        """With rate=0.0, no spot-check entry should be written."""
        hooks = _make_hooks(
            audit_path=self._audit,
            spot_check_rate=0.0,  # Never spot-check
        )
        result = json.dumps({"previous_status": "impl_complete"})
        hooks.post_tool_use(
            "transition_node",
            {"node_id": "n1", "new_status": "validated"},
            result,
        )
        entries = _read_audit_entries(self._audit)
        # Only the transition entry, no spot-check entry
        to_statuses = {e["to_status"] for e in entries}
        self.assertNotIn("spot_check_flagged", to_statuses)


# ---------------------------------------------------------------------------
# Environment variable: ATTRACTOR_MAX_RETRIES
# ---------------------------------------------------------------------------


class TestEnvVarMaxRetries(unittest.TestCase):
    """Verify that ATTRACTOR_MAX_RETRIES env var is read at module import.

    Note: The module-level MAX_RETRIES is read once at import time.
    We test the RunnerHooks behaviour with explicit state manipulation.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._audit = os.path.join(self._tmp, "audit.jsonl")

    def test_default_max_retries_is_three(self) -> None:
        """Without ATTRACTOR_MAX_RETRIES set, MAX_RETRIES should be 3."""
        import cobuilder.attractor.runner_hooks as runner_hooks
        # The env var is read at module load; if ATTRACTOR_MAX_RETRIES is not
        # set in the test environment the default must be 3.
        default = int(os.environ.get("ATTRACTOR_MAX_RETRIES", "3"))
        self.assertEqual(runner_hooks.MAX_RETRIES, default)

    def test_retry_guard_uses_module_max_retries(self) -> None:
        """Ensure the guard compares against the module-level MAX_RETRIES."""
        import cobuilder.attractor.runner_hooks as rh
        current_max = rh.MAX_RETRIES

        state = _make_state()
        state.retry_counts["node-x"] = current_max  # exactly at limit
        hooks = _make_hooks(state=state, audit_path=self._audit)

        with self.assertRaises(RunnerHookError):
            hooks.pre_tool_use(
                "transition_node", {"node_id": "node-x", "new_status": "active"}
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
