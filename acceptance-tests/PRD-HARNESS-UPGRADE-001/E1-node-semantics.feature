@epic-E1 @sd-HARNESS-UPGRADE-001-E1
Feature: Node Semantics Clarification

  # Epic 1 formalizes wait.system3 and wait.human as first-class handler types
  # with mandatory topology rules in the DOT pipeline schema.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E1-node-semantics.md

  @feature-F1.1 @weight-0.03
  Scenario: S1.1 — wait.system3 handler fully defined in agent-schema.md
    Given the schema documentation file exists (agent-schema.md or equivalent)
    When I search for "wait.system3" handler definition
    Then the definition includes:
      | Attribute    | Required | Description |
      | gate_type    | yes      | enum: unit, e2e, contract |
      | contract_ref | optional | path to PRD Contract |
      | summary_ref  | yes      | path for summary output |
    And the behavior description specifies:
      - Executed by Python runner (PipelineRunner), not by an LLM
      - Reads signal files from completed predecessor workers
      - Reads concerns.jsonl for worker-raised concerns
      - Runs acceptance tests based on gate_type
      - Validates against PRD Contract if contract_ref is set
      - Retains confidence score to Hindsight
      - Writes summary to summary_ref path
      - Transitions to validated or failed (no human prompt)

    # Confidence scoring guide:
    # 1.0 — Full handler definition with all attributes, behavior steps, executor clarification
    # 0.5 — Handler mentioned but attributes incomplete or executor unclear
    # 0.0 — No wait.system3 handler definition in schema docs

    # Red flags:
    # - wait.system3 described as requiring human input
    # - Missing gate_type attribute
    # - Executor described as LLM rather than Python runner

  @feature-F1.2 @weight-0.02
  Scenario: S1.2 — wait.human handler fully defined in agent-schema.md
    Given the schema documentation file exists
    When I search for "wait.human" handler definition
    Then the definition includes:
      | Attribute   | Required | Description |
      | summary_ref | yes      | path to read summary from |
    And the behavior description specifies:
      - Reads summary from summary_ref (written by preceding node)
      - Emits review request to GChat
      - Blocks until human responds
      - Transitions to validated (approved) or failed (rejected)

    # Confidence scoring guide:
    # 1.0 — Full definition with attributes, behavior, and GChat emission
    # 0.5 — Handler mentioned but missing GChat or blocking behavior
    # 0.0 — No wait.human handler definition

  @feature-F1.3 @weight-0.04
  Scenario: S1.3 — Full codergen cluster topology documented
    Given the schema or workflow documentation exists
    When I search for topology rules for codergen clusters
    Then the full cluster topology is documented:
      "acceptance-test-writer -> research -> refine -> codergen -> wait.system3[e2e] -> wait.human[e2e-review]"
    And the documentation specifies:
      - acceptance-test-writer at start generates blind Gherkin tests from PRD
      - research and refine are optional intermediate nodes
      - wait.system3 -> wait.human at end are mandatory
    And at least one DOT example demonstrates the full cluster topology

    # Confidence scoring guide:
    # 1.0 — Full topology documented with all 6 node types, optional/mandatory clarified, DOT example
    # 0.5 — Partial topology (missing acceptance-test-writer or only showing end pair)
    # 0.0 — No topology rules documented

    # Red flags:
    # - Topology only shows "codergen -> wait.system3 -> wait.human" (missing start)
    # - acceptance-test-writer not mentioned
    # - Topology described as "recommended" rather than "mandatory"

  @feature-F1.4 @weight-0.02
  Scenario: S1.4 — Existing pipeline example updated with full cluster
    Given at least one pipeline DOT file exists in examples or pipelines directory
    When I examine the pipeline structure
    Then at least one epic cluster demonstrates the full topology
    And the wait.system3 node has a gate_type attribute
    And the wait.human node has a summary_ref attribute

    # Confidence scoring guide:
    # 1.0 — At least one real pipeline example demonstrates the full cluster pattern
    # 0.5 — Example exists but missing required attributes on gate nodes
    # 0.0 — No pipeline example updated

  @feature-F1.5 @weight-0.03
  Scenario: S1.5 — Executor clarification and requeue mechanism documented
    Given the node semantics documentation exists
    When I search for wait.system3 executor details
    Then the documentation clarifies:
      - wait.system3 is executed by the Python runner (PipelineRunner from E7.2)
      - For browser-based E2E tests, Chrome MCP tools are used
      - On failure, the runner can requeue predecessor codergen back to "pending"
      - Requeue has a retry counter with configurable max (default 2)
    And the requeue mechanism is described with state transition details

    # Confidence scoring guide:
    # 1.0 — Executor, Chrome MCP, requeue mechanism all documented with details
    # 0.5 — Executor mentioned but requeue or Chrome MCP missing
    # 0.0 — No executor clarification
