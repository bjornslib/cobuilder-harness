# PRD-P1.1-UEA-DEPLOY-001: Acceptance Test Scenarios
# Generated: 2026-02-28 (guardian mode, blind rubric)
# Source: PRD v2 (amended post design-challenge)

# ============================================================
# F1: Migration 036 Reconciliation + Rebase (weight: 0.35)
# Validation method: code-analysis
# ============================================================

@feature-F1 @weight-0.35 @code-analysis
Feature: Migration 036 Reconciliation and Branch Rebase

  @S1_migration_036_uses_client_id
  Scenario: S1.1 Migration 036 uses client_id instead of client_reference
    Given the feature branch has been rebased on main
    When I examine migration 036_customer_sla_resolution.sql
    Then the migration does NOT add a client_reference column to background_check_sequence
    And the migration does NOT create indexes referencing client_reference
    And all indexes in 036 reference client_id (compatible with migration 025)
    And the unique index uq_bcs_customer_type_step_active uses COALESCE(client_id, 0) not COALESCE(client_reference, '')
    And the resolution lookup index idx_bcs_resolution_lookup includes client_id in its column list

    # Confidence scoring guide:
    # 1.0 — Migration 036 fully rewritten: zero references to client_reference, all indexes use client_id, compatible with 025
    # 0.5 — Migration 036 partially rewritten: client_id used in some places but client_reference still appears in indexes or comments
    # 0.0 — Migration 036 unchanged from original: still adds client_reference VARCHAR(255)

    # Evidence to check:
    # - agencheck-support-agent/database/migrations/036_customer_sla_resolution.sql (full file contents)
    # - grep for "client_reference" in all migration files (should only appear in 025's DROP)
    # - Compare index definitions between 025 and 036 for compatibility

    # Red flags:
    # - Any ADD COLUMN client_reference in 036
    # - Index using COALESCE(client_reference, '') pattern
    # - Duplicate index names between 025 and 036 with different column lists

  @S1_rebase_clean
  Scenario: S1.2 Feature branch cleanly rebased on main
    Given the feature branch feature/ue-a-workflow-config-sla exists
    When I check the git state
    Then the branch contains main's migration 025_replace_client_reference_with_client_id.sql
    And the branch contains main's migration 043_verification_tokens.sql
    And the branch contains main's migration 044_email_events.sql
    And migration files are in correct numeric order: 025 < 035 < 036 < 037 < 043 < 044
    And SendGrid imports resolve (from agencheck.services.sendgrid_client)
    And pytest runs with zero failures

    # Confidence scoring guide:
    # 1.0 — All main migrations present, correct order, SendGrid resolves, pytest green
    # 0.5 — Rebased but some tests failing or SendGrid imports unresolved
    # 0.0 — Branch not rebased (missing 025/043/044) or merge conflicts unresolved

    # Evidence to check:
    # - ls agencheck-support-agent/database/migrations/*.sql | sort
    # - python -c "from agencheck.services.sendgrid_client import SendGridClient"
    # - pytest output summary
    # - git log --oneline showing rebase commits

    # Red flags:
    # - Migration 025 absent from feature branch
    # - Migrations out of numeric order
    # - Import errors for sendgrid_client
    # - pytest failures related to client_reference

  @S1_models_use_client_id
  Scenario: S1.3 Pydantic models and service layer use client_id
    Given the feature branch has been rebased and migration 036 rewritten
    When I examine the SLA models, service, and API files
    Then sla_models.py uses client_id: int | None (not client_reference: str | None)
    And sla_service.py queries join on clients.id (not string match on client_reference)
    And sla_routes.py accepts client_id parameter (not client_reference)
    And the frontend slaConfigSlice.ts sends client_id in API calls
    And check-sla-configuration/page.tsx references client_id (not client_reference)

    # Confidence scoring guide:
    # 1.0 — Zero references to client_reference in models/service/API/frontend; all use client_id with proper FK typing
    # 0.5 — Backend uses client_id but frontend still references client_reference (or vice versa)
    # 0.0 — client_reference still used in models or service layer

    # Evidence to check:
    # - grep -r "client_reference" agencheck-support-agent/models/ agencheck-support-agent/services/ agencheck-support-agent/api/
    # - grep -r "client_reference" agencheck-support-frontend/stores/ agencheck-support-frontend/app/check-sla-configuration/
    # - Read sla_models.py for field type annotations
    # - Read sla_service.py for query patterns

    # Red flags:
    # - client_reference in Pydantic model field names
    # - String comparison WHERE client_reference = ? in service queries
    # - Frontend sending client_reference in fetch/axios calls


# ============================================================
# F2: PR Merge & Railway Deployment (weight: 0.25)
# Validation method: api-required
# ============================================================

@feature-F2 @weight-0.25 @api-required
Feature: PR Merge and Production Deployment

  @S2_tables_exist_in_railway
  Scenario: S2.1 SLA tables exist in Railway PostgreSQL after deployment
    Given PR #212 has been merged to main
    And Railway has auto-deployed from main
    When I query Railway PostgreSQL for SLA tables
    Then check_types table exists
    And background_check_sequence table exists
    And background_check_sequence has a client_id column (INTEGER, FK to clients)
    And background_check_sequence does NOT have a client_reference column
    And background_check_sequence has customer_id, version, status columns

    # TOOL: psql against Railway database
    # Confidence scoring guide:
    # 1.0 — Both tables exist, client_id FK present, no client_reference, all columns correct
    # 0.5 — Tables exist but schema is wrong (client_reference still present, or client_id missing)
    # 0.0 — Tables do not exist in Railway (migrations didn't run)

    # Evidence to check:
    # - railway run psql -c "\d check_types"
    # - railway run psql -c "\d background_check_sequence"
    # - railway run psql -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'background_check_sequence' AND column_name IN ('client_id', 'client_reference', 'customer_id')"
    # - Railway deployment logs showing migration execution

    # Red flags:
    # - "relation does not exist" errors
    # - client_reference column still present
    # - Deployment failed or no recent deployment

  @S2_seed_data_present
  Scenario: S2.2 Seed data present in Railway
    Given SLA tables exist in Railway PostgreSQL
    When I query for seed data
    Then check_types contains work_history with default_sla_hours = 48
    And check_types contains work_history_scheduling with default_sla_hours = 72
    And background_check_sequence has 4 steps for work_history (step_order 1-4)
    And background_check_sequence has 4 steps for work_history_scheduling (step_order 1-4)

    # TOOL: psql against Railway database
    # Confidence scoring guide:
    # 1.0 — Both check types with correct SLA hours, 8 total sequence steps (4 per type)
    # 0.5 — Check types exist but wrong SLA hours, or sequences missing/incomplete
    # 0.0 — No seed data (empty tables)

    # Evidence to check:
    # - SELECT name, default_sla_hours FROM check_types
    # - SELECT ct.name, bcs.step_order, bcs.step_name FROM background_check_sequence bcs JOIN check_types ct ON bcs.check_type_id = ct.id ORDER BY ct.name, bcs.step_order

    # Red flags:
    # - count(*) = 0 on either table
    # - SLA hours not matching (48/72)
    # - Missing sequence steps

  @S2_vercel_deployment
  Scenario: S2.3 Vercel frontend deployment succeeds
    Given PR #212 has been merged to main
    When I check the Vercel deployment
    Then https://agencheck.vercel.app responds with HTTP 200
    And the /check-sla-configuration route exists and redirects to Clerk auth if not logged in

    # TOOL: curl against Vercel URL
    # Confidence scoring guide:
    # 1.0 — Vercel responds 200, /check-sla-configuration route exists, Clerk auth gate active
    # 0.5 — Vercel responds but /check-sla-configuration returns 404
    # 0.0 — Vercel deployment failed or not triggered

    # Evidence to check:
    # - curl -sI https://agencheck.vercel.app/check-sla-configuration (check status code)
    # - Vercel deployment status in dashboard

    # Red flags:
    # - HTTP 404 on /check-sla-configuration
    # - Deployment not triggered after merge
    # - Build errors in Vercel logs


# ============================================================
# F3: SLA CRUD API — Guardian Validation (weight: 0.25)
# Validation method: api-required
# ============================================================

@feature-F3 @weight-0.25 @api-required
Feature: SLA CRUD API End-to-End Validation

  @S3_get_check_types
  Scenario: S3.1 GET /api/v1/sla/check-types returns correct data
    Given the API server is running on Railway
    When I send GET /api/v1/sla/check-types
    Then the response status is 200
    And the response body is a JSON array with at least 2 items
    And each item has fields: id, name, display_name, default_sla_hours, is_active
    And the items include work_history (48h) and work_history_scheduling (72h)

    # TOOL: curl against Railway API
    # Confidence scoring guide:
    # 1.0 — 200 status, correct JSON schema, both seed check types present with correct SLA hours
    # 0.5 — 200 status but missing fields or wrong SLA hours
    # 0.0 — Non-200 status or endpoint doesn't exist

    # Evidence to check:
    # - curl -s https://agencheck-production.up.railway.app/api/v1/sla/check-types | jq .
    # - Verify response schema matches Pydantic model

    # Red flags:
    # - 404 (endpoint not registered)
    # - 500 (database connection or model error)
    # - client_reference in response instead of client_id

  @S3_create_check_type
  Scenario: S3.2 POST /api/v1/sla/check-types creates a new check type
    Given the API server is running
    When I POST /api/v1/sla/check-types with body:
      | name            | display_name         | default_sla_hours |
      | test_guardian    | Guardian Test Type   | 24                |
    Then the response status is 201 or 200
    And the response body contains the created check type with an id
    And GET /api/v1/sla/check-types includes the new test_guardian type

    # TOOL: curl POST then curl GET
    # Confidence scoring guide:
    # 1.0 — Create succeeds, returned ID is valid, subsequent GET includes new type
    # 0.5 — Create returns 200 but GET doesn't show the new type (not persisted)
    # 0.0 — Create returns error (4xx or 5xx)

    # Evidence to check:
    # - POST response body
    # - GET response showing new type in list

    # Red flags:
    # - 422 validation error (model mismatch)
    # - 500 database error
    # - Response contains client_reference field

  @S3_get_sequence
  Scenario: S3.3 GET /api/v1/sla/check-types/{id}/sequence returns ordered steps
    Given check type work_history exists with known id
    When I send GET /api/v1/sla/check-types/{id}/sequence
    Then the response status is 200
    And the response body is a JSON array with 4 items
    And items are ordered by step_order (1, 2, 3, 4)
    And step 1 is initial_call with delay_hours 0
    And step 4 is final_attempt with delay_hours 24

    # TOOL: curl against Railway API
    # Confidence scoring guide:
    # 1.0 — 200, 4 steps in correct order with correct delay_hours and step_names
    # 0.5 — 200 but wrong ordering or missing steps
    # 0.0 — Endpoint doesn't exist or returns error

    # Evidence to check:
    # - Full response body showing all 4 steps

    # Red flags:
    # - Steps out of order
    # - Missing delay_hours values
    # - step_order not starting at 1

  @S3_three_tier_resolution
  Scenario: S3.4 Three-tier resolution: client_id > customer default > system fallback
    Given check types with different resolution levels exist:
      | level           | customer_id | client_id | sla_hours |
      | system fallback | 1           | NULL      | 48        |
      | customer default| 2           | NULL      | 36        |
      | client override | 2           | 5         | 24        |
    When I request the SLA configuration for customer_id=2, client_id=5
    Then the resolved SLA hours should be 24 (client override wins)
    When I request the SLA configuration for customer_id=2, client_id=NULL
    Then the resolved SLA hours should be 36 (customer default wins)
    When I request the SLA configuration for customer_id=99, client_id=NULL
    Then the resolved SLA hours should be 48 (system fallback wins)

    # TOOL: curl or direct API calls
    # Confidence scoring guide:
    # 1.0 — All three tiers resolve correctly in the right priority order
    # 0.5 — Some tiers work but fallback logic is wrong (e.g., client override not taking precedence)
    # 0.0 — Resolution logic not implemented or returns wrong tier

    # Evidence to check:
    # - sla_service.py resolve method
    # - API responses for each tier
    # - Database state showing multi-tier data

    # Red flags:
    # - Hardcoded customer_id=1 everywhere
    # - No client_id parameter accepted in API
    # - Resolution returns system default regardless of customer/client

  @S3_sla_deadline
  Scenario: S3.5 SLA deadline computation is correct
    Given a background task is created with check_type work_history (48h SLA)
    When the task's sla_due_at is computed
    Then sla_due_at = created_at + interval '48 hours'

    # Confidence scoring guide:
    # 1.0 — sla_due_at correctly computed as created_at + default_sla_hours for the check type
    # 0.5 — sla_due_at field exists but computation is wrong or hardcoded
    # 0.0 — sla_due_at field is NULL or not implemented

    # Evidence to check:
    # - SELECT created_at, sla_due_at, sla_due_at - created_at as diff FROM background_tasks WHERE check_type_config_id IS NOT NULL LIMIT 5
    # - Service layer code that sets sla_due_at

    # Red flags:
    # - sla_due_at is always NULL
    # - Hardcoded interval instead of reading from check_types.default_sla_hours
    # - No trigger or service logic that sets sla_due_at on task creation


# ============================================================
# F4: Browser SLA Configuration Page (weight: 0.15)
# Validation method: browser-required
# ============================================================

@feature-F4 @weight-0.15 @browser-required @claude-in-chrome
Feature: SLA Configuration Page — Browser Validation

  @S4_page_loads_with_auth
  Scenario: S4.1 SLA configuration page loads behind Clerk authentication
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to https://agencheck.vercel.app/check-sla-configuration
    Then the page redirects to Clerk login if not authenticated
    When the user authenticates with valid Clerk credentials
    Then the page loads with a title containing "SLA" or "Check" or "Configuration"
    And the page contains a table or list of check types

    # Confidence scoring guide:
    # 1.0 — Page loads with auth gate, shows check types after login
    # 0.5 — Page loads but no data displayed (empty table)
    # 0.0 — Page returns 404 or does not load

    # Evidence to check:
    # - Screenshot of page before and after auth
    # - Page title and main heading
    # - Presence of data table

    # Red flags:
    # - No Clerk auth redirect (page accessible without login)
    # - 404 or "Page not found"
    # - JavaScript console errors

  @S4_crud_check_types
  Scenario: S4.2 User can create and edit check types via the UI
    # TOOL: Claude in Chrome
    Given the user is authenticated on the SLA configuration page
    When Claude in Chrome clicks the "Add" or "Create" button for check types
    And Claude in Chrome fills in the form with name="browser_test" and SLA hours=12
    And Claude in Chrome clicks "Save" or "Submit"
    Then the new check type "browser_test" appears in the table with SLA hours 12
    When Claude in Chrome clicks "Edit" on the browser_test check type
    And Claude in Chrome changes SLA hours to 18
    And Claude in Chrome clicks "Save"
    Then the browser_test check type shows SLA hours 18

    # Confidence scoring guide:
    # 1.0 — Create and edit both work, data updates reflected immediately in UI
    # 0.5 — Create works but edit fails (or vice versa)
    # 0.0 — Neither create nor edit works in the UI

    # Evidence to check:
    # - Screenshots after create and after edit
    # - Table row showing updated values
    # - Network tab showing API calls with client_id (not client_reference)

    # Red flags:
    # - Form sends client_reference instead of client_id
    # - API error responses visible in network tab
    # - Stale data after save (cache not invalidated)

  @S4_sequence_management
  Scenario: S4.3 User can view and manage sequence steps
    # TOOL: Claude in Chrome
    Given the user is on the SLA configuration page
    When Claude in Chrome clicks on a check type (e.g., work_history) to expand it
    Then 4 sequence steps are displayed in order
    And each step shows step_name, delay_hours, and max_attempts
    When Claude in Chrome reorders step 2 and step 3 (drag or button)
    Then the step_order updates are reflected in the UI

    # Confidence scoring guide:
    # 1.0 — Steps display correctly, reordering works, UI updates immediately
    # 0.5 — Steps display but reordering is broken or not implemented
    # 0.0 — Sequence steps not displayed at all

    # Evidence to check:
    # - Screenshot of expanded check type with steps
    # - Step order before and after reorder

    # Red flags:
    # - Steps out of numeric order
    # - Reorder buttons/drag not functional
    # - Steps display but wrong data (e.g., missing delay_hours)

  @S4_persistence
  Scenario: S4.4 Changes persist after page refresh
    # TOOL: Claude in Chrome
    Given the user has created or edited a check type on the page
    When Claude in Chrome refreshes the page (navigate to same URL)
    Then all previous changes are still visible
    And the newly created/edited check type shows correct values

    # Confidence scoring guide:
    # 1.0 — All changes persist after refresh (data saved to Railway DB)
    # 0.5 — Some changes persist but others revert (partial save)
    # 0.0 — All changes lost after refresh (not saved to DB)

    # Evidence to check:
    # - Screenshot after refresh showing persisted data
    # - Compare values before and after refresh

    # Red flags:
    # - Data reverts to seed defaults after refresh
    # - Client-side only state (not hitting API save endpoint)
    # - API calls fail silently (200 but no DB write)
