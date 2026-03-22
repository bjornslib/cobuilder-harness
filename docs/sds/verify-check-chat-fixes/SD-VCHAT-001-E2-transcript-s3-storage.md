---
title: "SD-VCHAT-001-E2: Chat + Voice Transcript S3 Storage"
status: active
type: reference
last_verified: 2026-03-08
grade: authoritative
---

# SD-VCHAT-001-E2: Chat + Voice Transcript S3 Storage

## Problem

Voice transcripts are stored on S3 via egress. Chat transcripts exist only in frontend state — lost on page reload. PostCheckProcessor only evaluates voice transcripts.

## Solution

### 1. Backend: Accumulate Chat Messages

In `agent.py`, maintain a session-level chat history list:

```python
# In chat_verification_entrypoint or session userdata
ctx.userdata["chat_history"] = []

# In chat_text_handler, after each exchange:
ctx.userdata["chat_history"].append({
    "role": "user",
    "content": msg.text,
    "timestamp": datetime.utcnow().isoformat()
})
if response and response.text:
    ctx.userdata["chat_history"].append({
        "role": "agent",
        "content": response.text,
        "timestamp": datetime.utcnow().isoformat()
    })
```

### 2. Backend: Upload to S3 on Session End

In the agent's `on_session_end` callback (or `_end_call_internal`):

```python
async def _upload_chat_transcript(ctx):
    """Upload accumulated chat history to S3."""
    chat_history = ctx.userdata.get("chat_history", [])
    if not chat_history:
        return None  # No chat messages — nothing to upload

    task_id = ctx.userdata.get("task_id")
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    s3_key = f"transcripts/tasks/{task_id}/chat-{timestamp}.json"

    transcript_data = {
        "task_id": task_id,
        "type": "chat",
        "messages": chat_history,
        "started_at": chat_history[0]["timestamp"],
        "ended_at": chat_history[-1]["timestamp"],
        "message_count": len(chat_history)
    }

    # Use existing S3 upload utility
    await s3_client.put_object(
        Bucket=settings.S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(transcript_data),
        ContentType="application/json"
    )

    # Store key in session data for PostCheckProcessor
    ctx.userdata["chat_transcript_s3_key"] = s3_key
    return s3_key
```

### 3. Store S3 Key in Database

When the session ends, write the `chat_transcript_s3_key` to the task's metadata (same pattern as `transcript_s3_key` for voice):

```python
# In the session cleanup or form submission handler
await database_writer.update_task_metadata(
    task_id=task_id,
    chat_transcript_s3_key=s3_key
)
```

This may require adding `chat_transcript_s3_key` column to the relevant table, or storing in the existing JSONB metadata column.

### 4. PostCheckProcessor: Evaluate Both Transcripts

**File**: `my-project-backend/prefect_flows/flows/tasks/process_post_call.py`

Modify to accept optional `chat_transcript_s3_key`:

```python
async def process_post_call(task_id: str):
    task_data = await get_task_data(task_id)

    voice_transcript = None
    chat_transcript = None

    # Download voice transcript if exists
    if task_data.get("transcript_s3_key"):
        voice_transcript = await download_from_s3(task_data["transcript_s3_key"])

    # Download chat transcript if exists
    if task_data.get("chat_transcript_s3_key"):
        chat_transcript = await download_from_s3(task_data["chat_transcript_s3_key"])

    # Build combined transcript for evaluation
    combined = build_combined_transcript(voice_transcript, chat_transcript)

    # Evaluate using combined transcript
    result = await evaluate_verification(combined, task_data)
    return result

def build_combined_transcript(voice, chat):
    """Merge voice and chat transcripts chronologically."""
    entries = []
    if voice:
        for entry in voice.get("segments", []):
            entries.append({**entry, "source": "voice"})
    if chat:
        for msg in chat.get("messages", []):
            entries.append({
                "speaker": msg["role"],
                "text": msg["content"],
                "timestamp": msg["timestamp"],
                "source": "chat"
            })
    # Sort by timestamp
    entries.sort(key=lambda e: e.get("timestamp", ""))
    return entries
```

## Testing

- Chat-only session: verify S3 file exists at expected key, PostCheckProcessor evaluates it
- Voice-only session: verify existing behavior unchanged
- Mixed session: verify both files exist, PostCheckProcessor merges chronologically

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
