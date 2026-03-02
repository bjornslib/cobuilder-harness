@epic-E2 @sd-COBUILDER-001-pipeline-generation
Feature: RepoMap-Native Pipeline Generation with LLM Enrichment

  # Epic 2 replaces beads-only pipeline generation with RepoMap-native
  # generation enriched by LLM intelligence.
  # SD: docs/prds/SD-COBUILDER-001-pipeline-generation.md

  @feature-F2.1 @weight-0.03
  Scenario: S2.1 — Missing baseline triggers auto-init
    Given no baseline exists for a given repository name
    When I run "cobuilder pipeline create --sd SD-TEST.md --repo nonexistent-repo"
    Then the system detects the missing baseline
    And logs a clear message about running repomap init automatically
    And a baseline is created in .repomap/baselines/<repo>/ before generation continues

    # Confidence scoring guide:
    # 1.0 — Auto-init detected, logged, created baseline, pipeline generation continued
    # 0.5 — Auto-init fires but pipeline generation fails afterward
    # 0.0 — Missing baseline causes hard error with no auto-init attempt

    # Evidence to check:
    # - cobuilder/pipeline/generate.py (auto-init logic near top)
    # - Log output showing "Running repomap init..." or similar
    # - .repomap/baselines/ populated after auto-init

    # Red flags:
    # - generate.py assumes baseline always exists
    # - Auto-init silently swallows errors
    # - No logging during auto-init

  @feature-F2.2 @weight-0.06
  Scenario: S2.2 — Only MODIFIED and NEW RepoMap nodes become pipeline nodes
    Given a RepoMap baseline exists with EXISTING, MODIFIED, and NEW nodes
    When the pipeline generator collects nodes
    Then only MODIFIED and NEW delta_status nodes appear as pipeline codergen nodes
    And EXISTING nodes are excluded from the pipeline
    And each pipeline node carries the delta_status attribute from RepoMap

    # Confidence scoring guide:
    # 1.0 — Clear filtering logic, EXISTING excluded, delta_status propagated to DOT
    # 0.5 — Filtering exists but delta_status not propagated to DOT node attributes
    # 0.0 — No filtering — all baseline nodes become pipeline nodes

    # Evidence to check:
    # - cobuilder/pipeline/generate.py (node collection logic)
    # - Generated DOT file (delta_status attribute on nodes)
    # - Test verifying EXISTING nodes are excluded

    # Red flags:
    # - Pipeline includes EXISTING nodes
    # - Hardcoded node lists instead of reading from RepoMap
    # - delta_status not in DOT node attributes

  @feature-F2.3 @weight-0.10
  Scenario: S2.3 — LLM enrichment pipeline produces structured output
    Given a set of pipeline nodes from RepoMap
    When the enrichment pipeline runs all 5 enrichers sequentially
    Then FileScoper outputs file_scope with modify/create/reference_only lists
    And AcceptanceCrafter outputs acceptance_criteria with testable criteria
    And DependencyInferrer outputs dependencies with depends_on relationships
    And WorkerSelector outputs worker_type with confidence score
    And ComplexitySizer outputs complexity assessment and split recommendation
    And each enricher returns valid YAML-structured output

    # Confidence scoring guide:
    # 1.0 — All 5 enrichers implemented, produce valid YAML, tested with mocks
    # 0.5 — 3-4 enrichers implemented, some return incomplete output
    # 0.0 — Enrichment pipeline missing or only 1-2 enrichers exist

    # Evidence to check:
    # - cobuilder/pipeline/enrichers/ directory (6 files: __init__.py + 5 enrichers)
    # - Each enricher class has enrich_all() method
    # - EnrichmentPipeline.enrich() chains all 5 in sequence
    # - Tests for each enricher with mock LLM responses

    # Red flags:
    # - Enrichers that just pass through input unchanged
    # - Missing YAML validation of enricher output
    # - WorkerSelector using keyword heuristics instead of LLM
    # - No tests with structured mock responses

  @feature-F2.4 @weight-0.04
  Scenario: S2.4 — Beads matched to RepoMap nodes
    Given RepoMap nodes have been collected
    And beads exist for the initiative
    When beads cross-reference runs
    Then each pipeline node that matches a bead carries bead_id attribute
    And matching uses title/file similarity (not exact string match)
    And unmatched nodes still appear in the pipeline (beads are secondary)

    # Confidence scoring guide:
    # 1.0 — Fuzzy matching implemented, bead_id populated, unmatched nodes preserved
    # 0.5 — Exact matching only, or beads required (not optional)
    # 0.0 — No beads cross-reference logic

    # Evidence to check:
    # - cobuilder/pipeline/generate.py (beads matching section)
    # - Matching algorithm (title similarity, file overlap)
    # - Generated DOT nodes with bead_id attribute

    # Red flags:
    # - Beads matching crashes when no beads exist
    # - Only exact title match (misses partial matches)
    # - Missing nodes when beads don't match

  @feature-F2.5 @weight-0.06
  Scenario: S2.5 — TaskMaster receives SD + RepoMap context
    Given an SD file and RepoMap context exist
    When cobuilder calls TaskMaster via Python subprocess
    Then the subprocess receives an enriched file containing SD + RepoMap YAML
    And TaskMaster produces tasks with file paths from RepoMap context
    And tasks include delta classification (MODIFIED/NEW) for referenced files
    And a timeout of 120s is set on the subprocess call

    # Confidence scoring guide:
    # 1.0 — Subprocess call works, enriched input created, tasks have file paths
    # 0.5 — TaskMaster called but without RepoMap context appended
    # 0.0 — No TaskMaster integration, tasks created manually

    # Evidence to check:
    # - cobuilder/pipeline/taskmaster_bridge.py (run_taskmaster_parse function)
    # - Enriched input file format (SD + RepoMap YAML block)
    # - .taskmaster/tasks/tasks.json output (file_path fields present)

    # Red flags:
    # - TaskMaster called via MCP instead of subprocess
    # - No timeout on subprocess call
    # - Enriched input missing RepoMap YAML section
    # - Fallback logic missing (what if TaskMaster fails?)

  @feature-F2.6 @weight-0.05
  Scenario: S2.6 — DOT nodes carry all enriched attributes
    Given the enrichment pipeline has completed
    When the DOT file is rendered
    Then each codergen node carries: file_path, delta_status, interfaces, change_summary, worker_type, solution_design
    And hexagon validation nodes are auto-generated with AT pairing
    And the DOT file validates cleanly via "cobuilder validate"

    # Confidence scoring guide:
    # 1.0 — All 6 attributes present on nodes, validation passes, AT nodes generated
    # 0.5 — Most attributes present but some missing (e.g., no interfaces)
    # 0.0 — DOT nodes have minimal attributes (just label and handler)

    # Evidence to check:
    # - Generated .dot file (grep for file_path=, delta_status=, worker_type=)
    # - cobuilder validate output (no errors)
    # - Hexagon nodes present for each codergen node

    # Red flags:
    # - Attributes stored as comments instead of DOT node attributes
    # - Missing solution_design reference on nodes
    # - Validation fails on generated pipeline

  @feature-F2.7 @weight-0.04
  Scenario: S2.7 — SD file updated with CoBuilder enrichment blocks
    Given a pipeline has been generated from an SD
    When the SD v2 enrichment writer runs
    Then each feature section in the SD has a "CoBuilder Enrichment" YAML block appended
    And enrichment blocks contain: pipeline_node, bead_id, worker_type, taskmaster_tasks, file_scope, acceptance_criteria_enriched
    And the original SD content is preserved (enrichment is additive)

    # Confidence scoring guide:
    # 1.0 — All features annotated, YAML blocks valid, original content intact
    # 0.5 — Some features annotated but blocks incomplete or malformed
    # 0.0 — SD v2 enrichment not implemented

    # Evidence to check:
    # - cobuilder/pipeline/sd_enricher.py (SD v2 writer)
    # - Example SD after enrichment (diff showing added blocks)
    # - YAML validity of enrichment blocks

    # Red flags:
    # - Enrichment overwrites original SD content
    # - YAML blocks not properly delimited
    # - Missing pipeline_node or bead_id in enrichment

  @feature-F2.8 @weight-0.03
  Scenario: S2.8 — End-to-end CLI command works
    Given an SD file and a tracked repository exist
    When I run "cobuilder pipeline create --sd SD-FILE.md --repo REPO"
    Then the command chains: auto-init → node collection → TaskMaster → beads → enrichment → DOT → SD v2
    And a valid DOT file is produced at .claude/attractor/pipelines/<initiative>.dot
    And the exit code is 0 on success

    # Confidence scoring guide:
    # 1.0 — Full end-to-end works, all 7 steps execute, valid DOT output
    # 0.5 — Command runs but skips some steps or produces partial output
    # 0.0 — Command not registered or crashes immediately

    # Evidence to check:
    # - cobuilder/cli.py (pipeline create command registration)
    # - Output DOT file existence and validity
    # - E2E test running the full command

    # Red flags:
    # - Steps hardcoded instead of chained
    # - No error handling between pipeline stages
    # - DOT file not saved to expected location
