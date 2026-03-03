"""ConditionEvaluator — walks an ASTNode tree against PipelineContext.

AMD-4: Variables stored WITH $ prefix in context.
context["$retry_count"] = 2, context["$node_visits.impl_auth"] = 3

Short-circuit: AND stops on False, OR stops on True.
"""
from __future__ import annotations

import logging
from typing import Any, Union

from cobuilder.engine.conditions.ast import (
    ASTNode,
    ValueNode,
    VariableNode,
    LiteralNode,
    ComparisonNode,
    BinaryOpNode,
    NotNode,
    TokenType,
    ConditionEvalError,
    MissingVariableError,
    ConditionTypeError,
)

logger = logging.getLogger(__name__)

# Sentinel to distinguish "caller did not provide a default" from any real value.
_SENTINEL = object()


class ConditionEvaluator:
    """Evaluates an ASTNode tree against a PipelineContext (or dict).

    Usage::

        evaluator = ConditionEvaluator()
        result = evaluator.evaluate(ast_node, context)

    The evaluator is stateless — a single instance may be reused concurrently.
    """

    def evaluate(
        self,
        node: ASTNode,
        context: Any,
        *,
        missing_var_default: Any = _SENTINEL,
    ) -> bool:
        """Evaluate *node* against *context* and return a boolean result.

        Args:
            node:                Root AST node to evaluate.
            context:             PipelineContext or dict providing variable values.
            missing_var_default: If provided, missing variables return this value
                                 instead of raising :exc:`MissingVariableError`.
                                 Pass the module-level ``_SENTINEL`` (or omit the
                                 argument) to raise on missing variables.

        Returns:
            Boolean truth value of the condition.

        Raises:
            MissingVariableError: When a variable is absent and no default given.
            ConditionTypeError:   On unsupported type comparisons.
            ConditionEvalError:   For unexpected node types (should not occur in
                                  practice given a well-formed AST from the parser).
        """
        return self._eval(node, context, missing_var_default)

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------

    def _eval(self, node: ASTNode, context: Any, missing_var_default: Any) -> bool:
        if isinstance(node, LiteralNode):
            return bool(node.value)
        if isinstance(node, VariableNode):
            val = self._resolve_variable(node, context, missing_var_default)
            return bool(val)
        if isinstance(node, NotNode):
            return not self._eval(node.operand, context, missing_var_default)
        if isinstance(node, BinaryOpNode):
            return self._eval_binary(node, context, missing_var_default)
        if isinstance(node, ComparisonNode):
            return self._eval_comparison(node, context, missing_var_default)
        raise ConditionEvalError(f"Unknown node type: {type(node)}")

    # ------------------------------------------------------------------
    # Binary logical operators (AND / OR) with short-circuit evaluation
    # ------------------------------------------------------------------

    def _eval_binary(
        self,
        node: BinaryOpNode,
        context: Any,
        missing_var_default: Any,
    ) -> bool:
        if node.operator == TokenType.AND:
            left = self._eval(node.left, context, missing_var_default)
            if not left:
                return False  # short-circuit: skip right side
            return self._eval(node.right, context, missing_var_default)

        if node.operator == TokenType.OR:
            left = self._eval(node.left, context, missing_var_default)
            if left:
                return True  # short-circuit: skip right side
            return self._eval(node.right, context, missing_var_default)

        raise ConditionEvalError(f"Unknown binary operator: {node.operator}")

    # ------------------------------------------------------------------
    # Comparison evaluation
    # ------------------------------------------------------------------

    def _eval_comparison(
        self,
        node: ComparisonNode,
        context: Any,
        missing_var_default: Any,
    ) -> bool:
        left_val = self._resolve_value(node.left, context, missing_var_default)
        right_val = self._resolve_value(node.right, context, missing_var_default)
        left_coerced, right_coerced = self._coerce_for_comparison(
            left_val, right_val, node.operator
        )
        return self._apply_comparison(node.operator, left_coerced, right_coerced)

    # ------------------------------------------------------------------
    # Value resolution
    # ------------------------------------------------------------------

    def _resolve_value(
        self,
        node: ValueNode,
        context: Any,
        missing_var_default: Any,
    ) -> Any:
        if isinstance(node, VariableNode):
            return self._resolve_variable(node, context, missing_var_default)
        if isinstance(node, LiteralNode):
            return node.value
        raise ConditionEvalError(f"Unknown value node type: {type(node)}")

    def _resolve_variable(
        self,
        var: VariableNode,
        context: Any,
        missing_var_default: Any = _SENTINEL,
    ) -> Any:
        """Resolve a pipeline variable from context.

        AMD-4: Variables are stored WITH their ``$`` prefix in the context.

        Resolution strategy (tried in order):

        1. **Flat key with ``$`` prefix**: ``"$" + ".".join(var.path)``
           e.g. ``$node_visits.impl_auth`` → key ``"$node_visits.impl_auth"``

        2. **Nested dict lookup with ``$`` prefix on root segment**:
           ``context["$node_visits"]["impl_auth"]``

        3. **Flat key without ``$`` prefix** (backward-compat):
           ``".".join(var.path)``

        Args:
            var:                 The :class:`~cobuilder.engine.conditions.ast.VariableNode`.
            context:             PipelineContext or dict.
            missing_var_default: Sentinel or fallback value.

        Returns:
            Resolved Python value.

        Raises:
            MissingVariableError: When the variable is not found and no default.
        """
        # Obtain a snapshot for context-key listing (used in error messages).
        if hasattr(context, "snapshot"):
            snap: dict[str, Any] = context.snapshot()
        elif isinstance(context, dict):
            snap = context
        else:
            snap = {}

        # -- Strategy 1: flat key with $ prefix ---------------------------
        full_dollar_key = "$" + ".".join(var.path)
        if full_dollar_key in snap:
            return snap[full_dollar_key]

        # -- Strategy 2: nested dict with $ prefix on root segment --------
        if len(var.path) > 1:
            root_key = "$" + var.path[0]
            if root_key in snap:
                root_val = snap[root_key]
                if isinstance(root_val, dict):
                    current: Any = root_val
                    found = True
                    for segment in var.path[1:]:
                        if isinstance(current, dict) and segment in current:
                            current = current[segment]
                        else:
                            found = False
                            break
                    if found:
                        return current

        # -- Strategy 3: flat key without $ prefix (backward compat) ------
        no_dollar_key = ".".join(var.path)
        if no_dollar_key in snap:
            return snap[no_dollar_key]

        # -- Not found: apply missing-variable policy ---------------------
        if missing_var_default is _SENTINEL:
            raise MissingVariableError(var.path, list(snap.keys()))
        return missing_var_default

    # ------------------------------------------------------------------
    # Type coercion (SD §4.6)
    # ------------------------------------------------------------------

    def _coerce_for_comparison(
        self,
        left: Any,
        right: Any,
        op: TokenType,
    ) -> tuple[Any, Any]:
        """Apply type coercion rules before comparison.

        Rules (applied in order):

        * **bool + ordering operator** → :exc:`ConditionTypeError`
          (booleans only support ``=`` and ``!=``)
        * **int ↔ float** → promote int to float (with warning log)
        * **str ↔ number, equality** → attempt numeric parse of str
        * **str ↔ number, ordering** → attempt numeric parse of str
        * **str ↔ str** → no coercion (lexicographic comparison allowed)

        Args:
            left:  Left operand value.
            right: Right operand value.
            op:    Comparison operator token type.

        Returns:
            Pair ``(left_coerced, right_coerced)`` ready for comparison.

        Raises:
            ConditionTypeError: On unsupported type combinations.
        """
        ordering_ops = {TokenType.LT, TokenType.GT, TokenType.LTE, TokenType.GTE}
        equality_ops = {TokenType.EQ, TokenType.NEQ}

        # Bool + ordering → error
        if isinstance(left, bool) or isinstance(right, bool):
            if op in ordering_ops:
                raise ConditionTypeError(
                    f"Cannot apply ordering operator {op.name} to boolean value. "
                    "Booleans only support = and !=."
                )
            # Bool with = / != is fine; compare as-is
            return left, right

        # int ↔ float: promote int to float
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if type(left) is int and type(right) is float:
                logger.warning(
                    "Type coercion: int %s → float for comparison", left
                )
                return float(left), right
            if type(left) is float and type(right) is int:
                logger.warning(
                    "Type coercion: int %s → float for comparison", right
                )
                return left, float(right)
            return left, right

        # str ↔ number for equality: parse str as number
        if op in equality_ops:
            if isinstance(left, str) and isinstance(right, (int, float)):
                try:
                    coerced = float(left) if "." in left else int(left)
                    logger.warning(
                        "Type coercion: str '%s' → number for comparison", left
                    )
                    return coerced, right
                except (ValueError, TypeError):
                    raise ConditionTypeError(
                        f"Cannot compare string '{left}' with number {right}: "
                        f"'{left}' is not a valid number."
                    )
            if isinstance(right, str) and isinstance(left, (int, float)):
                try:
                    coerced = float(right) if "." in right else int(right)
                    logger.warning(
                        "Type coercion: str '%s' → number for comparison", right
                    )
                    return left, coerced
                except (ValueError, TypeError):
                    raise ConditionTypeError(
                        f"Cannot compare number {left} with string '{right}': "
                        f"'{right}' is not a valid number."
                    )

        # str ↔ number for ordering: parse str as number
        if op in ordering_ops:
            if isinstance(left, str) and isinstance(right, (int, float)):
                try:
                    coerced = float(left) if "." in left else int(left)
                    return coerced, right
                except (ValueError, TypeError):
                    raise ConditionTypeError(
                        f"Cannot compare string '{left}' with number {right} "
                        f"using {op.name}: '{left}' is not numeric."
                    )
            if isinstance(right, str) and isinstance(left, (int, float)):
                try:
                    coerced = float(right) if "." in right else int(right)
                    return left, coerced
                except (ValueError, TypeError):
                    raise ConditionTypeError(
                        f"Cannot compare number {left} with string '{right}' "
                        f"using {op.name}: '{right}' is not numeric."
                    )

        # str ↔ str or same types: no coercion needed
        return left, right

    # ------------------------------------------------------------------
    # Operator application
    # ------------------------------------------------------------------

    def _apply_comparison(self, op: TokenType, left: Any, right: Any) -> bool:
        """Apply a comparison operator to already-coerced values.

        Args:
            op:    Comparison operator token type.
            left:  Left operand (already type-coerced).
            right: Right operand (already type-coerced).

        Returns:
            Boolean result of the comparison.

        Raises:
            ConditionEvalError: For unknown operator types (programming error).
        """
        if op == TokenType.EQ:
            return left == right
        if op == TokenType.NEQ:
            return left != right
        if op == TokenType.LT:
            return left < right  # type: ignore[operator]
        if op == TokenType.GT:
            return left > right  # type: ignore[operator]
        if op == TokenType.LTE:
            return left <= right  # type: ignore[operator]
        if op == TokenType.GTE:
            return left >= right  # type: ignore[operator]
        raise ConditionEvalError(f"Unknown comparison operator: {op}")
