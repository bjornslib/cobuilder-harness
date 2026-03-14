"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/engine/run_research.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/run_research.py is deprecated. "
    "Use cobuilder.engine.run_research instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.engine.run_research import *  # noqa: F401,F403
