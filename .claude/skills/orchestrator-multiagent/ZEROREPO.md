---
title: "Zerorepo"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# ZeroRepo: Codebase-Aware Orchestration

ZeroRepo provides a codebase context graph that maps PRD requirements against existing code. It classifies every component as EXISTING (already implemented), MODIFIED (needs changes), or NEW (must be created from scratch). This classification enables orchestrators to generate precise, scoped task descriptions rather than blind decompositions.

---

## Three-Operation Lifecycle

| Operation | Purpose | When to Run | Duration |
|-----------|---------|-------------|----------|
| **init** | Generate baseline graph of current codebase | Once per project (or after major implementation) | ~5s |
| **generate** | Analyze PRD against baseline, produce delta report | Once per PRD during Phase 1 planning | ~2.5 min |
| **update** | Regenerate baseline after implementation completes | End of Phase 2, before next initiative | ~5s |

> **Prerequisites**: Python 3.12+, `zerorepo` installed (`pip install -e .` from source), LLM API key set, `LITELLM_REQUEST_TIMEOUT=1200` for generate operations.

---

## Operation 1: Initialize Baseline

Generate a structural snapshot of the existing codebase. This baseline serves as the reference point for all delta comparisons.

```bash
.claude/skills/orchestrator-multiagent/scripts/zerorepo-init.sh
```

**Arguments**:

| Argument | Default | Description |
|----------|---------|-------------|
| `--project-path` | `.` | Root of the codebase to scan |
| `--exclude` | (none) | Comma-separated directory patterns to skip |
| `--output` | `.zerorepo/baseline.json` | Output path for baseline file |

**Output**: `.zerorepo/baseline.json` -- a JSON graph of modules, classes, functions, and their relationships.

**Standard exclude patterns**: `node_modules,__pycache__,.git,trees,venv,.zerorepo`

**When to re-run**: After completing a major implementation phase. The baseline reflects the codebase at a point in time; stale baselines produce inaccurate delta reports.

---

## Operation 2: Generate Delta Report

Analyze a PRD (or design spec) against the baseline to classify every referenced component.

```bash
.claude/skills/orchestrator-multiagent/scripts/zerorepo-generate.sh \
  docs/prds/prd.md
```

**Arguments**:

| Argument | Default | Description |
|----------|---------|-------------|
| `<spec-file>` | (required) | Path to PRD or design specification |
| `--baseline` | `.zerorepo/baseline.json` | Path to baseline graph |
| `--model` | `claude-sonnet-4-20250514` | LLM model for analysis |
| `--output` | `.zerorepo/output` | Output directory for pipeline artifacts |

**Pipeline stages** (run sequentially):
1. Parse spec into `RepositorySpec`
2. Build `FunctionalityGraph`
3. Convert to `RPGGraph`
4. Enrich with semantic encoders
5. Generate delta report (when baseline provided)

**Primary output**: `.zerorepo/output/05-delta-report.md`

---

## Operation 3: Update Baseline

After completing an implementation phase, regenerate the baseline to reflect new code.

```bash
.claude/skills/orchestrator-multiagent/scripts/zerorepo-update.sh
```

The wrapper script backs up the current baseline to `baseline.prev.json` before regenerating, preserving a rollback point.

---

## Delta Report Interpretation

The delta report (`05-delta-report.md`) classifies each component with one of three statuses:

### Classification Table

| Status | Meaning | Task Implication |
|--------|---------|------------------|
| **EXISTING** | Component already implemented in codebase | Skip -- no task needed. Reference in worker context as "already exists at `<path>`" |
| **MODIFIED** | Component exists but needs changes | Create scoped modification task. Include current file path and specific changes needed |
| **NEW** | Component does not exist in codebase | Create full implementation task. Include suggested module path and interfaces |

### Reading the Report

The delta report contains:
- **Module-level classifications**: Each PRD-referenced module marked as EXISTING/MODIFIED/NEW
- **Change summaries**: For MODIFIED components, a description of what needs to change
- **Suggested interfaces**: For NEW components, proposed structure based on PRD requirements
- **File path mappings**: Existing file locations for EXISTING and MODIFIED components

### Example Delta Excerpt

```markdown
## voice_agent/ [EXISTING]
No changes required. Core voice agent pipeline is fully implemented.

## eddy_validate/ [MODIFIED]
Change: Add multi-form validation handler for new university contact types.
Files: eddy_validate/app.py, eddy_validate/validators.py

## email_service/ [NEW]
Create email notification service for validation results.
Suggested structure: email_service/__init__.py, email_service/sender.py, email_service/templates/
```

---

## Threading Delta Context into Task Master

After generating the delta report, use the classifications to enrich PRD content before parsing with Task Master. This produces better task decompositions because Task Master understands what already exists.

### Workflow

```
1. Generate delta report (Operation 2)
   ↓
2. Read 05-delta-report.md
   ↓
3. Annotate PRD or create enriched design doc
   - Mark EXISTING components: "Already implemented, reference only"
   - Mark MODIFIED components: "Modify existing <path> to add <change>"
   - Mark NEW components: "Create new module at <suggested-path>"
   ↓
4. Parse enriched PRD with Task Master
   task-master parse-prd docs/prds/prd.md --research --append
   ↓
5. Sync to Beads (standard workflow)
```

### Enriching Worker Task Assignments

Include delta context in TaskCreate descriptions to give workers precise scope:

```python
# Without ZeroRepo (vague scope)
TaskCreate(
    subject="Implement email notifications",
    description="""
    Add email notification support for validation results.
    Files: TBD
    """,
    activeForm="Implementing email notifications"
)

# With ZeroRepo (precise scope)
TaskCreate(
    subject="Implement email notifications",
    description="""
    ## Task: Email notification service [NEW]

    **Delta Status**: NEW -- no existing code for this component.

    **Create**:
    - email_service/__init__.py
    - email_service/sender.py (SMTP integration)
    - email_service/templates/ (Jinja2 templates)

    **Reference** (EXISTING -- do not modify):
    - eddy_validate/app.py (call email_service after validation)

    **Acceptance Criteria**:
    - Sends email on validation completion
    - Uses Jinja2 templates for formatting
    - Configurable SMTP settings via environment variables
    """,
    activeForm="Implementing email notifications"
)
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Init slow / large baseline | Scanning excluded dirs | Add patterns to `--exclude`: `node_modules,dist,build,.next,venv` |
| LLM timeout during generate | Default timeout too short | Set `LITELLM_REQUEST_TIMEOUT=1200` (or higher for large PRDs) |
| Most components show as NEW | LLM names don't match codebase names | Manual review of delta report (~2-3 min). Reclassify obvious mismatches |
| Baseline file not found | Init not run yet | Run `zerorepo init` first |
| Output dir already exists | Previous run artifacts | Pipeline overwrites by default, or use `--output .zerorepo/output-v2` |

---

## Pipeline Runner Script

The wrapper scripts delegate to `scripts/zerorepo-run-pipeline.py`. For direct runner usage, parameter reference, and timeout diagnostics, run `python scripts/zerorepo-run-pipeline.py --help`.

---

## Definition Pipeline (Single Command Workflow)

A single command chains the complete definition pipeline from PRD to executable .dot graph. This is Stage 1 of PRD-S3-DOT-LIFECYCLE-001.

### Usage

```bash
.claude/skills/orchestrator-multiagent/scripts/zerorepo-pipeline.sh \
  --prd docs/prds/PRD-XXX.md --format attractor
```

### Pipeline Steps

| Step | Action | Tool |
|------|--------|------|
| 1 | Initialize baseline (if missing) | `zerorepo init` |
| 2 | Generate delta + export .dot | `zerorepo generate --format attractor-pipeline` |
| 3 | Validate structure | `attractor validate` (automatic in step 2) |
| 4 | Copy to pipelines directory | `.pipelines/pipelines/<PRD-ID>.dot` |
| 5 | Cross-reference with beads | `attractor annotate` |
| 6 | Create completion promise | `attractor init-promise --execute` |
| 7 | Save checkpoint | `attractor checkpoint save` |
| 8 | Print summary report | Node counts, worker distribution |

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--prd <path>` | (required) | Path to PRD markdown file |
| `--format <fmt>` | `attractor` | Output format |
| `--baseline <path>` | `.zerorepo/baseline.json` | Path to baseline JSON |
| `--model <model>` | `claude-sonnet-4-5-20250929` | LLM model for analysis |
| `--output-dir <dir>` | `.zerorepo/output` | ZeroRepo output directory |
| `--skip-annotate` | — | Skip beads cross-reference step |
| `--skip-promise` | — | Skip completion promise creation |
| `--dry-run` | — | Print commands without executing |

### Output Paths

| Artifact | Path |
|----------|------|
| Pipeline DOT | `.pipelines/pipelines/<PRD-ID>.dot` |
| Checkpoint | `.pipelines/checkpoints/<PRD-ID>-definition.json` |
| ZeroRepo output | `.zerorepo/output/` (intermediate artifacts) |

### Example

```bash
# Full pipeline for a lifecycle PRD
zerorepo-pipeline.sh --prd docs/prds/PRD-S3-DOT-LIFECYCLE-001.md

# Dry-run to preview steps
zerorepo-pipeline.sh --prd docs/prds/PRD-S3-DOT-LIFECYCLE-001.md --dry-run

# Skip beads annotation (no beads DB available)
zerorepo-pipeline.sh --prd docs/prds/PRD-S3-DOT-LIFECYCLE-001.md --skip-annotate --skip-promise
```

---

## Enriching Beads with RPG Graph Context

After creating beads via Task Master sync, use the RPG graph (04-rpg.json) to inject precise technical context into each bead's design field. This transforms generic task descriptions into implementation-ready specifications.

### Pipeline Output Files Reference

| File | Content | Use In Orchestration |
|------|---------|---------------------|
| `01-spec.json` | LLM-parsed spec with components, features, technical requirements | **PRD validation** -- compare against PRD to surface missing requirements, unstated dependencies, and missing API contracts |
| `03-graph.json` | FunctionalityGraph: modules, features, dependency ordering | **PRD validation** -- verify module boundaries map 1:1 to PRD epics, check dependency ordering is correct |
| `04-rpg.json` | Full RPGGraph: nodes with folder/file paths, interfaces, signatures, docstrings | **Bead enrichment** -- extract per-component file paths, interface signatures, and technology stack for worker context |
| `05-delta-report.md` | Human-readable delta summary + implementation order | **Task scoping** -- use NEW vs MODIFIED classification to determine task scope and existing file references |

### Workflow

```
1. Generate delta report (Operation 2)
   ↓
2. Validate PRD against 01-spec.json + 03-graph.json
   - Verify modules map 1:1 to PRD epics
   - Surface missing requirements, unstated dependencies
   - Enrich PRD with identified gaps
   ↓
3. Parse enriched PRD with Task Master
   task-master parse-prd docs/prds/prd.md --research --append
   ↓
4. Sync to Beads (standard workflow from SKILL.md)
   node scripts/sync-taskmaster-to-beads.js --uber-epic=<epic-id> ...
   ↓
5. Enrich beads with RPG graph context (NEW STEP)
   - Read 04-rpg.json nodes
   - For each bead, update --design with delta, files, interfaces
   ↓
6. Review and commit
```

### Bead Enrichment Pattern

For each bead created by the sync script, update its design field with context extracted from the corresponding RPG graph nodes:

```bash
bd update <bead-id> --design "
Delta: NEW | MODIFIED | EXISTING
Epic: <epic-name>
TM-ID: <task-master-id>
Files:
- path/to/file.py (NEW | MODIFIED - <change description>)
- path/to/other.py (EXISTING - reference only)
Components: ComponentName1, ComponentName2
Technologies: Python, FastAPI, PostgreSQL, etc.
Interface:
  async def method_name(param: Type) -> ReturnType
  class ModelName(BaseModel): field1, field2, ...
Dependencies: blocks <bead-id> | blocked by <bead-id> | None
"
```

### Real Example (from Work History Phase 1)

```bash
bd update zenagent-irpn --design "
Delta: NEW + MODIFIED
Epic: 1.3 - SendGrid Email Templates (GAP 7)
TM-ID: 175
Files:
- agencheck-support-agent/utils/sendgrid_client.py (MODIFIED - extend with Dynamic Templates)
- agencheck-support-agent/templates/verification_request.html (NEW)
Components: SendGridTemplateIntegration, EmailTemplateHTML, SendGridClientExtension
Technologies: SendGrid, Python, HTML, CSS
Interface:
  async def send_verification_email(verifier_email: str, token: str, candidate_name: str, company_name: str) -> None
  Handlebars fields: {{candidate_name}}, {{company_name}}, {{verification_url}}, {{verifier_name}}, {{expiry_days}}
  Webhook: /api/v1/sendgrid/webhook for delivery/open/click tracking
CAN-SPAM: Unsubscribe link required
Dependencies: None (can start immediately, independent of other epics)
"
```

---

## Integration with Orchestrator Phases

| Phase | ZeroRepo Role |
|-------|---------------|
| **Phase 0: Ideation** | Not used -- focus on design and research |
| **Phase 1: Planning (Step 2.5a)** | Run `zerorepo-pipeline.sh --prd <prd>` (single command). Validates PRD against 01-spec.json + 03-graph.json, exports .dot graph, creates completion promise and checkpoint |
| **Phase 1: Planning (Step 2.5b)** | After Task Master sync, enrich beads with 04-rpg.json context (file paths, interfaces, delta status) |
| **Phase 2: Execution** | Workers reference enriched bead design fields for precise implementation scope |
| **Phase 3: Validation** | Not directly used -- validation focuses on test results |
| **Post-initiative** | Run update to refresh baseline for next initiative |

---

**Reference Version**: 2.2
**Created**: 2026-02-08
**CLI Source**: `src/zerorepo/cli/` (in trees/rpg-improve worktree)
