"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/attractor/guardian.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/guardian.py is deprecated. "
    "Use cobuilder.attractor.guardian instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.attractor.guardian import *  # noqa: F401,F403
