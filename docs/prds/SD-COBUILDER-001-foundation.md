---
title: "SD: CoBuilder Foundation — Rename, Consolidate, Central Storage"
status: active
type: architecture
last_verified: 2026-02-27
grade: authoritative
prd_ref: PRD-COBUILDER-001
epic: 1
---

# SD-COBUILDER-001-E1: CoBuilder Foundation

## 1. Business Context

This epic establishes the `cobuilder/` top-level package by consolidating the Attractor DOT pipeline and ZeroRepo into a single product. It creates `.repomap/` as committed central baseline storage and establishes YAML as the default output format.

**Parent PRD**: PRD-COBUILDER-001, Epic 1
**Goal**: G4 (Single `cobuilder` CLI unifies all operations)

## 2. Technical Architecture

### Package Layout

```
cobuilder/
├── __init__.py                    # Package root, version string
├── __main__.py                    # Entry: python3 -m cobuilder
├── cli.py                         # Typer CLI: top-level command groups
├── bridge.py                      # RepoMap ↔ Pipeline adapter
├── repomap/                       # Moved from src/zerorepo/
│   ├── __init__.py
│   ├── models/
│   │   ├── component.py           # RPGNode, RPGEdge, RPGGraph
│   │   ├── enums.py               # NodeLevel, NodeType, DeltaStatus, EdgeType
│   │   └── functionality_graph.py
│   ├── graph_construction/
│   │   ├── builder.py             # FunctionalityGraphBuilder
│   │   ├── converter.py           # FunctionalityGraph → RPGGraph
│   │   └── exporter.py            # RPGGraph → DOT (renamed from attractor_exporter.py)
│   ├── rpg_enrichment/
│   │   ├── folder_encoder.py
│   │   ├── file_encoder.py
│   │   ├── data_flow_encoder.py
│   │   ├── intra_module_order_encoder.py
│   │   ├── base_class_encoder.py
│   │   └── interface_design_encoder.py
│   ├── serena/
│   │   ├── codebase_walker.py
│   │   ├── baseline_manager.py
│   │   └── delta_report_generator.py
│   ├── llm/
│   │   └── gateway.py             # LiteLLM gateway
│   └── cli/                       # RepoMap-specific CLI commands
│       └── commands.py
├── pipeline/                      # Moved from .claude/scripts/attractor/
│   ├── __init__.py
│   ├── generate.py                # DOT pipeline generation (Epic 2 modifies)
│   ├── transition.py              # State machine (Epic 4 modifies)
│   ├── dashboard.py
│   ├── signal_protocol.py
│   ├── validator.py
│   ├── checkpoint.py
│   ├── parser.py
│   ├── status.py
│   ├── node_ops.py
│   ├── edge_ops.py
│   ├── annotate.py
│   └── init_promise.py
└── orchestration/
    ├── __init__.py
    ├── spawn_orchestrator.py
    ├── pipeline_runner.py
    ├── identity_registry.py
    └── runner_tools.py
```

### Central Storage Layout

```
.repomap/                          # COMMITTED to git
├── config.yaml                    # Registry of tracked repositories
├── manifests/
│   └── <repo-name>.manifest.yaml  # Per-repo summary (node count, modules, delta)
└── baselines/
    └── <repo-name>/
        ├── baseline.json          # Full baseline graph (JSON — machine data)
        └── baseline.prev.json     # Previous baseline (for diff)
```

### config.yaml Schema

```yaml
# .repomap/config.yaml
version: "1.0"
repos:
  - name: agencheck
    path: /Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck
    last_synced: 2026-02-27T10:00:00Z
    baseline_hash: "sha256:abc123..."
    node_count: 3037
    file_count: 312
```

### manifest.yaml Schema

```yaml
# .repomap/manifests/agencheck.manifest.yaml
repository: agencheck
snapshot_date: 2026-02-27T10:00:00Z
total_nodes: 3037
total_files: 312
total_functions: 1847

top_modules:
  - name: src/auth/
    files: 8
    functions: 42
    delta: existing
  - name: src/api/
    files: 24
    functions: 156
    delta: existing

technology_stack:
  - Python 3.12
  - FastAPI
  - Supabase
  - PydanticAI
```

## 3. Integration Points

### Shell Function

Add to zsh profile (alongside `ccorch`, `ccsystem3`):

```bash
cobuilder() {
    python3 -m cobuilder "$@"
}
```

### Import Path Migration

| Old Import | New Import |
|-----------|-----------|
| `from zerorepo.models.graph import RPGGraph` | `from cobuilder.repomap.models.graph import RPGGraph` |
| `from zerorepo.graph_construction.attractor_exporter import AttractorExporter` | `from cobuilder.repomap.graph_construction.exporter import AttractorExporter` |
| `.claude/scripts/attractor/cli.py` | `cobuilder/cli.py` |
| `.claude/scripts/attractor/generate.py` | `cobuilder/pipeline/generate.py` |
| `.claude/scripts/attractor/transition.py` | `cobuilder/pipeline/transition.py` |

### Compatibility Redirects

During migration, `.claude/scripts/attractor/cli.py` becomes a thin redirect:

```python
#!/usr/bin/env python3
"""Redirect to cobuilder CLI. Remove after all references are updated."""
import sys
sys.argv[0] = "cobuilder"
from cobuilder.__main__ import main
main()
```

## 4. Functional Decomposition

### F1.1: Package Scaffolding

Create `cobuilder/` directory structure with `__init__.py`, `__main__.py`, `cli.py`.

**Dependencies**: None
**Files**: `cobuilder/__init__.py`, `cobuilder/__main__.py`, `cobuilder/cli.py`

### F1.2: Move RepoMap

Move `src/zerorepo/` → `cobuilder/repomap/`. Update all internal imports.

**Dependencies**: F1.1
**Files**: All files in `src/zerorepo/` → `cobuilder/repomap/`

### F1.3: Move Pipeline

Move pipeline modules from `.claude/scripts/attractor/` → `cobuilder/pipeline/`. Create compatibility redirect.

**Dependencies**: F1.1
**Files**: `generate.py`, `transition.py`, `dashboard.py`, `signal_protocol.py`, `validator.py`, `checkpoint.py`, `parser.py`, `status.py`, `node_ops.py`, `edge_ops.py`, `annotate.py`, `init_promise.py`

### F1.4: Move Orchestration

Move orchestration modules → `cobuilder/orchestration/`.

**Dependencies**: F1.1
**Files**: `spawn_orchestrator.py`, `pipeline_runner.py`, `identity_registry.py`, `runner_tools.py`

### F1.5: Central Storage Setup

Create `.repomap/` directory with `config.yaml` schema and gitignore exceptions.

**Dependencies**: F1.1
**Files**: `.repomap/config.yaml`, `.repomap/manifests/.gitkeep`, `.repomap/baselines/.gitkeep`

### F1.6: Bridge Module

Implement `cobuilder/bridge.py` with `init_repo`, `sync_baseline`, `get_repomap_context`, `refresh_baseline`.

**Dependencies**: F1.2, F1.5
**Files**: `cobuilder/bridge.py`

### F1.7: CLI Subcommands

Wire `cobuilder repomap init|sync|status|context` subcommands through `cli.py`.

**Dependencies**: F1.6
**Files**: `cobuilder/cli.py`, `cobuilder/repomap/cli/commands.py`

### F1.8: Test Migration

Update all test imports and verify existing test suite passes.

**Dependencies**: F1.2, F1.3, F1.4
**Files**: All test files referencing old import paths

## 5. Implementation Plan

**Order**: F1.1 → F1.2 → F1.3 → F1.4 → F1.5 → F1.6 → F1.7 → F1.8

1. Scaffold `cobuilder/` package (F1.1)
2. Move + rename RepoMap (F1.2) — largest change, ~23K lines
3. Move pipeline modules (F1.3) — create redirect for compatibility
4. Move orchestration modules (F1.4)
5. Create `.repomap/` structure (F1.5)
6. Implement bridge (F1.6) — new code, ~300 lines
7. Wire CLI subcommands (F1.7) — ~200 lines
8. Fix all test imports (F1.8) — bulk find-and-replace

## 6. Acceptance Criteria per Feature

| Feature | Criterion | Evidence Type |
|---------|-----------|--------------|
| F1.1 | `python3 -m cobuilder --help` shows command groups | test |
| F1.2 | `from cobuilder.repomap.models.graph import RPGGraph` imports successfully | test |
| F1.3 | `cobuilder validate pipeline.dot` works | test |
| F1.4 | `cobuilder agents --pipeline pipeline.dot` works | test |
| F1.5 | `.repomap/config.yaml` exists and is valid YAML | test |
| F1.6 | `cobuilder repomap init --target-dir /tmp/test --name test` creates baseline | e2e |
| F1.7 | `cobuilder repomap status` shows tracked repos | test |
| F1.8 | All existing tests pass with new import paths | test |

## 7. Risk Assessment

| Risk | Mitigation |
|------|------------|
| 23K line move breaks imports everywhere | Do F1.2 + F1.8 together; single atomic commit |
| Existing pipelines reference old CLI path | Compatibility redirect (F1.3) |
| `.repomap/` adds to git repo size | Baselines are ~500KB-2MB; acceptable |

## 8. File Scope

**New files**: `cobuilder/__init__.py`, `cobuilder/__main__.py`, `cobuilder/cli.py`, `cobuilder/bridge.py`, `.repomap/config.yaml`
**Moved files**: ~60 files from `src/zerorepo/` and `~30 files from `.claude/scripts/attractor/`
**Modified files**: All test files (import path updates)
**Deleted files**: `src/zerorepo/` (after move), eventually `.claude/scripts/attractor/` (after redirect period)
