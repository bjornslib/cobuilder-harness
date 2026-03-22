---
title: "Workers"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Worker Delegation

Patterns for delegating implementation to worker teammates via native Agent Teams.

**Part of**: [Multi-Agent Orchestrator Skill](SKILL.md)

---

## Table of Contents
- [Core Principle](#core-principle)
- [3-Tier Hierarchy](#3-tier-hierarchy)
- [Worker Types](#worker-types)
- [Team Setup](#team-setup)
- [Task Delegation Pattern](#task-delegation-pattern)
- [Worker Assignment Template](#worker-assignment-template)
- [Parallel Worker Pattern](#parallel-worker-pattern)
- [Worker Lifecycle](#worker-lifecycle)
- [Browser Testing Workers](#browser-testing-workers)
- [Worker Output Handling](#worker-output-handling)
- [Fallback: Task Subagent Pattern](#fallback-task-subagent-pattern)

---

## 3-Tier Hierarchy (CRITICAL)

Understanding the hierarchy prevents delegation violations:

| Tier | Role | Spawns | Implements |
|------|------|--------|------------|
| **TIER 1: System 3** | Meta-orchestrator | Orchestrators via tmux | Never |
| **TIER 2: Orchestrator** | Team Lead / Coordinator | Workers via Agent Teams | Never |
| **TIER 3: Worker** | Teammate / Implementer | Does NOT spawn sub-workers | Directly |

**The Key Insight**: Workers are the END of the chain. They implement directly using Edit/Write tools. Workers do NOT spawn their own sub-workers or sub-agents for implementation.

```
System 3 ──tmux──> Orchestrator/Team Lead ──Team──> Worker (teammate) ──Edit/Write──> Code
                                                     |
                                                     +──> (validation tasks ONLY, not implementation)
```

**Important Distinction**:
- **System 3 -> Orchestrator**: Uses tmux for session isolation (orchestrators need persistent isolated environments in worktrees)
- **Orchestrator -> Worker**: Uses native Agent Teams (workers are teammates that persist across multiple tasks and communicate via SendMessage)

---

## Core Principle

**Orchestrator = Team Lead. Worker = Teammate Implementer.**

Use `Teammate` + `TaskCreate` + `Task(team_name=..., name=...)` for all worker delegation.

```python
# Step 1: Create team (once per session, in PREFLIGHT)
Teammate(
    operation="spawnTeam",
    team_name="{initiative}-workers",
    description="Workers for {initiative}"
)

# Step 2: Create a task in the shared TaskList
TaskCreate(
    subject="Implement {feature_name}",
    description="[worker assignment - see template below]",
    activeForm="Implementing {feature_name}"
)

# Step 3: Spawn a specialist worker into the team
Task(
    subagent_type="frontend-dev-expert",
    team_name="{initiative}-workers",
    name="worker-frontend",
    prompt="You are worker-frontend in team {initiative}-workers. Check TaskList for available work. Claim tasks, implement, report completion via SendMessage to team-lead."
)

# Step 4: Worker results arrive via SendMessage (auto-delivered)
# Worker sends: SendMessage(type="message", recipient="team-lead", content="Task #X complete: ...")
```

**Why native Agent Teams?**
- Workers persist across multiple tasks (no re-spawn overhead)
- Shared TaskList enables self-directed work claiming
- SendMessage provides real-time communication without polling
- Workers can communicate with peer workers directly
- Team cleanup is explicit and orderly

---

## Worker Types

| Type | subagent_type | Use For |
|------|---------------|---------|
| Frontend | `frontend-dev-expert` | React, Next.js, UI, TypeScript |
| Backend | `backend-solutions-engineer` | Python, FastAPI, PydanticAI, MCP |
| Browser Testing | `tdd-test-engineer` | E2E validation, browser automation |
| Architecture | `solution-design-architect` | Design docs, PRDs |
| General | `Explore` | Investigation, code search (read-only) |

### Quick Decision Rule

**Using Beads**: Worker type is stored in bead metadata:
```bash
bd show <bd-id>  # View metadata including worker_type
```

**If worker_type not specified**, determine from scope:
- Scope includes `*-frontend/*` -> `frontend-dev-expert`
- Scope includes `*-agent/*` or `*-backend/*` -> `backend-solutions-engineer`
- Otherwise -> `frontend-dev-expert` or `backend-solutions-engineer` based on file extensions

---

## Team Setup

Team creation happens once per session, during PREFLIGHT.

### Step 1: Create the Team

```python
Teammate(
    operation="spawnTeam",
    team_name="{initiative}-workers",
    description="Workers for {initiative}"
)
```

The team name follows the convention: `{initiative}-workers` where `{initiative}` matches the epic or PRD name (e.g., `auth-workers`, `dashboard-workers`).

### Step 2: Spawn Workers as Needed

Workers are spawned when tasks are ready. You do NOT need to spawn all workers upfront. Spawn a worker when you have work for that specialist type.

```python
# Spawn a frontend worker
Task(
    subagent_type="frontend-dev-expert",
    team_name="{initiative}-workers",
    name="worker-frontend",
    prompt="You are worker-frontend in team {initiative}-workers. Check TaskList for available work. Claim unassigned tasks matching your expertise (React, Next.js, TypeScript, UI). Implement directly using Edit/Write. Report completion via SendMessage to team-lead."
)

# Spawn a backend worker
Task(
    subagent_type="backend-solutions-engineer",
    team_name="{initiative}-workers",
    name="worker-backend",
    prompt="You are worker-backend in team {initiative}-workers. Check TaskList for available work. Claim unassigned tasks matching your expertise (Python, FastAPI, PydanticAI). Implement directly using Edit/Write. Report completion via SendMessage to team-lead."
)
```

---

## Task Delegation Pattern

### Creating Tasks for Workers

Tasks go into the shared TaskList. Workers claim them. The assignment content goes into `TaskCreate(description=...)`, NOT into the worker spawn prompt.

```python
# Create a task with full assignment details
TaskCreate(
    subject="Create API endpoint for user authentication",
    description="""
    ## Task: Create API endpoint for user authentication

    **Bead ID**: my-project-042
    **Context**: We're building a FastAPI backend with JWT auth
    **Requirements**:
    - POST /api/auth/login endpoint
    - Accept email and password
    - Return JWT token on success

    **Acceptance Criteria**:
    - Endpoint returns 200 with valid credentials
    - Endpoint returns 401 with invalid credentials
    - Token expires in 24 hours

    **Scope** (ONLY these files):
    - my-project-backend/app/routes/auth.py
    - my-project-backend/app/schemas/auth.py

    **When Done**:
    1. Run validation steps
    2. MANDATORY: mcp__serena__think_about_whether_you_are_done()
    3. TaskUpdate(taskId=..., status="completed")
    4. SendMessage(type="message", recipient="team-lead", content="Task complete: ...")
    """,
    activeForm="Implementing auth endpoint"
)

# Notify the appropriate worker (if already spawned)
SendMessage(
    type="message",
    recipient="worker-backend",
    content="New task available in TaskList: Create API endpoint for user authentication. Please claim and implement.",
    summary="New backend task available"
)
```

### Notifying Workers of New Tasks

If the worker is already spawned and idle, send a message to wake them:

```python
SendMessage(
    type="message",
    recipient="worker-backend",
    content="New task available. Check TaskList and claim it.",
    summary="New task available"
)
```

If no worker of the right type exists yet, spawn one (see Team Setup above).

---

## Worker Assignment Template

### Beads Format (RECOMMENDED)

This template goes into `TaskCreate(description=...)`:

```markdown
## Task Assignment: bd-xxxx

### Mandatory: Serena Mode Activation
Set mode before starting work:
mcp__serena__switch_modes(["editing", "interactive"])

### Checkpoint Protocol (NEVER SKIP)
1. After gathering context (3+ files/symbols):
   `mcp__serena__think_about_collected_information()`

2. Every 5 tool calls during implementation:
   `mcp__serena__think_about_task_adherence()`

3. BEFORE reporting completion (MANDATORY):
   `mcp__serena__think_about_whether_you_are_done()`

---

**Bead ID**: bd-xxxx
**Description**: [Task title from Beads]
**Priority**: P0/P1/P2/P3

**Validation Steps**:
1. [Step 1 from bead metadata]
2. [Step 2 from bead metadata]
3. [Step 3 from bead metadata]

**Scope** (ONLY these files):
- [file1.ts]
- [file2.py]

**Validation Type**: [browser/api/unit]

**Dependencies Verified**: [List parent beads that are closed]

**Your Role**:
- You are TIER 3 in the 3-tier hierarchy (Worker / Teammate)
- Complete this ONE SMALL TASK - implement it DIRECTLY yourself
- Do NOT spawn sub-agents for implementation - you ARE the implementer
- ONLY modify files in scope list
- Use superpowers:test-driven-development
- Use superpowers:verification-before-completion before claiming done

**Implementation Approach**:
- Write the code yourself using Edit/Write tools
- Write the tests yourself using Edit/Write tools
- You are a specialist agent (frontend-dev-expert, backend-solutions-engineer, etc.)
- If you need research help, use Task(model="haiku") for quick lookups only

**When Done**:
1. Run all validation steps from above
2. Verify all tests pass
3. MANDATORY CHECKPOINT: `mcp__serena__think_about_whether_you_are_done()`
4. TaskUpdate(taskId=..., status="completed")
5. SendMessage(type="message", recipient="team-lead", content="Task bd-xxxx COMPLETE: [summary of changes]")
6. Do NOT run `bd close` - orchestrator marks `impl_complete`, S3 handles closure
7. Check TaskList for more available work

**CRITICAL Constraints**:
- Do NOT modify files outside scope
- Do NOT leave TODO/FIXME comments
- Do NOT use "I think" or "probably" - verify everything
- Do NOT run `bd close` or update bead status
```

### Assignment Checklist

Before creating a task for a worker, verify the description includes:

- [ ] Feature ID and exact description
- [ ] Complete validation steps list
- [ ] Explicit scope (file paths)
- [ ] Validation type specified
- [ ] Dependencies verified as passing
- [ ] Role explanation (TIER 3 = direct implementer, teammate)
- [ ] Implementation approach (worker implements directly, not via sub-agents)
- [ ] Completion protocol (TaskUpdate + SendMessage)
- [ ] Instruction to check TaskList for next work after completion
- [ ] Critical constraints listed

---

## Parallel Worker Pattern

When delegating multiple workers that can run concurrently, spawn them into the same team. Each worker claims different tasks from the shared TaskList.

### Spawning Parallel Workers

```python
# Create tasks first
TaskCreate(
    subject="Build login form component",
    description="[frontend assignment...]",
    activeForm="Frontend: login form"
)

TaskCreate(
    subject="Create auth API endpoint",
    description="[backend assignment...]",
    activeForm="Backend: auth API"
)

# Spawn workers into the same team - they work in parallel
Task(
    subagent_type="frontend-dev-expert",
    team_name="{initiative}-workers",
    name="worker-frontend",
    prompt="You are worker-frontend. Check TaskList, claim frontend tasks, implement, report via SendMessage to team-lead."
)

Task(
    subagent_type="backend-solutions-engineer",
    team_name="{initiative}-workers",
    name="worker-backend",
    prompt="You are worker-backend. Check TaskList, claim backend tasks, implement, report via SendMessage to team-lead."
)

# Both workers now run in parallel on separate tasks
# Results arrive via SendMessage as workers complete
```

### Monitoring Parallel Workers

Workers send completion messages automatically. The orchestrator receives them as they arrive:

```
worker-frontend -> SendMessage -> team-lead: "Task #1 complete: login form built"
worker-backend  -> SendMessage -> team-lead: "Task #2 complete: auth API created"
```

To check overall progress, poll the TaskList:

```python
TaskList()  # Shows status of all tasks (pending, in-progress, completed)
```

### When to Use Parallel Workers

| Scenario | Pattern |
|----------|---------|
| Single feature, one specialist | One worker, sequential tasks |
| Frontend + Backend in parallel | Two workers, separate tasks |
| Multiple independent features | Multiple workers, each claims relevant tasks |
| Voting consensus | 3-5 workers, same problem, compare results |

### Voting Consensus Pattern

When you need multiple perspectives on a problem:

```python
# Create the same task with different approach instructions
for i, approach in enumerate(["approach_a", "approach_b", "approach_c"]):
    TaskCreate(
        subject=f"Solution {i+1}: {approach}",
        description=f"Solve [problem] using {approach}. Report your solution via SendMessage.",
        activeForm=f"Evaluating {approach}"
    )

# Spawn workers to tackle each approach
for i, approach in enumerate(["approach_a", "approach_b", "approach_c"]):
    Task(
        subagent_type="general-purpose",
        team_name="{initiative}-workers",
        name=f"solver-{i+1}",
        prompt=f"You are solver-{i+1}. Claim and work on 'Solution {i+1}' from TaskList. Report your solution via SendMessage to team-lead."
    )

# Collect all solutions via SendMessage, then evaluate consensus
```

---

## Worker Lifecycle

Workers in native Agent Teams persist across multiple tasks, unlike ephemeral Task subagents.

### Lifecycle Stages

```
1. SPAWN: Task(subagent_type=..., team_name=..., name=...)
   |
2. CLAIM: Worker checks TaskList, claims unassigned task via TaskUpdate(owner=...)
   |
3. IMPLEMENT: Worker uses Edit/Write to implement the task
   |
4. COMPLETE: Worker marks task done (TaskUpdate + SendMessage to team-lead)
   |
5. NEXT WORK: Worker checks TaskList again for more available tasks
   |
   +-- If tasks available -> go to step 2
   +-- If no tasks -> worker goes idle (waiting for new tasks or shutdown)
   |
6. SHUTDOWN: SendMessage(type="shutdown_request", recipient="worker-name")
   |
7. CLEANUP: Teammate(operation="cleanup")
```

### Completing Tasks

Workers complete tasks with two actions:

```python
# 1. Mark task as completed in TaskList
TaskUpdate(taskId="...", status="completed")

# 2. Notify orchestrator with summary
SendMessage(
    type="message",
    recipient="team-lead",
    content="Task #X complete: Created auth endpoint. Files modified: auth.py, auth_schema.py. Tests: 4 passing.",
    summary="Task #X complete"
)
```

### Reporting Blockers

Workers report blockers to the orchestrator:

```python
SendMessage(
    type="message",
    recipient="team-lead",
    content="BLOCKED on Task #X: Cannot find the database migration file referenced in requirements. Need path clarification.",
    summary="Worker blocked on Task #X"
)
```

### Shutting Down Workers

When all work is complete, shut down workers explicitly:

```python
# Request each worker to shut down
SendMessage(
    type="shutdown_request",
    recipient="worker-frontend",
    content="All tasks complete. Please shut down."
)

SendMessage(
    type="shutdown_request",
    recipient="worker-backend",
    content="All tasks complete. Please shut down."
)

# After all workers have shut down, clean up the team
Teammate(operation="cleanup")
```

---

## Browser Testing Workers

### Overview

Browser testing workers enable actual E2E validation using chrome-devtools MCP tools or Playwright for real browser automation.

**Pattern**: Orchestrator -> TaskCreate (test spec) -> tdd-test-engineer teammate -> Browser Testing -> Results via SendMessage

### When to Use

**Use browser testing workers when**:
- Feature requires validation of actual browser behavior
- Testing UI interactions, animations, scroll behavior
- Validating accessibility (keyboard navigation, ARIA)
- Performance testing (load times, interaction responsiveness)
- Visual regression testing (screenshots, layout)

**Don't use for**:
- Pure logic testing (use unit tests)
- API endpoint testing (use curl/HTTP requests)
- Backend validation (use pytest)

### Browser Testing Pattern

```python
# Create the test task
TaskCreate(
    subject="E2E browser testing for F084",
    description="""
    MISSION: Validate feature F084 via browser automation

    TARGET: http://localhost:5001/[path]

    TESTING CHECKLIST:
    - [ ] Navigate to page (chrome-devtools: navigate)
    - [ ] Verify UI renders correctly (read_page, screenshot)
    - [ ] Test user interactions (click, form_input)
    - [ ] Verify state changes (read_page after action)
    - [ ] Capture screenshots as evidence

    VALIDATION CRITERIA:
    - Page loads without console errors
    - All interactive elements are accessible
    - User workflow completes successfully

    REPORT FORMAT:
    - Pass/Fail per item
    - Screenshots of key states
    - Console log analysis
    - Overall assessment

    When Done:
    1. TaskUpdate(taskId=..., status="completed")
    2. SendMessage(type="message", recipient="team-lead", content="E2E results: ...")
    """,
    activeForm="E2E testing F084"
)

# Notify the tdd-test-engineer worker
SendMessage(
    type="message",
    recipient="worker-testing",
    content="E2E test task available for F084. Check TaskList.",
    summary="E2E test task available"
)
```

### Test Specification Workflow

```
1. TEST SPECIFICATION (Markdown)
   Location: __tests__/e2e/specs/J{N}-{journey-name}.md
   Format: Given/When/Then with chrome-devtools steps
                                 |
                                 v
2. WORKER EXECUTION (via teammate)
   - Worker reads the test spec Markdown file
   - Worker executes tests using chrome-devtools MCP tools
   - Worker captures screenshots as evidence
                                 |
                                 v
3. EXECUTION REPORT
   Location: __tests__/e2e/results/J{N}/J{N}_EXECUTION_REPORT.md
   Contents: Pass/Fail per test, evidence, issues found
                                 |
                                 v
4. ORCHESTRATOR REVIEW
   - Worker sends results via SendMessage
   - Orchestrator reviews execution report for anomalies
   - Orchestrator sense-checks results against expected behavior
   - Approves or requests fixes
```

---

## Worker Output Handling

### Interpreting Results

Workers report results via SendMessage. Look for these signals:

| Signal in Message | Meaning | Action |
|-------------------|---------|--------|
| "COMPLETE" | Worker finished successfully | Mark task impl_complete (`bd update <bd-id> --status=impl_complete`) |
| "BLOCKED" | Worker needs help | Read blocker, provide guidance via SendMessage |
| "FAIL" after test run | Tests failed | Review failure, send fix instructions or re-assign |
| "PASS" after test run | Tests passed | Proceed to validation |
| Files outside scope | Scope violation | Reject, create fresh task with clearer boundaries |

### Red Flags

| Signal | Action |
|--------|--------|
| Modified files outside scope | Reject - Create new task with clearer scope |
| TODO/FIXME in output | Reject - Create new task (incomplete work) |
| Validation fails | Reject - Create new task with fix instructions |
| Worker reports unclear requirements | Re-decompose task with better spec |

### Scope Enforcement

Every task description MUST include an explicit scope array limiting which files the worker can modify:

```markdown
**Scope** (ONLY these files):
- my-project-backend/app/routes/auth.py
- my-project-backend/app/schemas/auth.py
```

Workers that modify files outside scope have their work rejected. Create a new task with clearer boundaries if this occurs.

---

## Fallback: Task Subagent Pattern

When `AGENT_TEAMS` is not enabled (environment variable `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is not set), fall back to the legacy Task subagent pattern.

### Standard Blocking Pattern

```python
result = Task(
    subagent_type="backend-solutions-engineer",
    description="Implement [feature]",
    prompt="""
    ## Task: Create API endpoint for user authentication

    **Context**: We're building a FastAPI backend with JWT auth
    **Requirements**:
    - POST /api/auth/login endpoint
    - Accept email and password
    - Return JWT token on success

    **Acceptance Criteria**:
    - Endpoint returns 200 with valid credentials
    - Endpoint returns 401 with invalid credentials
    - Token expires in 24 hours

    **Scope**: ONLY these files:
    - my-project-backend/app/routes/auth.py
    - my-project-backend/app/schemas/auth.py

    **Report back with**: Files modified, tests written, any blockers
    """
)
# Orchestrator waits here until worker completes
```

### Parallel Subagent Pattern

```python
# Launch workers in parallel using run_in_background=True
frontend_task = Task(
    subagent_type="frontend-dev-expert",
    run_in_background=True,
    description="Frontend feature F001",
    prompt="[Worker assignment...]"
)

backend_task = Task(
    subagent_type="backend-solutions-engineer",
    run_in_background=True,
    description="Backend feature F002",
    prompt="[Worker assignment...]"
)

# Collect results when needed
frontend_result = TaskOutput(task_id=frontend_task.agent_id, block=True)
backend_result = TaskOutput(task_id=backend_task.agent_id, block=True)
```

### Fallback Key Differences

| Aspect | Native Teams | Task Subagent (Fallback) |
|--------|-------------|--------------------------|
| Worker persistence | Persists across tasks | Ephemeral per assignment |
| Communication | SendMessage (real-time) | Return value on completion |
| Parallel work | Multiple teammates | `run_in_background=True` + `TaskOutput()` |
| Task assignment | Shared TaskList | Full prompt per invocation |
| Cleanup | Explicit shutdown + cleanup | Automatic on completion |
| Worker awareness | Can see peers, collaborate | Isolated, no peer visibility |

---

## Related Documents

- **[SKILL.md](SKILL.md)** - Main orchestrator skill
- **[WORKFLOWS.md](WORKFLOWS.md)** - Feature decomposition, autonomous mode
- **[VALIDATION.md](VALIDATION.md)** - Service startup, testing infrastructure

---

**Document Version**: 3.0 (Native Agent Teams Delegation)
**Last Updated**: 2026-02-06
**Major Changes**: Replaced Task subagent worker delegation with native Agent Teams (Teammate + TaskCreate + SendMessage). Workers are now persistent teammates that claim tasks from a shared TaskList and communicate via SendMessage. Task subagent pattern preserved as fallback when AGENT_TEAMS is not enabled. Added worker lifecycle management (spawn, claim, implement, complete, shutdown, cleanup).
