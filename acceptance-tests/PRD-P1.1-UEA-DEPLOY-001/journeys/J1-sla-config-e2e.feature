@journey @prd-P1.1-UEA-DEPLOY-001 @J1 @api @db @smoke
Feature: SLA Configuration End-to-End via API

  Scenario J1: Create check type via API and verify in database
    # Goal G3: SLA CRUD API works end-to-end
    # This journey crosses: API → DB → API (read-back)

    # API layer — create
    # TOOL: curl
    Given I have a valid API authentication token
    When I POST to /api/v1/sla/check-types with:
      """
      {"name": "j1_test_type", "display_name": "Journey Test Type", "default_sla_hours": 36}
      """
    Then the API returns HTTP 201 or 200
    And the response body contains an id field

    # DB layer — verify persistence
    # TOOL: direct psql query
    And the check_types table has a row where name = 'j1_test_type' and default_sla_hours = 36

    # API layer — read-back
    # TOOL: curl GET
    When I GET /api/v1/sla/check-types
    Then the response includes j1_test_type with default_sla_hours = 36

    # API layer — add sequence steps
    # TOOL: curl POST
    When I POST /api/v1/sla/check-types/{id}/sequence with:
      """
      {"step_name": "j1_step_1", "step_order": 1, "delay_hours": 0, "max_attempts": 1}
      """
    Then the API returns HTTP 201 or 200

    # API layer — verify sequence
    # TOOL: curl GET
    When I GET /api/v1/sla/check-types/{id}/sequence
    Then the response contains 1 step with step_name = 'j1_step_1'

    # Business outcome
    And the SLA configuration is fully round-trippable: create → persist → read → extend with sequence
