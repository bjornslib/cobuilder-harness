"""Template instantiator — renders Jinja2 DOT templates with parameters.

Loads a template directory (template.dot.j2 + manifest.yaml), validates
parameters, renders the Jinja2 template, and optionally runs static
constraint validation on the output.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from cobuilder.templates.manifest import Manifest, load_manifest

logger = logging.getLogger(__name__)

# Default templates directory
_DEFAULT_TEMPLATES_DIR = ".claude/attractor/templates"


def _slugify(value: str) -> str:
    """Convert a string to a DOT-safe identifier (lowercase, underscores)."""
    value = str(value).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = value.strip("_")
    return value or "unnamed"


def _get_jinja_env(template_dir: Path) -> Any:
    """Create a Jinja2 environment for the template directory."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape([]),  # DOT files, no HTML escaping
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # Register custom filters
    env.filters["slugify"] = _slugify
    return env


def list_templates(templates_dir: str | Path | None = None) -> list[dict[str, str]]:
    """List all available templates.

    Args:
        templates_dir: Directory containing template directories.

    Returns:
        List of dicts with 'name', 'version', 'description', 'topology'.
    """
    if templates_dir is None:
        templates_dir = Path.cwd() / _DEFAULT_TEMPLATES_DIR
    else:
        templates_dir = Path(templates_dir)

    if not templates_dir.exists():
        return []

    results = []
    for child in sorted(templates_dir.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.yaml"
        if manifest_path.exists():
            try:
                m = load_manifest(manifest_path)
                results.append({
                    "name": m.name,
                    "version": m.version,
                    "description": m.description,
                    "topology": m.topology,
                })
            except Exception as exc:
                logger.warning("Failed to load template '%s': %s", child.name, exc)

    return results


def instantiate_template(
    template_name: str,
    params: dict[str, Any],
    *,
    output_path: str | Path | None = None,
    templates_dir: str | Path | None = None,
    validate: bool = True,
) -> str:
    """Instantiate a template with parameters and return the rendered DOT.

    Args:
        template_name: Name of the template directory.
        params: Parameter values to fill into the template.
        output_path: Optional path to write the rendered DOT file.
        templates_dir: Directory containing template directories.
        validate: Whether to run static constraint validation.

    Returns:
        Rendered DOT string.

    Raises:
        FileNotFoundError: Template directory or files not found.
        ValueError: Parameter validation fails or constraint violation.
    """
    if templates_dir is None:
        templates_dir = Path.cwd() / _DEFAULT_TEMPLATES_DIR
    else:
        templates_dir = Path(templates_dir)

    template_dir = templates_dir / template_name
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # Load manifest
    manifest_path = template_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)

    # Validate parameters
    errors = manifest.validate_params(params)
    if errors:
        raise ValueError(
            f"Parameter validation failed for template '{template_name}':\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    # Resolve parameters with defaults
    resolved = manifest.resolve_params(params)

    # Find template file
    template_file = template_dir / "template.dot.j2"
    if not template_file.exists():
        raise FileNotFoundError(f"Template file not found: {template_file}")

    # Render
    env = _get_jinja_env(template_dir)
    template = env.get_template("template.dot.j2")
    rendered = template.render(**resolved)

    # Run static constraint validation if requested
    if validate and (manifest.path_constraints or manifest.topology_constraints):
        from cobuilder.templates.constraints import validate_static_constraints
        constraint_errors = validate_static_constraints(rendered, manifest)
        if constraint_errors:
            raise ValueError(
                f"Static constraint validation failed for template '{template_name}':\n"
                + "\n".join(f"  - {e}" for e in constraint_errors)
            )

    # Write output file if requested
    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered)
        logger.info("Template '%s' instantiated to %s", template_name, out)

    return rendered
