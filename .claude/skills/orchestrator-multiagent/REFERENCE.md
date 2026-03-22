---
title: "Reference"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Quick Reference

Essential commands and patterns for orchestrator sessions.

## Table of Contents
- [Beads Commands](#beads-commands)
- [Epic Hierarchy](#epic-hierarchy)
- [Key Directories](#key-directories)
- [Service Ports](#service-ports)
- [Environment Variables](#environment-variables)
- [Session Start Template](#session-start-template)

---

## Beads Commands

### Finding Work

```bash
bd ready                          # Get unblocked tasks (MOST IMPORTANT)
bd list                           # All tasks
bd list --status=open             # Open tasks only
bd list --status=closed           # Closed tasks only
bd show <bd-id>                   # Task details with dependencies
bd stats                          # Project statistics
bd blocked                        # Show blocked issues and why
```

### Status Updates

```bash
bd update <bd-id> --status in_progress   # Mark as started
bd close <bd-id>                          # Mark complete
bd close <bd-id> --reason "Validated"     # Close with reason
bd reopen <bd-id>                         # Reopen if regression found
```

### Creating Tasks

```bash
bd create "Task title" -p 0              # Priority 0 (highest)
bd create "Task title" -p 1              # Priority 1 (normal)
bd create --title="..." --type=epic      # Create epic
bd create --title="..." --type=task      # Create task
```

### Dependencies

```bash
bd dep add <child> <parent>              # Add dependency
bd dep add <id> <id> --type=parent-child # Organizational grouping
bd dep add <id> <id> --type=blocks       # Sequential requirement
bd dep list <bd-id>                      # Show dependencies
bd dep remove <child> <parent>           # Remove dependency
```

### Sync & Commit

```bash
bd sync                                  # Sync with git remote
git add .beads/ && git commit -m "feat(<bd-id>): [description]"
```

---

## Epic Hierarchy

Every initiative requires this structure:

```
UBER-EPIC: Initiative Name
├── EPIC: Feature A ─────────────────────┐
│   ├── TASK: Implementation 1           │ [parent-child]
│   ├── TASK: Implementation 2           │ Concurrent work OK
│   └── TASK 3 → TASK 4 [blocks]         │
│                                        │
├── EPIC: AT-Feature A ──────────────────┤ [blocks]
│   └── TASK: E2E Tests                  │ AT blocks functional epic
│                                        │
├── EPIC: Feature B ─────────────────────┤
│   └── TASK: Implementation             │ [parent-child]
│                                        │
└── EPIC: AT-Feature B ──────────────────┘ [blocks]
    └── TASK: Validation tests
```

### Dependency Types

| Type | Blocks `bd ready`? | Use For |
|------|-------------------|---------|
| `parent-child` | No | Uber-epic→Epic, Epic→Task (organizational) |
| `blocks` | Yes | AT-epic→Functional-epic, Task→Task (sequential) |
| `related` | No | Cross-reference (soft link) |
| `discovered-from` | No | Bugs found during work |

### Quick Setup Example

```bash
# 1. Create uber-epic (ALWAYS FIRST)
bd create --title="Q1 Authentication" --type=epic --priority=1
# Returns: my-project-001

# 2. Create functional + AT epic pair
bd create --title="User Login Flow" --type=epic --priority=2      # my-project-002
bd create --title="AT-User Login Flow" --type=epic --priority=2   # my-project-003
bd dep add my-project-002 my-project-001 --type=parent-child        # Under uber-epic
bd dep add my-project-003 my-project-001 --type=parent-child        # Under uber-epic
bd dep add my-project-002 my-project-003 --type=blocks              # AT blocks functional

# 3. Create tasks
bd create --title="Implement login API" --type=task --priority=2  # my-project-004
bd dep add my-project-004 my-project-002 --type=parent-child        # Under epic
```

### Closure Order (MUST follow)

```
AT tasks → AT epic → Functional epic → Uber-epic
```

---

## Key Directories

| Directory | Purpose |
|-----------|---------|
| `.beads/` | Task state (managed by `bd` commands) |
| `.claude/progress/` | Session summaries and logs |
| `.claude/learnings/` | Accumulated patterns |
| `.claude/state/` | Mappings and state files |
| `.taskmaster/` | Task Master tasks and PRDs |

---

## Service Ports

| Port | Service |
|------|---------|
| 5001 | Frontend (Next.js) |
| 8000 | Backend (FastAPI) |
| 5184 | eddy_validate MCP |
| 5185 | user_chat MCP |

### Service Commands

```bash
# Start services
cd my-project-backend && ./start_services.sh
cd my-project-frontend && npm run dev

# Verify running
lsof -i :5001 -i :8000 -i :5184 -i :5185 | grep LISTEN
```

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `CLAUDE_SESSION_ID` | Session isolation |
| `CLAUDE_OUTPUT_STYLE` | Active output style |
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` | Set to `1` to enable native Agent Teams (required for Teammate/SendMessage) |

---

## Session Start Template

### PREFLIGHT Checklist

Run this at the start of every orchestrator session:

```markdown
### Phase 1: Tool Activation
- [ ] Serena: `mcp__serena__activate_project("my-project")`
- [ ] Serena: `mcp__serena__check_onboarding_performed`

### Phase 2: Memory Check
- [ ] Hindsight: `mcp__hindsight__recall("What should I remember about [current task]?")`
- [ ] Serena: `mcp__serena__list_memories` (if relevant)

### Phase 3: Beads Status
- [ ] `bd ready` - Find unblocked tasks
- [ ] `bd stats` - Overall progress

### Phase 4: Service Health (if executing)
- [ ] Frontend: `curl -s http://localhost:5001 > /dev/null && echo "OK"`
- [ ] Backend: `curl -s http://localhost:8000/health`

### Phase 5: Regression Check (pick 1-2 closed tasks)
- [ ] `bd list --status=closed` - Select tasks
- [ ] Run validation (Unit + API + E2E)
- [ ] If fail: `bd reopen <id>` and fix BEFORE new work
```

### Session End Checklist

```markdown
- [ ] Feature complete or cleanly stopped
- [ ] Shutdown all worker teammates: `SendMessage(type="shutdown_request", recipient="worker-name", ...)`
- [ ] Clean up team: `Teammate(operation="cleanup")`
- [ ] `bd sync` - Sync beads state
- [ ] Update `.claude/progress/` with summary
- [ ] `git status` clean, changes committed and pushed
- [ ] Hindsight: Store learnings with `mcp__hindsight__retain(...)`
```

---

## Worker Types (Native Agent Team Teammates)

| Type | subagent_type | Teammate Name | Use For |
|------|---------------|---------------|---------|
| Frontend | `frontend-dev-expert` | `worker-frontend` | React, Next.js, UI |
| Backend | `backend-solutions-engineer` | `worker-backend` | Python, FastAPI, APIs |
| Browser Testing | `tdd-test-engineer` | `worker-tester` | E2E validation |
| Validator | `validation-test-agent` | `worker-validator` | Task closure with evidence |
| General | `general-purpose` | `worker-general` | Everything else |

### Team Lifecycle Commands

```python
# 1. Create team (once per session, during PREFLIGHT)
Teammate(
    operation="spawnTeam",
    team_name="{initiative}-workers",
    description="Workers for {initiative}"
)

# 2. Create tasks in shared TaskList
TaskCreate(
    subject="Implement feature F001",
    description="[requirements, acceptance criteria, scope]",
    activeForm="Implementing F001"
)

# 3. Spawn specialist worker into team
Task(
    subagent_type="frontend-dev-expert",
    team_name="{initiative}-workers",
    name="worker-frontend",
    prompt="You are worker-frontend in team {initiative}-workers. Check TaskList for work. Claim tasks, implement, report via SendMessage."
)

# 4. Notify existing worker of new task
SendMessage(
    type="message",
    recipient="worker-frontend",
    content="New task available: F002 - Add login form",
    summary="New task F002 assigned"
)

# 5. Shutdown workers at session end
SendMessage(type="shutdown_request", recipient="worker-frontend", content="Session ending")

# 6. Clean up team
Teammate(operation="cleanup")
```

### Parallel Workers (Multiple Teammates)

```python
# Spawn multiple specialists into same team
Task(subagent_type="frontend-dev-expert", team_name="{initiative}-workers",
     name="worker-frontend", prompt="...")
Task(subagent_type="backend-solutions-engineer", team_name="{initiative}-workers",
     name="worker-backend", prompt="...")

# Each worker claims different tasks from shared TaskList
# Workers coordinate peer-to-peer via SendMessage
# Results arrive via SendMessage (auto-delivered to orchestrator)
```

### SendMessage Patterns

```python
# Direct message to a worker
SendMessage(type="message", recipient="worker-backend",
    content="Task #3 needs API endpoint at /api/auth", summary="Task details for worker")

# Worker reports completion (auto-delivered to orchestrator)
# Worker sends: SendMessage(type="message", recipient="team-lead",
#     content="Task #3 complete: implemented /api/auth endpoint", summary="Task 3 done")

# Shutdown request
SendMessage(type="shutdown_request", recipient="worker-frontend",
    content="All tasks complete, ending session")

# Broadcast to all workers (use sparingly - expensive)
SendMessage(type="broadcast",
    content="Critical: stop all work, regression found in auth module",
    summary="Critical regression alert")
```

---

## Task Lifecycle

```
created (open) → in-progress → closed
     ↑                            │
     └────── reopen ──────────────┘
```

---

**Related Files**:
- [SKILL.md](SKILL.md) - Main orchestrator documentation
- [PREFLIGHT.md](PREFLIGHT.md) - Full pre-flight checklist
- [WORKFLOWS.md](WORKFLOWS.md) - Detailed workflow patterns
- [WORKERS.md](WORKERS.md) - Worker delegation details
- [VALIDATION.md](VALIDATION.md) - Testing and troubleshooting
