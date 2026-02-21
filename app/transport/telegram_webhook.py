# app/transport/telegram_webhook.py
"""
Telegram Bot API webhook handler.

Handles:
- POST /webhooks/telegram — inbound Updates from Telegram

Security features:
- X-Telegram-Bot-Api-Secret-Token header validation (if configured)
- Per-chat rate limiting (anti-spam)
- Fast 200 response to avoid Telegram timeout
"""
from __future__ import annotations

import hmac
import time
from typing import TYPE_CHECKING

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from app.config import settings

if TYPE_CHECKING:
    from app.infra.tenant_registry import TenantContext
from app.core.use_cases import Stage0Engine
from app.transport.adapters import TelegramAdapter
from app.infra.logging_config import get_logger, LogContext
from app.infra.metrics import AppMetrics, inc_counter
from app.infra.pg_job_repo_async import get_job_repo
from app.infra.rate_limiter import InMemoryRateLimiter

logger = get_logger(__name__)


# Per-chat rate limiter (lazy init)
_chat_rate_limiter: InMemoryRateLimiter | None = None


def _get_chat_rate_limiter() -> InMemoryRateLimiter:
    global _chat_rate_limiter
    if _chat_rate_limiter is None:
        _chat_rate_limiter = InMemoryRateLimiter(
            max_requests=settings.chat_rate_limit_per_minute,
            window_seconds=60,
        )
    return _chat_rate_limiter


# -------------------------------------------------------------------------
# Secret Token Verification
# -------------------------------------------------------------------------

def _verify_secret_token(request: Request) -> bool:
    """
    Verify X-Telegram-Bot-Api-Secret-Token header.
    Returns True if valid or if secret token verification is disabled.
    """
    if not settings.telegram_webhook_secret:
        return True

    header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not header_token:
        logger.warning("Telegram webhook: missing X-Telegram-Bot-Api-Secret-Token header")
        return False

    return hmac.compare_digest(header_token, settings.telegram_webhook_secret)


# -------------------------------------------------------------------------
# POST — Inbound Updates
# -------------------------------------------------------------------------

async def telegram_webhook_handler(
    request: Request,
    *,
    tenant_ctx: "TenantContext | None" = None,
    engine_override: Stage0Engine | None = None,
) -> JSONResponse:
    """
    Handle Telegram Bot API webhook Updates (POST).

    Returns 200 quickly to avoid Telegram retries.

    Args:
        request: FastAPI request
        tenant_ctx: Optional tenant context for multi-tenant routes
        engine_override: Optional engine for multi-tenant routes (overrides app.state.engine)
    """
    start_time = time.time()

    # Secret token verification
    # For multi-tenant: use binding's webhook_secret if available
    if tenant_ctx:
        binding = tenant_ctx.channels.get("telegram")
        webhook_secret = binding.credentials.get("webhook_secret", "") if binding else ""
        if webhook_secret:
            header_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not header_token or not hmac.compare_digest(header_token, webhook_secret):
                logger.error("Telegram webhook: secret token verification failed (tenant)")
                AppMetrics.webhook_validation_failed("telegram")
                raise HTTPException(status_code=403, detail="Invalid secret token")
        # If no webhook_secret in binding, skip validation (like single-tenant without secret)
    else:
        if not _verify_secret_token(request):
            logger.error("Telegram webhook: secret token verification failed")
            AppMetrics.webhook_validation_failed("telegram")
            raise HTTPException(status_code=403, detail="Invalid secret token")

    # Parse JSON payload — always return 200 even on malformed input
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Telegram webhook: invalid JSON payload, returning 200 to suppress retries")
        inc_counter("telegram_webhook_malformed_payload")
        return JSONResponse({"ok": True}, status_code=200)

    # Determine tenant_id
    tenant_id = tenant_ctx.tenant_id if tenant_ctx else settings.tenant_id

    # Adapt to domain messages
    adapter = TelegramAdapter()
    messages = adapter._parse_update(payload, tenant_id)

    if not messages:
        # Non-message update (edited_message, callback_query, etc.) — acknowledge
        return JSONResponse({"ok": True}, status_code=200)

    # Get engine
    engine: Stage0Engine = engine_override or request.app.state.engine

    request_id = getattr(request.state, "request_id", "unknown")

    results = []
    for message in messages:
        log_ctx = LogContext(
            logger,
            tenant_id=message.tenant_id,
            chat_id=message.chat_id,
            request_id=request_id,
        )

        # Per-chat rate limiting
        allowed, retry_after = _get_chat_rate_limiter().is_allowed(message.chat_id)
        if not allowed:
            log_ctx.warning(f"Rate limit exceeded for chat, retry_after={retry_after}s")
            inc_counter("webhook_rate_limited", tenant_id=message.tenant_id, provider="telegram")
            results.append({"message_id": message.message_id, "status": "rate_limited"})
            continue

        try:
            log_ctx.info(
                f"Telegram webhook received: chat_id={message.chat_id[:4]}***, "
                f"has_text={message.has_text()}, has_media={message.has_media()}"
            )

            # Process through domain engine
            with AppMetrics.track_processing_time(message.tenant_id, "telegram_webhook"):
                result = await engine.process_inbound_message(message)

            AppMetrics.request_received(message.tenant_id, result["step"])
            inc_counter("inbound_messages_total", provider="telegram")

            elapsed_ms = (time.time() - start_time) * 1000
            log_ctx.info(
                f"Telegram webhook processed: step={result['step']}, "
                f"lead_id={result['lead_id']}, elapsed={elapsed_ms:.0f}ms"
            )

            # Enqueue outbound reply as a durable job
            if result.get("reply") and result["reply"] not in (None, "(duplicate ignored)"):
                job_repo = get_job_repo()
                await job_repo.enqueue(
                    tenant_id=message.tenant_id,
                    job_type="outbound_reply",
                    payload={
                        "provider": "telegram",
                        "chat_id": message.chat_id,
                        "text": result["reply"],
                        "message_id": message.message_id,
                    },
                    priority=-1,
                    max_attempts=5,
                )

            # Enqueue media processing as a durable job
            if message.has_media():
                job_repo = get_job_repo()
                media_items = [
                    {
                        "url": m.url,
                        "content_type": m.content_type,
                        "size_bytes": m.size_bytes,
                        "provider_media_id": m.provider_media_id,
                    }
                    for m in message.media
                ]
                await job_repo.enqueue(
                    tenant_id=message.tenant_id,
                    job_type="process_media",
                    payload={
                        "provider": "telegram",
                        "tenant_id": message.tenant_id,
                        "chat_id": message.chat_id,
                        "message_id": message.message_id,
                        "media_items": media_items,
                    },
                    priority=0,
                    max_attempts=3,
                )

            results.append({
                "message_id": message.message_id,
                "status": "processed",
                "step": result["step"],
            })

        except Exception as exc:
            log_ctx.error(
                f"Telegram webhook processing failed: {exc.__class__.__name__}",
                exc_info=True,
            )
            results.append({"message_id": message.message_id, "status": "error"})

    # Always return 200 to prevent Telegram retries
    return JSONResponse({"ok": True, "processed": len(results)}, status_code=200)
