Feature: Form validation
  As a logged-in HR user
  I want the form to validate required fields
  So that I cannot submit incomplete verification requests

  Background:
    Given I am authenticated as an HR user
    And I navigate to "/checks-dashboard/new"

  Scenario: Submitting empty form shows validation errors
    When I click "Submit Check" without filling any fields
    Then I should see validation error messages on the form
    And POST "/api/verify" should NOT have been called
    And I should remain on "/checks-dashboard/new"

  Scenario: Required fields are validated
    When I click "Submit Check" without filling any fields
    Then I should see error indicators on "First Name", "Last Name", "Position / Role", "Start Date", "End Date", "Employer Name"

  Scenario: Optional fields do not trigger validation errors
    Given I fill in all required fields
    And I leave "Middle Name", "Task ID", "Contact Person Name" empty
    When I click "Submit Check"
    Then I should NOT see validation errors for those optional fields
    And the form should submit successfully

  Scenario: Filling a required field clears its validation error
    Given I clicked "Submit Check" with empty "First Name"
    And I see a validation error on "First Name"
    When I fill in "First Name" with "Jane"
    Then the validation error on "First Name" should clear

  # Scoring guide:
  # 1.0 - All 4 scenarios pass
  # 0.8 - Required fields validated but error messages not cleared on input
  # 0.6 - Submission blocked but no inline error indicators
  # 0.4 - Some required fields validated but not all
  # 0.0 - Form submits without validation
