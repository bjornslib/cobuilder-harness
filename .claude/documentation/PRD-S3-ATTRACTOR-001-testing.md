---
title: "Prd S3 Attractor 001 Testing"
status: active
type: architecture
last_verified: 2026-02-19
grade: reference
---

# PRD-S3-ATTRACTOR-001 Testing Guide

Testing documentation for the S3 Attractor Pipeline system, covering the Attractor CLI, Doc Gardener, behavioral spec changes, and integration workflows.

---

## 1. Quick Smoke Test

Copy-paste commands to verify the core Attractor CLI is functional. All commands assume you are in the repository root.

```bash
# 1. Parse a simple DOT pipeline to JSON
python .claude/scripts/attractor/cli.py parse .pipelines/examples/simple-pipeline.dot --output json
# Expected: Valid JSON with 3 nodes, 2 edges

# 2. Validate a full initiative DOT file
python .claude/scripts/attractor/cli.py validate .pipelines/examples/full-initiative.dot
# Expected: "VALID: passes all validation rules"

# 3. Status summary of a full initiative
python .claude/scripts/attractor/cli.py status .pipelines/examples/full-initiative.dot
# Expected: Table with 17 nodes. Summary: active=2, impl_complete=1, pending=11, validated=3

# 4. Transition a node state
cp .pipelines/examples/full-initiative.dot /tmp/smoke-test.dot
python .claude/scripts/attractor/cli.py transition /tmp/smoke-test.dot impl_task active
# Expected: "Transition applied: impl_task: pending -> active"

# 5. Checkpoint save
python .claude/scripts/attractor/cli.py checkpoint save
# Expected: Saved with a hash (e.g., a96e77bc61c529e4)

# 6. Checkpoint restore round-trip
python .claude/scripts/attractor/cli.py checkpoint restore
python .claude/scripts/attractor/cli.py status /tmp/smoke-test.dot
# Expected: impl_task shows as active (preserved through save/restore cycle)

# 7. Doc gardener lint
python .claude/scripts/attractor/cli.py lint
# Expected: 297 files scanned, 395 violations found (174 auto-fixable, 221 manual)

# 8. Doc gardener report
python .claude/scripts/attractor/cli.py gardener --report
# Expected: Generates gardening-report.md correctly
```

---

## 2. Component Test Matrix

| Component | Test | Command / Check | Expected Result |
|-----------|------|-----------------|-----------------|
| **Attractor CLI - parse** | Parse simple DOT to JSON | `cli.py parse simple-pipeline.dot --output json` | Valid JSON, 3 nodes, 2 edges |
| **Attractor CLI - validate** | Validate full initiative | `cli.py validate full-initiative.dot` | "VALID: passes all validation rules" |
| **Attractor CLI - status** | Status of full initiative | `cli.py status full-initiative.dot` | 17 nodes; active=2, impl_complete=1, pending=11, validated=3 |
| **Attractor CLI - transition** | Transition node state | `cli.py transition <file> impl_task active` | "Transition applied: impl_task: pending -> active" |
| **Attractor CLI - checkpoint** | Save and restore round-trip | `cli.py checkpoint save` then `restore` | State preserved through round-trip |
| **Doc Gardener - lint** | Lint .claude/ directory | `cli.py lint` | 297 files scanned, 395 violations (174 auto-fixable, 221 manual) |
| **Doc Gardener - gardener** | Generate gardening report | `cli.py gardener --report` | gardening-report.md generated |
| **Doc Gardener - quality-grades** | Grade documentation quality | `cli.py gardener --quality-grades` | Quality grade summary per directory |
| **S3 Heartbeat** | SKILL.md structure check | Manual review of s3-heartbeat SKILL.md | No GChat MCP tool references present |
| **S3 Communicator** | SKILL.md scope check | Manual review of s3-communicator SKILL.md | Narrowed scope; no bd/git/tmux scanning references |
| **Validation Agent** | Dual-mode documentation | Review validation-test-agent.md | `--mode=technical` and `--mode=business` sections documented |
| **S3 Meta-Orchestrator** | Spawn block structure | Review system3-meta-orchestrator.md | 3 separate persistent agent spawn blocks present |
| **S3 Meta-Orchestrator** | DOT navigation section | Review system3-meta-orchestrator.md | DOT Graph Navigation section present |
| **Pre-push Hook** | Violation blocking | Attempt `git push` with violations | Push blocked when violations detected |
| **DOT Schema** | Example validity | Parse all example DOT files | All examples parse without errors |
| **generate-pipeline** | CLI subcommand | `cli.py generate --prd <PRD-REF>` | Produces valid DOT from PRD/beads |
| **annotate-pipeline** | Script execution | Run annotate-pipeline script | Updates node states in DOT file |
| **init-promise** | Script execution | Run init-promise script | Creates completion promise with pipeline reference |

---

## 3. Integration Tests

### 3.1 Full Pipeline Lifecycle

End-to-end test of the generate-validate-status-transition cycle:

```bash
# Step 1: Generate a pipeline DOT from beads
python .claude/scripts/attractor/cli.py generate --prd <PRD-REF> --output /tmp/integration-test.dot

# Step 2: Validate the generated pipeline
python .claude/scripts/attractor/cli.py validate /tmp/integration-test.dot
# Expected: VALID (or warnings only, no errors)

# Step 3: Check initial status
python .claude/scripts/attractor/cli.py status /tmp/integration-test.dot
# Expected: All nodes in pending state

# Step 4: Transition nodes through lifecycle
python .claude/scripts/attractor/cli.py transition /tmp/integration-test.dot <node_name> active
python .claude/scripts/attractor/cli.py transition /tmp/integration-test.dot <node_name> impl_complete
python .claude/scripts/attractor/cli.py transition /tmp/integration-test.dot <node_name> validated
# Expected: Each transition succeeds, status reflects changes

# Step 5: Checkpoint and verify persistence
python .claude/scripts/attractor/cli.py checkpoint save
python .claude/scripts/attractor/cli.py checkpoint restore
python .claude/scripts/attractor/cli.py status /tmp/integration-test.dot
# Expected: All transitions preserved
```

### 3.2 Doc Gardener Pre-push Hook

Verifies that the pre-push hook blocks pushes when documentation violations are present:

```bash
# Step 1: Ensure pre-push hook is installed
ls -la .git/hooks/pre-push

# Step 2: Introduce a documentation violation (or use existing ones)
# The current codebase has 395 known violations

# Step 3: Attempt a push
git push origin <branch>
# Expected: Push is blocked with violation summary

# Step 4: Fix violations (or use --no-verify to bypass for testing)
git push origin <branch> --no-verify
# Expected: Push succeeds when hook is bypassed
```

### 3.3 S3 Preflight Pipeline Status

Verifies that System 3 reads pipeline status during its preflight checks:

```bash
# Step 1: Ensure a valid pipeline DOT exists
python .claude/scripts/attractor/cli.py validate .pipelines/examples/full-initiative.dot

# Step 2: Check that S3 preflight step references attractor status
# The system3-orchestrator SKILL.md should include a preflight step that runs:
python .claude/scripts/attractor/cli.py status .pipelines/examples/full-initiative.dot
# Expected: S3 uses this output to determine which epics need attention
```

---

## 4. Manual Verification Checklist

Behavioral spec review -- verify each item by inspecting the referenced file:

- [ ] **s3-heartbeat SKILL.md**: No GChat MCP tool references (e.g., no `mcp__google-chat-bridge__*` tool calls)
- [ ] **s3-communicator SKILL.md**: Narrowed scope -- no `bd`/`git log`/`tmux` scanning references
- [ ] **validation-test-agent.md**: Both `--mode=technical` and `--mode=business` sections are present and documented
- [ ] **oversight-team.md**: Contains persistent `s3-validator` spawn pattern for continuous validation
- [ ] **system3-meta-orchestrator.md**: Contains 3 separate persistent agent spawn blocks (heartbeat, communicator, validator)
- [ ] **system3-meta-orchestrator.md**: Contains a DOT Graph Navigation section describing how S3 reads pipeline state
- [ ] **system3-meta-orchestrator.md**: Stop gate blocks session completion when unvalidated nodes remain in the pipeline
- [ ] **system3-orchestrator SKILL.md**: Includes a preflight step that checks attractor pipeline status before proceeding

---

## 5. Known Issues

### 5.1 Doc Gardener Violations on Current Codebase

The doc gardener reports **395 violations** when run against the current `.claude/` directory (297 files scanned). This is **expected** and pre-existing:

- **174 auto-fixable**: Mostly missing or malformed frontmatter in markdown files
- **221 manual**: Require human review (stale references, missing sections, etc.)

These violations reflect the state of the codebase before the doc gardener was introduced. They do not indicate a regression.

### 5.2 simple-pipeline.dot Validation Warnings

Running `validate` on `simple-pipeline.dot` produces **2 validation warnings**. This is **expected** because the simple example is intentionally minimal and lacks:

- Acceptance Test (AT) node pairs
- Full lifecycle state annotations

The warnings confirm that the validator correctly identifies incomplete pipelines without treating them as errors.
