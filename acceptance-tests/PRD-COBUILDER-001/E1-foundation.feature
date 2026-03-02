@epic-E1 @sd-COBUILDER-001-foundation
Feature: CoBuilder Foundation — Rename, Consolidate, Central Storage

  # Epic 1 establishes the cobuilder/ top-level package by consolidating
  # Attractor DOT pipeline and ZeroRepo into a single product.
  # SD: docs/prds/SD-COBUILDER-001-foundation.md

  @feature-F1.1 @weight-0.03
  Scenario: S1.1 — Package scaffolding with entry point
    Given the cobuilder/ directory exists at project root
    When I run "python3 -m cobuilder --help"
    Then the output shows command groups for repomap, pipeline, and orchestration
    And cobuilder/__init__.py contains a version string
    And cobuilder/__main__.py imports and calls a main() function
    And cobuilder/cli.py uses Typer for CLI definition

    # Confidence scoring guide:
    # 1.0 — All 4 files exist, --help runs cleanly showing 3+ command groups
    # 0.5 — Files exist but --help fails or shows incomplete command groups
    # 0.0 — cobuilder/ directory missing or no entry point

    # Evidence to check:
    # - cobuilder/__init__.py (version string)
    # - cobuilder/__main__.py (main function)
    # - cobuilder/cli.py (Typer app with command groups)
    # - python3 -m cobuilder --help output

    # Red flags:
    # - cli.py uses argparse instead of Typer
    # - __main__.py is empty or placeholder
    # - --help shows 0 commands

  @feature-F1.2 @weight-0.08
  Scenario: S1.2 — RepoMap moved from src/zerorepo/
    Given the src/zerorepo/ directory no longer exists (or is deprecated)
    When I import from cobuilder.repomap.models.component
    Then RPGNode, RPGEdge, RPGGraph are importable
    And cobuilder/repomap/ contains models/, graph_construction/, rpg_enrichment/, serena/, llm/
    And all internal imports within repomap use "cobuilder.repomap." prefix
    And the graph_construction/exporter.py file exists (renamed from attractor_exporter.py)

    # Confidence scoring guide:
    # 1.0 — All modules moved, all imports updated, existing tests pass
    # 0.5 — Modules moved but some imports still reference src/zerorepo
    # 0.0 — src/zerorepo/ still exists as primary location, cobuilder/repomap missing

    # Evidence to check:
    # - cobuilder/repomap/models/component.py (RPGNode, RPGEdge, RPGGraph classes)
    # - cobuilder/repomap/graph_construction/exporter.py (renamed from attractor_exporter.py)
    # - grep -r "from zerorepo" cobuilder/ (should return 0 matches)
    # - grep -r "from src.zerorepo" cobuilder/ (should return 0 matches)

    # Red flags:
    # - Symlinks instead of actual file moves
    # - Dual locations (both src/zerorepo and cobuilder/repomap exist with code)
    # - Import errors when running python3 -c "from cobuilder.repomap.models.component import RPGGraph"

  @feature-F1.3 @weight-0.06
  Scenario: S1.3 — Pipeline modules moved from .claude/scripts/attractor/
    Given the pipeline modules exist in cobuilder/pipeline/
    When I run "cobuilder validate pipeline.dot" (or equivalent)
    Then the validate command works using modules from cobuilder/pipeline/
    And cobuilder/pipeline/ contains generate.py, transition.py, dashboard.py, signal_protocol.py, validator.py, checkpoint.py, parser.py, status.py, node_ops.py, edge_ops.py, annotate.py, init_promise.py
    And .claude/scripts/attractor/cli.py is a thin redirect to cobuilder CLI

    # Confidence scoring guide:
    # 1.0 — All 12+ modules moved, redirect works, validate command functional
    # 0.5 — Modules moved but redirect missing or validate broken
    # 0.0 — Pipeline modules still only in .claude/scripts/attractor/

    # Evidence to check:
    # - ls cobuilder/pipeline/ (12+ .py files)
    # - .claude/scripts/attractor/cli.py (should contain redirect import)
    # - cobuilder validate on any .dot file

    # Red flags:
    # - .claude/scripts/attractor/ still contains full implementations (not just redirect)
    # - cobuilder/pipeline/__init__.py missing
    # - Circular imports between pipeline and repomap

  @feature-F1.4 @weight-0.04
  Scenario: S1.4 — Orchestration modules consolidated
    Given cobuilder/orchestration/ directory exists
    When I inspect the orchestration sub-package
    Then it contains spawn_orchestrator.py, pipeline_runner.py, identity_registry.py, runner_tools.py
    And all internal imports reference cobuilder.orchestration

    # Confidence scoring guide:
    # 1.0 — All 4 modules moved, imports clean
    # 0.5 — Modules moved but some still import from old locations
    # 0.0 — Orchestration modules not moved

    # Evidence to check:
    # - cobuilder/orchestration/__init__.py
    # - cobuilder/orchestration/spawn_orchestrator.py
    # - grep "from cobuilder.orchestration" across codebase

    # Red flags:
    # - spawn_orchestrator.py still at .claude/scripts/attractor/spawn_orchestrator.py as primary

  @feature-F1.5 @weight-0.04
  Scenario: S1.5 — Central .repomap/ storage created
    Given the .repomap/ directory exists at project root
    When I inspect .repomap/config.yaml
    Then it contains valid YAML with version and repos fields
    And .repomap/manifests/ directory exists
    And .repomap/baselines/ directory exists
    And .repomap/ is tracked by git (not gitignored)

    # Confidence scoring guide:
    # 1.0 — Directory structure complete, config.yaml valid, committed to git
    # 0.5 — Directory exists but config.yaml missing or invalid
    # 0.0 — .repomap/ directory does not exist

    # Evidence to check:
    # - .repomap/config.yaml (valid YAML with schema from SD)
    # - git ls-files .repomap/ (files tracked)
    # - .gitignore does NOT exclude .repomap/

    # Red flags:
    # - .repomap in .gitignore
    # - config.yaml uses JSON instead of YAML
    # - Missing manifests/ or baselines/ subdirectories

  @feature-F1.6 @weight-0.08
  Scenario: S1.6 — Bridge module connects RepoMap to Pipeline
    Given cobuilder/bridge.py exists
    When I inspect the ZeroRepoBridge class
    Then it has methods: init_repo, sync_baseline, get_repomap_context, refresh_baseline
    And init_repo accepts target_dir and name parameters
    And sync_baseline reads from .repomap/baselines/
    And get_repomap_context returns structured data (dict or YAML string)

    # Confidence scoring guide:
    # 1.0 — All 4 methods implemented, init_repo creates baseline, tests exist
    # 0.5 — Class exists with method stubs but incomplete implementation
    # 0.0 — bridge.py missing or empty

    # Evidence to check:
    # - cobuilder/bridge.py (ZeroRepoBridge class)
    # - Method signatures match SD specification
    # - Tests in tests/ for bridge module

    # Red flags:
    # - Methods raise NotImplementedError
    # - No interaction with .repomap/ directory
    # - Missing refresh_baseline (needed for Epic 4)

  @feature-F1.7 @weight-0.05
  Scenario: S1.7 — CLI subcommands wired
    Given cobuilder CLI is functional
    When I run "cobuilder repomap --help"
    Then it shows subcommands: init, sync, status, context
    And "cobuilder repomap status" shows tracked repos (or empty list)
    And "cobuilder repomap init --target-dir /tmp/test --name test" creates a baseline

    # Confidence scoring guide:
    # 1.0 — All 4 repomap subcommands work, init creates real baseline
    # 0.5 — Subcommands registered but some fail at runtime
    # 0.0 — repomap command group not registered

    # Evidence to check:
    # - cobuilder repomap --help output
    # - cobuilder/repomap/cli/commands.py (subcommand implementations)
    # - cobuilder/cli.py (command group registration)

    # Red flags:
    # - Subcommands exist but all raise NotImplementedError
    # - init creates empty files instead of running codebase walker

  @feature-F1.8 @weight-0.04
  Scenario: S1.8 — Test migration complete
    Given all test files have been updated to use new import paths
    When I run the test suite
    Then all existing tests pass with cobuilder.* imports
    And no test file imports from src/zerorepo or .claude/scripts/attractor directly

    # Confidence scoring guide:
    # 1.0 — Full test suite passes, 0 old import references
    # 0.5 — Most tests pass but some still reference old paths
    # 0.0 — Test suite broken due to import errors

    # Evidence to check:
    # - pytest output (pass/fail counts)
    # - grep -r "from zerorepo" tests/ (should be 0)
    # - grep -r "from src.zerorepo" tests/ (should be 0)

    # Red flags:
    # - Tests skipped due to import errors
    # - Tests that mock imports to hide broken paths
    # - Test count significantly lower than before migration
