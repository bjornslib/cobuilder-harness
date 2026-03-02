# PRD-PIPELINE-ENGINE-001 Epic 3+5: Condition Expression Language + Loop Detection
# Blind acceptance rubric — generated from SD-PIPELINE-ENGINE-001-epic3-5-conditions-loops.md
# Guardian: Do NOT share this file with orchestrators or workers.

@feature-F9 @weight-0.15
Feature: F9 — Condition Expression Lexer and Parser

  Scenario: S9.1 — Lexer tokenises condition expressions correctly
    Given condition strings with variables, operators, literals, and parentheses
    When Lexer.tokenise(expr) is called
    Then it produces a list of Token objects with correct type and value
    And $-prefixed variables produce VARIABLE tokens
    And quoted strings produce STRING tokens
    And bare unquoted words produce BARE_WORD tokens with deprecation warning (AMD-5)
    And comparison operators (=, !=, <, >, <=, >=) produce correct tokens

    # Confidence scoring guide:
    # 1.0 — Lexer handles all 18 token types including BARE_WORD (AMD-5). Produces
    #        DeprecationWarning for bare words. Whitespace skipped. LexError on
    #        invalid characters with position info.
    # 0.5 — Basic tokenisation works but missing BARE_WORD support or no deprecation warning.
    # 0.0 — No lexer exists or uses regex splitting instead of character-by-character scanning.

    # Evidence to check:
    # - cobuilder/engine/conditions/lexer.py — Lexer class with tokenise() method
    # - Token dataclass with type (TokenType enum) and value fields
    # - 18 token types in TokenType enum
    # - DeprecationWarning for BARE_WORD tokens (AMD-5)

    # Red flags:
    # - Using str.split() or simple regex instead of character scanning
    # - Missing position tracking in tokens
    # - No BARE_WORD token type (AMD-5 violation)

  Scenario: S9.2 — Parser produces correct AST from condition expressions
    Given condition expressions with variables, comparisons, AND, OR, NOT, parentheses
    When parse_condition(expr) is called
    Then it returns an AST with correct node types
    And "$retry_count < 3" produces ComparisonNode(VariableNode, LT, LiteralNode(3))
    And "$status = success AND $retry_count < 3" produces BinaryOpNode(AND, ...)
    And "NOT $failed" produces NotNode(VariableNode)
    And "($a OR $b) AND $c" respects parenthesis grouping
    And operator precedence is: NOT > AND > OR

    # Confidence scoring guide:
    # 1.0 — Recursive-descent parser with correct precedence. All 5 AST node types
    #        (VariableNode, LiteralNode, ComparisonNode, BinaryOpNode, NotNode) present.
    #        ConditionParseError on malformed input with position and snippet.
    # 0.5 — Parser works for simple expressions but fails on nested or complex ones.
    # 0.0 — No parser or uses eval() / string matching.

    # Evidence to check:
    # - cobuilder/engine/conditions/parser.py — recursive-descent parser
    # - cobuilder/engine/conditions/ast.py — 5 AST node types
    # - BNF grammar: expr := or_expr, or_expr := and_expr (OR and_expr)*
    # - cobuilder/engine/tests/test_conditions.py — parser tests

    # Red flags:
    # - Using Python's ast module or eval()
    # - Flat if/elif matching instead of recursive descent
    # - Missing NOT operator support
    # - Wrong precedence (OR before AND)


@feature-F10 @weight-0.10
Feature: F10 — Condition Evaluator

  Scenario: S10.1 — Evaluator resolves conditions against PipelineContext
    Given a PipelineContext with $retry_count=2, $status="success", $last_node="nodeA"
    When evaluate_condition("$retry_count < 3 AND $status = success", context) is called
    Then it returns True
    And evaluate_condition("$retry_count >= 3", context) returns False
    And evaluate_condition("$missing_var = foo", context) raises MissingVariableError

    # Confidence scoring guide:
    # 1.0 — Evaluator walks AST, resolves variables from context, applies type coercion
    #        at comparison boundaries. MissingVariableError for undefined variables.
    #        Short-circuit evaluation for AND (False short-circuits) and OR (True short-circuits).
    # 0.5 — Basic evaluation works but no type coercion or no short-circuit.
    # 0.0 — Evaluator doesn't exist or evaluates by string matching.

    # Evidence to check:
    # - cobuilder/engine/conditions/evaluator.py — Evaluator class or evaluate_condition()
    # - Type coercion: "3" compared with 3 should work (string-to-int coercion)
    # - Short-circuit tests: AND stops on first False, OR stops on first True
    # - MissingVariableError raised when variable not in context

    # Red flags:
    # - Using Python eval() to evaluate conditions
    # - No type coercion (strict type matching fails on string/int comparisons)
    # - Variables resolved without $ prefix convention (AMD-4)

  Scenario: S10.2 — validate_condition_syntax() for Rule 7 integration
    Given condition expression strings (valid and invalid)
    When validate_condition_syntax(expr) is called
    Then valid expressions return None (no error)
    And invalid expressions return a ConditionParseError with position info
    And this function is used by Epic 2's Rule 7 (ConditionSyntaxValid)

    # Confidence scoring guide:
    # 1.0 — Public API function exists, returns None or error object (not raise).
    #        Used by validation Rule 7. Tests cover valid and invalid expressions.
    # 0.5 — Function exists but raises instead of returning error objects.
    # 0.0 — No syntax validation function; Rule 7 does its own parsing.

    # Evidence to check:
    # - cobuilder/engine/conditions/__init__.py — validate_condition_syntax export
    # - cobuilder/engine/validation/rules.py — Rule 7 imports from conditions module


@feature-F11 @weight-0.05
Feature: F11 — Condition Error Hierarchy

  Scenario: S11.1 — Error classes with proper hierarchy and context
    Given the conditions error module
    Then ConditionError is the base exception
    And ConditionLexError, ConditionParseError, ConditionEvalError inherit from it
    And MissingVariableError and ConditionTypeError inherit from ConditionEvalError
    And all errors include position, expression snippet, and descriptive message

    # Confidence scoring guide:
    # 1.0 — Full hierarchy as specified. All errors carry position and expression context.
    # 0.5 — Hierarchy exists but errors lack position or snippet context.
    # 0.0 — Using generic exceptions (ValueError, RuntimeError) instead.

    # Evidence to check:
    # - cobuilder/engine/conditions/errors.py or exceptions.py
    # - Verify inheritance chain


@feature-F12 @weight-0.15
Feature: F12 — Loop Detection and Retry Policy

  Scenario: S12.1 — LoopDetector tracks visits and detects loops
    Given a LoopDetector with default policy (per_node_max=4, pipeline_max=50)
    When record_visit(node_id) is called 5 times for the same node
    Then the 5th call returns LoopDetectionResult with is_loop=True
    And result.violation_type is "per_node_exceeded"
    And result.visit_count is 5
    And result.max_allowed is 4

    # Confidence scoring guide:
    # 1.0 — LoopDetector class with record_visit(), per-node and pipeline-wide counters.
    #        LoopDetectionResult includes is_loop, violation_type, visit_count, max_allowed.
    #        VisitRecord tracks node_id, timestamp, attempt_number.
    #        AMD-6 compliant: NO repeating subsequence pattern detection.
    # 0.5 — Detection works but missing pipeline-wide counter or VisitRecord.
    # 0.0 — No loop detection or using pattern-based detection (AMD-6 violation).

    # Evidence to check:
    # - cobuilder/engine/loop_detection.py — LoopDetector class
    # - VisitRecord, LoopDetectionResult, LoopPolicy dataclasses
    # - Verify NO repeating subsequence detection (AMD-6)
    # - Per-node default: 4 visits (3 retries + 1 original)
    # - Pipeline-wide default: 50 total node executions

    # Red flags:
    # - Repeating subsequence detection code (AMD-6 violation)
    # - Pattern matching on execution history
    # - Missing pipeline-wide execution counter
    # - visit_count stored as retry_count (wrong semantics — visits are 1-indexed)

  Scenario: S12.2 — Policy resolution: node overrides graph defaults
    Given a node with max_retries=2 and graph default_max_retry=50
    When LoopDetector resolves the policy for that node
    Then per_node_max is 3 (max_retries + 1 for original visit)
    And pipeline_max is 50 (from graph attribute)

    # Confidence scoring guide:
    # 1.0 — Node-level max_retries overrides per_node_max. Graph-level default_max_retry
    #        sets pipeline_max. Convention: $retry_count is 0-indexed, $node_visits is 1-indexed.
    # 0.5 — Override works but indexing convention is wrong.
    # 0.0 — No policy resolution; hardcoded defaults only.

    # Evidence to check:
    # - LoopPolicy dataclass with per_node_max and pipeline_max fields
    # - Policy resolution logic in LoopDetector.__init__ or resolve_policy method

  Scenario: S12.3 — Escalation protocol on loop detection
    Given a loop detection result with is_loop=True
    When EngineRunner processes the result
    Then it emits a loop.detected event via the event bus
    And writes ORCHESTRATOR_STUCK signal via signal_protocol
    And checks allow_partial policy flag
    And raises LoopDetectedError if allow_partial is False

    # Confidence scoring guide:
    # 1.0 — Full escalation chain: event → signal → policy check → error.
    #        LoopDetectedError includes the LoopDetectionResult.
    #        allow_partial=True skips the error and continues to next edge.
    # 0.5 — Raises error but doesn't emit event or write signal.
    # 0.0 — No escalation protocol; loop detection result is ignored.

    # Evidence to check:
    # - cobuilder/engine/runner.py — loop detection handling in main loop
    # - LoopDetectedError in exceptions module
    # - Integration with EventEmitter (loop.detected event type)
    # - Integration with signal_protocol (ORCHESTRATOR_STUCK signal)

  Scenario: S12.4 — Visit records survive checkpoint and restart
    Given a checkpoint with visit records for 3 nodes
    When EngineRunner.run(resume=True) loads the checkpoint
    Then LoopDetector is initialized with the saved visit records
    And visit counts continue from where they left off
    And loop_restart edges reset only the target node's visit count

    # Confidence scoring guide:
    # 1.0 — Visit records serialized in EngineCheckpoint. LoopDetector accepts initial
    #        visit records in constructor. loop_restart edge type clears target node count.
    # 0.5 — Visit records saved but not restored on resume.
    # 0.0 — Visit records not part of checkpoint model.

    # Evidence to check:
    # - cobuilder/engine/checkpoint.py — visit_records field in EngineCheckpoint
    # - LoopDetector constructor accepts existing records
    # - loop_restart edge handling in EdgeSelector or EngineRunner
