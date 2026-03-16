---
title: "SD-VALIDATOR-CONSOLIDATION-001: Pipeline Validator Consolidation"
description: "Solution design for consolidating three duplicate pipeline validator modules into one authoritative validator with a shared schema constants module"
version: "1.0.0"
last-updated: 2026-03-16
status: active
type: sd
grade: authoritative
---

# SD-VALIDATOR-CONSOLIDATION-001: Pipeline Validator Consolidation

## 1. Problem Statement

CoBuilder's pipeline validation logic is split across three separate files that have diverged over time:

| File | Lines | Status | Entry Point |
|------|-------|--------|-------------|
| `cobuilder/engine/validator.py` | ~838 | Legacy, imported by active code | `engine/cli.py` validate subcommand |
| `cobuilder/engine/validation/` | ~600 across 4 files | Active (OOP, rule-per-class) | `cobuilder/cli.py` validate subcommand (Typer) |
| `cobuilder/pipeline/validator.py` | ~300 | Stale copy | `cobuilder/pipeline/tests/` and `tests/unit/conftest.py` |

The duplicates introduce three concrete risks:

1. **Silent drift**: `pipeline/validator.py` has an outdated `VALID_STATUSES` set (missing `"accepted"`), meaning pipeline tests run against a schema that disagrees with the production runner.
2. **Constants scattered at two import sites**: `engine/node_ops.py` imports six constants from `engine/validator.py`. Any schema change (new handler type, new shape) must be made in multiple places and the inconsistency is not caught until runtime.
3. **Two active CLI surfaces** with different rule coverage. The legacy CLI (`engine/cli.py`) invokes the flat 16-rule `validate()` function; the Typer CLI (`cobuilder/cli.py`) invokes the OOP `Validator(graph).run()` with 18 rules. A pipeline that passes one may silently fail the other.

The fix is a single migration that extracts shared constants into `engine/schema.py`, routes all imports there, retires the two legacy modules, and verifies that the OOP validator covers every rule that existed in the flat validators.

---

## 2. Current Architecture

### 2.1 engine/validator.py (Legacy Flat Validator)

Flat-function design. `validate(data: dict)` iterates raw parsed dicts directly. Constants live at module scope and are imported by other engine modules.

Unique content relative to the OOP validator:

| Rule | Number | In OOP validator? |
|------|--------|-------------------|
| Exactly one Msquare (exit) | 2 | Yes — `AtLeastOneExit` |
| No unguarded cycles | 9 | Not present — needs migration |
| `promise_id` on graph if `promise_ac` exists | 10 | Not present — needs migration |
| Edge conditions valid syntax | 11 | Yes — `ConditionSyntaxValid` |
| Refine `evidence_path` cross-references upstream research | 12 | Not present — needs migration |
| `bead_id` values map to real beads (via `bd show`) | 15 | Not present — needs migration |
| Manifest `validation_method` enforcement | 16 | Not present — needs migration |

Rules 9, 10, 12, 15, and 16 exist only in the legacy flat validator and must be ported to the OOP rule system before the legacy module can be deleted.

### 2.2 engine/validation/ (Active OOP Validator)

Protocol-based design. Each rule is a stateless class with `check(graph: Graph) -> list[RuleViolation]`. The `Validator` orchestrator runs all rules and accumulates violations without early termination.

Two rule files:

- `rules.py`: 13 base rules (structural topology, type system)
- `advanced_rules.py`: 5 advanced rules (SD path enforcement, worker type registry, cluster topology, wait ordering, codergen upstream AT)

Handler notation uses underscores internally (`node.handler_type == "wait_cobuilder"`) via the `Graph.Node.handler_type` property in `graph.py`.

### 2.3 pipeline/validator.py (Stale Copy)

Diverged clone of `engine/validator.py` with a different `parse_file` import path (`from .parser import parse_file`). Missing `"accepted"` from `VALID_STATUSES`. Missing the `refine` handler in `VALID_HANDLERS`. Entry point is only test fixtures — no production code path.

### 2.4 Existing Constants Import Graph

```
engine/node_ops.py
    └── from cobuilder.engine.validator import
            VALID_HANDLERS, HANDLER_SHAPE_MAP, VALID_STATUSES,
            REQUIRED_ATTRS, VALID_WORKER_TYPES, WARNING_ATTRS

tests/attractor/test_dot_schema_extensions.py
    └── from cobuilder.engine.validator import
            validate, WARNING_ATTRS, VALID_HANDLERS, HANDLER_SHAPE_MAP, REQUIRED_ATTRS

tests/unit/conftest.py
    └── from cobuilder.pipeline.validator import validate_file  (stubbed via autouse fixture)

cobuilder/pipeline/tests/test_research_nodes.py
    └── from cobuilder.pipeline.validator import ...

engine/cli.py (line 81)
    └── from cobuilder.engine.validator import main as validator_main
```

---

## 3. Target Architecture

```
cobuilder/engine/schema.py          (NEW — single source of truth for constants)
cobuilder/engine/validation/        (ACTIVE — sole validator implementation)
    __init__.py
    validator.py                    (unchanged)
    rules.py                        (add 5 ported rules)
    advanced_rules.py               (unchanged)

DELETED:
    cobuilder/engine/validator.py
    cobuilder/pipeline/validator.py
```

`schema.py` holds every constant that was previously defined in `engine/validator.py`: `VALID_STATUSES`, `VALID_HANDLERS`, `HANDLER_SHAPE_MAP`, `VALID_CONDITIONS`, `REQUIRED_ATTRS`, `WARNING_ATTRS`, `VALID_WORKER_TYPES`, `VALID_GATE_TYPES`, `VALID_MODES`, `VALID_VALIDATION_METHODS`.

`engine/node_ops.py` and `graph.py` import constants from `schema.py`. The OOP validator imports them from `schema.py` as well. There is one definition of each constant in the codebase.

The `engine/cli.py` legacy validate subcommand is re-pointed to `Validator(graph).run()`. The Typer CLI validate path (`cobuilder/cli.py`) is unchanged.

---

## 4. Hindsight Findings

Prior sessions contain one relevant observation: circular imports were resolved by moving shared state to the module that logically owns it. This reinforces `schema.py` as the right extraction target — it is the pure-data module (no logic, no imports from within `cobuilder`) and thus cannot create circular imports.

No prior sessions contain warnings about this specific consolidation.

---

## 5. Migration Plan

### Phase 1: Extract schema.py (no behaviour change)

**Files changed**: `cobuilder/engine/schema.py` (new), `cobuilder/engine/node_ops.py`, `cobuilder/engine/validation/rules.py`, `cobuilder/engine/validation/advanced_rules.py`

1. Create `cobuilder/engine/schema.py` containing all constants copied verbatim from `engine/validator.py`. No logic, no imports from sibling modules.
2. Update `engine/node_ops.py` to import from `schema.py` instead of `validator.py`.
3. Update any constant references inside `engine/validation/rules.py` and `advanced_rules.py` that currently duplicate constants inline — replace with imports from `schema.py`.

**Acceptance**: `pytest tests/engine/ tests/attractor/ -x` passes. No import errors.

### Phase 2: Port missing rules to the OOP validator

**Files changed**: `cobuilder/engine/validation/rules.py` or `advanced_rules.py`

Port five rules from `engine/validator.py` that have no equivalent in the OOP rule set. Each rule becomes a stateless class implementing the `Rule` protocol.

| New Rule Class | Ported from flat rule | Severity |
|---------------|----------------------|----------|
| `NoUnguardedCycles` | Rule 9 | ERROR |
| `PromiseIdPresent` | Rule 10 | ERROR |
| `RefineEvidencePathValid` | Rule 12 | ERROR |
| `BeadIdExists` | Rule 15 | WARNING (requires `--check-beads` flag) |
| `ManifestValidationMethod` | Rule 16 | WARNING |

`BeadIdExists` and `ManifestValidationMethod` should be opt-in (controlled by a flag on `Validator.__init__`, defaulting off) to preserve the current fast-path validation used by the pipeline runner on startup.

**Acceptance**: Each new rule has at least one positive and one negative unit test in `tests/engine/validation/`.

### Phase 3: Reroute legacy CLI entry point

**Files changed**: `cobuilder/engine/cli.py`

Replace the `validate` subcommand body (lines 80-82) to use `Validator(graph).run()` instead of `validator_main`. The output rendering should match existing CLI output format (errors then warnings, with counts).

**Acceptance**: `python3 cobuilder/engine/cli.py validate <file.dot>` runs without error on a valid pipeline and produces equivalent output to the Typer CLI.

### Phase 4: Update test imports

**Files changed**: `tests/attractor/test_dot_schema_extensions.py`, `tests/unit/conftest.py`, `cobuilder/pipeline/tests/test_research_nodes.py`

1. `test_dot_schema_extensions.py`: Change `from cobuilder.engine.validator import ...` to `from cobuilder.engine.schema import ...` for constants; replace `validate` call with `Validator(graph).run()` pattern.
2. `tests/unit/conftest.py`: The autouse fixture stubs `validate_file` from `pipeline/validator.py`. Replace with a stub of `cobuilder.engine.validation.validator.Validator.run` or remove the stub if it is no longer needed.
3. `cobuilder/pipeline/tests/test_research_nodes.py`: Replace any imports from `cobuilder.pipeline.validator` with `cobuilder.engine.validation.validator` and `cobuilder.engine.schema`.

**Acceptance**: `pytest tests/ -x` passes with no import errors from removed modules.

### Phase 5: Delete legacy modules

**Files deleted**: `cobuilder/engine/validator.py`, `cobuilder/pipeline/validator.py`

Delete both files. Run the full test suite. Any remaining import of the deleted paths will surface as an `ImportError` and must be fixed before proceeding.

**Acceptance**: `pytest tests/ -v` passes. `grep -r "from cobuilder.engine.validator" .` and `grep -r "from cobuilder.pipeline.validator" .` return no results outside of `__pycache__`.

---

## 6. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OOP validator produces different output format from legacy flat validator, breaking CI scripts that parse CLI output | Medium | Low | Phase 3 explicitly preserves output format; compare output manually before deleting legacy module |
| `NoUnguardedCycles` rule is complex to port correctly (graph traversal edge cases) | Medium | Medium | Port with direct test cases lifted from the existing flat rule's test coverage; mark with `# ported from validator.py rule 9` comment |
| `tests/unit/conftest.py` autouse stub masks real validation failures in unit tests | Low | Medium | Remove the stub entirely in Phase 4 and fix any newly-failing tests rather than re-stubbing |
| `pipeline/validator.py` uses a different `parse_file` import path (`from .parser import`); its callers may depend on slightly different parsed dict structure | Low | Low | The test files only use it for constants and the `validate_file` stub — no structural parsing difference affects the migration |
| Circular imports if `schema.py` imports from `graph.py` or vice versa | Low | High | `schema.py` must remain pure-data: no imports from `cobuilder.engine.*` other than stdlib |

---

## 7. Acceptance Criteria

1. `grep -rn "from cobuilder.engine.validator" .` returns zero results (excluding `__pycache__`).
2. `grep -rn "from cobuilder.pipeline.validator" .` returns zero results (excluding `__pycache__`).
3. `python3 cobuilder/engine/cli.py validate <valid_pipeline.dot>` exits 0.
4. `python3 -m cobuilder pipeline validate <valid_pipeline.dot>` exits 0.
5. Both CLIs produce non-zero exit codes and meaningful error output for a pipeline with a known topology error.
6. `pytest tests/ -v` passes with no skips attributed to missing validator modules.
7. `cobuilder/engine/schema.py` is the single definition of `VALID_HANDLERS`, `VALID_STATUSES`, `HANDLER_SHAPE_MAP`, `REQUIRED_ATTRS`, `VALID_WORKER_TYPES`, `WARNING_ATTRS`.
8. The five ported rules each have at least one passing and one failing test case.

---

## 8. Out of Scope

- Changing the DOT schema itself (adding or removing handler types, statuses).
- Unifying the two CLI surfaces (`engine/cli.py` vs `cobuilder/cli.py`) — these serve different invocation contexts and the consolidation does not require merging them.
- Migrating `cobuilder/pipeline/` tests to use the engine test infrastructure — only import paths are updated.

---

## Implementation Status

| Phase | Status | Date | Commit |
|-------|--------|------|--------|
| Phase 1: Extract schema.py | Remaining | - | - |
| Phase 2: Port missing rules | Remaining | - | - |
| Phase 3: Reroute legacy CLI | Remaining | - | - |
| Phase 4: Update test imports | Remaining | - | - |
| Phase 5: Delete legacy modules | Remaining | - | - |
