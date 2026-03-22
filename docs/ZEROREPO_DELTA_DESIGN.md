# ZeroRepo Delta Quality + Orchestrator Integration Design

**Date**: 2026-02-08
**Status**: Final
**Promise**: promise-2fe51a3b
**Branch**: rpg-zero-repo (worktree: trees/rpg-improve)

---

## Problem Statement

### Delta Classification Accuracy: 0%

When run against `my-org/my-project/` (3,037-node baseline), the delta report shows:

- **0 existing** nodes (should be many)
- **0 modified** nodes
- **33 new** nodes (all incorrectly classified)

### Root Cause: Two Structural Disconnects

```
1. NAMING MISMATCH
   LLM generates: "Configuration Service", "Email Service", "Token Service"
   Baseline has:  "eddy_validate", "live_form_filler", "voice_agent", "database"
   → converter.py name matching fails → everything marked NEW

2. CLASSIFICATION GAP
   Parser prompt says: "indicate whether existing, modified, or new"
   Component model has: NO delta_status field
   → LLM classification is never captured in structured output
```

### Missing Integration Point

The orchestrator-multiagent skill's Phase 1 (Planning) goes from "PRD written" directly to "Task Master parse". There is no step that analyzes the **actual codebase** to determine where changes should happen. Workers receive task descriptions but no map of existing code.

---

## Part 1: LLM-Based Delta Classification

### Core Change

Move delta classification INTO the LLM response. The LLM already sees the baseline context — it should explicitly map each component to baseline nodes in structured JSON.

### Current Flow (Broken)

```
Spec Parser (LLM) → Components without status
                         ↓
                    Converter (name matching) → delta_status ← FAILS
```

### Proposed Flow

```
Spec Parser (LLM) → Components WITH delta_status + baseline_match_name
                         ↓
                    Converter (trusts LLM classification) → delta_status ← WORKS
```

### Schema Changes

#### 1. Add delta fields to `Component` in `spec_parser/models.py`

```python
class DeltaClassification(str, Enum):
    EXISTING = "existing"   # Maps to existing baseline node, unchanged
    MODIFIED = "modified"   # Maps to existing baseline node, changed
    NEW = "new"             # No corresponding baseline node

class Component(BaseModel):
    # ... existing fields ...

    delta_status: Optional[DeltaClassification] = Field(
        default=None,
        description="Delta status relative to baseline (only when baseline provided).",
    )
    baseline_match_name: Optional[str] = Field(
        default=None,
        description="Exact name of matched baseline node. Required for existing/modified.",
    )
    change_summary: Optional[str] = Field(
        default=None,
        description="What changed, for modified components only.",
    )
```

#### 2. Update `spec_parsing.jinja2` with conditional baseline section

```jinja2
{% if has_baseline %}
## Baseline-Aware Classification

The existing codebase structure is provided above. For EACH component, classify as:

- **"existing"**: Maps to a baseline module/component unchanged for this spec.
  Set `baseline_match_name` to the exact baseline node name.
- **"modified"**: Maps to a baseline module/component that needs changes.
  Set `baseline_match_name` + `change_summary`.
- **"new"**: No existing component covers this. Set `baseline_match_name` to null.

Rules:
1. Copy baseline node names EXACTLY (from the structure above)
2. Prefer mapping to existing components over creating new ones
3. Use the baseline name as the component name for existing/modified
4. Only classify "new" when genuinely no existing component applies

Updated component fields: name, description, component_type, technologies,
suggested_module, **delta_status**, **baseline_match_name**, **change_summary**
{% endif %}
```

#### 3. Update converter to prefer LLM classification

```python
def _tag_delta_status_from_llm(self, node, component, baseline):
    """Prefer LLM classification over name matching."""
    if component.delta_status is not None:
        node.metadata["delta_status"] = component.delta_status.value
        if component.baseline_match_name and baseline:
            bl_node = self._find_matching_baseline_node(
                component.baseline_match_name, baseline, level=node.level
            )
            if bl_node:
                node.metadata["baseline_node_id"] = str(bl_node.id)
                self._copy_baseline_enrichment(node, bl_node)
        if component.change_summary:
            node.metadata["change_summary"] = component.change_summary
        return

    # Fallback: name matching (when no baseline provided to parser)
    if baseline is not None:
        bl_node = self._find_matching_baseline_node(node.name, baseline, level=node.level)
        self._tag_delta_status(node, bl_node)
```

---

## Part 2: Integration into Orchestrator-Multiagent Skill

### The Key Insight

The RPG graph IS the codebase context. It tells the orchestrator and workers:

1. **WHERE in the code** to make changes (modified nodes → file paths, signatures)
2. **WHERE to add new code** (new nodes → suggested module paths)
3. **WHAT already exists** (existing nodes → full codebase map with relationships)
4. **HOW things connect** (edges → dependencies, hierarchy, data flow)

This replaces the current gap where workers receive abstract task descriptions without any codebase map.

### Where It Fits: Phase 1 Step 2.5

The orchestrator-multiagent SKILL.md Phase 1 currently goes:

```
Phase 1: Planning
  1. Create uber-epic in Beads
  2. Create PRD from design document
  ──── GAP: No codebase analysis ────
  3. Parse PRD with Task Master
  4. Analyze complexity
  5. Expand tasks
  6. Sync to Beads
  7. Generate acceptance tests
```

With zerorepo integration:

```
Phase 1: Planning
  1. Create uber-epic in Beads
  2. Create PRD from design document
  ──── NEW: ZeroRepo Analysis (Step 2.5) ────
  2.5a. Initialize baseline (if not exists)
  2.5b. Generate RPG delta from PRD + baseline
  2.5c. Read delta report → enrich PRD context
  ─────────────────────────────────────────────
  3. Parse PRD with Task Master (now with delta context)
  4. Analyze complexity (informed by existing/modified/new)
  5. Expand tasks (with file paths and change scopes)
  6. Sync to Beads
  7. Generate acceptance tests
```

### What the Delta Report Provides to Task Decomposition

| Delta Status | Task Implication | Worker Context |
|--------------|------------------|----------------|
| EXISTING | **Skip** — no task needed | "This component exists at `voice_agent/` and needs no changes" |
| MODIFIED | **Scoped task** — specific changes only | "Modify `eddy_validate/` to add form submission handler. See `change_summary`." |
| NEW | **Full implementation task** | "Create new `email_service/` module. See suggested interfaces." |

### Deliverables

Following skill-development best practices (imperative form, progressive disclosure, lean SKILL.md):

#### A. New reference file: `ZEROREPO.md`

Location: `.claude/skills/orchestrator-multiagent/ZEROREPO.md`

Contains:
- Full workflow for init → generate → interpret
- Delta report interpretation guide
- How to thread delta context into Task Master parsing
- How to include file paths in worker task assignments
- Troubleshooting (large baselines, timeout, naming issues)

~2,000-3,000 words (loaded only when orchestrator invokes zerorepo step).

#### B. Update to `SKILL.md` Phase 1 section

Add Step 2.5 (zerorepo analysis) between PRD creation and Task Master parsing:

```markdown
# 2.5. Codebase Analysis with ZeroRepo (Recommended)

For detailed workflow, see [ZEROREPO.md](ZEROREPO.md).

Run ZeroRepo to map the PRD against the existing codebase:

```bash
# Initialize baseline (once per project)
zerorepo init --project-path . --exclude node_modules,__pycache__,.git,trees,venv

# Generate delta report from PRD
LITELLM_REQUEST_TIMEOUT=1200 zerorepo generate \
  .taskmaster/docs/prd.md \
  --baseline .zerorepo/baseline-self.json \
  --model claude-sonnet-4-20250514

# Read the delta report
Read(".zerorepo/output/05-delta-report.md")
```

The delta report classifies components as EXISTING, MODIFIED, or NEW.
Use this to enrich task descriptions with file paths and change scopes.
```

#### C. Wrapper scripts

Location: `.claude/skills/orchestrator-multiagent/scripts/`

| Script | Purpose |
|--------|---------|
| `zerorepo-init.sh` | Initialize baseline with standard excludes |
| `zerorepo-generate.sh` | Run pipeline with timeout + model defaults |
| `zerorepo-update.sh` | Regenerate baseline after implementation (backup + log) |
| `zerorepo-delta-summary.sh` | Parse delta report into task-friendly format |

#### D. Update to `WORKFLOWS.md`

Add "Codebase-Aware Task Creation" section showing how delta report enriches worker task assignments with file paths and change scopes.

### Skill Development Checklist

Following the skill-development best practices:

- [x] **Understanding**: Concrete examples of zerorepo usage identified (init, generate, interpret)
- [x] **Planning**: Resources identified (ZEROREPO.md reference, wrapper scripts)
- [ ] **Structure**: Create reference file and scripts
- [ ] **SKILL.md**: Add Phase 1 Step 2.5 (lean, ~200 words in SKILL.md, detail in ZEROREPO.md)
- [ ] **Writing style**: Imperative/infinitive form throughout
- [ ] **Progressive disclosure**: SKILL.md references ZEROREPO.md for detail
- [ ] **Validation**: Test end-to-end orchestrator workflow with zerorepo step
- [ ] **Iteration**: Improve based on first real orchestrator session

---

## Part 2.5: Graph Lifecycle — Init, Generate, Update

### The Three-Operation Cycle

```
┌─────────────────────────────────────────────────────────────┐
│  1. INIT (once per project)                                  │
│     zerorepo init --project-path .                           │
│     → .zerorepo/baseline-self.json (codebase snapshot)       │
│                                                              │
│  2. GENERATE (per PRD, during Phase 1 planning)              │
│     zerorepo generate prd.md --baseline baseline-self.json   │
│     → Delta report: existing/modified/new classification     │
│     → Workers know WHERE to make changes                     │
│                                                              │
│  3. UPDATE (after implementation, before next initiative)     │
│     zerorepo update --project-path .                         │
│     → Regenerates baseline-self.json from current codebase   │
│     → Next PRD generate starts with accurate baseline        │
└─────────────────────────────────────────────────────────────┘
```

### When Each Operation Runs

| Operation | When | Triggered By | Phase |
|-----------|------|-------------|-------|
| `init` | First time zerorepo is set up in a project | Manual or orchestrator first run | Setup |
| `generate` | Before implementation of each PRD/initiative | Orchestrator Phase 1 Step 2.5 | Planning |
| `update` | After implementation completes | Orchestrator Phase 3 (post-validation) | Closing |

### Update Operation Details

`zerorepo update` is functionally equivalent to `zerorepo init` but:
- Preserves the `.zerorepo/` directory and history
- Creates a timestamped backup of the previous baseline
- Logs the delta between old and new baseline (nodes added/removed/renamed)
- Can be run incrementally (only re-walk changed directories) in future versions

```bash
# After Phase 3 validation passes:
zerorepo update --project-path . --exclude node_modules,__pycache__,.git,trees,venv

# This produces:
# .zerorepo/baseline-self.json          ← Updated to current codebase
# .zerorepo/baseline-self.prev.json     ← Previous baseline (backup)
# .zerorepo/update-log.md               ← What changed since last baseline
```

### Integration into Orchestrator Phases

```
Phase 0: Ideation → Design document
Phase 1: Planning
  Step 2.5a: zerorepo init (if no baseline) OR zerorepo update (if stale)
  Step 2.5b: zerorepo generate PRD + baseline → delta report
  Step 2.5c: Enrich task descriptions with delta context
  Steps 3-7: Task Master, Beads, acceptance tests
Phase 2: Execution → Workers implement (with file paths from delta)
Phase 3: Validation → 3-level testing
  Post-validation: zerorepo update → refresh baseline for next initiative
```

---

## Part 3: Implementation Plan (Sprint 3)

### Wave 1: Schema + Prompt Changes (no behavior change)

**Files**: `spec_parser/models.py`, `llm/templates/spec_parsing.jinja2`, `spec_parser/parser.py`

1. Add `DeltaClassification` enum and `delta_status`, `baseline_match_name`, `change_summary` to `Component`
2. Add conditional `{% if has_baseline %}` block to jinja2 template
3. Pass `has_baseline` flag from parser to template context
4. **Tests**: Backward compatibility (no baseline = fields are None)

### Wave 2: Converter Classification Logic

**Files**: `graph_construction/converter.py`, `graph_construction/builder.py`

1. Add `_tag_delta_status_from_llm()` method
2. Thread `Component` objects from spec → graph → converter (currently lost after partitioning)
3. Modify converter to prefer LLM classification, fall back to name matching
4. **Tests**: Unit tests with mock LLM-classified components

### Wave 3: End-to-End Validation

1. Run against my-project codebase with real LLM
2. Measure: existing/modified/new accuracy vs manual ground truth
3. **Target**: >70% classification accuracy (from current 0%)

### Wave 4: Orchestrator Integration

**Files**: orchestrator-multiagent skill (`SKILL.md`, `ZEROREPO.md`, `WORKFLOWS.md`, scripts)

1. Create `ZEROREPO.md` reference file (~2,500 words)
2. Add Step 2.5 to SKILL.md Phase 1 (~200 words, points to ZEROREPO.md)
3. Create wrapper scripts (`zerorepo-init.sh`, `zerorepo-generate.sh`)
4. Update WORKFLOWS.md with codebase-aware task creation pattern
5. **Test**: Full orchestrator session using zerorepo step

---

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| Existing nodes correctly classified | 0% | >70% |
| Modified nodes detected | 0 | >50% of actual modifications |
| New nodes precision | ~0% (everything is new) | >80% |
| End-to-end pipeline time | 2.5 min | <3 min (no regression) |
| SKILL.md addition | N/A | <200 words (lean) |
| ZEROREPO.md reference | N/A | 2,000-3,000 words (detail) |
| Worker tasks include file paths | Never | Always (for modified/existing) |

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| LLM hallucinates baseline matches | Validate `baseline_match_name` against actual baseline graph |
| Large baselines exceed context window | Summarize (top-level modules only, skip features) |
| LLM inconsistently classifies | Few-shot examples in prompt with correct classifications |
| Backward compatibility | All delta fields are Optional, default None |
| zerorepo not installed in project | Wrapper script checks and provides install instructions |
| Baseline stale after commits | Script warns if baseline older than latest commit |

---

## Architecture Summary

```
Orchestrator Phase 1 Workflow (After This Design)
═══════════════════════════════════════════════════

  PRD Document
      │
      ▼
  ┌─────────────────────────────────────────────┐
  │  STEP 2.5: ZeroRepo Analysis                │
  │                                              │
  │  zerorepo init → Baseline (codebase map)     │
  │  zerorepo generate PRD + Baseline            │
  │      │                                       │
  │      ▼                                       │
  │  Spec Parser (LLM):                          │
  │    "eddy_validate" → MODIFIED (add forms)    │
  │    "live_form_filler" → MODIFIED (mode switch)│
  │    "email_service" → NEW                     │
  │    "voice_agent" → EXISTING (no changes)     │
  │      │                                       │
  │      ▼                                       │
  │  Delta Report:                               │
  │    15 existing, 5 modified, 13 new           │
  │    File paths, change summaries, signatures  │
  └──────────────────┬──────────────────────────┘
                     │
                     ▼
  Task Master Parsing (enriched with delta context)
      │
      ▼
  Worker Tasks (with file paths + change scopes)
      │
      ▼
  Workers know EXACTLY where to make changes
```

---

*Finalized by System 3 Meta-Orchestrator*
*Promise: promise-2fe51a3b (in_progress)*
*Skill-development best practices applied: progressive disclosure, imperative form, lean SKILL.md*

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
