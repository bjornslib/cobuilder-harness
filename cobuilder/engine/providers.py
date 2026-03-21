"""LLM provider profile management for per-node model configuration.

This module implements Epic 1 (PRD-COBUILDER-UPGRADE-001): Per-node LLM configuration
via named profiles in providers.yaml.

## Overview

LLM configuration uses **named profiles** defined in `providers.yaml`. DOT nodes
reference profiles by name; the runner resolves profile keys to Anthropic SDK
equivalents at dispatch time.

## Resolution Order (5-layer, first non-null wins)

1. **Node `llm_profile`** — profile on the DOT node → look up in `providers.yaml`
2. **Handler defaults** — `defaults.handler_defaults.{handler_type}.llm_profile` in manifest
3. **Manifest defaults** — `defaults.llm_profile` in manifest
4. **Environment variables** — `ANTHROPIC_MODEL`, `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`
5. **Runner defaults** — hardcoded fallback in runner

## Profile Translation

All profile keys translate to their Anthropic SDK equivalents at dispatch time:

| Profile Key | Anthropic SDK Equivalent | Environment Variable |
|-------------|--------------------------|---------------------|
| `model` | `model` in `ClaudeCodeOptions` | `ANTHROPIC_MODEL` |
| `api_key` | `ANTHROPIC_API_KEY` in worker env | `ANTHROPIC_API_KEY` |
| `base_url` | `ANTHROPIC_BASE_URL` in worker env | `ANTHROPIC_BASE_URL` |

Any provider speaking the Anthropic API protocol works transparently.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pattern for environment variable references: $VAR_NAME or ${VAR_NAME}
_ENV_VAR_PATTERN = re.compile(r"^\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$")

# Default providers file name (relative to project root or manifest directory)
DEFAULT_PROVIDERS_FILE = "providers.yaml"

# Runner-level defaults (layer 5)
RUNNER_DEFAULT_MODEL = "claude-sonnet-4-6"
RUNNER_DEFAULT_BASE_URL = "https://api.anthropic.com"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class LLMProfile:
    """A named LLM configuration profile.

    Profile keys translate to Anthropic SDK equivalents at dispatch time.
    Environment variable references ($VAR or ${VAR}) are resolved at load time.

    Attributes:
        name: Profile identifier (e.g., "anthropic-fast", "openrouter-smart").
        model: Model identifier (e.g., "claude-haiku-4-5-20251001").
        api_key: API key, may contain $ENV_VAR reference.
        base_url: API base URL (default: https://api.anthropic.com).
        extra: Additional provider-specific options.
    """

    name: str
    model: str
    api_key: str | None = None
    base_url: str = "https://api.anthropic.com"
    extra: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Sanitize api_key in repr to prevent secret leakage."""
        api_key_display = "***REDACTED***" if self.api_key else None
        return (
            f"LLMProfile(name={self.name!r}, model={self.model!r}, "
            f"api_key={api_key_display}, base_url={self.base_url!r})"
        )


@dataclass
class ResolvedLLMConfig:
    """Fully resolved LLM configuration ready for SDK dispatch.

    All environment variables have been resolved; no secrets remain.
    This is the internal representation used during dispatch.

    Attributes:
        model: Model identifier for Anthropic SDK.
        api_key: Resolved API key (or None to use env default).
        base_url: API base URL.
        profile_name: Source profile name (for logging/debugging).
        resolution_source: Which layer provided the config (for debugging).
    """

    model: str
    api_key: str | None = None
    base_url: str = RUNNER_DEFAULT_BASE_URL
    profile_name: str | None = None
    resolution_source: str = "unknown"

    def __repr__(self) -> str:
        """Sanitize api_key in repr to prevent secret leakage."""
        api_key_display = "***REDACTED***" if self.api_key else None
        return (
            f"ResolvedLLMConfig(model={self.model!r}, api_key={api_key_display}, "
            f"base_url={self.base_url!r}, profile_name={self.profile_name!r}, "
            f"resolution_source={self.resolution_source!r})"
        )

    def to_env_dict(self) -> dict[str, str]:
        """Convert to environment variables for worker process.

        Returns:
            Dict with ANTHROPIC_MODEL, ANTHROPIC_API_KEY (if set),
            and ANTHROPIC_BASE_URL (if non-default).
        """
        env: dict[str, str] = {"ANTHROPIC_MODEL": self.model}
        if self.api_key:
            env["ANTHROPIC_API_KEY"] = self.api_key
        if self.base_url != RUNNER_DEFAULT_BASE_URL:
            env["ANTHROPIC_BASE_URL"] = self.base_url
        return env


class ProvidersFile:
    """Loader and container for providers.yaml profiles.

    Example providers.yaml:

        profiles:
          anthropic-fast:
            model: claude-haiku-4-5-20251001
            api_key: $ANTHROPIC_API_KEY
            base_url: https://api.anthropic.com

          anthropic-smart:
            model: claude-sonnet-4-6
            api_key: $ANTHROPIC_API_KEY

          openrouter-smart:
            model: anthropic/claude-sonnet-4-6
            api_key: $OPENROUTER_API_KEY
            base_url: https://openrouter.ai/api/v1
    """

    def __init__(
        self,
        profiles: dict[str, LLMProfile],
        source_path: str | None = None,
        default_profile: str | None = None,
    ):
        """Initialize with pre-parsed profiles.

        Args:
            profiles: Dict mapping profile name → LLMProfile.
            source_path: Path to the source file (for error messages).
            default_profile: Name of the default profile to use when no
                llm_profile is specified on a node and no manifest defaults apply.
        """
        self._profiles = profiles
        self._source_path = source_path
        self.default_profile = default_profile

    def get(self, name: str) -> LLMProfile | None:
        """Get a profile by name.

        Args:
            name: Profile name from DOT node's llm_profile attribute.

        Returns:
            LLMProfile if found, None otherwise.
        """
        return self._profiles.get(name)

    def list_profiles(self) -> list[str]:
        """List all available profile names."""
        return list(self._profiles.keys())

    @classmethod
    def from_file(cls, path: str | Path) -> "ProvidersFile":
        """Load profiles from a providers.yaml file.

        Args:
            path: Path to providers.yaml file.

        Returns:
            ProvidersFile instance with loaded profiles.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the YAML is invalid.
        """
        import yaml

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Providers file not found: {path}")

        raw = yaml.safe_load(path.read_text())
        if not isinstance(raw, dict):
            raise ValueError(
                f"Providers file must be a YAML mapping, got {type(raw).__name__}"
            )

        profiles_raw = raw.get("profiles", {})
        if not isinstance(profiles_raw, dict):
            raise ValueError(
                f"'profiles' must be a mapping, got {type(profiles_raw).__name__}"
            )

        profiles: dict[str, LLMProfile] = {}
        for name, config in profiles_raw.items():
            if not isinstance(config, dict):
                logger.warning(
                    "Profile '%s' is not a mapping, skipping", name
                )
                continue

            profile = LLMProfile(
                name=name,
                model=config.get("model", ""),
                api_key=config.get("api_key"),
                base_url=config.get("base_url", "https://api.anthropic.com"),
                extra={k: v for k, v in config.items()
                       if k not in ("model", "api_key", "base_url")},
            )

            if not profile.model:
                logger.warning("Profile '%s' has no model, skipping", name)
                continue

            profiles[name] = profile

        default_profile = raw.get("default_profile")
        if default_profile and default_profile not in profiles:
            logger.warning(
                "default_profile '%s' not found in profiles, ignoring",
                default_profile,
            )
            default_profile = None

        logger.info(
            "Loaded %d LLM profile(s) from %s (default=%s)",
            len(profiles),
            path,
            default_profile or "<none>",
        )
        return cls(profiles, source_path=str(path), default_profile=default_profile)

    @classmethod
    def empty(cls) -> "ProvidersFile":
        """Create an empty providers file (no profiles loaded)."""
        return cls({}, source_path=None)


# ---------------------------------------------------------------------------
# Environment variable resolution
# ---------------------------------------------------------------------------


def resolve_env_var(value: str | None) -> str | None:
    """Resolve an environment variable reference.

    Supports $VAR_NAME and ${VAR_NAME} syntax. If the value is not an
    env var reference, returns it unchanged.

    Args:
        value: String value that may contain $VAR reference.

    Returns:
        Resolved value, or None if the env var is not set.
    """
    if value is None:
        return None

    match = _ENV_VAR_PATTERN.match(value)
    if match:
        var_name = match.group(1)
        return os.environ.get(var_name)

    return value


def sanitize_for_logging(value: str | None) -> str:
    """Sanitize a potentially secret value for logging.

    Returns a placeholder if the value looks like a secret, otherwise
    returns the value unchanged.

    Args:
        value: Value to sanitize.

    Returns:
        Sanitized string safe for logging.
    """
    if value is None:
        return "<none>"

    # Heuristic: if it looks like an API key (long alphanumeric), redact
    if len(value) > 20 and value.replace("-", "").replace("_", "").isalnum():
        return "***REDACTED***"

    return value


# ---------------------------------------------------------------------------
# Resolution functions
# ---------------------------------------------------------------------------


def resolve_llm_config(
    node_llm_profile: str | None,
    handler_type: str | None,
    providers: ProvidersFile,
    manifest_defaults: Any = None,
    node_id: str = "",
) -> ResolvedLLMConfig:
    """Resolve LLM configuration using the 5-layer resolution order.

    Resolution order (first non-null wins):
    1. Node's llm_profile attribute → look up in providers
    2. handler_defaults.{handler_type}.llm_profile from manifest
    3. defaults.llm_profile from manifest
    4. Environment variables (ANTHROPIC_MODEL, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL)
    5. Runner defaults (hardcoded)

    Args:
        node_llm_profile: Value of node's llm_profile attribute (may be None).
        handler_type: Handler type for the node (e.g., "codergen", "research").
        providers: Loaded ProvidersFile with profile definitions.
        manifest_defaults: Manifest.defaults object (has llm_profile and handler_defaults).
        node_id: Node ID for logging context.

    Returns:
        ResolvedLLMConfig with fully resolved values.
    """
    # Layer 1: Node's llm_profile → providers.yaml
    if node_llm_profile:
        profile = providers.get(node_llm_profile)
        if profile:
            resolved_api_key = resolve_env_var(profile.api_key)
            logger.debug(
                "Node '%s' using profile '%s' (model=%s, base_url=%s)",
                node_id,
                node_llm_profile,
                profile.model,
                profile.base_url,
            )
            return ResolvedLLMConfig(
                model=profile.model,
                api_key=resolved_api_key,
                base_url=profile.base_url,
                profile_name=node_llm_profile,
                resolution_source="node_profile",
            )
        else:
            logger.warning(
                "Node '%s' references unknown profile '%s', falling back",
                node_id,
                node_llm_profile,
            )

    # Layer 2: handler_defaults.{handler_type}.llm_profile
    if handler_type and manifest_defaults:
        handler_defaults = getattr(manifest_defaults, "handler_defaults", {})
        if handler_defaults and handler_type in handler_defaults:
            hd = handler_defaults[handler_type]
            handler_profile_name = getattr(hd, "llm_profile", None)
            if handler_profile_name:
                profile = providers.get(handler_profile_name)
                if profile:
                    resolved_api_key = resolve_env_var(profile.api_key)
                    logger.debug(
                        "Node '%s' using handler default profile '%s' (handler=%s)",
                        node_id,
                        handler_profile_name,
                        handler_type,
                    )
                    return ResolvedLLMConfig(
                        model=profile.model,
                        api_key=resolved_api_key,
                        base_url=profile.base_url,
                        profile_name=handler_profile_name,
                        resolution_source="handler_default",
                    )

    # Layer 3: manifest defaults.llm_profile
    if manifest_defaults:
        manifest_profile_name = getattr(manifest_defaults, "llm_profile", None)
        if manifest_profile_name:
            profile = providers.get(manifest_profile_name)
            if profile:
                resolved_api_key = resolve_env_var(profile.api_key)
                logger.debug(
                    "Node '%s' using manifest default profile '%s'",
                    node_id,
                    manifest_profile_name,
                )
                return ResolvedLLMConfig(
                    model=profile.model,
                    api_key=resolved_api_key,
                    base_url=profile.base_url,
                    profile_name=manifest_profile_name,
                    resolution_source="manifest_default",
                )

    # Layer 3.5: providers.yaml default_profile
    if providers.default_profile:
        profile = providers.get(providers.default_profile)
        if profile:
            resolved_api_key = resolve_env_var(profile.api_key)
            logger.debug(
                "Node '%s' using providers.yaml default_profile '%s' (model=%s)",
                node_id,
                providers.default_profile,
                profile.model,
            )
            return ResolvedLLMConfig(
                model=profile.model,
                api_key=resolved_api_key,
                base_url=profile.base_url,
                profile_name=providers.default_profile,
                resolution_source="providers_default",
            )

    # Layer 4: Environment variables
    env_model = os.environ.get("ANTHROPIC_MODEL")
    env_api_key = os.environ.get("ANTHROPIC_API_KEY")
    env_base_url = os.environ.get("ANTHROPIC_BASE_URL")

    if env_model:
        logger.debug(
            "Node '%s' using environment variables (model=%s)",
            node_id,
            env_model,
        )
        return ResolvedLLMConfig(
            model=env_model,
            api_key=env_api_key,
            base_url=env_base_url or RUNNER_DEFAULT_BASE_URL,
            profile_name=None,
            resolution_source="environment",
        )

    # Layer 5: Runner defaults
    logger.debug(
        "Node '%s' using runner defaults (model=%s)",
        node_id,
        RUNNER_DEFAULT_MODEL,
    )
    return ResolvedLLMConfig(
        model=RUNNER_DEFAULT_MODEL,
        api_key=None,  # Will use ANTHROPIC_API_KEY from env at dispatch time
        base_url=RUNNER_DEFAULT_BASE_URL,
        profile_name=None,
        resolution_source="runner_default",
    )


def load_providers_file(
    providers_file_path: str | None,
    manifest_dir: str | Path | None = None,
    project_root: str | Path | None = None,
) -> ProvidersFile:
    """Load providers.yaml from the appropriate location.

    Search order:
    1. Explicit path provided
    2. cobuilder/engine/providers.yaml (next to providers.py itself)
    3. manifest_dir/providers.yaml (next to manifest.yaml)
    4. project_root/providers.yaml (repo root)
    5. Return empty ProvidersFile if not found

    Args:
        providers_file_path: Explicit path to providers.yaml (may be None).
        manifest_dir: Directory containing manifest.yaml.
        project_root: Project root directory.

    Returns:
        Loaded ProvidersFile, or empty ProvidersFile if not found.
    """
    # Layer 1: Explicit path
    if providers_file_path:
        path = Path(providers_file_path)
        if path.exists():
            return ProvidersFile.from_file(path)
        logger.warning(
            "Providers file specified but not found: %s",
            providers_file_path,
        )
        return ProvidersFile.empty()

    # Layer 2: cobuilder/engine/providers.yaml (next to this file)
    engine_path = Path(__file__).parent / DEFAULT_PROVIDERS_FILE
    if engine_path.exists():
        return ProvidersFile.from_file(engine_path)

    # Layer 3: manifest_dir/providers.yaml
    if manifest_dir:
        manifest_path = Path(manifest_dir) / DEFAULT_PROVIDERS_FILE
        if manifest_path.exists():
            return ProvidersFile.from_file(manifest_path)

    # Layer 4: project_root/providers.yaml
    if project_root:
        root_path = Path(project_root) / DEFAULT_PROVIDERS_FILE
        if root_path.exists():
            return ProvidersFile.from_file(root_path)

    # Layer 5: Not found, return empty
    logger.debug("No providers.yaml found, using environment defaults")
    return ProvidersFile.empty()


# ---------------------------------------------------------------------------
# Integration helper
# ---------------------------------------------------------------------------


def get_llm_config_for_node(
    node: Any,
    graph: Any = None,  # noqa: ARG001 — reserved for future graph-level config
    providers: ProvidersFile | None = None,
    manifest: Any = None,
) -> ResolvedLLMConfig:
    """Get resolved LLM config for a node, extracting all necessary attributes.

    This is a convenience function that extracts node.llm_profile and node.handler_type
    before calling resolve_llm_config().

    Args:
        node: Node object with llm_profile and handler_type attributes/properties.
        graph: Graph object (reserved for future graph-level config).
        providers: Loaded ProvidersFile (defaults to empty if not provided).
        manifest: Optional Manifest object with defaults.

    Returns:
        ResolvedLLMConfig ready for dispatch.
    """
    node_llm_profile = getattr(node, "attrs", {}).get("llm_profile")
    if not node_llm_profile:
        # Try property if attrs doesn't have it
        node_llm_profile = getattr(node, "llm_profile", None)

    handler_type = getattr(node, "handler_type", None)
    manifest_defaults = getattr(manifest, "defaults", None) if manifest else None
    node_id = getattr(node, "id", "unknown")

    # Use empty providers if not provided
    if providers is None:
        providers = ProvidersFile.empty()

    return resolve_llm_config(
        node_llm_profile=node_llm_profile,
        handler_type=handler_type,
        providers=providers,
        manifest_defaults=manifest_defaults,
        node_id=node_id,
    )