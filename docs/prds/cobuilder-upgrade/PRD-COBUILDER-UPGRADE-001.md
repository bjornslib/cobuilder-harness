---
title: "CoBuilder Upgrade: Templates, Worktrees & Guardian Meta-Pipeline"
prd_id: PRD-COBUILDER-UPGRADE-001
status: draft
type: prd
created: 2026-03-14
last_verified: 2026-03-14
grade: authoritative
owner: theb
---

# PRD-COBUILDER-UPGRADE-001: CoBuilder Upgrade — Templates, Worktrees & Guardian Meta-Pipeline

## 1. Problem Statements

| ID | Problem | Impact |
|----|---------|--------|
| P1 | **No reusable pipeline topologies.** Every initiative requires hand-crafting a DOT graph from scratch. Common patterns (research-refine-codergen, hub-spoke validation) are copy-pasted and diverge over time. | Slow initiative boot, topology bugs, inconsistent gate placement |
| P2 | **No stable worktree management.** Worktrees are created ad-hoc via shell commands. No idempotent `get_or_create`, no lifecycle tracking, no cleanup. Stale worktrees accumulate and confuse agents. | Disk waste, branch pollution, agent confusion when worktrees vanish mid-run |
| P3 | **No Guardian meta-pipeline.** System 3's lifecycle (research → refine → plan → execute → validate → evaluate) is implicit in the output style prose. There is no executable representation that can be paused, resumed, inspected, or looped. | No audit trail of S3 decisions, no bounded retry, no programmatic introspection |
| P4 | **No per-node LLM configuration.** All workers in a pipeline use the same model, API key, and base URL. Cannot mix providers (Anthropic, OpenRouter, local) or models (Haiku for research, Opus for codergen) within one pipeline. | Over-spend on cheap tasks, cannot leverage specialized models, single-provider lock-in |
| P5 | **Attractor state mixed into `.claude/`.** Pipeline DOT files, signal files, and transition logs live under `.claude/attractor/`. This repo ships publicly on GitHub — runtime state files would pollute the published repo. | Signal files, DOT state, and ops logs committed accidentally; `.gitignore` rules fragile and spread across subdirectories |

## 2. Goals

| ID | Goal | Success Metric | Priority |
|----|------|---------------|----------|
| G1 | **Template library**: Ship 3+ parameterized DOT templates (sequential-validated, hub-spoke, s3-lifecycle) with Jinja2 rendering and `manifest.yaml` constraints | Templates instantiate valid DOT graphs; `cobuilder template list` shows 3+ entries | P0 |
| G2 | **Constraint enforcement**: Static constraints (topology, path, loop bounds) validated at instantiation; dynamic constraints (NodeStateMachine) enforced at runtime via ConstraintMiddleware | Invalid graphs rejected before dispatch; illegal transitions blocked with clear error | P0 |
| G3 | **Stable worktrees**: `WorktreeManager.get_or_create(initiative_id)` returns a worktree path idempotently. Cleanup via `WorktreeManager.cleanup(initiative_id)` with force and stale-detection options | Zero stale worktrees after pipeline completion; worktree survives runner restart | P0 |
| G4 | **Self-driving Guardian**: S3 lifecycle encoded as a DOT template (`s3-lifecycle.dot.j2`). ManagerLoopHandler reads the graph and drives RESEARCH → REFINE → PLAN → EXECUTE → VALIDATE → EVALUATE with bounded loops | Guardian pipeline runs autonomously for 1+ full cycle; loop count tracked and bounded | P1 |
| G5 | **Child pipeline spawning via SDK**: ManagerLoopHandler's EXECUTE node spawns a child `EngineRunner` via `asyncio.create_subprocess_exec` (calling `pipeline_runner.py --dot-file`). Parent waits for child exit code. No tmux. | Child pipeline completes and parent resumes; zero tmux sessions created | P0 |
| G6 | **Per-node LLM config via named profiles**: Each DOT node references an `llm_profile` name defined in `providers.yaml`. Profiles map to Anthropic SDK equivalents (`model` → `ANTHROPIC_MODEL`, `api_key` → `ANTHROPIC_API_KEY`, `base_url` → `ANTHROPIC_BASE_URL`). Resolution order: node profile → handler defaults → manifest defaults → env vars → runner defaults | Mixed-model pipeline runs successfully; Haiku research + Sonnet codergen in same graph | P1 |
| G7 | **Bounded loops**: `loop_constraint` in manifest caps iteration count. ManagerLoopHandler tracks loop counter and transitions to EXIT when bound reached | Loop terminates at bound; counter visible in pipeline status output | P1 |
| G8 | **Backward compatibility**: Existing pipelines (no templates, no per-node config) continue to work unchanged. New features are opt-in via DOT attributes and manifest files | All existing `acceptance-tests/` pass without modification | P0 |

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|-------------|-----------|
| US1 | System 3 meta-orchestrator | instantiate a pipeline from a template with parameters | I don't hand-craft DOT graphs for common patterns |
| US2 | Pipeline runner | resolve model/key/url per node at dispatch time | I can mix Haiku research with Sonnet implementation in one graph |
| US3 | System 3 meta-orchestrator | have my lifecycle (research→plan→execute→validate) be a runnable pipeline | my decisions are auditable and my process is bounded |
| US4 | Pipeline runner | spawn a child pipeline from a parent node and wait for completion | the Guardian's EXECUTE node can launch implementation pipelines |
| US5 | Developer | run `cobuilder worktree get-or-create my-initiative` and get a stable path | worktrees are idempotent and survive restarts |
| US6 | Pipeline runner | reject a graph that violates template constraints at instantiation | topology bugs are caught before any worker is dispatched |

## 4. Architecture

### 4.1 Three Pillars

```
┌─────────────────────────────────────────────────────────────┐
│                    PILLAR 1: TEMPLATES                       │
│  .cobuilder/templates/{name}/                                │
│    template.dot.j2    — Jinja2 parameterized DOT             │
│    manifest.yaml      — parameters, constraints, defaults    │
│    README.md          — human docs                           │
│                                                              │
│  Instantiator: manifest + params → rendered .dot             │
│  Constraints: topology, path, loop, node_state_machine       │
├─────────────────────────────────────────────────────────────┤
│                    PILLAR 2: WORKTREES                        │
│  WorktreeManager (shared between runner + CLI + web server)  │
│    get_or_create(id) → path   (idempotent)                   │
│    cleanup(id)                (force + stale detection)       │
│    list() → [{id, path, branch, created, last_used}]         │
│    Storage: {target_repo}/.claude/worktrees/{id}/            │
├─────────────────────────────────────────────────────────────┤
│                    PILLAR 3: GUARDIAN META-PIPELINE           │
│  s3-lifecycle.dot.j2 — RESEARCH→REFINE→PLAN→EXECUTE→        │
│                         VALIDATE→EVALUATE (with loop-back)   │
│  ManagerLoopHandler: drives the lifecycle graph               │
│    spawn_pipeline mode: EXECUTE spawns child EngineRunner     │
│    All dispatch via SDK (asyncio.create_subprocess_exec)      │
│    Loop counter tracked, bounded by loop_constraint           │
└─────────────────────────────────────────────────────────────┘
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

#### DOT Node Usage

```dot
research_backend [
    shape=tab
    handler="research"
    label="Research: Backend Patterns"
    llm_profile="anthropic-fast"
    status="pending"
];

codergen_backend [
    shape=box
    handler="codergen"
    label="Implement: Backend Service"
    llm_profile="anthropic-smart"
    status="pending"
];
```

#### Profile-to-Anthropic Translation

All profile keys translate to their Anthropic SDK equivalents at dispatch time:

| Profile Key | Anthropic SDK Equivalent | Environment Variable |
|-------------|--------------------------|---------------------|
| `model` | `model` in `ClaudeCodeOptions` | `ANTHROPIC_MODEL` |
| `api_key` | `ANTHROPIC_API_KEY` in worker env | `ANTHROPIC_API_KEY` |
| `base_url` | `ANTHROPIC_BASE_URL` in worker env | `ANTHROPIC_BASE_URL` |

This means any provider (OpenRouter, local proxy, etc.) works as long as it speaks the Anthropic API protocol. The runner always sets `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` in the worker's environment — the worker itself is unaware of provider identity.

#### Resolution Order (first non-null wins)

1. **Node `llm_profile`** — profile name on the DOT node → look up in `providers.yaml`
2. **Handler defaults** — `defaults.handler_defaults.{handler_type}` in `manifest.yaml`
3. **Manifest defaults** — `defaults.llm_profile` in `manifest.yaml` → look up in `providers.yaml`
4. **Environment variables** — `ANTHROPIC_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`
5. **Runner defaults** — hardcoded fallback in `pipeline_runner.py`

#### Runner Implementation (in `_dispatch_worker()`)

```python
def _resolve_llm_config(self, node_attrs: dict) -> dict:
    """Resolve per-node LLM config via named profile with 5-layer fallback."""
    profile_name = node_attrs.get("llm_profile")

    # Layer 1: Node profile
    if profile_name:
        profile = self._providers.get(profile_name)
        if profile:
            return self._translate_profile(profile)

    # Layer 2: Handler defaults
    handler = node_attrs.get("handler", "codergen")
    handler_profile = self._manifest_handler_defaults.get(handler, {}).get("llm_profile")
    if handler_profile:
        profile = self._providers.get(handler_profile)
        if profile:
            return self._translate_profile(profile)

    # Layer 3: Manifest default profile
    default_profile = self._manifest_defaults.get("llm_profile")
    if default_profile:
        profile = self._providers.get(default_profile)
        if profile:
            return self._translate_profile(profile)

    # Layer 4-5: Env vars and runner defaults
    return {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
        "base_url": os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
    }

def _translate_profile(self, profile: dict) -> dict:
    """Translate profile keys to Anthropic SDK equivalents, resolving env vars."""
    def resolve(val: str) -> str:
        if val and val.startswith("$"):
            return os.environ.get(val[1:], "")
        return val or ""

    return {
        "model": resolve(profile.get("model", "")),
        "api_key": resolve(profile.get("api_key", "")),
        "base_url": resolve(profile.get("base_url", "https://api.anthropic.com")),
    }
```

### 4.3 Guardian Meta-Pipeline (SDK Mode)

```
System 3 (LLM, Opus)
    │
    ├── Instantiates s3-lifecycle.dot.j2 with initiative params
    │
    ├── Launches EngineRunner(dot_file="s3-lifecycle.dot")
    │       │
    │       ├── RESEARCH node → Haiku worker (context7 + perplexity)
    │       ├── REFINE node → Sonnet worker (rewrite SD with findings)
    │       ├── PLAN node → Sonnet worker (generate child pipeline DOT)
    │       ├── EXECUTE node → ManagerLoopHandler.spawn_pipeline()
    │       │       │
    │       │       └── Child EngineRunner(dot_file="impl-pipeline.dot")
    │       │               ├── acceptance_test_writer → Haiku
    │       │               ├── research_sd_be → Haiku
    │       │               ├── refine_sd_be → Sonnet
    │       │               ├── codergen_be → Sonnet (or Opus)
    │       │               ├── wait_system3_e2e → validation-test-agent
    │       │               └── wait_human_review → signal file
    │       │
    │       ├── VALIDATE node → validation-test-agent (Gherkin E2E)
    │       └── EVALUATE node → Haiku (score + loop decision)
    │               │
    │               └── Loop back to RESEARCH if score < threshold
    │                   (bounded by loop_constraint.max_iterations)
    │
    └── Monitors via signal files + DOT mtime (Haiku sidecar)
```

**All dispatch is SDK-based.** `EngineRunner` calls `claude_code_sdk.query()` for each node. The EXECUTE node's `ManagerLoopHandler` launches a child `EngineRunner` as a subprocess:

```python
# In ManagerLoopHandler.spawn_pipeline()
child_dot = self._generate_child_pipeline(initiative_params)
proc = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "cobuilder.attractor.pipeline_runner",
    "--dot-file", str(child_dot),
    "--signal-dir", str(child_signal_dir),
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=child_env,
)
exit_code = await proc.wait()
```

### 4.4 Template Manifest Extensions

The existing `manifest.yaml` schema (from `abstract-workflow-system`) is extended with LLM defaults:

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
  llm_profile: "anthropic-fast"          # Default profile for all nodes
  providers_file: "providers.yaml"        # Path to profile definitions
  handler_defaults:                       # Per-handler profile overrides
    codergen:
      llm_profile: "anthropic-smart"
    research:
      llm_profile: "anthropic-fast"
    refine:
      llm_profile: "anthropic-smart"

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
    loop_nodes: ["evaluate", "research"]  # evaluate can loop back to research

  nesting_constraint:
    max_depth: 2                          # configurable per template (default 2)
    # 0 = this pipeline only, 1 = can spawn children, 2 = children can spawn grandchildren
```

### 4.5 WorktreeManager Integration

`WorktreeManager` is shared infrastructure used by:
- `pipeline_runner.py` — creates worktree before dispatching workers
- `cobuilder worktree` CLI — manual worktree management
- Future: CoBuilder web server (PRD-COBUILDER-WEB-001)

```python
class WorktreeManager:
    """Idempotent git worktree lifecycle manager."""

    def __init__(self, target_repo: Path):
        self.target_repo = target_repo
        self.worktree_root = target_repo / ".claude" / "worktrees"

    def get_or_create(self, initiative_id: str, base_branch: str = "main") -> Path:
        """Return existing worktree path or create a new one.
        Idempotent: safe to call multiple times for same initiative_id.
        """
        wt_path = self.worktree_root / initiative_id
        if wt_path.exists() and (wt_path / ".git").exists():
            return wt_path
        branch = f"worktree-{initiative_id}"
        # Create branch if needed, then worktree
        subprocess.run(["git", "worktree", "add", "-b", branch, str(wt_path), base_branch],
                       cwd=self.target_repo, check=True)
        return wt_path

    def cleanup(self, initiative_id: str, force: bool = False) -> None:
        """Remove worktree and optionally delete branch."""
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

## 5. Technical Decisions

| ID | Decision | Rationale | Alternatives Considered |
|----|----------|-----------|------------------------|
| TD1 | **SDK over tmux for all dispatch** | Zero tmux complexity. AgentSDK (`claude_code_sdk.query()`) provides structured output, error handling, and process management. tmux is retained only for human-interactive observation (explicit user request). | tmux (rejected: fragile send-keys, timing issues, no structured output) |
| TD2 | **Per-node LLM config via named profiles in `providers.yaml`** | Profiles centralize provider configuration. DOT nodes reference profiles by name (`llm_profile="anthropic-fast"`), keeping graphs clean. Profile keys translate to Anthropic SDK equivalents at dispatch time — any provider speaking the Anthropic protocol works transparently. Env var references (`$ANTHROPIC_API_KEY`) prevent plaintext secrets. | Inline DOT attrs (rejected: clutters graphs, duplicates config), vault integration (rejected: over-engineering for current scale) |
| TD3 | **Merge abstract-workflow-system branch** | 1,023 LOC of validated template system (constraints, instantiator, manifest, state machine, middleware). Cherry-picking would lose test coverage and create merge conflicts. | Cherry-pick (rejected: partial, fragile), rewrite (rejected: waste of validated code) |
| TD4 | **WorktreeManager as shared infrastructure** | Both `pipeline_runner.py` and future web server need worktree management. Single class prevents divergent implementations. Owned by `cobuilder/` package. | Runner-only (rejected: web server would duplicate), CLI-only (rejected: runner needs programmatic access) |
| TD5 | **EngineRunner spawns child runners as subprocess** | Clean process isolation. Parent EngineRunner awaits child exit code. Child gets its own signal directory. No shared mutable state. | In-process (rejected: shared state bugs), thread pool (rejected: GIL, no isolation) |
| TD6 | **Extract `.attractor/` to repo root, gitignored** | Pipeline runtime state (DOT files, signals, transitions) is NOT configuration — it's ephemeral execution state. Mixing it into `.claude/` risks accidental commits to the public GitHub repo. Top-level `.attractor/` with `.gitignore` entry cleanly separates config (version-controlled) from state (ephemeral). | Keep in `.claude/` with nested .gitignore (rejected: fragile, easy to miss subdirs), XDG data dir (rejected: loses locality) |

## 6. Non-Goals (Explicit Exclusions)

- **Web UI** — Covered by PRD-COBUILDER-WEB-001. This PRD provides the backend infrastructure that the web UI will consume.
- **SSE event bridge** — Deferred to PRD-COBUILDER-WEB-001 E3.
- **Template marketplace / sharing** — Out of scope. Templates are local to the repo.
- **Multi-repo pipeline** — All nodes execute within one target repo (possibly in worktrees). Cross-repo orchestration is future work.
- **LLM provider abstraction** — We pass `model`, `api_key`, `base_url` through to `claude_code_sdk`. No provider-agnostic wrapper.

## 7. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Merge conflicts from abstract-workflow-system | Medium | Medium | Merge early (E0), resolve conflicts before new code |
| Child pipeline exit code doesn't propagate cleanly | Low | High | E2E test: parent detects child failure and transitions to FAILED |
| `$ENV:` resolution exposes secrets in logs | Medium | High | Sanitize env values in all log output; never log resolved api_key |
| Template constraints too rigid for edge cases | Medium | Low | Constraints are opt-in per manifest; unconstrained templates still work |
| Nested pipeline depth causes resource exhaustion | Low | Medium | Configurable `nesting_constraint.max_depth` per manifest (default 2); enforced in ManagerLoopHandler |

## 8. Epics

### Phase 1: Foundation (P0 — Must Have)

#### Epic 0: Merge Template System from abstract-workflow-system
**Goal**: Integrate the validated 1,023 LOC template system into `cobuilder/` package on the main branch.

**Scope**:
- Merge `abstract-workflow-system` branch into this worktree
- Resolve any conflicts with current `cobuilder/` code
- Verify all existing tests pass
- Add integration test: instantiate `sequential-validated` template → valid DOT output

**Acceptance Criteria**:
- [ ] `cobuilder/templates/` directory exists with constraints.py, instantiator.py, manifest.py
- [ ] `cobuilder/engine/state_machine.py` and `middleware/constraint.py` present
- [ ] All existing tests pass (`pytest tests/`)
- [ ] New test: `test_template_instantiation` passes

---

#### Epic 1: Per-Node LLM Configuration via Named Profiles
**Goal**: Enable per-node LLM provider switching via named profiles in `providers.yaml`.

**Scope**:
- Create `providers.yaml` schema and loader
- Add `_resolve_llm_config()` to `pipeline_runner.py` with 5-layer resolution
- Implement `_translate_profile()` to map profile keys → Anthropic SDK equivalents
- Resolve `$VAR` env var references in profile values
- Add `handler_defaults` with `llm_profile` to manifest schema
- Sanitize api_key in all log output

**Acceptance Criteria**:
- [ ] DOT node with `llm_profile="anthropic-smart"` dispatches to Sonnet via profile lookup
- [ ] Profile `api_key: $OPENROUTER_API_KEY` resolves from environment
- [ ] Profile keys translate to Anthropic equivalents (`api_key` → `ANTHROPIC_API_KEY` in worker env)
- [ ] Missing profile falls back through handler defaults → manifest defaults → env vars → runner defaults
- [ ] No api_key values appear in log output
- [ ] Manifest `handler_defaults.{handler}.llm_profile` overrides per handler type
- [ ] `providers.yaml` documented with example profiles for Anthropic + OpenRouter

---

#### Epic 2: Stable Worktree Management
**Goal**: Ship `WorktreeManager` with idempotent lifecycle and integrate into `pipeline_runner.py`.

**Scope**:
- Implement `WorktreeManager` class in `cobuilder/worktrees/manager.py`
- Methods: `get_or_create()`, `cleanup()`, `list()`, `detect_stale()`
- Integrate into `pipeline_runner.py._get_target_dir()`
- CLI: `cobuilder worktree {get-or-create,cleanup,list,stale}`
- Storage: `{target_repo}/.claude/worktrees/{initiative_id}/`

**Acceptance Criteria**:
- [ ] `get_or_create("test-init")` creates worktree on first call
- [ ] `get_or_create("test-init")` returns same path on second call (idempotent)
- [ ] `cleanup("test-init")` removes worktree and branch
- [ ] `detect_stale(max_age_hours=0)` finds newly created worktrees
- [ ] `pipeline_runner.py` uses WorktreeManager when `worktree_id` DOT attr present
- [ ] CLI commands work: `cobuilder worktree list` shows managed worktrees

---

#### Epic 3: ManagerLoopHandler — spawn_pipeline Mode
**Goal**: EXECUTE node in a parent pipeline spawns a child `EngineRunner` via subprocess.

**Scope**:
- Implement `ManagerLoopHandler` in `cobuilder/engine/handlers/manager_loop.py`
- `spawn_pipeline` mode: `asyncio.create_subprocess_exec` launching `pipeline_runner.py --dot-file`
- Child signal directory: `{parent_signal_dir}/{node_id}/`
- Parent awaits child exit code; maps to node status (0=impl_complete, non-zero=failed)
- Nesting depth limit configurable per manifest (`constraints.nesting.max_depth`, default 2)

**Acceptance Criteria**:
- [ ] Parent pipeline EXECUTE node spawns child runner
- [ ] Child runner completes and parent node transitions to impl_complete
- [ ] Child failure (exit code != 0) transitions parent node to failed
- [ ] Nesting depth exceeding manifest `max_depth` (default 2) raises `MaxNestingDepthError`
- [ ] Child inherits per-node LLM config from parent EXECUTE node

---

### Phase 2: Guardian & Constraints (P1 — Should Have)

#### Epic 4: s3-lifecycle Template Hardening
**Goal**: Ship production-ready `s3-lifecycle.dot.j2` template with full constraint enforcement.

**Scope**:
- Finalize `s3-lifecycle.dot.j2` with RESEARCH→REFINE→PLAN→EXECUTE→VALIDATE→EVALUATE
- Loop-back edge from EVALUATE to RESEARCH (conditional on score)
- Manifest with `loop_constraint.max_iterations=3`
- ConstraintMiddleware blocks illegal transitions at runtime
- Integration test: full lifecycle with mock workers

**Acceptance Criteria**:
- [ ] Template instantiates with initiative parameters
- [ ] ConstraintMiddleware blocks EXECUTE→RESEARCH (must go through EVALUATE)
- [ ] Loop counter increments on each EVALUATE→RESEARCH transition
- [ ] Pipeline terminates when loop_constraint.max_iterations reached
- [ ] Status output shows current loop iteration

---

#### Epic 5: Stream Summarizer Sidecar
**Goal**: Haiku-based rolling summary of pipeline execution for human consumption.

**Scope**:
- Sidecar process watches signal directory for new events
- Feeds events to Haiku with rolling context window
- Outputs human-readable summary to `{signal_dir}/summary.md`
- Cost target: ~$0.015/hour (Haiku input pricing)

**Acceptance Criteria**:
- [ ] Summary file updated within 30s of new signal
- [ ] Summary includes: current node, elapsed time, key decisions, blockers
- [ ] Cost per hour stays under $0.02

---

#### Epic 6: Hub-Spoke Template
**Goal**: Ship `hub-spoke.dot.j2` template for parallel worker patterns.

**Scope**:
- `hub-spoke.dot.j2`: central coordinator with N spoke workers (parameterized `spoke_count`)
- Manifest with topology constraint (star graph, single coordinator)
- Each spoke can have its own `llm_profile`
- Integration test: instantiate with spoke_count=3 → valid DOT

**Acceptance Criteria**:
- [ ] Hub-spoke template instantiates with `spoke_count` parameter
- [ ] Each spoke can reference a different `llm_profile`
- [ ] Template passes `cobuilder template validate`
- [ ] Template documented with usage examples

---

### Phase 3: CLI & Extraction (P0/P1)

#### Epic 7: Template CLI
**Goal**: `cobuilder template {list,show,instantiate,validate}` commands.

**Scope**:
- `list`: show available templates with descriptions
- `show <name>`: display manifest + parameters
- `instantiate <name> --param key=value`: render DOT from template
- `validate <dot-file>`: check DOT against manifest constraints

**Acceptance Criteria**:
- [ ] `cobuilder template list` shows 3+ templates (sequential-validated, s3-lifecycle, hub-spoke)
- [ ] `cobuilder template instantiate sequential-validated --param initiative_id=test` produces valid DOT
- [ ] `cobuilder template validate bad-graph.dot` reports constraint violations

---

#### Epic 8: Extract `.attractor/` from `.claude/`
**Goal**: Move pipeline runtime state (DOT files, signals, transitions, ops logs) from `.claude/attractor/` to a top-level `.attractor/` directory, excluded from version control.

**Scope**:
- Create `.attractor/` at repo root with subdirectories: `pipelines/`, `signals/`, `checkpoints/`
- Update all references in `pipeline_runner.py`, `cobuilder` CLI, and s3-guardian skill
- Add `.attractor/` to `.gitignore`
- Migrate existing `.claude/attractor/pipelines/` content to `.attractor/pipelines/`
- Update `ATTRACTOR_SIGNAL_DIR` env var default from `.claude/attractor/signals/` to `.attractor/signals/`
- Preserve `.cobuilder/templates/` (these are version-controlled assets, NOT runtime state)
- Backward compat: if `.claude/attractor/` exists and `.attractor/` does not, auto-migrate on first run

**Acceptance Criteria**:
- [ ] `.attractor/` exists at repo root after first pipeline run
- [ ] `.attractor/` is in `.gitignore` — `git status` never shows signal files
- [ ] `pipeline_runner.py` reads/writes DOT files in `.attractor/pipelines/`
- [ ] `cobuilder pipeline status` reads from `.attractor/`
- [ ] `cobuilder pipeline create` writes to `.attractor/pipelines/`
- [ ] Template files remain in `.cobuilder/templates/` (version-controlled)
- [ ] Auto-migration moves `.claude/attractor/` → `.attractor/` on first run
- [ ] All existing tests pass after migration

## 9. Implementation Status

| Epic | Status | Notes |
|------|--------|-------|
| E0: Merge Template System | Not Started | 1,023 LOC ready in abstract-workflow-system branch |
| E1: Per-Node LLM Profiles | Not Started | Named profiles in providers.yaml |
| E2: Stable Worktrees | Not Started | |
| E3: ManagerLoopHandler | Not Started | |
| E4: s3-lifecycle Hardening | Not Started | |
| E5: Stream Summarizer | Not Started | |
| E6: Hub-Spoke Template | Not Started | Moved to Phase 2 (user: ship all 3 templates) |
| E7: Template CLI | Not Started | |
| E8: Extract .attractor/ | Not Started | Decouple runtime state from .claude/ for public GitHub |

## 10. Dependencies

| This PRD | Depends On | Relationship |
|----------|-----------|-------------|
| E0 | `abstract-workflow-system` branch | Source of template system code |
| E1 | E0 | Per-node config reads manifest defaults from template system |
| E2 | — | Independent (can parallel with E0-E1) |
| E3 | E1, E2 | Child pipeline needs per-node config + worktree |
| E4 | E0, E3 | s3-lifecycle template needs template system + spawn_pipeline |
| E5 | E3 | Summarizer watches child pipeline signals |
| E6 | E0 | Hub-spoke template uses template system |
| E7 | E0 | CLI wraps template instantiation |
| E8 | — | Independent (can parallel with E0-E3, but should precede E4+ to avoid double-migration) |

## 11. Relationship to PRD-COBUILDER-WEB-001

This PRD provides **backend infrastructure** that PRD-COBUILDER-WEB-001 consumes:

| This PRD Provides | CoBuilder Web Consumes |
|-------------------|----------------------|
| `WorktreeManager` | E0 (worktree endpoints) |
| `EngineRunner` with per-node config | E6 (pipeline launcher) |
| Template instantiation | E1 (initiative lifecycle — graph creation) |
| Signal file protocol | E3 (SSE bridge — event source) |

The two PRDs can be developed in parallel. CoBuilder Web depends on this PRD's E2 (worktrees) and E1 (per-node config) being complete before its E0 and E6 respectively.
