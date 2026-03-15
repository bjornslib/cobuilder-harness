---
title: "Guardian Workflow"
status: active
type: guide
last_verified: 2026-03-07
grade: authoritative
---

# Guardian Workflow

## Overview
The guardian workflow manages the end-to-end orchestration of initiatives from PRD to completion, with special attention to validation gates and compliance checks.

## Main Flow

### 1. Initiative Setup
- Validate PRD exists and is properly structured
- Check that PRD Contract exists (generated in Phase 0.2.5)
- Verify pipeline structure matches PRD epics
- Set up monitoring for the initiative lifecycle

### 2. Epic Lifecycle Management
- Monitor each epic's progress through its phases
- Ensure proper task breakdown and assignment
- Track dependencies between epics
- Validate completion criteria before moving to next epic

### 3. Topology Validation (Phase 2 Enhancement)
Before dispatching any nodes, validate that the pipeline follows the required topology rules:

#### Topology Validation Steps:
- Verify every `codergen` cluster follows the full topology: `acceptance-test-writer -> research -> refine -> codergen -> wait.cobuilder[e2e] -> wait.human[e2e-review]`
- Ensure every `wait.human` node has exactly one predecessor (either `wait.cobuilder` or `research`)
- Confirm every `wait.cobuilder` node has at least one `codergen` or `research` predecessor
- Validate that all required gate pairs exist: each `codergen` should have a `wait.cobuilder` (automated validation) and `wait.human` (human review) sequence

#### Validation Failure Handling:
- If topology violations are detected, reject the pipeline with specific error messages
- Require pipeline re-generation or manual correction before proceeding
- Log topology violations to concerns queue for human review

### 3.5 SD Version Pinning Protocol
After refine nodes complete, implement version pinning for Solution Design documents:

#### SD Tagging Process:
- Git-tag the SD after refine node completes:
  ```bash
  git tag sd/{prd-id}/E{n}/v{version} -- docs/sds/{initiative}/SD-{id}.md
  ```
- Codergen node's `sd_ref` attribute points to the tag (not the file path):
  ```
  impl_e1 [handler="codergen" sd_ref="sd/HARNESS-UPGRADE-001/E1/v1"]
  ```
- `dispatch_worker.py` resolves the tag to file content at dispatch time:
  ```bash
  git show sd/HARNESS-UPGRADE-001/E1/v1:docs/sds/harness-upgrade/SD-...-E1-node-semantics.md
  ```
- Signal evidence includes `sd_hash` (SHA256 of the resolved content)

#### Naming Convention:
- Format: `sd/{prd-id}/E{epic}/v{version}` (e.g., `sd/HARNESS-UPGRADE-001/E1/v1`)
- Applied after refine nodes to freeze the SD version before codergen implementation

### 3.6 Skill-First Dispatch Table
Integrate skill injection into worker dispatches:

| Node Intent | Skill to Invoke | Injected via |
|-------------|----------------|-------------|
| Codergen (frontend) | `react-best-practices`, `frontend-design` | `skills_required` in agent definition |
| Codergen (backend) | `dspy-development` (if applicable) | `skills_required` in agent definition |
| Research (framework validation) | `research-first` | Runner injects into research worker prompt |
| Validation (E2E gate) | `acceptance-test-runner` | Runner calls directly |
| UX review | `website-ux-audit` | `skills_required` in ux-designer agent |
| Acceptance test creation | `acceptance-test-writer` | Runner injects into AT writer worker prompt |

### 3.7 Concern Queue Processing
Workers write concerns during execution to `{signal_dir}/concerns.jsonl`:

```json
{"ts": "2026-03-06T10:15:00Z", "node": "impl_e1", "severity": "warning", "message": "SD references v1.x API but installed version is v2.0", "suggestion": "Pin dependency or update SD"}
```

#### Processing at wait.cobuilder gates:
- **Critical**: blocks gate, transitions to `failed`, includes in summary
- **Warning**: includes in summary for human review
- **Info**: logged to Hindsight only

#### Signal Directory Requirement:
Document `ATTRACTOR_SIGNAL_DIR` env var as mandatory preflight check:
```bash
# In dispatch_worker.py
export ATTRACTOR_SIGNAL_DIR="${pipeline_dir}/signals/"
```

### 4. Validation Gate Processing
For each `wait.cobuilder` node in the pipeline:

#### Automated Gate Processing (wait.cobuilder)
The `wait.cobuilder` handler is executed by the Python runner (not LLM) and performs:
- Reads signal files from completed predecessor workers
- Processes concerns from `concerns.jsonl` for worker-raised issues
- Reflects via Hindsight (confidence trend, concern patterns)
- Runs Gherkin E2E tests — for browser-based tests, uses Chrome MCP tools (`mcp__claude-in-chrome__*`)
- Checks PRD Contract if `contract_ref` is set
- Writes gate summary to `summary_ref` path
- If critical concerns exist or tests fail: transitions to `failed` and may requeue predecessor codergen node back to `pending` (with retry counter, max 2 retries)
- If all pass: transitions to `validated`

##### Guardian Reflection Protocol at wait.cobuilder Gates
Instead of a separate sketch pre-flight concept, the guardian/runner reflects at the `wait.cobuilder` gate AFTER workers complete:

**Protocol** (executed by `_handle_gate()` in the runner):
1. Read all signal files from completed codergen workers in this epic cluster
2. Read `concerns.jsonl` for worker-raised concerns
3. Reflect via Hindsight: query confidence trend, previous gate results, and concern patterns
4. If critical concerns exist or confidence is declining:
   - Write summary explaining the issue
   - Transition `wait.cobuilder` to `failed`
   - Optionally: transition predecessor codergen node back to `pending` for retry (DOT graph update)
5. If no blockers: proceed with Gherkin E2E test execution
6. After E2E tests: write full summary to `summary_ref`

**Requeue mechanism**: When the runner decides a codergen node needs to rerun:
```python
# In _handle_gate() when gate fails and retry is warranted
transition_node(pipeline, predecessor_codergen_id, "pending")
save_checkpoint(dot_file, pipeline)
# Runner's next dispatch cycle will pick up the re-queued node
```

This keeps the retry logic inside the pipeline state machine — no external process needed.

##### Requeue Mechanism
When a `wait.cobuilder` node fails validation, it can transition the predecessor codergen node back to `pending`:
- Increment retry counter on the predecessor node
- If retry counter exceeds max (default 2), transition to `failed` permanently
- Write failure details to concerns queue for the next iteration
- Restart the codergen node for another implementation attempt

#### Standard Gate Processing
- Check prerequisite tasks are completed
- Validate artifact quality and completeness
- Assess readiness for next phase
- Generate gate summary report

#### Contract Validation (when contract_ref is set)
- Read the PRD Contract specified by contract_ref
- For each domain invariant: verify it holds in the current codebase
- For scope freeze: verify no files outside the frozen scope were modified
- For compliance flags: verify each flag's condition is met
- Score: contract compliance percentage (0.0-1.0)
- Include compliance assessment in gate summary

### 5. Human Review Gate Processing (wait.human)
For each `wait.human` node in the pipeline:

#### Human Review Gate Processing
- Reads summary from `summary_ref` (written by preceding `wait.cobuilder` or `research` node)
- Emits review request to GChat with summary content
- Blocks until human responds (signal file or GChat reply)
- Transitions to `validated` (approved) or `failed` (rejected)

### 6. Quality Assurance
- Run static analysis on code artifacts
- Verify test coverage meets minimum thresholds
- Check for adherence to architectural principles
- Validate compliance with PRD requirements

### 7. Completion and Handoff
- Verify all epics are completed
- Confirm all validation gates passed
- Generate final initiative report
- Prepare handoff documentation