# app/infra/media_fetchers/meta_fetcher.py
"""
Meta WhatsApp Cloud API media fetcher.

Downloads media via the Graph API two-step flow:
1. Resolve media ID → temporary download URL
2. Download binary with Bearer token

This replaces the split logic that was previously spread across
meta_webhook.py (URL resolution) and image_processor.py (download).

Graph API endpoint:
    GET /vXX.X/{media-id}  →  { "url": "https://..." }
    GET {url}              →  binary data
"""
from __future__ import annotations

import asyncio

import aiohttp

from app.core.domain import MediaItem
from app.infra.http_client import get_fetcher_session
from app.infra.media_fetchers.base import FetchResult, MediaFetchError
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


class MetaMediaFetcher:
    """
    Fetches media via the Meta Graph API.

    Requires:
    - access_token for Bearer Auth
    - graph_api_version (e.g. "v20.0")
    - media_item.provider_media_id (Meta media ID from webhook)

    Two-step process:
    1. Resolve provider_media_id → temporary download URL
    2. Download binary with same Bearer token
    """

    def __init__(self, access_token: str, graph_api_version: str = "v20.0"):
        self._access_token = access_token
        self._api_version = graph_api_version
        self._base_url = f"https://graph.facebook.com/{graph_api_version}"

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _resolve_media_url(self, media_id: str) -> str:
        """Resolve Meta media ID to temporary download URL via Graph API."""
        url = f"{self._base_url}/{media_id}"
        session = get_fetcher_session()

        async with session.get(
            url,
            headers=self._auth_headers(),
            timeout=aiohttp.ClientTimeout(total=10, connect=5),
        ) as resp:
            if resp.status != 200:
                raise MediaFetchError(
                    f"Meta Graph API returned {resp.status} resolving media ID "
                    f"{media_id[:20]}",
                    retryable=resp.status >= 500 or resp.status == 429,
                )

            data = await resp.json()
            download_url = data.get("url")

            if not download_url:
                raise MediaFetchError(
                    f"Meta Graph API response missing 'url' for media ID {media_id[:20]}",
                    retryable=False,
                )

            return download_url

    async def _download_binary(self, download_url: str) -> tuple[bytes, str | None]:
        """Download binary media from the temporary URL."""
        session = get_fetcher_session()

        async with session.get(
            download_url,
            headers=self._auth_headers(),
        ) as resp:
            if resp.status != 200:
                raise MediaFetchError(
                    f"Meta media download returned {resp.status}",
                    retryable=resp.status >= 500 or resp.status == 429,
                )

            data = await resp.read()
            content_type = resp.headers.get("Content-Type")

            if not data:
                raise MediaFetchError("Meta media download returned empty body")

            # Validate Content-Length if present
            cl_header = resp.headers.get("Content-Length")
            if cl_header and len(data) < int(cl_header):
                raise MediaFetchError(
                    f"Incomplete download: got {len(data)} of {cl_header} bytes"
                )

            return data, content_type

    async def fetch(
        self,
        media_item: MediaItem,
        message_id: str,
    ) -> FetchResult:
        """
        Fetch media via Meta Graph API (resolve ID → download binary).
        """
        media_id = media_item.provider_media_id

        if not media_id:
            raise MediaFetchError(
                "MediaItem has no provider_media_id for Meta API fetch",
                retryable=False,
            )

        logger.info(f"Fetching media via Meta Graph API: media_id={media_id[:20]}")

        max_retries = 3
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                # Step 1: Resolve media ID → temporary download URL
                download_url = await self._resolve_media_url(media_id)

                logger.debug("Meta media URL resolved (download ready)")

                # Step 2: Download binary
                data, content_type = await self._download_binary(download_url)

                logger.info(
                    f"Meta API media fetched: {len(data)} bytes, "
                    f"content_type={content_type}"
                )

                return FetchResult(
                    data=data,
                    content_type=content_type or media_item.content_type,
                    source="meta_api",
                )

            except MediaFetchError as e:
                if not e.retryable or attempt == max_retries - 1:
                    raise
                last_error = e
            except aiohttp.ClientError as e:
                last_error = e
                if attempt == max_retries - 1:
                    raise MediaFetchError(
                        f"Meta API fetch failed after {max_retries} attempts: {e}"
                    ) from e

            # Exponential backoff
            wait = (attempt + 1) * 2
            logger.warning(
                f"Meta API fetch failed (attempt {attempt + 1}/{max_retries}), "
                f"retrying in {wait}s: {last_error}"
            )
            await asyncio.sleep(wait)

        raise MediaFetchError(
            f"Meta API fetch failed after {max_retries} attempts: {last_error}"
        )
