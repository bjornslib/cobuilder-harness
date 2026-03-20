@epic-2 @p1 @backend @frontend @browser
Feature: E2 — Case Detail Audit Trail with Sub_Threads

  Background:
    Given Epic 1 FK fix is deployed (sub_threads have correct background_task_id)
    And at least one case exists with sub_thread transcript data (chat and/or voice messages)

  @scoring: 0.20
  Scenario: Transcripts API returns sub_thread data
    When I call GET /api/v1/cases/{case_id}/transcripts with valid auth
    Then the response contains a list of CaseTranscriptEntry objects
    And each entry has sub_thread_id, channel, messages, message_count, created_at
    And entries with background_task_id link to a valid background_tasks.task_id

  @scoring: 0.15
  Scenario: Channel detection works correctly
    Given sub_threads exist with messages tagged channel="chat" and channel="phone"
    When I call GET /api/v1/cases/{case_id}/transcripts
    Then chat transcripts have channel="chat"
    And voice transcripts have channel="voice"

  @scoring: 0.25 @browser
  Scenario: Audit trail renders as accordions on case detail page
    When I navigate to /checks-dashboard/cases/{case_id} in the browser
    Then the audit trail section is visible below the timeline
    And each step with transcripts shows a collapsible accordion (closed by default)
    And each accordion header shows a channel badge (chat/voice/email)

  @scoring: 0.20 @browser
  Scenario: Expanding accordion shows transcript messages
    Given a step has chat transcript data
    When I click the accordion header for that step
    Then the accordion expands to show chronological messages
    And each message shows role (agent/verifier), content, and timestamp
    And messages are ordered by timestamp ascending

  @scoring: 0.10 @browser
  Scenario: Steps are chronologically ordered
    When I view the case detail page with multiple steps
    Then steps are ordered by step_order ascending
    And completed steps appear before pending steps within the same step_order

  @scoring: 0.10
  Scenario: Two-call loading strategy works
    When the case detail page loads
    Then the initial API call (GET /api/v1/cases/{case_id}) returns quickly without transcript data
    And transcript data is fetched via a separate call (GET /api/v1/cases/{case_id}/transcripts)
    And the audit trail section shows a loading state while transcripts are being fetched
