"""dispatch_worker.py — Worker dispatch utilities for AgentSDK pipeline execution.

Provides shared utilities used by pipeline_runner.py for AgentSDK-based worker dispatch:
    compute_sd_hash()        — Compute hash of a solution design file
    load_engine_env()     — Load attractor-specific environment credentials
    create_signal_evidence() — Write signal evidence files for pipeline nodes
    load_agent_definition()  — Load agent definition YAML from .claude/agents/
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import yaml
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


def compute_sd_hash(sd_content: str) -> str:
    """Compute SHA256 hash of SD content, truncated to first 16 characters.

    Args:
        sd_content: The solution design content as a string

    Returns:
        First 16 characters of the SHA256 hash of the SD content
    """
    return hashlib.sha256(sd_content.encode()).hexdigest()[:16]


def create_signal_evidence(node_id: str, status: str, sd_content: str = "", sd_path: str = "") -> dict:
    """Create signal evidence dictionary with SD hash included.

    Args:
        node_id: The node identifier
        status: The status of the operation
        sd_content: The solution design content to hash
        sd_path: The path to the solution design file

    Returns:
        Dictionary containing signal evidence with sd_hash field
    """
    signal = {
        "node": node_id,
        "status": status,
    }

    if sd_content:
        signal["sd_hash"] = compute_sd_hash(sd_content)

    if sd_path:
        signal["sd_path"] = sd_path

    return signal


# Keys that load_engine_env() is permitted to return.
_ENGINE_ENV_KEYS = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"})


# ---------------------------------------------------------------------------
# Module-level path constants (resolved once at import time)
# ---------------------------------------------------------------------------
# .env lives alongside this file at cobuilder/engine/.env
_this_dir = Path(__file__).resolve().parent  # cobuilder/engine/


def _find_attractor_env() -> Path:
    """Return the path to cobuilder/engine/.env (next to this file)."""
    return _this_dir / ".env"


def load_engine_env() -> dict[str, str]:
    """Load Anthropic credentials from ``cobuilder/engine/.env``.

    Reads the ``.env`` file co-located with this module and parses
    lines in the forms::

        export KEY=VALUE
        KEY=VALUE
        KEY="VALUE"
        KEY='VALUE'

    Only keys in ``_ENGINE_ENV_KEYS`` (``ANTHROPIC_API_KEY``,
    ``ANTHROPIC_BASE_URL``, ``ANTHROPIC_MODEL``) are returned; all other
    lines are silently ignored.

    Returns:
        Dict of allowed credential keys → values.  Returns ``{}`` if the
        file is missing or any parse error occurs.
    """
    # This file lives at cobuilder/engine/dispatch_worker.py.
    # The .env is at <project_root>/.claude/attractor/.env.
    env_path = _find_attractor_env()

    if not env_path.exists():
        logger.debug("load_engine_env: %s not found, skipping", env_path)
        return {}

    result: dict[str, str] = {}
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip leading "export "
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key not in _ENGINE_ENV_KEYS:
                continue
            # Strip surrounding quotes (" or ')
            value = value.strip()
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            result[key] = value
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_engine_env: failed to parse %s: %s", env_path, exc)
        return {}

    logger.debug("load_engine_env: loaded keys %s", list(result))
    return result


def load_agent_definition(work_dir: str, worker_type: str) -> dict:
    """Load an agent definition from its Markdown file and parse YAML frontmatter.

    Args:
        work_dir: The working directory of the project
        worker_type: The agent type (filename stem)

    Returns:
        The parsed YAML frontmatter as a dictionary

    Raises:
        FileNotFoundError: If the agent definition file does not exist
        ValueError: If the frontmatter is malformed
    """
    agents_dir = Path(work_dir) / ".claude" / "agents"
    agent_file = agents_dir / f"{worker_type}.md"

    if not agent_file.exists():
        raise FileNotFoundError(f"Agent definition not found: {agent_file}")

    content = agent_file.read_text()

    if not content.startswith("---"):
        raise ValueError(f"Agent file {agent_file} does not have YAML frontmatter")

    # Find the boundaries of the YAML frontmatter
    lines = content.split('\n')
    if len(lines) < 3:
        raise ValueError(f"Agent file {agent_file} has malformed YAML frontmatter")

    # Find where the frontmatter ends (the second occurrence of '---')
    frontmatter_end_idx = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            frontmatter_end_idx = i
            break

    if frontmatter_end_idx == -1:
        raise ValueError(f"Agent file {agent_file} has malformed YAML frontmatter (missing closing ---)")

    # Extract frontmatter lines (from after first --- to before second ---)
    frontmatter_lines = lines[1:frontmatter_end_idx]

    # Manually parse the YAML frontmatter, handling multi-line content carefully
    result = {}
    i = 0
    while i < len(frontmatter_lines):
        line = frontmatter_lines[i].rstrip()

        if not line.strip():  # Skip empty lines
            i += 1
            continue

        # Check if this line is a field definition (key: value format)
        colon_pos = line.find(':')
        if colon_pos != -1:
            key = line[:colon_pos].strip()
            value_part = line[colon_pos + 1:].strip()

            # Check if this field has a multi-line value (indented content after)
            # Look ahead to see if subsequent lines are more indented
            next_i = i + 1
            multi_line_value = []

            # If the initial value part isn't empty, start with that
            if value_part:
                multi_line_value.append(value_part)

            # Collect indented lines that belong to this field
            while next_i < len(frontmatter_lines):
                next_line = frontmatter_lines[next_i]
                if next_line.strip() == "":
                    # Empty line, but check if next line is indented (still part of this field)
                    next_i += 1
                    continue

                # Count leading spaces to determine indentation
                leading_spaces = len(next_line) - len(next_line.lstrip())

                # If it's more indented than the key, it's part of this field
                key_indent = len(line) - len(line.lstrip())
                if leading_spaces > key_indent and next_line.strip():
                    multi_line_value.append(next_line.strip())
                    next_i += 1
                else:
                    # Less or equal indentation means a new field
                    break

            # Join multi-line value with newlines
            full_value = '\n'.join(multi_line_value) if multi_line_value else ''

            # Process the value based on its content
            if key == "skills_required":
                # Handle skills list format like [item1, item2, ...]
                if full_value.startswith('[') and full_value.endswith(']'):
                    # Extract items from bracketed list
                    items_str = full_value[1:-1]  # Remove [ and ]
                    # Split by comma, but be careful of commas in the middle of complex values
                    items = [item.strip().strip('"\'') for item in items_str.split(',')]
                    items = [item for item in items if item]  # Filter out empty items
                    result[key] = items
                else:
                    result[key] = []  # Default to empty list if not properly formatted
            elif full_value.lower() in ['true', 'false']:
                # Handle boolean values
                result[key] = full_value.lower() == 'true'
            elif full_value and full_value.lstrip('-').isdigit():
                # Handle integer values
                result[key] = int(full_value)
            else:
                # Store as string (this handles the problematic description field)
                result[key] = full_value

            # Move to the next potential field
            i = next_i
        else:
            # This shouldn't happen in proper YAML, but skip this line
            i += 1

    return result


def _build_headless_worker_cmd(*args, **kwargs):  # type: ignore[no-untyped-def]
    """Removed: headless mode is no longer supported. Use pipeline_runner.py with AgentSDK."""
    raise NotImplementedError(
        "_build_headless_worker_cmd removed. Use pipeline_runner.py --dot-file with AgentSDK dispatch."
    )


def run_headless_worker(*args, **kwargs):  # type: ignore[no-untyped-def]
    """Removed: headless mode is no longer supported. Use pipeline_runner.py with AgentSDK."""
    raise NotImplementedError(
        "run_headless_worker removed. Use pipeline_runner.py --dot-file with AgentSDK dispatch."
    )


