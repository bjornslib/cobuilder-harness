---
title: "nWave Evaluation for CoBuilder Integration"
description: "Analysis of nWave AI agent framework and its applicability to CoBuilder pipeline orchestration"
version: "1.0.0"
last-updated: 2026-03-17
status: active
type: research
grade: reference
---

# nWave Evaluation for CoBuilder

## Executive Summary

**nWave** is a Claude Code plugin/framework that orchestrates software development through a 6-wave pipeline (DISCOVER → DISCUSS → DESIGN → DEVOPS → DISTILL → DELIVER) with 23 specialized agents and a Deterministic Execution System (DES) for quality enforcement.

**Verdict**: nWave solves an adjacent but different problem than CoBuilder. There are valuable ideas to borrow, but **direct integration is not recommended** — the architectures are fundamentally incompatible in execution model, communication protocol, and orchestration philosophy.

---

## What nWave Does Well

### 1. Structured Development Phases (Waves)

nWave's 6-wave pipeline enforces a disciplined SDLC:

| Wave | Agent | Output |
|------|-------|--------|
| DISCOVER | product-discoverer | Market validation |
| DISCUSS | product-owner | Requirements docs |
| DESIGN | solution-architect | Architecture + ADRs |
| DEVOPS | platform-architect | Infrastructure readiness |
| DISTILL | acceptance-designer | Acceptance test specs |
| DELIVER | software-crafter | TDD implementation |

Each wave produces reviewable artifacts with mandatory human gates before proceeding.

### 2. Rigor Profiles

Configurable quality intensity per task:

| Profile | Agent Model | Reviewer | TDD Depth | Cost |
|---------|-------------|----------|-----------|------|
| Lean | Haiku | none | RED→GREEN | lowest |
| Standard | Sonnet | Haiku | full 5-phase | moderate |
| Thorough | Opus | Sonnet | full 5-phase | higher |
| Exhaustive | Opus | Opus | full + mutation | highest |

This is a smart pattern — adjusting LLM cost/quality per task criticality.

### 3. DES (Deterministic Execution System)

Hook-based enforcement that:
- Validates pre-conditions before tool use
- Prevents unauthorized file modifications during delivery
- Enforces TDD phase completion (PREPARE → RED_ACCEPTANCE → RED_UNIT → GREEN → COMMIT)
- Manages session lifecycle and cleanup

### 4. Peer Review Architecture

Each of the 12 primary agents has a corresponding reviewer agent, enabling structured quality validation without manual review of every artifact.

### 5. Skill Library

98 domain-knowledge skill files organized by specialty, loaded during agent initialization — similar to our `.claude/skills/` approach but at larger scale.

---

## Architecture Comparison

| Dimension | CoBuilder | nWave |
|-----------|-----------|-------|
| **Execution model** | DOT graph state machine (zero LLM cost for orchestration) | Claude Code plugin (LLM-driven orchestration) |
| **Communication** | Atomic JSON signal files (write-then-rename) | Claude Code hooks + in-process state |
| **Pipeline definition** | DOT files (Graphviz) with node attributes | Predefined 6-wave sequence |
| **Worker dispatch** | AgentSDK `claude_code_sdk.query()` + ThreadPoolExecutor | Claude Code subagent spawning |
| **Parallelism** | Fan-out nodes, parallel handler, concurrent workers | Sequential waves (no parallel execution) |
| **Crash recovery** | Pydantic checkpoints, `--resume` flag | DES session cleanup |
| **LLM providers** | Multi-provider (Anthropic, DashScope, OpenRouter) via providers.yaml | Anthropic-only (Haiku/Sonnet/Opus) |
| **Human gates** | `wait.human` + `wait.cobuilder` node types | Mandatory review between each wave |
| **Flexibility** | Arbitrary DAG topologies | Fixed linear pipeline |
| **Cost optimization** | Per-node LLM profile selection | Per-task rigor profile |
| **Installation** | Copy harness into project | Claude Code plugin marketplace |

### Key Incompatibilities

1. **Execution model mismatch**: CoBuilder's pipeline_runner.py is a zero-cost Python state machine that dispatches workers via AgentSDK. nWave runs entirely within Claude Code's context window as a plugin. These cannot be combined without rewriting one.

2. **Communication protocol**: CoBuilder uses filesystem-based signal files for inter-layer communication. nWave uses Claude Code hooks (PreToolUse, SubagentStop, PostToolUse). These are fundamentally different IPC mechanisms.

3. **Pipeline topology**: CoBuilder supports arbitrary DAG topologies via DOT files. nWave enforces a fixed 6-wave linear sequence. CoBuilder is more flexible; nWave is more opinionated.

4. **Multi-provider**: CoBuilder routes to DashScope/OpenRouter for near-$0 operations. nWave is Anthropic-only.

---

## Ideas Worth Borrowing

### 1. Rigor Profiles → CoBuilder Provider Profiles

**Current state**: CoBuilder has `providers.yaml` with per-node `llm_profile` selection, but no concept of task-criticality-driven profile bundles.

**Borrow**: Add named "rigor profiles" that bundle model + reviewer + validation depth:

```yaml
# In providers.yaml
rigor_profiles:
  lean:
    worker: alibaba-glm5
    reviewer: null
    tdd_depth: red-green
  standard:
    worker: anthropic-fast      # Haiku
    reviewer: alibaba-glm5
    tdd_depth: full
  thorough:
    worker: anthropic-smart     # Sonnet
    reviewer: anthropic-fast
    tdd_depth: full
  exhaustive:
    worker: anthropic-opus
    reviewer: anthropic-smart
    tdd_depth: full-mutation
```

DOT nodes could reference `rigor="standard"` instead of individual `llm_profile` values.

### 2. Peer Review Pattern → Validation Node Enhancement

**Current state**: CoBuilder dispatches a single `validation-test-agent` after implementation.

**Borrow**: For each codergen node, optionally spawn a lightweight reviewer agent (using a cheaper model) before the full validation-test-agent. This catches obvious issues early at lower cost.

### 3. DES-Style Hook Enforcement → Pipeline Runner Guards

**Current state**: CoBuilder's handlers don't enforce TDD discipline within workers.

**Borrow**: Add optional DES-like constraints to codergen nodes:

```dot
impl_auth [shape=box, handler="codergen",
  enforce_tdd="true",
  tdd_phases="prepare,red_acceptance,red_unit,green,commit"]
```

The handler could inject TDD enforcement instructions into the worker prompt and validate the signal response includes evidence of each phase.

### 4. Wave-Based Decomposition → Template Enhancement

**Current state**: CoBuilder has `cobuilder-lifecycle` template (research → design → implement → validate).

**Borrow**: Create a `full-sdlc` template inspired by nWave's 6 waves:

```
discover → discuss → design → devops → distill → deliver → validate
```

This would be a new Jinja2 template in `.cobuilder/templates/full-sdlc/`.

### 5. Agent Specification Format

nWave defines agents as YAML frontmatter + markdown files with explicit:
- Role boundaries
- Skill assignments
- Phase responsibilities
- Quality gate requirements

CoBuilder's `.claude/agents/` already uses a similar pattern but could formalize it with a schema.

---

## What NOT to Borrow

1. **Fixed linear pipeline**: CoBuilder's DAG flexibility is strictly superior. Don't constrain to 6 sequential waves.

2. **Plugin distribution model**: CoBuilder's harness-copy approach works for our multi-repo use case. Plugin marketplace adds a dependency we don't need.

3. **In-process orchestration**: nWave runs orchestration logic inside Claude Code's context window, consuming tokens for coordination. CoBuilder's zero-LLM runner is more cost-efficient.

4. **Anthropic-only**: CoBuilder's multi-provider support (DashScope GLM-5 at near-$0) is a significant cost advantage.

---

## Recommendation

**Do not integrate nWave directly.** Instead, selectively adopt these patterns:

| Priority | Pattern | Effort | Impact |
|----------|---------|--------|--------|
| **P1** | Rigor profiles in providers.yaml | Low | High — cost optimization per task criticality |
| **P2** | Peer review nodes (cheap reviewer before full validation) | Medium | Medium — catches issues earlier |
| **P3** | Full-SDLC template | Medium | Medium — more structured greenfield projects |
| **P4** | TDD enforcement in codergen prompts | Low | Low — already partially covered by tdd-test-engineer |
| **P5** | Formalized agent specification schema | Low | Low — documentation improvement |

### Next Steps

If we decide to pursue P1-P2:
1. Extend `providers.yaml` schema to support rigor profile bundles
2. Add `rigor` attribute to DOT node parsing in `dispatch_parser.py`
3. Update `_resolve_llm_config()` in `pipeline_runner.py` to resolve rigor profiles
4. Create optional `reviewer` handler that runs a cheap model pass before validation

---

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| Research & Evaluation | Done | 2026-03-17 | - |
| Rigor Profiles (P1) | Remaining | - | - |
| Peer Review Nodes (P2) | Remaining | - | - |
