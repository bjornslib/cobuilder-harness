---
title: "Testing_Details"
status: active
type: skill
last_verified: 2026-02-19
grade: authoritative
---

# Testing Details for Workers

**Purpose**: Detailed testing procedures for worker feature validation
**Parent Skill**: worker-focused-execution

---

## Table of Contents

1. [Browser Testing with browsermcp](#browser-testing-with-browsermcp)
2. [API Testing](#api-testing)
3. [Unit Testing](#unit-testing)
4. [Service Startup](#service-startup)
5. [Common Patterns](#common-patterns)
6. [Troubleshooting](#troubleshooting)

---

## Browser Testing with browsermcp

### When to Use

Use browser testing when `validation: "browser"` in your feature assignment.

**Good For**:
- UI component behavior
- User workflows
- Visual validation
- End-to-end flows

### Basic Flow

```javascript
// 1. Navigate to the application
await browser_navigate("http://localhost:5001");

// 2. Wait for page load
await browser_wait({ time: 2 });

// 3. Capture accessibility snapshot
const snapshot = await browser_snapshot();
// This returns element references you'll use for interaction

// 4. Interact with elements
await browser_type({
  element: "message input field",
  ref: "[ref-from-snapshot]",  // Use exact ref from snapshot
  text: "Your test message",
  submit: false  // true to press Enter after
});

// 5. Click buttons
await browser_click({
  element: "send button",
  ref: "[ref-from-snapshot]"
});

// 6. Wait for response
await browser_wait({ time: 5 });

// 7. Verify result
const result = await browser_snapshot();
// Check result for expected content
```

### Finding Element References

After `browser_snapshot()`, you'll see output like:

```
[ref=input-1] textbox "Type your message..."
[ref=button-2] button "Send"
[ref=div-3] article "Assistant: Hello!"
```

Use the `ref` values exactly as shown.

### Chat Interface Test Example

```javascript
// Complete chat test flow
async function testChatFeature() {
  // Navigate
  await browser_navigate("http://localhost:5001");
  await browser_wait({ time: 2 });

  // Get initial state
  let snap = await browser_snapshot();

  // Type message (find input ref from snapshot)
  await browser_type({
    element: "chat input",
    ref: "input-main",  // actual ref from snapshot
    text: "Can you verify MIT credentials?",
    submit: false
  });

  // Click send
  await browser_click({
    element: "send button",
    ref: "button-send"  // actual ref from snapshot
  });

  // Wait for AI response
  await browser_wait({ time: 10 });

  // Verify response appeared
  snap = await browser_snapshot();
  // Check snap contains assistant message
}
```

### Visual Validation Points

Check for these common issues:

- Text is visible (not white on white)
- Loading states appear/disappear correctly
- Error messages are readable
- Layout isn't broken
- Interactive elements are clickable

### Taking Screenshots

```javascript
// Capture screenshot for visual inspection
await browser_screenshot();
```

Use sparingly - snapshots are usually more useful for validation.

---

## API Testing

### When to Use

Use API testing when `validation: "api"` in your feature assignment.

**Good For**:
- Backend endpoint behavior
- Response structure validation
- Error handling
- Data transformations

### Health Check First

```bash
# Always verify service is running
curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

### Main Endpoint Test

```bash
# POST to /my-project
curl -X POST http://localhost:8000/my-project \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Can MIT credentials be verified?",
    "thread_id": "test-session-001",
    "include_citations": true
  }'
```

### Expected Response Structure

```json
{
  "response": "MIT offers credential verification through...",
  "citations": [
    {"source": "...", "text": "..."}
  ],
  "confidence": 0.85,
  "tool_used": "verify_education"
}
```

### Testing MCP Services Directly

```bash
# eddy_validate (port 5184)
curl -X POST http://localhost:5184/verify \
  -H "Content-Type: application/json" \
  -d '{"institution": "MIT", "credential_type": "degree"}'

# user_chat (port 5185)
curl -X POST http://localhost:5185/search \
  -H "Content-Type: application/json" \
  -d '{"query": "How do I verify credentials?", "top_k": 5}'
```

### Validating Response

Check:
1. HTTP status code is 200
2. Response is valid JSON
3. Required fields present
4. Values are reasonable
5. No error messages in response

---

## Unit Testing

### When to Use

Use unit testing when `validation: "unit"` in your feature assignment.

**Good For**:
- Pure function logic
- Isolated component behavior
- Edge case coverage
- Fast feedback loops

### Frontend (Jest)

```bash
# Run all tests
npm run test

# Run specific test file
npm run test -- --testPathPattern="ChatInterface"

# Run with coverage
npm run test -- --coverage

# Watch mode (during development)
npm run test -- --watch
```

### Backend (pytest)

```bash
# Run all tests
pytest

# Run specific file
pytest tests/test_orchestrator.py -v

# Run specific test
pytest tests/test_orchestrator.py::test_specific_function -v

# With coverage
pytest --cov=my_project_backend tests/
```

### Writing Tests (TDD)

**Frontend Component Test**:
```typescript
import { render, screen, fireEvent } from '@testing-library/react';
import { ChatInput } from './ChatInput';

describe('ChatInput', () => {
  it('should call onSend with message when submitted', () => {
    const mockOnSend = jest.fn();
    render(<ChatInput onSend={mockOnSend} />);

    const input = screen.getByPlaceholderText(/type.*message/i);
    const button = screen.getByRole('button', { name: /send/i });

    fireEvent.change(input, { target: { value: 'Hello' } });
    fireEvent.click(button);

    expect(mockOnSend).toHaveBeenCalledWith('Hello');
  });
});
```

**Backend Function Test**:
```python
import pytest
from my_project_backend.orchestrator import process_query

@pytest.mark.asyncio
async def test_process_query_returns_response():
    result = await process_query(
        query="Test query",
        thread_id="test-001"
    )

    assert result is not None
    assert "response" in result
    assert result["confidence"] >= 0
```

---

## Service Startup

### Full Stack Startup

```bash
# Terminal 1: Backend services
cd my-project-backend
./start_services.sh

# Terminal 2: Frontend
cd my-project-frontend
npm run dev
```

### Service Ports

| Service | Port | Check |
|---------|------|-------|
| Frontend | 5001 | http://localhost:5001 |
| Backend | 8000 | http://localhost:8000/health |
| eddy_validate | 5184 | http://localhost:5184/health |
| user_chat | 5185 | http://localhost:5185/health |
| university-contact | 5186 | http://localhost:5186/health |
| deep_research | 8001 | http://localhost:8001/health |

### Quick Health Check All

```bash
for port in 8000 5184 5185 5186 8001; do
  echo "Port $port: $(curl -s -o /dev/null -w '%{http_code}' http://localhost:$port/health)"
done
```

---

## Common Patterns

### Wait for Async Operations

```javascript
// Browser: Wait for element to appear
await browser_wait({ time: 5 });
const snap = await browser_snapshot();
// Check snap for expected element

// Alternative: Poll until condition
let attempts = 0;
while (attempts < 10) {
  const snap = await browser_snapshot();
  if (snap.includes("expected text")) break;
  await browser_wait({ time: 1 });
  attempts++;
}
```

### Test Error Cases

```bash
# API: Test invalid input
curl -X POST http://localhost:8000/my-project \
  -H "Content-Type: application/json" \
  -d '{"query": ""}'
# Should return error response, not crash
```

### Test Edge Cases

- Empty inputs
- Very long inputs
- Special characters
- Missing required fields
- Invalid data types

---

## Troubleshooting

### Browser Tests Failing

**Element not found**:
- Run `browser_snapshot()` to see available elements
- Check element refs are correct
- Wait longer for dynamic content

**Page not loading**:
- Verify frontend is running on port 5001
- Check browser console for errors
- Try `browser_navigate` again

### API Tests Failing

**Connection refused**:
- Run `./start_services.sh` first
- Check port isn't in use: `lsof -i :8000`
- Check service logs for errors

**Unexpected response**:
- Verify request format matches API spec
- Check Content-Type header
- Review backend logs

### Unit Tests Failing

**Import errors**:
- Run from correct directory
- Check dependencies installed
- Verify module paths

**Async issues**:
- Use `@pytest.mark.asyncio` for async tests
- Use `await` correctly
- Check for race conditions

---

**Reference**: See orchestrator's [VALIDATION.md](../orchestrator-multiagent/VALIDATION.md) for complete service and testing documentation.
