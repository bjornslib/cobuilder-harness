Feature: Epic C — Frontend Case Detail Page
  As a customer viewing the checks dashboard
  I need a case detail page with timeline, comparison table, and audio player
  So I can see the full audit trail for my verification case

  Background:
    Given the agencheck-support-frontend repository on branch "feat/dashboard-audit-frontend"
    And the frontend dev server is running at http://localhost:3000

  # --- Page structure ---

  @page-exists @scoring:pass=1.0,fail=0.0
  Scenario: Case detail page exists at correct route
    When I inspect "app/checks-dashboard/cases/[id]/page.tsx"
    Then it exports a default page component
    And it imports useCaseDetail hook from "@/hooks/useCaseDetail"
    And it uses CaseDetail type from "@/types/case"

  @grid-layout @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Page uses 12-column grid layout
    When I inspect the page component JSX
    Then the main content uses "grid grid-cols-12"
    And the left panel uses "col-span-7"
    And the right panel uses "col-span-5"

  # --- Components ---

  @candidate-card @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: CandidateEmployerCard displays candidate and employer
    When I inspect "components/case-detail/CandidateEmployerCard.tsx"
    Then it accepts candidateName and employerName props
    And it renders candidate name with a person icon or avatar
    And it renders employer name with a business icon
    And it uses shadcn Card component

  @comparison-table @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: VerificationComparisonTable shows claimed vs verified data
    When I inspect "components/case-detail/VerificationComparisonTable.tsx"
    Then it accepts a VerificationResult prop
    And it renders column headers "Candidate Claimed" and "AgenCheck Verified"
    And it renders ComparisonRow for each field
    And it shows overall status Badge that pulses when non-terminal

  @comparison-row @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: ComparisonRow shows match/mismatch indicators
    When I inspect "components/case-detail/ComparisonRow.tsx"
    Then it accepts a VerificationField prop
    And matching fields show a green check indicator
    And mismatching fields show an amber warning indicator
    And null/missing values display a dash character

  @timeline @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: ActivityTimeline renders vertical timeline with dot states
    When I inspect "components/case-detail/ActivityTimeline.tsx"
    Then it renders a vertical timeline with "border-l" left border
    And it uses TimelineEvent sub-component for each entry
    And it accepts entries and currentStep props
    And it auto-scrolls to the current step on mount

  @timeline-event @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: TimelineEvent renders with correct dot variants
    When I inspect "components/case-detail/TimelineEvent.tsx"
    Then completed events show a filled dot (bg-teal-500 or similar)
    And current events show a filled dot with pulse animation
    And pending/future events show a dashed outline dot
    And each event displays title, subtitle, and timestamp

  @audio-player @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: CallRecordingPlayer uses HTML5 audio with custom controls
    When I inspect "components/case-detail/CallRecordingPlayer.tsx"
    Then it renders an HTML5 <audio> element
    And it has custom play/pause button (not native browser controls)
    And it shows a progress bar for audio scrubbing
    And it displays elapsed/total duration text

  @page-header @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: CasePageHeader shows breadcrumb and actions
    When I inspect "components/case-detail/CasePageHeader.tsx"
    Then it renders breadcrumb navigation (Dashboard > Checks > Case #id)
    And it shows the check type and status label
    And it includes an actions dropdown menu

  # --- Loading states ---

  @skeleton @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Skeleton loading state matches final layout
    When I inspect "app/checks-dashboard/cases/[id]/loading.tsx"
    Then it renders skeleton placeholders
    And the skeleton uses the same 12-col grid as the final layout

  # --- Data layer ---

  @api-client @scoring:pass=1.0,fail=0.0
  Scenario: API client uses case_id (integer) not task_id
    When I inspect "lib/api/cases.ts"
    Then getCaseById accepts a numeric case_id parameter
    And it calls GET /api/v1/cases/{id}

  @work-history-fix @scoring:pass=1.0,fail=0.0
  Scenario: work-history.ts case_id mapping is fixed
    When I inspect "lib/api/work-history.ts"
    Then the case_id field maps to v.case_id (not v.task_id)

  @react-query @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: useCaseDetail hook has terminal-aware polling
    When I inspect "hooks/useCaseDetail.ts"
    Then it uses useQuery with queryKey including case_id
    And refetchInterval is a callback function (not static number)
    And it returns false when case status is in TERMINAL_STATUSES set
    And it polls at 10_000ms (10s) for active cases

  @types @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: TypeScript types match API contract
    When I inspect "types/case.ts"
    Then CaseDetail interface includes case_id, status, status_label, timeline
    And TimelineEntry interface includes step_order, step_name, channel_type
    And VerificationResult interface includes overall_status and fields array
    And VerificationField interface includes claimed_value, verified_value, match boolean

  # --- Routing ---

  @redirect @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: UUID redirect middleware handles legacy task_id URLs
    When I inspect "middleware.ts"
    Then it detects UUID-pattern path segments in /checks-dashboard/cases/ routes
    And UUID-shaped segments trigger a redirect to the integer case_id URL

  # --- Browser rendering test ---

  @browser @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Case detail page renders in browser with correct layout
    Given the frontend dev server is running at http://localhost:3000
    When I navigate to "/checks-dashboard/cases/1" in the browser
    Then the page loads without JavaScript errors
    And the 12-column grid layout is visible
    And either case data or a "not found" message displays
    And the skeleton loading state appears briefly before data loads
