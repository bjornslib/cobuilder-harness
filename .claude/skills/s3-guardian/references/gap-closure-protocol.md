---
title: "Gap Closure Protocol"
status: active
type: reference
last_verified: 2026-03-09
grade: authoritative
---

# Gap Closure Protocol

When Phase 4 validation identifies gaps in the implementation, System 3 must autonomously decide whether to close each gap or escalate it to the wait.human stage. This protocol formalizes that decision-making process and ensures gaps are addressed systematically.

## Core Principle

**Never report to wait.human with known closable gaps.** If a gap is in-scope, fixable, and doesn't require architectural or UX decisions, System 3 creates a codergen fix-it node and closes it autonomously. Only when all fixable gaps are closed does System 3 proceed to wait.human.

## Gap Analysis Decision Tree

```
Gap Identified During Phase 4 Validation
    ↓
Is gap in PRD scope? (Reference PRD Section 8 epics)
    ├─ NO → Escalate to wait.human (out-of-scope, document as informational)
    ├─ YES ↓
    │
    ├─ Is gap fixable without architectural/UX decisions?
    │   ├─ NO (requires design change, API rework, etc.) → Escalate to wait.human
    │   ├─ YES ↓
    │       │
    │       ├─ Is this a regression? (feature worked, now broken)
    │       │   ├─ YES → Create fix-it codergen (P0, highest priority)
    │       │   ├─ NO ↓
    │       │       │
    │       │       └─ Fixable & low-risk? (import, test mock, style, etc.)
    │       │           ├─ YES → Create fix-it codergen
    │       │           └─ NO → Escalate to wait.human with evidence
```

### Decision Node: "Is Gap in PRD Scope?"

Reference the PRD Section 8 (initiatives/epics) to determine if the gap aligns with declared requirements.

**In-scope examples:**
- Missing validation from acceptance criteria
- Feature partially implemented but rubric expects complete
- Test scenario that explicitly maps to PRD requirement

**Out-of-scope examples:**
- Code style/naming convention violations
- Performance optimization (not in PRD acceptance criteria)
- Enhancement beyond PRD requirements
- Documentation gap (not in scope of code validation)

### Decision Node: "Fixable Without Decisions?"

Distinguish between gaps that can be fixed deterministically vs those requiring human judgment.

**Fixable autonomously:**
- Missing imports (clear from error)
- Test setup (can infer from existing tests)
- UI styling (clear from design system or mockup)
- Mock configuration (clear from error message)
- Missing validation check (clear from acceptance criteria)

**Requires escalation:**
- "Should this API endpoint accept X?" (architectural)
- "What should the button color be?" (UX decision)
- "Should we add dependency Y?" (policy decision)
- "Is this behavior intentional?" (clarification needed)
- "Should we refactor X?" (trade-off decision)

### Decision Node: "Is This a Regression?"

Compare current failure against the ZeroRepo snapshot taken at Phase 0. If a feature worked before, now it's broken — that's a regression.

```bash
# Regression detection pattern
zero_repo_snapshot = ZeroRepo("acceptance-tests/PRD-{ID}/.zero")
if gap.feature in zero_repo_snapshot.working_features:
    gap_type = "REGRESSION"  # Feature worked, now broken
    priority = "P0"          # Critical priority
else:
    gap_type = "NEW"         # Feature never worked
    priority = determine_by_criticality(gap)
```

Regressions **always** get autonomous fix-it nodes — no escalation. This prevents reintroduction of bugs that were already solved.

---

## Autonomous Fix-It Node Creation

When System 3 decides to close a gap autonomously, execute this pattern:

### Step 1: Create the Fix-It Node in DOT

```dot
fix_gap_x1 [
    shape=box
    label="FIX: {gap_title}"
    handler="codergen"
    worker_type="backend-solutions-engineer|frontend-dev-expert|tdd-test-engineer"
    sd_path="docs/sds/fix-gap-x1.md"
    acceptance="Gap X1 closed per rubric: {rubric_scenario}. Re-validation passes."
    prd_ref="PRD-{ID}"
    epic_id="FIX-X1"
    bead_id="FIX-X1-IMPL"
    status="pending"
];
```

**Worker type selection:**
- `backend-solutions-engineer`: Imports, validation logic, API changes
- `frontend-dev-expert`: CSS, HTML structure, component styling
- `tdd-test-engineer`: Mock configuration, test setup, assertion fixes

### Step 2: Wire Fix-It Into Pipeline Before wait.human

```dot
e1_gate -> fix_gap_x1 [label="gaps_detected"];
fix_gap_x1 -> revalidate_gap_x1 [label="impl_complete"];

revalidate_gap_x1 [
    shape=hexagon
    label="Re-validate Gap X1"
    handler="wait.system3"
    gate_type="gap-closure"
    status="pending"
];

revalidate_gap_x1 -> e1_review [label="validated"];
```

**Important**: Fix-it nodes are dispatched BEFORE the wait.human gate, so all closable gaps are resolved before user consultation.

### Step 3: Create Minimal Solution Design

```markdown
# SD-NEWCHECK-001-FIX-X1.md

## Gap Statement
From Phase 4 validation, Gherkin scenario F2-S3 fails because: {exact_error}

## Root Cause
{brief analysis}

## Solution
{focused fix, 2-3 lines max}

## Verification
Re-run scenario F2-S3, assert passes.

## Constraints
None — this is a pure bug fix, no trade-offs.
```

**Keep it minimal**: This SD is NOT a full feature design — it's a targeted fix. 3-4 paragraphs max.

### Step 4: Create Corresponding Bead

```bash
bd create \
    --title="FIX-X1: Close gap from PRD-{ID} validation" \
    --type=task \
    --priority=1 \
    --description="Gap identified during Phase 4 validation: {gap_description}. Closes scenario {rubric_scenario}."
```

**Get the bead ID:**
```bash
BEAD_ID=$(bd list --title="FIX-X1" --json | jq -r '.[0].id')
```

**Update DOT node:**
```bash
python3 .claude/scripts/attractor/cli.py node-modify \
    --dot-file .pipelines/pipelines/PRD-{ID}.dot \
    --node-id fix_gap_x1 \
    --set bead_id="$BEAD_ID"
```

### Step 5: Dispatch Fix-It Node

```bash
python3 .claude/scripts/attractor/runner.py --spawn \
    --node fix_gap_x1 \
    --prd PRD-{ID} \
    --dot-file .pipelines/pipelines/PRD-{ID}.dot
```

Worker receives:
- Minimal SD (fix-gap-x1.md)
- Acceptance criteria (re-run scenario, assert pass)
- Clear mandate: close this gap, nothing more

### Step 6: Re-Validate After Fix

After fix-it codergen completes:

```bash
# Run the exact Gherkin scenario that failed
behave acceptance-tests/PRD-{ID}/{scenario}.feature:S3

# If passes:
python3 .claude/scripts/attractor/cli.py node-modify \
    --dot-file .pipelines/pipelines/PRD-{ID}.dot \
    --node-id revalidate_gap_x1 \
    --set status=validated

bd update $BEAD_ID --status=done

# If still fails:
# Update SD with new evidence
# Re-dispatch fix-it with corrected guidance
```

---

## Cascade Handling: Multiple Related Gaps

When closing one gap exposes another:

### Example Scenario

- Gap 1: Missing import A → Create fix-it-1
- Gap 1 closes → Re-validate → Gap 2: Missing import B → Create fix-it-2
- Gap 2 closes → Re-validate → Gap 3: Same import, different usage → Create fix-it-3
- Gap 3 closes → All gaps closed, proceed to wait.human

### Cascade Depth Tracking

Track iteration count to prevent infinite loops:

```python
cascade_depth = 0
max_cascade_iterations = 3  # Threshold

for gap in gaps_found:
    cascade_depth += 1

    if cascade_depth > max_cascade_iterations:
        print(f"Cascade depth exceeded. Escalating remaining {len(remaining_gaps)} gaps to wait.human")
        escalate_to_wait_human(remaining_gaps)
        break

    if is_autonomous_fixable(gap):
        create_fix_it_node(gap)
        dispatch(gap)
        re_validate()
    else:
        escalate_to_wait_human(gap)
```

### When to Escalate Instead

If cascade depth reaches 3 iterations, escalate remaining gaps with summary:
```
"Cascade detected: 3 iterations of fix-it nodes revealed additional gaps.
Escalating to wait.human for user decision on approach."
```

This prevents runaway fix-it loops while allowing legitimate multi-step fixes.

---

## Escalation Rules: When NOT to Create Codergen

Do NOT create a fix-it node if any of these apply:

### 1. Gap Requires Architectural Redesign

**Example**: "API contract needs to return different field structure"

**Escalation summary**: "Gap requires changing API schema. This is an architectural decision."

### 2. Gap Requires UX/Design Decision

**Example**: "Button should be different color / form layout should change"

**Escalation summary**: "Gap requires design decision. Requires user/designer input."

### 3. Gap is Outside PRD Scope

**Example**: "Code doesn't follow company style guide"

**Escalation summary**: "Gap is out of scope for PRD-XXX. Noted as informational, not blocking."

### 4. Gap Requires User Clarification

**Example**: "Is feature X supposed to work with legacy API Y?"

**Escalation summary**: "Gap requires clarification on requirement ambiguity."

### 5. Closing Gap Would Introduce Risk

**Example**: "Fixing this requires removing dependency X, but other code depends on it"

**Escalation summary**: "Fix would introduce cascading changes. Escalating for impact assessment."

### 6. Iteration Limit Exceeded

**Example**: 3 cascading fix-it nodes and gaps still appearing

**Escalation summary**: "Cascade depth exceeded. Escalating for user decision on approach."

---

## Escalation Format for wait.human

When escalating a gap, structure the summary card as:

```markdown
### Gap: {gap_title}

**Scenario**: {rubric_scenario}

**Evidence**:
- Error: {exact_error_or_assertion}
- Root cause: {analysis}

**Why not autonomous**: {reason from above list}

**Recommended action**: {escalation reason + suggested next step}
```

Example:
```markdown
### Gap: Dashboard should refresh on data change

**Scenario**: F3-S2: User updates record, dashboard reflects change within 2s

**Evidence**:
- Dashboard shows stale data after 5s
- Checked React component, no useEffect for data polling
- API responds correctly

**Why not autonomous**: Requires architectural decision on polling vs WebSocket vs SSE

**Recommended action**: User should decide: lightweight polling (quick fix) or real-time architecture (better design)?
```

---

## Common Fix-It Patterns by Gap Type

### Pattern 1: Missing Import

**Gap**: Import error in logs

**Fix-it SD**:
```markdown
## Missing Import

Import `B` from module `X` at line N in file `A.py`.
```

**Worker**: `backend-solutions-engineer`
**Acceptance**: "Import resolves, test passes"
**Typical duration**: <2 minutes

### Pattern 2: Test Mock Setup

**Gap**: Test fails because mock not configured

**Fix-it SD**:
```markdown
## Mock Configuration

Configure mock for `APIClient.get_data()` to return `{...}` structure.
Reference existing mocks in file Y for pattern.
```

**Worker**: `tdd-test-engineer`
**Acceptance**: "Test assertion passes with correct mock data"
**Typical duration**: <5 minutes

### Pattern 3: UI Styling

**Gap**: Element has wrong CSS class or inline style

**Fix-it SD**:
```markdown
## CSS Class Update

Apply `button-primary` class to button element at line M in component X.
Reference design system in docs/design/colors.md for approved classes.
```

**Worker**: `frontend-dev-expert`
**Acceptance**: "Element matches expected style from mockup"
**Typical duration**: <3 minutes

### Pattern 4: Validation Logic

**Gap**: Validation check missing from acceptance criteria

**Fix-it SD**:
```markdown
## Add Validation

Add check: email field must match regex `[^@]+@[^@]+\.[^@]+`.
Place check in `validate_form()` function before submission.
Emit error message: "Invalid email format" on failure.
```

**Worker**: `backend-solutions-engineer`
**Acceptance**: "Gherkin scenario F1-S4 assertion passes"
**Typical duration**: <5 minutes

### Pattern 5: Regression (Feature That Broke)

**Gap**: Feature that was working is now broken

**Fix-it SD** (with urgency):
```markdown
## Regression Fix (P0)

Feature: User logout
Broken by: Unknown (regression detected in Phase 4)
Current behavior: Session persists after logout button clicked
Expected: Session cleared, user redirected to login

Root cause: [investigation needed by worker]
Fix: [worker to diagnose and correct]
```

**Worker**: Appropriate specialist based on component (backend/frontend)
**Acceptance**: "Gherkin scenario returns to passing state"
**Typical duration**: <15 minutes (may need investigation)

---

## Verifying Gap Closure

After re-validation passes, verify the gap is truly closed:

```python
# 1. Run the exact failing Gherkin scenario
result = run_gherkin_scenario(scenario_name)
assert result.status == "PASSED"

# 2. Check confidence score improved
old_score = validation_scores[gap.feature]
new_score = re_validate()[gap.feature]
assert new_score > old_score

# 3. Verify no regressions (ZeroRepo check)
zero_repo = ZeroRepo("acceptance-tests/PRD-{ID}/.zero")
for feature in zero_repo.working_features:
    result = run_gherkin_scenario(feature)
    assert result.status == "PASSED"  # Ensure fix didn't break others

# 4. Mark gap as closed in beads
bd update bead_id --status=done
```

---

## Timeline and Expectations

**Small gaps** (single root cause, <5min fix):
- Create fix-it node: <1 minute
- Dispatch: <30 seconds
- Worker completes: <5 minutes
- Re-validate: <2 minutes
- **Total**: ~10 minutes

**Medium gaps** (multi-file, <15min fix):
- Create fix-it node + minimal SD: <3 minutes
- Dispatch: <1 minute
- Worker completes: <15 minutes
- Re-validate: <3 minutes
- **Total**: ~25 minutes

**Complex gaps or cascades**:
- After 3 iterations or >30 minutes: escalate to wait.human with evidence
- User decides: fix now, defer, or replan approach

---

## Anti-Patterns

| Anti-Pattern | Problem | Fix |
|--------------|---------|-----|
| Escalating a clearly fixable gap | Interrupts user unnecessarily | Analyze decision tree, create fix-it |
| Creating fix-it for out-of-scope gap | Scope creep, confuses priorities | Check PRD Section 8, escalate instead |
| Skipping re-validation after fix | Gap may still exist, false confidence | Always re-run Gherkin scenario |
| Creating one mega fix-it for 5 gaps | Combines unrelated work, harder to debug | Create separate fix-it per root cause |
| Ignoring cascading gaps (depth > 3) | Infinite loop risk, time waste | Track depth counter, escalate at threshold |
| Using architectural SD for trivial fix | Bloats context, confuses workers | Keep fix-it SDs to 3-4 paragraphs max |
| Forgetting to create bead for fix-it | Pipeline loses visibility, unsyncable | Always `bd create` before DOT node-add |
| Reporting gap at wait.human when fixable | User sees incomplete solution | Close autonomously first, then wait.human |

---

## Integration with Phase 4

This protocol is invoked **during Phase 4** validation, specifically as Phase 4.5 (Autonomous Gap Closure).

**Placement in workflow:**
```
Phase 4: Validate Against Rubric
    ↓
    ├─ Score each feature/scenario
    ├─ Identify gaps
    ↓
Phase 4.5: Autonomous Gap Closure (THIS PROTOCOL)
    ├─ Analyze each gap
    ├─ Decide: fix autonomously or escalate?
    ├─ Create + dispatch fix-it nodes
    ├─ Re-validate after fixes
    ↓
Wait.Human Gate (Only after all fixable gaps closed)
    └─ User reviews final solution
```

Only when all autonomous gaps are closed does System 3 transition the pipeline to wait.human, ensuring the user sees a complete, validated solution.
