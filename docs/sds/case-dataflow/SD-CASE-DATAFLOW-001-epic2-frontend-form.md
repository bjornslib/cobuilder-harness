---
title: "SD-CASE-DATAFLOW-001-E2: Frontend Form — shadcn Component Upgrade"
description: "Upgrade New Case form with shadcn components, ISO standards, multiple contacts, and canonical TypeScript types"
version: "2.0.0"
last-updated: 2026-03-20
status: active
type: sd
grade: authoritative
prd_ref: PRD-CASE-DATAFLOW-001
---

# SD-CASE-DATAFLOW-001-E2: Frontend Form — shadcn Component Upgrade

## 1. Overview

Replace raw HTML inputs with proper shadcn/ui components, wire to generated TypeScript types, support ISO country codes, salary currency, and multiple employer contacts.

**Target**: `agencheck-support-frontend/`
**Worker Type**: `frontend-dev-expert`
**Depends On**: Epic 1 (TypeScript types at `lib/types/work-history.generated.ts`)

## 2. Components to Install

```bash
npx shadcn@latest add calendar popover command
npm install date-fns pycountry-data  # or use bundled country list from generated types
```

## 3. Key Changes

### 3.1 Date Fields → shadcn DatePicker

Replace `<Input type="date">` with `DatePicker` component (Calendar + Popover). Must output `YYYY-MM-DD` strings.

### 3.2 Country → shadcn Combobox (ISO alpha-2)

Replace `<Input>` with Combobox. Displays full country name, stores ISO 3166-1 alpha-2 code. Include the country list in generated TypeScript types from Epic 1 (derived from `pycountry` at generation time).

### 3.3 Employment Type — Fix Values

Replace `contract` with `contractor`, add `casual`:
```
full_time | part_time | contractor | casual
```

### 3.4 Employment Arrangement — New Field

Add `<Select>` with: `direct`, `agency`, `subcontractor`. Show conditional `Agency Name` input for agency/subcontractor.

### 3.5 middle_name — New Field

Add between first_name and last_name in the 3-column grid.

### 3.6 Salary — Amount + Currency Separate Fields

When `salary` verify field is checked:
- `salary_amount`: `<Input>` for numeric value (e.g., "85000")
- `salary_currency`: `<Select>` auto-populated from country_code, editable. ISO 4217 values.

### 3.7 Multiple Contacts

Replace single `contactPersonName` / `contactEmail` / `contactPhoneNumber` fields with a dynamic contact list:
- First contact is primary (always shown)
- "Add Contact" button adds additional contacts
- Each contact: name, department, position, email, phone
- Align with `EmployerContactPerson` from generated types

### 3.8 Updated Zod Schema

Import generated types. Add:
- Date regex: `/^\d{4}-\d{2}-\d{2}$/`
- country_code: 2-char uppercase
- salary_currency: 3-char uppercase when salary enabled
- Agency name required when arrangement != direct
- At least one contact must have a name or email

### 3.9 Verify Fields — Add Employment Arrangement

Add checkbox for `employment_arrangement` in the Additional Verification Points section.

## 4. Files to Modify/Create

| File | Action |
|------|--------|
| `components/ui/date-picker.tsx` | CREATE |
| `components/ui/country-combobox.tsx` | CREATE |
| `components/ui/contact-person-list.tsx` | CREATE — dynamic add/remove contacts |
| `app/checks-dashboard/new/page.tsx` | MAJOR MODIFY — all form fields |

## Implementation Status

| Task | Status | Date | Commit |
|------|--------|------|--------|
| Install shadcn deps | Remaining | - | - |
| DatePicker component | Remaining | - | - |
| CountryCombobox component | Remaining | - | - |
| ContactPersonList component | Remaining | - | - |
| Update form page | Remaining | - | - |
| Update Zod schema | Remaining | - | - |
