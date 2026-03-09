---
title: "SD-HARNESS-UPGRADE-001 Epic 0: Pipeline Progress Monitor"
status: complete
type: solution-design
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001 Epic 0: Pipeline Progress Monitor

## 1. Problem Statement

System 3 currently has no automated way to know when a pipeline run needs attention. After launching a guardian/runner, System 3 must manually check signal files, read DOT graph state, or poll tmux sessions. This is error-prone and creates gaps where failures go undetected for extended periods.

## 2. Design

### 2.1 Haiku 4.5 Monitor Sub-Agent

System 3 spawns a lightweight Haiku 4.5 sub-agent after launching a pipeline:

```python
Task(
    subagent_type="monitor",
    model="haiku",
    run_in_background=True,
    prompt=f"""Monitor pipeline progress for {pipeline_id}.

    Signal directory: {signal_dir}
    DOT file: {dot_file}
    Poll interval: 30 seconds
    Stall threshold: 5 minutes

    Check signal files for new completions or failures.
    Check DOT file mtime for state transitions.
    COMPLETE immediately with a status report when:
    - A node fails (report which node and error)
    - No state change for >5 minutes (report last known state)
    - All nodes reach terminal state (report completion)
    - Any anomaly detected (unexpected state, missing signal files)

    Do NOT attempt to fix issues. Just report what you observe.
    """
)
```

### 2.2 Monitoring Mechanism

**Signal directory polling**:
1. Record `os.stat(signal_dir).st_mtime` at start
2. Every 30s: check if mtime changed
3. If changed: scan for new/modified `.json` files
4. Parse each signal: check `status` field for `error` or `failed`
5. Count nodes by status: pending, active, impl_complete, validated, failed

**DOT file monitoring**:
1. Record DOT file mtime at start
2. Every 30s: check if mtime changed
3. If changed: re-read DOT file, extract node status attributes
4. Compare with previous state to detect transitions

**Stall detection**:
- Track `last_state_change_time`
- If `now - last_state_change_time > stall_threshold`: report stall
- Default stall threshold: 5 minutes (configurable)

### 2.3 Cyclic Re-Launch Pattern

The monitor completes (waking System 3) only when attention is needed:

```
System 3                    Monitor (Haiku 4.5)
   |                            |
   |  Launch monitor ---------->|
   |                            |<-- Poll signals + DOT (30s cycle)
   |                            |    Detect: node failed
   |<----- COMPLETE ------------|  status: "MONITOR_ERROR"
   |  Handle failure            |
   |  (fix issue, requeue)      |
   |  RE-LAUNCH monitor ------->|  (cycle repeats)
   |                            |
   |                            |<-- Poll signals + DOT (30s cycle)
   |                            |    Detect: all nodes terminal
   |<----- COMPLETE ------------|  status: "MONITOR_COMPLETE"
   |  Run final validation      |
```

### 2.4 Monitor Output Statuses

| Status | Meaning | System 3 Action |
|--------|---------|----------------|
| `MONITOR_COMPLETE` | All nodes validated | Run final E2E, close initiative |
| `MONITOR_ERROR` | Node failed | Investigate root cause, requeue or escalate |
| `MONITOR_STALL` | No progress for >threshold | Check if worker hung, restart if needed |
| `MONITOR_ANOMALY` | Unexpected state | Investigate, may need manual DOT edit |

### 2.5 DOT Pipeline Creation Guidance (Skill Gap Fix)

**Root cause**: The s3-guardian skill documents how to *launch* pipelines but not how to *create* DOT files from scratch. This causes agents to explore source code (guardian.py, runner.py, dispatch_worker.py) to reverse-engineer the DOT format — wasting 500+ context tokens on information the skill should provide.

**Fix**: Add a "Creating a New Pipeline" quick-start section to s3-guardian SKILL.md with:
1. **Inline minimal DOT example** — complete, valid pipeline showing all attribute conventions
2. **Handler type mapping table** — which `handler` value for which task type
3. **Required vs optional node attributes** — what the runner/guardian expects

Handler type mapping:

| Handler | Purpose | Worker Type | LLM? |
|---------|---------|-------------|------|
| `start` | Pipeline entry point | N/A | No |
| `codergen` | Code implementation | Agent from `worker_type` | Yes |
| `research` | Framework/API investigation | Haiku (cheap) | Yes |
| `refine` | Rewrite SD with research findings | Sonnet | Yes |
| `tool` | Run shell command | N/A (subprocess) | No |
| `wait.system3` | Automated E2E gate | Python runner | No |
| `wait.human` | Human review gate | N/A (GChat) | No |
| `exit` | Pipeline termination | N/A | No |

## 3. Files Changed

| File | Change |
|------|--------|
| s3-guardian `SKILL.md` | Add "Pipeline Progress Monitor" section with spawn template; Add "Creating a New Pipeline" quick-start with inline DOT example and handler mapping table |
| s3-guardian `references/monitoring-patterns.md` | Add Haiku monitor pattern alongside existing tmux/SDK monitoring |
| s3-guardian `references/dot-pipeline-creation.md` (new) | Detailed DOT format reference: graph attributes, node attributes per handler, edge labels, checkpoint conventions |

## 4. Testing

- Manual: launch a pipeline, spawn monitor, verify it detects completion
- Manual: simulate a node failure (write a failed signal), verify monitor reports it
- Manual: simulate a stall (don't write any signals for 6 minutes), verify stall detection
- Manual: follow the new "Creating a New Pipeline" quick-start to create a fresh DOT file — verify it passes `cli.py validate`

## 5. Acceptance Criteria

- AC-0.1: s3-guardian SKILL.md documents the progress monitor sub-agent pattern with spawn template
- AC-0.2: Monitor poll mechanism documented (signal dir mtime + DOT file mtime)
- AC-0.3: Stall/error/completion detection rules documented with configurable thresholds
- AC-0.4: s3-guardian SKILL.md includes "Creating a New Pipeline" quick-start with inline DOT example
- AC-0.5: Handler type mapping table in SKILL.md covers all 8 handler types
- AC-0.6: `references/dot-pipeline-creation.md` exists with full DOT format reference
