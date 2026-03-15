---
title: "Validation Scoring"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Validation Scoring Methodology

Detailed methodology for independently scoring implementation work against blind acceptance tests using gradient confidence scoring (0.0-1.0).

---

## 1. Weighted Scoring Formula

The overall validation score is computed as a weighted average across all features:

```
Overall Score = SUM( feature_weight[i] * feature_score[i] )  for i in all features
```

Where:

```
feature_score[i] = AVERAGE( scenario_score[j] )  for j in scenarios of feature i
```

### Worked Example

```
Feature 1 (weight 0.30): 2 scenarios scored 0.8 and 0.7 → feature_score = 0.75
Feature 2 (weight 0.25): 1 scenario scored 0.6 → feature_score = 0.60
Feature 3 (weight 0.20): 2 scenarios scored 0.9 and 0.8 → feature_score = 0.85
Feature 4 (weight 0.15): 1 scenario scored 0.5 → feature_score = 0.50
Feature 5 (weight 0.10): 1 scenario scored 0.7 → feature_score = 0.70

Overall = (0.30 * 0.75) + (0.25 * 0.60) + (0.20 * 0.85) + (0.15 * 0.50) + (0.10 * 0.70)
        = 0.225 + 0.150 + 0.170 + 0.075 + 0.070
        = 0.690

Decision: 0.690 >= 0.60 ACCEPT threshold → ACCEPT
```

---

## 2. Decision Thresholds

### Standard Thresholds

| Range | Decision | Meaning |
|-------|----------|---------|
| >= 0.60 | ACCEPT | Implementation meets business requirements. Proceed to merge. |
| 0.40 - 0.59 | INVESTIGATE | Partial implementation. Gaps must be identified and addressed. |
| < 0.40 | REJECT | Implementation fundamentally incomplete. Restart cycle. |

### Customizing Thresholds

Thresholds are configurable per initiative in `manifest.yaml`. Adjust based on:

| Factor | Lower Thresholds | Higher Thresholds |
|--------|-----------------|-------------------|
| Initiative criticality | Prototype, exploration | Production, customer-facing |
| Time pressure | Tight deadline, MVP | No deadline pressure |
| Iteration plan | Will have follow-up sessions | This is the final session |
| Scope complexity | Small, well-defined PRD | Large, ambiguous PRD |

**Example**: A prototype pipeline might use `accept: 0.50` while a production auth system might use `accept: 0.75`.

### Threshold Configuration in Manifest

```yaml
thresholds:
  accept: 0.60      # Score >= this → ACCEPT
  investigate: 0.40  # Score >= this but < accept → INVESTIGATE
  reject: 0.40      # Score < this → REJECT (always equals investigate threshold)
```

The `reject` threshold always equals `investigate` to ensure no scoring gap exists.

---

## 3. Mapping Code Evidence to Confidence Scores

The core of independent validation is reading actual code and mapping observations to the scenario's scoring guide.

### Evidence Gathering Workflow

For each scenario in the acceptance test suite:

**Step 1: Identify what to check**

Read the scenario's "Evidence to Check" section. Translate each item into a concrete action:

```
Evidence item: "src/pipeline.py for @flow decorator"
Action: cat /path/to/impl-repo/src/pipeline.py | grep "@flow"

Evidence item: "Tests that verify retry behavior"
Action: grep -r "retry\|retries" /path/to/impl-repo/tests/

Evidence item: "Configuration loaded from external source"
Action: grep -r "os.getenv\|BaseSettings\|load_config" /path/to/impl-repo/src/
```

**Step 2: Execute evidence gathering**

```bash
# Git diff for the implementation period
git -C /path/to/impl-repo log --oneline --since="4 hours ago"
git -C /path/to/impl-repo diff HEAD~20..HEAD --stat

# Specific file examination
cat /path/to/impl-repo/src/{file}

# Function body examination
grep -A 30 "def {function_name}" /path/to/impl-repo/src/{file}

# Import verification (is the module actually used?)
grep -r "from {module} import\|import {module}" /path/to/impl-repo/src/

# Test examination
cat /path/to/impl-repo/tests/test_{module}.py

# Test execution (if available and safe)
cd /path/to/impl-repo && python -m pytest tests/test_{module}.py -v --tb=short 2>&1
```

**Step 3: Map observations to scoring guide**

Read the scenario's "Confidence Scoring Guide" and find the closest match:

```
Observation: pipeline.py exists, has @flow decorator on main(),
             orchestrates 4 @task functions, parameters are typed,
             but no docstring on the flow function.

Scoring guide reference:
  0.8 — @flow orchestrates 3+ tasks with proper parameter passing
  1.0 — @flow is well-structured, typed parameters, docstring, 3+ tasks with dependencies

Score: 0.85 (between 0.8 and 1.0 — typed parameters push above 0.8, missing docstring prevents 1.0)
```

**Step 4: Check for red flags**

Read the scenario's "Red Flags" section. For each red flag, check whether it applies:

```
Red flag: "@flow decorator on an empty function"
Check: cat /path/to/impl-repo/src/pipeline.py | grep -A 5 "@flow"
Result: Function body has 40+ lines of real logic → Red flag NOT triggered

Red flag: "Tasks defined but never called from the flow"
Check: grep "@task" src/pipeline.py, then check if task names appear in the flow body
Result: All 4 tasks are called within the flow → Red flag NOT triggered
```

If a red flag IS triggered, apply the severity penalty from the gherkin-test-patterns reference:
- Minor red flag: -0.05 to -0.10
- Moderate red flag: -0.10 to -0.20
- Major red flag: -0.20 to -0.40
- Critical red flag: cap score at 0.3

---

## 4. Cross-Referencing Claims vs Actual Git Diff

Operators may claim completion of features that are only partially implemented. Cross-referencing is essential.

### Claim Sources

| Source | Reliability | Use For |
|--------|------------|---------|
| Git diff (actual code changes) | High | Ground truth of what was modified |
| Git commit messages | Medium | Intent, but may be optimistic |
| Orchestrator progress log | Low | Self-reported, often inflated |
| Worker completion messages | Low | Worker scope may not match feature scope |
| Test results (if run independently) | High | Objective pass/fail |
| `cs-promise --meet` evidence | Medium | Claimed evidence, verify independently |

### Cross-Reference Protocol

1. **Read the git diff**: What files actually changed? What was added vs modified?

```bash
# Summary of all changes
git -C /path/to/impl-repo diff HEAD~N..HEAD --stat

# Detailed changes in specific files
git -C /path/to/impl-repo diff HEAD~N..HEAD -- src/pipeline.py

# Show each commit individually
git -C /path/to/impl-repo log --oneline HEAD~N..HEAD
```

2. **Compare claims to reality**:

```
Claim: "Implemented retry logic with exponential backoff"
Git diff: Added `retries=3` to @task decorator, no custom retry handler
Reality: Basic retry, NOT exponential backoff
Score adjustment: Reduce from claimed 0.8 to actual 0.5
```

3. **Look for phantom features**: Features mentioned in commit messages or logs that do not appear in the actual diff.

```bash
# Check commit messages for feature claims
git -C /path/to/impl-repo log --oneline HEAD~N..HEAD | grep -iE "implement|add|feature"

# Cross-reference: do the claimed files actually exist and contain real code?
for file in $(git -C /path/to/impl-repo diff HEAD~N..HEAD --name-only); do
    wc -l /path/to/impl-repo/$file
done
```

---

## 5. What Constitutes "Independent" Validation

The guardian pattern's value comes from independence. Validation is only independent if:

### Independent Means

- Reading source code files directly (not orchestrator summaries)
- Running tests independently (not trusting "all tests pass" claims)
- Checking git diff for actual changes (not commit message descriptions)
- Evaluating against a rubric the operator never saw (blind testing)
- Scoring based on evidence, not on effort or time spent

### Independent Does NOT Mean

- Asking the operator if the feature is done
- Reading the operator's progress log and taking it at face value
- Trusting `cs-promise --meet` evidence without verifying the evidence itself
- Counting commit messages as proof of implementation
- Assuming tests pass because the operator said they do

### The Independence Test

Before recording a score, ask: "Could I arrive at this score WITHOUT any information from the operator?" If the answer is no, the validation is not independent. Gather more direct evidence.

---

## 6. Scoring Worksheet Template

Use this template for each validation session:

```markdown
# Validation Worksheet: PRD-{ID}

## Session Metadata
- Guardian session started: {timestamp}
- Operator session: s3-{initiative}
- Implementation repo: {path}
- Monitoring duration: {hours}
- Interventions performed: {count}

## Feature Scoring

### Feature: {F1 Name} (weight: {0.XX})

**Scenario: {scenario_name}**
- Evidence gathered:
  - {file}: {what was observed}
  - {test}: {results}
- Red flags:
  - {flag}: {triggered/not triggered}
- Score: {0.X}
- Rationale: {why this score}

**Feature Score**: {average of scenario scores}
**Weighted Contribution**: {feature_score * weight}

### Feature: {F2 Name} (weight: {0.XX})
...

## Summary

| Feature | Weight | Score | Weighted |
|---------|--------|-------|----------|
| F1 | {w} | {s} | {w*s} |
| F2 | {w} | {s} | {w*s} |
| ... | ... | ... | ... |
| **Total** | **1.00** | - | **{sum}** |

## Decision

- Overall Score: {X.XX}
- ACCEPT threshold: {from manifest}
- **Decision: {ACCEPT | INVESTIGATE | REJECT}**

## Gaps Identified
1. {gap}
2. {gap}

## Red Flags Triggered
1. {flag} — severity: {minor/moderate/major/critical} — impact: -{0.XX}

## Recommendations
- {next steps}
```

---

## 7. Storing Validation Results

After completing the scoring worksheet, store results in two locations.

### Hindsight — Private Bank (Guardian Learnings)

```python
mcp__hindsight__retain(
    content=f"""
    ## Guardian Validation: PRD-{prd_id}

    ### Result
    - Decision: {verdict}
    - Overall Score: {score}
    - Date: {timestamp}
    - Duration: {monitoring_duration}

    ### Feature Breakdown
    {feature_score_table}

    ### Key Gaps
    {gaps_list}

    ### Red Flags Triggered
    {red_flags_list}

    ### Lessons for Future Guardians
    - {lesson_1}
    - {lesson_2}

    ### Scoring Calibration Notes
    - {any adjustments to scoring guides for future use}
    """,
    context="s3-guardian-validations",
    bank_id="system3-orchestrator"
)
```

### Hindsight — Project Bank (Team Awareness)

```python
mcp__hindsight__retain(
    content=f"""
    PRD-{prd_id} Guardian Validation: {verdict} (score: {score})

    Features validated: {feature_count}
    Gaps found: {gap_count}
    Recommendations: {summary}
    """,
    context="project-validations",
    bank_id="claude-code-{project}"
)
```

### When to Store

- **ACCEPT**: Store immediately. Include positive patterns for future reference.
- **INVESTIGATE**: Store gaps and the investigation plan. Update after gaps are addressed.
- **REJECT**: Store failure analysis. Include anti-patterns to avoid.

---

## 8. Handling Edge Cases

### Feature Not Attempted

If a feature shows zero evidence of implementation (score 0.0), it receives its full weight as a penalty. A PRD with one critical feature (weight 0.30) completely missing will score at most 0.70.

### Feature Over-Implemented

If a feature exceeds PRD requirements, score it at 1.0 (the maximum). Do not award bonus points. The purpose of validation is to verify PRD compliance, not to reward over-engineering.

### Ambiguous Evidence

If evidence is unclear — the implementation exists but its correctness is uncertain without running it:

1. Default to the lower score in the ambiguous range
2. Note the ambiguity in the rationale
3. If the ambiguity affects the overall decision (score is near a threshold), attempt to resolve it by running the code or tests

### Operator Claims Not In PRD

If the operator implemented features not in the PRD, ignore them for scoring purposes. They do not increase or decrease the score. Note them in the validation report as "out of scope additions" for the oversight team's awareness.

### Tests Exist But Fail

If tests exist but fail when run independently:

- The test file existing is evidence of intent (worth 0.1-0.2)
- Failing tests indicate incomplete implementation (cap at 0.4 for the scenario)
- The failure reason matters: import error (0.2), assertion error (0.3), timeout (0.3)

### No Test Suite Available

If the implementation has no tests:

- This is NOT automatic failure — the scoring guide for each scenario defines what constitutes each score level
- Absence of tests typically limits a scenario to 0.5-0.6 maximum (functional but unverified)
- Exception: if the scoring guide explicitly requires tests for scores above 0.5, honor that

---

## 9. Calibration Over Time

Scoring calibration improves with experience. After each validation session:

1. **Review scoring decisions**: Were any scores surprisingly high or low in retrospect?
2. **Compare with operator claims**: Where did the guardian and operator most disagree?
3. **Adjust scoring guides**: If a scoring level description was misleading, update it for future use
4. **Update thresholds**: If the standard thresholds consistently produce wrong decisions, adjust per-domain

### Calibration Signals

| Signal | Meaning | Action |
|--------|---------|--------|
| ACCEPT but implementation has obvious bugs | Thresholds too low or scoring too generous | Raise ACCEPT threshold or recalibrate scoring guides |
| REJECT but implementation is actually solid | Scoring too strict or evidence gathering incomplete | Lower thresholds or expand evidence sources |
| INVESTIGATE frequently with no resolution | Threshold range too wide | Narrow the investigate band |
| All features score 0.7-0.8 | Scoring guides may be too coarse | Add more granularity to the 0.6-1.0 range |

Store calibration notes in Hindsight for future guardian sessions to reference.

---

## 10. Validation Method Enforcement

Features in the manifest may specify a `validation_method` field that dictates which tools the scoring agent MUST use. This prevents agents from taking the path of least resistance (static code analysis) for features that require live interaction.

### Method-Specific Minimum Evidence

| `validation_method` | Minimum Evidence Required | Score Cap Without Evidence |
|---------------------|--------------------------|---------------------------|
| `browser-required` | At least 2 of: screenshot artifact, navigate call, tabs_context usage, read_page output, Chrome interaction log | 0.0 (automatic override) |
| `api-required` | At least 2 of: curl/httpx command, HTTP status code, response body JSON, actual endpoint URL called | 0.0 (automatic override) |
| `code-analysis` | Standard code reading evidence (file contents, grep results, import traces) | No cap (current behavior) |
| `hybrid` (default) | No specific requirement — agent discretion | No cap (current behavior) |

### How This Works in Practice

**Phase 4 (Scoring Agent Dispatch)**:
1. Guardian reads `validation_method` from manifest for each feature
2. Guardian prepends mandatory tool instructions to the scoring agent prompt (see SKILL.md Step 5a)
3. Scoring agent executes with the prepended instructions

**Post-Scoring (Evidence Gate)**:
1. Guardian scans scoring agent output for method-appropriate keywords
2. If `browser-required` or `api-required` evidence is missing → score overridden to 0.0
3. Override reason logged in validation worksheet

### Evidence Gate Keyword Reference

**`browser-required` — must find at least 2:**
- `screenshot` — proves visual capture
- `navigate` — proves page navigation
- `tabs_context` — proves Chrome tab awareness
- `read_page` — proves DOM reading
- `Chrome` — proves browser tool usage
- `localhost:3000` — proves frontend interaction

**`api-required` — must find at least 2:**
- `curl` — proves HTTP request tool
- `HTTP 200` / `HTTP 201` / `HTTP 202` — proves actual response received
- `response body` — proves response examination
- `localhost:8000` — proves API server interaction
- Actual JSON (e.g., `{"id":`, `"status":`) — proves real response data

### Why This Matters

Without validation method enforcement, scoring agents consistently default to static code analysis because it's faster and easier. A frontend UI feature can score 0.8 based purely on reading React source files — without ever rendering the page in a browser. This fundamentally undermines the guardian pattern's purpose of independent, reality-based validation.

The evidence gate is the last line of defense: even if the prompt instruction is ignored, the score is corrected post-hoc.

---

## 11. Phase 4.5: Autonomous Gap Closure

After Phase 4 validation produces a confidence score and identifies gaps, System 3 must attempt autonomous closure of **closable** gaps before escalating any work to the wait.human stage. This phase is the critical link between validation findings and user escalation.

### Gap Classification Decision Tree

Every gap identified during Phase 4 scoring must be classified as **closable** or **not closable**:

| Classification | Definition | Action |
|---|---|---|
| **Closable** | Gap is in-scope (PRD Section 8), fixable without architectural/UX decisions, and low-risk | Create fix-it codergen node, re-dispatch pipeline |
| **Not Closable** | Gap requires user decision, is out-of-scope, or poses high risk | Escalate to wait.human with evidence |

**Reference**: See [gap-decision-tree.md](gap-decision-tree.md) for detailed visual flowchart and decision logic.

### Closable Gap Types

The following gap types are safe for autonomous closure:

**Low-Risk Gaps** (always safe):
- Missing import statement (clear from error message)
- Test assertion missing (clear from acceptance criteria)
- Mock configuration incomplete (clear from test error)
- UI styling missing (clear from screenshot or design system)
- Simple validation missing (clear from acceptance criteria)
- Error handling missing (clear from exception type)
- Type annotation missing (clear from type check output)

**Medium-Risk Gaps** (usually safe with constraints):
- Bug fix for obvious logic error (off-by-one, negation reversal, etc.)
- Test setup boilerplate (inferred from existing test patterns)
- Documentation string (inferred from code context)

**Always Closable — Regressions**:
- Any gap where the feature **worked at Phase 0** but is now broken
- Regressions get P0 priority and are closed even if complex
- Prevents reintroduction of previously-fixed bugs

### Not-Closable Gap Types

The following gaps require wait.human escalation:

**Architectural Decisions**:
- "Should this API endpoint accept parameter X?"
- "What should the database schema be?"
- "Should we add this dependency?"
- "What's the correct design pattern for this?"

**UX/Design Decisions**:
- "What color should this button be?"
- "Should this field be required or optional?"
- "What's the correct error message format?"
- "How should the form layout be organized?"

**Scope/Clarification**:
- "Is this feature in scope or out?"
- "Is this behavior intentional or a bug?"
- "Should we support this use case?"

**High-Risk Fixes**:
- Changes affecting >5 files
- Logic changes >10 lines
- Changes to API contracts or database schemas
- Breaking changes to other features

### Mandatory Workflow for Autonomous Closure

When gaps are identified, execute this 7-step workflow:

#### Step 1: Analyze Gap List from Phase 4

Review all gaps identified during validation scoring. For each gap, record:
- Gap ID (e.g., G1, G2)
- Description (what's missing or wrong)
- Acceptance criterion it violates
- Current implementation state

#### Step 2: Classify Each Gap

Use the decision tree in [gap-decision-tree.md](gap-decision-tree.md) to classify each gap:

```python
for gap in phase_4_gaps:
    gap.closable = is_in_prd_scope(gap) \
                   and is_fixable_without_decisions(gap) \
                   and (is_regression(gap) or is_low_risk(gap))
```

**Closable Gaps** → Proceed to Step 3
**Not-Closable Gaps** → Collect for Step 7 escalation

#### Step 3: Create Fix-It Nodes for Closable Gaps

For each closable gap, create a DOT node in the pipeline:

```dot
fix_gap_1 [
    shape=box
    label="FIX: Missing import in UserService"
    handler="codergen"
    worker_type="backend-solutions-engineer"
    sd_path="docs/sds/example/SD-EXAMPLE-FIX-G1.md"
    acceptance="Import added, test passes, no regressions"
    prd_ref="PRD-EXAMPLE-001"
    epic_id="FIX-G1"
    bead_id="FIX-G1"
    priority="P0"
    status="pending"
];
```

**Node attributes explained**:
- `label` — human-readable gap description
- `handler="codergen"` — always use codergen for fix-it nodes
- `worker_type` — route to appropriate specialist (see gap-decision-tree.md)
- `sd_path` — minimal solution design document for the gap
- `acceptance` — how to verify the gap is closed
- `priority` — P0 for regressions, P1 for high-severity closures, P2 for low-risk
- `status="pending"` — runner will dispatch when it reaches this node

#### Step 4: Create Minimal Solution Design Documents

Each fix-it node needs a Solution Design that constrains the scope. Document:
- **Gap Title** — exact title from gap list
- **In-scope Changes** — specific files and lines to modify
- **Acceptance Criteria** — how to verify closure
- **Risk Assessment** — why this is safe to close autonomously
- **Related Gaps** — cascade detection (if fixing G1 might create new gaps)

Example minimal SD:

```markdown
# Fix: Missing validation on email field

## Gap
Feature 2, Scenario 1 expects email validation but field accepts any string.

## In-Scope
- File: `frontend/forms/UserForm.tsx`
- Add: `email: z.string().email()` to validation schema
- Lines: ~150-160

## Acceptance
- Form rejects invalid emails
- Test `test_email_validation_rejects_invalid` passes
- No regression in other form tests

## Risk
Low — changes only validation schema, no API/database changes.

## Cascade
None expected — validation is isolated.
```

#### Step 5: Integrate Fix-It Nodes into Pipeline

Add fix-it nodes to the DOT file at the appropriate position. **Typical placement**:
- After the `validate_phase_4` node (which identified gaps)
- Before the `wait.cobuilder` node (final gate)

Update edges to wire fix-it nodes into the pipeline:

```dot
validate_phase_4 -> fix_gap_1;
validate_phase_4 -> fix_gap_2;
fix_gap_1 -> re_validate_1;
fix_gap_2 -> re_validate_1;
re_validate_1 -> wait.cobuilder;
```

#### Step 6: Re-Validate After Fixes Complete

After orchestrator executes fix-it nodes, run Phase 4 validation again on the same acceptance rubric:

- **All gaps closed?** → Proceed to Step 7 (escalation of non-closable gaps only)
- **New gaps introduced?** → Apply cascade detection rules:
  - Track iteration count (start at 1)
  - If iteration > 3, escalate entire gap set to wait.human
  - If new gaps are closable, continue to Step 3
  - If new gaps are not-closable, proceed to Step 7

#### Step 7: Escalate Remaining Gaps to wait.human

For each gap that is **not closable**, prepare escalation with context:

```
[ESCALATED GAP]
Gap ID: G5
Title: Missing database migration for new user roles table

Why Not Closable:
- Requires architectural decision on database schema design
- Impacts multiple services (auth, user, admin)
- Need to decide: normalize roles or embed in users table?

Acceptance Criterion:
Feature 4, Scenario 2 expects users with roles attribute populated

Current State:
- PR #47 added roles field to domain model
- API endpoint returns empty roles array
- No database columns exist yet

What User Must Decide:
1. Schema design: separate roles table or embedded?
2. Migration timeline: now or deferred?
3. Scope: which services need roles support?

Recommendation:
Schedule a 30-minute design review with backend architect.
Evidence is available in validation report at line 245.
```

### Common Gap Patterns by Framework

**React/TypeScript Frontend**:
- Missing import → low-risk closure
- Missing Tailwind class → low-risk closure
- State not initialized → medium-risk, depends on logic
- Event handler missing → medium-risk
- Props validation → low-risk

**Python/FastAPI Backend**:
- Missing import → low-risk closure
- Missing route → medium-risk
- Missing validation → low-risk closure
- Error handling → low-risk closure
- Database query → medium-risk

**Tests**:
- Assertion missing → low-risk closure
- Mock not configured → low-risk closure
- Setup missing → low-risk closure
- Test isolation → medium-risk

**All Frameworks**:
- Off-by-one error → low-risk closure (obvious fix)
- Logic inversion → low-risk closure (obvious fix)
- Type annotation → low-risk closure
- Documentation string → low-risk closure

### Time Complexity Thresholds

Estimate time to closure for each gap. Use this to make closure decisions:

| Estimate | Decision |
|----------|----------|
| < 5 min | Always create fix-it node |
| 5-15 min | Create fix-it node |
| 15-30 min | Create fix-it node (but monitor cascade) |
| 30-60 min | Escalate (too complex) |
| > 60 min | Escalate (major rework) |

**If multiple gaps combined exceed 30 minutes**, escalate the entire set to wait.human with grouping.

### Cascade Detection Rules

Track iteration depth when re-validating after closures:

```
Iteration 1: Fix G1, G2, G3 → Re-validate → New gaps G4, G5
             (3 closable fixes → 2 new gaps → continue)

Iteration 2: Fix G4, G5 → Re-validate → New gaps G6
             (2 closable fixes → 1 new gap → continue)

Iteration 3: Fix G6 → Re-validate → No new gaps
             (1 closable fix → clean → COMPLETE)

But if Iteration 3 → Re-validate → New gaps G7, G8, G9
                (3 new gaps at depth 3 → ESCALATE)
```

**Escalation trigger**: If after 3 iterations of closure attempts, you still have new closable gaps, escalate the entire set to wait.human with evidence of the cascade.

### Beads Synchronization

For each fix-it node created, create a corresponding Beads issue:

```bash
bd create --title="FIX-G1: Missing email validation" \
          --type=task \
          --priority=0 \
          --description="Close G1 gap from Phase 4 validation" \
          --epic-id=FIX-G1
```

Update the Beads issue when:
- Fix-it node is created (mark as in_progress)
- Worker completes the node (mark as done)
- Gap is re-validated and confirmed closed (mark evidence)

This enables cross-referencing between gap closure work and issue tracking.

### Storing Gap Closure Evidence

After all closable gaps are closed, store the evidence:

```python
mcp__hindsight__retain(
    content=f"""
Phase 4.5 Autonomous Gap Closure Results:
- Gaps identified: {len(phase_4_gaps)}
- Gaps closed autonomously: {len(closed_gaps)}
- Gaps escalated: {len(escalated_gaps)}
- Iterations required: {iteration_count}
- Total time: {total_time_minutes} min

Closed Gaps: {[g.id for g in closed_gaps]}
Escalated Gaps: {[g.id for g in escalated_gaps]}
Cascade depth: {iteration_count}
""",
    context="validation-gap-closure",
    bank_id="claude-code-{project}"
)
```

---

## Guardian Phase 4: Independent Validation (Full Reference)

> Extracted from s3-guardian SKILL.md — complete validation procedure including evidence gathering, DOT pipeline integration, regression detection, scoring method construction, evidence gates, journey tests, verdict delivery, and results storage.

### Phase 4: Independent Validation

After the meta-orchestrator claims completion, independently validate all work against the blind acceptance rubric.

#### Validation Protocol

1. **Read the acceptance manifest**: Load `acceptance-tests/PRD-{ID}/manifest.yaml` and the `.feature` files
2. **Read the actual code**: Navigate the implementation repo independently — examine git diffs, file contents, test results
3. **Score each scenario**: Assign a confidence score (0.0 to 1.0) per Gherkin scenario
4. **Compute weighted total**: Multiply each scenario score by its feature weight, sum across all features
5. **Decide**: Compare the weighted total against the manifest thresholds

#### Evidence Gathering

```bash
# Check what actually changed
git -C /path/to/impl-repo show --stat HEAD~10..HEAD

# Look for specific implementations
grep -r "function_name\|class_name" /path/to/impl-repo/src/

# Read actual function bodies
cat /path/to/impl-repo/src/module.py

# Run tests independently (if test suite exists)
cd /path/to/impl-repo && pytest --tb=short 2>&1 | tail -20
```

**Critical principle**: Read the code directly. Do NOT trust orchestrator self-reports, progress logs, or status messages. The entire point of the guardian pattern is independent verification.

#### DOT Pipeline Integration

When the initiative uses a `.dot` attractor pipeline, Phase 4 validation is node-driven. Each hexagon node in the pipeline graph represents a single validation gate. The guardian reads node attributes directly rather than inferring scope from PRD text.

##### Reading Validation Scope from Hexagon Nodes

```bash
# Extract node attributes from the pipeline DOT file
# Hexagon nodes (shape=hexagon) represent validation gates
grep -A 20 'shape=hexagon' .pipelines/<pipeline>.dot
```

A hexagon node exposes these attributes:

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `gate` | `technical` / `business` / `e2e` | Which validation mode to run |
| `mode` | `technical` / `business` | Maps directly to `--mode` parameter |
| `acceptance` | criteria text | What must be true for the gate to pass |
| `files` | comma-separated paths | Exact files to examine — no guessing |
| `bead_id` | e.g., `AT-10-TECH` | Beads task ID for recording results |
| `promise_ac` | e.g., `AC-1` | Completion promise criterion to meet |

**Example hexagon node:**
```dot
validate_backend_tech [
    shape=hexagon
    label="Backend\nTechnical\nValidation"
    gate="technical"
    mode="technical"
    bead_id="AT-10-TECH"
    acceptance="POST /auth/login returns JWT; POST /auth/refresh rotates token"
    files="src/auth/routes.py,src/auth/jwt.py,src/auth/models.py"
    promise_ac="AC-1"
    status="pending"
];
```

##### Validation Method Inference

The `files` attribute determines which validation technique the guardian uses:

```python
def infer_validation_method(files: list[str]) -> str:
    """Map file paths to the appropriate validation method."""
    for f in files:
        # Browser-required: frontend pages, components, stores
        if any(p in f for p in ["page.tsx", "component", "components/", "stores/", ".tsx", ".vue"]):
            return "browser-required"
        # API-required: route handlers, API modules, controllers
        if any(p in f for p in ["routes.py", "api/", "controllers/", "handlers/", "views.py"]):
            return "api-required"
    # Default: static code analysis is sufficient
    return "code-analysis"
```

| Files pattern | Validation method | Tools |
|--------------|-------------------|-------|
| `*.tsx`, `page.tsx`, `components/` | `browser-required` | chrome-devtools MCP, screenshot capture |
| `routes.py`, `api/`, `handlers/` | `api-required` | HTTP calls against real endpoints |
| `*.py`, `*.ts` (non-route) | `code-analysis` | Read file, check implementation, run pytest |

##### Evidence Storage

All evidence from DOT-based validation is stored under `.claude/evidence/<node-id>/`:

```
.claude/evidence/
└── <node-id>/                        # e.g., validate_backend_tech/
    ├── technical-validation.md       # Technical gate findings
    ├── business-validation.md        # Business gate findings (if mode=business)
    └── validation-summary.json       # Machine-readable summary
```

**validation-summary.json schema:**
```json
{
    "node_id": "validate_backend_tech",
    "bead_id": "AT-10-TECH",
    "gate": "technical",
    "mode": "technical",
    "verdict": "PASS",
    "confidence": 0.92,
    "files_examined": ["src/auth/routes.py", "src/auth/jwt.py"],
    "acceptance_criteria": "POST /auth/login returns JWT; POST /auth/refresh rotates token",
    "evidence": "pytest: 18/18 passing. routes.py: login endpoint at line 24. jwt.py: token rotation confirmed.",
    "timestamp": "2026-02-22T10:30:00Z"
}
```

**technical-validation.md template:**
```markdown
# Technical Validation: <node-id>

**Gate**: technical
**Bead**: <bead_id>
**Acceptance**: <acceptance text from node>

## Files Examined
- <file_path> — <summary of what was found>

## Checklist
- [ ] Unit tests pass (pytest/jest output)
- [ ] Build clean (no compile errors)
- [ ] Imports resolve
- [ ] TODO/FIXME count: 0
- [ ] Linter clean

## Verdict
**PASS** | **FAIL** (confidence: 0.XX)

## Evidence
<exact test output, file excerpts, or error messages>
```

##### Advancing the Pipeline After Validation

When a node passes, advance its status using the attractor CLI:

```bash
# Transition node to 'validated' status
cobuilder pipeline transition .pipelines/pipelines/<pipeline>.dot <node_id> validated

# If validation fails, transition to 'failed'
cobuilder pipeline transition .pipelines/pipelines/<pipeline>.dot <node_id> failed

# Save checkpoint after any transition
cobuilder pipeline checkpoint-save .pipelines/pipelines/<pipeline>.dot
```

**Guardian workflow for DOT pipelines:**
```python
def validate_dot_pipeline_node(node_id: str, node_attrs: dict):
    # 1. Extract scope from node attributes
    gate = node_attrs["gate"]       # technical / business / e2e
    mode = node_attrs["mode"]       # maps to --mode parameter
    files = node_attrs["files"].split(",")
    acceptance = node_attrs["acceptance"]
    bead_id = node_attrs["bead_id"]

    # 2. Infer validation method from files
    method = infer_validation_method(files)

    # 3. Execute appropriate validation
    if mode == "technical":
        result = run_technical_validation(files, acceptance)
    elif mode == "business":
        result = run_business_validation(files, acceptance, method)

    # 4. Store evidence
    evidence_dir = f".claude/evidence/{node_id}/"
    write_evidence(evidence_dir, result, gate, mode, bead_id, acceptance)

    # 5. Advance pipeline status
    status = "validated" if result.verdict == "PASS" else "failed"
    run(f"cobuilder pipeline transition .pipelines/pipelines/<pipeline>.dot {node_id} {status}")
    run(f"cobuilder pipeline checkpoint-save .pipelines/pipelines/<pipeline>.dot")

    # 6. Meet completion promise AC
    if result.verdict == "PASS":
        run(f"cs-promise --meet <id> --ac-id {node_attrs['promise_ac']} "
            f"--evidence 'Evidence at .claude/evidence/{node_id}/'")

    return result
```

---

### Phase 4.5: Autonomous Gap Closure

After Phase 4 validation identifies gaps, System 3 autonomously decides whether to close each gap via a codergen fix-it node or escalate it to the `wait.human` gate. The goal is to **never report gaps to the user that can be fixed without architectural or UX decisions**.

This phase implements the gap closure decision tree documented in `gap-closure-protocol.md` and `gap-decision-tree.md`.

#### When Phase 4.5 Executes

Phase 4.5 runs **immediately after** Phase 4 validation completes and has identified a list of gaps:

```
Phase 4: Independent Validation (identify gaps)
    ↓
Phase 4.5: Autonomous Gap Closure (this phase)
    ├─ Analyze each gap
    ├─ Decide: fixable autonomously or escalate?
    ├─ Create + dispatch fix-it codergen nodes for fixable gaps
    ├─ Re-validate scenarios corresponding to closed gaps
    ↓
wait.human Gate (only gaps requiring user input/decision)
```

Only when all autonomously-fixable gaps are closed does System 3 transition the pipeline to the `wait.human` gate.

#### Gap Analysis Decision Tree

For each gap identified in Phase 4:

1. **Is gap in PRD scope?** (Reference PRD Section 8 epics)
   - NO → Note as informational, do not escalate
   - YES → Continue to step 2

2. **Is gap fixable without architectural or UX decisions?**
   - NO (requires design change, API rework, etc.) → Escalate to `wait.human`
   - YES → Continue to step 3

3. **Is this a regression?** (Compare against ZeroRepo baseline)
   - YES → Create P0 fix-it node (highest priority)
   - NO → Continue to step 4

4. **Is this low-risk and fixable in <15 minutes?** (imports, test mocks, CSS, validation checks)
   - YES → Create fix-it codergen node
   - NO → Escalate to `wait.human` with evidence

**Full decision flowchart and detailed gap examples** are documented in `gap-decision-tree.md`.

#### Autonomous Fix-It Node Pattern

When System 3 decides to close a gap autonomously:

1. **Create the fix-it node in DOT** (e.g., `fix_gap_1`)
   - Handler: `codergen`
   - Worker type: Determined by gap (backend-solutions-engineer, frontend-dev-expert, or tdd-test-engineer)
   - SD path: Minimal Solution Design (3-4 paragraphs, specific fix only)
   - Acceptance: "Gherkin scenario X passes; no regressions introduced"
   - Epic ID: FIX-X1 (temporary, for tracking)
   - Bead ID: Real bead ID created via `bd create`

2. **Wire fix-it into pipeline** (before `wait.human`)
   ```dot
   e1_gate -> fix_gap_1 [label="gaps_detected"];
   fix_gap_1 -> revalidate_gap_1 [label="impl_complete"];
   revalidate_gap_1 [handler="wait.cobuilder", gate_type="gap-closure"];
   revalidate_gap_1 -> e1_review [label="validated"];
   ```

3. **Dispatch and re-validate**
   - Runner dispatches fix-it codergen node
   - After completion, System 3 re-runs the exact Gherkin scenario that failed
   - If scenario passes → mark gap as closed, continue to next gap
   - If scenario still fails → requeue fix-it with updated guidance

4. **Cascade depth control**
   - Track iteration count for dependent gaps
   - After 3 iterations of fix-it nodes revealing new gaps → escalate remaining gaps to `wait.human`
   - Prevents runaway fix-it loops while allowing legitimate multi-step fixes

#### Common Fix-It Patterns

See `gap-closure-protocol.md` § "Common Fix-It Patterns by Gap Type" for:
- Missing import (ImportError) — <2 minutes
- Test mock setup (AssertionError) — <5 minutes
- CSS class application (visual mismatch) — <3 minutes
- Validation logic (missing assertion) — <5 minutes
- Regressions (feature that broke) — <15 minutes with investigation

#### Escalation to wait.human

Escalate a gap to `wait.human` if any of these apply:

| Reason | Example |
|--------|---------|
| Requires architectural redesign | API contract needs to return different field structure |
| Requires UX/design decision | Button should be different color or form layout should change |
| Outside PRD scope | Code doesn't follow company style guide; not a PRD requirement |
| Requires user clarification | "Is feature X supposed to work with legacy API Y?" |
| Would introduce cascading risk | Fixing this requires removing dependency X that other code depends on |
| Iteration limit exceeded | 3 cascading fix-it nodes and gaps still appearing |

**Escalation format**: Structured summary with gap title, scenario reference, evidence (error + root cause), reason for non-autonomy, and recommended next step. See `gap-closure-protocol.md` § "Escalation Format for wait.human".

#### Completion Criteria

Phase 4.5 is complete when:
- All in-scope, fixable gaps have fix-it nodes created and dispatched
- All fix-it codergen nodes have completed and re-validation passed
- No gaps remain that are fixable autonomously
- Pipeline transitions to `wait.human` gate with only gaps requiring user decision

---

### Phase 4.6: Regression Detection

After the meta-orchestrator completes implementation but **before** running journey tests, run an
automated regression check to detect components that were previously stable (`delta_status=existing`)
but have been unexpectedly modified or re-flagged as new in the updated graph.

This phase uses the `regression-check.sh` workflow script and the `zerorepo diff` CLI command.

#### When to Run Phase 4.5

Run regression detection when:
- The initiative uses a ZeroRepo baseline (`.zerorepo/baseline.json` exists in the impl repo)
- The meta-orchestrator has completed at least one implementation cycle (some nodes have been marked as modified/new)
- You suspect scope creep or unexpected side-effects from implementation work

Skip Phase 4.5 if:
- No `.zerorepo/` directory exists in the implementation repo (no baseline tracking)
- The initiative is in its first generation (no "before" baseline to compare against)

#### Running the Regression Check

```bash
# Basic regression check (compares current baseline to post-update baseline)
./regression-check.sh --project-path /path/to/impl-repo

# With pipeline in-scope filter (only checks nodes referenced in the DOT pipeline)
./regression-check.sh \
    --project-path /path/to/impl-repo \
    --pipeline /path/to/impl-repo/.zerorepo/pipeline.dot \
    --output-dir /path/to/impl-repo/.zerorepo/

# Direct zerorepo diff (when you already have before/after baselines)
zerorepo diff \
    /path/to/impl-repo/.zerorepo/baseline.before.json \
    /path/to/impl-repo/.zerorepo/baseline.json \
    --pipeline /path/to/impl-repo/.zerorepo/pipeline.dot \
    --output /path/to/impl-repo/.zerorepo/regression-check.dot
```

#### Interpreting regression-check.dot

The output `.dot` file contains one red-filled box per regressed node:

| Node attribute | Meaning |
|----------------|---------|
| `regression_type="status_change"` | Node was `existing` in baseline, now `modified`/`new` — unexpected change |
| `regression_type="unexpected_new"` | Node exists in updated graph but was absent from baseline entirely |
| `delta_status="modified"` or `"new"` | The status assigned to this node in the updated graph |
| `file_path="..."` | File associated with the regressed node |

```bash
# Quick scan: count regressions
grep 'regression_type=' /path/to/impl-repo/.zerorepo/regression-check.dot | wc -l

# List regressed node names
grep -oP 'label="\K[^\\]+' /path/to/impl-repo/.zerorepo/regression-check.dot
```

A `no_regressions` node with green fill means the check passed cleanly.

#### Guardian Response Protocol

| Regression Check Result | Guardian Action |
|------------------------|-----------------|
| Exit 0 — no regressions | Log PASS, proceed to Phase 5 (journey tests) |
| Exit 1 — regressions detected | Send findings to meta-orchestrator with specific node names and file paths |
| Exit 3 — update step failed | Check runner script path; verify `.zerorepo/` is properly initialized |

**When regressions are found**, send structured guidance to the meta-orchestrator:

```
tmux send-keys -t "s3-{initiative}" \
  "REGRESSION ALERT: zerorepo diff found {N} regressed nodes. Review .zerorepo/regression-check.dot.
   Affected nodes: {node_names}
   These nodes were previously stable (delta_status=existing) and are now marked as modified/new.
   Investigate whether these changes are intentional or are side-effects of recent implementation work.
   If intentional, update the baseline. If unintentional, revert the affecting changes." Enter
```

#### Evidence Storage for Regression Phase

```
.claude/evidence/PRD-{ID}-epic6/
├── regression-check.dot          # DOT output from zerorepo diff
├── baseline.before.json          # The "before" snapshot (copy)
└── regression-summary.md         # Human-readable summary
```

**regression-summary.md template:**
```markdown
# Regression Check: PRD-{ID}

**Date**: {timestamp}
**Before baseline**: .zerorepo/baseline.before.json
**After baseline**: .zerorepo/baseline.json
**Pipeline filter**: {pipeline_path or "none"}

## Result: PASS | FAIL ({N} regressions)

### Regressions Found
- {node_name} ({file_path}): was existing → now {delta_status}
- ...

### Unexpected New Nodes
- {node_name} ({file_path}): appears in updated graph but not in baseline
- ...

## Disposition
{CLEARED: All regressions are intentional (implementation of planned changes) OR
ESCALATED: N regressions are unintentional side-effects, sent to meta-orchestrator}
```

#### Meeting the Completion Promise AC

```bash
# When regression check passes
cs-promise --meet <id> --ac-id AC-4.5 \
    --evidence "regression-check.dot: 0 regressions detected. Baseline updated." \
    --type manual

# When regressions found but cleared (intentional)
cs-promise --meet <id> --ac-id AC-4.5 \
    --evidence "regression-check.dot: 3 regressions — all intentional (confirmed with meta-orch)" \
    --type manual
```

---

### Step 5a: Validation Method-Specific Prompt Construction

Before dispatching scoring agents for each feature, provide the scoring agent with both:
- The **Gherkin scenario** (blind rubric from Phase 1, generated from the SD)
- The **SD document** for this epic (`solution_design` attribute on the DOT node, or from
  `.taskmaster/docs/SD-{CATEGORY}-{NUMBER}-{epic-slug}.md`)

The SD contains the file scope, API contracts, and per-feature acceptance criteria that tell
the scoring agent exactly what "done" looks like. Without it, agents score on gut feel rather
than specification.

```python
# Read SD path from DOT node or construct from naming convention
sd_path = node_attrs.get("solution_design", f".taskmaster/docs/SD-{epic_id}.md")

# Build per-feature scoring prompt
scoring_prompt = f"""
You are scoring the implementation of this feature against its acceptance rubric.

**Solution Design** (read this first — it defines done):
{sd_path}

Key sections to check:
- Section 4: Functional Decomposition (is each capability implemented?)
- Section 6: Acceptance Criteria per Feature (per-feature definition of done)
- Section 8: File Scope (were only allowed files modified?)

**Feature scenario to score:**
[scenario text from Gherkin file]
"""
```

Also read `validation_method` from the manifest and prepend mandatory tooling instructions:

**For `browser-required` features:**
```
MANDATORY: YOU MUST use Claude in Chrome (mcp__claude-in-chrome__*) to validate this feature.
Static code analysis alone (Read/Grep) = automatic 0.0 score.
Required tool sequence: tabs_context_mcp → navigate → read_page → screenshot → interact with elements.
If the frontend is not running, report "BLOCKED: frontend not running" — do NOT fall back to code analysis.
```

**For `api-required` features:**
```
MANDATORY: YOU MUST make actual HTTP requests (curl/httpx) to validate this feature.
Reading router/endpoint code alone = automatic 0.0 score.
Required: Make real requests, capture response status codes and bodies as evidence.
If the API server is not running, report "BLOCKED: API server not running" — do NOT fall back to code analysis.
```

**For `code-analysis` features:**
No special prepend. Current behavior (Read/Grep/file examination) is appropriate.

**For `hybrid` features (or absent field):**
No special prepend. Scoring agent uses its best judgment on which tools to employ.

**Implementation**: When constructing the scoring agent prompt in Phase 4, read each feature's `validation_method` from the manifest. If the field is present and not `hybrid`, prepend the corresponding instruction block above to the agent's prompt BEFORE the scenario text.

### Step 5b: Evidence Gate Enforcement

After scoring agents return results but BEFORE computing the weighted total, scan each feature's evidence for method-appropriate keywords. This is the strongest enforcement — it catches agents that ignore the prompt prepend.

**Evidence keyword requirements:**

| `validation_method` | Required keywords (at least 2) | What they prove |
|---------------------|-------------------------------|-----------------|
| `browser-required` | "screenshot", "navigate", "tabs_context", "read_page", "Chrome", "localhost:3000" | Agent actually used the browser |
| `api-required` | "curl", "HTTP 200", "HTTP 201", "HTTP 202", "response body", "localhost:8000", actual JSON snippets | Agent actually made HTTP requests |
| `code-analysis` | No keyword requirement | Static analysis is the expected method |
| `hybrid` | No keyword requirement | Agent discretion |

**Enforcement logic:**
1. For each feature with `validation_method` = `browser-required` or `api-required`:
2. Scan the scoring agent's evidence text for the required keywords
3. If fewer than 2 required keywords are found:
   - **Override the feature score to 0.0**
   - Set reason: `"EVIDENCE GATE: {validation_method} feature scored without {validation_method} evidence. Agent used static analysis instead of required tooling."`
   - Log the override in the validation worksheet
4. Proceed with weighted total computation using the overridden score

**Why 2 keywords minimum?** A single keyword match could be coincidental (e.g., mentioning "Chrome" in a description without using it). Two keywords indicate actual tool usage.

This gate ensures that even if a scoring agent ignores the prompt prepend, its score is corrected to 0.0 — making it impossible to score well on a browser-required feature without actually opening a browser.

### Step 6: Execute Journey Tests

After computing the per-feature weighted score, execute the journey tests in `journeys/`.

Journey tests were generated from the **PRD** (`PRD-{ID}.md`) — they verify cross-epic business
flows that no single orchestrator owns. The runner should be given the PRD for context so it can
understand *why* each step exists, not just whether it passes.

**Execution approach** — spawn a tdd-test-engineer sub-agent:

```python
Task(
    subagent_type="tdd-test-engineer",
    description="Execute journey tests for PRD-{ID}",
    prompt="""
    Execute the journey test scenarios at: acceptance-tests/PRD-{ID}/journeys/

    Context: these tests were generated from .taskmaster/docs/PRD-{ID}.md and validate
    end-to-end business flows that span multiple implementation epics. Read the PRD
    Goals section (Section 2) to understand the business outcomes being verified.

    For each J{N}.feature file:
    1. Read the scenario
    2. Execute each step in sequence:
       - @browser steps: use chrome-devtools MCP (navigate, click, assert_visible, etc.)
       - @api steps: make actual API calls and assert responses
       - @db steps: query the DB directly using runner_config.yaml dsn
       - "eventually" steps: poll the specified condition every interval_seconds, up to max_wait_seconds
       - Pass artifacts forward: contact_id extracted in step 3 → used in step 5 DB query
    3. Report pass/fail per step, plus the artifact values at each step
    4. Return journey-results.json: {J1: {status: PASS/FAIL, steps: [...]}, J2: ...}

    Services are defined in runner_config.yaml.
    If services are not running, mark all @async and @browser steps as SKIP (not FAIL)
    and note "requires live services". Mark @smoke steps as runnable anyway.

    Return journey-results.json to the guardian session.
    """
)
```

**If services not running** (structural-only mode):
- Guardian reads the journey `.feature` files manually
- Checks that each layer mentioned in the scenario has corresponding code
- Marks as `STRUCTURAL_PASS` / `STRUCTURAL_FAIL`
- Does not block the per-feature verdict (only live execution can apply the override)

**Override Rule (MANDATORY when live execution runs)**:
```
If ANY journey test returns FAIL (not SKIP):
  → Final verdict = REJECT regardless of per-feature weighted score
  → Reason: "Journey J{N} failed at step: {step_description} — business outcome not achieved"
```

Example: per-feature score = 0.92 (would be ACCEPT) + J1 FAILS at "Prefect flow Completed"
  → Final verdict: **REJECT**
  → Reason: "Prefect trigger not firing; contact_id xxx never appeared in flow runs"

Include `journey-results.json` in the evidence package alongside per-feature scores.

### Deliver Verdict

Combine results:
- Per-feature weighted score (0.0-1.0)
- Journey test results (PASS / FAIL / SKIP per J{N}, or STRUCTURAL_PASS/FAIL)

Final decision matrix:

| Per-feature score | Journey results     | Final verdict                                   |
|-------------------|---------------------|-------------------------------------------------|
| >= 0.60           | All PASS            | ACCEPT                                          |
| >= 0.60           | Any FAIL            | REJECT (journey override)                       |
| >= 0.60           | All SKIP            | ACCEPT (note: live validation pending)          |
| 0.40-0.59         | Any                 | INVESTIGATE                                     |
| < 0.40            | Any                 | REJECT                                          |

Thresholds are configurable per initiative in `manifest.yaml`.

---

### Storing Validation Results

After completing validation, store findings for institutional memory:

```python
# Store to Hindsight (private bank for future guardian sessions)
mcp__hindsight__retain(
    content=f"""
    ## Guardian Validation: PRD-{prd_id}
    ### Weighted Score: {score} ({verdict})
    ### Feature Scores: {feature_breakdown}
    ### Gaps Found: {gaps}
    ### Lessons: {lessons}
    """,
    context="s3-guardian-validations",
    bank_id="system3-orchestrator"
)

# Store to project bank (shared, for team awareness)
mcp__hindsight__retain(
    content=f"PRD-{prd_id} validated: {verdict} (score: {score}). Key findings: {summary}",
    context="project-validations",
    bank_id="claude-code-{project}"
)
```

---

**Reference Version**: 0.1.0
**Parent Skill**: s3-guardian
