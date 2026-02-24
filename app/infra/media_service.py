# app/infra/media_service.py
"""
Media service for secure handling of uploaded/downloaded media files.

Responsibilities:
- Select the right fetcher for each provider (strategy pattern)
- Download media via provider API or generic HTTP (with automatic fallback)
- Validate and sanitize images
- Store processed images
- Generate secure filenames
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.domain import MediaItem
from app.infra.image_processor import (
    process_image,
    ProcessedImage,
    ImageConfig,
    ImageError,
)
from app.infra.media_fetchers.base import MediaFetchError, FetchResult
from app.infra.media_fetchers.http_fetcher import HttpMediaFetcher
from app.infra.media_fetchers.twilio_fetcher import TwilioMediaFetcher
from app.infra.media_fetchers.meta_fetcher import MetaMediaFetcher
from app.infra.media_fetchers.telegram_fetcher import TelegramMediaFetcher
from app.infra.logging_config import get_logger
from app.infra.pg_photo_repo_async import get_photo_repo

logger = get_logger(__name__)

# Content-type → file extension mapping for video
_VIDEO_EXT_MAP = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/3gpp": "3gp",
}


def _ext_from_content_type(ct: str) -> str:
    """Derive file extension from content-type, defaulting to 'bin'."""
    return _VIDEO_EXT_MAP.get(ct, "bin")


@dataclass
class MediaServiceConfig:
    """Configuration for media service"""
    storage_path: str = "/tmp/media"  # Where to store processed files
    max_file_size_mb: int = 10
    max_width: int = 4096
    max_height: int = 4096
    output_format: str = "JPEG"
    output_quality: int = 85


# Default configuration from environment
def get_default_config() -> MediaServiceConfig:
    return MediaServiceConfig(
        storage_path=os.getenv("MEDIA_STORAGE_PATH", "/tmp/media"),
        max_file_size_mb=int(os.getenv("MAX_MEDIA_SIZE_MB", "10")),
        max_width=int(os.getenv("MAX_MEDIA_WIDTH", "4096")),
        max_height=int(os.getenv("MAX_MEDIA_HEIGHT", "4096")),
    )


class MediaService:
    """
    Service for securely handling media files.

    All images are:
    1. Downloaded via provider-specific or generic HTTP fetcher
    2. Validated for format (magic bytes)
    3. Re-encoded to strip EXIF/metadata
    4. Resized if too large
    5. Saved with UUID filenames

    Fetcher strategy (controlled by config flags):
    - Twilio: TWILIO_MEDIA_FETCH_STRATEGY=provider_api → TwilioMediaFetcher
    - Meta:   META_MEDIA_FETCH_STRATEGY=provider_api   → MetaMediaFetcher
    - Default (any provider): HttpMediaFetcher (generic HTTP download)
    - Automatic fallback to HttpMediaFetcher on provider API failure
    """

    def __init__(self, config: MediaServiceConfig | None = None):
        self.config = config or get_default_config()
        self._image_config = ImageConfig(
            max_file_size_bytes=self.config.max_file_size_mb * 1024 * 1024,
            max_width=self.config.max_width,
            max_height=self.config.max_height,
            output_format=self.config.output_format,
            output_quality=self.config.output_quality,
        )

        # Ensure storage directory exists
        self._storage_path = Path(self.config.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _get_fetcher(provider: str):
        """
        Select primary and fallback fetchers based on provider and config.

        Returns:
            (primary_fetcher, fallback_fetcher_or_None)
        """
        from app.config import settings

        http_fetcher = HttpMediaFetcher()

        # Twilio provider API
        if provider in ("twilio", "whatsapp") and settings.twilio_media_fetch_strategy == "provider_api":
            if settings.twilio_account_sid and settings.twilio_auth_token:
                primary = TwilioMediaFetcher(
                    account_sid=settings.twilio_account_sid,
                    auth_token=settings.twilio_auth_token,
                )
                return primary, http_fetcher  # HTTP as fallback
            else:
                logger.warning(
                    "twilio_media_fetch_strategy=provider_api but credentials not configured, "
                    "falling back to HTTP"
                )

        # Meta provider API
        if provider == "meta" and settings.meta_media_fetch_strategy == "provider_api":
            if settings.meta_access_token:
                primary = MetaMediaFetcher(
                    access_token=settings.meta_access_token,
                    graph_api_version=settings.meta_graph_api_version,
                )
                return primary, http_fetcher  # HTTP as fallback
            else:
                logger.warning(
                    "meta_media_fetch_strategy=provider_api but credentials not configured, "
                    "falling back to HTTP"
                )

        # Telegram: always uses Bot API (file_id requires getFile resolution)
        if provider == "telegram":
            token = settings.telegram_channel_token
            if token:
                primary = TelegramMediaFetcher(bot_token=token)
                return primary, http_fetcher  # HTTP as fallback
            else:
                logger.warning(
                    "Telegram media fetch requested but no bot token configured, "
                    "falling back to HTTP"
                )

        return http_fetcher, None  # No fallback needed when HTTP is primary

    async def process_media_item(
        self,
        media: MediaItem,
        tenant_id: str,
        chat_id: str,
        provider: str = "twilio",
        message_id: str = "",
    ) -> Optional[ProcessedImage]:
        """
        Process a media item from an inbound message.

        Uses the fetcher strategy to download raw bytes, then processes
        the image through validation, re-encoding, and resizing.

        Args:
            media: MediaItem with URL and/or provider-specific IDs
            tenant_id: Tenant identifier
            chat_id: Chat identifier (for logging)
            provider: Channel provider ("twilio", "whatsapp", "meta", "dev")
            message_id: Provider message ID (e.g. Twilio MessageSid)

        Returns:
            ProcessedImage if successful, None if failed
        """
        # Only process images
        if media.content_type and not media.content_type.startswith("image/"):
            logger.info(f"Skipping non-image media: {media.content_type}")
            return None

        try:
            primary, fallback = self._get_fetcher(provider)

            # Try primary fetcher
            fetch_result: FetchResult | None = None
            try:
                fetch_result = await primary.fetch(media, message_id)
            except MediaFetchError as e:
                if fallback:
                    logger.warning(
                        f"Primary fetcher ({primary.__class__.__name__}) failed: {e}. "
                        f"Falling back to {fallback.__class__.__name__}"
                    )
                    fetch_result = await fallback.fetch(media, message_id)
                else:
                    raise

            # Process the raw bytes through image pipeline
            processed = process_image(fetch_result.data, self._image_config)

            logger.info(
                f"Media processed: tenant={tenant_id}, chat={chat_id[:6]}***, "
                f"uuid={processed.uuid}, size={processed.size_bytes}, "
                f"source={fetch_result.source}"
            )

            return processed

        except (ImageError, MediaFetchError) as e:
            logger.warning(
                f"Media processing failed: tenant={tenant_id}, chat={chat_id[:6]}***, "
                f"error={e}"
            )
            return None
        except Exception as e:
            logger.error(
                f"Unexpected error processing media: tenant={tenant_id}, "
                f"chat={chat_id[:6]}***, error={e}",
                exc_info=True,
            )
            return None

    async def save_processed_image(
        self,
        processed: ProcessedImage,
        tenant_id: str,
        chat_id: str | None = None,
    ) -> str:
        """
        Save a processed image to database.

        Args:
            processed: ProcessedImage to save
            tenant_id: Tenant identifier
            chat_id: Chat identifier

        Returns:
            Photo ID (UUID string)
        """
        repo = get_photo_repo()
        photo_id = await repo.save(
            tenant_id=tenant_id,
            chat_id=chat_id or "unknown",
            filename=processed.filename,
            content_type=processed.content_type,
            size_bytes=processed.size_bytes,
            width=processed.width,
            height=processed.height,
            data=processed.data,
        )
        logger.info(f"Image saved to DB: id={photo_id}, uuid={processed.uuid}")
        return str(photo_id)

    async def process_and_save(
        self,
        media: MediaItem,
        tenant_id: str,
        chat_id: str,
        provider: str = "twilio",
        message_id: str = "",
    ) -> Optional[dict]:
        """
        Process media and save to database.

        Args:
            media: MediaItem to process
            tenant_id: Tenant identifier
            chat_id: Chat identifier
            provider: Channel provider (for fetcher selection)
            message_id: Provider message ID (for API-based fetching)

        Returns dict with:
        - photo_id: Database photo ID (UUID)
        - uuid: Image UUID
        - filename: Saved filename
        - size_bytes: File size
        - width: Image width
        - height: Image height
        """
        processed = await self.process_media_item(
            media, tenant_id, chat_id, provider, message_id,
        )

        if processed is None:
            return None

        photo_id = await self.save_processed_image(processed, tenant_id, chat_id)

        return {
            "photo_id": photo_id,
            "uuid": processed.uuid,
            "filename": processed.filename,
            "size_bytes": processed.size_bytes,
            "width": processed.width,
            "height": processed.height,
            "content_type": processed.content_type,
        }

    async def process_video_item(
        self,
        media: MediaItem,
        tenant_id: str,
        chat_id: str,
        provider: str = "twilio",
        message_id: str = "",
        lead_id: str | None = None,
    ) -> Optional[dict]:
        """
        Download and store a video attachment (no re-encoding).

        Validates size and content-type, uploads raw bytes to S3,
        saves metadata to ``media_assets`` table.

        Returns dict with asset metadata, or None on failure.
        """
        from uuid import uuid4
        from datetime import datetime, timedelta, timezone
        from app.config import settings
        from app.infra.s3_storage import get_s3_storage, is_s3_available
        from app.infra.pg_media_asset_repo_async import get_media_asset_repo

        if not is_s3_available():
            logger.warning("S3 not available — cannot store video")
            return None

        # Validate content-type against allowlist
        allowed = {t.strip() for t in settings.media_allowed_video_types.split(",")}
        ct = media.content_type or ""
        if ct not in allowed:
            logger.warning("Video content-type not allowed: %s", ct)
            return None

        try:
            primary, fallback = self._get_fetcher(provider)

            fetch_result = None
            try:
                fetch_result = await primary.fetch(media, message_id)
            except MediaFetchError as e:
                if fallback:
                    logger.warning(
                        "Primary fetcher (%s) failed for video: %s. Falling back.",
                        primary.__class__.__name__, e,
                    )
                    fetch_result = await fallback.fetch(media, message_id)
                else:
                    raise

            data = fetch_result.data

            # Validate size
            max_bytes = settings.media_video_max_size_mb * 1024 * 1024
            if len(data) > max_bytes:
                logger.warning(
                    "Video too large: %d bytes (max %d)", len(data), max_bytes,
                )
                return None

            # Generate UUID filename
            asset_uuid = uuid4()
            ext = _ext_from_content_type(ct)
            filename = f"{asset_uuid}.{ext}"

            s3 = get_s3_storage()
            s3_key = s3.build_media_key(tenant_id, str(asset_uuid), ext, lead_id=lead_id)
            await s3.put_object(s3_key, data, ct)

            # Save metadata row
            repo = get_media_asset_repo()
            expires_at = datetime.now(timezone.utc) + timedelta(days=settings.media_ttl_days)

            asset_id = await repo.save(
                tenant_id=tenant_id,
                chat_id=chat_id,
                provider=provider,
                kind="video",
                content_type=ct,
                size_bytes=len(data),
                filename=filename,
                s3_key=s3_key,
                lead_id=lead_id,
                message_id=message_id,
                expires_at=expires_at,
            )

            logger.info(
                "Video stored: asset=%s, tenant=%s, size=%d",
                str(asset_id)[:8], tenant_id, len(data),
            )
            return {
                "asset_id": str(asset_id),
                "kind": "video",
                "filename": filename,
                "size_bytes": len(data),
                "content_type": ct,
                "s3_key": s3_key,
            }

        except (MediaFetchError,) as e:
            logger.warning(
                "Video processing failed: tenant=%s, chat=%s***, error=%s",
                tenant_id, chat_id[:6], e,
            )
            return None
        except Exception as e:
            logger.error(
                "Unexpected error processing video: tenant=%s, chat=%s***, error=%s",
                tenant_id, chat_id[:6], e,
                exc_info=True,
            )
            return None

    def process_upload(self, data: bytes) -> ProcessedImage:
        """
        Process an uploaded image (synchronous, for form uploads).

        Args:
            data: Raw image bytes

        Returns:
            ProcessedImage with sanitized data
        """
        return process_image(data, self._image_config)


# Global service instance
_media_service: MediaService | None = None


def get_media_service() -> MediaService:
    """Get the global media service instance"""
    global _media_service
    if _media_service is None:
        _media_service = MediaService()
    return _media_service
