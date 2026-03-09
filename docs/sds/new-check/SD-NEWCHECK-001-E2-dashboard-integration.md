---
title: "SD-NEWCHECK-001-E2: Dashboard Integration"
status: active
type: guide
grade: authoritative
last_verified: 2026-03-07
---

# SD-NEWCHECK-001-E2: Dashboard Integration

## Epic
E2 — Add `+ New check` button to dashboard + handle success state

Bead: `agencheck-afm7`

Depends on: `agencheck-0h4w` (E1 must be complete)

## Overview

Two changes to existing files:
1. **`app/checks-dashboard/page.tsx`** — Add `+ New check` button to header top-right + show success toast/banner when `?checkCreated=1` query param present
2. No changes to `layout.tsx`, `ChecksSideNavigation.tsx`, or routing config (Next.js auto-discovers `/checks-dashboard/new/page.tsx`)

## Files to Modify

```
app/checks-dashboard/page.tsx    ← Add button + success state
```

## Change 1: Add `+ New check` Button

The current header in `page.tsx` (lines 64-72):
```tsx
<div className="flex justify-between items-start mb-6 pb-4 border-b border-gray-200">
  <div>
    <h1 className="text-2xl font-bold">Overview</h1>
    <p className="text-muted-foreground mt-1">
      Track your verification performance
    </p>
  </div>
</div>
```

Add the button in the right side of the `flex justify-between` div:
```tsx
<div className="flex justify-between items-start mb-6 pb-4 border-b border-gray-200">
  <div>
    <h1 className="text-2xl font-bold">Overview</h1>
    <p className="text-muted-foreground mt-1">
      Track your verification performance
    </p>
  </div>
  {/* NEW: + New check button */}
  <Link
    href="/checks-dashboard/new"
    className="flex items-center gap-2 px-4 py-2 bg-primary text-white text-sm font-semibold rounded-lg shadow-sm hover:bg-primary/90 transition-colors"
  >
    <span className="text-lg leading-none">+</span>
    New check
  </Link>
</div>
```

## Change 2: Success Banner

The `DashboardContent` component needs to read the `checkCreated` query param and show a success banner. Since it's a client component (`'use client'`):

```tsx
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';

function DashboardContent() {
  const searchParams = useSearchParams();
  const checkCreated = searchParams.get('checkCreated') === '1';

  return (
    <div className="container mx-auto px-4 pb-8">
      {/* Success banner */}
      {checkCreated && (
        <div className="mb-6 flex items-center gap-3 p-4 bg-green-50 border border-green-200 rounded-lg">
          <span className="text-green-600">
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          </span>
          <span className="text-green-700 text-sm font-medium">
            Verification check submitted successfully.
          </span>
        </div>
      )}

      {/* Header with + New check button */}
      <div className="flex justify-between items-start mb-6 pb-4 border-b border-gray-200">
        ...
      </div>
      ...
    </div>
  );
}
```

## Primary Color

Use `bg-primary` (defined as `#3b1e8a` in AgenCheck Tailwind config — matches the header/sidebar active state). Check `tailwind.config.ts` or `globals.css` for the `primary` color definition; if not present as a Tailwind key, use inline style or add the class.

Verify: look for `primary` in `tailwind.config.ts` in the frontend root. If found, use `bg-primary`. If only defined as CSS variable, use the hex inline: `style={{ backgroundColor: '#3b1e8a' }}`.

## Imports to Add

```tsx
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
```

Note: `useSearchParams` requires a `Suspense` boundary — the existing `<Suspense>` wrapper in `WorkHistoryDashboardPage` already covers `DashboardContent`, so no additional boundary needed.

## Acceptance Criteria

- [ ] `+ New check` button appears in top-right of Overview header on `/checks-dashboard`
- [ ] Button is styled with `bg-primary` (dark purple) matching AgenCheck design
- [ ] Clicking button navigates to `/checks-dashboard/new`
- [ ] After successful form submission, `/checks-dashboard?checkCreated=1` shows green success banner
- [ ] Success banner disappears if user navigates away and returns without the query param
