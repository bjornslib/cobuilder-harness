---
title: "Executable Browser Tests: Progress Bar"
status: active
type: reference
last_verified: 2026-03-05
---

# Progress Bar Validation Tests

These tests use browser automation to verify the progress bar implementation matches the design specification.

## Test Setup

**URL**: `http://localhost:3000/verify-check/[valid-task-id]`
**Prerequisites**:
- Frontend dev server running on port 3000
- Database has at least one valid task
- Form shows employment as "Was Employed" with 8 fields

## Test 1: Progress Bar Visibility and Position

**Objective**: Verify progress bar exists at the absolute top of the card, above the title

**Steps**:
1. Navigate to `/verify-check/[task-id]`
2. Wait for page to fully load
3. Find element with class containing `bg-gradient-to-r from-blue-500 to-purple-600`
4. Verify element is a direct child of `CardHeader` or first child of card
5. Verify element is positioned BEFORE (above) the "Work History Verification" heading

**Expected Results**:
- Progress bar element exists
- Progress bar is in the DOM before any title text
- Progress bar is visually at the top (y-position is minimal)
- No other elements are positioned above the progress bar

**Code Example** (using claude-in-chrome):
```javascript
// Find the progress bar element
const progressBar = document.querySelector('[class*="bg-gradient-to-r"][class*="from-blue-500"]')
if (!progressBar) throw new Error("Progress bar not found")

// Verify it's a thin horizontal bar at top
const rect = progressBar.getBoundingClientRect()
const cardRect = document.querySelector('[class*="CardHeader"]').getBoundingClientRect()

console.log(`Progress bar height: ${rect.height}px`)
console.log(`Progress bar width: ${rect.width}px`)
console.log(`Card width: ${cardRect.width}px`)

if (rect.height < 3 || rect.height > 8) throw new Error("Progress bar height not in expected range (3-8px)")
if (Math.abs(rect.width - cardRect.width) > 5) throw new Error("Progress bar doesn't span full width")
if (rect.top < cardRect.top) throw new Error("Progress bar not at top of card")
```

## Test 2: Full-Width Gradient

**Objective**: Verify progress bar spans full width with correct gradient colors

**Steps**:
1. Find progress bar element
2. Extract computed styles for width and background
3. Verify width is ~100% of parent
4. Verify gradient contains blue and purple colors

**Expected Results**:
- Progress bar width is ≥99% of parent card width
- Gradient colors include blue (#3b82f6 or similar) and purple (#9333ea or similar)
- No padding/margin reducing effective width

## Test 3: Progress Animation from 0% to 100%

**Objective**: Verify progress bar grows as fields are confirmed

**Steps**:
1. On page load, measure progress bar fill width (should be 0% or very small)
2. Click "Yes" on employment question, then click "Confirm"
3. Measure progress bar width (should be ~12.5% for 1/8 fields)
4. Repeat for additional fields (2/8 = 25%, 4/8 = 50%, etc.)
5. Confirm all 8 fields
6. Verify progress bar reaches 100%

**Expected Results**:
- Initial width is 0% or <5% (essentially empty)
- Width increases proportionally (widthPercent ≈ confirmedCount / totalCount * 100)
- Transitions are smooth (takes 300-700ms per field)
- Final width reaches 95-100% after all confirmations

**Pseudocode**:
```javascript
function measureProgress() {
  const progressFill = document.querySelector('[class*="bg-gradient-to-r"]')
  const style = window.getComputedStyle(progressFill)
  return {
    width: progressFill.offsetWidth,
    parentWidth: progressFill.parentElement.offsetWidth,
    percent: (progressFill.offsetWidth / progressFill.parentElement.offsetWidth) * 100
  }
}

// Measure at each step
const progress0 = measureProgress()  // Should be ~0%
// Click confirm on field 1
const progress1 = measureProgress()  // Should be ~12.5%
// etc.
```

## Test 4: No Text Counter Inline

**Objective**: Verify progress bar is the only progress indicator (no "N/M" text)

**Steps**:
1. Find all text nodes within the CardHeader
2. Search for patterns like "0/8", "1/8", "verified", "confirmedCount"
3. If found in CardHeader, note their position
4. Verify no text is positioned inline with or next to the progress bar

**Expected Results**:
- No text counter like "3/8 verified" in CardHeader
- Progress is indicated ONLY by the bar width
- Any field count information (if shown) is elsewhere in the UI

## Test 5: Progress Bar Thin Height

**Objective**: Verify progress bar is thin (~4-6px) not a full-height component

**Steps**:
1. Find progress bar element
2. Measure its height in pixels
3. Verify height is in range 4-6px

**Expected Results**:
- Height: 4-6px
- Not a tall button or component
- Visually appears as a thin line/bar, not as a UI element with padding/content

---

## Test Data

**Form Fields** (8 total):
1. Position Title
2. Company
3. Start Date (Month)
4. Start Date (Year)
5. End Date (Month)
6. End Date (Year)
7. [Any additional field from the actual form]
8. [Any additional field from the actual form]

**Expected Progress at Each Checkpoint**:
| Fields Confirmed | Expected Bar Width |
|------------------|-------------------|
| 0/8 | 0% |
| 1/8 | 12.5% |
| 2/8 | 25% |
| 3/8 | 37.5% |
| 4/8 | 50% |
| 5/8 | 62.5% |
| 6/8 | 75% |
| 7/8 | 87.5% |
| 8/8 | 100% |

---

## Scoring Guide

| Test | Pass Criteria | Confidence |
|------|---------------|-----------|
| Test 1: Visibility & Position | Progress bar at top, above title | High (DOM inspection) |
| Test 2: Full-Width Gradient | Spans 99-100% width, has blue-purple gradient | High (CSS inspection) |
| Test 3: Animation | Width grows 0→100% proportionally | High (DOM measurement) |
| Test 4: No Text Counter | No "N/M" text in CardHeader | High (text search) |
| Test 5: Thin Height | 4-6px height | High (dimension measurement) |

**Overall Progress Bar Feature Score** = Average of Test Pass Rates
- All 5 tests pass → 1.0 (100%)
- 4/5 tests pass → 0.8 (80%)
- 3/5 tests pass → 0.6 (60%)
- <3/5 tests pass → <0.6 (below threshold)
