# Blind acceptance test scenarios for PRD-STORY-ZUSTAND-001
# Generated from SD-STORY-ZUSTAND-001-store-foundation.md
# Mode: guardian (confidence scoring rubric — NOT executable)
#
# These scenarios live in the config repo (claude-harness-setup).
# Meta-orchestrators and workers in the impl repo (story-writer) cannot see them.

# ============================================================================
# F1.1 — Install Zustand and Create Store Shell (weight: 0.05)
# ============================================================================

@feature-F1.1 @weight-0.05
Feature: Zustand store installation

  Scenario: S1.1 — Package is installed
    Given I am in the web/ directory
    When I inspect package.json
    Then "zustand" appears in dependencies with version "^5.0.0"

    # Confidence scoring guide:
    # 1.0 — zustand ^5.0.0 in dependencies, package-lock.json updated
    # 0.5 — zustand present but wrong version (e.g., ^4.x)
    # 0.0 — zustand not in package.json at all

    # Evidence to check:
    # - web/package.json "dependencies" object
    # - web/package-lock.json zustand entry

    # Red flags:
    # - zustand in devDependencies instead of dependencies
    # - Version pinned to 4.x (wrong persist API)

  Scenario: S1.2 — Store exports typed hook
    Given storyStore.ts exists at web/src/stores/storyStore.ts
    When I import { useStoryStore } from './stores/storyStore'
    Then useStoryStore is a function that returns the store state

    # Confidence scoring guide:
    # 1.0 — File exists, exports useStoryStore, TypeScript types are strict
    # 0.5 — File exists but uses 'any' types or default export
    # 0.0 — File does not exist or has no named export

    # Evidence to check:
    # - web/src/stores/storyStore.ts exists
    # - Named export: export const useStoryStore = create<StoryState>()(...)
    # - StoryState interface defined with all fields

    # Red flags:
    # - export default create(...) instead of named export
    # - Missing TypeScript generic parameter on create()
    # - 'any' type anywhere in the file

  Scenario: S1.3 — TypeScript compilation succeeds
    When I run tsc --noEmit inside web/
    Then exit code is 0
    And no "any" types appear in storyStore.ts

    # Confidence scoring guide:
    # 1.0 — tsc --noEmit exits 0, grep for 'any' in storyStore.ts returns empty
    # 0.5 — tsc exits 0 but 'any' types present
    # 0.0 — tsc fails with type errors

    # Evidence to check:
    # - Run: cd web && npx tsc --noEmit
    # - Run: grep -n 'any' web/src/stores/storyStore.ts

    # Red flags:
    # - @ts-ignore or @ts-expect-error comments
    # - Type assertions (as any, as unknown)


# ============================================================================
# F1.2 — Story Session State Slice (weight: 0.30)
# ============================================================================

@feature-F1.2 @weight-0.30
Feature: Story session state shape and actions

  Scenario: S2.1 — StoredSession extends SessionSummary
    Given StoredSession is imported from features/session/types
    Then it has all SessionSummary fields: session_id, characters,
      player_character_id, ai_character_ids, conversation_state,
      story_context, interaction_history
    And it has additional fields: createdAt, updatedAt, isLocal, storyText

    # Confidence scoring guide:
    # 1.0 — StoredSession extends SessionSummary with all 4 extra fields, strict types
    # 0.5 — Type exists but missing fields or not extending SessionSummary
    # 0.0 — StoredSession type does not exist

    # Evidence to check:
    # - web/src/features/session/types.ts — StoredSession interface
    # - Must use "extends SessionSummary" (not duplicate fields)
    # - createdAt: string, updatedAt: string, isLocal: boolean, storyText: string

    # Red flags:
    # - Duplicating SessionSummary fields instead of extending
    # - Missing interaction_history (the conversation data)
    # - storyText typed as optional when it should be required

  Scenario: S2.2 — addSession appends to sessions
    Given the store has 0 sessions
    When I call addSession with a valid StoredSession
    Then store.sessions has length 1

    # Confidence scoring guide:
    # 1.0 — Test exists and passes: addSession creates new entry, sessions grows by 1
    # 0.5 — Action exists but no test, or test uses mocks instead of real store
    # 0.0 — addSession action missing from store

    # Evidence to check:
    # - storyStore.ts: addSession implementation uses set() with spread
    # - storyStore.test.ts: test for addSession

    # Red flags:
    # - Direct array mutation (state.sessions.push) instead of spread
    # - Missing from StoryState interface

  Scenario: S2.3 — removeSession removes by session_id
    Given the store has sessions ["s1", "s2"]
    When I call removeSession("s1")
    Then store.sessions has length 1
    And store.sessions[0].session_id equals "s2"

    # Confidence scoring guide:
    # 1.0 — Correctly filters by session_id, verified in test
    # 0.5 — Filters but no test, or filters by wrong field
    # 0.0 — removeSession missing or broken

    # Evidence to check:
    # - storyStore.ts: removeSession uses .filter(s => s.session_id !== sessionId)
    # - Test verifies correct session removed and other retained

    # Red flags:
    # - Filtering by index instead of session_id
    # - Using splice (mutation) instead of filter (immutable)

  Scenario: S2.4 — removeSession on active session resets activeSessionId
    Given activeSessionId is "s1"
    When I call removeSession("s1")
    Then activeSessionId is null

    # Confidence scoring guide:
    # 1.0 — Single set() call handles both filter AND activeSessionId reset, test exists
    # 0.5 — Resets activeSessionId but in a separate set() call (race condition risk)
    # 0.0 — Does not reset activeSessionId at all

    # Evidence to check:
    # - storyStore.ts: removeSession checks state.activeSessionId === sessionId
    # - Both filter and reset happen in the SAME set() callback
    # - storeActions.test.ts: test for this edge case

    # Red flags:
    # - Two separate set() calls (set filter, then set activeSessionId)
    # - Missing this edge case entirely

  Scenario: S2.5 — setActiveSession sets the active ID
    When I call setActiveSession("s2")
    Then store.activeSessionId equals "s2"

    # Confidence scoring guide:
    # 1.0 — Simple set({ activeSessionId }), test exists
    # 0.5 — Works but uses unnecessary updater function
    # 0.0 — Missing

    # Evidence to check:
    # - storyStore.ts: setActiveSession implementation
    # - Test verifies activeSessionId changes

  Scenario: S2.6 — updateSession merges patch and updates timestamp
    Given sessions contains session with session_id "s1"
    When I call updateSession("s1", { storyText: "updated" })
    Then sessions[0].storyText equals "updated"
    And sessions[0].updatedAt is a recent ISO string

    # Confidence scoring guide:
    # 1.0 — Spreads patch onto session, always stamps updatedAt, test exists
    # 0.5 — Merges patch but doesn't auto-stamp updatedAt
    # 0.0 — Missing or replaces entire session instead of merging

    # Evidence to check:
    # - storyStore.ts: { ...s, ...patch, updatedAt: new Date().toISOString() }
    # - Test checks both patch application and updatedAt freshness

    # Red flags:
    # - Patch replaces session instead of merging (Object.assign vs spread)
    # - updatedAt not stamped automatically (caller has to include it)

  Scenario: S2.7 — appendTurn adds turn to interaction_history
    Given sessions contains session "s1" with empty interaction_history
    When I call appendTurn("s1", { id: "t1", turn_number: 1, character_id: "c1", character_name: "Hero", content: "Hello world", is_player: true })
    Then sessions[0].interaction_history has length 1
    And sessions[0].interaction_history[0].content equals "Hello world"
    And sessions[0].interaction_history[0].is_player is true
    And sessions[0].updatedAt is a recent ISO string

    # Confidence scoring guide:
    # 1.0 — appendTurn exists, appends InteractionTurn, stamps updatedAt, test passes
    # 0.5 — appendTurn exists but missing updatedAt stamp, or no dedicated test
    # 0.0 — appendTurn action missing entirely (only updateSession exists for history)

    # Evidence to check:
    # - storyStore.ts: appendTurn implementation with [...s.interaction_history, turn]
    # - StoryState interface includes appendTurn signature
    # - storyStore.test.ts or storeActions.test.ts: test for appendTurn

    # Red flags:
    # - No appendTurn action — expects callers to use updateSession with full history
    # - Direct array mutation (push) instead of spread
    # - Missing updatedAt stamp in appendTurn

  Scenario: S2.8 — appendTurn preserves existing turns
    Given sessions contains session "s1" with 2 existing turns in interaction_history
    When I call appendTurn("s1", a new InteractionTurn)
    Then sessions[0].interaction_history has length 3
    And the first 2 turns are unchanged

    # Confidence scoring guide:
    # 1.0 — Test explicitly checks original turns preserved + new turn appended
    # 0.5 — appendTurn works but no test for preservation of existing turns
    # 0.0 — appendTurn replaces history instead of appending

    # Evidence to check:
    # - storeActions.test.ts: test with pre-populated interaction_history
    # - Verify spread [...existing, new] pattern, not [new] replacement

    # Red flags:
    # - interaction_history: [turn] instead of [...s.interaction_history, turn]
    # - Test only checks length, not content of original turns

  Scenario: S2.9 — storyText is immutable after creation (seed only)
    Given a session created with storyText "Once upon a time"
    When I call appendTurn with multiple user and assistant turns
    Then storyText still equals "Once upon a time"
    And interaction_history contains all the conversation turns

    # Confidence scoring guide:
    # 1.0 — Test proves storyText unchanged after appendTurn, plus JSDoc/comment
    #        clarifies storyText is seed-only
    # 0.5 — storyText doesn't change (correct) but no explicit test or documentation
    # 0.0 — storyText is being modified by appendTurn or updateSession during gameplay

    # Evidence to check:
    # - storeActions.test.ts: test that appends turns then asserts storyText unchanged
    # - StoredSession type comment: storyText is "original seed text"
    # - No code path modifies storyText after initial creation

    # Red flags:
    # - appendTurn implementation touches storyText field
    # - Tests that set storyText in appendTurn test setup (conflating seed with turns)
    # - Missing interaction_history — conversation stored in storyText instead


# ============================================================================
# F1.3 — localStorage Persistence Middleware (weight: 0.20)
# ============================================================================

@feature-F1.3 @weight-0.20
Feature: localStorage persistence

  Scenario: S3.1 — Store state is written to localStorage on change
    Given localStorage is empty
    When I call addSession with a valid session
    Then localStorage.getItem("story-extension-sessions") is not null
    And the parsed value has state.sessions with length 1

    # Confidence scoring guide:
    # 1.0 — persist middleware configured, test verifies localStorage write
    # 0.5 — persist() wrapped but no test for actual localStorage content
    # 0.0 — No persist middleware, store is ephemeral

    # Evidence to check:
    # - storyStore.ts: persist() wrapping create()
    # - storyStorePersistence.test.ts: test reads localStorage after addSession
    # - Key is exactly "story-extension-sessions"

    # Red flags:
    # - Wrong localStorage key name
    # - persist() imported from wrong path (zustand/middleware)
    # - No persistence test file at all

  Scenario: S3.2 — isLoading is not persisted
    When I inspect the localStorage value after any state change
    Then the parsed state object does not contain key "isLoading"

    # Confidence scoring guide:
    # 1.0 — partialize explicitly omits isLoading, test verifies absence
    # 0.5 — partialize exists but test doesn't check for isLoading absence
    # 0.0 — No partialize (entire state persisted including isLoading)

    # Evidence to check:
    # - storyStore.ts: partialize: (state) => ({ sessions, activeSessionId })
    # - storyStorePersistence.test.ts: test that isLoading is NOT in localStorage

    # Red flags:
    # - partialize missing entirely
    # - partialize includes isLoading
    # - No test for this behavior

  Scenario: S3.3 — Store rehydrates on load
    Given localStorage contains a pre-populated sessions JSON
    When the store is initialized (simulating page reload)
    Then store.sessions equals the pre-populated data

    # Confidence scoring guide:
    # 1.0 — Test pre-populates localStorage, creates fresh store, verifies sessions match
    # 0.5 — Rehydration works (persist configured) but no explicit test
    # 0.0 — No persist middleware or rehydration broken

    # Evidence to check:
    # - storyStorePersistence.test.ts: test sets localStorage THEN reads store
    # - Verify the test actually clears and re-initializes the store

    # Red flags:
    # - Test sets store state directly instead of via localStorage (not testing rehydration)
    # - Custom onRehydrateStorage callback that breaks default behavior

  Scenario: S3.4 — Version is set to 1
    When I inspect the localStorage value
    Then the parsed object has version equal to 1

    # Confidence scoring guide:
    # 1.0 — version: 1 in persist config, test verifies
    # 0.5 — version set but no test
    # 0.0 — No version field in persist config

    # Evidence to check:
    # - storyStore.ts: persist config has version: 1
    # - storyStorePersistence.test.ts: parsed.version === 1

    # Red flags:
    # - version: 0 or version missing
    # - No migrate callback foundation (acceptable in Epic 1 but worth noting)


# ============================================================================
# F1.4 — Session List Component (weight: 0.15, browser-required)
# ============================================================================

@feature-F1.4 @weight-0.15 @browser-required
Feature: SessionList component

  Scenario: S4.1 — Renders session title in browser
    Given localStorage contains a session with story_context.title "My Adventure"
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    Then Claude in Chrome finds text "My Adventure" in the sidebar

    # Confidence scoring guide:
    # 1.0 — Title visible in live browser sidebar, screenshot captured
    # 0.5 — Component exists in code but not visible in browser (rendering issue)
    # 0.0 — SessionList component does not exist or sidebar not rendered

    # Evidence to check:
    # - web/src/components/SessionList.tsx exists
    # - Reads from useStoryStore (not props or API)
    # - Screenshot of sidebar showing "My Adventure"
    # - SessionList.test.tsx: unit test with mock store data

    # Red flags:
    # - Reads from props instead of useStoryStore
    # - Component renders in tests but not in actual browser
    # - Sidebar not visible at default viewport width

  Scenario: S4.2 — Renders fallback title
    Given localStorage contains a session with story_context.title undefined
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    Then Claude in Chrome finds text "Untitled Story" in the sidebar

    # Confidence scoring guide:
    # 1.0 — Fallback "Untitled Story" visible in browser + unit test passes
    # 0.5 — Fallback exists in code but renders blank in browser
    # 0.0 — No fallback (renders undefined or empty string)

    # Evidence to check:
    # - SessionList.tsx: story_context.title || "Untitled Story" (or ??)
    # - Screenshot showing "Untitled Story" for session without title

  Scenario: S4.3 — Renders character count
    Given localStorage contains a session with 3 characters
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    Then Claude in Chrome finds text containing "3" and "character" in the sidebar

    # Confidence scoring guide:
    # 1.0 — Character count visible in browser sidebar, tested
    # 0.5 — Shows count but format differs from spec
    # 0.0 — No character count displayed

    # Evidence to check:
    # - SessionList.tsx: session.characters.length usage
    # - Screenshot showing character count in sidebar

  Scenario: S4.4 — Click selects session
    Given localStorage contains sessions "s1" and "s2"
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    And Claude in Chrome clicks the session item for "s1"
    Then the session item for "s1" is visually highlighted (different background)
    And the main content area shows session "s1" details

    # Confidence scoring guide:
    # 1.0 — Clicking a session highlights it AND updates activeSessionId, verified in browser
    # 0.5 — Click handler exists in code but visual feedback missing in browser
    # 0.0 — No click handler or no visual selection state

    # Evidence to check:
    # - SessionList.tsx: onClick calls setActiveSession(session.session_id)
    # - CSS class or style change on active session item
    # - Screenshot before and after click showing visual state change

  Scenario: S4.5 — Delete removes session from sidebar
    Given localStorage contains sessions "s1" and "s2"
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    And Claude in Chrome clicks the delete button on session "s1"
    Then session "s1" is no longer visible in the sidebar
    And session "s2" is still visible

    # Confidence scoring guide:
    # 1.0 — Delete button works in browser: session disappears, other sessions remain
    # 0.5 — Delete works in unit tests but button not clickable in browser
    # 0.0 — No delete button visible

    # Evidence to check:
    # - SessionList.tsx: delete button per session item
    # - Screenshot after deletion showing "s2" only
    # - SessionList.test.tsx: unit test for delete

  Scenario: S4.6 — Empty state message in browser
    Given localStorage has no stored sessions
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    Then Claude in Chrome finds text "No stories yet" in the sidebar

    # Confidence scoring guide:
    # 1.0 — "No stories yet" visible in live browser when no sessions exist
    # 0.5 — Text exists in code but sidebar shows blank in browser
    # 0.0 — No empty state handling (sidebar absent or errors)

    # Evidence to check:
    # - Screenshot of empty sidebar showing "No stories yet"
    # - SessionListEmpty.test.tsx: unit test for empty state

    # Red flags:
    # - No conditional for empty array
    # - Shows "Loading..." instead of empty state

  Scenario: S4.7 — Sidebar layout is two-column grid
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    Then the page has a two-column layout with sidebar on the left (~260px)
    And the main content area fills the remaining width

    # Confidence scoring guide:
    # 1.0 — md:grid-cols-[260px_1fr] applied, sidebar visible at desktop width, screenshot
    # 0.5 — Sidebar renders but layout is stacked (not side-by-side) at desktop width
    # 0.0 — No layout change, SessionList not integrated into App.tsx

    # Evidence to check:
    # - App.tsx: grid layout with md:grid-cols-[260px_1fr] or similar
    # - Screenshot at >=768px viewport showing two-column layout
    # - Claude in Chrome javascript_tool: getComputedStyle check for grid-template-columns

    # Red flags:
    # - SessionList rendered but positioned absolutely or overlapping content
    # - Layout breaks at common desktop widths (1024px, 1280px)


# ============================================================================
# F1.5 — Create Session Flow (Local-Only) (weight: 0.15, browser-required)
# ============================================================================

@feature-F1.5 @weight-0.15 @browser-required
Feature: Local session creation

  Scenario: S5.1 — Save Locally button visible in browser
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    Then Claude in Chrome finds a button with text "Save Locally"
    And the button is visible alongside the existing "Start Session" button

    # Confidence scoring guide:
    # 1.0 — Both "Save Locally" and "Start Session" buttons visible in browser
    # 0.5 — Button exists in DOM but not visible (display:none, overlapped)
    # 0.0 — No "Save Locally" button in the page

    # Evidence to check:
    # - Screenshot showing both buttons
    # - App.tsx: <button>Save Locally</button>
    # - App.test.tsx: unit test for button presence

    # Red flags:
    # - Replaces "Start Session" button instead of adding alongside
    # - Button hidden behind other elements

  Scenario: S5.2 — Button disabled without text in browser
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    And the story text input is empty
    Then the "Save Locally" button has disabled attribute

    # Confidence scoring guide:
    # 1.0 — Button visually disabled (grayed out) in browser when input empty
    # 0.5 — Disabled in DOM but no visual indication
    # 0.0 — Button always enabled

    # Evidence to check:
    # - Claude in Chrome javascript_tool: check button.disabled property
    # - Screenshot showing disabled state

  Scenario: S5.3 — Local session is created without API call
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    And Claude in Chrome fills the story text area with "Once upon a time in a land far away..."
    And Claude in Chrome clicks the "Save Locally" button
    Then a new session appears in the sidebar with title starting with "Once upon a time"
    And no network requests were made to /api endpoints

    # Confidence scoring guide:
    # 1.0 — Session appears in sidebar after click, network tab shows zero /api calls
    # 0.5 — Session created but can't verify no API call in browser
    # 0.0 — Button click triggers API call or nothing happens

    # Evidence to check:
    # - Screenshot after clicking "Save Locally" showing new session in sidebar
    # - Claude in Chrome read_network_requests: no /api calls
    # - App.tsx: handleCreateLocalSession() with isLocal: true
    # - App.test.tsx: unit test with fetch spy

    # Red flags:
    # - Network request to backend during "local" creation
    # - Session not appearing in sidebar (reactivity issue)
    # - Missing isLocal: true in created session

  Scenario: S5.4 — Session appears in SessionList immediately
    # TOOL: Claude in Chrome
    When Claude in Chrome navigates to http://localhost:5173
    And Claude in Chrome fills the story text area with "The dragon breathed fire..."
    And Claude in Chrome clicks "Save Locally"
    Then the sidebar immediately shows the new session (no page reload needed)
    And the new session is highlighted as active

    # Confidence scoring guide:
    # 1.0 — Reactive update verified in browser: session appears + highlighted without refresh
    # 0.5 — Session added but requires manual refresh to appear
    # 0.0 — Session not appearing at all

    # Evidence to check:
    # - Screenshot showing new session in sidebar with active highlight
    # - handleCreateLocalSession calls addSession AND setActiveSession

  Scenario: S5.5 — Story text is stored in session
    Given the story text input contains "Once upon a time..."
    When I click "Save Locally"
    Then sessions[0].storyText equals "Once upon a time..."
    And sessions[0].interaction_history is an empty array

    # Confidence scoring guide:
    # 1.0 — storyText captures input text, interaction_history starts empty, both tested
    # 0.5 — storyText captured but interaction_history not checked
    # 0.0 — storyText not stored or conversation incorrectly placed in storyText

    # Evidence to check:
    # - handleCreateLocalSession: storyText: storyText (from input state)
    # - interaction_history: [] in the new session object
    # - Test asserts both storyText value and empty interaction_history

    # Red flags:
    # - storyText contains something other than the raw input text
    # - interaction_history undefined instead of empty array
    # - No distinction between seed text and conversation

  Scenario: S5.6 — Sessions persist across page refresh
    # TOOL: Claude in Chrome
    Given Claude in Chrome navigates to http://localhost:5173
    And Claude in Chrome creates a local session with text "A persistent tale"
    When Claude in Chrome refreshes the page (navigate to same URL again)
    Then the previously created session is still visible in the sidebar
    And the session title matches the original

    # Confidence scoring guide:
    # 1.0 — Session survives full page refresh in browser, verified with screenshot
    # 0.5 — localStorage has data but session not rendering after refresh (rehydration bug)
    # 0.0 — Session lost on refresh (persist middleware not working)

    # Evidence to check:
    # - Screenshot before refresh: session visible
    # - Screenshot after refresh: same session still visible
    # - Claude in Chrome javascript_tool: localStorage.getItem("story-extension-sessions") is not null

    # Red flags:
    # - Session disappears on refresh (persist not configured)
    # - Session reappears but with wrong data (serialization issue)
    # - isLoading stuck at true after refresh (partialize bug)


# ============================================================================
# F1.6 — Unit Tests (weight: 0.15)
# ============================================================================

@feature-F1.6 @weight-0.15
Feature: Test suite completeness

  Scenario: S6.1 — All store action tests pass
    When I run npm run test inside web/
    Then tests for addSession, removeSession, setActiveSession, updateSession, appendTurn all pass

    # Confidence scoring guide:
    # 1.0 — All 5 actions tested with passing assertions, 8+ test cases in store test files
    # 0.5 — Most actions tested but appendTurn missing or only 4-5 test cases
    # 0.0 — No store test files or most tests failing

    # Evidence to check:
    # - web/src/stores/__tests__/storyStore.test.ts exists with action tests
    # - web/src/stores/__tests__/storeActions.test.ts exists with edge cases
    # - appendTurn has at least 2 tests (basic append + preservation)
    # - Run: cd web && npm run test -- --run 2>&1

    # Red flags:
    # - Tests that pass but use mocks instead of real store (hollow tests)
    # - Missing appendTurn tests entirely
    # - Missing storyText immutability test

  Scenario: S6.2 — Persistence tests pass
    When I run npm run test inside web/
    Then tests for localStorage write, rehydration, and isLoading exclusion all pass

    # Confidence scoring guide:
    # 1.0 — 3+ persistence tests: write, rehydrate, partialize — all passing
    # 0.5 — Some persistence tests but missing rehydration or partialize
    # 0.0 — No persistence test file

    # Evidence to check:
    # - web/src/stores/__tests__/storyStorePersistence.test.ts exists
    # - Tests actually read from localStorage (not just store state)
    # - Rehydration test pre-populates localStorage then checks store

    # Red flags:
    # - Testing persist by checking store state (tests the wrapper, not localStorage)
    # - No test for isLoading exclusion from localStorage

  Scenario: S6.3 — Component tests pass
    When I run npm run test inside web/
    Then tests for SessionList rendering, selection, deletion, and empty state all pass

    # Confidence scoring guide:
    # 1.0 — 5+ component tests covering title, fallback, click, delete, empty — all passing
    # 0.5 — Some component tests but missing empty state or interaction tests
    # 0.0 — No component test files

    # Evidence to check:
    # - web/src/components/__tests__/SessionList.test.tsx exists
    # - web/src/components/__tests__/SessionListEmpty.test.tsx exists
    # - Uses @testing-library/react (render, screen, fireEvent)
    # - Tests set store state via useStoryStore.setState() in beforeEach

    # Red flags:
    # - Tests that render SessionList with props instead of store (wrong pattern)
    # - Missing fireEvent tests (only rendering, no interaction)

  Scenario: S6.4 — No regressions
    When I run npm run test inside web/
    Then all pre-existing tests in App.test.tsx continue to pass
    And total test count is at least 18 new + existing

    # Confidence scoring guide:
    # 1.0 — Full test suite passes (0 failures), 18+ new tests, existing tests untouched
    # 0.5 — New tests pass but some existing tests modified or skipped
    # 0.0 — Existing tests broken by new changes

    # Evidence to check:
    # - Run: cd web && npm run test -- --run 2>&1 | tail -5
    # - Check for "Tests: X passed" with X >= 20 (2 existing + 18 new)
    # - App.test.tsx original tests unmodified

    # Red flags:
    # - Existing test modified to accommodate new code
    # - .skip() or .todo() on any test
    # - Test count below 18 new tests
