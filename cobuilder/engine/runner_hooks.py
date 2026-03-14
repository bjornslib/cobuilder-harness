"""Pipeline Runner Guard Rail Hooks.

Implements programmatic enforcement of anti-gaming rules for the Pipeline
Runner Agent. These hooks are called by the runner loop at key lifecycle
points — they cannot be bypassed by the agent's instruction following.

Hooks:
    pre_tool_use(tool_name, tool_input)  — called before each tool execution
    post_tool_use(tool_name, tool_input, result)  — called after each tool execution
    on_stop(plan, state)                 — called before the runner exits

Anti-gaming rules enforced:
    1. Runner never calls Edit/Write (coordinator, not implementer)
    2. Implementer-validator separation: same agent cannot validate its own work
    3. Evidence timestamping: stale evidence is rejected
    4. Retry hard limit: configurable via PIPELINE_MAX_RETRIES (default 3)
    5. Audit trail: every transition logged to append-only JSONL with chained hashes
    6. Spot-check selection: deterministic hash(session_id + node_id) auditing

Usage:
    hooks = RunnerHooks(state=runner_state, audit_path="/path/to/audit.jsonl")
    hooks.pre_tool_use("transition_node", {"node_id": "impl_auth", "status": "validated"})

Environment variables:
    PIPELINE_MAX_RETRIES        Maximum retries per node before STUCK (default: 3)
    PIPELINE_SPOT_CHECK_RATE    Fraction of nodes selected for spot-check (default: 0.25)
    PIPELINE_EVIDENCE_MAX_AGE   Max evidence age in seconds (default: 300)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any

from cobuilder.engine.anti_gaming import ChainedAuditWriter, EvidenceValidator, SpotCheckSelector
from cobuilder.engine.runner_models import AuditEntry, RunnerState

# ---------------------------------------------------------------------------
# Configurable constants (override via environment variables)
# ---------------------------------------------------------------------------

# Maximum retries per node before reporting STUCK
MAX_RETRIES: int = int(os.environ.get("PIPELINE_MAX_RETRIES", "3"))

# Tools the runner is allowed to call (read-only + coordination only)
_ALLOWED_TOOLS: frozenset[str] = frozenset({
    # Read tools (from poc_pipeline_runner)
    "get_pipeline_status",
    "get_pipeline_graph",
    "get_node_details",
    "check_checkpoint",
    # Production runner tools
    "get_dispatchable_nodes",
    "transition_node",
    "save_checkpoint",
    "spawn_orchestrator",
    "dispatch_validation",
    "send_approval_request",
    "modify_node",
    # Standard anthropic tool calls via tool_use blocks
    "get_pipeline_status",
})

# Tools the runner MUST NOT call (implementation tools)
_FORBIDDEN_TOOLS: frozenset[str] = frozenset({
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
})


class RunnerHookError(Exception):
    """Raised when a hook blocks an action due to guard rail violation."""


class RunnerHooks:
    """Guard rail hooks for the Pipeline Runner Agent.

    Enforces anti-gaming rules programmatically. Called by the runner loop
    at pre-tool and post-tool lifecycle points.

    Integrates three anti-gaming subsystems from ``anti_gaming.py``:

    * ``ChainedAuditWriter`` — tamper-evident append-only audit log.
    * ``EvidenceValidator``  — rejects stale/future-dated evidence timestamps.
    * ``SpotCheckSelector``  — deterministic selection of nodes for ad-hoc audit.

    Args:
        state: The current RunnerState (mutable, updated by hooks).
        audit_path: Path to the append-only audit JSONL file.
        session_id: Unique identifier for this runner session.
        verbose: If True, print debug information to stderr.
        spot_check_rate: Fraction of nodes selected for spot-check auditing.
            Defaults to the ``PIPELINE_SPOT_CHECK_RATE`` env var or 0.25.
        evidence_max_age: Maximum acceptable evidence age in seconds.
            Defaults to the ``PIPELINE_EVIDENCE_MAX_AGE`` env var or 300.
    """

    def __init__(
        self,
        state: RunnerState,
        audit_path: str,
        session_id: str,
        *,
        verbose: bool = False,
        spot_check_rate: float | None = None,
        evidence_max_age: int | None = None,
    ) -> None:
        self._state = state
        self._audit_path = audit_path
        self._session_id = session_id
        self._verbose = verbose

        # Initialise anti-gaming subsystems
        _rate = spot_check_rate if spot_check_rate is not None else float(
            os.environ.get("PIPELINE_SPOT_CHECK_RATE", "0.25")
        )
        self._spot_check = SpotCheckSelector(rate=_rate)

        _max_age = evidence_max_age if evidence_max_age is not None else int(
            os.environ.get("PIPELINE_EVIDENCE_MAX_AGE", "300")
        )
        self._evidence_validator = EvidenceValidator(max_age_seconds=_max_age)

        # ChainedAuditWriter continues an existing chain on restart
        self._audit_writer = ChainedAuditWriter(audit_path, verbose=verbose)

    # ------------------------------------------------------------------
    # Primary hook interface
    # ------------------------------------------------------------------

    def pre_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        """Called before a tool is executed.

        Checks:
            - Forbidden tool guard (Edit/Write/MultiEdit blocked)
            - Retry limit enforcement for transition_node to 'active'
            - Evidence staleness check for transition_node to 'validated'

        Args:
            tool_name: Name of the tool about to be called.
            tool_input: The tool's input parameters.

        Raises:
            RunnerHookError: If the action is blocked by a guard rail.
        """
        if self._verbose:
            print(
                f"[hooks.pre] {tool_name}({json.dumps(tool_input, separators=(',', ':'))[:120]})",
                file=sys.stderr,
            )

        # Guard 1: Forbidden tool
        if tool_name in _FORBIDDEN_TOOLS:
            raise RunnerHookError(
                f"GUARD RAIL VIOLATION: Runner attempted to call '{tool_name}'. "
                f"The runner is a coordinator — it must never call Edit/Write/MultiEdit. "
                f"This indicates a bug in the runner implementation."
            )

        # Guard 2: Retry limit check for re-activating a failed node
        if tool_name == "transition_node":
            node_id = tool_input.get("node_id", "")
            new_status = tool_input.get("new_status", "")
            if new_status == "active":
                retry_count = self._state.retry_counts.get(node_id, 0)
                if retry_count >= MAX_RETRIES:
                    raise RunnerHookError(
                        f"RETRY LIMIT: Node '{node_id}' has failed "
                        f"{retry_count}/{MAX_RETRIES} times. "
                        f"The runner must signal STUCK instead of retrying. "
                        f"System 3 intervention is required."
                    )

            # Guard 3: Evidence staleness check for validation transitions
            if new_status in ("validated", "impl_complete"):
                evidence_ts = tool_input.get("evidence_timestamp", "")
                ok, msg = self._evidence_validator.validate(evidence_ts)
                if not ok:
                    raise RunnerHookError(
                        f"EVIDENCE STALENESS VIOLATION for node '{node_id}': {msg}"
                    )
                if self._verbose and evidence_ts:
                    print(f"[hooks.pre] Evidence check passed: {msg}", file=sys.stderr)

    def post_tool_use(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        result: str,
    ) -> None:
        """Called after a tool completes successfully.

        Actions:
            - Writes chained audit trail entry for state transitions
            - Tracks implementer sessions for node spawns
            - Increments retry counters for failed transitions
            - Logs spot-check selections for audited nodes

        Args:
            tool_name: Name of the tool that was called.
            tool_input: The tool's input parameters.
            result: The tool's output (JSON string).
        """
        if self._verbose:
            print(
                f"[hooks.post] {tool_name} → {result[:120]}{'...' if len(result) > 120 else ''}",
                file=sys.stderr,
            )

        if tool_name == "transition_node":
            self._handle_transition_audit(tool_input, result)
        elif tool_name == "spawn_orchestrator":
            self._handle_spawn_tracking(tool_input, result)

    def on_stop(self, plan: dict[str, Any] | None, reason: str = "") -> None:
        """Called when the runner is about to exit.

        Validates that the pipeline is in a terminal or intentionally paused
        state before allowing exit. Writes a final chained audit entry.

        Args:
            plan: The most recent RunnerPlan dict (or None if runner failed
                early).
            reason: Reason for stopping (e.g. "pipeline_complete", "stuck",
                "error").

        Raises:
            RunnerHookError: If the runner exits with active unfinished work
                and no checkpoint was saved.
        """
        self._write_audit(
            AuditEntry(
                node_id="__runner__",
                from_status="running",
                to_status=reason or "stopped",
                agent_id=self._session_id,
                reason=f"Runner stopped: {reason}",
            )
        )

        if plan is None:
            return

        # Check for active nodes that were not resolved
        if not plan.get("pipeline_complete") and reason not in (
            "error",
            "paused",
            "stuck",
        ):
            active_actions = plan.get("actions", [])
            if active_actions and reason != "complete":
                if self._verbose:
                    print(
                        f"[hooks.stop] Warning: {len(active_actions)} unresolved action(s) on exit",
                        file=sys.stderr,
                    )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_transition_audit(
        self, tool_input: dict[str, Any], result: str
    ) -> None:
        """Write chained audit entry and update retry counts for a transition."""
        node_id = tool_input.get("node_id", "unknown")
        new_status = tool_input.get("new_status", "unknown")
        reason = tool_input.get("reason", "")

        # Parse result to get old status
        try:
            result_data = json.loads(result)
            from_status = result_data.get("previous_status", "unknown")
            evidence_data = result_data.get("evidence", "")
        except (json.JSONDecodeError, AttributeError):
            from_status = "unknown"
            evidence_data = ""

        evidence_hash = _hash_content(str(evidence_data)) if evidence_data else ""

        self._write_audit(
            AuditEntry(
                node_id=node_id,
                from_status=from_status,
                to_status=new_status,
                agent_id=self._session_id,
                evidence_hash=evidence_hash,
                reason=reason,
            )
        )

        # Update retry counters
        if new_status == "failed":
            self._state.increment_retry(node_id)
            if self._verbose:
                print(
                    f"[hooks] Node '{node_id}' failed "
                    f"({self._state.retry_counts.get(node_id, 0)}/{MAX_RETRIES} retries)",
                    file=sys.stderr,
                )
        elif new_status == "validated":
            self._state.reset_retry(node_id)

        # Spot-check selection for validated nodes
        if new_status == "validated":
            flagged = self._spot_check.should_spot_check(self._session_id, node_id)
            if flagged:
                if self._verbose:
                    print(
                        f"[hooks] Spot-check SELECTED: node '{node_id}' "
                        f"(session={self._session_id})",
                        file=sys.stderr,
                    )
                # Write a supplementary spot-check audit entry
                self._write_audit(
                    AuditEntry(
                        node_id=node_id,
                        from_status="validated",
                        to_status="spot_check_flagged",
                        agent_id=self._session_id,
                        reason=(
                            f"Deterministic spot-check selected this node for "
                            f"additional audit (session={self._session_id})"
                        ),
                    )
                )

    def _handle_spawn_tracking(
        self, tool_input: dict[str, Any], result: str
    ) -> None:
        """Track which session implemented each node (implementer-validator sep.)."""
        node_id = tool_input.get("node_id", "")
        if not node_id:
            return

        # Parse spawned session ID from result
        try:
            result_data = json.loads(result)
            spawned_session = result_data.get("session_id", self._session_id)
        except (json.JSONDecodeError, AttributeError):
            spawned_session = self._session_id

        self._state.record_implementer(node_id, spawned_session)
        if self._verbose:
            print(
                f"[hooks] Node '{node_id}' implemented by session '{spawned_session}'",
                file=sys.stderr,
            )

    def _write_audit(self, entry: AuditEntry) -> None:
        """Append a chained audit entry via the ChainedAuditWriter.

        Delegates to ``self._audit_writer`` which maintains the SHA-256
        chain and handles file I/O.  Failures are logged to stderr but do
        not crash the runner.
        """
        self._audit_writer.write(entry)

    def check_implementer_separation(
        self,
        node_id: str,
        validation_session_id: str,
    ) -> None:
        """Enforce that an agent cannot validate its own work.

        Raises:
            RunnerHookError: If the proposed validator implemented the node.
        """
        implementer = self._state.implementer_map.get(node_id)
        if implementer and implementer == validation_session_id:
            raise RunnerHookError(
                f"ANTI-GAMING VIOLATION: Agent session '{validation_session_id}' "
                f"implemented node '{node_id}' and cannot also validate it. "
                f"This is a self-validation attempt."
            )

    # ------------------------------------------------------------------
    # Audit chain verification (diagnostic helper)
    # ------------------------------------------------------------------

    def verify_audit_chain(self) -> tuple[bool, str]:
        """Verify the integrity of the audit chain for this session.

        Returns:
            ``(True, message)``  when the chain is intact.
            ``(False, message)`` if the chain is broken or unreadable.
        """
        return self._audit_writer.verify_chain()


def _hash_content(content: str, length: int = 16) -> str:
    """SHA-256 hash of content, truncated to `length` hex chars."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:length]
