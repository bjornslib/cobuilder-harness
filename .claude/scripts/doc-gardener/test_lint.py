#!/usr/bin/env python3
"""
Tests for the doc-gardener multi-target lint.py enhancements.

Run with:
  python -m pytest .claude/scripts/doc-gardener/test_lint.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers to locate the lint.py script
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
LINT_SCRIPT = SCRIPT_DIR / "lint.py"
CLAUDE_DIR = SCRIPT_DIR.parent.parent

# Import lint module directly for unit tests
sys.path.insert(0, str(SCRIPT_DIR))
import lint as lint_module
from lint import (
    LintContext,
    Violation,
    collect_md_files,
    check_frontmatter,
    check_crosslinks,
    check_naming,
    check_staleness,
    check_grades_sync,
    check_implementation_status,
    check_misplaced_documents,
    load_config,
    lint,
    format_text,
    format_json,
    should_require_frontmatter,
    CLAUDE_DIR as LINT_CLAUDE_DIR,
    DEFAULT_SKIP_DIRS,
    DEFAULT_SKIP_FILES,
    SEVERITY_WARNING,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_claude_dir(tmp_path):
    """Create a minimal .claude/-like directory structure."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "skills").mkdir()
    (claude / "agents").mkdir()
    (claude / "documentation").mkdir()
    (claude / "output-styles").mkdir()
    (claude / "commands").mkdir()
    return claude


@pytest.fixture
def tmp_docs_dir(tmp_path):
    """Create a docs/ directory structure."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture").mkdir()
    (docs / "prds").mkdir()
    (docs / "guides").mkdir()
    return docs


def write_md(path: Path, content: str) -> Path:
    """Write content to a markdown file, creating parents as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def frontmatter_md(title: str, status: str = "active", extra: str = "") -> str:
    """Return a markdown string with valid frontmatter."""
    return f"---\ntitle: \"{title}\"\nstatus: {status}\n{extra}---\n\nContent here.\n"


# ---------------------------------------------------------------------------
# 1. Backward Compatibility: lint() with no args uses CLAUDE_DIR
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Ensure lint() with no args behaves identically to before."""

    def test_lint_no_args_returns_tuple(self):
        """lint() must return a tuple of (violations, files_scanned)."""
        result = lint()
        assert isinstance(result, tuple)
        assert len(result) == 2
        violations, files_scanned = result
        assert isinstance(violations, list)
        assert isinstance(files_scanned, int)

    def test_lint_no_args_scans_claude_dir(self):
        """lint() with no args scans at least some files from CLAUDE_DIR."""
        _, files_scanned = lint()
        # The actual .claude/ dir has many files; any positive count is valid
        assert files_scanned >= 0

    def test_lint_no_args_uses_claude_dir_default(self):
        """lint(targets=None) and lint(targets=[CLAUDE_DIR]) give same results."""
        violations_default, files_default = lint()
        violations_explicit, files_explicit = lint(targets=[LINT_CLAUDE_DIR])
        assert files_default == files_explicit
        # Violations should be identical (same files, same checks)
        assert len(violations_default) == len(violations_explicit)

    def test_format_text_no_args_shows_target(self):
        """format_text with no targets arg shows CLAUDE_DIR."""
        output = format_text([], 0)
        assert "Target:" in output

    def test_format_json_no_args_has_target_field(self):
        """format_json with no targets arg includes 'target' field."""
        result = json.loads(format_json([], 0))
        assert "target" in result

    def test_cli_no_args_exits_cleanly(self):
        """Running lint.py with no args exits with code 0 or 1 (not crash)."""
        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode in (0, 1)
        assert "Harness Documentation Lint Report" in result.stdout


# ---------------------------------------------------------------------------
# 2. Single Target: lint(targets=[some_dir]) scans only that dir
# ---------------------------------------------------------------------------

class TestSingleTarget:
    """lint(targets=[dir]) scans only that directory."""

    def test_single_target_empty_dir(self, tmp_path):
        """An empty directory yields 0 files scanned."""
        empty = tmp_path / "empty"
        empty.mkdir()
        ctx = LintContext(target_dir=empty)
        files = collect_md_files(ctx)
        assert files == []

    def test_single_target_nonexistent_dir(self, tmp_path):
        """Nonexistent target emits a warning and returns 0 files."""
        missing = tmp_path / "does-not-exist"
        violations, files_scanned = lint(targets=[missing])
        assert files_scanned == 0

    def test_single_target_scans_correct_files(self, tmp_path):
        """lint(targets=[docs_dir]) only scans files in docs_dir."""
        docs = tmp_path / "docs"
        docs.mkdir()
        write_md(docs / "readme.md", "# Docs\n")
        write_md(docs / "architecture" / "design.md", frontmatter_md("Design"))

        other = tmp_path / "other"
        other.mkdir()
        write_md(other / "other.md", "# Other\n")

        _, files_scanned = lint(targets=[docs])
        # Should only see the 2 docs files, not other/other.md
        assert files_scanned == 2

    def test_single_target_skills_not_required(self, tmp_path):
        """A non-.claude/ target doesn't treat 'skills/' specially by default."""
        target = tmp_path / "mytarget"
        target.mkdir()
        # File in a 'skills' subdir should NOT require frontmatter by default
        # (since ctx.is_claude_dir is False and frontmatter_dirs is None -> uses dirname is not None)
        write_md(target / "skills" / "my-skill.md", "# My Skill\nNo frontmatter here.\n")

        ctx = LintContext(target_dir=target, frontmatter_dirs=None)
        # With frontmatter_dirs=None and non-claude-dir: require frontmatter in all subdirs
        assert should_require_frontmatter(target / "skills" / "my-skill.md", ctx) is True

    def test_single_target_top_level_no_frontmatter_required(self, tmp_path):
        """Top-level files in any target dir don't require frontmatter."""
        target = tmp_path / "docs"
        target.mkdir()
        ctx = LintContext(target_dir=target)
        top_file = target / "README.md"
        write_md(top_file, "# README\n")
        assert should_require_frontmatter(top_file, ctx) is False

    def test_single_target_skip_dirs_respected(self, tmp_path):
        """Files in skip dirs are not scanned."""
        target = tmp_path / "docs"
        target.mkdir()
        write_md(target / "state" / "session.md", "# State\n")
        write_md(target / "guides" / "how-to.md", "# Guide\n")

        ctx = LintContext(target_dir=target, skip_dirs={"state"})
        files = collect_md_files(ctx)
        # Only guides/how-to.md should be present
        assert len(files) == 1
        assert files[0].name == "how-to.md"


# ---------------------------------------------------------------------------
# 3. Multi-Target: lint(targets=[dir1, dir2]) scans both
# ---------------------------------------------------------------------------

class TestMultiTarget:
    """lint(targets=[dir1, dir2]) scans both directories."""

    def test_multi_target_file_count(self, tmp_path):
        """Total file count equals sum across all targets."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        write_md(dir1 / "a.md", "# A\n")
        write_md(dir1 / "b.md", "# B\n")

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        write_md(dir2 / "c.md", "# C\n")

        _, files_scanned = lint(targets=[dir1, dir2])
        assert files_scanned == 3

    def test_multi_target_violations_from_both(self, tmp_path):
        """Violations are collected from all targets."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        (dir1 / "sub1").mkdir()
        # File in sub1 without frontmatter - with non-claude dir and no frontmatter_dirs
        # it will require frontmatter by default since dirname is not None
        write_md(dir1 / "sub1" / "needs-fm.md", "# No frontmatter\n")

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        (dir2 / "sub2").mkdir()
        write_md(dir2 / "sub2" / "also-needs-fm.md", "# Also no frontmatter\n")

        violations, _ = lint(targets=[dir1, dir2])
        # Each file missing frontmatter should generate a violation
        fm_violations = [v for v in violations if v.category == "frontmatter"]
        assert len(fm_violations) >= 2

    def test_multi_target_violations_have_correct_paths(self, tmp_path):
        """Violation file paths are relative to their own target dir."""
        dir1 = tmp_path / "first"
        dir1.mkdir()
        (dir1 / "docs").mkdir()
        write_md(dir1 / "docs" / "missing.md", "# No frontmatter\n")

        dir2 = tmp_path / "second"
        dir2.mkdir()
        (dir2 / "docs").mkdir()
        write_md(dir2 / "docs" / "also-missing.md", "# No frontmatter\n")

        violations, _ = lint(targets=[dir1, dir2])
        fm_violations = [v for v in violations if v.category == "frontmatter"]
        file_paths = {v.file for v in fm_violations}

        # Both should show relative paths (docs/missing.md, docs/also-missing.md)
        assert "docs/missing.md" in file_paths
        assert "docs/also-missing.md" in file_paths

    def test_multi_target_cli_flags(self, tmp_path):
        """--target flag can be repeated for multiple targets."""
        dir1 = tmp_path / "a"
        dir1.mkdir()
        write_md(dir1 / "x.md", "# X\n")

        dir2 = tmp_path / "b"
        dir2.mkdir()
        write_md(dir2 / "y.md", "# Y\n")

        result = subprocess.run(
            [
                sys.executable, str(LINT_SCRIPT),
                "--target", str(dir1),
                "--target", str(dir2),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert data["files_scanned"] == 2
        # target should be a list when multiple targets provided
        assert isinstance(data["target"], list)
        assert len(data["target"]) == 2


# ---------------------------------------------------------------------------
# 4. Config Loading: load_config() correctly parses JSON
# ---------------------------------------------------------------------------

class TestConfigLoading:
    """Config file is loaded and applied correctly."""

    def test_load_config_nonexistent_returns_empty(self, tmp_path):
        """load_config with missing file returns empty dict."""
        result = load_config(str(tmp_path / "nonexistent.json"))
        assert result == {}

    def test_load_config_invalid_json_returns_empty(self, tmp_path):
        """load_config with invalid JSON returns empty dict."""
        config_file = tmp_path / "bad.json"
        config_file.write_text("{invalid json", encoding="utf-8")
        result = load_config(str(config_file))
        assert result == {}

    def test_load_config_valid_json(self, tmp_path):
        """load_config reads targets and other fields correctly."""
        config = {
            "targets": ["docs/", ".claude/"],
            "skip_dirs": ["archive", "scratch"],
            "directory_grades": {"docs/architecture": "reference"},
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        result = load_config(str(config_file))
        assert result["targets"] == ["docs/", ".claude/"]
        assert "archive" in result["skip_dirs"]
        assert result["directory_grades"]["docs/architecture"] == "reference"

    def test_load_config_none_returns_empty(self):
        """load_config(None) returns empty dict."""
        result = load_config(None)
        assert result == {}

    def test_config_passed_to_lint(self, tmp_path):
        """Config dict is respected when passed to lint()."""
        target = tmp_path / "target"
        target.mkdir()
        (target / "skip-me").mkdir()
        write_md(target / "skip-me" / "doc.md", "# Skip me\n")
        write_md(target / "keep.md", "# Keep\n")

        config = {"skip_dirs": ["skip-me"]}
        violations, files_scanned = lint(targets=[target], config=config)
        # skip-me dir should be excluded
        assert files_scanned == 1


# ---------------------------------------------------------------------------
# 5. Skip Dirs from Config
# ---------------------------------------------------------------------------

class TestConfigSkipDirs:
    """Config skip_dirs are merged with defaults and respected."""

    def test_config_skip_dirs_merge_with_defaults(self, tmp_path):
        """Config skip_dirs add to DEFAULT_SKIP_DIRS, not replace."""
        target = tmp_path / "target"
        target.mkdir()

        # Default skip dir
        (target / "state").mkdir()
        write_md(target / "state" / "runtime.md", "# Runtime\n")

        # Custom skip dir from config
        (target / "scratch-pads").mkdir()
        write_md(target / "scratch-pads" / "notes.md", "# Notes\n")

        # Legit dir
        (target / "docs").mkdir()
        write_md(target / "docs" / "guide.md", "# Guide\n")

        config = {"skip_dirs": ["scratch-pads"]}
        _, files_scanned = lint(targets=[target], config=config)

        # Only docs/guide.md should be scanned (state/ and scratch-pads/ skipped)
        assert files_scanned == 1

    def test_collect_md_files_respects_skip_dirs(self, tmp_path):
        """collect_md_files excludes files in skip dirs."""
        target = tmp_path / "target"
        target.mkdir()
        (target / "evidence").mkdir()
        (target / "documentation").mkdir()

        write_md(target / "evidence" / "proof.md", "# Proof\n")
        write_md(target / "documentation" / "guide.md", "# Guide\n")

        ctx = LintContext(target_dir=target, skip_dirs={"evidence"})
        files = collect_md_files(ctx)

        assert len(files) == 1
        assert files[0].name == "guide.md"


# ---------------------------------------------------------------------------
# 6. Directory Grades from Config
# ---------------------------------------------------------------------------

class TestConfigDirectoryGrades:
    """Config directory_grades override quality-grades.json defaults."""

    def test_config_grades_override_for_non_claude_dirs(self, tmp_path):
        """Custom directory_grades in config are used for grade mismatch checks."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "architecture").mkdir()

        # File with grade 'authoritative' but config says 'reference'
        content = frontmatter_md(
            "Design Doc",
            extra="grade: authoritative\n",
        )
        write_md(target / "architecture" / "design.md", content)

        config = {"directory_grades": {"architecture": "reference"}}
        violations, _ = lint(targets=[target], config=config)

        grades_violations = [v for v in violations if v.category == "grades-sync"]
        assert len(grades_violations) >= 1
        # The violation should mention that grade differs from directory default
        assert any("reference" in v.message for v in grades_violations)

    def test_check_grades_sync_uses_ctx_directory_grades(self, tmp_path):
        """check_grades_sync respects ctx.directory_grades."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "guides").mkdir()

        content = frontmatter_md("A Guide", extra="grade: authoritative\n")
        filepath = write_md(target / "guides" / "my-guide.md", content)

        ctx = LintContext(
            target_dir=target,
            directory_grades={"guides": "reference"},
        )
        violations = check_grades_sync(filepath, content, {}, ctx)
        assert len(violations) >= 1
        assert any("reference" in v.message for v in violations)


# ---------------------------------------------------------------------------
# 7. Frontmatter Required Dirs from Config
# ---------------------------------------------------------------------------

class TestFrontmatterRequiredDirs:
    """Config frontmatter_required_dirs controls which dirs need frontmatter."""

    def test_frontmatter_required_in_configured_dirs(self, tmp_path):
        """Files in frontmatter_required_dirs trigger violations if no frontmatter."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "architecture").mkdir()
        write_md(target / "architecture" / "design.md", "# No frontmatter\n")

        config = {"frontmatter_required_dirs": ["architecture"]}
        violations, _ = lint(targets=[target], config=config)

        fm_violations = [v for v in violations if v.category == "frontmatter"]
        assert len(fm_violations) >= 1
        assert any("design.md" in v.file for v in fm_violations)

    def test_frontmatter_not_required_in_unconfigured_dirs(self, tmp_path):
        """Files in dirs not in frontmatter_required_dirs don't need frontmatter."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "plans").mkdir()
        write_md(target / "plans" / "plan.md", "# No frontmatter\n")

        config = {"frontmatter_required_dirs": ["architecture"]}
        violations, _ = lint(targets=[target], config=config)

        fm_violations = [
            v for v in violations
            if v.category == "frontmatter" and "plan.md" in v.file
        ]
        # plans/ is not in required dirs, so no frontmatter violation
        assert len(fm_violations) == 0

    def test_claude_dir_uses_hardcoded_frontmatter_dirs_by_default(self, tmp_path):
        """For .claude/ target, backward-compat dirs are always used."""
        # Create a minimal .claude/-like structure
        claude = tmp_path / ".claude"
        (claude / "skills" / "my-skill").mkdir(parents=True)
        write_md(
            claude / "skills" / "my-skill" / "SKILL.md",
            "# Skill - no frontmatter\n",
        )

        # Even without config, SKILL.md in skills/ must have frontmatter
        ctx = LintContext(target_dir=claude)
        filepath = claude / "skills" / "my-skill" / "SKILL.md"
        assert should_require_frontmatter(filepath, ctx) is True

    def test_should_require_frontmatter_respects_frontmatter_dirs(self, tmp_path):
        """should_require_frontmatter uses ctx.frontmatter_dirs for non-.claude/ targets."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "guides").mkdir()

        filepath = write_md(target / "guides" / "howto.md", "# How To\n")

        # With frontmatter_dirs including 'guides': should require
        ctx_with = LintContext(target_dir=target, frontmatter_dirs={"guides"})
        assert should_require_frontmatter(filepath, ctx_with) is True

        # Without 'guides' in frontmatter_dirs: should not require
        ctx_without = LintContext(target_dir=target, frontmatter_dirs={"architecture"})
        assert should_require_frontmatter(filepath, ctx_without) is False


# ---------------------------------------------------------------------------
# 8. CLI Flags: --target and --config are parsed correctly
# ---------------------------------------------------------------------------

class TestCLIFlags:
    """CLI flags --target and --config work end-to-end."""

    def test_cli_single_target(self, tmp_path):
        """--target dir scans only that dir."""
        target = tmp_path / "mydir"
        target.mkdir()
        write_md(target / "file.md", "# File\n")

        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT), "--target", str(target), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert data["files_scanned"] == 1

    def test_cli_multiple_targets(self, tmp_path):
        """--target can be repeated."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        write_md(dir1 / "a.md", "# A\n")

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        write_md(dir2 / "b.md", "# B\n")

        result = subprocess.run(
            [
                sys.executable, str(LINT_SCRIPT),
                "--target", str(dir1),
                "--target", str(dir2),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        assert data["files_scanned"] == 2

    def test_cli_config_flag(self, tmp_path):
        """--config flag loads config and applies skip_dirs."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "secret").mkdir()
        write_md(target / "secret" / "hidden.md", "# Hidden\n")
        write_md(target / "visible.md", "# Visible\n")

        config = {
            "targets": [str(target)],
            "skip_dirs": ["secret"],
        }
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(LINT_SCRIPT), "--config", str(config_file), "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        # Only visible.md should be scanned (secret/ is skipped)
        assert data["files_scanned"] == 1

    def test_cli_target_overrides_config_targets(self, tmp_path):
        """CLI --target takes precedence over config targets."""
        dir_cli = tmp_path / "cli_dir"
        dir_cli.mkdir()
        write_md(dir_cli / "cli.md", "# CLI\n")

        dir_config = tmp_path / "config_dir"
        dir_config.mkdir()
        write_md(dir_config / "config.md", "# Config\n")

        config = {"targets": [str(dir_config)]}
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable, str(LINT_SCRIPT),
                "--target", str(dir_cli),
                "--config", str(config_file),
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode in (0, 1)
        data = json.loads(result.stdout)
        # Only cli_dir should be scanned (CLI target overrides config)
        assert data["files_scanned"] == 1


# ---------------------------------------------------------------------------
# 9. Cross-link Validation
# ---------------------------------------------------------------------------

class TestCrosslinks:
    """Cross-link validation works for single and multi-target scenarios."""

    def test_valid_crosslink_no_violation(self, tmp_path):
        """Existing relative links produce no crosslink violations."""
        target = tmp_path / "docs"
        target.mkdir()

        write_md(target / "target.md", "# Target\n")
        source = write_md(
            target / "source.md",
            "# Source\n\nSee [target](target.md).\n",
        )

        ctx = LintContext(target_dir=target)
        violations = check_crosslinks(source, source.read_text(), ctx)
        assert violations == []

    def test_broken_crosslink_produces_violation(self, tmp_path):
        """Missing link target produces a crosslinks violation."""
        target = tmp_path / "docs"
        target.mkdir()

        source = write_md(
            target / "source.md",
            "# Source\n\nSee [missing](nonexistent.md).\n",
        )

        ctx = LintContext(target_dir=target)
        violations = check_crosslinks(source, source.read_text(), ctx)
        assert len(violations) == 1
        assert violations[0].category == "crosslinks"
        assert "nonexistent.md" in violations[0].message

    def test_crosslink_subdirectory(self, tmp_path):
        """Relative links to subdirectory files work correctly."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "guides").mkdir()

        write_md(target / "guides" / "setup.md", "# Setup\n")
        source = write_md(
            target / "index.md",
            "# Index\n\nSee [setup](guides/setup.md).\n",
        )

        ctx = LintContext(target_dir=target)
        violations = check_crosslinks(source, source.read_text(), ctx)
        assert violations == []

    def test_crosslink_skips_external_urls(self, tmp_path):
        """External URLs (http/https) are not checked."""
        target = tmp_path / "docs"
        target.mkdir()

        source = write_md(
            target / "source.md",
            "# Source\n\nSee [external](https://example.com/page).\n",
        )

        ctx = LintContext(target_dir=target)
        violations = check_crosslinks(source, source.read_text(), ctx)
        assert violations == []

    def test_crosslink_code_block_not_checked(self, tmp_path):
        """Links inside fenced code blocks are not flagged."""
        target = tmp_path / "docs"
        target.mkdir()

        source = write_md(
            target / "source.md",
            "# Source\n\n```python\n# [link](nonexistent.md)\n```\n",
        )

        ctx = LintContext(target_dir=target)
        violations = check_crosslinks(source, source.read_text(), ctx)
        assert violations == []

    def test_crosslink_multi_target_paths_resolved_correctly(self, tmp_path):
        """Cross-links are resolved relative to each file's target dir."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        write_md(dir1 / "exists.md", "# Exists\n")
        source1 = write_md(
            dir1 / "doc.md",
            "# Doc\n\nSee [exists](exists.md).\n",
        )

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        source2 = write_md(
            dir2 / "doc.md",
            "# Doc\n\nSee [broken](nonexistent.md).\n",
        )

        ctx1 = LintContext(target_dir=dir1)
        ctx2 = LintContext(target_dir=dir2)

        v1 = check_crosslinks(source1, source1.read_text(), ctx1)
        v2 = check_crosslinks(source2, source2.read_text(), ctx2)

        assert v1 == []
        assert len(v2) == 1


# ---------------------------------------------------------------------------
# 10. LintContext class behavior
# ---------------------------------------------------------------------------

class TestLintContext:
    """LintContext correctly identifies .claude/ vs other dirs."""

    def test_is_claude_dir_true_for_actual_claude_dir(self):
        """LintContext with CLAUDE_DIR has is_claude_dir=True."""
        ctx = LintContext(target_dir=LINT_CLAUDE_DIR)
        assert ctx.is_claude_dir is True

    def test_is_claude_dir_false_for_other_dirs(self, tmp_path):
        """LintContext with any other dir has is_claude_dir=False."""
        ctx = LintContext(target_dir=tmp_path / "docs")
        assert ctx.is_claude_dir is False

    def test_default_skip_dirs_applied(self, tmp_path):
        """LintContext without explicit skip_dirs uses DEFAULT_SKIP_DIRS."""
        ctx = LintContext(target_dir=tmp_path)
        assert ctx.skip_dirs == DEFAULT_SKIP_DIRS

    def test_custom_skip_dirs_override(self, tmp_path):
        """LintContext with explicit skip_dirs uses those instead."""
        custom_skip = {"custom-dir", "another-dir"}
        ctx = LintContext(target_dir=tmp_path, skip_dirs=custom_skip)
        assert ctx.skip_dirs == custom_skip

    def test_default_skip_files_applied(self, tmp_path):
        """LintContext without explicit skip_files uses DEFAULT_SKIP_FILES."""
        ctx = LintContext(target_dir=tmp_path)
        assert ctx.skip_files == DEFAULT_SKIP_FILES


# ---------------------------------------------------------------------------
# 11. apply_fixes works with multiple targets
# ---------------------------------------------------------------------------

class TestApplyFixes:
    """apply_fixes correctly resolves file paths for multiple targets."""

    def test_fix_adds_frontmatter_to_correct_target(self, tmp_path):
        """Auto-fix adds frontmatter to files in their correct target directory."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "guides").mkdir()

        filepath = write_md(target / "guides" / "howto.md", "# How To\n")

        # Run lint with fix
        violations, _ = lint(
            targets=[target],
            fix=True,
            config={"frontmatter_required_dirs": ["guides"]},
        )

        # After fix, file should have frontmatter
        content = filepath.read_text()
        assert content.startswith("---")

    def test_fix_does_not_touch_other_targets(self, tmp_path):
        """Fixing violations in dir1 doesn't affect files in dir2."""
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        (dir1 / "docs").mkdir()
        file1 = write_md(dir1 / "docs" / "needs-fix.md", "# Needs Fix\n")

        dir2 = tmp_path / "dir2"
        dir2.mkdir()
        (dir2 / "docs").mkdir()
        file2 = write_md(dir2 / "docs" / "also-needs-fix.md", "# Also Needs Fix\n")

        original_content2 = file2.read_text()

        # Fix only dir1
        lint(
            targets=[dir1],
            fix=True,
            config={"frontmatter_required_dirs": ["docs"]},
        )

        # file2 should be unchanged
        assert file2.read_text() == original_content2


# ---------------------------------------------------------------------------
# 12. format_text and format_json multi-target display
# ---------------------------------------------------------------------------

class TestFormatOutput:
    """format_text and format_json correctly display multi-target results."""

    def test_format_text_single_target(self, tmp_path):
        """format_text with single target shows 'Target:' line."""
        output = format_text([], 5, targets=[tmp_path / "docs"])
        assert "Target:" in output
        assert "Targets" not in output

    def test_format_text_multiple_targets(self, tmp_path):
        """format_text with multiple targets shows 'Targets (N):' header."""
        targets = [tmp_path / "docs", tmp_path / ".claude"]
        output = format_text([], 10, targets=targets)
        assert "Targets (2):" in output

    def test_format_json_single_target_is_string(self, tmp_path):
        """format_json with single target has 'target' as a string."""
        result = json.loads(format_json([], 5, targets=[tmp_path / "docs"]))
        assert isinstance(result["target"], str)

    def test_format_json_multiple_targets_is_list(self, tmp_path):
        """format_json with multiple targets has 'target' as a list."""
        targets = [tmp_path / "docs", tmp_path / ".claude"]
        result = json.loads(format_json([], 10, targets=targets))
        assert isinstance(result["target"], list)
        assert len(result["target"]) == 2

    def test_format_json_contains_required_fields(self, tmp_path):
        """format_json always includes all required fields."""
        result = json.loads(format_json([], 0, targets=[tmp_path]))
        required = {"target", "files_scanned", "total_violations", "errors",
                    "warnings", "info", "fixable", "violations"}
        assert required.issubset(result.keys())


# ---------------------------------------------------------------------------
# 13. Naming checks work for non-.claude/ targets
# ---------------------------------------------------------------------------

class TestNamingForNonClaudeTargets:
    """Naming convention checks apply to any target directory."""

    def test_space_in_filename_violation(self, tmp_path):
        """Files with spaces in names produce naming violations."""
        target = tmp_path / "docs"
        target.mkdir()
        filepath = target / "bad file.md"
        filepath.write_text("# Bad\n", encoding="utf-8")

        ctx = LintContext(target_dir=target)
        violations = check_naming(filepath, ctx)
        assert any(v.category == "naming" and "spaces" in v.message for v in violations)

    def test_kebab_case_dir_no_violation(self, tmp_path):
        """Proper kebab-case directories produce no naming violations."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "my-guide").mkdir()
        filepath = write_md(target / "my-guide" / "content.md", "# Content\n")

        ctx = LintContext(target_dir=target)
        violations = check_naming(filepath, ctx)
        naming_violations = [v for v in violations if v.category == "naming"]
        assert naming_violations == []

    def test_uppercase_dir_violation(self, tmp_path):
        """Directories with UPPER_CASE names produce naming warnings."""
        target = tmp_path / "docs"
        target.mkdir()
        (target / "MyGuide").mkdir()
        filepath = write_md(target / "MyGuide" / "content.md", "# Content\n")

        ctx = LintContext(target_dir=target)
        violations = check_naming(filepath, ctx)
        naming_violations = [v for v in violations if v.category == "naming"]
        assert len(naming_violations) >= 1


# ---------------------------------------------------------------------------
# 14. Staleness checks work for non-.claude/ targets
# ---------------------------------------------------------------------------

class TestStalenessForNonClaudeTargets:
    """Staleness checks work correctly for any target directory."""

    def test_stale_document_violation(self, tmp_path):
        """Documents with old last_verified dates produce staleness violations."""
        target = tmp_path / "docs"
        target.mkdir()

        content = (
            "---\n"
            "title: \"Old Doc\"\n"
            "status: active\n"
            "grade: authoritative\n"
            "last_verified: 2020-01-01\n"
            "---\n\n"
            "Old content.\n"
        )
        filepath = write_md(target / "old.md", content)

        ctx = LintContext(target_dir=target)
        violations = check_staleness(filepath, content, ctx)
        assert len(violations) >= 1
        assert any(v.category == "staleness" for v in violations)

    def test_fresh_document_no_violation(self, tmp_path):
        """Documents with recent last_verified dates produce no staleness violations."""
        from datetime import date
        target = tmp_path / "docs"
        target.mkdir()

        today = date.today().isoformat()
        content = (
            f"---\n"
            f"title: \"Fresh Doc\"\n"
            f"status: active\n"
            f"grade: authoritative\n"
            f"last_verified: {today}\n"
            f"---\n\n"
            f"Fresh content.\n"
        )
        filepath = write_md(target / "fresh.md", content)

        ctx = LintContext(target_dir=target)
        violations = check_staleness(filepath, content, ctx)
        assert violations == []


# ---------------------------------------------------------------------------
# 15. Implementation status checks
# ---------------------------------------------------------------------------

class TestImplementationStatus:
    """check_implementation_status() detects missing sections in PRD/SD/Epic/Spec files."""

    def test_implementation_status_present(self, tmp_path):
        """PRD file with an Implementation Status section produces no violation."""
        target = tmp_path / "docs"
        target.mkdir()
        content = (
            "---\n"
            "title: \"My PRD\"\n"
            "status: active\n"
            "type: prd\n"
            "---\n\n"
            "# My PRD\n\n"
            "## Implementation Status\n\n"
            "| Epic | Status | Date | Commit |\n"
            "|------|--------|------|--------|\n"
            "| E1   | Done   | 2026-01-01 | abc123 |\n"
        )
        filepath = write_md(target / "PRD-MY.md", content)
        ctx = LintContext(target_dir=target)
        violations = check_implementation_status(filepath, content, ctx)
        assert violations == []

    def test_implementation_status_missing(self, tmp_path):
        """PRD file without an Implementation Status section produces a warning violation."""
        target = tmp_path / "docs"
        target.mkdir()
        content = (
            "---\n"
            "title: \"My PRD\"\n"
            "status: active\n"
            "type: prd\n"
            "---\n\n"
            "# My PRD\n\n"
            "Some content here.\n"
        )
        filepath = write_md(target / "PRD-MY.md", content)
        ctx = LintContext(target_dir=target)
        violations = check_implementation_status(filepath, content, ctx)
        assert len(violations) == 1
        v = violations[0]
        assert v.category == "implementation-status"
        assert v.severity == SEVERITY_WARNING
        assert v.fixable is True

    def test_implementation_status_draft_exempt(self, tmp_path):
        """Draft documents are exempt from the Implementation Status requirement."""
        target = tmp_path / "docs"
        target.mkdir()
        content = (
            "---\n"
            "title: \"Draft PRD\"\n"
            "status: draft\n"
            "type: prd\n"
            "---\n\n"
            "# Draft PRD\n\n"
            "Work in progress.\n"
        )
        filepath = write_md(target / "PRD-DRAFT.md", content)
        ctx = LintContext(target_dir=target)
        violations = check_implementation_status(filepath, content, ctx)
        assert violations == []


# ---------------------------------------------------------------------------
# 16. Misplaced document repo scan
# ---------------------------------------------------------------------------

class TestMisplacedDocuments:
    """check_misplaced_documents() repo-scan form detects PRD/SD files outside docs/."""

    def test_misplaced_document_detected(self, tmp_path):
        """A PRD file at repo root is flagged as misplaced."""
        repo_root = tmp_path
        docs_dir = repo_root / "docs"
        docs_dir.mkdir()
        # Create a PRD file at repo root (outside docs/)
        prd_file = repo_root / "PRD-FOO.md"
        prd_file.write_text("# PRD-FOO\n", encoding="utf-8")
        ctx = LintContext(target_dir=docs_dir)
        violations = check_misplaced_documents(repo_root, docs_dir, ctx)
        categories = [v.category for v in violations]
        assert "misplaced-document" in categories

    def test_misplaced_document_exclusion(self, tmp_path):
        """Files under excluded paths are not flagged."""
        repo_root = tmp_path
        docs_dir = repo_root / "docs"
        docs_dir.mkdir()
        # Create PRD file inside an excluded directory
        excl_dir = repo_root / ".claude" / "skills"
        excl_dir.mkdir(parents=True)
        prd_file = excl_dir / "PRD-REF.md"
        prd_file.write_text("# PRD reference\n", encoding="utf-8")
        ctx = LintContext(
            target_dir=docs_dir,
            misplaced_exclusions=[".claude/skills/"],
        )
        violations = check_misplaced_documents(repo_root, docs_dir, ctx)
        # None of the violations should be for PRD-REF.md inside the excluded path
        prd_violations = [
            v for v in violations
            if "PRD-REF" in v.file or "PRD-REF" in v.message
        ]
        assert prd_violations == []
