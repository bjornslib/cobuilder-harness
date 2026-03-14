# PRD-HARNESS-RELIABILITY-001: Harness Reliability + Setup Hook Integration

## Overview
Fix known reliability issues in the claude-harness-setup repository and integrate automatic
git hook installation into the setup-harness skill's copy-to-target workflow.

**PRD ID**: PRD-HARNESS-RELIABILITY-001
**Status**: Active
**Priority**: P2
**Owner**: System 3 Meta-Orchestrator
**Target Repository**: claude-harness-setup
**Estimated Effort**: Small (single orchestrator session, ~1 hour)

## Background
PR #11 (merged as `b53ae31`) added `cli.py install-hooks` for symlink-based pre-push hook
installation. However, validation of PR #9 and PR #11 revealed three reliability issues and
one gap in the setup-harness deployment workflow:

1. **Setup-harness gap**: The skill copies `.claude/hooks/` to targets but does not call
   `cli.py install-hooks` to create the `.git/hooks/pre-push` symlink. Users must manually
   install the hook after deploying the harness.

2. **Example file pollution**: `full-initiative.dot` has `validate_backend_tech` stuck in
   `active` state from WS2 integration testing. Example files should always be in clean
   (all-pending) state.

3. **Worktree path resolution**: `cli.py install-hooks` uses `os.path.abspath()` which
   resolves to the worktree path at installation time. When the worktree is removed, the
   symlink breaks. Should use a path relative to `.git/hooks/` or resolve via the main
   working tree.

4. **cs-store-validation DX**: Running `cs-store-validation --help` fails with a Python
   path resolution error. The script's `__main__` module detection needs fixing.

## Scope

### IN Scope
- Setup-harness hook installation step
- Example DOT file cleanup
- install-hooks path resolution fix
- cs-store-validation help/usage fix

### OUT of Scope
- New hook types (only pre-push for now)
- Changes to the doc-gardener linter itself
- Attractor CLI feature additions
- cs-verify gate logic changes

---

## Epic 1: Setup-Harness Hook Integration

### Problem
When a developer runs `/setup-harness` to deploy the Claude Code harness to a new project,
the pre-push hook files are copied but not installed into `.git/hooks/`. The developer must
manually create the symlink, which is error-prone and often forgotten.

### Requirements

- **R1.1**: Add a new step to the setup-harness SKILL.md workflow (after Step 10 "Verify
  Setup", before Step 11 "Provide Next Steps") that:
  1. Detects if the target directory is a git repository (`git rev-parse --git-dir`)
  2. Checks if `.claude/hooks/doc-gardener-pre-push.sh` exists in the target
  3. Calls `python3 .claude/scripts/attractor/cli.py install-hooks` (or equivalent) to
     create the `.git/hooks/pre-push` symlink
  4. Verifies the symlink was created and is executable

- **R1.2**: The hook installation must be **non-blocking** — if the target is not a git
  repository, skip gracefully with a warning message.

- **R1.3**: Update the "Next steps" completion summary (Step 11) to include:
  ```
  - Git hooks: pre-push hook installed (doc-gardener lint enforcement)
  ```

- **R1.4**: If a pre-push hook already exists at `.git/hooks/pre-push`, warn the user
  and ask whether to replace it (do not silently overwrite).

### Acceptance Criteria
- AC-1: Running `/setup-harness` on a git repo automatically installs the pre-push hook
- AC-2: Running `/setup-harness` on a non-git directory skips hook installation gracefully
- AC-3: Existing pre-push hooks are not silently overwritten
- AC-4: Verification step confirms the symlink exists and is executable

---

## Epic 2: Harness Reliability Fixes

### Problem
Three issues discovered during PR #9 / PR #11 validation need fixing:
1. Example DOT file has test pollution
2. install-hooks creates worktree-fragile symlinks
3. cs-store-validation CLI has broken --help

### Feature 2.1: Reset full-initiative.dot Example

**Requirements**:
- **R2.1.1**: Reset `validate_backend_tech` node in `.cobuilder/examples/full-initiative.dot`
  from `status="active"` back to `status="pending"` (or remove the status attribute entirely
  so it defaults to pending)
- **R2.1.2**: Verify all nodes in the example file are in their default/clean state

**Acceptance Criteria**:
- AC-5: `python3 .claude/scripts/attractor/cli.py status .cobuilder/examples/full-initiative.dot`
  shows all nodes as `pending` (no `active`, `validated`, or `failed` nodes)

### Feature 2.2: Worktree-Safe Hook Symlinks

**Requirements**:
- **R2.2.1**: Modify `cli.py install-hooks` to create a **relative symlink** from
  `.git/hooks/pre-push` to the hook source, OR resolve the path via `git rev-parse
  --show-toplevel` (main working tree root) instead of `os.path.abspath()` on the
  current working directory.
- **R2.2.2**: The symlink must survive worktree removal — it should point to a path
  that exists in the main working tree, not the worktree.
- **R2.2.3**: `git rev-parse --git-common-dir` is ALREADY used to find the hooks
  directory (correct). The fix is specifically about how the **source path** of the
  symlink is resolved.

**Acceptance Criteria**:
- AC-6: Running `install-hooks` from a worktree creates a symlink that resolves to
  a path in the main working tree (not the worktree)
- AC-7: The symlink still works after the worktree is removed

### Feature 2.3: cs-store-validation DX Fix

**Requirements**:
- **R2.3.1**: Fix `cs-store-validation --help` so it displays usage information instead
  of failing with `can't find '__main__' module` error.
- **R2.3.2**: The fix should be in the script header/shebang or module resolution logic —
  not a behavioral change.

**Acceptance Criteria**:
- AC-8: `cs-store-validation --help` prints usage information and exits 0
- AC-9: `cs-store-validation` with no args prints usage and exits non-zero (not a traceback)

---

## Technical Notes

### File Locations

| File | Purpose |
|------|---------|
| `.claude/skills/setup-harness/SKILL.md` | Setup-harness workflow definition |
| `.claude/scripts/attractor/cli.py` | Attractor CLI with `install-hooks` subcommand |
| `.cobuilder/examples/full-initiative.dot` | Example DOT pipeline file |
| `.claude/hooks/doc-gardener-pre-push.sh` | Pre-push hook script |
| `.claude/scripts/completion-state/cs-store-validation` | Validation storage CLI |

### Dependencies
- None — all changes are within the harness repository
- No external service dependencies

### Risk Assessment
- **Low risk**: All changes are to harness configuration, not application code
- **Reversible**: All file edits can be reverted via git
- **No breaking changes**: Existing setup-harness users get hook installation as a bonus step
