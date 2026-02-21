# app/infra/http_client.py
"""
Shared HTTP client sessions for the application.

Provides named, lazy-initialized aiohttp.ClientSession singletons
to avoid per-request session creation overhead and TCP connection churn.

Session profiles
~~~~~~~~~~~~~~~~
- **sender**  – outbound API calls (total=25 s, connect=5 s, pool limit=20)
- **fetcher** – media downloads   (total=60 s, connect=15 s, pool limit=10)
- **default** – general HTTP calls (total=30 s, connect=5 s, pool limit=10)

Shutdown
~~~~~~~~
Call ``close_all_sessions()`` once during application shutdown
(replaces per-module ``close_http_session()`` calls).
"""
from __future__ import annotations

import aiohttp

from app.infra.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_sessions: dict[str, aiohttp.ClientSession] = {}


def _get_or_create(
    name: str,
    timeout: aiohttp.ClientTimeout,
    limit: int = 10,
) -> aiohttp.ClientSession:
    """Return an existing session or create a new one."""
    session = _sessions.get(name)
    if session is None or session.closed:
        session = aiohttp.ClientSession(
            timeout=timeout,
            connector=aiohttp.TCPConnector(
                keepalive_timeout=30,
                limit=limit,
                enable_cleanup_closed=True,
            ),
        )
        _sessions[name] = session
        logger.debug("HTTP session '%s' created (limit=%d)", name, limit)
    return session


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_sender_session() -> aiohttp.ClientSession:
    """Session for outbound API calls (Telegram / Meta senders)."""
    return _get_or_create(
        "sender",
        aiohttp.ClientTimeout(total=25, connect=5),
        limit=20,
    )


def get_fetcher_session() -> aiohttp.ClientSession:
    """Session for media downloads (fetchers, image processor)."""
    return _get_or_create(
        "fetcher",
        aiohttp.ClientTimeout(total=60, connect=15),
        limit=10,
    )


def get_default_session() -> aiohttp.ClientSession:
    """General-purpose session (notification channels, etc.)."""
    return _get_or_create(
        "default",
        aiohttp.ClientTimeout(total=30, connect=5),
        limit=10,
    )


async def close_all_sessions() -> None:
    """Gracefully close every managed session.  Call during app shutdown."""
    for name in list(_sessions):
        session = _sessions.pop(name, None)
        if session is not None and not session.closed:
            await session.close()
            logger.debug("HTTP session '%s' closed", name)
