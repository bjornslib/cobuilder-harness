# Acceptance Test Scenarios for PRD-P1.1-VERIFY-CHECK-001
# Functional /verify-check Page — Chat + Voice Verification
#
# Generated: 2026-03-01
# Mode: guardian (blind scoring rubric — implementers never see this)
# Source SDs: 5 Solution Designs covering Epics 1-5

# ============================================================================
# EPIC 1: Backend SSE Wiring & Session Integration (weight: 0.25)
# ============================================================================

@feature-F1 @weight-0.25 @browser-required
Feature: Backend SSE Wiring & Session Integration

  Scenario: S1.1 — Session data loads from sessionStorage
    Given a verify session has been stored via storeVerifySession()
    When Claude in Chrome navigates to http://localhost:3000/verify-check/test-task-123
    Then the page displays the candidate's first name, last name, and company
    And the verify fields from session data are used (not hardcoded)

    # Confidence scoring guide:
    # 1.0 — readVerifySession() called on mount, candidateInfo + verifyFields populated from session data
    # 0.5 — Session read exists but falls back to URL params or hardcoded values
    # 0.0 — MOCK_CLAIMED_DATA still used; no readVerifySession() call

    # Evidence to check:
    # - app/verify-check/[task_id]/page.tsx: useEffect calling readVerifySession()
    # - No references to MOCK_CLAIMED_DATA in page.tsx
    # - lib/verification/verify-session.ts: readVerifySession() function exists

    # Red flags:
    # - MOCK_CLAIMED_DATA constant still present in page.tsx
    # - candidateInfo derived from hardcoded defaults instead of session data
    # - readVerifySession import missing

  Scenario: S1.2 — Listener registration fires on mount
    Given the backend API is running at http://localhost:8000
    When the /verify-check page mounts with a valid task_id
    Then a POST request is sent to /api/live-form-filler/listener/start
    And the payload includes task_id, verify_fields, and room_name
    And the request is only sent once (useRef guard)

    # Confidence scoring guide:
    # 1.0 — POST fires on mount with correct payload, useRef prevents re-fires, error handled gracefully
    # 0.5 — POST fires but missing some payload fields, or fires multiple times
    # 0.0 — No listener registration; SSE stream will 404 without queue initialization

    # Evidence to check:
    # - app/verify-check/[task_id]/page.tsx: useEffect with POST to /listener/start
    # - Network tab shows POST with { task_id, verify_fields, room_name }
    # - useRef guard to prevent duplicate registration

    # Red flags:
    # - No useEffect for listener registration
    # - POST fires on every re-render (missing dependency array or ref guard)
    # - Hardcoded verify_fields instead of from session data

  Scenario: S1.3 — SSE connection receives and dispatches events
    Given the listener has been registered for task_id
    When the backend pushes a STATE_SNAPSHOT event
    Then the v2 Zustand store initFields() is called with field definitions
    When the backend pushes a STATE_DELTA event with field data
    Then the field display values are updated on the page
    When the backend pushes a TRANSCRIPT_MESSAGE event
    Then the message appears in the transcript panel

    # Confidence scoring guide:
    # 1.0 — All 3 event types handled: STATE_SNAPSHOT→initFields, STATE_DELTA→field update, TRANSCRIPT_MESSAGE→append
    # 0.5 — Only 1-2 event types handled, or SSE connected but events not dispatched to store
    # 0.0 — useFormSSE not connected to real /stream endpoint; still using mock data

    # Evidence to check:
    # - app/verify-check/[task_id]/_hooks/useFormSSE.ts exists and connects to /api/live-form-filler/stream
    # - onSnapshot callback calls store.initFields()
    # - onFieldUpdate callback dispatches to handleFieldUpdate
    # - onTranscriptMessage callback appends to messages array
    # - DevTools EventSource tab shows events flowing

    # Red flags:
    # - useFormSSE.ts missing from verify-check/_hooks/
    # - Callbacks defined but not wired to useFormSSE options
    # - SSE endpoint URL hardcoded incorrectly

  Scenario: S1.4 — Connection status badge reflects SSE state
    Given the SSE connection is established
    When Claude in Chrome navigates to the /verify-check page
    Then a connection status indicator shows "Connected" (green)
    When the SSE connection drops
    Then the indicator changes to "Reconnecting" (amber)

    # Confidence scoring guide:
    # 1.0 — Badge renders with correct color states; onConnectionChange wired to visual indicator
    # 0.5 — Badge exists but doesn't reflect actual SSE state (hardcoded or always shows one state)
    # 0.0 — No connection status indicator on the page

    # Evidence to check:
    # - ConnectionStatusBadge component in verify-check/_components/
    # - onConnectionChange callback updates badge state
    # - CSS/className changes for connected/reconnecting/error states

    # Red flags:
    # - Badge always shows "Connected" regardless of actual state
    # - No ConnectionStatusBadge component imported or rendered

# ============================================================================
# EPIC 2: SSE-Driven Field Advancement — Voice Mode (weight: 0.30)
# ============================================================================

@feature-F2 @weight-0.30 @hybrid
Feature: SSE-Driven Field Advancement (Voice Mode)

  Scenario: S2.1 — Backend VerifiedFieldData includes field_action
    Given the VerifiedFieldData Pydantic model in state.py
    Then it includes a field_action attribute of type str | None with default None
    And the field_action passes through push_event() to the SSE STATE_DELTA payload
    And existing consumers (verify-call) are unaffected (backward compatible)

    # Confidence scoring guide:
    # 1.0 — field_action: str | None = None in VerifiedFieldData, serialized in STATE_DELTA, verify-call unaffected
    # 0.5 — Field added to model but not serialized in SSE events, or naming mismatch
    # 0.0 — No field_action field in VerifiedFieldData model

    # Evidence to check:
    # - agencheck-support-agent/live_form_filler/state.py: VerifiedFieldData class
    # - agencheck-support-agent/live_form_filler/ag_ui_routes.py: push_event serialization
    # - Existing /verify-call tests still pass (no regression)

    # Red flags:
    # - field_action is required (not optional) — breaks backward compatibility
    # - Field name differs between backend model and SSE payload
    # - field_action added but never set by any code path

  Scenario: S2.2 — Frontend auto-confirms field on field_action: "confirm"
    Given a field "start_date" is in PENDING status in the v2 store
    When an SSE STATE_DELTA arrives with start_date.field_action = "confirm"
    Then the store.confirmField("start_date") is called
    And the field transitions to CONFIRMED status
    And store.revealNextField() reveals the next hidden field
    And the confirmation happens within ~500ms of SSE event

    # Confidence scoring guide:
    # 1.0 — handleSSEFieldUpdate bridge function dispatches confirmField + revealNextField on "confirm"
    # 0.5 — Field updates display but doesn't auto-confirm (field_action ignored)
    # 0.0 — No bridge function; field_action field not parsed from SSE data

    # Evidence to check:
    # - app/verify-check/[task_id]/page.tsx: handleSSEFieldUpdate or handleFieldUpdate function
    # - Switch/if on data.field_action === 'confirm'
    # - store.confirmField(fieldName) call followed by store.revealNextField()
    # - stores/slices/verificationFormSlice.ts: confirmField + revealNextField work atomically

    # Red flags:
    # - field_action parsed but only logged, not acted upon
    # - confirmField called but revealNextField missing (field confirms but form doesn't advance)
    # - Race condition: field confirms before it's in PENDING status

  Scenario: S2.3 — Frontend auto-updates field on field_action: "update"
    Given a field "position_title" is in PENDING status
    When an SSE STATE_DELTA arrives with position_title.field_action = "update" and verified_value = "Lead Engineer"
    Then the store.startEditing("position_title") is called
    And store.updateField("position_title", "Lead Engineer") sets the corrected value
    And the field transitions to UPDATED status with hasDiscrepancy = true
    And store.revealNextField() reveals the next field

    # Confidence scoring guide:
    # 1.0 — Full update chain: startEditing → updateField → revealNextField, discrepancy tracked
    # 0.5 — Value updates but discrepancy flag not set, or revealNextField missing
    # 0.0 — "update" field_action not handled in bridge function

    # Evidence to check:
    # - handleSSEFieldUpdate: case 'update' branch
    # - store.startEditing → store.updateField → store.revealNextField sequence
    # - hasDiscrepancy set to true when verified_value differs from claimedValue

    # Red flags:
    # - Only "confirm" handled, "update" case missing
    # - updateField called without startEditing first (invalid state transition)

  Scenario: S2.4 — Confirmation animation completes before next field reveals
    Given a field is being auto-confirmed via SSE
    When the confirmField action fires
    Then the field row shows a green background transition (~300ms)
    And the next field reveals AFTER the animation completes (not simultaneously)

    # Confidence scoring guide:
    # 1.0 — setTimeout(revealNextField, 350) or requestAnimationFrame delay; CSS transition-colors on VerifyFieldRow
    # 0.5 — Both happen simultaneously (no delay) — functionally correct but visually jarring
    # 0.0 — No animation; field just snaps to confirmed state

    # Evidence to check:
    # - page.tsx: setTimeout or delay between confirmField and revealNextField
    # - VerifyFieldRow.tsx: transition-colors, duration-300 or similar CSS transition class
    # - Timing: ~300-400ms delay between confirm and reveal

    # Red flags:
    # - confirmField and revealNextField called synchronously with no delay
    # - Animation CSS exists but transition duration is 0ms

  Scenario: S2.5 — Backward compatibility when field_action is absent
    Given a STATE_DELTA event arrives WITHOUT a field_action field
    Then the field display value updates normally
    And no auto-confirm or auto-update action is taken
    And the user must manually click Confirm or Change

    # Confidence scoring guide:
    # 1.0 — Default/null case in bridge function does nothing beyond display update; /verify-call unaffected
    # 0.5 — field_action absence causes a console error but doesn't break functionality
    # 0.0 — Code crashes when field_action is undefined; or all fields auto-confirm even without field_action

    # Evidence to check:
    # - handleSSEFieldUpdate: default case (no field_action) just updates display
    # - /verify-call page.tsx: does NOT parse field_action (unchanged from merge)
    # - No runtime errors when field_action is missing from SSE payload

    # Red flags:
    # - field_action treated as required (no null check)
    # - Default case accidentally triggers confirmField

# ============================================================================
# EPIC 3: Form Submission & Completion Flow (weight: 0.20)
# ============================================================================

@feature-F3 @weight-0.20 @browser-required
Feature: Form Submission & Completion Flow

  Scenario: S3.1 — Mock data removed from page
    Given the verify-check page.tsx source code
    Then the MOCK_CLAIMED_DATA constant does not exist
    And field initialization comes from SSE STATE_SNAPSHOT (via store.initFields)
    And no hardcoded field values remain

    # Confidence scoring guide:
    # 1.0 — MOCK_CLAIMED_DATA deleted; fields initialized exclusively from SSE snapshot via store
    # 0.5 — MOCK_CLAIMED_DATA still exists as fallback but SSE is primary source
    # 0.0 — MOCK_CLAIMED_DATA is still the primary data source

    # Evidence to check:
    # - app/verify-check/[task_id]/page.tsx: search for "MOCK_CLAIMED_DATA"
    # - No hardcoded field values like "January 15, 2023" or "$145,000"
    # - initFields called from onSnapshot callback

    # Red flags:
    # - MOCK_CLAIMED_DATA renamed but still present
    # - Local fields state still initialized from mock values

  Scenario: S3.2 — Submission payload matches backend contract
    Given all fields are confirmed/updated in the v2 store
    When the verifier clicks Submit
    Then a POST is sent to /api/live-form-filler/submit
    And the payload includes: task_id, case_id, verifier_name, was_employed, fields[], claimed_data
    And each field in fields[] has: field_name, verified_value, confidence

    # Confidence scoring guide:
    # 1.0 — Payload exactly matches backend contract; case_id from SSE snapshot; fields from store
    # 0.5 — Payload sent but missing case_id or claimed_data (partial contract compliance)
    # 0.0 — Submission not wired; or payload uses wrong field names

    # Evidence to check:
    # - handleSubmit function in page.tsx
    # - payload construction maps storeFields to { field_name, verified_value, confidence }
    # - case_id and claimedData from STATE_SNAPSHOT (not hardcoded)
    # - Network tab: POST body structure

    # Red flags:
    # - case_id hardcoded as null
    # - fields[] maps from local state instead of v2 store
    # - claimed_data is empty object {}

  Scenario: S3.3 — Submit button guard prevents premature submission
    Given the verify-check page is loaded
    When not all fields are confirmed/updated
    Then the Submit button is disabled
    When verifierName is empty
    Then the Submit button is disabled
    When wasEmployed is null
    Then the Submit button is disabled
    When all conditions are met
    Then the Submit button is enabled

    # Confidence scoring guide:
    # 1.0 — canSubmit correctly checks: verifierName + !isSubmitting + (wasEmployed===false || allResolved)
    # 0.5 — Some guards work but missing one condition (e.g., wasEmployed check missing)
    # 0.0 — Submit button always enabled; no guard logic

    # Evidence to check:
    # - canSubmit computed value in page.tsx
    # - Button disabled={!canSubmit} prop
    # - areAllFieldsResolved() from v2 store

    # Red flags:
    # - canSubmit only checks verifierName, ignores field resolution
    # - isSubmitting guard missing (allows double-submit)

  Scenario: S3.4 — Thank-you redirect after successful submission
    Given all fields are resolved and verifier name is entered
    When the verifier clicks Submit and the backend returns success
    Then a success toast appears
    And the page redirects to a thank-you page (not /verify-call/thank-you)

    # Confidence scoring guide:
    # 1.0 — Toast shown + redirect to /verify-check/thank-you (or shared /verification/thank-you)
    # 0.5 — Redirect works but goes to /verify-call/thank-you (wrong route)
    # 0.0 — No redirect; page stays on form after submission

    # Evidence to check:
    # - router.push() target in handleSubmit success path
    # - toast.success() call present
    # - Thank-you page exists at the redirect target

    # Red flags:
    # - Redirect target still says '/verify-call/thank-you' (copy-paste from verify-call)
    # - Thank-you page doesn't exist (404 after redirect)

# ============================================================================
# EPIC 4: LiveKit Chat Mode Integration (weight: 0.15)
# ============================================================================

@feature-F4 @weight-0.15 @browser-required
Feature: LiveKit Chat Mode Integration

  Scenario: S4.1 — Chat token in session data
    Given a chat verification is initiated
    When storeVerifySession() is called for chat mode
    Then the session data includes a chatToken field
    And readVerifySession() returns the chatToken
    And VerifyCallSessionData type includes chatToken as optional string

    # Confidence scoring guide:
    # 1.0 — chatToken field added to type, stored in session, read on mount, passed to useAgentMessages
    # 0.5 — Type updated but chatToken never populated by the calling page
    # 0.0 — No chatToken field; chat mode still uses mock responses

    # Evidence to check:
    # - lib/verification/types.ts: VerifyCallSessionData.chatToken
    # - lib/verification/verify-session.ts: chatToken stored and retrieved
    # - page.tsx: chatToken passed to useAgentMessages hook

    # Red flags:
    # - chatToken always undefined/null at runtime
    # - Type exists but storeVerifySession never sets it

  Scenario: S4.2 — Real agent messages via lk.chat topic
    Given a verify-check page is opened in chat mode (no voice token)
    When the verifier types a message and sends it
    Then the message is published to the LiveKit lk.chat data topic
    And the agent receives the message and responds
    And the response appears as a chat bubble in the TranscriptPanel

    # Confidence scoring guide:
    # 1.0 — useAgentMessages connects to LiveKit Room, publishes on lk.chat, receives agent responses
    # 0.5 — LiveKit connection established but messages don't flow (encoding issue or topic mismatch)
    # 0.0 — Still using mock useAgentMessages with scripted responses

    # Evidence to check:
    # - app/verify-check/[task_id]/_hooks/useAgentMessages.ts: Room connection + data channel
    # - publishData on lk.chat topic
    # - RoomEvent.DataReceived listener for incoming messages
    # - TranscriptPanel renders received messages

    # Red flags:
    # - useAgentMessages still returns hardcoded mock messages
    # - Room.connect() called but no data event listener
    # - Topic mismatch: publishing on "chat" instead of "lk.chat"

  Scenario: S4.3 — Fallback to mock when no chatToken available
    Given no chatToken is in the session data
    When the verify-check page opens in chat mode
    Then the mock agent behavior is used as fallback
    And the page does not crash or show errors

    # Confidence scoring guide:
    # 1.0 — Graceful fallback: no chatToken → mock responses, no console errors
    # 0.5 — Fallback exists but shows connection error before falling back
    # 0.0 — Page crashes when chatToken is missing; or always uses mock (real chat never works)

    # Evidence to check:
    # - useAgentMessages: conditional logic based on chatToken presence
    # - No unhandled promise rejections when chatToken is undefined

    # Red flags:
    # - Unconditional Room.connect() that throws when chatToken is null
    # - Error boundary catches crash but user sees error flash

# ============================================================================
# EPIC 5: Form Event Publishing — Frontend → Agent (weight: 0.10)
# ============================================================================

@feature-F5 @weight-0.10 @hybrid
Feature: Form Event Publishing (Frontend → Agent)

  Scenario: S5.1 — publishFormEvent helper function exists
    Given the verify-check page source code
    Then a publishFormEvent function exists that:
    And serializes events to JSON
    And publishes on the "form_events" LiveKit data topic
    And uses reliable delivery (TCP-like)
    And is a no-op when room is null or not connected

    # Confidence scoring guide:
    # 1.0 — Function exists, publishes correctly, graceful no-op when disconnected
    # 0.5 — Function exists but missing reliable flag or no-op guard
    # 0.0 — No publishFormEvent function; events not published to agent

    # Evidence to check:
    # - page.tsx or separate hook: publishFormEvent(room, event) function
    # - room.localParticipant.publishData() with topic: "form_events", reliable: true
    # - Null check on room and localParticipant

    # Red flags:
    # - Events published on wrong topic (e.g., "lk.chat" instead of "form_events")
    # - No null check — crashes when LiveKit room not connected

  Scenario: S5.2 — FIELD_CONFIRMED event emitted on manual confirm
    Given the verifier is on the verify-check page with an active LiveKit room
    When the verifier manually clicks "Confirm" on a pending field
    Then a FIELD_CONFIRMED event is published with fieldName, claimedValue, verifiedValue, timestamp

    # Confidence scoring guide:
    # 1.0 — useEffect watches store field status transitions; FIELD_CONFIRMED emitted on pending→confirmed
    # 0.5 — Event emitted but missing some payload fields
    # 0.0 — No event emitted when user confirms a field

    # Evidence to check:
    # - page.tsx: useEffect watching storeFields for status transitions
    # - useRef tracking previous field statuses to detect pending→confirmed
    # - publishFormEvent called with type: "FIELD_CONFIRMED"

    # Red flags:
    # - No useEffect watching field status changes
    # - Events emitted on every render (not only on transitions)

  Scenario: S5.3 — DISCREPANCY_DETECTED event emitted on field correction
    Given the verifier edits a field and submits a different value
    When the field transitions from editing → updated
    Then a DISCREPANCY_DETECTED event is published
    And the event includes both claimedValue and the new verifiedValue

    # Confidence scoring guide:
    # 1.0 — DISCREPANCY_DETECTED emitted on editing→updated transition with both values
    # 0.5 — Event emitted but claimedValue missing (only verifiedValue included)
    # 0.0 — No discrepancy event emitted

    # Evidence to check:
    # - page.tsx: transition detection for editing→updated
    # - publishFormEvent with type: "DISCREPANCY_DETECTED"
    # - Payload includes fieldName, claimedValue, verifiedValue

    # Red flags:
    # - Only FIELD_CONFIRMED handled; DISCREPANCY_DETECTED case missing

  Scenario: S5.4 — Agent acknowledges form events
    Given the voice agent is connected and receiving data events
    When a FIELD_CONFIRMED event is received on the form_events topic
    Then the agent acknowledges the confirmation (e.g., "Got it, start date confirmed")
    And the agent skips asking about that field in subsequent prompts

    # Confidence scoring guide:
    # 1.0 — Agent has on_data_received handler for form_events; marks field confirmed; generates acknowledgment
    # 0.5 — Agent receives events but doesn't acknowledge or skip confirmed fields
    # 0.0 — Agent has no data event handler; form events are ignored

    # Evidence to check:
    # - voice_agent/verification_agents.py: @room.on("data_received") or equivalent handler
    # - Topic filter for "form_events"
    # - Agent internal state updated to skip confirmed fields
    # - Agent generates brief verbal/text acknowledgment

    # Red flags:
    # - No data event listener in agent code
    # - Agent re-asks about already-confirmed fields (events received but not tracked)
