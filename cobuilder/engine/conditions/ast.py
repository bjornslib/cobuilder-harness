"""AST node definitions, token types, and error hierarchy for condition expressions.

This module defines the complete data model for the condition expression
sub-language used in pipeline edge labels.  Everything is immutable
(frozen dataclasses) for safe sharing across threads and evaluation passes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


# ---------------------------------------------------------------------------
# Token types
# ---------------------------------------------------------------------------

class TokenType(Enum):
    """All token types produced by :class:`~cobuilder.engine.conditions.lexer.ConditionLexer`."""
    INTEGER    = auto()
    FLOAT      = auto()
    STRING     = auto()
    BOOLEAN    = auto()
    VARIABLE   = auto()   # $ prefix consumed; value is path string WITHOUT $
    BARE_WORD  = auto()   # unquoted identifier on RHS
    EQ         = auto()
    NEQ        = auto()
    LT         = auto()
    GT         = auto()
    LTE        = auto()
    GTE        = auto()
    AND        = auto()
    OR         = auto()
    NOT        = auto()
    LPAREN     = auto()
    RPAREN     = auto()
    EOF        = auto()


# ---------------------------------------------------------------------------
# Token dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Token:
    """A single lexical token with its type, value, and byte offset."""
    type: TokenType
    value: str | int | float | bool | None
    position: int  # byte offset in original expression string


# ---------------------------------------------------------------------------
# AST node dataclasses — all frozen=True for immutability
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VariableNode:
    """A pipeline context variable referenced with a ``$`` prefix.

    The ``path`` tuple represents dot-separated segments, e.g.
    ``$node_visits.impl_auth`` becomes ``("node_visits", "impl_auth")``.
    """
    path: tuple[str, ...]


@dataclass(frozen=True)
class LiteralNode:
    """A scalar literal value: string, integer, float, or boolean."""
    value: str | int | float | bool


@dataclass(frozen=True)
class ComparisonNode:
    """A binary comparison between two values.

    ``operator`` must be one of: EQ, NEQ, LT, GT, LTE, GTE.
    """
    operator: TokenType  # EQ | NEQ | LT | GT | LTE | GTE
    left: "ValueNode"
    right: "ValueNode"


@dataclass(frozen=True)
class BinaryOpNode:
    """A logical binary operation: AND or OR."""
    operator: TokenType  # AND | OR
    left: "ASTNode"
    right: "ASTNode"


@dataclass(frozen=True)
class NotNode:
    """Logical negation of an expression."""
    operand: "ASTNode"


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

#: A node that can appear on either side of a comparison operator.
ValueNode = Union[VariableNode, LiteralNode]

#: Any node that can appear at the top level of an expression tree.
ASTNode = Union[ComparisonNode, BinaryOpNode, NotNode, LiteralNode]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class ConditionError(Exception):
    """Base class for all condition expression errors."""


class ConditionLexError(ConditionError):
    """Raised when the lexer encounters an unexpected character or sequence.

    Attributes:
        message:  Human-readable description of the problem.
        position: Byte offset in the source string where the error occurred.
        source:   The full source string being tokenized.
    """

    def __init__(self, message: str, position: int, source: str) -> None:
        self.message = message
        self.position = position
        self.source = source
        super().__init__(f"{message} at position {position}: {source!r}")


class ConditionParseError(ConditionError):
    """Raised when the parser encounters an unexpected token.

    Attributes:
        message:  Human-readable description of the problem.
        token:    The token at which parsing failed.
        source:   The full source string being parsed.
    """

    def __init__(self, message: str, token: Token, source: str) -> None:
        self.message = message
        self.token = token
        self.source = source
        super().__init__(
            f"{message} (token at position {token.position}): {source!r}"
        )


class ConditionEvalError(ConditionError):
    """Base class for errors that occur during expression evaluation."""


class MissingVariableError(ConditionEvalError):
    """A required context variable was not found during evaluation.

    Attributes:
        path:         Tuple of path segments for the missing variable.
        context_keys: Top-level keys available in the evaluation context.
    """

    def __init__(self, path: tuple[str, ...], context_keys: list[str]) -> None:
        self.path = path
        self.context_keys = context_keys
        super().__init__(
            f"Variable '${'.'.join(path)}' not found in context. "
            f"Available keys: {context_keys}"
        )


class ConditionTypeError(ConditionEvalError):
    """A type mismatch was encountered during expression evaluation."""
