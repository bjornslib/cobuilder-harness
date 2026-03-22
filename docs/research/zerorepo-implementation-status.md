---
title: "ZeroRepo Implementation Status"
status: active
type: reference
last_verified: 2026-02-27
grade: reference
---

# ZeroRepo Implementation Status

## Overview

ZeroRepo is our local implementation of the RPG (Repository Planning Graph) paper. It lives at `src/zerorepo/` with 14 sub-modules covering all 3 stages of the RPG pipeline plus our extensions (delta classification, Serena integration, Attractor export).

## Module Inventory

### Core Models (`src/zerorepo/models/`)

| File | Contents | Status |
|------|----------|--------|
| `component.py` | `RPGNode`, `RPGEdge`, `RPGGraph` dataclasses | Complete |
| `enums.py` | `NodeLevel`, `NodeType`, `DeltaStatus`, `EdgeType` | Complete |
| `functionality_graph.py` | `FunctionalityGraph` (Stage 1 output) | Complete |

**DeltaStatus enum**: `EXISTING`, `MODIFIED`, `NEW` — our extension for iterative development.

### Graph Construction (`src/zerorepo/graph_construction/`)

| File | Purpose | Status |
|------|---------|--------|
| `builder.py` | `FunctionalityGraphBuilder` — Stage 1 construction | Complete |
| `converter.py` | `FunctionalityGraph → RPGGraph` conversion with delta tagging | Complete |
| `attractor_exporter.py` | `RPGGraph → DOT` pipeline export (Attractor format) | Complete |

**AttractorExporter**: Converts RPG delta graphs into DOT pipeline triplets. Only MODIFIED/NEW nodes get pipeline nodes — EXISTING nodes are skipped.

### RPG Enrichment (`src/zerorepo/rpg_enrichment/`)

5 sequential encoders (Stage 2):

| Encoder | Input | Output | LLM? | Status |
|---------|-------|--------|------|--------|
| `FolderEncoder` | RPGGraph | FOLDER nodes | No | Complete |
| `FileEncoder` | RPGGraph + folders | FILE nodes with paths | No | Complete |
| `DataFlowEncoder` | RPGGraph + files | DATA_FLOW edges | No | Complete |
| `IntraModuleOrderEncoder` | RPGGraph + files | FUNCTION nodes with order | No | Complete |
| `BaseClassEncoder` | RPGGraph + functions | CLASS nodes + inheritance | No | Complete |

Plus 1 LLM-powered encoder:

| Encoder | Input | Output | LLM? | Status |
|---------|-------|--------|------|--------|
| `InterfaceDesignEncoder` | RPGGraph (enriched) | Function signatures, docstrings | Yes | Complete |

### CLI (`src/zerorepo/cli/`)

Typer-based CLI:

| Command | Purpose | Status |
|---------|---------|--------|
| `zerorepo init --project-path <dir>` | Analyze codebase, create baseline | Complete |
| `zerorepo generate --project-path <dir>` | Generate RPG from codebase | Complete |
| `zerorepo diff --before <json> --after <json>` | Compare two baselines | Complete |

**Cross-repo support**: `--project-path` analyzes arbitrary directories (not just cwd).

### Serena Integration (`src/zerorepo/serena/`)

| File | Purpose | Status |
|------|---------|--------|
| `codebase_walker.py` | File-based codebase walking | Complete |
| `baseline_manager.py` | Baseline snapshot creation/storage | Complete |
| `delta_report_generator.py` | Diff reports between baselines | Complete |

### LLM Gateway (`src/zerorepo/llm/`)

| File | Purpose | Status |
|------|---------|--------|
| `gateway.py` | LiteLLM gateway with retry, token tracking, cost estimation | Complete |

Uses `claude-sonnet-4-6` via LiteLLM. Timeout fix: explicit kwarg required (env var + monkey-patch don't propagate).

### Orchestrator Integration

| File | Purpose | Status |
|------|---------|--------|
| `.claude/skills/orchestrator-multiagent/ZEROREPO.md` | Step 2.5 integration guide | Complete |
| `.claude/skills/orchestrator-multiagent/scripts/zerorepo-pipeline.sh` | 8-step definition pipeline | Complete |

**ZeroRepo Step 2.5**: Slots between PRD creation and Task Master parsing in the orchestrator workflow. 3 operations: `init` (baseline), `generate` (RPG), `update` (delta).

## Test Coverage

- **4,191 tests** passing (Sprint 1 through E2E)
- **40 delta classification tests** (Sprint 3)
- **46 E2E tests** (Sprint E2E)
- Runtime: ~28 seconds

## Pipeline Performance

| Metric | Value |
|--------|-------|
| Full `init` on my-org/my-project | ~2.5 minutes |
| Nodes generated | 3,037 (large codebase) |
| E2E validation (29 nodes, 46 edges) | ~30 seconds |
| Delta accuracy | Needs improvement (1/12 module match in early testing) |

## Baseline Storage

```
<project>/.zerorepo/
├── baseline.json          # Current baseline snapshot
├── baseline.before.json   # Pre-update snapshot (for diff)
└── regression-check.dot   # Output of zerorepo diff (DOT format)
```

## Known Issues & Gaps

### Delta Accuracy
- **Critical**: Early testing showed 1/12 module match accuracy
- **Root cause**: Naming mismatches between Serena's file-based walking and RPG's capability-based naming
- **Status**: Improved with LLM-based delta tagging (Sprint 3) but not re-benchmarked

### Cross-Repo Limitations
- `--project-path` works for single-repo analysis
- No multi-repo baseline aggregation (analyzing repo A + repo B into unified graph)
- No worktree-aware baseline (worktrees share .zerorepo/ with main checkout)

### Missing Capabilities
1. **No live Serena integration**: CodebaseWalker uses file-based walking, not Serena's LSP
2. **No incremental update**: Must regenerate full baseline (no append/patch)
3. **No cost estimation before run**: LLM gateway tracks cost but doesn't predict
4. **No pipeline integration**: ZeroRepo and Attractor CLI are separate — no shared context

### Integration with DOT Pipeline (Current State)

| Integration Point | Status | Detail |
|-------------------|--------|--------|
| `attractor_exporter.py` | Complete | Converts RPG → DOT with triplets |
| `cli.py annotate` | Complete | Adds ZeroRepo delta info to existing DOT |
| `generate.py --target-dir` | Partial | Exists but doesn't use ZeroRepo baseline |
| Live baseline updates during impl | Missing | No mechanism to update baseline as nodes complete |
| SD context injection from RPG | Missing | SDs don't receive codebase graph context |
| Multi-repo unified graph | Missing | Each repo has isolated baseline |

## Key Design Documents

| Document | Location |
|----------|----------|
| ZeroRepo Delta Design | `docs/ZEROREPO_DELTA_DESIGN.md` |
| Serena Integration Design | `docs/ZEROREPO_SERENA_DESIGN.md` |
| Implementation Plan | `docs/research/rpg-implementation-plan.pdf` |
| Orchestrator Integration | `.claude/skills/orchestrator-multiagent/ZEROREPO.md` |

## Completed Initiatives

| Sprint | Commit | Lines | Key Deliverable |
|--------|--------|-------|-----------------|
| Sprint 1 | `08eac73` | +1,938 | Pipeline connected |
| Sprint 1.5 | `86c9fd3` | +1,162 | 34 nodes, 51 edges |
| Sprint 2 | `5385449` | +7,563 | Serena baseline, E2E validated |
| Sprint 3 | `30473cf` | +575 | Delta classification, orchestrator skill |
| E2E | `d76b1e0` | +12,291 | Full pipeline validated |

**Total**: 52 files, ~23,500 lines of code

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
