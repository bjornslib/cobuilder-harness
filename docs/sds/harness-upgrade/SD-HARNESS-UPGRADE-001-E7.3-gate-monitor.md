---
title: "SD-HARNESS-UPGRADE-001 Epic 7.3: Gate Monitor Pattern"
status: complete
type: solution-design
last_verified: 2026-03-07
grade: authoritative
---

# SD-HARNESS-UPGRADE-001 Epic 7.3: Gate Monitor Pattern

## 1. Problem Statement

When `pipeline_runner.py` reaches a `wait.system3` or `wait.human` node, it writes a `.gate-wait` marker file and enters its poll loop waiting for a signal file response. But System 3 has no mechanism to detect these gate events and act on them:

- **wait.system3**: System 3 must run blind Gherkin E2E validation (stage 2) after the runner's validation agent (stage 1) passes. Currently System 3 has no way to know when stage 1 completes and the gate is waiting.
- **wait.human**: System 3 must present the gate summary to the user via `AskUserQuestion` and write the user's response as a signal file. Currently `_handle_human` attempts a GChat notification but there is no round-trip mechanism for the user to respond and unblock the pipeline.

**Evidence**: The pipeline runner already writes `.gate-wait` marker files (`_handle_gate` at line 707) for `wait.system3` nodes, but `_handle_human` (line 713) does NOT write a `.gate-wait` marker — it only attempts a GChat notification with no response path.

## 2. Design

### 2.1 Pipeline Runner: Unified Gate-Wait Markers

Both `_handle_gate` and `_handle_human` write `.gate-wait` marker files with `gate_type` field:

```python
# In _handle_gate (wait.system3):
gate_marker = os.path.join(self.signal_dir, f"{nid}.gate-wait")
json.dump({
    "node_id": nid,
    "gate_type": "wait.system3",
    "summary_ref": node["attrs"].get("summary_ref", ""),
    "epic_id": node["attrs"].get("epic_id", ""),
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, fh)

# In _handle_human (wait.human):
gate_marker = os.path.join(self.signal_dir, f"{nid}.gate-wait")
json.dump({
    "node_id": nid,
    "gate_type": "wait.human",
    "summary_ref": node["attrs"].get("summary_ref", ""),
    "mode": node["attrs"].get("mode", "technical"),
    "epic_id": node["attrs"].get("epic_id", ""),
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}, fh)
```

### 2.2 Haiku Monitor: Gate-Aware Prompt

The existing Haiku monitor prompt (in `monitoring-patterns.md` Section 7) is extended to detect `.gate-wait` files as a primary wake condition:

```python
Task(
    subagent_type="monitor",
    model="haiku",
    run_in_background=True,
    prompt=f"""Monitor pipeline progress for {pipeline_id}.

    Signal directory: {signal_dir}
    DOT file: {dot_file}
    Poll interval: 30 seconds
    Stall threshold: 5 minutes

    COMPLETE immediately with a status report when:
    1. A .gate-wait file appears in the signal directory
       - Report: node_id, gate_type, summary_ref from the JSON content
       - Status: MONITOR_GATE_WAITING
    2. A node fails (report which node and error)
       - Status: MONITOR_ERROR
    3. No state change for >5 minutes (report last known state)
       - Status: MONITOR_STALL
    4. All nodes reach terminal state (report completion)
       - Status: MONITOR_COMPLETE

    Priority: Check for .gate-wait files FIRST each cycle.
    Do NOT attempt to fix issues or respond to gates. Just report.
    """
)
```

### 2.3 System 3 Gate Response Handlers

When the monitor completes with `MONITOR_GATE_WAITING`, System 3 reads the gate type and acts:

**wait.system3 response:**
```python
# 1. Read the gate-wait marker
gate_info = json.loads(Read(f"{signal_dir}/{node_id}.gate-wait"))

# 2. Run blind Gherkin E2E validation
Task(
    subagent_type="validation-test-agent",
    prompt=f"--mode=e2e --prd={prd_id} --epic={gate_info['epic_id']}"
)

# 3. Write signal file to unblock the runner
Write(f"{signal_dir}/{node_id}.json", json.dumps({
    "node_id": node_id,
    "status": "success",  # or "error"
    "result": "pass",     # or "fail"
    "score": 0.87,
    "evidence": "Gherkin E2E: 5/6 scenarios passed",
    "timestamp": "..."
}))
# Runner polls, picks up signal, transitions gate to validated
```

**wait.human response:**
```python
# 1. Read the gate-wait marker
gate_info = json.loads(Read(f"{signal_dir}/{node_id}.gate-wait"))

# 2. Read summary from preceding validation gate
summary = Read(gate_info["summary_ref"])

# 3. Present to user via AskUserQuestion
AskUserQuestion(questions=[{
    "question": f"Pipeline gate {node_id} requests human review.\n\n{summary}\n\nApprove this work?",
    "header": "Gate Review",
    "options": [
        {"label": "Approve", "description": "Work meets acceptance criteria. Continue pipeline."},
        {"label": "Reject", "description": "Work does not meet criteria. Provide feedback for requeue."},
        {"label": "Investigate", "description": "Need more information before deciding."}
    ]
}])

# 4. Write signal file based on user response
result = "pass" if user_chose_approve else "fail"
Write(f"{signal_dir}/{node_id}.json", json.dumps({
    "node_id": node_id,
    "status": "success" if result == "pass" else "error",
    "result": result,
    "reviewer": "human",
    "feedback": user_feedback_if_reject,
    "timestamp": "..."
}))
# Runner polls, picks up signal, transitions gate
```

### 2.4 Gate-Wait File Cleanup

After System 3 writes the response signal (`{node_id}.json`), the `.gate-wait` marker is no longer needed. The runner should delete it after picking up the signal to prevent the monitor from re-triggering on stale markers.

```python
# In pipeline_runner.py _apply_signal():
gate_marker = os.path.join(self.signal_dir, f"{node_id}.gate-wait")
if os.path.exists(gate_marker):
    os.remove(gate_marker)
```

## 3. Files Changed

| File | Change |
|------|--------|
| `.claude/scripts/attractor/pipeline_runner.py` | `_handle_human`: add `.gate-wait` marker write with `gate_type`, `summary_ref`, `mode`. `_handle_gate`: add `summary_ref` and `epic_id` to existing marker. `_apply_signal`: clean up `.gate-wait` after processing. |
| `.claude/skills/s3-guardian/references/monitoring-patterns.md` | New Section 8: "Gate Monitor Pattern" with gate-aware Haiku prompt, System 3 response handlers for both gate types, AskUserQuestion template for wait.human |
| `.claude/skills/s3-guardian/SKILL.md` | Update Phase 3 row in Quick Reference to mention gate monitoring. Add brief gate monitor summary to Pipeline Progress Monitor Pattern section. |

## 4. Testing

- Unit test: `_handle_human` writes `.gate-wait` marker file with correct JSON schema
- Unit test: `_handle_gate` marker includes `summary_ref` and `epic_id` fields
- Unit test: `_apply_signal` removes `.gate-wait` marker after processing signal
- Integration test: full pipeline with `wait.system3` node — runner writes marker, external signal unblocks gate
- Integration test: full pipeline with `wait.human` node — runner writes marker, external signal unblocks gate
- Verify: stale `.gate-wait` files do not accumulate after pipeline completion

## 5. Acceptance Criteria

- AC-7.3.1: `_handle_human` writes a `.gate-wait` marker file with `gate_type: "wait.human"`, `summary_ref`, and `mode` fields
- AC-7.3.2: `_handle_gate` marker includes `summary_ref` and `epic_id` fields (enriched from current minimal marker)
- AC-7.3.3: `_apply_signal` cleans up `.gate-wait` marker after processing the corresponding signal
- AC-7.3.4: `monitoring-patterns.md` Section 8 documents gate-aware Haiku monitor prompt with `MONITOR_GATE_WAITING` status
- AC-7.3.5: `monitoring-patterns.md` Section 8 documents System 3 response handlers for both `wait.system3` (Gherkin E2E) and `wait.human` (AskUserQuestion) gates
- AC-7.3.6: s3-guardian SKILL.md Quick Reference updated with gate monitoring guidance
- AC-7.3.7: All existing pipeline tests pass (no regressions from marker enrichment or cleanup)
