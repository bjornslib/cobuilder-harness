---
title: "Solution Design: Pre-Execution Validation Suite (Epic 2 — PRD-PIPELINE-ENGINE-001)"
status: active
type: solution-design
last_verified: 2026-03-04T00:00:00.000Z
grade: authoritative
implementation_status: complete
---
# SD-PIPELINE-ENGINE-001-epic2-validation

> **Implementation Status**: COMPLETE (2026-03-04)
> - **Code**: 1,107 LOC in `cobuilder/engine/validation/` (rules.py, validator.py)
> - **Tests**: 52 tests (51 passing, 1 failure)
> - **Rules**: All 13 rules implemented — 9 error-level, 4 warning-level
> - **CLI**: `cobuilder pipeline validate` fully integrated
> - **Known Issues**: 1 test failure in `ConditionSyntaxValid` rule — edge case with simple labels that don't contain condition expressions

## Pre-Execution Validation Suite — Solution Design

**PRD Reference**: PRD-PIPELINE-ENGINE-001 §5 (Epic 2)
**Epic Goal**: 13-rule validation pass that catches structural errors before the engine burns any LLM tokens.
**Primary Research Reference**: `attractor-rb` (aliciapaz/attractor-rb) — most comprehensive validation implementation across 10 community Attractor ports.

---

## 1. Business Context

### Why This Epic Exists

The pipeline execution engine (Epic 1) spawns orchestrators via tmux and invokes LLM calls. A single corrupted DOT file can silently consume tokens, leave dangling tmux sessions, and produce no useful output. The cost of a malformed graph is not just wasted tokens — it is wasted human attention and broken pipeline state that must be manually cleaned up.

The pre-execution validation suite is a defensive gate that runs before any handler is invoked, before any tmux session is created, and before any LLM API call is made. It is the cheapest possible failure mode.

### Relationship to Existing Validation

The existing `cobuilder/pipeline/validator.py` implements 11 project-specific rules oriented around the current DOT schema (handler attributes, worker types, promise IDs). Those rules are retained as-is and remain in `cobuilder/pipeline/` for use by the pipeline management CLI.

The new validation suite in `cobuilder/engine/validation/` implements the 13 attractor-spec rules that the execution engine requires for safe graph traversal. These are structurally distinct:

| Dimension | Existing (`pipeline/validator.py`) | New (`engine/validation/`) |
| --- | --- | --- |
| Purpose | Schema conformance for pipeline authoring | Structural safety for autonomous execution |
| Rules | 11 project-specific (handler attrs, worker types) | 13 execution-safety rules (graph topology) |
| Invoked by | `python cli.py validate <file>` (manual) | Engine automatically, before every run |
| Failure mode | Print issues, exit 1 | Raise `ValidationError`, block execution |
| Skip flag | N/A | `--skip-validation` (emergency bypass only) |

The two validators are complementary. The authoring validator catches DOT authoring mistakes; the execution validator catches graph topology mistakes that would cause the engine to deadlock, loop infinitely, or dereference non-existent nodes.

### User-Facing Value

From PRD US-4: "As any user, I want `cobuilder pipeline validate pipeline.dot` to run 13 structural checks before the engine burns any LLM tokens, so that I catch graph authoring mistakes early."

---

## 2. Technical Architecture

### Component Map

```
cobuilder/engine/validation/
├── __init__.py          # Public API: validate_graph(), ValidationResult
├── rules.py             # 13 rule implementations as Rule protocol subclasses
└── validator.py         # Validator: rule runner, reporter, CLI entry point
```

The validation module depends only on the graph model from `cobuilder/engine/graph.py` (Node, Edge, Graph dataclasses). It has no dependency on handlers, the event bus, middleware, or any LLM client.

### Dependency Graph

```
cobuilder/engine/validation/
    │
    ├── depends on: cobuilder/engine/graph.py   (Node, Edge, Graph types)
    ├── depends on: cobuilder/engine/conditions/ (ConditionSyntaxValid rule only)
    │
    ├── consumed by: cobuilder/engine/runner.py  (auto-validate before execution)
    └── consumed by: cobuilder/pipeline/cli.py   (validate subcommand)
```

### Integration with the Execution Engine

The runner (`cobuilder/engine/runner.py`) calls validation as step 2 of the 5-step startup sequence:

```
cobuilder pipeline run pipeline.dot
  │
  ├── 1. PARSE ──────── parser.py → Graph
  ├── 2. VALIDATE ───── engine/validation/validator.py → ValidationResult
  │       ├── ERRORS?  → raise ValidationError, exit non-zero, print report
  │       └── WARNINGS? → log warnings, continue execution
  ├── 3. INITIALIZE ─── context, emitter, middleware chain
  ├── 4. EXECUTE ─────── traversal loop
  └── 5. FINALIZE ────── goal gate, checkpoint, completion event
```

The validation step emits two events from the Epic 4 event bus:
- `validation.started` — before any rule runs
- `validation.completed` — after all rules run, carries result summary

### Integration with the CLI

The `cobuilder pipeline validate` CLI subcommand calls the same `Validator.run()` method but renders results as human-readable terminal output (or JSON with `--output json`). It exits with code 0 if no errors, 1 if any errors, 2 if the DOT file cannot be parsed.

```
cobuilder/pipeline/cli.py
    └── "validate" subcommand
            └── imports cobuilder.engine.validation.validator.Validator
                └── calls Validator(graph).run()
                └── renders ValidationResult to terminal
```

---

## 3. Data Models

### Graph Input Types

The validator consumes the `Graph` type from `cobuilder/engine/graph.py`. The relevant fields are:

```python
# cobuilder/engine/graph.py  (defined in Epic 1 — consumed here)
from dataclasses import dataclass, field
from typing import Any

@dataclass
class Node:
    id: str
    shape: str                       # "Mdiamond", "Msquare", "box", "diamond", etc.
    attrs: dict[str, Any]            # All DOT attributes verbatim
    # Convenience accessors (populated by parser):
    prompt: str | None = None        # node prompt= attribute
    goal_gate: bool = False          # goal_gate="true"
    retry_target: str | None = None  # retry_target= attribute
    fidelity: str | None = None      # fidelity= attribute
    handler_type: str | None = None  # resolved handler class name

@dataclass
class Edge:
    src: str
    dst: str
    attrs: dict[str, Any]
    # Convenience accessors:
    condition: str | None = None     # condition= expression string
    label: str | None = None         # label= display text
    weight: float | None = None      # weight= numeric

@dataclass
class Graph:
    name: str
    nodes: list[Node]
    edges: list[Edge]
    graph_attrs: dict[str, Any]
    # Computed adjacency (populated by Graph.__post_init__):
    node_map: dict[str, Node] = field(default_factory=dict)
    adj: dict[str, list[str]] = field(default_factory=dict)    # node_id -> [neighbor_ids]
    in_adj: dict[str, list[str]] = field(default_factory=dict) # node_id -> [predecessor_ids]
```

### Validation Output Types

```python
# cobuilder/engine/validation/__init__.py

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class Severity(str, Enum):
    ERROR = "error"      # Blocks execution
    WARNING = "warning"  # Logged, execution continues


@dataclass(frozen=True)
class RuleViolation:
    """A single rule check failure."""
    rule_id: str          # e.g. "SingleStartNode", "AllNodesReachable"
    severity: Severity    # ERROR or WARNING
    message: str          # Human-readable description of the problem
    node_id: str | None   # Which node triggered the violation (None for graph-level)
    edge_src: str | None  # Which edge triggered the violation (None if not edge-related)
    edge_dst: str | None  # Target of offending edge
    fix_hint: str         # One-sentence fix suggestion

    def __str__(self) -> str:
        loc = ""
        if self.node_id:
            loc = f" [node:{self.node_id}]"
        elif self.edge_src and self.edge_dst:
            loc = f" [edge:{self.edge_src}->{self.edge_dst}]"
        return (
            f"  {self.severity.value.upper():7s} [{self.rule_id}]{loc}: "
            f"{self.message}\n"
            f"          Fix: {self.fix_hint}"
        )


@dataclass
class ValidationResult:
    """Aggregate result from a full validation run."""
    pipeline_id: str                           # DOT graph name
    violations: list[RuleViolation] = field(default_factory=list)

    @property
    def errors(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[RuleViolation]:
        return [v for v in self.violations if v.severity == Severity.WARNING]

    @property
    def is_valid(self) -> bool:
        """True when no ERROR-level violations exist."""
        return len(self.errors) == 0

    def to_dict(self) -> dict:
        return {
            "pipeline_id": self.pipeline_id,
            "valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity.value,
                    "message": v.message,
                    "node_id": v.node_id,
                    "edge_src": v.edge_src,
                    "edge_dst": v.edge_dst,
                    "fix_hint": v.fix_hint,
                }
                for v in self.violations
            ],
        }


class ValidationError(Exception):
    """Raised by the engine when ERROR-level violations block execution."""
    def __init__(self, result: ValidationResult):
        self.result = result
        error_count = len(result.errors)
        super().__init__(
            f"Pipeline '{result.pipeline_id}' failed validation with "
            f"{error_count} error(s). Run 'cobuilder pipeline validate "
            f"<file>.dot' for details."
        )
```

---

## 4. API Contracts

### Rule Protocol

Every rule is a single-responsibility class implementing the `Rule` protocol. Rules are stateless — they receive the graph at call time and return a list of violations (empty list means the rule passed).

```python
# cobuilder/engine/validation/rules.py

from typing import Protocol, runtime_checkable
from cobuilder.engine.graph import Graph
from cobuilder.engine.validation import RuleViolation


@runtime_checkable
class Rule(Protocol):
    """Protocol that all 13 validation rules must implement."""

    rule_id: str       # Class-level string constant, e.g. "SingleStartNode"
    severity: Severity # Class-level default severity (ERROR or WARNING)

    def check(self, graph: Graph) -> list[RuleViolation]:
        """Run this rule against graph and return any violations found.

        Returns:
            Empty list if the rule passes.
            One or more RuleViolation objects if violations are found.
            A single rule may produce multiple violations (e.g. AllNodesReachable
            produces one violation per unreachable node).
        """
        ...
```

### Validator Interface

```python
# cobuilder/engine/validation/validator.py

from cobuilder.engine.graph import Graph
from cobuilder.engine.validation import ValidationResult, ValidationError
from cobuilder.engine.validation.rules import (
    SingleStartNode, AtLeastOneExit, AllNodesReachable, EdgeTargetsExist,
    StartNoIncoming, ExitNoOutgoing, ConditionSyntaxValid,
    StylesheetSyntaxValid, RetryTargetsExist,
    NodeTypesKnown, FidelityValuesValid, GoalGatesHaveRetry,
    LlmNodesHavePrompts,
)


# Canonical rule ordering — error rules first, then warning rules
DEFAULT_RULES: list[type[Rule]] = [
    # Error-level (indices 1-9, block execution)
    SingleStartNode,
    AtLeastOneExit,
    AllNodesReachable,
    EdgeTargetsExist,
    StartNoIncoming,
    ExitNoOutgoing,
    ConditionSyntaxValid,
    StylesheetSyntaxValid,
    RetryTargetsExist,
    # Warning-level (indices 10-13, advisory)
    NodeTypesKnown,
    FidelityValuesValid,
    GoalGatesHaveRetry,
    LlmNodesHavePrompts,
]


class Validator:
    """Runs the full validation suite against a parsed Graph."""

    def __init__(
        self,
        graph: Graph,
        rules: list[type[Rule]] | None = None,
    ) -> None:
        """
        Args:
            graph: Parsed and post-initialized Graph object.
            rules: Override the default rule set (useful for testing
                   individual rules). Defaults to DEFAULT_RULES.
        """
        self.graph = graph
        self.rules = [cls() for cls in (rules or DEFAULT_RULES)]

    def run(self) -> ValidationResult:
        """Execute all rules and return a ValidationResult.

        Rules run in order. All rules run even when early rules fail,
        so the caller gets a complete picture of all violations.

        Returns:
            ValidationResult with all violations across all rules.
        """
        result = ValidationResult(pipeline_id=self.graph.name)
        for rule in self.rules:
            violations = rule.check(self.graph)
            result.violations.extend(violations)
        return result

    def run_or_raise(self) -> ValidationResult:
        """Execute all rules; raise ValidationError if any errors found.

        Used by the engine runner to block execution on ERROR violations.
        WARNING violations are present in the result but do not raise.

        Raises:
            ValidationError: If result.is_valid is False.
        """
        result = self.run()
        if not result.is_valid:
            raise ValidationError(result)
        return result
```

---

## 5. Functional Decomposition: The 13 Rules

Each rule section below specifies: purpose, algorithm, violations produced, and acceptance criteria for that rule.

---

### Rule 1: SingleStartNode (ERROR)

**Purpose**: Exactly one `Mdiamond` node must exist. The engine's traversal starts at the unique start node; zero start nodes means no entry point, multiple start nodes means ambiguous entry.

**Algorithm**:
```python
start_nodes = [n for n in graph.nodes if n.shape == "Mdiamond"]
if len(start_nodes) == 0:
    yield violation("No Mdiamond (start) node found. Add a node with shape=Mdiamond.")
elif len(start_nodes) > 1:
    for n in start_nodes:
        yield violation(f"Multiple start nodes found: {[n.id for n in start_nodes]}. "
                       "Exactly one Mdiamond is required.", node_id=n.id)
```

**Violations produced**: 1 violation (zero start nodes) or N violations (one per extra start node).

**Acceptance Criteria**:
- Graph with exactly 1 `Mdiamond` → no violations
- Graph with 0 `Mdiamond` → 1 ERROR: "No Mdiamond (start) node found"
- Graph with 2 `Mdiamond` → 1 ERROR referencing both node IDs
- Fix hint: "Add a node with `shape=Mdiamond` as the pipeline entry point."

---

### Rule 2: AtLeastOneExit (ERROR)

**Purpose**: At least one `Msquare` node must exist. The engine traverses until it reaches an exit node; a pipeline with no exit node will loop or halt on a fatal error without a natural termination condition.

**Algorithm**:
```python
exit_nodes = [n for n in graph.nodes if n.shape == "Msquare"]
if len(exit_nodes) == 0:
    yield violation("No Msquare (exit) node found. Add at least one exit node.")
```

**Note**: Multiple exit nodes are valid (e.g., success path and failure path each terminate at distinct exit nodes). The rule only enforces a minimum of one.

**Violations produced**: 0 or 1.

**Acceptance Criteria**:
- Graph with 1 `Msquare` → no violations
- Graph with 2 `Msquare` → no violations (multi-exit pipelines are valid)
- Graph with 0 `Msquare` → 1 ERROR
- Fix hint: "Add a node with `shape=Msquare` as the pipeline terminal node."

---

### Rule 3: AllNodesReachable (ERROR)

**Purpose**: Every node in the graph must be reachable from the start node via directed BFS. Unreachable nodes indicate dead graph sections that will never execute — these are authoring errors (deleted edges, copy-paste mistakes).

**Algorithm**:
```python
if not start_nodes:
    return []  # SingleStartNode will report this; skip to avoid noise
reachable = bfs(start=start_node.id, adjacency=graph.adj)
for node in graph.nodes:
    if node.id not in reachable:
        yield violation(
            f"Node is unreachable from start. Check for missing incoming edges.",
            node_id=node.id
        )
```

**Violations produced**: One per unreachable node.

**Acceptance Criteria**:
- Linear pipeline (A→B→C) → no violations
- Pipeline with isolated node D → 1 ERROR on D
- Pipeline with branch where one branch has a missing edge → ERROR on the disconnected subtree
- When `SingleStartNode` also fails (no start node), `AllNodesReachable` returns empty list to suppress noise
- Fix hint: "Add an incoming edge to this node from an appropriate predecessor, or remove the node."

---

### Rule 4: EdgeTargetsExist (ERROR)

**Purpose**: Every edge's `dst` node ID must reference a node that exists in the graph. A missing target causes the engine to dereference a `None` node and crash during traversal.

**Algorithm**:
```python
node_ids = {n.id for n in graph.nodes}
for edge in graph.edges:
    if edge.dst not in node_ids:
        yield violation(
            f"Edge target '{edge.dst}' does not exist in the graph.",
            edge_src=edge.src, edge_dst=edge.dst
        )
    if edge.src not in node_ids:
        yield violation(
            f"Edge source '{edge.src}' does not exist in the graph.",
            edge_src=edge.src, edge_dst=edge.dst
        )
```

**Violations produced**: One per dangling edge endpoint.

**Acceptance Criteria**:
- All edges reference existing nodes → no violations
- Edge `A -> nonexistent` → 1 ERROR naming the missing target ID
- Edge `nonexistent -> B` → 1 ERROR naming the missing source ID
- Fix hint: "Check the node ID for typos; node IDs are case-sensitive."

---

### Rule 5: StartNoIncoming (ERROR)

**Purpose**: The start node (`Mdiamond`) must have no incoming edges. An incoming edge to the start node creates an implicit cycle and makes the pipeline's entry point ambiguous.

**Algorithm**:
```python
for start in start_nodes:
    incoming = graph.in_adj.get(start.id, [])
    if incoming:
        yield violation(
            f"Start node has {len(incoming)} incoming edge(s) from: {incoming}. "
            "Start nodes must have no predecessors.",
            node_id=start.id
        )
```

**Violations produced**: 0 or 1 per start node.

**Acceptance Criteria**:
- Start node with no incoming edges → no violations
- Start node with 1 incoming edge (e.g., retry loop back to start) → 1 ERROR
- Fix hint: "Remove the incoming edge to the start node. Use a distinct recovery node as the retry target."

---

### Rule 6: ExitNoOutgoing (ERROR)

**Purpose**: Exit nodes (`Msquare`) must have no outgoing edges. An outgoing edge from an exit node would require the engine to continue traversal after declaring completion — contradictory behavior.

**Algorithm**:
```python
for exit_node in exit_nodes:
    outgoing = graph.adj.get(exit_node.id, [])
    if outgoing:
        yield violation(
            f"Exit node has {len(outgoing)} outgoing edge(s) to: {outgoing}. "
            "Exit nodes must be terminal.",
            node_id=exit_node.id
        )
```

**Violations produced**: 0 or 1 per exit node.

**Acceptance Criteria**:
- Exit node with no outgoing edges → no violations
- Exit node with 1 outgoing edge → 1 ERROR
- Fix hint: "Remove outgoing edges from exit nodes. If the pipeline needs to continue, use an intermediate node before the exit."

---

### Rule 7: ConditionSyntaxValid (ERROR)

**Purpose**: All edge `condition=` attribute values must parse without error using the Epic 3 condition expression parser. Invalid condition syntax will crash the engine during edge selection at runtime — catching this during validation prevents token waste.

**Algorithm**:
```python
from cobuilder.engine.conditions.parser import ConditionParser, ParseError

parser = ConditionParser()
for edge in graph.edges:
    if edge.condition is None:
        continue  # Unconditional edges are valid
    try:
        parser.parse(edge.condition)
    except ParseError as exc:
        yield violation(
            f"Edge condition expression '{edge.condition}' failed to parse: {exc}",
            edge_src=edge.src, edge_dst=edge.dst
        )
```

**Dependency note**: This rule imports `cobuilder.engine.conditions.parser` (Epic 3). During the interim before Epic 3 is implemented, this rule uses a lightweight placeholder parser that accepts the simple `pass`/`fail`/`partial` literals and rejects obviously malformed strings. The rule is designed so the placeholder can be swapped for the full parser without changing the rule implementation.

**Violations produced**: One per unparseable condition expression.

**Acceptance Criteria**:
- Edge with `condition="pass"` → no violations
- Edge with `condition="$retry_count < 3 && $status = success"` → no violations (full parser)
- Edge with `condition="$retry_count <"` (incomplete expression) → 1 ERROR with parse error detail
- Edge with no `condition` attribute → no violations (unconditional edges are valid)
- Fix hint: "Review the condition expression syntax. Variables use `$` prefix; operators are `=`, `!=`, `<`, `>`, `<=`, `>=`; connectives are `&&`, `||`, `!`."

---

### Rule 8: StylesheetSyntaxValid (ERROR)

**Purpose**: If a `model_stylesheet` attribute is present on any node, its value must be syntactically valid CSS-like model routing syntax. Invalid stylesheets cause model selection to fail silently or crash.

**Algorithm**:
```python
from cobuilder.engine.stylesheet import StylesheetParser, StylesheetParseError

stylesheet_parser = StylesheetParser()
for node in graph.nodes:
    stylesheet = node.attrs.get("model_stylesheet")
    if not stylesheet:
        # Check graph-level stylesheet too
        continue
    try:
        stylesheet_parser.parse(stylesheet)
    except StylesheetParseError as exc:
        yield violation(
            f"model_stylesheet value failed to parse: {exc}",
            node_id=node.id
        )

# Also check graph-level stylesheet attribute
graph_stylesheet = graph.graph_attrs.get("model_stylesheet")
if graph_stylesheet:
    try:
        stylesheet_parser.parse(graph_stylesheet)
    except StylesheetParseError as exc:
        yield violation(
            f"Graph-level model_stylesheet failed to parse: {exc}"
        )
```

**Scope note**: The PRD marks CSS-like model stylesheets as out of scope for the initial delivery (Section 10). This rule is implemented but its `StylesheetParser` dependency uses a permissive stub that accepts any non-empty string and logs a debug message. When the stylesheet feature is implemented, the stub is replaced with the real parser without changing this rule.

**Violations produced**: One per unparseable stylesheet value.

**Acceptance Criteria**:
- Node with no `model_stylesheet` attribute → no violations
- Node with valid stylesheet value → no violations
- Node with malformed stylesheet → 1 ERROR
- Fix hint: "Check model_stylesheet syntax. Format: `selector { llm_model: model-name; }`. Valid selectors: `*` (all nodes), `.class-name`, `#node-id`."

---

### Rule 9: RetryTargetsExist (ERROR)

**Purpose**: If a node has a `retry_target` attribute, the referenced node ID must exist in the graph. A dangling retry target causes the engine to crash during goal gate failure recovery.

**Algorithm**:
```python
node_ids = {n.id for n in graph.nodes}

# Check node-level retry_target
for node in graph.nodes:
    retry_target = node.attrs.get("retry_target")
    if retry_target and retry_target not in node_ids:
        yield violation(
            f"retry_target='{retry_target}' does not exist in the graph.",
            node_id=node.id
        )

# Check graph-level retry_target and fallback_retry_target
for attr_name in ("retry_target", "fallback_retry_target"):
    value = graph.graph_attrs.get(attr_name)
    if value and value not in node_ids:
        yield violation(
            f"Graph-level {attr_name}='{value}' does not exist in the graph."
        )
```

**Violations produced**: One per dangling retry target reference.

**Acceptance Criteria**:
- Node with `retry_target="impl_auth"` where `impl_auth` exists → no violations
- Node with `retry_target="nonexistent_node"` → 1 ERROR naming the missing node
- Graph with `retry_target="nonexistent"` graph attribute → 1 ERROR
- Node with no `retry_target` attribute → no violations
- Fix hint: "Check the retry_target value for typos. Node IDs are case-sensitive and must match exactly."

---

### Rule 10: NodeTypesKnown (WARNING)

**Purpose**: All node shapes should map to registered handlers. Unknown shapes produce a warning — execution is not blocked because the engine's handler registry returns a `GenericHandler` for unrecognized shapes rather than crashing. The warning alerts the author that a node will be executed with fallback behavior.

**Algorithm**:
```python
KNOWN_SHAPES = {
    "Mdiamond", "Msquare", "box", "hexagon", "diamond",
    "parallelogram", "component", "tripleoctagon", "house"
}

for node in graph.nodes:
    if node.shape not in KNOWN_SHAPES:
        yield warning_violation(
            f"Shape '{node.shape}' is not registered in the handler registry. "
            "The node will execute with GenericHandler (no-op).",
            node_id=node.id
        )
```

**Violations produced**: One WARNING per unrecognized shape.

**Acceptance Criteria**:
- Node with `shape=box` → no violations
- Node with `shape=unknown_shape` → 1 WARNING (not ERROR)
- Execution is NOT blocked by this warning
- Fix hint: "Use one of the registered shapes: Mdiamond, Msquare, box, hexagon, diamond, parallelogram, component, tripleoctagon, house."

---

### Rule 11: FidelityValuesValid (WARNING)

**Purpose**: The `fidelity` attribute, when present, controls context reconstruction on resume (full vs checkpoint). Only the values `full` and `checkpoint` are recognized. An unrecognized value falls back to `checkpoint` silently, which could cause unexpected behavior.

**Algorithm**:
```python
VALID_FIDELITY = {"full", "checkpoint"}

for node in graph.nodes:
    fidelity = node.attrs.get("fidelity")
    if fidelity is not None and fidelity not in VALID_FIDELITY:
        yield warning_violation(
            f"fidelity='{fidelity}' is not a recognized value. "
            f"Valid values: {sorted(VALID_FIDELITY)}. Defaulting to 'checkpoint'.",
            node_id=node.id
        )
```

**Violations produced**: One WARNING per invalid fidelity value.

**Acceptance Criteria**:
- Node with `fidelity=full` → no violations
- Node with `fidelity=checkpoint` → no violations
- Node with no `fidelity` attribute → no violations (attribute is optional)
- Node with `fidelity=partial` → 1 WARNING
- Fix hint: "Set fidelity to 'full' (inject complete conversation history on resume) or 'checkpoint' (inject summary only)."

---

### Rule 12: GoalGatesHaveRetry (WARNING)

**Purpose**: Nodes marked `goal_gate=true` are critical quality gates. If the goal gate check fails during exit processing and the node has no `retry_target`, the engine has no recovery path and must abort. This is a recoverable authoring omission (the author can add a retry target), so it is a WARNING.

**Algorithm**:
```python
for node in graph.nodes:
    if not node.goal_gate:
        continue
    has_node_retry = bool(node.attrs.get("retry_target"))
    has_graph_retry = bool(graph.graph_attrs.get("retry_target"))
    has_fallback = bool(graph.graph_attrs.get("fallback_retry_target"))
    if not (has_node_retry or has_graph_retry or has_fallback):
        yield warning_violation(
            f"Node has goal_gate=true but no retry_target defined. "
            "If the goal gate check fails, the pipeline will abort with no recovery path.",
            node_id=node.id
        )
```

**Violations produced**: One WARNING per goal gate node lacking any retry target.

**Acceptance Criteria**:
- Goal gate node with `retry_target="impl_auth"` → no violations
- Goal gate node with no `retry_target` but graph has `retry_target` → no violations
- Goal gate node with no `retry_target` and graph has no `retry_target` → 1 WARNING
- Non-goal-gate nodes → no violations regardless of retry_target presence
- Fix hint: "Add `retry_target=<node_id>` to the node, or add a `retry_target` attribute to the graph-level attributes block."

---

### Rule 13: LlmNodesHavePrompts (WARNING)

**Purpose**: `box` nodes (codergen handler — LLM invocation) should have a non-empty `prompt` or `label` attribute. A box node with no prompt will invoke the handler with an empty instruction, producing useless or confusing LLM output.

**Algorithm**:
```python
for node in graph.nodes:
    if node.shape != "box":
        continue
    has_prompt = bool(node.attrs.get("prompt", "").strip())
    has_label = bool(node.attrs.get("label", "").strip())
    if not has_prompt and not has_label:
        yield warning_violation(
            f"LLM node (box) has neither 'prompt' nor 'label' attribute. "
            "The handler will invoke the LLM with an empty instruction.",
            node_id=node.id
        )
```

**Violations produced**: One WARNING per prompt-less box node.

**Acceptance Criteria**:
- Box node with `prompt="Implement the authentication module"` → no violations
- Box node with `label="impl_auth"` and no `prompt` → no violations (label used as fallback instruction)
- Box node with neither `prompt` nor `label` → 1 WARNING
- Non-box nodes (diamond, hexagon, etc.) → no violations regardless of prompt presence
- Fix hint: "Add a `prompt=` attribute describing the task for the LLM, or ensure the `label=` attribute is descriptive enough to serve as the instruction."

---

## 6. Full Rule Table

| # | Rule ID | Severity | Checks | Primary Data |
| --- | --- | --- | --- | --- |
| 1 | `SingleStartNode` | ERROR | Exactly one `Mdiamond` | `node.shape` |
| 2 | `AtLeastOneExit` | ERROR | At least one `Msquare` | `node.shape` |
| 3 | `AllNodesReachable` | ERROR | BFS from start covers all nodes | `graph.adj` |
| 4 | `EdgeTargetsExist` | ERROR | `edge.src` and `edge.dst` in node set | `graph.nodes`, `graph.edges` |
| 5 | `StartNoIncoming` | ERROR | `Mdiamond` has no predecessors | `graph.in_adj` |
| 6 | `ExitNoOutgoing` | ERROR | `Msquare` has no successors | `graph.adj` |
| 7 | `ConditionSyntaxValid` | ERROR | `edge.condition` parses without error | `edge.condition`, Epic 3 parser |
| 8 | `StylesheetSyntaxValid` | ERROR | `model_stylesheet` parses correctly | `node.attrs`, `graph.graph_attrs` |
| 9 | `RetryTargetsExist` | ERROR | `retry_target` IDs exist in graph | `node.attrs`, `graph.graph_attrs` |
| 10 | `NodeTypesKnown` | WARNING | Node shapes are in registered set | `node.shape` |
| 11 | `FidelityValuesValid` | WARNING | `fidelity` is `full` or `checkpoint` | `node.attrs` |
| 12 | `GoalGatesHaveRetry` | WARNING | `goal_gate=true` nodes have retry path | `node.goal_gate`, retry attrs |
| 13 | `LlmNodesHavePrompts` | WARNING | `box` nodes have `prompt` or `label` | `node.shape`, `node.attrs` |

---

## 7. Error Handling

### Error Propagation Contract

```
Validator.run()          → always returns ValidationResult (never raises)
Validator.run_or_raise() → raises ValidationError if result.is_valid is False
Engine runner            → calls run_or_raise(); catches ValidationError; exits non-zero
CLI validate subcommand  → calls run(); renders result; exits 1 if errors
```

### Rule Isolation

Each rule's `check()` method is called inside a try/except in `Validator.run()`:

```python
def run(self) -> ValidationResult:
    result = ValidationResult(pipeline_id=self.graph.name)
    for rule in self.rules:
        try:
            violations = rule.check(self.graph)
            result.violations.extend(violations)
        except Exception as exc:
            # A rule implementation crash is itself an error, not a rule violation.
            # We surface it as an ERROR violation so it appears in the report.
            result.violations.append(RuleViolation(
                rule_id=rule.rule_id,
                severity=Severity.ERROR,
                message=f"Rule check crashed unexpectedly: {exc!r}",
                node_id=None,
                edge_src=None,
                edge_dst=None,
                fix_hint="This is a validator bug. Report the DOT file that triggered it.",
            ))
    return result
```

This ensures that one rule's implementation bug does not suppress violations from subsequent rules.

### Noise Suppression

Some rules are meaningless when earlier rules fail. The validator applies a single suppression heuristic: `AllNodesReachable` (Rule 3) skips its check and returns an empty list when `SingleStartNode` (Rule 1) detected zero start nodes. This prevents a flood of "unreachable" violations when the real problem is a missing start node.

All other rules run unconditionally. The output may include redundant violations (e.g., Rule 4 `EdgeTargetsExist` and Rule 3 `AllNodesReachable` can both flag consequences of the same missing node), but the author gets a complete picture in one pass.

### CLI Exit Codes

| Condition | Exit Code |
| --- | --- |
| No violations (VALID) | `0` |
| WARNING violations only | `0` |
| ERROR violations present | `1` |
| DOT file not found | `2` |
| DOT parse error (file is not valid DOT) | `2` |
| Internal validator crash | `3` |

---

## 8. File Scope

### New Files to Create

| File | Purpose | Lines (est.) |
| --- | --- | --- |
| `cobuilder/engine/__init__.py` | Package marker | 5 |
| `cobuilder/engine/validation/__init__.py` | Public API: `Severity`, `RuleViolation`, `ValidationResult`, `ValidationError` | ~80 |
| `cobuilder/engine/validation/rules.py` | 13 rule classes implementing `Rule` protocol | ~250 |
| `cobuilder/engine/validation/validator.py` | `Validator` class + `DEFAULT_RULES` list + CLI entry point | ~120 |

### Existing Files to Modify

| File | Change | Risk |
| --- | --- | --- |
| `cobuilder/pipeline/cli.py` | Add `validate` subcommand that imports and calls `engine.validation.validator.Validator` | Low — additive only |
| `cobuilder/engine/runner.py` (Epic 1) | Import `Validator`, call `run_or_raise()` in step 2; respect `--skip-validation` flag | Medium — requires coordination with Epic 1 implementor |

### Files Not Changed

- `cobuilder/pipeline/validator.py` — Existing schema validator remains unchanged, serving the pipeline authoring workflow
- `cobuilder/pipeline/parser.py` — Existing parser unchanged; `engine/validation/` consumes the `Graph` type from Epic 1's new parser

### Dependency on Epic 1

The validation module consumes `cobuilder.engine.graph.Graph`. This type is defined in Epic 1. The Epic 2 implementation must coordinate with Epic 1 to ensure the `Graph` dataclass fields match what the validation rules expect (specifically: `node.shape`, `node.goal_gate`, `node.retry_target`, `node.fidelity`, `graph.adj`, `graph.in_adj`).

If Epic 1 is not yet merged, the validation module can be developed against a stub `Graph` defined locally in `cobuilder/engine/validation/` and replaced at merge time.

### Dependency on Epic 3

Rule 7 (`ConditionSyntaxValid`) imports `cobuilder.engine.conditions.parser.ConditionParser`. If Epic 3 is not yet available, the rule uses this stub:

```python
# Placeholder in rules.py until Epic 3 is merged
class _ConditionParserStub:
    """Placeholder that accepts simple label conditions and rejects obviously broken ones."""
    _SIMPLE_LABELS = {"pass", "fail", "partial", "success", "error"}

    def parse(self, expression: str) -> None:
        expr = expression.strip()
        if not expr:
            raise ParseError("Empty condition expression")
        # Accept known simple labels
        if expr in self._SIMPLE_LABELS:
            return
        # Accept $-prefixed expressions (full parser will validate them properly)
        if "$" in expr:
            return
        # Reject expressions with unclosed quotes or brackets
        if expr.count('"') % 2 != 0 or expr.count("(") != expr.count(")"):
            raise ParseError(f"Unbalanced delimiters in condition: {expr!r}")
```

---

## 9. Testing Strategy

### Test File Location

```
tests/engine/validation/
├── conftest.py               # Pytest fixtures (Graph builders)
├── test_rules_error.py       # Tests for rules 1-9 (ERROR-level)
├── test_rules_warning.py     # Tests for rules 10-13 (WARNING-level)
├── test_validator.py         # Validator orchestration tests
└── test_cli_integration.py   # CLI subprocess tests
```

### Pytest Fixtures

```python
# tests/engine/validation/conftest.py

import pytest
from cobuilder.engine.graph import Graph, Node, Edge


def make_node(id: str, shape: str = "box", **attrs) -> Node:
    """Factory for test nodes with minimal required fields."""
    return Node(id=id, shape=shape, attrs={"shape": shape, **attrs})


def make_edge(src: str, dst: str, condition: str | None = None, **attrs) -> Edge:
    """Factory for test edges."""
    return Edge(src=src, dst=dst, attrs=attrs, condition=condition)


def make_graph(nodes: list[Node], edges: list[Edge], **graph_attrs) -> Graph:
    """Build a Graph with computed adjacency maps."""
    return Graph(
        name="test_pipeline",
        nodes=nodes,
        edges=edges,
        graph_attrs=graph_attrs,
    )


@pytest.fixture
def minimal_valid_graph():
    """Minimal valid pipeline: start -> codergen -> exit."""
    start = make_node("start", shape="Mdiamond", label="Start")
    work = make_node("impl", shape="box", label="Do work", prompt="Implement feature X")
    exit_ = make_node("done", shape="Msquare", label="Done")
    return make_graph(
        nodes=[start, work, exit_],
        edges=[
            make_edge("start", "impl"),
            make_edge("impl", "done"),
        ],
    )
```

### Rule Test Pattern

Each rule has three test cases minimum: valid (no violations), single violation, and fix hint present:

```python
# tests/engine/validation/test_rules_error.py

from cobuilder.engine.validation.rules import SingleStartNode
from cobuilder.engine.validation import Severity


class TestSingleStartNode:
    def test_valid_exactly_one_start(self, minimal_valid_graph):
        violations = SingleStartNode().check(minimal_valid_graph)
        assert violations == []

    def test_error_no_start_node(self, minimal_valid_graph):
        # Remove the Mdiamond node
        minimal_valid_graph.nodes = [
            n for n in minimal_valid_graph.nodes if n.shape != "Mdiamond"
        ]
        violations = SingleStartNode().check(minimal_valid_graph)
        assert len(violations) == 1
        assert violations[0].severity == Severity.ERROR
        assert violations[0].rule_id == "SingleStartNode"
        assert "Mdiamond" in violations[0].message

    def test_error_multiple_start_nodes(self, minimal_valid_graph):
        second_start = make_node("start2", shape="Mdiamond")
        minimal_valid_graph.nodes.append(second_start)
        violations = SingleStartNode().check(minimal_valid_graph)
        assert len(violations) >= 1
        assert all(v.severity == Severity.ERROR for v in violations)

    def test_fix_hint_present(self, minimal_valid_graph):
        minimal_valid_graph.nodes = [
            n for n in minimal_valid_graph.nodes if n.shape != "Mdiamond"
        ]
        violations = SingleStartNode().check(minimal_valid_graph)
        assert violations[0].fix_hint  # Non-empty fix hint required
```

### Coverage Requirements

| Test Category | Target |
| --- | --- |
| Line coverage across `rules.py` | ≥ 95% |
| Line coverage across `validator.py` | ≥ 90% |
| Each of the 13 rules has ≥ 3 tests (valid, violation, fix hint) | 39 minimum rule tests |
| `Validator.run()` with mixed errors and warnings | 1 integration test |
| `Validator.run_or_raise()` raises `ValidationError` on errors | 1 test |
| `Validator.run_or_raise()` does NOT raise on warnings only | 1 test |
| Rule crash isolation (one rule crash does not suppress others) | 1 test |
| CLI `--output json` produces valid JSON with `valid`, `errors`, `warnings` keys | 1 subprocess test |
| CLI exits 0 on valid graph | 1 subprocess test |
| CLI exits 1 on graph with errors | 1 subprocess test |
| Performance: 100-node graph validates in < 2 seconds | 1 timing test |

### Performance Test

```python
# tests/engine/validation/test_validator.py

import time

def test_performance_100_nodes(make_graph, make_node, make_edge):
    """Validation must complete in < 2 seconds for 100-node pipelines."""
    nodes = [make_node("start", shape="Mdiamond")] + [
        make_node(f"node_{i}", shape="box", prompt=f"Task {i}")
        for i in range(98)
    ] + [make_node("exit", shape="Msquare")]
    edges = [make_edge("start", "node_0")] + [
        make_edge(f"node_{i}", f"node_{i+1}") for i in range(97)
    ] + [make_edge("node_97", "exit")]
    graph = make_graph(nodes=nodes, edges=edges)

    start = time.monotonic()
    from cobuilder.engine.validation.validator import Validator
    result = Validator(graph).run()
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"Validation took {elapsed:.2f}s for 100 nodes (limit: 2s)"
    assert result.is_valid
```

---

## 10. Acceptance Criteria

These acceptance criteria map directly to the PRD Epic 2 ACs, extended with specific test evidence requirements.

### AC-1: All 13 Rules Run

`cobuilder pipeline validate pipeline.dot` runs all 13 rules and produces a report. Evidence: CLI subprocess test with a valid DOT file produces exit code 0 and "VALID" in stdout.

### AC-2: Errors Block Execution

ERROR-level violations block execution with clear error messages. Evidence: `cobuilder pipeline run pipeline.dot` with a graph missing a start node exits non-zero before creating any tmux session; the `ValidationError` message references the failing rules.

### AC-3: Warnings Allow Execution

WARNING-level violations allow execution with logged warnings. Evidence: `cobuilder pipeline run pipeline.dot` with a box node missing a prompt completes execution and the log contains `[WARNING] LlmNodesHavePrompts` before any handler invocation.

### AC-4: Rules Are Independently Testable

Each rule can be tested via pytest with synthetic `Graph` fixtures without requiring a real DOT file on disk or any LLM call. Evidence: `pytest tests/engine/validation/test_rules_error.py -v` passes with no network calls.

### AC-5: Automatic Engine Integration

The engine runs validation automatically before execution unless `--skip-validation` is passed. Evidence: `cobuilder pipeline run pipeline.dot` with a graph that violates Rule 1 exits with code 1 and the message includes "failed validation"; `cobuilder pipeline run pipeline.dot --skip-validation` with the same graph proceeds to handler dispatch.

### AC-6: Performance

Validation completes in < 2 seconds for pipelines with up to 100 nodes. Evidence: `test_performance_100_nodes` timing test passes.

### AC-7: Violation Messages Include Location and Fix

Each violation message includes the offending node/edge ID and a fix suggestion. Evidence: All 39+ minimum rule tests assert `violation.node_id is not None` or `violation.edge_src is not None` where applicable, and `violation.fix_hint` is non-empty.

### AC-8: JSON Output

`cobuilder pipeline validate pipeline.dot --output json` produces valid JSON with keys `valid` (bool), `error_count` (int), `warning_count` (int), and `violations` (list). Evidence: CLI integration test parses JSON output with `json.loads()` without error.

---

## 11. Implementation Notes for the Worker

### Recommended Implementation Order

1. Define `RuleViolation`, `ValidationResult`, `ValidationError`, `Severity` in `__init__.py` — these are consumed by all other components
2. Implement the `Rule` protocol stub and the `Validator` class in `validator.py`
3. Implement Rules 1-6 (pure graph topology, no external dependencies) — these are the simplest
4. Implement Rules 10-13 (warning-level, simple attribute checks) — also no external dependencies
5. Implement Rule 9 (`RetryTargetsExist`) — involves graph attributes and node attributes
6. Implement Rules 7-8 (`ConditionSyntaxValid`, `StylesheetSyntaxValid`) — these use stubs if Epic 3 is not yet merged
7. Wire into CLI (`cobuilder/pipeline/cli.py`) via the `validate` subcommand
8. Write tests in parallel with each rule group

### Key Design Invariants

- `Validator.run()` **never raises**. It always returns a `ValidationResult`. Rule crashes become ERROR violations in the result.
- All 13 rules **always run** (no early termination). The exception is the noise suppression heuristic in Rule 3.
- `RuleViolation` is **frozen** (immutable dataclass). Rules cannot modify violations after returning them.
- Rules are **stateless**. A single rule instance can be called multiple times on different graphs.
- The `DEFAULT_RULES` list is the **canonical ordering**. Error rules come before warning rules. Do not change this ordering without updating this document.

### Coordination with Epic 1 Worker

The Epic 2 worker must confirm with the Epic 1 worker the exact field names and types on `Node`, `Edge`, and `Graph` before writing rule implementations. The field names used in this document (`node.shape`, `node.goal_gate`, `node.retry_target`, `node.fidelity`, `graph.adj`, `graph.in_adj`) are the agreed interface. If Epic 1 uses different names, update the rules accordingly.

---

## 12. Handoff Summary for Project Manager

### What Epic 2 Delivers

A self-contained `cobuilder/engine/validation/` Python package with:
- 13 validation rules (9 ERROR + 4 WARNING) as independently testable classes
- A `Validator` orchestrator that runs all rules against a parsed `Graph`
- A `ValidationError` exception for engine integration
- A `ValidationResult` data model with JSON serialization
- CLI integration via `cobuilder pipeline validate <file>.dot`

### Dependencies

| Dependency | Blocker? | Mitigation |
| --- | --- | --- |
| Epic 1 `Graph` type | Soft — can stub locally | Agree on `Graph` field names before starting |
| Epic 3 condition parser | No — Rule 7 uses a stub | Stub is replaceable at merge time |
| Epic 3 stylesheet parser | No — Rule 8 uses a permissive stub | Same pattern as Rule 7 |

### Suggested Worker Assignment

Single `backend-solutions-engineer` worker. The validation module is pure Python with no async, no LLM calls, and no external services. A single focused worker can complete all 13 rules, the `Validator` class, and the test suite in one session.

**Estimated scope**: ~450 lines of implementation, ~350 lines of tests. No infrastructure setup required.

---

*Solution design authored for PRD-PIPELINE-ENGINE-001 Epic 2. Implementation target: **`cobuilder/engine/validation/`**. All rule numbering and behavior is derived from attractor-rb's 13-rule validation set, adapted to the Python type system and the engine's Graph model.*
