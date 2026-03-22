---
title: "SD: CoBuilder Standalone Consolidation — Attractor Merge, State Relocation, Dead Code Removal"
status: active
type: architecture
last_verified: 2026-03-09
grade: authoritative
prd_ref: PRD-HARNESS-UPGRADE-001
epic: "E4-E6 (new)"
---

# SD-COBUILDER-CONSOLIDATION-001: CoBuilder Standalone Autonomous Coding Harness

## 1. Executive Summary

CoBuilder is a fully functional installable Python package (`cobuilder/`) that already contains the canonical implementations of the pipeline engine, orchestration layer, repomap (ZeroRepo), and CLI. In parallel, `.claude/scripts/attractor/` grew organically as a harness-level script collection with a flat, non-importable layout. The two share module names, state paths, and logic — but only `cobuilder/` is the right home.

This SD designs the consolidation: attractor scripts that are still active merge into `cobuilder/`, dead code is deleted, `.claude/` is restored to Claude Code convention (config only), and runtime state relocates to a project-relative `.cobuilder/` data directory following XDG-derived conventions.

**Outcome**: One canonical entry point (`cobuilder` CLI or `python -m cobuilder`), one source of truth for each module, `.claude/` containing only what Claude Code expects (settings, hooks, skills, agents), and a clean state layout that workers can locate deterministically.

**Parent PRD**: PRD-HARNESS-UPGRADE-001 (Phase 2, new epics E4-E6)

---

## 2. Hindsight Findings

Queried Hindsight (bank: `claude-code-my-project`) before finalising this design.

**Relevant prior learnings:**
- **13 dead files** in `.claude/scripts/attractor/` were identified in the 2026-03-04 cleanup audit (POC scripts, tmux-era tools, deprecated signal protocol CLIs). These are confirmed dead and safe to delete.
- **Subprocess spawning pattern** (validated 2026-03-03): use `subprocess.Popen` with `os.environ` merge, unset `CLAUDECODE` in child, consume both stdout/stderr to prevent deadlock. This must be preserved exactly in the migrated code — it is not "implementation detail noise", it is a safety invariant.
- **Signal Directory Resolution pattern** (validated 2026-03-03): priority-based fallback (`explicit override → DOT-scoped → git root`). Keep this logic unchanged; only update the root fallback path from `.cobuilder/signals/` to `.cobuilder/signals/`.
- **`agents_app` in `cobuilder/cli.py`** is an empty Typer group — confirmed dead code to wire or remove.
- **Import collision risk**: never import submodules in `__init__.py`; import specific functions to avoid circular imports (confirmed by prior Railway debugging sessions).
- **Perplexity unavailable** during this session (quota exceeded). XDG spec sourced from freedesktop.org directly via Brave Search.

---

## 3. Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Package build | `hatchling` (existing) | Already configured in `pyproject.toml`; no change |
| CLI framework | `typer` (existing) | Already used in `cobuilder/cli.py` with 17 subcommands |
| State location | `.cobuilder/` (project-relative) | Follows XDG `$XDG_DATA_HOME` pattern; project-scoped so each repo has isolated state |
| Import layout | Flat `cobuilder/` (not `src/` layout) | Already established; changing would break all existing imports |
| Dead code detection | `vulture` + manual audit | Flags unused symbols; manual review guards against dynamic imports |

---

## 4. Current State Analysis

### 4.1 Active vs. Dead Files in `.claude/scripts/attractor/`

**Dead files** — delete without migration (confirmed by 2026-03-04 audit + zero import references):

| File | Reason Dead |
|------|-------------|
| `capture_output.py` | tmux-era tool, never imported |
| `check_orchestrator_alive.py` | tmux-era tool, never imported |
| `send_to_orchestrator.py` | tmux-era tool, replaced by signal files |
| `wait_for_guardian.py` | Deprecated signal protocol CLI |
| `wait_for_signal.py` | Deprecated signal protocol CLI |
| `read_signal.py` | Deprecated signal protocol CLI |
| `respond_to_runner.py` | Deprecated signal protocol CLI |
| `escalate_to_terminal.py` | Deprecated signal protocol CLI |
| `poc_pipeline_runner.py` | POC superseded by `pipeline_runner.py` |
| `poc_test_scenarios.py` | POC superseded |
| `runner_test_scenarios.py` | Orphaned test scenarios |
| `test_logfire_guardian.py` | Debug script, not a test suite |
| `test_logfire_sdk.py` | Debug script, not a test suite |

**Root-level garbage** — delete:

```
test_*.py          (test_api.py, test_compute_sd_hash.py, test_dispatch_worker.py)
test_pipeline*.dot (test_pipeline.dot, test_pipeline_final.dot, test_pipeline_fixed.dot)
*.log              (server.log, server_test.log, server_port8080.log)
screen_*.png       (screen_bf729906a02c445ba3879c99ef5822a3.png)
private.pem        (private key — verify not committed; add to .gitignore immediately)
```

**Active attractor files already mirrored in `cobuilder/`** (attractor copies are duplicates to remove):

| attractor/ file | cobuilder/ canonical | Action |
|----------------|---------------------|--------|
| `pipeline_runner.py` | `orchestration/pipeline_runner.py` | Verify cobuilder is newer; delete attractor copy |
| `runner.py` | `orchestration/` (merged) | Verify merge complete; delete attractor copy |
| `guardian.py` | `orchestration/runner_guardian.py` | Verify equivalent; delete attractor copy |
| `spawn_orchestrator.py` | `orchestration/spawn_orchestrator.py` | Cobuilder is canonical (attractor imports cobuilder.bridge); delete attractor copy |
| `parser.py` | `engine/parser.py` | Delete attractor copy |
| `transition.py` | `pipeline/transition.py` | Delete attractor copy |
| `checkpoint.py` | `engine/checkpoint.py` + `pipeline/checkpoint.py` | Delete attractor copy |
| `signal_protocol.py` | `pipeline/signal_protocol.py` | Delete attractor copy after path update |
| `node_ops.py` | `pipeline/node_ops.py` | Delete attractor copy |
| `edge_ops.py` | `pipeline/edge_ops.py` | Delete attractor copy |
| `status.py` | `pipeline/status.py` | Delete attractor copy |
| `dashboard.py` | `pipeline/dashboard.py` | Delete attractor copy |
| `generate.py` | `pipeline/generate.py` | Delete attractor copy |
| `annotate.py` | `pipeline/annotate.py` | Delete attractor copy |
| `init_promise.py` | `pipeline/init_promise.py` | Delete attractor copy |
| `validator.py` | `pipeline/validator.py` | Delete attractor copy |
| `runner_models.py` | `orchestration/runner_models.py` | Delete attractor copy |
| `runner_tools.py` | `orchestration/runner_tools.py` | Delete attractor copy |
| `runner_hooks.py` | `orchestration/runner_hooks.py` | Delete attractor copy |
| `runner_guardian.py` | `orchestration/runner_guardian.py` | Delete attractor copy |
| `identity_registry.py` | `orchestration/identity_registry.py` | Delete attractor copy |
| `adapters/` | `orchestration/adapters/` | Delete attractor copy |

**Active attractor files with NO cobuilder mirror** (must migrate):

| File | Destination in `cobuilder/` |
|------|-----------------------------|
| `dispatch_worker.py` | `orchestration/dispatch_worker.py` |
| `anti_gaming.py` | `orchestration/anti_gaming.py` |
| `signal_guardian.py` | `orchestration/signal_guardian.py` |
| `merge_queue.py` | `orchestration/merge_queue.py` |
| `merge_queue_cmd.py` | Wire into `cli.py` as `merge_queue_app` |
| `agents_cmd.py` | Wire into `cli.py` (replaces empty `agents_app` stub) |
| `channel_bridge.py` | `orchestration/channel_bridge.py` |
| `channel_adapter.py` | `orchestration/channel_adapter.py` |
| `gchat_adapter.py` | `orchestration/adapters/gchat.py` |
| `hook_manager.py` | `engine/hook_manager.py` |
| `run_research.py` | Logic merged into `engine/handlers/research.py` or kept as `orchestration/run_research.py` |
| `run_refine.py` | Logic merged into `engine/handlers/refine.py` or kept as `orchestration/run_refine.py` |

### 4.2 Cross-Import Analysis

- **attractor → cobuilder**: exactly 1 import — `spawn_orchestrator.py` imports `cobuilder.bridge.scoped_refresh`. This confirms cobuilder is the dependency layer and attractor is the consumer. Migration direction is correct.
- **cobuilder → attractor**: zero imports. The cobuilder package is already self-contained.

### 4.3 Dead Code in `cobuilder/cli.py`

```python
# Line 16 in cobuilder/cli.py — EMPTY Typer group, no registered commands
agents_app = typer.Typer(help="Agent orchestration commands")
# Line 20
app.add_typer(agents_app, name="agents")
```

This group has no registered functions. The intent was to expose `agents_cmd.py` handlers but the wiring was never done. In E6, wire the actual handlers from `agents_cmd.py` into this group.

---

## 5. Target Architecture

### 5.1 Directory Structure

```
claude-harness-setup/
├── .claude/                          # Claude Code config ONLY
│   ├── settings.json
│   ├── output-styles/
│   ├── hooks/
│   ├── skills/
│   ├── agents/
│   ├── commands/
│   ├── scripts/
│   │   ├── completion-state/         # cs-* session promise scripts (unchanged)
│   │   └── doc-gardener/             # Lint scripts (unchanged)
│   │   # attractor/ DELETED
│   └── [other Claude Code dirs]
│
├── .cobuilder/                       # Runtime state (project-relative, gitignored)
│   ├── pipelines/                    # DOT files + run directories
│   │   └── my-pipeline-run-20260309T120000Z/
│   │       ├── signals/              # {node_id}.json per worker
│   │       ├── state.json            # RunnerState snapshot
│   │       └── audit.jsonl           # Append-only audit trail
│   ├── state/                        # Cross-run persistent state
│   │   ├── merge-queue.json
│   │   └── identity-registry.json
│   ├── examples/                     # Example DOT files (committed)
│   └── .env                          # ANTHROPIC_API_KEY, ANTHROPIC_MODEL
│
├── cobuilder/                        # Installable package (canonical, unchanged structure)
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                        # Unified Typer CLI (agents + merge-queue wired)
│   ├── bridge.py
│   ├── engine/
│   │   ├── hook_manager.py           # MIGRATED from attractor
│   │   └── [existing files unchanged]
│   ├── pipeline/
│   │   └── [existing files, signal_protocol.py updated]
│   ├── orchestration/
│   │   ├── dispatch_worker.py        # MIGRATED from attractor
│   │   ├── anti_gaming.py            # MIGRATED from attractor
│   │   ├── signal_guardian.py        # MIGRATED from attractor
│   │   ├── merge_queue.py            # MIGRATED from attractor
│   │   ├── channel_bridge.py         # MIGRATED from attractor
│   │   ├── channel_adapter.py        # MIGRATED from attractor
│   │   └── adapters/
│   │       └── gchat.py              # MIGRATED from gchat_adapter.py
│   └── repomap/                      # ZeroRepo, UNCHANGED
│
├── tests/
│   ├── unit/                         # Existing unit tests
│   └── integration/
│       └── attractor/                # 25 migrated attractor tests, imports updated
│
├── pyproject.toml                    # cb-runner entry point added
└── .gitignore                        # .cobuilder/ added
```

### 5.2 State Directory Convention (XDG-Derived)

The XDG Base Directory Specification defines three categories relevant here:

| XDG Category | Default | Our Mapping |
|-------------|---------|-------------|
| Config (`$XDG_CONFIG_HOME`) | `~/.config` | `.claude/` (already correct — Claude Code convention) |
| Data (`$XDG_DATA_HOME`) | `~/.local/share` | `.cobuilder/` (project-relative, not global) |
| Runtime (`$XDG_RUNTIME_DIR`) | `/run/user/$UID` | Inside `.cobuilder/pipelines/{run-id}/signals/` |

We use **project-relative** `.cobuilder/` rather than global `~/.local/share/cobuilder/` because:
1. Each project repo has its own pipelines — global storage requires project-path namespacing with no benefit.
2. Workers are dispatched inside a specific project's worktree; relative paths are reliable and debuggable.
3. `.cobuilder/` mirrors established patterns (`.tox/`, `.pytest_cache/`, `.mypy_cache/`).

**`.gitignore` entries to add**:
```gitignore
.cobuilder/pipelines/
.cobuilder/state/
.cobuilder/.env
```

**`.cobuilder/examples/` is committed** to git — these are the canonical example DOT files used by tests and documentation.

### 5.3 Signal Protocol Path Update

The `signal_protocol.py` resolution chain currently (in both attractor and cobuilder copies):
```
1. ATTRACTOR_SIGNAL_DIR env var override
2. DOT-scoped: {dot_dir}/signals/
3. Git root: {git_root}/.claude/attractor/signals/
4. Fallback: ~/.claude/attractor/signals/
```

After consolidation:
```
1. ATTRACTOR_SIGNAL_DIR env var override  (backward compat — unchanged)
2. DOT-scoped: {dot_dir}/signals/         (unchanged — most common path)
3. Git root: {git_root}/.cobuilder/signals/  (updated)
4. Old git root: {git_root}/.claude/attractor/signals/  (shim — remove after 30 days)
5. Fallback: ~/.cobuilder/signals/         (updated)
```

The shim at step 4 ensures existing pipeline runs using the old path continue to work during the transition window.

### 5.4 CLI Consolidation

**Before** (attractor `cli.py` is argparse, cobuilder `cli.py` is Typer):
- Two separate dispatchers for overlapping commands
- `agents_app` in cobuilder CLI is empty

**After** (single Typer app in `cobuilder/cli.py`):

```
cobuilder pipeline <subcommand>      # create, node, edge, checkpoint, annotate, ...
cobuilder run <dot-file>             # shortcut alias for cobuilder pipeline run
cobuilder guardian <subcommand>      # status, list, verify-chain, audit
cobuilder agents <subcommand>        # list, show, mark-crashed (wired from agents_cmd.py)
cobuilder merge-queue <subcommand>   # list, enqueue, process (wired from merge_queue_cmd.py)
cobuilder lint [--fix] [--json]      # doc-gardener delegate
cobuilder install-hooks [--force]    # git hook installer
```

**`pyproject.toml` entry points after consolidation**:
```toml
[project.scripts]
cobuilder = "cobuilder.__main__:main"
zerorepo = "cobuilder.repomap.cli.app:app"
cb-runner = "cobuilder.orchestration.pipeline_runner:main"  # backward compat alias
```

---

## 6. Implementation Phases

### Phase E4: Dead Code Removal + Root Cleanup

**Goal**: Eliminate noise before restructuring. Establish a clean baseline.

**Scope**:
1. Delete 13 confirmed-dead attractor scripts (see §4.1 dead files table).
2. Delete root-level garbage (`test_*.py`, `*.dot` test files, `*.log`, `screen_*.png`, `private.pem`).
3. Verify `private.pem` is not in git history; if it is, initiate a secret rotation workflow before proceeding.
4. Remove the empty `agents_app` Typer group stub from `cobuilder/cli.py` (lines 16 and 20) — but do NOT yet add handlers. The group is re-added with real handlers in E6.

**Acceptance criteria**:
- `git status` shows none of the 13 dead file names present.
- `pytest cobuilder/ tests/` passes (zero imports broken by deletions).
- `cobuilder pipeline --help` renders without error.
- `git log --all --full-history -- private.pem` returns empty.

**Risk**: Low. All files confirmed dead via import analysis.

**Effort**: 0.5 days.

---

### Phase E5: State Directory Migration

**Goal**: Move all runtime state from `.claude/attractor/` to `.cobuilder/`. Update all path constants. Install the migration shim.

**File changes**:

1. Create `.cobuilder/examples/` — copy `attractor/examples/` DOT files into it.

2. Add to `.gitignore`:
   ```
   .cobuilder/pipelines/
   .cobuilder/state/
   .cobuilder/.env
   ```

3. `cobuilder/pipeline/signal_protocol.py` — update fallback resolution chain per §5.3.

4. `cobuilder/engine/runner.py` — change constant:
   ```python
   # Before
   _DEFAULT_PIPELINES_DIR: str = ".claude/attractor/pipelines"
   # After
   _DEFAULT_PIPELINES_DIR: str = ".cobuilder/pipelines"
   ```

5. `cobuilder/engine/checkpoint.py` — update default `pipelines_dir` docstring and default arg.

6. `cobuilder/orchestration/pipeline_runner.py` — change state/audit path constants:
   ```python
   # Before (in docstring and _state_path/_audit_path)
   # .claude/attractor/state/{pipeline-id}.json
   # After
   # .cobuilder/state/{pipeline-id}.json
   ```

7. `cobuilder/orchestration/runner_tools.py` — update default state dir:
   ```python
   # Before
   os.path.expanduser("~/.claude/attractor/state")
   # After
   os.path.expanduser("~/.cobuilder/state")
   ```

8. `cobuilder/orchestration/runner_models.py` — update docstring references.

9. `.env` lookup in `dispatch_worker.py`, `run_research.py`, `run_refine.py`, `pipeline_runner.py`:
   - Search order: `{git_root}/.cobuilder/.env` → `{git_root}/.claude/attractor/.env` (shim) → `~/.cobuilder/.env`

10. `tests/unit/test_engine_parser.py` — corpus test path:
    ```python
    # Before: walks .claude/attractor/pipelines/
    # After: walks .cobuilder/examples/
    ```

11. `cobuilder/cli.py` help text — replace any `.claude/attractor/pipelines/` references.

**Acceptance criteria**:
- `python -m cobuilder pipeline status .cobuilder/examples/simple-pipeline.dot` resolves correctly.
- `ATTRACTOR_SIGNAL_DIR` env var override still works (regression test).
- `pytest tests/unit/test_engine_parser.py` finds DOT files in `.cobuilder/examples/`.
- `grep -rn '\.claude/attractor' cobuilder/` returns zero results in path constants (docstrings excluded).

**Risk**: Medium. Path changes are pervasive but mechanical. The migration shim prevents breaking active runs.

**Effort**: 1 day.

---

### Phase E6: Attractor Merge + CLI Unification

**Goal**: Fold 10 unmirrored attractor files into `cobuilder/`, wire the full CLI, migrate the test suite, delete the attractor directory.

**Sub-steps (each is a separate commit)**:

**E6a — Migrate files**:
Copy each file from §4.1 "must migrate" list to its `cobuilder/` destination. No import changes yet.

**E6b — Fix imports in migrated files**:
Each migrated file uses `sys.path.insert(0, SCRIPT_DIR)` for flat imports. Replace with package imports:

```python
# BEFORE (attractor flat-import pattern)
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from signal_protocol import resolve_signal_dir

# AFTER (cobuilder package import)
from cobuilder.pipeline.signal_protocol import resolve_signal_dir
```

Pattern applies to all migrated files. After E6b, every file under `cobuilder/` must have zero `sys.path.insert` calls.

**E6c — Wire CLI subcommands**:
```python
# In cobuilder/cli.py — add these Typer groups

merge_queue_app = typer.Typer(help="Manage the sequential merge queue")
app.add_typer(merge_queue_app, name="merge-queue")
# Wire all commands from merge_queue_cmd.py into merge_queue_app

agents_app = typer.Typer(help="Inspect and manage agent identity records")
app.add_typer(agents_app, name="agents")
# Wire all commands from agents_cmd.py into agents_app

guardian_app = typer.Typer(help="System 3 read-only pipeline monitor")
app.add_typer(guardian_app, name="guardian")
# Wire all commands from runner_guardian.py into guardian_app
```

**E6d — Migrate attractor tests**:
Move `.claude/scripts/attractor/tests/` to `tests/integration/attractor/`. Update all imports from flat references to `cobuilder.*` package imports. Verify `pytest tests/integration/` passes.

**E6e — Delete `.claude/scripts/attractor/`**:
```bash
git rm -r .claude/scripts/attractor/
```

Only run after E6d test suite passes.

**E6f — Update documentation references**:
- `CLAUDE.md` — update any reference to `cli.py` in attractor to `cobuilder` CLI.
- `.claude/skills/orchestrator-multiagent/scripts/zerorepo-run-pipeline.py` — remove the commented reference to `.claude/scripts/attractor/cli.py` (line 165).
- `docs/prds/harness-upgrade/PRD-HARNESS-UPGRADE-001.md` — add E4-E6 rows to status table.

**Acceptance criteria (full E6)**:
- `ls .claude/scripts/attractor/` fails with "No such file or directory".
- `cobuilder --help` shows: `pipeline`, `guardian`, `agents`, `merge-queue`, `lint`, `install-hooks`.
- `cobuilder guardian --help` renders correctly.
- `cobuilder agents list` runs without error.
- `cobuilder merge-queue list` runs without error.
- `pytest tests/integration/attractor/` passes (25+ tests).
- `cobuilder pipeline run .cobuilder/examples/simple-pipeline.dot --dry-run` completes successfully.
- `grep -r "scripts/attractor" .claude/skills/ .claude/hooks/ .claude/output-styles/` returns zero active references (historical `MEMORY.md` entries are acceptable).

**Risk**: Medium-High for E6b (import rewrites). The test migration in E6d is the safety net — do not proceed to E6e without a green test suite.

**Effort**: 2 days.

---

## 7. Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Attractor test imports break after directory move | High | High | Migrate + update imports in E6d before deleting in E6e |
| Hardcoded `.claude/attractor` path strings missed | Medium | High | `grep -rn '\.claude/attractor' cobuilder/` as CI check in E5 |
| `sys.path` hacks persist in migrated files | Medium | Medium | Post-E6b: `grep -rn 'sys.path.insert' cobuilder/` must return zero |
| `private.pem` in git history | Critical | Unknown | Check git history before E4; rotate credentials if found |
| Signal files from active runs lost during state move | High | Low | Migration shim reads both `.claude/attractor/` and `.cobuilder/` paths for 30 days |
| `CLAUDECODE` env var not unset in spawned subprocesses | High | Low | Carry the validated subprocess pattern from attractor verbatim; add test for this invariant |
| Empty `agents_app` group shipped in E4 without handlers | Low | Low | Remove stub in E4; re-add with real handlers in E6c |
| Attractor `.env` file not found after migration | Medium | Medium | `.env` lookup uses shim: checks `.cobuilder/.env` then falls back to `.claude/attractor/.env` |

---

## 8. Testing Strategy

### Unit Tests (existing — must stay green throughout)
- `cobuilder/engine/conditions/tests/` — condition parser, lexer, evaluator, integration
- `cobuilder/pipeline/tests/` — research nodes, status deps
- `tests/unit/` — engine parser corpus (updated path in E5)

### New Integration Tests (E6d)
- `tests/integration/attractor/` — 25 migrated attractor tests with updated `cobuilder.*` imports
- `tests/integration/test_cli_unification.py` — smoke test every `cobuilder` subcommand group
- `tests/integration/test_state_paths.py` — verify `.cobuilder/` paths resolve; verify `ATTRACTOR_SIGNAL_DIR` shim works

### Key Migration Shim Test
```python
def test_signal_protocol_env_var_override_preserved(tmp_path, monkeypatch):
    """ATTRACTOR_SIGNAL_DIR env var override must continue to take priority."""
    old_dir = tmp_path / ".claude" / "attractor" / "signals"
    old_dir.mkdir(parents=True)
    monkeypatch.setenv("ATTRACTOR_SIGNAL_DIR", str(old_dir))
    resolved = resolve_signal_dir(dot_path=None)
    assert resolved == str(old_dir)

def test_new_state_path_resolves(tmp_path, monkeypatch):
    """After migration, .cobuilder/signals/ is the git-root fallback."""
    new_dir = tmp_path / ".cobuilder" / "signals"
    new_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    resolved = resolve_signal_dir(dot_path=None)
    assert ".cobuilder" in str(resolved)
```

### CLI Smoke Tests
```bash
cobuilder --help
cobuilder pipeline --help
cobuilder pipeline status .cobuilder/examples/simple-pipeline.dot
cobuilder guardian --help
cobuilder agents --help
cobuilder merge-queue --help
cobuilder lint --help
cobuilder install-hooks --help
```

---

## 9. Migration Sequence (Strict Dependency Order)

```
E4 — Delete dead files, root garbage
  |
  v
E5 — .cobuilder/ dir + path constants + shim + test path update
  |
  v
E6a — Copy unmirrored files to cobuilder/
  |
  v
E6b — Fix sys.path imports → package imports
  |
  v
E6c — Wire CLI subcommands
  |
  v
E6d — Migrate attractor tests to tests/integration/attractor/
  |   (pytest tests/integration/ must pass before proceeding)
  v
E6e — git rm -r .claude/scripts/attractor/
  |
  v
E6f — Update documentation references
```

Each sub-step is a separate commit. Do not squash E6a-E6e — granular commits bound rollback scope.

---

## 10. Files Explicitly Out of Scope

- `cobuilder/repomap/` — ZeroRepo's 149 modules are untouched.
- `.claude/skills/` — skill files content does not change (only documentation references in E6f).
- `.claude/hooks/` — hook scripts are unrelated to attractor Python code.
- `cobuilder/engine/handlers/codergen.py` — active codergen dispatch logic; separate concern.
- `cobuilder/engine/handlers/` handlers that already exist — do not merge `run_research.py`/`run_refine.py` logic into them unless the existing handler is a stub.

---

## 11. Success Metrics

| Metric | Before | Target |
|--------|--------|--------|
| Duplicate module pairs (attractor vs cobuilder) | ~25 | 0 |
| Python scripts in `.claude/scripts/attractor/` | 75+ | 0 (dir deleted) |
| Hardcoded `.claude/attractor` path strings in `cobuilder/` | 40+ | 0 |
| Confirmed-dead files in attractor | 13 | 0 |
| Root-level garbage files | 8 | 0 |
| `cobuilder` CLI subcommand groups | 3 (1 empty) | 6 (all wired) |
| `sys.path.insert` calls in `cobuilder/` | ~12 (migrated files) | 0 |
| Test pass rate | 100% | 100% (maintained) |

---

## 12. Handoff Notes

**Agent assignment**: `backend-solutions-engineer` for all E4-E6 work (Python only, no frontend).

**Start with E4.** It is zero-risk — delete confirmed-dead files and root garbage. This establishes the clean baseline and unblocks everything else.

**Three invariants that must be preserved verbatim** when migrating subprocess spawning code:
1. `CLAUDECODE` environment variable is unset (`""`) in every spawned child process.
2. `subprocess.Popen` is used as a context manager (`with Popen(...) as proc:`).
3. Both `stdout` and `stderr` are consumed (pipe deadlock prevention).

These are validated safety properties (2026-03-03), not style preferences. Do not refactor them.

**The `ATTRACTOR_SIGNAL_DIR` env var override is a forever contract.** Existing orchestrators, pipelines, and monitoring scripts in the wild use it. It must remain resolution priority #1 in `signal_protocol.py` permanently.

**The cobuilder CLI is the integration test.** If `cobuilder pipeline status .cobuilder/examples/simple-pipeline.dot` works at the end of each phase, the migration is on track.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
