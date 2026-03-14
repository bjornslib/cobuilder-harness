---
title: "SD-COBUILDER-WEB-001 Epic 6: Pipeline Launcher + Monitor"
status: active
type: solution-design
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E6
---

# SD-COBUILDER-WEB-001 Epic 6: Pipeline Launcher + Monitor

## 1. Problem Statement

The CoBuilder web server (FastAPI) must manage the lifecycle of `pipeline_runner.py` as a subprocess. Today, pipeline execution requires manually running `python3 pipeline_runner.py --dot-file <path>` in a terminal and visually monitoring its output. There is no programmatic way to:

1. **Launch** the runner from a web request and track its PID.
2. **Monitor health** -- detect crashes, hangs, or abnormal exits without watching stdout.
3. **Detect state transitions** -- know when a `pipeline.completed`, `pipeline.failed`, or `node.failed` event fires without tailing the terminal.
4. **Detect `wait.human` gates** -- the runner writes `.gate-wait` marker files to the signal directory, but nothing in the web layer watches for them.
5. **Recover from crashes** -- if the runner process dies (OOM, unhandled exception, SIGKILL), no mechanism restarts it with `--resume` to continue from the last checkpoint.
6. **Gracefully stop** -- there is no API to send SIGTERM to the runner and confirm it has exited.

The `PipelineLauncher` fills this gap: a single class that the web server's route handlers call to start, monitor, and stop pipeline runs. It exposes an async interface that fits naturally into FastAPI's event loop and produces typed status events that the SSE bridge (Epic 3) can forward to the frontend.

### Why asyncio subprocess (not threading)

The web server is an asyncio application (FastAPI + uvicorn). The launcher must not block the event loop. `asyncio.create_subprocess_exec` provides non-blocking process creation, stdout/stderr streaming, and wait semantics -- all without spawning OS threads. The existing `pipeline_runner.py` itself uses threads internally (ThreadPoolExecutor for AgentSDK dispatch, watchdog observers), but those are isolated inside the runner subprocess and invisible to the web server process.

---

## 2. Technical Architecture

### 2.1 Module Location

```
cobuilder/web/api/infra/pipeline_launcher.py
```

### 2.2 Class Diagram

```
PipelineLauncher
  |
  +-- _runs: dict[str, PipelineRun]          # initiative_id -> active run
  +-- _event_callbacks: list[Callable]        # SSE bridge subscribers
  |
  +-- launch(initiative_id, dot_path, worktree_path) -> PipelineRun
  +-- stop(initiative_id, timeout_s=15) -> StopResult
  +-- get_status(initiative_id) -> RunStatus | None
  +-- on_event(callback: Callable[[LauncherEvent], Awaitable[None]])
  |
  +-- _monitor_process(run: PipelineRun) [background task]
  +-- _tail_jsonl(run: PipelineRun) [background task]
  +-- _scan_gate_markers(run: PipelineRun) [background task]
  +-- _restart_on_crash(run: PipelineRun) [internal]

PipelineRun
  +-- initiative_id: str
  +-- dot_path: Path
  +-- worktree_path: Path
  +-- process: asyncio.subprocess.Process | None
  +-- pid: int | None
  +-- status: RunStatus
  +-- started_at: datetime
  +-- restart_count: int
  +-- jsonl_path: Path
  +-- signal_dir: Path
  +-- _monitor_task: asyncio.Task | None
  +-- _jsonl_task: asyncio.Task | None
  +-- _gate_task: asyncio.Task | None
```

### 2.3 Data Types

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable
import asyncio


class RunStatus(Enum):
    """Lifecycle states for a managed pipeline run."""
    STARTING = "starting"       # launch() called, process not yet confirmed alive
    RUNNING = "running"         # process alive, health checks passing
    GATE_WAITING = "gate_waiting"  # runner paused at wait.human or wait.system3
    STOPPING = "stopping"       # SIGTERM sent, waiting for graceful exit
    CRASHED = "crashed"         # process exited unexpectedly, restart pending
    RESTARTING = "restarting"   # restart in progress
    COMPLETED = "completed"     # pipeline.completed event received, process exited 0
    FAILED = "failed"           # pipeline.failed event received, or max restarts exhausted
    STOPPED = "stopped"         # stop() completed successfully


@dataclass
class PipelineRun:
    """Tracks one managed pipeline_runner.py subprocess."""
    initiative_id: str
    dot_path: Path
    worktree_path: Path
    process: asyncio.subprocess.Process | None = None
    pid: int | None = None
    status: RunStatus = RunStatus.STARTING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    restart_count: int = 0
    last_exit_code: int | None = None
    last_crash_at: datetime | None = None
    active_gate: str | None = None       # node_id of current wait.human gate
    active_gate_type: str | None = None  # "wait.human" or "wait.system3"

    _monitor_task: asyncio.Task | None = field(default=None, repr=False)
    _jsonl_task: asyncio.Task | None = field(default=None, repr=False)
    _gate_task: asyncio.Task | None = field(default=None, repr=False)

    @property
    def jsonl_path(self) -> Path:
        """JSONL event log path. Matches the runner's convention."""
        pipeline_id = self.dot_path.stem
        run_dir = self.dot_path.parent / "runs" / pipeline_id
        return run_dir / "pipeline-events.jsonl"

    @property
    def signal_dir(self) -> Path:
        """Signal file directory. Matches PipelineRunner.signal_dir convention."""
        pipeline_id = self.dot_path.stem
        return self.dot_path.parent / "signals" / pipeline_id


class LauncherEventType(Enum):
    """Events emitted by PipelineLauncher to subscribers (SSE bridge)."""
    PROCESS_STARTED = "launcher.process_started"
    PROCESS_CRASHED = "launcher.process_crashed"
    PROCESS_RESTARTING = "launcher.process_restarting"
    PROCESS_STOPPED = "launcher.process_stopped"
    PIPELINE_COMPLETED = "launcher.pipeline_completed"
    PIPELINE_FAILED = "launcher.pipeline_failed"
    GATE_ACTIVATED = "launcher.gate_activated"
    GATE_RESOLVED = "launcher.gate_resolved"
    HEALTH_CHECK_FAILED = "launcher.health_check_failed"


@dataclass(frozen=True)
class LauncherEvent:
    """Typed event emitted to subscribers."""
    type: LauncherEventType
    initiative_id: str
    timestamp: datetime
    data: dict[str, Any]
```

### 2.4 Configuration Constants

```python
# Maximum automatic restarts before marking as FAILED
MAX_RESTART_ATTEMPTS: int = 3

# Seconds between health checks (process alive + responsive)
HEALTH_CHECK_INTERVAL_S: float = 5.0

# Seconds between gate-marker directory scans
GATE_SCAN_INTERVAL_S: float = 2.0

# JSONL tail poll interval (used when inotify/kqueue is not available)
JSONL_POLL_INTERVAL_S: float = 1.0

# Grace period after SIGTERM before SIGKILL
SIGTERM_TIMEOUT_S: float = 15.0

# Backoff between restart attempts: base * 2^attempt (capped)
RESTART_BACKOFF_BASE_S: float = 2.0
RESTART_BACKOFF_MAX_S: float = 30.0
```

---

## 3. Event Monitoring

### 3.1 JSONL Tail Logic

The pipeline runner writes events to a JSONL file via `JSONLEmitter` at `{dot_dir}/runs/{pipeline_id}/pipeline-events.jsonl`. Each line is a serialized `PipelineEvent` (14 defined types in `cobuilder/engine/events/types.py`). The launcher tails this file to detect terminal and gate-related events without coupling to the runner's internal state.

```python
async def _tail_jsonl(self, run: PipelineRun) -> None:
    """Continuously tail the JSONL event log for state-changing events.

    Opens the file and seeks to the end (skip replay -- that is the SSE
    bridge's job). Then reads new lines as they appear, parsing each as
    a PipelineEvent dict.

    Terminal events:
        pipeline.completed  -> mark run COMPLETED, cancel monitor tasks
        pipeline.failed     -> mark run FAILED, cancel monitor tasks

    Alertable events:
        node.failed         -> emit PIPELINE_FAILED if goal_gate=true
        node.completed      -> informational (forwarded to SSE bridge)

    The tail loop exits when:
        1. A terminal event is detected, OR
        2. The run's status transitions to STOPPING/STOPPED, OR
        3. The process exits AND no new lines appear for 5s (drain window).
    """
    jsonl_path = run.jsonl_path

    # Wait for file to exist (runner creates it on startup)
    for _ in range(30):  # max 30s wait
        if jsonl_path.exists():
            break
        await asyncio.sleep(1.0)
    else:
        await self._emit(LauncherEvent(
            type=LauncherEventType.HEALTH_CHECK_FAILED,
            initiative_id=run.initiative_id,
            timestamp=datetime.now(timezone.utc),
            data={"reason": "JSONL file not created within 30s",
                  "path": str(jsonl_path)},
        ))
        return

    async with aiofiles.open(jsonl_path, mode="r") as f:
        # Seek to end -- we only want new events from this launch
        await f.seek(0, 2)

        drain_deadline: float | None = None

        while run.status not in (RunStatus.STOPPING, RunStatus.STOPPED,
                                  RunStatus.COMPLETED, RunStatus.FAILED):
            line = await f.readline()

            if not line:
                # No new data -- check if process is still alive
                if run.process and run.process.returncode is not None:
                    # Process exited; drain remaining lines for 5s
                    if drain_deadline is None:
                        drain_deadline = asyncio.get_event_loop().time() + 5.0
                    elif asyncio.get_event_loop().time() > drain_deadline:
                        break
                await asyncio.sleep(JSONL_POLL_INTERVAL_S)
                continue

            drain_deadline = None  # reset drain timer on each line read
            line = line.strip()
            if not line:
                continue

            try:
                event_dict = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event_dict.get("type", "")

            if event_type == "pipeline.completed":
                run.status = RunStatus.COMPLETED
                await self._emit(LauncherEvent(
                    type=LauncherEventType.PIPELINE_COMPLETED,
                    initiative_id=run.initiative_id,
                    timestamp=datetime.now(timezone.utc),
                    data=event_dict.get("data", {}),
                ))
                break

            elif event_type == "pipeline.failed":
                run.status = RunStatus.FAILED
                await self._emit(LauncherEvent(
                    type=LauncherEventType.PIPELINE_FAILED,
                    initiative_id=run.initiative_id,
                    timestamp=datetime.now(timezone.utc),
                    data=event_dict.get("data", {}),
                ))
                break

            elif event_type == "node.failed":
                # Forward to subscribers but do not terminate --
                # individual node failures may be retried by the runner
                pass

            # Forward all events to subscribers for SSE bridge
            for callback in self._event_callbacks:
                try:
                    await callback(event_dict)
                except Exception:
                    pass  # SSE bridge errors must not crash the tail loop
```

**Key design decisions:**

- **Seek to end on open**: The launcher only cares about events from THIS launch. Historical replay is the SSE bridge's concern (Epic 3).
- **Drain window**: After the process exits, continue reading for 5 seconds to capture any buffered writes that were flushed by `JSONLEmitter` before the process terminated.
- **aiofiles**: Standard `open()` would block the event loop on readline. `aiofiles` wraps file I/O in a thread pool transparently. Alternative: `asyncio.to_thread(f.readline)` with a regular file handle.

### 3.2 Gate Detection

The runner writes `.gate-wait` marker files when it encounters `wait.human` or `wait.system3` nodes. Both `_handle_gate` and `_handle_human` in `pipeline_runner.py` write markers to:

```
{dot_dir}/signals/{pipeline_id}/{node_id}.gate-wait
```

Each marker contains:
```json
{
    "node_id": "review_prd",
    "gate_type": "wait.human",
    "summary_ref": "",
    "mode": "technical",
    "epic_id": "E1",
    "timestamp": "2026-03-12T10:30:00+00:00"
}
```

The launcher scans for these markers on a 2-second interval:

```python
async def _scan_gate_markers(self, run: PipelineRun) -> None:
    """Poll signal_dir for .gate-wait marker files.

    When a new marker appears:
        1. Parse the JSON to extract gate_type and node_id
        2. Update run.active_gate and run.active_gate_type
        3. Transition run.status to GATE_WAITING
        4. Emit GATE_ACTIVATED event (picked up by SSE bridge -> frontend badge)

    When a marker disappears (runner consumed it after signal file written):
        1. Clear run.active_gate
        2. Transition run.status back to RUNNING
        3. Emit GATE_RESOLVED event
    """
    known_gates: set[str] = set()  # filenames currently tracked

    while run.status not in (RunStatus.STOPPING, RunStatus.STOPPED,
                              RunStatus.COMPLETED, RunStatus.FAILED):
        await asyncio.sleep(GATE_SCAN_INTERVAL_S)

        signal_dir = run.signal_dir
        if not signal_dir.exists():
            continue

        current_markers: dict[str, dict] = {}
        for entry in signal_dir.iterdir():
            if entry.suffix == ".gate-wait" and entry.is_file():
                try:
                    marker = json.loads(entry.read_text())
                    current_markers[entry.name] = marker
                except (json.JSONDecodeError, OSError):
                    continue

        current_names = set(current_markers.keys())

        # New gates
        for name in current_names - known_gates:
            marker = current_markers[name]
            node_id = marker.get("node_id", name.replace(".gate-wait", ""))
            gate_type = marker.get("gate_type", "unknown")
            run.active_gate = node_id
            run.active_gate_type = gate_type
            run.status = RunStatus.GATE_WAITING
            await self._emit(LauncherEvent(
                type=LauncherEventType.GATE_ACTIVATED,
                initiative_id=run.initiative_id,
                timestamp=datetime.now(timezone.utc),
                data={
                    "node_id": node_id,
                    "gate_type": gate_type,
                    "marker_path": str(signal_dir / name),
                    **marker,
                },
            ))

        # Resolved gates
        for name in known_gates - current_names:
            run.active_gate = None
            run.active_gate_type = None
            if run.status == RunStatus.GATE_WAITING:
                run.status = RunStatus.RUNNING
            await self._emit(LauncherEvent(
                type=LauncherEventType.GATE_RESOLVED,
                initiative_id=run.initiative_id,
                timestamp=datetime.now(timezone.utc),
                data={"resolved_marker": name},
            ))

        known_gates = current_names
```

**Why polling instead of watchdog**: The runner already uses watchdog internally for its own signal directory. Having two watchdog observers on the same directory from different processes risks event ordering issues. A 2-second poll from the web server is sufficient for the UI's "<2s notification" acceptance criterion and avoids cross-process inotify/kqueue contention.

---

## 4. Crash Recovery

### 4.1 Crash Detection

The `_monitor_process` background task awaits the subprocess exit and inspects the return code:

```python
async def _monitor_process(self, run: PipelineRun) -> None:
    """Await process exit and handle crash vs clean termination.

    Exit codes:
        0   -> clean exit (pipeline.completed should have been emitted)
        1   -> pipeline.failed (runner exits 1 on failure)
        -N  -> killed by signal N (e.g., -9 = SIGKILL, -15 = SIGTERM)
        >1  -> unexpected crash (Python traceback, OOM killer, etc.)
    """
    assert run.process is not None
    return_code = await run.process.wait()
    run.last_exit_code = return_code
    run.pid = None

    if run.status in (RunStatus.STOPPING, RunStatus.STOPPED):
        # Intentional stop -- do not restart
        run.status = RunStatus.STOPPED
        await self._emit(LauncherEvent(
            type=LauncherEventType.PROCESS_STOPPED,
            initiative_id=run.initiative_id,
            timestamp=datetime.now(timezone.utc),
            data={"exit_code": return_code},
        ))
        return

    if run.status == RunStatus.COMPLETED:
        # JSONL tail already detected pipeline.completed -- nothing to do
        return

    if return_code == 0 and run.status != RunStatus.COMPLETED:
        # Clean exit but no pipeline.completed event detected by JSONL tail.
        # This can happen if the runner exits before the tail drains.
        # Check JSONL one final time synchronously.
        if await self._check_jsonl_for_completion(run):
            run.status = RunStatus.COMPLETED
            return

    # Unexpected exit -- crash
    run.status = RunStatus.CRASHED
    run.last_crash_at = datetime.now(timezone.utc)
    await self._emit(LauncherEvent(
        type=LauncherEventType.PROCESS_CRASHED,
        initiative_id=run.initiative_id,
        timestamp=datetime.now(timezone.utc),
        data={"exit_code": return_code, "restart_count": run.restart_count},
    ))

    await self._restart_on_crash(run)
```

### 4.2 Restart Strategy

```python
async def _restart_on_crash(self, run: PipelineRun) -> None:
    """Attempt to restart the runner with --resume flag.

    Restart policy:
        - Max MAX_RESTART_ATTEMPTS restarts per initiative
        - Exponential backoff: RESTART_BACKOFF_BASE_S * 2^attempt
          (capped at RESTART_BACKOFF_MAX_S)
        - Runner is relaunched with --resume flag so it does not
          reset active nodes to pending
        - If max restarts exhausted, mark run as FAILED

    State preservation:
        - The DOT file on disk IS the state (node statuses persisted by runner)
        - The JSONL file is opened in append mode -- new events accumulate
        - Signal files remain in the signal directory
        - The only state lost is the runner's in-memory active_workers dict,
          which the runner rebuilds on --resume by re-reading active nodes
    """
    if run.restart_count >= MAX_RESTART_ATTEMPTS:
        run.status = RunStatus.FAILED
        await self._emit(LauncherEvent(
            type=LauncherEventType.PIPELINE_FAILED,
            initiative_id=run.initiative_id,
            timestamp=datetime.now(timezone.utc),
            data={
                "reason": "Max restart attempts exhausted",
                "max_attempts": MAX_RESTART_ATTEMPTS,
                "last_exit_code": run.last_exit_code,
            },
        ))
        return

    backoff = min(
        RESTART_BACKOFF_BASE_S * (2 ** run.restart_count),
        RESTART_BACKOFF_MAX_S,
    )
    run.status = RunStatus.RESTARTING
    run.restart_count += 1

    await self._emit(LauncherEvent(
        type=LauncherEventType.PROCESS_RESTARTING,
        initiative_id=run.initiative_id,
        timestamp=datetime.now(timezone.utc),
        data={
            "attempt": run.restart_count,
            "backoff_s": backoff,
            "max_attempts": MAX_RESTART_ATTEMPTS,
        },
    ))

    await asyncio.sleep(backoff)

    # Re-launch with --resume
    await self._start_process(run, resume=True)
```

### 4.3 The `--resume` Flag and State Preservation

When `pipeline_runner.py` starts with `--resume`, it skips `_reset_active_nodes()` -- the method that would transition all `active` nodes back to `pending`. This means:

- Nodes at `validated` or `impl_complete` stay as-is (no re-work).
- Nodes at `active` (in-flight when crash happened) remain `active`. The runner's orphaned-active-node recovery loop (lines 526-549 of `pipeline_runner.py`) detects these and re-dispatches them with exponential backoff.
- The DOT file on disk contains the last-known state because the runner writes transitions atomically via `apply_transition()`.

The launcher always passes `--resume` on restart. Fresh launches (from `launch()`) do NOT pass `--resume` so that the runner starts clean.

---

## 5. Core Implementation

### 5.1 PipelineLauncher Class

```python
import asyncio
import json
import logging
import os
import signal as signal_mod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

try:
    import aiofiles
    _AIOFILES_AVAILABLE = True
except ImportError:
    _AIOFILES_AVAILABLE = False

logger = logging.getLogger(__name__)


class PipelineLauncher:
    """Manages pipeline_runner.py subprocesses for the web server.

    One PipelineLauncher instance per web server process. Tracks multiple
    concurrent pipeline runs (one per initiative).
    """

    def __init__(self) -> None:
        self._runs: dict[str, PipelineRun] = {}
        self._event_callbacks: list[Callable[[LauncherEvent], Awaitable[None]]] = []

    def on_event(
        self, callback: Callable[[LauncherEvent], Awaitable[None]]
    ) -> None:
        """Register a callback for launcher events (used by SSE bridge)."""
        self._event_callbacks.append(callback)

    async def _emit(self, event: LauncherEvent) -> None:
        """Emit event to all registered callbacks."""
        for cb in self._event_callbacks:
            try:
                await cb(event)
            except Exception as exc:
                logger.warning("Event callback failed: %s", exc)

    async def launch(
        self,
        initiative_id: str,
        dot_path: str | Path,
        worktree_path: str | Path,
    ) -> PipelineRun:
        """Launch pipeline_runner.py for an initiative.

        Args:
            initiative_id: Unique initiative identifier (typically prd_id).
            dot_path: Absolute path to the DOT pipeline file.
            worktree_path: Absolute path to the initiative worktree.

        Returns:
            PipelineRun tracking object.

        Raises:
            ValueError: If a run is already active for this initiative.
            FileNotFoundError: If dot_path does not exist.
        """
        if initiative_id in self._runs:
            existing = self._runs[initiative_id]
            if existing.status in (
                RunStatus.RUNNING,
                RunStatus.STARTING,
                RunStatus.GATE_WAITING,
                RunStatus.RESTARTING,
            ):
                raise ValueError(
                    f"Pipeline already running for initiative "
                    f"{initiative_id} "
                    f"(status={existing.status.value}, pid={existing.pid})"
                )

        dot_path = Path(dot_path).resolve()
        worktree_path = Path(worktree_path).resolve()

        if not dot_path.exists():
            raise FileNotFoundError(f"DOT file not found: {dot_path}")

        run = PipelineRun(
            initiative_id=initiative_id,
            dot_path=dot_path,
            worktree_path=worktree_path,
        )
        self._runs[initiative_id] = run

        await self._start_process(run, resume=False)
        return run

    async def _start_process(
        self, run: PipelineRun, resume: bool
    ) -> None:
        """Start the pipeline_runner.py subprocess and monitoring tasks.

        Constructs the command:
            python3 -m cobuilder.attractor.pipeline_runner
                --dot-file <path> [--resume]

        The subprocess inherits the web server's environment
        (ANTHROPIC_API_KEY, ANTHROPIC_MODEL, etc.). cwd is set to
        worktree_path so that relative paths in the DOT file resolve
        correctly.
        """
        cmd = [
            "python3",
            "-m",
            "cobuilder.attractor.pipeline_runner",
            "--dot-file",
            str(run.dot_path),
        ]
        if resume:
            cmd.append("--resume")

        # Ensure signal directory exists before runner starts
        run.signal_dir.mkdir(parents=True, exist_ok=True)

        # Ensure run directory exists for JSONL output
        run.jsonl_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "[launcher] Starting runner: %s  cwd=%s  resume=%s",
            " ".join(cmd),
            run.worktree_path,
            resume,
        )

        run.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(run.worktree_path),
            # Start in new process group so SIGTERM targets only the runner
            start_new_session=True,
        )
        run.pid = run.process.pid
        run.status = RunStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)

        logger.info(
            "[launcher] Runner started: pid=%d initiative=%s",
            run.pid,
            run.initiative_id,
        )

        await self._emit(
            LauncherEvent(
                type=LauncherEventType.PROCESS_STARTED,
                initiative_id=run.initiative_id,
                timestamp=datetime.now(timezone.utc),
                data={
                    "pid": run.pid,
                    "resume": resume,
                    "dot_path": str(run.dot_path),
                },
            )
        )

        # Launch background monitoring tasks
        run._monitor_task = asyncio.create_task(
            self._monitor_process(run),
            name=f"monitor-{run.initiative_id}",
        )
        run._jsonl_task = asyncio.create_task(
            self._tail_jsonl(run),
            name=f"jsonl-{run.initiative_id}",
        )
        run._gate_task = asyncio.create_task(
            self._scan_gate_markers(run),
            name=f"gates-{run.initiative_id}",
        )

    async def stop(
        self,
        initiative_id: str,
        timeout_s: float = SIGTERM_TIMEOUT_S,
    ) -> RunStatus:
        """Gracefully stop a running pipeline.

        Sends SIGTERM to the runner's process group, waits up to
        timeout_s for clean exit, then sends SIGKILL if still alive.

        Args:
            initiative_id: Initiative to stop.
            timeout_s: Seconds to wait after SIGTERM before SIGKILL.

        Returns:
            Final RunStatus (STOPPED or FAILED).

        Raises:
            KeyError: If no run exists for this initiative.
        """
        if initiative_id not in self._runs:
            raise KeyError(f"No run found for initiative {initiative_id}")

        run = self._runs[initiative_id]

        if run.status in (
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.STOPPED,
        ):
            return run.status

        run.status = RunStatus.STOPPING

        if run.process and run.process.returncode is None:
            logger.info("[launcher] Sending SIGTERM to pid=%d", run.pid)
            try:
                # Send to process group (includes any child processes
                # spawned by the runner's ThreadPoolExecutor)
                os.killpg(os.getpgid(run.process.pid), signal_mod.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass

            try:
                await asyncio.wait_for(
                    run.process.wait(), timeout=timeout_s
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[launcher] Runner did not exit within %ds, "
                    "sending SIGKILL",
                    timeout_s,
                )
                try:
                    os.killpg(
                        os.getpgid(run.process.pid), signal_mod.SIGKILL
                    )
                    await asyncio.wait_for(
                        run.process.wait(), timeout=5.0
                    )
                except (ProcessLookupError, asyncio.TimeoutError):
                    pass

        # Cancel monitoring tasks
        for task in (run._monitor_task, run._jsonl_task, run._gate_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        run.status = RunStatus.STOPPED
        run.pid = None

        await self._emit(
            LauncherEvent(
                type=LauncherEventType.PROCESS_STOPPED,
                initiative_id=run.initiative_id,
                timestamp=datetime.now(timezone.utc),
                data={"exit_code": run.last_exit_code},
            )
        )

        return run.status

    def get_status(self, initiative_id: str) -> RunStatus | None:
        """Return current status for an initiative, or None."""
        run = self._runs.get(initiative_id)
        return run.status if run else None

    def get_run(self, initiative_id: str) -> PipelineRun | None:
        """Return the PipelineRun object for an initiative."""
        return self._runs.get(initiative_id)

    def list_runs(self) -> dict[str, RunStatus]:
        """Return initiative_id -> RunStatus for all tracked runs."""
        return {iid: run.status for iid, run in self._runs.items()}

    async def _check_jsonl_for_completion(
        self, run: PipelineRun
    ) -> bool:
        """One-shot check: does the JSONL contain pipeline.completed?"""
        try:
            text = run.jsonl_path.read_text()
            for line in text.strip().split("\n"):
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                    if evt.get("type") == "pipeline.completed":
                        return True
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        return False
```

### 5.2 Health Check Implementation

The health check runs as part of the monitor task, periodically verifying the subprocess is responsive:

```python
async def _health_check(self, run: PipelineRun) -> bool:
    """Verify the runner subprocess is alive and functional.

    Level 1: Process alive (returncode is None).
    Level 2: PID exists in process table (os.kill(pid, 0)).

    Returns True if healthy, False if degraded.
    """
    if run.process is None or run.process.returncode is not None:
        return False

    # Level 2: kernel-level PID check
    try:
        os.kill(run.process.pid, 0)  # signal 0 = existence check
    except (ProcessLookupError, PermissionError):
        return False

    return True
```

**Why not DOT mtime as a health signal?** The runner may legitimately go quiet for minutes while a worker is executing via AgentSDK. DOT mtime stalling does not imply the runner is hung -- it means a worker is working. The runner's internal `AdvancedWorkerTracker` handles worker timeouts (default 900s). Process-level liveness is the correct health check for the launcher.

---

## 6. Files Changed

### New Files

| File | Purpose |
|------|---------|
| `cobuilder/web/api/infra/pipeline_launcher.py` | `PipelineLauncher` class: subprocess management, JSONL tailing, gate detection, crash recovery |
| `cobuilder/web/api/infra/__init__.py` | Package init (exports `PipelineLauncher`) |

### Modified Files

| File | Change |
|------|--------|
| `cobuilder/web/api/routers/pipelines.py` (Epic 2) | Import and use `PipelineLauncher` for `POST /api/initiatives/{id}/launch` and `DELETE /api/initiatives/{id}/runner` endpoints |
| `cobuilder/web/api/main.py` (Epic 2) | Instantiate `PipelineLauncher` as app-level singleton via `app.state.launcher`; register SSE bridge callback via `launcher.on_event()` at startup |
| `cobuilder/web/api/infra/sse_bridge.py` (Epic 3) | Subscribe to `PipelineLauncher.on_event()` to forward `LauncherEvent` instances as SSE messages |

### Unchanged Files (Integration Points)

| File | How It Integrates |
|------|-------------------|
| `cobuilder/attractor/pipeline_runner.py` | Launched as subprocess; reads `--dot-file` and `--resume` CLI args; writes JSONL events and `.gate-wait` markers |
| `cobuilder/engine/events/jsonl_backend.py` | Writes the JSONL file that `_tail_jsonl()` reads; each line is a serialized `PipelineEvent` |
| `cobuilder/pipeline/signal_protocol.py` | Runner and web server both use `write_signal()` for atomic signal I/O; `.gate-wait` markers follow the same directory |
| `cobuilder/attractor/transition.py` | Runner writes DOT transitions atomically; launcher never writes to DOT directly |
| `cobuilder/engine/events/types.py` | Defines the 14 `EventType` literals that appear in JSONL lines |

---

## 7. Implementation Priority

| Priority | Component | Rationale |
|----------|-----------|-----------|
| P0 | `launch()` + `_start_process()` | Core functionality: start runner subprocess from web API |
| P0 | `_monitor_process()` | Crash detection: cannot recover without detecting exit |
| P0 | `stop()` | Graceful shutdown: prevents zombie processes on web server teardown |
| P1 | `_tail_jsonl()` | State detection: know when pipeline completes or fails without polling DOT |
| P1 | `_restart_on_crash()` | Resilience: auto-recover from transient failures (OOM, rate limit cascade) |
| P2 | `_scan_gate_markers()` | UX: detect `wait.human` gates for the review inbox (Epic 9) |
| P2 | `_health_check()` | Observability: detect degraded processes before they become zombies |
| P3 | `on_event()` + `_emit()` | Integration: SSE bridge subscription (Epic 3 dependency) |

---

## 8. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-1 | `launch()` starts `pipeline_runner.py` as a subprocess and returns a `PipelineRun` with a valid PID | Unit test: mock `asyncio.create_subprocess_exec`, assert PID is set and status is `RUNNING` |
| AC-2 | Runner crash (non-zero exit, SIGKILL) is detected within 5 seconds | Integration test: launch runner on invalid DOT file, assert `CRASHED` status within 5s |
| AC-3 | Auto-restart with `--resume` flag occurs on crash, up to `MAX_RESTART_ATTEMPTS` | Integration test: force-kill runner 4 times, assert 3 restarts then `FAILED` |
| AC-4 | `pipeline.completed` JSONL event transitions run to `COMPLETED` | Integration test: write `{"type":"pipeline.completed",...}` line to JSONL, assert status change |
| AC-5 | `pipeline.failed` JSONL event transitions run to `FAILED` | Integration test: write `{"type":"pipeline.failed",...}` line to JSONL, assert status change |
| AC-6 | `.gate-wait` marker file appearance emits `GATE_ACTIVATED` event within 2 seconds | Integration test: write marker file to signal_dir, assert `LauncherEvent` emitted within 2s |
| AC-7 | `.gate-wait` marker file removal emits `GATE_RESOLVED` event | Integration test: remove marker, assert `GATE_RESOLVED` within next scan cycle |
| AC-8 | `stop()` sends SIGTERM, waits for clean exit, escalates to SIGKILL after timeout | Unit test: mock process that ignores SIGTERM, assert SIGKILL sent after `SIGTERM_TIMEOUT_S` |
| AC-9 | `stop()` preserves DOT file state (worktree not corrupted) | Integration test: stop during active run, verify DOT file is valid and parseable via `parse_file()` |
| AC-10 | Multiple concurrent launches for different initiatives work independently | Unit test: launch two initiatives, stop one, assert the other continues unaffected |

---

## 9. Risks

### R1: Zombie Processes

**Risk**: If the web server crashes without calling `stop()`, the runner subprocess becomes orphaned.

**Mitigation**:
- `start_new_session=True` puts the runner in its own process group. The OS will NOT cascade SIGKILL from the web server to the runner -- this is intentional because the runner should survive web server restarts.
- On web server startup, `PipelineLauncher` should scan for running `pipeline_runner.py` processes (via `psutil` or `/proc`) and re-attach to them. This is a **follow-up enhancement** -- for v1, the web server logs warnings about orphaned PIDs at startup and the operator manually kills them.
- The runner itself is idempotent on `--resume` and does not corrupt state if killed at any point.

### R2: Race Condition Between Restart and Signal Writes

**Risk**: If the runner crashes while a worker is writing its signal file (JSON write-then-rename), the restart might see a partially written `.tmp` file and miss the signal.

**Mitigation**:
- `signal_protocol.write_signal()` uses atomic write-then-rename: `write(tmp) -> fsync -> rename(tmp, final)`. The `.json` file is either fully present or absent -- never partial.
- The runner's signal processing loop (`_process_signals()`) skips `.tmp` files explicitly.
- The restarted runner re-reads all `.json` files in the signal directory, so any signal written before the crash will be processed on resume.

### R3: JSONL Tail Missing Events Near Process Exit

**Risk**: The runner flushes the JSONL file and exits. The tail task may not read the final line(s) before the process exits, leading to a false crash detection.

**Mitigation**:
- The drain window (5 seconds after process exit) continues reading the file to capture late-flushed events.
- `_check_jsonl_for_completion()` is called as a fallback when the process exits with code 0 but the tail did not see `pipeline.completed`.
- `JSONLEmitter` calls `flush()` after every `emit()` (line 69 of `jsonl_backend.py`), so OS-level buffering is not a concern.

### R4: Signal Directory Contention

**Risk**: Both the runner (via watchdog) and the launcher (via polling) read the signal directory simultaneously.

**Mitigation**:
- The launcher reads `.gate-wait` files only (different extension from `.json` signal files).
- The runner's watchdog filters for `.json` files only (`_SignalFileHandler.on_created` checks `endswith(".json")`).
- No write contention exists: the launcher NEVER writes to the signal directory. Signal files for `wait.human` approval are written by the web server's `signals.py` router, which uses `signal_protocol.write_signal()` -- a separate code path.

### R5: Subprocess Environment Leakage

**Risk**: The runner subprocess inherits the web server's full environment, which may include uvicorn-specific variables.

**Mitigation**:
- For v1, environment inheritance is acceptable because the runner and web server share the same Python environment.
- `_start_process()` can optionally pass an explicit `env` dict to `create_subprocess_exec` that filters out web-server-specific variables while preserving `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `ATTRACTOR_SIGNALS_DIR`, etc. This is deferred to v2 unless conflicts are observed.

### R6: Multiple Launches for Same Initiative

**Risk**: A race in the web UI could trigger two `launch()` calls for the same initiative, creating duplicate runner processes that compete for the same DOT file.

**Mitigation**:
- `launch()` checks `self._runs[initiative_id]` and raises `ValueError` if a run is already active (status in `RUNNING`, `STARTING`, `GATE_WAITING`, or `RESTARTING`).
- The web router should also enforce this at the HTTP layer (409 Conflict response).
- Terminal states (`COMPLETED`, `FAILED`, `STOPPED`) allow re-launch, which creates a fresh run.
