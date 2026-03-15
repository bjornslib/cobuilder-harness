---
title: "SD-SEQ-PROGRESSION-001: Check Sequence Progression Implementation"
status: active
type: reference
grade: authoritative
last_verified: 2026-03-09T00:00:00.000Z
research_validated: true
---
# SD-SEQ-PROGRESSION-001: Check Sequence Progression Implementation

**PRD**: PRD-SEQ-PROGRESSION-001
**Epic**: A (Sequence Advancement Logic) + B (Delay Scheduling) + C (Terminal Detection) + D (Seed Data Fix)
**Target Repo**: zenagent2/zenagent/agencheck/agencheck-support-agent
**Estimated Effort**: ~3-4 days

---

## 1. Architecture Overview

### Current Flow (Broken)

```
verification_orchestrator_flow()
  → dispatch_channel_verification(voice)
  → process_call_result()
    → should_retry? → create_retry_task() [SAME step, hardcoded backoff]
    → max retries? → escalate to manual_review [SKIPS step 2]
```

### Target Flow (After Implementation)

```
verification_orchestrator_flow()
  → dispatch_channel_verification(channel_from_step)
  → process_call_result() / process_email_result()
    → should_retry_within_step? → create_retry_task() [SAME step, DB-driven intervals]
    → step exhausted?
        → advance_to_next_step()
            → resolve next step from background_check_sequence (3-tier)
            → create_next_step_task() with delay_hours scheduling
            → submit new Prefect flow for next channel
    → all steps exhausted? → mark_case_terminal()
    → terminal result at ANY step? → mark_case_complete()
```

### Key Design Decisions

**Decision 1: Event-Driven, Not Polling**

We use **Option A from the PRD** — post-completion hook in the existing flow. When `process_call_result()` (or future `process_email_result()`) determines a step is exhausted, it immediately resolves and schedules the next step. No separate polling flow needed.

**Decision 2: Hybrid Scheduling (Prefect + DB)**

*[Research-validated]* Use a **hybrid approach** for delayed step execution:
- Store next-step tasks in `background_tasks` with `scheduled_time` (source of truth for task metadata)
- **Additionally** submit a Prefect flow run with `scheduled_time` via `run_deployment()` for native scheduling:
```python
  from prefect.deployments.flow_runs import run_deployment
  run = run_deployment(
      name="verification-orchestrator/default",
      scheduled_time=datetime.now(timezone.utc) + timedelta(hours=delay),
      timeout=0,  # fire-and-forget, don't block
      parameters={"task_id": new_task_id, "case_id": case_id},
  )
```
- This gives Prefect UI visibility (scheduled runs show as "Scheduled" state) plus our queryable `background_tasks` table
- If Prefect deployment isn't configured, fall back to DB polling (existing `get_due_tasks()` pattern)

**Decision 3: Disable Prefect Retries, Use DB Retry Counting**

*[Research-validated]* Don't mix Prefect's `@task(retries=N)` with our DB-level retry counting. Pick one layer:
- Set `@task(retries=0)` on all sequence advancement tasks (Prefect won't auto-retry)
- Our `background_tasks.retry_count` / `max_retries` columns handle retry logic
- Exception: `@task(retries=1, retry_delay_seconds=5)` for transient DB connection errors only (not business-level retries)

**Decision 4: Explicit Transactions for Atomicity**

*[Research-validated]* All multi-statement DB operations MUST use `pool.acquire()` + `conn.transaction()`. Pool-level convenience methods (`pool.fetchrow()`, `pool.execute()`) auto-commit on **separate connections** and cannot participate in transactions. See Section 2.1 for the corrected pattern.

---

## 2. Component Design

### 2.1 New Module: `sequence_advancement.py`

**Location**: `prefect_flows/flows/tasks/sequence_advancement.py`

This is the core new module. It contains the logic to advance a case from one step to the next.

```python
"""Sequence advancement logic for check sequence progression.

Responsible for:
1. Determining if a step is exhausted (all attempts used, non-terminal result)
2. Resolving the next step from background_check_sequence (3-tier resolution)
3. Creating the next step's background_task with correct scheduling
4. Linking tasks via previous_task_id / next_task_id chain
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict
import logging

from prefect import task

logger = logging.getLogger(__name__)


class StepExhaustionResult(TypedDict):
    """Result of checking whether a step is exhausted."""
    is_exhausted: bool
    is_terminal: bool
    current_step: int
    attempts_used: int
    max_attempts: int
    last_result_status: str


class NextStepInfo(TypedDict):
    """Info about the next step to execute."""
    sequence_id: int
    step_order: int
    step_name: str
    delay_hours: float
    max_attempts: int
    channel_type: str  # voice | email | sms | whatsapp
    version: int


# Terminal result statuses — no further steps needed
TERMINAL_STATUSES = frozenset({
    "verified",
    "confirmed",
    "refused",
    "unable_to_verify",
    "not_employed",
    "company_closed",
    "invalid_contact",
})

# Retryable within same step
RETRYABLE_WITHIN_STEP = frozenset({
    "voicemail",
    "no_answer",
    "busy",
    "callback_requested",
    "timeout",
})


@task(name="check-step-exhaustion", retries=0)
async def check_step_exhaustion(
    case_id: int,
    task_id: int,
    result_status: str,
    db_pool,
) -> StepExhaustionResult:
    """Check if the current step is exhausted (all attempts used, non-terminal).

    Returns exhaustion state so the caller can decide to retry, advance, or close.
    """
    # Get current task's sequence metadata
    row = await db_pool.fetchrow("""
        SELECT
            bt.current_sequence_step,
            bt.check_type_config_id,
            bt.sequence_id,
            bt.retry_count,
            bt.max_retries,
            bcs.max_attempts,
            bcs.step_order
        FROM background_tasks bt
        LEFT JOIN background_check_sequence bcs ON bt.sequence_id = bcs.id
        WHERE bt.id = $1
    """, task_id)

    if row is None:
        logger.error(f"Task {task_id} not found for case {case_id}")
        return StepExhaustionResult(
            is_exhausted=False,
            is_terminal=True,  # Safety: don't advance if task not found
            current_step=1,
            attempts_used=0,
            max_attempts=0,
            last_result_status=result_status,
        )

    # Terminal results end the sequence at any step
    is_terminal = result_status in TERMINAL_STATUSES

    # Count actual attempts for this step (not just this task's retry_count)
    attempt_count = await db_pool.fetchval("""
        SELECT COUNT(*) FROM background_tasks
        WHERE case_id = $1
          AND current_sequence_step = $2
          AND action_type IN ('call_attempt', 'email_attempt', 'sms_attempt')
          AND status IN ('completed', 'failed')
    """, case_id, row['current_sequence_step'])

    max_attempts = row['max_attempts'] or row['max_retries'] or 5
    is_exhausted = (
        not is_terminal
        and result_status not in RETRYABLE_WITHIN_STEP
        or attempt_count >= max_attempts
    )

    return StepExhaustionResult(
        is_exhausted=is_exhausted,
        is_terminal=is_terminal,
        current_step=row['current_sequence_step'] or 1,
        attempts_used=attempt_count,
        max_attempts=max_attempts,
        last_result_status=result_status,
    )


@task(name="resolve-next-step", retries=1, retry_delay_seconds=5)
async def resolve_next_step(
    check_type_id: int,
    customer_id: int,
    client_id: Optional[int],
    current_step_order: int,
    db_pool,
) -> Optional[NextStepInfo]:
    """Resolve the next step in the sequence using 3-tier resolution.

    Resolution order:
    1. Client-specific (check_type_id + customer_id + client_id)
    2. Customer default (check_type_id + customer_id + client_id IS NULL)
    3. System fallback (check_type_id + customer_id=1 + client_id IS NULL)

    Returns None if no next step exists (sequence complete).
    """
    # Try 3-tier resolution for the next step
    next_step = await db_pool.fetchrow("""
        WITH ranked_steps AS (
            SELECT
                bcs.*,
                CASE
                    WHEN bcs.customer_id = $2 AND bcs.client_id = $3 THEN 1  -- Tier 1: client-specific
                    WHEN bcs.customer_id = $2 AND bcs.client_id IS NULL THEN 2  -- Tier 2: customer default
                    WHEN bcs.customer_id = 1 AND bcs.client_id IS NULL THEN 3   -- Tier 3: system fallback
                END as tier
            FROM background_check_sequence bcs
            WHERE bcs.check_type_id = $1
              AND bcs.step_order = $4
              AND bcs.status = 'active'
              AND bcs.is_active = true
              AND (
                  (bcs.customer_id = $2 AND bcs.client_id = $3) OR
                  (bcs.customer_id = $2 AND bcs.client_id IS NULL) OR
                  (bcs.customer_id = 1 AND bcs.client_id IS NULL)
              )
        )
        SELECT * FROM ranked_steps
        ORDER BY tier ASC
        LIMIT 1
    """, check_type_id, customer_id, client_id, current_step_order + 1)

    if next_step is None:
        logger.info(
            f"No next step found for check_type={check_type_id}, "
            f"customer={customer_id}, after step {current_step_order}"
        )
        return None

    return NextStepInfo(
        sequence_id=next_step['id'],
        step_order=next_step['step_order'],
        step_name=next_step['step_name'],
        delay_hours=float(next_step['delay_hours']),
        max_attempts=next_step['max_attempts'],
        channel_type=next_step['channel_type'] or 'voice',
        version=next_step['version'],
    )


@task(name="create-next-step-task", retries=1, retry_delay_seconds=5)
async def create_next_step_task(
    case_id: int,
    customer_id: int,
    previous_task_id: int,
    next_step: NextStepInfo,
    check_type_config_id: int,
    db_pool,
) -> int:
    """Create a background_task for the next step with proper scheduling.

    Sets:
    - current_sequence_step to next step's step_order
    - sequence_id and sequence_version from resolved step
    - scheduled_time based on delay_hours
    - previous_task_id for chain linking
    - action_type based on channel_type
    """
    scheduled_at = datetime.now(timezone.utc) + timedelta(hours=next_step['delay_hours'])

    # Map channel_type to action_type
    channel_to_action = {
        'voice': 'call_attempt',
        'email': 'email_attempt',
        'sms': 'sms_attempt',
        'whatsapp': 'whatsapp_attempt',
    }
    action_type = channel_to_action.get(next_step['channel_type'], 'call_attempt')

    # Create the next step task
    new_task_id = await db_pool.fetchval("""
        INSERT INTO background_tasks (
            case_id,
            customer_id,
            action_type,
            status,
            scheduled_time,
            current_sequence_step,
            sequence_id,
            sequence_version,
            check_type_config_id,
            previous_task_id,
            retry_count,
            max_retries,
            context_data,
            created_at
        ) VALUES (
            $1, $2, $3, 'pending', $4, $5, $6, $7, $8, $9, 0, $10,
            $11::jsonb, NOW()
        )
        RETURNING id
    """,
        case_id,
        customer_id,
        action_type,
        scheduled_at,
        next_step['step_order'],
        next_step['sequence_id'],
        next_step['version'],
        check_type_config_id,
        previous_task_id,
        next_step['max_attempts'],
        f'{{"step_name": "{next_step["step_name"]}", '
        f'"channel_type": "{next_step["channel_type"]}", '
        f'"advanced_from_step": {next_step["step_order"] - 1}}}',
    )

    # Link previous task to new task
    await db_pool.execute("""
        UPDATE background_tasks
        SET next_task_id = $1
        WHERE id = $2
    """, new_task_id, previous_task_id)

    logger.info(
        f"Created step {next_step['step_order']} task {new_task_id} for case {case_id}. "
        f"Channel: {next_step['channel_type']}, Scheduled: {scheduled_at}, "
        f"Delay: {next_step['delay_hours']}h"
    )

    return new_task_id


@task(name="advance-sequence", retries=1, retry_delay_seconds=5)
async def advance_sequence(
    case_id: int,
    task_id: int,
    result_status: str,
    db_pool,
) -> dict:
    """Main entry point: advance a case to the next sequence step.

    Called from process_result.py when a step is exhausted.

    IMPORTANT [Research-validated]: This function uses explicit transactions
    via pool.acquire() + conn.transaction() for atomicity. Pool-level methods
    (pool.fetchrow) auto-commit on separate connections and CANNOT be used
    for multi-statement atomic operations.

    Race condition prevention: Uses SELECT ... FOR UPDATE on the completed
    task row. If two workers finish step 1 simultaneously, the second caller
    blocks until the first commits, then sees next_task_id IS NOT NULL and
    bails out (idempotent).

    Returns:
        dict with keys:
        - advanced: bool (True if next step created)
        - terminal: bool (True if sequence complete)
        - next_task_id: Optional[int]
        - next_step_name: Optional[str]
        - reason: str (human-readable explanation)
    """
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # ── Step 1: Lock the completed task row (race prevention) ──
            prev_task = await conn.fetchrow("""
                SELECT
                    bt.id,
                    bt.current_sequence_step,
                    bt.check_type_config_id,
                    bt.sequence_id,
                    bt.next_task_id,
                    bt.retry_count,
                    bt.max_retries,
                    c.customer_id,
                    c.client_id,
                    bcs.max_attempts,
                    bcs.step_order
                FROM background_tasks bt
                JOIN cases c ON c.id = bt.case_id
                LEFT JOIN background_check_sequence bcs ON bt.sequence_id = bcs.id
                WHERE bt.id = $1 AND bt.case_id = $2
                FOR UPDATE OF bt
            """, task_id, case_id)

            if prev_task is None:
                return {
                    "advanced": False, "terminal": True,
                    "next_task_id": None, "next_step_name": None,
                    "reason": f"Task {task_id} not found for case {case_id}",
                }

            # Idempotency guard: already advanced by another worker
            if prev_task['next_task_id'] is not None:
                return {
                    "advanced": False, "terminal": False,
                    "next_task_id": prev_task['next_task_id'],
                    "next_step_name": None,
                    "reason": "Already advanced by concurrent worker",
                }

            # ── Step 2: Check terminal result ──
            if result_status in TERMINAL_STATUSES:
                await conn.execute("""
                    UPDATE cases SET status = 'completed', updated_at = NOW()
                    WHERE id = $1 AND status != 'completed'
                """, case_id)
                return {
                    "advanced": False, "terminal": True,
                    "next_task_id": None, "next_step_name": None,
                    "reason": f"Terminal result: {result_status}",
                }

            # ── Step 3: Count attempts for this step ──
            current_step = prev_task['current_sequence_step'] or 1
            attempt_count = await conn.fetchval("""
                SELECT COUNT(*) FROM background_tasks
                WHERE case_id = $1
                  AND current_sequence_step = $2
                  AND action_type IN ('call_attempt', 'email_attempt', 'sms_attempt')
                  AND status IN ('completed', 'failed')
            """, case_id, current_step)

            max_attempts = prev_task['max_attempts'] or prev_task['max_retries'] or 5

            # Step not exhausted — retries available
            if (result_status in RETRYABLE_WITHIN_STEP
                    and attempt_count < max_attempts):
                return {
                    "advanced": False, "terminal": False,
                    "next_task_id": None, "next_step_name": None,
                    "reason": f"Step {current_step} has retries remaining "
                              f"({attempt_count}/{max_attempts})",
                }

            # ── Step 4: Resolve next step (3-tier CTE, within same txn) ──
            next_step = await conn.fetchrow("""
                WITH ranked_steps AS (
                    SELECT
                        bcs.*,
                        CASE
                            WHEN bcs.customer_id = $2 AND bcs.client_id = $3 THEN 1
                            WHEN bcs.customer_id = $2 AND bcs.client_id IS NULL THEN 2
                            WHEN bcs.customer_id = 1 AND bcs.client_id IS NULL THEN 3
                        END as tier
                    FROM background_check_sequence bcs
                    WHERE bcs.check_type_id = $1
                      AND bcs.step_order = $4
                      AND bcs.status = 'active'
                      AND bcs.is_active = true
                      AND (
                          (bcs.customer_id = $2 AND bcs.client_id = $3) OR
                          (bcs.customer_id = $2 AND bcs.client_id IS NULL) OR
                          (bcs.customer_id = 1 AND bcs.client_id IS NULL)
                      )
                )
                SELECT * FROM ranked_steps
                ORDER BY tier ASC
                LIMIT 1
            """, prev_task['check_type_config_id'],
                prev_task['customer_id'],
                prev_task.get('client_id'),
                current_step + 1)

            if next_step is None:
                # No more steps — sequence complete
                await conn.execute("""
                    UPDATE cases
                    SET status = 'max_retries_exceeded', updated_at = NOW()
                    WHERE id = $1 AND status NOT IN ('completed', 'cancelled')
                """, case_id)
                return {
                    "advanced": False, "terminal": True,
                    "next_task_id": None, "next_step_name": None,
                    "reason": f"Sequence complete — all {current_step} steps exhausted",
                }

            # ── Step 5: Create next step task (atomic with lock) ──
            scheduled_at = datetime.now(timezone.utc) + timedelta(
                hours=float(next_step['delay_hours'])
            )
            channel_to_action = {
                'voice': 'call_attempt', 'email': 'email_attempt',
                'sms': 'sms_attempt', 'whatsapp': 'whatsapp_attempt',
            }
            action_type = channel_to_action.get(
                next_step['channel_type'] or 'voice', 'call_attempt'
            )

            import json
            context = json.dumps({
                "step_name": next_step['step_name'],
                "channel_type": next_step['channel_type'],
                "advanced_from_step": current_step,
            })

            new_task_id = await conn.fetchval("""
                INSERT INTO background_tasks (
                    case_id, customer_id, action_type, status,
                    scheduled_time, current_sequence_step,
                    sequence_id, sequence_version, check_type_config_id,
                    previous_task_id, retry_count, max_retries,
                    context_data, created_at
                ) VALUES (
                    $1, $2, $3, 'pending', $4, $5, $6, $7, $8,
                    $9, 0, $10, $11::jsonb, NOW()
                )
                RETURNING id
            """,
                case_id, prev_task['customer_id'], action_type,
                scheduled_at, next_step['step_order'],
                next_step['id'], next_step['version'],
                prev_task['check_type_config_id'], task_id,
                next_step['max_attempts'], context,
            )

            # ── Step 6: Link previous → new (atomic) ──
            await conn.execute("""
                UPDATE background_tasks SET next_task_id = $1 WHERE id = $2
            """, new_task_id, task_id)

            # ── Step 7: Update case status ──
            await conn.execute("""
                UPDATE cases
                SET status = 'in_progress', updated_at = NOW()
                WHERE id = $1 AND status NOT IN ('completed', 'cancelled')
            """, case_id)

    # Outside transaction: optionally submit Prefect scheduled run
    try:
        from prefect.deployments.flow_runs import run_deployment
        run_deployment(
            name="verification-orchestrator/default",
            scheduled_time=scheduled_at,
            timeout=0,  # fire-and-forget
            parameters={
                "task_id": new_task_id,
                "case_id": case_id,
                "customer_id": prev_task['customer_id'],
                "check_type": "work_history",
            },
        )
        logger.info(f"Submitted Prefect scheduled run for step {next_step['step_order']}")
    except Exception as e:
        # Prefect deployment may not be configured — fall back to DB polling
        logger.warning(f"Prefect scheduling failed (DB polling fallback): {e}")

    logger.info(
        f"Advanced case {case_id} to step {next_step['step_order']}: "
        f"{next_step['step_name']} (channel: {next_step['channel_type']}, "
        f"delay: {next_step['delay_hours']}h, task_id: {new_task_id})"
    )

    return {
        "advanced": True,
        "terminal": False,
        "next_task_id": new_task_id,
        "next_step_name": next_step['step_name'],
        "reason": f"Advanced to step {next_step['step_order']}: {next_step['step_name']} "
                  f"(channel: {next_step['channel_type']}, delay: {next_step['delay_hours']}h)",
    }
```

### 2.2 Integration Point: `process_result.py`

**Modification**: Add `advance_sequence()` call after determining step exhaustion.

**Current code** (lines 219-270) creates a same-step retry via `create_retry_task()`. The modification adds an else-branch for when retries are exhausted:

```python
# EXISTING: lines 219-270 in process_result.py
if should_retry:
    # ... existing same-step retry logic (keep unchanged) ...
    pass

# NEW: Add after the retry block
else:
    # Step exhausted or non-retryable result — try advancing sequence
    from prefect_flows.flows.tasks.sequence_advancement import advance_sequence
    advancement = await advance_sequence(
        case_id=case_id,
        task_id=task_id,
        result_status=result_status,
        db_pool=db_pool,
    )
    logger.info(f"Sequence advancement for case {case_id}: {advancement['reason']}")
```

**Key principle**: Same-step retries (voicemail, no_answer) continue using the existing `create_retry_task()` path. Cross-step advancement only triggers when the step is fully exhausted.

### 2.3 Integration Point: `verification_orchestrator.py`

**Modification**: Use `channel_type` from the background_task to determine which channel to dispatch, instead of hardcoded `load_sla_config()`.

```python
# EXISTING (lines 203-218): Hardcoded SLA config
# sla_config = load_sla_config(customer_id, check_type)
# primary_channel = sla_config.primary_method

# NEW: Read channel from task's sequence step
task_row = await db_pool.fetchrow("""
    SELECT
        bt.current_sequence_step,
        bt.sequence_id,
        bcs.channel_type
    FROM background_tasks bt
    LEFT JOIN background_check_sequence bcs ON bt.sequence_id = bcs.id
    WHERE bt.id = $1
""", task_id)

channel = VerificationChannelEnum(task_row['channel_type'] or 'voice')
result = await dispatch_channel_verification(
    channel=channel,
    case_id=case_id,
    customer_id=customer_id,
    task_id=task_id,
    check_type=check_type,
    retry_config=retry_config,
)
```

### 2.4 Prefect Task Scheduling for Delayed Steps

*[Research-validated]* Two complementary mechanisms handle delayed step execution:

**Primary: Prefect Native Scheduling**

When `advance_sequence()` creates a next-step task, it also submits a Prefect flow run with `scheduled_time`:

```python
from prefect.deployments.flow_runs import run_deployment

run = run_deployment(
    name="verification-orchestrator/default",
    scheduled_time=datetime.now(timezone.utc) + timedelta(hours=2),
    timeout=0,  # fire-and-forget — returns immediately
    parameters={"task_id": new_task_id, "case_id": case_id},
)
# Flow run appears as "Scheduled" in Prefect UI
# Prefect worker picks it up within its poll interval (5-10s) after scheduled_time
```

Benefits:
- Full visibility in Prefect UI (scheduled runs show as "Scheduled" state with countdown)
- Precision: Prefect worker picks up within 5-10s of scheduled_time
- Survives worker restarts (Prefect server persists scheduled runs)

**Fallback: DB Polling**

If Prefect deployment isn't configured (e.g., local dev), the existing `get_due_tasks()` pattern picks up tasks:

```python
async def get_due_tasks(self, db_pool) -> list:
    """Fetch tasks that are due for execution."""
    return await db_pool.fetch("""
        SELECT * FROM background_tasks
        WHERE status = 'pending'
          AND (scheduled_time IS NULL OR scheduled_time <= NOW())
        ORDER BY scheduled_time ASC NULLS FIRST
        LIMIT 50
    """)
```

**Idempotency note**: If both mechanisms fire (Prefect run + DB polling), the flow should check task status before processing — if already `in_progress` or `completed`, skip.

### 2.6 Transaction Safety Rules

*[Research-validated]* Critical asyncpg behavior that affects all DB operations in this module:

| Method | Auto-commits? | Transaction-safe? |
| --- | --- | --- |
| `pool.fetchrow(q)` | Yes (own connection) | NO — each call is independent |
| `pool.execute(q)` | Yes (own connection) | NO — separate from other calls |
| `conn.fetchrow(q)` inside `conn.transaction()` | No | YES — commits/rolls back together |
| `conn.execute(q)` inside `conn.transaction()` | No | YES |

**Rule**: Any operation that does SELECT → INSERT → UPDATE MUST use:
```python
async with pool.acquire() as conn:
    async with conn.transaction():
        # All operations here are atomic
        row = await conn.fetchrow("SELECT ...")
        await conn.execute("INSERT ...")
        await conn.execute("UPDATE ...")
```

**Race prevention pattern** (used in `advance_sequence()`):
```python
# Lock the specific completed task row — concurrent callers block here
prev = await conn.fetchrow(
    "SELECT ... FROM background_tasks WHERE id = $1 FOR UPDATE", task_id
)
# Guard: if already advanced, bail out
if prev['next_task_id'] is not None:
    return None  # idempotent
```

### 2.5 Seed Data Fix (Migration 048)

```sql
-- Fix channel_type for Email Outreach step (step_order=2, work_history)
UPDATE background_check_sequence
SET channel_type = 'email'
WHERE step_name = 'Email Outreach'
  AND channel_type = 'voice';

-- Fix channel_type for email-first check types (education, reference)
UPDATE background_check_sequence
SET channel_type = 'email'
WHERE step_name ILIKE '%email%'
  AND channel_type = 'voice';
```

---

## 3. Data Flow Diagram

```
┌─────────────────────┐
│ Case Created         │
│ (work_history.py)    │
│ current_step = 1     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ Step 1: Voice Call (max_attempts=2)  │
│ channel_type = 'voice'               │
├──────────────────────────────────────┤
│ Attempt 1: voicemail → retry (same)  │
│ Attempt 2: no_answer → EXHAUSTED     │
└──────────┬──────────────────────────┘
           │ advance_sequence()
           │ resolve_next_step(step_order=2)
           ▼
┌─────────────────────────────────────┐
│ Step 2: Email Outreach (delay=2h)    │
│ channel_type = 'email'               │
│ scheduled_time = now() + 2h          │
├──────────────────────────────────────┤
│ (waits 2h, then dispatcher picks up) │
│ Attempt 1: no_response → retry       │
│ Attempt 2: no_response → EXHAUSTED   │
└──────────┬──────────────────────────┘
           │ advance_sequence()
           │ resolve_next_step(step_order=3)
           ▼
┌─────────────────────────────────────┐
│ Step 3: Manual Review (delay=0h)     │
│ channel_type = 'manual'              │
├──────────────────────────────────────┤
│ Create manual review queue entry     │
│ Case status = 'requires_review'      │
└─────────────────────────────────────┘
```

---

## 4. Database Queries (Performance Notes)

### 4.1 Next Step Resolution Query

The 3-tier resolution CTE uses an index scan on `(check_type_id, customer_id, client_id, step_order)`. The existing UNIQUE constraint in migration 036 partially covers this. Consider adding:

```sql
CREATE INDEX IF NOT EXISTS idx_bcs_step_resolution
ON background_check_sequence (check_type_id, step_order, customer_id, client_id)
WHERE status = 'active' AND is_active = true;
```

### 4.2 Attempt Counting Query

Counting attempts per step per case:

```sql
SELECT COUNT(*) FROM background_tasks
WHERE case_id = $1 AND current_sequence_step = $2
  AND action_type IN ('call_attempt', 'email_attempt', 'sms_attempt')
  AND status IN ('completed', 'failed')
```

Index needed:

```sql
CREATE INDEX IF NOT EXISTS idx_bt_case_step_attempts
ON background_tasks (case_id, current_sequence_step, action_type)
WHERE status IN ('completed', 'failed');
```

---

## 5. Interaction with Existing Systems

### 5.1 Same-Step Retries (Unchanged)

The existing `create_retry_task()` in `background_task_helpers.py` continues to handle same-step retries for RETRYABLE_WITHIN_STEP results (voicemail, no_answer, busy, callback_requested). These retries:
- Stay at `current_sequence_step = N`
- Use the step's own retry intervals (from `background_check_sequence.delay_hours` — **TODO: replace hardcoded backoff**)
- Increment `retry_count` on the task

### 5.2 Cross-Step Advancement (New)

When same-step retries are exhausted (attempt_count >= max_attempts), `advance_sequence()` takes over:
- Resolves the NEXT step via 3-tier resolution
- Creates a NEW task at `current_sequence_step = N+1`
- Links via `previous_task_id` / `next_task_id`
- Schedules via `scheduled_time` based on `delay_hours`

### 5.3 Email Outreach Channel

Step 2 dispatches to `channel_type='email'`. The existing `channel_dispatch.py` has a placeholder `_dispatch_email_verification()`. For MVP:
- If email dispatch is not yet implemented, the task will be created but dispatch will return `{"status": "not_implemented"}`
- This is acceptable — the task exists in the audit trail, and when email dispatch is built (PRD-P1.1-INFRA-001), it will work automatically
- Alternative: Skip step 2 if channel_type='email' and email dispatch is not ready, advancing directly to step 3

### 5.4 Dashboard Integration

PRD-DASHBOARD-AUDIT-001 will display sequence progression in the timeline view. No dashboard changes needed here — the new tasks created at step 2/3 will automatically appear when the dashboard queries `background_tasks` by `case_id`.

---

## 6. Testing Strategy

### Unit Tests

| Test | Input | Expected Output |
| --- | --- | --- |
| `test_step_not_exhausted` | 1 attempt, max=2 | `is_exhausted=False` |
| `test_step_exhausted` | 2 attempts, max=2 | `is_exhausted=True` |
| `test_terminal_result` | `verified` result | `is_terminal=True`, case completed |
| `test_resolve_tier1` | Client-specific step exists | Returns client step |
| `test_resolve_tier2` | No client step, customer default exists | Returns customer step |
| `test_resolve_tier3` | No customer step, system fallback exists | Returns system step |
| `test_resolve_no_next` | Last step exhausted | Returns None |
| `test_advance_creates_task` | Step 1 exhausted, step 2 exists | New task at step_order=2 |
| `test_advance_sets_delay` | delay_hours=2.0 | scheduled_time = now + 2h |
| `test_advance_links_tasks` | previous_task_id=5 | previous_task_id=5, next_task_id updated |

### Integration Tests

| Scenario | Steps | Assertion |
| --- | --- | --- |
| Full 3-step progression | Create case → exhaust step 1 → verify step 2 created → exhaust step 2 → verify step 3 created | 3 tasks in background_tasks with step_order 1,2,3 |
| Terminal at step 1 | Create case → step 1 returns `verified` | Case completed, no step 2 task |
| Delay enforcement | Exhaust step 1 → step 2 delay=2h | Step 2 task scheduled_time = step 1 completion + 2h |
| 3-tier resolution | Create client-specific step 2 | Client step used over customer/system defaults |

---

## 7. Risks & Resolved Questions

### Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Email channel not implemented | Step 2 tasks created but can't execute | Accept placeholder response; task exists for audit. When email dispatch is built (PRD-P1.1-INFRA-001), step 2 tasks will work automatically |
| Race condition on concurrent retries | Duplicate next-step tasks | **[RESOLVED]** `SELECT ... FOR UPDATE` on completed task row + `next_task_id IS NOT NULL` idempotency guard. See section 2.6 |
| SLA config changes mid-case | Wrong step resolved | Use `sequence_version` from initial task to pin version |
| Prefect + DB double-retry | Task executes twice | Check task status at flow entry — skip if already `in_progress` |

### Research Questions (All Resolved)

| # | Question | Answer | Source |
| --- | --- | --- | --- |
| 1 | Prefect delayed scheduling | Use `run_deployment(scheduled_time=..., timeout=0)`. Prefect worker picks up within 5-10s poll interval. | Prefect 3.x docs, `deployments.flow_runs` module |
| 2 | asyncpg in Prefect tasks | asyncpg pools work natively in async Prefect tasks. Pass pool as parameter or use module singleton. No special integration needed. | asyncpg docs, Prefect community |
| 3 | Transaction safety | `pool.fetchrow()` auto-commits on separate connections — CANNOT use for multi-step ops. MUST use `pool.acquire()` + `conn.transaction()` for atomic SELECT→INSERT→UPDATE. | asyncpg usage docs |
| 4 | Race condition prevention | `SELECT ... FOR UPDATE` on the completed task row. Second caller blocks, then sees `next_task_id IS NOT NULL` and bails. Preferred over advisory locks (simpler) and `ON CONFLICT` (doesn't cover UPDATE). | PostgreSQL explicit locking docs |
| 5 | Retry layer | Don't mix Prefect retries with DB retry counting. Set `@task(retries=0)` for business logic (our DB handles retries). Use `retries=1` only for transient DB errors. | Prefect best practices |

### Remaining Open Questions (For Implementation)

1. **Same-step retry backoff**: ~~Should we also replace the hardcoded ~~~~`RETRY_BACKOFF_HOURS = [2, 4, 24, 48]`~~~~?~~ **DECIDED: YES — replace in same PR.** Replace hardcoded backoff in `process_result.py` with DB-driven intervals from the step's `delay_hours` and `max_attempts` config. The step config already has `delay_hours` per step — use it for same-step retries too. See Section 2.7.
2. **Manual review step**: When step 3 (`channel_type='manual'`) fires, should it create a queue entry in a `manual_reviews` table, or just update `cases.status = 'requires_review'`? Recommend `cases.status` update for MVP; dedicated table for Phase 2.

### 2.7 Replace Hardcoded Retry Backoff (In Scope)

**Current** (`process_result.py` lines 219-270):
```python
RETRY_BACKOFF_HOURS = [2, 4, 24, 48]  # HARDCODED
MAX_CALL_RETRIES = 5  # HARDCODED
```

**Target**: Read from the step's `background_check_sequence` config:

```python
async def get_retry_config(task_id: int, conn) -> tuple[float, int]:
    """Get retry delay and max attempts from the step's DB config."""
    row = await conn.fetchrow("""
        SELECT bcs.delay_hours, bcs.max_attempts
        FROM background_tasks bt
        JOIN background_check_sequence bcs ON bt.sequence_id = bcs.id
        WHERE bt.id = $1
    """, task_id)
    if row is None:
        return 2.0, 5  # fallback to safe defaults
    return float(row['delay_hours']), row['max_attempts']
```

**Changes to ****`process_result.py`**:
- Remove `RETRY_BACKOFF_HOURS` constant
- Remove `MAX_CALL_RETRIES` constant
- Call `get_retry_config(task_id, conn)` to get delay and max from DB
- Use returned `delay_hours` for `scheduled_time` calculation
- Use returned `max_attempts` for retry eligibility check
- Fallback to `(2.0, 5)` if no sequence config found (backward compatible)

---

## 8. File Change Summary

| File | Change Type | Description |
| --- | --- | --- |
| `prefect_flows/flows/tasks/sequence_advancement.py` | **NEW** | Core sequence advancement logic |
| `prefect_flows/flows/tasks/process_result.py` | MODIFY | Add `advance_sequence()` call after step exhaustion |
| `prefect_flows/flows/verification_orchestrator.py` | MODIFY | Read channel_type from task's sequence step |
| `database/migrations/048_fix_channel_type_seed.sql` | **NEW** | Fix seed data channel_type for email steps |
| `database/migrations/049_add_step_resolution_index.sql` | **NEW** | Performance indexes for step resolution + attempt counting |
| `tests/unit/test_sequence_advancement.py` | **NEW** | Unit tests for all advancement functions |
| `tests/integration/test_sequence_progression.py` | **NEW** | Integration test for full 3-step progression |
