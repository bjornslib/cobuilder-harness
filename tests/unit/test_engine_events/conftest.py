"""Test fixtures for engine event bus tests.

Ensures proper async isolation by providing a fresh event loop for each test,
preventing cross-test pollution when running the full suite.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _fresh_event_loop():
    """Auto-use fixture: create a fresh event loop before each test, clean up after.

    This prevents "no current event loop" errors caused by other test modules
    (e.g., test_logfire_spans) closing the default event loop via asyncio.run().
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    try:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    finally:
        loop.close()
        asyncio.set_event_loop(None)
