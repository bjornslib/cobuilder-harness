---
title: "Claude Harness Repository Cleanup"
description: "Cleanup and consolidation of the cobuilder-harness repository to eliminate runtime artifacts"
version: "1.1.0"
last-updated: 2026-03-22
status: active
type: prd
grade: authoritative
prd_id: PRD-HARNESS-CLEANUP-001
---

# PRD-HARNESS-CLEANUP-001: Claude Harness Repository Cleanup

## Overview

The claude-harness-setup repository has accumulated runtime artifacts, untracked files, and inconsistent gitignore coverage over multiple development sessions. This initiative cleans up the repository to a maintainable state.

## Goals

1. Eliminate untracked cruft from the repository (checkpoint files, evidence records, test artifacts)
2. Update .gitignore to prevent future accumulation
3. Consolidate scattered acceptance tests to a single location
4. Track documentation files that should be version-controlled
5. Remove or relocate root-level test artifacts that don't belong in the harness

## Non-Goals

- Restructuring the core .claude/ directory layout (skills, hooks, scripts are well-organized)
- Changing the attractor pipeline system itself
- Modifying the completion-state or message-bus systems

## Acceptance Criteria

### Epic 1: Gitignore Updates

**AC-1.1**: `.claude/.gitignore` updated with patterns for:
- `attractor/pipelines/*-checkpoint-*.json`
- `attractor/pipelines/signals/`
- `attractor/runner-state/`
- `attractor/checkpoints/`
- `completion-state/session-state.json`
- `evidence/*` with `!evidence/.gitkeep`
- `scripts/prototypes/`

**AC-1.2**: Root `.gitignore` updated with patterns for:
- `.serena/`
- `.zerorepo/`
- `trees/`
- `completion-state/` (root-level, not .claude/)
- `settings.local.json`
- `test` (root empty file)

**AC-1.3**: All existing gitignore patterns still work correctly (no regressions)

### Epic 2: File Cleanup

**AC-2.1**: Root-level `test` file (0B empty artifact) deleted
**AC-2.2**: Untracked checkpoint files in `.cobuilder/pipelines/` cleaned up (deleted or moved)
**AC-2.3**: `.gitkeep` files created in directories that need to exist but should be empty (evidence/, attractor/checkpoints/, attractor/runner-state/, attractor/pipelines/signals/)

### Epic 3: Track Untracked Documentation

**AC-3.1**: `.claude/documentation/ARCHITECTURE-ARTICLE.md` tracked in git
**AC-3.2**: `.claude/documentation/SOLUTION-DESIGN-P11-DEPLOY-001.md` tracked in git
**AC-3.3**: `.claude/skills/s3-guardian/references/sdk-cli-tools.md` tracked in git
**AC-3.4**: `.claude/skills/s3-guardian/references/sdk-mode.md` tracked in git

### Epic 4: Acceptance Test Consolidation

**AC-4.1**: Decision documented on acceptance test location (root `acceptance-tests/` vs `.claude/acceptance-tests/`)
**AC-4.2**: All acceptance tests in one location (consolidated)
**AC-4.3**: Gitignore updated for the chosen location pattern

### Epic 5: Verification

**AC-5.1**: `git status` shows clean working directory (no untracked files that should be ignored)
**AC-5.2**: All tests pass (`pytest .claude/scripts/attractor/tests/ -x -q`)
**AC-5.3**: Deploy harness to all targets succeeds
**AC-5.4**: Newly generated artifacts (checkpoints, signals) are properly gitignored

## Technical Approach

1. Update gitignore files first (prevents re-accumulation)
2. Clean up existing artifacts
3. Track documentation files
4. Consolidate acceptance tests
5. Verify clean state + run tests + deploy

## Estimated Effort

Small-medium initiative. 5 epics, ~15 tasks. Most are file operations (gitignore edits, git add/rm). No code logic changes.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| Epic 1: Gitignore Updates | Done | 2026-03-22 | (this PR) |
| Epic 2: File Cleanup | Done | 2026-03-22 | (this PR) |
| Epic 3: Track Untracked Documentation | Deferred | - | Already tracked or deleted as dead files |
| Epic 4: Acceptance Test Consolidation | Done | 2026-03-22 | Tests consolidated at root `acceptance-tests/` |
| Epic 5: Verification | In Progress | 2026-03-22 | - |
