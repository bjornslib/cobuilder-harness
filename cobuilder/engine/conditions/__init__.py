"""Condition expression sub-package for the pipeline execution engine.

Public API
----------
- :func:`parse_condition`        — Parse a condition string into an AST.
- :func:`validate_condition_syntax` — Validate syntax and return error strings.
- :func:`evaluate_condition`     — Evaluate a condition against a context
                                   (implemented in E3.2).

Error classes
-------------
- :class:`ConditionError`
- :class:`ConditionLexError`
- :class:`ConditionParseError`
- :class:`ConditionEvalError`
- :class:`MissingVariableError`
- :class:`ConditionTypeError`
"""
from __future__ import annotations

from typing import Any

from cobuilder.engine.conditions.ast import (
    ASTNode,
    ConditionError,
    ConditionEvalError,
    ConditionLexError,
    ConditionParseError,
    ConditionTypeError,
    MissingVariableError,
)
from cobuilder.engine.conditions.parser import ConditionParser

# Sentinel object used internally to distinguish "not provided" from None/False.
_SENTINEL = object()


def parse_condition(source: str) -> ASTNode:
    """Parse a condition expression string into an AST.

    Args:
        source: A condition expression such as ``"$retry_count < 3"``.

    Returns:
        Root :data:`~cobuilder.engine.conditions.ast.ASTNode` of the
        parsed expression tree.

    Raises:
        ConditionLexError:   If the source contains unrecognised characters.
        ConditionParseError: If the source is syntactically invalid.
    """
    return ConditionParser().parse(source)


def validate_condition_syntax(source: str) -> tuple[list[str], list[str]]:
    """Validate the syntax of a condition expression.

    Args:
        source: A condition expression string to validate.

    Returns:
        A two-tuple ``(errors, warnings)`` where each element is a list of
        human-readable strings.  Both lists are empty when the expression is
        fully valid.  ``errors`` being non-empty indicates a parse failure;
        ``warnings`` being non-empty indicates deprecated but accepted syntax
        (e.g. bare-word string literals, AMD-5).
    """
    import warnings as _warnings_mod

    try:
        with _warnings_mod.catch_warnings(record=True) as caught:
            _warnings_mod.simplefilter("always")
            parse_condition(source)
        warning_msgs = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
        return [], warning_msgs
    except ConditionParseError as exc:
        return [str(exc)], []
    except Exception as exc:  # ConditionLexError or unexpected errors
        return [str(exc)], []


def evaluate_condition(
    source: str,
    context: Any,
    *,
    missing_var_default: Any = False,
) -> bool:
    """Evaluate a condition expression against a context dictionary.

    Args:
        source:              The condition expression string to evaluate.
        context:             A :class:`~cobuilder.engine.context.PipelineContext`
                             or plain ``dict`` providing variable values
                             accessible via ``$variable_name`` references.
        missing_var_default: Value to return when a referenced variable is
                             absent from *context* and no explicit error is
                             desired.  Defaults to ``False``.

                             Pass the module-level :data:`_SENTINEL` to raise
                             :exc:`MissingVariableError` instead of silently
                             returning a default.

    Returns:
        Boolean result of evaluating the condition.

    Raises:
        ConditionLexError:    If the source contains unrecognised characters.
        ConditionParseError:  If the source is syntactically invalid.
        MissingVariableError: If a referenced variable is not in context and
                              *missing_var_default* is :data:`_SENTINEL`.
        ConditionTypeError:   If incompatible types are compared.
    """
    from cobuilder.engine.conditions.evaluator import (
        ConditionEvaluator,
        _SENTINEL as _EVAL_SENTINEL,
    )

    ast_node = parse_condition(source)

    # Map the public _SENTINEL to the evaluator's internal _SENTINEL so that
    # callers can trigger MissingVariableError via the public API.
    if missing_var_default is _SENTINEL:
        eval_default = _EVAL_SENTINEL
    else:
        eval_default = missing_var_default

    return ConditionEvaluator().evaluate(
        ast_node,
        context,
        missing_var_default=eval_default,
    )


__all__ = [
    "parse_condition",
    "evaluate_condition",
    "validate_condition_syntax",
    "ConditionParser",
    "ConditionError",
    "ConditionLexError",
    "ConditionParseError",
    "ConditionEvalError",
    "MissingVariableError",
    "ConditionTypeError",
    "_SENTINEL",
]
