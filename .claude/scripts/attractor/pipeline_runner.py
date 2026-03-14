"""30-day backward-compatibility shim. Expires 2026-04-11.
Real code lives at cobuilder/engine/pipeline_runner.py
"""
import warnings

warnings.warn(
    "Importing from .claude/scripts/attractor/pipeline_runner.py is deprecated. "
    "Use cobuilder.engine.pipeline_runner instead.",
    DeprecationWarning,
    stacklevel=2,
)
from cobuilder.engine.pipeline_runner import *  # noqa: F401,F403
