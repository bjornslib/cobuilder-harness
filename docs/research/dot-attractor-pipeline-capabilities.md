---
title: "DOT Attractor Pipeline — Capabilities Reference"
status: active
type: reference
last_verified: 2026-02-27
grade: reference
---

# DOT Attractor Pipeline — Capabilities Reference

## Overview

The Attractor Pipeline is a CLI-based execution engine that manages initiative lifecycles as directed graphs in DOT format. Each node represents a task (implementation, validation, tooling) and edges encode dependencies and conditional routing. The pipeline is the backbone of System 3's orchestration — it determines what work is ready, what's blocked, and what's been validated.

**CLI location**: `cobuilder/engine/cli.py`
**Pipeline storage**: `.pipelines/pipelines/<INITIATIVE>.dot`
**Checkpoints**: `.pipelines/checkpoints/`

## Node Types

| Shape | Handler | Purpose | Lifecycle |
|-------|---------|---------|-----------|
| `box` | `codergen` | Implementation task | pending → active → impl_complete → validated |
| `box` | `toolcall` | Tool/script execution | pending → active → impl_complete → validated |
| `hexagon` | `validation` | Validation gate (tech/business) | pending → active → validated/failed |
| `circle` | sentinel | Entry point (`START`) | Static |
| `doublecircle` | sentinel | Exit point (`EXIT-OK`, `EXIT-FAIL`) | Static |
| `diamond` | `decision` | Conditional routing | pending → active → routed |

## Node Attributes

Every node can carry these attributes (set via `--set key=value`):

| Attribute | Purpose | Example |
|-----------|---------|---------|
| `status` | Current lifecycle state | `pending`, `active`, `impl_complete`, `validated`, `failed` |
| `handler` | Node type/handler | `codergen`, `toolcall`, `validation`, `decision` |
| `bead_id` | Linked beads issue ID | `bd-f7k2` |
| `label` | Human-readable name | `"Implement Auth Module"` |
| `worker_type` | Agent type for dispatch | `backend-solutions-engineer`, `frontend-dev-expert` |
| `acceptance` | Acceptance criteria text | `"POST /auth/login returns JWT"` |
| `files` | Comma-separated file scope | `"src/auth/routes.py,src/auth/jwt.py"` |
| `solution_design` | Path to SD document | `.taskmaster/docs/SD-AUTH-001.md` |
| `gate` | Validation gate type | `technical`, `business`, `e2e` |
| `mode` | Validation mode | `technical`, `business` |
| `promise_ac` | Completion promise AC ID | `AC-1` |
| `folder_path` | Target directory scope | `src/auth/` |

## CLI Commands

### Pipeline Lifecycle

| Command | Purpose | Example |
|---------|---------|---------|
| `generate` | Create pipeline from beads/PRD | `cli.py generate --prd PRD-AUTH-001 --output pipeline.dot` |
| `validate` | Check graph structure (cycles, pairing) | `cli.py validate pipeline.dot` |
| `status` | Show all node states | `cli.py status pipeline.dot --json --summary` |
| `transition` | Advance node state | `cli.py transition pipeline.dot node_id active` |
| `checkpoint` | Save/restore pipeline state | `cli.py checkpoint save pipeline.dot` |
| `dashboard` | Visual status display | `cli.py dashboard pipeline.dot` |

### Node & Edge CRUD

| Command | Purpose | Example |
|---------|---------|---------|
| `node add` | Add a node | `cli.py node pipeline.dot add task_auth --handler codergen --set bead_id=BD-123` |
| `node modify` | Update node attributes | `cli.py node pipeline.dot modify task_auth --set status=active` |
| `node remove` | Remove node + cascade edges | `cli.py node pipeline.dot remove task_deprecated` |
| `edge add` | Add dependency edge | `cli.py edge pipeline.dot add task_auth task_api --label "pass"` |
| `edge remove` | Remove specific edge | `cli.py edge pipeline.dot remove task_a task_b --condition fail` |
| `edge list` | List all edges | `cli.py edge pipeline.dot list --output json` |

### Advanced

| Command | Purpose | Example |
|---------|---------|---------|
| `annotate` | Add ZeroRepo delta info to nodes | `cli.py annotate pipeline.dot --zerorepo-baseline baseline.json` |
| `init-promise` | Create completion promise from pipeline | `cli.py init-promise pipeline.dot --prd PRD-AUTH-001` |
| `run` | Execute pipeline via LLM runner | `cli.py run pipeline.dot --execute` |
| `guardian` | Launch guardian validation | `cli.py guardian pipeline.dot --prd PRD-AUTH-001` |
| `agents` | List registered agent identities | `cli.py agents --pipeline pipeline.dot` |

## Transition Engine

**File**: `cobuilder/engine/transition.py`

### State Machine

```
pending ──► active ──► impl_complete ──► validated
                 │                           │
                 └──► failed ◄───────────────┘
                       │
                       └──► active (retry)
```

### Hexagon Cascade (R4.1)

When a `codergen` node transitions to `impl_complete`, the transition engine automatically cascades to its paired hexagon validation nodes:

```
codergen (impl_complete) ──auto──► tech_hex (active) ──validate──► tech_hex (validated)
                                                                         │
                                                              ──auto──► biz_hex (active)
```

### Decision Routing (R4.5)

Diamond nodes route based on upstream validation results:
- All upstream `validated` → follow `pass` edge
- Any upstream `failed` → follow `fail` edge

### Finalize Gate (R4.7)

A special gate that checks if ALL codergen nodes are in terminal state (`validated` or `failed`) before allowing pipeline completion. Writes signal files to `.pipelines/signals/`.

### Concurrency Safety

Uses `fcntl.flock()` for file-level locking. All transitions are atomic — partial transitions cannot corrupt the DOT file.

### Audit Trail

Every transition is logged to `<pipeline>.transitions.jsonl`:
```json
{"timestamp": "2026-02-25T11:28:06Z", "node": "impl_auth", "from": "pending", "to": "active", "actor": "cobuilder"}
```

## Pipeline Generation (`generate.py`)

### Bead-to-Node Mapping

The `filter_beads_for_prd()` function at line ~174 heuristically matches beads to PRDs:
1. Find epic beads whose title contains the PRD reference
2. Find task beads that are children of those epics via `parent-child` dependency
3. Find task beads whose title/description contains the PRD reference

**Requirement**: Beads must include the PRD ID in their metadata for auto-mapping to work.

### Generated Structure

For each task bead, generate.py creates a triplet:
```
codergen_node → tech_validation_hex → biz_validation_hex → decision_diamond
```

Plus `START` → first node and last decision → `EXIT-OK` / `EXIT-FAIL` edges.

### Flags

| Flag | Purpose |
|------|---------|
| `--prd PRD-ID` | Filter beads by PRD reference |
| `--scaffold` | Create minimal template (no bead mapping) |
| `--target-dir PATH` | Cross-repo: analyze beads in another directory |
| `--no-filter` | Include all beads (no PRD filtering) |

## Signal Protocol

**File**: `cobuilder/engine/signal_protocol.py`

Inter-layer communication for the 4-layer chain (Guardian → Runner → Orchestrator → Worker):

| Signal | Direction | Meaning |
|--------|-----------|---------|
| `NEEDS_REVIEW` | Runner → Guardian | Node ready for validation |
| `VALIDATION_PASSED` | Guardian → Runner | Node validated successfully |
| `VALIDATION_FAILED` | Guardian → Runner | Node failed validation |
| `DISPATCH_READY` | Runner → Orchestrator | New node dispatched |
| `IMPL_COMPLETE` | Orchestrator → Runner | Implementation finished |

Signals are atomic file writes with timestamp-based naming in `pipelines/signals/`.

## Pipeline Runner (`pipeline_runner.py`)

Production LLM runner using Anthropic SDK with `claude-sonnet-4-6`:

- **11 tools**: spawn_orchestrator, dispatch_validation, transition_node, checkpoint, etc.
- **Two modes**: `--plan` (default, dry-run) and `--execute` (real dispatch)
- **Agent identity**: Registered in `identity_registry` with session tracking

## Dashboard (`dashboard.py`)

4-stage lifecycle display:
```
Definition ──► Implementation ──► Validation ──► Finalized
```

Shows node status distribution with ASCII bar charts. Known limitation: `estimated_completion` always "N/A" because DOT format doesn't store per-transition timestamps.

## Key File Locations

| File | Purpose |
|------|---------|
| `cobuilder/engine/cli.py` | Central CLI entry point |
| `cobuilder/engine/generate.py` | Pipeline DOT generation from beads |
| `cobuilder/engine/transition.py` | State machine + hexagon cascade |
| `cobuilder/engine/dashboard.py` | Visual status display |
| `cobuilder/engine/signal_protocol.py` | Inter-layer signal communication |
| `cobuilder/engine/pipeline_runner.py` | LLM-driven pipeline execution |
| `cobuilder/engine/spawn_orchestrator.py` | tmux orchestrator spawning |
| `.pipelines/pipelines/` | Pipeline DOT files |
| `.pipelines/checkpoints/` | Saved pipeline states |
| `.pipelines/signals/` | Signal files for inter-layer comms |
| `.pipelines/runner-state/` | Runner execution state |

## Current Gaps

1. **No ZeroRepo integration in generate.py**: Pipeline generation uses beads only — no codebase structure awareness
2. **No cross-repo baseline tracking**: `--target-dir` exists but doesn't leverage ZeroRepo baselines
3. **No estimated completion**: Dashboard can't estimate because timestamps aren't in DOT attributes
4. **No standalone diff command**: Regression detection referenced in memory but not implemented as standalone CLI
5. **No live SD context injection**: Nodes have `solution_design` attribute but generate.py doesn't populate it from SDs

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
