---
prd_id: PRD-COBUILDER-001
title: "Three-Way Context Enhancement: RepoMap + DOT + SD for TaskMaster"
status: active
type: solution-design
epic: E3 (Context Injection)
created: 2026-02-28
last_verified: 2026-02-28
grade: authoritative
---

# SD-COBUILDER-001: Three-Way Context Enhancement

## 1. Business Context

### Problem

The current `taskmaster_bridge.py` creates enriched input for TaskMaster using only two
context sources: the Solution Design (SD) document and the RepoMap YAML context. The DOT
pipeline file — which contains the node dependency graph, handler types, bead IDs, and
acceptance criteria — is NOT included.

This means TaskMaster decomposes tasks without knowledge of:
- Which nodes depend on which (execution order)
- What handler types are assigned (codergen, toolcall, wait.human)
- What acceptance criteria exist per node
- How implementation nodes relate to validation gates

### Goal

Enhance `taskmaster_bridge.py` to accept an optional DOT pipeline file and inject a
structured summary of the pipeline graph alongside the existing SD + RepoMap context.
This gives TaskMaster three-way context: **what to build** (SD), **what exists** (RepoMap),
and **how it connects** (DOT).

## 2. Technical Architecture

### Current Flow (Two-Way)

```
SD document ──┐
              ├──► create_enriched_input() ──► TaskMaster parse-prd
RepoMap YAML ─┘
```

### Target Flow (Three-Way)

```
SD document ──────┐
                  │
RepoMap YAML ─────┤──► create_enriched_input() ──► TaskMaster parse-prd
                  │
DOT pipeline ─────┘
   (parsed to structured summary)
```

### DOT Context Extraction

The DOT file is parsed to extract a structured summary containing:

```yaml
pipeline_context:
  prd_ref: "PRD-PIPELINE-ENGINE-001"
  total_nodes: 86
  node_summary:
    - id: impl_epic1_core_runner
      handler: codergen
      label: "Core Runner Implementation"
      status: validated
      bead_id: "abc123"
      acceptance: "Runner traverses graph from start to exit"
      depends_on: [start]
      blocks: [validate_epic1_tech]
    - id: validate_epic1_tech
      handler: wait.human
      label: "E1 Technical Validation"
      status: pending
      depends_on: [impl_epic1_core_runner]
  execution_order:
    - start → impl_epic1_core_runner → validate_epic1_tech → ...
  status_summary:
    validated: 11
    active: 4
    pending: 71
```

## 3. Functional Decomposition

### F1: DOT Parser for Context Extraction

**Input**: Path to a `.dot` pipeline file
**Output**: Structured YAML string suitable for LLM context injection

Responsibilities:
- Parse DOT file using regex (same approach as `attractor/cli.py` parser)
- Extract node attributes: `id`, `handler`, `label`, `status`, `bead_id`, `acceptance`
- Extract edge relationships: `source → target` with `condition` labels
- Compute topological order for `execution_order` field
- Summarize status counts

**File**: `cobuilder/pipeline/dot_context.py` (new file, ~120 lines)

### F2: Enhanced `create_enriched_input()`

Extend the existing function signature:

```python
def create_enriched_input(
    sd_path: str,
    repomap_context: str,
    dot_pipeline_path: str = "",  # NEW parameter
) -> str:
```

When `dot_pipeline_path` is provided:
1. Call `extract_dot_context(dot_pipeline_path)` from F1
2. Append a `## Pipeline Context (Auto-Generated from DOT Pipeline)` section
3. Include task ordering guidance for TaskMaster

### F3: Enhanced `run_taskmaster_parse()`

Add `dot_pipeline_path` parameter, pass through to `create_enriched_input()`.

### F4: CLI Integration

Add `--dot-pipeline` flag to the `cobuilder pipeline taskmaster` CLI subcommand.

## 4. Acceptance Criteria

### AC-1: DOT context extraction produces valid YAML
Given a `.dot` file with 10+ nodes,
When `extract_dot_context()` is called,
Then it returns a YAML string with node_summary, execution_order, and status_summary.

### AC-2: Three-way enriched input contains all three sections
Given an SD path, RepoMap YAML, and DOT pipeline path,
When `create_enriched_input()` is called with all three,
Then the output contains "## Codebase Context" AND "## Pipeline Context" sections.

### AC-3: TaskMaster receives pipeline ordering
Given three-way enriched input passed to `run_taskmaster_parse()`,
When TaskMaster generates tasks,
Then task dependencies reflect the DOT execution order.

### AC-4: Backward compatibility preserved
Given only SD path and RepoMap (no DOT path),
When `create_enriched_input()` is called,
Then it produces identical output to the current two-way version.

## 5. File Scope

| File | Action | Description |
|------|--------|-------------|
| `cobuilder/pipeline/dot_context.py` | NEW | DOT parser for context extraction |
| `cobuilder/pipeline/taskmaster_bridge.py` | MODIFY | Add dot_pipeline_path parameter |
| `cobuilder/cli.py` | MODIFY | Add --dot-pipeline CLI flag |
| `tests/unit/test_dot_context.py` | NEW | Tests for DOT context extraction |
| `tests/unit/test_taskmaster_bridge.py` | MODIFY | Tests for three-way enrichment |

## 6. Estimated Effort

Small enhancement — 1 worker, ~200 lines of new code + ~100 lines of tests.
Single orchestrator session, estimated 30-60 minutes.
