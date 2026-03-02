Feature: Recording Reliability — Egress recording always persists to DB

  Background:
    Given a voice verification call completes successfully
    And LiveKit Cloud egress records the room to S3

  @recording @critical
  Scenario: S1.1 Recording S3 key persists to cases table after call close
    When the CallClosingAgent ends the call
    Then schedule_finalization runs to completion
    And cases.call_recording_s3_key is populated with the S3 path
    And the recording file exists in S3 at that path

    # Confidence Guide:
    # 0.0 — call_recording_s3_key is NULL after call completes
    # 0.5 — recording exists in S3 but DB key is sometimes NULL (race condition)
    # 1.0 — call_recording_s3_key is always populated when egress completes

  @recording @critical
  Scenario: S1.2 Recording displays on case detail page
    Given the call has completed with recording uploaded to S3
    When the user navigates to /checks-dashboard/cases/{task_id}
    Then the audio player is visible
    And clicking play streams the recording from S3

    # Confidence Guide:
    # 0.0 — no audio player or "No recording" message
    # 0.5 — audio player visible but playback fails
    # 1.0 — audio plays back the actual call recording

  @recording @robustness
  Scenario: S1.3 Egress finalization survives process teardown
    Given the voice agent process is shutting down
    When schedule_finalization has been called but not completed
    Then the finalization task should complete before process exit
    Or a recovery mechanism should detect the missing S3 key and backfill it

    # Confidence Guide:
    # 0.0 — process exits, finalization cancelled, recording URL lost
    # 0.5 — finalization sometimes completes depending on timing
    # 1.0 — finalization always completes OR recovery backfills missing keys

  @recording @investigation
  Scenario: S1.4 Room deletion does not cancel egress recording
    When the room is deleted via delete_room API
    Then the egress recording should still complete upload to S3
    And stop_recording should be called BEFORE delete_room (not after)

    # Confidence Guide:
    # 0.0 — room deletion terminates egress before S3 upload
    # 0.5 — egress usually survives room deletion but not always
    # 1.0 — egress is independent of room lifecycle (stop_recording called first)

  @recording @manual-test
  Scenario: S1.5 End-to-end recording verification (manual local test)
    Given a local voice agent running with S3 egress enabled
    When a test call is initiated and completed
    Then the recording file appears in S3
    And cases.call_recording_s3_key is populated
    And the case detail page shows the audio player with playback working
