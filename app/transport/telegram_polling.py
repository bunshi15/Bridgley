# app/transport/telegram_polling.py
"""
Telegram Bot API long-polling handler.

Alternative to webhook mode. Calls getUpdates in a loop with long-polling.
Simpler ops (no public URL or SSL required).

Usage:
    poller = TelegramPoller(engine=engine)
    await poller.start()
    # ... on shutdown:
    await poller.stop()
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.core.use_cases import Stage0Engine
from app.transport.adapters import TelegramAdapter
from app.transport.telegram_sender import (
    get_updates,
    send_text_message,
    delete_webhook,
    TelegramSendError,
)
from app.infra.logging_config import get_logger, LogContext
from app.infra.metrics import AppMetrics, inc_counter
from app.infra.media_service import get_media_service
from app.infra.rate_limiter import InMemoryRateLimiter

logger = get_logger(__name__)


def _safe_create_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create a background task with exception logging to avoid 'Task exception was never retrieved'."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(_log_task_exception)
    return task


def _log_task_exception(task: asyncio.Task) -> None:
    """Callback: log unhandled exceptions from fire-and-forget tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            f"Background task {task.get_name()!r} failed: {exc}",
            exc_info=(type(exc), exc, exc.__traceback__),
        )


class TelegramPoller:
    """
    Long-polling loop for receiving Telegram updates.

    Calls getUpdates with a 30-second timeout (long-poll), processes each
    update through the domain engine, and sends replies.

    Supports per-tenant mode (v0.8.1): when ``tenant_ctx`` is provided,
    the poller uses the tenant's bot token instead of the global
    ``settings.telegram_channel_token``.

    Error handling:
    - On API errors: exponential backoff (1s → 2s → 4s → ... → 30s max)
    - On processing errors: log and continue (don't lose the offset)
    - On cancellation: graceful shutdown
    """

    def __init__(
        self,
        engine: Stage0Engine,
        poll_timeout: int = 30,
        *,
        tenant_ctx: "TenantContext | None" = None,
    ):
        self.engine = engine
        self.poll_timeout = poll_timeout
        self._adapter = TelegramAdapter()
        self._task: asyncio.Task | None = None
        self._offset: int | None = None
        self._running = False
        self._backoff = 1  # seconds, doubles on error, max 30

        # Per-tenant support (v0.8.1)
        self._tenant_ctx = tenant_ctx
        if tenant_ctx and "telegram" in tenant_ctx.channels:
            self._bot_token: str | None = tenant_ctx.channels["telegram"].credentials.get("bot_token")
            self._tenant_id = tenant_ctx.tenant_id
        else:
            self._bot_token = None
            self._tenant_id = settings.tenant_id

        # Per-chat rate limiter
        self._chat_rate_limiter = InMemoryRateLimiter(
            max_requests=settings.chat_rate_limit_per_minute,
            window_seconds=60,
        )

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        if self._running:
            logger.warning("Telegram poller already running")
            return

        # Remove any existing webhook so polling can work
        try:
            await delete_webhook(token=self._bot_token)
            logger.info(
                f"Telegram webhook removed (switching to polling mode, "
                f"tenant={self._tenant_id})"
            )
        except TelegramSendError as e:
            logger.warning(f"Could not delete Telegram webhook: {e}")

        self._running = True
        self._task = asyncio.create_task(
            self._poll_loop(),
            name=f"tg_poller_{self._tenant_id}",
        )
        logger.info(
            f"Telegram poller started (timeout={self.poll_timeout}s, "
            f"tenant={self._tenant_id})"
        )

    async def stop(self) -> None:
        """Stop the polling loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Telegram poller stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                updates = await get_updates(
                    offset=self._offset,
                    timeout=self.poll_timeout,
                    token=self._bot_token,
                )

                # Reset backoff on successful poll
                self._backoff = 1

                if not updates:
                    continue

                for update in updates:
                    # Advance offset to acknowledge this update
                    update_id = update.get("update_id", 0)
                    self._offset = update_id + 1

                    # Process update (errors here don't stop the loop)
                    await self._process_update(update)

            except TelegramSendError as e:
                if not self._running:
                    break
                logger.error(f"Telegram polling error: {e}, backing off {self._backoff}s")
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 30)

            except asyncio.CancelledError:
                break

            except Exception as e:
                if not self._running:
                    break
                logger.error(f"Telegram polling unexpected error: {e}", exc_info=True)
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 30)

    async def _process_update(self, update: dict) -> None:
        """Process a single Telegram Update through the domain engine."""
        messages = self._adapter.adapt_update(update, self._tenant_id)
        if not messages:
            return

        for message in messages:
            log_ctx = LogContext(
                logger,
                tenant_id=message.tenant_id,
                chat_id=message.chat_id,
            )

            # Per-chat rate limiting
            allowed, retry_after = self._chat_rate_limiter.is_allowed(message.chat_id)
            if not allowed:
                log_ctx.warning(f"Rate limit exceeded for chat, retry_after={retry_after}s")
                inc_counter("webhook_rate_limited", tenant_id=message.tenant_id, provider="telegram")
                continue

            try:
                log_ctx.info(
                    f"Telegram poll received: chat_id={message.chat_id[:4]}***, "
                    f"has_text={message.has_text()}, has_media={message.has_media()}"
                )

                # Process through domain engine
                with AppMetrics.track_processing_time(message.tenant_id, "telegram_poll"):
                    result = await self.engine.process_inbound_message(message)

                AppMetrics.request_received(message.tenant_id, result["step"])
                inc_counter("inbound_messages_total", provider="telegram")

                log_ctx.info(
                    f"Telegram poll processed: step={result['step']}, "
                    f"lead_id={result['lead_id']}"
                )

                # Send reply
                if result.get("reply") and result["reply"] not in (None, "(duplicate ignored)"):
                    try:
                        await send_text_message(
                            message.chat_id, result["reply"],
                            token=self._bot_token,
                        )
                        inc_counter("outbound_messages_total", provider="telegram", status="sent")
                    except TelegramSendError as err:
                        log_ctx.error(f"Telegram outbound send failed: {err}")
                        inc_counter("outbound_messages_total", provider="telegram", status="failed")

                # Process media in background
                if message.has_media():
                    _safe_create_task(
                        self._process_media(message, log_ctx),
                        name=f"tg_poll_media_{message.message_id}",
                    )

            except Exception as exc:
                log_ctx.error(
                    f"Telegram poll processing failed: {exc.__class__.__name__}",
                    exc_info=True,
                )

    @staticmethod
    async def _process_media(message, log_ctx) -> None:
        """Download and process media from Telegram."""
        media_service = get_media_service()
        for media_item in message.media:
            try:
                if not media_item.provider_media_id:
                    continue

                processed = await media_service.process_and_save(
                    media_item,
                    message.tenant_id,
                    message.chat_id,
                    provider=message.provider,
                    message_id=message.message_id,
                )
                if processed:
                    log_ctx.info(
                        f"Telegram media processed: uuid={processed['uuid']}, "
                        f"size={processed['size_bytes']}"
                    )
            except Exception as media_error:
                log_ctx.warning(f"Telegram media processing failed (continuing): {media_error}")
