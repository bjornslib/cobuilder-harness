---
title: "SD-COBUILDER-WEB-001 Epic 8: Pipeline Graph View"
status: active
type: solution-design
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E8
---

# SD-COBUILDER-WEB-001 Epic 8: Pipeline Graph View (Frontend)

**Version**: 1.0.0
**Date**: 2026-03-12
**PRD**: PRD-COBUILDER-WEB-001, Epic 8
**Depends on**: Epic 3 (SSE Event Bridge), Epic 2 (FastAPI endpoints)
**Target directory**: `cobuilder/web/frontend/`

---

## 1. Problem Statement

There is currently no visual representation of the pipeline execution graph. Operators monitor initiative progress by reading tmux terminal output, running `cobuilder pipeline status` commands, or inspecting DOT files with a text editor. This makes it impossible to:

- See the overall pipeline topology at a glance
- Identify which nodes are active, completed, or blocked
- Correlate real-time SSE events with specific graph nodes
- Drill into node-level metrics (duration, tokens, Logfire traces)

Without a visual graph, operators must maintain the full pipeline topology in their heads while reading streams of text events. This cognitive load limits effective supervision to a single initiative at a time.

Epic 8 delivers an interactive pipeline graph view that renders the raw DOT file as a coloured SVG in the browser, updates node status in real-time via SSE, and provides click-to-inspect drill-down for every node.

---

## 2. Technical Architecture

### 2.1 Rendering Pipeline

```
DOT file (string)
    |
    v
@hpcc-js/wasm Graphviz.layout()
    |
    v
SVG string (Graphviz-generated layout)
    |
    v
DOMPurify.sanitize() (XSS defence-in-depth)
    |
    v
Inject sanitized SVG into container div via ref
    |
    v
CSS class injection per node (status colouring)
    |
    v
Click event listeners on SVG <g> node groups
```

The critical design decision: Graphviz handles ALL layout computation. The frontend never computes node positions or edge routing. The `@hpcc-js/wasm` library runs the Graphviz `dot` layout engine compiled to WebAssembly, accepting a raw DOT string and producing an SVG string. This SVG is then sanitized with DOMPurify and post-processed in the DOM to inject status-based CSS classes and click handlers.

**SVG injection safety**: Although the SVG is generated locally by the wasm Graphviz engine (not from user input), we sanitize with DOMPurify before DOM injection as a defence-in-depth measure. The DOT string originates from server-controlled files, but the rendering path should still be hardened.

### 2.2 Data Flow

```
                    +-----------------+
                    |  FastAPI Server  |
                    +--------+--------+
                             |
         +-------------------+-------------------+
         |                                       |
  GET /api/initiatives/{id}          GET /api/initiatives/{id}/events
  (returns DOT string +              (SSE stream: PipelineEvent JSON)
   parsed node attributes)
         |                                       |
         v                                       v
   DotGraph component                   useSSE() hook
   renders SVG from DOT                 updates nodeStatusMap
         |                                       |
         +-------------------+-------------------+
                             |
                      DOM patching:
                CSS classes on SVG <g> nodes
                             |
                             v
                    Interactive SVG
                   (click -> NodeInspector)
```

### 2.3 Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DOT rendering | `@hpcc-js/wasm` client-side | No server round-trip for layout; DOT file is the source of truth; Graphviz handles complex graph layouts that manual positioning cannot |
| SVG manipulation | CSS classes on `<g>` elements | Graphviz generates stable `id` attributes on node `<g>` groups matching the DOT node IDs; CSS-only colour changes avoid re-rendering the full SVG |
| Status colouring | CSS classes, not inline SVG attributes | Enables CSS animations (pulsing blue), dark theme overrides, and separation of concerns between layout (Graphviz) and presentation (Tailwind/CSS) |
| SSE integration | EventSource with buffered pause | Native browser API with auto-reconnect; buffer pattern retains events during pause without data loss |
| Component splitting | DotGraph + NodeInspector + EventStream | Each component has one concern: rendering, inspection, and event display |
| SVG injection | DOMPurify sanitization before DOM insert | Defence-in-depth; DOT source is trusted but rendering path should be hardened |

---

## 3. Component Specifications

### 3.1 Component Tree

```
/initiatives/[id]/graph/page.tsx    ("use client")
+-- DotGraph
|   +-- SVG container (Graphviz output)
|   +-- Status overlay (CSS classes per node)
+-- NodeInspector (side panel, conditionally rendered)
|   +-- Node header (label, handler, worker_type)
|   +-- Metrics section (duration, tokens, model)
|   +-- Logfire deep-link
+-- EventStream (bottom panel)
    +-- EventStreamToolbar (pause/resume, filter)
    +-- EventStreamTable (scrolling event rows)
```

### 3.2 DotGraph Component

```tsx
// cobuilder/web/frontend/components/DotGraph.tsx
"use client";

interface DotGraphProps {
  dotString: string;                          // Raw DOT file content
  nodeStatusMap: Map<string, NodeStatus>;     // node_id -> current status
  onNodeClick: (nodeId: string) => void;      // Opens NodeInspector
}

type NodeStatus = "pending" | "active" | "impl_complete" | "validated" | "failed";
```

**Responsibilities:**
- Accept raw DOT string and render to SVG via `@hpcc-js/wasm`
- Sanitize SVG output with DOMPurify before inserting into DOM
- Apply CSS status classes to SVG `<g>` elements based on `nodeStatusMap`
- Attach click handlers to node `<g>` elements
- Re-render SVG only when `dotString` changes (graph structure mutation)
- Apply CSS class updates without SVG re-render when only `nodeStatusMap` changes

**Internal state:**
- `svgContent: string` -- cached SVG output from Graphviz
- `graphvizReady: boolean` -- wasm module loaded
- `containerRef: RefObject<HTMLDivElement>` -- DOM ref for SVG container

### 3.3 NodeInspector Component

```tsx
// cobuilder/web/frontend/components/NodeInspector.tsx
"use client";

interface NodeInspectorProps {
  nodeId: string;
  nodeAttrs: NodeAttributes;      // From DOT parser: worker_type, handler, sd_path, etc.
  nodeEvents: PipelineEvent[];    // Filtered events for this node
  logfireProjectUrl?: string;     // Base URL for deep-links
  onClose: () => void;
}

interface NodeAttributes {
  label: string;
  handler: string;                // "codergen" | "research" | "refine" | "wait.human" | "wait.system3"
  worker_type?: string;           // "backend-solutions-engineer", "frontend-dev-expert", etc.
  sd_path?: string;
  status: NodeStatus;
}
```

**Displayed fields:**

| Field | Source | Always Shown |
|-------|--------|-------------|
| Node label | DOT `label` attribute | Yes |
| Handler type | DOT `handler` attribute | Yes |
| Worker type | DOT `worker_type` attribute | If present (codergen nodes only) |
| Status | `nodeStatusMap` | Yes |
| Duration | `node.completed` event `data.duration_ms` | If completed |
| Token count | `node.completed` event `data.tokens_used` | If completed |
| Visit count | `node.started` event `data.visit_count` | If started |
| Logfire trace | `node.completed` event `span_id` | If `span_id` present |

**Layout:** Right-side sheet panel (shadcn `Sheet`) sliding in from right, width 400px. Close on escape or click outside.

### 3.4 EventStream Component

```tsx
// cobuilder/web/frontend/components/EventStream.tsx
"use client";

interface EventStreamProps {
  events: PipelineEvent[];
  isPaused: boolean;
  onTogglePause: () => void;
  onEventClick: (event: PipelineEvent) => void;  // Highlights node in graph
}
```

**Columns:**

| Column | Width | Content |
|--------|-------|---------|
| Timestamp | 120px | `HH:MM:SS.mmm` (local time) |
| Type | 160px | Event type badge with colour coding |
| Node | 200px | `node_id` or "pipeline" for pipeline-level events |
| Detail | flex | Event-type-specific summary (see Section 3.5) |

**Behaviour:**
- Auto-scrolls to bottom when new events arrive (unless paused)
- Pause button freezes the display; events continue buffering in the hook
- Resume button flushes buffer and resumes auto-scroll
- Click on an event row highlights the corresponding node in the DotGraph (via `onEventClick`)
- Maximum 500 events rendered in the DOM; older events are virtualized out (windowing via CSS `overflow-y: auto` and `max-height`)

### 3.5 Event Type Display Formatting

| Event Type | Badge Colour | Detail Column |
|------------|-------------|---------------|
| `pipeline.started` | Blue | "Started ({node_count} nodes)" |
| `pipeline.completed` | Green | "Completed in {duration_ms}ms ({total_tokens} tokens)" |
| `pipeline.failed` | Red | "{error_type}: {error_message}" |
| `pipeline.resumed` | Blue | "Resumed from checkpoint ({completed_node_count} completed)" |
| `node.started` | Blue | "Handler: {handler_type}, visit #{visit_count}" |
| `node.completed` | Green | "Status: {outcome_status}, {duration_ms}ms, {tokens_used} tokens" |
| `node.failed` | Red | "{error_type}" + "(goal gate)" if goal_gate |
| `edge.selected` | Gray | "{from_node_id} -> {to_node_id}" + condition if present |
| `checkpoint.saved` | Gray | "Checkpoint: {checkpoint_path}" |
| `context.updated` | Gray | "+{keys_added.length} keys, ~{keys_modified.length} modified" |
| `retry.triggered` | Amber | "Attempt #{attempt_number}, backoff {backoff_ms}ms" |
| `loop.detected` | Red | "Visit {visit_count}/{limit}" |
| `validation.started` | Blue | "{rule_count} rules" |
| `validation.completed` | Green/Red | "Passed" or "{errors.length} errors, {warnings.length} warnings" |

---

## 4. @hpcc-js/wasm Integration

### 4.1 Installation

```bash
npm install @hpcc-js/wasm dompurify
npm install -D @types/dompurify
```

The `@hpcc-js/wasm` package provides the `Graphviz` class that loads the Graphviz wasm binary. The wasm file is ~3.5MB and must be loaded asynchronously.

### 4.2 Initialization Pattern

```tsx
// cobuilder/web/frontend/lib/graphviz.ts
import { Graphviz } from "@hpcc-js/wasm/graphviz";

let graphvizInstance: Awaited<ReturnType<typeof Graphviz.load>> | null = null;

export async function getGraphviz() {
  if (!graphvizInstance) {
    graphvizInstance = await Graphviz.load();
  }
  return graphvizInstance;
}

export async function renderDot(dotString: string): Promise<string> {
  const graphviz = await getGraphviz();
  return graphviz.layout(dotString, "svg", "dot");
}
```

**Key points:**
- `Graphviz.load()` is called ONCE and cached. The wasm binary loads ~500ms on first call, <1ms on subsequent calls.
- `layout(dot, "svg", "dot")` renders using the `dot` layout engine (hierarchical top-to-bottom, matching pipeline topology).
- The returned string is a complete `<svg>` element with `<g>` groups per node and edge.

### 4.3 SVG Sanitization and Injection

```tsx
// cobuilder/web/frontend/lib/svg-inject.ts
import DOMPurify from "dompurify";

/**
 * Sanitize Graphviz SVG output and inject into a container element.
 * Uses DOMPurify with SVG profile as defence-in-depth.
 */
export function injectSanitizedSvg(
  container: HTMLDivElement,
  svgString: string
): void {
  const clean = DOMPurify.sanitize(svgString, {
    USE_PROFILES: { svg: true, svgFilters: true },
    ADD_TAGS: ["title"],  // Graphviz uses <title> for node IDs
  });
  // Safe: content has been sanitized by DOMPurify
  container.replaceChildren();
  container.insertAdjacentHTML("afterbegin", clean);
}
```

### 4.4 SVG Node ID Convention

Graphviz generates SVG `<g>` elements with `id` attributes derived from DOT node IDs. For a DOT node `impl_backend`, Graphviz produces:

```xml
<g id="node3" class="node">
  <title>impl_backend</title>
  <ellipse ... />
  <text>Implement: Backend</text>
</g>
```

The `<title>` element contains the DOT node ID. The outer `id="nodeN"` is a Graphviz-generated sequential ID. To map SSE events to SVG elements:

1. Query all `<g class="node">` elements
2. Read the `<title>` child text content to get the DOT node ID
3. Build a `Map<string, SVGGElement>` for O(1) lookup during SSE updates

```tsx
function buildNodeMap(svgContainer: HTMLDivElement): Map<string, SVGGElement> {
  const map = new Map<string, SVGGElement>();
  const groups = svgContainer.querySelectorAll<SVGGElement>("g.node");
  for (const g of groups) {
    const title = g.querySelector("title");
    if (title?.textContent) {
      map.set(title.textContent.trim(), g);
    }
  }
  return map;
}
```

### 4.5 SVG Node Colouring Approach

**Approach: CSS class injection on `<g>` elements.**

After the SVG is sanitized and inserted into the DOM, iterate the node map and apply status-specific CSS classes to each `<g>` group. Graphviz-generated SVG uses `<ellipse>`, `<polygon>`, or `<path>` for node shapes; CSS targets these child elements via descendant selectors.

```css
/* cobuilder/web/frontend/app/graph.css */

/* Base node styling for dark theme */
.dot-graph g.node ellipse,
.dot-graph g.node polygon,
.dot-graph g.node path {
  transition: fill 300ms ease, stroke 300ms ease;
}

.dot-graph g.node text {
  fill: #e2e8f0; /* slate-200 */
  transition: fill 300ms ease;
}

/* Status: pending (gray) */
.dot-graph g.node.status-pending ellipse,
.dot-graph g.node.status-pending polygon {
  fill: #374151;    /* gray-700 */
  stroke: #6b7280;  /* gray-500 */
}

/* Status: active (pulsing blue) */
.dot-graph g.node.status-active ellipse,
.dot-graph g.node.status-active polygon {
  fill: #1e3a5f;
  stroke: #3b82f6;  /* blue-500 */
  animation: pulse-active 2s ease-in-out infinite;
}

@keyframes pulse-active {
  0%, 100% { stroke-opacity: 1; filter: drop-shadow(0 0 4px #3b82f6); }
  50%      { stroke-opacity: 0.5; filter: drop-shadow(0 0 8px #3b82f6); }
}

/* Status: impl_complete (amber) */
.dot-graph g.node.status-impl_complete ellipse,
.dot-graph g.node.status-impl_complete polygon {
  fill: #78350f;
  stroke: #f59e0b;  /* amber-500 */
}

/* Status: validated (green) */
.dot-graph g.node.status-validated ellipse,
.dot-graph g.node.status-validated polygon {
  fill: #064e3b;
  stroke: #10b981;  /* green-500 */
}

/* Status: failed (red) */
.dot-graph g.node.status-failed ellipse,
.dot-graph g.node.status-failed polygon {
  fill: #7f1d1d;
  stroke: #ef4444;  /* red-500 */
}

/* Hover state for clickable nodes */
.dot-graph g.node:hover {
  cursor: pointer;
}
.dot-graph g.node:hover ellipse,
.dot-graph g.node:hover polygon {
  stroke-width: 3;
  filter: brightness(1.2);
}

/* Selected node (inspector open) */
.dot-graph g.node.selected ellipse,
.dot-graph g.node.selected polygon {
  stroke-width: 3;
  stroke-dasharray: 5 3;
}

/* Edge styling for dark theme */
.dot-graph g.edge path {
  stroke: #4b5563;  /* gray-600 */
}
.dot-graph g.edge polygon {
  fill: #4b5563;
  stroke: #4b5563;
}
```

**Status class application function:**

```tsx
function applyStatusClasses(
  nodeMap: Map<string, SVGGElement>,
  statusMap: Map<string, NodeStatus>,
  selectedNodeId: string | null
) {
  const allStatuses = [
    "status-pending", "status-active", "status-impl_complete",
    "status-validated", "status-failed", "selected"
  ];
  for (const [nodeId, gElement] of nodeMap) {
    gElement.classList.remove(...allStatuses);
    const status = statusMap.get(nodeId) ?? "pending";
    gElement.classList.add(`status-${status}`);
    if (nodeId === selectedNodeId) {
      gElement.classList.add("selected");
    }
  }
}
```

### 4.6 When to Re-render SVG vs. Patch CSS

| Change | Action | Why |
|--------|--------|-----|
| Node status changes (SSE event) | CSS class update only | Layout unchanged; only colours change |
| DOT string changes (graph extension) | Full `Graphviz.layout()` re-render | New nodes/edges require new layout computation |
| Node selected/deselected | CSS class toggle | No layout change |
| Graph zoom/pan | CSS transform on container | SVG content unchanged |

This distinction is critical for performance. `Graphviz.layout()` takes 50-200ms for typical pipeline graphs (10-30 nodes). CSS class updates take <1ms.

---

## 5. Real-time Update Strategy

### 5.1 useSSE Hook

```tsx
// cobuilder/web/frontend/hooks/useSSE.ts
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

interface PipelineEvent {
  type: string;
  timestamp: string;
  pipeline_id: string;
  node_id: string | null;
  data: Record<string, unknown>;
  span_id: string | null;
  sequence: number;
}

interface UseSSEOptions {
  url: string;                       // GET /api/initiatives/{id}/events
  enabled?: boolean;                 // default true
}

interface UseSSEReturn {
  events: PipelineEvent[];           // All events (including buffered)
  nodeStatusMap: Map<string, NodeStatus>;
  isPaused: boolean;
  pause: () => void;
  resume: () => void;
  connectionState: "connecting" | "open" | "closed" | "error";
}

export function useSSE({ url, enabled = true }: UseSSEOptions): UseSSEReturn {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [connectionState, setConnectionState] =
    useState<"connecting" | "open" | "closed" | "error">("connecting");

  const bufferRef = useRef<PipelineEvent[]>([]);
  const nodeStatusMapRef = useRef(new Map<string, NodeStatus>());
  const [nodeStatusMap, setNodeStatusMap] =
    useState<Map<string, NodeStatus>>(new Map());

  const eventSourceRef = useRef<EventSource | null>(null);
  const lastSequenceRef = useRef<number>(0);

  // Derive node status from event
  const updateNodeStatus = useCallback((event: PipelineEvent) => {
    if (!event.node_id) return;
    const map = nodeStatusMapRef.current;
    switch (event.type) {
      case "node.started":
        map.set(event.node_id, "active");
        break;
      case "node.completed": {
        const outcome = event.data.outcome_status as string;
        if (outcome === "validated" || outcome === "accepted") {
          map.set(event.node_id, "validated");
        } else {
          map.set(event.node_id, "impl_complete");
        }
        break;
      }
      case "node.failed":
        map.set(event.node_id, "failed");
        break;
    }
    setNodeStatusMap(new Map(map));
  }, []);

  useEffect(() => {
    if (!enabled) return;

    const es = new EventSource(url);
    eventSourceRef.current = es;

    es.onopen = () => setConnectionState("open");
    es.onerror = () => setConnectionState("error");

    es.onmessage = (msg) => {
      try {
        const event: PipelineEvent = JSON.parse(msg.data);
        // Skip duplicates on reconnect
        if (event.sequence <= lastSequenceRef.current) return;
        lastSequenceRef.current = event.sequence;

        // Always update status map (even when paused)
        updateNodeStatus(event);

        if (isPaused) {
          bufferRef.current.push(event);
        } else {
          setEvents((prev) => [...prev, event]);
        }
      } catch {
        // Malformed event; skip
      }
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
      setConnectionState("closed");
    };
  }, [url, enabled, isPaused, updateNodeStatus]);

  const pause = useCallback(() => setIsPaused(true), []);

  const resume = useCallback(() => {
    if (bufferRef.current.length > 0) {
      setEvents((prev) => [...prev, ...bufferRef.current]);
      bufferRef.current = [];
    }
    setIsPaused(false);
  }, []);

  return {
    events, nodeStatusMap, isPaused, pause, resume, connectionState
  };
}
```

### 5.2 SSE Event to DOM Patch Flow

```
SSE message received
    |
    v
Parse JSON -> PipelineEvent
    |
    +---> updateNodeStatus() updates nodeStatusMapRef
    |         |
    |         v
    |     setNodeStatusMap(new Map(...))  // triggers React re-render
    |         |
    |         v
    |     DotGraph receives new nodeStatusMap prop
    |         |
    |         v
    |     useEffect: applyStatusClasses(nodeMap, nodeStatusMap, selectedNode)
    |         |
    |         v
    |     CSS class change on SVG <g> elements (no SVG re-render)
    |
    +---> Append to events array (or buffer if paused)
              |
              v
          EventStream component re-renders with new event row
```

### 5.3 Buffer Pattern (Pause/Resume)

When paused:
1. SSE connection stays OPEN (events keep flowing from server)
2. `nodeStatusMap` CONTINUES updating (graph colouring stays current)
3. New events are pushed to `bufferRef.current` (mutable ref, no re-render)
4. `EventStream` display freezes (events state not updated)

When resumed:
1. `bufferRef.current` is flushed into `events` state in a single batch
2. `EventStream` auto-scrolls to bottom to show all buffered events
3. Buffer is cleared

This ensures zero data loss during pause. The operator can pause to inspect an event, and when they resume, all intervening events appear at once.

### 5.4 Reconnection Handling

The native `EventSource` API auto-reconnects on network failure. On reconnect:
1. The server replays all events from the JSONL file (see Epic 3 replay mode)
2. The hook checks `event.sequence` against `lastSequenceRef.current`
3. Events with `sequence <= lastSequenceRef.current` are dropped (deduplication)
4. New events (higher sequence) are processed normally

If the server supports `Last-Event-ID`, the `id` field in SSE messages should be set to `event.sequence`. The browser sends this header on reconnect, allowing the server to skip replay of already-delivered events.

---

## 6. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `cobuilder/web/frontend/components/DotGraph.tsx` | @hpcc-js/wasm DOT-to-SVG renderer with DOMPurify sanitization, CSS status colouring, and click handlers |
| `cobuilder/web/frontend/components/NodeInspector.tsx` | Side panel (shadcn Sheet) showing node attributes, metrics, Logfire link |
| `cobuilder/web/frontend/components/EventStream.tsx` | Bottom panel: scrolling event log table with pause/resume toolbar |
| `cobuilder/web/frontend/hooks/useSSE.ts` | EventSource hook with pause/resume buffering, node status derivation, reconnect dedup |
| `cobuilder/web/frontend/lib/graphviz.ts` | Singleton `@hpcc-js/wasm` Graphviz loader and `renderDot()` utility |
| `cobuilder/web/frontend/lib/svg-inject.ts` | DOMPurify-based SVG sanitization and safe DOM injection |
| `cobuilder/web/frontend/app/initiatives/[id]/graph/page.tsx` | Page component composing DotGraph + NodeInspector + EventStream |
| `cobuilder/web/frontend/app/graph.css` | CSS for SVG node status colouring, animations (pulse-active), dark theme |
| `cobuilder/web/frontend/types/pipeline.ts` | TypeScript types: `PipelineEvent`, `NodeStatus`, `NodeAttributes` |

### Modified Files

| File | Change |
|------|--------|
| `cobuilder/web/frontend/package.json` | Add `@hpcc-js/wasm` and `dompurify` dependencies |
| `cobuilder/web/frontend/app/layout.tsx` | Import `graph.css` for global SVG styles |
| `cobuilder/web/frontend/next.config.ts` | Add `@hpcc-js/wasm` to `serverExternalPackages` (wasm files must not be bundled by Next.js server) |

### Integration Points (Unchanged)

| File | How Used |
|------|----------|
| `cobuilder/engine/events/types.py` | Canonical event type definitions; TypeScript types mirror this |
| `cobuilder/web/api/routers/pipelines.py` (Epic 3) | `GET /api/initiatives/{id}/events` SSE endpoint consumed by `useSSE` |
| `cobuilder/web/api/routers/initiatives.py` (Epic 2) | `GET /api/initiatives/{id}` returns DOT string and parsed node attributes |

---

## 7. Implementation Priority

| Step | Component | Depends On | Estimated Effort |
|------|-----------|-----------|-----------------|
| 1 | `types/pipeline.ts` | None | S (type definitions mirroring Python event types) |
| 2 | `lib/graphviz.ts` | `@hpcc-js/wasm` install | S (singleton loader + renderDot) |
| 3 | `graph.css` | None | S (CSS only, all status classes + dark theme) |
| 4 | `DotGraph.tsx` | Steps 1-3 | M (wasm init, SVG node mapping, CSS class application) |
| 5 | `hooks/useSSE.ts` | Step 1 | M (EventSource, buffering, status derivation) |
| 6 | `NodeInspector.tsx` | Step 1, shadcn Sheet | S (display-only component with conditional fields) |
| 7 | `EventStream.tsx` | Steps 1, 5 | M (table rendering, auto-scroll, pause/resume UI) |
| 8 | `graph/page.tsx` | Steps 4-7 | S (composition and layout of subcomponents) |
| 9 | `next.config.ts` + `package.json` | Step 2 | S (config changes) |

Steps 2-3 can proceed in parallel. Steps 4 and 5 can proceed in parallel. Step 8 is final assembly.

---

## 8. Acceptance Criteria

### AC-8.1: DOT Graph Renders Correctly
- [ ] DOT graph renders as SVG for all lifecycle stages: 3-node skeleton, SD-phase (7 nodes), full implementation (15+ nodes)
- [ ] Node shapes match DOT `shape` attributes: `box` for codergen, `hexagon` for wait.human, `diamond` for wait.system3, `tab` for research, `note` for refine, `Mdiamond` for start, `Msquare` for exit
- [ ] Edge routing is legible with no overlapping labels for graphs up to 30 nodes
- [ ] Graph renders within 500ms of page load (excluding wasm cold start)

### AC-8.2: Node Status Colouring
- [ ] `pending` nodes display gray fill (#374151) with gray stroke (#6b7280)
- [ ] `active` nodes display blue stroke (#3b82f6) with pulsing drop-shadow animation
- [ ] `impl_complete` nodes display amber stroke (#f59e0b)
- [ ] `validated` nodes display green stroke (#10b981)
- [ ] `failed` nodes display red stroke (#ef4444)
- [ ] Status transitions animate with 300ms ease transition (no visual jump)

### AC-8.3: Real-time SSE Updates
- [ ] Node colours update within 2 seconds of SSE `node.started`, `node.completed`, or `node.failed` event
- [ ] `nodeStatusMap` updates continue during pause (graph stays current)
- [ ] EventSource auto-reconnects on network failure; duplicate events are dropped via sequence-based deduplication
- [ ] `Last-Event-ID` is sent on reconnect to minimise server-side replay

### AC-8.4: Node Inspector
- [ ] Clicking a node opens the inspector side panel with correct attributes from the DOT file
- [ ] `node.completed` events populate duration and token count in the inspector
- [ ] Logfire deep-link renders as clickable link when `span_id` is available in the `node.completed` event
- [ ] Logfire link format: `{LOGFIRE_PROJECT_URL}/traces/{span_id}`
- [ ] Missing `span_id` shows "No trace available" text (no broken link)
- [ ] Clicking outside the panel or pressing Escape closes it

### AC-8.5: Event Stream
- [ ] All 14 event types display with human-readable formatting (per Section 3.5 table)
- [ ] Event stream auto-scrolls to latest event when not paused
- [ ] Pause button stops auto-scroll and display updates; events buffer in memory
- [ ] Resume button flushes buffered events and resumes auto-scroll
- [ ] Clicking an event row highlights the corresponding node in the graph (via CSS `selected` class)

### AC-8.6: Dark Theme
- [ ] Background uses dark gray (#111827 / gray-900)
- [ ] SVG edges render in gray-600 (#4b5563)
- [ ] Node label text renders in slate-200 (#e2e8f0)
- [ ] No white flashes during SVG re-render

---

## 9. Risks

### R1: Large Graph Performance (Likelihood: Medium, Impact: Medium)

**Risk:** Initiatives with 30+ nodes may produce SVG files with hundreds of elements. `Graphviz.layout()` computation time scales roughly O(n * e) where n = nodes and e = edges.

**Mitigation:**
- Cache the SVG output in a `useRef` and only re-render when `dotString` changes (not on status updates)
- For graphs >50 nodes, consider `fdp` or `neato` layout engine instead of `dot` (passed as third arg to `layout()`)
- Profile with the largest expected pipeline graph (full lifecycle ~20-25 nodes) during development
- Measured baseline: `@hpcc-js/wasm` renders 30-node hierarchical graphs in ~100ms

### R2: SVG Click Target Accuracy (Likelihood: Medium, Impact: Low)

**Risk:** Graphviz-generated SVG node shapes (ellipses, polygons) have small click targets. Label text overlapping edges can cause misclicks.

**Mitigation:**
- Attach click handlers to the `<g class="node">` group, not individual shapes. The group's bounding box covers the entire node including label.
- Add `pointer-events: bounding-box` on node `<g>` elements so the entire rectangle around the node is clickable, not just the shape fill.
- On hover, increase stroke-width to 3px and apply `brightness(1.2)` filter as visual affordance.

### R3: Wasm Loading Time (Likelihood: Low, Impact: Medium)

**Risk:** The `@hpcc-js/wasm` Graphviz wasm binary is ~3.5MB. First page load requires downloading and compiling the wasm module, which can take 1-3 seconds on slow connections.

**Mitigation:**
- Show a skeleton placeholder with "Loading graph engine..." text during wasm initialization
- Use a loading state in the DotGraph component keyed to `graphvizReady` boolean
- The wasm module is cached by the browser after first load; subsequent page visits load from cache
- Consider preloading the wasm file via `<link rel="preload" as="fetch" crossorigin>` in the layout head

### R4: SSE Connection Limits (Likelihood: Low, Impact: Low)

**Risk:** Browsers limit concurrent SSE connections to ~6 per domain (HTTP/1.1). Multiple open initiative tabs could exhaust the limit.

**Mitigation:**
- Only open SSE connection on the graph page (not the initiative list page)
- Close SSE connection when navigating away (`useEffect` cleanup)
- HTTP/2 multiplexing (if available) lifts this limit significantly
- Fallback: poll `GET /api/initiatives/{id}` every 5 seconds if SSE connection fails

### R5: DOT String / SVG Node ID Mismatch (Likelihood: Low, Impact: High)

**Risk:** If the DOT node ID in the `<title>` element does not exactly match the `node_id` in SSE events, status updates will silently fail to apply.

**Mitigation:**
- Both use the same DOT node ID string (e.g., `impl_backend`). The parser (`cobuilder/attractor/parser.py`) extracts node IDs, and `EventBuilder` uses the same IDs.
- Add a dev-mode console warning when an SSE event references a `node_id` not found in the SVG node map.
- Include node map size in the connection status indicator for debugging.
