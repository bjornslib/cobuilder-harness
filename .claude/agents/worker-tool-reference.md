---
title: "Worker Tool Reference"
status: active
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# Worker Tool Reference

Quick reference for tool parameters in headless/SDK worker context.

## Write (create new files)

```
Write(file_path="/absolute/path/to/file.py", content="content here")
```

Note: parameter is `file_path`, NOT `path`.

## Edit (modify existing files)

```
Edit(file_path="/absolute/path/to/file.py", old_string="exact match", new_string="replacement")
```

Notes:
- `old_string` must match the file exactly (including whitespace and indentation)
- Do NOT pass `replace_all` unless you want to replace every occurrence
- Boolean values are `true`/`false` (lowercase), not `True`/`False`

## Read

```
Read(file_path="/absolute/path/to/file.py")
```

## Bash

```
Bash(command="python3 -m pytest tests/", description="Run tests")
```

## Signal File Format

Write a JSON file to `$ATTRACTOR_SIGNAL_DIR/{node_id}.json` on completion:

```json
{
  "status": "success",
  "sd_hash": "abc123def456",
  "files_changed": ["path/to/file.py", "path/to/other.py"],
  "message": "optional description of what was done"
}
```

On failure:
```json
{
  "status": "error",
  "message": "description of what went wrong",
  "files_changed": []
}
```

## Concerns File

If you encounter ambiguity or blockers, append a JSON line to `$CONCERNS_FILE`:

```json
{"node_id": "impl_e1", "concern": "SD says modify validator.py but file doesn't exist", "severity": "medium"}
```
