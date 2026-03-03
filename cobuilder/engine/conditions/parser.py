"""Condition expression parser.

Implements a recursive-descent parser that converts a token stream from
:class:`~cobuilder.engine.conditions.lexer.ConditionLexer` into a typed
AST rooted at an :data:`~cobuilder.engine.conditions.ast.ASTNode`.

Grammar (simplified, operator precedence low → high)
------------------------------------------------------
::

    expr       := or_expr
    or_expr    := and_expr ( '||' and_expr )*
    and_expr   := not_expr ( '&&' not_expr )*
    not_expr   := '!' atom | atom
    atom       := '(' expr ')' | comparison
    comparison := value operator value
    value      := VARIABLE | INTEGER | FLOAT | STRING | BOOLEAN | BARE_WORD
    operator   := '=' | '!=' | '<' | '>' | '<=' | '>='

Precedence (highest first): ``!``, comparison, ``&&``, ``||``.
"""
from __future__ import annotations

from cobuilder.engine.conditions.ast import (
    ASTNode,
    BinaryOpNode,
    ComparisonNode,
    ConditionParseError,
    LiteralNode,
    NotNode,
    Token,
    TokenType,
    ValueNode,
    VariableNode,
)
from cobuilder.engine.conditions.lexer import ConditionLexer

# Re-export as alias so existing code that imports ParseError from this module
# continues to work (backward compatibility with rules.py and similar callers).
ParseError = ConditionParseError

# Operator token types that can appear between two values in a comparison.
_COMPARISON_OPS: frozenset[TokenType] = frozenset(
    {
        TokenType.EQ,
        TokenType.NEQ,
        TokenType.LT,
        TokenType.GT,
        TokenType.LTE,
        TokenType.GTE,
    }
)

# Token types that are valid as literal values on either side of a comparison.
_LITERAL_TYPES: frozenset[TokenType] = frozenset(
    {
        TokenType.INTEGER,
        TokenType.FLOAT,
        TokenType.STRING,
        TokenType.BOOLEAN,
        TokenType.BARE_WORD,
    }
)


class ConditionParser:
    """Parses a condition expression string into an AST.

    Usage::

        parser = ConditionParser()
        ast = parser.parse("$retry_count < 3 && $status != 'failed'")

    The parser is **not** thread-safe for concurrent calls on the same
    instance; create a new instance per parse call if needed (or use the
    module-level :func:`~cobuilder.engine.conditions.parse_condition` helper).
    """

    # Instance state populated by :meth:`parse` before delegating to helpers.
    _tokens: list[Token]
    _pos: int
    _source: str

    def parse(self, source: str) -> ASTNode:
        """Parse *source* and return the root AST node.

        Args:
            source: The raw condition expression string.

        Returns:
            Root :data:`ASTNode` of the parsed expression tree.

        Raises:
            ConditionParseError: If the expression is syntactically invalid.
            ConditionLexError:   If the expression contains characters the
                                 lexer cannot tokenize.
        """
        lexer = ConditionLexer()
        self._tokens = lexer.tokenize(source)
        self._pos = 0
        self._source = source

        result = self._parse_or()

        # Ensure we consumed the entire token stream.
        tok = self._peek()
        if tok.type != TokenType.EOF:
            raise ConditionParseError(
                f"Unexpected token '{tok.value}' after expression",
                tok,
                source,
            )
        return result

    # ------------------------------------------------------------------
    # Token navigation helpers
    # ------------------------------------------------------------------

    def _peek(self) -> Token:
        """Return the current token without advancing."""
        return self._tokens[self._pos]

    def _consume(self, expected: TokenType | None = None) -> Token:
        """Advance past the current token and return it.

        Args:
            expected: If provided, raises :class:`ConditionParseError` when
                      the current token does not match *expected*.
        """
        tok = self._tokens[self._pos]
        if expected is not None and tok.type != expected:
            raise ConditionParseError(
                f"Expected {expected.name} but got '{tok.value}' ({tok.type.name})",
                tok,
                self._source,
            )
        self._pos += 1
        return tok

    # ------------------------------------------------------------------
    # Recursive-descent grammar rules
    # ------------------------------------------------------------------

    def _parse_or(self) -> ASTNode:
        """or_expr := and_expr ( '||' and_expr )*"""
        left = self._parse_and()
        while self._peek().type == TokenType.OR:
            self._consume(TokenType.OR)
            right = self._parse_and()
            left = BinaryOpNode(operator=TokenType.OR, left=left, right=right)
        return left

    def _parse_and(self) -> ASTNode:
        """and_expr := not_expr ( '&&' not_expr )*"""
        left = self._parse_not()
        while self._peek().type == TokenType.AND:
            self._consume(TokenType.AND)
            right = self._parse_not()
            left = BinaryOpNode(operator=TokenType.AND, left=left, right=right)
        return left

    def _parse_not(self) -> ASTNode:
        """not_expr := '!' atom | atom"""
        if self._peek().type == TokenType.NOT:
            self._consume(TokenType.NOT)
            operand = self._parse_atom()
            return NotNode(operand=operand)
        return self._parse_atom()

    def _parse_atom(self) -> ASTNode:
        """atom := '(' expr ')' | comparison"""
        if self._peek().type == TokenType.LPAREN:
            self._consume(TokenType.LPAREN)
            expr = self._parse_or()
            tok = self._peek()
            if tok.type != TokenType.RPAREN:
                raise ConditionParseError(
                    f"Expected ')' but got '{tok.value}'",
                    tok,
                    self._source,
                )
            self._consume(TokenType.RPAREN)
            return expr
        return self._parse_comparison()

    def _parse_comparison(self) -> ComparisonNode:
        """comparison := value operator value"""
        left = self._parse_value()

        op_tok = self._peek()
        if op_tok.type not in _COMPARISON_OPS:
            raise ConditionParseError(
                f"Expected operator after value but got '{op_tok.value}' "
                f"({op_tok.type.name}). "
                "Valid operators: =, !=, <, >, <=, >=",
                op_tok,
                self._source,
            )
        self._consume()  # consume operator token

        right = self._parse_value()
        return ComparisonNode(operator=op_tok.type, left=left, right=right)

    def _parse_value(self) -> ValueNode:
        """value := VARIABLE | INTEGER | FLOAT | STRING | BOOLEAN | BARE_WORD"""
        tok = self._peek()

        if tok.type == TokenType.VARIABLE:
            self._consume()
            # Split dotted path into tuple segments: "node_visits.impl_auth"
            # becomes ("node_visits", "impl_auth").
            path = tuple(tok.value.split('.'))  # type: ignore[arg-type]
            return VariableNode(path=path)

        if tok.type in _LITERAL_TYPES:
            self._consume()
            return LiteralNode(value=tok.value)  # type: ignore[arg-type]

        raise ConditionParseError(
            f"Expected a value (variable, literal, or bare word) but got "
            f"'{tok.value}' ({tok.type.name})",
            tok,
            self._source,
        )
