# PRD-S3-ATTRACTOR-002: Attractor Pipeline Execution Engine

## Overview

Evolve the Attractor DOT pipeline from a **status tracker** (Phase 1, manual CLI navigation by System 3)
to an **execution engine** (Phase 2, programmatic+LLM runner that traverses the graph automatically).

The runner is a Python process that reads a DOT pipeline, evaluates node readiness, spawns workers,
collects validation results, and advances state — while System 3 retains strategic oversight and
business-gate approval authority.

**PRD ID**: PRD-S3-ATTRACTOR-002
**Status**: Draft
**Priority**: P1
**Owner**: System 3 Meta-Orchestrator
**Parent**: PRD-S3-ATTRACTOR-001 (Attractor-Inspired Graph Orchestration)
**Design Doc**: .claude/documentation/PRD-S3-ATTRACTOR-002-design.md
**Target Repository**: claude-harness-setup

---

## Background

### What Phase 1 Delivered (PRD-S3-ATTRACTOR-001)

Phase 1 established the DOT graph as System 3's primary orchestration artifact:
- DOT vocabulary and schema (.cobuilder/schema.md)
- CLI tools: parse, validate, status, transition, checkpoint, generate, node/edge CRUD
- Completion promise integration (cs-init, cs-promise, cs-verify)
- Stop gate integration (blocks session end if pipeline has unvalidated nodes)
- System 3 output style with DOT Graph Navigation workflow

### The Problem: DOT as Status Tracker, Not Execution Engine

A guardian session's honest reflection (2026-02-24) identified the core limitation:

> "The graph gave me a clear sequential plan that survived context compaction — but for actual
> orchestrator dispatch, I still relied on tmux + wisdom files, not the graph. The graph tracked
> state, not execution."

System 3 currently performs **manual graph navigation**: read status, evaluate dependencies,
decide which node is ready, spawn an orchestrator, monitor it, call transition, checkpoint.
Each step consumes context budget on mechanical traversal logic rather than strategic oversight.

### Guardian Reflections — Triage

| Proposed Improvement | Verdict | Rationale |
|---------------------|---------|-----------|
| Auto-dispatch from graph | **Accept** | Core Phase 2 capability. Graph drives execution. |
| Handler execution (wait.human blocks, tool runs commands) | **Accept (modify)** | Event-driven, not literal blocking. Runner reacts to signals. |
| Parallel branch detection | **Already exists** | `status --filter=pending --deps-met` works. Runner acts on it. |
| Pipeline-aware stop gate (checkpoint hash matching) | **Discard** | Over-engineering. Unvalidated-node check is sufficient. |
| Real-time node status via message bus | **Accept** | Runner receives signals, calls transition. Graph IS the state. |
| Validation gate auto-trigger | **Accept** | Runner dispatches validation when codergen hits impl_complete. |
| Evidence auto-linking to nodes | **Accept** | Runner writes evidence_path as node attribute post-validation. |
| Rollback edges in DOT | **Accept (modify)** | Retry logic lives in runner state, not graph edges. Keeps DOT clean. |

---

## Architecture Decision: Agent SDK + GChat

### The Question

Three architectures were evaluated for the Pipeline Runner:

| Architecture | Description | Pros | Cons |
|-------------|-------------|------|------|
| **A: Pure CLI** | Python script with subprocess calls to attractor CLI | Simple, no dependencies | No LLM reasoning for edge cases, brittle error handling |
| **B: PydanticAI agent** | PydanticAI Agent with typed tools and structured output | Typed tools, graph-based workflows via pydantic-graph | Version-sensitive, rapidly evolving framework |
| **C: Claude Agent SDK** | Anthropic Agent SDK with tool loop + GChat webhook | Same runtime as Claude Code, structured output, HTTP-ready | Newer ecosystem, requires Node.js runtime |

### Decision: Architecture C — Claude Agent SDK

**Why Agent SDK over PydanticAI:**

1. **Same runtime as Claude Code.** The Agent SDK IS what Claude Code agents run on internally.
   When we spawn a `Task(subagent_type="backend-solutions-engineer")`, that worker uses the Agent SDK
   under the hood. Using the same SDK for the runner means identical tool behavior, context management,
   and session persistence.

2. **GChat interaction model.** The user wants to interact with the pipeline via Google Chat, not
   the terminal. The Agent SDK wraps cleanly in a FastAPI server that receives GChat webhooks:

   ```
   User (GChat) → FastAPI webhook → Agent SDK query() → attractor CLI → Pipeline state
                                                       → Claude Code spawn → Workers
   ```

3. **Structured output.** The Agent SDK supports Pydantic model output natively via `output_format`.
   The runner produces typed `RunnerPlan` objects — same pattern as the design doc's POC.

4. **Hooks for lifecycle control.** Agent SDK hooks (`PreToolUse`, `PostToolUse`, `Stop`) are
   Python callbacks — no file-based shell scripts. This enables programmatic guard rails:
   - `PreToolUse`: Enforce that the runner never calls `Edit`/`Write` (it's a coordinator, not implementer)
   - `Stop`: Verify all pipeline nodes are terminal before allowing exit
   - `PostToolUse`: Log every attractor CLI call to the audit trail

5. **Session persistence.** `resume=session_id` lets the runner survive crashes and context compaction.
   System 3 or the GChat webhook can restart the runner and it picks up exactly where it left off.

**What the Agent SDK does NOT replace:**
- Claude Code native Agent Teams for worker coordination (orchestrators still spawn workers via `Task` + `TeamCreate`)
- The attractor CLI tools (runner calls them as subprocess tools)
- System 3's strategic role (runner escalates business gates and stuck nodes)

### Channel Adapter Abstraction Layer

While GChat is the **primary** interface, the architecture uses a pluggable adapter pattern
inspired by OpenClaw's Channel interface. Each communication channel (GChat, WhatsApp, web,
Slack, etc.) implements a unified `ChannelAdapter` interface:

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel

class InboundMessage(BaseModel):
    """Normalized inbound message from any channel."""
    channel: str              # "gchat", "whatsapp", "web", "slack"
    sender_id: str            # Channel-specific user identifier
    text: str                 # Raw message text
    thread_id: str | None     # Thread/conversation context
    metadata: dict = {}       # Channel-specific extras (attachments, reactions)

class OutboundMessage(BaseModel):
    """Normalized outbound message to any channel."""
    text: str                 # Plain text content
    card: dict | None = None  # Rich card (channel adapts to its own card format)
    thread_id: str | None     # Reply in thread (if supported)

class ChannelAdapter(ABC):
    """Interface that all communication channel adapters must implement."""

    @abstractmethod
    async def parse_inbound(self, raw_payload: dict) -> InboundMessage:
        """Parse channel-specific webhook payload into normalized InboundMessage."""
        ...

    @abstractmethod
    async def send_outbound(self, message: OutboundMessage, recipient: str) -> dict:
        """Send a normalized OutboundMessage via channel-specific API."""
        ...

    @abstractmethod
    async def verify_webhook(self, request: dict) -> bool:
        """Verify incoming webhook authenticity (token, signature, etc.)."""
        ...

    @abstractmethod
    def format_card(self, pipeline_status: dict) -> dict:
        """Format a pipeline status dict into the channel's native card format."""
        ...
```

**Adapter Registry** — The bridge server dynamically loads adapters based on configuration:

```python
ADAPTERS: dict[str, ChannelAdapter] = {
    "gchat": GChatAdapter(),        # Google Chat (primary, Epic 2)
    # Future adapters:
    # "whatsapp": WhatsAppAdapter(),  # via Baileys/Cloud API
    # "slack": SlackAdapter(),        # via Bolt SDK
    # "web": WebSocketAdapter(),      # Browser-based dashboard
    # "telegram": TelegramAdapter(),  # via grammY
}
```

**Key Design Principles** (from OpenClaw's adapter pattern):
1. **Adapters are thin** — only handle authentication, inbound parsing, and outbound formatting
2. **Business logic lives in the runner** — adapters never make pipeline decisions
3. **Cards are channel-native** — each adapter formats status cards using its platform's rich messaging
4. **Thread affinity** — each pipeline maintains thread context per channel
5. **Multi-channel broadcast** — runner can notify across all registered channels simultaneously

This abstraction means adding WhatsApp or Slack support later requires ONLY implementing a new
`ChannelAdapter` subclass — zero changes to the runner, guard rails, or pipeline logic.

### GChat as Primary Interface

The user interacts with the pipeline runner through Google Chat, not the terminal:

```
┌─────────────────────────────────────────────────────────────────┐
│  USER (Google Chat)                                              │
│                                                                  │
│  "Start pipeline for PRD-AUTH-001"                              │
│  "What's the status?"                                           │
│  "Approve business validation for login feature"                │
│  "Why is node impl_auth stuck?"                                 │
│                                                                  │
│         │ webhook                          ▲ response            │
│         ▼                                  │                     │
│  ┌─────────────────────────────────────────────────────┐        │
│  │  FastAPI Server (gchat-pipeline-bridge)              │        │
│  │                                                      │        │
│  │  POST /webhook/gchat  →  parse intent               │        │
│  │                          │                           │        │
│  │                          ▼                           │        │
│  │                   Agent SDK query()                  │        │
│  │                   (Pipeline Runner)                  │        │
│  │                          │                           │        │
│  │              ┌───────────┼───────────┐              │        │
│  │              ▼           ▼           ▼              │        │
│  │         attractor    tmux spawn   validation        │        │
│  │         CLI tools    orchestrator  dispatch          │        │
│  └─────────────────────────────────────────────────────┘        │
│                                                                  │
│  Hosted: Local Docker container or Railway                      │
└─────────────────────────────────────────────────────────────────┘
```

**Intent classification** (programmatic, not LLM):

| User message pattern | Intent | Runner action |
|---------------------|--------|---------------|
| "start pipeline ..." | `START_PIPELINE` | Load DOT, begin traversal |
| "status" / "what's happening" | `GET_STATUS` | `attractor status --json --summary` |
| "approve ..." | `APPROVE_GATE` | Advance business validation node |
| "reject ..." / "redo ..." | `REJECT_GATE` | Transition to failed, send feedback |
| "why stuck" / "what's blocking" | `DIAGNOSE` | Identify blocked nodes, report deps |
| "stop" / "pause" | `PAUSE_PIPELINE` | Checkpoint, stop spawning new work |
| "skip node ..." | `OVERRIDE_SKIP` | System 3 override, transition with reason |

---

## Goals

1. **Eliminate manual graph navigation.** System 3 no longer calls `attractor status` + `transition`
   in a loop. The runner handles traversal; System 3 handles strategy.

2. **GChat-first interaction.** Users monitor and steer pipeline execution through Google Chat
   rather than attaching to tmux sessions or reading terminal output.

3. **Programmatic guard rails.** The runner enforces anti-gaming rules programmatically
   (no self-validation, fresh evidence, retry limits) rather than relying on LLM instruction following.

4. **Crash-resilient execution.** Pipeline state survives runner crashes, context compaction,
   and session restarts via checkpoint/restore.

5. **Preserve System 3 authority.** Business validation gates require explicit approval.
   System 3 can override, skip, or abort at any time.

---

## Epic 1: Pipeline Runner Agent (Agent SDK)

### Problem
System 3 manually navigates the DOT graph, consuming context budget on mechanical traversal.
Need a purpose-built runner agent that automates the traversal loop.

### Requirements

- R1.1: Pipeline Runner implemented using Claude Agent SDK (`query()` async generator)
- R1.2: Runner reads pipeline DOT file, evaluates node readiness using `attractor status --filter=pending --deps-met`
- R1.3: For ready `codergen` nodes: spawn orchestrator in tmux using node attributes (worker_type, acceptance, bead_id)
- R1.4: For `impl_complete` nodes: dispatch validation-test-agent with `--mode=technical`
- R1.5: For `wait.human` (business gate) nodes: signal for approval, pause until approved
- R1.6: After validation pass: call `attractor transition <node> validated` + `checkpoint save`
- R1.7: After validation fail: call `attractor transition <node> failed`, retry up to 3x with feedback
- R1.8: After 3 failures on same node: report STUCK, pause for intervention
- R1.9: When exit node is reachable (all predecessors validated): signal FINALIZE
- R1.10: Runner produces typed `RunnerPlan` output (Pydantic model) at each evaluation cycle
- R1.11: Runner state persisted in `.cobuilder/state/{pipeline-id}.json`
- R1.12: Evidence auto-linking: after validation, write `evidence_path` attribute on node via `node modify`

### Runner Tools (Agent SDK tool definitions)

| Tool | Purpose | Maps to |
|------|---------|---------|
| `get_pipeline_status` | Read current node states | `attractor status --json` |
| `get_dispatchable_nodes` | Find ready nodes | `attractor status --filter=pending --deps-met --json` |
| `transition_node` | Advance node state | `attractor transition <file> <node> <status>` |
| `save_checkpoint` | Persist state | `attractor checkpoint save <file>` |
| `spawn_orchestrator` | Launch worker in tmux | tmux new-session + ccorch |
| `dispatch_validation` | Run validation-test-agent | subprocess call |
| `send_approval_request` | Signal for business gate approval | GChat webhook or SendMessage |
| `get_node_details` | Read node attributes | DOT parser |
| `modify_node` | Update node attributes (evidence_path) | `attractor node modify` |

### Structured Output

```python
class NodeAction(BaseModel):
    node_id: str
    action: Literal["spawn_orchestrator", "dispatch_validation", "request_approval",
                     "transition", "signal_stuck", "signal_finalize"]
    reason: str
    worker_type: str | None = None
    validation_mode: str | None = None

class RunnerPlan(BaseModel):
    pipeline_id: str
    current_stage: str
    summary: str
    actions: list[NodeAction]
    blocked_nodes: list[str]
    completed_nodes: list[str]
    retry_counts: dict[str, int]
```

### Acceptance Criteria

- AC-1.1: Runner loads a DOT pipeline and produces a correct RunnerPlan for a 3-node pipeline
- AC-1.2: Runner spawns orchestrator in tmux for a ready codergen node with correct attributes
- AC-1.3: Runner dispatches validation-test-agent when codergen node reaches impl_complete
- AC-1.4: Runner pauses at business gate nodes and resumes after approval signal
- AC-1.5: Runner retries failed nodes up to 3x, then reports STUCK
- AC-1.6: Runner transitions all nodes correctly through lifecycle (pending → active → impl_complete → validated)
- AC-1.7: Runner survives crash and resumes from checkpoint (kill runner, restart, verify continuation)
- AC-1.8: Runner writes evidence_path attribute on nodes after successful validation
- AC-1.9: Runner correctly handles parallel fan-out/fan-in (multiple ready nodes dispatched concurrently)
- AC-1.10: Runner never calls Edit/Write (enforced by PreToolUse hook)

### Files

- CREATE: .claude/scripts/attractor/runner.py (Pipeline Runner Agent)
- CREATE: .claude/scripts/attractor/runner_tools.py (Agent SDK tool definitions)
- CREATE: .claude/scripts/attractor/runner_models.py (Pydantic models for structured output)
- CREATE: .claude/scripts/attractor/runner_hooks.py (PreToolUse/PostToolUse/Stop hooks)
- MODIFY: .claude/scripts/attractor/cli.py (add `run` subcommand that launches runner)

---

## Epic 2: Channel Bridge with Adapter Pattern (FastAPI + Webhooks)

### Problem
Users interact with pipelines via terminal/tmux. Need a multi-channel interface where users can
start, monitor, approve, and steer pipeline execution through natural language. GChat is the
primary channel, but the architecture must support adding WhatsApp, Slack, web, and other
channels without modifying core pipeline logic.

### Requirements

- R2.1: FastAPI server wrapping the Pipeline Runner Agent with pluggable channel adapters
- R2.2: `ChannelAdapter` abstract base class with `parse_inbound`, `send_outbound`, `verify_webhook`, `format_card` methods
- R2.3: `GChatAdapter` implementing ChannelAdapter for Google Chat webhooks (POST /webhook/gchat)
- R2.4: Adapter registry: dynamic loading of channel adapters from configuration
- R2.5: Intent classification from normalized `InboundMessage` (programmatic regex/keyword, not LLM)
- R2.6: Status formatting via adapter's `format_card()` — each channel renders natively
- R2.7: Approval flow: user says "approve" → runner advances business gate node (channel-agnostic)
- R2.8: Proactive notifications: runner sends status updates via all registered adapters when nodes complete/fail
- R2.9: Thread management: each pipeline gets its own thread per channel (where supported)
- R2.10: Authentication: each adapter handles its own webhook verification (tokens, signatures, etc.)
- R2.11: Multi-channel broadcast: runner can notify across all active channels simultaneously

### Interaction Patterns

| User Says | Runner Does | GChat Response |
|-----------|------------|----------------|
| "start PRD-AUTH-001" | Load pipeline, begin traversal | "Pipeline started: 5 nodes, 3 codergen, 2 validation gates" |
| "status" | `attractor status --summary` | Card with node progress bars |
| "approve login validation" | Transition business gate → validated | "Login validation approved. Frontend node now dispatching." |
| "reject login validation" | Transition → failed, inject feedback | "Login validation rejected. Feedback sent to orchestrator." |
| "why is auth stuck?" | Read blocked nodes + retry history | "auth_module failed validation 2/3 times. Error: missing error handling in routes.py" |
| "skip database migration" | Override skip with reason | "Skipped database_migration (override). Downstream nodes unblocked." |
| "pause" | Checkpoint, stop new dispatches | "Pipeline paused at checkpoint-007. 2/5 nodes validated." |

### Acceptance Criteria

- AC-2.1: FastAPI server starts and routes incoming webhooks to the correct ChannelAdapter
- AC-2.2: GChatAdapter correctly parses Google Chat webhook payloads into InboundMessage
- AC-2.3: GChatAdapter correctly sends OutboundMessage formatted as GChat cards
- AC-2.4: "start PRD-XXX" message loads pipeline DOT and begins runner traversal (channel-agnostic)
- AC-2.5: "status" returns formatted card via the originating channel's adapter
- AC-2.6: "approve <node>" advances a business gate node (channel-agnostic)
- AC-2.7: Runner sends proactive notifications via all registered adapters when nodes complete/fail
- AC-2.8: Each pipeline conversation lives in its own thread per channel (where supported)
- AC-2.9: Each adapter independently validates its incoming webhooks
- AC-2.10: Server handles multiple concurrent pipeline runners (one per DOT file)
- AC-2.11: Adding a new channel requires ONLY creating a new ChannelAdapter subclass + config entry (no runner/guard rail changes)

### Files

- CREATE: .claude/scripts/attractor/channel_adapter.py (ChannelAdapter ABC + InboundMessage/OutboundMessage models)
- CREATE: .claude/scripts/attractor/adapters/gchat_adapter.py (GChat ChannelAdapter implementation)
- CREATE: .claude/scripts/attractor/adapters/__init__.py (Adapter registry loader)
- CREATE: .claude/scripts/attractor/channel_bridge.py (FastAPI server with adapter routing)
- CREATE: .claude/scripts/attractor/channel_intents.py (Intent classification from normalized messages)
- CREATE: .claude/scripts/attractor/channel_cards.py (Card templating — adapters format natively)
- CREATE: .claude/scripts/attractor/Dockerfile (Container for deployment)
- MODIFY: .mcp.json (add pipeline-bridge as MCP server for Claude Code access)

---

## Epic 3: Guard Rails + Anti-Gaming (Programmatic Enforcement)

### Problem
Phase 1 relies on LLM instruction following for anti-gaming rules (no self-validation, fresh
evidence, retry limits). Need programmatic enforcement that cannot be bypassed.

### Requirements

- R3.1: PreToolUse hook blocks Edit/Write calls from the runner agent
- R3.2: Implementer-validator separation enforced: runner tracks which agent implemented each node, refuses to dispatch the same agent for validation
- R3.3: Evidence timestamping: validation evidence older than most recent impl_complete is rejected
- R3.4: Retry counter persisted in runner state, hard limit of 3 per node
- R3.5: Audit trail: every transition logged to `{pipeline-id}-audit.jsonl` (append-only)
- R3.6: Acceptance criteria immutability: runner rejects node modifications that weaken `acceptance` attribute after graph validation
- R3.7: Random spot-check selection: 20% of validated nodes flagged for System 3 re-verification (selection based on hash of session_id + node_id for deterministic but unpredictable sampling)

### Acceptance Criteria

- AC-3.1: Runner crashes if it attempts Edit/Write (PreToolUse hook blocks with error)
- AC-3.2: Runner refuses to dispatch validation-test-agent for a node that was implemented by the same agent session
- AC-3.3: Evidence with timestamp before latest impl_complete is rejected (validation re-triggered)
- AC-3.4: After 3 failures on same node, runner transitions to STUCK and stops retrying
- AC-3.5: Audit JSONL contains: timestamp, node_id, from_status, to_status, agent_id, evidence_hash
- AC-3.6: `attractor validate` rejects graphs where acceptance text was shortened after initial validation
- AC-3.7: Spot-check selection is deterministic (same session+node → same selection) but unpredictable

### Files

- CREATE: .claude/scripts/attractor/runner_hooks.py (expanded with guard rail hooks)
- CREATE: .claude/scripts/attractor/anti_gaming.py (evidence validation, implementer tracking)
- MODIFY: .claude/scripts/attractor/validator.py (acceptance immutability check)
- MODIFY: .claude/scripts/attractor/transition.py (audit trail logging)

---

## Epic 4: Spike POC — 3-Node Pipeline Runner

### Problem
Need to validate the Agent SDK approach before committing to full implementation.
Build a minimal runner that traverses a 3-node pipeline and produces structured output.

### Requirements

- R4.1: Spike uses Claude Agent SDK `query()` with 4 read-only tools
- R4.2: Input: path to a DOT pipeline file
- R4.3: Output: typed `RunnerPlan` with ordered actions
- R4.4: No execution — the spike plans but does not act (no tmux, no validation dispatch)
- R4.5: Test against 6 scenarios from design doc Section 5 (fresh, mid-execution, validation needed, all validated, stuck, parallel)
- R4.6: Validate structured output parsing with Pydantic model
- R4.7: Measure latency (<30s) and cost (<$0.05 per plan generation)

### Acceptance Criteria

- AC-4.1: Spike produces correct RunnerPlan for all 6 test scenarios
- AC-4.2: Runner never proposes action for a node whose dependencies are unsatisfied
- AC-4.3: Handler mapping correct: codergen → spawn, wait.human → validate, exit → finalize
- AC-4.4: RunnerPlan parses to Pydantic model without validation errors for all scenarios
- AC-4.5: Plan generation completes in <30s per pipeline
- AC-4.6: Single plan generation costs <$0.05 (Sonnet-class model)

### Files

- CREATE: .claude/scripts/attractor/poc_runner.py (Spike implementation)
- CREATE: .claude/scripts/attractor/poc_test_scenarios.py (6 test scenario DOT files)
- CREATE: .claude/scripts/attractor/poc_results.md (Spike results and decision record)

---

## Epic 5: System 3 + Guardian Integration

### Problem
System 3 and the s3-guardian need updated workflows to use the runner instead of manual navigation.

### Requirements

- R5.1: System 3 output style updated: DOT Graph Navigation section replaced with "Pipeline Runner Delegation"
- R5.2: System 3 launches runner via `attractor run <pipeline.dot>` instead of manual traversal loop
- R5.3: System 3 receives runner signals (STUCK, FINALIZE, APPROVAL_NEEDED) via message bus or GChat
- R5.4: System 3 handles business gate approvals via GChat or direct command
- R5.5: s3-guardian SKILL.md Phase 4 updated: DOT pipeline validation reads runner audit trail
- R5.6: s3-guardian can interact with pipeline via GChat (monitor, approve, intervene)
- R5.7: Runner-to-System-3 handoff: when runner signals FINALIZE, System 3 runs cs-verify triple-gate

### Acceptance Criteria

- AC-5.1: system3-meta-orchestrator.md has "Pipeline Runner Delegation" section replacing manual DOT navigation
- AC-5.2: `attractor run` CLI subcommand launches the runner agent
- AC-5.3: System 3 receives and acts on runner STUCK signal within 60s
- AC-5.4: s3-guardian validates pipeline completion using runner audit trail as evidence
- AC-5.5: Full pipeline traversal works end-to-end: System 3 launches runner, runner traverses, System 3 finalizes

### Files

- MODIFY: .claude/output-styles/system3-meta-orchestrator.md
- MODIFY: .claude/skills/s3-guardian/SKILL.md
- MODIFY: .claude/skills/system3-orchestrator/SKILL.md
- MODIFY: .claude/scripts/attractor/cli.py (add `run` subcommand)

---

## Implementation Order

```
Epic 4 (Spike POC)          ← FIRST: Validate Agent SDK approach
    │
    ▼ spike passes
Epic 1 (Pipeline Runner)    ← Core runner with all tools
    │
    ├──► Epic 3 (Guard Rails)  ← Can be built in parallel with Epic 2
    │
    └──► Epic 2 (GChat Bridge) ← Wrap runner in FastAPI
             │
             ▼
         Epic 5 (Integration)  ← Wire into System 3 + Guardian
```

**Phase gate after Epic 4:** If the spike shows that Agent SDK graph reasoning is unreliable
(wrong actions, missed dependencies, poor structured output), fall back to Architecture A
(pure programmatic CLI runner) or Architecture B (PydanticAI with explicit graph nodes).

## Dependencies

- Epic 1 depends on Epic 4 (spike must pass before full implementation)
- Epic 2 depends on Epic 1 (GChat bridge wraps the runner)
- Epic 3 depends on Epic 1 (guard rails hook into runner lifecycle)
- Epic 5 depends on Epics 1, 2, and 3 (integration requires all components)
- All epics depend on PRD-S3-ATTRACTOR-001 (existing CLI tools, schema, DOT vocabulary)

## Key Risks

| Risk | Mitigation |
|------|------------|
| Agent SDK graph reasoning unreliable | Spike POC validates before commitment. Fallback to PydanticAI/pure CLI. |
| GChat latency for approval gates | Approval timeout (5 min default). Runner continues other ready nodes while waiting. |
| Runner-orchestrator coordination race conditions | File-level locking on DOT file (already implemented in transition.py). Message bus for signals. |
| Runner context exhaustion on large pipelines | Session persistence via `resume=session_id`. Runner state in external JSON, not context. |
| Anti-gaming circumvention by sophisticated agents | Programmatic enforcement (Epic 3) makes gaming structurally impossible, not just instructionally discouraged. |

## Success Metrics

| Metric | Phase 1 (Current) | Phase 2 (Target) |
|--------|-------------------|-------------------|
| System 3 context on graph navigation | ~30% of session budget | <5% (launch runner, handle signals) |
| Time to detect stuck node | 5-15 min (manual poll) | <60s (runner signals immediately) |
| Validation gate latency | Manual dispatch by System 3 | Automatic dispatch on impl_complete |
| User pipeline visibility | Terminal/tmux only | GChat cards with real-time updates |
| Anti-gaming enforcement | LLM instruction following | Programmatic (unhackable) |

---

**Version**: 1.1 (Draft — adapter abstraction layer added)
**Date**: 2026-02-24
**Author**: System 3 Meta-Orchestrator
**Design Doc**: .claude/documentation/PRD-S3-ATTRACTOR-002-design.md
