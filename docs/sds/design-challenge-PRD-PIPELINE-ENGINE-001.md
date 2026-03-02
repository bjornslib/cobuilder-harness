---
title: "Design Challenge Report: PRD-PIPELINE-ENGINE-001 Pipeline Execution Engine"
status: active
type: reference
last_verified: 2026-02-28
grade: reference
---

# Design Challenge Report: PRD-PIPELINE-ENGINE-001

**Reviewer Role**: Independent design challenger
**Documents Reviewed**: PRD-PIPELINE-ENGINE-001, SD Epic 1 (Core Engine), SD Epic 2 (Validation), SD Epic 3+5 (Conditions + Loop Detection), SD Epic 4 (Event Bus), plus community research and spec analysis
**Date**: 2026-02-28

---

## Executive Summary

The PRD and four SDs represent a well-researched design that draws correctly from community patterns. The overall architecture is sound. However, there are **three critical issues** that could cause implementation failure or require expensive rework: a parallel fan-out merge conflict problem with no resolution strategy, a tmux-based orchestrator with no completion detection contract, and a context.updated event volume that will overwhelm both Logfire and the JSONL file. There are also several high-severity gaps and a meaningful set of medium concerns across the epics.

**VERDICT: AMEND** — Proceed after resolving the three critical issues and eight high-severity items identified below. Do not REDESIGN; the core architecture is correct.

---

## 1. Cross-SD Consistency Check

### 1.1 Outcome Model

The `Outcome` dataclass is defined in SD Epic 1 (`cobuilder/engine/outcome.py`) and referenced in all subsequent SDs. The model itself is consistent: all SDs use `OutcomeStatus.SUCCESS`, `FAILURE`, `PARTIAL_SUCCESS`.

**Inconsistency found**: SD Epic 4 specifies that `Outcome` gains `raw_messages: list[Any]` for token counting (Feature F8, Token Counting Middleware). This is a cross-epic mutation of Epic 1's data model. SD Epic 1 does not document this field, and does not list it as a known extension point. The field is mentioned in SD Epic 4's handoff summary as a "cross-epic dependency" but is not reflected in the Epic 1 `Outcome` contract. If Epic 1 is implemented first (as the sequencing implies), the token counting middleware will have no field to read.

**Recommended fix**: Add `raw_messages: list[Any] = field(default_factory=list)` to the `Outcome` definition in SD Epic 1 as an extension point, documented as "reserved for token counting middleware."

### 1.2 PipelineContext Key Conventions

SD Epic 1 defines `PipelineContext` built-in keys with `$` prefixes: `$last_status`, `$retry_count`, `$node_visits.<node_id>`, `$pipeline_duration_s`.

SD Epic 3 defines the condition expression variable resolution as stripping the `$` prefix before context lookup: `$retry_count` resolves to `context["retry_count"]`. However SD Epic 1's `PipelineContext` stores these keys WITH the `$` prefix. The context stores `$retry_count` but the evaluator looks up `retry_count`.

SD Epic 3 documents the convention table where `retry_count` (without `$`) is the key for condition evaluators, and `$node_visits.<node_id>` is used by the loop detector. These are inconsistent. One half of the system uses `$`-prefixed keys, the other half uses bare names.

This is a correctness bug that will cause all condition expressions using built-in variables to fail silently (returning `None`, failing comparisons) rather than erroring loudly.

**Recommended fix**: SD Epic 3 must be explicit that the evaluator resolves `$variable_name` by looking up `$variable_name` (with the `$`) in the context. Update the convention table in SD Epic 3, Section 3.3 to show keys with `$` prefixes matching the actual storage convention in `PipelineContext`.

### 1.3 Checkpoint Schema

SD Epic 1 defines `EngineCheckpoint` as a Pydantic model. SD Epic 3 states that `loop_detection.py` writes visit counts into the checkpoint. SD Epic 5 states visit counts survive the checkpoint/resume cycle. However, there is no single canonical definition of the `EngineCheckpoint` schema across the four SDs. Each SD assumes the checkpoint contains its data (context, visit counts, completed nodes) without any SD specifying the authoritative field list.

**Inconsistency found**: SD Epic 4 states the JSONL emitter writes to `{run_dir}/pipeline-events.jsonl`. SD Epic 1 says the checkpoint manager creates the run directory. Neither SD specifies whether the run directory path is deterministic (for resume) or timestamp-based (for new runs). If the path is timestamp-based, resume cannot locate the correct JSONL file for appending.

**Recommended fix**: Add a canonical `EngineCheckpoint` schema table to SD Epic 1 that all other SDs can reference. Include `run_dir` as a field in the checkpoint so resume operations can locate related files (JSONL, signals dir).

### 1.4 Event Schema Alignment

SD Epic 4 defines `PipelineEvent.span_id` as injected by `LogfireEmitter`. SD Epic 1 has no mention of span injection. The mechanism by which the active Logfire span ID gets into events emitted by components other than the middleware (e.g., `checkpoint.saved` emitted from `checkpoint.py`) is not specified. There is a gap between "span is open in LogfireMiddleware" and "span_id is available in checkpoint.py."

### 1.5 Handler Interface Signature Mismatch

SD Epic 1 defines the `Handler` protocol as:
```python
async def execute(self, node: Node, context: PipelineContext) -> Outcome
```

SD Epic 4 defines the `Middleware` protocol wrapping handlers via `HandlerRequest`, which carries `node`, `context`, `emitter`, `pipeline_id`, `visit_count`, `attempt_number`, `run_dir`. The middleware chain's `execute` callable matches `HandlerRequest -> Outcome`, not `(Node, PipelineContext) -> Outcome`.

This means the runner cannot call the same handler directly (for the simple case) AND through the middleware chain without an adapter. SD Epic 4's `compose_middleware([], handler)` claim "returns a callable equivalent to calling `handler.execute` directly" is false because the signatures differ. An empty middleware chain still requires `HandlerRequest` wrapping.

**Recommended fix**: Either always use `HandlerRequest` even in the non-middleware path, or define an adapter in `chain.py`. This needs an explicit decision in SD Epic 1.

---

## 2. Architectural Concerns (Ranked by Severity)

### CRITICAL-1: Fan-Out Context Merge Has No Conflict Resolution Strategy

SD Epic 1 defines `PipelineContext.merge_snapshot()` for fan-out/fan-in. The specification says:
> "Only merges keys that were set by the fan-out handler (i.e., keys present in snapshot but not in the pre-fan-out snapshot). Caller is responsible for passing the correct delta."

This is incomplete. When two parallel branches both write to the same context key (e.g., both branches write `status = "success"` or both call `context.update({"test_results": ...})`), the merge strategy is undefined. "Caller is responsible for passing the correct delta" pushes conflict resolution onto the caller without specifying who the caller is or what "correct" means.

In practice, `FanInHandler` must implement merge strategy, but SD Epic 1 does not specify how. The community implementations (attractor-rb, samueljklee) handle this through `join_policy` — `wait_all` merges all outcomes; `first_success` uses only the first successful branch. Neither policy handles key conflicts.

**Risk**: Silent data corruption in context when parallel branches write conflicting values. One branch's results silently overwrite the other's. This will produce incorrect routing at downstream conditional nodes.

**Required amendment**: SD Epic 1 must specify merge conflict policy explicitly. Options: last-writer-wins with warning, namespace by branch (e.g., `branch_0.status`, `branch_1.status`), or fan-in handler receives a list of snapshots and must return explicit context updates. The spec analysis (attractor-rb) shows fan-in handlers producing a merged `Outcome` — adopt this pattern.

### CRITICAL-2: CodergenHandler Has No Completion Detection for tmux Dispatch

SD Epic 1 specifies `CodergenHandler` dispatches to `spawn_orchestrator.py` for `dispatch_strategy=tmux`. The handler "spawns an orchestrator via tmux." However there is no specification of how `CodergenHandler.execute()` knows the orchestrator has finished, succeeded, or failed.

The handler signature is `async def execute(node, context) -> Outcome`. It must eventually return. For `sdk` dispatch, the handler awaits `claude_code_sdk.query()`. For `tmux` dispatch — which is the **default** — there is no await mechanism described anywhere in the four SDs.

The existing `runner_agent.py` uses signal files (`VALIDATION_PASSED`, `NEEDS_REVIEW`) for completion detection. But SD Epic 1 does not specify that `CodergenHandler` should poll for signals, what signal types to watch for, what the timeout is, or what happens if the signal never arrives.

**Risk**: The default dispatch strategy (tmux) produces a handler that either returns immediately (wrong — orchestrator still running) or blocks indefinitely (wrong — no timeout). This is the most commonly-executed handler in the entire engine.

**Required amendment**: SD Epic 1 must specify `CodergenHandler` completion protocol for tmux: which signal types are awaited, polling interval, timeout, and timeout behavior (emit `FAILURE` or `WAITING`). The existing signal protocol (`VALIDATION_PASSED`, `NEEDS_REVIEW`) should be the bridge.

### CRITICAL-3: context.updated Event Volume Will Overwhelm All Backends

SD Epic 4 specifies `context.updated` events are emitted "when keys change" from `context.py` via `emit_on_update`. A long pipeline with 20 nodes, where each node writes 5 context keys, produces 100 `context.updated` events — before counting retries. The PRD acceptance criterion for `CodergenHandler` is that the SDK dispatch propagates raw messages; if token counts update per-token (typical SDK streaming), this could produce thousands of events.

The JSONL backend flushes after every write. Emitting 1000+ events per pipeline run, each flushing, will produce measurable I/O overhead that violates the PRD requirement of `<10ms overhead per node execution`.

The Logfire backend opens and closes spans. Emitting `context.updated` at every key mutation will produce hundreds of child spans, making the Logfire dashboard unreadable.

**Required amendment**: Change `context.updated` to batch: emit once per node lifecycle (after `node.completed`) with a summary of all keys changed during that node's execution, not once per individual key mutation. Alternatively, make `context.updated` opt-in via `EventBusConfig` with a default of disabled. The PRD's acceptance criterion "Events include `span_id` for Logfire correlation" does not require `context.updated` to be per-mutation.

---

## 3. Per-Epic Concerns

### Epic 1: Core Execution Engine

**HIGH-1: WaitHumanHandler Signal Polling Is Blocking**

SD Epic 1 specifies `WaitHumanHandler` "pauses for signal, interruptible." A hexagon node must block the async loop until a human provides a signal file. The design does not specify whether this uses `asyncio.sleep` polling, `inotify`/`watchdog` file events, or a separate thread. If the handler polls using `asyncio.sleep` in the main loop, it will consume one coroutine slot permanently and prevent other async work. If it uses blocking I/O, it will stall the entire event loop.

This matters for fan-out pipelines where one branch is waiting for human approval while other branches could continue executing.

**Amendment**: Specify that `WaitHumanHandler` uses `asyncio.sleep(poll_interval)` with a configurable timeout. Document that this pauses the entire pipeline (acceptable since sequential core) or specify fan-out interaction.

**HIGH-2: ExitHandler Goal Gate Check Creates a Silent Deadlock Risk**

SD Epic 1 specifies the `ExitHandler` checks that all `goal_gate=true` nodes reached `SUCCESS`. If a goal gate node was never visited (unreachable path was taken), the goal gate check fails and falls to `retry_target`. If `retry_target` routes back into the pipeline, the pipeline re-executes from an earlier node. If that earlier node forks, the goal gate node may or may not be visited again. This is a valid retry loop — but there is no specification of how the engine tracks whether a goal gate failure is due to "node reached FAILURE" vs "node was never visited." The retry target is the same in both cases, but the human debugging experience is very different.

**Amendment**: Separate goal gate failure reasons in the exit handler: `GOAL_GATE_FAILED` (node executed and returned FAILURE) vs `GOAL_GATE_UNREACHED` (node was never visited). Emit different signals for each.

**HIGH-3: DOT Parser Attribute Extraction Has No Quoted-Value Handling Spec**

SD Epic 1 specifies a custom recursive-descent DOT parser but does not detail how it handles quoted multi-word attribute values. DOT attributes can be `prompt="Do the work\nwith newlines"` with embedded escape sequences. The parser must handle: single quotes, double quotes, HTML-like labels (`<...>`), backslash escapes, and Graphviz's string concatenation (`"part1" + " part2"`). The spec says the parser extracts 16+ attributes but provides no grammar for DOT string values.

**Amendment**: SD Epic 1 must include a DOT string value grammar or explicitly scope the parser to a subset of DOT syntax (which is fine, but must be documented so pipeline authors know what is forbidden).

**HIGH-4: The ManagerLoopHandler Design Is Absent**

SD Epic 1 names F13 as `ManagerLoopHandler (house)` but provides no specification. The feature map simply lists it alongside other handlers with the note "can be implemented in parallel." The `house` node shape is described as "supervisor over sub-pipeline" — but there is no contract, no acceptance criteria, and no description of what "sub-pipeline" means in this context (a different DOT file? a sub-graph? a recursive call to the engine?).

**Amendment**: Either define `ManagerLoopHandler` with a contract and acceptance criteria, or explicitly defer it to a future epic with a stub that raises `NotImplementedError`. The current state creates an implicit promise that is undeliverable.

**MEDIUM-1: No Timeout on Handler Execution**

SD Epic 1 does not specify a timeout for `handler.execute()`. A stuck `CodergenHandler` (tmux session hanging, SDK call hanging) will block the pipeline forever. The loop detection (Epic 5) detects repeated visits but cannot detect a single node that simply never returns.

**Amendment**: Add `handler_timeout_s` as a graph attribute (default: configurable, e.g., 3600s). Wrap each `handler.execute()` call in `asyncio.wait_for(handler.execute(...), timeout=handler_timeout_s)`. On timeout, emit `node.failed` with `error_type="TIMEOUT"` and treat as FAILURE.

**MEDIUM-2: Checkpoint Atomicity Across Multiple Files**

The design writes atomic JSON checkpoints (write-to-temp-then-rename). However, a pipeline run directory contains multiple files that must be consistent: `checkpoint.json`, `pipeline-events.jsonl`, and per-node artifact directories. If the process crashes after writing the checkpoint but before flushing the JSONL file, the checkpoint says node N is complete but the JSONL file has no `node.completed` event for node N.

This inconsistency is low-stakes for correctness (checkpoint is authoritative) but high-stakes for debugging (JSONL appears to show node N never ran). Add a note that JSONL is advisory, not authoritative, and that replaying events from a resumed pipeline should not be compared against JSONL from a prior run.

### Epic 2: Pre-Execution Validation

**MEDIUM-3: Two Validator Implementations Will Diverge**

SD Epic 2 explicitly acknowledges that `cobuilder/pipeline/validator.py` (11 existing rules) and `cobuilder/engine/validation/validator.py` (13 new rules) are separate. The justification is "structurally distinct purposes." This will cause maintenance burden: when DOT schema changes, both validators need updating. When the 13-rule validator blocks a pipeline, users will wonder why the 11-rule CLI validator accepted the same file.

**Amendment**: In the implementation phase, document a migration path to unify the two validators behind a shared rule runner. Even if the rule sets differ, the rule interface and runner should be shared infrastructure. Alternatively, have the 11-rule validator delegate to the 13-rule validator for the overlapping structural rules.

**MEDIUM-4: ValidationRule Concurrency Not Specified**

SD Epic 2's `Validator.run_all(graph)` runs 13 rules. The PRD acceptance criterion requires `<2 seconds for up to 100 nodes`. For a pipeline with 100 nodes, `AllNodesReachable` (BFS), `EdgeTargetsExist` (O(E)), and `ConditionSyntaxValid` (parse all edge conditions) are all O(N) or O(E). This is fast. However, the SD does not specify whether rules run sequentially or in parallel. With 13 rules on a 100-node graph, sequential is fast enough. But the implementation might naively spawn coroutines and introduce asyncio overhead that exceeds the sequential approach.

**Amendment**: Explicitly specify that validation runs synchronously (no async), with rules in a fixed priority order where error-level rules run first and short-circuit on first error. This is simpler and sufficient.

**LOW-1: ConditionSyntaxValid Rule Must Pre-compile Expressions**

SD Epic 2, Rule 7 (`ConditionSyntaxValid`) checks that edge conditions parse without error using Epic 3's evaluator. However Epic 3's evaluator is a new dependency that is implemented after Epic 2. If Epics are built in order (2 before 3), Rule 7 cannot be implemented without a stub. The SD does not acknowledge this inter-epic dependency.

**Amendment**: Explicitly note that Rule 7 requires the Epic 3 lexer/parser as a dependency. Either Epic 2 is implemented last (after Epic 3), or Rule 7 is a stub `return ValidationResult(passed=True)` until Epic 3 is available.

### Epic 3+5: Conditions and Loop Detection

**HIGH-5: Unquoted String Handling Is Contradictory**

SD Epic 3, Section 4.1 has a contradiction about unquoted strings. The grammar section says: "Bare unquoted identifiers on the right-hand side of a comparison are rejected. The lexer will emit `BARE_WORD` tokens and the parser will emit a `ConditionParseError`." The design note immediately below says: "Exception: The PRD lists `$status = success` (without quotes) as a supported form. The lexer treats unquoted words after an operator as implicit string literals with a deprecation warning."

These are mutually exclusive behaviors. The parser either rejects bare words or accepts them with a warning. You cannot do both. This contradiction will result in inconsistent validation (Rule 7 accepts some pipelines, the runtime rejects the same pipelines, or vice versa).

**Amendment**: Choose one behavior and document it as authoritative. The recommendation is to accept unquoted bare words as implicit string literals (matching community practice) and log a WARNING, with Rule 7 treating deprecation warnings as warnings (not errors). Update the grammar to reflect this.

**HIGH-6: Pattern Detection Subsequence Algorithm Is Not Specified**

SD Epic 5 specifies "detect repeating subsequences of length >= 3" in `execution_history[-20:]`. This is non-trivial algorithmically. The SD provides no specification of the algorithm, its time complexity, or its behavior on edge cases:
- What counts as a "repeating subsequence"? `[A, B, C, A, B, C]` is clearly cyclic. Is `[A, B, A, B, A]` detected?
- Does the algorithm look for exact node ID repetition, or does it consider edge labels too?
- What is the minimum repetition count (2 occurrences? 3?)?

The community implementations (Kilroy, samueljklee) use a simpler heuristic: detect if the same node appears more than N times in the last M executions. The SD proposes a more complex subsequence detection without justification.

**Amendment**: Replace the subsequence detection with the simpler per-node visit counter (already implemented) and a global execution counter (`default_max_retry`). The subsequence detection adds complexity without meaningful benefit over visit counts. If subsequence detection is retained, specify the algorithm (e.g., "Knuth-Morris-Pratt against last 20 nodes, minimum 2 complete repetitions of a sequence of length >= 3").

**MEDIUM-5: $retry_count Is Ambiguous**

SD Epic 3's context convention table shows `retry_count` is written by `runner.py` as "alias for current node's visit count minus 1." But the condition `$retry_count < 3` (used throughout the PRD as an example) will evaluate to `0 < 3` on the first execution (visit count = 1, retry count = 0), which is true. This means any edge with `$retry_count < 3` will be taken on every execution until the third retry, regardless of outcome.

This is probably correct behavior, but it means `$retry_count` and `$node_visits.<node_id>` are not interchangeable (one is 0-indexed, one is 1-indexed). The SD needs to document this distinction explicitly to prevent off-by-one errors in pipeline authorship.

**Amendment**: Add a concrete example table to SD Epic 3 showing: first execution: `$retry_count = 0`, `$node_visits.node_id = 1`; second execution: `$retry_count = 1`, `$node_visits.node_id = 2`; etc.

**MEDIUM-6: Loop Detection Fires Before Edge Selection Creates Incorrect Error Attribution**

SD Epic 5 specifies loop detection runs after `middleware_chain(handler.execute(node, context))` and before `edge_selector`. If the loop detector fires and raises `LoopDetectedError`, the `loop.detected` event is emitted and `ORCHESTRATOR_STUCK` signal is written. However, the node has already executed successfully (the handler returned a valid Outcome). The error is attributed to the node that exceeded the visit limit, but the actual problem is the retry routing that keeps sending the pipeline back to this node.

**Amendment**: The `ORCHESTRATOR_STUCK` signal payload should include the entire recent execution history (last 10 node IDs) so the guardian can diagnose which edge/routing caused the loop, not just which node was visited too many times.

### Epic 4: Event Bus

**MEDIUM-7: LogfireEmitter Holds Stateful Spans Across Async Context Switches**

SD Epic 4's `LogfireEmitter` holds `_pipeline_span` and `_node_spans: dict[str, logfire.Span]` as instance state. For parallel fan-out nodes (F10 in Epic 1), multiple node spans will be open simultaneously. The Logfire Python SDK uses context variables (`contextvars.ContextVar`) for span propagation. When `asyncio.TaskGroup` spawns coroutines for parallel branches, each coroutine gets a copy of the parent context (this is standard asyncio behavior). However, the `LogfireEmitter` instance is shared across all branches. Closing a node span in one branch and then reading `_node_spans` in another branch may produce unexpected behavior if Logfire uses context propagation internally.

**Amendment**: SD Epic 4 should explicitly validate that `logfire.Span` instances are safe to close from a different asyncio task than the one that opened them. If not, the emitter needs a lock around span operations, or each fan-out branch needs its own emitter instance.

**LOW-2: EventBuilder._counter Is a Class Variable Race Condition**

SD Epic 4's `EventBuilder._counter: int = 0` is a class-level variable acting as a monotonic sequence counter. In a synchronous single-process pipeline, this is fine. In a parallel fan-out where multiple asyncio tasks call `EventBuilder._build()` concurrently, the increment (`cls._counter += 1`) is not atomic (Python's GIL provides some protection but `+=` on class variables is not guaranteed atomic across coroutine switches in asyncio).

**Amendment**: Use `itertools.count()` started at construction, or use `threading.Lock` to protect the increment. Alternatively, use `time.time_ns()` as the sequence number (guaranteed unique per event in practice).

**LOW-3: SignalBridge Uses NODE_COMPLETE for Pipeline Completion**

SD Epic 4, Feature F5 documents that `pipeline.completed` writes a signal with `signal_type = "NODE_COMPLETE"` as a "stopgap." This is a semantic mismatch: the guardian receiving `NODE_COMPLETE` expects a node completion, not pipeline completion. The same signal type means different things depending on whether `node_id` is `"__pipeline__"` or a real node. The existing `runner_agent.py` signal handling logic may misinterpret pipeline completion as node completion and trigger incorrect downstream behavior.

**Amendment**: Add `PIPELINE_COMPLETE` to `signal_protocol.py` before Epic 4 implementation. This is the "clean solution" SD Epic 4 mentions but defers. Adding a string constant is a one-line change that prevents a semantic bug.

---

## 4. Community Pattern Gaps

The design research is thorough. However, four patterns from the community implementations were either explicitly deferred or implicitly omitted without sufficient justification:

### Gap A: CSS-like Model Stylesheet (Deferred as "Out of Scope")

The PRD explicitly defers model stylesheet support (Gap 3 in the spec analysis) with the justification: "our 3-level hierarchy handles model selection structurally." This is a reasonable short-term decision, but the community data shows model stylesheets are present in 3 of the 10 most architecturally interesting implementations (samueljklee, F#kYeah, and attractor-rb), and the Attractor spec includes it as a core feature.

The real cost of deferral is that all `box` (codergen) nodes will execute with the same model configuration. The PRD mentions `model_stylesheet` as a parseable attribute (SD Epic 1, F1 attribute list) but there is no handler behavior for it. This means the attribute will be parsed and silently ignored — a confusing experience for pipeline authors who add `model_stylesheet` to their DOT files expecting it to have effect.

**Recommendation**: Either remove `model_stylesheet` from the parser's attribute extraction list (so authors get an error if they use it) or add a stub that logs a `WARNING: model_stylesheet attribute is not yet implemented`. Do not silently ignore a parsed attribute.

### Gap B: Fidelity Preamble for Resume (From samueljklee)

The samueljklee implementation includes a "fidelity preamble" — when resuming from checkpoint, the resumed node's prompt is prepended with a structured summary of prior execution history. This enables the LLM at a resumed node to understand what happened before the crash. The current design checkpoints context (key-value pairs) but does not inject prior execution history into the resumed node's prompt.

**Recommendation**: Consider adding a `fidelity_preamble` to `CodergenHandler` that injects a structured summary of `completed_nodes` into the prompt on resume. This is low-implementation-cost (3-4 lines in the handler) and high-value for LLM quality on resumed runs.

### Gap C: Preflight Health Check Before Execution (From Kilroy)

Kilroy's "preflight probing" validates that LLM providers are reachable before burning tokens. The PRD's validation suite (Epic 2) is entirely structural (graph validation). There is no check that the `spawn_orchestrator.py` script is accessible, that the tmux session manager is running, or that Logfire credentials are valid before the engine starts executing nodes.

**Recommendation**: Add a `preflight_check()` step between validation and execution that tests: spawn_orchestrator.py is executable, tmux is available (for tmux dispatch), Logfire endpoint is reachable (optional, non-fatal). This prevents the common failure mode of a correctly-validated pipeline failing on the first node because of environment misconfiguration.

### Gap D: Per-Node Artifact Directory (From F#kYeah and attractor-rb)

The community consensus checkpoint structure includes a `<node-id>/` subdirectory containing `prompt.md`, `response.md`, `status.json`. SD Epic 1 specifies `EngineCheckpoint` as a single JSON file. There are no per-node artifacts stored. When debugging a failed pipeline, there is no way to see what prompt was sent to an orchestrator or what the raw response was.

The `CodergenHandler` uses `spawn_orchestrator.py` via tmux, so the orchestrator's output is in the tmux session (ephemeral) or in the orchestrator's own logs (not the engine's run directory). This creates a debugging gap: the engine's run directory shows the outcome but not the conversation.

**Recommendation**: `CodergenHandler` should write `{run_dir}/{node_id}/prompt.md` containing the constructed prompt and `{run_dir}/{node_id}/outcome.json` containing the full `Outcome` dataclass. This matches the community standard and costs minimal implementation effort.

---

## 5. Risk Matrix

| Risk | Severity | Likelihood | Epic | Issue ID |
|------|----------|------------|------|----------|
| Fan-out context merge conflict produces silent data corruption | Critical | High | 1 | CRITICAL-1 |
| tmux CodergenHandler never returns (no completion contract) | Critical | Certain | 1 | CRITICAL-2 |
| context.updated volume overwhelms Logfire and JSONL backends | Critical | High | 4 | CRITICAL-3 |
| PipelineContext key convention mismatch breaks all built-in conditions | High | Certain | 1, 3 | Cross-SD-1.2 |
| Handler protocol signature mismatch prevents direct + middleware use | High | High | 1, 4 | Cross-SD-1.5 |
| Unquoted string behavior contradiction causes Rule 7 vs runtime inconsistency | High | High | 2, 3 | HIGH-5 |
| Subsequence pattern detection unspecified — implementer will invent behavior | High | High | 5 | HIGH-6 |
| WaitHumanHandler blocks entire pipeline in non-deterministic way | High | Medium | 1 | HIGH-1 |
| ManagerLoopHandler has no spec — will be skipped or wrong | High | High | 1 | HIGH-4 |
| Two validator implementations diverge over time | Medium | High | 2 | MEDIUM-3 |
| $retry_count vs $node_visits off-by-one causes authoring confusion | Medium | Medium | 3, 5 | MEDIUM-5 |
| Loop detection fires on wrong node, misleading guardian | Medium | Medium | 5 | MEDIUM-6 |
| LogfireEmitter span state unsafe across asyncio task boundaries | Medium | Medium | 4 | MEDIUM-7 |
| EventBuilder counter race condition in fan-out | Low | Low | 4 | LOW-2 |
| PIPELINE_COMPLETE signal type missing | Low | Certain | 4 | LOW-3 |
| model_stylesheet silently ignored despite being parsed | Low | Certain | 1 | Gap-A |
| No preflight check before burning tokens | Low | High | 1 | Gap-C |
| No per-node artifact directory | Low | Medium | 1 | Gap-D |
| Fidelity preamble absent from resume behavior | Low | Low | 1 | Gap-B |

---

## 6. Recommended PRD/SD Amendments

### Required Before Implementation (Blocking)

**AMD-1 [CRITICAL-2]**: Add a `CodergenHandler Completion Protocol` section to SD Epic 1.
Specify: tmux dispatch writes to `{run_dir}/{node_id}/` and polls for one of three signal files (`{node_id}-complete.signal`, `{node_id}-failed.signal`) with configurable timeout (default 3600s). Timeout produces `OutcomeStatus.FAILURE` with `metadata.error_type = "TIMEOUT"`. The orchestrator spawned by `spawn_orchestrator.py` is responsible for writing the completion signal; `CodergenHandler` polls with `asyncio.sleep(5)`.

**AMD-2 [CRITICAL-1]**: Add a `Fan-Out Context Merge Policy` section to SD Epic 1.
Specify that parallel branches receive a read-only snapshot of the context (not a copy they can mutate). Each branch's `Outcome.context_updates` is namespaced by the branch node ID: `{node_id}.{key}`. `FanInHandler` receives a list of `Outcome` objects (one per branch) and produces a single merged `Outcome` that the caller may inspect. The main context is only updated with the merged result, never with individual branch updates directly.

**AMD-3 [CRITICAL-3]**: Revise SD Epic 4's `context.updated` event specification.
Change from per-mutation to per-node: emit one `context.updated` event per completed node containing `keys_added: list[str]` and `keys_modified: list[str]`. Remove the `emit_on_update` callback from `PipelineContext` (avoids coupling context to the event bus). The runner emits `context.updated` after merging `outcome.context_updates`, not inside the context object.

**AMD-4 [Cross-SD-1.2]**: Fix PipelineContext key convention in SD Epic 3.
Update Section 3.3 (Context Store Convention) to show that condition evaluator variable resolution strips the `$` prefix when looking up keys: `$retry_count` → `context.get("$retry_count")`. Add a test case explicitly verifying this behavior.

**AMD-5 [HIGH-5]**: Resolve unquoted string contradiction in SD Epic 3.
Adopt single behavior: accept unquoted bare words as implicit string literals with `log.warning()`. Update grammar BNF to include `bare_word := [a-zA-Z_][a-zA-Z0-9_]*` as a valid value type. Update Rule 7 in SD Epic 2 to emit a warning (not error) for unquoted bare words. Update the three PRD examples that use unquoted strings to note this is deprecated syntax.

**AMD-6 [HIGH-6]**: Simplify loop detection in SD Epic 5.
Remove the "repeating subsequence" pattern detection. Rely solely on: (a) per-node visit counter against `max_retries`, and (b) total execution counter against `default_max_retry`. These two mechanisms already catch all practical infinite loop scenarios. The subsequence detection adds complexity and is not in the canonical spec. If retained, specify the exact algorithm.

**AMD-7 [Cross-SD-1.1]**: Add `raw_messages` to `Outcome` in SD Epic 1.
Add `raw_messages: list[Any] = field(default_factory=list)` to the `Outcome` dataclass with a docstring noting it is populated by `CodergenHandler` for token counting and read by `TokenCountingMiddleware`.

**AMD-8 [Cross-SD-1.5]**: Resolve handler protocol vs middleware signature mismatch.
Define `HandlerRequest` in SD Epic 1 (not Epic 4) as part of the core contract. Specify that `EngineRunner` always wraps handler calls in `HandlerRequest`, even when no middlewares are configured. The runner's internal call is always `middleware_chain(HandlerRequest(...))` never `handler.execute(node, context)` directly.

### Recommended Before Implementation (Non-Blocking But High Value)

**AMD-9 [Gap-A]**: Add stub behavior for `model_stylesheet`.
In `CodergenHandler`, if `node.model_stylesheet` is non-empty, log a `WARNING: model_stylesheet is not yet implemented; using default model configuration` and proceed. Never silently ignore a parsed attribute.

**AMD-10 [HIGH-4]**: Scope `ManagerLoopHandler`.
Add an explicit ManagerLoopHandler specification or formally defer to a future epic with a stub. If deferred, the 13-rule validation suite should warn (not error) when a `house` node is encountered.

**AMD-11 [Gap-C]**: Add `preflight_check()` to SD Epic 1.
After validation and before the execution loop: verify `spawn_orchestrator.py` is executable, `tmux` binary is on PATH, and `attractor-logs/` directory is writable. Fail fast with a clear error rather than failing 30 minutes into a pipeline run.

**AMD-12 [Gap-D]**: Add per-node artifact directory to SD Epic 1.
Specify `{run_dir}/{node_id}/prompt.txt` and `{run_dir}/{node_id}/outcome.json` written by each handler. This matches the community standard and enables post-mortem debugging. `CodergenHandler` writes the constructed prompt before spawning; the outcome is written by the runner after the handler returns.

**AMD-13 [LOW-3]**: Add `PIPELINE_COMPLETE` signal type immediately.
Add the constant to `signal_protocol.py` before Epic 4 implementation. This is a one-line change. Do not ship the stopgap.

---

## 7. Verdict and Implementation Guidance

**VERDICT: AMEND**

The PRD and four SDs describe a coherent, well-researched architecture that correctly borrows from community patterns. The core design choices — sequential traversal, async fan-out via TaskGroup, Protocol-based handlers, atomic JSON checkpoints, middleware chain, pluggable event backends — are all appropriate and well-justified.

The design should NOT be sent to implementation workers in its current state due to the three critical issues. An orchestrator following these SDs will produce code that:
1. Hangs indefinitely waiting for tmux orchestrators to complete (CRITICAL-2)
2. Silently corrupts pipeline context in any fan-out pipeline (CRITICAL-1)
3. Produces thousands of context.updated events per pipeline run (CRITICAL-3)

**Minimum viable amendment sequence**:
1. Author AMD-1 through AMD-8 as SD amendments (estimated: 1-2 hours of writing)
2. Validate AMD-4 (key convention) with a single unit test before any other implementation work
3. Implement AMD-2 (fan-out merge policy) before `FanInHandler` or `ParallelHandler`
4. Implement AMD-1 (CodergenHandler completion protocol) as the first thing in Epic 1 implementation

After amendments, Epic 2 (validation) is the cleanest, best-specified epic and is the recommended starting point for the first implementation worker. Epic 4 (event bus) is the second cleanest. Epic 1 needs the most amendment work before it is implementation-ready.

---

*This report was produced by independent design review. All concerns are actionable. No concern requires redesigning the overall architecture.*
