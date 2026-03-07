---
title: "Living Narrative Protocol"
status: active
type: reference
last_verified: 2026-03-07
grade: authoritative
---

# Living Narrative Protocol

## Overview
The living narrative maintains a chronological record of initiative progress across multiple epics and sessions. It provides a high-level view of achievements, decisions, and outcomes for stakeholders.

## File Location
Narrative documents are stored per initiative at:
```
.claude/narrative/{initiative}.md
```

For example:
- `.claude/narrative/harness-upgrade.md` - for HARNESS-UPGRADE initiative
- `.claude/narrative/auth-system.md` - for AUTH-SYSTEM initiative

## Update Protocol
After each epic completion, System 3 appends a new entry to the initiative's narrative file.

## Entry Format
Each epic completion entry follows this format:

```
## Epic {N}: {title} — {date}

**Outcome**: {PASS/FAIL} (score: {x.xx})
**Key decisions**: {list}
**Surprises**: {unexpected findings}
**Concerns resolved**: {count}
**Time**: {duration}
```

### Field Descriptions
- **Epic N**: The epic number in sequence
- **Title**: Brief title describing the epic's purpose
- **Date**: Completion date in YYYY-MM-DD format
- **Outcome**: Result of the epic (PASS/FAIL)
- **Score**: Numeric score representing completion/quality (0.0-1.0)
- **Key decisions**: 2-5 significant decisions made during the epic
- **Surprises**: Unexpected challenges, discoveries, or deviations from plan
- **Concerns resolved**: Count of concerns addressed during the epic
- **Time**: Total duration spent on the epic

## Example Entry
```
## Epic 3: Workflow Protocol Enhancements — 2026-03-07

**Outcome**: PASS (score: 0.92)
**Key decisions**: Implemented SD version pinning, added concern queue processing, enhanced guardian reflection
**Surprises**: Found that signal directory configuration was causing dispatch issues
**Concerns resolved**: 5
**Time**: 12 hours
```

## Appending Protocol
1. Read the existing narrative file
2. Append the new epic entry at the end
3. Maintain chronological order (newest at the bottom)
4. Preserve all previous entries

## Use Cases
- Stakeholder reporting on initiative progress
- Historical reference for decision-making patterns
- Accountability tracking for epic outcomes
- Knowledge transfer between team members