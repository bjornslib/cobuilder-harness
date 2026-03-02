@epic-E3 @sd-COBUILDER-001-context-injection
Feature: Context Injection for Solution Design and Task Master

  # Epic 3 provides both the solution-design-architect agent and Task Master
  # with structured RepoMap context as input.
  # SD: docs/prds/SD-COBUILDER-001-context-injection.md

  @feature-F3.1 @weight-0.05
  Scenario: S3.1 — Context command outputs valid YAML
    Given a tracked repository with a baseline exists
    When I run "cobuilder repomap context --name repo --prd PRD-ID"
    Then the output is valid YAML
    And it contains: repository, snapshot_date, total_nodes, total_files, total_functions
    And it contains modules_relevant_to_epic with name, delta, files, summary, key_interfaces
    And it contains dependency_graph with from/to/type/description entries
    And it contains protected_files with path and reason
    And narrative fields use YAML block scalars (|) for markdown-compatible text

    # Confidence scoring guide:
    # 1.0 — Full YAML output matching SD schema, all sections present, block scalars used
    # 0.5 — YAML output but missing some sections (e.g., no protected_files)
    # 0.0 — Command not implemented or outputs non-YAML

    # Evidence to check:
    # - cobuilder/bridge.py (get_repomap_context method)
    # - cobuilder/cli.py (repomap context subcommand)
    # - Output parsed with yaml.safe_load() succeeds
    # - Check for "|" block scalar markers in output

    # Red flags:
    # - Output is JSON instead of YAML
    # - Narrative fields use quoted strings instead of block scalars
    # - Missing dependency_graph section
    # - Context command ignores --prd flag (returns unfiltered data)

  @feature-F3.2 @weight-0.04
  Scenario: S3.2 — Module relevance filter is deterministic
    Given a baseline with 50+ modules
    And a PRD with specific keywords (e.g., "authentication", "JWT")
    When the filter runs with the same input
    Then only modules matching by text reference, dependency expansion, or keyword are returned
    And the result is reproducible (same input → same output, no LLM involvement)
    And results are sorted with NEW/MODIFIED modules before EXISTING
    And a maximum of ~20 modules is returned (not the entire baseline)

    # Confidence scoring guide:
    # 1.0 — Deterministic filter with 3 match strategies, sorted, capped at ~20
    # 0.5 — Filter exists but uses LLM or is not reproducible
    # 0.0 — No filtering — returns entire baseline

    # Evidence to check:
    # - cobuilder/repomap/context_filter.py (filter_relevant_modules function)
    # - Three matching strategies: direct, dependency, keyword
    # - No LLM calls in the filter path
    # - Test with fixed input verifying deterministic output

    # Red flags:
    # - LLM call inside the filter function
    # - No module count limit (returns hundreds of modules)
    # - Only keyword matching (missing dependency expansion)
    # - Random ordering of results

  @feature-F3.3 @weight-0.02
  Scenario: S3.3 — s3-guardian SKILL.md documents RepoMap context injection
    Given the s3-guardian skill file exists
    When I read .claude/skills/s3-guardian/SKILL.md
    Then Phase 0 contains instructions for RepoMap context injection
    And it shows the "cobuilder repomap context" command usage
    And it shows how to inject the YAML output into solution-design-architect prompts

    # Confidence scoring guide:
    # 1.0 — Clear documentation with command examples and prompt template
    # 0.5 — Mentioned but incomplete (e.g., missing prompt template)
    # 0.0 — No mention of RepoMap in s3-guardian SKILL.md

    # Evidence to check:
    # - .claude/skills/s3-guardian/SKILL.md (search for "repomap" or "cobuilder")
    # - Phase 0 section content

    # Red flags:
    # - Documentation references old zerorepo commands
    # - Missing prompt template for context injection

  @feature-F3.4 @weight-0.04
  Scenario: S3.4 — TaskMaster tasks include file paths from context
    Given an SD has been enriched with RepoMap YAML context
    When TaskMaster parses the enriched SD
    Then generated tasks include specific file paths (not just module names)
    And tasks reference delta classification (MODIFIED vs NEW)
    And task descriptions distinguish between "create" and "modify" based on delta

    # Confidence scoring guide:
    # 1.0 — Tasks have file paths, delta-aware descriptions, create vs modify distinction
    # 0.5 — Tasks have some file paths but no delta awareness
    # 0.0 — Tasks are generic with no file references

    # Evidence to check:
    # - cobuilder/pipeline/taskmaster_bridge.py (create_enriched_input function)
    # - TaskMaster output tasks (file_path fields, delta references)
    # - Enriched SD temp file format (SD + YAML block with IMPORTANT instructions)

    # Red flags:
    # - Enriched input just concatenates without instruction block
    # - TaskMaster ignores the appended YAML (no file paths in output)
    # - No distinction between create and modify tasks
