Feature: E3 — API Proxy Contract Alignment
  As a platform engineer
  I want the frontend proxy to pass canonical types without field renaming
  So that no data is silently lost or misnamed

  Background:
    Given the API proxy at "app/api/verify/route.ts"

  # === Zero field renaming ===

  Scenario: No field renaming exists in proxy
    When I inspect route.ts
    Then there should be NO mapping from "supervisor" to "supervisor_name"
    And NO mapping from "contact_name" to "hr_contact_name"
    And NO mapping from "contact_email" to "hr_email"
    And NO mapping from "rehire_eligibility" to "eligibility_for_rehire"

  Scenario: Proxy uses canonical field names throughout
    Given frontend sends eligibility_for_rehire=true
    When the proxy builds verify_fields
    Then the key should be "eligibility_for_rehire" (same name, no mapping)

  # === Contacts list ===

  Scenario: Proxy passes contacts list not single contact
    Given frontend sends contacts=[{contact_name: "Jane", is_primary: true}]
    When the proxy builds the employer object
    Then employer.contacts should be the array as-is

  # === country_code ===

  Scenario: Proxy passes country_code not country name
    Given frontend sends country_code="AU"
    When the proxy builds the employer object
    Then employer.country_code should be "AU"
    And there should be NO "country" field with a full name

  # === Salary split ===

  Scenario: Proxy passes salary_amount and salary_currency separately
    Given frontend sends salary_amount="85000" and salary_currency="AUD"
    When the proxy builds the employment object
    Then employment.salary_amount should be "85000"
    And employment.salary_currency should be "AUD"

  # === phone_numbers in employer ===

  Scenario: phone_numbers passed inside employer object
    Given frontend sends phone_numbers=["+61 2 9123 4567"]
    When the proxy builds the payload
    Then employer.phone_numbers should contain "+61 2 9123 4567"
    And there should be NO top-level phone_numbers field

  # === Type imports ===

  Scenario: Proxy imports canonical TypeScript types
    When I inspect the imports in route.ts
    Then it should import from "lib/types/work-history.generated"
    And NOT define inline FrontendVerifyFields interface

  # === Date validation ===

  Scenario: Proxy rejects invalid date format
    Given frontend sends startDate="not-a-date"
    When the proxy processes the request
    Then it should return HTTP 400

  # === Regression ===

  Scenario: Standard submission succeeds end-to-end
    Given a valid complete form submission
    When the proxy forwards to /api/v1/verify
    Then the response should be HTTP 201 with a task_id
