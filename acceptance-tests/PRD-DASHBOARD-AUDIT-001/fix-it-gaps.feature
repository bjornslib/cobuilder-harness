Feature: Fix-It Gaps — Validation Defects from Initial Scoring
  As a quality assurance guardian
  I need the 6 gaps identified during independent validation to be resolved
  So the weighted acceptance score reaches ≥ 0.90

  Background:
    Given the agencheck-support-agent repository on branch "feat/dashboard-audit-perstep"
    And the agencheck-support-frontend repository on branch "feat/dashboard-audit-frontend"

  # --- Epic C Frontend Fixes ---

  @fix-employer-icon @scoring:pass=1.0,fail=0.0
  Scenario: CandidateEmployerCard renders a business icon for employer
    When I inspect "components/case-detail/CandidateEmployerCard.tsx"
    Then the employer section renders an icon (Building, Briefcase, or similar business icon)
    And the icon is imported from lucide-react or @radix-ui/react-icons

  @fix-completed-dots @scoring:pass=1.0,fail=0.0
  Scenario: TimelineEvent completed dots are filled, not hollow
    When I inspect "components/case-detail/TimelineEvent.tsx"
    Then completed events use a filled background color (bg-teal-500, bg-green-500, or similar)
    And completed events do NOT use bg-white as the dot background
    And current events retain pulse animation (animate-pulse)
    And pending events retain dashed border outline

  @fix-status-label @scoring:pass=1.0,fail=0.0
  Scenario: CasePageHeader renders the statusLabel prop
    When I inspect "components/case-detail/CasePageHeader.tsx"
    Then the statusLabel prop is rendered in the JSX (not just accepted in the interface)
    And it appears as a Badge or text element near the check type
    And it is visible in the header area

  @fix-polling-interval @scoring:pass=1.0,fail=0.0
  Scenario: useCaseDetail hook polls at 10000ms (10 seconds)
    When I inspect "hooks/useCaseDetail.ts"
    Then the refetchInterval returns 10000 (or 10_000) for active cases
    And it returns false for terminal statuses
    And the refetchInterval is a callback function, not a static number

  # --- Epic B Backend Fix ---

  @fix-status-mapper @scoring:pass=1.0,fail=0.0
  Scenario: StatusLabelMapper maps all 14 CallResultStatus enum values
    When I inspect "utils/status_labels.py"
    Then _RESULT_STATUS_MAP contains exactly the 14 CallResultStatus values
    And the value "partial_verification" is explicitly mapped
    And no unmapped enum values rely on the fallback .replace("_", " ").title()
    And the word "unreachable" does not appear in any label

  # --- Docker Rebuild ---

  @docker-rebuild @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Docker container runs code from feature branch
    Given the backend Docker container is rebuilt from feat/dashboard-audit-perstep
    When I send GET request to "/api/v1/cases/1"
    Then the response status is 200 or 404 (not "Not Found" from missing route)
    And if 200, the response body includes "case_id" and "timeline" fields
    And the StatusLabelMapper labels are present in the response
