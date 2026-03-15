---
title: "SD-HARNESS-UPGRADE-001 Epic 9: Persistent System 3 Controller"
status: draft
type: reference
last_verified: 2026-03-06T00:00:00.000Z
grade: draft
---
# SD-HARNESS-UPGRADE-001 Epic 9: Persistent System 3 Controller

> **Phase 3 — Future Work (\~6-12 months)**. This SD is a vision document, not an implementation spec.

## 1. Problem Statement

System 3 currently runs as episodic Claude Code sessions. Each session must:
1. Recall state from Hindsight
2. Read session handoff documents
3. Reconstruct pipeline state from DOT files
4. Re-orient before doing any work

This cold-start overhead costs 5-10 minutes and ~$1 per session. A persistent controller would maintain state in memory, eliminating reconstruction overhead.

## 2. Design Vision

A long-running Python process that:
- Maintains initiative state in memory (from initiative.json, E8)
- Receives events from pipeline_orchestrator.py (E7) via structured event bus
- Makes strategic decisions (which initiative to advance, when to pause for human input)
- Only invokes LLMs for reasoning tasks (not state management)
- Survives across Claude Code sessions via checkpoint/resume

```
persistent_s3.py (long-running)
  |-- Reads initiative.json on startup
  |-- Subscribes to pipeline events
  |-- Dispatches pipeline_orchestrator.py for each initiative
  |-- Handles cross-initiative coordination
  |-- Writes decisions to Hindsight
  |-- Sleeps when no work available (inotify/polling for new events)
```

## 3. Files Changed

| File | Change |
| --- | --- |
| `persistent_s3.py` (new) | Long-running controller |
| `pipeline_orchestrator.py` | Emits events to persistent_s3 via event bus or file |
| `initiative.json` | Updated by persistent_s3 |

## 4. Acceptance Criteria (Draft)

- AC-9.1: Persistent controller runs as a daemon process
- AC-9.2: State survives process restart via checkpoint
- AC-9.3: LLM invoked only for reasoning, not state management
