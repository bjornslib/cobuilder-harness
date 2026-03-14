# PRD-S3-DOT-LIFECYCLE-001: ZeroRepo-Powered Pipeline Lifecycle

## Overview

Use ZeroRepo's codebase analysis to automatically generate Attractor .dot pipeline graphs that serve as the single source of truth across three lifecycle stages: Definition, Implementation, and Validation. This closes the gap between "what needs to change" (ZeroRepo delta) and "how to orchestrate the change" (Attractor .dot graph).

```
PRD Document
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  STAGE 1: DEFINITION (ZeroRepo → .dot)                      │
│  ZeroRepo analyzes PRD + codebase baseline                  │
│  Produces delta report (EXISTING / MODIFIED / NEW)          │
│  Transforms delta into Attractor-compatible .dot graph      │
│  Graph = guiding light for the entire initiative            │
├─────────────────────────────────────────────────────────────┤
│  STAGE 2: IMPLEMENTATION (System 3 navigates .dot)          │
│  Taskmaster parses PRD → enriches .dot nodes with task IDs  │
│  System 3 reads attractor status → dispatches orchestrators │
│  Orchestrators complete nodes → transition to impl_complete │
├─────────────────────────────────────────────────────────────┤
│  STAGE 3: VALIDATION (Guardian scores against .dot)         │
│  s3-validator runs dual-pass (technical + business)         │
│  Guardian scores against acceptance criteria per node       │
│  Evidence gate links proof to each .dot node                │
│  All nodes validated → finalize → cs-verify                 │
└─────────────────────────────────────────────────────────────┘
```

**PRD ID**: PRD-S3-DOT-LIFECYCLE-001
**Status**: Active
**Priority**: P1
**Owner**: System 3 Meta-Orchestrator / S3 Guardian
**Target Repository**: claude-harness-setup (deployed to all targets)
**Depends On**: PRD-S3-ATTRACTOR-001 (Attractor CLI + DOT schema must exist)

## Background

### What Exists Today

1. **ZeroRepo** (`src/zerorepo/`): Generates codebase graphs (RPG) from source code. Produces delta reports classifying components as EXISTING, MODIFIED, or NEW against a baseline. Output: `05-delta-report.md`.

2. **Attractor CLI** (`.claude/scripts/attractor/cli.py`): Parse, validate, status, transition, and checkpoint DOT pipeline graphs. Supports node shapes (Mdiamond, box, hexagon, diamond, Msquare).

3. **S3 Guardian** (`.claude/skills/s3-guardian/`): Creates blind acceptance tests from PRDs, spawns meta-orchestrators, independently validates work against gradient confidence rubric.

### The Gap

ZeroRepo and Attractor are **disconnected**. Today:
- ZeroRepo produces a delta report → human reads it → manually creates beads/tasks
- Attractor .dot files are hand-crafted → System 3 navigates them manually
- No automated path from "codebase analysis" to "executable pipeline graph"

### The Vision

One command produces a .dot graph from a PRD + codebase. That graph becomes the single artifact that:
- **Defines** what work needs to happen (Stage 1)
- **Orchestrates** the implementation (Stage 2)
- **Validates** the results (Stage 3)

---

## Epic 1: ZeroRepo .dot Export — Delta to Pipeline Graph

### Problem
ZeroRepo's delta report is markdown text. It classifies components but doesn't produce an executable artifact that System 3 can navigate. The export module (`export.py`) generates basic DOT but not Attractor-compatible pipeline graphs.

### Requirements
- R1.1: New export mode `--format=attractor-pipeline` that produces lifecycle-compatible DOT
- R1.2: Delta classification maps to DOT node types:

| Delta Classification | DOT Node | Shape | Handler | Action |
|---------------------|----------|-------|---------|--------|
| EXISTING | (skipped) | — | — | Not included in pipeline |
| MODIFIED | Implementation node | box | codergen | File paths + change scope |
| NEW | Implementation node | box | codergen | Suggested module structure |
| (auto) | Validation gate | hexagon | wait.human | Paired with each impl node |
| (auto) | Decision node | diamond | conditional | Pass/fail routing |

- R1.3: Auto-generate AT (Acceptance Test) pairing: every codergen node gets a hexagon + diamond triplet
- R1.4: Inject node attributes from RPG enrichment (file_path, folder_path, interfaces, dependencies)
- R1.5: Include start (Mdiamond) and finalize (Msquare) bookend nodes
- R1.6: Edge generation follows dependency order from RPG graph edges
- R1.7: Worker type inference from file paths:

| Path Pattern | Worker Type |
|-------------|-------------|
| `**/components/**`, `**/pages/**`, `**/*.tsx` | frontend-dev-expert |
| `**/api/**`, `**/models/**`, `**/*.py` (non-test) | backend-solutions-engineer |
| `**/tests/**`, `**/*.test.*`, `**/*.spec.*` | tdd-test-engineer |
| Mixed or unclear | general-purpose |

### Acceptance Criteria
- AC-1.1: `zerorepo-run-pipeline.py --format=attractor-pipeline` produces a valid .dot file alongside the delta report
- AC-1.2: Generated .dot passes `attractor validate` with zero errors
- AC-1.3: Every MODIFIED/NEW component has a codergen→hexagon→diamond triplet
- AC-1.4: Node attributes include `worker_type`, `acceptance`, `bead_id` (if annotated), and `prd_ref`
- AC-1.5: Start and finalize nodes are present with correct shapes
- AC-1.6: Dependency edges match RPG graph structure (no circular dependencies)

### Key Files
- MODIFY: `src/zerorepo/graph_construction/export.py`
- CREATE: `src/zerorepo/graph_construction/attractor_exporter.py` (new module)
- MODIFY: `.claude/skills/orchestrator-multiagent/scripts/zerorepo-run-pipeline.py`
- CREATE: `tests/unit/test_attractor_exporter.py`

---

## Epic 2: Stage 1 Workflow — Definition Pipeline

### Problem
No automated workflow exists to go from "PRD + codebase" to "ready-to-execute .dot graph." Today this requires manual steps: run ZeroRepo, read the delta report, manually create beads, manually craft a .dot file.

### Requirements
- R2.1: Single command workflow: `zerorepo-pipeline.sh --prd <PRD-FILE> --format=attractor`
- R2.2: Pipeline stages:
  1. `zerorepo init` (if no baseline exists)
  2. `zerorepo generate --spec <PRD-FILE>` (delta analysis)
  3. Export to .dot (Epic 1's `--format=attractor-pipeline`)
  4. `attractor validate` (structural check)
  5. `attractor annotate` (cross-reference with beads DB)
  6. `attractor init-promise` (create completion promise from graph)
- R2.3: Output stored at `.cobuilder/pipelines/<PRD-ID>.dot`
- R2.4: Checkpoint created automatically after definition stage
- R2.5: Summary report showing node count, dependency graph, estimated effort per worker type

### Acceptance Criteria
- AC-2.1: `zerorepo-pipeline.sh --prd .taskmaster/docs/PRD-XXX.md --format=attractor` completes end-to-end
- AC-2.2: Output .dot is stored at correct path and passes `attractor validate`
- AC-2.3: Completion promise created with one AC per hexagon validation gate
- AC-2.4: Checkpoint saved at `.cobuilder/checkpoints/<PRD-ID>-definition.json`
- AC-2.5: Summary report printed to stdout with node counts by type and worker_type distribution

### Key Files
- CREATE: `.claude/skills/orchestrator-multiagent/scripts/zerorepo-pipeline.sh`
- MODIFY: `.claude/skills/orchestrator-multiagent/ZEROREPO.md` (document new workflow)
- MODIFY: `.claude/scripts/attractor/annotate.py`
- MODIFY: `.claude/scripts/attractor/init_promise.py`

---

## Epic 3: Stage 2 Workflow — Implementation Navigation

### Problem
System 3's DOT Navigation section (in the output style) describes the execution loop conceptually but lacks integration with ZeroRepo-generated pipelines. The generated .dot graph needs to be the primary instrument.

### Requirements
- R3.1: System 3 preflight reads `.cobuilder/pipelines/<INITIATIVE>.dot` automatically
- R3.2: `attractor status --filter=pending --deps-met` identifies dispatchable nodes (pending + all upstream validated)
- R3.3: When spawning an orchestrator for a node, inject:
  - Node's `acceptance` criteria as the mission brief
  - Node's `worker_type` as the recommended specialist
  - Node's file paths from RPG enrichment as scope boundaries
  - Node's `prd_ref` for context
- R3.4: Orchestrator completion triggers `attractor transition <node> impl_complete`
- R3.5: After each transition, `attractor checkpoint save` automatically
- R3.6: Parallel dispatch: nodes with no dependency relationship can execute simultaneously

### Acceptance Criteria
- AC-3.1: System 3 output style includes updated DOT Navigation section referencing ZeroRepo-generated pipelines
- AC-3.2: `attractor status --filter=pending --deps-met` correctly identifies only nodes whose upstream dependencies are all validated
- AC-3.3: Orchestrator spawn prompt includes acceptance criteria, worker_type, file paths, and prd_ref from the .dot node
- AC-3.4: Transition to `impl_complete` succeeds and checkpoint is saved
- AC-3.5: Two independent nodes can be dispatched to separate orchestrators simultaneously

### Key Files
- MODIFY: `.claude/output-styles/system3-meta-orchestrator.md` (DOT Navigation section)
- MODIFY: `.claude/skills/system3-orchestrator/SKILL.md` (spawn workflow)
- MODIFY: `.claude/scripts/attractor/status.py` (add `--deps-met` filter)

---

## Epic 4: Stage 3 Workflow — Validation Gate Integration

### Problem
Validation gates (hexagon nodes) in the .dot graph are currently decorative. They need to trigger actual validation via the s3-validator and s3-guardian, with evidence linking back to specific .dot nodes.

### Requirements
- R4.1: When a codergen node reaches `impl_complete`, the paired hexagon node becomes activatable
- R4.2: s3-validator receives the hexagon node's `acceptance` criteria as validation scope
- R4.3: Technical validation runs first (`--mode=technical`), then business (`--mode=business --prd=<prd_ref>`)
- R4.4: Validation evidence stored at `.claude/evidence/<node-id>/`
- R4.5: Decision diamond routes based on validation result:
  - PASS → transition hexagon to `validated`, advance to next stage
  - FAIL → transition codergen back to `active` (retry), send feedback to orchestrator
- R4.6: Guardian's `validation_method` enforcement (from today's changes) applies per node:
  - Nodes with frontend file paths → `browser-required`
  - Nodes with API file paths → `api-required`
  - Nodes with config/schema paths → `code-analysis`
- R4.7: Finalize node (Msquare) only activates when ALL hexagon nodes are `validated`

### Acceptance Criteria
- AC-4.1: `impl_complete` codergen node triggers paired hexagon activation
- AC-4.2: s3-validator receives acceptance criteria from the hexagon node's attributes
- AC-4.3: Dual-pass validation (technical → business) runs sequentially per hexagon
- AC-4.4: Evidence stored at correct path with node-id reference
- AC-4.5: Failed validation transitions codergen back to `active` and sends rejection message
- AC-4.6: `validation_method` is auto-inferred from file paths in the node attributes
- AC-4.7: Finalize node blocks until all hexagons show `validated`

### Key Files
- MODIFY: `.claude/skills/s3-guardian/SKILL.md` (Phase 4 integration)
- MODIFY: `.claude/skills/s3-guardian/references/guardian-workflow.md` (validation cycle)
- MODIFY: `.claude/scripts/attractor/transition.py` (activation logic)
- MODIFY: `.claude/agents/validation-test-agent.md` (node-based scope)

---

## Epic 5: Lifecycle Dashboard and Progress Tracking

### Problem
No single view shows initiative progress across all three stages. System 3 relies on multiple commands (`bd list`, `attractor status`, `cs-promise --check`) without a unified picture.

### Requirements
- R5.1: `attractor dashboard <pipeline.dot>` produces a combined progress view
- R5.2: Dashboard includes:
  - Pipeline stage (Definition / Implementation / Validation / Finalized)
  - Node status distribution (pending / active / impl_complete / validated / failed)
  - Per-node detail table with worker assignment and time in current state
  - Completion promise progress (N/M acceptance criteria met)
  - Estimated completion (based on average node duration)
- R5.3: JSON output mode for programmatic consumption
- R5.4: Integration with s3-heartbeat: heartbeat scans pipeline.dot during its 600s cycle
- R5.5: Progress stored to Hindsight for cross-session awareness

### Acceptance Criteria
- AC-5.1: `attractor dashboard <pipeline.dot>` produces human-readable progress table
- AC-5.2: JSON output matches dashboard content (`--output json`)
- AC-5.3: s3-heartbeat includes pipeline status in its scan findings
- AC-5.4: Progress retained to Hindsight project bank after each status change
- AC-5.5: Dashboard correctly shows "FINALIZED" when all nodes are validated

### Key Files
- CREATE: `.claude/scripts/attractor/dashboard.py`
- MODIFY: `.claude/skills/s3-heartbeat/SKILL.md` (pipeline scanning)
- MODIFY: `.claude/scripts/attractor/cli.py` (add dashboard subcommand)

---

## Epic 6: Regression Detection via Baseline Comparison

### Problem
After implementation, there's no automated way to detect if changes introduced regressions in previously-stable components. ZeroRepo can compare pre- and post-implementation baselines but this isn't wired into the lifecycle.

### Requirements
- R6.1: `zerorepo update` runs after finalize stage, creating new baseline
- R6.2: `zerorepo diff --baseline-before --baseline-after` produces regression delta
- R6.3: Any component that moved from EXISTING to MODIFIED (unexpected change) is flagged
- R6.4: Regression findings added as new nodes to a `regression-check.dot` graph
- R6.5: Guardian reviews regression nodes as part of final validation

### Acceptance Criteria
- AC-6.1: Post-finalize workflow includes `zerorepo update` automatically
- AC-6.2: `zerorepo diff` identifies unexpected changes to EXISTING components
- AC-6.3: Regression nodes appear in `regression-check.dot` with affected file paths
- AC-6.4: Guardian receives regression findings in its final validation pass
- AC-6.5: No false positives: only truly unexpected changes are flagged (not refactoring of in-scope files)

### Key Files
- CREATE: `src/zerorepo/commands/diff.py`
- CREATE: `.claude/scripts/zerorepo-regression-check.sh`
- MODIFY: `.claude/skills/s3-guardian/SKILL.md` (regression check phase)

---

## Dependencies

```
Epic 1 ──► Epic 2 ──► Epic 3
                  ──► Epic 4
                  ──► Epic 5
Epic 1 ──────────────► Epic 6

Legend:
  Epic 1 (DOT Export) must complete first — all others depend on it
  Epic 2 (Definition) must complete before 3, 4, 5
  Epic 3 (Implementation) and Epic 4 (Validation) can run in parallel
  Epic 5 (Dashboard) can start after Epic 2
  Epic 6 (Regression) needs Epic 1 but is otherwise independent
```

## Implementation Order

| Phase | Epics | Rationale |
|-------|-------|-----------|
| Phase 1 | Epic 1 | Foundation: .dot export must work before anything else |
| Phase 2 | Epic 2 | Definition pipeline: end-to-end workflow from PRD to .dot |
| Phase 3 | Epic 3 + Epic 4 (parallel) | Implementation + Validation: can develop simultaneously |
| Phase 4 | Epic 5 + Epic 6 (parallel) | Dashboard + Regression: polish and safety net |

## Out of Scope

- Automatic pipeline traversal (covered by PRD-S3-ATTRACTOR-002-design)
- Event streams or HTTP API
- Multi-pipeline orchestration
- Dashboard UI (CLI output only)
- ZeroRepo changes to parsing or graph construction (only export extension)

## Success Metrics

1. **Time to pipeline**: PRD → executable .dot < 5 minutes (currently manual, ~30 min)
2. **Navigation accuracy**: System 3 dispatches correct worker type > 90% of the time
3. **Validation coverage**: Every implementation node has a paired validation gate
4. **Regression detection**: Catches unintended changes to out-of-scope components
5. **Single source of truth**: No separate task tracking needed — .dot graph IS the tracker
