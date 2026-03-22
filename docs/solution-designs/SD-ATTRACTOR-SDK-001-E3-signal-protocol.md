# SD-ATTRACTOR-SDK-001-E3: Signal Protocol — Pull-Based Signals

**PRD**: GAP-PRD-ATTRACTOR-SDK-001
**Epic**: 3 — Signal Protocol Alignment (Pull-Based Signals)
**Priority**: P0 (must land first — other epics depend on this)
**Validated Against**: Claude Code v2.1.39 (Context7 + Perplexity, 2026-03-03)
**Design Influence**: [Gastown Pull-Based Pattern](../references/gastown-comparison.md#priority-1-gupp--pull-semantics-for-work-assignment) (originally called GUPP in Gastown)

---

## 1. Problem

Guardian and runner use different signal directories:
- Guardian reads from harness repo: `claude-harness-setup/.cobuilder/signals/`
- Runner writes to impl repo worktree: `my-project/.claude/worktrees/verify-check-002/.cobuilder/signals/`

Result: Guardian's `wait_for_signal.py` never finds runner's RUNNER_EXITED signal. Guardian waits full 600s timeout, then discovers signal on filesystem scan of the wrong directory.

## 2. Design

### Pull-Based Signal Semantics (Adopted from Gastown)

Instead of the Runner pushing signals to the Guardian's inbox, we adopt **pull semantics**: completion records are written to **stable, known paths** that the Guardian polls. This provides:

- **Durability**: Records survive Guardian crashes (committed to Git)
- **Decoupling**: Guardian and Runner are not in a request-response relationship
- **Idempotency**: Reading from a known path multiple times is harmless
- **Auditability**: Git history shows exactly what happened and when

### Signal Directory Layout

The signal directory is **pipeline-scoped** — derived from the DOT file path:

```
{dot_dir}/signals/
  └── {node_id}/
      ├── assigned.json    ← Written by Guardian when node goes active
      ├── complete.json    ← Written by Runner when node finishes
      └── notes.json       ← Written by Worker for mid-work observations (Seance recovery artifact, E4)
```

```python
def resolve_signals_dir(dot_path: str) -> str:
    """Resolve signals directory from the DOT file's parent directory."""
    return os.path.join(os.path.dirname(os.path.abspath(dot_path)), "signals")
```

### Signal File Schemas

**Assignment record** (written by Guardian):
```json
{
  "status": "ASSIGNED",
  "node_id": "codergen_g12",
  "worker_type": "backend-solutions-engineer",
  "ts": 1709424000.123,
  "pipeline_id": "GAP-PRD-ATTRACTOR-SDK-001"
}
```

**Completion record** (written by Runner):
```json
{
  "status": "NODE_COMPLETE",
  "node_id": "codergen_g12",
  "ts": 1709425200.456,
  "session_id": "abc-123",
  "stop_reason": "end_turn"
}
```

**Notes record** (written by Worker, for Seance context recovery in E4):
```json
{
  "node_id": "codergen_g12",
  "ts": 1709424600.789,
  "observations": ["Chose FastAPI over Flask because existing codebase uses it", "Added index on user_id column for query performance"]
}
```

The `ts` field must be a monotonic timestamp. Readers skip records whose `ts` is older than the current session's start time.

### Atomic Signal Writes + Git Commit

Signal files must be written atomically AND committed to Git for durability:

```python
def write_signal(signals_dir: str, signal_name: str, payload: dict) -> None:
    """Write a signal atomically using rename, then commit to Git."""
    # Ensure node-scoped directory exists
    node_dir = os.path.join(signals_dir, payload.get("node_id", ""))
    os.makedirs(node_dir, exist_ok=True)

    target = os.path.join(node_dir, f"{signal_name}.json")
    tmp = target + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, target)

    # Commit for durability (survives Guardian crashes)
    _git_commit_signal(target, signal_name, payload.get("node_id", "unknown"))


def _git_commit_signal(file_path: str, signal_name: str, node_id: str) -> None:
    """Commit signal file to Git for crash-durability."""
    try:
        subprocess.run(["git", "add", file_path], capture_output=True, timeout=5)
        subprocess.run(
            ["git", "commit", "-m", f"signal: {signal_name} for {node_id}",
             "--no-verify"],  # Skip hooks for signal commits
            capture_output=True, timeout=10,
        )
    except Exception:
        pass  # Non-fatal: signal is still in filesystem
```

### Guardian Polling Loop

The Guardian polls stable paths instead of watching for pushed signals:

```python
def wait_for_completion(signals_dir: str, node_id: str,
                        timeout: int = 600, interval: int = 5) -> dict | None:
    """Poll for completion record at a known stable path (pull-based pattern)."""
    target = os.path.join(signals_dir, node_id, "complete.json")
    deadline = time.time() + timeout

    while time.time() < deadline:
        if os.path.exists(target):
            with open(target) as f:
                payload = json.load(f)
            if payload.get("ts", 0) > session_start_ts:  # Skip stale signals
                return payload
        time.sleep(interval)

    return None  # Timeout
```

### Changes Required

#### 2.1 `signal_protocol.py` — Add `resolve_signals_dir()` and atomic write helpers

```python
# New function
def resolve_signals_dir(dot_path: str | None = None, signals_dir: str | None = None) -> str:
    """Resolve the signals directory.

    Priority:
    1. Explicit --signals-dir override
    2. Pipeline-scoped: {dot_dir}/signals/
    3. Fallback: .claude/attractor/signals/ relative to git root
    """
    if signals_dir:
        return signals_dir
    if dot_path:
        return os.path.join(os.path.dirname(os.path.abspath(dot_path)), "signals")
    # Fallback to git root
    git_root = _find_git_root(os.getcwd())
    return os.path.join(git_root or ".", ".pipelines", "signals")
```

All signal read/write functions should accept an optional `signals_dir` parameter and use this resolver. Replace any bare `open()` signal writes with the atomic `write_signal()` helper above.

#### 2.2 `spawn_runner.py` — Pass `--signals-dir` derived from `--dot-file`

```python
# In main(), after parsing args:
if args.dot_file:
    signals_dir = resolve_signals_dir(dot_path=args.dot_file)
    cmd += ["--signals-dir", signals_dir]
```

#### 2.3 `guardian_agent.py` — Pass signals dir in system prompt

The guardian's system prompt should include the resolved signals directory path so the Claude LLM agent uses `--signals-dir` on all signal tool invocations:

```python
# In build_system_prompt():
signals_dir = resolve_signals_dir(dot_path=dot_path)
# Include in prompt:
# - wait_for_signal.py --target guardian --timeout {timeout} --signals-dir {signals_dir}
# - signal_guardian.py ... --signals-dir {signals_dir}
```

#### 2.4 `wait_for_signal.py` — Respect `--signals-dir`

Add `--signals-dir` CLI argument. When provided, watch that directory instead of the default. The polling loop (currently 5s) is sufficient for single-pipeline runs; see Implementation Notes for scale considerations.

### 3. Testing

- **Unit test**: `resolve_signals_dir()` with various inputs (dot_path, override, fallback)
- **Unit test**: `write_signal()` atomicity — verify `.tmp` file is cleaned up on success, target file has correct JSON payload
- **Unit test**: Signal reader ignores stale signals (ts < session start)
- **Integration test**: Runner writes signal to pipeline-scoped dir → Guardian reads within 5s
- **Regression test**: tmux mode without `--dot-file` still uses fallback directory

### 4. Files Changed

| File | Change |
|------|--------|
| `signal_protocol.py` | Add `resolve_signals_dir()`, `write_signal()` atomic helper; update read/write functions |
| `spawn_runner.py` | Pass `--signals-dir` derived from `--dot-file` |
| `guardian_agent.py` | Include signals_dir in system prompt tool paths |
| `wait_for_signal.py` | Add `--signals-dir` CLI argument |
| `runner_agent.py` | Pass signals_dir to RunnerStateMachine |
| `tests/test_signal_protocol.py` | New/updated tests |

---

## 5. Implementation Notes

These constraints were validated against Claude Code v2.1.39 and the 2026 Python ecosystem. They must be respected by any implementation of this epic.

### 5.1 Atomicity Is Non-Negotiable

Guardian and runner are independent OS processes that may write and read signals concurrently. Non-atomic writes (e.g., plain `open(path, "w").write(...)`) create a window where the reader sees a partial file. Always use the `write_signal()` rename-based pattern. On Linux and macOS, `os.rename()` within the same filesystem is guaranteed atomic by POSIX.

### 5.2 Signal Timestamps Prevent Stale-Signal Processing

If a pipeline is re-run in the same directory without clearing signals, leftover files from the previous run will be picked up immediately by `wait_for_signal.py`. The JSON payload's `ts` field and a session-start timestamp check are the guard. Readers must reject signals where `payload["ts"] < session_start_ts`.

### 5.3 Nested Session Timeout Propagation

The guardian → runner → worker chain each has its own 600s timeout. If the runner's timeout fires while waiting for a signal, the runner exits without writing a clean `RUNNER_EXITED` signal. This leaves the guardian stuck until its own timeout fires. Each layer should catch timeout exceptions and write a failure signal before exiting so the parent layer can respond promptly.

### 5.4 Scale Considerations (Informational — Not In-Scope for E3)

The current 5-second polling loop in `wait_for_signal.py` is adequate for single-pipeline SDK-mode runs (1–3 parallel nodes). For pipelines with 10+ parallel nodes, polling every 5 seconds across all signal directories becomes CPU-intensive. At that scale, replace polling with `watchdog` (cross-platform inotify wrapper) or native `inotify` on Linux. This is deferred to a future epic; flag it with a `# TODO(scale): watchdog` comment in `wait_for_signal.py`.

### 5.5 Out-of-Scope for This Epic

- **PID liveness checks and stdout tailing** — Epic 2 (Mode-Aware Runner Monitor)
- **Git log polling reliability** — Epic 2; note that relying solely on `git log` for completion detection is fragile. Epic 2 should supplement or replace this with process-level signals
- **CLAUDECODE environment variable isolation** — Epic 1 (Worker Backend); the runner must unset `CLAUDECODE` before spawning workers to prevent nested session conflicts

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
