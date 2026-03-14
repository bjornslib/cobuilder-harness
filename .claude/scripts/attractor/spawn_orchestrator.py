"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/engine/spawn_orchestrator.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/spawn_orchestrator.py is deprecated. "
    "Use cobuilder.engine.spawn_orchestrator instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.engine.spawn_orchestrator import *  # noqa: F401,F403
