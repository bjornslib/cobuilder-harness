# Unified Form Page — Stitch Design Reference

**Source**: Stitch Project `738488051630944753` / Screen `bffc2c56bb194f11ae752f643b3ef8da`
**Screen Name**: `unified_form_page-chat` (Chat Mode variant)
**Captured**: 2026-02-25
**Stitch URL**: https://stitch.withgoogle.com/projects/738488051630944753

---

## Overview

This screen represents the **Chat Mode** of the Unified Form Page — a live verification call interface where an AI voice agent (Aura) conducts employment verification while a human verifier observes and confirms details in real-time. The design must also support a **Voice Mode** (not yet captured from Stitch).

The two modes (Chat + Voice) share the same form structure but differ in how the conversation is presented and how the verifier interacts.

---

## Layout Architecture

**Viewport**: Desktop-first, responsive via Tailwind `lg:` breakpoints
**Grid**: 12-column, split `lg:col-span-7` (form) / `lg:col-span-5` (transcript)
**Max width**: 1400px centered
**Background**: Slate-50 with subtle blue/purple gradient blurs (decorative)

```
┌──────────────────────────────────────────────────────────────────┐
│  HEADER BAR (sticky, rounded, floating shadow)                   │
│  [Speaking]  ||||||||| waveform |||||||||  [Mute] [⚙] [End Call] │
├──────────────────────────────────┬───────────────────────────────┤
│  LEFT PANEL (7 cols)             │  RIGHT PANEL (5 cols)         │
│                                  │                               │
│  Work History Verification       │  LIVE TRANSCRIPT              │
│  ─────────────────────────       │  ─────────────────            │
│  Candidate: Bjorn Schliebitz    │  Agent (Aura): "Hi! This is   │
│  Company: Engage & Experience    │  Aura. Thanks for joining..." │
│  Case Ref: #8291-AB-VER         │                               │
│                                  │  Verifier: "Hello, yes I'm    │
│  [Yes] [No] Employment confirm   │  ready."                      │
│                                  │                               │
│  Check Point | Statement         │                               │
│  Start Date  | Waiting...        │                               │
│  End Date    | Waiting...        │                               │
│  Position    | Waiting...        │                               │
│  Emp Type    | Waiting...        │                               │
│                                  │                               │
│  Verifier: [input field]         │                               │
│  [Submit Verification]           │                               │
└──────────────────────────────────┴───────────────────────────────┘
```

---

## Component Breakdown

### 1. Header Bar

- **Position**: Sticky top-4, z-50, white bg, rounded-2xl, floating shadow
- **Left third**: Status indicator — purple badge "SPEAKING" with animated pulse icon (`volume_up`)
- **Center**: Audio waveform — 10 animated bars (`waveform-bar` class), staggered `animation-delay`
- **Right third**: Action buttons
  - **Mute**: Slate bg, `mic_off` icon, hover → darker slate
  - **Settings**: Icon-only (`settings`), ghost button
  - **End Call**: Red-500 bg, `call_end` icon + "End Call" text

### 2. Left Panel — Verification Form

#### 2a. Panel Header
- Title: "Work History Verification" (xl, bold, slate-900)
- Subtitle: "Verify employment details for the candidate below" (sm, slate-500)

#### 2b. Candidate Info Card
- Slate-50 bg, rounded-xl, border slate-100
- Left side: Label "CANDIDATE" (xs, uppercase, tracking-wider) → Name (bold, lg) → Company (sm, slate-500)
- Right side: Label "CASE REFERENCE" → Mono-formatted ref number

#### 2c. Employment Confirmation
- Question: "Was [name] employed at [company]?"
- Two buttons: **Yes** / **No** — equal width (grid-cols-2), slate-200 bg, hover → slate-300
- Contained in slate-50 card with border

#### 2d. Checkpoint Table
- Header row: "Check Point" (4 cols) | "Statement Captured" (8 cols)
- Rows (each 12-col grid):
  - **Start Date** — "Waiting for response..." (italic, slate-400)
  - **End Date** — "Waiting for response..."
  - **Position Title** — "Waiting for response..."
  - **Employment Type** — "Waiting for response..."
- Rows have hover:bg-slate-50 + bottom border

#### 2e. Footer — Verifier Input
- Label: "VERIFIER FOR [COMPANY]" (xs, uppercase, tracking-wider)
- Text input: placeholder "e.g. Sarah Jenkins", focus ring → primary blue
- Submit button: Full-width, currently **disabled** (slate-400 bg, cursor-not-allowed)
  - Active state should be: primary blue bg with shadow

### 3. Right Panel — Live Transcript (Chat Mode)

#### 3a. Panel Header
- Icon: `chat_bubble_outline` (slate-400)
- Title: "LIVE TRANSCRIPT" (xs, bold, uppercase, tracking-widest)
- Status badge: Green "LIVE" with mic icon

#### 3b. Chat Bubbles
- **Agent (Aura)** bubbles:
  - Alignment: left (`items-start`)
  - Background: `agent-bubble-light` (blue-50) with `agent-bubble-border` (blue-100)
  - Rounded: `rounded-2xl rounded-tl-sm` (sharp top-left corner)
  - Header: Agent name (blue-600, uppercase, 10px) + timestamp (slate-400)

- **Verifier** bubbles:
  - Alignment: right (`items-end self-end`)
  - Background: `verifier-bubble-light` (slate-100) with `verifier-bubble-border` (slate-200)
  - Rounded: `rounded-2xl rounded-tr-sm` (sharp top-right corner)
  - Header: timestamp only (no name label)

- Max width: 90% of container
- Auto-scroll to bottom via JS

---

## Design Tokens

### Colors
| Token | Value | Usage |
|-------|-------|-------|
| `primary` | `#2563EB` (Blue-600) | Focus rings, active states, agent name |
| `background-light` | `#F8FAFC` (Slate-50) | Page background |
| `card-light` | `#FFFFFF` | Panel backgrounds |
| `accent-gradient-start` | `#2563EB` (Blue-600) | Decorative gradients |
| `accent-gradient-end` | `#9333EA` (Purple-600) | Decorative gradients |
| `agent-bubble-light` | `#EFF6FF` (Blue-50) | Agent chat bubbles |
| `agent-bubble-border` | `#DBEAFE` (Blue-100) | Agent bubble border |
| `verifier-bubble-light` | `#F1F5F9` (Slate-100) | Verifier chat bubbles |
| `verifier-bubble-border` | `#E2E8F0` (Slate-200) | Verifier bubble border |

### Typography
- **Font**: Inter (300–700 weights)
- **Display/Body**: Both Inter
- **Label pattern**: `text-xs font-semibold uppercase tracking-wider text-slate-400`

### Shadows
| Name | CSS | Usage |
|------|-----|-------|
| `glow` | `0 0 20px rgba(37,99,235,0.15)` | Active/focused elements |
| `soft` | `0 4px 6px -1px rgba(0,0,0,0.05)` | Cards |
| `floating` | `0 10px 15px -3px rgba(0,0,0,0.05)` | Header bar |

### Border Radius
- Default: `0.5rem`
- Cards/panels: `rounded-2xl`
- Buttons: `rounded-lg`
- Badges: `rounded-full`

---

## Animations

### Waveform Bars
```css
@keyframes waveform {
    0%, 100% { height: 10px; opacity: 0.5; }
    50% { height: 24px; opacity: 1; background-color: #3b82f6; }
}
```
- 10 bars, 3px wide, staggered delays (0.1s–0.6s)
- Duration: 1.2s ease-in-out infinite

### Speaking Pulse
- Uses Tailwind `animate-pulse` on the volume icon
- 3s cubic-bezier infinite

---

## States (Inferred from Design)

### Form States
| State | Visual |
|-------|--------|
| **Waiting** | Checkpoint values show "Waiting for response..." in italic slate-400 |
| **Captured** | Value replaces placeholder (presumably in bold slate-900) |
| **Confirmed (Yes)** | Yes button → blue/green active state |
| **Denied (No)** | No button → red/amber active state |
| **Submit disabled** | Slate-400 bg, cursor-not-allowed (current state) |
| **Submit enabled** | Blue-600 bg, hover darker, shadow |

### Call States
| State | Header Badge |
|-------|-------------|
| **Speaking** | Purple badge, animated pulse |
| **Listening** | (Not shown — likely green or blue badge) |
| **Muted** | Mute button active state |
| **Call Ended** | (Not shown — likely redirect or summary view) |

---

## Voice Mode — Design Reference

**Source**: Screen `da75b7e68c374b35b2019a6ef29de344` (`unified_form_page-voice`)

### Key Differences from Chat Mode

The Voice Mode shares the same 7/5 grid layout and design tokens but has significant differences in both panels:

### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  NO SEPARATE HEADER — controls moved into right panel header     │
├──────────────────────────────────┬───────────────────────────────┤
│  LEFT PANEL (7 cols)             │  RIGHT PANEL (5 cols)         │
│                                  │  ┌─────────────────────────┐  │
│  Live Work History Verification  │  │ LIVE TRANSCRIPT [Live]  │  │
│  "Verification in progress       │  │ [Mute] [End Call]       │  │
│   via Voice Agent"               │  ├─────────────────────────┤  │
│                                  │  │                         │  │
│  Candidate: Alex Morgan          │  │ Call Started 10:42 AM   │  │
│  Company: TechFlow Dynamics      │  │                         │  │
│  Case Ref: #8291-AB-VER         │  │ Agent: "Hello, my name  │  │
│                                  │  │ is Aura..."             │  │
│  Field | Claimed | Verified | ✓  │  │                         │  │
│  Start | 2020-01-15 | Jan 15 | ✅│  │ Verifier: "Yes, this is │  │
│  End   | Present | Current  | ✅│  │ Sarah, the HR Manager"  │  │
│  Title | Sr Eng  | Sr Softw | 🔄│  │                         │  │
│  Salary| $120K   | [pulse]  | ⏳│  │ (more messages...)       │  │
│  Rehire| Yes     | [pulse]  | ⏳│  │                         │  │
│                                  │  ├─────────────────────────┤  │
│  Verifier: [input]  [Submit ✓]   │  │ 🔊 |||||| SPEAKING...  │  │
└──────────────────────────────────┴──┴─────────────────────────┘──┘
```

### Left Panel — Enhanced Verification Table

Unlike Chat Mode's simple waiting states, Voice Mode shows a **4-column verification table** with live progress:

| Column | Width | Content |
|--------|-------|---------|
| **Field** | 3 cols | Field name (Start Date, End Date, Job Title, Salary, Rehire Eligible) |
| **Claimed** | 3 cols | Candidate's claimed value (mono font) |
| **Verified Value** | 5 cols | Agent-captured value — editable input field |
| **Status** | 1 col | Icon indicator |

#### Row States

| State | Background | Border | Input Style | Status Icon |
|-------|-----------|--------|-------------|-------------|
| **Verified** | `slate-50/50` | `slate-200` solid | Green border, green text, readonly | `check_circle` (green-600) |
| **In Progress** | `blue-50` | `blue-200` solid + left blue bar | Blue border, pulsing, blue ping dot | `sync` (amber-500, slow spin) |
| **Pending** | transparent | `slate-300` dashed, `opacity-60` | Skeleton pulse placeholder | `schedule` (slate-400) |

#### Submit Button
- **Enabled state** (unlike Chat Mode's disabled): Gradient blue→purple, shadow, hover scale effect
- Icon: `verified_user`
- Text: "Submit Verification"

### Right Panel — Transcript with Embedded Controls

#### Header (replaces separate header bar)
- `forum` icon + "LIVE TRANSCRIPT" label
- Live indicator: pulsing green dot + "Live" badge
- **Mute** + **End Call** buttons inline (moved from header bar)

#### Conversation Thread
- Timestamp separator: "Call Started 10:42 AM" centered pill
- **Agent bubbles**: Same as Chat Mode (blue-50, left-aligned) but with inline `<span>` formatting for candidate names (blue-600, semibold)
- **Verifier bubbles**: Purple label ("VERIFIER" in purple-600) instead of no label in Chat Mode
- **Active message indicator**: Blue cursor blink (`w-1.5 h-4 bg-blue-500 animate-pulse`) appended to latest agent message
- **Glow effect**: Active agent bubble has `shadow-glow` instead of `shadow-sm`

#### Footer — Speaking Status Bar
- Rounded pill container with:
  - `graphic_eq` icon (purple-500)
  - 5 animated wave bars (purple, `scaleY` animation)
  - "SPEAKING..." label (xs, bold, uppercase)
- Right side: Volume + overflow menu icon buttons

### Design Differences Summary

| Aspect | Chat Mode | Voice Mode |
|--------|-----------|------------|
| **Header bar** | Separate sticky header with waveform | No header — controls in right panel |
| **Subtitle** | "Verify employment details..." | "Verification in progress via Voice Agent" |
| **Form columns** | 2 (Check Point + Statement) | 4 (Field + Claimed + Verified + Status) |
| **Form row states** | Waiting only | Verified / In Progress / Pending |
| **Submit button** | Disabled (slate-400) | Active gradient (blue→purple) |
| **Verifier label** | No label on bubbles | "VERIFIER" label (purple-600) |
| **Call timestamp** | None | "Call Started 10:42 AM" pill |
| **Active message** | No indicator | Blue cursor blink + glow shadow |
| **Bottom bar** | None | Speaking status with wave animation |
| **Icons library** | Material Icons Outlined | Material Symbols Outlined (different package) |

---

## Mode Switching (Cross-Mode Requirements)

Both modes should be accessible from the same page. Implementation should support:

1. **Toggle/Tab control**: Switch between Chat and Voice mode without losing form state
2. **Shared state**: Candidate info, case reference, and verified values persist across modes
3. **Right panel swap**: Only the right panel content changes; left panel is shared
4. **Header adaptation**: Chat Mode has a full-width header bar; Voice Mode embeds controls in right panel header

---

## Technical Notes

- Built with **Tailwind CSS** (CDN with forms + container-queries plugins)
- Chat Mode uses **Material Icons Outlined**; Voice Mode uses **Material Symbols Outlined** (different CDN)
  - Implementation should standardize on one (recommend Material Symbols Outlined — newer, more flexible)
- Custom scrollbar styling (6px, slate colors)
- `overflow-hidden` on body prevents page scroll — panels scroll independently
- Chat auto-scrolls to bottom on load via vanilla JS
- Voice Mode wave animation uses `scaleY` transform (vs Chat Mode's `height` animation)

---

## v2.0 Design Amendments (2026-02-27 Stakeholder Review)

**Source**: Bjorn + Hayden walkthrough review of prototype. Transcript at `~/Downloads/review___walkthrough_prototype_and_insights_transcript.txt`.

These amendments override the original Stitch design where they conflict.

### A1: Animated Agent Text (Streaming)

All AURA chat messages must stream in word-by-word (typewriter effect). No pre-rendered static text. Animation begins within 300ms of message creation.

### A2: AURA Silent on Clean Confirmations

When the verifier confirms a field whose value matches the candidate's claim:
- **No AURA chat message is generated**
- **No verifier action appears in chat**
- The form state updates silently

AURA only speaks when:
- Page loads (intro message — always animated in)
- Verifier MODIFIES a field value (discrepancy detected)
- Verifier asks a question in the chat input

### A3: Verifier Modifications Appear as Chat Bubbles

When the verifier changes a field value (enters something different from the candidate's claim):
1. A verifier chat bubble appears: e.g., "Start date updated to 15 Jan 2019"
2. AURA responds contextually: "I've recorded the updated start date. The candidate claimed 1 March 2019. Any additional context?"

This does NOT happen on confirmations — only modifications.

### A4: Reduced Visual Noise — No "All Green"

- **Completed/confirmed fields**: Fade to muted grey (not green)
- **Updated fields (discrepancy)**: Distinct highlight color (amber/orange, not green)
- **Active field**: Only visually dominant item — both color AND size
- "Updated" and "Confirmed" must have distinct visual treatments

### A5: Progressive Size Hierarchy (All Fields)

- **Active field/question**: Expanded, visually highlighted, dominant
- **Completed fields**: Shrink to compact representation
- **Pending fields**: Not visible (progressive disclosure)
- Transition between states is animated (shrink outgoing, expand incoming)
- Applies to ALL fields including the employment gate question, not just dates

### A6: Employment Gate Greys Out After Answer

After the verifier answers Yes/No, the "Was [name] employed at [company]?" question fades to the same muted grey as all other completed steps. Remains visible but de-prioritized.

### A7: Full-Width Progress Bar + Candidate Name Repositioned

- Progress bar spans the full width of the form area at the very top (not a corner widget)
- Candidate name (e.g., "Jane Smith — Acme Corp") moves to top-right
- Progress bar tracks fields resolved / total fields

### A8: Rename Approval Section

- Label: "Approve Verification" (not "Verifier for [Company]")
- Placeholder: "Your name" (not "e.g. Sarah Jenkins")
- No industry jargon — the end user is a non-technical HR/admin contact

### A9: Signature/Approval Hidden Until All Fields Complete

- The approval section (name input + submit) is completely hidden during form completion
- It appears with a fade-in animation only after every field has been actioned
- It does not appear if any field remains unresolved

### A10: Submit Button Inline with Name Input

- Name input and "Submit Verification" button on the same horizontal line
- Submit button is proportionate (not full-width)
- Layout: `flex` row with input growing and button at natural width

### A11: Voice Mode — No Live Transcript, Chat Minimises

When switching to voice mode:
- Chat panel minimises (animates out)
- A minimal live call indicator is shown (waveform + "On Call" badge)
- No transcript text is rendered during active voice session
- Chat panel is manually re-expandable via a toggle

### Design Principles (from review)

1. **The verifier is not technical** — no industry jargon, everything self-explanatory
2. **Let the form do the work** — chat only intervenes on discrepancies or questions
3. **Visual hierarchy via size + color** — active = large + colored, completed = small + grey
4. **Progressive disclosure** — one field at a time, signature last
5. **Friendly, not robotic** — AURA's tone is approachable, animations feel natural

---

## Source References

### Chat Mode
- Screen ID: `bffc2c56bb194f11ae752f643b3ef8da`
- Re-fetch code: `mcp__stitch__fetch_screen_code(projectId="738488051630944753", screenId="bffc2c56bb194f11ae752f643b3ef8da")`
- Re-fetch image: `mcp__stitch__fetch_screen_image(projectId="738488051630944753", screenId="bffc2c56bb194f11ae752f643b3ef8da")`

### Voice Mode
- Screen ID: `da75b7e68c374b35b2019a6ef29de344`
- Re-fetch code: `mcp__stitch__fetch_screen_code(projectId="738488051630944753", screenId="da75b7e68c374b35b2019a6ef29de344")`
- Re-fetch image: `mcp__stitch__fetch_screen_image(projectId="738488051630944753", screenId="da75b7e68c374b35b2019a6ef29de344")`

### Project
- Project ID: `738488051630944753`
- Stitch URL: https://stitch.withgoogle.com/projects/738488051630944753
