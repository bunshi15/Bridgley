# app/core/bots/moving_bot_choices.py
"""
Choice mappings for the Moving Bot.

Re-exports from ``moving_bot_config`` under backward-compatible names
so that the handler (and future code) has a single import source for
user-input → enum-value mappings.
"""
from __future__ import annotations

from app.core.bots.moving_bot_config import (
    TIME_CHOICES, EXTRA_CHOICES,
    DATE_CHOICES, TIME_SLOT_CHOICES,
    VOLUME_CHOICES,
)
from app.core.engine.bot_types import MovingExtraService


# User input → enum value (legacy)
TIME_CHOICES_DICT: dict[str, str] = TIME_CHOICES       # {"1": "today", "2": "tomorrow", "3": "soon"}
EXTRA_OPTIONS: dict[str, str] = EXTRA_CHOICES           # {"1": "loaders", "2": "assembly", "3": "packing", "4": "none"}

# Phase 2: structured scheduling choices
DATE_CHOICES_DICT: dict[str, str] = DATE_CHOICES       # {"1": "tomorrow", "2": "2_3_days", "3": "this_week", "4": "specific"}
TIME_SLOT_CHOICES_DICT: dict[str, str] = TIME_SLOT_CHOICES  # {"1": "morning", ..., "5": "flexible"}

# Phase 9: volume category choices
VOLUME_CHOICES_DICT: dict[str, str] = VOLUME_CHOICES   # {"1": "small", "2": "medium", "3": "large", "4": "xl"}

# Sentinel value for "no extras"
VALUE_NONE: str = MovingExtraService.NONE.value         # "none"
