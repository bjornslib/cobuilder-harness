"""Unit tests for ChannelBridge.

Tests cover:
- register_channel / channel_names
- handle_inbound: verify → parse → translate → forward
- handle_inbound: verification failure
- handle_inbound: unknown channel
- handle_inbound: runner adapter not set
- broadcast_signal: single channel
- broadcast_signal: multiple channels concurrently
- broadcast_signal: channel error handling
- broadcast_signal: with pipeline_status card generation
- send_to_channel: specific channel delivery
- _translate_inbound: command mapping
- _format_signal_as_outbound: text and card generation
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cobuilder.engine.channel_bridge import ChannelBridge
from cobuilder.engine.channel_adapter import InboundMessage, OutboundMessage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_inbound(
    text: str = "status",
    sender: str = "users/123",
    thread_id: str | None = "spaces/AAA/threads/T1",
    channel: str = "gchat",
) -> InboundMessage:
    """Build a test InboundMessage."""
    return InboundMessage(
        channel=channel,
        sender_id=sender,
        text=text,
        thread_id=thread_id,
        metadata={"space": "spaces/AAA"},
    )


def _make_mock_gchat_adapter(
    inbound_text: str = "status",
    verify_result: bool = True,
) -> MagicMock:
    """Build a mock channel adapter (GChatAdapter-compatible)."""
    adapter = MagicMock()
    adapter.parse_inbound = AsyncMock(return_value=_make_inbound(text=inbound_text))
    adapter.send_outbound = AsyncMock(return_value={"name": "spaces/AAA/messages/NEW"})
    adapter.verify_webhook = AsyncMock(return_value=verify_result)
    adapter.format_card = MagicMock(
        return_value={"header": {"title": "Pipeline: PRD-AUTH-001"}, "sections": []}
    )
    return adapter


def _make_mock_runner_adapter() -> MagicMock:
    """Build a mock internal runner adapter (adapters.base.ChannelAdapter-compatible)."""
    adapter = MagicMock()
    adapter.send_signal = MagicMock()
    adapter.receive_message = MagicMock(return_value=None)
    return adapter


@pytest.fixture
def mock_gchat() -> MagicMock:
    return _make_mock_gchat_adapter()


@pytest.fixture
def mock_runner() -> MagicMock:
    return _make_mock_runner_adapter()


@pytest.fixture
def bridge(mock_gchat, mock_runner) -> ChannelBridge:
    """A ChannelBridge with one GChat channel and a runner adapter."""
    b = ChannelBridge(runner_adapter=mock_runner)
    b.register_channel("gchat", mock_gchat, default_recipient="spaces/AAA")
    return b


def _make_pipeline_status(complete: bool = False) -> dict:
    return {
        "pipeline_id": "PRD-AUTH-001",
        "prd_ref": "PRD-AUTH-001",
        "current_stage": "FINALIZE" if complete else "EXECUTE",
        "summary": "All done." if complete else "Backend is running.",
        "actions": [],
        "blocked_nodes": [],
        "completed_nodes": ["impl_backend"] if complete else [],
        "pipeline_complete": complete,
    }


# ---------------------------------------------------------------------------
# Registry management tests
# ---------------------------------------------------------------------------


class TestRegistry:
    """Tests for channel registration."""

    def test_register_channel(self):
        b = ChannelBridge()
        adapter = _make_mock_gchat_adapter()
        b.register_channel("gchat", adapter, "spaces/AAA")
        assert "gchat" in b.channel_names

    def test_channel_names_empty_initially(self):
        b = ChannelBridge()
        assert b.channel_names == []

    def test_register_multiple_channels(self):
        b = ChannelBridge()
        b.register_channel("gchat", _make_mock_gchat_adapter(), "spaces/AAA")
        b.register_channel("slack", _make_mock_gchat_adapter(), "#general")
        assert set(b.channel_names) == {"gchat", "slack"}

    def test_unregister_channel(self):
        b = ChannelBridge()
        b.register_channel("gchat", _make_mock_gchat_adapter(), "spaces/AAA")
        b.unregister_channel("gchat")
        assert "gchat" not in b.channel_names

    def test_unregister_nonexistent_is_noop(self):
        b = ChannelBridge()
        b.unregister_channel("nonexistent")  # Should not raise

    def test_set_runner_adapter(self):
        b = ChannelBridge()
        runner = _make_mock_runner_adapter()
        b.set_runner_adapter(runner)
        assert b._runner_adapter is runner

    def test_init_with_channel_adapters(self):
        adapter = _make_mock_gchat_adapter()
        b = ChannelBridge(channel_adapters={"gchat": (adapter, "spaces/AAA")})
        assert "gchat" in b.channel_names


# ---------------------------------------------------------------------------
# handle_inbound tests
# ---------------------------------------------------------------------------


class TestHandleInbound:
    """Tests for ChannelBridge.handle_inbound()."""

    @pytest.mark.asyncio
    async def test_routes_status_command_as_guidance(self, bridge, mock_runner):
        result = await bridge.handle_inbound("gchat", {})
        assert result["message_type"] == "guidance"
        assert result["routed"] is True
        mock_runner.send_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_routes_approve_command(self, mock_runner):
        adapter = _make_mock_gchat_adapter(inbound_text="approve impl_backend")
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("gchat", adapter, "spaces/AAA")
        result = await b.handle_inbound("gchat", {})
        assert result["message_type"] == "approval"

    @pytest.mark.asyncio
    async def test_routes_reject_command(self, mock_runner):
        adapter = _make_mock_gchat_adapter(inbound_text="reject impl_backend not ready")
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("gchat", adapter, "spaces/AAA")
        result = await b.handle_inbound("gchat", {})
        assert result["message_type"] == "override"

    @pytest.mark.asyncio
    async def test_routes_stop_command_as_shutdown(self, mock_runner):
        adapter = _make_mock_gchat_adapter(inbound_text="stop")
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("gchat", adapter, "spaces/AAA")
        result = await b.handle_inbound("gchat", {})
        assert result["message_type"] == "shutdown"

    @pytest.mark.asyncio
    async def test_unknown_command_defaults_to_guidance(self, mock_runner):
        adapter = _make_mock_gchat_adapter(inbound_text="whatever")
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("gchat", adapter, "spaces/AAA")
        result = await b.handle_inbound("gchat", {})
        assert result["message_type"] == "guidance"

    @pytest.mark.asyncio
    async def test_verification_failure_returns_rejected(self, mock_runner):
        adapter = _make_mock_gchat_adapter(verify_result=False)
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("gchat", adapter, "spaces/AAA")
        result = await b.handle_inbound("gchat", {})
        assert result["message_type"] == "rejected"
        assert result["routed"] is False
        assert result["parsed"] is None
        mock_runner.send_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_channel_raises_key_error(self, bridge):
        with pytest.raises(KeyError, match="unknown"):
            await bridge.handle_inbound("unknown", {})

    @pytest.mark.asyncio
    async def test_no_runner_adapter_still_parses(self):
        adapter = _make_mock_gchat_adapter()
        b = ChannelBridge()  # No runner adapter
        b.register_channel("gchat", adapter, "spaces/AAA")
        result = await b.handle_inbound("gchat", {})
        assert result["parsed"] is not None
        assert result["routed"] is False

    @pytest.mark.asyncio
    async def test_runner_adapter_send_signal_called_with_correct_type(
        self, bridge, mock_runner
    ):
        await bridge.handle_inbound("gchat", {})
        args, kwargs = mock_runner.send_signal.call_args
        assert args[0] == "INBOUND_COMMAND"

    @pytest.mark.asyncio
    async def test_runner_signal_payload_contains_channel(self, bridge, mock_runner):
        await bridge.handle_inbound("gchat", {})
        _, kwargs = mock_runner.send_signal.call_args
        payload = kwargs.get("payload", {})
        assert payload.get("channel") == "gchat"

    @pytest.mark.asyncio
    async def test_runner_signal_payload_contains_sender(self, bridge, mock_runner):
        await bridge.handle_inbound("gchat", {})
        _, kwargs = mock_runner.send_signal.call_args
        payload = kwargs.get("payload", {})
        assert payload.get("sender_id") == "users/123"

    @pytest.mark.asyncio
    async def test_result_contains_acknowledgement(self, bridge):
        result = await bridge.handle_inbound("gchat", {})
        assert "acknowledgement" in result
        assert len(result["acknowledgement"]) > 0

    @pytest.mark.asyncio
    async def test_runner_error_still_returns_routed_false(self, mock_gchat):
        runner = _make_mock_runner_adapter()
        runner.send_signal.side_effect = Exception("Bus down")
        b = ChannelBridge(runner_adapter=runner)
        b.register_channel("gchat", mock_gchat, "spaces/AAA")
        result = await b.handle_inbound("gchat", {})
        assert result["routed"] is False


# ---------------------------------------------------------------------------
# broadcast_signal tests
# ---------------------------------------------------------------------------


class TestBroadcastSignal:
    """Tests for ChannelBridge.broadcast_signal()."""

    @pytest.mark.asyncio
    async def test_single_channel_success(self, bridge, mock_gchat):
        results = await bridge.broadcast_signal("RUNNER_STARTED", {"pipeline_id": "PRD-AUTH-001"})
        assert len(results) == 1
        assert results[0]["sent"] is True
        assert results[0]["error"] is None
        mock_gchat.send_outbound.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_channels_returns_empty_list(self, mock_runner):
        b = ChannelBridge(runner_adapter=mock_runner)
        results = await b.broadcast_signal("RUNNER_STARTED", {})
        assert results == []

    @pytest.mark.asyncio
    async def test_multiple_channels_all_receive(self, mock_runner):
        a1 = _make_mock_gchat_adapter()
        a2 = _make_mock_gchat_adapter()
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("gchat1", a1, "spaces/AAA")
        b.register_channel("gchat2", a2, "spaces/BBB")
        results = await b.broadcast_signal("RUNNER_COMPLETE", {})
        assert len(results) == 2
        assert all(r["sent"] for r in results)
        a1.send_outbound.assert_called_once()
        a2.send_outbound.assert_called_once()

    @pytest.mark.asyncio
    async def test_channel_error_recorded_not_raised(self, mock_runner):
        bad_adapter = _make_mock_gchat_adapter()
        bad_adapter.send_outbound = AsyncMock(side_effect=Exception("Connection refused"))
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("gchat", bad_adapter, "spaces/AAA")
        results = await b.broadcast_signal("RUNNER_STARTED", {})
        assert results[0]["sent"] is False
        assert "Connection refused" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_partial_channel_failure(self, mock_runner):
        good = _make_mock_gchat_adapter()
        bad = _make_mock_gchat_adapter()
        bad.send_outbound = AsyncMock(side_effect=Exception("Timeout"))
        b = ChannelBridge(runner_adapter=mock_runner)
        b.register_channel("good", good, "spaces/AAA")
        b.register_channel("bad", bad, "spaces/BBB")
        results = await b.broadcast_signal("RUNNER_STUCK", {})
        sent = {r["channel"]: r["sent"] for r in results}
        assert sent["good"] is True
        assert sent["bad"] is False

    @pytest.mark.asyncio
    async def test_broadcast_with_pipeline_status_generates_card(self, bridge, mock_gchat):
        status = _make_pipeline_status(complete=True)
        await bridge.broadcast_signal("RUNNER_COMPLETE", {}, pipeline_status=status)
        call_args = mock_gchat.send_outbound.call_args
        msg: OutboundMessage = call_args.args[0]
        assert msg.card is not None

    @pytest.mark.asyncio
    async def test_broadcast_without_pipeline_status_no_card_for_stuck(
        self, bridge, mock_gchat
    ):
        # RUNNER_STUCK wants a card, but if no pipeline_status → no card
        await bridge.broadcast_signal("RUNNER_STUCK", {"node_id": "impl_backend"})
        call_args = mock_gchat.send_outbound.call_args
        msg: OutboundMessage = call_args.args[0]
        assert msg.card is None

    @pytest.mark.asyncio
    async def test_broadcast_non_card_signal(self, bridge, mock_gchat):
        # RUNNER_HEARTBEAT does not warrant a card
        await bridge.broadcast_signal(
            "RUNNER_HEARTBEAT", {"status": "running"}, pipeline_status=_make_pipeline_status()
        )
        call_args = mock_gchat.send_outbound.call_args
        msg: OutboundMessage = call_args.args[0]
        assert msg.card is None

    @pytest.mark.asyncio
    async def test_outbound_text_contains_signal_description(self, bridge, mock_gchat):
        await bridge.broadcast_signal("RUNNER_STUCK", {"node_id": "impl_backend"})
        call_args = mock_gchat.send_outbound.call_args
        msg: OutboundMessage = call_args.args[0]
        assert "STUCK" in msg.text

    @pytest.mark.asyncio
    async def test_outbound_text_includes_payload_fields(self, bridge, mock_gchat):
        await bridge.broadcast_signal(
            "NODE_VALIDATED",
            {"node_id": "impl_backend", "pipeline_id": "PRD-AUTH-001"},
        )
        call_args = mock_gchat.send_outbound.call_args
        msg: OutboundMessage = call_args.args[0]
        assert "impl_backend" in msg.text

    @pytest.mark.asyncio
    async def test_outbound_uses_default_recipient(self, bridge, mock_gchat):
        await bridge.broadcast_signal("RUNNER_STARTED", {})
        call_args = mock_gchat.send_outbound.call_args
        recipient = call_args.args[1]
        assert recipient == "spaces/AAA"


# ---------------------------------------------------------------------------
# send_to_channel tests
# ---------------------------------------------------------------------------


class TestSendToChannel:
    """Tests for ChannelBridge.send_to_channel()."""

    @pytest.mark.asyncio
    async def test_sends_to_registered_channel(self, bridge, mock_gchat):
        msg = OutboundMessage(text="Direct message")
        result = await bridge.send_to_channel("gchat", msg)
        assert result["name"] == "spaces/AAA/messages/NEW"
        mock_gchat.send_outbound.assert_called_once_with(msg, "spaces/AAA")

    @pytest.mark.asyncio
    async def test_uses_override_recipient(self, bridge, mock_gchat):
        msg = OutboundMessage(text="Override recipient")
        await bridge.send_to_channel("gchat", msg, recipient="spaces/OTHER")
        call_args = mock_gchat.send_outbound.call_args
        assert call_args.args[1] == "spaces/OTHER"

    @pytest.mark.asyncio
    async def test_unknown_channel_raises_key_error(self, bridge):
        msg = OutboundMessage(text="test")
        with pytest.raises(KeyError, match="not_a_channel"):
            await bridge.send_to_channel("not_a_channel", msg)


# ---------------------------------------------------------------------------
# _translate_inbound tests
# ---------------------------------------------------------------------------


class TestTranslateInbound:
    """Tests for ChannelBridge._translate_inbound() command mapping."""

    @pytest.fixture
    def bridge_instance(self) -> ChannelBridge:
        return ChannelBridge()

    def _inbound(self, text: str) -> InboundMessage:
        return _make_inbound(text=text)

    def test_approve(self, bridge_instance):
        msg_type, payload = bridge_instance._translate_inbound(self._inbound("approve"))
        assert msg_type == "approval"

    def test_approve_with_node_id(self, bridge_instance):
        msg_type, payload = bridge_instance._translate_inbound(
            self._inbound("approve impl_backend")
        )
        assert msg_type == "approval"
        assert payload["node_id"] == "impl_backend"

    def test_reject_with_node_and_reason(self, bridge_instance):
        msg_type, payload = bridge_instance._translate_inbound(
            self._inbound("reject impl_backend tests failing")
        )
        assert msg_type == "override"
        assert payload["node_id"] == "impl_backend"
        assert "tests failing" in payload["reason"]

    def test_stop(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(self._inbound("stop"))
        assert msg_type == "shutdown"

    def test_halt(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(self._inbound("halt"))
        assert msg_type == "shutdown"

    def test_yes(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(self._inbound("yes"))
        assert msg_type == "approval"

    def test_no(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(self._inbound("no"))
        assert msg_type == "override"

    def test_status(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(self._inbound("status"))
        assert msg_type == "guidance"

    def test_help(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(self._inbound("help"))
        assert msg_type == "guidance"

    def test_unknown_command_defaults_to_guidance(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(
            self._inbound("do something random")
        )
        assert msg_type == "guidance"

    def test_case_insensitive_matching(self, bridge_instance):
        msg_type, _ = bridge_instance._translate_inbound(self._inbound("APPROVE impl"))
        assert msg_type == "approval"

    def test_payload_contains_sender(self, bridge_instance):
        inbound = _make_inbound(text="status", sender="users/999")
        _, payload = bridge_instance._translate_inbound(inbound)
        assert payload["sender"] == "users/999"

    def test_payload_contains_thread_id(self, bridge_instance):
        inbound = _make_inbound(text="status", thread_id="spaces/A/threads/T")
        _, payload = bridge_instance._translate_inbound(inbound)
        assert payload["thread_id"] == "spaces/A/threads/T"


# ---------------------------------------------------------------------------
# _format_signal_as_outbound tests
# ---------------------------------------------------------------------------


class TestFormatSignalAsOutbound:
    """Tests for ChannelBridge._format_signal_as_outbound()."""

    @pytest.fixture
    def bridge_instance(self) -> ChannelBridge:
        return ChannelBridge()

    def test_runner_started_returns_text_no_card(self, bridge_instance):
        msg = bridge_instance._format_signal_as_outbound("RUNNER_STARTED", {"pipeline_id": "P"})
        assert "started" in msg.text.lower()
        assert msg.card is None

    def test_runner_stuck_returns_text_no_card_without_status(self, bridge_instance):
        msg = bridge_instance._format_signal_as_outbound("RUNNER_STUCK", {"node_id": "n1"})
        assert "STUCK" in msg.text
        assert msg.card is None

    def test_runner_stuck_with_status_generates_card(self, bridge_instance):
        adapter = _make_mock_gchat_adapter()
        bridge_instance.register_channel("gchat", adapter, "spaces/AAA")
        status = _make_pipeline_status()
        msg = bridge_instance._format_signal_as_outbound(
            "RUNNER_STUCK", {"node_id": "n1"}, pipeline_status=status
        )
        assert msg.card is not None
        adapter.format_card.assert_called_once_with(status)

    def test_runner_complete_with_status_generates_card(self, bridge_instance):
        adapter = _make_mock_gchat_adapter()
        bridge_instance.register_channel("gchat", adapter, "spaces/AAA")
        status = _make_pipeline_status(complete=True)
        msg = bridge_instance._format_signal_as_outbound(
            "RUNNER_COMPLETE", {}, pipeline_status=status
        )
        assert msg.card is not None

    def test_unknown_signal_type_produces_text(self, bridge_instance):
        msg = bridge_instance._format_signal_as_outbound(
            "MY_CUSTOM_SIGNAL_XYZ", {"key": "value"}
        )
        assert "MY_CUSTOM_SIGNAL_XYZ" in msg.text

    def test_node_id_in_payload_appears_in_text(self, bridge_instance):
        msg = bridge_instance._format_signal_as_outbound(
            "NODE_FAILED", {"node_id": "impl_frontend"}
        )
        assert "impl_frontend" in msg.text

    def test_runner_heartbeat_no_card(self, bridge_instance):
        msg = bridge_instance._format_signal_as_outbound(
            "RUNNER_HEARTBEAT",
            {"status": "running"},
            pipeline_status=_make_pipeline_status(),
        )
        assert msg.card is None

    def test_format_card_error_falls_back_to_no_card(self, bridge_instance):
        adapter = _make_mock_gchat_adapter()
        adapter.format_card.side_effect = Exception("Format error")
        bridge_instance.register_channel("gchat", adapter, "spaces/AAA")
        msg = bridge_instance._format_signal_as_outbound(
            "RUNNER_STUCK", {}, pipeline_status=_make_pipeline_status()
        )
        assert msg.card is None
