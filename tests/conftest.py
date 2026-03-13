import sys
import os

import pytest

# Add .claude/hooks to sys.path so tests can import decision_guidance
# and unified_stop_gate modules without installing them as packages.
_hooks_dir = os.path.join(os.path.dirname(__file__), "..", ".claude", "hooks")
_hooks_dir = os.path.abspath(_hooks_dir)
if _hooks_dir not in sys.path:
    sys.path.insert(0, _hooks_dir)


# ---------------------------------------------------------------------------
# Logfire capture fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def capture_logfire():
    """Capture all Logfire spans emitted during a test.

    Uses ``logfire.testing.CaptureLogfire`` to intercept spans without
    requiring a real Logfire project or network connection.

    Returns a ``CaptureLogfire`` instance.  Inspect spans via::

        spans = capture_logfire.exporter.exported_spans_as_dict()
        assert any(s["name"] == "pipeline.run" for s in spans)

    This fixture mirrors the built-in ``capfire`` fixture from the logfire
    pytest plugin but is explicitly registered here so it is guaranteed to
    be available regardless of plugin auto-discovery.

    Usage::

        def test_something(capture_logfire):
            # ... exercise code that emits spans ...
            spans = capture_logfire.exporter.exported_spans_as_dict()
            assert any(s["name"] == "pipeline.run" for s in spans)
    """
    import logfire
    from logfire.testing import (
        CaptureLogfire,
        IncrementalIdGenerator,
        InMemoryMetricReader,
        METRICS_PREFERRED_TEMPORALITY,
        SimpleLogRecordProcessor,
        SimpleSpanProcessor,
        TestExporter,
        TestLogExporter,
        TimeGenerator,
    )

    exporter = TestExporter()
    metrics_reader = InMemoryMetricReader(
        preferred_temporality=METRICS_PREFERRED_TEMPORALITY
    )
    time_generator = TimeGenerator()
    log_exporter = TestLogExporter(time_generator)

    logfire.configure(
        send_to_logfire=False,
        console=False,
        advanced=logfire.AdvancedOptions(
            id_generator=IncrementalIdGenerator(),
            ns_timestamp_generator=time_generator,
            log_record_processors=[SimpleLogRecordProcessor(log_exporter)],
        ),
        additional_span_processors=[SimpleSpanProcessor(exporter)],
        metrics=logfire.MetricsOptions(additional_readers=[metrics_reader]),
    )

    yield CaptureLogfire(
        exporter=exporter,
        metrics_reader=metrics_reader,
        log_exporter=log_exporter,
    )
