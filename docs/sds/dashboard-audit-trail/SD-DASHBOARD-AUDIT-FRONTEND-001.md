---
title: "SD-DASHBOARD-AUDIT-FRONTEND-001: Case Detail Page Frontend Redesign"
status: draft
type: guide
grade: authoritative
last_verified: 2026-03-09
---

# SD-DASHBOARD-AUDIT-FRONTEND-001: Case Detail Page Frontend Redesign

**Version**: 0.2.0 (Incorporated research findings from SD-DASHBOARD-AUDIT-001)
**Date**: 2026-03-09
**PRD**: PRD-DASHBOARD-AUDIT-001, Epic B
**Design Source**: Stitch project `4785994430092730679`, screen `2906fd2e2b044991b8e672b9c41e3bc5`
**Target Repo**: `zenagent3/zenagent/agencheck/agencheck-support-frontend`
**Constraint**: Main navigation (header) and side navigation (sidebar) are OUT OF SCOPE

---

## 1. Design Analysis (from Stitch HTML)

The Stitch design shows a case detail page at `/checks-dashboard/cases/[ref]` with:

- **12-column grid layout**: 7-col left panel, 5-col right panel
- **Left panel**: Candidate/employer card (top) + Verification results comparison table (below)
- **Right panel**: Activity & Communications vertical timeline
- **Color system**: `primary=#1E3A8A`, Inter font, `background-light=#f6f6f8`
- **Icons**: Material Symbols Outlined (`shield_person`, `fact_check`, `history`, `play_arrow`, etc.)

### Key Design Patterns

| Pattern | Design Implementation |
|---------|----------------------|
| Status indicators | Green check (match), amber warning (mismatch), badges |
| Timeline | Vertical left-border with circle dots (filled=active, outline=past) |
| Audio player | Inline in timeline entry: play button + progress bar + duration |
| Comparison layout | 2-column grid with "Claimed" vs "Verified" headers |
| Actions | Dropdown button (top-right of page header) |

---

## 2. Component Architecture

### 2.1 Page Component Tree

```
/checks-dashboard/cases/[ref]/page.tsx
├── Breadcrumb (shadcn)
├── CasePageHeader
│   ├── Title with case_reference
│   └── ActionsDropdown (shadcn DropdownMenu)
└── Grid (12-col)
    ├── Left (7-col)
    │   ├── CandidateEmployerCard (shadcn Card)
    │   └── VerificationComparisonTable (custom + shadcn Card)
    │       ├── ComparisonHeader (shadcn Badge for status)
    │       └── ComparisonRow[] (match/mismatch indicators)
    └── Right (5-col)
        └── ActivityTimeline (custom)
            ├── TimelineEvent[] (custom)
            └── CallRecordingPlayer (custom, embedded in TimelineEvent)
```

### 2.2 Component Inventory

| Component | Source | shadcn Install | Notes |
|-----------|--------|----------------|-------|
| `Breadcrumb` | shadcn | `npx shadcn@latest add breadcrumb` | Standard breadcrumb with chevron separators |
| `Card` | shadcn | `npx shadcn@latest add card` | Wraps candidate card + verification table |
| `Badge` | shadcn | `npx shadcn@latest add badge` | "Discrepancy Found", "Verified", "Mismatch" |
| `DropdownMenu` | shadcn | `npx shadcn@latest add dropdown-menu` | Actions: Flag Issue, Request Re-verification, Download Report |
| `Button` | shadcn | `npx shadcn@latest add button` | Actions button trigger |
| `Separator` | shadcn | `npx shadcn@latest add separator` | Between comparison rows |
| `Table` | shadcn | `npx shadcn@latest add table` | Alternative for verification results (TableHeader/TableBody/TableRow/TableCell) |
| `Skeleton` | shadcn | `npx shadcn@latest add skeleton` | Loading state placeholders |
| `Tooltip` | shadcn | `npx shadcn@latest add tooltip` | Timeline dot hover tooltips |
| `Sheet` | shadcn | `npx shadcn@latest add sheet` | Transcript slide-over panel |
| `AlertDialog` | shadcn | `npx shadcn@latest add alert-dialog` | Flag Issue / Re-verify confirmation |
| `Sonner` | shadcn | `npx shadcn@latest add sonner` | Toast notifications for status changes |
| `CasePageHeader` | custom | — | Title + actions layout |
| `CandidateEmployerCard` | custom | — | Avatar + candidate name + employer |
| `VerificationComparisonTable` | custom | — | Claimed vs Verified 2-col comparison |
| `ComparisonRow` | custom | — | Single field comparison with match/mismatch icon |
| `ActivityTimeline` | custom | — | Vertical timeline with left border + dots |
| `TimelineEvent` | custom | — | Single event: title, subtitle, timestamp |
| `CallRecordingPlayer` | custom | — | Inline audio: play/pause, progress bar, duration, transcript link |

---

## 3. Data Layer

### 3.1 API Client Fix (`work-history.ts`)

**Current bug** (line 368):
```typescript
// WRONG: uses task_id as case identifier
case_id: v.task_id
```

**Fix**:
```typescript
// CORRECT: use actual case_id from API response
case_id: v.case_id
```

### 3.2 New API Client Function

```typescript
// lib/api/cases.ts
export async function getCaseByReference(ref: string): Promise<CaseDetail> {
  const response = await apiClient.get(`/api/v1/cases/${ref}`);
  return response.data;
}
```

### 3.3 React Query Hook

**Research finding**: TanStack Query v5 supports `refetchInterval` as a callback — return `false` when status is terminal. Use `query.state.data` (untransformed) for status check.

```typescript
// hooks/useCaseDetail.ts
import { useQuery } from "@tanstack/react-query";
import { getCaseByReference } from "@/lib/api/cases";

const TERMINAL_STATUSES = new Set([
  "verification_complete", "verification_failed",
  "verification_aborted", "billed", "manual_resolved"
]);

export function useCaseDetail(caseRef: string) {
  return useQuery({
    queryKey: ["case", caseRef],
    queryFn: () => getCaseByReference(caseRef),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status && TERMINAL_STATUSES.has(status)) return false;
      return 10_000; // 10s polling for active cases
    },
  });
}
```

### 3.4 TypeScript Types

```typescript
// types/case.ts
export interface CaseDetail {
  case_reference: string;
  case_id: number;
  status: string;
  status_label: string;
  candidate_name: string;
  employer_name: string;
  check_type: string;
  created_at: string;
  latest_employment_status: string | null;
  sequence_progress: {
    current_step: number;
    total_steps: number;
    current_step_label: string;
  };
  timeline: TimelineEntry[];
  verification_results: VerificationResult | null;
}

export interface TimelineEntry {
  step_order: number;
  step_name: string;
  step_label: string;
  channel_type: string;
  task_id: string | null;
  result_status: string | null;
  result_label: string;
  attempted_at: string | null;
  completed_at: string | null;
  recording_url?: string | null;
  transcript_url?: string | null;
}

export interface VerificationResult {
  overall_status: "verified" | "discrepancy" | "pending";
  overall_label: string;
  fields: VerificationField[];
}

export interface VerificationField {
  field_name: string;        // "start_date", "end_date", "position", "employment_type"
  field_label: string;       // "Start Date", "End Date", etc.
  claimed_value: string | null;
  verified_value: string | null;
  match: boolean;
}
```

---

## 4. Component Specifications

### 4.1 CasePageHeader

```tsx
interface CasePageHeaderProps {
  caseReference: string;
  checkType: string;       // "Work History Verification (AI)"
  statusLabel: string;
}
```

- Layout: `flex justify-between items-start`
- Left: `<h2>` title with check type + case reference
- Right: Actions `<DropdownMenu>` with items:
  - Flag Issue (icon: `flag`)
  - Request Re-verification (icon: `refresh`)
  - Download Report (icon: `download`)

### 4.2 CandidateEmployerCard

```tsx
interface CandidateEmployerCardProps {
  candidateName: string;
  employerName: string;
}
```

- shadcn `<Card>` with `flex justify-between items-start`
- Left: person avatar (placeholder icon) + "Candidate" label + name
- Right: "Target Employer" label + business icon + name

### 4.3 VerificationComparisonTable

```tsx
interface VerificationComparisonTableProps {
  result: VerificationResult;
}
```

- shadcn `<Card>` wrapper
- Header row: `<CardHeader>` with `fact_check` icon + "Verification Results" + status Badge
- Column headers: "Candidate Claimed" | "AgenCheck Verified"
- Each `<ComparisonRow>`: field label, claimed value, verified value, match indicator
  - Match: green circle with white check icon
  - Mismatch: amber warning icon + "Mismatch" Badge (variant=`outline`, amber)
  - No data: dash character

### 4.4 ActivityTimeline

**Research finding**: shadcn/ui has no built-in timeline or stepper component. This component must be custom-built using Tailwind CSS utility classes.

**Research finding**: Recommended pattern: `<ol>` with `relative` positioning, `border-l` for connecting line, circles via `absolute` positioned `<div>` elements. Use `cn()` from shadcn for conditional styling (filled/hollow/pulsing states).

**Research finding**: Consider extracting as a reusable `<Timeline>` + `<TimelineItem>` compound component for the design system.

```tsx
interface ActivityTimelineProps {
  entries: TimelineEntry[];
  currentStep: number;
}
```

- Container: `relative pl-4 border-l-2 border-slate-100 space-y-8` using Tailwind utilities
- Each entry positioned relative with absolute dot at `-left-[21px]`
- Dot variants:
  - **Current/latest completed**: filled teal (`bg-teal-500 border-white`)
  - **Past completed**: outline (`bg-white border-slate-300`)
  - **Future pending**: dashed outline (`border-dashed border-slate-300`)
- Entry layout: title + subtitle (left), timestamp (right)
- If entry has `recording_url`: render `CallRecordingPlayer` below
- **Design system note**: Extract as reusable `<Timeline>` + `<TimelineItem>` compound component

### 4.5 CallRecordingPlayer

```tsx
interface CallRecordingPlayerProps {
  recordingUrl: string;
  transcriptUrl?: string;
  duration?: string;       // "04:05"
}
```

- Container: `bg-slate-50 border rounded-lg p-3`
- Row: play/pause button (circle) + progress bar + duration text
- Below: "View Full Transcript" link (text button with chat icon)
- Audio element: HTML5 `<audio>` with custom controls (no native browser controls)

---

## 5. Routing & Redirects

### 5.1 Route Structure

```
/checks-dashboard/cases/[ref]/page.tsx    ← new case detail page
/checks-dashboard/cases/[ref]/loading.tsx ← skeleton loader
```

### 5.2 Redirect Middleware

```typescript
// middleware.ts (or next.config.js redirects)
// Pattern: UUID-shaped path segment → look up case_reference via API → redirect
// Only applies to /checks-dashboard/cases/[segment] where segment matches UUID pattern
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-/;

if (UUID_PATTERN.test(ref)) {
  // Redirect old task_id URLs to new case_reference URLs
  // API call: GET /api/v1/verifications/{task_id} → extract case_reference
  return NextResponse.redirect(`/checks-dashboard/cases/${caseReference}`);
}
```

---

## 6. Interaction Design Specifications

### 6.1 Page Loading States

| State | Behavior |
|-------|----------|
| **Initial load** | Skeleton placeholders for each card/section (shadcn `<Skeleton>` components). Breadcrumb renders immediately (static). |
| **Data loaded** | Cards fade in with `transition-opacity duration-300`. Timeline entries stagger in with 50ms delay each. |
| **API error** | Toast notification (shadcn `<Sonner>`) with retry button. Cards show "Unable to load" inline. |
| **Case not found (404)** | Full-page empty state: "Case not found" illustration + "Back to Checks" link. |

**Skeleton layout** (matches final layout exactly):
```tsx
// loading.tsx
<div className="grid grid-cols-12 gap-6">
  <div className="col-span-7 space-y-6">
    <Skeleton className="h-24 rounded-xl" />   {/* Candidate card */}
    <Skeleton className="h-80 rounded-xl" />   {/* Verification table */}
  </div>
  <div className="col-span-5">
    <Skeleton className="h-[500px] rounded-xl" /> {/* Timeline */}
  </div>
</div>
```

### 6.2 Verification Results — Interaction States

| Element | Hover | Click | Active State |
|---------|-------|-------|-------------|
| **Matched row** | Subtle green tint (`bg-green-50/50`) | No action (v1) | — |
| **Mismatched row** | Amber tint (`bg-amber-50/50`) | Future: expand to show AI explanation | Highlighted border-left amber |
| **Overall status badge** | Slight scale (`scale-105`) | No action | Pulses gently when `status !== terminal` (CSS `animate-pulse` at reduced opacity) |
| **"Mismatch" pill** | — | — | Static indicator, always visible on discrepancy rows |

**Mismatch row hover detail**:
```css
.comparison-row[data-match="false"]:hover {
  background-color: rgb(255 251 235 / 0.5); /* bg-amber-50/50 */
  transition: background-color 150ms ease;
}
```

### 6.3 Activity Timeline — Interaction States

#### Dot States (Timeline Markers)

| State | Dot Style | Connector Style |
|-------|-----------|-----------------|
| **Completed (latest)** | `bg-teal-500 border-2 border-white shadow-sm` (filled, 14px) | Solid `border-l-2 border-slate-100` |
| **Completed (older)** | `bg-white border-2 border-slate-300` (outline, 14px) | Solid line |
| **In Progress** | `bg-teal-500 border-2 border-white animate-pulse` (filled + pulse) | Solid line |
| **Pending (future)** | `bg-white border-2 border-dashed border-slate-300 opacity-50` (dashed, 14px) | Dashed line segment |

#### Timeline Event Interactions

| Interaction | Behavior |
|-------------|----------|
| **Hover on event** | Entire event row gets `bg-slate-50/50` background. Timestamp text darkens from `text-slate-400` → `text-slate-600`. |
| **Hover on dot** | Tooltip appears with: step label, result label, timestamp. Tooltip uses shadcn `<Tooltip>` with 200ms delay. |
| **New event arrives (polling)** | New entry slides down from top of position with `animate-slideDown` (translateY -8px → 0, opacity 0 → 1, 300ms). Brief green flash (`ring-2 ring-green-400/30`) then fades. |
| **Click on completed event** | Future: expand to show full details (call summary, duration, etc.). V1: no click action. |

#### Auto-Scroll Behavior

On page load, the timeline container scrolls to bring the current/latest step into view:
```tsx
useEffect(() => {
  const currentStep = timelineRef.current?.querySelector('[data-current="true"]');
  currentStep?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}, [timeline]);
```

### 6.4 Call Recording Player — Interaction Design

| Element | Interaction | Behavior |
|---------|-------------|----------|
| **Play button** | Click | Toggles play/pause. Icon transitions: `play_arrow` ↔ `pause` with 150ms fade. Button has `hover:bg-slate-100` ring. |
| **Progress bar** | Click | Seeks to clicked position. Bar fills from left (`bg-teal-400`). |
| **Progress bar** | Drag | Scrubber knob (`w-3 h-3 bg-white border border-teal-400 rounded-full shadow-sm`) follows cursor. Audio seeks in real-time. |
| **Duration text** | — | Shows `{elapsed} / {total}` (e.g., "01:23 / 04:05"). Updates every second during playback. |
| **"View Full Transcript"** | Click | Opens slide-over panel (shadcn `<Sheet>` from right) with timestamped transcript lines. Each line clickable to seek audio to that timestamp. |

**Player container**:
```css
.recording-player {
  @apply bg-slate-50 border border-slate-200 rounded-lg p-3 mt-3 shadow-sm;
}
```

**Audio state management** (React ref-based):
```tsx
const audioRef = useRef<HTMLAudioElement>(null);
const [isPlaying, setIsPlaying] = useState(false);
const [progress, setProgress] = useState(0);

// Play/pause toggle
const togglePlay = () => {
  if (audioRef.current?.paused) {
    audioRef.current.play();
  } else {
    audioRef.current?.pause();
  }
};

// Progress tracking
useEffect(() => {
  const audio = audioRef.current;
  if (!audio) return;
  const onTimeUpdate = () => setProgress(audio.currentTime / audio.duration);
  const onPlay = () => setIsPlaying(true);
  const onPause = () => setIsPlaying(false);
  audio.addEventListener('timeupdate', onTimeUpdate);
  audio.addEventListener('play', onPlay);
  audio.addEventListener('pause', onPause);
  return () => {
    audio.removeEventListener('timeupdate', onTimeUpdate);
    audio.removeEventListener('play', onPlay);
    audio.removeEventListener('pause', onPause);
  };
}, []);
```

### 6.5 Actions Dropdown — Interaction Flows

| Action | Click Behavior | Confirmation | API Call |
|--------|---------------|--------------|----------|
| **Flag Issue** | Opens `<Dialog>` with textarea for notes + "Flag" button | Required: user must enter notes | `POST /api/v1/cases/{ref}/flags` |
| **Request Re-verification** | Opens `<Dialog>` with reason radio group (Data Error, New Information, Other) + notes | Required: reason selection | `POST /api/v1/cases/{ref}/reverify` |
| **Download Report** | Immediate: triggers PDF download | None | `GET /api/v1/cases/{ref}/report` (returns PDF blob) |

**Dialog pattern** (shadcn `<AlertDialog>`):
```tsx
<AlertDialog>
  <AlertDialogTrigger asChild>
    <DropdownMenuItem onSelect={(e) => e.preventDefault()}>
      Flag Issue
    </DropdownMenuItem>
  </AlertDialogTrigger>
  <AlertDialogContent>
    <AlertDialogHeader>
      <AlertDialogTitle>Flag Issue</AlertDialogTitle>
      <AlertDialogDescription>
        Describe the issue with this verification case.
      </AlertDialogDescription>
    </AlertDialogHeader>
    <Textarea placeholder="Describe the issue..." />
    <AlertDialogFooter>
      <AlertDialogCancel>Cancel</AlertDialogCancel>
      <AlertDialogAction>Submit Flag</AlertDialogAction>
    </AlertDialogFooter>
  </AlertDialogContent>
</AlertDialog>
```

### 6.6 Polling & Real-Time Update Behavior

| Scenario | Behavior |
|----------|----------|
| **Active case** | `refetchInterval: 10_000` (10s). Each refetch silently updates React Query cache. |
| **Terminal case** | `refetchInterval: false`. Page becomes static. Badge stops pulsing. |
| **New timeline event detected** | Diff previous vs current `timeline.length`. New entries get `data-new="true"` attribute → green flash animation (ring-2 ring-green-400/30, 1s fade). |
| **Status change** | Status badge text updates. If terminal, badge transitions from `animate-pulse` to static. Toast: "Case status updated to {label}". |
| **Sequence progress change** | Progress text ("Step 2 of 3") updates inline. No animation needed. |
| **Network error during poll** | Silent retry (React Query default). After 3 failures, show subtle inline warning: "Updates paused — retrying..." |

### 6.7 Keyboard Accessibility

| Key | Context | Action |
|-----|---------|--------|
| `Space/Enter` | Audio player play button focused | Toggle play/pause |
| `ArrowLeft/Right` | Audio player focused | Seek ±5 seconds |
| `Escape` | Transcript sheet open | Close sheet |
| `Tab` | Page-level | Navigate: breadcrumb → header → actions → candidate card → verification rows → timeline events → audio player |

### 6.8 Empty & Edge States

| State | UI |
|-------|-----|
| **No verification results yet** | Verification card shows "Verification results will appear here once the check is complete" with a clock icon |
| **No timeline events** | Timeline shows single "Case Created" entry with creation timestamp |
| **No recording available** | Timeline event renders without audio player section |
| **Case has 1 step only** | Timeline shows single step, no future pending steps |
| **All steps exhausted, non-terminal** | Final step shows amber "Max Retries Exceeded" badge, timeline complete |

---

## 7. Responsive Behavior (Detail)

| Breakpoint | Layout |
|------------|--------|
| `lg` (1024px+) | 12-col grid: 7-col left + 5-col right |
| `md` (768px) | Single column: candidate → verification → timeline stacked |
| `sm` (640px) | Full-width cards, timeline dots shift to smaller size |

---

## 8. Terminology Alignment

All customer-facing text must use v3.3 terminology:

| Forbidden | Use Instead |
|-----------|-------------|
| "task" | "check" or "verification" |
| "background_task" | "verification step" |
| "unreachable" | "Unable to Verify" |
| "task_id" | hidden from UI (debug-only collapsible) |

Status labels come exclusively from the backend `status_label` field — no frontend enum mapping.

---

## 9. Implementation Order

| Step | Component | Depends On |
|------|-----------|------------|
| 1 | TypeScript types (`types/case.ts`) | API contract (SD-DASHBOARD-AUDIT-001 §7) |
| 2 | API client fix (`work-history.ts:368`) | — |
| 3 | New API client (`lib/api/cases.ts`) | Backend endpoint |
| 4 | React Query hook (`hooks/useCaseDetail.ts`) | Step 3 |
| 5 | `CandidateEmployerCard` | shadcn Card |
| 6 | `ComparisonRow` + `VerificationComparisonTable` | shadcn Card, Badge |
| 7 | `TimelineEvent` + `CallRecordingPlayer` | — |
| 8 | `ActivityTimeline` | Step 7 |
| 9 | `CasePageHeader` | shadcn DropdownMenu, Breadcrumb |
| 10 | Page assembly (`page.tsx`) | Steps 4-9 |
| 11 | Redirect middleware | Step 10 |
| 12 | Checks list table updates | Backend `case_reference` field |

---

## 10. Testing Strategy

### Unit Tests
- `VerificationComparisonTable`: renders match/mismatch correctly for all field types
- `ActivityTimeline`: renders completed, current, and pending entries with correct dot styles
- `CallRecordingPlayer`: play/pause toggle, progress bar interaction
- `useCaseDetail`: stops polling when status is terminal

### Integration Tests
- Navigate to `/checks-dashboard/cases/AC-202603-00042` → renders full page
- Old UUID URL redirects to case_reference URL
- Actions dropdown items trigger correct API calls

### Visual Regression
- Snapshot tests for CandidateEmployerCard, VerificationComparisonTable, ActivityTimeline at `lg` and `md` breakpoints

---

## 11. Research Findings & Technical Notes

### Frontend Research Findings (from SD-DASHBOARD-AUDIT-001)

**1. Timeline Component Architecture**
- **Finding**: shadcn/ui has no built-in timeline or stepper component
- **Solution**: Custom Tailwind CSS implementation required using `<ol>` with `relative` positioning, `border-l` for connecting line, and absolute-positioned circles
- **Implementation**: Use `cn()` utility for conditional styling (filled/hollow/pulsing states)

**2. React Query v5 Polling Behavior**
- **Finding**: TanStack Query v5 supports `refetchInterval` as a callback function
- **Solution**: Return `false` when status is terminal to stop polling automatically
- **Implementation**: Use `query.state.data` for status checks to access untransformed data

**3. Component Reusability Pattern**
- **Finding**: Consider extracting timeline as reusable `<Timeline>` + `<TimelineItem>` compound component
- **Solution**: Design with potential extraction in mind for broader design system usage

**4. Frontend Terminology Alignment**
- **Finding**: All customer-facing text must use backend-provided labels
- **Solution**: Consume only `status_label` strings from backend; no frontend enum mapping
- **Validation**: CI gate ensures frontend labels match backend-generated constants

**5. Status Label Handling**
- **Finding**: No occurrence of legacy "unreachable" in frontend; use "Unable to Verify" instead
- **Solution**: Import from CI-generated `statusLabels.ts` constants rather than hardcoding

---
