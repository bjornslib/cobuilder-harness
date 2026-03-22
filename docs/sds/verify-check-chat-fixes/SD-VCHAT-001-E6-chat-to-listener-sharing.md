# SD-VCHAT-001-E6: Share Chat Messages with LK Listener

## Problem

The listener subprocess joins the LiveKit room as a silent participant to receive voice transcriptions and extract form field values via Groq/PydanticAI. However, when the user is in CHAT mode, the listener never sees chat messages. This means:

- User confirms a field via chat ("Yes") → listener doesn't know → may re-ask in voice mode
- Assistant questions in chat are invisible to listener's conversation_history

## Architecture

```
Current (broken):
  Frontend → POST /listener/chat-message → ag_ui_routes.py → process_chat_transcription() → SSE
  Listener subprocess (LK room) → voice only via data_received → process_transcription_data()

  ❌ Chat messages never reach listener subprocess

Fixed:
  Frontend → POST /listener/chat-message → ag_ui_routes.py → process_chat_transcription() → SSE
                                                            ↓
                                              LiveKit Server API: send_data()
                                                            ↓
  Listener subprocess (LK room) → data_received → process_transcription_data()

  ✅ Listener receives both voice AND chat messages
```

## Implementation

### File 1: `my-project-backend/live_form_filler/ag_ui_routes.py`

In `ingest_chat_message()` (~line 432), after pushing to SSE queue, publish the chat message to the LK room using LiveKit server-side API:

```python
from livekit import api as lk_api
import json

async def _publish_chat_to_lk_room(room_name: str, speaker: str, text: str):
    """Publish a chat message to the LK room so the listener subprocess receives it."""
    try:
        lk_client = lk_api.LiveKitAPI(
            url=os.environ.get("LIVEKIT_URL", ""),
            api_key=os.environ.get("LIVEKIT_API_KEY", ""),
            api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
        )
        data_packet = json.dumps({
            "type": "transcription",
            "text": text,
            "speaker": speaker,
            "is_final": True,
            "source": "chat"
        }).encode("utf-8")

        await lk_client.room.send_data(
            room=room_name,
            data=data_packet,
            kind=lk_api.DataPacketKind.RELIABLE,
        )
        await lk_client.aclose()
    except Exception as e:
        logger.warning(f"Failed to publish chat to LK room {room_name}: {e}")
```

Call `_publish_chat_to_lk_room()` inside `ingest_chat_message()` for BOTH user and assistant messages.

### File 2: `my-project-backend/live_form_filler/services/listener_service.py`

In `process_transcription_data()` (~line 311), the existing handler already processes any data packet with `{"type": "transcription"}` format. The only change needed:

- Add a `source` field to the conversation_history entry so we can distinguish chat vs voice entries:

```python
# In process_transcription_data(), where conversation_history is appended (~line 361):
state.conversation_history.append({
    "speaker": speaker,
    "text": text_content,
    "timestamp": datetime.utcnow().isoformat(),
    "source": payload.get("source", "voice"),  # NEW: tag source
})
```

### File 3: No other files need changes

The existing extraction pipeline in `process_transcription_data()` already:
- Accepts both user and agent transcriptions
- Runs form_filler_agent on user turns
- Pushes field updates via HTTP to the API

## Acceptance Criteria

1. When a user sends a chat message, it appears in the listener subprocess's `conversation_history` with `source: "chat"`
2. When an assistant sends a chat response, it also appears in the listener's history
3. Field extraction runs on chat user messages just like voice transcriptions
4. The `data_received` handler in listener_service.py correctly receives and processes chat-sourced data packets
5. LiveKit server-side API credentials (LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET) are used from environment

## Dependencies

- E1 (chat field extraction via process_chat_transcription) — validated ✓
- E3 (voice-to-chat handback) — validated ✓
- E4 (silent mode switch) — validated ✓
- LiveKit Python SDK (`livekit-api` package) — already installed

## Risk

- Double extraction: Both `process_chat_transcription()` (in-process) and `process_transcription_data()` (listener) will extract from the same chat message. This is acceptable — the listener's extraction is the canonical one, and the in-process one provides immediate SSE feedback. Field updates are idempotent.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
