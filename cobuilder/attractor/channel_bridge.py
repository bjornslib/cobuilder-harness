"""Channel Bridge — routes messages between channel adapters and the pipeline runner.

The ChannelBridge is the translation layer between:

1. **External communication channels** (GChat, Slack, Web) using the
   ``channel_adapter.ChannelAdapter`` ABC (channel_adapter.py).
   These channels carry *user commands* (approve, reject, status, pause)
   and *runner notifications* (formatted text + cards).

2. **The internal pipeline runner** communication layer using the
   ``adapters.base.ChannelAdapter`` ABC (adapters/base.py).
   This layer carries *runner signals* (RUNNER_STUCK, AWAITING_APPROVAL,
   NODE_VALIDATED) and *runner commands* (approval granted/rejected).

Architecture::

                        ┌─────────────────────────────────────────┐
                        │            ChannelBridge                │
                        │                                         │
    GChat webhook  ───► │  parse_inbound                          │
                        │      → translate text to message_type   │
                        │      → forward to runner via send_signal│
                        │                                         │
    Runner signal  ───► │  broadcast_signal                       │
                        │      → format as OutboundMessage        │
                        │      → send_outbound to ALL channels    │
                        │                                         │
                        └─────────────────────────────────────────┘

Inbound command mapping::

    "approve [node_id]"  → message_type="approval"
    "reject [node_id]"   → message_type="override"
    "stop" / "halt"      → message_type="shutdown"
    "status" / "help"    → message_type="guidance"
    (anything else)      → message_type="guidance"

Outbound signal formatting::

    RUNNER_STARTED        → text summary, no card
    RUNNER_STUCK          → text + card (if pipeline_status provided)
    AWAITING_APPROVAL     → text + card (approval gate notification)
    RUNNER_COMPLETE       → text + card (pipeline done)
    NODE_* signals        → text summary, no card

See PRD-S3-ATTRACTOR-002 Epic 2 for full specification.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

# External channel adapter ABC (channel_adapter.py)
from cobuilder.attractor.channel_adapter import ChannelAdapter as ExternalAdapter
from cobuilder.attractor.channel_adapter import InboundMessage, OutboundMessage

# Internal runner channel adapter ABC (adapters/base.py)
# Imported at runtime to avoid circular dependency issues
try:
    from adapters.base import ChannelAdapter as RunnerAdapter
    from adapters.base import ChannelError
except ImportError:
    # Allow importing this module standalone (e.g., tests)
    RunnerAdapter = object  # type: ignore[misc,assignment]
    ChannelError = Exception  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Command → message_type mapping
# ---------------------------------------------------------------------------

_COMMAND_MAP: dict[str, str] = {
    "approve": "approval",
    "approved": "approval",
    "yes": "approval",
    "lgtm": "approval",
    "reject": "override",
    "rejected": "override",
    "deny": "override",
    "no": "override",
    "stop": "shutdown",
    "halt": "shutdown",
    "shutdown": "shutdown",
    "pause": "guidance",
    "resume": "guidance",
    "status": "guidance",
    "help": "guidance",
    "?": "guidance",
}

# ---------------------------------------------------------------------------
# Signal → (description, include_card) mapping
# ---------------------------------------------------------------------------

#: Maps runner signal type → (human description, whether to include a card)
_SIGNAL_META: dict[str, tuple[str, bool]] = {
    "RUNNER_STARTED": ("Pipeline runner started", False),
    "RUNNER_HEARTBEAT": ("Runner heartbeat", False),
    "RUNNER_COMPLETE": ("✅ Pipeline COMPLETE", True),
    "RUNNER_STUCK": ("⚠️ Runner STUCK — intervention required", True),
    "RUNNER_ERROR": ("❌ Runner ERROR", False),
    "RUNNER_UNREGISTERED": ("Runner shutting down", False),
    "NODE_SPAWNED": ("Orchestrator spawned", False),
    "NODE_IMPL_COMPLETE": ("Node implementation complete", False),
    "NODE_VALIDATED": ("✅ Node validated", False),
    "NODE_FAILED": ("❌ Node failed", False),
    "AWAITING_APPROVAL": ("⏸️ Business gate — approval required", True),
    "INBOUND_COMMAND": ("Inbound command forwarded", False),
}

# ---------------------------------------------------------------------------
# Acknowledgement messages per message_type
# ---------------------------------------------------------------------------

_ACK_MESSAGES: dict[str, str] = {
    "approval": "✅ Approval recorded. The pipeline runner will advance.",
    "override": "⛔ Override recorded. The runner will hold at this gate.",
    "shutdown": "🛑 Shutdown signal sent to the pipeline runner.",
    "guidance": "📝 Message received. The runner has been notified.",
    "rejected": "❌ Webhook verification failed. Message not forwarded.",
}


class ChannelBridge:
    """Routes messages between external communication channels and the pipeline runner.

    The bridge maintains a registry of external channel adapters (GChat, Slack, etc.)
    and an optional reference to the internal runner adapter. It provides:

    - ``handle_inbound``: Parse + verify + translate + forward inbound channel messages.
    - ``broadcast_signal``: Format + send runner signals to ALL registered channels.
    - ``send_to_channel``: Send a specific OutboundMessage to one channel.

    Thread safety: Not thread-safe. All methods are async (use within a single event loop).

    Args:
        runner_adapter: The internal runner channel adapter from ``adapters/base.py``.
            If None, inbound messages are parsed but not forwarded.
        channel_adapters: Initial registry of channel adapters.
            Format: ``{name: (adapter, default_recipient)}``.

    Example::

        gchat = GChatAdapter(
            webhook_url="https://chat.googleapis.com/v1/spaces/AAA/messages?...",
        )
        runner = StdoutAdapter()
        bridge = ChannelBridge(runner_adapter=runner)
        bridge.register_channel("gchat", gchat, default_recipient="spaces/AAA")

        # Handle inbound GChat webhook
        result = await bridge.handle_inbound("gchat", raw_webhook_payload)

        # Broadcast runner signal to all channels
        await bridge.broadcast_signal(
            "RUNNER_STUCK",
            {"node_id": "impl_backend", "pipeline_id": "PRD-AUTH-001"},
            pipeline_status=runner_plan.to_agent_json(),
        )
    """

    def __init__(
        self,
        runner_adapter: RunnerAdapter | None = None,
        channel_adapters: dict[str, tuple[ExternalAdapter, str]] | None = None,
    ) -> None:
        self._runner_adapter = runner_adapter
        # Registry: channel_name → (adapter, default_recipient)
        self._channels: dict[str, tuple[ExternalAdapter, str]] = {}
        if channel_adapters:
            self._channels.update(channel_adapters)

    # -----------------------------------------------------------------------
    # Registry management
    # -----------------------------------------------------------------------

    def register_channel(
        self,
        name: str,
        adapter: ExternalAdapter,
        default_recipient: str = "",
    ) -> None:
        """Register a channel adapter with the bridge.

        Args:
            name: Unique channel name (e.g., "gchat", "slack").
            adapter: The external channel adapter instance.
            default_recipient: Default recipient ID for outbound messages
                (e.g., Google Chat space name, Slack channel ID).
        """
        self._channels[name] = (adapter, default_recipient)

    def unregister_channel(self, name: str) -> None:
        """Remove a channel adapter from the registry.

        Args:
            name: The channel name to remove.
        """
        self._channels.pop(name, None)

    def set_runner_adapter(self, adapter: RunnerAdapter) -> None:
        """Set or replace the internal runner adapter.

        Args:
            adapter: The new runner adapter from ``adapters/base.py``.
        """
        self._runner_adapter = adapter

    @property
    def channel_names(self) -> list[str]:
        """Return the names of all registered channels."""
        return list(self._channels.keys())

    # -----------------------------------------------------------------------
    # Inbound: channel → runner
    # -----------------------------------------------------------------------

    async def handle_inbound(
        self,
        channel_name: str,
        raw_payload: dict,
    ) -> dict[str, Any]:
        """Process an inbound webhook payload and route to the pipeline runner.

        Steps:
        1. Verify webhook authenticity via adapter.verify_webhook()
        2. Parse payload via adapter.parse_inbound()
        3. Translate text command to runner message_type
        4. Forward to runner via runner_adapter.send_signal("INBOUND_COMMAND", ...)

        Args:
            channel_name: The registered channel to use for parsing.
            raw_payload: The raw webhook payload from the channel.

        Returns:
            Dict with:
                "parsed": InboundMessage as dict (None if verification failed)
                "routed": True if the message was forwarded to the runner
                "message_type": The inferred runner message type
                "acknowledgement": Short text response to echo back to the sender

        Raises:
            KeyError: If channel_name is not registered.
        """
        if channel_name not in self._channels:
            available = ", ".join(sorted(self._channels.keys()))
            raise KeyError(
                f"Unknown channel: {channel_name!r}. Registered: {available}"
            )

        adapter, _ = self._channels[channel_name]

        # Step 1: Verify webhook authenticity
        is_valid = await adapter.verify_webhook(raw_payload)
        if not is_valid:
            return {
                "parsed": None,
                "routed": False,
                "message_type": "rejected",
                "acknowledgement": _ACK_MESSAGES["rejected"],
            }

        # Step 2: Parse the inbound payload
        inbound: InboundMessage = await adapter.parse_inbound(raw_payload)

        # Step 3: Translate text → (message_type, payload)
        message_type, command_payload = self._translate_inbound(inbound)

        # Step 4: Forward to runner
        routed = False
        if self._runner_adapter is not None:
            try:
                self._runner_adapter.send_signal(
                    "INBOUND_COMMAND",
                    payload={
                        "channel": channel_name,
                        "sender_id": inbound.sender_id,
                        "text": inbound.text,
                        "message_type": message_type,
                        "command_payload": command_payload,
                        "thread_id": inbound.thread_id,
                        "space": inbound.metadata.get("space", ""),
                    },
                )
                routed = True
            except Exception:
                routed = False  # Non-fatal: runner may not be listening

        ack = _ACK_MESSAGES.get(message_type, f"Received: {inbound.text[:50]}")

        return {
            "parsed": inbound.model_dump(),
            "routed": routed,
            "message_type": message_type,
            "acknowledgement": ack,
        }

    # -----------------------------------------------------------------------
    # Outbound: runner → channel(s)
    # -----------------------------------------------------------------------

    async def broadcast_signal(
        self,
        signal_type: str,
        payload: dict[str, Any],
        pipeline_status: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Broadcast a runner signal to ALL registered channel adapters.

        Converts the runner signal to an OutboundMessage and sends it
        to each channel's default recipient concurrently.

        Args:
            signal_type: Runner signal type (e.g., "RUNNER_STUCK").
            payload: Signal-specific payload from the runner.
            pipeline_status: Optional RunnerPlan dict for card generation.
                If provided and the signal warrants a card, a rich card
                is included in the outbound message.

        Returns:
            List of result dicts, one per registered channel::

                {"channel": str, "sent": bool, "error": str | None}
        """
        outbound = self._format_signal_as_outbound(signal_type, payload, pipeline_status)

        if not self._channels:
            return []

        channel_names: list[str] = []
        tasks: list = []
        for name, (adapter, recipient) in self._channels.items():
            channel_names.append(name)
            tasks.append(adapter.send_outbound(outbound, recipient))

        responses = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict[str, Any]] = []
        for name, response in zip(channel_names, responses):
            if isinstance(response, Exception):
                results.append({
                    "channel": name,
                    "sent": False,
                    "error": str(response),
                })
            else:
                results.append({
                    "channel": name,
                    "sent": True,
                    "error": None,
                })

        return results

    async def send_to_channel(
        self,
        channel_name: str,
        message: OutboundMessage,
        recipient: str | None = None,
    ) -> dict[str, Any]:
        """Send an OutboundMessage to a specific channel.

        Args:
            channel_name: The registered channel to use.
            message: The message to send.
            recipient: Override the channel's default_recipient.
                If None, uses the registered default_recipient.

        Returns:
            The channel API response dict.

        Raises:
            KeyError: If channel_name is not registered.
        """
        if channel_name not in self._channels:
            raise KeyError(
                f"Unknown channel: {channel_name!r}. "
                f"Registered: {sorted(self._channels.keys())}"
            )
        adapter, default_recipient = self._channels[channel_name]
        target = recipient if recipient is not None else default_recipient
        return await adapter.send_outbound(message, target)

    # -----------------------------------------------------------------------
    # Internal translation helpers
    # -----------------------------------------------------------------------

    def _translate_inbound(
        self,
        inbound: InboundMessage,
    ) -> tuple[str, dict[str, Any]]:
        """Translate an InboundMessage to a (message_type, command_payload) pair.

        Matches the first word of the message text against _COMMAND_MAP.
        Falls back to "guidance" for unrecognized commands.

        For approval/override commands, extracts an optional node_id:
            "approve impl_backend"  → {"node_id": "impl_backend", ...}
            "reject impl_backend too many errors" → {"node_id": ..., "reason": ...}

        Returns:
            Tuple of (message_type, payload_dict).
        """
        text = inbound.text.strip()
        lower_text = text.lower()
        words = re.split(r"\s+", lower_text) if lower_text else [""]
        first_word = words[0]

        message_type = _COMMAND_MAP.get(first_word, "guidance")

        command_payload: dict[str, Any] = {
            "text": inbound.text,
            "sender": inbound.sender_id,
            "thread_id": inbound.thread_id,
        }

        # Extract node_id (and optional reason) from approval/override commands
        # Format: "approve <node_id>" or "reject <node_id> <reason...>"
        if message_type in ("approval", "override"):
            original_words = re.split(r"\s+", text.strip())
            if len(original_words) >= 2:
                command_payload["node_id"] = original_words[1]
            if len(original_words) >= 3 and message_type == "override":
                command_payload["reason"] = " ".join(original_words[2:])

        return message_type, command_payload

    def _format_signal_as_outbound(
        self,
        signal_type: str,
        payload: dict[str, Any],
        pipeline_status: dict | None = None,
    ) -> OutboundMessage:
        """Convert a runner signal to an OutboundMessage for channel delivery.

        Builds the text summary from the signal description and key payload fields.
        If the signal warrants a card and pipeline_status is provided, generates
        a rich card using the first registered adapter that has ``format_card``.

        Args:
            signal_type: UPPER_SNAKE_CASE runner signal name.
            payload: Signal-specific payload from the runner.
            pipeline_status: Optional pipeline status dict for card generation.

        Returns:
            OutboundMessage with text (and optionally a card dict).
        """
        description, wants_card = _SIGNAL_META.get(
            signal_type,
            (f"Runner signal: {signal_type}", False),
        )

        # Build text summary
        text_parts = [description]
        for key in ("node_id", "pipeline_id", "reason", "status", "current_node"):
            if key in payload:
                text_parts.append(f"{key}: {payload[key]}")
        text = " | ".join(text_parts)

        # Generate card if warranted and pipeline_status is available
        card: dict | None = None
        if wants_card and pipeline_status:
            for _, (adapter, _) in self._channels.items():
                if hasattr(adapter, "format_card"):
                    try:
                        card = adapter.format_card(pipeline_status)  # type: ignore[attr-defined]
                    except Exception:
                        card = None
                    break  # Use the first capable adapter

        return OutboundMessage(text=text, card=card)
