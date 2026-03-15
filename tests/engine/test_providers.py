"""Tests for cobuilder.engine.providers — LLM profile management.

Tests the 5-layer LLM configuration resolution system:
1. Node's llm_profile attribute
2. Handler defaults from manifest
3. Manifest defaults
4. Environment variables
5. Runner defaults
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from cobuilder.engine.providers import (
    LLMProfile,
    ProvidersFile,
    ResolvedLLMConfig,
    get_llm_config_for_node,
    load_providers_file,
    resolve_env_var,
    resolve_llm_config,
    sanitize_for_logging,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_profiles_yaml(tmp_path: Path) -> Path:
    """Create a sample providers.yaml file."""
    content = {
        "profiles": {
            "anthropic-fast": {
                "model": "claude-haiku-4-5-20251001",
                "api_key": "$ANTHROPIC_API_KEY",
                "base_url": "https://api.anthropic.com",
            },
            "anthropic-smart": {
                "model": "claude-sonnet-4-5-20250514",
                "api_key": "$ANTHROPIC_API_KEY",
            },
            "openrouter-smart": {
                "model": "anthropic/claude-sonnet-4-5",
                "api_key": "$OPENROUTER_API_KEY",
                "base_url": "https://openrouter.ai/api/v1",
            },
            "profile-with-extra": {
                "model": "custom-model",
                "api_key": "sk-test-key",
                "custom_option": "value",
                "another_option": 42,
            },
        }
    }
    providers_path = tmp_path / "providers.yaml"
    providers_path.write_text(yaml.dump(content))
    return providers_path


@pytest.fixture
def minimal_profiles_yaml(tmp_path: Path) -> Path:
    """Create a minimal providers.yaml with one profile."""
    content = {
        "profiles": {
            "minimal": {
                "model": "claude-haiku-4-5-20251001",
            }
        }
    }
    providers_path = tmp_path / "providers.yaml"
    providers_path.write_text(yaml.dump(content))
    return providers_path


@pytest.fixture
def loaded_providers(sample_profiles_yaml: Path) -> ProvidersFile:
    """Load the sample providers.yaml."""
    return ProvidersFile.from_file(sample_profiles_yaml)


@pytest.fixture
def mock_manifest_defaults() -> Any:
    """Create a mock manifest defaults object."""
    @dataclass
    class HandlerDefault:
        llm_profile: str | None = None

    @dataclass
    class Defaults:
        llm_profile: str | None = None
        handler_defaults: dict[str, HandlerDefault] | None = None

    return Defaults(
        llm_profile="anthropic-smart",
        handler_defaults={
            "codergen": HandlerDefault(llm_profile="anthropic-fast"),
            "research": HandlerDefault(llm_profile="anthropic-smart"),
        }
    )


# ---------------------------------------------------------------------------
# LLMProfile Tests
# ---------------------------------------------------------------------------


class TestLLMProfile:
    """Tests for LLMProfile dataclass."""

    def test_create_profile_with_all_fields(self) -> None:
        """Profile can be created with all fields."""
        profile = LLMProfile(
            name="test-profile",
            model="claude-sonnet-4-5-20250514",
            api_key="sk-test-key",
            base_url="https://api.custom.com",
            extra={"custom": "option"},
        )
        assert profile.name == "test-profile"
        assert profile.model == "claude-sonnet-4-5-20250514"
        assert profile.api_key == "sk-test-key"
        assert profile.base_url == "https://api.custom.com"
        assert profile.extra == {"custom": "option"}

    def test_create_profile_with_defaults(self) -> None:
        """Profile uses default values for optional fields."""
        profile = LLMProfile(
            name="minimal",
            model="claude-haiku-4-5-20251001",
        )
        assert profile.api_key is None
        assert profile.base_url == "https://api.anthropic.com"
        assert profile.extra == {}

    def test_repr_redacts_api_key(self) -> None:
        """Profile repr hides the API key for security."""
        profile = LLMProfile(
            name="secret-profile",
            model="claude-sonnet-4-5-20250514",
            api_key="sk-super-secret-key",
        )
        repr_str = repr(profile)
        assert "sk-super-secret-key" not in repr_str
        assert "***REDACTED***" in repr_str
        assert "secret-profile" in repr_str

    def test_repr_shows_none_for_missing_key(self) -> None:
        """Profile repr shows None when no API key."""
        profile = LLMProfile(
            name="no-key",
            model="claude-haiku-4-5-20251001",
        )
        repr_str = repr(profile)
        assert "api_key=None" in repr_str
        assert "***REDACTED***" not in repr_str


# ---------------------------------------------------------------------------
# ResolvedLLMConfig Tests
# ---------------------------------------------------------------------------


class TestResolvedLLMConfig:
    """Tests for ResolvedLLMConfig dataclass."""

    def test_create_resolved_config(self) -> None:
        """Resolved config can be created with all fields."""
        config = ResolvedLLMConfig(
            model="claude-sonnet-4-5-20250514",
            api_key="resolved-key",
            base_url="https://api.custom.com",
            profile_name="custom-profile",
            resolution_source="node_profile",
        )
        assert config.model == "claude-sonnet-4-5-20250514"
        assert config.api_key == "resolved-key"
        assert config.base_url == "https://api.custom.com"
        assert config.profile_name == "custom-profile"
        assert config.resolution_source == "node_profile"

    def test_repr_redacts_api_key(self) -> None:
        """Resolved config repr hides the API key."""
        config = ResolvedLLMConfig(
            model="claude-sonnet-4-5-20250514",
            api_key="secret-key",
        )
        repr_str = repr(config)
        assert "secret-key" not in repr_str
        assert "***REDACTED***" in repr_str

    def test_to_env_dict_basic(self) -> None:
        """to_env_dict returns model in environment format."""
        config = ResolvedLLMConfig(
            model="claude-haiku-4-5-20251001",
            profile_name="test",
        )
        env = config.to_env_dict()
        assert env == {"ANTHROPIC_MODEL": "claude-haiku-4-5-20251001"}

    def test_to_env_dict_with_api_key(self) -> None:
        """to_env_dict includes API key when set."""
        config = ResolvedLLMConfig(
            model="claude-sonnet-4-5-20250514",
            api_key="sk-test-key",
        )
        env = config.to_env_dict()
        assert env["ANTHROPIC_MODEL"] == "claude-sonnet-4-5-20250514"
        assert env["ANTHROPIC_API_KEY"] == "sk-test-key"

    def test_to_env_dict_with_custom_base_url(self) -> None:
        """to_env_dict includes base_url when non-default."""
        config = ResolvedLLMConfig(
            model="claude-sonnet-4-5-20250514",
            base_url="https://openrouter.ai/api/v1",
        )
        env = config.to_env_dict()
        assert env["ANTHROPIC_BASE_URL"] == "https://openrouter.ai/api/v1"

    def test_to_env_dict_excludes_default_base_url(self) -> None:
        """to_env_dict excludes base_url when it's the default."""
        config = ResolvedLLMConfig(
            model="claude-sonnet-4-5-20250514",
            base_url="https://api.anthropic.com",  # default
        )
        env = config.to_env_dict()
        assert "ANTHROPIC_BASE_URL" not in env


# ---------------------------------------------------------------------------
# resolve_env_var Tests
# ---------------------------------------------------------------------------


class TestResolveEnvVar:
    """Tests for environment variable resolution."""

    def test_resolve_dollar_syntax(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resolve $VAR_NAME syntax."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = resolve_env_var("$TEST_VAR")
        assert result == "test_value"

    def test_resolve_brace_syntax(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Resolve ${VAR_NAME} syntax."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        result = resolve_env_var("${TEST_VAR}")
        assert result == "test_value"

    def test_returns_none_for_unset_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when environment variable is not set."""
        monkeypatch.delenv("UNSET_VAR", raising=False)
        result = resolve_env_var("$UNSET_VAR")
        assert result is None

    def test_returns_none_input(self) -> None:
        """Returns None when input is None."""
        result = resolve_env_var(None)
        assert result is None

    def test_returns_literal_value(self) -> None:
        """Returns value unchanged when not an env var reference."""
        result = resolve_env_var("literal-value")
        assert result == "literal-value"

    def test_returns_complex_string_unchanged(self) -> None:
        """Returns strings without $ prefix unchanged."""
        result = resolve_env_var("sk-12345-key")
        assert result == "sk-12345-key"

    def test_does_not_expand_embedded_vars(self) -> None:
        """Only matches full $VAR at start, not embedded vars."""
        # The pattern is anchored at start, so embedded $VAR won't match
        result = resolve_env_var("prefix-$VAR")
        # This should return unchanged since pattern requires $ at start
        assert result == "prefix-$VAR"


# ---------------------------------------------------------------------------
# sanitize_for_logging Tests
# ---------------------------------------------------------------------------


class TestSanitizeForLogging:
    """Tests for log sanitization."""

    def test_redacts_long_alphanumeric(self) -> None:
        """Redacts values that look like API keys (long alphanumeric)."""
        result = sanitize_for_logging("sk-proj-abcdefghijklmnopqrstuvwxyz123456")
        assert result == "***REDACTED***"

    def test_returns_short_values(self) -> None:
        """Returns short values unchanged."""
        result = sanitize_for_logging("short")
        assert result == "short"

    def test_returns_none_as_placeholder(self) -> None:
        """Returns '<none>' for None values."""
        result = sanitize_for_logging(None)
        assert result == "<none>"

    def test_returns_urls_unchanged(self) -> None:
        """URLs are returned unchanged (contain non-alphanumeric chars)."""
        result = sanitize_for_logging("https://api.anthropic.com")
        assert result == "https://api.anthropic.com"

    def test_handles_dashes_and_underscores(self) -> None:
        """Handles values with dashes and underscores."""
        # Long enough to trigger redaction
        result = sanitize_for_logging("sk_test_key_12345_abcdef_ghijkl")
        assert result == "***REDACTED***"


# ---------------------------------------------------------------------------
# ProvidersFile Tests
# ---------------------------------------------------------------------------


class TestProvidersFileLoad:
    """Tests for loading providers.yaml files."""

    def test_load_from_file(self, sample_profiles_yaml: Path) -> None:
        """Load profiles from a YAML file."""
        providers = ProvidersFile.from_file(sample_profiles_yaml)
        assert len(providers.list_profiles()) == 4
        assert "anthropic-fast" in providers.list_profiles()

    def test_load_minimal_file(self, minimal_profiles_yaml: Path) -> None:
        """Load a minimal providers file."""
        providers = ProvidersFile.from_file(minimal_profiles_yaml)
        assert len(providers.list_profiles()) == 1
        assert providers.get("minimal") is not None

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Raises FileNotFoundError for missing file."""
        missing_path = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            ProvidersFile.from_file(missing_path)

    def test_invalid_yaml_type(self, tmp_path: Path) -> None:
        """Raises ValueError for non-mapping YAML."""
        bad_path = tmp_path / "bad.yaml"
        bad_path.write_text("- list\n- instead\n- of mapping")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            ProvidersFile.from_file(bad_path)

    def test_invalid_profiles_type(self, tmp_path: Path) -> None:
        """Raises ValueError when 'profiles' is not a mapping."""
        bad_path = tmp_path / "bad.yaml"
        bad_path.write_text("profiles:\n  - list\n  - instead")
        with pytest.raises(ValueError, match="'profiles' must be a mapping"):
            ProvidersFile.from_file(bad_path)

    def test_skips_invalid_profile_entries(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Skips profiles that are not mappings, logs warning."""
        bad_path = tmp_path / "bad.yaml"
        bad_path.write_text("""
profiles:
  valid:
    model: claude-haiku
  invalid: "not a mapping"
  another_valid:
    model: claude-sonnet
""")
        providers = ProvidersFile.from_file(bad_path)
        assert len(providers.list_profiles()) == 2
        assert "invalid" not in providers.list_profiles()
        assert "Profile 'invalid' is not a mapping" in caplog.text

    def test_skips_profiles_without_model(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Skips profiles that have no model, logs warning."""
        bad_path = tmp_path / "bad.yaml"
        bad_path.write_text("""
profiles:
  no_model:
    api_key: test-key
""")
        providers = ProvidersFile.from_file(bad_path)
        assert len(providers.list_profiles()) == 0
        assert "has no model" in caplog.text

    def test_empty_creates_empty_providers(self) -> None:
        """empty() creates ProvidersFile with no profiles."""
        providers = ProvidersFile.empty()
        assert len(providers.list_profiles()) == 0
        assert providers.get("any") is None


class TestProvidersFileAccess:
    """Tests for accessing profiles from ProvidersFile."""

    def test_get_existing_profile(self, loaded_providers: ProvidersFile) -> None:
        """Get an existing profile by name."""
        profile = loaded_providers.get("anthropic-fast")
        assert profile is not None
        assert profile.model == "claude-haiku-4-5-20251001"

    def test_get_missing_profile(self, loaded_providers: ProvidersFile) -> None:
        """Get returns None for missing profile."""
        profile = loaded_providers.get("nonexistent")
        assert profile is None

    def test_list_profiles(self, loaded_providers: ProvidersFile) -> None:
        """List all profile names."""
        names = loaded_providers.list_profiles()
        assert set(names) == {
            "anthropic-fast",
            "anthropic-smart",
            "openrouter-smart",
            "profile-with-extra",
        }

    def test_profile_has_extra_fields(self, loaded_providers: ProvidersFile) -> None:
        """Extra fields in profile are preserved."""
        profile = loaded_providers.get("profile-with-extra")
        assert profile is not None
        assert profile.extra == {"custom_option": "value", "another_option": 42}


# ---------------------------------------------------------------------------
# resolve_llm_config Tests
# ---------------------------------------------------------------------------


class TestResolveLLMConfigLayer1NodeProfile:
    """Tests for Layer 1: Node's llm_profile attribute."""

    def test_resolves_node_profile(
        self, loaded_providers: ProvidersFile, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Node profile takes precedence over all else."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
        monkeypatch.setenv("ANTHROPIC_MODEL", "env-model")

        config = resolve_llm_config(
            node_llm_profile="anthropic-fast",
            handler_type="codergen",
            providers=loaded_providers,
            manifest_defaults=None,
            node_id="test-node",
        )
        assert config.model == "claude-haiku-4-5-20251001"
        assert config.profile_name == "anthropic-fast"
        assert config.resolution_source == "node_profile"

    def test_resolves_env_var_in_profile(
        self, loaded_providers: ProvidersFile, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Environment variables in profile are resolved."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "resolved-env-key")

        config = resolve_llm_config(
            node_llm_profile="anthropic-fast",
            handler_type=None,
            providers=loaded_providers,
            manifest_defaults=None,
            node_id="test-node",
        )
        assert config.api_key == "resolved-env-key"

    def test_falls_back_if_profile_not_found(
        self, loaded_providers: ProvidersFile, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back if profile name doesn't exist in providers."""
        # Clear env vars to ensure we hit runner defaults
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        config = resolve_llm_config(
            node_llm_profile="nonexistent-profile",
            handler_type=None,
            providers=loaded_providers,
            manifest_defaults=None,
            node_id="test-node",
        )
        # Falls back to runner defaults
        assert config.resolution_source == "runner_default"
        assert "unknown profile" in caplog.text


class TestResolveLLMConfigLayer2HandlerDefaults:
    """Tests for Layer 2: Handler defaults from manifest."""

    def test_uses_handler_default(
        self,
        loaded_providers: ProvidersFile,
        mock_manifest_defaults: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Uses handler-specific default when node has no profile."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

        config = resolve_llm_config(
            node_llm_profile=None,
            handler_type="codergen",
            providers=loaded_providers,
            manifest_defaults=mock_manifest_defaults,
            node_id="test-node",
        )
        # codergen handler default is "anthropic-fast"
        assert config.model == "claude-haiku-4-5-20251001"
        assert config.profile_name == "anthropic-fast"
        assert config.resolution_source == "handler_default"

    def test_no_handler_type_uses_manifest_default(
        self,
        loaded_providers: ProvidersFile,
        mock_manifest_defaults: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Falls back to manifest default when no handler type."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

        config = resolve_llm_config(
            node_llm_profile=None,
            handler_type=None,
            providers=loaded_providers,
            manifest_defaults=mock_manifest_defaults,
            node_id="test-node",
        )
        # Falls to layer 3: manifest default
        assert config.profile_name == "anthropic-smart"
        assert config.resolution_source == "manifest_default"


class TestResolveLLMConfigLayer3ManifestDefault:
    """Tests for Layer 3: Manifest defaults."""

    def test_uses_manifest_default(
        self, loaded_providers: ProvidersFile, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uses manifest default when no node or handler profile."""
        @dataclass
        class Defaults:
            llm_profile: str = "anthropic-smart"
            handler_defaults: dict = None

        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

        config = resolve_llm_config(
            node_llm_profile=None,
            handler_type=None,
            providers=loaded_providers,
            manifest_defaults=Defaults(),
            node_id="test-node",
        )
        assert config.model == "claude-sonnet-4-5-20250514"
        assert config.profile_name == "anthropic-smart"
        assert config.resolution_source == "manifest_default"


class TestResolveLLMConfigLayer4Environment:
    """Tests for Layer 4: Environment variables."""

    def test_uses_environment_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uses environment variables when no profiles specified."""
        monkeypatch.setenv("ANTHROPIC_MODEL", "env-model")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-api-key")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env.example.com")

        config = resolve_llm_config(
            node_llm_profile=None,
            handler_type=None,
            providers=ProvidersFile.empty(),
            manifest_defaults=None,
            node_id="test-node",
        )
        assert config.model == "env-model"
        assert config.api_key == "env-api-key"
        assert config.base_url == "https://env.example.com"
        assert config.resolution_source == "environment"

    def test_uses_default_base_url_if_not_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uses default base URL if ANTHROPIC_BASE_URL not set."""
        monkeypatch.setenv("ANTHROPIC_MODEL", "env-model")
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

        config = resolve_llm_config(
            node_llm_profile=None,
            handler_type=None,
            providers=ProvidersFile.empty(),
            manifest_defaults=None,
            node_id="test-node",
        )
        assert config.base_url == "https://api.anthropic.com"


class TestResolveLLMConfigLayer5RunnerDefaults:
    """Tests for Layer 5: Runner defaults."""

    def test_uses_runner_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses runner defaults when nothing else is configured."""
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

        config = resolve_llm_config(
            node_llm_profile=None,
            handler_type=None,
            providers=ProvidersFile.empty(),
            manifest_defaults=None,
            node_id="test-node",
        )
        assert config.model == "claude-sonnet-4-5-20250514"
        assert config.api_key is None
        assert config.base_url == "https://api.anthropic.com"
        assert config.resolution_source == "runner_default"


# ---------------------------------------------------------------------------
# load_providers_file Tests
# ---------------------------------------------------------------------------


class TestLoadProvidersFile:
    """Tests for loading providers file from various locations."""

    def test_load_explicit_path(self, sample_profiles_yaml: Path) -> None:
        """Load from explicit path."""
        providers = load_providers_file(str(sample_profiles_yaml))
        assert len(providers.list_profiles()) == 4

    def test_load_from_manifest_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Load from manifest directory when no explicit path and no engine-bundled file."""
        import cobuilder.engine.providers as providers_module

        providers_yaml = tmp_path / "providers.yaml"
        providers_yaml.write_text(yaml.dump({"profiles": {"test": {"model": "test-model"}}}))

        # Patch __file__ so the engine-bundled path points to a nonexistent file,
        # allowing manifest_dir to be reached (new Layer 3 in the search order).
        fake_engine_dir = tmp_path / "engine_fake"
        fake_engine_dir.mkdir()
        monkeypatch.setattr(providers_module, "__file__", str(fake_engine_dir / "providers.py"))

        providers = load_providers_file(
            providers_file_path=None,
            manifest_dir=str(tmp_path),
            project_root=None,
        )
        assert "test" in providers.list_profiles()

    def test_load_from_project_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Load from project root when not in manifest dir and no engine-bundled file."""
        import cobuilder.engine.providers as providers_module

        providers_yaml = tmp_path / "providers.yaml"
        providers_yaml.write_text(yaml.dump({"profiles": {"root": {"model": "root-model"}}}))

        manifest_dir = tmp_path / "manifest"
        manifest_dir.mkdir()

        # Patch __file__ so the engine-bundled path points to a nonexistent file,
        # allowing project_root to be reached (new Layer 4 in the search order).
        fake_engine_dir = tmp_path / "engine_fake"
        fake_engine_dir.mkdir()
        monkeypatch.setattr(providers_module, "__file__", str(fake_engine_dir / "providers.py"))

        providers = load_providers_file(
            providers_file_path=None,
            manifest_dir=str(manifest_dir),
            project_root=str(tmp_path),
        )
        assert "root" in providers.list_profiles()

    def test_returns_empty_if_not_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns empty ProvidersFile when no file found (including engine-bundled path)."""
        import cobuilder.engine.providers as providers_module

        # Patch __file__ so the engine-bundled path points to a nonexistent directory,
        # ensuring we reach the "not found" path.
        fake_engine_dir = tmp_path / "engine_fake"
        fake_engine_dir.mkdir()
        monkeypatch.setattr(providers_module, "__file__", str(fake_engine_dir / "providers.py"))

        providers = load_providers_file(
            providers_file_path=None,
            manifest_dir=str(tmp_path / "nonexistent"),
            project_root=str(tmp_path / "also-nonexistent"),
        )
        assert len(providers.list_profiles()) == 0

    def test_warning_for_missing_explicit_path(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Logs warning when explicit path doesn't exist."""
        providers = load_providers_file(
            providers_file_path=str(tmp_path / "nonexistent.yaml"),
        )
        assert len(providers.list_profiles()) == 0
        assert "not found" in caplog.text

    def test_priority_explicit_over_manifest(self, tmp_path: Path) -> None:
        """Explicit path takes priority over manifest dir."""
        # Create in both locations
        explicit = tmp_path / "explicit.yaml"
        explicit.write_text(yaml.dump({"profiles": {"explicit": {"model": "explicit-model"}}}))

        manifest_dir = tmp_path / "manifest"
        manifest_dir.mkdir()
        (manifest_dir / "providers.yaml").write_text(
            yaml.dump({"profiles": {"manifest": {"model": "manifest-model"}}})
        )

        providers = load_providers_file(
            providers_file_path=str(explicit),
            manifest_dir=str(manifest_dir),
        )
        assert "explicit" in providers.list_profiles()
        assert "manifest" not in providers.list_profiles()


# ---------------------------------------------------------------------------
# get_llm_config_for_node Tests
# ---------------------------------------------------------------------------


class TestGetLLMConfigForNode:
    """Tests for the convenience function."""

    def test_extracts_node_attributes(self, loaded_providers: ProvidersFile) -> None:
        """Extracts llm_profile from node.attrs."""
        @dataclass
        class MockNode:
            id: str
            attrs: dict[str, Any]
            handler_type: str = "codergen"

        node = MockNode(
            id="test-node",
            attrs={"llm_profile": "anthropic-fast"},
        )

        config = get_llm_config_for_node(
            node=node,
            providers=loaded_providers,
        )
        assert config.profile_name == "anthropic-fast"

    def test_falls_back_to_property(self) -> None:
        """Falls back to llm_profile property if not in attrs."""
        @dataclass
        class MockNode:
            id: str
            attrs: dict[str, Any]
            llm_profile: str
            handler_type: str = "codergen"

        node = MockNode(
            id="test-node",
            attrs={},
            llm_profile="test-profile",
        )

        # With empty providers, will fall back to defaults
        config = get_llm_config_for_node(node=node)
        assert config.resolution_source in ("runner_default", "environment")

    def test_uses_empty_providers_if_none(self) -> None:
        """Uses empty ProvidersFile if none provided."""
        @dataclass
        class MockNode:
            id: str
            attrs: dict[str, Any]
            handler_type: str = "codergen"

        node = MockNode(id="test-node", attrs={})

        config = get_llm_config_for_node(node=node, providers=None)
        assert config is not None  # Should return a valid config


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end integration tests."""

    def test_full_resolution_chain(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test full resolution chain with a real providers.yaml."""
        # Set up environment
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-api-key")
        monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)

        # Create providers.yaml
        providers_yaml = tmp_path / "providers.yaml"
        providers_yaml.write_text(yaml.dump({
            "profiles": {
                "production": {
                    "model": "claude-sonnet-4-5-20250514",
                    "api_key": "$ANTHROPIC_API_KEY",
                },
                "development": {
                    "model": "claude-haiku-4-5-20251001",
                    "api_key": "$ANTHROPIC_API_KEY",
                },
            }
        }))

        # Load providers
        providers = ProvidersFile.from_file(providers_yaml)

        # Resolve for a node
        config = resolve_llm_config(
            node_llm_profile="production",
            handler_type="codergen",
            providers=providers,
            manifest_defaults=None,
            node_id="integration-test",
        )

        assert config.model == "claude-sonnet-4-5-20250514"
        assert config.api_key == "test-api-key"
        assert config.profile_name == "production"
        assert config.resolution_source == "node_profile"

        # Convert to env dict
        env = config.to_env_dict()
        assert env["ANTHROPIC_MODEL"] == "claude-sonnet-4-5-20250514"
        assert env["ANTHROPIC_API_KEY"] == "test-api-key"