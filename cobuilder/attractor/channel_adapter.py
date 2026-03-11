"""Channel Adapter Abstraction Layer.

Defines the multi-channel communication interface for the Pipeline Runner.
Each communication channel (GChat, WhatsApp, Slack, web) implements this ABC.

This is SEPARATE from adapters/base.py (runner signaling).
- channel_adapter.py = external user communication (webhooks, cards, messages)
- adapters/base.py = internal runner-to-S3 signaling

See PRD-S3-ATTRACTOR-002 Epic 2 for full specification.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class InboundMessage(BaseModel):
    """Normalized inbound message from any channel."""

    channel: str  # "gchat", "whatsapp", "web", "slack"
    sender_id: str  # Channel-specific user identifier
    text: str  # Raw message text
    thread_id: str | None = None
    metadata: dict = {}  # Channel-specific extras (attachments, reactions)


class OutboundMessage(BaseModel):
    """Normalized outbound message to any channel."""

    text: str  # Plain text content
    card: dict | None = None  # Rich card (channel adapts to its own card format)
    thread_id: str | None = None


class ChannelAdapter(ABC):
    """Interface that all communication channel adapters must implement.

    Design principles (from OpenClaw adapter pattern):
    1. Adapters are thin - only handle auth, inbound parsing, outbound formatting
    2. Business logic lives in the runner - adapters never make pipeline decisions
    3. Cards are channel-native - each adapter formats using its platform's rich messaging
    4. Thread affinity - each pipeline maintains thread context per channel
    5. Multi-channel broadcast - runner can notify across all registered channels
    """

    @abstractmethod
    async def parse_inbound(self, raw_payload: dict) -> InboundMessage:
        """Parse channel-specific webhook payload into normalized InboundMessage."""
        ...

    @abstractmethod
    async def send_outbound(self, message: OutboundMessage, recipient: str) -> dict:
        """Send a normalized OutboundMessage via channel-specific API."""
        ...

    @abstractmethod
    async def verify_webhook(self, request: dict) -> bool:
        """Verify incoming webhook authenticity (token, signature, etc.)."""
        ...

    @abstractmethod
    def format_card(self, pipeline_status: dict) -> dict:
        """Format a pipeline status dict into the channel's native card format."""
        ...
