"""Condition expression lexer.

Converts a condition expression string into a flat list of
:class:`~cobuilder.engine.conditions.ast.Token` objects.

Supported syntax elements
--------------------------
- Variable references: ``$name``, ``$dotted.path``
- Quoted strings: ``"hello"`` or ``'world'``
- Boolean literals: ``true``, ``True``, ``TRUE``, ``false``, ``False``, ``FALSE``
- Integer literals: ``42``, ``-7``
- Float literals: ``3.14``, ``-0.5``
- Operators: ``=``, ``!=``, ``<``, ``>``, ``<=``, ``>=``
- Logical operators: ``&&``, ``||``, ``!``
- Grouping: ``(``, ``)``
- Bare words (deprecated): any unquoted non-keyword identifier on the RHS;
  emits a :class:`DeprecationWarning` and produces a BARE_WORD token.
"""
from __future__ import annotations

import warnings

from cobuilder.engine.conditions.ast import ConditionLexError, Token, TokenType


# Simple labels that are valid as standalone conditions (no comparison operator needed).
# These are used for decision routing in DOT pipelines (e.g., condition="pass").
_SIMPLE_LABELS: frozenset[str] = frozenset(
    {"pass", "fail", "partial", "success", "error"}
)


class ConditionLexer:
    """Tokenizes a condition expression string.

    Call :meth:`tokenize` with the raw source string.  The returned list
    always ends with an EOF token.
    """

    def tokenize(self, source: str) -> list[Token]:
        """Convert *source* into a list of :class:`Token` objects.

        Args:
            source: The raw condition expression string.

        Returns:
            Ordered list of tokens; the final token always has type
            :attr:`~TokenType.EOF`.

        Raises:
            ConditionLexError: On any unexpected character or malformed token.
        """
        tokens: list[Token] = []
        pos = 0
        n = len(source)

        while pos < n:
            # Skip whitespace
            if source[pos].isspace():
                pos += 1
                continue

            start = pos
            ch = source[pos]

            # ------------------------------------------------------------------
            # Variable: $ prefix
            # ------------------------------------------------------------------
            if ch == '$':
                pos += 1
                if pos >= n or not (source[pos].isalpha() or source[pos] == '_'):
                    raise ConditionLexError(
                        "Expected identifier after '$'", start, source
                    )
                var_start = pos
                while pos < n and (source[pos].isalnum() or source[pos] in ('_', '.')):
                    pos += 1
                var_name = source[var_start:pos]
                tokens.append(Token(TokenType.VARIABLE, var_name, start))
                continue

            # ------------------------------------------------------------------
            # String literals — single or double quoted
            # ------------------------------------------------------------------
            if ch in ('"', "'"):
                quote = ch
                pos += 1
                str_start = pos
                while pos < n and source[pos] != quote:
                    pos += 1
                if pos >= n:
                    raise ConditionLexError(
                        f"Unclosed string literal starting with {quote}",
                        start,
                        source,
                    )
                value = source[str_start:pos]
                pos += 1  # consume closing quote
                tokens.append(Token(TokenType.STRING, value, start))
                continue

            # ------------------------------------------------------------------
            # Two-character operators: &&, ||, <=, >=, !=
            # ------------------------------------------------------------------
            if pos + 1 < n:
                two = source[pos : pos + 2]
                if two == '&&':
                    tokens.append(Token(TokenType.AND, '&&', pos))
                    pos += 2
                    continue
                if two == '||':
                    tokens.append(Token(TokenType.OR, '||', pos))
                    pos += 2
                    continue
                if two == '<=':
                    tokens.append(Token(TokenType.LTE, '<=', pos))
                    pos += 2
                    continue
                if two == '>=':
                    tokens.append(Token(TokenType.GTE, '>=', pos))
                    pos += 2
                    continue
                if two == '!=':
                    tokens.append(Token(TokenType.NEQ, '!=', pos))
                    pos += 2
                    continue

            # ------------------------------------------------------------------
            # Single-character operators
            # ------------------------------------------------------------------
            if ch == '=':
                tokens.append(Token(TokenType.EQ, '=', pos))
                pos += 1
                continue
            if ch == '<':
                tokens.append(Token(TokenType.LT, '<', pos))
                pos += 1
                continue
            if ch == '>':
                tokens.append(Token(TokenType.GT, '>', pos))
                pos += 1
                continue
            if ch == '!':
                # bare ! → NOT (!=  already handled above as two-char)
                tokens.append(Token(TokenType.NOT, '!', pos))
                pos += 1
                continue
            if ch == '&':
                raise ConditionLexError(
                    "Bare '&' is invalid; use '&&' for logical AND", pos, source
                )
            if ch == '|':
                raise ConditionLexError(
                    "Bare '|' is invalid; use '||' for logical OR", pos, source
                )
            if ch == '(':
                tokens.append(Token(TokenType.LPAREN, '(', pos))
                pos += 1
                continue
            if ch == ')':
                tokens.append(Token(TokenType.RPAREN, ')', pos))
                pos += 1
                continue

            # ------------------------------------------------------------------
            # Numeric literals: optional leading minus, digits, optional decimal
            # ------------------------------------------------------------------
            if ch == '-' or ch.isdigit():
                num_start = pos
                if ch == '-':
                    pos += 1
                while pos < n and source[pos].isdigit():
                    pos += 1
                # Check for decimal float
                if (
                    pos < n
                    and source[pos] == '.'
                    and pos + 1 < n
                    and source[pos + 1].isdigit()
                ):
                    pos += 1  # consume '.'
                    while pos < n and source[pos].isdigit():
                        pos += 1
                    tokens.append(
                        Token(TokenType.FLOAT, float(source[num_start:pos]), num_start)
                    )
                else:
                    tokens.append(
                        Token(TokenType.INTEGER, int(source[num_start:pos]), num_start)
                    )
                continue

            # ------------------------------------------------------------------
            # Identifiers: true/false keywords, or BARE_WORD (deprecated)
            # ------------------------------------------------------------------
            if ch.isalpha() or ch == '_':
                word_start = pos
                while pos < n and (source[pos].isalnum() or source[pos] == '_'):
                    pos += 1
                word = source[word_start:pos]
                if word.lower() == 'true':
                    tokens.append(Token(TokenType.BOOLEAN, True, word_start))
                elif word.lower() == 'false':
                    tokens.append(Token(TokenType.BOOLEAN, False, word_start))
                else:
                    # Simple labels (pass, fail, etc.) are valid for decision routing
                    # and do not trigger deprecation warnings.
                    if word not in _SIMPLE_LABELS:
                        warnings.warn(
                            f"Deprecation: unquoted string '{word}' in condition "
                            f'expression. Use "{word}" for clarity.',
                            DeprecationWarning,
                            stacklevel=2,
                        )
                    tokens.append(Token(TokenType.BARE_WORD, word, word_start))
                continue

            # ------------------------------------------------------------------
            # Unexpected character
            # ------------------------------------------------------------------
            raise ConditionLexError(
                f"Unexpected character '{ch}'", pos, source
            )

        tokens.append(Token(TokenType.EOF, None, pos))
        return tokens
