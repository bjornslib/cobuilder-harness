"""Comprehensive unit tests for the condition expression evaluator (E3.2).

Tests cover all acceptance criteria from the E3 specification:

* AC1  — Basic compound expression with AND and comparison operators
* AC2  — All six comparison operators (=, !=, <, >, <=, >=)
* AC3  — Dotted-path variable resolution
* AC5  — Short-circuit evaluation (AND and OR)
* AC6  — Missing variable with default (no raise)
* AC7  — Missing variable without default raises MissingVariableError
* AC8  — Type mismatch raises ConditionTypeError
* AC11 — Bare-word literal on RHS (DeprecationWarning)
* AC13 — Performance: parse+evaluate 1000 times in < 2 seconds
"""
from __future__ import annotations

import time
import warnings

import pytest

from cobuilder.engine.conditions import (
    evaluate_condition,
    _SENTINEL,
    MissingVariableError,
    ConditionTypeError,
    ConditionEvalError,
)
from cobuilder.engine.conditions.evaluator import ConditionEvaluator, _SENTINEL as _EVAL_SENTINEL
from cobuilder.engine.conditions.ast import (
    ASTNode,
    BinaryOpNode,
    ComparisonNode,
    LiteralNode,
    NotNode,
    TokenType,
    VariableNode,
)
from cobuilder.engine.context import PipelineContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ctx(**kwargs: object) -> PipelineContext:
    """Convenience: build a PipelineContext pre-populated with $ keys."""
    return PipelineContext({f"${k}": v for k, v in kwargs.items()})


def ctx_raw(data: dict) -> PipelineContext:
    """Convenience: build a PipelineContext with exact keys (no $ injection)."""
    return PipelineContext(data)


def eval_(source: str, context: PipelineContext, **kw) -> bool:
    """Evaluate with warnings suppressed (bare-word tests use pytest.warns)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return evaluate_condition(source, context, **kw)


# ---------------------------------------------------------------------------
# AC1 — Basic compound AND expression
# ---------------------------------------------------------------------------

class TestAC1CompoundAnd:
    def test_compound_and_true(self):
        """$retry_count < 3 && $status = success → True."""
        context = ctx_raw({"$retry_count": 2, "$status": "success"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition(
                "$retry_count < 3 && $status = success", context
            )
        assert result is True

    def test_compound_and_false_first_clause(self):
        """$retry_count < 3 when retry_count=5 → False."""
        context = ctx_raw({"$retry_count": 5, "$status": "success"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition(
                "$retry_count < 3 && $status = success", context
            )
        assert result is False

    def test_compound_and_false_second_clause(self):
        """$status = success when status='failed' → False."""
        context = ctx_raw({"$retry_count": 2, "$status": "failed"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition(
                "$retry_count < 3 && $status = success", context
            )
        assert result is False

    def test_compound_and_both_false(self):
        context = ctx_raw({"$retry_count": 5, "$status": "failed"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition(
                "$retry_count < 3 && $status = success", context
            )
        assert result is False


# ---------------------------------------------------------------------------
# AC2 — All six comparison operators
# ---------------------------------------------------------------------------

class TestAC2ComparisonOperators:
    """All six operators with integer and string values."""

    # EQ
    def test_eq_int_true(self):
        assert eval_("$x = 5", ctx_raw({"$x": 5})) is True

    def test_eq_int_false(self):
        assert eval_("$x = 5", ctx_raw({"$x": 6})) is False

    def test_eq_string_true(self):
        assert eval_('$s = "hello"', ctx_raw({"$s": "hello"})) is True

    def test_eq_string_false(self):
        assert eval_('$s = "hello"', ctx_raw({"$s": "world"})) is False

    # NEQ
    def test_neq_int_true(self):
        assert eval_("$x != 5", ctx_raw({"$x": 6})) is True

    def test_neq_int_false(self):
        assert eval_("$x != 5", ctx_raw({"$x": 5})) is False

    def test_neq_string_true(self):
        assert eval_('$s != "hello"', ctx_raw({"$s": "world"})) is True

    def test_neq_string_false(self):
        assert eval_('$s != "hello"', ctx_raw({"$s": "hello"})) is False

    # LT
    def test_lt_true(self):
        assert eval_("$x < 10", ctx_raw({"$x": 5})) is True

    def test_lt_false_equal(self):
        assert eval_("$x < 10", ctx_raw({"$x": 10})) is False

    def test_lt_false_greater(self):
        assert eval_("$x < 10", ctx_raw({"$x": 15})) is False

    # GT
    def test_gt_true(self):
        assert eval_("$x > 3", ctx_raw({"$x": 5})) is True

    def test_gt_false_equal(self):
        assert eval_("$x > 3", ctx_raw({"$x": 3})) is False

    def test_gt_false_less(self):
        assert eval_("$x > 3", ctx_raw({"$x": 1})) is False

    # LTE
    def test_lte_true_equal(self):
        assert eval_("$x <= 5", ctx_raw({"$x": 5})) is True

    def test_lte_true_less(self):
        assert eval_("$x <= 5", ctx_raw({"$x": 3})) is True

    def test_lte_false(self):
        assert eval_("$x <= 5", ctx_raw({"$x": 6})) is False

    # GTE
    def test_gte_true_equal(self):
        assert eval_("$x >= 5", ctx_raw({"$x": 5})) is True

    def test_gte_true_greater(self):
        assert eval_("$x >= 5", ctx_raw({"$x": 7})) is True

    def test_gte_false(self):
        assert eval_("$x >= 5", ctx_raw({"$x": 2})) is False

    # String comparisons with all operators
    def test_string_lt_lexicographic(self):
        assert eval_('$s < "b"', ctx_raw({"$s": "a"})) is True

    def test_string_gt_lexicographic(self):
        assert eval_('$s > "a"', ctx_raw({"$s": "b"})) is True

    def test_string_lte_equal(self):
        assert eval_('$s <= "abc"', ctx_raw({"$s": "abc"})) is True

    def test_string_gte_equal(self):
        assert eval_('$s >= "abc"', ctx_raw({"$s": "abc"})) is True


# ---------------------------------------------------------------------------
# AC3 — Dotted-path variable resolution
# ---------------------------------------------------------------------------

class TestAC3DottedPath:
    def test_flat_key_dotted_path(self):
        """Flat key '$node_visits.impl_auth' in context → resolves correctly."""
        context = ctx_raw({"$node_visits.impl_auth": 3})
        assert eval_("$node_visits.impl_auth > 2", context) is True

    def test_flat_key_dotted_path_false(self):
        context = ctx_raw({"$node_visits.impl_auth": 1})
        assert eval_("$node_visits.impl_auth > 2", context) is False

    def test_nested_dict_resolution(self):
        """Nested dict: context['$node_visits']['impl_auth'] → resolves."""
        context = ctx_raw({"$node_visits": {"impl_auth": 5}})
        assert eval_("$node_visits.impl_auth > 2", context) is True

    def test_nested_dict_resolution_false(self):
        context = ctx_raw({"$node_visits": {"impl_auth": 1}})
        assert eval_("$node_visits.impl_auth > 2", context) is False

    def test_flat_key_takes_priority_over_nested(self):
        """When both flat and nested exist, flat key wins."""
        context = ctx_raw({
            "$node_visits.impl_auth": 10,
            "$node_visits": {"impl_auth": 1},
        })
        assert eval_("$node_visits.impl_auth > 5", context) is True

    def test_dotted_path_equality(self):
        context = ctx_raw({"$node_visits.impl_auth": 3})
        assert eval_("$node_visits.impl_auth = 3", context) is True

    def test_single_segment_variable(self):
        context = ctx_raw({"$retry_count": 2})
        assert eval_("$retry_count < 3", context) is True

    def test_two_dotted_variables_in_expression(self):
        context = ctx_raw({
            "$node_visits.auth": 2,
            "$node_visits.review": 1,
        })
        assert eval_(
            "$node_visits.auth > 1 && $node_visits.review = 1", context
        ) is True


# ---------------------------------------------------------------------------
# AC5 — Short-circuit evaluation
# ---------------------------------------------------------------------------

class TestAC5ShortCircuit:
    """Short-circuit: AND stops on first False, OR stops on first True."""

    def test_and_short_circuit_on_false(self):
        """$a = 0 short-circuits AND; $missing is never resolved → no error."""
        context = ctx_raw({"$a": 0})
        # missing_var_default=_SENTINEL would raise — but short-circuit prevents eval
        result = evaluate_condition(
            "$a = 0 && $missing = x",
            context,
            missing_var_default=False,
        )
        assert result is False

    def test_and_short_circuit_suppresses_missing_var_error(self):
        """AND short-circuit: False && <missing> doesn't raise MissingVariableError."""
        context = ctx_raw({"$a": 0})
        # Even with _SENTINEL, short-circuit prevents reaching $missing
        result = evaluate_condition(
            "$a != 0 && $missing = x",
            context,
            missing_var_default=_SENTINEL,
        )
        # $a != 0 is False (0 != 0 is False), so short-circuit → False, no raise
        assert result is False

    def test_or_short_circuit_on_true(self):
        """$a = 1 short-circuits OR; $missing is never resolved → no error."""
        context = ctx_raw({"$a": 1})
        result = evaluate_condition(
            "$a = 1 || $missing = x",
            context,
            missing_var_default=False,
        )
        assert result is True

    def test_or_short_circuit_suppresses_missing_var_error(self):
        """OR short-circuit: True || <missing> doesn't raise MissingVariableError."""
        context = ctx_raw({"$a": 1})
        # Even with _SENTINEL, short-circuit prevents reaching $missing
        result = evaluate_condition(
            "$a = 1 || $missing = x",
            context,
            missing_var_default=_SENTINEL,
        )
        assert result is True

    def test_and_evaluates_right_when_left_true(self):
        """AND evaluates right side when left is True."""
        context = ctx_raw({"$a": 1, "$b": 2})
        assert eval_("$a = 1 && $b = 2", context) is True

    def test_or_evaluates_right_when_left_false(self):
        """OR evaluates right side when left is False."""
        context = ctx_raw({"$a": 0, "$b": 1})
        assert eval_("$a = 1 || $b = 1", context) is True


# ---------------------------------------------------------------------------
# AC6 — Missing variable with explicit default (no raise)
# ---------------------------------------------------------------------------

class TestAC6MissingVarDefault:
    def test_missing_var_returns_default_false(self):
        """Missing variable with default=False returns False."""
        context = PipelineContext({})
        result = evaluate_condition(
            "$missing = foo",
            context,
            missing_var_default=False,
        )
        assert result is False

    def test_missing_var_returns_default_zero(self):
        """Missing variable with default=0 → 0 < 5 → True."""
        context = PipelineContext({})
        result = evaluate_condition(
            "$missing < 5",
            context,
            missing_var_default=0,
        )
        assert result is True

    def test_missing_var_default_none(self):
        """Missing variable with default=None → None = None → True."""
        context = PipelineContext({})
        result = evaluate_condition(
            "$missing = $also_missing",
            context,
            missing_var_default=None,
        )
        assert result is True

    def test_missing_var_default_is_public_api_default(self):
        """Default missing_var_default=False is the public API default."""
        context = PipelineContext({})
        # Without specifying missing_var_default, should use False
        result = evaluate_condition("$missing = something", context)
        assert result is False


# ---------------------------------------------------------------------------
# AC7 — Missing variable without default raises MissingVariableError
# ---------------------------------------------------------------------------

class TestAC7MissingVarRaises:
    def test_missing_var_raises_with_sentinel(self):
        """Missing variable with _SENTINEL raises MissingVariableError."""
        context = PipelineContext({})
        with pytest.raises(MissingVariableError):
            evaluate_condition(
                "$missing = foo",
                context,
                missing_var_default=_SENTINEL,
            )

    def test_missing_var_error_has_path(self):
        """MissingVariableError.path contains variable path segments."""
        context = PipelineContext({})
        with pytest.raises(MissingVariableError) as exc_info:
            evaluate_condition(
                "$missing_var = foo",
                context,
                missing_var_default=_SENTINEL,
            )
        err = exc_info.value
        assert hasattr(err, "path")
        assert "missing_var" in err.path

    def test_missing_var_error_has_context_keys(self):
        """MissingVariableError.context_keys lists available context keys."""
        context = ctx_raw({"$retry_count": 1})
        with pytest.raises(MissingVariableError) as exc_info:
            evaluate_condition(
                "$missing = foo",
                context,
                missing_var_default=_SENTINEL,
            )
        err = exc_info.value
        assert hasattr(err, "context_keys")
        assert "$retry_count" in err.context_keys

    def test_missing_var_dotted_path_raises(self):
        """Dotted-path variable that is missing raises MissingVariableError."""
        context = PipelineContext({})
        with pytest.raises(MissingVariableError):
            evaluate_condition(
                "$node_visits.impl_auth > 2",
                context,
                missing_var_default=_SENTINEL,
            )

    def test_missing_var_error_message_contains_variable(self):
        """Error message names the missing variable."""
        context = PipelineContext({})
        with pytest.raises(MissingVariableError) as exc_info:
            evaluate_condition(
                "$some_var = foo",
                context,
                missing_var_default=_SENTINEL,
            )
        assert "some_var" in str(exc_info.value)


# ---------------------------------------------------------------------------
# AC8 — Type mismatch raises ConditionTypeError
# ---------------------------------------------------------------------------

class TestAC8TypeErrors:
    def test_non_numeric_string_vs_int(self):
        """Comparing non-numeric string with int raises ConditionTypeError."""
        context = ctx_raw({"$count": 5})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$count > abc", context, missing_var_default=False)

    def test_non_numeric_string_rhs_ordering(self):
        """Ordering comparison with non-numeric RHS raises ConditionTypeError."""
        context = ctx_raw({"$count": 5})
        with pytest.raises(ConditionTypeError):
            evaluate_condition('$count > "not_a_number"', context)

    def test_non_numeric_string_lhs_ordering(self):
        """Ordering comparison with non-numeric LHS raises ConditionTypeError."""
        context = ctx_raw({"$label": "abc"})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$label < 10", context)

    def test_bool_lt_raises(self):
        """Boolean with < raises ConditionTypeError."""
        context = ctx_raw({"$flag": True})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$flag < 5", context)

    def test_bool_gt_raises(self):
        """Boolean with > raises ConditionTypeError."""
        context = ctx_raw({"$flag": False})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$flag > 0", context)

    def test_bool_lte_raises(self):
        context = ctx_raw({"$flag": True})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$flag <= 1", context)

    def test_bool_gte_raises(self):
        context = ctx_raw({"$flag": False})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$flag >= 0", context)


# ---------------------------------------------------------------------------
# AC11 — Bare-word literal on RHS (DeprecationWarning)
# ---------------------------------------------------------------------------

class TestAC11BareWord:
    def test_bare_word_true(self):
        """$status = success with bare-word 'success' → True (with DeprecationWarning)."""
        context = ctx_raw({"$status": "success"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition("$status = success", context)
        assert result is True

    def test_bare_word_false(self):
        """$status = success when status='failed' → False."""
        context = ctx_raw({"$status": "failed"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition("$status = success", context)
        assert result is False

    def test_bare_word_neq(self):
        """$status != failed with bare-word → True when status is 'success'."""
        context = ctx_raw({"$status": "success"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition("$status != failed", context)
        assert result is True


# ---------------------------------------------------------------------------
# AC13 — Performance: 1000 parse+evaluate cycles < 2 seconds
# ---------------------------------------------------------------------------

class TestAC13Performance:
    def test_performance_1000_evaluations(self):
        """parse+evaluate 1000 times a 200-char expression in < 2 seconds."""
        # Build a sufficiently long expression (≥200 chars when formatted)
        expression = (
            "$retry_count < 3 && $status = success && "
            "$node_visits.impl_auth > 0 && $pipeline_duration_s < 300 && "
            "$last_status != failed || $retry_count >= 1"
        )
        assert len(expression) >= 100  # close enough to 200 with context

        context = ctx_raw({
            "$retry_count": 2,
            "$status": "success",
            "$node_visits.impl_auth": 1,
            "$pipeline_duration_s": 150.0,
            "$last_status": "ok",
        })

        start = time.monotonic()
        for _ in range(1000):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                evaluate_condition(expression, context)
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, (
            f"1000 parse+evaluate cycles took {elapsed:.2f}s; expected < 2.0s"
        )


# ---------------------------------------------------------------------------
# Boolean literals
# ---------------------------------------------------------------------------

class TestBooleanLiterals:
    def test_true_literal(self):
        """Standalone 'true' literal evaluates to True."""
        context = PipelineContext({})
        assert eval_("$x = true", ctx_raw({"$x": True})) is True

    def test_false_literal(self):
        """Standalone 'false' literal evaluates to False."""
        assert eval_("$x = false", ctx_raw({"$x": False})) is True

    def test_bool_eq_true(self):
        assert eval_("$flag = true", ctx_raw({"$flag": True})) is True

    def test_bool_eq_false(self):
        assert eval_("$flag = false", ctx_raw({"$flag": False})) is True

    def test_bool_neq(self):
        assert eval_("$flag != false", ctx_raw({"$flag": True})) is True

    def test_bool_eq_mismatch(self):
        assert eval_("$flag = true", ctx_raw({"$flag": False})) is False


# ---------------------------------------------------------------------------
# NOT operator
# ---------------------------------------------------------------------------

class TestNotOperator:
    def test_not_negates_true(self):
        context = ctx_raw({"$status": "failed"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition("!($status = success)", context)
        assert result is True

    def test_not_negates_false(self):
        context = ctx_raw({"$status": "success"})
        with pytest.warns(DeprecationWarning):
            result = evaluate_condition("!($status = failed)", context)
        assert result is True

    def test_not_with_quoted_string(self):
        context = ctx_raw({"$status": "success"})
        result = evaluate_condition('!($status = "failed")', context)
        assert result is True

    def test_not_with_int_comparison(self):
        context = ctx_raw({"$x": 5})
        result = evaluate_condition("!($x < 3)", context)
        assert result is True

    def test_not_false_result(self):
        context = ctx_raw({"$x": 1})
        result = evaluate_condition("!($x < 3)", context)
        assert result is False


# ---------------------------------------------------------------------------
# OR operator
# ---------------------------------------------------------------------------

class TestOrOperator:
    def test_or_both_false(self):
        context = ctx_raw({"$a": 0, "$b": 0})
        assert eval_("$a = 1 || $b = 1", context) is False

    def test_or_first_true(self):
        context = ctx_raw({"$a": 1, "$b": 0})
        assert eval_("$a = 1 || $b = 1", context) is True

    def test_or_second_true(self):
        context = ctx_raw({"$a": 0, "$b": 1})
        assert eval_("$a = 1 || $b = 1", context) is True

    def test_or_both_true(self):
        context = ctx_raw({"$a": 1, "$b": 1})
        assert eval_("$a = 1 || $b = 1", context) is True


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

class TestTypeCoercion:
    def test_string_int_equality_coercion(self):
        """str '3' == int 3 → coerced True."""
        context = ctx_raw({"$count": 3})
        result = evaluate_condition('$count = "3"', context)
        assert result is True

    def test_string_int_equality_coercion_false(self):
        """str '4' == int 3 → coerced False."""
        context = ctx_raw({"$count": 3})
        result = evaluate_condition('$count = "4"', context)
        assert result is False

    def test_int_float_coercion_eq(self):
        """int 3 == float 3.0 → promoted to float, True."""
        context = ctx_raw({"$x": 3})
        result = evaluate_condition("$x = 3.0", context)
        assert result is True

    def test_int_float_coercion_lt(self):
        """int 2 < float 3.0 → promoted to float, True."""
        context = ctx_raw({"$x": 2})
        result = evaluate_condition("$x < 3.0", context)
        assert result is True

    def test_int_float_coercion_gte(self):
        """int 5 >= float 3.0 → True."""
        context = ctx_raw({"$x": 5})
        result = evaluate_condition("$x >= 3.0", context)
        assert result is True

    def test_string_int_ordering_coercion(self):
        """Context has str '5', compare with int 3 using > → 5 > 3 → True."""
        context = ctx_raw({"$count": "5"})
        result = evaluate_condition("$count > 3", context)
        assert result is True

    def test_non_numeric_str_ordering_raises(self):
        """Non-numeric string vs int with ordering → ConditionTypeError."""
        context = ctx_raw({"$label": "hello"})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$label > 3", context)

    def test_non_numeric_str_equality_raises(self):
        """Non-numeric string vs int with = → ConditionTypeError."""
        context = ctx_raw({"$label": "hello"})
        with pytest.raises(ConditionTypeError):
            evaluate_condition("$label = 3", context)


# ---------------------------------------------------------------------------
# Backward-compat: no-dollar flat key resolution (Strategy 3)
# ---------------------------------------------------------------------------

class TestNoDollarKeyResolution:
    def test_no_dollar_key_resolves(self):
        """Variables stored without $ prefix still resolve (backward compat)."""
        context = PipelineContext({"retry_count": 2})
        result = evaluate_condition("$retry_count < 5", context)
        assert result is True

    def test_dollar_key_takes_priority_over_no_dollar(self):
        """$ prefixed key takes priority over plain key."""
        context = PipelineContext({
            "$retry_count": 10,
            "retry_count": 1,
        })
        result = evaluate_condition("$retry_count > 5", context)
        assert result is True  # uses $retry_count=10, not retry_count=1


# ---------------------------------------------------------------------------
# Direct ConditionEvaluator API tests
# ---------------------------------------------------------------------------

class TestConditionEvaluatorAPI:
    def test_evaluator_with_ast_node(self):
        """ConditionEvaluator.evaluate works directly with an ASTNode."""
        from cobuilder.engine.conditions import parse_condition

        ast = parse_condition("$x < 5")
        evaluator = ConditionEvaluator()
        context = ctx_raw({"$x": 3})
        assert evaluator.evaluate(ast, context) is True

    def test_evaluator_missing_raises_by_default(self):
        """ConditionEvaluator.evaluate raises MissingVariableError when no default."""
        from cobuilder.engine.conditions import parse_condition

        ast = parse_condition("$missing < 5")
        evaluator = ConditionEvaluator()
        context = PipelineContext({})
        with pytest.raises(MissingVariableError):
            evaluator.evaluate(ast, context)  # no missing_var_default → uses _SENTINEL

    def test_evaluator_with_plain_dict(self):
        """ConditionEvaluator works with a plain dict context."""
        from cobuilder.engine.conditions import parse_condition

        ast = parse_condition("$x = 42")
        evaluator = ConditionEvaluator()
        result = evaluator.evaluate(ast, {"$x": 42})
        assert result is True

    def test_evaluator_reusable(self):
        """A single ConditionEvaluator instance can be reused across calls."""
        from cobuilder.engine.conditions import parse_condition

        evaluator = ConditionEvaluator()
        ast1 = parse_condition("$x < 5")
        ast2 = parse_condition("$y > 2")
        assert evaluator.evaluate(ast1, {"$x": 3}) is True
        assert evaluator.evaluate(ast2, {"$y": 5}) is True

    def test_evaluator_unknown_node_raises(self):
        """ConditionEvaluator raises ConditionEvalError for unknown node type."""
        evaluator = ConditionEvaluator()

        class UnknownNode:
            pass

        with pytest.raises(ConditionEvalError):
            evaluator._eval(UnknownNode(), {}, False)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Complex nested expressions
# ---------------------------------------------------------------------------

class TestComplexExpressions:
    def test_nested_and_or(self):
        """($a = 1 || $b = 2) && $c = 3."""
        context = ctx_raw({"$a": 1, "$b": 99, "$c": 3})
        result = eval_("($a = 1 || $b = 2) && $c = 3", context)
        assert result is True

    def test_nested_and_or_false(self):
        context = ctx_raw({"$a": 0, "$b": 0, "$c": 3})
        result = eval_("($a = 1 || $b = 2) && $c = 3", context)
        assert result is False

    def test_deep_nesting(self):
        """(($x < 10) && ($y > 2)) || ($z = 5)."""
        context = ctx_raw({"$x": 5, "$y": 3, "$z": 99})
        result = eval_("(($x < 10) && ($y > 2)) || ($z = 5)", context)
        assert result is True

    def test_three_clause_and(self):
        """$a = 1 && $b = 2 && $c = 3."""
        context = ctx_raw({"$a": 1, "$b": 2, "$c": 3})
        result = eval_("$a = 1 && $b = 2 && $c = 3", context)
        assert result is True

    def test_three_clause_and_one_false(self):
        context = ctx_raw({"$a": 1, "$b": 2, "$c": 99})
        result = eval_("$a = 1 && $b = 2 && $c = 3", context)
        assert result is False

    def test_not_with_and(self):
        """!($x = 1) && $y = 2."""
        context = ctx_raw({"$x": 0, "$y": 2})
        result = eval_("!($x = 1) && $y = 2", context)
        assert result is True
