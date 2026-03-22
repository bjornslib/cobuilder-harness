---
title: "SD-SEQ-PERSTEP-TASKS-001: Per-Step Background Task Creation for Audit Trail"
status: draft
type: reference
grade: authoritative
last_verified: 2026-03-11
---

# SD-SEQ-PERSTEP-TASKS-001: Per-Step Background Task Creation for Audit Trail

**PRD**: PRD-SEQ-PROGRESSION-001 (Epic E), PRD-DASHBOARD-AUDIT-001 (Epic A prerequisite)
**Parent SDs**: SD-SEQ-PROGRESSION-001 (advance_sequence), SD-SEQ-RETRY-LOOP-001 (guard + retry loop)
**Target Repo**: my-org/my-project/my-project-backend
**Estimated Effort**: ~2 days

---

## 1. Problem Statement

### What Exists

The Prefect `verification_orchestrator.py` resolves all sequence steps at flow start and iterates them **in-memory** via `asyncio.sleep(delay_hours)`. A `background_tasks` row is only written in two scenarios:

1. **Retryable call result** (`process_result.py:235`) — same-step retry via `create_retry_task()`
2. **All steps exhausted** (`followup_scheduler.py:81`) — escalation to manual review

The `advance_sequence()` function in `sequence_advancement.py` (SD-SEQ-PROGRESSION-001) creates next-step tasks with proper chaining, but it is called **after** a step's result is processed — it does not create a task row at the **start** of each step.

### What's Missing

Every sequence step needs its own `background_tasks` row **from the moment the step begins** — not just when it completes or fails. Without this:

- The dashboard timeline has no data for in-progress steps
- The audit trail is incomplete (shows only completed/failed tasks, not "Step 2: In Progress")
- Subsequent dispatches (voice calls, emails) reference the WRONG task_id — they use the previous step's task instead of a task that represents the current step

### The Core Requirement

After confirming (via `asyncio.sleep(delay_hours)`) that a case is **not yet done**, the orchestrator must:

1. **INSERT** a new `background_tasks` row for the next step with `status='in_progress'`
2. **Use that new task_id** for all subsequent dispatches (voice, email, SMS) in that step
3. **Chain** the new task to the previous step via `previous_task_id`/`next_task_id` (new columns, see Migration 052)
4. **Never reuse** the previous step's task_id for a different step's dispatches

### Database Change Summary

This SD requires **one database migration** (052_add_task_chain_columns.sql) to add the task chaining columns:
- `previous_task_id` (INTEGER, nullable FK to prior step)
- `next_task_id` (INTEGER, nullable FK to next step)

---

## 2. Architecture Overview

### Current Flow (Broken Audit Trail)

```
verification_orchestrator_flow(task_id=STEP1_TASK)
  → Resolve all sequence steps at start
  → Step 1: dispatch_voice(task_id=STEP1_TASK)
      → process_result → retryable? → create_retry_task (same step, new task)
      → step exhausted?
          → asyncio.sleep(delay_hours)    ← IN-MEMORY, no DB row for step 2
          → Step 2: dispatch_email(task_id=STEP1_TASK)  ← WRONG task_id!
              → step exhausted?
                  → Step 3: escalate(task_id=STEP1_TASK) ← WRONG task_id!
```

**Problems**:
- Steps 2 and 3 use Step 1's task_id in dispatches (emails, voice calls reference wrong task)
- No `background_tasks` row exists for step 2 until it completes/fails
- Dashboard query `SELECT * FROM background_tasks WHERE case_id = ?` returns only step 1 data

### Target Flow (Per-Step Task Creation)

```
verification_orchestrator_flow(task_id=STEP1_TASK)
  → Step 1: dispatch_voice(task_id=STEP1_TASK)
      → process_result → retryable? → create_retry_task (same step)
      → step exhausted?
          → asyncio.sleep(delay_hours)
          → GUARD: case still not done? (check cases.status)
              → YES: create_next_step_task() → STEP2_TASK
                     → dispatch_email(task_id=STEP2_TASK)  ← CORRECT task_id!
              → NO: case resolved externally → exit cleanly
          → step 2 exhausted?
              → create_next_step_task() → STEP3_TASK
                     → escalate(task_id=STEP3_TASK)  ← CORRECT task_id!
```

**Fixes**:
- Each step gets its own `background_tasks` row at the START of that step
- All dispatches use the CURRENT step's task_id
- Dashboard queries return one row per step, enabling full timeline display

---

## 3. Component Design

### 3.1 New Function: `create_step_task()`

**Location**: `utils/background_task_helpers.py` (extends existing module)

**PREREQUISITE**: Migration `052_add_task_chain_columns.sql` must be applied first to add `previous_task_id` and `next_task_id` columns.

This function creates a `background_tasks` row for a step that is **about to begin**, before any dispatch occurs. It differs from `advance_sequence()` (which is a post-completion hook) by being a pre-dispatch initialization.

```python
async def create_step_task(
    case_id: int,
    customer_id: int,
    step: dict,          # From resolved sequence: step_order, step_name, channel_type, max_attempts
    sequence_id: int,
    sequence_version: int,
    check_type_config_id: int,
    previous_task_id: int | None,  # INTEGER PK from background_tasks.id of prior step (None for step 1)
    db_pool,
) -> int:
    """Create a background_tasks row for a step that is about to begin.

    Called BEFORE dispatching the step's channel (voice/email/SMS).
    The returned task_id MUST be used for all dispatches in this step.

    PREREQUISITE: Migration 052 (previous_task_id, next_task_id columns) must be applied.

    Returns:
        int: The new task_id (background_tasks.id, INTEGER primary key)
    """
    # Map channel_type to action_type
    channel_to_action = {
        'voice': 'call_attempt',
        'email': 'email_attempt',
        'sms': 'sms_attempt',
        'whatsapp': 'whatsapp_attempt',
    }
    action_type = channel_to_action.get(step['channel_type'] or 'voice', 'call_attempt')

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # INSERT the new step task
            new_task_id = await conn.fetchval("""
                INSERT INTO background_tasks (
                    case_id,
                    customer_id,
                    action_type,
                    status,
                    current_sequence_step,
                    sequence_id,
                    sequence_version,
                    check_type_config_id,
                    previous_task_id,
                    retry_count,
                    max_retries,
                    context_data,
                    created_at,
                    attempt_timestamp
                ) VALUES (
                    $1, $2, $3, 'in_progress', $4, $5, $6, $7, $8,
                    0, $9, $10::jsonb, NOW(), NOW()
                )
                RETURNING id
            """,
                case_id,
                customer_id,
                action_type,
                step['step_order'],
                sequence_id,
                sequence_version,
                check_type_config_id,
                previous_task_id,
                step['max_attempts'],
                json.dumps({
                    "step_name": step['step_name'],
                    "channel_type": step['channel_type'],
                }),
            )

            # Chain: update previous task's next_task_id
            if previous_task_id is not None:
                # previous_task_id is the INTEGER PK from background_tasks.id
                await conn.execute("""
                    UPDATE background_tasks
                    SET next_task_id = $1
                    WHERE id = $2
                """, new_task_id, previous_task_id)

    return new_task_id
```

**Key differences from `advance_sequence()`**:

| Aspect | `advance_sequence()` | `create_step_task()` |
|--------|---------------------|---------------------|
| **When called** | After step completes/fails | Before step dispatch begins |
| **Initial status** | `pending` (scheduled for later) | `in_progress` (dispatching now) |
| **Delay handling** | Sets `scheduled_time` in future | No delay — step is starting now |
| **Prefect scheduling** | Submits scheduled flow run | Not needed — already in the flow |
| **Purpose** | Cross-step advancement after result evaluation | Pre-dispatch record creation for audit trail |

**Relationship**: In the fully integrated flow, the orchestrator uses `create_step_task()` to create the row at step start, then `advance_sequence()` handles the post-completion advancement logic. For step 1, the task already exists (created by the API at case submission). For steps 2+, `create_step_task()` creates the row before dispatch.

### 3.2 Integration: `verification_orchestrator.py` Step Loop

**Current pattern** (in-memory iteration, simplified):

```python
async def verification_orchestrator_flow(task_id, case_id, ...):
    # Resolve all steps at start
    steps = await resolve_check_sequence(check_type_id, customer_id, client_id)

    for i, step in enumerate(steps):
        if i > 0:
            # Wait between steps
            await asyncio.sleep(step['delay_hours'] * 3600)

        # Dispatch using ORIGINAL task_id (WRONG for steps 2+)
        result = await dispatch_channel(task_id=task_id, channel=step['channel_type'], ...)
        # ... process result ...
```

**Target pattern** (per-step task creation):

```python
async def verification_orchestrator_flow(task_id, case_id, customer_id, ...):
    """Orchestrate verification across sequence steps.

    CRITICAL: Each step gets its own background_tasks row.
    The task_id passed to dispatches MUST be the current step's task.
    """
    # Resolve all steps at start
    steps = await resolve_check_sequence(check_type_id, customer_id, client_id)
    current_task_id = task_id  # Step 1 task already exists (created at case submission)
    previous_task_id = None

    for i, step in enumerate(steps):
        # ── Guard: is case already resolved? ──
        case_status = await get_case_status(case_id, db_pool)
        if case_status in TERMINAL_CASE_STATUSES:
            logger.info(f"Case {case_id} already resolved ({case_status}), stopping sequence")
            return {"status": "already_terminal", "stopped_at_step": i + 1}

        # ── Wait between steps (skip for step 1) ──
        if i > 0 and step['delay_hours'] > 0:
            delay_seconds = step['delay_hours'] * 3600
            logger.info(f"Waiting {step['delay_hours']}h before step {step['step_order']}")
            await asyncio.sleep(delay_seconds)

            # Re-check after sleep: case may have been resolved externally
            case_status = await get_case_status(case_id, db_pool)
            if case_status in TERMINAL_CASE_STATUSES:
                logger.info(f"Case {case_id} resolved during delay, stopping")
                return {"status": "resolved_during_delay", "stopped_at_step": i + 1}

        # ── Create task for this step (step 1 already exists) ──
        if i > 0:
            current_task_id = await create_step_task(
                case_id=case_id,
                customer_id=customer_id,
                step=step,
                sequence_id=step['sequence_id'],
                sequence_version=step['version'],
                check_type_config_id=check_type_config_id,
                previous_task_id=previous_task_id,
                db_pool=db_pool,
            )
            logger.info(
                f"Created step {step['step_order']} task {current_task_id} "
                f"for case {case_id} (channel: {step['channel_type']})"
            )

        # ── Dispatch using CURRENT step's task_id ──
        result = await dispatch_channel_verification(
            channel=step['channel_type'],
            case_id=case_id,
            customer_id=customer_id,
            task_id=current_task_id,  # ← THIS is the critical fix
            check_type=check_type,
            retry_config=retry_config,
        )

        # ── Process result ──
        step_outcome = await process_and_retry_within_step(
            case_id=case_id,
            task_id=current_task_id,  # ← Use current step's task
            result=result,
            step=step,
            db_pool=db_pool,
        )

        # Terminal result at any step → stop sequence
        if step_outcome['is_terminal']:
            return {"status": "terminal", "result": step_outcome, "step": step['step_order']}

        # Step exhausted (all attempts used, non-terminal) → continue to next step
        if step_outcome['is_exhausted']:
            previous_task_id = current_task_id
            continue

        # Step still has retries → stay in this step (handled by process_and_retry)
        # This shouldn't reach here — process_and_retry handles within-step retries
        previous_task_id = current_task_id

    # All steps exhausted
    await mark_case_terminal(case_id, 'max_retries_exceeded', db_pool)
    return {"status": "all_steps_exhausted", "total_steps": len(steps)}
```

### 3.3 Task ID Handoff in Dispatch Functions

All dispatch functions MUST receive and use the current step's `task_id`:

#### Voice Dispatch

```python
# voice_verification.py — already accepts task_id
async def voice_verification_flow(task_id: int, case_id: int, ...):
    # task_id is now the CURRENT step's task (not step 1's task)
    # Used in: Vapi call metadata, call_log entries, result recording
    pass
```

#### Email Dispatch

```python
# email_dispatch.py — must use current step's task_id
async def send_verification_email(task_id: int, case_id: int, ...):
    # task_id is the CURRENT step's task
    # Used in: email template (links back to this specific task)
    # The unified-form link embeds this task_id so responses are tracked correctly
    email_body = render_template(
        template_name=get_email_template(attempt_number),
        task_id=task_id,  # ← MUST be current step, not step 1
        verification_link=f"{BASE_URL}/verify/{task_id}",
        ...
    )
```

**Critical**: Email templates include a verification link (`/verify/{task_id}`). If the wrong task_id is used, the verifier's response (via unified-form) gets linked to the wrong step, breaking the audit trail and potentially causing duplicate dispatches.

### 3.4 Relationship to `advance_sequence()` (SD-SEQ-PROGRESSION-001)

**Note**: The `advance_sequence()` function (SD-SEQ-PROGRESSION-001) handles post-completion step advancement. With per-step task creation via `create_step_task()`:

1. **In-flow steps**: The orchestrator uses `create_step_task()` for pre-dispatch task creation (what this SD covers)
2. **Fallback/external paths**: `advance_sequence()` handles catch-up scheduling if the orchestrator crashes mid-sequence, or when step completion comes from external triggers (e.g., webhook callback from email response)
3. **Migration dependency**: `advance_sequence()` must also use migration 052's `previous_task_id`/`next_task_id` columns

**Integration rule**: The orchestrator uses `create_step_task()` for pre-dispatch task creation. `advance_sequence()` is the fallback/external path. Both write the same columns and chain via `previous_task_id`/`next_task_id` (migration 052), so they are compatible.

---

## 4. Database Impact

### Database Migration Required

**Critical Finding from Research**: The `previous_task_id` and `next_task_id` columns **DO NOT EXIST** in the current database schema. Migration 037 (which added `sequence_id`, `sequence_version`, `attempt_timestamp`) did not add task chaining columns.\n\nA new migration `052_add_task_chain_columns.sql` is required to add these columns.

**Migration File**: `database/migrations/052_add_task_chain_columns.sql`

```sql
BEGIN;

DO $$
BEGIN
    -- previous_task_id: chain to prior step's task (NULL for step 1)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'background_tasks' AND column_name = 'previous_task_id'
    ) THEN
        ALTER TABLE background_tasks
            ADD COLUMN previous_task_id INTEGER
                REFERENCES background_tasks(id) ON DELETE SET NULL;

        COMMENT ON COLUMN background_tasks.previous_task_id IS
            'FK to background_tasks.id of the prior step in this verification sequence. '
            'NULL for the first step. Enables audit trail traversal from any step.';
    END IF;
END $$;

DO $$
BEGIN
    -- next_task_id: chain to next step's task (updated when next task is created)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'background_tasks' AND column_name = 'next_task_id'
    ) THEN
        ALTER TABLE background_tasks
            ADD COLUMN next_task_id INTEGER
                REFERENCES background_tasks(id) ON DELETE SET NULL;

        COMMENT ON COLUMN background_tasks.next_task_id IS
            'FK to background_tasks.id of the next step in this verification sequence. '
            'Updated when that step creates its task. Enables audit trail bidirectional traversal.';
    END IF;
END $$;

-- Index for forward/backward chain traversal
CREATE INDEX IF NOT EXISTS idx_background_tasks_previous_task_id
    ON background_tasks (previous_task_id)
    WHERE previous_task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_background_tasks_next_task_id
    ON background_tasks (next_task_id)
    WHERE next_task_id IS NOT NULL;

COMMIT;
```

### Existing Columns (From Migrations 035, 036, 037)

The following columns already exist and will be used by this SD:

| Column | Type | Current Status | This SD's Usage |
|--------|------|---------------|-----------------|
| `current_sequence_step` | INT | Present (M035) | Set to step_order (1, 2, 3, ...) |
| `sequence_id` | INT FK | Present (M037) | Set from resolved sequence |
| `sequence_version` | INT | Present (M037) | Set from resolved sequence |
| `check_type_config_id` | INT FK | Present (M035) | Carried from case |
| `customer_id` | INT | Present (M036) | Carried from case |
| `attempt_timestamp` | TIMESTAMPTZ | Present (M037) | Set to NOW() at step start |
| `context_data` | JSONB | Present | Stores `step_name`, `channel_type` |
| `retry_count` | INT | Present | Set to 0 for new step tasks |
| `max_retries` | INT | Present | From `step.max_attempts` |
| `status` | VARCHAR | Present | `'in_progress'` for new step tasks |
| `action_type` | VARCHAR | Present | Set from `step.channel_type` |

### Missing: Task Chaining Columns

The following columns must be added via migration 052:

| Column | Type | Description |
|--------|------|-------------|
| `previous_task_id` | INTEGER | FK to prior step's task (NULL for step 1) |
| `next_task_id` | INTEGER | FK to next step's task (updated when next task created) |

**Important**: The SD's `create_step_task()` function uses INTEGER PKs, not UUIDs. The `task_id` column (UUID) exists for Prefect flow correlation but is separate from the integer PK (`id`) used for task chaining.

### Expected Data After Implementation

For a 3-step sequence on case_id=97:

```sql
SELECT id, case_id, current_sequence_step, action_type, status,
       previous_task_id, next_task_id, context_data->>'step_name'
FROM background_tasks
WHERE case_id = 97
ORDER BY current_sequence_step;
```

| id | case_id | step | action_type | status | prev_task | next_task | step_name |
|----|---------|------|-------------|--------|-----------|-----------|-----------|
| 401 | 97 | 1 | call_attempt | completed | NULL | 402 | Voice Call Attempt |
| 402 | 97 | 2 | email_attempt | in_progress | 401 | NULL | Email Outreach |

(Step 3 row doesn't exist yet — will be created when step 2 exhausts)

### Dashboard Query (Enabled by This SD)

The case detail API (`GET /api/v1/cases/{case_id}`) from PRD-DASHBOARD-AUDIT-001 can now query:

```sql
-- Completed + in-progress steps (from background_tasks)
SELECT
    bt.current_sequence_step as step_order,
    bcs.step_name,
    bcs.channel_type,
    bt.id as task_id,
    bt.status as result_status,
    bt.attempt_timestamp as attempted_at,
    bt.completed_at
FROM background_tasks bt
JOIN background_check_sequence bcs ON bt.sequence_id = bcs.id
WHERE bt.case_id = $1
ORDER BY bt.current_sequence_step;

-- Future steps (from sequence definition, LEFT JOIN)
-- See SD-DASHBOARD-AUDIT-001 §2.x for the full synthesized timeline query
```

---

## 5. Edge Cases

### 5.1 Case Resolved During Delay

After `asyncio.sleep(delay_hours)`, the case may have been resolved externally (e.g., verifier clicked the email link from step 1). The guard check prevents creating a step 2 task for an already-resolved case.

```python
# Re-check after sleep
case_status = await get_case_status(case_id, db_pool)
if case_status in TERMINAL_CASE_STATUSES:
    # Do NOT create step 2 task — case is done
    return
```

### 5.2 Duplicate Step Tasks (Idempotency)

If the orchestrator crashes and restarts, it might try to create a step 2 task when one already exists. Guard with:

```python
# Check if task already exists for this step
existing = await db_pool.fetchval("""
    SELECT id FROM background_tasks
    WHERE case_id = $1 AND current_sequence_step = $2
    LIMIT 1
""", case_id, step['step_order'])

if existing:
    current_task_id = existing  # Reuse existing task
else:
    # PREREQUISITE: Migration 052 (previous_task_id, next_task_id columns) must be applied
    current_task_id = await create_step_task(...)
```

Note: This check uses `current_sequence_step` (which already exists from migration 035), not the new chaining columns.

### 5.3 Email Template Task ID

When sending emails, the verification link (`/verify/{task_id}`) must use the current step's task_id. If the verifier clicks the link and submits the unified-form, the form submission endpoint records the result against this specific task. Using the wrong task_id would:
- Record the result against step 1 instead of step 2
- Leave step 2's task stuck in `in_progress`
- Break the `previous_task_id`/`next_task_id` chain for subsequent steps

### 5.4 Same-Step Retries vs Cross-Step Tasks

Within a single step, retries create additional `background_tasks` rows via `create_retry_task()` (existing behavior). These retry tasks have the **same** `current_sequence_step` value. The step-level task created by `create_step_task()` is the "parent" for that step.

```
Step 1:
  task 401 (step=1, attempt 1, status=completed, result=no_answer)
  task 403 (step=1, attempt 2, status=completed, result=voicemail)  ← same-step retry

Step 2:
  task 402 (step=2, attempt 1, status=in_progress)  ← created by create_step_task
```

The dashboard timeline groups by `current_sequence_step` and shows the latest attempt per step.

---

## 6. Testing Strategy

### Unit Tests

1. **`create_step_task()` creates correct row**: Verify all columns set correctly (step_order, sequence_id, previous_task_id, status='in_progress')
2. **Task chain integrity**: After creating step 2 task, verify step 1 task's `next_task_id` is updated
3. **Guard prevents task creation for terminal cases**: If `cases.status = 'completed'`, no new task created
4. **Idempotency**: Calling `create_step_task()` twice for same step returns existing task_id

### Integration Tests

1. **Full 3-step sequence**: Submit case → step 1 exhausted → step 2 task created → step 2 dispatched with correct task_id → step 2 exhausted → step 3 task created
2. **Dashboard query returns all steps**: After steps 1+2 complete, `SELECT ... FROM background_tasks WHERE case_id = ?` returns 2+ rows with distinct `current_sequence_step` values
3. **Email verification link uses correct task_id**: Step 2 email contains `/verify/{step2_task_id}`, not `/verify/{step1_task_id}`
4. **External resolution during delay**: Start step 1, sleep for step 2 delay, resolve case externally during sleep → verify no step 2 task created

### Manual Validation

1. Run full 3-step sequence in staging
2. Query `background_tasks WHERE case_id = ?` — verify one row per step
3. Check Prefect email templates for correct task_id references
4. Verify dashboard timeline shows all steps (requires PRD-DASHBOARD-AUDIT-001 frontend)

---

## 7. Files to Modify

| File | Change | Priority |
|------|--------|----------|
| `database/migrations/052_add_task_chain_columns.sql` | **New migration** - Add `previous_task_id` and `next_task_id` columns to `background_tasks` | P0 |
| `utils/background_task_helpers.py` | Add `create_step_task()` function | P0 |
| `prefect_flows/flows/verification_orchestrator.py` | Replace in-memory step loop with per-step task creation + guard | P0 |
| `prefect_flows/flows/tasks/process_result.py` | Ensure `task_id` in results refers to current step's task | P0 |
| `prefect_flows/flows/email_dispatch.py` | Verify email template uses received `task_id` (not hardcoded) | P1 |
| `prefect_flows/flows/voice_verification.py` | Verify voice dispatch uses received `task_id` | P1 |
| Tests | Unit + integration tests for `create_step_task()` and orchestrator changes | P0 |

## 8. Acceptance Criteria

- [ ] Migration `052_add_task_chain_columns.sql` created and applied
- [ ] After each step in a 3-step sequence, a new `background_tasks` row exists with the correct `current_sequence_step`
- [ ] `previous_task_id`/`next_task_id` chain is intact across all step tasks
- [ ] Voice calls in step 1 use step 1's task_id; emails in step 2 use step 2's task_id
- [ ] If a case is resolved externally during the delay between steps, no new task is created
- [ ] Dashboard API query (`SELECT * FROM background_tasks WHERE case_id = ?`) returns one entry per step with correct step_order
- [ ] Email verification links (`/verify/{task_id}`) reference the current step's task, not a previous step's task
- [ ] No duplicate step tasks created on orchestrator restart (idempotency guard)

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
