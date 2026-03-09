Feature: F4 - Silent Mode Switch
  Weight: 0.15

  Scenario: Mode switch message filtered before LLM
    Given the chat_text_handler in agent.py
    When a mode_switch JSON message is received
    Then the inline JSON parser in chat_text_handler should detect it
    And the handler should return before calling session.generate_reply()
    # Scoring: 1.0 if filtered, 0.0 if passed to LLM

  Scenario: No visible response to mode switch
    Given a verify-check session in chat mode
    When handleStartCall sends {"type": "mode_switch", "mode": "voice"}
    Then no chat bubble or agent response should appear in the UI
    # Scoring: 1.0 if silent, 0.0 if agent responds

  Scenario: Regular chat messages still processed
    Given the mode switch filter is active
    When a normal text message "Hello, I need to verify employment" is sent
    Then it should pass through the filter and be processed by the LLM
    # Scoring: 1.0 if processed, 0.0 if filtered incorrectly

  Scenario: Mode switch triggers context-aware agent swap
    Given a mode_switch with mode="chat" is received
    Then chat_text_handler should swap to a chat-mode VerificationAgent with full chat_ctx
    And no text should be sent to the LLM as a user message
    And the handler should return before session.generate_reply()
    # Scoring: 1.0 if agent swapped with context + no LLM call, 0.5 if swapped but LLM triggered, 0.0 if not handled
