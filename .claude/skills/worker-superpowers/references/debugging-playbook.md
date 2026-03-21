---
title: "Systematic Debugging Playbook"
status: active
type: reference
---

# Systematic Debugging Playbook

Extended scenarios and solutions for the systematic debugging power. Use when the 7-step protocol in the main skill needs more detail.

---

## Scenario 1: Test Passes Locally, Fails in CI

### Investigation

1. Check environment differences (Node version, Python version, OS)
2. Check for `.env` files or environment variables present locally but not in CI
3. Check for file system dependencies (paths, permissions, temp files)
4. Check for timing-sensitive tests (CI is often slower)

### Common Causes

| Cause | Fix |
|-------|-----|
| Different dependency versions | Lock files (`package-lock.json`, `poetry.lock`) |
| Missing env vars | Add to CI config, use `.env.example` |
| File path differences | Use `os.path.join()` or `path.resolve()` |
| Timezone differences | Use UTC everywhere, mock time in tests |

---

## Scenario 2: Import/Module Not Found

### Investigation

1. Check the file actually exists at the expected path
2. Check for typos in the import statement
3. Check `__init__.py` files (Python) or `index.ts` exports
4. Check `tsconfig.json` paths or `package.json` exports field

### Root Cause Pattern

```
Error: Cannot find module './components/UserProfile'
  → File is actually at './components/user-profile' (case mismatch)
  → macOS is case-insensitive (works locally), Linux is case-sensitive (fails in CI)
```

---

## Scenario 3: Async/Await Issues

### Symptoms

- Test passes but assertion doesn't seem to run
- "Promise { <pending> }" in output
- Intermittent timeouts

### Investigation

1. Check every async function has `await` at call sites
2. Check test framework is configured for async tests
3. Check for fire-and-forget promises (no await, no .catch)

### Fix Pattern

```python
# Find all async calls missing await
grep -rn "async def" src/ | # Find async functions
  while read line; do
    func=$(echo "$line" | grep -o "def [a-z_]*")
    grep -rn "${func#def }(" src/ | grep -v "await"  # Calls without await
  done
```

---

## Scenario 4: Database State Leaks

### Symptoms

- Tests pass individually, fail when run together
- Order-dependent test failures
- "Unique constraint violation" errors in clean tests

### Investigation

1. Check test fixtures for proper cleanup (teardown/afterEach)
2. Check for shared database connections without transactions
3. Check for hardcoded IDs that collide

### Fix Pattern

```python
# Use transactions that rollback after each test
@pytest.fixture(autouse=True)
def db_session(db):
    session = db.begin_nested()
    yield session
    session.rollback()
```

---

## Scenario 5: React Component Not Rendering

### Symptoms

- `screen.getByText()` throws "Unable to find element"
- Component renders empty
- Wrong content displayed

### Investigation

1. Check props being passed match expected types
2. Check conditional rendering logic (`{condition && <Component />}`)
3. Check async data loading (component may render before data arrives)
4. Use `screen.debug()` to see actual DOM output

### Fix Pattern

```javascript
// Wait for async content
await waitFor(() => {
    expect(screen.getByText('Expected Content')).toBeInTheDocument();
});
```

---

## Scenario 6: API Endpoint Returns Wrong Status

### Symptoms

- 500 instead of 400 for validation errors
- 200 instead of 201 for creation
- 404 for routes that exist

### Investigation

1. Check route registration (order matters — catch-all routes swallow specific ones)
2. Check middleware (auth middleware might reject before reaching handler)
3. Check error handling (unhandled exceptions become 500s)
4. Add request logging to see what the server receives

---

## The Debugging Decision Tree

```
Test fails
    ├─ Error message is clear
    │   └─ Fix the specific issue → Verify → Done
    │
    ├─ Error is cryptic or misleading
    │   ├─ Add diagnostic logging at key points
    │   ├─ Reproduce with minimal input
    │   └─ Binary search: comment out code until error disappears
    │
    ├─ Works locally, fails elsewhere
    │   ├─ Environment difference (see Scenario 1)
    │   └─ Data/state difference
    │
    └─ Intermittent failure
        ├─ Race condition (add delays to confirm, then fix properly)
        ├─ Shared state (isolate tests)
        └─ External dependency (mock it)
```

---

## Key Principle

**Understand before you fix.** The goal is not to make the error go away — it is to understand WHY the error occurs. Fixes that suppress symptoms without addressing root causes create harder bugs later.
