"""HandlerRegistry — maps DOT node shapes to Handler instances.

The registry is the single point where the engine resolves a node's shape to
a concrete handler.  All 9 standard shapes are pre-registered when
``HandlerRegistry.default()`` is called.

Design:
- ``register(shape, handler)`` stores a handler for a shape string.
- ``dispatch(node)`` looks up the handler and returns it; raises
  ``UnknownShapeError`` for shapes not in the registry.
- ``HandlerRegistry(handlers={...})`` accepts a pre-populated dict for
  dependency injection in tests.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cobuilder.engine.exceptions import UnknownShapeError
from cobuilder.engine.graph import Node
from cobuilder.engine.handlers.base import Handler

if TYPE_CHECKING:
    pass


class HandlerRegistry:
    """Registry mapping DOT shape strings to Handler implementations.

    Args:
        handlers: Optional pre-populated shape → handler dict.  If not
                  provided, the registry starts empty.  Use
                  ``HandlerRegistry.default()`` to get a fully-wired registry.

    Example::

        registry = HandlerRegistry()
        registry.register("box", CodergenHandler())
        handler = registry.dispatch(node)  # node.shape == "box"
    """

    def __init__(self, handlers: dict[str, Handler] | None = None) -> None:
        self._handlers: dict[str, Handler] = dict(handlers or {})

    def register(self, shape: str, handler: Handler) -> None:
        """Register *handler* for DOT shape *shape*.

        Args:
            shape:   DOT shape string (e.g. ``"box"``, ``"Mdiamond"``).
            handler: Handler instance implementing the ``Handler`` protocol.
        """
        self._handlers[shape] = handler

    def dispatch(self, node: Node) -> Handler:
        """Return the handler registered for *node.shape*.

        Args:
            node: The graph node to dispatch.

        Returns:
            The Handler instance registered for this node's shape.

        Raises:
            UnknownShapeError: If no handler is registered for *node.shape*.
        """
        handler = self._handlers.get(node.shape)
        if handler is None:
            raise UnknownShapeError(shape=node.shape, node_id=node.id)
        return handler

    def registered_shapes(self) -> list[str]:
        """Return all registered shape strings (in insertion order)."""
        return list(self._handlers.keys())

    @classmethod
    def default(cls) -> "HandlerRegistry":
        """Build a fully-wired registry with all 10 standard handlers.

        Import is deferred to avoid circular imports at module load time.
        """
        from cobuilder.engine.handlers.close import CloseHandler
        from cobuilder.engine.handlers.codergen import CodergenHandler
        from cobuilder.engine.handlers.conditional import ConditionalHandler
        from cobuilder.engine.handlers.exit import ExitHandler
        from cobuilder.engine.handlers.fan_in import FanInHandler
        from cobuilder.engine.handlers.manager_loop import ManagerLoopHandler
        from cobuilder.engine.handlers.parallel import ParallelHandler
        from cobuilder.engine.handlers.start import StartHandler
        from cobuilder.engine.handlers.tool import ToolHandler
        from cobuilder.engine.handlers.wait_human import WaitHumanHandler

        registry = cls()
        registry.register("Mdiamond", StartHandler())
        registry.register("Msquare", ExitHandler())
        registry.register("box", CodergenHandler())
        registry.register("diamond", ConditionalHandler())
        registry.register("hexagon", WaitHumanHandler())
        registry.register("component", ParallelHandler())
        registry.register("tripleoctagon", FanInHandler())
        registry.register("parallelogram", ToolHandler())
        registry.register("house", ManagerLoopHandler())
        registry.register("octagon", CloseHandler())
        # Aliases: research (tab) and refine (note) use CodergenHandler dispatch
        registry.register("tab", CodergenHandler())
        registry.register("note", CodergenHandler())
        return registry
