@epic-4 @p1 @backend @browser
Feature: E4 — Verify & Test Task Status Lifecycle

  Background:
    Given the Prefect orchestrator and local PostgreSQL are running
    And at least one case exists with multiple sequence steps

  @scoring: 0.25
  Scenario: Multiple background_tasks created per case
    When I query background_tasks WHERE case_id = {test_case_id}
    Then there are at least 2 rows (one per sequence step)
    And each row has a distinct current_sequence_step value
    And task chaining is correct: task_N.next_task_id = task_N+1.id

  @scoring: 0.25
  Scenario: Status transitions through full Prefect flow
    When a new case is submitted and the Prefect flow runs to completion
    Then the first step's background_task has status = 'completed' or 'failed'
    And the second step's background_task has status = 'in_progress' or 'completed'
    And process_result.py was called (evidenced by result_status being non-null)

  @scoring: 0.15
  Scenario: Email-sent step does not stay in_progress forever
    Given a step dispatched an email (result.status = 'email_sent')
    When the orchestrator advances to the next step
    Then the email step's background_task status is not stuck at 'in_progress' indefinitely
    # Note: email steps may legitimately stay in_progress until verified via web form

  @scoring: 0.20 @browser
  Scenario: Case detail page shows per-step status badges
    Given a case exists with at least one completed and one in-progress step
    When I navigate to /checks-dashboard/cases/{case_id} in the browser
    Then each step in the timeline displays a status badge
    And completed steps show a green "Completed" badge
    And in-progress steps show a blue "In Progress" badge
    And steps without tasks show a gray "Pending" indicator

  @scoring: 0.15 @browser
  Scenario: Status updates on page reload
    Given a case has a step currently in_progress
    When the step completes (process_result.py runs)
    And I reload the case detail page
    Then the step's badge changes from "In Progress" to "Completed"
