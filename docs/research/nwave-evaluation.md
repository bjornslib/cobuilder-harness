---
title: "nWave Evaluation for CoBuilder Integration"
description: "Analysis of nWave AI agent framework and its applicability to CoBuilder pipeline orchestration"
version: "2.0.0"
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

## Deep Dive: Rigor Profiles

### How nWave's Rigor Profiles Work (From Source)

nWave defines five named profiles that bundle **7 dimensions** together:

| Dimension | Lean | Standard | Thorough | Exhaustive | Inherit |
|-----------|------|----------|----------|------------|---------|
| **agent_model** | haiku | sonnet | opus | opus | session model |
| **reviewer_model** | skip | haiku | sonnet | opus | haiku |
| **review_enabled** | false | true | true | true | true |
| **double_review** | false | false | true | true | false |
| **tdd_phases** | RED_UNIT, GREEN only | full 5-phase | full 5-phase | full 5-phase | full 5-phase |
| **refactor_pass** | false | true | true | true | true |
| **mutation_enabled** | false | false | false | true (≥80% kill) | false |

**Key detail**: Lean doesn't just simplify TDD — it **drops 3 phases entirely** (PREPARE, RED_ACCEPTANCE, COMMIT). The DES prompt template for lean profiles strips those section instructions completely.

The profile is selected per-feature via `/nw:rigor` command or config file. Persists to `.nwave/des-config.json` (project-local, overrides global `~/.nwave/global-config.json`).

**Priority cascade**: project config → global config → standard defaults.

The system then:
1. Passes `agent_model` as the model parameter to Task invocations (omits if "inherit")
2. Passes `reviewer_model` to reviewer Tasks; skips review entirely if "skip"
3. Replaces the TDD_PHASES section in the DES template based on `tdd_phases` array
4. Skips refactor pass if `refactor_pass: false`
5. Skips mutation testing if `mutation_enabled: false`
6. If `double_review: true`, runs two separate review passes (different reviewers)

**Critical constraint**: The DES hook validates the complete prompt BEFORE the sub-agent starts. Abbreviated prompts that delegate template reading to the sub-agent are BLOCKED. The orchestrator must embed the complete template inline.

### CoBuilder Adaptation Design

Our adaptation maps to existing CoBuilder primitives:

```yaml
# providers.yaml — extended with rigor_profiles section
# Mirrors nWave's 7-dimension schema, adapted for CoBuilder multi-provider
rigor_profiles:
  lean:
    worker_profile: alibaba-glm5         # near-$0
    reviewer_profile: null               # skip review entirely
    review_enabled: false
    double_review: false
    tdd_phases: [red_unit, green]        # drop prepare, red_acceptance, commit
    refactor_pass: false
    mutation_enabled: false
    anti_pattern_check: false

  standard:
    worker_profile: anthropic-fast       # Haiku
    reviewer_profile: alibaba-glm5       # cheap reviewer
    review_enabled: true
    double_review: false
    tdd_phases: [prepare, red_acceptance, red_unit, green, commit]
    refactor_pass: true
    mutation_enabled: false
    anti_pattern_check: true

  thorough:
    worker_profile: anthropic-smart      # Sonnet
    reviewer_profile: anthropic-fast     # Haiku reviewer
    review_enabled: true
    double_review: true                  # two review passes
    tdd_phases: [prepare, red_acceptance, red_unit, green, commit]
    refactor_pass: true
    mutation_enabled: false
    anti_pattern_check: true

  exhaustive:
    worker_profile: anthropic-opus       # Opus
    reviewer_profile: anthropic-smart    # Sonnet reviewer
    review_enabled: true
    double_review: true
    tdd_phases: [prepare, red_acceptance, red_unit, green, commit]
    refactor_pass: true
    mutation_enabled: true
    mutation_kill_threshold: 80
    anti_pattern_check: true

  inherit:
    worker_profile: null                 # use session model
    reviewer_profile: anthropic-fast
    review_enabled: true
    double_review: false
    tdd_phases: [prepare, red_acceptance, red_unit, green, commit]
    refactor_pass: true
    mutation_enabled: false
    anti_pattern_check: true
```

**DOT node usage:**

```dot
impl_auth [shape=box, handler="codergen",
    rigor="thorough",
    prompt="Implement JWT authentication..."]
```

**Resolution logic** (in `providers.py`):

```python
def resolve_rigor(node_attrs: dict, profiles: dict) -> RigorConfig:
    """Resolve rigor profile for a node. Falls back to 'standard'."""
    profile_name = node_attrs.get("rigor", "standard")
    profile = profiles.get(profile_name)
    return RigorConfig(
        worker_profile=profile["worker_profile"],
        reviewer_profile=profile.get("reviewer_profile"),
        tdd_depth=profile.get("tdd_depth", "full"),
        mutation_testing=profile.get("mutation_testing", False),
        anti_pattern_check=profile.get("anti_pattern_check", True),
    )
```

**Impact on pipeline_runner.py dispatch:**

1. Worker dispatch uses `rigor.worker_profile` instead of raw `llm_profile`
2. If `rigor.reviewer_profile` is set, a review sub-step runs between `impl_complete` and `validated`
3. If `rigor.tdd_depth == "full"`, the worker prompt includes TDD phase enforcement instructions
4. If `rigor.mutation_testing`, a mutation testing step runs before acceptance

### Selection Heuristic

| Task Characteristic | Recommended Rigor |
|---------------------|-------------------|
| Config changes, docs, env vars | lean |
| Standard features, CRUD, UI components | standard |
| Auth, payments, data integrity, security | thorough |
| Core business logic, compliance-critical | exhaustive |

The orchestrator (or System 3) selects rigor per-node when generating the pipeline DOT.

---

## Deep Dive: 7 Testing Anti-Patterns (Testing Theater Prevention)

### The Problem

LLM-generated tests frequently exhibit patterns that provide false confidence — tests that pass but don't actually verify behavior. nWave calls these the "7 Deadly Patterns."

### The 7 Patterns

| # | Pattern | Description | Detection Heuristic |
|---|---------|-------------|---------------------|
| 1 | **Tautological tests** | Assertions that are always true (`assert True`, `expect(1).toBe(1)`) | AST scan for literal-only assertions |
| 2 | **Mock-dominated tests** | More mock setup than actual assertions; testing mock behavior not real code | Ratio: mock lines / assertion lines > 3:1 |
| 3 | **Circular verification** | Test logic duplicates production logic rather than testing outcomes | Similarity score between test body and source function body |
| 4 | **Always-green tests** | Tests that can never fail regardless of implementation changes | Mutation: delete production code body → test should fail |
| 5 | **Implementation-mirroring** | Tests that break on any refactor because they test internal structure | References to private methods, internal state, or implementation details |
| 6 | **Assertion-free tests** | Tests with no assertions (rely on "no exception = pass") | Count assertions per test function; flag if 0 |
| 7 | **Hardcoded-oracle tests** | Expected values hardcoded from current output rather than derived from specification | Suspicious patterns: pasting exact JSON output as expected value |

### Integration into CoBuilder

**Where it fits**: These checks belong in the `validation-test-agent` (specifically `--mode=technical`) and as prompt injection into `tdd-test-engineer`.

#### Approach A: Prompt-Based Enforcement (Low effort, P1)

Add a "Testing Theater Prevention" section to `tdd-test-engineer.md` agent definition:

```markdown
## Testing Theater Prevention — 7 Deadly Patterns

Before marking any test suite complete, self-audit for these anti-patterns:

1. **Tautological**: Every assertion references at least one variable from the
   system under test. No `assert True`, no `expect(literal).toBe(literal)`.
2. **Mock-dominated**: If a test has >3 mock setups and <2 real assertions,
   restructure to test at a port boundary instead.
3. **Circular verification**: Never copy-paste production logic into test
   expected values. Derive expectations from the specification/requirements.
4. **Always-green**: For each test, mentally delete the function body being
   tested. Would the test fail? If not, fix the test.
5. **Implementation-mirroring**: Tests should verify WHAT (behavior/output),
   not HOW (method calls, internal state). No asserting on mock.call_count
   unless it's a genuine behavioral requirement.
6. **Assertion-free**: Every test function must have at least one assertion.
   "No error thrown" is not a test — add explicit outcome verification.
7. **Hardcoded-oracle**: Expected values should come from requirements or
   specification, not from running the code and pasting the output.

Report any detected anti-patterns in your signal response under
`anti_patterns_detected: []`.
```

#### Approach B: Automated Static Analysis Hook (Medium effort, P2)

Create a `PostToolUse` hook that runs after test file writes:

```python
# .claude/hooks/testing-theater-detector.py
# PostToolUse hook — matcher: "Edit|Write"
# Analyzes written test files for the 7 deadly patterns

def detect_anti_patterns(file_content: str, file_path: str) -> list[str]:
    """Returns list of detected anti-pattern names."""
    patterns = []

    if not is_test_file(file_path):
        return []

    # 1. Tautological — literal-only assertions
    if re.findall(r'assert\s+True|expect\(\d+\)\.toBe\(\d+\)', file_content):
        patterns.append("tautological")

    # 2. Mock-dominated — high mock:assertion ratio
    mock_lines = len(re.findall(r'mock|patch|MagicMock|jest\.fn', file_content))
    assert_lines = len(re.findall(r'assert |expect\(|should\.', file_content))
    if mock_lines > 0 and assert_lines > 0 and mock_lines / assert_lines > 3:
        patterns.append("mock-dominated")

    # 6. Assertion-free — test functions with no assertions
    test_fns = extract_test_functions(file_content)
    for fn in test_fns:
        if not re.search(r'assert |expect\(|should\.', fn.body):
            patterns.append("assertion-free")
            break

    return patterns
```

This hook would emit a `systemMessage` warning (not block) when anti-patterns are detected — similar to our `serena_enforce_pretool.py` nudge approach.

#### Approach C: Signal Response Validation (Medium effort, P2)

When a codergen worker's signal includes test files in `files_changed`, the runner can dispatch a lightweight anti-pattern scan before transitioning to `validated`:

```python
# In pipeline_runner.py, after receiving worker signal
if rigor.anti_pattern_check and signal.get("test_files_changed"):
    anti_patterns = run_static_analysis(signal["test_files_changed"])
    if anti_patterns:
        # Requeue with guidance
        write_signal({"status": "requeue", "reason": f"Testing theater detected: {anti_patterns}"})
```

### Extended: Test Code Smells Catalog (Beyond the 7 Deadly Patterns)

nWave also defines a **severity-tiered test smells catalog** (from `test-refactoring-catalog.md`):

| Severity | Smell | Description |
|----------|-------|-------------|
| **L1 Readability** | Obscure Test | Name doesn't reveal business scenario |
| L1 | Hard-Coded Test Data | Magic numbers lacking business context |
| L1 | Assertion Roulette | Multiple assertions without failure messages |
| **L2 Complexity** | Eager Test | Single test verifies multiple unrelated behaviors |
| L2 | Test Code Duplication | Repeated setup across 3+ tests |
| L2 | Conditional Test Logic | if/switch creating non-deterministic tests |
| **L3 Organization** | Mystery Guest | Tests depend on external files without explicit dependencies |
| L3 | Test Class Bloat | 15+ unrelated tests in one class |
| L3 | General Fixture | Shared setup used selectively |

**Detection heuristic from review-dimensions.md** — the "delete production code" falsifiability test:
1. Delete the production code body → does the test fail? If no → testing theater
2. Introduce a deliberate bug → does the test catch it? If no → testing theater

**Additional review signals**:
- Weakened assertions (`assertEquals` → `assertNotNull`) across commits
- Decreased assertion count between RED and GREEN phases
- "Test + implementation changed in same commit" during GREEN → automatic rejection

These L1-L3 smells are lower priority than the 7 deadly patterns but worth including in the `tdd-test-engineer` prompt for thoroughness.

### Recommendation

Start with **Approach A** (prompt injection) — it's zero infrastructure cost and leverages the LLM's own judgment. Graduate to **Approach B** (PostToolUse hook) for repeat offenders. **Approach C** is the most robust but requires pipeline_runner changes.

---

## Deep Dive: Hook-Based Worker Enforcement

### How nWave's DES Hooks Actually Work (From Source)

nWave registers **8 hooks** across 5 lifecycle events in `hooks.json`:

| Hook Type | Matcher | Handler | Purpose |
|-----------|---------|---------|---------|
| `PreToolUse` | `Agent` | `pre-task` | Validates DES markers before any subagent dispatch |
| `PreToolUse` | `Write` | `pre-write` | Blocks source writes unless DES subagent is active |
| `PreToolUse` | `Edit` | `pre-edit` | Same as Write guard |
| `PreToolUse` | `Bash` | inline shell | Blocks direct `execution-log.json` manipulation |
| `PostToolUse` | `Agent` | `post-tool-use` | Injects failure notifications if subagent failed |
| `SubagentStop` | `*` | `subagent-stop` | **Blocks exit** if TDD phases incomplete |
| `SessionStart` | `startup` | `session-start` | Housekeeping + update check |
| `SubagentStart` | `*` | `subagent-start` | DES task registration |

All hooks route through `claude_code_hook_adapter.py` which dispatches to handler modules.

#### Two Sentinel Files Control Everything

The entire enforcement system relies on just **two signal files**:

| File | Path | Meaning |
|------|------|---------|
| `DES_DELIVER_SESSION_FILE` | `.nwave/des/deliver-session.json` | A DELIVER session is active |
| `DES_TASK_ACTIVE_FILE` | `.nwave/des/des-task-active` | A DES-monitored subagent is running |

#### SessionGuardPolicy (Write/Edit Blocking Logic)

```python
PROTECTED_PATTERNS = ["src/", "tests/"]
ALLOWED_PATTERNS  = ["docs/feature/", ".nwave/", ".develop-progress"]

if not session_active:              → allow (no session, no restriction)
if path in ALLOWED_PATTERNS:        → allow (orchestration artifacts)
if path NOT in PROTECTED_PATTERNS:  → allow (unprotected file)
if des_task_active:                 → allow (subagent is doing it correctly)
else:                               → BLOCK — "Source/test files must be written
                                      by a DES-monitored software-crafter subagent,
                                      not directly by the orchestrator."
```

**In plain English**: During DELIVER, the orchestrator cannot write to `src/` or `tests/` — only DES-monitored subagents can. This enforces the orchestrator/worker boundary at the hook level, not just via prompt instructions.

#### SubagentStop Validation (The Killer Pattern)

This is the most powerful enforcement: **prevents the subagent from exiting** unless all TDD phases are complete.

On subagent exit, `SubagentStopService` checks:
1. `execution-log.json` exists and project_id matches
2. All 5 phases (PREPARE, RED_ACCEPTANCE, RED_UNIT, GREEN, COMMIT) are EXECUTED or SKIPPED
3. A git commit with `Step-ID: {step_id}` trailer exists
4. Log integrity (timestamps are plausible, not fabricated)
5. If incomplete: **blocks exit** with instructions to fix → second-attempt escape hatch via `stop_hook_active` flag to avoid infinite loops

#### Fail-Open vs Fail-Closed Asymmetry

| Hook | On Exception | Rationale |
|------|-------------|-----------|
| Pre-Task (Agent dispatch) | **Fail-closed** (block) | Prevent unchecked work |
| Pre-Write/Edit | **Fail-open** (allow) | Don't break the agent mid-task |
| SubagentStop | **Fail-closed** (block) | Don't let incomplete work escape |

#### StaleExecutionDetector

Scans step files for phases stuck in `IN_PROGRESS`:
- **Timeout**: 30 minutes → phase is stale
- **Stall**: 20 minutes with zero turn-count advancement → agent likely crashed
- Reports `StaleExecution` objects for the orchestrator to handle

### What We Can Borrow for CoBuilder Workers

Our harness already has the hook infrastructure (`PreToolUse`, `PostToolUse` in `settings.json`). We have a working pattern in `serena_enforce_pretool.py`. The question is: **what enforcement is worth the complexity?**

#### Design: Worker Discipline Hook (`worker-discipline-pretool.py`)

A `PreToolUse` hook that enforces discipline on worker agents (Level 3):

```python
# .claude/hooks/worker-discipline-pretool.py
# PreToolUse hook — matcher: "Edit|Write"
# Only active when WORKER_DISCIPLINE_MODE is set

DISCIPLINE_MODES = {
    "tdd": {
        # Phase-gated file writes
        "phases": ["prepare", "red", "green", "refactor", "commit"],
        "red_allowed": ["tests/**", "**/*.test.*", "**/*.spec.*"],
        "green_allowed": ["src/**", "lib/**", "app/**"],
        "refactor_allowed": ["*"],  # both source and tests
    },
    "read-only": {
        # Investigation mode — no writes at all
        "blocked_tools": ["Edit", "Write"],
    },
    "scoped": {
        # Only modify files within a declared scope
        "scope_env": "WORKER_FILE_SCOPE",  # comma-separated globs
    },
}
```

**Activation**: Set `WORKER_DISCIPLINE_MODE=tdd` in the worker's environment when dispatching via AgentSDK. The hook is a no-op when the env var is unset (doesn't affect orchestrators or System 3).

**Phase tracking**: The worker writes phase markers to a state file (`.claude/state/worker-phase.json`). The hook validates writes against the current phase.

#### The SubagentStop Pattern — Adapting for CoBuilder

nWave's SubagentStop hook is their most effective enforcement mechanism. We can adapt this for our `Stop` hook (which we already have as `unified-stop-gate.sh`).

**Design: TDD Completion Gate in Stop Hook**

When `WORKER_DISCIPLINE_MODE=tdd` is set, the stop gate additionally checks:

```python
# In unified_stop_gate, add a TDD completion checker
def check_tdd_completion():
    """Block stop if worker hasn't completed required TDD phases."""
    if os.environ.get("WORKER_DISCIPLINE_MODE") != "tdd":
        return None  # Not enforced

    phase_file = Path(".claude/state/worker-phase.json")
    if not phase_file.exists():
        return "BLOCK: No TDD phase tracking found. Complete your phases."

    state = json.loads(phase_file.read_text())
    required = {"prepare", "red", "green", "commit"}
    completed = set(state.get("phases_completed", []))
    missing = required - completed

    if missing:
        # Second attempt escape (like nWave's stop_hook_active)
        if state.get("stop_attempts", 0) >= 2:
            return None  # Allow exit to prevent infinite loop
        state["stop_attempts"] = state.get("stop_attempts", 0) + 1
        phase_file.write_text(json.dumps(state))
        return f"BLOCK: TDD phases incomplete. Missing: {', '.join(missing)}"

    return None
```

This is a lower-complexity version of nWave's SubagentStop — using our existing stop gate infrastructure.

#### How This Differs from nWave's Approach

| Aspect | nWave DES | CoBuilder Worker Discipline |
|--------|-----------|----------------------------|
| **Scope** | Always active during DELIVER | Opt-in per worker dispatch |
| **Phase tracking** | Mandatory 5-phase with audit log | Optional, worker self-reports |
| **Blocking** | Hard block via SubagentStop | Stop gate block (existing infra) |
| **Sentinel files** | 2 files (`deliver-session.json`, `des-task-active`) | 1 file (`worker-phase.json`) |
| **Fail behavior** | Fail-closed for tasks, fail-open for writes | Configurable per hook |
| **Escape hatch** | `stop_hook_active` flag (2nd attempt) | `stop_attempts` counter (same idea) |
| **Integration** | Plugin hooks | Harness hooks (same mechanism) |

#### Practical Concern: Hook Overhead

Every `Edit`/`Write` call would invoke the hook script. At ~10ms per invocation, this is negligible for typical worker sessions (10-50 edits). But for high-volume batch operations, the overhead matters.

**Recommendation**: Start with **prompt-based TDD enforcement** in the `tdd-test-engineer` agent definition. Only add hook-based enforcement if workers consistently ignore TDD discipline despite prompt instructions. The prompt approach is zero-overhead and leverages the LLM's compliance tendency.

#### What's Worth Implementing Now (Revised Priority)

1. **Scope enforcement** (`WORKER_FILE_SCOPE`) — prevents workers from modifying files outside their assigned scope. Highest-value guard.
2. **Orchestrator write protection** — we enforce this via output-style instructions, but nWave shows a `PreToolUse` hook makes it foolproof. Their two-sentinel-file approach is elegant and simple.
3. **Stop gate TDD checker** — adapted from nWave's SubagentStop. Low complexity since it plugs into our existing `unified-stop-gate.sh`.
4. **Fail-open/fail-closed asymmetry** — adopt nWave's pattern: fail-closed for task dispatch validation, fail-open for write hooks. Currently our hooks don't distinguish.

---

## Deep Dive: SDLC Lifecycle Pipeline Template

### Design: `tdd-first` Template

Inspired by nWave's 6-wave sequence but adapted to CoBuilder's DAG flexibility:

```
research → design → distill (acceptance tests) → deliver (TDD) → validate
```

Key differences from nWave:
- **No fixed DISCOVER/DISCUSS waves** — these map to System 3's existing ideation phase
- **Distill before Deliver** — write acceptance tests BEFORE implementation (TDD-first)
- **Parallel delivery** — CoBuilder's hub-spoke allows parallel worker dispatch within DELIVER
- **Configurable rigor** — each node inherits from the template's rigor profile

### Template Definition

```yaml
# .cobuilder/templates/tdd-first/manifest.yaml
template:
  name: tdd-first
  version: "1.0"
  description: >
    TDD-first development lifecycle: research problem → design solution →
    write acceptance tests → implement via TDD → validate against acceptance criteria.
    Inspired by nWave's SDLC waves, adapted for CoBuilder DAG execution.
  topology: linear
  min_nodes: 7
  max_nodes: 15

parameters:
  initiative_id:
    type: string
    required: true
  target_dir:
    type: string
    required: true
  business_spec_path:
    type: string
    required: true
  rigor:
    type: string
    required: false
    default: "standard"
    description: "Rigor profile: lean, standard, thorough, exhaustive"
  tasks:
    type: list
    required: true
    description: "List of implementation tasks for the DELIVER phase"
  require_human_gates:
    type: boolean
    required: false
    default: true

defaults:
  llm_profile: "anthropic-fast"
```

### Template Graph

```dot
digraph "tdd-first-{{ initiative_id }}" {
    // RESEARCH — understand the problem
    start -> research;

    // DESIGN — architecture + solution design
    research -> design;

    // DISTILL — write acceptance tests BEFORE implementation
    design -> distill;

    // Optional human gate before implementation
    {% if require_human_gates %}
    distill -> gate_review;
    gate_review -> deliver;
    {% else %}
    distill -> deliver;
    {% endif %}

    // DELIVER — TDD implementation (hub-spoke if multiple tasks)
    {% for task in tasks %}
    deliver -> impl_{{ task.id }};
    impl_{{ task.id }} -> fan_in;
    {% endfor %}

    // VALIDATE — run acceptance tests against implementation
    fan_in -> validate;
    validate -> close;
}
```

### How It Maps to nWave Waves

| nWave Wave | tdd-first Node | Notes |
|------------|----------------|-------|
| DISCOVER | (pre-pipeline) | System 3 handles discovery before pipeline launch |
| DISCUSS | (pre-pipeline) | PRD exists before pipeline instantiation |
| DESIGN | `design` | solution-architect produces SD + ADRs |
| DEVOPS | (omitted) | Infrastructure is typically pre-existing |
| DISTILL | `distill` | acceptance-test-writer creates Gherkin specs |
| DELIVER | `impl_*` (fan-out) | tdd-test-engineer + backend/frontend workers |

### Key Innovation: Tests Before Code

The `distill` node runs `acceptance-test-writer` to produce Gherkin feature files. These become the contract that `impl_*` workers must satisfy. The `validate` node then runs `acceptance-test-runner` against the implementation.

This inverts the typical "implement then test" flow and aligns with nWave's core philosophy — but within CoBuilder's flexible DAG structure.

---

## Updated Recommendations

| Priority | Pattern | Effort | Impact | Status |
|----------|---------|--------|--------|--------|
| **P1** | Rigor profiles in providers.yaml | Low | High — cost optimization per task criticality | Design complete |
| **P1** | Testing anti-patterns in tdd-test-engineer prompt | Low | High — prevents testing theater at zero infra cost | Design complete |
| **P2** | tdd-first pipeline template | Medium | High — enforces TDD-first workflow structurally | Design complete |
| **P2** | Scope enforcement hook (`WORKER_FILE_SCOPE`) | Medium | Medium — prevents workers from modifying unrelated files | Design complete |
| **P3** | Peer review nodes (cheap reviewer before validation) | Medium | Medium — catches issues earlier | Outlined |
| **P4** | PostToolUse anti-pattern detection hook | Medium | Medium — automated testing theater detection | Design complete |
| **P4** | Full TDD phase-gating hook | High | Low — prompt enforcement is usually sufficient | Designed, deferred |
| **P5** | Formalized agent specification schema | Low | Low — documentation improvement | Outlined |

---

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| Research & Evaluation | Done | 2026-03-17 | - |
| Deep Dive: Rigor Profiles | Done | 2026-03-17 | - |
| Deep Dive: Testing Anti-Patterns | Done | 2026-03-17 | - |
| Deep Dive: Hook Enforcement | Done | 2026-03-17 | - |
| Deep Dive: SDLC Template | Done | 2026-03-17 | - |
| Rigor Profiles Implementation (P1) | Remaining | - | - |
| Anti-Pattern Prompt Injection (P1) | Remaining | - | - |
| tdd-first Template (P2) | Remaining | - | - |
| Scope Enforcement Hook (P2) | Remaining | - | - |
