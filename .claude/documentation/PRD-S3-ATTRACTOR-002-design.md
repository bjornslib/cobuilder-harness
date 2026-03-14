---
title: "Prd S3 Attractor 002 Design"
status: active
type: architecture
last_verified: 2026-02-19
grade: reference
---

# PRD-S3-ATTRACTOR-002: Execution Engine Design Document

**Status**: Draft
**Date**: 2026-02-19
**Author**: System 3 Meta-Orchestrator
**Parent PRD**: PRD-S3-ATTRACTOR-001 (Attractor-Inspired Graph Orchestration)
**Bead ID**: claude-harness-setup-ej8c

---

## 1. Executive Summary

### Why an Execution Engine

PRD-S3-ATTRACTOR-001 establishes the Attractor-style DOT graph as the primary orchestration artifact for System 3. However, under that PRD, System 3 remains responsible for manually reading pipeline state (`attractor status`), deciding which node to advance next, calling `attractor transition`, spawning orchestrators, and checkpointing progress. This manual graph navigation consumes significant System 3 context and cognitive budget on mechanical traversal logic rather than strategic oversight.

An execution engine removes this burden. System 3 declares its intent by authoring (or approving) a DOT pipeline graph, and the engine handles the mechanical work of traversal: evaluating dependencies, spawning workers for ready nodes, collecting validation results, advancing state, and checkpointing.

### Goal

**System 3 declares intent via DOT graph; the engine handles traversal.**

The engine is not a replacement for System 3. It is an automation layer that eliminates the repetitive graph-navigation loop while preserving System 3's role as strategic overseer, anti-gaming enforcer, and business-outcome validator. System 3 remains the authority on what to build (the graph) and whether it was built correctly (validation). The engine handles the how of moving through the graph.

### Design Principles

1. **Progressive automation**: Start with CLI tools humans can inspect, layer automation on top.
2. **Same tools, different caller**: The engine calls the same `attractor` CLI commands System 3 calls manually. No new APIs needed for Phase 2.
3. **Oversight never automated away**: Validation gates (`hexagon` nodes) always require independent verification. The engine orchestrates validation but cannot self-validate.
4. **Crash resilience**: Every state transition is checkpointed. The engine can resume from any interruption.
5. **Anti-gaming by design**: The engine enforces the triple-gate protocol. Agents cannot mark their own work as validated.

---

## 2. Three-Phase Architecture

The execution engine evolves through three progressive phases, each building on the previous one. The key insight is that each phase uses the same DOT vocabulary and CLI tools -- what changes is who (or what) calls them.

```
Phase 1 (Current)          Phase 2 (Next)              Phase 3 (Future)
┌──────────────────┐      ┌──────────────────┐        ┌──────────────────┐
│  System 3         │      │  System 3         │        │  System 3         │
│  (manual graph    │      │  (oversight +     │        │  (strategic only) │
│   navigation)     │      │   approval)       │        │                   │
│                   │      │                   │        │                   │
│  attractor status │      │         │         │        │         │         │
│  attractor trans  │      │         ▼         │        │         ▼         │
│  attractor ckpt   │      │  ┌─────────────┐ │        │  ┌─────────────┐  │
│       │           │      │  │ Pipeline     │ │        │  │ Attractor   │  │
│       ▼           │      │  │ Runner Agent │ │        │  │ Runtime     │  │
│  [Workers]        │      │  │ (PydanticAI) │ │        │  │ (native)    │  │
│                   │      │  └──────┬──────┘ │        │  └──────┬──────┘  │
│                   │      │         │         │        │         │         │
│                   │      │  attractor CLI    │        │  Event streams    │
│                   │      │         │         │        │  Multi-pipeline   │
│                   │      │         ▼         │        │         │         │
│                   │      │  [Workers]        │        │         ▼         │
│                   │      │                   │        │  [Distributed     │
│                   │      │                   │        │   Workers]        │
└──────────────────┘      └──────────────────┘        └──────────────────┘
```

---

### Phase 1: CLI-Driven (Current -- PRD-S3-ATTRACTOR-001)

Phase 1 is the foundation delivered by PRD-S3-ATTRACTOR-001. All graph interaction is manual.

**How it works:**
1. System 3 authors or generates a DOT pipeline graph for an initiative.
2. System 3 calls `attractor parse` and `attractor validate` to verify the graph.
3. System 3 reads `attractor status` to identify which nodes are `pending` with all dependencies satisfied.
4. System 3 spawns an orchestrator (via tmux) for the next ready `codergen` node.
5. When the orchestrator reports `impl_complete`, System 3 transitions the node and dispatches validation via `attractor transition`.
6. System 3 evaluates validation results and advances or retries the node.
7. System 3 calls `attractor checkpoint save` after each transition.
8. Repeat steps 3-7 until the pipeline reaches the `exit` node.
9. System 3 runs `cs-verify --promise` for the triple-gate finalization.

**What exists after Phase 1:**
- DOT vocabulary and schema (`.pipelines/schema.md`)
- CLI tools: `attractor parse`, `validate`, `status`, `transition`, `checkpoint`
- Completion promise integration (`cs-init`, `cs-promise`, `cs-verify`)
- Checkpoint/restore for crash recovery
- System 3 output style with DOT graph navigation workflow
- Stop gate integration (blocks session end if pipeline has unvalidated nodes)

**Limitations of Phase 1:**
- System 3 spends substantial context on graph traversal logic.
- Each status check, dependency evaluation, and transition call is a tool use consuming context budget.
- No event-driven progression -- System 3 must actively poll.
- Multi-pipeline management requires System 3 to interleave manually.
- Error handling and retry logic is ad-hoc per session.

---

### Phase 2: Agent SDK Integration

Phase 2 introduces a **Pipeline Runner Agent** -- a purpose-built agent that reads the DOT graph and automates traversal. System 3 shifts from manual navigation to oversight and approval.

**Architecture:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  SYSTEM 3 (Opus)                                                     │
│                                                                      │
│  Responsibilities:                                                   │
│    - Author/approve DOT pipeline graphs                             │
│    - Launch Pipeline Runner with graph path                         │
│    - Review runner decisions at validation gates                    │
│    - Override/intervene on runner errors                            │
│    - Business-level outcome verification at FINALIZE                │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  PIPELINE RUNNER AGENT (Sonnet via PydanticAI)                 │  │
│  │                                                                 │  │
│  │  Input: pipeline.dot path                                      │  │
│  │  State: .pipelines/state/{pipeline-id}.json             │  │
│  │                                                                 │  │
│  │  Loop:                                                          │  │
│  │    1. attractor status --json -> identify ready nodes           │  │
│  │    2. For each ready codergen node:                             │  │
│  │       a. Spawn orchestrator (tmux) for the node                │  │
│  │       b. Monitor orchestrator progress                         │  │
│  │       c. On impl_complete: attractor transition                │  │
│  │    3. For each ready wait.human node:                          │  │
│  │       a. Dispatch validation-test-agent                        │  │
│  │       b. Collect results                                       │  │
│  │       c. On pass: attractor transition                         │  │
│  │       d. On fail: attractor transition --status=failed         │  │
│  │    4. attractor checkpoint save                                │  │
│  │    5. If exit node reached: signal System 3 for FINALIZE       │  │
│  │    6. If no ready nodes and not done: report STUCK to System 3 │  │
│  │                                                                 │  │
│  │  Tools: attractor CLI, tmux, validation-test-agent,            │  │
│  │         cs-promise                                              │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  ORCHESTRATORS + WORKERS (unchanged from Phase 1)              │  │
│  │  Spawned per codergen node by the runner agent                 │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Key design decisions for Phase 2:**

1. **Agent framework: PydanticAI or Anthropic Agent SDK**
   - The runner agent is a structured agent with well-defined tools and a loop.
   - PydanticAI provides typed tool definitions and structured output parsing.
   - The Anthropic Agent SDK (if available) may offer tighter integration with Claude Code's native Agent Teams.
   - Decision deferred to spike POC (Section 5).

2. **Event-driven progression**
   - Node completion triggers the runner to re-evaluate the graph.
   - The runner does not poll on a timer; it reacts to orchestrator completion signals.
   - Completion signals come via: (a) bead status updates, (b) tmux session exit, (c) task list changes detected by `task-list-monitor.py`.

3. **System 3 approval gates**
   - The runner advances `codergen` -> `impl_complete` -> `validated` automatically for technical validation.
   - Business validation gates (`gate=business`) require System 3 approval before the runner advances.
   - The runner signals System 3 via `SendMessage` when business approval is needed.
   - System 3 can override the runner's decisions at any point.

4. **Same CLI tools, different caller**
   - The runner calls `attractor status`, `attractor transition`, `attractor checkpoint` -- the exact same commands System 3 calls in Phase 1.
   - No new infrastructure needed. The runner is a caller, not a platform.

5. **Checkpoint recovery**
   - The runner checkpoints after every transition (same as Phase 1).
   - If the runner crashes, System 3 relaunches it. The runner reads the latest checkpoint and resumes.
   - Checkpoint frequency: after every node state transition (not time-based).

6. **Single-pipeline scope**
   - Phase 2 supports exactly one active pipeline per runner instance.
   - For multi-initiative work, System 3 launches multiple runner instances.
   - Cross-pipeline dependencies are not supported (those require Phase 3).

**What Phase 2 adds:**
- Pipeline Runner Agent (PydanticAI-based)
- Event-driven node evaluation (react to completion, not poll)
- Automatic worker spawning from graph nodes
- Automatic validation dispatching
- System 3 approval gates for business validation
- Crash recovery via checkpoint/restore

**What Phase 2 does NOT change:**
- DOT vocabulary (same schema.md)
- CLI tools (same attractor commands)
- Worker architecture (same orchestrator + native teams pattern)
- Validation protocol (same triple-gate, same validation-test-agent)
- Completion promises (same cs-* tools)

---

### Phase 3: Full Attractor Runtime

Phase 3 envisions a native Attractor-compatible runtime. This phase may never be needed -- evaluate after Phase 2 proves or disproves the need.

**What Phase 3 would add:**

1. **Event streams**: Real-time event bus for node state changes, enabling external dashboards and monitoring tools to subscribe to pipeline progress.

2. **Multi-pipeline orchestration**: A single runtime managing multiple concurrent pipelines with cross-pipeline dependency resolution. Pipeline A's node 5 can depend on Pipeline B's node 3.

3. **Distributed execution**: Workers distributed across multiple machines. The runtime manages node-to-machine assignment, remote monitoring, and result collection.

4. **Native Attractor compatibility**: Full compliance with the Attractor specification (github.com/strongdm/attractor), including `model_stylesheet`, `CodergenBackend` abstraction, and HTTP API endpoints.

5. **Real-time status dashboard**: Web-based UI showing pipeline progress, node states, worker assignments, and event history.

6. **Pluggable backends**: The `CodergenBackend` abstraction from Attractor, allowing different implementation strategies (Claude Code, other LLM tools, human workers) to be plugged in as node handlers.

**Why Phase 3 may not be needed:**
- Phase 2's single-pipeline runner + System 3 oversight may be sufficient for all practical workloads.
- Multi-pipeline orchestration adds significant complexity for marginal benefit when System 3 can manage 2-3 concurrent runners.
- Distributed execution is only relevant if work exceeds a single machine's capacity (unlikely for our use case).
- Event streams are nice-to-have but not critical when System 3 has direct access to pipeline state.

**Decision gate**: After 3 months of Phase 2 usage, evaluate whether any Phase 3 capability is truly needed based on:
- Number of concurrent pipelines being managed
- Frequency of System 3 context exhaustion from runner management
- Whether external stakeholders need real-time pipeline visibility
- Whether distributed execution would meaningfully improve throughput

---

## 3. Scenario Testing with Anti-Gaming

Testing the execution engine requires scenarios that exercise both the happy path and failure modes, with specific attention to agents attempting to bypass validation (gaming).

### 3.1 Scenario Categories

#### Happy Path: All Nodes Pass

```
Pipeline: 3-node (backend -> validate -> frontend -> validate -> finalize)

Timeline:
  t0: Runner reads graph, identifies backend node as ready
  t1: Runner spawns orchestrator for backend
  t2: Orchestrator completes, signals impl_complete
  t3: Runner dispatches technical validation -> PASS
  t4: Runner dispatches business validation -> PASS
  t5: Runner transitions backend to validated
  t6: Runner identifies frontend node as ready (dependency satisfied)
  t7: Repeat for frontend
  t8: Runner reaches exit node, signals System 3
  t9: System 3 runs cs-verify triple-gate -> PASS
  t10: Pipeline finalized

Expected: All nodes green. Promise verified. Pipeline in history.
Duration: ~30-60 minutes for a 3-node pipeline.
```

#### Partial Failure: Retry Logic

```
Pipeline: Same 3-node pipeline

Timeline:
  t0-t3: Backend impl_complete (same as above)
  t4: Technical validation -> FAIL (missing error handling)
  t5: Runner transitions backend to failed
  t6: Runner sends feedback to orchestrator via tmux injection
  t7: Orchestrator receives rejection, fixes issue
  t8: Orchestrator signals impl_complete (second attempt)
  t9: Technical validation -> PASS
  t10: Business validation -> PASS
  t11: Runner transitions backend to validated
  t12: Continue pipeline

Expected: Backend node shows retry path (failed -> active -> impl_complete -> validated).
          Checkpoint file shows the retry history.
          Runner handles retry without System 3 intervention.
Max retries: 3 per node. After 3 failures, runner signals STUCK to System 3.
```

#### Cascading Failure: Dependency Chain

```
Pipeline: A -> B -> C (serial dependency chain)

Timeline:
  t0: A completes and validates
  t1: B starts, fails validation 3 times
  t2: Runner signals STUCK to System 3
  t3: C never starts (blocked by B)

Expected: Runner reports exactly which node is stuck, with failure history.
          System 3 can: (a) provide guidance and reset retry count,
                        (b) skip the node with override, or
                        (c) abort the pipeline.
          C remains in pending state (never transitions to active).
```

#### Parallel Failure: Fan-Out Recovery

```
Pipeline: A -> [B, C, D] (parallel) -> E

Timeline:
  t0: A validates
  t1: Runner spawns B, C, D concurrently
  t2: B and C complete and validate
  t3: D fails validation
  t4: E cannot start (requires B + C + D)
  t5: D retries, succeeds
  t6: Runner detects all parallel nodes validated, advances to E

Expected: Runner correctly handles mixed completion in parallel groups.
          E only starts when ALL parallel predecessors are validated.
          Failed parallel nodes retry independently.
```

### 3.2 Anti-Gaming Measures

The execution engine must prevent agents from marking work as complete without genuine evidence. This is the single highest-risk failure mode in autonomous AI orchestration.

#### Threat Model

| Threat | Description | Severity |
|--------|-------------|----------|
| **Self-validation** | An agent validates its own work (grades own homework) | Critical |
| **Hollow evidence** | Agent produces evidence that looks correct but was not actually generated from real execution | High |
| **Premature completion** | Agent signals impl_complete before work is actually done to move to next task | High |
| **Validation replay** | Agent reuses evidence from a previous successful run instead of fresh validation | Medium |
| **Scope reduction** | Agent narrows acceptance criteria to make validation easier | Medium |

#### Triple-Gate Validation Protocol

The execution engine enforces the triple-gate at every validation point:

```
Gate 1: Self-Report (necessary but NOT sufficient)
  - Worker/orchestrator reports impl_complete
  - Evidence: git diff, test output, screenshots
  - Trust level: LOW (implementer's self-assessment)

Gate 2: Validation Response (independent check)
  - validation-test-agent runs independently with --mode=technical or --mode=business
  - Agent has NO access to self-report evidence (runs fresh)
  - Must produce its own evidence from scratch
  - Trust level: MEDIUM (independent but still LLM-based)

Gate 3: Independent Verify (ground truth)
  - System 3 dispatches s3-investigator (Explore agent) to verify claims
  - Reads actual code, runs actual commands, compares to acceptance criteria
  - Uses git log to verify changes are real (not fabricated)
  - Trust level: HIGH (independent and evidence-based)
```

#### Anti-Gaming Enforcement Rules

1. **No self-validation**: The runner MUST NOT allow the same agent that implemented a node to validate it. Implementation and validation are always separate agents.

2. **Fresh evidence requirement**: Every validation run MUST produce fresh evidence. The validator receives only the acceptance criteria and the codebase -- never the implementer's self-report.

3. **Evidence timestamping**: All evidence is timestamped. Evidence older than the most recent `impl_complete` transition is rejected as stale.

4. **Random spot-checks by System 3**: System 3 randomly selects 20% of validated nodes for manual re-verification. The selection is unpredictable (based on hash of session ID + node ID). If a spot-check fails, ALL nodes validated in the same session are re-validated.

5. **Acceptance criteria immutability**: Once a pipeline is validated (`attractor validate`), acceptance criteria on nodes cannot be weakened. They can only be strengthened (adding criteria) or clarified (rewording without reducing scope). The `attractor validate` command rejects graphs where `acceptance` attributes have been narrowed.

6. **Evidence requirements by validation type**:

| Validation Type | Required Evidence |
|----------------|-------------------|
| `technical` | Actual test output (exit code + stdout), lint results, type-check output |
| `business` | E2E test results against PRD criteria, API response bodies, screenshots |
| `e2e` | Full end-to-end workflow completion with timestamped artifacts |
| `manual` | Human-provided approval with signed reason |

7. **Audit trail**: Every transition is logged to `.pipelines/state/{pipeline-id}-audit.jsonl` with: timestamp, node_id, from_status, to_status, agent_id, evidence_hash, checkpoint_id. This trail is immutable (append-only).

---

## 4. Scope Boundaries

### IN Scope for Phase 2

| Capability | Description |
|------------|-------------|
| **Single pipeline execution** | One Pipeline Runner per DOT file. Multiple concurrent runners for multi-initiative work. |
| **CLI tool integration** | Runner calls existing `attractor` CLI commands. No new infrastructure. |
| **System 3 manual oversight** | System 3 approves business validation gates and can override/intervene at any point. |
| **Checkpoint/restore for crash recovery** | Runner checkpoints after every transition. Survives crashes, context resets, and session restarts. |
| **Worker spawning from graph nodes** | Runner reads `codergen` nodes, spawns orchestrators in tmux with appropriate worker_type and acceptance criteria. |
| **Automatic technical validation** | Runner dispatches `validation-test-agent --mode=technical` without System 3 involvement. |
| **Business validation gating** | Runner pauses at `gate=business` nodes and signals System 3 for approval. |
| **Retry logic** | Up to 3 automatic retries per node with feedback injection. After 3 failures, escalate to System 3. |
| **Parallel node management** | Runner correctly handles parallel fan-out/fan-in groups. |
| **Pipeline completion signaling** | Runner signals System 3 when exit node is reached for FINALIZE. |
| **Anti-gaming enforcement** | Triple-gate protocol, fresh evidence, spot-checks, audit trail. |

### OUT of Scope (Phase 3 or Never)

| Capability | Why Deferred | Phase |
|------------|-------------|-------|
| **Auto-traversal without human oversight** | Core design principle: System 3 always has veto power. Business gates always require approval. | Never (by design) |
| **Event streams** | Polling-based approach is sufficient when the runner is the only consumer. External dashboards are not a current requirement. | Phase 3 |
| **Multi-pipeline orchestration (single runtime)** | System 3 can launch multiple runner instances. A unified multi-pipeline runtime adds complexity without proven need. | Phase 3 |
| **Distributed execution** | Single-machine capacity is sufficient for current workloads. | Phase 3 |
| **Real-time status dashboard** | `attractor status` CLI output is sufficient for System 3. External stakeholders don't currently need pipeline visibility. | Phase 3 |
| **CodergenBackend abstraction** | The current worker architecture (Claude Code + native Agent Teams) is the only backend. Pluggable backends add abstraction without current benefit. | Phase 3 |
| **model_stylesheet** | Attractor's model_stylesheet concept for per-node model selection is interesting but not needed when System 3 controls model selection at orchestrator spawn time. | Phase 3 |
| **HTTP API** | No external consumers need to interact with the pipeline programmatically. | Phase 3 |
| **Cross-pipeline dependencies** | Rare edge case. System 3 can manually coordinate between runner instances for now. | Phase 3 |

### Boundary Decision Criteria

A capability moves from "Out of Scope" to "In Scope" when:
1. System 3 context exhaustion from manual management exceeds 30% of session budget.
2. The same coordination pattern is repeated manually 5+ times across sessions.
3. An external stakeholder (user, team) requests the capability with a concrete use case.
4. A Phase 2 limitation causes a pipeline failure that the capability would have prevented.

---

## 5. Agent SDK Spike POC

### Objective

Build a minimal Pipeline Runner agent that reads a DOT file, evaluates current state, and outputs a plan of action. The POC validates the agent design WITHOUT executing any actions.

### POC Scope

**Input**: Path to a DOT pipeline file (e.g., `.pipelines/examples/simple-pipeline.dot`)

**Output**: An ordered list of `(node_id, action)` tuples representing what the runner would do next.

**Constraint**: NO auto-execution in POC. The agent plans but does not act. This validates the agent's graph reasoning without risk.

### POC Architecture

```python
# poc_pipeline_runner.py
# Framework: PydanticAI (preferred) or plain Anthropic API

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

# --- Data Models ---

class NodeAction(BaseModel):
    """A single action the runner would take."""
    node_id: str
    action: str  # "spawn_orchestrator", "dispatch_validation", "transition", "signal_stuck", "signal_finalize"
    reason: str  # Why this action
    dependencies_satisfied: list[str]  # Which dependencies are met
    worker_type: str | None = None  # For spawn_orchestrator actions
    validation_mode: str | None = None  # For dispatch_validation actions

class RunnerPlan(BaseModel):
    """Complete plan of action for the current pipeline state."""
    pipeline_id: str
    current_stage: str  # PARSE, VALIDATE, INITIALIZE, EXECUTE, FINALIZE
    summary: str
    actions: list[NodeAction]  # Ordered list of actions to take
    blocked_nodes: list[str]  # Nodes that cannot proceed (with reasons)
    completed_nodes: list[str]  # Nodes already validated

# --- Tools (read-only for POC) ---

@agent.tool
async def get_pipeline_status(ctx: RunContext, pipeline_path: str) -> str:
    """Run attractor status --json on the pipeline file."""
    # Calls: attractor status {pipeline_path} --json
    # Returns: JSON representation of current node states
    result = subprocess.run(
        ["python", ".claude/scripts/attractor/cli.py", "status", pipeline_path, "--json"],
        capture_output=True, text=True
    )
    return result.stdout

@agent.tool
async def get_pipeline_graph(ctx: RunContext, pipeline_path: str) -> str:
    """Parse the DOT file and return node/edge structure as JSON."""
    # Calls: attractor parse {pipeline_path} --output -
    result = subprocess.run(
        ["python", ".claude/scripts/attractor/cli.py", "parse", pipeline_path, "--output", "-"],
        capture_output=True, text=True
    )
    return result.stdout

@agent.tool
async def get_node_details(ctx: RunContext, pipeline_path: str, node_id: str) -> str:
    """Get detailed attributes for a specific node."""
    # Parses DOT file and returns attributes for the given node
    ...

@agent.tool
async def check_checkpoint(ctx: RunContext, pipeline_path: str) -> str:
    """Check if a checkpoint exists and return its contents."""
    # Calls: attractor checkpoint list {pipeline_path}
    ...

# --- Agent Definition ---

pipeline_runner = Agent(
    model="claude-sonnet-4-20250514",
    result_type=RunnerPlan,
    system_prompt="""
    You are a Pipeline Runner agent. Your job is to analyze an Attractor-style
    DOT pipeline graph and determine the next actions to take.

    Rules:
    1. Read the pipeline status first to understand current state.
    2. Identify nodes that are "pending" with all dependencies satisfied.
    3. For each ready node, determine the appropriate action based on handler type:
       - codergen -> spawn_orchestrator (with worker_type from node attributes)
       - wait.human -> dispatch_validation (with mode from node attributes)
       - tool -> execute_tool (with command from node attributes)
       - conditional -> evaluate_condition
       - exit -> signal_finalize (requires all predecessors validated)
    4. Order actions by pipeline dependency (upstream before downstream).
    5. Never propose validating a node that hasn't reached impl_complete.
    6. Never propose spawning a worker for a node whose dependencies aren't validated.
    7. If no actions are possible and pipeline is not complete, report blocked nodes.
    """,
    tools=[get_pipeline_status, get_pipeline_graph, get_node_details, check_checkpoint],
)

# --- POC Execution ---

async def run_poc(pipeline_path: str):
    """Run the POC and print the plan."""
    result = await pipeline_runner.run(
        f"Analyze the pipeline at {pipeline_path} and produce a plan of action."
    )
    plan = result.data

    print(f"Pipeline: {plan.pipeline_id}")
    print(f"Stage: {plan.current_stage}")
    print(f"Summary: {plan.summary}")
    print(f"\nActions ({len(plan.actions)}):")
    for i, action in enumerate(plan.actions, 1):
        print(f"  {i}. [{action.action}] {action.node_id}")
        print(f"     Reason: {action.reason}")
        if action.worker_type:
            print(f"     Worker: {action.worker_type}")
        if action.validation_mode:
            print(f"     Mode: {action.validation_mode}")

    if plan.blocked_nodes:
        print(f"\nBlocked ({len(plan.blocked_nodes)}):")
        for node in plan.blocked_nodes:
            print(f"  - {node}")

if __name__ == "__main__":
    import sys
    asyncio.run(run_poc(sys.argv[1]))
```

### POC Test Cases

1. **Fresh pipeline** (all nodes pending): Should output spawn_orchestrator for the first codergen node after start.
2. **Mid-execution pipeline** (some nodes validated): Should output spawn_orchestrator for the next ready node, skipping validated ones.
3. **Validation needed** (node at impl_complete): Should output dispatch_validation for the wait.human node.
4. **All nodes validated** (ready for finalize): Should output signal_finalize.
5. **Stuck pipeline** (node failed 3x): Should output signal_stuck with failure history.
6. **Parallel pipeline** (multiple ready nodes): Should output multiple spawn_orchestrator actions for concurrent execution.

### POC Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| Correct action identification | Runner identifies the right next action for 6/6 test scenarios |
| Correct dependency evaluation | Runner never proposes an action for a node whose dependencies are unsatisfied |
| Correct handler mapping | codergen -> spawn, wait.human -> validate, exit -> finalize (100% accuracy) |
| Structured output | RunnerPlan parses correctly from agent output for all scenarios |
| Reasonable latency | Plan generation completes in < 30 seconds per pipeline |
| Cost efficiency | Single plan generation costs < $0.05 (Sonnet-class model) |

### POC Files

| File | Purpose |
|------|---------|
| `.claude/scripts/attractor/poc_pipeline_runner.py` | POC agent implementation |
| `.claude/scripts/attractor/poc_test_scenarios.py` | Test scenario runner |
| `.pipelines/examples/poc-fresh.dot` | Test: all nodes pending |
| `.pipelines/examples/poc-midway.dot` | Test: mid-execution state |
| `.pipelines/examples/poc-stuck.dot` | Test: failed node scenario |

### From POC to Production

If the POC validates successfully, the production Pipeline Runner adds:
1. **Action execution**: Actually call `attractor transition`, spawn tmux sessions, dispatch validators.
2. **Event loop**: Wait for orchestrator completion signals instead of one-shot planning.
3. **Checkpoint integration**: Save state after each action.
4. **System 3 communication**: Signal approval requests and completion via SendMessage.
5. **Retry logic**: Automatic retry with feedback injection up to 3x.

---

## 6. Open Questions

### Q1: Persistent Agent or Per-Session Invocation?

**Option A: Persistent agent** -- The Pipeline Runner runs as a long-lived agent (like s3-communicator) that sleeps between events.
- Pro: No startup cost for each event. Maintains context across node completions.
- Con: Consumes resources when idle. Risk of context exhaustion on long pipelines.

**Option B: Per-session invocation** -- System 3 launches the runner for each "round" of graph evaluation.
- Pro: Fresh context every round. No resource waste when idle.
- Con: Startup cost (graph parsing, state loading) on each invocation. No cross-round context.

**Current lean**: Per-session invocation (Option B) for Phase 2. The runner is stateless -- all state is in the checkpoint file. System 3 launches it when an event occurs (orchestrator completion, timer, manual trigger). This is simpler and avoids context exhaustion.

### Q2: How to Handle Multi-Initiative Pipelines?

When System 3 is managing 3 concurrent initiatives (each with its own DOT file), how do runner instances coordinate?

**Option A: Fully independent** -- Each runner knows nothing about other pipelines. System 3 manages cross-pipeline concerns.
- Pro: Simple. No coordination complexity.
- Con: System 3 bears the cognitive load of cross-pipeline coordination.

**Option B: Shared state file** -- Runners read a `multi-pipeline-state.json` that tracks resource allocation (e.g., "only 2 concurrent orchestrators allowed").
- Pro: Automatic resource management.
- Con: Shared state introduces coordination complexity and race conditions.

**Current lean**: Option A (fully independent) for Phase 2. System 3 already manages multi-initiative work manually. The runner automates WITHIN a pipeline, not across pipelines.

### Q3: What is the Right Checkpoint Frequency?

**Options**:
- After every node state transition (current design)
- After every N transitions (batched)
- On a timer (every 60 seconds)
- Only at stage boundaries (PARSE, VALIDATE, INITIALIZE, EXECUTE, FINALIZE)

**Current lean**: After every node state transition. The checkpoint is a single JSON file write (~1KB). The cost is negligible compared to the cost of re-running a failed node. For a 10-node pipeline, this means ~30-40 checkpoints (each node transitions 3-4 times on average).

### Q4: How Should the Engine Communicate with System 3?

**Option A: Native Agent Teams** -- Runner is a teammate of System 3's s3-live team, uses SendMessage.
- Pro: Event-driven (SendMessage triggers immediately). No polling.
- Con: Requires runner to be a persistent team member (conflicts with per-session invocation).

**Option B: Bead status updates** -- Runner updates bead statuses; System 3 monitors bead state.
- Pro: Uses existing infrastructure. Durable. Auditable.
- Con: Polling-based. Adds latency.

**Current lean**: Option A (Native Agent Teams) for Phase 2. The runner is spawned as a background task in the s3-live team with `run_in_background=True`. It uses SendMessage to communicate with System 3. This aligns with the existing s3-live team pattern (s3-communicator, s3-heartbeat, s3-validator are all team members).

### Q5: How Does the Runner Handle Context Exhaustion?

Long pipelines (10+ nodes) may cause the runner to exhaust its context window before completing traversal.

**Options**:
- Compact and continue (if supported by the agent framework)
- Exit and re-launch with fresh context (checkpoint-resume pattern)
- Split pipeline into sub-pipelines at stage boundaries

**Current lean**: Exit and re-launch. The runner's state is fully captured in the checkpoint file. A fresh instance can resume from the exact point of exhaustion. This is the simplest and most reliable approach.

### Q6: Should the Runner Support Pipeline Modification Mid-Execution?

Can System 3 add or remove nodes from a pipeline while the runner is executing?

**Current lean**: No. Pipeline graphs are immutable once execution begins. If changes are needed, System 3 must:
1. Pause the runner (signal via SendMessage)
2. Checkpoint current state
3. Modify the graph
4. Re-validate (`attractor validate`)
5. Resume the runner with the updated graph

This keeps the runner simple and avoids race conditions between graph modification and traversal.

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **Attractor** | Open-source pipeline specification from strongdm (github.com/strongdm/attractor) |
| **DOT** | Graph description language used by Graphviz |
| **Pipeline Runner** | The Phase 2 agent that automates DOT graph traversal |
| **Triple-gate** | Three-layer validation: self-report + validation response + independent verify |
| **Codergen node** | A DOT node representing implementation work (`handler=codergen`) |
| **Validation gate** | A hexagon DOT node representing a validation checkpoint (`handler=wait.human`) |
| **Checkpoint** | A JSON snapshot of pipeline state used for crash recovery |
| **AT pairing** | Convention where every implementation node has a paired validation node |

## Appendix B: Related Documents

| Document | Path | Relationship |
|----------|------|-------------|
| PRD-S3-ATTRACTOR-001 | `.taskmaster/docs/PRD-S3-ATTRACTOR-001.md` | Parent PRD (current phase) |
| Attractor DOT Schema | `.pipelines/schema.md` | DOT vocabulary definition |
| System 3 Output Style | `.claude/output-styles/system3-meta-orchestrator.md` | S3 navigation approach |
| Dual Closure Gate | `.claude/documentation/DUAL_CLOSURE_GATE.md` | Independent validation protocol |
| Completion Promise CLI | `.claude/skills/system3-orchestrator/references/completion-promise-cli.md` | Promise management |
| Monitoring Architecture | `.claude/documentation/SYSTEM3_MONITORING_ARCHITECTURE.md` | Monitor/watcher patterns |
