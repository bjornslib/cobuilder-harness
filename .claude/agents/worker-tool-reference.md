---
title: "Worker Tool Reference"
status: active
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# Worker Tool Reference

Your primary tools are: Bash, Read, Write, Edit, Glob, Grep, MultiEdit, TodoWrite, WebFetch, WebSearch.

You also have access to **LSP** (built-in type/definition tool) and **Serena MCP** (semantic code navigation). Use them for code investigation before falling back to Grep/Read on source files.

**Code Navigation Decision Guide** (use the right tool, not the first one):

| Task | Best Tool |
|------|-----------|
| Find a symbol by name | `mcp__serena__find_symbol` |
| Understand file/module structure | `mcp__serena__get_symbols_overview` |
| Find all callers of a function | `mcp__serena__find_referencing_symbols` |
| Search by regex/substring in code | `mcp__serena__search_for_pattern` |
| Edit a method body precisely | `mcp__serena__replace_symbol_body` |
| Get type info / docstrings | `LSP(operation="hover")` |
| Jump to exact definition | `LSP(operation="goToDefinition")` |
| Find all usages with types | `LSP(operation="findReferences")` |
| Detect type errors in file | `LSP(operation="documentSymbol")` |
| Grep/Read on source code | **Last resort only** (70-95% less efficient) |

## ABSOLUTE PATHS — MANDATORY

ALL file tool calls MUST use absolute paths. Relative paths will fail silently.

```
WRONG: Read(file_path="app/page.tsx")
RIGHT: Read(file_path="/Users/project/app/page.tsx")
```

Use `Bash(command="pwd")` at the start to get the working directory, then prefix all paths.

## CRITICAL RULE: Write vs Edit

**BEFORE creating or modifying any file, check if it exists first:**
```
Read(file_path="/absolute/path/to/target.tsx")
```
- If Read returns content → file exists → use **Edit** to change it
- If Read returns "file not found" → file is new → use **Write** to create it

| Situation | Tool | Why |
|-----------|------|-----|
| File does NOT exist yet | **Write** | Creates new files |
| File ALREADY exists and needs changes | **Edit** | Surgical replacement of specific text |
| File ALREADY exists and needs complete rewrite | **Write** | But you MUST Read THE SAME file first |

**THE #1 MISTAKE**: Using Write on an existing file when you should use Edit.
Write overwrites the entire file. Edit replaces only the specific text you target.
If you Read a file and it has content, use **Edit** to modify it — NOT Write.

**THE #2 MISTAKE**: Reading a DIFFERENT file to "satisfy" the Read-before-Write rule.
You must Read THE EXACT FILE you intend to Write. Reading package.json does not unlock Write for page.tsx.

**THE #3 MISTAKE**: Retrying the same failed tool call.
If a tool call fails, STOP and diagnose why. Do NOT retry the same call. Common causes:
- Relative path (must be absolute)
- File exists (use Edit instead of Write)
- old_string doesn't match (Read the file again to get exact content)

## Tool Decision Flowchart

```
Need to change code?
  1. First: Read(file_path="/absolute/path/to/file")
  2. Did Read succeed (file has content)?
     → YES: Use Edit to change specific parts
     → NO (file not found): Use Write to create it

Need to find something?
  → Know the filename pattern? → Glob
  → Know text to search for?  → Grep
  → Need to explore structure? → Bash("ls -la path/")

Need to run a command?
  → Bash (tests, builds, git, shell commands)
```

## Read

Read a file before modifying it. Always use absolute paths. Also use Read to CHECK if a file exists before deciding Write vs Edit.

```
Read(file_path="/absolute/path/to/file.py")
```

- Use `offset` and `limit` for large files: `Read(file_path="...", offset=100, limit=50)`
- MUST Read THE TARGET FILE before Edit (Edit will fail if you haven't read it)
- MUST Read THE TARGET FILE before Write on existing files (not a different file — the same one)

## Edit (modify existing files)

Replace specific text in an existing file. This is your PRIMARY editing tool.

```
Edit(file_path="/absolute/path/to/file.py", old_string="exact text to find", new_string="replacement text")
```

Rules:
- `old_string` MUST match the file content exactly — same whitespace, same indentation, same line breaks
- `old_string` must be unique in the file, or the edit will fail
- If you need to replace ALL occurrences: `Edit(file_path="...", old_string="...", new_string="...", replace_all=true)`
- Boolean values are `true`/`false` (lowercase), NOT `True`/`False`
- When your `old_string` isn't unique, include more surrounding context lines to make it unique

## Write (create NEW files)

Create a new file or completely overwrite an existing one.

```
Write(file_path="/absolute/path/to/new_file.py", content="file content here")
```

- Parameter is `file_path`, NOT `path`
- ONLY use for: (1) creating files that don't exist, (2) writing signal files, (3) complete rewrites after Reading
- If the file exists and you only need to change part of it → use **Edit** instead

## MultiEdit (multiple changes to one file)

Apply several edits to the same file in a single call. More efficient than multiple Edit calls.

```
MultiEdit(file_path="/absolute/path/to/file.py", edits=[
  {"old_string": "first match", "new_string": "first replacement"},
  {"old_string": "second match", "new_string": "second replacement"}
])
```

- Each edit follows the same rules as Edit (exact match, unique strings)
- Edits are applied in order
- Use when you need 2+ changes in the same file

## Glob (find files by name)

Find files matching a pattern. Use BEFORE Read when you don't know the exact path.

```
Glob(pattern="**/*.py", path="/absolute/path/to/search")
```

- `**/*.tsx` — all TypeScript React files recursively
- `src/**/index.ts` — all index files under src
- Returns file paths sorted by modification time

## Grep (search file contents)

Search for text or patterns across files. Use to find where code lives.

```
Grep(pattern="function_name", path="/absolute/path/to/search", output_mode="content")
```

- `output_mode="content"` — show matching lines (default: just file paths)
- `glob="*.py"` — restrict to specific file types
- `-n=true` — show line numbers (default for content mode)
- Supports regex: `Grep(pattern="def\\s+my_func")`

## Bash (run commands)

Execute shell commands. Use for tests, builds, git, and system operations.

```
Bash(command="python3 -m pytest tests/", description="Run tests")
```

- Always include a `description` for clarity
- Do NOT use Bash for: reading files (use Read), editing files (use Edit), searching (use Grep/Glob)
- Use absolute paths in commands

## TodoWrite (track your progress)

Track subtasks within your session. Helps you stay organized on multi-step work.

```
TodoWrite(todos=[
  {"id": "1", "content": "Read existing component", "status": "completed"},
  {"id": "2", "content": "Add new props", "status": "in_progress"},
  {"id": "3", "content": "Update tests", "status": "pending"}
])
```

- `status`: `"pending"`, `"in_progress"`, or `"completed"`
- Use at the start of complex tasks to plan your steps
- Update status as you complete each step

## WebFetch (fetch a URL)

Fetch content from a URL. Useful for reading documentation or API responses.

```
WebFetch(url="https://docs.example.com/api/reference")
```

- Returns the page content as text
- Use for documentation lookups, API specs, or verifying live endpoints

## WebSearch (search the web)

Search the web for information. Useful for finding documentation or solutions.

```
WebSearch(query="React useCallback best practices 2025")
```

- Returns search results with snippets
- Use when you need current information about a framework, library, or pattern

## LSP (type info and definitions)

Query type information, definitions, and diagnostics from the language server. Requires `pyright-langserver` (Python) or `typescript-language-server` (TypeScript/JS) to be installed.

```
LSP(operation="hover", filePath="/absolute/path/to/file.py", line=33, character=10)
```

Operations:
- `"hover"` — type info and docstrings at a position
- `"goToDefinition"` — find where a symbol is defined
- `"findReferences"` — all usages of a symbol (with types)
- `"documentSymbol"` — list all symbols + diagnostics in a file
- `"incomingCalls"` / `"outgoingCalls"` — call hierarchy
- `"goToImplementation"` — find concrete implementations of an interface

Use LSP when you need type information or exact definitions. Use Serena for structural navigation.

## Serena MCP (semantic code navigation)

Navigate code semantically — no regex, no line numbers, just symbol names.

**Activate first** (once per session):
```
mcp__serena__check_onboarding_performed()
mcp__serena__activate_project(project="<project-name>")
```

**Find a symbol**:
```
mcp__serena__find_symbol(name_path_pattern="ClassName/method_name", include_body=True)
```

**Search for a pattern across source files**:
```
mcp__serena__search_for_pattern(substring_pattern="pattern_here", restrict_search_to_code_files=True)
```

**Get file/module structure**:
```
mcp__serena__get_symbols_overview(relative_path="src/module.py")
```

**Find all callers of a symbol**:
```
mcp__serena__find_referencing_symbols(name_path="ClassName/method_name", relative_path="src/module.py")
```

**Replace a method body** (implementation workers only):
```
mcp__serena__replace_symbol_body(name_path="ClassName/method_name", relative_path="src/module.py", body="    def method_name(self):\n        ...")
```

## Common Workflows

### Modify an existing file
```
1. Read(file_path="/path/to/file.py")           ← see current content
2. Edit(file_path="/path/to/file.py",            ← change specific part
       old_string="old code",
       new_string="new code")
```

### Create a new file
```
1. Write(file_path="/path/to/new_file.py",       ← create it
        content="file content")
```

### Find and modify code
```
1. Grep(pattern="ClassName", path="/project")     ← find where it lives
2. Read(file_path="/project/src/module.py")       ← read the file
3. Edit(file_path="/project/src/module.py",       ← modify it
       old_string="...", new_string="...")
```

## Signal File Protocol

**Important**: Implementation workers should NOT git commit their changes.
The validation-test-agent commits on your behalf after successful validation.
This ensures commits are only made for validated, scoped work.

On task completion, write a signal file to `$ATTRACTOR_SIGNAL_DIR/{node_id}.json`:

```bash
# First, check the signal directory path
Bash(command="echo $ATTRACTOR_SIGNAL_DIR", description="Get signal directory path")
```

Then write the signal (this is a NEW file, so Write is correct):

Success:
```json
{"status": "success", "files_changed": ["path/to/file.py"], "message": "brief description"}
```

Failure:
```json
{"status": "error", "message": "what went wrong", "files_changed": []}
```
