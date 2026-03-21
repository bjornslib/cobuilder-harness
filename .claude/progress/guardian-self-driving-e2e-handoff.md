# Session Handoff: Guardian Self-Driving Pipeline E2E Validation

## Last Action
Completed both parallel tasks:
1. Documentation review agent updated CLAUDE.md, cobuilder/CLAUDE.md, lifecycle README, PRD-GUARDIAN-DISPATCH-001 status
2. Created PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001 (mini-PRD for autonomous PRD-to-implementation) with SD and 8 Gherkin acceptance tests

All work committed and pushed to branch `feat/PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001`. PR #41 (dispatch hardening) merged to main.

## Pipeline State
No active pipelines. All test pipelines completed:
- `hello-world-guardian-test.dot` — all 5 nodes terminal (Phase 1)
- `guardian-self-driving-phase2.dot` — all 14 nodes terminal (Phase 2)
- `add-two-numbers-lifecycle.dot` — all 6 nodes terminal (Phase 3)
- `add-two-numbers-lifecycle-v2.dot` — all 6 nodes terminal (hardened guardian test)
- `PRD-GUARDIAN-DISPATCH-001.dot` — all 20 nodes terminal (dispatch hardening)

## Next Dispatchable Nodes
**PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001** is ready for implementation on branch `feat/PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001`:

| Epic | Description | Files | Complexity |
|------|-------------|-------|------------|
| E1 (60%) | `launch_lifecycle()` function + `--lifecycle` CLI flag in `guardian.py` | `cobuilder/engine/guardian.py` | Medium — add function + CLI arg + template instantiation |
| E2 (40%) | System prompt teaches child pipeline creation at PLAN node | `cobuilder/engine/guardian.py` | Low — add template instantiation instructions to f-string |

**Recommended approach**: Create a 2-node pipeline (E1 → E2, sequential since both modify guardian.py) and run via `pipeline_runner.py`. Handle gates as Guardian.

### Key implementation details from the SD:
- `launch_lifecycle()` takes a PRD path, derives initiative_id from filename (PRD-AUTH-001.md → AUTH-001)
- Creates placeholder state files (research.json, refined.md) so sd_path validation passes
- Instantiates cobuilder-lifecycle template automatically
- Validates rendered DOT via cli.py validate
- New `--lifecycle <prd_path>` CLI flag, mutually exclusive with `--dot` and `--multi`

### Artifacts already created:
- PRD: `docs/prds/PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001.md`
- SD: `docs/sds/guardian-lifecycle-launcher/SD-GUARDIAN-LIFECYCLE-LAUNCHER-001.md`
- Acceptance tests: `acceptance-tests/PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001/` (manifest + 2 feature files, 8 scenarios)

## Open Concerns
1. **Stop hook still partially fires on guardian agent** (turns 77-99 in Logfire trace). Custom `_create_guardian_stop_hook()` was added but the harness unified-stop-gate.sh may still run alongside it. The custom hook correctly completes the pipeline, but the agent still spends ~5 turns on cs-verify/hindsight at exit. May need investigation into whether `hooks=` parameter fully overrides harness hooks or supplements them.

2. **cobuilder-lifecycle template file-existence validation**: Template references state files (research.json, refined.md) that don't exist at pipeline creation time. The `launch_lifecycle()` function handles this by creating placeholders, but direct template instantiation without the launcher will hit validation errors. Consider adding a `--skip-file-check` flag to `cli.py validate`.

3. **GLM-5 f-string escaping**: Workers using GLM-5 (alibaba-glm5) occasionally introduce unescaped `{variable}` inside Python f-strings. This caused a NameError in the failure context section (fixed manually). Consider adding a post-edit lint check for f-string syntax.

## Confidence Trend
- Phase 1 hello-world: PASS (gate deadlock found and fixed)
- Phase 2 gap closure: ALL 4 PASS (CRUD, gate fix, failure context, constraints)
- Phase 3 lifecycle: PASS (autonomous research→implement→validate→close)
- Dispatch hardening: ALL 6 epics PASS (30/30 acceptance checks)
- Hardened lifecycle test: PASS (45 tool calls, down from 97)

Confidence is high. The guardian self-driving pattern is validated and operational. The lifecycle launcher (PRD-GUARDIAN-LIFECYCLE-LAUNCHER-001) is the final piece to make it single-command autonomous.
