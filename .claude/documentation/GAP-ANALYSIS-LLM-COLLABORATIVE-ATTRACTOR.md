---
title: "Gap Analysis Llm Collaborative Attractor"
status: active
type: architecture
last_verified: 2026-03-14
grade: reference
---

# Gap Analysis: Static DOT Lifecycle vs LLM-Collaborative Graph Iteration

**Date**: 2026-02-23
**Promise**: promise-2867f2ab
**PRD Reference**: PRD-S3-ATTRACTOR-001
**Status**: Complete

---

## 1. Executive Summary

PRD-S3-ATTRACTOR-001 delivered a **static lifecycle management system** — CLI tools that parse, validate, transition, and checkpoint DOT pipeline graphs. What's missing is the **collaborative authoring loop** where an LLM (the S3 orchestrator or guardian) can iteratively analyze a PRD, generate a graph scaffold, refine it through inspection and modification, and then hand it off for execution with programmatic enforcement of all validations.

This document compares what we built against the 3-step collaborative vision:
1. **Auto-generate** initial .dot scaffold from codebase analysis
2. **Return to LLM** for review, analysis, and significant adjustment
3. **LLM uses CLI tools** to complete the graph with full validation enforcement

---

## 2. What We Built (Current State)

### 2.1 Schema (schema.md)
- 7 node shapes mapping to handler types (start, exit, codergen, tool, wait.human, conditional, parallel)
- Custom attributes: `handler`, `status`, `bead_id`, `worker_type`, `acceptance`, `promise_ac`
- 5-stage lifecycle: PARSE → VALIDATE → INITIALIZE → EXECUTE → FINALIZE
- 10 structural validation rules
- Status transitions: pending → active → impl_complete → validated (or failed → active retry)

### 2.2 CLI Tools (12 subcommands)

| Command | Purpose | LLM-Usable? |
|---------|---------|-------------|
| `parse` | Parse DOT into structured data | Yes — read-only inspection |
| `validate` | Check structural rules | Yes — validation feedback |
| `status` | Display node status table | Yes — awareness |
| `transition` | Advance node status | Yes — execution phase |
| `checkpoint save/restore` | Persist/restore state | Yes — safety net |
| `generate` | Auto-generate from beads | Partially — one-shot, no scaffold mode |
| `annotate` | Cross-ref with beads | Yes — sync awareness |
| `init-promise` | Generate cs-promise commands | Yes — promise setup |
| `dashboard` | Unified lifecycle view | Yes — monitoring |
| `lint` | Documentation linting | N/A |
| `gardener` | Doc remediation | N/A |
| `install-hooks` | Git hook setup | N/A |

### 2.3 Auto-Generation (generate.py)
- Reads beads task data (`bd list --json`)
- Infers `worker_type` from keyword matching on title/description
- Produces a **complete** graph with all 5 stages, AT pairing, conditional routing
- One-shot: generates everything at once, no intermediate review step
- No PRD analysis — works from beads only (not from PRD text)

### 2.4 System 3 Integration
- Output style includes "DOT Graph Navigation" section
- Execution loop: read state → identify dispatchable → dispatch → monitor → validate → loop
- Checkpoint after every transition
- Stop gate integration (block on unfinished nodes)

---

## 3. What's Missing (Gap Analysis)

### Gap 1: No Scaffold Generation Mode

**Current**: `generate` produces a complete graph from beads.
**Needed**: A `generate --scaffold` mode that produces a minimal skeleton — start node, exit node, and placeholder nodes for each epic/feature — leaving the internal structure for the LLM to design.

**Why it matters**: The LLM needs to see the raw structure and make architectural decisions about:
- Node ordering and dependencies (which tasks block which)
- Parallel vs sequential execution
- Where validation gates belong
- Which tasks need conditional routing (pass/fail branches)

**Impact**: Without this, the LLM either accepts the auto-generated graph wholesale or manually rewrites it from scratch.

### Gap 2: No Node CRUD Operations

**Current**: The only graph modification tool is `transition` (changes status attribute).
**Needed**: CLI tools to add, remove, and modify nodes:

```bash
# Proposed commands
attractor node add <file.dot> --id <node_id> --shape box --handler codergen \
    --label "Implement auth" --worker-type backend-solutions-engineer \
    --bead-id TASK-123

attractor node remove <file.dot> <node_id> [--cascade]  # removes edges too

attractor node modify <file.dot> <node_id> --label "Updated label" \
    --acceptance "New criteria"
```

**Why it matters**: Without node CRUD, the LLM must either regenerate the entire graph or perform raw text manipulation on DOT syntax — error-prone and hard to validate incrementally.

### Gap 3: No Edge CRUD Operations

**Current**: Edges are baked into the generated graph. No tool to add/remove/modify edges.
**Needed**:

```bash
# Proposed commands
attractor edge add <file.dot> <from_node> <to_node> [--label "reason"]
attractor edge remove <file.dot> <from_node> <to_node>
attractor edge list <file.dot> [--from <node>] [--to <node>]
```

**Why it matters**: Edge manipulation is how the LLM defines execution order, dependency chains, and parallel groups. This is the most creative part of graph design.

### Gap 4: No PRD-Aware Analysis Tool

**Current**: `generate` works from beads data only. No tool reads the PRD to suggest graph structure.
**Needed**: A `analyze-prd` command that:
1. Reads a PRD markdown file
2. Extracts features, epics, acceptance criteria
3. Suggests a graph structure (nodes, edges, validation gates)
4. Returns the analysis as structured data the LLM can act on

```bash
attractor analyze-prd <prd-file.md> --output suggestions.json
```

**Why it matters**: The "data-driven from codebase analysis through execution to validation" vision requires the pipeline to be informed by the PRD, not just by existing beads. The LLM should be able to say "given this PRD, what should the graph look like?" and get a structured starting point.

### Gap 5: No Semantic Validation

**Current**: `validate` checks structural rules (exactly one start/exit, AT pairing, no orphans, etc.)
**Needed**: Semantic validation that checks:
- Does every PRD epic have at least one codergen node?
- Do all acceptance criteria have corresponding validation gates?
- Are there unreachable nodes from any valid execution path?
- Does the graph's dependency order make architectural sense? (e.g., backend before frontend)

```bash
attractor validate <file.dot> --semantic --prd <prd-file.md>
```

**Why it matters**: Structural validity doesn't guarantee the graph implements the right thing. The LLM needs feedback like "PRD epic 3 has no corresponding nodes" or "AC-4 has no validation gate."

### Gap 6: No Graph Diff/Compare Tool

**Current**: No way to compare two versions of a graph.
**Needed**:

```bash
attractor diff <old.dot> <new.dot> [--json]
# Output: nodes added/removed/modified, edges added/removed, status changes
```

**Why it matters**: During iterative refinement, the LLM needs to understand what changed between versions. This also enables checkpoint-based rollback decisions ("should I revert to the last checkpoint?").

### Gap 7: No Explain/Suggest Commands

**Current**: Tools are imperative (do X). No tools for reasoning about the graph.
**Needed**:

```bash
# What would happen if I transition this node?
attractor explain <file.dot> <node_id>
# Output: upstream dependencies, downstream effects, cascade predictions

# What should I do next?
attractor suggest <file.dot>
# Output: recommended next actions based on current state
```

**Why it matters**: These are the "System 2 thinking" tools that help the LLM make better decisions. Without them, the LLM must mentally simulate the graph to predict transition effects.

### Gap 8: No Iterative Refinement Workflow

**Current**: The workflow is: generate → validate → execute. No loop back to refine.
**Needed**: A documented and tool-supported refinement loop:

```
generate --scaffold → LLM reviews → node add/remove/modify → edge add/remove →
validate (structural) → validate --semantic → LLM reviews feedback →
adjust → validate again → checkpoint save → proceed to execution
```

**Why it matters**: This is the core of the collaborative vision. The current tools support a linear pipeline; the vision requires an iterative design loop.

### Gap 9: Parallel Dispatch Lacks Locking

**Current**: System 3 output style describes parallel dispatch conceptually, but no locking prevents two sessions from dispatching the same node.
**Needed**: File-based or beads-based locking:

```bash
attractor lock <file.dot> <node_id> --session <session_id>
attractor unlock <file.dot> <node_id>
```

Or integrated into `transition`:
```bash
attractor transition <file.dot> <node_id> active --lock --session <session_id>
# Fails if node is already locked by another session
```

### Gap 10: No ZeroRepo Integration Point

**Current**: `generate` reads from beads. ZeroRepo generates codebase analysis graphs.
**Needed**: A bridge that:
1. ZeroRepo analyzes the codebase and produces a structural understanding
2. This understanding informs the scaffold generation (e.g., "these modules exist, these dependencies exist")
3. The LLM uses both the PRD and the codebase analysis to design the implementation graph

---

## 4. Proposed 3-Step Collaborative Workflow

### Step 1: Auto-Generate Scaffold

```
PRD document
    + beads data (existing tasks)
    + ZeroRepo codebase analysis (optional)
    ↓
attractor generate --scaffold --prd PRD-XXX.md [--zerorepo analysis.json]
    ↓
scaffold.dot (minimal graph: start, epic groups, exit)
```

The scaffold contains:
- Start and exit nodes
- One group per PRD epic (with a placeholder codergen node)
- Sequential edges between groups (conservative default)
- No validation gates (LLM decides where they go)
- No conditional routing (LLM designs the branching)

### Step 2: LLM Review and Refinement

```
LLM receives scaffold.dot
    ↓
attractor parse scaffold.dot --json        # Understand structure
attractor analyze-prd PRD-XXX.md           # Get PRD-informed suggestions
    ↓
LLM decisions:
    attractor node add ...                 # Add implementation nodes
    attractor node add ... --handler wait.human  # Add validation gates
    attractor edge add ...                 # Define dependencies
    attractor edge remove ...              # Remove conservative defaults
    ↓
attractor validate pipeline.dot            # Structural check
attractor validate --semantic --prd ...    # Semantic check
    ↓
If issues: LLM adjusts and re-validates
If clean: attractor checkpoint save       # Lock in the design
```

### Step 3: Execution with Programmatic Enforcement

```
System 3 reads the validated, LLM-refined pipeline.dot
    ↓
DOT Graph Navigation loop (existing):
    status → identify ready nodes → dispatch → monitor → validate → loop
    ↓
Enforcement:
    - transition validates pre-conditions programmatically
    - check-finalize-gate blocks premature closure
    - checkpoint saves after every transition
    - annotate syncs with beads continuously
```

---

## 5. Priority Ranking

| Gap | Priority | Effort | Rationale |
|-----|----------|--------|-----------|
| Gap 2: Node CRUD | P0 | Medium | Fundamental — LLM can't modify graph without this |
| Gap 3: Edge CRUD | P0 | Medium | Fundamental — LLM can't design dependencies without this |
| Gap 1: Scaffold mode | P1 | Low | Enhances generate, but LLM could work from full graph |
| Gap 5: Semantic validation | P1 | High | Critical for "did we implement the right thing?" |
| Gap 8: Refinement workflow | P1 | Low | Documentation + integration, tools from Gaps 1-3 |
| Gap 4: PRD analysis | P2 | High | Valuable but LLM can read PRD directly |
| Gap 7: Explain/Suggest | P2 | Medium | Helpful but LLM can reason from parse output |
| Gap 6: Diff/Compare | P3 | Low | Nice-to-have for iterative refinement |
| Gap 9: Parallel locking | P3 | Low | Edge case, single-orchestrator sessions are common |
| Gap 10: ZeroRepo bridge | P3 | Medium | Future integration, not blocking |

---

## 6. Implementation Recommendation

### Phase 1: Graph Manipulation Foundation (Gaps 1, 2, 3)
Add node and edge CRUD to `cli.py`. Add `--scaffold` mode to `generate`. This gives the LLM the minimum tools to iterate on a graph.

### Phase 2: Validation Enhancement (Gap 5, partial Gap 4)
Add `--semantic --prd` flag to `validate`. Implement PRD coverage checking (every epic has nodes, every AC has a gate).

### Phase 3: Refinement UX (Gaps 6, 7, 8)
Add `diff`, `explain`, `suggest` commands. Document the iterative refinement workflow. This is the "polish" that makes the collaborative loop smooth.

### Phase 4: Integration (Gaps 9, 10)
Add locking for parallel dispatch. Bridge ZeroRepo codebase analysis into scaffold generation.

---

## 7. User Feedback Integration

> "data-driven from codebase analysis through execution to validation"

This maps to: ZeroRepo (codebase analysis) → generate scaffold → LLM refines → execute → validate.
Currently missing: the middle step (LLM refines) has no tools.

> "we need a LLM to drive or at least be in a position to review and significantly adjust the generated pipeline"

This maps to: Gaps 2, 3 (node/edge CRUD) + Gap 8 (refinement workflow).
The LLM needs write access to the graph, not just read access.

> "provide the CLI tools necessary for the LLM to then carefully analyse the PRD it was asked to implement and complete the graph"

This maps to: Gaps 4 (PRD analysis), 5 (semantic validation), 7 (explain/suggest).
The LLM needs analytical tools, not just manipulation tools.

---

## 8. Relationship to PRD-S3-ATTRACTOR-002

The official Attractor spec gap analysis (promise-cc617ee2) identified that our implementation diverges from strongdm/attractor in several areas. This document focuses on a different dimension: not "are we spec-compliant?" but "can the LLM collaborate with the tools?"

PRD-S3-ATTRACTOR-002 should incorporate BOTH:
1. Spec compliance gaps (from cc617ee2 analysis)
2. LLM collaboration gaps (from this analysis)

The execution engine design (ATTRACTOR-002 Workstream 3) is the natural home for the collaborative workflow specification.

---

**End of Gap Analysis**
