"""EngineRunner — main execution loop for Attractor DOT pipelines.

The runner is the central coordinator.  It:
1. Parses the DOT file into a ``Graph``.
2. Creates or resumes an ``EngineCheckpoint`` via ``CheckpointManager``.
3. Runs the traversal loop: execute → checkpoint → select edge → advance.
4. Propagates well-typed exceptions for external error handling.

**Traversal contract**:
- Checkpoint is saved *before* executing a node (current_node_id is set) and
  *after* completing a node (node_record appended, completed_nodes extended).
  A crash inside ``handler.execute()`` is therefore safe: on resume the runner
  re-executes the same node from scratch.
- ``$graph`` is injected into ``PipelineContext`` but stripped from the
  checkpoint's ``context`` field (not JSON-serializable).
- ``$node_visits.*`` keys ARE saved so that loop detection survives resume.
- ``$completed_nodes`` is kept in sync with ``checkpoint.completed_nodes``.

**Epic 4 — Event Bus + Middleware (AMD-7)**:
- The event bus emitter is built once per run via ``build_emitter()`` and
  closed in a ``finally`` block regardless of pipeline outcome.
- Lifecycle events are emitted at each traversal step.
- Every handler invocation is wrapped in a middleware chain:
  LogfireMiddleware → TokenCountingMiddleware → RetryMiddleware →
  AuditMiddleware → Handler.
- The HandlerRequest from middleware/chain.py is used for middleware-wrapped
  calls; handlers/base.HandlerRequest is still used for backwards compat.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cobuilder.engine.checkpoint import CheckpointManager, EngineCheckpoint, NodeRecord
from cobuilder.engine.context import PipelineContext
from cobuilder.engine.edge_selector import EdgeSelector
from cobuilder.engine.exceptions import LoopDetectedError, NoEdgeError
from cobuilder.engine.graph import Graph, Node
from cobuilder.engine.handlers import HandlerRegistry
from cobuilder.engine.handlers.base import HandlerRequest
from cobuilder.engine.outcome import Outcome
from cobuilder.engine.parser import parse_dot_file

# Epic 4: Event bus — try/except so the engine works if events pkg is absent.
try:
    from cobuilder.engine.events import (
        EventBuilder,
        NullEmitter,
        build_emitter,
        CompositeEmitter,
        EventBusConfig,
    )
    _EVENTS_AVAILABLE = True
except ImportError:
    _EVENTS_AVAILABLE = False
    EventBuilder = None  # type: ignore[assignment]

# Epic 4: Middleware chain.
try:
    from cobuilder.engine.middleware import (
        AuditMiddleware,
        LogfireMiddleware,
        RetryMiddleware,
        TokenCountingMiddleware,
        compose_middleware,
    )
    from cobuilder.engine.middleware.chain import (
        HandlerRequest as MiddlewareHandlerRequest,
    )
    _MIDDLEWARE_AVAILABLE = True
except ImportError:
    _MIDDLEWARE_AVAILABLE = False
    compose_middleware = None  # type: ignore[assignment]
    MiddlewareHandlerRequest = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

DEFAULT_MAX_NODE_VISITS: int = 10
"""Maximum times any single node may be visited before LoopDetectedError."""

_DEFAULT_PIPELINES_DIR: str = ".claude/attractor/pipelines"
"""Default parent for run directories (relative to cwd)."""

_NON_SERIALIZABLE_CONTEXT_KEYS: frozenset[str] = frozenset({"$graph"})
"""Keys that must be stripped before serialising context to checkpoint JSON."""


# ── EngineRunner ──────────────────────────────────────────────────────────────

class EngineRunner:
    """Executes an Attractor DOT pipeline from start node to exit node.

    The runner is intentionally minimal: it performs the node-by-node traversal
    loop and delegates all domain logic to pluggable ``Handler`` instances.
    ``ParallelHandler`` owns concurrency; the runner sees only a sequential
    stream of ``(node, outcome)`` pairs.

    Args:
        dot_path:            Path to the ``.dot`` pipeline file (read-only input).
        pipelines_dir:       Parent directory for run directories.  Defaults to
                             ``.claude/attractor/pipelines/`` relative to cwd.
                             Ignored when *run_dir* is supplied.
        run_dir:             Explicit run directory for *resume* mode.  When set,
                             the runner loads an existing ``EngineCheckpoint`` from
                             this directory rather than creating a new one.
        max_node_visits:     Maximum number of times any single node may be
                             visited.  Raises ``LoopDetectedError`` on breach.
                             Defaults to ``DEFAULT_MAX_NODE_VISITS`` (10).
        condition_evaluator: Injectable condition evaluator for ``EdgeSelector``.
                             Defaults to the Epic 1 stub evaluator.
        handler_registry:    Pre-built handler registry.  Defaults to
                             ``HandlerRegistry.default()`` which wires all
                             nine built-in handlers.
        initial_context:     Seed values merged into the initial ``PipelineContext``
                             before any node executes.
    """

    DEFAULT_MAX_NODE_VISITS = DEFAULT_MAX_NODE_VISITS

    def __init__(
        self,
        dot_path: str | Path,
        *,
        pipelines_dir: str | Path | None = None,
        run_dir: str | Path | None = None,
        max_node_visits: int = DEFAULT_MAX_NODE_VISITS,
        condition_evaluator: Callable | None = None,
        handler_registry: "HandlerRegistry | None" = None,
        initial_context: dict[str, Any] | None = None,
        skip_validation: bool = False,
    ) -> None:
        self.dot_path = Path(dot_path).resolve()
        self._pipelines_dir = Path(pipelines_dir) if pipelines_dir else None
        self._resume_run_dir = Path(run_dir) if run_dir else None
        self.max_node_visits = max_node_visits
        self._edge_selector = EdgeSelector(condition_evaluator)
        self._registry = handler_registry or HandlerRegistry.default()
        self._initial_context = dict(initial_context or {})
        self._skip_validation = skip_validation

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> EngineCheckpoint:
        """Execute the pipeline to completion and return the final checkpoint.

        The pipeline runs from the unique ``Mdiamond`` (start) node to a
        ``Msquare`` (exit) node.  On resume, execution continues from
        ``checkpoint.current_node_id`` rather than the start node.

        Returns:
            The final ``EngineCheckpoint`` capturing the full execution history,
            accumulated context, and visit counts.

        Raises:
            FileNotFoundError:               DOT file does not exist.
            ParseError:                      DOT file is syntactically invalid.
            LoopDetectedError:               A node exceeded *max_node_visits*.
            NoEdgeError:                     A non-exit node has no outgoing edges.
            HandlerError:                    An unrecoverable handler failure.
            CheckpointVersionError:          Checkpoint schema mismatch on resume.
            CheckpointGraphMismatchError:    DOT file changed since checkpoint.
        """
        # ── 0. Pre-execution validation ───────────────────────────────────
        if not self._skip_validation:
            from cobuilder.pipeline.validator import validate_file
            from cobuilder.engine.exceptions import ValidationError
            issues = validate_file(str(self.dot_path))
            errors = [i for i in issues if i.level == "error"]
            warnings = [i for i in issues if i.level == "warning"]
            import logging as _logging
            _vlog = _logging.getLogger(__name__)
            for w in warnings:
                _vlog.warning("Pipeline validation warning: %s", w)
            if errors:
                raise ValidationError(
                    f"Pipeline validation failed with {len(errors)} error(s): "
                    + "; ".join(str(e) for e in errors)
                )

        # ── 1. Parse DOT file ─────────────────────────────────────────────
        graph = parse_dot_file(str(self.dot_path))
        pipeline_id = self.dot_path.stem

        # ── 2. Create or load checkpoint ──────────────────────────────────
        checkpoint_mgr, checkpoint = self._setup_checkpoint(pipeline_id, graph)
        run_dir = Path(checkpoint.run_dir)
        is_resume = bool(checkpoint.completed_nodes or checkpoint.current_node_id)

        # ── 3. Hydrate context ────────────────────────────────────────────
        # Seed with caller-supplied initial values.
        context = PipelineContext(initial=dict(self._initial_context))
        # Restore persisted context from checkpoint (handles resume).
        if checkpoint.context:
            context.update(checkpoint.context)
        # Inject / refresh engine-managed non-serializable keys.
        context.update({
            "$graph": graph,
            "$pipeline_id": pipeline_id,
            "$completed_nodes": list(checkpoint.completed_nodes),
        })

        # ── 4. Determine starting node ────────────────────────────────────
        current_node = self._resolve_start_node(graph, checkpoint)

        pipeline_start = time.monotonic()

        # ── Epic 4: Build event emitter ───────────────────────────────────
        if _EVENTS_AVAILABLE:
            emitter = build_emitter(
                pipeline_id=pipeline_id,
                run_dir=str(run_dir),
            )
        else:
            # Fallback: no-op stub so existing code paths are unchanged.
            class _NullEmitter:
                async def emit(self, event: Any) -> None:
                    return
                async def aclose(self) -> None:
                    return
            emitter = _NullEmitter()  # type: ignore[assignment]

        # ── 5. Traversal loop ─────────────────────────────────────────────
        try:
            # Emit pipeline.started (or pipeline.resumed on resume).
            if _EVENTS_AVAILABLE and EventBuilder is not None:
                try:
                    if is_resume:
                        await emitter.emit(EventBuilder.pipeline_resumed(
                            pipeline_id=pipeline_id,
                            checkpoint_path=str(run_dir / "checkpoint.json"),
                            completed_node_count=len(checkpoint.completed_nodes),
                        ))
                    else:
                        await emitter.emit(EventBuilder.pipeline_started(
                            pipeline_id=pipeline_id,
                            dot_path=str(self.dot_path),
                            node_count=len(graph.nodes),
                        ))
                except Exception as emit_exc:
                    logger.warning("Failed to emit pipeline start event: %s", emit_exc)

            checkpoint = await self._run_loop(
                graph=graph,
                pipeline_id=pipeline_id,
                checkpoint=checkpoint,
                checkpoint_mgr=checkpoint_mgr,
                run_dir=run_dir,
                context=context,
                current_node=current_node,
                pipeline_start=pipeline_start,
                emitter=emitter,
            )

            # Emit pipeline.completed.
            if _EVENTS_AVAILABLE and EventBuilder is not None:
                try:
                    duration_ms = (time.monotonic() - pipeline_start) * 1000.0
                    total_tokens = checkpoint.total_tokens_used
                    await emitter.emit(EventBuilder.pipeline_completed(
                        pipeline_id=pipeline_id,
                        duration_ms=duration_ms,
                        total_tokens=total_tokens,
                    ))
                except Exception as emit_exc:
                    logger.warning("Failed to emit pipeline.completed: %s", emit_exc)

            return checkpoint

        except Exception as fatal_exc:
            # Emit pipeline.failed before propagating.
            if _EVENTS_AVAILABLE and EventBuilder is not None:
                try:
                    last_node_id = context.get("$current_node_id")
                    await emitter.emit(EventBuilder.pipeline_failed(
                        pipeline_id=pipeline_id,
                        error_type=type(fatal_exc).__name__,
                        error_message=str(fatal_exc),
                        last_node_id=last_node_id,
                    ))
                except Exception as emit_exc:
                    logger.warning("Failed to emit pipeline.failed: %s", emit_exc)
            raise
        finally:
            try:
                await emitter.aclose()
            except Exception as close_exc:
                logger.warning("Emitter aclose() raised: %s", close_exc)

    async def _run_loop(
        self,
        graph: Graph,
        pipeline_id: str,
        checkpoint: EngineCheckpoint,
        checkpoint_mgr: CheckpointManager,
        run_dir: Path,
        context: PipelineContext,
        current_node: Node,
        pipeline_start: float,
        emitter: Any,
    ) -> EngineCheckpoint:
        """Inner traversal loop extracted from run() for readability."""
        while True:
            node = current_node
            node_started_at = datetime.now(timezone.utc)

            # --- Loop guard ----------------------------------------------
            visit_count = context.increment_visit(node.id)
            if visit_count > self.max_node_visits:
                raise LoopDetectedError(
                    node_id=node.id,
                    visit_count=visit_count,
                    max_retries=self.max_node_visits,
                )

            # --- Refresh engine-managed context keys --------------------
            context.update(
                {
                    "$retry_count": visit_count - 1,
                    "$pipeline_duration_s": time.monotonic() - pipeline_start,
                    "$completed_nodes": list(checkpoint.completed_nodes),
                }
            )

            # --- Pre-execute checkpoint save ----------------------------
            # Sets current_node_id so a crash inside execute() is resumable.
            checkpoint = checkpoint.model_copy(update={"current_node_id": node.id})
            checkpoint_mgr.save(checkpoint, emitter=emitter)

            logger.info(
                "Executing node '%s'  handler=%s  visit=%d",
                node.id,
                node.handler_type,
                visit_count,
            )

            # --- Execute handler (via middleware chain) ------------------
            outcome = await self._execute_node(
                node=node,
                context=context,
                pipeline_id=pipeline_id,
                visit_count=visit_count,
                run_dir=run_dir,
                emitter=emitter,
            )

            node_completed_at = datetime.now(timezone.utc)

            # --- Apply context updates ----------------------------------
            keys_before = set(context.snapshot().keys())
            if outcome.context_updates:
                context.update(outcome.context_updates)
            context.update({"$last_status": outcome.status.value})
            keys_after = set(context.snapshot().keys())
            keys_added = sorted(keys_after - keys_before)
            keys_modified = sorted(
                k for k in outcome.context_updates if k in keys_before
            )

            # Emit context.updated once per completed node (AMD-3).
            if _EVENTS_AVAILABLE and EventBuilder is not None and (
                keys_added or keys_modified
            ):
                try:
                    await emitter.emit(EventBuilder.context_updated(
                        pipeline_id=pipeline_id,
                        node_id=node.id,
                        keys_added=keys_added,
                        keys_modified=keys_modified,
                    ))
                except Exception as emit_exc:
                    logger.warning(
                        "Failed to emit context.updated for node '%s': %s",
                        node.id, emit_exc,
                    )

            # --- Record execution and advance checkpoint ----------------
            node_record = NodeRecord(
                node_id=node.id,
                handler_type=node.handler_type,
                status=outcome.status.value,
                context_updates=dict(outcome.context_updates),
                preferred_label=outcome.preferred_label,
                suggested_next=outcome.suggested_next,
                metadata=dict(outcome.metadata),
                started_at=node_started_at,
                completed_at=node_completed_at,
            )
            new_completed = list(checkpoint.completed_nodes) + [node.id]
            # Prefer token counts from middleware-accumulated context over metadata.
            tokens_delta = int(
                context.get("$node_tokens", 0)
                or outcome.metadata.get("tokens_used", 0)
                or 0
            )
            checkpoint = checkpoint.model_copy(
                update={
                    "completed_nodes": new_completed,
                    "node_records": list(checkpoint.node_records) + [node_record],
                    "context": self._serializable_context(context),
                    "visit_counts": self._extract_visit_counts(context),
                    "total_node_executions": checkpoint.total_node_executions + 1,
                    "total_tokens_used": checkpoint.total_tokens_used + tokens_delta,
                }
            )
            # Keep live context in sync.
            context.update({"$completed_nodes": new_completed})
            checkpoint_mgr.save(checkpoint, emitter=emitter)

            logger.info(
                "Node '%s' complete  status=%s",
                node.id,
                outcome.status.value,
            )

            # --- Exit check ---------------------------------------------
            if node.is_exit:
                logger.info("Pipeline '%s' reached exit node '%s'.", pipeline_id, node.id)
                break

            # --- Edge selection and advance -----------------------------
            next_edge = self._edge_selector.select(
                graph=graph,
                node=node,
                outcome=outcome,
                context=context,
            )
            checkpoint = checkpoint.model_copy(update={"last_edge_id": next_edge.id})

            # Emit edge.selected.
            if _EVENTS_AVAILABLE and EventBuilder is not None:
                try:
                    await emitter.emit(EventBuilder.edge_selected(
                        pipeline_id=pipeline_id,
                        from_node_id=node.id,
                        to_node_id=next_edge.target,
                        selection_step=1,
                        condition=next_edge.condition or None,
                    ))
                except Exception as emit_exc:
                    logger.warning(
                        "Failed to emit edge.selected for %s->%s: %s",
                        node.id, next_edge.target, emit_exc,
                    )

            current_node = graph.nodes[next_edge.target]

        return checkpoint

    # ── Private helpers ────────────────────────────────────────────────────────

    def _setup_checkpoint(
        self,
        pipeline_id: str,
        graph: Graph,
    ) -> tuple[CheckpointManager, EngineCheckpoint]:
        """Return a (CheckpointManager, EngineCheckpoint) pair.

        - **Resume mode** (``run_dir`` was supplied): loads the existing
          checkpoint from ``run_dir`` and validates it against the current graph.
        - **Fresh run**: creates a new timestamped run directory under
          ``pipelines_dir`` and returns a blank ``EngineCheckpoint``.
        """
        graph_node_ids = list(graph.nodes.keys())

        if self._resume_run_dir:
            mgr = CheckpointManager(self._resume_run_dir)
            checkpoint = mgr.load_or_create(
                pipeline_id=pipeline_id,
                dot_path=str(self.dot_path),
                graph_node_ids=graph_node_ids,
            )
            logger.info(
                "Resumed checkpoint from '%s'  completed=%d",
                self._resume_run_dir,
                len(checkpoint.completed_nodes),
            )
            return mgr, checkpoint

        # Fresh run — create a new run directory.
        pipelines_dir = self._pipelines_dir or (
            Path.cwd() / _DEFAULT_PIPELINES_DIR
        )
        Path(pipelines_dir).mkdir(parents=True, exist_ok=True)
        mgr = CheckpointManager.create_run_dir(
            pipelines_dir=Path(pipelines_dir),
            pipeline_id=pipeline_id,
        )
        checkpoint = mgr.load_or_create(
            pipeline_id=pipeline_id,
            dot_path=str(self.dot_path),
            graph_node_ids=graph_node_ids,
        )
        logger.info(
            "New run directory: '%s'",
            checkpoint.run_dir,
        )
        return mgr, checkpoint

    @staticmethod
    def _resolve_start_node(graph: Graph, checkpoint: EngineCheckpoint) -> Node:
        """Return the node to begin execution from.

        On a fresh run this is always the unique ``Mdiamond`` (start) node.
        On resume, if ``current_node_id`` was set but NOT yet completed (i.e.
        the engine crashed inside ``handler.execute()``), we re-execute from
        that node.  Otherwise we start from the graph start node so that the
        run completes cleanly (all nodes were already completed).
        """
        if (
            checkpoint.current_node_id
            and checkpoint.current_node_id not in checkpoint.completed_nodes
            and checkpoint.current_node_id in graph.nodes
        ):
            node = graph.nodes[checkpoint.current_node_id]
            logger.info("Resuming at node '%s' (was in-progress at crash)", node.id)
            return node

        return graph.start_node

    async def _execute_node(
        self,
        node: Node,
        context: PipelineContext,
        pipeline_id: str,
        visit_count: int,
        run_dir: Path,
        emitter: Any = None,
    ) -> Outcome:
        """Build a ``HandlerRequest`` and dispatch to the registered handler.

        When middleware is available (Epic 4), the handler invocation is wrapped
        in the full middleware chain:
            LogfireMiddleware → TokenCountingMiddleware →
            RetryMiddleware → AuditMiddleware → Handler

        The HandlerRequest from middleware/chain.py is used for the chain;
        the base HandlerRequest is preserved for direct handler calls.
        """
        handler = self._registry.dispatch(node)

        if _MIDDLEWARE_AVAILABLE and MiddlewareHandlerRequest is not None:
            # Build middleware-aware request.
            mw_request = MiddlewareHandlerRequest(
                node=node,
                context=context,
                emitter=emitter,
                pipeline_id=pipeline_id,
                visit_count=visit_count,
                attempt_number=0,
                run_dir=str(run_dir),
            )
            # Build and invoke the middleware chain.
            chain = compose_middleware(
                [
                    LogfireMiddleware(),
                    TokenCountingMiddleware(),
                    RetryMiddleware(),
                    AuditMiddleware(),
                ],
                handler,
            )
            return await chain(mw_request)

        # Fallback: direct handler call (no middleware).
        request = HandlerRequest(
            node=node,
            context=context,
            emitter=emitter,
            pipeline_id=pipeline_id,
            visit_count=visit_count,
            attempt_number=visit_count,
            run_dir=str(run_dir),
        )
        return await handler.execute(request)

    @staticmethod
    def _serializable_context(context: PipelineContext) -> dict[str, Any]:
        """Return a JSON-serializable snapshot, stripping non-serializable keys."""
        return {
            k: v
            for k, v in context.snapshot().items()
            if k not in _NON_SERIALIZABLE_CONTEXT_KEYS
        }

    @staticmethod
    def _extract_visit_counts(context: PipelineContext) -> dict[str, int]:
        """Extract ``{node_id: count}`` from ``$node_visits.*`` context keys."""
        prefix = "$node_visits."
        return {
            k[len(prefix):]: v
            for k, v in context.snapshot().items()
            if k.startswith(prefix)
        }
