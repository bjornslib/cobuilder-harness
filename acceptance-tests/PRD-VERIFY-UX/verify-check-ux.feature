Feature: Verify-Check UX Improvements from Hayden Feedback
  As a form verifier
  I want to see clear visual progress and interact with the form efficiently
  So that I can focus on verification without distraction

  Background:
    Given I navigate to /verify-check/[any-task-id]
    And the form loads with "Work History Verification" heading
    And employment status is "Was Employed"

  # Feature 1: Progress Bar
  Scenario: Progress bar appears at full width with gradient at top
    Then the progress bar is visible at the absolute top of the card
    And the progress bar spans the full width (left to right edges)
    And the progress bar has a blue-to-purple gradient (from-blue-500 to-purple-600)
    And the progress bar is positioned ABOVE the "Work History Verification" title
    And the progress bar height is approximately 4-6px (thin, not a full component)

  Scenario: Progress bar grows from 0% to 100% as fields are confirmed
    Then the progress bar width is 0% initially
    When I confirm the first employment field
    Then the progress bar width increases to approximately 12.5% (1/8 fields confirmed)
    When I confirm all remaining fields (7 more)
    Then the progress bar width reaches 100%
    And the progress bar is full width across the card

  # Feature 2: Field Expansion/Shrinking
  Scenario: Active field displays with blue border and expanded padding
    Given I have 0 confirmed fields
    And the first field "Position Title" is shown as active/pending
    Then the active field has:
      | Property | Value |
      | Background Color | Transparent or white |
      | Left Border | 4px solid blue (#3b82f6) |
      | Padding | py-4 (larger vertical padding) |
      | Text Size | Normal/full size |
      | Padding Left | pl-4 (extra padding due to border) |

  Scenario: Just-confirmed field shrinks and shows muted appearance
    Given I have confirmed one field
    When I confirm a field and see the checkmark
    Then the confirmed field:
      | Property | Value |
      | Background Color | Muted gray or transparent |
      | Text Color | text-gray-400 (muted) |
      | Padding | py-1 or py-2 (reduced) |
      | Opacity | 75% or reduced opacity |
      | Text Size | Small, de-emphasized |

  Scenario: Completed fields remain shrunk throughout form
    Given I confirm multiple fields in sequence
    When I have 4 confirmed fields
    Then all 4 confirmed fields maintain:
      | Property | Value |
      | Shrunken state | Yes (py-1-2, reduced padding) |
      | Muted appearance | Yes (gray text, 75% opacity) |
      | Not expanded | Yes (do not grow back) |

  Scenario: Field state transitions are smooth with animation
    When I click "Confirm" on the active field
    Then the field transition from active to confirmed takes 300ms
    And the transition uses transition-all duration-300
    And no abrupt visual jumps occur

  # Feature 3: Chat Agent Behavior
  Scenario: Welcome message appears on page load
    When the page loads
    Then an agent welcome message appears in the chat panel
    And the welcome message types out character-by-character (typewriter animation)
    And the animation completes within 3-5 seconds

  Scenario: Agent does NOT respond when confirming field values
    Given the initial welcome message is displayed
    When I click "Yes" on the employment question
    Then no new chat message appears
    And the chat remains silent

  Scenario: Agent does NOT respond to normal "Confirm" clicks
    Given I have the employment form open
    When I review a field and click "Confirm"
    Then no agent message appears in chat
    And the chat remains unchanged

  Scenario: Agent ONLY responds when verifier uses "Change" button
    Given I confirm a field with value "Acme Corp"
    When I click the "Change" button on that field
    Then the agent responds in chat with a message containing context about the change
    And the agent message appears within 2-3 seconds
    And the chat shows exactly one new message (the change response)

  # Feature 4: Signature Field Visibility
  Scenario: Signature field is hidden until all fields are complete
    When I load the form with 8 pending fields
    Then the "Your name" input field is NOT visible
    And the Submit button is NOT visible
    And the bottom bar does not render

  Scenario: Signature field appears when all fields are confirmed
    Given I have 7 fields confirmed and 1 pending
    When I confirm the last field
    Then the bottom bar appears with smooth transition
    And the "Your name" input field is visible
    And the Submit button is visible
    And the form footer is properly aligned

  # Feature 5: Label Language
  Scenario: Signature input uses plain language
    When the signature input is visible
    Then the input label reads "Your name" (NOT "Verifier")
    And the placeholder text reads "Type your full name to confirm" (NOT "EG")
    And no industry jargon appears in the signature section

  # Feature 6: Chat Panel Minimization During Voice
  Scenario: Chat panel minimizes to LIVE badge during voice call
    Given I have the form and chat visible
    When I click "Start Call"
    Then the TranscriptPanel minimizes:
      | Element | State |
      | Full message list | Hidden |
      | Text input field | Hidden |
      | LIVE badge | Visible (top-left, small) |
      | Animated waveform | Visible (center) |
      | "End Call" button | Visible (top-right, red) |

  Scenario: Voice mode LIVE indicator shows call status
    When in voice mode
    Then I see a small green "●" dot (or similar indicator)
    And the "LIVE" text appears next to the indicator
    And the waveform animates to show audio activity

  Scenario: Chat panel expands back when call ends
    Given I am in minimized voice mode
    When I click "End Call"
    Then the TranscriptPanel expands back to full width
    And the message list reappears
    And the text input field reappears
    And the transition is smooth (300-500ms)

  # Feature 7: Candidate Info De-emphasis
  Scenario: Candidate info appears with reduced visual weight
    When the form loads
    Then the candidate information (name, company) appears with:
      | Property | Value |
      | Text Size | Smaller (text-xs or similar) |
      | Color | Muted gray (text-gray-400) |
      | Visual Weight | Clearly secondary to form fields |
      | Not emphasized | Yes (no bold borders or large containers) |

  Scenario: Candidate info does not distract from form
    When I look at the form layout
    Then the candidate info is visually subordinate to:
      | Element |
      | Progress bar |
      | Form title |
      | Active field |
      | Confirm/Change buttons |

  # Feature 8: Overall Form Layout (Integration)
  Scenario: Full form layout matches design specification
    When the form is fully loaded with all 8 fields
    Then I see from top to bottom:
      | Layer | Component |
      | 1 | Full-width blue-purple gradient progress bar (thin, ~6px) |
      | 2 | Muted candidate info (name, company) |
      | 3 | "Work History Verification" heading |
      | 4 | Form fields (active expanded, confirmed shrunk) |
      | 5 | Chat panel on right (or minimized if voice active) |
      | 6 | Signature input (only when all fields complete) |

  # Feature 9: No Regressions (Keep What Works)
  Scenario: Progressive field disclosure still works
    When I load the form
    Then only relevant employment fields are shown
    And fields are not all displayed at once
    And the user can see progress as fields are completed

  Scenario: Confirm/Change interaction model preserved
    When viewing a field
    Then each field has both "Confirm" and "Change" buttons
    And clicking "Confirm" marks field as resolved (with checkmark)
    And clicking "Change" triggers agent response in chat

  Scenario: Voice/Chat toggle works as before
    When in form mode
    Then I can click "Start Call" to enter voice mode
    And when in voice mode, I can click "End Call" to return to text mode
    And the form state persists across mode switches
