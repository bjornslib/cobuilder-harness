---
prd_id: PRD-LIFECYCLE-001
title: "Harness Lifecycle Engine: Automated Feedback Loops, Unified State Machine, and Fleet Dashboard"
status: draft
created: 2026-03-02
last_verified: 2026-03-02
grade: authoritative
---

# PRD-LIFECYCLE-001: Harness Lifecycle Engine

## 1. Executive Summary

Our Claude Code harness excels at **cognitive orchestration** — hierarchical delegation, independent validation, long-term memory, and blind acceptance testing. But it has a critical gap in **DevOps automation**: when CI fails, a reviewer requests changes, or a PR is approved, our system relies on manual orchestrator intervention to detect and react. Meanwhile, Composio's agent-orchestrator demonstrates that automated event-reaction pipelines, formal state machines, and fleet dashboards are table stakes for production-grade agent orchestration.

This PRD closes the four largest gaps identified in the [Composio comparison](../../.claude/documentation/composio-vs-harness-comparison.md) while preserving our architectural advantages (3-level hierarchy, independent validation, memory, scope enforcement). The key design constraint: **every new capability must integrate with our existing hierarchy rather than flattening it**.

### What This Is NOT

- NOT replacing our 3-level hierarchy with Composio's flat model
- NOT adding agent agnosticism (we stay Claude Code-native for deeper integration)
- NOT reimplementing Composio in our harness — we're adopting their best ideas within our architecture

## 2. Goals

| ID | Goal | Success Metric |
|----|------|---------------|
| G1 | CI failures and review comments automatically route to the responsible worker | ≤60s from GitHub event to worker receiving context (measured via hook logs) |
| G2 | A single state machine governs task lifecycle from spawn to merge | All orchestrator sessions report state via unified FSM; no session in an "unknown" state |
| G3 | Operators can monitor all active sessions from a single interface | Dashboard loads in <2s, shows all sessions, state transitions updated within 30s |
| G4 | Session management is discoverable and consistent | All operations available via `harness <verb>` CLI; `harness help` lists all commands |
| G5 | Existing validation, memory, and hierarchy remain fully operational | All current hook tests + completion state tests pass; blind validation workflow unchanged |

## 3. User Stories

### US-1: Orchestrator Reacting to CI Failure
As an orchestrator managing workers on a feature branch, when CI fails on a PR opened by one of my workers, I want the CI failure logs and context to be automatically routed to the worker that owns the branch, so the worker can fix the issue without me manually detecting the failure, reading the logs, and creating a new task.

### US-2: Worker Receiving Review Feedback
As a worker implementing a feature, when a human reviewer requests changes on my PR, I want the review comments extracted and delivered to me as a new task with full context, so I can address the feedback immediately rather than waiting for my orchestrator to notice the review.

### US-3: System 3 Monitoring Fleet State
As System 3 overseeing multiple orchestrators, I want a single view showing each orchestrator's current lifecycle state (spawning, working, pr_open, ci_failing, review_pending, validated, merged, done), so I can identify stuck sessions and intervene proactively.

### US-4: Operator Launching and Managing Sessions
As a human operator, I want to run `harness spawn <project> <issue>` to start a new session, `harness status` to see all running sessions, and `harness send <session> "message"` to intervene — with consistent, discoverable commands rather than remembering `ccsystem3`, `launchorchestrator`, tmux attach patterns, etc.

### US-5: Guardian Verifying State Consistency
As a guardian running independent validation, I want the lifecycle state machine to expose its current state and transition history for any session, so I can cross-reference claimed state against actual evidence (PRs, CI checks, test results).

## 4. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Harness CLI (`harness`)                         │
│  spawn | status | send | kill | restore | dashboard                    │
├────────────────────────────────────────────────────────────────────────┤
│                     Lifecycle State Machine (FSM)                       │
│  States: spawning → working → pr_open → ci_failed → working →          │
│          review_pending → changes_requested → working → approved →      │
│          validating → validated → mergeable → merged → done             │
│  + stuck, errored, killed (terminal/error states)                      │
│  Transitions: event-driven, with guards and timeouts                   │
├───────────────┬────────────────────────────────────────────────────────┤
│  Reaction     │  Event Sources                                         │
│  Engine       │  ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│               │  │ GitHub   │ │ CI/CD    │ │ Session  │              │
│  CI → worker  │  │ Webhooks │ │ Webhooks │ │ Monitors │              │
│  Review → wkr │  └──────────┘ └──────────┘ └──────────┘              │
│  Timeout → ↑  │                                                        │
├───────────────┴────────────────────────────────────────────────────────┤
│  Existing Harness Infrastructure (PRESERVED)                           │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐         │
│  │ System 3   │ │ Orchestr.  │ │ Workers    │ │ Validation │         │
│  │ (Level 1)  │ │ (Level 2)  │ │ (Level 3)  │ │ Agent      │         │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘         │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐         │
│  │ Hindsight  │ │ Beads      │ │ DOT Pipes  │ │ Completion │         │
│  │ Memory     │ │ Tracking   │ │            │ │ Promises   │         │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘         │
└────────────────────────────────────────────────────────────────────────┘
```

### Integration with 3-Level Hierarchy

The lifecycle engine sits **alongside** (not above) the existing hierarchy:

| Component | Relationship to Hierarchy |
|-----------|--------------------------|
| FSM | Tracks session state; System 3 and Guardian can query it; does NOT override hierarchy decisions |
| Reaction Engine | Routes events to the correct level — CI failures go to workers (L3), not orchestrators (L2) |
| Dashboard | Read-only view for humans and System 3; no control actions bypass the hierarchy |
| CLI | Convenience wrapper around existing launch mechanisms; delegates to `ccsystem3` / `launchorchestrator` internally |

### State Machine Integration Points

The FSM unifies currently-distributed state:

| Current System | What It Tracks | FSM Integration |
|----------------|----------------|-----------------|
| Beads | Task status (open/in-progress/done) | Bead transitions trigger FSM events |
| DOT Pipeline | Node execution state | Node transitions map to FSM transitions |
| Completion Promises | Session-level acceptance criteria | Promise met/unmet feeds `validating → validated` |
| tmux session | Process alive/dead | Heartbeat feeds `working` / `stuck` / `errored` |
| GitHub PR | PR state, CI, reviews | Webhook events drive `pr_open`, `ci_failed`, `review_pending`, etc. |

## 5. Epic 1: Reaction Engine — Automated CI and Review Feedback Loops

**Goal**: When GitHub events occur (CI failure, review comment, PR approval), automatically extract relevant context and route it to the responsible agent at the correct hierarchy level.

### Scope

- **Event ingestion**: GitHub webhook receiver (lightweight Python HTTP server) that accepts `check_run`, `pull_request_review`, `pull_request_review_comment`, `pull_request`, and `status` events
- **Event-to-session mapping**: Map PR branch → session ID → responsible agent (worker or orchestrator) using a session registry (JSON file at `.claude/state/session-registry.json`)
- **Context extraction**: For CI failures, fetch the last 200 lines of failing job logs via `gh` CLI; for reviews, extract comment body, file path, and line numbers
- **Routing logic**: CI failures → responsible worker (Level 3); review comments → responsible worker; PR approval → orchestrator (Level 2); PR merge → System 3 (Level 1)
- **Delivery mechanism**: Write context to a well-known file path that the target agent's session monitor picks up; send tmux `send-keys` with a nudge message referencing the file
- **Reaction configuration**: YAML-based reaction rules per project (`.claude/reactions.yaml`)
- **Retry and escalation**: If a worker doesn't respond within configurable timeout, escalate to orchestrator; if orchestrator doesn't respond, escalate to System 3

### Acceptance Criteria

- [ ] AC-1.1: Webhook server starts on configurable port, authenticates requests via webhook secret
- [ ] AC-1.2: CI failure on a worker's PR branch triggers context file creation at `.claude/state/reactions/<session-id>/ci-failure-<timestamp>.md` within 30s
- [ ] AC-1.3: Context file contains: failing job name, last 200 log lines, PR URL, branch name, commit SHA
- [ ] AC-1.4: Worker session receives tmux `send-keys` nudge with path to context file
- [ ] AC-1.5: Review comment on a worker's PR creates context file with: reviewer name, comment body, file path, line range, review state (approve/request_changes/comment)
- [ ] AC-1.6: PR approval event routes notification to the orchestrator level, not the worker
- [ ] AC-1.7: Escalation fires after configurable timeout (default 10 min) if target agent hasn't acknowledged
- [ ] AC-1.8: `.claude/reactions.yaml` supports per-event configuration: `auto` (true/false), `maxRetries`, `escalateAfterMinutes`, `targetLevel`
- [ ] AC-1.9: All events are logged to `.claude/state/reactions/event-log.jsonl` with timestamp, event type, source, target, delivery status
- [ ] AC-1.10: Existing hook tests pass; webhook server does not interfere with current session-start or stop hooks

### Technical Approach

```
.claude/
├── scripts/
│   └── lifecycle/
│       ├── webhook-server.py       # GitHub webhook receiver
│       ├── event-router.py         # Event → session mapping + routing
│       └── context-extractor.py    # CI logs / review comment extraction
├── state/
│   ├── session-registry.json       # Branch → session → agent mapping
│   └── reactions/
│       ├── event-log.jsonl         # Append-only event log
│       └── <session-id>/           # Per-session reaction context files
└── reactions.yaml                  # Reaction configuration
```

**Why file-based delivery**: Claude Code sessions monitor files natively (via hooks and skill prompts). File-based delivery avoids adding IPC complexity and works with both tmux-mode and SDK-mode sessions.

## 6. Epic 2: Unified Lifecycle State Machine

**Goal**: Define and implement a single FSM that tracks every session from spawn to completion, unifying state currently distributed across beads, DOT pipelines, completion promises, and tmux process monitoring.

### Scope

- **State definition**: 15 states covering the full lifecycle (see architecture diagram)
- **Transition rules**: Event-driven transitions with guard conditions (e.g., `pr_open → ci_failed` requires a failing `check_run` event)
- **State persistence**: JSON file per session at `.claude/state/sessions/<session-id>/state.json` with full transition history
- **Bead sync**: Bead status changes (`bd status`) emit events that trigger FSM transitions
- **DOT sync**: Pipeline node transitions (via `cobuilder pipeline transition`) emit events to FSM
- **Promise sync**: Completion promise `--meet` calls transition FSM toward `validated`
- **Heartbeat**: Periodic process-alive check (tmux `capture-pane` or SDK poll) that detects `stuck` and `errored` states
- **Query API**: Python module (`lifecycle.query`) for querying current state, transition history, and time-in-state for any session
- **Timeout guards**: Configurable per-state timeouts that trigger escalation events (e.g., >30 min in `working` without activity → `stuck`)

### Acceptance Criteria

- [ ] AC-2.1: FSM supports all 15 states: `spawning`, `working`, `pr_open`, `ci_pending`, `ci_failed`, `review_pending`, `changes_requested`, `approved`, `validating`, `validated`, `mergeable`, `merged`, `done`, `stuck`, `errored`, `killed`
- [ ] AC-2.2: State file at `.claude/state/sessions/<id>/state.json` contains: `current_state`, `transition_history` (array of `{from, to, event, timestamp}`), `metadata` (session type, agent level, project, issue)
- [ ] AC-2.3: `lifecycle.query.get_state(session_id)` returns current state with time-in-state
- [ ] AC-2.4: `lifecycle.query.get_history(session_id)` returns full transition history
- [ ] AC-2.5: `lifecycle.query.get_all()` returns all active sessions with current states (for dashboard)
- [ ] AC-2.6: Bead status change triggers corresponding FSM transition within 5s
- [ ] AC-2.7: DOT pipeline node transition triggers FSM state update within 5s
- [ ] AC-2.8: Completion promise `--meet` on final AC triggers `validating → validated` transition
- [ ] AC-2.9: Heartbeat detects crashed tmux session and transitions to `errored` within 60s
- [ ] AC-2.10: Per-state timeout thresholds configurable via `.claude/lifecycle-config.yaml`
- [ ] AC-2.11: Guardian/System 3 can query FSM state to cross-reference against claimed completion
- [ ] AC-2.12: All state transitions are idempotent — duplicate events don't create duplicate transitions

### Technical Approach

```python
# .claude/scripts/lifecycle/fsm.py

TRANSITIONS = {
    "spawning":           {"agent_ready": "working"},
    "working":            {"pr_opened": "pr_open", "timeout": "stuck", "crash": "errored"},
    "pr_open":            {"ci_started": "ci_pending"},
    "ci_pending":         {"ci_passed": "review_pending", "ci_failed": "ci_failed"},
    "ci_failed":          {"fix_pushed": "ci_pending", "max_retries": "stuck"},
    "review_pending":     {"changes_requested": "changes_requested", "approved": "approved"},
    "changes_requested":  {"fix_pushed": "review_pending", "timeout": "stuck"},
    "approved":           {"ci_green": "mergeable", "ci_started": "ci_pending"},
    "validating":         {"validation_passed": "validated", "validation_failed": "working"},
    "validated":          {"merge_ready": "mergeable"},
    "mergeable":          {"merged": "merged"},
    "merged":             {"cleanup_done": "done"},
    "stuck":              {"intervention": "working", "killed": "killed"},
    "errored":            {"restored": "working", "killed": "killed"},
}
```

**Why file-based state**: Aligns with our existing file-based patterns (beads, DOT, promises). No database dependency. Git-friendly. Queryable by any agent at any level.

## 7. Epic 3: Fleet Dashboard

**Goal**: Provide a real-time visual interface showing all active sessions, their lifecycle states, PR/CI status, and recent activity — accessible to both human operators and System 3.

### Scope

- **Lightweight web server**: Python (Flask or similar) serving a single-page dashboard on configurable port (default 3001)
- **Data source**: Reads from `.claude/state/sessions/` (FSM state files), `.claude/state/session-registry.json`, and `.claude/state/reactions/event-log.jsonl`
- **Views**: Fleet overview (all sessions as cards), session detail (transition timeline, recent events), and system health (webhook status, process counts)
- **Refresh**: Auto-refresh every 15s via polling (SSE upgrade in future iteration)
- **CLI fallback**: `harness status` produces a formatted terminal table for environments where a browser isn't available
- **No authentication** (v1): Local-only access; authentication deferred to future iteration

### Acceptance Criteria

- [ ] AC-3.1: `harness dashboard` starts web server on port 3001, opens browser
- [ ] AC-3.2: Fleet overview shows one card per active session with: session ID, agent level (S3/Orch/Worker), current FSM state, time in state, PR URL (if exists), last event timestamp
- [ ] AC-3.3: Session detail view shows full transition timeline with timestamps and triggering events
- [ ] AC-3.4: Color coding: green (working/validated/merged/done), yellow (review_pending/ci_pending/validating), red (ci_failed/stuck/errored/killed), blue (spawning/pr_open)
- [ ] AC-3.5: Dashboard loads in <2s with up to 20 concurrent sessions
- [ ] AC-3.6: `harness status` outputs formatted terminal table with same information as fleet overview
- [ ] AC-3.7: `harness status --json` outputs machine-readable JSON for programmatic consumption
- [ ] AC-3.8: Dashboard shows webhook server health (last event received, uptime, error count)
- [ ] AC-3.9: No new runtime dependencies beyond Python standard library + one web framework (Flask or equivalent)

### Technical Approach

```
.claude/
├── scripts/
│   └── lifecycle/
│       ├── dashboard/
│       │   ├── app.py              # Flask server
│       │   ├── templates/
│       │   │   ├── fleet.html      # Fleet overview
│       │   │   └── session.html    # Session detail
│       │   └── static/
│       │       └── style.css       # Minimal styling
│       └── cli-status.py           # Terminal table formatter
```

**Why Flask**: Lightweight, no build step, Python-native (matches our existing tooling), minimal dependencies. The dashboard is a read-only view over existing state files — it doesn't need a framework heavier than Flask.

## 8. Epic 4: Unified Session Management CLI

**Goal**: Consolidate all session management operations into a single `harness` CLI with consistent, discoverable commands.

### Scope

- **Entry point**: `harness` command (Python CLI via `__main__.py` or shell wrapper)
- **Commands**: `spawn`, `status`, `send`, `kill`, `restore`, `dashboard`, `reactions`, `help`
- **Delegation**: `harness spawn` delegates to `ccsystem3` / `launchorchestrator` / worker spawn internally — it's a convenience wrapper, not a replacement
- **Session registry**: All spawn operations register in `.claude/state/session-registry.json` with session ID, type (s3/orchestrator/worker), project, issue/epic, branch, tmux session name, spawn timestamp
- **Tab completion**: Bash/Zsh completion for commands and session IDs
- **Consistency**: All commands follow `harness <verb> [<session-id>] [options]` pattern

### Acceptance Criteria

- [ ] AC-4.1: `harness spawn <project> <issue> [--level s3|orchestrator|worker]` creates and registers a new session
- [ ] AC-4.2: `harness status` lists all active sessions with FSM state, agent level, project, time active
- [ ] AC-4.3: `harness status <session-id>` shows detailed session info including transition history
- [ ] AC-4.4: `harness send <session-id> "message"` delivers message to the session (tmux send-keys or SDK message)
- [ ] AC-4.5: `harness kill <session-id>` gracefully terminates a session (completion promise check, cleanup)
- [ ] AC-4.6: `harness restore <session-id>` attempts to restore a crashed/errored session
- [ ] AC-4.7: `harness dashboard` launches the web dashboard (Epic 3)
- [ ] AC-4.8: `harness reactions [start|stop|status]` manages the webhook server (Epic 1)
- [ ] AC-4.9: `harness help` lists all commands with descriptions
- [ ] AC-4.10: Tab completion works for commands and session IDs in Bash and Zsh
- [ ] AC-4.11: All existing launch mechanisms (`ccsystem3`, `launchorchestrator`) continue to work independently — the CLI is additive, not a replacement
- [ ] AC-4.12: Session registry survives process restarts — it's file-based, not in-memory

### Technical Approach

```
.claude/
├── scripts/
│   └── harness/
│       ├── __main__.py             # CLI entry point
│       ├── commands/
│       │   ├── spawn.py            # Delegates to existing launch scripts
│       │   ├── status.py           # Queries FSM + session registry
│       │   ├── send.py             # tmux send-keys / SDK message
│       │   ├── kill.py             # Graceful termination
│       │   ├── restore.py          # Session recovery
│       │   └── reactions.py        # Webhook server management
│       ├── registry.py             # Session registry CRUD
│       └── completions/
│           ├── harness.bash        # Bash completion
│           └── harness.zsh         # Zsh completion
```

**Shell wrapper** (installed to PATH):
```bash
#!/bin/bash
# .claude/scripts/harness/harness
exec python3 "$(dirname "$0")/__main__.py" "$@"
```

## 9. Non-Goals (Explicit Exclusions)

| Exclusion | Rationale |
|-----------|-----------|
| Agent agnosticism (Codex, Aider support) | Our value comes from deep Claude Code integration (Agent Teams, output styles, skills). Adding agent plugins would dilute this. |
| Container-based isolation (Docker, K8s) | Worktree isolation is sufficient for our use cases. Container support adds operational complexity we don't need. |
| Database-backed state | File-based state is git-friendly, simple, and sufficient for our scale (tens of sessions, not thousands). |
| Dashboard authentication | v1 is local-only. If remote access is needed later, add nginx/auth proxy. |
| Replacing existing launch scripts | `ccsystem3` and `launchorchestrator` remain the source of truth. The CLI wraps them. |

## 10. Dependencies and Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| GitHub webhook delivery unreliable | Medium | High — CI failures go undetected | Polling fallback: `gh` CLI check every 2 min as backup |
| FSM state diverges from actual state | Medium | Medium — dashboard shows stale info | Heartbeat reconciliation every 60s; manual `harness reconcile` command |
| Webhook server process crashes | Low | High — all reaction routing stops | systemd/supervisor watchdog; `harness reactions status` health check |
| Dashboard introduces security exposure | Low | Medium — local-only mitigates | Bind to 127.0.0.1 only; no secrets in dashboard |
| CLI wrapper adds confusion vs direct commands | Low | Low — both pathways work | Clear docs; `harness help` shows delegation targets |

## 11. Implementation Priority

| Order | Epic | Rationale |
|-------|------|-----------|
| 1 | Epic 2: Lifecycle FSM | Foundation — all other epics depend on session state tracking |
| 2 | Epic 4: CLI | Enables testing of FSM via `harness status`; low effort, high discoverability |
| 3 | Epic 1: Reaction Engine | Highest user value (automated CI/review loops); requires FSM for routing |
| 4 | Epic 3: Dashboard | Nice-to-have visualization; CLI `harness status` covers the basic need |

## 12. Success Criteria (Initiative Level)

| Criterion | Measurement | Target |
|-----------|-------------|--------|
| CI failure response time | Time from `check_run` failure to worker receiving context | ≤60 seconds |
| State accuracy | % of sessions where FSM state matches actual state (spot-checked by guardian) | ≥95% |
| Operator discoverability | New operator can launch, monitor, and manage sessions using only `harness help` | Yes (validated via user test) |
| Hierarchy preservation | All existing hook tests, completion state tests, and validation workflows pass | 100% pass rate |
| Dashboard utility | System 3 uses dashboard/status API for fleet monitoring instead of ad-hoc tmux checks | ≥80% of monitoring actions via dashboard |
