---
title: "Pilot Terminology Rename — Technical Spec"
description: "Rename guardian agent references to Pilot terminology across docs and code"
version: "1.0.0"
last-updated: 2026-03-21
status: active
type: sd
---

# SD-PILOT-RENAME-001: Rename Guardian Agent to Pilot

## Overview

The `guardian.py` AgentSDK agent should be distinguished from the interactive CoBuilder session by renaming it to **Pilot**. This is a terminology-only change — no functional code changes.

## Terminology Map

| Entity | Current Name | New Name | Role |
|--------|-------------|----------|------|
| Opus interactive session | CoBuilder Guardian / System 3 | **CoBuilder** | Strategic oversight, PRD design, validation |
| guardian.py AgentSDK agent | "guardian agent" / "Guardian agent" | **Pilot** | Drives DOT graph execution, dispatches runner, handles gates |
| pipeline_runner.py | Runner | **Runner** (unchanged) | Zero-LLM state machine |
| AgentSDK codergen/research/refine | Workers | **Workers** (unchanged) | Implementation agents |

## Key Distinction

**CoBuilder** = the interactive Guardian session (you, the Opus meta-orchestrator).
**Pilot** = the headless AgentSDK agent launched by `guardian.py` that drives the DOT pipeline.

They are NOT the same entity despite currently sharing the "guardian" name.

## Files to Update

### 1. `cobuilder/engine/guardian.py` — Docstrings and Comments Only
- Update module docstring to mention "Pilot agent"
- Update `build_system_prompt()` opening line: "You are a Headless Guardian agent" → "You are the Pilot agent"
- Update function docstrings that say "Guardian agent" where they mean the AgentSDK process → "Pilot agent"
- Update `_create_guardian_stop_hook()` docstring
- Update `build_options()` docstring
- Update `_run_agent()` docstring
- Update `launch_guardian()` docstring — clarify it launches the Pilot
- Update `main()` docstring
- Update print statements: "[Layer 0] Launching guardian" → "[Layer 0] Launching Pilot"
- **DO NOT** rename function names or file names — only prose/comments/docstrings/print messages

### 2. `CLAUDE.md` (project root)
- In the "CoBuilder Pipeline Engine" section, update references from "Guardian agent" to "Pilot"
- Update the `guardian.py` description: "Guardian agent launcher" → "Pilot agent launcher"
- Update the architecture diagram text

### 3. `cobuilder/CLAUDE.md` (if exists, or skip)
- Same updates as root CLAUDE.md for the cobuilder package section

## Rules
- **DO NOT rename files** (guardian.py stays as guardian.py)
- **DO NOT rename functions** (launch_guardian stays as launch_guardian)
- **DO NOT rename CLI flags** (--dot, --multi stay the same)
- **ONLY change**: prose in docstrings, comments, print statements, and markdown docs
- Preserve the distinction: "CoBuilder" = interactive session, "Pilot" = headless AgentSDK agent
