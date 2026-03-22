---
title: "Solution Design P11 Deploy 001"
status: active
type: architecture
last_verified: 2026-03-14
grade: reference
---

# Solution Design: Phase 1.1 Railway Development Deployment

**ID**: SOLUTION-DESIGN-P11-DEPLOY-001
**Date**: 2026-02-23
**Status**: Draft — Awaiting Operator Approval
**Promise**: promise-cf4d1c98

---

## 1. Problem Statement

Phase 1.1 (PRs #213, #214, #215) has been merged to `main` but only partially deployed to Railway dev. The Prefect server and worker are running (from promise-0cf7cadb), but the application code changes (SendGrid email infrastructure, schema fixes) have not been deployed. The development environment needs a coordinated deployment to bring all Phase 1.1 changes online.

### Current State

| Component | Status | Details |
|-----------|--------|---------|
| Prefect Server | Running | Health check passing, 4 deployments registered |
| Prefect Worker | Running | Polling for flows, using public API URL |
| App Postgres (migrations) | Behind | Migrations 025, 043, 044 NOT applied |
| my-project (app server) | Behind | Running pre-Phase-1.1 code |
| SendGrid env vars | Missing | No API key, template ID, or webhook key configured |
| JWT key pair | Missing | RSA keys not generated or stored |
| Redis integration | Partial | Redis exists but not wired to app server |

### Known Constraint

Railway dev environment (created 2025-06-08) uses IPv6-only internal networking. Custom Docker services cannot communicate via `.railway.internal` addresses. Workaround: public URLs for inter-service communication. Railway support message drafted to request dual-stack migration.

---

## 2. Deployment Scope

### 2.1 Database Migrations (Priority: Critical — Must Run First)

Three migrations need applying to the Railway dev Postgres:

| Migration | Table | Purpose |
|-----------|-------|---------|
| `025_replace_client_reference_with_client_id.sql` | `background_check_sequence` | Replace VARCHAR client_reference with INTEGER FK to clients(id) |
| `043_verification_tokens.sql` | `verification_tokens` (new) | JWT token storage for email verification links |
| `044_email_events.sql` | `email_events` (new) | SendGrid webhook event tracking |

**Execution method**: Connect to Railway dev Postgres via `railway connect` or `psql` with Railway connection string, then apply migrations in order.

**Rollback plan**: Each migration should have a corresponding down migration. If 025 fails (data-dependent), stop and assess.

### 2.2 Application Code Deployment (Priority: High)

**Service**: `my-project` (ID: `78f83a62-97ea-4b8d-bdb7-c0a10df84823`)

The my-project service needs to pick up all three merged PRs from `main`:
- PR #213: Test fixes + migration 025 schema changes (model updates)
- PR #214: SendGrid client, JWT token system, webhook handler, email outreach flow
- PR #215: Dockerfile.prefect-worker.railway (already deployed separately)

**Method**: Trigger redeploy of my-project service from latest `main` commit (`d423e374`).

### 2.3 Environment Variables (Priority: High)

New variables needed on Railway dev:

| Variable | Service | Source | Sensitive? |
|----------|---------|--------|------------|
| `SENDGRID_API_KEY` | my-project, prefect-worker | SendGrid dashboard | Yes (secret) |
| `SENDGRID_VERIFICATION_TEMPLATE_ID` | my-project, prefect-worker | SendGrid dashboard | No |
| `SENDGRID_WEBHOOK_VERIFICATION_KEY` | my-project | SendGrid dashboard | Yes (secret) |
| `JWT_PRIVATE_KEY` | prefect-worker | Generated (RSA 2048) | Yes (secret) |
| `JWT_PUBLIC_KEY` | my-project | Generated (RSA 2048) | No |
| `REDIS_URL` | my-project | `redis://default:${Redis.REDISPASSWORD}@redis.railway.internal:6379` | No |

**Note**: SendGrid vars require manual setup in SendGrid dashboard first (single-sender auth, template creation). This is an operator task — cannot be automated.

### 2.4 Prefect Worker Update (Priority: Medium)

The prefect-worker service needs the email_outreach flow registered. Currently it has 4 deployments (voice-verification, verification-orchestrator, catch-up-poller, email-outreach). If email-outreach is already registered (from prior deployment), it just needs the latest code with SendGrid integration.

**Method**: Redeploy prefect-worker from latest `main`.

---

## 3. Deployment Order

```
Phase 0: Prerequisites (Operator Manual Steps)
  ├── 0a. Generate RSA key pair (openssl)
  ├── 0b. Set up SendGrid single-sender auth (verify@my-project.com)
  ├── 0c. Create SendGrid dynamic template
  └── 0d. Get SendGrid API key, template ID, webhook verification key

Phase 1: Database (10 min)
  ├── 1a. Apply migration 025 (client_id FK)
  ├── 1b. Apply migration 043 (verification_tokens)
  ├── 1c. Apply migration 044 (email_events)
  └── 1d. Verify all tables exist with correct schema

Phase 2: Environment Variables (5 min)
  ├── 2a. Set SENDGRID_* vars on my-project + prefect-worker
  ├── 2b. Set JWT_PRIVATE_KEY on prefect-worker
  ├── 2c. Set JWT_PUBLIC_KEY on my-project
  └── 2d. Set REDIS_URL on my-project (if not already)

Phase 3: Application Deployment (15 min)
  ├── 3a. Redeploy my-project from main (triggers auto-build)
  ├── 3b. Wait for my-project deployment SUCCESS
  ├── 3c. Redeploy prefect-worker from main
  └── 3d. Wait for prefect-worker deployment SUCCESS

Phase 4: Smoke Tests (10 min)
  ├── 4a. my-project health check: GET /health → 200
  ├── 4b. Prefect server health: GET /api/health → true
  ├── 4c. Prefect worker online: 5+ deployments registered
  ├── 4d. DB schema verification: verification_tokens, email_events tables exist
  ├── 4e. SendGrid webhook endpoint: POST /api/webhooks/sendgrid → 200 (with test payload)
  └── 4f. Email outreach flow: Trigger test run via Prefect API → Completed state
```

---

## 4. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Migration 025 fails (data integrity) | Medium | High | Backup database before applying; test on empty dev DB first |
| SendGrid rate limiting on dev | Low | Low | Use sandbox mode for initial testing |
| IPv6 networking breaks after env var changes | Low | Medium | Keep public URL fallback for prefect-worker |
| my-project crash on missing env vars | Medium | High | Set ALL env vars BEFORE redeploying |
| JWT key format issues (PEM encoding) | Medium | Medium | Test key generation locally first |

---

## 5. Validation Criteria

| Check | Method | Expected |
|-------|--------|----------|
| Migrations applied | `psql -c "\dt" \| grep verification_tokens` | Table exists |
| Schema correct | `psql -c "\d verification_tokens"` | Columns match migration |
| App server running | `curl /health` | 200 OK |
| Prefect healthy | `curl /api/health` | `true` |
| Worker registered | `GET /api/deployments/filter` | 5+ deployments |
| Webhook endpoint | `POST /api/webhooks/sendgrid` (test payload) | 200 |
| Email flow | Trigger email_outreach via Prefect API | Flow completes |
| JWT generation | POST to token endpoint | Valid JWT returned |

---

## 6. What System 3 Will Do vs Operator Manual Steps

### System 3 (Automated via Orchestrator)
- Apply database migrations via Railway GraphQL + psql
- Set environment variables via Railway GraphQL API
- Trigger service redeployments via Railway GraphQL API
- Run smoke tests and validate
- Report results

### Operator (Manual — Before Deployment)
- Generate RSA key pair and provide to System 3
- Set up SendGrid account (single-sender auth, template, API key)
- Provide SendGrid credentials to System 3
- Review and approve this deployment plan
- Send Railway support message for dual-stack migration

---

## 7. Estimated Timeline

| Phase | Duration | Blocker |
|-------|----------|---------|
| Phase 0 (Prerequisites) | 30-60 min | Operator availability for SendGrid setup |
| Phase 1 (Database) | 10 min | None after Phase 0 |
| Phase 2 (Env vars) | 5 min | Credentials from Phase 0 |
| Phase 3 (Deploy) | 15 min | Build time |
| Phase 4 (Smoke tests) | 10 min | None |
| **Total** | **~1-1.5 hours** | **Phase 0 is the bottleneck** |

---

## 8. Decision Required

**Before proceeding, operator must:**
1. Approve this deployment plan
2. Confirm SendGrid account is set up (or defer email testing)
3. Decide: Deploy everything now, or deploy in phases (DB + app first, SendGrid later)?

**Recommendation**: Deploy DB + app code + JWT keys first (Phases 1-3 without SendGrid vars). This unblocks schema validation and Prefect flow testing. Add SendGrid credentials later when the account is set up.
