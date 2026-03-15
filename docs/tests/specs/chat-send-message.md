---
title: "Chat Send Message and Receive Response"
status: active
type: reference
service: frontend
port: 5001
prerequisites:
  - "Frontend service running on port 5001"
  - "Backend API running on port 8000"
  - "Eddy validation service running on port 5184"
tags: [smoke, regression, critical]
estimated_duration: "2-5 minutes"
---

# Chat Send Message and Receive Response

## Description

Validates the core chat interaction flow: a user sends a message through the AgenCheck chat interface and receives a meaningful response from the assistant. This is the primary happy-path test for the credential verification chat application.

## Steps

1. **Navigate** to `http://localhost:5001`
   - Expected: Page loads with the AgenCheck chat interface visible, including header, message area, and input field

2. **Capture** screenshot of initial page state
   - Target: `screenshots/01-chat-interface-loaded.png`
   - Expected: Screenshot saved showing empty chat interface

3. **Assert** the chat input field is present and enabled
   - Target: `[data-testid="message-input"]` or message input textarea
   - Expected: Input field is visible, not disabled, and ready for text entry

4. **Fill** the message input with "Can you verify MIT credentials?"
   - Target: `[data-testid="message-input"]` or message input textarea
   - Expected: Text "Can you verify MIT credentials?" appears in the input field

5. **Assert** the Send button is enabled
   - Target: `[data-testid="send-button"]` or send button element
   - Expected: Send button is visible and not disabled (enabled state after text entry)

6. **Click** the Send button
   - Target: `[data-testid="send-button"]` or send button element
   - Expected: Message appears in the chat thread as a user message bubble

7. **Capture** screenshot after message sent
   - Target: `screenshots/07-message-sent.png`
   - Expected: Screenshot saved showing user message in the chat thread

8. **Assert** user message appears in the chat thread
   - Expected: A message bubble with "Can you verify MIT credentials?" is visible in the conversation area

9. **Wait** for assistant response (timeout: 30s)
   - Expected: An assistant response message bubble appears below the user message

10. **Assert** assistant response contains credential verification information
    - Expected: Response mentions "MIT" and includes relevant verification details or acknowledgment of the request

11. **Assert** no error messages are displayed
    - Expected: No error banners, toast notifications, or inline error text visible on the page

12. **Capture** screenshot of completed exchange
    - Target: `screenshots/12-response-received.png`
    - Expected: Screenshot saved showing both user message and assistant response

## Evidence

| Step | Screenshot | Description |
|------|-----------|-------------|
| 2 | `screenshots/01-chat-interface-loaded.png` | Clean initial state of chat interface |
| 7 | `screenshots/07-message-sent.png` | User message visible in chat thread |
| 12 | `screenshots/12-response-received.png` | Complete exchange with assistant response |

## Pass/Fail Criteria

- ALL Assert steps (3, 5, 8, 10, 11) must pass
- Screenshots captured for evidence steps 2, 7, and 12
- No unhandled JavaScript console errors during execution
- Assistant response appears within the 30-second timeout
- Message input clears after successful send
