---
prd_id: PRD-COBUILDER-001
title: "CoBuilder: Unified Pipeline with RepoMap Integration"
status: active
created: 2026-02-27
last_verified: 2026-02-27
grade: authoritative
---

# PRD-COBUILDER-001: CoBuilder — Unified Pipeline with RepoMap Integration

## 1. Executive Summary

CoBuilder consolidates two systems that currently operate in parallel — the Attractor DOT pipeline (execution engine) and ZeroRepo (codebase graph) — into a single, cohesive package. The renamed components (Attractor → CoBuilder, ZeroRepo → RepoMap) reflect a unified tool that maps codebases, generates intelligent execution pipelines, and keeps baselines current throughout implementation.

The core insight: **a map of the codebase is essential for every stage of the development pipeline** — from solution design through task decomposition, orchestrator dispatch, and post-implementation validation. Today that map exists (RepoMap) but isn't wired into the pipeline (CoBuilder). This PRD bridges that gap.

## 2. Goals

| ID | Goal | Success Metric |
|----|------|---------------|
| G1 | Solution Designs receive codebase context automatically | 100% of SDs include RepoMap YAML context before authoring |
| G2 | Pipeline generation uses codebase graph as primary source | DOT nodes carry file_path, delta_status, interfaces from RepoMap |
| G3 | Baselines stay current during implementation | Baseline refreshed within 60s of each node validation |
| G4 | Single `cobuilder` CLI unifies all operations | One entry point for repomap, pipeline, and orchestration commands |
| G5 | Task Master receives codebase context | Task decomposition produces file-path-specific, delta-aware tasks |

## 3. User Stories

### US-1: Guardian Designing an Initiative
As a guardian, I want to run `cobuilder repomap init` on the target repo and have the codebase context automatically injected into the SD creation prompt, so that the solution-design-architect produces technically accurate specifications grounded in the actual codebase.

### US-2: System 3 Generating a Pipeline
As System 3, I want to run `cobuilder pipeline create --sd SD-AUTH-001.md --repo agencheck` and get a fully enriched DOT pipeline where each node carries precise file scope, LLM-crafted acceptance criteria, and delta classification, so that orchestrators receive implementation-ready work packages.

### US-3: Orchestrator Completing a Node
As an orchestrator, when my workers complete a node and it transitions to `validated`, I want the RepoMap baseline to automatically refresh for the affected files, so that subsequent nodes and future initiatives see the current codebase state.

### US-4: Guardian Spawning Orchestrators
As a guardian spawning orchestrators in tmux, I want each orchestrator's worktree to already contain the RepoMap baseline (via git), so that no manual init step is required before work begins.

## 4. Epic 1: CoBuilder Foundation — Rename, Consolidate, Central Storage

**Goal**: Establish the `cobuilder/` top-level package with RepoMap integrated, `.repomap/` committed for central baseline storage, and YAML as the default output format.

### Scope

- Rename: `src/zerorepo/` → `cobuilder/repomap/`
- Rename: `.claude/scripts/attractor/` → `cobuilder/pipeline/` + `cobuilder/orchestration/`
- Create: `.repomap/` at project root (committed to git) with config.yaml, manifests/, baselines/
- Create: `cobuilder/cli.py` as main entry point with `__main__.py`
- Create: `cobuilder/bridge.py` — RepoMap ↔ Pipeline adapter
- CLI subcommands: `cobuilder repomap init`, `cobuilder repomap sync`, `cobuilder repomap status`, `cobuilder repomap context`
- Default output format: YAML (with markdown values for narrative fields)
- All config/manifests in YAML; baselines remain JSON (machine-generated graph data)

### Acceptance Criteria

- [ ] `cobuilder repomap init --target-dir /path --name repo` creates baseline and stores in `.repomap/baselines/<repo>/`
- [ ] `cobuilder repomap context --name repo --prd PRD-ID` outputs YAML-formatted codebase context
- [ ] `cobuilder repomap status` shows all tracked repos with node counts and last sync time
- [ ] `.repomap/config.yaml` committed to git with repo registry
- [ ] All existing attractor CLI commands work via `cobuilder` entry point
- [ ] All existing zerorepo commands work via `cobuilder repomap` subgroup
- [ ] Existing tests pass after rename (import path updates)

## 5. Epic 2: RepoMap-Native Pipeline Generation with LLM Enrichment

**Goal**: `cobuilder pipeline create` generates DOT pipelines from RepoMap as the primary source, enriched by LLM intelligence for file scoping, acceptance criteria, dependency inference, and worker selection.

### Scope

- RepoMap-native generation: no `--rpg-source` opt-in flag; RepoMap IS the source
- Auto-init: if no baseline exists, automatically run `repomap init` before generation
- LLM enrichment pipeline: FileScoper → AcceptanceCrafter → DependencyInferrer → WorkerSelector → ComplexitySizer
- Beads as secondary enrichment: auto-matched to RepoMap nodes for bead_id + priority
- SD annotation: each DOT node carries `solution_design` attribute pointing to its SD section
- SD v2 enrichment: after pipeline generation, update the SD file with TaskMaster task IDs, DOT node IDs, enriched file scope, and acceptance criteria
- Single command: `cobuilder pipeline create --sd SD-FILE.md --repo REPO` chains TaskMaster → Beads → DOT → SD enrichment
- TaskMaster integration via Python subprocess (not MCP)

### Acceptance Criteria

- [ ] `cobuilder pipeline create --sd SD-AUTH-001.md --repo agencheck` produces valid DOT pipeline
- [ ] Each DOT node carries: `file_path`, `delta_status`, `interfaces`, `change_summary`, `worker_type`, `solution_design`
- [ ] Worker type selection uses LLM (not keyword heuristic) and is more accurate than current regex
- [ ] TaskMaster receives RepoMap YAML context appended to SD input
- [ ] SD file is updated with CoBuilder enrichment block per feature after pipeline creation
- [ ] If no baseline exists, auto-init runs with clear logging before generation
- [ ] Generated pipeline validates cleanly via `cobuilder validate`

## 6. Epic 3: Context Injection for Solution Design and Task Master

**Goal**: Both the solution-design-architect agent and Task Master receive structured RepoMap context as input, producing more accurate technical specs and task decompositions.

### Scope

- `cobuilder repomap context --format sd-injection` outputs YAML context optimised for SD authoring
- Context includes: module inventory with delta status, dependency subgraph, protected file list, key interfaces
- Relevant module filtering by PRD/epic keywords (no LLM in this step — deterministic)
- Update cobuilder-guardian Phase 0 to inject RepoMap context when delegating SD creation
- Update `cobuilder pipeline create` to append RepoMap context to TaskMaster input
- YAML format with markdown values (block scalars for narrative text)

### Acceptance Criteria

- [ ] `cobuilder repomap context --name repo --prd PRD-ID --format sd-injection` produces YAML
- [ ] Context includes: repository name, total nodes/files, relevant modules with delta + interfaces, dependency graph, protected files
- [ ] Module filtering is deterministic (no LLM, keyword-based matching against PRD)
- [ ] cobuilder-guardian skill (SKILL.md) documents RepoMap context injection in Phase 0
- [ ] TaskMaster tasks include file paths and delta classification from RepoMap context
- [ ] Output is reproducible: same input → same output

## 7. Epic 4: Live Baseline Updates and Completion Promise Enforcement

**Goal**: RepoMap baselines automatically refresh as nodes validate, worktrees inherit baselines via git, and completion promises programmatically enforce baseline freshness.

### Scope

- Post-validation hook in `transition.py`: fires `cobuilder repomap refresh --scope <files>` when node → `validated`
- Scoped refresh: only re-scan files in the validated node's file_path/folder_path (seconds, not minutes)
- Worktree baselines: `.repomap/` is committed, so worktrees get baselines from git automatically
- Orchestrator cleanup: `spawn_orchestrator.py` triggers baseline sync on orchestrator completion
- Completion promise AC: "RepoMap baseline updated post-implementation" added programmatically
- cs-verify integration: event-driven check (baseline refreshed after last validated node, not time-based)
- cobuilder-guardian skill update: document `cobuilder` commands for tmux orchestrator boot sequence

### Acceptance Criteria

- [ ] `transition.py` fires baseline refresh when codergen node transitions to `validated`
- [ ] Scoped refresh completes in <10 seconds for typical node file scope
- [ ] Worktrees created via `claude --worktree` contain `.repomap/` with current baseline
- [ ] `cs-verify --check` blocks if baseline not refreshed since last node validation
- [ ] cobuilder-guardian SKILL.md includes CoBuilder tmux commands for orchestrator boot
- [ ] `spawn_orchestrator.py` runs `cobuilder repomap refresh` during cleanup

## 8. Technical Approach

### Package Structure

```
claude-harness-setup/
├── cobuilder/                     # Top-level first-class package
│   ├── __init__.py
│   ├── __main__.py                # python3 -m cobuilder
│   ├── cli.py                     # Main CLI entry point
│   ├── bridge.py                  # RepoMap ↔ Pipeline adapter
│   ├── repomap/                   # From src/zerorepo/ (14 modules)
│   │   ├── models/
│   │   ├── graph_construction/
│   │   ├── rpg_enrichment/
│   │   ├── serena/
│   │   └── llm/
│   ├── pipeline/                  # From .claude/scripts/attractor/
│   │   ├── generate.py
│   │   ├── transition.py
│   │   ├── dashboard.py
│   │   └── signal_protocol.py
│   └── orchestration/
│       ├── spawn_orchestrator.py
│       └── pipeline_runner.py
├── .repomap/                      # Central baseline storage (COMMITTED)
│   ├── config.yaml
│   ├── manifests/
│   └── baselines/
├── .claude/                       # Configuration only (lighter)
└── docs/prds/                     # This PRD and SDs
```

### Process Flow

```
1. PRD                         — Business requirements (human + LLM)
2. cobuilder repomap init      — Codebase baseline scan
3. SD v1                       — Technical spec (receives RepoMap YAML context)
4. cobuilder pipeline create   — Internally:
   a. TaskMaster parse (with RepoMap context appended)
   b. Beads sync
   c. DOT generation (LLM-enriched nodes)
   d. SD v2 enrichment (write back node IDs, file scope, acceptance criteria)
5. Orchestrator dispatch       — Each node carries SD section reference
6. Validation                  — Post-validation baseline refresh
```

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Output format | YAML (with markdown values) | LLMs parse YAML more reliably than JSON; markdown values for narrative |
| Backward compatibility | None — clean switch | Renaming + restructuring anyway; no installed base |
| Missing baseline | Auto-init then generate | Reduces friction; logs clearly |
| TaskMaster integration | Python subprocess | Works in tmux without MCP; simpler to test |
| Cross-repo unified graph | Dropped (YAGNI) | SDs are per-epic/per-repo; call context twice if needed |
| Baseline storage | Committed to git | Every worktree gets baseline automatically |
| Baseline refresh trigger | Event-driven (post-validation) | Not time-based; tied to actual state changes |
| LLM in pipeline generation | Pipeline of enrichers | Focused prompts with structured output per step |

## 9. Out of Scope

- Cross-repo unified graph aggregation (dropped per design review)
- Serena MCP integration for baseline refresh (file-based walking for now)
- Runtime code generation (RepoMap maps structure, doesn't generate code)
- Changes to the 3-level agent hierarchy (System 3 → Orchestrator → Worker unchanged)

## 10. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Auto-init adds 2.5 min to first pipeline create | Medium | Clear logging; one-time cost per repo |
| LLM enrichment adds cost/latency to generation | Medium | Pipeline of focused enrichers; cache results |
| Large rename breaks existing worktrees/sessions | High | Do in one atomic commit; update all import paths |
| Delta accuracy (1/12 module match historically) | Medium | LLM enrichers compensate; delta is context, not authority |

---

**Version**: 2.0.0
**Author**: System 3 Meta-Orchestrator + User
**Date**: 2026-02-27
**Supersedes**: SD-ZEROREPO-DOT-INTEGRATION-001.md (v1 draft, reclassified as PRD)

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
