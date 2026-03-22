# SD-VCHAT-001: Chat Agent Form State & Behaviour Fixes

**Status**: Draft v1
**Date**: 2026-03-14
**Parent PRD**: PRD-VCHAT-001-CHAT-AGENT-FIXES
**Target repo**: `my-org3/my-org/my-project`

---

## 1. Architecture Overview

The fix replicates the voice agent's "snapshot-in-instructions" pattern for chat mode and removes spurious `generate_reply()` calls that cause the agent to speak when it shouldn't.

```
Frontend (verify-check page)
    │
    │ FORM_STATE_SNAPSHOT (trigger=discrepancy)
    │ via data channel "form_events"
    ▼
agent.py :: handle_form_event()
    │
    ├─ Store snapshot in session.userdata["field_snapshot"]
    ├─ Store wasEmployed in session.userdata["employment_gate_status"]
    │
    ├─ Construct NEW VerificationAgent(
    │      mode="chat",
    │      field_snapshot=updated_fields,    ◀── NEW: chat gets snapshot
    │      was_employed=wasEmployed,
    │      chat_ctx=session.chat_ctx,        ◀── preserves conversation
    │  )
    ├─ session.update_agent(new_agent)       ◀── swap atomically
    └─ session.generate_reply(user_input=    ◀── focused discrepancy msg
          "[SYSTEM: discrepancy on {field}...]")
```

---

## 2. Epic 1: Chat Agent Form State Persistence

### 2.1 Remove Mode Gate in VerificationAgent

**File**: `my-project-communication/livekit_prototype/cli_poc/voice_agent/verification_agents.py`
**Line**: 1219

**Current**:
```python
if field_snapshot and mode == "voice":
```

**Change to**:
```python
if field_snapshot:
```

This allows the form state section builder (lines 1219-1264) to run for both voice and chat modes. The builder already produces human-readable text suitable for both modalities.

### 2.2 Adjust Employment Instruction Text for Chat Mode

**File**: Same as 2.1, lines 1241-1258

The employment instruction text currently uses voice-oriented phrasing. Add candidate name and company interpolation, and adjust wording to be mode-neutral:

**Current** (line 1253-1258):
```python
else:  # was_employed is True
    employment_instruction = (
        f"Employment was already confirmed in chat. "
        f"Begin with the FIRST UNCONFIRMED field. "
        f"DO NOT ask about employment or already-confirmed fields."
    )
```

**Change to**:
```python
else:  # was_employed is True
    employment_instruction = (
        f"Employment confirmed: {candidate_name} was employed at {company}. "
        f"Begin with the FIRST UNCONFIRMED field. "
        f"DO NOT ask about employment or already-confirmed fields."
    )
```

Apply the same `{candidate_name}` / `{company}` interpolation to the `was_employed is None` and `was_employed is False` branches.

### 2.3 Rebuild Agent on Discrepancy Snapshot

**File**: `my-project-communication/livekit_prototype/cli_poc/voice_agent/agent.py`
**Function**: `handle_form_event()` (line 1913)
**Section**: `FORM_STATE_SNAPSHOT` with `trigger == "discrepancy"` (lines 1975-2022)

**Replace** the existing discrepancy handler block (lines 1975-2022) with:

```python
# trigger == "discrepancy"
discrepant = [f for f in fields if f.get("hasDiscrepancy")]
pending = [f for f in fields if not f.get("verifierResponseReceived")]

if not discrepant:
    logger.warning("[Chat] FORM_STATE_SNAPSHOT(discrepancy) received but no discrepant fields found")
    return

# ── Rebuild VerificationAgent with updated snapshot ──
candidate_info = session.userdata.get("candidate_info")
if not candidate_info:
    logger.error("[Chat] No candidate_info in userdata — cannot rebuild agent")
    return

from .verification_agents import VerificationAgent

new_agent = VerificationAgent(
    candidate_info=candidate_info,
    contact_info="chat verifier",
    verification_type=session.userdata.get("verification_type", "work_history"),
    chat_ctx=session.chat_ctx,          # preserve full conversation history
    skip_recap=True,
    mode="chat",
    field_snapshot=fields,              # updated snapshot
    was_employed=event.get("wasEmployed"),
)
session.update_agent(new_agent)         # atomic swap — NOT awaited

# ── Generate focused discrepancy response ──
disc_field = discrepant[-1]
disc_label = disc_field.get("label", disc_field.get("fieldName"))
disc_claimed = disc_field.get("candidateClaimed", "?")
disc_verified = disc_field.get("verifierResponse", "?")

next_pending_label = pending[0].get("label", pending[0].get("fieldName")) if pending else None
next_instruction = (
    f"After confirming, move to {next_pending_label}."
    if next_pending_label else
    "All fields have now been verified — thank the verifier and let them know they can submit."
)

session.generate_reply(
    user_input=(
        f"[SYSTEM: The verifier entered '{disc_verified}' for {disc_label}, "
        f"which differs from the candidate's claim of '{disc_claimed}'. "
        f"Ask the verifier to confirm this is correct before proceeding.\n\n"
        f"{next_instruction}]"
    )
)
```

**Key changes**:
- Agent is rebuilt with the full updated snapshot, giving the LLM persistent context.
- `session.chat_ctx` is preserved so conversation history is not lost.
- The focused `generate_reply` still fires so the agent addresses the discrepancy.
- The verbose `snapshot_text` block is removed from the system message — it's now in the agent's instructions.

### 2.4 Initial Handoff: Pass Empty Snapshot

**File**: `verification_agents.py`
**Class**: `ChatWelcomeAgent.confirm_ready_and_handoff()` (in the tool method)

No change needed. The initial handoff does not pass `field_snapshot` (defaults to `None`), so the form state section won't be built. The first snapshot arrives when the frontend fires a discrepancy event. This is correct — there's nothing to show until the verifier starts filling fields.

---

## 3. Epic 2: Silent Confirmations & Explicit Text

### 3.1 Remove generate_reply from EMPLOYMENT_GATE Confirmed

**File**: `agent.py`
**Lines**: 2024-2039

**Current**:
```python
elif event_type == "EMPLOYMENT_GATE":
    gate_value = event.get("value", "")
    if gate_value == "denied":
        session.generate_reply(
            user_input=(
                "[SYSTEM: The verifier indicated the candidate was NOT employed. "
                "Acknowledge this and ask if they would like to provide any additional details.]"
            )
        )
    else:
        session.generate_reply(
            user_input=(
                "[SYSTEM: The verifier confirmed the candidate was employed. "
                "Begin verifying individual fields starting with start date.]"
            )
        )
```

**Change to**:
```python
elif event_type == "EMPLOYMENT_GATE":
    gate_value = event.get("value", "")
    # Always store gate status
    session.userdata["employment_gate_status"] = (gate_value != "denied")

    if gate_value == "denied":
        candidate_info = session.userdata.get("candidate_info")
        candidate_name = getattr(candidate_info, "candidate_name", "the candidate")
        company_name = getattr(candidate_info, "company", "the company")
        session.generate_reply(
            user_input=(
                f"[SYSTEM: The verifier indicated that {candidate_name} was NOT employed "
                f"at {company_name}. Acknowledge this and ask if they would like to "
                f"provide any additional details.]"
            )
        )
    # else: confirmed — stay silent. The form drives the UX; agent waits
    # for discrepancy events or verifier chat messages.
```

### 3.2 Explicit Names in Snapshot Text

Already addressed in §2.2. The employment instruction text in VerificationAgent's form state builder now includes `{candidate_name}` and `{company}`.

---

## 4. Epic 3: Listener Date Awareness

### 4.1 Add Current Date to Listener User Message

**File**: `my-project-backend/live_form_filler/services/listener_service.py`
**Line**: ~421 (user_message template)

**Add** after the `## VERIFICATION CONTEXT` header:

```python
from datetime import datetime

user_message = f"""## VERIFICATION CONTEXT

**Current date**: {datetime.now().strftime('%B %d, %Y')}
**Fields to verify**: {', '.join(state.verify_fields)}
...
```

### 4.2 Add Current Date Rule to Form Filler System Prompt

**File**: `my-project-backend/live_form_filler/agent.py`
**Line**: ~47 (within system_prompt, under DATE CALCULATION section)

**Add** rule 5:

```
5. **CURRENT DATE**: The current date is provided in the verification context.
   Use it to resolve relative expressions:
   - "last month" → subtract 1 month from current date
   - "two years ago" → subtract 2 years from current date
   - "still works here" / "currently employed" → end_date="Current"
```

---

## 5. File Change Summary

| File | Epic | Change |
|------|------|--------|
| `verification_agents.py` | E1 | Remove `mode == "voice"` gate (line 1219); add candidate/company to employment instructions (lines 1241-1258) |
| `agent.py` (`handle_form_event`) | E1 | Replace discrepancy handler with agent-rebuild pattern (lines 1975-2022) |
| `agent.py` (`EMPLOYMENT_GATE`) | E2 | Remove `generate_reply` from confirmed branch; add candidate/company to denied branch; store gate status (lines 2024-2039) |
| `listener_service.py` | E3 | Add `**Current date**` to user_message template (line ~421) |
| `live_form_filler/agent.py` | E3 | Add current-date rule to system prompt (line ~47) |

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Agent rebuild drops in-flight generation | `session.update_agent()` is synchronous and interrupts any pending generation. The subsequent `generate_reply()` starts clean. |
| Chat history lost on agent swap | `session.chat_ctx` is explicitly passed to the new agent constructor. |
| Circular import: `agent.py` imports `VerificationAgent` | Already imported at module level (`from .verification_agents import VerificationAgent` exists in several places). Move import to top of function if needed to avoid circular reference. |
| Form filler agent date calculations are imprecise | Acceptable — the form filler already handles relative dates ("4 years later") with ~0.9 confidence. Adding today's date improves accuracy for expressions like "last month" without changing the extraction pipeline. |

---

## 7. Testing Notes

- **E1 test**: Send a `FORM_STATE_SNAPSHOT` with `trigger="discrepancy"` in chat mode. Verify the agent's instructions contain the form state section. Verify conversation history is preserved.
- **E2 test**: Send `EMPLOYMENT_GATE` with `value="confirmed"`. Verify no agent response is generated. Send with `value="denied"`. Verify response includes candidate name and company.
- **E3 test**: Invoke form filler agent with a verifier statement like "he left last month". Verify extracted end_date uses the correct absolute date.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
