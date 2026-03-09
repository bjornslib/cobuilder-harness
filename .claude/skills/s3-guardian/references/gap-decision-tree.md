---
title: "Gap Decision Tree"
status: active
type: reference
last_verified: 2026-03-09
grade: authoritative
---

# Gap Decision Tree

Visual guide and concrete examples for analyzing validation gaps discovered during Phase 4. This document provides the decision logic to rapidly categorize gaps and route them to fix-it codergen nodes or escalation.

## Visual Decision Flowchart

```
┌──────────────────────────────────────┐
│   Gap Identified During Validation   │
│   (Error, assertion failure, etc.)   │
└───────────────┬──────────────────────┘
                │
                ▼
        ┌──────────────┐
        │ In PRD Scope?│  (Check Section 8)
        └──────┬───────┘
       YES │   │ NO
           │   └──────────────────────┐
           │                          ▼
           │                 [ESCALATE]
           │              Out-of-scope
           │              Document note
           │
           ▼
    ┌──────────────────────┐
    │ Fixable without UX   │
    │ or architecture      │
    │ decision?            │
    └──────┬───────────────┘
    NO  │  │ YES
        │  │
        │  ▼
        │  ┌──────────────┐
        │  │ Regression?  │  (ZeroRepo check)
        │  └──────┬───────┘
        │  YES  │ NO
        │    ┌──┘
        │    ▼
        │   ┌───────────────┐
        │   │ Quick & Low   │
        │   │ Risk Fix?     │
        │   └──┬────────────┘
        │  YES │ NO
        │    ┌─┘  │
        │    │    └────┐
        │    ▼         ▼
        │ [CREATE] [ESCALATE]
        │ FIX-IT  For judgment
        │ CODERGEN
        │
        ▼
    [ESCALATE]
    Requires design
    decision
```

## Gap Categories with Examples

### Category A: Fixable Autonomously (Create Fix-It)

**Characteristics:**
- Single, clear root cause
- Deterministic solution
- No judgment calls
- Low risk of side effects
- Closure time: <5 minutes typically

#### Example A1: Missing Import

**Gap**: `ImportError: cannot import name 'validate_email' from 'forms'`

**Analysis:**
- ✅ In-scope? Yes (validation is in PRD)
- ✅ Fixable? Yes (deterministic)
- ✅ Not a judgment? Correct (clear from error)

**Decision**: **CREATE FIX-IT**

**Fix-It Node**:
```dot
fix_import_a1 [
    shape=box
    label="FIX: Import validate_email from forms"
    handler="codergen"
    worker_type="backend-solutions-engineer"
    sd_path="docs/sds/fix-gap-a1.md"
    acceptance="ImportError resolved, test passes"
    prd_ref="PRD-EXAMPLE-001"
    epic_id="FIX-A1"
    bead_id="FIX-A1-IMPL"
];
```

**SD** (minimal):
```markdown
# Fix: Missing Import

File: `forms.py` line 42
Missing import: `from validation import validate_email`

Add line: `from validation import validate_email`
Verify: Test suite passes without import errors
```

**Worker**: backend-solutions-engineer
**Time**: <2 minutes

---

#### Example A2: Test Mock Configuration

**Gap**: `AssertionError: expected {data: 'mock'} but got None`

**Analysis:**
- ✅ In-scope? Yes (test is checking acceptance criteria)
- ✅ Fixable? Yes (mock setup pattern exists in codebase)
- ✅ Not a judgment? Correct (clear from test expectation)

**Decision**: **CREATE FIX-IT**

**Pattern**:
Look at similar test setup in same file. Mock needs to return the expected structure.

**SD**:
```markdown
# Fix: Configure Mock Return Value

Test: `test_user_registration` line 28
Mock missing setup: `APIClient.validate_email()`

Configure mock to return: `{status: 'valid', score: 0.95}`
Reference existing mock pattern in line 15: `mock.MagicMock(return_value=...)`
```

**Worker**: tdd-test-engineer
**Time**: <5 minutes

---

#### Example A3: CSS Class Application

**Gap**: Button shows as gray instead of blue (from visual comparison against mockup)

**Analysis:**
- ✅ In-scope? Yes (design is in acceptance criteria, mockup included)
- ✅ Fixable? Yes (clear from design system)
- ✅ Not a judgment? Correct (design system has approved classes)

**Decision**: **CREATE FIX-IT**

**SD**:
```markdown
# Fix: Apply Correct Button Class

Component: `SubmitButton.tsx` line 42
Current: `<button className="button-default">`
Should be: `<button className="button-primary">`

Reference: Design system at `docs/design/button-classes.md`
Verify: Visual matches mockup (blue, white text)
```

**Worker**: frontend-dev-expert
**Time**: <3 minutes

---

#### Example A4: Regression Detection

**Gap**: Logout button doesn't clear session (feature that was working, now broken)

**Analysis**:
- ✅ ZeroRepo check: Feature was passing at Phase 0, now failing
- ✅ Type: REGRESSION (broken after working)
- ✅ Priority: P0 (critical, must fix immediately)

**Decision**: **CREATE FIX-IT IMMEDIATELY**

**Pattern**:
Regressions **always** get autonomous fix-it nodes. System 3 should not escalate a feature that previously worked.

**SD**:
```markdown
# Fix: Logout Regression (P0)

Feature: User logout should clear session

Current behavior: Session persists after logout button clicked
Expected behavior: Session cleared, user redirected to /login

Investigation needed: Trace logout button handler
(Worker will determine root cause and fix)

Verify: Gherkin scenario F2-S1 returns to PASSED
```

**Worker**: backend-solutions-engineer or frontend-dev-expert (depending on handler)
**Time**: <15 minutes (may include investigation)

---

### Category B: Escalate to wait.human (Do NOT Create Fix-It)

**Characteristics:**
- Requires human judgment
- Architectural or UX decision
- Out of scope
- Ambiguous requirement
- High risk of unintended consequences

#### Example B1: Architectural Decision

**Gap**: API endpoint returns user ID but acceptance criteria expect email

**Analysis**:
- ✅ In-scope? Yes (API contract is PRD requirement)
- ❌ Fixable autonomously? No (requires design decision)
- ❓ Which should it return? (judgment call)

**Decision**: **ESCALATE**

**Escalation Summary**:
```markdown
### Gap: API Response Field Mismatch

**Scenario**: F1-S2: User registration returns user object

**Evidence**:
- Endpoint returns: `{user_id: 123}`
- Acceptance criteria expect: `{email: 'user@example.com'}`
- Root cause: API contract defined without acceptance criteria input

**Why not autonomous**: Changing API schema affects downstream code.
This requires architectural decision.

**Recommended action**: User should clarify: Is endpoint contract
correct, or should it be updated? Impacts all callers.
```

**User decision**: Return to designer/architect for endpoint spec clarification

---

#### Example B2: UX/Design Decision

**Gap**: Form field order doesn't match mockup, tests pass but UX feels wrong

**Analysis**:
- ✅ In-scope? Yes (form layout is part of PRD)
- ❌ Fixable autonomously? No (requires UX/design decision)
- ❓ Is this mockup the final design? (judgment call)

**Decision**: **ESCALATE**

**Escalation Summary**:
```markdown
### Gap: Form Field Layout Discrepancy

**Scenario**: F3-S1: Registration form displays all required fields

**Evidence**:
- Current order: email, password, confirm, name
- Mockup shows: name, email, password, confirm
- Both pass functional tests (all fields present and working)
- Difference is UX/flow

**Why not autonomous**: Field order is a design decision.
Auto-fixing could contradict user's actual design intent.

**Recommended action**: User should confirm: Is mockup the
final design direction? If yes, approve fix-it creation.
```

**User decision**: Design team confirms, System 3 creates fix-it OR design changes, escalation closes

---

#### Example B3: Out-of-Scope Gap

**Gap**: Code has inconsistent naming convention (camelCase vs snake_case)

**Analysis**:
- ❌ In-scope? No (code style is not in PRD Section 8)
- ✅ Fixable? Technically yes, but...
- ❓ Is this PRD scope? No.

**Decision**: **ESCALATE (or IGNORE)**

**Escalation Summary** (if mentioning at all):
```markdown
### Gap: Code Style Inconsistency (Out-of-Scope)

**Evidence**:
- Some variables: camelCase
- Some variables: snake_case
- No style guide in PRD acceptance criteria

**Why not autonomous**: Out-of-scope for PRD-EXAMPLE-001.
Code style is a separate concern (linter/formatter, not feature).

**Action**: Note as informational. Not a blocker for acceptance.
Defer to separate code quality initiative if needed.
```

**No user action needed**: Document, move forward

---

#### Example B4: Ambiguous Requirement

**Gap**: Gherkin scenario says "check password strength" but no specifics on what "strong" means

**Analysis**:
- ✅ In-scope? Yes (password validation in PRD)
- ❌ Fixable? Not without knowing criteria
- ❓ What makes password strong? (ambiguous requirement)

**Decision**: **ESCALATE**

**Escalation Summary**:
```markdown
### Gap: Ambiguous Requirement - Password Strength

**Scenario**: F1-S4: Registration accepts only strong passwords

**Evidence**:
- Acceptance criteria: "Check password strength"
- Missing: Definition of "strong" (length? complexity? dictionary check?)
- Current implementation: Accepts any password >8 chars
- Test fails: Because definition is unclear

**Why not autonomous**: Fix depends on requirement clarification.
Is >8 chars enough? Need uppercase? Numbers? Symbols?

**Recommended action**: Product/requirements team should define
"strong password" criteria, then System 3 creates fix-it.
```

**User decision**: Clarify requirement, then System 3 creates fix-it for implementation

---

### Category C: Cascade Detection (Watch for Infinite Loop)

**Pattern**: Fixing gap 1 reveals gap 2, fixing gap 2 reveals gap 3...

**Cascade Depth Tracking**:

```
Iteration 1: Fix "missing import A" → Gap discovered
Iteration 2: Fix "missing validation B" → Gap discovered
Iteration 3: Fix "mock config C" → Gap discovered
Iteration 4: Would fix "missing field D" but...

STOP: Cascade depth > 3
→ Escalate remaining gaps to wait.human
```

**Example Cascade**:

```
Phase 4: Run test `test_user_registration`
├─ Fail: "ImportError: validate_email"
├─ Create fix_gap_1, dispatch
├─ Fix completes, re-validate
│
├─ Fail: "AssertionError: mock returned None"
├─ Create fix_gap_2, dispatch
├─ Fix completes, re-validate
│
├─ Fail: "TypeError: expected dict, got list"
├─ Create fix_gap_3, dispatch
├─ Fix completes, re-validate
│
├─ Fail: "KeyError: 'email' not in response"
├─ Cascade depth = 4, STOP
│
└─ Escalate remaining gaps:
   "Multiple cascading issues detected.
    Escalating for root cause analysis."
```

**Decision**: After 3 fix-it iterations, escalate with summary:

```markdown
### Cascade Detected: Multiple Related Gaps

**Root cause**: Possibly incorrect mock setup or API contract

**Gaps closed**:
1. Missing import validate_email
2. Mock configuration for APIClient
3. Response structure mismatch

**Remaining gaps**:
1. Response missing required field 'email'
2. (Potentially more downstream)

**Why escalate**: 3-iteration threshold reached.
Likely systematic issue (mock, contract, or design) that requires
user review before continuing.

**Recommended action**: User should review API contract and mock
setup, then approve approach for remaining gaps.
```

---

## Quick Reference: Gap Type → Action

| Gap Type | Detection | Worker Type | Time | Action |
|----------|-----------|-------------|------|--------|
| Missing import | `ImportError` in logs | backend | <2m | ✅ Fix-it |
| Test mock failed | `AssertionError: got None` | tdd-engineer | <5m | ✅ Fix-it |
| CSS class wrong | Visual inspection vs mockup | frontend | <3m | ✅ Fix-it |
| Regression | ZeroRepo: was passing | (relevant) | <15m | ✅ Fix-it P0 |
| API contract change | Response field mismatch | (escalate) | - | ❌ Escalate |
| Form layout | Order doesn't match mockup | (escalate) | - | ❌ Escalate |
| Code style | Convention inconsistent | (none) | - | ℹ️ Note only |
| Requirement ambiguous | Criteria not defined | (escalate) | - | ❌ Escalate |
| Cascade >3 iterations | Depth exceeded | (escalate) | - | ❌ Escalate |

---

## Decision Flowchart for Each Gap

For every gap identified in Phase 4, System 3 should follow this logic:

```python
def decide_gap_action(gap):
    """Decide: fix autonomously or escalate?"""

    # Check 1: Scope
    if not is_in_prd_scope(gap):
        return ESCALATE("Out of PRD scope")

    # Check 2: Fixability
    if requires_architectural_decision(gap):
        return ESCALATE("Requires architecture decision")

    if requires_uux_decision(gap):
        return ESCALATE("Requires UX/design decision")

    if is_ambiguous(gap):
        return ESCALATE("Requirement is ambiguous")

    # Check 3: Risk
    if could_break_other_features(gap):
        return ESCALATE("High risk of regressions")

    # Check 4: Regression
    if is_regression(gap):  # ZeroRepo check
        return CREATE_FIX_IT(priority=P0)

    # Check 5: Low-risk fixable
    if is_low_risk_fix(gap):
        return CREATE_FIX_IT(priority=P2)

    # Default: When in doubt, escalate
    return ESCALATE("Uncertain fixability")
```

---

## Severity and Priority Guidelines

**How to set fix-it priority**:

| Severity | Examples | Fix-It Priority |
|----------|----------|-----------------|
| **Regression** | Feature that broke | **P0** (critical) |
| **Blocker** | Feature doesn't work at all | **P1** |
| **Major** | Feature partially works | **P1** |
| **Minor** | Edge case or styling | **P2** |
| **Trivial** | Typo, lint warning | **P3** |

**Regression rule**: Any gap detected via ZeroRepo (feature that was passing, now failing) = P0, create fix-it immediately.

---

## Time Complexity Threshold

Use time estimates to decide when to escalate instead of creating cascades:

| Estimate | Action |
|----------|--------|
| <5 minutes | Create fix-it |
| 5-15 minutes | Create fix-it, but watch closely |
| 15-30 minutes | Create fix-it ONLY if critical (regression/blocker) |
| >30 minutes | Escalate with evidence, let user decide |

**Cascade time limit**: If 3 cascading fix-its exceed 30 minutes total, escalate remaining gaps:

```bash
# Example: Cascade took 27 minutes so far
fix_gap_1: 8 minutes (import)
fix_gap_2: 7 minutes (mock)
fix_gap_3: 12 minutes (validation)
TOTAL: 27 minutes, close to 30-minute threshold

Gap 4 appears: Would take ~5 more minutes = 32 total
→ ESCALATE: "Exceeded time threshold for autonomous fixes"
```

---

## Anti-Patterns in Gap Analysis

| Anti-Pattern | Problem | Correct Approach |
|--------------|---------|------------------|
| Escalating every minor gap | Interrupts user unnecessarily | Analyze decision tree, create low-risk fixes |
| Creating fix-it for out-of-scope gap | Scope creep | Check PRD Section 8 first |
| Skipping cascade depth check | Infinite loop risk | Track depth, escalate at threshold |
| Assuming fix won't break others | False confidence | Consider downstream impacts |
| Creating mega fix-it for 5 gaps | Harder to debug | Create separate fix-it per root cause |
| Ignoring ZeroRepo regression signal | Misses critical issues | Always check ZeroRepo for regressions |

---

## Real-World Gap Analysis Examples

### Example 1: Simple Gap

```
Gap Found: Test fails with "IndexError: list index out of range"
Code: response.contacts[0].email

Analysis:
✅ In-scope? Yes (contact list in PRD)
✅ Fixable? Yes (probably missing initialization)
✅ Low-risk? Yes (clear root cause)

Decision: CREATE FIX-IT
Worker: backend-solutions-engineer
Time: <5 minutes
```

### Example 2: Complex Gap

```
Gap Found: API returns {user_id: 123} but test expects {user_id: 123, email: '...'}

Analysis:
✅ In-scope? Yes (user object contract)
❌ Fixable? Requires decision: Include email in response or not?
  - Changes API signature
  - Affects all downstream callers
  - May violate privacy constraints

Decision: ESCALATE
Reason: Architectural decision needed
Escalation: "User should clarify: Should user object include email?
This impacts API contract and all consumers."
```

### Example 3: Cascade

```
Gap 1: Missing import A
→ Fix, re-validate

Gap 2: Mock returns wrong structure
→ Fix, re-validate

Gap 3: Response missing field B
→ Fix, re-validate

Gap 4: Field B type mismatch
→ Depth = 4, STOP

Decision: ESCALATE
Reason: "Cascade detected. Escalating for root cause analysis of
API contract vs mock setup."
```

---

## When to Seek User Input (Escalation Triggers)

Check this list before deciding to escalate:

- **[ ] Ambiguity**: Could the fix be interpreted two different ways?
- **[ ] Design**: Does fixing this require a UX/design decision?
- **[ ] Architecture**: Would this change impact other components?
- **[ ] Scope**: Is this truly in the PRD requirements?
- **[ ] Risk**: Could this fix break an untested feature?
- **[ ] Policy**: Does this violate company/project policies?
- **[ ] Cascade**: Have we exceeded 3 iterations of fixes?
- **[ ] Time**: Would this fix take >30 minutes?

If ANY of these is true, escalate with clear evidence.
