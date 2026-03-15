---
title: "SD-PIPELINE-RUNNER-HARDENING-001: Pipeline Runner & Worker Hardening"
status: active
type: architecture
last_verified: 2026-03-10
grade: authoritative
prd_ref: PRD-HARNESS-UPGRADE-001
---

# SD-PIPELINE-RUNNER-HARDENING-001: Pipeline Runner & Worker Hardening

## 1. Context & Motivation

### 1.1 Current State (2026-03-09)

The `pipeline_runner.py` has run **7 pipelines in the last 24 hours** producing **81 signal files** with **zero failures**. Logfire confirms zero exceptions. However, deep code analysis reveals **4 critical latent bugs** that will surface under adversarial conditions (concurrent workers, crash recovery, validation timeouts).

### 1.2 Evidence Summary

| Source | Finding |
|--------|---------|
| **Logfire (24h)** | 5 pipeline spans, 0 exceptions. Longest: 85min (AURA-LIVEKIT impl). Workers avg ~6min each. Parallel dispatch confirmed (B+C at same second). |
| **Code Analysis** | 4 CRITICAL, 4 MEDIUM, 3 LOW severity issues identified |
| **Signal Files** | 81 signals processed, all `result: pass`. Zero `fail` or `requeue` signals observed. |
| **Worker Telemetry** | Tools used: Bash(40%), Read(25%), Write(15%), Grep/Glob(12%), TaskCreate/Update(5%), Explore(3%) |

### 1.3 The Problem

The runner works perfectly on the **happy path**. But it has never been stress-tested on:
- Concurrent signal writes from parallel workers
- Validation agent crashes mid-execution
- Force-status persistence across DOT reloads
- Corrupted signal file recovery
- Orphaned non-codergen nodes after crash

These are **ticking time bombs** — invisible until they detonate during a critical pipeline run.

### 1.4 Research Pipeline Evidence (2026-03-09)

A 4-node research pipeline was run to validate the SD. **The failures proved the thesis:**

| Node | Outcome | What It Proves |
|------|---------|----------------|
| `research_worker_context` | **FAILED 3/3** — worker modified SD with code fixes instead of research | Workers don't understand handler roles. Prompts are identical for codergen/research/refine. |
| `research_signal_atomicity` | **CRASHED** — JSON buffer overflow (1MB). No signal written. Node stuck `active` forever. | Dead workers leave nodes orphaned. No liveness check. No signal timeout. |
| `research_feedback_loops` | **ACCEPTED** — comprehensive doc on act-observe-correct loops | Current validation is sequential + binary. Needs parallel, predictive, graduated feedback. |
| `research_env_legibility` | **2 docs written** — gap analysis scores codebase | Discoverability: 5/10. Failure handling: 3/10. Inter-agent communication: 4/10. |

**2 new bugs discovered during the run:**
1. **Dead SDK workers → zombie nodes**: When worker process dies without writing signal, node stays `active` forever. Runner has no process liveness check.
2. **Validation agent spam**: After node reaches `accepted`, runner dispatches ~6 extra validation signals (blocked but noisy).

### 1.5 Harness Engineering Principles (Research Basis)

Per Anthropic, OpenAI, and Martin Fowler harness engineering best practices:

1. **Environment Legibility** > plumbing fixes. Make the codebase discoverable with AGENTS.md, architecture diagrams, schemas, and principles encoded in repo files.
2. **Worker Context** > raw model power. Workers need to know their role, what happened before them, and what "done" looks like for their specific handler type.
3. **Feedback Loops** > binary pass/fail. Implement act-observe-correct loops with graduated, actionable feedback.
4. **Constraints** > micromanagement. Enforce boundaries (linter rules, structured logging, schema validation) to prevent drift.

**Priority rebalancing**: Worker context and legibility promoted to P0 alongside signal/crash fixes. The root cause of the `research_worker_context` failure (workers don't know their role) is more impactful than signal atomicity (which only manifests under concurrent writes).

### 1.6 ToolSearch Gap Discovery (2026-03-10)

**Root cause**: Two separate mechanisms gate MCP tool access in Claude Code SDK:

1. **`allowed_tools` (permission gate)**: A restrict list — ONLY listed tools can be called. If any tool is listed, unlisted tools are blocked. If `allowed_tools` is omitted entirely, ALL tools are available.
2. **ToolSearch (schema discovery)**: MCP tools are deferred — their schemas are NOT in the agent's context until loaded via ToolSearch. Even with permission, the agent can't call a tool it doesn't know exists.

**Both mechanisms must be satisfied**: the tool must be in `allowed_tools` AND loaded via ToolSearch.

| File | Issue |
|------|-------|
| `pipeline_runner.py` `allowed_tools` | Listed Serena tools but NOT context7/Hindsight/Perplexity — research/refine workers were permission-blocked from MCP research tools |
| `pipeline_runner.py` prompts | No handler-specific preambles — all workers got identical generic prompts regardless of role |
| `run_research.py:83` | Prompt says "you do NOT need to use ToolSearch" — **false** |
| `run_refine.py:106` | Same incorrect claim. Additionally, `ToolSearch` was **missing from `allowed_tools`** |
| `worker-tool-reference.md` | Zero mention of ToolSearch or deferred tool loading |

**Context7 finding** (Claude Code agent docs): "Agents can use MCP tools autonomously without requiring pre-allowed lists, allowing Claude to determine which tools are necessary for the task at hand." — This means omitting `allowed_tools` gives agents ALL tools. We chose to keep explicit lists for role isolation (codergen shouldn't research, research shouldn't implement).

**Fix applied (2 phases)**:

Phase 1 (initial): ToolSearch added to all `allowed_tools` lists. Prompts updated with mandatory ToolSearch loading step. `worker-tool-reference.md` updated with ToolSearch section.

Phase 2 (deeper fix): Handler-specific `allowed_tools` — each handler type (codergen, research, refine) gets only the MCP tools appropriate for its role. Research workers get context7 + Perplexity + Hindsight. Refine workers get Hindsight + perplexity_reason. Codergen workers get Serena only. Prompts changed from "here are the exact tool names" to "use ToolSearch to discover available tools" — letting the agent self-discover rather than hardcoding names.

**Validated**: Test pipeline v3 (research node) successfully used ToolSearch → context7 → Hindsight in sequence.

---

## 2. Architecture Changes (Rebalanced Post-Research)

### 2.1 Epic A: Atomic Signal File Protocol (P0 — Critical)

**Problem**: `_write_node_signal()` does direct file writes without atomic guarantees. Concurrent writes to same node_id.json race silently.

**Current** (pipeline_runner.py:1419-1476):
```python
with open(signal_path, "w") as fh:
    fh.write(json.dumps(payload) + "\n")
```

**Proposed**:
```python
def _write_node_signal(self, node_id: str, payload: dict) -> str:
    signal_path = os.path.join(self.signal_dir, f"{node_id}.json")
    tmp_path = signal_path + f".tmp.{os.getpid()}.{time.monotonic_ns()}"

    # Add sequence number for ordering
    payload["_seq"] = self._signal_seq.get(node_id, 0) + 1
    self._signal_seq[node_id] = payload["_seq"]
    payload["_ts"] = datetime.utcnow().isoformat() + "Z"

    with open(tmp_path, "w") as fh:
        fh.write(json.dumps(payload) + "\n")
        fh.flush()
        os.fsync(fh.fileno())

    os.rename(tmp_path, signal_path)  # Atomic on POSIX
    return signal_path
```

**Also fix signal consumption order** (pipeline_runner.py:1230-1243):
```python
# BEFORE: consume then apply (data loss on crash)
os.rename(signal_path, dest)  # ← signal lost if _apply_signal crashes
self._apply_signal(node_id, signal)

# AFTER: apply then consume (idempotent)
self._apply_signal(node_id, signal)
os.rename(signal_path, dest)  # Only consumed after successful apply
```

**Corrupted signal handling**:
```python
except (OSError, json.JSONDecodeError) as exc:
    # Quarantine instead of silently skipping
    quarantine = os.path.join(self.signal_dir, "quarantine")
    os.makedirs(quarantine, exist_ok=True)
    shutil.move(signal_path, os.path.join(quarantine, os.path.basename(signal_path)))
    log.error("Quarantined corrupted signal %s: %s", signal_path, exc)
```

**Files to modify**:
- `pipeline_runner.py`: `_write_node_signal()`, `_process_signals()`, `_apply_signal()`

**Acceptance Criteria**:
- AC-1: Signal writes use temp-file-then-rename (atomic on POSIX)
- AC-2: Each signal includes `_seq` and `_ts` metadata fields
- AC-3: Corrupted signals moved to `signals/quarantine/` (not silently dropped)
- AC-4: Signal consumption happens AFTER successful transition application
- AC-5: Concurrent write test: 10 parallel writers, zero corruption

---

### 2.2 Epic B: force_status Persistence Fix (P0 — Critical)

**Problem**: `_force_status()` edits in-memory `self.dot_content` but `_main_loop()` reloads DOT from disk, clobbering the forced status.

**Current** (pipeline_runner.py ~line 1380):
```python
def _force_status(self, node_id, target_status):
    # Edits self.dot_content in memory only
    self.dot_content = self.dot_content.replace(...)
```

**Meanwhile** (pipeline_runner.py:335-349):
```python
# Main loop reloads from disk → clobbers in-memory edits
with open(self.dot_path) as fh:
    self.dot_content = fh.read()
```

**Proposed**: Use `_do_transition()` (which already writes to disk with fcntl lock) instead of `_force_status()`:

```python
def _force_status(self, node_id: str, target_status: str) -> None:
    """Force node status — writes to disk (not just memory)."""
    self._do_transition(node_id, target_status)
    # Also persist requeue guidance if present
    if node_id in self.requeue_guidance:
        self._persist_requeue_guidance(node_id, self.requeue_guidance[node_id])
```

**Files to modify**:
- `pipeline_runner.py`: `_force_status()`, add `_persist_requeue_guidance()`

**Acceptance Criteria**:
- AC-1: `_force_status()` writes to DOT file on disk (not just memory)
- AC-2: Status survives `_main_loop()` reload cycle
- AC-3: Requeue guidance persisted alongside status change
- AC-4: Test: force_status → reload DOT → verify status persists

---

### 2.3 Epic C: Validation Agent Error Handling (P0 — Critical)

**Problem**: Validation subprocess failures are invisible. If validation agent crashes, node stays `impl_complete` forever — "Pipeline stuck" with no clear cause.

**Current** (pipeline_runner.py:933-1210):
- Spawns validation subprocess in background
- No stdout/stderr capture
- No timeout enforcement
- No retry on failure

**Proposed**:

```python
def _dispatch_validation_agent(self, node_id, target_node_id):
    """Dispatch validation with error handling and configurable timeout."""
    timeout = int(os.environ.get("VALIDATION_TIMEOUT", "600"))  # 10min default

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            log.error("[validation] %s failed (rc=%d): %s",
                     node_id, result.returncode, result.stderr[:500])
            # Write failure signal so node doesn't hang
            self._write_node_signal(target_node_id, {
                "status": "fail",
                "result": "fail",
                "reason": f"Validation agent crashed: {result.stderr[:200]}",
                "validator_exit_code": result.returncode,
            })

    except subprocess.TimeoutExpired:
        log.error("[validation] %s timed out after %ds", node_id, timeout)
        self._write_node_signal(target_node_id, {
            "status": "fail",
            "result": "fail",
            "reason": f"Validation timed out after {timeout}s",
        })
```

**Files to modify**:
- `pipeline_runner.py`: `_dispatch_validation_agent()`

**Acceptance Criteria**:
- AC-1: Validation timeout configurable via `VALIDATION_TIMEOUT` env var (default 600s)
- AC-2: Validation failures write explicit `fail` signal (node never hangs)
- AC-3: stderr captured and included in failure signal (first 500 chars)
- AC-4: Test: mock validation crash → verify fail signal written within 5s

---

### 2.4 Epic D: Orphaned Node Resume Expansion (P1 — High)

**Problem**: After runner restart, only `codergen` nodes with status `active` are re-dispatched. Orphaned `research`, `refine`, and `acceptance-test-writer` nodes remain stuck.

**Current** (pipeline_runner.py:384-393):
```python
orphaned_active_nodes = [
    n for n in nodes
    if n["attrs"].get("status") == "active"
    and n["attrs"].get("handler") == "codergen"  # ← Only codergen!
    and n["id"] not in self.active_workers
]
```

**Proposed**:
```python
RESUMABLE_HANDLERS = frozenset({"codergen", "research", "refine", "acceptance-test-writer"})
GATE_HANDLERS = frozenset({"wait.cobuilder", "wait.human"})

orphaned_active_nodes = [
    n for n in nodes
    if n["attrs"].get("status") == "active"
    and n["id"] not in self.active_workers
]

for node in orphaned_active_nodes:
    handler = node["attrs"].get("handler", "")
    if handler in RESUMABLE_HANDLERS:
        retries = self.orphan_resume_counts.get(node["id"], 0)
        if retries < 3:  # Exponential backoff
            delay = min(2 ** retries * 5, 60)  # 5s, 10s, 20s, max 60s
            log.info("[resume] Re-dispatch %s (handler=%s, attempt=%d, delay=%ds)",
                    node["id"], handler, retries + 1, delay)
            time.sleep(delay)
            self._dispatch_node(node, data)
            self.orphan_resume_counts[node["id"]] = retries + 1
        else:
            log.error("[resume] Exhausted retries for orphaned node %s", node["id"])
            self._do_transition(node["id"], "failed")
    elif handler in GATE_HANDLERS:
        log.warning("[resume] Gate node %s stuck in active — emitting escalation", node["id"])
        self._write_node_signal(node["id"], {
            "status": "escalation",
            "reason": f"Gate node {node['id']} orphaned after restart",
        })
```

**Files to modify**:
- `pipeline_runner.py`: orphaned node detection block, add `orphan_resume_counts` dict

**Acceptance Criteria**:
- AC-1: All WORKER_HANDLERS covered by orphan resume (not just codergen)
- AC-2: Exponential backoff: 5s, 10s, 20s delays between retries
- AC-3: Max 3 retries per orphaned node before marking failed
- AC-4: Gate nodes (wait.cobuilder, wait.human) emit escalation signal instead of re-dispatch
- AC-5: Test: simulate crash → verify research/refine nodes resume correctly

---

### 2.5 Epic E: Worker Prompt Improvements (P1 — High)

**Problem**: Workers receive identical prompts regardless of handler type. Research nodes don't know they should validate docs. Validation agents don't see git diffs. Requeue guidance is lost after first dispatch.

**5 sub-improvements**:

#### E.1: Handler-Specific Prompt Preambles

```python
HANDLER_PREAMBLES = {
    "codergen": "You are implementing code changes. Write production-quality code.",
    "research": "You are researching framework patterns. Validate docs against installed versions. Update the SD with findings.",
    "refine": "You are refining a Solution Design. Merge research findings into the SD as first-class content.",
    "acceptance-test-writer": "You are writing Gherkin acceptance tests from the PRD acceptance criteria.",
}
```

#### E.2: Validation Prompt Gets Pre-Computed Diff

```python
def _build_validation_prompt(self, node_id, ...):
    # Pre-compute diff so validator doesn't waste 30s
    diff = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1"],
        capture_output=True, text=True, timeout=10
    ).stdout[:2000]

    prompt += f"\n## Changes Made\n```\n{diff}\n```\n"
```

#### E.3: Persistent Requeue Guidance

```python
# Instead of .pop() (one-shot), keep guidance in persistent store
def _get_requeue_guidance(self, node_id):
    # Check persistent file first
    guidance_path = os.path.join(self.signal_dir, "guidance", f"{node_id}.txt")
    if os.path.exists(guidance_path):
        return open(guidance_path).read()
    return self.requeue_guidance.get(node_id, "")
```

#### E.4: Worker Model Selection Documentation

Add to `worker-tool-reference.md`:
```markdown
## Model Selection Guide
| Handler | Default Model | When to Override |
|---------|--------------|-----------------|
| codergen | Haiku 4.5 | Sonnet for complex multi-file changes |
| research | Haiku 4.5 | Rarely needs upgrade |
| refine | Sonnet 4.6 | Always Sonnet (requires synthesis) |
| validation | Sonnet 4.6 | Never downgrade (needs judgment) |
```

#### E.5: SD Path Fallback Clarity

```python
# Replace ambiguous "(none)" with actionable message
if not os.path.exists(sd_path):
    sd_section = f"## Solution Design\nNo SD found at `{sd_path}`. If this is unexpected, check the DOT node's sd_path attribute."
```

**Files to modify**:
- `pipeline_runner.py`: `_build_worker_prompt()`, `_build_validation_prompt()`, requeue guidance
- `.claude/agents/worker-tool-reference.md`: model selection section

**Acceptance Criteria**:
- AC-1: Each handler type gets a distinct preamble in the worker prompt
- AC-2: Validation prompts include pre-computed `git diff --stat`
- AC-3: Requeue guidance persists across dispatches (not one-shot `.pop()`)
- AC-4: Model selection guide added to worker-tool-reference.md
- AC-5: SD path fallback shows actionable error (not just "(none)")

---

### 2.6 Epic F: Global Pipeline Safeguards (P2 — Medium)

#### F.1: Pipeline Timeout

```python
# Add --max-duration flag
parser.add_argument("--max-duration", type=int, default=7200,
                   help="Max pipeline duration in seconds (default: 2h)")
```

In main loop:
```python
if time.monotonic() - self.start_time > self.max_duration:
    log.error("[timeout] Pipeline exceeded %ds. Failing remaining nodes.", self.max_duration)
    for node_id in self._get_non_terminal_nodes():
        self._do_transition(node_id, "failed")
    return PipelineResult.TIMEOUT
```

#### F.2: Cost Tracking in Signals

```python
# Workers report token usage in signal
{
    "status": "success",
    "cost": {"input_tokens": 12500, "output_tokens": 3400, "model": "haiku-4.5"},
    ...
}
```

Runner aggregates:
```python
self.pipeline_cost = {
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "by_node": {},
}
```

#### F.3: Rate Limiting Per Worker Type

```python
# Prevent API rate limit exhaustion
WORKER_TYPE_LIMITS = {
    "codergen": 4,      # Max 4 parallel codergen workers
    "research": 6,      # Research is lightweight
    "validation": 2,    # Validation needs sequential access
}
```

**Acceptance Criteria**:
- AC-1: `--max-duration` flag with 2h default, failing remaining nodes on timeout
- AC-2: Cost data (tokens, model) included in worker signal payloads
- AC-3: Per-worker-type concurrency limits configurable via env vars

---

### 2.7 Epic G: Worker Context & Handler-Specific Preambles (P0 — Critical, NEW)

**Problem proven by research_worker_context failure**: Workers don't understand their handler role. A research node modified the SD with implementation fixes instead of conducting comparative research. Validator correctly rejected 3/3 times.

**Root cause**: `_build_worker_prompt()` generates identical prompts regardless of handler type. Workers have no context about:
- What their handler role means (research ≠ codergen ≠ refine)
- What happened in predecessor nodes (no prior-node-outcome injection)
- What "done" looks like for their specific handler type
- Decision history from the pipeline

**Additional root cause discovered in research_feedback_and_verification_loops.md**: The validation system has sequential processing with limited automated recovery and heavy reliance on human intervention. The act-observe-correct loops need strengthening with more predictive and parallel validation capabilities.

**Enhanced patterns from research_feedback_and_verification_loops.md integration**:

```python
HANDLER_CONTEXT = {
    "codergen": {
        "preamble": """You are an IMPLEMENTATION worker. Your job is to write production-quality code.
DO NOT research, investigate, or write documentation — only implement.
Read the Solution Design carefully. It contains the exact changes to make.

FEEDBACK LOOPS: Your implementation will be validated in the next phase. Pay attention to the PRD acceptance criteria to ensure you're building the right thing.""",
        "done_criteria": "All files changed, tests pass, signal written with files_changed list.",
    },
    "research": {
        "preamble": """You are a RESEARCH worker. Your job is to investigate and document findings.
DO NOT modify source code or the Solution Design directly.
Write your findings to a NEW markdown file (not the SD) at the repo root.
Use WebSearch, WebFetch, and Read to gather information from external sources AND the codebase.
Compare best practices against the current implementation.

FEEDBACK LOOPS: Focus on gathering objective data about current state versus best practices. Do not implement changes.""",
        "done_criteria": "Research doc written with all acceptance criteria addressed. Signal written with doc path.",
    },
    "refine": {
        "preamble": """You are a REFINEMENT worker. Your job is to merge research findings into the Solution Design.
Read the research docs produced by predecessor nodes (check signal files for paths).
Edit the SD to incorporate findings as first-class content (not annotations).
Use Hindsight reflect before editing to check for prior patterns.

FEEDBACK LOOPS: Ensure research findings are properly integrated into the SD structure with clear traceability to source research.""",
        "done_criteria": "SD updated with research findings integrated. No research annotations remain.",
    },
    "acceptance-test-writer": {
        "preamble": """You are a TEST WRITER. Your job is to create Gherkin acceptance test scenarios.
Read the PRD acceptance criteria. Write .feature files with Given/When/Then.
Tests should be blind (not peek at implementation).

FEEDBACK LOOPS: Create comprehensive test coverage that will effectively validate the implementation against PRD requirements.""",
        "done_criteria": "Feature files written with scenarios covering all PRD acceptance criteria.",
    },
}

# Incorporate the validation patterns from research_feedback_and_verification_loops.md
VALIDATION_CONTEXT = {
    "validation-test-agent": {
        "dual_pass_validation": {
            "technical_pass": [
                "Unit tests pass (pytest/jest)",
                "Code builds successfully (npm run build)",
                "Import resolution verified",
                "No TODO/FIXME in changed scope",
                "Dependencies valid (pip check/npm ls)",
                "Type-checking passes (mypy/tsc)",
                "Linting clean (eslint/ruff)"
            ],
            "business_pass": [
                "PRD requirements met",
                "User journeys functional",
                "Business outcomes achieved"
            ]
        },
        "act_observe_correct": {
            "act": "Workers implement features, validators run tests",
            "observe": "System monitors signal files and task states",
            "correct": "Failed validations trigger rework cycles or rejection signals"
        },
        "hidden_tests": [
            "Contract Verification: API contract invariants enforced",
            "Import Resolution: Ensures no broken dependencies",
            "Type Safety: Static type checking requirements",
            "Build Integrity: Compilation/execution validation",
            "Documentation Consistency: PRD-to-implementation traceability"
        ]
    }
}

# Additional validation agent patterns from research_feedback_and_verification_loops.md:
VALIDATION_AGENT_PATTERNS = {
    "feedback_design": {
        "specificity": "Precise identification of what failed",
        "context": "Clear explanation of why it matters",
        "guidance": "Concrete steps for remediation",
        "priority": "Critical vs minor issues differentiation",
        "verification_path": "Clear steps to confirm fixes"
    },
    "self_correction": {
        "capabilities": [
            "Missing acceptance tests (automatically generated)",
            "Technical validation failures (rerun with feedback)",
            "Build errors (retry after fixes)",
            "Type errors (suggest fixes)"
        ],
        "escalation_triggers": [
            "Critical acceptance criteria failures",
            "Security vulnerabilities",
            "Performance degradation",
            "Architecture violations",
            "Human judgment required scenarios"
        ]
    },
    "validation_enhancement": {
        "real_time_validation": "Inline validation during coding",
        "predictive_analytics": "Early detection of likely validation failures",
        "adaptive_learning": "Improved validation based on past patterns",
        "parallel_validation": "Run multiple validation types simultaneously",
        "continuous_monitoring": "Ongoing validation during development"
    }
}
```

**Enhanced Act-Observe-Correct Loop Patterns** (Integrated from research_feedback_and_verification_loops.md):

The system implements validation loops through:
1. **Worker-Reporter Pattern**: Workers report completion, validation agent observes state
2. **Signal-Based Communication**: JSON signal files communicate status between components
3. **State Transitions**: Pending → Active → Impl_Complete → Validated → Accepted

The enhanced loop components now include:
- **Act**: Workers implement features, validators run tests with predictive validation
- **Observe**: System monitors signal files and task states with real-time feedback
- **Correct**: Failed validations trigger rework cycles, automated recovery attempts, or rejection signals

**Enhanced Prior-node-outcome injection** — embed predecessor signals and validation context in prompt:

```python
def _inject_predecessor_context(self, node_id, data):
    """Read signals from predecessor nodes and embed in prompt with validation context."""
    predecessors = data.get("edges", {}).get(node_id, {}).get("predecessors", [])
    context_lines = []

    for pred_id in predecessors:
        # Find the most recent processed signal file for this predecessor
        signal_path = os.path.join(self.signal_dir, "processed", f"*-{pred_id}.json")
        import glob
        signals = sorted(glob.glob(signal_path))
        if signals:
            with open(signals[-1]) as f:
                sig = json.load(f)
            context_lines.append(f"### Predecessor: {pred_id}")
            context_lines.append(f"- Status: {sig.get('status', 'unknown')}")
            context_lines.append(f"- Result: {sig.get('result', 'N/A')}")
            context_lines.append(f"- Files: {sig.get('files_changed', [])}")
            context_lines.append(f"- Message: {sig.get('message', 'N/A')[:200]}")
            if 'reason' in sig:
                context_lines.append(f"- Reason: {sig['reason'][:200]}")

    # Add validation context for upcoming validation phases
    if node_id.startswith("validation"):
        context_lines.extend([
            "",
            "## Validation Context",
            "This validation will check:",
            "- Technical validation: Code builds, tests pass, type safety",
            "- Business validation: PRD requirements met",
            "- Hidden tests: Contract verification, import resolution, build integrity"
        ])

    return "\n".join(context_lines) if context_lines else "No predecessor signals available."
```

**Enhanced validation agent error handling** based on research findings:

```python
def _dispatch_validation_agent(self, node_id, target_node_id):
    """Dispatch validation with error handling and configurable timeout from research."""
    timeout = int(os.environ.get("VALIDATION_TIMEOUT", "600"))  # 10min default

    # Check if node already terminal to avoid validation spam
    node_status = self._get_node_status(target_node_id)
    if node_status in ("validated", "accepted", "failed"):
        log.debug("[validation] Skipping dispatch for terminal node %s (status=%s)",
                 target_node_id, node_status)
        return

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            log.error("[validation] %s failed (rc=%d): %s",
                     node_id, result.returncode, result.stderr[:500])
            # Write failure signal so node doesn't hang
            self._write_node_signal(target_node_id, {
                "status": "fail",
                "result": "fail",
                "reason": f"Validation agent crashed: {result.stderr[:200]}",
                "validator_exit_code": result.returncode,
            })

    except subprocess.TimeoutExpired:
        log.error("[validation] %s timed out after %ds", node_id, timeout)
        self._write_node_signal(target_node_id, {
            "status": "fail",
            "result": "fail",
            "reason": f"Validation timed out after {timeout}s",
        })

    except Exception as e:
        log.error("[validation] %s failed with exception: %s", node_id, e)
        self._write_node_signal(target_node_id, {
            "status": "error",
            "result": "fail",
            "reason": f"Validation agent error: {str(e)[:300]}",
            "exception": type(e).__name__,
        })
```

**Files to modify**:
- `pipeline_runner.py`: `_build_worker_prompt()`, add `HANDLER_CONTEXT` dict, add `_inject_predecessor_context()` with validation context, `_dispatch_validation_agent()` with spam prevention

**Acceptance Criteria**:
- AC-1: Each handler type gets a distinct preamble that clearly states what the worker SHOULD and SHOULD NOT do
- AC-2: Predecessor node signals are embedded in the prompt (status, files_changed, message)
- AC-3: "Done criteria" for each handler type is included in the prompt
- AC-4: Validation context and feedback loops are included in validation prompts
- AC-5: Test: research handler prompt does NOT contain "implement" or "write code"
- AC-6: Test: codergen handler prompt does NOT contain "research" or "investigate"
- AC-7: Validation agents implement dual-pass validation (technical + business)
- AC-8: Hidden validation checks are documented and executed
- AC-9: Validation spam is prevented by checking node status before dispatch
- AC-10: Enhanced act-observe-correct loops with predictive validation patterns
- AC-11: Validation feedback design includes specificity, context, guidance, priority and verification path elements
- AC-12: Self-correction capabilities and escalation triggers are properly implemented

---

### 2.8 Epic H: Dead Worker Detection & Signal Timeout (P0 — Critical, NEW)

**Problem proven by research_signal_atomicity crash**: Worker PID 98114 died with JSON buffer overflow. No signal was ever written. Node stayed `active` forever with no process working on it. Runner had no way to detect the dead worker.

**Root cause**: `_dispatch_agent_sdk()` tracks workers in `self.active_workers` dict but never checks if the underlying process is still alive. AgentSDK workers run in ThreadPoolExecutor futures — if the future completes with an exception, the result is silently lost.

**Enhanced patterns from dead_worker_detection_research.md integration**:

Based on the dead_worker_detection_research.md findings, implement a comprehensive dead worker detection system that includes process monitoring, timeout enforcement, and robust signal handling:

```python
from concurrent.futures import ThreadPoolExecutor, Future
import subprocess
import time
import os
import json
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Any, Set
import threading

class WorkerState(Enum):
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

@dataclass
class WorkerInfo:
    node_id: str
    future: Future
    submitted_at: float
    state: WorkerState = WorkerState.SUBMITTED
    result: Optional[Any] = None
    exception: Optional[Exception] = None
    process_handle: Optional[subprocess.Popen] = None

class AdvancedWorkerTracker:
    def __init__(self, default_timeout: int = 900):  # 15 min default
        self.default_timeout = default_timeout
        self.workers: Dict[str, WorkerInfo] = {}
        self.lock = threading.RLock()

    def track_worker(self, node_id: str, future: Future, process_handle: Optional[subprocess.Popen] = None) -> WorkerInfo:
        """Track a new worker future with process handle."""
        with self.lock:
            worker_info = WorkerInfo(
                node_id=node_id,
                future=future,
                submitted_at=time.time(),
                process_handle=process_handle
            )
            self.workers[node_id] = worker_info
            return worker_info

    def update_worker_states(self) -> None:
        """Update states of all tracked workers with comprehensive monitoring."""
        current_time = time.time()
        timeout_threshold = self.default_timeout

        with self.lock:
            for node_id, worker_info in self.workers.items():
                if worker_info.state in [WorkerState.COMPLETED, WorkerState.FAILED, WorkerState.CANCELLED]:
                    continue

                # Check if future is done
                if worker_info.future.done():
                    try:
                        worker_info.result = worker_info.future.result(timeout=0.01)
                        worker_info.state = WorkerState.COMPLETED
                    except Exception as e:
                        worker_info.exception = e
                        worker_info.state = WorkerState.FAILED
                    continue

                # Check for timeout
                elapsed = current_time - worker_info.submitted_at
                if elapsed > timeout_threshold:
                    # Attempt to cancel the future
                    if worker_info.future.cancel():
                        worker_info.state = WorkerState.CANCELLED
                    else:
                        worker_info.state = WorkerState.TIMED_OUT

                    # If there's a process handle, attempt to terminate it
                    if worker_info.process_handle:
                        try:
                            worker_info.process_handle.terminate()
                            worker_info.process_handle.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            worker_info.process_handle.kill()

    def get_dead_workers(self) -> list:
        """Get list of workers that are in failed, timed_out, or cancelled states."""
        with self.lock:
            dead_workers = []
            for node_id, worker_info in self.workers.items():
                if worker_info.state in [WorkerState.FAILED, WorkerState.TIMED_OUT, WorkerState.CANCELLED]:
                    dead_workers.append((node_id, worker_info))
            return dead_workers

    def remove_worker(self, node_id: str) -> bool:
        """Remove a worker from tracking."""
        with self.lock:
            if node_id in self.workers:
                del self.workers[node_id]
                return True
            return False

def _check_worker_liveness(self):
    """Enhanced dead worker detection using comprehensive tracking."""
    # Use the AdvancedWorkerTracker pattern from research
    for node_id, worker_info in list(self.worker_tracker.workers.items()):
        # Check if future completed without writing signal
        if worker_info.future.done() and worker_info.state in [WorkerState.FAILED, WorkerState.COMPLETED]:
            signal_path = os.path.join(self.signal_dir, f"{node_id}.json")
            if not os.path.exists(signal_path):
                exc = worker_info.exception
                if exc:
                    log.error("[liveness] Worker %s died with exception: %s", node_id, exc)
                    self._write_node_signal(node_id, {
                        "status": "error",
                        "result": "fail",
                        "reason": f"Worker process died: {str(exc)[:300]}",
                        "worker_crash": True,
                    })
                else:
                    # Completed without exception but no signal — worker forgot to write
                    elapsed = time.monotonic() - worker_info.submitted_at
                    log.warning("[liveness] Worker %s completed silently after %.0fs", node_id, elapsed)
                    self._write_node_signal(node_id, {
                        "status": "error",
                        "result": "fail",
                        "reason": f"Worker completed without writing signal after {elapsed:.0f}s",
                    })

            # Clean up from tracker
            self.worker_tracker.remove_worker(node_id)

    # Also check for signal timeout using the AdvancedWorkerTracker
    self.worker_tracker.update_worker_states()

    # Process any detected dead workers
    dead_workers = self.worker_tracker.get_dead_workers()
    for node_id, worker_info in dead_workers:
        if worker_info.state in [WorkerState.TIMED_OUT, WorkerState.FAILED]:
            elapsed = time.monotonic() - worker_info.submitted_at
            timeout = int(os.environ.get("WORKER_SIGNAL_TIMEOUT", "900"))

            error_msg = f"Worker "
            if worker_info.state == WorkerState.TIMED_OUT:
                error_msg += f"timed out after {elapsed:.0f}s (limit: {timeout}s)"
            else:
                error_msg += f"failed: {str(worker_info.exception)[:300] if worker_info.exception else 'Unknown error'}"

            self._write_node_signal(node_id, {
                "status": "error",
                "result": "fail",
                "reason": error_msg,
                "worker_crash": True,
                "state": worker_info.state.value
            })

            # Remove from tracking
            self.worker_tracker.remove_worker(node_id)

def _write_node_signal(self, node_id: str, payload: dict) -> str:
    """Atomically write a signal file using the temp file + rename pattern from research."""
    signal_path = os.path.join(self.signal_dir, f"{node_id}.json")

    # Add metadata for ordering and debugging as per research findings
    import datetime
    payload["_seq"] = getattr(self, '_signal_seq', {}).get(node_id, 0) + 1
    self._signal_seq = getattr(self, '_signal_seq', {})
    self._signal_seq[node_id] = payload["_seq"]
    payload["_ts"] = datetime.datetime.utcnow().isoformat() + "Z"
    payload["_pid"] = os.getpid()

    # Create temporary file with unique name
    tmp_path = signal_path.with_suffix(f'.tmp.{os.getpid()}.{int(time.monotonic_ns())}')

    try:
        # Write to temporary file
        with open(tmp_path, 'w') as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()  # Flush to OS buffer
            os.fsync(fh.fileno())  # Force OS to write to disk

        # Atomically rename (POSIX atomic operation)
        os.rename(str(tmp_path), str(signal_path))

        return str(signal_path)

    except Exception as e:
        # Clean up temp file if something went wrong
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass  # Ignore cleanup errors
        raise e
```

**Key dead worker detection patterns from research** (Integrated from dead_worker_detection_research.md):
1. **Process Lifetime Tracking**: Track process dispatch times and monitor their lifetimes
2. **Configurable Timeouts**: Use 10-30 min range with override mechanisms and validation
3. **stderr/stdout Capture**: Listen for and store output for diagnostics
4. **Atomic Failure-Signal Writes**: Use filesystem guarantees for idempotent writes
5. **Background Liveness Thread**: Monitor process lifecycles with dedicated thread
6. **Timeout Window Validation**: Proper validation of timeout values to prevent misconfiguration

Call `_check_worker_liveness()` in every iteration of `_main_loop()` and initialize the `worker_tracker`.

**Files to modify**:
- `pipeline_runner.py`: add `AdvancedWorkerTracker`, `_check_worker_liveness()` with comprehensive monitoring, update `_dispatch_agent_sdk()` to track workers with process handles, enhance `_write_node_signal()` with atomic operations

**Acceptance Criteria**:
- AC-1: Dead worker detection includes process monitoring and comprehensive state tracking
- AC-2: Failure signal written automatically when worker dies without signal
- AC-3: Worker signal timeout configurable via `WORKER_SIGNAL_TIMEOUT` env var (default 900s)
- AC-4: Timed-out workers have their futures and processes cancelled properly
- AC-5: Atomic signal file writes prevent corruption during concurrent access
- AC-6: Test: mock future.exception() → verify fail signal written with comprehensive error details
- AC-7: Test: simulate worker timeout → verify proper cleanup of process and tracking structures
- AC-8: Process lifetime tracking implemented with dispatch timestamps
- AC-9: Configurable timeout ranges validated (10-30 min default range)
- AC-10: stderr/stdout capture mechanism implemented for diagnostics
- AC-11: Atomic failure-signal writes use filesystem guarantees for idempotent operations
- AC-12: Background liveness thread monitors process lifecycles with appropriate resource management
- AC-13: Timeout window validation prevents misconfiguration

---

### 2.9 Epic I: Centralized AGENTS.md & Environment Legibility (P0 — Critical, NEW)

**Problem proven by env_legibility research**: Current discoverability score is **5/10**. Workers must manually search for agent configs. No centralized menu, no competency matrices, no boundary definitions.

**Root cause**: Agent docs exist in `.claude/agents/*.md` but there's no index, no routing guidance, and no cross-agent handoff protocols. Workers arriving at a new codebase have no map.

**Enhanced patterns from environment-legibility-for-ai-agents.md integration**:

Based on the environment-legibility-for-ai-agents.md research, create comprehensive environment legibility documentation that includes all essential files and cross-linking. Create `.claude/agents/AGENTS.md` as a centralized directory with competency matrices:

```markdown
# Agent Directory - Worker Menu

## Specialized Workers

### [Frontend Dev Expert](./agents/frontend-dev-expert.md)
- **Specialization**: Modern web technologies, UI/UX implementation, React/Vue/Angular
- **Best for**: Frontend development, component architecture, responsive design
- **Triggers**: "I need to create a login form", "mobile layout is broken"
- **Competency Matrix**: CAN do: React, Next.js, Tailwind, Zustand. CANNOT do: Python, databases, backend logic.

### [Backend Solutions Engineer](./agents/backend-solutions-engineer.md)
- **Specialization**: Python backend, APIs, databases, PydanticAI agents
- **Best for**: API development, database operations, server-side logic
- **Triggers**: "Create an API endpoint", "PydanticAI agent debugging"
- **Competency Matrix**: CAN do: Python, FastAPI, PydanticAI, SQL, MCP. CANNOT do: Frontend, CSS, React.

### [TDD Test Engineer](./agents/tdd-test-engineer.md)
- **Specialization**: Automated testing, test-driven development, CI/CD
- **Best for**: Writing comprehensive tests, test architecture
- **Triggers**: "Write tests for feature X", "Test coverage improvement"
- **Competency Matrix**: CAN do: Unit/integration/E2E tests, testing frameworks. CANNOT do: Implementation, design.

### [Solution Architect](./agents/solution-architect.md)
- **Specialization**: High-level design, architecture decisions, technical planning
- **Best for**: System design, architectural patterns, technology choices
- **Triggers**: "Design solution for X", "Architectural review needed"
- **Competency Matrix**: CAN do: System design, technical planning, architecture decisions. CANNOT do: Implementation, detailed coding.

## Validation and Quality

### [Validation Test Agent](./agents/validation-test-agent.md)
- **Specialization**: PRD acceptance validation, technical verification
- **Best for**: Verifying implementations meet requirements
- **Triggers**: "Validate implementation", "Run acceptance tests", "Does it work?"
- **Competency Matrix**: CAN do: PRD validation, acceptance testing, verification. CANNOT do: Implementation, design.

## Usage Guidelines

### When to Use Each Agent
- **Investigation**: Use general agents or orchestrators for analysis
- **Implementation**: Delegate to specialized workers based on technology domain
- **Validation**: Always use validation-test-agent before task completion
- **Architecture**: Engage solution architect for significant design decisions

### Interaction Patterns
- Agents are invoked with specific skills and contexts
- Workers focus on implementation while orchestrators coordinate
- Validation happens in layers: unit, integration, end-to-end

## Architecture Documentation Components:
- Component relationships and data flows
- Dependency maps (both internal and external dependencies)
- Service boundaries and integration points
- Technology stack and framework relationships

## Boundary Invariants and Linting Rules
- **Code formatting**: Enforce consistent style for readability by AI agents
- **Import validation**: Prevent circular dependencies and improper layering
- **Naming conventions**: Maintain consistent terminology across the codebase
- **Documentation requirements**: Ensure critical functions/classes have proper documentation
- **Schema Validation**: Ensure configuration files follow predefined schemas

## Cross-Link Integrity
All relative markdown links must resolve to real files. Use relative paths consistently.
Maintain link validity during refactoring. Include alternative pathways for critical navigation.

## Context Provision
Provide sufficient context for AI agents to understand their operating environment.
Include architectural context in all technical decisions. Maintain living documentation.
Use consistent terminology across all documentation.

## Handoff Protocol

When an agent encounters work outside its competency:
1. Document what was found (in signal file message)
2. Set signal status to "needs_handoff"
3. Include target_agent in signal payload
4. Runner will dispatch appropriate agent
```

Create `.claude/agents/ARCHITECTURE.md` — a lightweight codebase map for workers arriving fresh:

```markdown
# Codebase Architecture (for AI Workers)

## Repository Map
- `.claude/scripts/attractor/` — Pipeline runner and worker dispatch
- `.claude/agents/` — Agent configurations (YOU ARE HERE)
- `.claude/skills/` — Skill definitions (invoked via Skill tool)
- `docs/prds/` — Product requirement documents
- `docs/sds/` — Solution design documents
- `acceptance-tests/` — Gherkin acceptance test suites

## Essential Documentation Files:
- **`CLAUDE.md`**: Contains project-specific guidelines, coding standards, architectural decisions, and development workflows that override general best practices
- **`README.md`**: High-level overview of the project, setup instructions, and key entry points
- **`ARCHITECTURE.md`**: System architecture diagrams, component relationships, and technical design overview
- **`TOC.md` or `INDEX.md`**: Table of contents linking to major documentation sections and code areas

## Architecture Documentation Components:
The repository should contain architectural diagrams showing:
- Component relationships and data flows
- Dependency maps (both internal and external dependencies)
- Service boundaries and integration points
- Technology stack and framework relationships
```

Create `.claude/agents/CLAUDE.md` — project-specific guidelines for workers:

```markdown
# Project Guidelines for AI Workers

## Repository Purpose
This is a Claude Code harness setup repository that provides a complete configuration framework for multi-agent AI orchestration using Claude Code. It contains no application code—only configuration, skills, hooks, and orchestration tools.

## Key Patterns

### Investigation vs Implementation Boundary
- **Orchestrators**: Use Read/Grep/Glob to investigate, analyze, plan, and create task structures
- **Workers**: Implement features using Edit/Write
- **Never use Edit/Write directly for implementation in orchestrator mode**

### 4-Phase Orchestration Pattern
1. **Ideation** - Brainstorm, research, parallel-solutioning
2. **Planning** - PRD → Task Master → Beads hierarchy
3. **Execution** - Delegate to workers, monitor progress
4. **Validation** - 3-level testing (Unit + API + E2E)

### Validation Agent Enforcement
All task closures must go through validation-agent with --mode=implementation.

## Environment Variables
- `CLAUDE_SESSION_ID`: Unique session identifier
- `CLAUDE_OUTPUT_STYLE`: Active output style (cobuilder-guardian/orchestrator)
- `CLAUDE_PROJECT_DIR`: Project root directory
- `ANTHROPIC_API_KEY`: API authentication
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`: Enable native Agent Teams (1)
- `CLAUDE_CODE_TASK_LIST_ID`: Shared task list ID for team coordination

## Critical MCP Tools Patterns
Use ToolSearch to discover available tools before using them. MCP tools are deferred and their schemas are not in the agent's context until loaded via ToolSearch.

## Validation & Quality Standards
- Type Safety: Use comprehensive type hints and Pydantic models for all data structures
- Error Handling: Implement proper exception handling with meaningful error messages
- Performance: Profile and optimize critical paths, implement caching where appropriate
- Security: Validate all inputs, sanitize outputs, implement proper authentication
- Documentation: Write clear docstrings, maintain API documentation
```

**Environment Legibility Patterns** (Integrated from environment-legibility-for-ai-agents.md):

The system implements enhanced environment legibility through several key patterns:

1. **Repository-Level Documentation Requirements**:
   - CLAUDE.md: Project-specific guidelines and overrides
   - README.md: High-level overview and entry points
   - ARCHITECTURE.md: System architecture and component relationships
   - TOC.md or INDEX.md: Navigation and cross-references

2. **Agent Documentation Structure**:
   - AGENTS.md as centralized worker discovery menu
   - Competency matrices defining CAN/CANNOT capabilities
   - Boundary conditions for clear role definitions
   - Cross-agent handoff protocols

3. **Environment Variable Conventions**:
   - Required variables with default values clearly documented
   - Token-overhead impact considerations
   - CLAUDECODE variable gotcha prevention

4. **Conventions Section**:
   - Centralized low-level details (environment variables, token overhead)
   - Naming conventions for clarity
   - Documentation standards

5. **Discoverability Mechanisms**:
   - Clear file naming and organization
   - Consistent directory structure
   - Cross-references and links between related documents

**Files to create/modify**:
- `.claude/agents/AGENTS.md` (new) - comprehensive agent directory with competency matrices
- `.claude/agents/ARCHITECTURE.md` (new) - codebase map and essential documentation list
- `.claude/agents/CLAUDE.md` (new) - project-specific guidelines for AI workers
- `.claude/agents/worker-tool-reference.md` (update with model selection guide)
- Update all existing agent documentation files to cross-link with the new AGENTS.md

**Acceptance Criteria**:
- AC-1: AGENTS.md exists with quick selection guide, competency matrix, handoff protocol, and comprehensive documentation guidance
- AC-2: ARCHITECTURE.md exists with repo map, essential documentation list, and architectural components
- AC-3: CLAUDE.md exists with project-specific guidelines for AI workers
- AC-4: worker-tool-reference.md includes model selection guide per handler type
- AC-5: All agent *.md files cross-linked from AGENTS.md and properly cross-referenced
- AC-6: doc-gardener lint passes on all new files with proper frontmatter and cross-links
- AC-7: All essential documentation follows naming conventions and includes proper YAML frontmatter
- AC-8: Environment variable conventions properly documented with default values
- AC-9: Repository-level documentation requirements met (CLAUDE.md, README.md, ARCHITECTURE.md, TOC.md/INDEX.md)
- AC-10: Conventions section created with centralized low-level details
- AC-11: Discoverability mechanisms improve score from 5/10 to 8/10 or higher
- AC-12: Cross-reference integrity maintained across all documentation

---

### 2.10 Epic J: Validation Spam Suppression (P1 — High, NEW)

**Problem discovered during research pipeline**: After `research_feedback_loops` reached `accepted`, the runner dispatched ~6 additional validation signals (mix of pass/fail from lingering agents). Blocked by state machine but noisy.

**Root cause**: `_dispatch_validation_agent()` is called whenever a signal arrives for a node, even if the node is already in a terminal state.

**Proposed**:

```python
def _dispatch_validation_agent(self, node_id, target_node_id):
    # Guard: skip if node already terminal
    node_status = self._get_node_status(target_node_id)
    if node_status in ("validated", "accepted", "failed"):
        log.debug("[validation] Skipping dispatch for terminal node %s (status=%s)",
                 target_node_id, node_status)
        return
    # ... existing dispatch logic
```

**Acceptance Criteria**:
- AC-1: Validation not dispatched for nodes in terminal states
- AC-2: Zero validation signals for already-accepted nodes
- AC-3: Test: accept node → trigger signal → verify no validation dispatch

---

## 3. Implementation Priority & Status (Updated 2026-03-10)

| Priority | Epic | Effort | Impact | Status | Commit / Notes |
|----------|------|--------|--------|--------|----------------|
| **P0** | G: Worker Context & Handler Preambles | 3h | CRITICAL | **DONE** | Pre-session; handler-specific allowed_tools + preambles |
| **P0** | H: Dead Worker Detection | 2h | CRITICAL | **DONE** | `878d0ed` — AdvancedWorkerTracker, _check_worker_liveness, 10 E2E tests |
| **P0** | I: AGENTS.md & Environment Legibility | 2h | CRITICAL | **DONE** (redesigned) | Agent Directory merged into root CLAUDE.md for 100% auto-load. Standalone AGENTS.md removed. |
| **P1** | A: Atomic Signals | 2h | HIGH | **DONE** | `5e826fc` — temp+rename, _seq counter, quarantine, apply-before-consume. 7 E2E tests |
| **P1** | B: force_status Fix | 1h | HIGH | **DONE** | `5e826fc` — _force_status calls _do_transition (disk write), requeue guidance persisted. 4 E2E tests |
| **P1** | C: Validation Error Handling | 2h | HIGH | **DONE** | `5e826fc` — VALIDATION_TIMEOUT env var, crash→fail signal, no silent auto-pass. 4 E2E tests |
| **P1** | J: Validation Spam Suppression | 1h | MEDIUM | **DONE** | `5e826fc` — _get_node_status guard before dispatch. 8 E2E tests |
| **P2** | D: Orphan Resume Expansion | 2h | MEDIUM | **DONE** (via PRD-COBUILDER-CONSOLIDATION-001 E2) | All 4 handler types resumable (codergen, research, refine, acceptance-test-writer). Exponential backoff, max 3 retries. |
| **P2** | E.3: Persistent Requeue Guidance | 1h | MEDIUM | **DONE** (via PRD-COBUILDER-CONSOLIDATION-001 E2) | `bb5b60e`, `05cdb8a` — _load_persisted_guidance reads from signals/guidance/{node}.txt. File is authoritative source, checked before in-memory dict. |
| **P2** | F: Global Safeguards | 3h | LOW | Absorbed into PRD-COBUILDER-CONSOLIDATION-001 E4-E5 | Pipeline timeout, cost tracking, rate limiting |
| **P1** | Liveness Race Fix | 1h | HIGH | **DONE** | `6337153` — _get_node_status() guard in both liveness loops. Prevents spurious signal overwrites. |

**Total estimated effort**: ~19h | **Completed**: ~17h (9 of 10 epics done) | **Remaining**: ~3h (F: Global Safeguards — absorbed into CoBuilder consolidation E4-E5)

**E2E Test Suite**: 33 tests in `tests/e2e/test_pipeline_hardening.py`, all passing in 3.62s. Commit `cda90ed`.

---

## 4. Testing Strategy

### Unit Tests (per epic)
- Epic A: Concurrent signal write stress test (10 threads)
- Epic B: force_status → reload → verify persistence
- Epic C: Mock validation crash → verify fail signal timing
- Epic D: Simulate crash → verify all handler types resume
- Epic E: Prompt generation snapshot tests per handler type
- Epic F: Timeout enforcement test

### Integration Test
- Full pipeline with intentional failures injected at each stage
- Verify recovery from every failure mode

### Regression Guard
- Existing 15+ test files (~8500 LOC) must continue passing
- Add `test_hardening.py` with all new scenarios

---

## 5. Dependencies

- `claude_code_sdk` (existing, unchanged)
- `watchdog` (existing, optional)
- `logfire` (existing, optional — enhanced with cost tracking)
- No new external dependencies

---

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Atomic rename not truly atomic on NFS | Document: pipeline requires local filesystem |
| Exponential backoff delays pipeline | Cap at 60s, configurable via env var |
| Validation timeout too aggressive | Default 600s (10min), configurable |
| Cost tracking adds overhead | Opt-in via env var `PIPELINE_TRACK_COST=1` |

---

## 7. Open Questions (Resolved by Research)

- **Q1**: Should corrupted signals trigger immediate node failure or wait for manual inspection?
  - **RESOLVED**: Quarantine to `signals/quarantine/` + log error. Node retries via normal retry logic. Human can inspect quarantine dir.
- **Q2**: What is the right default for `--max-duration`? 2h may be too short for large initiatives.
  - **RESOLVED**: 2h is fine. Longest observed pipeline in 24h was 85min (AURA-LIVEKIT). Large initiatives run multiple pipelines, not one long one.
- **Q3**: Should we add structured logging (JSON) to complement Logfire spans?
  - **RESOLVED**: No. Logfire already provides structured tracing. Adding JSON logs would duplicate without value.
- **Q4**: Is there value in a `--dry-run` mode that validates the pipeline without dispatching workers?
  - **RESOLVED**: Yes — `cobuilder pipeline validate` already does this for graph structure. Adding `--dry-run` to runner would validate dispatch config without actual execution. Low priority (P2).

## 8. Research Artifacts (Updated with integrated findings)

| Artifact | Location | Status | Integration |
|----------|----------|--------|-------------|
| Feedback & Verification Loops Research | `research_feedback_and_verification_loops.md` (repo root) | Complete | Integrated into Epic G with enhanced validation patterns |
| Environment Legibility Guide | `docs/environment-legibility-for-ai-agents.md` | Complete | Integrated into Epic I with comprehensive documentation patterns |
| Agent Documentation Gap Analysis | `docs/agent-documentation-gap-analysis.md` | Complete | Integrated into Epic I with AGENTS.md creation |
| Worker Context Research | Not produced (worker failed 3/3) | Failed — proves Epic G thesis | Successfully validated need for handler-specific preambles |
| Signal Atomicity Research | Not produced (worker crashed) | Failed — proves Epic H thesis | Successfully validated need for dead worker detection |
| Dead Worker Detection Research | `docs/dead_worker_detection_research.md` | Complete | Integrated into Epic H with comprehensive detection patterns |
| ToolSearch Gap Discovery | Integrated in Section 1.6 | Validated | MCP tool access patterns properly implemented |
| Agent Documentation Patterns | Integrated in Section 2.9 | Validated | Environment legibility patterns properly implemented |

## 9. Open Questions (Resolved by Research)

- **Q1**: Should corrupted signals trigger immediate node failure or wait for manual inspection?
  - **RESOLVED**: Quarantine to `signals/quarantine/` + log error. Node retries via normal retry logic. Human can inspect quarantine dir.
- **Q2**: What is the right default for `--max-duration`? 2h may be too short for large initiatives.
  - **RESOLVED**: 2h is fine. Longest observed pipeline in 24h was 85min (AURA-LIVEKIT). Large initiatives run multiple pipelines, not one long one.
- **Q3**: Should we add structured logging (JSON) to complement Logfire spans?
  - **RESOLVED**: No. Logfire already provides structured tracing. Adding JSON logs would duplicate without value.
- **Q4**: Is there value in a `--dry-run` mode that validates the pipeline without dispatching workers?
  - **RESOLVED**: Yes — `cobuilder pipeline validate` already does this for graph structure. Adding `--dry-run` to runner would validate dispatch config without actual execution. Low priority (P2).

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
