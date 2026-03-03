# Runner Mode-Switching E2E Test Results

**Date**: 2026-03-02
**Promise**: promise-d6786302
**Pipeline**: .claude/attractor/pipelines/runner-e2e-test.dot

## Test Summary: 5/5 PASS

### TEST 1: Pipeline Validation
- **Status**: PASS
- **Evidence**: `cobuilder pipeline validate` exits 0
- **Pipeline**: 2 codergen nodes (impl_echo, impl_verify), 2 validation gates, sequential dependency

### TEST 2: RunnerStateMachine Init with --dot-file
- **Status**: PASS
- **Evidence**: State machine initializes correctly
  - mode: RunnerMode.MONITOR
  - node_id: impl_echo
  - prd_ref: PRD-RUNNER-E2E-TEST
  - dot_file: .claude/attractor/pipelines/runner-e2e-test.dot
  - max_turns: 5

### TEST 3: build_monitor_prompt Format (11/11 checks)
- **Status**: PASS
- **Evidence**: 1860 chars, contains:
  - STATUS format with COMPLETED|STUCK|CRASHED|WORKING|NEEDS_INPUT
  - EVIDENCE, COMMIT, OUTPUT_TAIL structured output fields
  - Node ID and session name interpolation
  - capture_output.py reference
  - Post-remediation VALIDATION_FAILED instruction
  - Git commit hash detection patterns
  - Push confirmation detection patterns

### TEST 4: RUNNER_EXITED Signal Write (7/7 checks)
- **Status**: PASS
- **Evidence**: Signal file created correctly
  - signal_type=RUNNER_EXITED
  - source=runner, target=guardian
  - payload.node_id=impl_echo
  - payload.mode=monitor
  - payload.reason=max_turns_exhausted
  - Filename contains RUNNER_EXITED

### TEST 5: Safety Net Behavior (5/5 checks)
- **Status**: PASS
- **Evidence**:
  - MONITOR mode exit: Writes RUNNER_EXITED signal (1 file)
  - COMPLETE mode exit: Does NOT write signal (still 1 file)
  - payload.mode=MONITOR (captures last mode before exit)
  - Correct node_id in payload

## Unit Test Suite
- **881 passed, 2 skipped, 0 failures** (pytest .claude/scripts/attractor/tests/)
- Includes 48 new RunnerStateMachine tests + 11 new RUNNER_EXITED signal tests
