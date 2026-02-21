# app/transport/meta_sender.py
"""
Meta WhatsApp Cloud API outbound sender.

Uses the Graph API to:
- Send text messages
- Send media messages (by URL)
- Resolve media IDs to download URLs (for inbound media processing)

Error classification (MetaSendError.retryable):
- Token expired/invalid  → NOT retryable (needs human intervention)
- Template required       → NOT retryable (outside 24h window)
- Invalid recipient       → NOT retryable (number not on WhatsApp)
- Rate limiting (429)     → retryable  (backoff then retry)
- Network / timeout       → retryable  (transient)
- Unknown server error    → retryable  (optimistic)

HTTP session lifecycle:
- Uses the shared sender session from app.infra.http_client.
- Call close_all_sessions() during application shutdown.
"""
from __future__ import annotations

import aiohttp

from app.config import settings
from app.infra.http_client import get_sender_session
from app.infra.logging_config import get_logger
from app.infra.metrics import inc_counter

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _graph_url(path: str, *, graph_api_version: str | None = None) -> str:
    """Build Graph API URL."""
    version = graph_api_version or settings.meta_graph_api_version
    return f"https://graph.facebook.com/{version}/{path}"


def _auth_headers(*, access_token: str | None = None) -> dict[str, str]:
    """Common auth headers for Graph API."""
    token = access_token or settings.meta_access_token
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class MetaSendError(Exception):
    """Error sending message via Meta Graph API.

    Attributes:
        status:     HTTP status code (0 for connection-level errors).
        error_code: Meta-specific error code from the response body.
        retryable:  Whether the caller should schedule a retry.
                    False for auth failures, template-required, invalid
                    recipient — retrying would be futile.
                    True for rate limits and transient network errors.
    """

    def __init__(
        self,
        status: int,
        error_code: int | None,
        message: str,
        *,
        retryable: bool = False,
    ):
        self.status = status
        self.error_code = error_code
        self.retryable = retryable
        super().__init__(f"Meta API error {status} (code={error_code}): {message}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def send_text_message(
    to: str,
    text: str,
    *,
    access_token: str | None = None,
    phone_number_id: str | None = None,
    graph_api_version: str | None = None,
) -> dict:
    """
    Send a text message via Meta Graph API.

    Args:
        to: Recipient phone number (international format without +, e.g. "1234567890")
        text: Message text body
        access_token: Override access token (for multi-tenant; defaults to settings)
        phone_number_id: Override phone number ID (for multi-tenant; defaults to settings)
        graph_api_version: Override Graph API version (defaults to settings)

    Returns:
        Meta API response dict with message ID

    Raises:
        MetaSendError: On API errors (check .retryable before scheduling retry)
    """
    pid = phone_number_id or settings.meta_phone_number_id
    url = _graph_url(f"{pid}/messages", graph_api_version=graph_api_version)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    return await _send_request(url, payload, to, access_token=access_token)


async def send_media_message(
    to: str,
    media_type: str,
    media_url: str,
    caption: str | None = None,
    *,
    access_token: str | None = None,
    phone_number_id: str | None = None,
    graph_api_version: str | None = None,
) -> dict:
    """
    Send a media message via Meta Graph API.

    Args:
        to: Recipient phone number
        media_type: "image", "document", "audio", "video"
        media_url: Public URL of the media file
        caption: Optional caption text
        access_token: Override access token (for multi-tenant; defaults to settings)
        phone_number_id: Override phone number ID (for multi-tenant; defaults to settings)
        graph_api_version: Override Graph API version (defaults to settings)

    Returns:
        Meta API response dict
    """
    pid = phone_number_id or settings.meta_phone_number_id
    url = _graph_url(f"{pid}/messages", graph_api_version=graph_api_version)

    media_object: dict = {"link": media_url}
    if caption and media_type in ("image", "video", "document"):
        media_object["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": media_type,
        media_type: media_object,
    }

    return await _send_request(url, payload, to, access_token=access_token)


async def get_media_url(
    media_id: str,
    *,
    access_token: str | None = None,
    graph_api_version: str | None = None,
) -> str | None:
    """
    Resolve a Meta media ID to a download URL.

    Used for processing inbound media: Meta sends media IDs in webhooks,
    which must be resolved to temporary download URLs via Graph API.

    Args:
        media_id: Meta media ID from inbound webhook
        access_token: Override access token (for multi-tenant; defaults to settings)
        graph_api_version: Override Graph API version (defaults to settings)

    Returns:
        Download URL string, or None on failure
    """
    url = _graph_url(media_id, graph_api_version=graph_api_version)
    token = access_token or settings.meta_access_token

    try:
        session = get_sender_session()
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.error(f"Meta media URL fetch failed: status={resp.status}")
                return None

            data = await _safe_response_json(resp)
            if data is None:
                return None
            return data.get("url")

    except Exception as exc:
        logger.error(f"Meta media URL fetch error: {type(exc).__name__}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

async def _safe_response_json(resp: aiohttp.ClientResponse) -> dict | None:
    """Parse JSON from response, returning None if body is not valid JSON."""
    try:
        return await resp.json()
    except Exception:
        logger.warning(f"Meta API returned non-JSON body: status={resp.status}")
        return None


async def _safe_response_text(resp: aiohttp.ClientResponse, max_len: int = 300) -> str:
    """Read response body as text, truncated for safe logging."""
    try:
        text = await resp.text()
        return text[:max_len]
    except Exception:
        return "<unreadable>"


async def _send_request(
    url: str,
    payload: dict,
    to: str,
    *,
    access_token: str | None = None,
) -> dict:
    """
    Execute a Graph API send request with error handling.

    Classifies every error as retryable or not, then raises MetaSendError
    so the caller can make an informed retry decision.
    """
    try:
        session = get_sender_session()
        async with session.post(
            url,
            json=payload,
            headers=_auth_headers(access_token=access_token),
        ) as resp:
            body = await _safe_response_json(resp)

            if resp.status in (200, 201) and body is not None:
                msg_id = body.get("messages", [{}])[0].get("id", "unknown")
                logger.info(
                    f"Meta message sent: to={to[:6]}***, msg_id={msg_id[:20]}"
                )
                inc_counter("meta_outbound_sent")
                return body

            # --- Error path ------------------------------------------------

            error = (body or {}).get("error", {})
            error_code = error.get("code")
            error_msg = error.get("message", "Unknown error")
            error_subcode = error.get("error_subcode")

            # -- Auth failure: token expired / invalid (DO NOT retry) --------
            if resp.status == 401 or error_code == 190:
                logger.error(
                    f"Meta API auth error: status={resp.status}, code={error_code}",
                    extra={"error_code": error_code},
                )
                inc_counter("meta_outbound_auth_error")
                raise MetaSendError(
                    resp.status, error_code, error_msg, retryable=False,
                )

            # -- Rate limit: retry with backoff ------------------------------
            if resp.status == 429 or error_code in (4, 80007):
                logger.warning(
                    f"Meta API rate limit: status={resp.status}, code={error_code}",
                    extra={"error_code": error_code},
                )
                inc_counter("meta_outbound_rate_limited")
                raise MetaSendError(
                    resp.status, error_code, error_msg, retryable=True,
                )

            # -- Template required: outside 24h window (DO NOT retry) --------
            if error_subcode == 2388049:
                logger.warning(
                    f"Meta API: template required (outside 24h window): to={to[:6]}***",
                    extra={"error_code": error_code, "error_subcode": error_subcode},
                )
                inc_counter("meta_outbound_template_required")
                raise MetaSendError(
                    resp.status, error_code, error_msg, retryable=False,
                )

            # -- Invalid recipient: not on WhatsApp (DO NOT retry) -----------
            if error_code == 131026:
                logger.warning(
                    f"Meta API: recipient not on WhatsApp: to={to[:6]}***",
                    extra={"error_code": error_code},
                )
                inc_counter("meta_outbound_invalid_recipient")
                raise MetaSendError(
                    resp.status, error_code, error_msg, retryable=False,
                )

            # -- Anything else: optimistic retry ----------------------------
            logger.error(
                f"Meta API error: status={resp.status}, code={error_code}, "
                f"subcode={error_subcode}",
                extra={
                    "error_code": error_code,
                    "error_subcode": error_subcode,
                },
            )
            inc_counter("meta_outbound_error")
            raise MetaSendError(
                resp.status, error_code, error_msg, retryable=True,
            )

    except MetaSendError:
        raise
    except aiohttp.ClientError as exc:
        logger.error(f"Meta API connection error: {type(exc).__name__}", exc_info=True)
        inc_counter("meta_outbound_connection_error")
        raise MetaSendError(0, None, type(exc).__name__, retryable=True)
    except Exception as exc:
        logger.error(f"Meta API unexpected error: {type(exc).__name__}", exc_info=True)
        inc_counter("meta_outbound_unexpected_error")
        raise MetaSendError(0, None, type(exc).__name__, retryable=True)
