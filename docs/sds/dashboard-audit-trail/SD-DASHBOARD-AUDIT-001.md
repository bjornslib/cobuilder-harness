---
title: "SD-DASHBOARD-AUDIT-001: Dashboard Audit Trail & Stable References"
status: draft
type: reference
grade: authoritative
last_verified: 2026-03-11T00:00:00.000Z
---
# SD-DASHBOARD-AUDIT-001: Dashboard Audit Trail & Stable References

**PRD**: PRD-DASHBOARD-AUDIT-001
**Date**: 2026-03-11
**Validated by**: 2026-03-11 - `research_backend_sd.md`, `research_perstep.md`, `research_gaps.md`

---

## Validated Constraints & Breaking Changes

This section front-loads critical constraints discovered during validation research. All sections referencing these patterns must comply.

| Constraint | Impact | Status |
| --- | --- | --- |
| `case_reference` column does NOT exist | No `cases.case_reference` column exists; use `cases.id` directly | **Active** |
| Timeline requires per-step `background_tasks` rows | Timeline display requires one row per sequence step (SD-SEQ-PERSTEP-TASKS-001) | **Prerequisite** |
| Frontend incorrectly uses `task_id` (UUID) | Must use `case_id` (INTEGER PK) for case navigation | **Bug Fix** |
| `cases.id` (INTEGER) is stable identity | All internal references use integer case ID | **Active** |
| `background_tasks.task_id` (UUID) is per-attempt | Task UUID changes on each retry attempt | **Active** |

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend (Next.js / React)                                     │
│  - Updated API client (work-history.ts)                         │
│  - New CaseTimeline vertical timeline component                 │
│  - Updated RequestsTable with case_id + progress                │
│  - StatusLabel component consuming backend-only labels          │
│  - CI-generated statusLabels.ts from backend mapping            │
├─────────────────────────────────────────────────────────────────┤
│  Backend API (FastAPI)                                           │
│  - New GET /api/v1/cases/{case_id} (timeline + future)          │
│  - Updated GET /api/v1/verifications (+ case_id, progress)      │
│  - StatusLabelMapper (single source of truth)                   │
│  - scripts/export_status_labels.py (CI generator)               │
├─────────────────────────────────────────────────────────────────┤
│  Database (PostgreSQL)                                           │
│  - cases.id (INTEGER PK, stable identity)                       │
│  - background_tasks.case_id (INTEGER FK)                        │
│  - background_tasks.current_sequence_step (INTEGER)             │
│  - cases.latest_employment_status (TEXT)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Database Changes

**Design Decision** (PRD section 415 - Design Challenge Results): Use `cases.id` directly as the stable identity. The `case_id` foreign key in `background_tasks` already links all retries to the same case. No `case_reference` column is needed or implemented.

**Live Data Context**: The `cases.id` column (SERIAL/INTEGER PK) is already the stable identity used throughout the codebase:
- `background_tasks.case_id` (INTEGER FK) links all retry tasks to the same case
- Prefect email templates reference `case_id` directly
- Existing URLs and integrations use `case_id`

---

### 2.1 Migration: Add latest_employment_status to cases

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

---

**Note**: The PRD Design Challenge resolved to use `cases.id` directly — no case_reference column is needed or implemented.

---

**Research Finding (2026-03-11)**: The `case_reference` column was **never implemented**. PRD v0.5.0 (2026-03-09) removed this column in favor of using `cases.id` directly. The timeline display REQUIRES per-step `background_tasks` rows (SD-SEQ-PERSTEP-TASKS-001) as a PREREQUISITE.

---

## 2a. Prerequisites: Per-Step Task Creation

**CRITICAL**: This SD requires **per-step task creation** (from SD-SEQ-PERSTEP-TASKS-001) as a BEFORE-DEPLOYMENT prerequisite. Without it, the timeline has no data to display.

### Why This Is Required

The timeline endpoint (`GET /api/v1/cases/{case_id}`) queries `background_tasks` for each step in a sequence. Currently:

1. The Prefect orchestrator iterates steps in-memory via `asyncio.sleep(delay_hours)`
2. A `background_tasks` row is only written when:
  - A call result is retryable (`process_result.py:235`)
  - All steps are exhausted (`followup_scheduler.py:81`)

**Result**: Only step 1 has a `background_tasks` row visible in the timeline. Steps 2+ are invisible because they reused step 1's task_id.

### Prerequisite Implementation (from SD-SEQ-PERSTEP-TASKS-001)

This SD requires the following to be implementation FIRST:

| File | Change |
| --- | --- |
| `database/migrations/052_add_task_chain_columns.sql` | Add `previous_task_id`, `next_task_id` columns to `background_tasks` |
| `utils/background_task_helpers.py` | Add `create_step_task()` function to create per-step task rows |
| `prefect_flows/flows/verification_orchestrator.py` | Update step loop to create per-step tasks before dispatch |

### Timeline Data Flow (After Per-Step Tasks)

```
API creates case -> background_tasks row #1 (task_id=101, step=1)
    ↓
verification_orchestrator_flow(task_id=101)
    ↓
Step 1: dispatch_voice(task_id=101) → completed
    ↓
asyncio.sleep(delay)
    ↓
Guard: case resolved? → NO
    ↓
create_step_task(step=2) → background_tasks row #2 (task_id=102, step=2)
    ↓
Step 2: dispatch_email(task_id=102) ← CORRECT task_id!
    ↓
Timeline query returns:
- task_id=101, step=1, action=call_attempt, status=completed
- task_id=102, step=2, action=email_attempt, status=in_progress (visible!)

(Steps 2+ now have rows in database!)
```

### Acceptance Check

Before deploying this SD's timeline endpoint, verify:
- [ ] Migration `052_add_task_chain_columns.sql` is applied
- [ ] `create_step_task()` function exists and creates per-step rows
- [ ] Orchestrator uses `current_sequence_step` correctly
- [ ] `background_tasks` query returns one row per step

---

## 3. Backend API Changes

### 3.1 New Endpoint: GET /api/v1/cases/{case_id}

**File**: `api/routers/work_history.py`

**Key innovation** (Architect 4): The API synthesizes future steps by LEFT JOINing `background_check_sequence_steps` with actual tasks, filling gaps with `{status: "pending", task_id: null}`.

```python
@router.get("/api/v1/cases/{case_id}")
async def get_case_by_id(
    case_id: int,
    user: AuthenticatedUser = Depends(require_api_key),
    db: WorkHistoryDBService = Depends(get_db_service),
):
    """
    Get full case details by stable case ID.
    Returns case overview + full timeline (completed + future steps).
    """
    case = await db.get_case_by_id(case_id, user.customer_id)
    if not case:
        raise HTTPException(404, f"Case {case_id} not found")

    timeline = await db.get_case_timeline(case['id'], case.get('check_type_id'))

    return {
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

Add `case_id` and `sequence_progress` to the existing list endpoint:

```python
# In list_verifications handler, add to each item:
"case_id": row['case_id'],
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

OUTPUT = Path(__file__).parent.parent.parent / "my-project-frontend" / "generated" / "statusLabels.ts"

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

**Explicit guarantee** (PRD G1): This endpoint is **never deprecated**. Existing integrations using task_id continue to work indefinitely.

---

## 4. Frontend Changes

### 4.1 Updated API Client

**File**: `lib/api/work-history.ts`

Key changes:
- New: `getCaseById(case_id: int)` calling `GET /api/v1/cases/{case_id}`
- `getVerifications()` items now include `case_id`, `sequence_progress`, `status_label`
- `getVerificationById()` kept for backward compat
- React Query cache keys use `case_id` (not task_id)
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
| --- | --- | --- |
| `case_id` (task_id) | `case_id` (stable identity) | API `case_id` |
| Status (raw enum) | Status (StatusLabel component) | API `status_label` + `variant` |
| *(new)* | Progress (e.g., "3/5") | API `sequence_progress` |

Row click navigates to `/checks-dashboard/cases/{case_id}`.

### 4.5 Updated Case Detail Page

**File**: `app/checks-dashboard/cases/[id]/page.tsx`

- URL param: `[id]` (case_id, the stable integer identity)
- Fetches via `getCaseById(case_id)`
- Layout: CaseTimeline at top → task history below → verification results section

### 4.6 Terminology Cleanup

- Remove all occurrences of `"unreachable"` → use `"Unable to Verify"` (from generated constants)
- Replace customer-facing word `"task"` with `"check"` or `"verification"` across all UI components
- CI gate: frontend build fails if `generated/statusLabels.ts` is stale vs backend

---

## 5. Migration Strategy

### Phase 1: Backend (non-breaking)
1. Run migrations (latest_employment_status only; case_id already used)
2. Deploy backend with new `/cases/{case_id}` endpoint
3. Augment existing `/verifications` response with `case_id` and `sequence_progress`
4. Old endpoints continue working — zero downtime

### Phase 2: Frontend
1. Generate `statusLabels.ts` via CI script
2. Update API client: use `case_id`, add `getCaseById()`
3. Deploy updated dashboard pages (CaseTimeline, RequestsTable, case detail)

### Phase 3: Cleanup (30 days post-deploy)
1. Log warnings on task_id-based navigation
2. Update external integrations to use case_id
3. Remove legacy UUID redirects

---

## 6. Research Findings & Resolved Questions

### Resolved by Research Pipeline

1. **PG sequence safety** ✅: `nextval()` is atomic, non-transactional, safe under high concurrency. Gaps are expected and harmless. Global sequence confirmed as correct approach.
2. **Frontend component library** ✅: shadcn/ui has no timeline/stepper component. Custom Tailwind vertical timeline is the correct approach. Extract as `<Timeline>` + `<TimelineItem>` compound component.
3. **React Query polling** ✅: TanStack Query v5 supports `refetchInterval` as a callback — return `false` when status is terminal. Use `query.state.data` (untransformed) for status check.
4. **Denormalized step\_order** ✅: Setting at Prefect flow task-creation time is the correct pattern (matches Stripe's attempt_count on PaymentIntent). Backfill from `created_at` ordering is a reasonable approximation for existing data.

### Remaining Open Questions

1. **Prefect flow visibility**: Should we expose Prefect flow run IDs in the timeline? (Deferred — out of MVP scope, would add API latency)
2. **Search by case\_reference**: Should the dashboard have a search/filter field? (Deferred — add in v2 if customers request it)
3. **Backfill edge cases**: Are there cases where tasks were created out of chronological order? (Low risk — backfill uses `created_at ASC` which matches the expected execution order)

---

## 7. Files to Create/Modify

### Backend (my-project-backend)

| File | Action | Epic | Notes |
| --- | --- | --- | --- |
| `database/migrations/052_add_task_chain_columns.sql` | CREATE | A | **PREREQUISITE**: Add `previous_task_id`, `next_task_id` columns for per-step task chaining (SD-SEQ-PERSTEP-TASKS-001) |
| `database/migrations/0XZ_add_latest_status.sql` | CREATE | A | Add `latest_employment_status` to cases |
| `utils/background_task_helpers.py` | MODIFY | A | **PREREQUISITE**: Add `create_step_task()` for per-step task creation (SD-SEQ-PERSTEP-TASKS-001) |
| `prefect_flows/flows/verification_orchestrator.py` | MODIFY | A | **PREREQUISITE**: Update step loop to call `create_step_task()` before each step |
| `api/routers/work_history.py` | MODIFY | A | New `/cases/{case_id}` endpoint with timeline |
| `utils/status_labels.py` | CREATE | C | StatusLabelMapper for canonical label mapping |
| `scripts/export_status_labels.py` | CREATE | C | CI generator for frontend TypeScript constants |

**PREREQUISITE**: The per-step task creation changes (SD-SEQ-PERSTEP-TASKS-001) must be completed BEFORE deploying this SD's timeline endpoint. Without per-step `background_tasks` rows, the timeline will only show step 1 data. Research validated: `create_step_task()` function pattern confirmed in `utils/background_task_helpers.py:162-280` (`create_retry_task` pattern is reusable).

### Frontend (my-project-frontend)

| File | Action | Epic | Notes |
| --- | --- | --- | --- |
| `generated/statusLabels.ts` | CREATE (auto-generated) | C | From backend `StatusLabelMapper` |
| `lib/api/work-history.ts` | MODIFY — use case_id (integer) | B | API uses `case_id` (INTEGER PK) |
| `components/ui/StatusLabel.tsx` | CREATE | C | Renders colored badges from backend labels |
| `components/work-history/CaseTimeline.tsx` | CREATE | B | Vertical timeline component |
| `components/work-history/RequestsTable.tsx` | MODIFY | B | Update to use `case_id` column |
| `components/work-history/RecentRequestsTable.tsx` | MODIFY | B | Update to use `case_id` column |
| `app/checks-dashboard/cases/[id]/page.tsx` | CREATE/UPDATE | B | Case detail page (integer case_id) |
| `app/checks-dashboard/requests/page.tsx` | MODIFY | B | Update columns |
| `app/checks-dashboard/page.tsx` | MODIFY | B | Summary cards |
| `hooks/useVerifications.ts` | MODIFY | B | Terminal-aware polling |

---

## 7a. Research Findings Summary (2026-03-11)

| Finding | Impact on SD |
| --- | --- |
| `case_reference` column does NOT exist | Removed migration reference; use `cases.id` directly |
| Frontend uses `task_id` (UUID) incorrectly | Changed API client to use `case_id` (integer) |
| Timeline requires per-step `background_tasks` rows | Added prerequisite section referencing SD-SEQ-PERSTEP-TASKS-001 |
| No PG sequence needed | Removed all sequence-related code from this SD |

---

## 7b. New Prerequisite: Per-Step Task Creation (SD-SEQ-PERSTEP-TASKS-001)

**CRITICAL**: This SD cannot be deployed without first implementing **per-step task creation** (SD-SEQ-PERSTEP-TASKS-001). The timeline display REQUIRES a `background_tasks` row for each sequence step, but the current Prefect orchestrator only creates tasks on retry or completion — not when moving to a new step.

### Current Problem (Verified by research_perstep.md)

The Prefect `verification_orchestrator_flow` iterates steps in-memory via `asyncio.sleep(delay_hours)` and only writes `background_tasks` rows when:
1. A call result is retryable (`process_result.py:235`)
2. All steps are exhausted (`followup_scheduler.py:81`)

**Result**: Only step 1 has a visible `background_tasks` row. Steps 2+ are invisible because they reuse step 1's `task_id`.

### Required Prerequisites (Before Deploying Timeline)

| File | Change | Priority | Status |
| --- | --- | --- | --- |
| `database/migrations/052_add_task_chain_columns.sql` | Add `previous_task_id`, `next_task_id` columns | P0 | Not created in SD-SEQ-PERSTEP-TASKS-001 |
| `utils/background_task_helpers.py` | Add `create_step_task()` function | P0 | Requires per-step task creation |
| `prefect_flows/flows/verification_orchestrator.py` | Update step loop to create per-step tasks | P0 | Requires per-step task creation |

### Implementation Pattern (from research_perstep.md)

```python
async def create_step_task(
    case_id: int,
    customer_id: int,
    step: dict,
    sequence_id: int,
    sequence_version: int,
    check_type_config_id: int,
    previous_task_id: int | None,
    db_pool,
) -> int:
    """Create a background_tasks row for a step that is about to begin.

    Called BEFORE dispatching the step's channel (voice/email/SMS).
    The returned task_id MUST be used for all dispatches in this step.
    """
    # Map channel_type to action_type
    channel_to_action = {
        'voice': 'call_attempt',
        'email': 'email_attempt',
        'sms': 'sms_attempt',
        'whatsapp': 'whatsapp_attempt',
    }
    action_type = channel_to_action.get(step['channel_type'], 'call_attempt')

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # INSERT the new step task
            new_task_id = await conn.fetchval("""
                INSERT INTO background_tasks (
                    case_id, customer_id, action_type, status,
                    current_sequence_step, sequence_id, sequence_version,
                    check_type_config_id, previous_task_id,
                    retry_count, max_retries, context_data,
                    created_at, attempt_timestamp
                ) VALUES ($1, $2, $3, 'in_progress', $4, $5, $6, $7, $8,
                          0, $9, $10::jsonb, NOW(), NOW())
                RETURNING id
            """, case_id, customer_id, action_type, step['step_order'],
                sequence_id, sequence_version, check_type_config_id,
                previous_task_id, step['max_attempts'],
                json.dumps({"step_name": step['step_name'], "channel_type": step['channel_type']}))

            # Chain: update previous task's next_task_id
            if previous_task_id is not None:
                await conn.execute("""
                    UPDATE background_tasks SET next_task_id = $1 WHERE id = $2
                """, new_task_id, previous_task_id)

    return new_task_id
```

### Timeline Data Flow (After Per-Step Tasks)

```
Step 1: dispatch_voice(task_id=101) → completed
    ↓
asyncio.sleep(delay)
    ↓
Guard: case resolved? → NO
    ↓
create_step_task(step=2) → task_id=103 (NEW ROW!)
    ↓
Step 2: dispatch_email(task_id=103) ← CORRECT task_id!

Timeline query now returns:
- task_id=101, step=1, action=call_attempt, status=completed
- task_id=103, step=2, action=email_attempt, status=in_progress (VISIBLE!)
```

### Acceptance Criteria (Before Timeline Deployment)

| Criteria | Status |
| --- | --- |
| Migration `052_add_task_chain_columns.sql` applied | PENDING |
| `create_step_task()` function exists | PENDING |
| Orchestrator uses per-step task creation | PENDING |
| `background_tasks` query returns one row per step | PENDING |
| Email verification links use correct task_id | PENDING |

---
