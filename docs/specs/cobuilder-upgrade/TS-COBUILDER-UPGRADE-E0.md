---
title: "TS-E0: Merge Template System + ManagerLoopHandler + Observability + Coverage Baseline"
ts_id: TS-COBUILDER-UPGRADE-E0
prd_ref: PRD-COBUILDER-UPGRADE-001
epic: E0
status: draft
type: reference
created: 2026-03-14
last_verified: 2026-03-14
grade: authoritative
---

# TS-COBUILDER-UPGRADE-E0: Merge Template System + ManagerLoopHandler

## 1. Overview

Epic 0 establishes the foundation by merging 5,061 lines from the `abstract-workflow-system` branch into the main codebase, preserving all Logfire observability spans, and establishing a test coverage baseline. This is prerequisite to all subsequent epics.

**Source branch**: `claude/abstract-workflow-system-MEtWv`
**Target branch**: `prd-cobuilder-upgrade` (then to `main`)
**Merge base**: `255fcff` (shared ancestor)

## 2. Sub-Epic Breakdown

| Sub-Epic | Goal | Owner |
|----------|------|-------|
| E0.1 | Code merge — bring 27 files, 5,061 LOC into `prd-cobuilder-upgrade` | System 3 (direct) |
| E0.2 | Logfire observability — audit spans, convert defensive imports, add test assertions | Sub-agent |
| E0.3 | Test coverage baseline — configure pytest-cov, measure, create gap backlog | Sub-agent |

## 3. E0.1: Code Merge Strategy

### 3.1 Files Being Merged (27 total)

**New files (no conflict risk)** — 22 files:
- `cobuilder/templates/__init__.py` (9 LOC)
- `cobuilder/templates/constraints.py` (255 LOC)
- `cobuilder/templates/instantiator.py` (161 LOC)
- `cobuilder/templates/manifest.py` (344 LOC)
- `cobuilder/engine/state_machine.py` (120 LOC)
- `cobuilder/engine/middleware/constraint.py` (134 LOC)
- `cobuilder/sidecar/__init__.py` (2 LOC)
- `cobuilder/sidecar/stream_summarizer.py` (255 LOC)
- `.cobuilder/templates/hub-spoke/manifest.yaml` (87 LOC)
- `.cobuilder/templates/hub-spoke/template.dot.j2` (217 LOC)
- `.cobuilder/templates/s3-lifecycle/manifest.yaml` (85 LOC)
- `.cobuilder/templates/s3-lifecycle/template.dot.j2` (182 LOC)
- `.cobuilder/templates/sequential-validated/manifest.yaml` (53 LOC)
- `.cobuilder/templates/sequential-validated/template.dot.j2` (113 LOC)
- `tests/templates/__init__.py`
- `tests/templates/test_constraints.py` (126 LOC)
- `tests/templates/test_instantiator.py` (153 LOC)
- `tests/templates/test_manifest.py` (170 LOC)
- `tests/templates/test_real_templates.py` (280 LOC)
- `tests/templates/test_stream_summarizer.py` (124 LOC)
- `tests/engine/test_manager_loop.py` (160 LOC)
- `tests/engine/test_state_machine.py` (102 LOC)

**Modified files (conflict risk)** — 5 files:
- `cobuilder/engine/handlers/manager_loop.py` — **HIGH RISK**: main=68 LOC, worktree=332 LOC. Worktree adds `spawn_pipeline` mode. Main may have minor updates.
- `cobuilder/engine/runner.py` — **HIGH RISK**: main=802 LOC, worktree=837 LOC. Worktree adds template constraint imports + integration. Main has Epic 5 loop detection that worktree lacks.
- `.claude/capability_model.json` — Low risk, auto-generated
- `docs/sds/SD-TEMPLATE-SYSTEM-AND-S3-META-PIPELINE.md` — New doc (no conflict)
- `docs/abstract-workflow-system-analysis.md` — New doc (no conflict)

### 3.2 Conflict Resolution Plan

#### runner.py (highest complexity)

The worktree branch adds template constraint imports (lines 79-89):
```python
try:
    from cobuilder.engine.state_machine import NodeStateMachine
    from cobuilder.engine.middleware.constraint import ConstraintMiddleware
    from cobuilder.templates.manifest import resolve_manifest_for_graph
    _TEMPLATE_CONSTRAINTS_AVAILABLE = True
except ImportError:
    _TEMPLATE_CONSTRAINTS_AVAILABLE = False
```

Main branch has Epic 5 loop detection imports (lines 89-103):
```python
try:
    from cobuilder.engine.loop_detection import (
        LoopDetector, LoopPolicy, apply_loop_restart, resolve_loop_policy,
    )
    _LOOP_DETECTION_AVAILABLE = True
except ImportError:
    _LOOP_DETECTION_AVAILABLE = False
```

**Resolution**: Keep BOTH import blocks. They are additive — template constraints and loop detection are independent features. The merge strategy is "ours + theirs" for all defensive import blocks.

#### manager_loop.py (medium complexity)

Main has a minimal 68-line stub. Worktree has a 332-line implementation with `spawn_pipeline` mode, depth limiting, and signal monitoring. **Resolution**: Take the worktree version wholesale — it's a superset of main's stub.

### 3.3 Merge Procedure

```bash
# 1. Ensure clean state
git stash  # if needed

# 2. Merge (allow conflicts for manual resolution)
git merge claude/abstract-workflow-system-MEtWv --no-ff -m "feat(E0): merge template system + ManagerLoopHandler from abstract-workflow-system"

# 3. Resolve conflicts (expected in runner.py and manager_loop.py)
# For runner.py: keep both import blocks, merge run() method changes
# For manager_loop.py: take worktree version (332 LOC superset)

# 4. Run tests
pytest tests/ -v

# 5. Verify template instantiation
python -c "from cobuilder.templates.instantiator import Instantiator; print('OK')"
```

### 3.4 Post-Merge Verification

| Check | Command | Expected |
|-------|---------|----------|
| All existing tests pass | `pytest tests/ -v` | 0 failures |
| Template imports work | `python -c "from cobuilder.templates import ..."` | No ImportError |
| State machine imports work | `python -c "from cobuilder.engine.state_machine import NodeStateMachine"` | No ImportError |
| ManagerLoopHandler has spawn_pipeline | `python -c "from cobuilder.engine.handlers.manager_loop import ManagerLoopHandler; print(hasattr(ManagerLoopHandler, 'spawn_pipeline'))"` | True |
| Constraint middleware imports | `python -c "from cobuilder.engine.middleware.constraint import ConstraintMiddleware"` | No ImportError |
| Real template instantiation | `pytest tests/templates/test_real_templates.py -v` | All pass |

## 4. E0.2: Logfire Observability Preservation

### 4.1 Current State Audit

**Problem**: Logfire is imported defensively (`_LOGFIRE_AVAILABLE` guard pattern) and `logfire` is NOT in `pyproject.toml` dependencies. No CI enforces span presence. This means observability is silently disabled in any environment where logfire isn't installed.

#### Logfire Instrumentation Inventory (Current Main)

| Layer | File | Pattern | Span Count |
|-------|------|---------|------------|
| Engine runner | `cobuilder/engine/runner.py` | `_LOGFIRE_AVAILABLE` guard | 2 spans (pipeline.run, node.execute) |
| Engine middleware | `cobuilder/engine/middleware/logfire.py` | `_LOGFIRE_AVAILABLE` guard | 2 spans (per-node handler) |
| Engine events | `cobuilder/engine/events/logfire_backend.py` | `_LOGFIRE_AVAILABLE` guard | 3 spans (pipeline, node, close) |
| **Dispatch runner** | `cobuilder/attractor/pipeline_runner.py` | `_LOGFIRE_AVAILABLE` guard | 12+ spans (pipeline, tool, worker, validation) |
| **Dispatch guardian** | `cobuilder/attractor/guardian.py` | Direct `import logfire` | 4 spans (build_system_prompt, build_initial_prompt, build_options, run_agent) |
| **Dispatch session** | `cobuilder/attractor/session_runner.py` | Direct `import logfire` | 10 spans (build_*, run_agent, main) |

**Key observation**: The engine layer uses defensive imports; the dispatch layer (attractor/) uses direct imports. The dispatch layer will CRASH if logfire is missing. This inconsistency must be resolved.

#### Worktree Logfire Status

The `abstract-workflow-system` worktree has the SAME engine-layer Logfire patterns (defensive imports in runner, middleware, events). It does NOT contain the dispatch layer (`cobuilder/attractor/`) at all — that code only exists on main.

### 4.2 Resolution Plan

1. **Add `logfire>=2.0` to `pyproject.toml` dependencies** (hard requirement, not optional)
2. **Convert all defensive imports to direct imports** in `cobuilder/engine/`:
   - Remove `_LOGFIRE_AVAILABLE` guard pattern
   - Replace with direct `import logfire`
   - Remove all `if _LOGFIRE_AVAILABLE:` conditionals
3. **Add `CaptureLogfire` test assertions** for every handler:
   ```python
   from logfire.testing import CaptureLogfire

   def test_handler_emits_span(capture_logfire: CaptureLogfire):
       # Run handler...
       spans = capture_logfire.exporter.exported_spans
       assert any(s.name == "node.execute" for s in spans)
   ```
4. **Preserve dispatch layer spans**: When E2 renames `attractor/` → `engine/`, all dispatch spans must be carried forward. The direct `import logfire` pattern in guardian.py and session_runner.py is correct — keep it.

### 4.3 Span Catalog (Post-Merge Target)

Every span listed below MUST exist after E0.2. CI tests assert their presence.

| Span Name | Source | Type |
|-----------|--------|------|
| `pipeline.run` | engine/runner.py | Pipeline lifecycle |
| `node.execute` | engine/runner.py | Per-node execution |
| `handler.{type}` | engine/middleware/logfire.py | Per-handler timing |
| `pipeline.{id}` | engine/events/logfire_backend.py | Event bus pipeline span |
| `node.{id}` | engine/events/logfire_backend.py | Event bus node span |
| `guardian.build_system_prompt` | attractor/guardian.py | Guardian prompt build |
| `guardian.run_agent` | attractor/guardian.py | Guardian agent execution |
| `runner.build_system_prompt` | attractor/session_runner.py | Session prompt build |
| `runner.run_agent` | attractor/session_runner.py | Session agent execution |
| `runner.main` | attractor/session_runner.py | Session entry point |
| `tool {node_id}` | attractor/pipeline_runner.py | Pipeline tool execution |
| `worker {node_id}` | attractor/pipeline_runner.py | SDK worker dispatch |
| `validation {node_id}` | attractor/pipeline_runner.py | Validation subprocess |

## 5. E0.3: Test Coverage Baseline

### 5.1 Configuration

Add to `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["cobuilder"]
omit = [
    "*/tests/*",
    "*/__pycache__/*",
    "cobuilder/__main__.py",
]

[tool.coverage.report]
fail_under = 0   # Baseline only — E5 enforces 90
show_missing = true
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "if __name__ == .__main__.",
    "raise NotImplementedError",
]

[tool.coverage.html]
directory = "htmlcov"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "functional: marks tests as functional (end-to-end) tests",
    "unit: fast unit tests",
    "integration: integration tests requiring external services",
    "e2e: full end-to-end pipeline tests",
]
addopts = "--cov=cobuilder --cov-report=term-missing --cov-report=html"
```

### 5.2 Known Gaps (from audit)

| Module | Estimated Coverage | Priority | Target (E5) |
|--------|-------------------|----------|-------------|
| `cobuilder/engine/handlers/` (11 modules) | ~10% | P0 | ≥80% |
| `cobuilder/repomap/models/` | ~0% | P1 | ≥70% |
| `cobuilder/repomap/serena/` | ~33% | P1 | ≥70% |
| `cobuilder/orchestration/adapters/` | ~25% | P1 | ≥70% |
| `cobuilder/templates/` (new from merge) | ~85% (well-tested in worktree) | P2 | Maintain |
| `cobuilder/engine/state_machine.py` (new) | ~90% (tested in worktree) | P2 | Maintain |
| `cobuilder/attractor/pipeline_runner.py` | Unknown | P0 | ≥70% |

### 5.3 Deliverables

1. `pyproject.toml` updated with coverage config
2. `tests/conftest.py` updated with shared fixtures (if needed)
3. Baseline coverage report saved to `docs/specs/cobuilder-upgrade/coverage-baseline.txt`
4. Gap backlog documented in this TS (Section 5.2 above)

## 6. Dependencies

| This Epic | Depends On | Relationship |
|-----------|-----------|-------------|
| E0.1 | `claude/abstract-workflow-system-MEtWv` branch | Source code |
| E0.2 | E0.1 | Audit requires merged codebase |
| E0.3 | E0.1 | Coverage measurement requires merged codebase |
| E1 | E0 | Profiles integrate with manifest schema |
| E2 | E0 | Rename targets the merged codebase |

## 7. Risks

| Risk | Mitigation |
|------|-----------|
| runner.py merge conflict breaks loop detection | Manual conflict resolution keeping both import blocks; run tests immediately |
| Removing `_LOGFIRE_AVAILABLE` guards breaks environments without logfire | Add `logfire>=2.0` to hard dependencies first |
| Coverage baseline reveals critically low numbers | Expected — this is an informational measurement, not a gate |
| Template tests assume directory structure that differs post-merge | Check template paths in test fixtures; now using `.cobuilder/templates/` |
