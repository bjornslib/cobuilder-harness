# PRD-PIPELINE-ENGINE-001 Epic 1: Core Execution Engine
# Blind acceptance rubric — generated from SD-PIPELINE-ENGINE-001-epic1-core-engine.md
# Guardian: Do NOT share this file with orchestrators or workers.

@feature-F1 @weight-0.15
Feature: F1 — Custom Recursive-Descent DOT Parser

  Scenario: S1.1 — Parser produces typed Graph from DOT file
    Given a DOT file with Mdiamond, Msquare, box, diamond, and hexagon nodes
    When DotParser.parse_file(path) is called
    Then it returns a Graph dataclass with typed Node and Edge objects
    And each Node has correct shape, id, label, and attrs
    And each Edge has source, target, condition, label, and weight

    # Confidence scoring guide:
    # 1.0 — Typed Graph returned with all 9+ Attractor attributes extracted; parser handles
    #        quoted strings, escaped chars, subgraphs, multi-line attrs. Tests confirm all shapes.
    # 0.5 — Graph returned but some attributes missing or not typed correctly (e.g., bead_id,
    #        solution_design, dispatch_strategy). Parser works on simple DOTs but fails on complex ones.
    # 0.0 — Parser does not exist, returns raw dicts, or imports graphviz/pydot library.

    # Evidence to check:
    # - cobuilder/engine/parser.py — DotParser class with recursive-descent logic
    # - cobuilder/engine/graph.py — Graph, Node, Edge dataclasses
    # - cobuilder/engine/tests/test_parser.py — unit tests covering all 9+ attrs
    # - Verify NO imports of graphviz, pydot, or pydotplus

    # Red flags:
    # - Using regex-only parsing (no recursive descent)
    # - Missing edge condition/weight extraction
    # - Tests that only parse trivial 2-node graphs
    # - Importing any external DOT parsing library

  Scenario: S1.2 — Parser handles existing pipeline corpus
    Given all .dot files in .claude/attractor/pipelines/
    When DotParser.parse_file() is called on each
    Then all files parse without raising ParseError
    And graph-level attributes (prd_ref, default_max_retry) are extracted

    # Confidence scoring guide:
    # 1.0 — Regression test iterates over real .dot files and all parse successfully.
    # 0.5 — Some files parse but others fail (complex attribute formats).
    # 0.0 — No regression corpus test exists.

    # Evidence to check:
    # - cobuilder/engine/tests/test_parser.py — parametrised test over real .dot files
    # - Check that test actually reads from .claude/attractor/pipelines/

    # Red flags:
    # - Hardcoded test DOT strings only (no real file corpus test)

  Scenario: S1.3 — Parser error reporting
    Given a malformed DOT file with a missing closing brace
    When DotParser.parse_file() is called
    Then it raises ParseError with line number and snippet of the error location

    # Confidence scoring guide:
    # 1.0 — ParseError includes line_number, column, and a snippet of the offending line.
    # 0.5 — ParseError raised but without location information.
    # 0.0 — Generic exception or no error on malformed input.

    # Evidence to check:
    # - cobuilder/engine/exceptions.py — ParseError class with line_number field
    # - cobuilder/engine/tests/test_parser.py — test for malformed DOT


@feature-F3 @weight-0.08
Feature: F3 — Handler Registry and Protocol

  Scenario: S3.1 — Registry dispatches correct handler per shape
    Given a HandlerRegistry with all 9 handler types registered
    When registry.dispatch(node) is called for each known shape
    Then the correct handler instance is returned for each shape
    And UnknownShapeError is raised for an unrecognised shape

    # Confidence scoring guide:
    # 1.0 — All 9 shapes map to correct handlers. UnknownShapeError includes shape name.
    #        Registry supports dependency injection (custom handler dict in constructor).
    # 0.5 — Most shapes registered but missing 1-2. No DI support.
    # 0.0 — No registry exists, or handlers are dispatched via if/elif chains.

    # Evidence to check:
    # - cobuilder/engine/handlers/registry.py — HandlerRegistry class
    # - cobuilder/engine/handlers/base.py — Handler protocol with HandlerRequest (AMD-8)
    # - cobuilder/engine/tests/test_handlers.py — dispatch tests

    # Red flags:
    # - Handler protocol uses (Node, PipelineContext) instead of HandlerRequest (AMD-8 violation)
    # - Registry uses isinstance checks instead of shape string mapping


@feature-F6 @weight-0.15
Feature: F6 — CodergenHandler (tmux + sdk dispatch)

  Scenario: S6.1 — CodergenHandler tmux dispatch with signal polling (AMD-1)
    Given a box node with dispatch_strategy=tmux
    When CodergenHandler.execute(request) is called
    Then it writes prompt to run_dir/nodes/<node_id>/prompt.md
    And it calls spawn_orchestrator with correct arguments
    And it polls for {node_id}-complete.signal every 10 seconds
    And on finding complete signal, returns Outcome(status=SUCCESS)

    # Confidence scoring guide:
    # 1.0 — Full AMD-1 protocol implemented: write prompt, spawn, poll signals, handle
    #        complete/failed/needs-review signals, write outcome.json. Timeout at 3600s.
    # 0.5 — Spawn works but signal polling is stub/mocked. No timeout handling.
    # 0.0 — CodergenHandler is a no-op stub or doesn't exist.

    # Evidence to check:
    # - cobuilder/engine/handlers/codergen.py — signal polling loop
    # - Look for asyncio.sleep(poll_interval) in the polling loop
    # - Check for ATTRACTOR_SIGNAL_POLL_INTERVAL env var support
    # - run_dir/nodes/<node_id>/prompt.md write logic
    # - run_dir/nodes/<node_id>/outcome.json write logic

    # Red flags:
    # - Synchronous polling (no async/await)
    # - No timeout mechanism
    # - Missing signal file path construction
    # - Tests that mock everything (no real file system interaction)

  Scenario: S6.2 — CodergenHandler sdk dispatch
    Given a box node with dispatch_strategy=sdk
    When CodergenHandler.execute(request) is called
    Then it calls claude_code_sdk.query() with the node prompt
    And converts the SDK response to an Outcome with raw_messages (AMD-7)

    # Confidence scoring guide:
    # 1.0 — SDK dispatch path exists, calls query(), maps response to Outcome with raw_messages.
    # 0.5 — SDK path exists but raw_messages not populated.
    # 0.0 — Only tmux dispatch implemented, no SDK path.

    # Evidence to check:
    # - cobuilder/engine/handlers/codergen.py — dispatch_strategy branching
    # - Outcome.raw_messages population from SDK response
    # - Import of claude_code_sdk


@feature-F14-F15 @weight-0.10
Feature: F14-F15 — Outcome Model + PipelineContext

  Scenario: S14.1 — Outcome is immutable with correct fields
    Given an Outcome dataclass
    Then it has status, context_updates, preferred_label, suggested_next, metadata, raw_messages
    And it is frozen (immutable after construction)
    And OutcomeStatus enum has SUCCESS, FAILURE, PARTIAL_SUCCESS, WAITING, SKIPPED

    # Confidence scoring guide:
    # 1.0 — All 6 fields present, frozen=True, OutcomeStatus has all 5 values, raw_messages
    #        defaults to empty list (AMD-7).
    # 0.5 — Missing raw_messages or missing some OutcomeStatus values.
    # 0.0 — Outcome doesn't exist or is a plain dict.

    # Evidence to check:
    # - cobuilder/engine/outcome.py — Outcome and OutcomeStatus

  Scenario: S14.2 — PipelineContext thread-safe with fan-out merge (AMD-2)
    Given a PipelineContext with initial data
    When multiple threads access get/update/snapshot concurrently
    Then operations are thread-safe (no data races)
    And merge_fan_out_results namespaces branch updates by branch_node_id
    And built-in keys ($retry_count, $node_visits, $last_status, $pipeline_duration_s) are maintained

    # Confidence scoring guide:
    # 1.0 — Thread-safe via Lock, merge_fan_out_results namespaces keys as {branch_id}.{key},
    #        increment_visit method exists, all 4 built-in $-prefixed keys documented.
    # 0.5 — Thread safety exists but fan-out merge uses flat merge (AMD-2 violation).
    # 0.0 — PipelineContext is a plain dict or not thread-safe.

    # Evidence to check:
    # - cobuilder/engine/context.py — PipelineContext class with Lock
    # - merge_fan_out_results method (NOT merge_snapshot — AMD-2 renamed it)
    # - cobuilder/engine/tests/test_context.py — concurrency tests

    # Red flags:
    # - Method named merge_snapshot (pre-AMD-2 name)
    # - No threading.Lock usage
    # - Fan-out merge that overwrites without namespacing


@feature-F16 @weight-0.12
Feature: F16 — EdgeSelector (5-step algorithm)

  Scenario: S16.1 — EdgeSelector follows 5-step priority
    Given a node with multiple outgoing edges (conditional, labeled, weighted, default)
    When EdgeSelector.select(node, outcome, context) is called
    Then Step 1 evaluates edge conditions against context (via injected evaluator)
    And Step 2 matches outcome.preferred_label against edge labels
    And Step 3 matches outcome.suggested_next against edge targets
    And Step 4 selects highest weight among remaining edges
    And Step 5 falls back to first unlabeled/unconditioned edge
    And NoEdgeError is raised when no step produces a result

    # Confidence scoring guide:
    # 1.0 — All 5 steps implemented in correct priority order. Condition evaluator is
    #        injected (not hardcoded). NoEdgeError raised correctly. Tests cover each step
    #        in isolation and in combination.
    # 0.5 — Some steps work but ordering is wrong, or condition evaluation is stubbed.
    # 0.0 — EdgeSelector is a simple first-match or doesn't exist.

    # Evidence to check:
    # - cobuilder/engine/edge_selector.py — EdgeSelector class with 5-step algorithm
    # - Constructor accepts condition_evaluator parameter (dependency injection)
    # - cobuilder/engine/tests/test_edge_selector.py — tests per step

    # Red flags:
    # - Hardcoded condition evaluation (should be injected from Epic 3)
    # - Missing NoEdgeError
    # - Steps not in correct priority order (1→2→3→4→5)


@feature-F17 @weight-0.10
Feature: F17 — CheckpointManager (atomic write/load)

  Scenario: S17.1 — Checkpoint atomic write and resume
    Given a CheckpointManager
    When save(checkpoint) is called
    Then it writes to checkpoint.json.tmp first then renames atomically
    And load_or_create() returns fresh checkpoint if no file exists
    And load_or_create() loads existing checkpoint and validates schema version
    And CheckpointVersionError is raised on schema mismatch

    # Confidence scoring guide:
    # 1.0 — Atomic write-rename pattern implemented. Schema version validation.
    #        EngineCheckpoint tracks completed_nodes, current_node_id, context snapshot,
    #        visit_counts. Pydantic model with serialization.
    # 0.5 — Checkpoint works but not atomic (direct write, no rename) or no version check.
    # 0.0 — No checkpoint system exists.

    # Evidence to check:
    # - cobuilder/engine/checkpoint.py — CheckpointManager + EngineCheckpoint
    # - Look for os.rename or Path.rename in save()
    # - Schema version constant (ENGINE_CHECKPOINT_VERSION)
    # - cobuilder/engine/tests/test_checkpoint.py

    # Red flags:
    # - json.dump directly to final path (not atomic)
    # - No schema version in checkpoint model
    # - Tests that don't verify atomicity


@feature-F18 @weight-0.20
Feature: F18 — EngineRunner (main loop)

  Scenario: S18.1 — Linear pipeline end-to-end traversal
    Given a 3-node DOT pipeline (start → codergen → exit) with mock handlers
    When EngineRunner.run() is called
    Then nodes are executed in topological order
    And checkpoint is saved after each node
    And the pipeline completes with SUCCESS status

    # Confidence scoring guide:
    # 1.0 — Full integration test with mock handlers. Real DOT file parsed, traversed,
    #        checkpointed at each step. Exit handler checks goal gates. CLI subcommand works.
    # 0.5 — Runner loop exists but only tested with in-memory graphs (no DOT parsing).
    # 0.0 — EngineRunner doesn't exist or has no tests.

    # Evidence to check:
    # - cobuilder/engine/runner.py — EngineRunner class with run() method
    # - cobuilder/engine/tests/test_runner.py — integration test with mock handlers
    # - Test uses a real .dot file (even if minimal)

    # Red flags:
    # - No async (engine should be async for CodergenHandler compatibility)
    # - No checkpoint between nodes
    # - Tests with no assertions on execution order

  Scenario: S18.2 — Resume from checkpoint
    Given a checkpoint file with 2 of 4 nodes completed
    When EngineRunner.run(resume=True) is called
    Then it loads the checkpoint and skips completed nodes
    And execution resumes from current_node_id

    # Confidence scoring guide:
    # 1.0 — Resume loads checkpoint, skips nodes in completed_nodes set, resumes execution.
    #        Test verifies skip behavior with mock that tracks call count.
    # 0.5 — Resume path exists but not tested.
    # 0.0 — No resume support.

    # Evidence to check:
    # - cobuilder/engine/runner.py — resume logic in run()
    # - cobuilder/engine/tests/test_runner.py — resume test

  Scenario: S18.3 — Error handling produces correct signals
    Given a handler that raises HandlerError
    When EngineRunner.run() encounters the error
    Then it writes ORCHESTRATOR_CRASHED signal via signal_protocol
    And it saves checkpoint before exiting
    And it exits with non-zero status code

    # Confidence scoring guide:
    # 1.0 — HandlerError, LoopDetectedError, NoEdgeError all handled with correct signals.
    #        KeyboardInterrupt saves checkpoint with "paused" message.
    # 0.5 — Some error types handled but not all.
    # 0.0 — Errors propagate as unhandled exceptions.

    # Evidence to check:
    # - cobuilder/engine/runner.py — except blocks in run()
    # - Signal writes for ORCHESTRATOR_CRASHED, ORCHESTRATOR_STUCK
    # - cobuilder/engine/tests/test_runner.py — error scenario tests

    # Red flags:
    # - Bare except: clauses
    # - No signal writing on failure
    # - Checkpoint not saved before exit on error


@feature-F19-F20 @weight-0.10
Feature: F19-F20 — CLI Integration + Logfire Spans

  Scenario: S19.1 — CLI run and validate subcommands
    Given cobuilder CLI with pipeline subcommand group
    When "cobuilder pipeline run --help" is invoked
    Then it shows all flags (--resume, --skip-validation, dot_path)
    And "cobuilder pipeline run nonexistent.dot" exits 1 with file not found
    And "cobuilder pipeline validate pipeline.dot" runs the validator

    # Confidence scoring guide:
    # 1.0 — Both run and validate subcommands registered in CLI. Help text complete.
    #        Error messages user-friendly. --resume flag functional.
    # 0.5 — Commands registered but incomplete flags or poor error messages.
    # 0.0 — No CLI integration (engine only callable programmatically).

    # Evidence to check:
    # - cobuilder/cli.py — pipeline_app with run/validate commands
    # - Click or Typer command definitions

  Scenario: S20.1 — Logfire spans wrap pipeline and node execution
    Given EngineRunner executing a pipeline
    When a pipeline run completes
    Then a logfire.span("pipeline.run") wraps the entire execution
    And each node gets a child logfire.span("node.execute")
    And outcome.status and metadata are added as span attributes

    # Confidence scoring guide:
    # 1.0 — Pipeline-level and node-level spans. Attributes include node_id, handler_type,
    #        outcome status. Token counts from CodergenHandler added when present.
    # 0.5 — Logfire imported but spans are incomplete or missing attributes.
    # 0.0 — No Logfire integration in Epic 1.

    # Evidence to check:
    # - cobuilder/engine/runner.py — logfire.span() calls
    # - import logfire at top of runner.py
    # - Span attributes include node_id, handler_type, status

    # Red flags:
    # - print() used instead of logfire
    # - Spans without attributes
