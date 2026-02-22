# app/core/handlers/registry.py
"""
Runtime-controlled handler registration (EPIC A1).

Replaces the old static ``import app.core.handlers`` pattern.
Only bots listed in ``ENABLED_BOTS`` env var are imported and registered,
eliminating side-effect imports and enabling modular deployment.

Usage at startup::

    from app.core.handlers.registry import register_handlers, parse_enabled_bots
    register_handlers(parse_enabled_bots())
"""
from __future__ import annotations

import logging
from typing import Sequence

from app.core.engine.bot_handler import BotHandlerRegistry

logger = logging.getLogger(__name__)

# Map of known bot_type → lazy import path + class name.
# New bots only need an entry here + their handler module.
_KNOWN_BOTS: dict[str, tuple[str, str]] = {
    "moving_bot_v1": (
        "app.core.handlers.moving_bot_handler",
        "MovingBotHandler",
    ),
    # Future:
    # "moving_bot_v2": (
    #     "app.core.handlers.moving_bot_v2_handler",
    #     "MovingBotV2Handler",
    # ),
}


def parse_enabled_bots() -> list[str]:
    """Parse ``ENABLED_BOTS`` from settings into a list of bot type strings."""
    from app.config import settings
    raw = settings.enabled_bots.strip()
    if not raw:
        return []
    return [b.strip() for b in raw.split(",") if b.strip()]


def register_handlers(enabled: Sequence[str] | None = None) -> list[str]:
    """
    Import and register only the requested bot handlers.

    Args:
        enabled: List of bot_type strings to register.
                 If *None*, falls back to ``parse_enabled_bots()``.

    Returns:
        List of bot_type strings that were successfully registered.
    """
    if enabled is None:
        enabled = parse_enabled_bots()

    registered: list[str] = []

    for bot_type in enabled:
        if BotHandlerRegistry.has_handler(bot_type):
            # Already registered (e.g. tests may call this twice)
            registered.append(bot_type)
            continue

        spec = _KNOWN_BOTS.get(bot_type)
        if spec is None:
            logger.error(
                "Unknown bot type '%s' in ENABLED_BOTS, skipping. "
                "Known types: %s",
                bot_type, ", ".join(_KNOWN_BOTS.keys()),
            )
            continue

        module_path, class_name = spec
        try:
            import importlib
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            BotHandlerRegistry.register(bot_type, cls())
            registered.append(bot_type)
            logger.info("Registered bot handler: %s", bot_type)
        except Exception:
            logger.error(
                "Failed to register bot handler '%s'",
                bot_type,
                exc_info=True,
            )

    if not registered:
        logger.warning("No bot handlers registered! Check ENABLED_BOTS setting.")

    return registered
