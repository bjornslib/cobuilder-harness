#!/usr/bin/env python3
"""Test launch_guardian._run_agent() Logfire instrumentation.

Calls the ACTUAL _run_agent() from launch_guardian.py with a 2-turn prompt.
Verifies guardian.tool_use + guardian.tool_result spans appear in Logfire.

Run:  CLAUDECODE= python3 .claude/scripts/attractor/test_logfire_guardian.py
"""

import asyncio
import os
import sys

# Ensure imports resolve
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from claude_code_sdk import ClaudeCodeOptions

# Import the actual _run_agent from guardian (merged from launch_guardian)
from guardian import _run_agent


async def main():
    options = ClaudeCodeOptions(
        max_turns=2,
        system_prompt="You are a test agent. Do exactly what is asked.",
    )
    prompt = "Run: echo 'logfire-guardian-ok'"
    await _run_agent(prompt, options)
    print("\nCheck Logfire: https://logfire-eu.pydantic.dev/faie/checkpro")


if __name__ == "__main__":
    asyncio.run(main())
