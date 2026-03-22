<COMMENTS>
Reviewer recommended additions to strengthen execution clarity and governance:

1. Security hardening completion criteria
- Add explicit credential rotation and revocation requirements (not only removal from files).
- Add incident response steps: identify exposure window, rotate keys, verify revocation, document owner and completion SLA.

2. Waiver and fallback policy specification
- Add a deterministic waiver matrix for UI-critical journeys:
  - When API-only fallback is allowed
  - Who can approve
  - Expiry/renewal rules
  - Whether fallback counts as PASS/BLOCKED
- Require waiver ID and rationale in execution reports.

3. Harness contract formalization
- Add a versioned contract section for Thread/Turn/Item:
  - Canonical schema location
  - Compatibility rules (backward/forward)
  - Change control process (who approves schema changes)

4. Baseline capture plan for KPIs
- Add baseline establishment tasks for all metrics currently marked Unknown/Inconsistent.
- Add metric owner and data source for each KPI.

5. Initiative ownership and accountability
- Add DRI assignment table for I1-I7 with review cadence and escalation path.

6. Alignment with existing native teams PRDs
- Add explicit relationship statement to PRD-NATIVE-TEAMS-001 and PRD-NATIVE-TEAMS-002:
  - What is reused
  - What is superseded
  - What remains out of scope

7. CI gate implementation detail
- Add required checks list (names) and enforcement points:
  - pre-commit
  - pull request required checks
  - branch protection expectations

8. Stronger Definition of Done
- Add objective release criteria beyond "merged":
  - Zero open P0 items
  - Policy engine tests passing
  - Spec/report/evidence lint gates passing in CI
  - Observability SLO checks passing for pilot initiatives
</COMMENTS>

# PRD-SYSTEM3-ORCHESTRATOR-AUTONOMY-001: Autonomous System 3 and Orchestrator Development Mode

```yaml
prd_id: PRD-SYSTEM3-ORCHESTRATOR-AUTONOMY-001
title: "Autonomous System 3 and Orchestrator Development Mode"
product: "Claude Harness Setup"
version: "1.0"
status: draft
created: "2026-02-16"
author: "System 3 + Harness Engineering"
```

**Status:** Draft for implementation
**Date:** 2026-02-16
**Scope:** Harness and orchestration control-plane, testing enforcement, observability, and autonomy policy

---

## 1. Executive Summary

We will evolve the harness into a product-grade autonomous development platform where System 3 and orchestrators run in a strict contract environment: repository-local source of truth, enforced docs/test artifacts, agent-legible telemetry, and graded autonomy.

The immediate gap is not lack of ideas; it is lack of enforcement. We already have markdown E2E specs, orchestration skills, Logfire integration, and parallel-solutioning guidance, but these are inconsistently applied and not continuously gated.

This PRD defines seven initiatives to close that gap and deliver a reliable autonomous loop for feature delivery, validation, and operational safety.

---

## 2. Problem Statement

Current autonomous development mode has four core issues:

1. Knowledge and state are fragmented across multiple doc trees and formats, making freshness and status unclear.
2. Markdown test specifications exist but are not hard-enforced in CI/runtime, so execution and evidence standards drift.
3. Observability and browser tooling are available but not integrated as mandatory stages in the orchestrator loop.
4. Autonomy controls (what can auto-execute vs require approval) are not modeled as a runtime policy contract.

### 2.1 Evidence Snapshot (from current analysis)

- Markdown E2E workflow is documented as primary, but enforcement is procedural, not mechanical.
- No `.github/workflows/` gate exists in the analyzed `my-project` repo for spec/report/evidence conformance.
- Drift exists between docs and runtime config (for example, E2E docs referencing `5001` while frontend dev config is `5002`).
- Execution reports show fallback to API-only validation when browser MCP was unavailable, but no automatic policy fail/waiver mechanism.
- Root and frontend E2E directories are duplicated with uneven completeness.
- Sensitive credentials/tokens appear in plain text in configuration and test-spec documents (must be remediated).

---

## 3. Goals and Success Metrics

### 3.1 Business Goals

| Goal | Description | Target |
|------|-------------|--------|
| G1 | Increase autonomous delivery throughput without quality regression | +40% accepted autonomous PR throughput in 90 days |
| G2 | Reduce human QA bottleneck | -50% manual QA effort for covered journeys |
| G3 | Improve operational confidence | 95% of autonomous runs produce complete evidence bundles |

### 3.2 System Goals

| Goal | Description | Target |
|------|-------------|--------|
| S1 | Enforce repository source-of-truth governance | 100% PRDs/plans/specs indexed with state + owner |
| S2 | Enforce markdown-spec execution contract | 100% required journeys have valid spec + execution report + evidence |
| S3 | Enforce policy-aware autonomy | 100% high-impact actions pass approval policy checks |

### 3.3 Key Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|------------|
| Spec Conformance Rate | Unknown | 100% | CI spec/report lint gate |
| Evidence Completeness Rate | Inconsistent | >=95% | Evidence manifest validation |
| Browser Validation Coverage | Inconsistent | >=85% of UI-tagged journeys | Journey execution ledger |
| Mean Time to Diagnose Failures | High | -40% | Logfire trace-to-root-cause duration |
| Secrets-in-Repo Incidents | Present | 0 | Secret scanning gate |

---

## 4. Scope

### 4.1 In Scope

- System 3/orchestrator operating contract and policy
- Documentation governance and canonical indexing
- Markdown test-spec execution standard with strict validation
- Observability contract (logs/metrics/traces) and Logfire integration into loop
- Browser MCP and Playwright execution policy and fallback rules
- Evaluation harness and autonomy gates

### 4.2 Out of Scope

- Full rewrite of all existing orchestration skills
- Migration of all historical docs into one sprint
- Replacing Beads/task systems

---

## 5. Guiding Principles

1. Harness is a product: versioned contracts, explicit state, measurable outcomes.
2. Repo is the world model: if it is not in-repo and indexed, it is not authoritative.
3. Agent legibility over human convenience: structured artifacts first.
4. Mechanical enforcement over social process.
5. Graded autonomy with explicit approval boundaries.

---

## 6. Target Architecture

### 6.1 Control Plane

System 3 (meta-governance) -> Orchestrator (initiative lead) -> Workers (specialists)

- System 3 owns goals, policy decisions, and escalation.
- Orchestrator owns decomposition, assignment, and synthesis.
- Workers execute implementation, tests, and evidence capture.

### 6.2 Harness Contract (App Server style)

Define and enforce core runtime primitives:

- `Thread`: durable initiative/session context
- `Turn`: user or system-initiated unit of work
- `Item`: typed event (`started`, `delta`, `completed`, `failed`, `needs_approval`)

All clients/tools (CLI, browser automation, Railway, Logfire) emit into this event model.

### 6.3 Docs Contract

Canonical docs tree with explicit state metadata:

- PRDs
- plans (active/completed)
- architecture decisions
- test specs and execution reports
- quality grades

Each artifact must include at minimum:
- owner
- last validated date
- state (`draft`, `validated`, `tested`, `deployed`, `superseded`)
- related task/epic ID

### 6.4 Validation Contract (Markdown Spec Execution)

For each required journey:

1. Valid markdown spec from canonical template/schema
2. Execution using approved browser engine (`chrome-devtools MCP` or Playwright)
3. Standardized execution report
4. Evidence bundle (screenshots/logs/network/trace links)
5. Policy decision if fallback path used (for example API-only verification)

No closure without complete bundle or explicit approved waiver.

### 6.5 Observability Contract

- Structured JSON logs with stable event taxonomy
- OpenTelemetry spans for turns/tools
- Correlation IDs: `thread_id`, `turn_id`, `task_id`, `trace_id`
- Logfire query surface integrated into orchestrator diagnostics

---

## 7. Initiatives

### Initiative I1: Documentation Governance and State Ledger

Deliverables:
- Canonical docs index (`docs/index.md`) with machine-readable metadata
- CI lints for freshness, cross-links, ownership, and state transitions
- Scheduled doc-gardening agent that opens corrective PRs

Acceptance:
- 100% active PRDs/plans indexed with state and owner
- CI fails on stale or orphaned active artifacts

### Initiative I2: Markdown Spec Enforcement Pipeline

Deliverables:
- Spec schema linter (required sections, Given/When/Then, execution block, evidence manifest)
- Execution report schema linter (result table, blockers, tool used, timestamps)
- Evidence validator (required files exist and match manifest)

Acceptance:
- CI blocks merges if required journey artifacts are non-conformant
- Filename convention normalization enforced (`J{N}_EXECUTION_REPORT.md`)

### Initiative I3: Unified E2E Topology and Path Normalization

Deliverables:
- Single canonical E2E root; deprecated duplicate trees marked and migrated
- Port/source-of-truth checks (docs must match runtime config)
- Journey registry that maps spec -> run config -> evidence directory

Acceptance:
- Zero path ambiguity for active journeys
- Automated drift detection between docs and runtime configuration

### Initiative I4: System 3 / Orchestrator Loop Expansion

Deliverables:
- Mandatory phase model: Research -> Parallel Solutioning -> Plan -> Implement -> Validate -> Review
- `/parallel-solutioning` required for multi-service/high-risk work
- Consensus artifact template: unanimous decisions, contested decisions, risks, eval plan

Acceptance:
- 100% of designated high-complexity initiatives include a consensus artifact before implementation

### Initiative I5: Observability-First Autonomous Debugging

Deliverables:
- Logfire + OTEL minimum instrumentation profile
- Concurrency wrapper with tracing for all fan-out operations
- Orchestrator “self-diagnose” routine that queries logs/traces before retry

Acceptance:
- Trace coverage >=90% for orchestrator turns/tool calls
- Failure reports include trace links and root-cause hypothesis

### Initiative I6: Policy-Aware Autonomy Guardrails

Deliverables:
- Autonomy levels (`observe`, `propose`, `execute_with_approval`, `bounded_execute`)
- Policy engine for action classes (code edit, merge, deploy, data mutation, infra changes)
- Server-initiated approval events that pause turns

Acceptance:
- 100% high-impact actions require explicit policy pass
- Full audit trail for approvals/rejections

### Initiative I7: Security and Secrets Hygiene

Deliverables:
- Remove plain-text secrets from docs/config, replace with env indirection
- Secret scanning in CI and pre-commit
- Redaction policy for test specs/reports

Acceptance:
- Zero known plaintext credentials in tracked files
- CI hard-fails on secret leak patterns

---

## 8. Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-001 | System shall maintain a canonical indexed ledger of PRDs/plans/specs with state metadata | P0 |
| FR-002 | System shall lint markdown specs/reports against strict schemas in CI | P0 |
| FR-003 | System shall require evidence manifest validation for required journeys | P0 |
| FR-004 | System shall enforce a mandatory phase-gated orchestrator workflow for complex initiatives | P0 |
| FR-005 | System shall emit typed thread/turn/item events for orchestrator runs | P0 |
| FR-006 | System shall integrate Logfire/trace diagnostics into retry and failure analysis loops | P1 |
| FR-007 | System shall enforce runtime autonomy policy before executing high-impact actions | P0 |
| FR-008 | System shall support documented waivers with explicit owner and expiry for temporary bypasses | P1 |
| FR-009 | System shall continuously detect doc/config/runtime drift and open remediation tasks | P1 |
| FR-010 | System shall prevent plaintext secret storage in docs/specs/config | P0 |

---

## 9. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR-001 | Spec/report lint runtime | < 60s per PR |
| NFR-002 | Evidence validation runtime | < 60s per PR |
| NFR-003 | Orchestrator event delivery | p95 < 500ms per item |
| NFR-004 | Observability availability | 99.9% for logging/trace ingestion |
| NFR-005 | Policy engine decision latency | p95 < 200ms |
| NFR-006 | Audit retention | 90 days minimum |

---

## 10. Rollout Plan (30-60-90 Days)

### Days 0-30: Foundations

- Implement docs ledger and metadata schema
- Implement spec/report/evidence linters
- Establish canonical E2E root and journey registry
- Secret hygiene remediation baseline

Exit Criteria:
- CI gates active for docs/spec/report/evidence/secret scan

### Days 31-60: Loop Expansion

- Integrate mandatory phase-gated orchestrator workflow
- Require `/parallel-solutioning` for designated complexity classes
- Add Logfire-based failure diagnosis into orchestrator loop
- Introduce autonomy policy levels and approval events

Exit Criteria:
- Policy and observability contracts enforced for new initiatives

### Days 61-90: Hardening and Scale

- Expand journey coverage and conformance to >=85% UI journeys
- Add dashboards for conformance, latency, and policy metrics
- Enable recurring doc-gardening and golden-principles refactor jobs
- Calibrate waivers and reduce fallback dependence

Exit Criteria:
- Stable autonomous mode with measurable quality and safety outcomes

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Enforcement too strict initially | Throughput drop | Introduce waiver workflow with expiry and owner |
| Browser MCP instability in parallel runs | False failures | Session coordination + deterministic fallback policy |
| Migration fatigue from doc normalization | Slow adoption | Incremental migration + automated remediations |
| Increased compute/token costs | Budget pressure | Concurrency budgets + targeted high-value coverage |

---

## 12. Open Questions

1. Which journeys are mandatory deployment gates vs informational coverage?
2. What is the exact approval matrix by environment (dev/staging/prod)?
3. Should fallback API-based validation ever count as PASS for UI-critical journeys?
4. Which team owns long-term governance of docs ledger and lint rules?

---

## 13. Definition of Done

This PRD is considered implemented when:

1. All P0 requirements are merged and enforced in CI.
2. At least one full initiative executes end-to-end under the new phase-gated loop.
3. A monthly governance report can be generated directly from repository artifacts and event traces.
4. No known plaintext credentials remain in tracked docs/configuration.

## Implementation Status

| Epic | Status | Date | Commit |
|------|--------|------|--------|
| - | Remaining | - | - |
