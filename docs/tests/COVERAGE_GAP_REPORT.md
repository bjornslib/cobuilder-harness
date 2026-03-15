---
title: "Browser Test Coverage Gap Report"
status: active
type: reference
last_updated: 2026-02-17
generated_from: component_test_map.json
---

# Browser Test Coverage Gap Report

## Summary

| Metric | Value |
|--------|-------|
| Total components | 6 |
| Components with browser tests | 1 |
| Components with API tests | 3 |
| Components with visual tests | 1 |
| Components with NO tests | 2 |
| Overall browser coverage | 17% |

## Coverage Matrix

| Component | E2E Browser | API | Visual | Unit | Status |
|-----------|------------|-----|--------|------|--------|
| frontend/chat-interface | 2 specs | - | 1 spec | - | PARTIAL |
| backend/orchestrator | - | 2 specs | - | - | PARTIAL |
| backend/eddy-validate | - | 1 spec | - | - | MINIMAL |
| backend/user-chat | - | 1 spec | - | - | MINIMAL |
| backend/deep-research | - | - | - | - | NONE |
| backend/university-contact-manager | - | - | - | - | NONE |

## Critical Gaps

### Priority 1: No Tests At All
- **backend/deep-research** (port 8001) — No test coverage of any kind
- **backend/university-contact-manager** (port 5186) — No test coverage of any kind

### Priority 2: Missing Browser E2E Tests
- **backend/orchestrator** — Has API tests but no browser E2E flow testing the full request path
- **backend/eddy-validate** — Only health check, no functional verification test
- **backend/user-chat** — Only health check, no functional query test

### Priority 3: Missing Visual Tests
- All backend services — Visual tests not applicable (API-only)
- frontend/chat-interface — Has 1 visual spec but could cover more states (error, loading, empty)

## Recommendations

1. **Immediate**: Add health check API specs for deep-research and university-contact-manager
2. **Short-term**: Add browser E2E specs for full credential verification flow (frontend → backend → MCP services)
3. **Medium-term**: Add visual regression specs for chat interface error states, loading states, and empty states
4. **Ongoing**: Update this report when new test specs are added to docs/tests/specs/

## How to Update This Report

1. Add/modify test specs in `docs/tests/specs/`
2. Update `component_test_map.json` with new spec mappings
3. Re-generate this report (or manually update the matrix)

---

*This report is generated from `component_test_map.json` and should be updated whenever test specs change.*
