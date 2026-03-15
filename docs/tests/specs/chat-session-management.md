---
title: "Chat Session Create, Switch, and Manage"
status: active
type: reference
service: frontend
port: 5001
prerequisites:
  - "Frontend service running on port 5001"
  - "Backend API running on port 8000"
  - "No pre-existing test sessions (clean state preferred)"
tags: [regression, critical]
estimated_duration: "3-5 minutes"
---

# Chat Session Create, Switch, and Manage

## Description

Validates session management capabilities in the AgenCheck chat interface. Tests that users can create new chat sessions, switch between sessions, and that conversation context is preserved per session. Session management is critical for users who handle multiple credential verification tasks concurrently.

## Steps

1. **Navigate** to `http://localhost:5001`
   - Expected: Page loads with the AgenCheck chat interface and session sidebar/panel visible

2. **Capture** screenshot of initial state with session list
   - Target: `screenshots/01-initial-session-state.png`
   - Expected: Screenshot saved showing default session state

3. **Assert** at least one default session exists
   - Target: `[data-testid="session-list"]` or session list panel
   - Expected: A default or initial chat session is visible in the session list

4. **Fill** the message input with "Testing session one - verify Harvard credentials"
   - Target: `[data-testid="message-input"]` or message input textarea
   - Expected: Text appears in input field

5. **Click** the Send button
   - Target: `[data-testid="send-button"]` or send button element
   - Expected: Message sent and appears in chat thread

6. **Wait** for assistant response in session one (timeout: 30s)
   - Expected: Assistant response appears in the conversation

7. **Capture** screenshot of session one with conversation
   - Target: `screenshots/07-session-one-conversation.png`
   - Expected: Screenshot saved showing session one with message exchange

8. **Click** the New Session button
   - Target: `[data-testid="new-session-button"]` or new session/new chat button
   - Expected: A new empty chat session is created and becomes the active session

9. **Assert** the chat area is empty in the new session
   - Expected: No messages visible in the conversation area; input field is empty and ready

10. **Capture** screenshot of new empty session
    - Target: `screenshots/10-new-session-empty.png`
    - Expected: Screenshot saved showing clean new session

11. **Fill** the message input with "Testing session two - verify Stanford credentials"
    - Target: `[data-testid="message-input"]` or message input textarea
    - Expected: Text appears in input field

12. **Click** the Send button
    - Target: `[data-testid="send-button"]` or send button element
    - Expected: Message sent and appears in the new session's chat thread

13. **Wait** for assistant response in session two (timeout: 30s)
    - Expected: Assistant response appears in session two's conversation

14. **Assert** session list shows at least two sessions
    - Target: `[data-testid="session-list"]` or session list panel
    - Expected: Both session one and session two are listed in the session panel

15. **Click** the first session in the session list (session one)
    - Target: First session item in `[data-testid="session-list"]` or session list panel
    - Expected: Session one becomes active and its conversation loads

16. **Assert** session one conversation is restored with original messages
    - Expected: The conversation shows "Testing session one - verify Harvard credentials" and its corresponding assistant response

17. **Capture** screenshot of restored session one
    - Target: `screenshots/17-session-one-restored.png`
    - Expected: Screenshot saved showing session one's conversation intact

18. **Click** the second session in the session list (session two)
    - Target: Second session item in `[data-testid="session-list"]` or session list panel
    - Expected: Session two becomes active and its conversation loads

19. **Assert** session two conversation shows its own messages
    - Expected: The conversation shows "Testing session two - verify Stanford credentials" and its corresponding assistant response, not session one's content

20. **Capture** screenshot of restored session two
    - Target: `screenshots/20-session-two-restored.png`
    - Expected: Screenshot saved showing session two's conversation intact

## Evidence

| Step | Screenshot | Description |
|------|-----------|-------------|
| 2 | `screenshots/01-initial-session-state.png` | Default session list state |
| 7 | `screenshots/07-session-one-conversation.png` | Session one with Harvard credential conversation |
| 10 | `screenshots/10-new-session-empty.png` | Newly created empty session |
| 17 | `screenshots/17-session-one-restored.png` | Session one restored after switching back |
| 20 | `screenshots/20-session-two-restored.png` | Session two with Stanford credential conversation |

## Pass/Fail Criteria

- ALL Assert steps (3, 9, 14, 16, 19) must pass
- Screenshots captured for evidence steps 2, 7, 10, 17, and 20
- Session switching preserves conversation history per session (no cross-contamination)
- No unhandled JavaScript console errors during execution
- Both assistant responses arrive within their 30-second timeouts
- New session creation results in a clean, empty conversation area
