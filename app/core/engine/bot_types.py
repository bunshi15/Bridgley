# app/core/engine/bot_types.py
"""
Universal bot configuration system.
Define different bot types with their own flows, messages, and business logic.
"""
from __future__ import annotations
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Set, Callable, Optional


# ============================================================================
# UNIVERSAL ENUMS (used across all bot types)
# ============================================================================

class Intent(str, Enum):
    """Universal user intents across all bot types"""
    RESET = "reset"
    CONFIRM = "confirm"  # yes, done, finished
    DECLINE = "decline"  # no, cancel
    SKIP = "skip"
    HELP = "help"


class MessageType(str, Enum):
    """Universal message types"""
    QUESTION = "question"
    ERROR = "error"
    INFO = "info"
    SUCCESS = "success"
    PROMPT = "prompt"


# ============================================================================
# BOT TYPE SPECIFIC ENUMS
# ============================================================================

class MovingBotStep(str, Enum):
    """Steps specific to moving/delivery bot"""
    WELCOME = "welcome"
    CARGO = "cargo"
    # Phase 9: volume category (small/medium/large/xl)
    VOLUME = "volume"
    # Phase 4: multi-pickup (1–3 locations)
    PICKUP_COUNT = "pickup_count"
    ADDR_FROM = "addr_from"
    FLOOR_FROM = "floor_from"
    ADDR_FROM_2 = "addr_from_2"
    FLOOR_FROM_2 = "floor_from_2"
    ADDR_FROM_3 = "addr_from_3"
    FLOOR_FROM_3 = "floor_from_3"
    ADDR_TO = "addr_to"
    FLOOR_TO = "floor_to"
    # Phase 2: structured scheduling (replaces TIME)
    DATE = "date"
    SPECIFIC_DATE = "specific_date"
    TIME_SLOT = "time_slot"
    EXACT_TIME = "exact_time"
    # Legacy (kept for backward compat with sessions mid-flow at deploy)
    TIME = "time"
    PHOTO_MENU = "photo_menu"
    PHOTO_WAIT = "photo_wait"
    EXTRAS = "extras"
    # Phase 3: pricing estimate shown before confirmation
    ESTIMATE = "estimate"
    DONE = "done"


class MovingTimeWindow(str, Enum):
    """Time window options for moving bot — LEGACY (Phase 1).
    Kept for backward compatibility with app_constants_v2.py.
    New code should use MovingTimeSlot instead."""
    TODAY = "today"
    TOMORROW = "tomorrow"
    SOON = "soon"
    CUSTOM = "custom"


class MovingDateChoice(str, Enum):
    """Date selection options for moving bot (Phase 2)"""
    TOMORROW = "tomorrow"
    IN_2_3_DAYS = "2_3_days"
    THIS_WEEK = "this_week"
    SPECIFIC = "specific"


class MovingTimeSlot(str, Enum):
    """Time-of-day slot options for moving bot (Phase 2)"""
    MORNING = "morning"       # 08:00-12:00
    AFTERNOON = "afternoon"   # 12:00-16:00
    EVENING = "evening"       # 16:00-20:00
    EXACT = "exact"           # user provides HH:MM
    FLEXIBLE = "flexible"     # not sure yet


class MovingExtraService(str, Enum):
    """Extra services for moving bot"""
    LOADERS = "loaders"
    ASSEMBLY = "assembly"
    PACKING = "packing"
    NONE = "none"


# Future bot types can add their own enums:
# class RestaurantBotStep(str, Enum):
#     WELCOME = "welcome"
#     CUISINE = "cuisine"
#     PARTY_SIZE = "party_size"
#     TIME = "time"
#     SPECIAL_REQUESTS = "special_requests"
#     DONE = "done"


# ============================================================================
# TRANSLATION SYSTEM
# ============================================================================

@dataclass
class Translation:
    """Multi-language text storage"""
    ru: str
    en: Optional[str] = None
    he: Optional[str] = None

    def get(self, lang: str = "ru") -> str:
        """Get translation for specified language, fallback to Russian"""
        return getattr(self, lang, None) or self.ru


class Translator:
    """Translation helper for bot messages"""

    def __init__(self, translations: Dict[str, Translation], lang: str = "ru"):
        self.translations = translations
        self.lang = lang

    def get(self, key: str) -> str:
        """Get translated text by key"""
        translation = self.translations.get(key)
        if translation:
            return translation.get(self.lang)
        return key  # Return key if translation not found

    def set_language(self, lang: str) -> None:
        """Change current language"""
        self.lang = lang


# ============================================================================
# INTENT PATTERNS (language-specific keywords)
# ============================================================================

@dataclass
class IntentPatterns:
    """Define keyword patterns for intent detection across languages"""
    ru: Set[str]
    en: Set[str]
    he: Set[str]

    def matches(self, text: str) -> bool:
        """Check if text matches any pattern"""
        normalized = text.strip().lower()
        return (
            normalized in self.ru or
            normalized in self.en or
            normalized in self.he
        )


# ============================================================================
# BOT CONFIGURATION
# ============================================================================

@dataclass
class BotConfig:
    """Configuration for a specific bot type"""
    bot_id: str  # e.g., "moving_bot_v1", "restaurant_bot_v1"
    name: Translation
    description: Translation

    # Conversation flow
    step_enum: type[Enum]  # e.g., MovingBotStep
    initial_step: str
    final_step: str

    # Intent patterns (universal intents)
    intent_patterns: Dict[Intent, IntentPatterns]

    # Bot-specific translations
    translations: Dict[str, Translation]

    # Bot-specific data mappings (for dropdowns, choices, etc.)
    choices: Dict[str, Dict[str, str]]  # e.g., {"time": {"1": "today", "2": "tomorrow"}}
    choice_labels: Dict[str, Dict[str, Translation]]  # Display labels

    # Business logic handlers (optional, can be overridden)
    validators: Dict[str, Callable] = None  # Step validators
    processors: Dict[str, Callable] = None  # Step processors


# ============================================================================
# BOT REGISTRY
# ============================================================================

class BotRegistry:
    """Central registry for all bot configurations"""

    _bots: Dict[str, BotConfig] = {}

    @classmethod
    def register(cls, bot_id: str, config: BotConfig) -> None:
        """Register a new bot configuration"""
        cls._bots[bot_id] = config

    @classmethod
    def get(cls, bot_id: str) -> Optional[BotConfig]:
        """Get bot configuration by ID"""
        return cls._bots.get(bot_id)

    @classmethod
    def list_bots(cls) -> list[str]:
        """List all registered bot IDs"""
        return list(cls._bots.keys())


# ============================================================================
# UNIVERSAL INTENT DETECTOR
# ============================================================================

def detect_universal_intent(
    text: str,
    intent_patterns: Dict[Intent, IntentPatterns]
) -> Optional[Intent]:
    """
    Universal intent detection that works with any bot configuration.

    Args:
        text: User input
        intent_patterns: Bot-specific intent patterns

    Returns:
        Detected intent or None
    """
    if not text:
        return None

    for intent, patterns in intent_patterns.items():
        if patterns.matches(text):
            return intent

    return None
