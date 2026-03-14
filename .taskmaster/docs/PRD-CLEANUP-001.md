# PRD-CLEANUP-001: .claude Directory Cleanup

**Status**: Active
**Priority**: P2
**Date**: 2026-02-24

---

## Problem Statement

The `.claude/` directory has accumulated stale files, empty placeholders, archived artifacts, orphaned hooks, project-specific content, and build caches over 6+ weeks of development. This wastes context tokens and creates confusion about what is actively used.

## Goals

1. Remove confirmed-unused files (empty, archived, cached, project-specific)
2. Cross-reference and remove orphaned hooks, utils, and commands
3. Clean stale runtime state and consolidate documentation

## Non-Goals

- Refactoring active code or changing working behavior
- Modifying `settings.json` hook registrations
- Changing directory structure or moving files

---

## Task 1: Safe Deletes — Confirmed Unused Files

Remove files and directories where no investigation is needed.

**Scope:**
- Empty files: `.claude/test`, `.claude/.doc-gardener-skip` (if unreferenced)
- Empty dirs: `.claude/progress/`
- Placeholders: `.claude/state/.gitkeep`, `.claude/evidence/.gitkeep`, `.claude/completion-state/.gitkeep`
- Archives: `.claude/skills/_archived/` (s3-communicator, replaced by GChat hooks), `.claude/hooks/archive/` (old hook versions)
- Caches: all `__pycache__/` dirs under `.claude/`
- Project-specific: `.claude/learnings/*.md`, `.claude/user-input-queue/EXAMPLE-*.md`
- **KEEP**: `.claude/schemas/v3.9-*.md` (used by agencheck-communication-agent)
- Gitignore: add `__pycache__/` to `.claude/.gitignore`

**Acceptance Criteria:**
- All listed files/dirs deleted
- `.claude/.gitignore` updated with `__pycache__/` pattern
- `pytest .claude/tests/ -q` passes after deletions

---

## Task 2: Cross-Reference Analysis — Orphaned Hooks, Utils, Commands

Investigate and remove files not referenced anywhere in the codebase.

**Scope:**
- Hooks NOT in `settings.json`: `completion-gate.py`, `completion-gate.sh`, `context-preserver-hook.py`, `context-reinjector-hook.py`, `decision-time-guidance-hook.py`, `test-stop-gate.sh`
- Utils: `advisory-report.sh`, `commit-range.sh`, `doc-cleanup.sh`, `document-lifecycle.sh` — grep for references in tests/hooks
- Commands: `o3-pro.md`, `use-codex-support.md`, `website-upgraded.md`, `parallel-solutioning.md`, `check-messages.md`

**Method:** `grep -r "filename" .claude/` for each file. Delete if zero references. Keep and document if referenced.

**Acceptance Criteria:**
- Each file disposition recorded (deleted or kept-with-reason)
- Zero orphaned hooks remain (all either in settings.json, referenced elsewhere, or deleted)
- `pytest .claude/tests/ -q` passes

---

## Task 3: State Cleanup + Documentation Consolidation

Clean runtime state and review documentation for currency.

**Scope — State:**
- `.claude/state/*/` marker files older than 7 days — delete
- `.cobuilder/pipelines/*.json` checkpoints — keep latest only per pipeline
- `.cobuilder/pipelines/signals/`, `.claude/message-bus/signals/` — empty
- `.claude/completion-state/sessions/` older than 14 days — delete
- `.claude/completion-state/history/` — KEEP (audit trail, never delete)

**Scope — Documentation:**
Review these files, delete if superseded or one-time work:
- `DECISION_TIME_GUIDANCE.md`, `STOP_GATE_CONSOLIDATION.md`, `NATIVE-TEAMS-EPIC1-FINDINGS.md`
- `ORCHESTRATOR_ARCHITECTURE_V2.md`, `SKILL-DEDUP-AUDIT.md`, `UPDATE-validation-agent-integration.md`
- `.claude/TM_COMMANDS_GUIDE.md` (may duplicate `/tm` commands)

**Acceptance Criteria:**
- State dirs cleaned per retention policy
- Each doc reviewed and resolved (kept or deleted)
- `git diff --stat` shows only deletions + .gitignore edit
- `pytest .claude/tests/ -q` passes

---

## Validation

After all tasks:
1. `pytest .claude/tests/` — all tests pass
2. `git diff --stat` — only deletions (no accidental modifications)
3. No broken references in settings.json or active skills
