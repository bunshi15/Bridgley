# app/core/handlers/__init__.py
"""
Bot Handlers Package

This package contains all bot type implementations.
Each handler implements the BotHandler protocol.

**Registration** is no longer done at import time (EPIC A1).
Use ``register_handlers()`` from ``app.core.handlers.registry``
at application startup instead.  Only bots listed in ``ENABLED_BOTS``
env var will be loaded.
"""

# NOTE: Do NOT import handler classes here — that would defeat
# the purpose of lazy/selective registration via ENABLED_BOTS.
# Use ``from app.core.handlers.registry import register_handlers``.
