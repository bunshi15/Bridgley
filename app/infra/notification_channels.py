# app/infra/notification_channels.py
"""
Notification channel abstraction for sending lead notifications to operators.

Supports multiple channels:
- WhatsApp (via Twilio or Meta Cloud API) - configurable via operator_whatsapp_provider
- Telegram - simple HTTP API, no rate limit issues
- Email - SMTP (placeholder for future)

Usage:
    channel = get_notification_channel()
    await channel.send(notification)
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any
import aiohttp

from app.config import settings
from app.infra.http_client import get_default_session
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)

# Phase 4: retry config for Meta operator notifications.
# One retry is enough — if Meta is truly down, spamming won't help and
# we don't want to delay the webhook response to the customer.
_META_MAX_ATTEMPTS = 2
_META_RETRY_DELAY_S = 3


@dataclass
class OperatorNotification:
    """Notification data to send to operator"""
    lead_id: str
    chat_id: str  # Customer's chat ID
    body: str  # Formatted message text
    photo_urls: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationChannel(abc.ABC):
    """Abstract base class for notification channels"""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Channel name for logging/metrics"""
        pass

    @abc.abstractmethod
    async def send(self, notification: OperatorNotification) -> bool:
        """
        Send notification to operator.

        Returns:
            True if sent successfully, False otherwise
        """
        pass

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Check if channel is properly configured"""
        pass


def _normalize_whatsapp_number(raw: str, provider: str) -> str:
    """Normalize operator WhatsApp number for the target provider.

    Twilio expects: ``whatsapp:+972501234567``
    Meta expects:   ``972501234567`` (E.164 digits, no ``+``)
    """
    # Strip whatsapp: prefix if present
    clean = raw.replace("whatsapp:", "").strip()
    if provider == "meta":
        return clean.lstrip("+")
    else:
        # Twilio: whatsapp:+...
        if not clean.startswith("+"):
            clean = f"+{clean}"
        return f"whatsapp:{clean}"


class WhatsAppChannel(NotificationChannel):
    """
    WhatsApp notification channel — supports Twilio and Meta Cloud API.

    Provider is selected via ``operator_whatsapp_provider`` setting:
    - ``"twilio"`` (default): outbound queue with rate limiting
    - ``"meta"``: direct send via Meta Cloud API (higher rate limits)

    The *destination* (``operator_whatsapp``) can be per-tenant (v0.8.1).
    """

    def __init__(
        self,
        operator_whatsapp: str | None = None,
        provider: str = "twilio",
        twilio_content_sid: str | None = None,
    ) -> None:
        self._operator_whatsapp = operator_whatsapp or settings.operator_whatsapp
        self._provider = provider
        self._twilio_content_sid = twilio_content_sid

    @property
    def name(self) -> str:
        return "whatsapp"

    def is_configured(self) -> bool:
        if not self._operator_whatsapp:
            return False
        if self._provider == "meta":
            return bool(
                settings.meta_access_token
                and settings.meta_phone_number_id
            )
        else:  # twilio
            return bool(
                settings.twilio_phone_number
                and settings.twilio_account_sid
                and settings.twilio_auth_token
            )

    async def send(self, notification: OperatorNotification) -> bool:
        if not self.is_configured():
            logger.warning(
                "WhatsApp channel not configured (provider=%s)", self._provider
            )
            return False

        if self._provider == "meta":
            return await self._send_via_meta(notification)
        else:
            return await self._send_via_twilio(notification)

    async def _send_via_twilio(self, notification: OperatorNotification) -> bool:
        """Send via Twilio with outbound queue and rate limiting."""
        import uuid
        from app.infra.outbound_queue import OutboundMessage, get_outbound_queue
        from app.infra.notification_service import _send_twilio_message, _mask_phone

        to_number = _normalize_whatsapp_number(self._operator_whatsapp, "twilio")
        dest_masked = _mask_phone(self._operator_whatsapp)

        queue = get_outbound_queue()
        queue.set_send_function(_send_twilio_message)

        base_metadata = {
            "lead_id": notification.lead_id,
            "chat_id": notification.chat_id,
            **notification.metadata,
        }
        if self._twilio_content_sid:
            base_metadata["twilio_content_sid"] = self._twilio_content_sid

        # Twilio WhatsApp supports only 1 media per message.
        # Send text message first, then each photo as a separate message.
        text_msg = OutboundMessage(
            id=f"lead-{notification.lead_id}-{uuid.uuid4().hex[:8]}",
            to=to_number,
            body=notification.body,
            media_urls=[],
            metadata=base_metadata,
        )
        await queue.enqueue(text_msg)

        for i, photo_url in enumerate(notification.photo_urls[:10]):
            photo_msg = OutboundMessage(
                id=f"lead-{notification.lead_id}-photo{i}-{uuid.uuid4().hex[:8]}",
                to=to_number,
                body="",
                media_urls=[photo_url],
                metadata=base_metadata,
            )
            await queue.enqueue(photo_msg)

        # Process queue in background (non-blocking)
        import asyncio
        asyncio.create_task(queue.process_queue())

        total_queued = 1 + len(notification.photo_urls[:10])
        logger.info(
            "WhatsApp notification queued (twilio): lead_id=%s, dest=%s, "
            "messages=%d (1 text + %d photos)",
            notification.lead_id, dest_masked,
            total_queued, total_queued - 1,
            extra={
                "lead_id": notification.lead_id,
                "provider": "twilio",
                "destination": dest_masked,
            },
        )
        return True

    async def _send_via_meta(self, notification: OperatorNotification) -> bool:
        """Send via Meta WhatsApp Cloud API (direct, no queue).

        Retry policy (Phase 4 hardening):
        - Non-retryable errors (auth 401, token expired, template required,
          invalid recipient) → fail immediately, no retry.
        - Retryable errors (429 rate limit, transient network) → single
          backoff retry after ``_META_RETRY_DELAY_S`` seconds.
        """
        import asyncio
        from app.transport.meta_sender import (
            send_text_message, send_media_message, MetaSendError,
        )
        from app.infra.notification_service import _mask_phone

        to_number = _normalize_whatsapp_number(self._operator_whatsapp, "meta")
        dest_masked = _mask_phone(self._operator_whatsapp)
        _extra = {
            "lead_id": notification.lead_id,
            "provider": "meta",
            "destination": dest_masked,
        }

        # -- Send text (with 1 retry on retryable errors) --
        sent = False
        for attempt in range(1, _META_MAX_ATTEMPTS + 1):
            try:
                await send_text_message(to_number, notification.body)
                sent = True
                break
            except MetaSendError as exc:
                if not exc.retryable or attempt == _META_MAX_ATTEMPTS:
                    lvl = "error" if not exc.retryable else "warning"
                    getattr(logger, lvl)(
                        "Meta WhatsApp text failed (retryable=%s, attempt=%d/%d): %s",
                        exc.retryable, attempt, _META_MAX_ATTEMPTS, exc,
                        extra=_extra,
                    )
                    inc_counter("operator_notifications_failed", tenant_id=settings.tenant_id)
                    return False
                # Retryable — wait and try once more
                logger.warning(
                    "Meta WhatsApp text retryable error (attempt=%d/%d), "
                    "retrying in %ds: %s",
                    attempt, _META_MAX_ATTEMPTS, _META_RETRY_DELAY_S, exc,
                    extra=_extra,
                )
                await asyncio.sleep(_META_RETRY_DELAY_S)
            except Exception as exc:
                logger.error(
                    "Meta WhatsApp unexpected error (attempt=%d/%d): %s",
                    attempt, _META_MAX_ATTEMPTS, exc,
                    extra=_extra, exc_info=True,
                )
                inc_counter("operator_notifications_failed", tenant_id=settings.tenant_id)
                return False

        if not sent:
            return False  # pragma: no cover — safety net

        # -- Send photos as native media messages (Meta fetches by URL) --
        photos_failed = 0
        for photo_url in notification.photo_urls[:10]:
            try:
                await send_media_message(to_number, "image", photo_url)
            except Exception as photo_exc:
                photos_failed += 1
                logger.warning(
                    "Meta photo send failed (%d/%d): %s",
                    photos_failed, len(notification.photo_urls[:10]), photo_exc,
                    extra=_extra,
                )
                # Continue — don't fail the whole notification for one photo

        inc_counter("operator_notifications_sent", tenant_id=settings.tenant_id)
        logger.info(
            "Meta WhatsApp notification sent: lead_id=%s, dest=%s, "
            "photos=%d (failed=%d)",
            notification.lead_id, dest_masked,
            len(notification.photo_urls[:10]), photos_failed,
            extra=_extra,
        )
        return True


class TelegramChannel(NotificationChannel):
    """
    Telegram notification channel.
    Simple HTTP API - no rate limit issues for low volume.
    """

    TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/{method}"

    @property
    def name(self) -> str:
        return "telegram"

    def is_configured(self) -> bool:
        return bool(settings.telegram_bot_token and settings.telegram_chat_id)

    async def send(self, notification: OperatorNotification) -> bool:
        if not self.is_configured():
            logger.warning("Telegram channel not configured")
            return False

        try:
            # Send text message
            success = await self._send_message(notification.body)

            if not success:
                return False

            # Send photos if any (Telegram supports sending photos separately)
            for photo_url in notification.photo_urls[:10]:  # Telegram limit
                # Try URL first, if fails download and upload directly
                url_success = await self._send_photo(photo_url)

                if not url_success:
                    # URL failed (probably internal URL) - try downloading and uploading
                    logger.info(f"Photo URL failed, trying direct upload: {photo_url[:50]}...")
                    photo_data = await self._download_photo(photo_url)
                    if photo_data:
                        await self._send_photo(photo_url, photo_data=photo_data)
                    else:
                        logger.warning(f"Could not download photo for upload: {photo_url[:50]}...")

            inc_counter("operator_notifications_sent", tenant_id=settings.tenant_id)
            logger.info(
                f"Telegram notification sent: lead_id={notification.lead_id}",
                extra={"lead_id": notification.lead_id}
            )
            return True

        except Exception as exc:
            logger.error(
                f"Telegram notification failed: {type(exc).__name__}",
                extra={"lead_id": notification.lead_id},
                exc_info=True
            )
            inc_counter("operator_notifications_failed", tenant_id=settings.tenant_id)
            return False

    async def _send_message(self, text: str) -> bool:
        """Send text message via Telegram Bot API"""
        url = self.TELEGRAM_API_URL.format(
            token=settings.telegram_bot_token,
            method="sendMessage"
        )

        payload = {
            "chat_id": settings.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",  # Allow basic formatting
        }

        session = get_default_session()
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                logger.error(f"Telegram API error: status={resp.status}")
                return False

            result = await resp.json()
            if not result.get("ok"):
                logger.error(f"Telegram API error: ok=false, error_code={result.get('error_code')}")
                return False

            return True

    async def _send_photo(self, photo_url: str, photo_data: bytes | None = None) -> bool:
        """
        Send photo via Telegram Bot API.

        Telegram supports both:
        1. URL (if publicly accessible)
        2. Direct file upload (more reliable)

        If photo_data is provided, uploads directly. Otherwise tries URL.
        """
        url = self.TELEGRAM_API_URL.format(
            token=settings.telegram_bot_token,
            method="sendPhoto"
        )

        try:
            session = get_default_session()
            if photo_data:
                # Direct upload - more reliable
                form = aiohttp.FormData()
                form.add_field("chat_id", settings.telegram_chat_id)
                form.add_field(
                    "photo",
                    photo_data,
                    filename="photo.jpg",
                    content_type="image/jpeg"
                )
                async with session.post(url, data=form, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        logger.warning(f"Telegram photo upload failed: status={resp.status}")
                        return False
                    return True
            else:
                # URL-based (requires public URL)
                payload = {
                    "chat_id": settings.telegram_chat_id,
                    "photo": photo_url,
                }
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        logger.warning(f"Telegram photo URL send failed: status={resp.status}")
                        return False
                    return True
        except Exception as e:
            logger.warning(f"Telegram photo send error: {type(e).__name__}")
            return False

    async def _download_photo(self, url: str) -> bytes | None:
        """Download photo from URL for direct upload."""
        try:
            session = get_default_session()
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    return await resp.read()
                logger.warning(f"Failed to download photo: {resp.status}")
                return None
        except Exception as e:
            logger.warning(f"Photo download error: {type(e).__name__}")
            return None


class EmailChannel(NotificationChannel):
    """
    Email notification channel via SMTP.
    Placeholder for future implementation.
    """

    @property
    def name(self) -> str:
        return "email"

    def is_configured(self) -> bool:
        return bool(
            settings.smtp_host
            and settings.smtp_user
            and settings.smtp_password
            and settings.operator_email
        )

    async def send(self, notification: OperatorNotification) -> bool:
        if not self.is_configured():
            logger.warning("Email channel not configured")
            return False

        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart

            # Create message
            msg = MIMEMultipart()
            msg["From"] = settings.smtp_user
            msg["To"] = settings.operator_email
            msg["Subject"] = f"Новая заявка #{notification.lead_id[:8]}"

            # Add text body
            body = notification.body
            if notification.photo_urls:
                body += "\n\nФото:\n" + "\n".join(notification.photo_urls)

            msg.attach(MIMEText(body, "plain", "utf-8"))

            # Send via SMTP (sync, but okay for low volume)
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_smtp, msg)

            inc_counter("operator_notifications_sent", tenant_id=settings.tenant_id)
            logger.info(
                f"Email notification sent: lead_id={notification.lead_id}",
                extra={"lead_id": notification.lead_id}
            )
            return True

        except Exception as exc:
            logger.error(
                f"Email notification failed: {type(exc).__name__}",
                extra={"lead_id": notification.lead_id},
                exc_info=True
            )
            inc_counter("operator_notifications_failed", tenant_id=settings.tenant_id)
            return False

    def _send_smtp(self, msg) -> None:
        """Send email via SMTP (blocking)"""
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)


class DisabledChannel(NotificationChannel):
    """Dummy channel when notifications are disabled"""

    @property
    def name(self) -> str:
        return "disabled"

    def is_configured(self) -> bool:
        return True  # Always "configured"

    async def send(self, notification: OperatorNotification) -> bool:
        logger.debug(
            f"Notifications disabled, skipping: lead_id={notification.lead_id}"
        )
        return True  # Return True to not trigger errors


# Channel registry
_CHANNELS: dict[str, type[NotificationChannel]] = {
    "whatsapp": WhatsAppChannel,
    "telegram": TelegramChannel,
    "email": EmailChannel,
}


def get_notification_channel(*, tenant_id: str | None = None) -> NotificationChannel:
    """
    Get the configured notification channel.

    Resolves per-tenant operator config (v0.8.1): channel selection and
    WhatsApp destination can be overridden per-tenant.  Falls back to
    ``settings.*`` for anything not set in the tenant config.

    Returns DisabledChannel if notifications are disabled.
    """
    from app.infra.tenant_registry import get_operator_config

    op_cfg = get_operator_config(tenant_id)

    if not op_cfg["enabled"]:
        logger.info(f"Operator notifications disabled (tenant={tenant_id or 'global'})")
        return DisabledChannel()

    channel_name = op_cfg["channel"]

    if channel_name not in _CHANNELS:
        logger.error(f"Unknown notification channel: {channel_name}")
        return DisabledChannel()

    channel_class = _CHANNELS[channel_name]

    # Pass per-tenant config to channels that support it
    if channel_class is WhatsAppChannel:
        channel = channel_class(
            operator_whatsapp=op_cfg.get("operator_whatsapp"),
            provider=op_cfg.get("operator_whatsapp_provider", "twilio"),
            twilio_content_sid=op_cfg.get("twilio_content_sid"),
        )
    else:
        channel = channel_class()

    if not channel.is_configured():
        logger.warning(
            f"Notification channel '{channel_name}' not configured, notifications will fail"
        )

    return channel
