#!/usr/bin/env python3
"""
Documentation linter for .claude/ harness directory.

Checks (5 categories):
  1. Frontmatter validation (SKILL.md, CLAUDE.md, agent .md files)
  2. Cross-link integrity (verify internal links resolve)
  3. Staleness detection (files not updated in configurable period)
  4. Naming conventions (kebab-case for dirs, UPPER for top-level docs)
  5. Quality-grades sync (grade assignments match directory defaults)

Usage:
  python .claude/scripts/doc-gardener/lint.py                  # Full scan, text output
  python .claude/scripts/doc-gardener/lint.py --dry-run        # Same as default (no changes)
  python .claude/scripts/doc-gardener/lint.py --verbose        # Show all files scanned
  python .claude/scripts/doc-gardener/lint.py --json           # Machine-readable output
  python .claude/scripts/doc-gardener/lint.py --fix            # Auto-fix what's possible
  python .claude/scripts/doc-gardener/lint.py --target docs/   # Scan specific directory
  python .claude/scripts/doc-gardener/lint.py --target docs/ --target .claude/  # Multiple targets
  python .claude/scripts/doc-gardener/lint.py --config docs-gardener.config.json  # Use config file

Exit codes:
  0 = no violations
  1 = violations found
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
# .claude/ is two levels up from scripts/doc-gardener/
CLAUDE_DIR = SCRIPT_DIR.parent.parent
QUALITY_GRADES_FILE = SCRIPT_DIR / "quality-grades.json"

VALID_GRADES = {"authoritative", "reference", "archive", "draft"}
VALID_STATUSES = {"active", "draft", "archived", "deprecated"}

# Harness-specific document types
VALID_TYPES = {
    "skill",          # SKILL.md files
    "agent",          # Agent definition files
    "output-style",   # Output style definitions
    "hook",           # Hook documentation
    "command",        # Slash command docs
    "guide",          # Guides and how-tos
    "architecture",   # Architecture decisions
    "reference",      # Reference material
    "config",         # Configuration docs
}

# Document types that appear in docs/ targets (broader than harness types)
VALID_DOCS_TYPES = {
    "prd",
    "sd",
    "epic",
    "specification",
    "research",
    "guide",
    "reference",
    "architecture",
}

# Template appended to PRD/SD/Epic/Spec files missing an Implementation Status section
IMPL_STATUS_TEMPLATE = """

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
"""

# Directories to skip entirely (runtime state, not documentation)
DEFAULT_SKIP_DIRS = {
    "state",
    "completion-state",
    "evidence",
    "progress",
    "worker-assignments",
    "user-input-queue",
}

# Specific files to skip (paths relative to target dir)
# gardening-report.md is auto-generated and contains markdown link syntax
# in its violation tables, causing self-referential crosslink false positives.
DEFAULT_SKIP_FILES = {
    "documentation/gardening-report.md",
}

# Top-level files that should use UPPER_CASE naming
UPPER_CASE_FILES = {"CLAUDE.md", "README.md", "INDEX.md", "CHANGELOG.md"}

# Files within skills/ that must exist
SKILL_REQUIRED_FILES = {"SKILL.md"}

# Staleness thresholds (days)
STALENESS_ARCHIVE = 90   # >90 days -> grade should be archive
STALENESS_REFERENCE = 60  # >60 days -> grade should be reference or lower

# Naming: kebab-case for directories
KEBAB_DIR_PATTERN = re.compile(
    r"^([a-z0-9]+(-[a-z0-9]+)*"                                     # standard kebab-case
    r"|(SD|PRD|TS|EPIC|SPEC|MANUAL|GAP)-[A-Za-z0-9][-A-Za-z0-9.]*)$"  # doc-id prefixed dirs
)

# Naming: kebab-case for files (with optional date prefix)
KEBAB_FILE_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}-)?"   # optional date prefix
    r"[a-z0-9]+(-[a-z0-9]+)*"   # kebab-case body
    r"\.[a-z]+$"                  # extension
)

# UPPER_CASE pattern for top-level docs (e.g. CLAUDE.md, SKILL.md)
# Allows hyphens for UPPER-WITH-HYPHENS convention (NATIVE-TEAMS-FINDINGS.md)
UPPER_FILE_PATTERN = re.compile(
    r"^[A-Z][A-Z0-9_-]*"  # UPPER start (hyphens allowed)
    r"\.[a-z]+$"           # extension
)

# Mixed: one or more UPPER word groups followed by kebab suffix
# Handles: ADR-001-foo.md, PRD-S3-ATTRACTOR-001-testing.md, SOLUTION-DESIGN-acceptance-testing.md
MIXED_FILE_PATTERN = re.compile(
    r"^([A-Z][A-Z0-9._]*-)+[a-z0-9]+(-[a-z0-9]+)*\.[a-z]+$"
)

# Kebab-case prefix with UPPER suffix (registry-SKILL.md, config-README.md)
KEBAB_UPPER_FILE_PATTERN = re.compile(
    r"^[a-z0-9]+(-[a-z0-9]+)*-[A-Z][A-Z0-9_]*\.[a-z]+$"
)

# Version-prefixed files (v3.9-foo.md, v2-bar.md)
VERSION_FILE_PATTERN = re.compile(
    r"^v\d+(\.\d+)*-[a-z0-9]+(-[a-z0-9]+)*\.[a-z]+$"
)

# Underscore-prefixed private files (_sections.md, _template.md)
UNDERSCORE_FILE_PATTERN = re.compile(
    r"^_[a-z0-9]+(-[a-z0-9]+)*\.[a-z]+$"
)

# Document-identifier prefixed files (SD-*, PRD-*, TS-*, EPIC-*, etc.)
# Handles: SD-COBUILDER-WEB-001-E1-initiative-lifecycle.md,
#          PRD-HARNESS-UPGRADE-001.md, TS-COBUILDER-UPGRADE-E0.4.md,
#          SD-VCHAT-001-E2.1-TRANSCRIPT-MERGE.md
DOC_ID_FILE_PATTERN = re.compile(
    r"^(SD|PRD|TS|EPIC|SPEC|MANUAL|GAP|SOLUTION|NATIVE)-[A-Za-z0-9][-A-Za-z0-9.]*\.md$"
)

# Kebab prefix followed by a doc-id suffix
# Handles: design-challenge-PRD-PIPELINE-ENGINE-001.md
KEBAB_DOCID_FILE_PATTERN = re.compile(
    r"^[a-z0-9]+(-[a-z0-9]+)*-(PRD|SD|TS|EPIC|SPEC|MANUAL|GAP)-[A-Za-z0-9][-A-Za-z0-9.]*\.md$"
)

# Severity levels
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

# Directories within .claude/ that require frontmatter
CLAUDE_FRONTMATTER_DIRS = {"skills", "agents", "documentation", "output-styles", "commands"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class LintContext:
    """Holds scanning context for a single target directory."""

    def __init__(
        self,
        target_dir: Path,
        skip_dirs: set[str] | None = None,
        skip_files: set[str] | None = None,
        frontmatter_dirs: set[str] | None = None,
        directory_grades: dict[str, str] | None = None,
        require_implementation_status: list[str] | None = None,
        misplaced_scan: bool = False,
        misplaced_exclusions: list[str] | None = None,
        docs_types: set[str] | None = None,
        required_fields: list[str] | None = None,
    ):
        self.target_dir = target_dir
        self.skip_dirs = skip_dirs if skip_dirs is not None else set(DEFAULT_SKIP_DIRS)
        self.skip_files = skip_files if skip_files is not None else set(DEFAULT_SKIP_FILES)
        self.frontmatter_dirs = frontmatter_dirs  # None means use is_claude_dir logic
        self.directory_grades = directory_grades  # None means use quality-grades.json
        self.require_implementation_status = require_implementation_status or []
        self.misplaced_scan = misplaced_scan
        self.misplaced_exclusions = misplaced_exclusions or []
        self.docs_types = docs_types  # None means use default VALID_DOCS_TYPES
        self.required_fields = required_fields  # None means use defaults per target

    @property
    def is_claude_dir(self) -> bool:
        """True if this target is the .claude/ directory (backward-compat mode)."""
        return self.target_dir.resolve() == CLAUDE_DIR.resolve()


class Violation:
    """A single lint violation."""

    __slots__ = ("file", "category", "severity", "message", "fixable", "target_dir")

    def __init__(
        self,
        file: str,
        category: str,
        severity: str,
        message: str,
        fixable: bool = False,
        target_dir: Path | None = None,
    ):
        self.file = file
        self.category = category
        self.severity = severity
        self.message = message
        self.fixable = fixable
        self.target_dir = target_dir

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "category": self.category,
            "severity": self.severity,
            "message": self.message,
            "fixable": self.fixable,
        }

    def __str__(self) -> str:
        icon = {"error": "E", "warning": "W", "info": "I"}.get(self.severity, "?")
        fix = " [fixable]" if self.fixable else ""
        return f"[{icon}] {self.file}: {self.message}{fix}"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str | None) -> dict:
    """Load and return a config dict from a JSON config file.

    Config keys supported:
      targets: list[str]                  - directories to scan
      skip_dirs: list[str]               - dirs to skip (merged with defaults)
      skip_files: list[str]              - files to skip (merged with defaults)
      directory_grades: dict[str, str]   - grade overrides per subdirectory
      frontmatter_required_dirs: list[str] - dirs that must have frontmatter
      frontmatter_optional_dirs: list[str] - dirs where frontmatter is optional
      claude_md_lint: bool               - whether to include .claude/ scanning
    """
    if config_path is None:
        return {}

    config_file = Path(config_path)
    if not config_file.exists():
        # Try resolving relative to cwd
        config_file = Path.cwd() / config_path
    if not config_file.exists():
        print(f"Warning: Config file not found: {config_path}", file=sys.stderr)
        return {}

    with open(config_file) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Warning: Invalid JSON in config file {config_path}: {e}", file=sys.stderr)
            return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_quality_grades() -> dict[str, Any]:
    """Load quality-grades.json if it exists."""
    if not QUALITY_GRADES_FILE.exists():
        return {}
    with open(QUALITY_GRADES_FILE) as f:
        return json.load(f)


def parse_frontmatter(content: str) -> tuple[dict[str, str] | None, str]:
    """
    Parse YAML frontmatter from markdown content.
    Returns (frontmatter_dict, body) or (None, full_content).
    Handles simple key: value pairs only (stdlib, no yaml library).
    """
    if not content.startswith("---"):
        return None, content

    lines = content.split("\n")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None, content

    fm: dict[str, str] = {}
    for line in lines[1:end_idx]:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip().strip('"').strip("'")

    body = "\n".join(lines[end_idx + 1:])
    return fm, body


def get_relative_path(filepath: Path, base_dir: Path | None = None) -> str:
    """Get path relative to base_dir (defaults to CLAUDE_DIR for backward compat)."""
    if base_dir is None:
        base_dir = CLAUDE_DIR
    try:
        return str(filepath.relative_to(base_dir))
    except ValueError:
        return str(filepath)


def get_directory_name(filepath: Path, base_dir: Path | None = None) -> str | None:
    """Get the immediate subdirectory name under base_dir."""
    if base_dir is None:
        base_dir = CLAUDE_DIR
    try:
        rel = filepath.relative_to(base_dir)
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) > 1:
        return parts[0]
    return None


def is_in_skip_dir(filepath: Path, ctx: LintContext) -> bool:
    """Check if a file is in a directory that should be skipped."""
    dirname = get_directory_name(filepath, ctx.target_dir)
    return dirname in ctx.skip_dirs


def is_skill_file(filepath: Path, ctx: LintContext) -> bool:
    """Check if file is a SKILL.md inside skills/."""
    try:
        rel = filepath.relative_to(ctx.target_dir)
    except ValueError:
        return False
    parts = rel.parts
    return len(parts) >= 2 and parts[0] == "skills" and filepath.name == "SKILL.md"


def is_agent_file(filepath: Path, ctx: LintContext) -> bool:
    """Check if file is an agent definition in agents/."""
    try:
        rel = filepath.relative_to(ctx.target_dir)
    except ValueError:
        return False
    parts = rel.parts
    return len(parts) >= 2 and parts[0] == "agents" and filepath.suffix == ".md"


def is_top_level_file(filepath: Path, ctx: LintContext) -> bool:
    """Check if file is a top-level file directly in the target directory."""
    try:
        rel = filepath.relative_to(ctx.target_dir)
    except ValueError:
        return False
    return len(rel.parts) == 1


def collect_md_files(ctx: LintContext) -> list[Path]:
    """Collect markdown files to lint within the target directory."""
    files = []
    for p in ctx.target_dir.rglob("*.md"):
        # Skip files in skip directories
        if is_in_skip_dir(p, ctx):
            continue
        # Skip hidden directories (e.g. .claude/.claude nested)
        try:
            rel = p.relative_to(ctx.target_dir)
        except ValueError:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        # Skip specific files (e.g. auto-generated reports)
        if str(rel) in ctx.skip_files:
            continue
        files.append(p)
    return sorted(files)


def should_require_frontmatter(filepath: Path, ctx: LintContext) -> bool:
    """Determine if a file should have frontmatter.

    For .claude/ target (backward-compat):
      Files that require frontmatter:
      - SKILL.md files in skills/
      - Agent definitions in agents/
      - Documentation in documentation/
      - Output styles in output-styles/
      - Commands in commands/

      Files that do NOT require frontmatter:
      - CLAUDE.md (top-level config, not a document)
      - Reference files nested deep in skills (e.g. skills/foo/references/bar.md)
      - Hook scripts documentation

    For other targets:
      Uses ctx.frontmatter_dirs if set, otherwise all dirs with .md files.
    """
    # Top-level files directly in the target dir don't need frontmatter
    if is_top_level_file(filepath, ctx):
        return False

    dirname = get_directory_name(filepath, ctx.target_dir)

    if ctx.is_claude_dir:
        # Backward-compatible logic for .claude/ directory
        if dirname in CLAUDE_FRONTMATTER_DIRS:
            return True
        return False
    else:
        # For non-.claude/ targets, use configured frontmatter_dirs
        if ctx.frontmatter_dirs is not None:
            return dirname in ctx.frontmatter_dirs
        # Default: require frontmatter in all non-root dirs if no config
        return dirname is not None


# ---------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------

def check_frontmatter(filepath: Path, content: str, ctx: LintContext) -> list[Violation]:
    """Check frontmatter presence and validity for applicable files."""
    violations = []
    rel = get_relative_path(filepath, ctx.target_dir)

    if not should_require_frontmatter(filepath, ctx):
        # Even if not required, validate frontmatter if present
        fm, _ = parse_frontmatter(content)
        if fm is not None:
            violations.extend(_validate_frontmatter_fields(filepath, fm, rel, ctx))
        return violations

    fm, _ = parse_frontmatter(content)

    if fm is None:
        violations.append(Violation(
            file=rel,
            category="frontmatter",
            severity=SEVERITY_WARNING,
            message="Missing YAML frontmatter block (---)",
            fixable=True,
            target_dir=ctx.target_dir,
        ))
        return violations

    violations.extend(_validate_frontmatter_fields(filepath, fm, rel, ctx))
    return violations


def _validate_frontmatter_fields(
    filepath: Path, fm: dict[str, str], rel: str, ctx: LintContext
) -> list[Violation]:
    """Validate individual frontmatter fields."""
    violations = []

    # Required fields depend on file type
    required_fields = ["title", "status"]

    for field in required_fields:
        if field not in fm:
            violations.append(Violation(
                file=rel,
                category="frontmatter",
                severity=SEVERITY_ERROR,
                message=f"Missing required frontmatter field: {field}",
                fixable=False,
                target_dir=ctx.target_dir,
            ))

    # Validate field values
    if "status" in fm and fm["status"] not in VALID_STATUSES:
        violations.append(Violation(
            file=rel,
            category="frontmatter",
            severity=SEVERITY_ERROR,
            message=(
                f"Invalid status '{fm['status']}'. "
                f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"
            ),
            target_dir=ctx.target_dir,
        ))

    if "type" in fm and fm["type"] not in VALID_TYPES:
        violations.append(Violation(
            file=rel,
            category="frontmatter",
            severity=SEVERITY_ERROR,
            message=(
                f"Invalid type '{fm['type']}'. "
                f"Must be one of: {', '.join(sorted(VALID_TYPES))}"
            ),
            target_dir=ctx.target_dir,
        ))

    if "grade" in fm and fm["grade"] not in VALID_GRADES:
        violations.append(Violation(
            file=rel,
            category="frontmatter",
            severity=SEVERITY_ERROR,
            message=(
                f"Invalid grade '{fm['grade']}'. "
                f"Must be one of: {', '.join(sorted(VALID_GRADES))}"
            ),
            target_dir=ctx.target_dir,
        ))

    # Check last_verified date format
    if "last_verified" in fm:
        try:
            datetime.strptime(fm["last_verified"], "%Y-%m-%d")
        except ValueError:
            violations.append(Violation(
                file=rel,
                category="frontmatter",
                severity=SEVERITY_ERROR,
                message=(
                    f"Invalid last_verified date format: '{fm['last_verified']}'. "
                    f"Expected YYYY-MM-DD"
                ),
                target_dir=ctx.target_dir,
            ))

    return violations


def check_crosslinks(filepath: Path, content: str, ctx: LintContext) -> list[Violation]:
    """Check that relative markdown links resolve to real files."""
    violations = []
    rel = get_relative_path(filepath, ctx.target_dir)

    # Strip fenced code blocks to avoid false positives from code examples.
    # E.g., Python `Agent(model=model, mcp_servers=[...], system_prompt=prompt)`
    # contains `[...]` followed by `(...)` which matches the link regex.
    stripped = re.sub(r"```[^\n]*\n.*?```", "", content, flags=re.DOTALL)

    # Also strip inline code spans: `[link](target)` should not trigger violations.
    # E.g., ``[filename](./evidence/filename)`` in prose is an example, not a real link.
    stripped = re.sub(r"`[^`\n]+`", "", stripped)

    # Find markdown links: [text](path) -- only relative paths
    link_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    for match in link_pattern.finditer(stripped):
        link_target = match.group(2)

        # Skip external URLs, anchors, mailto, etc.
        if link_target.startswith(("http://", "https://", "#", "mailto:")):
            continue

        # Strip anchor from target
        target_path = link_target.split("#")[0]
        if not target_path:
            continue

        # Skip template placeholders (e.g. {evidence_filename} in report templates)
        if "{" in target_path:
            continue

        # Resolve relative to the file's directory
        resolved = (filepath.parent / target_path).resolve()

        if not resolved.exists():
            violations.append(Violation(
                file=rel,
                category="crosslinks",
                severity=SEVERITY_ERROR,
                message=f"Broken link: [{match.group(1)}]({link_target})",
                target_dir=ctx.target_dir,
            ))

    return violations


def check_staleness(filepath: Path, content: str, ctx: LintContext) -> list[Violation]:
    """Check document staleness based on last_verified date."""
    violations = []
    rel = get_relative_path(filepath, ctx.target_dir)

    fm, _ = parse_frontmatter(content)
    if fm is None or "last_verified" not in fm:
        return violations

    try:
        last_verified = datetime.strptime(fm["last_verified"], "%Y-%m-%d").date()
    except ValueError:
        return violations  # Already caught by frontmatter checker

    today = date.today()
    age_days = (today - last_verified).days
    current_grade = fm.get("grade", "")

    if age_days > STALENESS_ARCHIVE and current_grade not in ("archive", "draft"):
        violations.append(Violation(
            file=rel,
            category="staleness",
            severity=SEVERITY_WARNING,
            message=(
                f"Document is {age_days} days old "
                f"(last_verified: {fm['last_verified']}). "
                f"Grade should be 'archive' but is '{current_grade}'"
            ),
            fixable=True,
            target_dir=ctx.target_dir,
        ))
    elif age_days > STALENESS_REFERENCE and current_grade == "authoritative":
        violations.append(Violation(
            file=rel,
            category="staleness",
            severity=SEVERITY_INFO,
            message=(
                f"Document is {age_days} days old "
                f"(last_verified: {fm['last_verified']}). "
                f"Consider downgrading from 'authoritative' to 'reference'"
            ),
            fixable=True,
            target_dir=ctx.target_dir,
        ))

    return violations


def check_naming(filepath: Path, ctx: LintContext) -> list[Violation]:
    """Check naming conventions for harness files and directories.

    Rules:
    - Directories should be kebab-case (lowercase with hyphens)
    - Top-level docs should be UPPER_CASE (e.g. CLAUDE.md, SKILL.md)
    - Other .md files should be kebab-case
    - No spaces in any file or directory names
    """
    violations = []
    rel = get_relative_path(filepath, ctx.target_dir)
    name = filepath.name

    # Check for spaces in filename
    if " " in name:
        violations.append(Violation(
            file=rel,
            category="naming",
            severity=SEVERITY_ERROR,
            message=f"Filename contains spaces: '{name}'",
            fixable=False,
            target_dir=ctx.target_dir,
        ))

    # Check directory naming (kebab-case)
    try:
        rel_path = filepath.relative_to(ctx.target_dir)
    except ValueError:
        return violations

    for part in rel_path.parts[:-1]:  # All parent dirs, not the filename
        if not KEBAB_DIR_PATTERN.match(part):
            violations.append(Violation(
                file=rel,
                category="naming",
                severity=SEVERITY_WARNING,
                message=(
                    f"Directory '{part}' doesn't follow kebab-case convention. "
                    f"Expected: lowercase-with-hyphens"
                ),
                fixable=False,
                target_dir=ctx.target_dir,
            ))
            break  # Only report once per file path

    # Check file naming
    if name in UPPER_CASE_FILES or name == "SKILL.md":
        # Top-level docs must be UPPER_CASE
        if not UPPER_FILE_PATTERN.match(name):
            violations.append(Violation(
                file=rel,
                category="naming",
                severity=SEVERITY_WARNING,
                message=(
                    f"Expected UPPER_CASE filename for '{name}'"
                ),
                fixable=False,
                target_dir=ctx.target_dir,
            ))
    elif is_top_level_file(filepath, ctx):
        # Top-level target dir files should be UPPER_CASE
        if not UPPER_FILE_PATTERN.match(name) and not KEBAB_FILE_PATTERN.match(name):
            violations.append(Violation(
                file=rel,
                category="naming",
                severity=SEVERITY_INFO,
                message=(
                    f"Top-level file '{name}' should be UPPER_CASE.md "
                    f"or kebab-case.md"
                ),
                fixable=False,
                target_dir=ctx.target_dir,
            ))
    else:
        # Non-top-level files: accept various naming conventions
        if (
            not KEBAB_FILE_PATTERN.match(name)
            and not UPPER_FILE_PATTERN.match(name)
            and not MIXED_FILE_PATTERN.match(name)
            and not VERSION_FILE_PATTERN.match(name)
            and not UNDERSCORE_FILE_PATTERN.match(name)
            and not KEBAB_UPPER_FILE_PATTERN.match(name)
            and not DOC_ID_FILE_PATTERN.match(name)
            and not KEBAB_DOCID_FILE_PATTERN.match(name)
        ):
            violations.append(Violation(
                file=rel,
                category="naming",
                severity=SEVERITY_WARNING,
                message=(
                    f"Filename '{name}' doesn't follow naming conventions. "
                    f"Expected: kebab-case.md, UPPER_CASE.md, "
                    f"UPPER-kebab.md, v1.0-kebab.md, or _private.md"
                ),
                fixable=False,
                target_dir=ctx.target_dir,
            ))

    return violations


def check_grades_sync(
    filepath: Path, content: str, grades_data: dict, ctx: LintContext
) -> list[Violation]:
    """Check that frontmatter grade matches quality-grades.json directory defaults."""
    violations = []
    rel = get_relative_path(filepath, ctx.target_dir)

    # Merge grades_data with ctx.directory_grades if provided
    effective_grades = dict(grades_data)
    if ctx.directory_grades:
        if "directoryGrades" not in effective_grades:
            effective_grades["directoryGrades"] = {}
        effective_grades["directoryGrades"].update(ctx.directory_grades)

    if not effective_grades:
        return violations

    fm, _ = parse_frontmatter(content)
    if fm is None or "grade" not in fm:
        return violations

    dirname = get_directory_name(filepath, ctx.target_dir)
    if dirname is None:
        return violations

    dir_grades = effective_grades.get("directoryGrades", {})
    file_overrides = effective_grades.get("fileOverrides", {})

    # Check file-level overrides first
    if isinstance(file_overrides, dict):
        for key, val in file_overrides.items():
            if key in ("_comment", "examples"):
                continue
            if rel == key and fm["grade"] != val:
                violations.append(Violation(
                    file=rel,
                    category="grades-sync",
                    severity=SEVERITY_ERROR,
                    message=(
                        f"Grade mismatch: frontmatter says '{fm['grade']}' "
                        f"but quality-grades.json override says '{val}'"
                    ),
                    fixable=True,
                    target_dir=ctx.target_dir,
                ))
                return violations

    # Check directory default
    if dirname in dir_grades:
        expected = dir_grades[dirname]
        actual = fm["grade"]
        if actual != expected:
            violations.append(Violation(
                file=rel,
                category="grades-sync",
                severity=SEVERITY_INFO,
                message=(
                    f"Grade '{actual}' differs from directory default "
                    f"'{expected}' for {dirname}/. "
                    f"Consider adding a fileOverride in quality-grades.json"
                ),
                target_dir=ctx.target_dir,
            ))

    return violations


def check_implementation_status(filepath: Path, content: str, ctx: LintContext) -> list[Violation]:
    """Check that PRD/SD/Epic/Spec documents have an Implementation Status section."""
    violations = []
    rel = get_relative_path(filepath, ctx.target_dir)
    fm, _ = parse_frontmatter(content)

    # Draft documents are exempt
    if fm and fm.get("status") == "draft":
        return []

    needs_status = False

    # Check frontmatter type
    if fm:
        doc_type = fm.get("type", "")
        if doc_type in ("prd", "sd", "epic", "specification", "spec"):
            needs_status = True
        # Also check against ctx-level require_implementation_status list
        require_types = getattr(ctx, "require_implementation_status", [])
        if require_types and doc_type in require_types:
            needs_status = True

    # Check filename stem (e.g. PRD-FOO.md, SD-BAR.md)
    name = filepath.stem.upper()
    if name.startswith(("PRD-", "SD-")):
        needs_status = True

    if not needs_status:
        return []

    if not re.search(r"^##\s+Implementation\s+Status", content, re.MULTILINE | re.IGNORECASE):
        violations.append(Violation(
            file=rel,
            category="implementation-status",
            severity=SEVERITY_WARNING,
            message=(
                "Missing '## Implementation Status' section "
                "(required for PRD/SD/Epic/Spec documents)"
            ),
            fixable=True,
            target_dir=ctx.target_dir,
        ))

    return violations


def _is_documentation_dir(target_dir: Path) -> bool:
    """Return True if target_dir is a docs/documentation directory."""
    name = target_dir.name.lower()
    return name in {"docs", "documentation"} or name.endswith("-docs") or name.startswith("docs-")


def _check_misplaced_document_single(filepath: Path, ctx: LintContext) -> list[Violation]:
    """Per-file misplaced-document check (legacy 2-arg form). Category: misplaced-documents."""
    if filepath.suffix.lower() != ".md":
        return []
    if _is_documentation_dir(ctx.target_dir):
        return []
    rel = get_relative_path(filepath, ctx.target_dir)
    return [Violation(
        file=rel,
        category="misplaced-documents",
        severity=SEVERITY_WARNING,
        message="This documentation file should be in docs/. Consider moving it.",
        fixable=False,
        target_dir=ctx.target_dir,
    )]


def _check_misplaced_documents_repo(repo_root: Path, docs_dir: Path, ctx: LintContext) -> list[Violation]:
    """Repo-wide scan for documentation files outside docs_dir. Category: misplaced-document."""
    violations = []
    exclusions = getattr(ctx, "misplaced_exclusions", [])

    for filepath in repo_root.rglob("*.md"):
        # Skip files already in docs_dir
        try:
            filepath.relative_to(docs_dir)
            continue
        except ValueError:
            pass

        # Skip files matching any exclusion prefix
        rel_to_root = str(filepath.relative_to(repo_root))
        excluded = False
        for excl in exclusions:
            if rel_to_root.startswith(excl.lstrip("/")):
                excluded = True
                break
        if excluded:
            continue

        # Skip hidden dirs and common non-doc dirs
        parts = filepath.relative_to(repo_root).parts
        skip = False
        for part in parts[:-1]:
            if part.startswith(".") or part in ("node_modules", "__pycache__"):
                skip = True
                break
        if skip:
            continue

        # Flag if filename or frontmatter indicates a PRD/SD/Epic/Spec
        name_upper = filepath.stem.upper()
        is_doc = name_upper.startswith(("PRD-", "SD-", "EPIC-", "SPEC-"))

        if not is_doc:
            try:
                content = filepath.read_text(encoding="utf-8")
                fm, _ = parse_frontmatter(content)
                if fm:
                    doc_type = fm.get("type", "")
                    if doc_type in ("prd", "sd", "epic", "specification", "spec"):
                        is_doc = True
            except (OSError, UnicodeDecodeError):
                pass

        if is_doc:
            violations.append(Violation(
                file=rel_to_root,
                category="misplaced-document",
                severity=SEVERITY_WARNING,
                message=(
                    f"Documentation file '{filepath.name}' found outside docs/. "
                    "Consider moving it to docs/."
                ),
                fixable=False,
                target_dir=ctx.target_dir,
            ))

    return violations


def check_misplaced_documents(first_arg, second_arg, third_arg=None):
    """Dispatch to per-file or repo-scan implementation based on argument count.

    2-arg form: check_misplaced_documents(filepath, ctx) -> per-file, category misplaced-documents
    3-arg form: check_misplaced_documents(repo_root, docs_dir, ctx) -> repo scan, category misplaced-document
    """
    if third_arg is None:
        return _check_misplaced_document_single(first_arg, second_arg)
    else:
        return _check_misplaced_documents_repo(first_arg, second_arg, third_arg)


# ---------------------------------------------------------------------------
# Fix logic
# ---------------------------------------------------------------------------

def generate_frontmatter(filepath: Path, grades_data: dict, ctx: LintContext) -> str:
    """Generate a frontmatter block for a file that lacks one."""
    dirname = get_directory_name(filepath, ctx.target_dir)
    name = filepath.stem

    # Infer title from filename
    if name == "SKILL":
        # Use parent directory name for SKILL.md
        title = filepath.parent.name.replace("-", " ").title()
    elif name == "CLAUDE":
        title = "Claude Configuration"
    else:
        title = name.replace("-", " ").title()
        # Strip date prefix from title
        date_prefix_match = re.match(r"^\d{4}-\d{2}-\d{2}\s+", title)
        if date_prefix_match:
            title = title[date_prefix_match.end():]

    # Infer type from directory and file
    type_map = {
        "skills": "skill",
        "agents": "agent",
        "output-styles": "output-style",
        "hooks": "hook",
        "commands": "command",
        "documentation": "architecture",
    }
    doc_type = type_map.get(dirname, "reference")

    # Infer grade from quality-grades.json, with ctx overrides
    dir_grades = grades_data.get("directoryGrades", {})
    if ctx.directory_grades:
        dir_grades = dict(dir_grades)
        dir_grades.update(ctx.directory_grades)
    grade = dir_grades.get(dirname, "draft")

    # Infer status from grade
    status_map = {
        "authoritative": "active",
        "reference": "active",
        "archive": "archived",
        "draft": "draft",
    }
    status = status_map.get(grade, "draft")

    today_str = date.today().isoformat()

    # For non-.claude/ targets, include description/version/last-updated
    if not ctx.is_claude_dir:
        # Infer description from first content paragraph
        try:
            raw = filepath.read_text(encoding="utf-8")
            _, body = parse_frontmatter(raw)
            description = ""
            for line in body.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("---"):
                    description = line[:200]
                    break
            if not description:
                description = f"Documentation for {filepath.stem}"
        except Exception:
            description = f"Documentation for {filepath.stem}"

        # Infer last-updated from git log
        last_updated = today_str
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ai", str(filepath)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                last_updated = result.stdout.strip()[:10]
        except Exception:
            pass

        return (
            f"---\n"
            f"title: \"{title}\"\n"
            f"description: \"{description}\"\n"
            f"version: \"1.0.0\"\n"
            f"last-updated: {last_updated}\n"
            f"status: {status}\n"
            f"type: {doc_type}\n"
            f"last_verified: {today_str}\n"
            f"grade: {grade}\n"
            f"---\n\n"
        )

    return (
        f"---\n"
        f"title: \"{title}\"\n"
        f"status: {status}\n"
        f"type: {doc_type}\n"
        f"last_verified: {today_str}\n"
        f"grade: {grade}\n"
        f"---\n\n"
    )


def apply_fixes(
    violations: list[Violation],
    grades_data: dict,
    targets: list[Path],
) -> int:
    """Apply automatic fixes. Returns number of files fixed."""
    fixed_count = 0

    # Build a mapping from target_dir to LintContext for fix generation
    # We need ctx to call generate_frontmatter correctly
    target_ctxs: dict[Path, LintContext] = {}
    for t in targets:
        target_ctxs[t.resolve()] = LintContext(target_dir=t)

    # Group fixable violations by (target_dir, file)
    fixable_by_target: dict[Path | None, dict[str, list[Violation]]] = {}
    for v in violations:
        if v.fixable:
            target_key = v.target_dir.resolve() if v.target_dir else None
            fixable_by_target.setdefault(target_key, {}).setdefault(v.file, []).append(v)

    for target_key, files_dict in fixable_by_target.items():
        # Determine base_dir for resolving files
        if target_key is not None:
            base_dir = target_key
        else:
            base_dir = CLAUDE_DIR

        ctx = target_ctxs.get(target_key, LintContext(target_dir=Path(base_dir)))

        for rel_path, file_violations in files_dict.items():
            filepath = base_dir / rel_path
            if not filepath.exists():
                continue

            content = filepath.read_text(encoding="utf-8")
            modified = False

            for v in file_violations:
                if (
                    v.category == "frontmatter"
                    and "Missing YAML frontmatter" in v.message
                ):
                    fm_block = generate_frontmatter(filepath, grades_data, ctx)
                    content = fm_block + content
                    modified = True

                elif (
                    v.category == "staleness"
                    and "should be 'archive'" in v.message
                ):
                    content = re.sub(
                        r"^(grade:\s*).*$",
                        r"\1archive",
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    modified = True

                elif (
                    v.category == "staleness"
                    and "Consider downgrading" in v.message
                ):
                    content = re.sub(
                        r"^(grade:\s*).*$",
                        r"\1reference",
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                    modified = True

                elif (
                    v.category == "grades-sync"
                    and "Grade mismatch" in v.message
                ):
                    # Extract expected grade from the file override
                    grade_match = re.search(
                        r"quality-grades\.json override says '([^']+)'",
                        v.message,
                    )
                    if grade_match:
                        expected_grade = grade_match.group(1)
                        content = re.sub(
                            r"^(grade:\s*).*$",
                            rf"\1{expected_grade}",
                            content,
                            count=1,
                            flags=re.MULTILINE,
                        )
                        modified = True

                elif (
                    v.category == "implementation-status"
                    and "Missing" in v.message
                ):
                    content = content.rstrip() + IMPL_STATUS_TEMPLATE
                    modified = True

            if modified:
                filepath.write_text(content, encoding="utf-8")
                fixed_count += 1

    return fixed_count


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def lint(
    fix: bool = False,
    verbose: bool = False,
    targets: list[Path] | None = None,
    config: dict | None = None,
) -> tuple[list[Violation], int]:
    """Run all lint checks and return (violations, files_scanned).

    Args:
        fix: If True, apply auto-fixes where possible.
        verbose: If True, print each file being scanned.
        targets: List of target directories to scan. Defaults to [CLAUDE_DIR].
        config: Parsed config dict. Overrides skip_dirs, skip_files, etc.
    """
    if targets is None:
        targets = [CLAUDE_DIR]

    grades_data = load_quality_grades()

    # Extract config overrides
    config_skip_dirs: set[str] = set()
    config_skip_files: set[str] = set()
    config_directory_grades: dict[str, str] | None = None
    config_frontmatter_required: set[str] | None = None
    config_require_impl_status: list[str] = []
    config_misplaced_scan: bool = False
    config_misplaced_exclusions: list[str] = []
    config_docs_types: set[str] | None = None
    config_required_fields: list[str] | None = None

    if config:
        if "skip_dirs" in config:
            config_skip_dirs = set(config["skip_dirs"])
        if "skip_files" in config:
            config_skip_files = set(config["skip_files"])
        if "directory_grades" in config:
            config_directory_grades = dict(config["directory_grades"])
        if "frontmatter_required_dirs" in config:
            config_frontmatter_required = set(config["frontmatter_required_dirs"])
        if "require_implementation_status" in config:
            config_require_impl_status = list(config["require_implementation_status"])
        if "misplaced_document_scan" in config:
            config_misplaced_scan = bool(config["misplaced_document_scan"])
        if "misplaced_document_exclusions" in config:
            config_misplaced_exclusions = list(config["misplaced_document_exclusions"])
        if "docs_types" in config:
            config_docs_types = set(config["docs_types"])
        if "required_fields" in config:
            raw_rf = config["required_fields"]
            if isinstance(raw_rf, list):
                config_required_fields = list(raw_rf)
            elif isinstance(raw_rf, dict):
                # Support {docs: [...], claude: [...]} form; pick appropriate list later
                config_required_fields = None  # handled per-ctx below

    all_violations: list[Violation] = []
    total_files = 0

    for target_dir in targets:
        if not target_dir.exists():
            print(f"Warning: Target directory does not exist: {target_dir}", file=sys.stderr)
            continue

        # Build effective skip sets (merge defaults with config)
        effective_skip_dirs = set(DEFAULT_SKIP_DIRS) | config_skip_dirs
        effective_skip_files = set(DEFAULT_SKIP_FILES) | config_skip_files

        # Determine frontmatter_dirs for this target
        # For .claude/ targets, use None (backward-compat logic in should_require_frontmatter)
        frontmatter_dirs: set[str] | None = None
        if config_frontmatter_required is not None:
            # Config specifies which subdirs need frontmatter for all targets
            # For .claude/ targets, still use backward-compat unless config overrides
            ctx_test = LintContext(target_dir=target_dir)
            if not ctx_test.is_claude_dir:
                frontmatter_dirs = config_frontmatter_required

        ctx = LintContext(
            target_dir=target_dir,
            skip_dirs=effective_skip_dirs,
            skip_files=effective_skip_files,
            frontmatter_dirs=frontmatter_dirs,
            directory_grades=config_directory_grades,
            require_implementation_status=config_require_impl_status,
            misplaced_scan=config_misplaced_scan,
            misplaced_exclusions=config_misplaced_exclusions,
            docs_types=config_docs_types,
            required_fields=config_required_fields,
        )

        files = collect_md_files(ctx)
        files_scanned = len(files)
        total_files += files_scanned

        if verbose:
            print(f"Scanning {files_scanned} markdown files in {target_dir}")
            for f in files:
                print(f"  {get_relative_path(f, target_dir)}")
            print()

        for filepath in files:
            try:
                content = filepath.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                all_violations.append(Violation(
                    file=get_relative_path(filepath, target_dir),
                    category="io",
                    severity=SEVERITY_ERROR,
                    message="Could not read file",
                    target_dir=target_dir,
                ))
                continue

            all_violations.extend(check_frontmatter(filepath, content, ctx))
            all_violations.extend(check_crosslinks(filepath, content, ctx))
            all_violations.extend(check_staleness(filepath, content, ctx))
            all_violations.extend(check_naming(filepath, ctx))
            all_violations.extend(check_grades_sync(filepath, content, grades_data, ctx))
            all_violations.extend(check_implementation_status(filepath, content, ctx))

        # Post-loop: repo-wide misplaced document scan
        if getattr(ctx, "misplaced_scan", False):
            repo_root = target_dir.parent if target_dir.name not in (".", "") else target_dir
            docs_dir = repo_root / "docs"
            if docs_dir.exists():
                all_violations.extend(check_misplaced_documents(repo_root, docs_dir, ctx))

    if fix and all_violations:
        fixed = apply_fixes(all_violations, grades_data, targets)
        if fixed > 0:
            # Re-run lint to get updated violations
            return lint(fix=False, verbose=False, targets=targets, config=config)

    return all_violations, total_files


def format_text(
    violations: list[Violation],
    files_scanned: int,
    targets: list[Path] | None = None,
) -> str:
    """Format violations as human-readable text."""
    lines = []
    lines.append("Harness Documentation Lint Report")
    lines.append("=" * 50)

    if targets is None:
        targets = [CLAUDE_DIR]

    if len(targets) == 1:
        lines.append(f"Target: {targets[0]}")
    else:
        lines.append(f"Targets ({len(targets)}):")
        for t in targets:
            lines.append(f"  - {t}")

    lines.append(f"Files scanned: {files_scanned}")
    lines.append("")

    if not violations:
        lines.append("No violations found.")
        return "\n".join(lines)

    # Group by category
    by_category: dict[str, list[Violation]] = {}
    for v in violations:
        by_category.setdefault(v.category, []).append(v)

    # Summary
    errors = sum(1 for v in violations if v.severity == SEVERITY_ERROR)
    warnings = sum(1 for v in violations if v.severity == SEVERITY_WARNING)
    infos = sum(1 for v in violations if v.severity == SEVERITY_INFO)
    fixable = sum(1 for v in violations if v.fixable)

    lines.append(
        f"Total: {len(violations)} violations "
        f"({errors} errors, {warnings} warnings, {infos} info)"
    )
    if fixable:
        lines.append(f"Fixable: {fixable} (run with --fix)")
    lines.append("")

    for category, cat_violations in sorted(by_category.items()):
        lines.append(f"--- {category.upper()} ({len(cat_violations)}) ---")
        for v in sorted(cat_violations, key=lambda x: x.file):
            lines.append(f"  {v}")
        lines.append("")

    return "\n".join(lines)


def format_json(
    violations: list[Violation],
    files_scanned: int,
    targets: list[Path] | None = None,
) -> str:
    """Format violations as JSON."""
    if targets is None:
        targets = [CLAUDE_DIR]

    target_str = str(targets[0]) if len(targets) == 1 else [str(t) for t in targets]

    return json.dumps(
        {
            "target": target_str,
            "files_scanned": files_scanned,
            "total_violations": len(violations),
            "errors": sum(
                1 for v in violations if v.severity == SEVERITY_ERROR
            ),
            "warnings": sum(
                1 for v in violations if v.severity == SEVERITY_WARNING
            ),
            "info": sum(
                1 for v in violations if v.severity == SEVERITY_INFO
            ),
            "fixable": sum(1 for v in violations if v.fixable),
            "violations": [v.to_dict() for v in violations],
        },
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint documentation in .claude/ harness directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Scan and report only, no changes (default)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show all files being scanned",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Auto-fix what's possible (add frontmatter, update stale grades)",
    )
    parser.add_argument(
        "--target",
        action="append",
        dest="targets",
        metavar="DIR",
        help=(
            "Directory to scan (repeatable). "
            "Default: .claude/ relative to this script. "
            "Example: --target docs/ --target .claude/"
        ),
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help=(
            "Path to JSON config file. "
            "Example: --config docs-gardener.config.json"
        ),
    )

    args = parser.parse_args()

    # Load config if provided
    config = load_config(args.config)

    # Determine targets: CLI > config > default
    targets: list[Path] | None = None
    if args.targets:
        targets = [Path(t) for t in args.targets]
    elif config.get("targets"):
        targets = [Path(t) for t in config["targets"]]

    violations, files_scanned = lint(
        fix=args.fix,
        verbose=args.verbose,
        targets=targets,
        config=config if config else None,
    )

    effective_targets = targets if targets is not None else [CLAUDE_DIR]

    if args.json_output:
        print(format_json(violations, files_scanned, effective_targets))
    else:
        print(format_text(violations, files_scanned, effective_targets))

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
