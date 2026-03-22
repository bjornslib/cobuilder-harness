---
title: "SD-VCHAT-001-E4: Silent Mode Switch"
status: active
type: reference
last_verified: 2026-03-08
grade: authoritative
---

# SD-VCHAT-001-E4: Silent Mode Switch

## Problem

Mode switch messages (`{"type": "mode_switch", "mode": "voice|chat"}`) are sent via `lk.chat` and reach the chat agent's text handler as regular user messages. The agent responds with unnatural text like "I see you're switching to voice mode."

## Solution

### Backend: Filter Mode Switch in chat_text_handler

**File**: `my-project-backend/live_form_filler/agent.py`

Add a filter at the TOP of the chat text handler, before any LLM processing:

```python
import json

def _is_mode_switch(text: str) -> bool:
    """Check if message is a mode_switch control signal."""
    try:
        data = json.loads(text)
        return data.get("type") == "mode_switch"
    except (json.JSONDecodeError, TypeError):
        return False

def _parse_mode_switch(text: str) -> str | None:
    """Extract mode from mode_switch message. Returns 'voice' or 'chat' or None."""
    try:
        data = json.loads(text)
        if data.get("type") == "mode_switch":
            return data.get("mode")
    except (json.JSONDecodeError, TypeError):
        pass
    return None

async def chat_text_handler(msg: TextInputEvent):
    text = msg.text

    # FIRST: Check for control signals — never forward to LLM
    mode = _parse_mode_switch(text)
    if mode:
        await _handle_mode_switch(session, ctx, mode)
        return  # Do NOT process with LLM

    # Normal chat message processing continues...
    # (E1: also emit as transcription for field extraction)
```

### Frontend: No Change Needed

The frontend already sends mode_switch as JSON on `lk.chat`. The backend filter ensures it never reaches the LLM. The user sees no response to the mode switch — only the natural greeting from E3's context injection.

### Edge Case: Malformed Mode Switch

If `sendText` sends mode_switch but JSON parsing fails (unlikely but defensive):
- `_is_mode_switch` returns False
- Message passes through to LLM as regular text
- Agent may produce odd response — acceptable failure mode (very rare)

## Testing

- Click "Start Call" → verify no chat bubble appears with mode switch text
- Click "End Call" → verify no "I see you're switching modes" response
- Verify only natural greeting appears (from E3)
- Verify regular chat messages still work normally

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
