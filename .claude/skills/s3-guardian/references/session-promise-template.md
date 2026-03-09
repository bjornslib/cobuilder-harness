---
title: "Session Promise Integration Template"
status: active
type: reference
last_verified: 2026-03-09
grade: authoritative
---

# Session Promise Integration (Guardian Validation Template)

The guardian session itself tracks completion via the `cs-promise` CLI.

> **DISAMBIGUATION**: `cs-promise` creates/manages promises. `cs-verify` verifies them.
> **CORRECT**: `cs-verify --promise <id>` | **WRONG**: `cs-promise --verify <id>` (flag doesn't exist)

## At Guardian Session Start

```bash
# Initialize completion state
cs-init

# Create guardian promise
cs-promise --create "Guardian: Validate PRD-{ID} implementation" \
    --ac "PRD designed, pipeline created, and design challenge passed (Phase 0)" \
    --ac "Acceptance tests and executable browser tests created in config repo" \
    --ac "Orchestrator(s) spawned and verified running" \
    --ac "Orchestrator progress monitored through completion" \
    --ac "Independent validation scored against rubric" \
    --ac "Final verdict delivered with evidence"
```

## During Monitoring

```bash
# Meet criteria as work progresses
cs-promise --meet <id> --ac-id AC-1 --evidence "acceptance-tests/PRD-{ID}/ created with N scenarios + executable browser tests" --type manual
cs-promise --meet <id> --ac-id AC-2 --evidence "headless worker process running for orch-{initiative}, output style verified" --type manual
```

## At Validation Complete

```bash
# Meet remaining criteria
cs-promise --meet <id> --ac-id AC-3 --evidence "Monitored for 2h15m, 3 interventions" --type manual
cs-promise --meet <id> --ac-id AC-4 --evidence "Weighted score: 0.73 (ACCEPT threshold: 0.60)" --type manual
cs-promise --meet <id> --ac-id AC-5 --evidence "ACCEPT verdict, report stored to Hindsight" --type manual

# Verify all criteria met
cs-verify --check --verbose
```
