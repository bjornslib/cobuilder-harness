@journey @prd-P1.1-UEA-DEPLOY-001 @J2 @browser @api @db @claude-in-chrome
Feature: Browser SLA Configuration Persists to Railway DB

  Scenario J2: User creates check type in browser, verify persisted in Railway
    # Goal G2: /check-sla-configuration renders correctly on Vercel
    # Goal G3: SLA CRUD API works end-to-end
    # This journey crosses: Browser → API → DB → Browser (refresh verify)

    # Browser layer — navigate and authenticate
    # TOOL: Claude in Chrome
    Given Claude in Chrome navigates to https://agencheck.vercel.app/check-sla-configuration
    And the user authenticates via Clerk

    # Browser layer — create check type via form
    # TOOL: Claude in Chrome
    When Claude in Chrome clicks the create/add button
    And Claude in Chrome fills name = "j2_browser_type" and SLA hours = 42
    And Claude in Chrome clicks Save

    # Browser layer — verify in UI
    # TOOL: Claude in Chrome
    Then the table shows j2_browser_type with SLA hours 42

    # DB layer — verify persistence
    # TOOL: direct psql query
    And the check_types table in Railway has name = 'j2_browser_type' and default_sla_hours = 42

    # API layer — cross-validate via API
    # TOOL: curl GET
    When I GET /api/v1/sla/check-types
    Then the response includes j2_browser_type with default_sla_hours = 42

    # Browser layer — refresh and verify persistence
    # TOOL: Claude in Chrome
    When Claude in Chrome refreshes the page
    Then j2_browser_type still appears with SLA hours 42

    # Business outcome
    And the browser → API → DB → browser round-trip proves full-stack persistence
