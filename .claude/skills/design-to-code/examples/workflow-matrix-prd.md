---
title: "Workflow Matrix Prd"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

```yaml
# PRD FRONTMATTER (REQUIRED)
# The prd_id is the canonical identifier used throughout the system
prd_id: PRD-WORKFLOW-MATRIX
title: "Workflow Matrix"
product: "My Project"
version: "0.1"
status: draft
created: "2026-01-15"
author: "FAIE Labs"
```

# PRD-WORKFLOW-MATRIX: Workflow Matrix

**Product:** My Project Workflow Matrix
**Version:** 0.1 (Initial Draft)
**Date:** 15 January 2026
**Author:** FAIE Labs
**Status:** Draft for Extension

---

## 1. Executive Summary

The Workflow Matrix enables My Project customers to configure automated retry and channel fallback rules for agent communications. This feature addresses a critical customer need: ensuring verification contacts are reached through intelligent multi-channel retry logic, while allowing flexibility for different client requirements.

### 1.1 Problem Statement

Background screening companies lose significant time and revenue when verification attempts fail due to unreachable contacts. Currently, retry logic is either manual (staff must remember to follow up) or rigidly programmed (no client-specific customisation). My Project customers need:

1. Configurable retry rules that automate follow-up attempts
2. Channel fallback logic (e.g., try SMS if email fails)
3. Client-specific overrides for customers with unique requirements
4. Visibility into what rules are active and when they trigger

### 1.2 Solution Overview

A visual matrix interface allowing customers to:
- Define default retry workflows that apply to all clients
- Create client-specific overrides for individual end-customers
- Configure retry counts, intervals, and fallback channels per action
- View and restore historical workflow configurations

---

## 2. Goals and Success Metrics

### 2.1 Business Goals

| Goal | Description | Target |
|------|-------------|--------|
| Reduce Manual Follow-ups | Automate retry attempts currently done manually by staff | 70% reduction in manual follow-up tasks |
| Improve Contact Success Rate | Increase successful contact through intelligent multi-channel retry | 15% improvement in first-attempt contact success |
| Enable Client Customisation | Allow per-client workflow customisation without engineering support | 100% of client-specific rules configurable via UI |
| Reduce Time-to-Resolution | Faster verification completion through automated escalation | 25% reduction in average verification time |

### 2.2 User Goals

| User Type | Primary Goal | Secondary Goal |
|-----------|--------------|----------------|
| Operations Manager | Configure default workflows once, apply everywhere | Monitor automated actions via analytics |
| Account Manager | Customise workflows for specific client requirements | Quickly explain workflow to clients |
| Compliance Officer | Ensure retry logic meets regulatory requirements | Audit historical workflow changes |

### 2.3 Success Metrics

| Metric | Current Baseline | Target | Measurement Method |
|--------|------------------|--------|-------------------|
| Workflow Configuration Time | N/A (new feature) | < 10 min for full setup | In-app timing analytics |
| Staff Satisfaction (Configuration) | N/A | > 4.0/5.0 rating | Post-setup survey |
| Automated Retry Success Rate | N/A | > 60% successful on retry | System telemetry |
| Client Override Adoption | N/A | > 30% of clients have custom rules within 6 months | Database query |

---

## 3. User Stories

### 3.1 Must Have (P0)

| ID | User Story | Acceptance Criteria |
|----|------------|---------------------|
| US-001 | As an Operations Manager, I want to define default retry rules so that all verifications follow a consistent process | - Can create rules for each channel (Email, Phone, SMS)<br>- Can set retry count (1-10)<br>- Can set retry interval<br>- Rules persist across sessions |
| US-002 | As an Operations Manager, I want to configure fallback channels so that if one channel fails, another is tried automatically | - Can select fallback channel per action<br>- System prevents circular fallbacks<br>- Fallback triggers after max retries exhausted |
| US-003 | As an Account Manager, I want to create client-specific workflow overrides so that I can meet unique client requirements | - Can select specific client<br>- Can override any default rule<br>- Non-overridden rules inherit from default |
| US-004 | As an Operations Manager, I want to save workflow configurations so that my changes are not lost | - Auto-save drafts locally<br>- Explicit publish action<br>- Version number increments on publish |
| US-005 | As any user, I want to see which rules apply to a client so that I understand the active workflow | - Visual distinction between default and inherited rules<br>- Clear indicator when client has overrides<br>- Matrix shows all active rules at once |

### 3.2 Should Have (P1)

| ID | User Story | Acceptance Criteria |
|----|------------|---------------------|
| US-006 | As a Compliance Officer, I want to view workflow history so that I can audit changes | - Can view list of historical versions<br>- Can preview any historical version<br>- Can see who made changes and when |
| US-007 | As a Compliance Officer, I want to restore a previous workflow version so that I can recover from mistakes | - Can restore any historical version<br>- Restore creates new version (doesn't overwrite history)<br>- Confirmation required before restore |
| US-008 | As an Operations Manager, I want to search and filter rule groups so that I can quickly find what I need | - Can search by rule group name<br>- Can filter by channel type<br>- Can filter by status (active, inactive) |
| US-009 | As any user, I want to see real-time preview of rule behaviour so that I understand the impact of my configuration | - Modal shows natural language description<br>- Description updates as I change values<br>- Preview shows entire fallback chain |

### 3.3 Could Have (P2)

| ID | User Story | Acceptance Criteria |
|----|------------|---------------------|
| US-010 | As an Operations Manager, I want to duplicate workflows between clients so that I can quickly configure similar clients | - Can copy all rules from one client<br>- Can paste to another client<br>- Can select which rules to copy |
| US-011 | As an Account Manager, I want to export workflow configuration so that I can share it with clients | - Can export as PDF<br>- Export shows all rules in readable format<br>- Includes timestamp and version |
| US-012 | As an Operations Manager, I want to see which clients will be affected by default rule changes so that I avoid unintended consequences | - Warning shows affected clients before save<br>- Can view list of affected clients<br>- Can exclude specific clients from change |

---

## 4. Functional Requirements

### 4.1 Workflow Scope Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-001 | System shall support two workflow scopes: Default and Client-Specific | P0 |
| FR-002 | System shall allow users to switch between scopes via toggle control | P0 |
| FR-003 | When Client-Specific scope is selected, system shall display client selector | P0 |
| FR-004 | System shall persist selected client within session | P0 |
| FR-005 | System shall warn users when switching scopes with unsaved changes | P1 |

### 4.2 Rule Group Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-010 | System shall display rule groups as rows in the matrix | P0 |
| FR-011 | System shall support the following rule groups: Document Collection, Phone Calls, SMS/WhatsApp, Research (AI) | P0 |
| FR-012 | Each rule group shall have a unique identifier (e.g., DOC-FLOW-01) | P0 |
| FR-013 | System shall allow administrators to add new rule groups (admin only) | P2 |
| FR-014 | System shall allow searching rule groups by name | P1 |
| FR-015 | System shall allow filtering rule groups by type | P1 |

### 4.3 Timeline Management

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-020 | System shall display timeline columns: Immediate, Day 1, Day 2, Day 3, Day 4 | P0 |
| FR-021 | System shall allow actions to be placed in any timeline column | P0 |
| FR-022 | System shall only allow one action per cell (rule group × day intersection) | P0 |
| FR-023 | System shall support extending timeline beyond Day 4 (configurable max) | P2 |
| FR-024 | "Immediate" actions shall trigger within 1 minute of workflow initiation | P0 |
| FR-025 | "Day N" actions shall trigger N×24 hours after workflow initiation | P0 |

### 4.4 Action Configuration

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-030 | Each action shall have the following configurable properties: Name, Max Retries, Interval, Fallback Channel | P0 |
| FR-031 | Max Retries shall accept integer values from 1 to 10 | P0 |
| FR-032 | Interval shall accept values: 5 min, 10 min, 15 min, 30 min, 1 hour, 4 hours, 24 hours | P0 |
| FR-033 | Fallback Channel shall accept values: SMS, Email, WhatsApp, Phone Call, None | P0 |
| FR-034 | System shall prevent circular fallback configurations | P0 |
| FR-035 | System shall display natural language summary of action behaviour | P1 |

### 4.5 Inheritance and Override

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-040 | Client-specific rules shall override default rules for the same cell | P0 |
| FR-041 | Cells without client-specific rules shall inherit from default | P0 |
| FR-042 | Inherited rules shall be visually distinct from overridden rules | P0 |
| FR-043 | Users shall be able to "reset to default" for any overridden rule | P1 |
| FR-044 | System shall track inheritance chain for audit purposes | P1 |

### 4.6 Persistence and Versioning

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-050 | System shall auto-save drafts to local storage | P0 |
| FR-051 | System shall require explicit action to publish changes | P0 |
| FR-052 | System shall increment version number on each publish | P0 |
| FR-053 | System shall retain history of all published versions | P1 |
| FR-054 | System shall allow viewing any historical version | P1 |
| FR-055 | System shall allow restoring any historical version | P1 |
| FR-056 | System shall record author and timestamp for each version | P1 |

---

## 5. Non-Functional Requirements

### 5.1 Performance

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-001 | Matrix shall load within 2 seconds for up to 100 rules | < 2s |
| NFR-002 | Action modal shall open within 100ms of click | < 100ms |
| NFR-003 | Auto-save shall complete within 500ms | < 500ms |
| NFR-004 | Publish shall complete within 5 seconds | < 5s |

### 5.2 Reliability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-010 | Local draft storage shall persist across browser refresh | 100% |
| NFR-011 | Local draft storage shall persist across browser close (up to 7 days) | 100% |
| NFR-012 | Published rules shall be replicated to backup storage | 99.99% |

### 5.3 Scalability

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-020 | System shall support up to 500 clients per customer account | 500 |
| NFR-021 | System shall support up to 50 rule groups per workflow | 50 |
| NFR-022 | System shall support up to 20 timeline columns | 20 |
| NFR-023 | System shall retain up to 100 historical versions per workflow | 100 |

### 5.4 Security

| ID | Requirement | Notes |
|----|-------------|-------|
| NFR-030 | All workflow data shall be encrypted at rest | AES-256 |
| NFR-031 | All workflow data shall be encrypted in transit | TLS 1.3 |
| NFR-032 | Access to client-specific workflows shall require appropriate permissions | RBAC |
| NFR-033 | Audit log shall record all workflow modifications | Immutable log |

### 5.5 Accessibility

| ID | Requirement | Standard |
|----|-------------|----------|
| NFR-040 | Interface shall be keyboard navigable | WCAG 2.1 AA |
| NFR-041 | Interface shall support screen readers | WCAG 2.1 AA |
| NFR-042 | Colour shall not be sole means of conveying information | WCAG 2.1 AA |
| NFR-043 | Focus indicators shall be visible | WCAG 2.1 AA |

---

## 6. Technical Architecture

### 6.1 Data Model

```
WorkflowConfiguration
├── id: UUID
├── customerId: UUID (My Project customer)
├── scope: "default" | "client_specific"
├── clientId: UUID | null (required if scope is client_specific)
├── version: integer
├── status: "draft" | "published"
├── rules: WorkflowRule[]
├── createdAt: timestamp
├── updatedAt: timestamp
├── publishedAt: timestamp | null
├── publishedBy: UUID | null

WorkflowRule
├── id: UUID
├── configurationId: UUID (FK to WorkflowConfiguration)
├── ruleGroupId: string (e.g., "DOC-FLOW-01")
├── timelinePosition: "immediate" | "day_1" | "day_2" | ...
├── actionName: string
├── actionType: "primary" | "fallback" | "multi_step"
├── maxRetries: integer (1-10)
├── intervalMinutes: integer
├── fallbackChannel: string | null
├── isInherited: boolean (computed, not stored)

RuleGroup
├── id: string
├── name: string
├── description: string
├── channelType: "email" | "phone" | "sms" | "whatsapp" | "internal"
├── isActive: boolean
├── displayOrder: integer

WorkflowVersion
├── id: UUID
├── configurationId: UUID
├── version: integer
├── snapshot: JSON (full configuration at time of publish)
├── publishedBy: UUID
├── publishedAt: timestamp
├── changeDescription: string | null
```

### 6.2 API Endpoints

```
GET    /api/v1/workflows                    # List all workflow configurations
GET    /api/v1/workflows/default            # Get default workflow
GET    /api/v1/workflows/client/:clientId   # Get client-specific workflow
POST   /api/v1/workflows                    # Create new workflow configuration
PUT    /api/v1/workflows/:id                # Update workflow configuration
POST   /api/v1/workflows/:id/publish        # Publish draft to live
GET    /api/v1/workflows/:id/versions       # List historical versions
GET    /api/v1/workflows/:id/versions/:ver  # Get specific historical version
POST   /api/v1/workflows/:id/restore/:ver   # Restore historical version

GET    /api/v1/rule-groups                  # List available rule groups
GET    /api/v1/clients                      # List clients (for dropdown)
```

### 6.3 Technology Stack

| Component | Technology | Notes |
|-----------|------------|-------|
| Frontend | Next.js 15.3 + React 19 | Existing My Project stack |
| State Management | React Query / TanStack Query | Server state caching |
| UI Components | Shadcn/ui + Tailwind CSS | Existing component library |
| Local Storage | IndexedDB via Dexie.js | Draft persistence |
| Backend | Python FastAPI | Existing My Project stack |
| Database | PostgreSQL | Existing infrastructure |
| Caching | Redis | Session and draft caching |

---

## 7. Dependencies

### 7.1 Internal Dependencies

| Dependency | Description | Owner | Risk |
|------------|-------------|-------|------|
| Client Management API | Required for client dropdown | My Project Core | Low |
| Authentication Service | Required for user identification | My Project Core | Low |
| Agent Orchestration Engine | Must consume workflow rules | Aura (My Project) | Medium |

### 7.2 External Dependencies

| Dependency | Description | Fallback |
|------------|-------------|----------|
| None | Feature is self-contained | N/A |

---

## 8. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Users create overly complex workflows | Medium | Medium | Provide templates, best practice guidance, complexity warnings |
| Circular fallback logic causes infinite loops | Low | High | Validation at configuration time prevents circular references |
| Performance degradation with many rules | Low | Medium | Lazy loading, pagination, indexed queries |
| Data loss from browser storage | Low | Medium | Auto-sync drafts to server, clear storage warnings |
| Users accidentally delete critical rules | Medium | Medium | Confirmation dialogs, soft delete with recovery period, version history |

---

## 9. Open Questions

| ID | Question | Owner | Due Date | Resolution |
|----|----------|-------|----------|------------|
| OQ-001 | Should we support time-of-day conditions for fallbacks? (e.g., "outside business hours, use SMS instead of call") | B | TBD | |
| OQ-002 | What is the maximum number of days we should support in the timeline? | B | TBD | |
| OQ-003 | Should client-specific rules require approval before activation? | B | TBD | |
| OQ-004 | How do we handle timezone differences for "Day N" calculations? | B | TBD | |
| OQ-005 | Should we allow custom intervals beyond the preset options? | B | TBD | |

---

## 10. Implementation Phases

### Phase 1: Core Matrix (MVP)
- Default workflow configuration
- Basic rule creation, editing, deletion
- Save and publish functionality
- Essential validation (circular fallback prevention)

### Phase 2: Client-Specific Workflows
- Client selector and scope toggle
- Inheritance logic and visual indicators
- Override and reset functionality

### Phase 3: History and Audit
- Version history viewing
- Version restoration
- Audit log integration

### Phase 4: Advanced Features
- Workflow templates
- Bulk actions
- Export functionality
- Analytics integration

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| Workflow | A collection of rules defining automated retry and fallback behaviour |
| Rule Group | A category of communication channel (e.g., Phone Calls, SMS) |
| Action | A specific communication task within a workflow |
| Fallback Channel | The alternative channel to use when primary action fails |
| Scope | Whether rules apply globally (Default) or to a specific client |
| Inheritance | Client-specific workflows inherit rules from Default when not overridden |

---

## Appendix B: Reference Materials

- Interaction Design Specification: [my-project-workflow-matrix-interaction-design.md]
- UI Mockups: [IMG_3435.png]
- My Project Technical Architecture: [See project knowledge]

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 15 Jan 2026 | FAIE Labs | Initial draft |
