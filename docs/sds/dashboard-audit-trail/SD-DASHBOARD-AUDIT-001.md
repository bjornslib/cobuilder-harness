---
title: "SD-DASHBOARD-AUDIT-001: Dashboard Audit Trail & Stable References"
status: draft
type: reference
grade: authoritative
last_verified: 2026-03-09
---

# SD-DASHBOARD-AUDIT-001: Dashboard Audit Trail & Stable References

**PRD**: PRD-DASHBOARD-AUDIT-001
**Version**: 0.4.0 (Corrected stable reference framing + research findings)
**Date**: 2026-03-09

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js / React)                                     │
│  - Updated API client (work-history.ts)                         │
│  - New CaseTimeline vertical timeline component                 │
│  - Updated RequestsTable with case_reference + progress         │
│  - StatusLabel component consuming backend-only labels          │
│  - CI-generated statusLabels.ts from backend mapping            │
├─────────────────────────────────────────────────────────────────┤
│  Backend API (FastAPI)                                           │
│  - New GET /api/v1/cases/{case_reference} (timeline + future)   │
│  - Updated GET /api/v1/verifications (+ case_reference, progress│
│  - StatusLabelMapper (single source of truth)                   │
│  - scripts/export_status_labels.py (CI generator)               │
├─────────────────────────────────────────────────────────────────┤
│  Database (PostgreSQL)                                           │
│  - cases.case_reference (TEXT, UNIQUE NOT NULL) + PG sequence   │
│  - background_tasks.sequence_step_order (INTEGER)               │
│  - cases.latest_employment_status (TEXT)                        │
│  - Backfill migration for existing cases                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Database Changes

### 2.1 Migration: Add case_reference (Display Alias) to `cases` Table

**File**: `database/migrations/0XX_add_case_reference.sql`

**Context**: `cases.id` (integer PK) is already the stable identity — `background_tasks.case_id` FK links all retries to the same case. This migration adds a **human-readable display alias** (`case_reference`) for customer-facing URLs and communication. The stable FK relationship is unchanged.

**Design decision** (5/7 architects): Stored column with PostgreSQL sequence. PG sequences are atomic across connections — `nextval()` is non-transactional, gaps on rollback are acceptable and cosmetic. No TOCTOU race condition.

```sql
-- Migration 0XX: Add stable case_reference to cases table
-- PRD: PRD-DASHBOARD-AUDIT-001 (Epic A)

BEGIN;

-- Step 1: Create global monotonic sequence
CREATE SEQUENCE cases_reference_seq START 1;

-- Step 2: Add nullable column
ALTER TABLE cases ADD COLUMN case_reference TEXT;

-- Step 3: Backfill existing cases
-- Uses global counter (NOT per-month reset) to avoid search ambiguity
-- YYYYMM is cosmetic, derived from created_at
UPDATE cases
SET case_reference = 'AC-' || to_char(created_at, 'YYYYMM') || '-'
    || LPAD(nextval('cases_reference_seq')::text, 5, '0')
WHERE case_reference IS NULL;

-- Step 4: Make NOT NULL and UNIQUE
ALTER TABLE cases ALTER COLUMN case_reference SET NOT NULL;
ALTER TABLE cases ADD CONSTRAINT uq_cases_case_reference UNIQUE (case_reference);

-- Step 5: Index for fast lookups
CREATE INDEX idx_cases_case_reference ON cases(case_reference);

COMMIT;
```

### 2.2 ~~Migration: Add sequence_step_order~~ — NOT NEEDED

**Live data finding**: `background_tasks` already has `current_sequence_step` (INTEGER, 1-indexed) and `sequence_id` (FK to `background_check_sequence.id`), both added in migrations 035/037. No new column needed.

**Current state of live data**:
- `current_sequence_step` = 1 for all tasks (no retries triggered yet)
- `sequence_id` populated only since ~March 1 (migration 037); older tasks = NULL
- `sequence_version` denormalized on tasks — captures version at task creation time

**Backfill for older tasks** (pre-037, NULL sequence_id): Resolve via `check_type_config_id` → `check_types.id` → active sequence lookup.

### 2.3 Migration: Add latest_employment_status to cases

**Design decision**: Denormalize for list performance. Case-list endpoint reads only from `cases` — no joins for paginated table view.

```sql
BEGIN;

ALTER TABLE cases ADD COLUMN latest_employment_status TEXT;

-- Backfill from most recent completed task per case
UPDATE cases c
SET latest_employment_status = sub.employment_status
FROM (
    SELECT DISTINCT ON (case_id) case_id, result_status AS employment_status
    FROM background_tasks
    WHERE result_status IS NOT NULL
    ORDER BY case_id, created_at DESC
) sub
WHERE c.id = sub.case_id;

COMMIT;
```

### 2.4 Application-Level Reference Generation

In `helpers/work_history_case.py`:

```python
async def create_work_history_case(self, ...):
    # Generate stable case reference using PG sequence
    month_key = datetime.now(timezone.utc).strftime('%Y%m')
    seq = await self.pool.fetchval("SELECT nextval('cases_reference_seq')")
    case_ref = f"AC-{month_key}-{seq:05d}"

    query = """
        INSERT INTO cases (case_type, status, case_reference, ...)
        VALUES ('work_history', 'pending', $1, ...)
        RETURNING id, case_reference, ...
    """
    row = await conn.fetchrow(query, case_ref, ...)
    return row['id'], row
```

**Note**: No PG function needed — application generates reference directly from `nextval()`. Simpler than the v0.1.0 `next_case_reference()` function approach.

**Research validation (PG sequences)**:
- `nextval()` is safe under high concurrency — it is non-transactional and never blocks on row locks. Each call atomically increments regardless of transaction isolation level.
- Gaps are expected and harmless (rollback, crash, or unused `nextval()` calls). Reference uniqueness is guaranteed; monotonicity is not.
- Global sequence (not per-month) is correct — avoids the ambiguity of resetting counters and the race condition of MAX+1 patterns.
- The `AC-YYYYMM-NNNNN` format uses YYYYMM as cosmetic context only; the 5-digit global counter is the true identifier.

---

## 3. Backend API Changes

### 3.1 New Endpoint: GET /api/v1/cases/{case_reference}

**File**: `api/routers/work_history.py`

**Key innovation** (Architect 4): The API synthesizes future steps by LEFT JOINing `background_check_sequence_steps` with actual tasks, filling gaps with `{status: "pending", task_id: null}`.

```python
@router.get("/api/v1/cases/{case_reference}")
async def get_case_by_reference(
    case_reference: str,
    user: AuthenticatedUser = Depends(require_api_key),
    db: WorkHistoryDBService = Depends(get_db_service),
):
    """
    Get full case details by stable case reference.
    Returns case overview + full timeline (completed + future steps).
    """
    case = await db.get_case_by_reference(case_reference, user.customer_id)
    if not case:
        raise HTTPException(404, f"Case {case_reference} not found")

    timeline = await db.get_case_timeline(case['id'], case.get('check_type_id'))

    return {
        "case_reference": case['case_reference'],
        "case_id": case['id'],
        "status": case['status'],
        "status_label": StatusLabelMapper.case_status(case['status']),
        "candidate_name": f"{case.get('candidate_first_name', '')} {case.get('candidate_last_name', '')}".strip(),
        "employer_name": case.get('employer_name'),
        "check_type": case.get('case_type'),
        "created_at": case['created_at'].isoformat(),
        "latest_employment_status": case.get('latest_employment_status'),
        "sequence_progress": timeline['progress'],
        "timeline": timeline['entries'],
        "verification_results": case.get('verification_results'),
    }
```

### 3.2 Timeline Query (Completed Tasks + Synthesized Future Steps)

**Live data context**: The actual sequence table is `background_check_sequence` (not `background_check_sequence_steps`). Tasks link to it via `sequence_id` FK and `current_sequence_step`. The 3-tier resolution chain (client → customer → system) determines which sequence applies. Current live work_history sequence (v5) has 3 steps: Voice Call Attempt → Email Outreach → Manual Review Escalation.

```python
async def get_case_timeline(self, case_id: int) -> dict:
    """
    Build full timeline: completed tasks + pending future steps.

    Algorithm:
    1. Get all tasks for this case
    2. Resolve the active sequence (3-tier: client → customer → system)
    3. LEFT JOIN tasks onto sequence steps by current_sequence_step = step_order
    4. Synthesize future steps where no task exists yet
    """
    # Step 1: Get case + its tasks
    case = await self.pool.fetchrow(
        "SELECT id, customer_id, client_id, case_type FROM cases WHERE id = $1", case_id
    )
    tasks = await self.pool.fetch("""
        SELECT task_id, status, result_status, current_sequence_step,
               sequence_id, sequence_version, check_type_config_id,
               created_at AS attempted_at, updated_at AS completed_at
        FROM background_tasks
        WHERE case_id = $1 AND action_type = 'call_attempt'
        ORDER BY created_at ASC
    """, case_id)

    # Step 2: Resolve the active sequence via 3-tier resolution
    # Determine check_type_id from the first task's check_type_config_id
    check_type_id = tasks[0]['check_type_config_id'] if tasks else 1
    customer_id = case['customer_id'] or 1
    client_id = case['client_id']

    sequence_steps = await self._resolve_sequence(check_type_id, customer_id, client_id)

    # Step 3: Build timeline by matching tasks to sequence steps
    # Index tasks by their current_sequence_step
    task_by_step = {}
    for t in tasks:
        step = t['current_sequence_step'] or 1
        task_by_step[step] = t

    entries = []
    current_step = 0
    for step in sequence_steps:
        task = task_by_step.get(step['step_order'])
        has_task = task is not None
        if has_task:
            current_step = step['step_order']
        entries.append({
            "step_order": step['step_order'],
            "step_name": step['step_name'],
            "step_label": StatusLabelMapper.step_name(step['step_name']),
            "channel_type": step['channel_type'],
            "delay_hours": float(step['delay_hours']),
            "max_attempts": step['max_attempts'],
            "task_id": str(task['task_id']) if has_task else None,
            "result_status": task['result_status'] if has_task else None,
            "result_label": StatusLabelMapper.result_status(task['result_status']) if has_task else "Pending",
            "task_status": task['status'] if has_task else None,
            "attempted_at": task['attempted_at'].isoformat() if has_task and task.get('attempted_at') else None,
            "completed_at": task['completed_at'].isoformat() if has_task and task.get('completed_at') else None,
            "sequence_version": task['sequence_version'] if has_task else None,
        })

    total_steps = len(entries)
    current_entry = next((e for e in entries if e['step_order'] == current_step), None)

    return {
        "progress": {
            "current_step": current_step,
            "total_steps": total_steps,
            "current_step_label": current_entry['step_label'] if current_entry else "Pending",
        },
        "entries": entries,
    }

async def _resolve_sequence(self, check_type_id: int, customer_id: int, client_id: int = None) -> list:
    """
    3-tier SLA resolution: client-specific → customer default → system fallback.
    Returns ordered list of active sequence steps.
    """
    # Tier 1: Client-specific
    if client_id:
        rows = await self.pool.fetch("""
            SELECT step_order, step_name, channel_type, delay_hours, max_attempts
            FROM background_check_sequence
            WHERE check_type_id = $1 AND customer_id = $2 AND client_id = $3
              AND status = 'active' AND is_active = true
            ORDER BY step_order
        """, check_type_id, customer_id, client_id)
        if rows:
            return [dict(r) for r in rows]

    # Tier 2: Customer default (client_id IS NULL)
    rows = await self.pool.fetch("""
        SELECT step_order, step_name, channel_type, delay_hours, max_attempts
        FROM background_check_sequence
        WHERE check_type_id = $1 AND customer_id = $2 AND client_id IS NULL
          AND status = 'active' AND is_active = true
        ORDER BY step_order
    """, check_type_id, customer_id)
    if rows:
        return [dict(r) for r in rows]

    # Tier 3: System fallback (customer_id=1)
    rows = await self.pool.fetch("""
        SELECT step_order, step_name, channel_type, delay_hours, max_attempts
        FROM background_check_sequence
        WHERE check_type_id = $1 AND customer_id = 1 AND client_id IS NULL
          AND status = 'active' AND is_active = true
        ORDER BY step_order
    """, check_type_id)
    return [dict(r) for r in rows]
```

**Version mismatch detection**: If a task's `sequence_version` differs from the current active sequence version, the timeline should display a warning icon. This means the sequence was updated after the task was created — the remaining steps may not match what the task was originally assigned.

### 3.3 Update list_verifications Response

Add `case_reference` and `sequence_progress` to the existing list endpoint:

```python
# In list_verifications handler, add to each item:
"case_reference": row['case_reference'],
"sequence_progress": f"{row.get('current_step', 0)}/{row.get('total_steps', 0)}",
"latest_employment_status": row.get('latest_employment_status'),
"status_label": StatusLabelMapper.case_status(row['status']),
```

### 3.4 StatusLabelMapper (Backend Single Source of Truth)

**File**: `utils/status_labels.py` (NEW)

**Design decision** (3/7 explicit, all compatible): Backend-only mapping. Frontend receives only `status_label` strings — never maps raw enums. CI script generates `generated/statusLabels.ts` and fails build if stale.

```python
"""
Canonical status label mapping for customer-facing display.

Single source of truth — frontend receives pre-mapped labels.
CI: scripts/export_status_labels.py generates generated/statusLabels.ts

Aligns with:
- Epic 7 CallResultStatus enum (14 values)
- WORK HISTORY VERIFICATION FLOW v3.3 employment_status (5 values)
- Epic F.6 Terminology Guide
"""
from typing import Optional


class StatusLabelMapper:
    """Maps internal status values to customer-facing labels."""

    # CallResultStatus → Customer Label
    _RESULT_STATUS_MAP: dict[str, tuple[str, str, bool]] = {
        # key: (label, variant, is_terminal)
        "completed": ("Verified", "success", True),
        "completed_discrepancies": ("Partial Verification", "warning", True),
        "refused": ("Refused", "error", True),
        "unable_to_verify": ("Unable to Verify", "neutral", True),
        "wrong_number": ("Wrong Number", "error", True),
        "max_retries_exceeded": ("Max Retries Exceeded", "error", True),
        "voicemail_left": ("Voicemail Left", "info", False),
        "no_answer": ("No Answer", "info", False),
        "busy": ("Busy", "info", False),
        "callback_requested": ("Callback Requested", "info", False),
        "manual_review": ("Under Review", "warning", False),
        "invalid_contact": ("Invalid Contact", "error", True),
        "aborted": ("Aborted", "neutral", True),
        "call_scheduled": ("Scheduled", "info", False),
        "in_progress": ("In Progress", "info", False),
    }

    # Case Status → Customer Label
    _CASE_STATUS_MAP: dict[str, tuple[str, str]] = {
        "pending": ("Pending", "neutral"),
        "in_progress": ("In Progress", "info"),
        "verification_complete": ("Verified", "success"),
        "requires_review": ("Under Review", "warning"),
        "awaiting_callback": ("Awaiting Callback", "info"),
        "verification_failed": ("Failed", "error"),
        "verification_aborted": ("Aborted", "neutral"),
        "billed": ("Complete", "success"),
        "manual_resolved": ("Resolved", "success"),
    }

    # Step Name → Customer Label
    _STEP_NAME_MAP: dict[str, str] = {
        "initial_call": "Initial Call",
        "first_retry": "First Retry",
        "second_retry": "Second Retry",
        "third_retry": "Third Retry",
        "final_attempt": "Final Attempt",
        "email_outreach": "Email Outreach",
        "human_review": "Human Review",
    }

    @classmethod
    def result_status(cls, status: Optional[str]) -> str:
        if status is None:
            return "In Progress"
        entry = cls._RESULT_STATUS_MAP.get(status)
        return entry[0] if entry else status.replace("_", " ").title()

    @classmethod
    def result_variant(cls, status: Optional[str]) -> str:
        if status is None:
            return "info"
        entry = cls._RESULT_STATUS_MAP.get(status)
        return entry[1] if entry else "neutral"

    @classmethod
    def is_terminal(cls, status: Optional[str]) -> bool:
        if status is None:
            return False
        entry = cls._RESULT_STATUS_MAP.get(status)
        return entry[2] if entry else False

    @classmethod
    def case_status(cls, status: Optional[str]) -> str:
        if status is None:
            return "Pending"
        entry = cls._CASE_STATUS_MAP.get(status)
        return entry[0] if entry else status.replace("_", " ").title()

    @classmethod
    def case_variant(cls, status: Optional[str]) -> str:
        if status is None:
            return "neutral"
        entry = cls._CASE_STATUS_MAP.get(status)
        return entry[1] if entry else "neutral"

    @classmethod
    def step_name(cls, name: Optional[str]) -> str:
        if name is None:
            return "Pending"
        return cls._STEP_NAME_MAP.get(name, name.replace("_", " ").title())

    @classmethod
    def export_for_frontend(cls) -> dict:
        """Export all mappings for CI-generated TypeScript constants."""
        return {
            "resultStatusLabels": {k: v[0] for k, v in cls._RESULT_STATUS_MAP.items()},
            "resultStatusVariants": {k: v[1] for k, v in cls._RESULT_STATUS_MAP.items()},
            "caseStatusLabels": {k: v[0] for k, v in cls._CASE_STATUS_MAP.items()},
            "caseStatusVariants": {k: v[1] for k, v in cls._CASE_STATUS_MAP.items()},
            "stepNameLabels": cls._STEP_NAME_MAP.copy(),
        }
```

### 3.5 CI Script: Export Status Labels

**File**: `scripts/export_status_labels.py` (NEW)

```python
#!/usr/bin/env python3
"""Generate frontend TypeScript constants from StatusLabelMapper.

Run: python scripts/export_status_labels.py
CI gate: fail build if generated/statusLabels.ts is stale.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.status_labels import StatusLabelMapper

OUTPUT = Path(__file__).parent.parent.parent / "agencheck-support-frontend" / "generated" / "statusLabels.ts"

def main():
    data = StatusLabelMapper.export_for_frontend()
    lines = [
        "// AUTO-GENERATED — do not edit manually",
        "// Source: utils/status_labels.py → scripts/export_status_labels.py",
        "",
        f"export const resultStatusLabels = {json.dumps(data['resultStatusLabels'], indent=2)} as const;",
        "",
        f"export const resultStatusVariants = {json.dumps(data['resultStatusVariants'], indent=2)} as const;",
        "",
        f"export const caseStatusLabels = {json.dumps(data['caseStatusLabels'], indent=2)} as const;",
        "",
        f"export const caseStatusVariants = {json.dumps(data['caseStatusVariants'], indent=2)} as const;",
        "",
        f"export const stepNameLabels = {json.dumps(data['stepNameLabels'], indent=2)} as const;",
        "",
        "export type ResultStatus = keyof typeof resultStatusLabels;",
        "export type CaseStatus = keyof typeof caseStatusLabels;",
        "export type StepName = keyof typeof stepNameLabels;",
        "",
    ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines))
    print(f"Generated {OUTPUT}")

if __name__ == "__main__":
    main()
```

### 3.6 Permanent Endpoint: GET /api/v1/verifications/{task_id}

**Explicit guarantee** (PRD G1): This endpoint is **never deprecated**. Existing integrations using task_id continue to work indefinitely. The response is augmented with `case_reference` for migration convenience.

---

## 4. Frontend Changes

### 4.1 Updated API Client

**File**: `lib/api/work-history.ts`

Key changes:
- **Fix root cause**: Remove `case_id: v.task_id` mapping (line ~368) — use `case_reference` from API response
- New: `getCaseByReference(ref: string)` calling `GET /api/v1/cases/{ref}`
- `getVerifications()` items now include `case_reference`, `sequence_progress`, `status_label`
- `getVerificationById()` kept for backward compat
- React Query cache keys use `case_reference` (not task_id)
- `refetchInterval` uses TanStack Query v5 callback pattern to stop polling when terminal:
  ```tsx
  refetchInterval: (query) => isTerminalStatus(query.state.data?.status) ? false : 5000
  ```

### 4.2 StatusLabel Component

**File**: `components/ui/StatusLabel.tsx` (NEW)

Renders colored badges from backend-provided `status_label` + `variant` strings. **Does NOT map raw enums** — consumes only pre-mapped labels. Uses the CI-generated `statusLabels.ts` for TypeScript types only (not for label computation).

### 4.3 CaseTimeline Component (Vertical Timeline)

**File**: `components/work-history/CaseTimeline.tsx` (NEW)

**Design decision** (unanimous): Vertical timeline, not ordered stepper. Shows completed tasks + synthesized future pending steps.

```
  ● Initial Call          — Voicemail Left      2026-03-01 10:05
  │
  ● First Retry           — No Answer           2026-03-01 14:00
  │
  ◉ Second Retry          — In Progress         2026-03-02 09:00  ← current
  ┆
  ○ Third Retry           — Pending
  ┆
  ○ Final Attempt         — Pending
```

- **Completed steps**: Solid filled circle (●) with result_label and timestamp
- **Current step**: Highlighted/pulsing circle (◉) with "In Progress" label
- **Future steps**: Hollow circle (○) with "Pending" label
- **Connecting lines**: Solid (│) for completed, dashed (┆) for future
- **Channel type icon**: Phone/email icon per step
- **Collapsible debug section**: Shows task_id UUIDs (not visible by default)

**Research validation (frontend timeline)**:
- shadcn/ui has no built-in timeline or stepper component — CaseTimeline must be custom-built using Tailwind CSS utility classes
- Recommended pattern: `<ol>` with `relative` positioning, `border-l` for connecting line, circles via `absolute` positioned `<div>` elements
- Use `cn()` from shadcn for conditional styling (filled/hollow/pulsing states)
- Consider extracting as a reusable `<Timeline>` + `<TimelineItem>` compound component for the design system

### 4.4 Updated RequestsTable

**File**: `components/work-history/RequestsTable.tsx`

| Column (before) | Column (after) | Source |
|-----------------|----------------|--------|
| `case_id` (was task_id) | `case_reference` (e.g., AC-202603-00042) | API `case_reference` |
| Status (raw enum) | Status (StatusLabel component) | API `status_label` + `variant` |
| _(new)_ | Progress (e.g., "3/5") | API `sequence_progress` |

Row click navigates to `/checks-dashboard/cases/{case_reference}`.

### 4.5 Updated Case Detail Page

**File**: `app/checks-dashboard/cases/[ref]/page.tsx` (NEW — replaces `[id]`)

- URL param: `[ref]` (case_reference, e.g., `AC-202603-00042`)
- Fetches via `getCaseByReference(ref)`
- Layout: CaseTimeline at top → task history below → verification results section
- Add redirect: `/checks-dashboard/cases/[old-task-id-uuid]` → `/cases/{case_reference}` (detect UUID format)

### 4.6 Terminology Cleanup

- Remove all occurrences of `"unreachable"` → use `"Unable to Verify"` (from generated constants)
- Replace customer-facing word `"task"` with `"check"` or `"verification"` across all UI components
- CI gate: frontend build fails if `generated/statusLabels.ts` is stale vs backend

---

## 5. Migration Strategy

### Phase 1: Backend (non-breaking)
1. Run 3 database migrations (case_reference, sequence_step_order, latest_employment_status)
2. Deploy backend with new `/cases/{case_reference}` endpoint
3. Augment existing `/verifications` response with `case_reference` and `sequence_progress`
4. Old endpoints continue working — zero downtime

### Phase 2: Frontend
1. Generate `statusLabels.ts` via CI script
2. Update API client: consume `case_reference`, add `getCaseByReference()`
3. Deploy updated dashboard pages (CaseTimeline, RequestsTable, case detail)
4. Add UUID→case_reference redirect for bookmarks

### Phase 3: Cleanup (30 days post-deploy)
1. Log warnings on task_id-based navigation
2. Update external integrations to use case_reference
3. Remove legacy UUID redirects

---

## 6. Research Findings & Resolved Questions

### Resolved by Research Pipeline

1. **PG sequence safety** ✅: `nextval()` is atomic, non-transactional, safe under high concurrency. Gaps are expected and harmless. Global sequence confirmed as correct approach.
2. **Frontend component library** ✅: shadcn/ui has no timeline/stepper component. Custom Tailwind vertical timeline is the correct approach. Extract as `<Timeline>` + `<TimelineItem>` compound component.
3. **React Query polling** ✅: TanStack Query v5 supports `refetchInterval` as a callback — return `false` when status is terminal. Use `query.state.data` (untransformed) for status check.
4. **Denormalized step_order** ✅: Setting at Prefect flow task-creation time is the correct pattern (matches Stripe's attempt_count on PaymentIntent). Backfill from `created_at` ordering is a reasonable approximation for existing data.

### Remaining Open Questions

1. **Prefect flow visibility**: Should we expose Prefect flow run IDs in the timeline? (Deferred — out of MVP scope, would add API latency)
2. **Search by case_reference**: Should the dashboard have a search/filter field? (Deferred — add in v2 if customers request it)
3. **Backfill edge cases**: Are there cases where tasks were created out of chronological order? (Low risk — backfill uses `created_at ASC` which matches the expected execution order)

---

## 7. Files to Create/Modify

### Backend (agencheck-support-agent)

| File | Action | Epic |
|------|--------|------|
| `database/migrations/0XX_add_case_reference.sql` | CREATE | A |
| `database/migrations/0XY_add_step_order.sql` | CREATE | A |
| `database/migrations/0XZ_add_latest_status.sql` | CREATE | A |
| `helpers/work_history_case.py` | MODIFY — PG sequence case_reference generation | A |
| `api/routers/work_history.py` | MODIFY — new endpoint, update list response | A |
| `utils/status_labels.py` | CREATE — StatusLabelMapper | C |
| `scripts/export_status_labels.py` | CREATE — CI generator | C |

### Frontend (agencheck-support-frontend)

| File | Action | Epic |
|------|--------|------|
| `generated/statusLabels.ts` | CREATE (auto-generated) | C |
| `lib/api/work-history.ts` | MODIFY — fix case_id mapping, add getCaseByReference | B |
| `components/ui/StatusLabel.tsx` | CREATE | C |
| `components/work-history/CaseTimeline.tsx` | CREATE | B |
| `components/work-history/RequestsTable.tsx` | MODIFY — case_reference, progress col | B |
| `components/work-history/RecentRequestsTable.tsx` | MODIFY — case_reference | B |
| `app/checks-dashboard/cases/[ref]/page.tsx` | CREATE (replace [id]) | B |
| `app/checks-dashboard/requests/page.tsx` | MODIFY — column updates | B |
| `app/checks-dashboard/page.tsx` | MODIFY — summary cards | B |
| `hooks/useVerifications.ts` | MODIFY — add useCaseByReference, terminal-aware polling | B |
