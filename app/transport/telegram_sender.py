# app/transport/telegram_sender.py
"""
Telegram Bot API outbound sender.

Uses the Bot API to:
- Send text messages
- Resolve file_id to download URLs (for inbound media processing)

Error classification (TelegramSendError.retryable):
- Token invalid / bot blocked  → NOT retryable (needs human intervention)
- Chat not found               → NOT retryable
- Rate limiting (429)          → retryable  (backoff then retry)
- Network / timeout            → retryable  (transient)
- Unknown server error         → retryable  (optimistic)

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

TELEGRAM_API_BASE = "https://api.telegram.org"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot_url(method: str, token: str | None = None) -> str:
    """Build Telegram Bot API URL."""
    bot_token = token or settings.telegram_channel_token
    return f"{TELEGRAM_API_BASE}/bot{bot_token}/{method}"


def _file_download_url(file_path: str, token: str | None = None) -> str:
    """Build Telegram file download URL."""
    bot_token = token or settings.telegram_channel_token
    return f"{TELEGRAM_API_BASE}/file/bot{bot_token}/{file_path}"


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class TelegramSendError(Exception):
    """Error sending message via Telegram Bot API.

    Attributes:
        status:     HTTP status code (0 for connection-level errors).
        error_code: Telegram-specific error code from the response body.
        retryable:  Whether the caller should schedule a retry.
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
        super().__init__(f"Telegram API error {status} (code={error_code}): {message}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def send_text_message(
    chat_id: str,
    text: str,
    token: str | None = None,
) -> dict:
    """
    Send a text message via Telegram Bot API.

    Args:
        chat_id: Telegram chat ID (numeric string)
        text: Message text body
        token: Bot token override (defaults to settings.telegram_channel_token)

    Returns:
        Telegram API response dict

    Raises:
        TelegramSendError: On API errors (check .retryable before scheduling retry)
    """
    url = _bot_url("sendMessage", token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    return await _send_request(url, payload, chat_id)


async def delete_webhook(token: str | None = None) -> dict:
    """
    Remove webhook so polling can work.

    Args:
        token: Bot token override

    Returns:
        Telegram API response dict
    """
    url = _bot_url("deleteWebhook", token)
    return await _send_request(url, {}, "system")


async def set_webhook(
    webhook_url: str,
    secret_token: str | None = None,
    token: str | None = None,
) -> dict:
    """
    Set webhook URL for Telegram bot.

    Args:
        webhook_url: Public HTTPS URL for receiving updates
        secret_token: Secret token for X-Telegram-Bot-Api-Secret-Token header validation
        token: Bot token override

    Returns:
        Telegram API response dict
    """
    url = _bot_url("setWebhook", token)
    payload: dict = {"url": webhook_url}
    if secret_token:
        payload["secret_token"] = secret_token

    return await _send_request(url, payload, "system")


async def get_updates(
    offset: int | None = None,
    timeout: int = 30,
    token: str | None = None,
) -> list[dict]:
    """
    Long-poll for updates via getUpdates.

    Args:
        offset: Identifier of the first update to be returned
        timeout: Long-polling timeout in seconds
        token: Bot token override

    Returns:
        List of Update dicts
    """
    url = _bot_url("getUpdates", token)
    payload: dict = {"timeout": timeout}
    if offset is not None:
        payload["offset"] = offset

    session = get_sender_session()
    try:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout + 10, connect=5),
        ) as resp:
            body = await _safe_response_json(resp)

            if resp.status == 200 and body and body.get("ok"):
                return body.get("result", [])

            error_desc = (body or {}).get("description", "Unknown error")
            error_code = (body or {}).get("error_code")

            raise TelegramSendError(
                resp.status, error_code, error_desc,
                retryable=resp.status == 429 or resp.status >= 500,
            )

    except TelegramSendError:
        raise
    except aiohttp.ClientError as exc:
        logger.error(f"Telegram getUpdates connection error: {exc}", exc_info=True)
        raise TelegramSendError(0, None, str(exc), retryable=True)


async def get_file(file_id: str, token: str | None = None) -> dict | None:
    """
    Get file info from Telegram (for media download).

    Args:
        file_id: Telegram file_id from message
        token: Bot token override

    Returns:
        File info dict with file_path, or None on failure
    """
    url = _bot_url("getFile", token)
    payload = {"file_id": file_id}

    try:
        session = get_sender_session()
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.error(f"Telegram getFile failed: status={resp.status}")
                return None

            data = await _safe_response_json(resp)
            if data and data.get("ok"):
                return data.get("result")
            return None

    except Exception as exc:
        logger.error(f"Telegram getFile error: {exc}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

async def _safe_response_json(resp: aiohttp.ClientResponse) -> dict | None:
    """Parse JSON from response, returning None if body is not valid JSON."""
    try:
        return await resp.json()
    except Exception:
        logger.warning(f"Telegram API returned non-JSON body: status={resp.status}")
        return None


async def _safe_response_text(resp: aiohttp.ClientResponse, max_len: int = 300) -> str:
    """Read response body as text, truncated for safe logging."""
    try:
        text = await resp.text()
        return text[:max_len]
    except Exception:
        return "<unreadable>"


async def _send_request(url: str, payload: dict, chat_id: str) -> dict:
    """
    Execute a Telegram Bot API request with error handling.
    """
    try:
        session = get_sender_session()
        async with session.post(url, json=payload) as resp:
            body = await _safe_response_json(resp)

            if resp.status == 200 and body and body.get("ok"):
                result = body.get("result", {})
                msg_id = result.get("message_id", "unknown") if isinstance(result, dict) else "ok"
                masked = chat_id[:4] + "***" if len(chat_id) > 4 else chat_id
                logger.info(f"Telegram message sent: to={masked}, msg_id={msg_id}")
                inc_counter("telegram_outbound_sent")
                return body

            # --- Error path ------------------------------------------------
            error_desc = (body or {}).get("description", "Unknown error")
            error_code = (body or {}).get("error_code")

            # -- Auth failure: token invalid (DO NOT retry) --------
            if resp.status == 401 or error_code == 401:
                logger.error(f"Telegram API auth error (token invalid): {error_desc}")
                inc_counter("telegram_outbound_auth_error")
                raise TelegramSendError(
                    resp.status, error_code, error_desc, retryable=False,
                )

            # -- Forbidden: bot blocked by user or chat not found (DO NOT retry) --
            if resp.status == 403:
                logger.warning(f"Telegram API forbidden: {error_desc}")
                inc_counter("telegram_outbound_forbidden")
                raise TelegramSendError(
                    resp.status, error_code, error_desc, retryable=False,
                )

            # -- Bad request: chat not found, message too long, etc. (DO NOT retry) --
            if resp.status == 400:
                logger.warning(f"Telegram API bad request: {error_desc}")
                inc_counter("telegram_outbound_bad_request")
                raise TelegramSendError(
                    resp.status, error_code, error_desc, retryable=False,
                )

            # -- Rate limit: retry with backoff --------------
            if resp.status == 429:
                retry_after = (body or {}).get("parameters", {}).get("retry_after", 30)
                logger.warning(f"Telegram API rate limit, retry_after={retry_after}s")
                inc_counter("telegram_outbound_rate_limited")
                raise TelegramSendError(
                    resp.status, error_code, error_desc, retryable=True,
                )

            # -- Anything else: optimistic retry ----------------------------
            logger.error(f"Telegram API error: status={resp.status}, code={error_code}, msg={error_desc}")
            inc_counter("telegram_outbound_error")
            raise TelegramSendError(
                resp.status, error_code, error_desc, retryable=True,
            )

    except TelegramSendError:
        raise
    except aiohttp.ClientError as exc:
        logger.error(f"Telegram API connection error: {exc}", exc_info=True)
        inc_counter("telegram_outbound_connection_error")
        raise TelegramSendError(0, None, str(exc), retryable=True)
    except Exception as exc:
        logger.error(f"Telegram API unexpected error: {exc}", exc_info=True)
        inc_counter("telegram_outbound_unexpected_error")
        raise TelegramSendError(0, None, str(exc), retryable=True)
