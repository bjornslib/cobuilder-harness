Feature: E2 — Frontend Form shadcn Component Upgrade
  As a verification operator
  I want a form with proper components and complete field coverage
  So that my data is always valid and complete

  Background:
    Given the New Verification form at "/checks-dashboard/new"

  # === DatePicker ===

  Scenario: Start date uses shadcn DatePicker
    When I inspect the startDate form field
    Then it should render a DatePicker (Calendar + Popover)
    And NOT a raw HTML input type="date"

  Scenario: DatePicker produces YYYY-MM-DD format
    When I select March 19, 2026 in the DatePicker
    Then the form value should be "2026-03-19"

  # === Country Combobox ===

  Scenario: Country uses shadcn Combobox with ISO alpha-2
    When I inspect the country field
    Then it should render a Combobox with searchable country list
    And selecting "Australia" should store "AU"

  Scenario: Country list derived from generated types
    When I inspect the Combobox options
    Then they should come from COUNTRY_CODES in work-history.generated.ts

  # === middle_name ===

  Scenario: Middle name field is present
    When I inspect the Candidate Details section
    Then there should be a "Middle Name" input between First Name and Last Name

  # === Employment Type ===

  Scenario: Employment Type has all backend enum values
    When I open the Employment Type Select
    Then options should be: full_time, part_time, contractor, casual
    And NOT contain "contract"

  # === Employment Arrangement ===

  Scenario: Employment Arrangement Select is present
    When I inspect the form
    Then there should be an "Employment Arrangement" Select
    With options: direct, agency, subcontractor

  Scenario: Agency Name appears for agency arrangement
    Given Employment Arrangement is "agency"
    Then "Agency Name" input should be visible and required

  Scenario: Agency Name hidden for direct arrangement
    Given Employment Arrangement is "direct"
    Then "Agency Name" input should NOT be visible

  # === Salary amount + currency ===

  Scenario: Salary checkbox reveals amount and currency fields
    When I enable the "Salary" verification checkbox
    Then two fields should appear: "Salary Amount" and "Salary Currency"

  Scenario: Salary currency auto-populated from country
    Given country is set to "AU"
    When I enable the "Salary" verification checkbox
    Then "Salary Currency" should default to "AUD"
    And the user should be able to change it

  # === Multiple contacts ===

  Scenario: Contact person list supports multiple entries
    When I inspect the Employer Details section
    Then there should be a primary contact form (name, department, position, email, phone)
    And an "Add Contact" button to add additional contacts

  Scenario: Primary contact is contacts[0]
    Given I fill primary contact name="Jane" and add another contact name="Bob"
    When I submit the form
    Then the payload contacts[0].contact_name should be "Jane"
    And contacts[1].contact_name should be "Bob"

  # === VerifyFields checkboxes ===

  Scenario: Verify Fields includes employment_arrangement
    When I inspect the Additional Verification Points section
    Then checkboxes should include "Employment Arrangement"

  # === Zod schema ===

  Scenario: Zod rejects invalid date format
    When startDate is set to "invalid"
    Then validation error should mention YYYY-MM-DD format

  Scenario: Form uses generated TypeScript types
    When I inspect the imports in page.tsx
    Then it should import from "lib/types/work-history.generated"
