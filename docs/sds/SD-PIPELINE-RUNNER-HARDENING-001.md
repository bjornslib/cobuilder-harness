---
title: "SD-PIPELINE-RUNNER-HARDENING-001: Pipeline Runner & Worker Hardening"
status: draft
type: architecture
last_verified: 2026-03-09
grade: authoritative
prd_ref: PRD-HARNESS-UPGRADE-001
---

# SD-PIPELINE-RUNNER-HARDENING-001: Pipeline Runner & Worker Hardening

## 1. Context & Motivation

### 1.1 Current State (2026-03-09)

The `pipeline_runner.py` has run **7 pipelines in the last 24 hours** producing **81 signal files** with **zero failures**. Logfire confirms zero exceptions. However, deep code analysis reveals **4 critical latent bugs** that will surface under adversarial conditions (concurrent workers, crash recovery, validation timeouts).

### 1.2 Evidence Summary

| Source | Finding |
|--------|---------|
| **Logfire (24h)** | 5 pipeline spans, 0 exceptions. Longest: 85min (AURA-LIVEKIT impl). Workers avg ~6min each. Parallel dispatch confirmed (B+C at same second). |
| **Code Analysis** | 4 CRITICAL, 4 MEDIUM, 3 LOW severity issues identified |
| **Signal Files** | 81 signals processed, all `result: pass`. Zero `fail` or `requeue` signals observed. |
| **Worker Telemetry** | Tools used: Bash(40%), Read(25%), Write(15%), Grep/Glob(12%), TaskCreate/Update(5%), Explore(3%) |

### 1.3 The Problem

The runner works perfectly on the **happy path**. But it has never been stress-tested on:
- Concurrent signal writes from parallel workers
- Validation agent crashes mid-execution
- Force-status persistence across DOT reloads
- Corrupted signal file recovery
- Orphaned non-codergen nodes after crash

These are **ticking time bombs** — invisible until they detonate during a critical pipeline run.

---

## 2. Architecture Changes

### 2.1 Epic A: Atomic Signal File Protocol (P0 — Critical)

**Problem**: `_write_node_signal()` does direct file writes without atomic guarantees. Concurrent writes to same node_id.json race silently.

**Current** (pipeline_runner.py:1419-1476):
```python
with open(signal_path, "w") as fh:
    fh.write(json.dumps(payload) + "\n")
```

**Proposed**:
```python
def _write_node_signal(self, node_id: str, payload: dict) -> str:
    signal_path = os.path.join(self.signal_dir, f"{node_id}.json")
    tmp_path = signal_path + f".tmp.{os.getpid()}.{time.monotonic_ns()}"

    # Add sequence number for ordering
    payload["_seq"] = self._signal_seq.get(node_id, 0) + 1
    self._signal_seq[node_id] = payload["_seq"]
    payload["_ts"] = datetime.utcnow().isoformat() + "Z"

    with open(tmp_path, "w") as fh:
        fh.write(json.dumps(payload) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    os.rename(tmp_path, signal_path)  # Atomic on POSIX
    return signal_path
```

**Also fix signal consumption order** (pipeline_runner.py:1230-1243):
```python
# BEFORE: consume then apply (data loss on crash)
os.rename(signal_path, dest)  # ← signal lost if _apply_signal crashes
self._apply_signal(node_id, signal)

# AFTER: apply then consume (idempotent)
self._apply_signal(node_id, signal)
os.rename(signal_path, dest)  # Only consumed after successful apply
```

**Corrupted signal handling**:
```python
except (OSError, json.JSONDecodeError) as exc:
    # Quarantine instead of silently skipping
    quarantine = os.path.join(self.signal_dir, "quarantine")
    os.makedirs(quarantine, exist_ok=True)
    shutil.move(signal_path, os.path.join(quarantine, os.path.basename(signal_path)))
    log.error("Quarantined corrupted signal %s: %s", signal_path, exc)
```

**Files to modify**:
- `pipeline_runner.py`: `_write_node_signal()`, `_process_signals()`, `_apply_signal()`

**Acceptance Criteria**:
- AC-1: Signal writes use temp-file-then-rename (atomic on POSIX)
- AC-2: Each signal includes `_seq` and `_ts` metadata fields
- AC-3: Corrupted signals moved to `signals/quarantine/` (not silently dropped)
- AC-4: Signal consumption happens AFTER successful transition application
- AC-5: Concurrent write test: 10 parallel writers, zero corruption

---

### 2.2 Epic B: force_status Persistence Fix (P0 — Critical)

**Problem**: `_force_status()` edits in-memory `self.dot_content` but `_main_loop()` reloads DOT from disk, clobbering the forced status.

**Current** (pipeline_runner.py ~line 1380):
```python
def _force_status(self, node_id, target_status):
    # Edits self.dot_content in memory only
    self.dot_content = self.dot_content.replace(...)
```

**Meanwhile** (pipeline_runner.py:335-349):
```python
# Main loop reloads from disk → clobbers in-memory edits
with open(self.dot_path) as fh:
    self.dot_content = fh.read()
```

**Proposed**: Use `_do_transition()` (which already writes to disk with fcntl lock) instead of `_force_status()`:

```python
def _force_status(self, node_id: str, target_status: str) -> None:
    """Force node status — writes to disk (not just memory)."""
    self._do_transition(node_id, target_status)
    # Also persist requeue guidance if present
    if node_id in self.requeue_guidance:
        self._persist_requeue_guidance(node_id, self.requeue_guidance[node_id])
```

**Files to modify**:
- `pipeline_runner.py`: `_force_status()`, add `_persist_requeue_guidance()`

**Acceptance Criteria**:
- AC-1: `_force_status()` writes to DOT file on disk (not just memory)
- AC-2: Status survives `_main_loop()` reload cycle
- AC-3: Requeue guidance persisted alongside status change
- AC-4: Test: force_status → reload DOT → verify status persists

---

### 2.3 Epic C: Validation Agent Error Handling (P0 — Critical)

**Problem**: Validation subprocess failures are invisible. If validation agent crashes, node stays `impl_complete` forever — "Pipeline stuck" with no clear cause.

**Current** (pipeline_runner.py:933-1210):
- Spawns validation subprocess in background
- No stdout/stderr capture
- No timeout enforcement
- No retry on failure

**Proposed**:

```python
def _dispatch_validation_agent(self, node_id, target_node_id):
    """Dispatch validation with error handling and configurable timeout."""
    timeout = int(os.environ.get("VALIDATION_TIMEOUT", "600"))  # 10min default

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            log.error("[validation] %s failed (rc=%d): %s",
                     node_id, result.returncode, result.stderr[:500])
            # Write failure signal so node doesn't hang
            self._write_node_signal(target_node_id, {
                "status": "fail",
                "result": "fail",
                "reason": f"Validation agent crashed: {result.stderr[:200]}",
                "validator_exit_code": result.returncode,
            })

    except subprocess.TimeoutExpired:
        log.error("[validation] %s timed out after %ds", node_id, timeout)
        self._write_node_signal(target_node_id, {
            "status": "fail",
            "result": "fail",
            "reason": f"Validation timed out after {timeout}s",
        })
```

**Files to modify**:
- `pipeline_runner.py`: `_dispatch_validation_agent()`

**Acceptance Criteria**:
- AC-1: Validation timeout configurable via `VALIDATION_TIMEOUT` env var (default 600s)
- AC-2: Validation failures write explicit `fail` signal (node never hangs)
- AC-3: stderr captured and included in failure signal (first 500 chars)
- AC-4: Test: mock validation crash → verify fail signal written within 5s

---

### 2.4 Epic D: Orphaned Node Resume Expansion (P1 — High)

**Problem**: After runner restart, only `codergen` nodes with status `active` are re-dispatched. Orphaned `research`, `refine`, and `acceptance-test-writer` nodes remain stuck.

**Current** (pipeline_runner.py:384-393):
```python
orphaned_active_nodes = [
    n for n in nodes
    if n["attrs"].get("status") == "active"
    and n["attrs"].get("handler") == "codergen"  # ← Only codergen!
    and n["id"] not in self.active_workers
]
```

**Proposed**:
```python
RESUMABLE_HANDLERS = frozenset({"codergen", "research", "refine", "acceptance-test-writer"})
GATE_HANDLERS = frozenset({"wait.system3", "wait.human"})

orphaned_active_nodes = [
    n for n in nodes
    if n["attrs"].get("status") == "active"
    and n["id"] not in self.active_workers
]

for node in orphaned_active_nodes:
    handler = node["attrs"].get("handler", "")
    if handler in RESUMABLE_HANDLERS:
        retries = self.orphan_resume_counts.get(node["id"], 0)
        if retries < 3:  # Exponential backoff
            delay = min(2 ** retries * 5, 60)  # 5s, 10s, 20s, max 60s
            log.info("[resume] Re-dispatch %s (handler=%s, attempt=%d, delay=%ds)",
                    node["id"], handler, retries + 1, delay)
            time.sleep(delay)
            self._dispatch_node(node, data)
            self.orphan_resume_counts[node["id"]] = retries + 1
        else:
            log.error("[resume] Exhausted retries for orphaned node %s", node["id"])
            self._do_transition(node["id"], "failed")
    elif handler in GATE_HANDLERS:
        log.warning("[resume] Gate node %s stuck in active — emitting escalation", node["id"])
        self._write_node_signal(node["id"], {
            "status": "escalation",
            "reason": f"Gate node {node['id']} orphaned after restart",
        })
```

**Files to modify**:
- `pipeline_runner.py`: orphaned node detection block, add `orphan_resume_counts` dict

**Acceptance Criteria**:
- AC-1: All WORKER_HANDLERS covered by orphan resume (not just codergen)
- AC-2: Exponential backoff: 5s, 10s, 20s delays between retries
- AC-3: Max 3 retries per orphaned node before marking failed
- AC-4: Gate nodes (wait.system3, wait.human) emit escalation signal instead of re-dispatch
- AC-5: Test: simulate crash → verify research/refine nodes resume correctly

---

### 2.5 Epic E: Worker Prompt Improvements (P1 — High)

**Problem**: Workers receive identical prompts regardless of handler type. Research nodes don't know they should validate docs. Validation agents don't see git diffs. Requeue guidance is lost after first dispatch.

**5 sub-improvements**:

#### E.1: Handler-Specific Prompt Preambles

```python
HANDLER_PREAMBLES = {
    "codergen": "You are implementing code changes. Write production-quality code.",
    "research": "You are researching framework patterns. Validate docs against installed versions. Update the SD with findings.",
    "refine": "You are refining a Solution Design. Merge research findings into the SD as first-class content.",
    "acceptance-test-writer": "You are writing Gherkin acceptance tests from the PRD acceptance criteria.",
}
```

#### E.2: Validation Prompt Gets Pre-Computed Diff

```python
def _build_validation_prompt(self, node_id, ...):
    # Pre-compute diff so validator doesn't waste 30s
    diff = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1"],
        capture_output=True, text=True, timeout=10
    ).stdout[:2000]

    prompt += f"\n## Changes Made\n```\n{diff}\n```\n"
```

#### E.3: Persistent Requeue Guidance

```python
# Instead of .pop() (one-shot), keep guidance in persistent store
def _get_requeue_guidance(self, node_id):
    # Check persistent file first
    guidance_path = os.path.join(self.signal_dir, "guidance", f"{node_id}.txt")
    if os.path.exists(guidance_path):
        return open(guidance_path).read()
    return self.requeue_guidance.get(node_id, "")
```

#### E.4: Worker Model Selection Documentation

Add to `worker-tool-reference.md`:
```markdown
## Model Selection Guide
| Handler | Default Model | When to Override |
|---------|--------------|-----------------|
| codergen | Haiku 4.5 | Sonnet for complex multi-file changes |
| research | Haiku 4.5 | Rarely needs upgrade |
| refine | Sonnet 4.6 | Always Sonnet (requires synthesis) |
| validation | Sonnet 4.6 | Never downgrade (needs judgment) |
```

#### E.5: SD Path Fallback Clarity

```python
# Replace ambiguous "(none)" with actionable message
if not os.path.exists(sd_path):
    sd_section = f"## Solution Design\nNo SD found at `{sd_path}`. If this is unexpected, check the DOT node's sd_path attribute."
```

**Files to modify**:
- `pipeline_runner.py`: `_build_worker_prompt()`, `_build_validation_prompt()`, requeue guidance
- `.claude/agents/worker-tool-reference.md`: model selection section

**Acceptance Criteria**:
- AC-1: Each handler type gets a distinct preamble in the worker prompt
- AC-2: Validation prompts include pre-computed `git diff --stat`
- AC-3: Requeue guidance persists across dispatches (not one-shot `.pop()`)
- AC-4: Model selection guide added to worker-tool-reference.md
- AC-5: SD path fallback shows actionable error (not just "(none)")

---

### 2.6 Epic F: Global Pipeline Safeguards (P2 — Medium)

#### F.1: Pipeline Timeout

```python
# Add --max-duration flag
parser.add_argument("--max-duration", type=int, default=7200,
                   help="Max pipeline duration in seconds (default: 2h)")
```

In main loop:
```python
if time.monotonic() - self.start_time > self.max_duration:
    log.error("[timeout] Pipeline exceeded %ds. Failing remaining nodes.", self.max_duration)
    for node_id in self._get_non_terminal_nodes():
        self._do_transition(node_id, "failed")
    return PipelineResult.TIMEOUT
```

#### F.2: Cost Tracking in Signals

```python
# Workers report token usage in signal
{
    "status": "success",
    "cost": {"input_tokens": 12500, "output_tokens": 3400, "model": "haiku-4.5"},
    ...
}
```

Runner aggregates:
```python
self.pipeline_cost = {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "by_node": {},
}
```

#### F.3: Rate Limiting Per Worker Type

```python
# Prevent API rate limit exhaustion
WORKER_TYPE_LIMITS = {
    "codergen": 4,      # Max 4 parallel codergen workers
    "research": 6,      # Research is lightweight
    "validation": 2,    # Validation needs sequential access
}
```

**Acceptance Criteria**:
- AC-1: `--max-duration` flag with 2h default, failing remaining nodes on timeout
- AC-2: Cost data (tokens, model) included in worker signal payloads
- AC-3: Per-worker-type concurrency limits configurable via env vars

---

## 3. Implementation Priority

| Priority | Epic | Effort | Impact | Risk if Skipped |
|----------|------|--------|--------|-----------------|
| **P0** | A: Atomic Signals | 2h | CRITICAL | Data loss, stuck pipelines |
| **P0** | B: force_status Fix | 1h | CRITICAL | Lost retries, stuck nodes |
| **P0** | C: Validation Error Handling | 2h | CRITICAL | Invisible failures |
| **P1** | D: Orphan Resume Expansion | 2h | HIGH | Stuck research/refine after crash |
| **P1** | E: Worker Prompt Improvements | 3h | HIGH | Worker confusion, wasted cycles |
| **P2** | F: Global Safeguards | 3h | MEDIUM | Runaway pipelines, cost surprises |

**Total estimated effort**: ~13h

---

## 4. Testing Strategy

### Unit Tests (per epic)
- Epic A: Concurrent signal write stress test (10 threads)
- Epic B: force_status → reload → verify persistence
- Epic C: Mock validation crash → verify fail signal timing
- Epic D: Simulate crash → verify all handler types resume
- Epic E: Prompt generation snapshot tests per handler type
- Epic F: Timeout enforcement test

### Integration Test
- Full pipeline with intentional failures injected at each stage
- Verify recovery from every failure mode

### Regression Guard
- Existing 15+ test files (~8500 LOC) must continue passing
- Add `test_hardening.py` with all new scenarios

---

## 5. Dependencies

- `claude_code_sdk` (existing, unchanged)
- `watchdog` (existing, optional)
- `logfire` (existing, optional — enhanced with cost tracking)
- No new external dependencies

---

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Atomic rename not truly atomic on NFS | Document: pipeline requires local filesystem |
| Exponential backoff delays pipeline | Cap at 60s, configurable via env var |
| Validation timeout too aggressive | Default 600s (10min), configurable |
| Cost tracking adds overhead | Opt-in via env var `PIPELINE_TRACK_COST=1` |

---

## 7. Open Questions (For Research Phase)

- **Q1**: Should corrupted signals trigger immediate node failure or wait for manual inspection?
- **Q2**: What is the right default for `--max-duration`? 2h may be too short for large initiatives.
- **Q3**: Should we add structured logging (JSON) to complement Logfire spans?
- **Q4**: Is there value in a `--dry-run` mode that validates the pipeline without dispatching workers?
