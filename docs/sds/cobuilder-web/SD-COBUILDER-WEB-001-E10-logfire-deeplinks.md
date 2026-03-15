---
title: "SD-COBUILDER-WEB-001 Epic 10: Logfire Deep-Links"
status: active
type: reference
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E10
---

# SD-COBUILDER-WEB-001 Epic 10: Logfire Deep-Links

## 1. Problem Statement

The pipeline engine already emits structured observability data via `LogfireEmitter` (SD-PIPELINE-ENGINE-001 Epic 4). Every `node.completed` event carries a `span_id` correlating the node execution to a Logfire span, and the `LogfireEmitter` maintains a pipeline-level parent span covering the entire run. However, this observability data is not surfaced in the web UI. Operators who want to inspect a node's execution trace must manually open Logfire, locate the correct project, and search for the span -- a context switch that breaks the control-tower flow.

Epic 10 closes this gap by constructing clickable deep-link URLs from the `span_id` already present in pipeline events and rendering them in the NodeInspector (Epic 8) and initiative detail view. The scope is narrow: URL construction, configuration, and graceful degradation. No Logfire API queries or inline timelines.

## 2. Technical Architecture

### 2.1 Data Flow

```
LogfireMiddleware (existing)
  │  Sets span attributes, captures span_id
  │  Emits node.completed(span_id=<hex>)
  ▼
SSE Event Bridge (E3)
  │  Streams event to frontend
  ▼
NodeInspector (E8)          Initiative Detail View (E8)
  │  Per-node deep-link       │  Pipeline-level deep-link
  ▼                            ▼
"Open in Logfire" link      "View Full Trace" link
```

The `span_id` originates in the `LogfireMiddleware` (`cobuilder/engine/middleware/logfire.py`, lines 148-155). After the handler completes, the middleware reads the active Logfire span context and injects `span_id` into the `node.completed` event via `EventBuilder.node_completed(..., span_id=span_id)`. This value is a hex-encoded 16-byte OpenTelemetry span ID.

For the pipeline-level trace, the `LogfireEmitter` opens a parent span on `pipeline.started`. The parent span's `span_id` is available in `pipeline.completed` events (currently not emitted -- see Section 6 for the one-line change needed).

### 2.2 URL Construction

All deep-link URLs are constructed client-side in a single utility function. The backend serves only the raw `span_id` values and the Logfire project base URL (via configuration endpoint or SSE event metadata).

```typescript
// lib/logfire.ts

/**
 * Construct a Logfire deep-link URL for a trace or span.
 *
 * Returns null when span_id is missing or project URL is not configured,
 * allowing the caller to hide the link rather than render a broken one.
 */
export function buildLogfireUrl(
  projectUrl: string | null,
  spanId: string | null,
): string | null {
  if (!projectUrl || !spanId) return null;

  // Strip trailing slash from project URL
  const base = projectUrl.replace(/\/+$/, "");

  // Logfire trace URL format: {project_url}/traces/{span_id}
  return `${base}/traces/${spanId}`;
}
```

### 2.3 URL Format

Logfire uses the pattern `https://logfire.pydantic.dev/{org}/{project}/traces/{span_id}` for trace deep-links. Since the org and project segments vary per deployment, the entire base is captured in a single `LOGFIRE_PROJECT_URL` environment variable.

| Link Type | URL Pattern | Source |
|-----------|-------------|--------|
| Node trace | `{LOGFIRE_PROJECT_URL}/traces/{node_span_id}` | `node.completed` event `span_id` field |
| Pipeline trace | `{LOGFIRE_PROJECT_URL}/traces/{pipeline_span_id}` | `pipeline.completed` event `span_id` field |

Example:
- `LOGFIRE_PROJECT_URL=https://logfire.pydantic.dev/theb/cobuilder-pipelines`
- Node span_id: `a1b2c3d4e5f67890`
- Result: `https://logfire.pydantic.dev/theb/cobuilder-pipelines/traces/a1b2c3d4e5f67890`

## 3. Integration Points

### 3.1 NodeInspector Component (Epic 8)

The `NodeInspector` side panel (opened by clicking a node in the pipeline graph) already displays `worker_type`, `model`, `duration`, and `token count`. This epic adds an "Open in Logfire" link at the bottom of the inspector panel.

```tsx
// components/NodeInspector.tsx (addition to existing component)

import { buildLogfireUrl } from "@/lib/logfire";
import { ExternalLink } from "lucide-react";

// Inside the inspector panel, after the existing metadata fields:
function LogfireLink({ spanId }: { spanId: string | null }) {
  const logfireUrl = buildLogfireUrl(config.logfireProjectUrl, spanId);

  if (!logfireUrl) {
    return (
      <span className="text-sm text-muted-foreground">
        Logfire trace unavailable
      </span>
    );
  }

  return (
    <a
      href={logfireUrl}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1.5 text-sm text-blue-400 hover:text-blue-300 transition-colors"
    >
      <ExternalLink className="h-3.5 w-3.5" />
      Open in Logfire
    </a>
  );
}
```

### 3.2 Event Data (Epic 3 SSE Bridge)

The `span_id` is already present in the `PipelineEvent` dataclass (`cobuilder/engine/events/types.py`, line 73) and serialised to JSONL by `JSONLEmitter`. The SSE bridge (Epic 3) streams these events unchanged. No modification to the SSE bridge is needed.

The frontend stores the most recent `node.completed` event per node in its local state (already required for duration and token count display in the NodeInspector). The `span_id` field is simply read from this stored event.

### 3.3 Initiative Detail View (Epic 8)

The initiative detail page shows pipeline-level metadata. A "View Full Trace" link is added next to the pipeline status, using the `span_id` from the `pipeline.completed` event.

## 4. Configuration

### 4.1 Environment Variable

| Variable | Required | Default | Example |
|----------|----------|---------|---------|
| `LOGFIRE_PROJECT_URL` | No | `null` | `https://logfire.pydantic.dev/theb/cobuilder-pipelines` |

The FastAPI backend reads this at startup and exposes it via the existing configuration endpoint:

```python
# api/routers/config.py (or added to initiatives.py response)

import os

LOGFIRE_PROJECT_URL = os.environ.get("LOGFIRE_PROJECT_URL")

@router.get("/api/config")
def get_config():
    return {
        "logfire_project_url": LOGFIRE_PROJECT_URL,
        # ... other config
    }
```

The frontend fetches this once at app initialization and stores it in a React context or module-level constant.

### 4.2 Fallback Behavior

| Condition | Behavior |
|-----------|----------|
| `LOGFIRE_PROJECT_URL` not set | "Open in Logfire" link hidden entirely; "Logfire not configured" tooltip on hover of a subtle info icon |
| `span_id` missing on event (Logfire disabled in runner) | "Logfire trace unavailable" text shown instead of link |
| Both missing | No Logfire UI elements rendered at all |
| `LOGFIRE_PROJECT_URL` set but span_id missing for specific node | Per-node: "Trace unavailable" text; pipeline-level link may still work if pipeline span was captured |

The graceful degradation is handled entirely in `buildLogfireUrl()` returning `null`, which the React components interpret as "hide this link."

## 5. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `cobuilder/web/frontend/lib/logfire.ts` | `buildLogfireUrl()` utility function |

### Modified Files

| File | Change |
|------|--------|
| `cobuilder/web/frontend/components/NodeInspector.tsx` | Add `LogfireLink` component below existing metadata |
| `cobuilder/web/frontend/app/initiatives/[id]/page.tsx` | Add "View Full Trace" link using pipeline-level `span_id` |
| `cobuilder/web/api/routers/initiatives.py` (or `config.py`) | Expose `LOGFIRE_PROJECT_URL` in config response |
| `cobuilder/engine/events/types.py` | Add `span_id` parameter to `EventBuilder.pipeline_completed()` factory method |
| `cobuilder/engine/events/logfire_backend.py` | Emit pipeline `span_id` in `pipeline.completed` event |

### Unchanged Files (Integration Points)

| File | Why Unchanged |
|------|---------------|
| `cobuilder/engine/middleware/logfire.py` | Already emits `span_id` in `node.completed` events |
| `cobuilder/engine/events/emitter.py` | `PipelineEvent.span_id` field already exists on the dataclass |
| `cobuilder/web/api/infra/sse_bridge.py` | Streams events as-is; `span_id` passes through |

## 6. Implementation Priority

This is a small, self-contained epic with no blocking dependencies beyond E3 (SSE bridge) and E8 (NodeInspector). The work decomposes into three tasks that can be done sequentially by a single worker in a short session:

1. **Backend config exposure** (~15 min): Read `LOGFIRE_PROJECT_URL` from env, add to config endpoint. Add `span_id` to `pipeline_completed` factory method in `EventBuilder`.
2. **Frontend utility** (~15 min): Write `buildLogfireUrl()` in `lib/logfire.ts` with unit test.
3. **Component integration** (~30 min): Add `LogfireLink` to `NodeInspector`, add "View Full Trace" to initiative detail page, implement fallback rendering.

**Total estimated effort:** ~1 hour of implementation + testing.

**Worker type:** `frontend-dev-expert` (primary work is React component integration; the one Python change is trivial).

### EventBuilder Change Detail

The `EventBuilder.pipeline_completed()` method currently does not accept a `span_id` parameter. Add it:

```python
# cobuilder/engine/events/types.py — pipeline_completed()

@classmethod
def pipeline_completed(
    cls,
    pipeline_id: str,
    duration_ms: float,
    total_tokens: int = 0,
    span_id: str | None = None,   # NEW: pipeline-level Logfire span ID
) -> PipelineEvent:
    """Emit after the exit handler returns successfully."""
    return cls._build(
        "pipeline.completed",
        pipeline_id,
        None,
        {"duration_ms": duration_ms, "total_tokens": total_tokens},
        span_id=span_id,
    )
```

The `LogfireEmitter` (or the runner's pipeline completion code) passes the pipeline-level span ID when constructing this event. The `_build` method already supports the `span_id` keyword argument.

## 7. Acceptance Criteria

- **AC-10.1**: NodeInspector shows "Open in Logfire" link when `span_id` is present in the `node.completed` event. Link opens `{LOGFIRE_PROJECT_URL}/traces/{span_id}` in a new tab.

- **AC-10.2**: Initiative detail view shows "View Full Trace" link using the pipeline-level `span_id` from the `pipeline.completed` event. Link opens the correct pipeline trace.

- **AC-10.3**: When `LOGFIRE_PROJECT_URL` is not set, no Logfire link elements are rendered (no broken links, no empty anchor tags).

- **AC-10.4**: When `span_id` is `null` on a specific event (e.g., Logfire was disabled for that pipeline run), the component shows "Logfire trace unavailable" text instead of a link.

- **AC-10.5**: `buildLogfireUrl()` has a unit test covering: valid input, null project URL, null span_id, trailing slash on project URL, both null.

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Stale span_id** -- Logfire retention policy expires spans before operator clicks the link | Low | Low | Logfire default retention is 30 days. Pipeline runs older than 30 days naturally lose trace data. No mitigation needed beyond documenting the retention window. |
| **Logfire project URL misconfiguration** -- Operator sets wrong project URL, links 404 | Medium | Low | Link opens in new tab; operator sees Logfire 404 and corrects config. Could add a "Test Logfire Connection" button in settings (future, not this epic). |
| **Missing span_id on node.completed** -- LogfireMiddleware fails to capture span context | Low | Low | The middleware has try/except around span_id extraction (lines 148-155); on failure it sets `span_id=None`, and the frontend gracefully hides the link. |
| **Pipeline-level span_id not emitted** -- `pipeline.completed` currently has no span_id | Certain | Medium | Requires the one-line `EventBuilder.pipeline_completed()` change described in Section 6. Without it, only node-level links work; pipeline-level "View Full Trace" is hidden. |
| **Logfire URL format changes** -- Pydantic updates their URL scheme | Very Low | Medium | URL construction is isolated in a single function (`buildLogfireUrl`). A format change requires updating one line. |
