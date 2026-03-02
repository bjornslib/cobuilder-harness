# PRD-PIPELINE-ENGINE-001 Epic 2: Pre-Execution Validation Suite
# Blind acceptance rubric — generated from SD-PIPELINE-ENGINE-001-epic2-validation.md
# Guardian: Do NOT share this file with orchestrators or workers.

@feature-F7 @weight-0.20
Feature: F7 — 13-Rule Validation Suite

  Scenario: S7.1 — Validator executes all 13 rules and produces ValidationResult
    Given a Validator class with all 13 rules registered
    When validator.run(graph) is called on a valid graph
    Then it returns a ValidationResult with is_valid=True and zero violations
    And each rule's rule_id appears in the execution log

    # Confidence scoring guide:
    # 1.0 — All 13 rules implemented. Validator.run() returns ValidationResult with
    #        violations list, is_valid property, and by_severity() grouping method.
    #        run_or_raise() raises ValidationError with embedded result on ERROR violations.
    # 0.5 — Most rules exist but some are stubs. ValidationResult exists but missing
    #        helper methods (by_severity, by_rule, summary).
    # 0.0 — Validator doesn't exist or fewer than 7 rules implemented.

    # Evidence to check:
    # - cobuilder/engine/validation/validator.py — Validator class
    # - cobuilder/engine/validation/rules.py — all 13 rule implementations
    # - cobuilder/engine/validation/models.py — RuleViolation, ValidationResult, Severity
    # - cobuilder/engine/tests/test_validation.py — tests per rule

    # Red flags:
    # - Rules that always return empty violations (no-op stubs)
    # - Missing run_or_raise() method
    # - Severity enum missing ERROR or WARNING level
    # - Rules not following the Rule protocol (rule_id, severity, check method)

  Scenario: S7.2 — ERROR-level rules block execution
    Given a DOT graph with no start node (violates Rule 1: SingleStartNode)
    When validator.run_or_raise(graph) is called
    Then it raises ValidationError
    And the error contains a RuleViolation with rule_id="R01" and severity=ERROR

    # Confidence scoring guide:
    # 1.0 — run_or_raise raises ValidationError with embedded ValidationResult.
    #        ERROR violations block, WARNING violations are collected but don't block.
    # 0.5 — Raises an exception but without structured ValidationResult.
    # 0.0 — No distinction between ERROR and WARNING severity.

    # Evidence to check:
    # - cobuilder/engine/validation/validator.py — run_or_raise method
    # - cobuilder/engine/validation/models.py — ValidationError with result attribute
    # - Test that ERROR violations cause raise, WARNING violations don't

  Scenario: S7.3 — Rules 1-9 (ERROR level) all implemented correctly
    Given test graphs that individually violate each of Rules 1-9
    When each rule's check(graph) is called
    Then Rule 1 (SingleStartNode) detects missing or multiple Mdiamond nodes
    And Rule 2 (AtLeastOneExit) detects missing Msquare nodes
    And Rule 3 (AllNodesReachable) detects unreachable nodes via BFS from start
    And Rule 4 (EdgeTargetsExist) detects edges pointing to non-existent nodes
    And Rule 5 (StartNoIncoming) detects edges targeting the start node
    And Rule 6 (ExitNoOutgoing) detects edges from exit nodes
    And Rule 7 (ConditionSyntaxValid) detects malformed edge condition expressions
    And Rule 8 (StylesheetSyntaxValid) passes with permissive stub (out of scope)
    And Rule 9 (RetryTargetsExist) detects retry edges pointing to non-existent nodes

    # Confidence scoring guide:
    # 1.0 — All 9 rules produce correct RuleViolation objects with meaningful messages.
    #        Rule 3 uses BFS/DFS traversal. Rule 7 delegates to condition parser (Epic 3).
    #        Rule 8 is a permissive stub that always passes.
    # 0.5 — Most rules work but Rule 3 (reachability) or Rule 7 (conditions) is stubbed.
    # 0.0 — Fewer than 5 of 9 ERROR-level rules implemented.

    # Evidence to check:
    # - cobuilder/engine/validation/rules.py — each rule class
    # - Look for BFS/DFS in Rule 3 (AllNodesReachable)
    # - Rule 7 should import from cobuilder.engine.conditions
    # - Rule 8 should be explicitly marked as stub/permissive

    # Red flags:
    # - Rule 3 that only checks direct edges (not full reachability)
    # - Rule 7 that doesn't use the condition parser from Epic 3
    # - Missing node_id in RuleViolation (violations must reference specific nodes/edges)

  Scenario: S7.4 — Rules 10-13 (WARNING level) all implemented correctly
    Given test graphs that individually trigger each of Rules 10-13
    When each rule's check(graph) is called
    Then Rule 10 (NodeTypesKnown) warns about unrecognised shape values
    And Rule 11 (FidelityValuesValid) warns about fidelity not in {full,mock,skip}
    And Rule 12 (GoalGatesHaveRetry) warns about exit nodes without retry edges
    And Rule 13 (LlmNodesHavePrompts) warns about codergen nodes missing prompt attribute

    # Confidence scoring guide:
    # 1.0 — All 4 WARNING rules produce violations with severity=WARNING.
    #        Rule 10 validates against the 9 known shape types.
    #        Rule 11 checks the fidelity attribute value set.
    #        Rule 12 checks exit (Msquare) nodes have at least one incoming retry edge.
    #        Rule 13 checks box nodes have a prompt or solution_design attribute.
    # 0.5 — Rules exist but produce ERROR instead of WARNING severity.
    # 0.0 — Fewer than 2 of 4 WARNING-level rules implemented.

    # Evidence to check:
    # - cobuilder/engine/validation/rules.py — Rules 10-13 with severity=WARNING
    # - Verify WARNING violations don't block in run_or_raise()

  Scenario: S7.5 — CLI validate subcommand invokes validator
    Given a DOT file with known violations
    When "cobuilder pipeline validate <file>" is run
    Then it prints a summary of violations grouped by severity
    And exits with code 1 if any ERROR violations exist
    And exits with code 0 if only WARNING violations exist

    # Confidence scoring guide:
    # 1.0 — CLI validate command exists, outputs structured summary, correct exit codes.
    # 0.5 — Command exists but output is unstructured or exit codes are wrong.
    # 0.0 — No CLI validate command or it doesn't invoke the Validator.

    # Evidence to check:
    # - cobuilder/cli.py — pipeline validate subcommand
    # - Integration between CLI and Validator.run()


@feature-F8 @weight-0.05
Feature: F8 — Validation Data Models

  Scenario: S8.1 — RuleViolation and ValidationResult models
    Given the validation models module
    Then RuleViolation is a frozen dataclass with rule_id, severity, message, node_id, edge_id
    And ValidationResult has violations list, is_valid property, by_severity(), by_rule(), summary()
    And Severity enum has ERROR and WARNING values
    And ValidationError is an Exception subclass with a result attribute

    # Confidence scoring guide:
    # 1.0 — All 4 models correct with frozen dataclasses, proper typing, helper methods.
    # 0.5 — Models exist but missing frozen or helper methods.
    # 0.0 — Using plain dicts instead of dataclasses.

    # Evidence to check:
    # - cobuilder/engine/validation/models.py — all model definitions
    # - Verify frozen=True on RuleViolation
