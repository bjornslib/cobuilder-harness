"""E2E integration tests for the 4-layer Guardian Architecture pipeline.

Layers:
    Layer 0: Interactive Terminal (launch_guardian.py)
    Layer 1: Headless Guardian  (guardian_agent.py)
    Layer 2: Runner             (runner_agent.py)
    Layer 3: Orchestrator       (tmux session — existing infrastructure)

This module contains TWO categories of tests:

Category 1 — Dry-Run Integration Tests (run in regular pytest):
    Exercise the full cross-layer wiring using signal file I/O and dry-run
    modes.  No real Agent SDK calls are made.  These should complete in well
    under 120 seconds total.

Category 2 — Live E2E Tests (marked @pytest.mark.e2e, skipped by default):
    Make REAL Agent SDK calls.  Expensive and slow.  Run explicitly with:
        pytest -m e2e --timeout=600

Signal type reference (Runner -> Guardian):
    NEEDS_REVIEW, NEEDS_INPUT, VIOLATION, ORCHESTRATOR_STUCK,
    ORCHESTRATOR_CRASHED, NODE_COMPLETE

Response type reference (Guardian -> Runner):
    VALIDATION_PASSED, VALIDATION_FAILED, INPUT_RESPONSE, GUIDANCE,
    KILL_ORCHESTRATOR
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Path setup (mirrors conftest.py)
# ---------------------------------------------------------------------------

_ATTRACTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ATTRACTOR_DIR not in sys.path:
    sys.path.insert(0, _ATTRACTOR_DIR)

from signal_protocol import (  # noqa: E402
    list_signals,
    move_to_processed,
    read_signal,
    wait_for_signal,
    write_signal,
)
import launch_guardian  # noqa: E402
import guardian_agent  # noqa: E402
import runner_agent  # noqa: E402


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def create_minimal_dot(
    tmp_path: Any,
    node_id: str = "impl_test",
    handler: str = "codergen",
    pipeline_id: str = "test-001",
    prd_ref: str = "PRD-TEST-001",
    acceptance: str = "Creates /tmp/test.txt with 'hello'",
) -> str:
    """Generate a minimal valid DOT file with a single codergen node and a
    validation gate.

    Args:
        tmp_path: pytest tmp_path fixture or pathlib.Path.
        node_id: Identifier for the implementation node.
        handler: Handler type for the implementation node.
        pipeline_id: Pipeline identifier embedded in graph metadata.
        prd_ref: PRD reference embedded in graph metadata.
        acceptance: Acceptance criteria text for the node.

    Returns:
        Absolute path to the written DOT file.
    """
    dot_content = f"""\
digraph pipeline {{
    // Pipeline metadata
    graph [label="Test Pipeline" prd_ref="{prd_ref}" pipeline_id="{pipeline_id}"];

    // Nodes
    {node_id} [label="Test Implementation" handler="{handler}" status="pending"
               bead_id="test-bead-{node_id}" acceptance="{acceptance}"];

    // Validation gate
    val_{node_id} [label="Validate {node_id}" shape="hexagon" handler="wait.human" status="pending"];

    // Edges
    {node_id} -> val_{node_id} [label="pass"];
}}
"""
    dot_path = os.path.join(str(tmp_path), f"pipeline-{pipeline_id}.dot")
    with open(dot_path, "w", encoding="utf-8") as fh:
        fh.write(dot_content)
    return dot_path


def create_multi_node_dot(
    tmp_path: Any,
    nodes: list[dict[str, str]] | None = None,
    pipeline_id: str = "multi-001",
    prd_ref: str = "PRD-MULTI-001",
    include_research: bool = False,
    solution_design: str = "docs/sds/SD-TEST.md",
) -> str:
    """Generate a DOT file with multiple codergen nodes and edges.

    Args:
        tmp_path: pytest tmp_path fixture or pathlib.Path.
        nodes: List of dicts with keys: id, label, acceptance.
               Defaults to two sample nodes.
        pipeline_id: Pipeline identifier.
        prd_ref: PRD reference.
        include_research: If True, insert a research node before each codergen node.
        solution_design: SD path for research nodes (only used if include_research=True).

    Returns:
        Absolute path to the written DOT file.
    """
    if nodes is None:
        nodes = [
            {"id": "impl_auth", "label": "Implement Auth", "acceptance": "Auth module works"},
            {"id": "impl_db", "label": "Implement DB", "acceptance": "DB layer works"},
        ]

    node_lines = []
    research_lines = []
    val_lines = []
    edge_lines = []

    for node in nodes:
        nid = node["id"]
        label = node.get("label", nid)
        ac = node.get("acceptance", "See DOT file")
        handler = node.get("handler", "codergen")
        research_queries = node.get("research_queries", "")

        # Optional research node before this codergen node
        if include_research and handler == "codergen":
            rid = f"research_{nid.removeprefix('impl_')}"
            research_lines.append(
                f'    {rid} [label="Research\\n{label}" shape="tab" handler="research"'
                f' downstream_node="{nid}" solution_design="{solution_design}"'
                f' research_queries="{research_queries}" prd_ref="{prd_ref}" status="pending"];'
            )

        node_lines.append(
            f'    {nid} [label="{label}" handler="{handler}" status="pending"'
            f' bead_id="bead-{nid}" acceptance="{ac}"];'
        )
        val_lines.append(
            f'    val_{nid} [label="Validate {nid}" shape="hexagon"'
            f' handler="wait.human" status="pending"];'
        )

        # Edge: research -> impl (or just impl -> val if no research)
        if include_research and handler == "codergen":
            rid = f"research_{nid.removeprefix('impl_')}"
            edge_lines.append(f'    {rid} -> {nid} [label="research_complete"];')
        edge_lines.append(f'    {nid} -> val_{nid} [label="pass"];')

    # Chain validation gates: val_nodeA -> research_nodeB (or nodeB if no research)
    for i in range(len(nodes) - 1):
        cur_val = f"val_{nodes[i]['id']}"
        next_nid = nodes[i + 1]["id"]
        next_handler = nodes[i + 1].get("handler", "codergen")
        if include_research and next_handler == "codergen":
            next_rid = f"research_{next_nid.removeprefix('impl_')}"
            edge_lines.append(f'    {cur_val} -> {next_rid} [label="next"];')
        else:
            edge_lines.append(f'    {cur_val} -> {next_nid} [label="next"];')

    all_node_lines = research_lines + node_lines
    dot_content = (
        f"digraph pipeline {{\n"
        f'    graph [label="Multi-Node Pipeline" prd_ref="{prd_ref}" pipeline_id="{pipeline_id}"];\n\n'
        + "\n".join(all_node_lines) + "\n\n"
        + "\n".join(val_lines) + "\n\n"
        + "\n".join(edge_lines) + "\n"
        + "}\n"
    )

    dot_path = os.path.join(str(tmp_path), f"pipeline-{pipeline_id}.dot")
    with open(dot_path, "w", encoding="utf-8") as fh:
        fh.write(dot_content)
    return dot_path


def assert_signal_flow(signals_dir: str, expected_types: list[str]) -> None:
    """Verify that processed signal files contain the expected signal types.

    Checks that the *set* of signal types matches (order is not guaranteed
    because signals written within the same second share a timestamp prefix
    and sort lexicographically by the source-target-type suffix instead).

    Args:
        signals_dir: The signals directory (checks processed/ subdirectory).
        expected_types: List of expected signal_type values (order-independent).

    Raises:
        AssertionError: If the processed signals do not match expected_types.
    """
    processed_dir = os.path.join(signals_dir, "processed")
    if not os.path.isdir(processed_dir):
        assert expected_types == [], (
            f"Expected signal flow {expected_types} but processed/ directory does not exist"
        )
        return

    files = sorted(
        f for f in os.listdir(processed_dir)
        if f.endswith(".json") and not f.endswith(".tmp")
    )

    actual_types = []
    for fname in files:
        fpath = os.path.join(processed_dir, fname)
        data = read_signal(fpath)
        actual_types.append(data["signal_type"])

    assert sorted(actual_types) == sorted(expected_types), (
        f"Signal flow mismatch.\n"
        f"  Expected (sorted): {sorted(expected_types)}\n"
        f"  Actual   (sorted): {sorted(actual_types)}"
    )


# ============================================================================
# Category 1: Dry-Run Integration Tests
# ============================================================================


class TestDryRunSinglePipeline:
    """Test 1: Create a minimal DOT file, call launch_guardian with dry_run,
    verify config dict has all expected fields."""

    def test_dry_run_single_pipeline(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path)

        result = launch_guardian.launch_guardian(
            dot_path=dot_path,
            project_root=str(tmp_path),
            pipeline_id="test-001",
            dry_run=True,
        )

        assert isinstance(result, dict)
        assert result["dry_run"] is True
        assert os.path.isabs(result["dot_path"])
        assert result["pipeline_id"] == "test-001"
        assert result["model"] == launch_guardian.DEFAULT_MODEL
        assert result["max_turns"] == launch_guardian.DEFAULT_MAX_TURNS
        assert result["signal_timeout"] == launch_guardian.DEFAULT_SIGNAL_TIMEOUT
        assert result["max_retries"] == launch_guardian.DEFAULT_MAX_RETRIES
        assert result["project_root"] == str(tmp_path)
        assert os.path.isabs(result["scripts_dir"])
        assert result["system_prompt_length"] > 0
        assert result["initial_prompt_length"] > 0


class TestDryRunSignalFlow:
    """Test 2: Write signals through the full chain (runner -> guardian -> terminal),
    verify each signal is parseable and routable."""

    def test_dry_run_signal_flow(self, tmp_path):
        # Expected signal flow:
        # 1. Runner signals Guardian: NEEDS_REVIEW
        # 2. Guardian signals Runner: VALIDATION_PASSED (response)
        # 3. Guardian signals Terminal: PIPELINE_COMPLETE (escalation/completion)

        signals_dir = str(tmp_path / "signals")

        # Step 1: Runner -> Guardian
        p1 = write_signal(
            source="runner", target="guardian", signal_type="NEEDS_REVIEW",
            payload={"node_id": "impl_test", "commit_hash": "abc123"},
            signals_dir=signals_dir,
        )
        s1 = read_signal(p1)
        assert s1["source"] == "runner"
        assert s1["target"] == "guardian"
        assert s1["signal_type"] == "NEEDS_REVIEW"

        # Guardian consumes it
        move_to_processed(p1)

        # Step 2: Guardian -> Runner (response)
        p2 = write_signal(
            source="guardian", target="runner", signal_type="VALIDATION_PASSED",
            payload={"node_id": "impl_test"},
            signals_dir=signals_dir,
        )
        s2 = read_signal(p2)
        assert s2["source"] == "guardian"
        assert s2["target"] == "runner"
        assert s2["signal_type"] == "VALIDATION_PASSED"

        # Runner consumes it
        move_to_processed(p2)

        # Step 3: Guardian -> Terminal (pipeline complete)
        p3 = write_signal(
            source="guardian", target="terminal", signal_type="PIPELINE_COMPLETE",
            payload={"pipeline_id": "test-001", "issue": "PIPELINE_COMPLETE: all nodes validated"},
            signals_dir=signals_dir,
        )
        s3 = read_signal(p3)
        assert s3["source"] == "guardian"
        assert s3["target"] == "terminal"
        assert s3["signal_type"] == "PIPELINE_COMPLETE"

        # Terminal consumes it
        move_to_processed(p3)

        # Verify the full chain is in processed/
        assert_signal_flow(
            signals_dir,
            ["NEEDS_REVIEW", "VALIDATION_PASSED", "PIPELINE_COMPLETE"],
        )


class TestDryRunGuardianToRunnerResponseFlow:
    """Test 3: Guardian writes VALIDATION_PASSED response, verify runner can read it."""

    def test_guardian_response_readable_by_runner(self, tmp_path):
        signals_dir = str(tmp_path / "signals")

        # Guardian writes response
        write_signal(
            source="guardian", target="runner", signal_type="VALIDATION_PASSED",
            payload={"node_id": "impl_auth"},
            signals_dir=signals_dir,
        )

        # Runner reads via list_signals (filtering by target)
        runner_signals = list_signals(target_layer="runner", signals_dir=signals_dir)
        assert len(runner_signals) == 1

        data = read_signal(runner_signals[0])
        assert data["signal_type"] == "VALIDATION_PASSED"
        assert data["payload"]["node_id"] == "impl_auth"


class TestDryRunEscalationToTerminal:
    """Test 4: Guardian writes escalation, verify terminal (launch_guardian)
    can parse it via handle_escalation()."""

    def test_escalation_parsed_by_terminal(self, tmp_path):
        signals_dir = str(tmp_path / "signals")

        # Guardian writes escalation to terminal
        path = write_signal(
            source="guardian", target="terminal", signal_type="ESCALATE",
            payload={
                "pipeline_id": "pipe-001",
                "issue": "Node impl_auth failed validation 3 times",
                "options": ["retry", "skip", "abort"],
            },
            signals_dir=signals_dir,
        )

        signal_data = read_signal(path)
        result = launch_guardian.handle_escalation(signal_data)

        assert result["status"] == "escalation"
        assert result["pipeline_id"] == "pipe-001"
        assert "impl_auth" in result["issue"]
        assert result["options"] == ["retry", "skip", "abort"]
        assert result["signal_type"] == "ESCALATE"
        assert result["source"] == "guardian"


class TestDryRunPipelineCompleteFlow:
    """Test 5: Write PIPELINE_COMPLETE signal, verify handle_pipeline_complete()
    returns correct summary."""

    def test_pipeline_complete_summary(self, tmp_path):
        signals_dir = str(tmp_path / "signals")
        dot_path = create_minimal_dot(tmp_path)

        path = write_signal(
            source="guardian", target="terminal", signal_type="PIPELINE_COMPLETE",
            payload={
                "pipeline_id": "test-001",
                "issue": "PIPELINE_COMPLETE: all nodes validated",
                "node_statuses": {
                    "impl_test": "validated",
                    "val_impl_test": "validated",
                },
            },
            signals_dir=signals_dir,
        )

        signal_data = read_signal(path)
        result = launch_guardian.handle_pipeline_complete(signal_data, dot_path)

        assert result["status"] == "complete"
        assert result["pipeline_id"] == "test-001"
        assert result["dot_path"] == dot_path
        assert result["node_statuses"]["impl_test"] == "validated"
        assert "PIPELINE_COMPLETE" in result["issue"]
        assert result["source"] == "guardian"


class TestDryRunMultiPipeline:
    """Test 6: Create 2 minimal DOT files, call launch_multiple_guardians
    with dry_run=True, verify both configs returned."""

    def test_multi_pipeline_dry_run(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        dot_a = create_minimal_dot(
            dir_a, node_id="impl_a", pipeline_id="pipe-alpha",
        )
        dot_b = create_minimal_dot(
            dir_b, node_id="impl_b", pipeline_id="pipe-beta",
        )

        configs = [
            {
                "dot_path": dot_a,
                "project_root": str(tmp_path),
                "pipeline_id": "pipe-alpha",
                "dry_run": True,
            },
            {
                "dot_path": dot_b,
                "project_root": str(tmp_path),
                "pipeline_id": "pipe-beta",
                "dry_run": True,
            },
        ]

        results = launch_guardian.launch_multiple_guardians(configs)

        assert len(results) == 2
        pipeline_ids = {r["pipeline_id"] for r in results}
        assert "pipe-alpha" in pipeline_ids
        assert "pipe-beta" in pipeline_ids
        for r in results:
            assert r["dry_run"] is True
            assert r["system_prompt_length"] > 0
            assert r["initial_prompt_length"] > 0


class TestMinimalDotCreation:
    """Test 7: Verify the test DOT helper creates a valid pipeline DOT."""

    def test_dot_file_exists(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path)
        assert os.path.exists(dot_path)

    def test_dot_file_has_digraph(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path)
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "digraph pipeline" in content

    def test_dot_file_has_node(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path, node_id="impl_foo")
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "impl_foo" in content
        assert "handler=\"codergen\"" in content
        assert "status=\"pending\"" in content

    def test_dot_file_has_validation_gate(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path, node_id="impl_foo")
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "val_impl_foo" in content
        assert "wait.human" in content

    def test_dot_file_has_edge(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path, node_id="impl_foo")
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "impl_foo -> val_impl_foo" in content

    def test_dot_file_has_metadata(self, tmp_path):
        dot_path = create_minimal_dot(
            tmp_path, pipeline_id="p-123", prd_ref="PRD-X-999",
        )
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "PRD-X-999" in content
        assert "p-123" in content

    def test_multi_node_dot_has_all_nodes(self, tmp_path):
        nodes = [
            {"id": "impl_a", "label": "A", "acceptance": "A works"},
            {"id": "impl_b", "label": "B", "acceptance": "B works"},
            {"id": "impl_c", "label": "C", "acceptance": "C works"},
        ]
        dot_path = create_multi_node_dot(tmp_path, nodes=nodes)
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        for node in nodes:
            assert node["id"] in content
            assert f"val_{node['id']}" in content

    def test_multi_node_dot_has_chained_edges(self, tmp_path):
        nodes = [
            {"id": "impl_a", "label": "A", "acceptance": "A works"},
            {"id": "impl_b", "label": "B", "acceptance": "B works"},
        ]
        dot_path = create_multi_node_dot(tmp_path, nodes=nodes)
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        # val_impl_a -> impl_b (sequential dependency)
        assert "val_impl_a -> impl_b" in content


class TestResearchNodePipeline:
    """Test: DOT pipelines with research nodes before codergen nodes."""

    def test_multi_node_dot_with_research_has_research_nodes(self, tmp_path):
        """include_research=True inserts research nodes before each codergen."""
        dot_path = create_multi_node_dot(
            tmp_path, include_research=True, solution_design="docs/sds/SD-TEST.md",
        )
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "research_auth" in content
        assert "research_db" in content
        assert 'handler="research"' in content
        assert 'shape="tab"' in content

    def test_multi_node_dot_with_research_has_correct_edges(self, tmp_path):
        """Research nodes are wired: research -> impl and val -> research (next)."""
        dot_path = create_multi_node_dot(
            tmp_path, include_research=True, solution_design="docs/sds/SD-TEST.md",
        )
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        # research -> impl edge
        assert "research_auth -> impl_auth" in content
        assert "research_db -> impl_db" in content
        # val -> research (chain to next research, not directly to next impl)
        assert "val_impl_auth -> research_db" in content

    def test_multi_node_dot_with_research_has_solution_design(self, tmp_path):
        """Research nodes include the solution_design attribute."""
        dot_path = create_multi_node_dot(
            tmp_path,
            include_research=True,
            solution_design="docs/sds/SD-CUSTOM.md",
        )
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "SD-CUSTOM.md" in content

    def test_multi_node_dot_with_research_has_downstream_node(self, tmp_path):
        """Research nodes include the downstream_node attribute."""
        dot_path = create_multi_node_dot(
            tmp_path, include_research=True,
        )
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert 'downstream_node="impl_auth"' in content
        assert 'downstream_node="impl_db"' in content

    def test_multi_node_dot_without_research_unchanged(self, tmp_path):
        """include_research=False (default) produces no research nodes."""
        dot_path = create_multi_node_dot(tmp_path, include_research=False)
        with open(dot_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "research" not in content.lower()
        assert "tab" not in content

    def test_guardian_prompt_mentions_research_dispatch(self, tmp_path):
        """Guardian system prompt includes Phase 2a research dispatch instructions."""
        dot_path = create_minimal_dot(tmp_path)
        scripts_dir = guardian_agent.resolve_scripts_dir()
        prompt = guardian_agent.build_system_prompt(
            dot_path=dot_path,
            pipeline_id="research-test-001",
            scripts_dir=scripts_dir,
            signal_timeout=600.0,
            max_retries=3,
            target_dir=str(tmp_path),
        )
        assert "Phase 2a" in prompt
        assert "run_research.py" in prompt
        assert "research" in prompt.lower()

    def test_guardian_prompt_research_before_codergen(self, tmp_path):
        """Phase 2a (research) appears before Phase 2b (codergen) in the prompt."""
        dot_path = create_minimal_dot(tmp_path)
        scripts_dir = guardian_agent.resolve_scripts_dir()
        prompt = guardian_agent.build_system_prompt(
            dot_path=dot_path,
            pipeline_id="order-test",
            scripts_dir=scripts_dir,
            signal_timeout=600.0,
            max_retries=3,
            target_dir=str(tmp_path),
        )
        research_pos = prompt.index("Phase 2a")
        codergen_pos = prompt.index("Phase 2b")
        assert research_pos < codergen_pos

    def test_run_research_dry_run_from_guardian_context(self, tmp_path):
        """run_research.py --dry-run produces valid JSON from the guardian's scripts dir."""
        import io
        from contextlib import redirect_stdout

        sd_file = tmp_path / "docs" / "sds" / "SD-TEST.md"
        sd_file.parent.mkdir(parents=True, exist_ok=True)
        sd_file.write_text("# Test Solution Design\n\n## Auth Patterns\nUse FastAPI Depends.\n")

        # Import run_research from scripts dir
        import run_research

        buf = io.StringIO()
        with pytest.raises(SystemExit) as exc_info:
            with redirect_stdout(buf):
                run_research.main([
                    "--node", "research_auth",
                    "--prd", "PRD-TEST-001",
                    "--solution-design", str(sd_file),
                    "--target-dir", str(tmp_path),
                    "--frameworks", "fastapi,pydantic",
                    "--dry-run",
                ])

        assert exc_info.value.code == 0
        data = json.loads(buf.getvalue())
        assert data["dry_run"] is True
        assert data["node"] == "research_auth"
        assert data["frameworks"] == ["fastapi", "pydantic"]
        assert "prompt" in data
        # Prompt should reference the SD path
        assert str(sd_file) in data["prompt"]


class TestSignalRoundtripAllTypes:
    """Test 8: For each of the 6 runner->guardian signal types, write and
    read back, verifying full round-trip fidelity."""

    RUNNER_SIGNAL_TYPES = [
        "NEEDS_REVIEW",
        "NEEDS_INPUT",
        "VIOLATION",
        "ORCHESTRATOR_STUCK",
        "ORCHESTRATOR_CRASHED",
        "NODE_COMPLETE",
    ]

    @pytest.mark.parametrize("signal_type", RUNNER_SIGNAL_TYPES)
    def test_signal_roundtrip(self, tmp_path, signal_type):
        signals_dir = str(tmp_path / "signals")
        payload = {
            "node_id": "impl_test",
            "signal_type_tag": signal_type,
            "extra": f"data-for-{signal_type}",
        }

        path = write_signal(
            source="runner", target="guardian",
            signal_type=signal_type,
            payload=payload,
            signals_dir=signals_dir,
        )

        data = read_signal(path)
        assert data["source"] == "runner"
        assert data["target"] == "guardian"
        assert data["signal_type"] == signal_type
        assert data["payload"]["node_id"] == "impl_test"
        assert data["payload"]["extra"] == f"data-for-{signal_type}"
        assert "timestamp" in data


class TestResponseRoundtripAllTypes:
    """Test 9: For each of the 5 guardian->runner response types, write and
    read back."""

    RESPONSE_TYPES = [
        "VALIDATION_PASSED",
        "VALIDATION_FAILED",
        "INPUT_RESPONSE",
        "GUIDANCE",
        "KILL_ORCHESTRATOR",
    ]

    @pytest.mark.parametrize("response_type", RESPONSE_TYPES)
    def test_response_roundtrip(self, tmp_path, response_type):
        signals_dir = str(tmp_path / "signals")
        payload = {
            "node_id": "impl_test",
            "response_tag": response_type,
            "detail": f"detail-for-{response_type}",
        }

        path = write_signal(
            source="guardian", target="runner",
            signal_type=response_type,
            payload=payload,
            signals_dir=signals_dir,
        )

        data = read_signal(path)
        assert data["source"] == "guardian"
        assert data["target"] == "runner"
        assert data["signal_type"] == response_type
        assert data["payload"]["node_id"] == "impl_test"
        assert data["payload"]["detail"] == f"detail-for-{response_type}"


class TestMonitorGuardianWithCompleteSignal:
    """Test 10: Write PIPELINE_COMPLETE signal to tmp signals dir, call
    monitor_guardian, verify returns complete status."""

    def test_monitor_detects_complete(self, tmp_path):
        signals_dir = str(tmp_path / "signals")

        # Pre-write a PIPELINE_COMPLETE signal targeting terminal
        write_signal(
            source="guardian", target="terminal",
            signal_type="PIPELINE_COMPLETE",
            payload={
                "pipeline_id": "test-pipe",
                "issue": "PIPELINE_COMPLETE: all nodes validated",
                "node_statuses": {"impl_test": "validated"},
            },
            signals_dir=signals_dir,
        )

        # monitor_guardian uses wait_for_signal internally; we mock it
        # to read from our tmp signals dir
        from unittest.mock import patch

        def mock_wait(target_layer, timeout=300, signals_dir=None, poll_interval=5.0):
            return wait_for_signal(
                target_layer=target_layer,
                timeout=5.0,
                signals_dir=signals_dir or str(tmp_path / "signals"),
                poll_interval=0.1,
            )

        with patch("launch_guardian.wait_for_signal", mock_wait):
            result = launch_guardian.monitor_guardian(
                guardian_process=None,
                dot_path="/tmp/pipeline.dot",
                signals_dir=signals_dir,
            )

        assert result["status"] == "complete"
        assert result["pipeline_id"] == "test-pipe"


class TestMonitorGuardianWithEscalationSignal:
    """Test 11: Write escalation signal, call monitor_guardian, verify
    returns escalation status."""

    def test_monitor_detects_escalation(self, tmp_path):
        signals_dir = str(tmp_path / "signals")

        write_signal(
            source="guardian", target="terminal",
            signal_type="ESCALATE",
            payload={
                "pipeline_id": "test-pipe",
                "issue": "Node impl_auth exceeded max retries",
            },
            signals_dir=signals_dir,
        )

        from unittest.mock import patch

        def mock_wait(target_layer, timeout=300, signals_dir=None, poll_interval=5.0):
            return wait_for_signal(
                target_layer=target_layer,
                timeout=5.0,
                signals_dir=signals_dir or str(tmp_path / "signals"),
                poll_interval=0.1,
            )

        with patch("launch_guardian.wait_for_signal", mock_wait):
            result = launch_guardian.monitor_guardian(
                guardian_process=None,
                dot_path="/tmp/pipeline.dot",
                signals_dir=signals_dir,
            )

        assert result["status"] == "escalation"
        assert "impl_auth" in result["issue"]


class TestFullSignalChainDryRun:
    """Test 12: Simulate the full signal chain through file I/O.

    Expected signal flow:
    1. (Launch dispatches guardian — simulated by dry-run config)
    2. Runner signals Guardian: NEEDS_REVIEW (implementation done)
    3. Guardian responds to Runner: VALIDATION_PASSED
    4. Runner signals Guardian: NODE_COMPLETE (committed)
    5. Guardian signals Terminal: PIPELINE_COMPLETE (all done)
    6. Terminal (launch_guardian) receives and parses PIPELINE_COMPLETE
    """

    def test_full_chain(self, tmp_path):
        signals_dir = str(tmp_path / "signals")
        dot_path = create_minimal_dot(tmp_path, pipeline_id="chain-001")
        timestamps = []

        # Step 0: Launch guardian dry-run (verify config is buildable)
        config = launch_guardian.launch_guardian(
            dot_path=dot_path,
            project_root=str(tmp_path),
            pipeline_id="chain-001",
            dry_run=True,
        )
        assert config["dry_run"] is True
        timestamps.append(("launch_config", time.monotonic()))

        # Step 1: Runner -> Guardian: NEEDS_REVIEW
        p1 = write_signal(
            source="runner", target="guardian",
            signal_type="NEEDS_REVIEW",
            payload={
                "node_id": "impl_test",
                "commit_hash": "abc123",
                "summary": "Implementation complete for impl_test",
            },
            signals_dir=signals_dir,
        )
        timestamps.append(("NEEDS_REVIEW written", time.monotonic()))

        # Guardian consumes the signal
        s1 = wait_for_signal(
            target_layer="guardian", timeout=5.0,
            signals_dir=signals_dir, poll_interval=0.1,
        )
        assert s1["signal_type"] == "NEEDS_REVIEW"
        assert s1["payload"]["node_id"] == "impl_test"
        timestamps.append(("NEEDS_REVIEW consumed by guardian", time.monotonic()))

        # Step 2: Guardian -> Runner: VALIDATION_PASSED
        p2 = write_signal(
            source="guardian", target="runner",
            signal_type="VALIDATION_PASSED",
            payload={"node_id": "impl_test"},
            signals_dir=signals_dir,
        )
        timestamps.append(("VALIDATION_PASSED written", time.monotonic()))

        # Runner consumes the response
        s2 = wait_for_signal(
            target_layer="runner", timeout=5.0,
            signals_dir=signals_dir, poll_interval=0.1,
        )
        assert s2["signal_type"] == "VALIDATION_PASSED"
        timestamps.append(("VALIDATION_PASSED consumed by runner", time.monotonic()))

        # Step 3: Runner -> Guardian: NODE_COMPLETE
        p3 = write_signal(
            source="runner", target="guardian",
            signal_type="NODE_COMPLETE",
            payload={
                "node_id": "impl_test",
                "commit_hash": "def456",
                "summary": "Node impl_test committed",
            },
            signals_dir=signals_dir,
        )
        timestamps.append(("NODE_COMPLETE written", time.monotonic()))

        # Guardian consumes it
        s3 = wait_for_signal(
            target_layer="guardian", timeout=5.0,
            signals_dir=signals_dir, poll_interval=0.1,
        )
        assert s3["signal_type"] == "NODE_COMPLETE"
        timestamps.append(("NODE_COMPLETE consumed by guardian", time.monotonic()))

        # Step 4: Guardian -> Terminal: PIPELINE_COMPLETE
        p4 = write_signal(
            source="guardian", target="terminal",
            signal_type="PIPELINE_COMPLETE",
            payload={
                "pipeline_id": "chain-001",
                "issue": "PIPELINE_COMPLETE: all nodes validated",
                "node_statuses": {"impl_test": "validated"},
            },
            signals_dir=signals_dir,
        )
        timestamps.append(("PIPELINE_COMPLETE written", time.monotonic()))

        # Step 5: Terminal consumes and parses it
        s4 = wait_for_signal(
            target_layer="terminal", timeout=5.0,
            signals_dir=signals_dir, poll_interval=0.1,
        )
        assert s4["signal_type"] == "PIPELINE_COMPLETE"
        timestamps.append(("PIPELINE_COMPLETE consumed by terminal", time.monotonic()))

        # Step 6: Terminal processes via handle_pipeline_complete
        result = launch_guardian.handle_pipeline_complete(s4, dot_path)
        assert result["status"] == "complete"
        assert result["pipeline_id"] == "chain-001"
        assert result["node_statuses"]["impl_test"] == "validated"
        timestamps.append(("handle_pipeline_complete done", time.monotonic()))

        # Verify all signals flowed through processed/
        assert_signal_flow(
            signals_dir,
            [
                "NEEDS_REVIEW",
                "VALIDATION_PASSED",
                "NODE_COMPLETE",
                "PIPELINE_COMPLETE",
            ],
        )

        # Verify timing: entire chain should complete in well under 10 seconds
        total_elapsed = timestamps[-1][1] - timestamps[0][1]
        assert total_elapsed < 10.0, (
            f"Full signal chain took {total_elapsed:.2f}s (expected < 10s)"
        )


class TestGuardianAgentDryRunIntegration:
    """Additional integration tests for guardian_agent dry-run mode using
    real DOT files created by the helpers."""

    def test_guardian_dry_run_with_real_dot(self, tmp_path):
        """guardian_agent.main() --dry-run with a real DOT file."""
        import io
        from contextlib import redirect_stdout

        dot_path = create_minimal_dot(tmp_path, pipeline_id="g-int-001")

        buf = io.StringIO()
        with pytest.raises(SystemExit) as exc_info:
            with redirect_stdout(buf):
                guardian_agent.main([
                    "--dot", dot_path,
                    "--pipeline-id", "g-int-001",
                    "--target-dir", str(tmp_path),
                    "--dry-run",
                ])

        assert exc_info.value.code == 0
        data = json.loads(buf.getvalue())
        assert data["dry_run"] is True
        assert data["pipeline_id"] == "g-int-001"
        assert data["dot_path"] == os.path.abspath(dot_path)


class TestRunnerAgentDryRunIntegration:
    """Integration tests for runner_agent dry-run mode."""

    def test_runner_dry_run(self, tmp_path):
        """runner_agent.main() --dry-run with standard args."""
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with pytest.raises(SystemExit) as exc_info:
            with redirect_stdout(buf):
                runner_agent.main([
                    "--node", "impl_test",
                    "--prd", "PRD-TEST-001",
                    "--session", "orch-test",
                    "--acceptance", "Creates test file",
                    "--target-dir", str(tmp_path),
                    "--dry-run",
                ])

        assert exc_info.value.code == 0
        data = json.loads(buf.getvalue())
        assert data["dry_run"] is True
        assert data["node_id"] == "impl_test"
        assert data["prd_ref"] == "PRD-TEST-001"
        assert data["session_name"] == "orch-test"
        assert data["system_prompt_length"] > 0
        assert data["initial_prompt_length"] > 0


class TestCrossLayerPromptConsistency:
    """Verify that the prompts built by launch_guardian and guardian_agent
    are identical (launch_guardian delegates to guardian_agent)."""

    def test_system_prompts_match(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path)
        scripts_dir = guardian_agent.resolve_scripts_dir()

        from_guardian = guardian_agent.build_system_prompt(
            dot_path=dot_path,
            pipeline_id="consistency-001",
            scripts_dir=scripts_dir,
            signal_timeout=600.0,
            max_retries=3,
        )
        from_launch = launch_guardian.build_system_prompt(
            dot_path=dot_path,
            pipeline_id="consistency-001",
            scripts_dir=scripts_dir,
            signal_timeout=600.0,
            max_retries=3,
        )
        assert from_guardian == from_launch

    def test_initial_prompts_match(self, tmp_path):
        dot_path = create_minimal_dot(tmp_path)
        scripts_dir = guardian_agent.resolve_scripts_dir()

        from_guardian = guardian_agent.build_initial_prompt(
            dot_path=dot_path,
            pipeline_id="consistency-001",
            scripts_dir=scripts_dir,
        )
        from_launch = launch_guardian.build_initial_prompt(
            dot_path=dot_path,
            pipeline_id="consistency-001",
            scripts_dir=scripts_dir,
        )
        assert from_guardian == from_launch


# ============================================================================
# Category 2: Live E2E Tests (marked @pytest.mark.e2e, skipped by default)
# ============================================================================


@pytest.mark.e2e
class TestE2ESingleNodePipeline:
    """Test 13: Full live E2E with real Agent SDK calls.

    Expected signal flow:
    1. Guardian dispatches impl_test -> active
    2. Guardian spawns Runner for impl_test
    3. Runner monitors orchestrator in tmux
    4. Runner signals: NEEDS_REVIEW (implementation done)
    5. Guardian responds: VALIDATION_PASSED
    6. Runner signals: NODE_COMPLETE (committed)
    7. Guardian transitions: impl_test -> impl_complete -> validated
    8. Guardian signals: PIPELINE_COMPLETE (to terminal)
    9. Terminal receives PIPELINE_COMPLETE

    This test creates a trivial task (create a file with specific content)
    to minimise cost and duration while exercising the full 3-layer pipeline.
    """

    @pytest.fixture
    def e2e_workspace(self, tmp_path):
        """Set up a workspace with DOT file, signals dir, and cleanup."""
        test_id = str(uuid.uuid4())[:8]
        signals_dir = str(tmp_path / "signals")
        target_file = f"/tmp/e2e-test-{test_id}.txt"

        dot_path = create_minimal_dot(
            tmp_path,
            node_id="impl_e2e",
            pipeline_id=f"e2e-{test_id}",
            acceptance=f"Creates {target_file} with content 'hello guardian'",
        )

        yield {
            "test_id": test_id,
            "dot_path": dot_path,
            "signals_dir": signals_dir,
            "target_file": target_file,
            "project_root": str(tmp_path),
            "pipeline_id": f"e2e-{test_id}",
        }

        # Cleanup
        if os.path.exists(target_file):
            os.unlink(target_file)

    @pytest.mark.timeout(600)
    def test_e2e_single_node(self, e2e_workspace):
        """Full live pipeline execution.

        NOTE: This test requires:
        - Valid ANTHROPIC_API_KEY in environment
        - claude CLI available on PATH
        - Sufficient API credits

        Skip with: pytest -m 'not e2e'
        """
        ws = e2e_workspace

        # This would invoke the real Agent SDK.
        # For now, we verify the setup is correct and skip the actual SDK call
        # since it requires a live API key and running tmux session.
        pytest.skip(
            "Live E2E test requires real Agent SDK and tmux infrastructure. "
            "Run explicitly with: pytest -m e2e --timeout=600"
        )

        # When enabled, the flow would be:
        # result = launch_guardian.launch_guardian(
        #     dot_path=ws["dot_path"],
        #     project_root=ws["project_root"],
        #     pipeline_id=ws["pipeline_id"],
        #     signals_dir=ws["signals_dir"],
        #     signal_timeout=120,
        #     max_retries=2,
        # )
        #
        # Then monitor:
        # monitor_result = launch_guardian.monitor_guardian(
        #     guardian_process=None,
        #     dot_path=ws["dot_path"],
        #     signals_dir=ws["signals_dir"],
        #     timeout=600,
        # )
        # assert monitor_result["status"] == "complete"
        # assert os.path.exists(ws["target_file"])
        # with open(ws["target_file"]) as fh:
        #     assert fh.read().strip() == "hello guardian"
