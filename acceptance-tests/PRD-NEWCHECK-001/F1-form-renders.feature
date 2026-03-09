Feature: New Check form page renders at /checks-dashboard/new
  As a logged-in HR user
  I want to access a New Verification form
  So that I can submit checks without using the Voice Sandbox

  Background:
    Given I am authenticated as an HR user
    And I navigate to "/checks-dashboard/new"

  Scenario: Page inherits checks-dashboard layout
    Then I should see the shared top navigation bar
    And I should see the checks sidebar with navigation items
    And the sidebar should show "Dashboard", "Agent SLAs", "Voice Sandbox" items

  Scenario: Page header shows correct title
    Then I should see the page heading "New Verification"
    And I should see the breadcrumb "Checks > New Verification"
    And I should see the subtitle "Submit a new background verification check for a candidate."

  Scenario: Check Selection section renders
    Then I should see a "Check Selection" section
    And I should see a "Work History" radio option that is selected by default
    And I should see a "Schedule Work History" radio option that is disabled or visually inactive

  Scenario: Candidate Details section renders with correct fields
    Then I should see a "Candidate Details" section
    And I should see input fields for "First Name", "Middle Name", "Last Name"
    And I should see an input field for "Position / Role"
    And I should see input fields for "Start Date" and "End Date"
    And I should see a dropdown for "Employment Type"
    And I should see an optional input for "Task ID"

  Scenario: Employer Details section renders with correct fields
    Then I should see an "Employer Details" section
    And I should see input fields for "Employer Name" and "Employer Website"
    And I should see input fields for "Country" and "City"
    And I should see an input for "Contact Person Name"
    And I should see an input for "Contact Phone Number"

  Scenario: Additional Verification Points section renders
    Then I should see an "Additional Verification Points" section
    And I should see checkboxes for "Salary", "Supervisor", "Employment Type", "Rehire Eligibility", "Reason for Leaving"
    And "Employment Type" should be checked by default

  Scenario: Call Configuration section renders
    Then I should see a "Call Configuration" section
    And I should see a dropdown for "Location" defaulting to "Singapore"
    And I should see a dropdown for "Phone Type"

  Scenario: Action buttons present
    Then I should see a "Cancel" button
    And I should see a "Submit Check" primary button

  # Scoring guide:
  # 1.0 - All 8 scenarios pass
  # 0.8 - Page renders with all sections but minor styling differences
  # 0.6 - Page renders but missing 1-2 sections or fields
  # 0.4 - Page renders but missing >2 sections
  # 0.0 - Page does not render or 404
