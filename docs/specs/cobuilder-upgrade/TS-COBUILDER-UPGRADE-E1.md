---
title: "TS-E1: Per-Node LLM Configuration via Named Profiles"
ts_id: TS-COBUILDER-UPGRADE-E1
prd_ref: PRD-COBUILDER-UPGRADE-001
epic: E1
status: draft
type: reference
created: 2026-03-14
last_verified: 2026-03-14
grade: authoritative
---

# TS-COBUILDER-UPGRADE-E1: Per-Node LLM Configuration via Named Profiles

## 1. Overview

Epic 1 replaces the current single-model `ANTHROPIC_MODEL` environment variable lookup with a named profile system. DOT nodes reference profiles by name; the runner resolves profile keys to Anthropic SDK equivalents at dispatch time using a 5-layer fallback chain.

**Problem addressed**: All workers currently use the same model, API key, and base URL. `ANTHROPIC_MODEL` (or `PIPELINE_WORKER_MODEL`) is read once from the environment and applied identically to every node dispatch. There is no way to use Haiku for cheap research nodes and Sonnet/Opus for codergen nodes within a single pipeline, and no way to route traffic through OpenRouter or a local provider.

**Goal**: Enable a mixed-model pipeline — for example, Haiku for `research` nodes and Sonnet for `codergen` nodes — by referencing named profiles from `providers.yaml` on each DOT node. Profile keys translate to Anthropic SDK equivalents at dispatch time. Credentials never appear in logs.

**Depends on**: E0 (template system merge). The manifest schema extensions for `handler_defaults` are defined in the template manifest from E0. E1 consumes and extends that schema.

---

## 2. File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `cobuilder/engine/providers.py` | **Create** | Profile loader, resolver, translator, env-var expander |
| `tests/engine/test_providers.py` | **Create** | Unit tests for all providers.py functions |
| `cobuilder/attractor/pipeline_runner.py` | **Modify** | Replace `ANTHROPIC_MODEL` lookup with `_resolve_llm_config()` call |
| `cobuilder/engine/runner.py` | **Modify** | Pass `llm_config` through to handler dispatch; add `initial_context` injection point |
| `providers.yaml` | **Create** | Default profile definitions at repo root (tracked) |
| `manifest.yaml` (template schema) | **Modify** | Add `defaults.llm_profile` and `defaults.handler_defaults.{type}.llm_profile` |

The `providers.yaml` at repo root is the **default** location. A manifest can override the path via `defaults.providers_file`. Workers never see `providers.yaml` — they only see resolved env vars injected at dispatch time.

---

## 3. providers.yaml Schema

### 3.1 File Location and Discovery

The loader searches for `providers.yaml` in this priority order:

1. Path from `manifest.yaml` `defaults.providers_file` field (if present)
2. Directory containing the active `.dot` pipeline file
3. Repo root (resolved via `git rev-parse --show-toplevel`)
4. Built-in defaults (Anthropic-only, Haiku model, `$ANTHROPIC_API_KEY`)

### 3.2 YAML Structure

```yaml
# providers.yaml
# Lives alongside manifest.yaml or at repo root.
# Profile names are arbitrary strings. Use kebab-case by convention.
# Values starting with $ are treated as environment variable references.

profiles:
  anthropic-fast:
    model: claude-haiku-4-5-20251001
    api_key: $ANTHROPIC_API_KEY          # Resolved from os.environ at dispatch time
    base_url: https://api.anthropic.com

  anthropic-smart:
    model: claude-sonnet-4-5-20250514
    api_key: $ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com

  anthropic-opus:
    model: claude-opus-4-6
    api_key: $ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com

  openrouter-smart:
    model: anthropic/claude-sonnet-4-5
    api_key: $OPENROUTER_API_KEY
    base_url: https://openrouter.ai/api/v1

  openrouter-fast:
    model: anthropic/claude-haiku-4-5
    api_key: $OPENROUTER_API_KEY
    base_url: https://openrouter.ai/api/v1
```

### 3.3 JSON Schema Validation Rules

```python
PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {
            "type": "string",
            "minLength": 1,
            "description": "Model identifier — passed directly to ClaudeCodeOptions.model"
        },
        "api_key": {
            "type": "string",
            "minLength": 1,
            "description": "API key or $ENV_VAR reference. Never logged after resolution."
        },
        "base_url": {
            "type": "string",
            "format": "uri",
            "description": "Base URL for the API endpoint. Must be https://."
        },
    },
    "required": ["model"],        # api_key and base_url are optional (fall through to env)
    "additionalProperties": False,
}

PROVIDERS_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "profiles": {
            "type": "object",
            "patternProperties": {
                # Profile names: kebab-case recommended but not enforced
                "^[a-zA-Z0-9][a-zA-Z0-9_-]*$": PROFILE_SCHEMA
            },
            "additionalProperties": False,
        }
    },
    "required": ["profiles"],
    "additionalProperties": False,
}
```

**Validation rules**:
- `model` is the only required field per profile. A profile with only `model` is valid; `api_key` and `base_url` will fall through to env vars.
- Profile names must match `^[a-zA-Z0-9][a-zA-Z0-9_-]*$`.
- `base_url` must begin with `https://`. The loader raises `ProfileValidationError` if it starts with `http://`.
- Unknown top-level keys in `providers.yaml` raise `ProfileValidationError`.
- A profile referenced by a DOT node that does not exist in `providers.yaml` raises `UnknownProfileError` at dispatch time (not at parse time).

### 3.4 Env Var Reference Syntax

Any profile value starting with `$` is an env var reference:

```
$VARNAME         → os.environ["VARNAME"]
${VARNAME}       → os.environ["VARNAME"]   (alternative syntax, both supported)
```

Resolution is **lazy**: env vars are resolved at dispatch time (when `_translate_profile()` is called), not at file load time. This allows profiles to be loaded at startup even when some keys are not yet set in the environment.

If the referenced env var is not set and the profile field is `api_key`, the resolver falls through to the next layer (env var fallback). If the env var is not set and the profile field is `model`, a `MissingEnvVarError` is raised at dispatch time.

---

## 4. `_resolve_llm_config()` Algorithm

### 4.1 Data Types

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class LLMConfig:
    """Resolved, pre-translation LLM configuration for a single node dispatch."""
    model: str
    api_key: Optional[str] = None   # None = use ANTHROPIC_API_KEY from env
    base_url: Optional[str] = None  # None = use default Anthropic endpoint
    profile_name: Optional[str] = None  # For logging/tracing only

@dataclass
class ResolvedEnv:
    """Translated config ready to inject into worker process environment."""
    model: str
    env_overrides: dict[str, str]   # ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL
```

### 4.2 Five-Layer Resolution

The resolution order is "first non-null wins". Each layer is attempted in sequence; the first layer that returns a complete `LLMConfig` wins. Partial resolution is not supported — a layer either provides a full profile name (which is then looked up) or passes through to the next layer.

```
Layer 1: node.llm_profile
    → DOT node attribute: llm_profile="anthropic-smart"
    → Look up profile name in providers.yaml
    → If found: use that profile's values
    → If not found: raise UnknownProfileError immediately (fail fast)
    → If attribute absent: fall through to Layer 2

Layer 2: handler_defaults (from manifest)
    → manifest.defaults.handler_defaults.{handler_type}.llm_profile
    → handler_type comes from node attribute: handler="codergen"
    → If handler_type key exists and has llm_profile: look up in providers.yaml
    → If absent: fall through to Layer 3

Layer 3: manifest defaults
    → manifest.defaults.llm_profile
    → If present: look up profile name in providers.yaml
    → If absent: fall through to Layer 4

Layer 4: environment variables
    → ANTHROPIC_MODEL       → model
    → ANTHROPIC_API_KEY     → api_key
    → ANTHROPIC_BASE_URL    → base_url
    → Each key is independent; a partial env config is valid

Layer 5: runner defaults (hardcoded)
    → model = "claude-haiku-4-5-20251001"
    → api_key = None  (not injected; SDK reads ANTHROPIC_API_KEY from process env)
    → base_url = None  (not injected; SDK uses Anthropic default)
```

### 4.3 Pseudocode

```
function _resolve_llm_config(node, handler_type, manifest, providers):
    # Layer 1: node-level profile
    profile_name = node.attrs.get("llm_profile")
    if profile_name is not None:
        profile = providers.get_profile(profile_name)  # raises UnknownProfileError if missing
        return LLMConfig(
            model=_expand_env(profile["model"]),
            api_key=_expand_env_optional(profile.get("api_key")),
            base_url=_expand_env_optional(profile.get("base_url")),
            profile_name=profile_name,
        )

    # Layer 2: handler defaults from manifest
    handler_defaults = manifest.get("defaults", {}).get("handler_defaults", {})
    handler_profile_name = handler_defaults.get(handler_type, {}).get("llm_profile")
    if handler_profile_name is not None:
        profile = providers.get_profile(handler_profile_name)
        return LLMConfig(
            model=_expand_env(profile["model"]),
            api_key=_expand_env_optional(profile.get("api_key")),
            base_url=_expand_env_optional(profile.get("base_url")),
            profile_name=handler_profile_name,
        )

    # Layer 3: manifest-level default profile
    manifest_profile_name = manifest.get("defaults", {}).get("llm_profile")
    if manifest_profile_name is not None:
        profile = providers.get_profile(manifest_profile_name)
        return LLMConfig(
            model=_expand_env(profile["model"]),
            api_key=_expand_env_optional(profile.get("api_key")),
            base_url=_expand_env_optional(profile.get("base_url")),
            profile_name=manifest_profile_name,
        )

    # Layer 4: environment variables (direct, no profile lookup)
    env_model = os.environ.get("ANTHROPIC_MODEL")
    env_api_key = os.environ.get("ANTHROPIC_API_KEY")
    env_base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if env_model is not None:
        return LLMConfig(
            model=env_model,
            api_key=env_api_key,   # may be None; that is fine
            base_url=env_base_url,
            profile_name=None,
        )

    # Layer 5: runner hardcoded default
    return LLMConfig(
        model="claude-haiku-4-5-20251001",
        api_key=None,
        base_url=None,
        profile_name=None,
    )
```

**"First non-null wins" means**: the presence of a profile name at any layer (node, handler_default, manifest_default) immediately terminates the search. There is no merging of values across layers. A profile with only `model` set does not inherit `api_key` from a lower-priority layer.

---

## 5. `cobuilder/engine/providers.py` — Full Implementation

```python
"""cobuilder/engine/providers.py

LLM profile loader, resolver, and translator for per-node model configuration.

Public API:
    ProvidersLoader       — loads and validates providers.yaml
    resolve_llm_config()  — 5-layer resolution returning LLMConfig
    translate_profile()   — maps LLMConfig to ResolvedEnv (SDK-ready)
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class LLMConfig:
    """Resolved (but not yet translated) LLM configuration for a node dispatch."""
    model: str
    api_key: Optional[str] = None    # None = pass-through, let SDK read env
    base_url: Optional[str] = None   # None = pass-through, SDK uses Anthropic default
    profile_name: Optional[str] = None  # Source profile name, for logging only


@dataclass
class ResolvedEnv:
    """Translated config ready to inject into worker process environment."""
    model: str
    env_overrides: dict[str, str] = field(default_factory=dict)
    # env_overrides keys: ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL
    # Only present if the profile explicitly set those values.
    # A missing key means the worker inherits the value from the process environment.


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProvidersError(Exception):
    """Base exception for providers module."""


class ProfileValidationError(ProvidersError):
    """providers.yaml schema validation failed."""


class UnknownProfileError(ProvidersError):
    """A profile name was referenced that does not exist in providers.yaml."""
    def __init__(self, profile_name: str, available: list[str]):
        self.profile_name = profile_name
        self.available = available
        super().__init__(
            f"Unknown LLM profile '{profile_name}'. "
            f"Available: {available}. "
            f"Check providers.yaml."
        )


class MissingEnvVarError(ProvidersError):
    """A required $VAR reference could not be resolved from the environment."""
    def __init__(self, var_name: str, profile_name: str, field_name: str):
        self.var_name = var_name
        super().__init__(
            f"Profile '{profile_name}' field '{field_name}' references "
            f"${var_name} but that environment variable is not set."
        )


# ---------------------------------------------------------------------------
# Env var expansion
# ---------------------------------------------------------------------------

_ENV_REF_RE = re.compile(r"^\$\{?([A-Z_][A-Z0-9_]*)\}?$")


def _expand_env(
    value: str,
    *,
    profile_name: str = "<unknown>",
    field_name: str = "<unknown>",
    required: bool = True,
) -> Optional[str]:
    """Expand a $VAR or ${VAR} reference to its environment value.

    Args:
        value:        Raw string from providers.yaml.
        profile_name: Profile name for error messages.
        field_name:   Field name (model/api_key/base_url) for error messages.
        required:     If True and the env var is missing, raise MissingEnvVarError.
                      If False, return None instead.

    Returns:
        Expanded string, or None if not an env-var reference.
    """
    m = _ENV_REF_RE.match(value.strip())
    if m is None:
        return value  # literal value, return as-is

    var_name = m.group(1)
    resolved = os.environ.get(var_name)
    if resolved is None:
        if required:
            raise MissingEnvVarError(var_name, profile_name, field_name)
        return None
    return resolved


# ---------------------------------------------------------------------------
# ProvidersLoader
# ---------------------------------------------------------------------------

_VALID_PROFILE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

_VALID_PROFILE_FIELDS = frozenset({"model", "api_key", "base_url"})


class ProvidersLoader:
    """Loads and validates a providers.yaml file.

    Usage:
        loader = ProvidersLoader.from_path(Path("providers.yaml"))
        loader = ProvidersLoader.from_dot_dir(dot_path)
        profile = loader.get_profile("anthropic-fast")  # dict
        names = loader.profile_names()
    """

    # Built-in defaults used when no providers.yaml is found anywhere.
    _BUILTIN_PROFILES: dict[str, dict] = {
        "anthropic-fast": {
            "model": "claude-haiku-4-5-20251001",
            "api_key": "$ANTHROPIC_API_KEY",
            "base_url": "https://api.anthropic.com",
        },
        "anthropic-smart": {
            "model": "claude-sonnet-4-5-20250514",
            "api_key": "$ANTHROPIC_API_KEY",
            "base_url": "https://api.anthropic.com",
        },
    }

    def __init__(self, profiles: dict[str, dict], source_path: Optional[Path] = None):
        self._profiles = profiles
        self._source_path = source_path

    @classmethod
    def from_path(cls, path: Path) -> "ProvidersLoader":
        """Load providers.yaml from an explicit path."""
        if not path.exists():
            raise FileNotFoundError(f"providers.yaml not found at {path}")
        raw = yaml.safe_load(path.read_text())
        return cls._from_raw(raw, source_path=path)

    @classmethod
    def from_dot_dir(
        cls,
        dot_path: Path,
        manifest_providers_file: Optional[str] = None,
    ) -> "ProvidersLoader":
        """Discover providers.yaml using the 4-location search order.

        Search order:
        1. manifest.defaults.providers_file (if provided)
        2. Directory containing the dot_path
        3. Git repo root
        4. Built-in defaults (no file found)
        """
        # 1. Manifest-specified path
        if manifest_providers_file:
            explicit = Path(manifest_providers_file)
            if not explicit.is_absolute():
                explicit = dot_path.parent / explicit
            if explicit.exists():
                return cls.from_path(explicit)
            logger.warning(
                "providers_file '%s' specified in manifest but not found; "
                "falling back to search.", manifest_providers_file
            )

        # 2. Dot file directory
        candidate = dot_path.parent / "providers.yaml"
        if candidate.exists():
            return cls.from_path(candidate)

        # 3. Git repo root
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(dot_path.parent),
                capture_output=True, text=True, check=True,
            )
            repo_root = Path(result.stdout.strip())
            candidate = repo_root / "providers.yaml"
            if candidate.exists():
                return cls.from_path(candidate)
        except Exception:
            pass

        # 4. Built-in defaults
        logger.info(
            "No providers.yaml found; using built-in Anthropic defaults. "
            "Create providers.yaml to configure per-node LLM profiles."
        )
        return cls(profiles=dict(cls._BUILTIN_PROFILES), source_path=None)

    @classmethod
    def _from_raw(cls, raw: Any, source_path: Optional[Path]) -> "ProvidersLoader":
        """Parse and validate raw YAML dict."""
        if not isinstance(raw, dict):
            raise ProfileValidationError(
                f"providers.yaml must be a YAML mapping, got {type(raw).__name__}"
            )
        if "profiles" not in raw:
            raise ProfileValidationError("providers.yaml missing required top-level key 'profiles'")
        if set(raw.keys()) - {"profiles"}:
            raise ProfileValidationError(
                f"Unknown top-level keys in providers.yaml: {set(raw.keys()) - {'profiles'}}. "
                f"Only 'profiles' is allowed."
            )

        profiles_raw = raw["profiles"]
        if not isinstance(profiles_raw, dict):
            raise ProfileValidationError("providers.yaml 'profiles' must be a YAML mapping")

        validated: dict[str, dict] = {}
        for name, body in profiles_raw.items():
            cls._validate_profile_name(name)
            cls._validate_profile_body(name, body)
            validated[name] = body

        return cls(profiles=validated, source_path=source_path)

    @staticmethod
    def _validate_profile_name(name: str) -> None:
        if not _VALID_PROFILE_NAME_RE.match(name):
            raise ProfileValidationError(
                f"Invalid profile name '{name}'. "
                f"Must match ^[a-zA-Z0-9][a-zA-Z0-9_-]*$"
            )

    @staticmethod
    def _validate_profile_body(name: str, body: Any) -> None:
        if not isinstance(body, dict):
            raise ProfileValidationError(
                f"Profile '{name}' must be a YAML mapping, got {type(body).__name__}"
            )
        unknown_keys = set(body.keys()) - _VALID_PROFILE_FIELDS
        if unknown_keys:
            raise ProfileValidationError(
                f"Profile '{name}' has unknown fields: {unknown_keys}. "
                f"Allowed: {_VALID_PROFILE_FIELDS}"
            )
        if "model" not in body:
            raise ProfileValidationError(
                f"Profile '{name}' missing required field 'model'"
            )
        base_url = body.get("base_url", "")
        if base_url and not base_url.startswith("$") and not base_url.startswith("https://"):
            raise ProfileValidationError(
                f"Profile '{name}' base_url must start with 'https://' (got '{base_url}'). "
                f"HTTP endpoints are not allowed."
            )

    def get_profile(self, name: str) -> dict:
        """Return the raw profile dict for a given name.

        Raises:
            UnknownProfileError: If name is not in profiles.
        """
        if name not in self._profiles:
            raise UnknownProfileError(name, available=list(self._profiles.keys()))
        return self._profiles[name]

    def profile_names(self) -> list[str]:
        """Return sorted list of all profile names."""
        return sorted(self._profiles.keys())

    def has_profile(self, name: str) -> bool:
        return name in self._profiles


# ---------------------------------------------------------------------------
# resolve_llm_config()
# ---------------------------------------------------------------------------

def resolve_llm_config(
    *,
    node_attrs: dict[str, Any],
    handler_type: str,
    manifest: dict[str, Any],
    providers: ProvidersLoader,
) -> LLMConfig:
    """Resolve LLM configuration via 5-layer fallback.

    Layer 1: node.llm_profile attribute
    Layer 2: manifest.defaults.handler_defaults.{handler_type}.llm_profile
    Layer 3: manifest.defaults.llm_profile
    Layer 4: ANTHROPIC_MODEL / ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL env vars
    Layer 5: Runner hardcoded default (claude-haiku-4-5-20251001)

    Args:
        node_attrs:   Attributes dict from the DOT node (e.g. node.attrs).
        handler_type: Value of the node's 'handler' attribute (e.g. "codergen").
        manifest:     Parsed manifest.yaml dict (may be empty {}).
        providers:    Loaded ProvidersLoader instance.

    Returns:
        LLMConfig with resolved (but not yet env-expanded) values.

    Raises:
        UnknownProfileError: Profile name referenced but not in providers.yaml.
        MissingEnvVarError:  $VAR reference in profile but env var not set.
    """
    defaults = manifest.get("defaults", {})

    # --- Layer 1: node-level profile ------------------------------------
    profile_name = node_attrs.get("llm_profile")
    if profile_name:
        return _config_from_profile(profile_name, providers)

    # --- Layer 2: handler defaults from manifest -------------------------
    handler_defaults = defaults.get("handler_defaults", {})
    handler_profile = handler_defaults.get(handler_type, {}).get("llm_profile")
    if handler_profile:
        return _config_from_profile(handler_profile, providers)

    # --- Layer 3: manifest-level default profile ------------------------
    manifest_profile = defaults.get("llm_profile")
    if manifest_profile:
        return _config_from_profile(manifest_profile, providers)

    # --- Layer 4: environment variables ---------------------------------
    env_model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("PIPELINE_WORKER_MODEL")
    if env_model:
        return LLMConfig(
            model=env_model,
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            profile_name=None,
        )

    # --- Layer 5: runner hardcoded default ------------------------------
    logger.debug(
        "No LLM profile resolved for handler_type=%s; using runner default.",
        handler_type,
    )
    return LLMConfig(
        model="claude-haiku-4-5-20251001",
        api_key=None,
        base_url=None,
        profile_name=None,
    )


def _config_from_profile(profile_name: str, providers: ProvidersLoader) -> LLMConfig:
    """Build LLMConfig from a named profile, expanding env var references."""
    profile = providers.get_profile(profile_name)  # raises UnknownProfileError if missing
    model_raw = profile["model"]
    api_key_raw = profile.get("api_key")
    base_url_raw = profile.get("base_url")

    model = _expand_env(
        model_raw, profile_name=profile_name, field_name="model", required=True
    )
    api_key = None
    if api_key_raw:
        api_key = _expand_env(
            api_key_raw, profile_name=profile_name, field_name="api_key", required=False
        )
    base_url = None
    if base_url_raw:
        base_url = _expand_env(
            base_url_raw, profile_name=profile_name, field_name="base_url", required=False
        )

    return LLMConfig(
        model=model,
        api_key=api_key,
        base_url=base_url,
        profile_name=profile_name,
    )


# ---------------------------------------------------------------------------
# translate_profile() — LLMConfig → ResolvedEnv (SDK-ready)
# ---------------------------------------------------------------------------

def translate_profile(config: LLMConfig) -> ResolvedEnv:
    """Translate an LLMConfig to Anthropic SDK equivalents.

    Translation table:
        LLMConfig.model    → ResolvedEnv.model (passed to ClaudeCodeOptions.model)
        LLMConfig.api_key  → ResolvedEnv.env_overrides["ANTHROPIC_API_KEY"]
        LLMConfig.base_url → ResolvedEnv.env_overrides["ANTHROPIC_BASE_URL"]

    Only non-None values are added to env_overrides. A missing key means
    the worker process inherits the value from its parent environment.

    Args:
        config: Resolved LLMConfig from resolve_llm_config().

    Returns:
        ResolvedEnv ready to be merged into the worker's subprocess environment.
    """
    env_overrides: dict[str, str] = {}
    if config.api_key is not None:
        env_overrides["ANTHROPIC_API_KEY"] = config.api_key
    if config.base_url is not None:
        env_overrides["ANTHROPIC_BASE_URL"] = config.base_url

    return ResolvedEnv(model=config.model, env_overrides=env_overrides)


# ---------------------------------------------------------------------------
# Log sanitization
# ---------------------------------------------------------------------------

_SENSITIVE_KEYS = frozenset({"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "api_key"})


def sanitize_for_log(env_overrides: dict[str, str]) -> dict[str, str]:
    """Return a copy of env_overrides with sensitive values redacted.

    Usage:
        logger.info("Worker env: %s", sanitize_for_log(resolved.env_overrides))

    NEVER log the raw env_overrides dict. Always pass through sanitize_for_log first.
    """
    return {
        k: "***REDACTED***" if k in _SENSITIVE_KEYS else v
        for k, v in env_overrides.items()
    }
```

---

## 6. Integration Points

### 6.1 `pipeline_runner.py` — Worker Dispatch

**Current code** (three locations in `pipeline_runner.py`):
```python
# Lines ~984, ~1159, ~1514 — all identical pattern:
worker_model = (
    os.environ.get("ANTHROPIC_MODEL")
    or os.environ.get("PIPELINE_WORKER_MODEL", "claude-haiku-4-5-20251001")
)
```

**Replacement pattern** — to be applied at all three dispatch call sites:

```python
from cobuilder.engine.providers import (
    ProvidersLoader,
    resolve_llm_config,
    translate_profile,
    sanitize_for_log,
)

# In PipelineRunner.__init__ — load providers once at startup:
self._providers = ProvidersLoader.from_dot_dir(
    dot_path=Path(self.dot_file),
    manifest_providers_file=self._manifest.get("defaults", {}).get("providers_file"),
)

# In _dispatch_agent_sdk() — replace the worker_model line:
llm_config = resolve_llm_config(
    node_attrs=attrs,
    handler_type=attrs.get("handler", "codergen"),
    manifest=self._manifest,
    providers=self._providers,
)
resolved = translate_profile(llm_config)
worker_model = resolved.model

log.info(
    "[sdk] Dispatching worker  node=%s  type=%s  model=%s  profile=%s  cwd=%s",
    node_id, worker_type, worker_model,
    llm_config.profile_name or "<env/default>",
    effective_dir,
)
# NEVER log resolved.env_overrides directly — use sanitize_for_log:
log.debug(
    "[sdk] Worker env overrides: %s",
    sanitize_for_log(resolved.env_overrides),
)

# Merge env_overrides into clean_env BEFORE building ClaudeCodeOptions:
clean_env = {**clean_env, **resolved.env_overrides}

options = ClaudeCodeOptions(
    system_prompt=self._build_system_prompt(worker_type),
    allowed_tools=tools,
    permission_mode="bypassPermissions",
    model=worker_model,          # from resolved.model
    cwd=effective_dir,
    env=clean_env,               # includes ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL overrides
)
```

**Logfire span update** — include profile name in spans:
```python
if _LOGFIRE_AVAILABLE:
    logfire.span(
        "sdk_worker {node_id} ({worker_type})",
        node_id=node_id,
        worker_type=worker_type,
        model=worker_model,
        llm_profile=llm_config.profile_name or "env_default",
        cwd=effective_dir,
    )
```

### 6.2 `engine/runner.py` — Pass-Through to Handlers

The `EngineRunner` does not directly dispatch workers; it calls handlers via the `HandlerRegistry`. However, handlers that spawn workers (e.g., a future `CodergenHandler` using AgentSDK) need access to the resolved LLM config.

The injection point is `initial_context`:

```python
# When constructing EngineRunner with per-pipeline providers:
providers = ProvidersLoader.from_dot_dir(dot_path=Path(dot_file))
runner = EngineRunner(
    dot_path=dot_file,
    initial_context={
        "$providers": providers,          # handlers can call resolve_llm_config()
        "$manifest": manifest_dict,       # manifest for handler_defaults lookup
    },
)
```

Handlers access the providers loader from `request.context`:
```python
# Inside a handler's execute() method:
providers = request.context.get("$providers")
manifest = request.context.get("$manifest", {})
if providers:
    llm_config = resolve_llm_config(
        node_attrs=dict(request.node.attrs),
        handler_type=request.node.handler_type,
        manifest=manifest,
        providers=providers,
    )
    resolved = translate_profile(llm_config)
```

This is a **non-breaking** addition. Handlers that do not inspect `$providers` continue to work identically.

### 6.3 `manifest.yaml` — Handler Defaults Schema Extension

The `defaults` section of any manifest (template or pipeline-level) gains two new keys:

```yaml
defaults:
  llm_profile: "anthropic-fast"          # Layer 3: manifest-level default
  providers_file: "providers.yaml"        # Optional path override for ProvidersLoader

  handler_defaults:                       # Layer 2: per-handler-type defaults
    codergen:
      llm_profile: "anthropic-smart"
    research:
      llm_profile: "anthropic-fast"
    refine:
      llm_profile: "anthropic-smart"
    summarizer:
      llm_profile: "anthropic-fast"
    validation:
      llm_profile: "anthropic-fast"
```

The template manifest schema in `cobuilder/templates/manifest.py` must be extended to recognise `defaults.llm_profile`, `defaults.providers_file`, and `defaults.handler_defaults`.

**Backward compatibility**: both keys are optional. An existing manifest without `llm_profile` or `handler_defaults` continues to work; resolution falls through to Layer 4 (env vars) and Layer 5 (runner default).

### 6.4 DOT Node Attributes

Profile names are referenced on individual nodes:

```dot
research_e1 [
    shape=tab
    handler="research"
    label="Research: LLM Profile Docs"
    llm_profile="anthropic-fast"
    status="pending"
];

codergen_e1 [
    shape=box
    handler="codergen"
    label="Implement: providers.py"
    llm_profile="anthropic-smart"
    ts_path="docs/specs/cobuilder-upgrade/TS-COBUILDER-UPGRADE-E1.md"
    worker_type="backend-solutions-engineer"
    status="pending"
];
```

Nodes without `llm_profile` fall through the resolution chain automatically.

---

## 7. Security: API Key Sanitization

### 7.1 Rule

**Never log a resolved `api_key` value.** This applies to:
- `LLMConfig.api_key` (after env var expansion)
- `ResolvedEnv.env_overrides["ANTHROPIC_API_KEY"]`
- Any dict containing `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, or similar

### 7.2 Sanitization Pattern

```python
# CORRECT — sanitize before logging
log.debug("Worker env: %s", sanitize_for_log(resolved.env_overrides))
logfire.info(
    "worker_dispatch_start {node_id}",
    node_id=node_id,
    model=resolved.model,
    llm_profile=llm_config.profile_name or "env_default",
    # DO NOT add api_key or env_overrides here
)

# WRONG — these must never appear in log calls
log.debug("Worker env: %s", resolved.env_overrides)           # leaks api_key
logfire.info("worker", api_key=llm_config.api_key)            # leaks api_key
logfire.span("...", **resolved.env_overrides)                  # leaks api_key
```

### 7.3 `sanitize_for_log()` Implementation

Already shown in `providers.py` above. The function checks against `_SENSITIVE_KEYS`:
```python
_SENSITIVE_KEYS = frozenset({"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "api_key"})
```

Any key in this set has its value replaced with `"***REDACTED***"`.

### 7.4 Logfire Span Attributes

Safe to include in Logfire spans:
- `model` (model name, not sensitive)
- `llm_profile` (profile name, not sensitive)
- `base_url` (URL, not sensitive)
- `node_id`, `handler_type`, `worker_type`

Never include in Logfire spans:
- `api_key` (raw or expanded)
- `env_overrides` (contains api_key)
- Any value that was resolved from a `$VAR` reference for an api_key field

---

## 8. Testing Strategy

### 8.1 Test File: `tests/engine/test_providers.py`

```python
"""Unit tests for cobuilder/engine/providers.py.

Coverage targets:
- ProvidersLoader: from_path, from_dot_dir (all 4 search locations)
- _expand_env: literal, $VAR, ${VAR}, missing required, missing optional
- resolve_llm_config: all 5 layers, partial env, layer ordering
- translate_profile: key mapping, missing optional fields
- sanitize_for_log: redaction, non-sensitive passthrough
- Error cases: UnknownProfileError, MissingEnvVarError, ProfileValidationError
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from cobuilder.engine.providers import (
    ProvidersLoader,
    LLMConfig,
    ResolvedEnv,
    resolve_llm_config,
    translate_profile,
    sanitize_for_log,
    UnknownProfileError,
    MissingEnvVarError,
    ProfileValidationError,
    _expand_env,
)
```

### 8.2 Test Cases by Category

**Category 1: Profile Loading and Validation**

```python
class TestProvidersLoader:

    def test_load_valid_providers_yaml(self, tmp_path):
        """Loads a valid providers.yaml with multiple profiles."""
        yaml_content = """
profiles:
  anthropic-fast:
    model: claude-haiku-4-5-20251001
    api_key: $ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com
  openrouter-smart:
    model: anthropic/claude-sonnet-4-5
    api_key: $OPENROUTER_API_KEY
    base_url: https://openrouter.ai/api/v1
"""
        p = tmp_path / "providers.yaml"
        p.write_text(yaml_content)
        loader = ProvidersLoader.from_path(p)
        assert loader.has_profile("anthropic-fast")
        assert loader.has_profile("openrouter-smart")
        assert sorted(loader.profile_names()) == ["anthropic-fast", "openrouter-smart"]

    def test_get_profile_returns_raw_dict(self, tmp_path):
        """get_profile returns the raw dict without env expansion."""
        yaml_content = "profiles:\n  fast:\n    model: claude-haiku-4-5-20251001\n    api_key: $ANTHROPIC_API_KEY\n"
        p = tmp_path / "providers.yaml"
        p.write_text(yaml_content)
        loader = ProvidersLoader.from_path(p)
        profile = loader.get_profile("fast")
        assert profile["model"] == "claude-haiku-4-5-20251001"
        assert profile["api_key"] == "$ANTHROPIC_API_KEY"  # NOT expanded yet

    def test_unknown_profile_raises(self, tmp_path):
        """get_profile raises UnknownProfileError for missing names."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  fast:\n    model: claude-haiku-4-5-20251001\n")
        loader = ProvidersLoader.from_path(p)
        with pytest.raises(UnknownProfileError) as exc_info:
            loader.get_profile("nonexistent")
        assert "nonexistent" in str(exc_info.value)
        assert "fast" in exc_info.value.available

    def test_missing_profiles_key_raises(self, tmp_path):
        """providers.yaml without 'profiles' key raises ProfileValidationError."""
        p = tmp_path / "providers.yaml"
        p.write_text("models:\n  fast:\n    model: claude-haiku\n")
        with pytest.raises(ProfileValidationError, match="missing required top-level key 'profiles'"):
            ProvidersLoader.from_path(p)

    def test_unknown_top_level_key_raises(self, tmp_path):
        """Extra top-level keys raise ProfileValidationError."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  fast:\n    model: x\nextra_key: value\n")
        with pytest.raises(ProfileValidationError, match="Unknown top-level keys"):
            ProvidersLoader.from_path(p)

    def test_missing_model_raises(self, tmp_path):
        """Profile without 'model' raises ProfileValidationError."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  bad:\n    api_key: $ANTHROPIC_API_KEY\n")
        with pytest.raises(ProfileValidationError, match="missing required field 'model'"):
            ProvidersLoader.from_path(p)

    def test_http_base_url_raises(self, tmp_path):
        """HTTP (non-HTTPS) base_url raises ProfileValidationError."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  bad:\n    model: x\n    base_url: http://insecure.example.com\n")
        with pytest.raises(ProfileValidationError, match="must start with 'https://'"):
            ProvidersLoader.from_path(p)

    def test_unknown_profile_field_raises(self, tmp_path):
        """Profile with unexpected fields raises ProfileValidationError."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  bad:\n    model: x\n    temperature: 0.7\n")
        with pytest.raises(ProfileValidationError, match="unknown fields"):
            ProvidersLoader.from_path(p)

    def test_from_dot_dir_finds_sibling(self, tmp_path):
        """from_dot_dir finds providers.yaml in the same directory as the dot file."""
        dot = tmp_path / "pipeline.dot"
        dot.write_text("digraph{}")
        prov = tmp_path / "providers.yaml"
        prov.write_text("profiles:\n  fast:\n    model: claude-haiku-4-5-20251001\n")
        loader = ProvidersLoader.from_dot_dir(dot)
        assert loader.has_profile("fast")

    def test_from_dot_dir_falls_back_to_builtin(self, tmp_path):
        """from_dot_dir returns built-in defaults when no providers.yaml found."""
        dot = tmp_path / "pipeline.dot"
        dot.write_text("digraph{}")
        loader = ProvidersLoader.from_dot_dir(dot)
        assert loader.has_profile("anthropic-fast")
        assert loader.has_profile("anthropic-smart")

    def test_model_only_profile_is_valid(self, tmp_path):
        """A profile with only 'model' (no api_key or base_url) is valid."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  minimal:\n    model: claude-haiku-4-5-20251001\n")
        loader = ProvidersLoader.from_path(p)
        assert loader.has_profile("minimal")
```

**Category 2: Env Var Substitution**

```python
class TestEnvVarExpansion:

    def test_literal_value_returned_unchanged(self):
        assert _expand_env("https://api.anthropic.com") == "https://api.anthropic.com"

    def test_dollar_var_expanded(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "sk-test123")
        assert _expand_env("$MY_KEY") == "sk-test123"

    def test_dollar_brace_var_expanded(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "sk-test123")
        assert _expand_env("${MY_KEY}") == "sk-test123"

    def test_missing_required_var_raises(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        with pytest.raises(MissingEnvVarError) as exc_info:
            _expand_env("$MISSING_VAR", profile_name="test", field_name="model", required=True)
        assert "MISSING_VAR" in str(exc_info.value)

    def test_missing_optional_var_returns_none(self, monkeypatch):
        monkeypatch.delenv("MISSING_VAR", raising=False)
        result = _expand_env("$MISSING_VAR", required=False)
        assert result is None
```

**Category 3: 5-Layer Resolution**

```python
class TestResolveLlmConfig:

    @pytest.fixture
    def providers(self, tmp_path):
        p = tmp_path / "providers.yaml"
        p.write_text("""
profiles:
  anthropic-fast:
    model: claude-haiku-4-5-20251001
    api_key: $ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com
  anthropic-smart:
    model: claude-sonnet-4-5-20250514
    api_key: $ANTHROPIC_API_KEY
    base_url: https://api.anthropic.com
""")
        return ProvidersLoader.from_path(p)

    def test_layer1_node_profile_wins(self, providers, monkeypatch):
        """Node llm_profile overrides all other layers."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("ANTHROPIC_MODEL", "some-other-model")
        config = resolve_llm_config(
            node_attrs={"llm_profile": "anthropic-smart"},
            handler_type="codergen",
            manifest={"defaults": {"llm_profile": "anthropic-fast"}},
            providers=providers,
        )
        assert config.model == "claude-sonnet-4-5-20250514"
        assert config.profile_name == "anthropic-smart"

    def test_layer2_handler_default_wins_over_manifest(self, providers, monkeypatch):
        """Handler defaults override manifest-level default."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = resolve_llm_config(
            node_attrs={},   # no llm_profile on node
            handler_type="codergen",
            manifest={
                "defaults": {
                    "llm_profile": "anthropic-fast",   # Layer 3
                    "handler_defaults": {
                        "codergen": {"llm_profile": "anthropic-smart"},  # Layer 2
                    },
                }
            },
            providers=providers,
        )
        assert config.model == "claude-sonnet-4-5-20250514"
        assert config.profile_name == "anthropic-smart"

    def test_layer3_manifest_default(self, providers, monkeypatch):
        """Manifest default applies when node and handler_defaults are absent."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = resolve_llm_config(
            node_attrs={},
            handler_type="codergen",
            manifest={"defaults": {"llm_profile": "anthropic-fast"}},
            providers=providers,
        )
        assert config.model == "claude-haiku-4-5-20251001"
        assert config.profile_name == "anthropic-fast"

    def test_layer4_env_var_fallback(self, providers, monkeypatch):
        """Falls through to ANTHROPIC_MODEL env var when no profiles match."""
        monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-from-env")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-env")
        config = resolve_llm_config(
            node_attrs={},
            handler_type="codergen",
            manifest={},    # no defaults
            providers=providers,
        )
        assert config.model == "claude-opus-from-env"
        assert config.api_key == "sk-test-env"
        assert config.profile_name is None

    def test_layer5_runner_default(self, providers, monkeypatch):
        """Falls through to hardcoded default when nothing else matches."""
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("PIPELINE_WORKER_MODEL", raising=False)
        config = resolve_llm_config(
            node_attrs={},
            handler_type="codergen",
            manifest={},
            providers=providers,
        )
        assert config.model == "claude-haiku-4-5-20251001"
        assert config.profile_name is None

    def test_unknown_node_profile_raises_immediately(self, providers, monkeypatch):
        """Unknown profile on node raises UnknownProfileError (fail fast)."""
        with pytest.raises(UnknownProfileError) as exc_info:
            resolve_llm_config(
                node_attrs={"llm_profile": "nonexistent-profile"},
                handler_type="codergen",
                manifest={},
                providers=providers,
            )
        assert "nonexistent-profile" in str(exc_info.value)

    def test_handler_type_mismatch_falls_through(self, providers, monkeypatch):
        """Handler defaults for a different type do not apply."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        config = resolve_llm_config(
            node_attrs={},
            handler_type="research",   # no handler_defaults.research entry
            manifest={
                "defaults": {
                    "handler_defaults": {
                        "codergen": {"llm_profile": "anthropic-smart"},
                    }
                }
            },
            providers=providers,
        )
        # Falls through to Layer 4/5 — no profile for "research" handler
        assert config.profile_name is None

    @pytest.mark.parametrize("node_llm,handler_type,expected_model", [
        ("anthropic-fast",  "research",  "claude-haiku-4-5-20251001"),
        ("anthropic-smart", "codergen", "claude-sonnet-4-5-20250514"),
        (None,              "research",  "claude-haiku-4-5-20251001"),  # from manifest handler_defaults
    ])
    def test_resolution_parametrized(self, providers, monkeypatch, node_llm, handler_type, expected_model):
        """Parametrized resolution across common scenarios."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        node_attrs = {"llm_profile": node_llm} if node_llm else {}
        config = resolve_llm_config(
            node_attrs=node_attrs,
            handler_type=handler_type,
            manifest={
                "defaults": {
                    "handler_defaults": {
                        "research": {"llm_profile": "anthropic-fast"},
                    }
                }
            },
            providers=providers,
        )
        assert config.model == expected_model
```

**Category 4: Profile Translation**

```python
class TestTranslateProfile:

    def test_all_fields_present(self):
        config = LLMConfig(
            model="claude-sonnet-4-5-20250514",
            api_key="sk-ant-123",
            base_url="https://openrouter.ai/api/v1",
            profile_name="openrouter-smart",
        )
        resolved = translate_profile(config)
        assert resolved.model == "claude-sonnet-4-5-20250514"
        assert resolved.env_overrides["ANTHROPIC_API_KEY"] == "sk-ant-123"
        assert resolved.env_overrides["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api/v1"

    def test_none_api_key_omitted(self):
        """None api_key means 'inherit from process env' — not in env_overrides."""
        config = LLMConfig(model="claude-haiku-4-5-20251001", api_key=None, base_url=None)
        resolved = translate_profile(config)
        assert "ANTHROPIC_API_KEY" not in resolved.env_overrides
        assert "ANTHROPIC_BASE_URL" not in resolved.env_overrides

    def test_none_base_url_omitted(self):
        config = LLMConfig(model="claude-haiku-4-5-20251001", api_key="sk-test", base_url=None)
        resolved = translate_profile(config)
        assert resolved.env_overrides["ANTHROPIC_API_KEY"] == "sk-test"
        assert "ANTHROPIC_BASE_URL" not in resolved.env_overrides
```

**Category 5: Log Sanitization**

```python
class TestSanitizeForLog:

    def test_api_key_redacted(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-real-key", "ANTHROPIC_BASE_URL": "https://api.anthropic.com"}
        safe = sanitize_for_log(env)
        assert safe["ANTHROPIC_API_KEY"] == "***REDACTED***"
        assert safe["ANTHROPIC_BASE_URL"] == "https://api.anthropic.com"

    def test_openrouter_key_redacted(self):
        env = {"OPENROUTER_API_KEY": "sk-or-real-key"}
        safe = sanitize_for_log(env)
        assert safe["OPENROUTER_API_KEY"] == "***REDACTED***"

    def test_non_sensitive_keys_unchanged(self):
        env = {"ANTHROPIC_BASE_URL": "https://api.anthropic.com", "SOME_OTHER": "value"}
        safe = sanitize_for_log(env)
        assert safe == env

    def test_empty_dict_unchanged(self):
        assert sanitize_for_log({}) == {}

    def test_original_not_mutated(self):
        env = {"ANTHROPIC_API_KEY": "sk-real"}
        _ = sanitize_for_log(env)
        assert env["ANTHROPIC_API_KEY"] == "sk-real"  # original unchanged
```

**Category 6: Error Cases**

```python
class TestErrorCases:

    def test_providers_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ProvidersLoader.from_path(tmp_path / "nonexistent.yaml")

    def test_invalid_yaml_raises(self, tmp_path):
        p = tmp_path / "providers.yaml"
        p.write_text("profiles: [\nnot: valid: yaml")
        with pytest.raises(Exception):   # yaml.YAMLError
            ProvidersLoader.from_path(p)

    def test_missing_env_var_for_model_raises(self, tmp_path, monkeypatch):
        """$VAR in 'model' field raises MissingEnvVarError when var is unset."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  dynamic:\n    model: $DYNAMIC_MODEL\n")
        loader = ProvidersLoader.from_path(p)
        monkeypatch.delenv("DYNAMIC_MODEL", raising=False)
        with pytest.raises(MissingEnvVarError, match="DYNAMIC_MODEL"):
            resolve_llm_config(
                node_attrs={"llm_profile": "dynamic"},
                handler_type="codergen",
                manifest={},
                providers=loader,
            )

    def test_invalid_profile_name_raises(self, tmp_path):
        """Profile name with invalid characters raises ProfileValidationError."""
        p = tmp_path / "providers.yaml"
        p.write_text("profiles:\n  'bad profile name':\n    model: x\n")
        with pytest.raises(ProfileValidationError, match="Invalid profile name"):
            ProvidersLoader.from_path(p)
```

### 8.3 Test Markers

All tests in `tests/engine/test_providers.py` should carry `@pytest.mark.unit`. No network calls, no filesystem side effects beyond `tmp_path`.

```python
# conftest.py or pyproject.toml marker registration:
# [tool.pytest.ini_options]
# markers = ["unit", "integration", "e2e"]
```

### 8.4 Logfire Span Assertions (Integration)

A separate integration test verifies that `sanitize_for_log` is called at every worker dispatch and that `api_key` never appears in Logfire spans:

```python
# tests/integration/test_provider_logfire.py
import logfire.testing

def test_no_api_key_in_logfire_spans(tmp_path, monkeypatch):
    """Verify api_key is never emitted to Logfire during worker dispatch."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-sentinel-should-never-appear")
    with logfire.testing.CaptureLogfire() as capture:
        # ... trigger a dispatch that would use profile with api_key ...
        pass
    for span in capture.exporter.exported_spans:
        for attr_value in span.attributes.values():
            assert "sk-sentinel-should-never-appear" not in str(attr_value), (
                f"API key leaked into Logfire span '{span.name}'"
            )
```

---

## 9. Acceptance Criteria Verification

| Criterion (from PRD §8 Epic 1) | How Verified |
|---------------------------------|-------------|
| DOT node with `llm_profile="anthropic-smart"` dispatches to Sonnet | `test_layer1_node_profile_wins` + manual pipeline run |
| Profile `api_key: $OPENROUTER_API_KEY` resolves from environment | `test_dollar_var_expanded` + `TestResolveLlmConfig` tests |
| Profile keys translate to Anthropic equivalents in worker env | `TestTranslateProfile.test_all_fields_present` |
| 5-layer fallback works: node → handler → manifest → env → runner default | `test_layer1` through `test_layer5` parametrized suite |
| No api_key values appear in log output | `TestSanitizeForLog` + Logfire integration test |
| `providers.yaml` documented with example profiles for Anthropic + OpenRouter | Built-in profiles in `ProvidersLoader._BUILTIN_PROFILES` + `providers.yaml` at repo root |

---

## 10. Implementation Checklist for Worker Agent

Execute in this exact order. Each step must pass before proceeding to the next.

**Step 1 — Create `providers.yaml` at repo root**
- Copy the example from §3.2 of this spec
- Include all 5 profiles: anthropic-fast, anthropic-smart, anthropic-opus, openrouter-smart, openrouter-fast

**Step 2 — Create `cobuilder/engine/providers.py`**
- Copy the full implementation from §5 of this spec exactly
- Run `python -c "from cobuilder.engine.providers import ProvidersLoader"` to verify import works

**Step 3 — Create `tests/engine/test_providers.py`**
- Copy all test classes from §8.2 of this spec
- Run `pytest tests/engine/test_providers.py -v` — all tests must pass
- Check coverage: `pytest tests/engine/test_providers.py --cov=cobuilder.engine.providers --cov-report=term-missing`
- Target: 100% line coverage on `providers.py`

**Step 4 — Modify `pipeline_runner.py`**
- Add import at top: `from cobuilder.engine.providers import ProvidersLoader, resolve_llm_config, translate_profile, sanitize_for_log`
- In `PipelineRunner.__init__`: add `self._providers` and `self._manifest` attributes
  - `self._manifest = {}` initially (manifest loading is out of scope for E1 if not yet implemented)
  - `self._providers = ProvidersLoader.from_dot_dir(Path(self.dot_file))`
- In `_dispatch_agent_sdk()`: replace the 3 occurrences of `worker_model = os.environ.get("ANTHROPIC_MODEL") or ...` with the pattern from §6.1
- In `_run_validation_subprocess()` (if it dispatches via AgentSDK): same replacement
- Verify: `grep -n "PIPELINE_WORKER_MODEL\|ANTHROPIC_MODEL" cobuilder/attractor/pipeline_runner.py` — should return 0 results

**Step 5 — Modify `cobuilder/engine/runner.py`**
- Add `$providers` and `$manifest` to `initial_context` injection pattern (§6.2)
- This is a non-breaking additive change

**Step 6 — Extend manifest schema**
- In `cobuilder/templates/manifest.py`: add `llm_profile`, `providers_file`, and `handler_defaults` to the `defaults` section schema
- Ensure unknown keys in `defaults` are allowed (existing manifests must not break)

**Step 7 — Verify E2E**
- Create a test DOT file with two nodes: one `llm_profile="anthropic-fast"` and one `llm_profile="anthropic-smart"`
- Run the pipeline: `python -m cobuilder.attractor.pipeline_runner --dot-file test.dot`
- Confirm in logs: first node uses Haiku, second uses Sonnet
- Confirm: no API key appears in any log line

**Step 8 — Run full test suite**
- `pytest tests/ -v --cov=cobuilder --cov-report=term-missing`
- Ensure no regressions from existing tests
