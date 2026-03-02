---
title: "Closure Report — CoBuilder E2 Tasks #172, #173, #174"
prd: PRD-COBUILDER-E2
epic: "CoBuilder Epic 2 — Enrichment Observability, DOT Rendering, CLI Distribution"
date: 2026-02-27
status: impl_complete
agent: worker-backend
team: drifting-nibbling-oasis
---

# Closure Report: CoBuilder E2 Tasks #172, #173, #174

## Summary

Three implementation tasks completed in sequence by worker-backend in team `drifting-nibbling-oasis`. All tasks targeted the CoBuilder pipeline enrichment and rendering subsystems.

---

## Task #172 — F2.3: Enricher Observability

### Files Modified

| File | Change | Line(s) |
|------|--------|---------|
| `cobuilder/pipeline/enrichers/base.py` | Added `_warn_if_empty` method to `BaseEnricher` | ~77–86 |
| `cobuilder/pipeline/enrichers/file_scoper.py` | Added `_warn_if_empty` call after `_parse_yaml` | 48 |
| `cobuilder/pipeline/enrichers/acceptance_crafter.py` | Added `_warn_if_empty` call after `_parse_yaml` | 39 |
| `cobuilder/pipeline/enrichers/dependency_inferrer.py` | Added `_warn_if_empty` call after `_parse_yaml` | 64 |
| `cobuilder/pipeline/enrichers/worker_selector.py` | Added `_warn_if_empty` call after `_parse_yaml` | 67 |
| `cobuilder/pipeline/enrichers/complexity_sizer.py` | Added `_warn_if_empty` call after `_parse_yaml` | 52 |

### Implementation

```python
def _warn_if_empty(self, parsed: dict, required_key: str, node_title: str) -> None:
    """Log a warning if the parsed result is missing the expected key."""
    if not parsed or required_key not in parsed:
        logger.warning(
            "[%s] Enrichment returned no '%s' for node '%s' — using defaults",
            self.__class__.__name__,
            required_key,
            node_title,
        )
```

Each enricher calls `self._warn_if_empty(parsed, "<key>", node.get("title", ""))` immediately after `_parse_yaml()`.

---

## Task #173 — F2.6: DOT Rendering Fixes

### File Modified

`cobuilder/pipeline/generate.py`

### Fix 1 — Node ID Deduplication

Replaced UUID-slice suffix with module-derived suffix + counter fallback:

```python
dot_node_id = f"impl_{sanitize_node_id(title)}"
existing_ids = {t["dot_node_id"] for t in task_nodes}
if dot_node_id in existing_ids:
    module_raw = node.get("module", "") or node.get("folder_path", "") or node_id_raw[-6:]
    module_slug = sanitize_node_id(module_raw.split("/")[0])
    dot_node_id = f"impl_{sanitize_node_id(title)}_{module_slug}"
    if dot_node_id in existing_ids:
        counter = sum(1 for nid in existing_ids if nid.startswith(f"impl_{sanitize_node_id(title)}"))
        dot_node_id = f"impl_{sanitize_node_id(title)}_{module_slug}_{counter}"
```

### Fix 2 — Per-node solution_design with feature_id Fragment

```python
feature_id = task.get("feature_id", "")
if solution_design:
    sd_ref = f"{solution_design}#{feature_id}" if feature_id else solution_design
    lines.append(f'        solution_design="{escape_dot_string(sd_ref)}"')
```

---

## Task #174 — F2.8: CLI Worker Type Distribution Log

### File Modified

`cobuilder/cli.py`

### Implementation

Added immediately after `pipeline.enrich()` call (step 5):

```python
worker_types = {}
for n in nodes:
    wt = n.get("worker_type", "unknown")
    worker_types[wt] = worker_types.get(wt, 0) + 1
typer.echo(f"      Worker type distribution: {worker_types}")
```

---

## Test Evidence

### Full Test Run

```
pytest tests/ -v (excluding pre-existing broken imports)
Result: 4489 passed, 71 skipped, 20 pre-existing failures (completion-state only)
Duration: 18.79s
```

### Pipeline/Enricher Focused Run

```
pytest tests/ -k "enricher or enrich or generate or cli or pipeline or..."
Result: 637 passed, 12 skipped, 0 failed
Duration: 10.21s
```

### Pre-existing Failures (NOT caused by this work)

- `tests/completion-state/test_cs_workflow.py` — 20 failures (cs-promise CLI tooling, unrelated to pipeline)
- `tests/unit/test_benchmark_*.py` — ImportError (missing deps, pre-existing)
- `tests/decision_guidance/`, `tests/hooks/test_work_exhaustion_checker.py` — pre-existing

---

## Acceptance Criteria Coverage

| Task | Criterion | Status |
|------|-----------|--------|
| #172 | `_warn_if_empty` method exists on `BaseEnricher` | ✓ |
| #172 | All 5 enrichers call `_warn_if_empty` after `_parse_yaml` | ✓ |
| #173 | Node ID deduplication uses module-derived suffix | ✓ |
| #173 | Per-node `solution_design` includes `#feature_id` fragment | ✓ |
| #174 | CLI prints worker type distribution after enrichment | ✓ |
| All | 637 enricher/pipeline/CLI tests pass | ✓ |
