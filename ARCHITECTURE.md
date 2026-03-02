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

## Agent Architecture (SDK Mode)

The harness uses a **Guardian-led hierarchy** in SDK mode. Layers 0 and 1 have
collapsed into a single S3 Guardian role — the terminal-based session users
interact with directly.

```
┌─────────────────────────────────────────────────────────────────┐
│  S3 GUARDIAN (User-Facing Terminal Session)                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Strategic planning, OKR tracking, acceptance tests     │  │
│  │  • Validates business outcomes (stop hook at this layer)  │  │
│  │  • In SDK mode: spawns Runner → which spawns Orchestrator │  │
│  │  • Can also spawn another Guardian for monitoring         │  │
│  │  • UUID-based completion promises (multi-session aware)   │  │
│  │                                                            │  │
│  │  Skills: s3-guardian/, completion-promise                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              │ (SDK mode only)                   │
│                              ▼                                   │
├─────────────────────────────────────────────────────────────────┤
│  RUNNER (SDK Mode Only)                                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Manages orchestrator lifecycle and reliability         │  │
│  │  • Spawned by Guardian; does NOT run in tmux              │  │
│  │  • Provides fault-tolerant orchestrator execution         │  │
│  │  • Reports back to Guardian on completion or failure      │  │
│  │                                                            │  │
│  │  Package: cobuilder/orchestration/pipeline_runner.py      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              │ spawns                            │
│                              ▼                                   │
├─────────────────────────────────────────────────────────────────┤
│  ORCHESTRATOR                                                   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  • Feature coordination and task breakdown                │  │
│  │  • Investigate: Read/Grep/Glob                            │  │
│  │  • Delegate to workers via native Agent Teams             │  │
│  │  • NEVER: Edit/Write/MultiEdit directly                   │  │
│  │                                                            │  │
│  │  Skills: orchestrator-multiagent/                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                   │
│                              │ delegates via native teams        │
│                              ▼                                   │
├─────────────────────────────────────────────────────────────────┤
│  WORKERS (Specialists)                                          │
│  ┌───────────────┬───────────────┬───────────────────────────┐  │
│  │ Frontend Dev  │ Backend Eng   │ TDD Test Engineer        │  │
│  │               │               │                          │  │
│  │ • React/Next  │ • Python/API  │ • Write tests first      │  │
│  │ • Zustand     │ • PydanticAI  │ • Red-Green-Refactor     │  │
│  │ • Tailwind    │ • Supabase    │ • Browser validation     │  │
│  │ • Edit/Write  │ • Edit/Write  │ • API testing            │  │
│  └───────────────┴───────────────┴───────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Guardian → Runner Reliability Pattern

In SDK mode, the Guardian does not call the Orchestrator directly. Instead it
spawns a **Runner** subagent. This indirection dramatically increases
reliability: if an orchestrator crashes or stalls, the Runner can detect the
failure and restart it without the Guardian needing to intervene.

```
Guardian
  │
  ├── SDK mode ──► Runner ──► Orchestrator ──► Workers
  │                  │
  │                  └── On failure: restarts Orchestrator automatically
  │
  └── Monitor ──► Guardian (validation subagent, runs in background)
```

## CoBuilder Package

The `cobuilder/` Python package formalises the orchestration patterns that
were previously implicit in harness scripts:

```
cobuilder/
├── orchestration/              ← Agent coordination layer
│   ├── pipeline_runner.py      ← Manages full pipeline execution (Runner)
│   ├── identity_registry.py    ← Tracks agent identities across sessions
│   ├── spawn_orchestrator.py   ← Programmatic orchestrator spawning
│   ├── runner_hooks.py         ← Hook lifecycle management
│   ├── runner_models.py        ← Data models for pipeline state
│   ├── runner_tools.py         ← Tool wrappers for orchestrators
│   └── adapters/
│       ├── native_teams.py     ← Native Agent Teams adapter
│       └── stdout.py           ← Stdout capture adapter
│
├── pipeline/                   ← Pipeline stage implementations
│   ├── generate.py             ← Code generation stage
│   ├── validate.py             ← Validation stage
│   ├── checkpoint.py           ← Save/restore pipeline state
│   ├── dashboard.py            ← Real-time progress display
│   ├── signal_protocol.py      ← Agent-to-agent signalling
│   ├── transition.py           ← State machine transitions
│   └── ...                     ← node_ops, edge_ops, annotate, etc.
│
└── repomap/                    ← Repository mapping (from zerorepo)
    └── cli/                    ← CLI commands: init, sync, status
```

## Session Resilience System

```
┌──────────────────────────────────────────────────────────────────┐
│  Attractor System (.claude/scripts/attractor/ + cobuilder/)      │
│                                                                   │
│  IdentityRegistry ─── Tracks agent identities & health          │
│         │                                                         │
│  MergeQueue ──────── Serialises concurrent code changes          │
│         │                                                         │
│  HookManager ─────── Central hook dispatch (pre/post tool)       │
│         │                                                         │
│  SignalProtocol ──── Agent-to-agent messaging                    │
│         │                                                         │
│  GuardianAgent ───── Validation subagent (monitoring mode)       │
│         │                                                         │
│  RunnerAgent ─────── Executes pipeline stages (SDK mode only)    │
└──────────────────────────────────────────────────────────────────┘

Cyclic Validation Pattern (Guardian monitors Runner/Orchestrator):
────────────────────────────────────────────────────────────────────

Guardian                 Monitor Guardian               Orchestrator
   │                           │                              │
   │  Launch monitor ─────────►│                              │
   │                           │◄── Poll task state ──────────│
   │                           │    Validate work...          │
   │◄──── COMPLETE ────────────│                              │
   │  Handle result            │                              │
   │  Re-launch monitor ──────►│  (cycle repeats)             │
```

## SDK Pipeline Engine (4-Layer Chain)

The Attractor Pipeline Engine executes DOT-based initiative pipelines through a
4-layer chain. Each layer has a distinct responsibility:

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 0: Claude Code CLI (S3 Guardian — user's terminal)        │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  • User's ccsystem3 session — the S3 Meta-Orchestrator      ││
│  │  • Launches SDK chain via: launch_guardian.py (bootstrap)   ││
│  │  • Post-pipeline blind validation (Phase 4 of s3-guardian)  ││
│  │  • Scores against rubric the SDK Guardian never saw         ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  Layer 1: guardian_agent.py (Anthropic Claude Code SDK)           │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  • Uses claude_code_sdk.query() — Claude as subprocess      ││
│  │  • Reads DOT pipeline, advances bootstrap nodes             ││
│  │  • Dispatches research nodes (tab shape) BEFORE codergen:   ││
│  │    → Validates framework patterns via Context7/Perplexity   ││
│  │    → Updates Solution Design with current API patterns      ││
│  │    → Writes evidence to .claude/evidence/{node}/            ││
│  │  • Identifies dispatchable codergen nodes (--deps-met)      ││
│  │  • Spawns Runner agents (Layer 2) per codergen node         ││
│  │  • VALIDATES nodes after impl_complete:                      ││
│  │    → Technical gate (hexagon node): tests, imports, TODOs   ││
│  │    → Business gate (hexagon node): acceptance criteria       ││
│  │  • Transitions nodes: impl_complete → validated | failed    ││
│  │  • Checkpoints pipeline state after each transition         ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  Layer 2: runner_agent.py + spawn_runner.py                      │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  • Spawns orchestrator in tmux via spawn_orchestrator.py    ││
│  │  • Monitors tmux output for completion/error signals        ││
│  │  • Signals NEEDS_REVIEW to Guardian when impl_complete      ││
│  │  • Handles orchestrator respawn on crash (max 3 retries)    ││
│  │  • NO validation role — pure lifecycle management            ││
│  └─────────────────────────────────────────────────────────────┘│
│                              │                                   │
│                              ▼                                   │
│  Layer 3: Orchestrator + Workers (tmux + Agent Teams)            │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │  • Orchestrator: reads SD, delegates to workers              ││
│  │  • Workers: implement code, run tests, report completion     ││
│  │  • Marks node as impl_complete when done                     ││
│  │  • NO self-validation — implementer never grades own work    ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### Validation Architecture (Who Validates What)

```
Layer 3 (Orchestrator/Workers)       →  Implements, marks impl_complete
Layer 2 (Runner)                     →  Detects impl_complete, signals NEEDS_REVIEW
Layer 1 (SDK Guardian, claude_code_sdk) →  Independent validation per node:
                                          Tech gate → Business gate → validated/failed
Layer 0 (S3 Guardian, Claude Code CLI)  →  Post-pipeline blind validation:
                                          Scores against rubric the SDK Guardian never saw
```

**Key principle**: The implementer (Layer 3) never validates its own work.
The SDK Guardian (Layer 1, `claude_code_sdk`) validates during execution.
The S3 Guardian (Layer 0, the user's Claude Code CLI session) validates
independently afterward using the s3-guardian skill's Phase 4 protocol.

### DOT Pipeline Node Types

| Shape | Handler | Role |
| --- | --- | --- |
| `Mdiamond` | `start` | Pipeline entry point |
| `tab` | `research` | Pre-implementation research gate — validates frameworks via Context7/Perplexity, updates SD |
| `box` | `tool` | Setup/teardown commands |
| `parallelogram` | `parallel` | Fan-out / fan-in synchronization |
| `box` | `codergen` | Implementation node — spawns orchestrator |
| `hexagon` | `wait.human` | Validation gate (technical or business) |
| `diamond` | `conditional` | Pass/fail routing |
| `Msquare` | `exit` | Pipeline finalization |

### Execution Mode: SDK vs tmux

The `spawn_orchestrator.py` script supports two execution modes via `--mode`:

| Mode | When | Worktree Behavior |
| --- | --- | --- |
| `tmux` (default) | Manual S3 Guardian in terminal | `ccorch --worktree <node>` — creates isolated worktree |
| `sdk` | PydanticAI Guardian already in worktree | `ccorch` WITHOUT `--worktree` — reuses guardian's worktree |

**Why this matters**: In SDK mode, the Guardian already runs in a worktree
(created by `launch_guardian.py`). If `spawn_orchestrator.py` creates another
nested worktree, it branches from main's HEAD — not the Guardian's branch.
The `--mode sdk` parameter prevents this double-worktree problem.

The mode propagates through the full chain:
```
launch_guardian.py
  → guardian_agent.py (system prompt includes --mode sdk)
    → spawn_runner.py --mode sdk
      → runner_agent.py --mode sdk
        → spawn_orchestrator.py --mode sdk  ← skips --worktree
```

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

All 4 layers executed: `launch_guardian.py` → `guardian_agent.py` →
`runner_agent.py` → orchestrator/workers in tmux.

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

## Workflow: New Feature (SDK Mode)

```
 1. User defines feature in PRD
        ↓
 2. Guardian receives request; writes blind acceptance tests (s3-guardian)
        ↓
 3. Guardian parses PRD with Task Master
        PRD ─→ tasks.json ─→ Beads issues
        ↓
 4. Guardian creates DOT pipeline with research + codergen nodes
        start → research_X → impl_X → validate_X → exit
        ↓
 5. Research nodes execute (Haiku, ~15s each, synchronous)
        Context7 + Perplexity → validate framework patterns → update SD
        ↓
 6. Guardian spawns Runner per codergen node (SDK mode)
        CoBuilder: IdentityRegistry.register()
        CoBuilder: PipelineRunner.start()
        ↓
 7. Runner spawns Orchestrator (with automatic restart on failure)
        Orchestrator reads the research-corrected SD as its brief
        ↓
 8. Orchestrator investigates codebase
        Read/Grep/Glob, analyzes dependencies
        ↓
 9. Orchestrator delegates to Workers (native Agent Teams)
        ┌──────────────┬──────────────┬──────────────┐
        │ Frontend     │ Backend      │ TDD Engineer │
        │ Worker       │ Worker       │              │
        │              │              │              │
        │ Implements   │ Implements   │ Writes tests │
        │ UI           │ API          │ Validates    │
        └──────────────┴──────────────┴──────────────┘
        ↓
10. Workers report completion; CoBuilder MergeQueue serialises changes
        ↓
11. Guardian Monitor validates work (background subagent, cyclic pattern)
        Unit tests + API tests + E2E browser tests
        ↓
12. Guardian validates business outcomes against acceptance tests
        Feature complete! ✓
```

## File Structure in Projects

```
your-project/
├── .claude/                    ─→ Symlink to ~/claude-harness/.claude
│   ├── output-styles/          ← Auto-loaded from harness
│   ├── skills/                 ← All skills available
│   ├── hooks/                  ← Lifecycle automation
│   ├── scripts/attractor/      ← Session resilience scripts
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

**Architecture Version**: 2.2.0
**Last Updated**: March 2, 2026
