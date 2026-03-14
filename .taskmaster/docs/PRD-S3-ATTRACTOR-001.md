# PRD-S3-ATTRACTOR-001: Attractor-Inspired Graph Orchestration

## Overview
Adopt Attractor-style DOT graph format as the primary orchestration artifact for System 3,
replacing markdown-convention-based workflow navigation with an executable Graphviz DOT graph.
Fix non-functional s3-live team components. Integrate completion promises into graph lifecycle.

**PRD ID**: PRD-S3-ATTRACTOR-001
**Status**: Active
**Priority**: P1
**Owner**: System 3 Meta-Orchestrator
**Target Repository**: claude-harness-setup (deployed to all targets)

## Background
PRD-S3-AUTONOMY-001 was closed with all 6 epics done, but several pieces are non-functional:
- s3-communicator and heartbeat are conflated into one agent
- GChat relay is a no-op (heartbeat runs but findings don't reach user)
- Documentation gardener exists in agencheck but never adapted for harness
- Validation-agent not consistently spawned as s3-live team member

The Attractor specification (github.com/strongdm/attractor) offers a declarative, graph-based
pipeline model using DOT format. This PRD adopts that model for System 3 navigation.

## Three Workstreams

### Workstream 1: S3-Live Operational Fixes
Fix broken components so s3-live team is operational.

### Workstream 2: Attractor-Style DOT Graph
Adopt DOT graph as primary orchestration format with CLI tools.

### Workstream 3: Execution Engine Design (Document Only)
Produce design document for PRD-S3-ATTRACTOR-002 (no implementation).

---

## Epic 1.1: Split Communicator and Heartbeat into Separate Agents

### Problem
s3-communicator and heartbeat are conflated into one 813-line spec. The communicator should
handle bidirectional GChat relay while heartbeat scans for actionable work.

### Requirements
- R1.1.1: Create separate s3-heartbeat SKILL.md with work-finding behavioral spec
- R1.1.2: Narrow s3-communicator SKILL.md to GChat relay only (outbound dispatch + inbound polling)
- R1.1.3: Update system3-meta-orchestrator.md s3-live team table with separate spawn blocks
- R1.1.4: s3-communicator polls GChat every 60s via poll_inbound_messages + process_commands
- R1.1.5: s3-heartbeat scans for actionable situations every 600s (10 min)
- R1.1.6: Heartbeat reports findings to System 3 via SendMessage (never directly to GChat)
- R1.1.7: System 3 decides what to relay to user via communicator

### Agent Responsibilities

| Agent | Model | Responsibility | Wake Frequency |
|-------|-------|----------------|----------------|
| s3-communicator | Haiku | Bidirectional GChat relay | 60s inbound poll |
| s3-heartbeat | Haiku | Scan for actionable work, alert team lead | 600s heartbeat cycle |

**s3-communicator outbound tools**:
- Blocked alerts: send_blocked_alert
- Progress updates: send_progress_update
- Task completions: send_task_completion
- General findings: send_heartbeat_finding
- Briefings: send_daily_briefing

**s3-heartbeat scan targets**:
- P0/P1 beads ready (bd ready)
- Orchestrator failures (tmux session crashed)
- Git staleness (uncommitted changes >1 hour)
- Stale tasks (in_progress >4 hours with no commits)
- Idle orchestrators (no tool calls in >30 minutes)

### Acceptance Criteria
- AC-1.1.1: s3-communicator and s3-heartbeat spawn as separate agents at System 3 startup
- AC-1.1.2: Heartbeat detects P1 bead creation within 10 minutes and notifies System 3
- AC-1.1.3: System 3 relays finding to communicator which sends to GChat
- AC-1.1.4: Inbound GChat message "status" parsed and relayed to System 3 within 60s
- AC-1.1.5: s3-communicator never scans beads/git/tmux; s3-heartbeat never sends to GChat

### Files
- CREATE: .claude/skills/s3-heartbeat/SKILL.md
- MODIFY: .claude/skills/s3-communicator/SKILL.md
- MODIFY: .claude/output-styles/system3-meta-orchestrator.md

---

## Epic 1.2: Documentation Gardener with Lint Enforcement

### Problem
Documentation gardener exists in agencheck/docs but never adapted for harness. No automated
quality enforcement for .claude/ directory documentation.

### Requirements
- R1.2.1: Adapt lint.py from agencheck/docs/lint.py (740 lines) for harness directory structure
- R1.2.2: Adapt gardener.py from agencheck/docs/gardener.py (300 lines) as auto-fix wrapper
- R1.2.3: Create harness-specific quality-grades.json with directory defaults
- R1.2.4: Wire gardener into pre-push hook (exit 0 required for push)
- R1.2.5: Create doc-gardener.md agent definition for on-demand s3-live team spawning
- R1.2.6: All adaptations go into .claude/scripts/doc-gardener/ (deployed from harness)

### Quality Grade Directory Defaults
- output-styles/ -> authoritative
- skills/ -> authoritative
- documentation/ -> reference
- scripts/ -> reference
- agents/ -> authoritative
- hooks/ -> reference

### Source Implementation (to adapt)
- /Users/theb/Documents/Windsurf/zenagent3/zenagent/agencheck/docs/lint.py (740 lines, 5 check categories)
- /Users/theb/Documents/Windsurf/zenagent3/zenagent/agencheck/docs/gardener.py (300 lines)
- /Users/theb/Documents/Windsurf/zenagent3/zenagent/agencheck/docs/quality-grades.json

### Acceptance Criteria
- AC-1.2.1: gardener.py --execute runs successfully on .claude/ directory
- AC-1.2.2: Lint detects frontmatter violations, cross-link issues, naming conventions
- AC-1.2.3: Auto-fix resolves fixable violations automatically
- AC-1.2.4: git push blocked when unfixed violations remain (pre-push hook)
- AC-1.2.5: quality-grades.json correctly maps harness directories to grade levels

### Files
- CREATE: .claude/scripts/doc-gardener/lint.py
- CREATE: .claude/scripts/doc-gardener/gardener.py
- CREATE: .claude/scripts/doc-gardener/quality-grades.json
- CREATE: .claude/agents/doc-gardener.md
- MODIFY: .claude/settings.json or .git/hooks/pre-push

---

## Epic 1.3: Validation-Agent Dual-Mode as S3-Live Team Member

### Problem
Validation-agent spawned per-task as one-shot subagent. Should be persistent s3-live team
member with dual-mode validation (technical + business).

### Requirements
- R1.3.1: Add --mode=technical (unit tests, compile, imports, type-checks, no TODO/FIXME)
- R1.3.2: Add --mode=business (acceptance criteria, user-facing behavior, E2E, PRD coverage)
- R1.3.3: Spawn as persistent s3-live team member (not one-shot per task)
- R1.3.4: Technical mode runs first, business mode runs second (sequential dual-pass)
- R1.3.5: Both results stored via cs-store-validation

### Mode Mapping
- --mode=technical approx= current --mode=unit + compile/import/type checks
- --mode=business approx= current --mode=e2e + PRD coverage matrix

### Acceptance Criteria
- AC-1.3.1: validation-test-agent.md documents --mode=technical and --mode=business
- AC-1.3.2: System 3 spawns s3-validator as persistent team member at startup
- AC-1.3.3: Technical validation runs before business validation for each task
- AC-1.3.4: Validation results stored in cs-store-validation with mode tag
- AC-1.3.5: s3-validator claims validation tasks from shared TaskList

### Files
- MODIFY: .claude/agents/validation-test-agent.md
- MODIFY: .claude/skills/system3-orchestrator/references/oversight-team.md
- MODIFY: .claude/output-styles/system3-meta-orchestrator.md

---

## Epic 2.1: Pipeline DOT Schema + Completion Promise Integration

### Problem
Orchestration workflow lives in markdown conventions, not executable format. Need a DOT-based
vocabulary that maps Attractor's node shapes to our domain.

### Requirements
- R2.1.1: Define DOT vocabulary with node shapes mapping to handler types
- R2.1.2: Document node attribute vocabulary (handler, bead_id, worker_type, acceptance, status, promise_id, promise_ac, gate, prd_ref, mode)
- R2.1.3: Map Attractor 5-stage lifecycle to our lifecycle with completion promise integration
- R2.1.4: Create minimal 3-node example pipeline
- R2.1.5: Create full initiative example with AT pairing and promise integration

### Attractor Stage Mapping

| Attractor Stage | Our Equivalent | Completion Promise |
|----------------|----------------|-------------------|
| PARSE | PRD parsed, tasks generated, beads created | cs-init: Create promise with ACs from PRD |
| VALIDATE | Graph validated (no cycles, deps resolved) | cs-promise: Register graph validation AC |
| INITIALIZE | Services started, worktrees created, teams spawned | cs-promise: Register env readiness AC |
| EXECUTE | Workers implementing, orchestrators coordinating | cs-promise --meet: Mark ACs as tasks complete |
| FINALIZE | All tasks validated, evidence collected, PRs merged | cs-verify: Triple-gate verification |

### Node Shape Vocabulary

| Shape | Handler | Purpose |
|-------|---------|---------|
| Mdiamond | start | Pipeline entry point |
| Msquare | exit | Pipeline exit (finalize) |
| box | codergen/tool | Implementation task or tool execution |
| hexagon | wait.human | Human/automated validation gate |
| diamond | conditional | Routing decision |

### Acceptance Criteria
- AC-2.1.1: schema.md documents full DOT vocabulary with all node attributes
- AC-2.1.2: simple-pipeline.dot renders correctly with standard Graphviz (dot -Tpng)
- AC-2.1.3: full-initiative.dot demonstrates AT pairing, promise_id/promise_ac, conditional routing
- AC-2.1.4: Pipeline includes all 5 Attractor lifecycle stages with promise integration

### Files
- CREATE: .cobuilder/schema.md
- CREATE: .cobuilder/examples/simple-pipeline.dot
- CREATE: .cobuilder/examples/full-initiative.dot

---

## Epic 2.2: CLI Tools - DOT Parsing and Validation

### Problem
Need CLI tools for System 3 to interact with DOT graph (parse, validate, status, transition, checkpoint).

### Requirements
- R2.2.1: attractor parse - Validate DOT syntax, extract node/edge metadata to JSON
- R2.2.2: attractor validate - Structural rules (AT pairing, no orphans, promise refs valid)
- R2.2.3: attractor status - Current pipeline state (table or JSON format)
- R2.2.4: attractor transition - Advance node state + checkpoint
- R2.2.5: attractor checkpoint save/restore - State snapshots for crash recovery
- R2.2.6: Python implementation using stdlib + pydot library

### Validation Rules
- Every codergen node must have bead_id
- Every task node should have a paired AT node (hexagon)
- No cycles in main flow (only via explicit loop_restart edges)
- Start (Mdiamond) and exit (Msquare) nodes must exist
- All conditional edges must have condition attributes
- If promise_id on finalize: validate promise exists via cs-promise
- If promise_ac on task nodes: validate AC exists in the promise

### Acceptance Criteria
- AC-2.2.1: attractor parse pipeline.dot --output pipeline.json produces valid JSON
- AC-2.2.2: attractor validate catches missing AT pairs and orphan nodes
- AC-2.2.3: attractor status displays current pipeline state in table and JSON
- AC-2.2.4: attractor transition advances node state and creates checkpoint
- AC-2.2.5: attractor checkpoint restore recovers state from checkpoint file
- AC-2.2.6: All commands have --help documentation

### Files
- CREATE: .claude/scripts/attractor/cli.py
- CREATE: .claude/scripts/attractor/parser.py
- CREATE: .claude/scripts/attractor/validator.py
- CREATE: .claude/scripts/attractor/status.py
- CREATE: .claude/scripts/attractor/transition.py
- CREATE: .claude/scripts/attractor/checkpoint.py

---

## Epic 2.3: ZeroRepo DOT Pipeline Generation + Bead Annotation

### Problem
ZeroRepo generates codebase graph but not Attractor-compatible pipeline DOT. Need to extend
DOT export and add bead annotation + promise initialization.

### Requirements
- R2.3.1: Extend export.py _export_dot() to emit Attractor-compatible attributes
- R2.3.2: EXISTING components -> no node (skip)
- R2.3.3: MODIFIED components -> codergen node with file paths and change scope
- R2.3.4: NEW components -> codergen node with suggested module structure
- R2.3.5: attractor annotate cross-references DOT nodes with beads database
- R2.3.6: attractor init-promise creates cs-promise from DOT graph hexagon nodes

### Acceptance Criteria
- AC-2.3.1: ZeroRepo generate produces pipeline.dot alongside existing outputs
- AC-2.3.2: Pipeline DOT contains handler, worker_type, acceptance attributes per node
- AC-2.3.3: attractor annotate adds bead_id to each node from .beads/beads.db
- AC-2.3.4: attractor init-promise creates cs-promise with ACs from hexagon nodes
- AC-2.3.5: Annotated DOT can be validated by attractor validate

### Files
- MODIFY: src/zerorepo/graph_construction/export.py (lines 367-401)
- MODIFY: .claude/skills/orchestrator-multiagent/scripts/zerorepo-run-pipeline.py
- CREATE: .claude/scripts/attractor/annotate.py
- CREATE: .claude/scripts/attractor/init_promise.py

---

## Epic 2.4: System 3 DOT Navigation + Stop Gate Integration

### Problem
System 3 navigates by reading checklists, not traversing a graph. Need to wire DOT graph
into System 3's monitoring and stop gate.

### Requirements
- R2.4.1: System 3 uses attractor status as primary navigation instrument
- R2.4.2: Pending nodes with satisfied deps trigger orchestrator spawning
- R2.4.3: impl_complete nodes trigger s3-validator with DOT acceptance criteria
- R2.4.4: attractor transition advances state after validation
- R2.4.5: Finalize node runs cs-verify --promise=PRD-XXX (triple-gate)
- R2.4.6: Checkpoint after each transition for crash recovery
- R2.4.7: Stop gate P1.5 checker: if pipeline.dot exists, verify all nodes validated

### Acceptance Criteria
- AC-2.4.1: system3-meta-orchestrator.md includes DOT Graph Navigation workflow section
- AC-2.4.2: system3-orchestrator SKILL.md includes attractor CLI in preflight
- AC-2.4.3: Stop gate blocks session end if pipeline.dot has unvalidated nodes
- AC-2.4.4: System 3 can complete full pipeline: parse -> validate -> execute -> finalize
- AC-2.4.5: Crash recovery restores pipeline state from checkpoint

### Files
- MODIFY: .claude/output-styles/system3-meta-orchestrator.md
- MODIFY: .claude/skills/system3-orchestrator/SKILL.md
- MODIFY: .claude/hooks/unified_stop_gate/checkers.py

---

## Epic 3.1: Execution Engine Design Document

### Problem
Need design document for automatic pipeline traversal (PRD-S3-ATTRACTOR-002).

### Requirements
- R3.1.1: Document hybrid runner architecture (CLI phase 1, Agent SDK phase 2, full Attractor phase 3)
- R3.1.2: Document scenario-based acceptance testing outside the repo
- R3.1.3: Explicitly scope what IS and IS NOT in this phase vs next

### Scope Boundary
**IN this phase**: CLI tools, System 3 manual navigation, DOT vocabulary, completion promise integration
**NOT in this phase**: Automatic traversal, event streams, HTTP API, CodergenBackend abstraction, model_stylesheet

### Acceptance Criteria
- AC-3.1.1: Design document covers hybrid runner architecture across 3 phases
- AC-3.1.2: Scenario-based testing pattern documented with anti-gaming protections
- AC-3.1.3: Document approved as input PRD for PRD-S3-ATTRACTOR-002
- AC-3.1.4: Agent SDK spike documented (3-node pipeline proof of concept)

### Files
- CREATE: .claude/documentation/PRD-S3-ATTRACTOR-002-design.md

---

## Implementation Order

Phase 1 (Workstream 1): Fix s3-live (3 epics)
- Epic 1.1: Split Communicator and Heartbeat
- Epic 1.2: Documentation Gardener (adapt from agencheck)
- Epic 1.3: Validation-Agent Dual-Mode

Phase 2 (Workstream 2): DOT Graph (4 epics)
- Epic 2.1: Pipeline DOT Schema
- Epic 2.2: CLI Tools (parse, validate, status, transition, checkpoint)
- Epic 2.3: ZeroRepo DOT Pipeline Generation
- Epic 2.4: System 3 DOT Navigation

Phase 3 (Workstream 3): Design document only
- Epic 3.1: Execution Engine Design Document

## Dependencies
- Epic 2.2 depends on Epic 2.1 (CLI needs schema)
- Epic 2.3 depends on Epic 2.2 (annotation needs CLI tools)
- Epic 2.4 depends on Epic 2.2 (navigation needs CLI tools)
- Epic 3.1 can start after Epic 2.1 (needs schema understanding)
- Workstream 1 epics are independent of each other
- Workstream 1 is independent of Workstream 2
