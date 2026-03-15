# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This is a **Claude Code harness setup** repository that provides a complete configuration framework for multi-agent AI orchestration using Claude Code. It contains configuration, skills, hooks, orchestration tools, and the **CoBuilder pipeline execution engine** (`cobuilder/`).

## Architecture

### 3-Level Agent Hierarchy

This setup implements a sophisticated multi-agent system with three distinct levels:

```
┌─────────────────────────────────────────────────────────────────────┐
│  LEVEL 1: SYSTEM 3 (Meta-Orchestrator)                              │
│  Output Style: cobuilder-guardian.md                                │
│  Skills: cobuilder-guardian/, completion-promise                    │
│  Role: Strategic planning, OKR tracking, business validation        │
├─────────────────────────────────────────────────────────────────────┤
│  LEVEL 2: ORCHESTRATOR                                              │
│  Output Style: orchestrator.md                                      │
│  Skills: orchestrator-multiagent/                                   │
│  Role: Feature coordination, worker delegation via native teams     │
├─────────────────────────────────────────────────────────────────────┤
│  LEVEL 3: WORKERS (native teammates via Agent Teams)                │
│  Specialists: frontend-dev-expert, backend-solutions-engineer,      │
│               tdd-test-engineer, solution-architect                 │
│  Role: Implementation, testing, focused execution                   │
└─────────────────────────────────────────────────────────────────────┘
```

**Key Principle**: Higher levels coordinate; lower levels implement.
- System 3 sets goals and validates business outcomes
- Orchestrators break down work and delegate to workers
- Workers execute focused tasks and report completion

### Launch Commands

| Level | Command | Purpose |
|-------|---------|---------|
| System 3 | `ccsystem3` | Launch meta-orchestrator with completion promises |
| Orchestrator | `launchorchestrator [epic-name]` | Launch in isolated worktree (via tmux) |
| Worker | `Task(subagent_type="...", team_name="...", name="...")` | Spawned as native teammate by orchestrator (team lead) |
| Pipeline | `python3 cobuilder/engine/pipeline_runner.py --dot-file <path.dot>` | Execute a DOT pipeline (zero LLM cost for runner) |
| Pipeline (resume) | `python3 cobuilder/engine/pipeline_runner.py --dot-file <path.dot> --resume` | Resume a pipeline from last checkpoint |

## Directory Structure

```
.claude/
├── CLAUDE.md                     # This configuration directory documentation
├── settings.json                 # Core settings (hooks, permissions, plugins)
├── settings.local.json           # Local overrides
├── output-styles/                # Automatically loaded agent behaviors
│   ├── orchestrator.md           # Level 2 orchestrator behavior
│   └── cobuilder-guardian.md         # Level 1 meta-orchestrator behavior
├── skills/                       # Explicitly invoked agent skills
│   ├── orchestrator-multiagent/  # Multi-agent orchestration patterns
│   ├── completion-promise/       # Session completion tracking
│   ├── mcp-skills/              # MCP server wrappers with progressive disclosure
│   └── [20+ additional skills]
├── hooks/                        # Lifecycle event handlers
│   ├── session-start-orchestrator-detector.py
│   ├── user-prompt-orchestrator-reminder.py
│   ├── unified-stop-gate.sh
│   └── unified_stop_gate/        # Stop gate implementation
├── scripts/                      # CLI utilities
│   └── completion-state/         # cs-* commands for session tracking
├── commands/                     # Slash commands
├── documentation/                # Architecture decisions and guides
│   ├── ADR-001-output-style-reliability.md
│   └── SYSTEM3_CHANGELOG.md
├── validation/                   # Validation agent configs
├── state/                        # Runtime state tracking
├── agents/                       # Agent configurations
└── tests/                        # Hook and workflow tests

cobuilder/                        # Pipeline execution engine (Python package)
├── engine/                       # Core runner, handlers, dispatch, signal protocol
│   ├── pipeline_runner.py        # Main DOT pipeline state machine (zero LLM)
│   ├── guardian.py               # Guardian agent launcher (Layers 0/1)
│   ├── session_runner.py         # Session monitoring runner (Layer 2)
│   ├── handlers/                 # Node handler implementations
│   │   ├── codergen.py           # box — LLM/orchestrator nodes
│   │   ├── manager_loop.py       # house — recursive sub-pipeline management
│   │   ├── wait_human.py         # diamond — human gate nodes
│   │   └── [base, close, conditional, exit, fan_in, parallel, start, tool]
│   ├── signal_protocol.py        # Atomic JSON signal file I/O
│   ├── providers.py              # LLM profile resolution (providers.yaml)
│   ├── dispatch_worker.py        # AgentSDK worker dispatch utilities
│   ├── dispatch_parser.py        # DOT file parsing utilities
│   ├── checkpoint.py             # Pydantic-based pipeline state checkpointing
│   ├── generate.py               # Pipeline DOT generation from beads tasks
│   ├── cli.py                    # Attractor CLI (parse/validate/status/transition/…)
│   ├── run_research.py           # Research node agent (Context7 + Perplexity)
│   ├── run_refine.py             # Refine node agent (rewrites SD from research)
│   └── .env                      # LLM credentials (DASHSCOPE_API_KEY, etc.)
├── templates/                    # Template instantiation system
│   ├── instantiator.py           # Jinja2 DOT template renderer
│   ├── constraints.py            # Static constraint validation
│   └── manifest.py               # Template manifest loader
└── repomap/                      # Codebase intelligence for context injection

.pipelines/                       # Runtime pipeline state (git-ignored)
├── pipelines/                    # DOT pipeline files and checkpoints
│   ├── *.dot                     # Active pipeline graphs
│   ├── *-checkpoint-*.json       # Periodic checkpoint snapshots
│   ├── signals/                  # Per-pipeline signal directories
│   │   └── {pipeline_id}/        # Worker result signals
│   └── evidence/                 # Validation evidence artifacts

.cobuilder/                       # Template library
└── templates/                    # Jinja2 DOT templates
    ├── sequential-validated/     # Linear pipeline with validation gates
    ├── hub-spoke/                # Fan-out parallel dispatch
    └── cobuilder-lifecycle/      # Full lifecycle pipeline (research → design → implement → validate)

cobuilder/engine/providers.yaml   # Named LLM profiles (shared config, lives next to providers.py)
```

## Core Systems

### 1. Output Styles vs Skills

**Critical Decision** (see ADR-001): Content is split by reliability requirements.

| Mechanism | Load Guarantee | Use For |
|-----------|----------------|---------|
| **Output Styles** | 100% (automatic) | Critical patterns, mandatory protocols, core workflows |
| **Skills** | ~85% (requires invocation) | Reference material, detailed guides, optional enhancements |

**Output styles are loaded automatically at session start**. Skills must be explicitly invoked using the `Skill` tool.

### 2. Task Master Integration

Task Master is used for task decomposition and tracking through the `/project:tm/` namespace.

**Common Commands**:
```bash
/project:tm/init/quick               # Initialize project
/project:tm/parse-prd <file>         # Generate tasks from PRD
/project:tm/next                     # Get next recommended task
/project:tm/list                     # List tasks with filters
/project:tm/set-status/to-done <id>  # Mark task complete
/project:tm/expand <id>              # Break down complex task
```

See `.claude/TM_COMMANDS_GUIDE.md` for complete command reference.

### 3. MCP Server Integration

The repository includes extensive MCP (Model Context Protocol) server integration:

**Available MCP Servers** (configured in `.mcp.json`):
- `sequential-thinking` - Multi-step reasoning
- `task-master-ai` - Task decomposition and management
- `context7` - Framework documentation lookup
- `perplexity` - Web research (4 tools: `perplexity_search`, `perplexity_ask`, `perplexity_research`, `perplexity_reason`)
- `brave-search` - Web search
- `serena` - IDE assistant patterns
- `hindsight` - Long-term memory (HTTP server on localhost:8888)
- `beads_dev:beads` - Issue tracking integration

**MCP Skills Wrapper**: The `.claude/skills/mcp-skills/` directory provides progressive disclosure wrappers that reduce context usage by 90%+ compared to native MCP loading.

Available wrapped skills: `assistant-ui`, `chrome-devtools`, `github`, `livekit-docs`, `logfire`, `magicui`, `playwright`, `shadcn`, `mcp-undetected-chromedriver`

### 4. Hooks System

Automated lifecycle event handlers configured in `.claude/settings.json`:

| Hook | Purpose | Script |
|------|---------|--------|
| `SessionStart` | Detect orchestrator mode, load MCP skills | `session-start-orchestrator-detector.py`, `load-mcp-skills.sh` |
| `UserPromptSubmit` | Remind orchestrator of delegation rules | `user-prompt-orchestrator-reminder.py` |
| `Stop` | Validate completion before session ends | `unified-stop-gate.sh` |
| `PreCompact` | Flush Hindsight memory before compression | `hindsight-memory-flush.py` |
| `Notification` | Webhook notifications | `gchat-notification-dispatch.py` |

### 5. Enabled Plugins

Configured in `.claude/settings.json`:
- `beads@beads-marketplace` - Issue tracking
- `frontend-design@claude-plugins-official` - UI design patterns
- `code-review@claude-plugins-official` - Code review automation
- `double-shot-latte@superpowers-marketplace` - Enhanced capabilities

## Key Patterns

### Investigation vs Implementation Boundary

**Orchestrators** (Level 2):
- ✅ Use Read/Grep/Glob to investigate
- ✅ Analyze, plan, and create task structures
- 🛑 NEVER use Edit/Write/MultiEdit directly
- 🛑 MUST delegate implementation to workers via native Agent Teams (`Teammate` + `TaskCreate` + `SendMessage`)

**Workers** (Level 3):
- ✅ Implement features using Edit/Write
- ✅ Run tests with tdd-test-engineer
- ✅ Report completion to orchestrator

### 4-Phase Orchestration Pattern

1. **Ideation** - Brainstorm, research, parallel-solutioning
2. **Planning** - PRD → Task Master → Beads hierarchy
3. **Execution** - Delegate to workers, monitor progress
4. **Validation** - 3-level testing (Unit + API + E2E)

### Validation Agent Enforcement

**MANDATORY**: All task closures must go through validation-agent with `--mode=implementation`:

```bash
# CORRECT: Delegate to validation-agent
Task(
    subagent_type="validation-agent",
    prompt="--mode=implementation --task_id=<id> ..."
)

# WRONG: Direct closure
bd close <task-id>  # BLOCKED
```

### Session Isolation

Each orchestrator session should have:
- Unique `CLAUDE_SESSION_ID` environment variable
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` for native team coordination
- Separate worktree (for code-based projects)
- Completion promise tracking
- Native team created via `Teammate(operation="spawnTeam")`

## Environment Variables

| Variable | Purpose | Set By |
|----------|---------|--------|
| `CLAUDE_SESSION_ID` | Unique session identifier | Launch scripts |
| `CLAUDE_OUTPUT_STYLE` | Active output style (cobuilder-guardian/orchestrator) | Claude Code CLI |
| `CLAUDE_PROJECT_DIR` | Project root directory | Claude Code CLI |
| `ANTHROPIC_API_KEY` | API authentication | `.mcp.json` env |
| `ANTHROPIC_BASE_URL` | Override API base URL (e.g. DashScope proxy) | `cobuilder/engine/.env` |
| `PERPLEXITY_API_KEY` | Perplexity API key | `.mcp.json` env |
| `BRAVE_API_KEY` | Brave search API key | `.mcp.json` env |
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | Enable native Agent Teams (`1`) | `.claude/settings.json` or spawn script |
| `CLAUDE_CODE_TASK_LIST_ID` | Shared task list ID for team coordination | Spawn script |
| `DASHSCOPE_API_KEY` | Alibaba DashScope API key (GLM-5/Qwen3 via Anthropic protocol) | `cobuilder/engine/.env` |
| `PIPELINE_SIGNAL_DIR` | Override signal file directory for pipeline runner | Environment |
| `PIPELINE_RATE_LIMIT_RETRIES` | Max retries on rate-limit errors (default: 3) | `cobuilder/engine/.env` |
| `PIPELINE_RATE_LIMIT_BACKOFF` | Backoff seconds on rate-limit (default: 65) | `cobuilder/engine/.env` |
| `PIPELINE_MAX_MANAGER_DEPTH` | Max recursive sub-pipeline depth (default: 5) | Environment |

## Testing

**Hook Tests**: `.claude/tests/hooks/`
```bash
pytest .claude/tests/hooks/              # Run all hook tests
pytest .claude/tests/hooks/test_*.py     # Run specific test
```

**Completion State Tests**: `.claude/tests/completion-state/`
```bash
pytest .claude/tests/completion-state/
```

## Utilities

### Status Line Analyzer

Real-time session status display:
```bash
./.claude/statusline_analyzer.py        # Show current session status
./.claude/setup-statusline.sh           # Configure status line
```

### Sync Scripts

Task Master to Beads synchronization:
```bash
node .claude/scripts/sync-taskmaster-to-features.js
node .claude/skills/orchestrator-multiagent/scripts/sync-taskmaster-to-beads.js
```

## Configuration Files

| File | Purpose |
|------|---------|
| `.mcp.json` | MCP server configurations (root level) |
| `.claude/settings.json` | Core Claude Code settings |
| `.claude/settings.local.json` | Local overrides (not in version control) |
| `.claude/.gitignore` | Excluded files (state/, logs/, etc.) |

## Important Notes

### API Keys in Configuration

⚠️ **Security Warning**: The `.mcp.json` file in this repository contains API keys embedded in the configuration. In a production environment:
- Never commit API keys to version control
- Use environment variables or secure secret management
- Rotate keys regularly
- This harness is for development/testing only

### No Application Code

This repository contains **only Claude Code configuration and orchestration tools**. It does not include:
- Application source code
- Frontend/backend implementations
- Deployment configurations
- Production services

The harness is designed to be copied into actual project repositories that contain application code.

### Orchestrator Delegation Rules

When running as an orchestrator (Level 2):
1. **Investigation is allowed**: Read/Grep/Glob to understand problems
2. **Implementation is forbidden**: Never use Edit/Write directly
3. **Always delegate**: Use native Agent Teams (teammates) for all code changes
4. **No exceptions**: Even "simple" changes must be delegated

This separation ensures proper testing, validation, and architectural consistency.

---

## CoBuilder Pipeline Engine

The `cobuilder/` package is the primary pipeline execution system. It runs DOT-defined multi-agent pipelines with zero LLM cost for graph traversal.

### Architecture

```
System 3 (Opus LLM)
    |
    pipeline_runner.py  (Python state machine, $0, <1s graph ops)
        |
        Workers  (AgentSDK: codergen, research, refine, validation)
```

The runner has **zero LLM intelligence**. It parses DOT, dispatches AgentSDK workers, watches signal files via watchdog, and transitions node states mechanically.

### pipeline_runner.py

Main runner. Parses a DOT pipeline file, finds dispatchable nodes, launches AgentSDK workers per node, and drives the status chain:

```
pending -> active -> impl_complete -> validated -> accepted
                  \-> failed
```

Worker result signals (written to `.pipelines/pipelines/signals/{pipeline_id}/`):
```json
{"status": "success"|"failed", "files_changed": [...], "message": "..."}
```

Validation result signals:
```json
{"result": "pass"|"fail"|"requeue", "reason": "...", "requeue_target": "node_id"}
```

On `requeue`: the runner mechanically sets the requeue target back to `pending`.

### Node Types

| Shape | Handler | Purpose |
|-------|---------|---------|
| `box` | `codergen` | LLM implementation node — dispatches orchestrator or SDK worker |
| `tab` | `research` | Research node — runs `run_research.py` (Context7 + Perplexity via Haiku) |
| `note` | `refine` | Refine node — runs `run_refine.py` (rewrites SD from research evidence) |
| `house` | `manager_loop` | Recursive sub-pipeline node — spawns child `pipeline_runner.py` |
| `diamond` | `wait.cobuilder` | Gate requiring System 3 validation before proceeding |
| `diamond` | `wait.human` | Gate requiring human input via `AskUserQuestion` |

### LLM Profiles (providers.yaml)

Named profiles are defined in `cobuilder/engine/providers.yaml`. DOT nodes reference profiles via `llm_profile="..."`. The runner resolves the profile to Anthropic SDK parameters at dispatch time.

Key profiles:

| Profile | Model | Provider |
|---------|-------|----------|
| `anthropic-fast` | `claude-haiku-4-5-20251001` | Anthropic |
| `anthropic-smart` | `claude-sonnet-4-5-20250514` | Anthropic |
| `anthropic-opus` | `claude-opus-4-6` | Anthropic |
| `alibaba-glm5` | `glm-5` | DashScope (default, near-$0 cost) |
| `alibaba-qwen3` | `qwen3-coder-plus` | DashScope |

Credentials are loaded from `cobuilder/engine/.env`. The file supports `$VAR` expansion (e.g. `ANTHROPIC_API_KEY=$DASHSCOPE_API_KEY` routes Anthropic-protocol calls through DashScope).

### Signal Protocol

All inter-layer communication uses atomic JSON signal files (`write-then-rename`). Signal files are stored in `.claude/attractor/signals/` (or `PIPELINE_SIGNALS_DIR` override).

Naming convention: `{timestamp}-{source}-{target}-{signal_type}.json`

Key signal types: `NEEDS_REVIEW`, `VALIDATION_PASSED`, `VALIDATION_FAILED`, `GATE_WAIT_COBUILDER`, `GATE_WAIT_HUMAN`, `GATE_RESPONSE`, `RUNNER_EXITED`, `AGENT_REGISTERED`

Processed signals are moved to `signals/processed/` after consumption.

### guardian.py

Layers 0/1 bridge. Launches guardian agent processes via AgentSDK, monitors for terminal-targeted signals, handles escalations and pipeline completion events. Supports single-guardian and parallel multi-guardian launch via `--multi <configs.json>`.

### session_runner.py (runner.py)

Layer 2 monitoring runner. Monitors an orchestrator tmux session and communicates status back to the guardian via signal files.

### handlers/

Node handler implementations. Each handler receives a `HandlerRequest` and returns an `Outcome`. The `manager_loop` handler supports recursive sub-pipeline spawning with child gate detection (`GATE_WAIT_COBUILDER`, `GATE_WAIT_HUMAN`).

### Checkpoint System

`checkpoint.py` provides Pydantic-based pipeline state persistence. Checkpoints are written atomically after each node transition to `.pipelines/pipelines/*-checkpoint-*.json`. Use `--resume` flag to restore from the latest checkpoint.

### Template System (.cobuilder/templates/)

Jinja2 DOT templates in `.cobuilder/templates/`. Instantiated via `cobuilder/templates/instantiator.py`. Available templates:

- `sequential-validated` — Linear pipeline with validation gates after each codergen node
- `hub-spoke` — Fan-out parallel dispatch to multiple workers
- `cobuilder-lifecycle` — Full lifecycle pipeline (research → design → implement → validate)

### Logfire Observability

Service names for filtering traces:
- `cobuilder-pipeline-runner` — Pipeline runner spans
- `cobuilder-guardian` — Guardian agent spans
- `cobuilder-session-runner` — Session runner spans

### CLI (cli.py)

Full subcommand interface for pipeline management:

```bash
python3 cobuilder/engine/cli.py status <file.dot>           # Show node states
python3 cobuilder/engine/cli.py validate <file.dot>         # Check topology
python3 cobuilder/engine/cli.py transition <file.dot> <node> <status>  # Manual transition
python3 cobuilder/engine/cli.py checkpoint save <file.dot>  # Save checkpoint
python3 cobuilder/engine/cli.py generate --prd <PRD-REF>    # Generate DOT from beads
python3 cobuilder/engine/cli.py dashboard <file.dot>        # Unified lifecycle dashboard
```

### Haiku Sub-Agent Monitoring Pattern

After launching `pipeline_runner.py`, System 3 spawns a **blocking** (foreground) Haiku sub-agent monitor to watch for state transitions without sleep-polling:

```python
Task(
    subagent_type="general-purpose",
    model="haiku",
    run_in_background=False,  # blocking — System 3 waits for result
    prompt="Monitor DOT file <path> and signal dir <signals_path>. "
           "Complete with a status report when: any node fails, pipeline stalls >5min, "
           "all nodes reach terminal state, gate node detected, or 10-min timeout."
)
```

Monitor completion statuses and System 3 actions:

| Monitor Reports | System 3 Action |
|-----------------|----------------|
| All nodes terminal (`accepted`) | Run blind Gherkin E2E, close uber-epic |
| Node failed | Inspect signal, send guidance, re-launch runner |
| `wait.cobuilder` gate detected | Run validation agent, write `GATE_RESPONSE` signal |
| `wait.human` gate detected | Call `AskUserQuestion`, write `GATE_RESPONSE` signal |
| Stall (>5 min no progress) | Send unblocking guidance to orchestrator |
| 10-min timeout | Evaluate state, re-launch monitor |

Cyclic pattern:
```
System 3  ->  launch monitor  ->  monitor watches DOT/signals
                                  monitor COMPLETES with report
System 3  <-  handle report   <-  (re-launch monitor if work remains)
```

---

## Agent Directory (Worker Selection Menu)

When dispatching workers (via `subagent_type` in Agent Teams or `worker_type` in DOT pipelines), use this directory to select the right specialist.

### Implementation Workers

| Agent | Specialization | Use When |
|-------|---------------|----------|
| `frontend-dev-expert` | React, Next.js, TypeScript, Zustand, Tailwind | Any file in `*/frontend/*` or UI work |
| `backend-solutions-engineer` | Python, FastAPI, PydanticAI, Supabase, databases | Any file in `*/agent/*` or API/backend work |
| `tdd-test-engineer` | Pytest, Jest, Playwright, TDD methodology | Writing NEW tests or test architecture |
| `solution-architect` | System design, architectural planning, PRDs | Solution design docs, technology decisions |
| `ux-designer` | UX audits, design concepts, UI mockups | UX analysis, design briefs, user journey mapping |

### Validation Workers

| Agent | Specialization | Use When |
|-------|---------------|----------|
| `validation-test-agent` | PRD acceptance validation, compliance checking | CHECKING existing work against requirements |
| `code-reviewer` | Code quality, security review, best practices | Code review, quality assurance |

### Coordination (Not Workers)

| Agent | Role |
|-------|------|
| `orchestrator` (Level 2) | Multi-agent task coordination, delegates to workers above |
| `cobuilder-guardian` (Level 1) | Strategic planning, business validation, pipeline oversight |

### Agent Selection Decision Tree

1. **Strategic/business-level?** → System 3
2. **Coordinating multiple agents?** → Orchestrator
3. **Design/planning/architecture?** → `solution-architect`
4. **Validation/compliance/checking?** → `validation-test-agent` or `code-reviewer`
5. **Frontend/UI?** → `frontend-dev-expert`
6. **Backend/server-side?** → `backend-solutions-engineer`
7. **Writing tests?** → `tdd-test-engineer`
8. **None of the above** → `general-purpose`

### Selection Guard

When reasoning includes "test" or "testing", STOP and ask: "Am I writing NEW tests (TDD) or CHECKING existing work?" Writing new → `tdd-test-engineer`. Checking → `validation-test-agent`.

## Documentation Standards

All markdown files in `.claude/` and `docs/` must follow documentation standards, enforced by the **doc-gardener** linter (`scripts/doc-gardener/lint.py`). The linter supports **target-specific schemas** — `.claude/` and `docs/` have different required fields and valid types, controlled via config files.

### Documentation Directory Map

**`.claude/` directories** (linted, require frontmatter):

| Directory | Purpose | Default Grade |
|-----------|---------|---------------|
| `skills/` | Skill implementations (SKILL.md per skill) | `authoritative` |
| `agents/` | Agent configuration definitions | `authoritative` |
| `output-styles/` | Output style behavior definitions | `authoritative` |
| `documentation/` | Architecture docs, ADRs, guides | `reference` |
| `commands/` | Slash command definitions | `reference` |

**`docs/` directories** (linted, require extended frontmatter):

| Directory | Purpose | Default Grade |
|-----------|---------|---------------|
| `prds/` | Product Requirement Documents | `authoritative` |
| `sds/` | Solution Design documents | `authoritative` |
| `solution-designs/` | Solution Design documents (alternate) | `authoritative` |
| `research/` | Research documents and spikes | `reference` |
| `references/` | Reference material | `reference` |
| `guides/` | How-to guides | `reference` |
| `tests/` | Test documentation | `reference` |
| `specs/` | Technical specifications | `reference` |
| `design-references/` | Design reference material | `reference` |

**Skipped directories** (runtime state, not documentation):

| Directory | Purpose |
|-----------|---------|
| `state/` | Runtime state tracking |
| `completion-state/` | Session completion tracking |
| `evidence/` | Validation evidence artifacts |
| `progress/` | Session progress logs |
| `worker-assignments/` | Worker task assignments |
| `user-input-queue/` | Queued user input |

Also skipped: `documentation/gardening-report.md` (auto-generated).

### Frontmatter Requirements

Frontmatter requirements differ by target directory:

**`.claude/` files** (minimal schema):

```yaml
---
title: "Human-Readable Title"           # REQUIRED
status: active                          # REQUIRED - active | draft | archived | deprecated
type: skill                             # Recommended - skill | agent | output-style | hook | command | guide | architecture | reference | config
last_verified: 2026-02-19              # Recommended - YYYY-MM-DD
grade: authoritative                    # Recommended - authoritative | reference | archive | draft
---
```

**`docs/` files** (extended schema):

```yaml
---
title: "Human-Readable Title"           # REQUIRED
description: "One-line purpose summary"  # REQUIRED - non-empty, max 200 chars
version: "1.0.0"                        # REQUIRED - semver N.N.N
last-updated: 2026-03-15               # REQUIRED - YYYY-MM-DD
status: active                          # REQUIRED - active | draft | archived | deprecated
type: prd                               # REQUIRED - prd | sd | epic | specification | research | guide | reference | architecture
grade: authoritative                    # Recommended
prd_id: PRD-XXX-NNN                    # CONDITIONAL - required for PRDs
---
```

Missing frontmatter is auto-fixable — the gardener generates it from filename, directory, git history, and content.

### Lint Check Categories

The doc-gardener checks 7 categories:

| Category | What It Checks | Severity | Auto-fixable |
|----------|---------------|----------|-------------|
| **frontmatter** | Missing block → `warning`; invalid field values → `error` | warning/error | Yes (generates missing frontmatter) |
| **crosslinks** | All relative markdown links resolve to real files | error | No |
| **naming** | Directory and file naming conventions (see below) | warning | No |
| **staleness** | `last_verified` > 90 days → `warning`; > 60 days (authoritative only) → `info` | warning/info | Yes (downgrades grade) |
| **grades-sync** | Frontmatter `grade` matches `quality-grades.json` defaults | info | Yes (updates frontmatter) |
| **implementation-status** | PRD/SD/Epic/Spec docs must have `## Implementation Status` section | warning | Yes (appends template) |
| **misplaced-document** | PRD/SD/Epic/Spec content outside `docs/` is flagged | warning | No (manual move) |

### Implementation Status Check

**Applies to**: Files where frontmatter `type` is `prd`, `sd`, `epic`, or `specification`, OR filename matches `PRD-*`, `SD-*`. Files with `status: draft` are exempt.

**Required**: An `## Implementation Status` heading (H2) with a status table:

```markdown
## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| E1: Foundation | Done | 2026-03-15 | abc1234 |
| E2: Validation | In Progress | - | - |
```

Auto-fix appends a template section with "Remaining" status.

### Misplaced Document Detection

Any `.md` file outside `docs/` whose filename or content indicates PRD/SD/Epic/Specification content is flagged. Detection checks:
1. Filename pattern: `PRD-*.md`, `SD-*.md`
2. Frontmatter: `type: prd|sd|epic|specification` or `prd_id:`/`prd_ref:` fields
3. Headings: H1/H2 containing `PRD-` or `SD-` identifiers

**Excluded paths** (allowed to contain such content):
- `.claude/skills/`, `.claude/output-styles/`, `.claude/commands/`, `.claude/evidence/`, `.claude/narrative/`
- `acceptance-tests/`, `node_modules/`, `.git/`, `.pipelines/`, `.cobuilder/`

### Naming Conventions

| Item | Convention | Pattern | Examples |
|------|-----------|---------|----------|
| Directories | `kebab-case` | `^[a-z0-9]+(-[a-z0-9]+)*$` | `orchestrator-multiagent/`, `doc-gardener/` |
| | Doc-ID prefixed dirs | `^(SD\|PRD\|...)-[A-Za-z0-9][-A-Za-z0-9.]*$` | `SD-DOC-GARDENER-002/` |
| Top-level docs | `UPPER-CASE.md` | Exact match set | `CLAUDE.md`, `SKILL.md`, `README.md`, `INDEX.md`, `CHANGELOG.md` |
| Regular files | `kebab-case.md` | `^[a-z0-9]+(-[a-z0-9]+)*\.md$` | `decision-time-guidance.md` |
| Doc-ID files | `PREFIX-name.md` | `^(SD\|PRD\|TS\|EPIC\|...)-*.md$` | `PRD-DOC-GARDENER-002.md`, `SD-EXAMPLE-001.md` |
| ADR/spec prefixes | `ADR-NNN-kebab.md` | Mixed case prefix | `ADR-001-output-style-reliability.md` |
| Version-prefixed | `vN.N-kebab.md` | Version prefix | `v3.9-migration-guide.md` |
| Private files | `_underscore.md` | Leading underscore | `_internal-notes.md` |

### Staleness Thresholds

| Condition | Severity | Action |
|-----------|----------|--------|
| `last_verified` > 90 days old | `warning` | Grade should be `archive` (auto-fixed) |
| `last_verified` > 60 days old AND grade is `authoritative` | `info` | Consider downgrading to `reference` (auto-fixed) |
| No `last_verified` field | — | Not flagged (field is optional) |

### Cross-Link Integrity

All relative markdown links (`[text](path)`) must resolve to existing files. The linter:
- Strips code blocks and inline code before scanning
- Resolves paths relative to the file containing the link
- Reports unresolvable links as errors (not auto-fixable)

### Quality Grades

Documents are graded by reliability and maintenance commitment:

| Grade | Meaning | Review Cadence | Trust Level |
|-------|---------|----------------|-------------|
| `authoritative` | Source of truth, actively maintained | Continuous | High |
| `reference` | Useful context, periodically reviewed | Quarterly | Medium |
| `archive` | Historical record, not maintained | None | Low |
| `draft` | Work in progress, unverified | On completion | Unverified |

Default grades per directory are defined in `scripts/doc-gardener/quality-grades.json`.

### Config Files

| File | Scope | Purpose |
|------|-------|---------|
| `.claude/scripts/doc-gardener/docs-gardener.config.json` | Both `.claude/` and `docs/` | Primary config with target-specific required fields, docs types, implementation status rules, misplaced document exclusions |
| `.claude/scripts/doc-gardener/quality-grades.json` | Both | Default grades per directory |

### Doc-Gardener Commands

```bash
# Lint .claude/ only (default target)
python3 .claude/scripts/doc-gardener/lint.py

# Lint docs/ with extended schema
python3 .claude/scripts/doc-gardener/lint.py --target docs/ --config .claude/scripts/doc-gardener/docs-gardener.config.json

# Lint both .claude/ and docs/ (uses config targets)
python3 .claude/scripts/doc-gardener/lint.py --config .claude/scripts/doc-gardener/docs-gardener.config.json

# Auto-fix and generate report
python3 .claude/scripts/doc-gardener/gardener.py --execute

# Auto-fix docs/ specifically
python3 .claude/scripts/doc-gardener/gardener.py --target docs/ --config .claude/scripts/doc-gardener/docs-gardener.config.json --execute

# Machine-readable output
python3 .claude/scripts/doc-gardener/lint.py --json

# Bypass on push (emergency only)
DOC_GARDENER_SKIP=1 git push
```

---

## System3 Monitoring Architecture

### Critical Discovery: Wake-Up Mechanism

**Only completing subagents can wake the main thread.** External scripts, file changes, and task list updates do NOT trigger notifications to idle Claude sessions.

This shapes the entire monitoring design: **monitors must be subagents that COMPLETE when attention is needed.**

### Validation-Agent Monitor Mode

System3 uses `validation-test-agent --mode=monitor` for continuous oversight of orchestrators:

```python
Task(
    subagent_type="validation-test-agent",
    model="sonnet",  # MUST be Sonnet - Haiku lacks exit discipline
    run_in_background=True,
    prompt="--mode=monitor --session-id=orch-{name} --task-list-id=PRD-{prd}"
)
```

**Monitor Outputs:**
| Status | Meaning | System3 Action |
|--------|---------|----------------|
| `MONITOR_COMPLETE` | All tasks validated | Run final e2e, close uber-epic |
| `MONITOR_STUCK` | Orchestrator blocked | Send guidance, re-launch monitor |
| `MONITOR_VALIDATION_FAILED` | Work invalid | Alert orchestrator, re-launch |
| `MONITOR_HEALTHY` | Still working | Re-launch monitor (heartbeat) |

### Cyclic Wake-Up Pattern

```
System3                    Monitor (Sonnet)                Orchestrator
   |                            |                              |
   |  Launch monitor ---------->|                              |
   |                            |<-- Poll task-list-monitor.py |
   |                            |    Detect task completed     |
   |                            |    Validate work...          |
   |<----- COMPLETE ------------|                              |
   |  Handle result             |                              |
   |  RE-LAUNCH monitor ------->|  (cycle repeats)             |
```

### Model Requirements

| Role | Model | Reason |
|------|-------|--------|
| System3 | Opus | Complex strategic reasoning |
| Orchestrator | Sonnet/Opus | Coordination, delegation |
| Worker | Haiku/Sonnet | Simple implementation |
| **Validation Monitor** | **Sonnet** | Exit discipline required |

### Task List Monitor Script

`scripts/task-list-monitor.py` provides efficient change detection using MD5 checksums:

```bash
python ~/.claude/scripts/task-list-monitor.py --list-id shared-tasks --changes --json
```

### Task List ID Convention

```
CLAUDE_CODE_TASK_LIST_ID = PRD-{category}-{number}
```

Tasks stored at: `~/.claude/tasks/{CLAUDE_CODE_TASK_LIST_ID}/`

---

## Skills Library

Skills are explicitly invoked via `Skill("skill-name")`. Use this library to know **when** to reach for each skill rather than doing the work manually. Skills contain versioned, current patterns — your memory does not.

### Orchestration & Planning

| Skill | Invoke When |
|-------|------------|
| `cobuilder-guardian` | Spawning orchestrators, creating blind acceptance tests, monitoring and independent validation |
| `orchestrator-multiagent` | Orchestrator setting up a native Agent Team and delegating to workers |
| `cobuilder-heartbeat` | Setting up a session-scoped keep-alive agent that scans for work on a cycle |
| `completion-promise` | Tracking session-level goals with verifiable acceptance criteria |
| `worker-focused-execution` | A worker agent needs persistent task claiming and completion reporting patterns |

### Research & Investigation

| Skill | Invoke When |
|-------|------------|
| `research-first` | Investigating an unfamiliar framework, library, or architectural pattern before briefing an orchestrator |
| `explore-first-navigation` | Need to find files, search a codebase, or understand structure before making a plan |
| `mcp-skills` | Looking up which MCP-derived skill wraps a tool (github, playwright, logfire, shadcn, magicui, livekit, etc.) |

### Validation & Quality

| Skill | Invoke When |
|-------|------------|
| `acceptance-test-writer` | Kicking off a new initiative — write blind Gherkin acceptance tests from the PRD **before** briefing the orchestrator |
| `acceptance-test-runner` | Running stored acceptance tests against a completed implementation to generate evidence |
| `codebase-quality` | Orchestrating a quality sweep (linting, dead code, security review) across the repo |

### Frontend & Design

| Skill | Invoke When |
|-------|------------|
| `frontend-design` | Designing or reviewing a frontend interface — ensures distinctive, non-generic UI patterns |
| `design-to-code` | Translating a design mockup or screenshot into production React components |
| `website-ux-audit` | Any work involving an existing website or UI — run audit before forming the design brief |
| `website-ux-design-concepts` | Generating visual mockups or HTML/CSS prototypes from audit recommendations |
| `react-best-practices` | Briefing frontend workers — reference current React/Next.js performance rules |

### Infrastructure & Deployment

| Skill | Invoke When |
|-------|------------|
| `railway-new` | Creating a new Railway project, service, or database |
| `railway-deploy` | Deploying code to Railway (`railway up`) |
| `railway-deployment` | Managing existing deployments (logs, redeploy, remove) |
| `railway-stat` | Checking current Railway project health |
| `railway-environment` | Reading or editing Railway environment variables |
| `railway-database` | Adding a managed database service to a Railway project |
| `railway-domain` | Adding or removing custom domains on Railway |
| `railway-metrics` | Querying CPU/memory resource usage for a Railway service |
| `railway-service` | Checking service status or advanced service configuration |
| `railway-projects` | Listing or switching Railway projects |
| `railway-templates` | Searching and deploying from the Railway template marketplace |
| `railway-railway-docs` | Looking up Railway documentation to answer config questions accurately |
| `railway-central-station` | Searching Railway community support threads |
| `worktree-manager-skill` | Creating, switching, or cleaning up git worktrees for parallel development |

### Development Tools

| Skill | Invoke When |
|-------|------------|
| `using-tmux-for-interactive-commands` | Running interactive CLI tools (vim, git rebase -i, REPLs) that require a real terminal |
| `dspy-development` | Building or modifying DSPy modules, optimizers, or LLM pipelines |
| `setup-harness` | Deploying this harness configuration to a target project repository |

### Skill Development

| Skill | Invoke When |
|-------|------------|
| `skill-development` | Creating a new skill or editing an existing one |
| `mcp-to-skill-converter` | Wrapping an MCP server as a progressive-disclosure Claude skill |

### Quick Decision Guide

**Before any new initiative** → `acceptance-test-writer` (blind tests first)
**Before researching a framework** → `research-first`
**Before spawning an orchestrator** → `cobuilder-guardian`
**Before designing UI** → `website-ux-audit` → `website-ux-design-concepts` → `frontend-design`
**Before deploying to Railway** → `railway-stat` → `railway-deploy`
**After orchestrator claims done** → `cobuilder-guardian` or validation-test-agent
**When navigating unfamiliar code** → Serena MCP (`mcp__serena__find_symbol`, `mcp__serena__search_for_pattern`)
