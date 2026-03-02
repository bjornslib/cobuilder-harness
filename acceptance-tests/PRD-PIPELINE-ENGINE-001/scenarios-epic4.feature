# PRD-PIPELINE-ENGINE-001 Epic 4: Structured Event Bus with Logfire Integration
# Blind acceptance rubric — generated from SD-PIPELINE-ENGINE-001-epic4-event-bus.md
# Guardian: Do NOT share this file with orchestrators or workers.

@feature-F13 @weight-0.08
Feature: F13 — PipelineEvent Model and EventBuilder

  Scenario: S13.1 — PipelineEvent frozen dataclass with all 14 event types
    Given the event bus models module
    Then PipelineEvent is a frozen dataclass with slots=True
    And it has fields: type, timestamp, pipeline_id, node_id, data, span_id, sequence
    And EventType enum has exactly 14 values covering pipeline, node, edge, checkpoint,
        context, retry, loop, and validation lifecycle events
    And EventBuilder factory class has one method per event type

    # Confidence scoring guide:
    # 1.0 — Frozen dataclass with all 7 fields. EventType enum with 14 values:
    #        pipeline.started, pipeline.completed, pipeline.failed, pipeline.resumed,
    #        node.started, node.completed, node.failed, edge.selected,
    #        checkpoint.saved, context.updated, retry.triggered, loop.detected,
    #        validation.started, validation.completed.
    #        EventBuilder with typed factory methods for each event.
    # 0.5 — PipelineEvent exists but missing some event types or not frozen.
    # 0.0 — Events are plain dicts or strings.

    # Evidence to check:
    # - cobuilder/engine/events/models.py — PipelineEvent, EventType, EventBuilder
    # - Verify frozen=True, slots=True on PipelineEvent
    # - Count EventType enum values (must be exactly 14)
    # - EventBuilder methods match 1:1 with EventType values

    # Red flags:
    # - Mutable event objects (no frozen=True)
    # - Using string event types instead of enum
    # - Missing lifecycle events (especially pipeline.resumed, loop.detected)
    # - EventBuilder missing for some event types


@feature-F14 @weight-0.10
Feature: F14 — EventEmitter Protocol and CompositeEmitter

  Scenario: S14.1 — CompositeEmitter fans out to multiple backends
    Given a CompositeEmitter with LogfireEmitter, JSONLEmitter, and SignalBridge
    When emitter.emit(event) is called
    Then all three backends receive the event via asyncio.gather
    And a failure in one backend does not prevent others from receiving the event
    And aclose() closes all backends

    # Confidence scoring guide:
    # 1.0 — EventEmitter protocol with emit(event) and aclose(). CompositeEmitter uses
    #        asyncio.gather(return_exceptions=True) for fan-out. Failed backends logged
    #        but don't crash the pipeline. aclose() propagates to all backends.
    # 0.5 — CompositeEmitter exists but uses sequential emission or doesn't handle errors.
    # 0.0 — No composite pattern; single hardcoded emitter.

    # Evidence to check:
    # - cobuilder/engine/events/emitter.py — EventEmitter protocol, CompositeEmitter
    # - asyncio.gather with return_exceptions=True in CompositeEmitter.emit()
    # - aclose() method that closes all backends
    # - cobuilder/engine/tests/test_events.py — fan-out tests

    # Red flags:
    # - Sequential backend calls (no asyncio.gather)
    # - Missing return_exceptions=True (one failure crashes all)
    # - No aclose() method


@feature-F15 @weight-0.10
Feature: F15 — Logfire Backend Emitter

  Scenario: S15.1 — LogfireEmitter creates two-level span hierarchy
    Given a LogfireEmitter instance
    When pipeline.started event is emitted
    Then it opens a pipeline-level logfire span
    And when node.started event is emitted, it opens a child node-level span
    And when node.completed event is emitted, it closes the node span with attributes
    And span attributes include node_id, handler_type, outcome status, and token counts

    # Confidence scoring guide:
    # 1.0 — Two-level span hierarchy: pipeline span wraps entire execution, node spans
    #        are children. Span attributes include all relevant fields from event.data.
    #        Token counts from CodergenHandler added when present. Span IDs stored in
    #        event.span_id for correlation.
    # 0.5 — Logfire spans exist but flat (not hierarchical) or missing attributes.
    # 0.0 — No Logfire integration in event bus; print() or logging.info() used instead.

    # Evidence to check:
    # - cobuilder/engine/events/logfire_emitter.py — LogfireEmitter class
    # - import logfire at top
    # - logfire.span() calls with parent-child relationship
    # - Span attributes include node_id, handler_type, status


@feature-F16 @weight-0.05
Feature: F16 — JSONL Backend Emitter

  Scenario: S16.1 — JSONLEmitter writes events to append-mode file
    Given a JSONLEmitter configured with an output path
    When events are emitted
    Then each event is serialized to one JSON line and appended to the file
    And the file is flushed after every write
    And aclose() closes the file handle

    # Confidence scoring guide:
    # 1.0 — Append-mode file writing. Each event is one JSON line. Flush after write.
    #        aclose() properly closes file handle. PipelineEvent serialization handles
    #        datetime and enum fields.
    # 0.5 — JSONL writing works but no flush or improper serialization.
    # 0.0 — No JSONL emitter.

    # Evidence to check:
    # - cobuilder/engine/events/jsonl_emitter.py — JSONLEmitter class
    # - open() with mode="a" (append)
    # - file.flush() after each write


@feature-F17 @weight-0.07
Feature: F17 — SignalBridge

  Scenario: S17.1 — SignalBridge translates critical events to signal files
    Given a SignalBridge instance
    When pipeline.completed event is emitted
    Then it writes a completion signal via signal_protocol.write_signal()
    And pipeline.failed writes a failure signal
    And loop.detected writes ORCHESTRATOR_STUCK signal
    And node.failed writes a node failure signal
    And non-critical events (edge.selected, context.updated) are ignored

    # Confidence scoring guide:
    # 1.0 — Exactly 4 event types mapped to signals: pipeline.completed, pipeline.failed,
    #        loop.detected, node.failed. Other events silently ignored. Uses existing
    #        signal_protocol module for file writing.
    # 0.5 — Some signal mappings work but not all 4, or writes signals directly without
    #        using signal_protocol.
    # 0.0 — No SignalBridge; signals still written inline in EngineRunner.

    # Evidence to check:
    # - cobuilder/engine/events/signal_bridge.py — SignalBridge class
    # - Import of signal_protocol module
    # - Mapping of exactly 4 event types to signal writes

    # Red flags:
    # - Writing signal files directly (bypassing signal_protocol)
    # - Missing loop.detected → ORCHESTRATOR_STUCK mapping
    # - All events triggering signals (should be selective)


@feature-F18 @weight-0.15
Feature: F18 — Middleware Chain

  Scenario: S18.1 — compose_middleware creates right-to-left middleware chain
    Given middleware classes [LogfireMiddleware, TokenCountingMiddleware, RetryMiddleware]
    When compose_middleware(middlewares, handler) is called
    Then the returned handler wraps the original with middlewares in order
    And execution flows: Logfire → TokenCounting → Retry → original handler
    And each middleware can pre-process (before handler) and post-process (after handler)

    # Confidence scoring guide:
    # 1.0 — compose_middleware function with right-to-left folding. Middleware protocol
    #        with __call__(request, next_handler) signature. Each middleware can wrap
    #        the handler's execution. Integration point in EngineRunner's node execution.
    # 0.5 — Middleware chain exists but wrong composition order or missing protocol.
    # 0.0 — No middleware pattern; all logic inline in EngineRunner.

    # Evidence to check:
    # - cobuilder/engine/events/middleware.py — compose_middleware function
    # - Middleware protocol: __call__(request: HandlerRequest, next: Callable) -> Outcome
    # - cobuilder/engine/runner.py — middleware chain integration

    # Red flags:
    # - Left-to-right composition (should be right-to-left for correct wrapping)
    # - Middleware that doesn't call next_handler (breaks the chain)
    # - No integration point in EngineRunner

  Scenario: S18.2 — LogfireMiddleware wraps handler execution with spans
    Given a LogfireMiddleware instance
    When a handler is executed through the middleware
    Then it creates a logfire.span("node.execute") around the handler call
    And adds node_id, handler_type as span attributes
    And adds outcome.status after handler completes
    And on handler error, adds exception info to span

    # Confidence scoring guide:
    # 1.0 — Span wraps handler call. Attributes set before and after. Exception captured.
    # 0.5 — Span exists but missing attributes or exception handling.
    # 0.0 — No LogfireMiddleware.

    # Evidence to check:
    # - cobuilder/engine/events/middleware.py — LogfireMiddleware class
    # - logfire.span() with attributes

  Scenario: S18.3 — RetryMiddleware implements retry logic
    Given a handler that fails on first attempt but succeeds on second
    When the handler is executed through RetryMiddleware with max_retries=2
    Then it catches the failure and retries the handler
    And emits retry.triggered event via the emitter
    And updates $retry_count in PipelineContext
    And on final failure, re-raises the exception

    # Confidence scoring guide:
    # 1.0 — Retry loop with configurable max_retries. Emits retry.triggered event.
    #        Updates $retry_count in context. Exponential backoff or configurable delay.
    #        Final failure propagates exception.
    # 0.5 — Retry works but doesn't emit events or update context.
    # 0.0 — No RetryMiddleware; retry logic handled elsewhere or not at all.

    # Evidence to check:
    # - cobuilder/engine/events/middleware.py — RetryMiddleware class
    # - Retry loop with attempt counter
    # - Event emission and context update

  Scenario: S18.4 — TokenCountingMiddleware extracts token usage
    Given a CodergenHandler that returns an Outcome with raw_messages
    When the handler is executed through TokenCountingMiddleware
    Then it inspects outcome.raw_messages for token usage data
    And adds token counts to the emitted node.completed event data
    And stores total_tokens in PipelineContext as $tokens.<node_id>

    # Confidence scoring guide:
    # 1.0 — Extracts token counts from raw_messages (AMD-7). Adds to event data.
    #        Stores in context with node-scoped key. Handles missing raw_messages gracefully.
    # 0.5 — Token counting exists but doesn't store in context or misses raw_messages.
    # 0.0 — No token counting middleware.

    # Evidence to check:
    # - cobuilder/engine/events/middleware.py — TokenCountingMiddleware class
    # - Inspection of Outcome.raw_messages field (AMD-7)

  Scenario: S18.5 — AuditMiddleware logs handler requests and outcomes
    Given an AuditMiddleware instance
    When a handler is executed
    Then it logs the HandlerRequest details before execution
    And logs the Outcome details after execution
    And logs exceptions if the handler fails
    And audit entries are written to the JSONL emitter

    # Confidence scoring guide:
    # 1.0 — Pre and post handler logging. Uses structured event emission.
    #        Captures timing (execution duration). Exception logging on failure.
    # 0.5 — Audit exists but uses print() instead of structured events.
    # 0.0 — No AuditMiddleware.

    # Evidence to check:
    # - cobuilder/engine/events/middleware.py — AuditMiddleware class


@feature-F19 @weight-0.05
Feature: F19 — HandlerRequest Integration (AMD-8)

  Scenario: S19.1 — HandlerRequest carries emitter and middleware context
    Given a HandlerRequest dataclass
    Then it has fields: node, context, emitter, pipeline_id, visit_count,
         attempt_number, run_dir
    And the emitter field allows handlers to emit events directly
    And EngineRunner constructs HandlerRequest before each handler call

    # Confidence scoring guide:
    # 1.0 — All 7 fields present. Handlers receive events via request.emitter.
    #        EngineRunner constructs request with correct values from runtime state.
    #        visit_count from LoopDetector, attempt_number from RetryMiddleware.
    # 0.5 — HandlerRequest exists but missing emitter or run_dir fields.
    # 0.0 — Handlers still use (Node, PipelineContext) signature (pre-AMD-8).

    # Evidence to check:
    # - cobuilder/engine/handlers/base.py — HandlerRequest dataclass
    # - cobuilder/engine/runner.py — HandlerRequest construction
    # - All handler execute() methods accept HandlerRequest

    # Red flags:
    # - Handler protocol uses (Node, PipelineContext) instead of HandlerRequest
    # - Missing emitter field (handlers can't emit events)
    # - visit_count or attempt_number hardcoded to 0
