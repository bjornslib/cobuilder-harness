---
title: "Legacy_Feature_List"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Legacy feature_list.json Reference

**Status**: ARCHIVED - For migration and legacy project support only

> **IMPORTANT**: New projects should use Beads (use `bd` commands directly).
>
> This document consolidates all legacy feature_list.json documentation from the orchestrator skill.

---

## Table of Contents

1. [State File Location](#state-file-location)
2. [Feature Schema](#feature-schema)
3. [Essential Commands](#essential-commands)
4. [Worker Assignment Template](#worker-assignment-template)
5. [Phase 2 Workflow](#phase-2-workflow)
6. [Task Master Sync](#task-master-sync)
7. [Migration to Beads](#migration-to-beads)

---

## State File Location

```
.claude/state/{project-name}-feature_list.json
```

**Note**: `feature_list.json` is deprecated. Use Beads for new projects.

For migration, use:
```bash
node .claude/skills/orchestrator-multiagent/migrate-features-to-beads.js \
  --input=.claude/state/{project-name}-feature_list.json
```

---

## Feature Schema

Every feature in feature_list.json must follow this structure:

```json
{
  "id": "F001",
  "description": "User can send a message and receive AI response",
  "steps": [
    "Navigate to chat interface at localhost:5001",
    "Type message in input field",
    "Click send button",
    "Verify AI response appears within 10 seconds"
  ],
  "passes": false,
  "scope": ["my-project-frontend/components/ChatInterface.tsx"],
  "validation": "browser",
  "worker_type": "frontend",
  "dependencies": []
}
```

### Field Definitions

| Field | Type | Description | Rules |
|-------|------|-------------|-------|
| `id` | string | Unique identifier | F001, F002, etc. Sequential |
| `description` | string | User-visible behavior | What the feature does, not how |
| `steps` | array | Validation steps | Executable instructions, 3-7 steps ideal |
| `passes` | boolean | Completion status | ONLY field that changes (false → true) |
| `scope` | array | File paths worker can modify | Be restrictive, expand if needed |
| `validation` | string | Test type | "browser", "api", or "unit" |
| `worker_type` | string | Agent type | "frontend", "backend", or "general" |
| `dependencies` | array | Feature IDs required first | Must have `passes: true` before this starts |

---

## Essential Commands

### Check Feature Status

```bash
# View all failing features
cat .claude/state/{project-name}-feature_list.json | jq '.[] | select(.passes == false) | .id'

# View specific feature
cat .claude/state/{project-name}-feature_list.json | jq '.[] | select(.id == "F001")'
```

### Update Feature Status

```bash
# Mark feature as passing
jq '(.[] | select(.id == "F001")).passes = true' \
  .claude/state/{project-name}-feature_list.json > tmp.json
mv tmp.json .claude/state/{project-name}-feature_list.json

# Commit the change
git add -A && git commit -m "feat(F001): [description]"
```

### Find Next Ready Feature

```bash
# This requires manual dependency checking
# For each feature where passes: false, verify all dependencies have passes: true
cat .claude/state/{project-name}-feature_list.json | \
  jq '.[] | select(.passes == false) | {id, dependencies}'
```

**Note**: Beads handles this automatically with `bd ready`.

---

## Worker Assignment Template

Use this template when delegating to workers with legacy projects:

```markdown
## Feature Assignment: F00X

**Description**: [Copy exact description from feature_list.json]

**Validation Steps**:
1. [Step 1 from feature_list.json]
2. [Step 2 from feature_list.json]
3. [Step 3 from feature_list.json]
...

**Scope** (ONLY these files):
- [file1.ts]
- [file2.py]
[List from scope field]

**Validation Type**: [browser/api/unit from feature_list.json]

**Dependencies Verified**: [List dependency IDs that are passes: true]

**Your Role**:
- You are TIER 2 in the 3-tier hierarchy
- Complete this ONE SMALL FEATURE
- Spawn Haiku sub-agents for atomic operations (code OR test, never both)
- ONLY modify files in scope list
- Use superpowers:test-driven-development
- Use superpowers:verification-before-completion before claiming done

**Sub-Agent Pattern**:
For each implementation step, spawn a Haiku sub-agent:
```
Task(subagent_type="general-purpose", model="haiku", prompt="
[Single atomic task - either code OR test, never both]
Modify ONLY: [specific file]
")
```

**When Done**:
1. Run all validation steps from above
2. Verify all tests pass
3. Report: COMPLETE or BLOCKED with details
4. If COMPLETE, commit with message: "feat(F00X): [description]"

**CRITICAL Constraints**:
- Do NOT modify files outside scope
- Do NOT leave TODO/FIXME comments
- Do NOT use "I think" or "probably" - verify everything
- Do NOT skip validation steps
```

---

## Phase 2 Workflow

When using legacy feature_list.json for Phase 2 execution:

```
1. Read {project-name}-feature_list.json
   ↓
2. MANDATORY: Run regression check (1-2 passing features)
   ↓
3. Find next ready feature (passes: false, dependencies satisfied)
   ↓
4. 🚨 DELEGATE TO WORKER VIA TMUX (MANDATORY - INTERACTIVE MODE REQUIRED)

   ❌ ANTI-PATTERN: Task(subagent_type="frontend-dev-expert", ...)
   ✅ CORRECT: Launch tmux session in INTERACTIVE mode (no -p flag)

   Steps:
   a. Create tmux session: tmux new-session -d -s worker-F00X
   b. Launch Claude Code INTERACTIVELY: claude --dangerously-skip-permissions
      (NO -p flag - worker must run interactively!)
   c. Paste worker assignment (see template above)
   d. Launch Haiku monitor sub-agent to track progress
   ↓
5. Monitor worker progress (via Haiku sub-agent)
   ↓
6. Validate completion (tests + Explore agent)
   ↓
7. Update feature_list.json:
   ```bash
   jq '(.[] | select(.id == "F00X")).passes = true' feature_list.json > tmp.json
   mv tmp.json feature_list.json
   git add -A && git commit -m "feat(F00X): [description]"
   ```
   ↓
8. Update progress summary for next session
```

**Critical Rules**:
- One feature at a time
- Leave clean state
- Commit progress
- NEVER use Task tool with implementation sub-agents - ALWAYS delegate via tmux
- INTERACTIVE MODE IS MANDATORY - Workers must be able to receive feedback

---

## Task Master Sync

### Sync Task Master to feature_list.json

```bash
node .claude/skills/orchestrator-multiagent/sync-taskmaster-to-features.js \
  --output=.claude/state/{project-name}-feature_list.json
```

### Bidirectional Sync Rules

```
feature_list.json passes: true   ←→  Task Master status: done
feature_list.json passes: false  ←→  Task Master status: in-progress OR review
```

### When Orchestrator Verifies Feature

```bash
# 1. Verify feature passes validation
# 2. Update feature_list.json
jq '(.[] | select(.id == "F00X")).passes = true' \
  .claude/state/{project-name}-feature_list.json > tmp.json
mv tmp.json .claude/state/{project-name}-feature_list.json

# 3. Sync Task Master to 'done'
task-master set-status --id=<task-id> --status=done

# 4. Commit the synchronized state
git add -A && git commit -m "feat(F00X): [description] - verified and complete"
```

---

## Migration to Beads

### One-Time Migration

```bash
# Migrate existing project:
node .claude/skills/orchestrator-multiagent/migrate-features-to-beads.js \
  --input=.claude/state/{project-name}-feature_list.json

# Verify:
bd list
bd ready

# Archive old file:
mv .claude/state/{project-name}-feature_list.json \
   .claude/state/{project-name}-feature_list.json.bak
```

### Migration Output

The migration script creates a mapping file:

```json
{
  "migrated_at": "2025-12-19T10:00:00Z",
  "source_file": ".claude/state/project-feature_list.json",
  "total_features": 11,
  "mappings": [
    { "feature_id": "F001", "bead_id": "bd-a1b2", "task_id": "1", "passed": true },
    { "feature_id": "F002", "bead_id": "bd-c3d4", "task_id": "2", "passed": false }
  ]
}
```

### What Gets Migrated

| feature_list.json | Beads |
|-------------------|-------|
| `id` (F001) | Stored in metadata as `feature_id` |
| `description` | `title` |
| `passes: true` | Bead status: closed |
| `passes: false` | Bead status: open |
| `dependencies` | `bd dep add` relationships |
| `worker_type` | Stored in metadata |
| `validation` | Stored in metadata |
| `scope` | Stored in metadata |
| `steps` | Stored in metadata |

---

## Related Documents

- **[SKILL.md](../SKILL.md)** - Main orchestration workflow (Beads-focused)
- **Beads** - Current state management system (use `bd` commands directly)
- **[WORKERS.md](../WORKERS.md)** - Worker templates (Beads format preferred)
- **Feature Decomposition** - Task sizing and quality (consolidated into SKILL.md)

---

**Version**: 1.0
**Created**: 2025-12-21
**Purpose**: Archived legacy documentation for migration support
**Source**: Consolidated from SKILL.md, WORKER_DELEGATION_GUIDE.md, FEATURE_DECOMPOSITION.md, BEADS_INTEGRATION.md
