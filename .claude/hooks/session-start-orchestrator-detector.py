#!/usr/bin/env python3
"""
SessionStart Hook: Orchestrator Skill Detector

This hook runs when a session starts. When the source is "compact" (post-compaction),
it checks if the orchestrator-multiagent skill was active in the pre-compaction
transcript and sets a flag for the UserPromptSubmit hook to inject a reminder.

The flag file persists the state between hooks since they run in separate processes.

DISTRIBUTION NOTE: This hook should be placed in .claude/hooks/ at the project level
for projects using the orchestrator-multiagent skill.
"""

import json
import os
import sys
from pathlib import Path


SKILL_NAME = "orchestrator-multiagent"
FLAG_FILE = Path.home() / ".claude" / "state" / "orchestrator-reminder-pending"
DEBUG_FILE = Path.home() / ".claude" / "state" / "sessionstart-debug.log"


def log_debug(msg: str):
    """Append debug message to log file."""
    try:
        DEBUG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DEBUG_FILE, "a") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def find_transcript_for_cwd(cwd: str) -> Path | None:
    """
    Find the most recent transcript file for the given working directory.
    Claude Code stores transcripts in ~/.claude/projects/-path-to-project/
    """
    # Convert cwd to Claude's project directory format
    # e.g., /home/user/project -> -home-user-project
    project_slug = cwd.replace("/", "-")
    if project_slug.startswith("-"):
        project_slug = project_slug  # Keep leading dash

    projects_dir = Path.home() / ".claude" / "projects"

    # Find matching project directory
    for project_dir in projects_dir.iterdir():
        if project_dir.is_dir() and project_dir.name == project_slug:
            # Find most recent .jsonl file (excluding agent-* files which are subagents)
            jsonl_files = [
                f for f in project_dir.glob("*.jsonl")
                if not f.name.startswith("agent-")
            ]
            if jsonl_files:
                # Return most recently modified
                return max(jsonl_files, key=lambda f: f.stat().st_mtime)

    return None


def parse_transcript_for_skill(transcript_path: Path, skill_name: str) -> bool:
    """
    Parse a JSONL transcript file and check if a specific skill was invoked.
    """
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    message = entry.get("message", {})
                    content = message.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use" and block.get("name") == "Skill":
                                input_data = block.get("input", {})
                                if isinstance(input_data, dict) and input_data.get("skill") == skill_name:
                                    log_debug(f"Found skill '{skill_name}' in transcript")
                                    return True
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError) as e:
        log_debug(f"Error reading transcript: {e}")
        return False
    return False


def main():
    """
    Main entry point for the SessionStart hook.

    Input JSON:
    {
        "session_id": "...",
        "transcript_path": "...",
        "cwd": "...",
        "source": "startup" | "resume" | "clear" | "compact",
        ...
    }
    """
    # Always log that we started, even before reading stdin
    log_debug(f"=== Hook Started at {__file__} ===")

    try:
        # Read raw stdin first for debugging
        raw_input = sys.stdin.read()
        log_debug(f"Raw stdin length: {len(raw_input)}")
        log_debug(f"Raw stdin (first 500 chars): {raw_input[:500]}")

        if not raw_input.strip():
            log_debug("ERROR: Empty stdin received")
            sys.exit(0)

        input_data = json.loads(raw_input)
        source = input_data.get("source", "")
        transcript_path = input_data.get("transcript_path", "")
        cwd = input_data.get("cwd", os.getcwd())

        log_debug("--- SessionStart Hook ---")
        log_debug(f"source: {source}")
        log_debug(f"cwd: {cwd}")
        log_debug(f"transcript_path (provided): {transcript_path}")
        log_debug(f"input keys: {list(input_data.keys())}")

        # Only act on post-compaction
        if source != "compact":
            log_debug("Not a compact event, exiting")
            sys.exit(0)

        # Ensure state directory exists
        FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Try to find transcript if not provided or doesn't exist
        transcript = None
        if transcript_path and Path(transcript_path).exists():
            transcript = Path(transcript_path)
            log_debug(f"Using provided transcript: {transcript}")
        else:
            # Fall back to finding transcript based on cwd
            transcript = find_transcript_for_cwd(cwd)
            log_debug(f"Found transcript via cwd: {transcript}")

        # Check if orchestrator skill was active
        if transcript and parse_transcript_for_skill(transcript, SKILL_NAME):
            # Set flag for UserPromptSubmit hook
            FLAG_FILE.write_text(SKILL_NAME)
            log_debug(f"Flag file created: {FLAG_FILE}")
        else:
            log_debug(f"Skill '{SKILL_NAME}' not found in transcript")
            # Clean up flag if it exists but skill wasn't active
            if FLAG_FILE.exists():
                FLAG_FILE.unlink()
                log_debug("Cleaned up existing flag file")

    except Exception as e:
        # Hooks should fail gracefully
        log_debug(f"ERROR: {e}")
        print(f"Warning: SessionStart hook error: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
