---
title: "ZeroRepo (RPG) Paper Summary"
status: active
type: reference
last_verified: 2026-02-27
grade: reference
---

# RPG: A Repository Planning Graph for Unified and Scalable Codebase Generation

**Paper**: arXiv:2509.16198v5 (Oct 2025)
**Authors**: Microsoft Research, Tsinghua University, UC San Diego
**Local PDF**: `docs/research/rpg-zerorepo-paper.pdf`

## Core Insight

LLM-based code generation struggles with repository-level codebases because it lacks a structured representation of the codebase's architecture. RPG solves this by constructing a **Repository Planning Graph** — a directed graph encoding capabilities, file structures, data flows, and function relationships — then using this graph to guide code generation in a structured, dependency-aware order.

## The Three Stages

### Stage 1: Proposal-Level Construction

Builds a high-level capability graph from a natural language requirement:

1. **Feature Extraction**: Uses an "Explore-Exploit" algorithm inspired by EpiCoder's 1.5M-feature ontology with diversity-aware rejection sampling. Features are tagged with categories and difficulty levels.
2. **Feature Subtree Selection**: Builds a feature tree (root = repo concept, leaves = atomic features). Uses confidence-based selection — each feature gets a confidence score, and subtrees below a threshold are rejected.
3. **Graph Construction**: Converts the feature tree into an RPG with `CAPABILITY` nodes linked by `DEPEND` edges. Each capability maps to user-facing functionality.

### Stage 2: Implementation-Level Construction

Enriches the capability graph with concrete implementation details through 5 sequential encoders:

| Encoder | Purpose | Node Types Added |
|---------|---------|-----------------|
| **FolderEncoder** | Directory structure | `FOLDER` nodes |
| **FileEncoder** | File-level decomposition | `FILE` nodes with file paths |
| **DataFlowEncoder** | Cross-file data dependencies | `DATA_FLOW` edges between files |
| **IntraModuleOrderEncoder** | Within-file function ordering | `FUNCTION` nodes with execution order |
| **BaseClassEncoder** | Inheritance and class hierarchies | `CLASS` nodes with inheritance edges |

Plus a 6th LLM-powered encoder:
- **InterfaceDesignEncoder**: Generates function signatures, docstrings, and type hints for each function node. This is the most expensive step but critical for cross-file consistency.

### Stage 3: Graph-Guided Code Generation

Generates actual code file-by-file, guided by the RPG:

1. **Topological Sort**: Files are ordered by dependency (most depended-on first).
2. **Context Window**: Each file generation receives:
   - Its function signatures and docstrings (from Stage 2)
   - Already-generated dependency files (as context)
   - The overall folder structure
3. **Incremental Generation**: Files are generated one at a time, each building on previously generated files.

## Key Results

| Metric | RPG | Claude Code (baseline) | Improvement |
|--------|-----|----------------------|-------------|
| **Coverage** | 81.5% | 54.2% | +50.4% |
| **Test Pass Rate** | 69.7% | 33.9% | +105.6% |
| **Avg LOC/Repo** | ~36,000 | ~9,200 | ~3.9x larger |
| **Files/Repo** | ~120 | ~35 | ~3.4x more |

Evaluated on **SWE-Bench-M** (repository-level generation benchmark) and **DevBench**.

## Delta Classification (Our Extension)

Our ZeroRepo implementation extends RPG with delta classification for iterative development:

| Status | Meaning | Action |
|--------|---------|--------|
| `EXISTING` | Unchanged from baseline | Skip (no code generation needed) |
| `MODIFIED` | Changed since baseline | Scoped regeneration of affected functions |
| `NEW` | Not in baseline | Full implementation required |

This enables **incremental updates** rather than full regeneration — critical for real-world development where codebases evolve over time.

## Architectural Insights for Our Integration

### Why RPG Matters for Solution Design

1. **Dependency-aware ordering**: RPG's topological sort ensures files are generated/modified in the right order. This directly maps to our DOT pipeline's node ordering.
2. **Cross-file consistency**: The InterfaceDesignEncoder ensures function signatures match across files. This is exactly what our orchestrators need when delegating to multiple workers.
3. **Structured context**: Rather than dumping entire codebases into context windows, RPG provides focused, relevant context per file. This maps to our `file_scope` and `solution_design` attributes on DOT nodes.

### Key Differences from Our Current Pipeline

| RPG Paper | Our Current Pipeline | Gap |
|-----------|---------------------|-----|
| Feature tree from scratch | PRD/SD from human + LLM | We have richer business context |
| 5 sequential encoders | Serena MCP (LSP-based) | Serena is faster but less structured |
| Full repo generation | Incremental delta updates | We're ahead on this |
| Single codebase | Multi-repo (--target_dir) | We need cross-repo support |
| No baseline tracking | ZeroRepo baseline + diff | We're ahead on this |

### The Explore-Exploit Algorithm

RPG's feature selection uses a bandit-like algorithm:
- **Explore**: Sample diverse features from the ontology
- **Exploit**: Select features with high confidence of being implementable
- **Rejection sampling**: Discard feature subtrees below a confidence threshold

This is analogous to our Task Master's task decomposition but more structured — it ensures coverage of the problem space before committing to implementation.

## Limitations Noted in Paper

1. **Cost**: Full RPG construction for a 36K LOC repo costs ~$2-5 in LLM API calls
2. **Latency**: Stage 2 enrichment takes 5-15 minutes per repo
3. **Single-shot**: No iterative refinement after code generation
4. **Python-focused**: Evaluated primarily on Python repos (SWE-Bench-M)
5. **No runtime validation**: Generated code isn't tested during construction

## References

- Full paper: `docs/research/rpg-zerorepo-paper.pdf`
- Our implementation: `src/zerorepo/` (14 sub-modules)
- Delta design: `docs/ZEROREPO_DELTA_DESIGN.md`
- Serena integration: `docs/ZEROREPO_SERENA_DESIGN.md`
