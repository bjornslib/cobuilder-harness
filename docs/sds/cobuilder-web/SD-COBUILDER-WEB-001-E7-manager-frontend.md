---
title: "SD-COBUILDER-WEB-001 Epic 7: CoBuilder Manager Frontend"
status: active
type: reference
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E7
---

# SD-COBUILDER-WEB-001 Epic 7: CoBuilder Manager Frontend

**Version**: 1.0.0
**Date**: 2026-03-12
**PRD**: PRD-COBUILDER-WEB-001, Epic 7
**Target Directory**: `cobuilder/web/frontend/`
**Dependencies**: Epic 2 (FastAPI endpoints: `GET /api/initiatives`, `POST /api/initiatives`), Epic 3 (SSE event bridge)

---

## 1. Problem Statement

There is no central view for CoBuilder initiatives. Managing concurrent initiatives requires switching between tmux sessions, terminal commands (`bd list`, `cobuilder pipeline status`, `cat .pipelines/pipelines/*.dot`), and GChat. The operator cannot answer "What initiatives exist, what phase are they in, and what needs my attention?" without synthesizing information from 4+ sources.

Epic 7 delivers the **main screen** of the CoBuilder web interface: a single-page initiative list with lifecycle progress cards, a "New Initiative" creation dialog, and deep-links to Guardian tmux sessions and worktree directories. This is the entry point into the Control Tower -- the first page an operator sees.

### What This Epic Does NOT Cover

- Pipeline graph visualization (Epic 8)
- `wait.human` review inbox (Epic 9)
- Logfire deep-links (Epic 10)
- Initiative detail/drill-down page (Epic 8 scope)

---

## 2. Technical Architecture

### 2.1 Next.js App Structure

The frontend is a Next.js 15 App Router application. Epic 7 establishes the shell layout and the initiative list page.

```
cobuilder/web/frontend/
├── package.json
├── next.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── tsconfig.json
├── .env.local                          # NEXT_PUBLIC_API_URL=http://localhost:8000
├── app/
│   ├── layout.tsx                      # Root layout: dark theme, sidebar shell
│   ├── page.tsx                        # Initiative list (CoBuilder Manager main screen)
│   ├── globals.css                     # Tailwind base + dark theme CSS variables
│   └── initiatives/[id]/
│       └── page.tsx                    # Placeholder for Epic 8 (pipeline graph view)
├── components/
│   ├── ui/                             # shadcn/ui primitives (installed via CLI)
│   ├── layout/
│   │   ├── Sidebar.tsx                 # Navigation sidebar with review badge
│   │   └── TopBar.tsx                  # Header bar with session indicator
│   ├── InitiativeCard.tsx              # Phase progress + pipeline summary card
│   ├── InitiativeList.tsx              # Grid of InitiativeCard components
│   ├── NewInitiativeDialog.tsx         # Modal: create new initiative
│   └── PhaseProgressBar.tsx            # Visual pipeline phase indicator
├── hooks/
│   ├── useInitiatives.ts              # React Query hook for initiative list
│   └── useInitiativeSSE.ts            # SSE subscription for live updates
├── lib/
│   ├── api.ts                          # Fetch wrapper, base URL config
│   └── utils.ts                        # cn() helper (shadcn standard)
└── types/
    └── initiative.ts                   # TypeScript types for API responses
```

### 2.2 Component Hierarchy

```
app/layout.tsx (RootLayout)
├── Sidebar
│   ├── Nav links: Manager, Reviews (badge), Graph
│   └── Session indicator (connected/disconnected)
├── TopBar
│   └── "New Initiative" button
└── app/page.tsx (ManagerPage)
    └── InitiativeList
        ├── InitiativeCard (per initiative)
        │   ├── PhaseProgressBar
        │   ├── Pipeline node count summary
        │   ├── Pending review badge
        │   ├── "Open Guardian" button
        │   └── "View Worktree" button
        └── Empty state (no initiatives)
```

### 2.3 Rendering Strategy

| Component | Rendering | Rationale |
|-----------|-----------|-----------|
| `RootLayout` | Server Component (RSC) | Static shell, no interactivity |
| `Sidebar` | Server Component | Static navigation links |
| `TopBar` | Client Component | "New Initiative" button triggers dialog |
| `ManagerPage` | Server Component | Passes to client `InitiativeList` |
| `InitiativeList` | Client Component (`"use client"`) | Polling/SSE subscription, interactive |
| `InitiativeCard` | Client Component | Click handlers, live badge updates |
| `NewInitiativeDialog` | Client Component | Form state, API mutation |
| `PhaseProgressBar` | Client Component | Animated transitions on status change |

---

## 3. Component Specifications

### 3.1 TypeScript Types

```typescript
// types/initiative.ts

/** Node statuses as defined in DOT graph status attributes */
export type NodeStatus =
  | "pending"
  | "active"
  | "impl_complete"
  | "validated"
  | "failed"
  | "accepted";

/** Initiative lifecycle phases derived from DOT node analysis */
export type InitiativePhase =
  | "prd_drafting"
  | "prd_review"
  | "sd_writing"
  | "sd_review"
  | "research_refine"
  | "implementation"
  | "validation"
  | "final_review"
  | "complete"
  | "failed";

/** Summary of pipeline node statuses for a single initiative */
export interface PipelineNodeSummary {
  total: number;
  pending: number;
  active: number;
  impl_complete: number;
  validated: number;
  failed: number;
  accepted: number;
}

/** A single DOT graph node as returned by the API */
export interface PipelineNode {
  id: string;
  label: string;
  handler: string;
  status: NodeStatus;
  worker_type?: string;
  shape: string;
}

/** Pending review gate information */
export interface PendingReview {
  node_id: string;
  label: string;
  gate_type: "prd_review" | "sd_review" | "e2e_review" | "final_review";
  activated_at: string; // ISO 8601
}

/** Initiative summary as returned by GET /api/initiatives */
export interface Initiative {
  id: string;                           // PRD ID, e.g. "PRD-DASHBOARD-AUDIT-001"
  label: string;                        // Human-readable name from DOT graph label
  description: string;                  // Brief description
  target_repo: string;                  // Target repository path
  worktree_path: string | null;         // Worktree directory path, null if not yet created
  dot_path: string;                     // Path to DOT file
  phase: InitiativePhase;               // Current lifecycle phase
  node_summary: PipelineNodeSummary;    // Aggregated node status counts
  pending_reviews: PendingReview[];     // Active wait.human gates
  guardian_session: string | null;       // tmux session name, null if not running
  created_at: string;                   // ISO 8601
  updated_at: string;                   // ISO 8601
}

/** Request body for POST /api/initiatives */
export interface CreateInitiativeRequest {
  description: string;
  prd_id: string;
  target_repo?: string; // Optional: falls back to PROJECT_TARGET_REPO env var
}
```

### 3.2 InitiativeCard

```typescript
// components/InitiativeCard.tsx

interface InitiativeCardProps {
  initiative: Initiative;
  onOpenGuardian: (sessionName: string) => void;
  onViewWorktree: (path: string) => void;
  onNavigate: (id: string) => void;
}
```

**Layout**: shadcn `<Card>` with `CardHeader` + `CardContent` + `CardFooter`.

**Card Header**:
- Left: initiative label (h3) + PRD ID as muted subtitle
- Right: phase badge (colored by phase)

**Card Content**:
- `PhaseProgressBar` showing node status distribution
- Node summary: `{validated}/{total} nodes complete` text
- Pending review badges: one `<Badge variant="destructive">` per active `wait.human` gate

**Card Footer**:
- "Open Guardian" button (disabled if `guardian_session` is null)
- "View Worktree" button (disabled if `worktree_path` is null)
- Clickable card body navigates to `/initiatives/{id}`

**Phase Badge Color Mapping**:

| Phase | Color | Tailwind Class |
|-------|-------|----------------|
| `prd_drafting`, `sd_writing` | Electric blue | `bg-blue-500/20 text-blue-400 border-blue-500/30` |
| `prd_review`, `sd_review`, `final_review` | Amber | `bg-amber-500/20 text-amber-400 border-amber-500/30` |
| `research_refine` | Purple | `bg-purple-500/20 text-purple-400 border-purple-500/30` |
| `implementation` | Electric blue (pulsing) | `bg-blue-500/20 text-blue-400 animate-pulse` |
| `validation` | Amber (pulsing) | `bg-amber-500/20 text-amber-400 animate-pulse` |
| `complete` | Green | `bg-emerald-500/20 text-emerald-400 border-emerald-500/30` |
| `failed` | Red | `bg-red-500/20 text-red-400 border-red-500/30` |

### 3.3 PhaseProgressBar

```typescript
// components/PhaseProgressBar.tsx

interface PhaseProgressBarProps {
  summary: PipelineNodeSummary;
  className?: string;
}
```

**Design**: A horizontal stacked bar showing the proportion of nodes in each status. Each segment is colored by status.

**Segment Colors** (left to right order):

| Status | Color | Tailwind |
|--------|-------|----------|
| `validated` + `accepted` | Green (#10B981) | `bg-emerald-500` |
| `impl_complete` | Amber | `bg-amber-500` |
| `active` | Electric blue (#3B82F6) | `bg-blue-500` |
| `failed` | Red (#EF4444) | `bg-red-500` |
| `pending` | Dark gray | `bg-zinc-700` |

**Implementation**:

```tsx
export function PhaseProgressBar({ summary, className }: PhaseProgressBarProps) {
  const { total, validated, accepted, impl_complete, active, failed, pending } = summary;
  if (total === 0) return null;

  const segments = [
    { count: validated + accepted, color: "bg-emerald-500", label: "Validated" },
    { count: impl_complete, color: "bg-amber-500", label: "Impl Complete" },
    { count: active, color: "bg-blue-500", label: "Active" },
    { count: failed, color: "bg-red-500", label: "Failed" },
    { count: pending, color: "bg-zinc-700", label: "Pending" },
  ];

  return (
    <div className={cn("flex h-2 w-full overflow-hidden rounded-full", className)}>
      {segments.map((seg) =>
        seg.count > 0 ? (
          <div
            key={seg.label}
            className={cn(seg.color, "transition-all duration-500 ease-out")}
            style={{ width: `${(seg.count / total) * 100}%` }}
            title={`${seg.label}: ${seg.count}`}
          />
        ) : null
      )}
    </div>
  );
}
```

### 3.4 NewInitiativeDialog

```typescript
// components/NewInitiativeDialog.tsx

interface NewInitiativeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultTargetRepo: string; // Pre-configured from PROJECT_TARGET_REPO
  onCreated: (initiative: Initiative) => void;
}
```

**Fields**:

| Field | Input Type | Validation | Notes |
|-------|-----------|------------|-------|
| Description | `<Textarea>` | Required, 10-500 chars | Free text describing the initiative |
| PRD ID | `<Input>` | Required, pattern: `PRD-[A-Z]+-[0-9]+` | Auto-suggested from description (kebab-case of first 3 words) |
| Target Repo | `<Input>` | Required, valid path | Pre-filled from `defaultTargetRepo`, editable |

**PRD ID Auto-Suggestion Logic**:

```typescript
function suggestPrdId(description: string): string {
  const words = description
    .replace(/[^a-zA-Z0-9\s]/g, "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 3)
    .map((w) => w.toUpperCase());
  const suffix = "001";
  return `PRD-${words.join("-")}-${suffix}`;
}
```

The auto-suggestion runs on `onBlur` of the description field. The PRD ID field remains editable so the operator can override the suggestion.

**Submission**: `POST /api/initiatives` with `CreateInitiativeRequest` body. On success, calls `onCreated` and closes the dialog. On error, displays inline error message below the form (not a toast -- the dialog stays open for correction).

**shadcn Components Used**: `Dialog`, `DialogContent`, `DialogHeader`, `DialogTitle`, `DialogDescription`, `DialogFooter`, `Input`, `Textarea`, `Button`, `Label`.

### 3.5 Layout Shell (Sidebar + TopBar)

```typescript
// components/layout/Sidebar.tsx

interface SidebarProps {
  pendingReviewCount: number;
}
```

**Navigation Links**:

| Link | Route | Icon | Badge |
|------|-------|------|-------|
| Manager | `/` | `LayoutDashboard` (lucide) | -- |
| Reviews | `/reviews` | `CheckCircle` (lucide) | `pendingReviewCount` (red dot if > 0) |

**Sidebar Styling**: Fixed-width (240px), dark background (`bg-zinc-950`), with a subtle border-right (`border-r border-zinc-800`).

```typescript
// components/layout/TopBar.tsx

interface TopBarProps {
  onNewInitiative: () => void;
}
```

**Layout**: Full-width bar with:
- Left: "CoBuilder" wordmark (text, not image) + "Control Tower" subtitle
- Right: "New Initiative" button (`<Button variant="default">` with `Plus` icon)

---

## 4. Data Flow

### 4.1 API Client

```typescript
// lib/api.ts

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }

  return res.json();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const api = {
  listInitiatives: () => apiFetch<Initiative[]>("/api/initiatives"),

  getInitiative: (id: string) => apiFetch<Initiative>(`/api/initiatives/${id}`),

  createInitiative: (data: CreateInitiativeRequest) =>
    apiFetch<Initiative>("/api/initiatives", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};
```

### 4.2 React Query Hook (Polling)

```typescript
// hooks/useInitiatives.ts

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Initiative, CreateInitiativeRequest } from "@/types/initiative";

const POLL_INTERVAL_MS = 5_000;

export function useInitiatives() {
  return useQuery<Initiative[]>({
    queryKey: ["initiatives"],
    queryFn: api.listInitiatives,
    refetchInterval: POLL_INTERVAL_MS,
  });
}

export function useCreateInitiative() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: CreateInitiativeRequest) => api.createInitiative(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["initiatives"] });
    },
  });
}
```

### 4.3 SSE Hook (Live Updates)

The initiative list uses **polling** as the primary update mechanism (5-second interval). SSE is available as an enhancement for real-time badge updates without waiting for the next poll cycle.

```typescript
// hooks/useInitiativeSSE.ts

import { useEffect, useRef, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Subscribe to SSE events for a specific initiative.
 * On receiving node status change events, invalidates the initiatives query
 * to trigger an immediate refetch rather than waiting for the poll interval.
 */
export function useInitiativeSSE(initiativeId: string | null) {
  const queryClient = useQueryClient();
  const eventSourceRef = useRef<EventSource | null>(null);

  const handleEvent = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data);
        // Any node status change should refresh the initiative list
        if (
          data.type === "node.started" ||
          data.type === "node.completed" ||
          data.type === "node.failed" ||
          data.type === "pipeline.completed" ||
          data.type === "pipeline.failed"
        ) {
          queryClient.invalidateQueries({ queryKey: ["initiatives"] });
        }
      } catch {
        // Ignore malformed events
      }
    },
    [queryClient],
  );

  useEffect(() => {
    if (!initiativeId) return;

    const es = new EventSource(
      `${API_BASE}/api/initiatives/${initiativeId}/events`,
    );
    eventSourceRef.current = es;

    es.onmessage = handleEvent;

    es.onerror = () => {
      // EventSource auto-reconnects. Log for debugging.
      console.warn(`SSE connection error for initiative ${initiativeId}`);
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
  }, [initiativeId, handleEvent]);
}
```

### 4.4 State Management Strategy

**No dedicated state management library** (no Zustand, no Redux). Rationale:

1. The initiative list is the only stateful data on this page.
2. React Query owns the server state cache (fetching, caching, invalidation, polling).
3. Local UI state (dialog open/close, form fields) lives in React `useState`.
4. SSE events trigger React Query cache invalidation, not separate state updates.

If Epic 8 or 9 introduce complex cross-page state, Zustand can be added then. For Epic 7, React Query + local state is sufficient and avoids premature abstraction.

---

## 5. Dark Theme Specification

### 5.1 Design Rationale

Operators use the Control Tower at odd hours during long-running initiative runs. Dark theme is the default (and only theme in v1). The color palette uses zinc grays for surfaces, electric blue for active/interactive elements, and high-contrast text for readability.

### 5.2 Color Palette

| Token | Hex | Usage | Tailwind |
|-------|-----|-------|----------|
| Background | `#09090B` | Page background | `bg-zinc-950` |
| Surface | `#18181B` | Card backgrounds, sidebar | `bg-zinc-900` |
| Surface raised | `#27272A` | Hover states, active cards | `bg-zinc-800` |
| Border | `#3F3F46` | Card borders, dividers | `border-zinc-700` |
| Border subtle | `#27272A` | Inner separators | `border-zinc-800` |
| Text primary | `#FAFAFA` | Headings, primary content | `text-zinc-50` |
| Text secondary | `#A1A1AA` | Subtitles, descriptions | `text-zinc-400` |
| Text muted | `#71717A` | Timestamps, tertiary info | `text-zinc-500` |
| Active / Interactive | `#3B82F6` | Active nodes, buttons, links | `text-blue-500` |
| Validated / Success | `#10B981` | Validated nodes, success badges | `text-emerald-500` |
| Failed / Error | `#EF4444` | Failed nodes, error badges | `text-red-500` |
| Warning / Pending review | `#F59E0B` | Amber warnings, `wait.human` | `text-amber-500` |
| Research / Refine | `#A855F7` | Research/refine phase | `text-purple-500` |

### 5.3 Tailwind Configuration

```typescript
// tailwind.config.ts

import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Semantic aliases for the CoBuilder palette
        "cb-active": "#3B82F6",
        "cb-validated": "#10B981",
        "cb-failed": "#EF4444",
        "cb-warning": "#F59E0B",
        "cb-research": "#A855F7",
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")], // Required by shadcn/ui
};

export default config;
```

### 5.4 CSS Variables (globals.css)

```css
/* app/globals.css */

@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    /* shadcn/ui CSS variables — dark theme as default */
    --background: 240 10% 3.9%;          /* zinc-950 */
    --foreground: 0 0% 98%;              /* zinc-50 */
    --card: 240 10% 6.5%;               /* zinc-900 */
    --card-foreground: 0 0% 98%;
    --popover: 240 10% 6.5%;
    --popover-foreground: 0 0% 98%;
    --primary: 217 91% 60%;             /* blue-500 (#3B82F6) */
    --primary-foreground: 0 0% 98%;
    --secondary: 240 5% 16%;            /* zinc-800 */
    --secondary-foreground: 0 0% 98%;
    --muted: 240 5% 16%;
    --muted-foreground: 240 4% 46%;     /* zinc-500 */
    --accent: 240 5% 16%;
    --accent-foreground: 0 0% 98%;
    --destructive: 0 84% 60%;           /* red-500 (#EF4444) */
    --destructive-foreground: 0 0% 98%;
    --border: 240 4% 26%;              /* zinc-700 */
    --input: 240 4% 26%;
    --ring: 217 91% 60%;               /* blue-500 */
    --radius: 0.5rem;
  }

  * {
    @apply border-border;
  }

  body {
    @apply bg-background text-foreground;
  }
}
```

---

## 6. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `cobuilder/web/frontend/package.json` | Next.js 15 project manifest with dependencies |
| `cobuilder/web/frontend/next.config.ts` | Next.js configuration (API proxy rewrite) |
| `cobuilder/web/frontend/tailwind.config.ts` | Tailwind config with dark theme + CoBuilder colors |
| `cobuilder/web/frontend/postcss.config.js` | PostCSS config for Tailwind |
| `cobuilder/web/frontend/tsconfig.json` | TypeScript config with path aliases |
| `cobuilder/web/frontend/.env.local` | `NEXT_PUBLIC_API_URL=http://localhost:8000` |
| `cobuilder/web/frontend/app/layout.tsx` | Root layout: dark class, font, sidebar shell |
| `cobuilder/web/frontend/app/page.tsx` | Manager page: initiative list + "New Initiative" trigger |
| `cobuilder/web/frontend/app/globals.css` | Tailwind base + dark theme CSS variables |
| `cobuilder/web/frontend/app/initiatives/[id]/page.tsx` | Stub for Epic 8 (pipeline graph view) |
| `cobuilder/web/frontend/components/layout/Sidebar.tsx` | Navigation sidebar with review badge |
| `cobuilder/web/frontend/components/layout/TopBar.tsx` | Header bar with "New Initiative" button |
| `cobuilder/web/frontend/components/InitiativeCard.tsx` | Initiative summary card component |
| `cobuilder/web/frontend/components/InitiativeList.tsx` | Grid of InitiativeCard components |
| `cobuilder/web/frontend/components/NewInitiativeDialog.tsx` | Modal dialog for initiative creation |
| `cobuilder/web/frontend/components/PhaseProgressBar.tsx` | Stacked bar showing node status distribution |
| `cobuilder/web/frontend/hooks/useInitiatives.ts` | React Query hook for initiative list + creation |
| `cobuilder/web/frontend/hooks/useInitiativeSSE.ts` | SSE subscription for live cache invalidation |
| `cobuilder/web/frontend/lib/api.ts` | Typed fetch wrapper for FastAPI backend |
| `cobuilder/web/frontend/lib/utils.ts` | `cn()` helper (shadcn standard: clsx + twMerge) |
| `cobuilder/web/frontend/types/initiative.ts` | TypeScript interfaces for API contract |

### shadcn/ui Components to Install

```bash
npx shadcn@latest init   # Initializes shadcn config + CSS variables
npx shadcn@latest add card badge button dialog input textarea label
```

These install into `cobuilder/web/frontend/components/ui/` and are committed to the repo (shadcn pattern: copy, not import).

### Modified Files

None. Epic 7 is a greenfield frontend build. The backend API endpoints it consumes are built in Epic 2.

### npm Dependencies

```json
{
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "@tanstack/react-query": "^5.0.0",
    "lucide-react": "^0.400.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.3.0",
    "tailwindcss-animate": "^1.0.0"
  },
  "devDependencies": {
    "typescript": "^5.5.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "@types/node": "^22.0.0"
  }
}
```

---

## 7. Implementation Priority

| Step | Component | Depends On | Estimated Effort |
|------|-----------|------------|-----------------|
| 1 | Project scaffolding (`npx create-next-app`, Tailwind, shadcn init) | -- | 15 min |
| 2 | `types/initiative.ts` | API contract (Epic 2 SD) | 15 min |
| 3 | `lib/api.ts` + `lib/utils.ts` | Step 2 | 20 min |
| 4 | `globals.css` + `tailwind.config.ts` (dark theme) | Step 1 | 20 min |
| 5 | shadcn component installation (card, badge, button, dialog, input, textarea, label) | Step 4 | 10 min |
| 6 | `PhaseProgressBar` | Step 2 | 30 min |
| 7 | `InitiativeCard` | Steps 5, 6 | 45 min |
| 8 | `Sidebar` + `TopBar` | Step 5 | 30 min |
| 9 | `app/layout.tsx` (root layout with sidebar shell) | Step 8 | 20 min |
| 10 | `hooks/useInitiatives.ts` (React Query) | Step 3 | 20 min |
| 11 | `InitiativeList` + `app/page.tsx` | Steps 7, 10 | 30 min |
| 12 | `NewInitiativeDialog` | Steps 5, 10 | 45 min |
| 13 | `hooks/useInitiativeSSE.ts` | Step 10, Epic 3 (SSE endpoint) | 30 min |
| 14 | Integration testing with backend | Steps 1-13, Epic 2 running | 60 min |

**Total estimated effort**: ~6 hours

**Critical path**: Steps 1-4 (scaffolding + theme) unblock all component work. Step 14 requires a running Epic 2 backend.

---

## 8. Acceptance Criteria

### AC-7.1: Initiative List Display

- [ ] `GET /api/initiatives` is called on page load and every 5 seconds thereafter
- [ ] Each initiative from the API response renders as an `InitiativeCard`
- [ ] Cards are displayed in a responsive grid: 3 columns on `xl` (1280px+), 2 on `lg` (1024px+), 1 on `md` and below
- [ ] When no initiatives exist, an empty state message is displayed: "No initiatives yet. Create one to get started."

### AC-7.2: Phase Progress Accuracy

- [ ] `PhaseProgressBar` segments accurately reflect DOT node status counts from `node_summary`
- [ ] Segment widths are proportional to node counts (e.g., 5 validated out of 10 total = 50% green)
- [ ] Phase badge text on each card matches the `phase` field from the API

### AC-7.3: Pending Review Badges

- [ ] When an initiative has `pending_reviews.length > 0`, a red badge appears on the card showing the count
- [ ] Badge updates within 5 seconds of a `wait.human` gate activation (via polling)
- [ ] With SSE enabled, badge updates within 2 seconds of gate activation

### AC-7.4: New Initiative Creation

- [ ] "New Initiative" button opens a modal dialog
- [ ] PRD ID is auto-suggested from the description field on blur
- [ ] PRD ID auto-suggestion follows the pattern `PRD-{WORD1}-{WORD2}-{WORD3}-001`
- [ ] Target repo is pre-filled from environment configuration
- [ ] Form validates: description required (10-500 chars), PRD ID matches `PRD-[A-Z]+-[0-9]+`
- [ ] Successful submission closes the dialog and the new initiative appears in the list
- [ ] Failed submission displays an inline error without closing the dialog

### AC-7.5: Deep-Link Buttons

- [ ] "Open Guardian" button is enabled when `guardian_session` is not null
- [ ] "Open Guardian" either copies the tmux attach command to clipboard or opens Terminal.app via `open -a Terminal`
- [ ] "View Worktree" button is enabled when `worktree_path` is not null
- [ ] "View Worktree" triggers `open {worktree_path}` to open in Finder, or opens in VS Code via `code {worktree_path}`

### AC-7.6: Dark Theme

- [ ] Page background is zinc-950 (`#09090B`)
- [ ] Card backgrounds are zinc-900 (`#18181B`)
- [ ] Active/interactive elements use electric blue (`#3B82F6`)
- [ ] Validated elements use green (`#10B981`)
- [ ] Failed elements use red (`#EF4444`)
- [ ] Text has sufficient contrast ratio (WCAG AA: 4.5:1 for body text)

### AC-7.7: Loading and Error States

- [ ] Initial page load shows skeleton cards (shadcn `<Skeleton>`) matching card dimensions
- [ ] API error displays a toast notification with retry action
- [ ] Network disconnection shows a subtle "Connection lost" indicator in the sidebar

---

## 9. Risks and Mitigations

### R1: Stale Initiative Data (Polling Lag)

**Risk**: With 5-second polling, the UI can show data up to 5 seconds stale. During active pipeline runs, node transitions happen faster than the poll interval.

**Likelihood**: Medium. **Impact**: Low (cosmetic -- operator sees stale badge for a few seconds).

**Mitigation**: SSE subscription (`useInitiativeSSE`) invalidates the React Query cache on node status events, triggering an immediate refetch. SSE is the primary real-time mechanism; polling is the fallback that guarantees updates even if SSE disconnects.

### R2: SSE Connection Drops and Reconnection

**Risk**: Browser `EventSource` auto-reconnects on disconnect, but there is a gap during reconnection where events are missed. If the backend does not support `Last-Event-ID`, the client has no way to catch up.

**Likelihood**: Medium (network instability, backend restarts). **Impact**: Low (polling catches up within 5 seconds).

**Mitigation**: (1) The backend SSE endpoint (Epic 3) supports `Last-Event-ID` for event replay. (2) Polling runs independently of SSE, so the worst case is a 5-second delay. (3) On SSE reconnection, the hook calls `queryClient.invalidateQueries` to force an immediate refetch regardless of replay support.

### R3: Large Initiative Lists (> 50 initiatives)

**Risk**: If the system accumulates many initiatives over time, rendering 50+ `InitiativeCard` components with polling every 5 seconds could cause performance issues (DOM size, network bandwidth).

**Likelihood**: Low in v1 (most operators manage 5-10 concurrent initiatives). **Impact**: Medium (UI jank, slow responses).

**Mitigation**: (1) API pagination: `GET /api/initiatives?status=active&offset=0&limit=20` -- but this is an API-side concern (Epic 2). (2) Client-side: add a status filter toggle (Active / Completed / All) to reduce rendered card count. (3) React Query's `staleTime` can be increased for completed initiatives that no longer change. (4) Virtual scrolling (e.g., `@tanstack/react-virtual`) can be added if the list exceeds 50 cards.

### R4: Backend Not Running During Frontend Development

**Risk**: Frontend developers cannot test against the real API without Epic 2 running.

**Likelihood**: Certain during initial development. **Impact**: Medium (blocks integration testing).

**Mitigation**: (1) Create a `lib/mock-data.ts` file with realistic `Initiative[]` fixtures. (2) Use Next.js API route handlers (`app/api/initiatives/route.ts`) as a local mock server that returns fixture data. (3) Toggle between mock and real API via `NEXT_PUBLIC_API_URL` env var. The mock routes are deleted when the real backend is available.

### R5: "Open Guardian" / "View Worktree" OS Integration

**Risk**: The `open -a Terminal` and `open {path}` commands work on macOS but not on Linux. VS Code's `code` command must be in PATH.

**Likelihood**: Low (PRD specifies macOS-only / desktop-only). **Impact**: Low.

**Mitigation**: (1) Deep-link buttons call the backend (`POST /api/guardian/{id}/attach` and similar), which executes the OS-specific command server-side. The frontend does not shell out. (2) As a fallback, the button copies the tmux attach command to the clipboard and shows a toast: "Copied: `tmux attach -t guardian-{id}`".

---

## 10. Open Questions

| ID | Question | Impact | Proposed Resolution |
|----|----------|--------|---------------------|
| OQ-1 | Should the initiative list auto-sort by `updated_at` or by phase priority (reviews first)? | UX ordering | Default: reviews first (initiatives with `pending_reviews.length > 0` sort to top), then by `updated_at` descending. Add a sort dropdown in v2. |
| OQ-2 | Should "View Worktree" open Finder or VS Code? | UX preference | Offer both: primary click opens VS Code (`code {path}`), secondary action (right-click / dropdown) opens Finder. If `code` is not in PATH, fall back to Finder. |
| OQ-3 | What happens when the backend returns a DOT file with no `label` attribute? | Display fallback | Use the `prd_id` as the card title. Display a warning icon indicating the initiative has no description. |
