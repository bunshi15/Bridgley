# app/transport/adapters.py
"""
Adapters to convert provider-specific request formats into domain models.
These are pure converters - they don't contain domain logic.
"""
from __future__ import annotations
from typing import Protocol
from fastapi import Request

from app.core.domain import InboundMessage, MediaItem, LocationData
from app.infra.logging_config import get_logger, mask_coordinates

logger = get_logger(__name__)


def _mask_phone(phone: str) -> str:
    """Mask phone number for logging: +1234567890 -> +123***7890"""
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


def _extract_twilio_location(form) -> LocationData | None:
    """Extract GPS location from Twilio form data if present."""
    lat_str = form.get("Latitude")
    lon_str = form.get("Longitude")
    if lat_str and lon_str:
        try:
            return LocationData(
                latitude=float(lat_str),
                longitude=float(lon_str),
            )
        except (ValueError, TypeError):
            pass
    return None


class InboundAdapter(Protocol):
    """Protocol for adapters that convert provider-specific formats to InboundMessage"""

    async def adapt(self, request: Request, tenant_id: str) -> InboundMessage:
        """Convert request to normalized InboundMessage"""
        ...


class TwilioAdapter:
    """
    Adapter for Twilio SMS/MMS webhooks.

    Twilio sends:
    - From: sender phone number (e.g., "+12345678900")
    - Body: message text
    - MessageSid: unique message ID (e.g., "SM1234567890abcdef")
    - NumMedia: number of media attachments
    - MediaUrl0, MediaUrl1, ...: URLs to media files
    - MediaContentType0, MediaContentType1, ...: MIME types
    """

    async def adapt(self, request: Request, tenant_id: str) -> InboundMessage:
        form = await request.form()

        # Extract basic fields
        chat_id = form.get("From", "")
        message_id = form.get("MessageSid", "")
        text = form.get("Body") or None  # Convert empty string to None

        # Extract media attachments
        num_media = int(form.get("NumMedia", "0"))
        media: list[MediaItem] = []

        for i in range(num_media):
            media_url = form.get(f"MediaUrl{i}")
            media_type = form.get(f"MediaContentType{i}")

            if media_url:
                media.append(MediaItem(
                    url=media_url,
                    content_type=media_type,
                ))

        # Phase 5: extract GPS location (Twilio sends Latitude/Longitude fields)
        location = _extract_twilio_location(form)

        logger.info(
            f"Twilio message: from={_mask_phone(chat_id)}, sid={message_id}, "
            f"has_text={bool(text)}, num_media={len(media)}, has_location={location is not None}"
        )

        return InboundMessage(
            tenant_id=tenant_id,
            provider="twilio",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            media=media,
            location=location,
        )


class DevAdapter:
    """
    Adapter for development/testing endpoints.
    Accepts simple parameters and converts to InboundMessage.
    """

    def adapt(
            self,
            tenant_id: str,
            chat_id: str,
            text: str | None = None,
            message_id: str | None = None,
            media_url: str | None = None,
    ) -> InboundMessage:
        """
        Create InboundMessage from development endpoint parameters.
        """
        import uuid

        # Generate message_id if not provided
        if not message_id:
            message_id = f"dev_{uuid.uuid4().hex[:16]}"

        # Convert single media URL to MediaItem list
        media: list[MediaItem] = []
        if media_url:
            media.append(MediaItem(url=media_url, content_type="image/jpeg"))

        logger.info(
            f"Dev message: chat={chat_id[:6]}***, "
            f"has_text={bool(text)}, has_media={bool(media)}"
        )

        return InboundMessage(
            tenant_id=tenant_id,
            provider="dev",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            media=media,
        )


class WhatsAppAdapter:
    """
    Adapter for WhatsApp Business API webhooks (via Twilio).

    Twilio WhatsApp uses similar format to SMS but with "whatsapp:" prefix.
    """

    async def adapt(self, request: Request, tenant_id: str) -> InboundMessage:
        form = await request.form()

        chat_id = form.get("From", "")
        # Remove "whatsapp:" prefix if present
        if chat_id.startswith("whatsapp:"):
            chat_id = chat_id[9:]

        message_id = form.get("MessageSid", "")
        text = form.get("Body") or None

        # WhatsApp media handling similar to Twilio
        num_media = int(form.get("NumMedia", "0"))
        media: list[MediaItem] = []

        for i in range(num_media):
            media_url = form.get(f"MediaUrl{i}")
            media_type = form.get(f"MediaContentType{i}")

            if media_url:
                media.append(MediaItem(
                    url=media_url,
                    content_type=media_type,
                ))

        # Phase 5: extract GPS location (same Twilio form fields)
        location = _extract_twilio_location(form)

        logger.info(
            f"WhatsApp message: from={_mask_phone(chat_id)}, sid={message_id}, "
            f"has_text={bool(text)}, num_media={len(media)}, has_location={location is not None}"
        )

        return InboundMessage(
            tenant_id=tenant_id,
            provider="whatsapp",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            media=media,
            location=location,
        )


class MetaCloudAdapter:
    """
    Adapter for Meta WhatsApp Cloud API webhooks.

    Meta sends JSON payloads with structure:
    {
      "object": "whatsapp_business_account",
      "entry": [{
        "id": "<WABA_ID>",
        "changes": [{
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "...", "phone_number_id": "..."},
            "contacts": [{"profile": {"name": "..."}, "wa_id": "..."}],
            "messages": [{
              "from": "...",
              "id": "wamid.xxx",
              "timestamp": "...",
              "type": "text",
              "text": {"body": "Hello"}
            }]
          },
          "field": "messages"
        }]
      }]
    }
    """

    def adapt_payload(self, payload: dict, tenant_id: str) -> list[InboundMessage]:
        """
        Convert Meta webhook payload to list of InboundMessages.
        A single webhook POST can contain multiple messages.
        Returns empty list for non-message events (status updates, etc.).
        """
        messages: list[InboundMessage] = []

        if payload.get("object") != "whatsapp_business_account":
            logger.debug(f"Meta webhook: ignoring non-whatsapp object: {payload.get('object')}")
            return messages

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                field_name = change.get("field")

                if field_name != "messages":
                    logger.debug(f"Meta webhook: ignoring field={field_name}")
                    continue

                # Process status updates (delivery/read receipts) - log and skip
                for status in value.get("statuses", []):
                    logger.debug(
                        f"Meta status update: id={status.get('id', '')[:20]}, "
                        f"status={status.get('status')}"
                    )

                # Process actual messages
                for msg in value.get("messages", []):
                    inbound = self._parse_message(msg, tenant_id)
                    if inbound:
                        messages.append(inbound)

        return messages

    def _parse_message(self, msg: dict, tenant_id: str) -> InboundMessage | None:
        """Parse a single message from Meta payload."""
        msg_type = msg.get("type")
        from_number = msg.get("from", "")
        message_id = msg.get("id", "")

        text = None
        media: list[MediaItem] = []

        if msg_type == "text":
            text = msg.get("text", {}).get("body")
        elif msg_type == "image":
            image = msg.get("image", {})
            media.append(MediaItem(
                provider_media_id=image.get("id"),
                content_type=image.get("mime_type", "image/jpeg"),
            ))
            text = image.get("caption")
        elif msg_type == "document":
            doc = msg.get("document", {})
            media.append(MediaItem(
                provider_media_id=doc.get("id"),
                content_type=doc.get("mime_type"),
            ))
            text = doc.get("caption")
        elif msg_type == "audio":
            audio = msg.get("audio", {})
            media.append(MediaItem(
                provider_media_id=audio.get("id"),
                content_type=audio.get("mime_type"),
            ))
        elif msg_type == "video":
            video = msg.get("video", {})
            media.append(MediaItem(
                provider_media_id=video.get("id"),
                content_type=video.get("mime_type"),
            ))
            text = video.get("caption")
        elif msg_type == "location":
            loc = msg.get("location", {})
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            if lat is not None and lon is not None:
                location = LocationData(
                    latitude=float(lat),
                    longitude=float(lon),
                    name=loc.get("name"),
                    address=loc.get("address"),
                )
                logger.info(
                    f"Meta message: from={_mask_phone(from_number)}, id={message_id[:20]}, "
                    f"type=location, coords={mask_coordinates(float(lat), float(lon))}"
                )
                return InboundMessage(
                    tenant_id=tenant_id,
                    provider="meta",
                    chat_id=from_number,
                    message_id=message_id,
                    location=location,
                )
            logger.debug(f"Meta message: location without coordinates, ignoring")
            return None
        elif msg_type in ("reaction", "sticker", "contacts"):
            logger.debug(f"Meta message: unsupported type={msg_type}, ignoring")
            return None
        else:
            logger.warning(f"Meta message: unknown type={msg_type}, ignoring")
            return None

        logger.info(
            f"Meta message: from={_mask_phone(from_number)}, id={message_id[:20]}, "
            f"type={msg_type}, has_text={bool(text)}, num_media={len(media)}"
        )

        return InboundMessage(
            tenant_id=tenant_id,
            provider="meta",
            chat_id=from_number,
            message_id=message_id,
            text=text,
            media=media,
        )


class TelegramAdapter:
    """
    Adapter for Telegram Bot API messages.

    Telegram sends JSON Updates with structure:
    {
      "update_id": 123456,
      "message": {
        "message_id": 42,
        "from": {"id": 123, "first_name": "User", ...},
        "chat": {"id": 123, "type": "private", ...},
        "date": 1234567890,
        "text": "Hello",
        "photo": [{"file_id": "...", "width": ..., "height": ..., "file_size": ...}, ...],
        "document": {"file_id": "...", "mime_type": "...", ...},
        ...
      }
    }
    """

    async def adapt(self, request: Request, tenant_id: str) -> list[InboundMessage]:
        """
        Convert Telegram webhook Update to list of InboundMessages.
        Returns empty list for non-message updates.
        """
        payload = await request.json()
        return self._parse_update(payload, tenant_id)

    def adapt_update(self, update: dict, tenant_id: str) -> list[InboundMessage]:
        """
        Convert a Telegram Update dict to list of InboundMessages.
        Used by the polling handler (no Request object).
        """
        return self._parse_update(update, tenant_id)

    def _parse_update(self, update: dict, tenant_id: str) -> list[InboundMessage]:
        """Parse a single Telegram Update into InboundMessages."""
        # Only handle regular messages (not edited, channel posts, etc.)
        message = update.get("message")
        if not message:
            logger.debug(f"Telegram update: no 'message' field, ignoring (keys={list(update.keys())})")
            return []

        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        message_id = str(message.get("message_id", ""))

        if not chat_id:
            logger.warning("Telegram message: missing chat.id, ignoring")
            return []

        # Extract sender info for contact identification
        # (Telegram chat_id is numeric, not a phone — we need name/username for operator)
        sender_name = self._extract_sender_name(message)

        # Extract text
        text = message.get("text")

        # Handle bot commands: strip bot mention suffix (e.g. "/start@MyBot" → "/start")
        if text and text.startswith("/"):
            parts = text.split()
            cmd = parts[0].split("@")[0]  # "/start@BotName" → "/start"
            parts[0] = cmd
            text = " ".join(parts)

        # Extract caption (for media with text)
        caption = message.get("caption")

        # Extract media
        media: list[MediaItem] = []

        if "photo" in message:
            # Telegram sends multiple sizes; pick the largest (last in array)
            photos = message["photo"]
            if photos:
                largest = photos[-1]
                media.append(MediaItem(
                    provider_media_id=largest.get("file_id"),
                    content_type="image/jpeg",
                    size_bytes=largest.get("file_size"),
                ))

        if "document" in message:
            doc = message["document"]
            media.append(MediaItem(
                provider_media_id=doc.get("file_id"),
                content_type=doc.get("mime_type"),
                size_bytes=doc.get("file_size"),
            ))

        if "audio" in message:
            audio = message["audio"]
            media.append(MediaItem(
                provider_media_id=audio.get("file_id"),
                content_type=audio.get("mime_type", "audio/mpeg"),
                size_bytes=audio.get("file_size"),
            ))

        if "voice" in message:
            voice = message["voice"]
            media.append(MediaItem(
                provider_media_id=voice.get("file_id"),
                content_type=voice.get("mime_type", "audio/ogg"),
                size_bytes=voice.get("file_size"),
            ))

        if "video" in message:
            video = message["video"]
            media.append(MediaItem(
                provider_media_id=video.get("file_id"),
                content_type=video.get("mime_type", "video/mp4"),
                size_bytes=video.get("file_size"),
            ))

        # Phase 5: extract GPS location
        location: LocationData | None = None
        if "location" in message:
            loc = message["location"]
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            if lat is not None and lon is not None:
                location = LocationData(
                    latitude=float(lat),
                    longitude=float(lon),
                )

        # Use caption as text if no text but has caption (photo/video with caption)
        if not text and caption:
            text = caption

        # Skip if no content at all
        if not text and not media and not location:
            logger.debug(f"Telegram message: no text or media, ignoring (type keys: {list(message.keys())})")
            return []

        logger.info(
            f"Telegram message: from={_mask_phone(chat_id)}, msg_id={message_id}, "
            f"has_text={bool(text)}, num_media={len(media)}, has_location={location is not None}"
        )

        return [InboundMessage(
            tenant_id=tenant_id,
            provider="telegram",
            chat_id=chat_id,
            message_id=f"tg_{chat_id}_{message_id}",  # Ensure uniqueness across chats
            text=text,
            media=media,
            sender_name=sender_name,
            location=location,
        )]

    @staticmethod
    def _extract_sender_name(message: dict) -> str | None:
        """
        Build a human-readable sender identifier from Telegram message.from.

        Telegram provides:
          - from.first_name (always present)
          - from.last_name (optional)
          - from.username (optional)

        We build a contact string that the operator can use to reach the user.
        Prefer "@username" (clickable in Telegram), fallback to full name.
        """
        sender = message.get("from", {})
        if not sender:
            return None

        parts: list[str] = []

        # Full name
        first_name = sender.get("first_name", "")
        last_name = sender.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()

        # Username (clickable in Telegram: @username)
        username = sender.get("username")

        if username and full_name:
            parts.append(f"{full_name} (@{username})")
        elif username:
            parts.append(f"@{username}")
        elif full_name:
            parts.append(full_name)

        return parts[0] if parts else None


def get_adapter(provider: str) -> InboundAdapter:
    """Get the appropriate adapter for a provider"""
    adapters = {
        "twilio": TwilioAdapter(),
        "whatsapp": WhatsAppAdapter(),
        "meta": MetaCloudAdapter(),
        "telegram": TelegramAdapter(),
    }

    adapter = adapters.get(provider)
    if not adapter:
        raise ValueError(f"Unknown provider: {provider}")

    return adapter
