# PRD-VCHAT-001: Manual Testing Guide

## Prerequisites

- Dev environment running: `agencheck-communication-agent` (LK agent) + `agencheck-support-agent` (FastAPI + listener)
- LiveKit server accessible
- S3 bucket `dev-aura-communicator-recordings` accessible
- A test task_id in the database with a valid verification task

## Test Environment Setup

1. Start the support agent: `cd agencheck-support-agent && uvicorn live_form_filler.app:app --port 8000`
2. Start the LK voice agent: `cd agencheck-communication-agent/livekit_prototype/cli_poc && python -m voice_agent.agent`
3. Open the verify-check page in browser: `/verify/[task_id]`

---

## E1: Chat Field Extraction (Score target: 1.0)

### Test 1.1: Chat message triggers form field update
1. Start a chat session (don't click "Start Call")
2. Type: "John Smith started as Software Engineer in January 2020"
3. **Verify**: Form fields for name, position, and start date update within 3 seconds
4. Check listener logs for: `source: "chat"` in received data

### Test 1.2: Agent response triggers extraction
1. In the same chat session, wait for the agent to respond with field-confirming text
2. **Verify**: Relevant form fields update from agent's response

### Test 1.3: Voice extraction still works
1. Click "Start Call" to escalate to voice
2. Speak: "The position is Senior Developer"
3. **Verify**: Position field updates via voice pipeline
4. **Verify**: No duplicate field updates (check listener logs for `source: "voice"`)

### Test 1.4: Data format verification
1. Check listener logs or add a breakpoint at `process_transcription_data()`
2. **Verify** payload format: `{"type": "transcription", "speaker": "user", "text": "...", "is_final": true, "source": "chat"}`
3. **Verify** topic is `"transcription"` (not `"form_events"` or other)

---

## E2: Chat Transcript S3 Storage (Score target: 0.8)

### Test 2.1: Chat-only session S3 upload
1. Start a chat-only session, exchange 3+ messages
2. Submit the form or end the session
3. **Verify** S3: Check `s3://dev-aura-communicator-recordings/transcripts/tasks/{task_id}/chat-*.json` exists
4. **Verify** file content: array of `{role, content, timestamp}` entries

### Test 2.2: call_type defaults correctly
1. Start a chat-only session (never escalate to voice)
2. On session end, check agent logs for `call_type = "chat"`
3. **Verify**: The S3 upload conditional fires (not skipped due to `call_type == "phone"`)

### Test 2.3: Mixed session produces both files
1. Start in chat, escalate to voice, end session
2. **Verify** S3 has BOTH `chat-*.json` AND voice transcript files

### Test 2.4: PostCheckProcessor handles chat transcript
1. After a chat-only session, check Redis Stream for `agencheck:calls:completed` event
2. **Verify**: PostCheckProcessor downloads and evaluates the chat transcript
3. **Known gap**: Voice+chat merge into `sub_threads.all_messages` is not yet unified — separate initiative

---

## E3: Voice-to-Chat Handback (Score target: 0.875)

### Test 3.1: Context preserved on handback
1. Start in chat, confirm 2 fields (e.g., name and position)
2. Escalate to voice, discuss 1 more field
3. End the voice call → return to chat
4. Type: "What have we confirmed so far?"
5. **Verify**: Agent references BOTH the chat-confirmed fields AND the voice-discussed field
6. **Verify**: Agent does NOT re-ask the already-confirmed questions

### Test 3.2: Passive wait on mode switch
1. After returning from voice to chat (step 3 above)
2. **Verify**: NO automatic greeting or agent message appears
3. **Verify**: Agent waits for YOU to type first
4. **Verify**: No SSE events emitted for the mode switch (check network tab)

### Test 3.3: Voice transcriptions accumulate
1. During voice mode, speak several utterances
2. Check listener's `conversation_history` (via logs or debugger)
3. **Verify**: Each entry has `speaker`, `text`, `timestamp`, and `source: "voice"`

### Test 3.4: Chat messages shared with listener
1. In chat mode, send a confirming message (e.g., "Yes, that's correct")
2. **Verify** in listener logs: Chat message received via `data_received` handler
3. **Verify**: `source: "chat"` in the received data
4. **Verify**: Field extraction runs on the chat confirmation

---

## E4: Silent Mode Switch (Score target: 1.0)

### Test 4.1: Mode switch filtered before LLM
1. Open browser DevTools → Network tab
2. Click "Start Call" (sends `{"type": "mode_switch", "mode": "voice"}`)
3. **Verify** in agent logs: `[mode_switch] Switching to voice mode` log line
4. **Verify**: NO LLM response generated for the mode_switch message
5. **Verify**: No chat bubble appears in the UI

### Test 4.2: Regular messages still work
1. In chat mode, type "Hello, I need to verify employment"
2. **Verify**: Agent responds normally (message was NOT filtered)

### Test 4.3: ag_ui_routes.py cleanup
1. Search `ag_ui_routes.py` for: `_is_mode_switch`, `_parse_mode_switch`, `ingest_chat_message`
2. **Verify**: NONE of these functions exist (they were deleted)

### Test 4.4: Voice agent starts naturally
1. Click "Start Call"
2. **Verify**: Voice agent starts speaking via its `on_enter()` / system prompt
3. **Verify**: The agent's greeting is NOT triggered by the mode_switch message itself

---

## E5: Graceful Room Cleanup (Score target: 0.9)

### Test 5.1: Chat-only session closes cleanly
1. Complete a full chat-only session (never use voice)
2. Submit the form
3. **Verify**: No egress-related errors in logs
4. **Verify**: No attempt to download `recording_s3_key`

### Test 5.2: Session mode tracking
1. Start a chat session
2. Check `session.userdata["session_modes"]` → should be `{"chat"}`
3. Escalate to voice
4. Check again → should be `{"chat", "voice"}`
5. **Verify**: `session_modes` included in the submit payload

### Test 5.3: PostCheckProcessor handles missing recording
1. After a chat-only session, trigger PostCheckProcessor
2. **Verify**: No error raised for missing `recording_s3_key`
3. **Verify**: Valid PostCheckResult produced using chat transcript only

### Test 5.4: Mixed session egress works
1. Use both chat and voice in a session
2. End the session
3. **Verify**: Voice egress processes normally (recording uploaded)
4. **Verify**: Chat transcript also uploads to S3

### Test 5.5: Frontend voiceWasUsed tracking
1. Inspect the React state in DevTools
2. **Verify**: `voiceWasUsed` is `false` initially
3. Click "Start Call" → **Verify**: `voiceWasUsed` becomes `true`
4. Submit form → **Verify**: `session_modes` present in POST payload

---

## Quick Smoke Test (5 minutes)

If you only have 5 minutes, run these critical path tests:

1. **Chat extraction works**: Send a chat message with field data → form updates (E1)
2. **Mode switch is silent**: Click "Start Call" → no chat bubble appears (E4)
3. **Voice-to-chat context**: Escalate to voice, say something, return to chat → agent remembers (E3)
4. **Clean session end**: Submit form → no errors in logs (E5)

---

## Known Limitations

- **E2 transcript merge**: Voice + chat transcripts are uploaded to S3 separately but NOT yet merged into `sub_threads.all_messages`. Dashboard may show only voice OR chat, not unified. (Separate initiative planned)
- **E3 context via SDK**: Context transfer relies on LK SDK's `session.chat_ctx` auto-population. If SDK behavior changes, context may break.
- **E4 JSON detection**: Mode switch detection uses `text.strip().startswith('{"type"')` — any user message starting with this pattern would be caught by the filter (unlikely in practice).
