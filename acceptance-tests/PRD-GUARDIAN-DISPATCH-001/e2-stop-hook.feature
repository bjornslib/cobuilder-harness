Feature: E2 — Custom Guardian Stop Hook
  Guardian has its own stop hook that checks pipeline completion, not promises

  Scenario: Stop hook function exists
    Given guardian.py exists at cobuilder/engine/guardian.py
    When I search for "_create_guardian_stop_hook"
    Then the function exists and takes dot_path and pipeline_id parameters
    And it returns a dict with "Stop" key containing hook callbacks
    # Scoring: 0.0 if missing, 1.0 if exists with correct signature

  Scenario: Stop hook checks pipeline completion
    Given a pipeline DOT with all nodes in terminal states (validated/accepted)
    When the stop hook fires
    Then it allows exit (returns empty dict or no "decision" key)
    # Scoring: 0.0 if blocks, 1.0 if allows

  Scenario: Stop hook blocks on non-terminal pipeline
    Given a pipeline DOT with active or pending nodes
    When the stop hook fires
    Then it blocks exit with corrective message about non-terminal nodes
    # Scoring: 0.0 if allows, 1.0 if blocks with message

  Scenario: Stop hook has safety valve
    Given a pipeline DOT with non-terminal nodes
    When the stop hook has blocked 3+ times
    Then it allows exit regardless (safety valve)
    # Scoring: 0.0 if infinite loop, 1.0 if safety valve works

  Scenario: build_options passes custom hooks
    Given guardian.py exists
    When I read build_options function
    Then it passes hooks= parameter to ClaudeCodeOptions
    And the hooks come from _create_guardian_stop_hook
    # Scoring: 0.0 if no hooks, 1.0 if custom hooks passed
