---
title: "Workflows"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Orchestrator Workflows

Execution workflows for multi-feature development.

## Table of Contents
- [4-Phase Pattern](#4-phase-pattern)
- [Autonomous Mode Protocol](#autonomous-mode-protocol)
- [Acceptance Test Generation (After PRD Parse)](#acceptance-test-generation-after-prd-parse)
- [Codebase-Aware Task Creation (ZeroRepo)](#codebase-aware-task-creation-zerorepo)
- [Feature Decomposition (MAKER)](#feature-decomposition-maker)
- [Progress Tracking](#progress-tracking)
- [Session Handoffs](#session-handoffs)

---

## 4-Phase Pattern

The orchestrator follows a complete cycle for each feature:

```
1. PREPARATION
   ├── Read feature_list.json / bd ready
   ├── Run regression check (1-2 passing features)
   └── Select next ready feature

2. ASSIGNMENT
   ├── Determine worker type (specialist teammate)
   ├── Prepare worker context
   ├── Create task in shared TaskList (TaskCreate)
   ├── Spawn/notify worker teammate
   └── Set expectations via task description

3. COMPLETION
   ├── Await worker SendMessage notification (auto-delivered)
   ├── Check for red flags in result
   └── Detect completion signals (COMPLETE/BLOCKED)

4. VALIDATION
   ├── Run feature validation command
   ├── Post-test verification (Explore agent)
   ├── Check scope compliance
   └── Decision: Accept / Reject / Escalate

5. PROGRESSION
   ├── Update feature_list.json (passes: true) / bd close
   ├── Commit to git
   ├── Update progress tracking
   └── Loop back to step 1
```

### Phase Details

**Preparation**: Ensure clean state and identify next actionable feature.
- Read state to understand current status
- Run regression check on 1-2 previously passing features
- Select first feature where dependencies are satisfied

**Assignment**: Delegate feature to appropriate worker teammate with complete context.
- Match feature to specialist teammate (frontend/backend/general)
- Create task in shared TaskList via `TaskCreate` with acceptance criteria, files, validation command
- Spawn new worker teammate via `Task(subagent_type=..., team_name=..., name=...)` or notify existing teammate via `SendMessage`

**Completion**: Await worker notification.
- Worker teammate sends completion via `SendMessage` (auto-delivered to orchestrator)
- Check result for COMPLETE/BLOCKED signals
- Workers persist across tasks -- no need to re-spawn for each feature

**Validation**: Verify feature works as designed, not just that tests pass.
- Pre-validation: git clean, scope compliance, no incomplete markers
- Run validation command (tests)
- Post-test validation via Explore agent (hollow test detection)

**Progression**: Record success, commit, prepare for next feature.
- Update state file (only the `passes` field)
- Commit with descriptive message
- Update progress tracking, document learnings
- Workers persist in team -- no re-spawn needed for next feature
- At session end: shutdown teammates and run `Teammate(operation="cleanup")`

---

## Autonomous Mode Protocol

Enable independent monitoring and completion of multiple features without user intervention.

### Autonomous Continuation Criteria

**Continue to next feature automatically when ALL conditions met:**

1. Current feature validation PASSED (all three levels)
2. validation-test-agent closed task with evidence
3. Git commit successful with `feat(<id>)` message
4. `bd ready` returns next available task
5. No regressions detected in spot checks
6. Services remain healthy

### Stop Conditions (Report to User)

**Stop autonomous operation and report when ANY condition met:**

1. **3+ consecutive features blocked** - Indicates systemic issue
2. **Regression discovered** - Previously closed work now failing
3. **Service crash not auto-recoverable** - Infrastructure problem
4. **Uber-epic complete** - All epics closed, initiative done
5. **User explicitly requested checkpoint** - Honor user requests
6. **Circular dependency detected** - Beads graph issue
7. **Worker exceeds 2 hours on single task** - Decomposition needed

### Multi-Feature Session Loop

```
LOOP:
  1. PRE-FLIGHT CHECK
     - If not done this session: Run full PREFLIGHT.md checklist
     - If already done: Quick service health check only
     - If new initiative: Create SD per epic from PRD → generate acceptance tests from SD (see Acceptance Test Generation)

  2. SELECT NEXT TASK
     bd ready → Pick highest priority unblocked task
     bd update <id> --status in_progress

  3. DELEGATE TO WORKER TEAMMATE
     ```python
     # Create task in shared TaskList
     TaskCreate(
         subject="[Feature description]",
         description="[Worker assignment - context, requirements, criteria]",
         activeForm="Implementing [feature]"
     )
     # Notify existing worker OR spawn new teammate
     SendMessage(type="message", recipient="worker-[type]",
         content="New task available: [feature]", summary="New task assigned")
     # OR if no worker of this type exists yet:
     Task(
         subagent_type="[frontend-dev-expert|backend-solutions-engineer|etc]",
         team_name="{initiative}-workers",
         name="worker-[type]",
         prompt="You are worker-[type] in team {initiative}-workers. Check TaskList for work."
     )
     ```
     # Worker completes and notifies via SendMessage (auto-delivered)

  4. CHECK RESULT
     - Parse worker's SendMessage for COMPLETE/BLOCKED signals
     - If BLOCKED: send guidance via SendMessage, worker retries

  5. VALIDATE (THREE LEVELS - ALL MANDATORY)
     See Validation Protocol below

  6. CLOSE OR REMEDIATE
     IF all validation passed:
       # Assign validation to validator teammate
       TaskCreate(
         subject="Validate <id> (e2e)",
         description="--mode=e2e --task_id=<id> --prd=PRD-XXX",
         activeForm="Validating <id>"
       )
       SendMessage(type="message", recipient="worker-validator",
         content="Validate task <id>", summary="Validation task ready")
       # validator teammate closes with evidence if all criteria pass
       git add . && git commit -m "feat(<id>): [description]"
       → CONTINUE LOOP

     IF validation failed:
       Document failure in scratch pad
       IF first failure: Send feedback to worker via SendMessage, retry
       IF second failure: Decompose task, create sub-beads
       IF third failure: STOP, report to user

  7. REGRESSION SPOT CHECK (every 3rd feature)
     Pick 1 recently closed bead
     Run its validation
     IF regression: bd reopen → STOP, report to user

  8. CHECK STOP CONDITIONS
     IF any stop condition met: Exit loop, report to user
     ELSE: → CONTINUE LOOP
```

### Validation Protocol (3-Level)

**All three levels are MANDATORY before closing any feature.**

#### Level 1: Unit Tests

**Backend (Python/pytest)**:
```bash
cd my-project-backend
pytest tests/ -v --tb=short
```

**Frontend (TypeScript/Jest)**:
```bash
cd my-project-frontend
npm run test -- --coverage
```

**Pass Criteria**: Zero test failures, no uncaught exceptions, coverage maintained.

#### Level 2: Integration/API Tests

**API Endpoint Validation**:
```bash
# Health checks
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:5184/health | jq .
curl -s http://localhost:5185/health | jq .

# Feature-specific endpoints
curl -X POST http://localhost:8000/my-project \
  -H "Content-Type: application/json" \
  -d '{"query": "test message", "session_id": "test-123"}'
```

**Pass Criteria**: All endpoints return 200, response structures match schemas, data persists.

#### Level 3: E2E Browser Tests

Use Markdown-based test specifications:

1. **Test Specification** → Read from `__tests__/e2e/specs/J{N}-*.md`
2. **Worker Execution** → Execute via chrome-devtools MCP tools
3. **Execution Report** → Write to `__tests__/e2e/results/J{N}/J{N}_EXECUTION_REPORT.md`
4. **Orchestrator Review** → Sense-check results, re-execute if anomalies

**Pass Criteria**: UI renders correctly, workflows complete, no JS console errors, 100% pass rate.

---

## Acceptance Test Generation (After SD Parse)

**When**: Immediately after Task Master parse-prd (of SD) and beads sync completes

**Purpose**: Generate executable test scripts from the Solution Design before implementation begins

**Input**: The **SD document**, not the PRD — the SD's Business Context section provides goals for meaningful
acceptance criteria, and Section 6 (Acceptance Criteria per Feature) provides Gherkin-ready criteria.

**Workflow**:

1. **Generate tests from SD**:
   ```python
   # Orchestrator invokes skill (NOT worker, NOT validation-test-agent)
   # --prd flag identifies the parent PRD for test organization
   # --source points to the SD document that was parsed
   Skill("acceptance-test-writer", args="--prd=PRD-XXX --source=.taskmaster/docs/SD-{ID}.md")
   ```

2. **Review generated tests**:
   - Check `acceptance-tests/PRD-XXX/manifest.yaml` for completeness
   - Review each `AC-*.yaml` file for clarity
   - Adjust selectors/assertions if needed

3. **Commit tests**:
   ```bash
   git add acceptance-tests/ && git commit -m "test(PRD-XXX): add acceptance test suite"
   ```

**Output Directory**:
```
acceptance-tests/PRD-XXX/
├── manifest.yaml           # PRD metadata + feature list
├── AC-user-login.yaml     # Browser acceptance test
├── AC-api-auth.yaml       # API acceptance test
└── AC-session-timeout.yaml # Hybrid test
```

**Key Rules**:
- Generate tests in Phase 1 (Planning), NOT Phase 2 (Execution)
- Orchestrator generates tests, NOT workers
- validation-test-agent executes tests in Phase 3 (NOT orchestrator)
- Tests are committed to git with the beads hierarchy

**Integration with Validation Gate**:
```
Phase 1: PRD → acceptance-test-writer → acceptance-tests/PRD-XXX/
Phase 2: Workers implement (reference tests for guidance)
Phase 3: validation-test-agent --mode=e2e --prd=PRD-XXX → runs tests → closes tasks
```

---

## Codebase-Aware Task Creation (ZeroRepo)

Use ZeroRepo delta analysis to produce precise, scoped task descriptions instead of blind decompositions. Run this after PRD creation and before Task Master parsing.

### Delta Status to Task Mapping

| Delta Status | Task Implication | Worker Context to Include |
|---|---|---|
| **EXISTING** | Skip -- no task needed | "This component exists at `<path>/` and needs no changes. Reference only." |
| **MODIFIED** | Create scoped modification task | "Modify `<path>/` to add `<change>`. See change_summary from delta report." |
| **NEW** | Create full implementation task | "Create new `<module>/` module. See suggested interfaces from delta report." |

### Enriched Worker Assignment Template

Include delta context in every TaskCreate description:

```python
TaskCreate(
    subject="[MODIFIED] Add form handler to eddy_validate",
    description="""
    ## Task: Add multi-form validation handler

    **Delta Status**: MODIFIED
    **Existing Files** (modify these):
    - eddy_validate/app.py (add new route handler)
    - eddy_validate/validators.py (add FormValidator class)

    **Reference Files** (EXISTING -- do not modify):
    - voice_agent/pipeline.py (call pattern for validators)
    - shared/models.py (existing Pydantic models to extend)

    **Change Summary** (from delta report):
    Add support for multi-form university contact types.
    Extend existing SingleFormValidator to handle FormArray input.

    **Acceptance Criteria**:
    - FormValidator accepts list of form entries
    - Each entry validated independently
    - Errors collected and returned as structured response
    """,
    activeForm="Adding form handler to eddy_validate"
)
```

### Before vs After: Task Description Quality

**Without ZeroRepo** (vague, worker must explore):
```
Subject: Implement validation service
Description: Create a validation service for university contacts.
  Files: TBD
  Requirements: Validate contact information
```

**With ZeroRepo** (precise, worker can start immediately):
```
Subject: [MODIFIED] Add contact validator to eddy_validate
Description:
  Delta Status: MODIFIED
  Existing Files: eddy_validate/app.py, eddy_validate/validators.py
  Change: Add UniversityContactValidator class extending BaseValidator
  Reference (EXISTING): shared/models.py (UniversityContact model)
  Reference (EXISTING): voice_agent/pipeline.py (validation call pattern)
```

### Workflow Integration

```
Phase 1 Planning:
  Step 2: Create PRD
  Step 2.5: Run ZeroRepo (init + generate)    ← NEW
  Step 3: Read delta report, annotate PRD
  Step 4: Parse PRD with Task Master
  Step 5: Sync to Beads
  Step 6: Generate acceptance tests

Phase 2 Execution:
  Include delta file paths in every TaskCreate
  Workers receive precise scope from day one
```

For detailed ZeroRepo CLI commands and troubleshooting, see [ZEROREPO.md](ZEROREPO.md).

---

## Feature Decomposition (MAKER)

**Reference:** "SOLVING A MILLION-STEP LLM TASK WITH ZERO ERRORS" paper

**Core Principle:** Decompose until each step is simple enough for a Haiku model to execute with high reliability.

### MAKER Checklist

Before adding ANY feature, ask these four questions:

| Question | If YES | If NO |
|----------|--------|-------|
| Can this be broken into smaller steps? | Decompose further | Proceed |
| Does each step modify multiple files? | Too broad, decompose | Proceed |
| Could a Haiku model complete each step? | Proceed | Too complex, decompose |
| Is there more than ONE decision per step? | Too complex, decompose | Proceed |

### Decision Tree

```
START: Evaluate feature candidate
    ↓
Is feature completable in ONE worker session?
    NO → Split into multiple features
    YES ↓
Does feature have 10+ validation steps?
    YES → Too large, split into smaller features
    NO ↓
Do validation steps include "and" or "then"?
    YES → Multiple tasks, split steps
    NO ↓
Does scope include 5+ files?
    YES → Too broad, reduce scope or split feature
    NO ↓
Is each step specific and verifiable?
    NO → Refine steps to be concrete
    YES ↓
✅ APPROVED: Add to feature list
```

### Red Flags

| Red Flag | Meaning | Action |
|----------|---------|--------|
| Feature has 10+ steps | Too large | Split into multiple features |
| Step says "and" | Multiple tasks | Split into separate steps |
| Step is vague ("make it work") | Undefined | Specify exact outcome |
| Scope has 5+ files | Too broad | Reduce scope per feature |
| Description includes "how" details | Implementation details leaking | Focus on "what" behavior |
| Dependencies form circular chain | Logic error | Redesign feature order |

### Warning Signs During Execution

If you observe these during Phase 2, the decomposition needs improvement:

- Workers consistently exceed 2 hours per feature
- Workers modify files outside scope repeatedly
- Features fail validation 3+ times
- Workers spawn 10+ sub-agents for one feature
- Workers report "unclear requirements"

**Action:** Stop, return to Phase 1, refine decomposition.

### Good vs Bad Steps

**Good Steps:**
- "Add email input field to login form"
- "Create POST /api/auth endpoint"
- "Verify token returned in response body"
- "Display error message when email invalid"

**Bad Steps:**
- "Implement authentication" (too vague)
- "Build login form and connect to backend" (multiple tasks)
- "Make it work" (undefined outcome)
- "Fix any bugs" (open-ended)

---

## Progress Tracking

### Files to Maintain

| File | Purpose | Update Frequency |
|------|---------|------------------|
| `.claude/progress/{project}-summary.md` | Current state & next steps | End of every session |
| `.claude/progress/{project}-log.md` | Chronological history | End of every session |
| `.claude/learnings/decomposition.md` | Task breakdown patterns | After discovering patterns |
| `.claude/learnings/coordination.md` | Orchestration patterns | After successful coordination |
| `.claude/learnings/failures.md` | Anti-patterns & red flags | After recovering from failure |

### Session Summary Template

**Location:** `.claude/progress/{project}-summary.md`

```markdown
# Progress Summary

**Last Updated**: [YYYY-MM-DD HH:MM]
**Last Feature Completed**: F00X - [description]
**Next Feature Ready**: F00Y - [description]

## Current State

**Features Status:**
- Total features: X
- Passed: Y (YY%)
- Remaining: Z

**Recent Activity:**
- [Date]: Completed F00X (description)
- [Date]: Fixed regression in F00W

**Current Blocker (if any):**
- [None | Description of blocker]

## Technical Context

**Active Services:**
- Frontend: [Running on :5001 | Not started | Crashed]
- Backend: [Running on :8000 | Not started | Crashed]

## Notes for Next Session

**Quick Wins Available:**
- F00Y ready to implement (no blockers)

**Known Issues:**
- [List any gotchas discovered]

## Next Steps

1. Run regression check on [F001, F002]
2. Implement F00Y
3. If F00Y passes, proceed to F00Z
```

### Progress Log Template

**Location:** `.claude/progress/{project}-log.md`

```markdown
## [YYYY-MM-DD] Session [N]

**Duration:** ~[X] minutes
**Features Attempted:** F00X, F00Y
**Features Completed:** F00X

### What Was Done
- Started session at [time]
- Ran regression check - all passed
- Assigned F00X to frontend worker
- Worker completed in 45 minutes
- Validated via browser testing - passed
- Committed: "feat(F00X): [description]"

### What Worked Well
- MAKER decomposition was effective
- Worker completed without blockers

### Challenges / Issues
- Initial scope included too many files

### Time Breakdown
- Regression check: 5 min
- Worker execution: 45 min
- Validation: 10 min

### Next Session Should
- Continue with F00Y (ready, no blockers)
```

### Learnings Accumulation

**Three learning categories:**

1. **Decomposition Patterns** (`.claude/learnings/decomposition.md`)
   - Feature sizes that work well
   - Effective validation step patterns

2. **Coordination Patterns** (`.claude/learnings/coordination.md`)
   - Effective worker delegation strategies
   - When to intervene vs let worker continue

3. **Failure Patterns** (`.claude/learnings/failures.md`)
   - Anti-patterns that caused problems
   - Recovery strategies that worked

---

## Session Handoffs

### Before Ending Checklist

**Before ending ANY orchestration session:**

1. **Feature State Clean**
   - [ ] Current feature either complete OR cleanly stopped
   - [ ] No uncommitted code changes
   - [ ] All worker teammates shut down (`SendMessage(type="shutdown_request", recipient="worker-name", ...)`)
   - [ ] Team cleaned up (`Teammate(operation="cleanup")`)

2. **Feature List Updated**
   - [ ] State file updated with latest passes status
   - [ ] State file committed to git
   - [ ] Commit message describes what passed

3. **Progress Documentation Updated**
   - [ ] `summary.md` updated with current counts, blockers, context
   - [ ] `log.md` entry added for this session
   - [ ] Progress files committed

4. **Git State Clean**
   - [ ] `git status` shows clean working tree
   - [ ] All progress committed
   - [ ] Current branch noted in summary.md

5. **Learnings Captured**
   - [ ] Any new patterns documented in `.claude/learnings/`
   - [ ] Learning files committed to git

6. **Services State Noted**
   - [ ] Service status documented in summary.md

**Quick handoff command sequence:**
```python
# 0. Shutdown worker teammates and clean up team
SendMessage(type="shutdown_request", recipient="worker-frontend", content="Session ending")
SendMessage(type="shutdown_request", recipient="worker-backend", content="Session ending")
SendMessage(type="shutdown_request", recipient="worker-validator", content="Session ending")
# Wait for shutdown confirmations, then:
Teammate(operation="cleanup")
```
```bash
# 1. Update state and commit
git add .claude/state/
git commit -m "feat(F00X): [description] - marked complete"

# 2. Update progress files
git add .claude/progress/
git commit -m "docs: update progress after F00X completion"

# 3. Verify clean state
git status
```

**Note**: Always shut down teammates and clean up the team before ending a session. Unlike ephemeral Task subagents, native teammates persist and must be explicitly terminated.

### Starting New Session

**When resuming orchestration work:**

1. **Load Context**
   ```bash
   cat .claude/progress/{project}-summary.md
   tail -100 .claude/progress/{project}-log.md
   ```

2. **Verify Environment**
   - [ ] Services status matches summary.md expectation
   - [ ] Git status clean, on correct branch

3. **Mandatory Regression Check**
   - Pick 1-2 features marked `passes: true`
   - Run their validation steps
   - If ANY fail → mark as `passes: false` and fix BEFORE proceeding

4. **Identify Next Feature**
   - Find next ready feature (passes == false, dependencies satisfied)
   - Check all dependencies have passes == true

5. **Begin Work**
   - Proceed to Phase 2 workflow

---

**Version**: 3.1 (ZeroRepo Codebase-Aware Task Creation)
**Created**: 2026-01-07
**Last Updated**: 2026-02-08
**Consolidated from**: AUTONOMOUS_MODE.md, ORCHESTRATOR_PROCESS_FLOW.md, FEATURE_DECOMPOSITION.md, PROGRESS_TRACKING.md
**Major Changes**: v3.1 - Added Codebase-Aware Task Creation section integrating ZeroRepo delta analysis for precise worker task scoping. v3.0 - Updated to use native Agent Teams (Teammate + TaskCreate + SendMessage) for worker delegation. Workers are persistent teammates that claim tasks from shared TaskList and communicate via SendMessage. v2.0 - Updated to use Task subagents for worker delegation instead of tmux sessions.
