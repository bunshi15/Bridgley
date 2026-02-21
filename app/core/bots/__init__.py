# app/core/bots/__init__.py
"""
Bot configurations registry.
Import and register all bot configurations here.

EPIC A1.1: bots are now organised as packages under this directory.
Each bot lives in its own sub-package (e.g. ``moving_bot_v1/``).
Legacy flat ``moving_bot_*.py`` files are thin re-export shims.
"""
from app.core.bot_types import BotRegistry
from app.core.bots.moving_bot_v1.config import MOVING_BOT_CONFIG
from app.core.bots.moving_bot_v1.texts import get_text
from app.core.bots.moving_bot_v1.validators import detect_intent

# Register all bots
BotRegistry.register("moving_bot_v1", MOVING_BOT_CONFIG)

# Export for convenience
__all__ = ["MOVING_BOT_CONFIG", "get_text", "detect_intent"]
