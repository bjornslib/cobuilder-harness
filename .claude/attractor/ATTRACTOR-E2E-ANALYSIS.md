---
title: "Attractor E2E Run Analysis — simple-pipeline.dot"
status: active
type: architecture
grade: reference
last_verified: 2026-03-06
---

# Attractor E2E Run Analysis

**Run**: `e2e-final-test-001` — 2026-03-06 10:17–10:24 AEST
**Model**: `qwen3-coder-plus` (via dashscope, `.env` override)
**Result**: **Pipeline completed successfully** — all 3 nodes validated

| Layer | Trace ID | Turns | Cost |
|-------|----------|-------|------|
| Guardian (LLM agent) | `019cc04ad1dcaafe63033551bb071e9b` | 33+2 | ~$4.91 |
| Runner/Worker (Python→SDK) | `019cc04bd4d254a601136d8f714ab862` | 37 | ~$5.86 |
| **Total** | | **72** | **~$10.77** |

---

## What Worked

### 1. Full guardian → runner → worker chain is functional

For the first time, the complete pipeline ran end-to-end without manual intervention:

```
Guardian: parse → validate → transition(pending→active) → spawn runner
Runner.py (Python): build_worker_system_prompt → build_worker_options → asyncio.run(_run_agent())
Worker (SDK/LLM): 37 turns of implementation → src/api_endpoint.py created
Runner.py: transition(active→impl_complete) on SDK success
Guardian: poll PID → detect exit → read node status → transition(impl_complete→validated)
Guardian: finalize unblocked → transition(pending→active→validated)
Pipeline: COMPLETE — all nodes green
```

### 2. PID polling is clean and reliable

Replacing signal-file waiting with `ps -p <pid>` polling worked correctly. The guardian correctly:
- Parsed `runner_pid` from the spawn JSON
- Polled until exit (2-minute wait, runner took ~4.5 minutes)
- Read node state post-exit with `cli.py status`

### 3. `.env` credential loading worked

`ANTHROPIC_MODEL=qwen3-coder-plus` and `ANTHROPIC_BASE_URL` from `.env` were applied correctly in both guardian and runner layers.

### 4. Automatic node state transitions

Runner.py Python code (not the LLM) performed `cli.py transition impl_task active impl_complete` on SDK success. This is the right separation: the *dispatcher* owns state transitions, not the *worker*.

---

## Issues Found

### Issue 1: Beads MCP triggered interactive permission dialog (CRITICAL)

**Observed**: Worker agent called `mcp__beads_dev_beads__get_tool_info` and `mcp__beads_dev_beads__context`. This surfaced an interactive permission dialog on the host that the user had to dismiss.

**Root cause**: `build_worker_options()` passes no `allowed_tools` restriction and no `mcp_servers` override. The worker inherits the full MCP server list from the session context, including the beads server which is not pre-authorized for headless execution.

**Impact**: 5+ wasted turns attempting beads, then falling back to `TaskCreate`/`TaskUpdate` (which also don't apply here — the worker has no team context).

**Fix**: Either:
- Pass `permission_mode="bypassPermissions"` in `ClaudeCodeOptions` for the worker, or
- Pass an empty `mcp_servers={}` override to strip MCP from the worker's available tools, or
- Add beads to the authorized-tools list in `.claude/settings.json` for headless mode

### Issue 2: Write/Edit tool parameter format failures (MEDIUM)

**Observed**: The worker tried `Write(path=...)` (wrong key) and `Edit(new_string=..., old_string=..., replace_all=False)` (wrong type for `replace_all`). Both failed silently. The worker fell back to `cat > file << 'EOF'` bash heredoc to create `src/api_endpoint.py`.

**Root cause**: The worker (qwen3-coder-plus) has imperfect Claude tool schema knowledge. The `replace_all` parameter should be a boolean `false`, not the string `"False"`.

**Impact**: 6+ turns wasted on retries. Final implementation still worked (bash heredoc is functionally equivalent).

**Fix options**:
- Add explicit tool-usage examples to the worker system prompt
- Or lean into it: bash is fine for file creation in the worker context

### Issue 3: Worker has no real PRD content — only an acceptance string

**Observed**: The runner state JSON shows `"solution_design": null`. The worker's only spec is `acceptance_criteria: "API endpoint returns 200"`. The worker spent 10+ turns searching for `PRD-EXAMPLE-001` files that don't exist.

**Root cause**: The dot node has `prd_ref="PRD-EXAMPLE-001"` as a label, but no `sd_path` attribute pointing to an actual design document.

**Impact**: Worker reasoning was entirely underdetermined. It created a reasonable "hello world" FastAPI endpoint, but in a real pipeline this would produce the wrong artifact.

**Fix**: Add `sd_path` as a dot node attribute pointing to the Solution Design file:
```dot
impl_task [
    handler="codergen"
    bead_id="TASK-1"
    acceptance="API endpoint returns 200"
    sd_path=".taskmaster/docs/SD-AUTH-001.md"   // ADD THIS
]
```
The runner's `build_worker_initial_prompt()` already accepts `solution_design` — wire it through.

### Issue 4: Guardian is an LLM doing deterministic state-machine work (STRUCTURAL)

**Observed**: Guardian spent 33 turns on work that is entirely deterministic:
- Parse dot file (CLI call)
- Find ready nodes (graph traversal)
- Transition to `active` (CLI call)
- Spawn runner (subprocess)
- Poll PID in a while loop
- Read node status (CLI call)
- Transition to `validated` (CLI call)
- Find next ready nodes
- Handle `exit` handler (immediate validate)

None of these steps require language model reasoning. The guardian LLM adds ~$4.91 cost and 33 turns of latency for work a 50-line Python loop would do in milliseconds.

---

## Architecture Recommendation: Python-Programmatic Guardian

### Current 3-layer architecture

```
Guardian (LLM agent, $4.91)
  → Bash tool calls to cli.py
    → Spawns runner.py as subprocess (PID polling)
      → runner.py (Python) calls asyncio.run(_run_agent())
        → Worker (LLM agent, $5.86) — implements the task
```

### Recommended 2-layer architecture

```
pipeline_executor.py (Python state machine, ~$0)
  → Reads dot file (pygraphviz/pydot)
  → Finds ready nodes (topological traversal)
  → For each codergen node: dispatch_worker(node) — direct Python call
    → Builds prompts (already implemented in runner.py)
    → Calls asyncio.run(_run_agent())
    → Transitions node state (cli.py or direct dot edit)
  → Loops until all nodes done or timeout
  → Handles: retries, failed nodes, escalation to terminal

Worker (LLM agent, $5.86) — implements the task
```

The runner.py subprocess + PID polling overhead disappears. The guardian LLM cost (~$4.91) disappears. The only LLM cost is the worker doing actual implementation.

### What the Python state machine replaces (guardian turns 1–33)

| Guardian step | Python equivalent |
|---------------|-------------------|
| `cli.py parse` | `Pipeline.load(dot_path)` |
| `cli.py validate` | `pipeline.validate()` |
| `cli.py status --ready` | `pipeline.ready_nodes()` |
| `cli.py transition → active` | `pipeline.transition(node, "active")` |
| `runner.py --spawn` | `asyncio.run(dispatch_worker(node))` — direct call |
| `ps -p <pid>` polling while loop | `await asyncio.Task` — natural async |
| `cli.py status` post-exit | Check SDK result directly |
| `cli.py transition → validated` | `pipeline.transition(node, "validated")` |
| Loop for finalize | `while pipeline.has_pending()` |

### Migration path

This is a non-breaking refactor:

1. **Phase 1** (quick wins, keep current arch): Fix MCP permissions for headless workers; add `sd_path` to dot nodes; fix `build_worker_initial_prompt` to inline SD content.

2. **Phase 2** (consolidate runner): Move runner.py's `build_worker_*` functions + `_run_agent()` into a `dispatch_worker.py` module. Remove the subprocess+PID dance — call dispatch directly.

3. **Phase 3** (remove guardian LLM): Replace `guardian.py` with `pipeline_executor.py` — a pure Python state machine that calls dispatch. Keep the guardian LLM as an optional "escalation handler" for anomalies only.

4. **Phase 4** (parallel nodes): With async Python, dispatch multiple ready nodes concurrently with `asyncio.gather()`. The current guardian serializes nodes; the Python executor can parallelize.

---

## Cost Model

| Layer | Current | After Phase 3 |
|-------|---------|---------------|
| Guardian/Executor | $4.91 (LLM, 33 turns) | ~$0 (Python) |
| Runner dispatch | subprocess overhead | ~$0 (function call) |
| Worker (per node) | $5.86 (LLM, 37 turns) | $5.86 (unchanged) |
| **Total per node** | **~$10.77** | **~$5.86** |
| **Savings** | | **~46%** |

Worker cost scales with task complexity, not architecture. The $5.86 for "hello world FastAPI" is high because the worker had no PRD spec. With a real SD document, worker turns drop significantly (less exploration, more execution).

---

## Immediate Action Items

Priority order:

1. **Add `sd_path` attribute to dot nodes** — give workers real specs (highest ROI)
2. **Fix MCP permissions in headless SDK workers** — eliminate permission dialogs
3. **Design `pipeline_executor.py`** — Python state machine to replace guardian LLM
4. **Wire `build_worker_initial_prompt(solution_design=...)` from dot attr** — already implemented, just needs the attribute

---

## What the Run Proved

Despite the issues, this run validated several critical architectural invariants:

- **The layering works**: guardian→runner→worker is the right mental model
- **State machine in a dot file works**: node status transitions are clean and auditable
- **SDK direct execution works**: no tmux needed for the worker layer
- **Alternative credentials work**: `.env` override with dashscope + qwen3-coder-plus ran successfully
- **Async coordination works**: PID polling is simpler and more reliable than signal files

The foundation is solid. The evolution to a Python-programmatic executor is a natural next step that preserves the architecture while removing the largest cost and latency overheads.
