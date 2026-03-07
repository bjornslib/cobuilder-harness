@epic-E5 @sd-HARNESS-UPGRADE-001-E5
Feature: Attractor Schema + Validate CLI Extension

  # Epic 5 extends the DOT schema and cobuilder pipeline validate to enforce
  # topology rules and required attributes.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E5-schema-validate-cli.md

  @feature-F5.1 @weight-0.04
  Scenario: S5.1 — sd_path mandatory on codergen nodes
    Given a DOT pipeline file with a codergen node WITHOUT sd_path attribute
    When I run "cobuilder pipeline validate <file>"
    Then the validator outputs an error mentioning sd_path as missing/required
    And the exit code is non-zero

    Given a DOT pipeline file with a codergen node WITH sd_path attribute
    When I run "cobuilder pipeline validate <file>"
    Then no error about sd_path appears
    And the validation passes (or only has unrelated warnings)

    # Confidence scoring guide:
    # 1.0 — Validator rejects missing sd_path with clear error, passes when present
    # 0.5 — Validator warns but doesn't error, or error message unclear
    # 0.0 — No sd_path validation

  @feature-F5.2 @weight-0.04
  Scenario: S5.2 — Epic-level E2E gate check
    Given a DOT pipeline with:
      - An epic cluster containing codergen nodes
      - NO wait.system3 gate downstream of the codergen nodes
    When I run "cobuilder pipeline validate <file>"
    Then the validator outputs an error about missing E2E gate for the epic
    And the error references the epic_id

    Given a DOT pipeline with:
      - An epic cluster containing codergen nodes
      - A wait.system3[e2e] -> wait.human pair downstream
    When I run "cobuilder pipeline validate <file>"
    Then no E2E gate error appears

    # Confidence scoring guide:
    # 1.0 — Validator detects missing gate pairs per epic and passes when present
    # 0.5 — Validation exists but doesn't check per-epic (only global)
    # 0.0 — No E2E gate validation

  @feature-F5.3 @weight-0.03
  Scenario: S5.3 — worker_type registry check rejects unknown types (6 valid)
    Given a DOT pipeline with worker_type="unknown-agent-type" on a node
    When I run "cobuilder pipeline validate <file>"
    Then the validator outputs an error about unknown worker_type
    And the error lists valid worker_type values (6 types, no compliance-researcher)

    # Confidence scoring guide:
    # 1.0 — Unknown types rejected with error listing 6 valid options
    # 0.5 — Unknown types warned but not rejected (soft check)
    # 0.0 — No worker_type validation

  @feature-F5.4 @weight-0.03
  Scenario: S5.4 — wait.human topology enforced
    Given a DOT pipeline where wait.human follows a codergen node directly
      (without an intervening wait.system3 or research node)
    When I run "cobuilder pipeline validate <file>"
    Then the validator outputs a topology error for wait.human
    And the error states that wait.human must follow wait.system3 or research

    Given a DOT pipeline where wait.human correctly follows wait.system3
    When I run "cobuilder pipeline validate <file>"
    Then no topology error for wait.human appears

    # Confidence scoring guide:
    # 1.0 — Invalid topology rejected, valid topology passes
    # 0.5 — Check exists but too permissive
    # 0.0 — No wait.human topology validation

  @feature-F5.5 @weight-0.02
  Scenario: S5.5 — Acceptance-test-writer topology and skills_required validation
    Given a DOT pipeline with a codergen cluster but no acceptance-test-writer node
    When I run "cobuilder pipeline validate <file>"
    Then the validator outputs a warning about missing acceptance-test-writer

    Given a DOT pipeline with worker_type="frontend-dev-expert" and
      the agent definition at .claude/agents/frontend-dev-expert.md lists
      skills_required: [react-best-practices, nonexistent-skill]
    When I run "cobuilder pipeline validate <file>"
    Then the validator outputs a warning about nonexistent-skill not found in .claude/skills/

    # Confidence scoring guide:
    # 1.0 — Both AT writer topology and skills_required validation produce warnings
    # 0.5 — One of the two validations works
    # 0.0 — Neither validation implemented
