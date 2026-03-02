---
title: "Guardian Workflow"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Guardian Workflow — End-to-End Reference

Complete workflow for the S3 Guardian pattern, from pre-flight checks through post-validation actions.

---

## 1. Pre-Flight Checks

Before beginning a guardian session, verify all prerequisites are met.

### 1.1 Environment Verification

```bash
# Verify config repo (where acceptance tests will live)
ls -la acceptance-tests/ 2>/dev/null || echo "Directory will be created"

# Verify implementation repo is accessible
ls -la /path/to/impl-repo/.taskmaster/docs/ 2>/dev/null || echo "ERROR: impl repo not found"

# Verify tmux is available
tmux -V

# Add cs-* scripts to PATH (REQUIRED — they are not system-wide commands)
export PATH="${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/completion-state:$PATH"

# Verify cs-promise CLI is available
cs-status 2>/dev/null || echo "ERROR: completion-state scripts not found"

# Verify ccsystem3 function is available
which ccsystem3 2>/dev/null || type ccsystem3 2>/dev/null
```

### 1.2 PRD Verification

```bash
# Check PRD exists
cat /path/to/impl-repo/.taskmaster/docs/PRD-{ID}.md | head -50

# Extract PRD metadata
grep -E "^#|^##|acceptance|criteria|epic|feature" /path/to/impl-repo/.taskmaster/docs/PRD-{ID}.md
```

### 1.3 Conflict Checks

```bash
# No existing tmux session with same name
tmux has-session -t "s3-{initiative}" 2>/dev/null && echo "WARNING: session exists" || echo "OK: no conflict"

# No existing acceptance tests (or confirm overwrite intent)
ls acceptance-tests/PRD-{ID}/ 2>/dev/null && echo "WARNING: tests exist, will be overwritten" || echo "OK: fresh"

# No stale completion state
cs-status 2>/dev/null | grep -i "pending\|in_progress"
```

### 1.4 Hindsight Context Gathering

Before creating acceptance tests, gather institutional knowledge about the initiative:

```python
# Check for previous guardian sessions on this PRD
previous = mcp__hindsight__reflect(
    f"Previous guardian validations for PRD-{prd_id} or similar initiatives",
    budget="mid",
    bank_id="system3-orchestrator"
)

# Check for known patterns in the implementation domain
domain_patterns = mcp__hindsight__reflect(
    f"Development patterns and anti-patterns for {domain}",
    budget="mid",
    bank_id="claude-code-{project}"
)
```

Use findings to calibrate acceptance test expectations and thresholds.

---

## 2. Acceptance Test Generation

### 2.1 Read and Analyze PRD

Read the entire PRD document. Extract a structured feature list:

```
Feature Extraction Template:
---
PRD: PRD-{ID}
Title: {PRD title}
Epics: {number of epics}

Features:
  - F1: {name} — {description} — Weight: {0.XX}
  - F2: {name} — {description} — Weight: {0.XX}
  ...

Total Weight Check: {sum} (must equal 1.00)
```

### 2.2 Determine Feature Weights

Weight assignment follows business criticality, not implementation complexity:

**Weight Calibration Process**:

1. Rank all features by "what breaks if this is missing?"
2. Assign the top feature 0.25-0.35 weight
3. Distribute remaining weight proportionally
4. Verify sum equals 1.00
5. Sanity check: would a product owner agree with this ranking?

**Common Mistakes**:
- Giving infrastructure features (logging, config) high weight — these rarely fail business validation
- Equal weights across all features — this dilutes the signal from core features
- Forgetting to account for cross-cutting concerns (error handling touches many features)

### 2.3 Write Gherkin Scenarios

For each feature, write 1-3 Gherkin scenarios. The number of scenarios depends on feature complexity:

| Feature Complexity | Scenarios |
|-------------------|-----------|
| Simple (single behavior) | 1 scenario |
| Medium (2-3 behaviors) | 2 scenarios |
| Complex (multiple states/paths) | 3 scenarios |

Each scenario follows this template:

```gherkin
  Scenario: {Descriptive name}
    Given {precondition — what must exist before testing}
    When {action — what the implementation should do}
    Then {outcome — what should be verifiable}

    # Confidence Scoring Guide:
    # 0.0 — {what total absence looks like}
    # 0.3 — {what partial/broken implementation looks like}
    # 0.5 — {what basic but incomplete implementation looks like}
    # 0.7 — {what solid implementation with minor gaps looks like}
    # 1.0 — {what complete, production-quality implementation looks like}
    #
    # Evidence to Check:
    #   - {specific file or function to examine}
    #   - {specific test to look for}
    #   - {specific behavior to verify}
    #
    # Red Flags:
    #   - {indicator of false or inflated claims}
    #   - {common shortcut that appears complete but isn't}
```

### 2.4 Create Manifest

Generate the manifest using the template script:

```bash
.claude/skills/s3-guardian/scripts/generate-manifest.sh PRD-{ID} "PRD Title"
```

Then populate the generated `manifest.yaml` with:
- Feature names, descriptions, and weights
- Scoring thresholds (ACCEPT, INVESTIGATE, REJECT)
- Validation protocol (which evidence sources to use)
- Implementation repo path

### 2.5 Verification of Test Quality

Before proceeding to meta-orchestrator spawning, verify acceptance test quality:

1. **Coverage check**: Every PRD feature has at least one scenario
2. **Weight sum**: Exactly 1.00
3. **Scoring guides**: Every scenario has a 0.0-1.0 calibration guide
4. **Evidence specificity**: Each scenario references concrete files or behaviors, not vague descriptions
5. **Red flag inclusion**: Every scenario has at least one red flag indicator

---

## 3. Meta-Orchestrator Spawning Sequence

### 3.1 Create Guardian Session Promise

Before spawning the meta-orchestrator, create the guardian's own session promise:

```bash
cs-init

cs-promise --create "Guardian: Validate PRD-{ID} implementation" \
    --ac "Acceptance tests created and stored in config repo" \
    --ac "S3 meta-orchestrator spawned and verified running" \
    --ac "Meta-orchestrator progress monitored through completion" \
    --ac "Independent validation scored against rubric" \
    --ac "Final verdict delivered with evidence"

cs-promise --start <promise-id>
```

### 3.2 Spawn Meta-Orchestrator

Execute the spawn sequence with proper error handling:

```bash
# Step 1: Create tmux session at implementation repo
tmux new-session -d -s "s3-{initiative}" -c "/path/to/impl-repo"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create tmux session"
    exit 1
fi

# Step 2: Unset CLAUDECODE (prevents nested session error)
tmux send-keys -t "s3-{initiative}" "unset CLAUDECODE"
tmux send-keys -t "s3-{initiative}" Enter
sleep 1

# Step 3: Launch ccsystem3
tmux send-keys -t "s3-{initiative}" "ccsystem3"
tmux send-keys -t "s3-{initiative}" Enter

# Step 4: Wait for initialization
sleep 15

# Step 5: Set output style for System 3 meta-orchestrator
tmux send-keys -t "s3-{initiative}" "/output-style system3-meta-orchestrator"
tmux send-keys -t "s3-{initiative}" Enter
sleep 3

# Step 6: Verify output style loaded
PANE_OUTPUT=$(tmux capture-pane -t "s3-{initiative}" -p -S -30)
echo "$PANE_OUTPUT" | grep -iE "system3-meta-orchestrator"
if [ $? -ne 0 ]; then
    echo "WARNING: Output style may not have loaded. Check manually."
fi
```

### 3.3 Send Initial Instructions

After verification, send the meta-orchestrator its mission:

```bash
# Construct the instruction payload
INSTRUCTION="You are the System 3 meta-orchestrator. Invoke Skill('s3-guardian') first. Then read PRD-{ID} at .taskmaster/docs/PRD-{ID}.md. Parse tasks with Task Master. Spawn orchestrators as needed. Report when all epics are complete."

# Send via tmux (text first, then Enter separately)
tmux send-keys -t "s3-{initiative}" "$INSTRUCTION"
sleep 2  # Large pastes need time for bracketed paste processing
tmux send-keys -t "s3-{initiative}" Enter
```

### 3.4 Session Resume (Alternative)

If resuming a previous meta-orchestrator session:

```bash
# Check if the session supports resume
tmux capture-pane -t "s3-{initiative}" -p -S -20 | grep -i "resume\|continue\|previous"

# Send resume command
tmux send-keys -t "s3-{initiative}" "/resume"
tmux send-keys -t "s3-{initiative}" Enter
sleep 5

# Verify resumed successfully
tmux capture-pane -t "s3-{initiative}" -p -S -20 | grep -iE "resumed|continuing|loaded"
```

### 3.5 Meet Spawn Acceptance Criteria

```bash
cs-promise --meet <id> --ac-id AC-2 --evidence "tmux session s3-{initiative} created, ccsystem3 launched, output style verified" --type manual
```

---

## 4. Monitoring Loop

### 4.1 Enter Monitoring State

Once the meta-orchestrator is confirmed running, enter the monitoring loop:

```
MONITORING LOOP:
  |
  +-- Capture tmux output
  |
  +-- Scan for signals
  |     |
  |     +-- AskUserQuestion → Intervene
  |     +-- Error pattern → Assess
  |     +-- Completion claim → Validate (Phase 4)
  |     +-- Normal work → Continue
  |
  +-- Check context percentage
  |     |
  |     +-- Above 80% → Expect auto-compact
  |     +-- Above 90% → Consider intervention
  |
  +-- Sleep (cadence-dependent)
  |
  +-- [REPEAT]
```

### 4.2 Cadence Adaptation

Adjust monitoring frequency based on what the meta-orchestrator is doing:

```bash
# Check meta-orchestrator activity
OUTPUT=$(tmux capture-pane -t "s3-{initiative}" -p -S -30)

# Determine cadence
if echo "$OUTPUT" | grep -qiE "edit|write|commit|test"; then
    CADENCE=30   # Active implementation — check frequently
elif echo "$OUTPUT" | grep -qiE "read|grep|analyze|plan"; then
    CADENCE=60   # Investigation phase — less frequent
elif echo "$OUTPUT" | grep -qiE "sleep|wait|idle|background"; then
    CADENCE=120  # Waiting for workers — infrequent
else
    CADENCE=60   # Default
fi

sleep $CADENCE
```

### 4.3 Intervention Protocol

When intervention is needed, follow this decision tree:

1. **AskUserQuestion / Permission Dialog**:
   - Check what is being asked
   - If it is a routine permission (file access, tool use): approve via Down/Enter
   - If it is a strategic question: answer based on PRD scope

2. **Repeated Errors**:
   - Count occurrences of the same error pattern
   - After 3 occurrences: send corrective guidance via tmux
   - After 5 occurrences: consider killing and restarting the session

3. **Scope Creep**:
   - Compare current work against PRD scope
   - If meta-orchestrator is working on unrelated features: send correction
   - If meta-orchestrator is over-engineering: remind of scope boundaries

4. **Time Limits**:
   - Typical initiative: 1-3 hours for implementation
   - At 2 hours: check progress percentage
   - At 3 hours: seriously consider partial completion + validation

### 4.4 Meet Monitoring Acceptance Criteria

When the meta-orchestrator signals completion (or time limit is reached):

```bash
cs-promise --meet <id> --ac-id AC-3 --evidence "Monitored s3-{initiative} for {duration}, {intervention_count} interventions performed" --type manual
```

---

## 5. Validation Cycle

### 5.1 Load Acceptance Rubric

```bash
# Read manifest
cat acceptance-tests/PRD-{ID}/manifest.yaml

# Read all feature files
cat acceptance-tests/PRD-{ID}/*.feature
```

### 5.2 Independent Evidence Gathering

For each feature in the manifest, gather evidence independently:

```bash
# Git history for the implementation period
git -C /path/to/impl-repo log --oneline --since="3 hours ago"
git -C /path/to/impl-repo show --stat HEAD~15..HEAD

# Specific file examination
cat /path/to/impl-repo/src/{file_referenced_in_scenario}

# Test results (if test suite exists)
cd /path/to/impl-repo && python -m pytest --tb=short -q 2>&1

# Import/dependency verification
grep -r "import\|from\|require" /path/to/impl-repo/src/ | grep "{expected_dependency}"
```

### 5.3 Score Each Scenario

For each Gherkin scenario, assign a confidence score using the scenario's scoring guide:

```
Scoring Worksheet:
---
Feature: F1 — {name} (weight: 0.30, validation_method: browser-required)
  Scenario 1: {name}
    Evidence found: {what was actually observed}
    Red flags detected: {any red flags from the guide}
    Score: 0.X
    Rationale: {why this score, not higher/lower}

  Scenario 2: {name}
    Evidence found: {what was actually observed}
    Red flags detected: {any red flags from the guide}
    Score: 0.X
    Rationale: {why this score, not higher/lower}

  Feature Score: average(scenario scores) = 0.XX
  Weighted Contribution: 0.XX * 0.30 = 0.XXX

Feature: F2 — {name} (weight: 0.20, validation_method: api-required)
  ...

TOTAL WEIGHTED SCORE: sum(weighted contributions) = 0.XXX
```

### 5.3b Evidence Gate Check

After scoring all features but BEFORE computing the weighted total, apply the evidence gate for features with `validation_method` = `browser-required` or `api-required`:

```
Evidence Gate:
---
Feature: F1 — {name} (validation_method: browser-required)
  Evidence keywords found: ["screenshot", "navigate", "localhost:3000"]
  Minimum required: 2
  Keywords found: 3
  Gate result: PASS (score unchanged)

Feature: F3 — {name} (validation_method: browser-required)
  Evidence keywords found: ["Read file", "grep"]
  Minimum required: 2
  Browser keywords found: 0
  Gate result: FAIL — Score overridden from 0.80 to 0.00
  Reason: EVIDENCE GATE: browser-required feature scored without browser evidence

Feature: F2 — {name} (validation_method: api-required)
  Evidence keywords found: ["curl", "HTTP 200", "localhost:8000"]
  Minimum required: 2
  Keywords found: 3
  Gate result: PASS (score unchanged)
```

See [validation-scoring.md](validation-scoring.md) Section 10 for the complete keyword reference.

### 5.4 Make Decision

Compare the total weighted score against manifest thresholds:

```
Score: 0.XXX
ACCEPT threshold: 0.60
INVESTIGATE range: 0.40-0.59
REJECT threshold: < 0.40

DECISION: {ACCEPT | INVESTIGATE | REJECT}
```

### 5.5 Report Generation

Generate a structured validation report:

```markdown
# Guardian Validation Report: PRD-{ID}

## Summary
- **Decision**: {ACCEPT | INVESTIGATE | REJECT}
- **Weighted Score**: {0.XX} / 1.00
- **Implementation Duration**: {time}
- **Interventions**: {count}

## Feature Scores

| Feature | Weight | Score | Weighted | Notes |
|---------|--------|-------|----------|-------|
| F1: {name} | 0.30 | 0.80 | 0.240 | {brief note} |
| F2: {name} | 0.20 | 0.65 | 0.130 | {brief note} |
| ... | ... | ... | ... | ... |
| **Total** | **1.00** | - | **0.XXX** | |

## Gaps Identified
1. {gap description with affected feature}
2. {gap description with affected feature}

## Red Flags Detected
1. {red flag and its implications}

## Recommendations
- {next steps based on decision}
```

---

## 6. Post-Validation Actions

### 6.1 ACCEPT Path

```bash
# Meet validation acceptance criteria
cs-promise --meet <id> --ac-id AC-4 --evidence "Weighted score: 0.XX, above ACCEPT threshold 0.60" --type manual
cs-promise --meet <id> --ac-id AC-5 --evidence "ACCEPT verdict delivered, report stored" --type manual

# Store to Hindsight
# (see SKILL.md "Storing Validation Results" section)

# Verify guardian promise is complete
cs-verify --check --verbose
```

### 6.2 INVESTIGATE Path

```bash
# Identify specific gaps that need attention
# Create a targeted follow-up plan
# Optionally spawn a new meta-orchestrator session focused on gaps

# Do NOT meet AC-4 yet — investigation is not acceptance
# Log the gaps for tracking
cs-verify --log --action "INVESTIGATE verdict for PRD-{ID}" --outcome "partial" \
    --learning "Gaps found in: {feature_list}"
```

### 6.3 REJECT Path

```bash
# Document specific failures
# Store anti-patterns to Hindsight
# Plan full reimplementation cycle

cs-verify --log --action "REJECT verdict for PRD-{ID}" --outcome "failed" \
    --learning "Critical failures in: {feature_list}. Score: {0.XX}"
```

### 6.4 Meta-Orchestrator Cleanup

After validation is complete (regardless of verdict):

```bash
# Check if meta-orchestrator session is still running
tmux has-session -t "s3-{initiative}" 2>/dev/null

# If running and verdict is ACCEPT — let it finish naturally or send shutdown
tmux send-keys -t "s3-{initiative}" "All work validated. You may finalize and exit."
sleep 2
tmux send-keys -t "s3-{initiative}" Enter

# If running and verdict is REJECT — send correction
tmux send-keys -t "s3-{initiative}" "Guardian validation REJECTED. Gaps: {summary}. Address these issues."
sleep 2
tmux send-keys -t "s3-{initiative}" Enter
```

---

## 7. Timeline Reference

Typical guardian session timeline for a medium-complexity PRD:

| Phase | Duration | Activities |
|-------|----------|------------|
| Pre-flight | 5 min | Environment checks, Hindsight queries |
| Acceptance test creation | 15-30 min | PRD analysis, Gherkin writing, manifest creation |
| Meta-orchestrator spawning | 2-5 min | tmux setup, ccsystem3 launch, verification |
| Monitoring | 1-3 hours | Continuous oversight, periodic interventions |
| Independent validation | 15-30 min | Evidence gathering, scoring, report generation |
| Post-validation | 5-10 min | Hindsight storage, cleanup, promise completion |
| **Total** | **1.5-4 hours** | |

---

## Guardian Phase 2: Orchestrator Spawning (Full Reference)

> Extracted from s3-guardian SKILL.md — complete orchestrator spawning procedure including DOT dispatch, tmux patterns, SDK mode, and wisdom injection.

### Overview

Two dispatch modes are available. Choose based on the use case:

| Mode | When to Use | How It Works |
|------|-------------|--------------|
| **SDK mode** | Automated pipelines, E2E tests, CI/CD | `launch_guardian.py` drives the full chain via `claude_code_sdk` — no tmux |
| **tmux mode** | Interactive sessions, long-running epics | Guardian spawns orchestrators in tmux sessions for manual monitoring |

**SDK mode architecture** (validated E2E 2026-03-02):
```
launch_guardian.py ──SDK──► guardian_agent.py ──SDK──► runner (spawn_runner.py)
                                                          ──SDK──► orchestrator (worker)
```
All 4 layers run headless via `claude_code_sdk`. No tmux sessions, no interactive prompts. The guardian reads the DOT pipeline, dispatches research nodes (synchronous), then spawns runners for codergen nodes. Each runner spawns an orchestrator that implements the work.

**tmux mode architecture** (interactive):
```
Guardian (this session) ──spawns──► Orchestrator A (orch-epic1) ──delegates──► Workers
                        ──spawns──► Orchestrator B (orch-epic2) ──delegates──► Workers
```

### Research Nodes (Mandatory Before Implementation)

Every codergen node SHOULD have a preceding research node that validates framework patterns against current documentation before implementation begins.

**Research node DOT attributes:**
```dot
research_impl_auth [
    shape=tab
    label="Research\nAuth Patterns"
    handler="research"
    downstream_node="impl_auth"
    solution_design="docs/sds/SD-AUTH-001-login.md"
    research_queries="fastapi,pydantic,supabase"
    prd_ref="PRD-AUTH-001"
    status="pending"
];

research_impl_auth -> impl_auth [label="research_complete"];
```

**What research nodes do:**
1. Read the Solution Design document
2. Validate framework patterns via Context7 (docs) and Perplexity (cross-validation)
3. **Update the SD directly** with corrected patterns — no side-channel injection needed
4. Write evidence to `.claude/evidence/{node_id}/research-findings.json`
5. Persist learnings to Hindsight (LLM-driven reflect + retain)

**Key design insight**: The SD is the single source of truth. Research nodes correct the SD itself, so downstream orchestrators get current patterns automatically by reading the SD they already reference.

Research runs synchronously before codergen dispatch (~15-30s, Haiku model, ~$0.02). The guardian handles dispatch and state transitions internally.

**Known limitation**: Research validates against *latest published docs* but does not check the *locally installed version*. If the local environment has an older version (e.g., pydantic-ai 1.58.0 vs documented 1.63.0), API attribute names may differ. Mitigation: pin dependency versions in the SD or add a local version check to the research prompt.

### SDK Mode Dispatch

For automated pipelines, use `launch_guardian.py`:

```bash
python3 .claude/scripts/attractor/launch_guardian.py \
    --dot-file .claude/attractor/pipelines/${INITIATIVE}.dot \
    --target-dir /path/to/target \
    --model claude-sonnet-4-6 \
    --max-turns 200
```

The guardian automatically:
1. Validates the DOT pipeline
2. Dispatches research nodes (synchronous, before codergen)
3. Transitions nodes through the state machine (pending → active → validated)
4. Spawns runners for codergen nodes via SDK
5. Handles validation gates
6. Exits when all nodes reach `validated` or a node fails

### tmux Mode Pre-flight Checks

Before spawning in tmux mode, verify:
- [ ] Implementation repo exists and is accessible
- [ ] PRD exists in `.taskmaster/docs/PRD-{ID}.md` (business artifact)
- [ ] SD exists per epic in `.taskmaster/docs/SD-{ID}.md` (technical spec; Task Master input)
- [ ] Acceptance tests have been created from SD (Phase 1 complete)
- [ ] DOT pipeline exists AND validates: `cobuilder pipeline validate <pipeline.dot>` exits 0. If missing, STOP and run Step 0.2 first — do NOT proceed to spawn without a pipeline.
- [ ] DOT codergen nodes have `solution_design` attribute pointing to their SD file
- [ ] Research nodes precede codergen nodes with correct `downstream_node` edges
- [ ] No existing tmux session with the same name
- [ ] Hindsight wisdom gathered from project bank

### Gather Wisdom from Hindsight

Before spawning each orchestrator, query the project Hindsight bank:

```python
PROJECT_BANK = os.environ.get("CLAUDE_PROJECT_BANK", "claude-harness-setup")
wisdom = mcp__hindsight__reflect(
    query=f"What patterns apply to {epic_name}? Any anti-patterns or lessons for this domain?",
    budget="mid",
    bank_id=PROJECT_BANK
)
# Include the wisdom output in the orchestrator's initialization prompt
```

### DOT Pipeline-Driven Dispatch

When a DOT pipeline exists, identify dispatchable nodes before spawning:

```bash
PIPELINE="/path/to/impl-repo/.claude/attractor/pipelines/${INITIATIVE}.dot"
CLI="python3 /path/to/impl-repo/.claude/scripts/attractor/cli.py"

# Find nodes with all upstream deps validated
$CLI status "$PIPELINE" --filter=pending --deps-met --json

# Transition node to active before dispatch (one per orchestrator)
$CLI transition "$PIPELINE" <node_id> active
$CLI checkpoint save "$PIPELINE"
```

Each orchestrator targets one pipeline node. Include the node's `acceptance`, `worker_type`, `file_path/folder_path`, and `bead_id` attributes in the initialization prompt.

### Critical tmux Patterns

**These patterns are mandatory. Violating them causes silent failures.**

**Pattern 1 — Enter as separate send-keys call** (not appended to the command):
```bash
# WRONG — Enter gets silently ignored
tmux send-keys -t "orch-epic1" "ccorch" Enter

# CORRECT
tmux send-keys -t "orch-epic1" "ccorch"
tmux send-keys -t "orch-epic1" Enter
```

**Pattern 2 — Use `ccorch` not plain `claude`** (prevents invisible permission dialog blocks):
```bash
# WRONG — orchestrator blocks silently on approval dialogs
tmux send-keys -t "orch-epic1" "claude"
tmux send-keys -t "orch-epic1" Enter

# CORRECT
tmux send-keys -t "orch-epic1" "ccorch"
tmux send-keys -t "orch-epic1" Enter
```

**Pattern 3 — Interactive mode is MANDATORY** (headless orchestrators cannot spawn native teams):
```bash
# WRONG — headless mode cannot spawn workers
claude -p "Do the work"

# CORRECT — interactive allows team spawning
tmux send-keys -t "orch-epic1" "ccorch"
tmux send-keys -t "orch-epic1" Enter
```

**Pattern 4 — Large pastes need `sleep 2` before Enter** (bracketed paste processing takes time):
```bash
tmux send-keys -t "orch-epic1" "$(cat /tmp/wisdom-epic1.md)"
sleep 2   # Wait for bracketed paste to complete
tmux send-keys -t "orch-epic1" Enter
```

### The Mandatory 3-Step Boot Sequence

Every orchestrator MUST go through these 3 steps in this exact order. No exceptions.

```
Step 1: ccorch          → Sets 9 env vars (output style, session ID, agent teams, etc.)
Step 2: /output-style   → Loads orchestrator persona and delegation rules
Step 3: Skill prompt    → Orchestrator invokes Skill("orchestrator-multiagent") before any work
```

Skipping ANY step produces a crippled orchestrator that either:
- Has no delegation rules (missing Step 2) → tries to implement directly
- Has no team coordination patterns (missing Step 3) → cannot spawn workers
- Has no session tracking, no model selection, no chrome (missing Step 1) → everything breaks silently

### Spawn Sequence: Use `spawn_orchestrator.py` (MANDATORY)

**Always use the canonical spawn script.** Never write ad-hoc tmux Bash for spawning.

The script at `.claude/scripts/attractor/spawn_orchestrator.py` handles:
- tmux session creation with `exec zsh` and correct dimensions
- `unset CLAUDECODE && ccorch --worktree <node_id>` (Step 1)
- `/output-style orchestrator` (Step 2)
- Prompt delivery (Step 3)
- Pattern 1 (Enter as separate send-keys call)
- Respawn logic if session dies

**CRITICAL: `IMPL_REPO` must point to the directory that contains `.claude/`** — this is the Claude Code project root. For monorepo layouts like `zenagent2/zenagent/agencheck/`, the project root is at `agencheck/` (where `.claude/output-styles/`, `.claude/settings.json`, etc. live), NOT at a subdirectory like `agencheck-support-agent/` or `agencheck-support-frontend/`. Spawning at the wrong level means the orchestrator boots without output styles, hooks, or skills.

```bash
EPIC_NAME="epic1"
# ✅ CORRECT: points to directory containing .claude/
IMPL_REPO="/path/to/impl-repo/agencheck"
# ❌ WRONG: git root — .claude/ is in agencheck/, not here
# IMPL_REPO="/path/to/impl-repo/zenagent"  # DON'T use the git/monorepo root!
# ❌ WRONG: subdirectory — no .claude/ here, orchestrator boots broken
# IMPL_REPO="/path/to/impl-repo/agencheck/agencheck-support-agent"  # DON'T use subdirectories!
PRD_ID="PRD-XXX-001"

# 1. Write the wisdom/prompt to a temp file FIRST
#    SD_PATH is the solution_design attribute from the DOT node
#    e.g., SD_PATH=".taskmaster/docs/SD-AUTH-001-login.md"
cat > "/tmp/wisdom-${EPIC_NAME}.md" << 'WISDOMEOF'
You are an orchestrator for initiative: ${EPIC_NAME}

> Your output style was set to "orchestrator" by the guardian during spawn.

## FIRST ACTIONS (Mandatory — do these BEFORE any investigation or implementation)
1. Skill("orchestrator-multiagent")   ← This loads your delegation patterns
2. Teammate(operation="spawnTeam", team_name="${EPIC_NAME}-workers", description="Workers for ${EPIC_NAME}")

## Your Mission
${EPIC_DESCRIPTION}

## Solution Design (Primary Technical Reference)
Your full technical specification is in: ${SD_PATH}
Read it before delegating to workers. Key sections:
- Section 2: Technical Architecture (data models, API contracts, component design)
- Section 4: Functional Decomposition (features with explicit dependencies)
- Section 6: Acceptance Criteria per Feature (definition of done for each worker task)
- Section 8: File Scope (which files workers are allowed to touch)

## DOT Node Scope (pipeline-driven)
- Node ID: ${NODE_ID}
- Acceptance: "${ACCEPTANCE_CRITERIA}"
- File Scope: ${FILE_PATHS} (see SD Section 8 for full scoping)
- Bead ID: ${BEAD_ID}

## Patterns from Hindsight
${WISDOM_FROM_HINDSIGHT}

## On Completion
Update bead to impl_complete: bd update ${BEAD_ID} --status=impl_complete
WISDOMEOF

# 2. Spawn via canonical script (handles Steps 1-3 of the boot sequence)
python3 "${IMPL_REPO}/.claude/scripts/attractor/spawn_orchestrator.py" \
    --node "${EPIC_NAME}" \
    --prd "${PRD_ID}" \
    --repo-root "${IMPL_REPO}" \
    --prompt "Read the file at /tmp/wisdom-${EPIC_NAME}.md and follow those instructions. Your FIRST ACTION must be: Skill(\"orchestrator-multiagent\")"

# 3. Verify spawn succeeded (script outputs JSON)
# {"status": "ok", "session": "orch-epic1", ...}
```

**What `spawn_orchestrator.py` does internally** (you should NOT replicate this manually):
1. Creates tmux session with `exec zsh` in `--repo-root` directory
2. Sends `unset CLAUDECODE && ccorch --worktree <node>` (8s pause) — **Step 1**
3. Sends `/output-style orchestrator` (3s pause) — **Step 2**
4. Sends the `--prompt` text (2s pause) — **Step 3**
5. All sends use Pattern 1 (Enter as separate call)

### Anti-Pattern: Ad-Hoc Bash Spawn (NEVER DO THIS)

The following code was found in a real session. It produces a **broken orchestrator** that lacks output style, delegation patterns, session tracking, and agent team support:

```bash
# ❌ WRONG — 5 critical violations that produce a crippled orchestrator
tmux new-session -d -s "orch-v2-ux" -c "$WORK_DIR"
sleep 1
tmux send-keys -t "orch-v2-ux" "exec zsh" Enter           # ❌ Pattern 1: Enter appended
sleep 2
tmux send-keys -t "orch-v2-ux" "unset CLAUDECODE && cd $WORK_DIR && claude --dangerously-skip-permissions" Enter
#                                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#                                    ❌ Uses plain `claude` instead of `ccorch`
#                                    ❌ Missing: output style, session ID, agent teams,
#                                       task list, project bank, model, chrome flag
sleep 10
tmux send-keys -t "orch-v2-ux" "$WISDOM"                   # ❌ No /output-style step
sleep 2                                                      # ❌ No Skill("orchestrator-multiagent")
tmux send-keys -t "orch-v2-ux" "" Enter
```

**Why each violation matters:**

| Violation | Consequence |
|-----------|-------------|
| `claude` instead of `ccorch` | No `CLAUDE_OUTPUT_STYLE`, no `CLAUDE_SESSION_ID`, no `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`, no `--model claude-opus-4-6`, no `--chrome`. Orchestrator boots as a generic Claude session. |
| No `/output-style orchestrator` | Orchestrator has no delegation rules — will try to implement code directly instead of spawning workers. |
| No `Skill("orchestrator-multiagent")` in prompt | Orchestrator doesn't know HOW to create teams, delegate tasks, or coordinate workers. |
| `Enter` appended to command | tmux may silently drop the Enter key, causing commands to not execute. |
| Direct paste instead of file reference | Large wisdom text can overflow tmux paste buffer, causing truncation. |
| `IMPL_REPO` points to git/monorepo root instead of `.claude/` root | Worktree created at wrong level; orchestrator can't find output styles, hooks, or skills. e.g., using `zenagent/` instead of `zenagent/agencheck/`. |
| `IMPL_REPO` points to subdirectory instead of `.claude/` root | Orchestrator boots without output styles, hooks, or skills. e.g., using `agencheck-support-agent/` instead of `agencheck/`. |

**The fix is always the same:** Use `spawn_orchestrator.py` with `--repo-root` pointing to the directory that contains `.claude/`.

### Parallel Spawning (Multiple Epics)

When multiple DOT nodes have no dependency relationship, spawn orchestrators in parallel:

```bash
# Check edges to confirm independence before parallel dispatch
cobuilder pipeline edge-list "${PIPELINE}" --output json

# Spawn each independent node as a separate orchestrator
for NODE_ID in node1 node2 node3; do
    EPIC_NAME="${NODE_ID}"
    # ... run spawn sequence above for each ...
done
```

### After Spawn: Communication Hierarchy

The guardian monitors orchestrators DIRECTLY:

```
Guardian ──monitors──► Orchestrator ──delegates──► Workers (native teams)
   │                       ▲
   └──── sends guidance ───┘
```

| Action | Target | When |
|--------|--------|------|
| Send guidance/corrections | Orchestrator tmux session | Primary channel |
| Monitor output (read-only) | Orchestrator tmux session | Continuous |
| Answer AskUserQuestion | Whichever session shows the dialog | Immediately (blocks are time-critical) |

Proceed to **Phase 3: Monitoring** after all orchestrators are spawned and running.

### CoBuilder Boot Sequence for Orchestrators

Every orchestrator session needs a functional RepoMap baseline before work begins.
Since `.repomap/` is committed to git and worktrees are full git checkouts, the
baseline is already present. The orchestrator only needs to verify it and know
the refresh commands for post-node-validation use.

Include these commands in the initial prompt sent to every orchestrator tmux session:

```
## CoBuilder Commands Available in This Session

# Verify baseline exists and is recent
cobuilder repomap status --name ${REPO_NAME}

# After completing your work (automatic via post-validated hook, manual fallback):
cobuilder repomap refresh --name ${REPO_NAME} --scope <file1> --scope <file2>

# Full resync if you added many new files:
cobuilder repomap sync --name ${REPO_NAME}
```

Set these environment variables in the tmux session alongside CLAUDE_SESSION_ID:

```bash
export COBUILDER_REPO_NAME="${REPO_NAME}"
export COBUILDER_PIPELINE_DOT="${PIPELINE_DOT_PATH}"
export COBUILDER_ENFORCE_FRESHNESS=1
```

The post-validation hook in `transition.py` handles per-node refresh automatically.
Manual refresh is only needed if the hook missed files (nodes without `file_path`
attributes) or if the hook logged an error.

After the orchestrator completes, invoke cleanup explicitly:

```bash
python cobuilder/orchestration/spawn_orchestrator.py \
    --node ${NODE_ID} \
    --prd ${PRD_REF} \
    --repo-root ${REPO_ROOT} \
    --on-cleanup \
    --repo-name ${REPO_NAME}
```

---

**Reference Version**: 0.1.0
**Parent Skill**: s3-guardian
