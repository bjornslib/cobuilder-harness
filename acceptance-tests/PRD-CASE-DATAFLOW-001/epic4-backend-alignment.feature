Feature: E4 — PostCheckProcessor Type Alignment
  As a platform engineer
  I want both outcome paths to produce identical VerificationOutcome objects
  So that downstream consumers don't need path-specific handling

  Background:
    Given the Live Form Filler path via outcome_builder.py
    And the PostCheckProcessor path via process_post_call.py
    And the canonical VerificationOutcome from models/work_history.py

  # === was_employed fix ===

  Scenario: was_employed uses only valid EmploymentStatusEnum values
    When I inspect the _EMPLOYED_STATUSES in outcome_converter.py
    Then it should contain "verified" and "partial_verification"
    And NOT contain "currently_employed"

  Scenario: Legacy "currently_employed" maps to VERIFIED
    When _normalize_employment_status("currently_employed") is called
    Then it should return EmploymentStatusEnum.VERIFIED

  # === Salary produces two VerifiedField entries ===

  Scenario: Salary verification produces salary_amount VerifiedField
    Given a verification with salary checked and claimed amount="85000"
    When the PostCheckProcessor processes the outcome
    Then verified_data should contain key "salary_amount"
    And verified_data["salary_amount"].claimed should be "85000"

  Scenario: Salary verification produces salary_currency VerifiedField
    Given a verification with salary checked and claimed currency="AUD"
    When the PostCheckProcessor processes the outcome
    Then verified_data should contain key "salary_currency"
    And verified_data["salary_currency"].claimed should be "AUD"

  # === VerifiedField convergence ===

  Scenario: Outcome converter produces Pydantic VerifiedField from dataclass
    Given a PostCheckResult with dataclass VerifiedField objects
    When postcall_result_to_outcome() runs
    Then all verified_data values should be Pydantic VerifiedField instances

  # === Outcome equivalence ===

  Scenario: Both paths produce identical JSON schema
    Given the same verification data processed through both paths
    When both outcomes are serialized with model_dump(mode="json")
    Then the JSON schemas should be identical

  # === JSONB read safety ===

  Scenario: context_data reads use model_validate
    When I inspect JSONB reads of background_tasks.context_data
    Then they should use VerificationRequest.model_validate()
    And NOT raw dict access like json_data["candidate"]["first_name"]

  Scenario: verification_metadata reads use model_validate
    When I inspect JSONB reads of cases.verification_metadata
    Then they should use WorkHistoryVerificationMetadata.model_validate()

  Scenario: verification_results reads use model_validate
    When I inspect JSONB reads of cases.verification_results
    Then they should use VerificationOutcome.model_validate()

  # === Field name validation ===

  Scenario: outcome_builder warns on unknown field names
    Given a form submission with field_name="unknown_field"
    When build_verification_outcome() processes it
    Then a warning should be logged

  Scenario: outcome_builder accepts all known field names
    Given form submissions with field names:
      | start_date             |
      | end_date               |
      | position_title         |
      | supervisor_name        |
      | employment_type        |
      | employment_arrangement |
      | eligibility_for_rehire |
      | reason_for_leaving     |
      | salary_amount          |
      | salary_currency        |
    Then no warnings should be logged

  # === Naming ===

  Scenario: PostCallProcessor renamed to PostCheckProcessor
    When I search for "PostCallProcessor" in source files
    Then it should only appear in legacy comments or import aliases
    And active code should use "PostCheckProcessor"
