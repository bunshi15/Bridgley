# app/core/bots/moving_bot_v1/texts.py
"""
Text accessor for the Moving Bot bundle.

Provides ``get_text(key, lang)`` which resolves translations from
``MOVING_BOT_CONFIG`` at call time (not import time), enabling
per-session language selection.
"""
from __future__ import annotations


def get_text(key: str, lang: str = "ru") -> str:
    """
    Get a translated text string from the moving bot bundle.

    Args:
        key: Translation key (e.g. ``"welcome"``, ``"q_cargo"``,
             ``"err_cargo_too_short"``).
        lang: ISO language code — ``"ru"``, ``"en"``, or ``"he"``.

    Returns:
        Translated string, or *key* itself if no translation exists.
    """
    from app.core.bots.moving_bot_v1.config import MOVING_BOT_CONFIG

    translation = MOVING_BOT_CONFIG.translations.get(key)
    if translation is None:
        return key
    return translation.get(lang)
