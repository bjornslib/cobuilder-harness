@epic-E4 @sd-COBUILDER-001-live-updates
Feature: Live Baseline Updates and Completion Promise Enforcement

  # Epic 4 makes baselines self-updating and enforces freshness through
  # the completion promise system.
  # SD: docs/prds/SD-COBUILDER-001-live-updates.md

  @feature-F4.1 @weight-0.04
  Scenario: S4.1 — Scoped refresh updates only targeted nodes
    Given a baseline exists with 100+ nodes
    When I call refresh_baseline(target_dir, scope=["src/auth/"])
    Then only nodes under src/auth/ are re-scanned
    And existing nodes outside the scope are preserved unchanged
    And the refresh completes in under 10 seconds
    And the returned dict includes refreshed_nodes count and duration_seconds

    # Confidence scoring guide:
    # 1.0 — Scoped refresh implemented, merges correctly, fast (<10s), return value correct
    # 0.5 — Refresh works but rescans entire baseline (not scoped)
    # 0.0 — refresh_baseline method missing or not implemented

    # Evidence to check:
    # - cobuilder/bridge.py (refresh_baseline method)
    # - Merge logic: replace matching nodes, keep everything else
    # - Performance test or timing assertion
    # - Return value schema matches SD spec

    # Red flags:
    # - refresh_baseline calls init_repo internally (full rescan)
    # - No merge logic (overwrites entire baseline)
    # - Missing scope parameter handling

  @feature-F4.2 @weight-0.04
  Scenario: S4.2 — Post-validation hook fires baseline refresh
    Given a DOT pipeline with a codergen node has file_path attribute
    When the node transitions to "validated" status
    Then _post_transition_hook fires automatically
    And it reads file_path/folder_path from the node attributes
    And it calls cobuilder repomap refresh with the scoped paths
    And a log message confirms the refresh (node count and duration)

    # Confidence scoring guide:
    # 1.0 — Hook fires on validated, reads scope from node, calls refresh, logs result
    # 0.5 — Hook exists but doesn't read scope (refreshes everything)
    # 0.0 — No post-transition hook in transition.py

    # Evidence to check:
    # - cobuilder/pipeline/transition.py (_post_transition_hook or _post_validated_hook)
    # - Hook checks new_status == "validated"
    # - get_node_attribute calls for file_path/folder_path
    # - bridge.refresh_baseline call with scope_list

    # Red flags:
    # - Hook fires on ALL transitions (not just validated)
    # - No debounce logic for rapid sequential validations
    # - Missing fallback when node has no file_path attribute

  @feature-F4.3 @weight-0.03
  Scenario: S4.3 — cs-verify blocks when baseline is stale
    Given a pipeline with validated nodes
    And the baseline was last updated before the most recent validation
    When I run "cs-verify --check"
    Then it detects baseline staleness
    And returns a BLOCKED message with timestamps (last_validated vs baseline_mtime)
    And suggests the fix command: "cobuilder repomap refresh --name <repo>"

    # Confidence scoring guide:
    # 1.0 — Freshness check implemented, timestamp comparison correct, helpful error message
    # 0.5 — Check exists but uses time-based instead of event-driven comparison
    # 0.0 — No baseline freshness check in cs-verify

    # Evidence to check:
    # - .claude/scripts/completion-state/cs-verify (freshness check function)
    # - Timestamp comparison: baseline_mtime >= last_validated
    # - Error message includes both timestamps and fix command

    # Red flags:
    # - Uses wall-clock age instead of comparing to validation timestamp
    # - Check always passes (no actual comparison)
    # - Missing transitions.jsonl reading for last_validated timestamp

  @feature-F4.4 @weight-0.03
  Scenario: S4.4 — Orchestrator cleanup refreshes baseline
    Given an orchestrator has completed work in a worktree
    When spawn_orchestrator cleanup runs
    Then it detects files changed in the worktree (via git diff)
    And calls refresh_baseline with those changed files as scope
    And calls sync_baseline to propagate changes

    # Confidence scoring guide:
    # 1.0 — Cleanup detects changes, scoped refresh, sync called
    # 0.5 — Cleanup runs but refreshes entire baseline (not scoped)
    # 0.0 — No baseline refresh in orchestrator cleanup

    # Evidence to check:
    # - cobuilder/orchestration/spawn_orchestrator.py (cleanup_orchestrator function)
    # - get_git_changed_files call
    # - bridge.refresh_baseline(scope=changed_files)
    # - bridge.sync_baseline call

    # Red flags:
    # - Cleanup only cleans tmux session, no baseline work
    # - Hard-coded file paths instead of git diff
    # - No error handling if refresh fails

  @feature-F4.5 @weight-0.01
  Scenario: S4.5 — s3-guardian includes CoBuilder tmux commands
    Given the s3-guardian SKILL.md exists
    When I read the Phase 2 (Orchestrator Spawning) section
    Then it includes CoBuilder commands for orchestrator boot sequence
    And commands include: cobuilder repomap status, cobuilder repomap refresh
    And commands are shown in the context of tmux wisdom injection

    # Confidence scoring guide:
    # 1.0 — Commands documented in Phase 2 with clear usage context
    # 0.5 — Commands mentioned but not in orchestrator context
    # 0.0 — No CoBuilder commands in s3-guardian SKILL.md

    # Evidence to check:
    # - .claude/skills/s3-guardian/SKILL.md (Phase 2 section)
    # - Search for "cobuilder repomap" in the file

    # Red flags:
    # - References old zerorepo commands
    # - Commands listed without context

  @feature-F4.6 @weight-0.02
  Scenario: S4.6 — Every orchestrator gets RepoMap freshness AC
    Given an orchestrator is being spawned via spawn_orchestrator.py
    When the completion promise is created for the orchestrator
    Then it includes an acceptance criterion: "RepoMap baseline updated post-implementation"
    And this AC is added programmatically (not manually by the guardian)

    # Confidence scoring guide:
    # 1.0 — AC added automatically during spawn, visible in promise
    # 0.5 — AC documented but not added programmatically
    # 0.0 — No RepoMap freshness AC in orchestrator promises

    # Evidence to check:
    # - cobuilder/orchestration/spawn_orchestrator.py (cs-promise --add-ac call)
    # - Promise JSON files showing the freshness AC

    # Red flags:
    # - AC text doesn't mention RepoMap or baseline
    # - AC added in documentation but not in code
    # - spawn_orchestrator.py has no promise interaction
