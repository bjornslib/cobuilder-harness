---
title: "Consolidate Hardcoded Model References to attractor/.env"
status: active
type: reference
prd_id: PRD-ENV-MODEL-001
last_verified: 2026-03-07
grade: authoritative
---

# PRD-ENV-MODEL-001: Consolidate Hardcoded Model References to attractor/.env

## Business Goal

Headless and SDK attractor scripts should read model identifiers from `.claude/attractor/.env` via the existing `load_attractor_env()` function, eliminating hardcoded Claude model strings in API-billed code paths. This enables switching to alternative providers (e.g., Qwen via DashScope) without code changes.

**Scope exclusion**: tmux mode (`spawn_orchestrator.py --mode tmux`) uses Max plan interactive sessions with no per-token API cost. The hardcoded `claude-sonnet-4-6` in `_build_claude_cmd()` is intentional and MUST NOT be changed.

## Current State

The `load_attractor_env()` function in `dispatch_worker.py` already parses `.claude/attractor/.env` for `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, and `ANTHROPIC_MODEL`. Two scripts (`guardian.py`, `runner.py`) already call `os.environ.update(load_attractor_env())` at startup. Two scripts do NOT:

| File | Hardcoded Model | Line | Mode |
|------|----------------|------|------|
| `run_research.py` | `claude-haiku-4-5-20251001` | 30 | Headless/SDK (API-billed) |
| `run_refine.py` | `claude-sonnet-4-6` | 30 | Headless/SDK (API-billed) |
| `spawn_orchestrator.py` | `claude-sonnet-4-6` | 78 | **tmux (Max plan) — KEEP AS-IS** |

## Requirements

### Epic 1: Env-Load Consolidation (Headless/SDK paths only)

**E1-T1**: In `run_research.py`, import `load_attractor_env` from `dispatch_worker`, call `os.environ.update(load_attractor_env())` before argparse, and change `DEFAULT_MODEL` to read from `os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")`.

**E1-T2**: In `run_refine.py`, same pattern — import `load_attractor_env`, call it before argparse, change `DEFAULT_MODEL` to `os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")`.

**E1-T3**: Update affected tests in `tests/test_run_research.py` and any tests asserting specific default models to account for env-based defaults (mock `os.environ` or `load_attractor_env`).

## Out of Scope

- `spawn_orchestrator.py` line 78 (`_build_claude_cmd`) — tmux mode intentionally uses hardcoded `claude-sonnet-4-6` (Max plan, no API cost)
- `guardian.py`, `runner.py`, `dispatch_worker.py` — already load from `.env`

## Acceptance Criteria

1. When `.claude/attractor/.env` sets `ANTHROPIC_MODEL=qwen3-coder-plus`, `run_research.py` and `run_refine.py` use that model instead of hardcoded defaults
2. When `.env` is absent or `ANTHROPIC_MODEL` is unset, existing hardcoded defaults are preserved (backward compatible)
3. `ANTHROPIC_BASE_URL` from `.env` is also propagated to research/refine scripts
4. `spawn_orchestrator.py` tmux command remains hardcoded to `claude-sonnet-4-6`
5. All existing tests pass (no regressions)
