"""E0.2: Logfire span assertion template.

This module is the canonical pattern for asserting Logfire span presence
across the cobuilder engine.  Every handler tested in subsequent epics
should follow this template.

Pattern:
    1. Use the ``capture_logfire`` fixture (defined in tests/conftest.py).
    2. Exercise the code path that should emit spans.
    3. Inspect ``capture_logfire.exporter.exported_spans_as_dict()`` for span names.

The single example test here asserts that LogfireMiddleware emits a
``handler.{node_id}`` span when called.  This validates that:

- ``logfire`` is installed as a hard dependency (not optional).
- ``CaptureLogfire`` correctly intercepts spans in test environments.
- The ``capture_logfire`` fixture is wired up at the root conftest level.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from cobuilder.engine.graph import Node
from cobuilder.engine.middleware.chain import HandlerRequest
from cobuilder.engine.middleware.logfire import LogfireMiddleware
from cobuilder.engine.outcome import Outcome, OutcomeStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(node_id: str = "n1") -> Node:
    return Node(id=node_id, shape="box", label=node_id, attrs={})


def _make_request(node: Node, emitter: Any = None) -> HandlerRequest:
    return HandlerRequest(
        node=node,
        context=MagicMock(),
        pipeline_id="test-pipeline",
        visit_count=1,
        emitter=emitter,
    )


async def _next_success(request: HandlerRequest) -> Outcome:
    return Outcome(status=OutcomeStatus.SUCCESS, metadata={})


def _run(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine synchronously (test helper).

    Creates a fresh event loop for each invocation to avoid state pollution
    between tests when running the full suite. Uses asyncio.run() for
    Python 3.7+ compatibility.
    """
    try:
        # Try asyncio.run() first (Python 3.7+)
        return asyncio.run(coro)
    except RuntimeError:
        # Fallback for nested loop scenarios (rare in tests)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# Example span assertion test — template for all future span tests
# ---------------------------------------------------------------------------

class TestLogfireMiddlewareEmitsSpan:
    """Verify that LogfireMiddleware emits a handler span captured by CaptureLogfire."""

    def test_handler_span_emitted(self, capture_logfire) -> None:
        """LogfireMiddleware must emit a 'handler.{node_id}' span on successful execution.

        This is the canonical E0.2 span assertion template.  Replicate this
        pattern for every handler type added in subsequent epics.

        Expected span name: ``handler.n1``  (template: ``handler.{node_id}``)
        """
        middleware = LogfireMiddleware()
        node = _make_node("n1")
        request = _make_request(node, emitter=None)

        _run(middleware(request, _next_success))

        # exported_spans_as_dict() returns list of dicts with a "name" key.
        exported = capture_logfire.exporter.exported_spans_as_dict()
        span_names = [s["name"] for s in exported]
        assert any(
            "handler.n1" in name for name in span_names
        ), (
            f"Expected a span matching 'handler.n1' but found: {span_names}. "
            "Ensure logfire>=2.0 is installed and LogfireMiddleware uses direct logfire.span()."
        )

    def test_handler_span_name_respects_template(self, capture_logfire) -> None:
        """The span name template is configurable via LogfireMiddleware constructor."""
        middleware = LogfireMiddleware(span_name_template="exec.{node_id}")
        node = _make_node("my-node")
        request = _make_request(node, emitter=None)

        _run(middleware(request, _next_success))

        exported = capture_logfire.exporter.exported_spans_as_dict()
        span_names = [s["name"] for s in exported]
        assert any(
            "exec.my-node" in name for name in span_names
        ), f"Expected span 'exec.my-node' but found: {span_names}"
