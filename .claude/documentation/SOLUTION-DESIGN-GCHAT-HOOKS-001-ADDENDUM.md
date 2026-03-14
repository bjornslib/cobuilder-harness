---
title: "Solution Design Gchat Hooks 001 Addendum"
status: active
type: architecture
last_verified: 2026-03-14
grade: reference
---

# Solution Design Addendum: PRD-GCHAT-HOOKS-001 v2.0
# Architecture Pivot: One-Shot Task + ThreadKey Correlation

**Document Version**: 2.1.0
**PRD Reference**: PRD-GCHAT-HOOKS-001 v2.0
**Status**: Fully Validated (all 6 criteria pass — outbound, inbound, threading, human detection, concurrent, auth)
**Author**: System 3 Guardian
**Created**: 2026-02-21
**Supersedes**: SOLUTION-DESIGN-GCHAT-HOOKS-001.md v1.0 (tmux injection architecture)

---

## Architecture Pivot Summary

The original v1.0 solution design used **tmux send-keys injection** for delivering GChat responses to blocked AskUserQuestion dialogs. This has been replaced with a fundamentally different approach: **deny the AskUserQuestion, forward to GChat, poll for response via one-shot background Task**.

### What Changed

| Aspect | v1.0 (Superseded) | v2.0 (Current) |
|--------|-------------------|----------------|
| AskUserQuestion handling | Approve → blocks terminal → tmux injects keystrokes | Deny → Claude continues → poller delivers answer |
| Inbound mechanism | launchd daemon + tmux send-keys | One-shot background Haiku Task |
| Response delivery | tmux keystroke injection | Task completion → wakes parent thread |
| Infrastructure | External daemon process (launchd plist) | Native Claude Code subagent |
| Session detection | All sessions affected | Only System 3 sessions (orchestrators pass through) |
| tmux dependency | Required for response injection | Not used for response delivery |
| Stop gate impact | None (AskUserQuestion approved) | Marker file integration required |

### Why the Pivot

1. **tmux injection is fragile**: Keystroke injection for AskUserQuestion dialogs requires precise timing, key mapping per option count, and handling of edge cases (multi-select, "Other", session state). This was identified as the highest risk in v1.0.

2. **Background Task wake-up is the only reliable mechanism**: Perplexity research confirmed that ONLY completing background Tasks/subagents wake the Claude Code main thread. File writes, Bash commands, and external processes cannot.

3. **Deny + continue is simpler**: Blocking AskUserQuestion and telling Claude the question was forwarded lets the session continue other work while waiting. No terminal blocking at all.

4. **No external daemon needed**: The launchd daemon (v1.0) adds macOS-specific infrastructure, installation scripts, and lifecycle management. The one-shot Task (v2.0) uses native Claude Code mechanisms.

---

## Validated Design: Thread Correlation

### Prototype Results (2026-02-21)

Script: `.claude/scripts/prototypes/gchat-thread-correlation.py`

**Test 1: Dry Run (threadKey → thread resource name mapping)**
```
RESULT: threadKey 'proto-ask-223142-6798b670-dryrun'
      → thread 'spaces/AAQAOmyvAfE/threads/fLaeKYynV6A'
STATUS: PASS
```

**Test 2: Concurrent Threads (no cross-contamination)**
```
Thread A: proto-ask-223150-6dc75d55-sessionA
        → spaces/AAQAOmyvAfE/threads/OJ0BHQav4rU
Thread B: proto-ask-223150-521b93c2-sessionB
        → spaces/AAQAOmyvAfE/threads/E84vl-LzRXs
RESULT: PASS — Two distinct threads created
```

**Test 3: Full Round-Trip (webhook send → user reply → API read)**
```
1. Webhook sent START message (threadKey: thread-visibility-test-002)
   → thread: spaces/AAQAOmyvAfE/threads/1aQXck5aX-4
2. Webhook sent REPLY in same thread (same threadKey)
   → same thread confirmed
3. User replied in GChat thread: "Works!"
   → sender.type: HUMAN (vs BOT for webhook messages)
4. Chat API read all 3 messages in thread:
   - [BOT] Webhook START
   - [BOT] Webhook REPLY
   - [HUMAN] "Works!"
RESULT: PASS — Complete outbound + inbound + human detection validated
```

**Test 4: Webhook creates visible threads**
```
User confirmed: webhook messages with threadKey create visible thread cards
in the GChat space. Reply button works. Threads are NOT flat messages.
RESULT: PASS — Webhooks sufficient for outbound (no need for Chat API outbound)
```

### Auth Requirements (Validated 2026-02-21)

| Direction | Auth Method | Scopes Required |
|-----------|-------------|-----------------|
| **Outbound** (webhook) | API key in URL | None (webhook URL includes key+token) |
| **Inbound** (Chat API) | ADC via custom OAuth client | `chat.spaces`, `chat.messages`, `chat.messages.create`, `cloud-platform` |

**Setup**: Default gcloud OAuth client is BLOCKED by Google for Chat scopes ("sensitive scopes").
Must use a custom OAuth Desktop client:
```bash
gcloud auth application-default login \
  --client-id-file=~/Downloads/client_secret_*.json \
  --scopes="https://www.googleapis.com/auth/chat.spaces,https://www.googleapis.com/auth/chat.messages,https://www.googleapis.com/auth/chat.messages.create,https://www.googleapis.com/auth/cloud-platform"
```

**MCP server restart**: After refreshing ADC, the MCP server must be restarted to pick up new credentials (it caches at startup).

### Critical Finding: threadKey vs thread_id

The google-chat-bridge MCP server has a **two-layer identifier system**:

| Layer | Parameter | Format | Example |
|-------|-----------|--------|---------|
| Sending (outbound) | `threadKey` | Arbitrary string | `ask-20260221-a7f3b9e1` |
| Querying (inbound) | `thread_id` | Full resource name | `spaces/AAQAOmyvAfE/threads/fLaeKYynV6A` |

**Mapping flow**:
1. Hook sends message via webhook with `threadKey=ask-session-uuid`
2. Webhook response includes `thread.name = spaces/{space}/threads/{id}`
3. Hook stores BOTH values in marker file
4. Poller Task uses `thread.name` (the resource name) to query `get_thread_messages()`

**The hook MUST capture the webhook response** to extract `thread.name`. This is a synchronous operation — the response is immediate.

### Polling Mechanism

The Haiku poller Task uses **direct Python** (not MCP tools) to avoid credential caching issues:

```python
import sys
sys.path.insert(0, f"{project_root}/mcp-servers/google-chat-bridge/src")
from google_chat_bridge.chat_client import ChatClient

client = ChatClient(default_space_id="spaces/AAQAOmyvAfE")
msgs = client.list_messages(
    filter_str=f'createTime > "{question_sent_time}"'
)
# Filter for sender.type == "HUMAN" in the target thread
human_replies = [
    m for m in msgs
    if m.thread_name == thread_resource_name
    and m.sender_type == "HUMAN"
]
```

**Why direct Python over MCP tools?**
- ADC credentials are read fresh each call (no MCP server restart needed after re-auth)
- Token auto-refresh works naturally (google-auth library handles expiry)
- No dependency on MCP server lifecycle

The poller checks for messages with `sender.type == "HUMAN"` in the thread. Webhook-sent messages have `sender.type == "BOT"`, making the distinction reliable and unambiguous.

---

## Component Flow (v2.0)

### Outbound (AskUserQuestion → GChat)

```
Claude Code calls AskUserQuestion
    │
    ▼
PreToolUse hook fires (gchat-ask-user-forward.py)
    │
    ├── 1. Check session type
    │   ├── System 3? → Continue to step 2
    │   └── Orchestrator/Worker? → return {"decision": "approve"}
    │
    ├── 2. Parse questions[] from tool_input
    │
    ├── 3. Generate threadKey: ask-{session_id}-{uuid8}
    │
    ├── 4. Call Haiku API to format question for GChat
    │   └── Input: raw questions JSON
    │   └── Output: clean formatted message
    │
    ├── 5. POST to webhook with threadKey
    │   └── URL: {webhook_url}&messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD
    │   └── Body: {"text": formatted_msg, "thread": {"threadKey": key}}
    │   └── Response: {"thread": {"name": "spaces/X/threads/Y"}, ...}
    │
    ├── 6. Write marker file: .claude/state/gchat-forwarded-ask/{question_id}.json
    │   └── Stores: threadKey, thread.name (resource), questions, session_id, timestamp
    │
    └── 7. Return DENY:
        {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Question forwarded to GChat (thread: ask-...)"
        }}
```

### Inbound (GChat → Claude Code)

```
Claude receives AskUserQuestion denial with "forwarded to GChat" reason
    │
    ▼
System 3 output style pattern: spawn one-shot poller Task
    │
    ├── Task(subagent_type="general-purpose", model="haiku",
    │        run_in_background=True, ...)
    │
    ▼
Haiku Poller Task runs:
    │
    ├── Loop (every 15s, max 120 iterations = 30 min):
    │   ├── poll_inbound_messages()          # Fetch from GChat API → queue
    │   ├── get_thread_messages(thread_id=   # Filter queue by thread
    │   │     "spaces/X/threads/Y")
    │   ├── Filter for non-bot messages
    │   ├── Found? → return "GCHAT_RESPONSE: {text}" and EXIT
    │   └── Not found? → sleep 15s, repeat
    │
    └── Timeout → return "GCHAT_TIMEOUT: No response in 30 minutes"

Poller Task COMPLETES
    │
    ▼
Parent System 3 session receives <task-notification>
    │
    ├── Parse "GCHAT_RESPONSE: {text}" → user's answer
    ├── Incorporate answer into decision-making
    └── Update marker file: status → "resolved"
```

### Stop Gate Integration

```
System 3 wants to stop
    │
    ▼
Stop gate fires (unified-stop-gate.sh)
    │
    ├── Step 5: system3_continuation_judge.py
    │   │
    │   ├── Check 1: AskUserQuestion presented via terminal?
    │   │   └── If yes → PASS (existing behavior)
    │   │
    │   └── Check 2: GChat marker files exist?
    │       └── Look in .claude/state/gchat-forwarded-ask/
    │       └── Find markers with status="pending" and age < 30 minutes
    │       └── If found → PASS (question was presented via GChat)
    │
    └── No markers AND no terminal AskUserQuestion → BLOCK
```

---

## Cost Model (v2.0)

| Event | Cost | Frequency | Daily Estimate |
|-------|------|-----------|----------------|
| AskUserQuestion → GChat | ~$0.005 (Haiku formatting) + $0 (webhook) | 2-5/day | ~$0.01-$0.025 |
| GChat response polling | ~$0.01/question (Haiku poller Task) | 2-5/day | ~$0.02-$0.05 |
| gchat-send outbound | $0 (bash + curl) | 10-20/day | $0 |
| **Total** | | | **~$0.03-$0.08/day** |

Compared to v1.0 (s3-communicator): ~$0.30-$0.60/day → **90%+ reduction**.

---

## Files to Create (Implementation)

| File | Epic | Purpose |
|------|------|---------|
| `.claude/hooks/gchat-ask-user-forward.py` | E1 F1.1 | PreToolUse hook: block + forward |
| `.claude/state/gchat-forwarded-ask/` | E1 F1.1 | Marker file directory |
| `.claude/scripts/gchat-send.sh` | E2 F2.1 | Outbound CLI utility |
| `.claude/hooks/gchat-notification-dispatch.py` | E2 F2.2 | Notification hook |
| `.claude/scripts/prototypes/gchat-thread-correlation.py` | E3 F3.1 | Already created (prototype) |

### Files to Modify

| File | Epic | Changes |
|------|------|---------|
| `.claude/output-styles/system3-meta-orchestrator.md` | E4 F4.1 | Remove s3-communicator spawn, add poller pattern |
| `.claude/hooks/unified_stop_gate/system3_continuation_judge.py` | E1 F1.4 | Add marker file check |
| `.claude/settings.json` | E1 F1.1 | Add PreToolUse hook for AskUserQuestion |

### Files to Archive

| File | Epic | Destination |
|------|------|-------------|
| `.claude/skills/s3-communicator/SKILL.md` | E4 F4.3 | `.claude/skills/_archived/s3-communicator/` |

---

## Implementation Order

1. **Epic 3 (F3.1, F3.2)**: Prototype validation — DONE (dry-run + concurrent tests pass)
2. **Epic 1 (F1.1 → F1.4)**: Core AskUserQuestion flow
3. **Epic 2 (F2.1 → F2.4)**: Outbound hooks (parallel with Epic 1)
4. **Epic 4 (F4.1 → F4.3)**: s3-communicator removal (last)

---

## Open Questions (Updated)

1. ~~**Interactive test pending**~~ — **RESOLVED**: Full round-trip validated. User replied "Works!" in GChat thread, detected via Chat API with `sender.type == "HUMAN"`.

2. **Haiku exit discipline for poller**: The poller Task uses Haiku. Haiku has known exit discipline issues (keeps going instead of returning). If this manifests, upgrade to Sonnet (increases cost from ~$0.01 to ~$0.05 per question).

3. **MCP tool availability split**:
   - **PreToolUse hook** (outbound): Runs as subprocess, CANNOT call MCP tools. Uses webhook directly via `urllib.request`. This is fine — webhook only needs the URL.
   - **Poller Task** (inbound): Runs as Claude Code subagent, CAN call MCP tools (`poll_inbound_messages`, `get_thread_messages`). However, the MCP server must have fresh ADC credentials with Chat scopes. Alternative: import `ChatClient` directly from the bridge source and use `list_messages(filter_str=...)`.

4. **Marker file race condition**: If the stop gate fires between the hook writing the marker and the poller resolving it, the session continues. This is the desired behavior (question is still pending). On timeout, the marker should be updated to `status: "timeout"` (not deleted) so subsequent stop gate checks know the question was asked but unanswered.

5. **MCP server credential caching**: The MCP server caches ADC credentials at startup. After `gcloud auth application-default login`, the MCP server must be restarted (`/mcp` in Claude Code) for `poll_inbound_messages` and `get_thread_messages` to work. The poller Task may need to import `ChatClient` directly instead of using MCP tools to avoid this issue.

6. **`_send_outbound()` prefers webhook**: The MCP `send_chat_message` tool routes through `_send_outbound()` which prefers webhook when `GOOGLE_CHAT_WEBHOOK_URL` is set (line 142-145 of server.py). This means `send_chat_message` creates flat webhook messages, NOT Chat API messages. For outbound, the hook should use the webhook directly (which works for threading). For inbound, the poller uses the Chat API (via MCP tools or direct ChatClient import).

---

**This addendum supersedes SOLUTION-DESIGN-GCHAT-HOOKS-001.md v1.0.**
The original document's outbound architecture (Epic 2: gchat-send CLI, notification hook, stop hook integration) remains valid. Only the inbound architecture (AskUserQuestion handling and response delivery) has changed.
