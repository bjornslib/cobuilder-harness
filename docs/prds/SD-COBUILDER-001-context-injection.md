---
title: "SD: Context Injection for Solution Design and Task Master"
prd_id: PRD-COBUILDER-001
epic: 3
status: active
type: architecture
created: 2026-02-27
last_verified: 2026-02-27
grade: authoritative
---

# SD-COBUILDER-001-E3: Context Injection for Solution Design and Task Master

## Executive Summary

Epic 3 is primarily a **wiring task**. Approximately 70% of the required code already exists and is tested. The core gap is a single missing call at `cobuilder/cli.py` line 60: `run_taskmaster_parse()` is invoked without passing `repomap_context`, even though `run_taskmaster_parse()` already accepts and processes that parameter. The remaining 30% is a skill documentation update and a verification pass to confirm that `--format sd-injection` is an alias (or that `--format yaml` is the correct flag to use) in the context command.

**Build estimate**: 2–4 hours of implementation, not 2–4 days. Workers should NOT redesign anything — the design is complete. They should wire, verify, and document.

---

## 1. Business Context

### Problem Statement

Solution Designs and Task Master currently operate without codebase awareness:

- The `solution-design-architect` writes technical specs based on the PRD and manual exploration, frequently inventing file paths that do not exist or missing modules that do.
- `task-master-ai parse-prd` decomposes tasks without knowing which files exist, what interfaces are available, or what delta status each module carries. Generated tasks reference ambiguous module names rather than precise file paths.

### Why This Matters

When TaskMaster lacks codebase context, orchestrators receive implementation work packages without file paths. Workers must spend their first turns exploring the codebase to find what to modify — wasting time and increasing the chance of touching the wrong file.

When the solution-design-architect lacks codebase context, SDs describe interfaces that do not match the actual code, requiring workers to reconcile discrepancies mid-implementation.

### Goals Served

| PRD Goal | Description | How Epic 3 Satisfies It |
|----------|-------------|------------------------|
| G1 | SDs receive codebase context automatically | RepoMap YAML injected into cobuilder-guardian Phase 0 prompt |
| G5 | Task Master receives codebase context | `repomap_context` wired through `cli.py` → `taskmaster_bridge.py` |

---

## 2. Technical Architecture

### End-to-End Data Flow

```
1. cobuilder repomap sync --name <repo>
       |
       v
   .repomap/baselines/<repo>/baseline.json  (RPGGraph as JSON)
   .repomap/manifests/<repo>.manifest.yaml  (summary stats)

2. cobuilder repomap context --name <repo> --prd <PRD-ID> --format yaml
       |
       v
   bridge.get_repomap_context()
       |
       +-- Loads manifest.yaml for stats
       +-- Calls context_filter.filter_relevant_modules() with prd_keywords
       |       (Strategy 1: direct file match, Strategy 2: dep expansion, Strategy 3: keyword)
       +-- Calls context_filter.extract_dependency_graph() for filtered modules
       |
       v
   YAML string (structured: repository, total_nodes, modules_relevant_to_epic,
                              dependency_graph, protected_files)

3A. cobuilder-guardian (Phase 0) injects YAML into solution-design-architect Task prompt
       |
       v
   solution-design-architect writes SD with accurate file paths and interfaces

3B. cobuilder pipeline create --sd SD-FILE.md --repo <repo> [Step 3/7]
       |
       v
   taskmaster_bridge.run_taskmaster_parse(sd_path, project_root, repomap_context=<yaml>)
       |
       +-- If repomap_context is non-empty: calls create_enriched_input(sd_path, context)
       |       → writes temp .md file: SD content + codebase context block
       |       → passes temp file path to npx task-master-ai parse-prd
       +-- Cleans up temp file in finally block
       |
       v
   .taskmaster/tasks/tasks.json  (tasks with file paths from RepoMap context)
```

### Key Insight: The Bridge Is Already Built

`taskmaster_bridge.py` contains the complete wiring logic. The function signature is:

```python
def run_taskmaster_parse(
    enriched_sd_path: str,
    project_root: str,
    repomap_context: str = "",   # <-- parameter exists, just not passed
) -> dict:
```

When `repomap_context` is provided, `create_enriched_input()` concatenates SD content with a structured codebase context block and writes it to a temp file. The temp file path is passed to `npx task-master-ai parse-prd --input <tmp>`. The temp file is cleaned up in the `finally` block. This entire path is implemented.

### Context YAML Format

The `get_repomap_context()` function in `bridge.py` produces this schema when `format="yaml"`:

```yaml
repository: agencheck
snapshot_date: "2026-02-27T10:00:00Z"
total_nodes: 3037
total_files: 312
total_functions: 1847

modules_relevant_to_epic:
  - name: cobuilder
    delta: MODIFIED
    files: 24
    summary: null          # populated by LLM enrichment (Epic 2, not Epic 3)
    key_interfaces:
      - signature: "get_repomap_context(name, *, project_root, max_modules, prd_keywords, ...)"
        file: cobuilder/bridge.py
        line: null

  - name: pipeline
    delta: MODIFIED
    files: 18
    summary: null
    key_interfaces:
      - signature: "run_taskmaster_parse(enriched_sd_path, project_root, repomap_context)"
        file: cobuilder/pipeline/taskmaster_bridge.py
        line: null

dependency_graph:
  - from: pipeline
    to: cobuilder
    type: depends
    description: ""
```

Note: `protected_files` is present in the YAML output only if the list is non-empty. The current implementation returns `{}` for `protected_files` (bridge.py line 401), which means the key is omitted from output (bridge.py line 445: `doc = {k: v for k, v in doc.items() if v is not None}`).

Note: The `--format sd-injection` flag mentioned in the PRD does not exist. The CLI supports `--format yaml` (default) and `--format text`. The Epic 3 acceptance criterion referencing `--format sd-injection` should be interpreted as `--format yaml` — that is the injection format. No new format needs to be added.

---

## 3. Current State Assessment

### Already Implemented and Working

| Component | File | Status | Evidence |
|-----------|------|--------|---------|
| Context command CLI | `cobuilder/repomap/cli/commands.py:143` | Complete | `context_cmd` accepts `--name`, `--prd`, `--prd-keywords`, `--sd-files`, `--format` |
| Context generation | `cobuilder/bridge.py:320` | Complete | `get_repomap_context()` generates YAML or text from manifest + baseline |
| Module relevance filter | `cobuilder/repomap/context_filter.py:161` | Complete | `filter_relevant_modules()` implements 3-strategy deterministic filtering |
| Dependency graph extraction | `cobuilder/repomap/context_filter.py:253` | Complete | `extract_dependency_graph()` extracts inter-module edges |
| TaskMaster bridge parameter | `cobuilder/pipeline/taskmaster_bridge.py:46` | Complete | `run_taskmaster_parse(enriched_sd_path, project_root, repomap_context="")` |
| SD enrichment in bridge | `cobuilder/pipeline/taskmaster_bridge.py:12` | Complete | `create_enriched_input()` concatenates SD + YAML context block with TaskMaster instructions |
| Temp file lifecycle | `cobuilder/pipeline/taskmaster_bridge.py:63-94` | Complete | Writes temp file, passes to subprocess, cleans up in `finally` |
| TaskMaster invocation | `cobuilder/pipeline/taskmaster_bridge.py:76-91` | Complete | `subprocess.run(["npx", "task-master-ai", "parse-prd", "--input", input_path, ...])` |

### The Single Gap: Missing Wire in `cli.py`

```python
# cobuilder/cli.py lines 56-61 — CURRENT STATE (broken)
if not skip_taskmaster:
    typer.echo("[3/7] Running TaskMaster parse...")
    taskmaster_tasks = run_taskmaster_parse(
        str(sd_path.resolve()),
        str(project_root.resolve())
        # MISSING: repomap_context=<yaml string>
    )
```

The `repomap_context` argument is never generated and never passed. The bridge parameter has a default of `""`, so the call succeeds but skips the enrichment path entirely.

### Secondary Gap: No Context Generation at Step 3

Even after the function parameter is wired, `cli.py` does not generate `repomap_context` before Step 3. The context must be generated using `get_repomap_context()` (already available in `bridge.py`) before `run_taskmaster_parse()` is called. The `repo` and `prd` variables are already present in scope.

### Tertiary Gap: SD Injection Documentation

The cobuilder-guardian SKILL.md mentions "Designs PRDs with CoBuilder RepoMap context (Phase 0)" in its diagram (SKILL.md line 16) but does not contain the actual commands or prompt template for injecting context. Phase 0 of the SKILL.md needs a concrete procedure.

### What Is NOT Missing

- No new Python modules needed
- No changes to `context_filter.py` — it is complete
- No changes to `bridge.py` — `get_repomap_context()` already produces the correct YAML
- No changes to `taskmaster_bridge.py` — `create_enriched_input()` and `run_taskmaster_parse()` are complete
- No new CLI flags needed — `--format yaml` is the correct flag (not `--format sd-injection`)
- No changes to `cobuilder/repomap/cli/commands.py` — the `context` command is complete

---

## 4. Functional Decomposition

### F3.1: Wire `repomap_context` Through `cli.py` (PRIMARY TASK)

**Status**: Not done. This is the critical gap.

**What the worker does**:

Modify `cobuilder/cli.py` in the `pipeline_create` function. After Step 2.5 (node filtering by SD relevance) and before Step 3 (TaskMaster parse), add a call to `get_repomap_context()` to produce the YAML string, then pass it to `run_taskmaster_parse()`.

**Exact location**: `cli.py`, the `pipeline_create` function, around line 56-63.

**Import to add** (at function scope, inside the existing import block for Step 3):

```python
from cobuilder.bridge import get_repomap_context
```

**Code change** — replace the existing Step 3 block with:

```python
# Step 3: TaskMaster parse (with RepoMap context)
taskmaster_tasks = {}
if not skip_taskmaster:
    typer.echo("[3/7] Running TaskMaster parse...")
    # Generate RepoMap context YAML for TaskMaster enrichment
    repomap_context = ""
    try:
        prd_kws = [w.lower() for w in prd.replace("-", " ").split() if w and not w.isdigit()] if prd else []
        repomap_context = get_repomap_context(
            repo,
            project_root=project_root,
            prd_keywords=prd_kws or None,
        )
        typer.echo(f"      RepoMap context: {len(repomap_context)} chars")
    except (KeyError, FileNotFoundError) as exc:
        typer.echo(f"      Warning: RepoMap context unavailable ({exc}) — proceeding without")
    taskmaster_tasks = run_taskmaster_parse(
        str(sd_path.resolve()),
        str(project_root.resolve()),
        repomap_context=repomap_context,
    )
else:
    typer.echo("[3/7] Skipping TaskMaster parse (--skip-taskmaster)")
```

**Error handling rationale**: `get_repomap_context()` raises `KeyError` if the repo is not registered and `FileNotFoundError` if no manifest exists. Both are recoverable — the pipeline can still run without context. Log a warning and proceed with `repomap_context=""`, which causes `run_taskmaster_parse()` to use the SD file directly (existing behaviour).

**Dependencies**: None — all imports already exist in the module or are available.

**Files touched**: `cobuilder/cli.py` only.

**Estimated change size**: ~12 lines added, 3 lines modified.

---

### F3.2: Verify `--format yaml` Is the Correct Injection Format

**Status**: Needs verification pass, not implementation.

The PRD acceptance criterion references `--format sd-injection`. Examination of `cobuilder/repomap/cli/commands.py:165` confirms the CLI supports `--format yaml` (default) and `--format text`. There is no `sd-injection` format.

**What the worker does**:

1. Run `cobuilder repomap context --name <any-registered-repo> --format yaml` and confirm output contains `repository`, `total_nodes`, `modules_relevant_to_epic`.
2. Confirm the output is valid YAML by parsing it with `yaml.safe_load()`.
3. If `sd-injection` is explicitly required by downstream consumers, add it as an alias in `bridge.py` `get_repomap_context()` (mapping `sd-injection` → `yaml` format path). This is a 2-line change.
4. Update the PRD acceptance criteria comment in this SD to reflect the actual flag name.

**Recommendation**: Do NOT add a new format. Document that `--format yaml` is the correct SD injection format. This avoids dead code and keeps the CLI surface small.

**Files touched**: None if no alias added. `cobuilder/bridge.py:354` if alias added (1-line change in format validation).

---

### F3.3: Update cobuilder-guardian SKILL.md Phase 0

**Status**: Partially documented. The diagram references it; the procedure is absent.

**What the worker does**:

Add a "Phase 0: Codebase Context Injection" section to `.claude/skills/cobuilder-guardian/SKILL.md` between the diagram and the "Guardian Disposition" section. The section must contain:

1. A concrete bash command showing how to generate RepoMap context.
2. A prompt template for injecting context into the `solution-design-architect` Task call.
3. Instructions for when to skip context injection (repo not yet synced, first-time setup).

**Phase 0 section content**:

```markdown
## Phase 0: Codebase Context Injection (Before SD Creation)

Before delegating SD authoring, generate RepoMap context for the target repo.
This gives the solution-design-architect accurate file paths, delta status,
and key interfaces — eliminating invented paths and wrong module names.

### Step 0.1: Generate Context

```bash
# Ensure repo is registered and synced
cobuilder repomap status

# Generate context YAML (adjust --name to the target repo)
cobuilder repomap context \
  --name <repo-name> \
  --prd <PRD-ID> \
  --format yaml \
  > /tmp/repomap-context.yaml

cat /tmp/repomap-context.yaml
```

If the repo is not yet registered:
```bash
cobuilder repomap init <repo-name> --target-dir /path/to/repo
cobuilder repomap sync <repo-name>
```

### Step 0.2: Inject Into SD Creation Task

```python
import subprocess

context_yaml = subprocess.run(
    ["cobuilder", "repomap", "context",
     "--name", repo_name,
     "--prd", prd_id,
     "--format", "yaml"],
    capture_output=True, text=True
).stdout

Task(
    subagent_type="solution-design-architect",
    prompt=f"""
Create a Solution Design for Epic {epic_num} of {prd_id}.

## PRD Reference
Read: {prd_path}
Focus on: Section {epic_section}

## Codebase Context (RepoMap — read this before designing)

```yaml
{context_yaml}
```

Instructions for using this context:
- EXISTING modules: reference their actual file paths; do not redesign them
- MODIFIED modules: scope changes to specific files listed; use key_interfaces for signatures
- NEW modules: design using suggested_structure from RepoMap
- protected_files: treat as read-only unless the PRD explicitly requires changes
- dependency_graph: respect dependency order in your implementation phases
"""
)
```

### When To Skip Context Injection

Skip Phase 0 if:
- No baseline exists for the target repo (first-time setup, no `cobuilder repomap sync` run yet)
- The PRD is for a greenfield repo with no existing code
- The `cobuilder repomap context` command returns an error

In these cases, proceed directly to Phase 1 and note in the SD that RepoMap context was unavailable.
```

**Files touched**: `.claude/skills/cobuilder-guardian/SKILL.md` only.

**Dependencies**: F3.1 must be complete (and ideally verified working) before this documentation is finalized, to ensure the command examples are accurate.

---

### F3.4: Validate End-to-End: TaskMaster Tasks Include File Paths

**Status**: Validation task (not implementation). Cannot be done until F3.1 is complete.

**What the worker does**:

After F3.1 is merged, run `cobuilder pipeline create` against a test SD and a registered repo, then inspect `.taskmaster/tasks/tasks.json` to confirm:

1. Tasks reference specific file paths (e.g., `cobuilder/cli.py`, `cobuilder/bridge.py`) rather than generic module names.
2. Tasks for EXISTING modules are scoped as reference/test tasks, not full implementation tasks.
3. Tasks for NEW or MODIFIED modules carry explicit file paths from the RepoMap context block.

**Validation command**:

```bash
# Run pipeline create with a known SD and registered repo
cobuilder pipeline create \
  --sd docs/prds/SD-COBUILDER-001-context-injection.md \
  --repo claude-harness-setup \
  --prd PRD-COBUILDER-001 \
  --skip-enrichment

# Inspect TaskMaster output
cat .taskmaster/tasks/tasks.json | python3 -c "
import json, sys
tasks = json.load(sys.stdin).get('tasks', [])
for t in tasks:
    print(t['id'], t.get('title', ''))
    for f in t.get('details', '').split('\n'):
        if '.py' in f or '.md' in f:
            print('  ', f.strip())
"
```

**Acceptance**: At least one task must reference a `.py` file path. If all tasks are generic ("Implement context injection", "Update bridge"), the wiring is not working correctly.

**Files touched**: None. This is a validation-only task.

---

## 5. Data Models

### RepoMap Context YAML Schema

Produced by `bridge.get_repomap_context(name, format="yaml")`.

```yaml
# Top-level stats (always present)
repository: string                    # repo name from .repomap/config.yaml
snapshot_date: string                 # ISO 8601 UTC datetime of last sync
total_nodes: integer                  # all nodes in baseline graph
total_files: integer                  # COMPONENT-level nodes (file-level)
total_functions: integer              # FEATURE-level nodes (function-level)

# Filtered module inventory (present only when prd_keywords or sd_file_references provided)
modules_relevant_to_epic:             # list[dict], max max_modules entries
  - name: string                      # top-level folder segment (e.g. "cobuilder")
    delta: string                     # "NEW" | "MODIFIED" | "existing"
    files: integer                    # count of COMPONENT nodes in module
    summary: null | string            # narrative summary (null in Epic 3; populated by LLM enrichment in Epic 2)
    key_interfaces:                   # list[dict], max 5 per module
      - signature: string             # function signature string
        file: string                  # file path relative to repo root
        line: null | integer          # line number (null when not available)

# Dependency graph (present when baseline available and modules filtered)
dependency_graph:                     # list[dict]
  - from: string                      # source module name
    to: string                        # target module name
    type: string                      # always "depends" in current implementation
    description: string               # edge transformation/data_type field (may be empty)

# Protected files (present only when non-empty; currently always absent — not yet populated)
protected_files:                      # list[dict]
  - path: string                      # file path relative to repo root
    reason: string                    # human-readable explanation
```

### TaskMaster Enriched Input Schema

Produced by `taskmaster_bridge.create_enriched_input(sd_path, repomap_context)`.

```markdown
{sd_content}

---

## Codebase Context (Auto-Generated by CoBuilder RepoMap)

```yaml
{repomap_context_yaml}
```

IMPORTANT for task decomposition:
- EXISTING modules: DO NOT create implementation tasks. Reference only.
- MODIFIED modules: Create scoped modification tasks with exact file paths from context.
- NEW modules: Create full implementation tasks using suggested_structure paths.
- Use dependency_graph to order tasks correctly.
- Use key_interfaces for accurate function signatures in task descriptions.
```

The temp file containing this content is written to `tempfile.NamedTemporaryFile(mode="w", suffix=".md")` and deleted in the `finally` block of `run_taskmaster_parse()`.

---

## 6. Acceptance Criteria Per Feature

### F3.1: Wire `repomap_context` Through `cli.py`

| # | Criterion | Verification Method |
|---|-----------|---------------------|
| AC-3.1.1 | `cobuilder pipeline create --sd <sd> --repo <repo> --prd <prd>` runs to completion without error when repo is registered and synced | Manual run, check exit code 0 |
| AC-3.1.2 | Step 3/7 output includes `RepoMap context: N chars` where N > 0 when repo is registered | Inspect stdout |
| AC-3.1.3 | Step 3/7 outputs warning and continues (exit code 0) when repo is not registered | Manual run with unregistered repo name |
| AC-3.1.4 | `run_taskmaster_parse()` is called with non-empty `repomap_context` when repo is registered | Add debug log or test mock |
| AC-3.1.5 | Temp file is removed after subprocess call (no files left in `/tmp` with `.md` suffix from cobuilder) | Check `/tmp` before/after |

### F3.2: Verify `--format yaml` Is the Correct Injection Format

| # | Criterion | Verification Method |
|---|-----------|---------------------|
| AC-3.2.1 | `cobuilder repomap context --name <repo> --format yaml` exits with code 0 | Manual run |
| AC-3.2.2 | Output parses as valid YAML | `python3 -c "import yaml,sys; yaml.safe_load(sys.stdin)"` |
| AC-3.2.3 | Output contains keys: `repository`, `total_nodes`, `total_files` | YAML parse + key check |
| AC-3.2.4 | When `--prd` is provided, output contains `modules_relevant_to_epic` with at least one entry | Manual run with valid PRD keyword |

### F3.3: cobuilder-guardian SKILL.md Phase 0

| # | Criterion | Verification Method |
|---|-----------|---------------------|
| AC-3.3.1 | SKILL.md contains a "Phase 0" section before "Phase 1" | Grep for `## Phase 0` |
| AC-3.3.2 | Phase 0 contains a bash command block with `cobuilder repomap context` | Read SKILL.md, verify command block |
| AC-3.3.3 | Phase 0 contains a Task() call example with context YAML injected into prompt | Read SKILL.md, verify Task block |
| AC-3.3.4 | Phase 0 documents when to skip (no baseline, greenfield, error) | Read SKILL.md, verify skip conditions |

### F3.4: TaskMaster Tasks Include File Paths

| # | Criterion | Verification Method |
|---|-----------|---------------------|
| AC-3.4.1 | `.taskmaster/tasks/tasks.json` is produced after `cobuilder pipeline create` | Check file exists |
| AC-3.4.2 | At least one task in `tasks.json` references a `.py` file path from the RepoMap context | Parse JSON, search for `.py` |
| AC-3.4.3 | No task is created for EXISTING modules that the context marks as reference-only | Parse JSON, check against module delta status |

---

## 7. Risk Assessment

| Risk | Severity | Probability | Mitigation |
|------|----------|-------------|------------|
| `get_repomap_context()` raises because repo not synced | Low | Medium | F3.1 wraps call in try/except; pipeline proceeds without context |
| Context YAML too large for TaskMaster context window | Medium | Low | `max_modules` defaults to 10; worst case ~2KB YAML; TaskMaster accepts files up to model context limit |
| Keyword extraction from PRD ID is too coarse (e.g. "PRD-COBUILDER-001" → ["cobuilder"]) | Low | Medium | PRD keywords from `--prd` flag supplement with `--prd-keywords` if needed; coarse match is better than no match |
| `--format sd-injection` is hardcoded somewhere in downstream tooling | Medium | Low | Audit grep across codebase before shipping; add alias if found |
| Protected files list is always empty (bridge.py line 401) | Low | High | Known limitation documented; Epic 4 will add protected file detection from git history |
| Task matching in `extract_task_ids_for_node()` uses 40% word overlap (may miss) | Low | Medium | Matching is best-effort; DOT nodes still carry accurate file_path from other enrichers |
| cobuilder-guardian SKILL.md update breaks existing Phase 0 workflow | Low | Low | Phase 0 is currently undocumented; addition cannot break what doesn't exist |

---

## 8. File Scope

### Files That Workers Modify

| File | Change Type | Size | Notes |
|------|-------------|------|-------|
| `cobuilder/cli.py` | Modify | ~12 lines added, 3 modified | F3.1: wire `repomap_context` into Step 3 of `pipeline_create` |
| `.claude/skills/cobuilder-guardian/SKILL.md` | Modify | ~60 lines added | F3.3: add Phase 0 section |

### Files That Workers Read (Reference Only — Do Not Modify)

| File | Purpose |
|------|---------|
| `cobuilder/pipeline/taskmaster_bridge.py` | Verify parameter signature, understand temp file lifecycle |
| `cobuilder/bridge.py` | Verify `get_repomap_context()` signature and return type |
| `cobuilder/repomap/cli/commands.py` | Verify `context_cmd` flags and format support |
| `cobuilder/repomap/context_filter.py` | Understand filtering algorithm (no changes needed) |
| `.repomap/config.yaml` | Verify repo is registered for E2E validation |

### Files That Workers Must NOT Modify

| File | Reason |
|------|--------|
| `cobuilder/pipeline/taskmaster_bridge.py` | Already complete; touching it risks breaking working code |
| `cobuilder/bridge.py` | Already complete; `get_repomap_context()` produces correct output |
| `cobuilder/repomap/context_filter.py` | Already complete; filtering algorithm is correct |
| `cobuilder/repomap/cli/commands.py` | Already complete; no new flags needed |

---

## 9. Implementation Sequence

Workers must execute tasks in this order. F3.4 depends on F3.1 being complete and verified.

```
F3.1 (cli.py wiring)
    |
    +-- F3.2 (format verification — can run in parallel with F3.1)
    |
    v
F3.4 (E2E validation — requires F3.1)
    |
    v
F3.3 (SKILL.md update — requires F3.4 to confirm commands work correctly)
```

F3.2 is a verification-only task and can be executed immediately alongside F3.1 since it requires no code changes.

---

## 10. Testing Strategy

### Unit Tests for F3.1

Add tests in `tests/test_pipeline_create.py` (or equivalent) to verify:

1. When `get_repomap_context()` returns a non-empty string, `run_taskmaster_parse()` is called with `repomap_context` matching that string.
2. When `get_repomap_context()` raises `KeyError`, `run_taskmaster_parse()` is called with `repomap_context=""`.
3. When `get_repomap_context()` raises `FileNotFoundError`, `run_taskmaster_parse()` is called with `repomap_context=""`.

Use `unittest.mock.patch` to mock both `get_repomap_context` and `run_taskmaster_parse`. No real subprocess calls needed in unit tests.

### Integration Test for F3.4

```bash
# Setup: ensure test repo is registered
cobuilder repomap init test-repo --target-dir $(pwd)
cobuilder repomap sync test-repo

# Run pipeline create with skip-enrichment to avoid LLM cost
cobuilder pipeline create \
  --sd docs/prds/SD-COBUILDER-001-context-injection.md \
  --repo test-repo \
  --prd PRD-COBUILDER-001 \
  --skip-enrichment \
  --output /tmp/test-pipeline.dot

# Assert: tasks.json was produced
test -f .taskmaster/tasks/tasks.json && echo PASS || echo FAIL

# Assert: at least one task references a .py file
python3 -c "
import json, sys
tasks = json.load(open('.taskmaster/tasks/tasks.json')).get('tasks', [])
has_file_ref = any('.py' in str(t) for t in tasks)
print('PASS' if has_file_ref else 'FAIL: no .py file references in tasks')
"
```

---

## Appendix A: Precise Function Signatures (From Source)

### `bridge.get_repomap_context()` (bridge.py:320)

```python
def get_repomap_context(
    name: str,
    *,
    project_root: Path | str = Path("."),
    max_modules: int = 10,
    prd_keywords: list[str] | None = None,
    sd_file_references: list[str] | None = None,
    format: str = "yaml",          # "yaml" or "text"
) -> str:
    """Return a repomap context string suitable for LLM injection.

    Raises:
        KeyError: If name is not registered.
        FileNotFoundError: If no manifest exists (sync first).
        ValueError: If format is not 'yaml' or 'text'.
    """
```

### `taskmaster_bridge.run_taskmaster_parse()` (taskmaster_bridge.py:46)

```python
def run_taskmaster_parse(
    enriched_sd_path: str,
    project_root: str,
    repomap_context: str = "",
) -> dict:
    """Call task-master-ai parse-prd via subprocess.

    Returns parsed tasks dict from .taskmaster/tasks/tasks.json.
    Returns {} on timeout or failure (logged, not raised).
    """
```

### `context_filter.filter_relevant_modules()` (context_filter.py:161)

```python
def filter_relevant_modules(
    baseline_path: Path,
    prd_keywords: list[str],
    sd_file_references: list[str],
    max_results: int = 15,
) -> list[dict]:
    """Filter RepoMap modules relevant to a PRD/SD — deterministic, no LLM.

    Returns list of module dicts with keys:
    name, delta, files, summary, key_interfaces
    """
```

---

## Appendix B: PRD Acceptance Criteria Mapping

The PRD (Section 6, Epic 3) lists 6 acceptance criteria. This SD maps them to features:

| PRD AC | Mapped Feature | Gap Status | Notes |
|--------|---------------|------------|-------|
| `cobuilder repomap context --name repo --prd PRD-ID --format sd-injection` produces YAML | F3.2 | Flag name correction needed | Use `--format yaml`; `sd-injection` does not exist |
| Context includes: repository name, total nodes/files, relevant modules with delta + interfaces, dependency graph, protected files | F3.2 | Partial | All fields except `protected_files` are produced; that list is always empty (known limitation) |
| Module filtering is deterministic (no LLM, keyword-based matching against PRD) | F3.2 | Complete | `context_filter.py` implements 3-strategy deterministic filter |
| cobuilder-guardian skill (SKILL.md) documents RepoMap context injection in Phase 0 | F3.3 | Not done | No Phase 0 section exists |
| TaskMaster tasks include file paths and delta classification from RepoMap context | F3.4 | Not done | Depends on F3.1 |
| Output is reproducible: same input → same output | F3.2 | Complete | Deterministic algorithm, no LLM, hash-stable baseline |

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
