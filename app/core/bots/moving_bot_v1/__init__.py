# app/core/bots/moving_bot_v1/__init__.py
"""
Moving Bot v1 — package layout (EPIC A1.1).

Canonical source for all moving-bot modules. The flat files at
``app/core/bots/moving_bot_*.py`` are now thin re-export shims that
import from this package for backward compatibility.

Sub-modules:
    config      — BotConfig, translations, choices, intent patterns
    texts       — get_text(key, lang) accessor
    choices     — choice mapping re-exports (TIME_CHOICES_DICT, etc.)
    validators  — input validators, intent detection, floor/date parsing
    pricing     — pricing config, item catalog, estimate_price()
    geo         — regional/route classification
    localities  — CBS locality dataset + lookup
    data/       — JSON data files (pricing_config, localities, etc.)
"""
