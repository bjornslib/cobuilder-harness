---
title: "Attractor Community Implementations Research"
status: active
type: reference
last_verified: 2026-02-28
grade: reference
---

# Attractor Community Implementations Research

## Executive Summary

StrongDM's [Attractor](https://github.com/strongdm/attractor) is a spec-only repository (no code, just three markdown files) that defines a non-interactive coding agent for use in a Software Factory. The spec describes how to build a DOT-graph-based pipeline orchestration engine that coordinates LLM calls, tool execution, human approvals, and conditional branching. As of February 2026, the repo has ~780 stars and ~126 forks.

The [StrongDM Software Factory page](https://factory.strongdm.ai/products/attractor) lists **16 community implementations** across 10 languages. This report analyzes the 10 most architecturally interesting implementations, identifies common patterns, and provides recommendations for our Python engine.

---

## 1. Kilroy (Go)

**Repository**: [github.com/danshapiro/kilroy](https://github.com/danshapiro/kilroy)
**Language**: Go
**Author**: Dan Shapiro (StrongDM CEO)

### Architecture

Kilroy is a local-first CLI that converts English-language requirements into Attractor pipelines. The pipeline flow is: Ingest (English to DOT via Claude) -> Validate -> Execute -> Resume.

### Graph Traversal

Deterministic sequential traversal of DOT digraphs with typed nodes. Node shapes (`Mdiamond`, `Msquare`, `box`) determine stage types. Control flow follows edges with optional conditions and retry semantics.

### Handler Dispatch

Pluggable multi-provider backends supporting OpenAI, Anthropic, Google, Kimi, ZAI, Cerebras, and Minimax. Two backend modes: `cli` (local binary invocation) and `api` (remote HTTP). Built-in CLI contracts per provider:

```
OpenAI:    codex exec --json --sandbox workspace-write
Anthropic: claude -p --output-format stream-json
Google:    gemini -p --output-format stream-json --yolo
```

Profile selection via config: `llm.cli_profile` (e.g., `real` vs `test_shim`).

### Checkpoint/Resume

Three-pronged persistence strategy:
- **Git worktree isolation**: Each run executes in a dedicated worktree, preserving main branch
- **Per-node commits**: When `git.commit_per_node=true`, each stage creates a checkpoint commit
- **CXDB timeline**: Typed run events recorded to execution database

Artifacts laid out as `{node_id}/` directories containing prompt, response, status, and CLI/API payloads.

### Event System

Structured events covering run lifecycle (started, finished), stage completion with timestamps, and checkpoint markers linking to git commits and artifact paths. Resume logic replays from checkpoint state.

### Condition Expressions

Runtime evaluation of edge conditions against context variables from prior stage outputs. Retry behavior configurable per edge. Timeout and stall watchdog policies via `runtime_policy`.

### What's Unique

- **Git-native checkpointing** (commits as checkpoints on isolated branches)
- **English-to-DOT ingestion** via Claude with skill-based templates
- **Preflight probing**: health checks against providers before execution
- **Model override**: `--force-model provider=model` for runtime substitution
- **7+ LLM provider support** including non-mainstream providers

---

## 2. brynary's Attractor (TypeScript)

**Repository**: [github.com/brynary/attractor](https://github.com/brynary/attractor)
**Language**: TypeScript
**Author**: Bryan Helmkamp

### Architecture

Three complementary libraries: `attractor/` (pipeline engine), `coding-agent/` (agentic coding loop), `unified-llm/` (LLM client for Anthropic/OpenAI). Includes built-in HTTP server with REST API.

### Graph Traversal

Sequential node execution via `PipelineRunner`. Follows edges based on: handler dispatch by shape -> execution returns `Outcome` -> edge selection via conditions and preferred labels -> checkpoint persistence.

### Handler Dispatch

Standard `Handler` interface:

```typescript
interface Handler {
  execute(node: GraphNode, context: PipelineContext): Promise<Outcome>
}
```

Built-in: `StartHandler`, `ExitHandler`, `CodergenHandler`, `ConditionalHandler`. Custom handlers extend via `HandlerRegistry`.

### Checkpoint/Resume

State saved after every node to `logsRoot` directory as JSON. Crash recovery resumes from last checkpoint without re-executing completed nodes.

### Event System

`PipelineEventEmitter` broadcasts: `STAGE_STARTED`, `PIPELINE_COMPLETED`, plus debugging events. Streams via Server-Sent Events (SSE) for remote monitoring.

### What's Unique

- **HTTP Server Architecture**: Built-in REST API for remote pipeline submission, status polling, and SSE streaming
- **Multi-Backend**: `StubBackend`, `CliAgentBackend`, `SessionBackend` for local CLI agents, APIs, or full agentic sessions
- **Human-in-the-loop**: Keyboard accelerators for terminal interaction at hexagon nodes

---

## 3. samueljklee's Attractor (Python)

**Repository**: [github.com/samueljklee/attractor](https://github.com/samueljklee/attractor)
**Language**: Python
**Author**: Samuel Lee

### Architecture

Vertically-integrated three-layer stack:
1. `attractor_llm/` — Provider abstraction (Anthropic, OpenAI, Gemini, OpenAI-compatible)
2. `attractor_agent/` — Agentic orchestration with tool execution and event streaming
3. `attractor_pipeline/` — DOT-based workflow orchestrator
4. `attractor_server/` — HTTP REST + SSE wrapper

### Graph Traversal

Custom recursive-descent DOT parser (no external libraries). Produces normalized graph with nodes (shape, prompt, system_prompt, class, id) and edges (conditional routing logic).

### Handler Dispatch

Shape-based handler registry with 9 handler types:

| Shape | Handler |
|-------|---------|
| `Mdiamond` | StartHandler |
| `box` | CodergenHandler |
| `diamond` | ConditionalHandler |
| `house` | HumanGateHandler |
| `hexagon` | ManagerHandler |
| `parallelogram` | ToolHandler |
| `component` | ParallelHandler |
| `tripleoctagon` | FanInHandler |
| `Msquare` | ExitHandler |

### Checkpoint/Resume

Context dictionary + checkpoint snapshots + fidelity preamble (reconstructed prompt prefix injecting prior execution history for resumed runs).

### Event System

12 distinct event types streamed via SSE:
`pipeline.started`, `pipeline.completed`, `pipeline.failed`, `interview.started`, `interview.answered`, `node.started`, `node.completed`, `node.failed`, `tool.executed`, `message.sent`

### Condition Evaluation

Expression parser supporting: equality (`outcome = success`), inequality (`status != failed`), logical operators (`&&`, `||`), and context variable interpolation.

### What's Unique

- **Middleware chain** for LLM requests (logging, token counting, caching):
  ```python
  ApplyMiddleware(client, [
      LoggingMiddleware(),
      TokenCountingMiddleware(),
      CachingMiddleware(max_size=100)
  ])
  ```
- **4-level system prompt layering**: provider profile -> pipeline goal -> node instruction -> user override
- **CSS-like model stylesheet**: `* { llm_model: claude-sonnet-4-5; } .critical { llm_model: claude-opus-4-6; }`
- **Subagent depth-limiting** prevents recursive delegation loops
- **Apply-patch v4a parser** for unified diff handling
- **Path confinement + symlink defense** for tool execution security

---

## 4. Forge (Rust)

**Repository**: [github.com/smartcomputer-ai/forge](https://github.com/smartcomputer-ai/forge)
**Language**: Rust

### Architecture

Five layered crates:
- `forge-llm` — Multi-provider LLM client (OpenAI, Anthropic) with deterministic test coverage
- `forge-agent` — Coding-agent loop with autonomous task execution
- `forge-attractor` — DOT pipeline parser and runtime engine
- `forge-cli` — CLI host for execution, resumption, and inspection
- `forge-cxdb-runtime` — Persistence layer with CXDB-first architecture

### Graph Traversal

DAG traversal executing nodes when prerequisites complete. Uses Rust trait objects or enum-based pattern matching for handler dispatch.

### Checkpoint/Resume

JSON checkpoints with explicit resume via CLI:
```bash
cargo run -p forge-cli -- resume \
  --dot-file examples/01-linear-foundation.dot \
  --checkpoint /path/to/checkpoint.json
```

### What's Unique

- **CXDB persistence** (structured context database) rather than ad-hoc file-based state
- **Compile-time correctness** via Rust type system — generics for provider abstraction, `Result<T, E>` for fallible operations
- **Deterministic testing** of core layers without external dependencies
- **CLI-first philosophy**: headless operation with no web UI dependencies

---

## 5. Corey's Attractor (Kotlin)

**Repository**: [github.com/coreydaley/coreys-attractor](https://github.com/coreydaley/coreys-attractor)
**Language**: Kotlin

### Architecture

Kotlin-based orchestration engine with multi-stage workflow support, conditional branching, and an SSE-powered web dashboard at `http://localhost:7070`.

### Graph Traversal

DOT parsing into executable graph structure. Dispatches by node shape: box (LLM), diamond (conditional), hexagon (human review), Mdiamond/Msquare (boundaries).

### Checkpoint/Resume

**SQLite-backed** persistence for resumability. Crashed runs recover from last known state. Artifacts and logs persisted per pipeline execution.

### Event System

Real-time Server-Sent Events stream state changes to a browser UI. Multiple pipelines execute independently with isolated state.

### What's Unique

- **SQLite checkpoint storage** (vs JSON files used by most implementations)
- **Web dashboard** with live concurrent pipeline monitoring
- **Independent pipeline isolation** — multiple pipelines run simultaneously without interference

---

## 6. F#kYeah (F#)

**Repository**: [github.com/TheFellow/fkyeah](https://github.com/TheFellow/fkyeah)
**Language**: F# (.NET 10)

### Architecture

Three main libraries: Attractor (11 modules), UnifiedLlm (10 modules), CodingAgent (9 modules). Ships as a single self-contained binary.

### Handler Dispatch

Leverages F# discriminated unions for node types:

```fsharp
type NodeType = Box | Parallelogram | Hexagon | Diamond | Component | ...
```

Pattern matching for handler dispatch and condition evaluation. Option types for nullable outcomes, Result types for error handling without exceptions.

### Checkpoint/Resume

Writes to `attractor-logs/<timestamp>/`: `manifest.json`, `checkpoint.json`, plus per-node directories with prompts, responses, tool output, and status JSON. Resume via `--resume` flag.

### CSS-like Model Routing

Specificity-based stylesheet system:

```css
* { llm_model: claude-sonnet-4-5; }
.critical { llm_model: claude-opus-4-6; reasoning_effort: high; }
#final_review { llm_model: gpt-5.2; }
```

### What's Unique

- **Discriminated unions + pattern matching** = exhaustive handler dispatch at compile time
- **Loop restart semantics**: `loop_restart=true` edges clear context except graph-level variables
- **Goal gates with retry targets**: critical nodes demand success before exit, failure auto-routes to earlier stage
- **Auto status synthesis**: tool nodes with `auto_status=true` create Success outcomes on clean exit
- **Compound conditions**: `"outcome=success && context.tests=passed"`
- **Pipeline classification**: validator categorizes pipelines as EXECUTION, PLANNING, HYBRID, or ANALYSIS
- **512 tests** (384 unit + 128 black-box conformance)

---

## 7. attractor-scala (Scala)

**Repository**: [github.com/bencivjan/attractor-scala](https://github.com/bencivjan/attractor-scala)
**Language**: Scala 3

### Architecture

Built on **Cats-Effect** (IO monads) and **FS2** (stream processing) for type-safe concurrency and resource safety. Five-stage lifecycle: parse -> transform -> validate -> execute -> checkpoint.

### Edge Selection

Explicit priority rules eliminating ambiguity:
1. Conditional matching
2. Outcome-preferred labels
3. Suggested node IDs from handler results
4. Edge weight values
5. Lexical tie-breaking

### What's Unique

- **IO monads** enforce compile-time guarantees around effect suspension and cancellation
- **Stream processing** for concurrent node execution
- **Deterministic edge selection** with explicit priority ordering (no heuristics)
- **Immutable pipeline lifecycle** prevents hidden state mutations

---

## 8. attractor-rb (Ruby) by aliciapaz

**Repository**: [github.com/aliciapaz/attractor-rb](https://github.com/aliciapaz/attractor-rb)
**Language**: Ruby

### Architecture

Five-phase pipeline: DOT source -> Parse -> Transform -> Validate -> Execute -> Outcome.

### Validation (13 Built-in Rules)

**Error-level** (block execution):
1. `StartNodeRule` — exactly one start node
2. `TerminalNodeRule` — at least one exit node
3. `ReachabilityRule` — all nodes reachable from start
4. `EdgeTargetExistsRule` — edge targets exist
5. `StartNoIncomingRule` — start has no incoming edges
6. `ExitNoOutgoingRule` — exit has no outgoing edges
7. `ConditionSyntaxRule` — edge conditions are valid
8. `StylesheetSyntaxRule` — model stylesheets parse correctly
9. `RetryTargetExistsRule` — retry targets exist

**Warning-level** (allow execution):
10. `TypeKnownRule` — node types match registered handlers
11. `FidelityValidRule` — fidelity values recognized
12. `GoalGateHasRetryRule` — goal gates have retry targets
13. `PromptOnLlmNodesRule` — LLM nodes have prompts

### Checkpoint Artifacts

Per-node: `manifest.json`, `checkpoint.json`, `prompt.md`, `response.md`, `status.json`.

### What's Unique

- **Most comprehensive validation** of any implementation (13 rules)
- **Deterministic retry gates**: goal gates auto-retry from specified earlier nodes
- **Fan-out/fan-in** with configurable `join_policy` (`wait_all` or `first_success`) and `max_parallel` limits
- **Accelerator keys** in human approval labels (`[A] Approve`)

---

## 9. Arc (TypeScript + Effect.ts)

**Repository**: [github.com/point-labs-dev/arc](https://github.com/point-labs-dev/arc)
**Language**: TypeScript

### Architecture

Effect.ts-based pipeline engine with a separate `packages/ui/` web dashboard.

### What's Unique

- **Effect.ts for typed error handling**: structured error propagation without try/catch
- **Structured concurrency**: deterministic cleanup of multiple agent attempts
- **Learning persistence**: failed attempts store insights in `progress/` directory for subsequent iterations
- **Fresh context windows** per attempt prevent "cheating" through pattern memorization
- **Convergence-oriented design**: treats coding agent convergence as a graph traversal problem

---

## 10. attractor-php (PHP)

**Repository**: [github.com/jaytaylor/attractor-php](https://github.com/jaytaylor/attractor-php)
**Language**: PHP

### Architecture

Three-layer design (LLM, Agent, Pipeline) with dual execution modes: CLI and HTTP server (PHP built-in server).

### HTTP Server Mode

```
POST /run     — accepts DOT graph (inline or file path)
GET  /status  — retrieves execution state (JSON or SSE)
POST /answer  — submits human decisions to paused wait.human checkpoints
```

### What's Unique

- **Stateful run tracking across distributed requests** — solves PHP's synchronous request-response model challenge
- **Session boundary checkpointing** — pipeline state persists across HTTP request cycles
- Demonstrates Attractor works even in traditionally "unfriendly" environments for long-running processes

---

## Cross-Implementation Patterns

### Universal Patterns (Present in All 10 Implementations)

| Pattern | Description |
|---------|-------------|
| **DOT as source of truth** | All implementations parse Graphviz DOT syntax. No implementation invented a custom DSL. |
| **Shape-based handler dispatch** | Node shape attribute (`box`, `diamond`, `hexagon`, etc.) maps to handler type. Every implementation uses this mapping. |
| **JSON checkpoints** | State serialized as JSON after each node. Some add git commits or SQLite on top. |
| **Sequential core loop** | Despite parallel node support, the core traversal is sequential: execute -> evaluate edges -> advance. |
| **Provider abstraction** | All implementations abstract LLM providers behind a unified interface. |
| **SSE event streaming** | 8 of 10 implementations use Server-Sent Events for real-time progress. |

### The 5-Step Edge Selection Algorithm

Multiple implementations (Ruby, Scala, Python) converge on the same priority-based edge selection:

1. **Condition truth** — evaluate boolean expression against context
2. **Preferred label match** — handler returns a preferred outcome label
3. **Suggested node ID** — handler recommends specific next node
4. **Edge weight** — numeric weight for tie-breaking
5. **Default/fallback** — unlabeled edge or lexical ordering

This algorithm is effectively canonical across the community.

### Checkpoint Directory Structure (Consensus Format)

```
attractor-logs/
  run-<timestamp>/
    manifest.json          # Pipeline metadata
    checkpoint.json        # Resumable execution state
    <node-id>/
      prompt.md            # What was sent to LLM
      response.md          # What came back
      status.json          # Normalized outcome {status, metadata}
```

### Handler Type Mapping (Canonical)

| DOT Shape | Handler Type | Behavior |
|-----------|-------------|----------|
| `Mdiamond` | `start` | Pipeline entry, no-op |
| `Msquare` | `exit` | Pipeline termination, goal gate check |
| `box` | `codergen` | LLM invocation with prompt |
| `diamond` | `conditional` | Route based on edge conditions |
| `hexagon` | `wait.human` | Pause for human approval |
| `component` | `parallel` | Fan-out concurrent branches |
| `tripleoctagon` | `parallel.fan_in` | Join concurrent results |
| `parallelogram` | `tool` | Shell command execution |
| `house` | `stack.manager_loop` | Supervisor over child pipeline |

---

## Recommendations for Our Python Engine

### 1. Adopt the Middleware Chain (from samueljklee)

The middleware pattern for LLM calls is the most reusable Python pattern found:

```python
class Middleware(Protocol):
    async def __call__(self, request: LLMRequest, next: Callable) -> LLMResponse: ...

# Stack middlewares for cross-cutting concerns
pipeline = compose(
    LoggingMiddleware(logfire),
    TokenCountingMiddleware(),
    RetryMiddleware(max_retries=3, backoff=exponential),
    CachingMiddleware(ttl=300),
)
```

This cleanly separates observability (Logfire), cost tracking, and retry logic from handler code.

### 2. Use the 13-Rule Validation Set (from attractor-rb)

The Ruby implementation's 13 validation rules are the most comprehensive. Implement all 13 as a pre-execution validation pass. This catches structural errors before burning LLM tokens:

- Exactly one start node, at least one exit
- All nodes reachable from start
- Edge targets exist
- Start has no incoming, exit has no outgoing
- Condition syntax valid
- Model stylesheets parse correctly
- Retry targets exist
- LLM nodes have prompts

### 3. Implement the CSS-like Model Stylesheet (from samueljklee and F#kYeah)

This pattern decouples model selection from graph structure, which is critical for our multi-model workflows:

```python
stylesheet = ModelStylesheet.parse("""
    * { llm_model: claude-sonnet-4-5; }
    .critical { llm_model: claude-opus-4-6; reasoning_effort: high; }
    #final_review { llm_model: gpt-5.2; temperature: 0.2; }
""")

# At execution time
model_config = stylesheet.resolve(node)  # Uses CSS specificity rules
```

### 4. Git-Native Checkpointing (from Kilroy)

Kilroy's approach of using git commits as checkpoints is powerful for our worktree-based orchestration:

```python
# After each node completes
if config.git_commit_per_node:
    subprocess.run(["git", "add", "-A"], cwd=worktree_path)
    subprocess.run(["git", "commit", "-m", f"checkpoint: {node_id} completed"], cwd=worktree_path)
```

This means any crash can be recovered by inspecting the git log.

### 5. Typed Event System (from anishkny)

Use a 14-type event taxonomy with SSE streaming:

```python
@dataclass
class PipelineEvent:
    type: Literal[
        "pipeline.started", "pipeline.completed", "pipeline.failed",
        "node.started", "node.completed", "node.failed",
        "interview.started", "interview.answered",
        "tool.executed", "checkpoint.saved",
        "context.updated", "edge.selected",
        "retry.triggered", "message.sent"
    ]
    timestamp: datetime
    node_id: str | None
    data: dict[str, Any]
```

### 6. The 5-Step Edge Selection Algorithm

Implement the community-standard edge selection:

```python
def select_next_edge(node: Node, outcome: Outcome, context: Context) -> Edge:
    outgoing = graph.edges_from(node)

    # Step 1: Condition match
    for edge in outgoing:
        if edge.condition and evaluate(edge.condition, context, outcome):
            return edge

    # Step 2: Preferred label match
    if outcome.preferred_label:
        for edge in outgoing:
            if edge.label == outcome.preferred_label:
                return edge

    # Step 3: Suggested next node
    if outcome.suggested_next:
        for edge in outgoing:
            if edge.target == outcome.suggested_next:
                return edge

    # Step 4: Weight-based selection
    weighted = [e for e in outgoing if e.weight is not None]
    if weighted:
        return max(weighted, key=lambda e: e.weight)

    # Step 5: Default (unlabeled or first)
    unlabeled = [e for e in outgoing if not e.label and not e.condition]
    return unlabeled[0] if unlabeled else outgoing[0]
```

### 7. Loop Detection via Max Visits (Spec Requirement)

Multiple implementations handle this with a per-node visit counter:

```python
MAX_NODE_VISITS = 10  # Configurable per-node via retry_limit attribute

def check_loop(node_id: str, visit_counts: dict[str, int]) -> None:
    visit_counts[node_id] = visit_counts.get(node_id, 0) + 1
    if visit_counts[node_id] > MAX_NODE_VISITS:
        raise LoopDetectedError(f"Node {node_id} visited {visit_counts[node_id]} times")
```

The `loop_restart=true` edge attribute (from F#kYeah) provides an escape hatch: it clears context and restarts the pipeline fresh rather than continuing to accumulate state.

### 8. Custom Recursive-Descent DOT Parser

Both samueljklee (Python) and attractor-c demonstrate that a hand-rolled parser is preferable to depending on the graphviz Python library. Benefits:
- Direct extraction of Attractor-specific attributes (prompt, goal_gate, tool_command, model_stylesheet)
- No GPL dependency issues
- Full control over error messages
- Lightweight (no external binary needed)

---

## Architecture Comparison Matrix

| Feature | Kilroy (Go) | brynary (TS) | samueljklee (Py) | Forge (Rust) | Kotlin | F# | Scala | Ruby-rb | Arc (TS) | PHP |
|---------|-------------|--------------|-------------------|--------------|--------|-----|-------|---------|----------|-----|
| Custom DOT parser | N/A | Yes | Yes (recursive-descent) | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Checkpoint format | Git + CXDB | JSON files | JSON + fidelity | JSON + CXDB | SQLite | JSON files | JSON files | JSON files | JSON + learnings | JSON + session |
| Event streaming | CXDB events | SSE | SSE (12 types) | N/A | SSE + web | N/A | N/A | SSE | SSE + web | SSE |
| Parallel execution | Worktrees | Yes | asyncio | Yes | Yes | Yes | Cats-Effect/FS2 | Yes (configurable) | Effect.ts | No |
| Validation rules | N/A | Basic | Basic | N/A | Basic | Classification | Basic | 13 rules | Basic | Basic |
| Model stylesheet | Config | No | CSS-like | No | No | CSS-like | No | CSS-like | No | No |
| HTTP server | Experimental | Yes | Yes | CLI-only | Dashboard | CLI-only | CLI-only | Yes | Dashboard | Yes |
| LLM providers | 7+ | 2 | 4+ | 2 | 3 | 3 | N/A | 3 | 1 (Pi) | N/A |
| Type safety | Go types | TypeScript | Runtime | Rust (compile) | Kotlin | F# (compile) | Scala 3 (compile) | Ruby (runtime) | Effect.ts | PHP |

---

## Key Takeaways

1. **The spec is well-designed**. 16 independent implementations across 10 languages converged on nearly identical architectures, validating that the natural-language spec is unambiguous enough for agent-generated code.

2. **Python implementations are the most feature-complete**. samueljklee's version has the best middleware, stylesheet, and event system. anishkny's has the cleanest handler abstraction. Both are strong references for our engine.

3. **Validation before execution saves money**. The Ruby implementation's 13-rule validation catches structural errors before any LLM tokens are burned. This is a must-have.

4. **Git-native checkpointing aligns with our worktree model**. Kilroy's per-node git commits map directly onto our existing worktree-based orchestration.

5. **The middleware chain is the most important Python pattern to borrow**. It cleanly separates Logfire observability, token counting, caching, and retry logic from core handler code.

6. **Effect systems improve reliability**. The F#, Scala, and Arc (Effect.ts) implementations show that typed effect systems catch concurrency and resource bugs at compile time. In Python, this translates to strict use of `asyncio` with structured concurrency patterns (`TaskGroup`).

7. **CSS-like model stylesheets are underappreciated**. Only 3 implementations include them, but they solve a real problem: decoupling "which model to use" from "what the pipeline does." Critical for cost optimization and A/B testing.

---

## Sources

- [StrongDM Attractor Repository](https://github.com/strongdm/attractor)
- [Attractor Specification](https://github.com/strongdm/attractor/blob/main/attractor-spec.md)
- [StrongDM Software Factory — Attractor](https://factory.strongdm.ai/products/attractor)
- [brynary/attractor (TypeScript)](https://github.com/brynary/attractor)
- [danshapiro/kilroy (Go)](https://github.com/danshapiro/kilroy)
- [samueljklee/attractor (Python)](https://github.com/samueljklee/attractor)
- [smartcomputer-ai/forge (Rust)](https://github.com/smartcomputer-ai/forge)
- [coreydaley/coreys-attractor (Kotlin)](https://github.com/coreydaley/coreys-attractor)
- [TheFellow/fkyeah (F#)](https://github.com/TheFellow/fkyeah)
- [bencivjan/attractor-scala (Scala)](https://github.com/bencivjan/attractor-scala)
- [aliciapaz/attractor-rb (Ruby)](https://github.com/aliciapaz/attractor-rb)
- [point-labs-dev/arc (TypeScript + Effect.ts)](https://github.com/point-labs-dev/arc)
- [jaytaylor/attractor-php (PHP)](https://github.com/jaytaylor/attractor-php)
- [jhugman/attractor-pi-dev (TypeScript)](https://github.com/jhugman/attractor-pi-dev)
- [anishkny/attractor (Python)](https://github.com/anishkny/attractor)
- [bborn/attractor-ruby (Ruby)](https://github.com/bborn/attractor-ruby)
- [Simon Willison — How StrongDM's AI team build serious software](https://simonwillison.net/2026/Feb/7/software-factory/)
