---
title: "Phase 0: PRD + Pipeline Creation"
status: active
type: guide
last_verified: 2026-03-07
grade: authoritative
---

# Phase 0: PRD + Pipeline Creation

## Overview
Phase 0 establishes the foundational artifacts for a new initiative: the PRD, the pipeline structure, and the initial task breakdown.

## Steps

### Step 0.1: PRD Creation
- Generate PRD document based on user requirements
- Include executive summary, goals, epics, success metrics
- Store in `docs/prds/{initiative}/PRD-{ID}.md`

### Step 0.2: Pipeline Creation
- Generate DOT pipeline files for each epic
- Create node clusters for each epic's tasks
- Establish dependencies between epics if needed
- Store in `.claude/pipelines/{initiative}/`

### Step 0.2.5: Generate PRD Contract
- Read PRD goals and epics
- Extract 3-5 domain invariants (truths that must hold regardless of implementation approach)
- List explicit scope boundaries (in-scope epics, out-of-scope items)
- Set compliance flags based on goal requirements
- Write to `docs/prds/{initiative}/prd-contract.md`
- Record `frozen_at_commit` (current HEAD)

### Step 0.2.6: SD Version Pinning Protocol
- After refine node completes, git-tag the SD:
  ```bash
  git tag sd/{prd-id}/E{n}/v{version} -- docs/sds/{initiative}/SD-{id}.md
  ```
- Codergen node's `sd_ref` attribute points to the tag (not the file path):
  ```
  impl_e1 [handler="codergen" sd_ref="sd/HARNESS-UPGRADE-001/E1/v1"]
  ```
- `dispatch_worker.py` resolves the tag to file content at dispatch time:
  ```bash
  git show sd/HARNESS-UPGRADE-001/E1/v1:docs/sds/harness-upgrade/SD-...-E1-node-semantics.md
  ```
- Signal evidence includes `sd_hash` (SHA256 of the resolved content)

#### Naming Convention:
- Format: `sd/{prd-id}/E{epic}/v{version}` (e.g., `sd/HARNESS-UPGRADE-001/E1/v1`)
- Applied after refine nodes to freeze the SD version before codergen implementation

### Step 0.3: Bead Hierarchy Creation
- Create epic-level beads (one per epic)
- Create feature-level beads within each epic
- Establish dependency relationships
- Assign to appropriate teams/individuals

### Step 0.4: Design Challenge Process
- Launch research-first investigation for each epic
- Generate solution design documents
- Create acceptance tests before implementation
- Validate designs with stakeholders

## E2E Gate Rule
For each epic defined in the PRD, an E2E validation gate must be established as part of the pipeline. This ensures that every major feature has end-to-end validation before being considered complete.

## Compliance Gate Rule
PRD Contract validation must occur at designated checkpoints. The contract defines domain invariants that must remain true and scope boundaries that must not be violated during implementation.

## Output Artifacts
- PRD document
- DOT pipeline files
- Bead hierarchy
- PRD Contract document
- Initial task assignments