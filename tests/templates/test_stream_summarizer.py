"""Tests for cobuilder.sidecar.stream_summarizer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestStreamSummarizer:
    def test_scan_empty_signals_dir(self, tmp_path: Path) -> None:
        from cobuilder.sidecar.stream_summarizer import StreamSummarizer

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        summarizer = StreamSummarizer(
            signals_dir=signals_dir,
            output_path=tmp_path / "summary.json",
        )
        events = summarizer.scan_signals()
        assert events == []

    def test_scan_finds_new_signals(self, tmp_path: Path) -> None:
        from cobuilder.sidecar.stream_summarizer import StreamSummarizer

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        # Write a signal file
        signal = {
            "signal_type": "NODE_COMPLETE",
            "node_id": "impl_auth",
            "source": "runner",
        }
        (signals_dir / "signal-001.json").write_text(json.dumps(signal))

        summarizer = StreamSummarizer(
            signals_dir=signals_dir,
            output_path=tmp_path / "summary.json",
        )
        events = summarizer.scan_signals()
        assert len(events) == 1
        assert events[0]["signal_type"] == "NODE_COMPLETE"
        assert events[0]["node_id"] == "impl_auth"

    def test_scan_ignores_already_seen(self, tmp_path: Path) -> None:
        from cobuilder.sidecar.stream_summarizer import StreamSummarizer

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        signal = {"signal_type": "NODE_COMPLETE", "node_id": "impl_auth"}
        (signals_dir / "signal-001.json").write_text(json.dumps(signal))

        summarizer = StreamSummarizer(
            signals_dir=signals_dir,
            output_path=tmp_path / "summary.json",
        )
        # First scan finds it
        events1 = summarizer.scan_signals()
        assert len(events1) == 1

        # Second scan skips it
        events2 = summarizer.scan_signals()
        assert len(events2) == 0

    def test_update_summary_tracks_completed(self, tmp_path: Path) -> None:
        from cobuilder.sidecar.stream_summarizer import StreamSummarizer

        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        for i, sig_type in enumerate(["NODE_COMPLETE", "NODE_COMPLETE", "failed"]):
            signal = {"signal_type": sig_type, "node_id": f"node_{i}"}
            (signals_dir / f"signal-{i:03d}.json").write_text(json.dumps(signal))

        summarizer = StreamSummarizer(
            signals_dir=signals_dir,
            output_path=tmp_path / "summary.json",
        )
        summarizer.scan_signals()
        summary = summarizer.update_summary()

        assert summary.nodes_completed == 2
        assert summary.nodes_failed == 1

    def test_write_summary_creates_file(self, tmp_path: Path) -> None:
        from cobuilder.sidecar.stream_summarizer import StreamSummarizer

        output = tmp_path / "summary.json"
        summarizer = StreamSummarizer(
            signals_dir=tmp_path / "signals",
            output_path=output,
        )
        (tmp_path / "signals").mkdir()

        summarizer.write_summary()
        assert output.exists()

        data = json.loads(output.read_text())
        assert "timestamp" in data
        assert "nodes_completed" in data

    def test_counts_nodes_from_dot(self, tmp_path: Path) -> None:
        from cobuilder.sidecar.stream_summarizer import StreamSummarizer

        dot_file = tmp_path / "test.dot"
        dot_file.write_text('''
            digraph test {
                start [shape=Mdiamond];
                impl_a [shape=box];
                impl_b [shape=box];
                gate [shape=hexagon];
                finalize [shape=Msquare];
            }
        ''')

        summarizer = StreamSummarizer(
            signals_dir=tmp_path / "signals",
            output_path=tmp_path / "summary.json",
            dot_file=dot_file,
        )
        assert summarizer._summary.nodes_total == 5
        assert summarizer._summary.pipeline_id == "test"
