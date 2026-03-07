---
title: "Session Handoff Format"
status: active
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# Session Handoff Format

## Overview
The session handoff document provides continuity between System 3 sessions by capturing the state of the current session before termination. It allows subsequent sessions to pick up where the previous session left off.

## File Location
Handoff documents are written at the end of every System 3 turn to:
```
.claude/progress/{session-id}-handoff.md
```

The handoff document is read first on session startup before Hindsight queries.

## Required Sections
Each session handoff document must contain the following sections:

### 1. Header
```
# Session Handoff: {session-id}
```

### 2. Last Action
Description of the most recently completed action or task.

### 3. Pipeline State
Current status of the pipeline as reported by `cobuilder pipeline status` command.

### 4. Next Dispatchable Nodes
List of pending nodes that have all upstream dependencies met and are ready for dispatch.

### 5. Open Concerns
List of unresolved items from `concerns.jsonl` that require attention in the next session.

### 6. Confidence Trend
Latest confidence scores and trends from Hindsight memory that inform the next session's approach.

## Template
```
# Session Handoff: {session-id}

## Last Action
{what was just completed}

## Pipeline State
{cobuilder pipeline status output}

## Next Dispatchable Nodes
{list of pending nodes with deps met}

## Open Concerns
{unresolved items from concerns.jsonl}

## Confidence Trend
{latest scores from Hindsight}
```

## Reading Protocol
On session startup, the System 3 orchestrator must read the most recent handoff document from `.claude/progress/` before proceeding with Hindsight queries or other activities.

## Writing Protocol
At the end of each System 3 turn, before session termination, write the handoff document to capture the current state.