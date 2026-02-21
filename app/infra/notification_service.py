# app/infra/notification_service.py
"""
Notification service for sending lead data to operators.

Supports multiple notification channels:
- WhatsApp (via Twilio) - with rate limiting and retry queue
- Telegram - simple HTTP API
- Email - SMTP

Configure via settings:
- OPERATOR_NOTIFICATIONS_ENABLED: bool (master switch)
- OPERATOR_NOTIFICATION_CHANNEL: "whatsapp" | "telegram" | "email"
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.config import settings
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)

# Twilio client (lazy initialization) - used by WhatsApp channel
_twilio_client = None


def _get_twilio_client():
    """Get or create Twilio client."""
    global _twilio_client
    if _twilio_client is None:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            logger.error("Twilio credentials not configured")
            return None
        from twilio.rest import Client
        _twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _twilio_client


async def _send_twilio_message(message) -> bool:
    """
    Actually send a message via Twilio.

    This is the function used by the outbound queue for WhatsApp.
    Returns True on success, False on failure (for retry).
    """
    client = _get_twilio_client()
    if not client:
        return False

    try:
        message_kwargs = {
            "from_": settings.twilio_phone_number if settings.twilio_phone_number.startswith("whatsapp:")
                     else f"whatsapp:{settings.twilio_phone_number}",
            "to": message.to if message.to.startswith("whatsapp:") else f"whatsapp:{message.to}",
        }

        # Twilio WhatsApp requires body or media_url (not both empty).
        # For photo-only messages body may be empty — omit it.
        if message.body:
            message_kwargs["body"] = message.body

        if message.media_urls:
            message_kwargs["media_url"] = message.media_urls

        # Safety: Twilio requires at least one of body or media_url
        if not message.body and not message.media_urls:
            logger.warning(f"Skipping empty Twilio message: {message.id}")
            return True

        result = client.messages.create(**message_kwargs)

        logger.info(
            f"Twilio message sent: sid={result.sid[:8]}***, to={message.to[:6]}***",
            extra={"message_sid": result.sid, "queue_msg_id": message.id}
        )
        inc_counter("operator_notifications_sent", tenant_id=settings.tenant_id)
        return True

    except Exception as exc:
        error_code = getattr(exc, 'code', None)

        # 63016: Outside 24h session window — freeform blocked by WhatsApp.
        # Fall back to Content Template if configured.
        if error_code == 63016:
            logger.warning(
                "Twilio 63016 (outside 24h window), attempting template fallback",
                extra={"queue_msg_id": message.id, "error_code": error_code},
            )
            return await _send_twilio_template_fallback(message)

        # Check if it's a rate limit error (429 / 63038)
        if error_code == 63038 or '429' in str(exc) or 'rate' in str(exc).lower():
            logger.warning(
                f"Twilio rate limit hit, will retry: {exc}",
                extra={"queue_msg_id": message.id, "error_code": error_code}
            )
            return False  # Signal retry

        # Other errors - log but still retry (might be transient)
        logger.error(
            f"Twilio send failed: {exc}",
            extra={"queue_msg_id": message.id, "error_code": error_code},
            exc_info=True
        )
        inc_counter("operator_notifications_failed", tenant_id=settings.tenant_id)
        return False


async def _send_twilio_template_fallback(message) -> bool:
    """Send a Content Template message as fallback when freeform is blocked (63016).

    Uses ``twilio_content_sid`` from message metadata to send a pre-approved
    template with key lead data as variables.

    Returns True on success (or when gracefully skipped), False on failure.
    """
    # Photo-only messages (empty body) — can't template photos, skip gracefully
    if not message.body:
        logger.info(
            "Skipping template fallback for photo-only message (63016)",
            extra={"queue_msg_id": message.id},
        )
        return True

    content_sid = message.metadata.get("twilio_content_sid")
    if not content_sid:
        logger.error(
            "Template fallback needed but TWILIO_CONTENT_SID not configured. "
            "Operator will not receive this notification. "
            "Set TWILIO_CONTENT_SID env var or ask operator to message the bot.",
            extra={"queue_msg_id": message.id},
        )
        # Return True to stop futile retries — 63016 won't resolve on its own
        return True

    client = _get_twilio_client()
    if not client:
        return False

    try:
        import json as _json

        template_vars = message.metadata.get("template_vars", {})
        content_variables = _json.dumps({
            "1": template_vars.get("contact", ""),
            "2": template_vars.get("cargo", ""),
            "3": template_vars.get("addr_from", ""),
            "4": template_vars.get("addr_to", ""),
            "5": template_vars.get("estimate", ""),
        })

        result = client.messages.create(
            content_sid=content_sid,
            content_variables=content_variables,
            from_=settings.twilio_phone_number if settings.twilio_phone_number.startswith("whatsapp:")
                  else f"whatsapp:{settings.twilio_phone_number}",
            to=message.to if message.to.startswith("whatsapp:") else f"whatsapp:{message.to}",
        )

        logger.info(
            f"Twilio template fallback sent: sid={result.sid[:8]}***",
            extra={"message_sid": result.sid, "queue_msg_id": message.id},
        )
        inc_counter("operator_notifications_sent_template", tenant_id=settings.tenant_id)
        return True

    except Exception as exc:
        logger.error(
            f"Twilio template fallback failed: {exc}",
            extra={"queue_msg_id": message.id},
            exc_info=True,
        )
        inc_counter("operator_notifications_failed", tenant_id=settings.tenant_id)
        return False


def _mask_phone(phone: str) -> str:
    """Mask phone number for logging: +1234567890 -> +123***7890"""
    if not phone:
        return "***"
    # Remove whatsapp: prefix if present
    clean = phone.replace("whatsapp:", "").strip()
    if len(clean) <= 6:
        return "***"
    return f"{clean[:4]}***{clean[-4:]}"


def _format_extras(extras: list[str] | None) -> str:
    """Format extras list to Russian labels."""
    if not extras:
        return "нет"

    labels = {
        "loaders": "грузчики",
        "assembly": "сборка/разборка",
        "packing": "упаковка",
        "none": "нет",
    }
    return ", ".join(labels.get(e, e) for e in extras if e != "none")


def _format_time_window(time_window: str | None) -> str:
    """Format time window to Russian with date."""
    today = datetime.now()
    date_str = today.strftime("%d/%m/%Y")

    labels = {
        # Legacy (Phase 1)
        "today": f"сегодня ({date_str})",
        "tomorrow": "завтра",
        "soon": "в ближайшие дни",
        # Phase 2: time slot values
        "morning": "утро (08:00–12:00)",
        "afternoon": "день (12:00–16:00)",
        "evening": "вечер (16:00–20:00)",
        "flexible": "время не определено",
    }

    # Handle "exact:HH:MM" format from Phase 2
    if time_window and time_window.startswith("exact:"):
        return f"точное время: {time_window[6:]}"

    return labels.get(time_window, time_window or "не указано")


def format_lead_message(chat_id: str, payload: dict[str, Any]) -> str:
    """
    Format lead data into a readable message for the operator in Russian.
    """
    # Get data from payload
    data = payload.get("data", payload)  # Handle both nested and flat structure

    # Build contact line:
    # - Telegram: use sender_name from custom data (e.g. "Ivan Petrov (@ivan_p)")
    # - WhatsApp/Twilio: extract phone number from chat_id
    custom = data.get("custom", {})
    sender_name = custom.get("sender_name")

    if sender_name:
        # Telegram or other provider with sender_name
        contact = sender_name
    else:
        # WhatsApp/Twilio — extract phone from chat_id
        contact = chat_id.replace("whatsapp:", "").strip()

    # --- Resolve translated values for main body ---
    # When translation succeeded, use translated fields in the main body
    # so the operator reads everything in their language immediately.
    trans_meta = custom.get("translation_meta", {})
    _translated = {}
    if trans_meta.get("status") in ("ok", "unchanged"):
        target_lang = trans_meta.get("target_lang", "ru")
        _translated = custom.get("translations", {}).get(target_lang, {})

    def _t(field: str, fallback: str | None = None) -> str | None:
        """Return translated value if available, else original."""
        val = _translated.get(field)
        if val and val.strip():
            return val.strip()
        return fallback

    cargo = _t("cargo_description", data.get("cargo_description")) or "не указано"
    # Support both old "addresses" field and new split addr_from/addr_to
    addr_from = _t("addr_from", data.get("addr_from"))
    addr_to = _t("addr_to", data.get("addr_to"))
    floor_from = data.get("floor_from")
    floor_to = data.get("floor_to")

    # Phase 4: multi-pickup formatting
    pickups = custom.get("pickups", [])

    if len(pickups) > 1:
        # Multi-pickup: numbered list of pickup locations + delivery
        addr_lines = []
        for i, p in enumerate(pickups, 1):
            pickup_addr = _t(f"pickup_{i}_addr", p.get("addr")) or "не указано"
            line = f"  Забор {i}: {pickup_addr}"
            floor_val = _t(f"pickup_{i}_floor", p.get("floor"))
            if floor_val and floor_val != "—":
                line += f" (этаж: {floor_val})"
            elif p.get("floor") and p["floor"] != "—":
                line += f" (этаж: {p['floor']})"
            addr_lines.append(line)
        delivery = addr_to or "не указано"
        if floor_to:
            delivery += f" (этаж: {floor_to})"
        addr_lines.append(f"  Доставка: {delivery}")
        addresses = "\n".join(addr_lines)
    elif addr_from or addr_to:
        pickup = addr_from or "не указано"
        if floor_from:
            pickup += f" (этаж: {floor_from})"
        delivery = addr_to or "не указано"
        if floor_to:
            delivery += f" (этаж: {floor_to})"
        addresses = f"{pickup} → {delivery}"
    else:
        addresses = data.get("addresses", "не указано")
    time_window_str = _format_time_window(data.get("time_window"))
    # Phase 2: prepend ISO move_date from custom dict when available
    move_date = custom.get("move_date")
    if move_date:
        time_window_str = f"{move_date}, {time_window_str}"
    extras = _format_extras(data.get("extras"))
    details = _t("details_free", data.get("details_free")) or data.get("custom", {}).get("notes")
    photo_count = data.get("photo_count", 0)

    # Phase 3: pricing estimate
    estimate_min = custom.get("estimate_min")
    estimate_max = custom.get("estimate_max")
    estimate_str = None
    if estimate_min is not None and estimate_max is not None:
        estimate_str = f"{estimate_min}–{estimate_max} ₪"

    # Phase 5: geo points → map links for operator
    geo_points = custom.get("geo_points", {})
    geo_lines: list[str] = []
    if geo_points:
        for key, pt in geo_points.items():
            lat, lon = pt.get("lat"), pt.get("lon")
            if lat is not None and lon is not None:
                label = key.replace("_", " ").capitalize()
                addr = pt.get("address") or pt.get("name")
                map_link = f"https://maps.google.com/?q={lat},{lon}"
                if addr:
                    geo_lines.append(f"  {label}: {addr}\n    {map_link}")
                else:
                    geo_lines.append(f"  {label}: {map_link}")

    # Multi-pickup uses "Адреса:" (plural) with multi-line block
    if len(pickups) > 1:
        addr_label = f"Адреса:\n{addresses}"
    else:
        addr_label = f"Адрес: {addresses}"

    # Lead number (sequential, from DB migration 010)
    lead_number = custom.get("lead_number")
    lead_header = "📦 Новая заявка"
    if lead_number is not None:
        lead_header = f"📦 Заявка #{lead_number}"

    lines = [
        lead_header,
        f"📱 От: {contact}",
        "",
        f"Статус: Получена\n",
        f"Что везем: {cargo}\n",
        addr_label,
    ]

    if geo_lines:
        lines.append(f"\n📍 Геоточки:\n" + "\n".join(geo_lines))

    lines += [
        f"\nДата: {time_window_str}\n",
        f"Дополнительно: {extras}\n",
    ]

    if estimate_str:
        lines.append(f"💰 Оценка: {estimate_str}")

    # Phase 8: Region classification
    region_info = custom.get("region_classifications", {})
    if region_info:
        any_outside = any(not r.get("inside_metro", True) for r in region_info.values())
        if any_outside:
            lines.append("⚠️ Зона: за пределами агломерации большая Хайфа")
        else:
            lines.append("📍 Зона: Агломерация большой Хайфы")

    if details:
        lines.append(f"Комментарий: {details}\n")

    if photo_count > 0:
        lines.append(f"📷 Фото: {photo_count} шт.\n")

    # Original text block: when translation was used in main body,
    # show originals for reference (operator can compare if needed)
    if _translated and trans_meta.get("status") in ("ok", "unchanged"):
        source_lang = trans_meta.get("source_lang", "")
        lang_labels = {"ru": "RU", "en": "EN", "he": "HE"}
        lang_label = lang_labels.get(source_lang, source_lang.upper())
        # Show key originals so operator can cross-reference
        _orig_fields = {
            "cargo_description": ("Груз", data.get("cargo_description")),
            "addr_from": ("Откуда", data.get("addr_from")),
            "addr_to": ("Куда", data.get("addr_to")),
            "details_free": ("Комментарий", data.get("details_free")),
        }
        orig_lines = []
        for field_key, (label, orig_val) in _orig_fields.items():
            if orig_val and orig_val.strip() and field_key in _translated:
                orig_lines.append(f"  {label}: {orig_val}")
        if orig_lines:
            lines.append(f"\n🌐 Оригинал ({lang_label}):")
            lines.extend(orig_lines)

    # Session language indicator
    session_lang = custom.get("session_language")
    if session_lang and session_lang != "ru":
        lang_names = {"en": "English", "he": "עברית"}
        lines.append(f"\n🗣 Язык клиента: {lang_names.get(session_lang, session_lang)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dispatch re-exports (canonical: app.core.dispatch.*)
# Keep backward-compatible imports for existing callers.
# ---------------------------------------------------------------------------
from app.core.dispatch.crew_view import format_crew_message  # noqa: F401
from app.core.dispatch.services import notify_operator_crew_fallback  # noqa: F401


async def _get_photo_urls_for_lead(tenant_id: str, lead_id: str) -> list[str]:
    """
    Get photo URLs for a specific lead/ticket.

    IMPORTANT: This fetches photos by lead_id, not chat_id, so it only
    includes photos uploaded during THIS ticket, not previous tickets.

    URL strategy (in order of preference):
    1. If S3_PUBLIC_URL is configured: use S3 direct URLs (fastest, CDN-ready)
    2. Otherwise: use /media/{id} endpoint (proxies from S3 or DB)

    The /media endpoint is always public if your webhook URL is public,
    so it works even when MinIO is internal-only.
    """
    from app.infra.pg_photo_repo_async import get_photo_repo

    try:
        repo = get_photo_repo()
        photos = await repo.get_for_lead(tenant_id, lead_id, limit=10)

        if not photos:
            return []

        # Check if we have a public S3 URL configured
        # If not, we'll use the /media endpoint which proxies from S3/DB
        use_s3_direct = bool(settings.s3_public_url)

        # Get base URL for /media endpoint
        base_url = None
        if not use_s3_direct:
            if settings.twilio_webhook_url:
                base_url = settings.twilio_webhook_url.rsplit("/webhooks", 1)[0]
            else:
                logger.warning("No webhook URL configured, cannot generate photo URLs for /media proxy")
                return []

        # Import signed URL generator for /media endpoint security
        from app.transport.security import generate_signed_media_url

        urls = []
        for photo in photos:
            if use_s3_direct and photo.s3_url:
                # S3 public URL configured - use direct S3 URL
                urls.append(photo.s3_url)
            else:
                # Use /media endpoint as proxy (works with internal MinIO)
                # SECURITY: Sign URL with HMAC so only authorized links work
                urls.append(generate_signed_media_url(base_url, str(photo.id)))

        return urls

    except Exception as e:
        logger.warning(f"Failed to get photos for lead {lead_id}: {e}")
        return []


async def notify_operator(
    lead_id: str,
    chat_id: str,
    payload: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> bool:
    """
    Send lead notification to operator via configured channel.

    Channel and destination are resolved per-tenant (v0.8.1):
    - Reads ``operator_notifications_enabled``, ``operator_notification_channel``,
      ``operator_whatsapp`` from tenant config first, then falls back to
      ``settings.*``.

    Args:
        lead_id: The lead identifier
        chat_id: The customer's chat ID (phone number)
        payload: The lead data
        tenant_id: Tenant to resolve operator config for (None = global)

    Returns:
        True if notification was sent/queued successfully, False otherwise
    """
    from app.infra.notification_channels import (
        OperatorNotification,
        get_notification_channel,
    )
    from app.infra.tenant_registry import get_operator_config

    # Resolve per-tenant operator config (with global fallback)
    op_cfg = get_operator_config(tenant_id)

    # Check enabled switch
    if not op_cfg["enabled"]:
        logger.debug(
            f"Operator notifications disabled for tenant={tenant_id or 'global'}"
        )
        return True  # Return True to not trigger errors

    resolved_tenant_id = tenant_id or settings.tenant_id

    try:
        # Translate operator lead payload (if enabled and source != target)
        _payload_data = payload.get("data", payload)
        _source_lang = _payload_data.get("custom", {}).get("session_language") or "ru"
        try:
            from app.core.i18n.lead_translator import translate_lead_payload
            await translate_lead_payload(payload, _source_lang)
        except Exception:
            logger.warning("Lead translation pipeline error", exc_info=True)

        # Format message
        message_body = format_lead_message(chat_id, payload)

        # Get photo URLs for THIS lead only (not previous tickets)
        data = payload.get("data", payload)
        photo_count = data.get("photo_count", 0)
        photo_urls = []

        if photo_count > 0:
            photo_urls = await _get_photo_urls_for_lead(resolved_tenant_id, lead_id)
            if photo_urls:
                logger.info(f"Attaching {len(photo_urls)} photos to operator notification (lead={lead_id[:8]})")

        # Extract structured fields for template fallback (WhatsApp 24h window)
        custom = data.get("custom", {})
        sender_name = custom.get("sender_name")
        contact = sender_name if sender_name else chat_id.replace("whatsapp:", "").strip()
        cargo = data.get("cargo_description", "не указано")
        estimate_min = custom.get("estimate_min")
        estimate_max = custom.get("estimate_max")
        estimate_str = f"{estimate_min}–{estimate_max} ₪" if estimate_min is not None and estimate_max is not None else None

        # Create notification
        notification = OperatorNotification(
            lead_id=lead_id,
            chat_id=chat_id,
            body=message_body,
            photo_urls=photo_urls,
            metadata={
                "template_vars": {
                    "contact": contact,
                    "cargo": cargo,
                    "addr_from": data.get("addr_from") or "не указано",
                    "addr_to": data.get("addr_to") or "не указано",
                    "estimate": estimate_str or "не указано",
                },
            },
        )

        # Get channel and send (tenant-aware)
        channel = get_notification_channel(tenant_id=tenant_id)
        logger.info(
            f"Sending notification via {channel.name}: lead_id={lead_id}, "
            f"tenant={resolved_tenant_id}",
            extra={"lead_id": lead_id, "channel": channel.name, "tenant_id": resolved_tenant_id}
        )

        return await channel.send(notification)

    except Exception as exc:
        logger.error(
            f"Failed to notify operator: lead_id={lead_id}, tenant={resolved_tenant_id}",
            exc_info=True
        )
        inc_counter("operator_notifications_failed", tenant_id=resolved_tenant_id)
        return False



# NOTE: notify_operator_crew_fallback() and format_crew_message() are now
# re-exported from app.core.dispatch above.
