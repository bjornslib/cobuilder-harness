# SD-VCHAT-001-E2.1: Unified Transcript Merge into sub_threads

**Status**: Draft for user review
**Date**: 2026-03-09
**PRD**: PRD-VCHAT-001 (E2 gap closure)
**Depends on**: E1, E2 (both validated)

## Problem Statement

Mixed sessions (chat → voice → chat) lose pre-escalation chat messages. The root cause is a 3-part failure:

1. **`call_type` mutation**: Voice escalation changes `call_type` from `"chat"` to `"web"` (agent.py:2269), so `on_chat_session_end` (guarded by `call_type == "chat"`) is never called for mixed sessions.
2. **LiveKit report excludes chat**: The session report uploaded to S3 contains only voice STT transcriptions. Chat messages sent via `lk.chat` data channel are not captured in the LiveKit session report.
3. **Channel hardcoding**: `batch-import` hardcodes `channel: "phone"` for all imports — chat messages get mislabeled.

### Current State

| Session Type | Voice → sub_threads | Chat → sub_threads | Status |
|-------------|--------------------|--------------------|--------|
| Voice-only | Yes (Prefect pipeline) | N/A | Working |
| Chat-only | N/A | Yes (PostCheckProcessor) | Working |
| Mixed | Yes (voice only) | **No** — chat lost | **Broken** |

## Solution: Merge in `on_session_end` (Option A)

### Why This Approach

Both data sources are available in memory at session end:
- **Voice**: `ctx.make_session_report()` → `parse_session_report_to_messages()` → `[{role, content, timestamp}]`
- **Chat**: `session.userdata["chat_history"]` → already `[{role, content, timestamp}]`

No additional S3 downloads needed. Runs synchronously before the agent process exits.

### Architecture Decision: Extract to `transcript_utils.py`

All transcript manipulation functions are pure data transforms with no agent state dependency. They belong in a shared utility module, not in `agent.py` (already ~2800 lines).

**New file**: `helpers/transcript_utils.py`

Contains:
- `store_unified_transcript()` — orchestrates merge + batch-import call
- `deduplicate_by_proximity()` — pure function, removes near-duplicate messages
- `parse_session_report_to_messages()` — extracted from `post_call_processor.py`
- `tag_messages()` — adds channel/metadata to message lists

`agent.py` calls `await store_unified_transcript(session, session_report)` as a one-liner. `post_call_processor.py` imports `parse_session_report_to_messages` from the new shared location.

### Implementation

#### Step 1: Create `helpers/transcript_utils.py`

**File**: `agencheck-communication-agent/.../voice_agent/helpers/transcript_utils.py` (NEW)

```python
"""Unified transcript merge utilities.

Pure data transforms for merging voice + chat transcripts
and storing them in sub_threads.all_messages.
"""
import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)


def parse_session_report_to_messages(session_report: dict) -> list[dict]:
    """Convert LiveKit session report into normalized [{role, content, timestamp}].

    Extracted from post_call_processor.py for shared use.
    """
    messages = []
    chat_history = session_report.get("chat_history", {})
    items = chat_history.get("items", [])

    for item in items:
        role = item.get("role", "unknown")
        # Content is a list of content parts; join text parts
        content_parts = item.get("content", [])
        text = " ".join(
            part.get("text", "") for part in content_parts
            if isinstance(part, dict) and part.get("text")
        )
        if not text:
            continue

        created_at = item.get("created_at", "")
        # Convert Unix epoch to ISO if numeric
        if isinstance(created_at, (int, float)):
            created_at = datetime.utcfromtimestamp(created_at).isoformat() + "Z"

        messages.append({
            "role": role,
            "content": text,
            "timestamp": created_at,
        })

    return messages


def tag_messages(messages: list[dict], channel: str, source: str) -> list[dict]:
    """Add channel and metadata.source to each message."""
    for msg in messages:
        msg["channel"] = channel
        msg.setdefault("metadata", {})["source"] = source
    return messages


def deduplicate_by_proximity(messages: list[dict], window_seconds: int = 5) -> list[dict]:
    """Remove near-duplicate messages within a time window.

    Voice STT may echo chat messages spoken aloud after escalation.
    If two messages have identical content and are within `window_seconds`,
    keep only the first occurrence.
    """
    seen: list[tuple[str, str]] = []
    result = []

    for msg in messages:
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")

        is_dup = False
        for seen_content, seen_ts in seen:
            if content == seen_content:
                try:
                    t1 = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    t2 = datetime.fromisoformat(seen_ts.replace("Z", "+00:00"))
                    if abs((t1 - t2).total_seconds()) < window_seconds:
                        is_dup = True
                        break
                except (ValueError, TypeError):
                    pass

        if not is_dup:
            result.append(msg)
            seen.append((content, timestamp))

    return result


async def store_unified_transcript(session, session_report: dict | None) -> None:
    """Merge voice + chat transcripts and store in sub_threads.all_messages.

    Called from on_session_end Phase 6. Both data sources are in memory —
    no additional S3 downloads needed.
    """
    userdata = session.userdata
    task_id = userdata.get("task_id")
    case_id = userdata.get("case_id")

    if not task_id or not case_id:
        logger.warning("No task_id/case_id — skipping transcript merge")
        return

    # Collect and tag chat messages
    chat_messages = list(userdata.get("chat_history", []))  # copy to avoid mutating userdata
    tag_messages(chat_messages, channel="chat", source="chat_accumulation")

    # Collect and tag voice messages from session report
    voice_messages = []
    if session_report:
        voice_messages = parse_session_report_to_messages(session_report)
        tag_messages(voice_messages, channel="voice", source="voice_transcript")

    # Merge, sort, deduplicate
    all_messages = chat_messages + voice_messages
    all_messages.sort(key=lambda m: m.get("timestamp", ""))

    if not all_messages:
        logger.info("No transcript messages to store")
        return

    all_messages = deduplicate_by_proximity(all_messages, window_seconds=5)

    # Write to sub_threads via batch-import
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(all_messages, f)
        temp_path = f.name

    try:
        subprocess.run([
            "python", "-m", "helpers.subthread_cycle_helper",
            "--action", "batch-import",
            "--case-id", str(case_id),
            "--messages-file", temp_path,
        ], check=True, timeout=30)
        logger.info(
            "Stored %d merged transcript messages (chat=%d, voice=%d)",
            len(all_messages), len(chat_messages), len(voice_messages),
        )
    except Exception as e:
        logger.error("Failed to store merged transcript: %s", e)
    finally:
        os.unlink(temp_path)
```

#### Step 2: Remove `call_type` guard in `on_session_end`

**File**: `agent.py`, Phase 6 (~line 1742)

Currently:
```python
if call_type == "chat" and userdata.get("form_submission"):
    await on_chat_session_end(session)
```

Change to:
```python
from helpers.transcript_utils import store_unified_transcript

# Phase 6: Unified transcript storage (all session types)
await store_unified_transcript(session, session_report)

# Chat-specific post-processing (form interpretation) still guarded
if call_type == "chat" and userdata.get("form_submission"):
    await on_chat_session_end(session)  # But remove batch-import from here
```

**Note**: `on_chat_session_end` still runs for form interpretation (Haiku eval, cases write). Only the `batch-import` call is removed from it — transcript storage is now handled by `store_unified_transcript`.

#### Step 3: Remove `channel` hardcoding from `batch-import`

**File**: `subthread_cycle_helper.py` (~line 446)

Currently:
```python
msg["channel"] = "phone"
```

Remove this line entirely. The caller (`store_unified_transcript`) already sets `channel` correctly. If `channel` is missing (legacy callers), `batch-import` should not overwrite it.

```python
# DELETE this line:
# msg["channel"] = "phone"

# If backward compatibility needed for callers that don't set channel:
msg.setdefault("channel", "phone")
```

#### Step 4: Remove duplicate `batch-import` from PostCheckProcessor

**File**: `post_call_processor.py`, PostCheckProcessor.process() (~line 568-595)

Remove the `batch-import` subprocess call. `store_unified_transcript()` already stored the transcript in `on_session_end` before `PostCheckProcessor` is invoked.

Also update `parse_session_report_to_messages` import to use the shared util:
```python
from helpers.transcript_utils import parse_session_report_to_messages
```

#### Step 5: Filter mode_switch JSON from chat_history

**File**: `agent.py`, `chat_text_handler` (~line 2071-2076)

Move `chat_history.append()` to AFTER the mode_switch intercept:

```python
# BEFORE (current — mode_switch JSON leaks into chat_history):
userdata["chat_history"].append({"role": "user", "content": text, ...})
# ... mode_switch check and return ...

# AFTER (correct — only real messages stored):
# ... mode_switch check and return ...
userdata["chat_history"].append({"role": "user", "content": text, ...})
```

### Files Changed

| File | Change | Epic |
|------|--------|------|
| `helpers/transcript_utils.py` | **NEW** — `store_unified_transcript()`, `deduplicate_by_proximity()`, `parse_session_report_to_messages()`, `tag_messages()` | E2.1 |
| `agent.py` | Import and call `store_unified_transcript()` in Phase 6, move chat_history append after mode_switch check | E2.1 |
| `subthread_cycle_helper.py` | Remove `channel = "phone"` hardcoding (use `setdefault`) | E2.1 |
| `post_call_processor.py` | Remove duplicate batch-import, import parse_session_report_to_messages from shared util | E2.1 |

### Acceptance Criteria

1. Mixed session (chat → voice → chat) stores ALL messages (pre-escalation chat + voice + post-escalation chat) in `sub_threads.all_messages`
2. Messages sorted chronologically regardless of channel
3. Each message tagged with `channel: "chat"` or `channel: "voice"` (not hardcoded "phone")
4. Near-duplicate messages (same content within 5s) deduplicated
5. Chat-only sessions still store correctly (no regression)
6. Voice-only sessions still store correctly (no regression)
7. Mode_switch JSON strings NOT present in stored transcripts
8. Dashboard endpoint displays merged transcript without code changes

### Risks

| Risk | Mitigation |
|------|-----------|
| Double-write if PostCheckProcessor not updated | Add idempotency key OR remove batch-import from PostCheckProcessor |
| `parse_session_report_to_messages()` not available in scope | Import from post_call_processor.py or extract to shared util |
| `batch-import` subprocess fails silently | Already has error logging; add metric/alert |
| Large mixed transcripts | Same unbounded risk as voice-only; no new risk |

### Testing

- Unit test: `deduplicate_by_proximity()` with overlapping timestamps
- Integration: Mixed session → verify sub_threads has both channels
- Regression: Chat-only and voice-only sessions still store correctly
