# app/infra/media_fetchers/twilio_fetcher.py
"""
Twilio REST API media fetcher.

Downloads media via the Twilio Media resource endpoint instead of raw MediaUrl.
This eliminates unpredictable CDN redirects and partial downloads.

API endpoint:
    GET /2010-04-01/Accounts/{AccountSid}/Messages/{MessageSid}/Media/{MediaSid}

Benefits over raw MediaUrl:
- No cross-origin redirect issues
- Consistent authentication (Basic Auth)
- Proper API contract with predictable behavior
- No CDN partial responses
"""
from __future__ import annotations

import asyncio
import base64
import re

import aiohttp

from app.core.domain import MediaItem
from app.infra.http_client import get_fetcher_session
from app.infra.media_fetchers.base import FetchResult, MediaFetchError
from app.infra.logging_config import get_logger

logger = get_logger(__name__)

# Pattern to extract MediaSid from Twilio MediaUrl path.
# Format: https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages/{msgSid}/Media/{mediaSid}
_MEDIA_URL_PATTERN = re.compile(
    r"/Accounts/[^/]+/Messages/[^/]+/Media/([^/?\s]+)"
)


def extract_media_sid(media_url: str) -> str | None:
    """Extract MediaSid from a Twilio MediaUrl."""
    match = _MEDIA_URL_PATTERN.search(media_url)
    return match.group(1) if match else None


class TwilioMediaFetcher:
    """
    Fetches media via the Twilio REST API.

    Requires:
    - account_sid and auth_token for Basic Auth
    - MediaSid (parsed from MediaItem.url)
    - MessageSid (passed as message_id)
    """

    def __init__(self, account_sid: str, auth_token: str):
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._base_url = "https://api.twilio.com/2010-04-01"

    def _auth_header(self) -> str:
        """Build Basic Auth header value."""
        credentials = f"{self._account_sid}:{self._auth_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return f"Basic {encoded}"

    async def fetch(
        self,
        media_item: MediaItem,
        message_id: str,
    ) -> FetchResult:
        """
        Fetch media via Twilio REST API.

        Constructs the API URL from AccountSid + MessageSid + MediaSid,
        then downloads with Basic Auth.
        """
        # Extract MediaSid from the webhook-provided URL
        media_sid = extract_media_sid(media_item.url) if media_item.url else None

        if not media_sid:
            raise MediaFetchError(
                f"Cannot extract MediaSid from URL: {media_item.url}",
                retryable=False,
            )

        if not message_id:
            raise MediaFetchError(
                "MessageSid (message_id) is required for Twilio API fetch",
                retryable=False,
            )

        api_url = (
            f"{self._base_url}/Accounts/{self._account_sid}"
            f"/Messages/{message_id}/Media/{media_sid}"
        )

        logger.info(
            f"Fetching media via Twilio API: message_sid={message_id}, "
            f"media_sid={media_sid}"
        )

        headers = {"Authorization": self._auth_header()}

        max_retries = 3
        last_error: Exception | None = None
        session = get_fetcher_session()

        for attempt in range(max_retries):
            try:
                async with session.get(
                    api_url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60, connect=15),
                    allow_redirects=True,  # Follow Twilio 301 → CDN
                ) as response:
                    if response.status != 200:
                        raise MediaFetchError(
                            f"Twilio API returned {response.status}",
                            retryable=response.status >= 500 or response.status == 429,
                        )

                    data = await response.read()
                    content_type = response.headers.get("Content-Type")

                    if not data:
                        raise MediaFetchError("Twilio API returned empty body")

                    # Validate Content-Length if present
                    cl_header = response.headers.get("Content-Length")
                    if cl_header and len(data) < int(cl_header):
                        raise MediaFetchError(
                            f"Incomplete download: got {len(data)} of {cl_header} bytes"
                        )

                    logger.info(
                        f"Twilio API media fetched: {len(data)} bytes, "
                        f"content_type={content_type}"
                    )

                    return FetchResult(
                        data=data,
                        content_type=content_type or media_item.content_type,
                        source="twilio_api",
                    )

            except MediaFetchError as e:
                if not e.retryable or attempt == max_retries - 1:
                    raise
                last_error = e
            except aiohttp.ClientError as e:
                last_error = e
                if attempt == max_retries - 1:
                    raise MediaFetchError(
                        f"Twilio API fetch failed after {max_retries} attempts: {e}"
                    ) from e

            # Exponential backoff
            wait = (attempt + 1) * 2
            logger.warning(
                f"Twilio API fetch failed (attempt {attempt + 1}/{max_retries}), "
                f"retrying in {wait}s: {last_error}"
            )
            await asyncio.sleep(wait)

        raise MediaFetchError(
            f"Twilio API fetch failed after {max_retries} attempts: {last_error}"
        )
