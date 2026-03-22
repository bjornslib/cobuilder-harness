# Validation Request Protocol (F4.3)

**PRD**: PRD-S3-AUTONOMY-001, Epic 4, Feature 4.3
**Version**: 1.0.0
**Status**: Implemented

---

## Overview

This protocol defines the standard message format for validation requests between System 3 (or orchestrators) and `s3-validator` teammates. It enables structured, correlatable validation workflows where requests and responses are matched by `task_id`.

## Message Flow

```
System 3                          s3-validator
   │                                   │
   │  SendMessage(content=request_json) │
   │ ─────────────────────────────────►│
   │                                   │── Parse request
   │                                   │── Validate each criterion
   │                                   │── Collect evidence
   │  SendMessage(content=response_json)│
   │◄───────────────────────────────── │
   │                                   │── Exit
   │  Correlate by task_id             ✕
   │  Apply verdict
```

## Transport

Validation requests and responses are carried as **JSON strings within the `content` field of `SendMessage`**. The validator parses the JSON from its initial prompt (for the request) and sends the response JSON via `SendMessage` to `team-lead`.

```python
# System 3 sends request via Task initial prompt
Task(
    subagent_type="validation-test-agent",
    team_name="s3-epic4-oversight",
    name="s3-validator-task-123",
    model="sonnet",
    prompt=f"""You are s3-validator-task-123.

    ## Validation Request
    ```json
    {json.dumps(validation_request)}
    ```

    Validate each criterion. Report results as JSON via SendMessage to team-lead.
    Exit after reporting.
    """
)

# Validator sends response via SendMessage
SendMessage(
    type="message",
    recipient="team-lead",
    content=json.dumps(validation_response),
    summary=f"Validation {verdict} for {task_id}"
)
```

## Request Schema

**Schema file**: `schemas/validation-request.schema.json`

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Beads task ID being validated |
| `validation_type` | enum | `code`, `browser`, or `both` |
| `acceptance_criteria` | array | List of criteria to validate against |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `prd_id` | string | PRD identifier (e.g., PRD-S3-AUTONOMY-001) |
| `claimed_evidence` | object | Orchestrator's claimed proof |
| `worktree_path` | string | Path to git worktree |
| `branch` | string | Git branch name |
| `services` | object | Required services (URLs, ports) |
| `focus_areas` | array | Priority areas for validation |
| `timeout_seconds` | integer | Max validation time (default 300) |

### Example Request

```json
{
  "task_id": "claude-harness-setup-5j8t",
  "prd_id": "PRD-S3-AUTONOMY-001",
  "validation_type": "code",
  "acceptance_criteria": [
    {
      "id": "F4.1-1",
      "description": "System 3 can spawn s3-validator on-demand via TeamCreate + Task",
      "validation_hint": "Check skills/system3-orchestrator/references/validation-workflow.md"
    },
    {
      "id": "F4.1-2",
      "description": "s3-validator reports results via SendMessage and exits gracefully",
      "validation_hint": "Check spawn prompt includes SendMessage + exit instructions"
    }
  ],
  "claimed_evidence": {
    "summary": "Added on-demand validator spawn pattern to validation-workflow.md and oversight-team.md",
    "files_modified": [
      ".claude/skills/system3-orchestrator/references/validation-workflow.md",
      ".claude/skills/system3-orchestrator/references/oversight-team.md",
      ".claude/skills/system3-orchestrator/SKILL.md"
    ]
  },
  "worktree_path": "$CLAUDE_PROJECT_DIR
  "branch": "epic4-validation-teammate"
}
```

## Response Schema

**Schema file**: `schemas/validation-response.schema.json`

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | MUST match request task_id (correlation key) |
| `verdict` | enum | `PASS`, `FAIL`, `PARTIAL`, `BLOCKED` |
| `criteria_results` | array | Per-criterion pass/fail with evidence |
| `timestamp` | datetime | ISO 8601 completion timestamp |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `evidence_collected` | object | Screenshots, test results, API responses, file checks |
| `reasoning` | string | Overall assessment |
| `confidence` | number | 0.0-1.0 confidence in verdict |
| `duration_seconds` | number | Validation duration |
| `validator_id` | string | Agent name (e.g., s3-validator-task-123) |

### Verdict Semantics

| Verdict | Meaning | System 3 Action |
|---------|---------|-----------------|
| `PASS` | All criteria verified | Proceed to Gate 3 (cs-verify), then close task |
| `FAIL` | One or more criteria not met | Send failures to orchestrator, do NOT close |
| `PARTIAL` | Some pass, some fail | Review failures, decide: fix or accept |
| `BLOCKED` | Cannot validate (services down, files missing) | Resolve blockers, retry validation |

### Example Response

```json
{
  "task_id": "claude-harness-setup-5j8t",
  "verdict": "PASS",
  "criteria_results": [
    {
      "criterion_id": "F4.1-1",
      "status": "PASS",
      "evidence": "validation-workflow.md contains 'On-Demand Validation Teammate' section with Task spawn pattern including team_name and name parameters"
    },
    {
      "criterion_id": "F4.1-2",
      "status": "PASS",
      "evidence": "Spawn prompt includes 'Report results via SendMessage to team-lead' and 'Exit after reporting'"
    }
  ],
  "evidence_collected": {
    "file_checks": [
      {
        "path": ".claude/skills/system3-orchestrator/references/validation-workflow.md",
        "exists": true,
        "size_bytes": 15234,
        "contains_expected": true,
        "note": "Contains on-demand spawn pattern with parallel validator support"
      }
    ]
  },
  "reasoning": "All F4.1 acceptance criteria are documented with concrete code examples, parallel patterns, and lifecycle diagrams. The spawn pattern correctly uses team_name + name parameters and includes SendMessage reporting.",
  "confidence": 0.9,
  "duration_seconds": 45.2,
  "timestamp": "2026-02-17T14:30:00Z",
  "validator_id": "s3-validator-claude-harness-setup-5j8t"
}
```

## Correlation Pattern

System 3 correlates requests and responses by `task_id`:

```python
# System 3 dispatches validation request
pending_validations = {}
pending_validations[task_id] = {
    "request": validation_request,
    "validator_name": f"s3-validator-{task_id}",
    "dispatched_at": datetime.now()
}

# When SendMessage arrives from validator:
response = json.loads(message.content)
request = pending_validations.get(response["task_id"])

if request and response["verdict"] == "PASS":
    # Proceed to Gate 3: cs-verify
    Bash(f"cs-verify --promise {promise_id} --type api --proof '{response['reasoning']}'")
    Bash(f"bd close {response['task_id']}")
elif response["verdict"] == "FAIL":
    # Extract failures and route to orchestrator
    failures = [r for r in response["criteria_results"] if r["status"] == "FAIL"]
    # Send failure details to orchestrator
```

## Integration with Triple-Gate Validation

This protocol serves as **Gate 2** in the triple-gate validation chain:

```
Gate 1: Session completion promise (cs-promise)
  ↓ Session claims work is done
Gate 2: s3-validator via this protocol (F4.1 + F4.3)
  ↓ Independent verification with structured evidence
Gate 3: cs-verify programmatic judge (F4.2 — Anthropic SDK)
  ↓ Sonnet 4.5 evaluates promise + evidence + validator verdict
```

## Relationship to Existing Schemas

| Schema | Purpose | Relationship |
|--------|---------|-------------|
| `validation/verdict-schema.json` | Validation-agent unit/e2e output | **Complementary** — used by orchestrator-level validation |
| `schemas/validation-request.schema.json` | S3→validator request format | **NEW** — this protocol |
| `schemas/validation-response.schema.json` | Validator→S3 response format | **NEW** — this protocol |
| `validation/evidence-templates.md` | Evidence capture templates | **Referenced** — validators follow these templates |

## Storage and Enforcement (Gate 2 Trigger)

After receiving a validation response from an s3-validator teammate, System 3 must store the response and then proceed through the triple-gate chain:

### Step 1: Store Validation Response

```bash
# Store the validator's response linked to a specific promise + AC
cs-store-validation --promise <promise-id> --ac-id <AC-X> --response '<validation-response-json>'

# Or from a file
cs-store-validation --promise <promise-id> --ac-id <AC-X> --response-file /path/to/response.json
```

**Storage location**: `.claude/completion-state/validations/{promise-id}/{ac-id}-validation.json`

### Step 2: Mark AC as Met (if validator PASSED)

```bash
# Only after validator confirms PASS for this criterion
cs-promise --meet <promise-id> --ac-id <AC-X> --evidence "Validator PASS: <summary>" --type api
```

### Step 3: Verify Promise (Triggers Gate 2 + Gate 3)

```bash
# Gate 1: All ACs marked as "met" (checked first)
# Gate 2: All ACs have PASS/PARTIAL validation responses (enforced by cs-verify)
# Gate 3: LLM programmatic judge evaluates evidence + validator findings (optional)
cs-verify --promise <promise-id> --llm-verify
```

### Gate 2 Enforcement Behavior

| Scenario | cs-verify Behavior |
|----------|--------------------|
| All ACs have PASS validation responses | Gate 2 passes, proceeds to Gate 3 |
| Any AC missing a validation response | **BLOCKS** with actionable error |
| Any AC has FAIL validation response | **BLOCKS** with remediation details |
| Any AC has BLOCKED validation response | **BLOCKS** with reasoning |
| PARTIAL verdict | Treated as PASS (System 3 decides acceptability) |
| Legacy promise (no ACs) | Gate 2 skipped entirely |
| `--skip-validation-check` flag | Gate 2 bypassed with WARNING |

### Override: Skip Validation Check

For edge cases where validation enforcement should be bypassed:

```bash
# WARNING: This skips Gate 2 — use only when justified
cs-verify --promise <promise-id> --skip-validation-check --proof "Reason for skipping validation"
```

A warning is logged to stderr when this flag is used.

### Complete Workflow Example

```python
# 1. Orchestrator signals impl_complete
# 2. System 3 dispatches s3-validator
validator_response = await_validator_result()

# 3. Store the response
Bash(f"cs-store-validation --promise {promise_id} --ac-id {ac_id} --response '{json.dumps(validator_response)}'")

# 4. Mark AC as met (if PASS)
if validator_response["verdict"] == "PASS":
    Bash(f"cs-promise --meet {promise_id} --ac-id {ac_id} --evidence 'Validator PASS' --type api")

# 5. When all ACs met + all validations stored:
Bash(f"cs-verify --promise {promise_id} --llm-verify")
# Gate 1: checks all ACs are "met"
# Gate 2: checks all validation responses are PASS/PARTIAL
# Gate 3: LLM judge cross-validates evidence + validator findings
```

---

**Version**: 1.1.0
**Source**: PRD-S3-AUTONOMY-001 Epic 4, Feature 4.3
