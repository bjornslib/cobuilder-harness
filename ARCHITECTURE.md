# Claude Code Harness Architecture

Visual guide to understanding how the harness works across multiple projects.

## The Symlink Concept

```
┌──────────────────────────────────────────────────────────────────┐
│  ~/claude-harness (Central Repository)                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  .claude/                                                   │  │
│  │  ├── output-styles/    ← Agent behaviors                   │  │
│  │  ├── skills/           ← 20+ capabilities                  │  │
│  │  ├── hooks/            ← Lifecycle automation              │  │
│  │  ├── scripts/          ← CLI utilities + Attractor         │  │
│  │  └── settings.json     ← Base configuration                │  │
│  │                                                             │  │
│  │  cobuilder/            ← Orchestration Python package      │  │
│  │  .mcp.json             ← Your API keys                     │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
        ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
        │  Project A    │  │  Project B    │  │  Project C    │
        │               │  │               │  │               │
        │  .claude ─────┼──│  .claude ─────┼──│  .claude ─────┼──► All point to
        │     (symlink) │  │     (symlink) │  │     (symlink) │    central harness
        │               │  │               │  │               │
        │  .mcp.json ───┼──│  .mcp.json ───┼──│  .mcp.json    │
        │     (symlink) │  │     (symlink) │  │     (copy)    │◄── Can be copied
        │               │  │               │  │               │    for custom MCP
        └───────────────┘  └───────────────┘  └───────────────┘

        Update once in           All projects get updates automatically
        central harness    ──────────────────────────────────────────►
```

## Agent Architecture (3-Layer Hierarchy)

The harness implements a **3-layer hierarchy** where higher levels coordinate
and lower levels execute. This separation ensures isolation, testability, and
clear ownership:

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 0: SYSTEM 3 (S3 Guardian - User's Terminal)              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Strategic planning, OKR tracking, acceptance tests     │  │
│  │  • Writes blind Gherkin tests (before implementation)     │  │
│  │  • Creates DOT pipelines with research + codergen nodes   │  │
│  │  • Launches pipeline_runner.py (pure Python, no LLM)      │  │
│  │  • Post-pipeline blind validation (Phase 4 of cobuilder-guardian)│  │
│  │  • UUID-based completion promises (multi-session aware)   │  │
│  │                                                            │  │
│  │  Skills: cobuilder-guardian/, completion-promise          │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              │ Launches with --dot-file          │
│                              ▼                                   │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 1: PIPELINE RUNNER (Pure Python State Machine)           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Zero LLM intelligence — mechanical state machine       │  │
│  │  • Parses DOT files, tracks node states                   │  │
│  │  • Dispatches workers via AgentSDK (not subprocess)       │  │
│  │  • Watches signal files (atomic writes, timeout detection)│  │
│  │  • Auto-detects dead workers (AdvancedWorkerTracker)      │  │
│  │  • Auto-dispatches validation agents at impl_complete     │  │
│  │  • Transitions: pending → active → impl_complete →        │  │
│  │                validated | failed                         │  │
│  │  • Checkpoints pipeline state mechanically                │  │
│  │                                                            │  │
│  │  Active: .claude/scripts/attractor/pipeline_runner.py     │  │
│  │  Cost: $0 (no LLM tokens)                                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              │ Dispatches via AgentSDK           │
│                              ▼                                   │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2: WORKERS (Standalone AgentSDK Queries)                 │
│  ┌───────────────┬───────────────┬───────────────────────────┐  │
│  │ Frontend Dev  │ Backend Eng   │ TDD Test Engineer        │  │
│  │               │               │ + Validation Agent       │  │
│  │ • React/Next  │ • Python/API  │ • Write tests first      │  │
│  │ • Zustand     │ • PydanticAI  │ • Technical validation   │  │
│  │ • Tailwind    │ • Supabase    │ • Business validation    │  │
│  │ • Edit/Write  │ • Edit/Write  │ • Signal result files    │  │
│  └───────────────┴───────────────┴───────────────────────────┘  │
│                              │                                   │
│  Each worker = standalone claude_code_sdk.query() call           │
│  (NOT Native Agent Teams — no TeamCreate/Teammate/SendMessage)  │
│                              │                                   │
│                              │ Write signal files                │
│                              ▼                                   │
│                   .claude/signals/{node}.json                    │
│                   {result: "pass"|"fail"|"requeue"}              │
└─────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Layer 0 (System 3)**: LLM-driven strategy, business judgment, independent validation
2. **Layer 1 (Runner)**: Deterministic automation, zero LLM tokens, mechanical state transitions
3. **Layer 2 (Workers)**: Focused implementation via standalone `claude_code_sdk.query()`, reporting via signal files, never self-grading

**Key principle**: The implementer (Layer 2) never validates its own work.
- Runner (Layer 1) detects completion via signals
- Validation agent (Layer 2 peer) provides independent technical/business gating
- System 3 (Layer 0) runs blind Gherkin E2E tests post-pipeline

## CoBuilder Package

The `cobuilder/` Python package formalises the orchestration patterns that
were previously implicit in harness scripts. It implements the **4-layer SDK
pipeline engine** with pure Python state machine dispatch (Layer 1):

```
cobuilder/
├── orchestration/              ← Agent coordination layer (older LLM-based runner)
│   ├── pipeline_runner.py      ← LLM-based runner (anthropic.Anthropic().messages.create())
│   │                           ← Plan-only + execute modes, 9 tool definitions
│   │                           ← NOT the active dispatch path (see .claude/scripts/attractor/)
│   ├── identity_registry.py    ← Tracks agent identities across sessions
│   ├── spawn_orchestrator.py   ← Programmatic worker spawning (tmux mode)
│   ├── runner_hooks.py         ← Hook lifecycle management
│   ├── runner_models.py        ← Data models for pipeline state
│   ├── runner_tools.py         ← Tool wrappers for workers
│   └── adapters/
│       ├── native_teams.py     ← Native Agent Teams adapter (unused by active runner)
│       └── stdout.py           ← Stdout capture adapter
│
├── engine/                     ← **NEW (Epic E7.2)**: Observable pipeline engine
│   ├── runner.py               ← EngineRunner: event bus + middleware chains (35K lines)
│   ├── checkpoint.py           ← Persistent state tracking (19K)
│   ├── parser.py               ← DOT parsing with quote-aware regex (25K)
│   ├── parser_utils.py         ← Quote tracking, escape handling
│   ├── events/                 ← Event bus pattern (Epic 4)
│   │   ├── emitter.py          ← Single-instance emitter per run
│   │   ├── dispatcher.py       ← Event routing
│   │   └── lifecycle.py        ← Session lifecycle events
│   ├── middleware/             ← Logging, token counting, retry, audit chains
│   │   ├── logfire.py          ← Pydantic Logfire integration
│   │   ├── token_counter.py    ← Token usage tracking
│   │   ├── retry.py            ← Exponential backoff retry logic
│   │   └── audit.py            ← Audit trail logging
│   ├── conditions/             ← Conditional gate logic
│   │   ├── evaluator.py        ← Condition evaluation
│   │   └── policies.py         ← Loop detection, restart handling
│   ├── handlers/               ← Handler registry + base handler
│   │   ├── handler_registry.py ← Registration by name
│   │   ├── base_handler.py     ← Abstract handler interface
│   │   ├── codergen.py         ← Implementation node handler
│   │   ├── research.py         ← Research node handler
│   │   ├── refine.py           ← Refinement node handler
│   │   └── validation/         ← **NEW**: Validation rules engine
│   │       ├── rules.py        ← Node type, edge, attribute validation (27K lines)
│   │       ├── advanced_rules.py ← Complex rules: deadlock, reachability, liveness (16K)
│   │       └── validator.py    ← Validation entry point (6K)
│   └── utils/                  ← Utilities: clock, signal files, paths
│       ├── clock.py            ← time.monotonic() for timeouts (not time.time())
│       ├── signal_writer.py    ← Atomic signal writes (tmp→rename)
│       └── paths.py            ← Signal directory conventions
│
├── pipeline/                   ← Pipeline stage implementations
│   ├── generate.py             ← Code generation stage
│   ├── validate.py             ← Validation stage (dual-pass: technical + business)
│   ├── checkpoint.py           ← Save/restore pipeline state
│   ├── dashboard.py            ← Real-time progress display
│   ├── signal_protocol.py      ← **Signal format spec**: {status, result, message, files_changed}
│   ├── transition.py           ← State machine transitions (mechanical, no LLM)
│   └── ...                     ← node_ops, edge_ops, annotate, etc.
│
└── repomap/                    ← Repository mapping (from zerorepo)
    └── cli/                    ← CLI commands: init, sync, status
```

### Signal Protocol (Layer 1 ↔ Layer 2 Communication)

**Format**:
```json
// Worker completion
{"status": "success"|"failed", "files_changed": [...], "message": "..."}

// Validation result (technical + business gates)
{"result": "pass"|"fail"|"requeue", "reason": "...", "requeue_target": "node_id"}
```

**Status transitions**:
- `success` → queued for validation agent
- `failed` → pipeline stops, requires user intervention
- `requeue` → retry at specified node (predecessor back to pending)
- `pass` (validation) → `accepted`
- `fail` (validation) → blocked, requires System 3 intervention

**Atomic writes**: tmp file → rename (prevents partial writes if process crashes)

## Session Resilience System (Pipeline Runner Hardening)

The pipeline runner (`pipeline_runner.py`) was hardened across 7 epics (G, H, A, B, C, J, D-partial)
to survive worker crashes, signal corruption, validation timeouts, and forced restarts without
human intervention.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Pipeline Runner (.claude/scripts/attractor/pipeline_runner.py)   │
│                                                                   │
│  Epic H: AdvancedWorkerTracker ─ Tracks futures, detects death  │
│         │                                                         │
│         ├─ Main loop: _check_worker_liveness() each iteration   │
│         ├─ WorkerState enum: SUBMITTED → RUNNING → COMPLETED    │
│         │                    → FAILED / TIMED_OUT / CANCELLED   │
│         └─ Timeout: if elapsed > default_timeout (900s)         │
│            → future.cancel() → process_handle.terminate/kill()  │
│            → Auto-generate fail signal file                      │
│                                                                   │
│  Epic A: Atomic Signal Protocol ─ Crash-safe I/O                │
│         │                                                         │
│         ├─ Writes: tmp file (PID+monotonic_ns suffix) → rename  │
│         ├─ Metadata: _seq counter, _ts timestamp, _pid           │
│         ├─ Corruption: invalid JSON → quarantine/ (not dropped) │
│         └─ Ordering: _apply_signal() BEFORE os.rename() to      │
│            processed/ (crash between = safe, signal re-applied)  │
│                                                                   │
│  Epic B: force_status Persistence ─ Survives restarts           │
│         │                                                         │
│         ├─ _force_status() calls _do_transition() (disk write)  │
│         └─ Requeue guidance persists to signals/guidance/{id}.txt│
│                                                                   │
│  Epic C: Validation Error Handling ─ No silent hangs            │
│         │                                                         │
│         ├─ VALIDATION_TIMEOUT env var (default 600s)             │
│         ├─ asyncio.TimeoutError → writes fail signal             │
│         ├─ Generic Exception → writes fail signal with details   │
│         └─ No silent auto-pass on validation errors              │
│                                                                   │
│  Epic J: Validation Spam Suppression ─ Cost savings             │
│         │                                                         │
│         ├─ _dispatch_validation_agent() checks _get_node_status()│
│         └─ Skips dispatch for terminal nodes (validated/accepted/│
│            failed) — prevents duplicate validation + API waste   │
│                                                                   │
│  Epic D (partial): Orphan Resume ─ All handlers resumable       │
│         │                                                         │
│         └─ Exponential backoff (5s, 10s, 20s, max 60s)          │
│            Gate nodes emit escalation signals on repeated failure│
└──────────────────────────────────────────────────────────────────┘
```

### State Chain (Deterministic, No LLM)

```
pending
    │
    ├─ Dispatch worker (via AgentSDK)
    ▼
active
    │
    ├─ Wait for signal file OR timeout (Epic H: auto-detect dead workers)
    ├─ If signal: read {status, message, files_changed}
    ├─ If timeout: auto-generate fail signal (Epic H)
    ├─ If corrupted signal: quarantine, retry (Epic A)
    ▼
impl_complete (signal received: status=success)
    │
    ├─ Check if node already terminal → skip dispatch (Epic J)
    ├─ Auto-dispatch validation agent (VALIDATION_TIMEOUT env var, Epic C)
    │  (--mode=technical --mode=business)
    │
    └─ Wait for validation signal {result: "pass"|"fail"|"requeue"}
       ├─ pass → validated (persisted to DOT on disk, Epic B)
       ├─ fail → blocked (fail signal written, not silent, Epic C)
       └─ requeue → predecessor back to pending + guidance file (Epic B)
```

### Hardening Summary

| Epic | Problem | Solution | E2E Tests |
|------|---------|----------|-----------|
| **H** | Workers die silently, runner waits forever | `AdvancedWorkerTracker` with `WorkerInfo` dataclass, `_check_worker_liveness()` in main loop | 10 tests |
| **A** | Partial JSON writes = corrupted signals | Temp+rename atomic writes, `_seq` counter, quarantine dir, apply-before-consume ordering | 7 tests |
| **B** | `_force_status()` only updated memory, lost on restart | Now calls `_do_transition()` (disk write), requeue guidance persisted to `signals/guidance/` | 4 tests |
| **C** | Validation timeout/crash = silent hang | `VALIDATION_TIMEOUT` env var (600s), both TimeoutError and Exception write fail signals | 4 tests |
| **J** | Validation dispatched for already-terminal nodes | `_get_node_status()` guard before dispatch, skips validated/accepted/failed | 8 tests |
| **D** (partial) | Orphan nodes not resumable across all handler types | All handlers resumable with exponential backoff (5s→60s max) | - |

**33 E2E tests** covering all hardening features pass in 3.62s (`tests/e2e/test_pipeline_hardening.py`).

### Key Design Decisions

1. **`time.time()` for worker tracking**: `AdvancedWorkerTracker.submitted_at` and `_check_worker_liveness()` both use `time.time()` (wall clock) for consistency. The cobuilder engine's `clock.py` uses `time.monotonic()` separately.
2. **Quarantine over discard**: Corrupted signals are moved to `signals/quarantine/` rather than silently dropped, preserving forensic evidence.
3. **Apply-before-consume**: Signal transitions are applied to the DOT file BEFORE the signal is moved to `processed/`. A crash between apply and move is safe — the signal will be re-applied on restart.
4. **No silent auto-pass**: Prior to Epic C, validation errors could silently auto-pass. Now all errors write explicit fail signals with reason strings.

## SDK Pipeline Engine (Execution & Validation)

The pipeline engine executes DOT-based initiative pipelines through a
**2-phase validation model**: inline gating (Layer 1 runner dispatch) +
post-pipeline blind validation (Layer 0):

### Phase 1: Inline Validation (During Pipeline Execution)

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 0: System 3 (S3 Guardian — User's Terminal)               │
│  ├─ Creates DOT pipeline with research + codergen + validation  │
│  ├─ Launches pipeline_runner.py --dot-file <path>              │
│  └─ Waits for pipeline completion signal                        │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: PIPELINE RUNNER (Pure Python State Machine)           │
│  ├─ Parses DOT, dispatches workers via AgentSDK                │
│  ├─ On impl_complete signal:                                    │
│  │  ├─ Auto-dispatches validation-test-agent                   │
│  │  │  ├─ Phase 1a: Technical validation (--mode=technical)    │
│  │  │  │   • Unit tests, build, imports, TODOs                │
│  │  │  │   • Returns: TECHNICAL_PASS | TECHNICAL_FAIL         │
│  │  │  │                                                        │
│  │  │  └─ Phase 1b: Business validation (--mode=business)     │
│  │  │      (only if Phase 1a passes)                           │
│  │  │      • PRD acceptance criteria matrix                    │
│  │  │      • E2E journey tests, user flows                     │
│  │  │      • Returns: BUSINESS_PASS | BUSINESS_FAIL           │
│  │  │                                                            │
│  │  └─ Validation agent writes signal: {result: "pass"|"fail"} │
│  │                                                               │
│  └─ Node transitions: validated | failed (or requeue)          │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: WORKERS (Standalone claude_code_sdk.query() calls)    │
│  ├─ Codergen: Implement features, write code                   │
│  ├─ Research: Validate framework patterns pre-implementation   │
│  ├─ Refine: Improve based on validation feedback               │
│  └─ Validation: Independently gate work (dual-pass)            │
│                                                                   │
│  Each worker = isolated AgentSDK query with handler-specific   │
│  allowed_tools list (no cross-worker communication)             │
└─────────────────────────────────────────────────────────────────┘
```

### Phase 2: Post-Pipeline Blind Validation

After all pipeline nodes reach terminal state (all validated/failed/accepted):

```
S3 Guardian (Layer 0)
  │
  ├─ Run blind Gherkin E2E tests (from acceptance-tests/PRD-XXX/)
  │  (Guardian never saw the implementation-specific validation)
  │
  ├─ Score against rubric (gradient confidence: 0.0-1.0)
  │  • Feature completeness
  │  • Edge case handling
  │  • User journey coherence
  │  • Performance and reliability
  │
  └─ Verdict: ACCEPT | INVESTIGATE | REJECT
```

### Validation Architecture (Who Validates What)

```
Layer 2 (Workers)                   →  Implements, never validates own work
Layer 1 (Pipeline Runner)           →  Detects completion, auto-dispatches
                                        validation agents
Validation Agent (Layer 2 peer)     →  Dual-pass validation:
                                        1. Technical (tests, build, imports)
                                        2. Business (acceptance criteria)
                                        → Writes signal {result, reason}
Layer 0 (S3 Guardian)               →  Post-pipeline blind validation:
                                        Gherkin E2E tests + gradient scoring
```

**Key principle**: NO worker validates its own output. Validation is always:
1. A separate peer agent (inline phase)
2. An independent blind auditor (post-pipeline phase)

### DOT Pipeline Node Types

| Shape | Handler | Role | New Attributes |
| --- | --- | --- | --- |
| `Mdiamond` | `start` | Pipeline entry point | - |
| `tab` | `research` | Pre-implementation research gate — validates frameworks via Context7/Perplexity, updates SD | `downstream_node`, `solution_design`, `research_queries` |
| `box` | `tool` | Setup/teardown commands | `command`, `retry_count` |
| `parallelogram` | `parallel` | Fan-out / fan-in synchronization | - |
| `box` | `codergen` | Implementation node — dispatches worker via AgentSDK | `handler="codergen"`, `worker_type`, `sd_path`, `acceptance`, `bead_id` |
| `hexagon` | `wait.cobuilder` | Technical + business validation gates | `handler="wait.cobuilder"`, gates technical then business phases |
| `hexagon` | `wait.human` | Manual approval gate (not auto-gated by runner) | `handler="wait.human"` |
| `diamond` | `conditional` | Pass/fail routing based on signal result | `condition="pass"|"fail"`, `style=dashed` for retry edges |
| `Msquare` | `exit` | Pipeline finalization | - |

**Epic E7.2 Changes**:
- `codergen` nodes now specify `worker_type` (backend-solutions-engineer, frontend-dev-expert, tdd-test-engineer)
- `wait.cobuilder` is the inline validation gate (auto-dispatches validation agents at impl_complete)
- Validation agents signal result via `.claude/signals/{node}.json`
- Validation agent dispatched as separate standalone `claude_code_sdk.query()` (not in a team)

### Pipeline Dispatch: Pure Python (E7.2+)

**Default execution model** (as of 2026-03-07):

```
System 3 (ccsystem3)
  │
  └─ .claude/scripts/attractor/pipeline_runner.py --dot-file <path.dot>
     │
     ├─ Parses DOT graph (pure Python, zero LLM cost)
     ├─ Dispatches workers via standalone claude_code_sdk.query() calls
     │  async for msg in claude_code_sdk.query(
     │      prompt=...,
     │      options=ClaudeCodeOptions(
     │          system_prompt=..., allowed_tools=[...],
     │          permission_mode="bypassPermissions",
     │          model=worker_model, cwd=target_dir, max_turns=50
     │      )
     │  )
     │  (NOT Native Agent Teams, NOT subprocess, NOT tmux)
     │
     ├─ Watches .claude/signals/{node}.json via watchdog (atomic writes)
     │
     └─ Transitions state mechanically on signal arrival
        (pending → active → impl_complete → validated | failed)
```

**Legacy execution mode** (tmux, kept for compatibility):

The old `spawn_orchestrator.py --mode tmux` still works for manual orchestrator
sessions, but is no longer the default. It requires a real terminal.

**Why pipeline_runner.py is better** (E7.2 benefits):

| Aspect | tmux mode | pipeline_runner.py |
| --- | --- | --- |
| **Cost** | Implicit (orchestrator LLM) | $0 (pure Python) |
| **Speed** | Slow startup (terminal boot) | 10x faster (no LLM init) |
| **Reliability** | Manual restarts on crash | Auto-detects dead workers (Epic H) |
| **Observability** | tmux capture-pane parsing | Signal files + event bus + Logfire |
| **Validation** | Manual gate decisions | Auto-dispatch validation agents |

### deps-met Filter (Retry Edge Exclusion)

The `status.py --deps-met` filter finds nodes ready for dispatch by checking
that all upstream predecessors are validated. DOT pipelines include retry
back-edges (condition=fail, style=dashed) for failure recovery:

```dot
decision_vite_config -> impl_vite_config [condition="fail" style=dashed]
```

These edges are **excluded** from dependency calculation to prevent cycles.
Only forward-path edges (no `condition=fail`) count as real dependencies.

### Research Nodes (Pre-Implementation Gates)

Research nodes (`handler="research"`, `shape=tab`) are mandatory gates that run
BEFORE their downstream codergen nodes. They validate that the Solution Design's
framework patterns match current documentation, preventing orchestrators from
implementing against outdated APIs.

```
Pipeline Flow:
    start → research_auth → impl_auth → validate_auth → exit

Research Node Execution:
    1. Guardian reads the research node's attributes (downstream_node, solution_design, research_queries)
    2. Runs a lightweight SDK agent (Haiku, ~15s, ~$0.02) that:
       a. Reads the current Solution Design document
       b. Queries Context7 for each framework's current API patterns
       c. Cross-validates with Perplexity
       d. Updates the SD directly with validated patterns
       e. Writes evidence JSON to .claude/evidence/{node_id}/
       f. Persists learnings to Hindsight for future sessions
    3. Guardian transitions research node: pending → active → validated
    4. Downstream codergen node becomes dispatchable (--deps-met)
```

**Key design insight**: Research updates the SD directly — no side-channel
injection into runners or orchestrators. Since orchestrators already read the SD
as their implementation brief, they receive corrected patterns naturally.

**DOT attributes for research nodes**:

| Attribute | Required | Purpose |
| --- | --- | --- |
| `handler` | Yes | Must be `"research"` |
| `shape` | Yes | Must be `tab` |
| `downstream_node` | Yes | ID of the codergen node this research feeds |
| `solution_design` | Yes | Path to SD document to validate and update |
| `research_queries` | Recommended | Comma-separated frameworks to query (e.g., `"fastapi,pydantic,supabase"`) |
| `prd_ref` | Recommended | PRD reference for traceability |

**Known limitation**: Research validates against the latest published
documentation (Context7/Perplexity) but does not check the locally installed
version. For example, Context7 may return v1.63 API patterns while the local
environment has v1.58 installed, causing attribute name mismatches (e.g.,
`.data` vs `.output`). Mitigation: pin versions in the SD or add a local
version check step to the research prompt.

### Dogfood Validation: PRD-STORY-ZUSTAND-001

The 4-layer SDK pipeline was validated end-to-end by re-implementing the
Zustand store for the story-writer project:

| Metric | Result |
| --- | --- |
| Pipeline nodes | 22 (4 codergen + 8 validators + 4 decisions + 6 infrastructure) |
| Source files | 12 files, +764 lines |
| Tests | 28/28 passing |
| API turns | 99 |
| Cost | $9.00 |
| Duration | ~20 minutes |
| Self-healing events | 2 (worktree branch fix, deps-met workaround) |

Full pipeline executed: System 3 → pipeline_runner.py → AgentSDK workers.

### Dogfood Validation: PRD-PYDANTICAI-WEBSEARCH-E2E

The research node pattern was validated end-to-end with a PydanticAI web search
agent pipeline. This was the first pipeline to include a `handler="research"`
node running in full SDK mode (zero tmux).

| Metric | Result |
| --- | --- |
| Pipeline nodes | 5 (1 research + 1 codergen + 1 validator + 2 infrastructure) |
| Source files | 3 files (agent.py, graph.py, models.py) |
| Research duration | ~15s (Haiku model, ~$0.02) |
| SD updated | Yes — 4 framework findings, 5 gotchas added |
| All nodes validated | Yes — 5/5 reached `validated` status |
| Live execution | Successful web search via Brave Search API |

The research node validated pydantic-ai v1.63.0, pydantic-graph, and httpx
patterns against Context7/Perplexity, then updated the Solution Design with
current API patterns. The downstream codergen node read the corrected SD and
produced working Python files.

## Core Systems Integration

```
┌──────────────────────────────────────────────────────────────────┐
│  Task Master (PRD → Task Decomposition)                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  1. Parse PRD ─→ Generate tasks                            │  │
│  │  2. Analyze complexity ─→ Expand tasks                     │  │
│  │  3. Track status ─→ Next task recommendation              │  │
│  │  4. Sync to Beads ─→ Issue tracking                        │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  MCP Integration (9+ Servers)                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Sequential Thinking | Task Master | Context7 (Docs)       │  │
│  │  Perplexity | Brave Search | Serena | Hindsight | Beads    │  │
│  │  Chrome DevTools | GitHub | Playwright | More...           │  │
│  │                                                             │  │
│  │  Progressive Disclosure: Load only what's needed (90%↓)    │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

## Hooks System (Lifecycle Automation)

```
Session Lifecycle:
─────────────────

SessionStart
    │
    ├─→ Detect orchestrator mode
    ├─→ Load MCP skills registry
    └─→ Initialize session state

UserPromptSubmit (Before each user prompt)
    │
    └─→ Remind orchestrator of delegation rules

PostToolUse (After each tool execution)
    │
    └─→ Decision-time guidance injection

PreCompact (Before context compression)
    │
    └─→ Reload MCP skills (preserve after compaction)

Stop (Before session end — enforced at Guardian layer)
    │
    ├─→ Validate completion promise (UUID-based, multi-session)
    ├─→ Check open tasks
    ├─→ Confirm user intent to stop
    └─→ Allow/block stop based on state

Notification (On notifications)
    │
    └─→ Forward to webhook for external alerting
```

## Workflow: New Feature (E7.2+ Pipeline Model)

```
 1. User defines feature in PRD
        ↓
 2. System 3 writes blind Gherkin acceptance tests (cobuilder-guardian Phase 1)
        acceptance-tests/PRD-XXX/{feature}.feature
        ↓
 3. System 3 creates Solution Designs per epic (cobuilder-guardian Phase 2)
        docs/sds/{sd-name}.md ← detailed implementation brief
        ↓
 4. System 3 creates DOT pipeline with all node types (cobuilder-guardian Phase 3)
        start → research_X → codergen_X → wait.cobuilder → exit
        (research validates framework patterns before implementation)
        ↓
 5. System 3 launches pipeline_runner.py --dot-file <path> (E7.2)
        CoBuilder: EngineRunner with event bus + middleware chains
        ↓
 6. Runner dispatches research nodes (Haiku, ~15s each)
        Context7 + Perplexity → validate frameworks → update SD directly
        ↓
 7. Runner dispatches codergen workers via AgentSDK (NOT tmux, NOT subprocess)
        Workers receive Solution Design as part of system prompt
        Workers implement features, write code, commit changes
        ↓
 8. Worker signals completion (writes to .claude/signals/{node}.json)
        {"status": "success", "files_changed": [...], "message": "..."}
        ↓
 9. Runner auto-dispatches validation-test-agent at impl_complete
        Phase 1a: Technical validation (tests, build, imports, TODOs)
        Phase 1b: Business validation (acceptance criteria matrix, E2E)
        ↓
10. Validation agent writes result signal
        {"result": "pass"|"fail"|"requeue", "reason": "...", "requeue_target": "..."}
        ↓
11. Runner transitions node state mechanically
        impl_complete + pass → validated
        impl_complete + fail → blocked (requires System 3 intervention)
        impl_complete + requeue → predecessor back to pending
        ↓
12. All pipeline nodes reach terminal state (validated/failed/accepted)
        ↓
13. System 3 runs blind Gherkin E2E tests (Phase 4)
        Gherkin journey tests that were written BEFORE implementation
        Validation agent never saw these tests
        ↓
14. System 3 scores confidence gradient (0.0-1.0)
        Completeness, edge cases, user flows, performance
        ↓
15. Verdict: ACCEPT | INVESTIGATE | REJECT
        Feature complete (or gaps identified for fix-it nodes)
```

**Key differences from pre-E7.2 workflows**:
- Pure Python pipeline runner ($0 dispatch cost)
- Dual-pass inline validation (technical + business phases)
- Dead worker detection (Epic H: timeouts auto-kill stuck processes)
- Signal protocol for all agent-to-agent communication
- Solution Design wired into worker prompts (not passed as file path)
- Post-pipeline blind validation (Gherkin tests written before implementation)

## File Structure in Projects

```
your-project/
├── .claude/                    ─→ Symlink to ~/claude-harness/.claude
│   ├── output-styles/          ← Auto-loaded from harness
│   ├── skills/                 ← All skills available
│   ├── hooks/                  ← Lifecycle automation
│   ├── scripts/attractor/      ← **Active pipeline runner** (Layer 1)
│   │   └── pipeline_runner.py  ← Pure Python state machine + AgentSDK dispatch
│   ├── scripts/                ← CLI utilities
│   └── settings.json           ← Base configuration
│
├── cobuilder/                  ─→ Orchestration Python package
│   ├── orchestration/          ← Pipeline runner, identity, spawner
│   └── pipeline/               ← Generate, validate, checkpoint
│
├── .mcp.json                   ─→ Symlink or copy from harness
├── .claude/settings.local.json ─→ Project-specific overrides
└── your-code/                  ─→ Your actual application code
```

## Benefits Summary

| Aspect | Without Harness | With Harness |
| --- | --- | --- |
| Configuration | Copy to each project | Symlink once |
| Updates | Manual copying | `git pull` → all projects |
| Consistency | Drift over time | Always synchronized |
| Team sharing | Manual distribution | `git clone` → ready |
| Version control | Per-project chaos | Single source of truth |
| Resilience | Single-agent, fragile | Multi-session, identity-tracked |
| Pipeline state | Implicit / lost on crash | Checkpoint & resume via CoBuilder |
| Reliability | Manual restarts | Runner auto-restarts Orchestrators |

---

**Architecture Version**: 2.4.0
**Last Updated**: March 10, 2026
**Hardening**: SD-PIPELINE-RUNNER-HARDENING-001 (Epics G, H, A, B, C, J, D-partial)
