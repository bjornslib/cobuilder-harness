"""Loop detection and retry policy for the Attractor pipeline engine.

Per-node visit counting and pipeline-wide execution counter. AMD-6 simplified
design — no subsequence pattern detection.

Built-in context keys written by sync_to_context():
    $node_visits.<node_id>   int  — visit count for each node
    $retry_count             int  — 0-indexed retry count for most recently checked node

All methods are synchronous — visit counting is not I/O bound.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Literal

from cobuilder.engine.context import PipelineContext

if TYPE_CHECKING:
    from cobuilder.engine.graph import Graph, Node


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class VisitRecord:
    """Per-node visit tracking. One record per unique node_id per pipeline run.

    Stored in PipelineContext under ``$node_visits.<node_id>``.
    Serialized into checkpoint.json under the key ``"visit_records"``.
    """

    node_id: str
    count: int = 0
    first_visit_ts: float = 0.0  # Unix timestamp of first execution
    last_visit_ts: float = 0.0   # Unix timestamp of most recent execution
    outcomes: list[str] = field(default_factory=list)  # status per visit


@dataclass
class LoopDetectionResult:
    """Result of a loop check for a single node execution.

    Returned by ``LoopDetector.check()`` before every edge selection.
    """

    node_id: str
    visit_count: int  # count AFTER incrementing (1-indexed)
    allowed: bool     # True → proceed; False → escalate
    reason: Literal[
        "ok",
        "per_node_limit_exceeded",
        "pipeline_limit_exceeded",
        "repeating_pattern_detected",
    ]
    pattern: list[str] | None = None  # node IDs forming detected pattern, if any
    limit: int | None = None          # which limit was exceeded


@dataclass
class LoopPolicy:
    """Resolved from graph and node attributes. Passed to LoopDetector.

    AMD-6: ``pattern_window`` and ``pattern_min_length`` REMOVED —
    subsequence detection dropped. Only per-node and pipeline-wide counters.
    """

    per_node_max: int = 4   # default 4 (initial + 3 retries)
    pipeline_max: int = 50  # default 50


# ---------------------------------------------------------------------------
# LoopDetector
# ---------------------------------------------------------------------------


class LoopDetector:
    """Tracks per-node visit counts and detects looping execution patterns.

    Instantiated once per pipeline run. State persisted in checkpoint via
    ``serialize()`` / ``from_checkpoint()``. Context kept in sync via
    ``sync_to_context()`` after every check.

    All methods are synchronous — visit counting is not I/O bound.
    """

    def __init__(self, policy: LoopPolicy) -> None:
        self._policy = policy
        self._visit_records: dict[str, VisitRecord] = {}
        self._execution_history: list[str] = []  # ordered node IDs, full history
        self._total_executions: int = 0

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def check(
        self,
        node_id: str,
        node_max_retries: int | None = None,  # from node attribute, overrides policy.per_node_max
        outcome_status: str | None = None,    # if re-entering after prior outcome
        ts: float | None = None,              # Unix timestamp; defaults to time.time()
    ) -> LoopDetectionResult:
        """Increment visit count for *node_id* and return a LoopDetectionResult.

        Call this AFTER the node executes (so visit count reflects completed runs).
        Call BEFORE edge selection (so loop escalation can short-circuit routing).

        Pipeline limit is checked first; per-node limit second.
        """
        now = ts if ts is not None else time.time()

        # Create or update VisitRecord
        if node_id not in self._visit_records:
            self._visit_records[node_id] = VisitRecord(
                node_id=node_id,
                count=0,
                first_visit_ts=now,
                last_visit_ts=now,
            )

        record = self._visit_records[node_id]
        record.count += 1
        record.last_visit_ts = now
        if outcome_status is not None:
            record.outcomes.append(outcome_status)

        # Update pipeline-wide state
        self._execution_history.append(node_id)
        self._total_executions += 1

        visit_count = record.count

        # Effective per-node limit: node_max_retries + 1 if provided, else policy
        if node_max_retries is not None:
            effective_limit = node_max_retries + 1
        else:
            effective_limit = self._policy.per_node_max

        # Check pipeline limit first
        if self._total_executions > self._policy.pipeline_max:
            return LoopDetectionResult(
                node_id=node_id,
                visit_count=visit_count,
                allowed=False,
                reason="pipeline_limit_exceeded",
                limit=self._policy.pipeline_max,
            )

        # Check per-node limit
        if visit_count > effective_limit:
            return LoopDetectionResult(
                node_id=node_id,
                visit_count=visit_count,
                allowed=False,
                reason="per_node_limit_exceeded",
                limit=effective_limit,
            )

        return LoopDetectionResult(
            node_id=node_id,
            visit_count=visit_count,
            allowed=True,
            reason="ok",
            limit=None,
        )

    # ------------------------------------------------------------------
    # Context sync (AMD-4: WITH $ prefix)
    # ------------------------------------------------------------------

    def sync_to_context(self, context: PipelineContext) -> None:
        """Write current visit counts into context.

        Writes ``$node_visits.<node_id>`` for each VisitRecord so condition
        expressions can read them.

        Also writes ``$retry_count`` (0-indexed) for the most recently
        checked node (last entry in ``_execution_history``).

        AMD-4: Keys stored WITH ``$`` prefix to match PipelineContext convention.
        """
        updates: dict = {}

        for node_id, record in self._visit_records.items():
            updates[f"$node_visits.{node_id}"] = record.count

        # $retry_count for the most recently checked node (0-indexed = count - 1)
        if self._execution_history:
            last_node = self._execution_history[-1]
            last_count = self._visit_records[last_node].count
            updates["$retry_count"] = last_count - 1

        context.update(updates)

    # ------------------------------------------------------------------
    # Serialization (checkpoint support)
    # ------------------------------------------------------------------

    def serialize(self) -> dict:
        """Return JSON-serializable dict for checkpoint inclusion."""
        return {
            "visit_records": {
                nid: asdict(vr) for nid, vr in self._visit_records.items()
            },
            "total_executions": self._total_executions,
            "execution_history": list(self._execution_history),
        }

    @classmethod
    def from_checkpoint(cls, data: dict, policy: LoopPolicy) -> "LoopDetector":
        """Restore state from checkpoint dict. Used during ``--resume``.

        Args:
            data:   Dict previously returned by ``serialize()``.
            policy: LoopPolicy to apply going forward.

        Returns:
            A LoopDetector with restored state.
        """
        detector = cls(policy)
        for nid, vr_data in data.get("visit_records", {}).items():
            detector._visit_records[nid] = VisitRecord(
                node_id=vr_data["node_id"],
                count=vr_data["count"],
                first_visit_ts=vr_data["first_visit_ts"],
                last_visit_ts=vr_data["last_visit_ts"],
                outcomes=list(vr_data.get("outcomes", [])),
            )
        detector._total_executions = data.get("total_executions", 0)
        detector._execution_history = list(data.get("execution_history", []))
        return detector


# ---------------------------------------------------------------------------
# Policy resolver
# ---------------------------------------------------------------------------


def resolve_retry_target(
    failed_node: "Node",
    graph: "Graph",
) -> str | None:
    """Return the node_id to retry from, or None if no retry target exists.

    Resolution order (first non-None/non-empty wins):
      1. ``failed_node.attrs.get("retry_target")``     — node-level attribute
      2. ``graph.attrs.get("retry_target")``            — graph-level attribute
      3. ``graph.attrs.get("fallback_retry_target")``   — last-resort graph attribute
      4. ``None`` → pipeline FAILS with NoRetryTargetError

    The caller is responsible for raising ``NoRetryTargetError`` when None
    is returned and the pipeline cannot continue.
    """
    return (
        failed_node.attrs.get("retry_target") or
        graph.attrs.get("retry_target") or
        graph.attrs.get("fallback_retry_target") or
        None
    )


def apply_loop_restart(
    context: "PipelineContext",
    graph: "Graph",
) -> "PipelineContext":
    """Clear all context keys except preserved ones, returning a new PipelineContext.

    Preserved keys:
    - Keys starting with ``"graph."`` (graph-level variables)
    - Keys starting with ``"pipeline_"`` (built-in immutable pipeline keys)
    - The legacy key ``"$node_visits"`` (if present as a top-level dict)
    - Keys starting with ``"$node_visits."`` (per-node visit counts with AMD-4 prefix)

    Visit counts are NOT reset — a ``loop_restart`` edge does not grant a fresh
    retry budget; it resets accumulated state only so loop detection still works.

    Returns a fresh ``PipelineContext`` with only the preserved keys.
    Does NOT modify the original context.
    """
    preserved_prefixes = ("graph.", "pipeline_")
    snapshot = context.snapshot()
    new_context = {
        k: v for k, v in snapshot.items()
        if (
            any(k.startswith(p) for p in preserved_prefixes)
            or k == "$node_visits"
            or k.startswith("$node_visits.")
        )
    }
    return PipelineContext(new_context)


def resolve_loop_policy(
    graph: "Graph",
    node: "Node | None" = None,
) -> LoopPolicy:
    """Resolve a LoopPolicy from graph and node attributes.

    Resolution:
    - ``pipeline_max``: graph's ``default_max_retry`` attribute (default 50)
    - ``per_node_max``: node's ``max_retries`` + 1 if node provided,
                        else policy default 4 (initial + 3 retries)

    Args:
        graph: The parsed pipeline graph.
        node:  Optional node for per-node override. If None, uses default.

    Returns:
        A resolved LoopPolicy.
    """
    pipeline_max = int(graph.attrs.get("default_max_retry", 50))

    if node is not None:
        per_node_max = int(node.attrs.get("max_retries", 3)) + 1
    else:
        per_node_max = 4  # initial + 3 retries

    return LoopPolicy(per_node_max=per_node_max, pipeline_max=pipeline_max)
