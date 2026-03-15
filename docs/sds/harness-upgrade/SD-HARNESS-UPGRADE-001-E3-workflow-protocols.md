---
title: "SD-HARNESS-UPGRADE-001 Epic 3: Workflow Protocol Enhancements"
status: archived
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001 Epic 3: Workflow Protocol Enhancements

## 1. Problem Statement

Multiple workflow gaps have been identified through production use:
- SDs are edited in-place during research/refine, creating version pollution for downstream workers
- No confidence trend tracking across sessions
- No structured mechanism for workers to raise concerns back to System 3
- No guardian reflection at validation gates — validation runs blind without reviewing worker signals
- Session boundaries lose context (no handoff document)
- No narrative record of initiative progress across epics

## 2. Design

### 2.1 SD Version Pinning

**Protocol**:
1. After refine node completes, git-tag the SD:
   ```bash
   git tag sd/{prd-id}/E{n}/v{version} -- docs/sds/{initiative}/SD-{id}.md
   ```
2. Codergen node's `sd_ref` attribute points to the tag (not the file path):
   ```dot
   impl_e1 [handler="codergen" sd_ref="sd/HARNESS-UPGRADE-001/E1/v1"]
   ```
3. `dispatch_worker.py` resolves the tag to file content at dispatch time:
   ```bash
   git show sd/HARNESS-UPGRADE-001/E1/v1:docs/sds/harness-upgrade/SD-...-E1-node-semantics.md
   ```
4. Signal evidence includes `sd_hash` (SHA256 of the resolved content)

**Naming convention**: `sd/{prd-id}/E{epic}/v{version}` (e.g., `sd/HARNESS-UPGRADE-001/E1/v1`)

### 2.2 Confidence Baseline

**After every `wait.cobuilder` gate**:
```python
mcp__hindsight__retain(
    content=f"Confidence: {epic_id} scored {score:.2f}. "
            f"Gate: {gate_type}. Contract: {contract_score:.2f}. "
            f"Concerns: {len(concerns)} resolved, {len(unresolved)} pending.",
    context=f"confidence-{prd_id}"
)
```

**At session startup** (added to output style Step 2):
```python
trend = mcp__hindsight__reflect(
    query=f"What is the confidence trend for {prd_id}? "
          f"Are scores improving? Any recurring failure patterns?",
    budget="mid",
    bank_id=PROJECT_BANK
)
```

### 2.3 Skill-First Dispatch Table

Added to `guardian-workflow.md` Phase 2 section. Includes skill injection into worker prompts:

| Node Intent | Skill to Invoke | Injected via |
|-------------|----------------|-------------|
| Codergen (frontend) | `react-best-practices`, `frontend-design` | `skills_required` in agent definition |
| Codergen (backend) | `dspy-development` (if applicable) | `skills_required` in agent definition |
| Research (framework validation) | `research-first` | Runner injects into research worker prompt |
| Validation (E2E gate) | `acceptance-test-runner` | Runner calls directly |
| UX review | `website-ux-audit` | `skills_required` in ux-designer agent |
| Acceptance test creation | `acceptance-test-writer` | Runner injects into AT writer worker prompt |

### 2.4 Guardian Reflection at wait.cobuilder Gates

**Replaces the previous sketch pre-flight concept.** Instead of a separate Haiku call before dispatch, the guardian/runner reflects at the `wait.cobuilder` gate AFTER workers complete:

**Protocol** (executed by `_handle_gate()` in the runner):
1. Read all signal files from completed codergen workers in this epic cluster
2. Read `concerns.jsonl` for worker-raised concerns
3. Reflect via Hindsight: query confidence trend, previous gate results, and concern patterns
4. If critical concerns exist or confidence is declining:
   - Write summary explaining the issue
   - Transition `wait.cobuilder` to `failed`
   - Optionally: transition predecessor codergen node back to `pending` for retry (DOT graph update)
5. If no blockers: proceed with Gherkin E2E test execution
6. After E2E tests: write full summary to `summary_ref`

**Requeue mechanism**: When the runner decides a codergen node needs to rerun:
```python
# In _handle_gate() when gate fails and retry is warranted
transition_node(pipeline, predecessor_codergen_id, "pending")
save_checkpoint(dot_file, pipeline)
# Runner's next dispatch cycle will pick up the re-queued node
```

This keeps the retry logic inside the pipeline state machine — no external process needed.

### 2.5 Session Handoff Document

Written at end of every System 3 turn to `.claude/progress/{session-id}-handoff.md`:

```markdown
# Session Handoff: {session-id}

## Last Action
{what was just completed}

## Pipeline State
{cobuilder pipeline status output}

## Next Dispatchable Nodes
{list of pending nodes with deps met}

## Open Concerns
{unresolved items from concerns.jsonl}

## Confidence Trend
{latest scores from Hindsight}
```

Read first on session startup (before Hindsight queries).

### 2.6 Living Narrative

After each epic completion, System 3 appends to `.claude/narrative/{initiative}.md`:

```markdown
## Epic {N}: {title} — {date}

**Outcome**: {PASS/FAIL} (score: {x.xx})
**Key decisions**: {list}
**Surprises**: {unexpected findings}
**Concerns resolved**: {count}
**Time**: {duration}
```

### 2.7 Concern Queue

Workers write concerns during execution to `{signal_dir}/concerns.jsonl`:

```json
{"ts": "2026-03-06T10:15:00Z", "node": "impl_e1", "severity": "warning", "message": "SD references v1.x API but installed version is v2.0", "suggestion": "Pin dependency or update SD"}
```

`wait.cobuilder` gate reads and processes:
- **Critical**: blocks gate, transitions to `failed`, includes in summary
- **Warning**: includes in summary for human review
- **Info**: logged to Hindsight only

### 2.8 Signal Directory Mitigation

Document `ATTRACTOR_SIGNAL_DIR` env var as mandatory preflight check:

```bash
# In dispatch_worker.py
export ATTRACTOR_SIGNAL_DIR="${pipeline_dir}/signals/"
```

Workers write signals to this directory. Runner polls this directory. Mismatch was a documented failure mode.

## 3. Files Changed

| File | Change |
|------|--------|
| `guardian-workflow.md` | SD pinning protocol, skill-first dispatch table, concern queue processing, guardian reflection at gates, signal dir docs |
| `phase0-prd-design.md` | SD tagging step after refine nodes |
| `output-styles/cobuilder-guardian.md` | Confidence baseline query in Step 2, session handoff write/read, living narrative append |

## 4. Testing

- Manual: create a git tag for an existing SD, resolve it with `git show`, verify content
- Manual: write sample concerns.jsonl, verify gate processing logic
- Manual: verify session handoff file is written and read correctly

## 5. Acceptance Criteria

- AC-3.1: SD version pinning protocol documented with git tag naming convention (`sd/{prd-id}/E{n}/v{version}`)
- AC-3.2: Concern queue JSONL schema documented with severity levels and processing rules
- AC-3.3: Guardian reflection protocol at wait.cobuilder documented (signal file check + Hindsight reflect + requeue decision)
- AC-3.4: Session handoff format documented with required sections
- AC-3.5: Living narrative append protocol documented with per-epic entry format

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
