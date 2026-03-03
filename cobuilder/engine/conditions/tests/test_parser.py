"""Comprehensive unit tests for the condition expression parser.

Covers AST construction, operator precedence, parenthesis grouping,
error handling, and backward-compatibility aliases.
"""
from __future__ import annotations

import pytest

from cobuilder.engine.conditions.ast import (
    ASTNode,
    BinaryOpNode,
    ComparisonNode,
    ConditionParseError,
    LiteralNode,
    NotNode,
    TokenType,
    VariableNode,
)
from cobuilder.engine.conditions.parser import ConditionParser, ParseError
from cobuilder.engine.conditions import parse_condition, validate_condition_syntax


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse(source: str) -> ASTNode:
    """Convenience wrapper around :class:`ConditionParser`."""
    return ConditionParser().parse(source)


# ---------------------------------------------------------------------------
# Simple comparisons
# ---------------------------------------------------------------------------

class TestSimpleComparisons:
    def test_integer_lt(self):
        ast = parse("$retry_count < 3")
        assert isinstance(ast, ComparisonNode)
        assert ast.operator == TokenType.LT
        assert isinstance(ast.left, VariableNode)
        assert ast.left.path == ("retry_count",)
        assert isinstance(ast.right, LiteralNode)
        assert ast.right.value == 3

    def test_integer_gt(self):
        ast = parse("$visits > 0")
        assert isinstance(ast, ComparisonNode)
        assert ast.operator == TokenType.GT
        assert ast.right.value == 0  # type: ignore[union-attr]

    def test_integer_lte(self):
        ast = parse("$x <= 10")
        assert isinstance(ast, ComparisonNode)
        assert ast.operator == TokenType.LTE

    def test_integer_gte(self):
        ast = parse("$x >= 10")
        assert isinstance(ast, ComparisonNode)
        assert ast.operator == TokenType.GTE

    def test_eq_string(self):
        ast = parse('$status = "done"')
        assert isinstance(ast, ComparisonNode)
        assert ast.operator == TokenType.EQ
        assert isinstance(ast.right, LiteralNode)
        assert ast.right.value == "done"

    def test_neq_string(self):
        ast = parse('$status != "failed"')
        assert isinstance(ast, ComparisonNode)
        assert ast.operator == TokenType.NEQ

    def test_float_comparison(self):
        ast = parse("$score >= 0.75")
        assert isinstance(ast, ComparisonNode)
        assert ast.operator == TokenType.GTE
        assert isinstance(ast.right, LiteralNode)
        assert ast.right.value == pytest.approx(0.75)

    def test_boolean_rhs(self):
        ast = parse("$enabled = true")
        assert isinstance(ast, ComparisonNode)
        assert isinstance(ast.right, LiteralNode)
        assert ast.right.value is True

    def test_negative_integer_rhs(self):
        ast = parse("$delta < -5")
        assert isinstance(ast, ComparisonNode)
        assert ast.right.value == -5  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Dotted variable paths
# ---------------------------------------------------------------------------

class TestDottedVariables:
    def test_two_segment_path(self):
        ast = parse("$node_visits.impl_auth > 2")
        assert isinstance(ast, ComparisonNode)
        assert isinstance(ast.left, VariableNode)
        assert ast.left.path == ("node_visits", "impl_auth")

    def test_three_segment_path(self):
        ast = parse("$a.b.c = 1")
        assert isinstance(ast, ComparisonNode)
        left = ast.left
        assert isinstance(left, VariableNode)
        assert left.path == ("a", "b", "c")

    def test_single_segment_path(self):
        ast = parse("$x = 1")
        assert isinstance(ast.left, VariableNode)
        assert ast.left.path == ("x",)


# ---------------------------------------------------------------------------
# Bare word on RHS (deprecated, still parses as LiteralNode)
# ---------------------------------------------------------------------------

class TestBareWord:
    def test_bare_word_parsed_as_literal(self):
        with pytest.warns(DeprecationWarning):
            ast = parse("$status = success")
        assert isinstance(ast, ComparisonNode)
        assert isinstance(ast.right, LiteralNode)
        assert ast.right.value == "success"

    def test_bare_word_value_preserved(self):
        with pytest.warns(DeprecationWarning):
            ast = parse("$phase = review")
        assert ast.right.value == "review"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Logical operators and precedence
# ---------------------------------------------------------------------------

class TestPrecedence:
    def test_and_before_or(self):
        # "$a < 5 || $b = done && $c > 1"
        # Should parse as: OR(Cmp(a<5), AND(Cmp(b=done), Cmp(c>1)))
        with pytest.warns(DeprecationWarning):
            ast = parse("$a < 5 || $b = done && $c > 1")

        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == TokenType.OR

        # Left of OR: $a < 5
        left = ast.left
        assert isinstance(left, ComparisonNode)
        assert isinstance(left.left, VariableNode)
        assert left.left.path == ("a",)
        assert left.operator == TokenType.LT

        # Right of OR: AND($b = done, $c > 1)
        right = ast.right
        assert isinstance(right, BinaryOpNode)
        assert right.operator == TokenType.AND

        and_left = right.left
        assert isinstance(and_left, ComparisonNode)
        assert isinstance(and_left.left, VariableNode)
        assert and_left.left.path == ("b",)

        and_right = right.right
        assert isinstance(and_right, ComparisonNode)
        assert isinstance(and_right.left, VariableNode)
        assert and_right.left.path == ("c",)

    def test_and_left_associative(self):
        ast = parse("$a < 1 && $b < 2 && $c < 3")
        # Should be AND(AND(a<1, b<2), c<3)
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == TokenType.AND
        assert isinstance(ast.left, BinaryOpNode)
        assert ast.left.operator == TokenType.AND

    def test_or_left_associative(self):
        ast = parse("$a < 1 || $b < 2 || $c < 3")
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == TokenType.OR
        assert isinstance(ast.left, BinaryOpNode)
        assert ast.left.operator == TokenType.OR

    def test_two_ands_grouped(self):
        ast = parse("$a = 1 && $b = 2")
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == TokenType.AND


# ---------------------------------------------------------------------------
# NOT operator
# ---------------------------------------------------------------------------

class TestNotOperator:
    def test_not_with_parentheses(self):
        with pytest.warns(DeprecationWarning):
            ast = parse("!($status = failed)")
        assert isinstance(ast, NotNode)
        inner = ast.operand
        assert isinstance(inner, ComparisonNode)
        assert isinstance(inner.left, VariableNode)
        assert inner.left.path == ("status",)

    def test_not_with_quoted_string(self):
        ast = parse('!($status = "failed")')
        assert isinstance(ast, NotNode)
        assert isinstance(ast.operand, ComparisonNode)

    def test_not_with_simple_comparison(self):
        ast = parse("!($x < 5)")
        assert isinstance(ast, NotNode)
        assert isinstance(ast.operand, ComparisonNode)


# ---------------------------------------------------------------------------
# Parenthesis grouping overrides precedence
# ---------------------------------------------------------------------------

class TestParentheses:
    def test_parens_override_and_or(self):
        # "($a || $b) && $c" should be AND(OR(a,b), c)
        ast = parse("($a < 1 || $b < 2) && $c < 3")
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == TokenType.AND

        # Left of AND: OR(a<1, b<2)
        left = ast.left
        assert isinstance(left, BinaryOpNode)
        assert left.operator == TokenType.OR

        # Right of AND: c<3
        right = ast.right
        assert isinstance(right, ComparisonNode)
        assert isinstance(right.left, VariableNode)
        assert right.left.path == ("c",)

    def test_nested_parens(self):
        ast = parse("(($a < 1))")
        assert isinstance(ast, ComparisonNode)

    def test_parens_on_rhs(self):
        ast = parse("$a < 1 && ($b < 2 || $c < 3)")
        assert isinstance(ast, BinaryOpNode)
        assert ast.operator == TokenType.AND
        rhs = ast.right
        assert isinstance(rhs, BinaryOpNode)
        assert rhs.operator == TokenType.OR


# ---------------------------------------------------------------------------
# ParseError alias backward compatibility
# ---------------------------------------------------------------------------

class TestParseErrorAlias:
    def test_parseerror_is_alias(self):
        assert ParseError is ConditionParseError

    def test_parseerror_raised_on_invalid(self):
        with pytest.raises(ParseError):
            parse("$x >> 5")

    def test_parseerror_is_subclass_of_condition_parse_error(self):
        # Since ParseError IS ConditionParseError, catching either works.
        with pytest.raises(ConditionParseError):
            parse(">> invalid")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestParseErrors:
    def test_invalid_double_operator_raises(self):
        with pytest.raises(ConditionParseError) as exc_info:
            parse("$x >> 5")
        # The error should contain position information.
        err = exc_info.value
        assert hasattr(err, "token")
        assert err.token.position >= 0

    def test_missing_rhs_raises(self):
        with pytest.raises(ConditionParseError):
            parse("$x <")

    def test_missing_lhs_raises(self):
        with pytest.raises(ConditionParseError):
            parse("< 5")

    def test_unclosed_paren_raises(self):
        with pytest.raises(ConditionParseError, match=r"Expected '\)'"):
            parse("($x < 5")

    def test_trailing_garbage_raises(self):
        with pytest.raises(ConditionParseError, match="Unexpected token"):
            parse("$x < 5 $y")

    def test_error_has_source(self):
        source = "$x >> 5"
        try:
            parse(source)
        except ConditionParseError as exc:
            assert exc.source == source
        else:
            pytest.fail("ConditionParseError not raised")

    def test_error_message_contains_operator_info(self):
        try:
            parse("$x >> 5")
        except ConditionParseError as exc:
            assert "operator" in str(exc).lower() or ">>" in str(exc)
        else:
            pytest.fail("ConditionParseError not raised")

    def test_empty_expression_raises(self):
        with pytest.raises(ConditionParseError):
            parse("")

    def test_only_operator_raises(self):
        with pytest.raises(ConditionParseError):
            parse("&&")


# ---------------------------------------------------------------------------
# Module-level helpers (parse_condition, validate_condition_syntax)
# ---------------------------------------------------------------------------

class TestModuleLevelHelpers:
    def test_parse_condition_returns_ast(self):
        ast = parse_condition("$x < 5")
        assert isinstance(ast, ComparisonNode)

    def test_validate_condition_syntax_valid(self):
        errors, warnings = validate_condition_syntax("$x < 5")
        assert errors == []
        assert warnings == []

    def test_validate_condition_syntax_invalid(self):
        errors, warnings = validate_condition_syntax("$x >>")
        assert len(errors) > 0
        assert isinstance(errors[0], str)

    def test_validate_condition_syntax_returns_tuple_of_lists(self):
        result = validate_condition_syntax("$x < 5")
        assert isinstance(result, tuple)
        assert len(result) == 2
        errors, warnings = result
        assert isinstance(errors, list)
        assert isinstance(warnings, list)


# ---------------------------------------------------------------------------
# AST node immutability
# ---------------------------------------------------------------------------

class TestASTImmutability:
    def test_comparison_node_frozen(self):
        ast = parse("$x < 5")
        assert isinstance(ast, ComparisonNode)
        with pytest.raises(AttributeError):
            ast.operator = TokenType.GT  # type: ignore[misc]

    def test_variable_node_frozen(self):
        node = VariableNode(path=("x",))
        with pytest.raises(AttributeError):
            node.path = ("y",)  # type: ignore[misc]

    def test_literal_node_frozen(self):
        node = LiteralNode(value=42)
        with pytest.raises(AttributeError):
            node.value = 99  # type: ignore[misc]

    def test_binary_op_node_frozen(self):
        ast = parse("$a < 1 && $b < 2")
        assert isinstance(ast, BinaryOpNode)
        with pytest.raises(AttributeError):
            ast.operator = TokenType.OR  # type: ignore[misc]

    def test_not_node_frozen(self):
        ast = parse("!($x < 5)")
        assert isinstance(ast, NotNode)
        inner = ast.operand
        with pytest.raises(AttributeError):
            ast.operand = inner  # type: ignore[misc]
