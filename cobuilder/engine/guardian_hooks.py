"""Pipeline Runner Guardian — System 3 State Reader.

The Guardian is System 3's lightweight monitor for active pipeline runners.
It reads runner state (persisted by the pipeline runner after every cycle)
without spawning a new runner instance.

Responsibilities:
    - Read current RunnerState from ~/.claude/attractor/state/{pipeline-id}.json
    - Read the latest RunnerPlan from state (last_plan field)
    - Verify audit chain integrity for a pipeline
    - Enumerate all active/recent pipeline runner states
    - Provide structured JSON output for System 3 consumption

This module is used by:
    1. ``cli.py guardian`` subcommand — for S3 to check runner status
    2. Programmatic S3 logic — to poll state between cycles
    3. Validation monitors — to detect stuck runners

Design:
    The guardian is READ-ONLY. It never modifies state. It is safe to call
    concurrently with a running runner (state files are written atomically
    by the runner using a write-then-rename pattern).

Usage:
    # CLI:
    python3 cli.py guardian status PRD-AUTH-001
    python3 cli.py guardian list
    python3 cli.py guardian verify-chain PRD-AUTH-001

    # Programmatic:
    guardian = RunnerGuardian()
    status = guardian.get_status("PRD-AUTH-001")
    all_pipelines = guardian.list_pipelines()
    ok, msg = guardian.verify_audit_chain("PRD-AUTH-001")

See PRD-S3-ATTRACTOR-002 Epic 5 for full specification.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from cobuilder.engine.runner_models import RunnerPlan, RunnerState

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default state directory (matches pipeline_runner.py's _STATE_DIR)
_DEFAULT_STATE_DIR: str = os.path.join(
    os.path.expanduser("~"), ".claude", "attractor", "state"
)

# Runner is considered stale if updated_at is older than this many seconds
_STALE_THRESHOLD_SECONDS: int = int(
    os.environ.get("PIPELINE_GUARDIAN_STALE_SECONDS", "300")
)


# ---------------------------------------------------------------------------
# Guardian dataclasses (Pydantic-free for lightweight imports)
# ---------------------------------------------------------------------------


class PipelineHealth:
    """Summary of a single pipeline runner's health."""

    __slots__ = (
        "pipeline_id",
        "pipeline_path",
        "session_id",
        "updated_at",
        "paused",
        "pipeline_complete",
        "retry_counts",
        "last_summary",
        "actions_count",
        "blocked_count",
        "completed_count",
        "age_seconds",
        "is_stale",
        "current_stage",
    )

    def __init__(
        self,
        pipeline_id: str,
        pipeline_path: str,
        session_id: str,
        updated_at: str,
        paused: bool,
        pipeline_complete: bool,
        retry_counts: dict[str, int],
        last_summary: str,
        actions_count: int,
        blocked_count: int,
        completed_count: int,
        age_seconds: float,
        is_stale: bool,
        current_stage: str,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.pipeline_path = pipeline_path
        self.session_id = session_id
        self.updated_at = updated_at
        self.paused = paused
        self.pipeline_complete = pipeline_complete
        self.retry_counts = retry_counts
        self.last_summary = last_summary
        self.actions_count = actions_count
        self.blocked_count = blocked_count
        self.completed_count = completed_count
        self.age_seconds = age_seconds
        self.is_stale = is_stale
        self.current_stage = current_stage

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "pipeline_id": self.pipeline_id,
            "pipeline_path": self.pipeline_path,
            "session_id": self.session_id,
            "updated_at": self.updated_at,
            "paused": self.paused,
            "pipeline_complete": self.pipeline_complete,
            "retry_counts": self.retry_counts,
            "last_summary": self.last_summary,
            "actions_count": self.actions_count,
            "blocked_count": self.blocked_count,
            "completed_count": self.completed_count,
            "age_seconds": round(self.age_seconds, 1),
            "is_stale": self.is_stale,
            "current_stage": self.current_stage,
            "overall_health": self._overall_health(),
        }

    def _overall_health(self) -> str:
        """Derive an overall health label from the state fields."""
        if self.pipeline_complete:
            return "complete"
        if self.paused:
            return "paused"
        if self.is_stale:
            return "stale"
        if self.blocked_count > 0 and self.actions_count == 0:
            return "stuck"
        if any(v >= 2 for v in self.retry_counts.values()):
            return "warning"
        return "healthy"


# ---------------------------------------------------------------------------
# RunnerGuardian
# ---------------------------------------------------------------------------


class RunnerGuardian:
    """Read-only monitor for active Pipeline Runner instances.

    Reads persisted RunnerState files from the state directory without
    modifying them. Safe to call concurrently with a running runner.

    Args:
        state_dir: Directory containing runner state JSON files.
            Defaults to ``~/.claude/attractor/state/``.
        stale_threshold_seconds: Seconds since last update before a runner
            is considered stale. Defaults to the
            ``PIPELINE_GUARDIAN_STALE_SECONDS`` env var or 300.

    Example::

        guardian = RunnerGuardian()

        # Check a specific pipeline
        health = guardian.get_status("PRD-AUTH-001")
        if health.is_stale:
            print("Runner may be stuck — consider re-launching")

        # List all pipelines
        for health in guardian.list_pipelines():
            print(f"{health.pipeline_id}: {health._overall_health()}")

        # Verify audit integrity
        ok, msg = guardian.verify_audit_chain("PRD-AUTH-001")
    """

    def __init__(
        self,
        state_dir: str = _DEFAULT_STATE_DIR,
        stale_threshold_seconds: int = _STALE_THRESHOLD_SECONDS,
    ) -> None:
        self._state_dir = state_dir
        self._stale_threshold = stale_threshold_seconds

    # -----------------------------------------------------------------------
    # Primary API
    # -----------------------------------------------------------------------

    def get_status(self, pipeline_id: str) -> PipelineHealth | None:
        """Return the health summary for a specific pipeline runner.

        Reads the state JSON for ``pipeline_id`` and produces a
        ``PipelineHealth`` with derived fields (age, staleness, health label).

        Args:
            pipeline_id: The pipeline identifier (DOT graph name), e.g.,
                ``"PRD-AUTH-001"``.

        Returns:
            ``PipelineHealth`` if the state file exists, ``None`` otherwise.
        """
        state = self._load_state(pipeline_id)
        if state is None:
            return None
        return self._to_health(state)

    def list_pipelines(self) -> list[PipelineHealth]:
        """Return health summaries for all known pipeline runners.

        Scans the state directory for ``*.json`` files (excluding audit logs).

        Returns:
            List of ``PipelineHealth`` objects, sorted by ``updated_at``
            descending (most recently active first).
        """
        if not os.path.isdir(self._state_dir):
            return []

        results: list[PipelineHealth] = []
        try:
            filenames = os.listdir(self._state_dir)
        except OSError:
            return []

        for fname in filenames:
            if not fname.endswith(".json") or fname.endswith("-audit.jsonl"):
                continue
            pipeline_id = fname[: -len(".json")]
            health = self.get_status(pipeline_id)
            if health is not None:
                results.append(health)

        # Sort by updated_at descending
        results.sort(key=lambda h: h.updated_at, reverse=True)
        return results

    def get_last_plan(self, pipeline_id: str) -> RunnerPlan | None:
        """Return the last RunnerPlan for a pipeline, or None.

        Args:
            pipeline_id: The pipeline identifier.

        Returns:
            The most recently persisted ``RunnerPlan``, or ``None`` if the
            state file does not exist or has no last_plan.
        """
        state = self._load_state(pipeline_id)
        if state is None:
            return None
        return state.last_plan

    def verify_audit_chain(self, pipeline_id: str) -> tuple[bool, str]:
        """Verify the integrity of the audit chain for a pipeline.

        Delegates to ``ChainedAuditWriter.verify_chain()`` on the pipeline's
        audit JSONL file.

        Args:
            pipeline_id: The pipeline identifier.

        Returns:
            ``(True, message)`` when the chain is intact or the file is absent.
            ``(False, message)`` if a tamper or parse error is found.
        """
        # Import here to avoid circular imports at module load
        from cobuilder.engine.anti_gaming import ChainedAuditWriter

        audit_path = self._audit_path(pipeline_id)
        writer = ChainedAuditWriter(audit_path)
        return writer.verify_chain()

    def get_audit_summary(self, pipeline_id: str) -> dict[str, Any]:
        """Return a summary of the audit trail for a pipeline.

        Args:
            pipeline_id: The pipeline identifier.

        Returns:
            Dict with:
                ``exists``: bool — whether the audit file exists.
                ``entry_count``: int — number of entries.
                ``chain_valid``: bool — True if chain is intact.
                ``chain_message``: str — verification message.
                ``audit_path``: str — path to the audit JSONL.
        """
        from cobuilder.engine.anti_gaming import ChainedAuditWriter

        audit_path = self._audit_path(pipeline_id)
        writer = ChainedAuditWriter(audit_path)
        chain_valid, chain_msg = writer.verify_chain()
        return {
            "exists": os.path.exists(audit_path),
            "entry_count": writer.entry_count(),
            "chain_valid": chain_valid,
            "chain_message": chain_msg,
            "audit_path": audit_path,
        }

    def read_audit_entries(
        self, pipeline_id: str, tail: int = 20
    ) -> list[dict[str, Any]]:
        """Read the last N audit entries for a pipeline.

        Args:
            pipeline_id: The pipeline identifier.
            tail: Maximum number of entries to return (from the end).
                Default 20.

        Returns:
            List of audit entry dicts (most recent last).
        """
        audit_path = self._audit_path(pipeline_id)
        if not os.path.exists(audit_path):
            return []
        entries: list[dict[str, Any]] = []
        try:
            with open(audit_path, encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped:
                        try:
                            entries.append(json.loads(stripped))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            return []
        return entries[-tail:] if len(entries) > tail else entries

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _state_path(self, pipeline_id: str) -> str:
        """Absolute path to the state JSON for a pipeline."""
        return os.path.join(self._state_dir, f"{pipeline_id}.json")

    def _audit_path(self, pipeline_id: str) -> str:
        """Absolute path to the audit JSONL for a pipeline."""
        return os.path.join(self._state_dir, f"{pipeline_id}-audit.jsonl")

    def _load_state(self, pipeline_id: str) -> RunnerState | None:
        """Read and parse a RunnerState from disk.

        Returns None if the file does not exist or cannot be parsed.
        """
        path = self._state_path(pipeline_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            return RunnerState.model_validate(data)
        except (OSError, ValueError, Exception):
            return None

    def _to_health(self, state: RunnerState) -> PipelineHealth:
        """Convert a RunnerState to a PipelineHealth summary."""
        plan = state.last_plan

        # Compute age from updated_at
        age_seconds = 0.0
        try:
            updated = datetime.fromisoformat(
                state.updated_at.replace("Z", "+00:00")
            )
            age_seconds = (datetime.now(timezone.utc) - updated).total_seconds()
        except (ValueError, TypeError):
            pass

        is_stale = age_seconds > self._stale_threshold

        if plan is not None:
            actions_count = len(plan.actions)
            blocked_count = len(plan.blocked_nodes)
            completed_count = len(plan.completed_nodes)
            last_summary = plan.summary
            pipeline_complete = plan.pipeline_complete
            current_stage = plan.current_stage
        else:
            actions_count = 0
            blocked_count = 0
            completed_count = 0
            last_summary = ""
            pipeline_complete = state.completed_checkpoint_path is not None
            current_stage = "INITIALIZE"

        return PipelineHealth(
            pipeline_id=state.pipeline_id,
            pipeline_path=state.pipeline_path,
            session_id=state.session_id,
            updated_at=state.updated_at,
            paused=state.paused,
            pipeline_complete=pipeline_complete,
            retry_counts=dict(state.retry_counts),
            last_summary=last_summary,
            actions_count=actions_count,
            blocked_count=blocked_count,
            completed_count=completed_count,
            age_seconds=age_seconds,
            is_stale=is_stale,
            current_stage=current_stage,
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the guardian subcommand.

    Usage::

        cli.py guardian status <pipeline-id> [--json]
        cli.py guardian list [--json]
        cli.py guardian verify-chain <pipeline-id>
        cli.py guardian audit <pipeline-id> [--tail=20]
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="attractor guardian",
        description="System 3 state monitor for Pipeline Runner instances.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    # status
    p_status = sub.add_parser("status", help="Show health of one pipeline runner")
    p_status.add_argument("pipeline_id", help="Pipeline identifier (e.g., PRD-AUTH-001)")
    p_status.add_argument("--json", dest="as_json", action="store_true")
    p_status.add_argument("--state-dir", default=_DEFAULT_STATE_DIR)

    # list
    p_list = sub.add_parser("list", help="List all known pipeline runners")
    p_list.add_argument("--json", dest="as_json", action="store_true")
    p_list.add_argument("--state-dir", default=_DEFAULT_STATE_DIR)

    # verify-chain
    p_verify = sub.add_parser("verify-chain", help="Verify audit chain integrity")
    p_verify.add_argument("pipeline_id")
    p_verify.add_argument("--state-dir", default=_DEFAULT_STATE_DIR)

    # audit
    p_audit = sub.add_parser("audit", help="Show recent audit entries")
    p_audit.add_argument("pipeline_id")
    p_audit.add_argument("--tail", type=int, default=20)
    p_audit.add_argument("--json", dest="as_json", action="store_true")
    p_audit.add_argument("--state-dir", default=_DEFAULT_STATE_DIR)

    args = parser.parse_args()
    guardian = RunnerGuardian(state_dir=getattr(args, "state_dir", _DEFAULT_STATE_DIR))

    if args.action == "status":
        health = guardian.get_status(args.pipeline_id)
        if health is None:
            print(f"No state found for pipeline: {args.pipeline_id}", file=sys.stderr)
            sys.exit(1)
        if args.as_json:
            print(json.dumps(health.to_dict(), indent=2))
        else:
            d = health.to_dict()
            _print_health(d)

    elif args.action == "list":
        healths = guardian.list_pipelines()
        if args.as_json:
            print(json.dumps([h.to_dict() for h in healths], indent=2))
        else:
            if not healths:
                print("No pipeline runners found.")
            else:
                print(f"{'PIPELINE':<30} {'STAGE':<12} {'HEALTH':<10} {'AGE':>8}s")
                print("-" * 65)
                for h in healths:
                    d = h.to_dict()
                    print(
                        f"{d['pipeline_id']:<30} {d['current_stage']:<12} "
                        f"{d['overall_health']:<10} {d['age_seconds']:>8.0f}"
                    )

    elif args.action == "verify-chain":
        ok, msg = guardian.verify_audit_chain(args.pipeline_id)
        print(f"{'✅' if ok else '❌'} {msg}")
        sys.exit(0 if ok else 1)

    elif args.action == "audit":
        entries = guardian.read_audit_entries(args.pipeline_id, tail=args.tail)
        if args.as_json:
            print(json.dumps(entries, indent=2))
        else:
            if not entries:
                print(f"No audit entries for pipeline: {args.pipeline_id}")
            else:
                print(f"{'TIMESTAMP':<27} {'NODE':<25} {'FROM':<15} {'TO':<15}")
                print("-" * 85)
                for e in entries:
                    ts = e.get("timestamp", "")[:26]
                    node = e.get("node_id", "?")[:24]
                    frm = e.get("from_status", "?")[:14]
                    to = e.get("to_status", "?")[:14]
                    print(f"{ts:<27} {node:<25} {frm:<15} {to:<15}")


def _print_health(d: dict[str, Any]) -> None:
    """Pretty-print a PipelineHealth dict."""
    print(f"Pipeline:   {d['pipeline_id']}")
    print(f"Session:    {d['session_id']}")
    print(f"Stage:      {d['current_stage']}")
    print(f"Health:     {d['overall_health']}")
    print(f"Updated:    {d['updated_at']}")
    print(f"Age:        {d['age_seconds']:.0f}s")
    print(f"Paused:     {d['paused']}")
    print(f"Complete:   {d['pipeline_complete']}")
    print(f"Actions:    {d['actions_count']}")
    print(f"Blocked:    {d['blocked_count']}")
    print(f"Completed:  {d['completed_count']}")
    if d.get("retry_counts"):
        print(f"Retries:    {d['retry_counts']}")
    if d.get("last_summary"):
        print(f"Summary:    {d['last_summary']}")
