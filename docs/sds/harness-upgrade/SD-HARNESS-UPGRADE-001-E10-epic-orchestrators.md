---
title: "SD-HARNESS-UPGRADE-001 Epic 10: Epic-Scoped Orchestrators + Parallel Execution"
status: draft
type: reference
last_verified: 2026-03-06T00:00:00.000Z
grade: draft
---
# SD-HARNESS-UPGRADE-001 Epic 10: Epic-Scoped Orchestrators + Parallel Execution

> **Phase 3 — Future Work (\~6-12 months)**. This SD is a vision document, not an implementation spec.

## 1. Problem Statement

Currently, a single pipeline_orchestrator.py instance processes nodes sequentially (with async dispatch for independent nodes). For large initiatives with 5+ epics, independent epics could execute in parallel — each with its own orchestrator instance, worktree, and worker pool.

## 2. Design Vision

```
pipeline_orchestrator.py (parent)
  |-- Identifies independent epic clusters (no cross-epic dependencies)
  |-- Spawns child pipeline_orchestrator.py per epic (in separate worktrees)
  |-- Coordinates via shared initiative.json + event bus
  |-- Merges worktrees on epic completion
  |-- Respects dependency ordering between dependent epics
```

Key design decisions:
- Each epic gets its own git worktree (isolation)
- Parallel epics use asyncio.TaskGroup for concurrent dispatch
- Dependent epics wait for predecessor epic's `wait.cobuilder` gate to pass
- Merge conflicts between parallel worktrees resolved by a dedicated merge worker

## 3. Files Changed

| File | Change |
| --- | --- |
| `pipeline_orchestrator.py` | Epic-level parallelism via asyncio.TaskGroup |
| `worktree-manager` | Programmatic worktree creation per epic |
| `initiative.json` | Per-epic status tracking |

## 4. Acceptance Criteria (Draft)

- AC-10.1: Independent epics execute in parallel
- AC-10.2: Dependent epics respect ordering
- AC-10.3: Worktree isolation prevents cross-epic file conflicts
