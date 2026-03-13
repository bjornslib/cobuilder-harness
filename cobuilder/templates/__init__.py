"""Template system for parameterized DOT pipeline generation.

Public API:
- :func:`instantiate_template` — Render a template with parameters.
- :func:`validate_constraints` — Check static constraints on a DOT file.
- :class:`Manifest` — Parsed template manifest.
- :class:`NodeStateMachine` — Per-node state transition constraints.
"""
from __future__ import annotations
