@epic-E2 @sd-HARNESS-UPGRADE-001-E2
Feature: PRD Contract + E2E Gate Protocol

  # Epic 2 defines the PRD Contract artifact and integrates E2E gates
  # into the guardian workflow.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E2-prd-contract.md

  @feature-F2.1 @weight-0.04
  Scenario: S2.1 — PRD Contract template exists with required sections
    Given the project documentation directory exists
    When I search for a PRD Contract template file
    Then the template contains these required sections:
      - Domain Invariants (3-5 truths that MUST hold)
      - Scope Freeze (in-scope and explicitly out-of-scope)
      - Compliance Flags (table with flag, required, rationale)
    And the template has YAML frontmatter with prd_id, contract_version, generated, frozen_at_commit

    # Confidence scoring guide:
    # 1.0 — Template exists with all 3 sections + frontmatter
    # 0.5 — Template exists but missing one section or frontmatter
    # 0.0 — No template found

    # Evidence to check:
    # - prd-contract-template.md or equivalent
    # - YAML frontmatter block
    # - All 3 required sections present

  @feature-F2.2 @weight-0.03
  Scenario: S2.2 — Phase 0 workflow includes contract generation step
    Given the Phase 0 workflow documentation exists (phase0-prd-design.md)
    When I search for contract generation step
    Then a step labeled "0.2.5" or similar exists between pipeline creation and design challenge
    And the step describes:
      - Read PRD goals and epics
      - Extract 3-5 domain invariants
      - List scope boundaries
      - Set compliance flags
      - Write to docs/prds/{initiative}/prd-contract.md
      - Record frozen_at_commit

    # Confidence scoring guide:
    # 1.0 — Step exists in correct position with all substeps
    # 0.5 — Step exists but missing substeps or in wrong position
    # 0.0 — No contract generation step in Phase 0

  @feature-F2.3 @weight-0.04
  Scenario: S2.3 — wait.system3 gate logic references contract validation
    Given the guardian workflow documentation exists
    When I search for wait.system3 gate processing logic
    Then the logic includes:
      - Check if contract_ref attribute is set on the node
      - If set: read PRD Contract
      - Validate each domain invariant against current codebase
      - Validate scope freeze (no out-of-scope file modifications)
      - Check compliance flags
      - Include contract compliance score in gate summary
    And contract validation failure is documented as blocking (gate transitions to "failed")

    # Confidence scoring guide:
    # 1.0 — Full contract validation logic documented with failure behavior
    # 0.5 — Contract mentioned in gate logic but validation steps incomplete
    # 0.0 — No contract validation in wait.system3 logic

    # Red flags:
    # - Contract validation described as optional/advisory
    # - No failure path documented
