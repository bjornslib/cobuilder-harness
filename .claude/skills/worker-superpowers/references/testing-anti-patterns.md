---
title: "Testing Anti-Patterns"
status: active
type: reference
---

# Testing Anti-Patterns

Common mistakes that undermine test reliability. Workers should avoid these during TDD cycles.

---

## 1. Testing Implementation Instead of Behavior

**Wrong**: Testing that a specific internal function is called.
**Right**: Testing that the observable output matches expectations.

## 2. Test-After Development

Writing tests after code tests what you built, not what was required. Always write the test FIRST (RED phase).

## 3. Flaky Tests

Tests that sometimes pass/fail without code changes. Caused by time dependencies, shared state, or external calls. Fix: Isolate each test, mock external services, use deterministic time.

## 4. Test Interdependence

Tests that depend on execution order. Fix: Each test sets up and tears down its own state.

## 5. Overly Complex Setup

When setup is longer than the test, the code under test may be too complex. Simplify dependencies.

## 6. Ignoring Edge Cases

Only testing the happy path. For each function, test: normal inputs, boundary values, invalid inputs, error conditions.

## 7. Snapshot Tests as Primary Tests

Snapshots are brittle and don't verify correctness. Use for regression detection only.

## 8. Mocking Everything

Over-mocking hides integration issues. Mock at system boundaries only.

## 9. Not Running Tests Before Committing

Always run the full test suite before committing.

## 10. The Invisible Test

A test that passes regardless of whether the feature works (missing await, incorrect assertions). Every RED phase must confirm actual FAILURE.
