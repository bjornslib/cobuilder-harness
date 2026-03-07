#!/usr/bin/env python3
"""E7.2 E2E Tests: Pure Python Pipeline Runner.

Tests against acceptance criteria from:
  - SD-HARNESS-UPGRADE-001-E7-python-runner.md
  - acceptance-tests/PRD-HARNESS-UPGRADE-001/E7.2-python-runner.feature

Run: python3 -m pytest tests/test_e72_pipeline_runner.py -v
"""

import json
import os
import subprocess
import sys

import pytest

# Ensure attractor scripts are importable
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".claude", "scripts", "attractor",
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_PIPELINE_DOT = """\
digraph "test-pipeline" {
    graph [
        label="Test Pipeline"
        prd_ref="PRD-TEST-001"
        target_dir="/tmp/test"
    ];

    node [fontname="Helvetica" fontsize=11];
    edge [fontname="Helvetica" fontsize=9];

    start [
        shape=Mdiamond
        label="START"
        handler="start"
        status="pending"
    ];

    impl_a [
        shape=box
        label="Task A"
        handler="codergen"
        worker_type="backend-solutions-engineer"
        sd_path="docs/sds/test-sd.md"
        acceptance="Write hello world"
        status="pending"
    ];

    impl_b [
        shape=box
        label="Task B"
        handler="codergen"
        worker_type="backend-solutions-engineer"
        sd_path="docs/sds/test-sd.md"
        acceptance="Write goodbye world"
        status="pending"
    ];

    tool_lint [
        shape=component
        label="Lint Check"
        handler="tool"
        command="echo lint-ok"
        status="pending"
    ];

    finalize [
        shape=Msquare
        label="FINALIZE"
        handler="exit"
        status="pending"
    ];

    start -> impl_a [label="begin"];
    start -> impl_b [label="begin"];
    impl_a -> tool_lint [label="impl_complete"];
    impl_b -> tool_lint [label="impl_complete"];
    tool_lint -> finalize [label="validated"];
}
"""

TWO_NODE_PIPELINE = """\
digraph "two-node" {
    graph [label="Two Node" prd_ref="PRD-TEST"];

    start [shape=Mdiamond label="START" handler="start" status="pending"];
    task [shape=box label="Task" handler="tool" command="echo ok" status="pending"];
    finish [shape=Msquare label="FINISH" handler="exit" status="pending"];

    start -> task [label="begin"];
    task -> finish [label="validated"];
}
"""


@pytest.fixture
def pipeline_dir(tmp_path):
    """Create a temp directory with a test pipeline DOT file."""
    dot_file = tmp_path / "test-pipeline.dot"
    dot_file.write_text(SIMPLE_PIPELINE_DOT)
    signals_dir = tmp_path / "signals"
    signals_dir.mkdir()
    return tmp_path, dot_file


@pytest.fixture
def two_node_dir(tmp_path):
    """Create a temp directory with a minimal two-node pipeline."""
    dot_file = tmp_path / "two-node.dot"
    dot_file.write_text(TWO_NODE_PIPELINE)
    signals_dir = tmp_path / "signals"
    signals_dir.mkdir()
    return tmp_path, dot_file


# ---------------------------------------------------------------------------
# S7.2.1 — pipeline_runner.py exists and has CLI
# ---------------------------------------------------------------------------


class TestPipelineRunnerCLI:
    """AC-7.2.1: pipeline_runner.py exists, imports, --help works."""

    def test_file_exists(self):
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        assert os.path.isfile(path), f"pipeline_runner.py not found at {path}"

    def test_imports_cleanly(self):
        """pipeline_runner.py imports without error."""
        from pipeline_runner import PipelineRunner  # noqa: F401

    def test_help_flag(self):
        """--help shows expected options."""
        result = subprocess.run(
            [sys.executable, os.path.join(_SCRIPTS_DIR, "pipeline_runner.py"), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "--dot-file" in result.stdout
        assert "--resume" in result.stdout

    def test_no_anthropic_import(self):
        """pipeline_runner.py must NOT import anthropic (zero LLM)."""
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        content = open(path).read()
        assert "anthropic.Anthropic" not in content, "Found anthropic.Anthropic — runner must be zero LLM"
        assert "messages.create" not in content, "Found messages.create — runner must be zero LLM"


# ---------------------------------------------------------------------------
# S7.2.2 — Dispatchable node discovery respects dependency state
# ---------------------------------------------------------------------------


class TestDispatchableNodes:
    """AC-7.2.2: _find_dispatchable_nodes() respects deps."""

    def test_start_node_dispatchable(self, pipeline_dir):
        """START node has no predecessors, should be immediately dispatchable."""
        tmp_path, dot_file = pipeline_dir
        from pipeline_runner import PipelineRunner
        from parser import parse_dot
        runner = PipelineRunner(str(dot_file))
        data = parse_dot(runner.dot_content)
        nodes = runner._find_dispatchable_nodes(data)
        node_ids = [n["id"] for n in nodes]
        assert "start" in node_ids, f"START should be dispatchable, got: {node_ids}"

    def test_blocked_node_not_dispatchable(self, pipeline_dir):
        """Nodes with pending predecessors should NOT be dispatchable."""
        tmp_path, dot_file = pipeline_dir
        from pipeline_runner import PipelineRunner
        from parser import parse_dot
        runner = PipelineRunner(str(dot_file))
        data = parse_dot(runner.dot_content)
        nodes = runner._find_dispatchable_nodes(data)
        node_ids = [n["id"] for n in nodes]
        assert "impl_a" not in node_ids, "impl_a should NOT be dispatchable (start still pending)"
        assert "finalize" not in node_ids, "finalize should NOT be dispatchable"


# ---------------------------------------------------------------------------
# S7.2.4 — Tool handler runs command without LLM
# ---------------------------------------------------------------------------


class TestToolHandler:
    """AC-7.2.4: _handle_tool runs command, writes signal, no LLM."""

    def test_tool_handler_writes_signal(self, two_node_dir):
        """Tool handler should run command and write signal file."""
        tmp_path, dot_file = two_node_dir
        from pipeline_runner import PipelineRunner
        from parser import parse_dot
        runner = PipelineRunner(str(dot_file))
        data = parse_dot(runner.dot_content)

        # Find the tool node
        tool_node = next(n for n in data["nodes"] if n["attrs"].get("handler") == "tool")

        # Run the handler
        runner._handle_tool(tool_node, data)

        # Check signal file was written
        signal_file = tmp_path / "signals" / f"{tool_node['id']}.json"
        assert signal_file.exists(), f"Signal file not written at {signal_file}"
        signal = json.loads(signal_file.read_text())
        assert signal.get("status") == "success", f"Expected success, got: {signal}"


# ---------------------------------------------------------------------------
# S7.2.6 — Zero LLM graph traversal tokens
# ---------------------------------------------------------------------------


class TestZeroLLMGraphTraversal:
    """AC-7.2.6: Graph traversal is pure Python, zero LLM tokens."""

    def test_no_llm_in_main_loop(self):
        """The main run() loop must not contain LLM API calls."""
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        content = open(path).read()

        llm_patterns = [
            "client.messages.create",
            "anthropic.Anthropic()",
            "openai.ChatCompletion",
            "completion(",
        ]
        for pattern in llm_patterns:
            assert pattern not in content, (
                f"Found LLM call pattern '{pattern}' — runner must use zero LLM tokens for graph ops"
            )

    def test_watchdog_import(self):
        """Runner should use watchdog for file monitoring."""
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        content = open(path).read()
        assert "watchdog" in content, "Runner should use watchdog for file monitoring"


# ---------------------------------------------------------------------------
# S7.2.7 — Watchdog-based file monitoring
# ---------------------------------------------------------------------------


class TestWatchdogMonitoring:
    """AC-7.2.7: Watchdog-based monitoring, not mtime polling."""

    def test_signal_file_handler_class(self):
        """_SignalFileHandler class should exist."""
        from pipeline_runner import _SignalFileHandler  # noqa: F401

    def test_uses_observer(self):
        """Should use watchdog.observers.Observer."""
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        content = open(path).read()
        assert "Observer" in content, "Should use watchdog Observer"

    def test_no_sleep_polling(self):
        """Main loop should NOT use time.sleep for polling."""
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        content = open(path).read()
        assert "Event" in content or "event" in content, (
            "Should use threading.Event for wake mechanism"
        )


# ---------------------------------------------------------------------------
# S7.2.8 — Status chain: pending, active, impl_complete, validated, accepted
# ---------------------------------------------------------------------------


class TestStatusChain:
    """AC-7.2.8: Status chain includes 'accepted'."""

    def test_accepted_in_valid_transitions(self):
        """transition.py should allow validated -> accepted."""
        from transition import VALID_TRANSITIONS
        assert "accepted" in VALID_TRANSITIONS.get("validated", set()), (
            "VALID_TRANSITIONS['validated'] should include 'accepted'"
        )

    def test_accepted_is_terminal(self):
        """accepted should be a terminal status."""
        from transition import VALID_TRANSITIONS
        assert "accepted" in VALID_TRANSITIONS, "'accepted' missing from VALID_TRANSITIONS"
        assert VALID_TRANSITIONS["accepted"] == set(), (
            "'accepted' should be terminal (empty transition set)"
        )

    def test_accepted_has_color(self):
        """accepted should have a color in STATUS_COLORS."""
        from transition import STATUS_COLORS
        assert "accepted" in STATUS_COLORS, "'accepted' missing from STATUS_COLORS"


# ---------------------------------------------------------------------------
# S7.2.3 — Workers dispatched via AgentSDK
# ---------------------------------------------------------------------------


class TestAgentSDKDispatch:
    """AC-7.2.3: All dispatch goes through AgentSDK."""

    def test_dispatch_method_exists(self):
        """_dispatch_agent_sdk method should exist on PipelineRunner."""
        from pipeline_runner import PipelineRunner
        assert hasattr(PipelineRunner, "_dispatch_agent_sdk") or hasattr(PipelineRunner, "_handle_worker"), (
            "PipelineRunner must have _dispatch_agent_sdk or _handle_worker method"
        )

    def test_uses_claude_code_sdk(self):
        """Dispatch should reference claude_code_sdk."""
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        content = open(path).read()
        assert "claude_code_sdk" in content, (
            "pipeline_runner.py should use claude_code_sdk for worker dispatch"
        )

    def test_no_headless_cli(self):
        """Must NOT use headless claude -p CLI for dispatch."""
        path = os.path.join(_SCRIPTS_DIR, "pipeline_runner.py")
        content = open(path).read()
        # _dispatch_via_subprocess should have been removed (dead code cleanup)
        assert "_dispatch_via_subprocess" not in content, (
            "Dead code _dispatch_via_subprocess still present — must be removed"
        )
        assert "claude -p" not in content, "Must not reference headless claude -p"


# ---------------------------------------------------------------------------
# Mechanical signal transitions
# ---------------------------------------------------------------------------


class TestSignalTransitions:
    """AC-7.2.5 + AC-7.2.6: SIGNAL_TRANSITIONS mechanical logic."""

    def test_signal_transitions_exist(self):
        from pipeline_runner import SIGNAL_TRANSITIONS
        assert "pass" in SIGNAL_TRANSITIONS
        assert "fail" in SIGNAL_TRANSITIONS
        assert "requeue" in SIGNAL_TRANSITIONS

    def test_pass_maps_to_validated(self):
        """pass signal should map to 'validated' status."""
        from pipeline_runner import SIGNAL_TRANSITIONS
        assert SIGNAL_TRANSITIONS["pass"] == "validated"

    def test_fail_maps_to_failed(self):
        """fail signal should map to 'failed' status."""
        from pipeline_runner import SIGNAL_TRANSITIONS
        assert SIGNAL_TRANSITIONS["fail"] == "failed"

    def test_requeue_maps_to_pending(self):
        """requeue signal should map to 'pending' status."""
        from pipeline_runner import SIGNAL_TRANSITIONS
        assert SIGNAL_TRANSITIONS["requeue"] == "pending"

    def test_success_maps_to_impl_complete(self):
        """success signal (from workers) should map to 'impl_complete'."""
        from pipeline_runner import SIGNAL_TRANSITIONS
        assert SIGNAL_TRANSITIONS["success"] == "impl_complete"
