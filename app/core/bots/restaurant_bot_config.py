# app/core/bots/restaurant_bot_config.py
"""
EXAMPLE: Restaurant Reservation Bot Configuration.
This demonstrates how easy it is to create a new bot type.
"""
from enum import Enum
from app.core.bot_types import (
    BotConfig, Intent, IntentPatterns, Translation
)


# ============================================================================
# RESTAURANT BOT SPECIFIC ENUMS
# ============================================================================

class RestaurantBotStep(str, Enum):
    """Steps for restaurant reservation flow"""
    WELCOME = "welcome"
    CUISINE = "cuisine"
    PARTY_SIZE = "party_size"
    DATE = "date"
    TIME = "time"
    SPECIAL_REQUESTS = "special_requests"
    CONTACT = "contact"
    DONE = "done"


class CuisineType(str, Enum):
    """Cuisine preferences"""
    ITALIAN = "italian"
    ASIAN = "asian"
    MEDITERRANEAN = "mediterranean"
    STEAKHOUSE = "steakhouse"
    VEGETARIAN = "vegetarian"
    ANY = "any"


class TimeSlot(str, Enum):
    """Dinner time slots"""
    LUNCH = "lunch"  # 12:00-15:00
    EARLY = "early"  # 17:00-19:00
    PRIME = "prime"  # 19:00-21:00
    LATE = "late"    # 21:00-23:00


# ============================================================================
# INTENT PATTERNS (Restaurant Bot)
# ============================================================================

RESTAURANT_INTENT_PATTERNS = {
    Intent.RESET: IntentPatterns(
        ru={"заново", "сначала", "рестарт", "/start"},
        en={"reset", "restart", "start", "/start"},
        he={"התחל", "מחדש"}
    ),
    Intent.CONFIRM: IntentPatterns(
        ru={"да", "подтверждаю", "готово"},
        en={"yes", "confirm", "done"},
        he={"כן", "אישור"}
    ),
    Intent.DECLINE: IntentPatterns(
        ru={"нет", "отмена"},
        en={"no", "cancel"},
        he={"לא", "ביטול"}
    ),
}


# ============================================================================
# TRANSLATIONS (Restaurant Bot)
# ============================================================================

RESTAURANT_TRANSLATIONS = {
    "welcome": Translation(
        ru="Привет! 👋\nЯ помогу забронировать столик в ресторане.\nЗадам несколько вопросов — это займёт минуту.",
        en="Hello! 👋\nI'll help you book a restaurant table.\nI'll ask a few questions — it will take a minute.",
        he="שלום! 👋\nאני אעזור לך להזמין שולחן במסעדה.\nאשאל כמה שאלות - זה ייקח דקה."
    ),

    "q_cuisine": Translation(
        ru="Какая кухня вас интересует?\n1 — итальянская\n2 — азиатская\n3 — средиземноморская\n4 — стейк-хаус\n5 — вегетарианская\n6 — любая",
        en="What cuisine are you interested in?\n1 — Italian\n2 — Asian\n3 — Mediterranean\n4 — Steakhouse\n5 — Vegetarian\n6 — Any",
        he="איזו מטבח מעניין אותך?\n1 — איטלקי\n2 — אסייתי\n3 — ים תיכוני\n4 — סטייקים\n5 — צמחוני\n6 — כל דבר"
    ),

    "q_party_size": Translation(
        ru="На сколько человек бронируем?",
        en="How many people?",
        he="כמה אנשים?"
    ),

    "q_date": Translation(
        ru="На какую дату?\n(например: сегодня, завтра, 25.01)",
        en="For what date?\n(e.g., today, tomorrow, 25.01)",
        he="לאיזה תאריך?\n(למשל: היום, מחר, 25.01)"
    ),

    "q_time": Translation(
        ru="В какое время?\n1 — обед (12:00-15:00)\n2 — ранний ужин (17:00-19:00)\n3 — прайм-тайм (19:00-21:00)\n4 — поздний ужин (21:00-23:00)\nили укажите конкретное время",
        en="What time?\n1 — lunch (12:00-15:00)\n2 — early dinner (17:00-19:00)\n3 — prime time (19:00-21:00)\n4 — late dinner (21:00-23:00)\nor specify exact time",
        he="באיזו שעה?\n1 — צהריים (12:00-15:00)\n2 — ארוחת ערב מוקדמת (17:00-19:00)\n3 — שעות שיא (19:00-21:00)\n4 — ארוחת ערב מאוחרת (21:00-23:00)\nאו ציין שעה מדויקת"
    ),

    "q_special": Translation(
        ru="Есть особые пожелания?\n(детское кресло, аллергии, день рождения и т.п.)\nИли напишите «нет»",
        en="Any special requests?\n(child seat, allergies, birthday, etc.)\nOr write \"no\"",
        he="יש בקשות מיוחדות?\n(כיסא לילד, אלרגיות, יום הולדת וכו')\nאו כתוב \"לא\""
    ),

    "q_contact": Translation(
        ru="Оставьте контактный телефон для подтверждения",
        en="Leave a contact phone for confirmation",
        he="השאר טלפון ליצירת קשר לאישור"
    ),

    "done": Translation(
        ru="Отлично! Бронирование принято.\nМы подтвердим по телефону в течение часа. 👍",
        en="Great! Reservation accepted.\nWe'll confirm by phone within an hour. 👍",
        he="מעולה! ההזמנה התקבלה.\nנאשר בטלפון תוך שעה. 👍"
    ),
}


# ============================================================================
# CHOICE LABELS
# ============================================================================

CUISINE_LABELS = {
    CuisineType.ITALIAN.value: Translation(ru="итальянская", en="Italian", he="איטלקי"),
    CuisineType.ASIAN.value: Translation(ru="азиатская", en="Asian", he="אסייתי"),
    CuisineType.MEDITERRANEAN.value: Translation(ru="средиземноморская", en="Mediterranean", he="ים תיכוני"),
    CuisineType.STEAKHOUSE.value: Translation(ru="стейк-хаус", en="Steakhouse", he="סטייקים"),
    CuisineType.VEGETARIAN.value: Translation(ru="вегетарианская", en="Vegetarian", he="צמחוני"),
    CuisineType.ANY.value: Translation(ru="любая", en="Any", he="כל דבר"),
}

TIME_SLOT_LABELS = {
    TimeSlot.LUNCH.value: Translation(ru="обед (12-15)", en="lunch (12-3pm)", he="צהריים (12-15)"),
    TimeSlot.EARLY.value: Translation(ru="ранний ужин (17-19)", en="early dinner (5-7pm)", he="מוקדם (17-19)"),
    TimeSlot.PRIME.value: Translation(ru="прайм-тайм (19-21)", en="prime time (7-9pm)", he="שעות שיא (19-21)"),
    TimeSlot.LATE.value: Translation(ru="поздний (21-23)", en="late (9-11pm)", he="מאוחר (21-23)"),
}


# ============================================================================
# CHOICE MAPPINGS
# ============================================================================

CUISINE_CHOICES = {
    "1": CuisineType.ITALIAN.value,
    "2": CuisineType.ASIAN.value,
    "3": CuisineType.MEDITERRANEAN.value,
    "4": CuisineType.STEAKHOUSE.value,
    "5": CuisineType.VEGETARIAN.value,
    "6": CuisineType.ANY.value,
}

TIME_SLOT_CHOICES = {
    "1": TimeSlot.LUNCH.value,
    "2": TimeSlot.EARLY.value,
    "3": TimeSlot.PRIME.value,
    "4": TimeSlot.LATE.value,
}


# ============================================================================
# BOT CONFIGURATION
# ============================================================================

RESTAURANT_BOT_CONFIG = BotConfig(
    bot_id="restaurant_bot_v1",
    name=Translation(
        ru="Бот бронирования ресторанов",
        en="Restaurant Booking Bot",
        he="בוט להזמנת מסעדות"
    ),
    description=Translation(
        ru="Помогает забронировать столик в ресторане",
        en="Helps book restaurant tables",
        he="עוזר להזמין שולחנות במסעדה"
    ),

    # Flow configuration
    step_enum=RestaurantBotStep,
    initial_step=RestaurantBotStep.WELCOME.value,
    final_step=RestaurantBotStep.DONE.value,

    # Intent patterns
    intent_patterns=RESTAURANT_INTENT_PATTERNS,

    # Translations
    translations=RESTAURANT_TRANSLATIONS,

    # Choices
    choices={
        "cuisine": CUISINE_CHOICES,
        "time_slot": TIME_SLOT_CHOICES,
    },
    choice_labels={
        "cuisine": CUISINE_LABELS,
        "time_slot": TIME_SLOT_LABELS,
    },
)


# To activate this bot, add to app/core/bots/__init__.py:
# from app.core.bots.restaurant_bot_config import RESTAURANT_BOT_CONFIG
# BotRegistry.register("restaurant_bot_v1", RESTAURANT_BOT_CONFIG)
