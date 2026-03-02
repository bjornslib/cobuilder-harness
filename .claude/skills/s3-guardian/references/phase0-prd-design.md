---
title: "Phase 0: PRD Design & Challenge"
status: active
type: reference
grade: authoritative
---

## Phase 0: PRD Design & Challenge

When the guardian is initiating a new initiative (rather than validating an existing one), it must first design the PRD, create the pipeline infrastructure, and challenge its own design before proceeding to acceptance test creation.

**Skip Phase 0 if**: A finalized PRD already exists at the implementation repo's `docs/prds/PRD-{ID}.md` and has been reviewed. Proceed directly to Phase 1.

### Step 0.1: PRD Authoring with CoBuilder RepoMap Context

Before writing the PRD, understand the current codebase structure using CoBuilder's RepoMap context command:

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
    query=f"Architecture patterns, prior PRDs, and design decisions for {initiative_domain}",
    budget="mid",
    bank_id=PROJECT_BANK
)
```

Using RepoMap context and Hindsight context, write the PRD to `docs/prds/PRD-{ID}.md` in the impl repo. The PRD must include:
- YAML frontmatter with `prd_id`, `title`, `status`, `created`
- Goals section (maps to journey tests)
- Epic breakdown with acceptance criteria per epic
- Technical approach (informed by RepoMap delta analysis — what's `new` vs `existing` vs `modified`)

#### Injecting RepoMap Context into SD Creation

When delegating SD creation to a `solution-design-architect`, inject the RepoMap YAML directly into the prompt. This ensures the SD references actual file paths, uses real interface signatures, and respects protected files:

```python
# Generate RepoMap context (capture output as string)
context_yaml = Bash(
    f"cobuilder repomap context --name {repo_name} --prd {prd_id} --format yaml"
)

# Inject into solution-design-architect prompt
Task(
    subagent_type="solution-design-architect",
    prompt=f"""
    Create a Solution Design for Epic {epic_num} of {prd_id}.

    ## PRD Reference
    Read: {prd_path}

    ## Codebase Context (RepoMap — read carefully before designing)
    ```yaml
    {context_yaml}
    ```

    Use this context to:
    - Reference EXISTING modules by their actual file paths
    - Scope MODIFIED modules to specific changes needed
    - Design NEW modules with suggested structure from RepoMap
    - Respect protected_files — do not include them in File Scope unless PRD requires changes
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
    --output /path/to/impl-repo/.claude/attractor/pipelines/${INITIATIVE}.dot

# 3. Validate the pipeline
cobuilder pipeline validate /path/to/impl-repo/.claude/attractor/pipelines/${INITIATIVE}.dot

# 4. Review status
cobuilder pipeline status /path/to/impl-repo/.claude/attractor/pipelines/${INITIATIVE}.dot --summary
```

The `cobuilder pipeline create` command performs 7 steps automatically:
1. Checks/auto-creates RepoMap baseline (`ensure_baseline`)
2. Collects MODIFIED/NEW nodes from RepoMap
3. Filters by SD relevance
4. Parses via TaskMaster (unless `--skip-taskmaster`)
5. Cross-references beads
6. Enriches with LLM analysis (unless `--skip-enrichment`)
7. Generates the DOT file

**Do NOT build pipelines manually** with `node-add` / `edge-add` commands. Use `cobuilder pipeline create` which produces a properly structured pipeline from your SD + RepoMap context.

### Step 0.3: Parse PRD with Task Master

Use Task Master to decompose the PRD into structured tasks, then sync to beads:

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

Before delegating SD creation to solution-design-architect, generate codebase context:

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
    Create a Solution Design for Epic {epic_num} of {prd_id}.

    ## PRD Reference
    Read: {prd_path}

    ## Codebase Context (RepoMap — read carefully before designing)
    ```yaml
    {context_yaml}
    ```

    Use this context to:
    - Reference EXISTING modules by their actual file paths
    - Scope MODIFIED modules to specific changes needed
    - Design NEW modules with suggested structure from RepoMap
    - Respect protected_files — do not include them in File Scope unless PRD requires changes
    - Use key_interfaces for accurate API contracts in your design
    """
)
```

**When to use**: Any initiative targeting a codebase registered with `cobuilder repomap init`.
**Skip when**: First-time setup (no baseline yet), or purely config/docs changes.

### Step 0.4: Design Challenge Protocol (MANDATORY)

Before proceeding to Phase 1, the guardian MUST challenge its own PRD design by spawning a solution-architect agent that independently evaluates the design.

**Why this matters**: The guardian wrote the PRD — it cannot objectively evaluate its own design. Independent challenge prevents proceeding with flawed architecture, missed edge cases, or technology choices that seem reasonable but have known pitfalls.

#### Launch Design Challenge Agent

```python
Task(
    subagent_type="solution-design-architect",
    description="Challenge PRD-{ID} design via parallel solutioning + research",
    prompt=f"""
    You are reviewing PRD-{prd_id} as an independent design challenger.

    ## MANDATORY First Actions
    1. Skill("parallel-solutioning") with the prompt:
       "Review and challenge the solution design in docs/prds/PRD-{prd_id}.md.
       Identify architectural weaknesses, missing edge cases, scalability concerns,
       and alternative approaches."
       - This spawns 7 architects with diverse reasoning strategies
       - Each architect must identify weaknesses, alternatives, and risks

    2. Skill("research-first") for each major technology choice in the PRD:
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

| Verdict | Guardian Action |
|---------|----------------|
| PROCEED | Log result to Hindsight, continue to Phase 1 |
| AMEND | Apply recommended changes to PRD, re-run Step 0.3 (Task Master re-parse), update beads |
| REDESIGN | Major rework needed — revisit Step 0.1 with architect feedback as input |

**Anti-pattern**: Ignoring AMEND/REDESIGN verdicts because "it's probably fine" or "we already created beads." The cost of fixing a flawed design after implementation is 10x the cost of fixing the PRD.

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
