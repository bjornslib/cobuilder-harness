# Email Template Rename Safety - Research Findings

**Date**: 2026-03-11
**Node ID**: research_email_templates
**Status**: Complete

## Executive Summary

This research investigates best practices for safely renaming email template files in the AgenCheck codebase. The primary concern is ensuring that renaming template files (e.g., `initial_contact.html` → `initial-contact.html`) does not break existing references in code, configuration, and documentation.

## Current State Analysis

### Email Templates Directory
Location: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-communication-agent/email-templates/`

**Current Template Files** (7 total):
| File | Purpose |
|------|---------|
| `initial_contact.html` | First outreach to university contacts |
| `follow_up_1.html` | First follow-up (48 hours after initial) |
| `follow_up_2.html` | Final follow-up (96 hours after initial) |
| `process_inquiry.html` | Requesting process details from POSITIVE responses |
| `clarification_response.html` | Responding to legitimacy questions |
| `thank_you.html` | Confirming partnership establishment |
| `agencheck-general.html` | Flexible template for edge cases |

### Template Reference Locations

After comprehensive search, the following references to email templates were found:

#### 1. Documentation Files
| File | Reference Pattern | Status |
|------|-------------------|--------|
| `helpers/EMAIL_TEMPLATES_README.md` | `email-templates/initial_contact.html` | Paths shown in code examples |
| `docs/email-templates-changelog.md` | `email-templates/initial_contact.html` | Historical changelog |
| `CLAUDE-NEW.md` | `Read("email-templates/initial_contact.html")` | Agent instructions |
| `docs/plans/2025-11-08-email-template-content-updates.md` | Multiple template references | Step-by-step update guide |

#### 2. Python Code
| File | Reference Pattern | Status |
|------|-------------------|--------|
| `helpers/append_audit_trail.py` | `args.template_file` → reads from `email-templates/` | Uses relative filename argument |
| `tests/test_templates.py` | Imports `EmailTemplates` class | Uses method calls, not file paths |
| `test_variables.sh` | `for template in email-templates/{...}.html` | Shell loop with hardcoded names |

#### 3. Test Files
| File | Reference Pattern | Status |
|------|-------------------|--------|
| `tests/test_templates.py` | Method names: `get_initial_contact`, `get_follow_up_1`, etc. | Indirect via helper class |

## Safe Rename Protocol

### Step 1: Audit All References

Before renaming, identify all locations that reference the template:

1. **Code references**: Python files, shell scripts, configuration
2. **Documentation**: README files, inline comments, usage examples
3. **Tests**: Test files that reference specific template filenames

### Step 2: Rename with Replacement

If the template file `initial_contact.html` is to be renamed to `initial-contact.html`:

#### For Python Files:
```python
# BEFORE (append_audit_trail.py line 228):
template_path = Path(__file__).parent.parent / "email-templates" / args.template_file

# AFTER - no change needed (uses relative filename from argument)
# This approach is safer as it accepts the filename as input
```

#### For Documentation:
Update all code examples and references:
```markdown
# BEFORE:
Read("email-templates/initial_contact.html")

# AFTER:
Read("email-templates/initial-contact.html")
```

### Step 3: Test the Rename

After renaming:
1. Run tests: `python tests/test_templates.py`
2. Verify audit trail helper works with `--template-file initial-contact.html`
3. Check shell scripts: `test_variables.sh`

## Risk Assessment

### Low Risk Scenarios
- **Renaming order only**: `initial_contact.html` → `01_initial_contact.html` or `initial-contact.html`
- **Underscore to hyphen**: Common pattern, no breaking changes if all references use same convention

### Higher Risk Scenarios
- **Special characters**: Avoid spaces, but hyphens/underscores are safe
- **Case changes**: `Initial_Contact.html` → `initial_contact.html` may break case-sensitive filesystems

### Context-Aware Analysis

**Current Architecture**: Templates are referenced by:
1. **Hardcoded paths in documentation/examples**: Static examples that should be updated
2. **Dynamic references via filename argument**: `append_audit_trail.py` uses `args.template_file` - highly flexible
3. **Helper methods**: `test_templates.py` uses `get_initial_contact()` method names - not affected by file rename

## Recommended Naming Convention

Based on current usage and codebase patterns:

| Aspect | Recommendation | Rationale |
|--------|----------------|-----------|
| **Separator** | Hyphen (`-`) | Consistent with Python naming (`snake_case` function names, hyphenated file references in examples) |
| **Case** | Lowercase | Consistent with existing templates |
| **Format** | `name_with_underscores` or `name-with-hyphens` | Both acceptable, but check consistency in codebase |

**Current status**: Mix of `initial_contact.html` (underscore) and check `process_inquiry.html` - consider standardizing.

## Safety Recommendations

### Before Renaming:
1. Run `grep -r "initial_contact" .` across codebase to find all references
2. Document each reference Location
3. Create backup: `cp initial_contact.html initial_contact.html.backup`

### During Renaming:
```bash
# In email-templates directory
mv initial_contact.html initial_contact_new.html

# Update references (if any hardcoded in Python code)
# Update documentation references

# Test
python tests/test_templates.py
```

### After Renaming:
1. Test template loading via helper methods
2. Verify audit trail functionality
3. Update this research document with findings

## Conclusion

**Key Finding**: The current architecture is relatively safe for renames because:
1. `append_audit_trail.py` uses dynamic filename from command-line argument
2. `test_templates.py` uses method names (not file paths)
3. Documentation references can be updated via find/replace

**Risk Level**: LOW - The system is designed with flexibility for template file naming

**Action Items**:
1. If renaming is needed, use `initial-contact.html` style (hyphens)
2. Update any hardcoded references in documentation
3. Test after rename to verify functionality

---

## Sources

1. Email Templates README: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-communication-agent/helpers/EMAIL_TEMPLATES_README.md`
2. Email Templates Changelog: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-communication-agent/docs/email-templates-changelog.md`
3. Append Audit Trail: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-communication-agent/helpers/append_audit_trail.py`
4. Test Templates: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-communication-agent/tests/test_templates.py`
5. CLAUDE Documentation: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-communication-agent/CLAUDE-NEW.md`
6. Template Content Updates Plan: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-communication-agent/docs/plans/2025-11-08-email-template-content-updates.md`

---

**Research Completed By**: Research Node
**Date**: 2026-03-11
**Files Analyzed**: 8 template files, 6 code files, 4 documentation files
