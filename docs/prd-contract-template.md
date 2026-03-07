---
title: "PRD Contract Template"
status: active
type: template
last_verified: 2026-03-07
grade: authoritative
---

# PRD Contract: {PROJECT_NAME}

## Domain Invariants (3-5 truths that MUST hold)

1. Every codergen node cluster must have a downstream E2E validation gate
2. Workers must receive frozen SD content, not live SD files
3. Graph traversal must not invoke any LLM for state machine logic
4. Agent definitions must exist for every worker_type used in pipelines
5. PRD Contract violations detected by wait.system3 gates must block pipeline progression

## Scope Freeze

### In Scope (frozen)
- {EPICS_AS_DEFINED_IN_PRD}
- Files listed in each epic's SD "Files Changed" section

### Explicitly Out of Scope
- {PHASE_3_EPICS_IF_APPLICABLE}
- Worker prompt optimization
- Multi-repo coordination

## Compliance Flags

| Flag | Required | Rationale |
|------|----------|-----------|
| E2E_GATE_REQUIRED | true | G3 mandates E2E validation per epic |
| SD_FROZEN | true | G2 mandates SD version pinning |
| AGENT_REGISTRY | true | G4 mandates agent definitions for all worker_types |

## Amendment Log

| Version | Date | Reason |
|---------|------|--------|
| v1 | {DATE} | Initial contract generation |