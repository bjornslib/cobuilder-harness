# Monitor Mode - Quick Start Guide

## TL;DR

Monitor task completion and validate work products in real-time.

```bash
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id demo-test \
    --task-list-id shared-tasks \
    --max-iterations 10 \
    --interval 10
```

## Exit Codes

| Code | Meaning | Action |
|------|---------|--------|
| 0 | Task done + validated ✅ | Proceed |
| 1 | Task done but invalid ❌ | Create fix task |
| 2 | Task not done yet ⏳ | Keep waiting |

## Parameters

```
--session-id     Required. Orchestrator session ID
--task-list-id   Required. Task list to monitor
--task-id        Optional. Task to monitor (default: 15)
--max-iterations Optional. Max polls (default: 10)
--interval       Optional. Seconds between polls (default: 10)
--json           Optional. Output as JSON
```

## Examples

### Monitor Task #15 (Default)
```bash
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id my-session \
    --task-list-id shared-tasks
```

### Fast Polling (Every 5 seconds)
```bash
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id my-session \
    --task-list-id shared-tasks \
    --max-iterations 20 \
    --interval 5
```

### Get JSON Output (For Integration)
```bash
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id my-session \
    --task-list-id shared-tasks \
    --json
```

### Monitor Custom Task
```bash
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id my-session \
    --task-list-id shared-tasks \
    --task-id 12
```

## What Gets Checked

When a task completes, monitor validates:

1. **File Existence** - Deliverable file must exist
2. **Python Syntax** - Code must be valid Python
3. **Test Code** - Should contain `def test_*` functions
4. **Pytest** - Optional: run tests if available

## Typical Output (Successful)

```
[INFO] VALIDATION-AGENT MONITOR MODE
[INFO] Iteration 1: Task #15 status: completed
[INFO] FOUND: Task #15 is completed!
[INFO] File found: ~/.claude/tests/demo/test_monitor_demo.py (2098 bytes)
[INFO] Found test function definitions
[INFO] Python syntax validation: OK
[INFO] pytest: All tests passed

Result: MONITOR_COMPLETE
Message: Task #15 completed and work product validated
```

## Troubleshooting

### Monitor keeps returning MONITOR_HEALTHY

Task hasn't completed yet. Either:
1. Worker is still implementing
2. Task is blocked
3. Worker status isn't synced to task file

Wait and retry, or check task status:
```bash
python ~/.claude/scripts/task-list-monitor.py --list-id shared-tasks --status
```

### MONITOR_VALIDATION_FAILED but task looks done

Deliverable file is missing or invalid. Check:
```bash
# Does file exist?
ls -la ~/.claude/tests/demo/test_monitor_demo.py

# Is it valid Python?
python -m py_compile ~/.claude/tests/demo/test_monitor_demo.py

# Do tests pass?
pytest ~/.claude/tests/demo/test_monitor_demo.py -v
```

### pytest Failures Show But Validation Still Passes

By design! Monitor doesn't fail on pytest failures.
Check the evidence JSON for `pytest_returncode` field.

## Files

| File | Purpose |
|------|---------|
| `validation-test-agent-monitor.py` | Monitor mode implementation |
| `MONITOR_MODE_QUICK_START.md` | This quick reference |
| `../../docs/architecture/VALIDATION_AGENT_MONITOR_MODE.md` | Full documentation |

## Documentation

For complete documentation, see:
`$CLAUDE_PROJECT_DIR/docs/architecture/VALIDATION_AGENT_MONITOR_MODE.md`

## Testing

Run validation tests:
```bash
pytest ~/.claude/tests/demo/test_monitor_exit_codes.py -v
```

All 4 tests should pass:
- ✅ Exit 0: MONITOR_COMPLETE
- ✅ Exit 1: MONITOR_VALIDATION_FAILED
- ✅ Exit 2: MONITOR_HEALTHY
- ✅ JSON output structure
