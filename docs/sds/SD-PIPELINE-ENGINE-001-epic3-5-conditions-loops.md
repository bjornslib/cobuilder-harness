---
title: "SD-PIPELINE-ENGINE-001: Condition Expression Language and Loop Detection"
status: active
type: reference
last_verified: 2026-03-04
grade: authoritative
implementation_status: complete
---
# SD-PIPELINE-ENGINE-001: Condition Expression Language (Epic 3) and Loop Detection & Retry Policy (Epic 5)

> **Implementation Status**: COMPLETE (2026-03-04)
>
> **Epic 3 — Condition Expression Language**:
> - **Code**: 1,117 LOC in `cobuilder/engine/conditions/` (lexer.py, parser.py, evaluator.py, ast_nodes.py)
> - **Tests**: 89 tests (86 passing, 3 failures)
> - **Features**: Hand-rolled lexer, recursive-descent parser, typed AST, evaluator with `PipelineContext` integration
> - **Known Issues**: 3 test failures at E3-E1 integration boundary — condition priority ordering in edge selector when multiple conditional edges exist. Core E3 condition logic is fully correct.
>
> **Epic 5 — Loop Detection & Retry Policy**:
> - **Code**: 323 LOC in `cobuilder/engine/loop_detection.py`
> - **Tests**: 42 tests, all passing
> - **Features**: Visit-counter tracking, per-node `max_retries` enforcement, `LoopDetectedError` exception, integration with `runner.py`

**Solution Design Document**
**PRD Reference**: PRD-PIPELINE-ENGINE-001, Sections 6 and 8
**Author**: Solution Architect
**Date**: 2026-02-28

---

## 1. Executive Summary

This solution design covers two tightly coupled subsystems of the Pipeline Execution Engine:

- **Epic 3 — Condition Expression Language**: A hand-rolled lexer, recursive-descent parser, AST, and evaluator that translates DOT edge `condition` attribute strings (e.g., `$retry_count < 3 && $status = success`) into boolean decisions at runtime. These decisions are the first step of the 5-step edge selection algorithm, making this subsystem the critical path of every conditional routing decision in the engine.

- **Epic 5 — Loop Detection and Retry Policy**: A visit-counter and pattern-detection subsystem that tracks how many times each node has been executed in the current run, detects repeating node subsequences, enforces per-node and pipeline-wide limits, and escalates to System 3 via the existing signal protocol when limits are exceeded.

The two epics are combined in one SD because they share pipeline context as a runtime dependency: condition expressions read `$node_visits.<node_id>` from the same context store where the loop detector writes, and both subsystems are consulted on every node execution cycle. Designing them together prevents redundant context-access patterns and ensures a single, consistent visit-count authority.

The implementation is greenfield code in `cobuilder/engine/conditions/` and `cobuilder/engine/loop_detection.py`, integrating at two fixed points: `edge_selector.py` (condition evaluation) and `runner.py` (loop check before edge selection).

---

## 2. Business Context and Motivation

The DOT pipeline files driving our multi-agent workflows currently rely on System 3 reading edge labels and manually deciding which branch to follow. This is the gap between Level 3 (manual coordination) and Level 4 (spec-driven autonomous execution) described in PRD-PIPELINE-ENGINE-001.

Two specific failures motivate these epics:

**Dynamic Routing Failure**: Pipelines with diamond (`diamond`) conditional nodes have edge conditions like `outcome=success && context.tests=passed`. Without a programmatic evaluator, the engine cannot traverse these nodes autonomously. Every conditional branch requires human or meta-orchestrator intervention.

**Infinite Loop Failure**: Production observations show orchestrators that fail a goal gate can re-enter a retry cycle indefinitely when the retry target leads back to failing work. Without visit-count enforcement, a single misconfigured pipeline can consume unbounded tokens and wall-clock time.

Both failures block the G3 and G5 goals from PRD-PIPELINE-ENGINE-001. This SD provides the implementation blueprint to close those gaps.

---

## 3. Technical Architecture

### 3.1 Subsystem Map and Integration Points

```
cobuilder/engine/
├── runner.py                    ← integration point A: calls loop_detector before edge selection
├── edge_selector.py             ← integration point B: calls condition evaluator in step 1
├── context.py                   ← shared runtime store for both subsystems
├── checkpoint.py                ← persists visit_counts from loop_detection
│
├── conditions/                  ← Epic 3 (NEW)
│   ├── __init__.py
│   ├── lexer.py                 ← tokenizes raw condition string → list[Token]
│   ├── parser.py                ← recursive-descent: list[Token] → ASTNode
│   ├── ast.py                   ← dataclass definitions for all AST node types
│   └── evaluator.py             ← walks AST against PipelineContext → bool
│
└── loop_detection.py            ← Epic 5 (NEW)
```

### 3.2 Data Flow

```
DOT edge attribute:  condition="$retry_count < 3 && $status = success"
                          │
                     [Lexer]  lexer.py
                          │  tokenizes into:
                          │  [VAR($retry_count), LT, INT(3), AND, VAR($status), EQ, STR(success)]
                          │
                     [Parser]  parser.py
                          │  builds:
                          │  BinaryOp(AND,
                          │    Comparison(LT, Variable("retry_count"), Number(3)),
                          │    Comparison(EQ, Variable("status"),  String("success"))
                          │  )
                          │
                     [Evaluator]  evaluator.py
                          │  resolves against PipelineContext:
                          │    context["retry_count"] = 2  → 2 < 3 = True
                          │    context["status"]      = "success" → True
                          │  short-circuits: True AND True → True
                          │
                     edge_selector.py  →  selects this edge
```

```
runner.py execution cycle:
  node_outcome = await middleware_chain(handler.execute(node, context))
          │
  [loop_detection.py]
     visit_counts[node.id] += 1
     check per-node limit (node.max_retries + 1)
     check pipeline-wide limit (graph.default_max_retry)
     detect_repeating_pattern(execution_history[-20:])
          │
          ├── within limits → proceed to edge_selector.py
          └── over limit    → emit loop.detected event
                              write ORCHESTRATOR_STUCK signal
                              if allow_partial → accept PARTIAL_SUCCESS, continue
                              else             → raise LoopDetectedError
```

### 3.3 Context Store Convention

Both subsystems read and write to `PipelineContext` (defined in `context.py`). The following keys are the interface contract:

| Key Pattern (in PipelineContext) | Writer | Condition Expression Syntax | Readers |
| --- | --- | --- | --- |
| `$retry_count` | `runner.py` (alias for current node's visit count minus 1) | `$retry_count` | condition evaluator |
| `$node_visits.<node_id>` | `loop_detection.py` | `$node_visits.impl_auth` | condition evaluator, edge_selector |
| `$last_status` | `runner.py` after each node outcome | `$last_status` | condition evaluator |
| `$pipeline_duration_s` | `runner.py` (updated each cycle) | `$pipeline_duration_s` | condition evaluator |
| `<node_id>.status` | handler via `outcome.context_updates` | `$<node_id>.status` | condition evaluator |
| `<node_id>.<field>` | handler via `outcome.context_updates` | `$<node_id>.<field>` | condition evaluator |

**AMD-4 Key Convention**: ALL built-in keys are stored WITH the `$` prefix in PipelineContext (e.g., `context["$retry_count"]`). The condition evaluator resolves `$variable_name` by looking up `$variable_name` (WITH the `$`) in the context. The `$` prefix in condition expressions is syntax that maps directly to the `$`-prefixed key in the context store. There is no stripping of `$` during variable resolution.

**AMD-4 Visit Count Index Convention**:

| Execution # | `$retry_count` | `$node_visits.<node_id>` | Explanation |
| --- | --- | --- | --- |
| 1st (initial) | 0 | 1 | First execution; 0 retries; visited once |
| 2nd (1st retry) | 1 | 2 | One retry; visited twice |
| 3rd (2nd retry) | 2 | 3 | Two retries; visited three times |

`$retry_count` is 0-indexed (retries only); `$node_visits.<id>` is 1-indexed (total visits including initial).

This convention must be documented in `context.py` as a module-level docstring. No implicit keys are permitted.

---

## 4. Epic 3: Condition Expression Language

### 4.1 Expression Grammar (BNF)

The grammar is a subset of boolean algebra with typed value comparisons. It is deliberately minimal — no arithmetic, no string interpolation beyond variable reference, no function calls. This keeps the evaluator secure (no `eval()`) and the error messages precise.

```
expr        := or_expr

or_expr     := and_expr ( '||' and_expr )*

and_expr    := not_expr ( '&&' not_expr )*

not_expr    := '!' atom
             | atom

atom        := comparison
             | '(' expr ')'

comparison  := value op value

value       := variable
             | string_literal
             | integer_literal
             | float_literal
             | boolean_literal

variable    := '$' identifier ( '.' identifier )*

identifier  := [a-zA-Z_][a-zA-Z0-9_]*

op          := '='
             | '!='
             | '<'
             | '>'
             | '<='
             | '>='

string_literal   := '"' [^"]* '"'
                  | '\'' [^\']* '\''

integer_literal  := '-'? [0-9]+

float_literal    := '-'? [0-9]+ '.' [0-9]+

boolean_literal  := 'true' | 'false'
```

**Design note — ****`=`**** vs ****`==`**: The community pattern (samueljklee, F#kYeah) uses single `=` for equality to match how edge conditions appear in actual DOT files authored by agents. The evaluator supports `=` as equality; `==` is rejected with a helpful error message.

**AMD-5 — Unquoted strings (RESOLVED)**: Bare unquoted identifiers on the right-hand side of a comparison are ACCEPTED as implicit string literals with a `log.warning("Deprecation: unquoted string '{value}' in condition expression. Use \"{value}\" for clarity.")`. This matches community practice (samueljklee, attractor-rb) and the PRD examples (`$status = success`).

The lexer emits `BARE_WORD` tokens for unquoted identifiers. The parser treats `BARE_WORD` tokens as implicit `LiteralNode(value=bare_word_text)` — NOT as an error.

Validation Rule 7 (`ConditionSyntaxValid`) treats conditions with bare words as WARNING-level (not error-level). The condition parses successfully but the validation report notes: "Deprecation: use quoted strings for clarity."

Grammar update — `value` production includes `bare_word`:
```
value       := variable
             | string_literal
             | integer_literal
             | float_literal
             | boolean_literal
             | bare_word              # AMD-5: accepted with deprecation warning

bare_word   := [a-zA-Z_][a-zA-Z0-9_]*    # only valid on RHS of comparison
```

### 4.2 Token Model

```python
# cobuilder/engine/conditions/ast.py

from enum import Enum, auto
from dataclasses import dataclass


class TokenType(Enum):
    # Literals
    INTEGER    = auto()
    FLOAT      = auto()
    STRING     = auto()
    BOOLEAN    = auto()
    VARIABLE   = auto()   # $ prefix consumed; name stored without $
    BARE_WORD  = auto()   # unquoted identifier on RHS (implicit string, deprecated)

    # Operators
    EQ         = auto()   # =
    NEQ        = auto()   # !=
    LT         = auto()   # <
    GT         = auto()   # >
    LTE        = auto()   # <=
    GTE        = auto()   # >=

    # Logical
    AND        = auto()   # &&
    OR         = auto()   # ||
    NOT        = auto()   # !

    # Grouping
    LPAREN     = auto()   # (
    RPAREN     = auto()   # )

    EOF        = auto()


@dataclass(frozen=True)
class Token:
    type: TokenType
    value: str | int | float | bool | None
    position: int   # byte offset in original expression string
```

### 4.3 AST Node Types

```python
# cobuilder/engine/conditions/ast.py  (continued)

from __future__ import annotations
from typing import Union


# Algebraic sum type via Union — all leaf nodes are frozen dataclasses

@dataclass(frozen=True)
class VariableNode:
    """$var_name or $node_id.field — path is list of identifier segments."""
    path: tuple[str, ...]          # ("retry_count",) or ("impl_auth", "status")


@dataclass(frozen=True)
class LiteralNode:
    """Scalar literal value."""
    value: str | int | float | bool


@dataclass(frozen=True)
class ComparisonNode:
    """Binary comparison: left op right."""
    operator: TokenType            # EQ | NEQ | LT | GT | LTE | GTE
    left: ValueNode
    right: ValueNode


@dataclass(frozen=True)
class BinaryOpNode:
    """Logical AND or OR of two sub-expressions."""
    operator: TokenType            # AND | OR
    left: ASTNode
    right: ASTNode


@dataclass(frozen=True)
class NotNode:
    """Logical NOT of a sub-expression."""
    operand: ASTNode


# Type aliases for clarity
ValueNode = Union[VariableNode, LiteralNode]
ASTNode   = Union[ComparisonNode, BinaryOpNode, NotNode, LiteralNode]
```

### 4.4 Lexer

```python
# cobuilder/engine/conditions/lexer.py

class ConditionLexer:
    """
    Tokenizes a condition expression string.

    Single-pass scanner. Whitespace is insignificant and consumed between
    tokens. No Unicode identifier support needed (DOT attribute values are ASCII).
    """

    def tokenize(self, source: str) -> list[Token]:
        """
        Returns a flat list of Token objects ending with Token(EOF).
        Raises ConditionLexError with position and reason on invalid input.
        """
        ...
```

Key lexer behaviors:

- `$` introduces a variable name; scanner consumes `$` then reads `[a-zA-Z_][a-zA-Z0-9_.]*`, splitting on `.` to produce the path tuple.
- `&&` and `||` are recognized as two-character tokens; bare `&` or `|` raise `ConditionLexError`.
- `<=` and `>=` are two-character tokens; bare `<` or `>` are single-character tokens.
- `!=` is a two-character token; bare `!` without a following `=` produces `TokenType.NOT`.
- Single-quoted and double-quoted strings are both valid; escape sequences are not processed (strings are taken verbatim between quotes).
- Numeric literals: integer if no decimal point; float if decimal point present. Leading `-` is consumed as part of the literal.
- `true` and `false` (case-insensitive) are boolean literals.
- Any other character sequence that starts with a letter is a `BARE_WORD` with a deprecation warning.

### 4.5 Parser

```python
# cobuilder/engine/conditions/parser.py

class ConditionParser:
    """
    Recursive-descent parser for the condition grammar.

    Precedence (lowest to highest):
      OR → AND → NOT → atom (comparison or grouped expr)

    All public methods raise ConditionParseError on invalid syntax.
    """

    def parse(self, source: str) -> ASTNode:
        """Entry point. Tokenizes source, then parses and returns root ASTNode."""
        ...

    def _parse_or(self) -> ASTNode: ...
    def _parse_and(self) -> ASTNode: ...
    def _parse_not(self) -> ASTNode: ...
    def _parse_atom(self) -> ASTNode: ...
    def _parse_comparison(self) -> ComparisonNode: ...
    def _parse_value(self) -> ValueNode: ...
    def _consume(self, expected: TokenType) -> Token: ...
    def _peek(self) -> Token: ...
```

The parser is stateless between calls; it constructs a fresh token stream for each `parse()` call. Error messages include the failing token's position and a human-readable description:

```
ConditionParseError: Expected operator after '$retry_count' at position 13,
  got 'three' (BARE_WORD). Valid operators: =, !=, <, >, <=, >=
```

### 4.6 Evaluator

```python
# cobuilder/engine/conditions/evaluator.py

class ConditionEvaluator:
    """
    Walks an ASTNode tree and evaluates it against a PipelineContext.

    Evaluation is strict: missing variables raise MissingVariableError
    unless the caller passes missing_var_default (then that value is used).
    Type coercion rules are applied at comparison boundaries.
    """

    def evaluate(
        self,
        node: ASTNode,
        context: PipelineContext,
        *,
        missing_var_default: Any = _SENTINEL,
    ) -> bool:
        """
        Returns True/False. Raises ConditionEvalError on type mismatch
        or unresolvable variable when no default is given.
        """
        ...

    def _resolve_variable(self, var: VariableNode, context: PipelineContext) -> Any: ...
    def _coerce_for_comparison(self, left: Any, right: Any, op: TokenType) -> tuple[Any, Any]: ...
    def _apply_comparison(self, op: TokenType, left: Any, right: Any) -> bool: ...
```

**Type coercion rules** applied in `_coerce_for_comparison`:

| Left type | Right type | Operator group | Coercion |
| --- | --- | --- | --- |
| `str` | `str` | any | no coercion |
| `str` | `int/float` | `=` / `!=` | parse left as number; raise `ConditionTypeError` if not numeric |
| `int/float` | `str` | `=` / `!=` | parse right as number; raise if not numeric |
| `int` | `float` | any | coerce int to float |
| `bool` | any | `=` / `!=` | compare as bool; raise `ConditionTypeError` for `<`/`>` |
| `str` | `str` | `<`/`>`/`<=`/`>=` | lexicographic comparison (allowed, not recommended) |

The `$retry_count` variable is always an integer from `loop_detection.py`. The `$status` variable is always a string. Mixed-type comparisons should be rare and are logged at WARNING level when coercion occurs.

**Short-circuit evaluation**: `BinaryOpNode(AND, ...)` evaluates the left branch first; if False, right branch is not evaluated (variables on the right are not resolved). This prevents `MissingVariableError` for conditions like `$retry_count > 0 && $last_result.coverage >= 80` when `last_result` does not yet exist on the first attempt.

**Built-in variable resolution**: Before looking up a variable in the context dict, the evaluator checks a built-in resolution table:

| Variable | Resolution |
| --- | --- |
| `$retry_count` | `context["node_visits"][current_node_id] - 1` (0-indexed) |
| `$node_visits.<node_id>` | `context["node_visits"].get(node_id, 0)` |
| `$pipeline_duration_s` | `(datetime.now(UTC) - context["pipeline_start"]).total_seconds()` |
| `$last_status` | `context.get("last_status", None)` |

Any other `$variable` resolves via flat lookup in `context` then nested lookup via `.`-separated path.

### 4.7 Public API (conditions package)

```python
# cobuilder/engine/conditions/__init__.py

def parse_condition(source: str) -> ASTNode:
    """
    Parse a condition expression string into an AST.
    Used by the validator (Epic 2, Rule 7: ConditionSyntaxValid) at graph load time.
    Raises ConditionParseError if syntax is invalid.
    """
    return ConditionParser().parse(source)


def evaluate_condition(
    source: str,
    context: PipelineContext,
    *,
    missing_var_default: Any = False,
) -> bool:
    """
    Parse and immediately evaluate a condition expression.
    Convenience function for edge_selector.py.
    Returns False on any error if missing_var_default=False.
    Raises ConditionEvalError only when missing_var_default is not supplied.
    """
    ast = parse_condition(source)
    return ConditionEvaluator().evaluate(ast, context, missing_var_default=missing_var_default)


def validate_condition_syntax(source: str) -> list[str]:
    """
    Returns a list of error strings (empty = valid).
    Used by Validator.ConditionSyntaxValid rule.
    Never raises — always returns errors as strings for the validation reporter.
    """
    try:
        parse_condition(source)
        return []
    except ConditionParseError as exc:
        return [str(exc)]
```

### 4.8 Integration with edge_selector.py

Step 1 of the 5-step edge selection algorithm becomes:

```python
# cobuilder/engine/edge_selector.py  (modified)

from cobuilder.engine.conditions import evaluate_condition

async def select_next_edge(
    node: Node,
    outcome: Outcome,
    context: PipelineContext,
    graph: Graph,
) -> Edge | None:
    outgoing = graph.edges_from(node.id)

    # Step 1: Condition match — evaluate all conditioned edges, take first True
    for edge in outgoing:
        if edge.condition:
            try:
                matched = evaluate_condition(
                    edge.condition,
                    context,
                    missing_var_default=False,   # missing vars = condition not met
                )
            except Exception as exc:
                # Condition syntax was validated at load time (Rule 7).
                # A runtime ConditionEvalError means context was modified to an
                # unexpected type. Log and skip this edge.
                logger.warning("condition_eval_error", edge=edge.id, error=str(exc))
                matched = False

            if matched:
                return edge

    # Steps 2-5: label, suggested_next, weight, default  (unchanged)
    ...
```

**Critical constraint**: The evaluator is called synchronously inside `select_next_edge`. It must never block on I/O. Variable resolution reads from an in-memory dict. This is guaranteed by the design — the context is fully in-memory.

### 4.9 Error Hierarchy

```python
# cobuilder/engine/conditions/ast.py

class ConditionError(Exception):
    """Base for all condition subsystem errors."""
    pass

class ConditionLexError(ConditionError):
    """Raised by the lexer on invalid tokens."""
    def __init__(self, message: str, position: int, source: str): ...

class ConditionParseError(ConditionError):
    """Raised by the parser on invalid grammar."""
    def __init__(self, message: str, token: Token, source: str): ...

class ConditionEvalError(ConditionError):
    """Raised by the evaluator on type mismatch or unresolvable variable."""
    pass

class MissingVariableError(ConditionEvalError):
    """Variable referenced in expression not found in context."""
    def __init__(self, path: tuple[str, ...], context_keys: list[str]): ...

class ConditionTypeError(ConditionEvalError):
    """Type coercion failed at comparison boundary."""
    pass
```

---

## 5. Epic 5: Loop Detection and Retry Policy

### 5.1 Data Models

```python
# cobuilder/engine/loop_detection.py

from dataclasses import dataclass, field
from typing import Literal
import re


@dataclass
class VisitRecord:
    """
    Per-node visit tracking. One record per unique node_id per pipeline run.
    Stored in PipelineContext under context["node_visits"][node_id].
    Serialized into checkpoint.json under the key "visit_records".
    """
    node_id: str
    count: int = 0
    first_visit_ts: float = 0.0     # Unix timestamp of first execution
    last_visit_ts: float = 0.0      # Unix timestamp of most recent execution
    outcomes: list[str] = field(default_factory=list)   # status per visit, e.g. ["SUCCESS", "FAILURE", "FAILURE"]


@dataclass
class LoopDetectionResult:
    """
    Result of a loop check for a single node execution.
    Returned by LoopDetector.check() before every edge selection.
    """
    node_id: str
    visit_count: int                    # count AFTER incrementing (1-indexed)
    allowed: bool                       # True → proceed; False → escalate
    reason: Literal[
        "ok",
        "per_node_limit_exceeded",
        "pipeline_limit_exceeded",
        "repeating_pattern_detected",
    ]
    pattern: list[str] | None = None    # node IDs forming the detected pattern, if any
    limit: int | None = None            # which limit was exceeded


@dataclass
class LoopPolicy:
    """
    Resolved from graph and node attributes. Passed to LoopDetector.
    """
    per_node_max: int           # default 4 (initial + 3 retries)
    pipeline_max: int           # default 50
    # AMD-6: pattern_window and pattern_min_length REMOVED — subsequence detection dropped
```

### 5.2 LoopDetector Class

```python
# cobuilder/engine/loop_detection.py  (continued)

class LoopDetector:
    """
    Tracks per-node visit counts and detects looping execution patterns.

    Instantiated once per pipeline run. State persisted in checkpoint
    via serialize() / from_checkpoint(). Context is kept in sync via
    sync_to_context() after every check.

    All methods are synchronous — visit counting is not I/O bound.
    """

    def __init__(self, policy: LoopPolicy) -> None:
        self._policy = policy
        self._visit_records: dict[str, VisitRecord] = {}
        self._execution_history: list[str] = []   # ordered node IDs, full history
        self._total_executions: int = 0

    def check(
        self,
        node_id: str,
        node_max_retries: int | None,    # from node attribute, overrides policy.per_node_max
        outcome_status: str | None = None,  # if re-entering after prior outcome
        ts: float | None = None,         # Unix timestamp; defaults to time.time()
    ) -> LoopDetectionResult:
        """
        Increment visit count for node_id and return a LoopDetectionResult.

        Call this AFTER the node executes (so visit count reflects completed runs).
        Call BEFORE edge selection (so loop escalation can short-circuit routing).
        """
        ...

    # AMD-6: detect_repeating_pattern() REMOVED — see Section 5.3

    def sync_to_context(self, context: PipelineContext) -> None:
        """
        Write current visit counts into context so condition
        expressions like $node_visits.impl_auth can read them.

        AMD-4: Keys are stored WITH '$' prefix to match the convention
        in PipelineContext. The condition evaluator looks up '$node_visits.impl_auth'
        (not 'node_visits.impl_auth').

        Also writes context["$retry_count"] for the most recently checked node.
        """
        ...

    def serialize(self) -> dict:
        """Return JSON-serializable dict for checkpoint inclusion."""
        ...

    @classmethod
    def from_checkpoint(cls, data: dict, policy: LoopPolicy) -> "LoopDetector":
        """Restore state from checkpoint dict. Used during --resume."""
        ...
```

### 5.3 Loop Detection Mechanisms — AMD-6 SIMPLIFIED

**AMD-6**: The repeating subsequence pattern detection has been REMOVED. Loop detection relies on two simple, proven mechanisms that cover all practical infinite loop scenarios:

1. **Per-node visit counter**: Each node has `max_retries` (default: 3). When `visit_count > max_retries + 1` (initial + retries), the loop detector fires `LoopDetectionResult(status="per_node_limit_exceeded")`.

2. **Pipeline-wide execution counter**: `default_max_retry` (default: 50) caps total node executions across the entire pipeline. When `total_executions > pipeline_max`, fires `LoopDetectionResult(status="pipeline_limit_exceeded")`.

**Rationale (from design challenge)**: The community implementations (Kilroy, samueljklee) use per-node visit counters as the primary loop detection mechanism. Subsequence detection adds O(window²) complexity without meaningful benefit over visit counts — a node that is visited 4+ times is already caught by the per-node limit. The `detect_repeating_pattern()` method is removed.

**ORCHESTRATOR\_STUCK signal payload (AMD-6 enhancement)**: When the loop detector fires, the signal includes the last 10 node IDs from execution history so the guardian can diagnose which edge/routing caused the loop, not just which node exceeded the limit:

```python
signal_protocol.write_signal(
    source="engine",
    target="guardian",
    signal_type=signal_protocol.ORCHESTRATOR_STUCK,
    payload={
        "node_id": node_id,
        "visit_count": visit_count,
        "limit": limit,
        "execution_history_tail": execution_history[-10:],  # AMD-6: for root cause diagnosis
    }
)
```

### 5.4 Retry Target Resolution Chain

When a node fails a goal gate check (or loop limit is reached), the engine must find a retry target. The resolution chain is:

```python
def resolve_retry_target(
    failed_node: Node,
    graph: Graph,
) -> str | None:
    """
    Returns the node_id to retry from, or None if no retry target exists.

    Resolution order (first non-None wins):
      1. failed_node.retry_target     (node-level attribute)
      2. graph.retry_target           (graph-level attribute, applies to all nodes)
      3. graph.fallback_retry_target  (last-resort graph attribute)
      4. None → pipeline FAILS with NoRetryTargetError
    """
    return (
        failed_node.attrs.get("retry_target")
        or graph.attrs.get("retry_target")
        or graph.attrs.get("fallback_retry_target")
    )
```

**Validation enforcement**: Validation Rule `RetryTargetsExist` (Epic 2) ensures that any non-None retry target returned by this function references a valid node ID. This means the resolution function never needs to check existence at runtime — it is guaranteed by the pre-execution pass.

### 5.5 Loop Restart Semantics

An edge with `loop_restart=true` triggers a partial context reset before the engine advances to the edge's target node:

```python
def apply_loop_restart(
    context: PipelineContext,
    graph: Graph,
) -> PipelineContext:
    """
    Clear all context keys except:
    - Graph-level variables (prefixed with "graph.")
    - Built-in immutable keys: pipeline_id, pipeline_start, pipeline_dot_path
    - Visit records (preserved so loop detection still functions after restart)

    Returns the cleared context. Visit counts are NOT reset — a loop_restart
    edge does not grant fresh retry budget; it resets accumulated state only.
    """
    preserved_prefixes = ("graph.", "pipeline_")
    new_context = {
        k: v for k, v in context.items()
        if any(k.startswith(p) for p in preserved_prefixes)
        or k == "node_visits"
    }
    return PipelineContext(new_context)
```

**Critical design decision**: Visit counts survive `loop_restart`. This is intentional. If visit counts were reset on loop restart, a pipeline could trigger `loop_restart` repeatedly and evade per-node limits. The loop restart is for context hygiene (preventing stale prior-run data from influencing new attempts), not for resetting retry budgets.

### 5.6 Escalation Protocol

When `LoopDetectionResult.allowed = False`, the runner executes this protocol:

```python
# cobuilder/engine/runner.py  (excerpt showing escalation path)

async def _handle_loop_detected(
    self,
    result: LoopDetectionResult,
    node: Node,
    context: PipelineContext,
) -> None:
    # 1. Emit structured event
    await self._emitter.emit(PipelineEvent(
        type="loop.detected",
        node_id=node.id,
        data={
            "visit_count": result.visit_count,
            "limit": result.limit,
            "reason": result.reason,
            "pattern": result.pattern,
        },
    ))

    # 2. Write ORCHESTRATOR_STUCK signal (bridges to S3 monitoring)
    await self._signal_bridge.write_signal(
        signal_type="ORCHESTRATOR_STUCK",
        payload={
            "node_id": node.id,
            "visit_count": result.visit_count,
            "reason": result.reason,
            "pipeline_id": context["pipeline_id"],
        },
    )

    # 3. Check allow_partial escape hatch
    if node.attrs.get("allow_partial") == "true":
        last_outcome = context.get(f"{node.id}.outcome")
        if last_outcome and last_outcome.get("status") == "PARTIAL_SUCCESS":
            logger.info("loop_partial_accepted", node=node.id)
            return   # caller proceeds to edge selection with PARTIAL_SUCCESS outcome

    # 4. Hard fail
    raise LoopDetectedError(
        node_id=node.id,
        visit_count=result.visit_count,
        reason=result.reason,
    )
```

### 5.7 Checkpoint Integration

Visit records are stored in the checkpoint under a dedicated key:

```json
{
  "pipeline_id": "cobuilder-e4",
  "last_node_id": "impl_auth",
  "completed_nodes": ["start", "impl_auth"],
  "context_snapshot": { "...": "..." },
  "visit_records": {
    "impl_auth": {
      "node_id": "impl_auth",
      "count": 2,
      "first_visit_ts": 1740700000.0,
      "last_visit_ts": 1740700120.0,
      "outcomes": ["FAILURE", "FAILURE"]
    }
  },
  "total_executions": 3,
  "execution_history": ["start", "impl_auth", "impl_auth"]
}
```

On `--resume`, the `LoopDetector.from_checkpoint()` restores `_visit_records`, `_execution_history`, and `_total_executions` so that retry limits are enforced continuously across crashes — a node cannot "reset" its retry budget by crashing the pipeline.

### 5.8 Policy Resolution from Graph Attributes

```python
def resolve_loop_policy(graph: Graph, node: Node | None = None) -> LoopPolicy:
    """
    Build a LoopPolicy from graph and optional node attributes.
    Node-level max_retries overrides the graph-level default.
    """
    graph_max_retries = int(graph.attrs.get("default_max_retry", 50))
    node_max_retries  = int(node.attrs.get("max_retries", 3)) + 1 if node else 4
    # +1 because max_retries=3 means 3 retries BEYOND the initial attempt = 4 total visits

    return LoopPolicy(
        per_node_max=node_max_retries,
        pipeline_max=graph_max_retries,
        pattern_window=20,
        pattern_min_length=3,
    )
```

The `LoopDetector` is initialized with a global `LoopPolicy` using graph-level defaults. When `check()` is called for a specific node, it computes the effective per-node limit by checking `node.attrs.get("max_retries")` and overriding the policy default inline — allowing per-node customization without re-instantiating the detector.

---

## 6. Functional Decomposition

### 6.1 Tasks for Epic 3 (Condition Expression Language)

| Task ID | Task | Owner Module | Complexity | Dependencies |
| --- | --- | --- | --- | --- |
| E3-T1 | Define `TokenType` enum and `Token` dataclass | `ast.py` | Low | None |
| E3-T2 | Define all AST node dataclasses and type aliases | `ast.py` | Low | E3-T1 |
| E3-T3 | Define error hierarchy (`ConditionError` subclasses) | `ast.py` | Low | None |
| E3-T4 | Implement `ConditionLexer.tokenize()` | `lexer.py` | Medium | E3-T1, E3-T3 |
| E3-T5 | Implement `ConditionParser` recursive descent methods | `parser.py` | High | E3-T1, E3-T2, E3-T3 |
| E3-T6 | Implement `ConditionEvaluator.evaluate()` and type coercion | `evaluator.py` | Medium | E3-T2, E3-T3 |
| E3-T7 | Implement built-in variable resolution table | `evaluator.py` | Low | E3-T6 |
| E3-T8 | Implement short-circuit evaluation in BinaryOpNode | `evaluator.py` | Low | E3-T6 |
| E3-T9 | Implement public API functions in `__init__.py` | `__init__.py` | Low | E3-T4, E3-T5, E3-T6 |
| E3-T10 | Integrate `evaluate_condition()` into `edge_selector.py` step 1 | `edge_selector.py` | Low | E3-T9, existing |
| E3-T11 | Integrate `validate_condition_syntax()` into validator Rule 7 | `validation/rules.py` | Low | E3-T9, existing |
| E3-T12 | Write 50+ unit tests (see §8 for coverage matrix) | `tests/` | High | E3-T1 through E3-T9 |

**Sequencing**: E3-T1 through E3-T3 are pure data definitions with no dependencies — implement in a single batch. E3-T4 (lexer) and E3-T5 (parser) can be developed concurrently once types are defined. E3-T6 through E3-T8 (evaluator) require the parser AST types. Integration tasks E3-T10 and E3-T11 are last and are read-only changes to existing files.

### 6.2 Tasks for Epic 5 (Loop Detection)

| Task ID | Task | Owner Module | Complexity | Dependencies |
| --- | --- | --- | --- | --- |
| E5-T1 | Define `VisitRecord`, `LoopDetectionResult`, `LoopPolicy` dataclasses | `loop_detection.py` | Low | None |
| E5-T2 | Implement `LoopDetector.__init__()` and internal state | `loop_detection.py` | Low | E5-T1 |
| E5-T3 | Implement `LoopDetector.check()` — per-node and pipeline limits | `loop_detection.py` | Medium | E5-T1, E5-T2 |
| E5-T4 | Implement `detect_repeating_pattern()` sliding-window algorithm | `loop_detection.py` | Medium | E5-T2 |
| E5-T5 | Integrate pattern detection into `check()` | `loop_detection.py` | Low | E5-T3, E5-T4 |
| E5-T6 | Implement `sync_to_context()` | `loop_detection.py` | Low | E5-T2 |
| E5-T7 | Implement `serialize()` and `from_checkpoint()` | `loop_detection.py` | Low | E5-T1, E5-T2 |
| E5-T8 | Implement `resolve_retry_target()` | `loop_detection.py` | Low | None (reads graph attrs) |
| E5-T9 | Implement `apply_loop_restart()` context reset | `loop_detection.py` | Low | None |
| E5-T10 | Implement `resolve_loop_policy()` | `loop_detection.py` | Low | E5-T1 |
| E5-T11 | Integrate `LoopDetector.check()` into `runner.py` execution cycle | `runner.py` | Medium | E5-T3, E5-T6, existing |
| E5-T12 | Implement `_handle_loop_detected()` escalation in `runner.py` | `runner.py` | Medium | E5-T11, event bus, signal bridge |
| E5-T13 | Integrate `loop_restart` edge handling in `runner.py` | `runner.py` | Low | E5-T9, existing |
| E5-T14 | Integrate visit count persistence into `checkpoint.py` | `checkpoint.py` | Low | E5-T7, existing |
| E5-T15 | Write loop scenario tests (see §8) | `tests/` | High | E5-T1 through E5-T14 |

**Sequencing**: E5-T1 through E5-T7 are self-contained within `loop_detection.py` and can be implemented as a unit. E5-T8 through E5-T10 are utility functions with no mutual dependencies. Integration tasks E5-T11 through E5-T14 require the existing `runner.py`, `checkpoint.py`, and event/signal infrastructure from Epic 4 to be at least partially implemented (specifically the event emitter protocol and signal bridge stub).

---

## 7. API Contracts

### 7.1 Condition Expression Public API

```python
# cobuilder/engine/conditions/__init__.py

def parse_condition(source: str) -> ASTNode:
    """
    Parse a condition string into an AST. No context required.

    Args:
        source: Raw condition string from DOT edge 'condition' attribute.
                Example: "$retry_count < 3 && $status = success"

    Returns:
        Root ASTNode of the parsed expression tree.

    Raises:
        ConditionLexError: If the string contains invalid tokens.
        ConditionParseError: If the token sequence violates the grammar.

    Note:
        This function is called by the validator (Epic 2) at graph load time.
        It must never trigger any I/O or network calls.
        Typical execution time: <1ms for expressions up to 200 characters.
    """


def evaluate_condition(
    source: str,
    context: PipelineContext,
    *,
    missing_var_default: Any = False,
) -> bool:
    """
    Parse and evaluate a condition expression against a pipeline context.

    Args:
        source: Raw condition string (same as parse_condition).
        context: Current pipeline context (in-memory dict-like object).
        missing_var_default: Value to use when a referenced variable is absent
            from context. Defaults to False (condition not met for missing vars).
            Pass _SENTINEL to raise MissingVariableError instead.

    Returns:
        True if condition evaluates to truthy, False otherwise.

    Raises:
        ConditionParseError: If syntax is invalid (caller should have validated).
        ConditionEvalError: If type coercion fails at a comparison boundary.
        MissingVariableError: Only when missing_var_default is not supplied.
    """


def validate_condition_syntax(source: str) -> list[str]:
    """
    Validate syntax without raising. Returns list of error messages (empty = valid).

    Args:
        source: Raw condition string.

    Returns:
        List of human-readable error strings. Empty list means the expression
        is syntactically valid. Errors include position information.

    Note:
        Never raises. Suitable for use in validator loop over all graph edges.
    """
```

### 7.2 Loop Detection Public API

```python
# cobuilder/engine/loop_detection.py

class LoopDetector:

    def check(
        self,
        node_id: str,
        node_max_retries: int | None = None,
        outcome_status: str | None = None,
        ts: float | None = None,
    ) -> LoopDetectionResult:
        """
        Record a node execution and check whether limits are exceeded.

        Call this once per node execution, AFTER the node handler returns
        and BEFORE edge selection.

        Args:
            node_id: The ID of the node that just executed.
            node_max_retries: Node-level override for max retries. If None,
                uses the policy default. Represents retry count beyond the
                first attempt (max_retries=3 → 4 total visits allowed).
            outcome_status: Status string from node outcome (e.g. "SUCCESS",
                "FAILURE"). Stored in VisitRecord.outcomes for audit trail.
            ts: Unix timestamp of execution. Defaults to time.time().

        Returns:
            LoopDetectionResult with allowed=True (proceed) or allowed=False
            (escalate). When allowed=False, runner must call _handle_loop_detected.

        Note:
            This method modifies internal state (visit counts, history).
            It must be called exactly once per node execution.
        """

    def sync_to_context(self, context: PipelineContext) -> None:
        """
        Write current visit counts to context["node_visits"] dict and
        update context["retry_count"] for the most recently checked node.

        Call this immediately after check() so that condition expressions
        in the following edge_selector call see up-to-date visit counts.

        Args:
            context: Mutable PipelineContext to update in place.
        """

    def serialize(self) -> dict:
        """
        Return a JSON-serializable dict representing complete detector state.
        Used by checkpoint.py to persist loop state.

        Schema:
            {
              "visit_records": { node_id: VisitRecord.__dict__, ... },
              "total_executions": int,
              "execution_history": [node_id, ...]
            }
        """

    @classmethod
    def from_checkpoint(cls, data: dict, policy: LoopPolicy) -> "LoopDetector":
        """
        Restore LoopDetector state from a checkpoint dict.
        Used during --resume to continue enforcing retry limits across restarts.

        Args:
            data: Dict previously produced by serialize().
            policy: LoopPolicy to apply (resolved from graph on resume).
        """


def resolve_retry_target(failed_node: Node, graph: Graph) -> str | None:
    """
    Return the node_id to route to on goal gate failure, following the
    resolution chain: node.retry_target → graph.retry_target →
    graph.fallback_retry_target → None.

    Args:
        failed_node: The node whose goal gate check failed.
        graph: The pipeline graph (for graph-level attribute fallback).

    Returns:
        A node_id string, or None if no retry target is configured.
        The caller is responsible for raising NoRetryTargetError when None is returned.
    """


def apply_loop_restart(context: PipelineContext, graph: Graph) -> PipelineContext:
    """
    Return a new PipelineContext with accumulated per-run state cleared,
    preserving graph-level variables and visit records.

    Used when traversing an edge with loop_restart=true.

    Args:
        context: Current context to copy from.
        graph: The pipeline graph (for identifying graph-level keys).

    Returns:
        A new PipelineContext with only preserved keys retained.
        The original context is not modified.
    """
```

---

## 8. Acceptance Criteria Per Feature

### 8.1 Epic 3 Acceptance Criteria

| ID | Criterion | Verification Method |
| --- | --- | --- |
| E3-AC1 | `$retry_count < 3 && $status = success` evaluates True when context has `retry_count=2, status="success"` | Unit test |
| E3-AC2 | `$retry_count < 3 && $status = success` evaluates False when `retry_count=3` | Unit test |
| E3-AC3 | `$node_visits.impl_auth > 2` evaluates True when `node_visits.impl_auth=3` in context | Unit test |
| E3-AC4 | `!($status = failed)` evaluates True when `status="success"` | Unit test |
| E3-AC5 | `($a < 5) |  | ($b = done)` evaluates correctly via short-circuit OR | Unit test |
| E3-AC6 | Missing variable with `missing_var_default=False` returns False without raising | Unit test |
| E3-AC7 | Missing variable without default raises `MissingVariableError` with variable path in message | Unit test |
| E3-AC8 | Expression `$count > abc` raises `ConditionTypeError` (string vs numeric operator) | Unit test |
| E3-AC9 | `validate_condition_syntax("$x >> 5")` returns non-empty error list (invalid operator) | Unit test |
| E3-AC10 | `validate_condition_syntax("$x < 5")` returns empty list | Unit test |
| E3-AC11 | Unquoted bare word on RHS is accepted with deprecation warning (backward compat) | Unit test + log capture |
| E3-AC12 | Nested parentheses `(($a < 3) && ($b > 1))` parse and evaluate correctly | Unit test |
| E3-AC13 | `parse_condition()` completes in <1ms for a 200-character expression | Performance test |
| E3-AC14 | `edge_selector.py` step 1 calls `evaluate_condition()` and selects first True edge | Integration test |
| E3-AC15 | Validator Rule 7 calls `validate_condition_syntax()` for each edge in graph | Integration test |
| E3-AC16 | Evaluator returns False (not exception) when condition eval error occurs in `edge_selector` integration path | Integration test |

### 8.2 Epic 5 Acceptance Criteria

| ID | Criterion | Verification Method |
| --- | --- | --- |
| E5-AC1 | `LoopDetector.check()` increments visit count on each call; count is 1-indexed | Unit test |
| E5-AC2 | `check()` returns `allowed=True` when count is at or below `per_node_max` | Unit test |
| E5-AC3 | `check()` returns `allowed=False, reason="per_node_limit_exceeded"` when count exceeds `per_node_max` | Unit test |
| E5-AC4 | `check()` returns `allowed=False, reason="pipeline_limit_exceeded"` when total executions exceed `pipeline_max` | Unit test |
| E5-AC5 | `detect_repeating_pattern([A,B,C,A,B,C])` returns `[A,B,C]` | Unit test |
| E5-AC6 | `detect_repeating_pattern([A,B,C,A,D])` returns None | Unit test |
| E5-AC7 | `detect_repeating_pattern` requires at least `2 * min_length` entries to trigger | Unit test |
| E5-AC8 | `check()` returns `allowed=False, reason="repeating_pattern_detected"` when A→B→C→A→B→C detected | Unit test |
| E5-AC9 | `sync_to_context()` writes `context["node_visits"]["impl_auth"]=2` after second check | Unit test |
| E5-AC10 | `sync_to_context()` writes `context["retry_count"]=1` (0-indexed) after second check | Unit test |
| E5-AC11 | `serialize()` produces a dict that `from_checkpoint()` restores identically (round-trip) | Unit test |
| E5-AC12 | After `from_checkpoint()`, `check()` continues counting from persisted count | Unit test |
| E5-AC13 | `resolve_retry_target(node_with_retry_target, graph)` returns node-level value | Unit test |
| E5-AC14 | `resolve_retry_target(node_without_retry_target, graph_with_retry_target)` returns graph-level value | Unit test |
| E5-AC15 | `resolve_retry_target(node, graph_no_retry)` returns None | Unit test |
| E5-AC16 | `apply_loop_restart()` preserves `graph.*` and `node_visits` keys | Unit test |
| E5-AC17 | `apply_loop_restart()` removes per-run context keys (e.g., `impl_auth.status`) | Unit test |
| E5-AC18 | `apply_loop_restart()` does NOT reset visit counts | Unit test |
| E5-AC19 | Runner integration: `loop.detected` event emitted when `allowed=False` | Integration test |
| E5-AC20 | Runner integration: `ORCHESTRATOR_STUCK` signal file written when loop detected | Integration test |
| E5-AC21 | `allow_partial=true` on node: runner accepts PARTIAL_SUCCESS when loop detected | Integration test |
| E5-AC22 | `allow_partial=false` on node: `LoopDetectedError` raised and pipeline fails | Integration test |
| E5-AC23 | Visit counts from pre-crash run are enforced in resumed run (not reset on resume) | Integration test |
| E5-AC24 | Node with `max_retries=1` allows exactly 2 total visits (initial + 1 retry) | Integration test |
| E5-AC25 | `loop_restart=true` edge triggers `apply_loop_restart()` before advancing | Integration test |

---

## 9. Error Handling

### 9.1 Error Taxonomy

```
ConditionError (base)
├── ConditionLexError       — invalid token; position + source in message
├── ConditionParseError     — grammar violation; failing token + position
└── ConditionEvalError      — runtime evaluation failure
    ├── MissingVariableError — variable not in context
    └── ConditionTypeError   — incompatible types at comparison

LoopError (base)
├── LoopDetectedError       — visit limit or pattern limit exceeded
│     fields: node_id, visit_count, reason, pattern
└── NoRetryTargetError      — goal gate failed and no retry target configured
      fields: node_id, pipeline_id
```

### 9.2 Error Propagation Strategy

| Error Class | Where Raised | Where Caught | Action |
| --- | --- | --- | --- |
| `ConditionLexError` | `lexer.py` | `validate_condition_syntax()` | Returned as string; also caught in `parse_condition()` and re-raised for caller |
| `ConditionParseError` | `parser.py` | Same as above | Same as above |
| `ConditionEvalError` | `evaluator.py` | `edge_selector.py` wrapper around `evaluate_condition()` | Logged at WARNING; condition treated as False; edge skipped |
| `MissingVariableError` | `evaluator.py` | `evaluate_condition()` with `missing_var_default` | Returns default value (False) silently; logs at DEBUG |
| `ConditionTypeError` | `evaluator.py` | `edge_selector.py` | Logged at WARNING; edge skipped |
| `LoopDetectedError` | `runner.py._handle_loop_detected()` | `runner.py` main loop | Emits `pipeline.failed` event; writes `PIPELINE_FAILED` signal; exits with non-zero status |
| `NoRetryTargetError` | `runner.py` on goal gate failure | `runner.py` main loop | Same as `LoopDetectedError` |

### 9.3 Validation vs Runtime Error Philosophy

All condition syntax errors should be caught at validation time (Epic 2, Rule 7). By the time the engine executes, every edge condition in the graph has been confirmed syntactically valid. Runtime `ConditionEvalError` should be rare and indicates either:
1. A context mutation by a handler that changed a value's type.
2. A missing variable that was not present during validation (dynamic context).

Both cases are logged and treated as "condition not met" (edge skipped), not as pipeline failures. The engine is designed to be resilient to evaluation noise; a wrong routing decision is preferable to a crash.

Loop detection errors, by contrast, are intentionally fatal by default. They indicate a structural problem (misconfigured retry target or genuinely broken task) that cannot be self-healed by the engine alone.

---

## 10. File Scope

The following files are created or modified by this SD. Files marked NEW are created from scratch. Files marked MODIFIED have defined, bounded changes.

### 10.1 New Files

| File | Lines (est.) | Purpose |
| --- | --- | --- |
| `cobuilder/engine/conditions/__init__.py` | 60 | Public API: `parse_condition`, `evaluate_condition`, `validate_condition_syntax` |
| `cobuilder/engine/conditions/ast.py` | 100 | `TokenType`, `Token`, all AST node dataclasses, error hierarchy |
| `cobuilder/engine/conditions/lexer.py` | 150 | `ConditionLexer.tokenize()` |
| `cobuilder/engine/conditions/parser.py` | 200 | `ConditionParser` recursive-descent methods |
| `cobuilder/engine/conditions/evaluator.py` | 180 | `ConditionEvaluator.evaluate()`, type coercion, variable resolution |
| `cobuilder/engine/loop_detection.py` | 300 | `VisitRecord`, `LoopDetectionResult`, `LoopPolicy`, `LoopDetector`, utility functions |
| `tests/engine/conditions/test_lexer.py` | 150 | Lexer token tests |
| `tests/engine/conditions/test_parser.py` | 200 | Parser AST shape tests |
| `tests/engine/conditions/test_evaluator.py` | 300 | Evaluator expression tests (50+ cases) |
| `tests/engine/conditions/test_integration.py` | 100 | Condition → edge_selector integration |
| `tests/engine/test_loop_detection.py` | 350 | Loop detector unit and scenario tests |

### 10.2 Modified Files

| File | Change Scope | Description |
| --- | --- | --- |
| `cobuilder/engine/edge_selector.py` | Step 1 only (5-10 lines) | Import and call `evaluate_condition()` for edges with `.condition` attribute |
| `cobuilder/engine/runner.py` | Post-handler section (30-50 lines) | Call `loop_detector.check()`, `sync_to_context()`, `_handle_loop_detected()`, `apply_loop_restart()` |
| `cobuilder/engine/checkpoint.py` | Serialize/deserialize (15-20 lines) | Include `visit_records`, `total_executions`, `execution_history` in checkpoint dict |
| `cobuilder/engine/validation/rules.py` | Rule 7 only (10-15 lines) | Call `validate_condition_syntax()` in `ConditionSyntaxValid` rule |
| `cobuilder/engine/context.py` | Docstring only | Document `node_visits`, `retry_count`, `last_status` as reserved keys |

**Total new lines**: approximately 1,900 production + 1,100 test = 3,000 lines.

No existing files outside the `cobuilder/engine/` directory are modified by this SD.

---

## 11. Testing Strategy

### 11.1 Unit Test Coverage Matrix for Epic 3

The 50+ required unit tests are distributed across these categories:

| Category | Test Count | Examples |
| --- | --- | --- |
| Lexer — valid tokens | 12 | `$var`, `$a.b`, `123`, `3.14`, `"hello"`, `true`, `&&`, `\ | \ | `, `!`, `<=`, `!=`, `(` |
| Lexer — invalid tokens | 6 | `&` (single), `\ | ` (single), `@var`, `$` (bare), unterminated string, unknown char |
| Parser — simple comparisons | 8 | `$x = 5`, `$x != 5`, `$x < 5`, `$x > 5`, `$x <= 5`, `$x >= 5`, `$a = "b"`, `$a.b = "c"` |
| Parser — logical operators | 6 | `$a && $b`, `$a \ | \ | $b`, `!$a`, `$a && $b && $c`, `$a \ | \ | $b \ | \ | $c`, `!($a && $b)` |
| Parser — grouping | 4 | `($a < 5)`, `(($a < 5) && ($b > 1))`, `!($a < 5)`, deeply nested |
| Parser — errors | 6 | Unmatched paren, missing operator, double operator, empty string, whitespace only, trailing junk |
| Evaluator — true conditions | 8 | Various comparisons resolving True |
| Evaluator — false conditions | 6 | Various comparisons resolving False |
| Evaluator — type coercion | 6 | Int vs float, string vs numeric string, bool comparisons |
| Evaluator — missing vars | 4 | Default=False, default=_SENTINEL raises, nested path missing, empty context |
| Evaluator — built-in vars | 4 | `$retry_count`, `$node_visits.X`, `$pipeline_duration_s`, `$last_status` |
| Evaluator — short-circuit | 4 | AND left=False skips right, OR left=True skips right |
| Total | 74 | Exceeds 50-test requirement |

### 11.2 Loop Scenario Tests for Epic 5

| Scenario | Test Name | Description |
| --- | --- | --- |
| Normal execution | `test_no_loop_single_visit` | Node visited once; `allowed=True` |
| Retry within limit | `test_retry_within_limit` | Node visited 3 times with `max_retries=3`; all `allowed=True` |
| Per-node limit hit | `test_per_node_limit_exceeded` | Node visited 5 times with `max_retries=3`; 5th returns `allowed=False` |
| Pipeline limit hit | `test_pipeline_limit_exceeded` | 51 total executions across many nodes; 51st returns `allowed=False, reason=pipeline_limit_exceeded` |
| Simple pattern A-B-A-B | `test_pattern_ab_ab` | History ends A,B,A,B,A,B; detector finds [A,B] after 6th |
| Pattern A-B-C-A-B-C | `test_pattern_abc_abc` | Classic 3-cycle detection |
| No pattern (A-B-C-A-D) | `test_no_pattern_when_diverged` | Should return None |
| Pattern below window | `test_pattern_below_min_length` | Length-2 repeat with min_length=3; no detection |
| Context sync | `test_sync_to_context` | After check(), context has correct node_visits and retry_count |
| Checkpoint round-trip | `test_checkpoint_roundtrip` | serialize() then from_checkpoint() restores identical state |
| Resume enforces limits | `test_resume_enforces_limits` | Node had 3 visits pre-crash; resumed run rejects 4th |
| Retry resolution — node | `test_retry_target_node_level` | Node-level `retry_target` takes precedence |
| Retry resolution — graph | `test_retry_target_graph_level` | Graph-level `retry_target` used when node has none |
| Retry resolution — fallback | `test_retry_target_fallback` | `fallback_retry_target` used as last resort |
| Retry resolution — none | `test_no_retry_target_returns_none` | Returns None when nothing configured |
| Loop restart preserves visits | `test_loop_restart_preserves_visits` | `apply_loop_restart()` keeps node_visits intact |
| Loop restart clears state | `test_loop_restart_clears_run_state` | `apply_loop_restart()` removes per-run context keys |
| Allow partial escape | `test_allow_partial_true` | `allow_partial=true` node continues with PARTIAL_SUCCESS |
| Allow partial blocked | `test_allow_partial_false` | `allow_partial=false` node raises LoopDetectedError |
| Signal written on loop | `test_orchestrator_stuck_signal_written` | Integration: signal file exists after loop detection |
| Event emitted on loop | `test_loop_detected_event_emitted` | Integration: event bus received `loop.detected` event |

### 11.3 Test File Organization

```
tests/
└── engine/
    ├── conditions/
    │   ├── __init__.py
    │   ├── test_lexer.py           # Token-level tests
    │   ├── test_parser.py          # AST shape tests
    │   ├── test_evaluator.py       # Expression evaluation tests
    │   └── test_integration.py     # evaluate_condition() → edge_selector
    └── test_loop_detection.py      # All loop detection unit + scenario tests
```

Tests use `pytest` with `pytest-asyncio` for integration tests that call `runner.py`. Condition tests are fully synchronous and have no async requirements.

Fixtures:

```python
@pytest.fixture
def basic_context() -> PipelineContext:
    return PipelineContext({
        "retry_count": 0,
        "status": "success",
        "pipeline_id": "test-pipeline",
        "pipeline_start": datetime.now(UTC),
        "node_visits": {},
    })

@pytest.fixture
def default_policy() -> LoopPolicy:
    return LoopPolicy(per_node_max=4, pipeline_max=50)
```

### 11.4 Performance Benchmarks

| Benchmark | Target | Method |
| --- | --- | --- |
| `parse_condition()` for 200-char expression | <1ms | `pytest-benchmark` or `timeit` in test |
| `evaluate_condition()` with 10-variable context | <2ms | Same |
| `LoopDetector.check()` for 1000th execution | <0.5ms | Timing assertion in test |
| `detect_repeating_pattern()` on 20-entry window | <0.1ms | Timing assertion in test |

These are soft targets documented in the tests as comments, not hard CI gates, given the pure-Python nature of the implementation.

---

## 12. Risk Assessment and Mitigation

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Bare-word backward compatibility breaks pipeline authors | Medium | Medium | Lexer emits `BARE_WORD` with deprecation warning; does not reject. Community pattern (`$status = success`) continues to work. Migration guide in `CHANGELOG`. |
| Type coercion surprises (e.g., `"3" >= 3` is True) | Low | Low | Coercion is logged at WARNING. Documentation provides coercion table. Authors should use explicit types. |
| Pattern detector false positive on legitimate re-entry | Low | High | `min_length=3` and `window=20` calibrated to avoid false positives on single re-entry. Pattern must repeat twice consecutively. |
| Visit counts not persisted on abrupt crash (SIGKILL) | Low | Medium | Checkpoint is written after every node by `checkpoint.py`. At most one visit is lost per crash. The retry budget is at most off by one. |
| `loop_restart` context wipe breaks downstream nodes | Medium | Medium | Only per-run keys are cleared; graph-level variables (which downstream nodes rely on for configuration) are preserved. Integration tests cover the boundary. |
| Condition evaluator performance degrades for deeply nested expressions | Low | Low | Grammar has no recursive compound left, keeping parser stack depth bounded. 200-char expression is a practical ceiling for DOT attributes. |
| `ORCHESTRATOR_STUCK` signal not consumed by S3 | Low | Medium | Signal bridge is the same protocol used by existing signals. Epic 4 `SignalBridge` handles this. Loop detection tests verify the signal file is written; S3 consumption is covered by existing signal tests. |

---

## 13. Implementation Sequencing and Dependencies

### 13.1 Implementation Order

Epic 3 and Epic 5 are independent of each other and can be implemented in parallel by two engineers. They share no code — only the `PipelineContext` type and the `edge_selector.py` integration point.

**Phase 1 (Parallel)**:
- Engineer A: E3-T1 → E3-T3 (type definitions), then E3-T4 (lexer), then E3-T5 (parser)
- Engineer B: E5-T1 → E5-T2 (data models + init), then E5-T3 → E5-T5 (check + patterns)

**Phase 2 (Parallel)**:
- Engineer A: E3-T6 → E3-T9 (evaluator + public API) + E3-T12 (tests)
- Engineer B: E5-T6 → E5-T10 (sync, serialize, resolve, restart) + initial unit tests

**Phase 3 (Sequential — requires both Phases 1+2 and Epic 4 event bus stub)**:
- Integrate both subsystems: E3-T10, E3-T11, E5-T11 → E5-T15

### 13.2 External Dependencies

| Dependency | Required By | Status |
| --- | --- | --- |
| `PipelineContext` type (from `context.py`) | Both subsystems | Must exist with `node_visits` dict key support |
| `edge_selector.py` 5-step algorithm | E3-T10 integration | Must have stub for step 1 (can be `pass` initially) |
| Event emitter protocol (from Epic 4) | E5-T12 escalation | Needs `emit(PipelineEvent)` interface; can be a mock stub |
| Signal bridge (from Epic 4) | E5-T12 escalation | Needs `write_signal(type, payload)` interface |
| `runner.py` execution cycle | E5-T11 integration | Must have a post-handler hook point |
| `checkpoint.py` serialize/deserialize | E5-T14 | Must support `extra_data` dict in checkpoint schema |

The condition language subsystem has zero external dependencies beyond Python stdlib. The loop detection subsystem depends only on the event emitter and signal bridge interfaces, which can be mocked with simple stubs for development and testing.

---

## 14. Handoff Notes for Implementing Engineer

### 14.1 Critical Implementation Details

**Condition parser precedence**: The grammar defines OR as lower precedence than AND. Implement `_parse_or` calling `_parse_and` (not the other way around). A common mistake is inverting this and getting right-hand associativity.

**Lexer state**: The lexer is implemented as a stateless function call. Do not use class-level mutable state between tokenize() calls. A fresh character index and output list per call is the safest approach.

**Loop detector thread safety**: The runner is async (asyncio). `LoopDetector` is called synchronously within the async event loop. Do not use threading locks — asyncio's single-threaded cooperative model makes them unnecessary. Do not make `check()` async.

**Context key naming**: The reserved keys `node_visits`, `retry_count`, `last_status`, `pipeline_id`, `pipeline_start` must not be set by handlers via `outcome.context_updates`. The runner enforces this by filtering reserved keys from handler updates before applying them to context. Document this in `context.py`.

**`loop_restart`**** timing**: Apply context reset AFTER recording the loop-restart edge selection in the event bus (`edge.selected` event) and BEFORE advancing to the next node. The checkpoint written at the start of the next node will capture the cleared context.

### 14.2 Reference Implementations

For the recursive-descent parser (E3-T5), the closest public reference is samueljklee's Python Attractor condition parser. The F#kYeah implementation's compound condition examples (`outcome=success && context.tests=passed`) are the primary source for validating the grammar handles real-world DOT condition strings.

For loop detection (E5-T3 through E5-T5), the community reference is the pseudocode in the Attractor spec supplemented by F#kYeah's `loop_restart=true` edge behavior. The repeating-pattern algorithm is novel to this implementation — no community implementation has published a sliding-window pattern detector. The algorithm in §5.3 of this SD is the specification.

---

*End of Solution Design Document*
