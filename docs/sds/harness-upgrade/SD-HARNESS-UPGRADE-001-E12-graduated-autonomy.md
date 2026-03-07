---
title: "SD-HARNESS-UPGRADE-001 Epic 12: Graduated Autonomy Model"
status: draft
type: solution-design
last_verified: 2026-03-06
grade: draft
---

# SD-HARNESS-UPGRADE-001 Epic 12: Graduated Autonomy Model

> **Phase 3 — Future Work (~6-12 months)**. This SD is a vision document, not an implementation spec.

## 1. Problem Statement

Every pipeline currently requires the same level of human oversight regardless of track record. A PRD in a well-understood domain (e.g., adding a new API endpoint to an existing service) gets the same `wait.human` gates as a PRD in an unexplored domain (e.g., first-time integration with a new third-party API). This wastes human attention on low-risk work.

## 2. Design Vision

Three autonomy levels based on PRD Contract satisfaction track record:

| Level | Name | wait.human Behavior | Earned By |
|-------|------|---------------------|-----------|
| 1 | **Supervised** | Every epic gate requires explicit human approval | Default for new domains |
| 2 | **Guided** | wait.system3 auto-approves if score >= 0.8; wait.human only for scores < 0.8 | 3 consecutive epics at score >= 0.8 |
| 3 | **Autonomous** | wait.system3 auto-approves; wait.human only for contract violations | 5 consecutive initiatives completed successfully |

**Level assignment**:
- Per-domain, not per-initiative (e.g., "backend API changes" can be Level 2 while "frontend UX" stays Level 1)
- Tracked in `initiative.json` under `domain_autonomy_levels`
- Demoted on failure: any epic scoring < 0.6 resets domain to Level 1

**Contract satisfaction history**:
```json
{
  "domain_autonomy": {
    "backend-api": {"level": 2, "history": [0.85, 0.92, 0.88]},
    "frontend-ux": {"level": 1, "history": [0.72, 0.55]},
    "infrastructure": {"level": 1, "history": []}
  }
}
```

## 3. Files Changed

| File | Change |
|------|--------|
| `initiative.json` | `domain_autonomy` section |
| `pipeline_orchestrator.py` | `_handle_human` checks autonomy level before blocking |
| `wait.system3` handler | Auto-approve logic based on score + autonomy level |

## 4. Acceptance Criteria (Draft)

- AC-12.1: Three autonomy levels defined with clear promotion/demotion criteria
- AC-12.2: `wait.human` behavior varies by autonomy level
- AC-12.3: Domain history tracked and used for level assignment
- AC-12.4: Failure resets domain to Level 1
