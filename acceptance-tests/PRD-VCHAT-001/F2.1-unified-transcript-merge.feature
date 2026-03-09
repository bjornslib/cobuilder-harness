Feature: F2.1 - Unified Transcript Merge into sub_threads
  Weight: 0.25

  Scenario: Mixed session stores all messages
    Given a session that starts in chat, escalates to voice, returns to chat
    And 3 chat messages were sent before voice escalation
    And 2 voice exchanges occurred during voice mode
    And 1 chat message was sent after returning to chat
    When the session ends and store_unified_transcript() runs
    Then sub_threads.all_messages should contain all 6+ messages
    And messages should be sorted chronologically by timestamp
    # Scoring: 1.0 if all messages present + sorted, 0.5 if partial, 0.0 if chat lost

  Scenario: Channel tagging correct
    Given a completed mixed session with both chat and voice messages
    When the merged transcript is stored in sub_threads.all_messages
    Then chat messages should have channel="chat"
    And voice messages should have channel="voice"
    And NO messages should have channel="phone" (legacy hardcode removed)
    # Scoring: 1.0 if all tagged correctly, 0.5 if mixed, 0.0 if all "phone"

  Scenario: Near-duplicate deduplication
    Given a voice STT transcription "Yes that is correct" at T=10:00:01
    And a chat message "Yes that is correct" at T=10:00:03 (same content, 2s apart)
    When deduplicate_by_proximity() runs with window_seconds=5
    Then only the first occurrence should remain
    And messages with different content should NOT be removed
    # Scoring: 1.0 if deduped correctly, 0.5 if some dupes remain, 0.0 if no dedup

  Scenario: Mode_switch JSON excluded from transcripts
    Given a chat session where the user clicks "Start Call"
    And the frontend sends {"type": "mode_switch", "mode": "voice"}
    When the chat_history is collected for storage
    Then the mode_switch JSON should NOT appear in chat_history
    And only real user messages should be present
    # Scoring: 1.0 if excluded, 0.0 if mode_switch JSON in transcript

  Scenario: Utility functions extracted to transcript_utils.py
    Given the codebase after E2.1 implementation
    Then helpers/transcript_utils.py should exist as a new file
    And it should contain store_unified_transcript, deduplicate_by_proximity, parse_session_report_to_messages, tag_messages
    And agent.py should import from helpers.transcript_utils
    And post_call_processor.py should import parse_session_report_to_messages from helpers.transcript_utils
    # Scoring: 1.0 if properly extracted, 0.5 if functions exist but not extracted, 0.0 if still in agent.py

  Scenario: Chat-only session regression check
    Given a chat-only session (no voice escalation)
    When the session ends
    Then store_unified_transcript should store chat messages with channel="chat"
    And the behavior should be identical to the pre-E2.1 PostCheckProcessor path
    # Scoring: 1.0 if works, 0.0 if regression

  Scenario: Voice-only session regression check
    Given a voice-only session (no chat before or after)
    When the session ends
    Then store_unified_transcript should store voice messages with channel="voice"
    And the Prefect pipeline should NOT double-write to sub_threads
    # Scoring: 1.0 if works + no dupes, 0.5 if works but dupes, 0.0 if regression

  Scenario: batch-import respects caller-provided channel
    Given subthread_cycle_helper.py batch-import is called with messages that have channel="chat"
    Then the stored messages should retain channel="chat"
    And the hardcoded channel="phone" assignment should be removed or use setdefault
    # Scoring: 1.0 if caller channel preserved, 0.0 if overwritten to "phone"
