---
title: "SD-SEQ-RETRY-LOOP-001: Continuous Retry Loop Until Final Status"
status: active
type: reference
last_verified: 2026-03-10T00:00:00.000Z
---
# SD-SEQ-RETRY-LOOP-001: Continuous Retry Loop Until Final Status

**PRD Reference**: PRD-SEQ-PROGRESSION-001 (Extension)
**Status**: Draft
**Created**: 2026-03-10

## 1. Problem Statement

The current verification orchestrator is **fire-and-forget**: it dispatches one attempt per channel and returns `COMPLETED` regardless of whether the verification case is actually resolved. This means:

1. **No pre-dispatch status check**: The orchestrator never checks whether the `background_tasks.status` or `cases.status` is already terminal before dispatching. If a verifier completes the unified-form (clicks the email link, fills in the form), the case may already be `completed` — but the orchestrator will still fire off another email or voice call.

2. **Email sends succeed but aren't followed up**: When an email is sent (`email_sent` status), the orchestrator considers this "success" and stops. There's no mechanism to check if the recipient responded (via the unified-form link in the email) and retry if they didn't. According to research, the system currently treats `email_sent` as a terminal success, but it's actually non-terminal - the verification is only complete when the recipient responds via the unified-form.

3. **No re-entry loop**: After the orchestrator completes, nothing triggers the next attempt. The `advance_sequence()` function creates a new pending task in the DB, but:
  - The `run_deployment()` call uses the wrong deployment name (`"verification-orchestrator/default"` vs actual `"verification-orchestrator/verification-orchestrator"`)
  - The catch-up poller only picks up `call_attempt` action types, ignoring `email_attempt`

4. **Scheduled times are ignored**: The catch-up poller doesn't filter `scheduled_time <= NOW()`, meaning delayed tasks would fire immediately if picked up.

5. **Missing email template progression**: Research indicates that the system has three email templates (`email_first_contact`, `email_reminder_1`, `email_reminder_2`) that should be selected based on the attempt number (0 for first contact, 1 for first reminder, ≥2 for final reminder), but the template selection mechanism may not be properly utilized in the retry loop.

6. **No attempt tracking per sequence step**: The system doesn't properly track email attempts per sequence step, making it difficult to know when to advance to the next step in the sequence. The attempt counter should be used for both determining when to retry the same step and for selecting the appropriate email template.

## 2. Target Architecture

### 2.1 Core Principle

**The orchestrator must check case AND task status before every dispatch.** If either is terminal, stop immediately — the verifier may have already completed the check via the unified-form link in the email, or through a previous voice call.

Each invocation follows this pattern:
1. **GUARD**: Check `cases.status` AND `background_tasks.status` → if terminal, exit (no dispatch)
2. Dispatches the current step's channel
3. Evaluates the dispatch result
4. If non-terminal: schedules the NEXT retry/step as a new Prefect flow run with the correct delay
5. Returns — Prefect handles the scheduling

This is a **scheduled chain** pattern: each orchestrator invocation schedules the next one. The chain stops naturally when the case reaches a terminal state (either through the orchestrator's own dispatch results, or externally when a verifier completes the unified-form).

### 2.1.1 The Critical Guard: Why Both Statuses Matter

The guard must check BOTH:
- **`cases.status`**: Terminal when the verification is definitively resolved (verified, refused, cancelled). This can happen externally — a verifier clicks the email link, fills the unified-form, and the case is marked `completed` by the form submission endpoint.
- **`background_tasks.status`**: Terminal when the specific task is done (`completed`, `failed`). A task can complete while the case is still `in_progress` (e.g., voice call failed, but email step is next).

```python
# The guard query — single DB round-trip
task_and_case = await pool.fetchrow("""
    SELECT
        bt.status as task_status,
        bt.action_type,
        bt.current_sequence_step,
        bt.sequence_id,
        c.status as case_status
    FROM background_tasks bt
    JOIN cases c ON c.id = bt.case_id
    WHERE bt.id = $1 AND bt.case_id = $2
""", task_id, case_id)

TERMINAL_CASE_STATUSES = {'completed', 'cancelled', 'max_retries_exceeded'}
TERMINAL_TASK_STATUSES = {'completed', 'failed', 'cancelled'}

if task_and_case['case_status'] in TERMINAL_CASE_STATUSES:
    logger.info(f"Case {case_id} already terminal: {task_and_case['case_status']}")
    return {"status": "already_terminal", "reason": "case_resolved"}

if task_and_case['task_status'] in TERMINAL_TASK_STATUSES:
    logger.info(f"Task {task_id} already terminal: {task_and_case['task_status']}")
    return {"status": "already_terminal", "reason": "task_resolved"}
```

This guard is what makes the whole system safe:
- Verifier completes the unified-form → case status set to `completed` → next scheduled orchestrator invocation hits the guard → exits cleanly
- No wasted emails/calls after verification is already done

### 2.2 High-Level Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    VERIFICATION LIFECYCLE                                │
│                                                                         │
│  /verify API                                                            │
│      │                                                                  │
│      ▼                                                                  │
│  create_prefect_flow_run()  ─── Tier 1: Immediate dispatch              │
│      │                                                                  │
│      ▼                                                                  │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  verification_orchestrator_flow  (INVOCATION N)              │       │
│  │                                                              │       │
│  │  1. GUARD: Check case + task status                          │       │
│  │     ├─ case terminal (completed/cancelled)? → EXIT           │       │
│  │     │  (verifier may have completed unified-form)            │       │
│  │     └─ task terminal (completed/failed)? → EXIT              │       │
│  │  2. Load SLA config + sequence step                          │       │
│  │  3. Dispatch channel (voice/email/sms)                       │       │
│  │  4. Evaluate result:                                         │       │
│  │     ├─ TERMINAL (verified/refused/etc) → update case, EXIT   │       │
│  │     ├─ NON-TERMINAL (email_sent/no_answer/busy)              │       │
│  │     │   ├─ retries remaining → create retry task (attempt+1) │       │
│  │     │   │   → schedule next Prefect run at delay_hours       │       │
│  │     │   └─ step exhausted → advance_sequence() to next step  │       │
│  │     │       → schedule next Prefect run at next delay        │       │
│  │     └─ ALL STEPS EXHAUSTED → finalize as max_retries_exceeded│       │
│  │  5. Return result                                            │       │
│  └──────────────────┬───────────────────────────────────────────┘       │
│                     │                                                   │
│                     ▼                                                   │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  verification_orchestrator_flow  (INVOCATION N+1)            │       │
│  │  1. GUARD: case still in_progress? task still pending?       │       │
│  │     YES → dispatch next attempt                              │       │
│  │     NO  → EXIT (verifier completed form, or case cancelled)  │       │
│  └──────────────────────────────────────────────────────────────┘       │
│                     │                                                   │
│                     ▼                                                   │
│              (repeats until guard catches terminal status)               │
│                                                                         │
│  EXTERNAL EVENT: Verifier clicks email link → completes unified-form    │
│  → cases.status set to 'completed' by form submission endpoint          │
│  → next orchestrator invocation hits guard → exits cleanly              │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │  catch_up_poller (every minute) ── Tier 2: Safety net        │       │
│  │                                                              │       │
│  │  Finds pending tasks where:                                  │       │
│  │  - prefect_flow_run_id IS NULL                               │       │
│  │  - scheduled_time IS NULL OR scheduled_time <= NOW()         │       │
│  │  - status = 'pending'                                        │       │
│  │  - action_type IN (call_attempt, email_attempt, sms_attempt) │       │
│  │  Also checks case status before dispatching (same guard)     │       │
│  └──────────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.3 What Changes

| Component | Current Behavior | Target Behavior |
| --- | --- | --- |
| **Orchestrator** | Fire-and-forget. `email_sent` = success, exit. | Loop driver. After dispatch, evaluates result → schedules next invocation if non-terminal. |
| **Email result handling** | `email_sent` = success → orchestrator returns | `email_sent` = attempt made, non-terminal → schedule follow-up check at `delay_hours` with next email template (first_contact → reminder_1 → reminder_2 based on attempt number) |
| **Retry task creation** | Only in `process_result.py` for voice | Orchestrator creates retry tasks for ALL channels |
| **Next Prefect run scheduling** | `advance_sequence()` tries wrong deployment name | Orchestrator schedules directly with correct deployment name |
| **Catch-up poller** | Only `call_attempt`, no `scheduled_time` filter | All action types, respects `scheduled_time <= NOW()` |
| **`advance_sequence()`** | Self-contained, tries `run_deployment()` | Returns info only; orchestrator handles Prefect scheduling |
| **Case status** | Set to `completed` when email sent | Stays `in_progress` until terminal result |
| **Email Template Selection** | Fixed template per step | Template varies based on attempt number: `email_first_contact` (attempt 0), `email_reminder_1` (attempt 1), `email_reminder_2` (attempt ≥2) |

### 2.4 Terminal vs Non-Terminal Results

| Result | Terminal? | Next Action |
| --- | --- | --- |
| `verified`, `confirmed` | YES | Close case as completed |
| `refused`, `not_employed`, `company_closed` | YES | Close case as completed (negative) |
| `invalid_contact` | YES | Close case, flag for review |
| `email_sent` | NO | Schedule follow-up at delay_hours with next template (first_contact → reminder_1 → reminder_2 based on attempt number) |
| `no_answer`, `busy`, `voicemail_left` | NO | Retry same step if attempts remain |
| `callback_requested` | NO | Retry same step at requested time |
| `max_retries_exceeded` (all steps exhausted) | YES | Close case as max_retries_exceeded |
| `not_implemented` (sms/whatsapp placeholder) | Treat as FAIL | Advance to next step or escalate |

According to research, the email template selection logic should work as follows:
- `attempt == 0`: Uses "email_first_contact" template - Professional first contact with verification details
- `attempt == 1`: Uses "email_reminder_1" template - Follow-up message after initial contact
- `attempt >= 2`: Uses "email_reminder_2" template - Final notice with deadline

### 2.5 Orchestrator Rewrite: Scheduling Chain Pattern

The orchestrator becomes a **guard-first, single-attempt dispatcher** that schedules the next invocation when non-terminal:

```python
async def verification_orchestrator_flow(case_id, customer_id, task_id, check_type, ...):
    pool = await get_db_pool()

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 0: THE CRITICAL GUARD — check BOTH case and task status
    # This is what stops the chain when a verifier completes the
    # unified-form, or when a previous invocation already resolved things.
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    guard = await pool.fetchrow("""
        SELECT bt.status as task_status, c.status as case_status,
               bt.action_type, bt.current_sequence_step, bt.sequence_id
        FROM background_tasks bt
        JOIN cases c ON c.id = bt.case_id
        WHERE bt.id = $1 AND bt.case_id = $2
    """, task_id, case_id)

    TERMINAL_CASE = {'completed', 'cancelled', 'max_retries_exceeded'}
    TERMINAL_TASK = {'completed', 'failed', 'cancelled'}

    if guard['case_status'] in TERMINAL_CASE:
        logger.info(f"Guard: case {case_id} already {guard['case_status']}, skipping")
        # Mark this task as cancelled (no longer needed)
        await pool.execute(
            "UPDATE background_tasks SET status='cancelled' WHERE id=$1 AND status='pending'",
            task_id)
        return {"status": "already_terminal", "reason": f"case_{guard['case_status']}"}

    if guard['task_status'] in TERMINAL_TASK:
        logger.info(f"Guard: task {task_id} already {guard['task_status']}, skipping")
        return {"status": "already_terminal", "reason": f"task_{guard['task_status']}"}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 1: Mark task as processing
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    await pool.execute(
        "UPDATE background_tasks SET status='processing', started_at=NOW() WHERE id=$1",
        task_id)

    # STEP 2: Load SLA config + resolve channel from sequence step
    # ... (existing logic) ...

    # STEP 3: Dispatch channel (voice/email/sms)
    result = await dispatch_channel_verification(channel, ...)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 4: EVALUATE — is the dispatch result terminal?
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    TERMINAL_RESULTS = {'verified', 'confirmed', 'refused', 'not_employed',
                        'company_closed', 'invalid_contact'}
    # email_sent is explicitly NOT terminal — verifier hasn't responded yet
    NON_TERMINAL = {'email_sent', 'no_answer', 'busy', 'voicemail_left',
                    'callback_requested', 'not_implemented'}

    result_status = result.get('status', 'failed')

    if result_status in TERMINAL_RESULTS or is_terminal_from_voice(result):
        await finalize_case(case_id, result)
        await mark_task_completed(task_id, result)
        return {"status": "completed", ...}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STEP 5: NON-TERMINAL — mark current task done, schedule next
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    await mark_task_completed(task_id, result)  # this attempt is done

    # Count attempts for this step
    attempt_count = await count_step_attempts(case_id, guard['current_sequence_step'])
    step_config = await get_step_config(guard['sequence_id'])

    if attempt_count < step_config['max_attempts']:
        # Same step, next attempt — create retry task + schedule
        next_task_id = await create_retry_task_for_step(
            case_id, customer_id, task_id, step_config,
            attempt_number=attempt_count)
        flow_run_id = await schedule_next_orchestrator_run(
            case_id, customer_id, next_task_id, check_type,
            delay_hours=step_config['delay_hours'])
        logger.info(f"Retry scheduled: task {next_task_id}, run {flow_run_id}, "
                     f"delay {step_config['delay_hours']}h")
    else:
        # Step exhausted — advance to next step in sequence
        advancement = await advance_sequence(case_id, task_id, result_status, pool)
        if advancement['advanced']:
            flow_run_id = await schedule_next_orchestrator_run(
                case_id, customer_id, advancement['next_task_id'], check_type,
                delay_hours=advancement['delay_hours'])
            logger.info(f"Advanced to {advancement['next_step_name']}, "
                         f"task {advancement['next_task_id']}, delay {advancement['delay_hours']}h")
        else:
            # All steps exhausted — terminal
            await finalize_case(case_id, "max_retries_exceeded")

    return {"status": "retry_scheduled", ...}
```

### 2.6 Catch-Up Poller Fix

```sql
-- Current (broken):
WHERE bt.status = 'pending'
  AND bt.prefect_flow_run_id IS NULL
  AND bt.action_type = 'call_attempt'

-- Fixed:
WHERE bt.status = 'pending'
  AND bt.prefect_flow_run_id IS NULL
  AND bt.action_type IN ('call_attempt', 'email_attempt', 'sms_attempt', 'whatsapp_attempt')
  AND (bt.scheduled_time IS NULL OR bt.scheduled_time <= NOW())
```

### 2.7 Schedule Helper Function

A new helper to be used by both the orchestrator and advance_sequence:

```python
async def schedule_next_orchestrator_run(
    case_id: int,
    customer_id: int,
    task_id: int,
    check_type: str,
    delay_hours: float,
    sequence_id: int | None = None,
    sequence_version: int | None = None,
) -> str | None:
    """Schedule the next verification-orchestrator Prefect flow run.

    Uses the correct deployment name and Scheduled state.
    Updates background_tasks.prefect_flow_run_id for the target task.
    Returns flow_run_id or None if scheduling fails.
    """
    scheduled_time = datetime.now(UTC) + timedelta(hours=delay_hours)
    deployment_name = "verification-orchestrator/verification-orchestrator"

    async with get_client() as client:
        deployment = await client.read_deployment_by_name(deployment_name)
        flow_run = await client.create_flow_run_from_deployment(
            deployment.id,
            parameters={
                "case_id": case_id,
                "customer_id": customer_id,
                "task_id": task_id,
                "check_type": check_type,
                "sequence_id": str(sequence_id) if sequence_id else None,
                "sequence_version": sequence_version,
            },
            state=Scheduled(scheduled_time=scheduled_time),
        )

    # Link Prefect run to task
    pool = await get_db_pool()
    await pool.execute("""
        UPDATE background_tasks
        SET prefect_flow_run_id = $1,
            prefect_scheduled_start = $2
        WHERE id = $3
    """, flow_run.id, scheduled_time, task_id)

    return str(flow_run.id)
```

## 3. Epics

### Epic A: Orchestrator Retry Loop (Core)
**Files**: `prefect_flows/flows/verification_orchestrator.py`, `prefect_flows/hooks/state_hooks.py`, new `prefect_flows/flows/flow_helpers/scheduling.py`

**PREREQUISITE — Fix task status lifecycle**: The `log_state_to_db` hook currently only updates `background_tasks.status` on `Completed` and `Failed/Crashed`. There is **no ****`Running`**** → ****`processing`**** transition** — tasks jump from `pending` directly to `completed`/`failed`. The guard depends on seeing `processing` to know a flow is actively running. Fix:

Add to `log_state_to_db` in `state_hooks.py` (alongside the existing `Failed`/`Completed` blocks):
```python
elif state_name in ("Running", "RUNNING"):
    try:
        await conn.execute("""
            UPDATE background_tasks
            SET status = 'processing',
                started_at = NOW()
            WHERE id = $1 AND status = 'pending'
        """, task_id)
    except Exception as bg_err:
        logger.error(f"Failed to update background_task {task_id} on running: {bg_err}")
```

This gives us a clean lifecycle: `pending → processing → completed | failed`

**Task status values after this fix:**

| Status | Meaning | Guard action |
| --- | --- | --- |
| `pending` | Waiting for Prefect to pick up | Safe to dispatch |
| `processing` | Flow is actively running | Do NOT dispatch (already in progress) |
| `completed` | Attempt finished | Terminal — skip |
| `failed` | Flow crashed or errored | Terminal — skip |
| `cancelled` | Manually cancelled or case resolved externally | Terminal — skip |

**Implementation steps:**

1. Add `Running` → `processing` update to `log_state_to_db` hook (prerequisite for guard)
2. Add **terminal status guard** as the first action (check both `cases.status` AND `background_tasks.status`)
3. If case is terminal (verifier completed unified-form, case cancelled, etc.) → cancel pending task, return immediately
4. If task is already `processing`/`completed`/`failed` → return immediately (duplicate invocation guard)
5. Remove `email_sent` from success status list — treat as non-terminal
6. After dispatch, count step attempts and either:
  - Create retry task (same step, next attempt) + schedule Prefect run
  - Or call `advance_sequence()` + schedule Prefect run for next step
7. Add `schedule_next_orchestrator_run()` helper with correct deployment name
8. Mark current task as `completed` after dispatch (the *attempt* is done; the *case* continues)

### Epic B: Catch-Up Poller Fix
**Files**: `prefect_flows/flows/catch_up_poller.py`

1. Expand `action_type` filter: `IN ('call_attempt', 'email_attempt', 'sms_attempt', 'whatsapp_attempt')`
2. Add `scheduled_time` guard: `AND (bt.scheduled_time IS NULL OR bt.scheduled_time <= NOW())`
3. Add case status check before dispatching (same guard pattern — don't dispatch if case already terminal)
4. Add logging for action_type distribution found

### Epic C: Fix advance_sequence() Scheduling
**Files**: `prefect_flows/flows/tasks/sequence_advancement.py`

1. Fix deployment name: `"verification-orchestrator/default"` → `"verification-orchestrator/verification-orchestrator"`
2. Return `delay_hours` from the resolved next step so the orchestrator can use it for scheduling
3. Remove direct Prefect scheduling from `advance_sequence()` — let the orchestrator handle it (single responsibility)

### Epic D: Email Retry Context & Template Progression
**Files**: `prefect_flows/flows/tasks/channel_dispatch.py`, `prefect_flows/templates/work_history/`

Research indicates the email system has three templates with specific subject lines and purposes:
- `email_first_contact.txt`: "Employment Verification Request – {candidate_name}" - Professional first contact with verification details
- `email_reminder_1.txt`: "Reminder – Employment Verification Request for {candidate_name}" - Follow-up message after initial contact
- `email_reminder_2.txt`: "Final Follow-Up – Employment Verification for {candidate_name}" - Final notice with 48-hour deadline

The template selection should be based on the attempt number from the retry task's context:
1. Ensure retry tasks carry `context_data` with `employer.contact_email` (the email recipient)
2. Track `attempt_number` in context_data for template selection (`email_first_contact` → `email_reminder_1` → `email_reminder_2`)
3. Pass `attempt` from the retry task's context to `_dispatch_email_verification` so the correct template is used
4. Template selection logic: `attempt == 0` → `email_first_contact`, `attempt == 1` → `email_reminder_1`, `attempt >= 2` → `email_reminder_2`
5. Email results: `email_sent` = dispatch succeeded but verification not complete; verifier needs to click link and fill unified-form
6. Template variables provided include: `employer_name`, `candidate_name`, `contact_name`, `verifier_name`, `company_name`, `case_id`, `callback_number`, `position_title`, `employment_start`, `employment_end`

## 4. Risks and Considerations

1. **Infinite loop prevention**: The guard + `max_attempts` per step + finite sequence steps provides a natural ceiling. As an extra safety net, add a hard limit on total tasks per case (e.g., 20) and case age (e.g., 30 days).

2. **Race condition: unified-form completion vs next dispatch**: A verifier may complete the unified-form at the exact moment the orchestrator is about to dispatch. The guard runs BEFORE dispatch, so if the form submission sets `cases.status = 'completed'` first, the orchestrator will see it and exit. If the dispatch races ahead, the next invocation will catch it. Worst case: one extra email/call after the verifier already responded — acceptable.

3. **Backward compatibility**: Existing completed cases have `cases.status = 'completed'`. The guard will correctly skip them. No re-triggering risk.

4. **Prefect flow run accumulation**: Each retry creates a new flow run. This is by design — Prefect flow runs are lightweight. The catch-up poller's `FOR UPDATE SKIP LOCKED` prevents duplicates.

5. **Email template progression**: The `attempt_number` must be tracked per-step (not globally). When sequence advances to a new step, the attempt counter resets to 0, selecting `email_first_contact` again (appropriate for a new step). The template progression follows the pattern: `email_first_contact` for attempt 0, `email_reminder_1` for attempt 1, and `email_reminder_2` for attempt 2 or greater.

6. **Context data loading**: The system loads context data from the `background_tasks.context_data` field. Email recipient extraction follows this priority: `context.get("to_email")` → `context.get("hr_email")` → `(context.get("employer", {}) or {}).get("contact_email")`.

## 5. File Change Summary

| File | Change Type | Description |
| --- | --- | --- |
| `verification_orchestrator.py` | **Major rewrite** | Guard-first pattern, scheduling chain, email_sent non-terminal |
| `flow_helpers/scheduling.py` | **New file** | `schedule_next_orchestrator_run()` helper |
| `catch_up_poller.py` | **Fix** | All action_types, scheduled_time guard, case status check |
| `sequence_advancement.py` | **Fix** | Correct deployment name, return delay_hours, remove direct scheduling |
| `channel_dispatch.py` | **Enhancement** | Attempt-based template selection, context_data carryover |
