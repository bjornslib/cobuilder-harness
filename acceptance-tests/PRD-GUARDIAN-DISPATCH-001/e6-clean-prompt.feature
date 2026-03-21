Feature: E6 — Remove Promise/System3 Assumptions from Guardian Prompt
  Guardian system prompt focuses on pipeline execution only

  Scenario: No promise-related instructions
    Given guardian.py exists
    When I read the system prompt from build_system_prompt()
    Then it does NOT contain "cs-verify"
    And it does NOT contain "cs-promise"
    And it does NOT contain "completion promise"
    # Scoring: 0.0 if any present, 1.0 if all absent

  Scenario: No hindsight-at-exit instructions
    Given guardian.py exists
    When I read the system prompt
    Then it does NOT instruct the agent to call mcp__hindsight__retain at session end
    And it does NOT contain "store learnings" or "store session" instructions
    # Scoring: 0.0 if present, 1.0 if absent

  Scenario: System prompt focuses on pipeline execution
    Given guardian.py exists
    When I read the system prompt
    Then it contains instructions for: parse, validate, dispatch, monitor, gate-handle, checkpoint
    And it does NOT contain "System 3" (should say "Guardian" or "Layer 0")
    # Scoring: 0.5 if execution focus but S3 refs remain, 1.0 if fully clean

  Scenario: Turn budget efficiency
    Given the guardian runs on add-two-numbers-lifecycle pipeline with all fixes applied
    When the pipeline completes
    Then the guardian uses fewer than 50 turns total
    And fewer than 5 turns are spent on stop hook compliance
    # Scoring: 0.0 if >80 turns, 0.5 if 50-80, 1.0 if <50
