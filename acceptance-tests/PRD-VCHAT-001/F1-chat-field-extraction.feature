Feature: F1 - Chat Transcript Field Extraction
  Weight: 0.25

  Scenario: Chat message triggers form field update
    Given a verify-check session is active in chat mode
    When the user sends "John Smith started as Software Engineer in January 2020"
    Then the form fields for name, position, and start date should update within 3 seconds
    # Scoring: 1.0 if all 3 fields update, 0.7 if 2, 0.3 if 1, 0.0 if none

  Scenario: Agent response also triggers extraction
    Given a verify-check session is active in chat mode
    When the agent responds "I can confirm the employee name is Jane Doe"
    Then the name field should update to "Jane Doe"
    # Scoring: 1.0 if extracted, 0.0 if not

  Scenario: Voice extraction continues working
    Given a verify-check session with voice mode active
    When the user speaks "The position is Senior Developer"
    Then the position field should update via the existing voice pipeline
    And the chat extraction pipeline should not duplicate the update
    # Scoring: 1.0 if voice works and no duplicates, 0.5 if voice works but duplicates, 0.0 if voice broken

  Scenario: Chat extraction uses same listener_service pipeline
    Given the backend code for chat field extraction
    Then chat messages should be emitted on the "form_events" data channel
    And the payload format should match {"type": "transcription", "speaker": "user"|"agent", "text": str, "is_final": true, "source": "chat"}
    And listener_service.process_transcription_data should process them
    # Scoring: 1.0 if correct format + correct channel, 0.5 if partially correct, 0.0 if different approach
