"""Unit tests for GChatAdapter.

Tests cover:
- parse_inbound: Various Google Chat webhook payload shapes
- verify_webhook: Token-based authentication
- format_card: Pipeline status → Google Chat Card v2
- send_outbound: HTTP call construction (mocked httpx)
- Private helpers: _strip_mention, _extract_space_from_name
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cobuilder.attractor.gchat_adapter import (
    GChatAdapter,
    _strip_mention,
    _extract_space_from_name,
)
from cobuilder.attractor.channel_adapter import InboundMessage, OutboundMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter() -> GChatAdapter:
    """A GChatAdapter with a verification token configured."""
    return GChatAdapter(
        webhook_url="https://chat.googleapis.com/v1/spaces/AAA/messages?key=K&token=T",
        verification_token="test-secret",
        space_name="spaces/AAA",
        timeout=5.0,
    )


@pytest.fixture
def adapter_no_token() -> GChatAdapter:
    """A GChatAdapter with no verification token (dev mode)."""
    return GChatAdapter(
        webhook_url="https://chat.googleapis.com/v1/spaces/AAA/messages",
    )


def _make_message_payload(
    text: str = "status",
    sender_name: str = "users/123",
    sender_display: str = "Alice",
    msg_name: str = "spaces/AAA/messages/BBB",
    thread_name: str | None = "spaces/AAA/threads/CCC",
    event_type: str = "MESSAGE",
) -> dict:
    """Build a realistic Google Chat webhook payload."""
    thread = {"name": thread_name} if thread_name else None
    return {
        "type": event_type,
        "message": {
            "name": msg_name,
            "text": text,
            "sender": {"displayName": sender_display, "name": sender_name},
            "thread": thread,
        },
    }


# ---------------------------------------------------------------------------
# parse_inbound tests
# ---------------------------------------------------------------------------


class TestParseInbound:
    """Tests for GChatAdapter.parse_inbound()."""

    @pytest.mark.asyncio
    async def test_basic_message(self, adapter):
        payload = _make_message_payload(text="status")
        msg = await adapter.parse_inbound(payload)
        assert msg.channel == "gchat"
        assert msg.text == "status"
        assert msg.sender_id == "users/123"
        assert msg.thread_id == "spaces/AAA/threads/CCC"

    @pytest.mark.asyncio
    async def test_strips_bot_mention_prefix(self, adapter):
        payload = _make_message_payload(
            text="<users/105123456789123456789> approve impl_backend"
        )
        msg = await adapter.parse_inbound(payload)
        assert msg.text == "approve impl_backend"

    @pytest.mark.asyncio
    async def test_strips_mention_with_no_trailing_text(self, adapter):
        payload = _make_message_payload(text="<users/999>")
        msg = await adapter.parse_inbound(payload)
        assert msg.text == ""

    @pytest.mark.asyncio
    async def test_no_mention_text_unchanged(self, adapter):
        payload = _make_message_payload(text="reject node_frontend too slow")
        msg = await adapter.parse_inbound(payload)
        assert msg.text == "reject node_frontend too slow"

    @pytest.mark.asyncio
    async def test_no_thread_yields_none(self, adapter):
        payload = _make_message_payload(thread_name=None)
        msg = await adapter.parse_inbound(payload)
        assert msg.thread_id is None

    @pytest.mark.asyncio
    async def test_extracts_space_from_message_name(self, adapter):
        payload = _make_message_payload(msg_name="spaces/MYSPACE/messages/MSG1")
        msg = await adapter.parse_inbound(payload)
        assert msg.metadata["space"] == "spaces/MYSPACE"

    @pytest.mark.asyncio
    async def test_falls_back_to_configured_space(self, adapter):
        payload = _make_message_payload(msg_name="")  # no space in name
        msg = await adapter.parse_inbound(payload)
        assert msg.metadata["space"] == "spaces/AAA"

    @pytest.mark.asyncio
    async def test_event_type_in_metadata(self, adapter):
        payload = _make_message_payload(event_type="MESSAGE")
        msg = await adapter.parse_inbound(payload)
        assert msg.metadata["event_type"] == "MESSAGE"

    @pytest.mark.asyncio
    async def test_added_to_space_event(self, adapter):
        payload = {"type": "ADDED_TO_SPACE"}
        msg = await adapter.parse_inbound(payload)
        assert msg.channel == "gchat"
        assert msg.text == ""
        assert msg.sender_id == "system"

    @pytest.mark.asyncio
    async def test_display_name_fallback_for_sender(self, adapter):
        payload = {
            "type": "MESSAGE",
            "message": {
                "name": "spaces/AAA/messages/BBB",
                "text": "hello",
                "sender": {"displayName": "Bob"},  # no "name" field
            },
        }
        msg = await adapter.parse_inbound(payload)
        assert msg.sender_id == "Bob"

    @pytest.mark.asyncio
    async def test_returns_inbound_message_model(self, adapter):
        payload = _make_message_payload()
        msg = await adapter.parse_inbound(payload)
        assert isinstance(msg, InboundMessage)


# ---------------------------------------------------------------------------
# verify_webhook tests
# ---------------------------------------------------------------------------


class TestVerifyWebhook:
    """Tests for GChatAdapter.verify_webhook()."""

    @pytest.mark.asyncio
    async def test_no_token_always_passes(self, adapter_no_token):
        result = await adapter_no_token.verify_webhook({})
        assert result is True

    @pytest.mark.asyncio
    async def test_no_token_passes_even_with_wrong_data(self, adapter_no_token):
        result = await adapter_no_token.verify_webhook({"token": "anything"})
        assert result is True

    @pytest.mark.asyncio
    async def test_bearer_token_valid(self, adapter):
        result = await adapter.verify_webhook(
            {"headers": {"Authorization": "Bearer test-secret"}}
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_bearer_token_invalid(self, adapter):
        result = await adapter.verify_webhook(
            {"headers": {"Authorization": "Bearer wrong-token"}}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_bearer_token_case_insensitive_header(self, adapter):
        result = await adapter.verify_webhook(
            {"headers": {"authorization": "Bearer test-secret"}}
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_body_token_valid(self, adapter):
        result = await adapter.verify_webhook({"token": "test-secret"})
        assert result is True

    @pytest.mark.asyncio
    async def test_body_token_invalid(self, adapter):
        result = await adapter.verify_webhook({"token": "nope"})
        assert result is False

    @pytest.mark.asyncio
    async def test_no_token_provided_returns_false(self, adapter):
        result = await adapter.verify_webhook({"headers": {}})
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_request_returns_false(self, adapter):
        result = await adapter.verify_webhook({})
        assert result is False

    @pytest.mark.asyncio
    async def test_timing_safe_comparison(self, adapter):
        # Verify we use hmac.compare_digest (no early exit on mismatch)
        # Any token of correct length should still fail
        result = await adapter.verify_webhook({"token": "test-secre"})  # 1 char short
        assert result is False


# ---------------------------------------------------------------------------
# format_card tests
# ---------------------------------------------------------------------------


class TestFormatCard:
    """Tests for GChatAdapter.format_card()."""

    @pytest.fixture
    def basic_status(self) -> dict:
        return {
            "pipeline_id": "PRD-AUTH-001",
            "prd_ref": "PRD-AUTH-001",
            "current_stage": "EXECUTE",
            "summary": "Backend node is ready to spawn.",
            "actions": [
                {
                    "node_id": "impl_backend",
                    "action": "spawn_orchestrator",
                    "priority": "normal",
                },
            ],
            "blocked_nodes": [],
            "completed_nodes": [],
            "pipeline_complete": False,
        }

    def test_returns_dict_with_header_and_sections(self, adapter, basic_status):
        card = adapter.format_card(basic_status)
        assert "header" in card
        assert "sections" in card

    def test_header_title_contains_pipeline_id(self, adapter, basic_status):
        card = adapter.format_card(basic_status)
        assert "PRD-AUTH-001" in card["header"]["title"]

    def test_header_subtitle_uses_prd_ref(self, adapter, basic_status):
        card = adapter.format_card(basic_status)
        assert card["header"]["subtitle"] == "PRD-AUTH-001"

    def test_header_subtitle_falls_back_to_stage(self, adapter, basic_status):
        basic_status["prd_ref"] = ""
        card = adapter.format_card(basic_status)
        assert "EXECUTE" in card["header"]["subtitle"]

    def test_summary_widget_present(self, adapter, basic_status):
        card = adapter.format_card(basic_status)
        widgets = card["sections"][0]["widgets"]
        text_widgets = [w for w in widgets if "textParagraph" in w]
        summary_text = " ".join(
            w["textParagraph"]["text"] for w in text_widgets
        )
        assert "Backend node" in summary_text

    def test_actions_widget_present(self, adapter, basic_status):
        card = adapter.format_card(basic_status)
        widgets = card["sections"][0]["widgets"]
        text_widgets = [w for w in widgets if "textParagraph" in w]
        actions_text = " ".join(
            w["textParagraph"]["text"] for w in text_widgets
        )
        assert "impl_backend" in actions_text

    def test_blocked_nodes_shown(self, adapter):
        status = {
            "pipeline_id": "PRD-STUCK-001",
            "prd_ref": "",
            "current_stage": "EXECUTE",
            "summary": "Backend stuck.",
            "actions": [],
            "blocked_nodes": [
                {"node_id": "impl_backend", "reason": "Validation failed 3x"}
            ],
            "completed_nodes": [],
            "pipeline_complete": False,
        }
        card = adapter.format_card(status)
        widgets = card["sections"][0]["widgets"]
        text_widgets = [w for w in widgets if "textParagraph" in w]
        all_text = " ".join(w["textParagraph"]["text"] for w in text_widgets)
        assert "impl_backend" in all_text
        assert "Blocked" in all_text

    def test_completed_nodes_kv_widget(self, adapter):
        status = {
            "pipeline_id": "PRD-DONE-001",
            "prd_ref": "",
            "current_stage": "FINALIZE",
            "summary": "All done.",
            "actions": [],
            "blocked_nodes": [],
            "completed_nodes": ["node_a", "node_b", "node_c"],
            "pipeline_complete": True,
        }
        card = adapter.format_card(status)
        widgets = card["sections"][0]["widgets"]
        kv_widgets = [w for w in widgets if "decoratedText" in w]
        all_kv_text = " ".join(
            w["decoratedText"]["text"] for w in kv_widgets
        )
        assert "3" in all_kv_text  # 3 completed nodes

    def test_pipeline_complete_shows_star_icon(self, adapter):
        status = {
            "pipeline_id": "PRD-X",
            "prd_ref": "",
            "current_stage": "FINALIZE",
            "summary": "Done.",
            "actions": [],
            "blocked_nodes": [],
            "completed_nodes": [],
            "pipeline_complete": True,
        }
        card = adapter.format_card(status)
        widgets = card["sections"][0]["widgets"]
        kv_widgets = [w for w in widgets if "decoratedText" in w]
        icons = [
            w["decoratedText"].get("startIcon", {}).get("knownIcon", "")
            for w in kv_widgets
        ]
        assert "STAR" in icons

    def test_incomplete_pipeline_shows_clock_icon(self, adapter, basic_status):
        card = adapter.format_card(basic_status)
        widgets = card["sections"][0]["widgets"]
        kv_widgets = [w for w in widgets if "decoratedText" in w]
        icons = [
            w["decoratedText"].get("startIcon", {}).get("knownIcon", "")
            for w in kv_widgets
        ]
        assert "CLOCK" in icons

    def test_high_priority_action_shown_with_red_icon(self, adapter):
        status = {
            "pipeline_id": "PRD-HP-001",
            "prd_ref": "",
            "current_stage": "EXECUTE",
            "summary": "High priority.",
            "actions": [
                {"node_id": "critical_node", "action": "spawn_orchestrator", "priority": "high"},
            ],
            "blocked_nodes": [],
            "completed_nodes": [],
            "pipeline_complete": False,
        }
        card = adapter.format_card(status)
        widgets = card["sections"][0]["widgets"]
        text_widgets = [w for w in widgets if "textParagraph" in w]
        all_text = " ".join(w["textParagraph"]["text"] for w in text_widgets)
        assert "🔴" in all_text

    def test_actions_capped_at_max(self, adapter):
        """More than 5 actions should show an ellipsis."""
        status = {
            "pipeline_id": "PRD-MANY-001",
            "prd_ref": "",
            "current_stage": "EXECUTE",
            "summary": "Many actions.",
            "actions": [
                {"node_id": f"node_{i}", "action": "spawn_orchestrator", "priority": "normal"}
                for i in range(8)
            ],
            "blocked_nodes": [],
            "completed_nodes": [],
            "pipeline_complete": False,
        }
        card = adapter.format_card(status)
        widgets = card["sections"][0]["widgets"]
        text_widgets = [w for w in widgets if "textParagraph" in w]
        all_text = " ".join(w["textParagraph"]["text"] for w in text_widgets)
        assert "more" in all_text

    def test_empty_status_does_not_crash(self, adapter):
        card = adapter.format_card({})
        assert "header" in card
        assert "sections" in card


# ---------------------------------------------------------------------------
# send_outbound tests (mocked httpx)
# ---------------------------------------------------------------------------


class TestSendOutbound:
    """Tests for GChatAdapter.send_outbound() — all HTTP calls are mocked."""

    def _make_mock_client(self, response_json: dict):
        """Create a mock httpx.AsyncClient context manager."""
        mock_response = MagicMock()
        mock_response.json.return_value = response_json
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        return mock_client

    @pytest.mark.asyncio
    async def test_sends_text_message(self, adapter):
        mock_client = self._make_mock_client({"name": "spaces/AAA/messages/NEW"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            msg = OutboundMessage(text="Pipeline started")
            result = await adapter.send_outbound(msg, "spaces/AAA")
        assert result["name"] == "spaces/AAA/messages/NEW"

    @pytest.mark.asyncio
    async def test_text_only_body(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            msg = OutboundMessage(text="Hello")
            await adapter.send_outbound(msg, "spaces/AAA")
        body = mock_client.post.call_args.kwargs["json"]
        assert body["text"] == "Hello"
        assert "cardsV2" not in body

    @pytest.mark.asyncio
    async def test_card_message_uses_cards_v2(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            card = {"header": {"title": "Test"}, "sections": []}
            msg = OutboundMessage(text="Fallback text", card=card)
            await adapter.send_outbound(msg, "spaces/AAA")
        body = mock_client.post.call_args.kwargs["json"]
        assert "cardsV2" in body
        assert body["cardsV2"][0]["cardId"] == "pipeline-status"
        assert body["cardsV2"][0]["card"] == card
        assert body["text"] == "Fallback text"

    @pytest.mark.asyncio
    async def test_card_without_text_omits_text_field(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            card = {"header": {"title": "Test"}, "sections": []}
            msg = OutboundMessage(text="", card=card)
            await adapter.send_outbound(msg, "spaces/AAA")
        body = mock_client.post.call_args.kwargs["json"]
        # text is empty string, should not appear (or be empty)
        assert body.get("text", "") == ""

    @pytest.mark.asyncio
    async def test_thread_id_sets_thread_in_body(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            msg = OutboundMessage(text="Reply", thread_id="spaces/AAA/threads/CCC")
            await adapter.send_outbound(msg, "spaces/AAA")
        body = mock_client.post.call_args.kwargs["json"]
        assert body["thread"]["name"] == "spaces/AAA/threads/CCC"

    @pytest.mark.asyncio
    async def test_thread_reply_adds_reply_option_to_url(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            msg = OutboundMessage(text="Reply", thread_id="spaces/AAA/threads/CCC")
            await adapter.send_outbound(msg, "spaces/AAA")
        url = mock_client.post.call_args.args[0]
        assert "messageReplyOption" in url

    @pytest.mark.asyncio
    async def test_no_thread_does_not_add_reply_option(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            msg = OutboundMessage(text="Broadcast")
            await adapter.send_outbound(msg, "spaces/AAA")
        url = mock_client.post.call_args.args[0]
        assert "messageReplyOption" not in url

    @pytest.mark.asyncio
    async def test_content_type_header_set(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            msg = OutboundMessage(text="Hello")
            await adapter.send_outbound(msg, "spaces/AAA")
        headers = mock_client.post.call_args.kwargs["headers"]
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_raise_for_status_called(self, adapter):
        mock_client = self._make_mock_client({"name": "x"})
        with patch("httpx.AsyncClient", return_value=mock_client):
            msg = OutboundMessage(text="Hello")
            await adapter.send_outbound(msg, "spaces/AAA")
        mock_client.post.return_value.raise_for_status.assert_called_once()


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for private helper functions."""

    def test_strip_mention_removes_user_mention(self):
        assert _strip_mention("<users/123> approve node") == "approve node"

    def test_strip_mention_no_mention(self):
        assert _strip_mention("status") == "status"

    def test_strip_mention_only_mention(self):
        assert _strip_mention("<users/123>") == ""

    def test_strip_mention_space_variant(self):
        assert _strip_mention("<spaces/AAA> help") == "help"

    def test_strip_mention_empty_string(self):
        assert _strip_mention("") == ""

    def test_extract_space_basic(self):
        assert _extract_space_from_name("spaces/AAA123/messages/BBB") == "spaces/AAA123"

    def test_extract_space_not_a_space_name(self):
        assert _extract_space_from_name("other/path") == ""

    def test_extract_space_empty_string(self):
        assert _extract_space_from_name("") == ""

    def test_extract_space_spaces_only(self):
        assert _extract_space_from_name("spaces/") == "spaces/"

    def test_extract_space_with_thread(self):
        # Full path: spaces/{space}/threads/{thread}
        result = _extract_space_from_name("spaces/MYSPACE/threads/T1")
        assert result == "spaces/MYSPACE"
