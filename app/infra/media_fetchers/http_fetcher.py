# app/infra/media_fetchers/http_fetcher.py
"""
Generic HTTP media fetcher — universal fallback.

Wraps the existing download_media_from_url() logic from image_processor.py.
Handles redirects, provider auth injection, Content-Length validation,
and retries via the proven HTTP pipeline.
"""
from __future__ import annotations

from app.core.domain import MediaItem
from app.infra.media_fetchers.base import FetchResult, MediaFetchError
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


class HttpMediaFetcher:
    """
    Generic HTTP media fetcher.

    Downloads media via raw HTTP using the URL in MediaItem.url.
    This is the current (pre-Phase 2) behavior, preserved as a fallback
    for all providers.
    """

    async def fetch(self, media_item: MediaItem, message_id: str) -> FetchResult:
        from app.infra.image_processor import download_media_from_url

        if not media_item.url:
            raise MediaFetchError("MediaItem has no URL", retryable=False)

        try:
            data, content_type = await download_media_from_url(media_item.url)
            return FetchResult(
                data=data,
                content_type=content_type or media_item.content_type,
                source="http_direct",
            )
        except Exception as e:
            raise MediaFetchError(f"HTTP download failed: {e}") from e
