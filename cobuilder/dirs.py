"""Centralized path constants for CoBuilder runtime state.

All runtime state (pipelines, signals, checkpoints, runner-state) lives under
a single `.cobuilder/` directory at the project root. This module provides
the canonical way to resolve that directory.

Resolution order:
  1. COBUILDER_STATE_DIR env var (explicit override)
  2. Walk up from CWD to find `.cobuilder/` (project-relative)
  3. Walk up from CWD to find `.claude/attractor/` (30-day fallback)
  4. Default: CWD / .cobuilder (created on first use)

Usage:
    from cobuilder.dirs import get_state_dir, get_pipelines_dir, get_signals_dir

    state = get_state_dir()          # -> /path/to/.cobuilder
    pipes = get_pipelines_dir()      # -> /path/to/.cobuilder/pipelines
    sigs  = get_signals_dir()        # -> /path/to/.cobuilder/signals
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# Maximum levels to walk up when searching for project root
_MAX_WALK_UP = 10

# Legacy state directory name (30-day fallback period)
_LEGACY_STATE_DIR = ".claude/attractor"

# New state directory name
_STATE_DIR_NAME = ".cobuilder"


def _find_dir_upward(start: Path, target: str, max_levels: int = _MAX_WALK_UP) -> Path | None:
    """Walk up from *start* looking for a directory named *target*."""
    current = start.resolve()
    for _ in range(max_levels):
        candidate = current / target
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def get_state_dir(*, create: bool = True) -> Path:
    """Return the CoBuilder state directory.

    Args:
        create: If True (default), create the directory if it doesn't exist.

    Returns:
        Path to the state directory.
    """
    # 1. Explicit env var override
    env_override = os.environ.get("COBUILDER_STATE_DIR")
    if env_override:
        p = Path(env_override)
        if create:
            p.mkdir(parents=True, exist_ok=True)
        return p

    cwd = Path.cwd()

    # 2. Walk up to find .cobuilder/
    found = _find_dir_upward(cwd, _STATE_DIR_NAME)
    if found:
        return found

    # 3. Fallback: walk up to find legacy .claude/attractor/
    legacy = _find_dir_upward(cwd, _LEGACY_STATE_DIR)
    if legacy:
        log.info(
            "[dirs] Using legacy state dir %s — migrate to .cobuilder/ "
            "(fallback expires 2026-04-10)",
            legacy,
        )
        return legacy

    # 4. Default: create .cobuilder/ in CWD
    default = cwd / _STATE_DIR_NAME
    if create:
        default.mkdir(parents=True, exist_ok=True)
    return default


def get_pipelines_dir(*, create: bool = True) -> Path:
    """Return the pipelines directory (contains .dot files)."""
    p = get_state_dir(create=create) / "pipelines"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def get_signals_dir(*, create: bool = True) -> Path:
    """Return the signals directory."""
    p = get_state_dir(create=create) / "signals"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def get_checkpoints_dir(*, create: bool = True) -> Path:
    """Return the checkpoints directory."""
    p = get_state_dir(create=create) / "checkpoints"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def get_runner_state_dir(*, create: bool = True) -> Path:
    """Return the runner-state directory."""
    p = get_state_dir(create=create) / "runner-state"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def get_examples_dir(*, create: bool = False) -> Path:
    """Return the examples directory (not auto-created by default)."""
    p = get_state_dir(create=create) / "examples"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p
