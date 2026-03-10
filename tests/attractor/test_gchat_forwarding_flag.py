"""Tests for GCHAT_FORWARDING_ENABLED flag in gchat-ask-user-forward.py hook."""
import json
import os
import subprocess
import sys
import unittest

HOOK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".claude", "hooks", "gchat-ask-user-forward.py"
)

def _run_hook(env_vars: dict, stdin_data: dict) -> dict:
    """Run the hook as a subprocess and return parsed JSON output."""
    env = os.environ.copy()
    # Clear any existing forwarding flag
    env.pop("GCHAT_FORWARDING_ENABLED", None)
    env.update(env_vars)
    # Ensure CLAUDE_PROJECT_DIR is set (hook needs it)
    if "CLAUDE_PROJECT_DIR" not in env:
        env["CLAUDE_PROJECT_DIR"] = "/tmp"

    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=json.dumps(stdin_data),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    # Hook outputs JSON to stdout
    return json.loads(result.stdout.strip().split("\n")[-1])


_VALID_INPUT = {
    "session_id": "test-session-001",
    "tool_name": "AskUserQuestion",
    "tool_input": {"questions": [{"question": "Test question?", "id": "q1"}]},
}


class TestGChatForwardingFlag(unittest.TestCase):
    """Tests for the GCHAT_FORWARDING_ENABLED env var check."""

    def test_forwarding_disabled_when_unset(self):
        """No GCHAT_FORWARDING_ENABLED -> approve (no forwarding)."""
        result = _run_hook({}, _VALID_INPUT)
        self.assertEqual(result["decision"], "approve")

    def test_forwarding_disabled_when_empty(self):
        """GCHAT_FORWARDING_ENABLED='' -> approve."""
        result = _run_hook({"GCHAT_FORWARDING_ENABLED": ""}, _VALID_INPUT)
        self.assertEqual(result["decision"], "approve")

    def test_forwarding_disabled_when_false(self):
        """GCHAT_FORWARDING_ENABLED=false -> approve."""
        result = _run_hook({"GCHAT_FORWARDING_ENABLED": "false"}, _VALID_INPUT)
        self.assertEqual(result["decision"], "approve")

    def test_forwarding_disabled_when_zero(self):
        """GCHAT_FORWARDING_ENABLED=0 -> approve."""
        result = _run_hook({"GCHAT_FORWARDING_ENABLED": "0"}, _VALID_INPUT)
        self.assertEqual(result["decision"], "approve")

    def test_forwarding_disabled_when_FALSE_uppercase(self):
        """GCHAT_FORWARDING_ENABLED=FALSE -> approve."""
        result = _run_hook({"GCHAT_FORWARDING_ENABLED": "FALSE"}, _VALID_INPUT)
        self.assertEqual(result["decision"], "approve")

    def test_forwarding_disabled_when_random_string(self):
        """GCHAT_FORWARDING_ENABLED=banana -> approve (not 'true' or '1')."""
        result = _run_hook({"GCHAT_FORWARDING_ENABLED": "banana"}, _VALID_INPUT)
        self.assertEqual(result["decision"], "approve")


if __name__ == "__main__":
    unittest.main(verbosity=2)
