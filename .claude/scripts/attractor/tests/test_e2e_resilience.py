"""E2E Integration Tests for Session Resilience (Epic 5).

Tests the full integration of identity_registry, hook_manager, runner,
merge_queue, and spawn_orchestrator respawn wisdom injection.

All tests use tmp_path isolation — no real Claude API, tmux, or git operations.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import pytest

# Ensure the attractor package is importable
_ATTRACTOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ATTRACTOR_DIR not in sys.path:
    sys.path.insert(0, _ATTRACTOR_DIR)

import identity_registry
from identity_registry import (
    create_identity,
    find_stale,
    list_all,
    mark_crashed,
    read_identity,
    update_liveness,
)

import hook_manager
from hook_manager import (
    build_wisdom_prompt_block,
    create_hook,
    read_hook,
    update_phase,
    update_resumption_instructions,
)

import merge_queue
from merge_queue import _read_queue, enqueue, process_next

import runner
import spawn_orchestrator
from spawn_orchestrator import respawn_orchestrator


# ---------------------------------------------------------------------------
# TestIdentityRegistryCLI
# ---------------------------------------------------------------------------


class TestIdentityRegistryCLI:
    """Test identity_registry CLI mode end-to-end."""

    def test_create_and_update_liveness(self, tmp_path):
        """Create identity, then update liveness. Verify heartbeat changes."""
        state_dir = str(tmp_path / "identities")
        create_identity(
            role="runner",
            name="test_node",
            session_id="runner-test",
            worktree="/tmp",
            state_dir=state_dir,
        )
        original = read_identity("runner", "test_node", state_dir=state_dir)
        assert original is not None
        original_hb = original["last_heartbeat"]

        # Sleep to ensure timestamp changes (1s resolution)
        time.sleep(1.05)
        updated = update_liveness("runner", "test_node", state_dir=state_dir)

        assert updated["last_heartbeat"] != original_hb
        # Verify change persisted on disk
        on_disk = read_identity("runner", "test_node", state_dir=state_dir)
        assert on_disk["last_heartbeat"] == updated["last_heartbeat"]

    def test_find_stale_returns_empty_for_fresh_agents(self, tmp_path):
        """Freshly created agents should not be stale with a large timeout."""
        state_dir = str(tmp_path / "identities")
        create_identity(
            role="runner",
            name="fresh_node",
            session_id="runner-fresh",
            worktree="/tmp",
            state_dir=state_dir,
        )
        stale = find_stale(timeout_seconds=300, state_dir=state_dir)
        assert stale == []

    def test_list_json_output(self, tmp_path):
        """list_all() returns all created identities."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "node_a", "runner-node_a", "/tmp", state_dir=state_dir)
        create_identity("orchestrator", "node_b", "orch-node_b", "/tmp", state_dir=state_dir)

        all_agents = list_all(state_dir=state_dir)

        assert len(all_agents) == 2
        names = {a["name"] for a in all_agents}
        assert "node_a" in names
        assert "node_b" in names

    def test_mark_crashed_transitions_status(self, tmp_path):
        """mark_crashed sets status=crashed and crashed_at timestamp."""
        state_dir = str(tmp_path / "identities")
        create_identity("orchestrator", "crash_node", "orch-crash", "/tmp", state_dir=state_dir)

        mark_crashed("orchestrator", "crash_node", state_dir=state_dir)

        result = read_identity("orchestrator", "crash_node", state_dir=state_dir)
        assert result is not None
        assert result["status"] == "crashed"
        assert result["crashed_at"] is not None

    def test_find_stale_excludes_crashed_agents(self, tmp_path):
        """Crashed agents with old heartbeats should not appear in find_stale."""
        state_dir = str(tmp_path / "identities")
        create_identity("runner", "stale_crash", "runner-stale", "/tmp", state_dir=state_dir)
        mark_crashed("runner", "stale_crash", state_dir=state_dir)

        # Backdate heartbeat manually
        path = os.path.join(state_dir, "runner-stale_crash.json")
        with open(path) as fh:
            data = json.load(fh)
        data["last_heartbeat"] = "2020-01-01T00:00:00Z"
        with open(path, "w") as fh:
            json.dump(data, fh)

        stale = find_stale(timeout_seconds=1, state_dir=state_dir)
        assert stale == []


# ---------------------------------------------------------------------------
# TestHookManagerCLI
# ---------------------------------------------------------------------------


class TestHookManagerCLI:
    """Test hook_manager CLI mode and build_wisdom_prompt_block."""

    def test_create_and_update_phase(self, tmp_path):
        """Create hook, update phase, verify in state file."""
        state_dir = str(tmp_path / "hooks")
        create_hook(role="runner", name="test_node", state_dir=state_dir)
        update_phase("runner", "test_node", "executing", state_dir=state_dir)

        hook = read_hook("runner", "test_node", state_dir=state_dir)
        assert hook is not None
        assert hook["phase"] == "executing"

    def test_build_wisdom_prompt_block_with_executing_phase(self, tmp_path):
        """build_wisdom_prompt_block generates skip instructions for non-planning phases."""
        state_dir = str(tmp_path / "hooks")
        create_hook(role="runner", name="test_node", state_dir=state_dir)
        update_phase("runner", "test_node", "executing", state_dir=state_dir)
        update_resumption_instructions(
            "runner", "test_node", "Resume from step 3",
            last_committed_node="impl_auth",
            state_dir=state_dir,
        )

        hook = read_hook("runner", "test_node", state_dir=state_dir)
        block = build_wisdom_prompt_block(hook)

        assert "SKIP planning phase" in block
        assert "Last committed node: impl_auth" in block

    def test_build_wisdom_prompt_block_planning_no_skip(self):
        """build_wisdom_prompt_block in planning phase has no SKIP directive."""
        hook = {
            "phase": "planning",
            "resumption_instructions": "",
            "last_committed_node": "",
        }
        block = build_wisdom_prompt_block(hook)

        assert "SKIP" not in block
        assert "planning" in block

    def test_update_resumption_instructions(self, tmp_path):
        """update_resumption_instructions stores text in hook file."""
        state_dir = str(tmp_path / "hooks")
        create_hook(role="orchestrator", name="impl_auth", state_dir=state_dir)
        update_resumption_instructions(
            "orchestrator", "impl_auth", "Resume from step 3",
            state_dir=state_dir,
        )

        hook = read_hook("orchestrator", "impl_auth", state_dir=state_dir)
        assert hook is not None
        assert hook["resumption_instructions"] == "Resume from step 3"

    def test_build_wisdom_prompt_block_includes_resumption_notes(self, tmp_path):
        """build_wisdom_prompt_block includes resumption notes when present."""
        state_dir = str(tmp_path / "hooks")
        create_hook("orchestrator", "node_x", state_dir=state_dir)
        update_phase("orchestrator", "node_x", "validating", state_dir=state_dir)
        update_resumption_instructions(
            "orchestrator", "node_x", "Check the auth tests first",
            state_dir=state_dir,
        )

        hook = read_hook("orchestrator", "node_x", state_dir=state_dir)
        block = build_wisdom_prompt_block(hook)

        assert "Check the auth tests first" in block
        assert "RESUMPTION CONTEXT" in block

    def test_hook_phase_transitions_persist(self, tmp_path):
        """Phase transitions through full lifecycle persist correctly."""
        state_dir = str(tmp_path / "hooks")
        create_hook("runner", "lifecycle_node", state_dir=state_dir)

        for phase in ["executing", "impl_complete", "validating", "merged"]:
            update_phase("runner", "lifecycle_node", phase, state_dir=state_dir)
            hook = read_hook("runner", "lifecycle_node", state_dir=state_dir)
            assert hook["phase"] == phase


# ---------------------------------------------------------------------------
# TestSpawnRunnerIntegration
# ---------------------------------------------------------------------------


class TestSpawnRunnerIntegration:
    """Test that runner.py creates identity + hook before launch."""

    def _make_identity_side_effect(self, identity_dir):
        """Return a side_effect function that calls the real create_identity with tmp state_dir."""
        # Capture the real function before any patching
        _real_create_identity = identity_registry.create_identity

        def _side_effect(role, name, session_id, worktree, **kw):
            return _real_create_identity(
                role=role, name=name, session_id=session_id,
                worktree=worktree, state_dir=identity_dir,
            )

        return _side_effect

    def _make_hook_side_effect(self, hooks_dir):
        """Return a side_effect function that calls the real create_hook with tmp state_dir."""
        _real_create_hook = hook_manager.create_hook

        def _side_effect(role, name, phase="planning", **kw):
            return _real_create_hook(role=role, name=name, phase=phase, state_dir=hooks_dir)

        return _side_effect

    def test_spawn_runner_creates_identity(self, tmp_path):
        """runner.main() registers runner identity before Popen."""
        identity_dir = str(tmp_path / "identities")
        hooks_dir = str(tmp_path / "hooks")
        runner_state_dir = str(tmp_path / "runner-state")

        mock_proc = MagicMock()
        mock_proc.pid = 12345

        with patch("runner.subprocess.Popen", return_value=mock_proc) as mock_popen, \
             patch("runner.identity_registry.create_identity",
                   side_effect=self._make_identity_side_effect(identity_dir)) as mock_create_id, \
             patch("runner.hook_manager.create_hook",
                   side_effect=self._make_hook_side_effect(hooks_dir)), \
             patch("runner._runner_state_dir", return_value=runner_state_dir), \
             patch("sys.argv", ["runner.py", "--spawn",
                                "--node", "test_node",
                                "--prd", "PRD-TEST-001",
                                "--target-dir", str(tmp_path)]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                runner.main()

        # Verify identity creation was called
        assert mock_create_id.called

        # Verify the identity file was actually created
        identity_path = os.path.join(identity_dir, "runner-test_node.json")
        assert os.path.exists(identity_path), f"Identity file not found at {identity_path}"

        with open(identity_path) as fh:
            identity_data = json.load(fh)
        assert identity_data["role"] == "runner"
        assert identity_data["name"] == "test_node"

    def test_spawn_runner_creates_hook(self, tmp_path):
        """runner.main() creates hook with phase=planning before Popen."""
        identity_dir = str(tmp_path / "identities")
        hooks_dir = str(tmp_path / "hooks")
        runner_state_dir = str(tmp_path / "runner-state")

        mock_proc = MagicMock()
        mock_proc.pid = 99999

        with patch("runner.subprocess.Popen", return_value=mock_proc), \
             patch("runner.identity_registry.create_identity",
                   side_effect=self._make_identity_side_effect(identity_dir)), \
             patch("runner.hook_manager.create_hook",
                   side_effect=self._make_hook_side_effect(hooks_dir)) as mock_create_hook, \
             patch("runner._runner_state_dir", return_value=runner_state_dir), \
             patch("sys.argv", ["runner.py", "--spawn",
                                "--node", "hook_test_node",
                                "--prd", "PRD-TEST-002",
                                "--target-dir", str(tmp_path)]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                runner.main()

        # Verify hook creation was called
        assert mock_create_hook.called

        # Verify the hook file was actually created
        hook_path = os.path.join(hooks_dir, "runner-hook_test_node.json")
        assert os.path.exists(hook_path), f"Hook file not found at {hook_path}"

        with open(hook_path) as fh:
            hook_data = json.load(fh)
        assert hook_data["role"] == "runner"
        assert hook_data["name"] == "hook_test_node"
        assert hook_data["phase"] == "planning"

    def test_spawn_runner_writes_state_with_pid(self, tmp_path):
        """runner.main() writes state file with runner_pid field."""
        runner_state_dir = str(tmp_path / "runner-state")
        identity_dir = str(tmp_path / "identities")
        hooks_dir = str(tmp_path / "hooks")

        mock_proc = MagicMock()
        mock_proc.pid = 54321

        with patch("runner.subprocess.Popen", return_value=mock_proc), \
             patch("runner.identity_registry.create_identity",
                   side_effect=self._make_identity_side_effect(identity_dir)), \
             patch("runner.hook_manager.create_hook",
                   side_effect=self._make_hook_side_effect(hooks_dir)), \
             patch("runner._runner_state_dir", return_value=runner_state_dir), \
             patch("sys.argv", ["runner.py", "--spawn",
                                "--node", "pid_test_node",
                                "--prd", "PRD-TEST-003",
                                "--target-dir", str(tmp_path)]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                runner.main()

        # Verify output JSON contains runner_pid
        output = buf.getvalue()
        assert output.strip(), "Expected JSON output from spawn_runner.main()"
        data = json.loads(output)
        assert data["status"] == "ok"
        assert data["runner_pid"] == 54321

        # Verify state file was written in runner-state dir
        assert os.path.isdir(runner_state_dir)
        state_files = [f for f in os.listdir(runner_state_dir) if f.endswith(".json")]
        assert len(state_files) == 1

        with open(os.path.join(runner_state_dir, state_files[0])) as fh:
            state_data = json.load(fh)
        assert state_data["runner_pid"] == 54321
        assert state_data["node_id"] == "pid_test_node"


# ---------------------------------------------------------------------------
# TestMergeQueueCLI
# ---------------------------------------------------------------------------


class TestMergeQueueCLI:
    """Test merge_queue_cmd CLI integration."""

    def test_enqueue_and_list(self, tmp_path):
        """Enqueue an entry and verify it appears in list."""
        state_dir = str(tmp_path / "queue")
        os.makedirs(state_dir, exist_ok=True)

        entry = enqueue(
            node_id="test_node",
            branch="feature/test",
            repo_root=str(tmp_path),
            state_dir=state_dir,
        )

        assert entry["node_id"] == "test_node"
        assert entry["branch"] == "feature/test"
        assert entry["status"] == "pending"

        # Verify via list read
        queue = _read_queue(state_dir=state_dir)
        assert len(queue["entries"]) == 1
        assert queue["entries"][0]["node_id"] == "test_node"

    def test_process_next_on_empty_queue(self, tmp_path):
        """process_next() on empty queue returns success=True with entry=None."""
        state_dir = str(tmp_path / "queue")

        result = process_next(state_dir=state_dir)

        assert isinstance(result, dict)
        assert result["success"] is True
        assert result["entry"] is None
        assert result["error"] is None

    def test_enqueue_is_idempotent(self, tmp_path):
        """Enqueuing the same node_id twice returns existing entry without duplicate."""
        state_dir = str(tmp_path / "queue")

        entry1 = enqueue("dedup_node", "feature/dedup", str(tmp_path), state_dir=state_dir)
        entry2 = enqueue("dedup_node", "feature/dedup", str(tmp_path), state_dir=state_dir)

        assert entry1["entry_id"] == entry2["entry_id"]

        queue = _read_queue(state_dir=state_dir)
        assert len(queue["entries"]) == 1

    def test_enqueue_multiple_nodes(self, tmp_path):
        """Multiple different nodes create separate queue entries."""
        state_dir = str(tmp_path / "queue")

        enqueue("node_a", "feature/a", str(tmp_path), state_dir=state_dir)
        enqueue("node_b", "feature/b", str(tmp_path), state_dir=state_dir)
        enqueue("node_c", "feature/c", str(tmp_path), state_dir=state_dir)

        queue = _read_queue(state_dir=state_dir)
        assert len(queue["entries"]) == 3

        node_ids = {e["node_id"] for e in queue["entries"]}
        assert node_ids == {"node_a", "node_b", "node_c"}


# ---------------------------------------------------------------------------
# TestRespawnWisdomE2E
# ---------------------------------------------------------------------------


class TestRespawnWisdomE2E:
    """Test the respawn wisdom injection end-to-end."""

    def test_wisdom_injected_when_hook_exists(self, tmp_path):
        """respawn_orchestrator prepends wisdom when hook file found."""
        hooks_dir = str(tmp_path / "hooks")
        identity_dir = str(tmp_path / "identities")

        # Set up hook state
        create_hook("orchestrator", "auth_node", state_dir=hooks_dir)
        update_phase("orchestrator", "auth_node", "executing", state_dir=hooks_dir)
        update_resumption_instructions(
            "orchestrator", "auth_node", "Continue from step 2",
            last_committed_node="step_2",
            state_dir=hooks_dir,
        )

        hook = read_hook("orchestrator", "auth_node", state_dir=hooks_dir)

        # Patch hook_manager.read_hook to return our controlled hook
        with patch("spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("spawn_orchestrator.subprocess.run") as mock_run, \
             patch("spawn_orchestrator.time.sleep"), \
             patch("spawn_orchestrator._tmux_send") as mock_send, \
             patch("spawn_orchestrator.hook_manager.read_hook", return_value=hook), \
             patch("spawn_orchestrator.identity_registry.create_identity",
                   return_value={"agent_id": "test-id"}), \
             patch("spawn_orchestrator.hook_manager.create_hook",
                   return_value={"hook_id": "test-hook-id"}):
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator(
                "orch-auth",
                str(tmp_path),
                "auth_node",
                None,
                0,
                3,
            )

        assert result["status"] == "respawned"

        # Verify wisdom block was sent (3 calls: launch + output-style + wisdom-prompt)
        assert mock_send.call_count == 3

        send_calls = [str(c) for c in mock_send.call_args_list]
        assert any("RESUMPTION CONTEXT" in s for s in send_calls), (
            f"Expected RESUMPTION CONTEXT in send calls. Calls: {send_calls}"
        )
        assert any("step_2" in s for s in send_calls), (
            f"Expected last_committed_node 'step_2' in send calls. Calls: {send_calls}"
        )
        assert any("SKIP planning phase" in s for s in send_calls), (
            f"Expected SKIP planning phase directive in send calls. Calls: {send_calls}"
        )

    def test_wisdom_contains_executing_skip_directive(self, tmp_path):
        """Wisdom block for executing phase contains the SKIP planning directive."""
        hook = {
            "phase": "executing",
            "resumption_instructions": "Pick up auth endpoint",
            "last_committed_node": "impl_auth_db",
        }
        block = build_wisdom_prompt_block(hook)

        assert "SKIP planning phase" in block
        assert "go directly to executing" in block
        assert "impl_auth_db" in block
        assert "Pick up auth endpoint" in block

    def test_no_wisdom_for_planning_phase(self, tmp_path):
        """No SKIP directive in wisdom block when phase is planning."""
        hook = {
            "phase": "planning",
            "resumption_instructions": "",
            "last_committed_node": None,
        }
        block = build_wisdom_prompt_block(hook)

        assert "SKIP" not in block
        assert "RESUMPTION CONTEXT" in block

    def test_respawn_without_hook_sends_no_wisdom(self):
        """When no existing hook, respawn sends only launch and output-style commands."""
        with patch("spawn_orchestrator.check_orchestrator_alive", return_value=False), \
             patch("spawn_orchestrator.subprocess.run") as mock_run, \
             patch("spawn_orchestrator.time.sleep"), \
             patch("spawn_orchestrator._tmux_send") as mock_send, \
             patch("spawn_orchestrator.hook_manager.read_hook", return_value=None), \
             patch("spawn_orchestrator.identity_registry.create_identity",
                   return_value={"agent_id": "test-id"}), \
             patch("spawn_orchestrator.hook_manager.create_hook",
                   return_value={"hook_id": "test-hook-id"}):
            mock_run.return_value = MagicMock(returncode=0)
            result = respawn_orchestrator("orch-nobook", "/tmp", "nobook_node", None, 0, 3)

        assert result["status"] == "respawned"
        # Only 2 sends: launch + output-style (no wisdom prompt)
        assert mock_send.call_count == 2
