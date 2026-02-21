# app/infra/media_fetchers/telegram_fetcher.py
"""
Telegram Bot API media fetcher.

Downloads media via the Bot API two-step flow:
1. getFile(file_id) → file_path
2. Download binary from https://api.telegram.org/file/bot{token}/{file_path}

Note: Telegram Bot API has a 20 MB file size limit for downloads.
"""
from __future__ import annotations

import asyncio

import aiohttp

from app.core.domain import MediaItem
from app.infra.http_client import get_fetcher_session
from app.infra.media_fetchers.base import FetchResult, MediaFetchError
from app.infra.logging_config import get_logger

logger = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramMediaFetcher:
    """
    Fetches media via the Telegram Bot API.

    Requires:
    - bot_token for authentication
    - media_item.provider_media_id (Telegram file_id from message)

    Two-step process:
    1. getFile(file_id) → file info with file_path
    2. Download binary from file URL
    """

    def __init__(self, bot_token: str):
        self._bot_token = bot_token

    def _api_url(self, method: str) -> str:
        return f"{TELEGRAM_API_BASE}/bot{self._bot_token}/{method}"

    def _file_url(self, file_path: str) -> str:
        return f"{TELEGRAM_API_BASE}/file/bot{self._bot_token}/{file_path}"

    async def _get_file_path(self, file_id: str) -> str:
        """Resolve Telegram file_id to file_path via getFile API."""
        url = self._api_url("getFile")
        payload = {"file_id": file_id}
        session = get_fetcher_session()

        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10, connect=5),
        ) as resp:
            if resp.status != 200:
                raise MediaFetchError(
                    f"Telegram getFile returned {resp.status} for file_id "
                    f"{file_id[:20]}",
                    retryable=resp.status >= 500 or resp.status == 429,
                )

            data = await resp.json()
            if not data.get("ok"):
                raise MediaFetchError(
                    f"Telegram getFile failed: {data.get('description', 'unknown error')}",
                    retryable=False,
                )

            result = data.get("result", {})
            file_path = result.get("file_path")

            if not file_path:
                raise MediaFetchError(
                    f"Telegram getFile response missing 'file_path' for file_id {file_id[:20]}",
                    retryable=False,
                )

            return file_path

    async def _download_binary(self, file_path: str) -> tuple[bytes, str | None]:
        """Download binary media from the Telegram file URL."""
        download_url = self._file_url(file_path)
        session = get_fetcher_session()

        async with session.get(download_url) as resp:
            if resp.status != 200:
                raise MediaFetchError(
                    f"Telegram file download returned {resp.status}",
                    retryable=resp.status >= 500 or resp.status == 429,
                )

            data = await resp.read()
            content_type = resp.headers.get("Content-Type")

            if not data:
                raise MediaFetchError("Telegram file download returned empty body")

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
        Fetch media via Telegram Bot API (getFile → download binary).
        """
        file_id = media_item.provider_media_id

        if not file_id:
            raise MediaFetchError(
                "MediaItem has no provider_media_id for Telegram API fetch",
                retryable=False,
            )

        logger.info(f"Fetching media via Telegram Bot API: file_id={file_id[:20]}")

        max_retries = 3
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                # Step 1: Resolve file_id → file_path
                file_path = await self._get_file_path(file_id)

                logger.debug("Telegram file path resolved (download ready)")

                # Step 2: Download binary
                data, content_type = await self._download_binary(file_path)

                logger.info(
                    f"Telegram API media fetched: {len(data)} bytes, "
                    f"content_type={content_type}"
                )

                return FetchResult(
                    data=data,
                    content_type=content_type or media_item.content_type,
                    source="telegram_api",
                )

            except MediaFetchError as e:
                if not e.retryable or attempt == max_retries - 1:
                    raise
                last_error = e
            except aiohttp.ClientError as e:
                last_error = e
                if attempt == max_retries - 1:
                    raise MediaFetchError(
                        f"Telegram API fetch failed after {max_retries} attempts: {e}"
                    ) from e

            # Exponential backoff
            wait = (attempt + 1) * 2
            logger.warning(
                f"Telegram API fetch failed (attempt {attempt + 1}/{max_retries}), "
                f"retrying in {wait}s: {last_error}"
            )
            await asyncio.sleep(wait)

        raise MediaFetchError(
            f"Telegram API fetch failed after {max_retries} attempts: {last_error}"
        )
