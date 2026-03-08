---
title: "SD-VCHAT-001-E1: Chat Transcript → Form Field Extraction"
status: active
type: reference
last_verified: 2026-03-08
grade: authoritative
---

# SD-VCHAT-001-E1: Chat Transcript → Form Field Extraction

## Problem

Voice transcripts flow through `listener_service.py:process_transcription_data()` → `form_filler_agent.run()` → field extraction → SSE push. Chat messages bypass this pipeline entirely, so chat conversations never update form fields.

## Solution

Feed chat messages into the SAME extraction pipeline that voice uses. Two integration points:

### Backend Change: agent.py — chat_text_handler

In the chat agent's text handler (where user chat messages arrive), after processing the message with the LLM, emit the user's text AND the agent's response as transcription-format data packets so `listener_service.py` can extract fields.

**File**: `agencheck-support-agent/live_form_filler/agent.py`

In the `chat_text_handler` callback:

```python
async def chat_text_handler(msg: TextInputEvent):
    text = msg.text

    # Skip mode_switch control messages (E4)
    if _is_mode_switch(text):
        await _handle_mode_switch(text)
        return

    # 1. Process with LLM as normal
    response = await session.generate_reply(user_input=text)

    # 2. Feed user message to transcript listener for field extraction
    await _emit_chat_as_transcription(ctx, text, speaker="user")

    # 3. Feed agent response to transcript listener for field extraction
    if response and response.text:
        await _emit_chat_as_transcription(ctx, response.text, speaker="agent")
```

The `_emit_chat_as_transcription` helper publishes to the room's data channel in the same format voice transcription uses:

```python
async def _emit_chat_as_transcription(ctx, text: str, speaker: str):
    """Emit chat text as a transcription-format data packet for form field extraction."""
    import json
    payload = json.dumps({
        "type": "transcription",
        "speaker": speaker,
        "text": text,
        "is_final": True,
        "source": "chat"  # Distinguishes from voice transcription
    }).encode()

    await ctx.room.local_participant.publish_data(
        payload,
        reliable=True,
        topic="form_events"
    )
```

### Backend Change: listener_service.py — process_transcription_data

The existing `process_transcription_data()` already handles `{"type": "transcription", "speaker": "user", ...}` format. The only change needed:

- Accept `source: "chat"` alongside voice transcriptions
- No functional change needed — the form_filler_agent extracts fields regardless of source

**Verification**: The `on_data_received` handler at line 238 filters out `lk.*` topics. Our emission uses topic `form_events` (not `lk.*`), so it will be processed.

### No Frontend Changes Required

The frontend already:
- Sends chat messages via `lk.chat` topic → agent receives them
- Listens to `form_events` data channel for field updates → FormEventEmitter handles STATE_DELTA
- Displays field updates in the form

The only change is backend: making the agent emit chat text on `form_events` so the listener extracts fields.

## Testing

- Send a chat message like "John Smith started as Software Engineer in January 2020"
- Verify form fields (name, position, start date) update within 3 seconds
- Verify voice transcription still works when switching to voice mode
- Verify no duplicate field updates (chat + voice processing the same content)

## Risk

- **Duplicate extraction**: If user speaks AND types simultaneously, both pipelines process. Mitigate: form_filler_agent is idempotent (same field value won't re-trigger update).
- **Latency**: Adding an extra publish_data call per chat message. Cost: ~1ms per message. Negligible.
