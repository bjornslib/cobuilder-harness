---
title: "SD-PIPELINE-ENGINE-001 Epic 1: Core Execution Engine with Checkpoint/Resume"
status: active
type: reference
last_verified: 2026-03-04
grade: authoritative
implementation_status: complete
---
# SD-PIPELINE-ENGINE-001 Epic 1: Core Execution Engine with Checkpoint/Resume

> **Implementation Status**: COMPLETE (2026-03-04)
> - **Code**: 1,459 LOC across `cobuilder/engine/` (parser, graph, handlers, edge_selector, checkpoint, runner, context, outcome, exceptions)
> - **Tests**: 67 tests, all passing
> - **Handlers**: All 9 handler types implemented (start, exit, codergen, conditional, wait_human, parallel, fan_in, tool, manager_loop)
> - **Dispatch**: Headless CLI mode (`--mode headless`) is now the DEFAULT dispatch strategy (AMD-10), replacing tmux. SDK mode for guardian/runner layer. tmux retained as legacy for interactive debugging.
> - **Known Issues**: 3 edge selector integration tests fail at the E3↔E1 boundary (condition priority ordering). Core E1 logic is fully correct.

## 1. Business Context

### Goals Addressed

| PRD Goal | How This Epic Addresses It |
| --- | --- |
| G1 — DOT pipelines execute autonomously | The engine loop parses, traverses, and dispatches handlers from `Mdiamond` to `Msquare` without human coordination between nodes |
| G2 — Crash recovery via checkpoint/resume | Atomic JSON checkpoint after every node; `--resume` reconstructs full context and skips completed nodes within 30 seconds |
| G3 — Dynamic edge routing | 5-step edge selection algorithm evaluates condition expressions from Epic 3 against accumulated `PipelineContext` |
| G5 — Loop detection | Per-node visit counters in `PipelineContext` trigger `LoopDetectedError` when `max_retries` is exceeded (Epic 5 extension point) |
| G6 — Pre-execution validation | Epic 2's 13-rule validator runs automatically before the engine enters its traversal loop unless `--skip-validation` is passed |

### Epic 1 Scope (Tight Boundary)

Epic 1 delivers the traversal loop, handler dispatch, checkpoint/resume, and edge selection. It specifically does **not** include:

- The 13-rule validation suite (Epic 2 — implemented in `cobuilder/engine/validation/`)
- The condition expression evaluator (Epic 3 — called from `edge_selector.py` but implemented in `cobuilder/engine/conditions/`)
- The structured event bus beyond direct Logfire span emission from the runner (Epic 4 — `cobuilder/engine/events/`)
- Loop detection thresholds and pattern detection (Epic 5 — visit counters stored by Epic 1; policy enforced by Epic 5)

Epic 1 defines the integration contracts that Epics 2–5 plug into. Each subsequent epic fills in a stub left by Epic 1.

---

## 2. Technical Architecture

### 2.1 Architectural Principles

The engine follows three architectural principles drawn from the 10-implementation community survey:

**Sequential core, parallel edges.** The engine loop is sequential: execute a node, select an edge, checkpoint, advance. Parallelism only enters at `component`/`parallelogram` (fan-out) nodes via `asyncio.TaskGroup`. This matches the universal pattern across all 10 community implementations and keeps crash recovery tractable.

**Protocol-based handler registry.** Handlers implement the `Handler` protocol (`execute(node, context) → Outcome`) and register by DOT shape name. The engine never calls handler implementations directly — only through the registry. This allows new shapes to be added without touching the runner.

**Atomic checkpoints as the single source of truth.** After every node execution, the engine writes a checkpoint using write-to-temp-then-rename. If the process crashes between nodes, the next resume reads the checkpoint and skips nodes in `completed_nodes`. The DOT file is never modified by the engine; it is read-only input.

### 2.2 System Diagram

```
cobuilder pipeline run pipeline.dot [--resume] [--skip-validation]
        │
        ▼
  EngineRunner.__init__()
        │ parse
        ▼
  DotParser.parse_file(path) ──────────────────► Graph
        │                                         │
        │ validate (auto, unless --skip-validation)
        ▼                                         │
  Validator.run_all(graph) ◄────────────────────┘
        │ pass / error
        ▼
  CheckpointManager.load_or_create(run_dir)
        │ EngineCheckpoint
        ▼
  EngineRunner.run() — main loop
    ┌───────────────────────────────────────┐
    │  current_node = start_node            │
    │                                       │
    │  while not is_exit(current_node):     │
    │    context = checkpoint.context       │
    │    visit_counts = checkpoint.visits   │
    │                                       │
    │    outcome = middleware_chain(        │
    │      handler.execute(node, context)   │
    │    )  ← logfire span wraps this       │
    │                                       │
    │    edge = EdgeSelector.select(        │
    │      node, outcome, context           │
    │    )                                  │
    │                                       │
    │    checkpoint.update(node, outcome,   │
    │      edge, visit_counts)              │
    │    CheckpointManager.save(checkpoint) │
    │                                       │
    │    current_node = edge.target         │
    │  end while                            │
    │                                       │
    │  ExitHandler.execute() — goal gate    │
    └───────────────────────────────────────┘
```

### 2.3 Integration Points with Existing Infrastructure

| Existing File | Location | How Engine Uses It |
| --- | --- | --- |
| `cobuilder/pipeline/parser.py` | `parse_dot(content)` | **Not reused.** The engine needs a richer, typed parser. `DotParser` in `cobuilder/engine/parser.py` is a new recursive-descent implementation that returns typed `Graph/Node/Edge` dataclasses. The existing parser returns raw dicts adequate for CLI ops but not for a typed execution engine. |
| `cobuilder/orchestration/spawn_orchestrator.py` | `spawn_orchestrator(node_id, prd, repo_root, ...)` | `CodergenHandler` imports and calls this for `dispatch_strategy=tmux` (default). No changes to spawn_orchestrator.py itself. |
| `cobuilder/pipeline/signal_protocol.py` | `write_signal(source, target, type, payload)` | `SignalBridge` event backend (Epic 4) calls `write_signal`. Epic 1 calls `write_signal(ORCHESTRATOR_STUCK)` directly from the loop when a fatal error occurs. |
| `cobuilder/pipeline/transition.py` | `apply_transition(content, node_id, status)` | Not called by the engine. Transition.py modifies DOT files in-place; the engine treats DOT files as read-only and tracks state in `EngineCheckpoint`. Handlers do **not** call `apply_transition`. |
| `.claude/scripts/attractor/anti_gaming.py` | `ChainedAuditWriter`, `SpotCheckSelector`, `EvidenceValidator` | `AuditMiddleware` (Epic 4) wraps these. Epic 1 stubs the middleware slot without implementing anti-gaming middleware. |
| `.claude/scripts/attractor/runner_hooks.py` | `RunnerHooks.pre_tool_use()` | Not integrated in Epic 1. Epic 4 adds `HookMiddleware` that delegates to `RunnerHooks`. |
| `logfire` Python package | `logfire.span()`, `logfire.instrument()` | `EngineRunner` wraps the full pipeline in a `logfire.span("pipeline.run")`. Each node execution is wrapped in a child `logfire.span("node.{node_id}")`. Epic 4 adds `LogfireEmitter` for the full 14-type event bus. |

---

## 3. Functional Decomposition

### Feature Map with Dependencies

```
F1: DotParser (custom recursive-descent)
  └─ F2: Graph/Node/Edge data models (consumed by all features)
       └─ F3: HandlerRegistry + Handler protocol
            ├─ F4: StartHandler (Mdiamond)
            ├─ F5: ExitHandler (Msquare) — depends on F9 (goal gate)
            ├─ F6: CodergenHandler (box) — depends on spawn_orchestrator.py
            ├─ F7: ConditionalHandler (diamond)
            ├─ F8: WaitHumanHandler (hexagon)
            ├─ F10: ParallelHandler (component/parallelogram) — asyncio.TaskGroup
            ├─ F11: FanInHandler (tripleoctagon)
            ├─ F12: ToolHandler (parallelogram tool variant)
            └─ F13: ManagerLoopHandler (house)
       └─ F14: Outcome model
            └─ F15: PipelineContext (key-value accumulator)
                 └─ F16: EdgeSelector (5-step algorithm)
                      └─ F17: CheckpointManager (atomic write/load)
                           └─ F18: EngineRunner (main loop)
                                └─ F19: CLI integration (run + validate subcommands)
                                     └─ F20: Logfire span wrapping (inline, pre-Epic 4 event bus)
```

### Feature Descriptions

**F1 — DotParser.** Custom recursive-descent parser producing typed `Graph`, `Node`, `Edge` dataclasses. Extracts all 9+ Attractor-specific attributes (`prompt`, `goal_gate`, `tool_command`, `model_stylesheet`, `bead_id`, `worker_type`, `acceptance`, `solution_design`, `file_path`, `folder_path`, `dispatch_strategy`, `max_retries`, `retry_target`, `join_policy`, `loop_restart`, `allow_partial`). No external graphviz dependency.

**F2 — Data Models.** Typed `@dataclass` definitions for `Graph`, `Node`, `Edge`. Separate from Pydantic models (Pydantic is used for `EngineCheckpoint` and `Outcome` which need serialisation). Dataclasses are sufficient for the parsed graph which is read-only after parsing.

**F3 — HandlerRegistry.** Dict mapping DOT shape strings to `Handler` implementations. `register(shape, handler)` API. `dispatch(node)` raises `UnknownShapeError` for unrecognised shapes.

**F4–F13 — Handler implementations.** See Section 5 (API Contracts) for each handler's contract. Only F4 (StartHandler) and F6 (CodergenHandler) are critical-path for the Epic 1 linear-pipeline acceptance test. The remaining handlers are required for full AC coverage but can be implemented in parallel.

**F14 — Outcome.** `@dataclass` returned by every `Handler.execute()` call. Contains `status`, `context_updates`, `preferred_label`, `suggested_next`. Immutable after construction.

**F15 — PipelineContext.** Mutable key-value accumulator. Thread-safe read (fan-out handlers get a snapshot copy, not a shared reference). Provides `get(key, default)`, `update(dict)`, `snapshot() → dict`. Built-in keys: `$retry_count`, `$node_visits.<node_id>`, `$last_status`, `$pipeline_duration_s`.

**F16 — EdgeSelector.** 5-step algorithm (Section 5.4). Returns one `Edge` or raises `NoEdgeError` when no edge can be selected.

**F17 — CheckpointManager.** Reads/writes `EngineCheckpoint` JSON atomically. Creates run directory structure. Provides `load_or_create(run_dir, dot_path)` and `save(checkpoint)`.

**F18 — EngineRunner.** Main loop. Instantiates all components, wires them together, runs the traversal loop, handles `LoopDetectedError`, `HandlerError`, `NoEdgeError`, and writes fatal signals on unrecoverable failure.

**F19 — CLI integration.** Adds `run` and `validate` subcommands to `pipeline_app` in `cobuilder/cli.py`. Connects to `EngineRunner` and `Validator`.

**F20 — Logfire span wrapping.** Inline with the runner — not via the Epic 4 event bus. Pipeline-level span with child node spans. Token counts from CodergenHandler added as span attributes. This is the minimal observability for Epic 1 that Epic 4 will replace/extend.

---

## 4. API / Interface Contracts

### 4.1 Handler Protocol

```python
# cobuilder/engine/handlers/base.py
from typing import Protocol, runtime_checkable
from cobuilder.engine.graph import Node
from cobuilder.engine.context import PipelineContext
from cobuilder.engine.outcome import Outcome


@dataclass(frozen=True)
class HandlerRequest:
    """AMD-8: Unified request object for handler invocation.

    Defined in Epic 1 (not Epic 4) as part of the core contract.
    The EngineRunner ALWAYS wraps handler calls in HandlerRequest,
    even when no middlewares are configured. This eliminates the
    signature mismatch between direct handler calls and middleware-wrapped calls.

    The middleware chain's callable signature is:
        async (request: HandlerRequest) -> Outcome
    """
    node: Node
    context: PipelineContext
    emitter: Any = None                 # EventEmitter (Epic 4); None in Epic 1
    pipeline_id: str = ""
    visit_count: int = 1
    attempt_number: int = 1
    run_dir: str = ""


@runtime_checkable
class Handler(Protocol):
    """All node handlers must implement this protocol.

    execute() receives a HandlerRequest wrapping the node and context.
    Handlers are stateless; all state lives in PipelineContext.

    The method must be async to support ParallelHandler (asyncio.TaskGroup).
    Sequential handlers simply run their logic in a coroutine body.

    AMD-8: The signature uses HandlerRequest, not (Node, PipelineContext),
    so that the runner can call handlers identically with or without middleware.
    """

    async def execute(self, request: HandlerRequest) -> Outcome:
        """Execute the handler's logic for the request.

        Args:
            request: HandlerRequest wrapping node, context, and metadata.

        Returns:
            Outcome with status, context_updates, preferred_label, suggested_next.

        Raises:
            HandlerError: If the handler encounters an unrecoverable error.
                          The runner catches this and writes a VIOLATION signal.
        """
        ...
```

### 4.2 Outcome Model

```python
# cobuilder/engine/outcome.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OutcomeStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL_SUCCESS = "partial_success"
    WAITING = "waiting"           # WaitHumanHandler: pause requested
    SKIPPED = "skipped"           # StartHandler: no-op


@dataclass(frozen=True)
class Outcome:
    """Immutable result returned by every Handler.execute() call.

    Attributes:
        status:          Normalised execution result.
        context_updates: Dict of key-value pairs to merge into PipelineContext.
                         Keys beginning with '$' are reserved for engine built-ins.
        preferred_label: If set, EdgeSelector preferentially matches this edge label
                         (Step 2 of the 5-step algorithm).
        suggested_next:  If set, EdgeSelector preferentially routes to this node ID
                         (Step 3 of the 5-step algorithm).
        metadata:        Arbitrary per-handler data (token counts, exit_code, etc.)
                         stored in checkpoint for observability but not used for routing.
    """
    status: OutcomeStatus
    context_updates: dict[str, Any] = field(default_factory=dict)
    preferred_label: str | None = None
    suggested_next: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_messages: list[Any] = field(default_factory=list)
    """Populated by CodergenHandler (SDK dispatch) with raw LLM messages.
    Read by TokenCountingMiddleware (Epic 4) for token usage tracking.
    Empty for non-LLM handlers. Reserved extension point — AMD-7."""
```

### 4.3 PipelineContext

```python
# cobuilder/engine/context.py
from __future__ import annotations
import threading
from typing import Any


class PipelineContext:
    """Thread-safe key-value store for accumulated pipeline state.

    Fan-out handlers receive a snapshot (shallow copy) of the context.
    Fan-in handlers merge snapshot updates back via merge_snapshot().

    Built-in keys (always present, maintained by the engine runner):
        $last_status           OutcomeStatus of the most recently completed node
        $retry_count           int, number of times current node has been retried
        $pipeline_duration_s   float, seconds elapsed since pipeline start
        $node_visits.<node_id> int, number of times node_id has been visited

    Custom keys (set by handler context_updates) must not begin with '$'.
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(initial or {})
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def update(self, updates: dict[str, Any]) -> None:
        with self._lock:
            self._data.update(updates)

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the current context state."""
        with self._lock:
            return dict(self._data)

    def merge_fan_out_results(
        self,
        branch_outcomes: list[tuple[str, "Outcome"]],
    ) -> dict[str, Any]:
        """Merge results from parallel fan-out branches into the main context.

        AMD-2 Fan-Out Context Merge Policy:
        - Parallel branches receive a READ-ONLY snapshot of the context.
        - Each branch's context_updates are namespaced by branch node ID:
          the key '{branch_node_id}.{original_key}' is stored in the main context.
        - This prevents silent data corruption when branches write the same key.
        - FanInHandler receives the list of (branch_id, Outcome) tuples and can
          inspect individual branch results before producing a merged Outcome.

        Args:
            branch_outcomes: List of (branch_node_id, outcome) tuples from
                             all completed parallel branches.

        Returns:
            Dict of all namespaced keys that were merged into the main context.
        """
        merged_keys: dict[str, Any] = {}
        with self._lock:
            for branch_id, outcome in branch_outcomes:
                for key, value in outcome.context_updates.items():
                    namespaced_key = f"{branch_id}.{key}"
                    self._data[namespaced_key] = value
                    merged_keys[namespaced_key] = value
        return merged_keys

    def increment_visit(self, node_id: str) -> int:
        """Increment and return the visit count for node_id."""
        key = f"$node_visits.{node_id}"
        with self._lock:
            count = self._data.get(key, 0) + 1
            self._data[key] = count
            return count

    def get_visit_count(self, node_id: str) -> int:
        key = f"$node_visits.{node_id}"
        with self._lock:
            return self._data.get(key, 0)
```

### 4.4 EdgeSelector — 5-Step Algorithm

```python
# cobuilder/engine/edge_selector.py
from __future__ import annotations
from cobuilder.engine.graph import Graph, Node, Edge
from cobuilder.engine.context import PipelineContext
from cobuilder.engine.outcome import Outcome


class NoEdgeError(Exception):
    """Raised when no edge can be selected after exhausting all 5 steps."""


class EdgeSelector:
    """Selects the next edge using the community-standard 5-step algorithm.

    Priority order (highest to lowest):
        1. Condition truth  — edge.condition evaluates True against context
        2. Preferred label  — edge.label matches outcome.preferred_label
        3. Suggested node   — edge.target matches outcome.suggested_next
        4. Edge weight      — numeric edge.weight (highest wins)
        5. Default edge     — unlabeled, unconditioned edge; or first outgoing edge

    The condition evaluator is provided as a callable to keep the edge selector
    decoupled from the expression language (Epic 3). In Epic 1, a stub evaluator
    that only handles literal "true"/"false" and simple equality is used.
    In Epic 3, this callable is replaced with the full recursive-descent evaluator.
    """

    def __init__(self, condition_evaluator=None) -> None:
        # Default stub evaluator for Epic 1; replaced by Epic 3 evaluator
        self._evaluate = condition_evaluator or _stub_condition_evaluator

    def select(
        self,
        graph: Graph,
        node: Node,
        outcome: Outcome,
        context: PipelineContext,
    ) -> Edge:
        """Select the next edge from node's outgoing edges.

        Args:
            graph:   The full pipeline graph (for edge lookup).
            node:    Current node whose outgoing edges we select from.
            outcome: The handler's returned outcome.
            context: Current pipeline context.

        Returns:
            The selected Edge.

        Raises:
            NoEdgeError: If no edge satisfies any of the 5 selection steps
                         (e.g., exit node with no outgoing edges caught here).
        """
        outgoing: list[Edge] = graph.edges_from(node.id)
        if not outgoing:
            raise NoEdgeError(
                f"Node '{node.id}' has no outgoing edges. "
                "If this is an exit node, the runner loop should have stopped before calling EdgeSelector."
            )

        ctx_snapshot = context.snapshot()

        # Step 1: Condition match
        for edge in outgoing:
            if edge.condition and self._evaluate(edge.condition, ctx_snapshot, outcome):
                return edge

        # Step 2: Preferred label match
        if outcome.preferred_label:
            for edge in outgoing:
                if edge.label == outcome.preferred_label:
                    return edge

        # Step 3: Suggested next node
        if outcome.suggested_next:
            for edge in outgoing:
                if edge.target == outcome.suggested_next:
                    return edge

        # Step 4: Weight-based selection (highest weight wins)
        weighted = [e for e in outgoing if e.weight is not None]
        if weighted:
            return max(weighted, key=lambda e: e.weight)

        # Step 5: Default — first unlabeled/unconditioned edge, then first outgoing
        unlabeled = [e for e in outgoing if not e.label and not e.condition]
        return unlabeled[0] if unlabeled else outgoing[0]


def _stub_condition_evaluator(condition: str, context: dict, outcome: Outcome) -> bool:
    """Epic 1 stub: handles only literal 'true'/'false' and simple equality.

    Replaced by the full recursive-descent evaluator in Epic 3.
    """
    stripped = condition.strip().lower()
    if stripped == "true":
        return True
    if stripped == "false":
        return False

    # Simple equality: "$key = value" or "outcome = success"
    if "=" in stripped and "==" not in stripped:
        parts = stripped.split("=", 1)
        lhs, rhs = parts[0].strip(), parts[1].strip()
        if lhs == "outcome":
            return str(outcome.status.value).lower() == rhs
        if lhs.startswith("$"):
            key = lhs[1:]
            val = context.get(key, context.get(f"${key}", None))
            return str(val).lower() == rhs if val is not None else False

    return False
```

### 4.5 EngineCheckpoint Schema (Pydantic)

```python
# cobuilder/engine/checkpoint.py  (schema portion)
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class NodeRecord(BaseModel):
    """Record of a single completed node execution."""
    node_id: str
    handler_type: str
    status: str                        # OutcomeStatus value
    context_updates: dict[str, Any] = Field(default_factory=dict)
    preferred_label: str | None = None
    suggested_next: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    completed_at: datetime


class EngineCheckpoint(BaseModel):
    """Full resumable state of a pipeline run.

    This is the single source of truth for crash recovery.
    Written atomically after every node execution.

    Schema version bumps when fields are added; runner checks
    checkpoint.schema_version against ENGINE_CHECKPOINT_VERSION
    and rejects incompatible checkpoints with a clear error.
    """
    schema_version: str = "1.0.0"
    pipeline_id: str                   # DOT file base name (without extension)
    dot_path: str                      # Absolute path to source DOT file
    run_dir: str                       # Absolute path to run directory
    started_at: datetime
    last_updated_at: datetime

    # Execution state
    completed_nodes: list[str] = Field(default_factory=list)   # Node IDs in order
    node_records: list[NodeRecord] = Field(default_factory=list)
    current_node_id: str | None = None  # None = not yet started
    last_edge_id: str | None = None     # Edge taken to reach current_node_id

    # Context snapshot (accumulated from all completed node outcomes)
    context: dict[str, Any] = Field(default_factory=dict)

    # Visit counts (also present in context as $node_visits.<id>, duplicated
    # here for explicit checkpoint schema clarity and resume validation)
    visit_counts: dict[str, int] = Field(default_factory=dict)

    # Pipeline-wide counters
    total_node_executions: int = 0      # For pipeline-wide loop detection (Epic 5)
    total_tokens_used: int = 0          # Aggregated from CodergenHandler metadata


ENGINE_CHECKPOINT_VERSION = "1.0.0"
```

### 4.6 Checkpoint Directory Structure

```
.pipelines/pipelines/
  <pipeline_id>-run-<timestamp>/      # run_dir, created by CheckpointManager
    checkpoint.json                   # EngineCheckpoint (atomic write)
    checkpoint.json.tmp               # Temporary write target (deleted after rename)
    manifest.json                     # Immutable run metadata written at start
    pipeline-events.jsonl             # Epic 4: event bus JSONL backend
    nodes/
      <node_id>/
        prompt.md                     # CodergenHandler: prompt sent to orchestrator
        response.md                   # CodergenHandler: response/signal received
        status.json                   # {"status": "success", "completed_at": "..."}
        audit.jsonl                   # AuditMiddleware (Epic 4): chained audit log
```

This matches the consensus format from attractor-rb, F#kYeah, and Kilroy. The `nodes/` subdirectory per node enables Kilroy-style git-native checkpointing as an optional future enhancement (toggle via `ATTRACTOR_GIT_COMMIT_PER_NODE=1` environment variable).

### 4.7 CLI Subcommands

```bash
# New subcommands added to cobuilder/cli.py (pipeline_app):

cobuilder pipeline run <file.dot>
  [--resume]                # Load existing checkpoint and skip completed nodes
  [--skip-validation]       # Skip the 13-rule validation pass
  [--run-dir <path>]        # Override default run directory location
  [--dispatch <strategy>]   # Override dispatch_strategy for all codergen nodes
  [--logfire-project <id>]  # Logfire project ID for span export

cobuilder pipeline validate <file.dot>
  # EXISTING command in cli.py, backed by cobuilder/pipeline/validator.py
  # Epic 2 replaces the validator backend with the 13-rule engine validator.
  # The CLI signature does NOT change; only the implementation module changes.
  [--json]                  # JSON output (existing flag)
```

The `run` subcommand does not exist yet in `cobuilder/cli.py`. It must be added. The `validate` subcommand already exists (line 958 in cli.py) and will have its backend swapped in Epic 2. For Epic 1, `run` calls the engine's built-in validation automatically before execution.

---

## 5. Data Models

### 5.1 Graph Models (dataclasses — read-only after parse)

```python
# cobuilder/engine/graph.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


# Canonical shape → handler type mapping
SHAPE_TO_HANDLER: dict[str, str] = {
    "Mdiamond":        "start",
    "Msquare":         "exit",
    "box":             "codergen",
    "diamond":         "conditional",
    "hexagon":         "wait_human",
    "component":       "parallel",
    "tripleoctagon":   "fan_in",
    "parallelogram":   "tool",         # disambiguated from parallel by 'tool_command' attr
    "house":           "manager_loop",
}

# Node shapes that require LLM invocation (used by validation Rule 13)
LLM_NODE_SHAPES: frozenset[str] = frozenset({"box"})

# Node shapes that are goal_gate candidates (used by ExitHandler)
GOAL_GATE_SHAPES: frozenset[str] = frozenset({"box", "hexagon", "component"})


@dataclass
class Node:
    """A parsed DOT node with all Attractor-specific attributes extracted.

    The 'attrs' dict holds the raw attribute bag; typed properties below
    provide ergonomic access to the attributes the engine cares about.
    """
    id: str
    shape: str
    label: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)

    # Attractor-specific typed accessors
    @property
    def handler_type(self) -> str:
        return SHAPE_TO_HANDLER.get(self.shape, "unknown")

    @property
    def is_start(self) -> bool:
        return self.shape == "Mdiamond"

    @property
    def is_exit(self) -> bool:
        return self.shape == "Msquare"

    @property
    def prompt(self) -> str:
        return self.attrs.get("prompt", "")

    @property
    def goal_gate(self) -> bool:
        return self.attrs.get("goal_gate", "false").lower() == "true"

    @property
    def tool_command(self) -> str:
        return self.attrs.get("tool_command", "")

    @property
    def dispatch_strategy(self) -> str:
        return self.attrs.get("dispatch_strategy", "tmux")

    @property
    def max_retries(self) -> int:
        return int(self.attrs.get("max_retries", "3"))

    @property
    def retry_target(self) -> str | None:
        return self.attrs.get("retry_target", None)

    @property
    def join_policy(self) -> str:
        return self.attrs.get("join_policy", "wait_all")

    @property
    def allow_partial(self) -> bool:
        return self.attrs.get("allow_partial", "false").lower() == "true"

    @property
    def bead_id(self) -> str:
        return self.attrs.get("bead_id", "")

    @property
    def worker_type(self) -> str:
        return self.attrs.get("worker_type", "")

    @property
    def acceptance(self) -> str:
        return self.attrs.get("acceptance", "")

    @property
    def solution_design(self) -> str:
        return self.attrs.get("solution_design", "")


@dataclass
class Edge:
    """A parsed DOT directed edge between two nodes."""
    source: str
    target: str
    label: str = ""
    condition: str = ""               # Raw condition expression string
    weight: float | None = None
    loop_restart: bool = False        # If True, clear context on traversal (Epic 5)
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Stable identifier for this edge (for logging and checkpoint)."""
        return f"{self.source}->{self.target}"


@dataclass
class Graph:
    """In-memory representation of a parsed Attractor DOT pipeline."""
    name: str
    attrs: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)  # node_id → Node
    edges: list[Edge] = field(default_factory=list)

    # Cached adjacency for performance
    _edges_from: dict[str, list[Edge]] = field(default_factory=dict, repr=False)
    _edges_to: dict[str, list[Edge]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._build_adjacency()

    def _build_adjacency(self) -> None:
        for edge in self.edges:
            self._edges_from.setdefault(edge.source, []).append(edge)
            self._edges_to.setdefault(edge.target, []).append(edge)

    def edges_from(self, node_id: str) -> list[Edge]:
        return list(self._edges_from.get(node_id, []))

    def edges_to(self, node_id: str) -> list[Edge]:
        return list(self._edges_to.get(node_id, []))

    @property
    def start_node(self) -> Node:
        starts = [n for n in self.nodes.values() if n.is_start]
        if len(starts) != 1:
            raise ValueError(
                f"Graph must have exactly one start node (Mdiamond); found {len(starts)}"
            )
        return starts[0]

    @property
    def exit_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.is_exit]

    @property
    def goal_gate_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.goal_gate]

    # PRD graph-level attributes
    @property
    def prd_ref(self) -> str:
        return self.attrs.get("prd_ref", "")

    @property
    def default_max_retry(self) -> int:
        return int(self.attrs.get("default_max_retry", "50"))

    @property
    def retry_target(self) -> str | None:
        return self.attrs.get("retry_target", None)

    @property
    def fallback_retry_target(self) -> str | None:
        return self.attrs.get("fallback_retry_target", None)
```

### 5.2 Handler Return Contracts per Shape

| Shape | Handler | Expected Outcome Status | context_updates Keys |
| --- | --- | --- | --- |
| `Mdiamond` | StartHandler | `SKIPPED` | None |
| `Msquare` | ExitHandler | `SUCCESS` if goal gates met; `FAILURE` otherwise | `$pipeline_outcome` |
| `box` (tmux) | CodergenHandler | `SUCCESS`/`FAILURE`/`PARTIAL_SUCCESS` | `$<node_id>.status`, `$<node_id>.tokens_used` |
| `box` (sdk) | CodergenHandler | Same | Same |
| `diamond` | ConditionalHandler | `SUCCESS` (routing only) | None |
| `hexagon` | WaitHumanHandler | `WAITING` (paused) or `SUCCESS` (approved) | `$<node_id>.approval` |
| `component` | ParallelHandler | `SUCCESS` if join_policy met | `$<node_id>.results` |
| `tripleoctagon` | FanInHandler | Per `join_policy` | `$fan_in.results` |
| `parallelogram` | ToolHandler | `SUCCESS` (exit 0) or `FAILURE` (non-zero) | `$<node_id>.stdout`, `$<node_id>.exit_code` |
| `house` | ManagerLoopHandler | `SUCCESS` if sub-pipeline completes | `$<node_id>.pipeline_outcome` |

---

## 6. Acceptance Criteria per Feature

### AC-F1: DotParser

- [ ] Parses a DOT file with `Mdiamond`, `Msquare`, and `box` nodes into a typed `Graph` object
- [ ] Extracts all 9+ Attractor-specific attributes: `prompt`, `goal_gate`, `tool_command`, `model_stylesheet`, `bead_id`, `worker_type`, `acceptance`, `solution_design`, `file_path`, `folder_path`, `dispatch_strategy`, `max_retries`, `retry_target`, `join_policy`, `loop_restart`, `allow_partial`
- [ ] Extracts edge `condition`, `label`, and `weight` attributes
- [ ] Extracts graph-level attributes: `prd_ref`, `promise_id`, `label`, `default_max_retry`, `retry_target`, `fallback_retry_target`
- [ ] Raises `ParseError` with line number and snippet for malformed DOT
- [ ] Does not import `graphviz`, `pydot`, or any non-stdlib DOT library
- [ ] Parses all `.dot` files in `.pipelines/pipelines/` without error (regression test corpus)

### AC-F3: HandlerRegistry

- [ ] `registry.dispatch(node)` returns the correct handler for all 9 known shapes
- [ ] `registry.dispatch(node)` raises `UnknownShapeError` with the shape name for unrecognised shapes
- [ ] Registry can be instantiated with a custom handler dict for testing (dependency injection)

### AC-F4: StartHandler

- [ ] Returns `Outcome(status=SKIPPED, context_updates={})` for any `Mdiamond` node
- [ ] Does not write any signals, spawn any processes, or modify any files

### AC-F5: ExitHandler

- [ ] Returns `Outcome(status=SUCCESS)` when all `goal_gate=true` nodes are in `completed_nodes`
- [ ] Returns `Outcome(status=FAILURE)` when any `goal_gate=true` node is missing from `completed_nodes`
- [ ] Updates `context["$pipeline_outcome"]` to `"success"` or `"failure"`
- [ ] On SUCCESS: writes `pipeline_complete.signal` to signals directory

### AC-F6: CodergenHandler

**AMD-1 Completion Protocol (tmux dispatch)**:

The CodergenHandler for `dispatch_strategy=tmux` follows a signal-polling completion protocol:

1. **Spawn**: Calls `spawn_orchestrator.spawn_orchestrator(node_id=node.id, prd=graph.prd_ref, repo_root=run_dir)`
2. **Write prompt**: Writes prompt to `{run_dir}/nodes/{node_id}/prompt.md` before spawning
3. **Poll for signals**: Uses `asyncio.sleep(poll_interval)` loop watching for:
  - `{node_id}-complete.signal` → `OutcomeStatus.SUCCESS`
  - `{node_id}-failed.signal` → `OutcomeStatus.FAILURE`
  - `{node_id}-needs-review.signal` → `OutcomeStatus.PARTIAL_SUCCESS`
4. **Timeout**: After `handler_timeout_s` seconds (default: 3600s), returns `Outcome(status=FAILURE, metadata={"error_type": "TIMEOUT", "elapsed_s": elapsed})`
5. **Write outcome**: Writes `{run_dir}/nodes/{node_id}/outcome.json` with the full Outcome dataclass

Signal directory: `{run_dir}/nodes/{node_id}/signals/`
Poll interval: configurable via `ATTRACTOR_SIGNAL_POLL_INTERVAL` (default: 10s)

The orchestrator spawned by `spawn_orchestrator.py` is responsible for writing the completion signal. The existing signal protocol (`VALIDATION_PASSED`, `NEEDS_REVIEW`) bridges to these node-scoped signals via the `SignalBridge` (Epic 4).

**Acceptance Criteria**:

- [ ] For `dispatch_strategy=tmux`: spawns orchestrator and polls for `{node_id}-complete.signal` or `{node_id}-failed.signal`
- [ ] For `dispatch_strategy=sdk`: calls `claude_code_sdk.query(prompt=node.prompt)` and converts result to `Outcome`
- [ ] Timeout: returns `Outcome(status=FAILURE, metadata={"error_type": "TIMEOUT"})` after `handler_timeout_s` seconds (default 3600s)
- [ ] Signal poll interval: 10 seconds (configurable via `ATTRACTOR_SIGNAL_POLL_INTERVAL`)
- [ ] On completion signal: returns `Outcome(status=SUCCESS, metadata={"signal": "complete"})`
- [ ] On failed signal: returns `Outcome(status=FAILURE, metadata={"signal": "failed", "feedback": payload.get("feedback")})`
- [ ] Writes node prompt to `run_dir/nodes/<node_id>/prompt.md` BEFORE spawning
- [ ] Writes outcome to `run_dir/nodes/<node_id>/outcome.json` AFTER completion

### AC-F7: ConditionalHandler

- [ ] Returns `Outcome(status=SUCCESS, preferred_label=None, suggested_next=None)` — routing is done entirely by EdgeSelector evaluating edge conditions
- [ ] Does not make LLM calls or spawn processes

### AC-F8: WaitHumanHandler

- [ ] Polls `signal_protocol.wait_for_signal(target_layer="runner")` for `INPUT_RESPONSE` signal
- [ ] Returns `Outcome(status=WAITING)` when no signal received within poll cycle
- [ ] On `INPUT_RESPONSE` signal with `response="approve"`: returns `Outcome(status=SUCCESS)`
- [ ] On `INPUT_RESPONSE` signal with `response="reject"`: returns `Outcome(status=FAILURE)`
- [ ] Respects `ATTRACTOR_HUMAN_GATE_TIMEOUT` (default: indefinite — polls until signal)

### AC-F10: ParallelHandler (component)

- [ ] Uses `asyncio.TaskGroup` to fan-out all child nodes concurrently
- [ ] Each child node executes in isolation with a snapshot copy of `PipelineContext`
- [ ] For `join_policy=wait_all`: waits for all children; returns `SUCCESS` only if all succeed
- [ ] For `join_policy=first_success`: returns as soon as any child succeeds; cancels remaining tasks
- [ ] Merges child context updates back into main `PipelineContext` after join

### AC-F11: FanInHandler (tripleoctagon)

- [ ] Blocks until all parallel branches have written their completion to a shared rendezvous (implemented as a dict of `asyncio.Event`)
- [ ] Returns `Outcome` based on collected results from all branches

### AC-F12: ToolHandler (parallelogram)

- [ ] Executes `node.tool_command` via `subprocess.run(shell=True)` in `run_dir`
- [ ] Returns `Outcome(status=SUCCESS)` for exit code 0; `Outcome(status=FAILURE)` for non-zero
- [ ] Captures stdout/stderr into `context_updates["$<node_id>.stdout"]`, `context_updates["$<node_id>.stderr"]`
- [ ] Timeout: `ATTRACTOR_TOOL_TIMEOUT` seconds (default: 300s)

### AC-F13: ManagerLoopHandler (house) — AMD-10: DEFERRED

**Status**: Explicitly deferred to a future epic. The `house` shape is parsed and registered but the handler is a stub.

- [ ] `ManagerLoopHandler.execute()` raises `NotImplementedError("ManagerLoopHandler is deferred to a future epic — see AMD-10 in design challenge report")`
- [ ] Validation Rule 10 (`NodeTypesKnown`) emits a WARNING (not error) when a `house` node is encountered
- [ ] The stub is clearly documented in the handler source code with a TODO referencing AMD-10

### AC-F16: EdgeSelector

- [ ] Step 1 (condition match): evaluates edge.condition against context snapshot using the injected evaluator
- [ ] Step 2 (preferred label): matches outcome.preferred_label against edge.label
- [ ] Step 3 (suggested next): matches outcome.suggested_next against edge.target
- [ ] Step 4 (weight): selects highest numeric edge.weight when present
- [ ] Step 5 (default): selects first unlabeled/unconditioned edge; falls back to outgoing[0]
- [ ] Raises `NoEdgeError` when no step produces a result (all edges have conditions that fail and no default exists)

### AC-F17: CheckpointManager

- [ ] `save(checkpoint)` writes to `checkpoint.json.tmp` then renames to `checkpoint.json` (atomic)
- [ ] `load_or_create()` returns a fresh `EngineCheckpoint` if no checkpoint exists
- [ ] `load_or_create()` loads and validates the existing checkpoint (schema version check) if it exists
- [ ] `load_or_create()` raises `CheckpointVersionError` if `schema_version` does not match `ENGINE_CHECKPOINT_VERSION`
- [ ] `save()` is called within 100ms of handler completion (not delayed by event emission)

### AC-F18: EngineRunner (Primary Integration Test)

- [ ] `cobuilder pipeline run linear.dot` traverses a 3-node pipeline (start → codergen → exit) end-to-end with a mock CodergenHandler
- [ ] `cobuilder pipeline run linear.dot --resume` skips `completed_nodes` and resumes from `current_node_id`
- [ ] On `HandlerError`: writes `ORCHESTRATOR_CRASHED` signal via `signal_protocol.write_signal`, exits non-zero
- [ ] On `LoopDetectedError` (Epic 5 raises this): writes `ORCHESTRATOR_STUCK` signal, exits non-zero
- [ ] On `NoEdgeError`: logs error with current node ID and all available edges, exits non-zero
- [ ] On validation failure (pre-run): prints rule violations and exits without spawning any processes

### AC-F19: CLI Integration

- [ ] `cobuilder pipeline run --help` shows all flags and docstring
- [ ] `cobuilder pipeline run nonexistent.dot` exits 1 with `Error: File not found`
- [ ] `cobuilder pipeline run pipeline.dot --resume` when no checkpoint exists: informs user and starts fresh
- [ ] `cobuilder pipeline validate pipeline.dot` delegates to engine validator (Epic 2 swaps backend)

### AC-F20: Logfire Spans

- [ ] `logfire.span("pipeline.run", pipeline_id=..., dot_path=...)` wraps the entire run
- [ ] Each node execution is wrapped in a child `logfire.span("node.execute", node_id=..., handler_type=...)`
- [ ] `outcome.status`, `outcome.metadata["tokens_used"]` (if present) added as span attributes on exit
- [ ] Spans visible in Logfire dashboard after a full pipeline run (manual verification)

---

## 7. Error Handling Strategy

### Error Taxonomy

| Error Class | Cause | Recovery |
| --- | --- | --- |
| `ParseError` | Malformed DOT file | Fatal — print error with line number, exit 1 |
| `ValidationError` | 13-rule validation failure (Epic 2) | Fatal — print rule violations, exit 1 |
| `UnknownShapeError` | Node shape not in registry | Fatal — print shape name and node ID, exit 1 |
| `HandlerError` | Handler encountered unrecoverable error | Write `ORCHESTRATOR_CRASHED` signal, checkpoint current state, exit 1 |
| `NoEdgeError` | EdgeSelector could not select any edge | Fatal — log node ID and available edges, exit 1 |
| `LoopDetectedError` | Visit count exceeded max_retries | Write `ORCHESTRATOR_STUCK` signal, checkpoint current state, exit 1 |
| `CheckpointVersionError` | Checkpoint schema version mismatch | Fatal — instruct user to delete run directory and restart |
| `TimeoutError` | CodergenHandler, ToolHandler, WaitHumanHandler timeout | Converted to `HandlerError` with timeout metadata |
| `KeyboardInterrupt` | User Ctrl+C during run | Checkpoint current state atomically, exit 130 with message "Pipeline paused. Resume with --resume." |

### Fatal vs Recoverable

**Fatal errors** (exit non-zero, no automatic retry):
- `ParseError`, `ValidationError`, `UnknownShapeError`, `NoEdgeError`, `CheckpointVersionError`
- These indicate authoring errors or configuration problems. Retrying without fixing the cause is useless.

**Recoverable on resume** (checkpoint written before exit):
- `HandlerError`, `LoopDetectedError`, `KeyboardInterrupt`, process kill (SIGTERM)
- The engine always writes the checkpoint before exiting for these cases. The next `--resume` picks up from the last completed node.

### Signal Protocol on Failure

When the engine exits with a fatal error from a handler (not a programming error), it writes a signal file so System 3 / the guardian is notified:

```python
# In EngineRunner.run() except block:
if isinstance(error, HandlerError):
    signal_protocol.write_signal(
        source="engine",
        target="guardian",
        signal_type=signal_protocol.ORCHESTRATOR_CRASHED,
        payload={
            "node_id": current_node.id,
            "error": str(error),
            "checkpoint_path": str(checkpoint_manager.checkpoint_path),
        }
    )
```

---

## 8. File Scope

### Files to Create (New)

```
cobuilder/engine/__init__.py
cobuilder/engine/runner.py           # EngineRunner — main loop
cobuilder/engine/parser.py           # DotParser — recursive-descent DOT parser
cobuilder/engine/graph.py            # Graph, Node, Edge dataclasses
cobuilder/engine/context.py          # PipelineContext
cobuilder/engine/checkpoint.py       # EngineCheckpoint Pydantic model + CheckpointManager
cobuilder/engine/edge_selector.py    # EdgeSelector + 5-step algorithm
cobuilder/engine/outcome.py          # Outcome + OutcomeStatus
cobuilder/engine/exceptions.py       # ParseError, UnknownShapeError, HandlerError, etc.

cobuilder/engine/handlers/__init__.py
cobuilder/engine/handlers/base.py    # Handler protocol
cobuilder/engine/handlers/registry.py  # HandlerRegistry
cobuilder/engine/handlers/start.py      # StartHandler (Mdiamond)
cobuilder/engine/handlers/exit.py       # ExitHandler (Msquare)
cobuilder/engine/handlers/codergen.py   # CodergenHandler (box)
cobuilder/engine/handlers/conditional.py # ConditionalHandler (diamond)
cobuilder/engine/handlers/wait_human.py  # WaitHumanHandler (hexagon)
cobuilder/engine/handlers/parallel.py   # ParallelHandler (component)
cobuilder/engine/handlers/fan_in.py     # FanInHandler (tripleoctagon)
cobuilder/engine/handlers/tool.py       # ToolHandler (parallelogram)
cobuilder/engine/handlers/manager_loop.py # ManagerLoopHandler (house)

# Stubs for Epic 2 (validation) — minimal implementations
cobuilder/engine/validation/__init__.py
cobuilder/engine/validation/validator.py  # Stub: delegates to existing cobuilder/pipeline/validator.py
cobuilder/engine/validation/rules.py      # Stub: 13 rule stubs returning (pass, "not yet implemented")

# Tests
cobuilder/engine/tests/__init__.py
cobuilder/engine/tests/conftest.py         # Shared fixtures (mock handlers, test graphs)
cobuilder/engine/tests/test_parser.py      # DotParser unit tests
cobuilder/engine/tests/test_graph.py       # Graph model tests
cobuilder/engine/tests/test_edge_selector.py # 5-step algorithm tests
cobuilder/engine/tests/test_checkpoint.py  # CheckpointManager atomic write tests
cobuilder/engine/tests/test_handlers.py    # Unit tests for all handlers
cobuilder/engine/tests/test_runner.py      # Integration test: 3-node pipeline end-to-end
cobuilder/engine/tests/test_resume.py      # Integration test: crash recovery
```

### Files to Modify (Existing)

| File | Change |
| --- | --- |
| `cobuilder/cli.py` | Add `pipeline run` subcommand (lines after line 957 where `validate` is defined). Wire to `EngineRunner`. |
| `cobuilder/pipeline/validator.py` | No change in Epic 1. Epic 2 replaces the backend implementation. CLI signature unchanged. |
| `pyproject.toml` | Ensure `pydantic>=2.0`, `logfire`, `claude_code_sdk` are in dependencies. No new external deps needed for Epic 1 itself. |

### Files NOT to Modify

| File | Reason |
| --- | --- |
| `cobuilder/orchestration/spawn_orchestrator.py` | Used as-is by CodergenHandler; no changes needed |
| `cobuilder/pipeline/signal_protocol.py` | Used as-is by handlers; no changes needed |
| `cobuilder/pipeline/transition.py` | Engine does not call transition.py (engine is read-only on DOT files) |
| `.claude/scripts/attractor/*.py` | These are the scripts-layer implementations; cobuilder/engine/ is the package-layer implementation |

---

## 9. Testing Strategy

### Testing Levels

**Level 1: Unit tests** — Pure function tests, no I/O, no LLM calls, no tmux.

Targets: `DotParser`, `EdgeSelector`, `PipelineContext`, `EngineCheckpoint` serialisation/deserialisation, individual handler logic with mock contexts.

Framework: `pytest`. No async framework overhead needed for unit tests since handlers are tested with `asyncio.run()`.

**Level 2: Integration tests** — In-process integration with mocked external calls.

The `CodergenHandler` has a `_spawner` dependency injected in tests:

```python
# In tests/conftest.py:
@pytest.fixture
def mock_spawner():
    """Replaces spawn_orchestrator.py calls with immediate VALIDATION_PASSED signal."""
    async def _spawn(node_id, prd, repo_root, **kwargs):
        return {"status": "ok", "session": f"orch-{node_id}"}
    return _spawn

@pytest.fixture
def mock_signal_poller():
    """Returns VALIDATION_PASSED immediately without polling the filesystem."""
    async def _poll(target_layer, timeout, signals_dir, poll_interval):
        return {
            "source": "runner",
            "target": "guardian",
            "signal_type": "VALIDATION_PASSED",
            "payload": {"node_id": "test_node"},
        }
    return _poll
```

The 3-node pipeline test (`test_runner.py::test_linear_pipeline_end_to_end`) uses these fixtures to run a complete traversal without any tmux or LLM involvement.

**Level 3: Checkpoint/Resume integration tests**

`test_resume.py` simulates a crash by:
1. Running the engine until node 2 of a 3-node pipeline (using a handler that raises `HandlerError` on node 2's first call)
2. Verifying `checkpoint.json` contains `completed_nodes=["start"]` and `current_node_id="node2"`
3. Running the engine again with `--resume` using a handler that succeeds on node 2
4. Verifying the pipeline completes and `completed_nodes=["start", "node2", "exit"]`

### Test File Corpus

The tests use existing `.dot` files from `.pipelines/pipelines/` as a parse regression corpus:

```python
# test_parser.py:
import glob

DOT_CORPUS = glob.glob(".pipelines/pipelines/*.dot")

@pytest.mark.parametrize("dot_file", DOT_CORPUS)
def test_parser_handles_existing_pipelines(dot_file):
    """All existing DOT files must parse without error."""
    from cobuilder.engine.parser import DotParser
    parser = DotParser()
    graph = parser.parse_file(dot_file)
    assert len(graph.nodes) > 0
```

This ensures the new parser is backward-compatible with all existing pipelines.

### Coverage Targets

| Module | Coverage Target |
| --- | --- |
| `parser.py` | 95% (critical path) |
| `edge_selector.py` | 100% (pure function, must cover all 5 steps) |
| `checkpoint.py` | 95% (atomic write path + error paths) |
| `handlers/` (all) | 85% minimum |
| `runner.py` | 80% (complex async loop) |

### Pytest Command

```bash
# From cobuilder/engine/tests/:
pytest cobuilder/engine/tests/ -v --asyncio-mode=auto

# With coverage:
pytest cobuilder/engine/tests/ --cov=cobuilder.engine --cov-report=term-missing
```

The `asyncio-mode=auto` flag (from `pytest-asyncio`) is required because handlers are `async def`.

---

## 10. Implementation Phases

### Phase 1 — Foundation (days 1–2)

Deliverables: `graph.py`, `outcome.py`, `context.py`, `exceptions.py`, `parser.py`, `test_parser.py`, `test_graph.py`

Success criteria: Parser handles all existing DOT files in `.pipelines/pipelines/`. `PipelineContext` thread-safety tests pass.

Dependencies: None.

### Phase 2 — Handler Infrastructure (days 2–3)

Deliverables: `handlers/base.py`, `handlers/registry.py`, `handlers/start.py`, `handlers/exit.py`, `handlers/conditional.py`

Success criteria: Registry dispatches correctly for all 9 shapes. Start and Exit handlers unit tests pass. Conditional handler unit tests pass.

Dependencies: Phase 1.

### Phase 3 — EdgeSelector and Checkpoint (days 3–4)

Deliverables: `edge_selector.py`, `checkpoint.py`, `test_edge_selector.py`, `test_checkpoint.py`

Success criteria: All 5 EdgeSelector steps tested with explicit fixtures. Atomic write verified by simulating a process kill between tmp write and rename. Schema version mismatch raises `CheckpointVersionError`.

Dependencies: Phase 1.

### Phase 4 — CodergenHandler and EngineRunner (days 4–6)

Deliverables: `handlers/codergen.py`, `runner.py`, `test_runner.py`, `test_resume.py`

Success criteria: 3-node linear pipeline traversal test passes with mock spawner. Resume test passes.

Dependencies: Phases 1–3.

### Phase 5 — Remaining Handlers and CLI (days 6–8)

Deliverables: `handlers/wait_human.py`, `handlers/parallel.py`, `handlers/fan_in.py`, `handlers/tool.py`, `handlers/manager_loop.py`, CLI `run` subcommand, `test_handlers.py`

Success criteria: All handler unit tests pass. `cobuilder pipeline run --help` works. `cobuilder pipeline run` with `--resume` against a non-existent checkpoint informs user and starts fresh.

Dependencies: Phase 4.

### Phase 6 — Logfire integration and Validation stub (days 8–9)

Deliverables: Inline Logfire spans in `runner.py` and `handlers/codergen.py`, `validation/validator.py` stub, `validation/rules.py` stubs

Success criteria: Running a pipeline creates visible spans in Logfire dashboard. `cobuilder pipeline validate` still works (delegates to existing `cobuilder/pipeline/validator.py`).

Dependencies: Phase 4.

---

## 11. Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
| --- | --- | --- | --- |
| DOT parser fails on edge cases in existing pipelines | High | Medium | Use corpus test over all `.pipelines/pipelines/*.dot` files from day 1. Fix parser before proceeding to runner. |
| `asyncio.TaskGroup` fan-out leaves zombied tmux sessions on cancellation | High | Medium | `ParallelHandler` catches `asyncio.CancelledError` and writes `KILL_ORCHESTRATOR` signal for each abandoned session. |
| CodergenHandler signal polling blocks the event loop | Medium | High | All polling is `async` with `await asyncio.sleep(poll_interval)` — never `time.sleep()`. |
| Checkpoint writes fail on full disk | Medium | Low | `CheckpointManager.save()` catches `OSError`, logs error, but does NOT crash the engine — it continues and retries the next checkpoint. Losing a checkpoint is recoverable; crashing is not. |
| `claude_code_sdk` SDK dispatch not available in all environments | Low | Medium | `dispatch_strategy=sdk` falls back to tmux with a warning log when `claude_code_sdk` is not importable. |
| Resume incorrectly re-executes completed nodes | High | Low | Resume logic compares `checkpoint.completed_nodes` against graph nodes. If the graph was modified between run and resume, `CheckpointManager` raises `CheckpointGraphMismatchError`. |
| ManagerLoopHandler recursive engine causes stack overflow on deep nesting | Low | Low | ManagerLoopHandler uses a subprocess-based sub-engine (separate process) rather than recursive in-process call. Depth is bounded by process memory, not call stack. |

---

## 12. Handoff Notes for Implementation

### Key Invariants the Implementer Must Maintain

1. **The engine never writes to the DOT file.** DOT files are read-only input. The engine writes only to its run directory. State lives in `EngineCheckpoint`, not in DOT attribute mutations.

2. **Every ****`await`**** in the handler path must be inside the ****`logfire.span()`**** context.** This ensures Logfire correctly attributes all async work to the right span.

3. **`CheckpointManager.save()`**** must be called before advancing ****`current_node_id`****.** The sequence is: complete node → record outcome → save checkpoint with `current_node_id` set to the next node → advance. If the process dies between save and advance, the next resume will re-execute the next node (idempotent for StartHandler, ConditionalHandler, ToolHandler; acceptable for CodergenHandler since tmux session naming ensures deduplication).

4. **`PipelineContext.snapshot()`**** (not the live context) is passed to ****`EdgeSelector.select()`****.** This prevents edge condition evaluation from seeing context mutations from parallel branches.

5. **Handler implementations must be stateless.** All state is passed in via `node` and `context` arguments. Handlers must not hold instance state that persists between `execute()` calls. This is enforced by convention (the registry creates a new handler instance per dispatch — OR uses a single shared instance; since they are stateless, both are correct).

### Integration Test to Run Before Merging

```bash
# Minimal smoke test — must pass before any PR is merged:
pytest cobuilder/engine/tests/test_runner.py::test_linear_pipeline_end_to_end -v
pytest cobuilder/engine/tests/test_resume.py::test_resume_from_node2 -v
pytest cobuilder/engine/tests/test_parser.py -v  # includes corpus test
```

---

## Appendix A: Community Patterns Adopted

| Pattern | Source | Where Used |
| --- | --- | --- |
| Custom recursive-descent DOT parser | samueljklee + attractor-c | `cobuilder/engine/parser.py` |
| `Handler.execute(node, context) → Outcome` protocol | brynary | `cobuilder/engine/handlers/base.py` |
| 5-step edge selection algorithm | Scala/Ruby/Python community standard | `cobuilder/engine/edge_selector.py` |
| JSON checkpoint with atomic write-then-rename | All 10 implementations | `cobuilder/engine/checkpoint.py` |
| `asyncio.TaskGroup` for parallel fan-out | Scala/Cats-Effect adapted to Python | `cobuilder/engine/handlers/parallel.py` |
| Per-node visit counter in context | Multiple implementations | `PipelineContext.increment_visit()` |
| Logfire middleware wrapping handler execution | samueljklee middleware chain | Inline spans in `runner.py` (full middleware chain in Epic 4) |
| Git-native checkpointing (optional) | Kilroy | `ATTRACTOR_GIT_COMMIT_PER_NODE=1` environment variable hook point |

## Appendix B: Environment Variables

| Variable | Default | Effect |
| --- | --- | --- |
| `ATTRACTOR_ORCHESTRATOR_TIMEOUT` | `1800` | Seconds before CodergenHandler raises TimeoutError |
| `ATTRACTOR_SIGNAL_POLL_INTERVAL` | `10` | Seconds between signal file polls in CodergenHandler |
| `ATTRACTOR_TOOL_TIMEOUT` | `300` | Seconds before ToolHandler raises TimeoutError |
| `ATTRACTOR_HUMAN_GATE_TIMEOUT` | `0` | Seconds before WaitHumanHandler times out (0 = indefinite) |
| `ATTRACTOR_GIT_COMMIT_PER_NODE` | `0` | If `1`, create a git commit after each successful node |
| `ATTRACTOR_RUN_DIR_ROOT` | `.pipelines/pipelines` | Base directory for run directories |
| `ATTRACTOR_SIGNALS_DIR` | git-root auto-detected | Override signals directory (existing signal_protocol.py convention) |
