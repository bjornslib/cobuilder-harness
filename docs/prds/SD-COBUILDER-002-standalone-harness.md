---
title: "SD-COBUILDER-002: CoBuilder Standalone Harness Restructure"
status: active
type: architecture
last_verified: 2026-03-09
grade: authoritative
---

# SD-COBUILDER-002: CoBuilder Standalone Harness Restructure

## Executive Summary

CoBuilder has outgrown its incubation space inside `.claude/scripts/attractor/`. It is now a substantial Python package (`cobuilder/`) with a proper `pyproject.toml`, entry points, a rich engine (`cobuilder/engine/`), and pipeline orchestration layer (`cobuilder/orchestration/`). The problem is that `.claude/` was never meant to be a 77 MB application directory — it is Claude Code's native config space.

This SD proposes restructuring CoBuilder using the **Shim + Env-Resolved State** pattern: a thin shim layer keeps `.claude/scripts/attractor/` as auto-generated import facades, while all real code and runtime state moves to `cobuilder/` and a project-local `.cobuilder/` run directory. The result is a clean, installable package that `.claude/` simply delegates to.

**Hindsight findings**: Prior sessions strongly favour XDG-style environment-controlled paths for state separation. The user has a documented preference for immutable config vs. explicit runtime factories — this design honours that preference precisely. The `ATTRACTOR_SIGNALS_DIR` env var already exists and is used by all tests, making env-controlled state paths zero-risk.

---

## Core Analogy: The Ghost Directory

The creative framing that best fits this situation is **The Ghost Directory**. Django's `manage.py` is generated — not maintained. Webpack's `node_modules/.cache` appears automatically — not committed. We apply the same principle:

`.claude/scripts/attractor/` becomes **auto-generated**. A single `cobuilder setup-harness` command writes thin shim files into it. Every real byte of logic lives in `cobuilder/`. The ghost files exist only to maintain backward compatibility with any Claude Code hooks or scripts that reference them by path. When those hooks are updated, the ghosts can be deleted entirely.

---

## Current State Analysis

### Directory Topology

```
.claude/scripts/attractor/     48 Python files (~32K lines) — DUPLICATED / ORIGINAL CODE
cobuilder/                     Python package (~70K lines) — AUTHORITATIVE CODE
  engine/                      Core execution engine (graph, runner, checkpoint, events)
  pipeline/                    Pipeline layer (parser, signal_protocol, generate, status)
  orchestration/               Orchestrator management (pipeline_runner, runner_tools)
  repomap/                     Repository mapping tools
```

### The One Real Cross-Import

```python
# .claude/scripts/attractor/spawn_orchestrator.py, line 245
from cobuilder.bridge import scoped_refresh
```

This is the only place the old attractor code calls into `cobuilder/`. Every other file in `.claude/scripts/attractor/` is either a standalone script or a duplicate of something in `cobuilder/`.

### State Path Inventory

| Path Pattern | Location | Env Override |
|---|---|---|
| `.claude/attractor/pipelines/` | DOT files, run directories | `_DEFAULT_PIPELINES_DIR` in `cobuilder/engine/runner.py` |
| `.claude/attractor/signals/` | Signal JSON files | `ATTRACTOR_SIGNALS_DIR` |
| `.claude/attractor/state/` | RunnerState JSON, audit JSONL | hardcoded in `runner_tools.py` |
| `.claude/attractor/examples/` | Example DOT files | n/a (user-managed) |
| `~/.claude/attractor/state/` | Fallback state dir | `runner_tools.py` fallback |

The critical observation: **`ATTRACTOR_SIGNALS_DIR` already exists as an env override** and is used in every test file. This means the signal path is already decoupled from the filesystem layout — we only need to set the env var in the right place.

---

## Proposed Architecture

### The Three-Layer Model

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: Claude Code Config (.claude/)                         │
│  What lives here: hooks, settings, skills, output-styles        │
│  What DOES NOT live here: Python application code               │
│  Changes needed: replace attractor/ with shim-only facade       │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2: CoBuilder Package (cobuilder/)                        │
│  What lives here: all engine, pipeline, orchestration code      │
│  Entry point: `cobuilder` CLI via pyproject.toml scripts        │
│  New addition: cobuilder/harness/ (harness integration module)  │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 3: Runtime State (.cobuilder/ project-local)             │
│  What lives here: pipelines/, signals/, state/, checkpoints/   │
│  Controlled by: COBUILDER_WORK_DIR env var                      │
│  Default: <git-root>/.cobuilder/                                │
└─────────────────────────────────────────────────────────────────┘
```

### State Directory Resolution (The .git Analogy)

CoBuilder resolves its work directory using the same walk-up algorithm that `git` uses to find `.git/`:

```python
# cobuilder/dirs.py  (new module, ~40 lines)

import os
from pathlib import Path

def cobuilder_work_dir(start: Path | None = None) -> Path:
    """
    Resolve CoBuilder's runtime work directory.

    Resolution order:
      1. COBUILDER_WORK_DIR env var (explicit override)
      2. Walk up from `start` (default: cwd) to find .cobuilder/ marker
      3. Walk up to find .git/ root, create .cobuilder/ there
      4. ~/.local/share/cobuilder/ (XDG fallback for global installs)
    """
    if env := os.environ.get("COBUILDER_WORK_DIR"):
        return Path(env)

    root = start or Path.cwd()
    for parent in [root, *root.parents]:
        if (parent / ".cobuilder").is_dir():
            return parent / ".cobuilder"
        if (parent / ".git").is_dir():
            d = parent / ".cobuilder"
            d.mkdir(exist_ok=True)
            return d

    # XDG fallback
    xdg = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return xdg / "cobuilder"

def pipelines_dir(work_dir: Path | None = None) -> Path:
    return (work_dir or cobuilder_work_dir()) / "pipelines"

def signals_dir(work_dir: Path | None = None) -> Path:
    return (work_dir or cobuilder_work_dir()) / "signals"

def state_dir(work_dir: Path | None = None) -> Path:
    return (work_dir or cobuilder_work_dir()) / "state"
```

This is the "10x simplification": one 40-line module replaces every hardcoded path string across the entire codebase. Every consumer calls `cobuilder.dirs.signals_dir()` instead of constructing `.claude/attractor/signals/`. The env var override means tests need only `os.environ["COBUILDER_WORK_DIR"] = str(tmp_path)` — the existing `ATTRACTOR_SIGNALS_DIR` pattern, but unified.

---

## Implementation Phases

### Phase 0: Add `cobuilder/dirs.py` (The Foundation)

**Goal**: Introduce the new path resolution module without breaking anything.

**Deliverables**:
- `cobuilder/dirs.py` as described above
- Export `cobuilder_work_dir`, `pipelines_dir`, `signals_dir`, `state_dir` from `cobuilder/__init__.py`
- Add `COBUILDER_WORK_DIR` to `.claude/settings.json` env block (value: `${CLAUDE_PROJECT_DIR}/.cobuilder`)
- Unit tests for all four resolution steps

**Acceptance criteria**:
- `cobuilder_work_dir()` returns `.cobuilder/` adjacent to `.git/` when `COBUILDER_WORK_DIR` is unset
- Setting `COBUILDER_WORK_DIR=/tmp/test` makes all four functions return paths under `/tmp/test`
- No existing tests break

**Risk**: None. This is purely additive.

---

### Phase 1: Migrate `cobuilder/pipeline/signal_protocol.py`

**Goal**: Replace hardcoded `.claude/attractor/signals/` fallback with `cobuilder.dirs.signals_dir()`.

**Current resolution chain in `signal_protocol.py`**:
```
1. Explicit argument
2. ATTRACTOR_SIGNALS_DIR env var
3. {git_root}/.claude/attractor/signals/   ← REMOVE THIS
4. ~/.claude/attractor/signals/             ← REPLACE WITH dirs fallback
```

**New resolution chain**:
```
1. Explicit argument
2. ATTRACTOR_SIGNALS_DIR env var  (keep for backward compat — maps to COBUILDER_WORK_DIR/signals)
3. cobuilder.dirs.signals_dir()   (uses COBUILDER_WORK_DIR or git-walk)
```

**Migration of the 367 DOT files**: The DOT files themselves do not embed signal paths — they reference node IDs. Signal paths are resolved at runtime by `signal_protocol.py`. The 367 checkpoint JSON files in `.claude/attractor/examples/` reference signal paths only in their `payload` fields — those paths are written at signal-creation time using the runtime resolution. Setting `COBUILDER_WORK_DIR` before running pipelines is sufficient. No DOT file changes required.

**Acceptance criteria**:
- Existing `ATTRACTOR_SIGNALS_DIR` tests pass without modification (env var is still honoured)
- New `COBUILDER_WORK_DIR` override makes signals go to `$COBUILDER_WORK_DIR/signals/`

---

### Phase 2: Migrate `cobuilder/engine/runner.py` and `cobuilder/engine/checkpoint.py`

**Goal**: Replace `_DEFAULT_PIPELINES_DIR = ".claude/attractor/pipelines"` with `cobuilder.dirs.pipelines_dir()`.

**Change**:
```python
# Before
_DEFAULT_PIPELINES_DIR: str = ".claude/attractor/pipelines"

# After
from cobuilder.dirs import pipelines_dir as _resolve_pipelines_dir
# used as: _resolve_pipelines_dir() at call time, not module load time
```

**Why call-time not import-time**: Avoids partially-initialized module errors during import (Hindsight-informed decision). The user has a documented preference for factories over module-level state.

**Acceptance criteria**:
- `cobuilder pipeline run <file.dot>` stores checkpoints under `.cobuilder/pipelines/` by default
- `--pipelines-dir` CLI flag continues to override (already implemented in `cobuilder/cli.py`)

---

### Phase 3: Migrate `cobuilder/orchestration/runner_tools.py` State Paths

**Goal**: Remove the `~/.claude/attractor/state` fallback from `runner_tools.py`.

```python
# Before (line 407)
os.path.expanduser("~/.claude/attractor/state")

# After
from cobuilder.dirs import state_dir
state_dir()  # resolves to .cobuilder/state/
```

**Acceptance criteria**:
- RunnerState JSON is written to `.cobuilder/state/{pipeline-id}.json`
- Audit JSONL is written to `.cobuilder/state/{pipeline-id}-audit.jsonl`
- Existing checkpoint resume tests pass with `COBUILDER_WORK_DIR` set to tmp

---

### Phase 4: Implement The Ghost Directory (Shim Layer)

**Goal**: Replace `.claude/scripts/attractor/` content with auto-generated shims.

**The `cobuilder setup-harness` command** (new subcommand in `cobuilder/cli.py`):

```python
@app.command("setup-harness")
def setup_harness(
    target: Path = typer.Argument(default=Path(".claude/scripts/attractor")),
    overwrite: bool = typer.Option(False, "--overwrite")
):
    """
    Generate shim files in .claude/scripts/attractor/ that delegate to cobuilder.

    Run this once after installing cobuilder. The generated files are NOT committed
    to version control — they are regenerated on each install.
    """
```

**What the shims look like** (generated, not hand-maintained):

```python
# .claude/scripts/attractor/pipeline_runner.py  (GENERATED — do not edit)
# Generated by: cobuilder setup-harness
# Source of truth: cobuilder/orchestration/pipeline_runner.py
"""Shim: delegates to cobuilder.orchestration.pipeline_runner"""
from cobuilder.orchestration.pipeline_runner import *  # noqa: F401,F403
from cobuilder.orchestration.pipeline_runner import main

if __name__ == "__main__":
    main()
```

**Files requiring a non-trivial shim** (only one):

`spawn_orchestrator.py` already imports `from cobuilder.bridge import scoped_refresh`. The shim is identical to others — the real code is already in `cobuilder/`.

**Files to DELETE outright** (confirmed dead code from Hindsight analysis of 2026-03-04):
- `poc_pipeline_runner.py`
- `poc_test_scenarios.py`
- `runner_test_scenarios.py`
- `test_logfire_guardian.py`
- `test_logfire_sdk.py`
- `capture_output.py`
- `check_orchestrator_alive.py`
- `send_to_orchestrator.py`
- `wait_for_guardian.py`
- `wait_for_signal.py`
- `read_signal.py`
- `respond_to_runner.py`
- `escalate_to_terminal.py`

That is 13 files (of 48) confirmed dead. The remaining 35 become shims.

**Add to `.gitignore`**:
```
# CoBuilder auto-generated harness shims
.claude/scripts/attractor/
```

**Acceptance criteria**:
- `cobuilder setup-harness` generates correct shim files
- `python .claude/scripts/attractor/pipeline_runner.py --help` works after generation
- `.claude/scripts/attractor/` is in `.gitignore`
- `git ls-files .claude/scripts/attractor/` returns empty (no committed shims)

---

### Phase 5: Migrate Runtime State from `.claude/attractor/` to `.cobuilder/`

**Goal**: Move the 367 checkpoint files and example DOT files to `.cobuilder/`.

**Migration script** (`cobuilder migrate-state` command):

```bash
cobuilder migrate-state \
    --from .claude/attractor \
    --to .cobuilder \
    --dry-run  # preview first
```

The script:
1. Copies `.claude/attractor/pipelines/` to `.cobuilder/pipelines/`
2. Copies `.claude/attractor/examples/` to `.cobuilder/pipelines/examples/`
3. Copies `.claude/attractor/state/` to `.cobuilder/state/`
4. Rewrites any absolute `.claude/attractor/signals/` paths inside checkpoint JSON files to use the new `.cobuilder/signals/` path
5. Leaves `.claude/attractor/` intact with a `MIGRATED.md` marker (for rollback safety)

**Acceptance criteria**:
- All 367 checkpoint files accessible from `.cobuilder/`
- `cobuilder pipeline run` resumes from migrated checkpoints
- `.claude/attractor/` can be deleted after 30-day observation period

---

### Phase 6: Trim `.claude/` to Its Intended Size

**Goal**: Remove everything from `.claude/` that is not Claude Code native config.

**What stays in `.claude/`**:
```
.claude/
├── settings.json          # Claude Code config
├── settings.local.json    # Local overrides
├── CLAUDE.md              # Codebase instructions
├── hooks/                 # Python/shell lifecycle handlers
├── skills/                # SKILL.md files
├── output-styles/         # Agent behavior definitions
├── commands/              # Slash commands
├── scripts/
│   ├── completion-state/  # cs-* commands (these are legitimate Claude hooks)
│   ├── doc-gardener/      # Documentation linter (legitimate tooling)
│   └── attractor/         # SHIMS ONLY (generated, gitignored)
├── agents/                # Agent markdown configs
├── documentation/         # ADRs
└── narrative/             # Session narrative files
```

**What moves out**:
| Current Location | New Location |
|---|---|
| `.claude/attractor/pipelines/` | `.cobuilder/pipelines/` |
| `.claude/attractor/signals/` | `.cobuilder/signals/` |
| `.claude/attractor/state/` | `.cobuilder/state/` |
| `.claude/attractor/examples/` | `.cobuilder/pipelines/examples/` |
| `.claude/attractor/.env` | `.cobuilder/.env` (or project root `.env`) |

**Expected size reduction**: From 77 MB to approximately 2-3 MB (the bulk of `.claude/` is the pipeline state and checkpoint JSON files).

---

## The 10x Simplification

The single most radical cut available is this: **delete `.claude/scripts/attractor/` from version control entirely**.

Every file in it is either:
- Dead code (13 files, confirmed)
- A duplicate of something in `cobuilder/` (remaining 35 files)

The only reason to keep it is backward compatibility with Claude Code hooks that reference scripts by path. Those hooks can be updated to call `cobuilder` CLI commands instead. For example:

```json
// .claude/settings.json hook BEFORE
{
  "hooks": {
    "Stop": "python .claude/scripts/attractor/pipeline_runner.py --status"
  }
}

// AFTER
{
  "hooks": {
    "Stop": "cobuilder pipeline status"
  }
}
```

If that full migration is done, `.claude/scripts/attractor/` can be deleted with zero shim generation needed. This is the **radical cut** — it trades a one-time hook-update effort for permanent simplicity.

---

## Novel Naming Convention Ideas

### Rename `attractor` to `cobuilder`

The word "attractor" was an internal codename. It is opaque to new contributors and confusing when mixed with the `cobuilder` package name. Proposed renaming:

| Old | New | Rationale |
|---|---|---|
| `ATTRACTOR_SIGNALS_DIR` | `COBUILDER_SIGNALS_DIR` | Consistent namespace |
| `.claude/attractor/` | `.cobuilder/` | Matches package name |
| `attractor` module/package | absorbed into `cobuilder` | One namespace |
| `runner_guardian.py` | `cobuilder/orchestration/watchdog.py` | Describes function (watches, wakes) |
| `guardian.py` | `cobuilder/orchestration/supervisor.py` | Clearer role name |

The `ATTRACTOR_SIGNALS_DIR` env var can remain as a deprecated alias pointing to `COBUILDER_SIGNALS_DIR` for one major version, then removed.

### File Naming Within `cobuilder/orchestration/`

Current names cause confusion (`guardian.py` vs `runner_guardian.py`, `runner.py` vs `pipeline_runner.py`). Proposed canonical names:

| Current File | Proposed Name | Role |
|---|---|---|
| `pipeline_runner.py` | `runner.py` | Main entry point for pipeline execution |
| `runner_tools.py` | `runner_tools.py` | Helper functions (keep as-is) |
| `runner_models.py` | `models.py` | Pydantic models (conventional Python name) |
| `runner_hooks.py` | `hooks.py` | Hook callbacks |
| `runner_guardian.py` (attractor) | `watchdog.py` | Moved to `cobuilder/orchestration/` |
| `guardian.py` (attractor) | DELETED | Merged into watchdog or supervisor |
| `spawn_orchestrator.py` | `launcher.py` | Consistent verb-as-noun |

---

## Ideas That Sound Crazy But Might Work

### Idea 1: CoBuilder as a Claude Code Plugin

Instead of living in the project repo at all, CoBuilder could be published as a Claude Code plugin (`.claude-plugin/plugin.json` format, as seen in Hindsight from the mcp-skills-plugin). The plugin manifest declares:

```json
{
  "name": "cobuilder",
  "hooks": {
    "SessionStart": "cobuilder harness-init --auto"
  },
  "commands": [
    { "name": "/pipeline", "handler": "cobuilder pipeline" },
    { "name": "/cobuilder", "handler": "cobuilder" }
  ]
}
```

Users install CoBuilder globally via `pip install cobuilder` and the plugin is registered once in `~/.claude/plugins/`. No project-repo footprint at all. This is the "kernel module" analogy — CoBuilder loads into the Claude runtime without polluting the project directory.

**Risk**: Claude Code plugin API for hooks and commands is not yet stable enough for a tool this complex. Treat as a future target, not a Phase 1 commitment.

### Idea 2: The Symlink Bridge

Instead of shim files, make `.claude/scripts/attractor/` a symlink to `cobuilder/` subdirectories:

```bash
ln -s $(pwd)/cobuilder/orchestration .claude/scripts/attractor
```

This means the same file is simultaneously `cobuilder/orchestration/pipeline_runner.py` AND `.claude/scripts/attractor/pipeline_runner.py`. Zero maintenance, zero duplication, zero shim generation needed. Works because `cobuilder/` uses relative imports (`from cobuilder.engine import...`) which resolve correctly regardless of how the file is invoked.

**Risk**: Windows compatibility (symlinks require elevated permissions). Does not apply here (macOS environment confirmed). If this repo is always macOS/Linux, the symlink bridge is viable with no downside.

### Idea 3: Declarative Harness Manifest

A `cobuilder.toml` at project root that CoBuilder reads on startup:

```toml
[cobuilder]
work_dir = ".cobuilder"
log_level = "INFO"

[cobuilder.harness]
# Paths that .claude/ hooks should use
signals_env = "COBUILDER_SIGNALS_DIR"
state_env = "COBUILDER_STATE_DIR"

[cobuilder.harness.hooks]
# Map Claude Code hook events to cobuilder commands
Stop = "cobuilder pipeline status --check"
```

This makes `.claude/settings.json` a thin bridge that reads from `cobuilder.toml`, rather than hardcoding paths. Claude Code settings stay minimal; all CoBuilder behaviour is declared in `cobuilder.toml`.

---

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| `.cobuilder/` gitignored accidentally | High | Medium | Add explicit `!.cobuilder/` to `.gitignore`; only gitignore the state subdirs |
| 367 checkpoint files not migrated cleanly | Medium | Low | `cobuilder migrate-state --dry-run` + keep `.claude/attractor/` as backup for 30 days |
| `ATTRACTOR_SIGNALS_DIR` tests break after rename | Medium | Low | Keep deprecated alias for one version; all tests currently use env var already |
| Shim generation step forgotten after reinstall | Medium | Medium | Add shim generation to `pip install` post-install hook via hatchling plugin |
| Namespace collision if `cobuilder` installed globally | Low | Low | `cobuilder.dirs` only calls `os.environ.get` — no global state |
| Large-scale directory migration causes broken imports | Medium | Medium | (Hindsight-informed) Do phases sequentially, run full test suite after each phase before proceeding |

---

## Success Metrics

| Metric | Current | Target |
|---|---|---|
| `.claude/` directory size | 77 MB | < 3 MB |
| Python files in `.claude/scripts/attractor/` | 48 | 0 (committed) / 35 (generated shims, gitignored) |
| Cross-imports between attractor and cobuilder | 1 | 0 |
| Hardcoded `.claude/attractor/` path strings in `cobuilder/` | 12 | 0 |
| Entry point for pipeline execution | `python .claude/scripts/attractor/pipeline_runner.py` | `cobuilder pipeline run` |
| Dead code files | 13 confirmed | 0 |
| State path resolution | ad-hoc per file | single `cobuilder.dirs` module |

---

## Handoff Summary for Orchestrator

### Implementation Priority

1. **Phase 0** (foundation): `cobuilder/dirs.py` — purely additive, zero risk, unblocks all other phases
2. **Phase 1** (signals): `signal_protocol.py` migration — highest user-visible pain point
3. **Phase 4** (shims): `cobuilder setup-harness` command — eliminates maintenance burden
4. **Phases 2-3** (state paths): routine path replacement — mechanical, low risk
5. **Phase 5** (migrate): `cobuilder migrate-state` — production data, needs extra care
6. **Phase 6** (cleanup): `.claude/` trim — satisfying but last in sequence

### Agent Assignments

| Phase | Agent | Why |
|---|---|---|
| 0, 1, 2, 3 | `backend-solutions-engineer` | Python package work, `cobuilder/` is backend |
| 4 | `backend-solutions-engineer` | CLI subcommand, shim generation logic |
| 5 | `backend-solutions-engineer` | Migration script with file I/O and JSON rewriting |
| 6 | Orchestrator (investigation only) | Config file changes, `.gitignore` updates |
| Tests | `tdd-test-engineer` | All new modules need pytest coverage |

### Key Files for Each Agent

**Phase 0**: Create `/Users/theb/Documents/Windsurf/claude-harness-setup/cobuilder/dirs.py`; update `cobuilder/__init__.py`

**Phase 1**: Edit `cobuilder/pipeline/signal_protocol.py` lines 26-27 and 88-91

**Phase 2**: Edit `cobuilder/engine/runner.py` line 119; `cobuilder/engine/checkpoint.py` lines 160, 198

**Phase 3**: Edit `cobuilder/orchestration/runner_tools.py` line 407

**Phase 4**: Add `setup-harness` subcommand to `cobuilder/cli.py`; update `.gitignore`

**Phase 5**: Add `migrate-state` subcommand to `cobuilder/cli.py`

### The One Decision That Changes Everything

If the team accepts the Symlink Bridge (Idea 2), Phases 4 and 5 collapse into a single `ln -sf` command and a `.gitignore` entry. Estimated effort drops from 3-4 days to 2 hours. The prerequisite is confirming that all `cobuilder/orchestration/*.py` files use relative imports (they do — `cobuilder/engine/runner.py` imports via `from cobuilder.engine.checkpoint import...`). The symlink is safe.
