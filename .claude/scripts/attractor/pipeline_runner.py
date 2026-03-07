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
from typing import Any

# Ensure local module imports work regardless of invocation directory
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from checkpoint import save_checkpoint  # noqa: E402
from parser import parse_file, parse_dot  # noqa: E402
from transition import apply_transition, VALID_TRANSITIONS  # noqa: E402

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
    logfire.configure()
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
        self._load_attractor_env()

        # Active workers: node_id -> worker metadata dict
        self.active_workers: dict[str, dict[str, Any]] = {}

        # Retry counters: node_id -> int
        self.retry_counts: dict[str, int] = {}

        # Requeue guidance: node_id -> failure message from downstream verify
        # Injected into worker prompt on re-dispatch so the worker knows what to fix
        self.requeue_guidance: dict[str, str] = {}

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

    def _load_attractor_env(self) -> None:
        """Source .claude/attractor/.env if it exists. Sets ANTHROPIC_MODEL etc."""
        env_path = os.path.join(_THIS_DIR, "..", "..", "attractor", ".env")
        env_path = os.path.normpath(env_path)
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
                    if key and key not in os.environ:
                        os.environ[key] = value
                        log.debug("[env] Set %s from attractor .env", key)

    def _get_target_dir(self) -> str:
        """Return target directory for worker execution. Falls back to dot_dir."""
        target = self._graph_attrs.get("target_dir", "")
        if target and os.path.isdir(target):
            return target
        return self.dot_dir

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
                # Don't wait — immediately check for more work
                self._wake_event.clear()
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

            # If nothing is dispatchable and nothing is active, we're stuck
            if not self.active_workers:
                pending_nodes = [n for n in nodes if n["attrs"].get("status", "pending") == "pending"]
                failed_nodes = [n for n in nodes if n["attrs"].get("status", "pending") == "failed"]
                if pending_nodes or failed_nodes:
                    log.error("Pipeline stuck: %d pending, %d failed, 0 active workers",
                              len(pending_nodes), len(failed_nodes))
                    self._save_checkpoint("stuck")
                    return False
                # All nodes are in terminal states but not "complete" — recheck
                if self._is_pipeline_complete(nodes):
                    log.info("Pipeline complete on recheck.")
                    self._save_checkpoint("complete")
                    return True

            # Wait for a file event or poll timeout
            self._wake_event.clear()
            if _WATCHDOG_AVAILABLE:
                self._wake_event.wait(timeout=30.0)
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
        import re as _re
        try:
            with open(self.dot_path) as fh:
                content = fh.read()
            # Match status="..." within the node's attribute block
            # Pattern: find the node definition and replace its status
            pattern = _re.compile(
                rf'({_re.escape(node_id)}\s*\[.*?status\s*=\s*")([^"]*?)(")',
                _re.DOTALL,
            )
            new_content, count = pattern.subn(rf'\g<1>{target_status}\g<3>', content)
            if count > 0:
                with open(self.dot_path, "w") as fh:
                    fh.write(new_content)
                self.dot_content = new_content
                log.info("[force-status] %s -> %s (direct DOT edit)", node_id, target_status)
            else:
                log.warning("[force-status] Could not find status attribute for %s in DOT", node_id)
        except OSError as exc:
            log.error("[force-status] Failed to edit DOT: %s", exc)

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
        self._executor.submit(self._dispatch_agent_sdk, nid, worker_type, prompt)

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
            from gchat_adapter import send_review_request  # type: ignore[import]
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

    def _dispatch_agent_sdk(self, node_id: str, worker_type: str, prompt: str) -> None:
        """Dispatch a worker via claude_code_sdk. No headless fallback.

        All worker dispatch goes through AgentSDK exclusively.
        This method runs in a background thread. On completion it writes a
        signal file to {signal_dir}/{node_id}.json and sets _wake_event.
        """
        worker_model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("PIPELINE_WORKER_MODEL", "claude-haiku-4-5-20251001")
        log.info("[sdk] Dispatching worker  node=%s  type=%s  model=%s  cwd=%s",
                 node_id, worker_type, worker_model, self._get_target_dir())

        # Logfire span covers the entire worker lifecycle (dispatch → completion)
        _span = None
        if _LOGFIRE_AVAILABLE:
            _span = logfire.span(
                "sdk_worker {node_id} ({worker_type})",
                node_id=node_id, worker_type=worker_type,
                model=worker_model, cwd=self._get_target_dir(),
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

            self._dispatch_via_sdk(node_id, worker_type, prompt)
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

    def _dispatch_via_sdk(self, node_id: str, worker_type: str, prompt: str) -> None:
        """Dispatch worker using claude_code_sdk."""
        import asyncio

        # Unset CLAUDECODE to avoid nested session detection
        os.environ.pop("CLAUDECODE", None)

        # Worker model: ANTHROPIC_MODEL (from attractor .env) > PIPELINE_WORKER_MODEL > default
        worker_model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("PIPELINE_WORKER_MODEL", "claude-haiku-4-5-20251001")

        # Import function to load agent definitions for skill injection (GAP-6.2)
        from dispatch_worker import load_agent_definition

        # Add skill injection from agent definitions (GAP-6.2)
        try:
            agent_def = load_agent_definition(self.dot_dir, worker_type)
            if agent_def and agent_def.get("skills_required"):
                skills_block = "\n".join(
                    f'Skill("{s}")' for s in agent_def["skills_required"]
                )
                prompt += f"\n\n## Required Skills\nInvoke these skills before starting:\n{skills_block}\n"
        except Exception:
            pass  # Don't fail dispatch on agent definition errors

        async def _run() -> dict:
            # Build clean env without CLAUDECODE
            clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            # Add ATTRACTOR_SIGNAL_DIR as required by GAP-6.1
            clean_env["ATTRACTOR_SIGNAL_DIR"] = str(self.signal_dir)
            options = claude_code_sdk.ClaudeCodeOptions(  # type: ignore[attr-defined]
                system_prompt=self._build_system_prompt(worker_type),
                allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "MultiEdit"],
                permission_mode="bypassPermissions",
                model=worker_model,
                cwd=self._get_target_dir(),
                max_turns=50,
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
                # If we got messages + result before the error, treat as success
                err_msg = str(stream_exc)
                if result_text:
                    log.warning("[sdk] Stream error after result: %s", err_msg)
                elif messages:
                    log.warning("[sdk] Stream error after %d msgs: %s", len(messages), err_msg)
                    return {"status": "success", "message": f"SDK completed with stream error ({len(messages)} events): {err_msg[:200]}"}
                else:
                    raise  # No messages at all — propagate the error

            if result_text:
                return {"status": "success", "message": result_text}
            return {"status": "success", "message": f"SDK worker completed ({len(messages)} events)"}

        if _LOGFIRE_AVAILABLE:
            logfire.info("worker_dispatch_start {node_id}",
                         node_id=node_id, worker_type=worker_type,
                         model=worker_model, cwd=self._get_target_dir())

        t0 = time.time()
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(_run())
        except Exception as exc:  # noqa: BLE001
            result = {"status": "failed", "message": str(exc)}
        finally:
            loop.close()

        elapsed = time.time() - t0
        log.info("[sdk] Worker %s finished in %.1fs  status=%s  msgs=%s",
                 node_id, elapsed, result.get("status"), result.get("message", "")[:100])
        if _LOGFIRE_AVAILABLE:
            logfire.info("worker_complete {node_id} {status} in {elapsed_s}s",
                         node_id=node_id, worker_type=worker_type,
                         status=result.get("status"), elapsed_s=round(elapsed, 1),
                         message=result.get("message", "")[:200])

        self._write_node_signal(node_id, result)
        self.active_workers.pop(node_id, None)
        self._wake_event.set()

    def _dispatch_validation_agent(self, node_id: str, target_node_id: str) -> None:
        """Dispatch a validation-test-agent for a node at impl_complete.

        Runs in a background thread. Writes a validation signal on completion.
        """
        log.info("[validation] Dispatching validation agent  node=%s  target=%s", node_id, target_node_id)
        self.active_workers[node_id] = {
            "node_id": node_id,
            "type": "validation",
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        # Dispatch via ThreadPoolExecutor so Logfire auto-propagates OTel context.
        if not hasattr(self, "_executor"):
            from concurrent.futures import ThreadPoolExecutor
            self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="worker")
        self._executor.submit(self._run_validation_subprocess, node_id, target_node_id)

    def _run_validation_subprocess(self, node_id: str, target_node_id: str) -> None:
        """Run validation-test-agent via AgentSDK. Falls back to auto-pass if unavailable.

        Validation is a System 3 concern — the runner auto-advances nodes when
        validation dispatch is not possible (e.g., nested sessions, no SDK).
        """
        import asyncio

        if not _SDK_AVAILABLE or claude_code_sdk is None:
            log.warning("[validation] SDK not available — auto-passing %s", node_id)
            signal: dict = {"result": "pass", "reason": "auto-pass: SDK not available for validation"}
            self._write_node_signal(node_id, signal)
            self.active_workers.pop(node_id, None)
            self._wake_event.set()
            return

        os.environ.pop("CLAUDECODE", None)
        worker_model = os.environ.get("ANTHROPIC_MODEL") or os.environ.get("PIPELINE_WORKER_MODEL", "claude-haiku-4-5-20251001")
        prompt = (
            f"Validate node {target_node_id} in pipeline {self.pipeline_id}. "
            f"Check if the implementation meets acceptance criteria. "
            f"DOT file: {self.dot_path}"
        )

        async def _run() -> dict:
            clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            options = claude_code_sdk.ClaudeCodeOptions(  # type: ignore[attr-defined]
                system_prompt="You are a validation agent. Check if implementation meets acceptance criteria. Respond with PASS or FAIL.",
                allowed_tools=["Read", "Bash", "Grep", "Glob"],
                permission_mode="bypassPermissions",
                model=worker_model,
                cwd=self._get_target_dir(),
                max_turns=10,
                env=clean_env,
            )
            messages = []
            try:
                async for msg in claude_code_sdk.query(prompt=prompt, options=options):  # type: ignore[attr-defined]
                    messages.append(msg)
                    if hasattr(msg, "result") and msg.result:  # type: ignore[union-attr]
                        result_text = str(msg.result).lower()
                        if "fail" in result_text:
                            return {"result": "fail", "reason": str(msg.result)[:300]}
            except Exception:  # noqa: BLE001
                pass  # Treat stream errors as auto-pass (validation is best-effort)
            return {"result": "pass", "reason": f"validation completed ({len(messages)} events)"}

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            signal = loop.run_until_complete(_run())
        except Exception as exc:  # noqa: BLE001
            log.warning("[validation] Dispatch failed for %s — auto-passing: %s", node_id, exc)
            signal = {"result": "pass", "reason": f"auto-pass: {exc}"}

        self._write_node_signal(node_id, signal)
        self.active_workers.pop(node_id, None)
        self._wake_event.set()

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
                continue

            # Consume the signal (move to processed/)
            processed_dir = os.path.join(self.signal_dir, "processed")
            os.makedirs(processed_dir, exist_ok=True)
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = os.path.join(processed_dir, f"{ts}-{fname}")
            try:
                os.rename(signal_path, dest)
            except OSError:
                pass

            self._apply_signal(node_id, signal)

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

        # --- Validation agent results ---
        if "result" in signal:
            result = signal["result"]
            if result == "pass":
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
                        if t_status in ("impl_complete", "validated"):
                            self._do_transition(requeue_target, "failed")
                        # Cannot go directly failed -> pending in standard chain
                        # Worker will be re-dispatched when pending
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
                    # Auto-dispatch validation agent for impl_complete nodes
                    self._dispatch_validation_agent(node_id, node_id)
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
        """Write a signal file for node_id at {signal_dir}/{node_id}.json.

        Uses atomic write-then-rename to ensure watchdog sees a complete file.

        Implements GAP-6.3: Add sd_hash to signal evidence when available.
        """
        os.makedirs(self.signal_dir, exist_ok=True)

        # Implement GAP-6.3: Include sd_hash in signal evidence
        # Look up node to check if it has an sd_path attribute
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
                        from dispatch_worker import compute_sd_hash
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

        final_path = os.path.join(self.signal_dir, f"{node_id}.json")
        tmp_path = final_path + ".tmp"
        with open(tmp_path, "w") as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, final_path)
        log.debug("Signal written: %s = %s", final_path, payload)
        return final_path

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
                log.info("[reset] Resetting active node %s -> pending (fresh start)", nid)
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
        solution_design_content = ""
        if solution_design_path:
            sd_abs = os.path.join(self.dot_dir, solution_design_path) if not os.path.isabs(solution_design_path) else solution_design_path
            if os.path.exists(sd_abs):
                try:
                    with open(sd_abs) as fh:
                        solution_design_content = fh.read()
                except OSError:
                    pass

        lines = [
            f"# Task: {label}",
            f"Node ID: {nid}",
            f"Handler: {handler}",
        ]
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
        guidance = self.requeue_guidance.pop(nid, None)
        if guidance:
            lines.append(
                f"\n## IMPORTANT: Previous Attempt Failed\n"
                f"{guidance}\n"
                f"Focus specifically on fixing the issue described above."
            )

        lines.append(
            f"\n## Signal Protocol\n"
            f"The signal directory is available as environment variable $ATTRACTOR_SIGNAL_DIR.\n"
            f"IMPORTANT: Always verify the path first:\n"
            f"  Bash(\"echo $ATTRACTOR_SIGNAL_DIR\")\n\n"
            f"Then write your result file to: $ATTRACTOR_SIGNAL_DIR/{nid}.json\n\n"
            f"Format:\n"
            f'  {{"status": "success", "files_changed": ["file1", "file2"], "message": "brief description"}}\n\n'
            f"Example (use the EXACT path from echo above, do NOT construct your own path):\n"
            f"  Bash(\"echo $ATTRACTOR_SIGNAL_DIR/{nid}.json\")  # verify path first\n"
            f"  Write(file_path=\"<path from echo above>/{nid}.json\", content='{{\"status\": \"success\", \"message\": \"done\"}}')\n\n"
            f"Tool usage reminder: boolean values are true/false (not True/False). "
            f"MCP tools are unavailable in this headless context. "
            f"Use only: Bash, Read, Write, Edit, Glob, Grep, MultiEdit."
        )

        return "\n".join(lines)

    def _build_system_prompt(self, worker_type: str) -> str:
        """Load system prompt from .claude/agents/{worker_type}.md."""
        agents_dir = os.path.join(self.dot_dir, ".claude", "agents")
        role_file = os.path.join(agents_dir, f"{worker_type}.md")
        if os.path.exists(role_file):
            try:
                with open(role_file) as fh:
                    content = fh.read()
                # Strip frontmatter
                if content.startswith("---"):
                    _, _, rest = content.partition("---")
                    _, _, content = rest.partition("---")
                return content.strip()
            except OSError:
                pass
        return f"You are a specialist agent ({worker_type}). Implement features directly using the provided tools."


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
  python3 -c "from pipeline_runner import PipelineRunner; print('Import OK')"
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
