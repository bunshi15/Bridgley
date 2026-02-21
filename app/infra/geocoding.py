# app/infra/geocoding.py
"""
Reverse geocoding via Nominatim (OpenStreetMap).

Provides ``reverse_geocode(lat, lon)`` which returns a human-readable
address string, or ``None`` on failure.  Uses the shared aiohttp session
from ``http_client`` with graceful degradation (timeout / error → None).

Nominatim usage policy: max 1 req/sec, requires User-Agent.
In practice, location messages are very infrequent (1–2 per session).
"""
from __future__ import annotations

import aiohttp

from app.infra.http_client import get_default_session
from app.infra.logging_config import get_logger, mask_coordinates

logger = get_logger(__name__)

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_USER_AGENT = "Stage0Bot/1.0 (moving-bot geocoding)"
_TIMEOUT_SECONDS = 5  # Aggressive timeout: don't block the user


def _format_address(data: dict) -> str | None:
    """Extract a short address from Nominatim response JSON.

    Prefers: ``"{road} {house_number}, {city}"``
    Falls back to ``display_name`` (truncated if very long).
    """
    address = data.get("address", {})

    parts: list[str] = []

    # Street / road
    road = (
        address.get("road")
        or address.get("pedestrian")
        or address.get("footway")
    )
    house = address.get("house_number")
    if road:
        parts.append(f"{road} {house}" if house else road)

    # City / town / village
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("suburb")
    )
    if city:
        parts.append(city)

    if parts:
        return ", ".join(parts)

    # Fallback: raw display_name (truncated if very long)
    display = data.get("display_name")
    if display and len(display) > 80:
        display = display[:77] + "..."
    return display


async def reverse_geocode(
    latitude: float,
    longitude: float,
    accept_language: str = "ru,en,he",
) -> str | None:
    """
    Reverse-geocode GPS coordinates to a human-readable address.

    Returns a short address string like ``"Herzl 10, Haifa"``
    or ``None`` if the geocoding fails for any reason.

    Uses the Nominatim (OpenStreetMap) API.  Failures are
    gracefully handled — the bot conversation is never interrupted.
    """
    params = {
        "lat": str(latitude),
        "lon": str(longitude),
        "format": "json",
        "addressdetails": "1",
        "zoom": "18",
        "accept-language": accept_language,
    }
    headers = {
        "User-Agent": _USER_AGENT,
    }

    try:
        session = get_default_session()
        timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)

        async with session.get(
            NOMINATIM_REVERSE_URL,
            params=params,
            headers=headers,
            timeout=timeout,
        ) as resp:
            masked = mask_coordinates(latitude, longitude)
            if resp.status != 200:
                logger.warning(
                    "Nominatim returned status %d for (%s)",
                    resp.status, masked,
                )
                return None

            data = await resp.json(content_type=None)

            result = _format_address(data)
            if result:
                logger.info(
                    "Geocoded (%s) → %s",
                    masked, result[:60],
                )
            return result

    except TimeoutError:
        logger.warning(
            "Nominatim timeout for (%s)", mask_coordinates(latitude, longitude),
        )
        return None

    except aiohttp.ClientError as exc:
        logger.warning(
            "Nominatim network error for (%s): %s",
            mask_coordinates(latitude, longitude), exc,
        )
        return None

    except Exception as exc:
        logger.warning(
            "Nominatim unexpected error for (%s): %s",
            mask_coordinates(latitude, longitude), exc,
            exc_info=True,
        )
        return None
