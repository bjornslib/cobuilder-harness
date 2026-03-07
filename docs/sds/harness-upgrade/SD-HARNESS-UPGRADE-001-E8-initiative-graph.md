---
title: "SD-HARNESS-UPGRADE-001 Epic 8: Initiative Graph"
status: draft
type: solution-design
last_verified: 2026-03-06
grade: draft
---

# SD-HARNESS-UPGRADE-001 Epic 8: Initiative Graph

> **Phase 3 — Future Work (~6-12 months)**. This SD is a vision document, not an implementation spec.

## 1. Problem Statement

System 3 currently tracks initiatives implicitly through Hindsight memory and beads. There is no single structured object that represents "all active initiatives, their pipelines, their dependencies, and their progress." This forces System 3 to reconstruct initiative state from multiple sources at every session start.

## 2. Design Vision

A shared state object at `.claude/state/initiative.json`:

```json
{
  "initiatives": [
    {
      "id": "PRD-HARNESS-UPGRADE-001",
      "title": "System 3 Self-Management Upgrade",
      "status": "in_progress",
      "pipeline": ".claude/attractor/pipelines/PRD-HARNESS-UPGRADE-001.dot",
      "phases": [
        {"id": "phase-1", "status": "complete", "epics": ["E1", "E2", "E3"]},
        {"id": "phase-2", "status": "in_progress", "epics": ["E4", "E5", "E6", "E7"]},
        {"id": "phase-3", "status": "future", "epics": ["E8", "E9", "E10", "E11", "E12"]}
      ],
      "dependencies": [],
      "confidence_trend": [0.65, 0.72, 0.78]
    }
  ],
  "cross_dependencies": []
}
```

Benefits:
- Single source of truth for initiative state
- Enables cross-initiative dependency tracking
- Startup reflection can query structured data instead of free-text memory
- Dashboard/monitoring can read this directly

## 3. Files Changed

| File | Change |
|------|--------|
| `.claude/state/initiative.json` (new) | Initiative state schema and file |
| `output-styles/system3-meta-orchestrator.md` | Startup reads initiative.json |
| `pipeline_orchestrator.py` | Updates initiative.json after pipeline transitions |

## 4. Acceptance Criteria (Draft)

- AC-8.1: `initiative.json` schema defined with validation
- AC-8.2: System 3 startup reads initiative state from file
- AC-8.3: Pipeline transitions update initiative state
