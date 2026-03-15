---
prd_id: PRD-HARNESS-UPGRADE-001
title: System 3 Self-Management Upgrade
status: active
created: 2026-03-06T00:00:00.000Z
last_verified: 2026-03-07T00:00:00.000Z
grade: authoritative
---
# PRD-HARNESS-UPGRADE-001: System 3 Self-Management Upgrade

## 1. Executive Summary

The System 3 meta-orchestrator and its supporting harness have proven the core architecture: DOT pipelines, headless worker dispatch, signal-file coordination, and multi-level agent hierarchy all work end-to-end (validated in `ATTRACTOR-E2E-ANALYSIS.md`, 2026-03-06). However, four structural gaps and one architectural insight emerged from production use:

1. **Scope drift**: PRDs evolve during implementation without a frozen contract. Workers operate against moving targets, producing artifacts that no longer match the original intent.
2. **SD version pollution**: Solution Designs are edited in-place during research/refine cycles. By the time a codergen worker reads the SD, it may contain inline annotations (`// Validated via...`) or outdated patterns from earlier iterations.
3. **Missing E2E validation gates**: Epic-level completion is declared based on unit-level checks (`validation-test-agent --mode=unit`). Gherkin E2E scenarios exist but are not structurally enforced in the pipeline topology.
4. **Skills and sub-agent dispatch unused**: Agent definitions exist but have no dispatch mechanism in the DOT pipeline schema. More critically, the rich `.claude/skills/` library (research-first, acceptance-test-writer, react-best-practices, etc.) is not injected into worker prompts — workers operate without the domain skills that would guide their work.
5. **Graph traversal LLM overhead** (architectural insight): The E2E analysis proved that the guardian layer spends ~$4.91 (33 LLM turns) on purely deterministic work: DOT parsing, graph traversal, state transitions, PID polling. The guardian concept dissolves; a pure Python state machine does this in milliseconds for $0, while System 3 remains as top-level strategic authority.

This PRD addresses all five gaps across three phases: Protocol Layer (documentation), Schema & Tooling (code), and Architecture Vision (future).

**Evidence base**: `.cobuilder/ATTRACTOR-E2E-ANALYSIS.md` — full pipeline run analysis showing $10.77 total cost ($4.91 guardian + $5.86 worker) with 46% savings achievable by replacing guardian graph traversal with a pure Python runner.

## 2. Goals

| ID | Goal | Success Metric |
| --- | --- | --- |
| G1 | Eliminate scope drift | PRD Contract generated alongside every PRD; scope freeze verified at every epic boundary by `wait.cobuilder` gate |
| G2 | Prevent SD version pollution | SD git-tagged before codergen dispatch; worker task prompt references frozen tag; SD hash in signal evidence |
| G3 | Enforce E2E validation per epic | Full cluster topology enforced: `acceptance-test-writer -> research -> refine -> codergen -> wait.cobuilder[e2e] -> wait.human[e2e-review]`; `cobuilder validate` rejects non-compliant pipelines |
| G4 | Activate specialist agents with skill injection | Agent definitions reference required skills (`skills_required` in frontmatter); dispatch layer injects `Skill()` invocations into worker prompts; `validation-test-agent`, `ux-designer` dispatchable via DOT `worker_type` |
| G5 | Worker visibility via concern queue and validation reflection | Workers write `concerns.jsonl`; `wait.cobuilder` gate reads concerns + reflects via Hindsight before validation; failed gates can requeue predecessor codergen nodes |
| G6 | Pure Python pipeline execution | Graph traversal requires 0 LLM tokens; LLMs only invoked for actual work nodes |
| G7 | Eliminate graph traversal LLM overhead | $0 graph traversal cost per pipeline run (down from ~$4.91 per run) |

## 3. User Stories

### US-1: Guardian Freezing a PRD
As System 3, when I finalize a PRD and its Solution Designs, I want a `prd-contract.md` automatically generated containing 3-5 domain-invariant truths, scope boundaries, and compliance flags — so that downstream `wait.cobuilder` gates can verify that implementation hasn't drifted from the original intent.

### US-2: Worker Reading a Frozen SD
As a worker dispatched by the pipeline runner, I want my task prompt to reference a specific git-tagged version of the Solution Design — so that even if the SD is refined after my dispatch, I work against the version that was validated by the research/refine chain.

### US-3: Pipeline Enforcing E2E Gates
As a pipeline author, I want `cobuilder pipeline validate` to reject any pipeline where a codergen node cluster lacks the full topology (`acceptance-test-writer -> ... -> codergen -> wait.cobuilder[e2e] -> wait.human[e2e-review]`) — so that no epic can complete without structured E2E validation.

### US-4: Dispatching a Worker with Skill Injection
As the pipeline runner, when a codergen node has `worker_type="frontend-dev-expert"`, I want the dispatch layer to load the agent definition from `.claude/agents/frontend-dev-expert.md`, read its `skills_required` field, and inject `Skill("react-best-practices")` into the worker's initial prompt — so that workers receive domain-specific guidance from the skills library.

### US-5: Running a Pipeline Without Guardian LLM
As a pipeline operator, I want to run `python3 pipeline_runner.py --dot pipeline.dot` and have the entire graph traversal, state transitions, signal polling, and checkpoint management happen in pure Python — so that the only LLM cost is for actual implementation work at codergen/research/refine nodes.

### US-6: Viewing Worker Concerns Before Validation
As the pipeline runner, during a `wait.cobuilder` gate, I want to read a `concerns.jsonl` file populated by workers, reflect via Hindsight on the concerns and confidence trend, then decide whether to proceed with E2E testing or requeue the codergen node for another attempt — so that validation is informed by worker feedback.

## 4. Phase 1: Protocol Layer (E0-E3)

Phase 1 consists of documentation changes that System 3 can make directly. No guardian/runner dispatch needed — these are updates to schema docs, workflow references, skills, and output styles.

### Epic 0 — Pipeline Progress Monitor (s3-guardian Enhancement)

**Goal**: Enhance the s3-guardian skill so that System 3 can launch a Haiku 4.5 sub-agent to monitor pipeline runner progress, reporting back when intervention is needed.

**Scope**:
- New sub-agent pattern in s3-guardian SKILL.md: "Progress Monitor" mode
- System 3 spawns Haiku 4.5 sub-agent via `Task(subagent_type="monitor", model="haiku")`
- Monitor polls signal directory for state changes (new/modified signal files)
- Monitor reads DOT graph file for node status transitions
- Stall detection: no state change in >N minutes triggers report to System 3
- Error detection: failed node or unexpected state triggers immediate report
- Completion detection: all nodes terminal triggers completion report
- Monitor completes (waking System 3) only when attention is needed — cyclic re-launch pattern

**Files changed**: s3-guardian `SKILL.md`, s3-guardian `references/monitoring-patterns.md`

**Acceptance criteria**:
- AC-0.1: s3-guardian SKILL.md documents the progress monitor sub-agent pattern
- AC-0.2: Monitor poll mechanism documented (signal dir + DOT file mtime)
- AC-0.3: Stall/error/completion detection rules documented with thresholds

### Epic 1 — Node Semantics Clarification

**Goal**: Formalize `wait.cobuilder` and `wait.human` as first-class handler types with mandatory topology rules.

**Scope**:
- Schema docs: `wait.cobuilder` defined as a two-stage automated gate:
  - Stage 1 (at `impl_complete`): Runner dispatches `validation-test-agent` via AgentSDK for technical checks (tests pass, code compiles, contract invariants hold). On success → `validated`.
  - Stage 2 (at `validated`): System 3's Haiku monitor wakes System 3 to run blind Gherkin E2E acceptance tests (with access to Chrome MCP tools for browser testing), checks PRD Contract. On success → `accepted`. On failure → rejection signal, runner can requeue predecessor.
  No human prompt at either stage.
- Schema docs: `wait.human` defined as review gate (always follows `wait.cobuilder` or `research`; always triggers `AskUserQuestion` with `summary_ref`)
- Mandatory topology — full codergen cluster:
```
  acceptance-test-writer -> research -> refine -> codergen -> wait.cobuilder[e2e] -> wait.human[e2e-review]
```
- Node attribute schema: `gate_type` (enum: "unit", "e2e", "contract"), `summary_ref` (file path), `contract_ref` (file path)
- Retry mechanism: when `wait.cobuilder` fails, runner can transition predecessor codergen node back to `pending` for requeue

**Files changed**: `agent-schema.md` (docs section), `guardian-workflow.md`, `output-styles/system3-meta-orchestrator.md`

**Acceptance criteria**:
- AC-1.1: `wait.cobuilder` and `wait.human` fully documented with attribute schemas
- AC-1.2: Full cluster topology rule documented with examples (acceptance-test-writer through wait.human)
- AC-1.3: Existing pipeline examples updated to include the mandatory cluster topology
- AC-1.4: `wait.cobuilder` execution context documented (who runs it, Chrome MCP access)
- AC-1.5: Node requeue mechanism documented (failed gate -> codergen back to pending)

### Epic 2 — PRD Contract + E2E Gate Protocol

**Goal**: Define the PRD Contract artifact and integrate E2E gates into the pipeline workflow.

**Scope**:
- Phase 0 Checkpoint A.5: generate `prd-contract.md` alongside PRD (3-5 domain-invariant truths, scope freeze boundary, compliance flags)
- Contract template follows doc-gardener conventions: YAML frontmatter with `contract_version`, `content_hash` (SHA256 of body), `frozen_at_commit`
- `guardian-workflow.md`: contract validation added to `wait.cobuilder` processing logic
- `phase0-prd-design.md`: E2E gate rule (every epic cluster requires the full topology), compliance gate rule
- `SKILL.md`: `prd-contract.md` added to Phase 0 artifact list
- Contract amendment: edit the file directly, increment `contract_version` in frontmatter, doc-gardener validates structure on commit

**Files changed**: `phase0-prd-design.md`, `guardian-workflow.md`, `SKILL.md`, new template `prd-contract-template.md`

**Acceptance criteria**:
- AC-2.1: PRD Contract template exists with required sections (invariants, scope freeze, compliance flags) and doc-gardener-compatible frontmatter
- AC-2.2: Phase 0 workflow includes contract generation step
- AC-2.3: `wait.cobuilder` gate logic references contract for validation
- AC-2.4: Contract amendment is a frontmatter version increment (no external script)

### Epic 3 — Workflow Protocol Enhancements

**Goal**: Add SD version pinning, confidence baselines, skill-first dispatch, validation reflection at gates, session handoff, living narrative, concern queues, and signal directory mitigation to the workflow protocols.

**Scope**:
- **SD version pinning**: git tag after refine node completes; worker task prompt references frozen tag; `sd_hash` attribute on codergen nodes
- **Confidence baseline**: Hindsight `retain()` after every `wait.cobuilder` gate; startup `reflect()` query for prior confidence trend
- **Skill-first dispatch table**: lookup table in `guardian-workflow.md` mapping node intent to skill invocation + skill injection into worker prompts
- **Validation reflection at wait.cobuilder**: before running E2E tests, the validation agent reads signal files from workers, reflects via Hindsight, and decides whether to proceed or requeue the codergen node (by transitioning it back to `pending` in the DOT graph)
- **Session handoff**: `.claude/progress/{session-id}-handoff.md` written at end of turn, read first on startup
- **Living narrative**: System 3 appends to `.claude/narrative/{initiative}.md` after each epic completion
- **Concern queue**: workers write to `concerns.jsonl`; `wait.cobuilder` reads and processes concerns
- **Signal dir mitigation**: `ATTRACTOR_SIGNAL_DIR` env var documented as preflight check

**Files changed**: `guardian-workflow.md`, `phase0-prd-design.md`, `output-styles/system3-meta-orchestrator.md`

**Acceptance criteria**:
- AC-3.1: SD version pinning protocol documented with git tag naming convention
- AC-3.2: Concern queue format (JSONL schema) documented
- AC-3.3: Validation reflection protocol at wait.cobuilder documented (signal file check + Hindsight reflect + requeue decision)
- AC-3.4: Session handoff format documented
- AC-3.5: Living narrative append protocol documented

## 5. Phase 2: Schema & Tooling (E4-E7)

Phase 2 involves code changes. Each epic MUST be implemented via the pipeline runner dispatching AgentSDK workers — not System 3 direct.

### Epic 4 — Sub-Agent Registry + Skill Injection

**Goal**: Create a complete agent registry with all specialist sub-agent definitions and wire skill injection into the dispatch layer.

**Scope**:
- Verify/create: `.claude/agents/solution-architect.md`, `.claude/agents/validation-test-agent.md`, `.claude/agents/ux-designer.md`
- **Skill injection**: Each agent definition gets a `skills_required` field in frontmatter:
```yaml
  skills_required: [react-best-practices, frontend-design]
```
- Dispatch layer reads `skills_required` and injects `Skill("skill-name")` invocations into the worker's initial prompt
- `agent-schema.md`: `worker_type` enum with all 6 agent types (`frontend-dev-expert`, `backend-solutions-engineer`, `tdd-test-engineer`, `solution-architect`, `validation-test-agent`, `ux-designer`)
- Output style Step 2: startup confidence reflection query referencing agent capability assessments

**Files changed**: `.claude/agents/*.md` (verify/update), `agent-schema.md`, `dispatch_worker.py`, `output-styles/system3-meta-orchestrator.md`

**Acceptance criteria**:
- AC-4.1: All 6 agent types have `.claude/agents/*.md` definition files with `skills_required` in frontmatter
- AC-4.2: `agent-schema.md` `worker_type` enum includes all 6 types with descriptions
- AC-4.3: `dispatch_worker.py` loads agent definition and injects skill invocations from `skills_required`
- AC-4.4: Missing agent definition is a hard error (not silent fallback to generic prompt)

### Epic 5 — Attractor Schema + Validate CLI Extension

**Goal**: Extend the DOT schema and `cobuilder pipeline validate` to enforce the new topology rules and attributes.

**Scope**:
- Schema code: `wait.cobuilder` handler implementation with `gate_type`, `summary_ref`, `contract_ref` attributes
- Schema code: `epic_id` attribute on all nodes (for epic-level clustering)
- Schema code: `solution_design_hash` attribute on codergen nodes (SHA256 of frozen SD)
- Schema code: `sd_path` as mandatory attribute on codergen nodes (from E2E analysis Issue 3) — hard error, no backward compatibility
- `cobuilder pipeline validate` extensions:
  - Full cluster topology check: every epic must have `acceptance-test-writer -> ... -> codergen -> wait.cobuilder -> wait.human`
  - `worker_type` registry check: unknown value = hard error
  - `wait.human`/`wait.cobuilder` topology validation: `wait.human` must follow `wait.cobuilder` or `research`
  - `skills_required` validation: referenced skills must exist in `.claude/skills/`
- `--mode=python` flag on runner for Python runner mode

**Files changed**: `agent-schema.md`, `validator.py`, `cobuilder/pipeline/` validation rules, `runner.py`

**Acceptance criteria**:
- AC-5.1: `sd_path` mandatory on codergen nodes; validate rejects nodes without it (hard error)
- AC-5.2: Full cluster topology check implemented and tested
- AC-5.3: `worker_type` registry check rejects unknown agent types
- AC-5.4: `wait.human` after `wait.cobuilder` topology enforced
- AC-5.5: `--mode=python` flag accepted by runner.py

### Epic 6 — Dispatch Worker Enhancements (SDK Mode)

**Goal**: Improve worker dispatch via `claude_code_sdk` with permission bypass, SD wiring, skill injection, and signal coordination.

**Scope** (adjusted from E2E analysis — Issues 1-3 are in-progress fixes):
- **In-progress fixes** (from E2E analysis):
  - MCP permission bypass: `permission_mode="bypassPermissions"` in `ClaudeCodeOptions` (workers keep MCP tools available but skip interactive permission dialogs) (Issue 1)
  - `sd_path` wiring: `build_worker_initial_prompt()` reads SD content from `sd_path` dot attribute (Issue 3)
  - Write/Edit examples: extracted to `.claude/agents/worker-tool-reference.md` (Issue 2, see E7.1)
- **New work**:
  - `ATTRACTOR_SIGNAL_DIR` env var: dispatch_worker passes signal directory path to worker subprocess
  - `CONCERNS_FILE` env var: worker can write concerns to a known JSONL path
  - Skill injection: read `skills_required` from agent definition, inject `Skill()` calls into initial prompt
  - SD hash verification: SHA256 of frozen SD content stored in signal evidence file
- **AgentSDK dispatch**: All dispatch paths use `claude_code_sdk` (`_run_agent()`). All workers are AgentSDK workers.

**Files changed**: `dispatch_worker.py`, `runner.py`

**Acceptance criteria**:
- AC-6.1: Workers run without MCP permission dialogs (bypassPermissions)
- AC-6.2: Workers receive real SD content in their initial prompt (not null)
- AC-6.3: Skill invocations injected into worker initial prompt from `skills_required`
- AC-6.4: `ATTRACTOR_SIGNAL_DIR` env var set for worker subprocesses
- AC-6.5: Signal evidence includes `sd_hash` field

### Epic 7.1 — Worker Prompt Restructuring (Prerequisite for E7.2)

**Goal**: Reduce the 21K worker system prompt to ~3K of essential role/tool guidance, and restructure the initial prompt so the worker's first action is reading its PRD and SD. This fixes the observed problem where task-specific instructions (acceptance criteria, file scope exclusions) are buried in a massive system prompt and ignored by the worker.

**Key insight** (from PRD-ENV-MODEL-001 pipeline run, Logfire trace analysis): A worker spent 14 of 19 turns on investigation before implementing, then modified a file its acceptance criteria explicitly excluded (`spawn_orchestrator.py`). Root cause: the 21K system prompt contained pipeline orchestration docs, signal protocol instructions, and merge queue guidance — none relevant to a focused implementation worker. The actual task was diluted.

**Scope**:
- **Slim \****`build_system_prompt()`** in `runner.py`: Remove pipeline orchestration docs (~6K), signal protocol instructions (~5K), and merge queue guidance that are guardian-level concerns. Keep: role description (~1K), tool allowlist with usage examples (~2K), "read your SD first" directive.
- **Restructure \****`build_initial_prompt()`** in `runner.py`: The initial prompt becomes the worker's primary briefing:
  1. PRD path + SD path + specific section reference
  2. Acceptance criteria (from DOT node)
  3. Directive: "The SD describes the intended approach and the AC defines success criteria. Use your judgment on implementation details."
- **Extract tool examples to reference file**: Move detailed tool usage examples (Write params, Edit syntax, boolean formats) to `.claude/agents/worker-tool-reference.md` that the worker can Read on demand, rather than loading them into every system prompt.
- **Parallel change in \****`guardian.py`**: Apply same slimming to guardian's `build_system_prompt()` (guardian prompt also contains irrelevant worker-level guidance).

**Evidence**: Logfire traces `019cc53082f3f45d35ae3b147d59d76e` through `019cc537ab8c263d2a1362b8ae08e1d4` — worker system prompt was 21,821 chars; initial prompt was 697 chars. The ratio should be inverted.

**Files changed**: `runner.py` (`build_system_prompt()`, `build_initial_prompt()`), `guardian.py` (`build_system_prompt()`), new file `.claude/agents/worker-tool-reference.md` (extracted tool examples)

**Acceptance criteria**:
- AC-7.1.1: Worker system prompt is under 4K chars (down from 21K)
- AC-7.1.2: Worker initial prompt contains PRD path, SD path, and AC as the primary content
- AC-7.1.3: Initial prompt includes directive giving worker judgment on implementation details
- AC-7.1.4: Tool usage examples are available as a reference file, not embedded in system prompt
- AC-7.1.5: Guardian system prompt is similarly slimmed (no worker-level guidance)
- AC-7.1.6: All existing tests pass; existing pipelines produce equivalent results

### Epic 7.2 — Pure Python DOT Runner

**Goal**: Implement the 3-layer architecture (System 3 -> Runner -> Workers) as a pure Python state machine for graph traversal, eliminating ~$4.91 per pipeline run. The guardian concept dissolves; System 3 remains as top-level authority.

**Prerequisite**: Epic 7.1 (worker prompt restructuring). The Python runner dispatches workers directly — it must dispatch workers that receive well-structured, concise prompts rather than the current 21K system prompt.

**Key insight** (from E2E analysis Issue 4): The guardian LLM spent 33 turns on entirely deterministic work — DOT parsing, graph traversal, state transitions, PID polling. None require language model reasoning. A 50-line Python loop does this in milliseconds.

**Scope**:
- New file: `.claude/scripts/attractor/pipeline_runner.py`
- Handler dispatch table mapping DOT node `handler` attribute to pure Python functions
- Signal-file wait: runner uses watchdog-based file monitoring on `{signal_dir}/` for worker completion signals
- Checkpoint after every transition
- Parallel dispatch via asyncio for independent ready nodes
- `_handle_gate()`: two-stage gate processing:
  - Stage 1 (at `impl_complete`): dispatches `validation-test-agent` via AgentSDK for technical checks (tests pass, code compiles, contract invariants hold). On success, transitions node to `validated`.
  - Stage 2 (at `validated`): System 3's Haiku monitor detects the `validated` status and wakes System 3 to run blind Gherkin E2E acceptance tests. System 3 writes acceptance signal → runner transitions to `accepted`.
- Retry: on validation failure, can transition predecessor codergen back to `pending`
- `--mode=python` flag on `spawn_orchestrator.py`
- All worker dispatch via `claude_code_sdk` (AgentSDK). No headless CLI or tmux dispatch.

**3-Layer Architecture**:
```
System 3 (LLM — blind Gherkin E2E at gate boundaries, ACCEPT/REJECT)
  │
  pipeline_runner.py (Python, $0 — persistent, watchdog monitoring, graph traversal, dispatch)
  │
  Workers (AgentSDK — codergen, research, refine, validation-test-agent)
```

**Handler registry**:
| Handler | Python Function | LLM Needed? |
| --- | --- | --- |
| `codergen` | `_handle_codergen()` — dispatch AgentSDK worker | No (dispatch only) |
| `research` | `_handle_research()` — dispatch AgentSDK research worker | No (dispatch only) |
| `refine` | `_handle_refine()` — dispatch AgentSDK refine worker | No (dispatch only) |
| `tool` | `_handle_tool()` — `subprocess.run(command)` | No |
| `wait.cobuilder` | `_handle_gate()` — dispatch validation agent (AgentSDK), signal System 3 | Yes (validation agent) |
| `wait.human` | `_handle_human()` — emit GChat, poll for response signal | No |
| `conditional` | `_handle_conditional()` — evaluate condition expr | No |
| `parallel` | `_handle_parallel()` — asyncio fan-out/fan-in | No |
| `start` | `_handle_noop()` | No |
| `exit` | `_handle_exit()` | No |

The `wait.cobuilder` handler is the only handler that involves LLM cost, and that cost is borne by the validation agent (AgentSDK worker) and System 3 (blind Gherkin E2E) — not by the runner itself. The runner's role is purely dispatch and status tracking. The `accepted` status is written by System 3 after successful Gherkin E2E; on failure, System 3 writes a rejection signal and the runner can requeue the predecessor.

**Signal-file wait mechanism**: Workers write `{signal_dir}/{node_id}.json` on completion. Runner uses watchdog-based file monitoring on the signal directory — when a new or modified file is detected, the runner processes the corresponding node state transition. This replaces mtime-based polling with event-driven monitoring.

**Migration path**:
1. `pipeline_runner.py` created alongside existing `runner.py` (non-breaking)
2. Activated via `--mode=python` flag
3. Default switches to `--mode=python` after validation period
4. `runner.py` kept for debugging/fallback

**Files changed**: `pipeline_runner.py` (new), `spawn_orchestrator.py` (flag), `launch_guardian.py` (optional bypass)

**Acceptance criteria**:
- AC-7.2.1: `pipeline_runner.py` exists, imports cleanly, `--help` works
- AC-7.2.2: `_find_dispatchable_nodes()` returns only nodes with all deps accepted
- AC-7.2.3: `_handle_codergen()` calls `dispatch_worker.py` with correct args including skill injection
- AC-7.2.4: `_handle_tool()` runs command and writes signal without any LLM call
- AC-7.2.5: `_handle_gate()` reads signals, reflects via Hindsight, runs E2E tests
- AC-7.2.6: Full pipeline run on `simple-pipeline.dot` completes with 0 LLM graph traversal tokens
- AC-7.2.7: Signal-file wait uses watchdog-based file monitoring
- AC-7.2.8: Multiple ready nodes dispatched concurrently via asyncio

## 6. Phase 3: Architecture Vision (E8-E12)

Phase 3 epics are future work (~6-12 months). Documented here for strategic alignment; no immediate implementation.

### Epic 8 — Initiative Graph
Shared state object at `.claude/state/initiative.json` tracking all active initiatives, their pipelines, and cross-initiative dependencies.

### Epic 9 — Persistent System 3 Controller
Long-running process replacing episodic sessions. Maintains state across initiatives without session handoff overhead.

### Epic 10 — Epic-Scoped Runners + Parallel Execution
Each epic gets its own Python runner instance in a separate worktree. Independent epics execute in parallel via asyncio, with dependency-aware scheduling.

### Epic 11 — Async Human Review Queue
GChat or web interface for non-blocking human review. Pipeline continues with other nodes while `wait.human` gates are pending.

### Epic 12 — Graduated Autonomy Model
Levels 1-3 autonomy based on PRD Contract satisfaction track record. New initiatives start at Level 1 (every gate requires human review); proven domains graduate to Level 3 (auto-approve).

## 7. Technical Approach

### DOT Pipeline Execution Model

The pipeline is a directed acyclic graph (DAG) encoded in DOT format. Each node has a `handler` attribute that determines its execution strategy. The state machine transitions nodes through: `pending -> active -> impl_complete -> validated -> accepted` (or `failed`).

- `impl_complete`: Worker self-reports completion
- `validated`: Validation agent (runner-dispatched via AgentSDK) confirms technical correctness (tests pass, code compiles, contract invariants hold)
- `accepted`: System 3 independently confirms business requirements via blind Gherkin E2E scenarios

**3-Layer Architecture**:
```
System 3 (LLM — strategic authority, blind Gherkin E2E, final ACCEPT/REJECT)
  │
  pipeline_runner.py (Python — persistent, watchdog file monitoring, graph traversal, dispatch, $0)
  │
  Workers (AgentSDK — codergen, research, refine, validation)
```

The guardian concept dissolves: System 3 remains as the top-level strategic authority responsible for blind Gherkin E2E acceptance and final ACCEPT/REJECT decisions. The Python runner replaces the guardian's graph traversal role with zero LLM intelligence. System 3 E2E cost is separate and only incurred at gate boundaries (not per-node).

### Cost Model (from E2E analysis)

| Layer | Current Cost | After E7.2 |
| --- | --- | --- |
| Guardian/Runner | $4.91 (LLM, 33 turns) | ~$0 (Python) |
| Worker (per node) | $5.86 (LLM, 37 turns) | $5.86 (unchanged) |
| System 3 E2E (per gate) | N/A (manual) | ~$0.50 (Haiku monitor + blind Gherkin) |
| **Total per node** | **\~$10.77** | **\~$5.86 + gate cost at epic boundaries** |
| **Savings** |  | **\~46%** |

Note: Worker cost in the E2E run was inflated because the worker had no real SD content (Issue 3) and a 21K system prompt diluted the task (see E7.1). With proper SD wiring (E6) and prompt restructuring (E7.1), worker turns and cost should decrease significantly.

### Python Runner Design

See SD-HARNESS-UPGRADE-001-E7.2-python-runner.md for detailed class design. Key principles:
- Zero LLM tokens for graph traversal
- Deterministic, testable, inspectable
- asyncio for parallel node dispatch
- Checkpoint after every state transition
- Handler registry maps `handler` attribute to Python functions
- Signal-file wait with watchdog-based file monitoring

## 8. Out of Scope

- Changes to the worker execution model (SDK `_run_agent()` stays as-is)
- Changes to the DOT file format itself (only new attributes added)
- Frontend/UI for pipeline monitoring (Phase 3, E11)
- Multi-repo pipeline coordination
- Non-AgentSDK dispatch modes (all dispatch is via `claude_code_sdk`)
- Changes to beads tracking (beads remain the primary work-tracking system)
- Compliance researcher agent (Could-Have, deferred)

## 9. Implementation Status (Updated 2026-03-10)

### Phase 1: Protocol Layer (E0-E3) — DONE

All 4 epics completed via pipeline dispatch. Documentation-only changes to schema docs, workflow references, skills, and output styles.

| Epic | Status | Key Commits |
| --- | --- | --- |
| E0: Pipeline Progress Monitor | **DONE** | s3-guardian SKILL.md + monitoring-patterns.md |
| E1: Node Semantics Clarification | **DONE** | wait.cobuilder/wait.human schemas, topology rules |
| E2: PRD Contract + E2E Gate Protocol | **DONE** | prd-contract template, guardian-workflow.md |
| E3: Workflow Protocol Enhancements | **DONE** | SD pinning, confidence baselines, concern queue |

### Phase 2: Schema & Tooling (E4-E7) — DONE

All epics completed via pipeline dispatch with AgentSDK workers.

| Epic | Status | Key Commits |
| --- | --- | --- |
| E4: Sub-Agent Registry + Skill Injection | **DONE** | Agent definitions + skills_required frontmatter |
| E5: Attractor Schema + Validate CLI | **DONE** | Topology validation, sd_path mandatory |
| E6: Dispatch Worker Enhancements | **DONE** | bypassPermissions, SD wiring, skill injection |
| E7.1: Worker Prompt Restructuring | **DONE** | System prompt 21K→3K, worker-tool-reference.md |
| E7.2: Pure Python DOT Runner | **DONE** | pipeline_runner.py — $0 dispatch, AgentSDK workers |

### Pipeline Runner Hardening (SD-PIPELINE-RUNNER-HARDENING-001)

Post-E7.2 hardening addressing latent bugs discovered via stress testing and research pipeline failures.

| Epic | Priority | Status | Evidence |
| --- | --- | --- | --- |
| G: Worker Context & Handler Preambles | P0 | **DONE** | Handler-specific allowed_tools + preambles |
| H: Dead Worker Detection | P0 | **DONE** | AdvancedWorkerTracker, 10 E2E tests (`878d0ed`) |
| I: Environment Legibility | P0 | **DONE** (redesigned) | Agent Directory merged into root CLAUDE.md; standalone AGENTS.md removed |
| A: Atomic Signal Writes | P1 | **DONE** | temp+rename, quarantine, apply-before-consume. 7 E2E tests (`5e826fc`) |
| B: force_status Persistence | P1 | **DONE** | _do_transition disk write, guidance files. 4 E2E tests (`5e826fc`) |
| C: Validation Error Handling | P1 | **DONE** | VALIDATION_TIMEOUT, crash→fail signal. 4 E2E tests (`5e826fc`) |
| J: Validation Spam Suppression | P1 | **DONE** | Terminal state guard. 8 E2E tests (`5e826fc`) |
| D: Orphan Resume Expansion | P2 | **DONE** (via PRD-COBUILDER-CONSOLIDATION-001 E2) | All 4 handler types resumable, exponential backoff, max 3 retries |
| E.3: Persistent Requeue Guidance | P2 | **DONE** (via PRD-COBUILDER-CONSOLIDATION-001 E2, `bb5b60e`+`05cdb8a`) | File-backed persistence, authoritative over in-memory dict |
| F: Global Safeguards | P2 | Absorbed into PRD-COBUILDER-CONSOLIDATION-001 E4-E5 |  |
| Liveness Race Fix | P1 | **DONE** | `6337153` — _get_node_status() guard prevents spurious signal overwrites |

**E2E Test Suite**: 33 tests in `tests/e2e/test_pipeline_hardening.py`, all passing (`cda90ed`).

> **Note (2026-03-10)**: Remaining hardening epics D, E.3, and F have been absorbed into PRD-COBUILDER-CONSOLIDATION-001.md to avoid migrating known-buggy code. See Section 13 of that PRD.

### Phase 3: Architecture Vision (E8-E12) — Future Work

Not started. Strategic alignment documented; no immediate implementation planned.

## 10. Risks

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Python runner misses edge cases that LLM guardian handled implicitly | Medium | Medium | Keep `runner.py` as fallback; extensive test coverage for state machine |
| PRD Contract too rigid — blocks legitimate scope evolution | Low | High | Contract amendment via frontmatter version increment (lightweight) |
| SD version pinning creates stale references | Medium | Low | Refine node updates SD before tagging; tags are cheap to regenerate |
| `wait.cobuilder` gates bottleneck pipeline throughput | High | Medium | Phase 3 E11 (async review queue) addresses this structurally |
| Agent skill injection injects wrong skills | Low | Medium | Agent registry validates `skills_required` against installed skills at startup |
| Worker prompt restructuring (E7.1) changes behavior | Medium | Medium | A/B comparison: run same pipeline with old and new prompts, compare results |

## 10. Dependencies

| Dependency | Required By | Status |
| --- | --- | --- |
| `cobuilder pipeline validate` CLI | E5 | Exists (basic rules) |
| `dispatch_worker.py` | E6, E7.2 | Exists (needs enhancement) |
| `runner.py` / `guardian.py` | E7.1 (prompt restructure), E7.2 (replacement) | Exists |
| `acceptance-test-runner` skill | E7.2 (`_handle_gate` — used by `validation-test-agent`) | Exists |
| Hindsight MCP | E3, E7.2 | Exists |
| GChat bridge | E7.2 (`_handle_human`) | Exists |
| `claude_code_sdk` | E6, E7.1, E7.2 | Exists |
| Chrome MCP (claude-in-chrome) | E7.2 (`_handle_gate` browser tests) | Exists |
| E7.1 — Worker Prompt Restructuring | E7.2 | Not started |
| `.claude/agents/` directory | E4 | Exists (partial) |
| `.claude/skills/` library | E4 (skill injection) | Exists |

## 11. Implementation Status

| Epic | Phase | Status | Notes |
| --- | --- | --- | --- |
| E0 — Pipeline Progress Monitor | 1 | **Complete** | s3-guardian skill enhancement. Haiku monitor pattern documented. |
| E1 — Node Semantics | 1 | **Complete** | Documentation: handler types, topology rules, schema docs. |
| E2 — PRD Contract | 1 | **Complete** | Documentation: prd-contract.md generation, compliance gate protocol. |
| E3 — Workflow Protocols | 1 | **Complete** | Documentation: SD pinning, confidence baseline, concern queue, session handoff, living narrative. |
| E4 — Agent Registry + Skills | 2 | **Complete** | 7 agent definitions with skills_required frontmatter. dispatch_worker.py loads agent defs + injects skill invocations. agent-schema.md updated. Pipeline-validated. |
| E5 — Schema + Validate | 2 | **Complete** | VALID_WORKER_TYPES has all 7 types. node_map param fixed in _check_cluster_topology. V-15 (AT writer warning) and V-16 (skills_required validation) implemented in cobuilder/pipeline/validator.py. sd_path mandatory on codergen. Pipeline-validated. |
| E6 — Dispatch Worker | 2 | **Complete** | ATTRACTOR_SIGNAL_DIR env var injected (GAP-6.1). Skill injection from agent definitions via load_agent_definition (GAP-6.2). sd_hash (SHA256) included in signal evidence (GAP-6.3). MCP bypass, SD wiring, tool examples from E7 commits. Pipeline-validated. |
| E7.1 — Worker Prompt Restructuring | 2 | **Complete** | 21/22 tests pass (1 skip). Slim system prompt (~3K), restructured initial prompt. Commit c5ddb4d. |
| E7.2 — Python Runner | 2 | **Complete** | 23/23 tests pass. Watchdog + AgentSDK dispatch, SIGNAL_TRANSITIONS, tool auto-accept. ThreadPoolExecutor for OTel context propagation. Logfire worker_tool/worker_text real-time events. Finalize gate fix (accepted status). Commits c5ddb4d–f4438e8. Post-validation fixes: signal protocol uses $ATTRACTOR_SIGNAL_DIR env var (e1d25eb), sd_path attribute name aligned with E5 schema (8697a1a). |
| E7.3 — Gate Monitor Pattern | 2 | **Designed** | SD written. Pipeline DOT created (2 parallel codergen nodes). Haiku monitor detects .gate-wait markers for wait.cobuilder (Gherkin E2E) and wait.human (AskUserQuestion round-trip). Not yet implemented. |
| E8 — Initiative Graph | 3 | Future | ~6-12 months |
| E9 — Persistent S3 | 3 | Future | ~6-12 months |
| E10 — Epic-Scoped Runners | 3 | Future | ~6-12 months |
| E11 — Async Review | 3 | Future | ~6-12 months |
| E12 — Graduated Autonomy | 3 | Future | ~6-12 months |

## Implementation Status

| Epic | Status | Date | Commit |
| --- | --- | --- | --- |
| - | Remaining | - | - |
