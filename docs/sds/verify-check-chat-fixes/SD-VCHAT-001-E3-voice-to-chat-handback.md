---
title: "SD-VCHAT-001-E3: Voice-to-Chat Handback"
status: active
type: reference
last_verified: 2026-03-08
grade: authoritative
---

# SD-VCHAT-001-E3: Voice-to-Chat Handback

## Problem

When user ends a voice call and returns to chat mode, the chat agent has no context about what was discussed during voice. It may re-ask questions already answered.

## Solution

### Backend: Context Injection on Mode Switch

When a `mode_switch: chat` control message is received (see E4 for filtering), inject a context summary into the chat agent's conversation:

```python
async def _handle_mode_switch(session, ctx, mode: str):
    """Handle mode_switch control signal."""
    if mode == "chat":
        await _inject_voice_context(session, ctx)
    elif mode == "voice":
        # Voice escalation handled by existing handle_voice_escalation
        await handle_voice_escalation(session, ctx)

async def _inject_voice_context(session, ctx):
    """Inject voice conversation summary into chat context."""
    # Get confirmed fields from form state
    form_state = ctx.userdata.get("form_state", {})
    confirmed_fields = {k: v for k, v in form_state.items() if v.get("confirmed")}

    # Get recent voice transcript (accumulated during voice mode)
    voice_history = ctx.userdata.get("voice_transcript_buffer", [])

    # Build context summary
    summary_parts = ["The user has returned from a voice call. Here's what was discussed:"]

    if confirmed_fields:
        summary_parts.append("\nConfirmed fields during voice:")
        for field, data in confirmed_fields.items():
            summary_parts.append(f"  - {field}: {data.get('value', 'unknown')}")

    if voice_history:
        # Include last few exchanges for conversational continuity
        recent = voice_history[-6:]  # Last 3 exchanges
        summary_parts.append("\nRecent voice conversation:")
        for entry in recent:
            summary_parts.append(f"  {entry['speaker']}: {entry['text']}")

    summary_parts.append("\nContinue the verification via chat. Do NOT re-ask questions already confirmed above.")

    context_message = "\n".join(summary_parts)

    # Inject as system context (not visible to user)
    # Use AgentSession's update_agent or equivalent to modify context
    await session.update_agent(
        instructions=session._current_instructions + "\n\n" + context_message
    )

    # Send a natural greeting to the user
    await session.generate_reply(
        user_input="[SYSTEM: User returned to chat from voice call. Greet naturally and continue.]"
    )
```

### Key Design Decisions

1. **Reuse existing session** — don't spawn a new agent. The LiveKit AgentSession persists across mode switches.
2. **Inject via instructions update** — `update_agent()` modifies the system prompt without resetting conversation history.
3. **Use form_state as ground truth** — confirmed fields from the form_filler_agent are authoritative (same source voice used).
4. **Natural greeting** — agent generates a contextual greeting, not a template string.

### Voice Transcript Buffer

During voice mode, accumulate transcript entries in `ctx.userdata["voice_transcript_buffer"]`:

```python
# In the voice agent's transcription handler
ctx.userdata.setdefault("voice_transcript_buffer", []).append({
    "speaker": speaker,
    "text": text,
    "timestamp": datetime.utcnow().isoformat()
})
```

This buffer is read by `_inject_voice_context` and also uploaded to S3 by E2.

## Testing

- Start chat → escalate to voice → confirm 2 fields → end call → return to chat
- Verify chat agent says something like "Welcome back! During the call we confirmed [fields]. Let's continue with [remaining fields]."
- Verify agent does NOT re-ask confirmed fields
