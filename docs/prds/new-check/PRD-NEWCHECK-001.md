---
title: "PRD-NEWCHECK-001: New Check Page"
status: active
type: guide
grade: authoritative
last_verified: 2026-03-07T00:00:00.000Z
---
# PRD-NEWCHECK-001: New Check Page

## 1. Overview

Add a **New Check** page to the MyProject customer dashboard, accessible from the checks-dashboard via a prominent `+ New check` button in the top-right header. The page allows users to submit a background verification check for a candidate by filling out a structured form.

## 2. Business Goals

- Reduce friction for submitting new verification checks (currently requires navigating to the Voice Sandbox/aura-call page, which is intended for testing)
- Provide a clean, production-grade form UI matching the MyProject design system (Stitch design)
- Re-use the existing `POST /api/verify` backend endpoint — zero backend work required

## 3. Users & Use Cases

**Primary user**: HR Manager / Compliance Officer logged into MyProject dashboard

**Use case**: User is on checks-dashboard, wants to submit a new employment verification for a candidate. Clicks `+ New check`, fills out the form, submits.

## 4. Scope

### In Scope
- New Check form page at `/checks-dashboard/new`
- `+ New check` button in checks-dashboard header (top-right)
- Form with all fields matching Stitch design and aura-call page field parity
- Integration with existing `POST /api/verify` endpoint
- Success state (redirect to dashboard with toast or success message)
- Cancel action (navigate back to dashboard)
- Form validation (required fields)

### Out of Scope
- New backend endpoints (existing `/api/verify` is sufficient)
- "Schedule Work History" check type (future epic — render as disabled/coming soon)
- File uploads or attachments
- Multi-step wizard flow
- Mobile-first responsive redesign (existing dashboard breakpoints apply)

## 5. Form Fields (from Stitch design + aura-call parity)

### Check Selection (radio)
| Field | Type | Default |
| --- | --- | --- |
| Check Type | radio | "Work History" |

Options: `Work History` (active), `Schedule Work History` (disabled, coming soon)

### Candidate Details
| Field | Type | Required |
| --- | --- | --- |
| First Name | text | yes |
| Middle Name | text | no |
| Last Name | text | yes |
| Position / Role | text | yes |
| Start Date | text (YYYY-MM or MMM YYYY) | yes |
| End Date | text (YYYY-MM or MMM YYYY) | yes |
| Employment Type | select | no |
| Task ID | text | no (testing only) |

### Employer Details
| Field | Type | Required |
| --- | --- | --- |
| Employer Name | text | yes |
| Employer Website | url | no |
| Country | text | yes |
| City | text | no |
| Contact Person Name | text | no |
| Contact Phone Number | text | no |

### Additional Verification Points (checkboxes)
| Field | Default |
| --- | --- |
| Salary | unchecked |
| Supervisor | unchecked |
| Employment Type | checked |
| Rehire Eligibility | unchecked |
| Reason for Leaving | unchecked |

### Call Configuration (collapsible)
| Field | Type | Default |
| --- | --- | --- |
| Location | select | Singapore |
| Phone Type | select | Direct Contact |

## 6. API Integration

Submit to existing endpoint: `POST /api/verify`

Request body maps directly to aura-call's `handleCreateTask` payload:
```json
{
  "firstName", "middleName", "lastName",
  "employerName", "employerWebsite", "employerCountry", "employerCity",
  "contactPersonName", "contactPhoneNumber",
  "position", "startDate", "endDate",
  "verifyFields": { "salary": bool, "supervisor": bool, "employment_type": bool, "rehire_eligibility": bool, "reason_for_leaving": bool },
  "location", "phoneType",
  "agentType": "work-history-agent",
  "taskId"
}
```

On success: redirect to `/checks-dashboard` with success message.
On error: show inline error banner on the form.

## 7. Navigation

- Entry point: `+ New check` button in `/checks-dashboard/page.tsx` header (top-right)
- Route: `/checks-dashboard/new` (inherits `checks-dashboard/layout.tsx` — sidebar + shared nav)
- Cancel: navigate back to `/checks-dashboard`
- Success: navigate to `/checks-dashboard` (with success state passed via URL param or sessionStorage)

## 8. Epics

| Epic | Title | Bead | Description |
| --- | --- | --- | --- |
| E1 | New Check form page UI | my-project-0h4w | Create `/checks-dashboard/new/page.tsx` with full form matching Stitch design |
| E2 | Dashboard integration | my-project-afm7 | Add `+ New check` button to dashboard header, wire navigation |

## 9. Acceptance Criteria

- [ ] Navigating to `/checks-dashboard/new` renders the New Verification form
- [ ] `+ New check` button appears in top-right of checks-dashboard Overview header
- [ ] Clicking `+ New check` navigates to `/checks-dashboard/new`
- [ ] Form has all 5 sections matching Stitch design
- [ ] Required fields (First Name, Last Name, Position, Start Date, End Date, Employer Name, Country) are validated before submission
- [ ] Submitting a valid form calls `POST /api/verify` and redirects to `/checks-dashboard` on success
- [ ] Cancel button returns to `/checks-dashboard`
- [ ] Error from API is shown as inline error banner
- [ ] Page inherits checks-dashboard layout (sidebar + shared nav visible)
