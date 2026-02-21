# app/core/bots/__init__.py
"""
Bot configurations registry.
Import and register all bot configurations here.

Bot-local modules (Phase 1 — bot engine isolation):
- moving_bot_config   — BotConfig + translations + choices (canonical source)
- moving_bot_texts    — get_text(key, lang) accessor
- moving_bot_choices  — choice mappings (TIME_CHOICES_DICT, EXTRA_OPTIONS)
- moving_bot_validators — input validators + intent detection
- moving_bot_pricing  — pricing placeholder (Haifa Metro catalog)
"""
from app.core.bot_types import BotRegistry
from app.core.bots.moving_bot_config import MOVING_BOT_CONFIG
from app.core.bots.moving_bot_texts import get_text
from app.core.bots.moving_bot_validators import detect_intent

# Register all bots
BotRegistry.register("moving_bot_v1", MOVING_BOT_CONFIG)

# Export for convenience
__all__ = ["MOVING_BOT_CONFIG", "get_text", "detect_intent"]
