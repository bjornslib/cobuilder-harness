Feature: F5 - Graceful Room Cleanup Without Egress
  Weight: 0.15

  Scenario: Chat-only session closes without errors
    Given a verify-check session that only used chat mode (no voice call)
    When the session ends or form is submitted
    Then room cleanup should complete without egress-related errors
    And no attempt to download recording_s3_key should be made
    # Scoring: 1.0 if no errors, 0.0 if egress error

  Scenario: Session mode tracking
    Given the agent.py session initialization
    Then ctx.userdata["session_modes"] should start as {"chat"}
    And should add "voice" when handle_voice_escalation is called
    # Scoring: 1.0 if tracked correctly, 0.0 if not tracked

  Scenario: PostCheckProcessor handles missing recording gracefully
    Given a chat-only session with no recording_s3_key
    When PostCheckProcessor.process_post_call is invoked
    Then it should NOT raise an error
    And should evaluate using chat transcript only
    And should return a valid PostCheckResult
    # Scoring: 1.0 if graceful + valid result, 0.5 if no error but empty result, 0.0 if error

  Scenario: Mixed session egress still works
    Given a session that used both chat and voice
    When the session ends
    Then voice egress should process normally
    And chat transcript should also upload
    # Scoring: 1.0 if both processed, 0.5 if only one, 0.0 if neither

  Scenario: Frontend tracks voice usage
    Given the verify-check page component
    Then a voiceWasUsed state variable should track whether voice was activated
    And form submission should include session_modes in the payload
    # Scoring: 1.0 if tracked + included, 0.5 if tracked but not sent, 0.0 if not tracked
