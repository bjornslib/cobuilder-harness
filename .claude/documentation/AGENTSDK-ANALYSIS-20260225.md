---
title: "Agentsdk Analysis 20260225"
status: active
type: architecture
last_verified: 2026-03-14
grade: reference
---

# AgentSDK Analysis — 2026-02-25

## Key Findings

| Metric | Value | Assessment |
|--------|-------|------------|
| E2E Cycle Time | 340s (5.7 min) | Excellent |
| Signal Latency | 81s | Good |
| Guardian Response | 17s | Excellent |
| Checkpoint Reliability | 100% | Excellent |
| Node Transitions | <10ms | Excellent |

---

## Improvement Areas (Priority Order)

### P1: Crash Recovery (spawn_orchestrator.py)

**Problem**: If orchestrator tmux session dies during active work, runner waits the full 600s timeout with no recovery path. No restart logic exists.

**Fix**: Add respawn mechanism with max 3 attempts, resume from checkpoint.

- Detect session failure via `tmux has-session`
- Respawn orchestrator in same worktree
- Load last checkpoint to resume from known-good state
- Escalate to guardian after 3 failed attempts

**Estimated effort**: 15-20 min

---

### P2: Validation Retry Logic (wait_for_guardian.py, runner_agent.py)

**Problem**: Single attempt with 600s timeout, no retry on transient failures.

**Fix**: Exponential backoff — 30s, 60s, 120s between retries, max 3 retries.

- Reduce per-attempt timeout to 300s
- On timeout/failure: wait backoff duration, retry
- After 3 retries: raise terminal error to guardian

**Estimated effort**: 10 min

---

### P3: Signal Bus Redundancy (signal_protocol.py)

**Problem**: Signal files are the only communication channel. No fallback if filesystem becomes unavailable or signal write fails.

**Fix**: Add message-bus queue adapter as secondary channel.

- Primary: signal files (current behavior, unchanged)
- Secondary: message-bus SQLite queue (already exists in .claude/message-bus/)
- Guardian checks both sources on startup and during polling

**Estimated effort**: 20 min

---

### P4: Session Naming Convention (guardian_agent.py, spawn_orchestrator.py)

**Problem**: Runner sessions can match the `s3-live-*` stop gate regex pattern, causing false positive team-missing blocks.

**Fix**: Use explicit prefixes; update stop gate matching.

- Runner sessions: `runner-{node_id}` prefix
- Orchestrators: `orch-{node_id}` prefix
- Stop gate: match only exact `s3-live-` prefix (not substring)

**Estimated effort**: 5 min

---

### P5: Boot Timeout Tuning (spawn_orchestrator.py)

**Problem**: Current sleeps (8s claude launch, 3s output-style, 2s prompt) may be conservative, slowing pipeline throughput unnecessarily.

**Fix**: Empirical measurement — sample 10 boots, calculate mean + 2σ, document final values.

- Current values are reliable; investigation is about optimization
- Any reduction multiplies across all pipeline nodes

**Estimated effort**: 30 min investigation

---

## What's Working Well

- **Signal atomicity**: write-to-.tmp → `os.rename` prevents partial reads
- **tmux send-keys patterns**: Pattern 1 (separate text + Enter calls) is reliable
- **Output style delivery**: `/output-style orchestrator` as slash command (not CLI flag) works consistently
- **Checkpoint save/restore cycle**: 100% reliable across all tested pipeline runs
- **4-layer chain integrity**: launch_guardian → guardian_agent → runner_agent → orchestrator (tmux) → worker all verified E2E

---

## Session Log Summary (2026-02-24)

Three bugs fixed in spawn_orchestrator.py during E2E validation:

1. `--output-style` is NOT a valid CLI flag — must send as `/output-style orchestrator` slash command after Claude boots
2. tmux send-keys: text and Enter MUST be separate calls (Pattern 1)
3. Boot timing: `sleep(8)` after tmux, `sleep(3)` after output-style, `sleep(2)` before Enter

Signal chain verified: Runner→Guardian `NEEDS_REVIEW` and Guardian→Runner `VALIDATION_PASSED` both propagated correctly.

Pipeline state transitions: `pending → active → validated` + finalize signals written.
