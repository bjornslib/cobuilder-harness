---
title: "Concern Queue Schema"
status: active
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# Concern Queue JSONL Schema

## Overview
The concern queue is a JSONL (JSON Lines) format file used by workers to report issues during execution. Each line contains a single JSON object representing a concern.

## File Location
Concerns are written to `{signal_dir}/concerns.jsonl` where `signal_dir` is determined by the `ATTRACTOR_SIGNAL_DIR` environment variable.

## JSON Schema
Each line in the concerns.jsonl file follows this schema:

```json
{
  "ts": "timestamp in ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ)",
  "node": "the node identifier where the concern originated",
  "severity": "the severity level (critical, warning, info)",
  "message": "descriptive message about the concern",
  "suggestion": "optional suggested action or solution"
}
```

## Severity Levels
- **critical**: Issues that block progress or cause failures. Will block validation gates and transition nodes to failed state.
- **warning**: Issues that indicate potential problems but don't block execution. Will be included in validation summaries for human review.
- **info**: Informational items for logging purposes. Will be logged to Hindsight memory only.

## Processing Rules
- **Critical**: Blocks wait.system3 gates, transitions to `failed`, includes in summary
- **Warning**: Included in summary for human review
- **Info**: Logged to Hindsight only

## Examples
```json
{"ts": "2026-03-06T10:15:00Z", "node": "impl_e1", "severity": "warning", "message": "SD references v1.x API but installed version is v2.0", "suggestion": "Pin dependency or update SD"}
```

```json
{"ts": "2026-03-06T10:20:00Z", "node": "impl_e2", "severity": "critical", "message": "Missing dependency 'requests' causes ImportError", "suggestion": "Add to requirements.txt"}
```

```json
{"ts": "2026-03-06T10:25:00Z", "node": "impl_e3", "severity": "info", "message": "Successfully processed 100 files", "suggestion": ""}
```

## Signal Directory Mitigation
The `ATTRACTOR_SIGNAL_DIR` environment variable must be set to ensure proper signal file handling:

```bash
export ATTRACTOR_SIGNAL_DIR="${pipeline_dir}/signals/"
```

This prevents signal directory mismatch which was a documented failure mode.