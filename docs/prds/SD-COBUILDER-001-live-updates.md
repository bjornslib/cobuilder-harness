---
title: "SD: Live Baseline Updates and Completion Promise Enforcement"
prd_id: PRD-COBUILDER-001
epic: 4
status: active
type: architecture
created: 2026-02-27
last_verified: 2026-02-27
grade: authoritative
---

# SD-COBUILDER-001-E4: Live Baseline Updates and Completion Promise Enforcement

## Executive Summary

Epic 4 closes the feedback loop between implementation work and codebase knowledge. When an orchestrator's worker validates a DOT pipeline node, the RepoMap baseline for the affected files must update within seconds — not on the next manual `cobuilder repomap sync` run. This epic wires that update into three places: (1) the state machine in `transition.py` that already fires on every node status change, (2) the orchestrator lifecycle manager `spawn_orchestrator.py` that runs cleanup on session end, and (3) the `cs-verify` stop-gate that already enforces completion promises.

**This is greenfield implementation.** Unlike Epics 2 and 3, no wiring gaps exist that a one-line fix can close. Every function described here must be authored from scratch.

**Implementation effort**: 3–5 days of focused implementation across five files. None of the individual pieces are architecturally complex, but they must integrate correctly to produce the event-driven freshness guarantee.

**The single hardest design decision**: scoped refresh. Full `repomap sync` on a 340-file codebase (the current claude-harness-setup baseline shows 2,593 nodes from 340 files) takes approximately 45–90 seconds. A scoped refresh that only re-scans the 3–15 files belonging to a single validated node must complete in under 10 seconds. The design below achieves this by adding a `walk_paths()` method to `CodebaseWalker` and a `merge_nodes()` operation to `BaselineManager`.

---

## 1. Business Context

### Problem Statement

RepoMap baselines become stale the moment implementation begins. The baseline is a snapshot of the codebase at scan time. As workers modify files, the snapshot diverges from reality. By the time an orchestrator's final node validates, the baseline may be describing structures that have been refactored, files that have been renamed, and interfaces that have changed signatures.

This staleness has two downstream effects:

- **Subsequent orchestrators** launched on the same codebase receive context that no longer matches the files they will modify. They will encounter implementation surprises that accurate baseline context would have prevented.
- **Solution-design-architect sessions** launched after implementation use stale context to author SDs for the next initiative, producing designs that reference outdated interfaces.

### Why Automatic Refresh Is Required

Manual refresh is not viable. The current workflow requires `cobuilder repomap sync --name <repo>` to be run explicitly. In a multi-orchestrator environment where nodes validate at different times, expecting manual sync after each node is unrealistic. The sync will be forgotten. The baseline will be stale.

The state machine in `transition.py` is the only place where all node validations converge. It already runs for every transition. Adding a post-validation hook there gives us universal coverage at zero additional coordination cost.

### Goals Served

| PRD Goal | Description | How Epic 4 Satisfies It |
|----------|-------------|------------------------|
| G3 | Baselines stay current during implementation | Post-validation hook refreshes baseline within 10s of node validation |
| G4 | Single `cobuilder` CLI unifies all operations | `cobuilder repomap refresh --scope` added as first-class subcommand |

### Acceptance Criteria Summary

Six ACs from PRD-COBUILDER-001 Epic 4:

| AC | Criterion |
|----|-----------|
| AC-1 | `transition.py` fires baseline refresh when codergen node transitions to `validated` |
| AC-2 | Scoped refresh completes in <10 seconds for typical node file scope |
| AC-3 | Worktrees created via `claude --worktree` contain `.repomap/` with current baseline |
| AC-4 | `cs-verify --check` blocks if baseline not refreshed since last node validation |
| AC-5 | cobuilder-guardian SKILL.md includes CoBuilder tmux commands for orchestrator boot |
| AC-6 | `spawn_orchestrator.py` runs `cobuilder repomap refresh` during cleanup |

AC-3 is satisfied by design (`.repomap/` is already committed to git and worktrees are full git checkouts), not by code. No implementation is required for AC-3. The remaining five ACs require code.

---

## 2. Technical Architecture

### 2.1 End-to-End Data Flow

```
Node transitions to "validated" in transition.py
        |
        v
_fire_post_validated_hook(dot_file, node_id, node_attrs)
        |
        +-- Extract file_path / folder_path from node attrs
        |       (comma-separated if multiple files)
        +-- Extract repo_name from DOT graph-level attributes
        |
        v
bridge.scoped_refresh(repo_name, scope=[...files...])
        |
        +-- Load existing baseline JSON
        +-- Walk ONLY the scoped paths via CodebaseWalker.walk_paths()
        +-- Merge scoped nodes into existing baseline
        +-- Rotate baseline.json → baseline.prev.json
        +-- Write merged baseline.json
        +-- Update manifest YAML (node_count, file_count, last_synced)
        +-- Update .repomap/config.yaml (last_synced, baseline_hash)
        |
        v
.repomap/baselines/<repo>/baseline.json updated (< 10 seconds)
        |
        v
[Optional] git add .repomap/ && git commit on worktree branch
```

```
Orchestrator completes (tmux session ends or signals finalize)
        |
        v
spawn_orchestrator.py: cleanup_orchestrator(session_name, repo_name, work_dir)
        |
        +-- git diff --name-only HEAD~1..HEAD (changed files in this session)
        +-- bridge.scoped_refresh(repo_name, scope=changed_files)
        +-- git add .repomap/ && git commit "chore: refresh baseline post-<session>"
```

```
cs-verify --check
        |
        v
[existing AC checks]
        |
        v
[NEW] check_repomap_freshness(pipeline_dot, repo_name)
        |
        +-- Read transitions JSONL: find last "validated" transition timestamp
        +-- Read .repomap/config.yaml: find last_synced for repo_name
        +-- Compare: if last_synced < last_validated_timestamp → BLOCK
        |
        v
[continue or block]
```

### 2.2 Why Transition.py Is the Right Hook Point

`transition.py` currently has three places where side effects are fired after a successful write:

1. `_append_transition_jsonl()` — appends to the JSONL audit log.
2. `_write_finalize_signal()` — writes a signal file for finalize nodes.

Both of these are called inside `_cmd_transition()`, after the file lock is released and the DOT file has been written. The baseline refresh hook must follow the same pattern: called after write, inside the same function, not inside `apply_transition()` (which is a pure string transformation with no I/O side effects).

The hook fires only when `new_status == "validated"` and only for nodes with `file_path` or `folder_path` attributes. Hexagon (validation gate) nodes do not carry file paths and are skipped automatically.

### 2.3 Scoped Refresh Design

The scoped refresh must satisfy two constraints: completeness (all changed files are included) and speed (<10 seconds).

**Completeness strategy**: The scope list is built from the node's `file_path` attribute, which is a comma-separated list of relative file paths (e.g., `"cobuilder/bridge.py,cobuilder/pipeline/transition.py"`). If `file_path` is absent, the `folder_path` attribute is used instead, which causes the entire folder to be re-scanned. This is the conservative fallback and ensures no changed file is missed.

**Speed strategy**: `CodebaseWalker.walk_paths(paths)` is added as a new method that accepts a list of specific file paths or directories. Unlike `walk()`, which recursively traverses the entire project root, `walk_paths()` only processes the named paths. For a typical 5–15 file node scope, this processes in under 2 seconds.

**Merge strategy**: The existing baseline contains nodes keyed by their `node_id` (a deterministic hash of the file path). Scoped refresh replaces existing nodes that match the scoped files' generated node IDs and appends any new nodes. Nodes for files not in scope are untouched. This is safe because: (a) the scoped files are the only files that changed, (b) unchanged files' node IDs are stable, (c) the baseline hash is recomputed after merge.

**Debounce**: If a refresh ran within the last 30 seconds for the same repo, the hook skips the refresh and logs a debug message. This prevents redundant re-scans when multiple nodes validate in quick succession.

### 2.4 Worktree Baseline Inheritance

No code is required. The `.repomap/` directory is committed to git (confirmed by the Glob output showing `.repomap/config.yaml`, `.repomap/baselines/`, `.repomap/manifests/` in the repository). When `claude --worktree <name>` creates a new worktree, it is a full git checkout of the current branch. The `.repomap/` directory and all its contents are present from the first moment.

After the worktree orchestrator validates nodes and the hook fires, the updated `baseline.json` is committed on the worktree branch. When the worktree branch merges to main, the updated baseline comes with it. No special handling is needed.

### 2.5 Completion Promise Enforcement Design

The `cs-verify --check` mode iterates all promises owned by the current session and checks their acceptance criteria. The new freshness check is inserted as an additional step after the existing AC checks, only when a `PIPELINE_DOT` environment variable or promise metadata points to an active pipeline.

The check is event-driven, not time-based. It compares two timestamps:
- `last_validated_timestamp`: the most recent `"validated"` entry in the pipeline's `.transitions.jsonl` file.
- `last_synced`: the `last_synced` field in `.repomap/config.yaml` for the relevant repo.

If `last_synced` is older than `last_validated_timestamp`, the check blocks with a clear message instructing the user to run `cobuilder repomap refresh --name <repo>`.

The promise AC is injected programmatically in `spawn_orchestrator.py` after the completion promise is created. This ensures every orchestrator, regardless of who spawned it, carries the baseline freshness requirement.

---

## 3. Functional Decomposition

### F4.1: `CodebaseWalker.walk_paths()` — Scoped File Walking

**File**: `cobuilder/repomap/serena/walker.py`

**What it does**: Accepts a list of file paths or directory paths. For files, creates exactly one COMPONENT node and attempts symbol extraction. For directories, recursively walks all Python/TypeScript files within that directory only. Returns an `RPGGraph` containing only the scoped nodes.

**Why it does not exist yet**: The existing `walk()` method takes a `project_root` and recursively walks the entire tree. There is no mechanism to restrict the walk to a subset of paths.

**Function signature**:

```python
def walk_paths(
    self,
    paths: list[str | Path],
    project_root: Path,
    exclude_patterns: list[str] | None = None,
) -> RPGGraph:
    """Walk only the specified file/directory paths and return an RPGGraph.

    Produces the same node structure as walk() but restricted to the
    given paths. File paths are processed directly; directory paths
    are walked recursively.

    Args:
        paths: List of relative or absolute file/directory paths to scan.
        project_root: The project root for computing relative node IDs.
        exclude_patterns: Optional patterns to exclude (same as walk()).

    Returns:
        RPGGraph containing nodes for the scoped paths only.
    """
```

**Implementation notes**:
- Resolve each path to absolute. If a path does not exist, log a warning and skip it.
- For file paths ending in `.py`, `.ts`, `.tsx`, `.js`, `.jsx`: call the analyzer directly on that file.
- For directory paths: call the existing `_walk_directory()` logic restricted to that directory.
- Use the same node ID generation logic as `walk()` so that node IDs are stable and the merge operation can match them correctly.
- Reuse `DEFAULT_EXCLUDE_PATTERNS` for directory scans.

**Dependencies**: None (modifies an existing class).

**Test approach**: Unit test with a temporary directory containing 3 Python files. Call `walk_paths()` with a list of 2 of them. Assert that the returned graph contains exactly nodes for those 2 files and nothing from the third.

---

### F4.2: `BaselineManager.merge_nodes()` and `.scoped_save()` — Merge and Persist

**File**: `cobuilder/repomap/serena/baseline.py`

**What it does**: Takes an existing `RPGGraph` and a "scoped graph" produced by `walk_paths()`. Replaces nodes in the existing graph whose node IDs match nodes in the scoped graph. Appends any new nodes from the scoped graph. Returns the merged `RPGGraph`.

**Function signatures**:

```python
def merge_nodes(
    self,
    existing: RPGGraph,
    scoped: RPGGraph,
) -> RPGGraph:
    """Merge scoped graph nodes into an existing baseline graph.

    Nodes in `scoped` replace nodes with the same ID in `existing`.
    Nodes in `scoped` with IDs not present in `existing` are appended.
    Nodes in `existing` with IDs not present in `scoped` are kept unchanged.

    Args:
        existing: The full baseline RPGGraph.
        scoped: A partial RPGGraph from walk_paths().

    Returns:
        New RPGGraph with merged nodes. The original graphs are not mutated.
    """

def scoped_save(
    self,
    repo_name: str,
    scoped: RPGGraph,
    *,
    project_root: Path,
    repomap_dir: Path,
) -> dict[str, Any]:
    """Load existing baseline, merge scoped nodes, rotate, and save.

    Implements the atomic refresh operation:
    1. Load baseline.json → RPGGraph
    2. merge_nodes(existing, scoped) → merged
    3. Rotate: baseline.json → baseline.prev.json
    4. Save merged → baseline.json
    5. Update manifest YAML
    6. Return updated config entry

    Args:
        repo_name: The repo name in .repomap/config.yaml.
        scoped: The partial graph from walk_paths().
        project_root: Root directory containing .repomap/.
        repomap_dir: The .repomap/ directory path.

    Returns:
        Updated config entry dict (same shape as sync_baseline returns).
    """
```

**Implementation notes for `merge_nodes()`**:
- `RPGGraph.nodes` is a `dict[str, RPGNode]` keyed by node ID.
- Build the merged dict: start with `dict(existing.nodes)`, then update with all entries from `scoped.nodes`. Python's dict update semantics handle both replace and append automatically.
- Copy `existing.edges` as the starting edge set. Edges from `scoped` are added without deduplication (scoped graphs from single files rarely carry cross-file edges; if they do, the duplicates are harmless for context injection purposes).
- Preserve `existing.metadata` except `baseline_generated_at` (which is updated to now) and `baseline_version`.

**Implementation notes for `scoped_save()`**:
- Use `BaselineManager.load()` to read the existing baseline (already implemented).
- If no baseline exists yet (fresh repo), treat `existing` as an empty `RPGGraph`.
- The rotation logic (rename `baseline.json` to `baseline.prev.json`) already exists in `sync_baseline()` in `bridge.py`. Extract it into a shared helper or duplicate it here.

**Dependencies**: F4.1 (`walk_paths()` produces the `scoped` argument).

**Test approach**: Unit test with a small RPGGraph (5 nodes). Create a scoped graph with 2 nodes: one matching an existing ID, one new. Assert the merge produces 6 nodes total (4 unchanged + 1 replaced + 1 new) and the replaced node has the scoped graph's version of the node.

---

### F4.3: `bridge.scoped_refresh()` — Orchestration Layer

**File**: `cobuilder/bridge.py`

**What it does**: The public-facing function that callers (the transition hook and spawn_orchestrator cleanup) use. Looks up the repo entry in `.repomap/config.yaml` to get `target_dir`, calls `walk_paths()` to scan the scope, calls `BaselineManager.scoped_save()` to merge and persist, updates `config.yaml` with the new `last_synced` timestamp, and returns a result dict.

**Function signature**:

```python
def scoped_refresh(
    name: str,
    scope: list[str],
    *,
    project_root: Path | str = Path("."),
) -> dict[str, Any]:
    """Re-scan only the specified files/folders and merge into the existing baseline.

    Unlike sync_baseline() which re-scans the entire repository, this
    function restricts the walk to the paths in `scope`. Designed for
    post-validation hooks where only a subset of files changed.

    Args:
        name: Repository name (must be registered in .repomap/config.yaml).
        scope: List of relative file or directory paths to re-scan.
               Paths are relative to the repo's target_dir.
        project_root: Root of the project that owns .repomap/.

    Returns:
        Dict with keys:
            - refreshed_nodes (int): Number of nodes updated or added.
            - duration_seconds (float): Wall-clock time of the refresh.
            - baseline_hash (str): New SHA-256 fingerprint.
            - skipped (bool): True if debounce threshold prevented refresh.

    Raises:
        KeyError: If `name` is not registered.
        FileNotFoundError: If the repo target_dir no longer exists.
    """
```

**Debounce implementation**:

```python
_REFRESH_DEBOUNCE_SECONDS = 30.0
_last_refresh_times: dict[str, float] = {}  # repo_name → epoch timestamp

# At top of scoped_refresh():
import time
now = time.monotonic()
if now - _last_refresh_times.get(name, 0.0) < _REFRESH_DEBOUNCE_SECONDS:
    logger.debug("scoped_refresh debounced for '%s' (ran within %ss)", name, _REFRESH_DEBOUNCE_SECONDS)
    return {"skipped": True, "refreshed_nodes": 0, "duration_seconds": 0.0, "baseline_hash": ""}
_last_refresh_times[name] = now
```

Note: `_last_refresh_times` is a module-level dict. It is reset when the process restarts. This is intentional — a new process should always be allowed to refresh. For the transition hook (which runs in a subprocess via the CLI), this means each invocation starts fresh and the debounce only fires if multiple nodes validate within 30 seconds of each other in the same process.

**CLI wiring**: Add `refresh` as a subcommand to the `repomap` group in `cobuilder/cli.py`:

```python
@repomap_app.command()
def refresh(
    name: str = typer.Argument(..., help="Repo name registered in .repomap/config.yaml"),
    scope: list[str] = typer.Option([], "--scope", "-s", help="File or folder paths to re-scan (repeatable)"),
    all_files: bool = typer.Option(False, "--all", help="Re-scan the entire repository (alias for sync)"),
) -> None:
    """Refresh the baseline for specific files/folders only.

    Use after node validation to update the baseline without a full rescan.

    Example:
        cobuilder repomap refresh --name my-project --scope cobuilder/bridge.py --scope cobuilder/pipeline/
    """
```

**Dependencies**: F4.1 (`walk_paths()`), F4.2 (`scoped_save()`).

**Test approach**: Integration test using an actual temp directory with Python files. Register the repo, run `scoped_refresh` on one file, assert `last_synced` updated in `config.yaml`, assert `refreshed_nodes` > 0, assert runtime < 10 seconds.

---

### F4.4: `_fire_post_validated_hook()` in `transition.py`

**File**: `cobuilder/pipeline/transition.py`

**What it does**: A function called inside `_cmd_transition()` immediately after the JSONL log entry is written and before the function returns. It reads the node's `file_path` or `folder_path` attribute from the (now-updated) DOT file, reads the graph-level `repo_name` attribute, and calls `bridge.scoped_refresh()`.

The hook is designed to be **non-blocking and non-fatal**. If the refresh fails for any reason (bridge not importable, repo not registered, network issue), it logs the error and returns without raising. The transition has already succeeded at this point — a baseline refresh failure must never cause a transition to appear to fail.

**Function signature**:

```python
def _fire_post_validated_hook(
    dot_file: str,
    node_id: str,
    updated_content: str,
    *,
    project_root: str | None = None,
) -> bool:
    """Fire post-validation baseline refresh for a node that just reached 'validated'.

    Reads file_path/folder_path and repo_name from the updated DOT content.
    Calls bridge.scoped_refresh() with the node's file scope.

    Args:
        dot_file: Path to the .dot pipeline file (used for project_root inference).
        node_id: The node ID that just reached 'validated'.
        updated_content: The DOT file content after the transition was applied.
        project_root: Optional explicit project root. If None, inferred by walking
                      up from dot_file until .repomap/ is found.

    Returns:
        True if refresh succeeded, False if skipped or failed (non-fatal).
    """
```

**Where it is called in `_cmd_transition()`**:

```python
def _cmd_transition(args: argparse.Namespace, content: str) -> None:
    """Handle the 'transition' sub-command (or legacy positional mode)."""
    # ... (existing code up to the file write) ...

    if not dry_run:
        with _dot_file_lock(args.file):
            with open(args.file, "w") as f:
                f.write(updated)

            # JSONL transition log (existing)
            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            _append_transition_jsonl(args.file, {...})

            # AC-3: finalize signal file (existing)
            _sig = _write_finalize_signal(...)

        # NEW: post-validated baseline refresh hook
        if args.new_status == "validated":
            _fire_post_validated_hook(
                dot_file=args.file,
                node_id=args.node_id,
                updated_content=updated,
            )
```

**Node attribute extraction**:

The DOT content is already parsed by `apply_transition()` before the hook fires. Rather than re-parsing, pass the `updated_content` string and re-use the existing `parse_dot()` function:

```python
def _extract_node_scope(dot_content: str, node_id: str) -> list[str]:
    """Extract file_path or folder_path from a node's attributes.

    Returns a list of paths (split on commas). Returns empty list if
    neither attribute is set.
    """
    from .parser import parse_dot
    data = parse_dot(dot_content)
    for node in data["nodes"]:
        if node["id"] == node_id:
            attrs = node["attrs"]
            raw = attrs.get("file_path") or attrs.get("folder_path") or ""
            if not raw:
                return []
            return [p.strip() for p in raw.split(",") if p.strip()]
    return []


def _extract_graph_repo_name(dot_content: str) -> str | None:
    """Extract the repo_name graph-level attribute from DOT content."""
    # Graph attributes appear as: graph [ repo_name="..." ]
    import re
    m = re.search(r'graph\s*\[([^\]]+)\]', dot_content, re.DOTALL)
    if not m:
        return None
    attrs_block = m.group(1)
    name_m = re.search(r'repo_name\s*=\s*"([^"]+)"', attrs_block)
    return name_m.group(1) if name_m else None
```

**Project root inference**:

When `project_root` is not supplied, the hook walks up from the dot file's directory until it finds a `.repomap/` directory or exhausts the path. This handles the common case where the dot file is in `.claude/attractor/pipelines/` and the project root is three levels up.

```python
def _infer_project_root(dot_file: str) -> Path | None:
    """Walk up from dot_file directory until .repomap/ is found."""
    current = Path(dot_file).resolve().parent
    for _ in range(8):  # max 8 levels up
        if (current / ".repomap").is_dir():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None
```

**Dependencies**: F4.3 (`bridge.scoped_refresh()`).

**Test approach**: Create a minimal DOT file with a node carrying `file_path="cobuilder/bridge.py"` and graph attribute `repo_name="test-repo"`. Register "test-repo" in a temp `.repomap/`. Call `_fire_post_validated_hook()`. Assert that `scoped_refresh()` was called (via mock or by checking the manifest `last_synced` updated). Assert the function returns `True`.

---

### F4.5: `cleanup_orchestrator()` and `--on-cleanup` in `spawn_orchestrator.py`

**File**: `cobuilder/orchestration/spawn_orchestrator.py`

**What it does**: Adds a cleanup step that fires `bridge.scoped_refresh()` for all files changed during the orchestrator session. This catches any files whose nodes lacked `file_path` attributes (and therefore missed the per-node hook) and provides a final reconciliation pass before the worktree is merged.

**New function**:

```python
def cleanup_orchestrator(
    session_name: str,
    repo_name: str,
    work_dir: str,
    *,
    project_root: str | None = None,
) -> dict:
    """Run post-completion cleanup for an orchestrator session.

    Discovers files changed during the session via git, refreshes the
    RepoMap baseline for those files, and returns a summary.

    Args:
        session_name: The tmux session name (for logging).
        repo_name: The repo name in .repomap/config.yaml.
        work_dir: The orchestrator's working directory (worktree root).
        project_root: Optional explicit project root for .repomap/ location.
                      Defaults to work_dir.

    Returns:
        Dict with: changed_files (list), refreshed_nodes (int), duration_seconds (float)
    """
    _project_root = Path(project_root or work_dir)

    # Get files changed by this orchestrator session
    try:
        result = subprocess.run(
            ["git", "-C", work_dir, "diff", "--name-only", "HEAD~10..HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        changed_files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except subprocess.SubprocessError as exc:
        logger.warning("cleanup_orchestrator: git diff failed: %s", exc)
        changed_files = []

    if not changed_files:
        logger.info("cleanup_orchestrator[%s]: no changed files detected", session_name)
        return {"changed_files": [], "refreshed_nodes": 0, "duration_seconds": 0.0}

    # Refresh baseline for changed files
    try:
        from cobuilder.bridge import scoped_refresh
        refresh_result = scoped_refresh(
            name=repo_name,
            scope=changed_files,
            project_root=_project_root,
        )
        logger.info(
            "cleanup_orchestrator[%s]: refreshed %d nodes in %.1fs",
            session_name,
            refresh_result.get("refreshed_nodes", 0),
            refresh_result.get("duration_seconds", 0.0),
        )
        return {
            "changed_files": changed_files,
            **refresh_result,
        }
    except Exception as exc:
        logger.error("cleanup_orchestrator[%s]: refresh failed: %s", session_name, exc)
        return {"changed_files": changed_files, "refreshed_nodes": 0, "error": str(exc)}
```

**CLI integration**: Add `--on-cleanup` flag to `spawn_orchestrator.py main()` that, when set, runs `cleanup_orchestrator()` instead of the normal spawn flow. This allows the guardian to call:

```bash
python spawn_orchestrator.py \
    --node epic1-node1 \
    --prd PRD-COBUILDER-001 \
    --repo-root /path/to/repo \
    --on-cleanup \
    --repo-name claude-harness-setup
```

This enables cleanup to be invoked explicitly by the guardian after detecting an orchestrator has completed (via the finalize signal file).

**Promise AC injection**: After the completion promise is created (the existing `cs-promise --create` call in guardian/s3 sessions), `spawn_orchestrator.py` injects the baseline freshness criterion:

```python
# After promise creation in main():
if args.promise_id:
    subprocess.run([
        "cs-promise", "--add-ac", args.promise_id,
        "RepoMap baseline refreshed for all validated nodes (scoped_refresh called after each validated transition)"
    ], check=False)  # Non-fatal: promise exists without this AC if cs-promise fails
```

The `--promise-id` flag is added as an optional argument to `spawn_orchestrator.py`.

**Dependencies**: F4.3 (`bridge.scoped_refresh()`).

**Test approach**: Mock `subprocess.run` to return a fixed `git diff` output. Mock `bridge.scoped_refresh`. Call `cleanup_orchestrator()`. Assert `scoped_refresh` was called with the correct scope list.

---

### F4.6: `cs-verify` Baseline Freshness Check

**File**: `.claude/scripts/completion-state/cs-verify` (bash script)

**What it does**: Adds a check inside `cs-verify --check` mode that compares the timestamp of the last "validated" transition in the pipeline's JSONL log against the `last_synced` timestamp in `.repomap/config.yaml`.

**Where it is inserted**: After the existing AC status iteration loop in the `if [ "$CHECK_MODE" = true ]` block, before the final exit decision. The check is advisory by default (produces a WARNING) and blocking when the `COBUILDER_ENFORCE_FRESHNESS=1` environment variable is set.

**Implementation** (bash):

```bash
# --- RepoMap freshness check (Epic 4) ---
check_repomap_freshness() {
    local pipeline_dot="${COBUILDER_PIPELINE_DOT:-}"
    local repo_name="${COBUILDER_REPO_NAME:-}"

    # Skip if pipeline or repo not configured
    if [ -z "$pipeline_dot" ] || [ -z "$repo_name" ]; then
        return 0
    fi

    local transitions_file="${pipeline_dot}.transitions.jsonl"
    if [ ! -f "$transitions_file" ]; then
        return 0  # No transitions yet, nothing to check
    fi

    # Find last validated transition timestamp
    local last_validated
    last_validated=$(grep '"new_status": "validated"' "$transitions_file" 2>/dev/null | \
        tail -1 | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); print(d.get("timestamp",""))' 2>/dev/null)

    if [ -z "$last_validated" ]; then
        return 0  # No validated transitions yet
    fi

    # Find baseline last_synced
    local config_file="${CLAUDE_PROJECT_DIR:-$(pwd)}/.repomap/config.yaml"
    if [ ! -f "$config_file" ]; then
        return 0  # No .repomap/ — not enforcing
    fi

    local last_synced
    last_synced=$(python3 -c "
import yaml, sys
with open('$config_file') as f:
    cfg = yaml.safe_load(f)
for repo in cfg.get('repos', []):
    if repo.get('name') == '$repo_name':
        print(repo.get('last_synced', ''))
        break
" 2>/dev/null)

    if [ -z "$last_synced" ]; then
        echo "WARNING: RepoMap baseline for '$repo_name' has never been synced" >&2
        return 0
    fi

    # Compare timestamps (ISO 8601 strings sort lexicographically)
    if [[ "$last_synced" < "$last_validated" ]]; then
        echo "REPOMAP_FRESHNESS_CHECK: STALE" >&2
        echo "  Last node validated:  $last_validated" >&2
        echo "  Baseline last synced: $last_synced" >&2
        echo "  Run: cobuilder repomap refresh --name $repo_name" >&2
        if [ "${COBUILDER_ENFORCE_FRESHNESS:-0}" = "1" ]; then
            return 1  # Blocking
        fi
    else
        if [ "$VERBOSE" = true ]; then
            echo "REPOMAP_FRESHNESS_CHECK: OK (synced $last_synced after validated $last_validated)"
        fi
    fi
    return 0
}

# Call inside --check mode, after existing AC loops:
if ! check_repomap_freshness; then
    IN_PROGRESS_COUNT=$((IN_PROGRESS_COUNT + 1))
fi
```

**Environment variables**:

| Variable | Default | Purpose |
|----------|---------|---------|
| `COBUILDER_PIPELINE_DOT` | (empty) | Path to the pipeline .dot file |
| `COBUILDER_REPO_NAME` | (empty) | Repo name in .repomap/config.yaml |
| `COBUILDER_ENFORCE_FRESHNESS` | `0` | Set to `1` to make stale baseline block cs-verify |

These are set by the guardian when spawning orchestrators alongside `CLAUDE_SESSION_ID`.

**Dependencies**: F4.3 (must have been run at least once to produce a `last_synced` timestamp).

**Test approach**: Create a temp `.transitions.jsonl` with a "validated" entry at T+10. Create `.repomap/config.yaml` with `last_synced` at T+0. Set `COBUILDER_ENFORCE_FRESHNESS=1`. Assert `cs-verify --check` exits with code 2. Then update `last_synced` to T+20. Assert `cs-verify --check` exits with code 0.

---

### F4.7: cobuilder-guardian SKILL.md CoBuilder Command Reference

**File**: `.claude/skills/cobuilder-guardian/SKILL.md`

**What it does**: Adds a new subsection to Phase 2 (Orchestrator Spawning) documenting the CoBuilder commands that every orchestrator receives in its boot sequence.

**Where it is inserted**: After the existing "Spawning Pattern" block in Phase 2, before Phase 3. The new subsection is titled "CoBuilder Boot Sequence for Orchestrators".

**Content to add**:

```markdown
### CoBuilder Boot Sequence for Orchestrators

Every orchestrator session needs a functional RepoMap baseline before work begins.
Since `.repomap/` is committed to git and worktrees are full git checkouts, the
baseline is already present. The orchestrator only needs to verify it and know
the refresh commands for post-node-validation use.

Include these commands in the initial prompt sent to every orchestrator tmux session:

```
## CoBuilder Commands Available in This Session

# Verify baseline exists and is recent
cobuilder repomap status --name ${REPO_NAME}

# After completing your work (automatic via post-validated hook, manual fallback):
cobuilder repomap refresh --name ${REPO_NAME} --scope <file1> --scope <file2>

# Full resync if you added many new files:
cobuilder repomap sync --name ${REPO_NAME}
```

Set these environment variables in the tmux session alongside CLAUDE_SESSION_ID:

```bash
export COBUILDER_REPO_NAME="${REPO_NAME}"
export COBUILDER_PIPELINE_DOT="${PIPELINE_DOT_PATH}"
export COBUILDER_ENFORCE_FRESHNESS=1
```

The post-validation hook in `transition.py` handles per-node refresh automatically.
Manual refresh is only needed if the hook missed files (nodes without `file_path`
attributes) or if the hook logged an error.

After the orchestrator completes, invoke cleanup explicitly:

```bash
python cobuilder/orchestration/spawn_orchestrator.py \
    --node ${NODE_ID} \
    --prd ${PRD_REF} \
    --repo-root ${REPO_ROOT} \
    --on-cleanup \
    --repo-name ${REPO_NAME}
```
```

**Dependencies**: None (documentation only).

**Test approach**: Manual verification — read the SKILL.md and confirm the section exists and the commands are syntactically correct.

---

## 4. Integration Points and Data Flow Detail

### How `transition.py` knows the project root

The DOT file path is always passed to `_cmd_transition()` as `args.file`. The project root is inferred by `_infer_project_root()` walking up until `.repomap/` is found. This works for the current directory structure:

```
$CLAUDE_PROJECT_DIR/  ← project root (.repomap/ here)
  .repomap/config.yaml
  .claude/attractor/pipelines/
    cobuilder-001.dot                                  ← dot_file (3 levels down)
```

`_infer_project_root(".claude/attractor/pipelines/cobuilder-001.dot")` will find `.repomap/` after 3 upward steps.

### How `repo_name` reaches the hook

Each DOT pipeline file must carry a graph-level attribute:

```dot
digraph cobuilder_001 {
    graph [
        repo_name="claude-harness-setup"
        prd_ref="PRD-COBUILDER-001"
    ]
    // ... nodes ...
}
```

The `generate.py` pipeline creator (Epic 2) is responsible for writing `repo_name` into the graph attributes when creating new pipelines. For existing pipelines created before Epic 4, `_extract_graph_repo_name()` returns `None` and the hook skips the refresh (logs a warning). This is graceful degradation — older pipelines simply do not trigger auto-refresh.

### How `scoped_refresh` handles relative vs absolute paths

The `scope` parameter accepts paths relative to `target_dir` (as stored in `.repomap/config.yaml`). The function resolves them against `target_dir`:

```python
target_dir = Path(entry["path"])  # from config.yaml
resolved_scope = [
    str((target_dir / p).resolve()) if not Path(p).is_absolute() else p
    for p in scope
]
```

The `file_path` attribute in DOT nodes is stored as a path relative to the repo root (e.g., `"cobuilder/bridge.py"`, not an absolute path). This matches the `scope` convention.

### Transition JSONL format (for cs-verify)

The existing JSONL entries look like:

```json
{"timestamp": "2026-02-27T10:30:00.000000+00:00", "file": "pipeline.dot", "command": "transition", "node_id": "n1", "new_status": "validated", "log": "[...] n1: impl_complete -> validated"}
```

The freshness check greps for `"new_status": "validated"` and reads the `timestamp` field. This format is stable (it is produced by the existing `_append_transition_jsonl()` call and has not changed across any Epic).

---

## 5. Dependencies

```
F4.1 (walk_paths)
  └── F4.2 (merge_nodes / scoped_save)
        └── F4.3 (bridge.scoped_refresh)
              ├── F4.4 (transition.py hook) ← uses scoped_refresh
              ├── F4.5 (spawn_orchestrator cleanup) ← uses scoped_refresh
              └── F4.6 (cs-verify check) ← reads config.yaml last_synced written by scoped_refresh

F4.7 (cobuilder-guardian SKILL.md) ← documentation only, no code dependencies
```

**External dependencies**:
- Epic 1 (F1.6): `bridge.py` must already exist with `_walk_codebase()`, `_save_config()`, `_load_config()`. **Confirmed present** — `bridge.py` exists with all these helpers.
- Epic 1 (F1.7): `cobuilder repomap` CLI subgroup must exist to wire the `refresh` command. **Confirmed present** — `cobuilder/cli.py` exists with `repomap_app` Typer group.
- The `repo_name` graph attribute in DOT files: populated by Epic 2's `generate.py`. For Epic 4 to work with existing DOT files that lack this attribute, the hook gracefully skips (no refresh but no error).

**Execution sequence**: F4.1 → F4.2 → F4.3 → (F4.4, F4.5, F4.6 in parallel) → F4.7.

---

## 6. Acceptance Criteria Per Feature

| Feature | AC | Criterion | Evidence Type | Blocking |
|---------|----|-----------|--------------|---------|
| F4.1 | AC-2a | `walk_paths(["cobuilder/bridge.py"])` returns graph with exactly 1 COMPONENT node | test | yes |
| F4.1 | AC-2b | `walk_paths()` on 10 files completes in <5 seconds | test | yes |
| F4.2 | AC-2c | `merge_nodes(existing=5_nodes, scoped=2_nodes)` returns 6 nodes (1 replaced, 1 new) | test | yes |
| F4.3 | AC-2d | `scoped_refresh("repo", ["file.py"])` updates `last_synced` in config.yaml | test | yes |
| F4.3 | AC-2e | Full scoped refresh (10 files) completes in <10 seconds | test | yes |
| F4.3 | AC-2f | Debounce: second call within 30s returns `{"skipped": True}` | test | yes |
| F4.4 | AC-1 | Transitioning node to `validated` (with `file_path` attr) triggers `scoped_refresh` | test | yes |
| F4.4 | — | Hook failure (import error) does not cause transition to fail | test | yes |
| F4.4 | — | Node without `file_path`/`folder_path` skips refresh with log warning | test | yes |
| F4.5 | AC-6 | `cleanup_orchestrator()` calls `scoped_refresh` for git-changed files | test | yes |
| F4.5 | — | `--on-cleanup` flag triggers cleanup path in spawn_orchestrator.py | test | yes |
| F4.6 | AC-4 | `cs-verify --check` with `COBUILDER_ENFORCE_FRESHNESS=1` blocks when baseline stale | test | yes |
| F4.6 | — | `cs-verify --check` passes when `last_synced` > last validated transition | test | yes |
| F4.7 | AC-5 | cobuilder-guardian SKILL.md contains "CoBuilder Boot Sequence for Orchestrators" section | manual | yes |
| — | AC-3 | `claude --worktree test-wt` produces worktree with `.repomap/` directory present | manual | yes |

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Scoped refresh exceeds 10-second SLA on large node scope (20+ files) | Medium | Medium | Conservative debounce; fall back to async subprocess if sync call exceeds 8 seconds. Log a warning and return `{"skipped": True, "reason": "timeout"}`. |
| `repo_name` absent in older DOT files (pre-Epic 2 pipelines) | High | Low | Hook skips with `logger.warning()`. No blocking behavior. Older pipelines degrade gracefully. |
| Baseline merge produces inconsistent node IDs if `walk_paths()` generates different IDs than `walk()` | Low | High | Use identical node ID generation code path in both methods. Unit test explicitly asserting round-trip stability. |
| `cs-verify` freshness check fires false positive when no nodes have been validated | Low | Medium | Check exits `return 0` if `last_validated` is empty — an empty JSONL or no validated entries means no check. |
| `git diff HEAD~10..HEAD` misses files changed more than 10 commits ago | Low | Low | Use `HEAD~50..HEAD` as the default range. The cost of a larger diff is negligible. Document that cleanup should run before branch diverges significantly. |
| Module-level `_last_refresh_times` dict not shared across subprocesses | Medium | Low | Each CLI invocation is a fresh process. Debounce only applies within a single process lifetime. This is acceptable — the 30-second window exists to prevent rapid sequential validations in the same process, not across processes. |
| `walk_paths()` called with paths that no longer exist (deleted files) | Low | Low | Log a warning and skip missing paths. The merge step will simply not update the node for that file. Deleted file nodes remain in the baseline until a full `repomap sync` runs. |

### Rollback Strategy

All five implementation files have clear pre-change states:

- `transition.py`: remove the `if args.new_status == "validated": _fire_post_validated_hook(...)` block and the three helper functions. The rest of the file is unmodified.
- `bridge.py`: remove `scoped_refresh()` and the debounce dict. The rest of the file is unmodified.
- `walker.py`: remove `walk_paths()`. The `walk()` method is unmodified.
- `baseline.py`: remove `merge_nodes()` and `scoped_save()`. The `save()` and `load()` methods are unmodified.
- `spawn_orchestrator.py`: remove `cleanup_orchestrator()` and the `--on-cleanup` flag.
- `cs-verify`: remove the `check_repomap_freshness()` function and its call site.

No database migrations, no schema changes, no API changes. Rollback is a git revert of the Epic 4 commits.

---

## 8. File Scope

### New Files

None. All implementation is in modifications to existing modules.

### Modified Files

| File | Change Description | Estimated LoC Added |
|------|--------------------|---------------------|
| `cobuilder/repomap/serena/walker.py` | Add `walk_paths()` method to `CodebaseWalker` | ~60 |
| `cobuilder/repomap/serena/baseline.py` | Add `merge_nodes()` and `scoped_save()` to `BaselineManager` | ~80 |
| `cobuilder/bridge.py` | Add `scoped_refresh()` function and `_last_refresh_times` debounce dict | ~75 |
| `cobuilder/pipeline/transition.py` | Add `_fire_post_validated_hook()`, `_extract_node_scope()`, `_extract_graph_repo_name()`, `_infer_project_root()`; call hook in `_cmd_transition()` | ~100 |
| `cobuilder/orchestration/spawn_orchestrator.py` | Add `cleanup_orchestrator()` function; add `--on-cleanup` and `--repo-name` CLI args; add `--promise-id` for AC injection | ~80 |
| `cobuilder/cli.py` | Add `refresh` subcommand to `repomap_app` | ~30 |
| `.claude/scripts/completion-state/cs-verify` | Add `check_repomap_freshness()` bash function and call site | ~50 lines bash |
| `.claude/skills/cobuilder-guardian/SKILL.md` | Add "CoBuilder Boot Sequence for Orchestrators" subsection in Phase 2 | ~40 lines markdown |

**Total**: ~515 lines of new code across 8 files.

### Test Files

| File | Test Coverage |
|------|--------------|
| `tests/test_walker.py` | `walk_paths()` unit tests (new test class) |
| `tests/test_baseline_manager.py` | `merge_nodes()` and `scoped_save()` unit tests |
| `tests/test_bridge.py` | `scoped_refresh()` integration tests |
| `tests/test_transition.py` | `_fire_post_validated_hook()` and helper function unit tests |
| `tests/test_spawn_orchestrator.py` | `cleanup_orchestrator()` unit tests with mocked subprocess |
| `tests/test_cs_verify.sh` | Bash integration tests for freshness check (new test file) |

---

## 9. Implementation Guidance for Workers

### Starting Point

Begin with F4.1. Every downstream feature depends on `walk_paths()`. A worker who completes F4.1 first unblocks all others.

### Completing F4.1 in Isolation

`walker.py` has no imports from `bridge.py` or `transition.py`. F4.1 can be implemented and tested entirely in isolation. The test does not require a real `.repomap/` directory.

### The Critical Test for F4.3

The 10-second SLA (AC-2) is the acceptance criterion most at risk. Before marking F4.3 complete, run:

```bash
time python -c "
from cobuilder.bridge import scoped_refresh
from pathlib import Path
result = scoped_refresh(
    'claude-harness-setup',
    ['cobuilder/bridge.py', 'cobuilder/pipeline/transition.py', 'cobuilder/repomap/serena/walker.py'],
    project_root=Path('.')
)
print(result)
"
```

This must complete in under 10 seconds on the local machine. If it does not, profile where the time is spent. The bottleneck is likely the AST parsing in `FileBasedCodebaseAnalyzer.analyze_file()` — if so, consider caching parsed ASTs by file mtime.

### Do Not Modify `apply_transition()`

`apply_transition()` is a pure string transformation function. It has no I/O side effects by design. All hook logic belongs in `_cmd_transition()`, which is the I/O boundary. Do not add the hook call inside `apply_transition()`.

### The Debounce Dict Is Not Thread-Safe

`_last_refresh_times` is a module-level dict. It is not protected by a lock. This is intentional — `transition.py` is invoked as a CLI subprocess, so each invocation is a separate process and there is no concurrency within a process. If the bridge is ever called from a multi-threaded context in the future, this will need a `threading.Lock`. For now, leave it as-is.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
