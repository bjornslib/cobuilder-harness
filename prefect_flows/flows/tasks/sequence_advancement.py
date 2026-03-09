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
    import json
    context = json.dumps({
        "step_name": next_step["step_name"],
        "channel_type": next_step["channel_type"],
        "advanced_from_step": next_step["step_order"] - 1,
    })

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
        context,
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