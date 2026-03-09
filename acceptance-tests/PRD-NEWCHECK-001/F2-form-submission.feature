Feature: Form submission and API integration
  As a logged-in HR user
  I want to submit a completed New Check form
  So that a verification check is created via POST /api/verify

  Background:
    Given I am authenticated as an HR user
    And I navigate to "/checks-dashboard/new"

  Scenario: Successful form submission redirects to dashboard
    Given I fill in "First Name" with "Bjorn"
    And I fill in "Last Name" with "Schliebitz"
    And I fill in "Position / Role" with "CRM Transformation Lead"
    And I fill in "Start Date" with "Feb 2019"
    And I fill in "End Date" with "Feb 2023"
    And I fill in "Employer Name" with "Engage & Experience"
    And I fill in "Country" with "Australia"
    When I click "Submit Check"
    Then the form should call POST "/api/verify" with the correct payload
    And I should be redirected to "/checks-dashboard"

  Scenario: API payload includes all filled fields
    Given I fill in the required fields
    And I fill in "Middle Name" with "James"
    And I fill in "Employer Website" with "http://example.com"
    And I fill in "City" with "Sydney"
    And I fill in "Contact Person Name" with "John"
    And I fill in "Contact Phone Number" with "+61 2 1234 5678"
    When I click "Submit Check"
    Then the POST "/api/verify" payload should include:
      | field               | value                |
      | firstName           | required value       |
      | lastName            | required value       |
      | middleName          | James                |
      | employerWebsite     | http://example.com   |
      | employerCity        | Sydney               |
      | contactPersonName   | John                 |
      | contactPhoneNumber  | +61 2 1234 5678      |

  Scenario: Verify fields are included in submission
    Given I check "Salary" in Additional Verification Points
    And I uncheck "Employment Type"
    And I check "Supervisor"
    When I click "Submit Check"
    Then the POST "/api/verify" payload verifyFields should include:
      | salary          | true  |
      | supervisor      | true  |
      | employment_type | false |

  Scenario: Agent type is always work-history-agent
    When I submit the form
    Then the POST "/api/verify" payload should have "agentType" equal to "work-history-agent"

  Scenario: Loading state shown during submission
    Given the API call takes more than 500ms
    When I click "Submit Check"
    Then the "Submit Check" button should show a loading indicator or be disabled
    And I should not be able to click "Submit Check" again

  Scenario: Success banner shown after redirect
    Given I submit a valid form
    When I am redirected to "/checks-dashboard"
    Then I should see a green success banner
    And the banner should contain text about successful submission

  Scenario: API error shows inline error banner
    Given the POST "/api/verify" returns a 400 error with message "Invalid phone number"
    When I click "Submit Check"
    Then I should see an error banner on the form page
    And the error banner should contain "Invalid phone number"
    And I should remain on "/checks-dashboard/new"

  # Scoring guide:
  # 1.0 - All scenarios pass including correct API payload
  # 0.8 - Form submits and redirects but payload has minor field name differences
  # 0.6 - Form submits but error handling or success banner missing
  # 0.4 - Form renders but submission does not call /api/verify
  # 0.0 - Form cannot be submitted
