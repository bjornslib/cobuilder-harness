Feature: F3 - Voice-to-Chat Handback
  Weight: 0.20

  Scenario: Chat agent receives voice context on handback
    Given a session that started in chat, escalated to voice, confirmed 2 fields
    When the user ends the voice call and returns to chat
    Then the chat agent's context should include the confirmed fields
    And the agent should NOT re-ask those questions
    # Scoring: 1.0 if context injected + no re-ask, 0.5 if context but still re-asks, 0.0 if no context

  Scenario: Passive wait after voice-to-chat transition
    Given a session returning from voice to chat
    When the mode switch is processed
    Then the chat agent should NOT generate any greeting or automatic response
    And the agent should wait passively for the user's next message
    And no SSE events should be emitted for the mode switch itself
    # Design: Chat agent waits passively — user initiates next exchange
    # Scoring: 1.0 if no auto-response + passive wait, 0.5 if greeting but no re-ask, 0.0 if agent speaks unprompted

  Scenario: Voice transcript accumulated during voice mode
    Given a verify-check session in voice mode
    Then voice transcription entries should accumulate in conversation_history with source="voice"
    And each entry should have speaker, text, and timestamp
    # Note: LiveKit SDK accumulates transcripts internally (session.chat_ctx).
    # Our HTTP/SSE architecture uses _chat_session_state["conversation_history"] instead.
    # Scoring: 1.0 if history populated with voice entries, 0.0 if not

  Scenario: Chat messages shared with LK listener for field extraction
    Given a verify-check session with an active listener subprocess in the LK room
    When the user sends a chat message (e.g. "Yes" confirming a field)
    Then the chat message should be published to the LK room as a data packet
    And the listener subprocess should receive it via existing data_received handler
    And the listener's conversation_history should include both assistant and user chat messages
    And field extraction should run on chat confirmations just like voice transcriptions
    # Note: Use LiveKit server-side API (livekit.api.RoomServiceClient.send_data) to publish
    # chat messages from the API process to the room. Listener receives via @room.on("data_received").
    # Data format: {"type": "transcription", "text": ..., "speaker": ..., "is_final": true, "source": "chat"}
    # Scoring: 1.0 if listener receives chat messages + extraction runs, 0.5 if received but no extraction, 0.0 if not shared
