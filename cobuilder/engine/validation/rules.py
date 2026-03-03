"""13 validation rules for the Pre-Execution Validation Suite (Epic 2).

Each rule is a stateless class implementing the ``Rule`` protocol.  Rules
receive the full ``Graph`` object and return a list of ``RuleViolation``
objects (empty list means the rule passed).

Rule index:
  ERROR-level (block execution):
    1.  SingleStartNode       — exactly one Mdiamond node
    2.  AtLeastOneExit        — at least one Msquare node
    3.  AllNodesReachable     — BFS from start covers all nodes
    4.  EdgeTargetsExist      — edge.source and edge.target in node set
    5.  StartNoIncoming       — Mdiamond has no predecessors
    6.  ExitNoOutgoing        — Msquare has no successors
    7.  ConditionSyntaxValid  — edge.condition parses without error
    8.  StylesheetSyntaxValid — model_stylesheet parses correctly
    9.  RetryTargetsExist     — retry_target IDs exist in graph

  WARNING-level (advisory, do not block execution):
    10. NodeTypesKnown        — node shapes are in registered set
    11. FidelityValuesValid   — fidelity is 'full' or 'checkpoint'
    12. GoalGatesHaveRetry    — goal_gate=true nodes have retry path
    13. LlmNodesHavePrompts   — LLM nodes have prompt or label
"""
from __future__ import annotations

from collections import deque
from typing import Protocol, runtime_checkable

from cobuilder.engine.graph import Graph, LLM_NODE_SHAPES, SHAPE_TO_HANDLER
from cobuilder.engine.validation import RuleViolation, Severity


# ---------------------------------------------------------------------------
# Rule protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class Rule(Protocol):
    """Protocol that all 13 validation rules must implement.

    Rules are stateless — a single instance may be called multiple times on
    different graphs.
    """

    rule_id: str
    """Class-level string constant, e.g. ``"SingleStartNode"``."""

    severity: Severity
    """Class-level default severity (``ERROR`` or ``WARNING``)."""

    def check(self, graph: Graph) -> list[RuleViolation]:
        """Run this rule against *graph* and return any violations found.

        Returns:
            Empty list if the rule passes.
            One or more ``RuleViolation`` objects if violations are found.
        """
        ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _error(
    rule_id: str,
    message: str,
    fix_hint: str,
    *,
    node_id: str | None = None,
    edge_src: str | None = None,
    edge_dst: str | None = None,
) -> RuleViolation:
    return RuleViolation(
        rule_id=rule_id,
        severity=Severity.ERROR,
        message=message,
        node_id=node_id,
        edge_src=edge_src,
        edge_dst=edge_dst,
        fix_hint=fix_hint,
    )


def _warning(
    rule_id: str,
    message: str,
    fix_hint: str,
    *,
    node_id: str | None = None,
    edge_src: str | None = None,
    edge_dst: str | None = None,
) -> RuleViolation:
    return RuleViolation(
        rule_id=rule_id,
        severity=Severity.WARNING,
        message=message,
        node_id=node_id,
        edge_src=edge_src,
        edge_dst=edge_dst,
        fix_hint=fix_hint,
    )


def _bfs_reachable(start_id: str, graph: Graph) -> set[str]:
    """BFS from *start_id* using ``graph.edges_from()``; returns visited node IDs."""
    visited: set[str] = set()
    queue: deque[str] = deque([start_id])
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        for edge in graph.edges_from(node_id):
            if edge.target not in visited:
                queue.append(edge.target)
    return visited


# ---------------------------------------------------------------------------
# ParseError stub for Rule 7 (used until Epic 3 condition parser lands)
# ---------------------------------------------------------------------------

class _ParseError(Exception):
    """Stub parse error for the placeholder condition parser."""


class _ConditionParserStub:
    """Placeholder that accepts simple label conditions and rejects obviously
    broken ones.  Will be replaced by the full Epic 3 ``ConditionParser``.
    """

    _SIMPLE_LABELS = {"pass", "fail", "partial", "success", "error"}

    def parse(self, expression: str) -> None:
        """Raise ``_ParseError`` if *expression* is obviously malformed."""
        expr = expression.strip()
        if not expr:
            raise _ParseError("Empty condition expression")
        # Accept known simple labels
        if expr in self._SIMPLE_LABELS:
            return
        # Accept $-prefixed expressions (full parser will validate properly)
        if "$" in expr:
            return
        # Reject expressions with unbalanced delimiters
        if expr.count('"') % 2 != 0:
            raise _ParseError(f"Unbalanced quotes in condition: {expr!r}")
        if expr.count("(") != expr.count(")"):
            raise _ParseError(f"Unbalanced parentheses in condition: {expr!r}")


# Try to import the real condition validator; fall back to the stub parser.
try:
    from cobuilder.engine.conditions import validate_condition_syntax as _validate_condition_syntax
    from cobuilder.engine.conditions.parser import ConditionParser as _ConditionParser
    from cobuilder.engine.conditions.parser import ParseError as _RealParseError

    _CONDITION_PARSER_CLS = _ConditionParser
    _CONDITION_PARSE_ERROR = _RealParseError
    _HAS_REAL_VALIDATOR = True
except ImportError:
    _CONDITION_PARSER_CLS = _ConditionParserStub  # type: ignore[assignment]
    _CONDITION_PARSE_ERROR = _ParseError  # type: ignore[assignment]
    _HAS_REAL_VALIDATOR = False

    def _validate_condition_syntax(source: str):  # type: ignore[misc]
        """Stub fallback: returns (errors, warnings) like the real function."""
        parser = _ConditionParserStub()
        try:
            parser.parse(source)
            return [], []
        except _ParseError as exc:
            return [str(exc)], []


# ---------------------------------------------------------------------------
# StylesheetParser stub for Rule 8 (permissive until feature lands)
# ---------------------------------------------------------------------------

class _StylesheetParseError(Exception):
    """Stub parse error for the placeholder stylesheet parser."""


class _StylesheetParserStub:
    """Permissive stub: accepts any non-empty string, logs a debug message.
    Will be replaced when the model-stylesheet feature is implemented.
    """

    def parse(self, value: str) -> None:
        """Accept any non-empty stylesheet string without validation."""
        # Permissive stub — the real parser will enforce CSS-like syntax.
        return


try:
    from cobuilder.engine.stylesheet import StylesheetParser as _StylesheetParser
    from cobuilder.engine.stylesheet import StylesheetParseError as _StylesheetParseError  # type: ignore[assignment]

    _STYLESHEET_PARSER_CLS = _StylesheetParser
    _STYLESHEET_PARSE_ERROR = _StylesheetParseError
except ImportError:
    _STYLESHEET_PARSER_CLS = _StylesheetParserStub  # type: ignore[assignment]
    _STYLESHEET_PARSE_ERROR = _StylesheetParseError  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Registered shapes for Rule 10 (derived from SHAPE_TO_HANDLER)
# ---------------------------------------------------------------------------

KNOWN_SHAPES: frozenset[str] = frozenset(SHAPE_TO_HANDLER.keys())

# ---------------------------------------------------------------------------
# Rule 1: SingleStartNode
# ---------------------------------------------------------------------------

class SingleStartNode:
    """Exactly one ``Mdiamond`` (start) node must exist."""

    rule_id = "SingleStartNode"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        start_nodes = [n for n in graph.nodes.values() if n.is_start]
        if len(start_nodes) == 0:
            return [
                _error(
                    self.rule_id,
                    "No Mdiamond (start) node found in the graph.",
                    "Add a node with shape=Mdiamond as the pipeline entry point.",
                )
            ]
        if len(start_nodes) > 1:
            ids = [n.id for n in start_nodes]
            return [
                _error(
                    self.rule_id,
                    f"Multiple start nodes found: {ids}. Exactly one Mdiamond is required.",
                    "Add a node with `shape=Mdiamond` as the pipeline entry point.",
                    node_id=n.id,
                )
                for n in start_nodes
            ]
        return []


# ---------------------------------------------------------------------------
# Rule 2: AtLeastOneExit
# ---------------------------------------------------------------------------

class AtLeastOneExit:
    """At least one ``Msquare`` (exit) node must exist."""

    rule_id = "AtLeastOneExit"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        exit_nodes = [n for n in graph.nodes.values() if n.is_exit]
        if len(exit_nodes) == 0:
            return [
                _error(
                    self.rule_id,
                    "No Msquare (exit) node found in the graph.",
                    "Add a node with `shape=Msquare` as the pipeline terminal node.",
                )
            ]
        return []


# ---------------------------------------------------------------------------
# Rule 3: AllNodesReachable
# ---------------------------------------------------------------------------

class AllNodesReachable:
    """Every node must be reachable from the start node via directed BFS.

    Skips the check (returns empty) when ``SingleStartNode`` already detected
    zero start nodes, to avoid noise.
    """

    rule_id = "AllNodesReachable"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        start_nodes = [n for n in graph.nodes.values() if n.is_start]
        if not start_nodes:
            # SingleStartNode will report the missing start node; skip here.
            return []

        start_id = start_nodes[0].id
        reachable = _bfs_reachable(start_id, graph)

        violations = []
        for node in graph.nodes.values():
            if node.id not in reachable:
                violations.append(
                    _error(
                        self.rule_id,
                        "Node is unreachable from the start node. "
                        "Check for missing or misdirected incoming edges.",
                        "Add an incoming edge to this node from an appropriate predecessor, "
                        "or remove the node.",
                        node_id=node.id,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 4: EdgeTargetsExist
# ---------------------------------------------------------------------------

class EdgeTargetsExist:
    """Every edge's source and target node IDs must exist in the graph."""

    rule_id = "EdgeTargetsExist"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        node_ids = set(graph.nodes.keys())
        violations = []
        for edge in graph.edges:
            if edge.target not in node_ids:
                violations.append(
                    _error(
                        self.rule_id,
                        f"Edge target '{edge.target}' does not exist in the graph.",
                        "Check the node ID for typos; node IDs are case-sensitive.",
                        edge_src=edge.source,
                        edge_dst=edge.target,
                    )
                )
            if edge.source not in node_ids:
                violations.append(
                    _error(
                        self.rule_id,
                        f"Edge source '{edge.source}' does not exist in the graph.",
                        "Check the node ID for typos; node IDs are case-sensitive.",
                        edge_src=edge.source,
                        edge_dst=edge.target,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 5: StartNoIncoming
# ---------------------------------------------------------------------------

class StartNoIncoming:
    """The start node (``Mdiamond``) must have no incoming edges."""

    rule_id = "StartNoIncoming"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        start_nodes = [n for n in graph.nodes.values() if n.is_start]
        violations = []
        for start in start_nodes:
            incoming = graph.edges_to(start.id)
            if incoming:
                sources = [e.source for e in incoming]
                violations.append(
                    _error(
                        self.rule_id,
                        f"Start node has {len(incoming)} incoming edge(s) from: {sources}. "
                        "Start nodes must have no predecessors.",
                        "Remove the incoming edge to the start node. Use a distinct recovery "
                        "node as the retry target.",
                        node_id=start.id,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 6: ExitNoOutgoing
# ---------------------------------------------------------------------------

class ExitNoOutgoing:
    """Exit nodes (``Msquare``) must have no outgoing edges."""

    rule_id = "ExitNoOutgoing"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        exit_nodes = [n for n in graph.nodes.values() if n.is_exit]
        violations = []
        for exit_node in exit_nodes:
            outgoing = graph.edges_from(exit_node.id)
            if outgoing:
                targets = [e.target for e in outgoing]
                violations.append(
                    _error(
                        self.rule_id,
                        f"Exit node has {len(outgoing)} outgoing edge(s) to: {targets}. "
                        "Exit nodes must be terminal.",
                        "Remove outgoing edges from exit nodes. If the pipeline needs to "
                        "continue, use an intermediate node before the exit.",
                        node_id=exit_node.id,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 7: ConditionSyntaxValid
# ---------------------------------------------------------------------------

class ConditionSyntaxValid:
    """All edge ``condition=`` values must parse without error.

    Uses the real conditions package validator when available (Epic 3):
    - Parse errors → ERROR violation (blocks execution).
    - Bare-word deprecation warnings → WARNING violation (AMD-5).
    """

    rule_id = "ConditionSyntaxValid"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []
        for edge in graph.edges:
            # Unconditional edges (empty condition string) are always valid.
            if not edge.condition:
                continue

            errors, warnings = _validate_condition_syntax(edge.condition)

            for err in errors:
                violations.append(
                    _error(
                        self.rule_id,
                        f"Edge condition expression '{edge.condition}' failed to parse: {err}",
                        "Review the condition expression syntax. Variables use `$` prefix; "
                        "operators are `=`, `!=`, `<`, `>`, `<=`, `>=`; "
                        "connectives are `&&`, `||`, `!`.",
                        edge_src=edge.source,
                        edge_dst=edge.target,
                    )
                )
            for warn in warnings:
                violations.append(
                    _warning(
                        self.rule_id,
                        f"Edge condition '{edge.condition}' uses unquoted bare-word string "
                        f"(deprecated, AMD-5): {warn}",
                        "Use quoted strings for clarity: e.g. `$status = \"success\"` "
                        "instead of `$status = success`.",
                        edge_src=edge.source,
                        edge_dst=edge.target,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 8: StylesheetSyntaxValid
# ---------------------------------------------------------------------------

class StylesheetSyntaxValid:
    """``model_stylesheet`` attribute values must be syntactically valid.

    Currently uses a permissive stub parser (accepts any non-empty string)
    until the model stylesheet feature is implemented.
    """

    rule_id = "StylesheetSyntaxValid"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        stylesheet_parser = _STYLESHEET_PARSER_CLS()
        violations = []

        # Per-node model_stylesheet attribute
        for node in graph.nodes.values():
            stylesheet = node.attrs.get("model_stylesheet")
            if not stylesheet:
                continue
            try:
                stylesheet_parser.parse(stylesheet)
            except _STYLESHEET_PARSE_ERROR as exc:
                violations.append(
                    _error(
                        self.rule_id,
                        f"model_stylesheet value failed to parse: {exc}",
                        "Check model_stylesheet syntax. Format: "
                        "`selector { llm_model: model-name; }`. "
                        "Valid selectors: `*` (all nodes), `.class-name`, `#node-id`.",
                        node_id=node.id,
                    )
                )

        # Graph-level model_stylesheet attribute
        graph_stylesheet = graph.attrs.get("model_stylesheet")
        if graph_stylesheet:
            try:
                stylesheet_parser.parse(graph_stylesheet)
            except _STYLESHEET_PARSE_ERROR as exc:
                violations.append(
                    _error(
                        self.rule_id,
                        f"Graph-level model_stylesheet failed to parse: {exc}",
                        "Check model_stylesheet syntax. Format: "
                        "`selector { llm_model: model-name; }`. "
                        "Valid selectors: `*` (all nodes), `.class-name`, `#node-id`.",
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 9: RetryTargetsExist
# ---------------------------------------------------------------------------

class RetryTargetsExist:
    """All ``retry_target`` node ID references must exist in the graph."""

    rule_id = "RetryTargetsExist"
    severity = Severity.ERROR

    def check(self, graph: Graph) -> list[RuleViolation]:
        node_ids = set(graph.nodes.keys())
        violations = []

        # Per-node retry_target
        for node in graph.nodes.values():
            retry_target = node.attrs.get("retry_target")
            if retry_target and retry_target not in node_ids:
                violations.append(
                    _error(
                        self.rule_id,
                        f"retry_target='{retry_target}' does not exist in the graph.",
                        "Check the retry_target value for typos. Node IDs are "
                        "case-sensitive and must match exactly.",
                        node_id=node.id,
                    )
                )

        # Graph-level retry_target and fallback_retry_target
        for attr_name in ("retry_target", "fallback_retry_target"):
            value = graph.attrs.get(attr_name)
            if value and value not in node_ids:
                violations.append(
                    _error(
                        self.rule_id,
                        f"Graph-level {attr_name}='{value}' does not exist in the graph.",
                        "Check the retry_target value for typos. Node IDs are "
                        "case-sensitive and must match exactly.",
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 10: NodeTypesKnown (WARNING)
# ---------------------------------------------------------------------------

class NodeTypesKnown:
    """All node shapes should map to a registered handler.

    Unknown shapes produce a WARNING — execution is not blocked because
    the engine's handler registry returns a ``GenericHandler`` fallback.
    """

    rule_id = "NodeTypesKnown"
    severity = Severity.WARNING

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []
        for node in graph.nodes.values():
            if node.shape not in KNOWN_SHAPES:
                violations.append(
                    _warning(
                        self.rule_id,
                        f"Shape '{node.shape}' is not registered in the handler registry. "
                        "The node will execute with GenericHandler (no-op).",
                        f"Use one of the registered shapes: "
                        f"{', '.join(sorted(KNOWN_SHAPES))}.",
                        node_id=node.id,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 11: FidelityValuesValid (WARNING)
# ---------------------------------------------------------------------------

VALID_FIDELITY: frozenset[str] = frozenset({"full", "checkpoint"})


class FidelityValuesValid:
    """The ``fidelity`` attribute, when present, must be ``full`` or ``checkpoint``.

    An unrecognised value silently falls back to ``checkpoint`` in the engine,
    which may cause unexpected context reconstruction behaviour.
    """

    rule_id = "FidelityValuesValid"
    severity = Severity.WARNING

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []
        for node in graph.nodes.values():
            fidelity = node.attrs.get("fidelity")
            if fidelity is not None and fidelity not in VALID_FIDELITY:
                violations.append(
                    _warning(
                        self.rule_id,
                        f"fidelity='{fidelity}' is not a recognised value. "
                        f"Valid values: {sorted(VALID_FIDELITY)}. "
                        "Defaulting to 'checkpoint'.",
                        "Set fidelity to 'full' (inject complete conversation history on "
                        "resume) or 'checkpoint' (inject summary only).",
                        node_id=node.id,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 12: GoalGatesHaveRetry (WARNING)
# ---------------------------------------------------------------------------

class GoalGatesHaveRetry:
    """Nodes with ``goal_gate=true`` should have a retry path.

    If the goal gate check fails and the node has no ``retry_target``
    (node-level or graph-level), the engine must abort with no recovery.
    """

    rule_id = "GoalGatesHaveRetry"
    severity = Severity.WARNING

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []
        has_graph_retry = bool(graph.attrs.get("retry_target"))
        has_fallback = bool(graph.attrs.get("fallback_retry_target"))

        for node in graph.nodes.values():
            if not node.goal_gate:
                continue
            has_node_retry = bool(node.attrs.get("retry_target"))
            if not (has_node_retry or has_graph_retry or has_fallback):
                violations.append(
                    _warning(
                        self.rule_id,
                        "Node has goal_gate=true but no retry_target is defined. "
                        "If the goal gate check fails, the pipeline will abort "
                        "with no recovery path.",
                        "Add `retry_target=<node_id>` to the node, or add a "
                        "`retry_target` attribute to the graph-level attributes block.",
                        node_id=node.id,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Rule 13: LlmNodesHavePrompts (WARNING)
# ---------------------------------------------------------------------------

class LlmNodesHavePrompts:
    """LLM-invoking nodes should have a non-empty ``prompt`` or ``label``.

    Nodes whose shapes are in ``LLM_NODE_SHAPES`` (``box``, ``tab``) invoke
    the LLM.  A node with neither attribute will invoke the handler with an
    empty instruction, producing useless or confusing output.
    """

    rule_id = "LlmNodesHavePrompts"
    severity = Severity.WARNING

    def check(self, graph: Graph) -> list[RuleViolation]:
        violations = []
        for node in graph.nodes.values():
            if node.shape not in LLM_NODE_SHAPES:
                continue
            has_prompt = bool(node.attrs.get("prompt", "").strip())
            has_label = bool(node.label.strip())
            if not has_prompt and not has_label:
                violations.append(
                    _warning(
                        self.rule_id,
                        f"LLM node (shape='{node.shape}') has neither 'prompt' nor "
                        "'label' attribute. The handler will invoke the LLM with an "
                        "empty instruction.",
                        "Add a `prompt=` attribute describing the task for the LLM, or "
                        "ensure the `label=` attribute is descriptive enough to serve "
                        "as the instruction.",
                        node_id=node.id,
                    )
                )
        return violations


# ---------------------------------------------------------------------------
# Exported rule names
# ---------------------------------------------------------------------------

__all__ = [
    "Rule",
    # Error-level
    "SingleStartNode",
    "AtLeastOneExit",
    "AllNodesReachable",
    "EdgeTargetsExist",
    "StartNoIncoming",
    "ExitNoOutgoing",
    "ConditionSyntaxValid",
    "StylesheetSyntaxValid",
    "RetryTargetsExist",
    # Warning-level
    "NodeTypesKnown",
    "FidelityValuesValid",
    "GoalGatesHaveRetry",
    "LlmNodesHavePrompts",
    # Constants
    "KNOWN_SHAPES",
    "VALID_FIDELITY",
]
