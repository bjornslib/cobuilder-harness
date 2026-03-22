# Validation Agent - Monitor Mode

## Overview

The validation-test-agent **monitor mode** provides continuous monitoring of task completion and work product validation. This is the third operating mode for the validation agent, complementing unit and E2E modes.

**Status**: Fully implemented and tested.

## Operating Modes Summary

```
┌─────────────────────────────────────────────────────────────────┐
│  VALIDATION-AGENT OPERATING MODES                               │
├─────────────────────────────────────────────────────────────────┤
│  --mode=unit                                                    │
│  - Fast unit tests with mocks                                   │
│  - Runs project's native test suite (pytest, jest, etc.)        │
│  - Output: UNIT_PASS | UNIT_FAIL                               │
│                                                                 │
│  --mode=e2e                                                     │
│  - Full acceptance testing against PRD                          │
│  - Real data, no mocks                                          │
│  - Uses acceptance-test-runner skill                            │
│  - Output: E2E_PASS | E2E_PARTIAL | E2E_FAIL                   │
│                                                                 │
│  --mode=monitor (NEW)                                           │
│  - Monitors task completion status                              │
│  - Validates work product when task completes                   │
│  - Real-time progress visibility for orchestrators              │
│  - Output: MONITOR_COMPLETE | MONITOR_HEALTHY | MONITOR_FAIL   │
└─────────────────────────────────────────────────────────────────┘
```

## Monitor Mode Features

### 1. Polling Protocol

The monitor continuously polls for task status changes:

```python
# Poll for completion
for iteration in range(1, max_iterations + 1):
    status = get_task_status(target_task_id)
    if status == "completed":
        # Proceed to validation
        break
    time.sleep(interval)  # Wait before next poll
```

**Configuration**:
- `--max-iterations`: Maximum polling attempts (default: 10)
- `--interval`: Seconds between polls (default: 10)

### 2. Work Product Validation

When a task completes, monitor validates the deliverable:

**Validation Steps**:
1. Check file exists at expected path
2. Verify it's valid code (syntax check)
3. Look for test function definitions
4. Optionally run pytest

**Task #15 Example**:
- Expected deliverable: `.claude/tests/demo/test_monitor_demo.py`
- Validations:
  - File exists
  - Valid Python syntax
  - Contains `def test_*` functions
  - Passes pytest

### 3. Evidence Collection

Monitor captures detailed evidence:

```json
{
  "file_exists": true,
  "file_path": ".claude/tests/demo/test_monitor_demo.py",
  "file_size": 2098,
  "has_test_code": true,
  "pytest_output": "...",
  "pytest_returncode": 0,
  "errors": []
}
```

## Usage

### Basic Invocation

```bash
# Monitor Task #15 in shared-tasks
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id demo-test \
    --task-list-id shared-tasks \
    --max-iterations 10 \
    --interval 10
```

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--session-id` | Required | Orchestrator session ID (e.g., "demo-test") |
| `--task-list-id` | Required | Task list to monitor (e.g., "shared-tasks") |
| `--task-id` | "15" | Task ID to monitor |
| `--max-iterations` | 10 | Maximum polling attempts |
| `--interval` | 10 | Seconds between polls |
| `--json` | False | Output as JSON |

### Advanced Examples

```bash
# Fast polling (5 seconds, 20 iterations = 100s max)
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id demo-test \
    --task-list-id shared-tasks \
    --max-iterations 20 \
    --interval 5 \
    --json

# Custom task (Task #12)
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id demo-test \
    --task-list-id shared-tasks \
    --task-id 12 \
    --max-iterations 30 \
    --interval 5

# Output JSON for integration with orchestrators
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id demo-test \
    --task-list-id shared-tasks \
    --json > monitor-result.json
```

## Output Modes

### Console Output (Default)

```
[INFO] ======================================================================
[INFO] VALIDATION-AGENT MONITOR MODE
[INFO] ======================================================================
[INFO] Session ID: demo-test
[INFO] Task List: shared-tasks
[INFO] Target Task: #15
[INFO] Max Iterations: 3 (interval: 2s)
[INFO] ======================================================================
[INFO]
[INFO] PHASE 1: Polling for task completion...
[INFO] ----------------------------------------------------------------------
[INFO] Iteration 1: Task #15 status: completed
[INFO]   Subject: Write sample unit test for monitoring demo
[INFO] FOUND: Task #15 is completed!
[INFO]
[INFO] PHASE 2: Validating work product...
[INFO] ----------------------------------------------------------------------
[INFO] File found: .claude/tests/demo/test_monitor_demo.py (2098 bytes)
[INFO] File content (2098 chars)
[INFO] Found test function definitions
[INFO] Python syntax validation: OK
[INFO] pytest: All tests passed
[INFO]
[INFO] ======================================================================
[INFO] MONITOR STATUS: COMPLETE AND VALIDATED
[INFO] ======================================================================
[INFO] Task #15 completed and work product validated
[INFO] Total time: 0.7s (1 iterations)
[INFO] ======================================================================
```

### JSON Output

```json
{
  "session_id": "demo-test",
  "task_list_id": "shared-tasks",
  "task_id": "15",
  "status": "MONITOR_COMPLETE",
  "message": "Task #15 completed and work product validated",
  "evidence": {
    "file_exists": true,
    "file_path": ".claude/tests/demo/test_monitor_demo.py",
    "file_size": 2098,
    "has_test_code": true,
    "pytest_output": "============================= test session starts ...",
    "pytest_returncode": 0,
    "errors": []
  },
  "iterations": 1,
  "total_time": 0.8824870586395264
}
```

## Return Codes

Monitor mode exits with status codes suitable for scripting:

| Code | Status | Meaning |
|------|--------|---------|
| 0 | `MONITOR_COMPLETE` | Task completed and validation passed ✅ |
| 1 | `MONITOR_VALIDATION_FAILED` | Task completed but validation failed ❌ |
| 2 | `MONITOR_HEALTHY` | Task not yet completed (healthy progress) ⏳ |

## Status Codes Explained

### MONITOR_COMPLETE (Exit 0)

Task has completed AND work product validated:
- Task status changed to "completed"
- Deliverable file exists
- File has valid syntax
- All validation checks passed

**Action**: Orchestrator can proceed with next steps

### MONITOR_VALIDATION_FAILED (Exit 1)

Task completed BUT validation failed:
- Task status is "completed"
- BUT: Deliverable file missing, syntax error, or invalid

**Action**: Orchestrator should:
1. Report failure with evidence
2. Create follow-up task to fix
3. Do not proceed with downstream tasks

### MONITOR_HEALTHY (Exit 2)

Task not yet completed after max iterations:
- Task still "pending" or "in_progress"
- No validation yet (can't validate incomplete work)

**Action**: Orchestrator should:
1. Continue waiting (optionally)
2. Check if task is blocked
3. Possibly escalate if stuck

## Workflow Integration

### With Orchestrators

Orchestrators use monitor mode to track worker progress:

```python
# In orchestrator session
while not all_tasks_complete:
    # Check progress of current task
    result = Task(
        subagent_type="validation-test-agent",
        prompt="--mode=monitor --session-id orch-123 --task-list-id shared-tasks"
    )

    if "MONITOR_COMPLETE" in result:
        # Task done and validated, move to next
        move_to_next_task()
    elif "MONITOR_VALIDATION_FAILED" in result:
        # Task done but invalid - escalate
        create_followup_task(result)
    else:  # MONITOR_HEALTHY
        # Still working - keep waiting
        time.sleep(30)
```

### With System 3

System 3 uses monitor for real-time visibility:

```python
# System 3 monitors orchestrator health
report = Task(
    subagent_type="validation-test-agent",
    prompt="--mode=monitor --session-id orch-homepage-123 --task-list-id orch-tasks"
)

if "MONITOR_VALIDATION_FAILED" in report:
    # Orchestrator has stuck/invalid task
    alert_human_operator(report)
elif completion_percentage < 30 and stuck_for_5_minutes:
    # Slow progress, possible doom loop
    send_guidance_to_orchestrator()
```

## Implementation Details

### File Structure

```
.claude/
├── scripts/
│   └── task-list-monitor.py           # Task polling utility
├── validation/
│   └── validation-test-agent-monitor.py     # Monitor mode implementation
└── tests/
    └── demo/
        └── test_monitor_demo.py        # Example work product
```

### Key Classes

**ValidationAgentMonitor**:
- `__init__(session_id, task_list_id, target_task_id)` - Initialize
- `poll_for_completion(max_iterations, interval)` - Poll for task status
- `validate_work_product()` - Validate deliverable
- `monitor(max_iterations, interval)` - Main monitoring loop

**MonitorResult** (dataclass):
- `session_id`, `task_list_id`, `task_id`
- `status` - MONITOR_COMPLETE | MONITOR_HEALTHY | MONITOR_VALIDATION_FAILED
- `message` - Human-readable result
- `evidence` - Validation details
- `iterations`, `total_time` - Timing info

### Validation Checks

For Task #15 (and customizable for other tasks):

1. **File Existence**
   - Check: `.claude/tests/demo/test_monitor_demo.py` exists
   - Error: Return `MONITOR_VALIDATION_FAILED` if missing

2. **Python Syntax**
   - Check: File compiles with Python parser
   - Error: Return `MONITOR_VALIDATION_FAILED` if syntax errors

3. **Test Detection**
   - Check: Contains `def test_*` function definitions
   - Warning: Log warning if missing, but don't fail

4. **Optional pytest Run**
   - Run: `pytest <file> -v` if available
   - Log: Pass/fail and output

## Testing

### Test Task #15 Completion Flow

```bash
# 1. Check initial status (should be pending)
python ~/.claude/scripts/task-list-monitor.py --list-id shared-tasks --status

# 2. Update Task #15 to completed
cat > ~/.claude/tasks/shared-tasks/15.json << 'EOF'
{
  "id": "15",
  "subject": "Write sample unit test for monitoring demo",
  "status": "completed",
  "blocks": [],
  "blockedBy": []
}
EOF

# 3. Run monitor mode (should find it completed immediately)
python ~/.claude/validation/validation-test-agent-monitor.py \
    --session-id demo-test \
    --task-list-id shared-tasks \
    --max-iterations 3 \
    --interval 2

# 4. Verify the test file passes
pytest ~/.claude/tests/demo/test_monitor_demo.py -v
```

### Test Cases

1. **Task Pending** → `MONITOR_HEALTHY` (Exit 2)
2. **Task Completed, File Valid** → `MONITOR_COMPLETE` (Exit 0)
3. **Task Completed, File Missing** → `MONITOR_VALIDATION_FAILED` (Exit 1)
4. **Task Completed, File Invalid Python** → `MONITOR_VALIDATION_FAILED` (Exit 1)

## Future Enhancements

### Planned Features

1. **Customizable Validators**
   - Plugin system for task-specific validation
   - Config-based validation rules

2. **Blocking Dependency Support**
   - Check if task is blocked before validating
   - Report blocked status separately

3. **Performance Metrics**
   - Track time from start to completion
   - Compare against expected duration

4. **Slack/Email Notifications**
   - Alert when task completes
   - Send validation failure reports

5. **Retry Logic**
   - Auto-retry validation failures
   - Exponential backoff for transient issues

## Troubleshooting

### Monitor Reports MONITOR_HEALTHY but Task Looks Complete

**Issue**: Task appears done, but monitor says not yet
**Solutions**:
1. Check JSON file format: `.claude/tasks/{list-id}/{id}.json`
2. Verify `"status": "completed"` exactly (no typos)
3. Wait a bit - file might not be synced yet

### Validation Fails with "File Not Found"

**Issue**: Task completed but deliverable file missing
**Solutions**:
1. Check correct file path in monitor script
2. Check if worker wrote to correct location
3. Verify file permissions (must be readable)

### pytest Shows Failures but Validation Passes

**Issue**: Monitor passes but tests actually fail
**Details**: Monitor doesn't fail on pytest failure by design
**Why**: Test failures are warnings, not blockers
**Solution**: Check evidence JSON for `pytest_returncode` field

## See Also

- `task-list-monitor.py` - Underlying polling utility
- `validation-test-agent` modes overview - All operating modes
- Orchestrator integration patterns - How to use in orchestrators
- System 3 documentation - Meta-orchestrator integration

## Related Documentation

- `.claude/scripts/task-list-monitor.py` - Task polling utility
- `.claude/tests/demo/test_monitor_demo.py` - Example test file
- `.claude/documentation/VALIDATION_AGENT_*` - Other validation guides
