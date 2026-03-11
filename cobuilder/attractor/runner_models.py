"""Pydantic models for the Pipeline Runner Agent structured output.

Defines the typed data models used by the production Pipeline Runner Agent
(pipeline_runner.py) and consumed by the channel adapters and state persistence
layer.

Models:
    NodeAction     - A single action the runner proposes or executes
    BlockedNode    - A node that cannot proceed (with reasons)
    RunnerPlan     - Complete evaluation result for one pipeline cycle
    RunnerState    - Persistent state for crash recovery

These models mirror the JSON schema emitted by the POC runner agent, enabling
full backward compatibility with poc_test_scenarios.py.
"""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

ActionType = Literal[
    "spawn_orchestrator",
    "dispatch_validation",
    "request_approval",
    "transition",
    "signal_stuck",
    "signal_finalize",
    "initialize",
    "sync_parallel",
    "evaluate_condition",
]

StageType = Literal["PARSE", "VALIDATE", "INITIALIZE", "EXECUTE", "FINALIZE"]
PriorityType = Literal["high", "normal", "low"]


# ---------------------------------------------------------------------------
# Core plan models
# ---------------------------------------------------------------------------


class NodeAction(BaseModel):
    """A single action the runner proposes or is executing for a pipeline node.

    Attributes:
        node_id: The node this action targets.
        action: What the runner should do (or is doing) for this node.
        reason: Human-readable explanation of why this action is proposed.
        dependencies_satisfied: List of upstream node IDs whose completion
            justifies proposing this action.
        worker_type: For spawn_orchestrator actions, the type of worker to spawn
            (from the node's worker_type attribute).
        validation_mode: For dispatch_validation actions, the mode to pass to
            validation-test-agent ("technical", "business", or "e2e").
        priority: Relative ordering hint for the runner's execution queue.
    """

    node_id: str
    action: ActionType
    reason: str
    dependencies_satisfied: list[str] = Field(default_factory=list)
    worker_type: str | None = None
    validation_mode: str | None = None
    priority: PriorityType = "normal"


class BlockedNode(BaseModel):
    """A node that cannot currently proceed, with diagnostic information.

    Attributes:
        node_id: The blocked node's identifier.
        reason: Human-readable description of why the node is blocked.
        missing_deps: IDs of upstream nodes that must reach 'validated' first.
    """

    node_id: str
    reason: str
    missing_deps: list[str] = Field(default_factory=list)


class RunnerPlan(BaseModel):
    """Complete pipeline evaluation result for one runner cycle.

    Produced by the agent loop after analyzing pipeline state.
    Contains ordered actions for the runner to execute, blocked nodes for
    reporting, and completion status.

    This model is backward-compatible with the POC runner's JSON output format.

    Attributes:
        pipeline_id: Graph name (from DOT graph_name attribute).
        prd_ref: PRD reference string (from graph prd_ref attribute).
        current_stage: High-level pipeline phase.
        summary: 1-2 sentence description of current state and next steps.
        actions: Ordered list of actions for the runner to execute.
        blocked_nodes: Nodes that cannot proceed (with reasons).
        completed_nodes: Node IDs that are in 'validated' state.
        retry_counts: Per-node retry counters (persisted across plan cycles).
        pipeline_complete: True when exit node is reachable with all deps validated.
    """

    pipeline_id: str
    prd_ref: str = ""
    current_stage: StageType = "EXECUTE"
    summary: str
    actions: list[NodeAction] = Field(default_factory=list)
    blocked_nodes: list[BlockedNode] = Field(default_factory=list)
    completed_nodes: list[str] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    pipeline_complete: bool = False

    def to_agent_json(self) -> dict:
        """Serialize to the JSON format emitted by the agent loop.

        Returns compact dict suitable for JSON serialization and downstream
        consumption by channel adapters.
        """
        return self.model_dump(exclude_none=True)


# ---------------------------------------------------------------------------
# State persistence model
# ---------------------------------------------------------------------------


class RunnerState(BaseModel):
    """Persistent runner state for crash recovery.

    Written to .claude/attractor/state/{pipeline-id}.json after each
    plan cycle. Enables the runner to resume after crash or context compaction
    without losing retry counters, implementer tracking, or paused status.

    Attributes:
        pipeline_id: Matches the DOT graph name.
        pipeline_path: Absolute path to the .dot file.
        session_id: Unique identifier for this runner instance.
        retry_counts: Per-node failure counters.
        implementer_map: Maps node_id → agent_session_id of the worker that
            implemented it. Used to enforce implementer-validator separation.
        last_plan: The most recently produced RunnerPlan (for diagnostics).
        created_at: ISO-8601 timestamp of initial state creation.
        updated_at: ISO-8601 timestamp of most recent state update.
        paused: If True, the runner has been paused by System 3 or a PAUSE intent.
        completed_checkpoint_path: Path to the checkpoint file written when
            pipeline_complete was signaled.
    """

    pipeline_id: str
    pipeline_path: str
    session_id: str
    retry_counts: dict[str, int] = Field(default_factory=dict)
    implementer_map: dict[str, str] = Field(default_factory=dict)
    last_plan: RunnerPlan | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    paused: bool = False
    completed_checkpoint_path: str | None = None

    def touch(self) -> None:
        """Update the updated_at timestamp to now."""
        self.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def increment_retry(self, node_id: str) -> int:
        """Increment the retry counter for a node and return the new count."""
        self.retry_counts[node_id] = self.retry_counts.get(node_id, 0) + 1
        self.touch()
        return self.retry_counts[node_id]

    def reset_retry(self, node_id: str) -> None:
        """Reset the retry counter for a node (after successful validation)."""
        self.retry_counts.pop(node_id, None)
        self.touch()

    def record_implementer(self, node_id: str, agent_session_id: str) -> None:
        """Record which agent session implemented a given node."""
        self.implementer_map[node_id] = agent_session_id
        self.touch()


# ---------------------------------------------------------------------------
# Audit log entry
# ---------------------------------------------------------------------------


class AuditEntry(BaseModel):
    """A single entry in the pipeline audit trail.

    Written to .claude/attractor/state/{pipeline-id}-audit.jsonl as
    newline-delimited JSON. Provides an append-only record of all transitions
    for anti-gaming verification.

    Attributes:
        timestamp: ISO-8601 event timestamp (UTC).
        node_id: The node that transitioned.
        from_status: Previous node status.
        to_status: New node status.
        agent_id: Session ID of the runner or agent responsible.
        evidence_hash: SHA-256 prefix of evidence content (if applicable).
        reason: Human-readable reason for the transition.
        prev_hash: SHA-256 prefix of the previous audit entry's serialised
            JSON (chained checksum). Empty string for the first entry.
    """

    timestamp: str = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    node_id: str
    from_status: str
    to_status: str
    agent_id: str
    evidence_hash: str = ""
    reason: str = ""
    prev_hash: str = ""
