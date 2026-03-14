"""Environment variable helpers with ATTRACTOR_ → PIPELINE_ deprecation warnings."""

from __future__ import annotations

import os
import warnings


def _get_env(new_name: str, old_name: str, default: str = "") -> str:
    """Read env var with deprecation warning for old ATTRACTOR_ prefix."""
    if new_name in os.environ:
        return os.environ[new_name]
    if old_name in os.environ:
        warnings.warn(
            f"{old_name} is deprecated; use {new_name}",
            DeprecationWarning,
            stacklevel=2,
        )
        return os.environ[old_name]
    return default
