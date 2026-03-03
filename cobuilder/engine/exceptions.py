"""Engine-specific exception hierarchy.

All exceptions raised by the engine are subclasses of ``EngineError``.
This lets callers catch any engine error with a single except clause while
still being able to discriminate between specific error types.

Error taxonomy (from SD Section 7):

Fatal (exit non-zero, no automatic retry):
    ParseError          — DOT parser encountered unrecoverable syntax error
    ValidationError     — 13-rule validator (Epic 2); stub present
    UnknownShapeError   — node shape not in handler registry
    NoEdgeError         — EdgeSelector exhausted all 5 steps
    CheckpointVersionError — checkpoint schema_version mismatch

Recoverable on resume (checkpoint written before exit):
    HandlerError        — handler encountered unrecoverable error
    LoopDetectedError   — visit count exceeded max_retries (Epic 5 raises this)

Converted to HandlerError:
    TimeoutError        — CodergenHandler, ToolHandler, WaitHumanHandler timeouts
"""
from __future__ import annotations


class EngineError(Exception):
    """Base class for all engine exceptions."""


# ---------------------------------------------------------------------------
# Fatal errors
# ---------------------------------------------------------------------------

class ParseError(EngineError):
    """Raised when the DOT source cannot be parsed.

    Attributes:
        message:  Human-readable description of the problem.
        line:     1-based line number in the source where the error occurred.
                  ``0`` means the line could not be determined.
        column:   1-based column number in the source where the error occurred.
                  ``0`` means the column could not be determined.
        snippet:  The offending source fragment (up to 80 characters).
    """

    def __init__(self, message: str, line: int = 0, snippet: str = "", column: int = 0) -> None:
        self.message = message
        self.line = line
        self.column = column
        self.snippet = snippet
        loc = f" (line {line}, col {column})" if line else ""
        snip = f": {snippet!r}" if snippet else ""
        super().__init__(f"{message}{loc}{snip}")


class ValidationError(EngineError):
    """13-rule validation failed before pipeline execution.

    Raised by ``Validator.run_all(graph)`` (Epic 2).  In Epic 1 this is a
    stub; the existing ``cobuilder/pipeline/validator.py`` is used instead.
    """


class UnknownShapeError(EngineError):
    """Handler registry received a node whose shape is not registered.

    Attributes:
        shape:   The unrecognised DOT shape string.
        node_id: The node ID where the unknown shape was encountered.
    """

    def __init__(self, shape: str, node_id: str = "") -> None:
        self.shape = shape
        self.node_id = node_id
        detail = f" (node '{node_id}')" if node_id else ""
        super().__init__(
            f"Unknown node shape '{shape}'{detail}. "
            f"Register a handler for this shape or remove the node from the pipeline."
        )


class NoEdgeError(EngineError):
    """EdgeSelector exhausted all 5 selection steps without finding a match.

    Attributes:
        node_id:        Node from which edge selection was attempted.
        available_edges: String representation of available outgoing edges.
    """

    def __init__(self, node_id: str, available_edges: str = "") -> None:
        self.node_id = node_id
        self.available_edges = available_edges
        detail = f" Available edges: {available_edges}" if available_edges else ""
        super().__init__(
            f"No edge selected from node '{node_id}' after exhausting all 5 steps.{detail}"
        )


class CheckpointVersionError(EngineError):
    """Checkpoint schema_version does not match ENGINE_CHECKPOINT_VERSION.

    The user must delete the run directory and restart from scratch.

    Attributes:
        found:    schema_version found in the checkpoint file.
        expected: ENGINE_CHECKPOINT_VERSION constant from checkpoint.py.
        path:     Path to the checkpoint file.
    """

    def __init__(self, found: str, expected: str, path: str = "") -> None:
        self.found = found
        self.expected = expected
        self.path = path
        location = f" at '{path}'" if path else ""
        super().__init__(
            f"Checkpoint{location} has schema_version '{found}' but engine "
            f"requires '{expected}'. Delete the run directory and restart: "
            f"rm -rf <run_dir>"
        )


# ---------------------------------------------------------------------------
# Recoverable errors
# ---------------------------------------------------------------------------

class HandlerError(EngineError):
    """Handler encountered an unrecoverable error during execution.

    The runner catches this, writes an ``ORCHESTRATOR_CRASHED`` signal, saves
    the current checkpoint, and exits with a non-zero status code.

    Attributes:
        node_id:    ID of the node whose handler raised this error.
        cause:      Original exception (may be None for synthetic errors).
    """

    def __init__(self, message: str, node_id: str = "", cause: BaseException | None = None) -> None:
        self.node_id = node_id
        self.cause = cause
        detail = f" (node '{node_id}')" if node_id else ""
        super().__init__(f"Handler error{detail}: {message}")
        if cause is not None:
            self.__cause__ = cause


class LoopDetectedError(EngineError):
    """A node's visit count exceeded its max_retries threshold.

    Raised by Epic 5's loop detection middleware; Epic 1 defines the class
    so that EngineRunner can catch it.

    Attributes:
        node_id:     Node that exceeded its visit budget.
        visit_count: Number of times the node was visited.
        max_retries: Configured limit (from node.max_retries or graph.default_max_retry).
    """

    def __init__(self, node_id: str, visit_count: int, max_retries: int) -> None:
        self.node_id = node_id
        self.visit_count = visit_count
        self.max_retries = max_retries
        super().__init__(
            f"Loop detected: node '{node_id}' visited {visit_count} times "
            f"(max_retries={max_retries}). "
            f"Check for cycles in the pipeline or increase max_retries."
        )


class NoRetryTargetError(EngineError):
    """No retry target is configured for a node that needs to retry.

    Raised when ``resolve_retry_target()`` returns ``None`` and the engine
    cannot continue — the pipeline has no path for recovery.

    Attributes:
        node_id:     Node for which no retry target was found.
        pipeline_id: Pipeline ID (from graph attributes), if available.
    """

    def __init__(self, node_id: str, pipeline_id: str = "") -> None:
        self.node_id = node_id
        self.pipeline_id = pipeline_id
        super().__init__(
            f"No retry target configured for node '{node_id}' in pipeline '{pipeline_id}'"
        )
