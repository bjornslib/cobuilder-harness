---
sd_id: SD-AURA-LIVEKIT-FIXES-001
prd_ref: PRD-AURA-LIVEKIT-FIXES-001
epic: "LiveKit Voice Agent Bug Fixes"
title: "LiveKit Agent — Validator Loop, TTS Crash, and Playout Deadlock Fixes"
version: "0.2"
status: draft
created: "2026-03-09"
author: "system3-meta-orchestrator"
---

# SD-AURA-LIVEKIT-FIXES-001: LiveKit Agent Bug Fixes

**Epic:** LiveKit Voice Agent Bug Fixes
**Source PRD:** PRD-AURA-LIVEKIT-FIXES-001
**Date:** 2026-03-09
**Author:** System 3 (root cause analysis from live session log)
**Status:** Draft

---

## 1. Business Context

**Goal**: Fix three production-confirmed bugs in the LiveKit voice agent (`verification_agents.py`) that cause incomplete calls, hard crashes, and deadlocked endings.

**User Impact**: Employment verification calls currently fail to complete cleanly when a verifier volunteers information out of order — the validator loops infinitely, the TTS crashes, and the call ending deadlocks. Every live call is affected by the playout deadlock risk.

**Success Metrics**:
- Zero `ToolError: CANNOT COMPLETE` loops when employment type was voluntarily provided
- Zero TTS 400 errors during normal call completion
- Zero `wait_for_playout` circular wait warnings in call end logs

**Constraints**:
- Changes are isolated to `verification_agents.py` and `verification_prompts.py`
- No changes to the LiveKit SDK or Prefect orchestration layer
- Must not regress happy-path (agent explicitly asks all questions)

**Research Findings**:
- Empty segment guard for TTS already implemented via `safe_tts_synthesize()` and `EmptySegmentGuardTTS` class
- Current `_end_call_internal` implementation contains problematic code causing circular wait: `await self.session.current_speech`
- Current validator logic in `validate_conditional_questions_asked()` raises `ToolError` when fields weren't explicitly asked by the agent
- Research confirms the LiveKit SDK's `ctx.wait_for_playout()` is the correct API for preventing circular dependencies

---

## 2. Technical Architecture

### 2.1 System Components

```
VerificationAgent
├── validate_conditional_questions_asked()   ← BUG 1: validator logic (already has TTS guard)
│   └── LLM prompt → ToolError loop when field wasn't explicitly asked
└── complete_verification() tool
    └── calls validator, raises ToolError
        └── mid-sentence ToolError → empty TTS segment (TTS guard exists but may not be used)

CallClosingAgent
└── end_call() tool
    └── _end_call_internal()
        └── await self.session.current_speech   ← BUG 3: circular wait (CONFIRMED in code)
```

**Research Findings**:
- The TTS guard mechanism exists via `safe_tts_synthesize()` and `EmptySegmentGuardTTS` class, but may not be properly integrated in all speech synthesis paths
- The validator logic in `validate_conditional_questions_asked()` checks if agent explicitly asked required questions, not if information was provided by verifier
- The circular wait issue is confirmed in `_end_call_internal()` method where `await self.session.current_speech` creates dependency loop

### 2.2 Data Models

No schema changes. All fixes are logic-only within existing agent classes.

### 2.3 API Contracts

No API changes. Internal agent tool changes only.

---

## 3. Implementation Approach

### 3.1 Technology Choices

| Choice | Technology | Rationale |
|--------|-----------|-----------|
| Playout wait | `ctx.wait_for_playout()` | LiveKit SDK-recommended pattern for tool-owned speech handles (RESEARCH: confirmed this is correct approach) |
| TTS guard | `text.strip()` pre-check | Prevents 400 from OpenAI TTS on zero-content segments (RESEARCH: already implemented via `safe_tts_synthesize()` function) |
| Validator logic | Separate "answered" from "asked" tracking | Decouples data completeness from conversation protocol (RESEARCH: current implementation checks "asked" not "received") |

**Research Findings**:
- The TTS guard mechanism already exists in the codebase via `safe_tts_synthesize()` function and `EmptySegmentGuardTTS` class
- Current validator logic in `validate_conditional_questions_asked()` specifically checks if the agent asked the questions, not if the information was provided by the verifier
- The circular wait issue in `_end_call_internal()` specifically uses `await self.session.current_speech` which creates the circular dependency

### 3.2 Key Design Decisions

**Decision 1: Validator should check field completion, not question asking**
- **Context**: The validator blocks `complete_verification` if the agent didn't explicitly ask about employment type. But the verifier may volunteer it. Research confirms current implementation checks if questions were "asked" not if field values were "received".
- **Options considered**:
  - (A) Require agent to always ask, even if answer was volunteered — poor UX, unnatural conversation
  - (B) Validator checks if field value was *received in any turn*, not just if agent asked — correct
  - (C) Update agent system prompt to always explicitly ask employment type even when volunteered — workaround, doesn't fix root validator logic
- **Chosen**: Option B — validator checks field completeness across the conversation regardless of who initiated
- **Trade-offs**: The validator's "asked" purpose is softened; for strict protocol enforcement (regulated contexts), Option A may be preferable

**Decision 2: ctx.wait_for_playout() replaces direct speech handle await**
- **Context**: `end_call` tool awaits `self.session.current_speech` — but that handle belongs to the turn that invoked `end_call`, creating a circular dependency. Research confirms this pattern exists in current code.
- **Chosen**: Use `await ctx.wait_for_playout()` on the `RunContext` passed to the tool
- **Trade-offs**: None — this is the LiveKit SDK's explicit design intent for this exact pattern

**Decision 3: TTS guard integration verification**
- **Context**: Research shows empty/punctuation-only segments still occur when `ToolError` interrupts mid-reply, but the TTS guard mechanism already exists via `safe_tts_synthesize()` and `EmptySegmentGuardTTS`. The issue may be that not all TTS call paths use the guard.
- **Chosen**: Ensure all TTS synthesis paths route through the guard mechanism, and add additional validation to catch segments that slip through
- **Trade-offs**: Minimal — ensures existing guard mechanism is properly utilized across all synthesis paths

**Research Findings**:
- Current implementation already includes TTS guard mechanisms (`safe_tts_synthesize`, `EmptySegmentGuardTTS`) suggesting the TTS crash issue might be due to some paths not using the guard
- Validator logic specifically examines chat history to see if agent asked questions, not whether information was provided by the verifier
- Circular wait issue is confirmed at lines 1578-1582 in `_end_call_internal()` method where `await self.session.current_speech` is used

### 3.3 Integration Points

| Integration | Type | Direction | Notes |
|-------------|------|-----------|-------|
| OpenAI TTS | REST API | Outbound | Input must contain at least one letter/digit |
| LiveKit `RunContext` | SDK | Internal | `ctx.wait_for_playout()` is the safe playout wait API |
| VerificationAgent chat history | In-memory | Internal | Validator reads message history |

---

## 4. Functional Decomposition

### Capability: Candidate-Claimed Context Snapshot

#### Feature: Pre-Call Claimed-Values Snapshot for Voice Mode
- **Description**: Inject a structured table of all HR-claimed field values into the voice agent's system prompt at initialization, mirroring the "Verification Context" table that chat mode already receives.
- **Inputs**: `CandidateInfo` fields — `start_date`, `end_date`, `position`, `employment_type`, `supervisor_name`, `salary`, `reason_for_leaving`, `eligibility_for_rehire` (conditional on `verify_fields` flags)
- **Outputs**: Updated `get_work_history_verification_prompt()` signature accepts these values and renders them as a Verification Context block at the top of the prompt
- **Behavior**:
  ```
  ## Verification Context (HR-claimed values to verify)
  | Field              | Claimed Value          |
  |--------------------|------------------------|
  | Candidate          | {candidate_name}       |
  | Company            | {company}              |
  | Position           | {position}             |
  | Start date         | {start_date}           |
  | End date           | {end_date or 'current'}|
  | Employment type    | {employment_type}      |  ← only if verify_fields.employment_type
  | Supervisor name    | {supervisor_name}      |  ← only if verify_fields.supervisor_name
  | Salary             | {salary}               |  ← only if verify_fields.salary
  | Reason for leaving | {reason_for_leaving}   |  ← only if verify_fields.reason_for_leaving
  | Rehire eligibility | {eligibility_for_rehire}| ← only if verify_fields.eligibility_for_rehire
  ```
  Only rows where the verify flag is True AND a claimed value exists are rendered. Rows with `None` claimed values are omitted (the field is still required but no prior value to compare against).
- **Why this matters**: Without this snapshot, when a verifier volunteers "he was part-time", the agent has no context that `employment_type` was claimed as "full_time" — it cannot recognize this as a relevant answer, cannot flag a discrepancy, and the validator has nothing to check field completeness against.
- **Depends on**: None (foundational enabler for Validator Correctness)
- **Caller in `verification_agents.py`**: `VerificationAgent.__init__` already has `candidate_info.start_date`, `candidate_info.end_date`, `candidate_info.employment_type`, etc. — they just need to be passed through to `get_work_history_verification_prompt()`.

---

### Capability: Validator Correctness

#### Feature: Field-Complete Validation
- **Description**: Validator accepts `complete_verification` if all required field *values* are present in the conversation, regardless of whether the agent initiated the question
- **Inputs**: Full chat history, list of required fields, **and claimed values from `CandidateInfo`** (enables discrepancy detection)
- **Outputs**: `allowed=True` if all fields answered; `allowed=False` with specific missing fields
- **Behavior**: For each required field, scan both agent and user turns for the field value. If found in any turn (agent question + answer, or verifier volunteering), mark as complete. Only reject if the value is genuinely absent.
- **Depends on**: Pre-Call Claimed-Values Snapshot (ensures claimed values are available for comparison)

#### Feature: Validator Prompt Precision
- **Description**: LLM validator prompt updated to clearly distinguish "field answered" from "agent asked"
- **Inputs**: Updated system prompt for `validate_conditional_questions_asked()`
- **Outputs**: Consistent accept/reject decisions
- **Behavior**: Prompt instructs LLM: "Check if each required field VALUE appears anywhere in the conversation — either the agent asked and got an answer, or the caller volunteered it. Both count as complete. The claimed value (if known) is provided for reference — a discrepancy (different value stated) also counts as the field being answered."
- **Depends on**: Field-Complete Validation

---

### Capability: TTS Stability

#### Feature: Empty Segment Guard
- **Description**: Before forwarding text to OpenAI TTS, validate the segment contains at least one alphanumeric character
- **Inputs**: Text segment from LLM speech stream
- **Outputs**: Synthesis call (if valid) or silent skip (if empty)
- **Behavior**: `if not text.strip(): return` before TTS API call. Log skipped segments at DEBUG level.
- **Depends on**: None (independent fix)

---

### Capability: Clean Call Ending

#### Feature: Non-Circular Playout Wait
- **Description**: Replace `await self.session.current_speech` in `_end_call_internal` with `await ctx.wait_for_playout()`
- **Inputs**: `RunContext` passed to `end_call` tool
- **Outputs**: Clean call termination after agent's final utterance completes
- **Behavior**: `ctx.wait_for_playout()` waits for the speech handle to complete without creating a circular dependency. The tool can then delete the room.
- **Depends on**: None (independent fix)

---

## 5. Dependency Graph

### Foundation Layer (Independent — Can Fix in Any Order)
- **Empty Segment Guard**: No dependencies
- **Non-Circular Playout Wait**: No dependencies
- **Pre-Call Claimed-Values Snapshot**: No dependencies (prompt-only change to `verification_prompts.py` + `VerificationAgent.__init__`)

### Layer 1: Depends on Foundation
- **Field-Complete Validation**: Depends on Pre-Call Claimed-Values Snapshot (claimed values needed to assess field completeness)
- **Validator Prompt Precision**: Depends on Field-Complete Validation

All four changes can be made in a single pass — the snapshot is a prompt change, the validator is a prompt + logic change, TTS guard is a guard clause, playout is a one-line swap.

---

## 6. Acceptance Criteria (Per Feature)

### Feature: Pre-Call Claimed-Values Snapshot

**Given** a voice verification call with `employment_type` claimed as "full_time" in `CandidateInfo`
**When** `VerificationAgent.__init__` is called with `mode="voice"`
**Then** the agent's system prompt contains a "Verification Context" table showing `employment_type: full_time`

**Given** a voice verification call where `supervisor_name` is not in `verify_fields`
**When** the prompt is rendered
**Then** the supervisor_name row is omitted from the Verification Context table

---

### Feature: Field-Complete Validation

**Given** a verification call where the verifier volunteers "He was part time employed" without being asked
**When** the agent calls `complete_verification`
**Then** the validator accepts the employment type field as answered
**And** no `ToolError: CANNOT COMPLETE` loop occurs

**Given** a verification call where employment type was never mentioned by either party
**When** the agent calls `complete_verification`
**Then** the validator correctly rejects with "employment type not answered"

---

### Feature: Empty Segment Guard

**Given** a `ToolError` interrupts an agent reply mid-sentence
**When** the next LLM response emits a punctuation-only first segment (e.g., `"."`)
**Then** TTS synthesis is skipped for that segment
**And** no 400 error is raised
**And** the call continues normally

---

### Feature: Non-Circular Playout Wait

**Given** the `CallClosingAgent` completes its farewell message and calls `end_call`
**When** `_end_call_internal` runs
**Then** no `wait_for_playout failed: cannot call SpeechHandle.wait_for_playout() from inside function tool` warning appears in logs
**And** the room is deleted cleanly after the farewell finishes playing

---

## 7. Test Strategy

### Test Pyramid

| Level | Coverage | Tools | What It Tests |
|-------|----------|-------|---------------|
| Unit | 80% | pytest | Validator accept/reject logic with synthetic chat histories |
| Integration | 20% | pytest + mock LiveKit session | TTS guard and playout wait with mock SDK objects |
| E2E | manual | Live call | Full happy path + volunteered-info scenario |

### Critical Test Scenarios

| Scenario | Type | Priority |
|----------|------|----------|
| Verifier volunteers employment type → validator accepts | Unit | P0 |
| Employment type genuinely absent → validator rejects | Unit | P0 |
| Punctuation-only TTS segment → skipped silently | Unit | P0 |
| `end_call` completes without circular wait warning | Integration | P0 |
| Full happy-path call → clean termination | E2E | P1 |

---

## 8. File Scope

### Modified Files

| File Path | Changes |
|-----------|---------|
| `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/verification_agents.py` | (1) Update `validate_conditional_questions_asked()` prompt to check field completeness not question-asking; (2) Pass `start_date`, `end_date`, and claimed conditional field values from `CandidateInfo` through to `get_work_history_verification_prompt()`; (3) Verify TTS guard mechanism integrates with all speech synthesis paths; (4) Replace `await self.session.current_speech` with `await ctx.wait_for_playout()` in `_end_call_internal` |
| `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/verification_prompts.py` | (1) Update `get_work_history_verification_prompt()` signature to accept `start_date`, `end_date`, and claimed conditional values; (2) Render "Verification Context" table at the top of the prompt (matching the pattern in `chat_prompts.py:get_chat_verification_prompt`); (3) Update pre-completion checklist to reference claimed values for discrepancy detection |

**Research Findings**:
- The TTS guard mechanisms (`safe_tts_synthesize`, `EmptySegmentGuardTTS`) are already implemented in the codebase
- The circular wait issue is confirmed in `_end_call_internal()` method where `await self.session.current_speech` creates dependency loop
- The validator logic specifically checks if agent asked questions, not if information was provided by verifier

### Files NOT to Modify

| File Path | Reason |
|-----------|--------|
| `agencheck-communication-agent/helpers/subthread_cycle_helper.py` | Separate fix being handled by another colleague |
| `agencheck-communication-agent/livekit_prototype/cli_poc/voice_agent/config.py` | No config changes needed |
| All Prefect flow files | Out of scope |

---

## 9. Risks & Technical Concerns

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Validator change regresses happy-path (agent asked + answered) | Low | High | Unit test both paths before deploying |
| `ctx.wait_for_playout()` not available in installed LiveKit SDK version | Low | High | Check SDK version; error message in logs mentioned the correct API, confirming it exists |
| Empty-segment guard drops valid short utterances | Low | Low | Log at DEBUG level; review logs post-deploy |
| Validator now too permissive (accepts partial data as complete) | Medium | Medium | Ensure validator still checks that a *value* was stated, not just the topic mentioned |
| TTS guard already exists but not properly integrated in all paths | Medium | Medium | Verify all TTS synthesis calls use EmptySegmentGuardTTS wrapper (RESEARCH FINDING) |
| Validator logic currently checks "asked" not "received" - hard to change | High | Medium | Carefully refactor validate_conditional_questions_asked() to check field values in chat history regardless of who provided them |
| Claimed value snapshot changes `get_work_history_verification_prompt()` signature | Low | Medium | Add new optional kwargs with defaults; existing callers that don't pass them get the same prompt as before, just without the snapshot table |

**Research-based Risk Mitigation**:
- Since TTS guard mechanisms already exist, the focus should be on ensuring proper integration throughout the codebase rather than implementing from scratch
- The validator logic change requires careful parsing of chat history to identify field values regardless of whether they came from agent questions or verifier statements

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-03-09 | system3-meta-orchestrator | Initial design from live session root cause analysis |
| 0.2 | 2026-03-09 | system3-meta-orchestrator | Added Feature: Pre-Call Claimed-Values Snapshot for Voice Mode; updated File Scope to include verification_prompts.py; updated dependency graph and risks; aligned with chat mode pattern in chat_prompts.py |
