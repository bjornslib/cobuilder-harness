"""Google Chat Channel Adapter.

Implements the ChannelAdapter ABC for Google Chat, enabling the pipeline
runner to receive commands and send status updates via Google Chat.

GChat webhook payload format (from Google Chat API):
    {
        "type": "MESSAGE",
        "eventTime": "...",
        "message": {
            "name": "spaces/.../messages/...",
            "text": "approve node_backend",
            "sender": {"displayName": "Alice", "name": "users/123"},
            "thread": {"name": "spaces/.../threads/..."}
        }
    }

GChat outbound card format (cardsV2):
    {
        "cardsV2": [{
            "cardId": "pipeline-status",
            "card": {
                "header": {"title": "...", "subtitle": "..."},
                "sections": [{"widgets": [...]}]
            }
        }]
    }

Authentication:
    Inbound verification uses the token-based approach (simpler than JWT).
    Set `verification_token` to the value from the Google Chat API console.
    Empty token disables verification (development only).

See PRD-S3-ATTRACTOR-002 Epic 2 for full specification.
"""

from __future__ import annotations

import hmac
import re
from typing import Any

import httpx

from cobuilder.attractor.channel_adapter import ChannelAdapter, InboundMessage, OutboundMessage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Status icons for pipeline stages and node states
_STAGE_ICONS: dict[str, str] = {
    "PARSE": "📋",
    "VALIDATE": "🔍",
    "INITIALIZE": "🚀",
    "EXECUTE": "⚙️",
    "FINALIZE": "🏁",
}

_NODE_STATUS_ICONS: dict[str, str] = {
    "pending": "⏳",
    "active": "🔄",
    "impl_complete": "🔵",
    "validated": "✅",
    "failed": "❌",
    "blocked": "🚫",
}

# Max number of actions/blocked nodes to show in a card (readability)
_MAX_CARD_ACTIONS = 5
_MAX_CARD_BLOCKED = 3
_MAX_CARD_COMPLETED = 6


class GChatAdapter(ChannelAdapter):
    """Google Chat implementation of the ChannelAdapter ABC.

    Supports:
    - Parsing incoming webhook events from Google Chat (MESSAGE, ADDED_TO_SPACE)
    - Sending text messages and rich cards via Google Chat incoming webhook
    - Verifying webhook authenticity via bearer token or body token
    - Formatting RunnerPlan data as Google Chat Cards v2

    Uses httpx for all async HTTP calls. The webhook URL is used for both
    sending and (optionally) as the space identifier.

    Args:
        webhook_url: Google Chat incoming webhook URL for posting messages.
            Format: https://chat.googleapis.com/v1/spaces/.../messages?key=...&token=...
        verification_token: Token for authenticating incoming webhooks.
            Empty string disables verification (safe only in development).
        space_name: Google Chat space name (e.g., "spaces/AAAA123").
            Used as fallback when space cannot be extracted from webhook payload.
        timeout: HTTP request timeout in seconds for outbound calls.

    Example:
        adapter = GChatAdapter(
            webhook_url="https://chat.googleapis.com/v1/spaces/AAA/messages?...",
            verification_token="my-secret-token",
            space_name="spaces/AAA",
        )
        msg = await adapter.parse_inbound(webhook_payload)
        await adapter.send_outbound(
            OutboundMessage(text="Pipeline started"),
            recipient="spaces/AAA",
        )
    """

    def __init__(
        self,
        webhook_url: str,
        verification_token: str = "",
        space_name: str = "",
        timeout: float = 10.0,
    ) -> None:
        self._webhook_url = webhook_url
        self._verification_token = verification_token
        self._space_name = space_name
        self._timeout = timeout

    async def parse_inbound(self, raw_payload: dict) -> InboundMessage:
        """Parse a Google Chat webhook event into a normalized InboundMessage.

        Handles MESSAGE and ADDED_TO_SPACE event types. Strips bot @mention
        prefixes from message text (format: "<users/123...> remaining text").

        Args:
            raw_payload: Raw JSON payload from Google Chat webhook.

        Returns:
            Normalized InboundMessage with channel="gchat".

        Raises:
            ValueError: If the payload is missing required fields.
        """
        event_type = raw_payload.get("type", "MESSAGE")
        message = raw_payload.get("message", {})

        if not message and event_type == "ADDED_TO_SPACE":
            # Bot was added to a space — no message to parse
            return InboundMessage(
                channel="gchat",
                sender_id="system",
                text="",
                thread_id=None,
                metadata={"event_type": event_type, "space": self._space_name},
            )

        # Extract sender
        sender = message.get("sender", {})
        sender_id = sender.get("name", "") or sender.get("displayName", "unknown")

        # Extract and clean message text
        text = message.get("text", "").strip()

        # Strip bot @mention: "<users/105...> " prefix pattern
        text = _strip_mention(text)

        # Extract thread context
        thread = message.get("thread") or {}
        thread_id = thread.get("name") if thread else None

        # Extract space name from message resource name
        # Message name format: "spaces/AAAA/messages/BBBB"
        msg_name = message.get("name", "")
        space = _extract_space_from_name(msg_name) or self._space_name

        return InboundMessage(
            channel="gchat",
            sender_id=sender_id,
            text=text,
            thread_id=thread_id,
            metadata={
                "event_type": event_type,
                "space": space,
                "raw_sender": sender,
                "message_name": msg_name,
            },
        )

    async def send_outbound(self, message: OutboundMessage, recipient: str) -> dict:
        """Send a message to Google Chat via the configured webhook URL.

        When message.card is set, sends a cardsV2 message with text as fallback.
        When message.thread_id is set, replies in that thread.

        Args:
            message: The normalized outbound message to send.
            recipient: Google Chat space or thread target. Currently used for
                routing context; the webhook URL is used for actual delivery.

        Returns:
            The Google Chat API response body as a dict.

        Raises:
            httpx.HTTPStatusError: If the API returns a non-2xx response.
            httpx.TimeoutException: If the request exceeds the configured timeout.
        """
        body: dict[str, Any] = {}

        if message.card is not None:
            # Rich card message — wrap in cardsV2 array
            body["cardsV2"] = [
                {
                    "cardId": "pipeline-status",
                    "card": message.card,
                }
            ]
            # Include text as fallback for clients that don't render cards
            if message.text:
                body["text"] = message.text
        else:
            body["text"] = message.text

        # Thread affinity: reply in the same thread if thread_id is set
        if message.thread_id:
            body["thread"] = {"name": message.thread_id}

        # For threaded replies, append messageReplyOption parameter
        url = self._webhook_url
        if message.thread_id and "messageReplyOption" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}messageReplyOption=REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            return response.json()

    async def verify_webhook(self, request: dict) -> bool:
        """Verify incoming webhook authenticity using token comparison.

        Supports two verification methods:
        1. Bearer token in Authorization header (recommended)
        2. Token in query parameter or request body

        Always returns True if no verification_token is configured (dev mode).

        Args:
            request: Dict containing webhook request context.
                Expected keys:
                    "headers": Dict of HTTP request headers.
                    "token": Token from query parameter or body (fallback).

        Returns:
            True if the request is authentic or if verification is disabled.
            False if the token is missing or does not match.
        """
        if not self._verification_token:
            # No verification configured — allow all (development only)
            return True

        # Method 1: Bearer token from Authorization header
        headers = request.get("headers", {})
        auth_header = headers.get("Authorization", headers.get("authorization", ""))
        if auth_header.startswith("Bearer "):
            provided = auth_header[len("Bearer "):]
            return hmac.compare_digest(provided, self._verification_token)

        # Method 2: Token from query parameter or body field
        token = request.get("token", "")
        if token:
            return hmac.compare_digest(str(token), self._verification_token)

        # No token found
        return False

    def format_card(self, pipeline_status: dict) -> dict:
        """Format a pipeline status dict as a Google Chat Card (v2 format).

        Produces the inner "card" object suitable for the `cardsV2[].card` field.
        The caller wraps this in `{"cardsV2": [{"cardId": ..., "card": <result>}]}`.

        Args:
            pipeline_status: Dict representation of a RunnerPlan. Expected keys:
                pipeline_id: str — pipeline name/ID
                prd_ref: str — PRD reference (e.g., "PRD-AUTH-001")
                current_stage: str — PARSE|VALIDATE|INITIALIZE|EXECUTE|FINALIZE
                summary: str — human-readable status summary
                actions: list[dict] — NodeAction dicts (node_id, action, priority)
                blocked_nodes: list[dict] — BlockedNode dicts (node_id, reason)
                completed_nodes: list[str] — node IDs in validated state
                pipeline_complete: bool — True when pipeline is done

        Returns:
            Google Chat card dict with "header" and "sections" keys.
        """
        pipeline_id = pipeline_status.get("pipeline_id", "unknown")
        prd_ref = pipeline_status.get("prd_ref", "")
        stage = pipeline_status.get("current_stage", "EXECUTE")
        summary = pipeline_status.get("summary", "")
        actions: list[dict] = pipeline_status.get("actions", [])
        blocked: list[dict] = pipeline_status.get("blocked_nodes", [])
        completed: list[str] = pipeline_status.get("completed_nodes", [])
        is_complete: bool = pipeline_status.get("pipeline_complete", False)

        stage_icon = _STAGE_ICONS.get(stage, "⚙️")

        # Card header
        subtitle = prd_ref if prd_ref else stage
        header: dict[str, Any] = {
            "title": f"Pipeline: {pipeline_id}",
            "subtitle": subtitle,
        }

        # Build widget list
        widgets: list[dict[str, Any]] = []

        # Status row (stage + completion)
        if is_complete:
            status_text = "✅ Pipeline COMPLETE"
            status_icon = "STAR"
        else:
            status_text = f"{stage_icon} {stage}"
            status_icon = "CLOCK"

        widgets.append(
            _kv_widget("Status", status_text, icon=status_icon)
        )

        # Summary paragraph
        if summary:
            widgets.append(_text_widget(f"<b>Summary:</b> {summary}"))

        # Next actions (capped for readability)
        if actions:
            lines: list[str] = []
            for act in actions[:_MAX_CARD_ACTIONS]:
                node = act.get("node_id", "?")
                action_type = act.get("action", "?")
                priority = act.get("priority", "normal")
                icon = "🔴" if priority == "high" else "🔵"
                lines.append(f"{icon} <b>{node}</b>: {action_type}")
            if len(actions) > _MAX_CARD_ACTIONS:
                lines.append(f"… and {len(actions) - _MAX_CARD_ACTIONS} more")
            widgets.append(_text_widget("<b>Next Actions:</b><br>" + "<br>".join(lines)))

        # Blocked nodes (capped)
        if blocked:
            lines = []
            for b in blocked[:_MAX_CARD_BLOCKED]:
                node = b.get("node_id", "?")
                reason = b.get("reason", "unknown")
                lines.append(f"🚫 <b>{node}</b>: {reason}")
            if len(blocked) > _MAX_CARD_BLOCKED:
                lines.append(f"… and {len(blocked) - _MAX_CARD_BLOCKED} more blocked")
            widgets.append(_text_widget("<b>Blocked:</b><br>" + "<br>".join(lines)))

        # Completed nodes count
        if completed:
            n = len(completed)
            noun = "node" if n == 1 else "nodes"
            widgets.append(_kv_widget("Completed", f"✅ {n} {noun}", icon="DESCRIPTION"))

        return {
            "header": header,
            "sections": [{"widgets": widgets}],
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _strip_mention(text: str) -> str:
    """Remove Google Chat bot @mention prefix from message text.

    Google Chat prepends "<users/BOT_ID> " when a bot is @mentioned.
    This function strips that prefix so the command text is clean.

    Args:
        text: Raw message text possibly starting with a mention prefix.

    Returns:
        Clean text with any leading mention removed.
    """
    # Pattern: "<users/123456789012345678901> remaining text"
    # Also handles: "<space/...> " and "<users/...>"
    mention_pattern = re.compile(r"^<[^>]+>\s*")
    return mention_pattern.sub("", text).strip()


def _extract_space_from_name(msg_name: str) -> str:
    """Extract the space name from a Google Chat message resource name.

    Args:
        msg_name: Message resource name, e.g., "spaces/AAAA123/messages/BBB".

    Returns:
        Space name string (e.g., "spaces/AAAA123") or empty string if not parseable.
    """
    if not msg_name.startswith("spaces/"):
        return ""
    parts = msg_name.split("/")
    if len(parts) >= 2:
        return f"spaces/{parts[1]}"
    return ""


def send_review_request(
    node_id: str,
    pipeline_id: str,
    acceptance: str = "",
    mode: str = "technical",
) -> None:
    """Send a human-review gate notification to Google Chat via webhook.

    Reads the webhook URL from the GOOGLE_CHAT_WEBHOOK_URL environment variable.
    Falls back silently if the variable is unset.

    Args:
        node_id: Pipeline node ID that requires review (e.g., "e1_review").
        pipeline_id: Pipeline identifier (e.g., "PRD-NEWCHECK-001").
        acceptance: Acceptance criteria text from the node attributes.
        mode: Review mode ("technical" or "product").
    """
    import os

    webhook_url = os.environ.get("GOOGLE_CHAT_WEBHOOK_URL", "")
    if not webhook_url:
        return  # No webhook configured — skip silently

    mode_label = "Technical Review" if mode == "technical" else "Product Review"
    text_lines = [
        f"🔍 *Human Review Required* — {mode_label}",
        f"Pipeline: `{pipeline_id}`  Node: `{node_id}`",
    ]
    if acceptance:
        text_lines.append(f"Acceptance: {acceptance[:400]}")
    text_lines.append("Approve by writing a pass signal to the node's signal file.")

    payload = {"text": "\n".join(text_lines)}
    try:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
    except Exception:  # noqa: BLE001
        pass  # Caller already catches and logs


def _text_widget(text: str) -> dict[str, Any]:
    """Create a Google Chat textParagraph widget."""
    return {"textParagraph": {"text": text}}


def _kv_widget(
    label: str,
    value: str,
    icon: str = "",
) -> dict[str, Any]:
    """Create a Google Chat decoratedText (key-value) widget."""
    widget: dict[str, Any] = {
        "decoratedText": {
            "topLabel": label,
            "text": value,
        }
    }
    if icon:
        widget["decoratedText"]["startIcon"] = {"knownIcon": icon}
    return widget
