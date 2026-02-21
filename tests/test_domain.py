# tests/test_domain.py
"""Tests for domain models"""
import pytest
from app.core.domain import InboundMessage, MediaItem, SessionState, Step, LeadData


class TestMediaItem:
    def test_create_media_item(self):
        media = MediaItem(
            url="https://example.com/photo.jpg",
            content_type="image/jpeg",
            size_bytes=12345
        )
        assert media.url == "https://example.com/photo.jpg"
        assert media.content_type == "image/jpeg"
        assert media.size_bytes == 12345

    def test_media_item_optional_fields(self):
        media = MediaItem(url="https://example.com/photo.jpg")
        assert media.url == "https://example.com/photo.jpg"
        assert media.content_type is None
        assert media.size_bytes is None


class TestInboundMessage:
    def test_create_text_message(self):
        msg = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            text="Hello world"
        )
        assert msg.has_text()
        assert not msg.has_media()
        assert not msg.is_photo()

    def test_create_media_message(self):
        msg = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            media=[MediaItem(url="https://example.com/photo.jpg", content_type="image/jpeg")]
        )
        assert not msg.has_text()
        assert msg.has_media()
        assert msg.is_photo()

    def test_create_text_and_media_message(self):
        msg = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            text="Check this out",
            media=[MediaItem(url="https://example.com/photo.jpg", content_type="image/jpeg")]
        )
        assert msg.has_text()
        assert msg.has_media()
        assert msg.is_photo()

    def test_empty_message(self):
        msg = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123"
        )
        assert not msg.has_text()
        assert not msg.has_media()
        assert not msg.is_photo()

    def test_whitespace_only_text_not_counted(self):
        msg = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            text="   "
        )
        assert not msg.has_text()

    def test_video_not_counted_as_photo(self):
        msg = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            media=[MediaItem(url="https://example.com/video.mp4", content_type="video/mp4")]
        )
        assert msg.has_media()
        assert not msg.is_photo()


class TestSessionState:
    def test_create_session_state(self):
        state = SessionState(
            tenant_id="tenant_01",
            chat_id="+12345678900",
            lead_id="lead_123",
            step=Step.WELCOME
        )
        assert state.tenant_id == "tenant_01"
        assert state.chat_id == "+12345678900"
        assert state.lead_id == "lead_123"
        assert state.step == Step.WELCOME
        assert isinstance(state.data, LeadData)

    def test_session_state_with_data(self):
        state = SessionState(
            tenant_id="tenant_01",
            chat_id="+12345678900",
            lead_id="lead_123",
            step="cargo",  # Now using string instead of enum
            data=LeadData(cargo_description="Furniture")
        )
        assert state.data.cargo_description == "Furniture"
