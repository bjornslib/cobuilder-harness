---
title: "PRD-SEQ-PROGRESSION-001: Check Sequence Progression Implementation"
status: draft
type: guide
grade: authoritative
last_verified: 2026-03-09T00:00:00.000Z
---
# PRD-SEQ-PROGRESSION-001: Check Sequence Progression Implementation

**Version**: 0.1.0
**Date**: 2026-03-09
**Status**: DRAFT — handover document for separate implementation
**Parent PRDs**: PRD-DASHBOARD-AUDIT-001 (Dashboard Audit Trail), Epic 7 Structured Interpretation PRD (v1.4)
**Target Repo**: zenagent3/zenagent/agencheck/agencheck-support-agent

---

## 1. Executive Summary

The AgenCheck check sequence progression mechanism is **not implemented**. The database schema (`background_check_sequence`, migrations 035/036/037) and Python models (`CheckSequenceResolution`, `ResolvedSequence`) are fully defined, but no Prefect flow code advances a case from step 1 to step 2 to step 3. Every case in production has exactly 1 `background_task` at `current_sequence_step=1`.

This means:
- **Email outreach (step 2) never fires** — non-terminal voice call results don't trigger the next step
- **Automated manual review escalation (step 3) never fires** — all escalation is manual
- All retries stay within step 1 (same-step voice call retries), never advancing the sequence

This PRD specifies the orchestration logic needed to advance the check sequence after each step completes.

---

## 2. Problem Statement

### Current Behavior (Broken)

```
Case Created → Step 1: Voice Call Attempt
                  ├── Verified → Case Complete ✅
                  ├── Retryable (no_answer, voicemail, busy) → Retry Step 1 (same step) ♻️
                  └── Non-terminal exhausted → Stuck / Manual intervention ❌
```

### Expected Behavior (After This PRD)

```
Case Created → Step 1: Voice Call Attempt (max_attempts=2)
                  ├── Verified → Case Complete ✅
                  ├── Retryable → Retry within Step 1 (up to max_attempts)
                  └── Step 1 exhausted → Wait delay_hours → Step 2: Email Outreach
                                              ├── Response received → Process result
                                              └── Step 2 exhausted → Step 3: Manual Review Escalation
                                                                        └── Create manual review queue entry
```

---

## 3. Live Data Evidence

### Production Database (Railway, queried 2026-03-09)

**Zero cases have multiple background\_tasks:**
```sql
SELECT case_id, COUNT(*) FROM background_tasks
WHERE case_id IS NOT NULL GROUP BY case_id HAVING COUNT(*) > 1;
-- (0 rows)
```

**All tasks are at step 1:**
```sql
SELECT DISTINCT current_sequence_step FROM background_tasks;
-- 1
```

**Active work\_history sequence (check\_type\_id=1, customer\_id=1, version=5):**

| step_order | step_name | delay_hours | max_attempts | channel_type |
| --- | --- | --- | --- | --- |
| 1 | Voice Call Attempt | 24.00 | 2 | voice |
| 2 | Email Outreach | 2.00 | 2 | voice |
| 3 | Manual Review Escalation | 0.00 | 1 | voice |

**Note**: `channel_type` is `voice` for all steps — likely a seed data issue. Step 2 (Email Outreach) should be `email`.

### Existing Columns Already on background_tasks

| Column | Type | Status | Purpose |
| --- | --- | --- | --- |
| `current_sequence_step` | INT | Always 1 | Which step in the sequence this task represents |
| `sequence_id` | INT FK | Populated since March 1 | Links to `background_check_sequence.id` |
| `sequence_version` | INT | Populated since March 1 | Denormalized version at task creation time |
| `check_type_config_id` | INT FK | Always populated | Links to `check_types.id` for SLA resolution |
| `previous_task_id` | UUID | NULL (never used) | Chain link to prior task in sequence |
| `next_task_id` | UUID | NULL (never used) | Chain link to next task in sequence |
| `attempt_timestamp` | TIMESTAMPTZ | Populated since March 1 | When Prefect flow submission occurred |

---

## 4. Root Cause Analysis

### Where the Gap Is

The Prefect flow `verification_orchestrator.py` handles post-call processing in `process_result.py`. When a call completes with a retryable result:

1. **`process_result.py`**** (lines 220-270)**: Creates a retry task via `create_retry_task()` — but this retries **within the same step**, not advancing to the next step
2. **`followup_scheduler.py`**: Called from `verification_orchestrator.py:303` — schedules follow-ups within step 1, never checks `background_check_sequence` for the next step
3. **`background_task_helpers.py:162-276`**: `create_retry_task()` creates a new task with `previous_task_id` link, but does NOT increment `current_sequence_step` or fetch the next sequence definition

### What Exists But Is Never Called

- `models/check_sequence.py`: Full data models (`CheckSequenceResolution`, `ResolvedSequence`) — defined but not used for progression
- `services/check_sequence_service.py` (~55KB): Complete service with `resolve_check_sequence()` — resolves the 3-tier sequence but is never called to get the NEXT step
- `api/routers/check_sequence.py`: REST endpoint for sequence resolution — exists for external queries but not used internally for progression

### Key Files

| File | Lines | Finding |
| --- | --- | --- |
| `api/routers/work_history.py` | ~315-330 | Creates initial task with `current_sequence_step=1` (only place it's set) |
| `prefect_flows/flows/tasks/process_result.py` | 220-270 | Creates retry tasks for SAME step, not next step |
| `prefect_flows/flows/tasks/followup_scheduler.py` | 1-126 | Schedules follow-ups within step 1 via `create_retry_task()` |
| `prefect_flows/flows/verification_orchestrator.py` | 303-327 | Calls `schedule_followup_task()`, then escalates directly to manual review |
| `utils/background_task_helpers.py` | 162-276 | `create_retry_task()` — no sequence progression |
| `models/check_sequence.py` | 1-540 | Data models defined but unused for progression |
| `services/check_sequence_service.py` | 1-55KB | Full service exists, never called for next-step logic |

---

## 5. Goals & Success Criteria

### G1: Sequence Step Advancement

When a step exhausts its `max_attempts` with non-terminal results, the system must automatically create the next step's task.

**Success Criteria**:
- [ ] After step 1 exhausts `max_attempts` (2), a step 2 task is created after `delay_hours` (2h)
- [ ] After step 2 exhausts `max_attempts` (2), a step 3 task is created after `delay_hours` (0h)
- [ ] `current_sequence_step` is correctly set on each new task (2, 3, etc.)
- [ ] `previous_task_id` links new task to the last task of the prior step
- [ ] `sequence_id` and `sequence_version` are set from the resolved sequence

### G2: 3-Tier Sequence Resolution

The correct sequence must be resolved per case using the existing 3-tier chain.

**Success Criteria**:
- [ ] Client-specific sequences override customer defaults
- [ ] Customer defaults override system fallback (customer_id=1)
- [ ] If no sequence found, fall back to single-step behavior (no crash)

### G3: Terminal Detection

The system must correctly identify when a sequence is complete (all steps exhausted or terminal result received).

**Success Criteria**:
- [ ] Terminal results at ANY step (verified, refused, unable_to_verify, etc.) → case complete, no further steps
- [ ] Non-terminal results at final step → case marked as `max_retries_exceeded` or escalated
- [ ] `next_task_id` is updated on the current task when next task is created

### G4: Delay Enforcement

Steps with `delay_hours > 0` must not execute immediately.

**Success Criteria**:
- [ ] Step 2 (delay_hours=2.0) creates a task scheduled 2 hours after step 1 completion
- [ ] Prefect scheduling respects the delay (either via `scheduled_start_time` or a separate scheduler)
- [ ] `attempt_timestamp` reflects the actual dispatch time, not creation time

---

## 6. Proposed Architecture

### Option A: Post-Completion Hook in process_result.py (Recommended)

Add sequence advancement logic to the existing `process_result.py` after it determines a step is exhausted:

```python
# In process_result.py, after determining step is exhausted:
async def advance_sequence(case_id: int, current_task: dict, db_pool):
    """Advance to next step in check sequence if available."""
    current_step = current_task['current_sequence_step']
    check_type_id = current_task['check_type_config_id']

    # Resolve sequence (3-tier)
    customer_id = await get_case_customer_id(case_id, db_pool)
    client_id = await get_case_client_id(case_id, db_pool)
    next_step = await get_next_sequence_step(
        check_type_id, customer_id, client_id, current_step + 1, db_pool
    )

    if next_step is None:
        # No more steps — mark case as terminal
        await mark_case_terminal(case_id, 'max_retries_exceeded', db_pool)
        return

    # Schedule next step task with delay
    scheduled_at = datetime.now(timezone.utc) + timedelta(hours=float(next_step['delay_hours']))
    await create_next_step_task(
        case_id=case_id,
        previous_task_id=current_task['task_id'],
        sequence_step=current_step + 1,
        sequence_id=next_step['id'],
        sequence_version=next_step['version'],
        check_type_config_id=check_type_id,
        scheduled_at=scheduled_at,
        channel_type=next_step['channel_type'],
        db_pool=db_pool,
    )
```

### Option B: Dedicated Prefect Flow (Alternative)

Create a separate `sequence_advancement_flow.py` that runs on a schedule, scanning for cases where the latest task is complete + non-terminal and no next task exists.

**Trade-offs**:
- Option A: Real-time advancement, simpler, but couples to existing flow
- Option B: Decoupled, but adds polling delay and a new flow to maintain

---

## 7. Scope

### In Scope

- Sequence progression logic (step 1 → 2 → 3)
- 3-tier sequence resolution for next step
- Delay enforcement via Prefect scheduling
- `previous_task_id` / `next_task_id` chain linking
- Terminal detection at any step
- Fix `channel_type` seed data (Email Outreach should be `email`, not `voice`)

### Out of Scope

- New check sequence types (only work_history for MVP)
- Dashboard UI changes (covered by PRD-DASHBOARD-AUDIT-001)
- Email outreach Prefect flow implementation (step 2 channel_type=email needs a new flow handler)
- Manual review queue UI (step 3 creates a queue entry, but the review UI is separate)

### Critical Dependency: Email Outreach Flow

Step 2 in the sequence is "Email Outreach" but there is **no Prefect flow that sends verification emails**. The current `voice_verification.py` flow only handles voice calls. Implementing sequence progression without an email flow means step 2 tasks will be created but cannot execute.

**Recommendation**: Implement email outreach flow as a parallel epic, or temporarily skip step 2 (voice → manual review directly) until the email flow exists.

---

## 8. Epics

### Epic A: Sequence Advancement Logic (Backend)

1. Add `advance_sequence()` function to `process_result.py` or `background_task_helpers.py`
2. Call `advance_sequence()` when a step's `max_attempts` are exhausted with non-terminal result
3. Use `check_sequence_service.resolve_check_sequence()` to find the next step (3-tier resolution)
4. Create next-step task with correct `current_sequence_step`, `sequence_id`, `sequence_version`, `delay_hours`
5. Update `next_task_id` on the exhausted task
6. Update `previous_task_id` on the new task

### Epic B: Delay Scheduling (Prefect)

1. Set `scheduled_start_time` on the new task's Prefect deployment based on `delay_hours`
2. Alternatively: create a `sequence_delay_scheduler` Prefect flow that polls for due tasks
3. Set `attempt_timestamp` when the task is actually dispatched (not when created)

### Epic C: Terminal Detection & Case Resolution

1. Add terminal result check at sequence advancement: if result is terminal (verified, refused, etc.), mark case complete
2. If final step exhausted with non-terminal result, mark case as `max_retries_exceeded`
3. Update `cases.status` via `update_case_status()` at each sequence transition

### Epic D: Seed Data Fix

1. Fix `channel_type` for step 2 (Email Outreach): should be `email`, not `voice`
2. Review and correct any other seed data inconsistencies
3. Consider adding a migration to fix existing rows

---

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Email outreach flow doesn't exist | Certain | High | Step 2 tasks created but can't execute. Skip step 2 or build email flow in parallel |
| Sequence version changes mid-case | Low | Medium | Use `sequence_version` from first task to determine remaining steps |
| Delay scheduling drift | Low | Low | Use Prefect's `scheduled_start_time`; acceptable to be minutes late |
| Existing retry logic conflicts | Medium | Medium | Ensure same-step retries and cross-step advancement don't duplicate tasks |

---

## 10. Testing Strategy

### Unit Tests
- Test `advance_sequence()` with mock DB: step 1→2, step 2→3, final step terminal
- Test 3-tier resolution: client override, customer default, system fallback
- Test terminal detection for all CallResultStatus values

### Integration Tests
- Create a case, complete step 1 with `no_answer`, verify step 2 task created
- Verify `delay_hours` respected (step 2 scheduled 2h after step 1 completion)
- Verify `previous_task_id`/`next_task_id` chain integrity
- Verify case status transitions: `in_progress` → `verification_complete` / `verification_failed`

### Manual Validation
- Run a full 3-step sequence in staging
- Verify dashboard timeline shows progression (requires PRD-DASHBOARD-AUDIT-001)

---

## 11. Handover Context

This PRD was created during the investigation phase of PRD-DASHBOARD-AUDIT-001 (Dashboard Audit Trail). The finding that sequence progression is unimplemented explains why the dashboard only ever shows step 1 — there's nothing to display beyond that.

**Key relationship**: PRD-DASHBOARD-AUDIT-001's timeline feature will show "Step 1 of 3" with steps 2-3 as "Pending" until this PRD is implemented. Once sequence progression works, the timeline automatically shows real progression without further frontend changes.

**Hindsight bank**: Findings stored in `system3-orchestrator` bank under context `design-decisions` (2026-03-09).

### Files to Start With

| File | Why |
| --- | --- |
| `prefect_flows/flows/tasks/process_result.py` | Entry point — add `advance_sequence()` call after step exhaustion |
| `services/check_sequence_service.py` | Already has `resolve_check_sequence()` — use it for next-step lookup |
| `utils/background_task_helpers.py` | Has `create_retry_task()` — extend or create `create_next_step_task()` |
| `models/check_sequence.py` | Data models for sequences — already complete |
| `prefect_flows/flows/verification_orchestrator.py` | Main orchestrator — may need to handle new channel types (email) |
