# PRD-S3-GUARDIAN-001: Guardian-Runner-Orchestrator Pipeline Architecture

**Status**: Draft
**Author**: System 3 + User collaborative design session
**Date**: 2026-02-24
**Priority**: P1
**Dependencies**: PRD-S3-ATTRACTOR-002 (pipeline runner, guardian, DOT tools — implemented)

---

## 1. Problem Statement

The current attractor pipeline execution is manually driven by System 3's interactive terminal session. System 3 reads DOT graphs, spawns orchestrators in tmux, monitors them via `tmux capture-pane`, and validates results — all within a single interactive context window. This creates several problems:

1. **Fragility**: If the terminal session runs out of context or crashes, all pipeline management state is lost
2. **No separation of concerns**: Strategic decisions (what to validate) and tactical monitoring (is the orchestrator progressing?) happen in the same context
3. **No autonomous execution**: The pipeline cannot progress without System 3 actively polling and making decisions
4. **Token waste**: Continuous polling burns tokens even when nothing has changed
5. **SDK race condition**: In-process MCP servers in `claude-code-sdk` 0.0.25 have a transport cleanup bug that prevents reliable agent-to-agent communication

## 2. Solution: 4-Layer Pipeline Architecture

Replace manual System 3 pipeline management with a formalized 4-layer hierarchy where each layer has clear responsibilities, communicates via structured signals, and can be independently restarted.

```
Layer 0: Interactive Terminal Guardian (ccsystem3)
    │   Human-facing: GChat, Hindsight, completion promises
    │   Launches and monitors Layer 1
    │
    ▼ Agent SDK (env -u CLAUDECODE)
Layer 1: Headless Guardian (Agent SDK subprocess)
    │   Pipeline execution engine: reads DOT, dispatches nodes
    │   Sleeps until Runner signals decision point
    │
    ▼ Agent SDK subprocess
Layer 2: Runner (Agent SDK)
    │   Tactical supervisor: monitors orchestrator via tmux
    │   Interprets output, escalates when needed
    │
    ▼ tmux session
Layer 3: Orchestrator (Claude Code + worker teams)
        Implementation: delegates to workers, writes code
```

### Key Design Principles

- **Each layer is independently restartable** — if Layer 1 crashes, Layer 0 spawns a new one
- **Intelligence at every layer** — no "dumb" regex parsing; each layer uses an LLM to interpret its child's output
- **Signal-driven, not polling-driven** — layers sleep until signaled, minimizing token burn
- **Project MCP servers available at all layers** — Hindsight, Beads, Brave Search, etc. work in Agent SDK subprocesses via `.mcp.json`
- **Custom tools via CLI scripts** — avoids the in-process MCP transport race condition in SDK 0.0.25

## 3. Architecture Detail

### 3.1 Layer 0: Interactive Terminal Guardian

**What it is**: The existing `ccsystem3` interactive terminal session with `system3-meta-orchestrator` output style and `s3-guardian` skill loaded.

**Responsibilities**:
- Launch Headless Guardian(s) via Agent SDK `query()` with `env -u CLAUDECODE`
- Handle escalations that require the actual human (GChat forwarding, AskUserQuestion)
- Manage completion promises and session lifecycle
- Access Hindsight for cross-session learning
- Restart Headless Guardian if it crashes or runs out of context
- Manage multiple Headless Guardians for parallel pipeline execution

**Tools available**: All existing — Hindsight, Beads, GChat Bridge, Serena, Brave, Perplexity, etc.

**Changes required**: Minimal — add a `launch_guardian()` helper that constructs the Agent SDK call.

### 3.2 Layer 1: Headless Guardian (Agent SDK)

**What it is**: A Claude Code subprocess launched via `query()` from the Interactive Terminal. It has no interactive UI — it communicates only through tool calls and signal files.

**Responsibilities**:
- Read pipeline DOT file, understand the full graph
- Identify ready nodes (pending + dependencies met)
- Spawn Runner for each ready codergen node
- Sleep/block until Runner signals a decision point
- Handle decision points:
  - **NEEDS_REVIEW**: Run validation-test-agent, approve/reject node
  - **NEEDS_INPUT**: Make the decision (it IS the "user" for layers below) or escalate to Layer 0
  - **VIOLATION**: Warn, restart, or kill the orchestrator
  - **ORCHESTRATOR_STUCK**: Send guidance or retry with different approach
  - **NODE_COMPLETE**: Transition node status, check if pipeline is done
- Transition node statuses in the DOT file
- Write checkpoints after each transition
- Signal Layer 0 when pipeline is complete or when it needs human input

**Custom CLI tools** (implemented as Python scripts in `.claude/scripts/attractor/guardian_tools/`):

| Tool Script | Purpose |
|-------------|---------|
| `spawn_runner.py` | Launch Runner as Agent SDK subprocess for a specific node |
| `wait_for_signal.py` | Block until a signal file appears in the signals directory |
| `read_signal.py` | Read and parse a signal file |
| `respond_to_runner.py` | Write a response file for the Runner to read |
| `escalate_to_terminal.py` | Write escalation signal for Layer 0 |

**MCP servers available**: All project MCP servers from `.mcp.json` (Hindsight, Beads, Brave, etc.) — loaded automatically by the spawned Claude Code subprocess.

**Allowed tools**: Custom CLI tools (via Bash) + Read/Grep/Glob (for reading DOT files, state) + project MCP tools. NOT Edit/Write (Guardian doesn't implement).

### 3.3 Layer 2: Runner (Agent SDK)

**What it is**: An Agent SDK subprocess launched by the Headless Guardian, responsible for a single pipeline node's lifecycle (spawn orchestrator, monitor, signal).

**Responsibilities**:
- Receive node assignment from Guardian (node_id, PRD ref, solution design, acceptance criteria)
- Spawn Orchestrator in tmux with full context extracted from DOT attributes
- Monitor Orchestrator via `tmux capture-pane` with intelligent interpretation
- Detect:
  - Completion: orchestrator finished all work
  - Errors: stack traces, repeated failures, no progress
  - Input needed: AskUserQuestion dialogs, permission prompts
  - Guard rail violations: orchestrator using Edit/Write directly
- Signal Guardian at decision points
- Relay Guardian decisions back to Orchestrator via `tmux send-keys`
- Track orchestrator token usage and context health

**Custom CLI tools** (implemented as Python scripts in `.claude/scripts/attractor/runner_tools/`):

| Tool Script | Purpose |
|-------------|---------|
| `spawn_orchestrator.py` | Create tmux session, inject output-style, send prompt |
| `capture_output.py` | tmux capture-pane with configurable line count |
| `send_to_orchestrator.py` | tmux send-keys to relay decisions/guidance |
| `signal_guardian.py` | Write signal file for Guardian to read |
| `wait_for_guardian.py` | Block until Guardian writes response file |
| `check_orchestrator_alive.py` | Verify tmux session still exists |

**MCP servers available**: All project MCP servers (for reading PRDs, solution designs, beads status).

**Allowed tools**: Custom CLI tools (via Bash) + Read/Grep/Glob + project MCP tools. NOT Edit/Write.

### 3.4 Layer 3: Orchestrator (Claude Code)

**What it is**: A standard Claude Code session in tmux with `orchestrator` output style and `orchestrator-multiagent` skill. Same as today's orchestrators.

**Responsibilities**:
- Receive specific work assignment: "Implement node X per PRD-Y section Z, solution design W"
- Create worker teams, delegate implementation
- Coordinate code changes across files
- Run tests, validate locally
- Commit work, report completion

**Changes required**: None — existing orchestrator infrastructure works as-is.

### 3.5 DOT Schema Extensions

Pipeline DOT nodes must carry enough information for the Runner to construct a complete orchestrator prompt.

**New node attributes** (added to codergen nodes):

| Attribute | Type | Required | Purpose |
|-----------|------|----------|---------|
| `prd_ref` | string | Yes | PRD document identifier (e.g., "PRD-AUTH-001") |
| `prd_section` | string | No | Specific section/epic within the PRD |
| `solution_design` | string | No | Path to solution design document |
| `target_dir` | string | No | Working directory for the orchestrator |
| `acceptance` | string | Yes | Acceptance criteria (already exists) |
| `bead_id` | string | Yes | Beads issue ID for tracking (already exists) |
| `worker_type` | string | Yes | Specialist agent type (already exists) |

**Example node with full attributes**:

```dot
impl_auth [
    handler="codergen"
    shape=box
    status="pending"
    bead_id="AUTH-042"
    worker_type="backend-solutions-engineer"
    prd_ref="PRD-AUTH-001"
    prd_section="Epic 2: JWT Authentication"
    solution_design=".claude/documentation/SOLUTION-DESIGN-AUTH.md"
    target_dir="zenagent/agencheck/agencheck-support-agent"
    acceptance="JWT auth with refresh tokens, unit tests pass, no hardcoded secrets"
    promise_ac="AC-2"
]
```

### 3.6 Signal Protocol

Layers communicate via JSON signal files in `.cobuilder/signals/`.

**Signal file naming**: `{timestamp}-{source_layer}-{target_layer}-{signal_type}.json`

**Example**: `20260224T120000Z-runner-guardian-NEEDS_REVIEW.json`

**Signal types (Runner → Guardian)**:

| Signal | When | Payload |
|--------|------|---------|
| `NEEDS_REVIEW` | Orchestrator completed node implementation | `{node_id, evidence_path, commit_hash}` |
| `NEEDS_INPUT` | Orchestrator asked a question / needs decision | `{node_id, question_text, options}` |
| `VIOLATION` | Orchestrator violated guard rails | `{node_id, violation_type, evidence}` |
| `ORCHESTRATOR_STUCK` | No progress detected for threshold period | `{node_id, last_output, duration_seconds}` |
| `ORCHESTRATOR_CRASHED` | tmux session died unexpectedly | `{node_id, last_output, exit_code}` |
| `NODE_COMPLETE` | Orchestrator finished and committed | `{node_id, commit_hash, summary}` |

**Signal types (Guardian → Runner)**:

| Signal | When | Payload |
|--------|------|---------|
| `VALIDATION_PASSED` | Guardian validated the node | `{node_id, new_status}` |
| `VALIDATION_FAILED` | Validation failed, retry needed | `{node_id, feedback, retry_count}` |
| `INPUT_RESPONSE` | Guardian made a decision for the orchestrator | `{node_id, response_text}` |
| `KILL_ORCHESTRATOR` | Guardian wants to abort and retry | `{node_id, reason}` |
| `GUIDANCE` | Guardian sending proactive guidance | `{node_id, message}` |

**Signal types (Guardian → Terminal)**:

| Signal | When | Payload |
|--------|------|---------|
| `PIPELINE_COMPLETE` | All nodes validated or failed | `{pipeline_id, summary}` |
| `ESCALATION` | Guardian can't handle, needs human | `{pipeline_id, issue, options}` |
| `GUARDIAN_ERROR` | Unrecoverable error | `{pipeline_id, error, stack_trace}` |

**Blocking wait mechanism**: `wait_for_signal.py` polls the signals directory every 5 seconds for files matching the expected pattern. When found, it reads, returns the content, and moves the file to `signals/processed/`.

## 4. Epics

### Epic 1: Signal Protocol and CLI Tools Foundation

Build the signal file protocol and the CLI tool scripts that all layers use to communicate.

**Deliverables**:
- Signal file reader/writer library (`signal_protocol.py`)
- Guardian CLI tools: `spawn_runner.py`, `wait_for_signal.py`, `read_signal.py`, `respond_to_runner.py`, `escalate_to_terminal.py`
- Runner CLI tools: `spawn_orchestrator.py`, `capture_output.py`, `send_to_orchestrator.py`, `signal_guardian.py`, `wait_for_guardian.py`, `check_orchestrator_alive.py`
- Unit tests for all tools
- Signal directory structure and cleanup

**Acceptance Criteria**:
- AC-1: `signal_guardian.py NEEDS_REVIEW --node impl_auth --evidence /path` creates a valid signal file
- AC-2: `wait_for_signal.py --source runner --timeout 30` blocks and returns when signal appears
- AC-3: `spawn_orchestrator.py --node impl_auth --prd PRD-AUTH-001 --worktree trees/auth` creates tmux session with output-style injected
- AC-4: `capture_output.py --session orch-impl-auth --lines 50` returns tmux pane content
- AC-5: All 11 CLI tools have `--help` and return valid JSON
- AC-6: Unit tests pass for signal_protocol.py (read, write, parse, move to processed)

### Epic 2: Runner Agent (Layer 2)

Build the Runner as an Agent SDK process that monitors an orchestrator and signals the Guardian.

**Deliverables**:
- Runner Agent SDK entry point (`runner_agent.py`)
- Runner system prompt (pipeline context, monitoring instructions)
- `ClaudeCodeOptions` configuration with CLI tools as allowed Bash commands
- tmux monitoring loop with intelligent output interpretation
- Signal emission on detected events (completion, stuck, violation, input needed)
- Guardian response relay back to orchestrator via tmux send-keys

**Acceptance Criteria**:
- AC-1: Runner launched via `query()` successfully monitors a tmux orchestrator session
- AC-2: Runner detects orchestrator completion and signals `NEEDS_REVIEW` to Guardian
- AC-3: Runner detects orchestrator stuck (no progress 5+ min) and signals `ORCHESTRATOR_STUCK`
- AC-4: Runner relays Guardian `INPUT_RESPONSE` to orchestrator via tmux send-keys
- AC-5: Runner detects tmux session death and signals `ORCHESTRATOR_CRASHED`
- AC-6: Runner correctly extracts DOT node attributes to construct orchestrator prompt (prd_ref, solution_design, acceptance, etc.)

### Epic 3: Headless Guardian Agent (Layer 1)

Build the Headless Guardian as an Agent SDK process that drives pipeline execution.

**Deliverables**:
- Guardian Agent SDK entry point (`guardian_agent.py`)
- Guardian system prompt (pipeline strategy, validation logic)
- `ClaudeCodeOptions` configuration with CLI tools + project MCP servers
- Pipeline reading and ready-node identification
- Runner spawning for codergen nodes
- Signal-driven decision loop (wait → handle → respond → wait)
- Node status transitions and checkpoint writing
- Validation dispatch (via validation-test-agent subprocess)
- Escalation to Layer 0 when human input needed

**Acceptance Criteria**:
- AC-1: Guardian reads DOT file and correctly identifies dispatchable nodes
- AC-2: Guardian spawns Runner for a codergen node with correct context
- AC-3: Guardian blocks on `wait_for_signal.py` and wakes when Runner signals
- AC-4: Guardian handles `NEEDS_REVIEW` by running validation and transitioning node status
- AC-5: Guardian handles `NEEDS_INPUT` by making a decision and responding to Runner
- AC-6: Guardian writes checkpoint after each node transition
- AC-7: Guardian signals `PIPELINE_COMPLETE` to Layer 0 when all nodes are terminal
- AC-8: Guardian escalates to Layer 0 when it cannot resolve an issue autonomously

### Epic 4: DOT Schema Extensions and Validator Updates

Extend the DOT schema to support the new node attributes and update the validator.

**Deliverables**:
- Updated `parser.py` to recognize new attributes (`prd_section`, `solution_design`, `target_dir`)
- Updated `validator.py` with rules for required attributes on codergen nodes
- Updated `generate.py` to populate new attributes from beads/PRD data
- Updated `cli.py node add/modify` to support new attributes
- Updated schema documentation

**Acceptance Criteria**:
- AC-1: `parser.py` extracts `prd_section`, `solution_design`, `target_dir` from DOT nodes
- AC-2: `validator.py` warns if codergen node is missing `prd_ref` or `acceptance`
- AC-3: `cli.py node add --set prd_ref=PRD-AUTH-001 --set solution_design=path` works
- AC-4: `generate.py` auto-populates `prd_ref` from graph-level attribute when creating nodes
- AC-5: Existing pipelines pass validation (backward compatible)

### Epic 5: Interactive Terminal Integration (Layer 0)

Connect the Interactive Terminal Guardian to the Headless Guardian via Agent SDK.

**Deliverables**:
- `launch_guardian.py` helper script for constructing Agent SDK calls
- Terminal monitoring loop for Headless Guardian health
- Escalation handling (receive signal, forward to user via AskUserQuestion/GChat)
- Crash recovery (detect Guardian subprocess exit, restart with state)
- Multi-pipeline support (launch multiple Headless Guardians in parallel)
- Updated `s3-guardian` skill with Layer 0 workflow

**Acceptance Criteria**:
- AC-1: Interactive Terminal launches Headless Guardian via `env -u CLAUDECODE` + `query()`
- AC-2: Terminal detects Guardian `PIPELINE_COMPLETE` signal and processes it
- AC-3: Terminal handles Guardian `ESCALATION` by forwarding to user via GChat
- AC-4: Terminal detects Guardian crash and restarts with preserved pipeline state
- AC-5: Terminal can run 2+ Headless Guardians for different pipelines simultaneously
- AC-6: Updated s3-guardian SKILL.md documents the 4-layer architecture and launch flow

### Epic 6: E2E Integration Test

End-to-end test that exercises all 4 layers on a minimal test pipeline.

**Deliverables**:
- Minimal test DOT with 1 codergen node + 1 validation gate
- E2E test script that launches Guardian, verifies Runner spawns, orchestrator executes, validation passes
- Test uses real Agent SDK calls (marked as slow/integration)
- Documents the full signal flow with timestamps

**Acceptance Criteria**:
- AC-1: E2E test launches Headless Guardian on test DOT
- AC-2: Guardian spawns Runner, Runner spawns Orchestrator in tmux
- AC-3: Orchestrator implements a trivial task (e.g., create a file with specific content)
- AC-4: Runner detects completion, signals Guardian
- AC-5: Guardian validates result, transitions node to `validated`
- AC-6: Guardian signals `PIPELINE_COMPLETE`
- AC-7: Full signal flow logged with timestamps for debugging

## 5. Non-Goals

- **Replacing the existing orchestrator infrastructure** — Layer 3 orchestrators work as-is
- **Building a distributed system** — all layers run on the same machine, communicate via filesystem
- **Real-time streaming** — signal files with 5s polling is sufficient latency
- **Multi-machine support** — single-developer workstation only
- **SDK bug fix** — the `claude-code-sdk` 0.0.25 MCP transport race condition is avoided by using CLI tools instead of in-process MCP servers

## 6. Technical Risks

| Risk | Mitigation |
|------|------------|
| Agent SDK subprocess nesting (`env -u CLAUDECODE`) may have undiscovered issues | Epic 6 E2E test validates the full 4-layer chain |
| Token cost of 4 intelligent layers | Layers 0 and 1 are mostly idle; cost is dominated by Layer 3 (implementation) |
| Signal file race conditions (write during read) | Atomic write-then-rename pattern; reader retries on parse failure |
| Orchestrator output interpretation requires intelligence | Runner is an Agent SDK process with full LLM reasoning |
| Context exhaustion at any layer | Each layer is independently restartable; state persisted via checkpoints/signals |

## 7. Success Metrics

- Pipeline execution proceeds autonomously after Layer 0 launches Layer 1
- Human intervention only required for business-level decisions (approval gates)
- Failed nodes are automatically retried with feedback (up to 3 retries)
- Full pipeline execution logged with audit trail for post-mortem analysis
- E2E test passes reliably on a trivial pipeline

## 8. Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| `claude-code-sdk` 0.0.25+ | Installed | CLI tools avoid in-process MCP race condition |
| Existing attractor CLI tools | Implemented (PRD-S3-ATTRACTOR-002) | `cli.py status`, `transition`, `validate`, `checkpoint` |
| Existing orchestrator infrastructure | Implemented | tmux spawn, output-style injection, worker teams |
| Signal directory writable | Runtime | `.cobuilder/signals/` must exist |
