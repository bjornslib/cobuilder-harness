# Epic 1 Findings: Native Agent Teams Compatibility Test

**Date**: 2026-02-06
**PRD**: PRD-NATIVE-TEAMS-001 v1.1

---

## 1. Agent ID Format

**Format**: `{name}@{team-name}`

| Role | Example ID |
|------|-----------|
| Team Lead | `team-lead@epic1-test` |
| Teammate | `test-researcher@epic1-test` |

**Key**: The `name` part is user-defined at spawn time. The `@{team-name}` suffix is auto-appended.

### Team Config Structure (`~/.claude/teams/{team-name}/config.json`)

```json
{
  "name": "epic1-test",
  "description": "...",
  "createdAt": 1770364613743,
  "leadAgentId": "team-lead@epic1-test",
  "leadSessionId": "e99adc7b-...",  // Lead's Claude Code session UUID
  "members": [
    {
      "agentId": "team-lead@epic1-test",
      "name": "team-lead",            // Used for messaging (SendMessage recipient)
      "agentType": "team-lead",
      "model": "claude-opus-4-6",
      "joinedAt": 1770364613743,
      "tmuxPaneId": "",
      "cwd": "$CLAUDE_PROJECT_DIR
      "subscriptions": []
    },
    {
      "agentId": "test-researcher@epic1-test",
      "name": "test-researcher",
      "agentType": "Explore",          // Maps to subagent_type
      "model": "haiku",
      "prompt": "...",                 // The full spawn prompt (wisdom injection!)
      "color": "blue",                // Display color
      "planModeRequired": false,       // Can be set true for plan approval
      "joinedAt": 1770364626194,
      "tmuxPaneId": "in-process",
      "cwd": "$CLAUDE_PROJECT_DIR
      "subscriptions": [],
      "backendType": "in-process"      // Display mode
    }
  ]
}
```

---

## 2. Task System Confirmation

**Native team tasks ARE the same TaskList system.**

- Location: `~/.claude/tasks/{team-name}/`
- Same JSON schema as `TaskCreate`/`TaskUpdate`
- When a teammate is spawned, an `_internal` task is auto-created for it
- File locking via `.lock` file for race-free claiming

### Task File Example (`~/.claude/tasks/epic1-test/1.json`)

```json
{
  "id": "1",
  "subject": "test-researcher",
  "description": "...",
  "status": "in_progress",
  "blocks": [],
  "blockedBy": [],
  "metadata": {
    "_internal": true   // Marks as system-created teammate task
  }
}
```

---

## 3. Hook Compatibility Analysis

### Hooks That Check Session ID Prefixes

| File | Check | Impact |
|------|-------|--------|
| `unified_stop_gate/config.py:33` | `session_id.startswith("orch-")` | **NEEDS UPDATE**: Native teammate IDs use `name@team` format, not `orch-*` |
| `unified_stop_gate/config.py:38` | `session_id.startswith("system3-")` | **OK**: System 3 stays outside teams, keeps its prefix |
| `unified_stop_gate/checkers.py:164` | `owner.startswith('orch-')` | **NEEDS UPDATE**: Promise owners may use new format |
| `unified_stop_gate/checkers.py:296` | `first_orch.replace('orch-', 'PRD-')` | **NEEDS UPDATE**: Hardcoded prefix transformation |
| `unified_stop_gate/checkers.py:570` | Orchestrator session check | **NEEDS UPDATE** |
| `decision_guidance/classifier.py:66` | `session_id.startswith("orch-")` | **NEEDS UPDATE** |
| `context-reinjector-hook.py:76` | `session_id.startswith("orch-")` | **NEEDS UPDATE** |
| `message-bus-signal-check.py:23` | Uses `CLAUDE_SESSION_ID` | **OK** if env var is set |

### Hooks That Don't Check Prefixes (No Changes Needed)

| File | Reason |
|------|--------|
| `session-start-orchestrator-detector.py` | Uses output style detection, not session ID |
| `user-prompt-orchestrator-reminder.py` | Checks flag file, not session ID |
| `load-mcp-skills.sh` | No session ID logic |
| `unified-stop-gate.sh` | Delegates to Python modules |

### Resolution: Skip Hooks for Teammates Entirely

**Key insight**: Teammates are ephemeral workers managed by the native team system. They don't need our custom hooks (stop gate, message bus, orchestrator detection). The lead (orchestrator) manages their lifecycle via native shutdown protocol.

**Why this works**:
1. **System 3** → Spawned via `ccsystem3`, has `CLAUDE_SESSION_ID=system3-*`. All hooks work.
2. **Orchestrator/Team Lead** → Spawned via tmux by System 3, has `CLAUDE_SESSION_ID=orch-*`. All hooks work.
3. **Workers/Teammates** → Spawned natively by team lead. **No custom hooks needed**. Native team system handles lifecycle.

**For in-process teammates**: They share the lead's process, so hooks fire for the lead (correct behavior).
**For split-pane teammates**: They're separate processes but don't need our hooks — add early-exit guard if needed.

**No hook files need to be updated for native team adoption.** The identity chain is preserved because System 3 controls tmux environment for the orchestrator/lead.

### Possible Future Enhancement

If split-pane teammates start triggering our hooks (separate processes), add a single guard function:

```python
def is_native_teammate():
    """Check if we're a native teammate (not lead) by checking team config."""
    import glob, json, os
    for config_path in glob.glob(os.path.expanduser("~/.claude/teams/*/config.json")):
        config = json.load(open(config_path))
        # If we're a member but NOT the lead, we're a teammate
        lead_session = config.get("leadSessionId")
        # ... compare with our session
    return False
```

This would allow hooks to exit early for teammates without modifying existing logic.

---

## 4. Feature Verification Summary

| Feature | Status | Notes |
|---------|--------|-------|
| Team creation (`Teammate.spawnTeam`) | **WORKS** | Creates config.json + task directory |
| Teammate spawning | **WORKS** | Full Claude Code instance with own context |
| Agent ID format | **DOCUMENTED** | `{name}@{team-name}` |
| Task system same as TaskList | **CONFIRMED** | Same `~/.claude/tasks/` path, same JSON schema |
| Shutdown protocol | **WORKS** | `SendMessage(type="shutdown_request")` |
| Cleanup | **WORKS** | `Teammate(operation="cleanup")` removes all |
| iTerm2 it2 CLI | **INSTALLED** | `~/.iterm2/it2*`, needs Python API enabled in iTerm2 settings |
| Hook compatibility | **NO CHANGES NEEDED** | Teammates skip hooks; lead inherits orch-* prefix from tmux |

---

---

# Epic 3 Findings: Cross-Layer Worker Coordination PoC

**Date**: 2026-02-06
**Team**: `epic3-poc` (System 3 as team lead, 2 Haiku workers)

---

## 6. Native Inbox Messaging Architecture

### Discovery: File-Based Inbox System

```
~/.claude/teams/{team-name}/
├── config.json              # Team config (members, metadata)
└── inboxes/                 # File-based messaging system
    ├── {agent-name}.json    # Messages TO this agent (JSON array)
    └── ...
```

Inboxes are created **on-demand** — only when a message is sent TO an agent.

### Message Schema

```json
{
  "from": "sender-name",       // Agent name of sender
  "text": "message content",   // Full message text
  "summary": "short preview",  // Summary for UI display
  "timestamp": "ISO-8601",     // When sent
  "color": "blue",             // Sender's color from config
  "read": false                // Delivery/read tracking
}
```

### Auto-Generated Messages

The system automatically sends idle notifications to the team lead:

```json
{
  "from": "styles-researcher",
  "text": "{\"type\":\"idle_notification\",\"from\":\"styles-researcher\",\"timestamp\":\"...\",\"idleReason\":\"available\"}",
  "timestamp": "...",
  "color": "blue",
  "read": true
}
```

---

## 7. Cross-Layer Coordination Results

### Test Setup

| Agent | Type | Model | Task |
|-------|------|-------|------|
| team-lead (System 3) | team-lead | Opus | Coordinate, monitor |
| styles-researcher | general-purpose | Haiku | Research output styles (#10) |
| skills-researcher | general-purpose | Haiku | Research skills architecture (#11) |
| — | — | — | Synthesis (#12, blocked by #10 + #11) |

### Timeline

| Time | Event |
|------|-------|
| 09:39 | Team `epic3-poc` created, workers spawned |
| 09:40 | Both workers claimed tasks. `styles-researcher` completed #10 |
| 09:40 | `styles-researcher` → peer message to `skills-researcher` (research findings) |
| 09:41 | `styles-researcher` went idle (notification to team-lead) |
| 09:45 | Team lead sent status check to `skills-researcher` via SendMessage |
| 09:46 | `skills-researcher` completed #11, sent findings BACK to `styles-researcher` |
| 09:46 | Task #12 auto-unblocked. `styles-researcher` woken up, claimed & completed #12 |
| 09:46-47 | Both workers sent completion reports to team-lead, went idle |
| 09:47 | Shutdown requests sent. Both confirmed. Team cleaned up. |

### Capability Verification

| Capability | Status | Evidence |
|-----------|--------|----------|
| **Peer-to-peer messaging** | **WORKS** | styles→skills AND skills→styles via inbox files |
| **Idle agent wake-up via peer message** | **WORKS** | `styles-researcher` woken when `skills-researcher` sent message |
| **Task dependency auto-unblock** | **WORKS** | #12 became available when #11 completed |
| **Autonomous task claiming** | **WORKS** | Workers picked up newly-available #12 without instruction |
| **Team lead inbox delivery** | **WORKS** | All notifications + completion messages auto-delivered |
| **Lead → teammate messaging** | **WORKS** | Status check delivered to skills-researcher inbox |
| **Read tracking** | **WORKS** | `read: true/false` field on messages |
| **Graceful shutdown protocol** | **WORKS** | SendMessage(type="shutdown_request") → confirmation → cleanup |

### Research Quality (Haiku Workers)

Both Haiku workers produced high-quality research summaries:

- **styles-researcher**: Correctly identified 2 output styles with line counts, understood ADR-001 reliability guarantees (100% vs ~85%), captured progressive disclosure pattern
- **skills-researcher**: Cataloged all 25 skills across 8 categories, documented 3-level progressive disclosure, understood SKILL.md anatomy
- **Synthesis (collaborative)**: Both workers contributed. Identified the "two-layer progressive disclosure architecture" and "two-stage boot sequence" (output style auto-loads → first action invokes companion skill)

---

## 8. Implications for Message Bus Architecture

| Communication Path | Current | With Native Teams | Recommendation |
|-------------------|---------|-------------------|----------------|
| System 3 ↔ Orchestrator | SQLite message bus | **Keep** (System 3 is outside teams) | No change |
| Orchestrator ↔ Workers | Task subagent return values | **Replace** with native inbox messaging | Use native |
| Worker ↔ Worker | IMPOSSIBLE (Task subagents isolated) | **WORKS** via peer messaging | New capability |
| Lead notifications | Only on completion | Automatic idle + completion | Native wins |

**Key insight**: Native team messaging provides worker-to-worker coordination **for free** — something that was impossible with Task subagents. The inbox system is simpler than our SQLite message bus and has built-in read tracking.

**Message bus still needed**: For System 3 ↔ Orchestrator communication, since System 3 operates OUTSIDE native teams (autonomous steering with completion promises, Hindsight, stop gate).

---

## 9. Updated Feature Verification (Epic 1 + Epic 3)

| Feature | Status | Notes |
|---------|--------|-------|
| Team creation (`Teammate.spawnTeam`) | **WORKS** | Creates config.json + task directory + inboxes/ |
| Teammate spawning | **WORKS** | Full Claude Code instance with own context |
| Agent ID format | **DOCUMENTED** | `{name}@{team-name}` |
| Task system same as TaskList | **CONFIRMED** | Same `~/.claude/tasks/` path, same JSON schema |
| Peer messaging (SendMessage) | **WORKS** | Bidirectional, file-based inbox system |
| Idle agent wake-up | **WORKS** | Peer message wakes idle teammate |
| Task dependency auto-unblock | **WORKS** | Blocked tasks auto-available when deps complete |
| Autonomous task claiming | **WORKS** | Workers claim newly-available tasks without instruction |
| Team lead inbox | **WORKS** | Auto idle notifications + explicit messages |
| Read tracking | **WORKS** | `read: true/false` on inbox messages |
| Shutdown protocol | **WORKS** | `SendMessage(type="shutdown_request")` |
| Cleanup | **WORKS** | `Teammate(operation="cleanup")` removes all |
| Hook compatibility | **NO CHANGES NEEDED** | Teammates skip hooks; lead inherits orch-* prefix |

---

## 10. Next Steps

1. **Epic 4**: Test delegate mode tool restrictions (verify Task tool available, Edit/Write removed)
2. **Epic 5**: Test plan approval workflow (planModeRequired=true)
3. **Epic 6**: Integrate validation-test-agent with native team pattern
4. **Epic 7**: Full integration test — System 3 (outside) → Orchestrator as team lead → Workers as teammates
