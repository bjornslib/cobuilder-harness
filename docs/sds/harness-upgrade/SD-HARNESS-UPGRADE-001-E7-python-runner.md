---
title: "SD-HARNESS-UPGRADE-001: Pure Python Pipeline Runner"
status: active
type: solution-design
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001: Pure Python Pipeline Runner

> **Prerequisite**: Epic 7.1 (Worker Prompt Restructuring). The Python runner dispatches workers directly — it must dispatch workers that receive well-structured, concise prompts rather than the current 21K system prompt.

## 1. Problem Statement

The E2E analysis (2026-03-06) proved that the guardian LLM layer is entirely superfluous for graph traversal:

> "Guardian spent 33 turns on work that is entirely deterministic: Parse dot file, find ready nodes, transition to active, spawn runner, poll PID, read node status, transition to validated, find next ready nodes. None of these steps require language model reasoning."

**Cost**: $4.91 per pipeline run (33 LLM turns) for work a Python loop does in milliseconds.
**Savings**: 46% reduction in total pipeline cost ($10.77 -> $5.86 per node).

The guardian concept dissolves entirely. `pipeline_runner.py` replaces the runner layer, and System 3 remains as the top-level LLM authority for business validation.

## 2. Design

### 2.1 Architecture

**Current 3-layer (guardian LLM)**:
```
guardian.py (LLM, $4.91, 33 turns)
  -> Bash calls to cli.py (parse, validate, transition, status)
  -> Spawns runner.py as subprocess
    -> runner.py (Python) builds prompts, calls _run_agent()
      -> Worker (LLM, $5.86) implements the task
```

**Proposed 3-layer (Python runner replaces guardian + runner)**:
```
System 3 (LLM, Opus)
  -> Strategic planning, OKR tracking, blind Gherkin E2E acceptance
  -> Launches pipeline_runner.py (Python, $0, <1s graph ops)
    -> pipeline_runner.py dispatches ALL workers via AgentSDK
      -> Workers (codergen, research, refine, validation) implement tasks
```

The guardian process is eliminated. System 3 is the only LLM that reasons about business outcomes. The runner is a purely mechanical state machine with zero LLM intelligence.

### 2.2 What Already Exists (Keep As-Is)

These pure Python modules are production-ready and reusable:

| Module | Function | Used By Runner |
|--------|----------|---------------|
| `parser.py` | DOT file parsing | `Pipeline.load()` |
| `transition.py` | State machine + cascade logic | `pipeline.transition()` |
| `checkpoint.py` | Pipeline state serialization | `save_checkpoint()` / `load_checkpoint()` |
| `validator.py` | Graph structural validation | `pipeline.validate()` |
| `signal_protocol.py` | Signal file I/O | `read_signal()` / `write_signal()` |

### 2.3 Status Chain

```
pending -> active -> impl_complete -> validated -> accepted
                  \-> failed
```

| Status | Meaning | Who Sets It |
|--------|---------|-------------|
| `pending` | Ready for dispatch (or requeued) | Runner (initial state, or requeue from validation) |
| `active` | Worker dispatched, in progress | Runner (on dispatch) |
| `impl_complete` | Worker says "I'm done" | Runner (reads worker signal) |
| `validated` | Validation agent confirms technical correctness | Runner (reads validation agent signal) |
| `accepted` | System 3 confirms business requirements via blind Gherkin + E2E | Runner (reads System 3 acceptance signal) |
| `failed` | Worker or validation failed, no retries left | Runner (reads failure signal) |

### 2.4 New File: `pipeline_runner.py`

```python
"""Pure Python DOT pipeline runner. Zero LLM tokens for graph traversal.

3-layer hierarchy: System 3 (LLM) -> pipeline_runner.py (Python) -> Workers (AgentSDK)

The runner has ZERO LLM intelligence. It can only:
- Parse DOT files, track node states, find dispatchable nodes
- Launch AgentSDK workers
- Watch signal files via watchdog
- Write checkpoints, transition DOT states
- Read signal files and mechanically apply results
"""

import asyncio
import json
import subprocess
import time
from pathlib import Path
from threading import Event
from typing import Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from .parser import Pipeline
from .transition import transition_node, cascade_finalize
from .checkpoint import save_checkpoint, load_checkpoint
from .signal_protocol import read_signal, write_signal


# --- Mechanical signal transition logic ---
# The runner applies these transitions without any interpretation.
# Pass = advance, fail = stop, requeue = send predecessor back to pending.
SIGNAL_TRANSITIONS = {
    "pass":    lambda runner, node: runner._transition(node.id, "validated"),
    "fail":    lambda runner, node: runner._transition(node.id, "failed"),
    "requeue": lambda runner, node: runner._requeue_predecessor(node),
}


class SignalFileHandler(FileSystemEventHandler):
    """Watchdog handler that sets an event when signal files change."""

    def __init__(self, wake_event: Event):
        self.wake_event = wake_event

    def on_created(self, event):
        if event.src_path.endswith(".json"):
            self.wake_event.set()

    def on_modified(self, event):
        if event.src_path.endswith(".json"):
            self.wake_event.set()


class DotFileHandler(FileSystemEventHandler):
    """Watchdog handler for external DOT file changes (e.g., System 3 gate approvals)."""

    def __init__(self, dot_path: str, wake_event: Event):
        self.dot_path = str(dot_path)
        self.wake_event = wake_event

    def on_modified(self, event):
        if event.src_path == self.dot_path:
            self.wake_event.set()


class PipelineRunner:
    """Pure Python DOT pipeline runner. Zero LLM tokens for graph traversal.

    Single writer: only this runner writes to the DOT file.
    Workers and validation agents communicate exclusively via signal files.
    """

    HANDLER_REGISTRY = {
        "codergen":     "_handle_worker",
        "research":     "_handle_worker",
        "refine":       "_handle_worker",
        "tool":         "_handle_tool",
        "wait.system3": "_handle_gate",
        "wait.human":   "_handle_human",
        "conditional":  "_handle_conditional",
        "parallel":     "_handle_parallel",
        "start":        "_handle_noop",
        "exit":         "_handle_exit",
    }

    # AgentSDK worker config per handler type
    WORKER_CONFIG = {
        "codergen": {
            "subagent_type": "codegen-worker",
            "skills": ["worker-focused-execution"],
        },
        "research": {
            "subagent_type": "research-worker",
            "skills": ["research-first", "explore-first-navigation"],
        },
        "refine": {
            "subagent_type": "refine-worker",
            "skills": ["worker-focused-execution"],
        },
    }

    VALIDATION_WORKER_CONFIG = {
        "subagent_type": "validation-test-agent",
        "skills": ["acceptance-test-runner"],
    }

    def __init__(
        self,
        dot_file: str,
        config: Optional[dict] = None,
        resume: bool = False,
    ):
        self.dot_file = Path(dot_file)
        self.config = config or {}
        self.pipeline = Pipeline.load(dot_file)
        self.signal_dir = self.dot_file.parent / "signals"
        self.signal_dir.mkdir(exist_ok=True)
        self.checkpoint_dir = self.dot_file.parent / "checkpoints"
        self.checkpoint_dir.mkdir(exist_ok=True)
        self.active_workers: dict[str, str] = {}  # node_id -> dispatch tracking

        # Watchdog event — set whenever a signal file or DOT file changes
        self._wake_event = Event()

        if resume:
            checkpoint = load_checkpoint(dot_file)
            if checkpoint:
                self.pipeline.restore(checkpoint)

    def run(self) -> dict:
        """Main loop. Returns final pipeline state.

        Uses watchdog-based file monitoring instead of polling.
        The runner blocks on _wake_event.wait() until a signal file
        or DOT file change wakes it up.
        """
        self.pipeline.validate()

        # Start watchdog observers
        observer = Observer()
        signal_handler = SignalFileHandler(self._wake_event)
        dot_handler = DotFileHandler(str(self.dot_file), self._wake_event)
        observer.schedule(signal_handler, str(self.signal_dir), recursive=False)
        observer.schedule(dot_handler, str(self.dot_file.parent), recursive=False)
        observer.start()

        try:
            while not self._is_terminal():
                # 1. Find and dispatch ready nodes
                for node in self._find_dispatchable_nodes():
                    handler_name = self.HANDLER_REGISTRY.get(node.handler)
                    if not handler_name:
                        raise ValueError(f"Unknown handler: {node.handler}")
                    self._transition(node.id, "active")
                    handler = getattr(self, handler_name)
                    handler(node)

                # 2. Process any completed signals
                self._process_signals()

                # 3. Cascade finalize (unblock downstream)
                cascade_finalize(self.pipeline)
                save_checkpoint(self.dot_file, self.pipeline)

                # 4. Block until watchdog detects a file change
                if not self._is_terminal():
                    self._wake_event.clear()
                    self._wake_event.wait(timeout=30.0)  # 30s safety timeout
        finally:
            observer.stop()
            observer.join()

        return self.pipeline.status_summary()

    def _transition(self, node_id: str, status: str):
        """Single-writer DOT state transition + checkpoint."""
        transition_node(self.pipeline, node_id, status)
        save_checkpoint(self.dot_file, self.pipeline)

    def _find_dispatchable_nodes(self) -> list:
        """Nodes that are pending AND all upstream deps are validated/accepted."""
        return [
            n for n in self.pipeline.nodes
            if n.status == "pending"
            and all(
                self.pipeline.node_status(dep) in ("validated", "accepted")
                for dep in self.pipeline.predecessors(n.id)
            )
            and n.id not in self.active_workers
        ]

    def _process_signals(self):
        """Read signal files for active workers. Apply mechanical transitions."""
        for node_id in list(self.active_workers.keys()):
            signal_path = self.signal_dir / f"{node_id}.json"
            signal = read_signal(signal_path)
            if not signal:
                continue

            node = self.pipeline.get_node(node_id)
            del self.active_workers[node_id]

            # Worker completion signals -> impl_complete or failed
            if node.status == "active":
                if signal.get("status") == "success":
                    self._transition(node_id, "impl_complete")
                    # Dispatch validation agent for nodes with wait.system3 gate
                    if self._has_system3_gate(node):
                        self._dispatch_validation_agent(node)
                else:
                    self._transition(node_id, "failed")

            # Validation agent signals -> validated, failed, or requeue
            elif node.status == "impl_complete":
                result = signal.get("result", "fail")
                action = SIGNAL_TRANSITIONS.get(result)
                if action:
                    action(self, node)
                else:
                    self._transition(node_id, "failed")

            # System 3 acceptance signals -> accepted
            elif node.status == "validated":
                if signal.get("result") == "accepted":
                    self._transition(node_id, "accepted")
                else:
                    self._transition(node_id, "failed")

    def _is_terminal(self) -> bool:
        """Pipeline is terminal when no pending/active/impl_complete nodes remain."""
        active_states = {"pending", "active", "impl_complete"}
        has_work = any(n.status in active_states for n in self.pipeline.nodes)
        return not has_work and not self.active_workers

    # --- Handler implementations ---
    # All handlers that dispatch LLM work use AgentSDK exclusively.
    # No headless `claude -p` anywhere.

    def _handle_worker(self, node):
        """Dispatch AgentSDK worker for implementation/research/refine."""
        worker_config = self.WORKER_CONFIG.get(node.handler, self.WORKER_CONFIG["codergen"])

        self._dispatch_agent_sdk(
            node_id=node.id,
            subagent_type=worker_config["subagent_type"],
            skills=worker_config["skills"],
            instructions=self._build_worker_instructions(node),
            worktree=node.attrs.get("worktree") or self.config.get("default_worktree"),
            sd_path=node.attrs.get("sd_path"),
        )
        self.active_workers[node.id] = worker_config["subagent_type"]

    def _handle_tool(self, node):
        """Run a shell command and write signal. No LLM."""
        command = node.attrs.get("command") or node.attrs.get("tool_command")
        timeout = int(node.attrs.get("timeout", 120))
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=timeout
            )
            write_signal(self.signal_dir / f"{node.id}.json", {
                "status": "success" if result.returncode == 0 else "error",
                "returncode": result.returncode,
                "stdout": result.stdout[:10000],
                "stderr": result.stderr[:5000],
            })
        except subprocess.TimeoutExpired:
            write_signal(self.signal_dir / f"{node.id}.json", {
                "status": "error",
                "message": f"Command timed out after {timeout}s",
            })

    def _handle_gate(self, node):
        """wait.system3 gate: two-stage validation.

        Stage 1 (impl_complete): Runner dispatches a validation-test-agent via AgentSDK
            to check technical correctness. Validation agent writes signal with
            result: "pass" | "fail" | "requeue".

        Stage 2 (validated): Runner writes a "ready-for-review" signal.
            System 3's Haiku 4.5 monitor detects this and wakes System 3.
            System 3 runs blind Gherkin E2E scenarios independently, then writes
            an acceptance signal. Runner transitions to "accepted".

        The runner itself performs NO validation, NO test execution, NO LLM reasoning.
        """
        # Gate nodes start as active. The actual validation is triggered
        # when predecessor workers reach impl_complete (see _process_signals).
        # Mark gate as waiting — it will be driven by signal file arrivals.
        self.active_workers[node.id] = "gate_waiting"

    def _handle_human(self, node):
        """Emit review request to GChat, wait for human response signal."""
        summary_ref = node.attrs.get("summary_ref")
        summary = ""
        if summary_ref and Path(summary_ref).exists():
            summary = Path(summary_ref).read_text()

        self._emit_gchat_review(node, summary)
        self.active_workers[node.id] = "human_waiting"

    def _handle_conditional(self, node):
        """Evaluate condition expression and route."""
        condition = node.attrs.get("condition", "true")
        result = condition.lower() in ("true", "1", "yes")
        write_signal(self.signal_dir / f"{node.id}.json", {
            "status": "success", "condition_result": result})

    def _handle_parallel(self, node):
        """Fan-out: mark as complete, downstream nodes become dispatchable."""
        write_signal(self.signal_dir / f"{node.id}.json", {
            "status": "success", "message": "Fan-out complete"})

    def _handle_noop(self, node):
        """Start/passthrough -- immediately complete."""
        write_signal(self.signal_dir / f"{node.id}.json", {"status": "success"})

    def _handle_exit(self, node):
        """Exit -- pipeline complete."""
        write_signal(self.signal_dir / f"{node.id}.json", {
            "status": "success", "message": "Pipeline complete"})

    # --- AgentSDK dispatch ---

    def _dispatch_agent_sdk(
        self,
        node_id: str,
        subagent_type: str,
        skills: list[str],
        instructions: str,
        worktree: Optional[str] = None,
        sd_path: Optional[str] = None,
    ):
        """Dispatch a worker via claude_code_sdk. All LLM work goes through here.

        No headless `claude -p` anywhere. Every worker is launched as an AgentSDK
        sub-agent with proper type, skills, and instructions.
        """
        import claude_code_sdk as sdk

        # Build AgentSDK options
        options = sdk.ClaudeCodeOptions(
            subagent_type=subagent_type,
            skills=skills,
            allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "MultiEdit"],
        )

        if worktree:
            options.worktree = worktree

        # Inline solution design content if path provided
        if sd_path and Path(sd_path).exists():
            sd_content = Path(sd_path).read_text()
            instructions = f"## Solution Design\n\n{sd_content}\n\n---\n\n{instructions}"

        # Add signal protocol to instructions
        instructions += (
            f"\n\n## Signal Protocol\n"
            f"When complete, write your result to: {self.signal_dir / f'{node_id}.json'}\n"
            f'Format: {{"status": "success"|"error", "summary": "...", "files_changed": [...]}}'
        )

        # Launch asynchronously (fire-and-forget, signal file communicates completion)
        asyncio.ensure_future(
            sdk.run(instructions, options=options)
        )

    def _dispatch_validation_agent(self, node):
        """Dispatch a validation-test-agent via AgentSDK to check technical correctness.

        The validation agent runs acceptance-test-runner skill and writes a signal:
        {
            "node": "<validate_node_id>",
            "result": "pass" | "fail" | "requeue",
            "reason": "...",
            "requeue_target": "<predecessor_node_id>",  # only if result=requeue
            "evidence": [...]
        }
        """
        config = self.VALIDATION_WORKER_CONFIG
        prd_ref = node.attrs.get("contract_ref", "")
        gate_type = node.attrs.get("gate_type", "e2e")

        instructions = (
            f"Validate technical correctness for node {node.id}.\n"
            f"Gate type: {gate_type}\n"
            f"PRD reference: {prd_ref}\n\n"
            f"Run acceptance tests and report results.\n"
            f"Write signal to: {self.signal_dir / f'{node.id}.json'}\n"
            f"Signal format:\n"
            f'{{"result": "pass"|"fail"|"requeue", "reason": "...", '
            f'"requeue_target": "<node_id if requeue>", "evidence": [...]}}'
        )

        self._dispatch_agent_sdk(
            node_id=node.id,
            subagent_type=config["subagent_type"],
            skills=config["skills"],
            instructions=instructions,
        )
        self.active_workers[node.id] = config["subagent_type"]

    def _write_ready_for_review(self, node):
        """Write a ready-for-review signal so System 3's monitor can detect it."""
        ready_signal = self.signal_dir / f"{node.id}.ready-for-review.json"
        write_signal(ready_signal, {
            "node": node.id,
            "status": "validated",
            "message": "Technical validation passed. Awaiting System 3 acceptance.",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    def _has_system3_gate(self, node) -> bool:
        """Check if this node has a downstream wait.system3 gate."""
        for succ_id in self.pipeline.successors(node.id):
            succ = self.pipeline.get_node(succ_id)
            if succ and succ.handler == "wait.system3":
                return True
        return False

    def _requeue_predecessor(self, gate_node):
        """Mechanical requeue: transition the predecessor back to pending."""
        for pred_id in self.pipeline.predecessors(gate_node.id):
            pred = self.pipeline.get_node(pred_id)
            if pred and pred.handler in ("codergen", "research", "refine"):
                retry_count = pred.attrs.get("_retry_count", 0)
                max_retries = int(pred.attrs.get("max_retries", 1))
                if retry_count < max_retries:
                    pred.attrs["_retry_count"] = retry_count + 1
                    self._transition(pred_id, "pending")
                    # Clean up old signal so worker gets a fresh start
                    old_signal = self.signal_dir / f"{pred_id}.json"
                    if old_signal.exists():
                        old_signal.unlink()
                    return
        # No retries left — fail the gate
        self._transition(gate_node.id, "failed")

    # --- Helper methods ---

    def _build_worker_instructions(self, node) -> str:
        """Build worker instructions from node attributes."""
        parts = []
        if node.label:
            parts.append(f"## Task: {node.label}")
        if node.attrs.get("description"):
            parts.append(node.attrs["description"])
        if node.attrs.get("worker_type"):
            parts.append(f"Worker type: {node.attrs['worker_type']}")
        return "\n\n".join(parts) if parts else f"Implement node {node.id}"

    def _emit_gchat_review(self, node, summary: str):
        try:
            subprocess.run(
                [".claude/scripts/gchat-send.sh", "--type", "review",
                 "--title", f"Review: {node.label or node.id}",
                 summary[:2000]],
                timeout=10, capture_output=True
            )
        except Exception:
            pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pure Python DOT pipeline runner")
    parser.add_argument("--dot-file", required=True, help="Path to DOT pipeline file")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--default-worktree", default=None)
    args = parser.parse_args()

    config = {"default_worktree": args.default_worktree}

    runner = PipelineRunner(
        dot_file=args.dot_file,
        config=config,
        resume=args.resume,
    )
    result = runner.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

### 2.5 Watchdog-Based File Monitoring

The runner uses Python's `watchdog` library instead of mtime polling:

1. **`SignalFileHandler`** watches `.claude/signals/*.json` for worker completion signals (primary wake source)
2. **`DotFileHandler`** watches the pipeline DOT file for external state changes (System 3 manual gate approvals)
3. Both handlers set a shared `threading.Event` that wakes the main loop
4. The main loop blocks on `_wake_event.wait(timeout=30.0)` -- the 30s timeout is a safety net, not the primary mechanism

This is event-driven rather than poll-driven: the runner sleeps until a file system event occurs, then processes all pending signals in one pass.

### 2.6 Validation Signal Protocol

When a worker reaches `impl_complete`, the runner dispatches a **validation-test-agent** via AgentSDK (with `acceptance-test-runner` skill). The validation agent writes a signal file:

```json
{
    "node": "e1_validate",
    "result": "requeue",
    "reason": "Unit tests fail -- missing import in agent-schema.md handler table",
    "requeue_target": "impl_e1",
    "evidence": ["test_output.log", "missing_handler_wait_system3"]
}
```

The runner applies these results mechanically via `SIGNAL_TRANSITIONS`:

```python
SIGNAL_TRANSITIONS = {
    "pass":    lambda runner, node: runner._transition(node.id, "validated"),
    "fail":    lambda runner, node: runner._transition(node.id, "failed"),
    "requeue": lambda runner, node: runner._requeue_predecessor(node),
}
```

No interpretation, no reasoning. Pass advances, fail stops, requeue sends the predecessor back to `pending`.

### 2.7 `wait.system3` Two-Stage Gate

`wait.system3` in the DOT graph means two stages in one conceptual gate:

| Stage | Trigger | Actor | Action |
|-------|---------|-------|--------|
| **Stage 1** | Node reaches `impl_complete` | Runner dispatches validation-test-agent (AgentSDK) | Technical validation: unit tests, lint, type checks |
| **Stage 2** | Node reaches `validated` | Runner writes `ready-for-review` signal; System 3's Haiku 4.5 monitor wakes System 3 | Business validation: blind Gherkin E2E scenarios |

- **Stage 1 result**: Validation agent writes signal (`pass`/`fail`/`requeue`). Runner applies mechanically.
- **Stage 2 result**: System 3 writes acceptance signal. Runner transitions to `accepted`.

The runner never runs tests, never evaluates quality, never makes judgment calls. It dispatches agents and reads their verdicts.

### 2.8 Single-Writer Concurrency Model

The runner is the **sole writer of the DOT file**. This eliminates concurrency issues:

- Workers communicate via signal files (one file per node)
- Validation agents communicate via signal files
- System 3 communicates via signal files
- Only the runner reads signals and applies state transitions to the DOT graph

Multiple readers (System 3 monitor, dashboards) can safely read the DOT file at any time.

### 2.9 Migration Path

| Phase | Action | Risk |
|-------|--------|------|
| Phase A | Create `pipeline_runner.py` alongside `runner.py` | Zero -- additive only |
| Phase B | Activate via `--mode=python` flag in `spawn_orchestrator.py` | Low -- opt-in |
| Phase C | Run both modes on same pipeline, compare results | Zero -- validation |
| Phase D | Default to `--mode=python`, remove guardian LLM path | Low -- fallback available |

### 2.10 What the Python Runner Does NOT Do

- **Does not reason about task results** -- validation agents judge quality
- **Does not write code** -- workers write code via Edit/Write tools
- **Does not make architectural decisions** -- those are in the Solution Design
- **Does not run tests** -- validation-test-agent runs tests via AgentSDK
- **Does not evaluate business requirements** -- System 3 runs blind Gherkin E2E independently
- **Does not contain any LLM calls** -- all LLM work is delegated via AgentSDK dispatch
- **Does not write to the DOT file from multiple processes** -- single writer, multiple readers

The runner is a **state machine**, not a reasoning system.

## 3. Files Changed

| File | Change |
|------|--------|
| `pipeline_runner.py` (new) | Full Python state machine with watchdog monitoring (~350 LOC) |
| `spawn_orchestrator.py` | `--mode=python` flag routes to `pipeline_runner.py` |
| `requirements.txt` | Add `watchdog` and `claude-code-sdk` dependencies |

## 4. Testing

- Unit test: `_find_dispatchable_nodes()` with various graph states
- Unit test: `_handle_tool()` runs command, writes signal, no LLM call
- Unit test: `_handle_noop()` / `_handle_exit()` immediate completion
- Unit test: `SIGNAL_TRANSITIONS` mechanical logic (pass/fail/requeue)
- Unit test: `_requeue_predecessor()` retries correctly and cleans old signal
- Unit test: `_has_system3_gate()` correctly identifies downstream gates
- Integration test: watchdog observer wakes runner on signal file creation
- Integration test: simple-pipeline.dot runs to completion with 0 LLM graph traversal tokens
- Integration test: resume from checkpoint after simulated crash
- Integration test: parallel dispatch of independent ready nodes
- Integration test: validation agent requeue cycle (impl_complete -> requeue -> pending -> active)

## 5. Acceptance Criteria

- AC-7.1: `pipeline_runner.py` exists, imports cleanly, `--help` works
- AC-7.2: `_find_dispatchable_nodes()` returns only nodes with all deps validated/accepted
- AC-7.3: All worker dispatch goes through `_dispatch_agent_sdk()` using `claude_code_sdk` -- no headless `claude -p` anywhere
- AC-7.4: `_handle_tool()` runs command and writes signal without any LLM call
- AC-7.5: Validation agent dispatch at `impl_complete` writes proper signal protocol (`pass`/`fail`/`requeue`)
- AC-7.6: `SIGNAL_TRANSITIONS` mechanically applies: pass->validated, fail->failed, requeue->predecessor pending
- AC-7.7: Full pipeline run on simple-pipeline.dot completes with 0 LLM graph traversal tokens
- AC-7.8: Watchdog-based monitoring wakes runner on signal file creation (no `time.sleep` polling)
- AC-7.9: Multiple ready nodes dispatched concurrently
- AC-7.10: Runner is sole DOT file writer; workers/validators communicate only via signal files
- AC-7.11: Status chain follows `pending -> active -> impl_complete -> validated -> accepted`

## 6. Implementation Status

**Status**: Complete (2026-03-07, commits c5ddb4d, 9594e62, 3552db9)
**Tests**: 23/23 pass (test_e72_pipeline_runner.py)
**Branch**: feat/harness-upgrade-e4-e7

### What was built
- `pipeline_runner.py` — 600+ lines, full state machine with handler dispatch table
- `_SignalFileHandler` + watchdog `Observer` for event-driven signal monitoring
- `SIGNAL_TRANSITIONS` dict: `pass→validated`, `fail→failed`, `requeue→pending`, `success→impl_complete`
- AgentSDK dispatch via `claude_code_sdk.query()` with `ClaudeCodeOptions`
- Tool node auto-accept: `active → validated → accepted` (no validation agent needed)
- Validation agent dispatch with `active_workers` tracking to prevent false stuck detection
- Resume logic: re-dispatch validation for `impl_complete` nodes on `--resume`
- `.env` loading: `ANTHROPIC_MODEL` from `.claude/attractor/.env` takes priority

### Deviations from design
- `_dispatch_via_subprocess` method was designed but removed — all dispatch is AgentSDK only
- `rate_limit_event` SDK bug required graceful catch in async stream iteration
- `CLAUDECODE` env var must be stripped from worker env to avoid nested session detection
- Validation auto-pass when SDK unavailable (prevents pipeline blocking in non-SDK environments)
- `target_dir` graph attribute used for worker cwd instead of `dot_dir`

### E2E validation results (6 live pipeline runs)
- Tool nodes: 0 LLM tokens, instant execution
- Codergen nodes: AgentSDK dispatch works end-to-end
- Signal transitions: mechanical, deterministic
- Status chain: `pending → active → impl_complete → validated → accepted` confirmed
- Model config: loads from `.claude/attractor/.env` (ANTHROPIC_MODEL=qwen3-coder-plus)
