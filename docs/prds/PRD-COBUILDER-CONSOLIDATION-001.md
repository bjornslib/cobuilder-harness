---
title: "PRD: CoBuilder Consolidation — Standalone Autonomous Coding Harness"
status: active
type: guide
last_verified: 2026-03-09
grade: authoritative
---

# PRD-COBUILDER-CONSOLIDATION-001: CoBuilder Consolidation

## 1. Business Goal

Transform CoBuilder from a package embedded within the Claude Code harness into a **standalone autonomous coding harness** by:
- Consolidating `.claude/scripts/attractor/` (32K lines) into the `cobuilder/` package
- Moving runtime state (pipelines, signals, checkpoints) from `.claude/` to `.cobuilder/`
- Eliminating dead code, naming confusion, and duplicated modules
- Unifying CLI entry points under `cobuilder`

**Outcome**: `.claude/` contains ONLY Claude Code native config (<5MB). All Python code lives in `cobuilder/`. Runtime state lives in `.cobuilder/`. One CLI to rule them all.

## 2. Problem Statement

The current codebase has grown organically, resulting in:

1. **Split codebase**: Pipeline orchestration code lives in `.claude/scripts/attractor/` (47 files, 32K lines) while the installable package `cobuilder/` (70K lines) duplicates much of the same functionality with different implementations.

2. **21 same-named file conflicts**: `pipeline_runner.py`, `runner.py`, `cli.py`, `parser.py`, `transition.py`, `signal_protocol.py`, `validator.py`, `checkpoint.py`, `spawn_orchestrator.py`, and 12 more — each with different code in attractor/ vs cobuilder/.

3. **77MB .claude/ directory**: Mixed config, code, and runtime state. Claude Code expects settings, hooks, skills, and output-styles — not 367 pipeline DOT files and execution logs.

4. **Dead code accumulation**: 13+ confirmed-dead files in attractor, superseded LLM-based runner in cobuilder/orchestration/, empty CLI groups, misplaced root artifacts.

5. **Pervasive anti-pattern**: Every attractor file uses `sys.path.insert(0, SCRIPT_DIR)` for bare imports like `from parser import parse_file` — incompatible with Python package structure and causes shadowing risks.

6. **Security**: `private.pem` committed to repo root.

## 3. Evidence (from 7-Architect Parallel Solutioning)

Seven solution-design-architect agents independently analyzed this problem using different reasoning strategies. Their consensus:

| Finding | Agreement | Source |
|---------|-----------|--------|
| Delete dead code first (zero risk) | 7/7 | All architects |
| `cobuilder/orchestration/pipeline_runner.py` is superseded LLM-based runner | 7/7 | Architects 1, 3, 4, 6 explicitly |
| State belongs in `.cobuilder/` (XDG-aligned, project-relative) | 5/7 | Architects 2, 3, 7 + research |
| Subpackage absorb (`cobuilder/attractor/`) is best migration path | 5/7 | Architects 1, 4, 6 |
| Only ~35 live path references matter (not 781) | 6/7 | Architect 5, 6 measured |
| Signal dirs computed dynamically — moving DOTs is safe | 5/7 | Architect 5 discovered |
| `VALID_TRANSITIONS` divergence must be fixed before migration | 4/7 | Architect 3 discovered |
| `sys.path` hacks require coordinated batch fixes, not file-by-file | 6/7 | Architects 4, 5, 6 |
| Attractor always wins in same-named conflicts | 5/7 | Architects 1, 2, 4 |

Architect SD documents preserved in `docs/prds/SD-COBUILDER-CONSOLIDATION-*.md` and `SD-ATTRACTOR-CONSOLIDATION-001.md`.

## 4. User Stories

**As a developer** copying this harness into a project repo, I want all Python code in one installable package (`pip install -e .`) so I don't have to understand the `.claude/scripts/attractor/` vs `cobuilder/` split.

**As an LLM agent** reading output-styles and skills, I want consistent paths that point to real code locations so I don't call scripts that have moved.

**As an operator** managing pipeline state, I want runtime data clearly separated from configuration so I can gitignore state without risking config loss.

**As a maintainer**, I want zero dead code, zero naming confusion, and one place to look for any module.

## 5. Scope

### In Scope
- Dead code deletion (13 attractor files, superseded cobuilder/orchestration/, root artifacts)
- Runtime state migration from `.claude/attractor/` to `.cobuilder/`
- Attractor code consolidation into `cobuilder/attractor/` subpackage
- Import surgery: `sys.path.insert` → proper package imports
- CLI unification under `cobuilder` entry point
- Documentation/skill path reference updates (49 markdown files)
- Naming convention fixes (runner_guardian.py confusion, etc.)
- `private.pem` security remediation

### Out of Scope
- Rewriting cobuilder/engine/ or cobuilder/repomap/ internals
- Changing pipeline DOT file format or schema
- Modifying Claude Code itself (settings.json, hooks behavior)
- Application code changes in pinchtab/, src/

## 6. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| `.claude/` size | 77MB | <5MB |
| Python files in `.claude/scripts/attractor/` | 47 | 0 |
| Dead code files | 13+ | 0 |
| Same-named file conflicts | 21 | 0 |
| `sys.path.insert` occurrences | ~47 | 0 |
| Hardcoded `.claude/attractor/` path refs | ~35 live | 0 |
| CLI entry points | 3 (cobuilder, zerorepo, attractor scripts) | 1 (cobuilder) |
| Tests passing | baseline | baseline (no regression) |

## 7. Architecture Overview

### Target Directory Structure

```
claude-harness-setup/
├── .claude/                     # Claude Code native config ONLY (<5MB)
│   ├── settings.json
│   ├── output-styles/           # orchestrator.md, system3-meta-orchestrator.md
│   ├── hooks/                   # Lifecycle handlers
│   ├── skills/                  # Skill implementations
│   ├── commands/                # Slash commands
│   ├── agents/                  # Agent .md configurations
│   ├── documentation/           # ADRs, guides
│   ├── tests/                   # Hook/workflow tests
│   └── schemas/, config/, validation/
│
├── .cobuilder/                  # Runtime state (GITIGNORED)
│   ├── pipelines/              # DOT files (was .claude/attractor/pipelines/)
│   ├── signals/                # Worker status JSONs
│   ├── checkpoints/            # State snapshots
│   ├── runner-state/           # Execution logs
│   ├── evidence/               # Validation artifacts
│   └── examples/               # Example pipelines (committed subset)
│
├── cobuilder/                   # THE installable package (all Python code)
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                  # Unified Typer CLI
│   ├── dirs.py                 # NEW: Path resolution (walk-up, env override)
│   ├── bridge.py
│   ├── attractor/              # NEW: Absorbed from .claude/scripts/attractor/
│   │   ├── pipeline_runner.py  # Production state machine (1,669 lines)
│   │   ├── session_runner.py   # Renamed from runner.py (avoid engine clash)
│   │   ├── guardian.py         # System 3 terminal + guardian agent
│   │   ├── dispatch_worker.py
│   │   ├── run_research.py
│   │   ├── run_refine.py
│   │   ├── spawn_orchestrator.py
│   │   └── [signal_protocol, transition, parser, validator, ...]
│   ├── engine/                 # Pipeline execution (existing)
│   │   └── runner.py           # Engine runner (802 lines, different purpose)
│   ├── pipeline/               # Pipeline generation (existing)
│   ├── orchestration/          # CLEANED: superseded files deleted
│   └── repomap/               # ZeroRepo (unchanged, 45K lines)
│
├── tests/                       # Consolidated tests
│   ├── attractor/              # Moved from .claude/scripts/attractor/tests/
│   └── integration/
│
├── docs/                        # Unchanged
├── acceptance-tests/            # Unchanged
└── pyproject.toml              # Updated entry points
```

### Key Design Decisions

1. **`cobuilder/dirs.py`**: A ~40-line module using git-style walk-up to resolve `.cobuilder/` state directory. Replaces ALL hardcoded paths. Supports `COBUILDER_STATE_DIR` env var override. (Architect 7 innovation)

2. **Subpackage absorb**: `cobuilder/attractor/` preserves the module's identity during transition. Modules can be gradually redistributed to `engine/`, `pipeline/`, `orchestration/` in future iterations.

3. **Attractor wins conflicts**: In all 21 same-named file pairs, the attractor version is newer, larger, and production-active. Cobuilder duplicates are either superseded or identical.

4. **30-day migration shim**: A thin `__init__.py` at the old `.claude/scripts/attractor/` path re-exports from `cobuilder.attractor.*` for backward compatibility during transition.

5. **`VALID_TRANSITIONS` fix before migration**: Architect 3 discovered the cobuilder version is missing `validated → accepted` and `failed → pending` transitions. Fix this divergence first to prevent mid-migration breakage.

## 8. Epics

### E0: Dead Code Cleanup
**Effort**: 0.5 days | **Risk**: Zero
- Delete 13 confirmed-dead attractor files (capture_output.py, check_orchestrator_alive.py, poc_pipeline_runner.py, poc_test_scenarios.py, runner_test_scenarios.py, test_logfire_guardian.py, test_logfire_sdk.py, + 6 more identified)
- Delete superseded `cobuilder/orchestration/pipeline_runner.py` (LLM-based, pre-E7)
- Remove empty `agents_app` stub from `cobuilder/cli.py`
- Clean root-level artifacts: test_*.py, test_*.dot, screen_*.png, *.log files
- Remove orphaned `.claude/signals/` and `.claude/message-bus/signals/` directories

### E1: Path Resolution Module (`dirs.py`)
**Effort**: 0.5 days | **Risk**: Low
- Create `cobuilder/dirs.py` with walk-up algorithm for `.cobuilder/` discovery
- Support `COBUILDER_STATE_DIR` env var override (highest priority)
- Support `ATTRACTOR_SIGNAL_DIR` env var (backward compat, forever contract)
- Default: walk up from CWD looking for `.cobuilder/`, create if not found
- Unit tests for all resolution paths

### E2: Fix Divergences
**Effort**: 0.5 days | **Risk**: Low-Medium
- Add missing `validated → accepted` and `failed → pending` to `cobuilder/pipeline/transition.py`
- Reconcile any other divergences between attractor and cobuilder module pairs
- Ensure signal protocol schemas match between both locations
- Tests for reconciled transitions

### E3: State Directory Migration
**Effort**: 1 day | **Risk**: Medium
- Create `.cobuilder/` directory structure
- Move `.claude/attractor/pipelines/` → `.cobuilder/pipelines/`
- Move `.claude/attractor/signals/` → `.cobuilder/signals/`
- Move `.claude/attractor/checkpoints/` → `.cobuilder/checkpoints/`
- Move `.claude/attractor/runner-state/` → `.cobuilder/runner-state/`
- Move `.claude/attractor/examples/` → `.cobuilder/examples/` (committed subset)
- Move `.claude/attractor/.env` → `.cobuilder/.env` (SDK worker model config: ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, ANTHROPIC_API_KEY)
- Add `.cobuilder/` to `.gitignore` (except examples/)
- Update `pipeline_runner.py` to load `.env` from `.cobuilder/.env` (with fallback to old path)
- ~~`dirs.py`~~: Dropped — a simple `COBUILDER_STATE_DIR` env var in `.cobuilder/.env` replaces the walk-up discovery logic. The pipeline runner already computes signal/checkpoint paths relative to the DOT file location; no centralized resolver needed.

### E4: Attractor Code Migration
**Effort**: 2 days | **Risk**: Medium-High
- `git mv .claude/scripts/attractor/*.py` → `cobuilder/attractor/`
- `git mv .claude/scripts/attractor/tests/` → `tests/attractor/`
- Rename `runner.py` → `session_runner.py` (avoid engine/runner.py clash)
- Rename `runner_guardian.py` → clarified name (e.g., `guardian_hooks.py`)
- Create `cobuilder/attractor/__init__.py` with proper package exports
- Leave 30-day shim at `.claude/scripts/attractor/` (re-exports)

### E5: Import Surgery
**Effort**: 1.5 days | **Risk**: Medium-High
- Replace ALL `sys.path.insert(0, SCRIPT_DIR)` with proper package imports
- Convert bare `from parser import ...` → `from cobuilder.attractor.parser import ...`
- Coordinated batch conversion (not file-by-file due to shadowing risk)
- Update all relative imports to absolute package imports
- Run full test suite after each batch

### E6: CLI Unification
**Effort**: 1 day | **Risk**: Medium
- Wire `attractor` subcommands into `cobuilder/cli.py` Typer app
- Create `cobuilder attractor` command group (14 subcommands from attractor/cli.py)
- Wire `cobuilder guardian` command group
- Verify `cobuilder pipeline`, `cobuilder repomap` still work
- Update `pyproject.toml` entry points

### E7: Documentation & Path Reference Updates
**Effort**: 1 day | **Risk**: Low
- Update 49 markdown path references across output-styles/ and skills/
- Update `system3-meta-orchestrator.md` pipeline launch commands
- Update `s3-guardian/SKILL.md` and all reference files
- Update `orchestrator.md` if it references attractor paths
- Update `worker-tool-reference.md` if needed
- Update `CLAUDE.md` architecture section
- Update hook scripts that reference `.claude/scripts/attractor/`

### E8: Security Remediation
**Effort**: 0.5 days | **Risk**: Low (operational)
- Rotate the key associated with `private.pem`
- Remove `private.pem` from repo using `git filter-branch` or BFG
- Add `*.pem` to `.gitignore`
- Audit for any other committed secrets

## 9. Dependencies

```
E0 (Dead Code) ✅ ──────────────────────────────┐
E2 (Fix Diverge) ✅                              │
E3 (State Migration + .env) ────────────────────┤
                    E4+E5 (Code + Imports) ──────├──→ E7 (Docs)
                    E6 (CLI Unification) ────────┘
E8 (Security) ✅ ── independent
~~E1 (dirs.py)~~ ── dropped, replaced by env var
```

- E0 has no dependencies (safe first)
- E1+E2 can run in parallel
- E3 depends on E1 (needs dirs.py)
- E4 depends on E2 (divergences fixed) and E3 (state moved)
- E5 depends on E4 (code in new location)
- E6 depends on E4+E5 (imports working)
- E7 depends on E4+E5+E6 (all paths finalized)
- E8 is independent

## 10. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Import breakage from sys.path removal | High | High | Batch conversion, full test suite after each batch |
| Missed markdown path reference | Medium | Medium | Automated grep sweep, CI check |
| Active pipeline breaks during state move | Medium | High | Quiesce check before move, 30-day fallback paths |
| `runner_tools.py` CLI_PATH hardcoded | High | High | Update in E5, add to dirs.py resolution |
| Test import failures after git mv | High | Medium | Update conftest.py and test imports in E4 |
| Git history loss on rename+edit | Low | Low | Separate git mv commits from content edits |

## 11. Open Questions

1. Should `cobuilder/attractor/` eventually be dissolved into `engine/`, `pipeline/`, `orchestration/`? (Deferred — subpackage is stable landing zone first)
2. Should the `zerorepo` CLI alias be preserved or deprecated in favor of `cobuilder repomap`?
3. Which `.cobuilder/examples/` files should be committed vs gitignored?

## 12. Timeline Estimate

| Phase | Epics | Duration | Cumulative |
|-------|-------|----------|------------|
| Phase 0 | E0 | 0.5 days | 0.5 days |
| Phase 1 | E1 + E2 (parallel) | 0.5 days | 1 day |
| Phase 2 | E3 | 1 day | 2 days |
| Phase 3 | E4 + E5 | 3.5 days | 5.5 days |
| Phase 4 | E6 + E7 (parallel) | 1 day | 6.5 days |
| Phase 5 | E8 | 0.5 days | 7 days |

**Total: ~7 working days** across 8 epics.

## 13. Absorbed Hardening Work (from SD-PIPELINE-RUNNER-HARDENING-001)

The following remaining hardening epics from PRD-HARNESS-UPGRADE-001 / SD-PIPELINE-RUNNER-HARDENING-001 are absorbed into this consolidation:

| Hardening Epic | Absorbed Into | Description |
|----------------|---------------|-------------|
| **D: Orphan Resume Expansion** | E2 (Fix Divergences) | Extend orphan resume to all handler types (research, refine, acceptance-test-writer), not just codergen. Exponential backoff with max 3 retries. Gate nodes emit escalation signals. |
| **E.3: Persistent Requeue Guidance** | E2 (Fix Divergences) | Replace `.pop()` one-shot guidance with file-backed persistence so validation feedback survives across multiple retries. |
| **F: Global Pipeline Safeguards** | E4-E5 (Code Migration) | Pipeline timeout (`--max-duration`), cost tracking in signals, per-worker-type rate limiting. Deferred to code migration phase. |

**Rationale**: These improvements strengthen the pipeline runner before it moves into `cobuilder/attractor/`. Fixing them during consolidation avoids migrating known-buggy code.

## 14. Implementation Status

| Epic | Status | Date | Commits | Notes |
|------|--------|------|---------|-------|
| **E0: Dead Code Cleanup** | **DONE** | 2026-03-10 | `5333115` | 23 files deleted, 3,232 lines removed. 11 dead attractor files + superseded cobuilder/orchestration/pipeline_runner.py + 10 root artifacts + empty dirs + empty CLI group. |
| **E8: Security Remediation** | **DONE** | 2026-03-10 | `5333115` | private.pem deleted, *.pem added to .gitignore, worktree copies cleaned. |
| **Bugfix: Liveness Race** | **DONE** | 2026-03-10 | `6337153` | Liveness checker now checks node status before writing error signals. Prevents spurious failures from overwriting processed signals. |
| **Bugfix: Monitor Cycles** | **DONE** | 2026-03-10 | `6337153` | Monitor pattern updated to blocking 10min cycles in s3-guardian SKILL.md and system3-meta-orchestrator.md. |
| ~~E1: dirs.py~~ | **Dropped** | 2026-03-11 | — | Replaced by `COBUILDER_STATE_DIR` env var in `.cobuilder/.env`. Pipeline runner computes paths relative to DOT files — no centralized resolver needed. |
| **E2: Fix Divergences (+D, E.3)** | **DONE** | 2026-03-10 | `bb5b60e` | Added validated→accepted, failed→pending to cobuilder transition.py. check_finalize_gate accepts both states. Persistent requeue guidance loader. 18 new tests. |
| E3: State Migration (+.env) | **Next** | — | — | Includes .env move from .claude/attractor/ to .cobuilder/. No longer depends on E1. |
| E4+E5: Code Migration + Import Surgery | Pending | — | — | Combined. Worktree isolation. Includes absorbed hardening F. |
| E6: CLI Unification | Pending | — | — | Depends on E4+E5 |
| E7: Documentation Updates | Pending | — | — | Depends on E4+E5+E6 |
