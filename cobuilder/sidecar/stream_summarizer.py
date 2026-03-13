"""Stream Summarizer — lightweight sidecar that watches pipeline signals.

Monitors signal files in a directory and produces rolling JSON summaries.
Designed to run as a standalone process alongside a pipeline runner.

Usage:
    python -m cobuilder.sidecar.stream_summarizer \
        --signals-dir /path/to/signals \
        --output /path/to/summary.json \
        [--dot-file /path/to/pipeline.dot] \
        [--interval 60]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_S = 60
_MAX_EVENTS = 50
_RUNNING = True


def _handle_signal(signum: int, frame: Any) -> None:
    global _RUNNING
    _RUNNING = False


@dataclass
class PipelineSummary:
    """Rolling summary of pipeline execution state."""
    pipeline_id: str = ""
    timestamp: str = ""
    nodes_completed: int = 0
    nodes_total: int = 0
    nodes_failed: int = 0
    current_activity: str = ""
    key_events: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    signal_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_id": self.pipeline_id,
            "timestamp": self.timestamp,
            "nodes_completed": self.nodes_completed,
            "nodes_total": self.nodes_total,
            "nodes_failed": self.nodes_failed,
            "current_activity": self.current_activity,
            "key_events": self.key_events[-10:],  # Last 10 events
            "blockers": self.blockers,
            "elapsed_seconds": self.elapsed_seconds,
            "signal_count": self.signal_count,
        }


class StreamSummarizer:
    """Watches signal files and produces rolling summaries.

    This is a simple file-watching summarizer that does NOT require an LLM.
    It reads signal files, tracks state, and writes structured JSON summaries.

    For LLM-based summarization (Haiku), the caller can post-process the
    summary JSON through a cheap model.
    """

    def __init__(
        self,
        signals_dir: str | Path,
        output_path: str | Path,
        dot_file: str | Path | None = None,
        interval_s: float = _DEFAULT_INTERVAL_S,
    ) -> None:
        self.signals_dir = Path(signals_dir)
        self.output_path = Path(output_path)
        self.dot_file = Path(dot_file) if dot_file else None
        self.interval_s = interval_s

        self._events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
        self._seen_signals: set[str] = set()
        self._start_time = time.monotonic()
        self._summary = PipelineSummary()

        # Parse DOT for node count if available
        if self.dot_file and self.dot_file.exists():
            self._summary.pipeline_id = self.dot_file.stem
            self._count_nodes_from_dot()

    def _count_nodes_from_dot(self) -> None:
        """Count nodes from DOT file for progress tracking."""
        try:
            import re
            content = self.dot_file.read_text()
            # Count node definitions (word followed by [attrs])
            nodes = re.findall(r'^\s+(\w+)\s*\[', content, re.MULTILINE)
            # Exclude defaults and graph keywords
            excluded = {"node", "edge", "graph", "digraph", "subgraph"}
            real_nodes = [n for n in nodes if n not in excluded]
            self._summary.nodes_total = len(real_nodes)
        except Exception:
            pass

    def scan_signals(self) -> list[dict[str, Any]]:
        """Scan for new signal files and return parsed events."""
        new_events: list[dict[str, Any]] = []

        if not self.signals_dir.exists():
            return new_events

        for sig_file in sorted(self.signals_dir.glob("*.json")):
            if sig_file.name in self._seen_signals:
                continue
            self._seen_signals.add(sig_file.name)

            try:
                data = json.loads(sig_file.read_text())
                event = {
                    "file": sig_file.name,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "signal_type": data.get("signal_type", "unknown"),
                    "node_id": data.get("node_id", data.get("payload", {}).get("node_id", "")),
                    "status": data.get("status", ""),
                    "source": data.get("source", ""),
                }
                new_events.append(event)
                self._events.append(event)
            except (json.JSONDecodeError, OSError) as exc:
                logger.debug("Failed to parse signal file %s: %s", sig_file, exc)

        return new_events

    def update_summary(self) -> PipelineSummary:
        """Update the rolling summary from accumulated events."""
        self._summary.timestamp = datetime.now(timezone.utc).isoformat()
        self._summary.elapsed_seconds = time.monotonic() - self._start_time
        self._summary.signal_count = len(self._seen_signals)

        # Count completed/failed nodes from events
        completed_nodes: set[str] = set()
        failed_nodes: set[str] = set()
        latest_activity = ""

        for event in self._events:
            node_id = event.get("node_id", "")
            sig_type = event.get("signal_type", "")

            if sig_type in ("NODE_COMPLETE", "VALIDATION_PASSED", "complete"):
                completed_nodes.add(node_id)
                failed_nodes.discard(node_id)
            elif sig_type in ("VALIDATION_FAILED", "failed", "ORCHESTRATOR_CRASHED"):
                failed_nodes.add(node_id)
            elif node_id:
                latest_activity = f"Working on: {node_id} ({sig_type})"

        self._summary.nodes_completed = len(completed_nodes)
        self._summary.nodes_failed = len(failed_nodes)
        if latest_activity:
            self._summary.current_activity = latest_activity

        # Key events — last 10
        self._summary.key_events = [
            f"{e['timestamp'][:19]} {e['signal_type']} {e['node_id']}"
            for e in list(self._events)[-10:]
        ]

        # Blockers
        self._summary.blockers = [
            f"Node '{nid}' failed"
            for nid in sorted(failed_nodes)
        ]

        return self._summary

    def write_summary(self) -> None:
        """Write the current summary to the output file."""
        summary = self.update_summary()
        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            # Atomic write
            tmp_path = self.output_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(summary.to_dict(), indent=2))
            tmp_path.rename(self.output_path)
        except OSError as exc:
            logger.warning("Failed to write summary: %s", exc)

    def run_loop(self) -> None:
        """Main monitoring loop — runs until SIGTERM or SIGINT."""
        global _RUNNING
        logger.info(
            "Stream summarizer started: signals=%s output=%s interval=%ds",
            self.signals_dir, self.output_path, self.interval_s,
        )

        while _RUNNING:
            new_events = self.scan_signals()
            if new_events:
                logger.debug("Found %d new signal(s)", len(new_events))
            self.write_summary()
            time.sleep(self.interval_s)

        # Final write
        self.write_summary()
        logger.info("Stream summarizer stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline stream summarizer sidecar"
    )
    parser.add_argument(
        "--signals-dir", required=True,
        help="Directory to watch for signal files",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write summary JSON",
    )
    parser.add_argument(
        "--dot-file", default=None,
        help="Optional DOT file for node count",
    )
    parser.add_argument(
        "--interval", type=float, default=_DEFAULT_INTERVAL_S,
        help="Poll interval in seconds (default: 60)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    summarizer = StreamSummarizer(
        signals_dir=args.signals_dir,
        output_path=args.output,
        dot_file=args.dot_file,
        interval_s=args.interval,
    )
    summarizer.run_loop()


if __name__ == "__main__":
    main()
