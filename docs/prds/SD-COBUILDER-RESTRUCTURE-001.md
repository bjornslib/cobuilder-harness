---
title: "SD-COBUILDER-RESTRUCTURE-001: CoBuilder Standalone Harness Restructure"
status: active
type: reference
last_verified: 2026-03-09
grade: authoritative
---

# SD-COBUILDER-RESTRUCTURE-001: CoBuilder Standalone Harness Restructure

## Executive Summary

This document specifies the reverse-engineered migration path from the current
intermingled state — where ~19,836 lines of pipeline execution Python live in
`.claude/scripts/attractor/` alongside 367 runtime DOT files scattered in
`.claude/attractor/` — to the ideal target state where `cobuilder/` is a
pip-installable Python package containing all application code and `data/`
holds all runtime state, leaving `.claude/` with only Claude Code native
configuration.

Working backwards from the ideal: a developer arriving at this repo for the
first time should be able to run `pip install -e .` and have full `cobuilder`
CLI capability; no Python should live under `.claude/`; all runtime artifacts
(DOT files, signals, checkpoints) should be in `data/`; and `.claude/` should
contain nothing that would break if deleted and restored from git.

**Hindsight findings**: Prior session analysis confirmed that staged extraction
(not big-bang moves), ownership-by-namespace rules, and shim imports for
backward compatibility are the validated patterns for monorepo consolidation.
The import-collision risk (same module names in two trees) is the primary
structural hazard — the audit below identifies 21 name-conflicting files.

---

## 1. Current State Inventory

### 1.1 The Two Parallel Python Trees

The codebase currently has two Python implementations of the same concepts:

| Component | `.claude/scripts/attractor/` (19,836 lines) | `cobuilder/` (70K+ lines) |
|-----------|---------------------------------------------|---------------------------|
| Pipeline runner (LLM-based) | `pipeline_runner.py` (1,669 lines) | `orchestration/pipeline_runner.py` (600 lines) |
| Runner state machine (pure Python) | `pipeline_runner.py` also contains `RunnerStateMachine` | `engine/runner.py` (802 lines) |
| Graph parser | `parser.py` (355 lines) | `pipeline/parser.py` + `engine/parser.py` |
| DOT transitions | `transition.py` (921 lines) | `pipeline/transition.py` |
| Signal protocol | `signal_protocol.py` (448 lines) | `pipeline/signal_protocol.py` |
| Validator | `validator.py` (904 lines) | `engine/validation/validator.py` |
| Checkpoint | `checkpoint.py` | `pipeline/checkpoint.py` + `engine/checkpoint.py` |
| Node/Edge ops | `node_ops.py` (751), `edge_ops.py` (685) | `pipeline/node_ops.py` + `pipeline/edge_ops.py` |
| Spawn orchestrator | `spawn_orchestrator.py` (492) | `orchestration/spawn_orchestrator.py` (386) |
| Runner models | `runner_models.py` | `orchestration/runner_models.py` |
| Runner hooks | `runner_hooks.py` (398) | `orchestration/runner_hooks.py` |
| Runner tools | `runner_tools.py` (850) | `orchestration/runner_tools.py` |
| Identity registry | `identity_registry.py` (469) | `orchestration/identity_registry.py` |

**Key insight**: The attractor versions use bare relative imports (`from parser import ...`) while the cobuilder versions use package-qualified imports (`from cobuilder.engine.parser import ...`). The attractor files add themselves to `sys.path` at startup. This is the `_THIS_DIR` anti-pattern documented in Hindsight.

### 1.2 Files Unique to Attractor (No cobuilder Counterpart)

These files exist only in `.claude/scripts/attractor/` and must be placed:

| File | Lines | Disposition |
|------|-------|-------------|
| `guardian.py` | 1,153 | → `cobuilder/orchestration/guardian.py` (replaces current stub) |
| `runner.py` | 1,426 | → `cobuilder/orchestration/runner_agent.py` (renamed to avoid collision with `engine/runner.py`) |
| `dispatch_worker.py` | 264 | → `cobuilder/orchestration/dispatch_worker.py` |
| `run_research.py` | 334 | → `cobuilder/orchestration/run_research.py` |
| `run_refine.py` | 342 | → `cobuilder/orchestration/run_refine.py` |
| `anti_gaming.py` | 379 | → `cobuilder/orchestration/anti_gaming.py` |
| `hook_manager.py` | 408 | → `cobuilder/orchestration/hook_manager.py` |
| `annotate.py` | 385 | → `cobuilder/pipeline/annotate.py` (already there — see conflict table) |
| `merge_queue.py` | 446 | → `cobuilder/orchestration/merge_queue.py` |
| `channel_bridge.py` | 472 | → `cobuilder/orchestration/channel_bridge.py` |
| `gchat_adapter.py` | 470 | → `cobuilder/orchestration/gchat_adapter.py` |
| `channel_adapter.py` | — | → `cobuilder/orchestration/channel_adapter.py` |
| `signal_guardian.py` | — | → `cobuilder/orchestration/signal_guardian.py` |
| `runner_guardian.py` | 535 | → `cobuilder/orchestration/runner_guardian.py` |
| `init_promise.py` | 331 | → `cobuilder/pipeline/init_promise.py` (already there — conflict) |
| `generate.py` | 777 | → `cobuilder/pipeline/generate.py` (already there — conflict) |
| `dashboard.py` | 432 | → `cobuilder/pipeline/dashboard.py` (already there — conflict) |
| `status.py` | — | → `cobuilder/pipeline/status.py` (already there — conflict) |
| `agents_cmd.py` | — | → `cobuilder/orchestration/agents_cmd.py` |
| `merge_queue_cmd.py` | — | → `cobuilder/orchestration/merge_queue_cmd.py` |
| `identity_registry.py` | 469 | → `cobuilder/orchestration/identity_registry.py` (conflict) |

### 1.3 Dead Code to Delete (No Migration Needed)

Based on the March 4, 2026 cleanup analysis in Hindsight, these files are confirmed obsolete:

| File | Reason |
|------|--------|
| `poc_pipeline_runner.py` | POC superseded by `pipeline_runner.py` |
| `poc_test_scenarios.py` | POC test file, no production use |
| `runner_test_scenarios.py` | Superseded by proper test suite |
| `test_logfire_guardian.py` | Debug script, not a real test |
| `test_logfire_sdk.py` | Debug script, not a real test |
| `capture_output.py` | Tmux-era tool, replaced by headless |
| `check_orchestrator_alive.py` | Tmux-era tool |
| `send_to_orchestrator.py` | Tmux-era tool |
| `wait_for_guardian.py` | Deprecated signal protocol CLI |
| `wait_for_signal.py` | Deprecated signal protocol CLI |
| `read_signal.py` | Deprecated signal protocol CLI |
| `respond_to_runner.py` | Deprecated signal protocol CLI |
| `escalate_to_terminal.py` | Deprecated signal protocol CLI |
| `adapters/message_bus.py` | Unused (pycache shows it was compiled but no source found in current state) |

### 1.4 Runtime State (NOT Source Code)

These live in `.claude/attractor/` and must move to `data/`:

| Current Path | Target Path | Count/Size |
|---|---|---|
| `.claude/attractor/pipelines/*.dot` | `data/pipelines/` | 367 files |
| `.claude/attractor/signals/` | `data/signals/` | 8 files currently |
| `.claude/attractor/checkpoints/` | `data/checkpoints/` | 3 files |
| `.claude/attractor/runner-state/` | `data/runner-state/` | 36 files |
| `.claude/attractor/examples/` | `data/examples/` | 9 DOT files |
| Root `test_*.dot` files | `data/examples/` | 4 files |
| Root `test_*.py` files | deleted (integration tests) | 4 files |
| Root `screen_*.png`, `*.log` | deleted | artefacts |

---

## 2. Target Directory Structure

```
claude-harness-setup/
├── .claude/                           # ONLY Claude Code native config
│   ├── settings.json
│   ├── output-styles/
│   │   ├── orchestrator.md
│   │   └── system3-meta-orchestrator.md
│   ├── hooks/
│   ├── skills/
│   ├── commands/
│   ├── agents/
│   ├── documentation/
│   ├── schemas/
│   └── tests/
│
├── cobuilder/                         # THE autonomous coding harness
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                         # Unified CLI entry point
│   ├── bridge.py
│   │
│   ├── engine/                        # Pure Python DOT execution engine (existing)
│   │   ├── runner.py                  # EngineRunner state machine
│   │   ├── parser.py
│   │   ├── checkpoint.py
│   │   ├── graph.py
│   │   ├── context.py
│   │   ├── edge_selector.py
│   │   ├── loop_detection.py
│   │   ├── outcome.py
│   │   ├── exceptions.py
│   │   ├── conditions/
│   │   ├── events/
│   │   ├── handlers/
│   │   ├── middleware/
│   │   └── validation/
│   │       ├── validator.py           # REPLACE with attractor validator.py content
│   │       ├── rules.py
│   │       └── advanced_rules.py
│   │
│   ├── pipeline/                      # DOT pipeline management (existing + attractor)
│   │   ├── __init__.py
│   │   ├── annotate.py                # MERGE: attractor wins (more recent)
│   │   ├── checkpoint.py              # MERGE: attractor wins
│   │   ├── dashboard.py               # MERGE: attractor wins
│   │   ├── dot_context.py
│   │   ├── edge_ops.py                # MERGE: attractor wins
│   │   ├── generate.py                # MERGE: attractor wins
│   │   ├── init_promise.py            # MERGE: attractor wins
│   │   ├── node_ops.py                # MERGE: attractor wins
│   │   ├── parser.py                  # MERGE: attractor wins
│   │   ├── sd_enricher.py
│   │   ├── signal_protocol.py         # MERGE: attractor wins
│   │   ├── status.py                  # MERGE: attractor wins
│   │   ├── taskmaster_bridge.py
│   │   ├── transition.py              # MERGE: attractor wins (921 lines vs cobuilder)
│   │   ├── validator.py               # MERGE: attractor wins (904 lines vs engine/validation)
│   │   └── enrichers/
│   │
│   ├── orchestration/                 # Agent/worker orchestration (existing + attractor)
│   │   ├── __init__.py
│   │   ├── adapters/
│   │   │   ├── base.py
│   │   │   ├── native_teams.py
│   │   │   └── stdout.py
│   │   ├── anti_gaming.py             # NEW from attractor
│   │   ├── agents_cmd.py              # NEW from attractor
│   │   ├── channel_adapter.py         # NEW from attractor
│   │   ├── channel_bridge.py          # NEW from attractor
│   │   ├── dispatch_worker.py         # NEW from attractor
│   │   ├── gchat_adapter.py           # NEW from attractor
│   │   ├── guardian.py                # NEW from attractor (guardian.py)
│   │   ├── hook_manager.py            # NEW from attractor
│   │   ├── identity_registry.py       # MERGE: attractor wins (469 lines)
│   │   ├── merge_queue.py             # NEW from attractor
│   │   ├── merge_queue_cmd.py         # NEW from attractor
│   │   ├── pipeline_runner.py         # MERGE: attractor wins (1,669 lines)
│   │   ├── run_refine.py              # NEW from attractor
│   │   ├── run_research.py            # NEW from attractor
│   │   ├── runner_agent.py            # RENAMED from attractor runner.py (1,426 lines)
│   │   ├── runner_guardian.py         # NEW from attractor
│   │   ├── runner_hooks.py            # MERGE: attractor wins (398 lines)
│   │   ├── runner_models.py           # MERGE: attractor wins
│   │   ├── runner_tools.py            # MERGE: attractor wins (850 lines)
│   │   ├── signal_guardian.py         # NEW from attractor
│   │   └── spawn_orchestrator.py      # MERGE: attractor wins (492 lines)
│   │
│   └── repomap/                       # ZeroRepo codebase intelligence (unchanged)
│       └── [existing structure unchanged]
│
├── data/                              # Runtime state (gitignored)
│   ├── pipelines/                     # ← from .claude/attractor/pipelines/ (367 files)
│   ├── signals/                       # ← from .claude/attractor/signals/
│   ├── checkpoints/                   # ← from .claude/attractor/checkpoints/
│   ├── runner-state/                  # ← from .claude/attractor/runner-state/
│   └── examples/                      # ← from .claude/attractor/examples/ + root test_*.dot
│
├── docs/
├── acceptance-tests/
├── pyproject.toml                     # Updated entry points
└── CLAUDE.md
```

---

## 3. File-by-File Mapping: Attractor → CoBuilder

### 3.1 Conflict Resolution Rules

When the same filename exists in both attractor and cobuilder, the rule is:

**The attractor version wins** in all cases where the files share the same
semantic role, because:
1. Attractor versions are larger and more recent (e.g. `transition.py` 921 vs
   cobuilder's version; `runner_tools.py` 850 vs cobuilder's 850 — same origin).
2. Cobuilder's orchestration/ files are known to be older copies of attractor
   files (confirmed by identical docstrings and identical `_THIS_DIR` patterns).
3. The `engine/` module is the exception — it contains the *new* pure-Python
   engine that *supersedes* the LLM-based orchestration/pipeline_runner.

**Exception rule for `runner.py`**: The attractor `runner.py` (1,426 lines,
"Runner Agent — Layer 2") becomes `cobuilder/orchestration/runner_agent.py`
to avoid collision with `cobuilder/engine/runner.py` (802 lines,
`EngineRunner` — the pure Python state machine). These are genuinely different
things with different responsibilities.

### 3.2 Complete Migration Table

| Attractor Source | Target in CoBuilder | Resolution |
|-----------------|---------------------|------------|
| `pipeline_runner.py` (1,669L) | `orchestration/pipeline_runner.py` | Attractor wins — replace |
| `runner.py` (1,426L) | `orchestration/runner_agent.py` | Renamed to avoid engine collision |
| `guardian.py` (1,153L) | `orchestration/guardian.py` | New file, no conflict |
| `transition.py` (921L) | `pipeline/transition.py` | Attractor wins — replace |
| `validator.py` (904L) | `pipeline/validator.py` | Attractor wins — replace |
| `runner_tools.py` (850L) | `orchestration/runner_tools.py` | Attractor wins — replace |
| `node_ops.py` (751L) | `pipeline/node_ops.py` | Attractor wins — replace |
| `generate.py` (777L) | `pipeline/generate.py` | Attractor wins — replace |
| `edge_ops.py` (685L) | `pipeline/edge_ops.py` | Attractor wins — replace |
| `runner_test_scenarios.py` | DELETED | Obsolete |
| `poc_pipeline_runner.py` | DELETED | Obsolete |
| `poc_test_scenarios.py` | DELETED | Obsolete |
| `runner_guardian.py` (535L) | `orchestration/runner_guardian.py` | New file |
| `signal_protocol.py` (448L) | `pipeline/signal_protocol.py` | Attractor wins — replace |
| `merge_queue.py` (446L) | `orchestration/merge_queue.py` | New file |
| `identity_registry.py` (469L) | `orchestration/identity_registry.py` | Attractor wins — replace |
| `hook_manager.py` (408L) | `orchestration/hook_manager.py` | New file |
| `runner_hooks.py` (398L) | `orchestration/runner_hooks.py` | Attractor wins — replace |
| `annotate.py` (385L) | `pipeline/annotate.py` | Attractor wins — replace |
| `anti_gaming.py` (379L) | `orchestration/anti_gaming.py` | New file |
| `init_promise.py` (331L) | `pipeline/init_promise.py` | Attractor wins — replace |
| `run_refine.py` (342L) | `orchestration/run_refine.py` | New file |
| `run_research.py` (334L) | `orchestration/run_research.py` | New file |
| `parser.py` (355L) | `pipeline/parser.py` | Attractor wins — replace |
| `checkpoint.py` | `pipeline/checkpoint.py` | Attractor wins — replace |
| `status.py` | `pipeline/status.py` | Attractor wins — replace |
| `dashboard.py` (432L) | `pipeline/dashboard.py` | Attractor wins — replace |
| `channel_bridge.py` (472L) | `orchestration/channel_bridge.py` | New file |
| `gchat_adapter.py` (470L) | `orchestration/gchat_adapter.py` | New file |
| `channel_adapter.py` | `orchestration/channel_adapter.py` | New file |
| `dispatch_worker.py` (264L) | `orchestration/dispatch_worker.py` | New file |
| `signal_guardian.py` | `orchestration/signal_guardian.py` | New file |
| `agents_cmd.py` | `orchestration/agents_cmd.py` | New file |
| `merge_queue_cmd.py` | `orchestration/merge_queue_cmd.py` | New file |
| `adapters/base.py` | `orchestration/adapters/base.py` | Already exists — verify identical |
| `adapters/native_teams.py` | `orchestration/adapters/native_teams.py` | Already exists — verify identical |
| `adapters/stdout.py` | `orchestration/adapters/stdout.py` | Already exists — verify identical |
| `cli.py` | `cli.py` (cobuilder's unified CLI, extended) | Attractor CLI merged INTO cobuilder CLI |
| `test_logfire_guardian.py` | DELETED | Debug script |
| `test_logfire_sdk.py` | DELETED | Debug script |
| `capture_output.py` | DELETED | Tmux-era |
| `check_orchestrator_alive.py` | DELETED | Tmux-era |
| `send_to_orchestrator.py` | DELETED | Tmux-era |
| `wait_for_guardian.py` | DELETED | Deprecated CLI |
| `wait_for_signal.py` | DELETED | Deprecated CLI |
| `read_signal.py` | DELETED | Deprecated CLI |
| `respond_to_runner.py` | DELETED | Deprecated CLI |
| `escalate_to_terminal.py` | DELETED | Deprecated CLI |
| `tests/*` | `cobuilder/orchestration/tests/` | Move test directory |

---

## 4. Import Rewrite Strategy

### 4.1 The `_THIS_DIR` Anti-Pattern

Every attractor file contains:
```python
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
```

This must be removed from every migrated file. Once inside the `cobuilder`
package, all imports become package-qualified.

### 4.2 Import Translation Table

| Old bare import (attractor) | New package import (cobuilder) |
|-----------------------------|-------------------------------|
| `from parser import parse_file, parse_dot` | `from cobuilder.pipeline.parser import parse_file, parse_dot` |
| `from transition import apply_transition, VALID_TRANSITIONS` | `from cobuilder.pipeline.transition import apply_transition, VALID_TRANSITIONS` |
| `from checkpoint import save_checkpoint` | `from cobuilder.pipeline.checkpoint import save_checkpoint` |
| `from signal_protocol import wait_for_signal` | `from cobuilder.pipeline.signal_protocol import wait_for_signal` |
| `from validator import VALID_HANDLERS` | `from cobuilder.pipeline.validator import VALID_HANDLERS` |
| `from dispatch_worker import load_attractor_env` | `from cobuilder.orchestration.dispatch_worker import load_attractor_env` |
| `from identity_registry import ...` | `from cobuilder.orchestration.identity_registry import ...` |
| `from hook_manager import ...` | `from cobuilder.orchestration.hook_manager import ...` |
| `from runner_models import RunnerState` | `from cobuilder.orchestration.runner_models import RunnerState` |
| `from runner_hooks import RunnerHooks` | `from cobuilder.orchestration.runner_hooks import RunnerHooks` |
| `from anti_gaming import ...` | `from cobuilder.orchestration.anti_gaming import ...` |
| `from adapters import ChannelAdapter, create_adapter` | `from cobuilder.orchestration.adapters import ChannelAdapter, create_adapter` |
| `from guardian import _run_agent` | `from cobuilder.orchestration.guardian import _run_agent` |

### 4.3 Backward Compatibility Shim (Optional, Time-Boxed 30 Days)

If any external script still invokes attractor files directly, a thin shim
`__init__.py` in `.claude/scripts/attractor/` can re-export from cobuilder:

```python
# .claude/scripts/attractor/__init__.py (SHIM — delete after 30 days)
from cobuilder.pipeline.parser import *  # noqa: F401,F403
from cobuilder.pipeline.transition import *  # noqa: F401,F403
```

However, given that the only callers of `.claude/scripts/attractor/*.py` are:
- `system3-meta-orchestrator.md` (hardcoded `python3 .claude/scripts/attractor/pipeline_runner.py`)
- `s3-guardian/SKILL.md` (same path)
- `orchestrator-multiagent/SKILL.md`

...it is simpler to update those 3 references to point at the cobuilder CLI
than to maintain a shim. The shim is only needed for the 5 surviving test
files in `.claude/scripts/attractor/tests/`.

---

## 5. Runtime State Migration (367 DOT Files)

### 5.1 Current State of .claude/attractor/

```
.claude/attractor/
├── pipelines/          367 .dot files (pipeline definitions)
├── examples/             9 .dot files (test/reference pipelines)
├── signals/              8 .json files (active worker signals)
├── checkpoints/          3 checkpoint files
├── runner-state/        36 log/state files
└── docs/, schema.md, ATTRACTOR-E2E-ANALYSIS.md (documentation)
```

Additionally at the repo root: `test_pipeline.dot`, `test_pipeline_final.dot`,
`test_pipeline_fixed.dot` (from E0 implementation tests).

### 5.2 Migration Approach

The 367 DOT files represent **active project pipeline state**. They are not
source code; they are runtime data analogous to a database. The migration is:

**Step 1: Create `data/` as top-level directory** (gitignored for runtime
state, but `data/examples/` committed as reference pipelines).

**Step 2: `git mv` the pipelines directory** (preserves git history):
```bash
mkdir -p data/pipelines data/signals data/checkpoints data/runner-state data/examples
git mv .claude/attractor/pipelines data/pipelines 2>/dev/null || cp -r .claude/attractor/pipelines/* data/pipelines/
git mv .claude/attractor/examples/*.dot data/examples/
git mv test_pipeline*.dot data/examples/
```

**Step 3: Update `.gitignore`** to exclude runtime state:
```
data/signals/
data/checkpoints/
data/runner-state/
data/pipelines/*.json
```
but commit `data/pipelines/*.dot` and `data/examples/*.dot`.

### 5.3 Hardcoded Signal Path Updates

The signal protocol library resolves the signal directory via this precedence:
1. Explicit `signals_dir` argument
2. `ATTRACTOR_SIGNALS_DIR` environment variable
3. `{git_root}/.claude/attractor/signals/` (git walk fallback)
4. `~/.claude/attractor/signals/` (home fallback)

**Fix**: Update fallback #3 in `cobuilder/pipeline/signal_protocol.py` to:
```python
# NEW fallback order:
# 3. {git_root}/data/signals/
# 4. ~/.claude/attractor/signals/  (legacy fallback, warn if used)
```

**Also update** `cobuilder/engine/runner.py` line 119:
```python
# Old:
_DEFAULT_PIPELINES_DIR: str = ".claude/attractor/pipelines"
# New:
_DEFAULT_PIPELINES_DIR: str = "data/pipelines"
```

**And** `cobuilder/engine/checkpoint.py` lines 160, 198:
```python
# Old references to ".claude/attractor/pipelines"
# New: "data/pipelines"
```

**And** skills/output-styles that reference `pipeline_runner.py` directly:
- `.claude/output-styles/system3-meta-orchestrator.md` line 600, 842
- `.claude/skills/s3-guardian/SKILL.md` lines 260-261
- `.claude/skills/orchestrator-multiagent/SKILL.md` lines 381, 387

These should reference the new `cobuilder pipeline run` CLI command instead
of the raw Python invocation.

---

## 6. pyproject.toml Updates

The `pyproject.toml` gains two new entry points for the attractor-derived
commands that become proper CLI subcommands:

```toml
[project.scripts]
cobuilder = "cobuilder.__main__:main"
zerorepo = "cobuilder.repomap.cli.app:app"
# Existing entry points above remain unchanged.

# New: cobuilder pipeline run = pipeline_runner entry point
# This is handled via the unified cobuilder CLI (typer subcommand),
# not a separate script entry point.
```

The `cobuilder pipeline run <dot-file>` subcommand (already stubbed in
`cobuilder/cli.py`'s `pipeline_app`) gets wired to
`cobuilder.orchestration.pipeline_runner:main` as its implementation.

The `cobuilder pipeline spawn` subcommand calls
`cobuilder.orchestration.spawn_orchestrator:main`.

No new top-level script entry points are added — all functionality routes
through the unified `cobuilder` CLI.

---

## 7. Implementation Phases

### Phase 1: Baseline (Zero Risk — No Behavior Change)

**Objective**: Prove the package structure is sound before moving attractor files.

**Tasks**:
1. Verify all `cobuilder/orchestration/` imports work correctly as a package
   (run `python -c "from cobuilder.orchestration import pipeline_runner"`)
2. Add `data/` directory structure with `.gitkeep` files
3. Update `.gitignore` to exclude `data/signals/`, `data/runner-state/`,
   `data/checkpoints/`; keep `data/examples/` and `data/pipelines/` committed
4. Update `pyproject.toml` `testpaths` to include `cobuilder/**/tests/`

**Acceptance**: `pip install -e .` succeeds; `cobuilder --help` shows all
subcommands; existing `cobuilder/engine/` tests pass.

---

### Phase 2: Dead Code Removal (Low Risk)

**Objective**: Delete confirmed-dead files from attractor before the main migration,
reducing noise.

**Tasks** (13 files deleted):
1. Delete the 5 tmux-era tools: `capture_output.py`, `check_orchestrator_alive.py`,
   `send_to_orchestrator.py`, `wait_for_guardian.py`, `wait_for_signal.py`
2. Delete the 5 deprecated signal protocol CLIs: `read_signal.py`,
   `respond_to_runner.py`, `escalate_to_terminal.py`, `merge_queue_cmd.py` (moved
   to orchestration if referenced), `agents_cmd.py` (same)
3. Delete the 3 debug/POC files: `test_logfire_guardian.py`, `test_logfire_sdk.py`,
   `poc_pipeline_runner.py`, `poc_test_scenarios.py`, `runner_test_scenarios.py`

**Verification**: Run attractor test suite. Only 6 active test files should remain:
`test_runner_hooks.py`, `test_dot_schema_extensions.py`, `test_e2e_resilience.py`,
`test_gchat_adapter.py`, `test_runner_state_machine.py`, `test_status_deps_met.py`
(plus `conftest.py`).

---

### Phase 3: Core Migration — Pipeline Module (Medium Risk)

**Objective**: Replace cobuilder/pipeline/ files with attractor versions.

**Sub-tasks in dependency order** (deepest dependencies first):

3.1 `parser.py` — no upstream attractor deps; replace `cobuilder/pipeline/parser.py`
    - Remove `_THIS_DIR` sys.path hack
    - Change bare imports to package-qualified
    - Run `cobuilder/pipeline/tests/test_status_deps_met.py`

3.2 `transition.py` — depends on `parser`; replace `cobuilder/pipeline/transition.py`
    - Update signal path references from `.claude/attractor/signals/` to `data/signals/`

3.3 `signal_protocol.py` — standalone; replace `cobuilder/pipeline/signal_protocol.py`
    - Update fallback path #3 from `.claude/attractor/signals/` to `data/signals/`

3.4 `node_ops.py`, `edge_ops.py` — depends on `parser`; replace in `pipeline/`

3.5 `checkpoint.py` — depends on `parser`, `transition`; replace

3.6 `validator.py` — depends on `parser`, `node_ops`, `edge_ops`; replace
    `cobuilder/pipeline/validator.py` (NOT `engine/validation/validator.py` —
    these serve different purposes; the engine validator validates engine rules,
    the pipeline validator validates DOT schema)

3.7 `annotate.py`, `status.py`, `dashboard.py`, `generate.py` — replace in `pipeline/`

3.8 `init_promise.py` — replace in `pipeline/`

**Verification after each step**: `pytest cobuilder/pipeline/tests/`

---

### Phase 4: Core Migration — Orchestration Module (Higher Risk)

**Objective**: Migrate attractor orchestration scripts into `cobuilder/orchestration/`.

**Sub-tasks**:

4.1 `identity_registry.py` — replace existing; no import changes needed beyond
    removing `_THIS_DIR`

4.2 `hook_manager.py` — new file; add to `orchestration/`

4.3 `runner_models.py` — replace existing; update imports

4.4 `runner_hooks.py` — replace existing; update `from runner_models import` →
    `from cobuilder.orchestration.runner_models import`

4.5 `dispatch_worker.py` — new file; update the `.claude/attractor/.env` path
    reference:
    ```python
    # Old: walks up from script to find .claude/attractor/.env
    # New: looks for data/.env or ATTRACTOR_ENV_FILE env var, falls back to
    #      {project_root}/.claude/attractor/.env for backward compatibility
    ```

4.6 `run_research.py`, `run_refine.py` — new files; update `from dispatch_worker`
    import

4.7 `anti_gaming.py` — new file

4.8 `spawn_orchestrator.py` — replace existing; update imports

4.9 `runner_tools.py` — replace existing; update `CLI_PATH` reference:
    ```python
    # Old:  CLI_PATH = os.path.join(_THIS_DIR, "cli.py")
    # New:  CLI_PATH = "cobuilder"  # Use the installed CLI entry point
    ```

4.10 `pipeline_runner.py` — replace existing; this is the most complex file
     (1,669 lines). Update:
     - All bare imports → package imports
     - `from checkpoint import` → `from cobuilder.pipeline.checkpoint import`
     - `from parser import` → `from cobuilder.pipeline.parser import`
     - `from transition import` → `from cobuilder.pipeline.transition import`
     - Signal path defaults: `.claude/attractor/signals/` → `data/signals/`

4.11 `guardian.py` — new file `orchestration/guardian.py`; update
     `from dispatch_worker import` → package import

4.12 `runner.py` → `runner_agent.py` — copy with rename; update all imports

4.13 `runner_guardian.py` — new file; update imports

4.14 `channel_adapter.py`, `channel_bridge.py`, `gchat_adapter.py` — new files

4.15 `signal_guardian.py` — new file

4.16 `merge_queue.py` — new file; depends on `signal_protocol`

4.17 Verify adapters match: compare `attractor/adapters/` against
     `orchestration/adapters/`; they should be identical (both originated from
     the same source); keep one copy

**Verification**: Run attractor test suite pointed at new package location.

---

### Phase 5: Runtime State Migration

**Objective**: Move 367 DOT files and runtime state to `data/`.

**Tasks**:
5.1 Create `data/` structure
5.2 `git mv .claude/attractor/pipelines data/pipelines`
5.3 `git mv .claude/attractor/examples data/examples`
5.4 Move (not git mv) runtime state: `signals/`, `checkpoints/`, `runner-state/`
5.5 Move root test_*.dot files to `data/examples/`
5.6 Update `.gitignore`
5.7 Update `cobuilder/engine/runner.py` `_DEFAULT_PIPELINES_DIR`
5.8 Update `cobuilder/engine/checkpoint.py` pipelines dir references

---

### Phase 6: CLI Unification and Reference Updates

**Objective**: Wire attractor commands into the cobuilder CLI; update all
prose references in skills and output styles.

**Tasks**:
6.1 Add `cobuilder pipeline run <dot-file>` command to `cobuilder/cli.py`
    wired to `cobuilder.orchestration.pipeline_runner`
6.2 Add `cobuilder pipeline spawn` command wired to
    `cobuilder.orchestration.spawn_orchestrator`
6.3 Add `cobuilder orchestration research` and `cobuilder orchestration refine`
    wired to `run_research.py` and `run_refine.py`
6.4 Update `.claude/output-styles/system3-meta-orchestrator.md`:
    - Line 600: `python3 .claude/scripts/attractor/pipeline_runner.py --dot-file <path>`
      → `cobuilder pipeline run <path>`
    - Line 842: same update
6.5 Update `.claude/skills/s3-guardian/SKILL.md`:
    - Lines 260-261: `python3 .claude/scripts/attractor/pipeline_runner.py` →
      `cobuilder pipeline run`
    - Signal directory reference: `.claude/attractor/signals/` → `data/signals/`
6.6 Update `.claude/skills/orchestrator-multiagent/SKILL.md`:
    - Lines 381, 387: `.claude/attractor/pipelines/` → `data/pipelines/`
6.7 Delete `data/examples/test_pipeline*.dot` (these were integration test artifacts)
6.8 Delete root-level `test_api.py`, `test_compute_sd_hash.py`,
    `test_dispatch_worker.py` (stale integration test files)

---

### Phase 7: Test Suite Relocation

**Objective**: Move attractor tests to cobuilder package tests directory.

**Tasks**:
7.1 `git mv .claude/scripts/attractor/tests/ cobuilder/orchestration/tests/`
7.2 Update conftest.py: remove `sys.path.insert(0, attractor_dir)` hacks,
    replace with proper package imports
7.3 Update `pyproject.toml` `testpaths` to include `cobuilder/orchestration/tests/`
7.4 Run `pytest cobuilder/orchestration/tests/` to verify green

---

### Phase 8: Final Cleanup

**Objective**: Remove the now-empty `.claude/scripts/attractor/` tree.

**Tasks**:
8.1 Verify `.claude/scripts/attractor/` is empty (or contains only `__pycache__/`)
8.2 `git rm -r .claude/scripts/attractor/`
8.3 Update any `sys.path` references to attractor in surviving scripts
8.4 Run full test suite: `pytest cobuilder/` and `pytest tests/`
8.5 Verify `pip install -e .` and `cobuilder --help` work cleanly
8.6 Remove root-level misplaced files: `API_README.md`, `IMPLEMENTATION_VERIFICATION_E3.md`,
    `E0-IMPL-PIPELINE-PROGRESS-MONITOR-SUMMARY.md` (move to `docs/` or delete)

---

## 8. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Import resolution breaks at runtime due to `_THIS_DIR` removal | Medium | High | Run each file's test immediately after migration; keep shim in `__init__.py` for 30 days |
| `pipeline_runner.py` subprocess spawns itself by path (`python3 /path/to/pipeline_runner.py`) | Medium | High | Audit all `subprocess.Popen` calls in `pipeline_runner.py` for self-referential paths; replace with `sys.executable -m cobuilder.orchestration.pipeline_runner` |
| Signal files from in-flight pipelines use old `.claude/attractor/signals/` path | Low | Medium | `ATTRACTOR_SIGNALS_DIR` env var override allows old path during transition; keep fallback #3 pointing to old path for 60 days |
| 367 DOT files: git history lost on `cp` vs `git mv` | Low | Low | Use `git mv` explicitly; DOT files are text, history reconstructable from git blame |
| Skills/output-styles updated but cached in Claude session | Low | Medium | Changes take effect on next session start; no special mitigation needed |
| `runner_tools.py` CLI_PATH points to attractor `cli.py` (absolute path) | High | High | Phase 4.9 explicitly addresses: replace with `cobuilder` entry point |
| Attractor `cli.py` and cobuilder `cli.py` merge conflict | High | Medium | Attractor `cli.py` provides the `attractor` CLI (pipeline/annotate/status/etc.); cobuilder `cli.py` provides the unified app. Merge by adding attractor's subcommands as `cobuilder pipeline` subcommands |
| `.claude/attractor/.env` path in `dispatch_worker.py` | Medium | Low | Update with env-var-based fallback; backward compat for 60 days |
| Same-named tests in both directories cause pytest collection conflicts | Medium | Low | Rename attractor tests to `test_attractor_*.py` prefix during Phase 7 |

### High-Priority Pre-Migration Checks

Before starting Phase 3, verify:
1. `python -m cobuilder.orchestration.pipeline_runner --help` works (package is importable)
2. The attractor `tests/` all pass pointing at current attractor directory
3. Git history is clean on `feat/harness-upgrade-e4-e6` branch

---

## 9. `pyproject.toml` Final State

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cobuilder"
version = "0.2.0"
description = "CoBuilder: unified autonomous coding harness (pipeline + repomap + orchestration)"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0,<3.0",
    "litellm>=1.0",
    "jinja2>=3.1",
    "chromadb>=0.5",
    "typer>=0.9",
    "rich>=13.0",
    "anthropic>=0.40",       # Added: used by orchestration/pipeline_runner.py
    "watchdog>=4.0",         # Added: used by pipeline_runner.py signal watching
    "logfire>=1.0",          # Added: used by guardian.py instrumentation
    "pyyaml>=6.0",           # Added: used by dispatch_worker.py
    "claude-code-sdk",       # Added: used by guardian.py, run_research.py, run_refine.py
]

[project.scripts]
cobuilder = "cobuilder.__main__:main"
zerorepo = "cobuilder.repomap.cli.app:app"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-mock>=3.12",
    "pytest-asyncio>=0.23",  # Added: async tests in orchestration
]
sandbox = ["docker>=7.0"]
vectordb = [
    "chromadb>=0.4.0",
    "sentence-transformers>=2.0",
]

[tool.pytest.ini_options]
testpaths = [
    "cobuilder/engine/conditions/tests",
    "cobuilder/pipeline/tests",
    "cobuilder/orchestration/tests",
    "tests",
]
markers = [
    "functional: marks tests as functional (end-to-end) tests",
]

[tool.hatch.build.targets.wheel]
packages = ["cobuilder"]
```

---

## 10. Success Criteria

The restructure is complete when all of the following are true:

1. **No Python under `.claude/`**: `find .claude -name "*.py" | grep -v "__pycache__"` returns only hook scripts (`.claude/hooks/*.py`) — no attractor scripts.

2. **Unified CLI**: `cobuilder pipeline run data/pipelines/simple-pipeline.dot` executes successfully; `cobuilder pipeline validate` reports pass/fail against DOT schema.

3. **Package integrity**: `pip install -e .` installs cleanly with no import errors; `python -c "import cobuilder; print(cobuilder.__version__)"` succeeds.

4. **Test coverage maintained**: All tests that passed in `.claude/scripts/attractor/tests/` still pass at `cobuilder/orchestration/tests/`.

5. **Runtime state separated**: `.claude/attractor/` directory does not exist; `data/pipelines/` contains the 367 DOT files; `data/signals/` is gitignored.

6. **Reference paths updated**: `grep -r "scripts/attractor" .claude/` returns no results (except git history).

7. **Skill references updated**: `grep -r "scripts/attractor" .claude/skills/ .claude/output-styles/` returns no results.

8. **`data/` gitignore correct**: Runtime state (`signals/`, `runner-state/`, `checkpoints/`) is excluded; pipeline DOT files and examples are tracked.

---

## 11. Handoff for Implementation

### Recommended Agent Assignment

| Phase | Agent | Rationale |
|-------|-------|-----------|
| 1 (Baseline) | `backend-solutions-engineer` | Python package configuration |
| 2 (Dead code deletion) | `backend-solutions-engineer` | Safe deletions, run tests |
| 3 (Pipeline module) | `backend-solutions-engineer` | Python import rewriting |
| 4 (Orchestration module) | `backend-solutions-engineer` | Most complex Python migration |
| 5 (Runtime state) | `backend-solutions-engineer` | Git mv + gitignore |
| 6 (CLI + references) | `backend-solutions-engineer` | CLI wiring + markdown updates |
| 7 (Test relocation) | `tdd-test-engineer` | Test suite integrity |
| 8 (Final cleanup) | `backend-solutions-engineer` | Verification and cleanup |

### Key Implementation Constraints

1. **Process one phase at a time** and run tests between phases. A broken import in Phase 3 blocks Phase 4.

2. **The `_THIS_DIR` removal is the most error-prone change**. Every file that used bare imports (`from parser import`) relied on `sys.path` manipulation. Remove the manipulation, rewrite the import, verify immediately.

3. **Do not refactor logic while migrating**. The goal is structural move, not functional change. Resist the temptation to clean up code during the move — that belongs in a separate PR.

4. **`pipeline_runner.py` subprocess self-invocation**: Search for `subprocess.Popen` or `subprocess.run` calls that reference `pipeline_runner.py` by filename. Replace with `[sys.executable, "-m", "cobuilder.orchestration.pipeline_runner"]`.

5. **The attractor `cli.py` is NOT the same as cobuilder `cli.py`**: The attractor `cli.py` provides the `attractor` subcommands (status, transition, annotate, etc.). These should be merged as `cobuilder pipeline <subcommand>` entries in the unified CLI, not as a standalone script.

6. **`ANTHROPIC_API_KEY` and `ATTRACTOR_SIGNALS_DIR` env vars**: These must remain functional. `dispatch_worker.load_attractor_env()` currently walks up from `_THIS_DIR` to find `.claude/attractor/.env`. After migration, the lookup should use `ATTRACTOR_ENV_FILE` env var first, then fall back to `{project_root}/.claude/attractor/.env`.
