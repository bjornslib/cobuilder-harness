---
title: "SD-COBUILDER-WEB-001 Epic 3: SSE Event Bridge"
status: active
type: solution-design
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E3
---

# SD-COBUILDER-WEB-001 Epic 3: SSE Event Bridge

## 1. Problem Statement

The pipeline engine's event bus (SD-PIPELINE-ENGINE-001 Epic 4) emits 14 typed events through `CompositeEmitter`, writing them to JSONL files and Logfire spans. However, there is no mechanism for a web client to receive these events in real-time. The `EventBusConfig.sse_enabled` flag exists as a `bool = False` placeholder, and the `SSEEmitter` slot in the architecture diagram is marked "future."

Without an SSE bridge, the CoBuilder Web UI (Epic 8: Pipeline Graph View) cannot render live node status changes. Clients would need to poll the REST API, introducing latency (seconds instead of sub-100ms) and unnecessary load. The browser-native `EventSource` API expects a `text/event-stream` endpoint that pushes `data: {json}\n\n` frames — this epic delivers that endpoint and the backend plumbing to feed it.

**Two distinct consumption patterns must be supported:**

1. **Live streaming** — A connected client receives events from `SSEEmitter`'s async queue as the pipeline runner emits them. Latency target: <100ms from `emit()` to browser receipt.
2. **Replay on reconnect** — A client connecting mid-run (or reconnecting after a network drop) must receive all historical events from the JSONL file before switching to the live queue. The `Last-Event-ID` header tells the bridge where to resume.

---

## 2. Technical Architecture

### 2.1 Component Topology

```
┌──────────────────────────────────────────────────────────────────────────┐
│  pipeline_runner.py  (execution loop)                                    │
│  Calls: await emitter.emit(event)                                        │
├──────────────────────────────────────────────────────────────────────────┤
│  CompositeEmitter                                                        │
│  ┌──────────────┬──────────────┬───────────────┬──────────────────────┐  │
│  │ LogfireEmitter│ JSONLEmitter │ SignalBridge  │ SSEEmitter (NEW)    │  │
│  │              │ → .jsonl file│              │ → asyncio.Queue     │  │
│  └──────────────┴──────────────┴───────────────┴──────────┬───────────┘  │
└───────────────────────────────────────────────────────────│──────────────┘
                                                            │
                                                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  sse_bridge.py  (async generator)                                        │
│  Reads: SSEEmitter.subscribe() queue  OR  JSONL file (replay fallback)  │
│  Yields: SSE-formatted text frames                                       │
├──────────────────────────────────────────────────────────────────────────┤
│  FastAPI SSE Endpoint                                                    │
│  GET /api/initiatives/{id}/events                                        │
│  Content-Type: text/event-stream                                         │
│  Cache-Control: no-cache                                                 │
│  Connection: keep-alive                                                  │
├──────────────────────────────────────────────────────────────────────────┤
│  Browser EventSource                                                     │
│  const es = new EventSource("/api/initiatives/{id}/events")              │
│  es.onmessage = (e) => updateGraph(JSON.parse(e.data))                  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 SSEEmitter Class

`SSEEmitter` implements the `EventEmitter` protocol. It does NOT stream to clients directly — it publishes events to an internal fan-out registry. Each connected client calls `subscribe()` to get its own `asyncio.Queue`.

```python
"""SSE backend — publishes events to per-subscriber asyncio queues."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from cobuilder.engine.events.types import PipelineEvent

logger = logging.getLogger(__name__)

_SENTINEL = object()  # Marks end-of-stream when aclose() is called


class SSEEmitter:
    """Event bus backend that fans out events to SSE subscriber queues.

    Each call to ``subscribe()`` creates a new ``asyncio.Queue`` that
    receives every subsequent event.  ``emit()`` pushes to ALL subscriber
    queues concurrently.  ``aclose()`` pushes a sentinel value to every
    queue, signalling end-of-stream.

    Thread-safety: This class is async-only and must be used within a
    single event loop.  Subscriber queues are standard ``asyncio.Queue``
    instances (not thread-safe).
    """

    def __init__(self, maxsize: int = 1000) -> None:
        """
        Args:
            maxsize: Maximum backlog per subscriber queue.  When a slow
                     client's queue is full, the oldest event is dropped
                     and a warning is logged.
        """
        self._subscribers: dict[int, asyncio.Queue[PipelineEvent | object]] = {}
        self._next_id: int = 0
        self._maxsize: int = maxsize
        self._closed: bool = False

    def subscribe(self) -> tuple[int, asyncio.Queue[PipelineEvent | object]]:
        """Create a new subscriber queue.

        Returns:
            A (subscription_id, queue) tuple.  The caller reads from the
            queue via ``await queue.get()``.  A sentinel value (checked
            via ``event is _SENTINEL``) indicates end-of-stream.
        """
        sub_id = self._next_id
        self._next_id += 1
        queue: asyncio.Queue[PipelineEvent | object] = asyncio.Queue(
            maxsize=self._maxsize
        )
        self._subscribers[sub_id] = queue
        logger.debug("SSEEmitter: subscriber %d connected (%d total)",
                      sub_id, len(self._subscribers))
        return sub_id, queue

    def unsubscribe(self, sub_id: int) -> None:
        """Remove a subscriber queue.  Idempotent."""
        removed = self._subscribers.pop(sub_id, None)
        if removed is not None:
            logger.debug("SSEEmitter: subscriber %d disconnected (%d remaining)",
                          sub_id, len(self._subscribers))

    async def emit(self, event: PipelineEvent) -> None:
        """Push event to all subscriber queues.

        If a subscriber's queue is full (slow consumer), the oldest event
        is dropped to make room.  This prevents a single stalled client
        from causing memory pressure across the system.
        """
        if self._closed:
            return

        for sub_id, queue in list(self._subscribers.items()):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Drop oldest event to make room (bounded backpressure)
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning(
                        "SSEEmitter: subscriber %d queue still full after drop; "
                        "event %s lost",
                        sub_id, getattr(event, "type", "<unknown>"),
                    )

    async def aclose(self) -> None:
        """Send sentinel to all subscribers and mark emitter as closed.

        Idempotent — calling twice is safe.
        """
        if self._closed:
            return
        self._closed = True

        for sub_id, queue in list(self._subscribers.items()):
            try:
                queue.put_nowait(_SENTINEL)
            except asyncio.QueueFull:
                # Force sentinel even if queue is full — drop oldest
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(_SENTINEL)
                except asyncio.QueueFull:
                    pass

    @property
    def subscriber_count(self) -> int:
        """Number of currently connected subscribers."""
        return len(self._subscribers)
```

**Key design decisions:**

- **Fan-out via per-subscriber queues** (not a single shared queue) so that slow consumers do not block fast ones.
- **Bounded queues with drop-oldest backpressure** instead of unbounded growth. The `maxsize=1000` default provides ~30 seconds of buffer at pipeline-scale event rates (~30 events/s max). Dropped events are recoverable via JSONL replay.
- **Sentinel-based shutdown** so subscribers can cleanly detect end-of-stream without polling or timeouts.

### 2.3 SSE Bridge (Async Generator)

The bridge is the glue between `SSEEmitter` (or JSONL file) and the FastAPI streaming response. It yields SSE-formatted text frames.

```python
"""SSE bridge — async generator that yields SSE text frames.

Supports two modes:
1. Live-only: reads from an SSEEmitter subscriber queue
2. Replay-then-live: replays events from JSONL file starting after
   ``last_event_id``, then switches to the live queue
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path
from typing import AsyncIterator

from cobuilder.engine.events.types import PipelineEvent

logger = logging.getLogger(__name__)


def _format_sse(event: PipelineEvent) -> str:
    """Format a PipelineEvent as an SSE text frame.

    SSE spec: https://html.spec.whatwg.org/multipage/server-sent-events.html

    Output format::

        id: 42
        event: node.completed
        data: {"type":"node.completed","timestamp":"2026-03-12T...","pipeline_id":"...","node_id":"impl_auth","data":{...},"span_id":"abc123","sequence":42}

    """
    record = dataclasses.asdict(event)
    record["timestamp"] = event.timestamp.isoformat()
    json_payload = json.dumps(record, ensure_ascii=False)

    lines = []
    lines.append(f"id: {event.sequence}")
    lines.append(f"event: {event.type}")
    lines.append(f"data: {json_payload}")
    # SSE frames are terminated by a blank line
    return "\n".join(lines) + "\n\n"


def _parse_jsonl_event(line: str) -> PipelineEvent | None:
    """Parse a single JSONL line back into a PipelineEvent.

    Returns None if the line is malformed (logged at WARNING).
    """
    try:
        record = json.loads(line)
        from datetime import datetime
        record["timestamp"] = datetime.fromisoformat(record["timestamp"])
        return PipelineEvent(**record)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("sse_bridge: malformed JSONL line skipped: %s", exc)
        return None


async def replay_from_jsonl(
    jsonl_path: Path,
    after_sequence: int = 0,
) -> AsyncIterator[str]:
    """Yield SSE frames for all events in a JSONL file with sequence > after_sequence.

    This function reads the file synchronously (it is a local file) but
    yields asynchronously to cooperate with the event loop.  For typical
    pipeline runs (hundreds to low thousands of events), the entire file
    fits comfortably in memory.

    Args:
        jsonl_path: Path to the ``pipeline-events.jsonl`` file.
        after_sequence: Only yield events whose ``sequence`` field is
                        strictly greater than this value.  Set to 0 to
                        replay all events.
    """
    if not jsonl_path.exists():
        logger.debug("sse_bridge: JSONL file %s does not exist; nothing to replay",
                      jsonl_path)
        return

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = _parse_jsonl_event(line)
            if event is None:
                continue
            if event.sequence <= after_sequence:
                continue
            yield _format_sse(event)
            # Yield control periodically so we don't block the event loop
            # during large replays
            await asyncio.sleep(0)


async def stream_live(
    sse_emitter: "SSEEmitter",
) -> AsyncIterator[str]:
    """Yield SSE frames from a live SSEEmitter subscriber queue.

    Subscribes on entry, unsubscribes on exit (generator close or
    exception).  Terminates when the sentinel value is received
    (emitter closed) or when the generator is closed by the caller
    (client disconnect).

    Args:
        sse_emitter: The SSEEmitter instance registered in the
                     CompositeEmitter for this pipeline run.
    """
    from cobuilder.engine.events.sse_emitter import _SENTINEL

    sub_id, queue = sse_emitter.subscribe()
    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                return
            yield _format_sse(item)  # type: ignore[arg-type]
    finally:
        sse_emitter.unsubscribe(sub_id)


async def stream_with_replay(
    sse_emitter: "SSEEmitter",
    jsonl_path: Path,
    last_event_id: int = 0,
) -> AsyncIterator[str]:
    """Replay historical events from JSONL, then switch to live stream.

    This is the primary entry point for the SSE endpoint.  The sequence
    of operations is:

    1. Subscribe to the live queue FIRST (so no events are missed during
       replay).
    2. Replay all JSONL events with sequence > last_event_id.
    3. Drain any live events that arrived during replay (dedup by
       sequence number).
    4. Stream live events until sentinel or client disconnect.

    The subscribe-before-replay ordering is critical: if we replayed
    first and then subscribed, events emitted during replay would be
    lost.

    Args:
        sse_emitter: The SSEEmitter instance for this pipeline.
        jsonl_path: Path to the pipeline's JSONL event file.
        last_event_id: The ``sequence`` value from the client's
                       ``Last-Event-ID`` header.  Events with sequence
                       <= this value are skipped.
    """
    from cobuilder.engine.events.sse_emitter import _SENTINEL

    # Step 1: Subscribe BEFORE replay to avoid a gap
    sub_id, queue = sse_emitter.subscribe()
    max_replayed_sequence = last_event_id

    try:
        # Step 2: Replay historical events from JSONL
        async for frame in replay_from_jsonl(jsonl_path, after_sequence=last_event_id):
            yield frame
            # Track the highest sequence we replayed so we can dedup
            # the live queue.  The sequence is embedded in the "id: N"
            # line of the SSE frame.
            try:
                id_line = frame.split("\n")[0]  # "id: 42"
                seq = int(id_line.split(": ", 1)[1])
                if seq > max_replayed_sequence:
                    max_replayed_sequence = seq
            except (ValueError, IndexError):
                pass

        # Step 3: Drain live events that arrived during replay (dedup)
        while not queue.empty():
            item = queue.get_nowait()
            if item is _SENTINEL:
                return
            event: PipelineEvent = item  # type: ignore[assignment]
            if event.sequence <= max_replayed_sequence:
                continue  # Already sent during replay
            yield _format_sse(event)
            if event.sequence > max_replayed_sequence:
                max_replayed_sequence = event.sequence

        # Step 4: Stream live events
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                return
            event = item  # type: ignore[assignment]
            if event.sequence <= max_replayed_sequence:
                continue  # Late duplicate from replay window
            yield _format_sse(event)

    finally:
        sse_emitter.unsubscribe(sub_id)
```

### 2.4 Replay Mechanism — Subscribe-Before-Replay

The ordering in `stream_with_replay()` is the most subtle part of the design. The naive approach (replay JSONL, then subscribe to live) creates a gap: events emitted between "finished reading JSONL" and "subscribed to queue" are lost.

The correct sequence:

```
  Time ─────────────────────────────────────────────────────>

  1. subscribe()          2. replay JSONL          3. live stream
  ├──────────────────────┤───────────────────────┤──────────────>
  │                      │                       │
  │  Live events start   │  JSONL events sent    │  Dedup, then
  │  buffering in queue  │  to client            │  forward live
  │  (will dedup later)  │                       │  events from
  │                      │                       │  queue
```

Events emitted during step 2 land in the subscriber queue. After replay completes, the bridge drains the queue and deduplicates by `sequence` number: any event with `sequence <= max_replayed_sequence` is discarded. This guarantees exactly-once delivery to the client (or at-most-once in the drop-oldest backpressure scenario, which is acceptable since the client can re-fetch via JSONL).

---

## 3. SSE Protocol Details

### 3.1 Event Frame Format

Every event is formatted per the [Server-Sent Events spec](https://html.spec.whatwg.org/multipage/server-sent-events.html):

```
id: 42
event: node.completed
data: {"type":"node.completed","timestamp":"2026-03-12T14:30:01.123456+00:00","pipeline_id":"prd-dashboard-audit-001","node_id":"impl_backend","data":{"outcome_status":"SUCCESS","duration_ms":14523.7,"tokens_used":8421},"span_id":"abc123def456","sequence":42}

```

**Field semantics:**

| SSE Field | Value | Purpose |
|-----------|-------|---------|
| `id` | `PipelineEvent.sequence` (monotonic int) | Reconnection resume point via `Last-Event-ID` header |
| `event` | `PipelineEvent.type` (e.g., `node.completed`) | Allows `EventSource.addEventListener("node.completed", ...)` on the client |
| `data` | Full JSON-serialized `PipelineEvent` | Client receives the complete event payload |

**Why `id` uses `sequence` (not a UUID):** The `sequence` field is a monotonic integer already maintained by `EventBuilder._counter`. It provides natural ordering for replay deduplication and is cheaper to compare than UUIDs. The `Last-Event-ID` header from `EventSource` sends this value back on reconnection.

### 3.2 Last-Event-ID and Reconnection

When the browser's `EventSource` reconnects (automatic on network drop, default 3-second retry), it sends:

```http
GET /api/initiatives/prd-dashboard-audit-001/events HTTP/1.1
Last-Event-ID: 42
```

The SSE endpoint parses this header and passes it to `stream_with_replay(last_event_id=42)`. The bridge replays JSONL events with `sequence > 42`, then switches to live. The client seamlessly resumes without duplicates.

**Edge case: stale Last-Event-ID.** If the client sends a `Last-Event-ID` from a previous pipeline run (sequence counter resets across process restarts), the replay simply sends all events from the current JSONL file (since none will have `sequence <= stale_id` unless the counter wraps, which is astronomically unlikely for a 64-bit int). This is correct behavior — the client gets a full replay of the current run.

### 3.3 Retry Directive

The server sends a `retry:` field on initial connection to control the browser's reconnection interval:

```
retry: 3000

```

This tells `EventSource` to wait 3 seconds before reconnecting on disconnect. The value is sent once, as the first frame before any event data.

### 3.4 Keep-Alive Comments

To prevent intermediate proxies (nginx, cloudflare) from closing idle connections, the SSE endpoint sends a comment frame every 15 seconds when no events are flowing:

```
: keepalive

```

SSE comments (lines starting with `:`) are silently ignored by `EventSource` but reset TCP idle timers.

---

## 4. Integration with Existing Event Bus

### 4.1 SSEEmitter as a CompositeEmitter Backend

`SSEEmitter` plugs into `CompositeEmitter` alongside `LogfireEmitter`, `JSONLEmitter`, and `SignalBridge`. The `build_emitter()` factory creates it when `EventBusConfig.sse_enabled` is `True`.

**Changes to `build_emitter()` in `emitter.py`:**

```python
def build_emitter(
    pipeline_id: str,
    run_dir: str,
    config: EventBusConfig | None = None,
    sse_emitter: SSEEmitter | None = None,   # <-- NEW parameter
) -> CompositeEmitter:
    if config is None:
        config = EventBusConfig()

    backends: list[EventEmitter] = []

    # ... existing JSONL, Logfire, SignalBridge setup unchanged ...

    # SSE backend — injected by the web server, not created here
    if config.sse_enabled and sse_emitter is not None:
        backends.append(sse_emitter)

    return CompositeEmitter(backends)
```

**Why inject, not create:** The `SSEEmitter` instance must be shared between `build_emitter()` (which registers it as a backend) and the SSE endpoint (which calls `subscribe()`). The web server creates the `SSEEmitter` per initiative, holds a reference in the initiative registry, and passes it to `build_emitter()` when launching the pipeline runner. This avoids a global singleton.

### 4.2 SSEEmitter Lifecycle

```
Web server starts
  │
  ▼
Initiative created
  │
  ├─ SSEEmitter instance created, stored in initiative registry
  │
  ▼
Pipeline runner launched
  │
  ├─ build_emitter(sse_emitter=initiative.sse_emitter)
  │  → SSEEmitter added to CompositeEmitter backends
  │
  ├─ Runner emits events → CompositeEmitter fans out to all backends
  │  → SSEEmitter.emit() pushes to subscriber queues
  │
  ▼
Pipeline completes (or fails)
  │
  ├─ CompositeEmitter.aclose()
  │  → SSEEmitter.aclose() sends sentinel to all subscribers
  │
  ▼
SSE clients receive sentinel → EventSource disconnects
  │
  ▼
New pipeline run for same initiative
  │
  ├─ SSEEmitter instance REPLACED (new instance, fresh state)
  │  → Old subscribers already disconnected via sentinel
  │  → New run gets clean subscriber registry
```

### 4.3 EventBusConfig Changes

The existing `EventBusConfig` dataclass gains no new fields. The `sse_enabled: bool = False` flag already exists. The web server sets it to `True` via:

```python
config = EventBusConfig(sse_enabled=True)
```

This flag is set when the web server is active. CLI-only pipeline runs leave it as `False` (default), and `build_emitter()` skips SSE setup entirely.

### 4.4 Interaction with JSONLEmitter

The SSE bridge depends on JSONL files for replay. Both `JSONLEmitter` and `SSEEmitter` receive the same events from `CompositeEmitter.emit()`. The JSONL file is the durable store; the SSE subscriber queues are ephemeral.

**Ordering guarantee:** Because `CompositeEmitter` calls `emit()` on all backends concurrently via `asyncio.gather()`, the JSONL write and SSE queue push happen in the same gather batch. The JSONL file will always contain at least the events that have been pushed to SSE queues (and typically more, since JSONL persists across reconnections).

---

## 5. FastAPI SSE Endpoint

### 5.1 Endpoint Definition

```python
"""SSE endpoint for real-time pipeline event streaming."""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from cobuilder.web.api.infra.sse_bridge import stream_with_replay

router = APIRouter()


async def _sse_generator(
    request: Request,
    initiative_id: str,
) -> AsyncIterator[str]:
    """Async generator that yields SSE frames for a given initiative.

    Sends retry directive, then replays + streams live events.
    Terminates when the client disconnects or the pipeline completes.
    """
    # Get initiative from app state (set during startup)
    initiative_registry = request.app.state.initiative_registry
    initiative = initiative_registry.get(initiative_id)
    if initiative is None:
        yield "event: error\ndata: {\"error\": \"Initiative not found\"}\n\n"
        return

    sse_emitter = initiative.sse_emitter
    jsonl_path = Path(initiative.run_dir) / "pipeline-events.jsonl"

    # Parse Last-Event-ID header for reconnection resume
    last_event_id_str = request.headers.get("Last-Event-ID", "0")
    try:
        last_event_id = int(last_event_id_str)
    except ValueError:
        last_event_id = 0

    # Send retry directive (3 seconds)
    yield "retry: 3000\n\n"

    # Stream with replay
    async for frame in stream_with_replay(
        sse_emitter=sse_emitter,
        jsonl_path=jsonl_path,
        last_event_id=last_event_id,
    ):
        # Check if client disconnected
        if await request.is_disconnected():
            return
        yield frame


@router.get("/api/initiatives/{initiative_id}/events")
async def stream_events(
    initiative_id: str,
    request: Request,
) -> StreamingResponse:
    """SSE endpoint for real-time pipeline event streaming.

    Supports reconnection via the Last-Event-ID header.  On initial
    connection (no Last-Event-ID), replays all events from JSONL then
    switches to live.
    """
    return StreamingResponse(
        _sse_generator(request, initiative_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
```

### 5.2 Keep-Alive Implementation

The keep-alive is implemented as a wrapper around the core generator:

```python
import asyncio
from typing import AsyncIterator


async def with_keepalive(
    inner: AsyncIterator[str],
    interval_seconds: float = 15.0,
) -> AsyncIterator[str]:
    """Wrap an async generator to inject SSE keep-alive comments.

    When the inner generator has no events for ``interval_seconds``,
    yields a ``: keepalive`` comment to prevent proxy timeouts.
    """
    inner_iter = inner.__aiter__()
    while True:
        try:
            frame = await asyncio.wait_for(
                inner_iter.__anext__(),
                timeout=interval_seconds,
            )
            yield frame
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
        except StopAsyncIteration:
            return
```

The endpoint wraps the generator: `with_keepalive(_sse_generator(request, initiative_id))`.

---

## 6. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `cobuilder/engine/events/sse_emitter.py` | `SSEEmitter` class — fan-out to per-subscriber `asyncio.Queue` instances |
| `cobuilder/web/api/infra/sse_bridge.py` | Async generators: `replay_from_jsonl()`, `stream_live()`, `stream_with_replay()`, `_format_sse()`, `with_keepalive()` |
| `cobuilder/web/api/routers/pipelines.py` | FastAPI router with `GET /api/initiatives/{id}/events` SSE endpoint (extends Epic 2 router) |
| `tests/unit/test_engine_events/test_sse_emitter.py` | Unit tests for `SSEEmitter` |
| `tests/unit/test_web/test_sse_bridge.py` | Unit tests for SSE bridge (replay, live, combined) |
| `tests/integration/test_sse_endpoint.py` | Integration test: pipeline run with SSE client |

### Modified Files

| File | Change |
|------|--------|
| `cobuilder/engine/events/emitter.py` | Add `sse_emitter: SSEEmitter \| None = None` parameter to `build_emitter()`; conditionally append to backends list when `config.sse_enabled and sse_emitter is not None` |
| `cobuilder/engine/events/__init__.py` | Add `SSEEmitter` to public exports and `__all__` |
| `cobuilder/web/api/infra/initiative_manager.py` | Create `SSEEmitter` instance per initiative; store in initiative registry (Epic 2 dependency) |
| `cobuilder/web/api/infra/pipeline_launcher.py` | Pass `sse_emitter=initiative.sse_emitter` to `build_emitter()` when launching runner (Epic 6 dependency) |

### Unchanged Files (Integration Points)

| File | Relationship |
|------|-------------|
| `cobuilder/engine/events/types.py` | `PipelineEvent` and `EventBuilder` used as-is; `sequence` field used as SSE `id` |
| `cobuilder/engine/events/jsonl_backend.py` | JSONL files read by replay; no modification needed |
| `cobuilder/engine/events/logfire_backend.py` | Unaffected — runs alongside SSEEmitter in CompositeEmitter |
| `cobuilder/engine/events/signal_bridge.py` | Unaffected — runs alongside SSEEmitter in CompositeEmitter |

---

## 7. Implementation Priority

Features are ordered by dependency:

| Priority | Feature | Depends On | Estimated LOC |
|----------|---------|------------|---------------|
| P1 | `SSEEmitter` class (`sse_emitter.py`) | `EventEmitter` protocol (exists) | ~100 |
| P2 | `_format_sse()` + `_parse_jsonl_event()` helpers | `PipelineEvent`, `JSONLEmitter` format (exist) | ~60 |
| P3 | `replay_from_jsonl()` async generator | P2 | ~40 |
| P4 | `stream_live()` async generator | P1 | ~30 |
| P5 | `stream_with_replay()` async generator | P1, P3, P4 | ~60 |
| P6 | `with_keepalive()` wrapper | None | ~20 |
| P7 | `build_emitter()` modification | P1 | ~5 (delta) |
| P8 | FastAPI SSE endpoint | P5, P6, Epic 2 router | ~50 |

**Total estimated new code: ~365 LOC** (excluding tests).

P1-P6 can proceed independently of Epic 2 (FastAPI server). P7 is a small delta to existing code. P8 depends on Epic 2's router structure.

---

## 8. Acceptance Criteria

### AC-1: SSEEmitter Delivers Events to Connected Clients

- `SSEEmitter.emit()` pushes events to all subscriber queues within a single event loop tick.
- A subscriber calling `await queue.get()` receives the event within 100ms of `emit()`.
- Multiple subscribers each receive every event independently.

### AC-2: SSE Frame Format Compliance

- Every frame matches the pattern `id: {int}\nevent: {type}\ndata: {json}\n\n`.
- The `data` field is valid JSON that deserializes to a dict matching `PipelineEvent` fields.
- The `id` field matches `PipelineEvent.sequence`.
- The `event` field matches `PipelineEvent.type` (one of the 14 canonical types).

### AC-3: Replay Mode Sends Historical Events

- On initial connection (no `Last-Event-ID`), all events from the JSONL file are sent before live events.
- Events are sent in `sequence` order (ascending).
- Malformed JSONL lines are skipped with a warning, not fatal.

### AC-4: Reconnection Resume via Last-Event-ID

- `EventSource` reconnection with `Last-Event-ID: 42` receives only events with `sequence > 42`.
- No duplicate events are sent (deduplication by `sequence` in `stream_with_replay()`).
- A stale `Last-Event-ID` from a previous pipeline run results in full replay of the current run (correct behavior).

### AC-5: CompositeEmitter Integration

- `SSEEmitter` is added to `CompositeEmitter` backends when `EventBusConfig.sse_enabled=True` and an `SSEEmitter` instance is provided.
- Other backends (`LogfireEmitter`, `JSONLEmitter`, `SignalBridge`) continue to function identically — no behavioral change.
- When `sse_enabled=False` (default), no `SSEEmitter` is instantiated and no SSE-related code is loaded.

### AC-6: Graceful Client Disconnect

- When a browser tab is closed, the SSE generator detects disconnect via `request.is_disconnected()` and terminates.
- The subscriber is unsubscribed from `SSEEmitter` (no leaked queues).
- No errors are logged for normal client disconnects.

### AC-7: Pipeline Completion Terminates Stream

- When `CompositeEmitter.aclose()` is called (pipeline end), `SSEEmitter` sends sentinel to all subscribers.
- Subscriber generators terminate cleanly after yielding the final event.
- `EventSource` in the browser fires its `onerror` handler; no automatic reconnection is attempted for a completed pipeline (the client handles this by checking the last event type).

### AC-8: Keep-Alive Prevents Proxy Timeout

- When no events are emitted for 15 seconds, a `: keepalive\n\n` comment is sent.
- `EventSource` in the browser ignores the comment (spec behavior).
- Connection remains open through standard proxy timeout windows (typically 60s).

---

## 9. Risks and Mitigations

### R1: Memory Pressure from Buffered Events (Likelihood: Medium, Impact: Medium)

**Risk:** Each subscriber queue buffers up to `maxsize` events. With N concurrent browser tabs and a burst of events, memory usage is `N * maxsize * avg_event_size`. At 1000 events * 1KB average * 10 tabs = 10MB — manageable. But 100 tabs with slow networks could reach 100MB.

**Mitigation:**
- Bounded queues with drop-oldest backpressure (implemented).
- `subscriber_count` property exposed for monitoring; the web server can reject new SSE connections when count exceeds a configurable limit (default: 50).
- Dropped events are recoverable via JSONL replay on reconnection.

### R2: Disconnected Clients Not Cleaned Up (Likelihood: Low, Impact: Medium)

**Risk:** If a client disconnects without the server detecting it (e.g., network partition without TCP RST), the subscriber queue accumulates events indefinitely until `maxsize` is reached, then enters drop-oldest mode forever.

**Mitigation:**
- FastAPI's `request.is_disconnected()` check on every yield iteration.
- Keep-alive comment every 15 seconds forces a write; a broken connection will raise `ConnectionResetError`, triggering the generator's `finally` block which calls `unsubscribe()`.
- Periodic cleanup task (every 60 seconds) in the web server that removes subscribers whose queues have been full for >30 seconds consecutively.

### R3: JSONL Replay Ordering vs. Live Queue Ordering (Likelihood: Low, Impact: Low)

**Risk:** The JSONL file and the SSE subscriber queue both receive events from the same `CompositeEmitter.emit()` call via `asyncio.gather()`. In theory, the JSONL write and queue push happen concurrently, so ordering is guaranteed within a single `emit()`. However, if two `emit()` calls overlap (impossible in the current single-threaded runner, but theoretically possible with future parallelism), events could arrive in different orders in JSONL vs. queue.

**Mitigation:**
- The `sequence` field provides a total order. The bridge always uses `sequence` for deduplication and ordering, not arrival order.
- The current runner is single-threaded and calls `emit()` sequentially. If parallelism is added, the `EventBuilder._counter` lock (currently a simple increment, which is atomic in CPython due to the GIL) may need an `asyncio.Lock`.

### R4: JSONL File Growth for Long-Running Pipelines (Likelihood: Medium, Impact: Low)

**Risk:** A pipeline with many nodes (50+) running over hours produces a large JSONL file. Replay of this file on every reconnection adds latency.

**Mitigation:**
- JSONL files are already scoped per pipeline run (`{run_dir}/pipeline-events.jsonl`), so they do not grow across runs.
- For a 50-node pipeline producing ~14 events per node = 700 events at ~1KB each = 700KB. Replay of 700KB over localhost is <50ms.
- If replay latency becomes problematic (pipelines with 500+ nodes), a future optimization could index the JSONL file by sequence ranges or use `Last-Event-ID` to seek directly.

### R5: EventBuilder Sequence Counter Across Pipeline Runs (Likelihood: Low, Impact: Low)

**Risk:** `EventBuilder._counter` is a class-level variable that increments across pipeline runs within the same process. If the web server launches multiple pipeline runs, `Last-Event-ID` from run 1 may be numerically less than events in run 2's JSONL, causing the bridge to skip events from run 2 that the client has not seen.

**Mitigation:**
- The SSEEmitter instance is replaced per pipeline run (see lifecycle in section 4.2). A reconnecting `EventSource` hits the new SSEEmitter, which has no subscribers yet.
- The JSONL file is per-run. The bridge reads the current run's JSONL file, not a previous run's.
- If the `Last-Event-ID` is from a previous run, all events in the current JSONL file will have `sequence > last_event_id` (because the counter only goes up), so full replay occurs — which is correct.

---

## 10. Client-Side Usage Reference

For completeness, here is the expected browser-side consumption pattern (implemented in Epic 8, not this epic):

```typescript
// EventStream.tsx — SSE subscriber hook
function usePipelineEvents(initiativeId: string) {
  const [events, setEvents] = useState<PipelineEvent[]>([]);

  useEffect(() => {
    const es = new EventSource(
      `/api/initiatives/${initiativeId}/events`
    );

    // Listen to all 14 event types via generic handler
    es.onmessage = (e: MessageEvent) => {
      const event: PipelineEvent = JSON.parse(e.data);
      setEvents((prev) => [...prev, event]);
    };

    // Or listen to specific event types
    es.addEventListener("node.completed", (e: MessageEvent) => {
      const event = JSON.parse(e.data);
      updateNodeColor(event.node_id, "green");
    });

    es.addEventListener("node.started", (e: MessageEvent) => {
      const event = JSON.parse(e.data);
      updateNodeColor(event.node_id, "pulsing-blue");
    });

    es.onerror = () => {
      // EventSource auto-reconnects with Last-Event-ID
      // No manual reconnection logic needed
    };

    return () => es.close();
  }, [initiativeId]);

  return events;
}
```

`EventSource` handles reconnection automatically. The browser sends `Last-Event-ID` on reconnect. The server replays missed events. The client receives a gap-free stream without application-level reconnection code.
