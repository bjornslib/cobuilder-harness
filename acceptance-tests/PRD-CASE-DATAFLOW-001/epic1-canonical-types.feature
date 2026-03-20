Feature: E1 — Canonical Type Definitions & ISO Standards
  As a platform engineer
  I want a single source of truth for all work history verification types
  So that field name mismatches are caught at build time

  Background:
    Given the Pydantic models in "models/work_history.py" are the canonical types
    And the router at "api/routers/work_history.py" imports from canonical module

  # === Model consolidation ===

  Scenario: No duplicate model definitions in router
    When I inspect "api/routers/work_history.py"
    Then it should NOT define its own CandidateInfo class
    And it should NOT define its own EmployerInfo class
    And it should import CandidateInfo from "models.work_history"
    And it should import EmployerInfo from "models.work_history"

  # === CandidateInfo ===

  Scenario: CandidateInfo includes middle_name
    When I create a CandidateInfo with first_name="John", middle_name="Michael", last_name="Smith"
    Then the model should be valid
    And middle_name should be "Michael"

  # === EmployerInfo — country_code ISO 3166-1 ===

  Scenario: EmployerInfo validates country_code via pycountry
    When I create an EmployerInfo with country_code="AU"
    Then the model should be valid

  Scenario: EmployerInfo rejects invalid country_code
    When I create an EmployerInfo with country_code="XX"
    Then a validation error should be raised

  Scenario: country_code is mandatory
    When I create an EmployerInfo without country_code
    Then a validation error should be raised

  # === EmployerInfo — website optional ===

  Scenario: EmployerInfo accepts missing website
    When I create an EmployerInfo without employer_website_url
    Then the model should be valid

  # === EmployerInfo — contacts list ===

  Scenario: EmployerInfo accepts contacts list
    When I create an EmployerInfo with contacts=[{contact_name: "Jane", is_primary: true}]
    Then contacts[0].contact_name should be "Jane"
    And contacts[0].is_primary should be true

  Scenario: EmployerContactPerson requires at least one field
    When I create an EmployerContactPerson with all fields null
    Then a validation error should be raised

  # === EmployerInfo — phone_numbers ===

  Scenario: phone_numbers lives on EmployerInfo not VerificationRequest
    When I inspect the VerificationRequest model
    Then it should NOT have a phone_numbers field
    And EmployerInfo should have phone_numbers field

  Scenario: phone_numbers validates international format
    When I create an EmployerInfo with phone_numbers=["+61 2 9123 4567"]
    Then the model should be valid

  # === EmploymentClaim — salary split ===

  Scenario: EmploymentClaim has separate salary_amount and salary_currency
    When I create an EmploymentClaim with salary_amount="85000" and salary_currency="AUD"
    Then both fields should be present and separate

  Scenario: salary_currency auto-derived from country_code
    Given an EmployerInfo with country_code="AU"
    When _transform_to_metadata() processes a request with salary_amount but no salary_currency
    Then salary_currency should be set to "AUD" via babel

  # === VerifyFields — employment_arrangement ===

  Scenario: VerifyFields includes employment_arrangement
    When I create a VerifyFields with employment_arrangement=True
    Then the model should be valid

  # === VerifyFields — eligibility_for_rehire ===

  Scenario: VerifyFields uses eligibility_for_rehire as field name
    When I inspect the VerifyFields model
    Then the field name should be "eligibility_for_rehire"

  # === CustomerAgreement removed ===

  Scenario: CustomerAgreement does not exist in models
    When I search for "CustomerAgreement" in models/work_history.py
    Then it should not be found

  Scenario: WorkHistoryVerificationMetadata has no customer_agreement field
    When I inspect WorkHistoryVerificationMetadata
    Then it should NOT have a customer_agreement field

  # === _transform_to_metadata — structural only ===

  Scenario: Transform does not rename any fields
    Given a VerificationRequest with employer.contacts[0].contact_name="Jane"
    When _transform_to_metadata() runs
    Then the metadata.employer.contacts[0].contact_name should be "Jane"
    And no field should have been renamed to hr_contact_name or hr_email

  # === DB migration ===

  Scenario: default_sla column removed from check_types
    Given the migration has been applied
    When I inspect the check_types table
    Then it should NOT have a default_sla column

  # === TypeScript generation ===

  Scenario: TypeScript types file matches Pydantic models
    Given generate_ts_types.py has been run
    Then "lib/types/work-history.generated.ts" should contain:
      | Interface               |
      | CandidateInfo           |
      | EmployerInfo            |
      | EmployerContactPerson   |
      | EmploymentClaim         |
      | VerifyFields            |
      | VerificationOutcome     |
      | VerifiedField           |
      | VerifierInfo            |
    And it should contain COUNTRY_CODES constant
    And it should contain COUNTRY_DEFAULT_CURRENCY constant

  Scenario: Pre-push hook detects drift
    Given a Pydantic model field has been changed
    And generate_ts_types.py has NOT been re-run
    When git push is attempted
    Then the pre-push hook should fail with a diff

  # === outcome_converter ===

  Scenario: outcome_converter uses only valid EmploymentStatusEnum
    When I inspect the _EMPLOYED_STATUSES set in outcome_converter.py
    Then all values should be valid EmploymentStatusEnum members
    And "currently_employed" should NOT be in the comparison set
