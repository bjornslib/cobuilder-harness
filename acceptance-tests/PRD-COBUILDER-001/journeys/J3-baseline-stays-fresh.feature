@journey @prd-COBUILDER-001 @J3 @code-analysis
Scenario J3: Baseline stays fresh through validation and orchestrator lifecycle

  # This journey verifies that Epic 4 (live updates) integrates with
  # Epic 1 (storage), Epic 2 (pipeline), and the completion promise system.
  # Baselines must update automatically as work progresses.

  # Layer 1: Pipeline with validated nodes (Epic 2)
  Given a DOT pipeline exists with codergen nodes carrying file_path attributes

  # Layer 2: Post-validation hook (Epic 4)
  When a codergen node transitions to "validated" status
  Then the post-transition hook fires
  And it reads the node's file_path attribute for scoped refresh
  And the baseline at .repomap/baselines/<repo>/baseline.json is updated
  And only the files in scope were re-scanned (not the entire codebase)

  # Layer 3: cs-verify enforcement (Epic 4)
  And when I run "cs-verify --check" after the validation
  Then the freshness check passes (baseline_mtime >= last_validated)
  And if I manually set baseline_mtime to an old date
  Then "cs-verify --check" blocks with a BLOCKED message

  # Layer 4: Orchestrator cleanup (Epic 4)
  And when orchestrator cleanup runs (spawn_orchestrator.py)
  Then it detects git-changed files
  And calls refresh_baseline with those files as scope
  And calls sync_baseline to propagate

  # Layer 5: Worktree inheritance (Epic 1 + Epic 4)
  And a new worktree created from the same branch
  Has .repomap/ present (committed to git)
  And the baseline reflects the latest refreshed state

  # Business outcome: baselines never go stale during implementation
  And every validated node results in an updated baseline
  And completion promises enforce freshness programmatically
