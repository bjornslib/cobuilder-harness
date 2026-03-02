#!/usr/bin/env python3
"""
GChat Thread Correlation Prototype
===================================

Validates the core mechanism for PRD-GCHAT-HOOKS-001:
  1. Send a question to GChat via webhook with a unique threadKey
  2. Capture the full thread resource name from the webhook response
  3. Poll for user's reply using the MCP server's message queue
  4. Detect and return the response

This is a RESEARCH PROTOTYPE — not the final implementation.
The final implementation will use:
  - PreToolUse hook (sends question, captures thread resource name)
  - One-shot Haiku Task (polls for response via MCP tools)

This prototype validates the mechanism using direct API calls
and the google-chat-bridge modules.

Usage:
    # Interactive test (sends question, waits for your GChat reply)
    python3 gchat-thread-correlation.py --interactive

    # Dry run (just validates threadKey → thread resource name mapping)
    python3 gchat-thread-correlation.py --dry-run

    # Test two concurrent threads (no cross-contamination)
    python3 gchat-thread-correlation.py --concurrent

Environment Variables:
    GOOGLE_CHAT_WEBHOOK_URL     - Webhook URL for outbound
    GOOGLE_CHAT_CREDENTIALS_FILE - Service account JSON for inbound (optional)

Requirements:
    pip install google-auth google-api-python-client  (for inbound polling)
    OR just use --dry-run mode (webhook only, no inbound)
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", "")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CHAT_CREDENTIALS_FILE", "")

# Polling config
POLL_INTERVAL_SECONDS = 10
MAX_POLL_ITERATIONS = 30  # 5 minutes max
THREAD_KEY_PREFIX = "proto-ask"


def generate_thread_key(label: str = "") -> str:
    """Generate a unique threadKey for a question."""
    short_uuid = uuid.uuid4().hex[:8]
    ts = datetime.now(timezone.utc).strftime("%H%M%S")
    suffix = f"-{label}" if label else ""
    return f"{THREAD_KEY_PREFIX}-{ts}-{short_uuid}{suffix}"


# ---------------------------------------------------------------------------
# Webhook (Outbound)
# ---------------------------------------------------------------------------

def send_question_via_webhook(
    question_text: str,
    options: list[str],
    thread_key: str,
) -> dict:
    """
    Send a formatted question to GChat via webhook with threadKey.
    Returns the full API response (including thread resource name).
    """
    if not WEBHOOK_URL:
        log.error("GOOGLE_CHAT_WEBHOOK_URL not set")
        sys.exit(1)

    # Format the question
    formatted_options = "\n".join(
        f"  {i+1}. {opt}" for i, opt in enumerate(options)
    )
    message = (
        f"*[Prototype Test]* Thread correlation test\n\n"
        f"*Question:* {question_text}\n\n"
        f"*Options:*\n{formatted_options}\n\n"
        f"Reply with the option number or type a custom response.\n"
        f"_Thread key: `{thread_key}`_"
    )

    # Build request body with threadKey
    body = {
        "text": message,
        "thread": {"threadKey": thread_key},
    }

    # POST to webhook with thread reply option
    url = f"{WEBHOOK_URL}&messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )

    try:
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read())
        return result
    except Exception as e:
        log.error("Webhook POST failed: %s", e)
        sys.exit(1)


def extract_thread_resource_name(webhook_response: dict) -> str:
    """Extract the full thread resource name from webhook response."""
    thread = webhook_response.get("thread", {})
    thread_name = thread.get("name", "")
    if not thread_name:
        log.warning(
            "No thread.name in webhook response. Full response: %s",
            json.dumps(webhook_response, indent=2),
        )
    return thread_name


# ---------------------------------------------------------------------------
# Inbound Polling (via google-chat-bridge modules)
# ---------------------------------------------------------------------------

def try_import_chat_client():
    """Try to import the google-chat-bridge chat client."""
    # Add the MCP server source to sys.path
    bridge_src = Path(__file__).resolve().parents[3] / "mcp-servers" / "google-chat-bridge" / "src"
    if bridge_src.exists():
        sys.path.insert(0, str(bridge_src))
        try:
            from google_chat_bridge.chat_client import ChatClient
            return ChatClient
        except ImportError as e:
            log.warning("Could not import ChatClient: %s", e)
            return None
    return None


def poll_for_response_direct(
    thread_resource_name: str,
    our_message_name: str,
    timeout_iterations: int = MAX_POLL_ITERATIONS,
) -> str | None:
    """
    Poll GChat API directly for a reply in the specific thread.
    Uses the google-chat-bridge ChatClient for authenticated API access.

    Returns the user's response text, or None on timeout.
    """
    ChatClient = try_import_chat_client()
    if ChatClient is None:
        log.error(
            "Cannot import ChatClient. "
            "Install google-auth and google-api-python-client, "
            "or use --dry-run mode."
        )
        return None

    try:
        client = ChatClient(credentials_file=CREDENTIALS_FILE or None)
    except Exception as e:
        log.error("Failed to initialize ChatClient: %s", e)
        return None

    # Extract space_id from thread resource name
    # Format: spaces/{space_id}/threads/{thread_id}
    parts = thread_resource_name.split("/")
    if len(parts) >= 2:
        space_id = parts[1]
    else:
        log.error("Invalid thread resource name format: %s", thread_resource_name)
        return None

    log.info("Polling thread: %s (space: %s)", thread_resource_name, space_id)
    log.info("Our message name: %s", our_message_name)

    for i in range(timeout_iterations):
        log.info("Poll iteration %d/%d...", i + 1, timeout_iterations)
        try:
            # Fetch recent messages from the space
            messages = client.list_messages(space_id=space_id, page_size=20)

            # Filter for messages in our thread that aren't our own
            thread_replies = [
                m for m in messages
                if m.thread_name == thread_resource_name
                and m.name != our_message_name
                and not _is_bot_message(m)
            ]

            if thread_replies:
                # Take the first non-bot reply
                reply = thread_replies[0]
                log.info(
                    "Response found from %s: %s",
                    reply.sender_display_name,
                    reply.text[:100],
                )
                return reply.text

        except Exception as e:
            log.warning("Poll error (will retry): %s", e)

        if i < timeout_iterations - 1:
            log.info("No response yet. Sleeping %ds...", POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)

    log.warning("Timeout: no response after %d iterations", timeout_iterations)
    return None


def _is_bot_message(message) -> bool:
    """Check if a message was sent by a bot (webhook or API sender)."""
    # Bot messages typically have sender_type == "BOT" or sender_name containing "users/"
    # Webhook messages may not have sender info or have a bot-like sender
    sender = getattr(message, "sender_name", "")
    sender_type = getattr(message, "sender_type", "")
    if sender_type == "BOT":
        return True
    # Webhook messages often have no sender or a generic sender
    if not sender or "bot" in sender.lower():
        return True
    return False


# ---------------------------------------------------------------------------
# Test Scenarios
# ---------------------------------------------------------------------------

def test_dry_run():
    """
    Dry run: Send question, verify threadKey → thread resource name mapping.
    Does NOT wait for response.
    """
    log.info("=" * 60)
    log.info("DRY RUN: Testing threadKey → thread resource name mapping")
    log.info("=" * 60)

    thread_key = generate_thread_key("dryrun")
    log.info("Generated threadKey: %s", thread_key)

    response = send_question_via_webhook(
        question_text="[DRY RUN] Testing thread correlation — please ignore",
        options=["Option A (test)", "Option B (test)", "Option C (test)"],
        thread_key=thread_key,
    )

    log.info("Webhook response received:")
    log.info("  Message name: %s", response.get("name", "N/A"))

    thread_name = extract_thread_resource_name(response)
    log.info("  Thread resource name: %s", thread_name)
    log.info("  Thread key used: %s", thread_key)

    if thread_name:
        log.info("")
        log.info("RESULT: threadKey '%s' → thread '%s'", thread_key, thread_name)
        log.info("STATUS: PASS — Thread resource name successfully extracted")

        # Verify format
        if "/" in thread_name and "threads" in thread_name:
            log.info("FORMAT: Valid (contains 'threads/' path segment)")
        else:
            log.warning("FORMAT: Unexpected — expected 'spaces/X/threads/Y'")
    else:
        log.error("RESULT: FAIL — No thread resource name in response")
        log.error("Full response: %s", json.dumps(response, indent=2))
        return False

    log.info("")
    log.info("Mapping table:")
    log.info("  +-----------------------+-----------------------------------------------+")
    log.info("  | Layer                 | Value                                         |")
    log.info("  +-----------------------+-----------------------------------------------+")
    log.info("  | threadKey (send)      | %-45s |", thread_key)
    log.info("  | thread.name (receive) | %-45s |", thread_name)
    log.info("  +-----------------------+-----------------------------------------------+")
    return True


def test_interactive():
    """
    Interactive test: Send question to GChat, wait for your reply.
    Validates the full round-trip.
    """
    log.info("=" * 60)
    log.info("INTERACTIVE TEST: Full round-trip question → response")
    log.info("=" * 60)

    thread_key = generate_thread_key("interactive")
    log.info("Generated threadKey: %s", thread_key)

    response = send_question_via_webhook(
        question_text="Which approach should we use for the new feature?",
        options=[
            "Approach A — Hook-based (recommended)",
            "Approach B — Daemon-based",
            "Approach C — MCP tool-based",
        ],
        thread_key=thread_key,
    )

    thread_name = extract_thread_resource_name(response)
    our_message_name = response.get("name", "")

    if not thread_name:
        log.error("FAIL: No thread resource name. Cannot poll.")
        return False

    log.info("Question sent to GChat!")
    log.info("  Thread: %s", thread_name)
    log.info("  Message: %s", our_message_name)
    log.info("")
    log.info(">>> Go to Google Chat and reply to the question <<<")
    log.info(">>> (reply with a number 1-3 or custom text)    <<<")
    log.info("")

    user_response = poll_for_response_direct(
        thread_resource_name=thread_name,
        our_message_name=our_message_name,
        timeout_iterations=MAX_POLL_ITERATIONS,
    )

    if user_response:
        log.info("")
        log.info("RESULT: Response received!")
        log.info("  User said: %s", user_response)

        # Parse option number
        stripped = user_response.strip()
        if stripped in ("1", "2", "3"):
            options = [
                "Approach A — Hook-based (recommended)",
                "Approach B — Daemon-based",
                "Approach C — MCP tool-based",
            ]
            log.info("  Mapped to: %s", options[int(stripped) - 1])
        else:
            log.info("  (Free text response — would be treated as 'Other')")

        log.info("STATUS: PASS — Full round-trip validated")
        return True
    else:
        log.info("")
        log.info("RESULT: Timeout — no response received")
        log.info("STATUS: PARTIAL — Outbound works, inbound not validated")
        return False


def test_concurrent():
    """
    Concurrent test: Send two questions with different threadKeys.
    Verify they create separate threads and don't cross-contaminate.
    """
    log.info("=" * 60)
    log.info("CONCURRENT TEST: Two threads, no cross-contamination")
    log.info("=" * 60)

    key_a = generate_thread_key("sessionA")
    key_b = generate_thread_key("sessionB")
    log.info("Thread A key: %s", key_a)
    log.info("Thread B key: %s", key_b)

    # Send both questions
    resp_a = send_question_via_webhook(
        question_text="[Session A] Which database should we use?",
        options=["PostgreSQL", "MySQL", "MongoDB"],
        thread_key=key_a,
    )
    thread_a = extract_thread_resource_name(resp_a)
    log.info("Thread A resource name: %s", thread_a)

    resp_b = send_question_via_webhook(
        question_text="[Session B] Which framework should we use?",
        options=["FastAPI", "Django", "Flask"],
        thread_key=key_b,
    )
    thread_b = extract_thread_resource_name(resp_b)
    log.info("Thread B resource name: %s", thread_b)

    # Verify they're different threads
    if thread_a and thread_b:
        if thread_a != thread_b:
            log.info("")
            log.info("RESULT: PASS — Two distinct threads created")
            log.info("  Thread A: %s", thread_a)
            log.info("  Thread B: %s", thread_b)
            log.info("")
            log.info("Cross-contamination test:")
            log.info("  A poller would query: get_thread_messages(thread_id='%s')", thread_a)
            log.info("  B poller would query: get_thread_messages(thread_id='%s')", thread_b)
            log.info("  These are different resource names → no cross-contamination")
            return True
        else:
            log.error("FAIL: Both questions ended up in the SAME thread!")
            return False
    else:
        log.error("FAIL: Could not extract thread names from one or both responses")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="GChat Thread Correlation Prototype",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Send question and verify threadKey mapping (no polling)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Send question and wait for your GChat reply",
    )
    parser.add_argument(
        "--concurrent",
        action="store_true",
        help="Test two concurrent threads for cross-contamination",
    )
    args = parser.parse_args()

    if not any([args.dry_run, args.interactive, args.concurrent]):
        parser.print_help()
        print("\nRun with --dry-run for a quick validation test.")
        sys.exit(0)

    if args.dry_run:
        success = test_dry_run()
    elif args.interactive:
        success = test_interactive()
    elif args.concurrent:
        success = test_concurrent()
    else:
        success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
