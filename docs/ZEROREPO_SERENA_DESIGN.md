# ZeroRepo + Serena Partnership Design

**Version**: 1.0
**Date**: 2026-02-07
**Status**: Design Document (Not Yet Implemented)

---

## Overview

This document describes a partnership architecture between ZeroRepo (RPG pipeline) and Claude Code (with Serena MCP) that enables project-aware technical specification generation.

**Core Insight**: The paper's ZeroRepo uses a 1.5M-feature ontology as a "structured knowledge base" to ground LLM planning. Our equivalent is an **RPG graph of the existing codebase**, built by Serena walking the actual code. This gives us a project-specific knowledge base that makes the LLM's planning dramatically more accurate than either tool alone.

---

## Architecture: Three-Phase Flow

```
Phase A: INIT (One-time, per project)
  Claude Code + Serena → zerorepo init → baseline.json
  "What already exists?"

Phase B: GENERATE (Per-PRD)
  PRD + baseline.json → zerorepo generate → delta RPG
  "What needs to be added/changed?"

Phase C: IMPLEMENT (Per-feature, Claude Code)
  Claude Code reads delta RPG → implements with Serena
  "Build what the graph says"
```

### How This Maps to the Paper

| Paper's Approach | Our Approach | Purpose |
|------------------|-------------|---------|
| 1.5M-feature ontology | Existing codebase RPG (`baseline.json`) | Structured knowledge base |
| User specification | New PRD | Desired capabilities |
| Proposal-Level Construction | Spec Parser + Graph Construction | High-level module planning |
| Implementation-Level Construction | Enrichment Pipeline | File paths, interfaces, data flows |
| Graph-Guided Code Generation | Claude Code + Serena reading the delta RPG | Actual implementation |

---

## Phase A: `zerorepo init` — Build Baseline RPG

### Command

```bash
zerorepo init --project-path /path/to/project
```

### What It Does

1. **Walk the codebase with Serena MCP**:
   - `list_dir(relative_path="/")` → discover all source directories
   - `get_symbols_overview(relative_path="src/")` → extract modules, classes, functions
   - `find_symbol(name_path="*", depth=2)` → get hierarchical symbol tree
   - `find_referencing_symbols(symbol="X")` → trace actual call/import relationships

2. **Build RPG nodes at all three levels**:

   | RPG Level | Source | Example |
   |-----------|--------|---------|
   | MODULE | Top-level packages | `my-project-backend/` |
   | COMPONENT | Subdirectories, files within packages | `api/routers/`, `models/` |
   | FEATURE | Individual classes, functions, methods | `class PostCallProcessor`, `def dispatch_verification_request()` |

3. **Build RPG edges from actual relationships**:

   | Edge Type | Source | How Detected |
   |-----------|--------|-------------|
   | HIERARCHY | Module containment | Directory structure (parent folder → child file → function) |
   | INVOCATION | Function call relationships | `find_referencing_symbols()` → caller/callee pairs |
   | DATA_FLOW | Import/data passing patterns | Parameter types, return types, import chains |
   | INHERITANCE | Class hierarchy | `find_symbol()` with `depth=2` on classes |
   | ORDERING | Execution/build dependencies | Import order, middleware chains |

4. **Populate node metadata from actual code**:

   | Field | Source |
   |-------|--------|
   | `file_path` | Actual file location from Serena |
   | `folder_path` | Parent directory |
   | `signature` | Actual function/method signature from Serena |
   | `docstring` | Actual docstring from symbol body |
   | `interface_type` | FUNCTION / CLASS / METHOD (from symbol type) |
   | `serena_validated` | `true` (all nodes come from real code) |
   | `actual_dependencies` | Real runtime dependencies from Serena |

5. **Store as baseline**:
   ```
   .zerorepo/
   ├── baseline.json          # Complete RPG of existing codebase
   ├── baseline-metadata.json # Timestamp, project path, Serena version
   └── config.json            # Project settings
   ```

### Baseline JSON Structure

```json
{
  "nodes": {
    "uuid-1": {
      "name": "my-project-backend",
      "level": "MODULE",
      "node_type": "FOLDER_AUGMENTED",
      "folder_path": "my-project-backend/",
      "serena_validated": true,
      "metadata": {
        "language": "python",
        "framework": "fastapi",
        "file_count": 47,
        "loc": 12500
      }
    },
    "uuid-2": {
      "name": "PostCallProcessor",
      "level": "FEATURE",
      "node_type": "FUNCTION_AUGMENTED",
      "file_path": "my-project-backend/processors/post_call_processor.py",
      "interface_type": "CLASS",
      "signature": "class PostCallProcessor(BaseProcessor):",
      "docstring": "Handles post-call processing...",
      "serena_validated": true,
      "actual_dependencies": ["uuid-3", "uuid-4"]
    }
  },
  "edges": {
    "edge-1": {
      "source_id": "uuid-1",
      "target_id": "uuid-2",
      "edge_type": "HIERARCHY"
    },
    "edge-2": {
      "source_id": "uuid-2",
      "target_id": "uuid-5",
      "edge_type": "INVOCATION",
      "metadata": {"call_count": 3}
    }
  },
  "metadata": {
    "project_name": "my-project",
    "generated_at": "2026-02-07T12:00:00Z",
    "serena_version": "1.0",
    "total_modules": 5,
    "total_components": 23,
    "total_features": 187,
    "total_edges": 342
  }
}
```

---

## Phase B: `zerorepo generate` — Produce Delta RPG

### Command

```bash
zerorepo generate test-spec.md \
  --baseline .zerorepo/baseline.json \
  --output-dir .zerorepo/output
```

### Pipeline Stages

#### Stage 1: Spec Parsing (temperature=0)

The LLM sees:
- The PRD text
- A SUMMARY of the baseline RPG (module names, key interfaces, file structure)
- Instruction: "Extract epics, components, data flows. Note which components already exist in the baseline."

Output: `01-spec.json` with deep structure including `exists_in_baseline: true/false` per component.

#### Stage 2: Graph Construction

Build new RPG nodes from the spec, merging with baseline:
- For each epic → check if MODULE exists in baseline
- For each component → check if COMPONENT exists in baseline
- For each feature → check if FEATURE exists in baseline
- Create ONLY new nodes for what doesn't exist
- Create edges connecting new nodes to existing ones

Output: `03-graph.json` — a DELTA graph showing:
```json
{
  "existing_nodes": ["uuid-1", "uuid-2", ...],  // Reference by ID
  "new_nodes": {...},                             // New RPG nodes
  "modified_nodes": {...},                        // Existing nodes that need changes
  "new_edges": {...},                             // New relationships
  "implementation_order": [...]                    // Topological sort of new work
}
```

#### Stage 3: Enrichment

The enrichment pipeline runs on the delta graph, with baseline context:
- **FolderEncoder**: Assigns paths matching existing project conventions
- **FileEncoder**: Names files matching existing naming patterns
- **DataFlowEncoder**: Adds DATA_FLOW edges connecting new modules to existing data sources
- **InterfaceDesignEncoder**: Generates signatures matching existing code style (Pydantic models, FastAPI patterns, etc.)
- **OrderingEncoder**: Determines build order respecting existing dependency graph

Output: `04-rpg.json` — fully enriched delta RPG.

#### Stage 4: Report

Output: `pipeline-report.md` — human-readable summary:
```markdown
## ZeroRepo Pipeline Report

### Baseline: my-project (5 modules, 187 features)

### Changes Required by PRD: work-history-phase1-enterprise-readiness

**New Modules**: 0
**Modified Modules**: 3
  - my-project-backend: +2 new components (workflow_config, verification_token)
  - my-project-frontend: +1 new component (verify/work-history page)
  - my-project-communication: +1 modified component (dispatch logic)

**New Features**: 15
  - WorkflowConfig model (Pydantic, 9 fields)
  - 5 API endpoints (CRUD + resolve)
  - Token generation/validation
  - Email dispatch logic
  - Unified verification page (form + voice modes)
  - PostCheckProcessor (rename + extend PostCallProcessor)

**New Edges**: 23
  - 8 DATA_FLOW (config → dispatch, token → page, form → processor)
  - 10 HIERARCHY (new features within existing modules)
  - 5 INVOCATION (new calls between existing and new components)

**Implementation Order**: (topological sort)
  1. Database migration (workflow_configurations)
  2. WorkflowConfig model + API
  3. Verification token model
  4. Email dispatch logic
  5. ...
```

---

## Phase C: Implementation (Claude Code)

Claude Code reads the delta RPG and implements systematically:

```python
# Claude Code as orchestrator can query the RPG:
rpg = load_rpg(".zerorepo/output/04-rpg.json")

# "What needs to be created?"
new_features = [n for n in rpg.nodes if not n.serena_validated]

# "In what order?"
ordered = rpg.topological_sort(new_features)

# "What interfaces does this feature need?"
for feature in ordered:
    print(f"Create: {feature.file_path}")
    print(f"Signature: {feature.signature}")
    print(f"Depends on: {feature.actual_dependencies}")
    print(f"Data flows: {rpg.get_edges(feature, EdgeType.DATA_FLOW)}")
```

This is NOT just "read the plan" — it's programmatic traversal of a structured graph that provides:
- Explicit dependency ordering (no guessing)
- Precise file paths respecting project conventions
- Interface signatures matching existing code style
- Data flow edges showing how new code connects to existing

---

## Why This Is Better Than Claude Code Alone

| Capability | Claude Code Alone | Claude Code + ZeroRepo |
|-----------|-------------------|----------------------|
| Planning structure | Free-form markdown (degrades at scale) | Typed RPG graph (scales to 100s of modules) |
| Coverage | Ad-hoc (misses edge cases) | Systematic (ontology-grounded, with baseline diff) |
| Existing code awareness | Reads files on demand | Pre-built graph of entire codebase |
| Reproducibility | Different plans each time | Deterministic (temperature=0, graph validation) |
| Dependency tracking | Implicit in context window | Explicit typed edges (DATA_FLOW, INVOCATION, etc.) |
| Interface consistency | Best-effort pattern matching | Signatures derived from existing code patterns |
| Implementation ordering | Developer intuition | Topological sort on dependency graph |

---

## Ontology Integration (Future)

The paper's 1.5M-feature ontology serves as domain knowledge — "what features COULD exist in software." For now, we skip it and rely on the LLM's built-in knowledge. Future integration:

```bash
# Future: init with both baseline AND ontology
zerorepo init --project-path /path/to/project --ontology features.db
```

The ontology would help identify features the codebase SHOULD have but DOESN'T — e.g., "most FastAPI projects have rate limiting, but yours doesn't." This is a coverage enhancement, not a prerequisite for the core pipeline.

---

## Implementation Phases

### Sprint 1 (Current): Basic Pipeline
- [x] Model upgrade to gpt-5.2
- [x] Deep spec parser with temperature=0
- [x] `zerorepo generate` command chaining stages
- [x] Spec → Graph converter
- [x] Enrichment encoders producing real output
- [ ] E2E test with test-spec.md

### Sprint 2 (Next): Codebase Baseline
- [ ] `zerorepo init` command
- [ ] Serena integration for codebase walking
- [ ] Baseline RPG builder (nodes + edges from real code)
- [ ] `.zerorepo/baseline.json` storage
- [ ] Baseline summary generation for LLM context injection

### Sprint 3 (After): Delta Pipeline
- [ ] `--baseline` parameter for `zerorepo generate`
- [ ] LLM prompt templates that include baseline context
- [ ] Delta graph output format (existing vs new vs modified)
- [ ] Implementation ordering via topological sort
- [ ] Pipeline report with delta-aware formatting

### Sprint 4 (Future): Full Loop
- [ ] Claude Code skill for invoking `zerorepo generate`
- [ ] Automatic Serena context gathering before pipeline
- [ ] RPG-guided implementation mode for Claude Code
- [ ] Ontology integration for coverage analysis

---

**Note**: The ontology is likely still needed for maximum coverage, but the codebase baseline + PRD pipeline provides immediate practical value without it. We can add the ontology layer later as a coverage enhancement.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
