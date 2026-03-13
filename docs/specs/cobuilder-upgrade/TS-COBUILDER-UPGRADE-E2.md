---
ts_id: TS-COBUILDER-UPGRADE-E2
prd_ref: PRD-COBUILDER-UPGRADE-001
epic: E2
title: "E2: Rename attractor→engine + Extract .pipelines/"
status: draft
type: technical-spec
grade: authoritative
created: 2026-03-14
last_verified: 2026-03-14
---

# TS-COBUILDER-UPGRADE-E2: Rename attractor→engine + Extract `.pipelines/`

## 1. Executive Summary

Epic 2 restructures the CoBuilder Python package and its runtime state layout. The `cobuilder/attractor/` package is moved to `cobuilder/engine/` (where the dispatch layer is co-located with the existing engine primitives). All runtime state — DOT files, signal files, checkpoints — is extracted from `.claude/attractor/` to a new `.pipelines/` directory at the repo root, which is gitignored and therefore safe for public GitHub publication.

This is a **pure refactor**: no logic changes, no new features. The goal is correct naming and clean separation of version-controlled code from transient runtime state.

**Dependencies:** Executed after E0 (code merge) and E1 (LLM profiles) in the merged codebase. The rename targets the `cobuilder/engine/` package that will exist after E0 merges the abstract-workflow-system branch. No backward compatibility is maintained (per TD9 in the PRD: we are the only users).

**Logfire constraint:** ALL span names must be preserved exactly as they appear in source. Span names are external observability identifiers and must not change during the rename.

---

## 2. Scope

### In Scope

- Move all Python source files from `cobuilder/attractor/` to `cobuilder/engine/` (dispatcher layer merged into engine package)
- Update every `from cobuilder.attractor` import across the codebase
- Update `cobuilder/attractor/__init__.py` (delete — no backward-compat re-exports)
- Update `.claude/scripts/attractor/` shim files to import from new location
- Rename all `ATTRACTOR_*` environment variables to `PIPELINE_*` with transitional fallback
- Extract runtime state from `.claude/attractor/` to `.pipelines/` at repo root
- Add `.pipelines/` to `.gitignore`
- Implement auto-migration: detect `.claude/attractor/` state on first run and move to `.pipelines/`
- Update `cobuilder pipeline status`, `run`, and `transition` CLI commands to read from `.pipelines/`
- Update all documentation, markdown files, DOT examples, and agent reference docs containing `cobuilder/attractor` or `.claude/attractor` path references

### Out of Scope

- Logic changes to any handler, runner, or dispatch module
- Logfire span name changes (explicitly forbidden)
- WorktreeManager implementation (E3)
- ManagerLoopHandler upgrade (E4)
- Test coverage gate enforcement (E5)

---

## 3. Current State Inventory

### 3.1 Source Files in `cobuilder/attractor/` (38 Python files)

The complete list of files to be moved, in logical groupings:

**Core dispatch layer (primary rename targets):**
| Current Path | New Path | Notes |
|---|---|---|
| `cobuilder/attractor/__init__.py` | DELETE | No re-exports; update docstring location note |
| `cobuilder/attractor/pipeline_runner.py` | `cobuilder/engine/pipeline_runner.py` | 110 KB; 12+ Logfire spans |
| `cobuilder/attractor/cli.py` | `cobuilder/engine/cli.py` | Typer CLI subcommands |
| `cobuilder/attractor/guardian.py` | `cobuilder/engine/guardian.py` | 47 KB; 4+ Logfire spans |
| `cobuilder/attractor/session_runner.py` | `cobuilder/engine/session_runner.py` | 57 KB; 10+ Logfire spans |
| `cobuilder/attractor/dispatch_worker.py` | `cobuilder/engine/dispatch_worker.py` | load_attractor_env() → load_engine_env() |
| `cobuilder/attractor/spawn_orchestrator.py` | `cobuilder/engine/spawn_orchestrator.py` | |
| `cobuilder/attractor/run_research.py` | `cobuilder/engine/run_research.py` | |
| `cobuilder/attractor/run_refine.py` | `cobuilder/engine/run_refine.py` | |

**Pipeline graph operations:**
| Current Path | New Path |
|---|---|
| `cobuilder/attractor/parser.py` | `cobuilder/engine/parser.py` |
| `cobuilder/attractor/validator.py` | `cobuilder/engine/validator.py` |
| `cobuilder/attractor/transition.py` | `cobuilder/engine/transition.py` |
| `cobuilder/attractor/checkpoint.py` | `cobuilder/engine/checkpoint.py` |
| `cobuilder/attractor/signal_protocol.py` | `cobuilder/engine/signal_protocol.py` |
| `cobuilder/attractor/signal_guardian.py` | `cobuilder/engine/signal_guardian.py` |
| `cobuilder/attractor/read_signal.py` | `cobuilder/engine/read_signal.py` |
| `cobuilder/attractor/wait_for_signal.py` | `cobuilder/engine/wait_for_signal.py` |
| `cobuilder/attractor/status.py` | `cobuilder/engine/status.py` |
| `cobuilder/attractor/node_ops.py` | `cobuilder/engine/node_ops.py` |
| `cobuilder/attractor/edge_ops.py` | `cobuilder/engine/edge_ops.py` |
| `cobuilder/attractor/annotate.py` | `cobuilder/engine/annotate.py` |
| `cobuilder/attractor/generate.py` | `cobuilder/engine/generate.py` |
| `cobuilder/attractor/dashboard.py` | `cobuilder/engine/dashboard.py` |
| `cobuilder/attractor/init_promise.py` | `cobuilder/engine/init_promise.py` |
| `cobuilder/attractor/runner_models.py` | `cobuilder/engine/runner_models.py` |

**Runner infrastructure (hooks, anti-gaming, identity):**
| Current Path | New Path |
|---|---|
| `cobuilder/attractor/runner_hooks.py` | `cobuilder/engine/runner_hooks.py` |
| `cobuilder/attractor/runner_tools.py` | `cobuilder/engine/runner_tools.py` |
| `cobuilder/attractor/guardian_hooks.py` | `cobuilder/engine/guardian_hooks.py` |
| `cobuilder/attractor/hook_manager.py` | `cobuilder/engine/hook_manager.py` |
| `cobuilder/attractor/anti_gaming.py` | `cobuilder/engine/anti_gaming.py` |
| `cobuilder/attractor/identity_registry.py` | `cobuilder/engine/identity_registry.py` |
| `cobuilder/attractor/agents_cmd.py` | `cobuilder/engine/agents_cmd.py` |
| `cobuilder/attractor/merge_queue.py` | `cobuilder/engine/merge_queue.py` |
| `cobuilder/attractor/merge_queue_cmd.py` | `cobuilder/engine/merge_queue_cmd.py` |

**Communication adapters:**
| Current Path | New Path |
|---|---|
| `cobuilder/attractor/channel_adapter.py` | `cobuilder/engine/channel_adapter.py` |
| `cobuilder/attractor/channel_bridge.py` | `cobuilder/engine/channel_bridge.py` |
| `cobuilder/attractor/gchat_adapter.py` | `cobuilder/engine/gchat_adapter.py` |

**Data file (not Python, move with package):**
| Current Path | New Path |
|---|---|
| `cobuilder/attractor/.env` | `cobuilder/engine/.env` |

### 3.2 Shim Files in `.claude/scripts/attractor/`

These are thin re-export shims used by the `.claude/` scripts layer. They import `from cobuilder.attractor.X import *`. Update import sources only — file names and locations stay the same (`.claude/scripts/attractor/` stays intact, but imports point to `cobuilder.engine`).

| Shim File | Current Import | Updated Import |
|---|---|---|
| `.claude/scripts/attractor/pipeline_runner.py` | `from cobuilder.attractor.pipeline_runner import *` | `from cobuilder.engine.pipeline_runner import *` |
| `.claude/scripts/attractor/guardian.py` | `from cobuilder.attractor.guardian import *` | `from cobuilder.engine.guardian import *` |
| `.claude/scripts/attractor/dispatch_worker.py` | `from cobuilder.attractor.dispatch_worker import *` | `from cobuilder.engine.dispatch_worker import *` |
| `.claude/scripts/attractor/spawn_orchestrator.py` | `from cobuilder.attractor.spawn_orchestrator import *` | `from cobuilder.engine.spawn_orchestrator import *` |
| `.claude/scripts/attractor/runner.py` | `from cobuilder.attractor.session_runner import *` | `from cobuilder.engine.session_runner import *` |
| `.claude/scripts/attractor/cli.py` | `from cobuilder.attractor.cli import *` | `from cobuilder.engine.cli import *` |
| `.claude/scripts/attractor/run_research.py` | `from cobuilder.attractor.run_research import *` | `from cobuilder.engine.run_research import *` |
| `.claude/scripts/attractor/run_refine.py` | `from cobuilder.attractor.run_refine import *` | `from cobuilder.engine.run_refine import *` |

### 3.3 Test Files (import updates only — test directory name stays)

All tests live under `tests/attractor/`. The directory name stays `tests/attractor/` for this epic (renaming the test directory is deferred to avoid churn; it can be done as part of E5 repository cleanup). All `from cobuilder.attractor` imports within these files must be updated to `from cobuilder.engine`.

Affected test files (19 files, ~250 distinct import lines):
- `tests/attractor/test_spawn_orchestrator.py`
- `tests/attractor/test_signal_protocol.py`
- `tests/attractor/test_status_deps_met.py`
- `tests/attractor/test_e2e_3layer.py`
- `tests/attractor/test_runner_guardian.py`
- `tests/attractor/test_runner_state_machine.py`
- `tests/attractor/test_identity_registry.py`
- `tests/attractor/test_persistent_guidance.py`
- `tests/attractor/test_hook_manager.py`
- `tests/attractor/test_gchat_adapter.py`
- `tests/attractor/test_channel_bridge.py`
- `tests/attractor/test_launch_guardian.py`
- `tests/attractor/test_sdk_error_handling.py`
- `tests/attractor/test_e2e_resilience.py`
- `tests/attractor/test_run_research.py`
- `tests/attractor/test_dot_schema_extensions.py`
- `tests/attractor/test_runner_agent.py`
- `tests/attractor/test_merge_queue.py`
- `tests/attractor/test_runner_hooks.py`
- `tests/attractor/test_anti_gaming.py`
- `tests/attractor/test_guardian_agent.py`

Also: `tests/test_spawn_orchestrator.py` (top-level, uses `sys.path` manipulation pointing to `_ATTRACTOR_DIR`).

### 3.4 Documentation Files Referencing Old Paths

The following categories of non-Python files reference `cobuilder.attractor` or `.claude/attractor` paths and require updates:

**Markdown docs (update path references, not content restructuring):**
- `.claude/agents/validation-test-agent.md` — references `ATTRACTOR_SIGNAL_DIR` and `cobuilder.attractor` import examples
- `.claude/agents/worker-tool-reference.md` — references `$ATTRACTOR_SIGNAL_DIR` in signal file instructions
- `.claude/documentation/concern-queue-schema.md` — references `ATTRACTOR_SIGNAL_DIR` env var
- `guardian-workflow.md` — references `ATTRACTOR_SIGNAL_DIR` and `.claude/attractor/`
- `.cobuilder/examples/*.dot` — comment headers: `// Schema: .claude/attractor/schema.md`

**Stale PRDs/SDs (update code examples only, not retrospective):**
- `docs/prds/SD-COBUILDER-CONSOLIDATION-002.md` — import examples
- `docs/sds/cobuilder-web/SD-COBUILDER-WEB-001-E1-initiative-lifecycle.md` — import example
- `docs/prds/harness-upgrade/PRD-HARNESS-UPGRADE-001.md` — `ATTRACTOR_SIGNAL_DIR` references in AC tables

Note: Historical PRDs/SDs are not retroactively rewritten. Only active agent reference docs (`worker-tool-reference.md`, `validation-test-agent.md`, `concern-queue-schema.md`) that workers read at runtime are updated.

---

## 4. Environment Variable Rename

### 4.1 Complete Mapping

All `ATTRACTOR_*` environment variables found in source code are renamed with `PIPELINE_` prefix. Variables found in documentation-only files (stale SDs, PRDs) are not renamed there — only in runtime-active source files.

| Old Variable | New Variable | Source Location | Default |
|---|---|---|---|
| `ATTRACTOR_SIGNAL_DIR` | `PIPELINE_SIGNAL_DIR` | `pipeline_runner.py:1175`, `session_runner.py:428`, agent docs | — |
| `ATTRACTOR_SIGNALS_DIR` | `PIPELINE_SIGNALS_DIR` | `signal_protocol.py:91` | git-root auto-detected |
| `ATTRACTOR_SIGNAL_POLL_INTERVAL` | `PIPELINE_SIGNAL_POLL_INTERVAL` | `cobuilder/engine/handlers/codergen.py:75` | 10s |
| `ATTRACTOR_RATE_LIMIT_RETRIES` | `PIPELINE_RATE_LIMIT_RETRIES` | `pipeline_runner.py:69` | 3 |
| `ATTRACTOR_RATE_LIMIT_BACKOFF` | `PIPELINE_RATE_LIMIT_BACKOFF` | `pipeline_runner.py:74` | 65 |
| `ATTRACTOR_TOOL_TIMEOUT` | `PIPELINE_TOOL_TIMEOUT` | `cobuilder/engine/handlers/tool.py:44` | 300s |
| `ATTRACTOR_HANDLER_TIMEOUT` | `PIPELINE_HANDLER_TIMEOUT` | `cobuilder/engine/handlers/codergen.py:72` | — |
| `ATTRACTOR_HUMAN_GATE_TIMEOUT` | `PIPELINE_HUMAN_GATE_TIMEOUT` | `cobuilder/engine/handlers/wait_human.py:53` | indefinite |
| `ATTRACTOR_MAX_MANAGER_DEPTH` | `PIPELINE_MAX_MANAGER_DEPTH` | `cobuilder/engine/handlers/manager_loop.py:31` | — |
| `ATTRACTOR_GIT_COMMIT_PER_NODE` | `PIPELINE_GIT_COMMIT_PER_NODE` | `cobuilder/engine/runner.py` | 0 |
| `ATTRACTOR_RUN_DIR_ROOT` | `PIPELINE_RUN_DIR_ROOT` | `cobuilder/engine/runner.py` | `.pipelines/pipelines` |
| `ATTRACTOR_GUARDIAN_STALE_SECONDS` | `PIPELINE_GUARDIAN_STALE_SECONDS` | `guardian_hooks.py:60` | 300 |
| `ATTRACTOR_MAX_RETRIES` | `PIPELINE_MAX_RETRIES` | `runner_hooks.py:46`, `cobuilder/orchestration/runner_hooks.py:46` | 3 |
| `ATTRACTOR_SPOT_CHECK_RATE` | `PIPELINE_SPOT_CHECK_RATE` | `runner_hooks.py:120`, `cobuilder/orchestration/runner_hooks.py:120` | 0.25 |
| `ATTRACTOR_EVIDENCE_MAX_AGE` | `PIPELINE_EVIDENCE_MAX_AGE` | `runner_hooks.py:125`, `anti_gaming.py:287` | 300 |
| `ATTRACTOR_STATE_DIR` | `PIPELINE_STATE_DIR` | `hook_manager.py:91`, `identity_registry.py:76` | — |
| `ATTRACTOR_MERGE_QUEUE_DIR` | `PIPELINE_MERGE_QUEUE_DIR` | `merge_queue.py:68` | — |

### 4.2 Backward-Compat Fallback Pattern

Per the PRD (TD9: no backward compatibility), old variable names are NOT honoured. However, to prevent silent failures during developer transition, every `os.environ.get()` call on a renamed variable logs a warning at startup if the old name is set but the new name is not:

```python
def _get_env(new_name: str, old_name: str, default: str = "") -> str:
    """Read env var with deprecation warning for old ATTRACTOR_ prefix."""
    if new_name in os.environ:
        return os.environ[new_name]
    if old_name in os.environ:
        import warnings
        warnings.warn(
            f"{old_name} is deprecated; use {new_name}",
            DeprecationWarning,
            stacklevel=2,
        )
        return os.environ[old_name]
    return default
```

This helper is defined once in `cobuilder/engine/_env.py` and imported everywhere env vars are read. It is removed entirely in E5 (GitHub publication).

### 4.3 `dispatch_worker.py` Function Rename

The function `load_attractor_env()` is renamed to `load_engine_env()`. It continues to load credentials from `cobuilder/engine/.env` (the `.env` file moves with the package). All callers are updated:

| File | Old Call | New Call |
|---|---|---|
| `cobuilder/engine/guardian.py` | `load_attractor_env()` | `load_engine_env()` |
| `cobuilder/engine/session_runner.py` | `load_attractor_env()` | `load_engine_env()` |
| `cobuilder/engine/run_research.py` | `load_attractor_env()` | `load_engine_env()` |
| `cobuilder/engine/run_refine.py` | `load_attractor_env()` | `load_engine_env()` |

The internal `_ATTRACTOR_ENV_KEYS` frozenset in `dispatch_worker.py` is renamed to `_ENGINE_ENV_KEYS`.

---

## 5. Runtime State Extraction: `.claude/attractor/` → `.pipelines/`

### 5.1 New Directory Layout

`.pipelines/` is created at the repo root alongside `.cobuilder/` and `.claude/`. It is gitignored and holds all transient pipeline execution state.

```
.pipelines/                        # repo-root level, gitignored
├── pipelines/                     # Active DOT files (one per pipeline run)
│   ├── {pipeline-id}.dot          # The live DOT graph (status attributes updated in-place)
│   └── {pipeline-id}.dot.ops.jsonl  # Transition log (append-only)
├── signals/                       # Signal files written by workers
│   └── {pipeline-id}/             # Subdirectory per pipeline run
│       ├── {node_id}.json         # Worker completion signal
│       └── concerns.jsonl         # Worker concern queue
├── checkpoints/                   # Checkpoint files for resume
│   └── {pipeline-id}.json         # Runner checkpoint (current node, state)
└── state/                         # Shared runner state (identity, hooks, merge queue)
    ├── identities/                # Identity registry (PIPELINE_STATE_DIR)
    ├── hooks/                     # Hook manager state
    └── merge-queue/               # Merge queue state
```

**What stays in `.cobuilder/` (version-controlled):**
```
.cobuilder/
├── templates/                     # Jinja2 DOT templates + manifests (E7, E8)
│   └── {template-name}/
│       ├── template.dot.j2
│       └── manifest.yaml
└── examples/                      # Example DOT graphs (schema reference)
    ├── full-initiative.dot
    ├── poc-stuck.dot
    ├── poc-needs-validation.dot
    └── poc-parallel.dot
```

Template files are version-controlled because they are reusable structural patterns authored by developers. Pipeline state files are runtime artefacts that must never be committed.

### 5.2 `.gitignore` Addition

Add to the root `.gitignore`:

```gitignore
# Pipeline runtime state — never commit
.pipelines/
```

Verify that `.claude/attractor/` is already in `.gitignore` (or add it):

```gitignore
# Legacy runtime state location — gitignored during transition
.claude/attractor/pipelines/
.claude/attractor/signals/
.claude/attractor/checkpoints/
.claude/attractor/state/
```

### 5.3 Default Path Resolution in `cobuilder/engine/runner.py`

The `ATTRACTOR_RUN_DIR_ROOT` default changes from `.claude/attractor/pipelines` to `.pipelines/pipelines`. The resolution order in `runner.py`:

```python
def _resolve_run_dir_root() -> Path:
    """Resolve the pipeline run directory root.

    Resolution order:
    1. PIPELINE_RUN_DIR_ROOT env var
    2. ATTRACTOR_RUN_DIR_ROOT env var (deprecated — warns)
    3. .pipelines/pipelines/ relative to cwd
    """
    new_var = os.environ.get("PIPELINE_RUN_DIR_ROOT")
    if new_var:
        return Path(new_var)
    old_var = os.environ.get("ATTRACTOR_RUN_DIR_ROOT")
    if old_var:
        warnings.warn("ATTRACTOR_RUN_DIR_ROOT is deprecated; use PIPELINE_RUN_DIR_ROOT", DeprecationWarning)
        return Path(old_var)
    return Path.cwd() / ".pipelines" / "pipelines"
```

Signal directory resolution in `signal_protocol.py`:

```python
def _resolve_signals_dir(dot_file: Path | None = None) -> Path:
    """Resolve signal directory.

    Resolution order:
    1. PIPELINE_SIGNAL_DIR env var (set by runner per-dispatch)
    2. PIPELINE_SIGNALS_DIR env var (global override)
    3. ATTRACTOR_SIGNAL_DIR env var (deprecated)
    4. ATTRACTOR_SIGNALS_DIR env var (deprecated)
    5. .pipelines/signals/{pipeline-id}/ derived from dot_file
    6. .pipelines/signals/ fallback
    """
```

### 5.4 Auto-Migration on First Run

When `PipelineRunner` or `EngineRunner` initialises, it checks for the legacy `.claude/attractor/` state directories. If found and `.pipelines/` does not yet exist, it migrates automatically:

```python
def _migrate_legacy_state(project_root: Path) -> None:
    """One-time migration from .claude/attractor/ to .pipelines/.

    Called at runner startup. Safe to call repeatedly (idempotent).
    Only migrates if .claude/attractor/pipelines/ exists AND .pipelines/ does not.
    Does NOT remove the source — operator can delete manually after verifying.
    """
    legacy_root = project_root / ".claude" / "attractor"
    new_root = project_root / ".pipelines"

    if not legacy_root.exists() or new_root.exists():
        return  # Already migrated or nothing to migrate

    import shutil
    import logging
    log = logging.getLogger(__name__)
    log.warning(
        "Auto-migrating pipeline state from %s to %s. "
        "Delete %s manually once migration is verified.",
        legacy_root, new_root, legacy_root,
    )

    new_root.mkdir(parents=True, exist_ok=True)

    for subdir in ("pipelines", "signals", "checkpoints", "state"):
        src = legacy_root / subdir
        dst = new_root / subdir
        if src.exists() and not dst.exists():
            shutil.copytree(src, dst)
            log.info("Migrated %s → %s", src, dst)
```

The migration copies (does not move) so that in-flight pipelines using the old path continue to work. The operator deletes `.claude/attractor/` manually after verification.

---

## 6. `__init__.py` Decision

The `cobuilder/attractor/__init__.py` is **deleted** with no backward-compat re-exports. Rationale:

- TD9 (PRD): "No backward compatibility. We are the only users."
- The `__init__.py` currently only contains a module docstring (no public API surface via `__all__`). There is nothing to re-export.
- Adding `cobuilder/attractor/__init__.py` as a shim that imports from `cobuilder.engine` would require the old package to remain on disk, defeating the rename.

The `cobuilder/engine/__init__.py` (already present, 1,394 bytes as of the E0 merge target) must be updated to document the new module inventory. Replace the existing content or append to it:

```python
"""cobuilder.engine — DOT-based pipeline execution engine.

Dispatch layer (from cobuilder.attractor, renamed E2):
    pipeline_runner   : PipelineRunner top-level orchestrator (12+ Logfire spans)
    session_runner    : RunnerStateMachine / monitor loop (10+ Logfire spans)
    guardian          : Guardian agent entry-point (4+ Logfire spans)
    dispatch_worker   : Worker dispatch + load_engine_env()
    spawn_orchestrator: Orchestrator spawn/respawn helpers
    cli               : Typer-based CLI for pipeline subcommands
    run_research      : Research node handler (standalone script)
    run_refine        : Refine node handler (standalone script)

Core engine primitives (from abstract-workflow-system, merged E0):
    runner            : EngineRunner (async pipeline execution)
    graph             : Graph / Node / Edge models
    parser            : DOT file lexer/parser
    handlers/         : Handler registry (codergen, tool, wait_human, manager_loop, ...)
    middleware/       : ConstraintMiddleware, LogfireMiddleware, RetryMiddleware
    events/           : Event backend (JSONL, Logfire, signal bridge)
    state_machine     : NodeStateMachine
    edge_selector     : Edge selection logic
    conditions/       : Condition evaluators
    checkpoint        : Checkpoint read/write (atomic)
    loop_detection    : Loop detection and bounded iteration
    exceptions        : Typed exception hierarchy

Pipeline graph operations:
    signal_protocol   : Signal read/write/wait helpers
    transition        : State-transition table and apply_transition()
    validator         : DOT graph validator
    status            : Pipeline status reporting
    node_ops          : Node attribute CRUD
    edge_ops          : Edge CRUD
    annotate          : Node annotation
    generate          : Pipeline generation helpers
    dashboard         : Dashboard rendering

Runner infrastructure:
    runner_models     : Pydantic models (PipelineConfig, RunnerState, etc.)
    runner_hooks      : RunnerHooks / anti-gaming enforcement
    runner_tools      : Low-level tool dispatch helpers
    guardian_hooks    : RunnerGuardian / PipelineHealth
    hook_manager      : Hook lifecycle management
    anti_gaming       : Audit chain + evidence validation
    identity_registry : Node identity tracking
    merge_queue       : Parallel merge queue

Communication adapters:
    channel_adapter   : Abstract channel adapter interface
    channel_bridge    : Channel bridge (inbound/outbound routing)
    gchat_adapter     : Google Chat adapter
"""
```

---

## 7. CLI Command Updates

### 7.1 Current CLI Structure

The `cobuilder` CLI entry point is `cobuilder/__main__.py` → `cobuilder/cli.py`. The pipeline subcommands are handled by:
- `cobuilder.cli.pipeline_app` (Typer sub-app in `cobuilder/cli.py`)
- `cobuilder/attractor/cli.py` (Typer app with `parse`, `validate`, `status`, `transition`, `checkpoint`, `generate`, `annotate`, `init-promise`, `dashboard`, `node`, `edge`, `run`, `run-guardian`, `agents`, `merge-queue`)

After E2, `cobuilder/attractor/cli.py` becomes `cobuilder/engine/cli.py`. The import in `cobuilder/cli.py` that routes to the engine CLI must be updated.

### 7.2 Updated Import in `cobuilder/cli.py`

Locate the routing import for the attractor/engine CLI. Currently the `cobuilder pipeline` command routes through `cobuilder/cli.py`'s `pipeline_app`. Update any import of `cobuilder.attractor.cli`:

```python
# Before:
from cobuilder.attractor.cli import app as attractor_cli_app

# After:
from cobuilder.engine.cli import app as engine_cli_app
```

### 7.3 `cobuilder pipeline status` Path Change

The `status` subcommand reads DOT files from the signal/pipeline directories. After E2 it must default to `.pipelines/pipelines/` instead of `.claude/attractor/pipelines/`. This is controlled by `PIPELINE_RUN_DIR_ROOT` (section 5.3 above).

No change to the command signature is required — the path resolution is internal.

### 7.4 `cobuilder pipeline run` Path Change

The `run` subcommand launches `PipelineRunner` against a DOT file. After E2, when no explicit `--dot-file` path is given, the default search path is `.pipelines/pipelines/*.dot`.

### 7.5 `cobuilder pipeline transition` Path Change

The `transition` subcommand reads and writes DOT files. After E2, default file paths resolve from `.pipelines/pipelines/` via `PIPELINE_RUN_DIR_ROOT`.

---

## 8. Logfire Observability — Span Preservation

This section is a hard constraint. All Logfire spans must be verified to be present and structurally identical after the rename.

### 8.1 Spans in `pipeline_runner.py` (preserved as-is)

| Span Name | Type | Context |
|---|---|---|
| `pipeline {pipeline_id}` | `logfire.span()` context manager | Top-level pipeline execution span |
| `tool {node_id}` | `logfire.span()` context manager | Tool handler execution |
| `wait_human {node_id}` | `logfire.span()` context manager | Wait-human gate |
| `wait_cobuilder {node_id}` | `logfire.span()` context manager | Wait-cobuilder gate |
| `dispatch_worker {node_id}` | `logfire.info()` event | Worker dispatch start |
| `worker_first_message {node_id}` | `logfire.info()` event | First SDK message from worker |
| `worker_tool {node_id} {tool}` | `logfire.info()` event | Worker tool call |
| `worker_text {node_id}` | `logfire.info()` event | Worker text output |
| `worker_dispatch_start {node_id}` | `logfire.info()` event | AgentSDK dispatch start |
| `worker_complete {node_id} {status} in {elapsed_s}s` | `logfire.info()` event | Worker completion |
| `tool PASS` / `tool FAIL exit={rc}` | `logfire.info()` events | Tool outcome |

### 8.2 Spans in `guardian.py` (preserved as-is)

| Span Name | Type |
|---|---|
| `guardian.build_system_prompt` | `logfire.span()` |
| `guardian.build_initial_prompt` | `logfire.span()` |
| `guardian.build_options` | `logfire.span()` |
| `guardian.run_agent` | `logfire.span()` |
| Guardian info events (on text/tool/result) | `logfire.info()` |

### 8.3 Spans in `session_runner.py` (preserved as-is)

| Span Name | Type |
|---|---|
| `runner.build_system_prompt` | `logfire.span()` |
| `runner.build_initial_prompt` | `logfire.span()` |
| `runner.build_options` | `logfire.span()` |
| `runner.build_worker_system_prompt` | `logfire.span()` |
| `runner.build_worker_initial_prompt` | `logfire.span()` |
| `runner.build_worker_options` | `logfire.span()` |
| `runner.build_monitor_prompt` | `logfire.span()` |
| `runner.run_agent` | `logfire.span()` |
| `runner.main` | `logfire.span()` |
| Runner info events (on text/tool/result) | `logfire.info()` |

### 8.4 Verification Approach

After completing the rename, run the existing Logfire span assertions (added in E0.2) to confirm no spans were lost:

```bash
pytest tests/ -k "logfire or span or CaptureLogfire" -v
```

No spans are to be renamed even when the function they trace is renamed (e.g., `load_attractor_env` → `load_engine_env` does not affect span names since that function has no associated span).

---

## 9. Execution Order — Step-by-Step Procedure

Execute steps in this exact order. Do not skip steps or reorder.

### Step 1: Prepare the target directory

```bash
# Verify cobuilder/engine/ exists from E0 merge
ls /Users/theb/Documents/Windsurf/claude-harness-setup/cobuilder/engine/

# Create __init__.py placeholder if not present (will be overwritten in Step 5)
touch cobuilder/engine/__init__.py
```

### Step 2: Move Python source files using `git mv`

Execute these `git mv` commands in order. The `git mv` preserves git history.

```bash
cd /Users/theb/Documents/Windsurf/claude-harness-setup

# Core dispatch layer
git mv cobuilder/attractor/pipeline_runner.py cobuilder/engine/pipeline_runner.py
git mv cobuilder/attractor/cli.py cobuilder/engine/cli.py
git mv cobuilder/attractor/guardian.py cobuilder/engine/guardian.py
git mv cobuilder/attractor/session_runner.py cobuilder/engine/session_runner.py
git mv cobuilder/attractor/dispatch_worker.py cobuilder/engine/dispatch_worker.py
git mv cobuilder/attractor/spawn_orchestrator.py cobuilder/engine/spawn_orchestrator.py
git mv cobuilder/attractor/run_research.py cobuilder/engine/run_research.py
git mv cobuilder/attractor/run_refine.py cobuilder/engine/run_refine.py

# Pipeline graph operations
git mv cobuilder/attractor/parser.py cobuilder/engine/parser.py
git mv cobuilder/attractor/validator.py cobuilder/engine/validator.py
git mv cobuilder/attractor/transition.py cobuilder/engine/transition.py
git mv cobuilder/attractor/checkpoint.py cobuilder/engine/checkpoint.py
git mv cobuilder/attractor/signal_protocol.py cobuilder/engine/signal_protocol.py
git mv cobuilder/attractor/signal_guardian.py cobuilder/engine/signal_guardian.py
git mv cobuilder/attractor/read_signal.py cobuilder/engine/read_signal.py
git mv cobuilder/attractor/wait_for_signal.py cobuilder/engine/wait_for_signal.py
git mv cobuilder/attractor/status.py cobuilder/engine/status.py
git mv cobuilder/attractor/node_ops.py cobuilder/engine/node_ops.py
git mv cobuilder/attractor/edge_ops.py cobuilder/engine/edge_ops.py
git mv cobuilder/attractor/annotate.py cobuilder/engine/annotate.py
git mv cobuilder/attractor/generate.py cobuilder/engine/generate.py
git mv cobuilder/attractor/dashboard.py cobuilder/engine/dashboard.py
git mv cobuilder/attractor/init_promise.py cobuilder/engine/init_promise.py
git mv cobuilder/attractor/runner_models.py cobuilder/engine/runner_models.py

# Runner infrastructure
git mv cobuilder/attractor/runner_hooks.py cobuilder/engine/runner_hooks.py
git mv cobuilder/attractor/runner_tools.py cobuilder/engine/runner_tools.py
git mv cobuilder/attractor/guardian_hooks.py cobuilder/engine/guardian_hooks.py
git mv cobuilder/attractor/hook_manager.py cobuilder/engine/hook_manager.py
git mv cobuilder/attractor/anti_gaming.py cobuilder/engine/anti_gaming.py
git mv cobuilder/attractor/identity_registry.py cobuilder/engine/identity_registry.py
git mv cobuilder/attractor/agents_cmd.py cobuilder/engine/agents_cmd.py
git mv cobuilder/attractor/merge_queue.py cobuilder/engine/merge_queue.py
git mv cobuilder/attractor/merge_queue_cmd.py cobuilder/engine/merge_queue_cmd.py

# Communication adapters
git mv cobuilder/attractor/channel_adapter.py cobuilder/engine/channel_adapter.py
git mv cobuilder/attractor/channel_bridge.py cobuilder/engine/channel_bridge.py
git mv cobuilder/attractor/gchat_adapter.py cobuilder/engine/gchat_adapter.py

# Data file
git mv cobuilder/attractor/.env cobuilder/engine/.env

# Delete old __init__.py (no re-exports)
git rm cobuilder/attractor/__init__.py
```

At this point `cobuilder/attractor/` should contain only `__pycache__/`. Verify:

```bash
ls cobuilder/attractor/
# Expected: __pycache__/  (only)
```

Remove the `__pycache__` and any remaining directory:

```bash
rm -rf cobuilder/attractor/__pycache__
rmdir cobuilder/attractor  # Fails if not empty — investigate if so
```

### Step 3: Automated import find-replace

Run this automated replacement across all Python files. The replacement must be exact-string, not regex-based, to avoid false positives:

```bash
cd /Users/theb/Documents/Windsurf/claude-harness-setup

# Python source files: replace import paths
find . -name "*.py" \
  ! -path "./.git/*" \
  ! -path "./__pycache__/*" \
  -exec sed -i '' \
    's/from cobuilder\.attractor\b/from cobuilder.engine/g;
     s/import cobuilder\.attractor\b/import cobuilder.engine/g;
     s/cobuilder\.attractor\./cobuilder.engine./g' {} +
```

Verify with a grep that no `cobuilder.attractor` references remain in Python files:

```bash
grep -r "cobuilder\.attractor" . --include="*.py" ! -path "./.git/*"
# Expected: zero matches
```

If any remain (e.g., in docstrings or string literals within source files), update them manually.

### Step 4: Create `cobuilder/engine/_env.py`

Create the deprecation-aware env helper module:

```python
# cobuilder/engine/_env.py
"""Environment variable resolution with deprecation warnings for renamed ATTRACTOR_ vars."""
from __future__ import annotations
import os
import warnings


def get_env(new_name: str, old_name: str, default: str = "") -> str:
    """Read env var, warning if the deprecated ATTRACTOR_ name is set instead."""
    val = os.environ.get(new_name)
    if val is not None:
        return val
    old_val = os.environ.get(old_name)
    if old_val is not None:
        warnings.warn(
            f"{old_name!r} is deprecated; use {new_name!r} instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        return old_val
    return default
```

### Step 5: Update `cobuilder/engine/__init__.py`

Replace the existing content of `cobuilder/engine/__init__.py` with the full docstring from Section 6.

### Step 6: Update ATTRACTOR_ → PIPELINE_ env vars in moved source files

Apply find-replace for env var names within all moved engine source files. Use the mapping in Section 4.1. Also rename `load_attractor_env` → `load_engine_env` and `_ATTRACTOR_ENV_KEYS` → `_ENGINE_ENV_KEYS`:

```bash
# Env var prefix rename
find cobuilder/engine/ tests/ -name "*.py" -exec sed -i '' \
  's/ATTRACTOR_SIGNAL_DIR/PIPELINE_SIGNAL_DIR/g;
   s/ATTRACTOR_SIGNALS_DIR/PIPELINE_SIGNALS_DIR/g;
   s/ATTRACTOR_SIGNAL_POLL_INTERVAL/PIPELINE_SIGNAL_POLL_INTERVAL/g;
   s/ATTRACTOR_RATE_LIMIT_RETRIES/PIPELINE_RATE_LIMIT_RETRIES/g;
   s/ATTRACTOR_RATE_LIMIT_BACKOFF/PIPELINE_RATE_LIMIT_BACKOFF/g;
   s/ATTRACTOR_TOOL_TIMEOUT/PIPELINE_TOOL_TIMEOUT/g;
   s/ATTRACTOR_HANDLER_TIMEOUT/PIPELINE_HANDLER_TIMEOUT/g;
   s/ATTRACTOR_HUMAN_GATE_TIMEOUT/PIPELINE_HUMAN_GATE_TIMEOUT/g;
   s/ATTRACTOR_MAX_MANAGER_DEPTH/PIPELINE_MAX_MANAGER_DEPTH/g;
   s/ATTRACTOR_GIT_COMMIT_PER_NODE/PIPELINE_GIT_COMMIT_PER_NODE/g;
   s/ATTRACTOR_RUN_DIR_ROOT/PIPELINE_RUN_DIR_ROOT/g;
   s/ATTRACTOR_GUARDIAN_STALE_SECONDS/PIPELINE_GUARDIAN_STALE_SECONDS/g;
   s/ATTRACTOR_MAX_RETRIES/PIPELINE_MAX_RETRIES/g;
   s/ATTRACTOR_SPOT_CHECK_RATE/PIPELINE_SPOT_CHECK_RATE/g;
   s/ATTRACTOR_EVIDENCE_MAX_AGE/PIPELINE_EVIDENCE_MAX_AGE/g;
   s/ATTRACTOR_STATE_DIR/PIPELINE_STATE_DIR/g;
   s/ATTRACTOR_MERGE_QUEUE_DIR/PIPELINE_MERGE_QUEUE_DIR/g' {} +

# Function and constant renames (isolated to dispatch_worker.py)
sed -i '' \
  's/load_attractor_env/load_engine_env/g;
   s/_ATTRACTOR_ENV_KEYS/_ENGINE_ENV_KEYS/g' \
  cobuilder/engine/dispatch_worker.py

# Update callers of load_attractor_env
sed -i '' 's/load_attractor_env/load_engine_env/g' \
  cobuilder/engine/guardian.py \
  cobuilder/engine/session_runner.py \
  cobuilder/engine/run_research.py \
  cobuilder/engine/run_refine.py
```

Also update `cobuilder/orchestration/runner_hooks.py` (this file was NOT moved but uses `ATTRACTOR_*` vars):

```bash
sed -i '' \
  's/ATTRACTOR_MAX_RETRIES/PIPELINE_MAX_RETRIES/g;
   s/ATTRACTOR_SPOT_CHECK_RATE/PIPELINE_SPOT_CHECK_RATE/g;
   s/ATTRACTOR_EVIDENCE_MAX_AGE/PIPELINE_EVIDENCE_MAX_AGE/g' \
  cobuilder/orchestration/runner_hooks.py \
  cobuilder/orchestration/identity_registry.py
```

### Step 7: Update `.claude/scripts/attractor/` shim files

Update only the `import *` source in each shim:

```bash
sed -i '' 's/from cobuilder\.attractor\./from cobuilder.engine./g' \
  .claude/scripts/attractor/pipeline_runner.py \
  .claude/scripts/attractor/guardian.py \
  .claude/scripts/attractor/dispatch_worker.py \
  .claude/scripts/attractor/spawn_orchestrator.py \
  .claude/scripts/attractor/runner.py \
  .claude/scripts/attractor/cli.py \
  .claude/scripts/attractor/run_research.py \
  .claude/scripts/attractor/run_refine.py
```

### Step 8: Update `.pipelines/` path and `.gitignore`

```bash
# Create .pipelines/ structure
mkdir -p .pipelines/pipelines
mkdir -p .pipelines/signals
mkdir -p .pipelines/checkpoints
mkdir -p .pipelines/state/identities
mkdir -p .pipelines/state/hooks
mkdir -p .pipelines/state/merge-queue

# Add to .gitignore
echo "" >> .gitignore
echo "# Pipeline runtime state — never commit" >> .gitignore
echo ".pipelines/" >> .gitignore
```

### Step 9: Implement auto-migration in `pipeline_runner.py`

Add the `_migrate_legacy_state()` function from Section 5.4 to `cobuilder/engine/pipeline_runner.py`. Call it at the top of `PipelineRunner.__init__()`:

```python
def __init__(self, ...):
    _migrate_legacy_state(Path.cwd())  # one-time migration
    ...
```

### Step 10: Update `_resolve_run_dir_root()` in `cobuilder/engine/runner.py`

Replace the existing default path logic (`.claude/attractor/pipelines`) with the new resolution logic from Section 5.3.

### Step 11: Update signal_protocol.py resolution

Update `_resolve_signals_dir()` in `cobuilder/engine/signal_protocol.py` to use `PIPELINE_SIGNALS_DIR` as primary and the new `.pipelines/signals/` default.

### Step 12: Update active agent reference docs

Update these runtime-active documentation files (workers read them at dispatch time):

```bash
# worker-tool-reference.md: update ATTRACTOR_SIGNAL_DIR → PIPELINE_SIGNAL_DIR
sed -i '' \
  's/ATTRACTOR_SIGNAL_DIR/PIPELINE_SIGNAL_DIR/g' \
  .claude/agents/worker-tool-reference.md \
  .claude/agents/validation-test-agent.md \
  .claude/documentation/concern-queue-schema.md

# guardian-workflow.md: update env var and path references
sed -i '' \
  's/ATTRACTOR_SIGNAL_DIR/PIPELINE_SIGNAL_DIR/g;
   s|\.claude/attractor/|.pipelines/|g' \
  guardian-workflow.md

# .cobuilder/examples/*.dot: update schema comment
sed -i '' \
  's|// Schema: .claude/attractor/schema.md|// Schema: .cobuilder/schema.md|g' \
  .cobuilder/examples/full-initiative.dot \
  .cobuilder/examples/poc-stuck.dot \
  .cobuilder/examples/poc-needs-validation.dot \
  .cobuilder/examples/poc-parallel.dot
```

### Step 13: Run full test suite

```bash
cd /Users/theb/Documents/Windsurf/claude-harness-setup

# First: verify no import errors
python3 -c "from cobuilder.engine.pipeline_runner import PipelineRunner; print('Import OK')"
python3 -c "from cobuilder.engine.guardian import main; print('Guardian OK')"
python3 -c "from cobuilder.engine.session_runner import RunnerStateMachine; print('SessionRunner OK')"

# Run full test suite
pytest tests/ -v 2>&1 | tee /tmp/e2-test-results.txt

# Check for any remaining attractor imports
grep -r "cobuilder\.attractor" . --include="*.py" ! -path "./.git/*"
# Expected: zero matches
```

### Step 14: Verify zero `cobuilder.attractor` references remain in Python

```bash
# This should return empty
grep -rn "cobuilder\.attractor" . \
  --include="*.py" \
  --exclude-dir=".git" \
  --exclude-dir="__pycache__"
```

If any matches remain: fix them manually. Do not proceed to commit until this grep returns zero results.

---

## 10. Testing Strategy

### 10.1 Import Migration Verification

```python
# tests/engine/test_e2_import_migration.py
"""Verify E2 import migration: no cobuilder.attractor imports remain."""
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_no_attractor_imports_in_python_files():
    """grep for cobuilder.attractor in all .py files — must return zero matches."""
    result = subprocess.run(
        ["grep", "-r", "cobuilder.attractor", str(PROJECT_ROOT),
         "--include=*.py", "--exclude-dir=.git", "--exclude-dir=__pycache__",
         "-l"],  # -l: print only filenames
        capture_output=True, text=True
    )
    matching_files = result.stdout.strip()
    assert matching_files == "", (
        f"Files still importing from cobuilder.attractor:\n{matching_files}"
    )


def test_engine_package_importable():
    """All key engine modules must be importable."""
    modules = [
        "cobuilder.engine.pipeline_runner",
        "cobuilder.engine.guardian",
        "cobuilder.engine.session_runner",
        "cobuilder.engine.dispatch_worker",
        "cobuilder.engine.signal_protocol",
        "cobuilder.engine.parser",
        "cobuilder.engine.validator",
        "cobuilder.engine.transition",
        "cobuilder.engine.checkpoint",
        "cobuilder.engine.runner_models",
        "cobuilder.engine.runner_hooks",
        "cobuilder.engine.guardian_hooks",
        "cobuilder.engine.anti_gaming",
        "cobuilder.engine.identity_registry",
        "cobuilder.engine.hook_manager",
        "cobuilder.engine.merge_queue",
        "cobuilder.engine.channel_adapter",
        "cobuilder.engine.channel_bridge",
        "cobuilder.engine.gchat_adapter",
        "cobuilder.engine.cli",
    ]
    for module in modules:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}; print('OK')"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Failed to import {module}:\n{result.stderr}"
        )


def test_attractor_package_gone():
    """cobuilder.attractor must not be importable."""
    result = subprocess.run(
        [sys.executable, "-c", "import cobuilder.attractor"],
        capture_output=True, text=True
    )
    assert result.returncode != 0, (
        "cobuilder.attractor should not be importable after E2 rename"
    )
```

### 10.2 Auto-Migration Test

```python
# tests/engine/test_e2_auto_migration.py
"""Test .claude/attractor/ → .pipelines/ auto-migration."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from cobuilder.engine.pipeline_runner import _migrate_legacy_state


def test_migration_copies_state(tmp_path):
    """_migrate_legacy_state copies files from legacy to new location."""
    # Set up legacy state
    legacy = tmp_path / ".claude" / "attractor"
    for subdir in ("pipelines", "signals", "checkpoints", "state"):
        (legacy / subdir).mkdir(parents=True)

    # Add a sample DOT file
    (legacy / "pipelines" / "test.dot").write_text("digraph test {}")
    # Add a signal file
    (legacy / "signals" / "test-pipeline").mkdir()
    (legacy / "signals" / "test-pipeline" / "node1.json").write_text(
        json.dumps({"node": "node1", "status": "accepted"})
    )

    # Run migration
    _migrate_legacy_state(tmp_path)

    # Verify new location
    new_root = tmp_path / ".pipelines"
    assert new_root.exists()
    assert (new_root / "pipelines" / "test.dot").exists()
    assert (new_root / "signals" / "test-pipeline" / "node1.json").exists()

    # Verify legacy NOT removed (operator deletes manually)
    assert legacy.exists()


def test_migration_idempotent(tmp_path):
    """_migrate_legacy_state is safe to call repeatedly."""
    legacy = tmp_path / ".claude" / "attractor"
    (legacy / "pipelines").mkdir(parents=True)
    (legacy / "pipelines" / "a.dot").write_text("digraph a {}")

    # First call migrates
    _migrate_legacy_state(tmp_path)
    assert (tmp_path / ".pipelines" / "pipelines" / "a.dot").exists()

    # Second call: no error, no duplicate
    _migrate_legacy_state(tmp_path)
    assert (tmp_path / ".pipelines" / "pipelines" / "a.dot").exists()


def test_migration_skipped_if_pipelines_exists(tmp_path):
    """Migration does not run if .pipelines/ already exists."""
    legacy = tmp_path / ".claude" / "attractor" / "pipelines"
    legacy.mkdir(parents=True)
    (legacy / "old.dot").write_text("digraph old {}")

    # Pre-create .pipelines/ (simulates already-migrated state)
    new_pipelines = tmp_path / ".pipelines"
    new_pipelines.mkdir(parents=True)

    _migrate_legacy_state(tmp_path)

    # old.dot should NOT appear in .pipelines/ (no migration ran)
    assert not (new_pipelines / "pipelines" / "old.dot").exists()


def test_migration_skipped_if_no_legacy(tmp_path):
    """Migration does nothing if .claude/attractor/ does not exist."""
    _migrate_legacy_state(tmp_path)  # Should not raise
    assert not (tmp_path / ".pipelines").exists()
```

### 10.3 Env Var Deprecation Warning Test

```python
# tests/engine/test_e2_env_deprecation.py
"""Test ATTRACTOR_ → PIPELINE_ deprecation warnings."""
import warnings
import pytest
from cobuilder.engine._env import get_env


def test_new_name_returns_value(monkeypatch):
    monkeypatch.setenv("PIPELINE_SIGNAL_DIR", "/new/path")
    result = get_env("PIPELINE_SIGNAL_DIR", "ATTRACTOR_SIGNAL_DIR", "")
    assert result == "/new/path"


def test_old_name_warns_and_returns_value(monkeypatch):
    monkeypatch.delenv("PIPELINE_SIGNAL_DIR", raising=False)
    monkeypatch.setenv("ATTRACTOR_SIGNAL_DIR", "/old/path")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = get_env("PIPELINE_SIGNAL_DIR", "ATTRACTOR_SIGNAL_DIR", "")

    assert result == "/old/path"
    assert len(caught) == 1
    assert issubclass(caught[0].category, DeprecationWarning)
    assert "ATTRACTOR_SIGNAL_DIR" in str(caught[0].message)


def test_default_returned_when_neither_set(monkeypatch):
    monkeypatch.delenv("PIPELINE_SIGNAL_DIR", raising=False)
    monkeypatch.delenv("ATTRACTOR_SIGNAL_DIR", raising=False)
    result = get_env("PIPELINE_SIGNAL_DIR", "ATTRACTOR_SIGNAL_DIR", "default-val")
    assert result == "default-val"
```

### 10.4 Full Regression Suite

```bash
# All existing tests must pass unchanged
pytest tests/ -v --tb=short 2>&1 | tail -20
# Expect: N passed, 0 failed

# Logfire span assertions specifically
pytest tests/ -k "logfire or CaptureLogfire or span" -v

# New E2 tests
pytest tests/engine/test_e2_import_migration.py \
       tests/engine/test_e2_auto_migration.py \
       tests/engine/test_e2_env_deprecation.py \
       -v
```

---

## 11. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `parser.py` collision: `cobuilder/engine/parser.py` already exists from E0 merge | Medium | High | Check before Step 2. If collision: the attractor `parser.py` (DOT lexer) differs from the engine `parser.py` (abstract graph parser). Rename attractor's to `dot_parser.py` and update all callers. |
| `checkpoint.py` collision: both attractor and engine have a `checkpoint.py` | Medium | High | Same resolution pattern as parser.py — inspect both files; if functionally overlapping, merge; if distinct, rename one. |
| `cli.py` collision: `cobuilder/engine/cli.py` target may already exist | Low | Medium | Check first. If exists, review content — engine's CLI may already subsume attractor's CLI. |
| sed false positives on `cobuilder.attractor` in string literals | Medium | Low | After automated replace, manually inspect docstrings and help text in moved files to ensure no accidental breakage. |
| ATTRACTOR_ env var rename breaks CI test fixtures that set old names | Medium | Medium | Search test fixtures and conftest.py for ATTRACTOR_ env var sets; update them in Step 6. |
| `.env` file move breaks `load_engine_env()` path resolution | Low | High | `dispatch_worker.py` resolves `.env` relative to `__file__`. After move, `_this_dir` points to `cobuilder/engine/` which is correct. Verify with a quick import test. |
| `.claude/attractor/` path in agent prompts (e.g., validation-test-agent.md) | High | Medium | Covered in Step 12. Search thoroughly before declaring done. |

---

## 12. Acceptance Criteria Checklist

Map to PRD-COBUILDER-UPGRADE-001 Epic 2 acceptance criteria:

- [ ] `cobuilder/attractor/` directory no longer exists on disk
- [ ] `cobuilder/engine/pipeline_runner.py` is the pipeline runner entry point
- [ ] `cobuilder/engine/guardian.py` is the guardian agent entry point
- [ ] `cobuilder/engine/session_runner.py` is the runner state machine
- [ ] `grep -r "cobuilder\.attractor" . --include="*.py"` returns zero matches
- [ ] `.pipelines/` directory exists at repo root with `pipelines/`, `signals/`, `checkpoints/`, `state/` subdirs
- [ ] `.pipelines/` is listed in `.gitignore`
- [ ] `cobuilder pipeline status` reads from `.pipelines/pipelines/` by default
- [ ] `cobuilder pipeline run` resolves DOT files from `.pipelines/pipelines/` by default
- [ ] Template files remain in `.cobuilder/templates/` (version-controlled, unchanged)
- [ ] All `ATTRACTOR_*` env vars renamed to `PIPELINE_*` in engine source files
- [ ] `load_engine_env()` replaces `load_attractor_env()` in `dispatch_worker.py`
- [ ] `_migrate_legacy_state()` present and triggered at `PipelineRunner.__init__()` startup
- [ ] Auto-migration test passes: mock `.claude/attractor/` state moves to `.pipelines/`
- [ ] All existing tests pass: `pytest tests/ -v` returns zero failures
- [ ] New E2 tests added: `test_e2_import_migration.py`, `test_e2_auto_migration.py`, `test_e2_env_deprecation.py`
- [ ] All Logfire span names from Section 8 verified present (E0.2 `CaptureLogfire` assertions pass)
- [ ] Active agent docs updated: `worker-tool-reference.md`, `validation-test-agent.md`, `concern-queue-schema.md`

---

## 13. Files Changed — Complete Reference

| File | Change Type | Description |
|---|---|---|
| `cobuilder/attractor/__init__.py` | DELETE | Package removed |
| `cobuilder/attractor/*.py` (36 files) | MOVE → `cobuilder/engine/` | All Python source files |
| `cobuilder/attractor/.env` | MOVE → `cobuilder/engine/.env` | Credentials file |
| `cobuilder/engine/__init__.py` | EDIT | Full docstring rewrite with new inventory |
| `cobuilder/engine/_env.py` | CREATE | Deprecation-aware env helper |
| `cobuilder/engine/pipeline_runner.py` | EDIT | ATTRACTOR_ → PIPELINE_, add _migrate_legacy_state call |
| `cobuilder/engine/dispatch_worker.py` | EDIT | load_attractor_env → load_engine_env, _ATTRACTOR_ → _ENGINE_ |
| `cobuilder/engine/signal_protocol.py` | EDIT | PIPELINE_SIGNALS_DIR primary, new default path |
| `cobuilder/engine/runner.py` | EDIT | _resolve_run_dir_root() default → .pipelines/ |
| `cobuilder/orchestration/runner_hooks.py` | EDIT | ATTRACTOR_MAX_RETRIES → PIPELINE_MAX_RETRIES |
| `cobuilder/orchestration/identity_registry.py` | EDIT | ATTRACTOR_STATE_DIR → PIPELINE_STATE_DIR |
| `cobuilder/cli.py` | EDIT | Import from cobuilder.engine.cli |
| `.claude/scripts/attractor/*.py` (8 files) | EDIT | Update import * sources |
| `tests/attractor/*.py` (21 files) | EDIT | All from cobuilder.attractor → from cobuilder.engine |
| `tests/test_spawn_orchestrator.py` | EDIT | sys.path manipulation updated |
| `tests/engine/test_e2_import_migration.py` | CREATE | New E2 test |
| `tests/engine/test_e2_auto_migration.py` | CREATE | New E2 test |
| `tests/engine/test_e2_env_deprecation.py` | CREATE | New E2 test |
| `.pipelines/` | CREATE | New runtime state directory |
| `.gitignore` | EDIT | Add .pipelines/ |
| `.claude/agents/worker-tool-reference.md` | EDIT | PIPELINE_SIGNAL_DIR, .pipelines/ paths |
| `.claude/agents/validation-test-agent.md` | EDIT | PIPELINE_SIGNAL_DIR |
| `.claude/documentation/concern-queue-schema.md` | EDIT | PIPELINE_SIGNAL_DIR, .pipelines/ paths |
| `guardian-workflow.md` | EDIT | PIPELINE_SIGNAL_DIR, .pipelines/ paths |
| `.cobuilder/examples/*.dot` (4 files) | EDIT | Schema comment path |
