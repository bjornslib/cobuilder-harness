---
name: s3-guardian
description: This skill should be used when System 3 needs to act as an independent guardian angel — designing PRDs with CoBuilder RepoMap context injection, challenging designs via parallel solutioning, spawning orchestrators in tmux, creating blind Gherkin acceptance tests and executable browser test scripts from PRDs, monitoring orchestrator progress, independently validating claims against acceptance criteria using gradient confidence scoring (0.0-1.0), and setting session promises. Use when asked to "spawn and monitor an orchestrator", "create acceptance tests for a PRD", "validate orchestrator claims", "act as guardian angel", "independently verify implementation work", or "design and challenge a PRD".
version: 0.1.0
title: "S3 Guardian"
status: active
---

# S3 Guardian — Independent Validation Pattern

The guardian angel pattern provides independent, blind validation of System 3 meta-orchestrator work. A guardian session creates acceptance tests from PRDs, stores them outside the implementation repo where meta-orchestrators cannot see them, spawns and monitors S3 meta-orchestrators in tmux, and independently validates claims against a gradient confidence rubric.

```
Guardian (this session, config repo)
    |
    |-- Designs PRDs with CoBuilder RepoMap context (Phase 0)
    |-- Challenges own designs via parallel-solutioning + research-first (Phase 0)
    |-- Creates blind Gherkin acceptance tests (stored here, NOT in impl repo)
    |-- Generates executable browser test scripts for UX prototypes
    |-- Dispatches via DOT pipeline (two modes):
    |       |
    |       +-- SDK mode: launch_guardian.py → guardian → runner → orchestrator (all headless)
    |       +-- tmux mode: Spawns Orchestrators in tmux (one per epic/DOT node)
    |       |
    |       +-- Research nodes run BEFORE codergen (validate SD via Context7/Perplexity)
    |       +-- Workers (native Agent Teams, spawned by orchestrator)
    |
    |-- Monitors orchestrator progress (SDK: poll DOT state; tmux: capture-pane)
    |-- Independently validates claims against rubric
    |-- Delivers verdict with gradient confidence scores
```

**Key Innovation**: Acceptance tests live in `claude-harness-setup/acceptance-tests/PRD-{ID}/`, NOT in the implementation repository. Meta-orchestrators and their workers never see the rubric. This enables truly independent validation — the guardian reads actual code and scores it against criteria the implementers did not have access to.

---

## Guardian Disposition: Skeptical Curiosity

The guardian operates with a specific mindset that distinguishes it from passive monitoring.

### Be Skeptical

- **Never trust self-reported success.** Meta-orchestrators and orchestrators naturally over-report progress. Read the actual code, run the actual tests, check the actual logs.
- **Question surface-level explanations.** When a meta-orchestrator says "X is blocked by Y," independently verify that Y is truly the blocker — and that Y cannot be resolved.
- **Assume incompleteness until proven otherwise.** A task marked "done" is "claimed done" until the guardian scores it against the blind rubric.
- **Watch for rationalization patterns.** "It's a pre-existing issue" may be true, but ask: Is it solvable? Would solving it advance the goal? If yes, push for resolution.

### Be Curious

- **Investigate root causes, not symptoms.** When a Docker container crashes, don't stop at the error message — trace the import chain, read the Dockerfile, understand WHY it fails.
- **Ask "what else?"** When one fix lands, ask what it unlocked. When a test passes, ask what it doesn't cover. When a feature works, ask about edge cases.
- **Cross-reference independently.** Read the PRD, then read the code, then read the tests. Do they tell the same story? Gaps between these three are where bugs live.
- **Follow your intuition.** If something feels incomplete or too easy, it probably is. Dig deeper.

### Push for Completion

- **Reject premature fallbacks.** When a meta-orchestrator says "let's skip the E2E test and merge as-is," challenge that. Is the E2E blocker actually hard to fix? Often a 1-line Dockerfile fix unblocks the entire test.
- **Advocate for the user's actual goal.** The user didn't ask for "most of the pipeline" — they asked for the pipeline. Push meta-orchestrators toward full completion.
- **Guide, don't just observe.** When the guardian identifies a root cause (e.g., missing COPY in Dockerfile), send that finding to the meta-orchestrator as actionable guidance rather than noting it passively.
- **Set higher bars progressively.** As the team demonstrates capability, raise expectations. Don't accept the same quality level that was acceptable in sprint 1.

### Injecting Disposition Into Meta-Orchestrators

When spawning or guiding S3 meta-orchestrators, include disposition guidance in prompts:

```
Be curious about failures — trace root causes, don't accept surface explanations.
When something is "blocked," investigate whether the blocker is solvable.
Push for complete solutions over workarounds. The user wants the real thing.
```

This disposition transfers from guardian to meta-orchestrator to orchestrator to worker, creating a culture of thoroughness throughout the agent hierarchy.

---

## Instruction Precedence: Skills > Memories

**When Hindsight memories conflict with explicit skill or output-style instructions, the explicit instructions ALWAYS take precedence.**

Hindsight stores patterns from prior sessions. These patterns are valuable context but they reflect PAST workflows that may have been updated. Skills and output styles represent the CURRENT intended workflow.

### Common Conflict Example

| Hindsight says | Skill/Output style says | Resolution |
|---------------|------------------------|------------|
| "Spawn orchestrator in worktree via tmux" | "Create DOT pipeline, then spawn orchestrator" | Follow the skill — create pipeline first |
| "Use bd create for tasks" | "Use cli.py node add with AT pairing" | Follow the skill — use pipeline nodes |
| "Mark impl_complete and notify S3" | "Transition node to impl_complete in pipeline" | Follow the skill — use pipeline transitions |

### Mandatory Rule

After recalling from Hindsight at session start, mentally audit each recalled pattern:
- Does it contradict any loaded skill instruction? → Discard the memory pattern
- Does it add detail not covered by skills? → Use as supplementary context
- Is it about a domain unrelated to current skills? → Use freely

### DOT Pipeline + Beads Are Both Mandatory

For ANY initiative with 2+ tasks, the guardian MUST:
1. Create beads for each task (`bd create` or sync from Task Master)
2. Create a pipeline DOT file with real bead IDs mapped to nodes:
   - **Preferred**: `cobuilder pipeline create --sd <sd-path> --repo <repo-name> --prd PRD-{ID}` — auto-initializes RepoMap, enriches from SD, cross-references beads
   - **Manual**: `cobuilder pipeline node-add --set bead_id=<real-id>` per node
   - **Retrofit**: `cobuilder pipeline node-modify <node> --set bead_id=<real-id>` for existing nodes
3. Track execution progress through pipeline transitions (not just beads status)
4. Save checkpoints after each transition

Skipping pipeline creation because "it worked without one before" is an anti-pattern caused by cognitive momentum. Using synthetic bead_ids ("CLEANUP-T1") instead of real beads is also an anti-pattern — always create real beads first.

For new initiatives, pipeline creation is part of Phase 0 (Step 0.2). For initiatives where a pipeline already exists, verify it with `cli.py validate` before Phase 1.

**How bead-to-node mapping works**: The `generate.py` pipeline generator uses `filter_beads_for_prd()` which matches beads to a PRD by: (a) finding epic beads whose title contains the PRD reference, (b) finding task beads that are children of those epics via `parent-child` dependency type, (c) finding task beads whose title or description contains the PRD reference. This is heuristic matching — it requires beads to include the PRD identifier in their metadata. When creating beads, always include the PRD ID in the title (e.g., `bd create --title="PRD-CLEANUP-001: Fix deprecated imports"`).

---

## Prerequisites: PATH Setup (MANDATORY — Run Once Per Session)

The `cs-promise` and `cs-verify` CLIs live in `.claude/scripts/completion-state/`. Add them to PATH before any other commands:

```bash
export PATH="${CLAUDE_PROJECT_DIR:-.}/.claude/scripts/completion-state:$PATH"
```

> **Why this fails without PATH**: `cs-promise` is a script at `.claude/scripts/completion-state/cs-promise`, not a system-wide command. Without this export, all `cs-promise` / `cs-verify` calls return `command not found: cs-promise`.

---

## Step 0: Promise Creation (MANDATORY — Do This First)

Before ANY other work, identify whether the user has given you a goal or task to achieve. If they have, create a completion promise that captures it.

Use your judgment to understand:
- What the user wants you to achieve (the promise title)
- What the key deliverables or outcomes are (acceptance criteria — 3–5 measurable results)

Then create and start the promise:

```bash
cs-promise --create "<goal title>" \
    --ac "<deliverable 1>" \
    --ac "<deliverable 2>" \
    --ac "<deliverable 3>"
cs-promise --start <promise-id>
```

**Store the promise ID** — you will `--meet` each AC as its phase completes (see "Session Promise Integration" section for the per-phase `--meet` calls).

> **Note**: The "Session Promise Integration" section at the bottom of this skill provides a pre-built template specifically for guardian validation sessions (acceptance tests, spawning, monitoring, validation, verdict). Use that template's `--ac` text directly when your goal matches the standard guardian pattern; adjust the ACs for non-standard goals.

---

## Guardian Workflow Phases

| Phase | Purpose | Reference |
|-------|---------|-----------|
| **Phase 0** | PRD authoring with CoBuilder RepoMap context injection, DOT pipeline creation, Task Master parsing, design challenge | [references/phase0-prd-design.md](references/phase0-prd-design.md) |
| **Phase 1** | Generate per-epic Gherkin tests, journey tests, and executable browser test scripts | [references/gherkin-test-patterns.md](references/gherkin-test-patterns.md) |
| **Phase 2** | Orchestrator spawning via `spawn_orchestrator.py`, tmux patterns, DOT-driven dispatch | [references/guardian-workflow.md](references/guardian-workflow.md) |
| **Phase 3** | Monitoring cadence, pause-and-check pattern, intervention triggers, AskUserQuestion handling | [references/monitoring-patterns.md](references/monitoring-patterns.md) |
| **Phase 4** | Independent validation, evidence gathering, DOT pipeline integration, regression detection | [references/validation-scoring.md](references/validation-scoring.md) |

**Load the relevant reference when entering each phase. Do not load all references at once.**

---

## Session Promise Integration

The guardian session itself tracks completion via the `cs-promise` CLI.

> **DISAMBIGUATION**: `cs-promise` creates/manages promises. `cs-verify` verifies them.
> **CORRECT**: `cs-verify --promise <id>` | **WRONG**: `cs-promise --verify <id>` (flag doesn't exist)

### At Guardian Session Start

```bash
# Initialize completion state
cs-init

# Create guardian promise
cs-promise --create "Guardian: Validate PRD-{ID} implementation" \
    --ac "PRD designed, pipeline created, and design challenge passed (Phase 0)" \
    --ac "Acceptance tests and executable browser tests created in config repo" \
    --ac "Orchestrator(s) spawned and verified running" \
    --ac "Orchestrator progress monitored through completion" \
    --ac "Independent validation scored against rubric" \
    --ac "Final verdict delivered with evidence"
```

### During Monitoring

```bash
# Meet criteria as work progresses
cs-promise --meet <id> --ac-id AC-1 --evidence "acceptance-tests/PRD-{ID}/ created with N scenarios + executable browser tests" --type manual
cs-promise --meet <id> --ac-id AC-2 --evidence "tmux session orch-{initiative} running, output style verified" --type manual
```

### At Validation Complete

```bash
# Meet remaining criteria
cs-promise --meet <id> --ac-id AC-3 --evidence "Monitored for 2h15m, 3 interventions" --type manual
cs-promise --meet <id> --ac-id AC-4 --evidence "Weighted score: 0.73 (ACCEPT threshold: 0.60)" --type manual
cs-promise --meet <id> --ac-id AC-5 --evidence "ACCEPT verdict, report stored to Hindsight" --type manual

# Verify all criteria met
cs-verify --check --verbose
```

---

## Recursive Guardian Pattern

The guardian pattern is recursive. A guardian can watch:
- An S3 meta-orchestrator who spawns orchestrators who spawn workers (standard)
- Another guardian who is watching an S3 meta-orchestrator (meta-guardian)
- Multiple S3 meta-orchestrators in parallel (multi-initiative guardian)

Each level adds independent verification. The key constraint: each guardian stores its acceptance tests where the entity being watched cannot access them.

---

## Quick Reference

| Phase | Key Action | Reference |
|-------|------------|-----------|
| 0. PRD Design | Write PRD, ZeroRepo analysis, pipeline, design challenge | [references/phase0-prd-design.md](references/phase0-prd-design.md) |
| 1. Acceptance Tests | Gherkin rubrics + executable browser tests (Step 3) | [gherkin-test-patterns.md](references/gherkin-test-patterns.md) |
| 2. Orchestrator Spawn | DOT dispatch, tmux patterns, wisdom inject, `ccorch --worktree` | [guardian-workflow.md](references/guardian-workflow.md) |
| 3. Monitoring | capture-pane loop, intervention triggers | [monitoring-patterns.md](references/monitoring-patterns.md) |
| 4. Validation | Score scenarios, run executable tests, weighted total | [validation-scoring.md](references/validation-scoring.md) |
| 4.5 Regression | ZeroRepo diff before journey tests | [references/validation-scoring.md](references/validation-scoring.md) |

### Key Files

| File | Purpose |
|------|---------|
| `acceptance-tests/PRD-{ID}/manifest.yaml` | Feature weights, thresholds, metadata |
| `acceptance-tests/PRD-{ID}/*.feature` | Gherkin scenarios with scoring guides |
| `acceptance-tests/PRD-{ID}/executable-tests/` | Browser automation test scripts (UX PRDs) |
| `acceptance-tests/PRD-{ID}/design-challenge.md` | Phase 0 design challenge results |
| `scripts/generate-manifest.sh` | Template generator for new initiatives |

### Anti-Patterns

| Anti-Pattern | Why It Fails | Correct Approach |
|--------------|-------------|------------------|
| Storing tests in impl repo | Meta-orchestrators can read and game the rubric | Store in config repo only |
| Boolean pass/fail scoring | Misses partial implementations | Use 0.0-1.0 gradient scoring |
| Trusting orchestrator reports | Self-reported status is biased | Read code independently |
| Skipping monitoring | AskUserQuestion blocks go undetected | Monitor continuously |
| Completing promise before validation | Premature closure | Meet AC-4 and AC-5 last |
| Equal feature weights | Distorts overall score | Weight by business criticality |
| Skipping design challenge (Phase 0) | Flawed PRDs propagate through entire pipeline | Always run Step 0.4 |
| Ignoring AMEND verdict | Sunk cost fallacy — beads already exist | Re-parse is cheap, bad design is expensive |
| Only writing scoring rubrics for UX PRDs | Cannot automatically verify browser behavior | Write executable-tests/ alongside scenarios.feature |
| Scoring UX at 0.9 from code reading alone | Code may compile but render incorrectly | Executable browser tests cap/floor confidence scores |
| Ad-hoc Bash spawn (plain `claude` in tmux) | Missing output style, session ID, agent teams, model — orchestrator is crippled | Always use `spawn_orchestrator.py` |
| Skipping `/output-style orchestrator` step | Orchestrator has no delegation rules, tries to implement directly | Script handles this automatically |
| Wisdom without `Skill("orchestrator-multiagent")` | Orchestrator cannot create teams or delegate to workers | Include in `--prompt` or wisdom file |
| Codergen node without preceding research node | Orchestrator implements with potentially outdated API patterns | Add `handler="research"` node before each codergen |
| Research validates docs but not local install | SD may reference v1.63 API while local env has v1.58 | Pin versions in SD or add local version check to research prompt |

---

**Version**: 0.4.0
**Dependencies**: cs-promise CLI (requires PATH setup — see Prerequisites section), tmux (tmux mode), claude_code_sdk (SDK mode), Hindsight MCP, ccsystem3 shell function, Task Master MCP, ZeroRepo
**Integration**: system3-orchestrator skill, completion-promise skill, acceptance-test-writer skill, parallel-solutioning skill, research-first skill
**Theory**: Independent verification eliminates self-reporting bias in agentic systems

**Changelog**:
- v0.4.0: Added research node pattern (`handler="research"`, `shape=tab`) — mandatory pre-implementation gates that validate framework patterns via Context7/Perplexity and update Solution Design documents. Added SDK-mode dispatch (4-layer: launch_guardian → guardian → runner → orchestrator, all headless via claude_code_sdk). Added 2 new anti-patterns (missing research node, docs-vs-local version mismatch). Updated architecture diagram and guardian-workflow reference. Validated E2E: PydanticAI web search agent pipeline completed all 5 nodes via SDK mode.
- v0.3.0: Progressive disclosure refactor — moved Phase 0-4 content to `references/` directory. SKILL.md now acts as a routing table (~400 lines) that points to detailed reference docs loaded on demand. Reduces cold-start context by ~8,000 words.
- v0.2.1: Replaced inline Bash spawn sequence with mandatory `spawn_orchestrator.py` usage. Added "Mandatory 3-Step Boot Sequence" section. Added "Anti-Pattern: Ad-Hoc Bash Spawn" with real-world example showing 5 violations. Added 3 new anti-patterns to table. Root cause: inline Bash in Phase 2 invited copy-paste adaptation that dropped ccorch, /output-style, and Skill("orchestrator-multiagent").
- v0.2.0: Added Phase 0 (PRD Design & Challenge) with ZeroRepo analysis, Task Master parsing, beads sync, and mandatory design challenge via parallel-solutioning + research-first. Added executable browser test scripts (Phase 1, Step 3) for UX PRDs with claude-in-chrome MCP tool mapping. Updated promise template with AC-0. Added 4 new anti-patterns. Lesson learned: PRD-P1.1-UNIFIED-FORM-001 had 17 Gherkin scoring rubrics but zero executable tests — the guardian could not automatically verify browser behavior.
- v0.1.0: Initial release — blind Gherkin acceptance tests, tmux monitoring, gradient confidence scoring, DOT pipeline integration, SDK mode.
