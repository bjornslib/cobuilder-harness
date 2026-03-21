Feature: E4 — Clean Environment Isolation
  Guardian strips conflicting env vars and sets required ones

  Scenario: Environment strips conflicting variables
    Given guardian.py exists
    When I read the environment setup in build_options or _run_agent
    Then CLAUDECODE is removed or overridden to empty
    And CLAUDE_SESSION_ID is removed
    And CLAUDE_OUTPUT_STYLE is removed
    # Scoring: 0.0 if none stripped, 0.5 if CLAUDECODE only, 1.0 if all three

  Scenario: Required variables are set
    Given guardian.py exists
    When I read the environment setup
    Then PIPELINE_SIGNAL_DIR is set
    And PROJECT_TARGET_DIR is set
    # Scoring: 0.0 if neither, 0.5 if one, 1.0 if both
