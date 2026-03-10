"""Tests for cobuilder/dirs.py — centralized path resolution.

Covers:
- COBUILDER_STATE_DIR env var override
- Walk-up discovery of .cobuilder/
- Legacy fallback to .claude/attractor/
- Default creation in CWD
- Subdirectory helpers
"""

import os
from pathlib import Path

import pytest

from cobuilder.dirs import (
    get_state_dir,
    get_pipelines_dir,
    get_signals_dir,
    get_checkpoints_dir,
    get_runner_state_dir,
    get_examples_dir,
)


class TestEnvVarOverride:
    def test_env_var_takes_priority(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom-state"
        monkeypatch.setenv("COBUILDER_STATE_DIR", str(custom))
        result = get_state_dir(create=True)
        assert result == custom
        assert custom.is_dir()

    def test_env_var_no_create(self, tmp_path, monkeypatch):
        custom = tmp_path / "no-create"
        monkeypatch.setenv("COBUILDER_STATE_DIR", str(custom))
        result = get_state_dir(create=False)
        assert result == custom
        assert not custom.exists()


class TestWalkUpDiscovery:
    def test_finds_cobuilder_in_parent(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COBUILDER_STATE_DIR", raising=False)
        # Create .cobuilder/ at project root
        (tmp_path / ".cobuilder").mkdir()
        # CWD is a subdirectory
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        result = get_state_dir(create=False)
        assert result == tmp_path / ".cobuilder"

    def test_legacy_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COBUILDER_STATE_DIR", raising=False)
        # Create legacy .claude/attractor/ at project root
        (tmp_path / ".claude" / "attractor").mkdir(parents=True)
        subdir = tmp_path / "src"
        subdir.mkdir()
        monkeypatch.chdir(subdir)
        result = get_state_dir(create=False)
        assert result == tmp_path / ".claude" / "attractor"

    def test_cobuilder_preferred_over_legacy(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COBUILDER_STATE_DIR", raising=False)
        # Both exist — .cobuilder/ should win
        (tmp_path / ".cobuilder").mkdir()
        (tmp_path / ".claude" / "attractor").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        result = get_state_dir(create=False)
        assert result == tmp_path / ".cobuilder"


class TestDefaultCreation:
    def test_creates_cobuilder_in_cwd(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COBUILDER_STATE_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        result = get_state_dir(create=True)
        assert result == tmp_path / ".cobuilder"
        assert result.is_dir()


class TestSubdirectoryHelpers:
    def test_pipelines_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COBUILDER_STATE_DIR", str(tmp_path))
        result = get_pipelines_dir()
        assert result == tmp_path / "pipelines"
        assert result.is_dir()

    def test_signals_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COBUILDER_STATE_DIR", str(tmp_path))
        result = get_signals_dir()
        assert result == tmp_path / "signals"
        assert result.is_dir()

    def test_checkpoints_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COBUILDER_STATE_DIR", str(tmp_path))
        result = get_checkpoints_dir()
        assert result == tmp_path / "checkpoints"
        assert result.is_dir()

    def test_runner_state_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COBUILDER_STATE_DIR", str(tmp_path))
        result = get_runner_state_dir()
        assert result == tmp_path / "runner-state"
        assert result.is_dir()

    def test_examples_dir_no_autocreate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COBUILDER_STATE_DIR", str(tmp_path))
        result = get_examples_dir(create=False)
        assert result == tmp_path / "examples"
        assert not result.exists()
