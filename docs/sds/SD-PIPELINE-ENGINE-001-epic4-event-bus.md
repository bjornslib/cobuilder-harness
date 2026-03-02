---
title: "SD-PIPELINE-ENGINE-001 Epic 4: Structured Event Bus with Logfire Integration"
status: active
type: solution-design
last_verified: 2026-02-28
grade: authoritative
---

# SD-PIPELINE-ENGINE-001 Epic 4: Structured Event Bus with Logfire Integration

## 1. Business Context

### Problem Statement

Pipeline execution currently produces observability only through tmux `capture-pane` output — raw text that System 3 must parse manually or poll indirectly. There is no structured record of what happened inside a pipeline run, when each node started and finished, how many tokens were consumed, or why an edge was taken. When a pipeline stalls or crashes, diagnosis requires reading tmux scrollback and correlating it with signal files.

This epic bridges that gap. It delivers a structured event bus that emits typed events at every lifecycle point in pipeline execution, feeds those events into Logfire parent/child spans, writes a local JSONL audit trail, and bridges critical events back to the existing signal protocol that System 3 and the Guardian already monitor. Observability becomes first-class rather than an afterthought.

### Strategic Value

| Stakeholder | Benefit |
|-------------|---------|
| System 3 (meta-orchestrator) | Monitors pipeline health via Logfire dashboard instead of tmux capture |
| Guardian agent | Receives `pipeline.completed` and `node.failed` via signal bridge without polling |
| Developers debugging failed runs | JSONL event log provides complete replay of what happened |
| Cost-tracking | Per-node and per-pipeline token totals available in pipeline context as `$total_tokens` |

### Relationship to Other Epics

Epic 4 is not an isolated feature. It is the observability layer that wraps Epics 1, 2, and 3:
- The **middleware chain** (Epic 4) wraps the **handler dispatch** (Epic 1) to intercept every handler invocation
- The **event emitter** (Epic 4) is called by the **execution loop** (Epic 1) after each node, edge, and checkpoint
- The **SignalBridge** backend (Epic 4) feeds the **signal protocol** (existing infrastructure) so the Guardian's existing polling loop continues to work unchanged

Epic 4 does not replace `signal_protocol.py`. The signal protocol is authoritative for inter-layer communication. The event bus supplements it by adding richer structured data and Logfire visibility.

---

## 2. Technical Architecture

### 2.1 Architectural Layers

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  EXECUTION LOOP (engine/runner.py)                                          │
│  Calls emit() at each lifecycle point: node start, node complete,           │
│  edge selected, checkpoint saved, pipeline started/completed/failed         │
├─────────────────────────────────────────────────────────────────────────────┤
│  MIDDLEWARE CHAIN (engine/middleware/chain.py)                              │
│  Wraps every handler.execute() call through a composable async chain       │
│  Chain: LogfireMiddleware → TokenCountingMiddleware → RetryMiddleware →     │
│          AuditMiddleware → actual Handler                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  EVENT EMITTER (engine/events/emitter.py)                                  │
│  CompositeEmitter fans out to all configured backends                       │
├────────────────┬───────────────┬────────────────────────────────────────────┤
│  LogfireEmitter│  JSONLEmitter │  SignalBridge      │  SSEEmitter (future) │
│  logfire spans │  .jsonl file  │  signal_protocol   │  web dashboard       │
└────────────────┴───────────────┴────────────────────┴──────────────────────┘
```

### 2.2 Event Taxonomy (14 Types)

The 14 event types are derived from the samueljklee Python implementation (12 types) and extended with two Attractor-spec-required events (`checkpoint.saved`, `loop.detected`):

| # | Event Type | Emitter Location | Key Payload Fields |
|---|-----------|------------------|--------------------|
| 1 | `pipeline.started` | `runner.py` before loop | `pipeline_id`, `dot_path`, `node_count` |
| 2 | `pipeline.completed` | `runner.py` after exit handler | `pipeline_id`, `duration_ms`, `total_tokens` |
| 3 | `pipeline.failed` | `runner.py` on fatal error | `pipeline_id`, `error_type`, `error_message`, `last_node_id` |
| 4 | `pipeline.resumed` | `runner.py` when checkpoint loaded | `pipeline_id`, `checkpoint_path`, `completed_node_count` |
| 5 | `node.started` | `middleware/logfire.py` pre-call | `node_id`, `handler_type`, `visit_count` |
| 6 | `node.completed` | `middleware/logfire.py` post-call | `node_id`, `outcome_status`, `duration_ms`, `tokens_used` |
| 7 | `node.failed` | `middleware/logfire.py` on failure | `node_id`, `error_type`, `goal_gate`, `retry_target` |
| 8 | `edge.selected` | `runner.py` after edge selection | `from_node_id`, `to_node_id`, `selection_step`, `condition` |
| 9 | `checkpoint.saved` | `checkpoint.py` after atomic write | `pipeline_id`, `checkpoint_path`, `node_id` |
| 10 | `context.updated` | `runner.py` after merging outcome.context_updates | `pipeline_id`, `node_id`, `keys_added`, `keys_modified` |
| 11 | `retry.triggered` | `middleware/retry.py` before retry | `node_id`, `attempt_number`, `backoff_ms`, `error_type` |
| 12 | `loop.detected` | `loop_detection.py` on limit breach | `node_id`, `visit_count`, `limit`, `pattern_detected` |
| 13 | `validation.started` | `validation/validator.py` | `pipeline_id`, `rule_count` |
| 14 | `validation.completed` | `validation/validator.py` | `pipeline_id`, `errors`, `warnings`, `passed` |

**Design principle**: Events are informational. They describe what happened — they do not drive control flow. The execution loop still advances through its own logic; events are side-effects of that logic.

### 2.3 Emitter Protocol

The `EventEmitter` is a structural protocol — any class implementing `emit()` and `aclose()` qualifies. This enables test doubles and custom backends without subclassing:

```python
class EventEmitter(Protocol):
    async def emit(self, event: PipelineEvent) -> None: ...
    async def aclose(self) -> None: ...
```

The `CompositeEmitter` holds a list of backends and fans out each `emit()` call to all of them concurrently using `asyncio.gather()` with `return_exceptions=True`, ensuring one failing backend never blocks others:

```python
class CompositeEmitter:
    def __init__(self, backends: list[EventEmitter]) -> None:
        self._backends = backends

    async def emit(self, event: PipelineEvent) -> None:
        results = await asyncio.gather(
            *[b.emit(event) for b in self._backends],
            return_exceptions=True,
        )
        for backend, result in zip(self._backends, results):
            if isinstance(result, Exception):
                logger.warning("Emitter %s failed: %s", type(backend).__name__, result)

    async def aclose(self) -> None:
        await asyncio.gather(*[b.aclose() for b in self._backends], return_exceptions=True)
```

### 2.4 Middleware Chain Pattern

The middleware chain pattern is borrowed directly from samueljklee's Python implementation. Each middleware is an async callable that receives a `HandlerRequest` and a `next` callable. Middleware composition is right-to-left: the first middleware in the list is the outermost wrapper.

```
request → LogfireMiddleware → TokenCountingMiddleware → RetryMiddleware → AuditMiddleware → Handler
response ←─────────────────────────────────────────────────────────────────────────────────────────
```

This makes each cross-cutting concern independently testable: you can test `TokenCountingMiddleware` by passing a mock `next` callable, without needing a real handler or Logfire connection.

### 2.5 Logfire Span Design

The Logfire integration creates a two-level span hierarchy:

```
logfire.span("pipeline.{pipeline_id}") as pipeline_span:
    pipeline_span.set_attribute("pipeline_id", ...)
    pipeline_span.set_attribute("dot_path", ...)

    for each node:
        with logfire.span("node.{node_id}") as node_span:
            node_span.set_attribute("node_id", ...)
            node_span.set_attribute("handler_type", ...)
            # handler executes here
            node_span.set_attribute("outcome_status", ...)
            node_span.set_attribute("duration_ms", ...)
            node_span.set_attribute("tokens_used", ...)
```

The pipeline-level span context is held in the `LogfireEmitter` instance and passed to node spans via standard Logfire context propagation. The `span_id` of the active node span is injected into every `PipelineEvent` emitted during that node's execution, enabling correlation between JSONL events and Logfire spans.

**Existing Logfire configuration pattern** (from `guardian_agent.py` and `runner_agent.py`) is reused unchanged:

```python
import logfire
logfire.configure(
    inspect_arguments=False,
    scrubbing=logfire.ScrubbingOptions(callback=lambda m: m.value),
)
```

This configuration is called once at module load in `cobuilder/engine/__init__.py` or in the CLI entrypoint, not in each backend class.

### 2.6 Signal Bridge Design

The `SignalBridge` backend translates a subset of pipeline events to signal files using the existing `signal_protocol.write_signal()` function. Only events with S3-relevant meaning are translated — not every event becomes a signal:

| Pipeline Event | Signal Type | Source → Target | When |
|---------------|-------------|-----------------|------|
| `pipeline.completed` | `NODE_COMPLETE` (or new `PIPELINE_COMPLETE`) | `engine` → `guardian` | Pipeline exits successfully |
| `node.failed` where `goal_gate=true` | `VIOLATION` | `engine` → `guardian` | Critical node failure |
| `loop.detected` | `ORCHESTRATOR_STUCK` | `engine` → `guardian` | Visit limit exceeded |
| `pipeline.failed` | `ORCHESTRATOR_CRASHED` | `engine` → `guardian` | Fatal pipeline error |

The `SignalBridge` constructor accepts `signals_dir` (optional, defaults to `_default_signals_dir()` from `signal_protocol.py`) and `pipeline_id`. It holds no state beyond these and is fully reentrant.

---

## 3. Functional Decomposition

### Feature F1: PipelineEvent Type System (`events/types.py`)

Define the canonical `PipelineEvent` dataclass and all 14 event-type constants. This module has no runtime dependencies beyond the standard library and dataclasses.

**Deliverables**:
- `PipelineEvent` dataclass (frozen, `slots=True` for minimal overhead)
- `EventType` `Literal` type alias covering all 14 string constants
- `EventBuilder` helper class with factory methods like `EventBuilder.node_started(node_id, handler_type, visit_count)` that construct valid `PipelineEvent` instances without repeating boilerplate

**Rationale for factory methods**: Emitter call sites in `runner.py` and the middleware chain should not construct `PipelineEvent` dicts by hand — this spreads the event schema across the codebase and makes future schema changes brittle.

### Feature F2: CompositeEmitter and Protocol (`events/emitter.py`)

Implement the `EventEmitter` protocol and `CompositeEmitter`. Includes `NullEmitter` (for testing without any backends), and the public `build_emitter(config)` factory that instantiates the correct set of backends based on configuration.

### Feature F3: Logfire Backend (`events/logfire_backend.py`)

Implement `LogfireEmitter` which:
1. Opens a pipeline-level span on `pipeline.started` and holds it in instance state
2. Opens a node-level child span on `node.started`, attaches it to the instance map keyed by `node_id`
3. Sets structured attributes on the node span for `node.completed` and `node.failed`
4. Closes the node span on `node.completed` or `node.failed`
5. Closes the pipeline span on `pipeline.completed` or `pipeline.failed`
6. Injects the current active span ID into emitted events via `logfire.get_current_span().context.span_id`

**State held**: `_pipeline_span` (one per emitter instance), `_node_spans: dict[str, logfire.Span]` (open node spans).

**Thread safety**: The emitter is async-only. Node spans are keyed by `node_id`; parallel fan-out nodes each open their own span and close it independently.

### Feature F4: JSONL Backend (`events/jsonl_backend.py`)

Implement `JSONLEmitter` which:
1. Opens the JSONL file on construction (append mode)
2. Serialises each `PipelineEvent` to a single JSON line using `dataclasses.asdict()` + `json.dumps()`
3. Flushes after every write to ensure events are durable even if the process crashes
4. Closes the file handle on `aclose()`

**File path**: `{run_dir}/pipeline-events.jsonl` where `run_dir` is the existing checkpoint run directory (e.g., `attractor-logs/run-{timestamp}/`).

### Feature F5: Signal Bridge Backend (`events/signal_bridge.py`)

Implement `SignalBridge` which translates the 4 critical event types to `signal_protocol.write_signal()` calls. Ignores all other event types silently. Stores no spans or open file handles — purely stateless beyond `pipeline_id` and `signals_dir`.

### Feature F6: Middleware Chain (`middleware/chain.py`)

Implement `compose_middleware(middlewares: list[Middleware], handler: Handler) -> Callable`:

```python
def compose_middleware(middlewares, handler):
    async def execute(request: HandlerRequest) -> Outcome:
        return await handler.execute(request.node, request.context)

    for mw in reversed(middlewares):
        inner = execute
        async def execute(request, _mw=mw, _inner=inner):  # noqa: E731
            return await _mw(request, _inner)

    return execute
```

The `HandlerRequest` dataclass carries `node`, `context`, `emitter`, `pipeline_id`, and `visit_count` so that middlewares can emit events and access context without needing additional injection.

### Feature F7: Logfire Middleware (`middleware/logfire.py`)

Implement `LogfireMiddleware` which:
1. Emits `node.started` via `request.emitter` before calling `next`
2. Opens a `logfire.span(f"handler.{request.node.id}")` context
3. Calls `next(request)` inside the span
4. Emits `node.completed` or `node.failed` after `next` returns (or raises)
5. Sets span attributes: `outcome_status`, `duration_ms`, `handler_type`

This middleware is the primary source of `node.started` and `node.completed` events — it should not be duplicated in the execution loop.

### Feature F8: Token Counting Middleware (`middleware/token_counter.py`)

Implement `TokenCountingMiddleware` which:
1. Intercepts `claude_code_sdk` output messages from `CodergenHandler` via the `context` accumulation pattern
2. Reads `usage.input_tokens` and `usage.output_tokens` from SDK `ResultMessage` objects
3. Accumulates totals into `context["$node_tokens"]` and `context["$total_tokens"]`
4. Emits `context.updated` event after accumulation

**Implementation note**: The token counts come from the SDK message stream. `CodergenHandler` must propagate raw SDK messages up through the `Outcome` object so this middleware can extract them. The `Outcome` model gains an optional `raw_messages: list[Any]` field for this purpose.

### Feature F9: Retry Middleware (`middleware/retry.py`)

Implement `RetryMiddleware` which:
1. Calls `next(request)` and checks if `Outcome.status == FAILURE`
2. If FAILURE and `attempt < max_attempts`: emits `retry.triggered`, sleeps for `backoff_ms` (exponential: `base * 2^attempt`), then calls `next(request)` again
3. If attempts exhausted: returns the final FAILURE `Outcome` without re-raising
4. `max_attempts` defaults to the node's `max_retries` attribute, fallback to `RetryMiddleware.default_max_retries` (3)

**Not responsible for loop detection** — that is `loop_detection.py`'s responsibility. The retry middleware handles within-node transient failures; loop detection handles cross-node visit counts.

### Feature F10: Audit Middleware (`middleware/audit.py`)

Implement `AuditMiddleware` which wraps `ChainedAuditWriter` from the existing `anti_gaming.py`:
1. Constructs an `AuditEntry` from `HandlerRequest` before calling `next` (`from_status="pending"`, `to_status="active"`)
2. Calls `next(request)`
3. Writes a second `AuditEntry` after completion (`from_status="active"`, `to_status` = outcome status)

The `AuditMiddleware` is the only component that touches `ChainedAuditWriter` — the writer is injected via constructor, not created internally, enabling test injection.

---

## 4. API Contracts

### 4.1 EventEmitter Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class EventEmitter(Protocol):
    async def emit(self, event: PipelineEvent) -> None:
        """Emit one pipeline event.

        Must not raise. Backend failures should be caught internally and
        logged at WARNING level without propagating to the execution loop.
        """
        ...

    async def aclose(self) -> None:
        """Flush and close any open resources (file handles, spans).

        Called once at pipeline completion or on fatal failure.
        Must be idempotent — calling twice must not raise.
        """
        ...
```

### 4.2 Middleware Protocol

```python
from typing import Protocol, Callable, Awaitable

class Middleware(Protocol):
    async def __call__(
        self,
        request: HandlerRequest,
        next: Callable[[HandlerRequest], Awaitable[Outcome]],
    ) -> Outcome:
        """Process a handler request.

        Must call next(request) exactly once (unless implementing retry logic
        that calls it multiple times). Must not swallow exceptions from next()
        unless retry logic dictates returning a FAILURE Outcome instead.
        """
        ...
```

### 4.3 SignalBridge Public Interface

```python
class SignalBridge:
    def __init__(
        self,
        pipeline_id: str,
        signals_dir: str | None = None,  # defaults to signal_protocol._default_signals_dir()
    ) -> None: ...

    async def emit(self, event: PipelineEvent) -> None:
        """Translate event to signal file if event type is bridge-eligible.

        Eligible types: pipeline.completed, pipeline.failed,
                        node.failed (goal_gate only), loop.detected.
        All other event types are silently ignored.
        """
        ...

    async def aclose(self) -> None:
        """No-op. SignalBridge holds no open resources."""
        ...
```

### 4.4 CompositeEmitter Factory

```python
@dataclass
class EventBusConfig:
    logfire_enabled: bool = True
    jsonl_path: str | None = None       # None = auto-derive from run_dir
    signal_bridge_enabled: bool = True
    signals_dir: str | None = None      # None = use signal_protocol default
    sse_enabled: bool = False           # Future; no-op when False

def build_emitter(
    pipeline_id: str,
    run_dir: str,
    config: EventBusConfig | None = None,
) -> CompositeEmitter:
    """Construct and return a CompositeEmitter with configured backends.

    Called once per pipeline run in engine/runner.py before the execution
    loop begins. The returned emitter must be closed via aclose() in a
    finally block regardless of pipeline outcome.
    """
    ...
```

---

## 5. Data Models

### 5.1 PipelineEvent

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

EventType = Literal[
    "pipeline.started",
    "pipeline.completed",
    "pipeline.failed",
    "pipeline.resumed",
    "node.started",
    "node.completed",
    "node.failed",
    "edge.selected",
    "checkpoint.saved",
    "context.updated",
    "retry.triggered",
    "loop.detected",
    "validation.started",
    "validation.completed",
]

@dataclass(frozen=True, slots=True)
class PipelineEvent:
    type: EventType
    timestamp: datetime                  # UTC; always timezone-aware
    pipeline_id: str                     # DOT graph identifier
    node_id: str | None                  # None for pipeline-level events
    data: dict[str, Any]                 # Event-type-specific payload
    span_id: str | None = None           # Logfire span ID for correlation
    sequence: int = 0                    # Monotonic counter per pipeline run
```

**Serialisation**: `dataclasses.asdict()` produces a JSON-serialisable dict when `timestamp` is replaced by `timestamp.isoformat()`. The `JSONLEmitter` performs this replacement before writing.

**Immutability**: `frozen=True` prevents accidental mutation after construction. The `data` dict is validated at construction time in `EventBuilder` factory methods.

### 5.2 HandlerRequest

```python
@dataclass
class HandlerRequest:
    node: Node                           # From engine/graph.py
    context: PipelineContext             # Mutable accumulated state
    emitter: EventEmitter                # For middleware-initiated events
    pipeline_id: str
    visit_count: int                     # Current visit count for this node
    attempt_number: int = 0             # Current retry attempt (0 = first)
    run_dir: str = ""                    # For checkpoint-relative paths
```

### 5.3 SpanConfig

```python
@dataclass
class SpanConfig:
    """Configuration for Logfire span naming and attribute mapping."""
    pipeline_span_name: str = "pipeline.{pipeline_id}"
    node_span_name: str = "node.{node_id}"
    # Attributes set on the pipeline-level span
    pipeline_attrs: tuple[str, ...] = (
        "pipeline_id", "dot_path", "node_count", "resume"
    )
    # Attributes set on each node-level span
    node_attrs: tuple[str, ...] = (
        "node_id", "handler_type", "visit_count",
        "outcome_status", "duration_ms", "tokens_used", "goal_gate",
    )
```

### 5.4 EventBuilder (Factory)

```python
class EventBuilder:
    """Factory methods that produce valid PipelineEvent instances.

    Centralises event schema knowledge. Call sites in runner.py and
    middleware modules use these methods rather than constructing
    PipelineEvent directly.
    """

    _counter: int = 0  # module-level monotonic sequence counter

    @classmethod
    def pipeline_started(cls, pipeline_id: str, dot_path: str, node_count: int) -> PipelineEvent:
        return cls._build("pipeline.started", pipeline_id, None, {
            "dot_path": dot_path, "node_count": node_count,
        })

    @classmethod
    def node_started(cls, pipeline_id: str, node_id: str, handler_type: str, visit_count: int) -> PipelineEvent:
        return cls._build("node.started", pipeline_id, node_id, {
            "handler_type": handler_type, "visit_count": visit_count,
        })

    @classmethod
    def node_completed(
        cls, pipeline_id: str, node_id: str,
        outcome_status: str, duration_ms: float,
        tokens_used: int = 0, span_id: str | None = None,
    ) -> PipelineEvent:
        return cls._build("node.completed", pipeline_id, node_id, {
            "outcome_status": outcome_status,
            "duration_ms": duration_ms,
            "tokens_used": tokens_used,
        }, span_id=span_id)

    # ... analogous factory methods for all 14 event types ...

    @classmethod
    def _build(
        cls, event_type: EventType, pipeline_id: str, node_id: str | None,
        data: dict, span_id: str | None = None,
    ) -> PipelineEvent:
        cls._counter += 1
        return PipelineEvent(
            type=event_type,
            timestamp=datetime.now(timezone.utc),
            pipeline_id=pipeline_id,
            node_id=node_id,
            data=data,
            span_id=span_id,
            sequence=cls._counter,
        )
```

---

## 6. Acceptance Criteria Per Feature

### F1: PipelineEvent Type System
- [ ] `PipelineEvent` is frozen and slot-based; construction raises `TypeError` on unknown event type
- [ ] All 14 `EventType` literals are defined; no additional string types accepted
- [ ] `EventBuilder` provides a factory method for every event type
- [ ] `EventBuilder._build()` always produces a timezone-aware UTC `timestamp`
- [ ] `sequence` counter is monotonically increasing across all events in a process

### F2: CompositeEmitter
- [ ] `CompositeEmitter.emit()` fans out to all backends concurrently via `asyncio.gather`
- [ ] One backend failing does not prevent other backends from receiving the event
- [ ] `NullEmitter` is available for tests; accepts all events, stores nothing
- [ ] `build_emitter()` constructs correct set of backends based on `EventBusConfig` flags
- [ ] `aclose()` calls `aclose()` on all backends regardless of individual failures

### F3: Logfire Backend
- [ ] `pipeline.started` opens a pipeline-level span; span remains open until `pipeline.completed` or `pipeline.failed`
- [ ] `node.started` opens a node-level child span under the pipeline span
- [ ] `node.completed` sets `outcome_status`, `duration_ms`, `tokens_used` on the node span and closes it
- [ ] `node.failed` records exception info on the span and closes it
- [ ] `span_id` from the active node span is injected into all events emitted during that node (verified by checking `PipelineEvent.span_id` in test)
- [ ] Parallel fan-out nodes each get their own independent child span
- [ ] All span attribute keys match `SpanConfig.node_attrs` exactly

### F4: JSONL Backend
- [ ] File is opened in append mode; existing events are preserved on resume
- [ ] Each event produces exactly one newline-terminated JSON line
- [ ] File is flushed after every write
- [ ] `timestamp` is serialised as ISO-8601 string
- [ ] `aclose()` closes the file handle; subsequent `emit()` calls raise `ValueError`
- [ ] File path is `{run_dir}/pipeline-events.jsonl`

### F5: Signal Bridge
- [ ] `pipeline.completed` writes a signal with `signal_type = "NODE_COMPLETE"` (or `"PIPELINE_COMPLETE"` when that constant is added to `signal_protocol.py`)
- [ ] `node.failed` with `data["goal_gate"] == True` writes `VIOLATION` signal
- [ ] `loop.detected` writes `ORCHESTRATOR_STUCK` signal
- [ ] `pipeline.failed` writes `ORCHESTRATOR_CRASHED` signal
- [ ] All other event types produce no signal file
- [ ] Signal payload includes `pipeline_id` and `node_id` where applicable
- [ ] Signal is written atomically (delegated to `signal_protocol.write_signal`)

### F6: Middleware Chain
- [ ] `compose_middleware([], handler)` returns a callable equivalent to calling `handler.execute` directly
- [ ] `compose_middleware([A, B], handler)` calls A, then B, then handler in that order (verified with call-order capture test)
- [ ] Exception from `handler.execute` propagates through all middlewares unless a middleware catches it
- [ ] Each middleware receives a fresh `next` callable bound to the remainder of the chain

### F7: Logfire Middleware
- [ ] `node.started` event emitted before `next()` is called
- [ ] `node.completed` event emitted after `next()` returns with `SUCCESS` or `PARTIAL_SUCCESS`
- [ ] `node.failed` event emitted after `next()` returns with `FAILURE`
- [ ] `duration_ms` reflects wall-clock time from before `next()` to after it returns
- [ ] Events carry the active Logfire span ID in `span_id`

### F8: Token Counting Middleware
- [ ] `$node_tokens` in context reflects token usage for the most recently completed node
- [ ] `$total_tokens` in context is a running sum across all completed nodes
- [ ] Token counting is a no-op when handler does not provide `raw_messages` in `Outcome`
- [ ] `context.updated` event emitted when `$total_tokens` changes

### F9: Retry Middleware
- [ ] `retry.triggered` event emitted before each retry attempt
- [ ] Backoff is exponential: attempt 1 → 1s, attempt 2 → 2s, attempt 3 → 4s (configurable base)
- [ ] Max retries defaults to node's `max_retries` attribute; `RetryMiddleware.default_max_retries = 3` if not set
- [ ] After exhausting retries, final `FAILURE` Outcome is returned (not re-raised)
- [ ] If `next()` raises an exception (not FAILURE outcome), the exception propagates without retry unless `retry_on_exception=True`

### F10: Audit Middleware
- [ ] Two `AuditEntry` records written per node: one before execution, one after
- [ ] `from_status` / `to_status` pair reflects actual node lifecycle transition
- [ ] `ChainedAuditWriter` failure does not propagate — audit middleware catches `OSError` and warns
- [ ] `agent_id` in `AuditEntry` matches `request.context["$session_id"]` if present

---

## 7. Error Handling

### Principle: Never Kill the Pipeline

The event bus is an observability system. A backend failure must never cause a handler failure or stop pipeline execution. This principle is enforced at three levels:

1. **`CompositeEmitter.emit()`**: Uses `asyncio.gather(..., return_exceptions=True)`. Backend exceptions are logged at `WARNING` level and discarded.

2. **`LogfireEmitter`**: Wraps all Logfire calls in try/except. If Logfire is unreachable (network error, invalid credentials), the emitter logs once and operates in no-op mode for the rest of the run.

3. **`AuditMiddleware`**: Already follows this pattern in `ChainedAuditWriter.write()` — catches `OSError` and warns without re-raising.

### Backend-Specific Error Handling

| Backend | Error Scenario | Response |
|---------|---------------|----------|
| `LogfireEmitter` | Logfire API unavailable | Warn once, all subsequent `emit()` calls are no-ops |
| `LogfireEmitter` | Span already closed (double-close) | Catch `logfire.SpanAlreadyClosedError` if raised; no-op |
| `JSONLEmitter` | Disk full / permission error | Warn on first failure; no-op for rest of run |
| `JSONLEmitter` | File not yet open | `ValueError: emitter is closed` raised (programming error) |
| `SignalBridge` | `signal_protocol.write_signal` raises | Warn; do not retry (signals are best-effort for observability) |

### Middleware Error Handling

| Middleware | Error Scenario | Response |
|-----------|---------------|----------|
| `LogfireMiddleware` | `next()` raises `Exception` | Re-raise after closing the node span with `record_exception=True` |
| `RetryMiddleware` | `next()` returns FAILURE | Retry up to `max_retries`; return final FAILURE after exhaustion |
| `RetryMiddleware` | `next()` raises `Exception` | By default, propagate. Set `retry_on_exception=True` to retry |
| `AuditMiddleware` | `ChainedAuditWriter.write()` raises | Warn, continue — audit failure is non-fatal |
| `TokenCountingMiddleware` | No `raw_messages` in `Outcome` | Skip silently; context unchanged |

### Event Emission Failure on Fatal Events

If emitting `pipeline.failed` itself raises an exception (unlikely but possible), the exception is caught by the `runner.py` finally block and logged — it must not mask the original pipeline failure.

---

## 8. File Scope

### New Files

```
cobuilder/engine/events/
├── __init__.py                  # Exports: PipelineEvent, EventBuilder, EventEmitter,
│                                #          CompositeEmitter, NullEmitter, build_emitter
├── types.py                     # PipelineEvent, EventType, EventBuilder, SpanConfig
├── emitter.py                   # EventEmitter Protocol, CompositeEmitter, NullEmitter,
│                                # EventBusConfig, build_emitter()
├── logfire_backend.py           # LogfireEmitter
├── jsonl_backend.py             # JSONLEmitter
└── signal_bridge.py             # SignalBridge

cobuilder/engine/middleware/
├── __init__.py                  # Exports: Middleware, HandlerRequest, compose_middleware
├── chain.py                     # Middleware Protocol, HandlerRequest, compose_middleware()
├── logfire.py                   # LogfireMiddleware
├── token_counter.py             # TokenCountingMiddleware
├── retry.py                     # RetryMiddleware
└── audit.py                     # AuditMiddleware (wraps ChainedAuditWriter)
```

### Modified Files

| File | Modification |
|------|-------------|
| `cobuilder/engine/runner.py` | Import `build_emitter`, `EventBusConfig`, `EventBuilder`; call `emit()` at lifecycle points; wrap in `try/finally: await emitter.aclose()` |
| `cobuilder/engine/outcome.py` | Add optional `raw_messages: list[Any] = field(default_factory=list)` to `Outcome` for token counting |
| `cobuilder/engine/context.py` | AMD-3: Do NOT add `emit_on_update`. `context.updated` is emitted by `runner.py` ONCE per node (after merging outcome.context_updates), not per-mutation. Context remains decoupled from the event bus. |
| `cobuilder/engine/checkpoint.py` | Emit `checkpoint.saved` via injected emitter after atomic write succeeds |
| `cobuilder/engine/handlers/codergen.py` | Propagate raw SDK messages into `Outcome.raw_messages` |
| `cobuilder/cli.py` | Wire `EventBusConfig` from CLI flags (`--no-logfire`, `--no-signals`, `--events-file`) |

### Unchanged Files (Integration Points)

| File | Integration Method |
|------|-------------------|
| `signal_protocol.py` | Used by `SignalBridge` via direct import; not modified |
| `anti_gaming.py` | Used by `AuditMiddleware` via constructor injection; not modified |
| `guardian_agent.py` | Receives signals from `SignalBridge`; no modification needed |
| `runner_agent.py` | Receives signals from `SignalBridge`; no modification needed |

---

## 9. Testing Strategy

### Unit Tests (`tests/engine/events/`)

Each backend and middleware is tested in isolation using `NullEmitter` or injected mocks.

#### `test_types.py`
- Verify all 14 `EventType` literals are present in `EventType`
- Verify `PipelineEvent` is frozen (attempting `event.node_id = "x"` raises `FrozenInstanceError`)
- Verify `EventBuilder` factory methods produce correct `type` and non-None `timestamp`
- Verify `EventBuilder._counter` increments monotonically across calls

#### `test_emitter.py`
- `CompositeEmitter` calls all backends: use 3 `NullEmitter` subclasses that record calls; verify each received all events
- `CompositeEmitter` isolates failures: one backend raises; verify other two still received the event
- `build_emitter()` with `logfire_enabled=False, signal_bridge_enabled=False`: only `JSONLEmitter` in composite
- `NullEmitter` accept/discard semantics

#### `test_logfire_backend.py`
- Use `logfire.testing.LogfireTestExporter` (from logfire's testing module) to capture spans without a real Logfire API connection
- Verify pipeline span opened on `pipeline.started`; verify span attributes match `SpanConfig`
- Verify node span opened/closed per `node.started`/`node.completed`
- Verify `outcome_status` and `duration_ms` set on closed span
- Verify `span_id` injected into `node.completed` event

#### `test_jsonl_backend.py`
- Emit 5 events; read back JSONL; verify 5 lines, each valid JSON
- Verify `timestamp` is ISO-8601 string in output
- Verify file opened in append mode: write 2 events, close, write 2 more, verify 4 lines total
- Verify flush after each write (use `os.stat` to check file size before/after each `emit`)

#### `test_signal_bridge.py`
- For each of the 4 bridge-eligible event types: emit, verify `write_signal` called with correct `signal_type`
- For a non-bridge event (`edge.selected`): emit, verify no signal file written
- Verify `aclose()` is idempotent (call twice, no error)
- Use `tmp_path` pytest fixture as `signals_dir` to avoid filesystem side effects

#### `test_chain.py`
- Call-order test: 3 middlewares each append their name to a list; verify order after `compose_middleware`
- Exception propagation: middleware A wraps `next()` in try/except; verify B's exception is caught by A
- Empty chain: `compose_middleware([], handler)` calls handler directly

#### `test_middleware_logfire.py`
- Verify `node.started` event emitted before `next()` called (mock `next` records call order)
- Verify `node.completed` emitted with `outcome_status = "SUCCESS"` when `next()` returns SUCCESS
- Verify `node.failed` emitted when `next()` returns FAILURE
- Verify `duration_ms > 0` in emitted event

#### `test_middleware_token_counter.py`
- Outcome with `raw_messages` containing usage data: verify `$node_tokens` and `$total_tokens` updated
- Outcome with empty `raw_messages`: verify context unchanged
- Cumulative: 3 nodes each with 100 tokens; verify `$total_tokens == 300`

#### `test_middleware_retry.py`
- `next()` fails twice then succeeds: verify `retry.triggered` emitted twice, final outcome is SUCCESS
- `next()` fails 3 times: verify final FAILURE returned after 3 attempts
- Backoff timing: mock `asyncio.sleep`; verify called with `1.0`, `2.0`, `4.0` seconds
- `max_retries=0`: no retry, first FAILURE returned immediately

#### `test_middleware_audit.py`
- Verify 2 `AuditEntry` records written per handler invocation
- Verify `prev_hash` chain is intact (use `ChainedAuditWriter.verify_chain()`)
- `ChainedAuditWriter` raises `OSError`: verify error is caught and handler outcome still returned

### Integration Tests (`tests/engine/test_event_bus_integration.py`)

End-to-end test using a minimal 3-node pipeline (start → box → exit) with all backends active:
- Pipeline runs to completion
- Verify Logfire test exporter captured pipeline and node spans
- Verify JSONL file contains all 14 applicable event types
- Verify signal file written for `pipeline.completed`
- Verify `$total_tokens` in final context matches token sum from mock handler

### Performance Test (`tests/engine/test_event_bus_perf.py`)

Single benchmark: measure wall-clock time added by emitting 14 events through `CompositeEmitter` with all backends (Logfire stubbed, JSONL to `/dev/null`). Assertion: total overhead per node `< 10ms`. This guards the PRD requirement that event emission adds `<10ms overhead per node execution`.

---

## 10. Implementation Sequencing

The features within Epic 4 must be built in dependency order:

1. **F1** (`types.py`, `EventBuilder`) — No dependencies; build first. Everything else imports from here.
2. **F2** (`emitter.py`, `NullEmitter`, `CompositeEmitter`) — Depends on F1.
3. **F6** (`chain.py`, `HandlerRequest`) — Parallel with F2; depends only on `outcome.py` and `graph.py` from Epic 1.
4. **F4** (`jsonl_backend.py`) — Depends on F1, F2. Build before Logfire backend to have a working backend for early integration testing.
5. **F5** (`signal_bridge.py`) — Depends on F1, F2, and `signal_protocol.py` (existing).
6. **F3** (`logfire_backend.py`) — Depends on F1, F2. Needs Logfire testing infrastructure.
7. **F7** (`middleware/logfire.py`) — Depends on F1, F2, F3, F6.
8. **F8** (`middleware/token_counter.py`) — Depends on F1, F6. Also requires `Outcome.raw_messages` field added to Epic 1's `outcome.py`.
9. **F9** (`middleware/retry.py`) — Depends on F1, F6.
10. **F10** (`middleware/audit.py`) — Depends on F6 and `anti_gaming.py` (existing).
11. **Integration**: Wire all into `runner.py` and `cli.py`.

---

## 11. Design Decisions and Rationale

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Protocol-based emitter | `EventEmitter` as `Protocol` | Enables `NullEmitter` test doubles without inheritance; matches Python structural subtyping idioms |
| `asyncio.gather` with `return_exceptions=True` | In `CompositeEmitter` | Backend failure isolation — one slow or crashed backend never blocks pipeline execution |
| Frozen dataclass for `PipelineEvent` | `frozen=True, slots=True` | Prevents accidental mutation; `slots=True` reduces per-event memory overhead when thousands of events are emitted in a long pipeline |
| `EventBuilder` factory class | Static factory methods | Centralises event schema; prevents schema drift across call sites; makes refactoring events easy |
| `HandlerRequest` dataclass | Carries `emitter` | Avoids threading emitter through handler.execute() signatures; middlewares can emit without changing handler interface |
| Logfire span held in `LogfireEmitter` instance | State per emitter | Keeps span lifecycle tracking collocated with the emitter; avoids global state |
| JSONL append mode | Preserves events on resume | When pipeline is resumed from checkpoint, prior run events are not overwritten — the file grows continuously |
| `SignalBridge` extends signal protocol | Wraps `write_signal()` | Reuses battle-tested atomic write pattern; Signal protocol ownership stays in `signal_protocol.py` |
| Token counting via `Outcome.raw_messages` | Optional field on Outcome | Avoids coupling `CodergenHandler` to the token counting middleware; handler just stores messages, middleware extracts counts |
| Separate `validation.started` / `validation.completed` events | Two events for validation | Enables measuring validation duration in Logfire; allows System 3 to detect stuck validation |

---

## 12. Handoff Summary for Orchestrator

### Implementation Priorities

This epic can be parallelised into two tracks after F1 and F2 are complete:

**Track A (Event Types and Backends)**: F1 → F2 → F4 → F5 → F3
- Worker: backend-solutions-engineer
- Deliverable: All four emitter backends passing unit tests; `build_emitter()` factory working

**Track B (Middleware Chain)**: F6 → F7 → F8 → F9 → F10
- Worker: backend-solutions-engineer
- Deliverable: All five middleware classes passing unit tests; `compose_middleware` verified

**Track C (Integration)**: After Track A and B complete
- Worker: backend-solutions-engineer
- Deliverable: `runner.py` wired; integration test green; performance test passing

### Key Risks for Orchestrator Attention

1. **Logfire test isolation**: The `logfire.testing.LogfireTestExporter` API must be available in the installed logfire version. Verify this before starting F3 by checking `import logfire.testing` in the project environment.

2. **Outcome.raw_messages**: Adding this field to `Outcome` in `outcome.py` (Epic 1 territory) requires coordination if Epic 1 is being implemented concurrently. Flag this as a cross-epic dependency.

3. **`context.updated` event volume — AMD-3 RESOLVED**: `context.updated` is now emitted ONCE per completed node (by `runner.py`, after merging `outcome.context_updates`), not per-mutation. The `emit_on_update` callback has been removed from `PipelineContext` — context is fully decoupled from the event bus. This reduces event volume from potentially thousands per pipeline run to N (where N = number of nodes).

4. **Signal type `PIPELINE_COMPLETE`**: The `signal_protocol.py` currently has `NODE_COMPLETE` but not `PIPELINE_COMPLETE`. The `SignalBridge` can use `NODE_COMPLETE` as a stopgap with `node_id = "__pipeline__"`, but adding `PIPELINE_COMPLETE` to `signal_protocol.py` is the clean solution. This is a one-line addition to the constants block.
