#!/usr/bin/env python3
"""
PreToolUse hook — nudges agents toward Serena MCP for source code exploration.

When Claude Code invokes Read or Grep targeting source code files (.py, .ts, etc.),
this hook blocks the call and suggests the Serena equivalent (find_symbol,
search_for_pattern, get_symbols_overview).

Hook type : PreToolUse (matcher: "Read|Grep")
Input     : JSON on stdin with {"tool_name": "Read"|"Grep", "tool_input": {...}}
Output    : JSON on stdout — {"decision": "approve"} or {"decision": "block", "reason": "..."}

Fast path : ~1ms for non-code files (extension check only).

Bypass methods:
  1. Environment variable : SERENA_ENFORCE_SKIP=1
  2. Signal file          : .claude/.serena-enforce-skip

PRD: PRD-SERENA-ENFORCE-001
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Source code extensions that should use Serena instead of Read/Grep
SOURCE_CODE_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".jsx", ".js",
    ".vue", ".go", ".rs", ".java", ".kt",
    ".rb", ".php", ".swift", ".c", ".cpp",
    ".h", ".hpp", ".cs", ".scala", ".ex",
    ".exs", ".clj", ".zig", ".nim", ".lua",
})

# Directories where source code reads are always allowed (non-application code)
WHITELISTED_DIRS = frozenset({
    ".claude", ".taskmaster", "acceptance-tests", "docs", "documentation",
    ".beads", ".serena", ".zerorepo", ".github", ".vscode",
    "node_modules", "__pycache__", ".git",
})

# Non-code extensions that are always allowed
NON_CODE_EXTENSIONS = frozenset({
    ".md", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini",
    ".env", ".txt", ".csv", ".feature", ".html", ".css", ".scss",
    ".dot", ".gitignore", ".lock", ".log", ".xml", ".svg",
    ".sh", ".bash", ".zsh", ".fish",  # Shell scripts are config-like
    ".sql", ".graphql", ".gql",       # Query languages
    ".dockerfile", ".dockerignore",
    ".editorconfig", ".prettierrc", ".eslintrc",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approve(message: str | None = None) -> None:
    """Print approve decision and exit."""
    result: dict = {"decision": "approve"}
    if message:
        result["systemMessage"] = message
    print(json.dumps(result))
    sys.exit(0)


def _block(reason: str) -> None:
    """Print block decision and exit."""
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def _is_bypassed(project_dir: str) -> bool:
    """Check if enforcement is bypassed via env var or signal file."""
    if os.environ.get("SERENA_ENFORCE_SKIP", "").strip() in ("1", "true", "yes"):
        return True
    signal_file = Path(project_dir) / ".claude" / ".serena-enforce-skip"
    if signal_file.exists():
        return True
    return False


def _serena_is_active(project_dir: str) -> bool:
    """Check if Serena is configured for this project."""
    serena_config = Path(project_dir) / ".serena" / "project.yml"
    return serena_config.exists()


def _is_in_whitelisted_dir(file_path: str, project_dir: str) -> bool:
    """Check if file is in a directory that's always allowed."""
    try:
        rel = Path(file_path).relative_to(project_dir)
    except ValueError:
        return False
    parts = rel.parts
    if not parts:
        return False
    return parts[0] in WHITELISTED_DIRS


def _get_extension(file_path: str) -> str:
    """Get lowercase file extension."""
    return Path(file_path).suffix.lower()


def _is_source_code(file_path: str) -> bool:
    """Check if a file path points to source code based on extension."""
    ext = _get_extension(file_path)
    if ext in NON_CODE_EXTENSIONS:
        return False
    if ext in SOURCE_CODE_EXTENSIONS:
        return True
    # Unknown extension — don't block (err toward approval)
    return False


# ---------------------------------------------------------------------------
# Tool-specific extractors
# ---------------------------------------------------------------------------

def _extract_path_from_read(tool_input: dict) -> str | None:
    """Extract the file path from a Read tool call."""
    return tool_input.get("file_path")


def _extract_path_from_grep(tool_input: dict) -> str | None:
    """Extract the target path from a Grep tool call."""
    return tool_input.get("path")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Parse hook input
    try:
        data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        _approve()  # Can't parse — don't block
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Determine project directory
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    # Fast path: bypass check
    if _is_bypassed(project_dir):
        _approve()
        return

    # Fast path: Serena not active — approve everything
    if not _serena_is_active(project_dir):
        _approve()
        return

    # Extract the target file/path
    if tool_name == "Read":
        target_path = _extract_path_from_read(tool_input)
    elif tool_name == "Grep":
        target_path = _extract_path_from_grep(tool_input)
    else:
        _approve()  # Unknown tool — don't block
        return

    if not target_path:
        _approve()  # No path — can't determine, approve
        return

    # Fast path: whitelisted directories
    if _is_in_whitelisted_dir(target_path, project_dir):
        _approve()
        return

    # Check if target is source code
    if tool_name == "Read" and _is_source_code(target_path):
        ext = _get_extension(target_path)
        _approve(
            f"[serena-enforce] Tip: Serena is active. For exploration, prefer "
            f"Serena (find_symbol, get_symbols_overview) for navigation or "
            f"LSP(operation='hover') for type info — both are more precise than Read for {ext} files "
            f"(70-95% token savings). Read is allowed for pre-edit file loading."
        )
        return

    if tool_name == "Grep" and target_path:
        # For Grep, check if the path itself is a source file or a directory
        # that likely contains source code
        target = Path(target_path)
        if target.is_file() and _is_source_code(target_path):
            _block(
                f"[serena-enforce] Serena is active for this project. "
                f"Use mcp__serena__search_for_pattern() for pattern search, or "
                f"LSP(operation='findReferences') for symbol usages — "
                f"instead of Grep for source code files. "
                f"Bypass: set SERENA_ENFORCE_SKIP=1 or create .claude/.serena-enforce-skip"
            )
            return
        # For Grep on directories, check the glob filter
        glob_filter = tool_input.get("glob", "") or tool_input.get("type", "")
        if glob_filter:
            # If grep is filtering for source code types, suggest Serena
            code_globs = {"*.py", "*.ts", "*.tsx", "*.jsx", "*.js", "*.go", "*.rs", "*.java"}
            code_types = {"py", "ts", "js", "go", "rust", "java", "python", "typescript"}
            if glob_filter in code_globs or glob_filter in code_types:
                _block(
                    f"[serena-enforce] Serena is active for this project. "
                    f"Use mcp__serena__search_for_pattern() for pattern search, or "
                    f"LSP(operation='findReferences') for symbol usages — "
                    f"instead of Grep with type/glob filter '{glob_filter}'. "
                    f"Bypass: set SERENA_ENFORCE_SKIP=1 or create .claude/.serena-enforce-skip"
                )
                return

    # Default: approve
    _approve()


if __name__ == "__main__":
    main()
