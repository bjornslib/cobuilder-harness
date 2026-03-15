---
title: "SD-HARNESS-UPGRADE-001 Epic 11: Async Human Review Queue"
status: draft
type: solution-design
last_verified: 2026-03-06T00:00:00.000Z
grade: draft
---
# SD-HARNESS-UPGRADE-001 Epic 11: Async Human Review Queue

> **Phase 3 — Future Work (\~6-12 months)**. This SD is a vision document, not an implementation spec.

## 1. Problem Statement

`wait.human` gates currently block the entire pipeline. While one epic waits for human review, other independent nodes cannot progress (in the current sequential model). Even with E10's parallel execution, `wait.human` represents a throughput bottleneck — human response times are measured in hours, not seconds.

## 2. Design Vision

A non-blocking review queue accessible via GChat or a simple web interface:

```
Pipeline node reaches wait.human
  |-- Emit review request to queue (GChat message + web dashboard entry)
  |-- Pipeline continues with OTHER independent nodes
  |-- Human reviews asynchronously (minutes to hours)
  |-- Human response writes signal file
  |-- Pipeline picks up signal in next poll cycle
  |-- Blocked downstream nodes become dispatchable
```

**GChat integration**:
- Review request sent as a card message with approve/reject buttons
- Button click triggers a webhook that writes the signal file
- Thread-based: all context for a review stays in one thread

**Web dashboard** (optional, future):
- Simple page showing pending reviews with context
- Approve/reject buttons per review
- History of past reviews with outcomes

## 3. Files Changed

| File | Change |
| --- | --- |
| `pipeline_orchestrator.py` | `_handle_human` becomes non-blocking (already designed this way in E7) |
| `gchat-review-webhook.py` (new) | Receives GChat button clicks, writes signal files |
| `review-dashboard/` (new, optional) | Simple web UI for pending reviews |

## 4. Acceptance Criteria (Draft)

- AC-11.1: `wait.human` does not block other independent pipeline nodes
- AC-11.2: Review requests appear in GChat with approve/reject actions
- AC-11.3: GChat response triggers signal file creation
