"""Template manifest parser — loads and validates manifest.yaml files.

A manifest defines:
- Template metadata (name, version, topology)
- Parameters with types, defaults, and validation rules
- Constraints (node_state_machine, path_constraint, topology_constraint, loop_constraint)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parameter models
# ---------------------------------------------------------------------------


@dataclass
class ParameterDef:
    """Definition of a single template parameter."""

    name: str
    type: str  # string | integer | boolean | list | object
    required: bool = True
    default: Any = None
    description: str = ""
    enum: list[str] | None = None
    min_length: int | None = None
    max_length: int | None = None
    item_schema: dict[str, Any] | None = None

    def validate_value(self, value: Any) -> list[str]:
        """Validate a value against this parameter definition. Returns errors."""
        errors: list[str] = []
        if value is None:
            if self.required:
                errors.append(f"Parameter '{self.name}' is required")
            return errors

        if self.type == "string" and not isinstance(value, str):
            errors.append(f"Parameter '{self.name}' must be a string, got {type(value).__name__}")
        elif self.type == "integer" and not isinstance(value, int):
            errors.append(f"Parameter '{self.name}' must be an integer, got {type(value).__name__}")
        elif self.type == "boolean" and not isinstance(value, bool):
            errors.append(f"Parameter '{self.name}' must be a boolean, got {type(value).__name__}")
        elif self.type == "list":
            if not isinstance(value, list):
                errors.append(f"Parameter '{self.name}' must be a list, got {type(value).__name__}")
            else:
                if self.min_length is not None and len(value) < self.min_length:
                    errors.append(
                        f"Parameter '{self.name}' must have at least {self.min_length} items"
                    )
                if self.max_length is not None and len(value) > self.max_length:
                    errors.append(
                        f"Parameter '{self.name}' must have at most {self.max_length} items"
                    )

        if self.enum is not None and isinstance(value, str) and value not in self.enum:
            errors.append(
                f"Parameter '{self.name}' must be one of {self.enum}, got '{value}'"
            )

        return errors


# ---------------------------------------------------------------------------
# Defaults models
# ---------------------------------------------------------------------------


@dataclass
class HandlerDefaults:
    """Default configuration for a specific handler type."""

    llm_profile: str | None = None

    # Future extensions can add more fields here (e.g., timeout, allowed_tools)


@dataclass
class Defaults:
    """Default configuration values for the template.

    Provides a 5-layer resolution for LLM configuration:
    1. Node's llm_profile attribute
    2. handler_defaults.{handler_type}.llm_profile
    3. defaults.llm_profile (this field)
    4. Environment variables (ANTHROPIC_MODEL, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL)
    5. Runner hardcoded defaults
    """

    llm_profile: str | None = None
    providers_file: str | None = None
    handler_defaults: dict[str, HandlerDefaults] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Constraint models
# ---------------------------------------------------------------------------


@dataclass
class StateMachineConstraint:
    """A node_state_machine constraint from the manifest."""

    name: str
    description: str = ""
    applies_to_shape: str = ""
    applies_to_handler: str | None = None
    states: list[str] = field(default_factory=list)
    transitions: list[dict[str, str]] = field(default_factory=list)
    initial: str = "pending"
    terminal: list[str] = field(default_factory=list)


@dataclass
class PathConstraint:
    """A path_constraint requiring certain shapes between source and target."""

    name: str
    description: str = ""
    from_shape: str = ""
    must_pass_through: list[str] = field(default_factory=list)
    before_reaching: list[str] = field(default_factory=list)


@dataclass
class TopologyConstraint:
    """A topology_constraint requiring structural pairing."""

    name: str
    description: str = ""
    every_node_shape: str = ""
    every_node_handler: str | None = None
    must_have_downstream_shape: str = ""
    max_hops: int = 20


@dataclass
class LoopConstraint:
    """A loop_constraint setting visit bounds."""

    name: str
    description: str = ""
    max_per_node_visits: int = 4
    max_pipeline_visits: int = 50


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


@dataclass
class Manifest:
    """Parsed template manifest with metadata, parameters, constraints, and defaults."""

    name: str
    version: str = "1.0"
    description: str = ""
    topology: str = "linear"  # linear | parallel | cyclic | meta
    min_nodes: int | None = None
    max_nodes: int | None = None
    parameters: dict[str, ParameterDef] = field(default_factory=dict)
    defaults: Defaults = field(default_factory=Defaults)
    state_machine_constraints: list[StateMachineConstraint] = field(default_factory=list)
    path_constraints: list[PathConstraint] = field(default_factory=list)
    topology_constraints: list[TopologyConstraint] = field(default_factory=list)
    loop_constraints: list[LoopConstraint] = field(default_factory=list)

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate all parameters against their definitions. Returns errors."""
        errors: list[str] = []
        for name, param_def in self.parameters.items():
            value = params.get(name, param_def.default)
            errors.extend(param_def.validate_value(value))
        return errors

    def resolve_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Resolve parameters with defaults applied."""
        resolved = {}
        for name, param_def in self.parameters.items():
            if name in params:
                resolved[name] = params[name]
            elif param_def.default is not None:
                resolved[name] = param_def.default
            elif not param_def.required:
                resolved[name] = None
        # Pass through any extra params not in the manifest
        for k, v in params.items():
            if k not in resolved:
                resolved[k] = v
        return resolved


def _parse_parameter(name: str, raw: dict[str, Any]) -> ParameterDef:
    """Parse a single parameter definition from YAML."""
    return ParameterDef(
        name=name,
        type=raw.get("type", "string"),
        required=raw.get("required", True),
        default=raw.get("default"),
        description=raw.get("description", ""),
        enum=raw.get("enum"),
        min_length=raw.get("min_length"),
        max_length=raw.get("max_length"),
        item_schema=raw.get("item_schema"),
    )


def _parse_constraint(name: str, raw: dict[str, Any]) -> Any:
    """Parse a constraint definition from YAML into the appropriate model."""
    ctype = raw.get("type", "")

    if ctype == "node_state_machine":
        applies_to = raw.get("applies_to", {})
        return StateMachineConstraint(
            name=name,
            description=raw.get("description", ""),
            applies_to_shape=applies_to.get("shape", ""),
            applies_to_handler=applies_to.get("handler"),
            states=raw.get("states", []),
            transitions=raw.get("transitions", []),
            initial=raw.get("initial", "pending"),
            terminal=raw.get("terminal", []),
        )

    elif ctype == "path_constraint":
        rule = raw.get("rule", {})
        return PathConstraint(
            name=name,
            description=raw.get("description", ""),
            from_shape=rule.get("from_shape", ""),
            must_pass_through=rule.get("must_pass_through", []),
            before_reaching=rule.get("before_reaching", []),
        )

    elif ctype == "topology_constraint":
        rule = raw.get("rule", {})
        every_node = rule.get("every_node", {})
        must_have = rule.get("must_have_downstream", {})
        return TopologyConstraint(
            name=name,
            description=raw.get("description", ""),
            every_node_shape=every_node.get("shape", ""),
            every_node_handler=every_node.get("handler"),
            must_have_downstream_shape=must_have if isinstance(must_have, str)
            else must_have.get("shape", ""),
            max_hops=rule.get("max_hops", 20) if isinstance(must_have, dict) else 20,
        )

    elif ctype == "loop_constraint":
        rule = raw.get("rule", {})
        return LoopConstraint(
            name=name,
            description=raw.get("description", ""),
            max_per_node_visits=rule.get("max_per_node_visits", 4),
            max_pipeline_visits=rule.get("max_pipeline_visits", 50),
        )

    else:
        logger.warning("Unknown constraint type '%s' in constraint '%s'", ctype, name)
        return None


def _parse_defaults(raw: dict[str, Any]) -> Defaults:
    """Parse the defaults section from manifest YAML.

    Expected structure:
        defaults:
          llm_profile: "anthropic-fast"
          providers_file: "providers.yaml"
          handler_defaults:
            codergen:
              llm_profile: "anthropic-smart"
            research:
              llm_profile: "anthropic-fast"
    """
    handler_defaults: dict[str, HandlerDefaults] = {}

    # Parse handler_defaults if present
    handler_defaults_raw = raw.get("handler_defaults", {})
    if isinstance(handler_defaults_raw, dict):
        for handler_type, hd_config in handler_defaults_raw.items():
            if isinstance(hd_config, dict):
                handler_defaults[handler_type] = HandlerDefaults(
                    llm_profile=hd_config.get("llm_profile"),
                )
            elif isinstance(hd_config, str):
                # Shorthand: handler_defaults: {codergen: "anthropic-smart"}
                handler_defaults[handler_type] = HandlerDefaults(
                    llm_profile=hd_config,
                )

    return Defaults(
        llm_profile=raw.get("llm_profile"),
        providers_file=raw.get("providers_file"),
        handler_defaults=handler_defaults,
    )


def load_manifest(manifest_path: str | Path) -> Manifest:
    """Load and parse a manifest.yaml file into a Manifest object.

    Args:
        manifest_path: Path to the manifest.yaml file.

    Returns:
        Parsed Manifest.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the YAML is invalid or missing required fields.
    """
    import yaml

    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Manifest must be a YAML mapping, got {type(raw).__name__}")

    # Template metadata
    tmpl = raw.get("template", {})
    name = tmpl.get("name", path.parent.name)
    if not name:
        raise ValueError("Manifest must specify template.name")

    # Parameters
    parameters = {}
    for pname, praw in raw.get("parameters", {}).items():
        parameters[pname] = _parse_parameter(pname, praw if isinstance(praw, dict) else {})

    # Constraints
    sm_constraints: list[StateMachineConstraint] = []
    path_constraints: list[PathConstraint] = []
    topo_constraints: list[TopologyConstraint] = []
    loop_constraints: list[LoopConstraint] = []

    for cname, craw in raw.get("constraints", {}).items():
        if not isinstance(craw, dict):
            continue
        parsed = _parse_constraint(cname, craw)
        if isinstance(parsed, StateMachineConstraint):
            sm_constraints.append(parsed)
        elif isinstance(parsed, PathConstraint):
            path_constraints.append(parsed)
        elif isinstance(parsed, TopologyConstraint):
            topo_constraints.append(parsed)
        elif isinstance(parsed, LoopConstraint):
            loop_constraints.append(parsed)

    # Defaults
    defaults_raw = raw.get("defaults", {})
    defaults = _parse_defaults(defaults_raw) if isinstance(defaults_raw, dict) else Defaults()

    return Manifest(
        name=name,
        version=tmpl.get("version", "1.0"),
        description=tmpl.get("description", ""),
        topology=tmpl.get("topology", "linear"),
        min_nodes=tmpl.get("min_nodes"),
        max_nodes=tmpl.get("max_nodes"),
        parameters=parameters,
        defaults=defaults,
        state_machine_constraints=sm_constraints,
        path_constraints=path_constraints,
        topology_constraints=topo_constraints,
        loop_constraints=loop_constraints,
    )


def resolve_manifest_for_graph(
    graph_attrs: dict[str, Any],
    templates_dir: str | Path | None = None,
) -> Manifest | None:
    """Resolve a manifest for a DOT file based on its _template attribute.

    Args:
        graph_attrs: Graph-level attributes from the parsed DOT file.
        templates_dir: Directory containing template directories. Defaults to
                       .claude/attractor/templates/ relative to cwd.

    Returns:
        Parsed Manifest if _template attribute is present and manifest exists,
        None otherwise.
    """
    template_name = graph_attrs.get("_template", "")
    if not template_name:
        return None

    if templates_dir is None:
        templates_dir = Path.cwd() / ".claude" / "attractor" / "templates"
    else:
        templates_dir = Path(templates_dir)

    manifest_path = templates_dir / template_name / "manifest.yaml"
    if not manifest_path.exists():
        logger.warning(
            "Template '%s' referenced in DOT but manifest not found at %s",
            template_name,
            manifest_path,
        )
        return None

    try:
        return load_manifest(manifest_path)
    except Exception as exc:
        logger.warning("Failed to load manifest for template '%s': %s", template_name, exc)
        return None
