@journey @prd-COBUILDER-001 @J1 @code-analysis
Scenario J1: Foundation package enables pipeline generation end-to-end

  # This journey verifies that Epic 1 (foundation) properly enables Epic 2
  # (pipeline generation). It crosses the package boundary: cobuilder/ must
  # be properly scaffolded for pipeline create to work.

  # Layer 1: Package structure (Epic 1)
  Given the cobuilder/ package exists with repomap/, pipeline/, orchestration/ sub-packages
  And .repomap/ directory is committed to git with config.yaml

  # Layer 2: Bridge module (Epic 1 → Epic 2 bridge)
  When I run "cobuilder repomap init --target-dir /tmp/test-repo --name test-repo"
  Then a baseline is created at .repomap/baselines/test-repo/baseline.json
  And .repomap/config.yaml lists test-repo with node_count > 0

  # Layer 3: Pipeline generation (Epic 2)
  And when I run "cobuilder pipeline create --sd test-sd.md --repo test-repo"
  Then the pipeline uses the RepoMap baseline (not just beads)
  And the generated DOT file contains nodes with delta_status attributes
  And the DOT file validates cleanly via "cobuilder validate"

  # Business outcome: unified tool works end-to-end
  And the entire flow used a single "cobuilder" CLI entry point
  And no references to "zerorepo" or ".claude/scripts/attractor/cli.py" were needed
