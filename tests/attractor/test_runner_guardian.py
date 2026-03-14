"""Unit tests for runner_guardian.py — System 3 read-only state monitor.

Tests:
    TestPipelineHealth          - PipelineHealth.to_dict() and _overall_health()
    TestRunnerGuardianGetStatus - get_status() with valid/missing/corrupt files
    TestRunnerGuardianListPipelines - list_pipelines() scanning and sorting
    TestRunnerGuardianGetLastPlan   - get_last_plan() extracts RunnerPlan
    TestRunnerGuardianVerifyChain   - verify_audit_chain() delegates to writer
    TestRunnerGuardianAuditHelpers  - get_audit_summary() and read_audit_entries()
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest

# Ensure attractor package is importable

from cobuilder.engine.guardian_hooks import PipelineHealth, RunnerGuardian  # noqa: E402
from cobuilder.engine.runner_models import NodeAction, RunnerPlan, RunnerState  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now(delta_seconds: float = 0.0) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        seconds=delta_seconds
    )
    return dt.isoformat()


def _make_plan(**kwargs) -> RunnerPlan:
    defaults = {
        "pipeline_id": "TEST-001",
        "summary": "Test plan",
        "current_stage": "EXECUTE",
    }
    defaults.update(kwargs)
    return RunnerPlan(**defaults)


def _make_state(
    pipeline_id: str = "TEST-001",
    *,
    updated_at: str | None = None,
    paused: bool = False,
    last_plan: RunnerPlan | None = None,
    retry_counts: dict | None = None,
    completed_checkpoint_path: str | None = None,
) -> RunnerState:
    return RunnerState(
        pipeline_id=pipeline_id,
        pipeline_path=f"/tmp/{pipeline_id}.dot",
        session_id="sess-test",
        paused=paused,
        last_plan=last_plan,
        retry_counts=retry_counts or {},
        updated_at=updated_at or _utc_now(),
        completed_checkpoint_path=completed_checkpoint_path,
    )


def _write_state(state_dir: str, state: RunnerState) -> str:
    """Write a RunnerState JSON file and return the path."""
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, f"{state.pipeline_id}.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(state.model_dump_json())
    return path


def _make_guardian(state_dir: str, stale_seconds: int = 300) -> RunnerGuardian:
    return RunnerGuardian(state_dir=state_dir, stale_threshold_seconds=stale_seconds)


# ---------------------------------------------------------------------------
# PipelineHealth
# ---------------------------------------------------------------------------


class TestPipelineHealth(unittest.TestCase):
    """Tests for PipelineHealth.to_dict() and _overall_health()."""

    def _make_health(self, **kwargs) -> PipelineHealth:
        defaults = {
            "pipeline_id": "TEST-001",
            "pipeline_path": "/tmp/test.dot",
            "session_id": "sess-1",
            "updated_at": _utc_now(),
            "paused": False,
            "pipeline_complete": False,
            "retry_counts": {},
            "last_summary": "Running",
            "actions_count": 2,
            "blocked_count": 0,
            "completed_count": 3,
            "age_seconds": 10.0,
            "is_stale": False,
            "current_stage": "EXECUTE",
        }
        defaults.update(kwargs)
        return PipelineHealth(**defaults)

    def test_to_dict_has_all_keys(self) -> None:
        h = self._make_health()
        d = h.to_dict()
        for key in [
            "pipeline_id", "pipeline_path", "session_id", "updated_at",
            "paused", "pipeline_complete", "retry_counts", "last_summary",
            "actions_count", "blocked_count", "completed_count",
            "age_seconds", "is_stale", "current_stage", "overall_health",
        ]:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_overall_health_complete(self) -> None:
        h = self._make_health(pipeline_complete=True)
        self.assertEqual(h._overall_health(), "complete")

    def test_overall_health_paused(self) -> None:
        h = self._make_health(paused=True, pipeline_complete=False)
        self.assertEqual(h._overall_health(), "paused")

    def test_overall_health_stale(self) -> None:
        h = self._make_health(is_stale=True, paused=False, pipeline_complete=False)
        self.assertEqual(h._overall_health(), "stale")

    def test_overall_health_stuck(self) -> None:
        h = self._make_health(blocked_count=2, actions_count=0, is_stale=False)
        self.assertEqual(h._overall_health(), "stuck")

    def test_overall_health_warning_on_high_retries(self) -> None:
        h = self._make_health(retry_counts={"n1": 2}, is_stale=False)
        self.assertEqual(h._overall_health(), "warning")

    def test_overall_health_healthy(self) -> None:
        h = self._make_health(
            pipeline_complete=False,
            paused=False,
            is_stale=False,
            blocked_count=0,
            retry_counts={},
        )
        self.assertEqual(h._overall_health(), "healthy")

    def test_complete_takes_priority_over_paused(self) -> None:
        h = self._make_health(pipeline_complete=True, paused=True)
        self.assertEqual(h._overall_health(), "complete")

    def test_to_dict_age_rounded(self) -> None:
        h = self._make_health(age_seconds=123.456789)
        d = h.to_dict()
        self.assertEqual(d["age_seconds"], 123.5)


# ---------------------------------------------------------------------------
# RunnerGuardian.get_status()
# ---------------------------------------------------------------------------


class TestRunnerGuardianGetStatus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._guardian = _make_guardian(self._tmp)

    def test_returns_none_for_missing_pipeline(self) -> None:
        result = self._guardian.get_status("NONEXISTENT-001")
        self.assertIsNone(result)

    def test_returns_health_for_existing_pipeline(self) -> None:
        state = _make_state("PRD-AUTH-001")
        _write_state(self._tmp, state)
        result = self._guardian.get_status("PRD-AUTH-001")
        self.assertIsNotNone(result)
        self.assertEqual(result.pipeline_id, "PRD-AUTH-001")

    def test_health_pipeline_id_matches(self) -> None:
        state = _make_state("PRD-DASH-002")
        _write_state(self._tmp, state)
        health = self._guardian.get_status("PRD-DASH-002")
        self.assertEqual(health.pipeline_id, "PRD-DASH-002")

    def test_health_paused_field(self) -> None:
        state = _make_state("TEST-001", paused=True)
        _write_state(self._tmp, state)
        health = self._guardian.get_status("TEST-001")
        self.assertTrue(health.paused)

    def test_health_not_stale_for_fresh_state(self) -> None:
        state = _make_state("TEST-002", updated_at=_utc_now(-10))
        _write_state(self._tmp, state)
        guardian = _make_guardian(self._tmp, stale_seconds=300)
        health = guardian.get_status("TEST-002")
        self.assertFalse(health.is_stale)

    def test_health_stale_for_old_state(self) -> None:
        state = _make_state("TEST-003", updated_at=_utc_now(-400))
        _write_state(self._tmp, state)
        guardian = _make_guardian(self._tmp, stale_seconds=300)
        health = guardian.get_status("TEST-003")
        self.assertTrue(health.is_stale)

    def test_health_age_approximately_correct(self) -> None:
        state = _make_state("TEST-004", updated_at=_utc_now(-60))
        _write_state(self._tmp, state)
        health = self._guardian.get_status("TEST-004")
        self.assertGreater(health.age_seconds, 50)
        self.assertLess(health.age_seconds, 120)

    def test_returns_none_for_corrupt_json(self) -> None:
        path = os.path.join(self._tmp, "CORRUPT-001.json")
        with open(path, "w") as fh:
            fh.write("NOT_VALID_JSON")
        result = self._guardian.get_status("CORRUPT-001")
        self.assertIsNone(result)

    def test_health_counts_from_plan(self) -> None:
        plan = _make_plan(
            pipeline_id="TEST-005",
            actions=[NodeAction(node_id="n1", action="spawn_orchestrator", reason="test")],
            completed_nodes=["a", "b", "c"],
        )
        state = _make_state("TEST-005", last_plan=plan)
        _write_state(self._tmp, state)
        health = self._guardian.get_status("TEST-005")
        self.assertEqual(health.completed_count, 3)
        self.assertEqual(health.actions_count, 1)

    def test_health_pipeline_complete_from_plan(self) -> None:
        plan = _make_plan(pipeline_id="TEST-006", pipeline_complete=True)
        state = _make_state("TEST-006", last_plan=plan)
        _write_state(self._tmp, state)
        health = self._guardian.get_status("TEST-006")
        self.assertTrue(health.pipeline_complete)
        self.assertEqual(health._overall_health(), "complete")


# ---------------------------------------------------------------------------
# RunnerGuardian.list_pipelines()
# ---------------------------------------------------------------------------


class TestRunnerGuardianListPipelines(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._guardian = _make_guardian(self._tmp)

    def test_empty_dir_returns_empty_list(self) -> None:
        result = self._guardian.list_pipelines()
        self.assertEqual(result, [])

    def test_missing_dir_returns_empty_list(self) -> None:
        guardian = _make_guardian("/nonexistent/path/xyz")
        self.assertEqual(guardian.list_pipelines(), [])

    def test_lists_existing_pipelines(self) -> None:
        for pid in ["PRD-A-001", "PRD-B-002"]:
            _write_state(self._tmp, _make_state(pid))
        result = self._guardian.list_pipelines()
        ids = {h.pipeline_id for h in result}
        self.assertIn("PRD-A-001", ids)
        self.assertIn("PRD-B-002", ids)

    def test_sorted_most_recent_first(self) -> None:
        _write_state(self._tmp, _make_state("OLD-001", updated_at=_utc_now(-200)))
        _write_state(self._tmp, _make_state("NEW-002", updated_at=_utc_now(-10)))
        result = self._guardian.list_pipelines()
        self.assertEqual(result[0].pipeline_id, "NEW-002")
        self.assertEqual(result[1].pipeline_id, "OLD-001")

    def test_audit_files_excluded(self) -> None:
        """JSONL audit files must not be included in the pipeline list."""
        _write_state(self._tmp, _make_state("PRD-C-003"))
        # Write a fake audit file
        with open(os.path.join(self._tmp, "PRD-C-003-audit.jsonl"), "w") as fh:
            fh.write('{"node_id": "x"}\n')
        result = self._guardian.list_pipelines()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pipeline_id, "PRD-C-003")

    def test_corrupt_files_skipped(self) -> None:
        _write_state(self._tmp, _make_state("VALID-001"))
        corrupt_path = os.path.join(self._tmp, "BAD-002.json")
        with open(corrupt_path, "w") as fh:
            fh.write("invalid json")
        result = self._guardian.list_pipelines()
        # Only the valid pipeline is returned
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].pipeline_id, "VALID-001")


# ---------------------------------------------------------------------------
# RunnerGuardian.get_last_plan()
# ---------------------------------------------------------------------------


class TestRunnerGuardianGetLastPlan(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._guardian = _make_guardian(self._tmp)

    def test_none_when_no_plan(self) -> None:
        state = _make_state("TEST-001", last_plan=None)
        _write_state(self._tmp, state)
        result = self._guardian.get_last_plan("TEST-001")
        self.assertIsNone(result)

    def test_returns_plan_when_present(self) -> None:
        plan = _make_plan(pipeline_id="TEST-002", summary="My test plan")
        state = _make_state("TEST-002", last_plan=plan)
        _write_state(self._tmp, state)
        result = self._guardian.get_last_plan("TEST-002")
        self.assertIsNotNone(result)
        self.assertEqual(result.summary, "My test plan")

    def test_none_for_missing_pipeline(self) -> None:
        result = self._guardian.get_last_plan("NONEXISTENT-001")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# RunnerGuardian.verify_audit_chain()
# ---------------------------------------------------------------------------


class TestRunnerGuardianVerifyChain(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._guardian = _make_guardian(self._tmp)

    def test_no_audit_file_returns_true(self) -> None:
        ok, msg = self._guardian.verify_audit_chain("NO-AUDIT-001")
        self.assertTrue(ok)

    def test_valid_chain_returns_true(self) -> None:
        from cobuilder.engine.anti_gaming import ChainedAuditWriter
        from cobuilder.engine.runner_models import AuditEntry

        audit_path = os.path.join(self._tmp, "PRD-AUDIT-001-audit.jsonl")
        writer = ChainedAuditWriter(audit_path)
        for i in range(3):
            writer.write(AuditEntry(
                node_id=f"n{i}",
                from_status="pending",
                to_status="active",
                agent_id="sess-test",
            ))
        ok, msg = self._guardian.verify_audit_chain("PRD-AUDIT-001")
        self.assertTrue(ok, msg)

    def test_tampered_chain_returns_false(self) -> None:
        from cobuilder.engine.anti_gaming import ChainedAuditWriter
        from cobuilder.engine.runner_models import AuditEntry

        audit_path = os.path.join(self._tmp, "PRD-AUDIT-002-audit.jsonl")
        writer = ChainedAuditWriter(audit_path)
        writer.write(AuditEntry(node_id="n1", from_status="a", to_status="b", agent_id="s"))
        writer.write(AuditEntry(node_id="n2", from_status="b", to_status="c", agent_id="s"))

        # Tamper
        with open(audit_path) as fh:
            lines = fh.readlines()
        data = json.loads(lines[0])
        data["node_id"] = "tampered"
        lines[0] = json.dumps(data) + "\n"
        with open(audit_path, "w") as fh:
            fh.writelines(lines)

        ok, msg = self._guardian.verify_audit_chain("PRD-AUDIT-002")
        self.assertFalse(ok)


# ---------------------------------------------------------------------------
# RunnerGuardian.get_audit_summary() and read_audit_entries()
# ---------------------------------------------------------------------------


class TestRunnerGuardianAuditHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._guardian = _make_guardian(self._tmp)

    def _write_audit(self, pipeline_id: str, count: int) -> str:
        from cobuilder.engine.anti_gaming import ChainedAuditWriter
        from cobuilder.engine.runner_models import AuditEntry

        audit_path = os.path.join(self._tmp, f"{pipeline_id}-audit.jsonl")
        writer = ChainedAuditWriter(audit_path)
        for i in range(count):
            writer.write(AuditEntry(
                node_id=f"n{i}",
                from_status="pending",
                to_status="active",
                agent_id="sess-test",
            ))
        return audit_path

    def test_audit_summary_no_file(self) -> None:
        summary = self._guardian.get_audit_summary("NO-FILE-001")
        self.assertFalse(summary["exists"])
        self.assertEqual(summary["entry_count"], 0)
        self.assertTrue(summary["chain_valid"])

    def test_audit_summary_with_entries(self) -> None:
        self._write_audit("SUMMARY-001", 5)
        summary = self._guardian.get_audit_summary("SUMMARY-001")
        self.assertTrue(summary["exists"])
        self.assertEqual(summary["entry_count"], 5)
        self.assertTrue(summary["chain_valid"])
        self.assertIn("audit_path", summary)

    def test_read_audit_entries_empty(self) -> None:
        entries = self._guardian.read_audit_entries("EMPTY-001")
        self.assertEqual(entries, [])

    def test_read_audit_entries_returns_entries(self) -> None:
        self._write_audit("READ-001", 10)
        entries = self._guardian.read_audit_entries("READ-001")
        self.assertEqual(len(entries), 10)
        self.assertEqual(entries[0]["node_id"], "n0")

    def test_read_audit_entries_tail(self) -> None:
        self._write_audit("READ-002", 20)
        entries = self._guardian.read_audit_entries("READ-002", tail=5)
        self.assertEqual(len(entries), 5)
        # The last 5 should be n15..n19
        node_ids = [e["node_id"] for e in entries]
        self.assertEqual(node_ids[-1], "n19")

    def test_read_audit_entries_tail_less_than_count(self) -> None:
        self._write_audit("READ-003", 3)
        entries = self._guardian.read_audit_entries("READ-003", tail=10)
        self.assertEqual(len(entries), 3)

    def test_read_entries_are_dicts(self) -> None:
        self._write_audit("READ-004", 2)
        entries = self._guardian.read_audit_entries("READ-004")
        for e in entries:
            self.assertIsInstance(e, dict)
            self.assertIn("node_id", e)


if __name__ == "__main__":
    unittest.main(verbosity=2)
