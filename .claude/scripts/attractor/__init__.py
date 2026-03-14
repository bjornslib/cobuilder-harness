"""Backward-compatibility shim package. Expires 2026-04-11.

All real code has moved to cobuilder.engine.
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/ is deprecated. "
    "Use cobuilder.engine instead.",
    DeprecationWarning,
    stacklevel=2,
)
