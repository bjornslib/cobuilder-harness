---
title: "Solution Design Gchat Hooks 001"
status: active
type: architecture
last_verified: 2026-03-14
grade: reference
---

# Solution Design: PRD-GCHAT-HOOKS-001
# Programmatic GChat Integration via Hooks

**Document Version**: 1.0.0
**PRD Reference**: PRD-GCHAT-HOOKS-001
**Status**: Draft
**Author**: Solution Design Architect
**Created**: 2026-02-21
**Supersedes**: s3-communicator SKILL.md v2.0.0

---

## Executive Summary

This document describes the technical design for replacing the persistent `s3-communicator` Haiku agent with a zero-token-cost GChat integration built from Claude Code hooks, a bash CLI utility, and a background daemon. The primary driver is eliminating the #1 cause of stalled autonomous sessions: `AskUserQuestion` dialogs that block Claude Code terminals without notifying the user. The secondary driver is eliminating approximately $0.30-$0.60/day in token spend for what is fundamentally a message relay function.

The solution comprises five components:

1. `gchat-ask-user-forward.py` - PreToolUse hook that captures `AskUserQuestion` calls and forwards them to GChat
2. `gchat-ask-user-answered.py` - PostToolUse hook that sends answer confirmations to GChat
3. `gchat-notification-dispatch.py` - Notification hook that forwards Claude Code notifications to GChat
4. `gchat-send.sh` - CLI utility for on-demand outbound GChat messaging
5. `gchat-response-poller.py` - Background daemon (launchd) that polls GChat and injects answers via tmux

---

## 1. Architecture Overview

### 1.1 Component Diagram

```
 CLAUDE CODE SESSIONS (all levels)
 ┌─────────────────────────────────────────────────────────────────────┐
 │  SYSTEM 3 (tmux: system3)        ORCHESTRATORS (tmux: orch-*)       │
 │  ┌───────────────────────────┐   ┌──────────────────────────────┐   │
 │  │ AskUserQuestion ─────────┼──►│ PreToolUse Hook              │   │
 │  │   (blocks session)       │   │ gchat-ask-user-forward.py    │   │
 │  │                          │   └──────────┬───────────────────┘   │
 │  │ Notification event ──────┼──►Notification Hook              │   │
 │  │                          │   gchat-notification-dispatch.py │   │
 │  │                          │   └──────────┬───────────────────┘   │
 │  │ Session end (Stop) ──────┼──►Stop Hook  │                        │
 │  │                          │   unified-stop-gate.sh (extended) │   │
 │  │                          │   └──────────┬───────────────────┘   │
 │  │ Bash("gchat-send ...") ──┼──────────────┼──────────────────────►│
 │  └───────────────────────────┘              │                        │
 └────────────────────────────────────────────┼────────────────────────┘
                                              │ HTTP POST
                                              ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  gchat-send.sh (CLI utility)                                        │
 │  Reads: $GOOGLE_CHAT_WEBHOOK_URL                                    │
 │  Fallback: parse .mcp.json                                          │
 │  Sends: curl POST with JSON payload                                 │
 └──────────────────────────┬──────────────────────────────────────────┘
                             │ HTTPS POST
                             ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  GOOGLE CHAT                                                        │
 │  ┌─────────────────────────────────────────────────────────────┐   │
 │  │  Claude Code space                                           │   │
 │  │  • [AskUserQuestion] from session: orch-epic4               │   │
 │  │    Options: 1. Approach A   2. Approach B                   │   │
 │  │    Reply with option number or custom text                  │   │
 │  │  • [Answered] Which approach: Approach A selected           │   │
 │  │  • [Done] Epic 3 completed. 12/12 subtasks validated.       │   │
 │  └─────────────────────────────────────────────────────────────┘   │
 └──────────────────────────┬──────────────────────────────────────────┘
                             │ Google Chat API (poll)
                             ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  gchat-response-poller.py (launchd daemon — OUTSIDE Claude Code)    │
 │                                                                      │
 │  Loop (every 10s):                                                  │
 │    1. Scan .claude/state/pending-questions/ for .json files         │
 │    2. If found: poll GChat API for messages since asked_at          │
 │    3. Match response → pending question by thread_key               │
 │    4. Parse user's reply (number, text, comma-list)                 │
 │    5. Inject via tmux send-keys → blocked Claude session            │
 │    6. Update pending question file status = "resolved"              │
 │    7. Stale cleanup: delete files older than 24 hours               │
 └──────────────────────────┬──────────────────────────────────────────┘
                             │ tmux send-keys
                             ▼
 ┌─────────────────────────────────────────────────────────────────────┐
 │  tmux session (orch-epic4 or system3)                               │
 │  Claude Code at AskUserQuestion prompt                              │
 │  Receives: Down Down Enter  (selects option 3)                     │
 │  AskUserQuestion resolves → session unblocks                       │
 └─────────────────────────────────────────────────────────────────────┘
```

### 1.2 State Registry Location

```
$CLAUDE_PROJECT_DIR/.claude/state/pending-questions/
  {session_id}-{timestamp}.json    # Active pending questions (one per dialog)

$CLAUDE_PROJECT_DIR/.claude/state/
  gchat-poller.pid                 # Daemon PID for health checks
  gchat-poller-last-poll.txt       # Timestamp of last successful poll

~/.claude/logs/
  gchat-response-poller.log        # Daemon log (rotated at 10MB)
  gchat-response-poller.err        # Daemon stderr
```

### 1.3 Data Flow A: AskUserQuestion Outbound (PreToolUse to GChat)

```
Claude Code                PreToolUse Hook              GChat                 State
    │                            │                        │                     │
    │ tool_call: AskUserQuestion │                        │                     │
    ├───────────────────────────►│                        │                     │
    │                            │ parse tool_input       │                     │
    │                            │ extract questions[]    │                     │
    │                            │ generate question_id   │                     │
    │                            │ (UUID)                 │                     │
    │                            │                        │                     │
    │                            │ write pending file ───────────────────────►│
    │                            │ (atomic: .tmp→rename)  │                     │
    │                            │                        │                     │
    │                            │ curl POST webhook ────►│                     │
    │                            │ (thread_key=question_id│                     │
    │                            │  timeout=3s)           │                     │
    │                            │                        │ message rendered    │
    │                            │◄────── HTTP 200 ───────│                     │
    │                            │                        │                     │
    │◄─── {"decision":"approve"} │                        │                     │
    │                            │                        │                     │
    │ AskUserQuestion dialog     │                        │                     │
    │ renders, session blocks    │                        │                     │
```

### 1.4 Data Flow B: GChat Response Inbound (Daemon to tmux)

```
GChat          gchat-response-poller              State                tmux
  │                     │                           │                    │
  │                     │ scan pending-questions/ ─►│                    │
  │                     │◄─ found: {session}-{ts}.json                   │
  │                     │                           │                    │
  │ poll API ◄──────────│                           │                    │
  │ GET /spaces/.../    │                           │                    │
  │ messages?filter=    │                           │                    │
  │ createTime>asked_at │                           │                    │
  │─────────────────────►                           │                    │
  │ messages[]          │                           │                    │
  │◄────────────────────│                           │                    │
  │                     │ match: thread_key==question_id                 │
  │                     │ parse: "2" → option index 1                   │
  │                     │                           │                    │
  │                     │ update status=resolved ──►│                    │
  │                     │                           │                    │
  │                     │ tmux send-keys "Down Enter" ────────────────►│
  │                     │ (target: tmux_session from pending file)       │
  │                     │                           │  AskUserQuestion   │
  │                     │                           │  receives keystrokes
  │                     │                           │  dialog resolves   │
  │                     │                           │  session unblocks  │
```

### 1.5 Data Flow C: Notification Outbound (Hook to GChat)

```
Claude Code              Notification Hook         gchat-send.sh         GChat
    │                          │                        │                   │
    │ notification event       │                        │                   │
    ├─────────────────────────►│                        │                   │
    │                          │ parse notification     │                   │
    │                          │ classify type          │                   │
    │                          │ exec gchat-send ──────►│                   │
    │                          │ --type subagent_done   │ curl POST ───────►│
    │                          │                        │◄── HTTP 200 ──────│
    │                          │◄──── exit 0 ───────────│                   │
    │◄─ (no output, fire-forget│                        │                   │
```

### 1.6 Data Flow D: System 3 Direct Outbound (Bash to GChat)

```
System 3 Claude Code                gchat-send.sh               GChat
    │                                     │                        │
    │ Bash("gchat-send --type             │                        │
    │   task_completion 'Epic done'")     │                        │
    ├────────────────────────────────────►│                        │
    │                                     │ read GOOGLE_CHAT_      │
    │                                     │   WEBHOOK_URL from env  │
    │                                     │ format JSON payload    │
    │                                     │ curl POST ────────────►│
    │                                     │◄───── HTTP 200 ────────│
    │                                     │ exit 0                 │
    │◄────────────────────────────────────│                        │
    │ Bash tool returns (< 2s)            │                        │
```

---

## 2. Component Specifications

### 2.1 gchat-ask-user-forward.py (PreToolUse Hook)

**Location**: `$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-ask-user-forward.py`

**Hook Registration** (addition to `settings.json` `PreToolUse` array):

```json
{
  "matcher": "AskUserQuestion",
  "hooks": [{
    "type": "command",
    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-ask-user-forward.py",
    "timeout": 5
  }]
}
```

The hook is registered with a 5-second timeout. This is intentionally shorter than the default 10-second hook timeout to ensure the AskUserQuestion dialog is not blocked for an extended period if the webhook is slow.

#### 2.1.1 Input JSON Schema

Claude Code delivers the following JSON on stdin for PreToolUse hooks matching `AskUserQuestion`:

```json
{
  "tool_name": "AskUserQuestion",
  "tool_input": {
    "questions": [
      {
        "question": "Which deployment approach should we use?",
        "header": "Deployment Strategy",
        "options": [
          {
            "label": "Blue-green deployment",
            "description": "Zero-downtime with instant rollback. Requires 2x infra."
          },
          {
            "label": "Rolling deployment",
            "description": "Gradual rollout. Lower infra cost, slower rollback."
          },
          {
            "label": "Other",
            "description": "Specify a custom approach"
          }
        ],
        "multiSelect": false
      }
    ]
  },
  "session_id": "orch-epic4",
  "hook_event_name": "PreToolUse"
}
```

The `questions` array may contain more than one question object. Each question has `question` (text), `header` (optional title), `options` (array of `{label, description}` objects), and `multiSelect` (boolean).

#### 2.1.2 Output JSON Schema

The hook must write JSON to stdout. The only valid decision for a PreToolUse hook that should not block execution is `approve`:

```json
{"decision": "approve"}
```

If the webhook POST fails, the hook still returns `approve`. The `AskUserQuestion` must not be blocked because the user may be at the terminal to respond locally. The GChat notification is best-effort.

On webhook failure the hook may include a `systemMessage` to inform the AI that the notification failed:

```json
{
  "decision": "approve",
  "systemMessage": "[gchat-ask-user-forward] Warning: GChat webhook POST failed (timeout). Question not forwarded to GChat. Pending question file written."
}
```

#### 2.1.3 Processing Logic

```
1. Read JSON from stdin
2. Extract session_id (from hook_input.session_id or CLAUDE_SESSION_ID env)
3. Extract tmux_session from TMUX_PANE env or derive from session_id
4. Generate question_id = str(uuid.uuid4())
5. Generate thread_key = "ask-user-" + question_id (first 8 chars)
6. Parse questions[] array
7. Format GChat message (see 2.1.4)
8. Write pending question file atomically (see 2.1.5)
9. POST to webhook (3s timeout, no retry in hook — daemon handles retry)
10. Return {"decision": "approve"} regardless of POST result
```

Step 3 — tmux session detection:

```python
def detect_tmux_session(session_id: str) -> str:
    """Determine the tmux session name for later injection."""
    # Prefer explicit env var
    tmux_session = os.environ.get("TMUX_PANE", "")
    if tmux_session:
        # TMUX_PANE is like "%3" — get the session name from tmux
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            return result.stdout.strip()

    # Fall back to CLAUDE_SESSION_ID which is set to match tmux session name
    # in the orchestrator launch scripts (e.g., "orch-epic4")
    if session_id:
        return session_id

    return ""  # No tmux — inbound injection not possible, outbound still works
```

#### 2.1.4 GChat Message Formatting

The message is formatted as a plain text GChat message (not a card) to ensure mobile readability and thread reply support.

For a single-select question:

```
[AskUserQuestion] Session: orch-epic4

Deployment Strategy
Which deployment approach should we use?

Options:
1. Blue-green deployment — Zero-downtime with instant rollback. Requires 2x infra.
2. Rolling deployment — Gradual rollout. Lower infra cost, slower rollback.
3. Other — Specify a custom approach

Reply with the option number (e.g., "2") or type a custom response.
Thread key: ask-user-a1b2c3d4
```

For a multi-select question, the prompt changes:

```
Reply with comma-separated numbers (e.g., "1,3") or type a custom response.
```

For multiple questions in a single `AskUserQuestion` call, each question is formatted as a numbered section separated by `---`. The reply format becomes:

```
Reply with answers in order, each on its own line:
Q1: <answer>
Q2: <answer>
```

For multi-question dialogs, the thread_key is shared across all questions in the call.

#### 2.1.5 Pending Question File Format

**Path**: `$CLAUDE_PROJECT_DIR/.claude/state/pending-questions/{session_id}-{unix_timestamp}.json`

**Write method**: Atomic — write to `.tmp` file first, then `os.rename()`.

```json
{
  "question_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "session_id": "orch-epic4",
  "tmux_session": "orch-epic4",
  "asked_at": "2026-02-21T10:30:00.123Z",
  "gchat_thread_key": "ask-user-a1b2c3d4",
  "questions": [
    {
      "question": "Which deployment approach should we use?",
      "header": "Deployment Strategy",
      "options": [
        {"label": "Blue-green deployment", "description": "Zero-downtime..."},
        {"label": "Rolling deployment", "description": "Gradual rollout..."},
        {"label": "Other", "description": "Specify a custom approach"}
      ],
      "multiSelect": false,
      "option_count": 3
    }
  ],
  "status": "pending",
  "resolved_at": null,
  "response": null,
  "gchat_message_sent": true,
  "gchat_message_name": "spaces/AAAA.../messages/BBBB..."
}
```

The `gchat_message_name` field is populated from the webhook response if available. When the webhook is hit directly (not the API), the response does not include the message resource name. In that case, the daemon matches by thread_key rather than by message_name.

#### 2.1.6 Error Handling

| Error Condition | Hook Behavior | Impact |
|----------------|---------------|--------|
| Webhook POST timeout (> 3s) | Return approve with systemMessage warning | AskUserQuestion proceeds, GChat not notified |
| Webhook returns non-2xx | Return approve with systemMessage warning | Same as above |
| State directory missing | Create it, then write file | Transparent to user |
| `tmux` command not found | Set tmux_session to "", continue | Outbound works, inbound cannot inject |
| stdin JSON malformed | Return approve immediately (fast path) | Hook no-ops |
| question_id collision | UUIDs make this astronomically unlikely | N/A |

The hook must never return `{"decision": "block"}` — this would prevent the AI from asking questions entirely, which is far worse than missing a GChat notification.

---

### 2.2 gchat-ask-user-answered.py (PostToolUse Hook)

**Location**: `$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-ask-user-answered.py`

**Hook Registration** (addition to `settings.json` `PostToolUse` array):

```json
{
  "matcher": "AskUserQuestion",
  "hooks": [{
    "type": "command",
    "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-ask-user-answered.py",
    "timeout": 5
  }]
}
```

#### 2.2.1 Input JSON Schema

PostToolUse hooks receive both the tool input and the tool result:

```json
{
  "tool_name": "AskUserQuestion",
  "tool_input": {
    "questions": [
      {
        "question": "Which deployment approach should we use?",
        "header": "Deployment Strategy",
        "options": [...],
        "multiSelect": false
      }
    ]
  },
  "tool_response": {
    "answers": [
      {
        "selectedOption": "Blue-green deployment",
        "customText": null
      }
    ]
  },
  "session_id": "orch-epic4",
  "hook_event_name": "PostToolUse"
}
```

The `tool_response.answers` array is parallel to `tool_input.questions`. Each answer contains either `selectedOption` (label string), `selectedOptions` (array for multi-select), or `customText` (string for "Other" responses).

#### 2.2.2 Processing Logic

```
1. Read JSON from stdin
2. Extract session_id
3. Find matching pending question file in state/pending-questions/
   - Match on: session_id AND status == "pending"
   - If multiple pending (rare): match the most recently asked_at
4. Extract answers from tool_response.answers
5. Format confirmation message (see 2.2.3)
6. POST confirmation to GChat (thread_key from pending file)
7. Clean up pending question file (unlink)
8. Return {"continue": true}
```

Matching the pending question file to the PostToolUse event is done by session_id because only one AskUserQuestion can be active per session at a time (they are blocking). If no pending file is found (race condition or system restart), the hook skips GChat notification and returns continue.

#### 2.2.3 Answer Confirmation Message Format

```
[Answered] orch-epic4

Question: Which deployment approach should we use?
Selected: Blue-green deployment
```

For multi-select:

```
[Answered] orch-epic4

Question: Which tools should be enabled?
Selected: option-1-label, option-3-label
```

For custom text ("Other"):

```
[Answered] orch-epic4

Question: Which deployment approach should we use?
Custom response: "We should use canary deployment via feature flags"
```

#### 2.2.4 Pending Question Cleanup

The hook calls `os.unlink()` on the pending question file. If the unlink fails (file already removed by daemon, or file not found), the error is swallowed. The hook does not fail on cleanup errors.

#### 2.2.5 Output JSON Schema

```json
{"continue": true}
```

PostToolUse hooks that return `{"continue": true}` allow the session to proceed normally. There is no `block` decision available for PostToolUse hooks.

---

### 2.3 gchat-notification-dispatch.py (Notification Hook)

**Location**: `$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-notification-dispatch.py`

**Hook Registration** (replaces the empty `Notification` array in `settings.json`):

```json
"Notification": [
  {
    "hooks": [{
      "type": "command",
      "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-notification-dispatch.py",
      "timeout": 5
    }]
  }
]
```

#### 2.3.1 Input JSON Schema

The Claude Code Notification hook receives a notification payload. Based on the Claude Code documentation, the schema is:

```json
{
  "session_id": "orch-epic4",
  "hook_event_name": "Notification",
  "notification": {
    "type": "subagent_complete",
    "title": "Subagent finished",
    "body": "The tdd-test-engineer subagent has completed its task.",
    "agent_name": "tdd-test-engineer",
    "timestamp": "2026-02-21T10:45:00Z"
  }
}
```

The `notification.type` field is used for routing. Known types include:

- `subagent_complete` - A native teammate subagent has finished
- `background_task_complete` - A background Task() has returned
- `idle` - The session has gone idle (no active work)
- `error` - An error occurred that requires attention

#### 2.3.2 Message Type Routing Logic

```python
TYPE_ROUTING = {
    "subagent_complete": ("progress_update", "[Subagent Done]"),
    "background_task_complete": ("progress_update", "[Task Done]"),
    "idle": None,            # Suppressed — idle notifications are noisy
    "error": ("error", "[Error]"),
}

def route_notification(notification: dict) -> tuple[str, str] | None:
    """Returns (gchat_type, prefix) or None to suppress."""
    ntype = notification.get("type", "unknown")
    routing = TYPE_ROUTING.get(ntype)
    if routing is None:
        return None  # Suppress
    return routing
```

The `idle` notification type is suppressed because orchestrators and workers go idle frequently as part of normal operation (they wait between turns). Forwarding idle notifications would create noise in GChat.

#### 2.3.3 Notification Message Formatting

For `subagent_complete`:

```
[Subagent Done] orch-epic4
tdd-test-engineer completed task
The tdd-test-engineer subagent has completed its task.
```

For `error`:

```
[Error] orch-epic4
An error occurred that requires attention.
{body text from notification}
```

#### 2.3.4 Processing Logic

```
1. Read JSON from stdin
2. Extract notification object
3. Route to message type (or suppress)
4. If suppressed: return immediately (exit 0, no output)
5. Format message body
6. exec gchat-send.sh with --type and message body
7. Return (fire-and-forget, gchat-send exit code not checked)
```

The hook does not return structured JSON — Notification hooks are fire-and-forget with no output expectations from Claude Code.

---

### 2.4 gchat-send.sh (CLI Utility)

**Location**: `$CLAUDE_PROJECT_DIR/.claude/scripts/gchat-send.sh`

**Symlink**: `~/bin/gchat-send` (installed by install.sh for PATH accessibility)

**Dependencies**: `curl`, `jq`, `python3` (for `.mcp.json` parsing fallback only)

#### 2.4.1 Command-Line Interface Specification

```
USAGE:
  gchat-send [OPTIONS] <message>
  gchat-send --type <type> [OPTIONS] <message>

ARGUMENTS:
  message         Message text to send. Required.

OPTIONS:
  --type <type>   Message type for formatting. Default: "plain".
                  Valid types: task_completion, progress_update, blocked_alert,
                               heartbeat, session_start, session_end, error, plain
  --thread-key <key>
                  Send as a reply in the given thread. Optional.
  --session <id>  Override session ID in message header. Defaults to
                  $CLAUDE_SESSION_ID or $TMUX_PANE.
  --quiet         Suppress stdout output. Exit code still reflects success/failure.
  --dry-run       Print formatted JSON to stdout without sending. Useful for testing.
  --help          Print this usage and exit.

EXIT CODES:
  0   Message sent successfully (HTTP 200-299)
  1   Webhook URL not found (env var not set, not in .mcp.json)
  2   Webhook POST failed (network error, timeout, non-2xx response)
  3   jq/curl not found
  4   Invalid arguments
```

#### 2.4.2 Message Type to Format Mapping

| Type | Prefix | Formatting Notes |
|------|--------|-----------------|
| `task_completion` | `[Done]` | Include session ID in header |
| `progress_update` | `[Progress]` | Include session ID in header |
| `blocked_alert` | `[BLOCKED]` | All-caps emphasis, include action needed |
| `heartbeat` | `[Heartbeat]` | Include timestamp, agent counts |
| `session_start` | `[Session Start]` | Include session ID, timestamp |
| `session_end` | `[Session End]` | Include duration, work completed count |
| `error` | `[Error]` | Include stack trace / error details if provided |
| `plain` | (none) | Message text as-is |

All non-plain types prepend the session ID and current timestamp in a header line:

```
[Done] orch-epic4 | 2026-02-21 10:45:23

Epic 3 completed. 12/12 subtasks validated.
```

For `blocked_alert`, the formatting adds urgency markers:

```
[BLOCKED] orch-epic4 | 2026-02-21 10:45:23

ACTION REQUIRED: Need API credentials for GChat service account.
Session cannot proceed without this.
```

#### 2.4.3 Webhook URL Resolution

The script resolves the webhook URL in the following order:

1. `$GOOGLE_CHAT_WEBHOOK_URL` environment variable (preferred, fastest)
2. Parse `.mcp.json` at `$CLAUDE_PROJECT_DIR/.mcp.json` for the `GOOGLE_CHAT_WEBHOOK_URL` key within the `mcpServers.google-chat-bridge.env` object
3. Parse `.mcp.json` at `~/.mcp.json` as a global fallback
4. If none found: exit code 1 with error message to stderr

The `.mcp.json` fallback uses `python3 -c` to safely parse JSON without depending on a specific jq path format:

```bash
WEBHOOK_URL=$(python3 -c "
import json, sys
try:
    with open('${MCP_JSON_PATH}') as f:
        cfg = json.load(f)
    bridge = cfg.get('mcpServers', {}).get('google-chat-bridge', {})
    env = bridge.get('env', {})
    print(env.get('GOOGLE_CHAT_WEBHOOK_URL', ''))
except Exception:
    pass
" 2>/dev/null)
```

#### 2.4.4 Thread Reply Support

When `--thread-key` is provided, the webhook URL is appended with `&messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD`. The JSON payload includes the thread field:

```json
{
  "text": "...",
  "thread": {
    "threadKey": "ask-user-a1b2c3d4"
  }
}
```

This matches the pattern used by the existing `WebhookClient` in `mcp-servers/google-chat-bridge/src/google_chat_bridge/webhook_client.py`.

#### 2.4.5 Internal Implementation Structure

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Parse arguments
# 2. Validate dependencies (curl, jq)
# 3. Resolve webhook URL
# 4. Detect session ID
# 5. Format message based on --type
# 6. Build JSON payload
# 7. [--dry-run] print and exit
# 8. POST via curl (3s connect timeout, 5s max time)
# 9. Check HTTP status code
# 10. Exit with appropriate code
```

The curl invocation uses `-w "%{http_code}"` to capture the HTTP status code separately from the response body, enabling reliable success/failure detection:

```bash
HTTP_STATUS=$(curl -s -o /tmp/gchat-send-response.json \
    -w "%{http_code}" \
    --connect-timeout 3 \
    --max-time 5 \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$WEBHOOK_URL")
```

---

### 2.5 gchat-response-poller.py (Background Daemon)

**Location**: `$CLAUDE_PROJECT_DIR/.claude/scripts/gchat-response-poller/gchat-response-poller.py`

**Execution context**: Outside all Claude Code sessions. Runs as a macOS launchd user agent.

**Dependencies**: Python 3.9+ (stdlib only for core loop). Google API client libraries (`google-api-python-client`, `google-auth`) are required for inbound polling. These are already installed for the `google-chat-bridge` MCP server.

#### 2.5.1 Main Loop Architecture

```python
def main_loop(config: PollerConfig) -> None:
    """Main polling loop. Runs indefinitely until SIGTERM."""
    logger.info("gchat-response-poller starting. Poll interval: %ds", config.poll_interval)
    write_pid_file(config.pid_file)

    chat_client = ChatClient(
        credentials_file=config.credentials_file,
        default_space_id=config.space_id,
    )

    while True:
        try:
            pending = scan_pending_questions(config.pending_dir)

            if pending:
                logger.debug("Found %d pending question(s)", len(pending))
                for pq in pending:
                    process_pending_question(pq, chat_client, config)
            else:
                # No pending questions — clean interval, check for stales
                cleanup_stale_files(config.pending_dir, max_age_hours=24)

            update_last_poll_timestamp(config.last_poll_file)
            time.sleep(config.poll_interval)

        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down.")
            break
        except Exception as e:
            logger.error("Unexpected error in main loop: %s", e, exc_info=True)
            time.sleep(config.poll_interval)  # Continue after errors
```

#### 2.5.2 Pending Question Scanning

```python
def scan_pending_questions(pending_dir: Path) -> list[PendingQuestion]:
    """Read all *.json files in pending-questions dir, return pending ones."""
    results = []
    for path in sorted(pending_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            if data.get("status") == "pending":
                results.append(PendingQuestion.from_dict(data, path))
        except (json.JSONDecodeError, KeyError):
            logger.warning("Malformed pending question file: %s", path)
    return results
```

#### 2.5.3 GChat API Polling Mechanism

For each pending question, the daemon polls for messages in the configured GChat space that arrived after `asked_at` and belong to the thread identified by `gchat_thread_key`:

```python
def poll_for_response(pq: PendingQuestion, client: ChatClient) -> str | None:
    """Poll GChat API for a response to the given pending question.

    Returns the user's response text if found, None if no response yet.
    """
    messages = client.get_messages_after(
        after_time=pq.asked_at,
        page_size=20,
    )

    for msg in messages:
        # Skip messages from the bot itself (webhook messages have no sender)
        if not msg.sender_name or msg.sender_name == "unknown":
            continue

        # Match by thread: the thread_name contains the thread key identifier
        # Google Chat threads are named "spaces/{space}/threads/{thread}"
        # We correlate by checking if the thread_key appears in the thread context
        if pq.gchat_thread_key in (msg.thread_name or ""):
            return msg.text.strip()

        # Fallback: if thread matching fails, accept any human reply after asked_at
        # that could plausibly answer this question (within a 5-minute window)
        # This handles webhooks that don't preserve thread metadata
        if is_plausible_response(msg.text, pq):
            return msg.text.strip()

    return None
```

The `is_plausible_response` fallback function checks if the message text looks like a valid option selection (integer in range, comma-separated integers, or non-empty text) and if the message arrived within 5 minutes of the question being asked. This fallback degrades gracefully when thread correlation fails.

#### 2.5.4 Response Parsing

```python
def parse_response(text: str, pq: PendingQuestion) -> ParsedResponse:
    """Parse user's GChat reply into tmux keystrokes.

    Handles:
    - Single integer: "2" → option index 1 (0-based)
    - Comma-separated integers: "1,3" → multi-select indices [0, 2]
    - Multi-line (multi-question): "Q1: 2\nQ2: custom text"
    - Raw text: passed as custom input for "Other"
    """
    text = text.strip()
    question = pq.questions[0]  # Primary question for single-question dialogs

    # Single integer selection
    if re.match(r'^\d+$', text):
        idx = int(text) - 1  # Convert 1-based to 0-based
        if 0 <= idx < question.option_count:
            return ParsedResponse(type="single_select", option_index=idx)
        # Out of range → treat as custom text
        return ParsedResponse(type="custom_text", text=text)

    # Comma-separated integers (multi-select)
    if re.match(r'^\d+(,\d+)*$', text) and question.multi_select:
        indices = [int(n) - 1 for n in text.split(",")]
        valid = [i for i in indices if 0 <= i < question.option_count]
        return ParsedResponse(type="multi_select", option_indices=valid)

    # Multi-question format: "Q1: answer\nQ2: answer"
    if re.search(r'^Q\d+:', text, re.MULTILINE):
        return parse_multi_question_response(text, pq)

    # Everything else → custom text (navigate to "Other", type text)
    return ParsedResponse(type="custom_text", text=text)
```

#### 2.5.5 tmux Injection Engine

The injection engine translates a `ParsedResponse` into a sequence of `tmux send-keys` commands targeting the session that is blocked at the `AskUserQuestion` prompt.

**Key Mapping Reference:**

The `AskUserQuestion` UI in Claude Code renders as a terminal menu. The first option is selected by default (highlighted). Navigation works as follows:

- `Down` arrow key moves selection down one option
- `Space` toggles selection in multi-select mode
- `Enter` confirms the current selection
- In "Other" mode: `Enter` opens a text input field, text is typed, `Enter` confirms

**Implementation:**

```python
def inject_response(pq: PendingQuestion, response: ParsedResponse, config: PollerConfig) -> bool:
    """Inject the parsed response into the tmux session.

    Returns True if injection succeeded, False if session not found.
    """
    tmux_session = pq.tmux_session
    if not tmux_session:
        logger.warning("No tmux session in pending question %s, cannot inject", pq.question_id)
        return False

    # Verify the tmux session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", tmux_session],
        capture_output=True, timeout=2
    )
    if result.returncode != 0:
        logger.warning("tmux session '%s' not found (crashed?)", tmux_session)
        return False

    keys = build_keystrokes(response, pq)

    for key in keys:
        subprocess.run(
            ["tmux", "send-keys", "-t", tmux_session, key, ""],
            check=True, timeout=2
        )
        time.sleep(0.05)  # Small delay between keystrokes for UI stability

    logger.info("Injected response into tmux session '%s'", tmux_session)
    return True


def build_keystrokes(response: ParsedResponse, pq: PendingQuestion) -> list[str]:
    """Build the list of tmux send-keys arguments."""
    keys = []
    question = pq.questions[0]

    if response.type == "single_select":
        n = response.option_index  # 0-based, first option is already selected
        for _ in range(n):
            keys.append("Down")
        keys.append("Enter")

    elif response.type == "multi_select":
        # Navigate to each selected option and toggle with Space
        # Sort indices to minimize cursor movement
        current_pos = 0
        for idx in sorted(response.option_indices):
            moves = idx - current_pos
            for _ in range(moves):
                keys.append("Down")
            keys.append(" ")  # Space to toggle
            current_pos = idx
        keys.append("Enter")

    elif response.type == "custom_text":
        # Navigate to "Other" option (last option by convention)
        other_index = question.option_count - 1
        for _ in range(other_index):
            keys.append("Down")
        keys.append("Enter")  # Select "Other" → opens text field
        # Type the custom text character by character via a single send-keys
        # (send-keys handles string literals in addition to special key names)
        keys.append(response.text)
        keys.append("Enter")  # Confirm text entry

    return keys
```

**Multi-question dialogs:**

When `pq.questions` has more than one entry, the daemon handles each question sequentially after the previous one is answered. The `AskUserQuestion` UI presents questions one at a time in sequence. The daemon waits 500ms between question responses to allow the UI to advance.

#### 2.5.6 Session Detection (tmux vs non-tmux)

The daemon checks whether the target session exists in tmux before attempting injection. If `tmux has-session` fails, the daemon:

1. Logs a warning at WARN level
2. Does NOT delete the pending question file immediately
3. Retries the session check on the next poll cycle
4. After 3 consecutive "session not found" results, marks the pending question as `abandoned` and writes a warning log entry

This retry behavior handles transient cases where the tmux session is momentarily unavailable (e.g., during context compaction which briefly suspends the session).

#### 2.5.7 Error Handling and Retry Logic

| Error | Retry Strategy | Max Retries |
|-------|---------------|-------------|
| GChat API auth failure | Log error, sleep 60s before retrying auth | 5 (then daemon continues with degraded mode) |
| GChat API rate limit (429) | Exponential backoff starting at 30s | Unlimited (keeps backing off) |
| GChat API network error | Retry on next poll cycle | Per poll cycle |
| tmux session not found | Retry on next 3 poll cycles, then mark abandoned | 3 |
| tmux send-keys failure | Log warning, do not retry | 1 |
| Pending file parse error | Log warning, skip file | 1 |
| Stale file (> 24h) | Delete unconditionally | N/A |

#### 2.5.8 Graceful Shutdown

The daemon registers signal handlers for `SIGTERM` and `SIGINT`. On receiving either signal:

1. Sets a shutdown flag
2. Finishes the current poll cycle (does not abandon in-progress injection)
3. Removes the PID file
4. Logs "Shutting down" and exits cleanly

```python
def setup_signal_handlers(shutdown_event: threading.Event) -> None:
    import signal
    def handler(signum, frame):
        logger.info("Received signal %d, initiating shutdown", signum)
        shutdown_event.set()
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
```

---

## 3. State Management

### 3.1 Pending Question File Schema (Complete)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12",
  "type": "object",
  "required": ["question_id", "session_id", "tmux_session", "asked_at",
               "gchat_thread_key", "questions", "status"],
  "properties": {
    "question_id": {
      "type": "string",
      "description": "UUID v4 identifying this question uniquely"
    },
    "session_id": {
      "type": "string",
      "description": "CLAUDE_SESSION_ID of the session that asked the question"
    },
    "tmux_session": {
      "type": "string",
      "description": "tmux session name for injection. Empty string if not in tmux."
    },
    "asked_at": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 UTC timestamp when the hook fired"
    },
    "gchat_thread_key": {
      "type": "string",
      "description": "Webhook thread key used for GChat thread correlation"
    },
    "gchat_message_sent": {
      "type": "boolean",
      "description": "Whether the outbound webhook POST succeeded"
    },
    "gchat_message_name": {
      "type": ["string", "null"],
      "description": "GChat message resource name if available from API response"
    },
    "questions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["question", "options", "multiSelect", "option_count"],
        "properties": {
          "question": {"type": "string"},
          "header": {"type": ["string", "null"]},
          "options": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "label": {"type": "string"},
                "description": {"type": ["string", "null"]}
              }
            }
          },
          "multiSelect": {"type": "boolean"},
          "option_count": {"type": "integer"}
        }
      }
    },
    "status": {
      "type": "string",
      "enum": ["pending", "resolved", "abandoned", "expired"]
    },
    "resolved_at": {"type": ["string", "null"], "format": "date-time"},
    "response": {"type": ["string", "null"]},
    "response_type": {
      "type": ["string", "null"],
      "enum": ["single_select", "multi_select", "custom_text", null]
    },
    "injection_attempted": {"type": "boolean"},
    "injection_succeeded": {"type": ["boolean", "null"]}
  }
}
```

### 3.2 File Lifecycle

```
1. CREATED by gchat-ask-user-forward.py
   - Status: "pending"
   - Path: {session_id}-{unix_ts}.json
   - Write: atomic (tmp → rename)

2. READ by gchat-response-poller.py (daemon)
   - Every 10 seconds while status == "pending"
   - No modification at read time

3. RESOLVED by gchat-response-poller.py
   - After successful tmux injection
   - Status updated to "resolved"
   - resolved_at, response, injection_succeeded populated
   - Write: atomic (tmp → rename)
   - File retained until cleanup

4. CLEANED UP by gchat-ask-user-answered.py (PostToolUse hook)
   - Fires after AskUserQuestion returns
   - Calls os.unlink() on the file
   - If file not found: no error (daemon may have cleaned it)

5. STALE CLEANUP by gchat-response-poller.py
   - Files older than 24 hours regardless of status
   - Prevents accumulation from crashed sessions
   - Logs cleanup at INFO level

6. ABANDONED by gchat-response-poller.py
   - After 3 consecutive "tmux session not found" checks
   - Status updated to "abandoned"
   - Remains for 24 hours then stale-cleaned
```

### 3.3 Concurrency Handling

**Write conflicts** between the hook (writing) and the daemon (reading) are addressed through atomic writes. Python's `os.rename()` is atomic on POSIX systems when source and destination are on the same filesystem, which is guaranteed since the `.tmp` file is in the same directory.

**Simultaneous pending questions** from different sessions: Each file is namespaced by `{session_id}-{unix_ts}.json`. Since a session can only block on one AskUserQuestion at a time, there is at most one file per session. Multiple sessions can each have one pending file simultaneously with no conflict.

**Read-modify-write by daemon**: The daemon writes atomically when updating status from `pending` to `resolved`. Since only the daemon performs this update (the hook only creates and deletes), there is no write-write conflict between daemon and hook.

**File locking**: Explicit `fcntl` file locking is not used because:
1. The create-write-rename pattern is already atomic
2. The daemon is a single-threaded process (no concurrent threads touching the same file)
3. The hook runs once per `AskUserQuestion` call (Claude Code does not parallelize hook execution)

### 3.4 Stale File Cleanup

The daemon runs stale file cleanup during any poll cycle where there are zero pending questions. It does not run cleanup when processing pending questions (to avoid race conditions with in-progress injections).

```python
def cleanup_stale_files(pending_dir: Path, max_age_hours: int = 24) -> int:
    """Delete pending question files older than max_age_hours.

    Returns the number of files deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    deleted = 0
    for path in pending_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            asked_at = datetime.fromisoformat(data["asked_at"].replace("Z", "+00:00"))
            if asked_at < cutoff:
                path.unlink()
                logger.info("Stale cleanup: deleted %s (asked %s)", path.name, asked_at)
                deleted += 1
        except Exception as e:
            logger.warning("Stale cleanup error for %s: %s", path, e)
    return deleted
```

---

## 4. Configuration

### 4.1 settings.json Hook Additions

The following additions are required to `$CLAUDE_PROJECT_DIR/.claude/settings.json`. The existing structure is preserved; only new entries are added.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/doc-gardener-pre-push-hook.py",
          "timeout": 65
        }]
      },
      {
        "matcher": "AskUserQuestion",
        "hooks": [{
          "type": "command",
          "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-ask-user-forward.py",
          "timeout": 5
        }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/message-bus-signal-check.py"
        }]
      },
      {
        "matcher": "AskUserQuestion",
        "hooks": [{
          "type": "command",
          "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-ask-user-answered.py",
          "timeout": 5
        }]
      }
    ],
    "Notification": [
      {
        "hooks": [{
          "type": "command",
          "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/gchat-notification-dispatch.py",
          "timeout": 5
        }]
      }
    ]
  }
}
```

The Stop hook is extended within `unified-stop-gate.sh` itself (see section 4.4) rather than as a separate hook entry, to ensure the GChat session-end notification fires at the correct point in the stop gate flow (after all checks pass).

### 4.2 launchd Plist Specification

**Path**: `~/Library/LaunchAgents/com.claude.gchat-response-poller.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude.gchat-response-poller</string>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$CLAUDE_PROJECT_DIR/.claude/scripts/gchat-response-poller/gchat-response-poller.py</string>
        <string>--pending-dir</string>
        <string>$CLAUDE_PROJECT_DIR/.claude/state/pending-questions</string>
        <string>--poll-interval</string>
        <string>10</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>Crashed</key>
        <true/>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>20</integer>

    <key>StandardOutPath</key>
    <string>~/.claude/logs/gchat-response-poller.log</string>

    <key>StandardErrorPath</key>
    <string>~/.claude/logs/gchat-response-poller.err</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>GOOGLE_CHAT_CREDENTIALS_FILE</key>
        <string>~/.config/google/service-account.json</string>
        <key>GOOGLE_CHAT_SPACE_ID</key>
        <string>spaces/AAAA...</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>

    <key>WorkingDirectory</key>
    <string>$CLAUDE_PROJECT_DIR</string>
</dict>
</plist>
```

**Key design decisions in the plist:**

- `KeepAlive.Crashed: true` - Restart if daemon crashes
- `KeepAlive.SuccessfulExit: false` - Do not restart if daemon exits cleanly (allows manual stop)
- `ThrottleInterval: 20` - Minimum 20 seconds between restart attempts (prevents crash loops)
- `StandardOutPath` points to `~/.claude/logs/` not the project dir (survives project directory changes)
- `EnvironmentVariables` must be populated by the install script with actual values from `.mcp.json`

**Log rotation**: launchd does not natively rotate logs. A companion `com.claude.gchat-log-rotate.plist` runs `newsyslog` monthly, or the install script configures a cron entry using `newsyslog.conf`.

Alternative lightweight rotation: The daemon itself can check log file size at startup and rotate if > 10MB:

```python
def rotate_log_if_needed(log_path: Path, max_bytes: int = 10 * 1024 * 1024) -> None:
    if log_path.exists() and log_path.stat().st_size > max_bytes:
        rotated = log_path.with_suffix(".log.1")
        log_path.rename(rotated)
```

### 4.3 Environment Variables

| Variable | Purpose | Source | Required |
|----------|---------|--------|----------|
| `GOOGLE_CHAT_WEBHOOK_URL` | Outbound webhook endpoint | `.mcp.json` env or shell profile | Yes (for outbound) |
| `GOOGLE_CHAT_CREDENTIALS_FILE` | Service account JSON for inbound API | `.mcp.json` env or launchd plist | Yes (for inbound) |
| `GOOGLE_CHAT_SPACE_ID` | Space to poll for inbound messages | `.mcp.json` env or launchd plist | Yes (for inbound) |
| `CLAUDE_SESSION_ID` | Session identifier for pending files | Set by Claude Code / launch scripts | Auto |
| `CLAUDE_PROJECT_DIR` | Project root for state file paths | Set by Claude Code | Auto |
| `TMUX_PANE` | Current tmux pane identifier | Set by tmux | Auto (tmux only) |
| `GCHAT_POLLER_INTERVAL` | Override default 10s poll interval | Optional, daemon only | No |
| `GCHAT_POLLER_PENDING_DIR` | Override default pending-questions dir | Optional, daemon only | No |

### 4.4 Stop Hook Extension

The `unified-stop-gate.sh` is extended to call `gchat-send` at the end of a successful stop gate sequence. This is implemented as the final step in the shell script, after all Python checks pass and the decision is `continue`:

```bash
# At the end of unified-stop-gate.sh, after the Python evaluator returns "continue"
if [ "$GATE_DECISION" = "continue" ]; then
    # Send session-end notification to GChat (best-effort, non-blocking)
    SESSION_ID="${CLAUDE_SESSION_ID:-unknown}"
    DURATION=$(compute_session_duration)  # from session start time in state
    gchat-send --type session_end --quiet \
        "Session ${SESSION_ID} ended. Duration: ${DURATION}." 2>/dev/null || true
fi
```

The `|| true` ensures that a gchat-send failure never causes the stop gate to block or error.

---

## 5. Non-tmux Session Handling

This is the most architecturally significant edge case in the design. The two Claude Code session types have different tmux characteristics:

### 5.1 Session Type Analysis

| Session Type | Launch Command | tmux | AskUserQuestion Forwarding | GChat Injection |
|-------------|---------------|------|--------------------------|-----------------|
| System 3 | `ccsystem3` | Depends on `ccsystem3` implementation | Yes (outbound) | Only if tmux |
| Orchestrator | `launchorchestrator [name]` | Always (tmux new-session) | Yes (outbound) | Yes |
| Worker | Spawned as native teammate | Shares lead's tmux | Yes (outbound) | Through lead session |
| Development / one-off | `claude` directly | No | Yes (outbound only) | No |

### 5.2 The ccsystem3 tmux Situation

Based on the memory context (tmux Spawn Pattern v3, 2026-02-17), `ccsystem3` is a zsh function that may or may not create a tmux session depending on whether the user invokes it from within tmux. The design must not assume System 3 always has tmux.

**Proposed behavior:**

When `gchat-ask-user-forward.py` runs in a non-tmux context:
- `TMUX_PANE` is unset
- `tmux display-message` fails
- The hook sets `tmux_session: ""` in the pending question file

When the daemon reads a pending question with `tmux_session: ""`:
- The outbound GChat message was already sent (the question appears in GChat)
- The daemon logs: "Pending question {id} has no tmux session — cannot inject response"
- The daemon does NOT mark the question as abandoned immediately
- Instead, it checks if the `CLAUDE_SESSION_ID` matches a currently-active tmux session name (the session may have been wrapped in tmux after the fact):
  ```python
  def try_locate_tmux_session(session_id: str) -> str:
      """Try to find a tmux session matching the session_id."""
      result = subprocess.run(
          ["tmux", "list-sessions", "-F", "#{session_name}"],
          capture_output=True, text=True, timeout=2
      )
      if result.returncode == 0:
          for name in result.stdout.splitlines():
              if name == session_id or name.startswith(session_id):
                  return name
      return ""
  ```
- If a matching tmux session is found despite `tmux_session: ""` in the file, the daemon uses it for injection

### 5.3 Graceful Degradation for Plain Terminal Sessions

For sessions running without tmux (e.g., a developer running `claude` directly):

1. **Outbound works normally**: The GChat notification is sent. The user sees the question in GChat.
2. **Inbound cannot be injected**: The daemon has no tmux target. It logs a warning.
3. **User must answer locally**: The user sees the question on their terminal and answers there.
4. **PostToolUse hook fires normally**: The `gchat-ask-user-answered.py` hook sends the answer confirmation to GChat.
5. **Pending file is cleaned up**: By the PostToolUse hook after the answer.

This degradation is acceptable because non-tmux sessions are typically developer/interactive sessions where the user is physically present. The primary value of GChat injection is for autonomous orchestrator sessions running in background tmux panes.

### 5.4 ccsystem3 tmux Wrapping Recommendation

To enable full GChat injection for System 3, `ccsystem3` should be updated to always start within tmux. The recommended pattern (from tmux Spawn Pattern v3):

```bash
function ccsystem3() {
    local SESSION_NAME="system3-$(date +%s)"
    export CLAUDE_SESSION_ID="$SESSION_NAME"
    unset CLAUDECODE  # Prevents nested session error

    if [ -n "$TMUX" ]; then
        # Already in tmux — create a new window
        tmux new-window -n "$SESSION_NAME" "exec zsh -c 'claude ...'"
    else
        # Not in tmux — create new session
        tmux new-session -d -s "$SESSION_NAME" "exec zsh -c 'claude ...'"
        tmux attach -t "$SESSION_NAME"
    fi
}
```

This is a recommendation for the Epic 4 migration phase, not a requirement for the initial hook implementation.

---

## 6. Edge Cases

### 6.1 Multiple Simultaneous AskUserQuestion Dialogs

**Scenario**: System 3, two orchestrators, and a worker all hit `AskUserQuestion` within the same 10-second poll window.

**Handling**:
- Each session writes its own `{session_id}-{timestamp}.json` file
- Each file has a unique `gchat_thread_key` (`ask-user-{uuid}`)
- Each GChat message is in its own thread (GChat webhook creates a new thread per unique thread key)
- The daemon processes each pending file independently
- The user sees 4 separate threads in GChat, can reply to each independently
- Thread-key matching ensures each reply goes to the correct session

**Limitation**: If the user replies to the wrong thread, the wrong session receives the injected answer. This is mitigated by clear session identification in the GChat message header (`[AskUserQuestion] Session: orch-epic4`).

### 6.2 User Responds to Wrong Question Thread

**Scenario**: User replies "2" to the System 3 thread but meant to reply to the `orch-epic4` thread.

**Handling**:
1. The daemon matches the "2" reply to the System 3 pending question (correct thread key)
2. System 3 receives the injected answer
3. The `orch-epic4` pending question remains unanswered until the user replies to its thread
4. There is no automatic detection or correction of cross-thread responses

**Mitigation in UI**: The GChat message format must clearly identify the session. Additionally, the thread title (set by GChat from the first message in the thread) includes the session ID, making it harder to confuse.

**Worst case**: System 3 receives an answer intended for an orchestrator. The AskUserQuestion resolves with a potentially wrong answer. This is treated as user error and is equivalent to pressing the wrong key locally. The user can observe the result in GChat via the confirmation message from `gchat-ask-user-answered.py`.

### 6.3 Session Crashes Between Question and Answer

**Scenario**: The `AskUserQuestion` is forwarded to GChat. Before the daemon can inject a response, the tmux session crashes (out of memory, user killed it, etc.).

**Handling**:
1. The pending question file remains in `state/pending-questions/`
2. The daemon attempts injection on the next poll cycle
3. `tmux has-session` fails → daemon logs warning
4. After 3 consecutive failures, daemon sets status to `abandoned`
5. After 24 hours, stale cleanup removes the file

**GChat visibility**: The question thread in GChat never receives an `[Answered]` confirmation because the PostToolUse hook never fired (session crashed). This is acceptable — the absence of a confirmation message indicates something went wrong. The user can check the session in the monitoring tooling.

### 6.4 GChat API Unavailable (Daemon Fallback)

**Scenario**: The GChat API is down or credentials expire while the daemon is running.

**Handling**:

For **outbound** (hooks and gchat-send.sh): The webhook URL is a separate endpoint from the API. Webhook availability is independent of API availability. Outbound typically continues working even when the read API is down.

For **inbound** (daemon polling): If `client.get_messages_after()` raises an exception:
1. Daemon logs the error at ERROR level
2. Daemon sleeps `poll_interval * backoff_factor` (starts at 10s, doubles up to 5 minutes)
3. Daemon does not delete pending files during the outage
4. Pending files accumulate until resolved or stale-cleaned (24h)

**Local file queue fallback**: The PRD mentions a fallback to `.claude/user-input-queue/`. This design implements a simpler variant: the daemon reads a `user-input-queue/{session_id}.txt` file if it exists, treating its contents as the response to inject. This allows users to manually create response files if GChat is unavailable:

```bash
# Manual fallback: respond to orch-epic4's pending question
echo "2" > .claude/state/user-input-queue/orch-epic4.txt
```

The daemon checks for these files during each poll cycle, before attempting the GChat API call.

### 6.5 Webhook POST Timeout

**Scenario**: The hook fires, attempts `curl` POST, but the request times out after 3 seconds.

**Handling**:
1. Hook returns `{"decision": "approve"}` with a `systemMessage` warning
2. The pending question file was already written before the POST attempt
3. The `gchat_message_sent: false` field in the pending file records the failure
4. The daemon reads the pending file but cannot correlate a response (no GChat thread exists for this question)
5. The daemon logs: "Pending question {id}: gchat_message_sent=false, no thread to poll"
6. The pending question remains in `pending` status until stale-cleaned (24h)

**Partial mitigation**: The daemon could attempt a belated POST of the GChat message using `gchat-send.sh` (since the question text is in the pending file). This would create a new GChat thread with a delay. However, implementing this retry in the daemon adds complexity. This is a design choice for the implementer: the simpler path (no retry) is recommended for v1.

### 6.6 Unicode and Special Characters

**Scenario**: The question text or options contain Unicode, newlines, emoji, or shell-special characters.

**Handling for outbound (webhook POST)**:
- Python's `json.dumps()` handles Unicode encoding natively
- The webhook payload is always `Content-Type: application/json` with UTF-8 encoding
- No escaping issues

**Handling for gchat-send.sh (bash)**:
- Message text is passed to `jq` using `--arg` which handles arbitrary strings including Unicode and single quotes
- Example: `jq -n --arg text "$MESSAGE" '{"text": $text}'`

**Handling for tmux injection**:
- Custom text responses are passed to `tmux send-keys` as a string argument
- tmux `send-keys` handles UTF-8 but has issues with some special characters (particularly `{`, `}`, `$`, backticks in shell contexts)
- Mitigation: The injection function escapes known problematic characters before passing to `send-keys`
- For the `AskUserQuestion` UI specifically, users are selecting from numbered options (which are just integers), so custom text injection is the rare case

**Handling for file naming**:
- File names use `{session_id}-{unix_timestamp}.json`
- Session IDs are constrained to `[a-zA-Z0-9_-]+` by the launch scripts
- Unix timestamps are pure integers
- No Unicode in file names

---

## 7. Testing Strategy

### 7.1 Unit Tests

Unit tests use pytest and are located at `.claude/tests/gchat-hooks/`.

**gchat-ask-user-forward.py tests** (`test_ask_user_forward.py`):

```python
# Test cases:
# 1. Single-select question → correct GChat format
# 2. Multi-select question → correct GChat format with multi-select instruction
# 3. Multiple questions in one call → correct sequential format
# 4. No options (free text question) → treated as custom text only
# 5. Webhook POST success → returns approve, file written
# 6. Webhook POST timeout → returns approve with systemMessage, file written
# 7. Webhook POST network error → returns approve with systemMessage, file written
# 8. Malformed stdin JSON → returns approve (fast path)
# 9. Missing CLAUDE_PROJECT_DIR → uses getcwd() fallback
# 10. tmux not in PATH → tmux_session="" in pending file
# 11. Pending question file written atomically (tmp file removed)
# 12. thread_key format: "ask-user-" + first 8 chars of UUID
```

**gchat-ask-user-answered.py tests** (`test_ask_user_answered.py`):

```python
# Test cases:
# 1. Single-select answer → correct confirmation format
# 2. Multi-select answer → comma-joined labels in confirmation
# 3. Custom text answer → "Custom response:" format
# 4. Matching pending file found → file deleted after confirmation
# 5. No matching pending file → no error, returns continue
# 6. Webhook POST fails → returns continue (no error)
```

**gchat-notification-dispatch.py tests** (`test_notification_dispatch.py`):

```python
# Test cases:
# 1. subagent_complete → calls gchat-send --type progress_update
# 2. error → calls gchat-send --type error
# 3. idle → suppressed (gchat-send not called)
# 4. unknown type → suppressed
# 5. gchat-send not in PATH → exits 0 silently (no block)
```

**gchat-send.sh tests** (`test_gchat_send.sh` using bats or similar):

```bash
# Test cases:
# 1. --type task_completion → [Done] prefix in payload
# 2. --type blocked_alert → [BLOCKED] prefix + ACTION REQUIRED
# 3. --thread-key → messageReplyOption in URL
# 4. --dry-run → prints JSON, no curl call
# 5. GOOGLE_CHAT_WEBHOOK_URL not set, not in .mcp.json → exit 1
# 6. GOOGLE_CHAT_WEBHOOK_URL from env → used directly
# 7. Webhook URL from .mcp.json → parsed correctly
# 8. curl HTTP 200 → exit 0
# 9. curl HTTP 500 → exit 2
# 10. curl timeout → exit 2
# 11. jq not found → exit 3
# 12. Missing message argument → exit 4 with usage
```

**response_parser.py tests** (`test_response_parser.py`):

```python
# Test cases:
# 1. "1" → single_select, index 0
# 2. "3" → single_select, index 2
# 3. "0" → out of range (0-based invalid) → custom_text
# 4. "99" → out of range → custom_text
# 5. "1,3" → multi_select, indices [0, 2]
# 6. "1, 3" → multi_select (strips spaces)
# 7. "custom response text" → custom_text
# 8. "Q1: 2\nQ2: custom text" → multi_question response
# 9. Empty string → custom_text
# 10. Unicode text → custom_text (preserved)
```

**inject_engine.py tests** (`test_inject_engine.py`):

```python
# Test cases (use tmux mock subprocess):
# 1. single_select index 0 → ["Enter"]
# 2. single_select index 2 → ["Down", "Down", "Enter"]
# 3. multi_select [0, 2] → ["Space", "Down", "Down", "Space", "Enter"]
# 4. custom_text "hello" → [Down×(n-1), "Enter", "hello", "Enter"]
# 5. tmux session not found → returns False, no send-keys calls
# 6. tmux send-keys fails → logs warning, returns False
# 7. 50ms delay between keystrokes confirmed
```

### 7.2 Integration Test: Full AskUserQuestion Round-Trip

**Test scenario**: End-to-end test from AskUserQuestion dialog through GChat to tmux injection.

**Location**: `.claude/tests/gchat-hooks/test_integration_roundtrip.py`

**Setup**: The test uses a real tmux session and a GChat webhook/API mock (or a test GChat space with test credentials).

```python
class TestAskUserQuestionRoundTrip:
    """Integration test for the full AskUserQuestion → GChat → tmux flow."""

    @pytest.fixture
    def tmux_session(self):
        """Create a temporary tmux session for testing."""
        session_name = f"test-gchat-{int(time.time())}"
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name], check=True)
        # Launch a simple Python script that calls AskUserQuestion (simulated)
        yield session_name
        subprocess.run(["tmux", "kill-session", "-t", session_name])

    @pytest.fixture
    def pending_question_file(self, tmp_path, tmux_session):
        """Write a synthetic pending question file."""
        pq = {
            "question_id": "test-uuid-1234",
            "session_id": tmux_session,
            "tmux_session": tmux_session,
            "asked_at": datetime.now(timezone.utc).isoformat(),
            "gchat_thread_key": "ask-user-test1234",
            "gchat_message_sent": True,
            "questions": [{
                "question": "Test question?",
                "header": "Test",
                "options": [
                    {"label": "Option A", "description": "First"},
                    {"label": "Option B", "description": "Second"}
                ],
                "multiSelect": False,
                "option_count": 2
            }],
            "status": "pending",
            "resolved_at": None,
            "response": None
        }
        path = tmp_path / f"{tmux_session}-test.json"
        path.write_text(json.dumps(pq))
        return path

    def test_option_selection_injected_to_tmux(self, pending_question_file, tmux_session):
        """Response "2" should inject Down + Enter into tmux session."""
        # Start a process in the tmux session that records keystrokes
        subprocess.run([
            "tmux", "send-keys", "-t", tmux_session,
            "python3 -c 'import sys; data=sys.stdin.read(); open(\"/tmp/keys.txt\",\"w\").write(data)' ", ""
        ])

        # Simulate daemon receiving "2" as GChat response
        with patch.object(ChatClient, "get_messages_after") as mock_poll:
            mock_poll.return_value = [
                ChatMessage(name="spaces/X/messages/Y", text="2",
                           sender_name="users/human", thread_name="test-thread/ask-user-test1234")
            ]
            poller = GChatResponsePoller(config=test_config)
            poller.process_pending_question(
                PendingQuestion.from_dict(json.loads(pending_question_file.read_text()), pending_question_file)
            )

        # Verify the pending file is marked resolved
        data = json.loads(pending_question_file.read_text())
        assert data["status"] == "resolved"
        assert data["response"] == "2"
        assert data["injection_succeeded"] is True
```

### 7.3 Daemon Health Check

The daemon exposes a simple health check mechanism via a state file rather than an HTTP endpoint (to avoid dependency on a web framework):

**Health check file**: `.claude/state/gchat-poller-last-poll.txt`

Contents: ISO 8601 timestamp of the last successful poll cycle.

A companion script `.claude/scripts/gchat-response-poller/health-check.sh` reads this file and exits with:
- `0` if last poll was within 2× poll_interval (daemon is healthy)
- `1` if last poll was more than 2× poll_interval ago (daemon may be stuck)
- `2` if the health file does not exist (daemon never ran or never completed a poll)

```bash
#!/usr/bin/env bash
# health-check.sh — check if gchat-response-poller is operating
HEALTH_FILE="${CLAUDE_PROJECT_DIR}/.claude/state/gchat-poller-last-poll.txt"
POLL_INTERVAL="${GCHAT_POLLER_INTERVAL:-10}"
MAX_AGE=$((POLL_INTERVAL * 2))

if [ ! -f "$HEALTH_FILE" ]; then
    echo "WARN: Health file not found — daemon may not have run yet"
    exit 2
fi

LAST_POLL=$(cat "$HEALTH_FILE")
NOW=$(date -u +%s)
LAST_POLL_EPOCH=$(date -d "$LAST_POLL" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$LAST_POLL" +%s)
AGE=$((NOW - LAST_POLL_EPOCH))

if [ "$AGE" -le "$MAX_AGE" ]; then
    echo "OK: Last poll ${AGE}s ago (threshold: ${MAX_AGE}s)"
    exit 0
else
    echo "WARN: Last poll ${AGE}s ago (threshold: ${MAX_AGE}s) — daemon may be stuck"
    exit 1
fi
```

---

## 8. Migration Plan

### 8.1 Phase 1: Deploy Hooks Alongside s3-communicator (Parallel Run)

**Goal**: Verify hooks work without disrupting existing s3-communicator operation.

**Steps**:
1. Deploy `gchat-ask-user-forward.py` and `gchat-ask-user-answered.py` hooks
2. Deploy `gchat-send.sh` CLI
3. Deploy `gchat-notification-dispatch.py` hook
4. Update `settings.json` to register the new hooks
5. Create `state/pending-questions/` directory
6. Deploy `gchat-response-poller.py` daemon
7. Install daemon via `install.sh` (launchd)
8. Run daemon in dry-run mode for 48 hours: verify pending files are created/resolved without tmux injection

**Success criteria for Phase 1**:
- [ ] AskUserQuestion calls appear in GChat within 2 seconds
- [ ] Answer confirmations appear in GChat within 2 seconds of selection
- [ ] Pending question files are created and cleaned up correctly
- [ ] Daemon starts on login and runs continuously
- [ ] s3-communicator continues to function normally (parallel operation)
- [ ] No hook timeout errors in Claude Code logs

**Rollback**: Disable new hooks in `settings.json` by removing their entries. The s3-communicator continues unchanged.

### 8.2 Phase 2: Enable tmux Injection (Live Response Routing)

**Goal**: Enable inbound GChat → tmux injection for orchestrator sessions.

**Prerequisites**: Phase 1 running stably for 48+ hours.

**Steps**:
1. Enable tmux injection in daemon (remove dry-run flag)
2. Test with a non-critical orchestrator session (e.g., a test epic)
3. Manually verify injection by watching the tmux session while responding in GChat
4. Monitor daemon logs for injection errors
5. Update `ccsystem3` to always run in tmux (see section 5.4)

**Success criteria for Phase 2**:
- [ ] GChat reply "2" correctly selects Option B in the AskUserQuestion dialog
- [ ] Multi-select responses work correctly
- [ ] Custom text responses work correctly
- [ ] Session-end notifications sent to GChat when stop gate passes
- [ ] System 3 uses `gchat-send` for at least one message type

**Rollback**: Set daemon to dry-run mode. tmux injection stops but outbound continues.

### 8.3 Phase 3: Remove s3-communicator

**Goal**: Eliminate s3-communicator and update all references.

**Prerequisites**: Phase 2 running stably for 72+ hours without regressions.

**Steps**:
1. Update System 3 output style (`system3-meta-orchestrator.md`):
   - Remove s3-communicator spawn instructions
   - Replace `SendMessage(recipient="s3-communicator", ...)` with `Bash("gchat-send ...")`
   - Update cost estimates and agent count
   - Update Post-Compaction Recovery (2 agents: heartbeat + validator)
2. Update stop gate (`communicator_checker.py` → `persistent_agent_checker.py`):
   - Check for ANY persistent agent, not specifically s3-communicator
   - Ensure backward compatibility if s3-communicator still present
3. Archive s3-communicator skill:
   - Move `.claude/skills/s3-communicator/` to `.claude/skills/_archived/s3-communicator/`
   - Update s3-heartbeat SKILL.md
   - Update system3-orchestrator SKILL.md
4. Update SYSTEM3_CHANGELOG.md with migration notes
5. Start a new System 3 session (fresh session without s3-communicator spawn)
6. Verify all GChat communication works through hooks only

**Success criteria for Phase 3**:
- [ ] System 3 starts without spawning s3-communicator
- [ ] All outbound GChat messages delivered (no regression)
- [ ] AskUserQuestion forwarding and injection working
- [ ] Stop gate passes without s3-communicator in team
- [ ] Cost reduction: ~$0.30-$0.60/day eliminated
- [ ] SYSTEM3_CHANGELOG.md updated

**Rollback**:
1. Restore `system3-meta-orchestrator.md` from git
2. Restore `communicator_checker.py` from git
3. Move skill back from `_archived/`
4. Launch new System 3 session (it will spawn s3-communicator as before)
5. The hooks and daemon continue running (harmless alongside s3-communicator)

### 8.4 Rollback Summary

| Phase | Rollback Trigger | Rollback Action | Recovery Time |
|-------|-----------------|-----------------|---------------|
| Phase 1 | Hook timeout errors > 5/hour | Remove hook entries from settings.json | < 5 min |
| Phase 2 | Wrong keys injected into session | Set daemon dry-run mode | < 2 min |
| Phase 3 | GChat messages missing | git revert output style, restore communicator | 10-15 min (new session) |

---

## 9. File Layout Summary

All new files introduced by this design:

```
.claude/
├── hooks/
│   ├── gchat-ask-user-forward.py          # PreToolUse: AskUserQuestion capture
│   ├── gchat-ask-user-answered.py         # PostToolUse: Answer confirmation
│   └── gchat-notification-dispatch.py    # Notification: GChat forwarding
├── scripts/
│   ├── gchat-send.sh                      # CLI: On-demand GChat messaging
│   └── gchat-response-poller/
│       ├── gchat-response-poller.py       # Daemon: Inbound polling + injection
│       ├── poller_config.py               # Daemon: Configuration dataclass
│       ├── pending_question.py            # Daemon: PendingQuestion model
│       ├── response_parser.py             # Daemon: GChat reply → ParsedResponse
│       ├── inject_engine.py               # Daemon: ParsedResponse → tmux keystrokes
│       ├── install.sh                     # Daemon: macOS launchd install
│       ├── uninstall.sh                   # Daemon: macOS launchd uninstall
│       └── health-check.sh               # Daemon: Health check utility
├── state/
│   └── pending-questions/                 # Runtime: Active AskUserQuestion registry
│       └── (runtime JSON files)
└── tests/
    └── gchat-hooks/
        ├── test_ask_user_forward.py
        ├── test_ask_user_answered.py
        ├── test_notification_dispatch.py
        ├── test_gchat_send.sh
        ├── test_response_parser.py
        ├── test_inject_engine.py
        └── test_integration_roundtrip.py

~/Library/LaunchAgents/
└── com.claude.gchat-response-poller.plist  # macOS service definition
```

---

## 10. Success Metrics

| Metric | Baseline | Target | Measurement Method |
|--------|---------|--------|--------------------|
| Daily GChat relay token cost | ~$0.30-$0.60/day | $0/day | Anthropic billing dashboard |
| AskUserQuestion → GChat latency | N/A (not possible) | < 3 seconds | Hook execution time + webhook POST time |
| GChat reply → tmux injection latency | N/A | < 15 seconds | Poll interval (10s) + processing (< 1s) |
| Outbound message latency | ~5-10s (3-hop relay) | < 2 seconds | gchat-send.sh execution time |
| Persistent agents in s3-live | 3 | 2 | Team config after Phase 3 |
| GChat code size for relay | 470 lines (SKILL.md) | ~300 lines (all new files combined) | wc -l |
| Hook timeout rate | 0% (hooks didn't exist) | < 0.1% | Claude Code hook error logs |
| Daemon uptime | N/A | > 99% | launchd restart count |
| Stale pending files | N/A | 0 (cleaned after 24h) | File count in pending-questions/ |

---

## 11. Open Questions and Decisions Deferred to Implementation

1. **Thread key matching fidelity**: The design assumes the GChat API returns the `thread.name` field for messages. If the webhook does not write into a named thread (some webhook configurations do not support this), the thread-key correlation fails silently and falls back to recency matching. The implementer should test with the actual GChat space configuration to determine which matching strategy is primary.

2. **AskUserQuestion UI key mapping**: The exact key sequence for AskUserQuestion dialogs should be verified during implementation. The menu rendering may differ between terminal types and Claude Code versions. A brief manual test with tmux send-keys is required before Phase 2 goes live.

3. **Multi-question sequencing delay**: The 500ms delay between question answers in multi-question dialogs is a guess. The correct value depends on how fast the AskUserQuestion UI advances between questions. This should be measured empirically during Phase 2 testing.

4. **launchd plist path hardcoding**: The plist hardcodes the user's home directory and project directory. The `install.sh` script must use `sed` or Python to substitute the correct paths at install time. The design shows literal paths for clarity; the implementer should use template substitution.

5. **s3-communicator parallel operation during Phase 1**: During parallel operation, both s3-communicator and the hooks will send GChat messages for the same events. This creates duplicate messages in GChat (e.g., task completion announced twice). The test plan should include verifying that duplicate messages are acceptable to the user for a 48-72 hour evaluation period, or the Phase 1 hooks should be limited to AskUserQuestion only (which s3-communicator cannot do) to avoid duplication.

6. **Google Chat API version**: The `ChatClient` in `mcp-servers/google-chat-bridge/src/google_chat_bridge/chat_client.py` uses `googleapiclient.discovery.build("chat", "v1", ...)`. The daemon can import this class directly (to avoid reimplementing the auth logic) if the MCP server package is on the Python path. The implementer should decide whether to import the existing `ChatClient` or reimplement a minimal version using `urllib.request` (stdlib-only, no pip dependencies required by the PRD's dependency constraints).

---

## Appendix A: Existing Code References

The following existing files are directly relevant to implementation:

| File | Relevance |
|------|-----------|
| `.claude/hooks/message-bus-signal-check.py` | Reference implementation for PostToolUse hook structure (stdin parsing, `{"continue": true}` output) |
| `.claude/hooks/doc-gardener-pre-push-hook.py` | Reference implementation for PreToolUse hook structure (`{"decision": "approve"}` / `{"decision": "block"}` output) |
| `mcp-servers/google-chat-bridge/src/google_chat_bridge/webhook_client.py` | Existing webhook POST implementation (thread key, messageReplyOption, urllib) |
| `mcp-servers/google-chat-bridge/src/google_chat_bridge/chat_client.py` | Existing GChat API client (auth, `get_messages_after`, `ChatMessage` model) |
| `mcp-servers/google-chat-bridge/src/google_chat_bridge/state.py` | Reference for atomic write pattern (`tmp → rename`) and ReadState tracking |
| `.claude/hooks/unified_stop_gate/communicator_checker.py` | The checker to be replaced/extended in Epic 4 (F4.2) |
| `.claude/settings.json` | Current hook configuration — the base for new hook additions |

---

*End of Solution Design Document — PRD-GCHAT-HOOKS-001*
