---
title: "SD-DASHBOARD-AUDIT-001: Checks Dashboard — Stable References, Audit Trail, Terminology (Reverse Engineering Design)"
status: active
type: architecture
grade: authoritative
last_verified: 2026-03-09T00:00:00.000Z
---
# SD-DASHBOARD-AUDIT-001: Checks Dashboard Reverse Engineering Design

**Version**: 1.0.0
**Date**: 2026-03-09
**Methodology**: Reverse Engineering — working backwards from the ideal customer experience
**Companion PRD**: [PRD-DASHBOARD-AUDIT-001.md](./PRD-DASHBOARD-AUDIT-001.md)
**Codebase Verified**: `zenagent2/zenagent/agencheck` (backend + frontend, 2026-03-09)

---

## VERDICT: APPROVE with One Modification

**APPROVE** the AC-YYYYMM-NNNN format with one modification: make the sequence number **global** (not per-month). Rationale below.

### Challenge Response: Should customers want AC-202603-0042 or AC-42?

The format question is not purely cosmetic — it determines the operational surface area.

| Format | Pros | Cons |
| --- | --- | --- |
| `AC-202603-0042` | Self-dating (compliance auditors know when it was created); survives 10+ years without collision; aligns with invoice numbers | Too long for verbal communication; month-number ambiguity (0042 this month ≠ 0042 last month) |
| `AC-42` | Shortest; works verbally; matches Stripe/Jira style | Ambiguous at scale (case 42 vs invoice 42 vs customer 42); not self-dating |
| `AC-202603-042` | Compromise — shorter seq, retains date context | Still long; 3-digit seq overflows at 999/month for active clients |

**Recommended format**: `AC-{YYYYMM}-{NNNNN}` where `{NNNNN}` is a **global** monotonic counter (5 digits, zero-padded), NOT per-month.

**Rationale**: The per-month sequential number creates two problems:
1. Backfill via `row_number() OVER (PARTITION BY YYYYMM ORDER BY id)` is deterministic but means case 0042 exists in every month — if a customer emails "AC-202603-0042" and support searches "0042", they must also filter by month.
2. A global counter means `AC-202603-00042` is permanently unique across all time. The date prefix still provides temporal context for auditors.

**In email subject lines**: `[AgenCheck] Verification AC-202603-00042 — John Doe at Acme Corp` is acceptable. Users who want brevity can use `00042` as the short-form within a session where the month is implied.

---

## IDEAL DATA CONTRACT

### What the frontend needs to render the ideal case list row

```
"AC-202603-0042 | John Doe → Acme Corp | Step 3/5: Second Retry | In Progress"
```

**Minimum API response per list row** (`GET /api/v1/verifications`):

```json
{
  "case_reference": "AC-202603-00042",
  "case_db_id": 123,
  "candidate_name": "John Doe",
  "employer_name": "Acme Corp",
  "check_type": "work_history",
  "case_status": "in_progress",
  "case_status_label": "In Progress",
  "sequence_progress": {
    "current_step": 3,
    "total_steps": 5,
    "current_step_name": "second_retry",
    "current_step_label": "Second Retry",
    "channel_type": "voice"
  },
  "created_at": "2026-03-01T10:00:00Z",
  "last_activity_at": "2026-03-02T09:00:00Z"
}
```

### What the frontend needs to render the ideal case timeline

```
Initial Call (Voicemail Left) → First Retry (No Answer) → Second Retry (In Progress)
  → Third Retry (Pending) → Final Attempt (Pending)
```

**Full case detail response** (`GET /api/v1/cases/{case_reference}`):

```json
{
  "case_reference": "AC-202603-00042",
  "case_db_id": 123,
  "candidate_name": "John Doe",
  "employer_name": "Acme Corp",
  "check_type": "work_history",
  "case_status": "in_progress",
  "case_status_label": "In Progress",
  "created_at": "2026-03-01T10:00:00Z",
  "sequence_progress": {
    "current_step": 3,
    "total_steps": 5,
    "current_step_name": "second_retry",
    "current_step_label": "Second Retry"
  },
  "timeline": [
    {
      "step_order": 1,
      "step_name": "initial_call",
      "step_label": "Initial Call",
      "channel_type": "voice",
      "task_id": "uuid-abc-001",
      "status": "completed",
      "result_status": "voicemail_left",
      "result_label": "Voicemail Left",
      "started_at": "2026-03-01T10:05:00Z",
      "completed_at": "2026-03-01T10:08:00Z"
    },
    {
      "step_order": 2,
      "step_name": "first_retry",
      "step_label": "First Retry",
      "channel_type": "voice",
      "task_id": "uuid-abc-002",
      "status": "completed",
      "result_status": "no_answer",
      "result_label": "No Answer",
      "started_at": "2026-03-01T14:00:00Z",
      "completed_at": "2026-03-01T14:02:00Z"
    },
    {
      "step_order": 3,
      "step_name": "second_retry",
      "step_label": "Second Retry",
      "channel_type": "voice",
      "task_id": "uuid-abc-003",
      "status": "in_progress",
      "result_status": null,
      "result_label": "In Progress",
      "started_at": "2026-03-02T09:00:00Z",
      "completed_at": null
    },
    {
      "step_order": 4,
      "step_name": "third_retry",
      "step_label": "Third Retry",
      "channel_type": "voice",
      "task_id": null,
      "status": "pending",
      "result_status": null,
      "result_label": "Pending",
      "started_at": null,
      "completed_at": null
    },
    {
      "step_order": 5,
      "step_name": "final_attempt",
      "step_label": "Final Attempt",
      "channel_type": "voice",
      "task_id": null,
      "status": "pending",
      "result_status": null,
      "result_label": "Pending",
      "started_at": null,
      "completed_at": null
    }
  ],
  "verification_results": null
}
```

**Key design decisions in this contract:**

1. **Future steps appear in the timeline with ****`status: "pending"`**** and ****`task_id: null`**. They come from `background_check_sequence_steps` joined against the case's `sequence_id`. The frontend renders them as unfilled circles. This is what transforms the view from "flat history" to "full workflow awareness."

2. **`result_label`**** is computed server-side**, not by the frontend. This guarantees terminology consistency without duplicating the mapping table in TypeScript.

3. **`sequence_progress`**** is a summary object** in both list and detail responses. The list view can render "3/5" without loading the full timeline.

4. **`case_reference`**** is the canonical URL key**. The URL becomes `/checks-dashboard/cases/AC-202603-00042`. Old `task_id`-based URLs redirect 301 to the case_reference URL.

---

## MINIMAL SCHEMA CHANGES

**Goal**: Maximum impact with minimum migrations. Three changes only.

### Change 1: Add `case_reference` to `cases` table

```sql
-- Migration 047: Stable case reference
-- Run: psql $DATABASE_URL -f 047_case_reference.sql

BEGIN;

-- Step 1: Add global sequence (monotonic, never resets)
CREATE SEQUENCE IF NOT EXISTS cases_reference_seq START 1;

-- Step 2: Add column (nullable initially for backfill)
ALTER TABLE cases
  ADD COLUMN IF NOT EXISTS case_reference TEXT UNIQUE;

-- Step 3: Back-fill existing rows
-- Format: AC-{YYYYMM}-{5-digit padded global seq}
-- Use created_at for the date prefix, row insertion order (id ASC) for sequence
UPDATE cases
SET case_reference =
  'AC-' || to_char(created_at, 'YYYYMM') || '-' ||
  lpad(nextval('cases_reference_seq')::text, 5, '0')
WHERE case_reference IS NULL
ORDER BY id ASC;  -- Ensures monotonic seq aligns with creation order

-- Step 4: Enforce NOT NULL after backfill
ALTER TABLE cases
  ALTER COLUMN case_reference SET NOT NULL,
  ALTER COLUMN case_reference SET DEFAULT
    'AC-' || to_char(NOW(), 'YYYYMM') || '-' || lpad(nextval('cases_reference_seq')::text, 5, '0');

-- Step 5: Index (already unique, but add for pattern search)
CREATE INDEX IF NOT EXISTS idx_cases_case_reference ON cases(case_reference);

COMMIT;
```

**Note on DEFAULT**: The DEFAULT expression cannot reference a sequence in this form in Postgres — instead, the application layer (`WorkHistoryCaseService.create_work_history_case`) generates the reference before the INSERT. The column should have `DEFAULT NULL` and the NOT NULL enforcement happens at app layer. See Backend Change 1 below.

### Change 2: Add `sequence_id` FK to `background_tasks` (if not already present)

From the existing code review, `background_tasks` links to `cases` via `case_id`. The `cases` table already has `verification_metadata` with SLA/sequence info. The `background_check_sequence_steps` table already exists (migrations 035/036). What is missing is the join path to determine **which step** a background_task corresponds to.

The minimal solution is a single column addition:

```sql
-- Migration 048: Link background_tasks to check sequence steps
ALTER TABLE background_tasks
  ADD COLUMN IF NOT EXISTS sequence_step_order INTEGER DEFAULT NULL;

COMMENT ON COLUMN background_tasks.sequence_step_order IS
  'The step_order from background_check_sequence_steps that this task executes.
   NULL for non-sequence tasks. Set by Prefect flow at task creation.';
```

**Why ****`step_order`**** not ****`step_id`****?** Step order is stable and human-readable. If the sequence configuration changes (a step is deleted and re-added), using `step_id` FK would leave orphan references. `step_order` is the position in the sequence, not a pointer — it degrades gracefully.

### Change 3: No additional changes required

The `result_status` column already exists as `call_result_status` enum with 14 values (verified in migration 028). The `previous_task_id` / `next_task_id` chain already exists. The `cases.status` field already tracks overall case state. The `background_check_sequence_steps` table already has `step_name`, `step_order`, `channel_type`.

**Total schema delta**: 2 columns added (1 on `cases`, 1 on `background_tasks`), 1 sequence created. No table drops, no enum changes, no data model restructuring.

---

## RECOMMENDED CHANGES

### Path from Current to Ideal: 4 steps in sequence

---

### Step 1: Backend — `case_reference` generation and exposure (Epic A)

**Files to change:**
- `helpers/work_history_case.py` — generate case_reference on `create_work_history_case`
- `api/routers/work_history.py` — expose case_reference in `list_verifications`, new `GET /cases/{ref}` endpoint
- `database/migrations/047_case_reference.sql` — migration (schema above)

**Generation logic** (in `create_work_history_case`):

```python
async def _generate_case_reference(self, conn, created_at: datetime) -> str:
    """Generate stable case reference: AC-YYYYMM-NNNNN"""
    month_prefix = created_at.strftime('%Y%m')
    seq = await conn.fetchval("SELECT nextval('cases_reference_seq')")
    return f"AC-{month_prefix}-{str(seq).zfill(5)}"
```

Call this before the `INSERT INTO cases ...` and pass `case_reference` as a column value.

**Update ****`list_verifications`**** query** — add to the SELECT:

```sql
SELECT
    bt.id,
    bt.task_id,
    bt.status,
    bt.result_status,
    bt.sequence_step_order,       -- NEW
    bt.created_at,
    bt.completed_at,
    c.case_reference,              -- NEW
    c.status AS case_status,       -- NEW (cases.status, not bt.status)
    c.sequence_id,                 -- for step count lookup
    uc.employer_name AS uc_employer_name
FROM background_tasks bt
LEFT JOIN cases c ON bt.case_id = c.id
LEFT JOIN university_contacts uc ON c.employer_contact_id = uc.id
WHERE bt.customer_id = $1
  AND bt.action_type = 'call_attempt'
```

**New endpoint**: `GET /api/v1/cases/{case_reference}`

Query pattern:

```sql
-- Get case + all tasks + sequence steps
SELECT
    c.case_reference,
    c.id AS case_db_id,
    c.status AS case_status,
    c.sequence_id,
    c.created_at,
    -- Candidate name from context_data
    -- Employer from university_contacts or context_data
    bt.id AS task_db_id,
    bt.task_id,
    bt.status AS task_status,
    bt.result_status,
    bt.sequence_step_order,
    bt.created_at AS task_created_at,
    bt.completed_at AS task_completed_at,
    bcss.step_name,
    bcss.step_order,
    bcss.channel_type
FROM cases c
LEFT JOIN background_tasks bt
    ON bt.case_id = c.id
    AND bt.action_type = 'call_attempt'
LEFT JOIN background_check_sequence_steps bcss
    ON bcss.sequence_id = c.sequence_id
    AND bcss.step_order = bt.sequence_step_order
WHERE c.case_reference = $1
  AND c.customer_id = $2
ORDER BY bt.sequence_step_order ASC NULLS LAST, bt.created_at ASC;
```

Then fetch total steps from `background_check_sequence_steps WHERE sequence_id = c.sequence_id` and synthesize the pending future steps in Python before returning. The pending steps have `task_id = None`, `status = "pending"`.

**`StatusLabelMapper`** — new utility class in `helpers/status_labels.py`:

```python
CALL_RESULT_LABELS: dict[str, str] = {
    "completed": "Verified",
    "partial_verification": "Partial Verification",
    "refused": "Refused",
    "unable_to_verify": "Unable to Verify",
    "wrong_number": "Wrong Number",
    "max_retries_exceeded": "Max Retries Exceeded",
    "voicemail_left": "Voicemail Left",
    "no_answer": "No Answer",
    "busy": "Busy",
    "callback_requested": "Callback Requested",
    "manual_review": "Under Review",
    "invalid_contact": "Invalid Contact",
    "aborted": "Aborted",
    "call_scheduled": "Scheduled",
}

STEP_NAME_LABELS: dict[str, str] = {
    "initial_call": "Initial Call",
    "first_retry": "First Retry",
    "second_retry": "Second Retry",
    "third_retry": "Third Retry",
    "final_attempt": "Final Attempt",
    "email_outreach": "Email Outreach",
    "human_review": "Human Review",
}
```

---

### Step 2: Backend — `sequence_step_order` population in Prefect flows (Epic B)

**Where to change**: `prefect_flows/templates/work_history/` — specifically the task creation step in each flow subflow.

When a Prefect subflow creates a `background_task` row for a call attempt, it must set `sequence_step_order` to the step's order from the sequence definition.

This is the only place where the step order is known — in the Prefect flow context when the sequence is being executed. The flow already reads `check_steps` from the case's `verification_metadata`. The step_order can be passed at task creation time.

**Backward compatibility**: `sequence_step_order IS NULL` for existing tasks. The timeline API gracefully falls back to `previous_task_id`/`next_task_id` chain order when `sequence_step_order` is not populated. This means old cases show the chain order without step labels.

---

### Step 3: Frontend — API client and type updates (Epic C, Part 1)

**File**: `lib/api/work-history.ts`

Replace:
```typescript
// BEFORE — conflates task_id with case identity
export interface VerificationCaseSummary {
  case_id: string;  // This is actually task_id (UUID)
  candidate_name: string;
  employer: string;
  status: CaseStatus;
  employment_status?: EmploymentStatus;
}
```

With:
```typescript
// AFTER — correct field separation
export interface VerificationCaseSummary {
  case_reference: string;    // AC-202603-00042 — stable, human-readable
  case_db_id: number;        // Internal DB integer ID (for API calls)
  task_id?: string;          // UUID of most recent task (for backward compat)
  candidate_name: string;
  employer_name: string;
  case_status: CaseStatus;
  sequence_progress?: SequenceProgress;
  created_at: string;
  last_activity_at?: string;
}

export interface SequenceProgress {
  current_step: number;
  total_steps: number;
  current_step_label: string;
  channel_type: string;
}

export interface TimelineStep {
  step_order: number;
  step_label: string;
  channel_type: string;
  task_id: string | null;
  status: 'pending' | 'in_progress' | 'completed';
  result_status: string | null;
  result_label: string;
  started_at: string | null;
  completed_at: string | null;
}
```

The frontend API call for the list view hits `GET /api/v1/verifications` (existing endpoint, now enriched). The case detail view hits the **new** `GET /api/v1/cases/{case_reference}` endpoint.

---

### Step 4: Frontend — UI components (Epic C, Part 2)

**URL routing change**: `app/checks-dashboard/cases/[id]/page.tsx` → rename to `app/checks-dashboard/cases/[ref]/page.tsx`. Add a redirect in `next.config.js` or a catch-all from the old UUID pattern to the new `case_reference` pattern.

**New component**: `components/work-history/CaseTimeline.tsx`

Renders the stepper:
- Completed steps: filled circle with green ✓ and `result_label`
- Current step: half-filled circle (animated pulse if `status === "in_progress"`)
- Pending steps: empty circle with grey "Pending" label

The component receives the `timeline` array from the case detail API. No business logic in the component — it only renders what the API provides.

**Requests table update** (`components/work-history/RequestsTable.tsx`):

Replace the `case_id` UUID cell with `case_reference`. Add a `Progress` cell showing `{current_step}/{total_steps}` as a small progress indicator.

**Status badge alignment** (`components/work-history/VerificationStatusBadge.tsx`):

The `STATUS_CONFIG` object currently has `in_progress` mapped to `label: CASE_STATUS_DISPLAY.in_progress`. The fix is straightforward — add entries for all `call_result_status` values that are missing. The key terminology fix: remove any reference to "unreachable" (it was a v3.0 enum value that was removed; the current backend enum does not contain it, but if it was hardcoded in the frontend config it must be removed).

---

## EXECUTION ORDER AND DEPENDENCIES

```
Step 1 (Backend schema + API)
  ├── 047_case_reference.sql migration
  ├── case_reference generation in WorkHistoryCaseService
  ├── list_verifications query update (backward compatible)
  └── GET /api/v1/cases/{ref} new endpoint
       ↓
Step 2 (Prefect flows — parallel with Step 3)
  └── sequence_step_order population at task creation
       ↓
Step 3 (Frontend types — can start after Step 1 API is deployed)
  └── lib/api/work-history.ts type updates
       ↓
Step 4 (Frontend UI — requires Step 3)
  ├── URL routing rename
  ├── CaseTimeline component
  ├── RequestsTable updates
  └── VerificationStatusBadge terminology fixes
```

Steps 2 and 3 can be executed in parallel once Step 1 is deployed.

---

## RISK MITIGATION

| Risk | Mitigation |
| --- | --- |
| Backfill fails on large dataset | Run `UPDATE cases ... ORDER BY id ASC LIMIT 1000` in batches via script; verify count before making NOT NULL |
| Old UUID-based bookmarks break | Next.js redirect: if `[ref]` matches UUID pattern, call `GET /api/v1/verifications/{uuid}`, extract `case_reference`, redirect 301 |
| `sequence_step_order` NULL for all old tasks | Fall back to `previous_task_id` chain when `sequence_step_order IS NULL`; show "Step N (estimated)" label |
| Prefect flow cannot determine step_order | Step_order is already in `check_steps` JSONB in `verification_metadata` — the flow reads this to know delay intervals, so it knows its own position |
| Frontend references to `case_id` field | The API continues to return `task_id` for backward compatibility; only `case_reference` is the new canonical field |

---

## HINDSIGHT FINDINGS

Reflected against `claude-code-agencheck` bank (2026-03-09).

**Prior learnings confirmed by this analysis:**
- The `verification_events` table exists for billing but is separate from `background_tasks`. The audit trail for the dashboard should come from `background_tasks` (the execution record), not `verification_events` (the billing record). These serve different audiences.
- The `partial_verification` enum is correct terminology (not "completed with discrepancies"). The frontend `EMPLOYMENT_STATUS_DISPLAY` object already uses this key — no frontend rename needed, only ensure the display label reads "Partial Verification" not "partial_verification".
- The `left JOIN cases c ON bt.case_id = c.id` + `LEFT JOIN university_contacts uc ON c.employer_contact_id = uc.id` pattern is already in `list_verifications` (added in Fix agencheck-io2w, 2026-02-06). The employer name source is correct. Only `case_reference` and `sequence_step_order` are missing from this query.

**New finding from this analysis:**
- The frontend `work-history.ts` line 368 maps `case_id: v.task_id`. This is the single root cause of the identity confusion. All downstream components that read `case_id` are actually reading the `task_id` UUID. This must be corrected at the API client layer — not in each component individually.
