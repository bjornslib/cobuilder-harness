---
title: "Phase 0: PRD Design & Challenge"
status: active
type: reference
grade: authoritative
---

## Phase 0: PRD Design & Challenge

When the guardian is initiating a new initiative (rather than validating an existing one), it must first design the Business Spec (BS), create the pipeline infrastructure, and challenge its own design before proceeding to acceptance test creation.

**Skip Phase 0 if**: A finalized BS already exists at the implementation repo's `docs/prds/PRD-{ID}.md` and has been reviewed. Proceed directly to Phase 1.

> **Note on file paths**: New Business Specs (BS) are written to `docs/specs/business/`. Historical specs remain in `docs/prds/`.

### Step 0.1: Business Spec (BS) Authoring with CoBuilder RepoMap Context

Before writing the Business Spec (BS), understand the current codebase structure using CoBuilder's RepoMap context command:

```bash
# Generate structured YAML codebase context filtered to the relevant PRD scope
cobuilder repomap context --name <repo-name> --prd PRD-{ID}

# For agent-consumable output (recommended when delegating to solution-design-architect):
cobuilder repomap context --name <repo-name> --prd PRD-{ID} --format yaml
```

The command outputs structured YAML with module relevance, dependency graph, and protected files:

```yaml
# Example output of: cobuilder repomap context --name agencheck --prd PRD-AUTH-001

repository: agencheck
snapshot_date: 2026-02-27T10:00:00Z
total_nodes: 3037
total_files: 312

modules_relevant_to_epic:
  - name: src/auth/
    delta: existing          # existing | modified | new
    files: 8
    summary: |
      Authentication module with JWT handling.
      Fully implemented — no changes needed for this epic.
    key_interfaces:
      - signature: "authenticate(token: str) -> User"
        file: src/auth/middleware.py
        line: 42

  - name: src/api/routes/
    delta: modified
    files: 12
    summary: |
      API route handlers for all endpoints.
      Needs new refresh token endpoint added.
    change_summary: "Add POST /auth/refresh route handler"

  - name: src/email/
    delta: new
    files: 0
    summary: |
      Email notification service — does not exist yet.
      Needs to be created from scratch.
    suggested_structure:
      - email_service/__init__.py
      - email_service/sender.py

dependency_graph:
  - from: src/api/routes/
    to: src/auth/
    type: invokes
    description: "Route handlers call authenticate()"

protected_files:
  - path: src/database/models.py
    reason: "Core data models — shared across all modules"
  - path: src/auth/jwt.py
    reason: "JWT utilities — security-critical, modify with care"
```

Also gather domain context from Hindsight:

```python
PROJECT_BANK = os.environ.get("CLAUDE_PROJECT_BANK", "claude-harness-setup")
domain_context = mcp__hindsight__reflect(
    query=f"Architecture patterns, prior Business Specs (BS), and design decisions for {initiative_domain}",
    budget="mid",
    bank_id=PROJECT_BANK
)
```

Using RepoMap context and Hindsight context, write the Business Spec (BS) to `docs/specs/business/PRD-{ID}.md` in the impl repo (historical specs remain in `docs/prds/`). The BS must include:
- YAML frontmatter with `prd_id`, `title`, `status`, `created`
- Goals section (maps to journey tests)
- Epic breakdown with acceptance criteria per epic
- Technical approach (informed by RepoMap delta analysis — what's `new` vs `existing` vs `modified`)

#### Injecting RepoMap Context into Technical Spec (TS) Creation

When delegating Technical Spec (TS) creation to a `solution-design-architect`, inject the RepoMap YAML directly into the prompt. This ensures the TS references actual file paths, uses real interface signatures, and respects protected files:

```python
# Generate RepoMap context (capture output as string)
context_yaml = Bash(
    f"cobuilder repomap context --name {repo_name} --prd {prd_id} --format yaml"
)

# Inject into solution-design-architect prompt
Task(
    subagent_type="solution-design-architect",
    prompt=f"""
    Create a Technical Spec (TS) for Epic {epic_num} of {prd_id}.

    ## Business Spec (BS) Reference
    Read: {prd_path}

    ## Codebase Context (RepoMap — read carefully before designing)
    ```yaml
    {context_yaml}
    ```

    Use this context to:
    - Reference EXISTING modules by their actual file paths
    - Scope MODIFIED modules to specific changes needed
    - Design NEW modules with suggested structure from RepoMap
    - Respect protected_files — do not include them in File Scope unless the BS requires changes
    - Use key_interfaces for accurate API contracts in your design
    """
)
```

> **Note on `--format yaml`**: This is the default format and produces structured YAML with module info, dependency graph, and key interfaces. Use `--format yaml` (or omit the flag) when reviewing context yourself or when the output is consumed by another agent or for LLM injection.

### Step 0.2: Create DOT Pipeline (MANDATORY — Do Not Skip)

> **Anti-pattern**: Skipping this step due to "cognitive momentum" from pre-CoBuilder sessions. The pipeline is REQUIRED for initiative tracking, orchestrator dispatch, and checkpoint/validation workflows. Without it, System 3 loses graph-driven execution and falls back to ad-hoc spawning.

Create the task tracking and pipeline infrastructure:

```bash
# 1. Create beads for each epic and task (include PRD ID in titles)
bd create --title="PRD-{ID}: Epic 1 — {name}" --type=epic --priority=2
bd create --title="PRD-{ID}: Task 1.1 — {name}" --type=task --priority=2
bd dep add <task-bead> <epic-bead>  # Task belongs to epic

# 2. Generate pipeline DOT file using CoBuilder
#    NOTE: This auto-initializes RepoMap if no baseline exists (~2-3 min).
#    Do NOT run `cobuilder repomap init` manually first.
cobuilder pipeline create \
    --sd docs/prds/SD-{ID}.md \
    --repo <repo-name> \
    --prd PRD-{ID} \
    --target-dir /path/to/impl-repo \
    --output /path/to/impl-repo/.pipelines/pipelines/${INITIATIVE}.dot

# 3. Validate the pipeline
cobuilder pipeline validate /path/to/impl-repo/.pipelines/pipelines/${INITIATIVE}.dot

# 4. Review status
cobuilder pipeline status /path/to/impl-repo/.pipelines/pipelines/${INITIATIVE}.dot --summary

# 5. Verify research → refine → codergen chains (MANDATORY)
PIPELINE=/path/to/impl-repo/.pipelines/pipelines/${INITIATIVE}.dot
cobuilder pipeline status ${PIPELINE} --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
nodes = data.get('nodes', [])
edges = data.get('edges', [])

codergen = [n for n in nodes if n.get('handler') == 'codergen']
research = {n['node_id'] for n in nodes if n.get('handler') == 'research'}
refine = {n['node_id'] for n in nodes if n.get('handler') == 'refine'}

# Build edge lookup: dst -> set of srcs
incoming = {}
for e in edges:
    incoming.setdefault(e['dst'], set()).add(e['src'])

issues = []
for cg in codergen:
    cg_id = cg['node_id']
    cg_preds = incoming.get(cg_id, set())
    refine_preds = cg_preds & refine
    if not refine_preds:
        issues.append(f'  {cg_id}: no refine predecessor (needs research -> refine -> codergen chain)')
        continue
    for rp in refine_preds:
        rp_preds = incoming.get(rp, set())
        if not (rp_preds & research):
            issues.append(f'  {cg_id}: refine node {rp} has no research predecessor')

if issues:
    print('FAILED: Missing research -> refine -> codergen chains:', file=sys.stderr)
    for i in issues:
        print(i, file=sys.stderr)
    sys.exit(1)
else:
    print(f'OK: All {len(codergen)} codergen nodes have research -> refine predecessors')
"
```

**MANDATORY**: Every `codergen` node in the pipeline MUST be preceded by a `research → refine` chain. This was introduced in v0.4.1 — research nodes validate framework patterns via Context7/Perplexity, refine nodes rewrite the TS with findings as first-class content. Bare codergen nodes risk implementing against outdated API patterns. If step 5 fails, add the missing research/refine nodes via `cobuilder pipeline node-add` and `cobuilder pipeline edge-add` before proceeding to Checkpoint A.

The `cobuilder pipeline create` command performs 7 steps automatically:
1. Checks/auto-creates RepoMap baseline (`ensure_baseline`)
2. Collects MODIFIED/NEW nodes from RepoMap
3. Filters by SD relevance
4. Parses via TaskMaster (unless `--skip-taskmaster`)
5. Cross-references beads
6. Enriches with LLM analysis (unless `--skip-enrichment`)
7. Generates the DOT file

**Do NOT build pipelines manually** with `node-add` / `edge-add` commands. Use `cobuilder pipeline create` which produces a properly structured pipeline from your SD + RepoMap context.

**If validation fails**: Load [references/dot-pipeline-creation.md](dot-pipeline-creation.md) for correct node shapes, required attributes per handler, edge rules, and cluster topology constraints. Common errors include wrong shapes (`house`/`octagon` instead of `Mdiamond`/`Msquare`), missing required attributes on codergen nodes (`bead_id`, `worker_type`, `sd_path`), and missing `wait.cobuilder → wait.human` chains after codergen nodes.

### Checkpoint A: PRD & Pipeline Review

Before proceeding to Task Master parsing, pause and present the user with a summary of what Phase 0 has produced so far. This is the last opportunity to adjust Business Spec (BS) scope or pipeline structure before the task hierarchy is locked in.

**Gather summary data**:

```bash
# Pipeline summary
cobuilder pipeline status ${PIPELINE} --summary --json

# Count epics and goals in PRD
EPIC_COUNT=$(grep -c "^## Epic" ${IMPL_REPO}/docs/prds/PRD-${ID}.md || echo 0)
GOAL_COUNT=$(grep -c "^## Goal\|^### Goal" ${IMPL_REPO}/docs/prds/PRD-${ID}.md || echo 0)
SD_COUNT=$(ls ${IMPL_REPO}/docs/prds/SD-*.md 2>/dev/null | wc -l | tr -d ' ')
```

**Present to user via AskUserQuestion**:

Compose a summary message that includes:
- BS title, goal count, and epic count
- Per-epic: title, Technical Spec (TS) file path, number of acceptance criteria
- Pipeline summary: total nodes (research/refine/codergen breakdown), edge count, chain validation status
- Estimated implementation scope (node count as proxy for effort)

Then call `AskUserQuestion` with these options:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | Continue to Task Master (Recommended) | Business Spec (BS) scope and pipeline look correct — proceed to parse BS into tasks and sync to beads |
| 2 | Adjust BS scope | I want to modify epics, acceptance criteria, or technology choices before proceeding |
| 3 | Regenerate pipeline | Pipeline structure needs changes — re-run `cobuilder pipeline create` with different parameters |
| 4 | Review files first | Show me the file paths so I can review the Business Spec (BS) and Technical Specs (TS) manually before deciding |

**Response handling**:

| User Choice | Guardian Action |
|-------------|-----------------|
| Continue to Task Master | Proceed to Step 0.3 |
| Adjust BS scope | Wait for user edits or apply specified changes to the BS, then re-run Step 0.2 (pipeline creation + chain validation) and present Checkpoint A again |
| Regenerate pipeline | Re-run `cobuilder pipeline create` with user-specified adjustments, re-validate chains, and present Checkpoint A again |
| Review files first | List all relevant file paths (BS, Technical Specs (TS), pipeline DOT file) so the user can inspect them, then re-present Checkpoint A |

### Step 0.3: Parse PRD with Task Master

Use Task Master to decompose the Business Spec (BS) into structured tasks, then sync to beads:

```python
# Parse PRD into tasks
mcp__task-master-ai__parse_prd(
    input="docs/prds/PRD-{ID}.md",
    project_root="/path/to/impl-repo"
)

# Verify tasks were created
mcp__task-master-ai__get_tasks(project_root="/path/to/impl-repo")
```

```bash
# Sync Task Master output into beads
node /path/to/config-repo/.claude/scripts/sync-taskmaster-to-features.js \
    --project-root /path/to/impl-repo

# Verify beads are populated and DOT pipeline nodes have real bead_ids
bd list --status=open
$CLI status pipeline.dot --json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for n in data.get('nodes', []):
    bid = n.get('bead_id', 'MISSING')
    print(f\"{n['node_id']}: bead_id={bid}\")
"
```

**If bead_ids are missing in DOT nodes**, retrofit them:
```bash
$CLI node modify pipeline.dot <node_id> --set bead_id=<real-bead-id>
$CLI checkpoint save pipeline.dot
```

### RepoMap Context Injection (Phase 0 Step 2.5)

Before delegating Technical Spec (TS) creation to solution-design-architect, generate codebase context:

```bash
# Generate structured YAML context for the repo
cobuilder repomap context --name <repo_name> --prd <prd_id>
```

Then inject into the solution-design-architect prompt:

```python
context_yaml = Bash("cobuilder repomap context --name {repo_name} --prd {prd_id}")

Task(
    subagent_type="solution-design-architect",
    prompt=f"""
    Create a Technical Spec (TS) for Epic {epic_num} of {prd_id}.

    ## Business Spec (BS) Reference
    Read: {prd_path}

    ## Codebase Context (RepoMap — read carefully before designing)
    ```yaml
    {context_yaml}
    ```

    Use this context to:
    - Reference EXISTING modules by their actual file paths
    - Scope MODIFIED modules to specific changes needed
    - Design NEW modules with suggested structure from RepoMap
    - Respect protected_files — do not include them in File Scope unless the BS requires changes
    - Use key_interfaces for accurate API contracts in your design
    """
)
```

**When to use**: Any initiative targeting a codebase registered with `cobuilder repomap init`.
**Skip when**: First-time setup (no baseline yet), or purely config/docs changes.

### Step 0.4: Design Challenge Protocol (MANDATORY)

Before proceeding to Phase 1, the guardian MUST challenge its own Business Spec (BS) design by spawning a solution-architect agent that independently evaluates the design.

**Why this matters**: The guardian wrote the BS — it cannot objectively evaluate its own design. Independent challenge prevents proceeding with flawed architecture, missed edge cases, or technology choices that seem reasonable but have known pitfalls.

#### Launch Design Challenge Agent

```python
Task(
    subagent_type="solution-design-architect",
    description="Challenge PRD-{ID} design via parallel solutioning + research",
    prompt=f"""
    You are reviewing Business Spec PRD-{prd_id} as an independent design challenger.

    ## MANDATORY First Actions
    1. Skill("parallel-solutioning") with the prompt:
       "Review and challenge the Business Spec (BS) at docs/prds/PRD-{prd_id}.md.
       Identify architectural weaknesses, missing edge cases, scalability concerns,
       and alternative approaches."
       - This spawns 7 architects with diverse reasoning strategies
       - Each architect must identify weaknesses, alternatives, and risks

    2. Skill("research-first") for each major technology choice in the BS:
       - Validate framework versions and API compatibility
       - Check for deprecations or known issues
       - Cross-reference with context7 docs for current best practices
       - Validate integration patterns between chosen technologies

    ## Your Deliverable
    Write a design-challenge report to {config_repo}/acceptance-tests/PRD-{prd_id}/design-challenge.md:

    ### Report Structure
    - **Consensus Concerns**: Issues flagged by 5+ of the 7 architects
    - **Technology Validation**: research-first findings per technology choice
    - **Recommended PRD Amendments**: Specific changes with rationale
    - **Risk Matrix**: severity (critical/high/medium/low) x likelihood
    - **VERDICT**: PROCEED / AMEND / REDESIGN

    Read the PRD at: {impl_repo}/docs/prds/PRD-{prd_id}.md
    Store the report at: {config_repo}/acceptance-tests/PRD-{prd_id}/design-challenge.md
    """
)
```

#### Handling Challenge Results

| Verdict | Guardian Action | User Checkpoint |
|---------|----------------|-----------------|
| PROCEED | Log result to Hindsight, continue to Phase 1 | Confirm via Checkpoint B |
| AMEND | Apply changes, re-run 0.3 | Select which amendments to accept |
| REDESIGN | Revisit Step 0.1 | Confirm restart or narrow scope |

**Anti-pattern**: Ignoring AMEND/REDESIGN verdicts because "it's probably fine" or "we already created beads." The cost of fixing a flawed design after implementation is 10x the cost of fixing the BS.

### Checkpoint B: Design Challenge Review

After the design challenge completes and the verdict is determined, pause and present the results to the user before proceeding. The user should see the architect consensus and confirm the path forward.

**Present to user via AskUserQuestion** — use the variant matching the verdict:

#### Variant: PROCEED Verdict

Compose a summary that includes:
- Design challenge verdict: PROCEED
- Key consensus items from the architect review (top 3 concerns, even if minor)
- Technology validation results (any deprecation warnings or version issues)
- Confirmation that all 7 architects found no blocking issues

Then call `AskUserQuestion` with these options:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | Proceed to Phase 1 (Recommended) | Design challenge passed — continue to acceptance test creation |
| 2 | Address concerns first | I want to address the minor concerns raised before proceeding |
| 3 | Run additional research | I want deeper investigation on a specific technology choice |

**Response handling**:

| User Choice | Guardian Action |
|-------------|-----------------|
| Proceed to Phase 1 | Log PROCEED to Hindsight, continue to Phase 1 |
| Address concerns first | Wait for user to specify which concerns to address, apply changes, re-run Step 0.4 |
| Run additional research | Spawn `research-first` for the specified technology, present findings, then re-present Checkpoint B |

#### Variant: AMEND Verdict

Compose a summary that includes:
- Design challenge verdict: AMEND
- Recommended amendments (list each with rationale)
- Risk matrix highlights (critical/high items only)
- Impact on existing pipeline and task structure

Then call `AskUserQuestion` with these options:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | Accept all amendments (Recommended) | Apply all recommended changes to PRD, re-run Task Master parsing |
| 2 | Accept some amendments | I want to select which amendments to apply |
| 3 | Override and proceed | I understand the risks — proceed without amendments |
| 4 | Redesign from scratch | The amendments reveal deeper issues — restart Phase 0 |

**Response handling**:

| User Choice | Guardian Action |
|-------------|-----------------|
| Accept all amendments | Apply all changes to PRD, re-run Step 0.3, update beads and pipeline |
| Accept some amendments | Wait for user to specify which amendments, apply selected changes, re-run Step 0.3 |
| Override and proceed | Log override decision to Hindsight with rationale, continue to Phase 1 |
| Redesign from scratch | Return to Step 0.1 with architect feedback as input |

#### Variant: REDESIGN Verdict

Compose a summary that includes:
- Design challenge verdict: REDESIGN
- Critical issues that necessitate redesign (from consensus concerns)
- Architect recommendations for alternative approaches
- Estimated impact of redesign vs proceeding with current design

Then call `AskUserQuestion` with these options:

| Option | Label | Description |
|--------|-------|-------------|
| 1 | Restart Phase 0 (Recommended) | Return to Step 0.1 with architect feedback as input for a new PRD |
| 2 | Narrow scope | Reduce the initiative scope to avoid the critical issues, then re-design |
| 3 | Override and proceed | I understand the significant risks — proceed with the current design |

**Response handling**:

| User Choice | Guardian Action |
|-------------|-----------------|
| Restart Phase 0 | Return to Step 0.1 with architect feedback as context, create new Business Spec (BS) |
| Narrow scope | Work with user to define reduced scope, then restart from Step 0.1 with narrower BS |
| Override and proceed | Log override to Hindsight with explicit risk acknowledgment, continue to Phase 1 |

#### Evidence Storage

```
acceptance-tests/PRD-{ID}/
├── design-challenge.md         # Architect consensus report
└── research-validation.md      # research-first findings (if separate)
```

#### Promise Integration

```bash
# After Phase 0 completes successfully
cs-promise --meet <id> --ac-id AC-0 \
    --evidence "PRD written, pipeline created with N nodes, design challenge verdict: PROCEED" \
    --type manual
```

---

### Phase 0 → Phase 1 Transition (GATE G1 — MANDATORY)

**Phase 0 is now complete. Before proceeding to Phase 2 (orchestrator dispatch), Phase 1 (acceptance tests) MUST run.**

This is the most commonly skipped gate. Cognitive momentum from "write a PRD and SD" causes jumping directly to implementation. The user values correctness over speed.

**Mandatory actions before ANY SD writing or orchestrator dispatch:**

1. **Verify gate**: `python3 .claude/skills/cobuilder-guardian/scripts/verify-phase-gate.py --prd PRD-{ID} --gate G1`
2. **If gate fails**: Run `Skill("acceptance-test-writer")` with the PRD
3. **If gate passes**: Proceed to Phase 2

**Inject phase checklist into TodoWrite** (if not already done):

```
TodoWrite([
  {"content": "Phase 0: PRD + pipeline + design challenge", "status": "completed"},
  {"content": "GATE G1: Acceptance tests exist", "status": "in_progress"},
  {"content": "Phase 1: Blind Gherkin acceptance tests", "status": "pending"},
  {"content": "Phase 2: Orchestrator/pipeline dispatch", "status": "pending"},
  ...
])
```

This makes the skip visible. If Phase 1 is deleted from the todo list, it's a conscious override — not a silent omission.

**If the user explicitly asks to skip Phase 1**: Log the override to Hindsight with the rationale, mark the gate as "SKIPPED (user override)" in the todo list, and proceed. But never skip silently.
