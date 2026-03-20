@epic-5 @p3 @backend
Feature: E5 — Non-Sequential Public Case Identifiers

  @scoring: 0.20
  Scenario: Public ID generated on case creation
    When a new case is created via POST /api/verify
    Then the cases row has a non-null public_id
    And public_id matches the pattern [A-Z][0-9]{3} (e.g., "A329")
    And public_id is unique across all cases

  @scoring: 0.20
  Scenario: Collision retry works
    Given 25,000 cases already exist (high collision probability)
    When a new case is created
    Then the INSERT retries until a unique public_id is found
    And the case is created successfully

  @scoring: 0.20
  Scenario: Case detail resolves by public_id
    Given a case exists with public_id = "M071"
    When I call GET /api/v1/cases/M071 with valid auth
    Then the response returns the correct case data
    And the response includes public_id = "M071"

  @scoring: 0.20
  Scenario: Case detail still resolves by integer ID (backward compat)
    Given a case exists with id = 83 and public_id = "M071"
    When I call GET /api/v1/cases/83 with valid auth
    Then the response returns the same case data as /api/v1/cases/M071

  @scoring: 0.20
  Scenario: Dashboard links use public_id
    When I view /checks-dashboard and click a case row
    Then the URL navigates to /checks-dashboard/cases/{public_id}
    And the URL does NOT contain the integer case_id
