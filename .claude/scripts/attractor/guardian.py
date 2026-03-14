"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/engine/guardian.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/guardian.py is deprecated. "
    "Use cobuilder.engine.guardian instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.engine.guardian import *  # noqa: F401,F403
