---
title: "Systematic Debugging Playbook"
status: active
type: reference
---

# Systematic Debugging Playbook

Extended scenarios for the 7-step debugging protocol.

---

## Scenario 1: Works Locally, Fails in CI

Check: env var differences, dependency version mismatches, file path case sensitivity (macOS vs Linux), timezone differences.

## Scenario 2: Import/Module Not Found

Check: file exists at expected path, typos in import, `__init__.py` files, `tsconfig.json` paths, case sensitivity.

## Scenario 3: Async/Await Issues

Symptoms: test passes but assertion doesn't run, `Promise { <pending> }`, intermittent timeouts.
Check: every async function has `await` at call sites, fire-and-forget promises.

## Scenario 4: Database State Leaks

Symptoms: tests pass individually, fail together; order-dependent failures.
Fix: Use transaction rollback fixtures, avoid hardcoded IDs.

## Scenario 5: React Component Not Rendering

Check: props match expected types, conditional rendering logic, async data loading.
Use `screen.debug()` and `waitFor()`.

## Scenario 6: API Returns Wrong Status

Check: route registration order, middleware rejection, unhandled exceptions becoming 500s.

---

## Decision Tree

```
Test fails
  ├─ Clear error message → Fix directly → Verify
  ├─ Cryptic error → Add diagnostics → Binary search code
  ├─ Works locally, fails elsewhere → Environment diff
  └─ Intermittent → Race condition or shared state
```

**Key Principle**: Understand before you fix.
