---
title: "CoBuilder Upgrade: Templates, Worktrees & Guardian Meta-Pipeline"
prd_id: PRD-COBUILDER-UPGRADE-001
status: draft
type: prd
created: 2026-03-14
last_verified: 2026-03-14
grade: authoritative
owner: theb
note: "This is the LAST document using PRD/SD terminology. E6 migrates to Business Spec (BS) / Technical Spec (TS)."
---

# PRD-COBUILDER-UPGRADE-001: CoBuilder Upgrade — Templates, Worktrees & Guardian Meta-Pipeline

## 1. Problem Statements

| ID | Problem | Impact |
|----|---------|--------|
| P1 | **No reusable pipeline topologies.** Every initiative requires authoring a DOT graph from scratch. Common structural patterns (research-refine-codergen, hub-spoke validation) are copy-pasted and diverge. | Slow initiative boot, topology bugs, inconsistent gate placement |
| P2 | **No stable worktree management.** Worktrees are created ad-hoc via shell commands. No idempotent `get_or_create`, no existing-branch support, no lifecycle tracking, no human-gated cleanup. | Disk waste, branch pollution, agent confusion when worktrees vanish mid-run |
| P3 | **No Guardian meta-pipeline.** The CoBuilder Guardian's lifecycle (research → refine → plan → execute → validate → evaluate) is implicit prose. No executable representation that can be paused, resumed, inspected, or looped. | No audit trail, no bounded retry, no programmatic introspection |
| P4 | **No per-node LLM configuration.** All workers use the same model, API key, and base URL. Cannot mix providers (Anthropic, OpenRouter, local) or models (Haiku for research, Opus for codergen) within one pipeline. | Over-spend on cheap tasks, cannot leverage specialized models, single-provider lock-in |
| P5 | **Runtime state mixed into `.claude/`.** Pipeline DOT files, signal files, and transition logs live under `.claude/attractor/`. This repo ships publicly on GitHub — runtime state would pollute the published repo. | Accidental commits of signal/state files; fragile `.gitignore` rules |
| P6 | **Stale terminology and fragmented guardian skill.** `system3-meta-orchestrator`, `s3-guardian`, `wait.system3`, agent teams, tmux spawning — legacy concepts that confuse new contributors and leak into agent prompts as cognitive momentum. PRD/SD naming is project-specific rather than generalised. | Contributor confusion, stale mental models in agent prompts, inconsistent vocabulary |

## 2. Goals

| ID | Goal | Success Metric | Priority |
|----|------|---------------|----------|
| G1 | **Template library**: Ship 3 parameterized DOT templates (sequential-validated, hub-spoke, cobuilder-lifecycle) with Jinja2 rendering and `manifest.yaml` constraints | `cobuilder template list` shows 3 entries; each instantiates valid DOT | P0 |
| G2 | **Constraint enforcement**: Static constraints (topology, path, loop bounds, nesting depth) validated at instantiation; dynamic constraints (NodeStateMachine) enforced at runtime via ConstraintMiddleware | Invalid graphs rejected before dispatch; illegal transitions blocked | P0 |
| G3 | **Stable worktrees**: `WorktreeManager.get_or_create(id, branch=)` returns a path idempotently, supporting both new and existing branches. Cleanup gated behind `wait.human`. Worktree target set at DOT graph level. | Worktrees survive runner restarts; cleanup never happens without human approval | P0 |
| G4 | **Self-driving Guardian**: CoBuilder Guardian lifecycle encoded as `cobuilder-lifecycle.dot.j2`. Guardian has explicit permission to create DOT graphs and launch runners. `wait.human` gate required before launching new pipelines (configurable in manifest: `permissions.require_human_before_launch`) | Guardian pipeline runs autonomously for 1+ cycle with human gates at launch points | P1 |
| G5 | **Child pipeline spawning via SDK**: ManagerLoopHandler EXECUTE node spawns child EngineRunner. Parent monitors child signal directory for `wait.cobuilder` gates (not just exit code). No tmux anywhere. | Parent handles child gates correctly; no deadlocks | P0 |
| G6 | **Per-node LLM config via named profiles**: DOT nodes reference `llm_profile` names from `providers.yaml`. Profile keys translate to Anthropic SDK equivalents. 5-layer resolution: node → handler defaults → manifest defaults → env vars → runner defaults | Mixed-model pipeline: Haiku research + Sonnet codergen in same graph | P1 |
| G7 | **Bounded loops**: `loop_constraint` in manifest caps iteration count. ManagerLoopHandler tracks loop counter. | Loop terminates at bound; counter visible in status output | P1 |
| G8 | **Unified cobuilder-guardian skill**: Merge `s3-guardian` + `system3-meta-orchestrator` into single `cobuilder-guardian` skill. Strip all legacy terminology (system3, agent teams, sub agents, tmux). Rename `wait.system3` → `wait.cobuilder` globally. Migrate PRD→Business Spec (BS), SD→Technical Spec (TS) with per-initiative directories. | Zero references to "system3", "agent teams", or "tmux" in skills/output-styles | P1 |
| G9 | **GitHub publication readiness**: Secret scrubbing, LICENSE, CONTRIBUTING.md, onboarding docs, CI/CD via GitHub Actions. | Repo passes `git-secrets` scan; README has Getting Started section; CI runs on PR | P1 |
| G10 | **Logfire observability preserved**: All existing Logfire spans survive the merge and package rename. New features (ManagerLoopHandler upgrade, child signal monitoring) add their own spans. | Zero span regression; `CaptureLogfire` assertions in all handler tests | P0 |
| G11 | **90% unit test coverage**: CI enforces `fail_under=90` on all PRs. Coverage baseline established in E0, gaps filled progressively, gate enforced in E5. | `pytest --cov-fail-under=90` passes; no PR reduces coverage | P1 |

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|-------------|-----------|
| US1 | CoBuilder Guardian | instantiate a pipeline from a template with parameters | the structural patterns are reusable while per-initiative nodes and prompts are authored fresh |
| US2 | Pipeline runner | resolve model/key/url per node via named profiles at dispatch time | I can mix Haiku research with Sonnet implementation in one graph |
| US3 | CoBuilder Guardian | have my lifecycle (research→plan→execute→validate) be a runnable pipeline | my decisions are auditable and my process is bounded |
| US4 | Pipeline runner | spawn a child pipeline and monitor its gates (not just its exit code) | `wait.cobuilder` gates in child pipelines don't deadlock the parent |
| US5 | Developer | run `cobuilder worktree get-or-create my-initiative --branch existing-branch` | worktrees are idempotent, support existing branches, and survive restarts |
| US6 | Pipeline runner | reject a graph that violates template constraints at instantiation | topology bugs are caught before any worker is dispatched |
| US7 | CoBuilder Guardian | have a `wait.human` gate before launching any new pipeline | I never run unsupervised pipelines without explicit human approval (configurable) |
| US8 | Developer (contributing to repo) | find clear docs, no leaked secrets, and CI checks on my PRs | I can contribute confidently to the public GitHub repo |

## 4. Architecture

### 4.1 Three Pillars

```
┌──────────────────────────────────────────────────────────────┐
│                    PILLAR 1: TEMPLATES                        │
│  .cobuilder/templates/{name}/                                 │
│    template.dot.j2    — Jinja2 parameterized topology         │
│    manifest.yaml      — parameters, constraints, defaults     │
│    README.md          — human docs                            │
│                                                               │
│  Instantiator: manifest + params → rendered .dot skeleton     │
│  Per-node prompts and worker types authored per-initiative    │
│  Constraints: topology, path, loop, nesting, state machine   │
├──────────────────────────────────────────────────────────────┤
│                    PILLAR 2: WORKTREES                         │
│  WorktreeManager (shared: runner + CLI + future web server)   │
│    get_or_create(id, branch=) → path  (idempotent)            │
│    cleanup(id)  — ONLY after wait.human approval              │
│    list() → [{id, path, branch, created, last_used}]          │
│    from_existing(id, branch) → path  (attach existing branch) │
│    Worktree target: DOT graph-level `target_dir` attribute    │
├──────────────────────────────────────────────────────────────┤
│                    PILLAR 3: GUARDIAN META-PIPELINE            │
│  cobuilder-lifecycle.dot.j2                                   │
│    RESEARCH → REFINE → PLAN → wait.human →                    │
│    EXECUTE → VALIDATE → EVALUATE (with bounded loop-back)     │
│  Guardian = headful Claude Code session (Opus)                │
│    Creates DOT graphs, launches EngineRunner                  │
│    Responds to wait.cobuilder + wait.human gates              │
│    Monitors via blocking Haiku sub-agent (signal watcher)     │
│  ManagerLoopHandler: spawn_pipeline mode (already implemented)│
│  Standalone pipelines (no guardian) fully supported            │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Per-Node LLM Configuration via Named Profiles

LLM configuration uses **named profiles** defined in `providers.yaml`. DOT nodes reference profiles by name; the runner resolves profile keys to Anthropic SDK equivalents at dispatch time.

#### providers.yaml (per-repo or per-manifest)

```yaml
# providers.yaml — lives alongside manifest.yaml or at repo root
profiles:
  anthropic-fast:
    model: claude-haiku-4-5-20251001
    api_key: $ANTHROPIC_API_KEY          # env var reference
    base_url: https://api.anthropic.com

  anthropic-smart:
    model: claude-sonnet-4-5-20250514
    api_key: $ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com

  anthropic-opus:
    model: claude-opus-4-6
    api_key: $ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com

  openrouter-smart:
    model: anthropic/claude-sonnet-4-5
    api_key: $OPENROUTER_API_KEY
    base_url: https://openrouter.ai/api/v1
```

#### Profile-to-Anthropic Translation

All profile keys translate to their Anthropic SDK equivalents at dispatch time:

| Profile Key | Anthropic SDK Equivalent | Environment Variable |
|-------------|--------------------------|---------------------|
| `model` | `model` in `ClaudeCodeOptions` | `ANTHROPIC_MODEL` |
| `api_key` | `ANTHROPIC_API_KEY` in worker env | `ANTHROPIC_API_KEY` |
| `base_url` | `ANTHROPIC_BASE_URL` in worker env | `ANTHROPIC_BASE_URL` |

Any provider speaking the Anthropic API protocol works transparently. The worker is unaware of provider identity.

#### Resolution Order (first non-null wins)

1. **Node `llm_profile`** — profile on the DOT node → look up in `providers.yaml`
2. **Handler defaults** — `defaults.handler_defaults.{handler_type}.llm_profile` in manifest
3. **Manifest defaults** — `defaults.llm_profile` in manifest
4. **Environment variables** — `ANTHROPIC_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`
5. **Runner defaults** — hardcoded fallback in runner

### 4.3 Per-Node Prompts

Each DOT node carries a `prompt` attribute containing the worker's instructions. The runner injects this prompt into the worker's system context at dispatch time, along with the node's handler type, Technical Spec path, and any additional context attributes.

```dot
codergen_backend [
    shape=box
    handler="codergen"
    label="Implement: Backend Auth"
    llm_profile="anthropic-smart"
    prompt="Implement JWT authentication per TS-COBUILDER-UPGRADE-E3. Files: cobuilder/auth/..."
    ts_path="docs/specs/cobuilder-upgrade/TS-COBUILDER-UPGRADE-E3.md"
    worker_type="backend-solutions-engineer"
    status="pending"
];
```

For templates, prompts can use Jinja2 variables that are filled in at instantiation time, but the initiative-specific content (what to build, which files, which spec) is always authored per-initiative.

### 4.4 Guardian Architecture

```
CoBuilder Guardian (headful Claude Code session, Opus)
    │
    ├── Creates/authors DOT pipeline (from template or hand-authored)
    │   (each node has prompt, handler, worker_type, llm_profile)
    │
    ├── wait.human gate before pipeline launch (configurable)
    │
    ├── Launches EngineRunner (cobuilder.engine.runner)
    │       │
    │       ├── RESEARCH node → Haiku worker (context7 + perplexity)
    │       ├── REFINE node → Sonnet worker (rewrite TS with findings)
    │       ├── PLAN node → Sonnet worker (generate child pipeline DOT)
    │       ├── EXECUTE node → ManagerLoopHandler.spawn_pipeline()
    │       │       │
    │       │       └── Child EngineRunner (implementation pipeline)
    │       │               ├── codergen nodes → workers
    │       │               ├── wait.cobuilder → validation-test-agent
    │       │               └── wait.human → signal file (human review)
    │       │
    │       ├── VALIDATE node → validation-test-agent (Gherkin E2E)
    │       ├── EVALUATE node → score + loop decision
    │       │       └── Loop back to RESEARCH if score < threshold
    │       │           (bounded by loop_constraint.max_iterations)
    │       └── CLOSE node → programmatic epic closure
    │               ├── Push branch to remote
    │               ├── Create PR
    │               └── Cleanup worktree (after wait.human approval)
    │
    └── Monitors via blocking Haiku sub-agent
            Watches: .pipelines/signals/ for new files + DOT mtime
            Completes when: wait.cobuilder gate, wait.human gate,
              node failure, stall >5min, or 10-min timeout
            Reports to Guardian — never fixes anything
```

**Key distinctions:**
- **With Guardian**: Guardian creates the DOT graph, launches runner, handles gates, makes strategic decisions. The `cobuilder-lifecycle` template encodes this lifecycle.
- **Without Guardian (standalone pipeline)**: Any developer or script can launch `cobuilder pipeline run <dot-file>`. Gates still work — `wait.cobuilder` dispatches validation-test-agent automatically, `wait.human` writes a signal file and waits for manual response. No Opus session required.

**Parent-child gate handling**: When ManagerLoopHandler spawns a child pipeline, it monitors the child's signal directory (not just the exit code). When the child hits a `wait.cobuilder` gate, the parent runner detects the gate signal, runs validation, writes the response signal, and the child continues. This prevents deadlocks.

### 4.5 Template Instantiation Model

Templates provide **structural patterns** — the topology, gate placement, constraint rules, and handler assignments. They do NOT provide the initiative-specific content (what to build, which files, what prompts). That content is authored per-initiative.

**What a template defines:**
- Node handler types (research, refine, codergen, wait.cobuilder, wait.human)
- Edge structure (which nodes depend on which)
- Constraint rules (path sequences, loop bounds, nesting depth)
- Default LLM profiles per handler type

**What the user provides at instantiation:**
- `initiative_id`, `epic_count`, and other structural parameters
- Per-node prompts, worker types, spec paths (authored after instantiation)

**Workflow:**
```
1. cobuilder template instantiate sequential-validated \
     --param initiative_id=my-feature --param epic_count=3
   → Produces: .pipelines/pipelines/my-feature.dot (skeleton)

2. Developer fills in per-node attributes:
   - prompt="Implement X per TS-Y..."
   - ts_path="docs/specs/..."
   - worker_type="backend-solutions-engineer"

3. cobuilder template validate .pipelines/pipelines/my-feature.dot
   → Validates against manifest constraints

4. cobuilder pipeline run .pipelines/pipelines/my-feature.dot
   → EngineRunner dispatches workers
```

### 4.6 Template Manifest Extensions

```yaml
# manifest.yaml
name: sequential-validated
version: "1.0"
description: "Linear pipeline with research→refine→codergen chains"

parameters:
  initiative_id:
    type: string
    required: true
  epic_count:
    type: integer
    default: 1
    min: 1
    max: 20

defaults:
  llm_profile: "anthropic-fast"
  providers_file: "providers.yaml"
  handler_defaults:
    codergen:
      llm_profile: "anthropic-smart"
    research:
      llm_profile: "anthropic-fast"
    refine:
      llm_profile: "anthropic-smart"
    summarizer:                            # stream summarizer model
      llm_profile: "anthropic-fast"

permissions:
  create_pipelines: true                   # Guardian can create new DOT graphs
  launch_runners: true                     # Guardian can launch EngineRunner
  require_human_before_launch: true        # wait.human gate before pipeline launch

constraints:
  node_state_machine:
    states: [pending, active, impl_complete, validated, failed, accepted]
    transitions:
      pending: [active]
      active: [impl_complete, failed]
      impl_complete: [validated, failed]
      validated: [accepted]
      failed: [active]  # retry

  topology_constraint:
    type: dag
    require_single_entry: true
    require_single_exit: true

  path_constraint:
    required_sequence: ["research", "refine", "codergen"]
    description: "Every codergen must be preceded by research→refine"

  loop_constraint:
    max_iterations: 3
    loop_nodes: ["evaluate", "research"]

  nesting_constraint:
    max_depth: 2                           # configurable per template
```

### 4.7 WorktreeManager Integration

`WorktreeManager` is shared infrastructure, configured at the DOT graph level via a `target_dir` attribute:

```dot
digraph initiative {
    graph [
        target_dir="/path/to/project"      // worktree created inside this repo
        worktree_id="my-initiative"         // idempotent worktree identifier
        worktree_branch="existing-branch"   // optional: attach to existing branch
    ];
    // ... nodes ...
}
```

```python
class WorktreeManager:
    """Idempotent git worktree lifecycle manager."""

    def __init__(self, target_repo: Path):
        self.target_repo = target_repo
        self.worktree_root = target_repo / ".claude" / "worktrees"

    def get_or_create(self, initiative_id: str,
                      base_branch: str = "main",
                      existing_branch: str | None = None) -> Path:
        """Return existing worktree path or create a new one.
        If existing_branch is provided, attaches to that branch instead
        of creating a new one. Idempotent: safe to call repeatedly.
        """
        wt_path = self.worktree_root / initiative_id
        if wt_path.exists() and (wt_path / ".git").exists():
            return wt_path
        if existing_branch:
            subprocess.run(["git", "worktree", "add", str(wt_path), existing_branch],
                           cwd=self.target_repo, check=True)
        else:
            branch = f"worktree-{initiative_id}"
            subprocess.run(["git", "worktree", "add", "-b", branch, str(wt_path), base_branch],
                           cwd=self.target_repo, check=True)
        return wt_path

    def cleanup(self, initiative_id: str, force: bool = False) -> None:
        """Remove worktree. MUST be gated behind wait.human approval."""
        wt_path = self.worktree_root / initiative_id
        if wt_path.exists():
            subprocess.run(["git", "worktree", "remove", str(wt_path)]
                           + (["--force"] if force else []),
                           cwd=self.target_repo, check=True)

    def list(self) -> list[dict]:
        """List all managed worktrees with metadata."""
        ...

    def detect_stale(self, max_age_hours: int = 72) -> list[str]:
        """Find worktrees not used within max_age_hours."""
        ...
```

### 4.8 Programmatic Epic Closure Node

The `close` handler type enables automated epic completion within a pipeline:

```dot
close_epic [
    shape=octagon
    handler="close"
    label="Close: Push & PR"
    prompt="Push branch, create PR, report completion"
    status="pending"
];

wait_human_cleanup [
    shape=diamond
    handler="wait.human"
    label="Approve: Worktree Cleanup"
    status="pending"
];

close_epic -> wait_human_cleanup;
```

The `close` handler:
1. Pushes the worktree branch to remote
2. Creates a PR via GitHub CLI
3. Reports completion via signal file
4. **Does NOT cleanup worktree** — that requires `wait.human` approval

### 4.9 Specification Directory Structure (Post-Migration)

After E6 terminology migration, specifications use per-initiative directories:

```
docs/specs/
  cobuilder-upgrade/
    BS-COBUILDER-UPGRADE-001.md           # Business Specification
    TS-COBUILDER-UPGRADE-E0.md            # Technical Spec per epic
    TS-COBUILDER-UPGRADE-E1.md
    ...
  cobuilder-web/
    BS-COBUILDER-WEB-001.md
    TS-COBUILDER-WEB-E0.md
    ...
```

## 5. Technical Decisions

| ID | Decision | Rationale | Alternatives Considered |
|----|----------|-----------|------------------------|
| TD1 | **SDK over tmux for all dispatch** | Zero tmux complexity. AgentSDK provides structured output, error handling, and process management. | tmux (rejected: fragile, no structured output) |
| TD2 | **Named profiles in `providers.yaml`** | Centralizes provider config. DOT nodes stay clean (`llm_profile="anthropic-fast"`). Keys translate to Anthropic equivalents at dispatch time. | Inline DOT attrs (rejected: clutters graphs), vault (rejected: over-engineering) |
| TD3 | **Full branch merge of abstract-workflow-system** | 1,023 LOC of validated code (constraints, instantiator, manifest, state machine, middleware, ManagerLoopHandler). | Cherry-pick (rejected: fragile), rewrite (rejected: waste) |
| TD4 | **WorktreeManager as shared infrastructure** | Runner, CLI, and future web server all need worktree management. Single class prevents divergence. | Runner-only (rejected: duplication), CLI-only (rejected: runner needs programmatic access) |
| TD5 | **Parent monitors child signals (not just exit code)** | Prevents deadlock when child pipeline hits `wait.cobuilder` gate. Parent sees gate signal, handles it, writes response, child continues. | Simple `await proc.wait()` (rejected: deadlocks on gates) |
| TD6 | **Rename attractor→engine, extract to `.pipelines/`** | `cobuilder/engine/` is the natural package name (already contains state_machine, middleware). `.pipelines/` at repo root (gitignored) cleanly separates runtime state from version-controlled config. | Keep attractor (rejected: opaque jargon), `.runner/` (rejected: too generic) |
| TD7 | **Migrate PRD→BS, SD→TS** | Generalises terminology. Business Spec / Technical Spec are industry-neutral. Per-initiative directories group related specs. | Keep PRD/SD (rejected: project-specific jargon) |
| TD8 | **wait.human before pipeline launch (configurable)** | Safety default: guardian never launches pipelines without human approval. Configurable via `permissions.require_human_before_launch` in manifest for future autonomous operation. | Always require (rejected: blocks automation), never require (rejected: unsafe) |
| TD9 | **No backward compatibility** | We are the only users. Committing fully to the upgrade avoids carrying legacy patterns. All existing pipelines will be migrated. | Backward compat (rejected: maintenance burden for zero users) |

## 6. Non-Goals (Explicit Exclusions)

- **Web UI** — Covered by BS-COBUILDER-WEB-001. This spec provides backend infrastructure.
- **SSE event bridge** — Deferred to BS-COBUILDER-WEB-001 E3.
- **Multi-repo pipeline** — All nodes execute within one target repo (in worktrees). Cross-repo is future work.
- **LLM provider abstraction** — Profile keys pass through to `claude_code_sdk` as Anthropic equivalents. No abstraction layer.
- **Template marketplace** — Templates are committed to the repo and shareable with contributors, but there is no external registry or discovery mechanism.

## 7. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Observability optional instead of mandatory: Logfire is imported defensively and skipped if missing (see `_LOGFIRE_AVAILABLE` in runner), and no CI enforces span presence | High | High | E0.2 audits all spans; E5 CI enforces span presence via `CaptureLogfire` test assertions. Convert defensive imports to hard requirements in `cobuilder/engine/` package |
| Merge conflicts from abstract-workflow-system | Medium | Medium | Merge early (E0), resolve conflicts before new code |
| Child gate deadlock if signal monitoring fails | Low | High | E2E test: parent detects child `wait.cobuilder`, handles, child resumes |
| Profile `$VAR` resolution exposes secrets in logs | Medium | High | Sanitize env values in all log output; never log resolved api_key |
| Terminology migration breaks existing skills/hooks | Medium | Medium | Grep audit before migration; automated find-replace with test suite |
| GitHub publication leaks secrets from git history | Low | Critical | BFG repo cleaner + git-secrets pre-commit hook |
| Template constraints too rigid for edge cases | Medium | Low | Constraints are opt-in per manifest; unconstrained graphs still work |

## 8. Epics

### Phase 0: Foundation

#### Epic 0: Merge Template System + ManagerLoopHandler from abstract-workflow-system
**Goal**: Integrate the validated template system (1,023 LOC) and the existing ManagerLoopHandler implementation into `cobuilder/` package.

**Scope**:
- Merge `abstract-workflow-system` branch
- Resolve conflicts with current `cobuilder/` code
- Verify all existing tests pass
- Verify ManagerLoopHandler `spawn_pipeline` mode works (already implemented and tested)
- Add integration test: instantiate `sequential-validated` template → valid DOT output

**Sub-epics**:

**E0.1: Code Merge & Integration**
- Merge `abstract-workflow-system` branch into `cobuilder/`
- Resolve conflicts with current `cobuilder/` code
- Verify all existing tests pass
- Verify ManagerLoopHandler `spawn_pipeline` mode works (already implemented and tested)
- Add integration test: instantiate `sequential-validated` template → valid DOT output

**E0.2: Logfire Observability Preservation**
- **Goal**: Preserve ALL existing Logfire spans during the merge. The current `cobuilder/attractor/` layer has Logfire tracing (pipeline_runner.py, dispatch, session_runner). The `abstract-workflow-system` worktree's engine layer also has Logfire spans (middleware, event backend, runner). Both must survive the merge.
- Audit current Logfire instrumentation: 6 files in current codebase (engine middleware + event backend + runner + attractor dispatch layer)
- Audit worktree Logfire instrumentation: 4 files in abstract-workflow-system (engine middleware + event backend + runner — NO attractor/dispatch layer)
- Ensure all spans from BOTH codebases survive the merge without duplication or omission
- Add Logfire span assertions to merge validation tests using `logfire.testing.CaptureLogfire`
- **Gap to close**: The `cobuilder/attractor/` dispatch layer (pipeline_runner.py, guardian.py, session_runner.py) is NOT present in the abstract-workflow-system worktree — these Logfire spans must be explicitly carried forward during the rename to `cobuilder/engine/`
- **Colleague observation**: "Observability optional instead of mandatory: Logfire is imported defensively and skipped if missing (see `_LOGFIRE_AVAILABLE` in runner), and no CI enforces span presence." → Convert defensive `try/except` Logfire imports to hard requirements in `cobuilder/engine/` package; add `logfire` to `pyproject.toml` dependencies; add `CaptureLogfire` test assertions in CI

**E0.3: Test Coverage Baseline**
- **Goal**: Establish coverage measurement infrastructure and measure baseline before any refactoring.
- Configure `pytest-cov` with `pyproject.toml` settings:
  ```toml
  [tool.coverage.run]
  source = ["cobuilder"]
  omit = ["*/tests/*", "*/__pycache__/*"]

  [tool.coverage.report]
  fail_under = 0  # Baseline measurement only — gate enforced in E5
  show_missing = true
  exclude_lines = ["pragma: no cover", "if TYPE_CHECKING:"]
  ```
- Run baseline coverage measurement and record results
- Identify critical gaps (known: `engine/handlers/` at ~10%, `repomap/models/` at 0%, `repomap/serena/` at 33%)
- Create prioritized test gap backlog for downstream epics to consume

**Acceptance Criteria**:
- [ ] `cobuilder/templates/` directory exists with constraints.py, instantiator.py, manifest.py
- [ ] `cobuilder/engine/state_machine.py` and `middleware/constraint.py` present
- [ ] `cobuilder/engine/handlers/manager_loop.py` present with `spawn_pipeline` mode
- [ ] All existing tests pass (`pytest tests/`)
- [ ] New test: `test_template_instantiation` passes
- [ ] All Logfire spans from both codebases present in merged code (verified via `CaptureLogfire` assertions)
- [ ] No Logfire span regression: dispatch layer spans (pipeline_runner, guardian, session_runner) carried forward
- [ ] `pytest --cov=cobuilder --cov-report=term-missing` runs successfully and baseline recorded
- [ ] Test gap backlog created with priority-ordered list of under-tested modules

---

#### Epic 1: Per-Node LLM Configuration via Named Profiles
**Goal**: Enable per-node LLM provider switching via named profiles in `providers.yaml`.

**Scope**:
- Create `providers.yaml` schema and loader
- Add `_resolve_llm_config()` with 5-layer resolution
- Implement `_translate_profile()` mapping profile keys → Anthropic SDK equivalents
- Resolve `$VAR` env var references in profile values
- Add `handler_defaults` with `llm_profile` to manifest schema
- Sanitize api_key in all log output

**Acceptance Criteria**:
- [ ] DOT node with `llm_profile="anthropic-smart"` dispatches to Sonnet via profile lookup
- [ ] Profile `api_key: $OPENROUTER_API_KEY` resolves from environment
- [ ] Profile keys translate to Anthropic equivalents in worker env
- [ ] 5-layer fallback works: node → handler → manifest → env → runner default
- [ ] No api_key values appear in log output
- [ ] `providers.yaml` documented with example profiles for Anthropic + OpenRouter

---

#### Epic 2: Rename attractor→engine + Extract `.pipelines/`
**Goal**: Move Python code from `cobuilder/attractor/` to `cobuilder/engine/` and extract runtime state to `.pipelines/` at repo root (gitignored).

**Scope**:
- Move `pipeline_runner.py` → `cobuilder/engine/runner.py`
- Move `cli.py` → `cobuilder/engine/cli.py`
- Move handlers to `cobuilder/engine/handlers/`
- Create `.pipelines/` at repo root with `pipelines/`, `signals/`, `checkpoints/`
- Add `.pipelines/` to `.gitignore`
- Update `ATTRACTOR_SIGNAL_DIR` → `PIPELINE_SIGNAL_DIR` env var
- Update all imports across codebase
- Auto-migrate: if `.claude/attractor/` exists, move contents to `.pipelines/` on first run

**Acceptance Criteria**:
- [ ] `cobuilder/attractor/` no longer exists
- [ ] `cobuilder/engine/runner.py` is the pipeline runner
- [ ] `.pipelines/` in `.gitignore`
- [ ] `cobuilder pipeline status` reads from `.pipelines/`
- [ ] Template files remain in `.cobuilder/templates/` (version-controlled)
- [ ] All tests pass after migration

---

### Phase 1: Infrastructure

#### Epic 3: Stable Worktree Management
**Goal**: Ship `WorktreeManager` with idempotent lifecycle, existing-branch support, and DOT graph-level configuration.

**Scope**:
- Implement `WorktreeManager` in `cobuilder/worktrees/manager.py`
- Methods: `get_or_create(id, branch=, existing_branch=)`, `cleanup(id)`, `list()`, `detect_stale()`
- Cleanup ONLY after `wait.human` approval — never programmatic
- DOT graph-level config: `target_dir` and `worktree_id` as graph attributes
- Integrate into `cobuilder.engine.runner` `_get_target_dir()`
- CLI: `cobuilder worktree {get-or-create,cleanup,list,stale}`

**Acceptance Criteria**:
- [ ] `get_or_create("test-init")` creates worktree on first call
- [ ] `get_or_create("test-init")` returns same path on second call (idempotent)
- [ ] `get_or_create("test-init", existing_branch="feature-x")` attaches to existing branch
- [ ] `cleanup()` is never called programmatically — only via `wait.human`-gated pipeline node
- [ ] DOT graph `target_dir` attribute controls worktree location
- [ ] Runner uses WorktreeManager when `worktree_id` graph attr present

---

#### Epic 4: ManagerLoopHandler Upgrade — Child Signal Monitoring
**Goal**: Upgrade the existing ManagerLoopHandler to monitor child pipeline signals (not just exit code), preventing deadlocks on `wait.cobuilder` gates.

**Scope**:
- ManagerLoopHandler already exists (from E0 merge) with basic `spawn_pipeline`
- Add child signal directory monitoring: detect `wait.cobuilder` and `wait.human` gates
- When child hits `wait.cobuilder`: parent runs validation, writes response signal
- When child hits `wait.human`: parent surfaces to its own guardian (or writes signal)
- Configurable nesting depth per manifest (`constraints.nesting_constraint.max_depth`)
- Add `close` handler type for programmatic epic closure (push, PR)

**Acceptance Criteria**:
- [ ] Parent detects child `wait.cobuilder` gate and handles it (no deadlock)
- [ ] Parent detects child `wait.human` gate and surfaces appropriately
- [ ] Nesting depth exceeding manifest `max_depth` raises `MaxNestingDepthError`
- [ ] `close` handler pushes branch, creates PR, reports via signal
- [ ] Child gate handling has E2E test
- [ ] All Logfire observability spans maintained — ManagerLoopHandler upgrade must preserve existing engine spans and add new spans for child signal monitoring, gate detection, and nesting depth tracking
- [ ] Unit test coverage for `engine/handlers/` module reaches ≥80% (up from ~10% baseline)

---

### Phase 1.5: GitHub Publication

#### Epic 5: GitHub Publication Readiness
**Goal**: Prepare repo for public GitHub release.

**Scope**:
- **Secret scrubbing**: Remove API keys from `.mcp.json`, replace with `$ENV` references. Create `.mcp.json.example` with placeholders. Run `git-secrets` scan on full history. Add pre-commit hook.
- **LICENSE**: Choose and add license file (MIT or Apache 2.0)
- **CONTRIBUTING.md**: Contributor guide explaining 3-level agent hierarchy, MCP server setup, how to run tests, how to create templates
- **Onboarding**: "Getting Started" section in README.md with setup steps
- **CI/CD**: GitHub Actions workflow — linting (doc-gardener), pytest with coverage enforcement, template validation on PR. Badge in README.
- **Test coverage gate**: Enforce 90% minimum coverage in CI via `pytest --cov=cobuilder --cov-report=term-missing --cov-fail-under=90`
- **History cleanup**: BFG repo cleaner if secrets found in history. Stale branch cleanup.

**Test Coverage Strategy** (enforced in CI):
```toml
# pyproject.toml
[tool.coverage.run]
source = ["cobuilder"]
omit = ["*/tests/*", "*/__pycache__/*"]

[tool.coverage.report]
fail_under = 90
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "if __name__ == .__main__.",
]

[tool.coverage.html]
directory = "htmlcov"
```

**Test Management Best Practices** (documented in CONTRIBUTING.md):
1. **Test co-location**: Tests mirror source layout (`cobuilder/engine/runner.py` → `tests/engine/test_runner.py`)
2. **Fixture library**: Shared fixtures in `tests/conftest.py` and `tests/fixtures/` for DOT graphs, providers.yaml, manifest.yaml, mock signal files
3. **Parameterized tests**: Use `@pytest.mark.parametrize` for handler variations, profile resolution order, constraint types
4. **Test markers**: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.e2e` — CI runs unit+integration; e2e on demand
5. **Logfire span assertions**: Use `logfire.testing.CaptureLogfire` to verify observability in all handler tests
6. **Coverage-per-PR**: CI reports coverage diff on each PR — no PR may reduce overall coverage
7. **Priority test gaps** (from E0.3 baseline): engine/handlers (~10%), repomap/models (0%), repomap/serena (33%), orchestration/adapters (~25%)

**Acceptance Criteria**:
- [ ] `git-secrets --scan` returns clean on full history
- [ ] `.mcp.json` contains no plaintext API keys
- [ ] `.mcp.json.example` exists with placeholder values
- [ ] LICENSE file present
- [ ] CONTRIBUTING.md covers: architecture overview, setup, testing (including coverage requirements), template creation
- [ ] README.md has "Getting Started" section
- [ ] GitHub Actions CI runs on PR: lint + test + coverage enforcement (≥90%) + template-validate
- [ ] `pytest --cov-fail-under=90` passes in CI
- [ ] Coverage diff reported on each PR (no coverage regression allowed)
- [ ] No stale branches remaining

---

### Phase 2: Guardian & Templates

#### Epic 6: cobuilder-guardian Skill + Terminology Migration
**Goal**: Create unified `cobuilder-guardian` skill from `s3-guardian` + `system3-meta-orchestrator`. Migrate all terminology globally.

**Scope**:
- Merge `s3-guardian` skill + `system3-meta-orchestrator` output style → `cobuilder-guardian` skill
- Strip all legacy concepts: agent teams, sub agents, tmux spawning, system3
- Rename globally: `system3` → `cobuilder`, `wait.system3` → `wait.cobuilder`
- Update stop gate: `wait.system3` → `wait.cobuilder` in unified-stop-gate
- Migrate specification terminology: PRD → Business Spec (BS), SD → Technical Spec (TS)
- Create `docs/specs/` directory structure with per-initiative subdirectories
- Move existing PRDs/SDs to new locations with new prefixes
- Update all DOT node attributes: `prd_ref` → `bs_ref`, `sd_path` → `ts_path`

**Acceptance Criteria**:
- [ ] `cobuilder-guardian` skill exists and is invocable
- [ ] Zero references to "system3", "agent teams", "sub agents", or "tmux" in skills/output-styles
- [ ] `wait.cobuilder` works in all pipelines (stop gate, runner, CLI)
- [ ] `docs/specs/{initiative}/BS-*.md` and `TS-*.md` structure in place
- [ ] All existing specs migrated to new naming
- [ ] DOT node attributes use `bs_ref` and `ts_path`

---

#### Epic 7: cobuilder-lifecycle Template Hardening
**Goal**: Ship production-ready `cobuilder-lifecycle.dot.j2` template with full constraint enforcement.

**Scope**:
- Template: RESEARCH → REFINE → PLAN → wait.human → EXECUTE → VALIDATE → EVALUATE → CLOSE
- `wait.human` gate before EXECUTE (configurable via `permissions.require_human_before_launch`)
- Loop-back edge from EVALUATE to RESEARCH (conditional on score)
- `close` node: push, PR, cleanup (after wait.human)
- Manifest with `loop_constraint.max_iterations=3`
- ConstraintMiddleware blocks illegal transitions at runtime
- Guardian consumes stream summary after each node transition

**Acceptance Criteria**:
- [ ] Template instantiates with initiative parameters
- [ ] `wait.human` gate blocks before EXECUTE (when `require_human_before_launch=true`)
- [ ] ConstraintMiddleware blocks EXECUTE→RESEARCH (must go through EVALUATE)
- [ ] Loop counter increments on each EVALUATE→RESEARCH transition
- [ ] Pipeline terminates at `max_iterations`
- [ ] `close` node creates PR and gates cleanup behind wait.human

---

#### Epic 8: Hub-Spoke Template
**Goal**: Ship `hub-spoke.dot.j2` template for parallel worker patterns.

**Scope**:
- Central coordinator with N spoke workers (parameterized `spoke_count`)
- Manifest with topology constraint (star graph, single coordinator)
- Each spoke can have its own `llm_profile`
- Integration test: instantiate with spoke_count=3 → valid DOT

**Acceptance Criteria**:
- [ ] Hub-spoke template instantiates with `spoke_count` parameter
- [ ] Each spoke can reference a different `llm_profile`
- [ ] Template passes `cobuilder template validate`
- [ ] Template documented with usage examples

---

#### Epic 9: Template CLI
**Goal**: `cobuilder template {list,show,instantiate,validate}` commands.

**Scope**:
- `list`: show available templates with descriptions
- `show <name>`: display manifest + parameters
- `instantiate <name> --param key=value`: render DOT skeleton from template
- `validate <dot-file>`: check DOT against manifest constraints

**Acceptance Criteria**:
- [ ] `cobuilder template list` shows 3 templates (sequential-validated, cobuilder-lifecycle, hub-spoke)
- [ ] `cobuilder template instantiate sequential-validated --param initiative_id=test` produces valid DOT
- [ ] `cobuilder template validate bad-graph.dot` reports constraint violations

---

#### Epic 10: Stream Summarizer Sidecar
**Goal**: Rolling summary of pipeline execution, configurable model via `providers.yaml`.

**Scope**:
- Sidecar process watches signal directory for new events
- Model configurable via `defaults.handler_defaults.summarizer.llm_profile` in manifest
- Outputs human-readable summary to `{signal_dir}/summary.md`
- Guardian can consume summary after each node transition for decision context

**Acceptance Criteria**:
- [ ] Summary file updated within 30s of new signal
- [ ] Summary includes: current node, elapsed time, key decisions, blockers
- [ ] Summarizer model configurable via manifest (not hardcoded to Haiku)
- [ ] Guardian reads summary before making EVALUATE loop decisions

## 9. Implementation Status

| Epic | Status | Notes |
|------|--------|-------|
| E0: Merge Template System + ManagerLoopHandler | Not Started | 1,023 LOC + ManagerLoopHandler ready in abstract-workflow-system. Sub-epics: E0.1 Code Merge, E0.2 Logfire Preservation, E0.3 Coverage Baseline |
| E1: Per-Node LLM Profiles | Not Started | providers.yaml with named profiles |
| E2: Rename attractor→engine + .pipelines/ | Not Started | Package + runtime state extraction |
| E3: Stable Worktree Management | Not Started | Existing branch support, DOT graph-level config |
| E4: ManagerLoopHandler Upgrade | Not Started | Child signal monitoring (prevent gate deadlocks). Requires Logfire span preservation + 80% handler coverage |
| E5: GitHub Publication Readiness | Not Started | Secret scrubbing, LICENSE, CI/CD with 90% coverage gate |
| E6: cobuilder-guardian + Terminology Migration | Not Started | system3→cobuilder, PRD→BS, SD→TS |
| E7: cobuilder-lifecycle Template | Not Started | Self-driving guardian template |
| E8: Hub-Spoke Template | Not Started | Parallel worker patterns |
| E9: Template CLI | Not Started | list/show/instantiate/validate |
| E10: Stream Summarizer | Not Started | Configurable model, guardian-consumable |

## 10. Dependencies

| Epic | Depends On | Relationship |
|------|-----------|-------------|
| E0 | `abstract-workflow-system` branch | Source code |
| E1 | E0 | Profiles integrate with manifest schema from template system |
| E2 | E0 | Rename targets the merged codebase |
| E3 | E2 | WorktreeManager references `cobuilder.engine` package |
| E4 | E0, E2 | Upgrades ManagerLoopHandler in new package location |
| E5 | E2 | GitHub prep after codebase restructure |
| E6 | E5 | Terminology migration after GitHub structure is stable |
| E7 | E0, E4, E6 | Template uses engine + new terminology |
| E8 | E0, E6 | Template uses engine + new terminology |
| E9 | E0, E6 | CLI wraps template instantiation with new naming |
| E10 | E4 | Summarizer integrates with ManagerLoopHandler signal protocol |

## 11. Relationship to BS-COBUILDER-WEB-001

This spec provides **backend infrastructure** that the CoBuilder Web spec consumes:

| This Spec Provides | CoBuilder Web Consumes |
|-------------------|----------------------|
| `WorktreeManager` | Worktree endpoints |
| `EngineRunner` with per-node config | Pipeline launcher |
| Template instantiation | Initiative lifecycle — graph creation |
| Signal file protocol | SSE bridge — event source |

The two specs can be developed in parallel. CoBuilder Web depends on E3 (worktrees) and E1 (per-node config).
