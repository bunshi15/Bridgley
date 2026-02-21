# app/transport/twilio_webhook.py
"""
Twilio webhook handler with signature validation and secure media processing.

Security features:
- Twilio signature validation (HMAC-SHA1)
- Per-chat rate limiting (anti-spam)
- Secure media downloading with size limits
- Image re-encoding to strip EXIF/metadata
- Format validation using magic bytes
"""
from typing import TYPE_CHECKING

from fastapi import Request, HTTPException
from fastapi.responses import PlainTextResponse
from twilio.request_validator import RequestValidator

from app.config import settings
from app.core.use_cases import Stage0Engine
from app.core.domain import InboundMessage
from app.transport.adapters import TwilioAdapter
from app.infra.logging_config import get_logger, LogContext
from app.infra.metrics import AppMetrics, inc_counter
from app.infra.pg_job_repo_async import get_job_repo
from app.infra.rate_limiter import InMemoryRateLimiter

if TYPE_CHECKING:
    from app.infra.tenant_registry import TenantContext

logger = get_logger(__name__)

# Per-chat rate limiter (lazy init to use settings)
_chat_rate_limiter: InMemoryRateLimiter | None = None


def _get_chat_rate_limiter() -> InMemoryRateLimiter:
    """Get or create per-chat rate limiter"""
    global _chat_rate_limiter
    if _chat_rate_limiter is None:
        _chat_rate_limiter = InMemoryRateLimiter(
            max_requests=settings.chat_rate_limit_per_minute,
            window_seconds=60
        )
    return _chat_rate_limiter


def _mask_phone(phone: str) -> str:
    """Mask phone number for logging: whatsapp:+1234567890 -> whatsapp:+123***7890"""
    if not phone:
        return "***"
    # Handle whatsapp: prefix
    prefix = ""
    clean = phone
    if phone.startswith("whatsapp:"):
        prefix = "whatsapp:"
        clean = phone[9:]
    if len(clean) <= 6:
        return f"{prefix}***"
    return f"{prefix}{clean[:4]}***{clean[-4:]}"


async def get_validated_twilio_message(
    request: Request,
    *,
    tenant_ctx: "TenantContext | None" = None,
) -> InboundMessage:
    """
    Dependency that validates Twilio signature and returns normalized domain model.
    Use this as a dependency in your Twilio webhook endpoint.

    Args:
        tenant_ctx: Optional tenant context for multi-tenant routes
    """
    # Determine auth token and tenant_id
    if tenant_ctx:
        binding = tenant_ctx.channels.get("twilio")
        auth_token = binding.credentials.get("auth_token", "") if binding else ""
        webhook_url = binding.config.get("webhook_url", "") if binding else ""
        tenant_id = tenant_ctx.tenant_id
    else:
        auth_token = settings.twilio_auth_token
        webhook_url = settings.twilio_webhook_url
        tenant_id = settings.tenant_id

    # Validate signature if required
    if settings.require_webhook_validation:
        if not auth_token:
            logger.error("TWILIO_AUTH_TOKEN not configured")
            AppMetrics.webhook_validation_failed("twilio")
            raise HTTPException(status_code=500, detail="Webhook validation not configured")

        # Get signature
        signature = request.headers.get("X-Twilio-Signature", "")
        if not signature:
            logger.warning("Missing X-Twilio-Signature header")
            AppMetrics.webhook_validation_failed("twilio")
            raise HTTPException(status_code=403, detail="Missing signature")

        # Get form data for validation
        form = await request.form()
        form_dict = dict(form)

        # Validate signature
        validator = RequestValidator(auth_token)

        # Reconstruct the URL that Twilio used to sign the request
        # When behind a proxy (Cloudflare, nginx), request.url gives internal URL
        # but Twilio signed with the public URL
        if webhook_url:
            # Use configured public URL
            url = webhook_url
        else:
            # Try to reconstruct from proxy headers
            proto = request.headers.get("X-Forwarded-Proto", "https")
            host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "")
            path = request.url.path
            url = f"{proto}://{host}{path}"

        if not validator.validate(url, form_dict, signature):
            logger.error("Invalid Twilio signature", extra={"url": url})
            AppMetrics.webhook_validation_failed("twilio")
            raise HTTPException(status_code=403, detail="Invalid signature")

        logger.debug("Twilio signature validated successfully")

    # Convert to domain model
    adapter = TwilioAdapter()
    message = await adapter.adapt(request, tenant_id)

    return message


async def twilio_webhook_handler(
    request: Request,
    *,
    tenant_ctx: "TenantContext | None" = None,
    engine_override: Stage0Engine | None = None,
) -> PlainTextResponse:
    """
    Main Twilio webhook endpoint.

    Twilio expects a TwiML response or plain text response within 15 seconds.
    For longer processing, respond immediately and process in background.

    Args:
        request: FastAPI request
        tenant_ctx: Optional tenant context for multi-tenant routes
        engine_override: Optional engine for multi-tenant routes (overrides app.state.engine)
    """
    import time
    start_time = time.time()

    # Validate and get message (manually resolve since not using FastAPI DI)
    message = await get_validated_twilio_message(request, tenant_ctx=tenant_ctx)

    request_id = getattr(request.state, "request_id", "unknown")
    log_ctx = LogContext(
        logger,
        tenant_id=message.tenant_id,
        chat_id=message.chat_id,
        request_id=request_id,
    )

    log_ctx.info(
        f"Twilio webhook received: from={_mask_phone(message.chat_id)}, "
        f"has_text={message.has_text()}, has_media={message.has_media()}"
    )

    # Per-chat rate limiting (anti-spam)
    allowed, retry_after = _get_chat_rate_limiter().is_allowed(message.chat_id)
    if not allowed:
        log_ctx.warning(f"Rate limit exceeded for chat, retry_after={retry_after}s")
        inc_counter("webhook_rate_limited", tenant_id=message.tenant_id)
        # Return friendly message instead of error
        twiml = create_twiml_response(
            "Слишком много сообщений. Пожалуйста, подождите минуту."
        )
        return PlainTextResponse(content=twiml, media_type="application/xml")

    try:
        # Get engine from app state
        engine: Stage0Engine = engine_override or request.app.state.engine

        # Process the domain model FIRST — this returns the confirmation reply
        # instantly (no I/O) so the user sees "Photo received" without waiting
        # for the slow media download/processing.
        with AppMetrics.track_processing_time(message.tenant_id, "twilio_webhook"):
            result = await engine.process_inbound_message(message)

        AppMetrics.request_received(message.tenant_id, result["step"])

        elapsed_ms = (time.time() - start_time) * 1000
        log_ctx.info(
            f"Twilio webhook processed: step={result['step']}, lead_id={result['lead_id']}, elapsed={elapsed_ms:.0f}ms",
            extra={"step": result["step"], "lead_id": result["lead_id"], "elapsed_ms": elapsed_ms}
        )

        # Log response for debugging
        if elapsed_ms > 5000:
            log_ctx.warning(f"Slow webhook response: {elapsed_ms:.0f}ms - may cause Twilio timeout")

        # Return TwiML response for WhatsApp/SMS
        # When reply is None (e.g. 2nd+ photo in a batch), return empty TwiML
        # so the user doesn't receive a message
        if result.get("reply"):
            twiml = create_twiml_response(result["reply"])
        else:
            twiml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

        # Enqueue media processing as a durable job.
        # The user sees the confirmation immediately while media is downloaded,
        # validated, and saved by the job worker.
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
                    "provider": "twilio",
                    "tenant_id": message.tenant_id,
                    "chat_id": message.chat_id,
                    "message_id": message.message_id,
                    "media_items": media_items,
                },
                priority=0,
                max_attempts=3,
            )

        return PlainTextResponse(content=twiml, media_type="application/xml")

    except Exception as exc:
        log_ctx.error(
            f"Twilio webhook processing failed: {exc.__class__.__name__}",
            exc_info=True
        )

        # Return error message to user via TwiML
        error_twiml = create_twiml_response("Sorry, something went wrong. Please try again later.")
        return PlainTextResponse(
            content=error_twiml,
            media_type="application/xml",
            status_code=200  # Still return 200 so Twilio doesn't retry
        )


def create_twiml_response(message: str) -> str:
    """
    Create a TwiML response for Twilio.
    Use this if you need more control over the response (media, multiple messages, etc.)

    IMPORTANT: Message must be XML-escaped to prevent parsing errors.
    """
    import html
    # Escape XML special characters: & < > " '
    escaped_message = html.escape(message, quote=True)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{escaped_message}</Message>
</Response>"""
