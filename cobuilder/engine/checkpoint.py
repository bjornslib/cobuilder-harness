"""Checkpoint/resume system for the Attractor pipeline engine.

This module provides:
- ``NodeRecord``        — Pydantic model for a single completed node's execution record
- ``EngineCheckpoint``  — Full resumable state, written atomically after every node
- ``CheckpointManager`` — Reads and writes checkpoints; creates the run directory structure

Design invariants (from SD Section 12):
1. The engine never writes to the DOT file — only to the run directory.
2. ``CheckpointManager.save()`` must be called BEFORE advancing ``current_node_id``.
3. ``save()`` uses write-to-tmp-then-rename for atomic semantics.
4. ``save()`` catches ``OSError`` and logs but does NOT crash the engine — a lost
   checkpoint is recoverable on the next successful save; a crash is not.
5. ``load_or_create()`` raises ``CheckpointVersionError`` on schema mismatch
   and ``CheckpointGraphMismatchError`` if the DOT file has changed between runs.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, Field

from cobuilder.engine.exceptions import CheckpointVersionError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Version constant
# ──────────────────────────────────────────────────────────────────────────────

ENGINE_CHECKPOINT_VERSION = "1.0.0"


# ──────────────────────────────────────────────────────────────────────────────
# Additional exception (graph mismatch is checkpoint-specific)
# ──────────────────────────────────────────────────────────────────────────────

class CheckpointGraphMismatchError(Exception):
    """The DOT file changed between the original run and a ``--resume`` attempt.

    The engine detected that the set of node IDs in the current DOT file does
    not match the ``completed_nodes`` list in the existing checkpoint.  This is
    a safety guard — silently re-executing nodes that no longer exist would
    produce nonsensical results.

    Recovery: delete the run directory and restart from scratch.

    Attributes:
        checkpoint_path: Path to the mismatched checkpoint file.
        missing_nodes:   Node IDs present in checkpoint but absent from the graph.
        extra_nodes:     Node IDs present in the graph but absent from the checkpoint.
    """

    def __init__(
        self,
        checkpoint_path: str,
        missing_nodes: list[str],
        extra_nodes: list[str],
    ) -> None:
        self.checkpoint_path = checkpoint_path
        self.missing_nodes = missing_nodes
        self.extra_nodes = extra_nodes
        details = []
        if missing_nodes:
            details.append(f"nodes in checkpoint but not in graph: {missing_nodes}")
        if extra_nodes:
            details.append(f"nodes in graph but not in checkpoint: {extra_nodes}")
        super().__init__(
            f"DOT file changed since checkpoint was written at '{checkpoint_path}'. "
            f"{'; '.join(details)}. "
            "Delete the run directory and restart: rm -rf <run_dir>"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ──────────────────────────────────────────────────────────────────────────────

class NodeRecord(BaseModel):
    """Record of a single completed node execution.

    Written into ``EngineCheckpoint.node_records`` after each handler returns.
    Provides an immutable audit log of the full pipeline run.
    """

    node_id: str
    handler_type: str
    status: str                                   # OutcomeStatus.value
    context_updates: dict[str, Any] = Field(default_factory=dict)
    preferred_label: str | None = None
    suggested_next: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    completed_at: datetime


class EngineCheckpoint(BaseModel):
    """Full resumable state of a pipeline run.

    This is the single source of truth for crash recovery.
    Written atomically (via ``CheckpointManager.save()``) after every node
    execution so that ``--resume`` can skip all ``completed_nodes`` and pick
    up from ``current_node_id``.

    Schema version bumps are rejected by ``CheckpointManager.load_or_create()``
    to prevent silent state corruption between incompatible engine versions.
    """

    schema_version: str = ENGINE_CHECKPOINT_VERSION

    # ── Pipeline identity ──────────────────────────────────────────────────
    pipeline_id: str            # DOT file base name (without extension)
    dot_path: str               # Absolute path to source DOT file (read-only input)
    run_dir: str                # Absolute path to the run directory

    # ── Timing ────────────────────────────────────────────────────────────
    started_at: datetime
    last_updated_at: datetime

    # ── Execution state ────────────────────────────────────────────────────
    completed_nodes: list[str] = Field(default_factory=list)  # Node IDs in order
    node_records: list[NodeRecord] = Field(default_factory=list)
    current_node_id: str | None = None   # None = not yet started
    last_edge_id: str | None = None      # Edge taken to reach current_node_id

    # ── Accumulated context ────────────────────────────────────────────────
    context: dict[str, Any] = Field(default_factory=dict)

    # ── Visit counts ───────────────────────────────────────────────────────
    # Duplicated from context.$node_visits.<id> for explicit schema clarity
    # and resume validation.
    visit_counts: dict[str, int] = Field(default_factory=dict)

    # ── Pipeline-wide counters ─────────────────────────────────────────────
    total_node_executions: int = 0    # For pipeline-wide loop detection (Epic 5)
    total_tokens_used: int = 0        # Aggregated from CodergenHandler metadata

    # ── Epic 5: LoopDetector state ─────────────────────────────────────────
    # Serialized LoopDetector state for checkpoint/resume support.
    # None means Epic 5 is not active (no LoopDetector was instantiated).
    visit_records_data: dict | None = Field(default=None)


# ──────────────────────────────────────────────────────────────────────────────
# CheckpointManager
# ──────────────────────────────────────────────────────────────────────────────

class CheckpointManager:
    """Creates, reads, and atomically writes ``EngineCheckpoint`` files.

    Directory structure managed by this class (see SD Section 4.6):

    .. code-block:: text

        .claude/attractor/pipelines/
          <pipeline_id>-run-<timestamp>/     ← run_dir
            checkpoint.json                  ← atomic write target
            checkpoint.json.tmp              ← temporary write (deleted after rename)
            manifest.json                    ← immutable run metadata (written once)
            nodes/                           ← per-node artefacts (CodergenHandler)
              <node_id>/
                prompt.md
                response.md
                status.json
                audit.jsonl

    Args:
        run_dir: Path to the run directory.  Created by ``CheckpointManager``
                 if it does not exist.
    """

    CHECKPOINT_FILENAME = "checkpoint.json"
    CHECKPOINT_TMP_FILENAME = "checkpoint.json.tmp"
    MANIFEST_FILENAME = "manifest.json"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.checkpoint_path = self.run_dir / self.CHECKPOINT_FILENAME
        self._tmp_path = self.run_dir / self.CHECKPOINT_TMP_FILENAME

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    def create_run_dir(
        cls,
        pipelines_dir: Path,
        pipeline_id: str,
        timestamp: str | None = None,
    ) -> "CheckpointManager":
        """Create a new run directory and return a ``CheckpointManager`` for it.

        Args:
            pipelines_dir: Parent directory (e.g. ``.claude/attractor/pipelines/``).
            pipeline_id:   DOT file base name (no extension).
            timestamp:     ISO-8601 timestamp suffix; defaults to now (UTC).

        Returns:
            A ``CheckpointManager`` pointing at the newly created run directory.
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = Path(pipelines_dir) / f"{pipeline_id}-run-{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "nodes").mkdir(exist_ok=True)
        return cls(run_dir)

    # ── load_or_create ─────────────────────────────────────────────────────

    def load_or_create(
        self,
        pipeline_id: str,
        dot_path: str,
        graph_node_ids: list[str] | None = None,
    ) -> EngineCheckpoint:
        """Return an existing ``EngineCheckpoint`` or create a fresh one.

        If ``checkpoint.json`` exists in ``run_dir``:
        - Validates ``schema_version`` — raises ``CheckpointVersionError`` on mismatch.
        - Optionally validates that ``completed_nodes`` are a subset of the current
          graph nodes (raises ``CheckpointGraphMismatchError`` if the DOT file
          changed between runs).
        - Returns the loaded checkpoint for resume.

        If no checkpoint exists:
        - Creates a fresh ``EngineCheckpoint`` and writes ``manifest.json``.
        - Returns the fresh checkpoint (caller must call ``save()`` after each node).

        Args:
            pipeline_id:     DOT file base name (no extension).
            dot_path:        Absolute path to the source DOT file.
            graph_node_ids:  All node IDs in the current graph.  When provided,
                             the manager validates the checkpoint against them to
                             detect DOT-file modifications between runs.

        Returns:
            An ``EngineCheckpoint`` instance (loaded or freshly created).

        Raises:
            CheckpointVersionError:      ``schema_version`` mismatch.
            CheckpointGraphMismatchError: DOT file changed between runs.
        """
        if self.checkpoint_path.exists():
            return self._load_and_validate(dot_path, graph_node_ids)

        # ── Fresh start ────────────────────────────────────────────────────
        now = datetime.now(timezone.utc)
        checkpoint = EngineCheckpoint(
            pipeline_id=pipeline_id,
            dot_path=dot_path,
            run_dir=str(self.run_dir),
            started_at=now,
            last_updated_at=now,
        )
        self._write_manifest(pipeline_id, dot_path, now)
        return checkpoint

    # ── save ───────────────────────────────────────────────────────────────

    def save(self, checkpoint: EngineCheckpoint, emitter: Any = None) -> None:
        """Atomically persist *checkpoint* to ``checkpoint.json``.

        Uses write-to-tmp-then-rename pattern for crash safety.  If the rename
        fails (e.g. full disk), the error is logged but **not** re-raised — a
        lost checkpoint is recoverable on the next successful save; a crash
        from a raised exception is not (SD Section 11 risk table).

        The ``last_updated_at`` field is refreshed to the current UTC time
        before writing so that the file always reflects when it was last written.

        After a successful atomic write, emits a ``checkpoint.saved`` event via
        *emitter* if provided.  The emit call is fire-and-forget (errors are
        logged, not raised) to preserve the non-fatal guarantee.

        Args:
            checkpoint: The ``EngineCheckpoint`` to persist.
            emitter:    Optional EventEmitter.  When provided, a
                        ``checkpoint.saved`` event is emitted after the atomic
                        write succeeds.  ``None`` disables event emission (Epic 1
                        behaviour).
        """
        # Refresh timestamp
        updated = checkpoint.model_copy(
            update={"last_updated_at": datetime.now(timezone.utc)}
        )

        write_succeeded = False
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            payload = updated.model_dump_json(indent=2)
            self._tmp_path.write_text(payload, encoding="utf-8")
            # Atomic rename (POSIX guarantees atomicity on same filesystem)
            os.replace(self._tmp_path, self.checkpoint_path)
            write_succeeded = True
            logger.debug(
                "Checkpoint saved: node=%s completed=%d",
                updated.current_node_id,
                len(updated.completed_nodes),
            )
        except OSError as exc:
            logger.error(
                "Checkpoint write failed (non-fatal): %s — pipeline will continue "
                "but crash recovery may not be available until the next successful save.",
                exc,
            )
            # Clean up tmp if it exists
            try:
                self._tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

        # Emit checkpoint.saved event if write succeeded and emitter is present.
        if write_succeeded and emitter is not None:
            import asyncio
            try:
                from cobuilder.engine.events.types import EventBuilder
                event = EventBuilder.checkpoint_saved(
                    pipeline_id=updated.pipeline_id,
                    node_id=updated.current_node_id or "",
                    checkpoint_path=str(self.checkpoint_path),
                )
                # Emit is async; schedule it if an event loop is running.
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(emitter.emit(event))
                    else:
                        loop.run_until_complete(emitter.emit(event))
                except RuntimeError:
                    # No event loop available — skip emission.
                    pass
            except Exception as emit_exc:
                logger.warning(
                    "checkpoint.saved emit failed (non-fatal): %s", emit_exc
                )

    # ── Internal helpers ────────────────────────────────────────────────────

    def _load_and_validate(
        self,
        dot_path: str,
        graph_node_ids: list[str] | None,
    ) -> EngineCheckpoint:
        """Load ``checkpoint.json``, validate version and graph consistency."""
        raw = self.checkpoint_path.read_text(encoding="utf-8")
        data = json.loads(raw)

        found_version = data.get("schema_version", "unknown")
        if found_version != ENGINE_CHECKPOINT_VERSION:
            raise CheckpointVersionError(
                found=found_version,
                expected=ENGINE_CHECKPOINT_VERSION,
                path=str(self.checkpoint_path),
            )

        checkpoint = EngineCheckpoint.model_validate(data)

        # ── Graph mismatch check ───────────────────────────────────────────
        if graph_node_ids is not None:
            graph_set = set(graph_node_ids)
            completed_set = set(checkpoint.completed_nodes)
            missing = sorted(completed_set - graph_set)
            if missing:
                # Nodes were completed in the previous run but no longer exist in the graph
                raise CheckpointGraphMismatchError(
                    checkpoint_path=str(self.checkpoint_path),
                    missing_nodes=missing,
                    extra_nodes=[],
                )

        logger.info(
            "Checkpoint loaded for resume: pipeline=%s completed=%d current=%s",
            checkpoint.pipeline_id,
            len(checkpoint.completed_nodes),
            checkpoint.current_node_id,
        )
        return checkpoint

    def _write_manifest(
        self,
        pipeline_id: str,
        dot_path: str,
        started_at: datetime,
    ) -> None:
        """Write immutable ``manifest.json`` at run start (written once only)."""
        manifest = {
            "schema_version": ENGINE_CHECKPOINT_VERSION,
            "pipeline_id": pipeline_id,
            "dot_path": dot_path,
            "run_dir": str(self.run_dir),
            "started_at": started_at.isoformat(),
        }
        manifest_path = self.run_dir / self.MANIFEST_FILENAME
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

    # ── Convenience ────────────────────────────────────────────────────────

    def node_dir(self, node_id: str) -> Path:
        """Return (and create) the per-node artefact directory for *node_id*."""
        d = self.run_dir / "nodes" / node_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def exists(self) -> bool:
        """Return True if a checkpoint file exists in ``run_dir``."""
        return self.checkpoint_path.exists()
