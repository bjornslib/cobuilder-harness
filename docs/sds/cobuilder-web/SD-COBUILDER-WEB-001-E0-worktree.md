---
title: "SD-COBUILDER-WEB-001 Epic 0: Stable Worktree Infrastructure"
status: active
type: solution-design
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E0
---

# SD-COBUILDER-WEB-001 Epic 0: Stable Worktree Infrastructure

## 1. Problem Statement

Pipeline workers dispatched by `pipeline_runner.py` currently execute in a single shared directory (either `target_dir` from the DOT graph or the DOT file's own directory). This creates three concrete problems:

1. **Merge conflicts between concurrent workers.** Two codergen nodes editing the same file in parallel will race. The second worker to `git add && git commit` silently overwrites the first worker's changes, or fails with a dirty-tree error.

2. **No isolation between pipeline runs.** When System 3 launches a second pipeline against the same target repository, workers from pipeline A and pipeline B share a working directory. Partial commits from one pipeline pollute the other.

3. **Stale worktree accumulation.** The existing `spawn_orchestrator.py` creates worktrees at `.claude/worktrees/<node_id>/` via `claude --worktree`, but nothing cleans them up after the pipeline completes. Over time, abandoned worktrees consume disk and confuse `git branch --list`.

**Why this must be solved first (Epic 0):** Every subsequent epic in PRD-COBUILDER-WEB-001 dispatches multiple workers in parallel. Without stable worktree isolation, worker output is unreliable and non-reproducible. The worktree layer is a foundational dependency.

## 2. Technical Architecture

### 2.1 WorktreeManager Class

A stateless utility class that wraps `git worktree` commands with idempotency guarantees. It owns no persistent state; the git worktree list itself is the source of truth.

**Module location:** `cobuilder/web/api/infra/worktree_manager.py`

```python
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorktreeInfo:
    """Immutable snapshot of a single git worktree."""
    path: str          # Absolute path on disk
    branch: str        # Branch name (e.g., "worktree-PRD-COBUILDER-WEB-001")
    commit: str        # HEAD commit SHA (short)
    prd_id: str        # PRD identifier extracted from path convention


class WorktreeManager:
    """Manages git worktrees for pipeline isolation.

    Convention:
        path:   {target_repo}/.claude/worktrees/{prd_id}/
        branch: worktree-{prd_id}

    All methods are idempotent and safe to call concurrently
    (protected by git's own lock file mechanism).
    """

    WORKTREE_DIR = ".claude/worktrees"
    BRANCH_PREFIX = "worktree-"

    def get_or_create(
        self,
        prd_id: str,
        target_repo: str,
        base_branch: str = "main",
    ) -> str:
        """Return the absolute path to a worktree for the given PRD.

        If the worktree already exists and is valid, returns its path
        without modification. If it does not exist, creates it from
        base_branch.

        Args:
            prd_id: PRD identifier (e.g., "PRD-COBUILDER-WEB-001").
            target_repo: Absolute path to the git repository root.
            base_branch: Branch to fork from when creating. Default "main".

        Returns:
            Absolute path to the worktree directory.

        Raises:
            WorktreeError: If git commands fail (e.g., repo not found,
                branch conflict, lock contention).
        """
        ...

    def list_active(self, target_repo: str) -> list[WorktreeInfo]:
        """List all pipeline worktrees managed by this class.

        Filters git worktree list output to only those under
        {target_repo}/.claude/worktrees/. Does NOT include the main
        worktree or worktrees created by other tools.

        Args:
            target_repo: Absolute path to the git repository root.

        Returns:
            List of WorktreeInfo, sorted by prd_id.
        """
        ...

    def cleanup(self, prd_id: str, target_repo: str) -> bool:
        """Remove the worktree and its branch for a completed pipeline.

        Idempotent: returns True if the worktree was removed (or was
        already absent). Returns False only on unexpected git errors.

        Args:
            prd_id: PRD identifier.
            target_repo: Absolute path to the git repository root.

        Returns:
            True if cleanup succeeded, False otherwise.
        """
        ...

    def validate(self, prd_id: str, target_repo: str) -> bool:
        """Check whether a worktree exists and is in a clean state.

        "Clean" means: directory exists, is a valid git worktree,
        and HEAD is reachable from the expected branch.

        Args:
            prd_id: PRD identifier.
            target_repo: Absolute path to the git repository root.

        Returns:
            True if the worktree is valid and clean.
        """
        ...
```

### 2.2 Internal Git Commands

Each public method maps to specific git operations:

#### `get_or_create(prd_id, target_repo, base_branch="main")`

```
Step 1: Compute paths
    worktree_path = {target_repo}/.claude/worktrees/{prd_id}/
    branch_name   = worktree-{prd_id}

Step 2: Check existing worktrees
    git -C {target_repo} worktree list --porcelain
    Parse output for worktree_path. If found and directory exists:
        return worktree_path   (idempotent exit)

Step 3: Handle stale entry (listed but directory missing)
    git -C {target_repo} worktree prune
    (Removes stale entries so the add command succeeds)

Step 4: Create parent directory
    os.makedirs(os.path.dirname(worktree_path), exist_ok=True)

Step 5: Create worktree
    If branch exists locally:
        git -C {target_repo} worktree add {worktree_path} {branch_name}
    Else:
        git -C {target_repo} worktree add -b {branch_name} {worktree_path} {base_branch}

Step 6: Verify
    assert os.path.isdir(worktree_path)
    return worktree_path
```

#### `list_active(target_repo)`

```
Step 1: List all worktrees
    git -C {target_repo} worktree list --porcelain

Step 2: Parse porcelain output
    Each entry is:
        worktree /absolute/path
        HEAD <sha>
        branch refs/heads/<name>
        (blank line)

Step 3: Filter to managed worktrees
    Keep only entries where path starts with
    {target_repo}/.claude/worktrees/

Step 4: Extract prd_id from path
    prd_id = basename(path)

Step 5: Return sorted list of WorktreeInfo
```

#### `cleanup(prd_id, target_repo)`

```
Step 1: Compute paths (same as get_or_create)

Step 2: Remove worktree (force, handles dirty trees)
    git -C {target_repo} worktree remove --force {worktree_path}
    Catch CalledProcessError — if "not a working tree", already gone.

Step 3: Prune stale entries
    git -C {target_repo} worktree prune

Step 4: Delete branch (optional, only if worktree was the sole user)
    git -C {target_repo} branch -D {branch_name}
    Catch CalledProcessError — branch may already be deleted.

Step 5: Return True (or False on unexpected error)
```

#### `validate(prd_id, target_repo)`

```
Step 1: Check directory exists
    os.path.isdir(worktree_path) -> False means invalid

Step 2: Verify it is a git worktree
    git -C {worktree_path} rev-parse --is-inside-work-tree
    Must return "true"

Step 3: Verify branch matches
    git -C {worktree_path} symbolic-ref --short HEAD
    Must equal {branch_name}

Step 4: Return True if all checks pass
```

### 2.3 Error Handling

```python
class WorktreeError(Exception):
    """Base exception for worktree operations."""

    def __init__(self, message: str, prd_id: str, git_stderr: str = ""):
        self.prd_id = prd_id
        self.git_stderr = git_stderr
        super().__init__(message)


class WorktreeLockError(WorktreeError):
    """Raised when git worktree lock file prevents operation."""
    pass


class WorktreeBranchConflictError(WorktreeError):
    """Raised when the target branch is already checked out elsewhere."""
    pass
```

**Error detection strategy:** All `subprocess.run()` calls use `capture_output=True, text=True`. The stderr output is inspected for known git error patterns:

| stderr pattern | Exception raised | Recovery |
|----------------|------------------|----------|
| `fatal: '.claude/worktrees/X' is a missing but locked worktree` | `WorktreeLockError` | Caller retries after `git worktree unlock` |
| `fatal: 'worktree-X' is already checked out at` | `WorktreeBranchConflictError` | Caller uses existing worktree path from message |
| `fatal: not a git repository` | `WorktreeError` | Abort — target_repo is wrong |
| Any other non-zero exit | `WorktreeError` with full stderr | Log and propagate |

### 2.4 Subprocess Wrapper

All git commands route through a single internal helper for consistent logging and error handling:

```python
def _run_git(
    self,
    args: list[str],
    cwd: str,
    prd_id: str,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command with logging and structured error handling.

    Args:
        args: Git arguments (without the leading "git").
        cwd: Working directory for the command.
        prd_id: PRD ID for error context.
        check: If True, raise WorktreeError on non-zero exit.

    Returns:
        CompletedProcess with stdout/stderr captured.
    """
    cmd = ["git"] + args
    log.debug("[worktree] Running: %s (cwd=%s)", " ".join(cmd), cwd)
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        if "locked worktree" in stderr:
            raise WorktreeLockError(
                f"Worktree locked: {stderr}", prd_id=prd_id, git_stderr=stderr,
            )
        if "already checked out" in stderr:
            raise WorktreeBranchConflictError(
                f"Branch conflict: {stderr}", prd_id=prd_id, git_stderr=stderr,
            )
        raise WorktreeError(
            f"git {args[0]} failed: {stderr}", prd_id=prd_id, git_stderr=stderr,
        )
    return result
```

## 3. Integration Points

### 3.1 pipeline_runner.py Changes

The runner's `_get_target_dir()` method is the single integration point. Today it reads `target_dir` from the DOT graph attributes and falls back to `dot_dir`. The change adds a worktree resolution step between these two:

**Current implementation** (`pipeline_runner.py:395-400`):

```python
def _get_target_dir(self) -> str:
    """Return target directory for worker execution. Falls back to dot_dir."""
    target = self._graph_attrs.get("target_dir", "")
    if target and os.path.isdir(target):
        return target
    return self.dot_dir
```

**Proposed implementation:**

```python
def _get_target_dir(self) -> str:
    """Return target directory for worker execution.

    Resolution order:
    1. If graph has `worktree_path` AND the directory exists on disk, use it.
    2. If graph has `worktree_path` AND `target_dir`, call
       WorktreeManager.get_or_create() to provision the worktree, then use it.
    3. If graph has `target_dir` and it exists, use it (legacy behavior).
    4. Fall back to dot_dir.
    """
    worktree_path = self._graph_attrs.get("worktree_path", "")
    target_dir = self._graph_attrs.get("target_dir", "")

    # Worktree already exists on disk — use it directly
    if worktree_path and os.path.isdir(worktree_path):
        return worktree_path

    # Worktree requested but not yet created — provision it
    if worktree_path and target_dir:
        prd_id = self._graph_attrs.get("prd_ref", "")
        if prd_id:
            from cobuilder.web.api.infra.worktree_manager import WorktreeManager
            mgr = WorktreeManager()
            try:
                created_path = mgr.get_or_create(prd_id, target_dir)
                log.info("[worktree] Provisioned: %s", created_path)
                return created_path
            except Exception as exc:
                log.warning("[worktree] Failed to provision: %s — falling back", exc)

    # Legacy: direct target_dir
    if target_dir and os.path.isdir(target_dir):
        return target_dir

    return self.dot_dir
```

**Key design decisions:**

- **Lazy import.** `WorktreeManager` is imported inside the method to avoid a hard dependency for pipelines that do not use worktrees.
- **Graceful fallback.** If worktree provisioning fails, the runner falls back to `target_dir` or `dot_dir` rather than aborting the pipeline. This preserves backward compatibility.
- **Single call site.** Every worker dispatch in the runner already calls `self._get_target_dir()` for `cwd`. No other methods need modification.

### 3.2 DOT Graph Attributes

Two new graph-level attributes:

```dot
digraph "PRD-COBUILDER-WEB-001" {
    graph [
        prd_ref="PRD-COBUILDER-WEB-001"
        target_dir="/Users/theb/Documents/Windsurf/target-repo"
        worktree_path=".claude/worktrees/PRD-COBUILDER-WEB-001/"  // NEW
        base_branch="main"                                         // NEW (optional)
    ];
    // ... nodes ...
}
```

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `worktree_path` | string | No | Relative path (from `target_dir`) or absolute path to the worktree. Triggers worktree provisioning when set. |
| `base_branch` | string | No | Branch to fork from. Defaults to `"main"`. |

**Backward compatibility:** Existing DOT files without `worktree_path` behave exactly as before. The new attributes are additive.

### 3.3 Parser Compatibility

No changes needed to `cobuilder/attractor/parser.py`. The parser already extracts arbitrary key-value pairs from `graph [...]` blocks (lines 168-174). The new `worktree_path` and `base_branch` attributes are automatically available via `pipeline_data["graph_attrs"]`.

### 3.4 Pipeline Cleanup Hook

After a pipeline reaches terminal state (all nodes `accepted` or `failed`), the runner should call `WorktreeManager.cleanup()`. This hooks into the existing completion detection in the runner's main loop:

```python
# In PipelineRunner.run(), after detecting terminal state:
if all_terminal and worktree_path:
    from cobuilder.web.api.infra.worktree_manager import WorktreeManager
    mgr = WorktreeManager()
    prd_id = self._graph_attrs.get("prd_ref", "")
    if prd_id and self._graph_attrs.get("target_dir"):
        mgr.cleanup(prd_id, self._graph_attrs["target_dir"])
        log.info("[worktree] Cleaned up worktree for %s", prd_id)
```

## 4. Files Changed

### New Files

| File | Description |
|------|-------------|
| `cobuilder/web/__init__.py` | Package init (empty) |
| `cobuilder/web/api/__init__.py` | Package init (empty) |
| `cobuilder/web/api/infra/__init__.py` | Package init (empty) |
| `cobuilder/web/api/infra/worktree_manager.py` | `WorktreeManager` class with `get_or_create`, `list_active`, `cleanup`, `validate` |
| `tests/web/test_worktree_manager.py` | Unit tests for WorktreeManager (mocked git subprocess calls) |
| `tests/web/__init__.py` | Package init (empty) |

### Modified Files

| File | Change Description |
|------|-------------------|
| `cobuilder/attractor/pipeline_runner.py` | Modify `_get_target_dir()` to resolve `worktree_path` via WorktreeManager; add cleanup call on pipeline terminal state |

## 5. Implementation Priority

The implementation should proceed in this order, each step building on the previous:

### Phase 1: Core Class (Day 1)

1. **`_run_git()` helper** — Foundation for all operations. Includes logging, timeout, structured error detection.
2. **`WorktreeError` hierarchy** — `WorktreeError`, `WorktreeLockError`, `WorktreeBranchConflictError`.
3. **`get_or_create()`** — The critical method. Must be idempotent from the start. Handles the stale-entry prune, branch-exists check, and creation.
4. **`list_active()`** — Porcelain parser. Useful for debugging and the validate step.

### Phase 2: Lifecycle (Day 1-2)

5. **`validate()`** — Lightweight health check used before dispatch.
6. **`cleanup()`** — Force-remove with branch deletion. Tolerant of already-removed state.

### Phase 3: Integration (Day 2)

7. **`_get_target_dir()` modification** — Wire WorktreeManager into the runner with lazy import and graceful fallback.
8. **Cleanup hook** — Add post-pipeline cleanup call in the runner's terminal-state handler.

### Phase 4: Tests (Day 2-3)

9. **Unit tests** — Mock `subprocess.run` to test all git command paths: create fresh, idempotent reuse, stale prune, lock error, branch conflict, cleanup of absent worktree.
10. **Integration test** — One test that creates a real worktree in a temp git repo, lists it, validates it, and cleans it up. Uses `tempfile.mkdtemp()` + `git init`.

## 6. Acceptance Criteria

From PRD-COBUILDER-WEB-001 Epic 0:

| ID | Criterion | Verification |
|----|-----------|--------------|
| AC-E0.1 | `get_or_create("PRD-X", repo)` creates worktree at `{repo}/.claude/worktrees/PRD-X/` on branch `worktree-PRD-X` | Unit test: assert path exists, `git branch` lists branch |
| AC-E0.2 | Calling `get_or_create` twice with the same arguments returns the same path without error | Unit test: second call returns same path, git is NOT called a second time for `worktree add` |
| AC-E0.3 | `list_active(repo)` returns only worktrees under `.claude/worktrees/`, not the main worktree | Unit test: mock `git worktree list --porcelain` with mixed entries, assert filter |
| AC-E0.4 | `cleanup("PRD-X", repo)` removes the worktree directory AND the branch | Unit test: assert `worktree remove --force` and `branch -D` are called |
| AC-E0.5 | `cleanup` on an already-absent worktree returns True without error | Unit test: mock git error for missing worktree, assert returns True |
| AC-E0.6 | `pipeline_runner._get_target_dir()` resolves `worktree_path` from DOT graph and calls `get_or_create` when directory is missing | Integration test: DOT with `worktree_path` attribute, assert runner dispatches workers to worktree cwd |
| AC-E0.7 | Pipelines without `worktree_path` in their DOT graph behave identically to current behavior | Regression test: DOT without `worktree_path`, assert `_get_target_dir()` returns `target_dir` or `dot_dir` |
| AC-E0.8 | Runner calls `cleanup()` when pipeline reaches terminal state | Integration test: run pipeline to completion, assert worktree directory is removed |

## 7. Risks & Edge Cases

### 7.1 Concurrent Worktree Creation

**Risk:** Two pipeline runner instances call `get_or_create()` for the same PRD simultaneously.

**Mitigation:** Git's own `.git/worktrees/<name>/locked` mechanism serializes worktree operations. If two processes race on `git worktree add`, the second gets a lock error. `get_or_create()` handles this:

1. Catch `WorktreeLockError`.
2. Sleep 1 second.
3. Re-check `git worktree list`. If the worktree now exists, return its path (the other process won the race).
4. If still absent after 3 retries, propagate the error.

```python
# Inside get_or_create():
for attempt in range(3):
    try:
        self._run_git(["worktree", "add", ...], ...)
        break
    except WorktreeLockError:
        if attempt < 2:
            time.sleep(1)
            # Re-check: other process may have created it
            if os.path.isdir(worktree_path):
                return worktree_path
        else:
            raise
```

### 7.2 Orphaned Worktrees

**Risk:** Pipeline crashes (runner killed, machine reboots) leave worktrees on disk with no pipeline to clean them up.

**Mitigation:** Two-layer defense:

1. **`git worktree prune`** is called at the start of `get_or_create()` to remove stale entries where the directory has been deleted but the git metadata remains.
2. **Periodic garbage collection.** A future System 3 health check (not in this epic) can call `list_active()` across all target repos and compare against running pipelines. Orphans older than 24 hours get cleaned up.

For this epic, the `cleanup()` method is the primary defense. The PRD notes that System 3 should call cleanup after validating pipeline results.

### 7.3 Branch Conflicts

**Risk:** A branch named `worktree-PRD-X` already exists and is checked out in the main worktree or another worktree.

**Mitigation:** `get_or_create()` detects `WorktreeBranchConflictError` and attempts recovery:

1. Parse the conflicting worktree path from git's error message (`already checked out at '/path/to/...'`).
2. If the conflicting path matches our expected `worktree_path`, the worktree already exists — return it.
3. If it is a different path (e.g., someone manually checked out the branch), raise the error with a clear message indicating manual resolution is needed.

### 7.4 Dirty Worktree on Cleanup

**Risk:** Worker left uncommitted changes in the worktree. `git worktree remove` without `--force` will refuse.

**Mitigation:** `cleanup()` always uses `--force`. Uncommitted work in a pipeline worktree is expendable — the worker should have committed and pushed before signaling completion. The `--force` flag is safe here because pipeline worktrees are ephemeral by design.

### 7.5 Path Length Limits

**Risk:** Deeply nested paths like `/Users/theb/Documents/Windsurf/target-repo/.claude/worktrees/PRD-COBUILDER-WEB-001/` approach filesystem limits on some platforms.

**Mitigation:** The `prd_id` is used directly as the directory name (no additional nesting). PRD IDs are typically 15-25 characters. The full path stays well under the 260-character Windows limit and the 1024-character macOS/Linux limit. No action needed beyond documenting the convention.

### 7.6 Target Repo Without `.claude/` Directory

**Risk:** `target_dir` points to a repository that does not have a `.claude/` directory.

**Mitigation:** `get_or_create()` calls `os.makedirs(os.path.dirname(worktree_path), exist_ok=True)` which creates `.claude/worktrees/` if absent. The `.claude/` directory itself is not special here — it is just a conventional namespace to avoid polluting the repo root.

### 7.7 Worktree Manager Used Outside Pipeline Runner

**Risk:** Other tools (e.g., `spawn_orchestrator.py`) use Claude's native `--worktree` flag, which creates worktrees at `.claude/worktrees/<name>/` with branch `worktree-<name>`. These could collide with `WorktreeManager`-created worktrees if the names overlap.

**Mitigation:** Convention separation. `spawn_orchestrator.py` uses node IDs as names (e.g., `impl_auth`), while `WorktreeManager` uses PRD IDs (e.g., `PRD-COBUILDER-WEB-001`). PRD IDs always contain uppercase and hyphens, making accidental collision extremely unlikely. The `list_active()` filter uses path prefix matching, so it only returns worktrees it created.
