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


# Keys that load_engine_env() always loads (Anthropic SDK defaults).
# Additional keys referenced by providers.yaml profiles (e.g. $OPENROUTER_API_KEY)
# are also loaded — see _load_providers_env_keys().
_CORE_ENV_KEYS = frozenset({"ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"})


def _load_providers_env_keys() -> frozenset[str]:
    """Scan providers.yaml for $VAR references and return the var names.

    This allows load_engine_env() to load provider-specific keys like
    OPENROUTER_API_KEY or MINIMAX_API_KEY from .env without hardcoding them.
    """
    import re

    providers_path = _this_dir / "providers.yaml"
    if not providers_path.exists():
        return frozenset()

    env_var_pattern = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
    keys: set[str] = set()
    try:
        for line in providers_path.read_text(encoding="utf-8").splitlines():
            for match in env_var_pattern.finditer(line):
                keys.add(match.group(1))
    except Exception:  # noqa: BLE001
        pass
    return frozenset(keys)


# ---------------------------------------------------------------------------
# Module-level path constants (resolved once at import time)
# ---------------------------------------------------------------------------
# .env lives alongside this file at cobuilder/engine/.env
_this_dir = Path(__file__).resolve().parent  # cobuilder/engine/


def _find_attractor_env() -> Path:
    """Return the path to cobuilder/engine/.env (next to this file)."""
    return _this_dir / ".env"


def load_engine_env() -> dict[str, str]:
    """Load LLM credentials from ``cobuilder/engine/.env``.

    Reads the ``.env`` file co-located with this module and parses
    lines in the forms::

        export KEY=VALUE
        KEY=VALUE
        KEY="VALUE"
        KEY='VALUE'

    Loads the core Anthropic SDK keys (``ANTHROPIC_API_KEY``,
    ``ANTHROPIC_BASE_URL``, ``ANTHROPIC_MODEL``), **plus** any env var
    keys referenced in ``providers.yaml`` (e.g. ``$OPENROUTER_API_KEY``,
    ``$MINIMAX_API_KEY``).  Keys also matching the ``PIPELINE_*`` prefix
    are loaded for runner configuration.

    Returns:
        Dict of allowed credential keys → values.  Returns ``{}`` if the
        file is missing or any parse error occurs.
    """
    env_path = _find_attractor_env()

    if not env_path.exists():
        logger.debug("load_engine_env: %s not found, skipping", env_path)
        return {}

    allowed_keys = _CORE_ENV_KEYS | _load_providers_env_keys()

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
            if key not in allowed_keys and not key.startswith("PIPELINE_"):
                continue
            # Strip surrounding quotes (" or ')
            value = value.strip()
            if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
                value = value[1:-1]
            # Expand $VARIABLE references against already-parsed values
            # and inherited environment (mirrors pipeline_runner behaviour)
            if value.startswith("$"):
                ref_key = value[1:]
                value = result.get(ref_key, os.environ.get(ref_key, value))
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


