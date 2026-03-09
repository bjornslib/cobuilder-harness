---
title: "SD-ATTRACTOR-CONSOLIDATION-001: Attractor-to-CoBuilder Restructure"
status: active
type: architecture
last_verified: 2026-03-09
grade: authoritative
---

# SD-ATTRACTOR-CONSOLIDATION-001
## Attractor-to-CoBuilder Restructure: Constraint Analysis and Migration Blueprint

**Document type**: Solution Design
**Reasoning mode**: Constraint Analysis (Architect 5)
**Date**: 2026-03-09
**Status**: Active

---

## 1. Executive Summary

This document is the authoritative constraint analysis and migration blueprint for consolidating `.claude/scripts/attractor/` into `cobuilder/`, moving runtime state out of `.claude/`, and deleting confirmed dead code.

The primary finding is that the consolidation is **feasible in four phases** but contains three hard blockers that prior planning understated:

1. The `pipeline_runner.py` files are not versions of the same thing — the attractor version (1,669 lines, 35 class methods) is the production runtime; the cobuilder version (7 functions, 802 lines) is a legacy runner-agent pattern from a different era. They cannot be naively merged.
2. Every attractor script uses bare `sys.path.insert(0, _THIS_DIR)` self-injection to import siblings as flat modules. This is incompatible with Python package imports (`from cobuilder.pipeline.parser import ...`). Migration requires converting ALL cross-module imports in the attractor scripts simultaneously, not one file at a time.
3. The `signal_dir` is **not** hardcoded in DOT file attributes (C2 as stated was inaccurate). It is computed dynamically as `os.path.join(dot_dir, "signals", pipeline_id)` inside `PipelineRunner.__init__`. The physical location `.claude/attractor/signals/` therefore derives from where the DOT files live. Moving DOT files moves signals with them.

---

## 2. Constraint Satisfaction Matrix

Each cell shows whether the constraint **blocks** (B), **complicates** (C), or is **neutral** (N) for the four proposed decisions.

| Constraint | Dead Code Delete | Signal Dir Move | Code to CoBuilder | State Out of .claude/ |
|---|---|---|---|---|
| C1: .claude/ convention | N | N | N | N |
| C2: DOT file paths (REVISED) | N | B* | C | C |
| C3: Hook script paths | N | N | B | N |
| C4: Output style paths | N | N | B | N |
| C5: Skills paths | N | N | B | N |
| C6: pyproject.toml | N | N | B | N |
| C7: Name collisions | N | N | B | N |
| C8: Tests | N | N | B | N |
| C9: Git history | C | N | C | N |
| C10: Import paths | N | N | B | N |
| S1: Diff size | C | N | B | C |
| S2: Backward compat | N | N | B | N |
| S3: Active pipelines | N | B* | N | N |
| S4: Single source | N | N | B-then-solves | N |

\* B for signal dir move: signals live under the DOT file's directory. Moving DOT files moves signals. Active pipelines lose their in-flight signal state on move.

**Summary of blockers**:
- Deleting dead code: zero hard blockers. Safe immediately.
- Moving signal dir: only blocked by active in-flight pipelines. Coordinate with a quiescent window.
- Code to CoBuilder: blocked by 7 constraints simultaneously. Requires phased approach.
- State out of .claude/: minimal hard blockers; mainly a naming/convention question.

---

## 3. Corrected Constraint Analysis

### C2 Correction: DOT Files Do Not Hardcode Signal Paths

The original brief stated "367 live DOT files contain hardcoded paths like `signal_dir=".claude/attractor/signals/"`". Investigation found this is **false**. Zero DOT files in `.claude/attractor/pipelines/` use `signal_dir` as a DOT attribute. The signal directory is computed at runtime:

```python
# pipeline_runner.py line 217
self.signal_dir = os.path.join(self.dot_dir, "signals", self.pipeline_id)
```

`self.dot_dir` is `os.path.dirname(os.path.abspath(dot_file))`. If the DOT file is at `.claude/attractor/pipelines/PRD-FOO.dot`, signals land at `.claude/attractor/pipelines/signals/PRD-FOO/`. Moving the DOT file moves the signal directory with it automatically. This substantially reduces C2 from a blocker to a coordination concern.

### C4/C5 Actual Reference Inventory

Output styles and skills do reference hardcoded attractor script paths. The complete inventory:

**`.claude/output-styles/system3-meta-orchestrator.md`** — 4 references:
- Line 600: `python3 .claude/scripts/attractor/pipeline_runner.py --dot-file <path.dot>`
- Lines 677/680/683/686/842: `cobuilder pipeline status .claude/attractor/pipelines/${INITIATIVE}.dot`

**`.claude/skills/s3-guardian/references/guardian-workflow.md`** — 18 references to:
- `.claude/scripts/attractor/spawn_orchestrator.py`
- `.claude/scripts/attractor/runner.py`
- `.claude/scripts/attractor/cli.py`
- `.claude/scripts/attractor/respond_to_runner.py`
- `.claude/attractor/signals/`
- `.claude/attractor/pipelines/`
- `.claude/attractor/checkpoints/`

**`.claude/skills/s3-guardian/references/monitoring-patterns.md`** — 12 references

**`.claude/skills/s3-guardian/references/gap-closure-protocol.md`** — 4 references

**`.claude/skills/s3-guardian/references/phase0-prd-design.md`** — 4 references

**`.claude/skills/s3-guardian/references/validation-scoring.md`** — 6 references

**`.claude/skills/s3-guardian/references/dot-pipeline-creation.md`** — 1 reference

Total: approximately 49 path strings across 7 markdown files that must be updated in lockstep with any code moves.

### C7 Detailed Collision Analysis

19 files share names between `.claude/scripts/attractor/` and `cobuilder/pipeline/` or `cobuilder/orchestration/`. Divergence levels:

| File | Attractor fns | CoBuilder fns | Shared | Status |
|---|---|---|---|---|
| `parser.py` | 9 | 9 | 9 | **Identical surface** — attractor is canonical |
| `checkpoint.py` | 5 | 5 | 5 | **Identical surface** — attractor is canonical |
| `signal_protocol.py` | 13 | 12 | 12 | Attractor has one extra: `write_runner_exited` |
| `transition.py` | 20 | 24 | 20 | CoBuilder has 4 extra hooks (post-validated, project root) |
| `pipeline_runner.py` | 35 methods | 7 functions | 1 (`main`) | **Different beasts** — cannot merge |
| `validator.py` | (not compared) | (not compared) | — | Check before merge |
| `status.py` | (not compared) | (not compared) | — | Check before merge |
| `annotate.py` | (not compared) | (not compared) | — | Check before merge |

**Critical finding on `pipeline_runner.py`**: The attractor version is the live pipeline orchestration engine (class `PipelineRunner`, signal watching, AgentSDK dispatch, gate handling). The cobuilder version implements `RunnerAgent` — a different, older pattern based on an LLM agent that reads state files. These two files describe architecturally distinct concepts that happened to be given the same name. They must be given distinct canonical names before any merge:
- Attractor `pipeline_runner.py` → canonical name: `cobuilder/orchestration/pipeline_engine.py`
- CoBuilder `pipeline_runner.py` → canonical name: `cobuilder/orchestration/runner_agent.py` (or delete if superseded)

### C8 Test Isolation: The sys.path Problem

All attractor tests use `conftest.py` to inject the attractor directory into `sys.path`:

```python
_ATTRACTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ATTRACTOR_DIR)
```

Tests then do bare imports: `from runner import RunnerStateMachine`. This pattern is incompatible with Python package structure. Once attractor modules move into `cobuilder/`, all 12,299 lines of tests must be updated to use package-qualified imports: `from cobuilder.orchestration.runner import RunnerStateMachine`.

This is not optional. The sys.path injection approach only works when the module being tested is not yet a package. The migration must update all test imports as part of each module move.

### C10 Import Pattern: Self-Injection is Pervasive

Every attractor module uses `sys.path.insert(0, _THIS_DIR)` then bare imports:

```python
from checkpoint import save_checkpoint
from parser import parse_file, parse_dot
from transition import apply_transition
```

When these modules move into `cobuilder/`, all bare imports become package imports. This must happen in a coordinated batch — partial migration (moving some modules but not others) creates a state where some bare imports resolve and others do not, which will silently shadow stdlib modules named `parser` or `status`.

**The `parser` name shadow risk**: Python's stdlib had a `parser` module (deprecated in 3.9, removed in 3.12). The attractor `parser.py` shadows this. Inside cobuilder as a package, `from cobuilder.pipeline.parser import parse_file` is explicit and safe.

---

## 4. Dead Code Registry (Safe to Delete — Phase 0)

These files have zero import references in the live codebase. Deletion carries no migration risk.

| File | Lines | Evidence of Dead Status |
|---|---|---|
| `.claude/scripts/attractor/capture_output.py` | 79 | Never imported in any other attractor file |
| `.claude/scripts/attractor/check_orchestrator_alive.py` | 64 | Never imported; `check_orchestrator_alive` not referenced |
| `.claude/scripts/attractor/poc_pipeline_runner.py` | 637 | Superseded POC; imports `dispatch_worker.load_attractor_env` only |
| `.claude/scripts/attractor/poc_test_scenarios.py` | 417 | POC test; no live references |
| `.claude/scripts/attractor/runner_test_scenarios.py` | 536 | Orphaned; 0 test runs reference it |
| `.claude/scripts/attractor/test_logfire_guardian.py` | (lines TBC) | Standalone test script, not in test suite |
| `.claude/scripts/attractor/test_logfire_sdk.py` | (lines TBC) | Standalone test script, not in test suite |
| Root: `test_*.py`, `test_*.dot` | varies | Ad-hoc test artefacts |
| Root: `*.log`, `screen_*.png` | varies | Runtime artefacts |

**Also safe**: `cobuilder/cli.py` `agents_app` — the empty Typer sub-application. Verify it has no registered commands before deletion.

---

## 5. Path Update Registry

Every reference that must be updated when code moves. Grouped by destination.

### Group A: Output Styles (owned by .claude/output-styles/)

File: `.claude/output-styles/system3-meta-orchestrator.md`

| Old path | New path | Nature |
|---|---|---|
| `python3 .claude/scripts/attractor/pipeline_runner.py --dot-file` | `python3 -m cobuilder.orchestration.pipeline_engine --dot-file` OR `cobuilder pipeline run` | CLI invocation |
| `.claude/attractor/pipelines/${INITIATIVE}.dot` | `.claude/attractor/pipelines/${INITIATIVE}.dot` | **No change** — pipeline store stays |

### Group B: Skills (owned by .claude/skills/s3-guardian/)

Files: `guardian-workflow.md`, `monitoring-patterns.md`, `gap-closure-protocol.md`, `phase0-prd-design.md`, `validation-scoring.md`, `dot-pipeline-creation.md`

| Old path pattern | New path pattern |
|---|---|
| `python3 .claude/scripts/attractor/spawn_orchestrator.py` | `cobuilder orchestrator spawn` or `python3 -m cobuilder.orchestration.spawn_orchestrator` |
| `python3 .claude/scripts/attractor/cli.py node-modify` | `cobuilder pipeline node-modify` |
| `python3 .claude/scripts/attractor/runner.py --spawn` | `cobuilder pipeline run` |
| `python3 .claude/scripts/attractor/respond_to_runner.py` | `cobuilder pipeline signal write` |
| `.claude/attractor/signals/` | `.claude/attractor/signals/` (no change if DOTs stay) |
| `.claude/attractor/pipelines/` | `.claude/attractor/pipelines/` (no change) |
| `.claude/attractor/checkpoints/` | `.claude/attractor/checkpoints/` (no change if DOTs stay) |

### Group C: CoBuilder CLI (entry point update in pyproject.toml)

If `cobuilder pipeline` commands are exposed, the Typer CLI at `cobuilder/cli.py` must register them. Current entry points are valid but need new subcommands added.

### Group D: Tests

All 12,299 lines of tests in `.claude/scripts/attractor/tests/` must update their import patterns from bare names to package-qualified names. This is a bulk mechanical change that a worker can execute with a targeted sed or AST transformation.

---

## 6. Risk-Ordered Migration Plan

Phases are sequenced with highest-risk items deferred until backward compatibility infrastructure is in place.

### Phase 0: Dead Code Deletion (Risk: Very Low)

**Duration**: 1 session
**Risk factors**: None identified. No imports reference these files.
**Rollback**: `git revert <commit>`

**Actions**:
1. Delete `.claude/scripts/attractor/capture_output.py`
2. Delete `.claude/scripts/attractor/check_orchestrator_alive.py`
3. Delete `.claude/scripts/attractor/poc_pipeline_runner.py`
4. Delete `.claude/scripts/attractor/poc_test_scenarios.py`
5. Delete `.claude/scripts/attractor/runner_test_scenarios.py`
6. Delete `.claude/scripts/attractor/test_logfire_guardian.py`
7. Delete `.claude/scripts/attractor/test_logfire_sdk.py`
8. Delete root-level `test_*.py`, `test_*.dot`, `*.log`, `screen_*.png`
9. Verify test suite still passes: `cd .claude/scripts/attractor && python -m pytest tests/ -m "not e2e"`

**Acceptance**: Green test run, no living import references to deleted files.

---

### Phase 1: Rename Colliding Pipeline Runner (Risk: Medium)

**Duration**: 1 session
**Risk factors**: output-styles and skills reference the old filename; must update 5 markdown files in the same commit.
**Rollback**: `git revert <commit>`

**Rationale**: The name collision between the two `pipeline_runner.py` files is the single biggest blocker to any subsequent merge work. Resolving the naming first unlocks all subsequent phases.

**Actions**:
1. In `.claude/scripts/attractor/`: rename `pipeline_runner.py` → `pipeline_engine.py` using `git mv`
2. Update any scripts that invoke it by filename:
   - Any shell scripts or Python scripts that call `python3 pipeline_runner.py`
   - `hooks/` scripts (verify via grep — currently none found)
3. Update the invocation in `.claude/output-styles/system3-meta-orchestrator.md` line 600:
   - Old: `python3 .claude/scripts/attractor/pipeline_runner.py --dot-file`
   - New: `python3 .claude/scripts/attractor/pipeline_engine.py --dot-file`
4. Update all references in s3-guardian skill markdown files
5. Rename `cobuilder/orchestration/pipeline_runner.py` → `cobuilder/orchestration/runner_agent.py` (clarifies it is the old LLM-agent runner pattern, distinct from the engine)
6. Update `cobuilder/orchestration/__init__.py` exports
7. Run tests

**Mitigations**:
- Create a one-line shim at the old name for 30 days: `.claude/scripts/attractor/pipeline_runner.py` containing only `from pipeline_engine import *; import warnings; warnings.warn("pipeline_runner.py is renamed to pipeline_engine.py", DeprecationWarning, stacklevel=2)`
- This keeps any muscle-memory scripts working during the transition window.

---

### Phase 2: Resolve Module Divergence in Shared Files (Risk: Medium)

**Duration**: 1-2 sessions
**Risk factors**: `transition.py` in cobuilder has 4 extra functions absent from attractor. Must decide canonical source.
**Rollback**: `git revert <range>`

**Goal**: Before moving any code, ensure the cobuilder copies of the 19 conflicting modules are either identical to attractor or are known-divergent with a merge plan.

**Actions for each conflicting module**:

1. **`parser.py`** — identical surface. Attractor copy is canonical. Mark cobuilder copy as a re-export shim pointing at attractor (in the interim) or delete cobuilder copy and keep attractor.

2. **`checkpoint.py`** — identical surface. Same as parser.

3. **`signal_protocol.py`** — attractor has `write_runner_exited` that cobuilder lacks. Merge: add the missing function to cobuilder's version, then treat cobuilder as canonical.

4. **`transition.py`** — cobuilder has 4 extra functions (`_extract_graph_repo_name`, `_extract_node_scope`, `_fire_post_validated_hook`, `_infer_project_root`). These are enrichment hooks for the cobuilder pipeline enricher path. Merge plan: bring attractor transition.py to cobuilder, then add the 4 extra cobuilder functions on top. The merged file becomes canonical in `cobuilder/pipeline/transition.py`.

5. **`validator.py`, `status.py`, `annotate.py`, `node_ops.py`, `edge_ops.py`, `generate.py`, `init_promise.py`, `dashboard.py`** — diff each pair. For modules with identical content, mark cobuilder as canonical. For any divergence, document specifically which functions differ before proceeding.

**Output of Phase 2**: A merge decision record (can be a comment block at the top of each file or a separate registry document) stating "attractor canonical" or "cobuilder canonical" or "merged" for each of the 19 files.

---

### Phase 3: Install Attractor as a CoBuilder Subpackage (Risk: High)

**Duration**: 2-3 sessions
**Risk factors**: sys.path self-injection must be replaced; tests break until all imports are updated; active pipelines must be quiescent.
**Rollback**: Complex — requires reverting git mv operations and restoring sys.path patches. Use a dedicated branch.

**This is the most complex phase. Execute on a feature branch with CI.**

**Preconditions**:
- Phase 0, 1, 2 complete
- No in-flight pipelines running against `.claude/attractor/pipelines/`
- All 19 conflicting modules have a merge decision

**Step 3a: Create the target package structure**

```
cobuilder/
  orchestration/
    __init__.py
    pipeline_engine.py    (was attractor/pipeline_engine.py after Phase 1)
    runner_agent.py       (was cobuilder/orchestration/runner_agent.py after Phase 1)
    runner.py             (was attractor/runner.py — 1,426 lines)
    runner_models.py      (merged)
    runner_hooks.py       (merged)
    runner_tools.py       (merged)
    runner_guardian.py
    guardian.py           (1,153 lines — complex, see note below)
    spawn_orchestrator.py (merged)
    identity_registry.py  (merged)
    dispatch_worker.py    (attractor-only, no cobuilder equivalent)
    adapters/             (move from attractor/adapters/)
  pipeline/
    __init__.py
    parser.py             (canonical)
    transition.py         (merged)
    validator.py          (canonical)
    signal_protocol.py    (merged)
    checkpoint.py         (canonical)
    status.py             (canonical)
    node_ops.py           (canonical)
    edge_ops.py           (canonical)
    annotate.py           (canonical)
    generate.py           (canonical)
    init_promise.py       (canonical)
    dashboard.py          (canonical)
    dot_context.py        (cobuilder-only, keep)
    sd_enricher.py        (cobuilder-only, keep)
    taskmaster_bridge.py  (cobuilder-only, keep)
    signal_protocol.py    (merged)
```

**Guardian note**: `guardian.py` (1,153 lines) imports from `dispatch_worker` and `signal_protocol`. It is a complex orchestration script that predates the current 3-layer architecture. Before moving it, verify whether it is still referenced by any live pipeline (check signal file patterns in active DOTs). If the guardian pattern is superseded by the `pipeline_engine.py` + validation-agent design, it may be archiveable rather than migrated.

**Step 3b: Convert all bare imports to package imports**

For each moved module, replace bare sibling imports:

```python
# Before (bare import, works via sys.path injection)
from parser import parse_file, parse_dot
from signal_protocol import write_signal

# After (package import)
from cobuilder.pipeline.parser import parse_file, parse_dot
from cobuilder.pipeline.signal_protocol import write_signal
```

This must be done for ALL modules simultaneously in one commit per logical group (e.g., all pipeline/ modules in one commit, all orchestration/ modules in another).

**Step 3c: Remove sys.path injections**

Each file currently has a pattern like:
```python
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
```

Remove this block from every moved file. The package structure makes it unnecessary.

**Step 3d: Update tests**

All tests in `.claude/scripts/attractor/tests/` use conftest.py to inject the attractor directory. After migration:
1. Move tests to `cobuilder/orchestration/tests/` and `cobuilder/pipeline/tests/`
2. Update `conftest.py` to remove sys.path injection entirely
3. Update all test imports from bare names to package names
4. Update `pyproject.toml` `[tool.pytest.ini_options]` testpaths to include the new locations

**Step 3e: Install shims at old paths**

For the 90-day backward-compatibility window, leave thin shim files at `.claude/scripts/attractor/` that re-export from the new package locations:

```python
# .claude/scripts/attractor/pipeline_engine.py (shim)
"""Backward-compat shim. Import from cobuilder.orchestration.pipeline_engine instead."""
import warnings
warnings.warn(
    ".claude/scripts/attractor/pipeline_engine is deprecated. "
    "Use: from cobuilder.orchestration.pipeline_engine import PipelineRunner",
    DeprecationWarning,
    stacklevel=2
)
from cobuilder.orchestration.pipeline_engine import *  # noqa: F401, F403
```

**Critical shim gotcha from Hindsight**: Do NOT use module-level imports in shim `__init__.py` files — this causes partially-initialized module errors. The shim must import from the new package, not the other way around. And because deferred imports break `mock.patch`, the shims must use module-level re-exports, not lazy imports.

**Step 3f: Update CLI entry in output-styles and skills**

After the package is installable, update all 49 path references in markdown files to use the `cobuilder` CLI:
- `python3 .claude/scripts/attractor/pipeline_engine.py --dot-file` → `cobuilder pipeline run --dot-file`
- `python3 .claude/scripts/attractor/spawn_orchestrator.py` → `cobuilder orchestrator spawn`

This only works if `cobuilder pipeline run` is registered as a CLI command in `cobuilder/__main__.py`. Verify pyproject.toml entry point still resolves after the restructure.

---

### Phase 4: State Directory Cleanup (Risk: Low)

**Duration**: 1 session
**Risk factors**: Only concerns where runtime files (signals, checkpoints, examples) live. No code changes.

The `.claude/attractor/` directory contains runtime state that can remain where it is. The constraint brief asked to "move state out of .claude/" but C1 makes it clear that `.claude/` is required for Claude Code conventions. The real goal is cleaner separation:

**Recommended final layout**:

```
.claude/
  attractor/
    pipelines/         (DOT files — KEEP here, Claude Code reads them)
    signals/           (computed from DOT dir — moves with pipelines, stays here)
    checkpoints/       (KEEP here — runtime state)
    examples/          (KEEP here — reference DOTs)
    .env               (KEEP here — credentials)
  scripts/
    attractor/         (SHIMS ONLY after Phase 3 — for 90-day compat window)
```

After the 90-day shim window expires, `.claude/scripts/attractor/` can be removed entirely. The scripts are now in `cobuilder/`.

**What cannot move**: `.claude/attractor/pipelines/`, `.claude/attractor/signals/`, `.claude/attractor/checkpoints/`. These are runtime state tied to live pipeline executions. Moving them mid-flight loses pipeline state. They can move to `state/` or `data/` only if a complete pipeline quiescence window is arranged and all active pipelines are checkpointed and restored.

---

## 7. Backward Compatibility Strategy

### Shim Lifecycle

| Phase | Old path | Status | New path |
|---|---|---|---|
| Phase 0-2 | `.claude/scripts/attractor/*.py` | Canonical, live | — |
| Phase 3 start | `.claude/scripts/attractor/*.py` | Shims with DeprecationWarning | `cobuilder/orchestration/*.py` or `cobuilder/pipeline/*.py` |
| Day 90 post-Phase-3 | `.claude/scripts/attractor/*.py` | **Deleted** | (fully in cobuilder) |

### Shim Construction Rules

From Hindsight and prior migration experience:
1. Shims must use explicit `__all__` — never `import *` in production code, but the shim body can use it to surface the full public API
2. Place `DeprecationWarning` at module level (not inside a function) so it fires on import
3. Never put heavy logic in a shim — pure re-export only
4. Keep shims out of `__init__.py` — use named shim files to avoid partially-initialized module issues
5. Document shim removal date in a comment at the top of every shim file

### Attractor Invocation Wrapper

For the 90-day window, the skills and output-styles can continue calling:
```
python3 .claude/scripts/attractor/pipeline_engine.py --dot-file ...
```

The shim file at that path ensures this still works. This avoids forcing an immediate update of all 49 markdown path references in a single commit.

---

## 8. Rollback Plan Per Phase

| Phase | Rollback Method | Time to Recover | Risk of Data Loss |
|---|---|---|---|
| Phase 0: Dead code delete | `git revert <commit>` | 2 minutes | None |
| Phase 1: Rename pipeline_runner | `git revert <commit>`; restore shim | 10 minutes | None |
| Phase 2: Resolve divergence | `git revert <range>` | 15 minutes | None |
| Phase 3: Move to package | `git revert <branch merge>` | 30 minutes | Possible: in-flight signals lost if pipelines were running |
| Phase 4: State cleanup | Not applicable (no move recommended) | — | — |

**Phase 3 data loss mitigation**: Before starting Phase 3, checkpoint all active pipelines:
```bash
cobuilder pipeline checkpoint-save .claude/attractor/pipelines/*.dot
```
Checkpoints persist independently of signal files. If Phase 3 must be rolled back, signal files can be reconstructed from checkpoints.

---

## 9. What Cannot Be Done (Hard Limits)

These actions are explicitly out of scope due to hard constraints. Do not attempt them regardless of apparent simplicity.

### Cannot: Move .claude/settings.json, hooks/, output-styles/, skills/

C1 is absolute. Claude Code reads these locations unconditionally. Moving them breaks Claude Code itself, not just pipelines.

### Cannot: Do a "big bang" attractor-to-cobuilder migration in one commit

The sys.path self-injection pattern means that all modules must be converted simultaneously. However, 19 files have naming collisions with different content. Doing this in one commit means resolving all divergences, updating all imports, updating all tests, updating all markdown references, and adding all shims in a single pass — approximately 200+ file changes. This exceeds the safe diff size for review and has no intermediate checkpoints for rollback.

**The only safe approach is phases 1-2-3 as described above**, where phase 2 resolves all divergences on paper first, and phase 3 executes the migration with a verified merge decision for every file.

### Cannot: Merge attractor/pipeline_runner.py with cobuilder/orchestration/pipeline_runner.py

These are architecturally distinct programs that share a name. They implement different abstractions (`PipelineRunner` class with 35 methods vs `RunnerAgent` function-based pattern). They must be given distinct names (phase 1) before any merge is possible.

### Cannot: Move .claude/attractor/signals/ while pipelines are running

Signal files are the communication channel between the runner and validation agents. Moving the directory while signals are being written or polled will cause:
- The runner to lose signal files it is watching
- Validation agents writing signals to the old path (they get `ATTRACTOR_SIGNAL_DIR` from the runner's environment at dispatch time)
- Gate nodes stuck in `gate-wait` state permanently

Any signals migration requires a quiescence window confirmed by verifying no `.gate-wait` files exist and no runner processes are active.

### Cannot: Convert attractor tests to package imports incrementally

Because the tests use `sys.path` injection and bare imports, converting half of them (while the other half still use bare imports against the old location) creates a state where Python's import cache may serve the wrong module depending on which test runs first. All test imports must be updated in a single coordinated commit per test file group.

---

## 10. Recommended Compromises for Soft Constraints

### S1: Diff Size

Phase 3 will produce a large diff. The recommended compromise is to split it into sub-phases:
- 3a: Move `cobuilder/pipeline/` modules only (the pure DOT-handling tools — parser, transition, validator, etc.)
- 3b: Move `cobuilder/orchestration/` modules (runner, guardian, spawn_orchestrator, dispatch_worker)
- 3c: Update tests
- 3d: Install shims

Each sub-phase is reviewable independently. Total 3a+3b+3c+3d still lands the complete migration.

### S2: Backward Compatibility Period

90-day shim window is the recommendation. This covers:
- All existing skills markdown examples to be updated without emergency pressure
- Any external scripts that shell out to attractor paths
- The session memory entries that reference old paths

After 90 days, a "shim removal" PR deletes `.claude/scripts/attractor/` except for `.env` and the `pipelines/signals/checkpoints/` state directories (which remain).

### S3: Active Pipelines

The quiescence window for Phase 3 should be scheduled explicitly. Recommended trigger: when the current branch (`feat/harness-upgrade-e4-e6`) is merged and the associated pipelines reach terminal state. Do not begin Phase 3 while `PRD-HARNESS-UPGRADE-E4-E6.dot` has any nodes in `active` or `gate-wait` status.

### S4: Single Source of Truth

The post-Phase-3 state achieves single source of truth: `cobuilder/` owns all pipeline code; `.claude/scripts/attractor/` contains only shims; `.claude/attractor/` contains only runtime state (pipelines/, signals/, checkpoints/).

---

## 11. Hindsight Findings

Two Hindsight reflect calls were made before finalizing this document.

**Reflect 1** (query: "attractor cobuilder migration consolidation path updates"):
- Prior vector storage migration missed 4 stray references post-move, requiring a hotfix. Recommendation surfaced: pre-flight grep audit for old paths before declaring migration complete.
- Pydantic v2 migration pattern validated thin adapters as safe for incremental migration.
- Breaking-change summary as a standalone section (not buried in prose) was validated as the user's preferred pattern.

**Reflect 2** (query: "thin adapter shim pattern for incremental module migration"):
- Shims using wildcard `import *` are acceptable in shim bodies but `__all__` should be set explicitly.
- Deferred imports (imports inside function bodies) break `mock.patch`. Shims must use module-level re-exports.
- One prior migration created circular imports by importing shim modules into `__init__.py`. Shims must not be registered in package `__init__.py`.
- From one prior session, the user holds the opinion: "keeping immutable settings in a config file and exposing mutable runtime objects through explicit factories is cleaner because it makes the package import-safe and avoids partially initialized module errors." This supports keeping `.env` and runtime state in `.claude/attractor/` rather than pulling it into the cobuilder package.

---

## 12. Success Metrics and Monitoring

| Metric | Target | Verification |
|---|---|---|
| Dead code removed | 7 files deleted | `git log --diff-filter=D` |
| Naming collision resolved | `pipeline_runner.py` name retired from both locations | `grep -r "pipeline_runner" .claude/scripts/attractor/` returns only shim |
| Package importable | `from cobuilder.orchestration.pipeline_engine import PipelineRunner` succeeds | `python -c "from cobuilder.orchestration.pipeline_engine import PipelineRunner"` |
| Tests green | All attractor tests pass with package imports | `pytest cobuilder/ -m "not e2e"` exit code 0 |
| No stray old-path references | Zero non-shim Python files reference old bare import paths | Pre-flight grep audit |
| Shims emit warnings | `import warnings; warnings.catch_warnings()` captures DeprecationWarning | Unit test per shim |
| Signal dir unbroken | Active pipeline completes end-to-end post-Phase-3 | Run simple-pipeline.dot through pipeline_engine.py |
| Markdown updated | 49 path references in skills/output-styles updated | `grep -r ".claude/scripts/attractor" .claude/` returns only shim comments |

---

## 13. Handoff Summary for Orchestrator

**Priority order for implementation**:

1. **Immediately safe**: Phase 0 (dead code deletion). Assign to any worker. No coordination needed.
2. **Next**: Phase 1 (rename `pipeline_runner.py` to `pipeline_engine.py` in attractor, `runner_agent.py` in cobuilder). One session, one worker, small diff.
3. **Before Phase 3**: Phase 2 (module divergence audit). Assign to `solution-architect` or `backend-solutions-engineer`. Output is a merge decision record for all 19 conflicting modules — this is investigation and documentation, not code changes.
4. **Scheduled with pipeline quiescence**: Phase 3 (actual code migration). This is the largest implementation effort. Assign to `backend-solutions-engineer` with clear acceptance criteria from Section 12.
5. **After Phase 3**: Markdown path updates in skills/output-styles. Assign to a worker that can edit documentation files. 49 substitutions across 7 files.

**Do not combine Phase 3 with Phase 4 in the same session.** The state directory question (Phase 4) is low-risk and can be deferred indefinitely if the team decides `.claude/attractor/` is a permanent home for pipeline state.

**Key file paths relevant to implementation**:
- Pipeline state: `/Users/theb/Documents/Windsurf/claude-harness-setup/.claude/attractor/pipelines/`
- Code to migrate: `/Users/theb/Documents/Windsurf/claude-harness-setup/.claude/scripts/attractor/`
- Migration target: `/Users/theb/Documents/Windsurf/claude-harness-setup/cobuilder/`
- Output style to update: `/Users/theb/Documents/Windsurf/claude-harness-setup/.claude/output-styles/system3-meta-orchestrator.md`
- Skills to update: `/Users/theb/Documents/Windsurf/claude-harness-setup/.claude/skills/s3-guardian/references/` (7 files)
- Test suite: `/Users/theb/Documents/Windsurf/claude-harness-setup/.claude/scripts/attractor/tests/` (12,299 lines, 19 files)
- Package manifest: `/Users/theb/Documents/Windsurf/claude-harness-setup/pyproject.toml`
