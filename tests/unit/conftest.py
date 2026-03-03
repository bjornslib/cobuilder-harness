"""Shared test fixtures for unit tests.

This conftest provides an autouse fixture that patches
``cobuilder.pipeline.validator.validate_file`` to return an empty list so that
pre-existing EngineRunner tests (which use synthetic DOT files that do not
satisfy all 13 validation rules) continue to pass.

Tests in ``TestEngineRunnerValidation`` override this fixture with their own
``patch()`` context managers to test the actual validation wiring.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _stub_validate_file():
    """Stub validate_file to return no issues for all unit tests by default.

    Individual validation-focused tests override this by using their own
    ``with patch(...)`` context managers inside the test body, which take
    precedence over this autouse patch.
    """
    with patch(
        "cobuilder.pipeline.validator.validate_file",
        return_value=[],
    ):
        yield
