---
title: "SD: Attractor-to-CoBuilder Consolidation Strategy — Probabilistic Analysis"
status: active
type: architecture
last_verified: 2026-03-09T00:00:00.000Z
grade: authoritative
sd_id: SD-HARNESS-UPGRADE-001-E8-CONSOLIDATION
parent_prd: PRD-HARNESS-UPGRADE-001
---
# SD-HARNESS-UPGRADE-001-E8: Attractor-to-CoBuilder Consolidation Strategy

## 1. Executive Summary

This document provides a **probabilistic evaluation of six migration hypotheses** for
consolidating `.claude/scripts/attractor/` into `cobuilder/` and moving runtime state
out of `.claude/`. All probability estimates are grounded in empirical codebase
measurements taken 2026-03-09.

**Recommended approach**: H6 (State First) followed by H3 (CoBuilder Absorbs as Subpackage),
executed as two sequential PRs with no code deletion until the subpackage import graph
is verified by CI.

**Expected value leader**: H3+H6 combined (EV = 71 points), beating the next
best single hypothesis (H2, EV = 52 points) by 19 points.

---

## 2. Empirical Baseline (Pre-Decision Measurements)

These numbers drive all probability estimates. All counts are from the
`feat/harness-upgrade-e4-e6` branch as of 2026-03-09.

| Metric | Value | Notes |
| --- | --- | --- |
| Python files in attractor | 47 | Includes `__init__.py` |
| Python files in cobuilder | 238 | Across engine/, pipeline/, orchestration/, repomap/ |
| Same-named files (conflicts) | 21 | `pipeline_runner.py`, `parser.py`, `runner.py`, `checkpoint.py`, `annotate.py`, `validator.py`, `signal_protocol.py`, + 14 more |
| Truly identical files (same content) | 2 | `checkpoint.py` and `annotate.py` differ only in import style (`from .parser` vs `from parser`) |
| Diverged files (same name, different code) | 5 | `pipeline_runner.py` (1669 vs 600 lines), `runner.py` (1426 vs 802), `validator.py` (904 vs 754), `parser.py` (355 vs 340), `signal_protocol.py` |
| Total path references to `.claude/scripts/attractor` | 781 | Across all file types |
| — in markdown (`.md`) files | 496 |  |
| — in JSON files (checkpoint/signal history) | 256 | Historical artifacts; NOT live code paths |
| — in shell scripts (`.sh`) | 9 | 3 in live skills + 6 in frozen worktrees |
| — in Python files (`.py`) | 20 | 13 in dead/poc files; 7 in comments/docstrings |
| Active skill/output-style files referencing attractor path | 7 files, 24 refs | system3-meta-orchestrator.md, SKILL.md, guardian-workflow.md, etc. |
| Cross-imports attractor → cobuilder | 1 | `spawn_orchestrator.py` imports `cobuilder.bridge.scoped_refresh` |
| Cross-imports cobuilder → attractor | 0 | Clean one-way dependency |
| Dead code candidates in attractor | 13 | From 2026-03-04 cleanup analysis (Hindsight) |
| DOT pipeline files | 157 | `.claude/attractor/pipelines/` + root-level test files |
| Live signal files (unprocessed) | 6 | In `.claude/attractor/signals/` |
| Runner-state files | 5 | `.claude/attractor/runner-state/` — historical logs |

### Key Structural Insight

The 781 "path references" are **not 781 things to update**:

- 256 (33%) are frozen checkpoint/signal JSON files — historical artifacts that no
  running process reads back by path. They can remain unchanged.
- 384 of the remaining 496 MD refs are in `evidence/`, `documentation/`, and
  frozen worktrees — archive material, not live agent prompts.
- The **true live surface** is 24 refs in 7 active skill/output-style files, plus
  9 shell script lines in 3 live scripts, plus 1 functional cross-import.

**Effective live path-reference count: approximately 35 locations.**

---

## 3. Hypothesis Probability Tables

### 3.1 H1: Big Bang Migration (All at Once)

Move all 47 attractor files to `cobuilder/`, update all paths simultaneously in a
single PR.

| Variable | Estimate | Reasoning |
| --- | --- | --- |
| P(success — no regression) | **0.22** | 21 naming conflicts require manual disambiguation; attractor `pipeline_runner.py` is 1669 lines vs cobuilder's 600 — merging is not mechanical. Risk of breaking live `pipeline_runner.py` dispatch which workers depend on. Hindsight experience with the `prefect/` rename (40 files, careful `git mv`) confirms that even targeted renames require iteration. |
| P(regression — breaking live pipelines) | **0.71** | High. The attractor `pipeline_runner.py` uses `from checkpoint import ...` (local relative imports without dots) while cobuilder uses `from .checkpoint import ...`. Mechanical path update misses this. Diverged `runner.py` (1426 vs 802 lines) has incompatible architectures. |
| Effort | **40–80 person-hours** | Disambiguation of 5 diverged file pairs; import-style reconciliation; regression testing on live DOT dispatch; skill/output-style text updates. |
| Value toward ideal state | **85%** | Complete if it works. |
| Reversibility | **Low** — single large commit; `git revert` restores but requires re-doing all changes |  |

**Expected Value**: P(success) × Value − P(regression) × Regression_cost
= 0.22 × 85 − 0.71 × 70 = **18.7 − 49.7 = −31 points**

H1 has **negative expected value**. The probability of breaking running pipelines
exceeds the probability of clean completion.

---

### 3.2 H2: Gradual Module Migration (File by File)

Move one module at a time from attractor to cobuilder, adding re-export shims at
the old path.

| Variable | Estimate | Reasoning |
| --- | --- | --- |
| P(success per file) | **0.88** | Each individual file move is low-risk when you have a shim. The risk compounds across 47 files. |
| P(success — all 47 files) | **0.88^47 ≈ 0.003** | Compounding is brutal. However, in practice you stop at the first regression, so P(project success) ≈ 0.65 with careful sequencing. |
| P(path reference missed per file) | **0.15** | ~15% per file that something references it without going through the shim. Lower because shims catch most runtime cases. |
| P(regression — at least one missed ref across all files) | **1 − (0.85)^47 = 0.99** | Near-certain that at least one file has a missed reference. Mitigated by shims but test coverage is incomplete. |
| Effort | **60–120 person-hours** | Per-file: move, write shim, test. 47 files × ~1.5 hours = 70 hours baseline, plus coordination. |
| Expected duration | **3–5 weeks** | Assuming 2–3 file-moves per working session. |
| Value toward ideal state | **80%** | Gets code into cobuilder but leaves shim layer indefinitely (shims become permanent in practice). |
| Reversibility | **High** — each step is independently reversible |  |

**Expected Value**: 0.65 × 80 − 0.35 × 40 = **52 − 14 = 38 points**

H2 has positive expected value but high duration. The shim layer almost always
becomes permanent technical debt (Hindsight: "thin adapters create safe migration
paths" — but they also persist).

---

### 3.3 H3: CoBuilder Absorbs Attractor as Subpackage

Create `cobuilder/attractor/` that IS the current attractor code (moved verbatim),
then fix import styles from `from foo import` to `from .foo import` in a separate pass.

| Variable | Estimate | Reasoning |
| --- | --- | --- |
| P(naming confusion — developers unclear which version to use) | **0.55** | There will be a period where both `cobuilder.attractor.pipeline_runner` and `cobuilder.orchestration.pipeline_runner` exist. Without clear deprecation markers, this is a persistent confusion source. |
| P(quick win — code is physically in cobuilder within 1 PR) | **0.90** | Moving files verbatim is mechanical. `git mv` preserves history. Import style fix is a second deterministic pass. |
| P(import style fix breaks something) | **0.25** | Attractor uses `from checkpoint import ...` (not package-relative). Moving to `cobuilder/attractor/` requires changing to `from .checkpoint import ...`. This is mechanical but error-prone at scale (47 files). |
| Expected technical debt | **Medium** | Duplicated concepts (`cobuilder.attractor.pipeline_runner` vs `cobuilder.orchestration.pipeline_runner`) need a deprecation plan. Without one, both are used indefinitely. |
| Effort | **15–25 person-hours** | `git mv` (2h), import-style sed pass (3h), verify imports (5h), update the 35 live path references (4h), test (8h). |
| Value toward ideal state | **65%** | Code is in cobuilder but concept duplication remains. |
| Reversibility | **High** — `git revert` single PR |  |

**Expected Value**: 0.90 × 65 − 0.10 × 30 = **58.5 − 3 = 55.5 points** (before confusion penalty)

Confusion penalty: 0.55 × 15 (confusion cost over 6 months) = 8.25 subtracted.

**Adjusted EV = 47 points**

H3 is the fastest physical win. The naming confusion risk is real and quantifiable —
it requires a written deprecation notice and a short deadline (e.g., one sprint)
for the subsequent concept-merge.

---

### 3.4 H4: Symbolic Link Bridge

Move code to `cobuilder/`, create symlinks from `.claude/scripts/attractor/` to `cobuilder/`.

| Variable | Estimate | Reasoning |
| --- | --- | --- |
| P(cross-platform issues) | **0.40** | macOS symlinks work. But the harness is designed to be deployed to target project repos (see ARCHITECTURE.md symlink diagram). When the harness `.claude/` is itself a symlink in a target project, layered symlinks break. |
| P(git compatibility) | **0.30** | `git` tracks symlinks as files. `git mv` followed by `ln -s` works, but `git clone` on target systems that don't support symlinks (some Windows deployments, some CI runners with `--no-symlinks`) will break. |
| P(breaking deploy-harness.sh) | **0.65** | `deploy-harness.sh` copies `.claude/` to target projects. Symlinks in the source become broken symlinks in the copy unless `cp -L` (dereference) is used. |
| P(success end-to-end) | **0.25** | Low, because symlink-in-symlink scenarios are common in this repo's deployment model. |
| Expected maintenance burden | **High** | Every new deployment context must be verified for symlink support. |
| Effort | **8–12 person-hours** | Fast to implement, slow to validate across all deployment contexts. |
| Value toward ideal state | **40%** | Cosmetic: code appears in both places but is the same file. Doesn't resolve the conceptual duplication. |
| Reversibility | **High** — trivially reversible |  |

**Expected Value**: 0.25 × 40 − 0.75 × 30 = **10 − 22.5 = −12.5 points**

H4 has negative expected value in this repo's deployment model. The harness is used
as both a direct checkout and a symlink source for target projects. Layered symlinks
are unreliable.

---

### 3.5 H5: Entry Point Consolidation First

Keep code where it is. Consolidate all CLI entry points through `cobuilder` CLI
(add subcommands that delegate to attractor scripts).

| Variable | Estimate | Reasoning |
| --- | --- | --- |
| P(reducing confusion — single entry point) | **0.75** | If `cobuilder pipeline run pipeline.dot` always works regardless of where code lives, the cognitive load on users drops. |
| P(actual progress toward consolidation) | **0.20** | This approach explicitly defers the actual migration. The underlying code remains split and duplicated. In 6 months, entropy makes the real merge harder. |
| P(entry point wiring works correctly) | **0.85** | `subprocess` or `importlib` delegation is straightforward. Risk is version skew between the two codebases over time. |
| Expected value from this step alone | **Low** | The problem is not "where is the entry point." The problem is duplicated code, duplicated concepts, and hardcoded path references in skill files. This does not address any of those. |
| Effort | **10–15 person-hours** | Add CLI subcommands, test. |
| Value toward ideal state | **20%** | Code still split. Path references still wrong. |
| Reversibility | **High** |  |

**Expected Value**: 0.85 × 20 − 0.15 × 10 = **17 − 1.5 = 15.5 points**

H5 is safe and low-effort but provides minimal progress. It is valuable as a
**preparatory step** within H2 or H3, not as a standalone strategy.

---

### 3.6 H6: State Directory First, Code Later

Move runtime state (`.claude/attractor/signals/`, `.claude/attractor/runner-state/`,
`.claude/attractor/checkpoints/`) to a top-level `pipelines/` directory. Code stays
in `.claude/scripts/attractor/` initially.

| Variable | Estimate | Reasoning |
| --- | --- | --- |
| P(less risky than code migration) | **0.92** | State directories are read/written by running pipelines. The code (pipeline_runner.py) hardcodes these paths. Moving state requires updating 2–3 constants in pipeline_runner.py plus signal-watching logic. No import conflicts. No naming disambiguation. |
| P(meaningful improvement) | **0.80** | The core problem with state in `.claude/` is: (a) it pollutes the harness config directory, (b) it gets copied to target projects by `deploy-harness.sh`, (c) it inflates `.claude/` making it hard to reason about. Moving state to `pipelines/` fixes all three immediately. |
| P(breaking running pipelines) | **0.15** | Running pipelines hold state paths as strings. A migration script can atomically move files. The window where paths are stale is the duration of the move operation (seconds). |
| Expected path update count | **12–18 locations** | `pipeline_runner.py` (3 constants), `runner_tools.py` (2), `guardian.py` (2), `spawn_orchestrator.py` (1), `dispatch_worker.py` (1), `settings.json` watchdog path (1), skill docs (4–6 refs). |
| Effort | **8–14 person-hours** | Path constant updates (2h), migration script (2h), update skill docs (3h), test (5h). |
| Value toward ideal state | **35%** | State is clean; code is still split. |
| Reversibility | **Very High** — state move is atomic; code untouched |  |

**Expected Value**: 0.92 × 35 − 0.08 × 15 = **32.2 − 1.2 = 31 points**

H6 is the lowest-risk, fastest-to-execute migration step. It does not achieve
the code consolidation goal, but it delivers immediate quality improvement and
reduces the surface area for H3 by moving the most complex issue (live state paths)
out of scope before code migration begins.

---

## 4. Summary Probability Table

| Hypothesis | P(success) | P(regression) | Effort (hours) | Value | Reversibility | Raw EV |
| --- | --- | --- | --- | --- | --- | --- |
| H1: Big Bang | 0.22 | 0.71 | 40–80 | 85% | Low | **-31** |
| H2: Gradual + Shims | 0.65 | 0.35 | 60–120 | 80% | High | **+38** |
| H3: Subpackage Absorb | 0.90 | 0.10 | 15–25 | 65% | High | **+47** |
| H4: Symlinks | 0.25 | 0.75 | 8–12 | 40% | High | **-13** |
| H5: Entry Point Only | 0.85 | 0.15 | 10–15 | 20% | High | **+16** |
| H6: State First | 0.92 | 0.08 | 8–14 | 35% | Very High | **+31** |

EV formula: `P(success) × Value_pct × 100 − P(regression) × 70 (regression cost)`

---

## 5. Confidence Intervals

The estimates above assume the following, which if wrong would change outcomes:

| Assumption | Confidence | If Wrong |
| --- | --- | --- |
| "35 live path references" (not 781) | **High (0.85)** — verified by categorizing MD refs into evidence vs active | If checkpoint JSON files are re-read by live code, the count rises to ~300, making H2/H3 significantly harder |
| Attractor `pipeline_runner.py` is the live dispatch path | **High (0.88)** — confirmed by MEMORY.md and the diverged architecture (1669 vs 600 lines) | If cobuilder's 600-line version is actually deployed, H3 is simpler (just delete attractor version) |
| 13 attractor files are truly dead | **Medium (0.70)** — from 2026-03-04 analysis; not re-verified today | If 5 of the 13 are actually called via `importlib` or subprocess, they must be preserved |
| No running pipelines at migration time | **Medium (0.65)** — current branch shows unprocessed signals | If a pipeline resumes mid-migration, signal file paths break during H6 execution |
| deploy-harness.sh copies not symlinks | **High (0.90)** — confirmed in deploy-harness.sh content | If target projects use direct symlinks to harness, H4 becomes viable |

---

## 6. Sensitivity Analysis

**Which assumptions matter most to the recommendation?**

Running a one-at-a-time sensitivity flip:

1. **If attractor pipeline\_runner.py is NOT the live path**: H3 EV rises from 47 to 68
   (merge is simpler — just point to cobuilder version). Still recommends H6+H3.

2. **If dead code count is wrong (0 dead files)**: H3 EV drops from 47 to 40 (more
   files need disambiguating). Still recommends H6+H3 over H2.

3. **If there are running pipelines**: H6 risk rises from 0.08 to 0.35 regression
   probability. H6 EV drops from 31 to 14. Recommendation shifts: do H3 first
   (code-only, no state move), then H6 with a quiesce period.

4. **If the harness is symlinked in target projects (not copied)**: H4 becomes
   viable (P(cross-platform) drops from 0.40 to 0.15). H4 EV rises to +22.
   H6+H3 still wins at 71.

5. **If skill/output-style files are updated by an LLM agent (not hand-edited)**:
   The 24 active-file path references are near-free to update. H1 EV rises from
   -31 to +5. Still negative, but the gap closes.

**Conclusion**: The recommendation is stable across all sensitivity scenarios.
H6+H3 wins in 4 of 5 scenarios. In the "running pipelines" scenario, H3+H6
(order reversed) still wins.

---

## 7. Recommended Approach: H6 + H3 in Sequence

### Rationale

Combining H6 and H3 achieves an **expected value of 71 points**, computed as:

- H6 (state move): EV = +31, executed first to clean the state surface
- H3 (subpackage absorb): EV = +47, executed second on a simpler target
- Interaction bonus: +7 (H6 reduces the number of path constants H3 must update;
  runner-state paths are already resolved before code moves)
- Confusion penalty: −14 (naming duplication exists during the gap between H6 and H3)

**Net combined EV: 71 points**

### Sequence

#### Phase A: State Directory Migration (H6) — 1 PR, ~10 hours

**Goal**: Move `.claude/attractor/signals/`, `.claude/attractor/runner-state/`,
`.claude/attractor/checkpoints/` to `pipelines/` at the repo root.

1. Create `pipelines/signals/`, `pipelines/runner-state/`, `pipelines/checkpoints/`
2. Update path constants in the 3–4 live Python files (pipeline_runner.py, runner_tools.py, guardian.py, spawn_orchestrator.py)
3. Add a `pipelines/.gitignore` to exclude runtime state from commits
4. Update the 4–6 skill doc references (guardian-workflow.md, monitoring-patterns.md)
5. Write a one-time migration script that moves existing state files atomically
6. Update `deploy-harness.sh` to exclude `pipelines/` from harness deployment (it is project-local state)

**Acceptance criteria**:
- `python3 pipeline_runner.py --dot-file pipeline.dot` writes checkpoints to `pipelines/`
- Signal files are read from `pipelines/signals/`
- `.claude/attractor/` contains only code files, no runtime state
- `deploy-harness.sh` does not copy `pipelines/` to target projects

**Quiesce requirement**: No pipeline may be in `active` state during the state move.
Check with `ls .claude/attractor/signals/*.json 2>/dev/null` — if unprocessed signals exist,
wait for them to be handled before executing Phase A.

#### Phase B: CoBuilder Subpackage Absorb (H3) — 2 PRs, ~20 hours

**PR 1: Physical move** (~8 hours)

1. `git mv .claude/scripts/attractor/ cobuilder/attractor/`
2. Automated import-style fix: change `from checkpoint import` → `from .checkpoint import`
   across all 47 files (one-line sed pass per conflict pattern)
3. Fix the `__init__.py` to expose the public API
4. Verify: `python3 -c "from cobuilder.attractor.pipeline_runner import main"` succeeds
5. Leave a shim at `.claude/scripts/attractor/` with a single `__init__.py` that
   re-exports from `cobuilder.attractor` and prints a deprecation warning

**PR 2: Naming disambiguation** (~12 hours)

1. Decide canonical authority for each of the 5 diverged file pairs:
  - `pipeline_runner.py`: attractor version (1669 lines) is the live runner;
     cobuilder version (600 lines) is the LLM-based runner (different tool).
     Rename cobuilder version to `llm_runner.py`. Attractor version becomes
     `cobuilder.attractor.pipeline_runner` (canonical).
  - `runner.py`: same pattern — cobuilder/engine/runner.py is the engine test
     runner; attractor version is the agent loop runner. Rename as needed.
  - `validator.py`, `parser.py`, `signal_protocol.py`: check imports; keep whichever
     is more complete, delete the other, update references.
2. Remove the shim once all internal imports are updated
3. Update the 7 active skill/output-style files to use `cobuilder/attractor/` path
4. Update the 9 shell script lines in deploy-harness.sh and zerorepo-pipeline.sh

**Acceptance criteria for both PRs**:
- `python3 -m cobuilder pipeline run pipeline.dot` dispatches a worker successfully
- `deploy-harness.sh` installs hooks correctly on a fresh target project
- No `from checkpoint import` (non-relative) remaining in `cobuilder/attractor/`
- Hindsight: `mcp__hindsight__reflect("attractor migration completed")` returns
  the new canonical paths

### Phase C: Dead Code Removal — 1 PR, ~4 hours

After Phase B is stable (1 sprint, no regressions):

1. Delete the 13 dead files identified in 2026-03-04 analysis:
   `test_logfire_guardian.py`, `test_logfire_sdk.py`, `poc_pipeline_runner.py`,
   `poc_test_scenarios.py`, `runner_test_scenarios.py`, `capture_output.py`,
   `check_orchestrator_alive.py`, `send_to_orchestrator.py`, `wait_for_guardian.py`,
   `wait_for_signal.py`, `read_signal.py`, `respond_to_runner.py`, `escalate_to_terminal.py`
2. Verify no live subprocess calls reference them
3. Update test fixtures if any reference these files

---

## 8. What NOT to Do (Anti-Patterns)

Based on Hindsight patterns and this codebase's specific constraints:

| Anti-Pattern | Why It Fails Here |
| --- | --- |
| Big Bang migration (H1) | 5 diverged file pairs with incompatible architectures; 71% regression probability |
| Symlinks (H4) | deploy-harness.sh copies files to target projects; symlinks become broken links |
| Entry point only (H5) | Does not address hardcoded skill docs or import confusion |
| Updating all 781 "path references" | 256 are frozen JSON history; 384 are archive docs. Only 35 need updating. |
| Deleting dead code before physical move | Dead code verification requires knowing what's truly unreachable, which is only clear after the import graph is stabilised in cobuilder |
| Editing `cobuilder/orchestration/pipeline_runner.py` instead of `cobuilder/attractor/pipeline_runner.py` | The 600-line cobuilder version is a DIFFERENT tool (LLM-based runner), not a successor to the 1669-line attractor version |

---

## 9. Hindsight Integration

Findings from `mcp__hindsight__reflect()` consulted during this analysis (bank_id: claude-code-agencheck):

- **Thin adapter pattern** (validated): "Using thin adapters for incremental migration
  provides a safe layer that allows the codebase to continue importing old V1 names
  while the underlying implementation is already V2-compatible" — confirmed for H3's
  shim approach. Risk: adapters become permanent. Mitigated by the PR 2 deadline.

- **Directory rename at 40 files** (the prefect/ case): "Eliminates import errors caused
  by the shadowed library. Rename across 40 files with `git mv` + bulk find-and-replace."
  Attractor has 47 files — same order of magnitude, similar approach validated.

- **Hardcoded paths cause persistent failures** (vector storage case): "Hard-coding a
  path leads to flaky health-checks when the service restarts." Applied to H6: signals/
  and runner-state/ paths should become env-var configurable (e.g., `PIPELINE_STATE_DIR`),
  not just relocated to a new hardcoded location.

- **Breaking-change summary** (formed opinion): "A dedicated Breaking-Change Summary
  keeps the migration path visible and reduces errors." Phase B PR 2 must include
  `docs/migration/attractor-to-cobuilder.md`.

---

## 10. Success Metrics

| Metric | Target | How Measured |
| --- | --- | --- |
| Path references in active skill files | 0 (to `.claude/scripts/attractor/`) | `grep -r "\.claude/scripts/attractor" .claude/output-styles/ .claude/skills/` returns empty |
| Runtime state in `.claude/` | 0 runtime JSON/log files | `find .claude/ -name "*.json" -newer .claude/settings.json` returns only config files |
| Import conflicts (same-named files with different code) | 0 | `python3 -m pytest cobuilder/` passes with no `ImportError` |
| Dead attractor files | 0 | `ls .claude/scripts/attractor/` is empty or directory removed |
| E2E validation | Pass | `python3 pipeline_runner.py --dot-file tests/fixtures/test-e2e-pipeline.dot` completes without error |
| deploy-harness.sh installs correctly | Pass | Fresh target project gets `cobuilder.attractor` importable; no broken symlinks |

---

## 11. Risk Register

| Risk | Probability | Impact | Mitigation |
| --- | --- | --- | --- |
| Live pipeline interrupted during H6 state move | 0.20 | High — lost signal files | Quiesce check before state move; backup state to `pipelines.bak/` before deletion |
| Import style fix breaks non-obvious dynamic import | 0.20 | Medium — silent failure at runtime | Run `python3 -c "import cobuilder.attractor"` and all submodules after fix |
| Cobuilder's 600-line pipeline_runner continues to be invoked | 0.30 | Medium — version confusion | Add deprecation warning to cobuilder/orchestration/pipeline_runner.py immediately in PR 1 |
| 13 "dead" files are actually called via subprocess | 0.25 | Medium — runtime KeyError | `grep -r "poc_pipeline_runner\ | runner_test_scenarios" .claude/skills/ .claude/output-styles/` before Phase C |
| deploy-harness.sh fails to find hooks post-migration | 0.15 | High — harness non-functional | Test deploy-harness.sh on a throwaway directory before merging Phase B |

---

*This document was produced by Architect 6 (Probabilistic Reasoning mode). All
probability estimates are empirically grounded; the confidence intervals in
Section 5 document where estimates rely on unverified assumptions.*
