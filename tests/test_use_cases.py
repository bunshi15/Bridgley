# tests/test_use_cases.py
"""Tests for use cases / application service"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from app.core.use_cases import Stage0Engine
from app.core.domain import InboundMessage, Step, SessionState, LeadData


class MockSessionStore:
    """Async mock for SessionStore"""
    def __init__(self):
        self.sessions = {}

    async def get(self, tenant_id: str, chat_id: str):
        return self.sessions.get((tenant_id, chat_id))

    async def upsert(self, state: SessionState):
        self.sessions[(state.tenant_id, state.chat_id)] = state

    async def delete(self, tenant_id: str, chat_id: str):
        self.sessions.pop((tenant_id, chat_id), None)

    async def cleanup_expired(self, ttl_seconds: int):
        return 0


class MockLeadRepository:
    """Async mock for LeadRepository"""
    def __init__(self):
        self.leads = []

    async def save_lead(self, tenant_id: str, lead_id: str, chat_id: str, payload: dict):
        self.leads.append((tenant_id, lead_id, chat_id, payload))


class MockInboundMessageRepository:
    """Async mock for InboundMessageRepository"""
    def __init__(self):
        self.seen = set()

    async def seen_or_mark(self, tenant_id: str, provider: str, message_id: str, chat_id: str) -> bool:
        key = (tenant_id, provider, message_id)
        if key in self.seen:
            return True
        self.seen.add(key)
        return False

    async def delete_for_chat(self, tenant_id: str, provider: str, chat_id: str) -> int:
        return 0


class TestStage0Engine:
    def setup_method(self):
        self.sessions = MockSessionStore()
        self.leads = MockLeadRepository()
        self.inbound = MockInboundMessageRepository()
        self.engine = Stage0Engine(
            tenant_id="tenant_01",
            provider="twilio",
            sessions=self.sessions,
            leads=self.leads,
            inbound=self.inbound,
        )

    @pytest.mark.asyncio
    async def test_process_inbound_message_with_text(self):
        message = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            text="Hello"
        )

        result = await self.engine.process_inbound_message(message)

        assert "reply" in result
        assert "step" in result
        assert "lead_id" in result
        assert result["step"] != Step.DONE.value  # First message shouldn't complete

    @pytest.mark.asyncio
    async def test_process_inbound_message_with_media(self):
        from app.core.domain import MediaItem

        message = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            media=[MediaItem(url="https://example.com/photo.jpg", content_type="image/jpeg")]
        )

        result = await self.engine.process_inbound_message(message)

        assert "reply" in result
        assert "step" in result

    @pytest.mark.asyncio
    async def test_process_inbound_message_empty_returns_error(self):
        message = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123"
        )

        result = await self.engine.process_inbound_message(message)

        assert "reply" in result
        assert "didn't receive any message content" in result["reply"].lower()

    @pytest.mark.asyncio
    async def test_process_inbound_message_wrong_tenant_raises_error(self):
        message = InboundMessage(
            tenant_id="wrong_tenant",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            text="Hello"
        )

        with pytest.raises(ValueError, match="tenant_id"):
            await self.engine.process_inbound_message(message)

    @pytest.mark.asyncio
    async def test_idempotency_duplicate_message(self):
        message = InboundMessage(
            tenant_id="tenant_01",
            provider="twilio",
            chat_id="+12345678900",
            message_id="SM123",
            text="Hello"
        )

        # Process first time
        result1 = await self.engine.process_inbound_message(message)
        assert "(duplicate ignored)" not in result1["reply"]

        # Process same message again
        result2 = await self.engine.process_inbound_message(message)
        assert "(duplicate ignored)" in result2["reply"]

    @pytest.mark.asyncio
    async def test_process_text_creates_session(self):
        chat_id = "+12345678900"

        result = await self.engine.process_text(
            chat_id=chat_id,
            text="Hello",
            message_id="msg_123"
        )

        # Session should be created
        session = await self.sessions.get("tenant_01", chat_id)
        assert session is not None
        assert session.chat_id == chat_id

    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        result = await self.engine.cleanup_expired(3600)

        assert result["ok"] is True
        assert "deleted_sessions" in result
        assert "ttl_seconds" in result

    @pytest.mark.asyncio
    async def test_reset_chat(self):
        chat_id = "+12345678900"

        # Create a session first
        await self.engine.process_text(
            chat_id=chat_id,
            text="Hello",
            message_id="msg_123"
        )

        # Reset
        result = await self.engine.reset_chat(chat_id)

        assert result["ok"] is True
        # Session should be deleted
        assert await self.sessions.get("tenant_01", chat_id) is None


# ============================================================================
# Phase 7: Session TTL & Stale Hint Tests
# ============================================================================


class TestSessionStaleness:
    """Test _is_stale_session and _is_expired_session logic."""

    def test_stale_session_when_inactive(self):
        """Session inactive longer than stale_hint_seconds → is_stale = True."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        # Default stale_hint is 3600s (1 hour); 2 hours > 1 hour
        assert Stage0Engine._is_stale_session(st) is True

    def test_not_stale_when_recent(self):
        """Session active recently → is_stale = False."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=datetime.now(timezone.utc) - timedelta(seconds=10),
        )
        assert Stage0Engine._is_stale_session(st) is False

    def test_not_stale_when_no_updated_at(self):
        """New session without updated_at → is_stale = False."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
        )
        assert st.updated_at is None
        assert Stage0Engine._is_stale_session(st) is False

    def test_expired_session_when_past_ttl(self):
        """Session inactive longer than ttl_seconds → is_expired = True."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=7),
        )
        # Default ttl is 21600s (6 hours); 7 hours > 6 hours
        assert Stage0Engine._is_expired_session(st) is True

    def test_not_expired_when_within_ttl(self):
        """Session within TTL → is_expired = False."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert Stage0Engine._is_expired_session(st) is False

    def test_not_expired_when_no_updated_at(self):
        """New session without updated_at → is_expired = False."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
        )
        assert Stage0Engine._is_expired_session(st) is False

    def test_stale_with_custom_settings(self):
        """Stale check respects overridden settings."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=datetime.now(timezone.utc) - timedelta(seconds=15),
        )
        with patch("app.config.settings") as mock_settings:
            mock_settings.session_stale_hint_seconds = 10
            assert Stage0Engine._is_stale_session(st) is True

    def test_expired_with_custom_settings(self):
        """TTL check respects overridden settings."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=datetime.now(timezone.utc) - timedelta(seconds=35),
        )
        with patch("app.config.settings") as mock_settings:
            mock_settings.session_ttl_seconds = 30
            assert Stage0Engine._is_expired_session(st) is True

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetime (no tzinfo) is treated as UTC."""
        naive_time = datetime.utcnow() - timedelta(hours=2)
        assert naive_time.tzinfo is None
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=naive_time,
        )
        assert Stage0Engine._is_stale_session(st) is True

    def test_elapsed_seconds(self):
        """_elapsed_seconds returns correct value."""
        updated = datetime.now(timezone.utc) - timedelta(seconds=100)
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
            updated_at=updated,
        )
        elapsed = Stage0Engine._elapsed_seconds(st)
        assert elapsed is not None
        assert 99 < elapsed < 105  # allow small timing variance

    def test_elapsed_seconds_none_for_new(self):
        """_elapsed_seconds returns None for sessions without updated_at."""
        st = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="l1",
        )
        assert Stage0Engine._elapsed_seconds(st) is None


class TestTTLEnforcementInProcessText:
    """Test that expired sessions are discarded and recreated."""

    def setup_method(self):
        self.sessions = MockSessionStore()
        self.leads = MockLeadRepository()
        self.inbound = MockInboundMessageRepository()
        self.engine = Stage0Engine(
            tenant_id="tenant_01",
            provider="twilio",
            sessions=self.sessions,
            leads=self.leads,
            inbound=self.inbound,
        )

    @pytest.mark.asyncio
    async def test_expired_session_discarded(self):
        """An expired session is deleted and user starts fresh."""
        chat_id = "+12345678900"

        # Create a session at the "extras" step (mid-flow)
        old_session = SessionState(
            tenant_id="tenant_01",
            chat_id=chat_id,
            lead_id="old-lead-id",
            step="extras",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=7),
        )
        self.sessions.sessions[("tenant_01", chat_id)] = old_session

        # Process a new message — should start fresh, not resume extras
        result = await self.engine.process_text(
            chat_id=chat_id,
            text="Hello",
            message_id="msg_1"
        )

        # Should have gone through welcome → cargo (fresh start)
        assert result["step"] == "cargo"
        assert result["lead_id"] != "old-lead-id"

    @pytest.mark.asyncio
    async def test_non_expired_session_preserved(self):
        """A session within TTL is preserved and resumed."""
        chat_id = "+12345678900"

        # Create a recent session at "extras" step
        old_session = SessionState(
            tenant_id="tenant_01",
            chat_id=chat_id,
            lead_id="recent-lead",
            step="extras",
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        self.sessions.sessions[("tenant_01", chat_id)] = old_session

        # Process a message — should resume at extras
        result = await self.engine.process_text(
            chat_id=chat_id,
            text="4",  # "skip extras" choice
            message_id="msg_2"
        )

        # Should continue from extras step, not start fresh
        assert result["step"] == "estimate"
        assert result["lead_id"] == "recent-lead"

    @pytest.mark.asyncio
    async def test_stale_hint_shown(self):
        """A stale (but not expired) session shows the hint."""
        chat_id = "+12345678900"

        # Create a session that's stale (>1h) but not expired (<6h)
        old_session = SessionState(
            tenant_id="tenant_01",
            chat_id=chat_id,
            lead_id="stale-lead",
            step="extras",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        self.sessions.sessions[("tenant_01", chat_id)] = old_session

        result = await self.engine.process_text(
            chat_id=chat_id,
            text="4",
            message_id="msg_3"
        )

        # Should contain the stale hint in the reply
        from app.core.bots.moving_bot_texts import get_text
        assert get_text("hint_stale_resume", "ru") in result["reply"]
        # Session should be resumed, not fresh
        assert result["lead_id"] == "stale-lead"

    @pytest.mark.asyncio
    async def test_stale_hint_not_shown_on_welcome(self):
        """Stale hint is NOT shown when session is at welcome step."""
        chat_id = "+12345678900"

        # Create a stale session at welcome step
        old_session = SessionState(
            tenant_id="tenant_01",
            chat_id=chat_id,
            lead_id="welcome-lead",
            step="welcome",
            updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        self.sessions.sessions[("tenant_01", chat_id)] = old_session

        result = await self.engine.process_text(
            chat_id=chat_id,
            text="Hello",
            message_id="msg_4"
        )

        from app.core.bots.moving_bot_texts import get_text
        assert get_text("hint_stale_resume", "ru") not in result["reply"]
