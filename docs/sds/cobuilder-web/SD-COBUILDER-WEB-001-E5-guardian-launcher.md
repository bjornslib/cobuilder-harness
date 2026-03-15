---
title: "SD-COBUILDER-WEB-001 Epic 5: Guardian Launcher"
status: active
type: reference
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E5
---

# SD-COBUILDER-WEB-001 Epic 5: Guardian Launcher

## 1. Problem Statement

The CoBuilder web server (PRD-COBUILDER-WEB-001) owns the initiative lifecycle, but the Guardian -- the independent validation and acceptance-test agent -- must run in a tmux session so that humans can observe, interact with, and steer it. Today, Guardians are launched manually via `ccsystem3` or by System 3 itself. The web server needs a programmatic launcher that:

1. **Creates a tmux session with the exact environment and output style** the Guardian requires, without requiring human CLI knowledge.
2. **Injects a scoped prompt** that constrains the Guardian to its defined role: writing blind acceptance tests, monitoring pipeline progress, and independently validating implementations. The Guardian must NOT create PRDs, SDs, pipelines, or launch the runner -- those are owned by the web server and `pipeline_runner.py` respectively.
3. **Provides attach/list primitives** so the web UI can offer "Open in Terminal" deep-links and display which Guardian sessions are active across initiatives.
4. **Handles tmux lifecycle concerns**: duplicate session prevention, session health checks, and zombie cleanup.

Without this, the web server cannot fulfil US-1 (starting a new initiative end-to-end) or Epic 6 (pipeline launcher triggering Guardian validation after `pipeline.completed`).

## 2. Technical Architecture

### 2.1 Class Design

`GuardianLauncher` is a stateless utility class. It does not hold references to running sessions -- it queries tmux directly each time, making it crash-safe (the web server can restart and rediscover all active Guardians).

```python
"""cobuilder/web/api/infra/guardian_launcher.py

Programmatic launcher for Guardian tmux sessions. Provides launch, attach,
list, health-check, and kill operations for the web server.

The Guardian runs Claude Code with the system3-meta-orchestrator output style
and a scoped prompt that restricts it to acceptance tests + monitoring +
validation. It does NOT create PRDs, SDs, pipelines, or launch the runner.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# --------------------------------------------------------------------------- #
# Session naming convention
# --------------------------------------------------------------------------- #
SESSION_PREFIX = "guardian-"


def _session_name(prd_id: str) -> str:
    """Deterministic tmux session name from PRD ID.

    Example: PRD-DASHBOARD-AUDIT-001 -> guardian-prd-dashboard-audit-001
    """
    return f"{SESSION_PREFIX}{prd_id.lower()}"


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #

@dataclass
class GuardianSession:
    """Metadata for an active Guardian tmux session."""
    session_name: str
    prd_id: str
    created_at: str          # ISO-8601 from tmux session_created
    attached: bool           # True if a human terminal is attached
    window_count: int


@dataclass
class LaunchResult:
    """Result of a launch() call."""
    status: str              # "ok" | "already_running" | "error"
    session_name: str
    message: str = ""


# --------------------------------------------------------------------------- #
# Core class
# --------------------------------------------------------------------------- #

class GuardianLauncher:
    """Manages Guardian tmux sessions for the CoBuilder web server.

    All methods are synchronous (subprocess calls to tmux). The FastAPI
    layer wraps them in run_in_executor() for async compatibility.
    """

    # Timing constants (seconds) -- validated in MEMORY.md tmux patterns
    SHELL_INIT_PAUSE = 2.0       # Wait for zsh to initialize
    CLAUDE_BOOT_PAUSE = 8.0      # Wait for Claude Code to start
    OUTPUT_STYLE_PAUSE = 3.0     # Wait for /output-style to render
    OUTPUT_STYLE_POST = 5.0      # Wait for output-style to take effect
    PROMPT_PAUSE = 2.0           # Wait for prompt paste to render

    def launch(
        self,
        prd_id: str,
        dot_path: str,
        target_repo: str,
        *,
        prd_path: Optional[str] = None,
        sd_paths: Optional[list[str]] = None,
        worktree_path: Optional[str] = None,
    ) -> LaunchResult:
        """Launch a Guardian tmux session for a specific initiative.

        Args:
            prd_id: Initiative identifier (e.g., PRD-DASHBOARD-AUDIT-001).
            dot_path: Absolute path to the initiative DOT pipeline file.
            target_repo: Absolute path to the target repository root.
            prd_path: Absolute path to the PRD markdown file.
            sd_paths: List of absolute paths to SD markdown files.
            worktree_path: Absolute path to the initiative worktree.

        Returns:
            LaunchResult with status and session name.
        """
        session = _session_name(prd_id)

        # Guard: prevent duplicate sessions
        if self._session_exists(session):
            return LaunchResult(
                status="already_running",
                session_name=session,
                message=f"Guardian session '{session}' is already running.",
            )

        # 1. Create detached tmux session with exec zsh
        try:
            self._create_tmux_session(session, target_repo)
        except subprocess.CalledProcessError as exc:
            return LaunchResult(
                status="error",
                session_name=session,
                message=f"tmux session creation failed: {exc.stderr or exc}",
            )
        except FileNotFoundError:
            return LaunchResult(
                status="error",
                session_name=session,
                message="tmux not found. Install tmux to launch Guardians.",
            )

        time.sleep(self.SHELL_INIT_PAUSE)

        # 2. Launch Claude Code with Guardian environment
        claude_cmd = self._build_claude_command(prd_id, dot_path)
        try:
            self._tmux_send(session, claude_cmd, pause=self.CLAUDE_BOOT_PAUSE)
        except subprocess.CalledProcessError as exc:
            self._kill_session(session)
            return LaunchResult(
                status="error",
                session_name=session,
                message=f"Claude launch failed: {exc.stderr or exc}",
            )

        # 3. Set output style to system3-meta-orchestrator
        try:
            self._tmux_send(
                session,
                "/output-style system3-meta-orchestrator",
                pause=self.OUTPUT_STYLE_PAUSE,
                post_pause=self.OUTPUT_STYLE_POST,
            )
        except subprocess.CalledProcessError as exc:
            self._kill_session(session)
            return LaunchResult(
                status="error",
                session_name=session,
                message=f"Output style injection failed: {exc.stderr or exc}",
            )

        # 4. Send scoped prompt
        scoped_prompt = self._build_scoped_prompt(
            prd_id=prd_id,
            dot_path=dot_path,
            target_repo=target_repo,
            prd_path=prd_path,
            sd_paths=sd_paths or [],
            worktree_path=worktree_path,
        )
        try:
            self._tmux_send(session, scoped_prompt, pause=self.PROMPT_PAUSE)
        except subprocess.CalledProcessError as exc:
            # Session is created and Claude is running -- prompt failure is non-fatal.
            # The human can type the prompt manually via attach().
            return LaunchResult(
                status="ok",
                session_name=session,
                message=f"Session created but prompt injection failed: {exc.stderr or exc}. "
                        f"Attach and send prompt manually.",
            )

        return LaunchResult(status="ok", session_name=session)

    def attach(self, prd_id: str) -> Optional[str]:
        """Return the tmux session name for a given PRD ID, or None if not running.

        The caller (web UI) uses this to construct a terminal deep-link:
            tmux attach -t <session_name>
        or on macOS:
            open -a Terminal && tmux attach -t <session_name>
        """
        session = _session_name(prd_id)
        if self._session_exists(session):
            return session
        return None

    def list_active(self) -> list[GuardianSession]:
        """Return all active Guardian tmux sessions with PRD associations.

        Filters tmux sessions by the guardian- prefix. Extracts PRD ID from
        session name (inverse of _session_name).
        """
        try:
            result = subprocess.run(
                [
                    "tmux", "list-sessions",
                    "-F", "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_windows}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return []

        if result.returncode != 0:
            return []

        sessions = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name, created, attached, windows = parts[0], parts[1], parts[2], parts[3]
            if not name.startswith(SESSION_PREFIX):
                continue

            # Reverse session name to PRD ID: guardian-prd-dashboard-audit-001 -> PRD-DASHBOARD-AUDIT-001
            prd_id = name[len(SESSION_PREFIX):].upper()

            sessions.append(GuardianSession(
                session_name=name,
                prd_id=prd_id,
                created_at=created,
                attached=attached != "0",
                window_count=int(windows),
            ))

        return sessions

    def is_alive(self, prd_id: str) -> bool:
        """Check if a Guardian session exists for the given PRD ID."""
        return self._session_exists(_session_name(prd_id))

    def kill(self, prd_id: str) -> bool:
        """Kill a Guardian session. Returns True if killed, False if not found."""
        session = _session_name(prd_id)
        if not self._session_exists(session):
            return False
        self._kill_session(session)
        return True

    # ----------------------------------------------------------------------- #
    # tmux primitives
    # ----------------------------------------------------------------------- #

    def _create_tmux_session(self, session: str, work_dir: str) -> None:
        """Create a detached tmux session with exec zsh.

        Uses the same pattern as spawn_orchestrator.py:
        - exec zsh: clean shell so CLAUDECODE can be unset
        - -c work_dir: tmux starts IN the target directory
        - -x 220 -y 50: wide terminal for Claude Code output
        """
        subprocess.run(
            [
                "tmux", "new-session",
                "-d",                # detached
                "-s", session,       # session name
                "-c", work_dir,      # working directory
                "-x", "220",         # width
                "-y", "50",          # height
                "exec zsh",          # clean shell
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def _tmux_send(
        self,
        session: str,
        text: str,
        pause: float = 2.0,
        post_pause: float = 0.0,
    ) -> None:
        """Send text to tmux with Enter as a separate call.

        Pattern 1 from MEMORY.md: text and Enter must be separate tmux
        send-keys calls with a pause between them. Large pastes need
        time to render before Enter is sent.
        """
        subprocess.run(
            ["tmux", "send-keys", "-t", session, text],
            check=True,
            capture_output=True,
            text=True,
        )
        time.sleep(pause)
        subprocess.run(
            ["tmux", "send-keys", "-t", session, "Enter"],
            check=True,
            capture_output=True,
            text=True,
        )
        if post_pause > 0.0:
            time.sleep(post_pause)

    def _session_exists(self, session: str) -> bool:
        """Check if a tmux session exists."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", session],
            capture_output=True,
        )
        return result.returncode == 0

    def _kill_session(self, session: str) -> None:
        """Kill a tmux session (best-effort, no error on missing)."""
        subprocess.run(
            ["tmux", "kill-session", "-t", session],
            capture_output=True,
        )

    # ----------------------------------------------------------------------- #
    # Claude command construction
    # ----------------------------------------------------------------------- #

    def _build_claude_command(self, prd_id: str, dot_path: str) -> str:
        """Build the Claude Code launch command with Guardian-specific env vars.

        Environment variables injected:
        - CLAUDE_SESSION_ID: Unique session identifier for tracing
        - PRD_ID: Initiative identifier for signal file naming
        - PIPELINE_DOT_PATH: Absolute path to the DOT pipeline file

        The Guardian does NOT get:
        - CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: Guardian does not spawn teams
        - CLAUDE_CODE_TASK_LIST_ID: Guardian does not use task lists
        """
        timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

        env_vars = " ".join([
            f"CLAUDE_SESSION_ID=guardian-{shlex.quote(prd_id.lower())}-{timestamp}",
            f"PRD_ID={shlex.quote(prd_id)}",
            f"PIPELINE_DOT_PATH={shlex.quote(dot_path)}",
        ])

        return (
            f"unset CLAUDECODE && env {env_vars} "
            f"claude --model claude-sonnet-4-6"
            f" --dangerously-skip-permissions"
        )

    # ----------------------------------------------------------------------- #
    # Scoped prompt construction
    # ----------------------------------------------------------------------- #

    def _build_scoped_prompt(
        self,
        prd_id: str,
        dot_path: str,
        target_repo: str,
        prd_path: Optional[str],
        sd_paths: list[str],
        worktree_path: Optional[str],
    ) -> str:
        """Build the scoped prompt injected into the Guardian session.

        This prompt is the CONTRACT between the web server and the Guardian.
        It explicitly lists what the Guardian CAN and CANNOT do.
        """
        sd_list = "\n".join(f"  - {p}" for p in sd_paths) if sd_paths else "  (none yet -- SDs not written)"
        prd_ref = prd_path or "(PRD path will be provided after PRD writing phase)"
        wt_ref = worktree_path or f"{target_repo}/.claude/worktrees/{prd_id.lower()}/"

        return f"""You are the Guardian for initiative {prd_id}.

## Your Initiative Context

- **PRD**: {prd_ref}
- **Solution Designs**:
{sd_list}
- **Pipeline DOT**: {dot_path}
- **Target Repository**: {target_repo}
- **Worktree**: {wt_ref}

## Your Role (STRICT SCOPE)

You are the independent validation agent for this initiative. Your job has three phases:

### Phase 1: Acceptance Tests
Write blind Gherkin acceptance tests from the PRD. Store them in:
  acceptance-tests/{prd_id}/
These tests are YOUR rubric. Implementation workers never see them.

### Phase 2: Monitor
Watch the pipeline DOT file for node status changes. When workers complete nodes (status transitions to impl_complete), note what was done. Do NOT intervene in worker execution.

### Phase 3: Validate
When the pipeline reaches validation gates (wait.cobuilder nodes), independently validate:
1. Read the actual code in the worktree (not self-reported summaries).
2. Run your blind Gherkin acceptance tests against the implementation.
3. Score each criterion with gradient confidence (0.0-1.0).
4. Write your verdict as a signal file.

## What You CANNOT Do (HARD CONSTRAINTS)

- DO NOT create or modify PRDs. The web server creates PRDs via content workers.
- DO NOT create or modify Solution Designs. The web server manages SD writing and research/refine.
- DO NOT create or modify the pipeline DOT file. The web server and pipeline_runner.py own graph state.
- DO NOT launch pipeline_runner.py. The web server manages process lifecycle.
- DO NOT spawn orchestrators or workers. The pipeline_runner.py dispatches via AgentSDK.
- DO NOT modify files in the worktree (except acceptance-tests/ in the config repo).

## What You CAN Do

- READ any file in the target repo worktree (for independent validation).
- READ the pipeline DOT file (for monitoring progress).
- WRITE acceptance tests in acceptance-tests/{prd_id}/ (config repo only).
- WRITE signal files when you complete validation (signal protocol).
- USE Hindsight for memory (bank_id: system3-orchestrator for private, $CLAUDE_PROJECT_BANK for project).
- USE Skill("s3-guardian") for your workflow patterns.
- USE Skill("acceptance-test-writer") for Gherkin test generation.
- USE Skill("acceptance-test-runner") for running tests against implementations.

## Getting Started

1. Invoke Skill("s3-guardian") to load your workflow patterns.
2. If the PRD exists, begin Phase 1: read the PRD and write blind acceptance tests.
3. If the pipeline is already running, begin Phase 2: monitor node status changes.
4. When validation gates activate, execute Phase 3."""

    # ----------------------------------------------------------------------- #
    # JSON serialization helper (for router layer)
    # ----------------------------------------------------------------------- #

    @staticmethod
    def session_to_dict(session: GuardianSession) -> dict:
        """Serialize a GuardianSession to a JSON-compatible dict."""
        return {
            "session_name": session.session_name,
            "prd_id": session.prd_id,
            "created_at": session.created_at,
            "attached": session.attached,
            "window_count": session.window_count,
        }
```

### 2.2 Integration Points

```
                         CoBuilder Web Server
                               |
              +----------------+------------------+
              |                |                  |
     guardians.py         pipeline_launcher.py    initiatives.py
     (FastAPI router)     (subprocess mgmt)       (DOT lifecycle)
              |                |
              v                v
     GuardianLauncher     PipelineLauncher
              |                |
              v                v
        tmux sessions    pipeline_runner.py
        (Claude Code)    (subprocess)
```

The `guardians.py` router calls `GuardianLauncher` methods, wrapping the synchronous subprocess calls in `asyncio.run_in_executor()` to avoid blocking the FastAPI event loop:

```python
# cobuilder/web/api/routers/guardians.py (relevant integration snippet)

from fastapi import APIRouter, HTTPException
from ..infra.guardian_launcher import GuardianLauncher

router = APIRouter(prefix="/api/guardians", tags=["guardians"])
launcher = GuardianLauncher()

@router.post("/{prd_id}/launch")
async def launch_guardian(prd_id: str, body: LaunchRequest):
    import asyncio
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: launcher.launch(
            prd_id=prd_id,
            dot_path=body.dot_path,
            target_repo=body.target_repo,
            prd_path=body.prd_path,
            sd_paths=body.sd_paths,
            worktree_path=body.worktree_path,
        )
    )
    if result.status == "error":
        raise HTTPException(status_code=500, detail=result.message)
    return result

@router.get("/{prd_id}/attach")
async def get_attach_info(prd_id: str):
    session = launcher.attach(prd_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active Guardian for this initiative")
    return {
        "session_name": session,
        "tmux_attach_cmd": f"tmux attach -t {session}",
        "macos_deep_link": f"open -a Terminal && tmux attach -t {session}",
    }

@router.get("/")
async def list_guardians():
    sessions = launcher.list_active()
    return [GuardianLauncher.session_to_dict(s) for s in sessions]
```

### 2.3 Lifecycle Triggers

The web server launches and interacts with Guardians at specific initiative lifecycle points:

| Trigger | When | Action |
|---------|------|--------|
| Initiative creation | After `POST /api/initiatives` creates skeleton DOT | Optionally launch Guardian early (if PRD already exists externally) |
| PRD approved | After `review_prd` wait.human transitions to validated | Launch Guardian with `prd_path` so it can begin writing acceptance tests |
| SDs approved | After `review_sds` wait.human transitions to validated | Update Guardian context (send SD paths via tmux) |
| Pipeline complete | After `pipeline.completed` event from runner | Guardian enters Phase 3 (validation) -- no action needed from launcher; Guardian monitors DOT |
| Initiative closed | After `done` node transitions to validated | `kill(prd_id)` to clean up the tmux session |

The most common launch point is **PRD approved**: the Guardian cannot write meaningful acceptance tests until the PRD is finalized.

## 3. Scoped Prompt Template

The full scoped prompt is constructed by `_build_scoped_prompt()` (shown in Section 2.1). The key design principles:

### 3.1 Explicit Scope Boundaries

The prompt uses two clearly separated sections:

- **"What You CANNOT Do (HARD CONSTRAINTS)"** -- 6 prohibitions that prevent the Guardian from overstepping into web server or runner territory.
- **"What You CAN Do"** -- 7 capabilities that give the Guardian clear operational boundaries.

This dual-section approach was chosen over a single "allowed actions" list because LLMs respond better to explicit prohibitions. The existing s3-guardian SKILL.md already defines the Guardian's validation workflow; the scoped prompt constrains it to a single initiative.

### 3.2 Context Injection

The prompt includes all file paths the Guardian needs to do its job:

| Context Item | Source | Example |
|-------------|--------|---------|
| PRD path | DOT graph `output_path` attr on `write_prd` node | `docs/prds/dashboard-audit-trail/PRD-DASHBOARD-AUDIT-001.md` |
| SD paths | DOT graph `output_path` attrs on `write_sd_*` nodes | List of SD file paths |
| DOT path | `dot_path` argument | `.pipelines/pipelines/prd-dashboard-audit-001.dot` |
| Target repo | `target_repo` argument | `/Users/theb/Documents/Windsurf/zenagent2` |
| Worktree | DOT graph `worktree_path` attr or derived from PRD ID | `{target_repo}/.claude/worktrees/prd-dashboard-audit-001/` |

### 3.3 Skill Invocation Hints

The prompt tells the Guardian which skills to invoke and in what order. This is necessary because the system3-meta-orchestrator output style provides generic Guardian guidance, but the scoped prompt must direct the Guardian to the correct skill for this specific initiative.

## 4. tmux Integration Details

### 4.1 Session Creation Commands

The exact tmux command sequence (mirrors `spawn_orchestrator.py` patterns):

```bash
# Step 1: Create detached tmux session
tmux new-session -d -s guardian-prd-dashboard-audit-001 \
    -c /Users/theb/Documents/Windsurf/zenagent2 \
    -x 220 -y 50 \
    "exec zsh"

# Step 2: (wait 2s for shell init)

# Step 3: Launch Claude Code with environment
tmux send-keys -t guardian-prd-dashboard-audit-001 \
    "unset CLAUDECODE && env CLAUDE_SESSION_ID=guardian-prd-dashboard-audit-001-20260312T143022Z PRD_ID=PRD-DASHBOARD-AUDIT-001 PIPELINE_DOT_PATH=/path/to/pipeline.dot claude --model claude-sonnet-4-6 --dangerously-skip-permissions"
# (wait 2s)
tmux send-keys -t guardian-prd-dashboard-audit-001 Enter
# (wait 8s for Claude boot)

# Step 4: Set output style
tmux send-keys -t guardian-prd-dashboard-audit-001 \
    "/output-style system3-meta-orchestrator"
# (wait 3s)
tmux send-keys -t guardian-prd-dashboard-audit-001 Enter
# (wait 5s for output style to take effect)

# Step 5: Send scoped prompt
tmux send-keys -t guardian-prd-dashboard-audit-001 \
    "You are the Guardian for initiative PRD-DASHBOARD-AUDIT-001. ..."
# (wait 2s)
tmux send-keys -t guardian-prd-dashboard-audit-001 Enter
```

### 4.2 Critical tmux Patterns (from MEMORY.md)

These patterns are battle-tested and MUST be followed exactly:

| Pattern | Requirement | Reason |
|---------|-------------|--------|
| `exec zsh` | Shell command in session creation | Ensures clean shell; CLAUDECODE env var can be unset |
| `unset CLAUDECODE` | Before launching `claude` | Prevents nested-session detection error |
| Separate `send-keys` for text and Enter | Two subprocess calls with pause between | Large pastes need render time; combined calls truncate |
| `/output-style` as text command | NOT as `--output-style` CLI flag | CLI flag applies output style before session hooks; slash command applies after |
| Sleep timings | 2s shell, 8s Claude, 3s+5s output-style, 2s prompt | Validated through production usage in spawn_orchestrator.py |

### 4.3 Environment Variable Injection

The Guardian receives three environment variables via the `env` command prefix:

| Variable | Format | Purpose |
|----------|--------|---------|
| `CLAUDE_SESSION_ID` | `guardian-{prd-id-lowercase}-{timestamp}` | Unique session identifier for Logfire tracing and Hindsight memory scoping |
| `PRD_ID` | `PRD-DASHBOARD-AUDIT-001` | Initiative identifier; used by hooks and signal protocol |
| `PIPELINE_DOT_PATH` | Absolute path | Allows Guardian to monitor pipeline state without needing to discover the DOT file |

The Guardian intentionally does NOT receive:
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`: Guardian does not spawn native teams.
- `CLAUDE_CODE_TASK_LIST_ID`: Guardian does not use shared task lists.
- `CLAUDE_CODE_ENABLE_TASKS`: Guardian tracks its own work via acceptance tests, not task items.

### 4.4 Attachment and Deep-Linking

The `attach()` method returns a session name that the web UI uses to construct terminal commands:

```
# Direct terminal (user runs in their terminal)
tmux attach -t guardian-prd-dashboard-audit-001

# macOS deep-link (web UI opens Terminal.app)
open -a Terminal && sleep 0.5 && tmux attach -t guardian-prd-dashboard-audit-001

# iTerm2 deep-link (if available)
osascript -e 'tell application "iTerm2" to create window with default profile command "tmux attach -t guardian-prd-dashboard-audit-001"'
```

The web UI renders the session name prominently so the user can also copy-paste the `tmux attach` command manually.

### 4.5 Session Discovery

`list_active()` uses `tmux list-sessions` with custom format strings to efficiently query all Guardian sessions without parsing tmux's default output:

```bash
tmux list-sessions -F "#{session_name}\t#{session_created}\t#{session_attached}\t#{session_windows}"
```

Filtering by `SESSION_PREFIX` ("guardian-") isolates Guardian sessions from orchestrator sessions (prefixed "orch-") and other tmux sessions.

## 5. Files Changed

### New Files

| File | Description | LOC (est.) |
|------|-------------|------------|
| `cobuilder/web/api/infra/guardian_launcher.py` | `GuardianLauncher` class with launch/attach/list/kill | ~350 |
| `cobuilder/web/api/infra/__init__.py` | Package init (if not already created by earlier epics) | ~5 |

### Modified Files

| File | Change |
|------|--------|
| `cobuilder/web/api/routers/guardians.py` | Import and use `GuardianLauncher` (router is new in E5 scope but listed in PRD Section 7) |

### Unchanged Files (Read-Only Dependencies)

| File | Integration |
|------|------------|
| `cobuilder/orchestration/spawn_orchestrator.py` | Reference for tmux patterns only -- NOT imported or called. `GuardianLauncher` reimplements the tmux primitives because the Guardian has different env vars, output style, and no identity/hook registration. |
| `.claude/output-styles/system3-meta-orchestrator.md` | Loaded automatically by Claude Code when `/output-style system3-meta-orchestrator` is sent |
| `.claude/skills/s3-guardian/SKILL.md` | Invoked by the Guardian via `Skill("s3-guardian")` after receiving the scoped prompt |

## 6. Implementation Priority

E5 (Guardian Launcher) has the following dependencies and dependents:

```
E0 (Worktree) ──┐
E1 (DOT Graph) ─┼──> E5 (Guardian Launcher) ──> E6 (Pipeline Launcher)
E2 (Web Server) ┘                                       |
                                                         v
                                                    E7+ (Frontend)
```

- **Depends on**: E0 (worktree paths to inject into prompt), E1 (DOT graph paths and phase detection), E2 (FastAPI app to mount the router).
- **Depended on by**: E6 (pipeline launcher triggers Guardian validation after pipeline completion), E7 ("Open Guardian" button in frontend).
- **Can be developed in parallel with**: E3 (SSE bridge), E4 (content workers) -- no code overlap.

**Recommended implementation order within E5**:
1. `_create_tmux_session`, `_tmux_send`, `_session_exists`, `_kill_session` (tmux primitives)
2. `_build_claude_command` (environment injection)
3. `_build_scoped_prompt` (prompt template)
4. `launch()` (orchestrates the above)
5. `attach()`, `list_active()`, `is_alive()`, `kill()` (query methods)
6. `guardians.py` router integration

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-E5.1 | `launch()` creates a tmux session named `guardian-{prd-id-lowercase}` in the target repo directory | `tmux has-session -t guardian-prd-test-001` returns 0 |
| AC-E5.2 | Guardian receives `CLAUDE_SESSION_ID`, `PRD_ID`, and `PIPELINE_DOT_PATH` environment variables | `tmux capture-pane` shows env vars in Claude startup |
| AC-E5.3 | Guardian's output style is `system3-meta-orchestrator` | `tmux capture-pane` shows System 3 Meta-Orchestrator behavior |
| AC-E5.4 | Scoped prompt includes PRD path, SD paths, DOT path, worktree path, and explicit CAN/CANNOT constraints | Inspect prompt text via `tmux capture-pane` after launch |
| AC-E5.5 | `launch()` with an already-running session returns `status="already_running"` without creating a duplicate | Call `launch()` twice with same PRD ID; second returns "already_running" |
| AC-E5.6 | `attach()` returns the session name for an active Guardian, `None` for inactive | Call `attach()` before and after `launch()` |
| AC-E5.7 | `list_active()` returns all running Guardian sessions with correct PRD associations | Launch 2 Guardians, verify `list_active()` returns both with correct PRD IDs |
| AC-E5.8 | `kill()` terminates the tmux session | `tmux has-session` returns non-zero after `kill()` |
| AC-E5.9 | Guardian scoped prompt prohibits PRD/SD/pipeline creation and runner launch | Manual review: send Guardian a task that would violate constraints; verify it refuses |
| AC-E5.10 | Session name uses lowercase PRD ID with `guardian-` prefix | `guardian-prd-dashboard-audit-001` for input `PRD-DASHBOARD-AUDIT-001` |
| AC-E5.11 | Web server can restart and rediscover active Guardians via `list_active()` | Kill and restart FastAPI; call `list_active()`; verify previously launched sessions appear |
| AC-E5.12 | `guardians.py` router exposes `POST /launch`, `GET /attach`, `GET /list` endpoints | `curl` or test client hits all three endpoints |

## 8. Risks and Mitigations

### R1: tmux Session Zombies

**Risk**: If the web server crashes after creating a tmux session but before recording it, the Guardian runs indefinitely with no management.

**Likelihood**: Medium. Web server crashes are expected during development.

**Mitigation**: `list_active()` discovers sessions purely from tmux (no database needed). The web server rediscovers all Guardians on restart. Additionally, the `guardian-` prefix namespace prevents collision with manually created tmux sessions.

**Future enhancement**: A periodic cleanup task that kills Guardian sessions whose initiative DOT file shows `done` status.

### R2: Prompt Injection via tmux send-keys

**Risk**: If `prd_id` or file paths contain tmux escape sequences or shell metacharacters, `tmux send-keys` could execute unintended commands.

**Likelihood**: Low. PRD IDs follow a controlled naming convention (`PRD-CATEGORY-NNN`). File paths are generated by the web server, not user input.

**Mitigation**: All dynamic values are passed through `shlex.quote()` in `_build_claude_command()`. The scoped prompt is sent as a single text block to `tmux send-keys` (not interpreted by the shell). PRD ID validation can be added at the router layer to reject IDs with special characters.

### R3: Session Name Collisions

**Risk**: Two initiatives with the same PRD ID would map to the same tmux session name.

**Likelihood**: Very low. PRD IDs are unique by convention and enforced by the `InitiativeManager` in E1.

**Mitigation**: `launch()` checks `_session_exists()` before creating and returns `already_running` if a collision occurs. The `InitiativeManager.create()` (E1) enforces PRD ID uniqueness at the DOT graph level.

### R4: Claude Boot Timing

**Risk**: The 8-second pause for Claude Code boot may be insufficient on slower machines, causing the `/output-style` command to be sent before Claude is ready.

**Likelihood**: Low on the target development machine. Higher on resource-constrained environments.

**Mitigation**: The timing constants are class attributes (`CLAUDE_BOOT_PAUSE = 8.0`) and can be overridden per environment. Future enhancement: poll `tmux capture-pane` for the Claude Code prompt indicator before proceeding.

### R5: Output Style Not Applied

**Risk**: If `/output-style system3-meta-orchestrator` fails silently (e.g., output style file missing), the Guardian runs without the System 3 behavior, potentially violating scope constraints.

**Likelihood**: Low. The output style file is part of this repository and is always present.

**Mitigation**: The scoped prompt contains the explicit CAN/CANNOT constraints independently of the output style. Even if the output style fails to load, the prompt-level constraints remain active. The output style adds depth (Hindsight integration, disposition guidance) but the core scope boundaries are prompt-enforced.

### R6: Guardian Runs Without --chrome Flag

**Risk**: The Guardian command does not include `--chrome` (unlike spawn_orchestrator.py for orchestrators). If Chrome DevTools integration is needed for the Guardian's validation workflow, it would be unavailable.

**Likelihood**: Low. The Guardian validates by reading code and running acceptance tests, not by interacting with a browser.

**Mitigation**: The `--chrome` flag can be added to `_build_claude_command()` if browser-based validation becomes a Guardian requirement. Currently omitted to reduce resource usage (Chrome DevTools protocol connection).
