# app/core/engine/use_cases.py
import time
from datetime import datetime, timezone

from app.core.engine.domain import InboundMessage, SessionState
from app.core.engine.universal_engine import UniversalEngine
# NOTE: Handler registration is NOT done here.
# The application bootstrap (http_app.py) is responsible for importing
# app.core.handlers to trigger BotHandlerRegistry.register() calls.
# This keeps the engine decoupled from specific bot implementations.
from app.core.engine.ports import (
    AsyncSessionStore,
    AsyncLeadRepository,
    AsyncInboundMessageRepository,
    AsyncLeadFinalizer,
)
from app.infra.metrics import AppMetrics


class Stage0Engine:
    """
    Application service / use-case layer.
    Workflow: idempotency -> session -> processing -> persistence -> finalization.

    Now supports multiple bot types through the universal engine system.
    Each tenant can use a different bot type.

    Note: Now accepts both sync and async repository implementations.
    Async implementations are recommended for production use.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        provider: str,
        sessions: AsyncSessionStore,
        leads: AsyncLeadRepository,
        inbound: AsyncInboundMessageRepository,
        finalizer: AsyncLeadFinalizer | None = None,
        bot_type: str = "moving_bot_v1",
    ) -> None:
        self.tenant_id = tenant_id
        self.provider = provider
        self.sessions = sessions
        self.leads = leads
        self.inbound = inbound
        self.finalizer = finalizer
        self.bot_type = bot_type

    def _mk_message_id(self, prefix: str) -> str:
        return f"{prefix}-{time.time_ns()}"

    @staticmethod
    def _elapsed_seconds(session: SessionState) -> float | None:
        """Return seconds since last session update, or None if unknown."""
        if not session.updated_at:
            return None
        now = datetime.now(timezone.utc)
        updated = session.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated).total_seconds()

    @staticmethod
    def _is_stale_session(session: SessionState) -> bool:
        """Check if session has been inactive longer than the stale hint threshold."""
        from app.config import settings

        elapsed = Stage0Engine._elapsed_seconds(session)
        if elapsed is None:
            return False
        return elapsed > settings.session_stale_hint_seconds

    @staticmethod
    def _is_expired_session(session: SessionState) -> bool:
        """Check if session has exceeded the TTL and should be discarded."""
        from app.config import settings

        elapsed = Stage0Engine._elapsed_seconds(session)
        if elapsed is None:
            return False
        return elapsed > settings.session_ttl_seconds

    @staticmethod
    def _prepend_stale_hint(reply: str | None, session: SessionState, original_step: str | None = None) -> str | None:
        """Prepend stale session hint to reply if session is stale and not just started.

        Args:
            original_step: The step BEFORE the handler mutated the session.
                           Needed because handlers mutate state in place.
        """
        from app.core.bots.moving_bot_texts import get_text

        step_to_check = original_step or session.step
        if not reply or step_to_check == "welcome":
            return reply
        if not Stage0Engine._is_stale_session(session):
            return reply
        hint = get_text("hint_stale_resume", session.language)
        return f"{hint}\n\n{reply}"

    async def process_text(
        self,
        *,
        chat_id: str,
        text: str,
        message_id: str | None = None,
        sender_name: str | None = None,
    ) -> dict:
        msg_id = message_id or self._mk_message_id("dev")

        # idempotency
        if await self.inbound.seen_or_mark(self.tenant_id, self.provider, msg_id, chat_id):
            st = await self.sessions.get(self.tenant_id, chat_id) or UniversalEngine.new_session(
                self.tenant_id, chat_id, self.bot_type
            )
            AppMetrics.idempotency_hit(self.tenant_id, self.provider)
            return {"reply": "(duplicate ignored)", "step": st.step, "lead_id": st.lead_id}

        existing = await self.sessions.get(self.tenant_id, chat_id)

        # TTL enforcement: discard expired sessions (Phase 7)
        if existing and self._is_expired_session(existing):
            await self.sessions.delete(self.tenant_id, chat_id)
            existing = None  # start fresh

        st = existing or UniversalEngine.new_session(
            self.tenant_id, chat_id, self.bot_type
        )
        is_stale = self._is_stale_session(st)
        original_step = st.step  # save before handler mutates state in place

        # Store sender contact info once (for providers like Telegram where
        # chat_id is not a phone number and operators need a way to reach the user)
        if sender_name and not st.data.custom.get("sender_name"):
            st.data.custom["sender_name"] = sender_name

        # Track processing time
        with AppMetrics.track_processing_time(self.tenant_id, st.step):
            st2, reply, is_done = UniversalEngine.handle_text(st, text)
            await self.sessions.upsert(st2)

            if is_done and st2.step == "done":
                payload = UniversalEngine.get_payload(st2)
                if self.finalizer is not None:
                    await self.finalizer.finalize(self.tenant_id, st2.lead_id, st2.chat_id, payload)
                else:
                    await self.leads.save_lead(self.tenant_id, st2.lead_id, st2.chat_id, payload)
                    await self.sessions.delete(self.tenant_id, chat_id)

        # Track request
        AppMetrics.request_received(self.tenant_id, st2.step)

        # Prepend stale session hint if user was inactive for a long time
        if is_stale:
            reply = self._prepend_stale_hint(reply, st, original_step)

        return {"reply": reply, "step": st2.step, "lead_id": st2.lead_id}

    async def process_media(
        self,
        *,
        chat_id: str,
        message_id: str | None = None,
        sender_name: str | None = None,
    ) -> dict:
        msg_id = message_id or self._mk_message_id("dev")

        if await self.inbound.seen_or_mark(self.tenant_id, self.provider, msg_id, chat_id):
            st = await self.sessions.get(self.tenant_id, chat_id) or UniversalEngine.new_session(
                self.tenant_id, chat_id, self.bot_type
            )
            AppMetrics.idempotency_hit(self.tenant_id, self.provider)
            return {"reply": "(duplicate ignored)", "step": st.step, "lead_id": st.lead_id}

        existing = await self.sessions.get(self.tenant_id, chat_id)

        # TTL enforcement: discard expired sessions (Phase 7)
        if existing and self._is_expired_session(existing):
            await self.sessions.delete(self.tenant_id, chat_id)
            existing = None

        st = existing or UniversalEngine.new_session(
            self.tenant_id, chat_id, self.bot_type
        )
        is_stale = self._is_stale_session(st)
        original_step = st.step  # save before handler mutates state in place

        # Store sender contact info once (same as process_text)
        if sender_name and not st.data.custom.get("sender_name"):
            st.data.custom["sender_name"] = sender_name

        # Track processing time
        with AppMetrics.track_processing_time(self.tenant_id, st.step):
            st2, maybe_reply = UniversalEngine.handle_media(st)
            await self.sessions.upsert(st2)

        # Track request
        AppMetrics.request_received(self.tenant_id, st2.step)

        # Prepend stale session hint if user was inactive for a long time
        if is_stale and maybe_reply:
            maybe_reply = self._prepend_stale_hint(maybe_reply, st, original_step)

        return {"reply": maybe_reply, "step": st2.step, "lead_id": st2.lead_id}

    async def cleanup_expired(self, ttl_seconds: int) -> dict:
        deleted = await self.sessions.cleanup_expired(ttl_seconds)
        return {"ok": True, "deleted_sessions": deleted, "ttl_seconds": ttl_seconds}

    async def reset_chat(self, chat_id: str) -> dict:
        """Hard reset: deletes session AND inbound messages"""
        await self.sessions.delete(self.tenant_id, chat_id)
        deleted = await self.inbound.delete_for_chat(self.tenant_id, self.provider, chat_id)
        return {"ok": True, "deleted_inbound": deleted}

    async def soft_reset_chat(self, chat_id: str) -> dict:
        """
        Soft reset: deletes session only, keeps lead data and inbound messages.
        Allows user to restart conversation without losing collected data.
        """
        await self.sessions.delete(self.tenant_id, chat_id)
        return {"ok": True, "chat_id": chat_id, "message": "Session reset, lead data preserved"}

    async def process_location(
        self,
        *,
        chat_id: str,
        latitude: float,
        longitude: float,
        name: str | None = None,
        address: str | None = None,
        message_id: str | None = None,
        sender_name: str | None = None,
    ) -> dict:
        """Process a GPS location message (Phase 5)."""
        msg_id = message_id or self._mk_message_id("dev")

        if await self.inbound.seen_or_mark(self.tenant_id, self.provider, msg_id, chat_id):
            st = await self.sessions.get(self.tenant_id, chat_id) or UniversalEngine.new_session(
                self.tenant_id, chat_id, self.bot_type
            )
            AppMetrics.idempotency_hit(self.tenant_id, self.provider)
            return {"reply": "(duplicate ignored)", "step": st.step, "lead_id": st.lead_id}

        existing = await self.sessions.get(self.tenant_id, chat_id)

        # TTL enforcement: discard expired sessions (Phase 7)
        if existing and self._is_expired_session(existing):
            await self.sessions.delete(self.tenant_id, chat_id)
            existing = None

        st = existing or UniversalEngine.new_session(
            self.tenant_id, chat_id, self.bot_type
        )
        is_stale = self._is_stale_session(st)
        original_step = st.step  # save before handler mutates state in place

        if sender_name and not st.data.custom.get("sender_name"):
            st.data.custom["sender_name"] = sender_name

        with AppMetrics.track_processing_time(self.tenant_id, st.step):
            # Enrich with reverse geocoding when no name/address from adapter
            effective_name = name
            effective_address = address
            if not name and not address:
                try:
                    from app.infra.geocoding import reverse_geocode
                    geocoded = await reverse_geocode(latitude, longitude)
                    if geocoded:
                        effective_address = geocoded
                except Exception:
                    pass  # Geocoding failure never blocks the flow

            st2, reply, is_done = UniversalEngine.handle_location(
                st, latitude, longitude, effective_name, effective_address
            )
            await self.sessions.upsert(st2)

            if is_done and st2.step == "done":
                payload = UniversalEngine.get_payload(st2)
                if self.finalizer is not None:
                    await self.finalizer.finalize(self.tenant_id, st2.lead_id, st2.chat_id, payload)
                else:
                    await self.leads.save_lead(self.tenant_id, st2.lead_id, st2.chat_id, payload)
                    await self.sessions.delete(self.tenant_id, chat_id)

        AppMetrics.request_received(self.tenant_id, st2.step)

        if is_stale:
            reply = self._prepend_stale_hint(reply, st, original_step)

        return {"reply": reply, "step": st2.step, "lead_id": st2.lead_id}

    async def process_inbound_message(self, message: InboundMessage) -> dict:
        """
        Process a normalized InboundMessage (domain model) from any provider.
        This is the recommended entry point for webhook handlers.

        Routes to process_text(), process_media(), or process_location()
        based on message content.
        """
        # Validate message matches engine configuration
        if message.tenant_id != self.tenant_id:
            raise ValueError(
                f"Message tenant_id '{message.tenant_id}' does not match engine tenant_id '{self.tenant_id}'"
            )

        # Determine message type and route appropriately
        # Priority: text > location > media (location messages may also carry text)
        if message.has_text():
            return await self.process_text(
                chat_id=message.chat_id,
                text=message.text or "",
                message_id=message.message_id,
                sender_name=message.sender_name,
            )
        elif message.has_location():
            loc = message.location
            return await self.process_location(
                chat_id=message.chat_id,
                latitude=loc.latitude,
                longitude=loc.longitude,
                name=loc.name,
                address=loc.address,
                message_id=message.message_id,
                sender_name=message.sender_name,
            )
        elif message.has_media():
            return await self.process_media(
                chat_id=message.chat_id,
                message_id=message.message_id,
                sender_name=message.sender_name,
            )
        else:
            st = await self.sessions.get(self.tenant_id, message.chat_id) or UniversalEngine.new_session(
                self.tenant_id, message.chat_id, self.bot_type
            )
            return {
                "reply": "Sorry, I didn't receive any message content.",
                "step": st.step,
                "lead_id": st.lead_id,
            }
