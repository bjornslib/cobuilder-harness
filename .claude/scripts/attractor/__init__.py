"""Backward-compatibility shim package. Expires 2026-04-11.

All real code has moved to cobuilder.attractor.
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/ is deprecated. "
    "Use cobuilder.attractor instead.",
    DeprecationWarning,
    stacklevel=2,
)
