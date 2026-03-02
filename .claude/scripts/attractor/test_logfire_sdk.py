#!/usr/bin/env python3
"""Minimal test: claude_code_sdk query() + Logfire span capture.

Run:  python3 .claude/scripts/attractor/test_logfire_sdk.py

Verifies that tool_use, tool_result, assistant_text, and result spans
appear in Logfire at https://logfire-eu.pydantic.dev/faie/checkpro
"""

import asyncio
import json
import os
import time
from pathlib import Path

import logfire

# Gracefully handle missing Logfire project credentials:
# Auth is global (~/.logfire/default.toml) but project association requires
# .logfire/ in cwd or LOGFIRE_TOKEN. When neither exists, disable sending
# rather than triggering an interactive prompt that crashes non-interactive contexts.
_send_to_logfire = os.environ.get("LOGFIRE_SEND_TO_LOGFIRE", "").lower()
if _send_to_logfire == "false":
    _logfire_enabled = False
elif _send_to_logfire == "true":
    _logfire_enabled = True
else:
    _logfire_enabled = (
        Path(".logfire").is_dir()
        or bool(os.environ.get("LOGFIRE_TOKEN"))
    )

logfire.configure(
    send_to_logfire=_logfire_enabled,
    scrubbing=logfire.ScrubbingOptions(callback=lambda m: m.value),
)

from claude_code_sdk import (
    query,
    ClaudeCodeOptions,
    AssistantMessage,
    UserMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)


async def main():
    options = ClaudeCodeOptions(
        max_turns=3,
        system_prompt="You are a test agent. Do exactly what is asked, nothing more.",
    )

    prompt = "Run this command: echo 'logfire-test-ok' then tell me the output."

    turn_count = 0
    tool_call_count = 0
    t0 = time.time()

    with logfire.span("test_sdk.run"):
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                turn_count += 1
                for block in message.content:
                    if isinstance(block, TextBlock):
                        logfire.info(
                            "test_sdk.assistant_text",
                            turn=turn_count,
                            text_preview=block.text[:300] if block.text else "",
                        )
                        print(f"[text] {block.text}")

                    elif isinstance(block, ToolUseBlock):
                        tool_call_count += 1
                        input_preview = json.dumps(block.input)[:500]
                        logfire.info(
                            "test_sdk.tool_use",
                            tool_name=block.name,
                            tool_use_id=block.id,
                            tool_input_preview=input_preview,
                            turn=turn_count,
                        )
                        print(f"[tool_use] {block.name}: {input_preview[:200]}")

                    elif isinstance(block, ThinkingBlock):
                        logfire.info(
                            "test_sdk.thinking",
                            turn=turn_count,
                            thinking_preview=(block.thinking or "")[:200],
                        )
                        print(f"[thinking] {(block.thinking or '')[:100]}")

            elif isinstance(message, UserMessage):
                if isinstance(message.content, list):
                    for block in message.content:
                        if isinstance(block, ToolResultBlock):
                            content = ""
                            if isinstance(block.content, str):
                                content = block.content[:500]
                            elif isinstance(block.content, list):
                                content = json.dumps(block.content)[:500]
                            logfire.info(
                                "test_sdk.tool_result",
                                tool_use_id=block.tool_use_id,
                                is_error=block.is_error or False,
                                content_preview=content,
                            )
                            print(f"[tool_result] error={block.is_error} content={content[:100]}")

            elif isinstance(message, ResultMessage):
                elapsed = time.time() - t0
                logfire.info(
                    "test_sdk.result",
                    num_turns=message.num_turns,
                    total_cost_usd=message.total_cost_usd,
                    duration_ms=message.duration_ms,
                    wall_time_s=round(elapsed, 2),
                    total_tool_calls=tool_call_count,
                )
                print(f"[result] turns={message.num_turns} cost=${message.total_cost_usd} tools={tool_call_count} wall={elapsed:.1f}s")

    print(f"\nDone. Check Logfire: https://logfire-eu.pydantic.dev/faie/checkpro")


if __name__ == "__main__":
    asyncio.run(main())
