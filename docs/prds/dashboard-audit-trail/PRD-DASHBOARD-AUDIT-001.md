---
title: "PRD-DASHBOARD-AUDIT-001: Dashboard Audit Trail & Stable References"
status: draft
type: guide
grade: authoritative
last_verified: 2026-03-09T00:00:00.000Z
---
# PRD-DASHBOARD-AUDIT-001: Dashboard Audit Trail & Stable References

**Version**: 0.4.0 (Added frontend case detail page design from Stitch)
**Date**: 2026-03-09
**Status**: DRAFT — pending research → refine pipeline
**Parent PRDs**: Epic 7 Structured Interpretation PRD (v1.4), Phase 1 UE-F Platform Infrastructure (Epic F.6)
**Target Repo**: my-org3/my-org/my-project (frontend + backend)

---

## 1. Executive Summary

The MyProject checks-dashboard frontend incorrectly uses `task_id` (per-attempt UUID from `background_tasks`) for navigation and display, even though a stable case identity already exists via `cases.id` and the `background_tasks.case_id` FK. Customers cannot see the full audit trail — they see isolated task snapshots without understanding which step in the check sequence they're viewing.

This PRD addresses three interconnected problems:

1. **Fix Frontend ID Usage + Human-Readable Reference**: The frontend must use `cases.id` (not `task_id`) for all case navigation. Additionally, add a `case_reference` column (format `AC-YYYYMM-NNNNN`) to the `cases` table as a customer-friendly display alias, generated via PostgreSQL sequence
2. **Full Audit Trail Display**: Show the complete task history AND synthesized future steps from the check_sequence definition — customers see "Step 3 of 5: Second Retry" with a vertical timeline
3. **Terminology Alignment**: Single-source StatusLabelMapper on the backend; frontend receives only canonical v3.3 labels

**Design validated by**: 7 parallel solution architects (unanimous MODIFY consensus). Key patterns: Stripe PaymentIntent (denormalized status + attempt chain), FedEx tracking (stable reference + event timeline), Zendesk (human-readable ID generation).

---

## 2. Problem Statement

### P1: Frontend Uses Wrong ID (task_id Instead of case_id)

The `cases` table already provides a stable identity across retries — `background_tasks.case_id` FK links every attempt back to the same case. The stable reference **already exists** in the database.

However, the frontend ignores `cases.id` and navigates using `task_id` (per-attempt UUID from `background_tasks`). The API client in `work-history.ts` line 368 maps `case_id: v.task_id` — literally substituting the per-attempt UUID where the stable `cases.id` should be used.

Additionally, `cases.id` (an integer PK) is not customer-friendly for display, URLs, or external communication. Adding a human-readable `case_reference` (e.g., `AC-202603-00042`) to the `cases` table provides a display-friendly alias while preserving the existing stable foreign key relationship.

### P2: No Audit Trail Visibility

The dashboard shows a flat list of tasks. No visibility into which step in the `check_sequence` a task represents, how many attempts were made, or what comes next. The system already has `background_check_sequence_steps` (step_order, step_name, delay_hours, channel_type), `previous_task_id`/`next_task_id` chain on background_tasks, and `sequence_id`/`sequence_version` — but none of this is exposed to the frontend.

### P3: Terminology Misalignment

| Context | Frontend | Backend | Database |
| --- | --- | --- | --- |
| Case identifier | `case_id` (actually task_id) | `task_id` (UUID) | `background_tasks.id` |
| Outcome | "verified" / "failed" | `employment_status` (5 values) | `result_status` (CallResultStatus, 14 values) |
| Legacy label | "unreachable" | Does not exist in v3.3 | `UNABLE_TO_VERIFY` |

---

## 3. Goals & Success Criteria

### G1: Human-Readable Case Reference + Fix Frontend ID Usage

The stable reference already exists (`cases.id` → `background_tasks.case_id` FK). Two changes are needed:

1. **Fix the frontend**: Replace `task_id` (per-attempt UUID) with `cases.id` / `case_reference` for all navigation and display
2. **Add display-friendly alias**: Add `case_reference` column to `cases` table with human-readable format

**Format**: `AC-YYYYMM-NNNNN` (e.g., `AC-202603-00042`)
- Global monotonic PostgreSQL sequence (no per-month reset — avoids search ambiguity)
- YYYYMM is cosmetic (derived from created_at), NNNNN is global counter
- 5-digit padding supports 99,999 cases before width change

**Success Criteria**:
- [ ] Frontend uses `cases.id` (or `case_reference`) for all navigation — never `task_id`
- [ ] `work-history.ts` `case_id: v.task_id` mapping is replaced with actual `case_id` from API
- [ ] All API responses include `case_reference`
- [ ] Dashboard URLs use case_reference: `/checks-dashboard/cases/AC-202603-00042`
- [ ] `GET /api/v1/verifications/{task_id}` remains permanent (never deprecated)
- [ ] Existing cases receive back-filled references via migration

### G2: Full Audit Trail on Dashboard

**Success Criteria**:
- [ ] Case detail page shows vertical timeline of ALL tasks + synthesized future pending steps
- [ ] Each timeline entry: step_name, attempt number, channel_type, result_label, timestamp
- [ ] Current position highlighted; future steps shown as pending circles
- [ ] Cases list shows `sequence_progress` summary (e.g., "3/5")
- [ ] `step_order` denormalized on `background_tasks` for accurate positioning

### G3: Terminology Alignment

**Success Criteria**:
- [ ] Backend `StatusLabelMapper` is single source of truth for all display labels
- [ ] Frontend receives only `status_label` strings — never maps raw enums
- [ ] No occurrence of legacy "unreachable" in frontend
- [ ] CI gate validates frontend status labels match backend-generated file
- [ ] Word "task" retired from all customer-facing UI surfaces

---

## 4. Scope

### In Scope

| Area | Changes |
| --- | --- |
| **Database** | `cases.case_reference` column (UNIQUE NOT NULL), `background_tasks.sequence_step_order` column, PG sequence, backfill migration |
| **Backend API** | `GET /api/v1/cases/{case_reference}` (case + timeline + future steps), `StatusLabelMapper` utility, `latest_employment_status` denormalized on cases |
| **Frontend** | Vertical timeline component, updated RequestsTable with case_reference + progress, StatusLabel component consuming backend labels only |
| **Terminology** | Backend-canonical label mapping, CI-generated frontend constants |

### Out of Scope

- Modifying Prefect flow logic
- Dedicated `case_events` table (deferred — reconstruct from existing background_tasks chain for v1)
- Real-time WebSocket updates
- AI-generated natural language summaries (future v2 enhancement)
- CSV export of audit trail

---

## 5. Technical Design Decisions (Architect Consensus)

### 5.1 Human-Readable Reference: Stored Column on `cases` + PG Sequence

The stable identity already exists (`cases.id`). This decision concerns only the **display-friendly alias**.

**Decision**: Store `case_reference` as a concrete column on `cases` table (5/7 architects).
**Rejected**: Computing display format from `cases.id` at API layer (1/7) — external systems need queryable references, and format changes would break URLs.

```sql
CREATE SEQUENCE cases_reference_seq START 1;

-- Application generates at INSERT time:
-- 'AC-' || to_char(created_at, 'YYYYMM') || '-' || lpad(nextval('cases_reference_seq')::text, 5, '0')
```

**Thread safety**: PG sequences are atomic across connections. `nextval()` is non-transactional (gaps on rollback are acceptable). No TOCTOU race.

### 5.2 Audit Trail: Timeline with Synthesized Future Steps

**Decision**: Vertical timeline (not ordered stepper) showing completed tasks + pending future steps from check_sequence.
**Key innovation** (Architect 4): The API synthesizes future steps by LEFT JOINing `background_check_sequence_steps` with actual tasks, filling gaps with `{status: "pending", task_id: null}`.

### 5.3 Step Position: Denormalized on background_tasks

**Decision**: Add `sequence_step_order INTEGER` to `background_tasks`. Prefect flows set it at task creation time (4/7 architects).
**Rejected**: Counting tasks to derive step order (P=0.31 accuracy per Architect 6).

### 5.4 Status Labels: Backend Single Source of Truth

**Decision**: `StatusLabelMapper` Python dict in `utils/status_labels.py`. Frontend receives only `status_label` strings. CI script generates `generated/statusLabels.ts` and fails build if stale (3/7 explicit, all compatible).

### 5.5 List Performance: Denormalized latest_employment_status

**Decision**: Add `latest_employment_status` on cases table, updated via Prefect on_completion hook. Case-list endpoint reads only from cases — no joins for the paginated table view.

---

## 6. Epics (Scoped to MVP Sprint 1)

### Epic A: Stable Reference + Schema Changes (Backend)

1. Migration: add `case_reference` column with PG sequence, backfill via CTE, unique index
2. Migration: add `sequence_step_order` to background_tasks
3. Migration: add `latest_employment_status` to cases
4. Application: generate case_reference in `WorkHistoryCaseService.create_work_history_case`
5. New endpoint: `GET /api/v1/cases/{case_reference}` with full timeline (tasks + future steps)
6. Update `GET /api/v1/verifications` to include `case_reference` and `sequence_progress`
7. Explicit: `GET /api/v1/verifications/{task_id}` is permanent, never deprecated

### Epic B: Dashboard Frontend — Case Detail Page Redesign

**Design Source**: Stitch project 4785994430092730679, screen 2906fd2e2b044991b8e672b9c41e3bc5
**Constraint**: Do NOT change main navigation (header) or side navigation (sidebar)

#### B.1: Data Layer & API Client Fix
1. Fix `work-history.ts:368` — replace `case_id: v.task_id` with actual `case_id` from API response
2. Add `getCaseByReference(ref: string)` API client calling `GET /api/v1/cases/{case_reference}`
3. React Query cache keys use `case_reference` (not task_id); `refetchInterval` callback returns `false` when case status is terminal

#### B.2: Case Detail Page Layout (`/checks-dashboard/cases/[ref]`)
1. **Breadcrumb**: Dashboard → Checks → Case #{case_reference} (shadcn Breadcrumb)
2. **Page header**: Title "Work History Verification (AI) Case #{case_reference}" + Actions dropdown (shadcn DropdownMenu with Flag Issue, Request Re-verification, Download Report)
3. **12-column grid layout**: 7-col left (candidate card + verification results), 5-col right (activity timeline)

#### B.3: Candidate & Employer Card (left column, top)
1. shadcn Card with candidate avatar placeholder, name, and target employer with business icon
2. Data: `candidate_name`, `employer_name` from case detail API

#### B.4: Verification Results Comparison Table (left column, below candidate)
1. Two-column comparison: "Candidate Claimed" vs "MyProject Verified"
2. Rows: Start Date, End Date, Employment Type, Position (from `verification_results` API field)
3. Each verified field shows green check (match) or amber warning icon + "Mismatch" badge (discrepancy)
4. Header badge: overall status — "Verified", "Discrepancy Found", "Pending" (shadcn Badge with variant)
5. Custom `VerificationComparisonTable` component; uses shadcn Card as wrapper

#### B.5: Activity & Communications Timeline (right column)
1. Custom vertical `CaseTimeline` component with left border line + dot markers
2. Each event: title, subtitle, timestamp (right-aligned)
3. Completed events: filled dot (teal for latest action, outline for older)
4. Future/pending steps: dashed outline dots with "Pending" label
5. Call recording entry: embedded audio player (play button + progress bar + duration) + "View Full Transcript" link
6. Events sourced from `timeline` array in case detail API response

#### B.6: Checks List Table Updates
1. `/checks-dashboard/requests` table: add `case_reference` column, `sequence_progress` column ("Step 1 of 3")
2. All status labels from backend `status_label` field (no frontend mapping)
3. Replace word "task" with "check" or "verification" in all customer-facing text

#### B.8: Interaction Design (High-Level Requirements)

**Page Loading States**:
1. Skeleton loader while case detail API loads (shadcn Skeleton for each card/section)
2. Timeline entries animate in sequentially (stagger 50ms) on first load
3. If API returns 404 for case_reference, show "Case not found" empty state with link back to checks list

**Verification Results Interactions**:
1. Mismatch rows highlight on hover with subtle amber background tint
2. Clicking a mismatched row could expand to show additional context (future: AI explanation of discrepancy)
3. Overall status badge pulses gently when status is "In Progress" (non-terminal)

**Activity Timeline Interactions**:
1. Timeline auto-scrolls to current/latest step on page load
2. Hovering a timeline dot shows tooltip with step label + timestamp
3. Pending (future) steps appear faded (opacity-50) with dashed connector line
4. When a new step completes (via polling), it animates from pending→completed (dot fills, opacity transitions to 100%)

**Audio Player Interactions**:
1. Play/pause toggle with smooth icon transition
2. Clicking progress bar seeks to that position
3. Dragging the scrubber knob adjusts playback position
4. "View Full Transcript" opens a modal or inline expandable panel with timestamped transcript

**Actions Dropdown**:
1. "Flag Issue" → opens confirmation dialog with optional notes field
2. "Request Re-verification" → opens confirmation dialog with reason selection
3. "Download Report" → triggers PDF download of case summary

**Polling & Real-Time Updates**:
1. Active cases poll every 10 seconds via React Query `refetchInterval`
2. When case reaches terminal status, polling stops (`refetchInterval: false`)
3. New timeline events appear with a brief highlight animation (green flash then fade)
4. Sequence progress ("Step 2 of 3") updates inline without page reload

**Responsive Behavior**:
1. On mobile (`< lg`): grid collapses to single column — candidate card → verification table → timeline stacked vertically
2. Timeline switches to a compact mode on mobile (smaller dots, tighter spacing)
3. Audio player remains full-width on mobile
4. Actions dropdown moves to a fixed bottom bar on mobile

#### B.7: URL Migration & Redirect
1. Route: `/checks-dashboard/cases/[ref]` where `ref` = case_reference (e.g., `AC-202603-00042`)
2. Redirect: old `/cases/[task_id]` → `/cases/[case_reference]` via Next.js middleware
3. `GET /api/v1/verifications/{task_id}` remains permanent (backend compatibility)

### Epic C: Terminology Alignment (Cross-cutting)

1. Create `utils/status_labels.py` — canonical StatusLabelMapper
2. CI script: `scripts/export_status_labels.py` generates `generated/statusLabels.ts`
3. CI gate: fail build if generated file is stale
4. Audit all frontend components: replace "unreachable" → "Unable to Verify"
5. Retire word "task" from all customer-facing UI (use "check" or "verification")

---

## 7. API Response Contract

### Case Detail (`GET /api/v1/cases/{case_reference}`)

```json
{
  "case_reference": "AC-202603-00042",
  "case_id": 97,
  "status": "in_progress",
  "status_label": "In Progress",
  "candidate_name": "John Doe",
  "employer_name": "Acme Corp",
  "check_type": "work_history",
  "created_at": "2026-03-01T10:00:00Z",
  "latest_employment_status": null,
  "sequence_progress": {
    "current_step": 3,
    "total_steps": 5,
    "current_step_label": "Second Retry"
  },
  "timeline": [
    {
      "step_order": 1,
      "step_name": "initial_call",
      "step_label": "Initial Call",
      "channel_type": "voice",
      "task_id": "uuid-1",
      "result_status": "voicemail_left",
      "result_label": "Voicemail Left",
      "attempted_at": "2026-03-01T10:05:00Z",
      "completed_at": "2026-03-01T10:08:00Z"
    },
    {
      "step_order": 2,
      "step_name": "first_retry",
      "step_label": "First Retry",
      "channel_type": "voice",
      "task_id": "uuid-2",
      "result_status": "no_answer",
      "result_label": "No Answer",
      "attempted_at": "2026-03-01T14:00:00Z",
      "completed_at": "2026-03-01T14:02:00Z"
    },
    {
      "step_order": 3,
      "step_name": "second_retry",
      "step_label": "Second Retry",
      "channel_type": "voice",
      "task_id": "uuid-3",
      "result_status": null,
      "result_label": "In Progress",
      "attempted_at": "2026-03-02T09:00:00Z",
      "completed_at": null
    },
    {
      "step_order": 4,
      "step_name": "third_retry",
      "step_label": "Third Retry",
      "channel_type": "voice",
      "task_id": null,
      "result_status": null,
      "result_label": "Pending",
      "attempted_at": null,
      "completed_at": null
    },
    {
      "step_order": 5,
      "step_name": "final_attempt",
      "step_label": "Final Attempt",
      "channel_type": "voice",
      "task_id": null,
      "result_status": null,
      "result_label": "Pending",
      "attempted_at": null,
      "completed_at": null
    }
  ],
  "verification_results": null
}
```

Note: `task_id` values appear in timeline entries but should be rendered only in a collapsible debug section in the UI — customers see step labels and results, not UUIDs.

---

## 8. Status Label Mapping (Canonical)

### CallResultStatus → Customer Label (backend-only mapping)

| CallResultStatus | Customer Label | Variant | Terminal |
| --- | --- | --- | --- |
| `completed` | Verified | success | true |
| `completed_discrepancies` | Partial Verification | warning | true |
| `refused` | Refused | error | true |
| `unable_to_verify` | Unable to Verify | neutral | true |
| `wrong_number` | Wrong Number | error | true |
| `max_retries_exceeded` | Max Retries Exceeded | error | true |
| `voicemail_left` | Voicemail Left | info | false |
| `no_answer` | No Answer | info | false |
| `busy` | Busy | info | false |
| `callback_requested` | Callback Requested | info | false |
| `manual_review` | Under Review | warning | false |
| `invalid_contact` | Invalid Contact | error | true |
| `aborted` | Aborted | neutral | true |
| `call_scheduled` | Scheduled | info | false |
| (null / in_progress) | In Progress | info | false |
| (pending) | Pending | neutral | false |

### Case Status → Customer Label

| Case Status | Customer Label | Variant |
| --- | --- | --- |
| `pending` | Pending | neutral |
| `in_progress` | In Progress | info |
| `verification_complete` | Verified | success |
| `requires_review` | Under Review | warning |
| `awaiting_callback` | Awaiting Callback | info |
| `verification_failed` | Failed | error |
| `verification_aborted` | Aborted | neutral |
| `billed` | Complete | success |
| `manual_resolved` | Resolved | success |

---

## 9. Dependencies

| Dependency | Status | Impact |
| --- | --- | --- |
| Epic 7 (Structured Interpretation) | APPROVED | CallResultStatus enum, status flow, case state machine |
| Epic F.6 (Terminology) | NOT STARTED | This PRD implements F.6's terminology goals for the dashboard |
| Check Sequence SLA (Migration 035/036/037) | COMPLETE | `background_check_sequence` table + `sequence_id`/`sequence_version` on background_tasks exist |
| Epic 2 (Case Workflow) | COMPLETE | `cases` table, `case_id` FK, `previous_task_id`/`next_task_id` chain |
| **Sequence Progression (Prefect flows)** | **NOT IMPLEMENTED** | Schema exists but no code advances `current_sequence_step` from 1→2→3. Retries stay within step 1. Email outreach (step 2) and automated escalation (step 3) never fire. **This PRD's timeline will show only step 1 with future steps as "Pending" until sequence progression is implemented as a separate epic.** |

### Note on `cases.check_type_id`

The `cases` table intentionally has no `check_type_id` FK. `case_type` (VARCHAR) is a business classification; `check_type_config_id` (INT FK to `check_types`) lives on `background_tasks` and is resolved at task dispatch time via string matching (`cases.case_type` → `check_types.name`). The timeline query resolves the sequence via the task's `check_type_config_id`, not the case directly.

---

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| PG sequence gaps on rollback | Certain | None | Gaps are cosmetic; references remain unique |
| Legacy tasks have NULL step_order | Certain | Low | Timeline gracefully handles NULL; backfill infers from created_at |
| Frontend/backend label drift | Medium | High | CI-generated statusLabels.ts with build gate |
| Bookmark breakage on URL change | Low | Low | Redirect `/cases/[task_id]` → `/cases/[ref]` |

---

## 11. Design Challenge Results

### Parallel Solutioning (7 Architects)

**Methodology**: 7 independent solution architects evaluated the design using different reasoning strategies (First Principles, Pattern Recognition, Systematic Decomposition, Reverse Engineering, Constraint Analysis, Probabilistic Reasoning, Creative Exploration).

**Verdict**: Unanimous MODIFY (0 approves as-is, 0 rejects, 7 modify)

**Key changes from original draft**:
1. ~~MAX+1 reference generation~~ → PG sequence (fix: race condition)
2. ~~4-digit NNNN~~ → 5-digit NNNNN with global counter (fix: month-reset ambiguity)
3. ~~Ordered stepper UI~~ → Vertical timeline with synthesized future steps
4. ~~Dual frontend/backend StatusLabelMapper~~ → Backend-only with CI-generated frontend
5. ~~Derive step position from task count~~ → Denormalize step_order on background_tasks
6. ~~4 epics~~ → 3 epics (MVP Sprint 1 scope)
7. Added: `latest_employment_status` denormalized on cases for list performance
8. Added: Explicit permanence guarantee for `/verifications/{task_id}` endpoint
9. Added: React Query cache keys use case_reference, terminal-aware polling

---

## 12. Future Enhancements (v2)

- Dedicated `case_events` table for full event sourcing (Architects 3, 7)
- AI-generated natural language case summaries (Architect 7)
- Dependency-graph view for non-linear workflows (Architect 6)
- Real-time WebSocket status updates
- CSV/PDF export of audit trail
