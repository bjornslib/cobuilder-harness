---
title: "SD-CASE-DATAFLOW-001-E4: PostCheckProcessor Type Alignment"
description: "Unify the PostCheckProcessor outcome paths using canonical Pydantic types and model_validate() for JSONB safety"
version: "2.0.0"
last-updated: 2026-03-20
status: active
type: sd
grade: authoritative
prd_ref: PRD-CASE-DATAFLOW-001
---

# SD-CASE-DATAFLOW-001-E4: PostCheckProcessor Type Alignment

## 1. Overview

Unify the two outcome production paths (Live Form Filler and voice agent transcript processing) to both produce canonical `VerificationOutcome` objects. Ensure all JSONB reads use `Model.model_validate()`.

**Target**: `agencheck-support-agent/`
**Worker Type**: `backend-solutions-engineer`
**Depends On**: Epic 1 (canonical types + outcome_converter.py)

## 2. Two Paths, One Output

### Path A: Live Form Filler
```
FormSubmissionRequest → outcome_builder.build_verification_outcome()
→ VerificationOutcome → database_writer.write_verification_to_case()
```

### Path B: Voice Agent Transcript
```
stream_message → PostCheckProcessor → PostCheckResult
→ outcome_converter.postcall_result_to_outcome()
→ VerificationOutcome → process_call_result (Prefect task)
```

Both paths must produce identical `VerificationOutcome` instances.

## 3. Key Changes

### 3.1 outcome_converter.py (Created in Epic 1)

Handles:
- Dataclass `VerifiedField` → Pydantic `VerifiedField` conversion
- Legacy status values (`"currently_employed"` → `VERIFIED`)
- `was_employed` derived from valid `EmploymentStatusEnum` only
- Salary split: if `claimed_data` has `salary_amount` + `salary_currency`, produce two `VerifiedField` entries

### 3.2 Update process_post_call.py

Rename references from PostCallProcessor to PostCheckProcessor in comments/logs.

Replace manual dict building (lines 344-374) with:
```python
from models.outcome_converter import postcall_result_to_outcome

canonical_outcome = postcall_result_to_outcome(result.outcome)
return canonical_outcome.model_dump(mode="json")
```

### 3.3 Update outcome_builder.py

- Validate `field_name` against known verification field names
- When `salary` is verified, produce both `salary_amount` and `salary_currency` entries:
```python
if field_name == "salary":
    # Split into amount + currency
    verified_data["salary_amount"] = VerifiedField(
        claimed=claimed.get("salary_amount"),
        verified=verified_value,
        match=...
    )
    verified_data["salary_currency"] = VerifiedField(
        claimed=claimed.get("salary_currency"),
        verified=claimed.get("salary_currency", ""),  # verifier usually doesn't state currency
        match=True  # assume currency matches unless explicitly stated otherwise
    )
```

### 3.4 JSONB Read Safety — All Reads via model_validate()

Audit and fix all places that read JSONB columns:

| File | Current Read Pattern | Fixed Pattern |
|------|---------------------|---------------|
| `work_history.py` (router, GET endpoint) | `json.loads(row["context_data"])` → raw dict | `VerificationRequest.model_validate(json.loads(...))` |
| `process_post_call.py` | `stream_message.get("candidate_info", {})` → raw dict | Type via canonical model where possible |
| `database_writer.py` | Already uses `VerificationOutcome` | Verify type hints correct |
| `/verify-check` frontend | Reads from API response | TypeScript types enforce shape |

### 3.5 Rename PostCallProcessor References

In comments, log messages, and variable names: `PostCallProcessor` → `PostCheckProcessor`, `post_call` → `post_check` where it refers to the generic check processing (not the specific call step).

## 4. Files to Modify

| File | Action |
|------|--------|
| `prefect_flows/flows/tasks/process_post_call.py` | MODIFY — use outcome_converter, rename references |
| `live_form_filler/services/outcome_builder.py` | MODIFY — salary split, field validation |
| `live_form_filler/services/database_writer.py` | VERIFY — type hints |
| `api/routers/work_history.py` (GET endpoints) | MODIFY — JSONB reads via model_validate() |

## 5. Test Strategy

1. Unit: outcome_converter produces valid VerificationOutcome from dataclass input
2. Unit: salary verification produces two VerifiedField entries
3. Unit: `was_employed` only uses valid enum values
4. Integration: both paths produce identical JSON schema when serialized
5. Integration: JSONB round-trip (write → read → model_validate) for all three columns

## Implementation Status

| Task | Status | Date | Commit |
|------|--------|------|--------|
| Update process_post_call.py | Remaining | - | - |
| Update outcome_builder.py | Remaining | - | - |
| Audit JSONB reads | Remaining | - | - |
| Rename PostCall → PostCheck | Remaining | - | - |
| Salary split logic | Remaining | - | - |
