---
title: "Guardian Lifecycle Launcher — Autonomous PRD-to-Implementation"
description: "Add lifecycle launcher function to guardian.py and teach system prompt to create child pipelines"
version: "1.0.0"
last-updated: 2026-03-21
status: active
type: prd
prd_id: PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001
---

# PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001: Guardian Lifecycle Launcher

## Problem Statement

The CoBuilder Guardian can drive pipelines autonomously (validated in session 2026-03-21). The `cobuilder-lifecycle` template v2.0 defines the full research→refine→plan→execute→validate→close lifecycle. But currently, launching a lifecycle pipeline requires manual steps:

1. Manually instantiate the template with parameters
2. Create placeholder state files so sd_path validation passes
3. Manually launch `guardian.py` with the rendered DOT path

The Guardian should be able to take a PRD path and autonomously drive the entire lifecycle — from research through implementation to validation — with a single command.

## User Story

**As the CoBuilder Guardian (interactive Opus session)**, I want to launch a self-driving lifecycle pipeline by providing only a PRD path, so the guardian agent autonomously researches, plans, implements, validates, and closes the initiative without manual pipeline construction.

## Requirements

### Epic 1: Lifecycle Launcher Function in guardian.py

Add a `launch_lifecycle()` function that:
1. Reads the PRD to extract `initiative_id` and `business_spec_path`
2. Creates placeholder state files (research.json, refined.md) so validation passes
3. Instantiates `cobuilder-lifecycle` template with auto-derived parameters
4. Validates the rendered DOT
5. Launches `guardian.py` on the rendered pipeline

**CLI interface:**
```bash
python3 cobuilder/engine/guardian.py --lifecycle <prd_path> \
    [--initiative-id <id>] \
    [--target-dir <path>] \
    [--max-cycles <n>] \
    [--model <model_id>]
```

If `--initiative-id` is not provided, derive it from the PRD filename (e.g., `PRD-AUTH-001.md` → `AUTH-001`).

**Acceptance Criteria:**
- AC-1.1: `--lifecycle` flag exists and accepts a PRD path
- AC-1.2: Function auto-derives initiative_id from PRD filename
- AC-1.3: Template instantiation happens automatically
- AC-1.4: Placeholder state files created before validation
- AC-1.5: Rendered DOT validates via `cli.py validate`
- AC-1.6: Guardian launches on the validated DOT

### Epic 2: System Prompt — Child Pipeline Creation at PLAN Node

The PLAN node in the lifecycle template generates a child implementation pipeline. The guardian's system prompt must teach it how to:
1. Read the refined BS from `state/{id}-refined.md`
2. Break the BS into implementation tasks
3. Use `cobuilder template instantiate` (or manual DOT creation) to generate the child pipeline
4. Write `state/{id}-plan.json` with `{dot_path, template, params}`
5. The next EXECUTE node (codergen) reads the plan and implements it

**Current gap**: The system prompt teaches pipeline management (status, transition, checkpoint) and CRUD (node add/modify/remove) but doesn't teach template instantiation or child pipeline generation.

**Acceptance Criteria:**
- AC-2.1: System prompt includes instructions for `cobuilder template instantiate` command
- AC-2.2: System prompt includes pattern for reading refined BS and generating implementation tasks
- AC-2.3: System prompt includes `state/{id}-plan.json` format specification
- AC-2.4: Dry-run shows template instantiation instructions in system prompt

## Key Files

| File | Changes |
|------|---------|
| `cobuilder/engine/guardian.py` | Add `launch_lifecycle()`, add `--lifecycle` CLI flag, update system prompt |
| `cobuilder/templates/instantiator.py` | No changes — already supports programmatic instantiation |
| `.cobuilder/templates/cobuilder-lifecycle/template.dot.j2` | No changes — v2.0 already passes validator |

## Testing

1. `guardian.py --lifecycle docs/prds/PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001.md --dry-run` — should show lifecycle pipeline config
2. Template instantiation produces valid DOT
3. System prompt contains template instantiation instructions
4. End-to-end: launch lifecycle on a simple PRD and observe research→implement→validate flow

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| E1: Lifecycle launcher function | Done | 2026-03-21 | pipeline-worker |
| E2: System prompt child pipeline | Done | 2026-03-21 | pipeline-worker |
| E3: Pilot terminology rename | Done | 2026-03-21 | pipeline-worker |
