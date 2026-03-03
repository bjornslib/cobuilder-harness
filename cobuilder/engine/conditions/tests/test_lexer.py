"""Comprehensive unit tests for the condition expression lexer.

Covers all 18 token types, error paths, deprecation warnings, and
token immutability guarantees.
"""
from __future__ import annotations

import pytest

from cobuilder.engine.conditions.ast import ConditionLexError, Token, TokenType
from cobuilder.engine.conditions.lexer import ConditionLexer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def lex(source: str) -> list[Token]:
    """Tokenize *source* and drop the trailing EOF token."""
    tokens = ConditionLexer().tokenize(source)
    assert tokens[-1].type == TokenType.EOF, "Last token must be EOF"
    return tokens[:-1]


def lex_with_eof(source: str) -> list[Token]:
    """Tokenize *source* and retain the EOF token."""
    return ConditionLexer().tokenize(source)


# ---------------------------------------------------------------------------
# Basic token type coverage — one token at a time
# ---------------------------------------------------------------------------

class TestSingleTokens:
    def test_integer_positive(self):
        tokens = lex("42")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.INTEGER
        assert tokens[0].value == 42

    def test_integer_zero(self):
        tokens = lex("0")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.INTEGER
        assert tokens[0].value == 0

    def test_integer_negative(self):
        tokens = lex("-7")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.INTEGER
        assert tokens[0].value == -7

    def test_float_positive(self):
        tokens = lex("3.14")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == pytest.approx(3.14)

    def test_float_negative(self):
        tokens = lex("-0.5")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == pytest.approx(-0.5)

    def test_float_multi_digit(self):
        tokens = lex("100.99")
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == pytest.approx(100.99)

    def test_string_double_quoted(self):
        tokens = lex('"hello world"')
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello world"

    def test_string_single_quoted(self):
        tokens = lex("'hello world'")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello world"

    def test_string_empty_double(self):
        tokens = lex('""')
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == ""

    def test_string_empty_single(self):
        tokens = lex("''")
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == ""

    def test_boolean_true_lowercase(self):
        tokens = lex("true")
        assert tokens[0].type == TokenType.BOOLEAN
        assert tokens[0].value is True

    def test_boolean_true_uppercase(self):
        tokens = lex("TRUE")
        assert tokens[0].type == TokenType.BOOLEAN
        assert tokens[0].value is True

    def test_boolean_true_titlecase(self):
        tokens = lex("True")
        assert tokens[0].type == TokenType.BOOLEAN
        assert tokens[0].value is True

    def test_boolean_false_lowercase(self):
        tokens = lex("false")
        assert tokens[0].type == TokenType.BOOLEAN
        assert tokens[0].value is False

    def test_boolean_false_uppercase(self):
        tokens = lex("FALSE")
        assert tokens[0].type == TokenType.BOOLEAN
        assert tokens[0].value is False

    def test_boolean_false_titlecase(self):
        tokens = lex("False")
        assert tokens[0].type == TokenType.BOOLEAN
        assert tokens[0].value is False

    def test_variable_simple(self):
        tokens = lex("$retry_count")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.VARIABLE
        # Dollar sign is NOT in the value
        assert tokens[0].value == "retry_count"

    def test_variable_dotted(self):
        tokens = lex("$node_visits.impl_auth")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.VARIABLE
        assert tokens[0].value == "node_visits.impl_auth"

    def test_variable_underscore_start(self):
        tokens = lex("$_private")
        assert tokens[0].type == TokenType.VARIABLE
        assert tokens[0].value == "_private"

    def test_eq_operator(self):
        tokens = lex("=")
        assert tokens[0].type == TokenType.EQ
        assert tokens[0].value == "="

    def test_neq_operator(self):
        tokens = lex("!=")
        assert tokens[0].type == TokenType.NEQ
        assert tokens[0].value == "!="

    def test_lt_operator(self):
        tokens = lex("<")
        assert tokens[0].type == TokenType.LT
        assert tokens[0].value == "<"

    def test_gt_operator(self):
        tokens = lex(">")
        assert tokens[0].type == TokenType.GT
        assert tokens[0].value == ">"

    def test_lte_operator(self):
        tokens = lex("<=")
        assert tokens[0].type == TokenType.LTE
        assert tokens[0].value == "<="

    def test_gte_operator(self):
        tokens = lex(">=")
        assert tokens[0].type == TokenType.GTE
        assert tokens[0].value == ">="

    def test_and_operator(self):
        tokens = lex("&&")
        assert tokens[0].type == TokenType.AND
        assert tokens[0].value == "&&"

    def test_or_operator(self):
        tokens = lex("||")
        assert tokens[0].type == TokenType.OR
        assert tokens[0].value == "||"

    def test_not_operator(self):
        tokens = lex("!")
        assert tokens[0].type == TokenType.NOT
        assert tokens[0].value == "!"

    def test_lparen(self):
        tokens = lex("(")
        assert tokens[0].type == TokenType.LPAREN

    def test_rparen(self):
        tokens = lex(")")
        assert tokens[0].type == TokenType.RPAREN

    def test_eof_token_present(self):
        tokens = lex_with_eof("42")
        assert tokens[-1].type == TokenType.EOF
        assert tokens[-1].value is None


# ---------------------------------------------------------------------------
# BARE_WORD deprecation warning
# ---------------------------------------------------------------------------

class TestBareWord:
    def test_bare_word_produces_deprecation_warning(self):
        with pytest.warns(DeprecationWarning):
            tokens = lex("success")
        assert tokens[0].type == TokenType.BARE_WORD
        assert tokens[0].value == "success"

    def test_bare_word_deprecation_message_contains_word(self):
        with pytest.warns(DeprecationWarning, match="success"):
            lex("success")

    def test_bare_word_suggests_quoting(self):
        with pytest.warns(DeprecationWarning, match='"success"'):
            lex("success")

    def test_bare_word_does_not_match_boolean(self):
        # "true" must be BOOLEAN, not BARE_WORD — no DeprecationWarning
        with pytest.warns(DeprecationWarning) as record:
            tokens = lex("truevalue")
        # truevalue is a BARE_WORD (starts with 'true' but is longer)
        assert tokens[0].type == TokenType.BARE_WORD
        assert tokens[0].value == "truevalue"
        assert len(record) == 1


# ---------------------------------------------------------------------------
# Multi-token expressions
# ---------------------------------------------------------------------------

class TestMultiToken:
    def test_simple_comparison(self):
        tokens = lex("$retry_count < 3")
        assert [t.type for t in tokens] == [
            TokenType.VARIABLE,
            TokenType.LT,
            TokenType.INTEGER,
        ]
        assert tokens[0].value == "retry_count"
        assert tokens[2].value == 3

    def test_and_expression(self):
        tokens = lex("$a < 5 && $b > 0")
        types = [t.type for t in tokens]
        assert types == [
            TokenType.VARIABLE,
            TokenType.LT,
            TokenType.INTEGER,
            TokenType.AND,
            TokenType.VARIABLE,
            TokenType.GT,
            TokenType.INTEGER,
        ]

    def test_or_expression(self):
        tokens = lex("$a = 1 || $b = 2")
        assert TokenType.OR in [t.type for t in tokens]

    def test_not_expression(self):
        tokens = lex("!($status = failed)")
        assert tokens[0].type == TokenType.NOT
        assert tokens[1].type == TokenType.LPAREN

    def test_parenthesised_expression(self):
        tokens = lex("($a || $b) && $c")
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[-1].type == TokenType.VARIABLE

    def test_lte_in_expression(self):
        tokens = lex("$x <= 10")
        assert tokens[1].type == TokenType.LTE

    def test_gte_in_expression(self):
        tokens = lex("$x >= 10")
        assert tokens[1].type == TokenType.GTE

    def test_neq_in_expression(self):
        tokens = lex("$x != 10")
        assert tokens[1].type == TokenType.NEQ

    def test_whitespace_ignored_between_tokens(self):
        tokens_tight = lex("$a<3")
        tokens_spaced = lex("$a < 3")
        assert [t.type for t in tokens_tight] == [t.type for t in tokens_spaced]


# ---------------------------------------------------------------------------
# Position tracking
# ---------------------------------------------------------------------------

class TestPositions:
    def test_first_token_at_zero(self):
        tokens = lex("$x < 5")
        assert tokens[0].position == 0

    def test_operator_position_after_variable_and_space(self):
        # "$x" is 2 chars, then a space, then "<" at position 3
        tokens = lex("$x < 5")
        assert tokens[1].position == 3

    def test_integer_position(self):
        tokens = lex("$x < 5")
        assert tokens[2].position == 5

    def test_string_position(self):
        tokens = lex('$a = "hello"')
        # "$a" = pos 0, " " skip, "=" = pos 3, " " skip, '"hello"' = pos 5
        assert tokens[2].position == 5

    def test_eof_position_at_end(self):
        source = "$x"
        tokens = lex_with_eof(source)
        eof = tokens[-1]
        assert eof.position == len(source)


# ---------------------------------------------------------------------------
# Token immutability
# ---------------------------------------------------------------------------

class TestTokenImmutability:
    def test_token_is_frozen(self):
        token = Token(TokenType.INTEGER, 42, 0)
        with pytest.raises(AttributeError):
            token.value = 99  # type: ignore[misc]

    def test_token_type_is_frozen(self):
        token = Token(TokenType.STRING, "hello", 0)
        with pytest.raises(AttributeError):
            token.type = TokenType.BOOLEAN  # type: ignore[misc]

    def test_token_position_is_frozen(self):
        token = Token(TokenType.EOF, None, 10)
        with pytest.raises(AttributeError):
            token.position = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestLexErrors:
    def test_bare_ampersand_raises(self):
        with pytest.raises(ConditionLexError, match="&&"):
            ConditionLexer().tokenize("$a & $b")

    def test_bare_pipe_raises(self):
        with pytest.raises(ConditionLexError, match=r"\|\|"):
            ConditionLexer().tokenize("$a | $b")

    def test_unclosed_double_quote_raises(self):
        with pytest.raises(ConditionLexError, match="Unclosed string"):
            ConditionLexer().tokenize('"hello')

    def test_unclosed_single_quote_raises(self):
        with pytest.raises(ConditionLexError, match="Unclosed string"):
            ConditionLexer().tokenize("'world")

    def test_dollar_with_no_identifier_raises(self):
        with pytest.raises(ConditionLexError, match="Expected identifier after"):
            ConditionLexer().tokenize("$ ")

    def test_dollar_at_end_raises(self):
        with pytest.raises(ConditionLexError, match="Expected identifier after"):
            ConditionLexer().tokenize("$")

    def test_lex_error_contains_position(self):
        try:
            ConditionLexer().tokenize("$a & $b")
        except ConditionLexError as exc:
            assert exc.position >= 0
            assert exc.source == "$a & $b"
        else:
            pytest.fail("ConditionLexError not raised")

    def test_lex_error_str_contains_position(self):
        try:
            ConditionLexer().tokenize("$a & $b")
        except ConditionLexError as exc:
            assert "at position" in str(exc)

    def test_unexpected_character_raises(self):
        with pytest.raises(ConditionLexError, match="Unexpected character"):
            ConditionLexer().tokenize("$a @ $b")


# ---------------------------------------------------------------------------
# All 18 token types present in TokenType enum
# ---------------------------------------------------------------------------

class TestTokenTypeCompleteness:
    def test_eighteen_token_types(self):
        members = list(TokenType)
        assert len(members) == 18, (
            f"Expected 18 TokenType members, got {len(members)}: {members}"
        )

    def test_all_expected_names_present(self):
        names = {m.name for m in TokenType}
        expected = {
            "INTEGER", "FLOAT", "STRING", "BOOLEAN", "VARIABLE", "BARE_WORD",
            "EQ", "NEQ", "LT", "GT", "LTE", "GTE",
            "AND", "OR", "NOT", "LPAREN", "RPAREN", "EOF",
        }
        assert names == expected
