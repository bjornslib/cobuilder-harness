# Accessibility and Responsive Timeline Implementation Research

## Overview
Research findings on implementing accessible and responsive timeline components for the case detail page, specifically focusing on the ActivityTimeline component mentioned in SD-DASHBOARD-AUDIT-FRONTEND-001.

## 1. Vertical Timeline Structure

Based on the solution design requirements, the ActivityTimeline component should follow this structure:

```tsx
interface ActivityTimelineProps {
  entries: TimelineEntry[];
  currentStep: number;
}

interface TimelineEventProps {
  entry: TimelineEntry;
  isCurrent: boolean;
  isCompleted: boolean;
  isPending: boolean;
}
```

The timeline should be implemented as a vertical list with connecting lines and circular dots representing each event.

## 2. Accessibility Implementation

### ARIA Roles and Attributes
- Use `role="feed"` on the timeline container for live updates
- Use `aria-live="polite"` for non-critical timeline updates
- Use `aria-live="assertive"` for critical status changes
- Each timeline item should have `role="article"`
- Add `aria-label` or `aria-labelledby` to describe the timeline's purpose

### Keyboard Navigation
- Implement arrow key navigation to move between timeline events
- Support focus management when new events are added
- Ensure all interactive elements (dots, expandable sections) are keyboard accessible
- Add skip links for users of screen readers

### Screen Reader Considerations
- Provide clear labels for each timeline event
- Announce status changes (completed, in-progress, pending)
- Include timestamps and relevant metadata in the accessible name

## 3. Responsive Design Patterns

### Breakpoint Strategy
Based on the solution design's requirements:

| Breakpoint | Layout |
|------------|--------|
| `lg` (1024px+) | 12-col grid: 7-col left + 5-col right |
| `md` (768px) | Single column: candidate → verification → timeline stacked |
| `sm` (640px) | Full-width cards, timeline dots shift to smaller size |

### CSS Implementation
```css
.timeline-container {
  @apply relative pl-4 border-l-2 border-slate-100 space-y-8;
}

.timeline-item {
  @apply relative;
}

.timeline-dot {
  position: absolute;
  left: -21px;
  @apply w-4 h-4 rounded-full border-2;
}

/* Completed (latest) */
.timeline-dot.completed-latest {
  @apply bg-teal-500 border-white shadow-sm;
}

/* Completed (older) */
.timeline-dot.completed {
  @apply bg-white border-slate-300;
}

/* In Progress */
.timeline-dot.in-progress {
  @apply bg-teal-500 border-white animate-pulse;
}

/* Pending (future) */
.timeline-dot.pending {
  @apply bg-white border-dashed border-slate-300 opacity-50;
}
```

## 4. Implementation Patterns

### Base Component Structure
```tsx
const ActivityTimeline = ({ entries, currentStep }: ActivityTimelineProps) => {
  return (
    <div
      className="timeline-container"
      role="feed"
      aria-label="Case activity timeline"
    >
      {entries.map((entry, index) => (
        <TimelineEvent
          key={entry.step_order}
          entry={entry}
          position={index}
          isCurrent={index === currentStep}
          isCompleted={index < currentStep}
          isPending={index > currentStep}
        />
      ))}
    </div>
  );
};
```

### Individual Event Component
```tsx
const TimelineEvent = ({
  entry,
  isCurrent,
  isCompleted,
  isPending
}: TimelineEventProps) => {
  return (
    <div
      className="timeline-item"
      role="article"
      aria-label={`${entry.step_label}${isCurrent ? ' (current)' : ''}`}
    >
      <div className={`timeline-dot
        ${isCurrent ? 'completed-latest' : ''}
        ${isCompleted ? 'completed' : ''}
        ${isPending ? 'pending' : ''}
      `} />

      <div className="event-content">
        <h3>{entry.step_label}</h3>
        <p>{entry.result_label}</p>
        <time dateTime={entry.completed_at}>{entry.completed_at}</time>

        {entry.recording_url && (
          <CallRecordingPlayer
            recordingUrl={entry.recording_url}
            transcriptUrl={entry.transcript_url}
            duration={entry.duration}
          />
        )}
      </div>
    </div>
  );
};
```

## 5. Interaction States

### Dot States (Timeline Markers)
| State | Dot Style | Connector Style |
|-------|-----------|-----------------|
| **Completed (latest)** | `bg-teal-500 border-2 border-white shadow-sm` (filled, 14px) | Solid `border-l-2 border-slate-100` |
| **Completed (older)** | `bg-white border-2 border-slate-300` (outline, 14px) | Solid line |
| **In Progress** | `bg-teal-500 border-2 border-white animate-pulse` (filled + pulse) | Solid line |
| **Pending (future)** | `bg-white border-2 border-dashed border-slate-300 opacity-50` (dashed, 14px) | Dashed line segment |

### Timeline Event Interactions
- **Hover on event**: Entire event row gets `bg-slate-50/50` background
- **Hover on dot**: Tooltip appears with step details
- **New event arrival**: New entry slides down with animation
- **Focus management**: Auto-scroll to bring current step into view

## 6. Auto-Scroll Behavior
```tsx
useEffect(() => {
  const currentStep = timelineRef.current?.querySelector('[data-current="true"]');
  currentStep?.scrollIntoView({
    behavior: 'smooth',
    block: 'center',
    inline: 'nearest'
  });
}, [timeline]);
```

## 7. Keyboard Accessibility
- `Tab` key: Navigate between timeline elements
- `ArrowUp/ArrowDown`: Move between timeline events (if interactive)
- `Space/Enter`: Activate focused timeline event details
- `Escape`: Close expanded timeline event details

## 8. Focus Management
- Maintain focus when timeline updates occur
- Implement skip links for keyboard users
- Ensure focus order matches visual order
- Announce new events to screen readers

## 9. Performance Considerations
- Virtualize long timelines to improve rendering performance
- Debounce scroll handlers
- Optimize animations with CSS transforms
- Use React.memo for timeline event components

## 10. Testing Guidelines
- Test with screen readers (NVDA, JAWS, VoiceOver)
- Verify keyboard navigation works without mouse
- Confirm responsive layouts at all breakpoints
- Validate ARIA attributes with accessibility auditing tools

## Conclusion
The ActivityTimeline component should be built with accessibility as a first-class concern, implementing proper ARIA roles, keyboard navigation, and responsive design patterns. The component should maintain the visual design requirements from the solution design while ensuring it works for all users regardless of their abilities or device constraints.