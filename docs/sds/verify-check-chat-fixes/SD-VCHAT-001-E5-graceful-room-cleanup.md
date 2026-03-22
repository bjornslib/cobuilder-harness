---
title: "SD-VCHAT-001-E5: Graceful Room Cleanup Without Egress"
status: active
type: reference
last_verified: 2026-03-08
grade: authoritative
---

# SD-VCHAT-001-E5: Graceful Room Cleanup Without Egress

## Problem

PostCheckProcessor assumes voice recording exists (`recording_s3_key`, `transcript_s3_key`). Chat-only sessions have no egress job, no recording, no voice transcript. Room cleanup fails or produces incomplete results.

## Solution

### 1. Track Session Mode in Backend

Add a `session_modes` set to track which modes were used:

```python
# In agent.py, session initialization
ctx.userdata["session_modes"] = {"chat"}  # Always starts with chat

# In handle_voice_escalation (when voice starts)
ctx.userdata["session_modes"].add("voice")
```

### 2. Conditional Egress on Room Close

**File**: `my-project-backend/live_form_filler/agent.py` (or listener_service.py cleanup)

In the session end handler:

```python
async def on_session_end(ctx):
    session_modes = ctx.userdata.get("session_modes", {"chat"})
    task_id = ctx.userdata.get("task_id")

    # Always upload chat transcript (E2)
    chat_s3_key = await _upload_chat_transcript(ctx)

    # Only process voice egress if voice mode was used
    if "voice" in session_modes:
        # Existing voice egress/recording logic
        recording_s3_key = ctx.userdata.get("recording_s3_key")
        transcript_s3_key = ctx.userdata.get("transcript_s3_key")
    else:
        recording_s3_key = None
        transcript_s3_key = None

    # Trigger PostCheckProcessor with available data
    await trigger_post_check(
        task_id=task_id,
        recording_s3_key=recording_s3_key,
        transcript_s3_key=transcript_s3_key,
        chat_transcript_s3_key=chat_s3_key,
        session_modes=list(session_modes)
    )

    # Cleanup listener (existing logic — idempotent)
    await _cleanup_listener(ctx)
```

### 3. PostCheckProcessor: Handle Missing Recording

**File**: `my-project-backend/prefect_flows/flows/tasks/process_post_call.py`

Make recording download conditional:

```python
async def process_post_call(task_id: str, **kwargs):
    recording_s3_key = kwargs.get("recording_s3_key")
    transcript_s3_key = kwargs.get("transcript_s3_key")
    chat_transcript_s3_key = kwargs.get("chat_transcript_s3_key")

    voice_transcript = None
    chat_transcript = None

    # Voice transcript — optional
    if transcript_s3_key:
        try:
            voice_transcript = await download_from_s3(transcript_s3_key)
        except Exception as e:
            logger.warning(f"Voice transcript not found: {e}")

    # Chat transcript — optional
    if chat_transcript_s3_key:
        try:
            chat_transcript = await download_from_s3(chat_transcript_s3_key)
        except Exception as e:
            logger.warning(f"Chat transcript not found: {e}")

    # Must have at least one transcript
    if not voice_transcript and not chat_transcript:
        logger.error(f"No transcripts available for task {task_id}")
        return PostCheckResult(
            status="error",
            reason="No transcripts available for evaluation"
        )

    # Build combined transcript (E2 logic)
    combined = build_combined_transcript(voice_transcript, chat_transcript)

    # Evaluate
    result = await evaluate_verification(combined, task_data)
    return result
```

### 4. Frontend: Track Voice Usage

**File**: `my-project-frontend/app/verify-check/[task_id]/page.tsx`

Track whether voice was ever used in the session:

```typescript
const [voiceWasUsed, setVoiceWasUsed] = useState(false);

const handleStartCall = async () => {
    setVoiceWasUsed(true);
    // ... existing voice start logic
};

// On form submission, include in request:
const submitPayload = {
    ...formData,
    session_modes: voiceWasUsed ? ['chat', 'voice'] : ['chat'],
};
```

## Testing

- Chat-only session → submit form → verify no egress error, PostCheckProcessor uses chat transcript
- Voice session → submit → verify egress runs, PostCheckProcessor uses voice transcript
- Mixed session → submit → verify both transcripts processed
- Chat-only session → close browser → verify room cleanup completes without error

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
