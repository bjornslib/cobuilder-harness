@epic-E7.2 @sd-HARNESS-UPGRADE-001-E7.2
Feature: Pure Python DOT Runner

  # Epic 7.2 replaces the LLM-based guardian with a pure Python state machine
  # for graph traversal, eliminating ~$4.91 per pipeline run.
  # Prerequisite: E7.1 (Worker Prompt Restructuring)
  # SD: docs/sds/harness-upgrade/SD-HARNESS-UPGRADE-001-E7-python-runner.md
  # Evidence: .claude/attractor/ATTRACTOR-E2E-ANALYSIS.md (Issue 4)

  @feature-F7.2.1 @weight-0.03
  Scenario: S7.2.1 — pipeline_runner.py exists and has CLI
    Given the .claude/scripts/attractor/ directory exists
    When I check for pipeline_runner.py
    Then the file exists and imports cleanly (python3 -c "import pipeline_runner")
    And running "python3 pipeline_runner.py --help" shows:
      - --dot-file (required)
      - --resume flag
      - --poll-interval option
      - --default-worktree option

    # Confidence scoring guide:
    # 1.0 — File exists, imports cleanly, --help shows all 4 options
    # 0.5 — File exists but import errors or missing CLI options
    # 0.0 — File does not exist

    # Red flags:
    # - File named pipeline_orchestrator.py (old name)
    # - --sketch-preflight flag present (removed)

  @feature-F7.2.2 @weight-0.04
  Scenario: S7.2.2 — Dispatchable node discovery respects dependency state
    Given a pipeline with nodes A -> B -> C where A is validated and B is pending
    When _find_dispatchable_nodes() is called
    Then B is returned (A validated, B's deps met)
    And C is NOT returned (B not yet validated)

    Given a pipeline where B has two predecessors A1 and A2, A1 is validated, A2 is pending
    When _find_dispatchable_nodes() is called
    Then B is NOT returned (not all deps validated)

    # Confidence scoring guide:
    # 1.0 — Correct dependency checking with unit tests for both cases
    # 0.5 — Basic dependency checking but edge cases not tested
    # 0.0 — No dependency checking (dispatches all pending nodes)

  @feature-F7.2.3 @weight-0.04
  Scenario: S7.2.3 — Codergen handler dispatches worker via SDK
    Given a codergen node with sd_path, worker_type, and worktree attributes
    When _handle_codergen(node) is called
    Then dispatch_worker() is called via SDK (_run_agent()) with:
      - node_id matching the node
      - dot_file matching the pipeline
      - sd_path from the node attributes
      - worker_type from the node attributes
      - signal_dir matching the runner's signal directory
    And the returned process is tracked in active_processes
    And NO sketch pre-flight is run (removed — replaced by guardian reflection at gates)

    # Confidence scoring guide:
    # 1.0 — All parameters passed correctly, process tracked, no sketch pre-flight
    # 0.5 — Dispatch works but missing some parameters
    # 0.0 — Handler doesn't call dispatch_worker

    # Red flags:
    # - sketch pre-flight code still present
    # - tmux or headless CLI used instead of SDK
    # - worker_type not passed to dispatch

  @feature-F7.2.4 @weight-0.03
  Scenario: S7.2.4 — Tool handler runs command without LLM
    Given a tool node with command="echo hello" and timeout=30
    When _handle_tool(node) is called
    Then subprocess.run is called with the command
    And a signal file is written with:
      - status: "success" (for exit code 0)
      - stdout containing "hello"
    And NO LLM API calls are made during this handler execution

    # Confidence scoring guide:
    # 1.0 — Command executed, signal written, verified no LLM calls
    # 0.5 — Command executed but signal format incorrect
    # 0.0 — Handler doesn't execute command or uses LLM

  @feature-F7.2.5 @weight-0.04
  Scenario: S7.2.5 — System3 gate handler with guardian reflection
    Given a wait.system3 node with gate_type="e2e" and summary_ref path
    And predecessor codergen nodes have completed with signal files
    When _handle_system3(node) is called
    Then the handler:
      - Reads signal files from completed predecessor workers
      - Reads concerns.jsonl if it exists
      - Reflects via Hindsight (confidence trend, concern patterns)
      - Runs Gherkin E2E acceptance tests
      - Checks PRD Contract if contract_ref is set
      - Writes gate summary to summary_ref path
      - Writes signal file with pass/fail status
    And if critical concerns exist or tests fail:
      - May requeue predecessor codergen back to "pending" (max 2 retries)
      - Transitions gate to "failed"

    # Confidence scoring guide:
    # 1.0 — Full guardian reflection: signals, concerns, Hindsight, tests, requeue
    # 0.5 — Gate handler exists but skips reflection or requeue
    # 0.0 — No system3 handler implementation

    # Red flags:
    # - Sketch pre-flight used instead of post-hoc reflection
    # - No requeue mechanism on failure
    # - Concerns.jsonl ignored

  @feature-F7.2.6 @weight-0.06
  Scenario: S7.2.6 — Full pipeline run with zero LLM graph traversal tokens
    Given the simple-pipeline.dot test file exists
    And pipeline_runner.py is available
    When I run "python3 pipeline_runner.py --dot-file simple-pipeline.dot"
    Then the pipeline completes (all nodes reach terminal state)
    And the ONLY LLM API calls are for worker nodes (codergen/research/refine)
    And graph traversal (node discovery, state transitions, signal polling, checkpoints) uses ZERO LLM tokens
    And the total cost for graph traversal is ~$0 (Python only)

    # Confidence scoring guide:
    # 1.0 — Pipeline completes, verified zero LLM graph tokens via cost tracking
    # 0.5 — Pipeline completes but some graph operations still use LLM
    # 0.0 — Pipeline fails or uses LLM for graph traversal

    # Evidence to check:
    # - Run pipeline_runner.py on simple-pipeline.dot
    # - Check Logfire/logs for LLM API calls — only worker nodes should have them
    # - Compare total cost with E2E analysis ($10.77 with guardian LLM vs ~$5.86 without)

    # Red flags:
    # - Any LLM call in main loop, _find_dispatchable_nodes, _poll_completions
    # - Pipeline hangs (infinite loop, missing signal files)
    # - Checkpoint not saved after transitions
