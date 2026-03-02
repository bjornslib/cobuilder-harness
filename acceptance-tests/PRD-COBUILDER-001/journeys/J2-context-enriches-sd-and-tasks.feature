@journey @prd-COBUILDER-001 @J2 @code-analysis
Scenario J2: RepoMap context enriches both SD creation and task decomposition

  # This journey verifies that Epic 3 (context injection) integrates with
  # Epic 1 (baseline) and Epic 2 (pipeline generation). Context must flow
  # from RepoMap through SD authoring and into TaskMaster.

  # Layer 1: Baseline exists (Epic 1)
  Given a RepoMap baseline exists for a repository with 50+ nodes

  # Layer 2: Context generation (Epic 3)
  When I run "cobuilder repomap context --name repo --prd PRD-TEST"
  Then the YAML output contains relevant modules filtered by PRD keywords
  And the output includes dependency_graph and protected_files sections
  And the output is deterministic (running twice produces identical YAML)

  # Layer 3: SD creation receives context (Epic 3 → SD workflow)
  And the s3-guardian SKILL.md documents injecting this YAML into SD creation prompts
  And the prompt template shows the YAML being passed to solution-design-architect

  # Layer 4: TaskMaster receives enriched input (Epic 3 → Epic 2)
  And when "cobuilder pipeline create" runs, the TaskMaster subprocess receives
      an enriched input file containing both the SD and the RepoMap YAML
  And TaskMaster tasks include file paths from the RepoMap context

  # Business outcome: codebase awareness flows through entire pipeline
  And SDs are grounded in actual codebase structure
  And tasks reference real file paths (not abstract module names)
