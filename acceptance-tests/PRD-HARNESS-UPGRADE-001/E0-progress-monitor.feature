@epic-E0 @sd-HARNESS-UPGRADE-001-E0
Feature: Pipeline Progress Monitor

  # Epic 0 adds a Haiku 4.5 sub-agent that monitors pipeline progress
  # via signal files and DOT graph mtime, reporting back to System 3.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E0-progress-monitor.md

  @feature-F0.1 @weight-0.03
  Scenario: S0.1 — Haiku monitor sub-agent pattern documented in s3-guardian
    Given the s3-guardian skill documentation exists
    When I search for pipeline progress monitor guidance
    Then the documentation describes:
      - Launching a Haiku 4.5 sub-agent with run_in_background=True
      - Monitor polls signal files in ATTRACTOR_SIGNAL_DIR
      - Monitor checks DOT graph file mtime for runner activity
      - Monitor COMPLETES (not loops forever) when attention is needed
    And the model is explicitly specified as Haiku (not Sonnet/Opus)

    # Confidence scoring guide:
    # 1.0 — Full pattern documented with model, background flag, polling, and completion trigger
    # 0.5 — Monitor mentioned but missing key details (model, completion semantics)
    # 0.0 — No monitor pattern in s3-guardian

    # Red flags:
    # - Monitor uses Sonnet/Opus (too expensive for polling)
    # - Monitor loops forever instead of completing to wake System 3
    # - No signal directory polling described

  @feature-F0.2 @weight-0.03
  Scenario: S0.2 — Signal directory polling mechanism described
    Given the monitor pattern documentation exists
    When I examine the polling mechanism
    Then the monitor:
      - Uses os.stat(signal_dir).st_mtime for efficient change detection
      - Only scans individual signal files when directory mtime changes
      - Checks for new/updated signal files matching {node_id}.json pattern
      - Has a configurable poll interval (default ~30s for Haiku cost efficiency)

    # Confidence scoring guide:
    # 1.0 — mtime-based polling with fallback to file scan, configurable interval
    # 0.5 — Polling described but no mtime optimization
    # 0.0 — No polling mechanism described

  @feature-F0.3 @weight-0.02
  Scenario: S0.3 — Cyclic re-launch pattern documented
    Given the monitor pattern documentation exists
    When I search for the re-launch or wake-up mechanism
    Then the documentation explains:
      - Monitor completes with a status output (not an infinite loop)
      - System 3 receives the completion and re-launches the monitor
      - This creates a cyclic wake-up pattern (launch → poll → complete → handle → re-launch)
    And the rationale references the "only completing subagents wake main thread" constraint

    # Confidence scoring guide:
    # 1.0 — Cyclic pattern documented with rationale for completion-based wake-up
    # 0.5 — Re-launch mentioned but rationale missing
    # 0.0 — No re-launch pattern

  @feature-F0.4 @weight-0.02
  Scenario: S0.4 — Output status enum covers all pipeline states
    Given the monitor pattern documentation exists
    When I search for monitor output statuses
    Then the following statuses are defined:
      | Status | Meaning |
      | MONITOR_COMPLETE | All pipeline nodes reached terminal state |
      | MONITOR_ERROR | Worker signal contains error status |
      | MONITOR_STALL | No signal file changes within stall threshold |
      | MONITOR_ANOMALY | Unexpected state (e.g., signal without pending node) |
    And each status includes guidance for what System 3 should do in response

    # Confidence scoring guide:
    # 1.0 — All 4 statuses defined with System 3 response guidance
    # 0.5 — Some statuses defined but missing guidance
    # 0.0 — No status enum defined
