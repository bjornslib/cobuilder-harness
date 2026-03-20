---
title: "Worker Tool Reference"
status: active
type: reference
last_verified: 2026-03-17
grade: authoritative
---

# Worker Tool Reference

## How You Work

You are a focused worker. Your job is to understand the codebase, make changes, and verify they work.

**Loop: Explore → Plan → Implement → Verify → Signal**

1. **Explore first**: Read files, Grep for patterns, understand before changing anything.
2. **Plan with TodoWrite**: Break your task into steps, track progress as you go.
3. **Implement with Edit**: Small, verified changes. Read every file before editing it.
4. **Verify with Bash**: Run tests, check your work compiles/passes.
5. **Signal when done**: Write the signal file with files_changed list.

## Exploring the Codebase

### Before Editing Any File, Understand It

```
1. Glob("**/*.py", path="/project/src")     — find relevant files
2. Read the file you'll change              — understand the full context
3. Grep("function_name")                    — find callers and dependencies
4. Read the test file                       — understand expected behavior
5. THEN plan your changes with TodoWrite
```

### Tracing Data Flows

When the SD says "modify the auth handler":
1. `Grep("auth")` — find all auth-related files
2. Read the main auth file — understand the current flow
3. Grep for the function being called — find upstream callers
4. Read downstream dependencies — understand what breaks if you change this
5. Now you understand the flow — implement with confidence

### When Reality Doesn't Match the SD

The SD is a guide, not a contract. If you discover that:
- A file doesn't exist where the SD says → Grep for it, find where it moved
- A function has a different signature → Read the actual code and adapt
- The SD misses a dependency → Fix it and note in your signal message

## Tools

Your primary tools: Bash, Read, Write, Edit, Glob, Grep, MultiEdit, TodoWrite, WebFetch, WebSearch.

You also have **LSP** (built-in type/definition tool) and **Serena MCP** (semantic code navigation — load via ToolSearch first).

### Absolute Paths

All file tool calls MUST use absolute paths. Use `Bash(command="pwd")` to get the working directory.

### Write vs Edit Decision

Before creating or modifying any file, check if it exists:
```
Read(file_path="/absolute/path/to/target.tsx")
```
- Read returns content → file exists → use **Edit**
- Read returns "file not found" → file is new → use **Write**

| Situation | Tool |
|-----------|------|
| File does NOT exist yet | **Write** |
| File exists, needs specific changes | **Edit** |
| File exists, needs complete rewrite | **Write** (but Read the same file first) |

Key rules:
- Read THE EXACT FILE you intend to Write (not a different file)
- If a tool call fails, diagnose why before retrying (wrong path? file exists? old_string mismatch?)

### Read

```
Read(file_path="/absolute/path/to/file.py")
Read(file_path="...", offset=100, limit=50)   # for large files
```

Must Read the target file before Edit or Write on existing files.

### Edit (modify existing files)

Your PRIMARY editing tool. Replaces specific text in a file.

```
Edit(file_path="/absolute/path/to/file.py", old_string="exact text to find", new_string="replacement text")
```

- `old_string` must match exactly — same whitespace, indentation, line breaks
- Must be unique in the file; include more context lines if not
- `replace_all=true` to replace ALL occurrences
- Boolean values: `true`/`false` (lowercase)

### Write (create new files)

```
Write(file_path="/absolute/path/to/new_file.py", content="file content here")
```

Only use for: (1) new files, (2) signal files, (3) complete rewrites after Reading.

### MultiEdit (multiple changes to one file)

```
MultiEdit(file_path="/absolute/path/to/file.py", edits=[
  {"old_string": "first match", "new_string": "first replacement"},
  {"old_string": "second match", "new_string": "second replacement"}
])
```

### Glob (find files by name)

```
Glob(pattern="**/*.py", path="/absolute/path")
```

### Grep (search file contents)

```
Grep(pattern="function_name", path="/absolute/path", output_mode="content")
```

- `output_mode="content"` shows matching lines; `glob="*.py"` restricts file types
- Supports regex: `Grep(pattern="def\\s+my_func")`

### Bash (run commands)

```
Bash(command="python3 -m pytest tests/", description="Run tests")
```

Do NOT use Bash for: reading files (Read), editing files (Edit), searching (Grep/Glob).

### TodoWrite (track your progress)

```
TodoWrite(todos=[
  {"id": "1", "content": "Read existing component", "status": "completed"},
  {"id": "2", "content": "Add new props", "status": "in_progress"},
  {"id": "3", "content": "Update tests", "status": "pending"}
])
```

Use at the start of multi-step tasks. Update status as you complete each step.

### WebFetch / WebSearch

```
WebFetch(url="https://docs.example.com/api/reference")
WebSearch(query="React useCallback best practices 2025")
```

## ToolSearch — Discover MCP Tools Before Use

MCP tools (context7, Hindsight, Perplexity, Serena) are **deferred** — load them via ToolSearch before use.

```
ToolSearch(query="hindsight")     # memory/learning tools
ToolSearch(query="context7")      # library/framework docs
ToolSearch(query="perplexity")    # web research
ToolSearch(query="serena")        # code navigation
```

ToolSearch must complete BEFORE you call the discovered tool. Do NOT run ToolSearch in parallel with the tool it loads.

## Hindsight Memory — Recall and Retain Across Sessions

Long-term memory shared across all sessions. Load first: `ToolSearch(query="hindsight")`

```bash
# Get project bank ID
Bash(command="echo $CLAUDE_PROJECT_BANK", description="Get project memory bank")
```

| Operation | When | Example |
|-----------|------|---------|
| `recall` | Start of task — check for prior work | `mcp__hindsight__recall(query="...", bank_id="...")` |
| `reflect` | Before major decisions | `mcp__hindsight__reflect(query="...", budget="mid", bank_id="...")` |
| `retain` | After completing work | `mcp__hindsight__retain(content="...", context="...", bank_id="...")` |

## Context7 — Framework/Library Documentation

Load first: `ToolSearch(query="context7")`

Use for: React, FastAPI, PydanticAI, TanStack Query, or any popular open-source library.
Do NOT use for: proprietary APIs, general web facts, internal codebase patterns.

```
mcp__context7__resolve-library-id(libraryName="react")
mcp__context7__query-docs(libraryId="/facebook/react", query="useCallback optimization")
```

## Code Navigation Decision Guide

| Task | Best Tool |
|------|-----------|
| Find a symbol by name | `mcp__serena__find_symbol` |
| Understand file/module structure | `mcp__serena__get_symbols_overview` |
| Find all callers of a function | `mcp__serena__find_referencing_symbols` |
| Search by regex/substring | `mcp__serena__search_for_pattern` |
| Edit a method body precisely | `mcp__serena__replace_symbol_body` |
| Get type info / docstrings | `LSP(operation="hover")` |
| Jump to exact definition | `LSP(operation="goToDefinition")` |
| Find all usages with types | `LSP(operation="findReferences")` |
| Detect type errors in file | `LSP(operation="documentSymbol")` |

## LSP (type info and definitions)

```
LSP(operation="hover", filePath="/absolute/path/to/file.py", line=33, character=10)
```

Operations: `hover`, `goToDefinition`, `findReferences`, `documentSymbol`, `incomingCalls`, `outgoingCalls`, `goToImplementation`.

## Serena MCP (semantic code navigation)

Load first: `ToolSearch(query="serena")`

```
mcp__serena__check_onboarding_performed()
mcp__serena__activate_project(project="<project-name>")
mcp__serena__find_symbol(name_path_pattern="ClassName/method_name", include_body=True)
mcp__serena__search_for_pattern(substring_pattern="pattern", restrict_search_to_code_files=True)
mcp__serena__get_symbols_overview(relative_path="src/module.py")
```

## Signal File Protocol

Implementation workers should NOT git commit. The validation-test-agent commits after successful validation.

On completion, write a signal file to `$PIPELINE_SIGNAL_DIR/{node_id}.json`:

```bash
Bash(command="echo $PIPELINE_SIGNAL_DIR", description="Get signal directory path")
```

Success:
```json
{"status": "success", "files_changed": ["path/to/file.py"], "message": "brief description"}
```

Failure:
```json
{"status": "error", "message": "what went wrong", "files_changed": []}
```

## Model Selection Guide

| Handler | Default Model | When to Override |
|---------|--------------|-----------------|
| codergen | claude-haiku-4-5-20251001 | claude-sonnet-4-5-20251001 for complex multi-file changes |
| research | claude-haiku-4-5-20251001 | Rarely needs upgrade |
| refine | claude-sonnet-4-5-20251001 | Always Sonnet (requires synthesis) |
| validation | claude-sonnet-4-5-20251001 | Never downgrade (needs judgment) |
