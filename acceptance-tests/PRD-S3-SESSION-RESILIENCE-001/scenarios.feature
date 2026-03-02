@prd-S3-SESSION-RESILIENCE-001

# ============================================================
# Epic 1: Agent Identity Registry (weight: 0.40)
# ============================================================

@feature-F001 @weight-0.40 @epic-1
Feature: Agent Identity Registry — Identity Creation

  Scenario: F001 — Identity file created at spawn time
    Given spawn_orchestrator.py is called with --node test_node --prd PRD-TEST-001
    When the spawn sequence completes
    Then .claude/state/identities/orchestrator-test_node.json exists
    And the identity file contains status "active"
    And the identity file contains a non-null created_at timestamp
    And the identity file contains the correct prd_id and node_id

    # Confidence scoring guide:
    # 1.0 — identity_registry.py implements create_identity(), spawn_orchestrator.py calls it,
    #        identity file written with all required fields, test_identity_registry.py has passing test
    # 0.5 — Module exists but spawn integration missing OR test exists but fields incomplete
    # 0.0 — identity_registry.py does not exist or create_identity not implemented

    # Evidence to check:
    # - .claude/scripts/attractor/identity_registry.py: create_identity() function
    # - .claude/scripts/attractor/spawn_orchestrator.py: import + call to create_identity
    # - .claude/scripts/attractor/tests/test_identity_registry.py: test for AC-1.1
    # - .claude/state/identities/ directory structure

    # Red flags:
    # - identity_registry.py exists but create_identity() is a stub/pass
    # - spawn_orchestrator.py does not import identity_registry
    # - No test file for identity_registry
    # - Identity file schema missing required fields (uuid, status, created_at, prd_id)


  Scenario: F002 — Liveness heartbeat updates last_seen every 60s
    Given an active identity file exists for orchestrator-test_node
    When update_liveness.py --identity test_node is called
    Then the identity file's last_seen field is updated to within 5 seconds of now

    # Confidence scoring guide:
    # 1.0 — update_liveness() implemented with atomic write, CLI wrapper exists,
    #        runner_agent.py system prompt includes liveness update instructions,
    #        test verifies last_seen changes
    # 0.5 — Function exists but CLI wrapper or runner integration missing
    # 0.0 — update_liveness() not implemented

    # Evidence to check:
    # - identity_registry.py: update_liveness() function
    # - update_liveness.py: CLI wrapper script
    # - runner_agent.py: system prompt mentions liveness update
    # - test_identity_registry.py: test for AC-1.2

    # Red flags:
    # - update_liveness() modifies file without atomic write (no tmp+rename)
    # - No CLI wrapper (update_liveness.py missing)
    # - runner_agent.py system prompt unchanged


  Scenario: F003 — Stale identity detected within one monitoring cycle
    Given an identity file with last_seen set to 6 minutes ago
    When find_stale(threshold_seconds=300) is called
    Then the stale identity appears in the results list

    # Confidence scoring guide:
    # 1.0 — find_stale() compares last_seen against threshold, returns list of stale identities,
    #        guardian_agent.py system prompt includes stale scan instructions, test passes
    # 0.5 — find_stale() exists but threshold logic incorrect or guardian not integrated
    # 0.0 — find_stale() not implemented

    # Evidence to check:
    # - identity_registry.py: find_stale() function with threshold parameter
    # - guardian_agent.py: system prompt mentions stale identity scanning
    # - test_identity_registry.py: test for AC-1.3

    # Red flags:
    # - find_stale() returns all identities instead of filtering by staleness
    # - Threshold hardcoded instead of parameterized
    # - No 3-strike confirmation logic documented


  Scenario: F004 — Re-spawned orchestrator has predecessor_id
    Given a previous orchestrator session "old_session" has been marked crashed
    When spawn_orchestrator.py --predecessor-id old_session is called
    Then the new identity file contains predecessor_id "old_session"

    # Confidence scoring guide:
    # 1.0 — spawn_orchestrator.py accepts --predecessor-id flag, passes to create_identity(),
    #        identity schema includes predecessor_id field, test verifies chain
    # 0.5 — Flag accepted but not stored in identity file OR stored but not tested
    # 0.0 — --predecessor-id flag not implemented

    # Evidence to check:
    # - spawn_orchestrator.py: --predecessor-id CLI argument parsing
    # - identity_registry.py: create_identity() accepts predecessor_id parameter
    # - test_spawn_orchestrator.py: test for AC-1.4

    # Red flags:
    # - --predecessor-id accepted but silently ignored
    # - predecessor_id field not in identity JSON schema


  Scenario: F005 — CLI agents command returns machine-readable output
    Given two identity files exist in .claude/state/identities/
    When cli.py agents --json is called
    Then the output is valid JSON containing an array of 2 identity objects
    And each object has fields: identity_name, status, last_seen, prd_id

    # Confidence scoring guide:
    # 1.0 — agents_cmd.py implements list handler, cli.py dispatches "agents" subcommand,
    #        --json flag outputs valid JSON, --stale-only flag filters correctly, test passes
    # 0.5 — Subcommand exists but missing --json or --stale-only flag
    # 0.0 — agents subcommand not added to cli.py

    # Evidence to check:
    # - agents_cmd.py: handler functions
    # - cli.py: "agents" dispatch branch in main()
    # - test_cli.py: test for AC-1.5

    # Red flags:
    # - cli.py help text not updated with agents subcommand
    # - agents_cmd.py outputs text instead of JSON when --json passed


# ============================================================
# Epic 2: Persistent Work State Hook Files (weight: 0.30)
# ============================================================

@feature-F006 @weight-0.30 @epic-2
Feature: Persistent Work State — Hook File Management

  Scenario: F006 — Hook file created at spawn time with initial scope
    Given spawn_orchestrator.py is called with --node epic1 --prd PRD-TEST-001
    When the spawn sequence completes
    Then .claude/state/hooks/epic1.json exists
    And the hook file contains current_phase "investigation"
    And the hook file contains the correct node_id and pipeline_id

    # Confidence scoring guide:
    # 1.0 — hook_manager.py implements create_hook(), spawn_orchestrator.py calls it,
    #        hook file written with all fields from SD Section 2.3, test passes
    # 0.5 — Module exists but spawn integration missing OR schema incomplete
    # 0.0 — hook_manager.py does not exist

    # Evidence to check:
    # - .claude/scripts/attractor/hook_manager.py: create_hook() function
    # - spawn_orchestrator.py: import + call to create_hook after create_identity
    # - test_hook_manager.py: test for AC-2.1

    # Red flags:
    # - hook_manager.py is a stub
    # - Hook schema missing work_summary or resumption_instructions fields
    # - No atomic write pattern (tmp+rename)


  Scenario: F007 — Hook work_phase updates on orchestrator phase transition
    Given an active hook file exists for node epic1
    When the runner detects orchestrator output indicating "planning" phase
    And update_hook_phase.py --node epic1 --phase planning is called
    Then the hook file shows current_phase "planning"

    # Confidence scoring guide:
    # 1.0 — update_phase() changes current_phase atomically, CLI wrapper exists,
    #        runner_agent.py system prompt includes phase detection instructions,
    #        HOOK_UPDATED signal written, test passes
    # 0.5 — update_phase() works but runner integration or signal missing
    # 0.0 — update_phase() not implemented

    # Evidence to check:
    # - hook_manager.py: update_phase() function
    # - update_hook_phase.py: CLI wrapper
    # - runner_agent.py: phase transition detection in system prompt
    # - signal_protocol.py: HOOK_UPDATED in VALID_SIGNAL_TYPES
    # - test_hook_manager.py: test for AC-2.2

    # Red flags:
    # - Phase values not validated against allowed set
    # - No HOOK_UPDATED signal emission
    # - runner_agent.py unchanged


  Scenario: F008 — Re-spawned session wisdom includes hook context
    Given a hook file exists with current_phase "implementation" and work_summary "Working on JWT"
    When spawn_orchestrator.py is called with --predecessor-id old_id
    Then the tmux wisdom prompt contains "Resume from phase: implementation"
    And the wisdom prompt contains "Working on JWT"

    # Confidence scoring guide:
    # 1.0 — spawn_orchestrator.py reads hook file on respawn, injects phase + summary into wisdom,
    #        test verifies wisdom prompt content
    # 0.5 — Hook read works but wisdom prompt formatting incomplete
    # 0.0 — spawn_orchestrator.py does not read hooks on respawn

    # Evidence to check:
    # - spawn_orchestrator.py: hook reading in respawn path
    # - hook_manager.py: read_hook() function
    # - test_spawn_orchestrator.py: test for AC-2.3

    # Red flags:
    # - respawn_orchestrator() exists but does not call read_hook()
    # - Wisdom prompt template missing hook context block


  Scenario: F009 — Re-spawned session skips already-completed phases
    Given a hook with resumption_instructions naming the last incomplete step
    When the wisdom prompt is built from hook context
    Then the prompt contains explicit instructions to skip completed phases

    # Confidence scoring guide:
    # 1.0 — context_monitor.build_wisdom_prompt_block() reads resumption_instructions,
    #        formats skip instructions, test verifies content
    # 0.5 — Function exists but resumption_instructions not used
    # 0.0 — build_wisdom_prompt_block() not implemented

    # Evidence to check:
    # - context_monitor.py: build_wisdom_prompt_block() function
    # - test_context_monitor.py: test for AC-2.4

    # Red flags:
    # - Wisdom block is generic "resume work" without specific phase skip instructions


  Scenario: F010 — Hook file survives concurrent writes without corruption
    Given 5 concurrent threads calling update_phase with different phases
    When all threads complete
    Then the hook file is valid JSON
    And current_phase is one of the valid phase values

    # Confidence scoring guide:
    # 1.0 — Atomic write pattern (tmp+rename) used consistently, concurrent test passes,
    #        no data corruption under race conditions
    # 0.5 — Atomic write used but test not present or not testing concurrency
    # 0.0 — Direct file write without atomic pattern

    # Evidence to check:
    # - hook_manager.py: _atomic_write() or equivalent pattern
    # - test_hook_manager.py: concurrent write test for AC-2.5

    # Red flags:
    # - open("w") instead of tmp+rename pattern
    # - No concurrent write test


# ============================================================
# Epic 3: Sequential Merge Queue (weight: 0.20)
# ============================================================

@feature-F011 @weight-0.20 @epic-3
Feature: Sequential Merge Queue — Ordered Branch Merging

  Scenario: F011 — Two simultaneous MERGE_READY signals processed sequentially
    Given two entries are enqueued in rapid succession
    When process_next() is called in a loop
    Then only one entry has status "processing" at any time
    And both entries end up "merged" in sequence

    # Confidence scoring guide:
    # 1.0 — merge_queue.py implements enqueue() + process_next() with single-processing
    #        semaphore, test verifies sequential ordering
    # 0.5 — Functions exist but no single-processing guard
    # 0.0 — merge_queue.py does not exist

    # Evidence to check:
    # - merge_queue.py: enqueue(), dequeue_next(), process_next()
    # - merge_queue.py: "processing" field as distributed semaphore
    # - test_merge_queue.py: test for AC-3.1

    # Red flags:
    # - No "processing" field guard — parallel processing possible
    # - test_merge_queue.py uses mocks that hide the ordering issue


  Scenario: F012 — Clean merge: rebase, test, merge, delete branch
    Given two worktrees with non-conflicting changes are enqueued
    When the queue is processed
    Then both branches are merged to main with no conflicts
    And worktree branches are deleted after merge

    # Confidence scoring guide:
    # 1.0 — rebase_and_test() + merge_branch() implemented with subprocess calls,
    #        integration test with real git repo fixture passes, branch cleanup confirmed
    # 0.5 — Functions exist but integration test missing or branch cleanup not implemented
    # 0.0 — rebase_and_test() or merge_branch() not implemented

    # Evidence to check:
    # - merge_queue.py: rebase_and_test(), merge_branch()
    # - test_merge_queue_integration.py: test for AC-3.2 with git fixture

    # Red flags:
    # - subprocess.run() calls without timeout parameter
    # - No branch deletion after successful merge
    # - Integration test uses mocks instead of real git operations


  Scenario: F013 — Conflict detected and escalated via MERGE_CONFLICT signal
    Given two worktrees modifying the same file are enqueued
    When the second entry is processed after the first merges
    Then a MERGE_CONFLICT signal is written
    And the signal contains the conflicting_files list

    # Confidence scoring guide:
    # 1.0 — Conflict detection in rebase_and_test(), MERGE_CONFLICT signal written with
    #        conflicting_files list, integration test with conflicting changes passes
    # 0.5 — Conflict detected but signal not written or missing file list
    # 0.0 — No conflict handling

    # Evidence to check:
    # - merge_queue.py: conflict detection logic in rebase_and_test()
    # - signal_protocol.py: MERGE_CONFLICT in VALID_SIGNAL_TYPES
    # - test_merge_queue_integration.py: test for AC-3.3

    # Red flags:
    # - CalledProcessError caught but no signal written
    # - conflicting_files field empty or hardcoded


  Scenario: F014 — CLI merge-queue list shows queue state with ordering
    Given 3 entries enqueued at different timestamps
    When cli.py merge-queue list --json is called
    Then the output is valid JSON with 3 entries sorted by requested_at

    # Confidence scoring guide:
    # 1.0 — merge_queue_cmd.py implements list handler, cli.py dispatches subcommand,
    #        --json flag works, test verifies ordering
    # 0.5 — Subcommand exists but ordering not guaranteed or --json missing
    # 0.0 — merge-queue subcommand not added to cli.py

    # Evidence to check:
    # - merge_queue_cmd.py: list handler
    # - cli.py: "merge-queue" dispatch branch
    # - test_cli.py: test for AC-3.4

    # Red flags:
    # - cli.py help text not updated
    # - No timestamp-based sorting


  Scenario: F015 — Zero direct merges to main in orchestrator/runner prompts
    Given spawn_orchestrator.py and runner_agent.py system prompts
    When the prompts are searched for merge-to-main instructions
    Then neither contains "merge" or "gh pr merge" commands
    And all merge operations are routed through the merge queue

    # Confidence scoring guide:
    # 1.0 — Contract test passes: no direct merge instructions in system prompts,
    #        runner emits MERGE_READY signal instead of merging directly
    # 0.5 — Most merge paths go through queue but one direct path remains
    # 0.0 — System prompts still contain direct merge instructions

    # Evidence to check:
    # - spawn_orchestrator.py: wisdom prompt template
    # - runner_agent.py: build_system_prompt() output
    # - test_spawn_orchestrator.py + test_runner_agent.py: tests for AC-3.5

    # Red flags:
    # - "git merge main" or "gh pr merge" in system prompt strings
    # - MERGE_READY signal not emitted by runner after VALIDATION_PASSED


# ============================================================
# Epic 4: Proactive Context Cycling (weight: 0.10)
# ============================================================

@feature-F016 @weight-0.10 @epic-4
Feature: Proactive Context Cycling — Symptom Detection & Handoff

  Scenario: F016 — Runner detects PreCompact event and signals CONTEXT_WARNING
    Given tmux output containing a PreCompact system message
    When detect_symptoms() is called with that output
    Then urgency is "medium" and "PreCompact" appears in symptoms

    # Confidence scoring guide:
    # 1.0 — context_monitor.py implements detect_symptoms() with substring matching,
    #        returns urgency levels, CONTEXT_WARNING signal type defined, test passes
    # 0.5 — Function exists but signal type not defined or urgency levels wrong
    # 0.0 — context_monitor.py does not exist

    # Evidence to check:
    # - context_monitor.py: detect_symptoms() function
    # - signal_protocol.py: CONTEXT_WARNING in VALID_SIGNAL_TYPES
    # - test_context_monitor.py: test for AC-4.1

    # Red flags:
    # - Exact string matching instead of substring (fragile)
    # - No urgency levels (all symptoms treated equally)


  Scenario: F017 — Graceful handoff completes within 90s
    Given an orchestrator responding to "Save and exit" within 10s
    When the handoff sequence is triggered
    Then HANDOFF_REQUESTED is sent, hook updated, session killed, re-spawn called
    And total wall time is under 90 seconds

    # Confidence scoring guide:
    # 1.0 — Full handoff sequence implemented in runner, integration test with
    #        stubbed orchestrator passes within timeout
    # 0.5 — Handoff logic exists but integration test missing or timing untested
    # 0.0 — No handoff sequence implemented

    # Evidence to check:
    # - runner_agent.py: handoff handling in system prompt or code
    # - context_monitor.py: handoff coordination
    # - test_context_monitor_integration.py: test for AC-4.2

    # Red flags:
    # - No timeout enforcement
    # - Handoff starts but re-spawn not triggered


  Scenario: F018 — Re-spawned session resumes from correct phase
    Given a hook with current_phase "testing"
    When re-spawn is triggered with hook context
    Then wisdom prompt contains "Resume from phase: testing"

    # Confidence scoring guide:
    # 1.0 — build_wisdom_prompt_block() reads phase from hook, formats correctly, test passes
    # 0.5 — Function exists but output format doesn't match expected template
    # 0.0 — No phase-aware resume in wisdom prompt

    # Evidence to check:
    # - context_monitor.py: build_wisdom_prompt_block()
    # - test_context_monitor.py: test for AC-4.3

    # Red flags:
    # - Generic "resume work" without phase specificity


  Scenario: F019 — Force-kill at 60s timeout
    Given an orchestrator that never responds to "Save and exit"
    When 60 seconds elapse
    Then tmux kill-session is called for the target session

    # Confidence scoring guide:
    # 1.0 — Timeout logic with subprocess.run(timeout=60), tmux kill-session call,
    #        test verifies kill after timeout
    # 0.5 — Timeout exists but no kill-session call
    # 0.0 — No timeout handling

    # Evidence to check:
    # - runner_agent.py or context_monitor.py: force-kill logic
    # - test_runner_agent.py or test_context_monitor.py: test for AC-4.4

    # Red flags:
    # - subprocess.run() without timeout parameter
    # - Infinite wait without fallback


  Scenario: F020 — No data loss: all files committed before handoff
    Given the handoff sequence is in progress
    When HANDOFF_COMPLETE signal is checked
    Then it was only sent after HOOK_UPDATED was received
    And HOOK_UPDATED implies the orchestrator committed work

    # Confidence scoring guide:
    # 1.0 — Contract test verifies signal ordering: HANDOFF_REQUESTED → HOOK_UPDATED →
    #        HANDOFF_COMPLETE, runner waits for HOOK_UPDATED before signaling complete
    # 0.5 — Signal types defined but ordering not enforced
    # 0.0 — No ordering constraint between signals

    # Evidence to check:
    # - runner_agent.py: signal ordering logic
    # - test_runner_agent.py: test for AC-4.5

    # Red flags:
    # - HANDOFF_COMPLETE sent without waiting for HOOK_UPDATED
    # - No test for signal ordering
