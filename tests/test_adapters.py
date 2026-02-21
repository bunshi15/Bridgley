# tests/test_adapters.py
"""Tests for transport adapters"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.transport.adapters import TwilioAdapter, DevAdapter, WhatsAppAdapter
from app.core.domain import InboundMessage


class TestTwilioAdapter:
    @pytest.mark.asyncio
    async def test_adapt_text_only_message(self):
        # Mock request with Twilio format
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "+12345678900",
            "Body": "Hello world",
            "MessageSid": "SM1234567890abcdef",
            "NumMedia": "0"
        })

        adapter = TwilioAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert isinstance(message, InboundMessage)
        assert message.tenant_id == "tenant_01"
        assert message.provider == "twilio"
        assert message.chat_id == "+12345678900"
        assert message.text == "Hello world"
        assert message.message_id == "SM1234567890abcdef"
        assert len(message.media) == 0
        assert message.has_text()
        assert not message.has_media()

    @pytest.mark.asyncio
    async def test_adapt_message_with_media(self):
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "+12345678900",
            "Body": "Check this out",
            "MessageSid": "SM1234567890abcdef",
            "NumMedia": "2",
            "MediaUrl0": "https://api.twilio.com/photo1.jpg",
            "MediaContentType0": "image/jpeg",
            "MediaUrl1": "https://api.twilio.com/photo2.jpg",
            "MediaContentType1": "image/png"
        })

        adapter = TwilioAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert message.has_text()
        assert message.has_media()
        assert len(message.media) == 2
        assert message.media[0].url == "https://api.twilio.com/photo1.jpg"
        assert message.media[0].content_type == "image/jpeg"
        assert message.media[1].url == "https://api.twilio.com/photo2.jpg"
        assert message.media[1].content_type == "image/png"

    @pytest.mark.asyncio
    async def test_adapt_empty_body_becomes_none(self):
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "+12345678900",
            "Body": "",
            "MessageSid": "SM123",
            "NumMedia": "0"
        })

        adapter = TwilioAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert message.text is None
        assert not message.has_text()


class TestDevAdapter:
    def test_adapt_simple_text_message(self):
        adapter = DevAdapter()
        message = adapter.adapt(
            tenant_id="tenant_01",
            chat_id="+12345678900",
            text="Test message",
            message_id="dev_123"
        )

        assert message.provider == "dev"
        assert message.chat_id == "+12345678900"
        assert message.text == "Test message"
        assert message.message_id == "dev_123"
        assert len(message.media) == 0

    def test_adapt_generates_message_id_if_missing(self):
        adapter = DevAdapter()
        message = adapter.adapt(
            tenant_id="tenant_01",
            chat_id="+12345678900",
            text="Test"
        )

        assert message.message_id is not None
        assert message.message_id.startswith("dev_")

    def test_adapt_with_media_url(self):
        adapter = DevAdapter()
        message = adapter.adapt(
            tenant_id="tenant_01",
            chat_id="+12345678900",
            media_url="https://example.com/photo.jpg"
        )

        assert message.has_media()
        assert len(message.media) == 1
        assert message.media[0].url == "https://example.com/photo.jpg"
        assert message.media[0].content_type == "image/jpeg"


class TestWhatsAppAdapter:
    @pytest.mark.asyncio
    async def test_adapt_removes_whatsapp_prefix(self):
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "whatsapp:+12345678900",
            "Body": "Hello",
            "MessageSid": "SM123",
            "NumMedia": "0"
        })

        adapter = WhatsAppAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert message.provider == "whatsapp"
        assert message.chat_id == "+12345678900"  # Prefix removed
        assert not message.chat_id.startswith("whatsapp:")

    @pytest.mark.asyncio
    async def test_adapt_no_prefix_leaves_unchanged(self):
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "+12345678900",
            "Body": "Hello",
            "MessageSid": "SM123",
            "NumMedia": "0"
        })

        adapter = WhatsAppAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert message.chat_id == "+12345678900"


# ============================================================================
# Phase 5: Location extraction tests
# ============================================================================

class TestTwilioLocationExtraction:
    """Twilio adapter extracts GPS location from Latitude/Longitude fields."""

    @pytest.mark.asyncio
    async def test_location_extracted(self):
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "+12345678900",
            "Body": "",
            "MessageSid": "SM123",
            "NumMedia": "0",
            "Latitude": "32.794",
            "Longitude": "34.989",
        })

        adapter = TwilioAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert message.has_location()
        assert message.location.latitude == pytest.approx(32.794)
        assert message.location.longitude == pytest.approx(34.989)

    @pytest.mark.asyncio
    async def test_no_location_fields(self):
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "+12345678900",
            "Body": "Hello",
            "MessageSid": "SM123",
            "NumMedia": "0",
        })

        adapter = TwilioAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert not message.has_location()
        assert message.location is None


class TestWhatsAppLocationExtraction:
    """WhatsApp adapter (Twilio-based) extracts GPS location."""

    @pytest.mark.asyncio
    async def test_location_extracted(self):
        request = MagicMock()
        request.form = AsyncMock(return_value={
            "From": "whatsapp:+12345678900",
            "Body": "",
            "MessageSid": "SM123",
            "NumMedia": "0",
            "Latitude": "32.080",
            "Longitude": "34.780",
        })

        adapter = WhatsAppAdapter()
        message = await adapter.adapt(request, "tenant_01")

        assert message.has_location()
        assert message.location.latitude == pytest.approx(32.080)
        assert message.location.longitude == pytest.approx(34.780)


class TestTelegramLocationExtraction:
    """Telegram adapter extracts GPS location from message.location."""

    def test_location_message(self):
        from app.transport.adapters import TelegramAdapter

        adapter = TelegramAdapter()
        update = {
            "update_id": 123,
            "message": {
                "message_id": 42,
                "from": {"id": 123, "first_name": "User"},
                "chat": {"id": 123, "type": "private"},
                "date": 1234567890,
                "location": {
                    "latitude": 32.794,
                    "longitude": 34.989,
                },
            },
        }

        messages = adapter.adapt_update(update, "tenant_01")
        assert len(messages) == 1
        msg = messages[0]
        assert msg.has_location()
        assert msg.location.latitude == pytest.approx(32.794)
        assert msg.location.longitude == pytest.approx(34.989)

    def test_text_message_no_location(self):
        from app.transport.adapters import TelegramAdapter

        adapter = TelegramAdapter()
        update = {
            "update_id": 124,
            "message": {
                "message_id": 43,
                "from": {"id": 123, "first_name": "User"},
                "chat": {"id": 123, "type": "private"},
                "date": 1234567890,
                "text": "Hello",
            },
        }

        messages = adapter.adapt_update(update, "tenant_01")
        assert len(messages) == 1
        assert not messages[0].has_location()


class TestMetaLocationExtraction:
    """Meta Cloud adapter extracts GPS location from type=location messages."""

    def test_location_message(self):
        from app.transport.adapters import MetaCloudAdapter

        adapter = MetaCloudAdapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "messages": [{
                            "from": "1234567890",
                            "id": "wamid.xxx",
                            "timestamp": "1234567890",
                            "type": "location",
                            "location": {
                                "latitude": 32.794,
                                "longitude": 34.989,
                                "name": "Haifa Port",
                                "address": "Herzl St 10",
                            },
                        }],
                    },
                    "field": "messages",
                }],
            }],
        }

        messages = adapter.adapt_payload(payload, "tenant_01")
        assert len(messages) == 1
        msg = messages[0]
        assert msg.has_location()
        assert msg.location.latitude == pytest.approx(32.794)
        assert msg.location.longitude == pytest.approx(34.989)
        assert msg.location.name == "Haifa Port"
        assert msg.location.address == "Herzl St 10"

    def test_sticker_still_ignored(self):
        from app.transport.adapters import MetaCloudAdapter

        adapter = MetaCloudAdapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "messages": [{
                            "from": "1234567890",
                            "id": "wamid.yyy",
                            "timestamp": "1234567890",
                            "type": "sticker",
                        }],
                    },
                    "field": "messages",
                }],
            }],
        }

        messages = adapter.adapt_payload(payload, "tenant_01")
        assert len(messages) == 0
