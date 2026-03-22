---
title: "PRD-CASE-DATAFLOW-001: Work History Check Data Type Consistency"
description: "Enforce consistent data types across the entire case/check data flow from New Case creation through verification outcomes"
version: "2.0.0"
last-updated: 2026-03-20
status: active
type: prd
grade: authoritative
prd_id: PRD-CASE-DATAFLOW-001
---

# PRD-CASE-DATAFLOW-001: Work History Check Data Type Consistency

## 1. Problem Statement

The AgenCheck work history verification system has critical type inconsistencies across its 4-layer data flow. Type definitions evolved independently across the frontend form, API proxy, backend processing, and outcome storage — causing silent data loss, validation bypasses, and field mapping errors.

The root cause: the `/verify` API endpoint defines **its own inline Pydantic models** (Layer A) that are separate from the canonical storage models in `models/work_history.py` (Layer B), connected by a manual `_transform_to_metadata()` bridge that renames fields. There is no shared type contract between frontend and backend.

## 2. Canonical Data Schema

The `/verify` API endpoint's data model is the **single source of truth**. All other layers (frontend, storage, PostCheckProcessor) derive from it.

### 2.1 Enums

| Enum | Values | Used By |
|------|--------|---------|
| `CheckType` | `work_history`, `work_history_scheduling` | VerificationRequest |
| `EmploymentTypeEnum` | `full_time`, `part_time`, `contractor`, `casual` | EmploymentClaim |
| `EmploymentArrangementEnum` | `direct`, `agency`, `subcontractor` | EmploymentClaim |
| `EmploymentStatusEnum` | `verified`, `partial_verification`, `failed_verification`, `refused`, `unable_to_verify` | VerificationOutcome |
| `EligibilityForRehireEnum` | `yes`, `no`, `refused` | EmploymentClaim |
| `UnableToVerifyReasonEnum` | `voicemail`, `voicemail_max_retries`, `wrong_number`, `number_disconnected`, `business_closed`, `transferred_no_answer`, `callback_not_received`, `other` | VerificationOutcome |
| `ClientTypeEnum` | `company` (B2B, has client_id, custom SLA), `individual` (B2C, default config) | EmployerInfo |

### 2.2 Input Models (API Contract)

```python
class CandidateInfo(BaseModel):
    first_name: str                                  # required, 1-100 chars
    middle_name: Optional[str]                       # optional, max 100
    last_name: str                                   # required, 1-100 chars
    email: Optional[str]                             # max 255
    phone: Optional[str]                             # max 50
    job_title: Optional[str]                         # max 255
    start_date: Optional[str]                        # YYYY-MM-DD
    end_date: Optional[str]                          # YYYY-MM-DD or null

class EmployerContactPerson(BaseModel):
    """A contact at the employer — could be HR, Payroll, Finance, CEO, etc."""
    contact_name: Optional[str]                      # max 255
    department: Optional[str]                        # max 255
    position: Optional[str]                          # max 255
    email: Optional[str]                             # max 254
    phone: Optional[str]                             # max 50, international format
    is_primary: bool = False

class EmployerInfo(BaseModel):
    employer_company_name: str                       # required
    employer_website_url: Optional[str]              # optional (not all companies have websites)
    country_code: str                                # required, ISO 3166-1 alpha-2 ("AU", "SG")
    phone_numbers: List[str]                         # 1-5 numbers, required
    contacts: List[EmployerContactPerson]            # [0] = primary, [1:] = additional
    external_reference: Optional[str]                # client's internal ID (Epic 9)
    client_type: ClientTypeEnum = ClientTypeEnum.COMPANY

class EmploymentClaim(BaseModel):
    """All fields that can be verified. /verify-check page displays these."""
    start_date: str                                  # YYYY-MM-DD, required
    end_date: Optional[str]                          # YYYY-MM-DD or null
    position_title: str                              # required
    supervisor_name: Optional[str]
    employment_type: Optional[EmploymentTypeEnum]
    employment_arrangement: Optional[EmploymentArrangementEnum] = "direct"
    agency_name: Optional[str]                       # required if arrangement != direct
    salary_amount: Optional[str]                     # numeric string, e.g. "85000"
    salary_currency: Optional[str]                   # ISO 4217, auto-derived from country_code
    eligibility_for_rehire: Optional[EligibilityForRehireEnum]
    reason_for_leaving: Optional[str]

class VerifyFields(BaseModel):
    """Which fields to verify during the call."""
    employment_dates: bool = True                    # always on
    position_title: bool = True                      # always on
    supervisor_name: bool = False
    employment_type: bool = False
    employment_arrangement: bool = False
    eligibility_for_rehire: bool = False
    reason_for_leaving: bool = False
    salary: bool = False                             # when True, checks both amount + currency

class VerificationRequest(BaseModel):
    """POST /api/v1/verify — THE central API contract."""
    candidate: CandidateInfo
    employer: EmployerInfo
    employment: Optional[EmploymentClaim]
    verify_fields: Optional[VerifyFields]
    check_type: CheckType = CheckType.WORK_HISTORY
    preferred_timezone: Optional[str]                # IANA format
    notes: Optional[str]                             # max 1000
    client_id: Optional[int]                         # SLA tier override FK
```

### 2.3 Storage Models (JSONB)

```python
class WorkHistoryVerificationMetadata(BaseModel):
    """cases.verification_metadata — structural pass-through, no field renaming."""
    employer: EmployerInfo
    employment: EmploymentClaim
    verify_fields: VerifyFields
```

### 2.4 Output Models (Verification Results)

```python
class VerifiedField(BaseModel):
    """One entry per checked field."""
    claimed: Optional[str]
    verified: str
    match: Optional[bool]

class VerifierInfo(BaseModel):
    """Person who provided verification — not necessarily HR."""
    name: Optional[str]
    title: Optional[str]
    department: Optional[str]

class VerificationOutcome(BaseModel):
    """cases.verification_results — produced by PostCheckProcessor."""
    was_employed: bool
    employment_status: EmploymentStatusEnum
    verified_data: Dict[str, VerifiedField]          # keyed by field name
    verifier: Optional[VerifierInfo]
    unable_to_verify_reason: Optional[UnableToVerifyReasonEnum]
    confidence: float                                # 0.0-1.0
    supporting_quotes: List[str]
    verified_at: datetime
```

### 2.5 JSONB Write/Read Contract

| Column | Model | Write | Read |
|--------|-------|-------|------|
| `background_tasks.context_data` | `VerificationRequest` | `model_dump(mode="json")` | `VerificationRequest.model_validate()` |
| `cases.verification_metadata` | `WorkHistoryVerificationMetadata` | `model_dump(mode="json")` | `WorkHistoryVerificationMetadata.model_validate()` |
| `cases.verification_results` | `VerificationOutcome` | `model_dump(mode="json")` | `VerificationOutcome.model_validate()` |

### 2.6 Standards

| Domain | Standard | Library |
|--------|----------|---------|
| Country codes | ISO 3166-1 alpha-2 | `pycountry` |
| Currency codes | ISO 4217 | `babel.numbers.get_territory_currencies()` |
| Phone numbers | International format, `^[+\-()0-9\s]{5,50}$` | Regex (aligned with ContactRecord) |
| Date format | `YYYY-MM-DD` | Zod regex + Pydantic validator |

### 2.7 Salary Verification Produces Two VerifiedField Entries

When `VerifyFields.salary=True`, the PostCheckProcessor produces:
- `verified_data["salary_amount"]` = `VerifiedField(claimed="85000", verified="82000", match=False)`
- `verified_data["salary_currency"]` = `VerifiedField(claimed="AUD", verified="AUD", match=True)`

The `/verify-check` page displays salary amount and currency as separate fields.

## 3. Target Repository

**Codebase**: `my-org/my-project`
- Frontend: `my-project-frontend/` (Next.js, TypeScript, shadcn/ui)
- Backend: `my-project-backend/` (FastAPI, Pydantic, Python)

## 4. Scope

### In Scope
- Consolidate all Pydantic models into canonical module (eliminate router-inline duplicates)
- Implement ISO 3166/4217 with `pycountry`/`babel`
- Upgrade frontend form with proper shadcn components
- Align /verify-check form with all EmploymentClaim fields
- Unify PostCheckProcessor outcome production paths
- Generate TypeScript types from Pydantic via pre-push hook
- Add `EmployerContactPerson` list aligned with `AdditionalContact` model
- Remove `CustomerAgreement` from schema
- Remove `default_sla` column from `check_types` table
- Ensure all JSONB reads use `Model.model_validate()`

### Out of Scope
- New check types beyond work_history
- Prefect flow restructuring
- Voice agent internal refactoring (only the interface contract)
- LiveKit integration changes
- Renaming university_contacts → contacts (separate initiative)

## 5. Epics

### Epic 1: Canonical Type Definitions & ISO Standards (Backend)
**Priority**: P0 — Foundation for all other epics

Consolidate all Pydantic models, add ISO country/currency support, create TypeScript generation.

**Key deliverables**:
- Move router-inline `CandidateInfo`, `EmployerInfo` into `models/work_history.py`
- Add `EmployerContactPerson` model aligned with `AdditionalContact`
- Add `middle_name` to `CandidateInfo`
- Add `country_code` (ISO 3166-1 alpha-2, mandatory) with `pycountry` validation
- Add `salary_amount` + `salary_currency` (ISO 4217 via `babel`)
- Add `employment_arrangement` to `VerifyFields`
- Move `phone_numbers` into `EmployerInfo`
- Make `employer_website_url` optional
- Remove `CustomerAgreement` from schema
- Remove `hr_contact_name`/`hr_email` fields (replaced by `contacts[0]`)
- Eliminate `_transform_to_metadata()` field renaming
- DB migration: remove `default_sla` from `check_types` table
- Create TypeScript generation script + git pre-push hook
- Create `outcome_converter.py` for PostCheckProcessor alignment

**Acceptance Criteria**:
- [ ] Single canonical module, no duplicate model definitions
- [ ] ISO country validation via `pycountry`
- [ ] Currency auto-derived from country via `babel`
- [ ] TypeScript types generated and match Pydantic models
- [ ] Pre-push hook runs generation script and fails on drift
- [ ] `contacts[0]` = primary contact, writes to table columns; `contacts[1:]` writes to `additional_contacts` JSONB
- [ ] `default_sla` removed from `check_types` table
- [ ] All existing tests pass

### Epic 2: Frontend Form — shadcn Component Upgrade
**Priority**: P1 — Depends on Epic 1

Replace raw HTML inputs with shadcn components, wire to generated TypeScript types.

**Key deliverables**:
- shadcn `DatePicker` (Calendar + Popover) for start/end dates
- shadcn `Combobox` for country (ISO alpha-2, display full name)
- Fix Employment Type options: `contractor` (not `contract`), add `casual`
- Add Employment Arrangement select + conditional Agency Name
- Add `middle_name` field
- Add salary currency field (auto-derived, displayed separately)
- Support multiple contacts (add/remove contact persons)
- Update Zod schema with date regex, use generated TypeScript types

### Epic 3: API Proxy Contract Alignment (Frontend)
**Priority**: P1 — Depends on Epic 1

Fix route.ts to pass through canonical types without field renaming.

**Key deliverables**:
- Replace inline `FrontendVerifyFields` with imported canonical types
- Pass `contacts` list (not single contact_name/email)
- Pass `country_code` (alpha-2, not full name)
- Pass `salary_amount` + `salary_currency` separately
- Pass `employment_arrangement` and `agency_name`
- Add date format validation
- Import canonical TypeScript types

### Epic 4: PostCheckProcessor Type Alignment (Backend)
**Priority**: P1 — Depends on Epic 1

Unify outcome production paths using canonical types.

**Key deliverables**:
- Create `outcome_converter.py` (PostCheckProcessor result → canonical `VerificationOutcome`)
- Fix `was_employed` to use only valid `EmploymentStatusEnum` values
- Salary verification produces two `VerifiedField` entries (amount + currency)
- All JSONB reads use `Model.model_validate()` not raw dict access
- Field name validation in outcome builder
- Converge `VerifiedField` to single Pydantic model

## 6. Dependency Graph

```
Epic 1 (Canonical Types + ISO)
  ├──→ Epic 2 (Frontend Form)
  ├──→ Epic 3 (API Proxy)
  └──→ Epic 4 (PostCheckProcessor)
```

## 7. Key File Map

| Layer | File | Purpose |
|-------|------|---------|
| Canonical Models | `my-project-backend/models/work_history.py` | Single source of truth |
| Contact Models | `my-project-backend/models/contacts.py` | AdditionalContact, EmployerContact |
| Backend Router | `my-project-backend/api/routers/work_history.py` | /api/v1/verify (imports from canonical) |
| Case Service | `my-project-backend/helpers/work_history_case.py` | Case creation + JSONB writes |
| Outcome Builder | `my-project-backend/live_form_filler/services/outcome_builder.py` | Live Form Filler → VerificationOutcome |
| DB Writer | `my-project-backend/live_form_filler/services/database_writer.py` | Write outcomes to cases table |
| PostCheckProcessor | `my-project-backend/prefect_flows/flows/tasks/process_post_call.py` | Transcript → VerificationOutcome |
| Frontend Form | `my-project-frontend/app/checks-dashboard/new/page.tsx` | New Case form |
| Frontend Proxy | `my-project-frontend/app/api/verify/route.ts` | Field mapping to backend |
| TS Types | `my-project-frontend/lib/types/work-history.generated.ts` | Auto-generated from Pydantic |

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| E1: Canonical Types + ISO | Remaining | - | - |
| E2: Frontend Form shadcn | Remaining | - | - |
| E3: API Proxy Contract | Remaining | - | - |
| E4: PostCheckProcessor Alignment | Remaining | - | - |
