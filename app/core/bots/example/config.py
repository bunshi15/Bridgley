# app/core/bots/example/config.py
"""
Example bot configuration — minimal skeleton.

This file demonstrates the minimum required to define a new bot.
It is NOT registered by default — see __init__.py for instructions.
"""
from enum import Enum

from app.core.bot_types import BotConfig, Intent, IntentPatterns, Translation


# ---------------------------------------------------------------------------
# Steps — define your conversation flow
# ---------------------------------------------------------------------------

class ExampleBotStep(str, Enum):
    WELCOME = "welcome"
    ASK_NAME = "ask_name"
    DONE = "done"


# ---------------------------------------------------------------------------
# Intent patterns — keywords that trigger intents in any language
# ---------------------------------------------------------------------------

EXAMPLE_INTENT_PATTERNS = {
    Intent.RESET: IntentPatterns(
        ru={"заново", "/start"},
        en={"reset", "/start"},
        he={"מחדש", "/start"},
    ),
    Intent.CONFIRM: IntentPatterns(
        ru={"да", "готово"},
        en={"yes", "done"},
        he={"כן", "סיימתי"},
    ),
}


# ---------------------------------------------------------------------------
# Translations — all user-facing text, tri-lingual
# ---------------------------------------------------------------------------

EXAMPLE_TRANSLATIONS = {
    "welcome": Translation(
        ru="Привет! Это пример бота.",
        en="Hello! This is an example bot.",
        he="שלום! זה בוט לדוגמה.",
    ),
    "q_name": Translation(
        ru="Как тебя зовут?",
        en="What is your name?",
        he="מה שמך?",
    ),
    "done": Translation(
        ru="Спасибо, {name}! Готово.",
        en="Thanks, {name}! Done.",
        he="תודה, {name}! סיימנו.",
    ),
}


# ---------------------------------------------------------------------------
# Bot configuration — NOT registered (example only)
# ---------------------------------------------------------------------------

EXAMPLE_BOT_CONFIG = BotConfig(
    bot_id="example_bot",
    name=Translation(ru="Пример", en="Example Bot", he="בוט לדוגמה"),
    description=Translation(
        ru="Минимальный пример бота",
        en="Minimal bot example",
        he="דוגמה מינימלית לבוט",
    ),
    step_enum=ExampleBotStep,
    initial_step=ExampleBotStep.WELCOME.value,
    final_step=ExampleBotStep.DONE.value,
    intent_patterns=EXAMPLE_INTENT_PATTERNS,
    translations=EXAMPLE_TRANSLATIONS,
    choices={},
    choice_labels={},
)
