@epic-1 @p0 @backend
Feature: E1 — Fix task_id/case_id FK Violation in sub_threads

  Background:
    Given a case exists in the PostgreSQL database with case_id and a linked background_task with a UUID task_id
    And migration 042 (background_task_id column on sub_threads) is applied

  @scoring: 0.30
  Scenario: LiveKit agent stores transcript without FK violation
    When the LiveKit agent completes a voice session for the case
    And on_session_end triggers store_unified_transcript
    Then the sub_threads INSERT succeeds without FK constraint violation
    And the sub_threads.background_task_id contains a valid UUID string
    And that UUID matches an existing background_tasks.task_id row

  @scoring: 0.25
  Scenario: UUID propagated through dispatch chain
    When dispatch_work_history_call is called with case_id and task_id (integer PK)
    Then job_metadata contains both "task_id" (integer) and "task_uuid" (UUID string)
    And agent.py session.userdata contains "task_uuid" with the UUID string
    And agent.py session.userdata contains "background_task_id" with the integer PK

  @scoring: 0.25
  Scenario: Transcript session isolation
    Given two concurrent LiveKit sessions exist for the same case but different background_tasks
    When both sessions write transcripts to sub_threads
    Then each session creates a separate sub_thread record
    And each sub_thread.background_task_id matches its own session's UUID
    And messages from session A do not appear in session B's sub_thread

  @scoring: 0.20
  Scenario: Phone call transcript also writes correctly
    When Prefect dispatches a phone call via dispatch_channel_verification(VOICE)
    And the LiveKit agent completes the phone call
    Then on_session_end writes the call transcript to sub_threads
    And sub_threads.background_task_id contains the correct UUID for that step's background_task
    And the messages have channel="phone" metadata
