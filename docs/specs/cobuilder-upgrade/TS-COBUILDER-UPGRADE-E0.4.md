---
title: "TS-E0.4: Fix Pre-Existing Test Failures + Coverage Improvement"
ts_id: TS-COBUILDER-UPGRADE-E0.4
prd_ref: PRD-COBUILDER-UPGRADE-001
epic: E0.4
status: draft
type: reference
created: 2026-03-14
last_verified: 2026-03-14
grade: authoritative
---

# TS-COBUILDER-UPGRADE-E0.4: Fix Pre-Existing Test Failures + Coverage Improvement

## 1. Overview

E0.4 resolves 195 pre-existing test failures across 8 root cause categories and improves test coverage from the current 68% baseline toward 80%+. This is a foundation epic: broken tests mask regressions in all subsequent phases. E1 and E2 must not begin until E0.4 is complete and the suite is green.

**Current state**: 195 failures across 6,400+ tests; coverage at 68%
**Target state**: 0 failures; coverage ≥75% (stretch: 80%)

**Dependency chain**: E0.1 (merge) → E0.2 (Logfire) → E0.3 (coverage baseline) → **E0.4** → E1 → E2

## 2. Failure Inventory

### 2.1 Summary by Category

| # | Category | Failures | Complexity | Parallel Group |
|---|----------|----------|------------|----------------|
| 1 | Node `handler` attribute error | 62 | Trivial | A |
| 2 | Missing completion-state scripts | 15 | Medium | D |
| 3 | Guardian signal handler definitions | 12 | Medium | B |
| 4 | Pipeline runner import + feature gaps | 10 | Complex | D |
| 5 | Event bus test isolation | 49 | Medium | C |
| 6 | Work exhaustion checker logic | 4 | Trivial | A |
| 7 | Validation rule count mismatch | 1 | Trivial | A |
| 8 | E2E and miscellaneous failures | 14 | Complex | D |
| | **Total** | **195** | | |

### 2.2 Category 1: Node `handler` Attribute Error (62 failures) — TRIVIAL

**Root cause**: Rules in `cobuilder/engine/validation/advanced_rules.py` access `node.handler` but the Node dataclass exposes `handler_type` as the correct property name. Every rule that reads `node.handler` raises `AttributeError` at validation time.

**Fix**: Find-and-replace all 8 occurrences of `node.handler` with `node.handler_type` in the file.

**Verification**:
```bash
grep -n "node\.handler[^_]" cobuilder/engine/validation/advanced_rules.py
# Must return 0 results after fix
pytest tests/engine/validation/ -v
```

**Files**: `cobuilder/engine/validation/advanced_rules.py`

### 2.3 Category 2: Missing Completion-State Scripts (15 failures) — MEDIUM

**Root cause**: Tests in `tests/completion-state/test_cs_workflow.py` invoke CLI scripts expected at `scripts/completion-state/` (e.g. `cs-init`, `cs-complete`, `cs-status`). These scripts either do not exist or are not on the test PATH.

**Fix options** (choose one per test-by-test investigation):
- If the scripts exist but the test PATH is wrong: fix the test fixture to set `PATH` correctly.
- If the scripts genuinely do not exist: add `pytest.importorskip` / `skipif` guards so tests skip gracefully when the scripts are absent, with a clear skip message.
- If the scripts should exist: implement the minimal stubs needed to satisfy the test contract.

**Investigation command**:
```bash
ls scripts/completion-state/ 2>/dev/null || echo "directory missing"
python -m pytest tests/completion-state/test_cs_workflow.py -v --no-header 2>&1 | head -60
```

**Files**: `tests/completion-state/test_cs_workflow.py`, `scripts/completion-state/` (create if needed)

### 2.4 Category 3: Guardian Signal Handler Definitions (12 failures) — MEDIUM

**Root cause**: Tests in `tests/attractor/test_guardian_agent.py` assert that the guardian system prompt builder produces output containing specific signal handler type names (e.g. `impl_complete`, `validated`, `requeue`). The current `guardian.py` prompt builder omits some of these names.

**Fix**: Audit the expected handler names in the failing tests, then add the missing names to the guardian prompt builder. Do not remove any existing handler names — this is an additive fix only.

**Investigation command**:
```bash
python -m pytest tests/attractor/test_guardian_agent.py -v 2>&1 | grep FAILED
grep -n "handler" tests/attractor/test_guardian_agent.py | head -40
```

**Files**: `cobuilder/attractor/guardian.py`, `tests/attractor/test_guardian_agent.py`

### 2.5 Category 4: Pipeline Runner Import + Feature Gaps (10 failures) — COMPLEX

**Root cause**: Tests in `tests/test_e72_pipeline_runner.py` import from `.claude/scripts/attractor/pipeline_runner.py` (a deprecated path) rather than the canonical `cobuilder/attractor/pipeline_runner.py`. Additionally, some tests expect classes or symbols (`_SignalFileHandler`, watchdog integration) that either do not exist in the canonical module or have different names.

**Fix procedure**:
1. Update all import statements in the test file to point at `cobuilder.attractor.pipeline_runner`.
2. For each test that then fails due to a missing symbol: determine whether (a) the symbol exists under a different name in the canonical module (rename the test reference) or (b) the feature is genuinely absent (mark the test `xfail` with a tracking comment referencing E2).
3. Do not stub out or mock missing functionality to make tests pass artificially — if a feature is absent, it should be `xfail`, not silently skipped.

**Investigation command**:
```bash
python -m pytest tests/test_e72_pipeline_runner.py -v 2>&1 | head -80
grep -n "from\|import" tests/test_e72_pipeline_runner.py | head -20
```

**Files**: `tests/test_e72_pipeline_runner.py`

### 2.6 Category 5: Event Bus Test Isolation (49 failures) — MEDIUM

**Root cause**: Tests in `tests/unit/test_engine_events/` pass when run individually but fail in a full suite run. This is classic async state pollution: shared event loop state, logfire mock setup leaking between test sessions, or event bus subscribers accumulating across tests.

**Fix procedure**:
1. Audit `conftest.py` in `tests/unit/test_engine_events/` — ensure each async test gets a fresh event loop via `@pytest.fixture(loop_scope="function")` or the `anyio` backend fixture.
2. Add explicit teardown to every fixture that registers event bus subscribers: call `bus.unsubscribe_all()` or equivalent in the fixture's `yield`/`finally` block.
3. Ensure logfire mocking (`CaptureLogfire`) is scoped to `function` (not `session` or `module`) to prevent span accumulation.
4. Run the full suite (not just these 5 files) after each change to catch cross-module pollution.

**Investigation command**:
```bash
# Run individually (should pass)
pytest tests/unit/test_engine_events/ -v

# Run in full suite context (exposes failures)
pytest tests/ -v -k "test_engine_events" 2>&1 | grep -E "FAILED|ERROR"
```

**Files**: `tests/unit/test_engine_events/` (5 test files), `tests/unit/test_engine_events/conftest.py` (create if absent)

### 2.7 Category 6: Work Exhaustion Checker Logic (4 failures) — TRIVIAL

**Root cause**: `tests/hooks/test_work_exhaustion_checker.py` asserts `result.passed == False` for certain edge cases, but the implementation in `.claude/hooks/unified_stop_gate/work_exhaustion_checker.py` returns `True` for those cases.

**Fix procedure**:
1. Read the test intent: is the test correct (the checker should fail on these inputs) or is the test wrong (the checker behaviour is correct)?
2. If the checker logic is wrong: fix the implementation to correctly identify exhausted work.
3. If the test expectation is wrong: update the assertion to match the correct behaviour and add a comment explaining why `True` is the right return value for that edge case.

**Files**: `tests/hooks/test_work_exhaustion_checker.py`, `.claude/hooks/unified_stop_gate/work_exhaustion_checker.py`

### 2.8 Category 7: Validation Rule Count Mismatch (1 failure) — TRIVIAL

**Root cause**: `tests/engine/validation/test_validator.py` line 149 hardcodes `assert len(rules) == 13`, but the validator now has 20 rules following Epic 5 additions.

**Fix**: Update the assertion from `13` to `20`.

**Verification**:
```bash
python -c "from cobuilder.engine.validation.validator import Validator; print(len(Validator().rules))"
# Must print 20
```

**Files**: `tests/engine/validation/test_validator.py`

### 2.9 Category 8: E2E and Miscellaneous Failures (14 failures) — COMPLEX

**Root cause**: Mixed bag — missing parser imports, SDK dispatch expectation mismatches, signal protocol divergences between tests and implementation. Each failure requires individual diagnosis.

**Fix procedure**: Investigate each failing test individually. For each failure:
- If the test references a removed or renamed symbol: update the reference.
- If the test assumes a signal format that has changed: update the test fixture to match the current protocol (documented in `SD-DASHBOARD-AUDIT-001.md`).
- If the test is testing behaviour that genuinely no longer exists: mark `xfail` with a reference to the epic that removed it.
- Do not delete tests without a comment explaining why.

**Investigation command**:
```bash
pytest tests/e2e/ tests/attractor/ -v 2>&1 | grep -E "FAILED|ImportError|AttributeError" | head -40
```

**Files**: `tests/e2e/`, `tests/attractor/`

## 3. Execution Strategy

E0.4 is split across 4 parallel codergen nodes in a DOT pipeline. Each node is preceded by a `research` node that investigates the exact failures before writing any code, and followed by a `wait.cobuilder` validation gate.

### 3.1 Parallel Group Map

```
research_trivial  ──► codergen_trivial  ──► wait_trivial
research_guardian ──► codergen_guardian ──► wait_guardian
research_events   ──► codergen_events   ──► wait_events
research_complex  ──► codergen_complex  ──► wait_complex
                                              │
                                              ▼
                                       coverage_improvement
                                              │
                                              ▼
                                       wait.cobuilder (final gate)
```

### 3.2 Group A: Trivial Fixes (Cat 1 + Cat 6 + Cat 7)

**Target failures**: 67 (62 + 4 + 1)
**Worker type**: `tdd-test-engineer`
**Estimated effort**: 1–2 hours

**Research node**: Run the three investigation commands from Sections 2.2, 2.7, 2.8. Confirm exact occurrence counts match expectations. Note any surprises.

**Codergen node tasks**:
1. Replace 8 occurrences of `node.handler` with `node.handler_type` in `advanced_rules.py`
2. Update rule count assertion from 13 to 20 in `test_validator.py`
3. Resolve work exhaustion checker logic/test mismatch

**Acceptance**: `pytest tests/engine/validation/ tests/hooks/test_work_exhaustion_checker.py -v` — 0 failures.

### 3.3 Group B: Validation and Guardian (Cat 3 + Cat 4 partial)

**Target failures**: ~22 (12 + up to 10)
**Worker type**: `backend-solutions-engineer`
**Estimated effort**: 2–3 hours

**Research node**: Identify the exact set of missing signal handler names. Map deprecated import paths to canonical paths in the pipeline runner test file.

**Codergen node tasks**:
1. Add missing signal handler names to `guardian.py` prompt builder
2. Update import paths in `tests/test_e72_pipeline_runner.py`
3. Mark genuinely absent features as `xfail` with tracking comments

**Acceptance**: `pytest tests/attractor/test_guardian_agent.py tests/test_e72_pipeline_runner.py -v` — 0 unexpected failures (xfail allowed).

### 3.4 Group C: Event Bus Isolation (Cat 5)

**Target failures**: 49
**Worker type**: `tdd-test-engineer`
**Estimated effort**: 3–4 hours (async fixtures require care)

**Research node**: Identify which fixtures are missing teardown. Check if a `conftest.py` exists in `tests/unit/test_engine_events/`. Determine the async backend in use (`asyncio` vs `anyio`).

**Codergen node tasks**:
1. Create or update `tests/unit/test_engine_events/conftest.py` with proper async lifecycle fixtures
2. Add `yield`/`finally` teardown to every event bus subscriber fixture
3. Scope `CaptureLogfire` fixtures to `function`
4. Verify tests pass in both isolated and full-suite context

**Acceptance**: `pytest tests/unit/test_engine_events/ -v` passes; `pytest tests/ -v -k "test_engine_events"` also passes.

### 3.5 Group D: E2E, Pipeline, and Completion-State (Cat 2 + Cat 4 remainder + Cat 8)

**Target failures**: ~57 (15 + remaining Cat 4 + 14)
**Worker type**: `backend-solutions-engineer`
**Estimated effort**: 4–6 hours (most complex group)

**Research node**: Run `pytest tests/e2e/ tests/completion-state/ -v` and catalogue each failure type. Check `scripts/completion-state/` existence. Identify signal protocol mismatches.

**Codergen node tasks**:
1. Fix or skip completion-state tests based on script availability
2. Update E2E test fixtures for current signal protocol
3. Fix parser import errors in E2E suite
4. Mark genuinely obsolete tests as `xfail` with comments

**Acceptance**: `pytest tests/e2e/ tests/completion-state/ tests/attractor/ -v` — 0 unexpected failures.

## 4. Coverage Improvement

Once all 4 parallel groups are complete and the gate passes, a final `coverage_improvement` node runs:

1. Measure current coverage: `pytest --cov=cobuilder --cov-report=term-missing tests/ -q`
2. Identify the lowest-coverage modules from E0.3's gap backlog (Section 5.2 of TS-E0)
3. Add unit tests for the highest-priority uncovered paths, focusing on:
   - `cobuilder/engine/handlers/` (currently ~10%)
   - `cobuilder/attractor/pipeline_runner.py` (unknown baseline)
4. Re-measure and confirm ≥75% overall coverage

**Coverage does not gate E0.4 completion.** The 0-failure gate gates E0.4 completion. Coverage improvement is a best-effort task within the same epic.

## 5. Success Criteria

| Criterion | Measurement | Target |
|-----------|------------|--------|
| Test failures | `pytest tests/ -v \| grep FAILED \| wc -l` | 0 |
| Total passing | `pytest tests/ -q \| tail -1` | ≥6,400 |
| Overall coverage | `pytest --cov=cobuilder -q \| grep TOTAL` | ≥75% |
| No regressions | Compare against E0.3 baseline | 0 new failures |
| xfail tracking | All xfail have epic reference comments | 100% |

## 6. Dependencies

| This Epic | Depends On | Relationship |
|-----------|-----------|-------------|
| E0.4 | E0.1 | Requires merged codebase |
| E0.4 | E0.2 | Logfire fixtures must be stable before fixing event bus isolation |
| E0.4 | E0.3 | Coverage baseline required to measure improvement |
| E1 | E0.4 | Must not start until suite is green |
| E2 | E0.4 | Must not start until suite is green |

## 7. Risks

| Risk | Mitigation |
|------|-----------|
| Event bus fixes alter async behaviour in production code | Fix only test fixtures and teardown; do not modify production event bus code unless a genuine bug is confirmed |
| Pipeline runner test changes mask real bugs | Preserve tests that verify canonical module behaviour; only update import paths and mark obsolete symbols as `xfail` — never delete test assertions |
| Coverage improvement introduces flaky tests | Each new test must pass in both isolated and full-suite context before merge |
| Cat 8 investigation reveals more root causes | Group D research node must complete before codergen node starts; if new categories emerge, create sub-tasks under Group D rather than expanding scope |
| Trivial fixes interact unexpectedly | Run Group A in isolation first; its failures are mechanical and should not affect other groups |
