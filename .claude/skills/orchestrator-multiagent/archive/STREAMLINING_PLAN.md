---
title: "Streamlining_Plan"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Orchestrator Skill Streamlining Plan

**Created**: 2025-12-21
**Purpose**: Comprehensive plan to streamline the orchestrator-multiagent skill for improved autonomous operation
**Status**: APPROVED FOR IMPLEMENTATION

---

## Executive Summary

This plan documents 6 critical streamlining opportunities identified through deep analysis of the 7-file orchestrator skill ecosystem (~4,000 lines total). Implementation will reduce complexity by ~20% while significantly improving autonomous monitoring and task completion capabilities.

---

## Current Architecture Analysis

### File Inventory

| File | Lines | Primary Purpose |
|------|-------|-----------------|
| SKILL.md | ~600 | Main orchestration logic, decision trees, workflow phases |
| FEATURE_DECOMPOSITION.md | ~440 | MAKER checklist, task sizing, templates |
| WORKER_DELEGATION_GUIDE.md | ~600 | 3-tier hierarchy, worker launch, monitoring |
| BEADS_INTEGRATION.md | ~690 | Task tracking, uber-epic pattern, AT epics |
| TROUBLESHOOTING.md | ~650 | Red flags, anti-patterns, recovery |
| PROGRESS_TRACKING.md | ~520 | Session handoff, learnings accumulation |
| SERVICE_MANAGEMENT.md | ~470 | Service health, port management |

**Total**: ~3,970 lines across 7 files

---

## Issue #1: Decision Tree Fragmentation

### Problem Description

Multiple overlapping decision trees are scattered across SKILL.md, requiring mental reconciliation of 4+ decision paths when starting a session.

### Specific Line References

**SKILL.md - Workflow Triage** (lines 112-150):
```markdown
## Workflow Triage (MANDATORY FIRST STEP)

**Before any orchestration, determine which workflow applies:**

1. Check if Beads is initialized OR {project-name}-feature_list.json exists
   - Run: bd list (if Beads installed)
   - Or check: .claude/state/{project-name}-feature_list.json
   ↓
2. If NEITHER exists → PLANNING MODE (Phase 0 required)
...
```

**SKILL.md - Phase 0 Decision Tree** (lines 258-290):
```markdown
### Phase 0 Decision: Task Master vs Manual Planning

**🚨 MANDATORY: Choose planning approach BEFORE entering Phase 0**

#### Planning Approach Decision Tree

1. Does {project-name}-feature_list.json already exist?
   YES → Skip Phase 0, proceed to Phase 1/2
   NO → Continue to step 2 (Phase 0 required)
   ↓
2. Is there a PRD document OR can requirements be written as PRD?
...
```

**SKILL.md - Verification Mode** (lines 145-180):
```markdown
### Verification Mode (When Code Already Exists)

**When to use**: Implementation was done in a previous session but features weren't marked as passing.

**Key Difference from Implementation Mode**:
- ❌ Do NOT launch workers in tmux for implementation
- ✅ Run tests directly to verify existing code
...
```

**SKILL.md - Workflow Decision Matrix** (lines 135-145):
```markdown
### Workflow Decision Matrix

| Scenario | Signs | Workflow |
|----------|-------|----------|
| **Planning** | No {project-name}-feature_list.json exists | Phase 0: Task Master or Manual Planning |
| **Greenfield** | {project-name}-feature_list.json exists, all pending | Implementation Mode (Phase 2) |
...
```

### Impact

- Cognitive overload when starting sessions
- Risk of following wrong decision path
- Repeated logic checking across multiple sections

### Recommendation

Create a **single unified state machine** in SKILL.md that consolidates all decision logic:

```
SESSION_START → CHECK_BEADS →
  ├─ NO_BEADS → PLANNING_MODE → Phase 0
  └─ HAS_BEADS → bd ready →
       ├─ ALL_CLOSED → MAINTENANCE_MODE
       ├─ SOME_CLOSED → CONTINUATION_MODE → Phase 2
       └─ NONE_CLOSED → IMPLEMENTATION_MODE → Phase 2
```

### Implementation Steps

1. Create new "Unified Session State Machine" section at top of SKILL.md
2. Remove redundant decision trees (lines 112-180, 258-290)
3. Replace with single flowchart + lookup table
4. Estimated line reduction: ~80 lines

---

## Issue #2: Legacy Dual-Track (Beads + feature_list.json)

### Problem Description

Every section maintains parallel instructions for Beads AND legacy feature_list.json, effectively doubling content and creating cognitive overhead.

### Specific Line References

**SKILL.md - Quick Reference duplicated commands** (lines 55-85):
```markdown
# Task status (Beads - RECOMMENDED)
bd ready                                    # Get unblocked tasks
bd list                                     # All tasks
bd show <bd-id>                             # Task details

# Update task status (Beads)
bd update <bd-id> --status in-progress      # Mark as started
bd close <bd-id> --reason "Validated"       # Mark complete

# Commit (Beads)
git add .beads/ && git commit -m "feat(<bd-id>): [description]"

# Legacy: Feature status (feature_list.json)
cat .claude/state/{project-name}-feature_list.json | jq '.[] | select(.passes == false) | .id'

# Legacy: Update feature (feature_list.json)
jq '(.[] | select(.id == "F001")).passes = true' .claude/state/{project-name}-feature_list.json > tmp.json && mv tmp.json .claude/state/{project-name}-feature_list.json
```

**SKILL.md - Phase 2 dual instructions** (lines 390-450):
```markdown
**Using Beads (RECOMMENDED)**:
1. `bd ready` → Get unblocked tasks
...

**Using Legacy feature_list.json**:
1. Read {project-name}-feature_list.json
...
```

**WORKER_DELEGATION_GUIDE.md - Dual templates** (lines 110-220):
```markdown
### Beads Format (RECOMMENDED)

## Task Assignment: bd-xxxx
...

### Legacy Format (feature_list.json)

## Feature Assignment: F00X
...
```

**FEATURE_DECOMPOSITION.md - Dual schemas** (lines 28-90):
```markdown
### Beads Format (RECOMMENDED)

Tasks are created using `bd` commands...

### Legacy Format (feature_list.json)

Every feature in feature_list.json must follow this structure:
...
```

**BEADS_INTEGRATION.md - Migration section** (lines 305-355):
```markdown
## Migration from feature_list.json

### One-Time Migration

node .claude/skills/orchestrator-multiagent/migrate-features-to-beads.js \
  --input=.claude/state/project-feature_list.json
...
```

### Impact

- ~30% of documentation is legacy content
- Cognitive load from deciding which system to use
- Risk of mixed-state operations

### Recommendation

1. Create `LEGACY_FEATURE_LIST.md` appendix file
2. Move ALL feature_list.json content to appendix
3. Make SKILL.md, WORKER_DELEGATION_GUIDE.md, FEATURE_DECOMPOSITION.md Beads-only
4. Add single reference line: "For legacy projects, see LEGACY_FEATURE_LIST.md"

### Implementation Steps

1. Create LEGACY_FEATURE_LIST.md with:
   - Full feature_list.json schema
   - Legacy commands
   - Migration instructions (from BEADS_INTEGRATION.md lines 305-355)
   - Legacy worker templates (from WORKER_DELEGATION_GUIDE.md lines 166-217)
2. Remove legacy sections from:
   - SKILL.md lines 55-85 (legacy commands)
   - SKILL.md lines 390-450 (legacy Phase 2)
   - WORKER_DELEGATION_GUIDE.md lines 166-217
   - FEATURE_DECOMPOSITION.md lines 56-90
3. Estimated line reduction: ~150 lines from active files

---

## Issue #3: Circuit Breaker Fragmentation

### Problem Description

5+ mandatory pre-flight checks are scattered across different sections and files, making it easy to miss critical steps.

### Specific Line References

**CLAUDE.md - Serena MCP activation** (mandatory_first_step section):
```markdown
## 🚨 MANDATORY FIRST STEP: Activate Serena MCP (NO EXCEPTIONS)
**Before ANY task work, you MUST:**
1. **CRITICAL**: Ensure you're in the project root directory
2. Check if Serena is active: Try using any Serena tool
3. If not active, activate immediately: `mcp__serena__activate_project`
4. Check onboarding: `mcp__serena__check_onboarding_performed`
```

**CLAUDE.md - Memory protocol** (memory_protocol section):
```markdown
## 🧠 MANDATORY Memory Protocol (Circuit Breaker)

### Task Start Memory Check (NO EXCEPTIONS)
**BEFORE ANY INVESTIGATION, you MUST:**
1. ✅ Activate Serena MCP at project root
2. ✅ Check BOTH memory systems:
   mcp__serena__list_memories
   mcp__serena__read_memory("relevant-memory-name")
   mcp__byterover-mcp__byterover-retrieve-knowledge("task-related-query")
```

**SKILL.md - Regression check** (lines 520-560):
```markdown
## Mandatory Regression Check (CIRCUIT BREAKER)

**CRITICAL: Before ANY new feature work**:

**This is a CIRCUIT BREAKER that prevents cascading failures.**

1. Pick 1-2 features marked `passes: true`
2. Run their validation steps
3. If ANY fail:
   - Mark as `passes: false`
   - Note the failure reason
   - Fix BEFORE proceeding to new work
4. Only then proceed to next feature
```

**SKILL.md - Session Start Memory Check** (lines 155-175):
```markdown
### Session Start Memory Check (CRITICAL CIRCUIT BREAKER)

**BEFORE ANY investigation in a new session:**

1. **Check Serena memories** for patterns from previous sessions
2. **Check Byterover knowledge base** for architectural patterns
3. **Document in scratch pad** what you learned
```

**SKILL.md - Uber-epic first pattern** (lines 188-230):
```markdown
### 🚨 MANDATORY: Uber-Epic First Pattern

**BEFORE ANY PHASE 0 WORK, you MUST create an Uber-Epic**

Every new feature, fix, or release MUST start with an uber-epic. This is non-negotiable.
```

**SKILL.md - AT Epic pattern** (lines 232-300):
```markdown
### 🚨 MANDATORY: Acceptance Test Epic Pattern

**Every functional Epic MUST have a paired Acceptance Test (AT) Epic**.
```

**SERVICE_MANAGEMENT.md - Pre-Flight Checklist** (lines 196-212):
```markdown
### Pre-Flight Checklist for Workers

Before starting ANY feature implementation, verify:

# 1. Services exist
[ "$(tmux list-sessions | grep -c -E 'frontend|backend')" -eq 2 ]

# 2. Ports listening
[ "$(lsof -i :5001 -i :8000 | grep -c LISTEN)" -ge 2 ]

# 3. Backend health
curl -s http://localhost:8000/health | grep -q "healthy"
```

### Impact

- Mandatory steps spread across 3+ files
- High risk of missing a circuit breaker
- No single checklist to follow

### Recommendation

Create **PREFLIGHT.md** with ONE unified checklist consolidating ALL mandatory checks.

### Implementation Steps

1. Create PREFLIGHT.md with consolidated checklist
2. Add references from SKILL.md to PREFLIGHT.md
3. Remove redundant checklist fragments from:
   - SERVICE_MANAGEMENT.md lines 196-212
   - SKILL.md lines 155-175 (merge into PREFLIGHT)
4. Keep detailed explanations in source files, but checklist in PREFLIGHT.md

### PREFLIGHT.md Content (New File)

```markdown
# Session Pre-Flight Checklist

**ALL STEPS MANDATORY - NO EXCEPTIONS**

## Phase 1: Environment Setup (30 seconds)

□ **Serena Active**
  ```bash
  mcp__serena__check_onboarding_performed
  # If not active: mcp__serena__activate_project with project="my-project"
  ```

□ **Services Healthy**
  ```bash
  lsof -i :5001 -i :8000 -i :5184 -i :5185 | grep LISTEN
  # Must show 4 ports. If not: see SERVICE_MANAGEMENT.md
  ```

□ **Git Clean**
  ```bash
  git status
  # Must show clean working tree
  ```

## Phase 2: Context Loading (60 seconds)

□ **Memory Systems Checked**
  ```bash
  # Serena memories
  mcp__serena__list_memories
  mcp__serena__read_memory("relevant-memory-name")

  # Byterover knowledge
  mcp__byterover-mcp__byterover-retrieve-knowledge("task context query")
  ```

□ **Beads Status**
  ```bash
  bd ready
  # Shows available unblocked tasks
  ```

## Phase 3: Regression Validation (2-5 minutes)

□ **Select 1-2 Closed Beads**
  ```bash
  bd list --status closed
  # Pick recently closed items
  ```

□ **Run Validation for Each**
  - Unit tests: `npm run test` / `pytest`
  - E2E tests: Browser automation via chrome-devtools
  - API tests: `curl` endpoints
  - If ANY fail: `bd reopen <id> --reason "Regression"` → FIX BEFORE PROCEEDING

## Phase 4: Session Goal Determination

□ **Check Initiative Status**
  ```bash
  bd list --type epic
  # Existing uber-epic? → Continue to Phase 2
  # No uber-epic? → Create one first (MANDATORY)
  ```

□ **For New Initiatives**
  ```bash
  # Step 1: Create uber-epic
  bd create --title="[Initiative Name]" --type=epic --priority=1

  # Step 2: Create capability stream epics
  bd create --title="[Stream A]" --type=epic --priority=2
  bd dep add <epic-a-id> <uber-epic-id> --type=parent-child

  # Step 3: Create AT epic for each functional epic (MANDATORY)
  bd create --title="AT-[Stream A]" --type=epic --priority=2
  bd dep add <at-epic-id> <uber-epic-id> --type=parent-child
  bd dep add <epic-a-id> <at-epic-id> --type=blocks
  ```

---

**Pre-Flight Complete** → Proceed to Phase 2 (Incremental Progress)
```

---

## Issue #4: Missing Autonomous Monitoring Protocol

### Problem Description

The skill describes HOW to monitor workers but lacks explicit guidance for autonomous multi-feature session progression without user intervention.

### Specific Line References

**SKILL.md - Phase 2 workflow** (lines 380-480):
```markdown
### Phase 2: Incremental Progress (Each Session)

**Using Beads (RECOMMENDED)**:
1. `bd ready` → Get unblocked tasks
   ↓
2. MANDATORY: Run regression check (pick 1-2 closed tasks, validate)
   ↓
3. Select next ready task from `bd ready` output
   ↓
4. 🚨 DELEGATE TO WORKER VIA TMUX (MANDATORY)
...
```
*Note: No guidance on when to continue vs stop*

**WORKER_DELEGATION_GUIDE.md - Haiku Monitor** (lines 340-400):
```markdown
### Option 1: Haiku Monitor Sub-Agent (RECOMMENDED)

Task(
    subagent_type="general-purpose",
    model="haiku",
    run_in_background=True,
    prompt="""Monitor the tmux worker session 'worker-F001' until completion...
    """)
```
*Note: Monitors single worker, no multi-feature loop*

**SKILL.md - Concurrent Orchestration** (lines 590-640):
```markdown
## Concurrent Orchestration (Multi-Epic Workflow)

When working with uber-epics containing multiple epics, leverage concurrent development:

### Starting Multiple Workers

bd ready
# Returns tasks from ALL epics
# Workers can work on different epics concurrently!
```
*Note: Mentions concurrency but no autonomous progression protocol*

### Gap Analysis

Missing guidance for:
- When to continue to next feature automatically
- When to stop and report to user
- Multi-feature session orchestration loop
- Validation completeness (unit + E2E + API)

### Recommendation

Create **AUTONOMOUS_MODE.md** with explicit autonomous operation protocol.

### Implementation Steps

1. Create AUTONOMOUS_MODE.md with:
   - Autonomous continuation criteria
   - Stop conditions (excluding time limits per user feedback)
   - Multi-feature session loop
   - Comprehensive validation protocol
2. Reference from SKILL.md Phase 2 section

### AUTONOMOUS_MODE.md Content (New File)

```markdown
# Autonomous Operation Protocol

**Purpose**: Enable independent monitoring and completion of multiple features without user intervention.

---

## Core Principle

The orchestrator operates autonomously through feature implementation cycles, only stopping when specific conditions require user input.

---

## Autonomous Continuation Criteria

**Continue to next feature automatically when ALL conditions met:**

1. ✅ Current feature validation PASSED (all three levels - see below)
2. ✅ `bd close <id>` completed with evidence in reason
3. ✅ Git commit successful with `feat(<id>)` message
4. ✅ `bd ready` returns next available task
5. ✅ No regressions detected in spot checks
6. ✅ Services remain healthy

---

## Stop Conditions (Report to User)

**Stop autonomous operation and report when ANY condition met:**

1. 🛑 **3+ consecutive features blocked** - Indicates systemic issue
2. 🛑 **Regression discovered** - Previously closed work now failing
3. 🛑 **Service crash not auto-recoverable** - Infrastructure problem
4. 🛑 **Uber-epic complete** - All epics closed, initiative done
5. 🛑 **User explicitly requested checkpoint** - Honor user requests
6. 🛑 **Circular dependency detected** - Beads graph issue
7. 🛑 **Worker exceeds 2 hours on single task** - Decomposition needed

---

## Multi-Feature Session Loop

```
LOOP:
  1. PRE-FLIGHT CHECK
     - If not done this session: Run full PREFLIGHT.md checklist
     - If already done: Quick service health check only

  2. SELECT NEXT TASK
     bd ready → Pick highest priority unblocked task
     bd update <id> --status in-progress

  3. DELEGATE TO WORKER
     - Create tmux session: worker-<id>
     - Launch Claude Code interactively (no -p flag)
     - Paste worker assignment template
     - Launch Haiku monitor with run_in_background=True

  4. AWAIT COMPLETION
     TaskOutput(task_id=monitor_agent_id, block=True)

  5. VALIDATE (THREE LEVELS - ALL MANDATORY)

     Level 1: Unit Tests
     - Backend: pytest my-project-backend/tests/
     - Frontend: npm run test (Jest)
     - Must PASS before proceeding

     Level 2: Integration/API Tests
     - Backend endpoints: curl validation
     - MCP tool calls: Verify tool responses
     - Database operations: Check data persistence

     Level 3: E2E Browser Tests
     - Launch chrome-devtools or Playwright
     - Execute user workflow validation
     - Capture evidence (screenshots, logs)

  6. CLOSE OR REMEDIATE
     IF all validation passed:
       bd close <id> --reason "PASS: Unit ✓ API ✓ E2E ✓ [evidence]"
       git add . && git commit -m "feat(<id>): [description]"
       → CONTINUE LOOP

     IF validation failed:
       Document failure in scratch pad
       IF first failure: Provide worker feedback, retry
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

---

## Validation Protocol (Comprehensive)

### Level 1: Unit Tests

**Backend (Python/pytest)**:
```bash
cd my-project-backend
pytest tests/ -v --tb=short
# Must show all tests PASSED
```

**Frontend (TypeScript/Jest)**:
```bash
cd my-project-frontend
npm run test -- --coverage
# Must show all tests PASSED
```

### Level 2: Integration/API Tests

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

**MCP Tool Validation**:
```bash
# Verify MCP tools respond correctly
# Use Explore agent to test tool invocations
```

### Level 3: E2E Browser Tests

**Using chrome-devtools MCP**:
```javascript
// Navigate to application
mcp__chrome-devtools__navigate_page({ url: "http://localhost:5001" })

// Take snapshot for validation
mcp__chrome-devtools__take_snapshot({})

// Interact with UI elements
mcp__chrome-devtools__click({ uid: "element-uid" })
mcp__chrome-devtools__fill({ uid: "input-uid", value: "test input" })

// Verify expected outcomes
mcp__chrome-devtools__take_screenshot({ name: "validation-evidence" })
```

**Validation Evidence Requirements**:
- Screenshot of final state
- Console log excerpt (no errors)
- Network request log (successful responses)

---

## Session Handoff (When Stopping)

**Minimal handoff (2 minutes max)**:

1. **Close current work cleanly**
   ```bash
   # If mid-feature, save state
   bd update <id> --status open  # Revert to open if incomplete
   git stash  # Preserve uncommitted work
   ```

2. **Document next steps**
   ```bash
   bd ready > /tmp/next-tasks.txt
   echo "Next: $(head -1 /tmp/next-tasks.txt)"
   ```

3. **Quick scratch pad note** (only if complex context)
   ```markdown
   ## Session End: [timestamp]

   Completed: bd-xxx, bd-yyy
   Next ready: bd-zzz
   Context: [any critical info for next session]
   ```

4. **Push changes**
   ```bash
   git push
   bd sync
   ```

---

## Example Autonomous Session

```
SESSION START
├── Run PREFLIGHT.md checklist ✓
├── bd ready → [bd-abc, bd-def, bd-ghi]
│
├── FEATURE 1: bd-abc
│   ├── Delegate to worker-abc
│   ├── Monitor via Haiku (background)
│   ├── Worker reports COMPLETE
│   ├── Validate: Unit ✓ API ✓ E2E ✓
│   ├── bd close bd-abc --reason "PASS: all tests green"
│   └── git commit -m "feat(bd-abc): implement login form"
│
├── FEATURE 2: bd-def
│   ├── Delegate to worker-def
│   ├── Monitor via Haiku (background)
│   ├── Worker reports COMPLETE
│   ├── Validate: Unit ✓ API ✓ E2E ✓
│   ├── bd close bd-def --reason "PASS: API returns JWT"
│   └── git commit -m "feat(bd-def): auth endpoint"
│
├── REGRESSION CHECK (3rd feature trigger)
│   ├── Check bd-abc validation → PASS
│   └── Continue
│
├── FEATURE 3: bd-ghi
│   ├── Delegate to worker-ghi
│   ├── Monitor via Haiku (background)
│   ├── Worker reports BLOCKED: "dependency missing"
│   ├── Provide feedback, worker retries
│   ├── Worker reports COMPLETE
│   ├── Validate: Unit ✓ API ✓ E2E ✓
│   ├── bd close bd-ghi --reason "PASS: integration verified"
│   └── git commit -m "feat(bd-ghi): session management"
│
├── bd ready → [] (empty - uber-epic complete)
│
└── STOP: Report to user "Uber-epic complete, all features validated"
```

---

**Version**: 1.0
**Created**: 2025-12-21
```

---

## Issue #5: Reference File Duplication

### Problem Description

Significant content overlap exists between files, requiring updates in multiple locations and risking inconsistency.

### Specific Line References

**tmux Enter pattern duplication**:

1. **SKILL.md** (lines 1-25, top banner):
```markdown
## 🚨 CRITICAL: tmux Enter Pattern (READ THIS FIRST)

When sending commands via tmux, **Enter must be a separate `send-keys` command**...

# ❌ WRONG - Enter gets silently ignored
tmux send-keys -t worker "command" Enter

# ✅ CORRECT - Enter as separate command
tmux send-keys -t worker "command"
tmux send-keys -t worker Enter
```

2. **WORKER_DELEGATION_GUIDE.md** (lines 290-303):
```markdown
**⚠️ CRITICAL tmux Pattern**: Enter must be separate `send-keys` command! See [SKILL.md](../SKILL.md) top banner for details.

# Launch Claude Code in INTERACTIVE mode (no -p flag!)
# NOTE: Enter is SEPARATE command (critical pattern!)
tmux send-keys -t worker-F001 "claude --dangerously-skip-permissions --model claude-opus-4-5-20251101"
tmux send-keys -t worker-F001 Enter
```

3. **SERVICE_MANAGEMENT.md** (lines 44-56):
```markdown
**⚠️ tmux Pattern**: Enter must be separate `send-keys` command or it gets ignored. See [SKILL.md](../SKILL.md) for details.

# Start services (from clean state)
# NOTE: Each Enter is SEPARATE command (critical!)
tmux new-session -d -s backend -c /path/to/my-project-backend
tmux send-keys -t backend "./start_services.sh"
tmux send-keys -t backend Enter
```

**AT Epic pattern duplication**:

1. **SKILL.md** (lines 232-300):
```markdown
### 🚨 MANDATORY: Acceptance Test Epic Pattern

**Every functional Epic MUST have a paired Acceptance Test (AT) Epic**...

#### The AT Epic Pattern

UBER-EPIC (the initiative)
├── EPIC: User Login Flow [parent-child]
│   ├── TASK: Implement login API
│   ├── TASK: Create login form
│   └── TASK: Add validation
├── EPIC: AT-User Login Flow [parent-child] ← MANDATORY PAIR
...
```

2. **BEADS_INTEGRATION.md** (lines 537-686):
```markdown
## Acceptance Test (AT) Epic Convention

Every functional epic requires a paired Acceptance Test epic...

### AT Epic Naming Convention

Functional Epic: "User Login Flow"
AT Epic:         "AT-User Login Flow"

### AT Epic Structure

UBER-EPIC: Q1 Authentication
├── EPIC: User Login Flow (my-project-abc)
...
```

**Service ports duplication**:

1. **SKILL.md** (lines 50-54):
```markdown
### Service Ports
- Frontend: 5001 | Backend: 8000 | eddy_validate: 5184 | user_chat: 5185
```

2. **SERVICE_MANAGEMENT.md** (lines 26-35):
```markdown
### Service Ports

| Service | Port | Purpose |
|---------|------|---------|
| Frontend (Next.js) | 5001 | React UI dev server |
| Backend (FastAPI) | 8000 | Main API server |
| eddy_validate (MCP) | 5184 | Education verification service |
| user_chat (MCP) | 5185 | Knowledge base service |
```

### Impact

- Updates require editing 2-3 files
- Risk of inconsistency between copies
- Maintenance burden

### Recommendation

Establish **single source of truth** for each concept:

| Concept | Canonical Location | Other Files |
|---------|-------------------|-------------|
| tmux Enter pattern | SKILL.md (top banner) | Reference only |
| AT Epic pattern | BEADS_INTEGRATION.md | SKILL.md references |
| Service ports | SERVICE_MANAGEMENT.md | SKILL.md references |
| Worker launch | WORKER_DELEGATION_GUIDE.md | SKILL.md references |

### Implementation Steps

1. Keep full content in canonical location
2. Replace duplicates with references:
   ```markdown
   **See the AT Epic convention section in the orchestrator skill documentation for the full AT Epic pattern.**
   ```
3. Estimated line reduction: ~100 lines

---

## Issue #6: Progress Tracking Ceremony Overhead

### Problem Description

PROGRESS_TRACKING.md defines extensive templates that add ceremony overhead during autonomous operation.

### Specific Line References

**PROGRESS_TRACKING.md - Summary template** (lines 66-126):
```markdown
### Template

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
...
```

**PROGRESS_TRACKING.md - Log template** (lines 168-230):
```markdown
### Template

# Progress Log

Append-only chronological record of orchestration sessions.

---

## [YYYY-MM-DD] Session [N]

**Duration:** ~[X] minutes
**Features Attempted:** F00X, F00Y
**Features Completed:** F00X

### What Was Done
...
### What Worked Well
...
### Challenges / Issues
...
```

**PROGRESS_TRACKING.md - Learning files** (lines 260-370):
```markdown
### Three Learning Categories

#### 1. Decomposition Patterns
**File:** `.claude/learnings/decomposition.md`

#### 2. Coordination Patterns
**File:** `.claude/learnings/coordination.md`

#### 3. Failure Patterns
**File:** `.claude/learnings/failures.md`
```

**PROGRESS_TRACKING.md - Handoff checklist** (lines 378-450):
```markdown
## Session Handoff Checklist

### 1. Feature State Clean
- [ ] Current feature either:
  - ✅ Complete (marked `passes: true`)
  - ✅ OR cleanly stopped
- [ ] No uncommitted code changes
- [ ] No active worker sessions

### 2. Feature List Updated
- [ ] {project-name}-feature_list.json updated
...
```

### Impact

- ~10 minutes overhead per session for documentation
- Duplicates information already captured in Beads and git
- Learning files rarely consulted (Serena memories more effective)

### Recommendation

Streamline to essential-only protocol:

1. **During session**: Beads + git commits capture everything
2. **End of session**: Quick scratch pad note only if complex context
3. **Replace learning files**: Use Serena memories instead

### Implementation Steps

1. Create lightweight handoff section in AUTONOMOUS_MODE.md (included above)
2. Mark PROGRESS_TRACKING.md as "DETAILED REFERENCE - USE FOR COMPLEX HANDOFFS ONLY"
3. Remove learning file requirements (use Serena memories)
4. Reduce handoff checklist to essentials

---

## Proposed File Restructure

### BEFORE (7 files, ~3,970 lines)

```
SKILL.md                    (600 lines)
FEATURE_DECOMPOSITION.md    (440 lines)
WORKER_DELEGATION_GUIDE.md  (600 lines)
BEADS_INTEGRATION.md        (690 lines)
TROUBLESHOOTING.md          (650 lines)
PROGRESS_TRACKING.md        (520 lines)
SERVICE_MANAGEMENT.md       (470 lines)
```

### AFTER (7 files + 2 new, ~3,300 lines active)

```
SKILL.md                    (420 lines) ← Streamlined, single state machine
PREFLIGHT.md                (120 lines) ← NEW: Unified mandatory checklist
AUTONOMOUS_MODE.md          (200 lines) ← NEW: Multi-feature session protocol
WORKER_DELEGATION_GUIDE.md  (500 lines) ← Condensed, owns worker patterns
BEADS_INTEGRATION.md        (600 lines) ← Owns AT epic, consolidated
TROUBLESHOOTING.md          (550 lines) ← Condensed recovery patterns
SERVICE_MANAGEMENT.md       (350 lines) ← Essentials only
PROGRESS_TRACKING.md        (300 lines) ← Marked as detailed reference
LEGACY_FEATURE_LIST.md      (250 lines) ← NEW: Archived legacy content
```

### Changes Summary

| Action | Files Affected | Line Change |
|--------|----------------|-------------|
| Create PREFLIGHT.md | New file | +120 |
| Create AUTONOMOUS_MODE.md | New file | +200 |
| Create LEGACY_FEATURE_LIST.md | New file | +250 |
| Consolidate decision trees | SKILL.md | -80 |
| Remove legacy dual-track | SKILL.md, WORKER_DELEGATION, FEATURE_DECOMP | -150 |
| Deduplicate references | SKILL.md, SERVICE_MANAGEMENT | -100 |
| Streamline progress tracking | PROGRESS_TRACKING.md | -220 |
| Consolidate AT epic | SKILL.md (reference only) | -50 |
| **NET CHANGE** | | **-30 lines** |

### Active vs Reference Files

**Active (consulted every session)**:
- SKILL.md (main workflow)
- PREFLIGHT.md (session start)
- AUTONOMOUS_MODE.md (multi-feature operation)
- BEADS_INTEGRATION.md (task management)

**Reference (consulted when needed)**:
- WORKER_DELEGATION_GUIDE.md (worker details)
- TROUBLESHOOTING.md (problem recovery)
- SERVICE_MANAGEMENT.md (service issues)
- PROGRESS_TRACKING.md (complex handoffs)
- LEGACY_FEATURE_LIST.md (migration only)

---

## Implementation Priority

### Phase 1: HIGH PRIORITY (Immediate)

1. **Create PREFLIGHT.md** - Consolidates all circuit breakers
   - Source: CLAUDE.md, SKILL.md lines 155-175, 520-560, SERVICE_MANAGEMENT.md lines 196-212
   - Impact: No missed mandatory steps

2. **Create AUTONOMOUS_MODE.md** - Enables true autonomous operation
   - Source: New content based on gap analysis
   - Impact: Multi-feature sessions without user intervention

### Phase 2: MEDIUM PRIORITY (Next)

3. **Create LEGACY_FEATURE_LIST.md** - Move legacy content
   - Source: SKILL.md, WORKER_DELEGATION_GUIDE.md, FEATURE_DECOMPOSITION.md
   - Impact: Cleaner main documentation

4. **Consolidate decision trees** - Single state machine
   - Source: SKILL.md lines 112-180, 258-290
   - Impact: Faster session starts

### Phase 3: LOW PRIORITY (When Convenient)

5. **Deduplicate references** - Single source of truth
   - Source: tmux pattern, AT epic, service ports
   - Impact: Easier maintenance

6. **Streamline progress tracking** - Lightweight protocol
   - Source: PROGRESS_TRACKING.md
   - Impact: Faster handoffs

---

## Success Metrics

After implementation, measure:

| Metric | Before | Target |
|--------|--------|--------|
| Session start time | ~5 min (multiple files) | <2 min (PREFLIGHT.md) |
| Decision clarity | 4+ trees to reconcile | 1 state machine |
| Missed circuit breakers | Risk of missing | Zero (unified checklist) |
| Multi-feature capability | No protocol | Explicit loop |
| Legacy confusion | Dual-track | Beads-only main path |
| Files to consult per session | 4-5 | 2-3 |

---

## Appendix: Files to Modify

### New Files to Create

1. `PREFLIGHT.md` - Session pre-flight checklist
2. `AUTONOMOUS_MODE.md` - Multi-feature autonomous protocol
3. `LEGACY_FEATURE_LIST.md` - Archived legacy documentation

### Existing Files to Modify

1. **SKILL.md**
   - Remove: Lines 55-85 (legacy commands), 112-180 (redundant decision trees), 258-290 (Phase 0 decision tree), 390-450 (legacy Phase 2)
   - Add: Unified state machine, references to new files
   - Condense: AT epic section (reference BEADS_INTEGRATION.md)

2. **WORKER_DELEGATION_GUIDE.md**
   - Remove: Lines 166-217 (legacy template)
   - Keep: Lines 110-165 (Beads template)

3. **FEATURE_DECOMPOSITION.md**
   - Remove: Lines 56-90 (legacy schema)
   - Keep: Lines 28-55 (Beads schema), MAKER checklist

4. **BEADS_INTEGRATION.md**
   - Remove: Lines 305-355 (migration, move to LEGACY)
   - Keep: AT epic as canonical source

5. **SERVICE_MANAGEMENT.md**
   - Remove: Lines 196-212 (pre-flight, move to PREFLIGHT.md)
   - Keep: Troubleshooting sections

6. **PROGRESS_TRACKING.md**
   - Add: Header marking as "DETAILED REFERENCE"
   - Simplify: Reduce mandatory handoff requirements

---

**Plan Status**: READY FOR IMPLEMENTATION
**Estimated Effort**: 2-3 hours
**Risk Level**: Low (additive changes, preserves existing content)
