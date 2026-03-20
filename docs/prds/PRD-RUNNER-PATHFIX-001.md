---
title: "Pipeline Runner Path Resolution & Worker Lifecycle Fixes"
description: "Fix silent path resolution failures, add worker signal enforcement via Stop hooks, and refactor to ClaudeSDKClient"
version: "1.0.0"
last-updated: 2026-03-21
status: active
type: prd
grade: authoritative
prd_id: PRD-RUNNER-PATHFIX-001
---

# PRD-RUNNER-PATHFIX-001: Pipeline Runner Path Resolution & Worker Lifecycle Fixes

## Problem Statement

The CoBuilder pipeline runner had multiple silent failure modes:
1. Workers writing to wrong directories (CWD mismatch) with no error
2. SD/PRD file paths unresolvable across harness/target repo split
3. Workers exiting without writing signal files, leaving gates stuck indefinitely
4. Stale signal files causing false successes on retry
5. The unified stop gate judge treating SDK workers as System 3 sessions

## Solution Summary

### Issue 1: Directory Model (T1)
- Added `cobuilder_root` (harness repo) and `target_dir` (worker CWD) as mandatory graph attributes
- `_get_target_dir()` no longer silently falls back to `dot_dir`
- `_get_cobuilder_root()` replaces `_get_repo_root()` for SD resolution

### Issue 2: Path Validation (T2)
- DOT graph validator checks all file references are absolute and exist
- Rejects deprecated `target_repo` attribute with clear migration message
- 13 new test cases in `test_dot_schema_extensions.py`

### Issue 3: CWD Enforcement (T3 — deferred)
- `can_use_tool` requires `ClaudeSDKClient` (bidirectional), not `query()` (unidirectional)
- Removed `_create_path_guard` — CWD enforcement deferred until `can_use_tool` is re-enabled
- CWD currently enforced by prompt instructions + `_verify_worker_output`

### Issue 4: Post-Signal Verification (T4)
- `_verify_worker_output` checks file existence as primary verification
- `git diff HEAD~1` is informational only (not a failure condition)
- Prevents false failures when files are already committed

### Issue 5: Stale Signal Cleanup (T5)
- `transition.py` moves signal files to `processed/` on pending transition
- Respects `PIPELINE_SIGNAL_DIR` environment variable

### Issue 6: Worker Stop Hook
- `_create_signal_stop_hook` blocks worker exit if signal file missing
- Uses `ClaudeSDKClient` (bidirectional) for Stop hook support
- Pattern: `connect()` → `query(prompt)` → `receive_response()`
- Max 2 blocks then allows exit (prevents infinite loops)
- Checks both active and `processed/` directories
- Clear message: "your task is COMPLETE, just write signal and stop"

### Issue 7: Worker Environment Isolation
- Strips `CLAUDE_SESSION_ID` and `CLAUDE_OUTPUT_STYLE` from worker env
- Workers no longer detected as System 3 by unified stop gate judge
- SDK Stop hook remains active (in-process, independent of settings.json)

## Implementation Status

| Epic | Status | Date | Commits |
|------|--------|------|---------|
| T1: cobuilder_root + target_dir | Done | 2026-03-20 | 74079ff |
| T2: Validator path checks | Done | 2026-03-20 | 86301cb |
| T3: can_use_tool CWD enforcement | Deferred | — | Removed (1fa4129) |
| T4: Post-signal verify | Done | 2026-03-20 | aa45084, 0e6af04 |
| T5: Stale signal cleanup | Done | 2026-03-20 | 1f2ad50 |
| T6: Worker Stop hook | Done | 2026-03-20 | 565ddb1, 838a8b6, 1617708, eb0bb09 |
| T7: Worker env isolation | Done | 2026-03-20 | bf8ea6d |
| ClaudeSDKClient refactor | Done | 2026-03-20 | 7c61db4, f0226c1 |
| Verify fix (file existence) | Done | 2026-03-20 | 0e6af04 |
| FIX2: Portable test paths | Done | 2026-03-20 | f0a0ab3 |

## Key Discoveries

1. **SDK `query()` is unidirectional** — hooks don't fire because control protocol closes before Stop events
2. **`ClaudeSDKClient` pattern**: `connect()` then `query(prompt)` then `receive_response()` — the only way hooks work
3. **Workers inherit parent env** — `CLAUDE_SESSION_ID=system3-*` makes the S3 judge treat workers as System 3
4. **`_verify_worker_output` self-referential bug** — git status is clean when files already committed by prior gates
5. **Stop hook race condition** — runner moves signal to `processed/` before worker exits; hook must check both dirs

## Test Results

- 239 engine tests pass (0 failures)
- 918 attractor tests pass (42 pre-existing failures, 0 new)
- 37 schema extension tests pass
- Stop hook validated end-to-end: blocking works, worker self-corrects
