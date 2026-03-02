# StrongDM Attractor Specification Analysis

**Date**: 2026-02-28
**Purpose**: Gap analysis between the StrongDM Attractor spec and our harness implementation, plus research on autonomous coding practices toward "Level 5" maturity.

---

## Part 1: Attractor Spec — Stages, State Machine, and Mechanisms

### 1.1 The Three Specifications

StrongDM's [Attractor repository](https://github.com/strongdm/attractor) contains no code — only three markdown specifications designed to be fed into any coding agent to produce a working implementation:

1. **attractor-spec.md** — Core pipeline orchestration (DOT graph engine)
2. **coding-agent-loop-spec.md** — Inner/outer agentic loop for code generation
3. **unified-llm-spec.md** — Provider-agnostic LLM client abstraction

The spec is language-agnostic and has been implemented by 17+ community contributors across Go, Python, Kotlin, Rust, TypeScript, Ruby, Scala, F#, C, and PHP.

### 1.2 Five Execution Phases

The Attractor engine defines a 5-phase lifecycle for pipeline execution:

| Phase | Purpose | Key Actions |
|-------|---------|-------------|
| **PARSE** | Convert `.dot` source into in-memory graph model | Load DOT file, build directed graph |
| **VALIDATE** | Run lint rules, reject invalid graphs | Single start/exit, reachability, no orphans, AT pairing |
| **INITIALIZE** | Create run directory, context, checkpoint; apply transforms | Set up context object, apply model stylesheet |
| **EXECUTE** | Traverse graph from start node using handlers | Run node handlers, checkpoint after each node, select edges |
| **FINALIZE** | Write final checkpoint, emit events, release resources | Persist terminal state, emit completion events |

### 1.3 Node Handler Types

Each node shape maps to exactly one handler:

| Shape | Handler | Purpose |
|-------|---------|---------|
| `Mdiamond` | `start` | Pipeline entry point |
| `Msquare` | `exit` | Pipeline exit point |
| `box` | `codergen` | LLM task (implementation) |
| `hexagon` | `wait.human` | Human-in-the-loop gate |
| `diamond` | `conditional` | Condition-based routing |
| `parallelogram` / `component` | `parallel` | Concurrent fan-out |
| `tripleoctagon` | `parallel.fan_in` | Consolidate parallel results |
| `parallelogram` (input shape) | `tool` | External tool execution |
| `house` | `stack.manager_loop` | Supervisor loop |

### 1.4 State Machine / Lifecycle

**Node Outcome Model**: Each handler execution produces an outcome with:
- **Status**: `SUCCESS`, `FAILURE`, `PARTIAL_SUCCESS`
- **Context updates**: Key-value pairs merged into pipeline context
- **Preferred label**: For routing at conditional nodes

**Edge Selection Algorithm** (ranked priority):
1. Condition satisfaction (boolean guard expression)
2. Preferred-label match (from upstream outcome)
3. Weight value (integer priority among eligible edges)

**Checkpoint Structure**: After every node execution:
- Current context snapshot
- Completed node list
- Last executed node ID

This enables **resume from any checkpoint** — a core design principle.

### 1.5 Goal Gates and Validation

**Goal gates** are nodes marked with `goal_gate=true`. These MUST reach `SUCCESS` before the pipeline can exit. If a goal gate fails:

1. Engine checks the failed node's `retry_target` attribute
2. Falls back to graph-level `retry_target`
3. Falls back to `fallback_retry_target`
4. Pipeline FAILS if no retry target exists

**Retry Policy**:
- `max_retries` per node (additional attempts beyond initial)
- `default_max_retry` at graph level (default: 50)
- `allow_partial` flag for accepting `PARTIAL_SUCCESS` when retries are exhausted

### 1.6 Context Fidelity Modes

Controls LLM session reuse across nodes:
- **full**: Maintain LLM session across nodes (requires `thread_id`)
- **checkpoint**: Session resets at checkpoints

This determines whether nodes share conversational context or get clean slates.

### 1.7 Condition Expression Language

Edges support a condition language with:
- Variable resolution from context (`$variable`)
- Comparison operators: `=`, `!=`, `<`, `>`, `<=`, `>=`
- Logical connectives: `&&`, `||`, `!`

### 1.8 Model Stylesheet

CSS-inspired syntax for per-node LLM configuration:

```css
box.critical { llm_model = "claude-opus"; reasoning_effort = "high" }
.code { llm_provider = "anthropic" }
```

Selectors target nodes by ID, shape, or class.

### 1.9 Coding Agent Loop (Inner Specification)

The coding agent loop is a **turn-based agentic loop** with:

**Outer Loop** (Session Management):
- `IDLE` -> `PROCESSING` -> `IDLE/AWAITING_INPUT/CLOSED`
- Manages conversation history, configuration, event emission

**Inner Loop** (Per-Input Tool Cycle):
1. Check limits (`max_tool_rounds_per_input`, `max_turns`)
2. Build LLM request (system prompt + history + tools)
3. Call LLM via `Client.complete()` (single-shot, not high-level tool loop)
4. Record response (text, tool calls, reasoning, usage)
5. Execute tools through `ExecutionEnvironment`
6. Append tool results to history
7. Drain steering queue (injected mid-turn messages)
8. Detect loops (repeating patterns in last N calls, default: 10)
9. Continue or break (text-only response = exit)

**Convergence Criteria**:
- Natural completion (model responds with text only, no tool calls)
- Round limit reached
- Turn limit exceeded
- Abort signal from host application
- Unrecoverable error (auth failure, context overflow)

### 1.10 Unified LLM Client (Provider Abstraction)

Four-layer architecture:
1. **Provider Specification Layer** — `ProviderAdapter` interface per provider
2. **Provider Utilities Layer** — Shared HTTP, SSE, retry helpers
3. **Core Client Layer** — Routes requests, applies middleware
4. **High-Level API Layer** — `generate()`, `stream()`, `generate_object()`

Critical principle: "Each provider adapter MUST use the provider's native, preferred API" (not lowest-common-denominator).

---

## Part 2: StrongDM's Software Factory and Autonomous Coding Practices

### 2.1 StrongDM's Software Factory Principles

StrongDM's AI team (formed July 2025) operates under three foundational rules:

1. **"Code must not be written by humans"**
2. **"Code must not be reviewed by humans"**
3. **Token spending should exceed "$1,000 on tokens today per human engineer"**

The team was catalyzed by Claude 3.5 Sonnet's October 2024 release, when "long-horizon agentic coding workflows began to compound correctness rather than error."

Source: [Simon Willison's analysis](https://simonwillison.net/2026/Feb/7/software-factory/) and [StrongDM's blog](https://www.strongdm.com/blog/the-strongdm-software-factory-building-software-with-ai)

### 2.2 Satisfaction Testing (Replacing Code Review)

StrongDM replaces traditional code review with **scenario-based satisfaction testing**:

- **Scenarios** are end-to-end user stories stored OUTSIDE the codebase (like ML holdout sets)
- **Satisfaction** measures the fraction of observed trajectories through scenarios that likely satisfy users
- This shifts from boolean test results to **probabilistic validation**
- The agent never sees its own test suite — preventing specification gaming

Key insight: "Validation replaces code review."

### 2.3 Digital Twin Universe (DTU)

StrongDM built behavioral clones of third-party services:
- **Okta, Jira, Slack, Google Docs, Drive, Sheets** — all replicated as self-contained binaries
- Enable testing at volumes exceeding production limits
- No rate limits, no API costs, full failure mode validation
- Strategy: "Use popular reference SDK client libraries as compatibility targets, with 100% compatibility as the goal"

### 2.4 Proof of Scale: CXDB

Three engineers built **CXDB** using the Software Factory approach:
- 16,000 lines of Rust
- 9,500 lines of Go
- 6,700 lines of TypeScript
- **No human code writing** — entirely agent-driven from markdown specifications

### 2.5 Autonomy Progression (Dark Factory Levels)

Based on the [Infralovers Dark Factory Architecture analysis](https://www.infralovers.com/blog/2026-02-22-architektur-patterns-dark-factory/):

| Level | Description | Human Role |
|-------|-------------|------------|
| **Level 1** | Autocomplete, copilot suggestions | Human writes code, AI assists |
| **Level 2** | Pair programming assistance | Human leads, AI accelerates |
| **Level 3** | Task-scoped agents (Devin, Claude Code) | Human defines tasks, reviews output |
| **Level 4** | Autonomous development against specifications | Human writes specs, validates scenarios |
| **Level 5** | Self-improving factory (implied) | Human sets business goals only |

StrongDM operates at **Level 4**: humans design specification architecture, not individual code reviews. The bottleneck has shifted "from implementation speed to spec quality."

### 2.6 Industry Landscape (2026)

From the [PeerPush landscape overview](https://peerpush.net/blog/coding-agents-in-2026) and [Faros AI reviews](https://www.faros.ai/blog/best-ai-coding-agents-2026):

**Autonomy Spectrum**:
- **Assistance-focused**: GitHub Copilot, Cursor — tab-complete and chat-based
- **Task-ownership**: Devin, OpenAI Codex — take ownership of scoped tasks
- **Factory-grade**: StrongDM Attractor — end-to-end specification-to-deployment

**Common Quality Gates** across the industry:
- Sandboxed execution environments
- Approval gates before destructive actions
- Configurable autonomy levels per task type
- Clear audit trails of every agent action
- Strong CI/CD as prerequisite for agent quality

**Key limitation**: All agents "inherit the structure, clarity, and constraints of the systems they work in" — quality gates depend heavily on baseline engineering practices.

Sources:
- [Martin Fowler on autonomous agents](https://martinfowler.com/articles/exploring-gen-ai/autonomous-agents-codex-example.html)
- [Devin's Agents 101](https://devin.ai/agents101)
- [GitHub agentic adoption study](https://arxiv.org/html/2601.18341v1)
- [Stanford Law: Built by Agents, Trusted by Whom?](https://law.stanford.edu/2026/02/08/built-by-agents-tested-by-agents-trusted-by-whom/)

---

## Part 3: Gap Analysis — Our Harness vs. Attractor Spec

### 3.1 What We Have (Current State)

Our harness implements a substantial subset of Attractor concepts:

| Attractor Concept | Our Implementation | Status |
|-------------------|--------------------|--------|
| DOT-based pipeline graphs | `.claude/attractor/pipelines/*.dot` | **Implemented** |
| 5-stage lifecycle (PARSE/VALIDATE/INITIALIZE/EXECUTE/FINALIZE) | Schema defines all 5 stages with cs-* integration | **Implemented** |
| Node shapes → handler types | Mdiamond, Msquare, box, hexagon, diamond, parallelogram all mapped | **Implemented** |
| Status transitions (pending/active/impl_complete/validated/failed) | Defined in schema, tracked via DOT attributes + checkpoints | **Implemented** |
| Checkpoint/resume | `.claude/attractor/pipelines/*-checkpoint-*.json` files exist | **Partial** — checkpoints written but no automated resume engine |
| Goal gates | `hexagon` nodes with `wait.human` handler | **Implemented** via validation agents |
| Conditional routing | `diamond` nodes with pass/fail edges | **Implemented** in DOT structure |
| Parallel execution | `parallelogram` fan-out/fan-in nodes | **Implemented** in DOT structure |
| Completion promise integration | cs-* commands mapped to each lifecycle stage | **Implemented** |
| AT (acceptance test) pairing | Every codergen node paired with tech+biz hexagons | **Implemented** |
| Retry on failure | Dashed red edges from decision nodes back to impl nodes | **Implemented** in graph structure |
| Signal-based coordination | `.claude/attractor/pipelines/signals/` and `.claude/attractor/signals/` | **Implemented** |
| Runner state tracking | `.claude/attractor/runner-state/*.json` | **Implemented** |

### 3.2 Critical Gaps

#### Gap 1: No Automated Graph Execution Engine

**Spec requires**: An engine that traverses the graph automatically — checking limits, executing handlers, recording outcomes, selecting edges, and checkpointing after each node.

**We have**: The DOT files are declarative descriptions that System 3 and orchestrators read and interpret manually. State transitions happen through convention (bd update, attractor transition) rather than through an automated engine.

**Impact**: HIGH — This is the core differentiator. Without an engine, pipeline execution requires constant human/S3 coordination rather than autonomous traversal.

#### Gap 2: No Condition Expression Language

**Spec requires**: Boolean expressions on edges (`$retry_count < 3 && $test_coverage > 80`) evaluated against the pipeline context.

**We have**: Static `condition=pass/fail` labels that are interpreted by convention, not evaluated programmatically.

**Impact**: MEDIUM — Limits dynamic routing. Currently, pass/fail decisions are binary and determined by the validation agent, not by expressions against accumulated context.

#### Gap 3: No Model Stylesheet

**Spec requires**: CSS-like syntax for configuring LLM parameters per node type/class.

**We have**: `worker_type` attribute determines which specialist agent handles a node, but no per-node LLM model or reasoning effort configuration.

**Impact**: LOW — Our 3-level hierarchy (Opus/Sonnet/Haiku) and worker specialization achieve similar outcomes through structural means.

#### Gap 4: No Context Fidelity Control

**Spec requires**: `full` vs `checkpoint` modes controlling whether LLM sessions persist across nodes.

**We have**: Each worker session is independent (effectively `checkpoint` mode everywhere). No mechanism to share conversational context across pipeline nodes.

**Impact**: MEDIUM — For tightly coupled implementation sequences (e.g., backend then frontend that depends on its types), context sharing could reduce rework.

#### Gap 5: No Loop Detection

**Spec requires**: Automatic detection of repeating patterns in the last N tool calls (default: 10) to prevent infinite loops.

**We have**: `default_max_retry` concept exists in schema (retries via fail edges), but no automated detection of agents stuck in loops.

**Impact**: HIGH — We have observed this problem in practice (Haiku workers failing to exit, orchestrators stuck in retry cycles). The spec's loop detection is specifically designed to address this.

#### Gap 6: No Event System

**Spec requires**: 10+ event types (USER_INPUT, ASSISTANT_TEXT_DELTA, TOOL_CALL_END, etc.) for observability.

**We have**: Logfire integration for tracing, signal files for inter-agent coordination, but no structured event bus that the pipeline engine emits into.

**Impact**: MEDIUM — Logfire provides observability, but events are not structured around the pipeline lifecycle.

#### Gap 7: No Satisfaction Testing

**Spec/practice requires**: Scenarios stored OUTSIDE the codebase as holdout sets, with probabilistic LLM-based satisfaction scoring.

**We have**: Acceptance tests (Gherkin `.feature` files) that are written before implementation and stored in `acceptance-tests/`. These are visible to the implementing agents — not holdout sets.

**Impact**: HIGH for Level 4+ autonomy — This is the key mechanism that lets StrongDM eliminate human code review. Without holdout scenarios, we still need human oversight of agent output.

#### Gap 8: No Digital Twin Universe

**Spec/practice requires**: Behavioral clones of external services for isolated testing.

**We have**: No service clones. Tests run against real services or mocks within the test suite.

**Impact**: MEDIUM — Relevant when our projects integrate with external APIs (Supabase, Okta, etc.).

### 3.3 What We Have That the Spec Does Not

| Our Feature | Attractor Spec Equivalent | Assessment |
|-------------|---------------------------|------------|
| 3-level agent hierarchy (System 3 / Orchestrator / Worker) | Not specified — Attractor is a single-level engine | Our hierarchy adds strategic oversight that Attractor lacks |
| Completion promises with triple gate | Not specified — goal gates are simpler pass/fail | Our promises are more rigorous (Gate 1: ACs, Gate 2: validation responses, Gate 3: independent verification) |
| Beads issue tracking integration | Not specified | Adds traceability absent from the spec |
| Output styles for role enforcement | Not specified | Structural role separation through prompt injection |
| Stop gate hooks | Not specified | Prevents premature session termination |
| Native Agent Teams (Claude Code) | Not specified — Attractor is implementation-agnostic | Leverages Claude Code's native team coordination |
| Cyclic wake-up monitoring pattern | Not specified | Addresses the real-world problem of idle agent detection |

---

## Part 4: Recommendations — Path to Level 5

### 4.1 Priority 1: Automated Pipeline Engine (Closes Gap 1)

Build a Python engine (`cobuilder pipeline run <file>.dot`) that:
- Parses the DOT file into an in-memory graph
- Traverses from `Mdiamond` to `Msquare`
- Executes handlers: spawns workers for `codergen`, runs commands for `tool`, pauses for `wait.human`
- Checkpoints after each node
- Supports resume from checkpoint
- Implements the edge selection algorithm (condition > label > weight)

This is the single highest-leverage improvement. It converts our DOT files from documentation into executable programs.

### 4.2 Priority 2: Holdout Scenario Testing (Closes Gap 7)

Adopt StrongDM's satisfaction testing pattern:
- Store scenarios in a separate repository or encrypted directory that agents cannot access during implementation
- Use an independent LLM to judge whether the implementation satisfies each scenario
- Score satisfaction probabilistically (0.0-1.0) rather than binary pass/fail
- This would enable removing human code review from the loop

### 4.3 Priority 3: Loop Detection (Closes Gap 5)

Add loop detection to the pipeline engine:
- Track the last N node executions (configurable, default: 10)
- Detect repeating patterns (same node failing repeatedly, circular retry paths)
- Escalate to System 3 when a loop is detected rather than continuing to retry
- Set hard limits: `max_retries` per node, `default_max_retry` per pipeline

### 4.4 Priority 4: Condition Expression Evaluation (Closes Gap 2)

Implement a simple expression evaluator for edge conditions:
- Resolve `$variables` from the pipeline context (accumulated outcomes)
- Support comparison and logical operators
- Enable dynamic routing based on accumulated metrics (test coverage, retry count, etc.)

### 4.5 Priority 5: Context Fidelity (Closes Gap 4)

For tightly coupled node sequences, allow context sharing:
- `fidelity=full` edges would pass the conversation history from one worker to the next
- Requires serializing Claude Code conversation state between sessions
- Could use shared context files as an intermediate step

### 4.6 Priority 6: Event Bus (Closes Gap 6)

Structure observability around pipeline events:
- Emit structured events at each lifecycle stage
- Feed events into Logfire with pipeline-specific span attributes
- Enable dashboards showing pipeline progress, bottlenecks, and failure patterns

### 4.7 Level 5 Aspirations (Long-Term)

Based on industry research, Level 5 would add:

| Capability | Description | Prerequisites |
|------------|-------------|---------------|
| **Self-improving specifications** | Agent proposes PRD amendments based on implementation experience | Holdout testing + feedback loops |
| **Automatic pipeline generation** | Given a PRD, generate the DOT pipeline automatically | Pipeline engine + template library |
| **Cross-pipeline learning** | Use past pipeline outcomes to predict optimal worker assignment | Event bus + hindsight memory |
| **Cost optimization** | Automatically select model tier per node based on complexity | Model stylesheet + cost tracking |
| **Continuous validation** | Run holdout scenarios continuously against deployed code | DTU + satisfaction testing |

---

## Summary

### Where We Stand

Our harness is a **strong Level 3 implementation** with some Level 4 characteristics. We have the declarative pipeline structure (DOT graphs), multi-level agent hierarchy, validation gates, and checkpoint infrastructure. What we lack is the automated engine that converts these from documents into executable programs.

### The StrongDM Delta

StrongDM's key insight is that the bottleneck has shifted from "implementation speed" to "spec quality." Their Attractor spec demonstrates this by containing zero code — only specifications that any agent can implement. Their three innovations that matter most:

1. **Graph-as-program** — DOT files are not documentation; they are executable
2. **Satisfaction testing** — Holdout scenarios replace code review
3. **Digital twins** — External service clones enable testing at scale

### Recommended Next Step

Build the pipeline execution engine. Everything else — loop detection, expression evaluation, event emission — is a feature of that engine. The DOT files and schema already exist. The gap is the runtime that traverses them.

---

## Sources

- [StrongDM Attractor GitHub Repository](https://github.com/strongdm/attractor)
- [Attractor Specification (attractor-spec.md)](https://github.com/strongdm/attractor/blob/main/attractor-spec.md)
- [Coding Agent Loop Specification](https://github.com/strongdm/attractor/blob/main/coding-agent-loop-spec.md)
- [Unified LLM Client Specification](https://github.com/strongdm/attractor/blob/main/unified-llm-spec.md)
- [StrongDM Software Factory Product Page](https://factory.strongdm.ai/products/attractor)
- [Simon Willison: How StrongDM's AI team build serious software without looking at the code](https://simonwillison.net/2026/Feb/7/software-factory/)
- [StrongDM Blog: The Software Factory](https://www.strongdm.com/blog/the-strongdm-software-factory-building-software-with-ai)
- [Infralovers: Dark Factory Architecture — Level 4 Patterns](https://www.infralovers.com/blog/2026-02-22-architektur-patterns-dark-factory/)
- [PeerPush: Coding Agents in 2026 — Practical Landscape Overview](https://peerpush.net/blog/coding-agents-in-2026)
- [Martin Fowler: Autonomous Coding Agents — A Codex Example](https://martinfowler.com/articles/exploring-gen-ai/autonomous-agents-codex-example.html)
- [Devin: Coding Agents 101](https://devin.ai/agents101)
- [Stanford Law: Built by Agents, Tested by Agents, Trusted by Whom?](https://law.stanford.edu/2026/02/08/built-by-agents-tested-by-agents-trusted-by-whom/)
- [GitHub Agentic Adoption Study (arXiv)](https://arxiv.org/html/2601.18341v1)
- [Ry Walker Research: StrongDM Factory](https://rywalker.com/research/strongdm-factory)
