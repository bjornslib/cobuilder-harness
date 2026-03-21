---
title: "Guardian AgentSDK Dispatch Hardening — Technical Spec"
description: "ClaudeSDKClient migration, custom stop hook, expanded tools, env isolation, research fix"
version: "1.0.0"
last-updated: 2026-03-21
status: active
type: sd
---

# SD-GUARDIAN-DISPATCH-001: Guardian AgentSDK Dispatch Hardening

## Target File

Primary: `cobuilder/engine/guardian.py`
Secondary: `cobuilder/engine/run_research.py`

## Epic 1: Migrate to ClaudeSDKClient

### Current (guardian.py:647-730)
```python
async def _run_agent(initial_prompt: str, options: Any) -> None:
    from claude_code_sdk import query, AssistantMessage, ...
    async for message in query(prompt=initial_prompt, options=options):
        # Log messages
```

### Target
```python
async def _run_agent(initial_prompt: str, options: Any) -> None:
    from claude_code_sdk import ClaudeSDKClient, AssistantMessage, ...
    async with ClaudeSDKClient(options=options) as client:
        await client.connect()
        async for message in client.query(prompt=initial_prompt):
            # Same logging as before — preserve all Logfire spans
```

Reference: `pipeline_runner.py:1544-1546` for the pattern.

## Epic 2: Custom Guardian Stop Hook

### New function: `_create_guardian_stop_hook()`

```python
def _create_guardian_stop_hook(dot_path: str, pipeline_id: str) -> dict:
    """Stop hook that checks pipeline completion instead of promises/hindsight."""
    _block_count = 0
    _MAX_BLOCKS = 3

    async def _check_pipeline(hook_input, event_name, context):
        nonlocal _block_count
        import subprocess
        result = subprocess.run(
            ["python3", "cobuilder/engine/cli.py", "status", dot_path, "--json", "--summary"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json
            status = json.loads(result.stdout)
            summary = status.get("summary", {})
            # Terminal states: validated, accepted, failed
            non_terminal = summary.get("pending", 0) + summary.get("active", 0) + summary.get("impl_complete", 0)
            if non_terminal == 0:
                return {}  # All nodes terminal — allow exit

        _block_count += 1
        if _block_count > _MAX_BLOCKS:
            return {}  # Safety valve
        return {
            "decision": "block",
            "reason": f"Pipeline {pipeline_id} has {non_terminal} non-terminal nodes. "
                      f"Continue driving the pipeline to completion."
        }

    return {"Stop": [{"matcher": {}, "hooks": [_check_pipeline]}]}
```

### Integration in `build_options()`
Pass `hooks=_create_guardian_stop_hook(dot_path, pipeline_id)` to `ClaudeCodeOptions`.

## Epic 3: Expand allowed_tools

### Current (guardian.py:540)
```python
allowed_tools=["Bash"],
```

### Target
Import the tool lists from pipeline_runner.py or define locally:
```python
_GUARDIAN_TOOLS = [
    # Base tools
    "Bash", "Read", "Glob", "Grep", "ToolSearch", "Skill", "LSP",
    # Serena: code navigation for validation inspection
    "mcp__serena__activate_project",
    "mcp__serena__check_onboarding_performed",
    "mcp__serena__find_symbol",
    "mcp__serena__search_for_pattern",
    "mcp__serena__get_symbols_overview",
    "mcp__serena__find_referencing_symbols",
    "mcp__serena__find_file",
    # Hindsight: learning storage
    "mcp__hindsight__retain",
    "mcp__hindsight__recall",
    "mcp__hindsight__reflect",
]
```

Note: Guardian does NOT get Write/Edit/MultiEdit — it's a coordinator, not implementer. Workers handle implementation.

### Add permission_mode
```python
permission_mode="bypassPermissions",
```

## Epic 4: Clean Environment

### Current (guardian.py:548)
```python
env={"CLAUDECODE": ""},
```

### Target (match pipeline_runner.py:1513)
```python
clean_env = {k: v for k, v in os.environ.items()
             if k not in ("CLAUDECODE", "CLAUDE_SESSION_ID", "CLAUDE_OUTPUT_STYLE")}
clean_env["PIPELINE_SIGNAL_DIR"] = str(signals_dir)
clean_env["PROJECT_TARGET_DIR"] = target_dir
```

## Epic 5: Fix run_research.py Async Bug

### Root Cause
`run_research.py` uses `query()` which returns an async generator. The error `Task exception was never retrieved / async_generator_athrow` suggests the generator isn't being properly consumed or cleaned up.

### Fix
Wrap the async iteration in proper try/finally, or switch to `ClaudeSDKClient` pattern:
```python
try:
    async with ClaudeSDKClient(options=options) as client:
        await client.connect()
        async for msg in client.query(prompt=prompt):
            # process
except Exception as e:
    # handle cleanly
```

Need to investigate exact line in `run_research.py` where the generator is created.

## Epic 6: Remove Promise/System3 Assumptions

### Search and remove from `build_system_prompt()`
- Any reference to `cs-verify`, `cs-promise`
- Any instruction to call `mcp__hindsight__retain` at session end
- Any "System 3" references that should say "Guardian" or "Layer 0"

The system prompt should focus exclusively on: parse DOT → validate → dispatch nodes → monitor → handle gates → checkpoint → complete.

## Testing Strategy

1. Unit test: `build_options()` returns correct tools, permissions, hooks
2. Unit test: `_create_guardian_stop_hook()` blocks on non-terminal nodes, allows on all-terminal
3. Integration test: dry-run produces correct system prompt (no promise references)
4. E2E test: re-run `add-two-numbers-lifecycle` — guardian completes in <50 turns
