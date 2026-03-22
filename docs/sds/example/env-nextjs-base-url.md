---
title: "SD: Add NEXTJS_BASE_URL, Update Email Templates, and Fix Variable Naming"
status: active
type: reference
epic_id: MODEL-MIGRATION-001
prd_ref: MyProject Configuration Consolidation
last_verified: 2026-03-11
---

## Overview

Three changes to the employment verification email system:

1. **Add `NEXTJS_BASE_URL`** env var and include three CTAs in all email templates:
   - Online verification form: `{check_verification_url}`
   - Direct call: `{callback_number}`
   - Schedule a callback: `{schedule_callback_url}`

2. **Fix variable naming** — current names are semantically backwards:
   - `{contact_name}` (employer HR person) → rename to `{verifier_name}` (they ARE the verifier)
   - `{verifier_name}` ("MyProject Team") → rename to `{agent_name}` (it's our agent, not a verifier)

3. **Fix `days_elapsed` bug** — `email_reminder_2.txt` uses `{days_elapsed}` but code never provides it.

The online verification form is the unified page with chat + voice agent (LiveKit). This is the actual verification interface for employer HR contacts, NOT a status page.

## Research Findings (Verified 2026-03-11)

### Email Template Rename Safety

**Context:** Research validated the safety of renaming template variables (e.g., `initial_contact.html` → `initial-contact.html`).

#### Architecture Analysis
The current email template system is **designed for flexibility** with low renaming risk:

| Reference Type | File | Risk Level |
|----------------|------|------------|
| Documentation examples | Static paths in README/docs | Low (updated via find/replace) |
| Python code | Dynamic filename from args | Very Low (no hardcoded names) |
| Test files | Method names | None (not affected by rename) |

#### Current Template Files
Location: `my-project-communication/email-templates/`

| Template | Purpose |
|----------|---------|
| `initial_contact.html` | First outreach to university contacts |
| `follow_up_1.html` | First follow-up (48 hours after initial) |
| `follow_up_2.html` | Final follow-up (96 hours after initial) |
| `process_inquiry.html` | Requesting process details from POSITIVE responses |
| `clarification_response.html` | Responding to legitimacy questions |
| `thank_you.html` | Confirming partnership establishment |
| `my-project-general.html` | Flexible template for edge cases |

#### Safe Rename Protocol (Validated)
- **Underscore to hyphen:** `initial_contact.html` → `initial-contact.html` - SAFE
- **Order prefixes:** `initial_contact.html` → `01_initial_contact.html` - SAFE
- **Case changes:** NOT recommended (breaks case-sensitive filesystems)

#### Risk Assessment: LOW
- `append_audit_trail.py` uses dynamic filename from command-line argument
- `test_templates.py` uses method names (not file paths)
- Documentation references can be updated via find/replace

---

## Architecture

**Email dispatch chain:**
```
verification_orchestrator.py:_build_email_context()  ← assembles context dict
  → channel_dispatch.py:_dispatch_email_verification()  ← maps context to template variables
    → template_service.render_template("work_history", template_name, variables)
      → prefect_flows/templates/work_history/{template}.txt
        → SendGridEmailClient.send_email(rendered_body)
```

## Acceptance Criteria

- AC1: `NEXTJS_BASE_URL=http://localhost:5002` added to `.env`
- AC2: `channel_dispatch.py` builds `check_verification_url` and `schedule_callback_url`, passes to variables
- AC3: All 3 email templates rewritten with three CTAs and correct variable names
- AC4: Variable rename applied atomically across ALL files (templates + code)
- AC5: `voice_voicemail.txt` updated with renamed variables (no online form URL — audio only)
- AC6: `days_elapsed` bug fixed in `channel_dispatch.py`
- AC7: `template_service.py` docstring example updated with new variable names

## Variable Rename Map

**CRITICAL: This rename must be atomic.** If templates change but code doesn't (or vice versa), `render_template()` will throw `KeyError` on first email send.

### Template placeholders

| Old placeholder | New placeholder | Meaning |
|----------------|----------------|---------|
| `{contact_name}` | `{verifier_name}` | The employer HR person who verifies employment |
| `{verifier_name}` | `{agent_name}` | Our MyProject agent name ("MyProject Team") |

### Code: variables dict keys

**Because both old names exist and map to different values, the rename must be done carefully — NOT a simple find-and-replace.** The correct transformation for each file:

**`channel_dispatch.py` (lines 318-319):**
```python
# BEFORE
"contact_name": context.get("contact_name", "HR Department"),
"verifier_name": context.get("verifier_name", "MyProject Team"),

# AFTER
"verifier_name": context.get("verifier_name", "HR Department"),
"agent_name": context.get("agent_name", "MyProject Team"),
```

**`verification_orchestrator.py` (lines 248, 252):**
```python
# BEFORE
"contact_name": contact_name,
...
"verifier_name": "MyProject Team",

# AFTER
"verifier_name": contact_name,
...
"agent_name": "MyProject Team",
```

**`stream_consumer.py` (line 126):**
```python
# BEFORE
"verifier_name": fields.get("verifier_name"),

# AFTER
"agent_name": fields.get("verifier_name"),  # DB field name unchanged
```

**`services/template_service.py` (lines 19-20, docstring only):**
```python
# BEFORE
"contact_name": "HR Department",
"verifier_name": "MyProject Team",

# AFTER
"verifier_name": "HR Department",
"agent_name": "MyProject Team",
```

### Database columns — NO CHANGE

The underlying DB columns (`employer_contact_name`, `hr_contact_name`) and the Python variable `contact_name` inside `verification_orchestrator.py` (line 235) are **internal** and do NOT need renaming. Only the context/template-facing keys change.

## Implementation Details

### 1. Environment Configuration

**File:** `my-project-backend/.env`

Add:
```env
# Frontend base URL for online verification form (/verify-check/{task_id})
NEXTJS_BASE_URL=http://localhost:5002
```

Production value (set in Railway or Vercel): `NEXTJS_BASE_URL=http://my-project.vercel.app`

### 2. Channel Dispatch Update

**File:** `my-project-backend/prefect_flows/flows/tasks/channel_dispatch.py`

**At module level** (after imports, around line 102), add:
```python
import os
_NEXTJS_BASE_URL = os.environ.get("NEXTJS_BASE_URL", "http://localhost:5002")
_SCHEDULE_BASE_URL = os.environ.get("SCHEDULE_BASE_URL", "")
```

**Inside `_dispatch_email_verification()`**, before `body = render_template(...)`:
```python
# Build online verification form URL
check_verification_url = f"{_NEXTJS_BASE_URL}/verify-check/{task_id}"

# Build schedule callback URL
schedule_callback_url = _SCHEDULE_BASE_URL or f"{_NEXTJS_BASE_URL}/schedule/{task_id}"
```

**Replace the entire variables dict** (lines 315-327):
```python
variables={
    "employer_name": context.get("employer_name", ""),
    "candidate_name": context.get("candidate_name", ""),
    "verifier_name": context.get("verifier_name", "HR Department"),     # RENAMED from contact_name
    "agent_name": context.get("agent_name", "MyProject Team"),          # RENAMED from verifier_name
    "company_name": "MyProject",
    "case_id": str(case_id),
    "callback_number": context.get("callback_number", "+61 2 9000 0000"),
    "position_title": context.get("position_title", ""),
    "employment_start": context.get("employment_start", ""),
    "employment_end": context.get("employment_end", ""),
    "original_date": context.get("original_date", ""),
    "check_verification_url": check_verification_url,
    "schedule_callback_url": schedule_callback_url,
    "days_elapsed": context.get("days_elapsed", ""),
},
```

### 3. Verification Orchestrator Update

**File:** `my-project-backend/prefect_flows/flows/verification_orchestrator.py`

**Line 248:** `"contact_name": contact_name,` → `"verifier_name": contact_name,`
**Line 252:** `"verifier_name": "MyProject Team",` → `"agent_name": "MyProject Team",`

### 4. Stream Consumer Update

**File:** `my-project-backend/prefect_flows/flows/tasks/stream_consumer.py`

**Line 126:** `"verifier_name": fields.get("verifier_name"),` → `"agent_name": fields.get("verifier_name"),`

### 5. Template Service Docstring Update

**File:** `my-project-backend/services/template_service.py`

**Lines 19-20 (docstring example):**
```python
# BEFORE
"contact_name": "HR Department",
"verifier_name": "MyProject Team",

# AFTER
"verifier_name": "HR Department",
"agent_name": "MyProject Team",
```

### 6. Template Rewrites

All templates use the NEW variable names (`{verifier_name}` = employer person, `{agent_name}` = our agent).

---

**File:** `prefect_flows/templates/work_history/email_first_contact.txt`

```
Subject: Employment Verification Request – {candidate_name}

Dear {verifier_name},

My name is {agent_name} and I am contacting you on behalf of {company_name} regarding the employment record of {candidate_name} (Case ID: {case_id}).

We are seeking you to validate details for {candidate_name} who said they worked at your organisation. We understand you are busy, and we will keep this as straightforward as possible.

You can:
- Use our fast, simple online verification form {check_verification_url}
- Call us directly on {callback_number} or
- Schedule a callback {schedule_callback_url}.

The verification is typically completed in under five minutes.

If you are not the right person to handle this request, please forward it to your HR or payroll team, or let us know who to contact.

Thank you for your time.

Warm regards,
{agent_name}
{company_name} – Employment Verification Team
Phone: {callback_number}
Reference: {case_id}
```

---

**File:** `prefect_flows/templates/work_history/email_reminder_1.txt`

```
Subject: Reminder – Employment Verification Request for {candidate_name} (Case {case_id})

Dear {verifier_name},

This is a friendly follow-up to our message sent on {original_date} regarding the employment verification for {candidate_name} at {employer_name}.

We have not yet received a response and wanted to check whether this reached the right person, or whether there is any information we can provide to help.

You can complete the verification quickly:
- Use our fast, simple online verification form {check_verification_url}
- Call us directly on {callback_number} or
- Schedule a callback {schedule_callback_url}.

The verification is typically completed in under five minutes. If you need to redirect this request to another team member, please forward this email and copy us on the reply.

We appreciate your assistance and look forward to hearing from you soon.

Kind regards,
{agent_name}
{company_name} – Employment Verification Team
Phone: {callback_number}
Reference: {case_id}
```

---

**File:** `prefect_flows/templates/work_history/email_reminder_2.txt`

```
Subject: Final Follow-Up – Employment Verification for {candidate_name} (Case {case_id})

Dear {verifier_name},

We are writing for the final time regarding the employment verification for {candidate_name} at {employer_name}. It has now been {days_elapsed} days since our initial contact on {original_date} and we have not yet received a response.

Without a response within the next 48 hours, we will be required to record this verification as unconfirmed in our records, which may affect {candidate_name}'s application outcome.

You can still complete the verification quickly:
- Use our fast, simple online verification form {check_verification_url}
- Call us directly on {callback_number} or
- Schedule a callback {schedule_callback_url}.

If your organisation has a dedicated process for verification requests, please provide us with the appropriate contact or portal, and we will follow that process immediately.

We appreciate that your team is busy and thank you for any assistance you are able to provide.

Regards,
{agent_name}
{company_name} – Employment Verification Team
Phone: {callback_number}
Reference: {case_id}
```

---

**File:** `prefect_flows/templates/work_history/voice_voicemail.txt`

```
[MyProject Voicemail — Employment Verification]

Hello, this is a message for {verifier_name} from {employer_name}.

My name is {agent_name}, calling on behalf of {company_name} to complete
an employment verification for {candidate_name} (Reference: {case_id}).

This is regarding their employment from {employment_start} to {employment_end}
in the role of {position_title}.

The verification typically takes less than five minutes. Please call us back
at {callback_number} and quote reference {case_id}.

Thank you for your time.
```

## Bugs Fixed

1. **`days_elapsed` never provided:** `email_reminder_2.txt` uses `{days_elapsed}` but the variables dict never included it → would cause `KeyError` at runtime. Fixed by adding to variables.

2. **Backwards variable naming:** `{contact_name}` referred to the verifier; `{verifier_name}` referred to our agent. Semantically backwards. Fixed with atomic rename across all 8 files.

## Files Changed (8 files total)

| File | Changes |
|------|---------|
| `my-project-backend/.env` | Add `NEXTJS_BASE_URL=http://localhost:5002` |
| `prefect_flows/flows/tasks/channel_dispatch.py` | Add URL builders; rename variable keys; add `days_elapsed` |
| `prefect_flows/flows/verification_orchestrator.py` | Rename context keys (lines 248, 252) |
| `prefect_flows/flows/tasks/stream_consumer.py` | Rename context key (line 126) |
| `services/template_service.py` | Update docstring example (lines 19-20) |
| `prefect_flows/templates/work_history/email_first_contact.txt` | Full rewrite: three CTAs + renamed vars |
| `prefect_flows/templates/work_history/email_reminder_1.txt` | Full rewrite: three CTAs + renamed vars |
| `prefect_flows/templates/work_history/email_reminder_2.txt` | Full rewrite: three CTAs + renamed vars + urgency |
| `prefect_flows/templates/work_history/voice_voicemail.txt` | Rename vars only (no form URL) |

## Notes

- `SCHEDULE_BASE_URL` is a placeholder — may not be implemented. Fallback: `{NEXTJS_BASE_URL}/schedule/{task_id}`
- `email_outreach.py` is a SEPARATE flow (JWT token-based) — not touched
- HTML templates in `my-project-communication/email-templates/` are for education verification — not touched
- Database column names (`employer_contact_name`, `hr_contact_name`) are internal and do NOT change

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
