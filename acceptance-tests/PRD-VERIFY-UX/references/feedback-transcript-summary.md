---
title: "Hayden Feedback Transcript Summary"
status: active
type: reference
last_verified: 2026-03-05
---

# Hayden Feedback — Verify-Check UX Improvements

**Source**: Friday sync call walkthrough, Jan 2026
**Attendees**: Hayden (user/founder), Bjorn
**Key Quote**: "What I'm going to do with all of this feedback is share the transcript with my coding assistant and have it create updated screens."

## 1. Progress Bar → Full-Width at Top (01:20–01:21)

**Hayden's Feedback**:
> "That verified bar should be at the top. It should be left-aligned and right-aligned all the way across. The top has a block bar — not just in a right-aligned corner."

> "Right now you're not paying attention to it because you're looking at the center of the form. If it's a full part at the top, your eyes aren't distorted."

**Current State**: Small `w-24` green bar + text counter, right-aligned in CardHeader
**Target**: Full-width blue-to-purple gradient bar at absolute top, above title, thin (~6px)

---

## 2. Active Field Expands, Completed Fields Shrink (01:23)

**Hayden's Feedback**:
> "That start date that you confirmed should shrink and the other one — the end date that you're working on — is enlarged."

> "It's not only color that you're relying on for highlighting something — it's color and size."

**Current State**: All confirmed fields stay full-size with green background
**Target**:
- Confirmed fields: shrunk (smaller text, reduced padding, muted/faded)
- Active field: expanded (larger, more prominent)
- Editing field: expanded with yellow/amber background
- Use `transition-all duration-300` for smooth animation

---

## 3. Chat Agent — Only Speak on Discrepancy (01:28)

**Hayden's Feedback**:
> "If someone's concentrating on the form, let them just concentrate. If the UX is doing its job — extended, highlighted, confirmed — they know. If you keep putting in words, they're going to learn to ignore it."

**Bjorn's Agreement**:
> "Don't put in the chatbot response when you just confirm, but do put in a response when they've made a change."

**Current State**: Agent responds in chat on every field confirmation
**Target**: Agent only sends messages:
1. Initial welcome/introduction (types out with animation)
2. When "Change" button is clicked (discrepancy detected)

---

## 4. Signature Field Hidden Until Complete (01:26)

**Hayden's Feedback**:
> "It shouldn't be there at all because it's just in the way. It's only until you're finished does that pop up."

**Current State**: `VerifierNameInput` + Submit always visible in bottom bar
**Target**: Bottom bar only renders when `resolvedCount >= totalCount && totalCount > 0`

---

## 5. "Verifier" Label → Plain Language (01:24)

**Hayden's Feedback**:
> "They don't see themselves as a verifier. That's industry talk. Who the heck is a verifier? Is it me? Should I sign this name, print name, type name?"

**Current State**: Label "verifier", placeholder "EG"
**Target**:
- Label: "Your name"
- Placeholder: "Type your full name to confirm"

---

## 6. Chat Panel Minimizes During Voice (01:31–01:32)

**Hayden's Feedback**:
> "I don't think we should show the transcript live when they're on a call — it's a distraction."

**Bjorn's Follow-up**:
> "Does that mean the whole chat ought to disappear? Actually, it ought to minimize."

**Current State**: `TranscriptPanel` shows full transcript during voice mode
**Target**: When voice mode active:
- Hide full message list and text input
- Show only: LIVE badge + waveform animation + End Call button
- Minimize to a compact voice indicator panel

---

## 7. Chat Intro Text Animates (01:00)

**Bjorn's Feedback**:
> "I think it's actually important to show that there's a chatbot that slowly writes out what they're saying."

**Current State**: Welcome message appears instantly
**Target**: First agent message types out character-by-character (typewriter animation)

---

## 8. Candidate Info — Reduce Noise (01:22)

**Hayden's Feedback**:
> "You're getting the candidate is just stating a fact. John Smith — you're not verifying that. So you've got noise there."

**Current State**: `CandidateInfoBlock` displayed prominently
**Target**: Reduce visual weight:
- Smaller text (text-xs)
- Muted color (text-gray-400)
- Move below title or render as single line
- Not inline with form header

---

## What to Keep (Confirmed as Working)

**Progressive field disclosure** — Hayden explicitly agreed with showing fields as verifier progresses
**Two-column layout** — Form left, chat right
**Voice ↔ chat switching** — Start Call / End Call toggle validated
**Confirm / Change buttons** — Interaction model is correct
**FormEventEmitter architecture** — LiveKit data channel for agent communication is right approach

---

## Design Direction Summary

The feedback emphasizes **visual hierarchy and minimalism**:
1. Progress is immediately visible (full-width bar)
2. Active content stands out (expansion + color + size)
3. Completed content fades (shrinking + muting)
4. Distraction is minimized (agent quiet unless change detected, chat hidden during voice)
5. Plain language throughout (no "verifier" jargon)

**Mindset**: Remove cognitive noise. Let the UX do the talking. Only use words when something unexpected happens (change).
