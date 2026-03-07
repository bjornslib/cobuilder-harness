@epic-E3 @sd-HARNESS-UPGRADE-001-E3
Feature: Workflow Protocol Enhancements

  # Epic 3 adds SD version pinning, concern queues, guardian reflection at gates,
  # session handoff, and living narrative to the guardian workflow.
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E3-workflow-protocols.md

  @feature-F3.1 @weight-0.04
  Scenario: S3.1 — SD version pinning protocol documented
    Given the guardian workflow documentation exists
    When I search for SD version pinning protocol
    Then the documentation describes:
      - Git tag naming convention: sd/{prd-id}/E{n}/v{version}
      - Tag created after refine node completes
      - Codergen node sd_ref attribute points to tag
      - dispatch_worker resolves tag to file content via git show
      - Signal evidence includes sd_hash (SHA256 of resolved content)
    And at least one example shows the full flow from tag creation to worker dispatch

    # Confidence scoring guide:
    # 1.0 — Full protocol with naming convention, flow, and example
    # 0.5 — Protocol described but missing naming convention or example
    # 0.0 — No SD version pinning documented

  @feature-F3.2 @weight-0.03
  Scenario: S3.2 — Concern queue JSONL schema documented
    Given the workflow documentation exists
    When I search for concern queue or concerns.jsonl
    Then the schema is documented:
      | Field    | Type   | Required | Description |
      | ts       | string | yes      | ISO 8601 timestamp |
      | node     | string | yes      | Node ID that raised the concern |
      | severity | enum   | yes      | critical, warning, info |
      | message  | string | yes      | Human-readable concern description |
      | suggestion | string | no    | Recommended action |
    And severity-based processing rules are defined:
      - critical: blocks gate, transitions to failed
      - warning: included in summary for human review
      - info: logged to Hindsight only

    # Confidence scoring guide:
    # 1.0 — Full JSONL schema + severity processing rules
    # 0.5 — Schema present but processing rules missing
    # 0.0 — No concern queue documentation

  @feature-F3.3 @weight-0.03
  Scenario: S3.3 — Guardian reflection at wait.system3 gates documented
    Given the workflow documentation exists
    When I search for guardian reflection or wait.system3 gate processing
    Then the documentation describes:
      - Read all signal files from completed codergen workers in the epic cluster
      - Read concerns.jsonl for worker-raised concerns
      - Reflect via Hindsight: query confidence trend, previous gate results, concern patterns
      - If critical concerns or declining confidence: write summary, transition to failed
      - Requeue mechanism: transition predecessor codergen back to "pending" for retry
      - If no blockers: proceed with Gherkin E2E test execution
      - After tests: write full summary to summary_ref
    And the documentation does NOT reference a sketch pre-flight (removed)

    # Confidence scoring guide:
    # 1.0 — Full reflection protocol with signals, concerns, Hindsight, requeue, E2E tests
    # 0.5 — Protocol partially documented (e.g., tests but no reflection or requeue)
    # 0.0 — No guardian reflection at gates documented

    # Red flags:
    # - Sketch pre-flight still referenced (should be removed)
    # - Reflection happens before dispatch instead of at gates
    # - No requeue mechanism on failure

  @feature-F3.4 @weight-0.02
  Scenario: S3.4 — Session handoff format documented
    Given the output style or workflow documentation exists
    When I search for session handoff
    Then the handoff document format includes:
      - Last Action (what was just completed)
      - Pipeline State (cobuilder pipeline status output)
      - Next Dispatchable Nodes
      - Open Concerns
      - Confidence Trend
    And the file path convention is: .claude/progress/{session-id}-handoff.md
    And startup behavior reads handoff before Hindsight queries

    # Confidence scoring guide:
    # 1.0 — Full format with all 5 sections, path convention, and startup behavior
    # 0.5 — Format partially documented, missing startup behavior
    # 0.0 — No session handoff documentation

  @feature-F3.5 @weight-0.02
  Scenario: S3.5 — Living narrative append protocol documented
    Given the workflow documentation exists
    When I search for living narrative
    Then the documentation describes:
      - File path convention: .claude/narrative/{initiative}.md
      - Append after each epic completion
      - Entry format includes: Epic N, title, date, outcome, key decisions, surprises, concerns resolved, time
    And the narrative is described as human-readable (not machine-parsed)

    # Confidence scoring guide:
    # 1.0 — Full protocol with path, trigger, entry format
    # 0.5 — Mentioned but entry format incomplete
    # 0.0 — No living narrative documentation
