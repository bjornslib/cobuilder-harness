---
title: "Testing Anti-Patterns"
status: active
type: reference
---

# Testing Anti-Patterns

Common mistakes that undermine test reliability, adapted from the superpowers methodology. Workers should avoid these patterns during TDD cycles.

---

## Anti-Pattern 1: Testing Implementation Instead of Behavior

**Wrong**: Testing that a specific function is called with specific arguments.
**Right**: Testing that the observable output matches expectations for given inputs.

```python
# WRONG — tests implementation detail
def test_save_user():
    mock_db = Mock()
    save_user(mock_db, user)
    mock_db.insert.assert_called_once_with("users", user.dict())

# RIGHT — tests behavior
def test_save_user():
    save_user(db, user)
    assert get_user(db, user.id) == user
```

## Anti-Pattern 2: Test-After Development

Writing tests after the code is written. This tests what you built, not what was required. The test will always pass because it was written to match existing code.

**Fix**: Always write the test FIRST (RED phase). If you forgot, delete the implementation and start over with the test.

## Anti-Pattern 3: Flaky Tests

Tests that sometimes pass and sometimes fail without code changes. Usually caused by:
- Time-dependent assertions
- Shared mutable state between tests
- Network calls to external services
- Race conditions in async code

**Fix**: Isolate each test completely. Mock external services. Use deterministic time. Reset state between tests.

## Anti-Pattern 4: Test Interdependence

Tests that depend on execution order or state from previous tests.

**Fix**: Each test must set up its own state and tear it down. Run tests in random order to catch this.

## Anti-Pattern 5: Overly Complex Test Setup

When test setup is longer than the test itself, the code under test may be too complex.

**Fix**: Simplify the code's dependencies. Use builder patterns or fixtures for complex objects.

## Anti-Pattern 6: Ignoring Edge Cases

Only testing the happy path.

**Fix**: For each function, test:
- Normal inputs (happy path)
- Boundary values (empty, zero, max)
- Invalid inputs (null, wrong type)
- Error conditions (network failure, timeout)

## Anti-Pattern 7: Snapshot Tests as Primary Tests

Using snapshot tests instead of behavior tests. Snapshots are brittle and don't verify correctness.

**Fix**: Use snapshots only for regression detection. Primary tests should assert specific behaviors.

## Anti-Pattern 8: Mocking Everything

Over-mocking hides integration issues. If everything is mocked, tests prove nothing about real behavior.

**Fix**: Mock at system boundaries (external APIs, databases). Test internal logic with real objects.

## Anti-Pattern 9: Not Running Tests Before Committing

Assuming tests pass because they passed earlier.

**Fix**: Always run the full test suite before committing. Automate this with pre-commit hooks.

## Anti-Pattern 10: The Invisible Test

A test that passes regardless of whether the feature works. Usually caused by incorrect assertions or missing await.

```python
# WRONG — always passes (missing await, async assertion ignored)
async def test_fetch_data():
    fetch_data()  # Missing await — never actually runs

# RIGHT
async def test_fetch_data():
    result = await fetch_data()
    assert result.status == 200
```

**Fix**: Every RED phase must confirm the test actually FAILS before implementation.
