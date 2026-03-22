---
title: "Solution Design: ZeroRepo-DOT Deep Integration"
status: draft
type: architecture
last_verified: 2026-02-27
grade: draft
prd_id: SD-ZEROREPO-DOT-INTEGRATION-001
---

# Solution Design: ZeroRepo-DOT Deep Integration

## 1. Business Context

### Problem Statement

Today, ZeroRepo and the Attractor DOT pipeline coexist but operate largely in parallel:

- **ZeroRepo** produces a codebase graph (RPG) with delta classification (EXISTING/MODIFIED/NEW) and exports it to DOT via `AttractorExporter`
- **The DOT pipeline** (`generate.py`) builds execution graphs from **beads** (issue tracker), ignoring codebase structure entirely
- **Solution Designs** are written by `solution-design-architect` without access to the codebase graph
- **Baselines become stale** during implementation — no mechanism updates them as orchestrators complete work
- **Cross-repo context is fragmented** — each repo has its own `.zerorepo/` with no aggregation

The result: orchestrators and workers operate with incomplete codebase context, leading to scope mismatches, missing dependencies, and architectural drift.

### Vision

**An always-up-to-date codebase snapshot, centrally accessible from claude-harness-setup, that informs every stage of the pipeline — from PRD authoring through solution design, DOT graph generation, orchestrator dispatch, and post-implementation validation.**

### Success Criteria

| ID | Criterion | Measurable Outcome |
|----|-----------|-------------------|
| SC-1 | Solution Designs receive codebase context | SD documents include RPG graph summary as input context |
| SC-2 | DOT pipeline generation uses RPG graph | `generate.py` can use RPG nodes as primary source (not just beads) |
| SC-3 | Baselines update as nodes complete | When a codergen node transitions to `validated`, baseline refreshes |
| SC-4 | Cross-repo baselines aggregate | A single command produces a unified graph across multiple repos |
| SC-5 | Central storage in claude-harness-setup | All baselines accessible from config repo via `--target-dir` |

---

## 2. Technical Architecture

### 2.1 Current Architecture (As-Is)

```
                    ┌─────────────────────────────────────────┐
                    │         claude-harness-setup             │
                    │                                         │
                    │  .claude/scripts/attractor/              │
                    │  ├── cli.py (DOT pipeline CLI)           │
                    │  ├── generate.py (beads → DOT)           │
                    │  └── transition.py (state machine)       │
                    │                                         │
                    │  .claude/attractor/pipelines/            │
                    │  └── <initiative>.dot                    │
                    └─────────────────────────────────────────┘
                                    │
                                    │ (orchestrators spawned via tmux)
                                    │
                    ┌───────────────┴───────────────┐
                    │       impl-repo (worktree)     │
                    │                                │
                    │  src/zerorepo/                  │
                    │  ├── graph_construction/        │
                    │  │   └── attractor_exporter.py  │  ← RPG → DOT (one-shot)
                    │  ├── serena/                    │
                    │  │   └── baseline_manager.py    │
                    │  └── cli/                       │
                    │                                │
                    │  .zerorepo/                     │
                    │  └── baseline.json              │  ← Per-repo, stale during impl
                    └────────────────────────────────┘
```

**Key problems**:
1. `generate.py` reads beads, NOT RPG nodes → no codebase awareness in pipeline
2. `attractor_exporter.py` creates DOT but isn't connected to `generate.py`
3. Baselines are per-repo, updated manually, stale during implementation
4. Solution Designs don't receive RPG context
5. No central location for cross-repo baselines

### 2.2 Target Architecture (To-Be)

```
                    ┌─────────────────────────────────────────────────┐
                    │              claude-harness-setup                │
                    │                                                 │
                    │  .zerorepo-central/                   [NEW]     │
                    │  ├── manifests/                                  │
                    │  │   ├── <repo-a>.manifest.json                  │
                    │  │   ├── <repo-b>.manifest.json                  │
                    │  │   └── unified.manifest.json    [aggregated]   │
                    │  └── baselines/                                  │
                    │      ├── <repo-a>/baseline.json                  │
                    │      └── <repo-b>/baseline.json                  │
                    │                                                 │
                    │  .claude/scripts/attractor/                      │
                    │  ├── cli.py (extended with zerorepo subcommands) │
                    │  ├── generate.py (hybrid: beads + RPG)   [MOD]  │
                    │  ├── transition.py (baseline refresh hook)[MOD]  │
                    │  └── zerorepo_bridge.py                  [NEW]   │
                    │                                                 │
                    │  .claude/attractor/pipelines/                    │
                    │  └── <initiative>.dot (RPG-enriched nodes)       │
                    └─────────────────────────────────────────────────┘
                                    │
                          ┌─────────┴──────────┐
                          │                    │
                    ┌─────┴─────┐      ┌──────┴──────┐
                    │ repo-a    │      │ repo-b      │
                    │ (worktree)│      │ (worktree)  │
                    │           │      │             │
                    │ .zerorepo/│      │ .zerorepo/  │
                    │ └baseline │      │ └baseline   │
                    └───────────┘      └─────────────┘
```

### 2.3 New Components

| Component | Type | Location | Purpose |
|-----------|------|----------|---------|
| `zerorepo_bridge.py` | New module | `.claude/scripts/attractor/` | Bridge between ZeroRepo's Python API and the Attractor CLI |
| `.zerorepo-central/` | New directory | Config repo root | Central storage for cross-repo baselines and manifests |
| `unified.manifest.json` | New file | `.zerorepo-central/manifests/` | Aggregated view of all repo baselines |
| `generate.py` (v2) | Modified | `.claude/scripts/attractor/` | Hybrid pipeline: beads + RPG as dual sources |
| `transition.py` (v2) | Modified | `.claude/scripts/attractor/` | Post-validation hook to refresh baseline |
| `cli.py zerorepo` | New subcommand | `.claude/scripts/attractor/` | `zerorepo init`, `zerorepo sync`, `zerorepo context` |

---

## 3. Functional Decomposition

### Epic 1: Central Baseline Storage (Foundation)

**Goal**: Establish `.zerorepo-central/` as the single source of truth for codebase snapshots, steered from claude-harness-setup.

#### F1.1: Central Directory Structure

Create `.zerorepo-central/` with manifest + baseline storage:

```
.zerorepo-central/
├── config.json                     # Registry of tracked repos
│   {
│     "repos": [
│       {
│         "name": "my-project",
│         "path": "$CLAUDE_PROJECT_DIR",
│         "last_synced": "2026-02-27T10:00:00Z",
│         "baseline_hash": "sha256:abc..."
│       }
│     ]
│   }
├── manifests/
│   ├── my-project.manifest.json     # Summary: node count, top-level modules, delta
│   └── unified.manifest.json       # Merged cross-repo graph summary
└── baselines/
    └── my-project/
        ├── baseline.json           # Full baseline (copied from repo)
        └── baseline.prev.json      # Previous version (for diff)
```

#### F1.2: `zerorepo-bridge.py` — The Adapter

A new Python module that wraps ZeroRepo's Python API for use by the Attractor CLI:

```python
class ZeroRepoBridge:
    """Adapter between ZeroRepo's RPGGraph and Attractor's DOT pipeline."""

    def __init__(self, central_dir: str = ".zerorepo-central"):
        self.central_dir = Path(central_dir)

    def init_repo(self, target_dir: str, repo_name: str = None) -> dict:
        """Run zerorepo init on target_dir, sync result to central storage."""

    def sync_baseline(self, repo_name: str) -> dict:
        """Copy latest baseline from repo to central, update manifest."""

    def get_rpg_context(self, repo_name: str, prd_id: str = None) -> dict:
        """Return RPG graph summary suitable for SD/generate injection.

        Returns:
            {
                "repo": "my-project",
                "total_nodes": 3037,
                "modules": [{"name": "auth", "files": 12, "delta": "existing"}, ...],
                "top_level_structure": "...",
                "relevant_nodes": [...]  # filtered by PRD if provided
            }
        """

    def get_unified_context(self) -> dict:
        """Aggregate all repo baselines into a single context object."""

    def refresh_baseline(self, target_dir: str, scope: list[str] = None) -> dict:
        """Re-run zerorepo init on target_dir, scoped to specific paths.

        Used after node validation to incrementally update the baseline.
        """

    def diff_baselines(self, repo_name: str) -> dict:
        """Compare current vs previous baseline, return regression report."""
```

#### F1.3: CLI Subcommands

Extend `cli.py` with a `zerorepo` subcommand group:

```bash
# Initialize and register a repo in central storage
python3 cli.py zerorepo init --target-dir /path/to/repo --name my-project

# Sync latest baseline from repo to central
python3 cli.py zerorepo sync --name my-project

# Sync ALL registered repos
python3 cli.py zerorepo sync --all

# Get RPG context for SD injection
python3 cli.py zerorepo context --name my-project --prd PRD-AUTH-001 --format markdown

# Get unified cross-repo context
python3 cli.py zerorepo context --unified --format markdown

# Refresh baseline after implementation (scoped)
python3 cli.py zerorepo refresh --name my-project --scope "src/auth/,src/api/"

# Show status of all tracked repos
python3 cli.py zerorepo status
```

**Acceptance Criteria**:
- [ ] `.zerorepo-central/config.json` created with repo registry
- [ ] `init` command runs `zerorepo init` on target and copies baseline to central
- [ ] `sync` command copies latest baseline without re-running init
- [ ] `context` command returns markdown-formatted RPG summary
- [ ] `status` shows all repos with last sync time and node counts

---

### Epic 2: RPG-Aware Pipeline Generation

**Goal**: `generate.py` uses RPG nodes (from ZeroRepo) as the primary source for pipeline construction, with beads as a secondary enrichment layer.

#### F2.1: Hybrid Generation Mode

Currently `generate.py` reads beads exclusively. Add an `--rpg-source` flag:

```bash
# Current: beads-only (unchanged)
python3 cli.py generate --prd PRD-AUTH-001 --output pipeline.dot

# New: RPG-primary with beads enrichment
python3 cli.py generate --prd PRD-AUTH-001 --rpg-source my-project --output pipeline.dot

# New: RPG-only (no beads required)
python3 cli.py generate --prd PRD-AUTH-001 --rpg-source my-project --no-beads --output pipeline.dot
```

**How hybrid mode works**:

```python
def generate_hybrid(prd_id: str, rpg_source: str, beads_json: str = None):
    # 1. Load RPG graph from central baseline
    bridge = ZeroRepoBridge()
    rpg_context = bridge.get_rpg_context(rpg_source, prd_id)

    # 2. Get actionable nodes (MODIFIED + NEW only)
    actionable = [n for n in rpg_context["nodes"] if n["delta"] in ("modified", "new")]

    # 3. If beads available, cross-reference for enrichment
    if beads_json:
        beads = load_beads(beads_json)
        # Match beads to RPG nodes by title/file_path similarity
        for node in actionable:
            matched_bead = find_matching_bead(node, beads)
            if matched_bead:
                node["bead_id"] = matched_bead["id"]
                node["priority"] = matched_bead.get("priority", 2)

    # 4. Generate DOT with RPG-enriched attributes
    #    - file_path from RPG (precise)
    #    - worker_type from RPG file paths (more accurate than keyword matching)
    #    - acceptance from beads (if matched) or RPG docstring
    #    - delta_status as DOT attribute (enables scoped worker instructions)
    return render_dot(actionable, prd_id)
```

**Key improvement**: Worker type inference uses actual file paths from the RPG graph (e.g., `src/auth/routes.py` → `backend-solutions-engineer`) instead of keyword matching on bead titles.

#### F2.2: Enhanced Node Attributes

RPG-sourced nodes carry richer attributes than bead-sourced nodes:

| Attribute | Beads Source | RPG Source | Benefit |
|-----------|-------------|------------|---------|
| `file_path` | None or manual | Precise from graph | Workers know exactly which files to modify |
| `folder_path` | None | Precise from graph | Scoped `--target-dir` for workers |
| `worker_type` | Keyword heuristic | File path pattern | More accurate agent selection |
| `delta_status` | None | `EXISTING/MODIFIED/NEW` | Workers know if creating or modifying |
| `interfaces` | None | Function signatures from InterfaceDesignEncoder | Workers get the contract upfront |
| `dependencies` | Parent-child from beads | DATA_FLOW/ORDERING edges | True implementation ordering |
| `change_summary` | None | LLM-generated for MODIFIED | Workers know what specifically to change |
| `rpg_node_id` | None | UUID | Traceability back to RPG graph |

#### F2.3: Backward Compatibility

The existing beads-only mode MUST continue to work unchanged. The `--rpg-source` flag is opt-in. When omitted, behavior is identical to current `generate.py`.

**Acceptance Criteria**:
- [ ] `--rpg-source <repo>` flag triggers hybrid mode
- [ ] `--no-beads` flag allows RPG-only generation (useful for repos without beads)
- [ ] All existing DOT files remain valid (no breaking changes to format)
- [ ] Generated nodes include `delta_status`, `interfaces`, `change_summary` when RPG source used
- [ ] Worker type inference accuracy improves (measure: compare against manual assignments)

---

### Epic 3: SD Context Injection

**Goal**: Solution Design documents receive codebase graph context as a structured input, enabling more accurate technical specifications.

#### F3.1: RPG Context Format for SDs

When System 3 delegates SD creation to `solution-design-architect`, include RPG context:

```markdown
## Codebase Context (from ZeroRepo)

### Repository: my-project
**Total modules**: 47 | **Total files**: 312 | **Total functions**: 1,847

### Modules Relevant to This Epic

| Module | Status | Files | Key Interfaces |
|--------|--------|-------|----------------|
| `src/auth/` | EXISTING | 8 | `authenticate(token: str) -> User`, `create_jwt(user_id: UUID) -> str` |
| `src/api/routes/` | MODIFIED | 12 | `POST /auth/login`, `POST /auth/refresh` |
| `src/email/` | NEW | 0 | (to be created) |

### Dependency Graph (Relevant Subgraph)

```
auth/ ──depends──► database/models.py
auth/ ──depends──► config/settings.py
api/routes/ ──invokes──► auth/authenticate
email/ ──will-depend──► config/settings.py (NEW)
```

### File Scope Constraints

These files are EXISTING and should NOT be modified unless the PRD explicitly requires changes:
- `src/database/models.py` (core data models)
- `src/config/settings.py` (configuration)
- `src/auth/jwt.py` (JWT utilities)
```

#### F3.2: Automated Context Generation

The `zerorepo context` CLI command outputs this format:

```bash
# Generate SD-ready context
python3 cli.py zerorepo context \
    --name my-project \
    --prd PRD-AUTH-001 \
    --format sd-injection \
    --output /tmp/rpg-context-auth.md

# The SD architect receives this as input alongside the PRD
```

**Acceptance Criteria**:
- [ ] `--format sd-injection` produces markdown formatted for SD consumption
- [ ] Relevant module filtering uses PRD keywords to select only related RPG nodes
- [ ] Dependency subgraph extraction shows connections between relevant nodes
- [ ] File scope constraints identify EXISTING files that should be protected
- [ ] Output is deterministic (same input → same output, no LLM in this step)

---

### Epic 4: Live Baseline Updates

**Goal**: Baselines automatically refresh as orchestrators complete and validate work, keeping the codebase snapshot current throughout an initiative.

#### F4.1: Post-Validation Baseline Refresh

Extend `transition.py` with a hook that fires when a codergen node transitions to `validated`:

```python
# In transition.py — after successful validated transition
def _post_transition_hook(node_id: str, new_status: str, dot_path: str):
    if new_status == "validated":
        # Read the node's file_path/folder_path scope
        scope = get_node_scope(dot_path, node_id)

        # Trigger scoped baseline refresh
        bridge = ZeroRepoBridge()
        bridge.refresh_baseline(
            target_dir=get_target_dir(dot_path),
            scope=scope  # Only re-scan the files this node touched
        )

        # Sync updated baseline to central
        bridge.sync_baseline(repo_name=get_repo_name(dot_path))
```

**Why scoped refresh**: Full `zerorepo init` takes ~2.5 minutes. Scoped refresh on just the changed files takes seconds.

#### F4.2: Worktree-Aware Baselines

Worktrees share `.zerorepo/` with the main checkout (because `.zerorepo/` is in `.gitignore`). This means a worktree's baseline reflects the main branch, not its own changes.

**Solution**: Store worktree-specific baselines in central storage:

```
.zerorepo-central/baselines/
├── my-project/
│   ├── baseline.json              # Main branch baseline
│   ├── baseline.prev.json
│   └── worktrees/
│       ├── epic1.baseline.json    # Worktree-specific overlay
│       └── epic2.baseline.json
```

When a worktree orchestrator requests context, the bridge merges the main baseline with the worktree overlay:

```python
def get_rpg_context(self, repo_name: str, worktree: str = None):
    base = self.load_baseline(repo_name)
    if worktree:
        overlay = self.load_worktree_baseline(repo_name, worktree)
        base = self.merge_baselines(base, overlay)
    return base
```

#### F4.3: Refresh on Orchestrator Completion

When `spawn_orchestrator.py` detects orchestrator completion (tmux session ends), automatically refresh:

```bash
# Added to orchestrator cleanup in spawn_orchestrator.py
python3 cli.py zerorepo refresh \
    --name my-project \
    --worktree epic1 \
    --scope "$(get_modified_files_from_git)"
```

**Acceptance Criteria**:
- [ ] `transition.py` fires baseline refresh on `validated` transitions
- [ ] Scoped refresh completes in <10 seconds for typical node file scope
- [ ] Worktree baselines stored separately in central
- [ ] Merged context (main + worktree overlay) available via bridge
- [ ] Orchestrator cleanup triggers baseline sync

---

### Epic 5: Cross-Repo Unified Graph

**Goal**: A single command aggregates baselines from multiple repos into a unified context, enabling cross-codebase solution design.

#### F5.1: Unified Manifest

```json
// .zerorepo-central/manifests/unified.manifest.json
{
  "generated_at": "2026-02-27T10:00:00Z",
  "repos": [
    {
      "name": "my-project",
      "path": "/path/to/my-project",
      "total_nodes": 3037,
      "total_files": 312,
      "top_modules": ["auth", "api", "database", "voice_agent", "eddy_validate"]
    },
    {
      "name": "claude-harness-setup",
      "path": "/path/to/claude-harness-setup",
      "total_nodes": 450,
      "total_files": 87,
      "top_modules": ["scripts", "skills", "hooks", "attractor"]
    }
  ],
  "cross_repo_edges": [
    {
      "from": {"repo": "my-project", "module": "voice_agent"},
      "to": {"repo": "claude-harness-setup", "module": "skills/orchestrator-multiagent"},
      "type": "configuration_dependency"
    }
  ]
}
```

#### F5.2: Cross-Repo Context Command

```bash
# Generate unified context across all tracked repos
python3 cli.py zerorepo context --unified --format sd-injection --output /tmp/unified-context.md

# Filter to specific repos
python3 cli.py zerorepo context --unified --repos my-project,harness --format sd-injection
```

**Acceptance Criteria**:
- [ ] `--unified` flag aggregates all registered repo baselines
- [ ] Cross-repo edges detected (configuration dependencies, import references)
- [ ] Unified manifest updated on every `sync --all`
- [ ] Context output includes cross-repo dependency information

---

## 4. Integration Points

### 4.1 With cobuilder-guardian Skill (Phase 0)

Guardian Phase 0 currently writes PRDs and creates DOT pipelines. With this integration:

1. **Before PRD writing**: `cli.py zerorepo context --name <repo> --format markdown` → provides codebase overview
2. **Before SD delegation**: `cli.py zerorepo context --name <repo> --prd <id> --format sd-injection` → provides per-epic context
3. **Pipeline generation**: `cli.py generate --prd <id> --rpg-source <repo>` → RPG-enriched nodes
4. **Phase 4.5 regression**: `cli.py zerorepo refresh --name <repo>` + `zerorepo diff` → regression detection from central

### 4.2 With Orchestrator Dispatch

When spawning orchestrators, inject RPG context into the wisdom file:

```bash
# In spawn_orchestrator.py or guardian Phase 2
RPG_CONTEXT=$(python3 cli.py zerorepo context \
    --name my-project \
    --prd PRD-AUTH-001 \
    --node impl_auth \
    --format worker-brief)

cat >> /tmp/wisdom-epic1.md << EOF

## Codebase Context (ZeroRepo)
$RPG_CONTEXT

## File Scope (from RPG)
- MODIFY: src/auth/routes.py (add refresh token endpoint)
- MODIFY: src/auth/jwt.py (add rotation logic)
- CREATE: src/auth/models.py (RefreshToken model)
- REFERENCE ONLY: src/database/base.py, src/config/settings.py
EOF
```

### 4.3 With Completion Promise

ZeroRepo baseline freshness can be an acceptance criterion:

```bash
cs-promise --create "Implement auth feature" \
    --ac "All unit tests pass" \
    --ac "API endpoints verified" \
    --ac "ZeroRepo baseline updated (post-impl snapshot matches code)"
```

### 4.4 With Hindsight Memory

Store RPG context snapshots to Hindsight for cross-session awareness:

```python
mcp__hindsight__retain(
    content=f"ZeroRepo baseline for my-project: {node_count} nodes, {file_count} files. "
            f"Delta from PRD-AUTH-001: {new_count} NEW, {mod_count} MODIFIED, {exist_count} EXISTING",
    context="zerorepo-baselines",
    bank_id=PROJECT_BANK
)
```

---

## 5. Implementation Plan

### Phase 1: Foundation (Epic 1) — Central Storage + Bridge

**Dependencies**: None (foundational)
**Estimated effort**: 3-4 orchestrator sessions

1. Create `.zerorepo-central/` directory structure
2. Implement `zerorepo_bridge.py` with `init_repo`, `sync_baseline`, `get_rpg_context`
3. Add `zerorepo` subcommand group to `cli.py`
4. Implement `init`, `sync`, `status` subcommands
5. Test with my-org/my-project as first tracked repo

### Phase 2: Pipeline Integration (Epic 2) — RPG-Aware Generation

**Dependencies**: Epic 1 (bridge must exist)
**Estimated effort**: 2-3 orchestrator sessions

1. Extend `generate.py` with `--rpg-source` flag
2. Implement hybrid generation (beads + RPG)
3. Add enhanced node attributes (delta_status, interfaces, change_summary)
4. Test backward compatibility (beads-only mode unchanged)
5. Test RPG-only mode (--no-beads)

### Phase 3: SD Injection (Epic 3) — Context for Design

**Dependencies**: Epic 1 (context command must exist)
**Estimated effort**: 1-2 orchestrator sessions

1. Implement `--format sd-injection` output mode
2. Add relevant module filtering by PRD keywords
3. Add dependency subgraph extraction
4. Update cobuilder-guardian Phase 0 to include RPG context in SD delegation
5. Test with real PRD + SD cycle

### Phase 4: Live Updates (Epic 4) — Keep Baselines Fresh

**Dependencies**: Epic 1 + Epic 2 (bridge and pipeline must exist)
**Estimated effort**: 2-3 orchestrator sessions

1. Add post-validation hook to `transition.py`
2. Implement scoped refresh in bridge
3. Add worktree-aware baseline storage
4. Integrate with `spawn_orchestrator.py` cleanup
5. Test baseline freshness across implementation cycle

### Phase 5: Cross-Repo (Epic 5) — Unified Graph

**Dependencies**: Epic 1 + Epic 4 (multiple repos must be trackable)
**Estimated effort**: 1-2 orchestrator sessions

1. Implement unified manifest generation
2. Add cross-repo edge detection
3. Implement `--unified` context command
4. Test with my-project + claude-harness-setup as two repos

---

## 6. File Scope

### New Files

| File | Epic | Purpose |
|------|------|---------|
| `.zerorepo-central/config.json` | 1 | Repo registry |
| `.claude/scripts/attractor/zerorepo_bridge.py` | 1 | ZeroRepo ↔ Attractor bridge |
| `.zerorepo-central/manifests/*.json` | 1, 5 | Baseline summaries |
| `.zerorepo-central/baselines/` | 1 | Central baseline storage |

### Modified Files

| File | Epic | Changes |
|------|------|---------|
| `.claude/scripts/attractor/cli.py` | 1 | Add `zerorepo` subcommand group |
| `.claude/scripts/attractor/generate.py` | 2 | Add `--rpg-source`, `--no-beads` flags; hybrid generation |
| `.claude/scripts/attractor/transition.py` | 4 | Add post-validation baseline refresh hook |
| `.claude/scripts/attractor/spawn_orchestrator.py` | 4 | Add cleanup baseline sync |
| `.claude/skills/cobuilder-guardian/SKILL.md` | 3 | Update Phase 0 to inject RPG context |
| `.claude/skills/orchestrator-multiagent/ZEROREPO.md` | 2 | Update to reference hybrid generation |

### Unchanged (Reference Only)

| File | Reason |
|------|--------|
| `src/zerorepo/` | All 14 modules — used via bridge, not modified |
| `.claude/scripts/attractor/dashboard.py` | Display only, no changes needed |
| `.claude/scripts/attractor/signal_protocol.py` | Inter-layer signals unchanged |

---

## 7. Risks and Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| ZeroRepo init is slow (~2.5min) | Medium | Scoped refresh for validated nodes; full init only on first run |
| Delta accuracy still low (1/12 modules) | High | This SD does NOT depend on delta accuracy — it uses the graph structure, not classification correctness |
| RPG graph may be out of date | Medium | Live updates (Epic 4) address this; staleness indicator in manifest |
| Cross-repo edge detection is heuristic | Medium | Start with configuration dependencies (import patterns), extend later |
| Backward compatibility break in generate.py | High | `--rpg-source` is opt-in; omitting it preserves exact current behavior |
| Central storage adds complexity | Low | Simple JSON files, no database; `git add` for versioning |

---

## 8. Open Questions

1. **Should `.zerorepo-central/` be gitignored or committed?** Baselines can be large (3,037 nodes). Manifests are small. Consider: commit manifests, gitignore baselines.

2. **Should scoped refresh use Serena MCP or file-based walking?** Serena gives LSP-quality analysis but requires a running language server. File-based walking is simpler and always available. Recommendation: start with file-based, add Serena as enhancement.

3. **How should cross-repo edges be detected?** Options: (a) import path scanning, (b) configuration file references, (c) manual annotation. Recommendation: start with (b) configuration references, extend to (a) import scanning.

4. **Should RPG context be injected into Task Master parsing?** Currently Task Master doesn't receive codebase context. Adding RPG context could improve task decomposition quality. Recommendation: defer to after Epic 3 validates the SD injection pattern.

---

**Version**: 0.1.0 (Draft)
**Author**: System 3 Meta-Orchestrator
**Date**: 2026-02-27
**Dependencies**: ZeroRepo (src/zerorepo/), Attractor CLI (.claude/scripts/attractor/), Beads

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
