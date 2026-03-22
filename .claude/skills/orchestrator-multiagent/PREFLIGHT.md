---
title: "Preflight"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Session Pre-Flight Checklist

**ALL STEPS MANDATORY - NO EXCEPTIONS**

> **Purpose**: Consolidate all circuit breakers into ONE unified checklist to eliminate missed mandatory steps.

---

## Phase 1: Environment Setup (30 seconds)

### [ ] Agent Teams Enabled

```bash
# Verify CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS is set
echo $CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
# Must output: 1
# If not set: export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
```

### [ ] Serena Active (MANDATORY — enables all code navigation)

```bash
mcp__serena__check_onboarding_performed
# If not active: mcp__serena__activate_project with project="<project-name>"

# Set session mode based on work type:
mcp__serena__switch_modes(["editing", "interactive"])  # For implementation sessions
# OR mcp__serena__switch_modes(["planning", "one-shot"])  # For design sessions
```

**Once active, use Serena's symbolic tools for ALL code investigation:**

| Task | Tool | Replaces |
|------|------|---------|
| Read a function | `find_symbol(name_path="Class/method", include_body=True)` | `Read` entire file |
| Understand a class | `find_symbol(name_path="Class", depth=1)` | `Read` entire file |
| Find callers | `find_referencing_symbols("Class/method")` | `Grep` + reading |
| Search codebase | `search_for_pattern("pattern")` | `Grep` + manual |
| Edit a method | `replace_symbol_body("Class/method", new_body)` | `Edit` with long strings |

**Reserve `Read` for**: Non-code files only (PRDs, YAML configs, markdown docs).
**Reserve `Grep`/`Glob` for**: When you don't know the symbol name or need file-pattern matching.

### [ ] Services Healthy

```bash
lsof -i :5001 -i :8000 -i :5184 -i :5185 | grep LISTEN
# Must show 4 ports listening. If not: see VALIDATION.md (Service Management section)
```

**Expected output** (all 4 services):
| Port | Service |
|------|---------|
| 5001 | Frontend (Next.js) |
| 8000 | Backend (FastAPI) |
| 5184 | eddy_validate (MCP) |
| 5185 | user_chat (MCP) |

### [ ] Git Clean

```bash
git status
# Must show clean working tree or only expected staged changes
```

### [ ] Create Worker Team

```python
# Create the team for this initiative's workers (once per session)
Teammate(
    operation="spawnTeam",
    team_name="{initiative}-workers",
    description="Workers for {initiative}"
)
# Workers will be spawned into this team as needed during execution
```

---

## Phase 2: Context Loading (60 seconds)

### [ ] Memory Context Retrieved (Hindsight)

```python
# Step 1: Recall task-relevant context
mcp__hindsight__recall("context about current task domain")

# Step 2: Recall recent patterns
mcp__hindsight__recall("recent patterns and lessons learned")
```

**Document in scratch pad**:
```markdown
## Memories Consulted
- Hindsight recalls: [key context retrieved]
- Relevant patterns: [applicable patterns]
- Known gotchas: [any warnings from past sessions]
```

### [ ] 🧠 CHECKPOINT: Context Validation

```python
# MANDATORY after loading memories - validates sufficient context before proceeding
# Ask yourself: Do I have enough context? What patterns apply? What am I missing?

# If patterns suggest a particular approach:
mcp__hindsight__reflect(
    query="What approach should I take for [current task] based on past patterns?",
    budget="mid"
)
```

### [ ] Beads Status

```bash
bd ready
# Shows available unblocked tasks
```

---

## Phase 3: Regression Validation (2-5 minutes)

### [ ] Select 1-2 Closed Beads

```bash
bd list --status=closed
# Pick recently closed items for spot-check
```

### [ ] Run Validation for Each (THREE LEVELS)

**Level 1: Unit Tests**
```bash
# Backend
cd my-project-backend && pytest tests/ -v --tb=short

# Frontend
cd my-project-frontend && npm run test
```

**Level 2: API Tests**
```bash
# Health checks
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:5184/health | jq .
curl -s http://localhost:5185/health | jq .
```

**Level 3: E2E Browser Tests**
```javascript
// Use chrome-devtools MCP
mcp__chrome-devtools__navigate_page({ url: "http://localhost:5001" })
mcp__chrome-devtools__take_snapshot({})
```

### [ ] Handle Regressions

```bash
# If ANY validation fails:
bd reopen <id> --reason "Regression: [description]"
# FIX BEFORE PROCEEDING to new work
```

---

## Phase 4: Session Goal Determination

### [ ] Check Initiative Status

```bash
bd list --type=epic
# Existing uber-epic? → Continue to Phase 2 (see WORKFLOWS.md)
# No uber-epic? → Create one first (MANDATORY)
```

### [ ] 🧠 CHECKPOINT: Session Goal Alignment

```python
# MANDATORY before starting work - ensures alignment with initiative
# Ask yourself: Is my session goal aligned with the uber-epic? Am I in the right mode?

# Check for relevant initiative context in Hindsight:
mcp__hindsight__recall("What is the current initiative and its goals?")
```

### [ ] For New Initiatives (MANDATORY Structure)

```bash
# Step 1: Create uber-epic
bd create --title="[Initiative Name]" --type=epic --priority=1
# Save the returned ID (e.g., my-project-xyz)

# Step 2: Create capability stream epics
bd create --title="[Stream A]" --type=epic --priority=2
bd dep add <epic-a-id> <uber-epic-id> --type=parent-child

# Step 3: Create AT epic for each functional epic (MANDATORY)
bd create --title="AT-[Stream A]" --type=epic --priority=2
bd dep add <at-epic-id> <uber-epic-id> --type=parent-child
bd dep add <epic-a-id> <at-epic-id> --type=blocks
```

**See the AT Epic convention section in the orchestrator skill documentation for the full AT Epic pattern.**

---

## Pre-Flight Complete

**All boxes checked?** → Proceed to multi-feature session execution via [WORKFLOWS.md](WORKFLOWS.md).

**Any box failed?** → Resolve before proceeding. See:
- Service issues and troubleshooting: [VALIDATION.md](VALIDATION.md#service-management)

---

**Version**: 1.3
**Created**: 2025-12-21
**Updated**: 2026-02-22
**Source**: Consolidated from CLAUDE.md, SKILL.md, SERVICE_MANAGEMENT.md circuit breaker sections
**v1.3 Changes**:
- Strengthened Serena section: added symbolic tool usage table, reserve guidance for Read/Grep/Glob
- Clarified that Serena is for code navigation (not memory); Hindsight is for memory
**v1.2 Changes**:
- Added Agent Teams env var check (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) to Phase 1
- Added "Create Worker Team" step (`Teammate(operation="spawnTeam", ...)`) to Phase 1
**v1.1 Changes**:
- Memory checks: replaced Serena/Byterover memory tools with Hindsight `recall` and `reflect`
- Updated Phase 2 to use `mcp__hindsight__recall()` for context loading
- Note: Serena was never removed for CODE navigation — only for memory operations
