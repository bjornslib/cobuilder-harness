"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/engine/run_refine.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/run_refine.py is deprecated. "
    "Use cobuilder.engine.run_refine instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.engine.run_refine import *  # noqa: F401,F403
