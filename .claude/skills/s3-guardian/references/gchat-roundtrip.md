---
title: "GChat AskUserQuestion Round-Trip"
status: active
type: reference
grade: authoritative
---

## GChat AskUserQuestion Round-Trip (S3 Sessions)

When S3 calls `AskUserQuestion` and the `gchat-ask-user-forward.py` hook blocks it, the block reason contains `[gchat-ask-user-forward]` plus thread metadata. S3 must spawn a **blocking Haiku Task agent** to poll for the user's GChat reply and return it to S3's context.

### Detection

The block reason from the hook contains:
- `thread_name` (e.g., `spaces/AAQAOmyvAfE/threads/xyz`) — identifies the GChat thread
- `marker_path` (e.g., `.claude/state/gchat-forwarded-ask/system3-20260222-a1b2c3d4.json`) — tracks resolution status

Parse these from the block reason string.

### Spawn Blocking Reply Watcher

Uses `gchat-poll-replies.py` which handles OAuth2 credentials directly and uses
the raw Google Chat API (not ChatMessage objects) for proper `sender.type` and
`thread.name` matching.

```python
# Extract marker_path and question_id from the block reason
# marker_path = ".claude/state/gchat-forwarded-ask/xxx.json"  (from "Marker file   : ...")
# question_id = the marker filename without .json extension
# project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

result = Task(
    subagent_type="general-purpose",
    model="haiku",
    run_in_background=False,  # BLOCKING — S3 waits for the agent to return
    description="Watch for GChat reply",
    prompt=f"""
You are a GChat reply watcher. Your ONLY job: poll for a human reply
to a forwarded AskUserQuestion and return it.

Question ID: {question_id}
Marker file: {marker_path}
Project dir: {project_dir}

## Polling Loop

Every 10 seconds, run this Bash command which uses the existing
gchat-poll-replies.py script (handles OAuth2 creds and thread matching):

```bash
python3 {project_dir}/.claude/scripts/gchat-poll-replies.py \
    --marker-dir {project_dir}/.claude/state/gchat-forwarded-ask
```

The script outputs JSON:
```json
{{"replies": [{{"question_id": "...", "reply_text": "...", "sender_name": "..."}}], "pending_count": 0}}
```

## Rules
- Run the command, parse JSON output
- If `replies` array contains an entry matching question_id "{question_id}":
  -> return EXACTLY: "GCHAT_RESPONSE: <the reply_text>"
- If `replies` is empty or no match -> sleep 10s -> try again
- Max 180 attempts (30 minutes). If timeout:
  -> update marker (set status="timeout" in the JSON file)
  -> return EXACTLY: "GCHAT_TIMEOUT: No response in 30 minutes"
- Do NOT do anything else. No exploration, no investigation, no extra work.
- Return as soon as you have a result. EXIT IMMEDIATELY after returning.
"""
)
```

### Handling the Result

After the Task agent returns:
- `GCHAT_RESPONSE: <text>` — Parse the reply text and proceed as if the user answered the question with that text. Use the reply to inform your next action.
- `GCHAT_TIMEOUT: ...` — The user didn't reply within 30 minutes. Log to Hindsight and either retry the question or proceed with best judgment.

### Why Blocking (Not Background)

- **Blocking** Task agents return their result to S3's context when they complete
- S3's turn stays alive until the reply arrives — no wake-up mechanism needed
- Background agents write to files, but S3 has no way to detect file changes
- The stop gate also blocks on pending GChat markers as a safety net
