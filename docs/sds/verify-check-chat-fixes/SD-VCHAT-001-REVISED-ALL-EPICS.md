# SD-VCHAT-001: Revised Solution Design — All Epics (FINAL)

**Status**: Final draft for user review
**Date**: 2026-03-08
**PRD**: PRD-VCHAT-001 (Verify-Check Chat/Voice Fixes)

## Architecture Principle

**All chat and voice interactions happen within LiveKit (agent.py)**. The FastAPI layer (ag_ui_routes.py) handles HTTP API endpoints for the frontend form, SSE events, and listener queue management — but does NOT handle chat messages. Chat messages flow through the LK agent's `chat_text_handler` via the `lk.chat` text stream topic.

The listener subprocess joins the LK room as a hidden participant and receives data via `@room.on("data_received")`. It processes transcription-format data packets for field extraction.

**Key SDK fact (validated)**: The LK Agents SDK automatically populates `session.chat_ctx` with both user and assistant messages during voice mode. No manual injection needed. `session.update_agent()` does NOT auto-trigger an LLM response — only `on_enter()` or `generate_reply()` does.

---

## E1: Chat Field Extraction via Listener (REVISED)

*E6 (Share Chat with Listener) is merged into this epic — they are the same mechanism.*

### Problem
The listener subprocess only receives voice transcriptions via the `"transcription"` data channel topic. Chat messages (user confirmations, field data) never reach the listener, so no extraction runs on chat interactions.

### Previous (Wrong) Approach
Added HTTP endpoint `POST /listener/chat-message` in `ag_ui_routes.py`. Broke architecture — chat is handled by LK, not FastAPI.

### Correct Approach (Option B — User Confirmed)
The LK agent (`agent.py`) already publishes voice transcriptions to the room via `publish_transcription_to_room()` (lines 102-130). We extend this: when the agent processes a chat message, it ALSO publishes it as a data packet on the `"transcription"` topic with `source: "chat"`.

### Implementation

**File: `agent.py`**

Update `publish_transcription_to_room()` (lines 102-130) to accept optional `source` parameter:

```python
async def publish_transcription_to_room(
    room, text: str, speaker: str, is_final: bool = True, source: str = "voice"
):
    data = json.dumps({
        "type": "transcription",
        "text": text,
        "speaker": speaker,
        "is_final": is_final,
        "source": source,
    }).encode("utf-8")
    await room.local_participant.publish_data(data, topic="transcription")
```

In `chat_text_handler()` (~line 2135), publish BOTH user and assistant messages:

```python
# After user message is recorded (~line 2147):
asyncio.create_task(publish_transcription_to_room(
    ctx.room, text, "user", is_final=True, source="chat"
))

# After agent response is recorded (~line 2201):
asyncio.create_task(publish_transcription_to_room(
    ctx.room, latest_content, "agent", is_final=True, source="chat"
))
```

**File: `listener_service.py`**

In `process_transcription_data()` (~line 361), tag conversation_history entries with source:

```python
state.conversation_history.append({
    "speaker": speaker,
    "text": text_content,
    "timestamp": datetime.utcnow().isoformat(),
    "source": payload.get("source", "voice"),
})
```

### Extraction Trigger: User Messages Only

Matching the existing voice pattern, extraction should only run when a **user** message arrives, not on assistant-only messages. The listener already implements this: `process_transcription_data()` only invokes `form_filler_agent.run()` when `speaker == "user"` (line ~369). Assistant messages are recorded in `conversation_history` for context but do NOT trigger Groq extraction by themselves.

This means: if the assistant asks "Can you confirm XYZ?" and the user never responds, no extraction is triggered. The assistant's question is stored in conversation_history so that when the user eventually responds "Yes", the extraction agent has the full context (question + answer) to identify the confirmation.

### What to Remove
- Delete `ingest_chat_message()` endpoint from `ag_ui_routes.py`
- Delete `_chat_session_state` module-level dict from `ag_ui_routes.py`
- Delete `process_chat_transcription()` from `listener_service.py`
- Delete `_publish_chat_to_lk_room()` from `ag_ui_routes.py`
- Delete `SendDataRequest` / `DataPacket` / `lk_api` imports from `ag_ui_routes.py`
- Delete chat session auto-seeding from `/listener/register` and `/listener/start`

### Acceptance Criteria
1. When user sends a chat message, listener receives it via `data_received` with `source: "chat"`
2. When agent responds in chat, listener ALSO receives it with `source: "chat"` and `speaker: "agent"`
3. Listener's `conversation_history` includes both chat and voice entries with source tags
4. Groq extraction runs ONLY on user messages (not assistant-only), matching voice pattern
5. No HTTP endpoints used for chat message routing
6. Assistant messages are stored in history for context but don't trigger extraction alone

---

## E2: Chat Transcript S3 Upload & Dashboard Display (REVISED)

### Finding: Upload Already Implemented
Chat transcript upload is **already fully implemented** in `agent.py` lines 1673-1710:
- Chat history accumulated in `session.userdata["chat_history"]` (user: line 2147, agent: line 2201)
- On session end, if `call_type == "chat"`, uploads to S3 bucket `dev-aura-communicator-recordings`
- S3 key: `transcripts/tasks/{task_id}/chat-{timestamp}.json`
- Uses `upload_transcript_to_s3()` with 3-retry exponential backoff
- Stores `chat_transcript_s3_key` in userdata for downstream processing

### Fix Required: `call_type` Default for Chat Sessions
The default `call_type` is `"phone"` (line 895). For chat-only sessions that never escalate to voice, the upload conditional (`if call_type == "chat"`) is skipped.

**Fix**: Set `call_type = "chat"` at session initialization when `agent_type` metadata is `"chat"`:

```python
# In chat_verification_entrypoint() or session setup:
if merged_metadata.get("agent_type") == "chat":
    session.userdata["call_type"] = "chat"
```

### Sub_Threads Transcript Storage (NEW)

**Current pipeline** (voice only):
1. `on_session_end()` uploads voice transcript to S3
2. Redis Stream event `agencheck:calls:completed` triggers Prefect consumer
3. `post_call_processor.py` downloads transcript from S3
4. Calls `subthread_cycle_helper.py --action batch-import` to store in `sub_threads.all_messages` (JSONB)
5. Dashboard loads transcript from `sub_threads.all_messages` (Priority 1) or S3 fallback (Priority 3)

**What needs to change for chat+voice transcripts**:

The dashboard transcript endpoint (`GET /api/v1/verification-transcripts/{task_id}`, work_history.py lines 1830-1973) loads from `sub_threads.all_messages` first. We need to ensure BOTH voice and chat messages end up there in chronological order.

**Implementation**:

In `post_call_processor.py` (`_trigger_post_call_processing` or equivalent):
1. Download voice transcript from S3 (existing)
2. Download chat transcript from S3 (NEW — using `chat_transcript_s3_key`)
3. Merge both transcripts chronologically using `build_combined_transcript()` (already implemented in E2)
4. Tag each message with `source: "voice"` or `source: "chat"` for display differentiation
5. Store merged transcript in `sub_threads.all_messages` via `batch-import`

**Storage format** (extends existing):
```json
[
  {"role": "assistant", "content": "Can you confirm your employment at ABC Corp?", "timestamp": "2026-03-08T10:00:01Z", "source": "chat"},
  {"role": "user", "content": "Yes, I worked there from 2020 to 2023", "timestamp": "2026-03-08T10:00:15Z", "source": "chat"},
  {"role": "assistant", "content": "Thank you. Let me verify the dates...", "timestamp": "2026-03-08T10:01:00Z", "source": "voice"},
  {"role": "user", "content": "Sure, go ahead", "timestamp": "2026-03-08T10:01:05Z", "source": "voice"}
]
```

**No schema changes needed**: The `sub_threads.all_messages` column is JSONB and already accepts arbitrary message objects. Adding `source` field is backward-compatible. The `chat_transcript_s3_key` can be passed through the existing Redis Stream payload or stored in `session.userdata` → post-call payload.

### What to Remove
- Delete `_upload_chat_transcript()` from `listener_service.py` (wrong layer)

### Acceptance Criteria
1. Chat-only sessions upload transcript to S3 (verify `call_type` defaults correctly)
2. S3 verification: file exists at `s3://dev-aura-communicator-recordings/transcripts/tasks/{task_id}/chat-*.json`
3. Mixed sessions (chat+voice) produce merged transcript in `sub_threads.all_messages`
4. Merged transcript preserves chronological order across chat and voice
5. Each message tagged with `source: "chat"` or `source: "voice"`
6. Dashboard displays merged transcript correctly

---

## E3: Voice-to-Chat Handback (REVISED)

### Problem
When the user returns from voice to chat, the chat agent should have context of what was discussed in voice — without triggering a response or greeting.

### Previous (Wrong) Approach
`_inject_voice_context()` in `ag_ui_routes.py` with SSE events and synthetic greeting. Involved the listener (wrong). Triggered a response (wrong).

### Correct Approach
**Validated finding**: The LK Agents SDK automatically populates `session.chat_ctx` with both user and assistant messages during voice mode (confirmed via SDK source: `agent_activity.py` lines 1138-1140 for user, lines 1734-1741 for assistant). The chat_ctx is the single source of truth for the entire conversation across all modes.

The voice→chat mode switch handler (agent.py lines 2113-2131) already creates a new chat VerificationAgent with `chat_ctx=session.chat_ctx`. This means the chat agent inherits the **complete** voice conversation — ALL messages, not just recent ones.

**No manual injection, no synthetic messages, no greeting needed.**

### What the Agent Gets
When `session.update_agent(chat_agent)` is called with `chat_ctx=session.chat_ctx`:
- The chat agent sees ALL prior chat messages (from before voice escalation)
- ALL voice conversation entries (user speech transcriptions + assistant responses)
- The full chronological history

The agent simply waits for the user's next message. No `generate_reply()` is called. The agent does NOT auto-respond on `update_agent()` — it only responds when `on_enter()` calls `generate_reply()` or when the user sends a new message.

### Implementation
Ensure the voice→chat switch does NOT call `generate_reply()`:

```python
elif parsed.get("mode") == "chat":
    logger.info("[G15] Returning to chat mode — disabling audio inline")
    session.input.set_audio_enabled(False)
    session.output.set_audio_enabled(False)

    chat_agent = VerificationAgent(
        candidate_info=candidate_info,
        contact_info="chat verifier",
        verification_type=session.userdata.get("verification_type", "work_history"),
        chat_ctx=session.chat_ctx,  # Full conversation history (auto-populated by SDK)
        skip_recap=True,
        mode="chat",
    )
    session.update_agent(chat_agent)  # Does NOT trigger response
    session.userdata["call_type"] = "chat"
    return  # Agent waits passively for next user message
```

**Critical**: Ensure `VerificationAgent(mode="chat")`'s `on_enter()` does NOT call `generate_reply()`. It should be a passive handback — the agent waits for the user to type.

### What to Remove
- Delete `_inject_voice_context()` from `ag_ui_routes.py`
- Delete `_handle_mode_switch()` from `ag_ui_routes.py`
- Delete `CONTEXT_INJECTED` SSE event handling

### Acceptance Criteria
1. After voice→chat switch, chat agent has access to ALL voice conversation entries (not truncated)
2. No greeting or response is triggered by the mode switch
3. Chat agent waits passively for user's next message
4. When user types, chat agent can reference what was discussed in voice
5. No listener involvement in the handback

---

## E4: Silent Mode Switch (REVISED)

### Problem
Mode switch messages should be infrastructure-level signals — log output only. The agents don't need to know about mode switches. They have all context from `chat_ctx`.

### Current State (Validated)
The `chat_text_handler` (lines 2100-2131) already intercepts mode_switch JSON and returns immediately — no `generate_reply()` is called. `session.update_agent()` does NOT auto-trigger a response.

For voice escalation, the voice agent starts speaking naturally via its `on_enter()` / system prompt — this is desired behavior and has nothing to do with the mode_switch message itself.

### Why the Filter Exists
The filter at the top of `chat_text_handler` catches `{"type": "mode_switch", ...}` JSON strings BEFORE they reach `session.generate_reply(user_input=text)` at line 2135. Without this filter, the mode_switch JSON would be treated as a normal user message and sent to the LLM, which would try to respond to it. The filter ensures mode_switch is consumed silently and the handler returns before any LLM processing.

### Implementation
The current implementation is already correct in concept:

```python
# In chat_text_handler:
if text.strip().startswith('{"type"'):
    try:
        parsed = json.loads(text)
        if parsed.get("type") == "mode_switch":
            mode = parsed.get("mode")
            logger.info(f"[mode_switch] Switching to {mode} mode")
            if mode == "voice":
                # Audio toggle + agent swap
                handle_voice_escalation_inline(session)
            elif mode == "chat":
                # Audio off + agent swap (passive, no response)
                session.input.set_audio_enabled(False)
                session.output.set_audio_enabled(False)
                chat_agent = VerificationAgent(mode="chat", chat_ctx=session.chat_ctx, ...)
                session.update_agent(chat_agent)
            return  # Consumed — no LLM processing
    except json.JSONDecodeError:
        pass  # Not JSON, treat as normal message

# Normal text message processing follows...
session.generate_reply(user_input=text)
```

### What to Remove
- Delete `_is_mode_switch()` from `ag_ui_routes.py`
- Delete `_parse_mode_switch()` from `ag_ui_routes.py`
- Delete mode switch filter at top of `ingest_chat_message()` in `ag_ui_routes.py`

### Acceptance Criteria
1. Mode switch messages produce terminal log output only
2. Mode switch JSON is consumed before reaching LLM
3. Voice agent starts speaking naturally (via `on_enter()`/system prompt, not mode_switch)
4. Chat agent waits passively — no response on mode switch
5. No SSE events for mode switch

---

## E5: Graceful Room Cleanup (NEEDS VERIFICATION)

### Current Implementation
- `ListenerState.session_modes: set = {"chat"}` tracks modes used
- Frontend `voiceWasUsed` state tracks voice usage
- `session_modes` included in submit payload

### What to Verify
1. Does `agent.py`'s `on_session_end()` handle chat-only sessions gracefully? (No egress wait for non-voice sessions)
2. Does PostCheckProcessor handle missing `recording_s3_key` without error?
3. Does the listener cleanup path work for chat-only sessions?

### What to Keep
- `session_modes` tracking in listener
- Frontend `voiceWasUsed` state
- Session mode in submit payload

### Acceptance Criteria
1. Chat-only sessions close without egress errors or timeouts
2. PostCheckProcessor handles missing voice recording gracefully
3. Session mode is correctly tracked and reported
4. Listener subprocess disconnects cleanly for chat-only sessions

---

## Summary of Changes by File

### Files to MODIFY

| File | Epic | Changes |
|------|------|---------|
| `agent.py` | E1 | Add `source` param to `publish_transcription_to_room()`, publish chat messages |
| `agent.py` | E2 | Set `call_type = "chat"` when `agent_type` metadata is `"chat"` |
| `agent.py` | E3 | Verify `on_enter()` doesn't call `generate_reply()` for chat mode |
| `agent.py` | E4 | Verify mode_switch filter is correct (likely already is) |
| `listener_service.py` | E1 | Add `source` field to conversation_history entries |
| `post_call_processor.py` | E2 | Merge chat+voice transcripts, store combined in sub_threads |

### Files to REVERT (remove wrong-layer changes)

| File | What to Remove |
|------|---------------|
| `ag_ui_routes.py` | `_chat_session_state`, `ingest_chat_message()`, `_publish_chat_to_lk_room()`, `_inject_voice_context()`, `_handle_mode_switch()`, `_is_mode_switch()`, `_parse_mode_switch()`, `SendDataRequest`/`DataPacket`/`lk_api` imports, chat session auto-seeding |
| `listener_service.py` | `process_chat_transcription()`, `_upload_chat_transcript()` |

### Files UNCHANGED

| File | Reason |
|------|--------|
| `process_post_call.py` | E2 `build_combined_transcript()` is correct — extend for chat |
| `page.tsx` | E5 frontend changes are correct |
