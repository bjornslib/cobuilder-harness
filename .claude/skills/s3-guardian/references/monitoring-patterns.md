---
title: "Monitoring Patterns"
status: active
type: skill
last_verified: 2026-03-04
grade: authoritative
---

# Monitoring Patterns Reference

Commands, signal detection, intervention protocols, and red flags for continuous monitoring of S3 operators. **Headless mode (signal files) is the default.** Legacy tmux monitoring patterns are preserved at the end of this document for debugging use only.

---

## 1. Signal File Monitoring (Default)

In headless mode, orchestrators communicate via signal files in `.claude/attractor/signals/`. The guardian polls these files instead of capturing terminal output.

### Basic Signal Checks

```bash
SIGNAL_DIR=".claude/attractor/signals"

# List all recent signals (sorted by time)
ls -lt "${SIGNAL_DIR}"/*.json 2>/dev/null | head -20

# Read the most recent signal
LATEST=$(ls -t "${SIGNAL_DIR}"/*.json 2>/dev/null | head -1)
[ -n "$LATEST" ] && python3 -c "import json; print(json.dumps(json.load(open('$LATEST')), indent=2))"

# Check for signals from a specific node
ls -lt "${SIGNAL_DIR}"/*-${NODE_ID}-*.json 2>/dev/null
```

### Targeted Signal Detection

```bash
SIGNAL_DIR=".claude/attractor/signals"

# Check for completion signals
ls "${SIGNAL_DIR}"/*.json 2>/dev/null | xargs grep -l '"signal_type": "NODE_COMPLETE"' 2>/dev/null

# Check for error/stuck signals
ls "${SIGNAL_DIR}"/*.json 2>/dev/null | xargs grep -l '"signal_type": "ORCHESTRATOR_STUCK\|ORCHESTRATOR_CRASHED"' 2>/dev/null

# Check for review-needed signals
ls "${SIGNAL_DIR}"/*.json 2>/dev/null | xargs grep -l '"signal_type": "NEEDS_REVIEW"' 2>/dev/null

# Check for input-needed signals (equivalent of AskUserQuestion in headless)
ls "${SIGNAL_DIR}"/*.json 2>/dev/null | xargs grep -l '"signal_type": "NEEDS_INPUT"' 2>/dev/null

# Parse signal type from most recent signal for a node
LATEST_SIGNAL=$(ls -t "${SIGNAL_DIR}"/*-${NODE_ID}-*.json 2>/dev/null | head -1)
if [ -n "$LATEST_SIGNAL" ]; then
    python3 -c "import json; d=json.load(open('$LATEST_SIGNAL')); print(d.get('signal_type',''), d.get('payload',{}).get('summary',''))"
fi
```

### Process Health Check

```bash
# Check if orchestrator subprocess is still running (headless mode)
# spawn_orchestrator.py writes PID to state file
STATE_FILE=".claude/attractor/runner-state-${NODE_ID}.json"
if [ -f "$STATE_FILE" ]; then
    PID=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('pid',''))")
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "ALIVE (PID $PID)"
    else
        echo "DEAD (PID $PID no longer running)"
    fi
else
    echo "NO STATE FILE — process may not have started"
fi

# List all active orchestrator processes
ps aux | grep "claude.*--output-format json" | grep -v grep
```

---

## 2. Key Signals and Their Meaning

### Positive Signals (Operator is Making Progress)

| Signal Type | Meaning | Guardian Action |
|------------|---------|-----------------|
| `NODE_COMPLETE` | Node work finished, ready for validation | Run validation gate |
| `NEEDS_REVIEW` | Work ready for guardian review | Inspect evidence, validate |
| (process running, no signals) | Orchestrator is actively working | Continue monitoring |
| `git commit` in evidence | Code has been committed | Note for later validation |

### Negative Signals (Potential Problems)

| Signal Type | Meaning | Guardian Action |
|------------|---------|-----------------|
| `NEEDS_INPUT` | Orchestrator blocked, needs guidance | Respond via `respond_to_runner.py` |
| `ORCHESTRATOR_STUCK` | No progress for stuck-threshold seconds | Send guidance or re-launch |
| `ORCHESTRATOR_CRASHED` | Process died unexpectedly | Re-launch with same prompt |
| `VIOLATION` | Protocol violation detected | Assess severity, send corrective guidance |
| (process dead, no completion signal) | Silent crash | Re-launch orchestrator |
| (no signals for 10+ minutes, process alive) | Possible hang | Check process, consider timeout |

### Completion Signals (Operator Claims Done)

| Signal Type | Meaning | Guardian Action |
|------------|---------|-----------------|
| `NODE_COMPLETE` with evidence | Node implementation finished | Begin validation |
| `NEEDS_REVIEW` with commit hash | Work committed, requesting review | Run acceptance tests |
| Process exit code 0 + JSON stdout | Clean completion | Parse results, validate |
| Process exit code != 0 | Error exit | Check stderr, retry or escalate |

---

## 3. Intervention Protocol (Headless Mode)

In headless mode, there is no interactive session to send keystrokes to. Instead, the guardian communicates with orchestrators through the signal protocol.

### Responding to NEEDS_INPUT

```bash
# Runner signals that orchestrator needs guidance
# Guardian responds via the signal protocol
python3 .claude/scripts/attractor/respond_to_runner.py \
    --node "${NODE_ID}" \
    INPUT_RESPONSE \
    --response "Focus on the PRD scope. Complete the current feature before starting new work." \
    --message "Guardian guidance: stay on scope"
```

### Sending Corrective Guidance

```bash
# Send guidance without changing node state
python3 .claude/scripts/attractor/respond_to_runner.py \
    --node "${NODE_ID}" \
    GUIDANCE \
    --feedback "Scope creep detected. Return to ${CORRECT_SCOPE}." \
    --message "Guardian corrective guidance"
```

### Killing and Re-launching

```bash
# If orchestrator is stuck beyond recovery, kill and re-launch
python3 .claude/scripts/attractor/respond_to_runner.py \
    --node "${NODE_ID}" \
    KILL_ORCHESTRATOR \
    --reason "Stuck for ${DURATION}s with no progress"

# Re-launch with updated prompt (spawn_orchestrator.py handles cleanup)
python3 .claude/scripts/attractor/spawn_orchestrator.py \
    --node "${NODE_ID}" \
    --prd "${PRD_ID}" \
    --repo-root "${IMPL_REPO}" \
    --mode headless \
    --prompt "RETRY: Previous attempt failed. ${CORRECTIVE_GUIDANCE}"
```

### Common Intervention Patterns

| Situation | Headless Action |
|-----------|----------------|
| Orchestrator needs guidance | `respond_to_runner.py GUIDANCE --feedback "..."` |
| Orchestrator asks a question | `respond_to_runner.py INPUT_RESPONSE --response "..."` |
| Orchestrator is stuck | `respond_to_runner.py KILL_ORCHESTRATOR` then re-launch |
| Orchestrator crashed | Re-launch via `spawn_orchestrator.py --mode headless` |
| Scope creep detected | `respond_to_runner.py GUIDANCE --feedback "Return to scope"` |
| Work passes validation | `respond_to_runner.py VALIDATION_PASSED` |
| Work fails validation | `respond_to_runner.py VALIDATION_FAILED --feedback "..."` |

**Note**: In headless mode, there are no AskUserQuestion dialogs or permission prompts. Orchestrators run with `--permission-mode bypassPermissions`, so all tool usage is auto-approved.

---

## 4. Red Flags to Watch For

### Scope Creep Indicators

In headless mode, scope creep is detected by analyzing signal payloads and git diffs rather than terminal output:

```bash
# Check git diff for files outside expected scope
cd "${IMPL_REPO}"
git diff --name-only HEAD~5 | grep -vE "${EXPECTED_FILE_PATTERN}"

# Check signal payloads for scope warnings
ls "${SIGNAL_DIR}"/*-${NODE_ID}-*.json 2>/dev/null | \
    xargs grep -l "scope\|outside\|unrelated" 2>/dev/null
```

**When to intervene**: If git diff shows modifications to files outside the node's `file_path`/`folder_path` scope, send corrective guidance via signal protocol.

### Repeated Error Patterns

Track error occurrences across monitoring cycles. Maintain a mental count:

| Error Count | Action |
|-------------|--------|
| 1 | Note it, continue monitoring |
| 2 | Check if same error -- may be a retry in progress |
| 3 | Assess: is the operator stuck in a loop? |
| 4+ | Kill and re-launch with corrective guidance |

### Time-Based Red Flags

| Duration | Expected Progress | Red Flag If |
|----------|------------------|-------------|
| 0-15 min | PRD reading, task parsing | Still configuring environment |
| 15-45 min | First workers spawned, implementation starting | No workers spawned yet |
| 45-90 min | Multiple features implemented, tests running | Only 1 feature done |
| 90-120 min | Most features complete, validation beginning | Less than 50% done |
| 120+ min | Should be wrapping up or very close | Major features still pending |

### TODO/FIXME Accumulation

```bash
# Count TODO markers in the implementation repo
git -C "${IMPL_REPO}" grep -c "TODO\|FIXME\|HACK\|XXX" -- "*.py" "*.ts" "*.js" 2>/dev/null
```

A growing TODO count suggests the operator is deferring work rather than completing it. Each TODO reduces the maximum achievable score for the relevant feature.

---

## 5. When to Intervene vs When to Wait

### Always Intervene

- `NEEDS_INPUT` signal with no response for 5+ minutes
- Process has died (no PID) but work is incomplete
- Operator is clearly working on wrong PRD or wrong repo (from git diff)
- `ORCHESTRATOR_STUCK` signal received

### Usually Wait

- Operator process is alive and recent signal shows progress
- No signals for a few minutes (operator may be working)
- `NEEDS_REVIEW` signal just arrived (give time to prepare evidence)

### Never Intervene

- Operator's coding style differs from preference (implementation detail)
- Operator chose a different technical approach than expected (as long as it meets PRD)
- Operator process is alive and within expected time bounds
- Recent signal shows normal progress

---

## 6. Context and Resource Monitoring

Claude Code sessions have finite context windows. In headless mode, context exhaustion manifests as process completion with truncated output.

### Detecting Context Issues

```bash
# Check process exit status and output size
STATE_FILE=".claude/attractor/runner-state-${NODE_ID}.json"
if [ -f "$STATE_FILE" ]; then
    python3 -c "
import json
state = json.load(open('$STATE_FILE'))
if state.get('exit_code') is not None:
    print(f'Exit code: {state[\"exit_code\"]}')
    output_len = len(state.get('stdout', ''))
    print(f'Output length: {output_len} chars')
    if output_len < 100 and state['exit_code'] != 0:
        print('WARNING: Short output with error exit — possible context exhaustion')
"
fi
```

### Post-Exhaustion Recovery

If a headless orchestrator exits due to context exhaustion:
1. Check what work was completed (git log, signal files)
2. Re-launch with a narrower scope prompt
3. Include a summary of what was already done to avoid rework

---

## 7. Multi-Session Monitoring

When monitoring multiple orchestrators in parallel:

### Signal-Based Round-Robin

```bash
SIGNAL_DIR=".claude/attractor/signals"

# Check all active nodes in one pass
for NODE_ID in node1 node2 node3; do
    echo "=== ${NODE_ID} ==="
    LATEST=$(ls -t "${SIGNAL_DIR}"/*-${NODE_ID}-*.json 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        python3 -c "import json; d=json.load(open('$LATEST')); print(f'{d[\"signal_type\"]}: {d.get(\"payload\",{}).get(\"summary\",\"no summary\")}')"
    else
        # Check if process is running
        STATE_FILE=".claude/attractor/runner-state-${NODE_ID}.json"
        if [ -f "$STATE_FILE" ]; then
            PID=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('pid',''))")
            kill -0 "$PID" 2>/dev/null && echo "Running (no signals yet)" || echo "DEAD (no signals)"
        else
            echo "Not started"
        fi
    fi
done
```

### Priority-Based Monitoring

Check nodes in priority order:
1. Nodes with `NEEDS_INPUT` or `ORCHESTRATOR_STUCK` signals -- check every cycle
2. Nodes in active implementation (process alive, no signals) -- check every 2 cycles
3. Nodes awaiting validation -- check every 4 cycles
4. Nodes not yet started -- check every 6 cycles

### Cross-Session Awareness

Watch for:
- Two orchestrators modifying the same files (merge conflict risk)
- One orchestrator's output referencing another's work (scope boundary violation)
- Shared resource contention (database, API rate limits)

### Blocking Pause Agent

For longer monitoring intervals (120s+), consider using a blocking Task agent instead of bash sleep loops. This keeps S3's context clean and gives the user an interruptible status line. See [SKILL.md Phase 3: Pause-and-Check Pattern](../SKILL.md#pause-and-check-pattern-blocking-task-agent) for the full pattern.

---

## Guardian Phase 3: Monitoring (Full Reference)

> Complete monitoring procedure including cadence, pause-and-check pattern, intervention triggers, and signal handling.

### Monitoring Cadence

| Phase | Interval | Rationale |
|-------|----------|-----------|
| Active implementation | 30s | Catch errors early, detect stuck signals |
| Investigation/planning | 60s | Orchestrator is reading/thinking, less likely to need help |
| Idle / waiting for workers | 120s | Nothing to intervene on |

### Core Monitoring Loop

```bash
SIGNAL_DIR=".claude/attractor/signals"

# Check for actionable signals (per orchestrator node)
for NODE_ID in ${ACTIVE_NODES}; do
    LATEST=$(ls -t "${SIGNAL_DIR}"/*-${NODE_ID}-*.json 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        SIGNAL_TYPE=$(python3 -c "import json; print(json.load(open('$LATEST')).get('signal_type',''))")
        case "$SIGNAL_TYPE" in
            NEEDS_INPUT|ORCHESTRATOR_STUCK)
                echo "ACTION REQUIRED: ${NODE_ID} — ${SIGNAL_TYPE}"
                ;;
            NODE_COMPLETE|NEEDS_REVIEW)
                echo "READY FOR VALIDATION: ${NODE_ID}"
                ;;
            *)
                echo "INFO: ${NODE_ID} — ${SIGNAL_TYPE}"
                ;;
        esac
    fi
done
```

### Pause-and-Check Pattern (Blocking Task Agent)

When the guardian is satisfied that an orchestrator is progressing well and doesn't need
frequent intervention, use a blocking Task agent as a clean pause timer instead of
bash sleep loops:

```python
# Pause for N seconds while orchestrator works
Task(
    subagent_type="general-purpose",
    model="haiku",
    description=f"Wait {wait_seconds}s for orchestrator to work",
    prompt=f"Run: sleep {wait_seconds}. Then return 'PAUSE_COMPLETE'.",
    run_in_background=False,  # BLOCKING -- guardian waits in-context
)
# Guardian resumes here with full context intact
```

**Why this is better than `Bash("sleep 100")`:**
- Status line shows "Waiting for task (esc to give additional instructions)" -- user knows what's happening
- User can press Esc to interrupt the pause and give S3 new instructions
- No shell output cluttering the conversation context
- S3 resumes with full context when the pause completes

**When to use:**
- After initial spawn verification (orchestrator is running)
- When monitoring cadence is 120s+ (idle/waiting for workers)
- Between monitoring check-ins when no intervention signals were found

**When NOT to use:**
- During active intervention (errors detected, guidance needed)
- When NEEDS_INPUT signals are likely (use 30s signal polling instead)
- For the first 5 minutes after spawn (use active monitoring to catch boot failures)

**Recommended cadence:**

| Phase | Pause Duration | Rationale |
|-------|---------------|-----------|
| Post-spawn (first 5 min) | Don't use -- active poll at 30s | Catch boot failures early |
| Active implementation | 60-90s | Check frequently but not constantly |
| Investigation/planning | 120-180s | Orchestrator is thinking, less likely to need help |
| Worker execution (steady state) | 180-300s | Workers are running, minimal intervention needed |

**Combined pattern -- pause then check:**
```python
while not orchestrator_complete:
    # Pause
    Task(
        subagent_type="general-purpose", model="haiku",
        description=f"Wait {pause_seconds}s for {epic_name}",
        prompt=f"Sleep {pause_seconds} seconds, then return PAUSE_COMPLETE.",
    )

    # Check signals
    output = Bash(f'ls -t .claude/attractor/signals/*-{node_id}-*.json 2>/dev/null | head -1 | xargs cat 2>/dev/null')
    if "NODE_COMPLETE" in output or "ORCHESTRATOR_STUCK" in output:
        break
    # Adjust pause_seconds based on signals found
```

### Intervention Triggers

| Signal | Action |
|--------|--------|
| `NEEDS_INPUT` signal | Respond via `respond_to_runner.py INPUT_RESPONSE` |
| `ORCHESTRATOR_STUCK` signal | Send guidance or kill + re-launch |
| `ORCHESTRATOR_CRASHED` signal | Re-launch orchestrator |
| No signals for 10+ minutes (process alive) | Check process health, consider timeout |
| Scope creep (git diff outside scope) | Send corrective guidance via signal protocol |
| `VIOLATION` signal | Assess severity, send guidance |
| Time exceeded (2+ hours) | Assess progress, consider intervention |

### Sending Guidance (Headless Mode)

The guardian communicates with orchestrators via the signal protocol:

```bash
# Send corrective instruction
python3 .claude/scripts/attractor/respond_to_runner.py \
    --node "${NODE_ID}" \
    GUIDANCE \
    --feedback "Focus on ${CORRECT_SCOPE}. Do not modify ${OUT_OF_SCOPE_FILES}."

# Respond to orchestrator question
python3 .claude/scripts/attractor/respond_to_runner.py \
    --node "${NODE_ID}" \
    INPUT_RESPONSE \
    --response "Use approach X. The constraint is Y."
```

---

## Legacy: tmux Monitoring (Debugging Only)

> The patterns below apply only when running orchestrators in legacy tmux mode for interactive debugging. **For production pipelines, use signal file monitoring (sections 1-7 above).**

### tmux Capture Commands

```bash
# Capture visible pane content (what you would see on screen)
tmux capture-pane -t "s3-{initiative}" -p

# Capture with scrollback history (last 100 lines)
tmux capture-pane -t "s3-{initiative}" -p -S -100

# Capture with extended scrollback (last 500 lines -- for deep investigation)
tmux capture-pane -t "s3-{initiative}" -p -S -500

# Capture only the last N lines (tail equivalent)
tmux capture-pane -t "s3-{initiative}" -p -S -100 | tail -20
```

### tmux Targeted Signal Detection

```bash
# Check for task completion signals
tmux capture-pane -t "s3-{initiative}" -p -S -100 | grep -iE "complete|done|finished|merged"

# Check for error signals
tmux capture-pane -t "s3-{initiative}" -p -S -100 | grep -iE "error|failed|exception|traceback"

# Check for blocking signals (AskUserQuestion, permission dialogs)
tmux capture-pane -t "s3-{initiative}" -p -S -50 | grep -iE "AskUser|permission|approve|reject|y/n|yes/no"

# Check for context exhaustion signals
tmux capture-pane -t "s3-{initiative}" -p -S -50 | grep -iE "compact|context|token|limit"
```

### tmux Session Health Check

```bash
# Verify session exists
tmux has-session -t "s3-{initiative}" 2>/dev/null && echo "ALIVE" || echo "DEAD"

# List all system3 sessions
tmux list-sessions 2>/dev/null | grep "^s3-"
```

### tmux AskUserQuestion Intervention

AskUserQuestion dialogs are the most common blocking issue in tmux mode. They appear when:
- A worker finishes its task and asks for next steps
- The stop gate judge asks if the session should continue
- A tool needs permission approval
- An orchestrator asks for strategic direction

```bash
# Step 1: Identify what is being asked
tmux capture-pane -t "s3-{initiative}" -p -S -20

# Step 2: Determine appropriate response
# For permission dialogs (most common):
tmux send-keys -t "s3-{initiative}" Down    # Navigate to approve/yes
tmux send-keys -t "s3-{initiative}" Enter   # Confirm

# For "continue working?" dialogs:
tmux send-keys -t "s3-{initiative}" Enter   # Accept default (usually "yes")

# For strategic questions that need real input:
tmux send-keys -t "s3-{initiative}" "Focus on the PRD scope. Complete the current epic before starting new work."
sleep 2
tmux send-keys -t "s3-{initiative}" Enter
```

### tmux Common Dialog Patterns

| Dialog Pattern | Response |
|---------------|----------|
| `[Y/n]` | Enter (accept default yes) |
| Permission to use tool X | Down, Enter (approve) |
| "Should I continue?" | Enter (yes) |
| "Which option?" with choices | Read choices, select most aligned with PRD scope |
| "Should I stop?" | Depends on progress -- assess first |

### tmux Important Caveats

- `tmux send-keys` sends keystrokes but CANNOT interact with Claude Code's built-in permission dialogs at the SDK level. Some dialogs require killing the session.
- After sending keys, wait 2-3 seconds and re-check the pane to verify the dialog was resolved.
- If the same dialog reappears after intervention, the session may be in a loop. Consider killing and restarting.

### tmux Core Monitoring Loop

```bash
# Capture recent output (per orchestrator session)
tmux capture-pane -t "orch-{epic}" -p -S -100

# Check for key signals
tmux capture-pane -t "orch-{epic}" -p -S -100 | grep -iE "error|stuck|complete|failed|AskUser|permission"

# Monitor multiple orchestrators in parallel
for SESSION in orch-epic1 orch-epic2 orch-epic3; do
    echo "=== $SESSION ===" && tmux capture-pane -t "$SESSION" -p -S -20 2>/dev/null || echo "(not running)"
done
```

### tmux Sending Guidance

```bash
# Send corrective instruction (Pattern 1: separate Enter)
tmux send-keys -t "orch-{epic}" "GUARDIAN: Focus on {correct scope}. Do not modify {out-of-scope files}."
tmux send-keys -t "orch-{epic}" Enter

# Send unblocking guidance
tmux send-keys -t "orch-{epic}" "GUARDIAN: The issue is {root cause}. Fix: {specific fix}."
tmux send-keys -t "orch-{epic}" Enter
```

---

**Reference Version**: 0.2.0
**Parent Skill**: s3-guardian
