---
title: "Guardian AgentSDK Dispatch Hardening"
description: "Fix guardian.py dispatch to use ClaudeSDKClient with proper hooks, tools, and permissions"
version: "1.0.0"
last-updated: 2026-03-21
status: active
type: prd
prd_id: PRD-GUARDIAN-DISPATCH-001
---

# PRD-GUARDIAN-DISPATCH-001: Guardian AgentSDK Dispatch Hardening

## Problem Statement

The guardian agent (`guardian.py`) successfully drives pipelines via AgentSDK, but wastes 23% of its turn budget (22/97 turns) on stop hook compliance and encounters permission errors because its dispatch configuration is under-specified compared to worker agents.

### Evidence (from Logfire trace of `add-two-numbers-lifecycle` pipeline)

| Issue | Turns Wasted | Root Cause |
|-------|-------------|------------|
| Stop hook retry loop | 22 turns (77-99) | No custom `hooks=` parameter — inherits harness unified-stop-gate.sh |
| MCP permission error | 1 turn (97) | `allowed_tools=["Bash"]` and no `permission_mode` set |
| Unnecessary promise verification | 2 turns (78, 95) | Stop hook demands `cs-verify` which is Guardian-level, not worker-level |
| Research async bug | 4 turns (15, 22, 25, 27) | `run_research.py` asyncio `async_generator_athrow` error |

### Comparison: Guardian vs Worker Dispatch

| Config | Guardian (current) | Workers (pipeline_runner) |
|--------|-------------------|---------------------------|
| SDK method | `query()` (unidirectional) | `ClaudeSDKClient` (bidirectional) |
| `allowed_tools` | `["Bash"]` | 20+ tools (Bash, Read, Write, Edit, Serena, Hindsight, etc.) |
| `permission_mode` | Not set (interactive default) | `bypassPermissions` |
| `hooks` | Not set (inherits harness hooks) | Custom `_create_signal_stop_hook()` |
| `env` | `{"CLAUDECODE": ""}` | Clean env without CLAUDECODE, SESSION_ID, OUTPUT_STYLE |
| Stop hook behavior | Demands promises, hindsight, acceptance tests | Checks signal file only |

## User Stories

1. **As the CoBuilder Guardian**, I want the guardian.py AgentSDK agent to complete pipelines without wasting turns on irrelevant stop hook demands, so pipeline execution is efficient and predictable.

2. **As a developer**, I want the guardian agent to have access to the same tools as workers (Serena, Hindsight, etc.) so it can inspect code, store learnings, and navigate the codebase during validation.

3. **As the pipeline system**, I want the guardian agent to exit cleanly when the pipeline reaches terminal state (all nodes validated/accepted/failed), not when an external stop hook is satisfied.

## Requirements

### Epic 1: Migrate to ClaudeSDKClient (Bidirectional Protocol)

Replace `query()` with `ClaudeSDKClient` in `_run_agent()`. This enables:
- Stop hooks via the bidirectional control protocol
- Future: injecting user messages mid-stream
- Parity with worker dispatch pattern

**Acceptance Criteria:**
- AC-1.1: `_run_agent()` uses `ClaudeSDKClient.connect()` + `query()` pattern
- AC-1.2: All existing Logfire instrumentation preserved (tool_use, assistant_text, thinking, tool_result spans)
- AC-1.3: Guardian dry-run still works (`guardian.py --dry-run`)

### Epic 2: Custom Guardian Stop Hook

Create a guardian-specific stop hook that checks pipeline completion state instead of promises/hindsight/acceptance tests.

**Acceptance Criteria:**
- AC-2.1: New function `_create_guardian_stop_hook(dot_path, pipeline_id)` exists
- AC-2.2: Stop hook checks: all non-start/exit nodes are in terminal state (validated/accepted/failed)
- AC-2.3: Stop hook allows exit when pipeline is complete
- AC-2.4: Stop hook blocks exit (with corrective message) when pipeline has active/pending nodes
- AC-2.5: Stop hook has max_blocks=3 safety valve (prevent infinite loops)
- AC-2.6: `build_options()` passes `hooks=_create_guardian_stop_hook(...)` to override harness hooks

### Epic 3: Expand allowed_tools for Guardian

Give the guardian the same base toolset as workers, plus Hindsight for learning storage.

**Acceptance Criteria:**
- AC-3.1: `allowed_tools` includes at minimum: `Bash`, `Read`, `Glob`, `Grep`, `ToolSearch`, `Skill`, `LSP`
- AC-3.2: `allowed_tools` includes Hindsight tools: `mcp__hindsight__retain`, `mcp__hindsight__recall`, `mcp__hindsight__reflect`
- AC-3.3: `allowed_tools` includes Serena tools for code inspection during validation
- AC-3.4: `permission_mode="bypassPermissions"` set in `build_options()`
- AC-3.5: Guardian can call `mcp__hindsight__retain` without permission errors

### Epic 4: Clean Environment Isolation

Match worker environment isolation to prevent nested session conflicts.

**Acceptance Criteria:**
- AC-4.1: Environment strips `CLAUDECODE`, `CLAUDE_SESSION_ID`, `CLAUDE_OUTPUT_STYLE`
- AC-4.2: `PIPELINE_SIGNAL_DIR` set in environment
- AC-4.3: `PROJECT_TARGET_DIR` set in environment

### Epic 5: Fix run_research.py Async Bug

Fix the `async_generator_athrow` error that crashes research node execution.

**Acceptance Criteria:**
- AC-5.1: `run_research.py` completes without `Task exception was never retrieved` error
- AC-5.2: Research node passes in the lifecycle pipeline test
- AC-5.3: Existing research tests still pass

### Epic 6: Remove Promise/System3 Assumptions from Guardian Prompt

The guardian system prompt should not reference promise verification or System 3 patterns. These are Guardian-level (my) concerns.

**Acceptance Criteria:**
- AC-6.1: System prompt does not contain `cs-verify`, `cs-promise`, or promise-related instructions
- AC-6.2: System prompt does not tell the guardian to call `mcp__hindsight__retain` at exit (that's the stop hook's job or the Guardian's job, not the agent's)
- AC-6.3: System prompt focuses purely on pipeline execution: parse, validate, dispatch, monitor, gate-handle, checkpoint

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| E1: ClaudeSDKClient migration | Remaining | - | - |
| E2: Custom stop hook | Remaining | - | - |
| E3: Expand allowed_tools | Remaining | - | - |
| E4: Clean environment | Remaining | - | - |
| E5: Fix run_research.py | Remaining | - | - |
| E6: Remove promise assumptions | Remaining | - | - |

## Key Files

| File | Role |
|------|------|
| `cobuilder/engine/guardian.py` | Main file — `build_options()`, `_run_agent()`, `build_system_prompt()` |
| `cobuilder/engine/pipeline_runner.py` | Reference — `_create_signal_stop_hook()`, `_get_allowed_tools()`, `_dispatch_via_sdk()` |
| `cobuilder/engine/run_research.py` | Research node — asyncio bug |

## Verification Plan

Re-run the `add-two-numbers-lifecycle` pipeline after fixes. Success criteria:
- Guardian completes in <50 turns (was 97)
- No stop hook retry loops
- No permission errors
- Research node passes without manual recovery
- All Logfire spans preserved
