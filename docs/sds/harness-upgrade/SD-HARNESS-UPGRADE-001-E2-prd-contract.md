---
title: "SD-HARNESS-UPGRADE-001 Epic 2: PRD Contract + E2E Gate Protocol"
status: archived
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001 Epic 2: PRD Contract + E2E Gate Protocol

## 1. Problem Statement

PRDs evolve during implementation — user feedback, research findings, and technical discoveries all trigger scope changes. Without a frozen reference point, `wait.cobuilder` gates cannot detect drift. Workers may implement features that were added mid-flight without proper SD coverage, or skip features that were silently removed.

## 2. Design

### 2.1 PRD Contract Artifact

A `prd-contract.md` is generated at Phase 0 Checkpoint A.5 (after PRD + pipeline creation, before design challenge). It contains:

```markdown
---
prd_id: PRD-HARNESS-UPGRADE-001
contract_version: 1
generated: 2026-03-06T10:00:00Z
frozen_at_commit: abc123
---

# PRD Contract: System 3 Self-Management Upgrade

## Domain Invariants (3-5 truths that MUST hold)

1. Every codergen node cluster must have a downstream E2E validation gate
2. Workers must receive frozen SD content, not live SD files
3. Graph traversal must not invoke any LLM for state machine logic
4. Agent definitions must exist for every worker_type used in pipelines
5. PRD Contract violations detected by wait.cobuilder gates must block pipeline progression

## Scope Freeze

### In Scope (frozen)
- E1-E7 as defined in PRD sections 4-5
- Files listed in each epic's SD "Files Changed" section

### Explicitly Out of Scope
- Phase 3 epics (E8-E12)
- Worker prompt optimization
- Multi-repo coordination

## Compliance Flags

| Flag | Required | Rationale |
|------|----------|-----------|
| E2E_GATE_REQUIRED | true | G3 mandates E2E validation per epic |
| SD_FROZEN | true | G2 mandates SD version pinning |
| AGENT_REGISTRY | true | G4 mandates agent definitions for all worker_types |
```

### 2.2 Contract Generation Step

Inserted into Phase 0 between pipeline creation (Step 0.2) and design challenge (Step 0.4):

**Step 0.2.5 — Generate PRD Contract**:
1. Read PRD goals and epics
2. Extract 3-5 domain invariants (truths that must hold regardless of implementation approach)
3. List explicit scope boundaries (in-scope epics, out-of-scope items)
4. Set compliance flags based on goal requirements
5. Write to `docs/prds/{initiative}/prd-contract.md`
6. Record `frozen_at_commit` (current HEAD)

### 2.3 Contract Validation in wait.cobuilder Gates

When a `wait.cobuilder` node has `contract_ref` set:
1. Read the PRD Contract
2. For each domain invariant: verify it holds in the current codebase
3. For scope freeze: verify no files outside the frozen scope were modified
4. For compliance flags: verify each flag's condition is met
5. Score: contract compliance percentage (0.0-1.0)
6. Include in gate summary

### 2.4 Contract Amendment

Contracts are not immutable — but amendments require explicit action:
1. Increment `contract_version` in the frontmatter of `prd-contract.md`
2. Update the relevant section (invariants, scope, or compliance flags)
3. Add an `## Amendment Log` entry: `v{N} — {date} — {reason}`
4. Commit with message `amend(contract): {reason}`
5. Hindsight `retain()` records the amendment with reason

No external script needed — the contract is a doc-gardener-compatible markdown file with YAML frontmatter. Amendment is a manual edit with version increment, just like any other governed document.

## 3. Files Changed

| File | Change |
|------|--------|
| `phase0-prd-design.md` | Add Step 0.2.5 (contract generation); add E2E gate rule; add compliance gate rule |
| `guardian-workflow.md` | Add contract validation to `wait.cobuilder` processing logic |
| `SKILL.md` | Add `prd-contract.md` to Phase 0 artifact list |
| `prd-contract-template.md` (new) | Template for contract generation |

## 4. Testing

- Generate a contract for an existing PRD (PRD-PIPELINE-ENGINE-001) and verify it captures the right invariants
- Simulate a contract violation (modify out-of-scope file) and verify detection logic
- Verify contract amendment flow preserves history

## 5. Acceptance Criteria

- AC-2.1: PRD Contract template exists with required sections (invariants, scope freeze, compliance flags)
- AC-2.2: Phase 0 workflow includes contract generation step (Step 0.2.5)
- AC-2.3: `wait.cobuilder` gate logic includes contract validation when `contract_ref` is set
