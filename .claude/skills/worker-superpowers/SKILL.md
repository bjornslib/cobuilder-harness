---
name: worker-superpowers
description: This skill should be used when a worker needs to "debug a failing test", "trace root cause", "follow TDD workflow", "verify before completion", "brainstorm approach", "use systematic debugging", "use superpowers", or when any pipeline worker needs access to structured development powers. Bundles the superpowers methodology (test-driven development, systematic debugging, verification, brainstorming) adapted for CoBuilder pipeline workers.
version: 1.0.0
title: "Worker Superpowers"
status: active
type: skill
last_verified: 2026-03-21
grade: authoritative
---

# Worker Superpowers

Structured development powers for CoBuilder pipeline workers, adapted from the [superpowers](https://github.com/obra/superpowers) methodology. These powers enforce disciplined development practices: test-first, evidence-based verification, and systematic debugging.

**Core Principle**: Never claim success without evidence. Test first, debug systematically, verify before completion.

---

## Power 1: Test-Driven Development (RED-GREEN-REFACTOR)

The foundational development cycle. Every feature starts with a failing test.

### RED Phase — Write Failing Test

1. Read the acceptance criteria from the task assignment
2. Write a test that captures the expected behavior
3. Run the test — it **MUST fail**
4. If the test passes, either the feature exists or the test is wrong

```bash
# Run the specific test
pytest tests/test_feature.py::test_new_behavior -v  # Python
npm test -- --testPathPattern="feature" --verbose     # JavaScript
```

**Anti-pattern**: Writing tests after implementation. This tests what you built, not what was required.

### GREEN Phase — Minimal Implementation

1. Write the **minimum code** to make the failing test pass
2. Do not add features beyond what the test requires
3. Run the test — it **MUST pass**
4. If it still fails, fix the implementation, not the test

**Anti-pattern**: Gold-plating during GREEN phase. Extras belong in new RED-GREEN cycles.

### REFACTOR Phase — Clean Up

1. Improve code quality while tests stay green
2. Remove duplication, improve naming, simplify logic
3. Run tests after **every change** — they must stay green
4. Do not add new functionality during refactor

**Anti-pattern**: Adding features during refactor. That is a new RED phase.

### TDD Cycle for Sub-Agents

When delegating to Haiku sub-agents, separate code and test concerns:

```
Worker (Opus) coordinates:
  RED:     Sub-agent A writes failing test
           Sub-agent B runs test, confirms failure
  GREEN:   Sub-agent C implements code
           Sub-agent D runs test, confirms pass
  REFACTOR: Sub-agent E cleans up code
            Sub-agent F runs test, confirms still passing
```

Never let the same sub-agent write both the test and the implementation.

---

## Power 2: Systematic Debugging

When a test fails unexpectedly or behavior is wrong, follow this root-cause analysis protocol instead of guessing.

### The Protocol

1. **Reproduce** — Run the failing test and capture exact error output
2. **Hypothesize** — Form 2-3 theories about the root cause based on the error
3. **Isolate** — Test each hypothesis with targeted investigation:
   - Read the specific code path
   - Add diagnostic logging or print statements
   - Check input/output at each step
4. **Identify** — Determine the actual root cause (not symptoms)
5. **Fix** — Apply the minimal fix for the root cause
6. **Verify** — Run the original failing test plus regression tests
7. **Clean up** — Remove diagnostic code, commit the fix

### Investigation Techniques

| Symptom | Investigation |
|---------|--------------|
| Test timeout | Check for infinite loops, unresolved promises, missing await |
| Wrong output | Trace data flow from input to output, check each transformation |
| Import error | Verify file paths, check exports, confirm dependencies installed |
| Type error | Check function signatures, verify argument types at call sites |
| Intermittent failure | Look for race conditions, shared mutable state, time dependencies |

### Anti-Patterns

- **Shotgun debugging**: Changing random things hoping something works
- **Blame the framework**: Assuming a library bug before checking your code
- **Fix the symptom**: Suppressing errors instead of fixing causes
- **Abandon and rewrite**: Starting over instead of understanding the failure

---

## Power 3: Verification Before Completion

**MANDATORY** before claiming any task is done. Never self-certify — produce evidence.

### Verification Checklist

1. **Run all tests** — Actually execute them, do not assume they pass

```bash
# Capture test output as evidence
pytest tests/ -v 2>&1 | tee .pipelines/evidence/task-{id}-tests.log
npm test 2>&1 | tee .pipelines/evidence/task-{id}-tests.log
```

2. **Check scope compliance** — Only scoped files should be modified

```bash
git diff --name-only | sort > /tmp/modified.txt
# Compare against task scope — flag any files outside scope
```

3. **Check for incomplete markers** — No TODO/FIXME in committed code

```bash
grep -rn "TODO\|FIXME\|HACK\|XXX" [scoped-files]
# Must return empty
```

4. **Verify git status** — Everything committed, working tree clean

```bash
git status --porcelain
# Must return empty
```

5. **Validate acceptance criteria** — Each criterion from the task must have evidence

| Criterion | Evidence | Status |
|-----------|----------|--------|
| {AC-1} | {test output / screenshot / log} | PASS/FAIL |
| {AC-2} | {test output / screenshot / log} | PASS/FAIL |

### Evidence Collection

Write verification evidence to `.pipelines/evidence/`:

```
.pipelines/evidence/
├── task-{id}-tests.log      # Test execution output
├── task-{id}-scope.txt      # Modified files list
├── task-{id}-markers.txt    # TODO/FIXME grep result
└── task-{id}-criteria.md    # Acceptance criteria evidence table
```

---

## Power 4: Brainstorming (When Approach Is Unclear)

When a task has multiple valid approaches or the path forward is uncertain.

### Workflow

1. **List 2-3 approaches** with trade-offs for each
2. **Evaluate** against criteria: simplicity, testability, scope compliance
3. **Select** the approach that is simplest and most testable
4. **Document** the decision in a code comment at the key decision point

### Decision Criteria

| Factor | Weight | Question |
|--------|--------|----------|
| Simplicity | High | Which approach has fewer moving parts? |
| Testability | High | Which is easiest to write tests for? |
| Scope | Critical | Which stays within assigned file scope? |
| Reversibility | Medium | Which is easiest to change if wrong? |

When in doubt, choose the simplest approach and validate with a test.

---

## Quick Reference

### When to Use Each Power

| Situation | Power | Action |
|-----------|-------|--------|
| Starting a new feature | TDD | Write failing test first |
| Test fails unexpectedly | Systematic Debugging | Follow the 7-step protocol |
| Task feels complete | Verification | Run the full checklist |
| Multiple valid approaches | Brainstorming | Evaluate trade-offs |
| Sub-agent failed | Systematic Debugging | Don't retry blindly — diagnose |

### Skill Invocation

Workers access these powers by loading this skill:

```
Skill("worker-superpowers")
```

Or reference specific powers in the worker-focused-execution flow:

```
Step 4: Skill("worker-superpowers") → brainstorming if approach unclear
Step 5-7: Follow RED-GREEN-REFACTOR from this skill
Step 8: Follow verification-before-completion from this skill
```

---

## Additional Resources

### Reference Files

- **`references/testing-anti-patterns.md`** — Comprehensive list of testing mistakes to avoid
- **`references/debugging-playbook.md`** — Extended systematic debugging scenarios and solutions

### Related Skills

- `worker-focused-execution` — Complete worker lifecycle (claims tasks, uses these powers)
- `ideation-to-execution` — End-to-end pipeline that configures worker powers
- `development:testing-protocol` — Testing protocol requirements
