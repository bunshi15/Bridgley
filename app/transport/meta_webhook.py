# app/transport/meta_webhook.py
"""
Meta WhatsApp Cloud API webhook handler.

Handles:
- GET /webhooks/meta — verification handshake (hub.verify_token + hub.challenge)
- POST /webhooks/meta — inbound messages and status updates

Security features:
- Verify token validation (required)
- Optional X-Hub-Signature-256 payload signature verification
- Per-chat rate limiting (anti-spam)
- Fast 200 response to avoid Meta timeout (< 5 seconds)
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import TYPE_CHECKING

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import settings

if TYPE_CHECKING:
    from app.infra.tenant_registry import TenantContext
from app.core.use_cases import Stage0Engine
from app.transport.adapters import MetaCloudAdapter
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


def _mask_phone(phone: str) -> str:
    if not phone:
        return "***"
    if len(phone) <= 6:
        return "***"
    return f"{phone[:4]}***{phone[-4:]}"


# -------------------------------------------------------------------------
# GET — Webhook Verification
# -------------------------------------------------------------------------

async def meta_webhook_verify(
    request: Request,
    *,
    tenant_ctx: "TenantContext | None" = None,
) -> PlainTextResponse:
    """
    Handle Meta webhook verification (GET).

    Meta sends:
      hub.mode=subscribe
      hub.verify_token=<configured token>
      hub.challenge=<random string>

    We must respond with hub.challenge as plain text on success,
    or 403 on failure.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    # Determine expected verify token
    if tenant_ctx:
        binding = tenant_ctx.channels.get("meta")
        expected_token = binding.config.get("webhook_verify_token", "") if binding else ""
    else:
        expected_token = settings.meta_webhook_verify_token

    if mode == "subscribe" and token == expected_token:
        logger.info("Meta webhook verification successful")
        inc_counter("meta_webhook_verified")
        return PlainTextResponse(content=challenge, status_code=200)

    logger.warning(
        f"Meta webhook verification failed: mode={mode}, token_match={token == expected_token}"
    )
    AppMetrics.webhook_validation_failed("meta")
    raise HTTPException(status_code=403, detail="Verification failed")


# -------------------------------------------------------------------------
# Signature Verification (optional)
# -------------------------------------------------------------------------

def _verify_signature(request: Request, body: bytes, *, app_secret: str | None = None) -> bool:
    """
    Verify X-Hub-Signature-256 header against payload.
    Returns True if valid or if signature verification is disabled.

    Args:
        app_secret: Override app secret (for multi-tenant; defaults to settings)
    """
    secret = app_secret or settings.meta_app_secret
    if not secret:
        # Signature verification not configured — skip
        return True

    signature_header = request.headers.get("X-Hub-Signature-256", "")
    if not signature_header:
        logger.warning("Meta webhook: missing X-Hub-Signature-256 header")
        return False

    # Header format: "sha256=<hex digest>"
    if not signature_header.startswith("sha256="):
        logger.warning("Meta webhook: invalid signature format")
        return False

    expected_sig = signature_header[7:]  # strip "sha256="
    computed_sig = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, computed_sig)


# -------------------------------------------------------------------------
# POST — Inbound Events
# -------------------------------------------------------------------------

async def meta_webhook_handler(
    request: Request,
    *,
    tenant_ctx: "TenantContext | None" = None,
    engine_override: Stage0Engine | None = None,
) -> JSONResponse:
    """
    Handle Meta WhatsApp Cloud API webhook events (POST).

    Must return 200 quickly to avoid Meta retries.

    Args:
        request: FastAPI request
        tenant_ctx: Optional tenant context for multi-tenant routes
        engine_override: Optional engine for multi-tenant routes (overrides app.state.engine)
    """
    start_time = time.time()

    # Read raw body for signature verification
    body = await request.body()

    # Signature verification
    # For multi-tenant: use binding's app_secret if available
    if tenant_ctx:
        binding = tenant_ctx.channels.get("meta")
        app_secret = binding.credentials.get("app_secret", "") if binding else ""
    else:
        app_secret = None  # will fall back to settings

    if not _verify_signature(request, body, app_secret=app_secret):
        logger.error("Meta webhook: signature verification failed")
        AppMetrics.webhook_validation_failed("meta")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Parse JSON payload — always return 200 even on malformed input
    # to prevent Meta from retrying bad payloads indefinitely
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Meta webhook: invalid JSON payload, returning 200 to suppress retries")
        inc_counter("meta_webhook_malformed_payload")
        return JSONResponse({"status": "ok"}, status_code=200)

    # Determine tenant_id
    tenant_id = tenant_ctx.tenant_id if tenant_ctx else settings.tenant_id

    # Adapt to domain messages
    adapter = MetaCloudAdapter()
    messages = adapter.adapt_payload(payload, tenant_id)

    if not messages:
        # Status update or non-message event — acknowledge
        return JSONResponse({"status": "ok"}, status_code=200)

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
            inc_counter("webhook_rate_limited", tenant_id=message.tenant_id, provider="meta")
            results.append({"message_id": message.message_id, "status": "rate_limited"})
            continue

        try:
            log_ctx.info(
                f"Meta webhook received: from={_mask_phone(message.chat_id)}, "
                f"has_text={message.has_text()}, has_media={message.has_media()}"
            )

            # Process through domain engine FIRST — returns confirmation reply
            # instantly so the user sees "Photo received" without waiting
            # for the slow media download/processing.
            with AppMetrics.track_processing_time(message.tenant_id, "meta_webhook"):
                result = await engine.process_inbound_message(message)

            AppMetrics.request_received(message.tenant_id, result["step"])
            inc_counter("inbound_messages_total", provider="meta")

            elapsed_ms = (time.time() - start_time) * 1000
            log_ctx.info(
                f"Meta webhook processed: step={result['step']}, "
                f"lead_id={result['lead_id']}, elapsed={elapsed_ms:.0f}ms"
            )

            # Enqueue outbound reply as a durable job
            if result.get("reply") and result["reply"] not in (None, "(duplicate ignored)"):
                job_repo = get_job_repo()
                await job_repo.enqueue(
                    tenant_id=message.tenant_id,
                    job_type="outbound_reply",
                    payload={
                        "provider": "meta",
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
                        "provider": "meta",
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
                f"Meta webhook processing failed: {exc.__class__.__name__}",
                exc_info=True,
            )
            results.append({"message_id": message.message_id, "status": "error"})

    # Always return 200 to prevent Meta retries
    return JSONResponse({"status": "ok", "processed": len(results)}, status_code=200)
