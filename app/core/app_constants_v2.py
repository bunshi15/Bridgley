# app/core/app_constants_v2.py
"""
Universal bot constants system — DEPRECATED.

This file provides backward compatibility with app_constants.py
while using the new universal bot configuration system.

.. deprecated::
    Use the bot-local modules directly instead of importing from here:
    - ``app.core.bots.moving_bot_texts.get_text`` — translated texts
    - ``app.core.bots.moving_bot_choices`` — TIME_CHOICES_DICT, EXTRA_OPTIONS, VALUE_NONE
    - ``app.core.bots.moving_bot_validators`` — norm, lower, looks_too_short, detect_intent
    - ``app.core.bots.moving_bot_pricing`` — pricing catalog (Phase 3)

    Only ``HINT_STALE_RESUME`` is still consumed by ``use_cases.py``.
"""
from app.core.bot_types import Translator, Intent, detect_universal_intent
from app.core.bots.moving_bot_config import (
    MOVING_BOT_CONFIG,
    MovingBotStep,
    MovingTimeWindow,
    MovingExtraService,
    TIME_CHOICES,
    EXTRA_CHOICES,
)

# ============================================================================
# TRANSLATOR INSTANCE (default Russian)
# ============================================================================

# Create translator with default language
translator = Translator(MOVING_BOT_CONFIG.translations, lang="ru")


def get_translator(lang: str = "ru") -> Translator:
    """Get translator instance with specified language"""
    return Translator(MOVING_BOT_CONFIG.translations, lang=lang)


def translate(key: str, lang: str = "ru") -> str:
    """Quick translation helper"""
    return get_translator(lang).get(key)


# ============================================================================
# BACKWARD COMPATIBILITY - Expose old constant names
# ============================================================================

# Questions
WELCOME_TEXT = translator.get("welcome")
Q_CARGO = translator.get("q_cargo")
Q_ADDR_FROM = translator.get("q_addr_from")
Q_ADDR_TO = translator.get("q_addr_to")
Q_FLOOR_FROM = translator.get("q_floor_from")
Q_FLOOR_TO = translator.get("q_floor_to")
Q_TIME = translator.get("q_time")
Q_PHOTO_MENU = translator.get("q_photo_menu")
Q_PHOTO_WAIT = translator.get("q_photo_wait")
Q_EXTRAS = translator.get("q_extras")
DONE_TEXT = translator.get("done")

# Errors
ERR_CARGO_TOO_SHORT = translator.get("err_cargo_too_short")
ERR_ADDR_TOO_SHORT = translator.get("err_addr_too_short")
ERR_FLOOR_TOO_SHORT = translator.get("err_floor_too_short")
ERR_TIME_FORMAT = translator.get("err_time_format")
ERR_PHOTO_MENU = translator.get("err_photo_menu")
ERR_EXTRAS_EMPTY = translator.get("err_extras_empty")

# Info messages
INFO_PHOTO_WAIT = translator.get("info_photo_wait")
INFO_PHOTO_RECEIVED_FIRST = translator.get("info_photo_received_first")
INFO_PHOTO_RECEIVED_LATE = translator.get("info_photo_received_late")
INFO_ALREADY_DONE = translator.get("info_already_done")
HINT_CAN_RESET = translator.get("hint_can_reset")
HINT_STALE_RESUME = translator.get("hint_stale_resume")

# Choice mappings (backward compatible)
TIME_CHOICES_DICT = TIME_CHOICES  # {"1": "today", "2": "tomorrow", "3": "soon"}
EXTRA_OPTIONS = EXTRA_CHOICES  # {"1": "loaders", "2": "assembly", "3": "packing"}

# Value constants
VALUE_NONE: str = MovingExtraService.NONE.value  # "none"

# Legacy constants (keep for now)
HEBREW_RE = r"[\u0590-\u05FF]"


# ============================================================================
# INTENT DETECTION (Universal)
# ============================================================================

def detect_intent(text: str) -> str | None:
    """
    Detect user intent using universal intent detection system.

    Returns:
        Intent name as string ("reset", "confirm", "decline") or None

    Note: Maps universal Intent enum to old string format for backward compatibility
    """
    intent = detect_universal_intent(text, MOVING_BOT_CONFIG.intent_patterns)

    if intent is None:
        return None

    # Map universal intents to old names for backward compatibility
    intent_map = {
        Intent.RESET: "reset",
        Intent.CONFIRM: "done_photos",  # Old code expects "done_photos"
        Intent.DECLINE: "no",
    }

    return intent_map.get(intent)


# ============================================================================
# ENUM EXPORTS (for new code)
# ============================================================================

# Export enums for use in engine
Step = MovingBotStep
TimeWindow = MovingTimeWindow
ExtraService = MovingExtraService

# Export for convenience
__all__ = [
    # Translator
    "translator",
    "get_translator",
    "translate",

    # Questions
    "WELCOME_TEXT",
    "Q_CARGO",
    "Q_ADDR_FROM",
    "Q_ADDR_TO",
    "Q_FLOOR_FROM",
    "Q_FLOOR_TO",
    "Q_TIME",
    "Q_PHOTO_MENU",
    "Q_PHOTO_WAIT",
    "Q_EXTRAS",
    "DONE_TEXT",

    # Errors
    "ERR_CARGO_TOO_SHORT",
    "ERR_ADDR_TOO_SHORT",
    "ERR_FLOOR_TOO_SHORT",
    "ERR_TIME_FORMAT",
    "ERR_PHOTO_MENU",
    "ERR_EXTRAS_EMPTY",

    # Info
    "INFO_PHOTO_WAIT",
    "INFO_PHOTO_RECEIVED_FIRST",
    "INFO_PHOTO_RECEIVED_LATE",
    "INFO_ALREADY_DONE",
    "HINT_CAN_RESET",
    "HINT_STALE_RESUME",

    # Choices
    "TIME_CHOICES_DICT",
    "EXTRA_OPTIONS",
    "VALUE_NONE",

    # Intent detection
    "detect_intent",

    # Enums
    "Step",
    "TimeWindow",
    "ExtraService",
    "Intent",

    # Legacy
    "HEBREW_RE",
]
