@feature-G12 @weight-1.00 @code-analysis
Feature: G12 - Form Events Data Channel Topic Alignment

  Background:
    Given the implementation repository is at /Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck
    And the target file is app/verify-check/[task_id]/_components/FormEventEmitter.tsx

  # =====================================================================
  # Scenario 1: Frontend topic string changed from 'lk.form-events' to 'form_events'
  # =====================================================================

  @AC-G12.1 @critical
  Scenario: useDataChannel hook uses correct custom topic string
    When the validator reads FormEventEmitter.tsx
    Then the useDataChannel hook is called with topic 'form_events'
    And the string 'lk.form-events' does NOT appear anywhere in FormEventEmitter.tsx
    And the string 'lk.form-events' does NOT appear in any send() call options

    # Confidence scoring guide:
    # 1.0 — Both useDataChannel('form_events', ...) AND send(encoded, { topic: 'form_events' })
    #        are present. Zero occurrences of 'lk.form-events' in the file.
    # 0.5 — One of the two locations changed but not the other (partial fix).
    #        Or 'form_events' appears but 'lk.form-events' also still appears somewhere.
    # 0.0 — useDataChannel still uses 'lk.form-events', or topic strings are missing/undefined.

    # Evidence to check:
    # - FormEventEmitter.tsx: useDataChannel() first argument (line ~35 in original)
    # - FormEventEmitter.tsx: send() call options.topic (line ~41 in original)
    # - grep -r 'lk.form-events' across entire verify-check directory (should return 0 results)

    # Red flags:
    # - 'lk.form-events' still present anywhere in the file
    # - Topic string is a variable that resolves to 'lk.form-events' at runtime
    # - useDataChannel called without any topic argument
    # - send() called without { topic: ... } option

  # =====================================================================
  # Scenario 2: Backend handler topic string matches frontend
  # =====================================================================

  @AC-G12.2 @critical
  Scenario: Backend agent.py handler matches the corrected topic string
    Given the backend file is agencheck-support-agent/agent.py
    When the validator reads the data packet topic check in agent.py
    Then the handler checks for topic "form_events" (not "lk.form-events")
    And handle_form_event or handle_voice_form_event functions exist

    # Confidence scoring guide:
    # 1.0 — agent.py checks `topic == "form_events"` AND both handler functions exist
    #        and contain meaningful logic (not just pass/TODO).
    # 0.5 — Topic string is correct but handlers are stubs or have TODO comments.
    #        Or handlers exist but topic check is missing.
    # 0.0 — agent.py still checks for "lk.form-events" or topic check is absent entirely.

    # Evidence to check:
    # - agent.py: search for getattr(data_packet, "topic", None) == "form_events"
    # - agent.py: handle_form_event() function body
    # - agent.py: handle_voice_form_event() function body
    # - grep -r 'form_events' in agencheck-support-agent/ (should find matches)

    # Red flags:
    # - Multiple different topic strings for form events (inconsistency)
    # - Handler functions that are empty or only contain logging
    # - TODO/FIXME comments in the handler path

  # =====================================================================
  # Scenario 3: No regressions — only FormEventEmitter.tsx changed
  # =====================================================================

  @AC-G12.3 @high
  Scenario: Fix is minimal and does not introduce unrelated changes
    When the validator checks git diff for the G12 fix
    Then only FormEventEmitter.tsx has topic-related changes
    And no other files in the verify-check directory have form event topic changes
    And the agent.py backend handler was already correct (topic: "form_events")

    # Confidence scoring guide:
    # 1.0 — Git diff shows exactly 2 string replacements in FormEventEmitter.tsx
    #        (useDataChannel argument + send option). No other files changed for this fix.
    #        agent.py already had "form_events" (no backend changes needed).
    # 0.5 — Fix is correct but additional files were modified (possible unrelated changes
    #        bundled in). Or more than 2 lines changed in FormEventEmitter.tsx.
    # 0.0 — Fix introduces breaking changes elsewhere. Or backend topic was also changed
    #        incorrectly (both sides now use wrong string). Or new files added for this fix.

    # Evidence to check:
    # - git diff --stat for the commit implementing G12
    # - git diff FormEventEmitter.tsx (should show ~2 line changes)
    # - agent.py: verify "form_events" was already present before the fix

    # Red flags:
    # - Large diff for a 2-line fix (scope creep)
    # - Changes to agent.py topic string (it was already correct)
    # - New imports or dependencies added
    # - Changes to useDataChannel hook signature or parameters beyond topic
