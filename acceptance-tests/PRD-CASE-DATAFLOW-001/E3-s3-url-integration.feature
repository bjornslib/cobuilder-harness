@epic-3 @p2 @frontend
Feature: E3 — S3 Recording & Transcript URL Integration

  Background:
    Given Epic 2 audit trail is deployed
    And a completed step exists with an S3 recording and/or transcript

  @scoring: 0.25
  Scenario: Timeline entries include has_recording and has_transcript flags
    When I call GET /api/v1/cases/{case_id}
    Then completed timeline entries include has_recording boolean
    And completed timeline entries include has_transcript boolean
    And entries without recordings have has_recording = false

  @scoring: 0.25
  Scenario: NextJS proxy routes forward to backend
    When I call GET /api/verification-recordings/{task_id} via the NextJS proxy
    Then the request is forwarded to the Railway backend with Clerk JWT auth
    And the response contains a presigned S3 URL with an expiry timestamp

  @scoring: 0.25
  Scenario: Recording playback button appears for steps with recordings
    Given a completed step has has_recording = true
    When I view the case detail page in the browser
    Then a play button appears in that step's audit trail entry
    And clicking the play button fetches the presigned URL and renders an audio player

  @scoring: 0.25
  Scenario: Transcript view loads on demand
    Given a completed step has has_transcript = true
    When I click "View Transcript" on that step
    Then the transcript content loads from the proxy endpoint
    And the transcript displays as formatted messages (not raw JSON)
