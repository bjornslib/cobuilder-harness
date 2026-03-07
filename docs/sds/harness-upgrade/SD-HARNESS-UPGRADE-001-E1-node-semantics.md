---
title: "SD-HARNESS-UPGRADE-001 Epic 1: Node Semantics Clarification"
status: active
type: solution-design
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001 Epic 1: Node Semantics Clarification

## 1. Problem Statement

The DOT pipeline schema currently treats `wait.system3` and `wait.human` as informal conventions rather than formally defined handler types. Their behavior, required attributes, and topology constraints are documented inconsistently across `guardian-workflow.md`, `schema.md`, and `output-styles/system3-meta-orchestrator.md`. This leads to:

- Pipelines where codergen nodes have no downstream E2E validation gate
- `wait.human` nodes placed without a preceding summary-generating node
- Ambiguity about what `wait.system3` actually executes (is it automated? does it prompt?)

## 2. Design

### 2.1 Handler Type Definitions

#### `wait.system3` — Automated Gate

```dot
e1_e2e_gate [
    handler="wait.system3"
    gate_type="e2e"           # enum: "unit" | "e2e" | "contract"
    contract_ref="docs/prds/harness-upgrade/prd-contract.md"
    summary_ref=".claude/summaries/E1-gate-summary.md"
    label="E1 E2E Validation"
    shape=hexagon
]
```

**Behavior**: Fully automated. No human prompt. Executes:
1. Reads `concerns.jsonl` from worker concern queue
2. Runs acceptance tests matching `gate_type` (unit tests for "unit", Gherkin E2E for "e2e")
3. If `contract_ref` set: validates implementation against PRD Contract truths
4. Retains confidence score to Hindsight
5. Writes summary to `summary_ref` path
6. Transitions to `validated` or `failed`

#### `wait.human` — Human Review Gate

```dot
e1_human_review [
    handler="wait.human"
    summary_ref=".claude/summaries/E1-gate-summary.md"
    label="E1 Human Review"
    shape=octagon
]
```

**Behavior**: Always requires human input. Executes:
1. Reads summary from `summary_ref` (written by preceding `wait.system3` or `research` node)
2. Emits review request to GChat with summary content
3. Blocks until human responds (signal file or GChat reply)
4. Transitions to `validated` (approved) or `failed` (rejected)

### 2.2 Mandatory Topology Rules

**Rule 1**: Every codergen cluster follows the full topology:
```
acceptance-test-writer -> research -> refine -> codergen -> wait.system3[e2e] -> wait.human[e2e-review]
```
The `acceptance-test-writer` node generates blind Gherkin tests from the PRD before implementation begins. Intermediate nodes (`research`, `refine`) are optional but the start (`acceptance-test-writer`) and end (`wait.system3 -> wait.human`) are mandatory.

**Rule 2**: `wait.human` must have exactly one predecessor, which must be either:
- A `wait.system3` node (standard gate pair)
- A `research` node (research review)

**Rule 3**: `wait.system3` must have at least one codergen or research predecessor (it validates work, so there must be work to validate).

### 2.3 Executor Clarification

**`wait.system3` is executed by the Python runner** (`PipelineRunner` from E7.2), not by an LLM. The runner:
1. Reads signal files from completed predecessor workers
2. Reads `concerns.jsonl` for worker-raised concerns
3. Reflects via Hindsight (confidence trend, concern patterns)
4. Runs Gherkin E2E tests — for browser-based tests, uses Chrome MCP tools (`mcp__claude-in-chrome__*`)
5. Checks PRD Contract if `contract_ref` is set
6. Writes gate summary to `summary_ref`
7. If critical concerns exist or tests fail: transitions to `failed` and may requeue predecessor codergen node back to `pending` (with retry counter, max 2 retries)
8. If all pass: transitions to `validated`

### 2.4 Node Attribute Schema

| Attribute | Type | Required On | Description |
|-----------|------|-------------|-------------|
| `handler` | string | all | Handler type identifier |
| `gate_type` | enum | `wait.system3` | "unit", "e2e", or "contract" |
| `contract_ref` | path | `wait.system3` (optional) | Path to PRD Contract for validation |
| `summary_ref` | path | `wait.system3`, `wait.human` | Path where summary is written/read |
| `epic_id` | string | all (recommended) | Epic identifier for clustering |

## 3. Files Changed

| File | Change |
|------|--------|
| `agent-schema.md` (docs section) | Add `wait.system3` and `wait.human` handler definitions, attribute table, topology rules |
| `guardian-workflow.md` | Add topology validation to Phase 2 dispatch logic; add gate processing to Phase 4 |
| `output-styles/system3-meta-orchestrator.md` | Update DOT Graph Navigation section with gate pair requirement |

## 4. Testing

- **Manual verification**: Review updated schema docs for completeness
- **Existing pipeline audit**: Check all `.dot` files in `.claude/attractor/pipelines/` against new topology rules
- **Validator extension** (deferred to E5): `cobuilder pipeline validate` enforces these rules programmatically

## 5. Acceptance Criteria

- AC-1.1: `wait.system3` and `wait.human` fully documented with attribute schemas in `agent-schema.md`
- AC-1.2: Full codergen cluster topology documented: `acceptance-test-writer -> research -> refine -> codergen -> wait.system3[e2e] -> wait.human[e2e-review]`
- AC-1.3: At least one existing pipeline example updated to demonstrate the full cluster topology
- AC-1.4: `wait.system3` executor clarified as Python runner (not LLM), with Chrome MCP dependency for browser E2E tests
- AC-1.5: Requeue mechanism documented: failed `wait.system3` can transition predecessor codergen back to `pending`
