# GAP-PRD-ATTRACTOR-SDK-001: Attractor SDK-Mode Architecture Alignment

## 1. Business Context

### 1.1 Problem Statement

The Attractor pipeline execution system was designed to work in two modes: tmux (interactive) and SDK (headless). While tmux mode functions correctly, **SDK mode is fundamentally broken** — it was never fully implemented despite being shipped as a supported feature in `launch_guardian.py`, `spawn_runner.py`, and `runner_agent.py`.

The root cause is that the SDK-mode execution path was bolted onto a tmux-centric architecture without redesigning the monitoring and worker-spawning layers to work without tmux sessions.

### 1.2 Current Architecture (Broken SDK Mode)

```
launch_guardian.py (Layer 0: Terminal)
  → guardian_agent.py (Layer 1: SDK headless Claude)
    → [Bash] spawn_runner.py --mode sdk (Layer 2: subprocess)
      → runner_agent.py (Layer 2: SDK headless Claude)
        → RunnerStateMachine._do_monitor_mode()
          → build_monitor_prompt() → capture_output.py --session orch-{node}
            ❌ FAILS: No tmux session exists in SDK mode
            → 10 cycles of tmux errors → FAILED → RUNNER_EXITED signal
```

**Failure chain** (confirmed via Logfire trace 2026-03-02):
1. Guardian spawns runner via `spawn_runner.py --mode sdk`
2. Runner enters `RunnerStateMachine` (correct, dot-file provided)
3. Monitor prompt tells LLM child to run `capture_output.py` (tmux-only)
4. `capture_output.py` fails — no tmux session `orch-codergen_g12` exists
5. `_do_monitor_mode()` only checks for "COMPLETED"/"FAILED" strings, not "CRASHED"
6. 10 rapid cycles (~25s each), all returning "IN_PROGRESS" → FAILED after max_cycles
7. RUNNER_EXITED signal written to impl repo signals dir (wrong location)
8. Guardian's `wait_for_signal` misses the signal, waits full 600s timeout
9. Guardian discovers signal on filesystem scan, respawns runner → same loop

### 1.3 Target Architecture (3-Layer Model)

The attractor-spec-reference.md defines a **single-threaded graph traversal engine** with pluggable handlers. The spec's `CodergenBackend` interface and `ManagerLoopHandler` (Section 4.5, 4.11) map to a **3-layer model** — no orchestrator needed:

```
Attractor Spec Concept          Our Implementation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Execution Engine                guardian_agent.py (drives DOT traversal)
CodergenBackend.run()           Runner spawns worker via Claude Agent SDK
                                  (claude_agent_sdk.query() with ClaudeAgentOptions)
ManagerLoopHandler              Guardian observe/steer/wait pattern
  - observe                     Runner monitors worker via SDK events
  - steer                       Guardian sends guidance signals
  - wait                        Pull-based signal protocol
Checkpoint                      cli.py checkpoint save
Context                         DOT node attributes + signal payloads
```

**Worker spawning approach**: Workers are launched via the **Claude Agent SDK** (`claude_agent_sdk.query()` with `ClaudeAgentOptions`). The SDK provides clean-room isolation via `setting_sources=None` (default) — workers inherit zero filesystem config (no MCP servers, hooks, or plugins from the harness). Required MCP tools are explicitly injected per worker type via `mcp_servers={}`. This eliminates the ~5-12K token overhead per worker that subprocess spawning would inherit from our harness config.

**Signal protocol**: Adopts pull-based signal semantics (inspired by gastown-comparison.md's GUPP pattern) — completion records written to stable paths that the Guardian polls, rather than push-based signaling. See sdk-vs-subprocess-analysis.md for the full decision rationale.

**Key insight**: The DOT pipeline IS the orchestration plan. Each codergen node already specifies `worker_type`, `acceptance` criteria, and the SD provides implementation details. An orchestrator layer that re-plans work is redundant. The runner reads the `worker_type` attribute from the DOT node and launches the corresponding specialist as a headless Claude Code session.

The **target architecture** for SDK mode:

```
launch_guardian.py (Layer 0: Terminal bridge)
  → guardian_agent.py (Layer 1: Headless Claude Code — PIPELINE DRIVER)
    │
    ├── For each codergen node:
    │   ├── Transition node → active
    │   ├── [Bash] spawn_runner.py --mode sdk --node {id} --worker-type {type}
    │   │     → runner_agent.py (Layer 2: RUNNER — headless Claude Code)
    │   │       ├── Phase A: SPAWN
    │   │       │     ├── Read worker_type from DOT node (passed via CLI)
    │   │       │     ├── Read node context (acceptance, SD path)
    │   │       │     ├── Launch worker as headless Claude Code session
    │   │       │     │     → Worker (Layer 3: Specialist implementer)
    │   │       │     │       e.g., backend-solutions-engineer, frontend-dev-expert
    │   │       │     └── Record process handle for monitoring
    │   │       ├── Phase B: MONITOR worker by polling:
    │   │       │     - Process alive? (pid check)
    │   │       │     - stdout log growing? (file stat)
    │   │       │     - Git commits appearing? (git log)
    │   │       ├── Phase C: On worker completion:
    │   │       │     - Transition codergen node → impl_complete
    │   │       │     - Spawn independent validation worker
    │   │       │     - On PASS: transition node → validated, signal guardian
    │   │       │     - On FAIL: collect Seance context, spawn remediation worker
    │   │       ├── Phase D: SIGNAL guardian when:
    │   │       │     - NODE_VALIDATED: validation passed
    │   │       │     - NODE_FAILED: validation failed after max retries
    │   │       │     - NEEDS_INPUT: AskUserQuestion detected
    │   │       │     - WORKER_STUCK: no progress for threshold
    │   │       │     - WORKER_CRASHED: process exited non-zero
    │   │       └── Phase E: RELAY guardian responses to worker
    │   │
    │   ├── Wait for runner signal (pull-based polling)
    │   └── On NODE_VALIDATED: select next ready node
    │
    └── Pipeline complete → PIPELINE_COMPLETE signal to terminal
```

**Key architectural principles**:
1. **No orchestrator**: The runner launches specialist workers directly — the pipeline graph IS the orchestration plan
2. **Worker type in DOT graph**: The guardian sets `worker_type` on each node during pipeline creation; the runner reads it and spawns the corresponding specialist. If the guardian judges a change is needed, it modifies the DOT graph (LLM-first — no regex heuristics)
3. **Runner owns the full node lifecycle**: The runner spawns workers, monitors them via SDK streaming events, transitions nodes (active → impl_complete → validated), launches validation workers, and writes completion records for the guardian. The guardian only handles cross-node decisions (next node selection, retry strategy)
4. **All headless Claude Code**: Guardian, runner, and workers all run as headless Claude Code sessions via the SDK (`setting_sources=None` for worker isolation)
5. **Independent validation**: Validate nodes spawn a separate validation worker (not the same worker that implemented)
6. **Seance context recovery**: On retry, predecessor's git commits, notes, and error details are collected and passed to the fresh worker as additional context
7. **Explicit MCP injection**: Workers inherit nothing from harness config — required MCP tools (e.g., Context7, Beads) are explicitly specified per worker type

### 1.4 Success Criteria

- SDK-mode pipeline executes end-to-end without tmux dependency
- Guardian-runner-worker chain works for codergen nodes
- Runner monitors worker via non-tmux signals (process, files, git)
- Signal protocol works bidirectionally between guardian and runner
- Validate nodes use independent validation workers
- Existing tmux mode continues to function (no regression)

---

## 2. Gap Analysis

### Gap A: Runner Does Not Spawn Worker (CRITICAL)

**Current**: `spawn_runner.py` launches `runner_agent.py` which immediately enters monitoring mode. Nobody spawns a worker. In tmux mode, the guardian LLM happened to call `spawn_orchestrator.py` separately before calling `spawn_runner.py`, but this was implicit.

**Target**: Runner (Layer 2) should have an explicit SPAWN phase before MONITOR phase. In SDK mode, the runner reads the `worker_type` from the DOT node (passed via CLI), builds the worker prompt from the node context, and spawns the specialist as a headless Claude Code session.

**Files affected**: `spawn_runner.py`, `runner_agent.py`, new `worker_backend.py`

### Gap B: RunnerStateMachine Is 100% tmux-Coupled (CRITICAL)

**Current**: `RunnerStateMachine._do_monitor_mode()` calls `build_monitor_prompt()` which hardcodes `capture_output.py --session {session_name}`. The monitor checks:
- `capture_output.py` (tmux capture-pane)
- `check_orchestrator_alive.py` (tmux has-session)

All monitoring tools are tmux-specific. There is no SDK-mode monitoring path.

**Target**: RunnerStateMachine should have a mode-aware monitor that uses:
- **tmux mode**: existing `capture_output.py` + `check_orchestrator_alive.py`
- **SDK mode**: PID check, stdout log tail, git log, file-based progress indicators

**Files affected**: `runner_agent.py` (RunnerStateMachine, build_monitor_prompt), new `sdk_monitor.py`

### Gap C: RunnerStateMachine Status Handling Incomplete (HIGH)

**Current**: `_do_monitor_mode()` only checks for `"STATUS: COMPLETED"` and `"STATUS: FAILED"` in LLM output text. The monitor prompt defines 5 statuses (COMPLETED, STUCK, CRASHED, WORKING, NEEDS_INPUT) but only 2 are handled.

**Target**: All 5 status types should map to appropriate state transitions:
- COMPLETED → RunnerMode.COMPLETE
- FAILED → RunnerMode.FAILED
- CRASHED → Signal guardian, attempt respawn or RunnerMode.FAILED
- STUCK → Signal guardian with WORKER_STUCK
- NEEDS_INPUT → Signal guardian with NEEDS_INPUT, wait for response
- WORKING → Continue monitoring (current IN_PROGRESS behavior)

**Files affected**: `runner_agent.py` (RunnerStateMachine._do_monitor_mode)

### Gap D: Signal Directory Mismatch (HIGH)

**Current**: Runner writes signals to the impl repo's `.pipelines/signals/` directory. Guardian's `wait_for_signal.py` watches the harness repo's signals directory. They never find each other.

**Target**: Signal directory should be deterministic and shared. Options:
1. Both use `--signals-dir` pointing to same absolute path
2. Signals written to DOT file's directory (pipeline-scoped)

**Files affected**: `spawn_runner.py`, `wait_for_signal.py`, `signal_protocol.py`

### Gap E: No Independent Validation at Validate Nodes (MEDIUM)

**Current**: Guardian validates nodes directly via its LLM reasoning — essentially self-grading. In tmux mode, the guardian reads tmux output and makes a judgment call.

**Target**: Validate nodes should spawn an **independent validation worker** — a specialist (e.g., `tdd-test-engineer` or `validation-test-agent`) that reviews the implementation without knowledge of the implementer's self-assessment. This follows the guardian's skeptical-curiosity disposition: never trust self-reported success.

**Files affected**: `guardian_agent.py` (system prompt), new `validation_backend.py` or extension of `worker_backend.py`

---

## 3. Epics

### Epic 1: SDK Worker Backend (Gaps A + E-partial)

**Goal**: Create a `CodergenBackend` implementation (per Attractor spec Section 4.5) where the runner reads `worker_type` from the DOT node and spawns the corresponding specialist via the **Claude Agent SDK** (`claude_agent_sdk.query()` with `ClaudeAgentOptions`). No orchestrator layer — the DOT graph contains the worker selection (set by the guardian LLM). Workers run in clean-room isolation (`setting_sources=None`) with explicitly injected MCP tools per worker type.

**Acceptance Criteria**:
- AC-1.1: `worker_backend.py` implements the backend interface using Claude Agent SDK: accepts node context + worker_type, spawns headless Claude Code via `query(prompt, ClaudeAgentOptions(...))`, yields SDK streaming events for monitoring
- AC-1.2: Runner's SPAWN phase reads `worker_type` from CLI args (sourced from DOT node) before entering MONITOR phase
- AC-1.3: Worker receives a focused `system_prompt` (role definition) and task context via `prompt` parameter — separated per the SDK's native structure
- AC-1.4: Worker runs with `setting_sources=None` — zero inherited harness config. Required MCP tools explicitly specified per worker type via `mcp_servers={}`
- AC-1.5: Guardian sets `worker_type` on DOT nodes during pipeline creation; runner reads it via `spawn_runner.py --worker-type`. If guardian judges a change is needed, it modifies the DOT graph (LLM-first approach)
- AC-1.6: Supported worker types: `backend-solutions-engineer`, `frontend-dev-expert`, `tdd-test-engineer` — each with researched MCP tool requirements
- AC-1.7: Unit tests cover: happy path, crash handling (ProcessError), timeout (asyncio.wait_for)
- AC-1.8: MCP tool requirements documented per worker type (which tools each specialist needs)

### Epic 2: Mode-Aware Runner Monitor (Gaps B + C)

**Goal**: Redesign RunnerStateMachine to have separate monitoring strategies for tmux and SDK modes. SDK mode uses **pure SDK streaming events** — `AssistantMessage`, `ResultMessage`, typed exceptions (`ProcessError`, `TimeoutError`) — for worker health monitoring. No PID polling or file heartbeats in SDK mode.

**Acceptance Criteria**:
- AC-2.1: SDK-mode monitoring uses `async for message in query(...)` event stream: `AssistantMessage` for progress, `ResultMessage` for completion, `ProcessError` for crashes, `asyncio.TimeoutError` for stalls
- AC-2.2: `build_monitor_prompt()` generates mode-appropriate instructions (tmux: capture_output.py, SDK: event-stream-based — no external monitor script needed)
- AC-2.3: All 5 monitor statuses (COMPLETED, STUCK, CRASHED, WORKING, NEEDS_INPUT) are handled with correct state transitions
- AC-2.4: CRASHED (ProcessError) triggers pull-based completion record + possible respawn
- AC-2.5: NEEDS_INPUT detection via SDK event stream triggers signal record + wait for guardian response + relay to worker
- AC-2.6: Unit tests cover all status transitions, both modes

### Epic 3: Signal Protocol Alignment — Pull-Based Signals (Gap D)

**Goal**: Replace push-based signaling with **pull-based signal protocol** (inspired by gastown-comparison.md). Completion records are written to stable, pipeline-scoped paths that the Guardian polls. Records are committed to Git for durability across Guardian crashes.

**Acceptance Criteria**:
- AC-3.1: Signal directory is resolved from the DOT file path (e.g., `{dot_dir}/signals/`)
- AC-3.2: Completion records written to `signals/<node_id>/complete.json` (stable path, polled by Guardian)
- AC-3.3: Assignment records written to `signals/<node_id>/assigned.json` (pulled by Runner at start)
- AC-3.4: Signal files committed to Git for durability (survives Guardian crashes)
- AC-3.5: `wait_for_signal.py` polls stable paths instead of watching for pushed signals
- AC-3.6: Existing tmux-mode signal flow is not broken (regression test)
- AC-3.7: Integration test: runner writes completion record → guardian reads within 5s

### Epic 4: Guardian Baton-Passing, Independent Validation & Seance Context Recovery (Gap E)

**Goal**: Implement the spec's ManagerLoopHandler observe/steer/wait pattern for guardian↔runner coordination, with independent validation at validate nodes and **Seance-style context recovery** on retry (inspired by gastown-comparison.md).

**Acceptance Criteria**:
- AC-4.1: When implementation worker completes, **runner** transitions codergen node to `impl_complete` and spawns an independent validation worker
- AC-4.2: Validation worker is launched by the **runner** (not the guardian) via `worker_backend.py` with `worker_type=tdd-test-engineer` or `validation-test-agent`
- AC-4.3: Validation worker receives: acceptance criteria, implementation diff, test results — but NOT the implementation worker's self-assessment
- AC-4.4: On VALIDATION_PASSED, **runner** transitions node to `validated` and writes NODE_VALIDATED signal for the guardian
- AC-4.5: On VALIDATION_FAILED, **runner** collects **predecessor context** (Seance pattern): git commits from failed attempt, node-scoped notes, error details, and validation feedback
- AC-4.6: Predecessor context is passed as `additional_context` to the remediation worker — preventing contradictory implementation decisions on retry
- AC-4.7: Runner re-enters MONITOR mode after spawning remediation worker
- AC-4.8: Node-scoped `signals/<node_id>/notes.json` written by workers for mid-work observations (Seance recovery artifact)
- AC-4.9: End-to-end test: codergen node → impl_complete → independent validate → validated
- AC-4.10: End-to-end test: codergen node → FAIL → Seance context collected → remediation worker → re-validate

### Epic 5: Three-Layer Context Injection (Future — Leveraging Existing Agent Definitions)

**Goal**: Adopt Gastown's three-layer context injection pattern (ROLE / SKILLS DIGEST / TASK / IDENTITY) for worker spawning. Leverage existing `.claude/agents/` definitions as the ROLE layer and `.claude/skills/` as the SKILLS DIGEST source. Separate stable role identity from per-node task context to improve prompt caching and reduce token costs. Close the skills gap created by `setting_sources=None`.

**Acceptance Criteria**:
- AC-5.1: Worker role definitions sourced from existing `.claude/agents/*.md` files — no duplication of agent persona definitions
- AC-5.2: Role layer + Skills Digest (system_prompt) is stable per worker type — same across all nodes, enabling Anthropic prompt caching (~90% cost reduction on cached tokens)
- AC-5.3: Task layer (prompt parameter) contains only per-node context: acceptance criteria, SD section, target directory
- AC-5.4: Identity layer (env vars) provides `WORKER_NODE_ID`, `PIPELINE_ID`, `RUNNER_ID`, `PRD_REF` — zero token cost
- AC-5.5: MCP tool injection per worker type defined in a central config (extends AC-1.8 mapping)
- AC-5.6: Existing agent definitions in `.claude/agents/` are the source of truth for role content — `worker_backend.py` reads from these files rather than hardcoding persona strings
- AC-5.7: **Skills Digest** (Layer 1.5): Pre-computed skill content per worker type appended to system_prompt. Workers receive relevant skill patterns (e.g., `research-first` for backend, `react-best-practices` for frontend, `test-driven-development` for test engineers) without requiring the `Skill` tool or `setting_sources=["project"]`
- AC-5.8: Skills Digest mapping is configurable — `WORKER_SKILL_DIGESTS` dict maps worker types to lists of skill directories to include

**Note**: This epic depends on Epics 1-4 being stable. It is an optimization and architectural improvement on top of the working SDK-mode pipeline. The core SDK spawning (E1) should use simple inline personas first, then this epic refactors to the three-layer model with skills digest.

**Why not ****`setting_sources=["project"]`****?** Loading project settings gives workers skills but also inherits: stop gate hooks (blocks worker completion), orchestrator-detector hooks (confuses identity), all MCP servers (5K-12K token overhead), output styles (overrides focused persona), plugins (unnecessary for leaf workers). There is no selective "load just skills" option in the SDK.

---

## 4. Dependencies

```
Epic 3 (Signal Protocol — Pull-Based) → Epic 1 (Worker Backend — SDK) → Epic 2 (Monitor — SDK Events) → Epic 4 (Baton-Passing + Seance)
                                                                                                       ↓
                                                                                                  Epic 5 (Three-Layer Context — Future)
```

Epic 3 must land first because both Epic 1 and Epic 2 depend on correct signal routing.
Epic 4 depends on both Epic 1 (worker spawning exists) and Epic 2 (monitor works).
Epic 5 depends on Epic 4 (stable SDK pipeline) — it is an optimization, not a prerequisite.

---

## 5. Non-Goals

- Removing tmux mode (it continues to work alongside SDK mode)
- Implementing the full Attractor spec (parallel handlers, fan-in, etc.)
- Changing the DOT file format or CLI tools
- Adding an orchestrator layer in SDK mode (workers are launched directly)
- Modifying the guardian_agent.py system prompt structure (only content changes)

---

## 6. Risk Assessment

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Worker runs without enough context | Worker makes wrong implementation choices | System prompt must include PRD, SD section, and clear acceptance criteria |
| Wrong worker_type on DOT node | Implementation uses wrong specialist | Guardian LLM sets worker_type during pipeline creation; can modify DOT graph if needed (LLM-first, no heuristics) |
| Signal race conditions | Guardian and runner miss signals | Use filesystem polling with atomic writes (existing pattern) |
| Nested CLAUDECODE env var conflict | SDK child fails to start | Existing `env={"CLAUDECODE": ""}` workaround, plus Popen cleanup |
| tmux mode regression | Existing working mode breaks | Regression tests for tmux mode in each epic |
| Validation worker too strict/lenient | False positives/negatives on acceptance | Calibrate via acceptance criteria specificity in DOT nodes |
| SDK API stability | Claude Agent SDK had breaking changes v0.0.x→v0.1.x; API may evolve | Pin SDK version in requirements. `ClaudeAgentOptions` core interface (system_prompt, model, cwd, max_turns, setting_sources) is stable as of v1.0+. Monitor Anthropic changelog |
| Worker MCP tool requirements | Workers need specific MCP tools (Context7, Beads) but default `setting_sources=None` loads nothing | Define explicit `mcp_servers={}` config per worker type. Research required MCP needs per specialist before implementation |
| Pipeline state not advanced after worker completion | Workers complete but DOT nodes stay `active` — no state transition | Runner owns the full node lifecycle: monitors workers, transitions nodes (active → impl_complete → validated), launches validation workers, and signals guardian with pipeline-level results |

---

## 7. References

- attractor-spec-reference.md — Sections 3 (Execution Engine), 4.5 (CodergenBackend), 4.11 (ManagerLoopHandler), 5 (State/Context)
- sdk-vs-subprocess-analysis.md — Decision document: Claude Agent SDK primary for worker spawning
- gastown-comparison.md — Architectural comparison with Gastown, pull-based signal/Seance pattern adoption rationale
- Logfire trace 2026-03-02 — Guardian trace showing SDK-mode failure chain
- promise-7bfe8dc9.json — Detailed root cause analysis

---

## 8. Section 8: Epic Summary (for Task Master parsing)

### Epic 1: SDK Worker Backend
- Type: feature
- Priority: P0
- Depends on: Epic 3
- Files: new `worker_backend.py`, modify `spawn_runner.py`, modify `runner_agent.py`

### Epic 2: Mode-Aware Runner Monitor
- Type: feature
- Priority: P0
- Depends on: Epic 1
- Files: new `sdk_monitor.py`, modify `runner_agent.py` (RunnerStateMachine)

### Epic 3: Signal Protocol Alignment
- Type: bug-fix
- Priority: P0
- Depends on: none
- Files: modify `spawn_runner.py`, modify `wait_for_signal.py`, modify `signal_protocol.py`

### Epic 4: Guardian Baton-Passing, Independent Validation & Seance Context Recovery
- Type: feature
- Priority: P1
- Depends on: Epic 1, Epic 2
- Files: modify `guardian_agent.py` (system prompt), modify `runner_agent.py`, extend `worker_backend.py` with validation persona and Seance context collection

### Epic 5: Three-Layer Context Injection
- Type: enhancement
- Priority: P2
- Depends on: Epic 4
- Files: modify `worker_backend.py` (read from `.claude/agents/`), new MCP tool config per worker type, modify `spawn_runner.py` (env var identity layer)

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
