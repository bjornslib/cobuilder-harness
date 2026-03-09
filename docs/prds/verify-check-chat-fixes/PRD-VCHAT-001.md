---
title: "PRD-VCHAT-001: Verify-Check Chat/Voice Integration Fixes"
status: active
type: reference
last_verified: 2026-03-08
grade: authoritative
---

# PRD-VCHAT-001: Verify-Check Chat/Voice Integration Fixes

## 1. Business Goal

The `/verify-check/[task_id]` page supports both chat and voice verification modes. Currently, five integration gaps degrade the user experience and data completeness:

1. Chat messages don't update form fields (voice does)
2. Chat transcripts aren't stored on S3 (PostCheckProcessor can't evaluate chat-only sessions)
3. Voice-to-chat handback loses agent context
4. Mode switch messages are visible to the chat agent, producing unnatural responses
5. Room cleanup crashes when no egress/voice recording exists

## 2. Target Repo

`/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck`

- Frontend: `agencheck-support-frontend/app/verify-check/[task_id]/`
- Backend: `agencheck-support-agent/live_form_filler/`
- Prefect flows: `agencheck-support-agent/prefect_flows/flows/tasks/`

## 3. Epics

### E1: Chat Transcript → Form Field Extraction

**Goal**: Chat messages update form fields identically to voice transcripts.

**Approach**: When the chat agent (or user) sends a message, emit it as a transcription-format event on the `form_events` data channel so `listener_service.py`'s existing `process_transcription_data()` pipeline extracts fields via the form_filler_agent.

**Key files**:
- `agencheck-support-agent/live_form_filler/services/listener_service.py` (lines 238-340)
- `agencheck-support-agent/live_form_filler/agent.py` (chat_text_handler)
- `agencheck-support-frontend/app/verify-check/[task_id]/_components/FormEventEmitter.tsx`
- `agencheck-support-frontend/app/verify-check/[task_id]/_hooks/useAgentMessages.ts`

**Acceptance criteria**:
- AC1.1: When user sends a chat message containing field data (e.g., "John started in January 2020"), the form field updates within 3 seconds
- AC1.2: When agent sends a chat response confirming data, it also triggers extraction
- AC1.3: Existing voice field extraction continues working unchanged

### E2: Chat + Voice Transcript S3 Storage

**Goal**: All transcripts (chat and voice) stored on S3. PostCheckProcessor evaluates both.

**Approach**: Backend accumulates chat messages in memory during the session. On room close or form submission, upload chat transcript JSON to S3. PostCheckProcessor reads both `transcript_s3_key` (voice) and `chat_transcript_s3_key` (chat).

**Key files**:
- `agencheck-support-agent/live_form_filler/agent.py` (chat message accumulation)
- `agencheck-support-agent/prefect_flows/flows/tasks/process_post_call.py` (PostCheckProcessor)
- S3 upload utility (existing pattern in codebase)

**Acceptance criteria**:
- AC2.1: Chat-only session produces `transcripts/tasks/{task_id}/chat-{timestamp}.json` on S3
- AC2.2: Mixed session (chat + voice) produces both chat and voice transcript files
- AC2.3: PostCheckProcessor evaluates chat transcript when voice transcript is absent
- AC2.4: PostCheckProcessor evaluates BOTH when both exist

### E3: Voice-to-Chat Handback

**Goal**: When user ends voice call and returns to chat, the chat agent receives full voice conversation context.

**Approach**: On mode_switch to chat, inject a context summary (what was discussed, what fields were confirmed) into the chat agent's system prompt or conversation history. Do NOT spawn a new agent — reuse the existing session.

**Key files**:
- `agencheck-support-agent/live_form_filler/agent.py` (chat_text_handler, handle_voice_escalation)
- `agencheck-support-frontend/app/verify-check/[task_id]/page.tsx` (handleEndCall)

**Acceptance criteria**:
- AC3.1: After ending voice call, chat agent knows what was discussed during voice
- AC3.2: Chat agent doesn't re-ask questions already answered during voice
- AC3.3: Chat agent greets naturally (e.g., "Welcome back to chat. We confirmed X during the call...")

### E4: Silent Mode Switch

**Goal**: Mode switch messages are invisible to the chat agent LLM.

**Approach**: Filter mode_switch messages in the backend before they reach the LLM. Use them as control signals only (to trigger context injection per E3), not as user messages.

**Key files**:
- `agencheck-support-agent/live_form_filler/agent.py` (chat_text_handler)
- `agencheck-support-frontend/app/verify-check/[task_id]/page.tsx` (mode_switch send)

**Acceptance criteria**:
- AC4.1: Agent does NOT respond to mode_switch messages with text like "I see you're switching modes"
- AC4.2: Mode switch triggers E3 context injection silently
- AC4.3: User sees only natural conversation flow, no technical artifacts

### E5: Graceful Room Cleanup Without Egress

**Goal**: Room cleanup succeeds regardless of whether a voice call occurred.

**Approach**: Make egress/recording handling conditional. If no voice session existed, skip recording download and proceed with chat-only PostCheckProcessor path.

**Key files**:
- `agencheck-support-agent/prefect_flows/flows/tasks/process_post_call.py`
- `agencheck-support-agent/live_form_filler/services/listener_service.py` (cleanup)
- `agencheck-support-frontend/app/verify-check/[task_id]/page.tsx` (room disconnect)

**Acceptance criteria**:
- AC5.1: Chat-only session closes without errors (no egress expected)
- AC5.2: Mixed session closes correctly, recording uploaded
- AC5.3: PostCheckProcessor handles missing recording_s3_key gracefully (returns valid result using chat transcript only)

## 4. Dependencies

- E4 depends on E3 (silent mode switch triggers context injection)
- E2 is independent
- E1 is independent
- E5 is independent
- E3 depends on E1 (context injection uses the same transcript accumulation)

## 5. Out of Scope

- Phone-based verification flow
- Agent LLM model selection (stays as-is)
- SSE infrastructure changes
- New UI components (existing chat/voice UI is sufficient)

## 6. Success Metrics

- Chat-only verification sessions produce complete form data (parity with voice)
- PostCheckProcessor generates valid reports for chat-only, voice-only, and mixed sessions
- Zero errors on room cleanup for any session type
- User cannot distinguish mode switch from natural conversation flow
