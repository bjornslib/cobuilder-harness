Feature: Dashboard + New check button
  As a logged-in HR user
  I want a "+ New check" button on the checks dashboard
  So that I can quickly start a new verification from the main view

  Background:
    Given I am authenticated as an HR user
    And I navigate to "/checks-dashboard"

  Scenario: + New check button appears in dashboard header
    Then I should see a button labeled "+ New check" or "New check"
    And the button should be in the top-right area of the page header
    And the button should have a primary (dark purple) background color

  Scenario: + New check button navigates to new check page
    When I click the "+ New check" button
    Then I should be navigated to "/checks-dashboard/new"

  Scenario: Cancel button on new check page returns to dashboard
    Given I navigate to "/checks-dashboard/new"
    When I click the "Cancel" button
    Then I should be navigated to "/checks-dashboard"
    And no verification check should have been submitted

  Scenario: Success banner appears after form submission
    Given I have just submitted a valid new check form
    When I am redirected to "/checks-dashboard"
    Then I should see a green success banner at the top of the page
    And the banner should indicate the check was submitted successfully

  Scenario: Success banner not shown on normal dashboard visit
    Given I navigate directly to "/checks-dashboard" without query params
    Then I should NOT see a success banner

  # Scoring guide:
  # 1.0 - All 5 scenarios pass
  # 0.8 - Button present and links work but success banner missing
  # 0.6 - Button present but not styled correctly (wrong color/position)
  # 0.4 - Navigation works but button is missing from dashboard header
  # 0.0 - No button, no navigation
