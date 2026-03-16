"""In-memory graph models for Attractor DOT pipelines.

These are read-only dataclasses after parsing. The engine never modifies the
parsed graph — all mutable state lives in ``EngineCheckpoint`` and
``PipelineContext``.

Design notes:
- ``@dataclass`` (not Pydantic) because the graph is read-only after parsing;
  Pydantic's serialisation overhead is unnecessary for a static data structure.
- Typed ``@property`` accessors surface the Attractor-specific attributes the
  engine cares about, while ``attrs`` retains the full raw attribute bag for
  forward-compatibility.
- Adjacency indices (``_edges_from``, ``_edges_to``) are built once in
  ``__post_init__`` so that edge lookups during traversal are O(1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Shape → handler-type mapping (canonical, shared with validation)
# ---------------------------------------------------------------------------

SHAPE_TO_HANDLER: dict[str, str] = {
    "Mdiamond": "start",
    "Msquare": "exit",
    "box": "codergen",
    "diamond": "conditional",
    "hexagon": "wait_human",
    "component": "parallel",
    "tripleoctagon": "fan_in",
    "parallelogram": "tool",      # disambiguated from 'parallel' by 'tool_command' attr
    "house": "manager_loop",
    "tab": "research",
}

# Node shapes that require LLM invocation — used by Validation Rule 13
LLM_NODE_SHAPES: frozenset[str] = frozenset({"box", "tab"})

# Node shapes that are eligible goal_gate candidates — used by ExitHandler
GOAL_GATE_SHAPES: frozenset[str] = frozenset({"box", "hexagon", "component"})


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """A parsed DOT directed edge between two nodes.

    Attributes:
        source:       Source node ID.
        target:       Target node ID.
        label:        Human-readable edge label (used in Step 2 of edge
                      selection and for display).
        condition:    Raw condition expression string evaluated by EdgeSelector
                      Step 1.  Empty string means "no condition" (always passes
                      Step 1 but is skipped — Step 1 only fires for non-empty
                      conditions).
        weight:       Optional numeric weight for Step 4 of edge selection.
                      ``None`` means no weight is set.
        loop_restart: When ``True``, traversing this edge clears pipeline
                      context back to graph-level variables (Epic 5 semantics).
        attrs:        Full raw attribute bag.  All keys present in the DOT
                      source are preserved here for forward-compatibility.
    """

    source: str
    target: str
    label: str = ""
    condition: str = ""
    weight: float | None = None
    loop_restart: bool = False
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        """Stable string identifier for this edge (used in logging and checkpoints)."""
        return f"{self.source}->{self.target}"


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """A parsed DOT node with all Attractor-specific attributes extracted.

    The ``attrs`` dict holds the raw attribute bag from the DOT source.
    Typed properties below provide ergonomic access to the attributes the
    engine relies on.  Any attribute not explicitly surfaced by a property can
    still be read via ``node.attrs["key"]``.

    Attributes:
        id:     Node identifier as written in the DOT source (e.g. ``impl_auth``).
        shape:  DOT ``shape`` attribute value (e.g. ``"box"``, ``"Mdiamond"``).
        label:  Human-readable label string (newlines preserved from DOT source).
        attrs:  Full raw attribute bag.
    """

    id: str
    shape: str
    label: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Handler classification
    # ------------------------------------------------------------------

    @property
    def handler_type(self) -> str:
        """The canonical handler type for this node.

        For hexagon nodes (which can be wait.cobuilder or wait.human),
        checks the explicit ``handler`` attribute in attrs first.
        Falls back to SHAPE_TO_HANDLER mapping for other shapes.

        Returns ``"unknown"`` for shapes not in ``SHAPE_TO_HANDLER``.
        The engine's ``HandlerRegistry`` will raise ``UnknownShapeError``
        when it encounters ``"unknown"``.
        """
        # Hexagon is dual-purpose: wait.cobuilder or wait.human
        # Distinguished by explicit 'handler' attribute in attrs
        explicit_handler = self.attrs.get("handler")
        if explicit_handler:
            # Normalize dot notation (wait.cobuilder) to underscore (wait_cobuilder)
            # so it matches SHAPE_TO_HANDLER values used by validation rules.
            return explicit_handler.replace(".", "_")
        return SHAPE_TO_HANDLER.get(self.shape, "unknown")

    @property
    def is_start(self) -> bool:
        """True if this is a pipeline start node (``Mdiamond`` shape)."""
        return self.shape == "Mdiamond"

    @property
    def is_exit(self) -> bool:
        """True if this is a pipeline exit node (``Msquare`` shape)."""
        return self.shape == "Msquare"

    # ------------------------------------------------------------------
    # Attractor-specific typed accessors
    # ------------------------------------------------------------------

    @property
    def prompt(self) -> str:
        """LLM prompt for codergen nodes.  Empty string if not set."""
        return self.attrs.get("prompt", "")

    @property
    def goal_gate(self) -> bool:
        """True if this node is a goal gate (must complete for pipeline success)."""
        raw = self.attrs.get("goal_gate", "false")
        return str(raw).lower() == "true"

    @property
    def tool_command(self) -> str:
        """Shell command for tool/parallelogram nodes.  Empty string if not set."""
        return self.attrs.get("tool_command", self.attrs.get("command", ""))

    @property
    def model_stylesheet(self) -> str:
        """Model stylesheet attribute.  Empty string if not set."""
        return self.attrs.get("model_stylesheet", "")

    @property
    def dispatch_strategy(self) -> str:
        """Dispatch strategy for codergen nodes.

        Valid values: ``"tmux"`` (default), ``"sdk"``, ``"inline"``.
        """
        return self.attrs.get("dispatch_strategy", "tmux")

    @property
    def max_retries(self) -> int:
        """Maximum number of additional retries beyond the initial attempt.

        Defaults to 3 if not set (from PRD Epic 5).
        """
        try:
            return int(self.attrs.get("max_retries", 3))
        except (ValueError, TypeError):
            return 3

    @property
    def retry_target(self) -> str | None:
        """Node ID to route to when retries are exhausted.  ``None`` if not set."""
        return self.attrs.get("retry_target") or None

    @property
    def join_policy(self) -> str:
        """Join policy for fan-in nodes.

        Valid values: ``"wait_all"`` (default), ``"first_success"``.
        """
        return self.attrs.get("join_policy", "wait_all")

    @property
    def allow_partial(self) -> bool:
        """If True, accept ``PARTIAL_SUCCESS`` when retries are exhausted (Epic 5)."""
        raw = self.attrs.get("allow_partial", "false")
        return str(raw).lower() == "true"

    @property
    def bead_id(self) -> str:
        """Beads issue ID for this node.  Empty string if not set."""
        return self.attrs.get("bead_id", "")

    @property
    def worker_type(self) -> str:
        """Specialist agent type for codergen nodes.  Empty string if not set."""
        return self.attrs.get("worker_type", "")

    @property
    def acceptance(self) -> str:
        """Acceptance criteria text.  Empty string if not set."""
        return self.attrs.get("acceptance", "")

    @property
    def solution_design(self) -> str:
        """Path to solution design document.  Empty string if not set."""
        return self.attrs.get("solution_design", "")

    @property
    def file_path(self) -> str:
        """Target file path for scoped workers.  Empty string if not set."""
        return self.attrs.get("file_path", "")

    @property
    def folder_path(self) -> str:
        """Target folder path for scoped workers.  Empty string if not set."""
        return self.attrs.get("folder_path", "")

    @property
    def downstream_node(self) -> str:
        """Codergen node ID this research node feeds into.  Empty string if not set."""
        return self.attrs.get("downstream_node", "")

    @property
    def research_queries(self) -> list[str]:
        """Frameworks/topics to research, parsed from comma-separated string."""
        raw = self.attrs.get("research_queries", "")
        return [q.strip() for q in raw.split(",") if q.strip()] if raw else []

    @property
    def prd_ref(self) -> str:
        """PRD reference for this node.  Empty string if not set."""
        return self.attrs.get("prd_ref", "")

    @property
    def llm_profile(self) -> str | None:
        """LLM profile name for per-node model configuration (Epic 1).

        References a profile in providers.yaml. Returns None if not set.
        Used by the 5-layer resolution in cobuilder.engine.providers.
        """
        return self.attrs.get("llm_profile") or None


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

@dataclass
class Graph:
    """In-memory representation of a parsed Attractor DOT pipeline.

    After construction all nodes and edges are immutable.  The engine
    uses this as a read-only map; all mutable execution state lives in
    ``EngineCheckpoint`` and ``PipelineContext``.

    Attributes:
        name:  Graph name as written in the ``digraph`` declaration.
        attrs: Graph-level attribute bag (``prd_ref``, ``promise_id``, etc.).
        nodes: Dict mapping node ID → ``Node``.
        edges: Ordered list of all edges in the graph.

    Private cached adjacency dicts (``_edges_from``, ``_edges_to``) are built
    once in ``__post_init__`` for O(1) lookups during traversal.
    """

    name: str
    attrs: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)   # node_id → Node
    edges: list[Edge] = field(default_factory=list)

    # Cached adjacency — built in __post_init__, not serialised
    _edges_from: dict[str, list[Edge]] = field(
        default_factory=dict, repr=False, compare=False
    )
    _edges_to: dict[str, list[Edge]] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        self._build_adjacency()

    def _build_adjacency(self) -> None:
        """Build source and target adjacency indices from ``self.edges``."""
        self._edges_from = {}
        self._edges_to = {}
        for edge in self.edges:
            self._edges_from.setdefault(edge.source, []).append(edge)
            self._edges_to.setdefault(edge.target, []).append(edge)

    # ------------------------------------------------------------------
    # Traversal helpers
    # ------------------------------------------------------------------

    def edges_from(self, node_id: str) -> list[Edge]:
        """Return all outgoing edges from *node_id* in declaration order."""
        return list(self._edges_from.get(node_id, []))

    def edges_to(self, node_id: str) -> list[Edge]:
        """Return all incoming edges to *node_id* in declaration order."""
        return list(self._edges_to.get(node_id, []))

    def node(self, node_id: str) -> Node:
        """Retrieve a node by ID.

        Raises:
            KeyError: If *node_id* is not present in the graph.
        """
        return self.nodes[node_id]

    # ------------------------------------------------------------------
    # Well-known node sets (used by validation and the runner)
    # ------------------------------------------------------------------

    @property
    def start_node(self) -> Node:
        """The unique start node (``Mdiamond`` shape).

        Raises:
            ValueError: If the graph has zero or more than one start node.
                        (Validation Rule ``SingleStartNode`` catches this before
                        execution; the property is defensive for direct use.)
        """
        starts = [n for n in self.nodes.values() if n.is_start]
        if len(starts) != 1:
            raise ValueError(
                f"Graph must have exactly one start node (Mdiamond); found {len(starts)}"
            )
        return starts[0]

    @property
    def exit_nodes(self) -> list[Node]:
        """All exit nodes (``Msquare`` shape) in declaration order."""
        return [n for n in self.nodes.values() if n.is_exit]

    @property
    def goal_gate_nodes(self) -> list[Node]:
        """All nodes with ``goal_gate=true`` in declaration order."""
        return [n for n in self.nodes.values() if n.goal_gate]

    # ------------------------------------------------------------------
    # Graph-level attribute accessors
    # ------------------------------------------------------------------

    @property
    def prd_ref(self) -> str:
        """PRD identifier for this pipeline (e.g. ``"PRD-AUTH-001"``)."""
        return self.attrs.get("prd_ref", "")

    @property
    def promise_id(self) -> str:
        """Completion promise ID.  Empty string if not set."""
        return self.attrs.get("promise_id", "")

    @property
    def default_max_retry(self) -> int:
        """Pipeline-wide maximum total node executions before loop detection fires.

        Defaults to 50 as specified in PRD Epic 5.
        """
        try:
            return int(self.attrs.get("default_max_retry", 50))
        except (ValueError, TypeError):
            return 50

    @property
    def retry_target(self) -> str | None:
        """Graph-level fallback retry target node ID.  ``None`` if not set."""
        return self.attrs.get("retry_target") or None

    @property
    def fallback_retry_target(self) -> str | None:
        """Second-level fallback retry target.  ``None`` if not set."""
        return self.attrs.get("fallback_retry_target") or None

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def all_node_ids(self) -> list[str]:
        """Return all node IDs in insertion order."""
        return list(self.nodes.keys())

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self.nodes
