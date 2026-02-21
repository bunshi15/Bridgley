# app/core/i18n/lead_translator.py
"""
Operator lead translation pipeline.

Translates human-readable fields in the finalized lead payload from
the user's session language to the configured ``operator_lead_target_lang``.

Only runs when:
- ``operator_lead_translation_enabled`` is True
- ``source_lang != target_lang``
- A translation provider is configured

Preserves original payload fields and adds:
- ``translations.{target_lang}`` — translated field values
- ``translation_meta`` — provider, status, source/target lang
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# Fields eligible for translation (human-readable, free-text).
# Phone numbers, IDs, prices, etc. are excluded.
_TRANSLATABLE_FIELDS = frozenset({
    "cargo_description",
    "addr_from",
    "addr_to",
    "details_free",
})

# Custom dict keys that may contain translatable text
_TRANSLATABLE_CUSTOM_FIELDS = frozenset({
    "cargo_raw",
    "landing_date_hint",
    "landing_move_type",
})


def _extract_translatable(payload: dict[str, Any]) -> dict[str, str]:
    """Extract translatable text fields from a lead payload.

    Returns ``{field_name: text_value}`` for non-empty text fields.
    """
    data = payload.get("data", payload)
    custom = data.get("custom", {})

    fields: dict[str, str] = {}

    for key in _TRANSLATABLE_FIELDS:
        val = data.get(key)
        if val and isinstance(val, str) and val.strip():
            fields[key] = val.strip()

    for key in _TRANSLATABLE_CUSTOM_FIELDS:
        val = custom.get(key)
        if val and isinstance(val, str) and val.strip():
            fields[key] = val.strip()

    # Multi-pickup addresses
    pickups = custom.get("pickups", [])
    for i, p in enumerate(pickups):
        addr = p.get("addr")
        if addr and isinstance(addr, str) and addr.strip():
            fields[f"pickup_{i+1}_addr"] = addr.strip()
        floor = p.get("floor")
        if floor and isinstance(floor, str) and floor.strip() and floor != "—":
            fields[f"pickup_{i+1}_floor"] = floor.strip()

    return fields


async def translate_lead_payload(
    payload: dict[str, Any],
    source_lang: str,
) -> dict[str, Any]:
    """Translate operator-facing fields in a lead payload.

    Mutates *payload* in-place by adding ``translations`` and
    ``translation_meta`` blocks.  Original fields are never modified.

    Returns the same *payload* dict (for convenience).

    If translation is disabled, source==target, or the provider fails,
    the payload is returned unchanged (with appropriate meta status).
    """
    from app.config import settings
    from app.core.i18n.translation_provider import get_translation_provider

    target_lang = settings.operator_lead_target_lang

    # Ensure we have a data.custom dict to attach translation blocks
    data = payload.get("data", payload)
    custom = data.setdefault("custom", {})

    # Skip if disabled
    if not settings.operator_lead_translation_enabled:
        return payload

    # Skip if source == target (no translation needed)
    if source_lang == target_lang:
        custom["translation_meta"] = {
            "enabled": True,
            "provider": settings.translation_provider,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "status": "skipped_same_lang",
        }
        return payload

    # Get provider
    provider = get_translation_provider()
    if provider is None:
        custom["translation_meta"] = {
            "enabled": True,
            "provider": settings.translation_provider,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "status": "no_provider",
        }
        return payload

    # Extract translatable fields
    fields = _extract_translatable(payload)
    if not fields:
        custom["translation_meta"] = {
            "enabled": True,
            "provider": settings.translation_provider,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "status": "no_fields",
        }
        return payload

    # Translate via external API
    start = time.monotonic()
    try:
        translated = await provider.translate_batch(fields, source_lang, target_lang)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        # Check if we got back the same text (API failure fallback)
        any_changed = any(translated.get(k) != v for k, v in fields.items())
        status = "ok" if any_changed else "unchanged"

        custom["translations"] = {target_lang: translated}
        custom["translation_meta"] = {
            "enabled": True,
            "provider": settings.translation_provider,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "status": status,
            "latency_ms": elapsed_ms,
            "field_count": len(fields),
        }

        logger.info(
            "Lead translation completed: status=%s, provider=%s, "
            "fields=%d, latency=%dms",
            status, settings.translation_provider,
            len(fields), elapsed_ms,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.error(
            "Lead translation failed: %s, latency=%dms",
            type(exc).__name__, elapsed_ms,
        )
        custom["translations"] = {target_lang: {}}
        custom["translation_meta"] = {
            "enabled": True,
            "provider": settings.translation_provider,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "status": "failed",
            "latency_ms": elapsed_ms,
            "error": type(exc).__name__,
        }

    return payload
