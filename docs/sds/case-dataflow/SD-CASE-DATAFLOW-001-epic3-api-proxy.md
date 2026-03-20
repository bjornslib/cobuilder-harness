---
title: "SD-CASE-DATAFLOW-001-E3: API Proxy Contract Alignment"
description: "Fix frontend API proxy to pass through canonical types without field renaming"
version: "2.0.0"
last-updated: 2026-03-20
status: active
type: sd
grade: authoritative
prd_ref: PRD-CASE-DATAFLOW-001
---

# SD-CASE-DATAFLOW-001-E3: API Proxy Contract Alignment

## 1. Overview

Fix `app/api/verify/route.ts` to pass canonical types straight through to the backend without field renaming. Import generated TypeScript types.

**Target**: `agencheck-support-frontend/app/api/verify/route.ts`
**Worker Type**: `frontend-dev-expert`
**Depends On**: Epic 1 (TypeScript types), Epic 2 (form field additions)

## 2. Key Changes

### 2.1 Import Canonical Types

```typescript
import type {
  VerificationRequest, CandidateInfo, EmployerInfo,
  EmployerContactPerson, EmploymentClaim, VerifyFields,
} from "@/lib/types/work-history.generated";
```

Remove the inline `FrontendVerifyFields` interface.

### 2.2 Verify Fields — Direct Pass-Through

No more `supervisor` → `supervisor_name` mapping. The frontend form now uses canonical field names:
```typescript
const backendVerifyFields: VerifyFields = {
    employment_dates: true,
    position_title: true,
    salary: verifyFields.salary ?? false,
    supervisor_name: verifyFields.supervisor_name ?? false,
    employment_type: verifyFields.employment_type ?? false,
    employment_arrangement: verifyFields.employment_arrangement ?? false,
    eligibility_for_rehire: verifyFields.eligibility_for_rehire ?? false,
    reason_for_leaving: verifyFields.reason_for_leaving ?? false,
};
```

### 2.3 Employer — Contacts List + country_code

```typescript
employer: {
    employer_company_name: employerName,
    employer_website_url: employerWebsite || undefined,
    country_code: countryCode,                    // ISO alpha-2, not full name
    phone_numbers: phoneNumbers,                  // moved here from top level
    contacts: contacts,                           // List[EmployerContactPerson]
    external_reference: undefined,
    client_type: "company",
},
```

No more `contact_name` → `hr_contact_name` renaming. No more `contact_email` → `hr_email` renaming. The field names are the same end-to-end.

### 2.4 Employment — Salary Split + Arrangement

```typescript
employment: {
    start_date: normalizedStart,
    end_date: normalizedEnd || undefined,
    position_title: position,
    supervisor_name: supervisorName || undefined,
    employment_type: employmentType || undefined,
    employment_arrangement: employmentArrangement || undefined,
    agency_name: agencyName || undefined,
    salary_amount: salaryAmount || undefined,
    salary_currency: salaryCurrency || undefined,   // auto-derived or user-selected
    eligibility_for_rehire: undefined,              // not known at submission
    reason_for_leaving: undefined,                  // not known at submission
},
```

### 2.5 Candidate — Add middle_name

```typescript
candidate: {
    first_name: firstName,
    middle_name: middleName || undefined,
    last_name: lastName,
    job_title: position,
    start_date: normalizedStart,
    end_date: normalizedEnd || undefined,
},
```

### 2.6 Date Format Validation

```typescript
const DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;
if (startDate && !DATE_REGEX.test(startDate)) {
    return NextResponse.json({ error: "Invalid startDate format" }, { status: 400 });
}
```

## 3. Files to Modify

| File | Changes |
|------|---------|
| `app/api/verify/route.ts` | Complete rewrite of field mapping, import canonical types |

## Implementation Status

| Task | Status | Date | Commit |
|------|--------|------|--------|
| Import canonical types | Remaining | - | - |
| Fix field mapping | Remaining | - | - |
| Add new fields | Remaining | - | - |
| Date validation | Remaining | - | - |
