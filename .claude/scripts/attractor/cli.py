"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/attractor/cli.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/cli.py is deprecated. "
    "Use cobuilder.attractor.cli instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.attractor.cli import *  # noqa: F401,F403
