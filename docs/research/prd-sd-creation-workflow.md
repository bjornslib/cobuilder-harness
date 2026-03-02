---
title: "PRD/SD Creation Workflow — End-to-End Reference"
status: active
type: reference
last_verified: 2026-02-27
grade: reference
---

# PRD/SD Creation Workflow — End-to-End Reference

## Overview

This document maps the complete workflow from business idea to executing orchestrators, showing where each tool (PRD, SD, ZeroRepo, Task Master, Beads, Attractor DOT) fits in the pipeline. Understanding this flow is critical for designing ZeroRepo's deeper integration.

## The Full Pipeline

```
Business Goal
    │
    ▼
┌─────────────────────────────────────┐
│  1. PRD (Product Requirements Doc)  │  ← System 3 or Guardian writes
│     docs/prds/PRD-{ID}.md           │  ← Business goals, user stories, epics
│     .taskmaster/docs/PRD-{ID}.md    │  ← Same content, Task Master location
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  2. ZeroRepo Baseline (Step 2.5)    │  ← `zerorepo init --project-path <dir>`
│     <project>/.zerorepo/baseline.json│  ← Codebase snapshot BEFORE implementation
│                                      │  ← Delta: what's EXISTING/MODIFIED/NEW
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  3. Solution Design (SD) per Epic   │  ← `solution-design-architect` agent
│     .taskmaster/docs/SD-{ID}.md     │  ← Technical: data models, API contracts,
│                                      │    component design, file scope, acceptance
│                                      │    criteria per feature
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  4. Task Master Parsing             │  ← `mcp__task-master-ai__parse_prd()`
│     .taskmaster/tasks/tasks.json    │  ← Structured tasks with dependencies
│                                      │  ← Input: PRD + SD
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  5. Beads Sync                      │  ← `sync-taskmaster-to-beads.js`
│     .beads/issues.jsonl             │  ← Git-tracked issue tracking
│                                      │  ← Epics → Tasks with parent-child deps
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  6. DOT Pipeline Generation         │  ← `cli.py generate --prd PRD-{ID}`
│     .claude/attractor/pipelines/    │  ← Directed graph with typed nodes
│     <INITIATIVE>.dot                 │  ← Maps beads to codergen + validation nodes
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  7. Acceptance Tests (Blind)        │  ← `Skill("acceptance-test-writer")`
│     acceptance-tests/PRD-{ID}/      │  ← Gherkin + executable browser tests
│                                      │  ← Stored in config repo (blind to impl)
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  8. Orchestrator Dispatch           │  ← `spawn_orchestrator.py` via tmux
│     One per epic/DOT node           │  ← Receives: SD, wisdom, bead ID, file scope
│                                      │  ← Delegates to workers via Agent Teams
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│  9. Validation (Guardian)           │  ← Phase 4: Independent blind scoring
│     .claude/evidence/PRD-{ID}/      │  ← Per-feature confidence + journey tests
│                                      │  ← DOT transitions: validated/failed
└─────────────────────────────────────┘
```

## Step-by-Step Detail

### Step 1: PRD Authoring

**Who**: System 3 (meta-orchestrator) or Guardian
**Input**: Business goal, user stories, domain context
**Output**: `docs/prds/PRD-{CATEGORY}-{DESCRIPTOR}.md`

PRD structure:
- YAML frontmatter: `prd_id`, `title`, `status`, `created`
- Section 1: Executive Summary
- Section 2: Goals (maps to journey tests)
- Section 3: User Stories
- Section 4-7: Epic breakdown with acceptance criteria per epic
- Section 8: Technical approach

**Key principle**: PRD is a BUSINESS document. It defines WHAT, not HOW.

### Step 2: ZeroRepo Baseline (Step 2.5)

**Who**: Orchestrator or Guardian (automated)
**Input**: Target codebase directory
**Output**: `.zerorepo/baseline.json`

```bash
# Analyze target codebase
zerorepo init --project-path /path/to/impl-repo

# Result: baseline.json with node/edge counts
# Example: 3,037 nodes for zenagent2/agencheck
```

This step creates a BEFORE snapshot. After implementation, a new baseline is generated and `zerorepo diff` compares them for regression detection.

**Current integration**: ZEROREPO.md defines this as Step 2.5, slotting between PRD creation and Task Master parsing. The 8-step `zerorepo-pipeline.sh` automates: check baseline → generate RPG → copy to pipelines → validate → annotate → init-promise → checkpoint → summary.

### Step 3: Solution Design (SD) per Epic

**Who**: `solution-design-architect` agent (delegated by System 3)
**Input**: PRD epic section + ZeroRepo baseline (when available)
**Output**: `.taskmaster/docs/SD-{CATEGORY}-{NUMBER}-{epic-slug}.md`

SD structure:
- Section 1: Business Context (from PRD)
- Section 2: Technical Architecture (data models, API contracts, component design)
- Section 3: Integration Points
- Section 4: Functional Decomposition (features with dependencies)
- Section 5: Implementation Plan
- Section 6: Acceptance Criteria per Feature
- Section 7: Risk Assessment
- Section 8: File Scope (which files workers are allowed to touch)

**Key principle**: SD is a TECHNICAL document. It defines HOW, scoped to one epic.

**Gap**: SDs currently do NOT receive ZeroRepo codebase context. The solution-design-architect works from the PRD + manual codebase exploration. This is a primary integration target.

### Step 4: Task Master Parsing

**Who**: System 3 via MCP
**Input**: PRD (and optionally SD)
**Output**: `.taskmaster/tasks/tasks.json`

```python
mcp__task-master-ai__parse_prd(
    input="docs/prds/PRD-{ID}.md",
    project_root="/path/to/impl-repo"
)
```

Task Master decomposes the PRD into structured tasks with:
- Dependencies between tasks
- Priority levels
- Subtask breakdown
- Complexity estimates

### Step 5: Beads Sync

**Who**: Automated script
**Input**: `.taskmaster/tasks/tasks.json`
**Output**: `.beads/issues.jsonl`

```bash
node .claude/skills/orchestrator-multiagent/scripts/sync-taskmaster-to-beads.js \
    --project-root /path/to/impl-repo
```

Creates beads issues with:
- Epic beads (parent)
- Task beads (children) with `parent-child` dependency type
- PRD ID in title for auto-mapping: `"PRD-AUTH-001: Implement login endpoint"`

### Step 6: DOT Pipeline Generation

**Who**: Guardian or System 3
**Input**: Beads + PRD reference
**Output**: `.claude/attractor/pipelines/<INITIATIVE>.dot`

```bash
python3 .claude/scripts/attractor/cli.py generate \
    --prd PRD-AUTH-001 \
    --output .claude/attractor/pipelines/auth-initiative.dot
```

The `filter_beads_for_prd()` function matches beads to the PRD by title/description heuristics. Each task bead becomes a `codergen → tech_hex → biz_hex → decision` triplet.

**Critical**: Beads MUST include the PRD ID in their titles for auto-mapping.

### Step 7: Acceptance Tests

**Who**: Guardian (Phase 1 of s3-guardian skill)
**Input**: SD documents (per-epic Gherkin) + PRD (journey tests)
**Output**: `acceptance-tests/PRD-{ID}/` in config repo

Two modes:
- `--mode=guardian`: Per-epic Gherkin scenarios with confidence scoring
- `--mode=journey`: Cross-epic business flow scenarios

Stored in config repo (claude-harness-setup), NOT impl repo — blind to implementers.

### Step 8: Orchestrator Dispatch

**Who**: Guardian or System 3
**Tool**: `spawn_orchestrator.py`

Each orchestrator receives:
- Epic scope + bead IDs
- SD document path (primary technical reference)
- DOT node context (acceptance, file scope, worker type)
- Hindsight wisdom (patterns from prior sessions)

Orchestrators delegate to workers via native Agent Teams.

### Step 9: Validation

**Who**: Guardian (Phase 4 of s3-guardian skill)
**Input**: Blind acceptance tests + actual code
**Output**: Evidence at `.claude/evidence/PRD-{ID}/`

Guardian independently reads code and scores against blind rubric. DOT nodes transition to `validated` or `failed` based on results.

## Where ZeroRepo Fits Today vs. Where It Should Fit

| Step | Current ZeroRepo Role | Desired Role |
|------|----------------------|--------------|
| 1. PRD | None | Codebase context for goal feasibility |
| 2. Baseline | Create snapshot | Same + multi-repo aggregation |
| 3. SD | None | **PRIMARY**: Inject codebase graph as SD context |
| 4. Task Master | None | Codebase-aware task decomposition |
| 5. Beads | None | Auto-tag beads with file scope from RPG |
| 6. DOT Generation | `annotate` command adds delta info | **PRIMARY**: RPG drives node creation, not just beads |
| 7. Acceptance Tests | None | Scope tests to actual file changes |
| 8. Orchestrator | Step 2.5 in workflow | Live baseline updates as nodes complete |
| 9. Validation | Regression check (Phase 4.5) | Same + compare against RPG predictions |

## Cross-Repo Considerations

| Aspect | Current | Needed |
|--------|---------|--------|
| Baseline location | `<repo>/.zerorepo/` | Central location or per-repo with aggregation |
| Analysis command | `zerorepo init --project-path <dir>` | Same, but triggered from config repo |
| DOT generation | Single repo beads | Multi-repo beads with `--target-dir` |
| Worktree awareness | None | Detect worktrees, share/sync baselines |
| SD context | None | Inject all repo baselines relevant to the epic |

## Key File Locations

| File | Purpose |
|------|---------|
| `docs/prds/PRD-{ID}.md` | Business requirements |
| `.taskmaster/docs/SD-{ID}.md` | Technical solution design per epic |
| `.taskmaster/tasks/tasks.json` | Task Master structured tasks |
| `.beads/issues.jsonl` | Git-tracked issue tracking |
| `.claude/attractor/pipelines/*.dot` | Execution pipeline graphs |
| `acceptance-tests/PRD-{ID}/` | Blind acceptance tests (config repo) |
| `.zerorepo/baseline.json` | Codebase snapshot |
| `src/zerorepo/` | ZeroRepo implementation (14 modules) |
| `.claude/scripts/attractor/` | Attractor CLI + runner |
