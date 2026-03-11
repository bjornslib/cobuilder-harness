Feature: Epic B — Dashboard Backend API
  As a frontend developer
  I need a GET /api/v1/cases/{case_id} endpoint with timeline data
  So the case detail page can display the full audit trail

  Background:
    Given the agencheck-support-agent repository on branch "feat/dashboard-audit-perstep"
    And the backend API is running (via Docker or local)

  # --- Case Detail Endpoint ---

  @endpoint @scoring:pass=1.0,fail=0.0
  Scenario: GET /cases/{case_id} route handler exists
    When I inspect "api/routers/work_history.py"
    Then a route handler decorated with @router.get exists for path "/api/v1/cases/{case_id}"
    And it accepts case_id as an integer path parameter

  @response-model @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Case detail response includes required fields
    When I inspect the CaseDetailResponse Pydantic model
    Then it includes fields:
      | field                   | type           |
      | case_id                 | int            |
      | status                  | str            |
      | status_label            | str            |
      | candidate_name          | str            |
      | employer_name           | str            |
      | check_type              | str            |
      | created_at              | str/datetime   |
      | latest_employment_status| str or None    |
      | sequence_progress       | object         |
      | timeline                | list           |
      | verification_results    | object or None |

  @timeline @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Timeline synthesizes future steps from sequence definition
    When I inspect the "get_case_timeline" service method
    Then it queries completed background_tasks for the case
    And it queries the background_check_sequence definition
    And it LEFT JOINs or merges actual tasks with all sequence steps
    And steps without a matching task appear as pending entries with task_id=null
    And each timeline entry includes step_order, step_name, step_label, channel_type

  # --- Service layer ---

  @service @scoring:pass=1.0,fail=0.0
  Scenario: get_case_by_id service method exists
    When I inspect "api/routers/work_history.py"
    Then a method "get_case_by_id" exists in WorkHistoryDBService
    And it accepts case_id as integer parameter
    And it returns case overview data from the cases table

  # --- Status Labels ---

  @status-labels @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: StatusLabelMapper provides canonical labels
    When I inspect "utils/status_labels.py"
    Then class "StatusLabelMapper" exists
    And it has a method "result_status" mapping raw status to display label
    And it has a method "case_status" mapping case status to display label
    And it has a method "is_terminal" checking if status is terminal
    And all 14 CallResultStatus values are mapped
    And the word "unreachable" does not appear in any label

  @ci-export @scoring:pass=1.0,fail=0.0
  Scenario: CI export script generates TypeScript constants
    When I inspect "scripts/export_status_labels.py"
    Then it imports StatusLabelMapper
    And it generates a TypeScript file at the expected frontend path
    And the generated file exports status label constants

  # --- Migration ---

  @migration @scoring:pass=1.0,fail=0.0
  Scenario: Migration adds latest_employment_status to cases
    When I inspect migration files for "latest_employment_status"
    Then a migration adds column "latest_employment_status" TEXT to "cases" table
    And it includes a backfill query from most recent completed task per case
    And it has IF NOT EXISTS guard

  # --- List endpoint update ---

  @list-update @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: list_verifications includes new fields
    When I inspect the list_verifications query in work_history.py
    Then the response includes "case_id" (integer, from cases table)
    And the response includes "sequence_progress" summary
    And the response includes "status_label" from StatusLabelMapper

  # --- API integration test (Docker) ---

  @api-test @docker @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: GET /api/v1/cases/{case_id} returns valid JSON from running API
    Given the backend Docker container is running
    When I send GET request to "/api/v1/cases/1"
    Then the response status is 200 or 404
    And if 200, the response body matches CaseDetailResponse schema
    And the timeline array contains entries with step_order field
    And status_label is a non-empty string
