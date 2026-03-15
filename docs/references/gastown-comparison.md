---
title: "Gastown vs Attractor Pipeline: Architectural Comparison"
status: active
type: reference
last_verified: 2026-03-03
grade: reference
---

# Gastown vs Attractor Pipeline: Architectural Comparison

**Purpose**: Reference document for research validation and informed pipeline design decisions.
**Date**: 2026-03-03
**Author**: Research synthesis (Claude Code, research-first pattern)
**Sources**: Gastown README, docs.gastownhall.ai, Perplexity deep research, DoltHub post-mortem, community analysis

---

## Executive Summary

Gastown (steveyegge/gastown) and our Attractor Pipeline solve the same fundamental problem — how to drive multiple headless AI coding agents at scale without constant human supervision — but they solve it from diametrically opposite starting points. Gastown places a deterministic Go binary as the outer shell: the binary supervises Claude Code, handles process lifecycle, writes hook files, and patrols agent health. Our Attractor pipeline inverts this: headless Claude Code sessions ARE the supervisors; Python scripts and DOT graph files are the plumbing.

A colleague previously reviewed Gastown and concluded: "The inversion is correct — our approach, where the agent IS the supervisor and scripts are the plumbing, is architecturally sound." This analysis confirms that conclusion while identifying specific Gastown patterns that offer genuine learning opportunities.

**Key findings:**

1. Gastown's Go binary and our Python SDK scripts occupy the same structural role (outer supervisor), but the Go binary is deterministic while our Guardian layer is agentic. This is our primary architectural difference and its implications run through every dimension of comparison.

2. Gastown's GUPP (Git Universal Propulsion Principle — work persisted in hook files, agents pull on start) is more elegant than our current signal-file protocol. It warrants adoption.

3. Gastown's Seance (predecessor context recovery via `/resume`) is directly applicable to our Guardian's node-retry logic. Our current retry pattern is stateless; Seance adds state recovery.

4. Gastown's patrol-based supervisor hierarchy (Deacon → Witness → Polecat) maps well onto our Guardian → Runner → Worker model, but Gastown makes the supervisors explicitly named and identity-bearing. Our current implementation does not assign persistent identity to runners.

5. Our DOT graph pipeline is architecturally superior to Gastown's more fluid work-distribution approach for projects that require rigorous execution ordering and typed validation gates. Gastown does not have an equivalent to our `research` → `codergen` → `AT` gate sequence enforced at the graph level.

6. Our file-based signal protocol (`os.rename` for atomicity) is equivalent to Gastown's hook-file IPC but less structured. Gastown formalizes hook files with typed schemas and commit semantics; we use raw JSON with informal conventions.

---

## Architecture Comparison Table

| Dimension | Gastown | Attractor Pipeline | Advantage |
|-----------|---------|-------------------|-----------|
| **Outer supervisor** | Go binary (`gt` CLI) | Python SDK + guardian_agent.py (headless Claude Code) | Gastown (determinism for lifecycle ops) |
| **Agent runtime** | Claude Code (headless + interactive) | Claude Code (headless SDK, subprocess, or tmux) | Tie |
| **Execution model** | Parallel swarm (20-30 polecats simultaneously) | Pipeline DAG (sequential with parallel branches) | Context-dependent |
| **Work definition** | Beads (JSONL + SQLite) assigned by Mayor | DOT graph nodes with typed handlers | Attractor (formal ordering guarantees) |
| **IPC / signaling** | Hook files (JSON) committed to Git, pull-on-start | File-based signals (JSON, atomic `os.rename`) | Gastown (Git semantics = durable + auditable) |
| **Context injection** | Role-specific CLAUDE.md + env vars + hook files | DOT node attributes + Solution Design document | Tie (different foci) |
| **Process supervision** | Three-tier patrol: Deacon → Witness → Polecat | Two-tier: Guardian → Runner (Worker is fire-and-forget) | Gastown (explicit health checks) |
| **Error recovery** | Nudge → Seance (predecessor context) → reassign | Retry with max-retries counter, node re-queued | Gastown (Seance is superior context recovery) |
| **Memory / learning** | None (stateless across projects) | Hindsight MCP (long-term cross-session memory) | Attractor |
| **Merge management** | Refinery agent (autonomous merge queue) | Not implemented (human or manual) | Gastown |
| **Validation gates** | None formal (merge failing tests is documented failure) | AT hexagon nodes (mandatory per codergen) | Attractor |
| **Research nodes** | None (agents use whatever they know) | `research` handler → SD update before codergen | Attractor |
| **Agent identity** | Persistent identity bead per polecat | No persistent runner identity (ephemeral per node) | Gastown |
| **Configuration** | role-specific CLAUDE.md + settings.json per agent | CLAUDE.md harness + output-style per level | Tie |
| **Cost model** | High (many parallel agents, expensive at scale) | Lower (sequential pipeline, controlled concurrency) | Attractor |
| **Visibility** | `gt status` shows beads state; limited cross-project view | DOT node state + Logfire tracing | Attractor (Logfire instrumentation is stronger) |
| **Human escalation** | `wait.human` not formalized; Witness nudges, escalates | `wait.human` node type with gate/mode attributes | Attractor (formal gate is structurally safer) |
| **Reproducibility** | Low (vibe-coded, embraces chaos) | High (DOT schema + validator enforce graph invariants) | Attractor |

---

## Detailed Analysis by Dimension

### 1. Process Supervision Model: Go Binary vs Headless Claude Code

**Gastown:**
The Go binary (`gt`) is the unambiguous process owner. It spawns Claude Code instances as child processes, writes to their worktrees, sends nudge signals, and cleans up terminated sessions. The binary reads from Git-backed Beads to understand what work is in-flight and which agents are assigned. The core insight is that **deterministic code handles process lifecycle while Claude Code handles reasoning**. This is a clean boundary: the Go binary never makes judgment calls; Claude instances never do system-level process management.

The lifecycle sequence:
1. `gt prime` → Go binary starts Mayor Claude Code session with role-specific settings
2. Mayor reasons about work, creates Beads, assigns them to hook files
3. `gt start <polecat-name>` → Go binary creates isolated worktree, writes role settings, sets `GT_ROLE=polecat`, starts Claude Code
4. Polecat reads hook at SessionStart, executes work
5. Polecat calls `gt done` → Go binary removes worktree, records completion in Beads
6. Witness patrols at intervals; nudges stalled polecats; escalates to Deacon

**Attractor Pipeline:**
The Guardian (guardian_agent.py) is itself a headless Claude Code session running via the Python SDK. It uses Bash tools within Claude's reasoning loop to: read the DOT graph, check node statuses, invoke spawn_orchestrator.py for codergen nodes, wait for signal files, and transition node states. The Guardian IS an agent — it can reason about unexpected situations, handle novel pipeline shapes, and adapt to errors in ways a Go binary cannot.

The tradeoff is real: the Guardian's behavior is probabilistic (dependent on model reasoning), whereas the Go binary's behavior is deterministic. If guardian_agent.py interprets a node wrong or misses a signal, the failure mode is opaque. If the Go binary misses a step, it is a reproducible bug.

**Assessment:**
For pipeline-level control (process spawning, signal handling, node state transitions), the Go binary's determinism is valuable. Our current approach works but imposes a reliability ceiling that a deterministic supervisor would not. The colleague's "inversion is correct" observation holds for the agent role hierarchy (agents supervise other agents), but the very bottom layer — raw subprocess management — would benefit from deterministic scripting.

**Recommendation:** Do not change the Guardian's nature as an agentic supervisor. Do consider extracting the signal-wait loop and node-state-transition logic into a deterministic Python state machine that the Guardian calls, rather than implementing it through Claude's reasoning loop.

---

### 2. IPC and Signaling: Git-Committed Hook Files vs Atomic Signal Files

**Gastown:**
All agent-to-agent communication flows through files that are committed to Git. When the Mayor assigns work to a Polecat, it writes a hook file to `.beads/hooks/<polecat-name>/current.json` and commits it. The Polecat's Claude Code `SessionStart` hook reads this file and injects the work into the session context. For nudging, a special marker file is written to the same location.

Key properties of Gastown's IPC:
- **Durability**: Signals survive machine crashes (they are Git-committed)
- **Auditability**: Git history shows exactly what was assigned, when, and by whom
- **Pull semantics**: Workers pull their assignments at session start; no push required
- **Conflict resistance**: JSONL append-only format makes merge conflicts near-impossible

**Attractor Pipeline:**
Signals are written as JSON files to a `signals/` directory using `os.rename` for atomic delivery. The Guardian waits with a polling loop (checking every N seconds). Signal files have a defined schema: `{node_id, status, timestamp, evidence_path}`. Files are not committed to Git by default; they live in the runtime state directory.

Key differences:
- **Atomicity**: `os.rename` is atomic; Gastown's Git commits are also atomic but slower
- **Durability**: Our signals are ephemeral (in-process lifetime); Gastown's survive crashes
- **Semantics**: We use push-style signaling (Runner writes, Guardian reads); Gastown uses pull-style (hook files sit at known locations, agents read at start)
- **Schema**: Ours is informal (validated at read time); Gastown's hook files have role-specific structure enforced by Go binary

**Assessment:**
The most significant gap is durability. If the Guardian crashes mid-pipeline, signals already written are lost because they are not Git-committed. Gastown's signals survive crashes because they are in Git. Our `os.rename` atomicity prevents torn writes, but it does not help with recovery after a Guardian restart.

The pull-semantics model (GUPP) is more elegant than our push model. Rather than the Runner actively signaling the Guardian, GUPP makes the Runner's completion visible in a known location that supervisors check. This decouples the signaling from the supervision loop.

**Recommendation:**
1. Adopt GUPP's pull-semantics: write node completion records to a known path (e.g., `signals/<node_id>/complete.json`) that the Guardian polls, rather than the Runner pushing to the Guardian's inbox.
2. Commit signal files (or a completion log) to Git to gain durability across Guardian restarts.

---

### 3. Context Injection: GUPP/Identity Files vs DOT Node Attributes + SD

**Gastown:**
Context is injected through three layers:
1. **Role-specific CLAUDE.md**: Each role (Mayor, Polecat, Witness) has its own CLAUDE.md at its working directory that defines its role, responsibilities, and behavioral rules.
2. **Environment variables**: `GT_ROLE`, `GT_RIG`, `BD_ACTOR` give agents their identity without consuming context window tokens unnecessarily.
3. **Hook files**: Runtime work assignments injected via SessionStart/UserPromptSubmit hooks.

The separation is important: CLAUDE.md defines the *role* (what kind of agent you are), hook files define the *task* (what you should do right now), and env vars provide *identity* (which specific instance you are). This three-layer injection prevents any single injection point from becoming bloated.

Gastown also uses Seance for context *recovery*: when a new Polecat session starts to resume crashed work, it can use Claude Code's `/resume` capability to temporarily spawn the previous session and interrogate it for context not captured in Beads.

**Attractor Pipeline:**
Context injection is flatter:
1. **DOT node attributes**: `worker_type`, `bead_id`, `solution_design`, `frameworks` are passed to spawn_orchestrator.py and form the prompt context.
2. **Solution Design document**: The SD is the central context document, read by research nodes, updated before codergen nodes execute, and referenced by workers.
3. **Output styles**: Guardian runs with `orchestrator` output style; workers inherit their specialist persona from `subagent_type`.

Our SD-centric model is stronger for projects where a single coherent design document governs implementation. Gastown's hook-file model is stronger for projects where work items are more independent and a central SD would be too broad.

**Assessment:**
The role/task/identity separation in Gastown is cleaner than our current approach. Our workers receive their context in a single prompt blob; Gastown's workers receive role context from CLAUDE.md (loaded at session start), task context from hook files (injected at SessionStart), and identity from env vars (available throughout). This separation means each layer can be updated independently.

Our SD update via `research` nodes is a capability Gastown lacks entirely. Before any codergen node executes, our pipeline verifies current framework docs against the SD and updates it. Gastown agents use whatever knowledge they have at inference time; stale patterns propagate uncorrected.

**Recommendation:**
Adopt the three-layer separation (role / task / identity) for orchestrator and worker injection. Create a distinct `ROLE.md` per agent type (separate from CLAUDE.md harness config) that defines the agent's identity and constraints. Pass task context via hook-file-style injection (at SessionStart, not in the spawn command). Preserve env vars for identity.

---

### 4. Error Recovery: Nudge + Seance vs Retry Counter

**Gastown:**
Error recovery is a three-tier escalation:

**Tier 1 — Nudge**: Witness detects stalled Polecat (no recent Git commits despite assigned work). Writes nudge marker to Polecat's hook location. Polecat wakes up, re-reads hook, continues.

**Tier 2 — Seance**: If a Polecat crashed with incomplete context, the new session uses `/resume` to spawn the previous session, queries it for decisions and reasoning not captured in Beads, then continues with that recovered context.

**Tier 3 — Reassignment**: If a Polecat is repeatedly unresponsive, the Witness escalates to the Deacon, which can reassign the work to a different Polecat or escalate to human (Mayor) attention.

Seance is particularly powerful because it acknowledges that external state (Beads, Git history, code) captures *what* was done but not necessarily *why* specific decisions were made. The predecessor agent holds that reasoning in its session, and Seance can retrieve it.

**Attractor Pipeline:**
Error recovery is simpler and more mechanical:
1. Runner reports failure signal with error details.
2. Guardian increments retry counter for the node.
3. If retries < max_retries, Guardian re-spawns runner.
4. If retries == max_retries, Guardian transitions node to `failed` state.
5. Failed nodes block downstream dependents; human must intervene.

We do not have context recovery. If an orchestrator fails mid-work, the retry spawns a fresh orchestrator with no knowledge of the predecessor's decisions. This is stateless retry.

**Assessment:**
Our retry logic is correct but context-blind. Gastown's Seance pattern addresses a real gap: when an agent fails, valuable reasoning about why it made certain decisions is lost. A fresh retry regenerates that reasoning, which may lead to different (possibly worse) decisions.

For our pipeline, the relevant scenario is: a codergen orchestrator starts implementing a feature, makes 50% of the required changes, encounters an error, and fails. Our retry spawns a fresh orchestrator. The fresh orchestrator reads the SD and the bead, but does not know which implementation choices the predecessor made or why. It may make contradictory choices.

The Seance pattern for us would be: when retrying a codergen node, include `context_recovery: true` in the orchestrator prompt, which triggers the new orchestrator to first inspect the predecessor's git commits, intermediate files, and any notes the predecessor wrote before failing.

**Recommendation:**
1. Add a pre-retry context recovery step: before re-spawning a failed codergen node, collect Git commit messages, any progress notes written to a node-scoped notes file, and error details. Include these in the retry orchestrator's initial prompt.
2. Formalize a `notes/` directory per node where orchestrators can write mid-work observations. These become the Seance-equivalent recovery artifact.

---

### 5. Monitoring: DYFJ Patrol Loops vs Runner PID/Git Monitoring

**Gastown:**
Monitoring follows the supervisor tree pattern (from Erlang):
- **Boot the Dog** watches the Deacon
- **Deacon** patrols all Witnesses every few minutes
- **Witnesses** patrol their Polecats every few minutes
- Polecats are self-reporting only (they call `gt done` when complete)

Patrol checks: Beads status for assigned work, Git history for recent commits from the polecat's worktree, error log files. A polecat is flagged stalled if it has assigned work but no new commits for N minutes.

DYFJ is the nudge signal: a file written to the agent's hook location that Claude Code interprets as an urgent resume-work instruction. DYFJ bypasses normal conversational flow; it is essentially a forced context injection.

**Attractor Pipeline:**
Runner monitoring is more reactive than patrol-based:
- Runner spawns orchestrator (subprocess or tmux), records PID.
- Runner periodically polls: is the process alive? Has it written a completion signal?
- If process dies without signal → failure.
- If timeout exceeded → kill, report timeout failure.
- Guardian monitors Runners by waiting for Runner signal files.

We do not have periodic health checks of the worker from the Guardian level. Once a Runner is spawned, Guardian waits passively for the signal. If the Runner itself crashes without writing a signal, Guardian waits until timeout.

**Assessment:**
Gastown's patrol loops catch a class of failure our system misses: agents that are technically alive (process running) but not making progress. A Claude Code session can be alive, consuming context on irrelevant reasoning, without writing any commits. Our timeout-based monitoring will eventually catch this, but only after the full timeout expires. Gastown's Witnesses detect it within one patrol cycle.

The DYFJ nudge is more targeted than our timeout-and-retry: rather than killing and restarting, it first attempts to wake the stuck agent. This is both less expensive (avoids full restart cost) and more context-preserving (the stuck session retains its context window).

**Recommendation:**
1. Add periodic health checks from Guardian to Runners: poll Git for recent commits from the orchestrator's worktree every N minutes (e.g., 5-minute interval). If no new commits and node is in `active` state, emit a nudge (write to the orchestrator's user-input-queue or send a follow-up message via SDK).
2. Distinguish "stalled" from "failed" in node state model. Stalled nodes get nudge attempts before being marked failed.

---

### 6. Scalability: Swarm Parallelism vs Pipeline DAG

**Gastown:**
Designed for horizontal scaling — 20-30 polecats running simultaneously on independent tasks. The worktree topology isolates each polecat completely; the Refinery handles merge queue management. Scalability is limited by:
- Token cost (dozens of agents running in parallel burns $100s/hour without cost optimization)
- Human capacity to specify enough work items to keep the swarm fed
- Merge queue throughput (Refinery is a single agent managing potentially hundreds of pending merges)

Yegge's reported observation: "Gas Town churns through implementation plans so quickly that you have to do a LOT of design and planning to keep the engine fed." This is the design bottleneck at scale.

Gastown also notes diminishing returns beyond a certain number of parallel agents, and potential negative returns if agents produce more conflicting work than the Refinery can manage.

**Attractor Pipeline:**
Designed for depth-first pipeline execution with controlled parallelism at the `parallel` node type. Our primary scaling axis is pipeline complexity (number of nodes), not agent concurrency. Key constraints:
- Guardian is the single pipeline driver; it cannot itself be parallelized across pipelines without a higher-level System 3 orchestrator.
- Node dependencies in the DOT graph enforce sequential ordering where required.
- Parallel branches are an explicit graph construct, not an emergent property.

Our approach is more suitable when correctness ordering matters (research must complete before codergen; AT validation must pass before declaring complete). Gastown's approach is more suitable when tasks are genuinely independent and speed matters more than ordering.

**Assessment:**
These are complementary models, not competing ones. For feature work with clear dependencies (research → design → implement → test → validate), our pipeline DAG is the right model. For parallel execution of independent tasks (implement 15 UI components simultaneously), Gastown's swarm model is right. The Attractor pipeline could adopt a swarm-like `parallel` node that spawns N codergen nodes simultaneously, using the Refinery pattern for integration.

**Recommendation:**
When the `parallel` node type spawns multiple codergen workers simultaneously, add a merge integration step (equivalent to Gastown's Refinery) that reconciles concurrent changes before downstream AT validation. This is currently unimplemented.

---

### 7. Memory and Learning: Gastown's Seance vs Hindsight MCP

**Gastown:**
Memory is per-project and primarily Git-based. Beads store work history, identity beads store agent history, and Git tracks all changes. There is no cross-project memory — knowledge gained in one Gas Town workspace does not transfer to another. Seance provides intra-session context recovery (recovering context from a crashed predecessor) but not cross-session learning.

Gastown explicitly embraces statelessness between projects. Each engagement starts fresh. There is no equivalent to Claude's project memory, persistent notes, or cross-project pattern learning.

**Attractor Pipeline:**
Hindsight MCP provides persistent long-term memory across sessions and projects. Key capabilities:
- Store and retrieve decisions, patterns, and outcomes
- Cross-project search (a pattern learned in project A is retrievable in project B)
- Session-scoped banks for isolation where needed
- Reflection (synthesizing stored memories into answers about design tradeoffs)

Logfire integration gives us observable tracing across the full pipeline execution, including research node outputs, SD update diffs, runner outcomes, and signal timelines. This is a significant observability advantage.

**Assessment:**
Hindsight + Logfire represent a genuine architectural advantage over Gastown. We accumulate knowledge across pipelines; Gastown does not. When we research a framework in one pipeline, Hindsight can surface those findings in a future pipeline. When a node pattern fails repeatedly, Logfire traces allow us to diagnose the failure mode across multiple pipeline runs.

**Recommendation:** Preserve and deepen Hindsight integration. Consider having the Guardian store key pipeline execution facts in Hindsight at completion (e.g., which research findings led to SD updates, which node types caused most retries, which worker types were most reliable). This creates a learning loop across pipelines.

---

### 8. Configuration: Gastown's Role-Specific Settings vs .claude/ Harness

**Gastown:**
Configuration is deeply role-aware:
- Each agent role gets its own `settings.json` at its working directory (isolated from source repo settings)
- Sparse checkout excludes Gas Town config files from the source repo view (prevents contamination)
- Protection matrix enforced via hook guards (only polecats can write/commit; Mayors/Witnesses are read-only)
- `gt doctor` diagnoses and auto-repairs misconfigurations

The Go binary manages settings isolation actively — it writes the correct `settings.json` for each role when spawning an agent.

**Attractor Pipeline:**
Configuration lives in the `.claude/` harness directory:
- `settings.json` configures hooks system-wide
- `output-styles/` defines behavior for orchestrator and System 3 levels
- `agents/` defines specialist agent configurations
- Workers inherit settings from the worktree they are launched in

Our configuration is less role-isolated. If a worker's working directory traverses up and finds the harness settings, there can be unexpected behavior. We do not have a `gt doctor` equivalent for detecting configuration drift.

**Assessment:**
Gastown's protection matrix (only workers can edit files, supervisors are read-only) is a safety property we should formalize. Currently our orchestrators are prevented from editing files by convention (the CLAUDE.md rules) rather than by enforced hook guards. If an orchestrator violates the rule, no system-level enforcement catches it.

**Recommendation:**
1. Implement hook guards for orchestrator sessions that detect and block Edit/Write tool calls (similar to Gastown's protection matrix).
2. Add a `harness-doctor` command that verifies worktree settings isolation, hook configurations, and env var correctness before pipeline launch.

---

## Patterns to Consider Adopting from Gastown

### Priority 1: GUPP — Pull Semantics for Work Assignment

**What**: Instead of the Runner pushing signals to the Guardian, write node-state records to known, stable paths. The Guardian polls these paths. Workers pull their assignments from known paths at SessionStart.

**Why**: Durability (survives crashes), decoupling (supervisor and worker are not in a request-response relationship), and natural idempotency (reading from a known path multiple times is harmless).

**Implementation sketch**:
```
signals/<node_id>/assigned.json   ← written by Guardian when node goes active
signals/<node_id>/complete.json   ← written by Runner when node finishes
signals/<node_id>/notes.json      ← written by Worker for context recovery
```

Commit these to Git for durability. Guardian polls `signals/<node_id>/` directory.

---

### Priority 2: Seance — Context Recovery on Retry

**What**: When retrying a failed codergen node, collect context from the predecessor's execution before spawning the fresh orchestrator.

**Why**: Stateless retry loses reasoning context. The retry orchestrator must rediscover decisions the predecessor already made, potentially making contradictory choices.

**Implementation sketch**:
```python
# In Guardian retry logic:
if node.retry_count > 0:
    predecessor_context = collect_predecessor_context(
        node_id=node.id,
        git_commits=get_commits_since(node.start_time, worktree=node.worktree),
        notes=read_if_exists(f"signals/{node.id}/notes.json"),
        error=node.last_error,
    )
    orchestrator_prompt = f"{base_prompt}\n\n## Predecessor Context\n{predecessor_context}"
```

---

### Priority 3: DYFJ Nudge Before Kill

**What**: When a runner appears stalled, send a nudge signal before escalating to kill-and-retry.

**Why**: Nuding is cheaper than full restart, more context-preserving, and handles the common case of a briefly-stuck-but-recoverable agent.

**Implementation sketch**: Write to the orchestrator's user-input-queue (or send via SDK if using SDK mode) with a message like "You appear to have stalled. Check your current node state and continue from where you left off." Wait one patrol cycle before escalating to kill.

---

### Priority 4: Persistent Runner Identity

**What**: Assign persistent identity to runners (not just orchestrators). Record which runner executed which node and what its outcome was.

**Why**: Currently our Runners are anonymous processes. Gastown's identity-bead-per-polecat pattern creates an auditable record of which agent did what, enabling better failure attribution and recovery.

**Implementation sketch**: Store a runner identity record in Beads (using the existing beads MCP) when a runner starts. Include: node_id, pipeline_id, start_time, model, worker_type. Update with completion status.

---

### Priority 5: Protection Matrix Hook Guards

**What**: Enforce via hooks that orchestrators cannot use Edit/Write tools; only workers can.

**Why**: Currently this is a convention enforced by CLAUDE.md rules. Gastown enforces it via `PreToolUse` hooks. Convention-based enforcement is fragile; hook-based enforcement is structural.

**Implementation sketch**:
```json
// .claude/settings.json — add to hooks
{
  "PreToolUse": [
    {
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [
        {"type": "command", "command": ".claude/hooks/guard-orchestrator-writes.sh"}
      ]
    }
  ]
}
```

---

## Where Our Architecture Is Stronger

### 1. Formal Pipeline Validation

The DOT graph schema (validator.py) enforces structural correctness before any agent executes. Gastown has no equivalent — work distribution is emergent from Mayor reasoning and Beads assignment. Our schema ensures:
- Every codergen node has at least one AT (acceptance test) hexagon downstream
- No unguarded cycles
- Research nodes reference valid upstream evidence paths
- Required attributes are present per handler type

This means pipeline misconfiguration is caught at parse time, not at runtime after an agent has already burned tokens on an invalid task.

### 2. Research Nodes — Docs Validation Before Execution

Our `research` handler nodes (run_research.py) validate current framework documentation against the Solution Design before any codergen node executes. Gastown agents use knowledge from training time; stale API patterns propagate uncorrected. Our research nodes:
- Call Context7 to retrieve current library documentation
- Call Perplexity to cross-validate against 2026 sources
- Update the SD document directly with corrections
- Write evidence to a timestamped file for audit

This is a significant correctness advantage for any pipeline targeting frameworks with rapid API evolution.

### 3. Hindsight MCP — Cross-Session Learning

As described above, Hindsight provides genuine cross-project memory. Gastown's knowledge is session-scoped and project-scoped. Ours accumulates.

### 4. Logfire Tracing — Deep Observability

Gastown's observability is primarily through Beads status and Git history — sufficient for understanding what happened, but not for diagnosing *why* something took longer than expected or where exactly a failure occurred. Our Logfire integration traces:
- Each guardian loop iteration
- Signal wait durations
- Runner spawn and completion events
- SD update diffs from research nodes
- Model and token usage per node

This enables post-hoc analysis of pipeline performance that Gastown does not support.

### 5. Typed Validation Gates (AT Hexagon Nodes)

Every codergen node in our pipeline must have a downstream AT hexagon that runs formal acceptance tests. This is enforced by the validator as a schema rule. Gastown famously had an incident where agents auto-merged code with failing tests to main — precisely the failure mode our AT gate prevents. Our pipeline structurally cannot mark a codergen node `validated` without a passing AT gate upstream.

### 6. Explicit Human Escalation Gates

Our `wait.human` node type formalizes human-in-the-loop checkpoints with typed `gate` and `mode` attributes. The pipeline pauses at this node and waits for explicit human approval before continuing. Gastown's human escalation path is more ad-hoc: the Mayor can ask for input, but there is no formal gate node that blocks the pipeline.

---

## Patterns We Should NOT Adopt

### 1. Gastown's "Embrace Chaos" Philosophy

Gastown explicitly embraces losing some work, auto-merging with failing tests, and prioritizing velocity over correctness. For development tooling in environments where pipeline output feeds production, this is not acceptable. Our AT gate pattern is explicitly designed to prevent the class of errors Gastown encountered at DoltHub.

### 2. Gastown's Refinery Autonomous Merge

The Refinery (autonomous merge queue manager) can "creatively re-imagine implementations" if merge conflicts are intractable. This is a high-risk behavior for production use. Without a human in the loop for merge decisions, the Refinery can introduce subtle correctness regressions that are hard to detect. Our `wait.human` node at integration points is safer.

### 3. Removing the DOT Graph for Fluid Work Distribution

Gastown's Mayor decomposes work dynamically at runtime. This is flexible but not auditable. Our DOT graph provides a pre-defined, validator-checked execution plan that is immutable during execution. This supports reproducibility, enables pre-run estimation of pipeline cost, and makes it possible to pause and resume pipelines predictably.

---

## Recommendation Section

### Tier 1: Adopt Now (High Value, Low Risk)

1. **GUPP Pull Semantics**: Refactor signal protocol to use stable-path completion records that the Guardian polls, rather than Runner-pushed signals. Commit completion records to Git.

2. **Context Recovery on Retry**: Add predecessor context collection to Guardian retry logic. Read Git commits, notes files, and error details before spawning retry orchestrator.

3. **Three-Layer Context Injection**: Separate role definition (ROLE.md per agent type), task assignment (injected at SessionStart from hook file), and identity (env vars). Reduce reliance on bloated initial prompts.

### Tier 2: Evaluate Further

4. **Patrol-Based Health Checks**: Add periodic Git commit monitoring for active codergen nodes. Flag stalled nodes (active but no commits in N minutes) before timeout fires.

5. **DYFJ Nudge**: Implement nudge-before-kill for stalled nodes. Requires defining what a "nudge" looks like in SDK mode vs tmux mode.

6. **Persistent Runner Identity**: Log runner executions to Beads for audit trail. Useful for debugging repeated node failures.

### Tier 3: Architectural Consideration (Longer Term)

7. **Refinery Pattern for Parallel Branches**: When the `parallel` node type spawns concurrent codergen workers, add a merge integration step before downstream AT validation.

8. **Protection Matrix Enforcement**: Implement hook guards that structurally prevent orchestrators from using Edit/Write tools. Currently convention-only.

9. **Harness Doctor Command**: Build a diagnostic command equivalent to `gt doctor` that validates harness configuration, worktree isolation, and env vars before pipeline launch.

---

## References

### Gastown Primary Sources

- Gastown GitHub Repository: https://github.com/steveyegge/gastown
- Gastown Documentation: https://docs.gastownhall.ai/reference/
- Gastown Glossary: https://github.com/steveyegge/gastown/blob/main/docs/glossary.md
- Steve Yegge's Blog Post (January 1, 2026): Reported via Maggie Appleton summary at https://maggieappleton.com/gastown
- DoltHub Post-Mortem: https://www.dolthub.com/blog/2026-01-15-a-day-in-gas-town/

### Community Analysis

- Justin Abrahms: https://justin.abrah.ms/blog/2026-01-05-wrapping-my-head-around-gas-town.html
- Steve Klabnik: https://steveklabnik.com/writing/how-to-think-about-gas-town/
- Simon Hartcher (10,000 hours of Claude Code): https://simonhartcher.com/posts/2026-01-19-my-thoughts-on-gas-town-after-10000-hours-of-claude-code
- Paddo.dev (two kinds of multi-agent): https://paddo.dev/blog/gastown-two-kinds-of-multi-agent/
- Goosetown (Block/Goose alternative): https://block.github.io/goose/blog/2026/02/19/gastown-explained-goosetown/
- HN Discussion (first): https://news.ycombinator.com/item?id=46458936
- HN Discussion (second): https://news.ycombinator.com/item?id=46902368
- Trilogy AI Workflows: https://trilogyai.substack.com/p/how-to-gastown-workflows-and-60-second
- Nate's Newsletter (dumb agents): https://natesnewsletter.substack.com/p/why-dumb-agents-mean-smart-orchestration

### Our Architecture Sources

- `.claude/scripts/attractor/guardian_agent.py` — Guardian (Layer 1)
- `.claude/scripts/attractor/spawn_orchestrator.py` — Orchestrator spawner
- `.claude/scripts/attractor/run_research.py` — Research node agent
- `.claude/scripts/attractor/validator.py` — DOT schema validator
- `.claude/skills/cobuilder-guardian/SKILL.md` — CoBuilder Guardian skill (v0.4.0)
- `CLAUDE.md` — Harness configuration and orchestration rules

### Prior Analysis Referenced

A colleague previously analyzed Gastown independently and concluded: "The inversion is correct — our approach, where the agent IS the supervisor and scripts are the plumbing, is architecturally sound." This document confirms that conclusion while extending the analysis to specific pattern-level learning opportunities. The colleague's observation about Gastown's Go binary enabling deterministic process lifecycle management is incorporated in the Process Supervision analysis above (Section 1) and the Tier 1 recommendation to extract deterministic state-transition logic from the agentic Guardian loop.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
