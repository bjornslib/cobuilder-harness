@prd-P1.1-UNIFIED-FORM-V2 @guardian @v2.1
Feature: Unified Verification Form Page — v2.1 Review Amendments

  Background:
    Given the frontend dev server is running at localhost:5002
    And I navigate to /verify/test-task-123?mode=chat

  # ============================================================
  # S1: Page Layout & Header
  # ============================================================

  @layout @critical
  Scenario: S1.1 — Page header with candidate info and full-width progress bar
    Then the top of the page shows "Live Work History Verification" heading
    And a full-width progress bar spans the entire form area at the top
    And the candidate name "Bjorn Schliebitz — Engage & Experience" appears at top-right
    And there is NO "Task test-task-123" or "Case Reference" text
    And the progress bar is NOT a small widget in a corner

    # Scoring: 1.0 — full-width bar + name top-right | 0.5 — bar present but not full-width | 0.0 — missing

  @layout @critical
  Scenario: S1.2 — Two-panel grid with no tab switcher
    Then the page has a two-panel layout (form left, transcript right)
    And there is NO Chat/Voice tab switcher component
    And mode switching happens via Start Call / End Call

    # Scoring: 1.0 — correct layout, no tabs | 0.5 — layout ok but tabs present | 0.0 — broken

  # ============================================================
  # S2: Progressive Disclosure with Size Hierarchy
  # ============================================================

  @disclosure @critical
  Scenario: S2.1 — Only employment gate visible on load
    Then the employment gate "Was Bjorn Schliebitz employed at Engage & Experience?" is visible
    And the employment gate has compact Yes/No pill buttons
    And NO verification field rows are visible below the gate
    And there is placeholder text indicating fields will appear as the verifier progresses
    And the approval/signature section is NOT visible

    # Scoring: 1.0 — gate only, no fields, no signature | 0.5 — gate + some fields | 0.0 — all fields shown

  @disclosure @critical
  Scenario: S2.2 — First field reveals after employment gate "Yes" — gate shrinks
    When I click "Yes" on the employment gate
    Then the employment gate shrinks to a compact muted grey representation
    And exactly ONE verification field appears below with a fade-in animation
    And the new field is visually expanded (larger than the shrunk gate)
    And the field shows the claimed value as read-only text
    And the field has [Confirm] and [Change] buttons
    And the progress bar increases

    # Scoring: 1.0 — gate shrinks + field expands with animation | 0.5 — reveals but no size change | 0.0 — no reveal

  @disclosure @critical
  Scenario: S2.3 — Next field reveals after confirming current field — current shrinks
    Given the employment gate is confirmed (grey, compact)
    And the first field (Start Date) is the active expanded field
    When I click "Confirm" on the Start Date field
    Then the Start Date field shrinks to a compact muted grey representation
    And the next field (End Date) fades in as the new expanded active field
    And the progress bar increases
    And the approval section is still NOT visible

    # Scoring: 1.0 — sequential shrink/expand + progress | 0.5 — reveals but no size change | 0.0 — no reveal

  @disclosure @critical
  Scenario: S2.4 — Next field reveals after updating current field — current shrinks with marker
    Given a field is in EDITING state with a changed value
    When I click "Update"
    Then the field shrinks to compact grey with a discrepancy marker (amber dot/icon)
    And the next field fades in as the new expanded active field
    And the progress bar increases

    # Scoring: 1.0 — shrink + marker + next expands | 0.5 — reveals but no marker or size change | 0.0 — no reveal

  @disclosure
  Scenario: S2.5 — All fields visible after full completion — approval section appears
    Given all verification fields have been confirmed or updated
    Then all completed fields are visible in compact muted grey
    And the approval section fades into view with animation
    And the approval section shows "Approve Verification" label
    And the name input placeholder reads "Your name"
    And the name input and Submit button are on the same horizontal line

    # Scoring: 1.0 — all compact + approval animates in + inline layout | 0.5 — visible but stacked layout | 0.0 — approval missing

  @disclosure
  Scenario: S2.6 — Employment gate "No" reveals all fields and approval
    When I click "No" on the employment gate
    Then the employment gate shrinks to compact muted grey
    And all verification fields become visible simultaneously
    And the approval section becomes visible
    And the agent acknowledges the "No" response

    # Scoring: 1.0 — all revealed + agent response | 0.5 — partial reveal | 0.0 — nothing happens

  # ============================================================
  # S3: Field States & Interactions
  # ============================================================

  @fields @critical
  Scenario: S3.1 — PENDING (active) state shows claimed value with Confirm/Change — expanded
    Given a field is the currently active field
    Then the field is rendered at expanded size (larger than completed fields)
    And the field is visually highlighted (distinct background/border)
    And the claimed value is shown as read-only text (not an input)
    And a green "Confirm" button and an orange "Change" button are visible

    # Scoring: 1.0 — expanded + highlighted + read-only + both buttons | 0.5 — correct buttons but no size/highlight | 0.0 — missing

  @fields @critical
  Scenario: S3.2 — Confirm transitions to CONFIRMED state — muted grey, compact
    When I click "Confirm" on the active field
    Then the field shrinks to compact size
    And the field background changes to muted grey (NOT green)
    And a subtle checkmark and "Confirmed" text appear
    And a small pencil Edit icon is visible
    And the Confirm/Change buttons are gone

    # Scoring: 1.0 — grey compact + check + edit icon | 0.5 — confirmed but still green or full-size | 0.0 — no state change

  @fields @critical
  Scenario: S3.3 — Change transitions to EDITING state
    When I click "Change" on the active field
    Then the field background changes to amber-50
    And the value becomes an editable input pre-filled with the claimed value
    And "Update" (green) and "Cancel" (grey) buttons appear
    And the Confirm/Change buttons are gone

    # Scoring: 1.0 — amber bg + input + Update/Cancel | 0.5 — editable but wrong buttons | 0.0 — no state change

  @fields @critical
  Scenario: S3.4 — Update transitions to UPDATED — distinct from Confirmed
    Given a field is in EDITING state
    And I have changed the value to something different from the claimed value
    When I click "Update"
    Then the field shrinks to compact size
    And the field has an amber/orange discrepancy marker (distinct from grey confirmed)
    And "Updated" text appears (visually distinct from "Confirmed")
    And a small pencil Edit icon is visible
    And the input becomes read-only text showing the updated value

    # Scoring: 1.0 — compact + distinct marker + different from confirmed | 0.5 — updated but same as confirmed styling | 0.0 — no change

  @fields @critical
  Scenario: S3.5 — Cancel from first edit returns to PENDING (active)
    Given a field is in EDITING state (first time, was active PENDING before)
    When I click "Cancel"
    Then the field returns to active PENDING state (expanded, highlighted)
    And the claimed value is shown as read-only text
    And Confirm/Change buttons reappear

    # Scoring: 1.0 — returns to expanded active | 0.5 — returns but collapsed | 0.0 — stuck in editing

  @fields
  Scenario: S3.6 — Edit icon on CONFIRMED reopens editing
    Given a field is in CONFIRMED state (compact, grey)
    When I click the Edit pencil icon
    Then the field expands to EDITING state
    And the input is pre-filled with the confirmed value
    And Update/Cancel buttons appear

    # Scoring: 1.0 — edit works, field expands | 0.5 — edit icon missing | 0.0 — no edit capability

  @fields
  Scenario: S3.7 — Edit icon on UPDATED reopens editing
    Given a field is in UPDATED state (compact, with discrepancy marker)
    When I click the Edit pencil icon
    Then the field expands to EDITING state
    And the input is pre-filled with the UPDATED value (not claimed)
    And Update/Cancel buttons appear

    # Scoring: 1.0 — pre-fills updated value | 0.5 — pre-fills claimed value | 0.0 — no edit

  @fields
  Scenario: S3.8 — Cancel from re-edit returns to previous resolved state
    Given a field is in CONFIRMED state (compact, grey)
    And I click Edit to enter EDITING state
    When I click "Cancel"
    Then the field returns to CONFIRMED state (compact, grey — not active PENDING)

    # Scoring: 1.0 — returns to CONFIRMED compact | 0.5 — returns to active PENDING | 0.0 — stuck

  # ============================================================
  # S4: Chat Agent Behavior
  # ============================================================

  @agent @critical
  Scenario: S4.1 — Agent introduction animates on page load
    Then the chat panel shows an agent introduction message
    And the message streams in word-by-word (typewriter animation)
    And the message references "Bjorn Schliebitz" and "Engage & Experience"
    And the agent positions itself as a support tool
    And the agent asks about the employment gate

    # Scoring: 1.0 — animated intro with name, support positioning, gate question | 0.5 — intro but no animation | 0.0 — no intro

  @agent @critical
  Scenario: S4.2 — Agent is SILENT when verifier confirms a matching field
    Given a field has just been confirmed (value matches candidate claim)
    Then NO new agent message appears in the chat
    And NO verifier action bubble appears in the chat
    And the chat panel remains unchanged

    # Scoring: 1.0 — complete silence | 0.5 — agent or verifier message appears | 0.0 — N/A

  @agent @critical
  Scenario: S4.3 — Verifier modification appears as chat bubble + AURA responds
    Given a field has just been updated with a different value (discrepancy)
    Then a verifier bubble appears in the chat showing the action (e.g. "Start date updated to 15 Jan 2019")
    And AURA responds with a contextual message that streams in
    And AURA's response references both the updated value and the candidate's original claim
    And AURA offers context capture ("Any additional context, or shall we continue?")

    # Scoring: 1.0 — verifier bubble + animated AURA with both values + context offer | 0.5 — AURA responds but no verifier bubble | 0.0 — silent

  @agent
  Scenario: S4.4 — Agent silent on Change click (entering edit mode)
    When I click "Change" on a field
    Then the agent does NOT send a message
    And NO verifier bubble appears

    # Scoring: 1.0 — silent | 0.5 — sends message | 0.0 — N/A

  @agent
  Scenario: S4.5 — Agent silent on re-edit of resolved field
    When I click Edit on a previously resolved field
    Then the agent does NOT send a message

    # Scoring: 1.0 — silent | 0.5 — sends message | 0.0 — N/A

  @agent
  Scenario: S4.6 — Agent completion summary (all fields resolved)
    Given all fields have been resolved
    Then the agent sends an animated summary message
    And the summary states how many discrepancies were noted
    And the agent instructs to enter name and submit

    # Scoring: 1.0 — animated summary with discrepancy count | 0.5 — generic completion | 0.0 — no summary

  # ============================================================
  # S5: Approval & Submit
  # ============================================================

  @submit @critical
  Scenario: S5.1 — Approval section hidden during form completion
    Given at least one field is still unresolved
    Then the approval section (name input + submit button) is NOT visible in the DOM
    And there is no "Approve Verification" label visible

    # Scoring: 1.0 — completely hidden | 0.5 — visible but disabled | 0.0 — visible and active

  @submit @critical
  Scenario: S5.2 — Approval section appears after all fields resolved — inline layout
    Given all fields are resolved
    Then the approval section fades into view
    And the label reads "Approve Verification"
    And the name input placeholder reads "Your name" (no "e.g." prefix)
    And the name input and "Submit Verification" button are on the SAME horizontal line
    And the submit button is NOT full-width
    And the button is DISABLED when the name input is empty
    When I enter a name in the input
    Then the button becomes ENABLED with gradient styling

    # Scoring: 1.0 — inline layout, correct labels, activation | 0.5 — correct but stacked layout | 0.0 — missing

  @build @critical
  Scenario: S5.3 — TypeScript compilation passes
    When I run `npx tsc --noEmit`
    Then there are zero TypeScript errors

    # Scoring: 1.0 — zero errors | 0.0 — compilation fails

  @build @critical
  Scenario: S5.4 — Next.js build succeeds
    When I run `npm run build`
    Then the build completes successfully

    # Scoring: 1.0 — clean build | 0.5 — warnings only | 0.0 — build fails

  # ============================================================
  # S6: Voice Mode
  # ============================================================

  @voice @critical
  Scenario: S6.1 — Voice mode hides live transcript, chat minimises
    When I start a voice call
    Then the chat panel minimises (animates out of view)
    And a minimal live call indicator is shown (waveform or "On Call" badge)
    And NO transcript text is rendered
    And the form panel remains fully functional

    # Scoring: 1.0 — chat minimised + indicator + no transcript | 0.5 — transcript still showing | 0.0 — no mode change

  @voice
  Scenario: S6.2 — Chat panel re-expandable in voice mode
    Given voice mode is active and chat is minimised
    When I click a toggle/expand control
    Then the chat panel re-expands
    And previous chat messages are still visible

    # Scoring: 1.0 — re-expandable with history | 0.5 — expandable but history lost | 0.0 — cannot expand
