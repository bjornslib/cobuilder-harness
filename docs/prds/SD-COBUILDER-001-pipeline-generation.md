---
title: "SD: RepoMap-Native Pipeline Generation with LLM Enrichment"
prd_id: PRD-COBUILDER-001
epic: "2"
status: active
type: architecture
created: 2026-02-27
last_verified: 2026-02-27
grade: authoritative
---

# SD-COBUILDER-001-E2: RepoMap-Native Pipeline Generation with LLM Enrichment

## Executive Summary

Epic 2 of PRD-COBUILDER-001 closes the final wiring gaps in the `cobuilder pipeline create` command. The 7-step pipeline skeleton exists in `cobuilder/cli.py` and all five LLM enrichers exist in `cobuilder/pipeline/enrichers/`. The problem is that three specific integration points are broken or incomplete, causing the command to produce pipelines that are less accurate and less useful than the code is capable of supporting.

The three gaps are:

1. **RepoMap context not reaching TaskMaster.** `cli.py` line 60 calls `run_taskmaster_parse(str(sd_path), ...)` without the `repomap_context` parameter, even though `taskmaster_bridge.py` fully supports it. TaskMaster therefore parses a bare SD with no codebase awareness and produces generic tasks instead of file-path-scoped tasks.

2. **Duplicate node IDs in DOT output.** When multiple RepoMap nodes share the same `label` string, `generate_pipeline_dot()` produces colliding DOT identifiers (`impl_<sanitized_title>`). The deduplication suffix appended at line 648 uses a raw UUID slice rather than a meaningful differentiator, which makes node IDs unreadable in dashboards.

3. **YAML parse failures in enrichers silently drop enrichment.** The `_sanitize_yaml()` function in `base.py` handles the most common LLM output errors (unquoted colons) but the 3-tier retry chain does not validate that required top-level keys are present after parsing. A response that parses successfully but returns `{}` or an empty list causes downstream enrichers (WorkerSelector, ComplexitySizer) to use defaults, degrading pipeline quality without any log warning at `INFO` level.

Fixing these three gaps — plus adding the `solution_design` attribute to every generated DOT node — satisfies all seven acceptance criteria from PRD-COBUILDER-001 Epic 2. Approximately 80% of the code for this epic already exists and is correct.

---

## Business Context

**Parent PRD**: PRD-COBUILDER-001, Epic 2
**Goals addressed**: G2 (Pipeline uses codebase graph as primary source), G5 (TaskMaster receives codebase context)

Before this epic is complete, `cobuilder pipeline create` operates as follows:

- It loads RepoMap nodes correctly (F2.1, F2.2 done)
- It filters nodes by SD relevance correctly (F2.2.5 done)
- It calls TaskMaster **without** RepoMap context (F2.5 broken — this SD)
- It runs all five LLM enrichers which broadly work but silently degrade on empty responses (F2.3 partial)
- It generates DOT with duplicate IDs for same-title nodes (F2.6 broken — this SD)
- It writes SD v2 enrichment blocks correctly (F2.7 done)
- The `solution_design` attribute exists at graph level but is not written per-node (F2.6 incomplete — this SD)

After this epic, orchestrators receive DOT pipelines where every node is uniquely addressable, carries the correct worker type determined by LLM reasoning over file paths, and the SD file has been enriched with TaskMaster task IDs sourced from a codebase-aware parse.

---

## Technical Architecture

### Component Map (What Exists vs. What Changes)

```
cobuilder/
├── cli.py                              MODIFY  — pass repomap_context to run_taskmaster_parse
├── bridge.py                           VERIFY  — get_repomap_context() already works; confirm call path
├── pipeline/
│   ├── generate.py                     MODIFY  — fix duplicate node ID collision; add per-node solution_design
│   ├── taskmaster_bridge.py            VERIFY  — run_taskmaster_parse() repomap_context param exists; no change
│   ├── sd_enricher.py                  VERIFY  — write_all_enrichments() works correctly; no change
│   └── enrichers/
│       ├── base.py                     MODIFY  — add empty-result warning at INFO level; log enricher name
│       ├── file_scoper.py              VERIFY  — correct; no change
│       ├── acceptance_crafter.py       VERIFY  — correct; no change
│       ├── dependency_inferrer.py      VERIFY  — correct; no change
│       ├── worker_selector.py          VERIFY  — correct; no change
│       └── complexity_sizer.py        VERIFY  — correct; no change
```

**Total files requiring modification: 2** (`cli.py`, `generate.py`)
**Total files requiring verification only: 6** (all other listed files)
**Total new files: 0**

### End-to-End Pipeline Flow

The full `cobuilder pipeline create --sd SD-FILE.md --repo REPO` execution sequence after this epic:

```
Step 1/7: ensure_baseline(repo, project_root)
    └── .repomap/baselines/{repo}/baseline.json exists?
        YES → continue
        NO  → auto-init: cobuilder repomap init → sync_baseline() → continue
              (logs: "[1/7] No baseline found — running repomap init (~2-3 min)...")

Step 2/7: collect_repomap_nodes(repo, project_root)
    └── reads baseline.json → returns list[dict] with keys:
        node_id, title, file_path, folder_path, delta_status,
        interfaces, description, module, change_summary

Step 2.5/7: filter_nodes_by_sd_relevance(nodes, sd_content)
    └── deterministic keyword filter against SD text
        returns subset of nodes whose module/title match SD scope

Step 3/7: run_taskmaster_parse(sd_path, project_root, repomap_context=ctx)
    └── [FIX] build repomap_context via get_repomap_context(repo, ...)
    └── create_enriched_input() writes temp .md with SD + context block
    └── subprocess: npx task-master-ai parse-prd --input <tmp> --project-root <root>
    └── reads .taskmaster/tasks/tasks.json → returns tasks dict
    └── on timeout/failure: returns {} (logs warning, does NOT abort)

Step 4/7: cross_reference_beads(nodes, prd_ref)
    └── matches beads by title similarity (40% word overlap)
        enriches nodes with bead_id, priority

Step 5/7: EnrichmentPipeline().enrich(nodes, {}, sd_content)
    └── FileScoper         → node["file_scope"]            (LLM call per node)
    └── AcceptanceCrafter  → node["acceptance_criteria"]   (LLM call per node)
    └── DependencyInferrer → node["dependencies"]          (LLM call per node, sees all nodes)
    └── WorkerSelector     → node["worker_type"]           (LLM call per node, uses file_scope)
    └── ComplexitySizer    → node["complexity"]            (LLM call per node, uses ACs + file count)

Step 6/7: generate_pipeline_dot(prd_ref, nodes, solution_design, target_dir)
    └── [FIX] unique dot_node_id = impl_{sanitize(title)}_{sanitize(module[:8])}
    └── [FIX] per-node solution_design attribute = f"{sd_path}#{feature_id}"
    └── triplet: codergen node → validate_tech node → validate_biz node
    └── linear ordering by dependency graph (DependencyInferrer output)
    └── writes DOT to --output path or stdout

Step 7/7: write_all_enrichments(sd_path, nodes, taskmaster_tasks)
    └── for each node with feature_id: append ## CoBuilder Enrichment block to SD
    └── block contains: pipeline_node, bead_id, worker_type, delta_status,
        taskmaster_tasks, file_scope, acceptance_criteria_enriched
```

### Node Deduplication Strategy

**Current behavior (broken):** When two nodes both have title "Add Auth Middleware", both get `dot_node_id = "impl_add_auth_middleware"`. The deduplication at line 648 appends a UUID slice: `impl_add_auth_middleware_a3f7b2c1`. This is unreadable.

**Target behavior:** Use `module` from the node dict (already populated from RepoMap) as the disambiguator. The deduplication rule is:

```python
dot_node_id = f"impl_{sanitize_node_id(title)}"
if dot_node_id in existing_ids:
    # Use module as disambiguator (e.g., "auth" from "src/auth/")
    module_slug = sanitize_node_id(node.get("module", "").split("/")[0] or node_id_raw[-6:])
    dot_node_id = f"impl_{sanitize_node_id(title)}_{module_slug}"
    # If still collides (same module + same title), append counter
    if dot_node_id in existing_ids:
        counter = sum(1 for nid in existing_ids if nid.startswith(dot_node_id))
        dot_node_id = f"{dot_node_id}_{counter}"
```

This produces human-readable IDs like `impl_add_auth_middleware_auth` and `impl_add_auth_middleware_middleware` instead of UUID suffixes.

### Per-Node `solution_design` Attribute

**Current behavior (incomplete):** The `solution_design` attribute is written at graph level (the DOT `digraph` header) referencing the SD file path. Individual codergen nodes do not carry the attribute, so workers cannot tell which SD section their node belongs to.

**Target behavior:** Each codergen node carries:

```dot
impl_add_auth_middleware [
    handler="codergen"
    label="Add Auth Middleware"
    worker_type="backend-solutions-engineer"
    solution_design="SD-COBUILDER-001-pipeline-generation.md#F2.3"
    ...
]
```

The `feature_id` (e.g., `F2.3`) must be propagated from the node dict through `generate_pipeline_dot()`. It is already available on nodes that have a `feature_id` key (set during beads cross-reference or SD relevance filtering). For nodes without a `feature_id`, the graph-level `solution_design` attribute serves as fallback — no change needed for those nodes.

### TaskMaster Context Wire-Up

**Current call (line 60, `cli.py`):**

```python
taskmaster_tasks = run_taskmaster_parse(str(sd_path.resolve()), str(project_root.resolve()))
```

**Fixed call:**

```python
# Get RepoMap context for TaskMaster input enrichment
try:
    repomap_ctx = bridge.get_repomap_context(
        repo,
        project_root=project_root,
        prd_keywords=_extract_prd_keywords(sd_content),
        format="yaml",
    )
except (KeyError, FileNotFoundError):
    repomap_ctx = ""
    typer.echo("      [warn] RepoMap context unavailable — TaskMaster will use SD only")

taskmaster_tasks = run_taskmaster_parse(
    str(sd_path.resolve()),
    str(project_root.resolve()),
    repomap_context=repomap_ctx,
)
```

The helper `_extract_prd_keywords(sd_content)` extracts keywords from the SD frontmatter `prd_id` field and the first H1 heading to drive relevance filtering in `get_repomap_context()`. This is a private function added to `cli.py`, not to `bridge.py`.

```python
def _extract_prd_keywords(sd_content: str) -> list[str]:
    """Extract keywords from SD frontmatter and H1 for RepoMap context filtering."""
    keywords: list[str] = []
    # Pull prd_id from YAML frontmatter
    fm_match = re.search(r'^prd_id:\s*(.+)$', sd_content, re.MULTILINE)
    if fm_match:
        keywords.extend(fm_match.group(1).strip().lower().split('-'))
    # Pull words from first H1
    h1_match = re.search(r'^#\s+(.+)$', sd_content, re.MULTILINE)
    if h1_match:
        keywords.extend(h1_match.group(1).lower().split())
    return [k for k in keywords if len(k) > 2]  # filter stopwords by length
```

---

## Functional Decomposition

### F2.1: Auto-Init Logic (DONE — verify only)

**Status**: Implemented in `generate.py` via `ensure_baseline()`.

**What exists**: `ensure_baseline()` at line 91 of `generate.py` checks for `.repomap/baselines/{repo}/baseline.json`. If missing, it calls `bridge.init_repo()` then `bridge.sync_baseline()` and logs progress. The CLI wires it at step 1/7.

**Verification checklist**:
- `ensure_baseline("nonexistent-repo", Path("."))` triggers init and logs at `typer.echo` level
- Log message format: `"[1/7] No baseline found — running repomap init..."` (clear, with timing expectation)
- Init failure raises `FileNotFoundError` (not swallowed) so the CLI exits with code 1

**No code changes required.**

### F2.2: RepoMap Node Collection (DONE — verify only)

**Status**: Implemented in `generate.py` via `collect_repomap_nodes()`.

**What exists**: Reads `baseline.json`, iterates nodes, returns list of dicts with keys: `node_id`, `title`, `file_path`, `folder_path`, `delta_status`, `interfaces`, `description`, `module`, `change_summary`. Only MODIFIED and NEW nodes are returned (EXISTING nodes filtered out).

**Verification checklist**:
- Only nodes with `delta_status in {"modified", "new"}` are returned
- Node dict contains all required keys (missing keys default to empty string, not `None`)
- Empty baseline returns `[]` without exception

**No code changes required.**

### F2.3: LLM Enrichment Pipeline (DONE with observability fix)

**Status**: All five enrichers exist and are wired in `EnrichmentPipeline.enrich()`. The pipeline is correct. One observability gap must be fixed.

**What needs to change in `base.py`**:

The `_parse_yaml()` method returns `{}` silently on total failure. Downstream enrichers check `parsed.get("key", default)` — they do not detect that the parse failed entirely. This means a node can complete enrichment with all default values while the logs show nothing alarming.

Add a warning log when the parsed result is empty or missing required keys:

```python
# In BaseEnricher._parse_yaml(), after all attempts fail:
logger.error(
    "YAML parse failed after all attempts for %s — enricher %s returning empty dict",
    node_info,          # pass through from caller
    self.__class__.__name__,
)
return {}
```

And in `_enrich_one()` of each subclass — actually, the cleaner fix is to add an enricher-level `_check_result()` call in the base class after `_parse_yaml()`:

```python
# In BaseEnricher, add:
def _warn_if_empty(self, parsed: dict, required_key: str, node_title: str) -> None:
    """Log a warning if the parsed result is missing the expected key."""
    if not parsed or required_key not in parsed:
        logger.warning(
            "[%s] Enrichment returned no '%s' for node '%s' — using defaults",
            self.__class__.__name__,
            required_key,
            node_title,
        )
```

Each enricher calls `self._warn_if_empty(parsed, "file_scope", node.get("title", ""))` immediately after `parsed = self._parse_yaml(response)`.

**Files modified**: `cobuilder/pipeline/enrichers/base.py` (add `_warn_if_empty` method)
**Files modified**: Each of the 5 enricher files (1-line call to `_warn_if_empty` added after parse)

**Acceptance**: Log output during a run shows `[WorkerSelector] Enrichment returned no 'worker_type'...` when LLM returns malformed YAML, rather than silent default.

### F2.4: Beads Cross-Reference (DONE — verify only)

**Status**: Implemented in `generate.py` via `cross_reference_beads()`. Matches nodes to beads by 40% word-overlap threshold on title. Enriches nodes with `bead_id` and `priority`.

**Verification checklist**:
- Matching is by title words, not file path (intentional — beads don't have file paths)
- Node with no beads match gets `bead_id = ""`, `priority = 0`
- `bd list --json` subprocess failure returns nodes unchanged (logs warning)

**No code changes required.**

### F2.5: TaskMaster Integration with RepoMap Context (BROKEN — primary fix)

**Status**: `taskmaster_bridge.py` is complete and correct. `cli.py` line 60 does not pass `repomap_context`. This is the primary bug.

**Files modified**: `cobuilder/cli.py`

**Changes**:

1. Import `re` at top of file (already imported? verify — if not, add)
2. Import `cobuilder.bridge as bridge` in the function body (lazy import, like all other imports in this file)
3. Add `_extract_prd_keywords(sd_content)` as a module-level private function
4. Replace the bare `run_taskmaster_parse()` call with the context-enriched version shown in the Technical Architecture section

**Exact diff target (line 59-60 of `cli.py`):**

```python
# BEFORE:
taskmaster_tasks = run_taskmaster_parse(str(sd_path.resolve()), str(project_root.resolve()))

# AFTER:
from cobuilder import bridge as _bridge
try:
    repomap_ctx = _bridge.get_repomap_context(
        repo,
        project_root=project_root,
        prd_keywords=_extract_prd_keywords(sd_content),
        format="yaml",
    )
except (KeyError, FileNotFoundError):
    repomap_ctx = ""
    typer.echo("      [warn] RepoMap context unavailable — proceeding without it")
taskmaster_tasks = run_taskmaster_parse(
    str(sd_path.resolve()),
    str(project_root.resolve()),
    repomap_context=repomap_ctx,
)
```

Note: `sd_content` is already read at step 2.5. This fix reuses it — no additional file read required.

**Acceptance**: `run_taskmaster_parse` is called with `repomap_context` non-empty when a baseline exists. The temp file written by `create_enriched_input()` contains the SD text followed by `## Codebase Context (Auto-Generated by CoBuilder RepoMap)` block. TaskMaster tasks in `tasks.json` reference actual file paths from the codebase (not invented paths).

### F2.6: DOT Rendering with Enriched Attributes (PARTIAL — two fixes needed)

**Status**: `generate_pipeline_dot()` exists and produces valid DOT. Two issues remain: duplicate node IDs and missing per-node `solution_design`.

**Files modified**: `cobuilder/pipeline/generate.py`

**Fix 1: Node ID deduplication** (lines 641-666 approximately)

Replace the UUID-slice suffix with a module-derived suffix:

```python
dot_node_id = f"impl_{sanitize_node_id(title)}"
existing_ids = {t["dot_node_id"] for t in task_nodes}
if dot_node_id in existing_ids:
    module_raw = node.get("module", "") or node.get("folder_path", "") or node_id_raw[-6:]
    module_slug = sanitize_node_id(module_raw.split("/")[0])
    dot_node_id = f"impl_{sanitize_node_id(title)}_{module_slug}"
    if dot_node_id in existing_ids:
        counter = sum(1 for nid in existing_ids if nid.startswith(f"impl_{sanitize_node_id(title)}"))
        dot_node_id = f"impl_{sanitize_node_id(title)}_{module_slug}_{counter}"
```

**Fix 2: Per-node `solution_design` attribute** (within the loop that writes each codergen node, lines ~700-740)

After the existing graph-level `solution_design` is written to the digraph header, also write it per-node. The value should be `f"{solution_design}#{feature_id}"` when `feature_id` is available, falling back to `solution_design` alone:

```python
# Inside the node-rendering loop, after writing worker_type:
feature_id = task.get("feature_id", "")
if solution_design:
    sd_ref = f"{solution_design}#{feature_id}" if feature_id else solution_design
    lines.append(f'        solution_design="{escape_dot_string(sd_ref)}"')
```

**Acceptance**: `cobuilder pipeline validate` on the generated DOT reports 0 errors. All node IDs are unique. Nodes with matching features have `solution_design="SD-FILE.md#F2.3"`.

### F2.7: SD v2 Enrichment Writer (DONE — verify only)

**Status**: `sd_enricher.py` is complete. `write_all_enrichments()` iterates nodes with `feature_id` and appends YAML blocks. Existing blocks are replaced idempotently.

**Verification checklist**:
- Node with `feature_id = ""` is skipped (no orphan enrichment blocks)
- Running `pipeline create` twice produces the same SD (idempotent block replacement)
- SD file encoding is preserved (UTF-8)

**No code changes required.**

### F2.8: CLI Command (`cobuilder pipeline create`) (PARTIAL — fix in F2.5)

**Status**: The 7-step command exists in `cli.py`. All steps are wired. The only change is the `run_taskmaster_parse` call at step 3 (covered in F2.5).

**Additional hardening** (minor, same file):

Add a step-completion log at the end of step 5 (LLM enrichment) showing per-enricher node counts, to aid debugging when enrichers silently use defaults:

```python
# After: nodes = pipeline.enrich(nodes, {}, sd_content)
worker_types = {}
for n in nodes:
    wt = n.get("worker_type", "unknown")
    worker_types[wt] = worker_types.get(wt, 0) + 1
typer.echo(f"      Worker type distribution: {worker_types}")
```

This is a 5-line addition that provides meaningful signal during CI runs without altering behavior.

---

## Dependencies

| Feature | Depends On | Reason |
|---------|-----------|--------|
| F2.5 (TaskMaster fix) | F2.1, F2.2 (done) | Needs baseline to generate RepoMap context |
| F2.5 (TaskMaster fix) | `bridge.get_repomap_context()` (done) | Already implemented and tested |
| F2.6 (DOT fix) | F2.3 (enrichers) | Per-node `feature_id` comes from enriched nodes |
| F2.3 observability | `base.py` `_warn_if_empty` | Base class change; enrichers call it |
| All | Epic 1 (done) | Package structure and `bridge.py` already exist |

**External dependencies (no new ones)**:
- `anthropic` SDK — already used by all enrichers
- `npx task-master-ai` — already called by `taskmaster_bridge.py`
- `yaml` (PyYAML) — already used throughout

---

## Acceptance Criteria per Feature

### AC-F2.1: Auto-Init
- Running `cobuilder pipeline create --sd X.md --repo nonexistent-repo` when `.repomap/baselines/nonexistent-repo/` does not exist triggers `sync_baseline()` and logs `[1/7] No baseline found — running repomap init`.
- The command does not abort; it completes normally after init.
- Evidence: unit test mocking `bridge.sync_baseline` to verify it is called when baseline is absent.

### AC-F2.2: Node Collection
- `collect_repomap_nodes()` returns only nodes with `delta_status in {"modified", "new"}`.
- All returned nodes have non-None values for: `node_id`, `title`, `delta_status`.
- Evidence: unit test with a fixture `baseline.json` containing EXISTING, MODIFIED, and NEW nodes.

### AC-F2.3: LLM Enrichment
- `EnrichmentPipeline().enrich(nodes, {}, sd_text)` returns nodes with all five enricher output keys: `file_scope`, `acceptance_criteria`, `dependencies`, `worker_type`, `complexity`.
- When LLM returns malformed YAML, the `WARNING` log contains the enricher class name and node title.
- Evidence: unit test with mocked `_call_llm` returning malformed YAML; assert logger.warning called.

### AC-F2.4: Beads Cross-Reference
- A node with title "Add Auth Middleware" matches a bead titled "Add Authentication Middleware" (sufficient word overlap).
- A node with title "Implement ZZZ Frob" (no beads) gets `bead_id = ""`.
- Evidence: unit test with fixture beads JSON.

### AC-F2.5: TaskMaster Integration (primary fix)
- `run_taskmaster_parse` is called with `repomap_context` containing the string `"repository:"` (YAML preamble from `get_repomap_context()`).
- The temp file passed to `task-master-ai parse-prd` contains `## Codebase Context (Auto-Generated by CoBuilder RepoMap)`.
- Tasks in `tasks.json` include at least one file path matching a path in the baseline.
- Evidence: integration test with a real baseline and real TaskMaster invocation (tagged `@pytest.mark.integration`).

### AC-F2.6: DOT Rendering
- A pipeline with two nodes both titled "Setup Config" produces two distinct DOT node IDs (e.g., `impl_setup_config_auth` and `impl_setup_config_pipeline`).
- Every codergen node carries a `solution_design` attribute.
- `cobuilder pipeline validate` on the output DOT returns 0 errors.
- Evidence: unit test with two nodes having identical titles but different modules.

### AC-F2.7: SD Enrichment
- After `pipeline create`, each feature section in the SD file that has a corresponding node contains a `## CoBuilder Enrichment — FX.X:` block.
- Running `pipeline create` a second time produces identical SD content (idempotent).
- Evidence: unit test with a fixture SD file containing `## F1.1: Auth` and `## F1.2: Middleware`.

### AC-F2.8: End-to-End
- `cobuilder pipeline create --sd SD-AUTH-001.md --repo my-project` completes without exception.
- The generated DOT passes `cobuilder pipeline validate`.
- Evidence: acceptance test `acceptance-tests/PRD-COBUILDER-001/test_pipeline_create_e2e.py`.

---

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| `get_repomap_context()` raises `FileNotFoundError` when manifest is missing | Medium | Medium | Already handled — try/except in cli.py degrades gracefully to empty context |
| Two nodes in same module have identical titles (triple collision) | Low | Low | Three-tier deduplication: title, title+module, title+module+counter |
| TaskMaster subprocess takes >120s on large codebases | Medium | Low | Existing timeout=120 remains; logs warning and returns `{}` without aborting |
| LLM enrichers cost ~$0.01 per node at 10 nodes = ~$0.10 per pipeline create | Low | High | Acceptable for current usage; cache layer is future work (Epic 2 out of scope) |
| Per-node `solution_design` attribute breaks DOT parsers expecting only graph-level attributes | Low | Low | Graphviz DOT format supports node-level attributes freely; `cobuilder pipeline validator.py` will be updated to accept this attribute |
| `_sanitize_yaml` regex misquotes values containing backslash sequences | Low | Low | Existing escape logic handles `"` → `\"` but not `\n`; enricher prompts do not produce multi-line values in single-quoted fields, so this is not triggered in practice |

---

## File Scope

### Files Modified

**`cobuilder/cli.py`**
- Add `import re` if not already present (check: it is NOT imported at top level currently)
- Add private `_extract_prd_keywords(sd_content: str) -> list[str]` function (module level, before the command definitions)
- Modify `pipeline_create()` step 3 block (lines 57-63): add `from cobuilder import bridge as _bridge`, build `repomap_ctx`, pass to `run_taskmaster_parse`
- Add worker type distribution log after step 5

**`cobuilder/pipeline/generate.py`**
- Modify node deduplication logic in `generate_pipeline_dot()` (lines ~645-648): replace UUID suffix with module-derived suffix
- Add per-node `solution_design` attribute in the codergen node rendering block (lines ~727-732)

**`cobuilder/pipeline/enrichers/base.py`**
- Add `_warn_if_empty(self, parsed: dict, required_key: str, node_title: str) -> None` method to `BaseEnricher`

**`cobuilder/pipeline/enrichers/file_scoper.py`**
- Add `self._warn_if_empty(parsed, "file_scope", node.get("title", ""))` after `parsed = self._parse_yaml(response)`

**`cobuilder/pipeline/enrichers/acceptance_crafter.py`**
- Add `self._warn_if_empty(parsed, "acceptance_criteria", node.get("title", ""))` after `parsed = self._parse_yaml(response)`

**`cobuilder/pipeline/enrichers/dependency_inferrer.py`**
- Add `self._warn_if_empty(parsed, "dependencies", node.get("title", ""))` after `parsed = self._parse_yaml(response)` in `_enrich_one_with_context`

**`cobuilder/pipeline/enrichers/worker_selector.py`**
- Add `self._warn_if_empty(parsed, "worker_type", node.get("title", ""))` after `parsed = self._parse_yaml(response)`

**`cobuilder/pipeline/enrichers/complexity_sizer.py`**
- Add `self._warn_if_empty(parsed, "complexity", node.get("title", ""))` after `parsed = self._parse_yaml(response)`

### Files Verified (No Change)

- `cobuilder/pipeline/taskmaster_bridge.py` — `run_taskmaster_parse(repomap_context=...)` already implemented correctly
- `cobuilder/pipeline/sd_enricher.py` — `write_all_enrichments()` correct and idempotent
- `cobuilder/bridge.py` — `get_repomap_context()` with `format="yaml"` returns structured YAML
- `cobuilder/pipeline/generate.py` functions: `ensure_baseline()`, `collect_repomap_nodes()`, `filter_nodes_by_sd_relevance()`, `cross_reference_beads()` — all correct

### Files NOT Changed (Out of Scope for Epic 2)

- `cobuilder/pipeline/transition.py` — baseline refresh on validation is Epic 4
- `cobuilder/orchestration/spawn_orchestrator.py` — orchestrator boot sequence is Epic 4
- `cobuilder/repomap/context_filter.py` — relevance filtering algorithm is Epic 3
- All test files — test additions are a separate deliverable tracked in acceptance-tests/

---

## Implementation Sequence

The fixes are independent of each other and can be implemented in parallel, but the following sequence minimizes debugging surface:

**Phase 1: Observability (lowest risk, highest diagnostic value)**
- Add `_warn_if_empty()` to `base.py`
- Add `self._warn_if_empty(...)` calls in all 5 enrichers
- Run existing enricher unit tests to confirm no regressions
- Estimated: 30 minutes

**Phase 2: TaskMaster Context Wire-Up (primary functional fix)**
- Add `import re` and `_extract_prd_keywords()` to `cli.py`
- Modify step 3 block to pass `repomap_context`
- Add worker type distribution log after step 5
- Test: run `cobuilder pipeline create --skip-enrichment` to verify TaskMaster call; check temp file contents
- Estimated: 45 minutes

**Phase 3: DOT Rendering Fixes (correctness fixes)**
- Fix node deduplication in `generate.py`
- Add per-node `solution_design` attribute
- Test: run with two nodes of identical title; verify unique IDs in DOT
- Run `cobuilder pipeline validate` on generated output
- Estimated: 30 minutes

**Phase 4: End-to-End Validation**
- Run full `cobuilder pipeline create --sd docs/prds/SD-COBUILDER-001-pipeline-generation.md --repo claude-harness-setup`
- Verify: DOT generated, SD enriched, TaskMaster tasks present, `validate` passes
- Check TaskMaster `tasks.json` for file paths from baseline
- Estimated: 20 minutes (mostly waiting for LLM enrichment)

---

## CoBuilder Enrichment — F2.1: Auto-Init Logic
<!-- Auto-generated by cobuilder pipeline create — do not manually edit -->

```yaml
pipeline_node: impl_auto_init_logic
bead_id: ""
worker_type: backend-solutions-engineer
delta_status: existing
taskmaster_tasks: []
file_scope:
  modify:
    - path: cobuilder/pipeline/generate.py
      reason: "ensure_baseline() already exists — verify only"
  create: []
  reference_only:
    - cobuilder/bridge.py
acceptance_criteria_enriched:
  - "Missing baseline triggers auto-init with clear log message"
  - "Init failure raises FileNotFoundError (does not swallow)"
```

## CoBuilder Enrichment — F2.3: LLM Enrichment Pipeline
<!-- Auto-generated by cobuilder pipeline create — do not manually edit -->

```yaml
pipeline_node: impl_llm_enrichment_observability
bead_id: ""
worker_type: backend-solutions-engineer
delta_status: modified
taskmaster_tasks: []
file_scope:
  modify:
    - path: cobuilder/pipeline/enrichers/base.py
      reason: "Add _warn_if_empty() method"
    - path: cobuilder/pipeline/enrichers/file_scoper.py
      reason: "Add _warn_if_empty() call"
    - path: cobuilder/pipeline/enrichers/acceptance_crafter.py
      reason: "Add _warn_if_empty() call"
    - path: cobuilder/pipeline/enrichers/dependency_inferrer.py
      reason: "Add _warn_if_empty() call"
    - path: cobuilder/pipeline/enrichers/worker_selector.py
      reason: "Add _warn_if_empty() call"
    - path: cobuilder/pipeline/enrichers/complexity_sizer.py
      reason: "Add _warn_if_empty() call"
  create: []
  reference_only: []
acceptance_criteria_enriched:
  - "WARNING log contains enricher class name and node title on YAML parse failure"
  - "Existing enricher unit tests pass without modification"
```

## CoBuilder Enrichment — F2.5: TaskMaster Integration
<!-- Auto-generated by cobuilder pipeline create — do not manually edit -->

```yaml
pipeline_node: impl_taskmaster_context_wirep
bead_id: ""
worker_type: backend-solutions-engineer
delta_status: modified
taskmaster_tasks: []
file_scope:
  modify:
    - path: cobuilder/cli.py
      reason: "Pass repomap_context to run_taskmaster_parse; add _extract_prd_keywords"
  create: []
  reference_only:
    - cobuilder/pipeline/taskmaster_bridge.py
    - cobuilder/bridge.py
acceptance_criteria_enriched:
  - "run_taskmaster_parse called with repomap_context containing 'repository:' YAML key"
  - "Temp file passed to task-master-ai contains Codebase Context block"
  - "TaskMaster tasks reference actual file paths from baseline"
```

## CoBuilder Enrichment — F2.6: DOT Rendering
<!-- Auto-generated by cobuilder pipeline create — do not manually edit -->

```yaml
pipeline_node: impl_dot_rendering_fixes
bead_id: ""
worker_type: backend-solutions-engineer
delta_status: modified
taskmaster_tasks: []
file_scope:
  modify:
    - path: cobuilder/pipeline/generate.py
      reason: "Fix duplicate node IDs; add per-node solution_design attribute"
  create: []
  reference_only:
    - cobuilder/pipeline/validator.py
acceptance_criteria_enriched:
  - "Two nodes with identical titles but different modules get unique DOT IDs"
  - "Every codergen node carries solution_design attribute"
  - "cobuilder pipeline validate returns 0 errors on generated DOT"
```

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
