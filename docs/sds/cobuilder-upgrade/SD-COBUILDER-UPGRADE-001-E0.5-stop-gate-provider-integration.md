---
sd_id: SD-COBUILDER-UPGRADE-001-E0.5-stop-gate-provider-integration
prd_ref: PRD-COBUILDER-UPGRADE-001
epic: "E0.5: Stop Gate Environment Variables & Provider Integration"
title: "Stop Gate Environment Variables & DashScope Provider Integration"
version: "1.0"
status: active
created: "2026-03-14"
author: "backend-solutions-engineer (refine worker)"
grade: authoritative
---

# SD-COBUILDER-UPGRADE-001-E0.5: Stop Gate Environment Variables & DashScope Provider Integration

**Epic:** E0.5 — Stop Gate & Provider Integration
**Source PRD:** PRD-COBUILDER-UPGRADE-001
**Date:** 2026-03-14
**Author:** backend-solutions-engineer (refine worker)
**Status:** Active

---

## 1. Business Context

**Goal**: Ensure proper integration of the unified stop gate system with the new `cobuilder/engine/` package, and enable DashScope (Alibaba Cloud Qwen) as a supported LLM provider in the providers.yaml system.

**User Impact**: Pipeline runners and workers will correctly honor stop gate checks (iteration limits, completion promises, business outcome enforcement). Users can leverage cost-effective Qwen models for non-critical pipeline tasks.

**Success Metrics**:
- Stop gate environment variables correctly sourced in both Bash entry point and Python core
- `CLAUDE_ENFORCE_BO=true` enables all stop gate checks; `false` bypasses via fast-path
- DashScope profile in `providers.yaml` dispatches workers to Qwen models
- No API key leakage in logs

**Constraints**:
- Stop gate must support both legacy `system3-` session detection AND new `cobuilder-` session detection
- Provider profiles must translate cleanly to Anthropic SDK equivalents
- No code duplication between Bash and Python configuration layers

---

## 2. Technical Architecture

### 2.1 Stop Gate Two-Layer Architecture

The unified stop gate system uses a **two-layer architecture** for environment variable sourcing:

```
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 1: BASH ENTRY POINT                                          │
│  unified-stop-gate.sh                                               │
│    - Reads env vars directly from shell environment                 │
│    - Implements fast-path bypass for non-enforced sessions          │
│    - Outputs JSON result to stdout                                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  LAYER 2: PYTHON CORE                                               │
│  cobuilder/engine/stop_gate/                                        │
│    - EnvironmentConfig.from_env() dataclass                         │
│    - Priority-based checker system (P0-P5)                          │
│    - Session type detection (system3, orchestrator, worker)         │
│    - PathResolver for session isolation                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 Environment Variables Catalog

| Variable | Default | Purpose | Used By |
|----------|---------|---------|---------|
| `CLAUDE_PROJECT_DIR` | `.` | Project root directory | All checkers for path resolution |
| `CLAUDE_SESSION_DIR` | `None` | Session isolation subdirectory | PathResolver for parallel initiatives |
| `CLAUDE_SESSION_ID` | `None` | Unique session identifier | Session type detection, promise ownership |
| `CLAUDE_MAX_ITERATIONS` | `25` | Circuit breaker threshold | MaxIterationsChecker (P0) |
| `CLAUDE_ENFORCE_PROMISE` | `false` | Enable completion promise checks | CompletionPromiseChecker (P1) |
| `CLAUDE_ENFORCE_BO` | `false` | Enable business outcome checks | BusinessOutcomeChecker (P5), fast-path bypass |
| `CLAUDE_OUTPUT_STYLE` | `""` | Active output style mode | System3 detection (must != "orchestrator") |
| `CLAUDE_CODE_TASK_LIST_ID` | `None` | Task list for team coordination | WorkExhaustionChecker (P3) |
| `ANTHROPIC_API_KEY` | - | API key for Haiku judge | System3ContinuationJudgeChecker (P3.5) |
| `WORK_STATE_SUMMARY` | `""` | Pre-computed work state | System3ContinuationJudgeChecker |

### 2.3 DashScope Provider Integration

DashScope (Alibaba Cloud LLM service) integrates via the `providers.yaml` profile system:

```
┌─────────────────────────────────────────────────────────────────────┐
│  providers.yaml                                                     │
│  profiles:                                                          │
│    alibaba-qwen-fast:                                               │
│      model: qwen-turbo                                              │
│      api_key: $DASHSCOPE_API_KEY                                    │
│      base_url: https://dashscope-intl.aliyuncs.com/compatible-mode/v1│
│    alibaba-qwen-smart:                                              │
│      model: qwen-plus                                               │
│      api_key: $DASHSCOPE_API_KEY                                    │
│      base_url: https://dashscope-intl.aliyuncs.com/compatible-mode/v1│
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  cobuilder/engine/providers.py                                      │
│    _resolve_llm_config() — 5-layer resolution                       │
│    _translate_profile() — profile keys → Anthropic SDK equivalents  │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.4 Data Models

```python
# cobuilder/engine/stop_gate/config.py

@dataclass
class EnvironmentConfig:
    """Configuration sourced from environment variables."""
    project_dir: str
    session_dir: str | None
    session_id: str | None
    max_iterations: int
    enforce_promise: bool
    enforce_bo: bool

    @classmethod
    def from_env(cls) -> 'EnvironmentConfig':
        return cls(
            project_dir=os.environ.get('CLAUDE_PROJECT_DIR', '.'),
            session_dir=os.environ.get('CLAUDE_SESSION_DIR'),
            session_id=os.environ.get('CLAUDE_SESSION_ID'),
            max_iterations=int(os.environ.get('CLAUDE_MAX_ITERATIONS', '25')),
            enforce_promise=os.environ.get('CLAUDE_ENFORCE_PROMISE', '').lower() in ('true', '1', 'yes'),
            enforce_bo=os.environ.get('CLAUDE_ENFORCE_BO', '').lower() in ('true', '1', 'yes'),
        )

    @property
    def is_system3(self) -> bool:
        """Detect System3 session type."""
        session_ok = bool(self.session_id and self.session_id.startswith("system3-"))
        output_style = os.environ.get("CLAUDE_OUTPUT_STYLE", "")
        not_orchestrator = output_style != "orchestrator"
        return session_ok and not_orchestrator

    @property
    def is_cobuilder(self) -> bool:
        """Detect CoBuilder session type (new terminology)."""
        return bool(self.session_id and self.session_id.startswith("cobuilder-"))

    @property
    def is_orchestrator(self) -> bool:
        """Detect Orchestrator session type."""
        return bool(self.session_id and self.session_id.startswith("orch-"))
```

### 2.5 API Contracts

#### Stop Gate Check Response

```json
{
  "decision": "approve" | "block" | "warn",
  "systemMessage": "Human-readable explanation",
  "checkName": "MaxIterationsChecker",
  "priority": 0,
  "metadata": {
    "iterations": 26,
    "max_iterations": 25
  }
}
```

#### Provider Profile Resolution

| Input | Resolution Path | Output |
|-------|-----------------|--------|
| `llm_profile="alibaba-qwen-fast"` | providers.yaml → profile lookup | `model=qwen-turbo`, `base_url=dashscope...` |
| `api_key: $DASHSCOPE_API_KEY` | Environment substitution | `api_key=sk-...` |

---

## 3. Implementation Approach

### 3.1 Technology Choices

| Choice | Technology | Rationale |
|--------|-----------|-----------|
| Config sourcing | Python dataclass + os.environ | Type-safe, testable, single source of truth |
| Fast-path check | Bash (unified-stop-gate.sh) | Zero Python overhead for non-enforced sessions |
| Provider profiles | YAML + env var substitution | Human-readable, supports `$VAR` syntax |
| DashScope integration | OpenAI SDK compatibility mode | Drop-in replacement, no custom client needed |

### 3.2 Key Design Decisions

**Decision 1: Two-Layer Sourcing Architecture**
- **Context**: Stop gate must work in both pure Bash contexts (hook exit) and Python contexts (detailed checks)
- **Options considered**: (A) Python-only, (B) Bash-only, (C) Two-layer hybrid
- **Chosen**: Two-layer hybrid
- **Rationale**: Bash fast-path enables zero-overhead bypass for non-enforced sessions; Python core provides type-safe detailed checks
- **Trade-offs**: Slight duplication between Bash and Python defaults; mitigated by single source of truth in documentation

**Decision 2: CLAUDE_ENFORCE_BO as Master Switch**
- **Context**: Stop gate checks add latency and complexity
- **Options considered**: (A) Always enforce all checks, (B) Per-check opt-in, (C) Single master switch
- **Chosen**: Single master switch (`CLAUDE_ENFORCE_BO`)
- **Rationale**: Simplifies mental model; users either want full enforcement or no enforcement
- **Trade-offs**: Less granular control; acceptable given use case (development pipelines)

**Decision 3: DashScope via OpenAI SDK Compatibility**
- **Context**: DashScope provides OpenAI-compatible endpoint
- **Options considered**: (A) Native DashScope SDK, (B) OpenAI SDK compatibility mode, (C) Custom HTTP client
- **Chosen**: OpenAI SDK compatibility mode
- **Rationale**: Zero custom code, leverages existing OpenAI SDK patterns, works with `providers.yaml` profile system
- **Trade-offs**: Limited to OpenAI-compatible features; DashScope-specific features require custom implementation

### 3.3 Integration Points

| Integration | Type | Direction | Notes |
|-------------|------|-----------|-------|
| `unified-stop-gate.sh` | Shell script | Entry point | Called by Stop hook |
| `cobuilder/engine/stop_gate/` | Python module | Core logic | Imported by runner |
| `providers.yaml` | Config file | Read | Profile definitions |
| DashScope API | HTTP REST | Outbound | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |

---

## 4. Functional Decomposition

### Capability: Stop Gate Configuration

Environment variable sourcing and session type detection.

#### Feature: Environment Variable Sourcing
- **Description**: Read and validate all stop gate environment variables
- **Inputs**: Shell environment
- **Outputs**: `EnvironmentConfig` dataclass instance
- **Behavior**: Defaults applied, boolean parsing, integer parsing
- **Depends on**: None

#### Feature: Session Type Detection
- **Description**: Determine session type from session ID and output style
- **Inputs**: `EnvironmentConfig.session_id`, `CLAUDE_OUTPUT_STYLE`
- **Outputs**: `is_system3`, `is_cobuilder`, `is_orchestrator` boolean properties
- **Behavior**: Prefix matching + output style exclusion for System3
- **Depends on**: Environment Variable Sourcing

#### Feature: Fast-Path Bypass
- **Description**: Skip all checks when `CLAUDE_ENFORCE_BO != true`
- **Inputs**: `CLAUDE_ENFORCE_BO` environment variable
- **Outputs**: Immediate `approve` decision
- **Behavior**: Bash-level check, no Python invocation
- **Depends on**: None

### Capability: Priority-Based Checking

Ordered execution of stop gate checkers.

#### Feature: MaxIterationsChecker (P0)
- **Description**: Circuit breaker for runaway iterations
- **Inputs**: `CLAUDE_MAX_ITERATIONS`, iteration counter file
- **Outputs**: `approve` if under limit, `block` if exceeded
- **Behavior**: Forces ALLOW when limit exceeded (safety valve)
- **Depends on**: Environment Variable Sourcing

#### Feature: CompletionPromiseChecker (P1)
- **Description**: Verify completion promises are satisfied
- **Inputs**: `CLAUDE_ENFORCE_PROMISE`, promise directory
- **Outputs**: `block` if promises not satisfied
- **Behavior**: Checks for pending promises before allowing completion
- **Depends on**: Environment Variable Sourcing, Session Type Detection

#### Feature: BusinessOutcomeChecker (P5)
- **Description**: Validate business outcomes before session close
- **Inputs**: `CLAUDE_ENFORCE_BO`, outcome evidence
- **Outputs**: `block` if outcomes not validated
- **Behavior**: Final gate for enforced sessions
- **Depends on**: All other checkers (runs last)

### Capability: DashScope Provider Support

Integration of Alibaba Cloud Qwen models via providers.yaml.

#### Feature: DashScope Profile Definition
- **Description**: Define standard DashScope profiles in providers.yaml
- **Inputs**: providers.yaml config
- **Outputs**: Profile entries with base_url, model, api_key
- **Behavior**: Supports qwen-turbo, qwen-plus, qwen-max, qwen-long
- **Depends on**: None

#### Feature: Environment Variable Substitution
- **Description**: Resolve `$DASHSCOPE_API_KEY` from environment
- **Inputs**: Profile api_key value, shell environment
- **Outputs**: Resolved API key string
- **Behavior**: Pattern match `$VAR` and substitute from os.environ
- **Depends on**: DashScope Profile Definition

#### Feature: Profile-to-Anthropic Translation
- **Description**: Translate profile keys to Anthropic SDK equivalents
- **Inputs**: Profile model, api_key, base_url
- **Outputs**: `ANTHROPIC_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` worker env vars
- **Behavior**: Transparent translation at dispatch time
- **Depends on**: Environment Variable Substitution

---

## 5. Dependency Graph

### Foundation Layer (Build First)
No dependencies — these are built first.

- **Environment Variable Sourcing**: Provides `EnvironmentConfig` for all downstream work
- **DashScope Profile Definition**: Provides profile entries for provider resolution

### Layer 1: Detection & Resolution
- **Session Type Detection**: Depends on [Environment Variable Sourcing]
- **Environment Variable Substitution**: Depends on [DashScope Profile Definition]
- **Fast-Path Bypass**: Independent (Bash-level, no Python)

### Layer 2: Checkers & Translation
- **MaxIterationsChecker (P0)**: Depends on [Environment Variable Sourcing]
- **CompletionPromiseChecker (P1)**: Depends on [Environment Variable Sourcing, Session Type Detection]
- **Profile-to-Anthropic Translation**: Depends on [Environment Variable Substitution]

### Layer 3: Final Gates
- **BusinessOutcomeChecker (P5)**: Depends on [All checkers above]

---

## 6. Acceptance Criteria

### Feature: Environment Variable Sourcing

**Given** the shell environment contains `CLAUDE_SESSION_ID=test-123`
**When** `EnvironmentConfig.from_env()` is called
**Then** the resulting config has `session_id="test-123"`
**And** all defaults are applied for unspecified variables

### Feature: Session Type Detection

**Given** `CLAUDE_SESSION_ID=system3-abc-123` and `CLAUDE_OUTPUT_STYLE=""`
**When** `config.is_system3` is evaluated
**Then** the result is `True`

**Given** `CLAUDE_SESSION_ID=system3-abc-123` and `CLAUDE_OUTPUT_STYLE="orchestrator"`
**When** `config.is_system3` is evaluated
**Then** the result is `False` (orchestrator style overrides)

**Given** `CLAUDE_SESSION_ID=cobuilder-init-001`
**When** `config.is_cobuilder` is evaluated
**Then** the result is `True`

### Feature: Fast-Path Bypass

**Given** `CLAUDE_ENFORCE_BO` is unset or `"false"`
**When** `unified-stop-gate.sh` executes
**Then** the output is `{"decision": "approve", "systemMessage": "Non-enforced session — approved"}`
**And** no Python code is invoked

### Feature: MaxIterationsChecker

**Given** `CLAUDE_MAX_ITERATIONS=25` and iteration counter shows 26
**When** MaxIterationsChecker runs
**Then** the decision is `approve` with explanation "Max iterations reached — circuit breaker"

### Feature: DashScope Profile Resolution

**Given** a DOT node with `llm_profile="alibaba-qwen-fast"`
**And** `providers.yaml` contains the `alibaba-qwen-fast` profile
**When** `_resolve_llm_config()` is called
**Then** the worker receives `ANTHROPIC_MODEL=qwen-turbo`
**And** `ANTHROPIC_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1`
**And** `ANTHROPIC_API_KEY` is set from `$DASHSCOPE_API_KEY`

---

## 7. Test Strategy

### Test Pyramid

| Level | Coverage | Tools | What It Tests |
|-------|----------|-------|---------------|
| Unit | 90% | pytest | Config parsing, session detection, profile resolution |
| Integration | 80% | pytest + subprocess | Stop gate end-to-end, provider dispatch |
| E2E | 70% | pytest + pipeline runner | Full pipeline with stop gate, mixed-provider nodes |

### Critical Test Scenarios

| Scenario | Type | Priority |
|----------|------|----------|
| Fast-path bypass when CLAUDE_ENFORCE_BO=false | Integration | P0 |
| Session type detection with orchestrator override | Unit | P0 |
| DashScope profile resolves to correct base_url | Unit | P0 |
| MaxIterationsChecker circuit breaker fires | Integration | P1 |
| API key never logged (sanitization) | Unit | P0 |
| Mixed-provider pipeline (Anthropic + DashScope) | E2E | P1 |

---

## 8. File Scope

### New Files

| File Path | Purpose |
|-----------|---------|
| `cobuilder/engine/stop_gate/__init__.py` | Module init |
| `cobuilder/engine/stop_gate/config.py` | `EnvironmentConfig` dataclass |
| `cobuilder/engine/stop_gate/checkers.py` | Priority-based checker implementations |
| `cobuilder/engine/stop_gate/path_resolver.py` | Session isolation path handling |
| `tests/engine/stop_gate/test_config.py` | Config parsing tests |
| `tests/engine/stop_gate/test_checkers.py` | Checker behavior tests |

### Modified Files

| File Path | Changes |
|-----------|---------|
| `providers.yaml` | Add DashScope profiles (alibaba-qwen-fast, alibaba-qwen-smart, alibaba-qwen-max, alibaba-qwen-long) |
| `unified-stop-gate.sh` | Add `cobuilder-` session detection (alongside `system3-`) |
| `cobuilder/engine/providers.py` | Ensure OpenAI-compatible base URLs work transparently |

### Files NOT to Modify

| File Path | Reason |
|-----------|--------|
| `.claude/hooks/unified-stop-gate.sh` | Symlink to shared location; modify source, not symlink |
| `cobuilder/attractor/` | Removed in E2; changes go to `cobuilder/engine/` |

---

## 9. Risks & Technical Concerns

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| DashScope API differs from OpenAI spec | Medium | Medium | Integration test against real DashScope endpoint; document known incompatibilities |
| Session type detection false positive | Low | High | Dual-condition check (session ID prefix AND output style != orchestrator) |
| API key leakage in logs | Medium | Critical | Sanitize all `api_key` values in log output; never log resolved secrets |
| Stop gate adds latency to every session end | Low | Medium | Fast-path bypass for non-enforced sessions; Python checkers only when needed |

---

## 10. DashScope Integration Reference

### API Endpoint

```
https://dashscope-intl.aliyuncs.com/compatible-mode/v1
```

### Available Models (Qwen Family)

| Model | Description | Use Case |
|-------|-------------|----------|
| `qwen-turbo` | Fast, cost-effective | Quick responses, simple tasks |
| `qwen-plus` | Balanced performance | General-purpose use |
| `qwen-max` | Most capable | Complex reasoning, long context |
| `qwen-long` | Extended context | Document analysis |

### OpenAI SDK Compatibility Example

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ]
)
```

### LangChain Integration Example

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    model="qwen-plus"
)
```

### Compatibility Notes

| Integration Type | Feasibility | Approach |
|-----------------|-------------|----------|
| Claude Code native | Not possible | Claude Code requires Anthropic API |
| Claude Agent SDK | Not possible | SDK built for Claude models |
| MCP Tool wrapper | Possible | Create MCP server that calls DashScope |
| Custom agent tool | Possible | Use OpenAI SDK in Python tool code |
| LangChain agent | Possible | LangChain supports both Claude and Qwen |
| providers.yaml profile | Supported | This design — transparent via OpenAI-compatible mode |

### API Key Setup

```bash
export DASHSCOPE_API_KEY="sk-your-api-key"
```

Get API key from: https://dashscope.console.aliyun.com/

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-14 | backend-solutions-engineer | Initial design incorporating research findings |