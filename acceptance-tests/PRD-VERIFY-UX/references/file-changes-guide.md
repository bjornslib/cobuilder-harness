---
title: "File Changes Implementation Guide"
status: active
type: reference
last_verified: 2026-03-05
---

# File Changes Guide — Verify-Check UX Improvements

## Overview

This document maps each UX change to specific files that need modification in the zenagent2 repo.

**Base Path**: `/Users/theb/Documents/Windsurf/zenagent2/zenagent/agencheck/agencheck-support-frontend/app/verify-check/[task_id]/`

---

## Change 1: Full-Width Progress Bar at Top

**Files to Modify**: `_components/LiveFormCard.tsx`

### Current Code (Lines ~123–133)
Locate the progress bar that appears in CardHeader with counter text on the right.

### Change Required
1. **Remove** the current right-aligned counter block and green bar
2. **Add** a full-width gradient bar at the **very top** of CardHeader, **before** the title row
3. The bar should:
   - Have classes: `w-full h-1.5 bg-gradient-to-r from-blue-500 via-blue-600 to-purple-600`
   - Use inner fill: `h-full bg-gradient-to-r from-blue-600 to-purple-600` with dynamic width
   - Animate width: `transition-all duration-700 ease-out`
   - Calculate width: `(resolvedCount / totalCount) * 100`
   - Only render when `wasEmployed === true && totalCount > 0`

### Code Snippet
```tsx
{/* Full-width progress bar at card top — gradient from blue to purple */}
{store.wasEmployed === true && totalCount > 0 && (
  <div className="w-full h-1.5 bg-gradient-to-r from-blue-500 via-blue-600 to-purple-600 rounded-full overflow-hidden mb-6">
    <div
      className="h-full rounded-full transition-all duration-700 ease-out bg-gradient-to-r from-blue-600 to-purple-600"
      style={{ width: `${(resolvedCount / totalCount) * 100}%` }}
    />
  </div>
)}
```

**Position**: This should be the **first render item** inside CardHeader (before title text)

---

## Change 2: Field Expansion/Shrinking

**Files to Modify**: `_components/VerifyFieldRow.tsx`

### Current Code
All field rows render with consistent sizing, with color to indicate status.

### Change Required
1. **Add state-based class mapping** based on field status:
   - `pending` (not started): transparent, normal padding
   - `editing` (user is editing): yellow/amber background + blue left border, expanded
   - `confirmed` (resolved): muted gray text, small padding, reduced opacity
   - `updated` (user made change): slightly muted

2. **Apply conditional classes** to the root wrapper:
   ```tsx
   const rowClasses = {
     pending: 'py-4 bg-transparent border-l-4 border-blue-500 pl-4', // Blue border, full padding
     confirmed: 'py-1 text-gray-400 opacity-75',  // Muted, shrunk
     editing: 'py-4 bg-amber-50 border-l-4 border-blue-500 pl-4',  // Yellow bg + blue border
     updated: 'py-2 opacity-70'
   }
   ```

3. **Add transition animation**:
   ```tsx
   <div className={`transition-all duration-300 ${rowClasses[status]}`}>
     {/* field content */}
   </div>
   ```

### Visual Reference
- **Active field**: Yellow/amber background (`bg-amber-50`), blue left border (`border-l-4 border-blue-500`), full padding (`py-4`)
- **Confirmed field**: Muted gray text (`text-gray-400`), reduced padding (`py-1-2`), 75% opacity
- **Smooth transitions**: `transition-all duration-300` between states

---

## Change 3: Chat Agent Response Logic

**Files to Modify**:
- `_components/MessageBubble.tsx` (for typewriter animation)
- `page.tsx` (for agent response logic)
- Agent backend prompt/system message

### Current Code
Agent responds in chat on every field confirmation or state change.

### Change Required

#### Backend Agent Logic
Modify the agent system prompt or response handler to:
1. **On initial load**: Send welcome message
2. **On employment Yes/No**: Send NO message (field value selection is not a change)
3. **On Confirm click**: Send NO message (confirming a value is expected behavior)
4. **On Change click**: Send YES message (change indicates discrepancy, needs explanation)

**Trigger Condition for Agent Response**:
```python
# Only respond if the change event is from Change button, not Confirm
if event_type == "change" and field_name and old_value != new_value:
    respond_with_context(f"I see you changed {field_name} from {old_value} to {new_value}")
```

#### Frontend Changes
In `page.tsx`, pass an event flag to the agent indicating whether this is a "Confirm" or "Change" event:
```tsx
// When user clicks Confirm
handleConfirm({ event_type: "confirm", field_id: ... })

// When user clicks Change
handleChange({ event_type: "change", field_id: ... })
```

The backend agent should **ignore** `event_type: "confirm"` events and only respond to `event_type: "change"`.

---

## Change 4: Signature Field Conditional Visibility

**Files to Modify**: `page.tsx` (around lines ~700–730)

### Current Code
The signature input section and Submit button render unconditionally at the bottom.

### Change Required
Wrap the entire signature/submit section with a conditional check:

```tsx
{resolvedCount >= totalCount && totalCount > 0 && (
  <div className="...bottom-bar classes...">
    <VerifierNameInput
      value={verifierName}
      onChange={setVerifierName}
      disabled={isLoading}
    />
    <Button
      onClick={handleSubmit}
      disabled={!verifierName.trim() || isLoading}
      variant="primary"
    >
      Submit Verification
    </Button>
  </div>
)}
```

**Variables Available**:
- `resolvedCount` (from store)
- `totalCount` (from store)
- These should already be accessible via `useVerificationFormStore()`

---

## Change 5: Label Language Update

**Files to Modify**: `_components/VerifierNameInput.tsx`

### Current Code
```tsx
<label>Verifier name</label>
<input placeholder="EG" />
```

### Change Required
Replace with plain language:
```tsx
<label>Your name</label>
<input placeholder="Type your full name to confirm" />
```

**Note**: Ensure no other references to "verifier" appear in the UI (search for "verifier" in lowercase in the component files).

---

## Change 6: Chat Panel Minimization During Voice

**Files to Modify**:
- `_components/TranscriptPanel.tsx` (main chat panel component)
- `page.tsx` (for passing voice mode state to TranscriptPanel)

### Current Code
TranscriptPanel always shows the full message list and text input, regardless of mode.

### Change Required

#### In `page.tsx`
Pass the `isVoiceMode` state to TranscriptPanel:
```tsx
<TranscriptPanel
  messages={messages}
  onSendMessage={handleSendMessage}
  isVoiceMode={isVoiceMode}  // Add this prop
/>
```

#### In `TranscriptPanel.tsx`
Add conditional rendering based on `isVoiceMode`:

```tsx
interface TranscriptPanelProps {
  messages: Message[]
  onSendMessage: (text: string) => void
  isVoiceMode?: boolean
}

export function TranscriptPanel({ messages, onSendMessage, isVoiceMode }: TranscriptPanelProps) {
  return (
    <div className="transition-all duration-300">
      {isVoiceMode ? (
        // Minimized voice mode view
        <div className="flex flex-col items-center justify-center gap-4 p-6">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-sm font-semibold">LIVE</span>
          </div>
          {/* Waveform animation */}
          <VoiceWaveform />
          {/* End Call button */}
          <Button variant="destructive" onClick={onEndCall}>
            End Call
          </Button>
          <p className="text-xs text-gray-400">AWAITING INPUT</p>
        </div>
      ) : (
        // Full chat view (existing code)
        <div className="flex flex-col gap-4">
          <div className="overflow-y-auto flex-1">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} {...msg} />
            ))}
          </div>
          <input
            type="text"
            placeholder="Type a message..."
            onKeyPress={(e) => e.key === 'Enter' && onSendMessage(e.currentTarget.value)}
          />
        </div>
      )}
    </div>
  );
}
```

**Key Elements in Minimized View**:
- Green "●" dot + "LIVE" text (top-left, small)
- Animated waveform showing audio activity (center)
- Red "End Call" button (top-right)
- "AWAITING INPUT" label (below waveform, muted gray)

---

## Change 7: Typewriter Animation for Welcome Message

**Files to Modify**: `_components/MessageBubble.tsx`, `_components/TranscriptPanel.tsx`

### Current Code
Messages appear instantly in full.

### Change Required

#### In `MessageBubble.tsx`
Add an `isAnimated` prop for the welcome message:

```tsx
interface MessageBubbleProps {
  content: string
  role: 'user' | 'assistant'
  isAnimated?: boolean
}

export function MessageBubble({ content, role, isAnimated }: MessageBubbleProps) {
  const [displayedText, setDisplayedText] = useState('')

  useEffect(() => {
    if (!isAnimated) {
      setDisplayedText(content)
      return
    }

    let i = 0
    const interval = setInterval(() => {
      setDisplayedText(content.slice(0, ++i))
      if (i >= content.length) clearInterval(interval)
    }, 25) // Adjust speed (25ms per character = ~40 chars/sec)

    return () => clearInterval(interval)
  }, [content, isAnimated])

  return (
    <div className={`message-bubble role-${role}`}>
      {displayedText}
    </div>
  )
}
```

#### In `TranscriptPanel.tsx`
Mark the first message as animated:

```tsx
const isFirstMessage = messages.length === 1 && messages[0].role === 'assistant'

<MessageBubble
  key={msg.id}
  content={msg.content}
  role={msg.role}
  isAnimated={isFirstMessage}  // Only first assistant message
/>
```

---

## Change 8: Candidate Info De-emphasis

**Files to Modify**: `_components/LiveFormCard.tsx` or `_components/CandidateInfoBlock.tsx`

### Current Code
Candidate name and company displayed in a prominent block or inline with the form title.

### Change Required
Reduce visual weight:

```tsx
{/* Before: <CandidateInfoBlock /> */}

{/* After: Muted, single-line display */}
<div className="text-xs text-gray-400 mb-4">
  Verifying employment for {candidateName} at {companyName}
</div>
```

Or if keeping CandidateInfoBlock component, update its internal styling:

```tsx
function CandidateInfoBlock({ name, company }) {
  return (
    <div className="text-xs text-gray-400 opacity-75 mb-6">
      <p>{name} • {company}</p>
    </div>
  )
}
```

**Key Changes**:
- Text size: `text-xs` (smaller)
- Color: `text-gray-400` (muted)
- Opacity: 75% (slightly transparent)
- No bold borders or large container
- Position: Below title or above form fields (not inline with header)

---

## Testing Checklist

After implementing all changes, verify:

- [ ] Progress bar at top, full width, blue-purple gradient
- [ ] Active field has blue border + yellow bg + full padding
- [ ] Confirmed fields are muted, shrunken, low opacity
- [ ] Smooth transitions between field states (300ms)
- [ ] Agent welcome message types out on load
- [ ] Agent does NOT respond to Confirm clicks
- [ ] Agent ONLY responds to Change clicks
- [ ] Signature input/button hidden until all fields complete
- [ ] Signature label reads "Your name" (not "Verifier")
- [ ] Chat panel minimizes to LIVE badge during voice mode
- [ ] Chat panel expands back when voice call ends
- [ ] Candidate info appears small and muted
- [ ] No regressions: Progressive disclosure, voice/chat toggle still work

---

## Component Dependency Summary

| Change | Component Files | Depends On | Affected By |
|--------|-----------------|-----------|-------------|
| Progress Bar | LiveFormCard.tsx | store (resolved/total count) | field state changes |
| Field Expansion | VerifyFieldRow.tsx | field status | user actions |
| Chat Response | page.tsx + Agent backend | event_type flag | agent logic |
| Signature Conditional | page.tsx | store (resolved/total count) | field completion |
| Label Language | VerifierNameInput.tsx | — | — |
| Chat Minimize | TranscriptPanel.tsx + page.tsx | isVoiceMode prop | voice state |
| Typewriter | MessageBubble.tsx | isAnimated prop | first message |
| Candidate De-emphasis | LiveFormCard.tsx or CandidateInfoBlock.tsx | — | — |
