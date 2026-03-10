"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/attractor/dispatch_worker.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/dispatch_worker.py is deprecated. "
    "Use cobuilder.attractor.dispatch_worker instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.attractor.dispatch_worker import *  # noqa: F401,F403
