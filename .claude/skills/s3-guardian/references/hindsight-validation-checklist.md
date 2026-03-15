---
title: "Hindsight Validation Checklist (MANDATORY)"
status: active
type: reference
last_verified: 2026-03-09
grade: authoritative
---

# Hindsight Validation Checklist (MANDATORY)

**This checklist is non-negotiable.** Every guardian validation session MUST complete these Hindsight integration steps before closing.

## Phase 4 Completion: Storing Results

After scoring validation and determining verdict (ACCEPT, INVESTIGATE, or REJECT), execute both steps:

### Step 1: Store to Private Bank (Guardian Learnings)

```python
mcp__hindsight__retain(
    content=f"""## Guardian Validation: PRD-{prd_id}

### Decision
- Verdict: {verdict}  # ACCEPT|INVESTIGATE|REJECT
- Overall Score: {score:.2f}
- Date: {timestamp}
- Duration: {duration}

### Feature Breakdown
{feature_table}

### Gaps Identified
{gaps_list}

### Lessons Learned
- {lesson_1}
- {lesson_2}

""",
    context="s3-guardian-validations",
    bank_id="system3-orchestrator"
)
```

**When**: After Phase 4 validation scoring completes.
**Why**: Captures patterns for future guardian sessions to reference.
**Required fields**: `context="s3-guardian-validations"`, `bank_id="system3-orchestrator"` (always).

### Step 2: Store to Project Bank (Team Context)

```python
# Get project bank from environment (set by ccsystem3/ccorch)
import os
PROJECT_BANK = os.environ.get("CLAUDE_PROJECT_BANK", "default-project")

mcp__hindsight__retain(
    content=f"PRD-{prd_id}: {verdict} (score: {score:.2f}) | {gap_summary}",
    context="project-validations",
    bank_id=PROJECT_BANK
)
```

**When**: Immediately after Step 1.
**Why**: Other sessions in this project can quickly understand validation outcomes.
**Required fields**: `context="project-validations"`, `bank_id=PROJECT_BANK` (auto-derived).

## PRD Contract Generation and Validation (New in v0.6.0)

With the addition of PRD Contract artifacts, Phase 0 now includes Step 0.2.5 for contract generation and validation gates now check contract compliance.

### Step 0.2.5: PRD Contract Generation

During Phase 0, a `prd-contract.md` is automatically generated at `docs/prds/{initiative}/prd-contract.md`. This contract contains:
- Domain invariants that must hold regardless of implementation approach
- Scope freeze boundaries (what is in/out of scope)
- Compliance flags that mandate specific requirements

### Contract Validation in Gates

When a `wait.cobuilder` node has `contract_ref` attribute, the validation includes:
- Reading the PRD Contract specified by contract_ref
- Verifying each domain invariant holds in the current codebase
- Checking that no files outside the frozen scope were modified
- Verifying each compliance flag's condition is met
- Calculating contract compliance percentage (0.0-1.0) for the gate summary

## Completion Verification

Before marking promise AC as complete:

```bash
# Verify both Hindsight operations succeeded
echo "✓ Private bank (system3-orchestrator) retains guardian validation"
echo "✓ Project bank ($CLAUDE_PROJECT_BANK) retains project context"
echo "✓ Both mcp__hindsight__retain() calls executed without error"
echo "✓ PRD Contract generated and validated if required"

# Then meet the promise AC
cs-promise --meet <promise-id> --ac-id AC-5 \
    --evidence "ACCEPT verdict + Hindsight stored to both banks + Contract validated" \
    --type manual
```

## Common Mistakes to Avoid

| Mistake | Fix |
|---------|--------|
| Storing only to private bank (forget project bank) | Execute BOTH steps above |
| Using wrong `bank_id` value | Private = `"system3-orchestrator"`, Project = environment `$CLAUDE_PROJECT_BANK` |
| Forgetting `context=` parameter | Must include: `context="s3-guardian-validations"` for private, `context="project-validations"` for project |
| Storing BEFORE validation completes | Store ONLY after Phase 4 verdict determined |
| Storing results but not meeting promise AC | Meeting the AC is how System 3 knows validation is complete |
