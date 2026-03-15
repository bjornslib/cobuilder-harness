---
title: "SD-COBUILDER-WEB-001 Epic 9: wait.human Review Inbox"
status: active
type: reference
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E9
---

# SD-COBUILDER-WEB-001 Epic 9: wait.human Review Inbox (Frontend)

## 1. Problem Statement

`wait.human` gates in the CoBuilder pipeline are currently invisible to operators. When a pipeline node reaches `wait.human`, the runner writes a `.gate-wait` marker file and optionally dispatches a GChat notification. The operator must:

1. **Notice** the GChat message (often buried in threads)
2. **Context-switch** to a terminal or file browser to locate the relevant artifact (PRD, SD, validation report)
3. **Read** the artifact outside any structured interface
4. **Manually write** a signal JSON file (`{"result": "pass"}` or `{"result": "requeue", ...}`) to the correct signals directory
5. **Hope** the pipeline runner picks up the signal and resumes

This workflow has four concrete failure modes:

- **Missed gates.** GChat messages go unread; pipelines stall indefinitely with no dashboard indicator.
- **No contextual display.** A PRD review gate and an E2E validation review gate both look identical in GChat. The operator has no structured view of *what* they are reviewing or *why*.
- **Error-prone signal authoring.** Writing `{"result": "requeue", "requeue_target": "impl_backend", "reason": "..."}` by hand invites typos and malformed JSON.
- **No audit trail.** Handled reviews are consumed (moved to `processed/`) with no queryable history of who approved what, when, or why they rejected.

Epic 9 replaces this manual workflow with a web-based review inbox: a notification badge in the sidebar, a `/reviews` page with context-aware review cards, structured Approve/Reject actions that POST to the signals API, and a history tab for completed reviews.

## 2. Technical Architecture

### 2.1 Data Flow

```
pipeline_runner.py                    FastAPI Backend                     Next.js Frontend
      |                                     |                                   |
      | _handle_human() writes              |                                   |
      | {node_id}.gate-wait file            |                                   |
      |------------------------------------>|                                   |
      |                                     | GET /api/reviews/pending           |
      |                                     |   - scans signal_dir for           |
      |                                     |     *.gate-wait files              |
      |                                     |   - enriches with DOT node attrs   |
      |                                     |   - returns PendingReview[]        |
      |                                     |<----------------------------------|
      |                                     |                                   |
      |                                     | GET /api/reviews/pending/count     |
      |                                     |   - returns { count: N }           |
      |                                     |   - polled every 5s by badge       |
      |                                     |<----------------------------------|
      |                                     |                                   |
      |                                     | POST /api/initiatives/{id}/signal  |
      |                                     |   - writes signal JSON atomically  |
      |                                     |   - writes review to history log   |
      |                                     |   - returns { success: true }      |
      |                                     |<----------------------------------|
      |                                     |                                   |
      | _process_signals() reads            |                                   |
      | {node_id}.json signal file          |                                   |
      |<------------------------------------|                                   |
      | applies SIGNAL_TRANSITIONS          |                                   |
      | removes .gate-wait marker           |                                   |
```

### 2.2 Signal Directory Layout

All signal files live under `{dot_dir}/signals/` (resolved by the runner via `ATTRACTOR_SIGNALS_DIR` or git-root fallback). The review inbox interacts with two file types:

```
{dot_dir}/signals/
    review_prd.gate-wait          # Written by runner when wait.human activates
    review_prd.json               # Written by web UI when human approves/rejects
    review_sds.gate-wait
    review_e2e.gate-wait
    processed/                    # Consumed signals moved here by runner
        review_prd.json
    history/                      # NEW: review decisions persisted for audit
        2026-03-12T140000Z-review_prd-pass.json
        2026-03-12T153000Z-review_sds-requeue.json
```

### 2.3 Review Context Resolution

Different `wait.human` gate types require different context. The `mode` attribute on the DOT node determines which context loader runs:

| `mode` / Gate Name Pattern | Context Source | What to Display |
|---------------------------|---------------|-----------------|
| `review_prd` / mode unset | `output_path` attribute on predecessor `codergen` node | PRD markdown rendered inline |
| `review_sds` | All `output_path` attributes on predecessor SD-writer nodes | SD summaries with links to full files |
| `e2e-review` / `review_e2e` | Validation signal from `wait.cobuilder` predecessor | Validation score, gap list, test results |
| `review_final` / mode=`business` at terminal position | Pipeline summary: all node statuses, total duration, key metrics | Initiative summary dashboard |

Context resolution follows edges backwards from the `wait.human` node through the DOT graph to find the relevant artifacts.

### 2.4 Polling Strategy

The review inbox uses two polling intervals:

| Endpoint | Interval | Consumer | Purpose |
|----------|----------|----------|---------|
| `GET /api/reviews/pending/count` | 5 seconds | `NotificationBadge` | Lightweight integer check for sidebar badge |
| `GET /api/reviews/pending` | 10 seconds | `ReviewInbox` (when `/reviews` page is open) | Full review list with context |

Both use React Query's `refetchInterval`. The count endpoint is intentionally cheap (directory listing + count, no file parsing).

## 3. Component Specifications

### 3.1 Component Tree

```
app/layout.tsx
├── Sidebar
│   └── NotificationBadge              # Badge on "Reviews" nav item
│
app/reviews/page.tsx
├── ReviewInbox
│   ├── Tabs (shadcn)
│   │   ├── Tab: "Pending" (default)
│   │   │   └── ReviewCard[]           # One per pending wait.human gate
│   │   └── Tab: "History"
│   │       └── ReviewHistoryTable     # Handled reviews with timestamps
│   └── EmptyState                     # When no pending reviews
│
components/
├── NotificationBadge.tsx
├── ReviewCard.tsx
├── ReviewContextDisplay.tsx           # Context-aware: PRD | SD | E2E | Final
├── ReviewInbox.tsx
├── ReviewHistoryTable.tsx
├── ApproveRejectActions.tsx
└── RejectReasonDialog.tsx
```

### 3.2 NotificationBadge

**Location:** Rendered inside the sidebar nav, next to the "Reviews" link.

```tsx
// cobuilder/web/frontend/components/NotificationBadge.tsx

interface NotificationBadgeProps {
  /** Overrides polled count (for SSE-driven updates in future) */
  count?: number;
}
```

**Behavior:**
- Polls `GET /api/reviews/pending/count` every 5 seconds via `useQuery`
- Renders a shadcn `Badge` with variant `destructive` when count > 0
- Renders nothing (returns `null`) when count === 0
- Badge text: the count number (e.g., "3")
- Subtle entrance animation: `animate-in fade-in-0 zoom-in-75` (shadcn animation utilities)
- Accessible: `aria-label="N pending reviews"`

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";

export function NotificationBadge({ count: overrideCount }: NotificationBadgeProps) {
  const { data } = useQuery({
    queryKey: ["reviews", "count"],
    queryFn: () => fetch("/api/reviews/pending/count").then(r => r.json()),
    refetchInterval: 5_000,
  });

  const count = overrideCount ?? data?.count ?? 0;
  if (count === 0) return null;

  return (
    <Badge
      variant="destructive"
      className="ml-auto animate-in fade-in-0 zoom-in-75 text-xs px-1.5 py-0.5 min-w-[20px] text-center"
      aria-label={`${count} pending review${count !== 1 ? "s" : ""}`}
    >
      {count}
    </Badge>
  );
}
```

### 3.3 ReviewCard

**Location:** Rendered inside `ReviewInbox` for each pending `wait.human` gate.

```tsx
// cobuilder/web/frontend/components/ReviewCard.tsx

interface ReviewCardProps {
  review: PendingReview;
  onApprove: (nodeId: string) => Promise<void>;
  onReject: (nodeId: string, reason: string) => Promise<void>;
}

/** Shape returned by GET /api/reviews/pending */
interface PendingReview {
  node_id: string;               // DOT node identifier (e.g., "review_prd")
  initiative_id: string;         // Pipeline/initiative ID (e.g., "PRD-DASHBOARD-AUDIT-001")
  initiative_label: string;      // Human label from DOT graph[label] (e.g., "Dashboard Audit Trail")
  gate_label: string;            // DOT node label (e.g., "Review PRD")
  gate_type: ReviewGateType;     // Resolved from mode attr + node naming
  mode: string;                  // Raw mode attr from DOT node
  waiting_since: string;         // ISO timestamp from .gate-wait file
  context: ReviewContext;        // Type-specific context payload
}

type ReviewGateType = "review_prd" | "review_sds" | "review_e2e" | "review_final";

type ReviewContext =
  | { type: "review_prd"; prd_path: string; prd_content: string }
  | { type: "review_sds"; sds: Array<{ sd_path: string; sd_title: string; sd_summary: string }> }
  | { type: "review_e2e"; score: number; total: number; gaps: string[]; test_results: string }
  | { type: "review_final"; summary: InitiativeSummary };

interface InitiativeSummary {
  total_nodes: number;
  validated_nodes: number;
  failed_nodes: number;
  total_duration_s: number;
  key_artifacts: Array<{ label: string; path: string }>;
}
```

**Layout:**

```
┌──────────────────────────────────────────────────────────────┐
│  [Initiative Badge]  Dashboard Audit Trail                    │
│  Gate: Review PRD                     ⏱ Waiting 2h 15m       │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  [ReviewContextDisplay — type-specific content]               │
│                                                               │
├──────────────────────────────────────────────────────────────┤
│                            [Reject]  [Approve]                │
└──────────────────────────────────────────────────────────────┘
```

**Implementation:**

```tsx
"use client";

import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ReviewContextDisplay } from "./ReviewContextDisplay";
import { ApproveRejectActions } from "./ApproveRejectActions";
import { formatDistanceToNow } from "date-fns";

export function ReviewCard({ review, onApprove, onReject }: ReviewCardProps) {
  const waitingSince = formatDistanceToNow(new Date(review.waiting_since), {
    addSuffix: true,
  });

  return (
    <Card className="border-slate-700 bg-slate-900">
      <CardHeader className="flex flex-row items-start justify-between pb-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="text-xs border-blue-500 text-blue-400">
              {review.initiative_id}
            </Badge>
            <span className="text-sm font-medium text-slate-200">
              {review.initiative_label}
            </span>
          </div>
          <p className="text-sm text-slate-400">
            Gate: {review.gate_label}
          </p>
        </div>
        <span className="text-xs text-slate-500 whitespace-nowrap">
          Waiting {waitingSince}
        </span>
      </CardHeader>

      <CardContent className="pt-0">
        <ReviewContextDisplay context={review.context} />
      </CardContent>

      <CardFooter className="flex justify-end gap-2 pt-4 border-t border-slate-800">
        <ApproveRejectActions
          nodeId={review.node_id}
          initiativeId={review.initiative_id}
          onApprove={onApprove}
          onReject={onReject}
        />
      </CardFooter>
    </Card>
  );
}
```

### 3.4 ReviewContextDisplay

**Location:** Rendered inside `ReviewCard` to show gate-type-specific content.

```tsx
// cobuilder/web/frontend/components/ReviewContextDisplay.tsx

interface ReviewContextDisplayProps {
  context: ReviewContext;
}
```

**Context-type rendering:**

| Gate Type | Rendering |
|-----------|-----------|
| `review_prd` | Markdown content rendered via `react-markdown` with `remark-gfm`. Max height 400px with scroll. Link to raw file path. |
| `review_sds` | Accordion (shadcn) with one section per SD. Each section shows `sd_title` as trigger, `sd_summary` as content. Link to full SD file. |
| `review_e2e` | Score badge (`{score}/{total}`), color-coded (green >= 80%, amber >= 50%, red < 50%). Gap list as bulleted items. Collapsible raw test results. |
| `review_final` | Stats grid: total nodes, validated, failed, duration. Artifact links as a list. |

```tsx
"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";

export function ReviewContextDisplay({ context }: ReviewContextDisplayProps) {
  switch (context.type) {
    case "review_prd":
      return (
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            Source: <code className="text-slate-400">{context.prd_path}</code>
          </p>
          <div className="max-h-[400px] overflow-y-auto rounded-md border border-slate-700 bg-slate-950 p-4 prose prose-invert prose-sm max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {context.prd_content}
            </ReactMarkdown>
          </div>
        </div>
      );

    case "review_sds":
      return (
        <div className="space-y-2">
          <p className="text-xs text-slate-500">
            {context.sds.length} solution design{context.sds.length !== 1 ? "s" : ""} to review
          </p>
          <Accordion type="multiple" className="w-full">
            {context.sds.map((sd) => (
              <AccordionItem key={sd.sd_path} value={sd.sd_path} className="border-slate-700">
                <AccordionTrigger className="text-sm text-slate-200 hover:text-slate-100">
                  {sd.sd_title}
                </AccordionTrigger>
                <AccordionContent className="text-sm text-slate-400">
                  <p>{sd.sd_summary}</p>
                  <p className="mt-2 text-xs">
                    Full document: <code className="text-slate-400">{sd.sd_path}</code>
                  </p>
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>
      );

    case "review_e2e":
      return <E2EReviewContext context={context} />;

    case "review_final":
      return <FinalReviewContext context={context} />;
  }
}

function E2EReviewContext({
  context,
}: {
  context: Extract<ReviewContext, { type: "review_e2e" }>;
}) {
  const pct = context.total > 0 ? (context.score / context.total) * 100 : 0;
  const scoreColor =
    pct >= 80 ? "bg-green-500/20 text-green-400 border-green-500" :
    pct >= 50 ? "bg-amber-500/20 text-amber-400 border-amber-500" :
               "bg-red-500/20 text-red-400 border-red-500";

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Badge variant="outline" className={scoreColor}>
          {context.score}/{context.total} ({Math.round(pct)}%)
        </Badge>
        <span className="text-xs text-slate-500">Validation Score</span>
      </div>

      {context.gaps.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-slate-400">Gaps identified:</p>
          <ul className="list-disc list-inside text-sm text-slate-400 space-y-0.5">
            {context.gaps.map((gap, i) => (
              <li key={i}>{gap}</li>
            ))}
          </ul>
        </div>
      )}

      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button variant="ghost" size="sm" className="text-xs text-slate-500 hover:text-slate-300 p-0 h-auto">
            Show raw test results
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="mt-2 max-h-[300px] overflow-y-auto rounded-md border border-slate-700 bg-slate-950 p-3 text-xs text-slate-400 font-mono">
            {context.test_results}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}

function FinalReviewContext({
  context,
}: {
  context: Extract<ReviewContext, { type: "review_final" }>;
}) {
  const { summary } = context;
  const durationMin = Math.round(summary.total_duration_s / 60);

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-4 gap-3">
        <StatCard label="Total Nodes" value={summary.total_nodes} />
        <StatCard label="Validated" value={summary.validated_nodes} color="text-green-400" />
        <StatCard label="Failed" value={summary.failed_nodes} color="text-red-400" />
        <StatCard label="Duration" value={`${durationMin}m`} />
      </div>

      {summary.key_artifacts.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-slate-400">Key artifacts:</p>
          <ul className="text-sm text-slate-400 space-y-0.5">
            {summary.key_artifacts.map((a) => (
              <li key={a.path}>
                {a.label}: <code className="text-xs text-slate-500">{a.path}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  color = "text-slate-200",
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div className="rounded-md border border-slate-700 bg-slate-800 p-2 text-center">
      <div className={`text-lg font-semibold ${color}`}>{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  );
}
```

### 3.5 ApproveRejectActions

```tsx
// cobuilder/web/frontend/components/ApproveRejectActions.tsx

interface ApproveRejectActionsProps {
  nodeId: string;
  initiativeId: string;
  onApprove: (nodeId: string) => Promise<void>;
  onReject: (nodeId: string, reason: string) => Promise<void>;
}
```

**Behavior:**
- "Approve" button: `variant="default"` with green styling (`bg-green-600 hover:bg-green-700`). On click, calls `onApprove(nodeId)`. Shows loading spinner during POST.
- "Reject" button: `variant="outline"` with red border. On click, opens `RejectReasonDialog`. On dialog submit, calls `onReject(nodeId, reason)`.
- Both buttons are disabled while a request is in-flight (optimistic locking at the UI level).
- After either action completes, the card should disappear (handled by parent via React Query cache invalidation).

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { RejectReasonDialog } from "./RejectReasonDialog";

export function ApproveRejectActions({
  nodeId,
  initiativeId,
  onApprove,
  onReject,
}: ApproveRejectActionsProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);

  const handleApprove = async () => {
    setIsSubmitting(true);
    try {
      await onApprove(nodeId);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReject = async (reason: string) => {
    setIsSubmitting(true);
    try {
      await onReject(nodeId, reason);
    } finally {
      setIsSubmitting(false);
      setRejectDialogOpen(false);
    }
  };

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="border-red-500/50 text-red-400 hover:bg-red-500/10 hover:text-red-300"
        onClick={() => setRejectDialogOpen(true)}
        disabled={isSubmitting}
      >
        Reject
      </Button>
      <Button
        size="sm"
        className="bg-green-600 hover:bg-green-700 text-white"
        onClick={handleApprove}
        disabled={isSubmitting}
      >
        {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Approve"}
      </Button>
      <RejectReasonDialog
        open={rejectDialogOpen}
        onOpenChange={setRejectDialogOpen}
        onSubmit={handleReject}
        nodeId={nodeId}
        initiativeId={initiativeId}
        isSubmitting={isSubmitting}
      />
    </>
  );
}
```

### 3.6 RejectReasonDialog

```tsx
// cobuilder/web/frontend/components/RejectReasonDialog.tsx

interface RejectReasonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (reason: string) => Promise<void>;
  nodeId: string;
  initiativeId: string;
  isSubmitting: boolean;
}
```

**Behavior:**
- shadcn `Dialog` with a `Textarea` for the rejection reason.
- "Reject" button is disabled when textarea is empty or when `isSubmitting` is true.
- Minimum reason length: 10 characters (prevents empty/meaningless rejections).
- Placeholder text: "Explain what needs to change and why..."
- The reason text is included in the signal file and in the review history.

```tsx
"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";

export function RejectReasonDialog({
  open,
  onOpenChange,
  onSubmit,
  nodeId,
  initiativeId,
  isSubmitting,
}: RejectReasonDialogProps) {
  const [reason, setReason] = useState("");
  const isValid = reason.trim().length >= 10;

  const handleSubmit = async () => {
    if (!isValid) return;
    await onSubmit(reason.trim());
    setReason("");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-slate-900 border-slate-700">
        <DialogHeader>
          <DialogTitle className="text-slate-100">Reject Review</DialogTitle>
          <DialogDescription className="text-slate-400">
            Rejecting <code className="text-slate-300">{nodeId}</code> in{" "}
            <code className="text-slate-300">{initiativeId}</code>.
            The predecessor node will be requeued for rework.
          </DialogDescription>
        </DialogHeader>
        <Textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Explain what needs to change and why..."
          className="min-h-[100px] bg-slate-950 border-slate-700 text-slate-200 placeholder:text-slate-600"
        />
        {reason.length > 0 && reason.trim().length < 10 && (
          <p className="text-xs text-amber-400">Reason must be at least 10 characters</p>
        )}
        <DialogFooter>
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
            className="text-slate-400"
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleSubmit}
            disabled={!isValid || isSubmitting}
          >
            {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Reject & Requeue"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

### 3.7 ReviewInbox

**Location:** The main page component at `app/reviews/page.tsx`.

```tsx
// cobuilder/web/frontend/components/ReviewInbox.tsx

// No external props — fetches its own data via React Query
```

**Behavior:**
- Two tabs: "Pending" (default) and "History"
- Pending tab: renders `ReviewCard[]` from `GET /api/reviews/pending`, polled every 10s
- History tab: renders `ReviewHistoryTable` from `GET /api/reviews/history`
- Empty state on pending tab: illustration + "No pending reviews" text
- After approve/reject: invalidate both `["reviews", "pending"]` and `["reviews", "count"]` query keys so badge updates instantly

```tsx
"use client";

import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ReviewCard } from "./ReviewCard";
import { ReviewHistoryTable } from "./ReviewHistoryTable";
import { Inbox } from "lucide-react";

async function fetchPendingReviews(): Promise<PendingReview[]> {
  const res = await fetch("/api/reviews/pending");
  if (!res.ok) throw new Error("Failed to fetch pending reviews");
  return res.json();
}

async function postSignal(
  initiativeId: string,
  nodeId: string,
  result: "pass" | "requeue",
  reason?: string,
): Promise<void> {
  const body: Record<string, unknown> = { node_id: nodeId, result };
  if (result === "requeue" && reason) {
    body.reason = reason;
    body.requeue_target = nodeId; // Default: requeue the gate's predecessor
  }
  const res = await fetch(`/api/initiatives/${initiativeId}/signal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to post signal");
}

export function ReviewInbox() {
  const queryClient = useQueryClient();

  const { data: reviews = [], isLoading } = useQuery({
    queryKey: ["reviews", "pending"],
    queryFn: fetchPendingReviews,
    refetchInterval: 10_000,
  });

  const signalMutation = useMutation({
    mutationFn: (params: {
      initiativeId: string;
      nodeId: string;
      result: "pass" | "requeue";
      reason?: string;
    }) => postSignal(params.initiativeId, params.nodeId, params.result, params.reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["reviews", "pending"] });
      queryClient.invalidateQueries({ queryKey: ["reviews", "count"] });
      queryClient.invalidateQueries({ queryKey: ["reviews", "history"] });
    },
  });

  const handleApprove = async (nodeId: string) => {
    const review = reviews.find((r) => r.node_id === nodeId);
    if (!review) return;
    await signalMutation.mutateAsync({
      initiativeId: review.initiative_id,
      nodeId,
      result: "pass",
    });
  };

  const handleReject = async (nodeId: string, reason: string) => {
    const review = reviews.find((r) => r.node_id === nodeId);
    if (!review) return;
    await signalMutation.mutateAsync({
      initiativeId: review.initiative_id,
      nodeId,
      result: "requeue",
      reason,
    });
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-slate-100">Review Inbox</h1>
      <Tabs defaultValue="pending">
        <TabsList className="bg-slate-800 border-slate-700">
          <TabsTrigger value="pending" className="data-[state=active]:bg-slate-700">
            Pending ({reviews.length})
          </TabsTrigger>
          <TabsTrigger value="history" className="data-[state=active]:bg-slate-700">
            History
          </TabsTrigger>
        </TabsList>

        <TabsContent value="pending" className="mt-4 space-y-4">
          {isLoading ? (
            <ReviewCardSkeleton count={3} />
          ) : reviews.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-500">
              <Inbox className="h-12 w-12 mb-4 opacity-50" />
              <p className="text-lg">No pending reviews</p>
              <p className="text-sm">Pipeline reviews will appear here when a wait.human gate activates</p>
            </div>
          ) : (
            reviews.map((review) => (
              <ReviewCard
                key={review.node_id}
                review={review}
                onApprove={handleApprove}
                onReject={handleReject}
              />
            ))
          )}
        </TabsContent>

        <TabsContent value="history" className="mt-4">
          <ReviewHistoryTable />
        </TabsContent>
      </Tabs>
    </div>
  );
}
```

### 3.8 ReviewHistoryTable

```tsx
// cobuilder/web/frontend/components/ReviewHistoryTable.tsx

interface ReviewHistoryEntry {
  timestamp: string;          // ISO 8601
  initiative_id: string;
  node_id: string;
  gate_label: string;
  decision: "pass" | "requeue";
  reason: string | null;      // Only present for "requeue"
}
```

**Behavior:**
- Fetches from `GET /api/reviews/history` (reads from `signals/history/` directory)
- Sorted by timestamp descending (most recent first)
- Columns: Time, Initiative, Gate, Decision, Reason
- Decision column: green "Approved" badge or red "Rejected" badge
- Reason column: truncated to 80 chars with tooltip for full text
- Paginated: 20 entries per page (client-side pagination)

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { format } from "date-fns";

export function ReviewHistoryTable() {
  const { data: history = [] } = useQuery<ReviewHistoryEntry[]>({
    queryKey: ["reviews", "history"],
    queryFn: () => fetch("/api/reviews/history").then((r) => r.json()),
  });

  if (history.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        No review history yet.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow className="border-slate-700">
          <TableHead className="text-slate-400">Time</TableHead>
          <TableHead className="text-slate-400">Initiative</TableHead>
          <TableHead className="text-slate-400">Gate</TableHead>
          <TableHead className="text-slate-400">Decision</TableHead>
          <TableHead className="text-slate-400">Reason</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {history.map((entry) => (
          <TableRow key={`${entry.timestamp}-${entry.node_id}`} className="border-slate-800">
            <TableCell className="text-xs text-slate-400 whitespace-nowrap">
              {format(new Date(entry.timestamp), "MMM d, HH:mm")}
            </TableCell>
            <TableCell>
              <Badge variant="outline" className="text-xs border-slate-600 text-slate-300">
                {entry.initiative_id}
              </Badge>
            </TableCell>
            <TableCell className="text-sm text-slate-300">{entry.gate_label}</TableCell>
            <TableCell>
              <Badge
                variant={entry.decision === "pass" ? "default" : "destructive"}
                className={
                  entry.decision === "pass"
                    ? "bg-green-500/20 text-green-400 border-green-500"
                    : ""
                }
              >
                {entry.decision === "pass" ? "Approved" : "Rejected"}
              </Badge>
            </TableCell>
            <TableCell className="text-sm text-slate-400 max-w-[200px]">
              {entry.reason ? (
                entry.reason.length > 80 ? (
                  <Tooltip>
                    <TooltipTrigger className="text-left truncate block max-w-[200px]">
                      {entry.reason.slice(0, 80)}...
                    </TooltipTrigger>
                    <TooltipContent className="max-w-[400px] bg-slate-800 text-slate-200">
                      {entry.reason}
                    </TooltipContent>
                  </Tooltip>
                ) : (
                  entry.reason
                )
              ) : (
                <span className="text-slate-600">-</span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
```

## 4. Context-Aware Display

### 4.1 Context Resolution Algorithm

The backend resolves review context by traversing the DOT graph backwards from the `wait.human` node. The algorithm is:

```python
# cobuilder/web/api/infra/review_context.py

def resolve_review_context(
    node_id: str,
    dot_data: dict,
    signal_dir: str,
) -> dict:
    """Resolve context for a wait.human review card.

    1. Identify gate_type from node_id naming convention or 'mode' attribute:
       - node_id starts with "review_prd" OR mode == "prd-review" -> review_prd
       - node_id starts with "review_sd"  OR mode == "sd-review"  -> review_sds
       - node_id contains "e2e"          OR mode == "e2e-review" -> review_e2e
       - node_id starts with "review_final" OR terminal position -> review_final

    2. Walk predecessors in DOT graph (reverse edge traversal)

    3. Based on gate_type, extract relevant context:
       - review_prd:  find predecessor codergen node with worker_type="prd-writer",
                      read its output_path file content
       - review_sds:  find all predecessor codergen nodes with worker_type="solution-design-architect",
                      read each output_path file, extract title + first 3 lines as summary
       - review_e2e:  find predecessor wait.cobuilder node, read its signal file
                      from signals/{node_id}.json for score/gaps
       - review_final: aggregate all node statuses from DOT, compute duration from
                       timestamps, collect output_path attrs as key artifacts
    """
```

### 4.2 Gate Type Detection

The backend uses a two-pass detection strategy:

```python
GATE_TYPE_PATTERNS = {
    "review_prd":   lambda node: node["id"].startswith("review_prd") or node["attrs"].get("mode") == "prd-review",
    "review_sds":   lambda node: node["id"].startswith("review_sd") or node["attrs"].get("mode") == "sd-review",
    "review_e2e":   lambda node: "e2e" in node["id"] or node["attrs"].get("mode") == "e2e-review",
    "review_final": lambda node: node["id"].startswith("review_final") or node["attrs"].get("mode") == "business",
}

def detect_gate_type(node: dict, dot_data: dict) -> str:
    """Detect review gate type. Falls back to 'review_prd' if no pattern matches."""
    for gate_type, predicate in GATE_TYPE_PATTERNS.items():
        if predicate(node):
            return gate_type

    # Fallback: check if this is a terminal wait.human (no downstream non-exit nodes)
    downstream = [e["target"] for e in dot_data["edges"] if e["source"] == node["id"]]
    downstream_nodes = [n for n in dot_data["nodes"] if n["id"] in downstream]
    if all(n["attrs"].get("handler") == "exit" for n in downstream_nodes):
        return "review_final"

    return "review_prd"  # safe default
```

### 4.3 PRD Content Loading

For `review_prd` gates, the context loader reads the PRD file referenced in the predecessor node's `output_path` attribute. The content is truncated at 50KB to prevent oversized payloads:

```python
MAX_CONTEXT_BYTES = 50 * 1024  # 50 KB

def load_prd_context(predecessor_node: dict, target_dir: str) -> dict:
    output_path = predecessor_node["attrs"].get("output_path", "")
    abs_path = os.path.join(target_dir, output_path)
    try:
        content = Path(abs_path).read_text(encoding="utf-8")
        if len(content) > MAX_CONTEXT_BYTES:
            content = content[:MAX_CONTEXT_BYTES] + "\n\n[...truncated at 50KB]"
        return {
            "type": "review_prd",
            "prd_path": output_path,
            "prd_content": content,
        }
    except FileNotFoundError:
        return {
            "type": "review_prd",
            "prd_path": output_path,
            "prd_content": f"*File not found: {output_path}*",
        }
```

### 4.4 E2E Validation Context Loading

For `review_e2e` gates, the context is extracted from the predecessor `wait.cobuilder` node's signal file:

```python
def load_e2e_context(wait_cobuilder_node_id: str, signal_dir: str) -> dict:
    signal_path = os.path.join(signal_dir, f"{wait_cobuilder_node_id}.json")
    try:
        with open(signal_path) as fh:
            signal = json.load(fh)
        return {
            "type": "review_e2e",
            "score": signal.get("score", 0),
            "total": signal.get("total", 0),
            "gaps": signal.get("gaps", []),
            "test_results": signal.get("test_output", "No test output available"),
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "type": "review_e2e",
            "score": 0,
            "total": 0,
            "gaps": ["Unable to load validation results"],
            "test_results": "Signal file not found or malformed",
        }
```

## 5. Signal Protocol Integration

### 5.1 Signal File Format

When the user clicks Approve or Reject, the frontend POSTs to `POST /api/initiatives/{id}/signal`. The backend writes two files atomically:

**Approve signal** (consumed by pipeline runner):

```json
// {signal_dir}/{node_id}.json
{
  "result": "pass"
}
```

**Reject signal** (consumed by pipeline runner):

```json
// {signal_dir}/{node_id}.json
{
  "result": "requeue",
  "requeue_target": "write_prd",
  "reason": "PRD is missing success metrics for G2. Add measurable KPIs."
}
```

The `requeue_target` is resolved by the backend: it walks the DOT graph backwards from the `wait.human` node to find the most recent `codergen` predecessor. This is the node that will be reset to `pending` by the runner's `SIGNAL_TRANSITIONS["requeue"] = "pending"` mapping.

**Review history entry** (persisted for audit, never consumed by runner):

```json
// {signal_dir}/history/{timestamp}-{node_id}-{decision}.json
{
  "timestamp": "2026-03-12T14:00:00Z",
  "initiative_id": "PRD-DASHBOARD-AUDIT-001",
  "node_id": "review_prd",
  "gate_label": "Review PRD",
  "decision": "pass",
  "reason": null,
  "reviewed_by": "human"
}
```

### 5.2 Backend Signal Writer

```python
# In cobuilder/web/api/routers/signals.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from cobuilder.pipeline.signal_protocol import write_signal
import json
import os
from datetime import datetime, timezone

router = APIRouter()

class SignalRequest(BaseModel):
    node_id: str
    result: str = Field(pattern="^(pass|requeue)$")
    reason: str | None = None
    requeue_target: str | None = None  # Auto-resolved if not provided

class SignalResponse(BaseModel):
    success: bool
    signal_path: str
    history_path: str

@router.post("/api/initiatives/{initiative_id}/signal", response_model=SignalResponse)
async def post_signal(initiative_id: str, req: SignalRequest):
    signal_dir = resolve_signal_dir(initiative_id)
    if not signal_dir:
        raise HTTPException(status_code=404, detail=f"Initiative {initiative_id} not found")

    # Build signal payload
    payload: dict = {"result": req.result}
    if req.result == "requeue":
        if not req.reason:
            raise HTTPException(status_code=422, detail="Reason required for requeue")
        # Resolve requeue_target from DOT graph if not provided
        requeue_target = req.requeue_target or resolve_requeue_target(
            initiative_id, req.node_id
        )
        payload["reason"] = req.reason
        payload["requeue_target"] = requeue_target

    # Write signal file atomically (consumed by pipeline runner)
    signal_path = os.path.join(signal_dir, f"{req.node_id}.json")
    tmp_path = signal_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.rename(tmp_path, signal_path)

    # Write review history entry (never consumed by runner)
    history_dir = os.path.join(signal_dir, "history")
    os.makedirs(history_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    history_path = os.path.join(history_dir, f"{ts}-{req.node_id}-{req.result}.json")
    history_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "initiative_id": initiative_id,
        "node_id": req.node_id,
        "gate_label": resolve_gate_label(initiative_id, req.node_id),
        "decision": req.result,
        "reason": req.reason,
        "reviewed_by": "human",
    }
    with open(history_path, "w", encoding="utf-8") as fh:
        json.dump(history_entry, fh, indent=2)

    return SignalResponse(
        success=True,
        signal_path=signal_path,
        history_path=history_path,
    )
```

### 5.3 Requeue Target Resolution

When the user rejects a review without specifying a `requeue_target`, the backend resolves it automatically:

```python
def resolve_requeue_target(initiative_id: str, wait_human_node_id: str) -> str:
    """Walk backwards from wait.human node to find the nearest codergen predecessor.

    Resolution order:
    1. Direct predecessor with handler in (codergen, research, refine, acceptance-test-writer)
    2. Transitive predecessor (walk up to 3 hops back)
    3. Fallback: the wait.human node itself (runner will handle gracefully)
    """
    dot_data = parse_dot_file(get_dot_path(initiative_id))
    edges_by_target = defaultdict(list)
    for edge in dot_data["edges"]:
        edges_by_target[edge["target"]].append(edge["source"])
    nodes_by_id = {n["id"]: n for n in dot_data["nodes"]}

    WORKER_HANDLERS = {"codergen", "research", "refine", "acceptance-test-writer"}

    # BFS backwards, max 3 hops
    queue = edges_by_target.get(wait_human_node_id, [])
    visited = set()
    for _ in range(3):
        next_queue = []
        for pred_id in queue:
            if pred_id in visited:
                continue
            visited.add(pred_id)
            pred_node = nodes_by_id.get(pred_id)
            if pred_node and pred_node["attrs"].get("handler") in WORKER_HANDLERS:
                return pred_id
            next_queue.extend(edges_by_target.get(pred_id, []))
        queue = next_queue

    return wait_human_node_id  # fallback
```

### 5.4 Pipeline Runner Consumption

No changes to `pipeline_runner.py` are required. The runner already:

1. Watches `signal_dir` for `{node_id}.json` files via `_process_signals()`
2. Reads the signal JSON and applies `SIGNAL_TRANSITIONS`:
   - `"pass"` -> transitions node to `validated` then `accepted`
   - `"requeue"` -> transitions `requeue_target` back through `failed` -> `pending`
3. Removes the `.gate-wait` marker file after processing the signal
4. Stores `requeue_guidance` for the target node so the re-dispatched worker knows what failed

The web UI is just a structured way to write the same signal JSON files that the runner already expects.

## 6. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `cobuilder/web/frontend/app/reviews/page.tsx` | Reviews page shell, renders `ReviewInbox` |
| `cobuilder/web/frontend/components/NotificationBadge.tsx` | Sidebar badge showing pending review count |
| `cobuilder/web/frontend/components/ReviewCard.tsx` | Individual review card with context and actions |
| `cobuilder/web/frontend/components/ReviewContextDisplay.tsx` | Context-aware display (PRD/SD/E2E/Final) |
| `cobuilder/web/frontend/components/ApproveRejectActions.tsx` | Approve/Reject button pair |
| `cobuilder/web/frontend/components/RejectReasonDialog.tsx` | Modal dialog for rejection reason input |
| `cobuilder/web/frontend/components/ReviewInbox.tsx` | Main inbox component with tabs |
| `cobuilder/web/frontend/components/ReviewHistoryTable.tsx` | History tab with past decisions |
| `cobuilder/web/frontend/lib/api/reviews.ts` | API client functions for review endpoints |
| `cobuilder/web/frontend/types/review.ts` | TypeScript type definitions for review data |
| `cobuilder/web/api/routers/reviews.py` | FastAPI router: `GET /api/reviews/pending`, `GET /api/reviews/pending/count`, `GET /api/reviews/history` |
| `cobuilder/web/api/infra/review_context.py` | Context resolution: gate type detection, artifact loading |

### Modified Files

| File | Change |
|------|--------|
| `cobuilder/web/frontend/app/layout.tsx` | Add `NotificationBadge` to sidebar nav next to "Reviews" link |
| `cobuilder/web/api/routers/signals.py` | Add history entry write alongside signal file write |
| `cobuilder/web/api/main.py` | Mount `reviews` router |

### Unchanged Files (Integration Points)

| File | Integration |
|------|------------|
| `cobuilder/attractor/pipeline_runner.py` | Consumes `{node_id}.json` signal files written by the review inbox; no changes needed |
| `cobuilder/pipeline/signal_protocol.py` | Signal constants and directory resolution used by `review_context.py` |
| `cobuilder/attractor/parser.py` | DOT graph parsing used by context resolution |

## 7. Implementation Priority

| Step | Component | Depends On | Effort |
|------|-----------|-----------|--------|
| 1 | `types/review.ts` | None | S |
| 2 | `lib/api/reviews.ts` | Step 1 | S |
| 3 | `cobuilder/web/api/routers/reviews.py` (backend endpoints) | E2 (FastAPI core) | M |
| 4 | `cobuilder/web/api/infra/review_context.py` | Step 3 + E1 (InitiativeManager) | M |
| 5 | `NotificationBadge.tsx` | Step 2 | S |
| 6 | `ReviewContextDisplay.tsx` | Step 1 | M |
| 7 | `ApproveRejectActions.tsx` + `RejectReasonDialog.tsx` | Step 1 | S |
| 8 | `ReviewCard.tsx` | Steps 6, 7 | S |
| 9 | `ReviewHistoryTable.tsx` | Step 2 | S |
| 10 | `ReviewInbox.tsx` | Steps 8, 9 | M |
| 11 | `app/reviews/page.tsx` | Step 10 | S |
| 12 | `layout.tsx` modification (badge integration) | Step 5 | S |
| 13 | Signal history write in `signals.py` | E2 (signals router) | S |

**Total estimated effort:** 2-3 days for a frontend-dev-expert worker with backend endpoints already available from E2.

## 8. Acceptance Criteria

### AC-9.1: Badge Count

Badge count in sidebar nav updates within 5 seconds of a new `wait.human` gate activation. Badge disappears when count reaches zero.

**Verification:** Activate a `wait.human` gate by creating a `.gate-wait` marker file in the signals directory. Observe badge appears within one poll cycle (5s). Approve the review. Observe badge disappears.

### AC-9.2: Context-Aware Review Cards

Review card shows relevant context based on gate type:
- `review_prd` gate: shows PRD markdown content inline with syntax highlighting
- `review_sds` gate: shows accordion with one section per SD, each with title and summary
- `review_e2e` gate: shows validation score badge (color-coded), gap list, and collapsible test results
- `review_final` gate: shows stats grid (total/validated/failed nodes, duration) and artifact links

**Verification:** Create `.gate-wait` files for each gate type with appropriate predecessor nodes in the DOT graph. Verify each card renders the correct context type.

### AC-9.3: Approve Signal

Clicking "Approve" writes a signal file `{signal_dir}/{node_id}.json` containing `{"result": "pass"}` that unblocks the pipeline runner. The `.gate-wait` marker is removed by the runner after processing.

**Verification:** Click Approve on a pending review card. Verify signal file is written. Verify pipeline runner transitions the node to `validated` then `accepted`.

### AC-9.4: Reject Signal

Clicking "Reject" opens a reason dialog. Submitting with reason text writes `{signal_dir}/{node_id}.json` containing `{"result": "requeue", "requeue_target": "<resolved_predecessor>", "reason": "<user_text>"}`. The runner requeues the predecessor node.

**Verification:** Click Reject, enter reason text (>= 10 chars), submit. Verify signal file written with correct `requeue_target`. Verify runner resets predecessor to `pending`.

### AC-9.5: Card Disappears After Action

After either Approve or Reject, the review card disappears from the pending list within 2 seconds (via React Query cache invalidation, not waiting for next poll).

**Verification:** Approve a review. Observe the card is removed from the UI immediately after the POST completes.

### AC-9.6: History Tab

Handled reviews appear in the "History" tab with: timestamp, initiative ID, gate label, decision badge (green "Approved" / red "Rejected"), and reason text (for rejections).

**Verification:** Approve one review, reject another. Switch to History tab. Verify both entries appear with correct data and chronological ordering.

### AC-9.7: Empty State

When no reviews are pending, the Pending tab shows an empty state with icon and explanatory text (not a blank page).

**Verification:** Ensure no `.gate-wait` files exist. Navigate to `/reviews`. Verify empty state renders.

## 9. Risks

### R1: Stale Reviews

**Risk:** A `.gate-wait` marker file persists after the pipeline runner has already processed a signal for that node (e.g., another operator approved via CLI, or the runner timed out and marked the node as failed). The inbox shows a review card that, when acted upon, writes a signal for a node no longer in the expected state.

**Likelihood:** Medium (especially during development when manual signal files are common)

**Impact:** Low (runner ignores signals for nodes in terminal states — `validated`, `accepted` — as per `_apply_signal_to_graph` line 1766-1769)

**Mitigation:**
- Backend `GET /api/reviews/pending` cross-references each `.gate-wait` file against the DOT node's current status. If the node is not in `active` state, the `.gate-wait` file is stale and excluded from the response.
- Frontend: if POST returns a 409 Conflict (node already transitioned), show a toast "This review has already been handled" and remove the card.

### R2: Race Condition Between Concurrent Reviewers

**Risk:** Two operators both see the same pending review. Operator A clicks Approve, Operator B clicks Reject 2 seconds later. Both write signal files. The runner processes whichever it reads first; the second signal is ignored (node already in terminal state) but the second operator's history entry is misleading.

**Likelihood:** Low (single-operator system per PRD-COBUILDER-WEB-001 section 11: "Authentication: Localhost only")

**Impact:** Low (runner's idempotent signal processing prevents double-transition)

**Mitigation:**
- Signal files use atomic write-then-rename. If `{node_id}.json` already exists when the second write attempts the rename, the OS-level rename atomically replaces it. The runner reads whichever version is present at poll time.
- The backend checks for the existence of `{node_id}.json` before writing. If already present, returns 409 Conflict. The frontend handles this gracefully.
- History entries are timestamped and immutable (append-only). Even in a race, both decisions are recorded for audit. The "effective" decision is whichever the runner consumed.

### R3: Pipeline State Divergence After Approve

**Risk:** The user clicks Approve, the signal file is written, but the pipeline runner crashes before consuming it. The review card disappears from the UI (cache invalidated), but the pipeline is stalled.

**Likelihood:** Low

**Impact:** Medium (pipeline stalled without visible indicator)

**Mitigation:**
- The `.gate-wait` marker file is only removed by the runner, not by the web UI. If the runner crashes and restarts, it re-reads the signal file on the next `_process_signals()` cycle.
- The `NotificationBadge` count endpoint checks `.gate-wait` files, not the absence of signal files. If the gate-wait marker still exists after approval, the badge count will re-increment on the next poll, alerting the operator that the signal was not consumed.
- Future enhancement (not in this epic): SSE pipeline event `node.transitioned` confirms the runner consumed the signal. Until then, polling-based detection is the safety net.

### R4: Large Artifact Content in Review Cards

**Risk:** A PRD or SD file exceeds 50KB, causing slow API responses and browser rendering issues when displayed inline.

**Likelihood:** Medium (PRDs with embedded diagrams or long SDs can reach this size)

**Impact:** Low (performance degradation, not data loss)

**Mitigation:**
- Backend truncates content at 50KB with a `[...truncated at 50KB]` marker.
- Frontend `ReviewContextDisplay` uses `max-h-[400px] overflow-y-auto` for scrollable content areas.
- PRD/SD content is rendered via `react-markdown` which handles large documents efficiently with virtual scrolling potential in future iterations.

### R5: History Directory Growth

**Risk:** The `signals/history/` directory accumulates JSON files indefinitely. Over months with many initiatives, this could grow to thousands of small files.

**Likelihood:** Low (each review produces one ~200-byte file)

**Impact:** Low (filesystem handles small files well; `GET /api/reviews/history` may slow at scale)

**Mitigation:**
- History endpoint returns only the most recent 100 entries by default (configurable via `?limit=N` query parameter).
- Future enhancement: periodic archival of history older than 30 days into a single JSONL file.
