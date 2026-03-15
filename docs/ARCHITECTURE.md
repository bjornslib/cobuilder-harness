---
title: ZeroRepo Architecture
status: active
type: reference
last_verified: 2026-02-08T00:00:00.000Z
---
# ZeroRepo Architecture

## Overview

ZeroRepo is a **Repository Planning Graph (RPG)** system that generates complete
software repositories from natural language descriptions. It transforms a
free-form specification into a richly annotated directed graph of modules,
components, and functions, then uses graph-guided code generation with
test-driven development to produce a working codebase.

The system is organised into five pipeline phases, each corresponding to a
package under `src/zerorepo/`:

```
Phase 1 ──> Phase 2 ──> Phase 3 ──> Phase 4 ──> Phase 5
Foundation   Planning    Enrichment  CodeGen     Evaluation
```

---

## System Architecture Diagram

```
                    ┌──────────────────────────────────────────────────────┐
                    │                   USER INPUT                        │
                    │         Natural Language Description                │
                    └───────────────────────┬──────────────────────────────┘
                                            │
                                            ▼
              ┌─────────────────────────────────────────────────────────────┐
              │                  PHASE 1: FOUNDATION                       │
              │                                                            │
              │  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐    │
              │  │   llm    │  │   vectordb   │  │     sandbox       │    │
              │  │ Gateway  │  │ ChromaDB     │  │  Docker           │    │
              │  │ (LiteLLM)│  │ Store        │  │  Executor         │    │
              │  └─────┬────┘  └──────┬───────┘  └────────┬──────────┘    │
              │        │              │                    │               │
              │  ┌─────┴────┐  ┌──────┴───────┐  ┌────────┴──────────┐    │
              │  │  serena  │  │  models/     │  │      cli          │    │
              │  │  MCP     │  │  RPGNode     │  │  Typer + Rich     │    │
              │  │  Server  │  │  RPGEdge     │  │                   │    │
              │  └──────────┘  │  RPGGraph    │  └───────────────────┘    │
              │                └──────────────┘                           │
              └─────────────────────────────────────────────────────────────┘
                                            │
                                            ▼
              ┌─────────────────────────────────────────────────────────────┐
              │                  PHASE 2: PLANNING                         │
              │                                                            │
              │  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐  │
              │  │ spec_parser  │──▶│  ontology     │──▶│  selection    │  │
              │  │              │   │               │   │               │  │
              │  │ NL → Spec    │   │ Feature Tree  │   │ Explore-     │  │
              │  │ SpecParser   │   │ OntologyServ. │   │ Exploit Loop │  │
              │  │ ConflictDet. │   │ FeatureNode   │   │ Diversity    │  │
              │  │ SpecRefiner  │   │ ChromaStore   │   │ Sampling     │  │
              │  └──────────────┘   └──────────────┘   └──────┬────────┘  │
              │                                                │          │
              │                     ┌──────────────────────────┘          │
              │                     ▼                                     │
              │              ┌──────────────────┐                         │
              │              │graph_construction │                         │
              │              │                   │                         │
              │              │ Partitioner       │                         │
              │              │ DependencyInfer.  │                         │
              │              │ GraphBuilder      │                         │
              │              │ Metrics (Q-score) │                         │
              │              │ Refinement        │                         │
              │              │ GraphExporter     │                         │
              │              └────────┬──────────┘                         │
              └───────────────────────┼────────────────────────────────────┘
                                      │
                                      ▼
              ┌─────────────────────────────────────────────────────────────┐
              │                  PHASE 3: ENRICHMENT                       │
              │                                                            │
              │  ┌──────────────────┐     ┌─────────────────────────────┐  │
              │  │ rpg_enrichment   │     │       graph_ops             │  │
              │  │                  │     │                             │  │
              │  │ RPGBuilder       │     │ topological_sort            │  │
              │  │  (Pipeline)      │     │ detect_cycles               │  │
              │  │ RPGEncoder (ABC) │     │ filter_nodes                │  │
              │  │ FolderEncoder    │     │ extract_subgraph_by_*       │  │
              │  │ FileEncoder      │     │ get_ancestors/descendants   │  │
              │  │ InterfaceDesign  │     │ diff_dependencies           │  │
              │  │ DataFlowEncoder  │     │ serialize/deserialize       │  │
              │  │ BaseClassEncoder │     │                             │  │
              │  │ OrderingEncoder  │     └─────────────────────────────┘  │
              │  │ SerenaValidator  │                                      │
              │  └──────────────────┘                                      │
              └─────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
              ┌─────────────────────────────────────────────────────────────┐
              │                  PHASE 4: CODE GENERATION                  │
              │                                                            │
              │  ┌──────────────────────────────────────────────────────┐  │
              │  │                codegen                                │  │
              │  │                                                      │  │
              │  │  CodegenOrchestrator ──▶ TraversalEngine              │  │
              │  │        │                    (topological order)       │  │
              │  │        ▼                                             │  │
              │  │  LocalizationOrchestrator ──▶ RPGFuzzySearch          │  │
              │  │        │                     DependencyExplorer       │  │
              │  │        ▼                                             │  │
              │  │    TDDLoop ──▶ LLMImplementationGenerator            │  │
              │  │        │      DockerSandboxExecutor                  │  │
              │  │        │      MajorityVoteDiagnoser                  │  │
              │  │        ▼                                             │  │
              │  │  UnitValidator ──▶ RegressionDetector                 │  │
              │  │  IntegrationGenerator ──▶ MajorityVoter              │  │
              │  │  TestArtifactStore                                   │  │
              │  │        │                                             │  │
              │  │        ▼                                             │  │
              │  │  Repository Assembly                                 │  │
              │  │   build_file_map / create_directory_structure         │  │
              │  │   resolve_imports / detect_circular_imports           │  │
              │  │   render_pyproject_toml / generate_readme             │  │
              │  │   build_coverage_report / export_rpg_artifact         │  │
              │  └──────────────────────────────────────────────────────┘  │
              └─────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
              ┌─────────────────────────────────────────────────────────────┐
              │                  PHASE 5: EVALUATION                       │
              │                                                            │
              │  ┌──────────────────────────────────────────────────────┐  │
              │  │               evaluation                             │  │
              │  │                                                      │  │
              │  │  EvaluationPipeline (3-stage):                       │  │
              │  │    Stage 1: FunctionLocalizer (embedding similarity) │  │
              │  │    Stage 2: SemanticValidator (LLM majority voting)  │  │
              │  │    Stage 3: ExecutionTester   (Docker sandbox)       │  │
              │  │                                                      │  │
              │  │  Supporting Services:                                │  │
              │  │    MetricsCalculator   Categorizer                   │  │
              │  │    ProfilingCollector   ReportGenerator               │  │
              │  │    FailureAnalyzer     PromptABTest                  │  │
              │  │    TestFilter          EmbeddingCache                │  │
              │  │    LLMResponseCache    BatchedFunctionGenerator      │  │
              │  └──────────────────────────────────────────────────────┘  │
              └─────────────────────────────────────────────────────────────┘
```

---

## Core Data Model

The heart of ZeroRepo is the **Repository Planning Graph (RPG)** -- a directed
graph where nodes represent planning/implementation units and edges represent
relationships between them.

### RPGNode (`models/node.py`)

Each node represents a unit of planning at one of three hierarchical levels:

```
NodeLevel           Description
─────────           ──────────────────────────────────────
MODULE              Top-level software module
COMPONENT           Sub-module component (folder/file)
FEATURE             Leaf-level function/class/method
```

Nodes are further classified by type, which drives enrichment:

```
NodeType                Description
────────                ──────────────────────────────────────
FUNCTIONALITY           Abstract feature (pre-enrichment)
FOLDER_AUGMENTED        Mapped to a folder path
FILE_AUGMENTED          Mapped to a specific file path
FUNCTION_AUGMENTED      Mapped to a function/class/method
```

Key fields on `RPGNode`:

| Field | Type | Description |
| --- | --- | --- |
| `id` | `UUID` | Unique identifier |
| `name` | `str` | Human-readable name (1-200 chars) |
| `level` | `NodeLevel` | MODULE / COMPONENT / FEATURE |
| `node_type` | `NodeType` | FUNCTIONALITY through FUNCTION_AUGMENTED |
| `parent_id` | `UUID?` | Parent node in the hierarchy |
| `folder_path` | `str?` | Relative folder path |
| `file_path` | `str?` | Relative file path |
| `interface_type` | `InterfaceType?` | FUNCTION / CLASS / METHOD |
| `signature` | `str?` | Python function/method signature |
| `docstring` | `str?` | Documentation string |
| `implementation` | `str?` | Generated Python code |
| `test_code` | `str?` | Generated pytest test code |
| `test_status` | `TestStatus` | PENDING / PASSED / FAILED / SKIPPED |
| `serena_validated` | `bool` | Whether Serena MCP validated this node |
| `actual_dependencies` | `list[UUID]` | Runtime dependencies (from Serena) |
| `metadata` | `dict[str, Any]` | Arbitrary metadata |

Cross-field validation constraints are enforced by Pydantic model validators:
- `file_path` must be a child of `folder_path` when both present
- `signature` is required when `interface_type` is set
- `implementation` cannot be set without `file_path`
- `interface_type` is required when `node_type` is `FUNCTION_AUGMENTED`

### RPGEdge (`models/edge.py`)

Directed edges connect nodes with five relationship types:

```
EdgeType        Direction               Description
────────        ─────────               ──────────────────────────────
HIERARCHY       parent → child          Module containment
DATA_FLOW       producer → consumer     Data passes between nodes
ORDERING        before → after          Execution/build ordering
INHERITANCE     child → parent class    Class hierarchy
INVOCATION      caller → callee         Function call relationship
```

Key fields on `RPGEdge`:

| Field | Type | Description |
| --- | --- | --- |
| `id` | `UUID` | Unique identifier |
| `source_id` | `UUID` | Source node UUID |
| `target_id` | `UUID` | Target node UUID (must differ from source) |
| `edge_type` | `EdgeType` | Relationship type |
| `data_id` | `str?` | Data identifier (DATA_FLOW only) |
| `data_type` | `str?` | Type annotation (DATA_FLOW only) |
| `transformation` | `str?` | Transform description (DATA_FLOW only) |
| `validated` | `bool` | Whether this edge has been validated |

Constraints: no self-loops; `data_id`/`data_type`/`transformation` only valid
on `DATA_FLOW` edges.

### RPGGraph (`models/graph.py`)

The container that manages all nodes and edges:

```python
class RPGGraph(BaseModel):
    nodes: dict[UUID, RPGNode]     # Indexed by UUID
    edges: dict[UUID, RPGEdge]     # Indexed by UUID
    metadata: dict[str, Any]       # Project name, version, timestamp
```

Key methods:

| Method | Description |
| --- | --- |
| `add_node()` | Add node; raises if duplicate ID |
| `add_edge()` | Add edge; validates both endpoints exist |
| `remove_node()` | Remove node + cascading edge removal |
| `to_json()` | Serialize to JSON string |
| `from_json()` | Deserialize from JSON string (round-trip safe) |

---

## Phase 1: Foundation Infrastructure

### LLM Gateway (`llm/`)

Unified multi-provider LLM interface built on **LiteLLM**:

```
┌──────────────────────────────────────────────────────────┐
│  LLMGateway                                              │
│                                                          │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────┐   │
│  │ LiteLLM  │   │ TokenTracker │   │ PromptTemplate │   │
│  │ complete()│   │ cost estim.  │   │ Jinja2 render  │   │
│  └──────────┘   └──────────────┘   └────────────────┘   │
│                                                          │
│  Tiers: CHEAP / MEDIUM / STRONG                          │
│  Retry: Exponential backoff for rate limits              │
│  Logging: Request/response with truncation               │
└──────────────────────────────────────────────────────────┘
```

- **`LLMGateway`** -- Main class for completions. Routes requests through
  `ModelTier` for cost/quality selection.
- **`TokenTracker`** -- Tracks token usage per request with cost estimation.
- **`PromptTemplate`** -- Jinja2-based prompt rendering.
- **`GatewayConfig`** -- Configuration model (API keys, timeouts, tier maps).

### VectorDB (`vectordb/`)

ChromaDB-backed embedding storage for feature trees:

- **`VectorStore`** -- ChromaDB wrapper with collection management and search.
- **`EmbeddingGenerator`** -- Sentence-transformer embedding generation.
- **`SearchResult`** -- Similarity search result with scores.

### Docker Sandbox (`sandbox/`)

Isolated container environment for code execution:

- **`DockerSandbox`** -- Container lifecycle, code execution, pytest running.
- **`SandboxConfig`** -- Resource limits, timeouts, image selection.
- **`ExecutionResult`** / **`TestResult`** -- Captured output models.

### Serena MCP (`serena/`)

Workspace validation and symbol analysis via Model Context Protocol:

- **`SerenaMCPServer`** -- MCP server lifecycle management.
- **`MCPClient`** -- JSON-RPC client for tool calls.
- **`WorkspaceManager`** -- Workspace initialization and file tracking.
- **`SymbolLookup`** -- Symbol search and overview.
- **`PyrightConfigurator`** -- Pyright configuration generation.
- **`DependencyExtractor`** -- Code dependency extraction.

### CLI (`cli/`)

Command-line interface built with **Typer** and **Rich**:

```
zerorepo
├── init          Initialize a new ZeroRepo project
├── spec          Specification parsing commands
│   ├── parse     Parse natural language → RepositorySpec
│   └── refine    Iteratively refine a specification
└── ontology      Feature ontology commands
    ├── build     Build ontology from specification
    └── search    Search the feature tree
```

Global options: `--version`, `--verbose`, `--config <path.toml>`.

---

## Phase 2: Planning Pipeline

### Spec Parser (`spec_parser/`)

Converts natural language descriptions into structured `RepositorySpec`:

```
Natural Language  ──▶  SpecParser  ──▶  RepositorySpec
                       (2-phase)
                         │
                         ├── Phase 1: LLM Extraction → ParsedSpecResponse
                         └── Phase 2: Assembly → RepositorySpec
```

Key classes:

| Class | Role |
| --- | --- |
| `SpecParser` | LLM-based NL parser (extraction + assembly) |
| `ConflictDetector` | Detects contradictions between requirements |
| `SpecRefiner` | Iterative spec improvement with LLM suggestions |
| `ReferenceProcessor` | Extracts concepts from URLs, PDFs, code samples |

The `RepositorySpec` model includes:
- `TechnicalRequirement` -- languages, frameworks, platforms, deployment targets
- `QualityAttributes` -- performance, security, scalability, reliability
- `Constraint` -- prioritized constraints (MUST_HAVE / SHOULD_HAVE / NICE_TO_HAVE)
- `ReferenceMaterial` -- supporting references with extracted concepts

### Feature Ontology (`ontology/`)

Builds a hierarchical feature tree from the repository specification:

```
RepositorySpec  ──▶  OntologyService  ──▶  Feature Tree (ChromaDB)
                         │
                         ├── LLMOntologyBackend (LLM-generated tree)
                         ├── FeatureEmbedder (batch embeddings)
                         ├── OntologyChromaStore (vector storage)
                         └── OntologyExtensionAPI (domain extensions)
```

- **`FeatureNode`** -- A node in the feature ontology tree.
- **`OntologyService`** -- Unified facade for build, search, extend operations.
- **`OntologyBackend`** -- Abstract base for pluggable backends.

### Explore-Exploit Selection (`selection/`)

Selects relevant features from the ontology using an explore-exploit loop:

```
                    ┌─────────────────────────────────────┐
                    │  ExploreExploitOrchestrator          │
                    │                                     │
   Exploitation ──▶ │  ExploitationRetriever              │
   (vector search)  │    ↓                                │
                    │  ExplorationStrategy (coverage gaps) │
   Exploration ──▶  │    ↓                                │
                    │  DiversitySampler (cosine reject.)   │
   Diversity ──▶    │    ↓                                │
                    │  LLMFilter (relevance filtering)    │
   Filtering ──▶    │    ↓                                │
                    │  ConvergenceMonitor (plateau det.)  │
                    │                                     │
                    └─────────────────────────────────────┘
```

Algorithm (from the PRD):
1. For each iteration, run exploitation (vector search with LLM query augmentation)
2. Run exploration (generate queries from uncovered branches)
3. Merge candidates, apply diversity sampling (cosine similarity threshold = 0.85)
4. Every 5 iterations, apply LLM relevance filtering
5. Monitor convergence; break on coverage plateau

### Graph Construction (`graph_construction/`)

Builds the functionality graph from selected features:

```
Selected Features
       │
       ▼
┌──────────────────┐     ┌──────────────────────┐
│ ModulePartitioner │────▶│  Metrics              │
│ (LLM clustering)  │     │  compute_cohesion()   │
└──────────┬───────┘     │  compute_coupling()   │
           │              │  compute_modularity() │
           ▼              └──────────────────────┘
┌──────────────────┐
│DependencyInference│
│ (LLM detection)  │
└──────────┬───────┘
           │
           ▼
┌──────────────────────────┐
│FunctionalityGraphBuilder  │
│  NetworkX graph output    │
│  Export: JSON/GraphML/DOT │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐     ┌──────────────────────────┐
│   GraphRefinement         │────▶│   GraphExporter           │
│   (iterative quality      │     │   JSON / GraphML / DOT    │
│    improvement with undo) │     └──────────────────────────┘
└──────────────────────────┘
```

Metrics include Newman's modularity Q-score, intra-module cohesion,
and inter-module coupling.

---

## Phase 3: RPG Enrichment

### Encoder Pipeline (`rpg_enrichment/`)

The **RPGBuilder** runs a sequential pipeline of `RPGEncoder` stages that
progressively enrich the graph:

```
RPGGraph  ──▶  RPGBuilder.run()
                   │
                   ├── FolderEncoder        Assigns folder_path to MODULE nodes
                   ├── FileEncoder          Assigns file_path to COMPONENT nodes
                   ├── InterfaceDesignEncoder  Designs function signatures
                   ├── DataFlowEncoder      Adds DATA_FLOW edges
                   ├── BaseClassEncoder     Adds INHERITANCE edges
                   ├── IntraModuleOrderEncoder  Adds ORDERING edges
                   └── SerenaValidator      Validates via Serena MCP
                   │
                   ▼
            Enriched RPGGraph
```

Each encoder implements the `RPGEncoder` abstract base class:

```python
class RPGEncoder(ABC):
    @abstractmethod
    def encode(self, graph: RPGGraph) -> RPGGraph: ...

    @abstractmethod
    def validate(self, graph: RPGGraph) -> ValidationResult: ...
```

The builder records timing and validation results for each step via
`EncoderStep` metadata, enabling pipeline observability.

### Graph Operations (`graph_ops/`)

Pure-function utilities for graph analysis and manipulation:

| Module | Functions |
| --- | --- |
| `topological.py` | `topological_sort()`, `detect_cycles()` |
| `traversal.py` | `get_ancestors()`, `get_descendants()`, `get_direct_dependencies()` |
| `subgraph.py` | `extract_subgraph_by_level()`, `..._by_module()`, `..._by_type()` |
| `filtering.py` | `filter_nodes()`, `filter_by_level()`, `..._by_status()`, `..._by_validation()` |
| `diff.py` | `diff_dependencies()` -- Compare planned vs actual deps |
| `serialization.py` | `serialize_graph()` / `deserialize_graph()` (JSON files) |
| `exceptions.py` | `CycleDetectedError` |

Topological sort uses **Kahn's algorithm** considering HIERARCHY and DATA_FLOW
edges for ordering.

---

## Phase 4: Code Generation

### CodegenOrchestrator (`codegen/codegen_orchestrator.py`)

The main orchestrator coordinates the full code generation pipeline:

```
┌──────────────────────────────────────────────────────────────────┐
│  CodegenOrchestrator                                             │
│                                                                  │
│  1. TraversalEngine ──▶ Topological order of FUNCTION_AUGMENTED  │
│                          nodes with failure propagation           │
│                                                                  │
│  2. For each node in order:                                      │
│     ┌──────────────────────────────────────────────────────────┐ │
│     │  LocalizationOrchestrator                                │ │
│     │    RPGFuzzySearch (embedding search over RPG nodes)      │ │
│     │    RepositoryCodeView (source reading + AST)             │ │
│     │    DependencyExplorer (N-hop neighbourhood)              │ │
│     │    LocalizationTracker (query dedup)                     │ │
│     └──────────────────────────┬───────────────────────────────┘ │
│                                │ context                         │
│                                ▼                                 │
│     ┌──────────────────────────────────────────────────────────┐ │
│     │  TDDLoop (up to max_retries iterations)                  │ │
│     │    1. Generate tests (TestGenerator protocol)            │ │
│     │    2. Generate impl  (ImplementationGenerator protocol)  │ │
│     │    3. Run in sandbox (SandboxExecutor protocol)          │ │
│     │    4. On failure: diagnose (MajorityVoteDiagnoser)       │ │
│     │    5. Repeat until PASSED or retries exhausted           │ │
│     └──────────────────────────┬───────────────────────────────┘ │
│                                │                                 │
│                                ▼                                 │
│     ┌──────────────────────────────────────────────────────────┐ │
│     │  Staged Validation                                       │ │
│     │    UnitValidator (per-node test verification)            │ │
│     │    RegressionDetector (cross-iteration comparison)       │ │
│     │    IntegrationGenerator (cross-node integration tests)   │ │
│     │    MajorityVoter (consensus on test outcomes)            │ │
│     │    TestArtifactStore (artifact lifecycle)                │ │
│     └──────────────────────────────────────────────────────────┘ │
│                                                                  │
│  3. Repository Assembly                                          │
│     build_file_map ──▶ create_directory_structure                │
│     resolve_imports ──▶ detect_circular_imports                   │
│     render_pyproject_toml / render_setup_py                      │
│     generate_readme / render_requirements_txt                    │
│     build_coverage_report / export_rpg_artifact                  │
│                                                                  │
│  4. Workspace Management                                         │
│     SerenaEditor (structural edits via MCP)                      │
│     BatchedFileWriter (atomic writes)                            │
│     SerenaReindexer (LSP re-indexing)                            │
│     RepositoryStateManager (file state tracking)                 │
│     ProgressLogger (ETA display)                                 │
│     GracefulShutdownHandler (SIGINT/SIGTERM)                     │
│     CheckpointManager (save/restore generation state)            │
└──────────────────────────────────────────────────────────────────┘
```

### TDD Loop Detail

The TDD loop implements test-driven development at the node level:

```
          ┌─────────────┐
          │ RPGNode      │
          └──────┬──────┘
                 │
                 ▼
         Generate Tests ◄──── TestGenerator (Protocol)
                 │
                 ▼
      Generate Implementation ◄──── ImplementationGenerator (Protocol)
                 │
                 ▼
        Run in Sandbox ◄──── SandboxExecutor (Protocol)
                 │
            ┌────┴────┐
            │         │
          PASS      FAIL
            │         │
            ▼         ▼
         Mark      Diagnose ◄──── MajorityVoteDiagnoser
        PASSED        │
                      ▼
                 Retry (up to max_retries=8)
                      │
                  Exhausted?
                      │
                      ▼
                  Mark FAILED
                  Skip downstream nodes
```

The pluggable protocol pattern allows different implementations of test
generation, code generation, and sandbox execution to be swapped in.

---

## Phase 5: Evaluation

### EvaluationPipeline (`evaluation/pipeline.py`)

Three-stage evaluation against the RepoCraft benchmark:

```
Generated Repository
       │
       ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 1: Localization (FunctionLocalizer)               │
│  Embedding similarity to find matching functions         │
│  Output: Ranked candidate functions                      │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 2: Semantic Validation (SemanticValidator)        │
│  LLM majority voting on correctness                      │
│  Output: Validated function match                        │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Stage 3: Execution Testing (ExecutionTester)            │
│  Docker sandbox execution of benchmark tests             │
│  Output: Pass/fail + execution result                    │
└──────────────────────────────────────────────────────────┘
```

Supporting services:
- **MetricsCalculator** -- Computes evaluation metrics
- **Categorizer** -- Groups results by taxonomy
- **ProfilingCollector** -- Collects timing/resource data
- **ReportGenerator** -- Produces evaluation reports
- **FailureAnalyzer** / **PromptABTest** -- Failure analysis and prompt A/B testing
- **TestFilter** -- Filters tests by criteria
- **EmbeddingCache** / **LLMResponseCache** -- Caching for efficiency
- **BatchedFunctionGenerator** -- Batched embedding computation

---

## Module Dependency Graph

```
                         ┌──────────┐
                         │  models  │  (no dependencies)
                         └────┬─────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
        ┌──────────┐   ┌───────────┐   ┌──────────┐
        │graph_ops │   │    llm    │   │ vectordb │
        └────┬─────┘   └─────┬─────┘   └────┬─────┘
             │                │               │
             │          ┌─────┼───────────────┘
             │          │     │
             ▼          ▼     ▼
        ┌───────────────────────────┐
        │       spec_parser         │
        └──────────┬────────────────┘
                   │
                   ▼
        ┌───────────────────────────┐
        │        ontology           │ ← llm, vectordb
        └──────────┬────────────────┘
                   │
                   ▼
        ┌───────────────────────────┐
        │       selection           │ ← ontology, llm
        └──────────┬────────────────┘
                   │
                   ▼
        ┌───────────────────────────┐
        │   graph_construction      │ ← ontology, llm, selection
        └──────────┬────────────────┘
                   │
                   ▼
        ┌───────────────────────────┐
        │    rpg_enrichment         │ ← models, graph_ops, serena
        └──────────┬────────────────┘
                   │
                   ▼
        ┌───────────────────────────┐
        │        codegen            │ ← ALL above + sandbox
        └──────────┬────────────────┘
                   │
                   ▼
        ┌───────────────────────────┐
        │      evaluation           │ ← codegen, sandbox, llm, vectordb
        └───────────────────────────┘

        ┌───────────────────────────┐
        │          cli              │ ← spec_parser, ontology, config
        └───────────────────────────┘

        ┌───────────────────────────┐
        │        serena             │  (standalone MCP client)
        └───────────────────────────┘

        ┌───────────────────────────┐
        │        sandbox            │  (standalone Docker wrapper)
        └───────────────────────────┘
```

---

## Key Design Patterns

### 1. Pydantic-First Data Modelling

All data models use **Pydantic v2** `BaseModel` with:
- `ConfigDict(frozen=False, validate_assignment=True)` for mutable but validated models
- `field_validator` and `model_validator` for cross-field constraints
- Full JSON serialization/deserialization round-trip support
- Comprehensive type hints with `Optional` and `list` annotations

### 2. Protocol-Based Pluggability

The TDD loop uses Python `Protocol` classes for pluggable components:

```python
class TestGenerator(Protocol):
    def generate_tests(self, node: RPGNode, context: dict) -> str: ...

class ImplementationGenerator(Protocol):
    def generate_implementation(self, node: RPGNode, test_code: str, context: dict) -> str: ...

class SandboxExecutor(Protocol):
    def run_tests(self, implementation: str, test_code: str, node: RPGNode) -> SandboxResult: ...
```

This allows swapping implementations (e.g., Docker vs in-process sandbox)
without modifying the orchestration logic.

### 3. Pipeline Composition

The RPG enrichment pipeline uses the **Builder pattern**:

```python
builder = RPGBuilder(validate_after_each=True)
builder.add_encoder(FolderEncoder())
builder.add_encoder(FileEncoder())
builder.add_encoder(InterfaceDesignEncoder())
enriched_graph = builder.run(graph)
```

Each encoder implements `RPGEncoder(ABC)` with `encode()` and `validate()`
methods, providing a clean separation of enrichment concerns.

### 4. LLM Gateway Abstraction

All LLM interactions go through the `LLMGateway` which provides:
- Multi-provider routing via LiteLLM
- Tiered model selection (CHEAP / MEDIUM / STRONG)
- Automatic retry with exponential backoff
- Token usage tracking with cost estimation
- Jinja2 prompt template management

### 5. Graph-Guided Traversal

Code generation follows the graph's topological order:
- Kahn's algorithm computes a deterministic traversal order
- Failure propagation skips downstream nodes when a dependency fails
- Checkpointing enables resume after interruption
- Graceful shutdown handles SIGINT/SIGTERM

---

## Technology Stack

| Layer | Technology |
| --- | --- |
| Language | Python 3.11+ |
| Data Validation | Pydantic v2 |
| LLM Integration | LiteLLM (multi-provider) |
| Prompt Templates | Jinja2 |
| Vector Database | ChromaDB + sentence-transformers |
| Graph Library | NetworkX (graph_construction) |
| Container Runtime | Docker SDK for Python |
| Code Analysis | Serena MCP (Pyright-based) |
| CLI Framework | Typer + Rich |
| Testing | pytest + pytest-cov + pytest-mock |
| Build System | Hatchling |

---

## Configuration

ZeroRepo uses a layered configuration approach:

1. **`pyproject.toml`** -- Project metadata and dependencies
2. **`.zerorepo/`** -- Project-local configuration directory (created by `zerorepo init`)
3. **TOML config file** -- Optional config file passed via `--config`
4. **`ZeroRepoConfig`** -- Pydantic model loaded by `cli/config.py`

Each pipeline stage has its own `*Config` Pydantic model:
- `ParserConfig` -- Model selection, template, max length
- `LLMBackendConfig` -- Ontology generation parameters
- `OrchestratorConfig` (selection) -- Iteration limits, thresholds
- `BuilderConfig` -- Partitioning, dependency, metrics settings
- `OrchestratorConfig` (codegen) -- Retry limits, checkpointing
- `GatewayConfig` -- API keys, timeouts, tier mappings
- `SandboxConfig` -- Resource limits, Docker image selection

---

## Delta Classification System

When running with a **baseline** (a previously generated RPG graph), ZeroRepo classifies
every component in the new graph as one of three delta statuses relative to the baseline.
This enables incremental repository planning -- identifying what already exists, what
changed, and what is entirely new.

### DeltaClassification Enum (`models/node.py`)

```
DeltaClassification    Description
──────────────────     ──────────────────────────────────────────
EXISTING               Component exists in the baseline, unchanged
MODIFIED               Component exists in the baseline but has changed
NEW                    Component does not exist in the baseline
```

### Component Model Delta Fields

Three fields on `RPGNode` (at the `COMPONENT` level and below) support delta tracking:

| Field | Type | Description |
| --- | --- | --- |
| `delta_status` | `DeltaClassification?` | The classified delta status (EXISTING/MODIFIED/NEW) |
| `baseline_match_name` | `str?` | Name of the matched node in the baseline graph |
| `change_summary` | `str?` | Human-readable summary of what changed (for MODIFIED) |

### How Delta Classification Works

The classification pipeline has four stages:

#### 1. Baseline Context Injection (`spec_parser/parser.py`)

The `_build_baseline_context()` method (lines 419-487) extracts all MODULE, COMPONENT,
and FEATURE nodes from the baseline `RPGGraph` and formats them hierarchically:

```
Module: auth_module
  Folder: src/auth/
  Components:
    - jwt_handler (src/auth/jwt_handler.py)
      Docstring: "Handles JWT token creation and validation"
      Features:
        - create_token(user_id: str, expiry: int) -> str
        - validate_token(token: str) -> dict
```

This context is injected into the LLM prompt so the model can compare new components
against the existing baseline.

#### 2. Jinja2 Template Conditional Block (`llm/templates/spec_parsing.jinja2`)

When `has_baseline=True`, the template (lines 101-121) adds a "Baseline-Aware Delta
Classification" instruction block that tells the LLM to:

- Compare each component against the baseline listing
- Classify as `existing`, `modified`, or `new`
- Provide the exact `baseline_match_name` for existing/modified components
- Write a `change_summary` for modified components

#### 3. LLM Response Processing (`graph_construction/converter.py`)

The `_tag_delta_status_from_llm()` method (lines 626-700) processes each component
with a three-priority classification strategy:

```
Priority (a): LLM delta_status field
  └── If the LLM explicitly set delta_status → use it directly

Priority (b): baseline_match_name field
  └── If the LLM provided baseline_match_name → find the baseline node
      └── Copy enrichment data (folder_path, signatures, docstrings)

Priority (c): Fallback name matching
  └── Fuzzy-match component name against baseline node names
      └── If match found → classify as EXISTING or MODIFIED
      └── If no match → classify as NEW
```

This priority ordering ensures the LLM's classification is preferred when available,
with deterministic fallbacks for robustness.

#### 4. Delta Report Generation (`serena/delta_report.py`)

The `DeltaReportGenerator` produces `05-delta-report.md` with:

- **Summary counts**: Total EXISTING, MODIFIED, and NEW components
- **Per-level breakdown**: Counts at MODULE, COMPONENT, and FEATURE levels
- **Implementation order**: Recommended order for implementation
  (MODULE > COMPONENT > FEATURE; modified before new)
- **Change details**: Per-component change summaries for MODIFIED items

### The `zerorepo generate` Command

The `zerorepo generate` CLI command runs the full planning pipeline (spec parsing
through graph construction) with optional baseline support:

```bash
# Generate without baseline (all components classified as NEW)
zerorepo generate prd.md --model gpt-4o --output ./output

# Generate with baseline (enables delta classification)
zerorepo generate prd.md --model gpt-4o --output ./output --baseline baseline-graph.json

# Skip enrichment stage (faster, planning-only)
zerorepo generate prd.md --model gpt-4o --output ./output --skip-enrichment
```

When `--baseline` is provided, the pipeline:
1. Loads the baseline RPG graph from the JSON file
2. Builds baseline context via `_build_baseline_context()`
3. Injects context into the LLM prompt via the Jinja2 template
4. Tags delta status on all generated components
5. Produces `05-delta-report.md` alongside the standard outputs
