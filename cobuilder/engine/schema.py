"""Pipeline schema constants — single source of truth.

This module is the authoritative registry for all enumerated values used in
CoBuilder pipeline DOT files.  It is intentionally pure-data: no imports from
cobuilder.engine.* are allowed, only the Python standard library if needed.

Every validator, rule, and node-operation module MUST import its constants from
here rather than defining them locally.  Keeping them in one place ensures that
a single change propagates everywhere without divergence.

Constants:
    VALID_STATUSES          — allowed pipeline node status values
    VALID_HANDLERS          — registered handler type identifiers
    HANDLER_SHAPE_MAP       — mapping from handler name → expected DOT shape
    VALID_CONDITIONS        — allowed edge condition labels
    REQUIRED_ATTRS          — required node attributes per handler type
    WARNING_ATTRS           — recommended (advisory) attributes per handler type
    VALID_WORKER_TYPES      — allowed worker_type values for codergen nodes
    VALID_GATE_TYPES        — allowed gate= values for wait.human nodes
    VALID_MODES             — allowed mode= values for wait.human nodes
    VALID_VALIDATION_METHODS — allowed validation_method values in manifests
"""

# --- Node status lifecycle ---

VALID_STATUSES: frozenset[str] = frozenset(
    {"pending", "active", "impl_complete", "validated", "accepted", "failed"}
)

# --- Handler registry ---

VALID_HANDLERS: frozenset[str] = frozenset(
    {
        "start",
        "exit",
        "codergen",
        "tool",
        "wait.human",
        "wait.cobuilder",
        "conditional",
        "parallel",
        "research",
        "refine",
        "acceptance-test-writer",
    }
)

# --- Handler → DOT shape mapping ---

HANDLER_SHAPE_MAP: dict[str, str] = {
    "start": "Mdiamond",
    "exit": "Msquare",
    "codergen": "box",
    "tool": "box",
    "wait.human": "hexagon",
    "wait.cobuilder": "hexagon",
    "conditional": "diamond",
    "parallel": "parallelogram",
    "research": "tab",
    "refine": "note",
    "acceptance-test-writer": "component",
}

# --- Edge condition labels ---

VALID_CONDITIONS: frozenset[str] = frozenset({"pass", "fail", "partial"})

# --- Required attributes per handler type ---

REQUIRED_ATTRS: dict[str, list[str]] = {
    "start": ["label", "handler"],
    "exit": ["label", "handler"],
    "codergen": ["label", "handler", "bead_id", "worker_type", "sd_path"],
    "tool": ["label", "handler", "command"],
    "wait.human": ["label", "handler", "gate", "mode"],
    "wait.cobuilder": ["label", "handler", "gate_type"],
    "conditional": ["label", "handler"],
    "parallel": ["label", "handler"],
    "research": ["label", "handler", "solution_design"],
    "refine": ["label", "handler", "solution_design", "evidence_path"],
    "acceptance-test-writer": ["label", "handler", "prd_ref"],
}

# --- Recommended (advisory) attributes per handler type ---
# Absence of these emits warnings rather than errors.
# They are needed for Runner context and PRD traceability.

WARNING_ATTRS: dict[str, list[str]] = {
    "codergen": ["prd_ref", "acceptance"],
    "research": ["prd_ref", "research_queries", "downstream_node"],
    "refine": ["prd_ref"],
}

# --- Worker type registry ---

VALID_WORKER_TYPES: frozenset[str] = frozenset(
    {
        "frontend-dev-expert",
        "backend-solutions-engineer",
        "tdd-test-engineer",
        "solution-architect",
        "solution-design-architect",
        "validation-test-agent",
        "ux-designer",
    }
)

# --- Gate type registry (wait.human nodes) ---

VALID_GATE_TYPES: frozenset[str] = frozenset({"technical", "business", "e2e", "manual"})

# --- Mode registry (wait.human nodes) ---

VALID_MODES: frozenset[str] = frozenset({"technical", "business"})

# --- Manifest validation method registry ---

VALID_VALIDATION_METHODS: frozenset[str] = frozenset(
    {
        "browser-required",  # Must use Claude-in-Chrome for UI validation
        "api-required",      # Must make real HTTP requests
        "code-analysis",     # Static code reading is sufficient
        "doc-review",        # Documentation review (no runtime validation)
        "e2e-test",          # End-to-end test execution required
        "hybrid",            # Agent uses best judgment on tooling
    }
)
