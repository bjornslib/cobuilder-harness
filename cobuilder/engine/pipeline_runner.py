#!/usr/bin/env python3
"""Pure Python DOT pipeline runner. Zero LLM tokens for graph traversal.

3-layer hierarchy: System 3 (LLM) -> pipeline_runner.py (Python) -> Workers (AgentSDK)

The runner has ZERO LLM intelligence. It can only:
- Parse DOT files, track node states, find dispatchable nodes
- Launch AgentSDK workers via claude_code_sdk
- Watch signal files via watchdog
- Write checkpoints, transition DOT states mechanically
- Read signal files and apply results without interpretation

Architecture:
    System 3 (Opus)         — strategic planning, blind Gherkin E2E
      |
      pipeline_runner.py    — Python state machine, $0, <1s graph ops
        |
        Workers             — AgentSDK: codergen, research, refine, validation

Signal file format (per node at {dot_dir}/signals/{node_id}.json):
    Worker result:     {"status": "success"|"failed", "files_changed": [...], "message": "..."}
    Validation result: {"result": "pass"|"fail"|"requeue", "reason": "...", "requeue_target": "node_id"}

Status chain:
    pending -> active -> impl_complete -> validated -> accepted
                      \\-> failed

Usage:
    python3 pipeline_runner.py --dot-file pipeline.dot
    python3 pipeline_runner.py --dot-file pipeline.dot --resume
    python3 pipeline_runner.py --help
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Set

# Ensure local module imports work regardless of invocation directory

from cobuilder.engine.dispatch_checkpoint import save_checkpoint  # noqa: E402
from cobuilder.engine.dispatch_parser import parse_file, parse_dot  # noqa: E402
from cobuilder.engine.providers import (  # noqa: E402
    get_llm_config_for_node,
    load_providers_file,
    ProvidersFile,
    ResolvedLLMConfig,
)
from cobuilder.engine.transition import apply_transition, VALID_TRANSITIONS  # noqa: E402

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Rate limit retry configuration
# ---------------------------------------------------------------------------
# Defaults — overridable via env vars (read lazily after .env is loaded)
_RATE_LIMIT_MAX_RETRIES_DEFAULT = 3
_RATE_LIMIT_BACKOFF_SECONDS_DEFAULT = 65  # DashScope resets ~60s


def _get_rate_limit_retries() -> int:
    """Get max retries. Set PIPELINE_RATE_LIMIT_RETRIES=1 to disable retry."""
    return int(os.environ.get("PIPELINE_RATE_LIMIT_RETRIES", str(_RATE_LIMIT_MAX_RETRIES_DEFAULT)))


def _get_rate_limit_backoff() -> int:
    """Get backoff seconds. Set PIPELINE_RATE_LIMIT_BACKOFF=0 to skip sleep."""
    return int(os.environ.get("PIPELINE_RATE_LIMIT_BACKOFF", str(_RATE_LIMIT_BACKOFF_SECONDS_DEFAULT)))

# ---------------------------------------------------------------------------
# Watchdog import (optional — falls back to polling if not installed)
# ---------------------------------------------------------------------------

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    _WATCHDOG_AVAILABLE = True
except ImportError:
    _WATCHDOG_AVAILABLE = False
    Observer = None  # type: ignore[assignment,misc]
    FileSystemEventHandler = object  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# AgentSDK import (optional — falls back to subprocess dispatch)
# ---------------------------------------------------------------------------

try:
    import claude_code_sdk  # type: ignore[import]
    _SDK_AVAILABLE = True
except ImportError:
    claude_code_sdk = None  # type: ignore[assignment]
    _SDK_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logfire instrumentation (optional — graceful no-op if not installed)
# ---------------------------------------------------------------------------

try:
    import logfire
    logfire.configure(scrubbing=False)
    _LOGFIRE_AVAILABLE = True
except ImportError:
    logfire = None  # type: ignore[assignment]
    _LOGFIRE_AVAILABLE = False

# OpenTelemetry context propagation for background threads
try:
    from contextvars import copy_context
    _CONTEXT_COPY_AVAILABLE = True
except ImportError:
    _CONTEXT_COPY_AVAILABLE = False

# Worker state tracking for dead worker detection
class WorkerState(Enum):
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

@dataclass
class WorkerInfo:
    node_id: str
    future: Future
    submitted_at: float
    state: WorkerState = WorkerState.SUBMITTED
    result: Optional[Any] = None
    exception: Optional[Exception] = None
    process_handle: Optional[subprocess.Popen] = None

class AdvancedWorkerTracker:
    """Advanced worker tracking with comprehensive liveness monitoring."""

    def __init__(self, default_timeout: int = 900):  # 15 min default
        self.default_timeout = default_timeout
        self.workers: Dict[str, WorkerInfo] = {}
        self.lock = threading.RLock()

    def track_worker(self, node_id: str, future: Future, process_handle: Optional[subprocess.Popen] = None) -> WorkerInfo:
        """Track a new worker future with process handle."""
        with self.lock:
            worker_info = WorkerInfo(
                node_id=node_id,
                future=future,
                submitted_at=time.time(),
                process_handle=process_handle
            )
            self.workers[node_id] = worker_info
            return worker_info

    def update_worker_states(self) -> None:
        """Update states of all tracked workers with comprehensive monitoring."""
        current_time = time.time()
        timeout_threshold = self.default_timeout

        with self.lock:
            for node_id, worker_info in self.workers.items():
                if worker_info.state in [WorkerState.COMPLETED, WorkerState.FAILED, WorkerState.CANCELLED]:
                    continue

                # Check if future is done
                if worker_info.future.done():
                    try:
                        worker_info.result = worker_info.future.result(timeout=0.01)
                        worker_info.state = WorkerState.COMPLETED
                    except Exception as e:
                        worker_info.exception = e
                        worker_info.state = WorkerState.FAILED
                    continue

                # Check for timeout
                elapsed = current_time - worker_info.submitted_at
                if elapsed > timeout_threshold:
                    # Attempt to cancel the future
                    if worker_info.future.cancel():
                        worker_info.state = WorkerState.CANCELLED
                    else:
                        worker_info.state = WorkerState.TIMED_OUT

                    # If there's a process handle, attempt to terminate it
                    if worker_info.process_handle:
                        try:
                            worker_info.process_handle.terminate()
                            worker_info.process_handle.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            worker_info.process_handle.kill()

    def get_dead_workers(self) -> list:
        """Get list of workers that are in failed, timed_out, or cancelled states."""
        with self.lock:
            dead_workers = []
            for node_id, worker_info in self.workers.items():
                if worker_info.state in [WorkerState.FAILED, WorkerState.TIMED_OUT, WorkerState.CANCELLED]:
                    dead_workers.append((node_id, worker_info))
            return dead_workers

    def remove_worker(self, node_id: str) -> bool:
        """Remove a worker from tracking."""
        with self.lock:
            if node_id in self.workers:
                del self.workers[node_id]
                return True
            return False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [runner] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline_runner")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Handler types that map to worker dispatch (AgentSDK)
WORKER_HANDLERS = frozenset({"codergen", "research", "refine"})

# Handler registry: handler name -> method name on PipelineRunner
HANDLER_REGISTRY: dict[str, str] = {
    "start":      "_handle_noop",
    "noop":       "_handle_noop",
    "codergen":   "_handle_worker",
    "research":   "_handle_worker",
    "refine":     "_handle_worker",
    "tool":       "_handle_tool",
    "exit":       "_handle_exit",
    "gate":       "_handle_gate",
    "wait.human": "_handle_human",
    "wait.system3": "_handle_gate",
    "wait.cobuilder": "_handle_gate",
    "acceptance-test-writer": "_handle_worker",
}

# Mechanical transitions applied to validation signal results
SIGNAL_TRANSITIONS: dict[str, str] = {
    "pass":    "validated",
    "success": "impl_complete",
    "fail":    "failed",
    "requeue": "pending",
}

# Max retries per node before giving up
MAX_RETRIES = 3

# Polling fallback interval when watchdog is unavailable
POLL_INTERVAL_S = 2.0

# ---------------------------------------------------------------------------
# Watchdog event handlers
# ---------------------------------------------------------------------------


class _SignalFileHandler(FileSystemEventHandler if _WATCHDOG_AVAILABLE else object):
    """Watchdog handler for the signals/ directory.

    Sets ``event`` when any .json file is created or modified.
    """

    def __init__(self, event: threading.Event) -> None:
        if _WATCHDOG_AVAILABLE:
            super().__init__()  # type: ignore[call-arg]
        self._event = event

    def on_created(self, event: Any) -> None:  # type: ignore[override]
        if not getattr(event, "is_directory", False) and str(getattr(event, "src_path", "")).endswith(".json"):
            log.debug("Signal file created: %s", event.src_path)
            self._event.set()

    def on_modified(self, event: Any) -> None:  # type: ignore[override]
        if not getattr(event, "is_directory", False) and str(getattr(event, "src_path", "")).endswith(".json"):
            log.debug("Signal file modified: %s", event.src_path)
            self._event.set()


class _DotFileHandler(FileSystemEventHandler if _WATCHDOG_AVAILABLE else object):
    """Watchdog handler for the DOT file directory.

    Sets ``event`` when the monitored .dot file changes.
    """

    def __init__(self, dot_path: str, event: threading.Event) -> None:
        if _WATCHDOG_AVAILABLE:
            super().__init__()  # type: ignore[call-arg]
        self._dot_path = os.path.abspath(dot_path)
        self._event = event

    def on_modified(self, event: Any) -> None:  # type: ignore[override]
        if not getattr(event, "is_directory", False) and os.path.abspath(str(getattr(event, "src_path", ""))) == self._dot_path:
            log.debug("DOT file modified: %s", event.src_path)
            self._event.set()

    def on_created(self, event: Any) -> None:  # type: ignore[override]
        if not getattr(event, "is_directory", False) and os.path.abspath(str(getattr(event, "src_path", ""))) == self._dot_path:
            self._event.set()


# ---------------------------------------------------------------------------
# PipelineRunner
# ---------------------------------------------------------------------------


class PipelineRunner:
    """Pure Python DOT pipeline state machine.

    Operates by:
    1. Parsing the DOT file to find dispatchable nodes.
    2. Dispatching workers via AgentSDK.
    3. Watching signal files for results via watchdog.
    4. Mechanically applying transitions — no LLM involvement.
    """

    HANDLER_REGISTRY = HANDLER_REGISTRY

    def __init__(self, dot_path: str, resume: bool = False) -> None:
        self.dot_path = os.path.abspath(dot_path)
        self.dot_dir = os.path.dirname(self.dot_path)
        # Each pipeline gets its own signal subdirectory to avoid cross-pipeline clutter
        self.pipeline_id = os.path.splitext(os.path.basename(self.dot_path))[0]
        self.signal_dir = os.path.join(self.dot_dir, "signals", self.pipeline_id)
        self.resume = resume

        # Load attractor .env if present (sets ANTHROPIC_MODEL, ANTHROPIC_BASE_URL, etc.)
        self._load_engine_env()

        # Active workers: node_id -> worker metadata dict
        self.active_workers: dict[str, dict[str, Any]] = {}

        # Initialize advanced worker tracker for dead worker detection
        self.worker_tracker = AdvancedWorkerTracker(
            default_timeout=int(os.environ.get("WORKER_SIGNAL_TIMEOUT", "900"))
        )

        # Retry counters: node_id -> int
        self.retry_counts: dict[str, int] = {}

        # Requeue guidance: node_id -> failure message from downstream verify
        # Injected into worker prompt on re-dispatch so the worker knows what to fix
        self.requeue_guidance: dict[str, str] = {}

        # Orphan resume counts: node_id -> int (for exponential backoff)
        self.orphan_resume_counts: dict[str, int] = {}

        # Threading event — wakes the main loop on file changes
        self._wake_event = threading.Event()

        # Read initial DOT content
        with open(self.dot_path) as fh:
            self.dot_content = fh.read()

        os.makedirs(self.signal_dir, exist_ok=True)

        pipeline_data = parse_dot(self.dot_content)
        self.pipeline_id = pipeline_data.get("graph_name", os.path.splitext(os.path.basename(dot_path))[0])
        self._graph_attrs = pipeline_data.get("graph_attrs", {})
        log.info("Pipeline loaded: %s  nodes=%d", self.pipeline_id, len(pipeline_data.get("nodes", [])))

        # Load providers.yaml for per-node LLM configuration (Epic 1)
        self._providers = self._load_providers()

    def _load_providers(self) -> ProvidersFile:
        """Load providers.yaml for per-node LLM configuration.

        Search order (per providers.py):
        1. graph_attrs.providers_file in DOT file
        2. dot_dir/providers.yaml (next to DOT file)
        3. repo_root/providers.yaml (repo root)
        4. Empty ProvidersFile if not found

        Returns:
            Loaded ProvidersFile, or empty ProvidersFile if not found.
        """
        providers_file_path = self._graph_attrs.get("providers_file")
        manifest_dir = self.dot_dir
        project_root = self._get_repo_root()

        providers = load_providers_file(
            providers_file_path=providers_file_path,
            manifest_dir=manifest_dir,
            project_root=project_root,
        )
        if providers.list_profiles():
            log.info(
                "Loaded %d LLM profile(s) from providers.yaml: %s",
                len(providers.list_profiles()),
                ", ".join(providers.list_profiles()),
            )
        return providers

    def _load_engine_env(self) -> None:
        """Source cobuilder/engine/.env if it exists. Sets ANTHROPIC_MODEL etc.

        The .env file lives alongside pipeline_runner.py at
        cobuilder/engine/.env. Values ALWAYS override existing env vars
        so that editing .env takes effect on relaunch.
        """
        # .env is co-located with this module
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if not os.path.isfile(env_path):
            return
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Handle 'export KEY=VALUE' and 'KEY=VALUE'
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Expand $VARIABLE references using values already set in
                    # this .env file (earlier lines) or the inherited environment
                    if value.startswith('$'):
                        ref_key = value[1:]
                        value = os.environ.get(ref_key, value)
                    if key:
                        os.environ[key] = value
                        log.debug("[env] Set %s from attractor .env", key)

    def _get_target_dir(self) -> str:
        """Return target directory for worker execution. Falls back to dot_dir."""
        target = self._graph_attrs.get("target_dir", "")
        if target and os.path.isdir(target):
            return target
        return self.dot_dir

    def _resolve_target_dir(self, node_attrs: dict | None = None) -> str:
        """Resolve target directory: node attr > graph attr > dot_dir."""
        if node_attrs:
            node_td = node_attrs.get("target_dir", "")
            if node_td and os.path.isdir(node_td):
                return node_td
        graph_td = self._graph_attrs.get("target_dir", "")
        if graph_td and os.path.isdir(graph_td):
            return graph_td
        return self.dot_dir

    def _get_repo_root(self) -> str:
        """Find the git repo root by walking up from dot_dir. Falls back to target_dir."""
        d = os.path.abspath(self.dot_dir)
        for _ in range(10):  # max 10 levels up
            if os.path.isdir(os.path.join(d, ".git")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
        return self._get_target_dir()

    def _resolve_llm_config(
        self,
        node_id: str,
        handler_type: str,
        node_attrs: dict | None = None,
    ) -> ResolvedLLMConfig:
        """Resolve LLM configuration for a node using 5-layer resolution.

        Resolution order (first non-null wins):
        1. Node's llm_profile attribute → look up in providers.yaml
        2. handler_defaults.{handler_type}.llm_profile from graph_attrs
        3. defaults.llm_profile from graph_attrs
        4. Environment variables (ANTHROPIC_MODEL, ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL)
        5. Runner defaults (hardcoded fallback)

        Args:
            node_id: Node ID for logging context.
            handler_type: Handler type (e.g., "codergen", "research", "refine").
            node_attrs: Node attributes dict (may contain llm_profile).

        Returns:
            ResolvedLLMConfig with fully resolved values.
        """
        # Extract llm_profile from node attrs if present
        node_llm_profile = None
        if node_attrs:
            node_llm_profile = node_attrs.get("llm_profile")

        # Build a minimal manifest-like object from graph_attrs
        class _ManifestDefaults:
            def __init__(self, graph_attrs: dict) -> None:
                self.llm_profile = graph_attrs.get("llm_profile")
                self.handler_defaults = graph_attrs.get("handler_defaults", {})

        manifest_defaults = _ManifestDefaults(self._graph_attrs)

        return get_llm_config_for_node(
            node=type("_Node", (), {
                "attrs": node_attrs or {},
                "llm_profile": node_llm_profile,
                "handler_type": handler_type,
                "id": node_id,
            })(),
            providers=self._providers,
            manifest=type("_Manifest", (), {"defaults": manifest_defaults})(),
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> bool:
        """Run the pipeline to completion. Returns True on success, False on failure."""
        log.info("Starting pipeline runner  dot=%s  resume=%s  watchdog=%s  sdk=%s  logfire=%s",
                 self.dot_path, self.resume, _WATCHDOG_AVAILABLE, _SDK_AVAILABLE, _LOGFIRE_AVAILABLE)

        # Top-level Logfire span wraps the entire pipeline run
        if _LOGFIRE_AVAILABLE:
            self._pipeline_span = logfire.span(
                "pipeline_runner {pipeline_id}",
                pipeline_id=self.pipeline_id,
                dot_path=str(self.dot_path),
                resume=self.resume,
            )
            self._pipeline_span.__enter__()
        else:
            self._pipeline_span = None

        if not self.resume:
            self._reset_active_nodes()

        observers: list[Any] = []
        if _WATCHDOG_AVAILABLE:
            # Watch the signals directory for worker result files
            sig_handler = _SignalFileHandler(self._wake_event)
            sig_observer = Observer()
            sig_observer.schedule(sig_handler, self.signal_dir, recursive=False)
            sig_observer.start()
            observers.append(sig_observer)

            # Watch the DOT file directory for external DOT changes
            dot_handler = _DotFileHandler(self.dot_path, self._wake_event)
            dot_observer = Observer()
            dot_observer.schedule(dot_handler, self.dot_dir, recursive=False)
            dot_observer.start()
            observers.append(dot_observer)

        try:
            return self._main_loop()
        finally:
            for obs in observers:
                obs.stop()
                obs.join()
            if self._pipeline_span is not None:
                self._pipeline_span.__exit__(None, None, None)

    def _main_loop(self) -> bool:
        """Main event loop. Blocks on _wake_event until pipeline completes."""
        max_iterations = 500  # safety limit
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Reload DOT content from disk (may have been modified externally)
            try:
                with open(self.dot_path) as fh:
                    self.dot_content = fh.read()
            except OSError as exc:
                log.error("Cannot read DOT file: %s", exc)
                return False

            # Process any pending signal files first
            self._process_signals()

            # Check for dead workers (futures completed but no signal written)
            self._check_worker_liveness()

            # Reload content after signal processing (transitions may have been written)
            try:
                with open(self.dot_path) as fh:
                    self.dot_content = fh.read()
            except OSError:
                pass

            data = parse_dot(self.dot_content)
            nodes = data.get("nodes", [])

            # Check for pipeline completion
            if self._is_pipeline_complete(nodes):
                log.info("Pipeline complete: all exit nodes accepted/validated.")
                self._save_checkpoint("complete")
                return True

            # Find and dispatch nodes that are ready
            dispatchable = self._find_dispatchable_nodes(data)
            if dispatchable:
                for node in dispatchable:
                    self._dispatch_node(node, data)
                self._save_checkpoint("progress")
                # Don't wait — immediately check for more work.
                # Don't clear the event here — a background thread may have set()
                # it while we were dispatching. The clear() after wait() handles it.
                continue

            # Re-dispatch validation for impl_complete nodes with no active workers
            impl_complete_nodes = [
                n for n in nodes
                if n["attrs"].get("status") == "impl_complete"
                and n["id"] not in self.active_workers
            ]
            for node in impl_complete_nodes:
                nid = node["id"]
                log.info("[resume] Re-dispatching validation for impl_complete node: %s", nid)
                self._dispatch_validation_agent(nid, nid)

            # Re-dispatch codergen workers for active nodes with no in-memory worker.
            # This handles the case where validation fails and requeues a node back to
            # "active" in the DOT, but the dispatch loop only picks up "pending" nodes.
            # Expand to include all resumable handlers (Epic D)
            RESUMABLE_HANDLERS = frozenset({"codergen", "research", "refine", "acceptance-test-writer"})
            GATE_HANDLERS = frozenset({"wait.system3", "wait.human"})

            orphaned_active_nodes = [
                n for n in nodes
                if n["attrs"].get("status") == "active"
                and n["attrs"].get("handler") in RESUMABLE_HANDLERS
                and n["id"] not in self.active_workers
            ]
            for node in orphaned_active_nodes:
                nid = node["id"]
                handler = node["attrs"].get("handler", "")
                retries = self.orphan_resume_counts.get(nid, 0)
                if retries < 3:  # Exponential backoff
                    delay = min(2 ** retries * 5, 60)  # 5s, 10s, 20s, max 60s
                    log.info("[resume] Re-dispatching %s for orphaned %s node (attempt=%d, delay=%ds)",
                             handler, nid, retries + 1, delay)
                    time.sleep(delay)
                    self._dispatch_node(node, data)
                    self.orphan_resume_counts[nid] = retries + 1
                else:
                    log.error("[resume] Exhausted retries for orphaned node %s", nid)
                    self._do_transition(nid, "failed")

            # Handle orphaned gate nodes (Epic D)
            orphaned_gate_nodes = [
                n for n in nodes
                if n["attrs"].get("status") == "active"
                and n["attrs"].get("handler") in GATE_HANDLERS
                and n["id"] not in self.active_workers
            ]
            for node in orphaned_gate_nodes:
                nid = node["id"]
                log.warning("[resume] Gate node %s stuck in active — emitting escalation", nid)
                self._write_node_signal(nid, {
                    "status": "escalation",
                    "reason": f"Gate node {nid} orphaned after restart",
                })

            # If nothing is active, check if there are dispatchable pending nodes.
            # A requeue or retry may have just reset nodes to pending — give the
            # dispatch loop one more iteration before declaring stuck.
            if not self.active_workers:
                pending_nodes = [n for n in nodes if n["attrs"].get("status", "pending") == "pending"]
                failed_nodes = [n for n in nodes if n["attrs"].get("status", "pending") == "failed"]
                if pending_nodes:
                    # Pending nodes exist — continue to next iteration so the
                    # dispatch logic at the top of the loop can pick them up.
                    log.info("No active workers but %d pending nodes — re-entering dispatch loop",
                             len(pending_nodes))
                    continue
                if failed_nodes and not pending_nodes:
                    log.error("Pipeline stuck: 0 pending, %d failed, 0 active workers",
                              len(failed_nodes))
                    self._save_checkpoint("stuck")
                    return False
                # All nodes are in terminal states but not "complete" — recheck
                if self._is_pipeline_complete(nodes):
                    log.info("Pipeline complete on recheck.")
                    self._save_checkpoint("complete")
                    return True

            # Wait for a file event or poll timeout.
            # IMPORTANT: Do NOT clear() before wait() — that races with background
            # threads calling set() (validation, worker signals). Instead, wait first,
            # then clear. If set() fires between clear() and the next wait(), the
            # wait() returns immediately (correct behavior).
            if _WATCHDOG_AVAILABLE:
                self._wake_event.wait(timeout=30.0)
                self._wake_event.clear()
            else:
                time.sleep(POLL_INTERVAL_S)

        log.error("Pipeline exceeded max iterations (%d). Aborting.", max_iterations)
        return False

    # ------------------------------------------------------------------
    # Graph analysis
    # ------------------------------------------------------------------

    def _is_pipeline_complete(self, nodes: list[dict]) -> bool:
        """Return True when all exit nodes have reached 'validated' or 'accepted'."""
        exit_nodes = [n for n in nodes if n["attrs"].get("handler") == "exit"
                      or n["attrs"].get("shape") == "Msquare"]
        if not exit_nodes:
            # No exit node — check if ALL nodes are in a terminal state
            terminal = {"validated", "accepted", "failed"}
            return all(n["attrs"].get("status", "pending") in terminal for n in nodes)
        return all(
            n["attrs"].get("status", "pending") in ("validated", "accepted")
            for n in exit_nodes
        )

    def _find_dispatchable_nodes(self, data: dict) -> list[dict]:
        """Return nodes that are ready for dispatch.

        Conditions:
        - status == "pending"
        - handler is not None/empty
        - not already in active_workers
        - all predecessor nodes are in ("validated", "accepted")
        """
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        # Build predecessor map: node_id -> set of predecessor node_ids
        predecessors: dict[str, set[str]] = {n["id"]: set() for n in nodes}
        for edge in edges:
            dst = edge["dst"]
            src = edge["src"]
            if dst in predecessors:
                predecessors[dst].add(src)

        # Build status map
        status_of: dict[str, str] = {
            n["id"]: n["attrs"].get("status", "pending") for n in nodes
        }

        terminal_statuses = {"validated", "accepted"}
        dispatchable = []

        for node in nodes:
            nid = node["id"]
            status = node["attrs"].get("status", "pending")
            handler = node["attrs"].get("handler", "")

            if status != "pending":
                continue
            if not handler:
                continue
            if nid in self.active_workers:
                continue

            # Check all predecessors are in terminal state
            preds = predecessors.get(nid, set())
            if preds and not all(status_of.get(p, "pending") in terminal_statuses for p in preds):
                continue

            dispatchable.append(node)

        return dispatchable

    def _find_predecessor_workers(self, node_id: str, data: dict) -> list[str]:
        """Find upstream codergen/research/refine predecessor node IDs for a given node."""
        edges = data.get("edges", [])
        nodes_by_id = {n["id"]: n for n in data.get("nodes", [])}

        predecessors: list[str] = []
        for edge in edges:
            if edge["dst"] == node_id:
                src = edge["src"]
                src_node = nodes_by_id.get(src)
                if src_node and src_node["attrs"].get("handler") in WORKER_HANDLERS:
                    predecessors.append(src)
        return predecessors

    def _requeue_upstream_worker(self, tool_node_id: str, failure_message: str, data: dict) -> bool:
        """When a verify tool fails, requeue its upstream codergen predecessor.

        Returns True if an upstream node was successfully requeued, False if no
        eligible predecessor was found (caller should mark tool as permanently failed).
        """
        predecessors = self._find_predecessor_workers(tool_node_id, data)
        if not predecessors:
            log.warning("[requeue] No upstream worker found for tool node %s", tool_node_id)
            return False

        requeued_any = False
        for pred_id in predecessors:
            retries = self.retry_counts.get(pred_id, 0) + 1
            self.retry_counts[pred_id] = retries

            if retries >= MAX_RETRIES:
                log.error("[requeue] Upstream %s exhausted retries (%d/%d) — cannot fix %s",
                          pred_id, retries, MAX_RETRIES, tool_node_id)
                continue

            # Store the failure message so the re-dispatched worker gets context
            self.requeue_guidance[pred_id] = (
                f"Your previous implementation failed verification at node '{tool_node_id}'.\n"
                f"Error: {failure_message}\n"
                f"Fix the issue and re-signal completion."
            )

            # Transition predecessor back to pending: accepted/validated → failed → active
            # Then _find_dispatchable_nodes will NOT pick it up (status != pending).
            # We need to get it to pending. The valid chain from accepted is not standard,
            # so we edit the DOT directly.
            nodes_by_id = {n["id"]: n for n in data.get("nodes", [])}
            pred_node = nodes_by_id.get(pred_id)
            if pred_node:
                current = pred_node["attrs"].get("status", "pending")
                log.info("[requeue] Resetting upstream %s (%s -> pending) for retry %d/%d",
                         pred_id, current, retries, MAX_RETRIES)
                # Use direct DOT edit to reset to pending (transition chain doesn't support accepted->pending)
                self._force_status(pred_id, "pending")
                # Also reset the tool node itself to pending so it re-runs after the worker
                self._force_status(tool_node_id, "pending")
                requeued_any = True

        return requeued_any

    def _force_status(self, node_id: str, target_status: str) -> None:
        """Directly edit the DOT file to set a node's status, bypassing transition validation.

        Used for requeue operations where the standard transition chain doesn't support
        the required state change (e.g., accepted -> pending).
        """
        self._do_transition(node_id, target_status)
        # Also persist requeue guidance if present
        if node_id in self.requeue_guidance:
            self._persist_requeue_guidance(node_id, self.requeue_guidance[node_id])

    def _persist_requeue_guidance(self, node_id: str, guidance: str) -> None:
        """Persist requeue guidance to a file so it survives reloads."""
        guidance_dir = os.path.join(self.signal_dir, "guidance")
        os.makedirs(guidance_dir, exist_ok=True)
        guidance_path = os.path.join(guidance_dir, f"{node_id}.txt")
        try:
            with open(guidance_path, "w") as fh:
                fh.write(guidance)
        except OSError as exc:
            log.error("[persist-guidance] Failed to write guidance for %s: %s", node_id, exc)

    def _load_persisted_guidance(self, node_id: str) -> str | None:
        """Load persisted requeue guidance from file (survives runner restarts).

        Returns the guidance text if found, else None. Does NOT delete the file
        so guidance persists across multiple retry attempts.
        """
        guidance_dir = os.path.join(self.signal_dir, "guidance")
        guidance_path = os.path.join(guidance_dir, f"{node_id}.txt")
        try:
            with open(guidance_path, "r") as fh:
                return fh.read().strip() or None
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.error("[load-guidance] Failed to read guidance for %s: %s", node_id, exc)
            return None

    # ------------------------------------------------------------------
    # Node dispatch
    # ------------------------------------------------------------------

    def _dispatch_node(self, node: dict, data: dict) -> None:
        """Dispatch a single node based on its handler type."""
        nid = node["id"]
        handler = node["attrs"].get("handler", "")

        method_name = self.HANDLER_REGISTRY.get(handler)
        if method_name is None:
            log.warning("Unknown handler '%s' for node %s — treating as noop", handler, nid)
            method_name = "_handle_noop"

        method = getattr(self, method_name)

        # Transition to active before dispatch (except noop/exit which self-complete)
        if method_name not in ("_handle_noop", "_handle_exit"):
            self._transition(nid, "active")

        method(node, data)

    def _handle_noop(self, node: dict, data: dict) -> None:  # noqa: ARG002
        """Start nodes: immediately write a success signal and transition to validated."""
        nid = node["id"]
        log.info("[noop] %s -> validated immediately", nid)
        # Transition active -> validated directly (start nodes use hexagon shortcut)
        self._transition(nid, "active")
        self._transition(nid, "validated")
        self._write_node_signal(nid, {"status": "success", "message": "start node — no work needed"})

    def _handle_exit(self, node: dict, data: dict) -> None:  # noqa: ARG002
        """Exit nodes: validate immediately if finalize gate is satisfied.

        The finalize gate is enforced by transition.py (raises ValueError if
        hexagon nodes are not yet validated). If the gate blocks, we log and
        do not dispatch.
        """
        nid = node["id"]
        log.info("[exit] %s — attempting finalize", nid)
        try:
            self._transition(nid, "active")
            self._transition(nid, "validated")
            self._transition(nid, "accepted")
            log.info("[exit] %s -> accepted (pipeline finalized)", nid)
        except ValueError as exc:
            log.warning("[exit] %s finalize gate blocked: %s", nid, exc)
            # Reset to pending so we retry when gate opens
            # (no transition needed — it was never moved out of pending)

    def _handle_worker(self, node: dict, data: dict) -> None:
        """Dispatch a codergen/research/refine node via AgentSDK or subprocess."""
        nid = node["id"]
        attrs = node["attrs"]
        worker_type = attrs.get("worker_type", "backend-solutions-engineer")
        prd_ref = attrs.get("prd_ref", data.get("graph_attrs", {}).get("prd_ref", ""))

        log.info("[worker] Dispatching %s (handler=%s worker_type=%s)",
                 nid, attrs.get("handler"), worker_type)
        if _LOGFIRE_AVAILABLE:
            logfire.info("dispatch_worker {node_id}",
                         node_id=nid, handler=attrs.get("handler"),
                         worker_type=worker_type, prd_ref=prd_ref)

        # Build task prompt from node attributes
        prompt = self._build_worker_prompt(node, data)

        # Register as active before spawning thread
        self.active_workers[nid] = {
            "node_id": nid,
            "worker_type": worker_type,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "prd_ref": prd_ref,
        }

        # Dispatch via ThreadPoolExecutor so Logfire auto-propagates OTel context.
        # (Logfire patches ThreadPoolExecutor; raw threading.Thread loses trace linkage.)
        if not hasattr(self, "_executor"):
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="worker")
        handler = attrs.get("handler", "codergen")

        # Resolve per-node target_dir for worker cwd
        resolved_target_dir = self._resolve_target_dir(attrs)

        # Submit the task and track the future for liveness monitoring
        future = self._executor.submit(self._dispatch_agent_sdk, nid, worker_type, prompt, handler, resolved_target_dir, attrs)

        # Track the worker future using the advanced worker tracker
        self.worker_tracker.track_worker(nid, future)

    def _handle_tool(self, node: dict, data: dict) -> None:  # noqa: ARG002
        """Tool nodes: run subprocess.run() with the command from node attrs."""
        nid = node["id"]
        cmd = node["attrs"].get("command", "")
        if not cmd:
            log.warning("[tool] %s has no 'command' attribute — skipping", nid)
            self._write_node_signal(nid, {"status": "failed", "message": "no command attribute"})
            return

        log.info("[tool] %s — running: %s", nid, cmd[:200])
        _span = logfire.span("tool {node_id}", node_id=nid, command=cmd[:200]) if _LOGFIRE_AVAILABLE else None
        if _span:
            _span.__enter__()
        self.active_workers[nid] = {
            "node_id": nid,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        try:
            result = subprocess.run(
                cmd,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=300,
                cwd=self.dot_dir,
            )
            if result.returncode == 0:
                if _LOGFIRE_AVAILABLE:
                    logfire.info("tool PASS", node_id=nid)
                self._write_node_signal(nid, {
                    "status": "success",
                    "message": result.stdout[-500:] if result.stdout else "exit code 0",
                })
            else:
                if _LOGFIRE_AVAILABLE:
                    logfire.info("tool FAIL exit={rc}", node_id=nid, rc=result.returncode,
                                 stderr=result.stderr[-300:] if result.stderr else "")
                self._write_node_signal(nid, {
                    "status": "failed",
                    "message": f"exit {result.returncode}: {result.stderr[-300:]}",
                })
        except subprocess.TimeoutExpired:
            self._write_node_signal(nid, {"status": "failed", "message": "tool timeout (300s)"})
        except Exception as exc:  # noqa: BLE001
            self._write_node_signal(nid, {"status": "failed", "message": str(exc)})
        finally:
            self.active_workers.pop(nid, None)
            self._wake_event.set()
            if _span:
                _span.__exit__(None, None, None)

    def _handle_gate(self, node: dict, data: dict) -> None:  # noqa: ARG002
        """Gate/wait.system3 nodes: emit a gate-wait signal and mark as waiting.

        System 3 must write a pass signal to {signal_dir}/{node_id}.json to
        unblock the gate.
        """
        nid = node["id"]
        log.info("[gate] %s — waiting for System 3 approval", nid)
        # Mark as active so the runner knows it's waiting
        self.active_workers[nid] = {
            "node_id": nid,
            "waiting_for": "system3",
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        # Write a gate-wait marker file so System 3 knows to look at this node
        gate_marker = os.path.join(self.signal_dir, f"{nid}.gate-wait")
        with open(gate_marker, "w") as fh:
            json.dump({
                "node_id": nid,
                "gate_type": "wait.system3",
                "summary_ref": node["attrs"].get("summary_ref", ""),
                "epic_id": node["attrs"].get("epic_id", ""),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }, fh)
        log.info("[gate] Gate marker written: %s", gate_marker)

    def _handle_human(self, node: dict, data: dict) -> None:
        """Human review nodes (wait.human): emit gate-wait marker + GChat review request."""
        nid = node["id"]
        log.info("[human] %s — requesting human review", nid)
        self.active_workers[nid] = {
            "node_id": nid,
            "waiting_for": "human",
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        # Write a gate-wait marker file so System 3 / monitor can detect this gate
        gate_marker = os.path.join(self.signal_dir, f"{nid}.gate-wait")
        with open(gate_marker, "w") as fh:
            json.dump({
                "node_id": nid,
                "gate_type": "wait.human",
                "summary_ref": node["attrs"].get("summary_ref", ""),
                "mode": node["attrs"].get("mode", "technical"),
                "epic_id": node["attrs"].get("epic_id", ""),
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }, fh)
        log.info("[human] Gate marker written: %s", gate_marker)
        # Attempt GChat notification; fall back gracefully
        try:
            from cobuilder.engine.gchat_adapter import send_review_request  # type: ignore[import]
            send_review_request(
                node_id=nid,
                pipeline_id=self.pipeline_id,
                acceptance=node["attrs"].get("acceptance", ""),
            )
        except (ImportError, Exception) as exc:  # noqa: BLE001
            log.warning("[human] GChat dispatch failed: %s", exc)

    # ------------------------------------------------------------------
    # AgentSDK dispatch
    # ------------------------------------------------------------------

    def _dispatch_agent_sdk(self, node_id: str, worker_type: str, prompt: str, handler: str = "codergen", target_dir: str = "", node_attrs: dict | None = None) -> None:
        """Dispatch a worker via claude_code_sdk. No headless fallback.

        All worker dispatch goes through AgentSDK exclusively.
        This method runs in a background thread. On completion it writes a
        signal file to {signal_dir}/{node_id}.json and sets _wake_event.
        """
        effective_dir = target_dir or self._get_target_dir()

        # Resolve LLM config using 5-layer resolution (Epic 1)
        llm_config = self._resolve_llm_config(node_id, handler, node_attrs)
        worker_model = llm_config.model

        log.info("[sdk] Dispatching worker  node=%s  type=%s  model=%s  profile=%s  cwd=%s",
                 node_id, worker_type, worker_model, llm_config.profile_name or "default", effective_dir)

        # Logfire span covers the entire worker lifecycle (dispatch → completion)
        _span = None
        if _LOGFIRE_AVAILABLE:
            _span = logfire.span(
                "sdk_worker {node_id} ({worker_type})",
                node_id=node_id, worker_type=worker_type,
                model=worker_model, cwd=effective_dir,
                sdk_version=getattr(claude_code_sdk, "__version__", "unknown"),
            )
            _span.__enter__()

        try:
            if not _SDK_AVAILABLE or claude_code_sdk is None:
                log.error("[sdk] claude_code_sdk not available — cannot dispatch %s", node_id)
                self._write_node_signal(node_id, {
                    "status": "failed",
                    "message": "claude_code_sdk not installed. Install with: pip install claude-code-sdk",
                })
                self.active_workers.pop(node_id, None)
                self._wake_event.set()
                return

            # Rate limit retry loop — backs off and retries on 429 / rate_limit_event.
            # Configure via env: PIPELINE_RATE_LIMIT_RETRIES (default 3, set 1 to disable)
            #                    PIPELINE_RATE_LIMIT_BACKOFF (default 65s, set 0 to skip sleep)
            _max_retries = _get_rate_limit_retries()
            _backoff = _get_rate_limit_backoff()
            for _attempt in range(1, _max_retries + 1):
                self._dispatch_via_sdk(node_id, worker_type, prompt, handler, effective_dir, llm_config)
                # _dispatch_via_sdk writes the signal itself; read it back to
                # detect a rate-limit failure before deciding to retry.
                signal_path = os.path.join(self.signal_dir, f"{node_id}.json")
                _result: dict = {}
                if os.path.isfile(signal_path):
                    try:
                        with open(signal_path) as _sf:
                            _result = json.load(_sf)
                    except Exception:  # noqa: BLE001
                        pass
                _msg = _result.get("message", "").lower()
                _is_rate_limit = (
                    _result.get("status") == "failed"
                    and ("rate_limit" in _msg or "rate limit" in _msg or "429" in _msg)
                )
                if _is_rate_limit and _attempt < _max_retries:
                    # Guard: if the signal watcher already advanced this node
                    # (e.g. worker actually succeeded but SDK stream errored),
                    # don't retry — we'd be spawning a ghost worker.
                    _current = self._get_node_status(node_id)
                    if _current != "active":
                        log.info(
                            "[sdk] Node %s already transitioned to %s, skipping retry",
                            node_id, _current,
                        )
                        break
                    log.warning(
                        "[sdk] Rate limited on %s (attempt %d/%d), backing off %ds",
                        node_id, _attempt, _max_retries, _backoff,
                    )
                    # Remove stale signal so the next attempt writes a fresh one.
                    try:
                        os.remove(signal_path)
                    except OSError:
                        pass
                    if _backoff > 0:
                        time.sleep(_backoff)
                    continue
                if _is_rate_limit:
                    log.error(
                        "[sdk] Rate limited on %s after %d attempts, giving up",
                        node_id, _max_retries,
                    )
                break  # Success or non-rate-limit failure — do not retry.
        except Exception as exc:  # noqa: BLE001
            log.error("[sdk] SDK dispatch failed for %s: %s", node_id, exc)
            self._write_node_signal(node_id, {
                "status": "failed",
                "message": f"SDK dispatch error: {exc}",
            })
            self.active_workers.pop(node_id, None)
            self._wake_event.set()
        finally:
            if _span:
                _span.__exit__(None, None, None)

    # ------------------------------------------------------------------
    # Handler-specific allowed_tools
    # ------------------------------------------------------------------
    # Claude Code SDK `allowed_tools` is a RESTRICT list: only listed tools
    # can be used. MCP tools are deferred — they need ToolSearch to load
    # their schemas into context AND they need to be in allowed_tools to
    # pass the permission gate.
    #
    # Base tools available to ALL handlers:
    _BASE_TOOLS: list[str] = [
        "Bash", "Read", "Write", "Edit", "Glob", "Grep", "MultiEdit",
        "TodoWrite", "WebFetch", "WebSearch",
        "ToolSearch",  # MANDATORY — loads deferred MCP tool schemas
        "Skill",       # Native skill invocation (requires setting_sources)
        "LSP",         # type info, definitions, diagnostics
    ]
    # Serena: semantic code navigation and symbol-level editing
    _SERENA_TOOLS: list[str] = [
        "mcp__serena__activate_project",
        "mcp__serena__check_onboarding_performed",
        "mcp__serena__find_symbol",
        "mcp__serena__search_for_pattern",
        "mcp__serena__get_symbols_overview",
        "mcp__serena__find_referencing_symbols",
        "mcp__serena__find_file",
        "mcp__serena__replace_symbol_body",
        "mcp__serena__insert_after_symbol",
        "mcp__serena__insert_before_symbol",
    ]
    # Context7: framework documentation lookup
    _CONTEXT7_TOOLS: list[str] = [
        "mcp__context7__resolve-library-id",
        "mcp__context7__query-docs",
    ]
    # Perplexity: web research and reasoning
    _PERPLEXITY_TOOLS: list[str] = [
        "mcp__perplexity__perplexity_ask",
        "mcp__perplexity__perplexity_reason",
        "mcp__perplexity__perplexity_research",
        "mcp__perplexity__perplexity_search",
    ]
    # Hindsight: long-term memory (reflect/retain/recall)
    _HINDSIGHT_TOOLS: list[str] = [
        "mcp__hindsight__reflect",
        "mcp__hindsight__retain",
        "mcp__hindsight__recall",
    ]

    # Per-handler tool sets (additive on top of _BASE_TOOLS)
    _HANDLER_EXTRA_TOOLS: dict[str, list[str]] = {
        "codergen": [
            # Implementation workers: code nav only, no research tools
            *_SERENA_TOOLS,
        ],
        "research": [
            # Research workers: docs + web research + memory + code nav (read-only)
            *_SERENA_TOOLS,
            *_CONTEXT7_TOOLS,
            *_PERPLEXITY_TOOLS,
            *_HINDSIGHT_TOOLS,
        ],
        "refine": [
            # Refine workers: memory + reasoning + code nav (for SD verification)
            *_SERENA_TOOLS,
            *_HINDSIGHT_TOOLS,
            "mcp__perplexity__perplexity_reason",  # Reasoning only, not full research
        ],
        "acceptance-test-writer": [
            # Test writers: code nav only
            *_SERENA_TOOLS,
        ],
    }

    def _get_allowed_tools(self, handler: str) -> list[str]:
        """Build the allowed_tools list for a given handler type."""
        extra = self._HANDLER_EXTRA_TOOLS.get(handler, self._SERENA_TOOLS)
        return self._BASE_TOOLS + extra

    def _dispatch_via_sdk(self, node_id: str, worker_type: str, prompt: str, handler: str = "codergen", target_dir: str = "", llm_config: ResolvedLLMConfig | None = None) -> None:
        """Dispatch worker using claude_code_sdk."""
        import asyncio

        # Unset CLAUDECODE to avoid nested session detection
        os.environ.pop("CLAUDECODE", None)

        # Use resolved LLM config if provided, otherwise fall back to env defaults
        if llm_config is None:
            llm_config = self._resolve_llm_config(node_id, handler, None)
        worker_model = llm_config.model

        # Skills are available to SDK agents via setting_sources=['user', 'project']
        # + 'Skill' in allowed_tools. Agent .md files reference skills in their body
        # text (e.g., Skill('acceptance-test-runner')). The setting_sources option
        # enables filesystem-based skill discovery from .claude/skills/.

        # Build handler-specific allowed_tools
        tools = self._get_allowed_tools(handler)

        effective_dir = target_dir or self._get_target_dir()

        async def _run() -> dict:
            # Build clean env without CLAUDECODE
            clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            # Add PIPELINE_SIGNAL_DIR as required by GAP-6.1
            clean_env["PIPELINE_SIGNAL_DIR"] = str(self.signal_dir)
            clean_env["PROJECT_TARGET_DIR"] = effective_dir
            # Apply LLM config env vars (api_key, base_url) from resolved profile
            clean_env.update(llm_config.to_env_dict())
            options = claude_code_sdk.ClaudeCodeOptions(  # type: ignore[attr-defined]
                system_prompt=self._build_system_prompt(worker_type),
                allowed_tools=tools,
                permission_mode="bypassPermissions",
                model=worker_model,
                cwd=effective_dir,
                env=clean_env,
            )
            messages = []
            result_text = ""
            _first_msg_logged = False
            try:
                async for msg in claude_code_sdk.query(  # type: ignore[attr-defined]
                    prompt=prompt,
                    options=options,
                ):
                    messages.append(msg)
                    msg_type = type(msg).__name__
                    if not _first_msg_logged and _LOGFIRE_AVAILABLE:
                        logfire.info("worker_first_message {node_id}",
                                     node_id=node_id, worker_type=worker_type,
                                     msg_type=msg_type)
                        _first_msg_logged = True
                    # Log tool use and assistant text for real-time visibility
                    if _LOGFIRE_AVAILABLE and hasattr(msg, "content") and msg_type == "AssistantMessage":
                        for block in (msg.content if isinstance(msg.content, list) else []):
                            block_type = type(block).__name__
                            if block_type == "ToolUseBlock":
                                logfire.info("worker_tool {node_id} {tool}",
                                             node_id=node_id, tool=getattr(block, "name", ""),
                                             input_preview=str(getattr(block, "input", ""))[:300])
                            elif block_type == "TextBlock":
                                text = getattr(block, "text", "")
                                if text and len(text.strip()) > 5:
                                    logfire.info("worker_text {node_id}",
                                                 node_id=node_id, text=text[:300])
                    # Capture result from ResultMessage
                    if hasattr(msg, "result") and msg.result:  # type: ignore[union-attr]
                        result_text = str(msg.result)[:500]
            except Exception as stream_exc:  # noqa: BLE001
                # SDK may raise on unknown message types (e.g. rate_limit_event)
                # Only treat as success if result_text was captured (worker completed
                # its task and the error occurred at the tail end of the stream).
                # Protocol handshake messages alone do NOT indicate completion.
                err_msg = str(stream_exc)
                if result_text:
                    log.warning("[sdk] Stream error after result: %s", err_msg)
                elif messages:
                    log.warning("[sdk] Stream error after %d msgs (no result): %s", len(messages), err_msg)
                    return {"status": "failed", "message": f"SDK stream error before completion ({len(messages)} events): {err_msg[:200]}"}
                else:
                    raise  # No messages at all — propagate the error

            if result_text:
                return {"status": "success", "message": result_text}
            return {"status": "success", "message": f"SDK worker completed ({len(messages)} events)"}

        if _LOGFIRE_AVAILABLE:
            logfire.info("worker_dispatch_start {node_id}",
                         node_id=node_id, worker_type=worker_type,
                         model=worker_model, cwd=effective_dir)

        t0 = time.time()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_run())
        except Exception as exc:  # noqa: BLE001
            result = {"status": "failed", "message": str(exc)}
        finally:
            loop.close()

        # Fix 1 (softened): Worker-written signal is preferred, but not required.
        # If the SDK reports success but no signal file exists, the worker likely
        # ran out of turns before writing the signal. The runner writes the signal
        # on the worker's behalf at line 1274 below.
        if result.get("status") == "success":
            signal_path = os.path.join(self.signal_dir, f"{node_id}.json")
            if not os.path.exists(signal_path):
                log.warning(
                    "[sdk] Worker %s completed without writing signal file — "
                    "runner will write signal on worker's behalf",
                    node_id,
                )
                # Do NOT override to "failed" — the SDK stream completed normally.
                # The runner's _write_node_signal at line 1274 will handle it.

        elapsed = time.time() - t0
        log.info("[sdk] Worker %s finished in %.1fs  status=%s  msgs=%s",
                 node_id, elapsed, result.get("status"), result.get("message", "")[:100])
        if _LOGFIRE_AVAILABLE:
            logfire.info("worker_complete {node_id} {status} in {elapsed_s}s",
                         node_id=node_id, worker_type=worker_type,
                         status=result.get("status"), elapsed_s=round(elapsed, 1),
                         message=result.get("message", "")[:200])

        # Fix 5: Do NOT overwrite a worker-written success signal with an SDK failure.
        # Race condition: worker writes success signal → signal watcher advances node
        # to impl_complete and dispatches validation → SDK completion fires late with
        # "failed" → overwrites success → second validation agent spawns.
        # Guard: if node already advanced past "active", the signal watcher already
        # processed the worker's signal — do NOT write a competing SDK signal.
        current_node_status = self._get_node_status(node_id)
        if current_node_status != "active":
            log.info(
                "[sdk] Node %s already at '%s' (signal watcher processed worker signal) — "
                "skipping SDK signal write (sdk_status=%s)",
                node_id, current_node_status, result.get("status"),
            )
            # Do NOT pop active_workers here — the validation agent may already
            # own this slot (inserted by _dispatch_validation_agent at line 1276).
        else:
            self._write_node_signal(node_id, result)
            self.active_workers.pop(node_id, None)
        self._wake_event.set()

    def _dispatch_validation_agent(self, node_id: str, target_node_id: str) -> None:
        """Dispatch a validation-test-agent for a node at impl_complete.

        Runs in a background thread. Writes a validation signal on completion.

        Includes validation timeout and error handling for crashes.
        Also prevents validation spam for already terminal nodes.
        """
        # Guard: skip if node already terminal to avoid validation spam
        node_status = self._get_node_status(target_node_id)
        if node_status in ("validated", "accepted", "failed"):
            log.debug("[validation] Skipping dispatch for terminal node %s (status=%s)",
                     target_node_id, node_status)
            return

        log.info("[validation] Dispatching validation agent  node=%s  target=%s", node_id, target_node_id)
        self.active_workers[node_id] = {
            "node_id": node_id,
            "type": "validation",
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        # Resolve target_dir from the target node's attrs
        data = parse_dot(self.dot_content)
        target_node = next((n for n in data["nodes"] if n["id"] == target_node_id), None)
        resolved_target_dir = self._resolve_target_dir(target_node["attrs"] if target_node else None)

        # Dispatch via ThreadPoolExecutor so Logfire auto-propagates OTel context.
        if not hasattr(self, "_executor"):
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="worker")
        self._executor.submit(self._run_validation_subprocess, node_id, target_node_id, resolved_target_dir)

    def _get_node_status(self, node_id: str) -> str:
        """Get the current status of a node by reading the DOT file."""
        try:
            with open(self.dot_path) as fh:
                content = fh.read()
            data = parse_dot(content)
            node = next((n for n in data["nodes"] if n["id"] == node_id), None)
            if node:
                return node["attrs"].get("status", "pending")
        except Exception:
            pass
        return "pending"

    def _build_validation_prompt(self, target_node_id: str) -> str:
        """Build a rich validation prompt with acceptance criteria, files changed, and SD."""
        data = parse_dot(self.dot_content)
        node = next((n for n in data["nodes"] if n["id"] == target_node_id), None)
        if node is None:
            return f"Validate node {target_node_id} in pipeline {self.pipeline_id}."

        attrs = node["attrs"]
        acceptance = attrs.get("acceptance", "")
        sd_path = attrs.get("sd_path", "")
        label = attrs.get("label", target_node_id).replace("\\n", " ")

        resolved_dir = self._resolve_target_dir(attrs)
        lines = [
            f"# Validate: {label}",
            f"Node ID: {target_node_id}",
            f"Pipeline: {self.pipeline_id}",
            f"Project Directory: `{resolved_dir}`",
        ]

        if acceptance:
            lines.append(f"\n## Acceptance Criteria\n{acceptance}")
        else:
            lines.append("\n## Acceptance Criteria\n(none specified — check for reasonable implementation)")

        # Read the worker's signal to get files_changed
        processed_dir = os.path.join(self.signal_dir, "processed")
        files_changed = []
        if os.path.isdir(processed_dir):
            for fname in sorted(os.listdir(processed_dir), reverse=True):
                if target_node_id in fname and fname.endswith(".json"):
                    try:
                        with open(os.path.join(processed_dir, fname)) as fh:
                            worker_signal = json.load(fh)
                            files_changed = worker_signal.get("files_changed", [])
                            if files_changed:
                                break
                    except (OSError, json.JSONDecodeError):
                        continue

        if files_changed:
            lines.append(f"\n## Files Changed by Worker\n" + "\n".join(f"- {f}" for f in files_changed))
            lines.append("\nRead these files to verify the implementation.")
        else:
            lines.append("\n## Files Changed\n(not reported — search the codebase to find relevant changes)")

        # Inline SD if available
        if sd_path:
            sd_abs = os.path.join(self.dot_dir, sd_path) if not os.path.isabs(sd_path) else sd_path
            if os.path.exists(sd_abs):
                try:
                    with open(sd_abs) as fh:
                        sd_content = fh.read()
                    lines.append(f"\n## Solution Design\n{sd_content}")
                except OSError:
                    lines.append(f"\n## Solution Design Path\n{sd_path}")
            else:
                lines.append(f"\n## Solution Design Path\n{sd_path}")

        # Read manifest validation_method and prepend method-specific instructions
        prd_ref = attrs.get("prd_ref", data.get("graph_attrs", {}).get("prd_ref", ""))
        self._validation_method_hint = None  # Store for allowed_tools decision
        if prd_ref:
            # Walk up from DOT file directory to find acceptance-tests/{prd_ref}/manifest.yaml
            manifest_path = ""
            search_dir = self.dot_dir
            for _ in range(10):
                candidate = os.path.join(search_dir, "acceptance-tests", prd_ref, "manifest.yaml")
                if os.path.exists(candidate):
                    manifest_path = candidate
                    break
                parent = os.path.dirname(search_dir)
                if parent == search_dir:
                    break
                search_dir = parent

            if manifest_path:
                try:
                    import yaml
                    with open(manifest_path) as mfh:
                        manifest = yaml.safe_load(mfh)
                    methods = set()
                    for feature in (manifest or {}).get("features", []):
                        vm = feature.get("validation_method", "")
                        if vm:
                            methods.add(vm)
                    if "browser-required" in methods:
                        self._validation_method_hint = "browser-required"
                        lines.insert(0,
                            "MANDATORY: This PRD has browser-required features. "
                            "You MUST use Claude in Chrome (mcp__claude-in-chrome__*) tools to validate UI. "
                            "Static code analysis alone (Read/Grep) = automatic 0.0 score. "
                            "Required tool sequence: tabs_context_mcp -> navigate -> read_page -> screenshot -> interact. "
                            "If the frontend is not running, report 'BLOCKED: frontend not running' — do NOT fall back to code analysis.\n"
                        )
                    elif "api-required" in methods:
                        self._validation_method_hint = "api-required"
                        lines.insert(0,
                            "MANDATORY: This PRD has api-required features. "
                            "You MUST make actual HTTP requests (curl/httpx) to validate API endpoints. "
                            "Reading router/endpoint code alone = automatic 0.0 score. "
                            "If the API server is not running, report 'BLOCKED: API server not running'.\n"
                        )
                except Exception:  # noqa: BLE001
                    pass  # Best-effort — don't block validation on manifest parse errors

        # Signal file path for result
        signal_file_path = os.path.join(self.signal_dir, f"{target_node_id}.json")
        lines.append(
            f"\n## Write Your Result\n"
            f"Write your validation result to: {signal_file_path}\n\n"
            f"PASS example:\n"
            f'```\nWrite(file_path="{signal_file_path}", content=\'{{"result": "pass", "reason": "All criteria met"}}\')\n```\n\n'
            f"FAIL example:\n"
            f'```\nWrite(file_path="{signal_file_path}", content=\'{{"result": "fail", "reason": "Criterion X not met because..."}}\')\n```'
        )

        # Git Commit Requirement section — only when files were changed and not opted out
        skip_commit = attrs.get("skip_commit", "false") == "true"
        if files_changed and not skip_commit:
            effective_prd_ref = prd_ref if prd_ref else "pipeline"
            epic_id = attrs.get("epic_id", target_node_id)
            files_list = "\n".join(f"  - {f}" for f in files_changed)
            commit_msg = f"feat({effective_prd_ref}): {label} [{target_node_id}]"
            lines.append(
                f"\n## Git Commit Requirement\n"
                f"The implementation worker left these files modified in the working tree:\n"
                f"{files_list}\n\n"
                f"**If validation PASSES** (you are about to write `{{\"result\": \"pass\"}}`), you MUST commit these changes BEFORE writing the signal file:\n\n"
                f"```\n"
                f"# 1. Stage only the files listed above\n"
                f"Bash(command='git add {' '.join(files_changed)}', description='Stage implementation files')\n\n"
                f"# 2. Verify something is staged\n"
                f"Bash(command='git diff --cached --name-only', description='Confirm staged files')\n\n"
                f"# 3. Commit with the required message format\n"
                f"Bash(command='git commit -m \"{commit_msg}\" -m \"epic_id: {epic_id}\\nprd_ref: {effective_prd_ref}\\nvalidated_by: validation-test-agent\"', description='Commit validated implementation')\n"
                f"```\n\n"
                f"If `git commit` fails for any reason, write a fail signal instead of a pass:\n"
                f'```\nWrite(file_path="{signal_file_path}", content=\'{{"result": "fail", "reason": "git commit failed: <error>"}}\')\n```\n\n'
                f"**If validation FAILS or you are writing `{{\"result\": \"fail\"}}` or `{{\"result\": \"requeue\"}}`**:\n"
                f"- Do NOT stage or commit any files\n"
                f"- Leave the working tree dirty so the implementation can be inspected and reworked"
            )

        return "\n".join(lines)

    def _run_validation_subprocess(self, node_id: str, target_node_id: str, target_dir: str = "") -> None:
        """Run validation-test-agent via AgentSDK. Falls back to auto-pass if unavailable.

        Validation is a System 3 concern — the runner auto-advances nodes when
        validation dispatch is not possible (e.g., nested sessions, no SDK).

        Includes timeout handling and error reporting for validation crashes.
        """
        import asyncio

        _span = None
        if _LOGFIRE_AVAILABLE:
            _span = logfire.span(
                "validation_agent {node_id}",
                node_id=node_id, target_node_id=target_node_id,
            )
            _span.__enter__()

        if not _SDK_AVAILABLE or claude_code_sdk is None:
            log.warning("[validation] SDK not available — auto-passing %s", node_id)
            signal: dict = {"result": "pass", "reason": "auto-pass: SDK not available for validation"}
            self._write_node_signal(node_id, signal)
            self.active_workers.pop(node_id, None)
            self._wake_event.set()
            if _span:
                _span.__exit__(None, None, None)
            return

        os.environ.pop("CLAUDECODE", None)
        effective_dir = target_dir or self._get_target_dir()

        # Resolve LLM config for validation agent (Epic 1)
        llm_config = self._resolve_llm_config(node_id, "validation", None)
        worker_model = llm_config.model

        # Build a rich validation prompt with acceptance criteria and context
        prompt = self._build_validation_prompt(target_node_id)

        if _LOGFIRE_AVAILABLE:
            logfire.info("validation_dispatch {node_id}",
                         node_id=node_id, model=worker_model,
                         cwd=effective_dir)

        # Dispatch with timeout handling - Epic C
        timeout = int(os.environ.get("VALIDATION_TIMEOUT", "600"))  # 10min default

        async def _run() -> dict:
            clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            clean_env["PROJECT_TARGET_DIR"] = effective_dir
            # Apply LLM config env vars (api_key, base_url) from resolved profile
            clean_env.update(llm_config.to_env_dict())
            # Base tools for validation; extend for browser-required PRDs
            validation_tools = ["Read", "Write", "Bash", "Grep", "Glob", "ToolSearch", "Skill"]
            if getattr(self, "_validation_method_hint", None) == "browser-required":
                validation_tools.extend([
                    "mcp__claude-in-chrome__navigate",
                    "mcp__claude-in-chrome__read_page",
                    "mcp__claude-in-chrome__find",
                    "mcp__claude-in-chrome__get_page_text",
                    "mcp__claude-in-chrome__computer",
                    "mcp__claude-in-chrome__javascript_tool",
                    "mcp__claude-in-chrome__form_input",
                    "mcp__claude-in-chrome__tabs_context_mcp",
                    "mcp__claude-in-chrome__tabs_create_mcp",
                ])
            options = claude_code_sdk.ClaudeCodeOptions(  # type: ignore[attr-defined]
                system_prompt=self._build_system_prompt("validation-test-agent"),
                allowed_tools=validation_tools,
                permission_mode="bypassPermissions",
                model=worker_model,
                cwd=effective_dir,
                max_turns=100,
                env=clean_env,
            )
            messages = []
            _first_msg_logged = False
            try:
                async for msg in claude_code_sdk.query(prompt=prompt, options=options):  # type: ignore[attr-defined]
                    messages.append(msg)
                    msg_type = type(msg).__name__
                    if not _first_msg_logged and _LOGFIRE_AVAILABLE:
                        logfire.info("validation_first_message {node_id}",
                                     node_id=node_id, msg_type=msg_type)
                        _first_msg_logged = True
                    # Log tool use and text for visibility
                    if _LOGFIRE_AVAILABLE and hasattr(msg, "content") and msg_type == "AssistantMessage":
                        for block in (msg.content if isinstance(msg.content, list) else []):
                            block_type = type(block).__name__
                            if block_type == "ToolUseBlock":
                                logfire.info("validation_tool {node_id} {tool}",
                                             node_id=node_id, tool=getattr(block, "name", ""),
                                             input_preview=str(getattr(block, "input", ""))[:300])
                            elif block_type == "TextBlock":
                                text = getattr(block, "text", "")
                                if text and len(text.strip()) > 5:
                                    logfire.info("validation_text {node_id}",
                                                 node_id=node_id, text=text[:300])
                    if hasattr(msg, "result") and msg.result:  # type: ignore[union-attr]
                        result_text = str(msg.result).lower()
                        if "fail" in result_text:
                            return {"result": "fail", "reason": str(msg.result)[:300]}
            except Exception as val_exc:  # noqa: BLE001
                log.error("[validation] Stream error for %s: %s", node_id, val_exc)
                return {"result": "fail", "reason": f"Validation stream error: {str(val_exc)[:200]}"}
            return {"result": "pass", "reason": f"validation completed ({len(messages)} events)"}

        try:
            # Set timeout for the validation subprocess
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Wrap the run function with timeout
            future = loop.create_task(_run())
            signal = loop.run_until_complete(asyncio.wait_for(future, timeout=timeout))

        except asyncio.TimeoutError:
            log.error("[validation] %s timed out after %ds", node_id, timeout)
            # Write failure signal so node doesn't hang (Epic C)
            self._write_node_signal(target_node_id, {
                "status": "fail",
                "result": "fail",
                "reason": f"Validation timed out after {timeout}s",
            })
            self.active_workers.pop(node_id, None)
            self._wake_event.set()
            if _span:
                _span.__exit__(None, None, None)
            return

        except Exception as exc:  # noqa: BLE001
            log.error("[validation] %s failed with exception: %s", node_id, exc)
            # Write failure signal so node doesn't hang (Epic C)
            self._write_node_signal(target_node_id, {
                "status": "error",
                "result": "fail",
                "reason": f"Validation agent crashed: {str(exc)[:200]}",
                "validator_exit_code": -1,  # Indicate agent crash
                "exception": type(exc).__name__,
            })
            self.active_workers.pop(node_id, None)
            self._wake_event.set()
            if _span:
                _span.__exit__(None, None, None)
            return

        if _LOGFIRE_AVAILABLE:
            logfire.info("validation_complete {node_id} {result}",
                         node_id=node_id, result=signal.get("result"),
                         reason=signal.get("reason", "")[:200])

        self._write_node_signal(node_id, signal)
        self.active_workers.pop(node_id, None)
        self._wake_event.set()
        if _span:
            _span.__exit__(None, None, None)

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------

    def _process_signals(self) -> None:
        """Read signal files for active workers and apply mechanical transitions."""
        if not os.path.isdir(self.signal_dir):
            return

        for fname in sorted(os.listdir(self.signal_dir)):
            if not fname.endswith(".json"):
                continue

            # Signal filename is {node_id}.json
            node_id = fname[:-5]  # strip .json

            signal_path = os.path.join(self.signal_dir, fname)
            try:
                with open(signal_path) as fh:
                    signal = json.load(fh)
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Cannot read signal %s: %s", signal_path, exc)
                # Quarantine corrupted signals instead of silently skipping
                quarantine = os.path.join(self.signal_dir, "quarantine")
                os.makedirs(quarantine, exist_ok=True)
                corrupted_dest = os.path.join(quarantine, fname)
                try:
                    import shutil
                    shutil.move(signal_path, corrupted_dest)
                    log.error("Quarantined corrupted signal %s: %s", signal_path, exc)
                except Exception:
                    # If quarantine fails, at least log the issue
                    log.error("Failed to quarantine corrupted signal %s: %s", signal_path, exc)
                continue

            # Apply the signal BEFORE consuming it (apply-then-consume for atomicity)
            self._apply_signal(node_id, signal)

            # Now consume the signal (move to processed/) - only after successful application
            processed_dir = os.path.join(self.signal_dir, "processed")
            os.makedirs(processed_dir, exist_ok=True)
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = os.path.join(processed_dir, f"{ts}-{fname}")
            try:
                os.rename(signal_path, dest)
            except OSError:
                pass  # Signal may have already been moved by another process

    def _check_worker_liveness(self) -> None:
        """Enhanced dead worker detection using comprehensive tracking.

        IMPORTANT: Before writing any liveness error signal, check the node's
        current status in the DOT graph. If the node has already progressed past
        'active' (e.g., impl_complete, validated, accepted), the signal was already
        processed and moved to processed/ — writing an error would be a false positive.
        """
        # Use the AdvancedWorkerTracker pattern from research
        for node_id, worker_info in list(self.worker_tracker.workers.items()):
            # Check if future completed without writing signal
            if worker_info.future.done() and worker_info.state in [WorkerState.FAILED, WorkerState.COMPLETED]:
                # Guard: skip if node already progressed past active (signal was already processed)
                current_status = self._get_node_status(node_id)
                if current_status != "active":
                    log.info("[liveness] Skipping %s — node already at '%s' (signal was processed)", node_id, current_status)
                    self.worker_tracker.remove_worker(node_id)
                    continue

                signal_path = os.path.join(self.signal_dir, f"{node_id}.json")
                if not os.path.exists(signal_path):
                    exc = worker_info.exception
                    if exc:
                        log.error("[liveness] Worker %s died with exception: %s", node_id, exc)
                        self._write_node_signal(node_id, {
                            "status": "error",
                            "result": "fail",
                            "reason": f"Worker process died: {str(exc)[:300]}",
                            "worker_crash": True,
                        })
                    else:
                        # Completed without exception but no signal — worker forgot to write
                        elapsed = time.time() - worker_info.submitted_at
                        log.warning("[liveness] Worker %s completed silently after %.0fs", node_id, elapsed)
                        self._write_node_signal(node_id, {
                            "status": "error",
                            "result": "fail",
                            "reason": f"Worker completed without writing signal after {elapsed:.0f}s",
                        })

                # Clean up from tracker
                self.worker_tracker.remove_worker(node_id)

        # Also check for signal timeout using the AdvancedWorkerTracker
        self.worker_tracker.update_worker_states()

        # Process any detected dead workers
        dead_workers = self.worker_tracker.get_dead_workers()
        for node_id, worker_info in dead_workers:
            if worker_info.state in [WorkerState.TIMED_OUT, WorkerState.FAILED]:
                # Guard: skip if node already progressed past active
                current_status = self._get_node_status(node_id)
                if current_status != "active":
                    log.info("[liveness] Skipping dead worker %s — node already at '%s'", node_id, current_status)
                    self.worker_tracker.remove_worker(node_id)
                    continue

                elapsed = time.time() - worker_info.submitted_at
                timeout = int(os.environ.get("WORKER_SIGNAL_TIMEOUT", "900"))

                error_msg = f"Worker "
                if worker_info.state == WorkerState.TIMED_OUT:
                    error_msg += f"timed out after {elapsed:.0f}s (limit: {timeout}s)"
                else:
                    error_msg += f"failed: {str(worker_info.exception)[:300] if worker_info.exception else 'Unknown error'}"

                self._write_node_signal(node_id, {
                    "status": "error",
                    "result": "fail",
                    "reason": error_msg,
                    "worker_crash": True,
                    "state": worker_info.state.value
                })

                # Remove from tracking
                self.worker_tracker.remove_worker(node_id)

    def _apply_signal(self, node_id: str, signal: dict) -> None:
        """Mechanically apply a signal to the pipeline graph. No LLM involved."""
        sig_status = signal.get("status") or signal.get("result", "unknown")
        log.info("[signal] Processing signal for %s  status=%s", node_id, sig_status)
        # Clean up gate-wait marker if present (prevents monitor re-triggering on stale markers)
        gate_marker = os.path.join(self.signal_dir, f"{node_id}.gate-wait")
        if os.path.exists(gate_marker):
            try:
                os.remove(gate_marker)
                log.info("[signal] Cleaned up gate-wait marker: %s", gate_marker)
            except OSError as exc:
                log.warning("[signal] Failed to remove gate-wait marker: %s", exc)
        if _LOGFIRE_AVAILABLE:
            logfire.info("signal {node_id} → {signal_status}",
                         node_id=node_id, signal_status=sig_status,
                         signal_keys=list(signal.keys()))
        # Reload current content to get latest state
        try:
            with open(self.dot_path) as fh:
                self.dot_content = fh.read()
        except OSError:
            return

        data = parse_dot(self.dot_content)
        node = next((n for n in data["nodes"] if n["id"] == node_id), None)
        if node is None:
            log.warning("Signal for unknown node %s — ignoring", node_id)
            return

        current_status = node["attrs"].get("status", "pending")
        log.debug("Applying signal node=%s current=%s signal=%s", node_id, current_status, signal)

        # Skip signals for nodes already in terminal state (duplicate/stale signals)
        if current_status in ("accepted", "validated"):
            log.debug("[signal] %s already in terminal state %s — ignoring stale signal", node_id, current_status)
            self.active_workers.pop(node_id, None)
            return

        # --- Validation agent results ---
        if "result" in signal:
            result = signal["result"]
            if result == "pass":
                # Guard: ignore duplicate pass signals for already-terminal nodes
                if current_status in ("validated", "accepted"):
                    log.debug("[signal] %s: ignoring duplicate validation PASS (already %s)",
                              node_id, current_status)
                    self.active_workers.pop(node_id, None)
                    return
                self._do_transition(node_id, "validated")
                self._do_transition(node_id, "accepted")
                self.active_workers.pop(node_id, None)
                log.info("[signal] %s: validation PASS -> accepted", node_id)

            elif result == "fail":
                retries = self.retry_counts.get(node_id, 0) + 1
                self.retry_counts[node_id] = retries
                if retries >= MAX_RETRIES:
                    self._do_transition(node_id, "failed")
                    self.active_workers.pop(node_id, None)
                    log.error("[signal] %s: validation FAIL (retry %d/%d) -> failed permanently",
                              node_id, retries, MAX_RETRIES)
                else:
                    # Reset to pending for retry (impl_complete -> failed -> active -> pending)
                    if current_status == "impl_complete":
                        self._do_transition(node_id, "failed")
                    if current_status in ("failed", "impl_complete"):
                        self._do_transition(node_id, "active")
                    # We'll reset to pending by transitioning back
                    # Note: active -> pending is not in VALID_TRANSITIONS; we mark failed + reset
                    self.active_workers.pop(node_id, None)
                    log.warning("[signal] %s: validation FAIL (retry %d/%d) — requeuing",
                                node_id, retries, MAX_RETRIES)

            elif result == "requeue":
                requeue_target = signal.get("requeue_target", node_id)
                retries = self.retry_counts.get(requeue_target, 0) + 1
                self.retry_counts[requeue_target] = retries
                if retries < MAX_RETRIES:
                    # Transition requeue_target back to pending via failed
                    target_node = next((n for n in data["nodes"] if n["id"] == requeue_target), None)
                    if target_node:
                        t_status = target_node["attrs"].get("status", "pending")
                        if t_status in ("impl_complete", "validated", "accepted"):
                            self._do_transition(requeue_target, "failed")
                        # Force reset to pending so dispatch loop picks it up
                        self._force_status(requeue_target, "pending")
                    # Also reset the gate node itself to pending so it doesn't
                    # appear as an orphaned active gate on the next loop iteration
                    if node_id != requeue_target:
                        self._force_status(node_id, "pending")
                    log.info("[signal] %s: requeue -> %s (retry %d/%d)",
                             node_id, requeue_target, retries, MAX_RETRIES)
                self.active_workers.pop(node_id, None)

        # --- Worker result signals ---
        elif "status" in signal:
            status = signal["status"]
            if status == "success":
                handler = node["attrs"].get("handler", "")
                if current_status == "active" and handler == "tool":
                    # Tool nodes: command exit code IS the validation — skip validation agent
                    self._do_transition(node_id, "validated")
                    self._do_transition(node_id, "accepted")
                    log.info("[signal] %s: tool success -> accepted (no validation needed)", node_id)
                elif current_status == "active":
                    self._do_transition(node_id, "impl_complete")
                    log.info("[signal] %s: worker success -> impl_complete", node_id)
                    # Auto-dispatch validation agent — it owns the active_workers slot
                    # until it completes. Do NOT pop here; _run_validation_subprocess
                    # calls active_workers.pop when done, preventing the resume loop
                    # from re-dispatching validation while it is already in-flight.
                    self._dispatch_validation_agent(node_id, node_id)
                    return
                elif current_status in ("validated", "accepted"):
                    log.debug("[signal] %s already in terminal state %s — ignoring success signal", node_id, current_status)
                self.active_workers.pop(node_id, None)

            elif status in ("failed", "error"):
                handler = node["attrs"].get("handler", "")
                failure_msg = signal.get("message", "unknown error")

                if handler == "tool":
                    # Tool verify nodes: requeue the upstream codergen worker
                    # instead of retrying the tool itself
                    log.info("[signal] %s: tool verify failed — attempting upstream requeue", node_id)
                    requeued = self._requeue_upstream_worker(node_id, failure_msg, data)
                    if not requeued:
                        # No eligible upstream — mark tool as permanently failed
                        if current_status == "active":
                            self._do_transition(node_id, "failed")
                        log.error("[signal] %s: tool failed, no upstream to requeue — permanent failure",
                                  node_id)
                    self.active_workers.pop(node_id, None)
                else:
                    # Non-tool nodes (codergen/research/refine): retry the node itself
                    retries = self.retry_counts.get(node_id, 0) + 1
                    self.retry_counts[node_id] = retries
                    if retries >= MAX_RETRIES:
                        if current_status == "active":
                            self._do_transition(node_id, "failed")
                        log.error("[signal] %s: worker failed permanently (retry %d/%d)",
                                  node_id, retries, MAX_RETRIES)
                    else:
                        # Reset to pending for retry via force_status
                        self._force_status(node_id, "pending")
                        log.warning("[signal] %s: worker failed (retry %d/%d) — reset to pending for retry",
                                    node_id, retries, MAX_RETRIES)
                    self.active_workers.pop(node_id, None)

    # ------------------------------------------------------------------
    # DOT file transition helpers
    # ------------------------------------------------------------------

    def _transition(self, node_id: str, new_status: str) -> bool:
        """Apply a transition to the DOT file. Reloads content before applying.

        Returns True on success, False if transition was invalid or failed.
        The runner is the SOLE writer of the DOT file.
        """
        try:
            with open(self.dot_path) as fh:
                current_content = fh.read()
        except OSError as exc:
            log.error("Cannot read DOT for transition %s -> %s: %s", node_id, new_status, exc)
            return False

        try:
            updated_content, log_msg = apply_transition(current_content, node_id, new_status)
        except ValueError as exc:
            log.warning("Transition blocked %s -> %s: %s", node_id, new_status, exc)
            return False

        # Write back atomically
        tmp_path = self.dot_path + ".tmp"
        try:
            with open(tmp_path, "w") as fh:
                fh.write(updated_content)
            os.replace(tmp_path, self.dot_path)
            self.dot_content = updated_content
            log.info("[transition] %s", log_msg)
            return True
        except OSError as exc:
            log.error("Cannot write DOT after transition: %s", exc)
            return False

    def _do_transition(self, node_id: str, new_status: str) -> bool:
        """Alias for _transition with consistent logging prefix."""
        return self._transition(node_id, new_status)

    # ------------------------------------------------------------------
    # Signal file helpers
    # ------------------------------------------------------------------

    def _write_node_signal(self, node_id: str, payload: dict) -> str:
        """Atomically write a signal file using the temp file + rename pattern from research.

        Implements atomic signal writes with additional metadata for ordering and debugging.
        """
        os.makedirs(self.signal_dir, exist_ok=True)

        # Add metadata for ordering and debugging as per research findings
        payload["_seq"] = getattr(self, '_signal_seq', {}).get(node_id, 0) + 1
        self._signal_seq = getattr(self, '_signal_seq', {})
        self._signal_seq[node_id] = payload["_seq"]
        payload["_ts"] = datetime.datetime.utcnow().isoformat() + "Z"
        payload["_pid"] = os.getpid()

        # Create temporary file with unique name
        signal_path = os.path.join(self.signal_dir, f"{node_id}.json")
        tmp_path = Path(signal_path).with_suffix(f'.tmp.{os.getpid()}.{int(time.monotonic_ns())}')

        # Implement GAP-6.3: Include sd_hash in signal evidence (preserved from original)
        try:
            # Reload current DOT content to get node attributes
            with open(self.dot_path) as fh:
                current_content = fh.read()
            data = parse_dot(current_content)
            node = next((n for n in data["nodes"] if n["id"] == node_id), None)

            if node and node["attrs"].get("sd_path"):
                sd_path = node["attrs"]["sd_path"]
                sd_abs = os.path.join(self.dot_dir, sd_path) if not os.path.isabs(sd_path) else sd_path

                if os.path.exists(sd_abs):
                    try:
                        # Import compute function from dispatch_worker for GAP-6.3
                        from cobuilder.engine.dispatch_worker import compute_sd_hash
                        with open(sd_abs, 'r') as sd_fh:
                            sd_content = sd_fh.read()
                        payload["sd_hash"] = compute_sd_hash(sd_content)
                        payload["sd_path"] = sd_path  # Also include the path for reference
                    except ImportError:
                        # If compute_sd_hash is not available, fall back to basic approach
                        import hashlib
                        with open(sd_abs, 'r') as sd_fh:
                            sd_content = sd_fh.read()
                        payload["sd_hash"] = hashlib.sha256(sd_content.encode()).hexdigest()[:16]
                        payload["sd_path"] = sd_path
                    except Exception:
                        # If there's any error reading the SD file, continue without sd_hash
                        pass
        except Exception:
            # If there's any error looking up node attributes, continue without sd_hash
            pass

        try:
            # Write to temporary file
            with open(tmp_path, 'w') as fh:
                json.dump(payload, fh, indent=2)
                fh.flush()  # Flush to OS buffer
                os.fsync(fh.fileno())  # Force OS to write to disk

            # Atomically rename (POSIX atomic operation)
            os.rename(str(tmp_path), str(signal_path))

            log.debug("Signal written: %s = %s", signal_path, payload)
            return str(signal_path)

        except Exception as e:
            # Clean up temp file if something went wrong
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except:
                    pass  # Ignore cleanup errors
            raise e

    # ------------------------------------------------------------------
    # Checkpoint
    # ------------------------------------------------------------------

    def _save_checkpoint(self, stage: str = "progress") -> None:
        """Save a checkpoint of the current DOT file state."""
        try:
            result = save_checkpoint(self.dot_path)
            log.info("[checkpoint] Saved at stage=%s path=%s",
                     stage, result.get("checkpoint_path", "?"))
        except Exception as exc:  # noqa: BLE001
            log.warning("[checkpoint] Failed to save: %s", exc)

    # ------------------------------------------------------------------
    # Resume helper
    # ------------------------------------------------------------------

    def _reset_active_nodes(self) -> None:
        """On a fresh (non-resume) start, reset any 'active' nodes back to 'pending'.

        Workers may have crashed mid-run leaving nodes stuck in 'active'.
        """
        try:
            with open(self.dot_path) as fh:
                content = fh.read()
        except OSError:
            return

        data = parse_dot(content)
        for node in data["nodes"]:
            if node["attrs"].get("status") == "active":
                nid = node["id"]
                handler = node["attrs"].get("handler", "")
                log.info("[reset] Resetting active node %s -> pending (fresh start)", nid)
                if handler in ("wait.system3", "wait.human", "gate"):
                    # Gate nodes have no running worker — they were just waiting.
                    # Transition active→failed, then failed→pending so the gate
                    # can be re-dispatched cleanly. Both transitions go through
                    # apply_transition which handles the specific node's status.
                    try:
                        content, _ = apply_transition(content, nid, "failed")
                        content, _ = apply_transition(content, nid, "pending")
                    except ValueError:
                        pass
                else:
                    try:
                        content, _ = apply_transition(content, nid, "failed")
                        # Note: we can't go failed->pending directly; leave as failed
                        # The dispatcher will skip non-pending nodes
                    except ValueError:
                        pass

        tmp_path = self.dot_path + ".tmp"
        try:
            with open(tmp_path, "w") as fh:
                fh.write(content)
            os.replace(tmp_path, self.dot_path)
            self.dot_content = content
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    # Handler-specific preambles: tell workers their role and how to use MCP tools
    HANDLER_PREAMBLES: dict[str, str] = {
        "codergen": (
            "## Your Role: IMPLEMENTATION Worker\n"
            "You write production-quality code. Do NOT research or investigate — only implement.\n"
            "Read the Solution Design carefully. It contains the exact changes to make.\n\n"
            "### MANDATORY FIRST STEP: Load Code Navigation Tools\n"
            "Before writing ANY code, run these ToolSearch calls to load MCP tools:\n"
            "```\n"
            "ToolSearch(query=\"serena\")     # Code navigation: find_symbol, get_symbols_overview, search_for_pattern\n"
            "ToolSearch(query=\"hindsight\")  # Memory: recall past patterns and retain learnings\n"
            "```\n"
            "Once loaded, use Serena to explore the codebase BEFORE editing.\n"
            "Use `mcp__hindsight__recall()` to check for known patterns in this project.\n"
            "Use `mcp__hindsight__retain()` after completing work to store learnings.\n\n"
            "Done when: All files changed, tests pass, signal written with files_changed list."
        ),
        "research": (
            "## Your Role: RESEARCH Worker\n"
            "You investigate and document findings. Do NOT modify source code.\n"
            "Write findings to a NEW markdown file (not the SD) at the evidence directory.\n"
            "Use WebSearch, WebFetch, and Read to gather information.\n\n"
            "### MCP Tools: Use ToolSearch to Discover Available Tools\n"
            "You have access to MCP tools for research — use ToolSearch to discover them:\n"
            "- Search `ToolSearch(query=\"context7\")` to find documentation lookup tools\n"
            "- Search `ToolSearch(query=\"perplexity\")` to find web research tools\n"
            "- Search `ToolSearch(query=\"hindsight\")` to find memory/learning tools\n"
            "ToolSearch loads tool schemas into your context. Once loaded, call them directly.\n\n"
            "Done when: Research doc written with findings. Signal written with doc path."
        ),
        "refine": (
            "## Your Role: REFINEMENT Worker\n"
            "You merge research findings into the Solution Design document.\n"
            "Read predecessor signal files to find research doc paths.\n"
            "Edit the SD to incorporate findings as first-class content (not annotations).\n\n"
            "### MCP Tools: Use ToolSearch to Discover Available Tools\n"
            "You have access to MCP tools — use ToolSearch to discover them:\n"
            "- Search `ToolSearch(query=\"hindsight\")` to find memory tools (reflect before editing, retain after)\n"
            "- Search `ToolSearch(query=\"perplexity\")` if you need to reason through conflicting findings\n"
            "ToolSearch loads tool schemas into your context. Once loaded, call them directly.\n\n"
            "Done when: SD updated with research findings integrated. No annotations remain."
        ),
        "acceptance-test-writer": (
            "## Your Role: TEST WRITER\n"
            "You create Gherkin acceptance test scenarios from PRD acceptance criteria.\n"
            "Write .feature files with Given/When/Then. Tests should be blind (not peek at implementation).\n\n"
            "### MANDATORY FIRST STEP: Load Code Navigation Tools\n"
            "Run `ToolSearch(query=\"serena\")` to load code navigation tools.\n"
            "Use Serena to understand the codebase structure before writing tests.\n\n"
            "Done when: Feature files written covering all PRD acceptance criteria."
        ),
    }

    def _build_worker_prompt(self, node: dict, data: dict) -> str:
        """Build a task prompt for a worker from node attributes."""
        attrs = node["attrs"]
        nid = node["id"]
        handler = attrs.get("handler", "")
        label = attrs.get("label", nid).replace("\\n", " ")
        acceptance = attrs.get("acceptance", "")
        prd_ref = attrs.get("prd_ref", data.get("graph_attrs", {}).get("prd_ref", ""))
        solution_design_path = attrs.get("sd_path", "") or attrs.get("solution_design", "")
        bead_id = attrs.get("bead_id", "")

        # Inline solution design content if file exists
        # Try repo root first (most SD paths are relative to repo root), then dot_dir as fallback
        solution_design_content = ""
        if solution_design_path:
            candidates = []
            if not os.path.isabs(solution_design_path):
                # Try repo root first (SD paths like docs/sds/... are relative to repo root)
                repo_root = self._get_repo_root()
                candidates.append(os.path.join(repo_root, solution_design_path))
                # Then target_dir and dot_dir as fallbacks
                target = self._get_target_dir()
                if target != repo_root:
                    candidates.append(os.path.join(target, solution_design_path))
                candidates.append(os.path.join(self.dot_dir, solution_design_path))
            else:
                candidates.append(solution_design_path)
            for sd_abs in candidates:
                if os.path.exists(sd_abs):
                    try:
                        with open(sd_abs) as fh:
                            solution_design_content = fh.read()
                        break
                    except OSError:
                        pass

        lines = [
            f"# Task: {label}",
            f"Node ID: {nid}",
            f"Handler: {handler}",
        ]

        # Add handler-specific preamble (role, MCP tool loading instructions)
        preamble = self.HANDLER_PREAMBLES.get(handler, "")
        if preamble:
            lines.append(f"\n{preamble}")

        # Inject project directory so workers know where to operate
        resolved_dir = self._resolve_target_dir(attrs)
        lines.append(
            f"\n## Project Directory — MANDATORY\n"
            f"Your working directory is: `{resolved_dir}`\n"
            f"This is also available as `$PROJECT_TARGET_DIR` env var.\n"
            f"ALL file operations (Read, Edit, Write, Glob, Grep, Bash) MUST target files within this directory.\n"
            f"Do NOT navigate to or operate in any other directory.\n"
            f"Use `Bash(command=\"pwd\")` to confirm your working directory if unsure."
        )

        if prd_ref:
            lines.append(f"PRD: {prd_ref}")
        if bead_id:
            lines.append(f"Bead ID: {bead_id}")
        if acceptance:
            lines.append(f"\n## Acceptance Criteria\n{acceptance}")
        if solution_design_content:
            lines.append(f"\n## Solution Design\n{solution_design_content}")
        else:
            lines.append(f"\n## Solution Design Path\n{solution_design_path or '(none)'}")

        # Inject failure guidance if this is a requeued node
        # Persisted file is authoritative (written at requeue time, survives restarts).
        # In-memory dict is fallback for same-process retries before file is written.
        guidance = self._load_persisted_guidance(nid)
        if not guidance:
            guidance = self.requeue_guidance.pop(nid, None)
        if guidance:
            lines.append(
                f"\n## IMPORTANT: Previous Attempt Failed\n"
                f"{guidance}\n"
                f"Focus specifically on fixing the issue described above."
            )

        # Resolve signal path at prompt-build time so worker gets the absolute path
        signal_file_path = os.path.join(self.signal_dir, f"{nid}.json")

        lines.append(
            f"\n## Signal Protocol — MANDATORY on completion\n"
            f"When your task is done (success or failure), write a signal file.\n\n"
            f"Signal file path (absolute): {signal_file_path}\n\n"
            f"Use Write (this is a NEW file):\n"
            f'```\n'
            f'Write(file_path="{signal_file_path}", content=\'{{"status": "success", "files_changed": ["file1.py"], "message": "brief description"}}\')\n'
            f'```\n\n'
            f"On failure:\n"
            f'```\n'
            f'Write(file_path="{signal_file_path}", content=\'{{"status": "error", "message": "what went wrong", "files_changed": []}}\')\n'
            f'```\n\n'
            f"IMPORTANT: Use this EXACT path. Do NOT construct your own path.\n"
            f"For modifying existing source code files, ALWAYS use Edit (not Write)."
        )

        return "\n".join(lines)

    def _build_system_prompt(self, worker_type: str) -> str:
        """Load system prompt from .claude/agents/{worker_type}.md + tool reference."""
        # Use repo root for agent files (they live at <repo>/.claude/agents/)
        repo_root = self._get_repo_root()
        agents_dir = os.path.join(repo_root, ".claude", "agents")

        # Always load tool reference — this is critical for smaller models
        tool_ref = ""
        tool_ref_file = os.path.join(agents_dir, "worker-tool-reference.md")
        if os.path.exists(tool_ref_file):
            try:
                with open(tool_ref_file) as fh:
                    raw = fh.read()
                # Strip frontmatter
                if raw.startswith("---"):
                    _, _, rest = raw.partition("---")
                    _, _, raw = rest.partition("---")
                tool_ref = raw.strip()
            except OSError:
                pass

        # Load role-specific prompt
        role_content = ""
        role_file = os.path.join(agents_dir, f"{worker_type}.md")
        if os.path.exists(role_file):
            try:
                with open(role_file) as fh:
                    content = fh.read()
                # Strip frontmatter
                if content.startswith("---"):
                    _, _, rest = content.partition("---")
                    _, _, content = rest.partition("---")
                role_content = content.strip()
            except OSError:
                pass

        if not role_content:
            role_content = f"You are a specialist agent ({worker_type}). Implement features directly using the provided tools."

        # Tool reference goes FIRST so it's always visible, even if role prompt is long
        if tool_ref:
            return f"{tool_ref}\n\n---\n\n{role_content}"
        return role_content


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Pure Python DOT pipeline runner. Zero LLM tokens for graph traversal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a pipeline from scratch:
  python3 pipeline_runner.py --dot-file .claude/attractor/examples/simple-pipeline.dot

  # Resume a pipeline (don't reset active nodes):
  python3 pipeline_runner.py --dot-file pipeline.dot --resume

  # Check imports work:
  python3 -c "from cobuilder.engine.pipeline_runner import PipelineRunner; print('Import OK')"
        """,
    )
    ap.add_argument(
        "--dot-file",
        required=True,
        metavar="FILE",
        help="Path to the .dot pipeline file (required).",
    )
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Resume from current state (don't reset active nodes to pending).",
    )

    args = ap.parse_args()

    dot_path = os.path.abspath(args.dot_file)
    if not os.path.exists(dot_path):
        print(f"Error: DOT file not found: {dot_path}", file=sys.stderr)
        sys.exit(1)

    runner = PipelineRunner(dot_path=dot_path, resume=args.resume)

    success = runner.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
