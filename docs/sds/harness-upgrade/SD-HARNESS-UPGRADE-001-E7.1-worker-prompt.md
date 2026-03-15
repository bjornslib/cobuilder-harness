---
title: "SD-HARNESS-UPGRADE-001 Epic 7.1: Worker Prompt Restructuring"
status: archived
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001 Epic 7.1: Worker Prompt Restructuring

## 1. Problem Statement

Workers receive a 21K character system prompt containing pipeline orchestration docs, signal protocol instructions, merge queue guidance, and tool examples — none of which are relevant to a focused implementation worker. The actual task (acceptance criteria, file scope) is buried in a 697 char initial prompt.

**Evidence**: Logfire traces `019cc53082f3f45d35ae3b147d59d76e` through `019cc537ab8c263d2a1362b8ae08e1d4` — a worker spent 14 of 19 turns on investigation before implementing, then modified a file (`spawn_orchestrator.py`) that its acceptance criteria explicitly excluded. Root cause: task dilution from irrelevant system prompt content.

## 2. Design

### 2.1 Slimmed System Prompt (~3K)

`build_system_prompt()` in `runner.py` reduced to essential role/tool guidance:

```markdown
# Worker Role

You are a focused implementation worker. Your task is defined in your initial prompt.

## First Action (MANDATORY)
Read the Solution Design file referenced in your initial prompt. It describes the
intended approach. The acceptance criteria define success.

## Tool Allowlist
You have access to: Read, Write, Edit, Grep, Glob, Bash

For tool parameter reference, read: .claude/agents/worker-tool-reference.md

## Constraints
- Only modify files listed in the SD's "Files Changed" section unless the AC explicitly widens scope
- Write a signal file to $ATTRACTOR_SIGNAL_DIR/{node_id}.json on completion
- Write concerns to $CONCERNS_FILE if you encounter ambiguity or blockers
```

**What's removed** (~18K):
- Pipeline orchestration documentation (~6K)
- Signal protocol instructions (~5K) — workers just write one signal file
- Merge queue guidance (~3K) — guardian-level concern
- Inline tool examples (~2K) — extracted to reference file
- Architecture descriptions (~2K) — irrelevant to focused task

### 2.2 Restructured Initial Prompt (Primary Briefing)

`build_initial_prompt()` becomes the worker's main context:

```markdown
## Task: {node.label}

## PRD Reference
Read: {prd_path} (Section {epic_section})

## Solution Design
Read: {sd_path}
Key section: "2. Design" describes the technical approach.
Key section: "3. Files Changed" lists the files you should modify.

## Acceptance Criteria
{acceptance_criteria_from_dot_node}

## Directive
The SD describes the intended approach and the AC defines success criteria.
Use your judgment on implementation details. If you encounter ambiguity,
write a concern to $CONCERNS_FILE and proceed with your best interpretation.

## Skills
{Skill("skill-name") invocations from agent definition's skills_required}
```

### 2.3 Tool Reference File

New file `.claude/agents/worker-tool-reference.md`:

```markdown
# Worker Tool Reference

## Write (create new files)
Write(file_path="/absolute/path/to/file.py", content="content here")
Note: parameter is `file_path`, NOT `path`.

## Edit (modify existing files)
Edit(file_path="/absolute/path/to/file.py", old_string="existing", new_string="replacement")
Note: Do NOT pass `replace_all`.

## Read
Read(file_path="/absolute/path/to/file.py")

## Bash
Bash(command="python3 -m pytest tests/", description="Run tests")

## Signal File Format
Write a JSON file to $ATTRACTOR_SIGNAL_DIR/{node_id}.json:
{
  "status": "success",  // or "error"
  "sd_hash": "abc123",  // SHA256 of SD content you read
  "files_changed": ["path/to/file.py"],
  "message": "optional description"
}
```

### 2.4 Guardian Prompt Slimming

Apply same principle to `guardian.py`'s `build_system_prompt()`:
- Remove worker-level tool guidance
- Remove implementation examples
- Keep: guardian role, pipeline coordination, DOT traversal reference

## 3. Files Changed

| File | Change |
|------|--------|
| `runner.py` | `build_system_prompt()` slimmed to ~3K, `build_initial_prompt()` restructured |
| `guardian.py` | `build_system_prompt()` slimmed (remove worker-level content) |
| `.claude/agents/worker-tool-reference.md` (new) | Extracted tool examples + signal file format |

## 4. Testing

- Measure: system prompt char count before/after (target: 21K -> <4K)
- Measure: initial prompt char count before/after (target: 697 -> ~2K with SD path + AC)
- A/B test: run same pipeline with old and new prompts, compare worker behavior
- Regression: all existing tests must pass
- Verify: worker reads SD file as first action (check Logfire trace)

## 5. Acceptance Criteria

- AC-7.1.1: Worker system prompt is under 4K chars (down from 21K)
- AC-7.1.2: Worker initial prompt contains PRD path, SD path, and AC as the primary content
- AC-7.1.3: Initial prompt includes directive giving worker judgment on implementation details
- AC-7.1.4: Tool usage examples available as `.claude/agents/worker-tool-reference.md`, not embedded in system prompt
- AC-7.1.5: Guardian system prompt similarly slimmed (no worker-level guidance)
- AC-7.1.6: All existing tests pass; existing pipelines produce equivalent results

## 6. Implementation Status

**Status**: Complete (2026-03-07, commit c5ddb4d)
**Tests**: 21/22 pass, 1 skip (test_e71_worker_prompt.py)
**Branch**: feat/harness-upgrade-e4-e7

### What was built
- `_build_system_prompt()` in `pipeline_runner.py` produces ~3K system prompt (role, tool allowlist with usage examples, "read your SD first" directive)
- `_build_initial_prompt()` produces structured briefing: PRD path, SD content (inlined), acceptance criteria from DOT node
- Tool reference file at `.claude/agents/worker-tool-reference.md` with Write/Edit/Bash parameter examples
- Guardian system prompt in `guardian.py` similarly slimmed

### Deviations from design
- SD content is **inlined** into the initial prompt (not just a path reference) — eliminates a Read round-trip for the worker
- Tool examples kept in system prompt as well as reference file — workers need them immediately, not after a Read
- Boolean format note (`true`/`false` not `True`/`False`) added to prevent common Python-to-CLI errors
