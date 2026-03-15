---
title: "SD-SEQ-RETRY-LOOP-GAPS-001: Gap Analysis — Sequence Routing & Deployment Convergence"
status: active
type: reference
last_verified: 2026-03-10T00:00:00.000Z
---
# SD-SEQ-RETRY-LOOP-GAPS-001: Gap Analysis — Sequence Routing & Deployment Convergence

**Status**: Draft
**PRD**: PRD-SEQ-RETRY-LOOP-001
**Date**: 2026-03-10
**Context**: Issues surfaced during live E2E testing of the retry loop implementation

---

## 1. Executive Summary

Live E2E testing revealed 6 interconnected gaps preventing the retry loop from functioning end-to-end when cases are submitted via the `/verify` API. The core retry loop logic (guard checks, scheduling, sequence advancement) works correctly when triggered directly, but the API-to-orchestrator integration path has structural misalignments.

**Impact**: Cases submitted via the API always create `call_attempt` tasks (ignoring sequence channel), target the wrong Prefect deployment, and cannot leverage the retry loop.

---

## 2. Gap Inventory

### Gap A: Deployment Mismatch (P1) — `claude-harness-setup-hxc8`

**Issue**: The `/verify` API triggers Prefect flows via `prefect_bridge.create_prefect_flow_run()` which targets the legacy `voice-verification/voice-verification` deployment — a single-call flow with no guard checks, no retry loop, and no sequence advancement.

**Root cause**: The API was built before the verification-orchestrator existed. The deployment target was never updated.

**Code path**:
```
POST /api/v1/verify
  → work_history.py → create_prefect_flow_run()
    → prefect_bridge.py → VOICE_VERIFICATION_DEPLOYMENT = "voice-verification/voice-verification"  ← WRONG
```

**Proposed fix**: Update `prefect_bridge.py` to target `verification-orchestrator/verification-orchestrator` and pass the full parameter set (`task_id`, `check_type`, `sequence_id`, `sequence_version`).

**Risk**: Parameter signature difference between old and new flows. Mitigated by verifying the orchestrator flow accepts the required params.

---

### Gap B: Duplicate Sequence Rows (P1) — `claude-harness-setup-xlk8`

**Issue**: `background_check_sequence` has 8 rows for `work_history` — two overlapping sequences (ids 1-4: voice-only, ids 22-25: email→voice). The 3-tier resolution doesn't disambiguate between same-`step_order` rows across sequences.

**Root cause**: The email-first sequence was added without deactivating the original voice-only sequence.

**Proposed fix — Use the existing \****`replaceSequenceWithVersioning`**\*\* API**:

The SLA configuration page already has a `PUT /api/v1/check-types/:id/sequence` endpoint that atomically:
1. Archives all existing active steps (`is_active = false`)
2. Creates new steps with an incremented `sequence_version`
3. Returns the new steps with their IDs

**Implementation**: Call this endpoint (or its Python equivalent from `check_sequence_service.py`) to create a clean default SLA:
- Step 1: Email Outreach — max_attempts: 2, delay: 5 minutes
- Step 2: Email Reminder — max_attempts: 2, delay: 5 minutes
- Step 3: Voice Call — max_attempts: 2, delay: 5 minutes
- Step 4: Voice Retry — max_attempts: 2, delay: 5 minutes

This approach:
- Uses the same code path as the frontend SLA config page
- Automatically archives old rows (both voice-only ids 1-4 AND email-first ids 22-25)
- Assigns a new `sequence_version` for traceability
- Zero raw SQL needed

---

### Gap C: Sequence ID Assignment at Task Creation (P1) — `claude-harness-setup-yn39`

**Issue**: `prefect_bridge.py:479` sets `sequence_id = resolution.steps[0].id` — a single step's PK. When advancing, `advance_sequence()` queries for `step_order = current_step + 1` via 3-tier resolution. If the initial step came from one tier but the next lookup resolves to a different tier, the orchestrator could jump across tiers.

**Root cause**: The `sequence_id` represents a step PK, not a sequence/version identifier. There's no mechanism to lock advancement to the same resolution tier.

**Proposed fix**: After resolving Gap B (clean single sequence via versioned replacement), the step PK is unambiguous. For robustness, `advance_sequence()` should also filter by `sequence_version` to ensure it stays within the same version that was assigned at task creation. The current CTE-based approach in `advance_sequence()` already uses 3-tier with `ORDER BY tier ASC LIMIT 1`, which is correct but should additionally constrain by version.

**How the frontend already handles this**: The V3.2 adapter (`checkSequenceToSLA.ts`) groups steps into PRIMARY and FALLBACK channels based on `step_order`. The frontend understands that step 1 = primary channel, step 2 = fallback channel. The backend orchestrator should use the same `sequence_version` constraint to stay coherent.

---

### Gap D: CheckTypeEnum Hardcoded (P2) — `claude-harness-setup-3uzv`

**Issue**: `models/workflow_events.py` hardcodes:
```python
class CheckTypeEnum(str, Enum):
    WORK_HISTORY = "work_history"
    CALL_SCHEDULING = "call_scheduling"
    EDUCATION = "education"
```

The DB `check_types` table contains additional types (e.g., `work_history_scheduling`). The orchestrator rejects unknown types with a 409 Conflict.

**Root cause**: Enum was created when only 3 types existed. New types were added to the DB but not the enum.

**Proposed fix**: Replace the hardcoded enum with DB-driven validation:
```python
# At flow startup, query valid types from check_types table
valid_types = await conn.fetch("SELECT name FROM check_types WHERE is_active = true")
if check_type not in {r['name'] for r in valid_types}:
    raise ValueError(f"Unknown check_type: {check_type}")
```

This is the approach recommended by the user — linking to the `check_types` table as the source of truth. The frontend already does this: `fetchCheckTypes()` queries the DB for the valid list.

---

### Gap E: Webhook ConnectError (P4) — `claude-harness-setup-ervh`

**Issue**: `state_hooks.send_completion_webhook` and `send_failure_webhook` POST to `{SUPPORT_AGENT_URL}/api/webhooks/prefect/{completion|failure}`. In local Docker, the URL is unreachable.

**Root cause**: These are **internal webhooks** — Prefect calls back to the support agent API to update task status on completion/failure.

**Finding**: These webhooks are **redundant**. The `log_state_to_db` hook (lines 273-347 of `state_hooks.py`) already directly updates `background_tasks.status` via DB for all terminal states (completed, failed, crashed) AND running states. This is a belt-and-suspenders pattern where both the webhook AND the direct DB update do the same thing.

**Logfire already covers observability**: Every state hook is wrapped in `logfire.span()` (line 193). State transitions, parameters, and errors are all traced. The webhooks provide no additional observability that Logfire doesn't already capture.

**Proposed fix**:
1. Guard the webhook calls with an env var check (immediate):
```python
   if not os.getenv("SUPPORT_AGENT_URL"):
       return  # Skip webhook in environments without API
```
2. Long-term: Remove the webhook hooks entirely. The direct DB updates in `log_state_to_db` + Logfire spans provide complete coverage. The webhook endpoint (`api/webhooks/prefect.py`) can be deprecated.

---

### Gap F: action_type Hardcoded at INSERT (P1) — NEW

**Issue**: The `/verify` endpoint (`work_history.py:828`) hardcodes `action_type = 'call_attempt'` when creating the `background_tasks` row. It also omits `sequence_id` and `sequence_version` — those are only set later by the bridge's UPDATE.

**Root cause**: The INSERT was written before multi-channel sequences existed. It assumes all verifications start with a voice call.

**Code path**:
```
POST /api/v1/verify
  → work_history.py:798 INSERT INTO background_tasks (
      ...
      action_type,        ← 'call_attempt' HARDCODED (line 828)
      current_sequence_step  ← 1 (correct)
      -- sequence_id       ← NOT SET at INSERT time
      -- sequence_version  ← NOT SET at INSERT time
    )
  → prefect_bridge.py:516 UPDATE background_tasks SET
      sequence_id = $4,        ← SET here, from resolution.steps[0].id
      sequence_version = $5    ← SET here, from resolution.steps[0].version
```

**Impact**: After Gap B fix, step 1 will be email (`channel_type = 'email'`), but the task will say `action_type = 'call_attempt'`. The orchestrator dispatches based on `action_type`, so it will attempt a voice call instead of sending an email.

**Proposed fix**: Resolve the sequence at INSERT time (the SLA service is already called at line 778), use step 1's `channel_type` to set `action_type`, and write `sequence_id` + `sequence_version` directly in the INSERT:

```python
# After SLA resolution (line 778), also resolve the full sequence
resolution = await sla_service.resolve_check_sequence(
    check_type_name=request.check_type.value,
    customer_id=user.customer_id,
    client_ref=getattr(request, 'client_id', None),
)
step_1 = resolution.steps[0] if resolution and resolution.steps else None

channel_to_action = {
    'voice': 'call_attempt', 'email': 'email_attempt',
    'sms': 'sms_attempt', 'whatsapp': 'whatsapp_attempt',
}
action_type = channel_to_action.get(
    step_1.channel_type if step_1 else 'voice', 'call_attempt'
)
sequence_id = step_1.id if step_1 else None
sequence_version = step_1.version if step_1 else None
```

Then update the INSERT to include `sequence_id` and `sequence_version`, and use the resolved `action_type` instead of the hardcoded `'call_attempt'`.

The bridge UPDATE becomes a belt-and-suspenders confirmation rather than the only place these fields get set.

---

## 3. Dependency Graph

```
Gap B (duplicate rows) ←── ROOT CAUSE
  ↓ enables
Gap F (action_type + sequence_id at INSERT) ←── depends on B for correct step 1
  ↓ enables
Gap C (sequence version locking in advance_sequence) ←── depends on F writing version
  ↓ enables
Gap A (deployment convergence) ←── completes the chain
  ↓ enables
End-to-end flow via API → email×2 → voice×2 (no manual triggers)

Gap D (enum → DB-driven) ←── independent
Gap E (webhook removal) ←── independent, low priority
```

**Critical path**: B → F → C → A (fix in this order)

---

## 4. Execution Plan

### Decisions (User-Approved 2026-03-10)
- **Default SLA**: Email-first (2× email, 5 min → 2× voice, 5 min)
- **Legacy deployment**: Retire `voice-verification` entirely
- **CheckTypeEnum**: Replace with DB-driven validation via `check_types` table
- **Webhooks**: Remove immediately (log_state_to_db + Logfire provide full coverage)

### Phase 1: Sequence Data Fix (15 min)
- Use `replace_sequence_with_versioning()` from `check_sequence_service.py` to create clean default:
  - Step 1: Email Outreach — channel_type='email', max_attempts=2, delay_hours=0.083 (5 min)
  - Step 2: Email Reminder — channel_type='email', max_attempts=2, delay_hours=0.083
  - Step 3: Voice Call — channel_type='voice', max_attempts=2, delay_hours=0.083
  - Step 4: Voice Retry — channel_type='voice', max_attempts=2, delay_hours=0.083
- Old rows automatically archived
- Verify: `resolve_check_sequence('work_history', 1)` returns 4 steps, step 1 = email

### Phase 2: Fix action_type + sequence_id at INSERT (20 min)
- In `work_history.py:create_verification_task()`:
  - Resolve full sequence (not just SLA hours)
  - Use step 1's `channel_type` to determine `action_type`
  - Write `sequence_id` and `sequence_version` in the INSERT
- Verify: After INSERT, `background_tasks` row has `action_type='email_attempt'`, correct `sequence_id`

### Phase 3: Sequence Version Locking in advance_sequence (15 min)
- Add `sequence_version` filter to the 3-tier CTE in `advance_sequence()`
- Ensures advancement stays within the same version assigned at task creation
- Verify: Step 1 (email) exhausted → advances to step 2 (email), not a different version's step 2

### Phase 4: Deployment Convergence (15 min)
- Confirm `prefect_bridge.py` targets `verification-orchestrator/verification-orchestrator` (already updated)
- Ensure bridge passes `task_id`, `check_type`, `sequence_id`, `sequence_version` to flow
- Verify: Prefect flow run uses verification-orchestrator, not voice-verification

### Phase 5: CheckType DB-Driven Validation (10 min)
- Replace `CheckTypeEnum` with runtime DB lookup against `check_types` table
- Verify: `work_history_scheduling` accepted without 409

### Phase 6: Remove Webhook Hooks (10 min)
- Remove `send_completion_webhook` and `send_failure_webhook` from state_hooks.py
- Remove webhook endpoint at `api/webhooks/prefect.py`
- Keep `log_state_to_db` (direct DB updates + Logfire spans)
- Verify: Flow completes without ConnectError, Logfire traces all transitions

### Phase 7: E2E Validation (live test with user as verifier)
- Submit `work_history` case via `/verify` API
- Verify: email sent (step 1) → 5 min → email retry (step 1 retry) → step exhausted → advance
- Verify: email sent (step 2) → 5 min → email retry (step 2 retry) → step exhausted → advance
- Verify: voice call (step 3) → user answers → result recorded → sequence advances or terminates
- Verify: guard checks block dispatch for terminal cases

---

## 5. Key Design Insight: Frontend Already Models This Correctly

The V3.2 SLA configuration UI (`VerificationChannelsSection.tsx`) models sequences as:
- **PRIMARY channel** (e.g., email) with its own retry config (maxRetries, interval)
- **FALLBACK channel** (e.g., voice) with its own retry config
- **Escalation to manual review** (optional)

The adapter (`checkSequenceToSLA.ts`) converts flat DB steps to this structure:
- `step 1 (non-manual)` → primary channel
- `step 2 (non-manual)` → fallback/secondary channel
- `any manual step` → escalation toggle

The backend orchestrator should follow this same mental model: exhaust primary channel retries → advance to fallback channel → exhaust fallback retries → escalate or terminate.

The `replaceSequenceWithVersioning` API endpoint ensures atomic sequence replacement with version tracking, which is exactly what the orchestrator's `advance_sequence()` needs for robustness.

---

## 6. Questions for Review

1. **Default SLA**: Email-first (2× email, 5 min interval → 2× voice, 5 min interval) — is this the correct default?

2. **Voice-verification deployment**: Should it be retired entirely once the API converges on verification-orchestrator, or kept for backward compatibility?

3. **CheckTypeEnum → DB-driven**: Confirmed — link to `check_types` table as source of truth?

4. **Webhook deprecation**: Since `log_state_to_db` already updates `background_tasks.status` directly AND Logfire traces all transitions — should we deprecate the webhook hooks, or keep the belt-and-suspenders pattern?
