---
title: "Logfire Span Catalog — cobuilder E0.2 Audit"
status: draft
type: reference
grade: reference
last_verified: 2026-03-14
---

# Logfire Span Catalog

Audit completed as part of E0.2 (Logfire Observability Preservation).
All spans listed below were found in the merged codebase at commit time.

## Summary

| Layer | Files | Import Pattern | Span Count |
|-------|-------|---------------|------------|
| Engine runner | `cobuilder/engine/runner.py` | Defensive (`_LOGFIRE_AVAILABLE`) | 2 |
| Engine middleware | `cobuilder/engine/middleware/logfire.py` | Defensive (`_LOGFIRE_AVAILABLE`) | 1 per-node (dynamic) |
| Engine events | `cobuilder/engine/events/logfire_backend.py` | Defensive (`_LOGFIRE_AVAILABLE`) | 2 (dynamic pipeline/node names) |
| Dispatch pipeline runner | `cobuilder/attractor/pipeline_runner.py` | Defensive (`_LOGFIRE_AVAILABLE`) | 3 spans + multiple `logfire.info()` |
| Dispatch guardian | `cobuilder/attractor/guardian.py` | Direct (`import logfire`) | 4 |
| Dispatch session runner | `cobuilder/attractor/session_runner.py` | Direct (`import logfire`) | 9 |

**Key finding**: Engine layer uses defensive imports; dispatch layer (attractor/) uses direct imports.
The dispatch layer **will crash** if logfire is missing. Adding `logfire>=2.0` to hard dependencies
(done in this E0.2 task) resolves this inconsistency.

---

## Engine Layer (Defensive Import Pattern)

### `cobuilder/engine/runner.py`

Import block (lines 116–122):
```python
try:
    import logfire as _logfire
    _LOGFIRE_AVAILABLE = True
except ImportError:
    _logfire = None
    _LOGFIRE_AVAILABLE = False
```

| Line | Span Name | Attributes | Type |
|------|-----------|------------|------|
| 407 | `pipeline.run` | `pipeline_id` | Pipeline lifecycle |
| 478 | `node.execute` | `node_id`, `handler_type` | Per-node execution |

Both spans are constructed as context managers using the low-level `__enter__`/`__exit__` API
(not the `with` statement) to work inside an async traversal loop.

---

### `cobuilder/engine/middleware/logfire.py`

Import block (lines 27–34):
```python
try:
    import logfire as _logfire
    _LOGFIRE_AVAILABLE = True
except ImportError:
    _logfire = None
    _LOGFIRE_AVAILABLE = False
```

| Line | Span Name | Attributes | Type |
|------|-----------|------------|------|
| 100 | `handler.{node_id}` (default template) | `node_id`, `handler_type`, `visit_count`, `outcome_status`, `duration_ms`, `tokens_used`, `goal_gate` | Per-node handler timing |

The span name is controlled by `span_name_template` parameter (default: `"handler.{node_id}"`).
Falls back to `_NullSpan()` context manager when logfire is unavailable — events are still
emitted via the event bus even in no-op span mode.

---

### `cobuilder/engine/events/logfire_backend.py`

Import block (lines 26–31):
```python
try:
    import logfire as _logfire
    _LOGFIRE_AVAILABLE = True
except ImportError:
    _logfire = None
    _LOGFIRE_AVAILABLE = False
```

| Line | Span Name | Attributes | Type |
|------|-----------|------------|------|
| 101 | `pipeline.{pipeline_id}` | `pipeline_id`, `dot_path`, `node_count`, `duration_ms`, `total_tokens`, `outcome_status` | Event bus pipeline span |
| 144 | `node.{node_id}` | `node_id`, `handler_type`, `visit_count`, `outcome_status`, `duration_ms`, `tokens_used`, `goal_gate` | Event bus node span |

Span names are controlled by `SpanConfig.pipeline_span_name` and `SpanConfig.node_span_name`
(defaults: `"pipeline.{pipeline_id}"` and `"node.{node_id}"`).

`aclose()` method (line 227) closes all open spans on pipeline teardown.

---

## Dispatch Layer (Direct Import Pattern)

### `cobuilder/attractor/guardian.py`

Direct import (line 76): `import logfire`

| Line | Span Name | Attributes | Type |
|------|-----------|------------|------|
| 137 | `guardian.build_system_prompt` | `pipeline_id` | Guardian prompt construction |
| 384 | `guardian.build_initial_prompt` | `pipeline_id` | Guardian initial prompt |
| 422 | `guardian.build_options` | `model` | Agent options construction |
| 562 | `guardian.run_agent` | (captures span as `agent_span`) | Guardian agent execution |

All four use the `with logfire.span(...) as span:` pattern.
`guardian.run_agent` additionally logs multiple `logfire.info()` events for message streaming.

---

### `cobuilder/attractor/session_runner.py`

Direct import (line 96): `import logfire`

| Line | Span Name | Attributes | Type |
|------|-----------|------------|------|
| 183 | `runner.build_system_prompt` | `node_id`, `prd_ref` | Session prompt construction |
| 350 | `runner.build_initial_prompt` | `node_id`, `prd_ref` | Session initial prompt |
| 387 | `runner.build_options` | `model` | Session options construction |
| 412 | `runner.build_worker_system_prompt` | `node_id`, `prd_ref` | Worker system prompt |
| 448 | `runner.build_worker_initial_prompt` | `node_id`, `prd_ref` | Worker initial prompt |
| 526 | `runner.build_worker_options` | `model` | Worker options |
| 696 | `runner.build_monitor_prompt` | `node_id`, `session_name` | Monitor prompt construction |
| 942 | `runner.run_agent` | (captures span as `agent_span`) | Session agent execution |
| 1201 | `runner.main` | `node_id`, `prd_ref` | Session entry point |

`runner.run_agent` and `runner.main` additionally emit multiple `logfire.info()` events
for streaming messages, tool use blocks, and result captures.

---

### `cobuilder/attractor/pipeline_runner.py`

Import block (lines 103–110) — defensive despite dispatch layer conventions:
```python
try:
    import logfire
    logfire.configure(scrubbing=False)
    _LOGFIRE_AVAILABLE = True
except ImportError:
    logfire = None
    _LOGFIRE_AVAILABLE = False
```

Note: This file calls `logfire.configure(scrubbing=False)` on import — the only file to do so.

| Line | Span Name | Attributes | Type |
|------|-----------|------------|------|
| 425–430 | `pipeline_runner {pipeline_id}` | `pipeline_id`, `dot_path`, `resume` | Top-level pipeline runner span |
| 858 | `tool {node_id}` | `node_id`, `command` (truncated 200) | Tool node subprocess execution |
| 976–981 | `sdk_worker {node_id} ({worker_type})` | `node_id`, `worker_type`, `model`, `cwd`, `sdk_version` | AgentSDK worker dispatch |
| 1471–1474 | `validation_agent {node_id}` | `node_id`, `target_node_id` | Validation subprocess dispatch |

Additional `logfire.info()` calls (not spans) for real-time visibility:
- `dispatch_worker {node_id}` (line 820)
- `tool PASS` / `tool FAIL exit={rc}` (lines 877, 884)
- `worker_first_message {node_id}` (lines 1178, 1532)
- `worker_tool {node_id} {tool}` (lines 1187, 1541)
- `worker_text {node_id}` (lines 1193, 1547)
- `worker_dispatch_start {node_id}` (lines 1217)
- `worker_complete {node_id} {status} in {elapsed_s}s` (line 1250)
- `validation_dispatch {node_id}` (line 1494)
- `validation_complete {node_id} {result}` (line 1598)
- `signal {node_id} → {signal_status}` (line 1746)

---

## Complete Span Name Registry

All distinct span names (not logfire.info logs) across the merged codebase:

| Span Name | Source File | Import Pattern | Notes |
|-----------|-------------|---------------|-------|
| `pipeline.run` | engine/runner.py | Defensive | Static name |
| `node.execute` | engine/runner.py | Defensive | Static name |
| `handler.{node_id}` | engine/middleware/logfire.py | Defensive | Template; default prefix `handler.` |
| `pipeline.{pipeline_id}` | engine/events/logfire_backend.py | Defensive | Template via SpanConfig |
| `node.{node_id}` | engine/events/logfire_backend.py | Defensive | Template via SpanConfig |
| `guardian.build_system_prompt` | attractor/guardian.py | Direct | Static name |
| `guardian.build_initial_prompt` | attractor/guardian.py | Direct | Static name |
| `guardian.build_options` | attractor/guardian.py | Direct | Static name |
| `guardian.run_agent` | attractor/guardian.py | Direct | Static name |
| `runner.build_system_prompt` | attractor/session_runner.py | Direct | Static name |
| `runner.build_initial_prompt` | attractor/session_runner.py | Direct | Static name |
| `runner.build_options` | attractor/session_runner.py | Direct | Static name |
| `runner.build_worker_system_prompt` | attractor/session_runner.py | Direct | Static name |
| `runner.build_worker_initial_prompt` | attractor/session_runner.py | Direct | Static name |
| `runner.build_worker_options` | attractor/session_runner.py | Direct | Static name |
| `runner.build_monitor_prompt` | attractor/session_runner.py | Direct | Static name |
| `runner.run_agent` | attractor/session_runner.py | Direct | Static name |
| `runner.main` | attractor/session_runner.py | Direct | Static name |
| `pipeline_runner {pipeline_id}` | attractor/pipeline_runner.py | Defensive | Template; uses logfire `{}` syntax |
| `tool {node_id}` | attractor/pipeline_runner.py | Defensive | Template; uses logfire `{}` syntax |
| `sdk_worker {node_id} ({worker_type})` | attractor/pipeline_runner.py | Defensive | Template; uses logfire `{}` syntax |
| `validation_agent {node_id}` | attractor/pipeline_runner.py | Defensive | Template; uses logfire `{}` syntax |

**Total distinct span names**: 22 (10 static, 12 templated)

---

## E2 Migration Notes

When E2 renames `cobuilder/attractor/` to `cobuilder/engine/dispatch/` (or similar):

1. All direct `import logfire` calls in guardian.py and session_runner.py are correct — keep them.
2. Convert the engine layer's `_LOGFIRE_AVAILABLE` defensive imports to direct `import logfire`
   (this is safe once logfire is a hard dependency, which E0.2 establishes).
3. The `logfire.configure(scrubbing=False)` call in pipeline_runner.py should be reviewed —
   it may belong in the application entry point rather than in the module body.
4. All 22 span names listed above must be preserved through the rename.

---

## Test Fixtures

- **`capture_logfire` fixture**: `tests/conftest.py` — root-level, available in all test modules.
  Inspect spans via `capture_logfire.exporter.exported_spans_as_dict()` which returns a list of
  dicts with a `"name"` key.
- **`capfire` fixture**: Provided automatically by logfire's pytest plugin when logfire is installed.
  Equivalent to `capture_logfire` — both use `TestExporter` internally.
- **Example span assertion test**: `tests/engine/test_logfire_spans.py`
