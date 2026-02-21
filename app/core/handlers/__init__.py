# app/core/handlers/__init__.py
"""
Bot Handlers Package

This package contains all bot type implementations.
Each handler implements the BotHandler protocol and is registered with the BotHandlerRegistry.
"""
from app.core.bot_handler import BotHandlerRegistry
from app.core.handlers.moving_bot_handler import MovingBotHandler

# Register all bot handlers
BotHandlerRegistry.register("moving_bot_v1", MovingBotHandler())

# Export for convenience
__all__ = [
    "MovingBotHandler",
]
