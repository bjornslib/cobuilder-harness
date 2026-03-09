Feature: F2 - Chat + Voice Transcript S3 Storage
  Weight: 0.25

  Scenario: Chat-only session uploads transcript to S3
    Given a chat-only verify-check session with messages exchanged
    When the session ends
    Then a JSON file should be uploaded to S3 at "transcripts/tasks/{task_id}/chat-{timestamp}.json"
    And the file should contain all chat messages with roles and timestamps
    # Scoring: 1.0 if uploaded with correct format, 0.5 if uploaded but wrong format, 0.0 if not uploaded

  Scenario: Mixed session produces both transcript files
    Given a verify-check session with both chat and voice interactions
    When the session ends
    Then both chat transcript and voice transcript should exist on S3
    # Scoring: 1.0 if both exist, 0.5 if only one, 0.0 if neither

  Scenario: PostCheckProcessor evaluates chat-only transcript
    Given a completed chat-only session with chat_transcript_s3_key set
    And no voice transcript exists
    When PostCheckProcessor runs
    Then it should download and evaluate the chat transcript
    And produce a valid PostCheckResult
    # Scoring: 1.0 if valid result from chat, 0.0 if error or skip

  Scenario: PostCheckProcessor merges chat and voice chronologically
    Given a completed mixed session with both transcript keys
    When PostCheckProcessor runs
    Then it should merge entries from both sources sorted by timestamp
    And each entry should have a "source" field ("chat" or "voice")
    # Scoring: 1.0 if merged correctly, 0.5 if both evaluated but not merged, 0.0 if only one used

  Scenario: Chat history accumulation in backend
    Given the agent.py chat_text_handler
    Then each user message and agent response should be appended to ctx.userdata["chat_history"]
    And each entry should have role, content, and timestamp fields
    # Scoring: 1.0 if implemented, 0.0 if not
