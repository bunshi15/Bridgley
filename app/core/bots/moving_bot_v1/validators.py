# app/core/bots/moving_bot_v1/validators.py
"""
Input validators and intent detection for the Moving Bot.

Extracted from ``MovingBotHandler`` static methods so they can be
tested independently and reused across handler versions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

__all__ = [
    # Public API
    "norm", "lower",
    "sanitize_text", "looks_too_short",
    "detect_language",
    "parse_choices", "parse_extras_input",
    "parse_floor_info",
    "parse_date", "parse_exact_time",
    "extract_items",
    "detect_volume_from_rooms",
    "detect_intent",
    "LandingPrefill", "parse_landing_prefill",
    # Private — used by tests / other modules:
    "_parse_natural_date", "_validate_date_range", "_resolve_day_month",
    "_EXPLICIT_QTY_PATTERN", "_ATTR_SUFFIXES", "_BARE_QTY_PATTERN",
    "_QTY_SANITY_CAP", "_UNIT_STRIP", "_ITEM_SEPARATORS",
    "_JUNK_INPUTS",
    "_HEBREW_RE", "_CYRILLIC_RE", "_LATIN_RE", "_MIN_LETTERS_FOR_DETECTION",
    "_ELEVATOR_YES_PATTERNS", "_ELEVATOR_NO_PATTERNS",
    "_FLOOR_NUMBER_PATTERN", "_GROUND_PATTERNS",
    "_URL_RE", "_HTML_TAG_RE", "_SCRIPT_URI_RE", "_CONTROL_RE",
    "_MULTI_SPACE_RE", "_MAX_FIELD_LEN",
    "_RELATIVE_DAYS", "_WEEKDAY_NAMES", "_MONTH_NAMES",
    "_NEXT_PREFIX_RE", "_WEEKDAY_PREP_RE",
    "_RELATIVE_DAYS_SORTED", "_WEEKDAY_NAMES_SORTED", "_MONTH_NAMES_SORTED",
    "_TZ", "_MAX_DAYS_AHEAD",
    "_LANDING_SIGNATURE", "_LANDING_FIELDS", "_VALID_MOVE_TYPES", "_FIELD_MAX",
    "_ROOM_PATTERNS", "_ROOM_COUNT_TO_VOLUME",
]


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

def norm(s: str) -> str:
    """Strip whitespace from *s* (None-safe)."""
    return (s or "").strip()


def lower(s: str) -> str:
    """Normalise and lowercase *s*."""
    return norm(s).lower()


# ---------------------------------------------------------------------------
# Input sanitisation
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]{1,200}>")
_SCRIPT_URI_RE = re.compile(r"(?:javascript|vbscript|data)\s*:", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MAX_FIELD_LEN = 500


def sanitize_text(s: str, max_length: int = _MAX_FIELD_LEN) -> str:
    """Sanitise user text input.

    Strips HTML tags, URLs, ``javascript:``/``data:`` URIs, control
    characters and enforces a maximum length.  Legitimate printable text
    (including ``\\n``, ``\\r``, ``\\t``) is preserved.

    Returns the cleaned string.  Raises :class:`ValueError` with
    ``"rejected"`` when the *entire* input consists of stripped content
    (URLs, HTML, scripts) leaving nothing useful behind.
    """
    t = norm(s)
    if not t:
        return ""
    original_non_empty = True
    t = t[:max_length]
    t = _HTML_TAG_RE.sub("", t)
    t = _URL_RE.sub("", t)
    t = _SCRIPT_URI_RE.sub("", t)
    t = _CONTROL_RE.sub("", t)
    t = _MULTI_SPACE_RE.sub(" ", t).strip()
    if not t and original_non_empty:
        raise ValueError("rejected")
    return t


_JUNK_INPUTS: set[str] = {".", "..", "...", "ок", "ok", "ага", "да", "нет", "?"}


def looks_too_short(s: str, n: int) -> bool:
    """
    Return ``True`` if *s* is shorter than *n* characters **or** is a
    known low-information "junk" response (e.g. ``"ok"``, ``"да"``).
    """
    t = norm(s)
    if len(t) < n:
        return True
    return lower(t) in _JUNK_INPUTS


# ---------------------------------------------------------------------------
# Language detection (script-based heuristic — no API)
# ---------------------------------------------------------------------------

# Unicode ranges for script detection
_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")

# Minimum letter count to be confident — short inputs (< 3 letters) are
# ambiguous (could be a button choice, phone digit, etc.)
_MIN_LETTERS_FOR_DETECTION = 3


def detect_language(text: str) -> tuple[str | None, float]:
    """Detect user language from text using cheap script-based heuristics.

    Returns ``(lang, confidence)`` where *lang* is ``"he"``, ``"ru"``,
    ``"en"`` or ``None``, and *confidence* is 0.0–1.0.

    Rules:

    * Hebrew characters present -> ``"he"`` (Hebrew is unambiguous).
    * Cyrillic characters dominant -> ``"ru"``.
    * Latin characters dominant -> ``"en"``.
    * Numeric-only, very short, or no script letters -> ``(None, 0.0)``.
    """
    if not text:
        return None, 0.0

    t = text.strip()

    # Count script letters (ignoring digits, punctuation, spaces)
    he_count = len(_HEBREW_RE.findall(t))
    cyr_count = len(_CYRILLIC_RE.findall(t))
    lat_count = len(_LATIN_RE.findall(t))

    total_letters = he_count + cyr_count + lat_count

    # Too few letters -> skip detection (button press, phone, etc.)
    if total_letters < _MIN_LETTERS_FOR_DETECTION:
        return None, 0.0

    # Hebrew is highest priority (unique script, unambiguous)
    if he_count > 0:
        return "he", min(he_count / total_letters + 0.3, 1.0)

    # Cyrillic dominant
    if cyr_count > lat_count:
        return "ru", min(cyr_count / total_letters + 0.2, 1.0)

    # Latin dominant
    if lat_count > cyr_count:
        return "en", min(lat_count / total_letters + 0.2, 1.0)

    return None, 0.0


# ---------------------------------------------------------------------------
# Choice parsing
# ---------------------------------------------------------------------------

def parse_choices(s: str) -> set[str]:
    """Extract numeric choice digits (1-4) from *s*."""
    t = lower(s)
    return {ch for ch in t if ch in {"1", "2", "3", "4"}}


def parse_extras_input(s: str) -> tuple[set[str], Optional[str]]:
    """
    Parse the EXTRAS step input — supports numbers, free text, or both.

    Input formats::

        "1 3"              -> choices={1,3}, details=None
        "5 этаж без лифта" -> choices={},   details="5 этаж без лифта"
        "1 3 + 5 этаж"    -> choices={1,3}, details="5 этаж"
        "1, 3, срочно"    -> choices={1,3}, details="срочно"
        "1 и 2 и нужен лифт" -> choices={1,2}, details="нужен лифт"

    Returns:
        ``(choices, details)`` where *choices* is a set of digit strings
        and *details* is an optional free-text comment.
    """
    text = norm(s)
    if not text:
        return set(), None

    # Try to split by explicit separators
    separators = [
        r'\s*\+\s*',           # "1 3 + text"
        r'\s*,\s*(?=[^\d])',   # "1, 3, text"
        r'\s+и\s+(?=[^\d])',   # "1 и 2 и text"
        r'\s+and\s+(?=[^\d])', # "1 and 2 and text"
        r'\s+также\s+',        # "1 2 также text"
    ]

    for sep_pattern in separators:
        match = re.search(sep_pattern, text, re.IGNORECASE)
        if match:
            before = text[:match.start()].strip()
            after = text[match.end():].strip()
            choices_before = {ch for ch in before if ch in "1234"}
            if choices_before and after:
                return choices_before, after

    # Pure numeric input ("1 3", "1,2,3")
    clean = re.sub(r'[,\s]+', '', text)
    if clean and all(ch in "1234" for ch in clean):
        return {ch for ch in clean if ch in "1234"}, None

    # Numbers followed by text ("1 3 пятый этаж")
    match = re.match(r'^([1-4](?:\s*[,\s]\s*[1-4])*)\s+(.+)$', text)
    if match:
        nums_part = match.group(1)
        text_part = match.group(2).strip()
        choices = {ch for ch in nums_part if ch in "1234"}
        if choices and text_part and not text_part[0].isdigit():
            return choices, text_part

    # Fallback: look for any valid digit choices
    all_choices = {ch for ch in text if ch in "1234"}
    non_numeric = re.sub(r'[1-4\s,]+', '', text).strip()
    if all_choices and len(non_numeric) > 3:
        if not re.match(r'^[1-4]', text):
            return set(), text

    if all_choices:
        return all_choices, None

    return set(), text if text else None


# ---------------------------------------------------------------------------
# Floor / elevator parsing (Phase 3 — pricing estimate)
# ---------------------------------------------------------------------------

_ELEVATOR_YES_PATTERNS = re.compile(
    r"(?:лифт\s*(?:есть|работает|да))|"
    r"(?:есть\s*лифт)|"
    r"(?:elevator\s*(?:yes|available|works))|"
    r"(?:yes\s*elevator)|"
    r"(?:יש\s*מעלית)|"
    r"(?:מעלית\s*(?:יש|עובדת|כן))",
    re.IGNORECASE,
)

_ELEVATOR_NO_PATTERNS = re.compile(
    r"(?:без\s*лифта)|"
    r"(?:лифта\s*нет)|"
    r"(?:нет\s*лифта)|"
    r"(?:no\s*elevator)|"
    r"(?:without\s*elevator)|"
    r"(?:elevator\s*(?:no|none))|"
    r"(?:בלי\s*מעלית)|"
    r"(?:אין\s*מעלית)",
    re.IGNORECASE,
)

_FLOOR_NUMBER_PATTERN = re.compile(
    r"(?:(\d{1,2})\s*(?:этаж|эт|floor|fl|קומה))|"
    r"(?:(?:этаж|эт|floor|fl|קומה)\s*(\d{1,2}))|"
    r"^(\d{1,2})$",
    re.IGNORECASE,
)

_GROUND_PATTERNS = re.compile(
    r"(?:(?:частный\s*дом)|(?:private\s*house)|(?:בית\s*פרטי)|(?:ground))",
    re.IGNORECASE,
)


def parse_floor_info(text: str) -> tuple[int, bool]:
    """
    Extract floor number and elevator presence from free-text input.

    Returns ``(floor_number, has_elevator)``.

    Heuristics:
    - Looks for explicit floor numbers (``"3 этаж"``, ``"floor 5"``).
    - Looks for elevator keywords (``"лифт есть"``, ``"без лифта"``).
    - If "private house" / ``"частный дом"`` is detected, returns ``(1, True)``.
    - Defaults: floor=1, has_elevator=True (ground level, safe default).
    """
    t = norm(text)
    if not t:
        return 1, True

    # Ground / private house -> floor 1, elevator yes (no surcharge)
    if _GROUND_PATTERNS.search(t):
        return 1, True

    # Floor number
    floor = 1
    m = _FLOOR_NUMBER_PATTERN.search(t)
    if m:
        floor = int(m.group(1) or m.group(2) or m.group(3))

    # Elevator
    has_elevator = True  # default: assume elevator
    if _ELEVATOR_NO_PATTERNS.search(t):
        has_elevator = False
    elif _ELEVATOR_YES_PATTERNS.search(t):
        has_elevator = True

    return floor, has_elevator


# ---------------------------------------------------------------------------
# Date / time parsing (Phase 2 — structured scheduling)
# ---------------------------------------------------------------------------

from datetime import date, timedelta, datetime as _dt
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Jerusalem")
_MAX_DAYS_AHEAD = 60


# ---------------------------------------------------------------------------
# Natural date parsing helpers (Phase 15)
# ---------------------------------------------------------------------------

# Relative day keywords -> offset from today
_RELATIVE_DAYS: dict[str, int] = {
    # Russian
    "сегодня": 0,
    "завтра": 1,
    "послезавтра": 2,
    # English
    "today": 0,
    "tomorrow": 1,
    "day after tomorrow": 2,
    # Hebrew
    "היום": 0,
    "מחר": 1,
    "מחרתיים": 2,
}

# Weekday names -> weekday index (0=Monday)
_WEEKDAY_NAMES: dict[str, int] = {
    # Russian
    "понедельник": 0, "пн": 0,
    "вторник": 1, "вт": 1,
    "среда": 2, "ср": 2, "среду": 2,
    "четверг": 3, "чт": 3,
    "пятница": 4, "пт": 4, "пятницу": 4,
    "суббота": 5, "сб": 5, "субботу": 5,
    "воскресенье": 6, "вс": 6,
    # English
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
    # Hebrew
    "שני": 0, "יום שני": 0,
    "שלישי": 1, "יום שלישי": 1,
    "רביעי": 2, "יום רביעי": 2,
    "חמישי": 3, "יום חמישי": 3,
    "שישי": 4, "יום שישי": 4,
    "שבת": 5,
    "ראשון": 6, "יום ראשון": 6,
}

# Month names -> month number (1-based)
_MONTH_NAMES: dict[str, int] = {
    # Russian
    "января": 1, "январь": 1, "янв": 1,
    "февраля": 2, "февраль": 2, "фев": 2,
    "марта": 3, "март": 3, "мар": 3,
    "апреля": 4, "апрель": 4, "апр": 4,
    "мая": 5, "май": 5,
    "июня": 6, "июнь": 6, "июн": 6,
    "июля": 7, "июль": 7, "июл": 7,
    "августа": 8, "август": 8, "авг": 8,
    "сентября": 9, "сентябрь": 9, "сен": 9, "сент": 9,
    "октября": 10, "октябрь": 10, "окт": 10,
    "ноября": 11, "ноябрь": 11, "ноя": 11,
    "декабря": 12, "декабрь": 12, "дек": 12,
    # English
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
    # Hebrew
    "ינואר": 1,
    "פברואר": 2,
    "מרץ": 3, "מרס": 3,
    "אפריל": 4,
    "מאי": 5,
    "יוני": 6,
    "יולי": 7,
    "אוגוסט": 8,
    "ספטמבר": 9,
    "אוקטובר": 10,
    "נובמבר": 11,
    "דצמבר": 12,
}

# "next" prefix patterns — match only non-empty "next week" prefixes
_NEXT_PREFIX_RE = re.compile(
    r"^(?:(?:в\s+)?следующ(?:ий|ую|ее)\s+|"
    r"next\s+|"
    r"(?:ב\s*)?שבוע\s+הבא\s+)", re.IGNORECASE
)

# Simple preposition before weekday ("в среду", "on Friday", "ביום")
_WEEKDAY_PREP_RE = re.compile(
    r"^(?:в\s+|on\s+|ב\s*)", re.IGNORECASE
)

# Sort longest-first for matching
_RELATIVE_DAYS_SORTED = sorted(_RELATIVE_DAYS.items(), key=lambda kv: -len(kv[0]))
_WEEKDAY_NAMES_SORTED = sorted(_WEEKDAY_NAMES.items(), key=lambda kv: -len(kv[0]))
_MONTH_NAMES_SORTED = sorted(_MONTH_NAMES.items(), key=lambda kv: -len(kv[0]))


def _parse_natural_date(text: str, *, tz: ZoneInfo = _TZ) -> date | None:
    """Parse a natural language date string.

    Supports:
    - Relative: "завтра", "послезавтра", "tomorrow", "מחר"
    - Weekday: "в пятницу", "next Friday", "יום שישי"
    - Day + month name: "20 февраля", "March 5", "15 ינואר"

    Returns ``None`` if no pattern matches. Does NOT validate
    the date against too_soon/too_far boundaries — the caller should do that.
    """
    t = norm(text).lower()
    if not t:
        return None

    today = _dt.now(tz).date()

    # 1. Relative day keywords (longest-first)
    for keyword, offset in _RELATIVE_DAYS_SORTED:
        if t == keyword or t.startswith(keyword):
            return today + timedelta(days=offset)

    # 2. Weekday — with optional "next" or simple preposition prefix
    is_next = False
    t_clean = t
    m_next = _NEXT_PREFIX_RE.match(t)
    if m_next:
        is_next = True
        t_clean = t[m_next.end():].strip()
    else:
        # Simple preposition ("в среду", "on Friday")
        m_prep = _WEEKDAY_PREP_RE.match(t)
        if m_prep:
            t_clean = t[m_prep.end():].strip()

    for weekday_name, weekday_idx in _WEEKDAY_NAMES_SORTED:
        if t_clean == weekday_name or t_clean.startswith(weekday_name):
            # Calculate next occurrence of this weekday
            today_wd = today.weekday()
            days_ahead = (weekday_idx - today_wd) % 7
            if days_ahead == 0:
                days_ahead = 7  # same weekday -> next week
            if is_next:
                days_ahead += 7  # "next Friday" -> skip this week
            return today + timedelta(days=days_ahead)

    # 3. Day + month name: "20 февраля", "March 5", "15 ינואר"
    # Pattern A: DD month_name
    for month_name, month_num in _MONTH_NAMES_SORTED:
        # "20 февраля"
        pat_a = re.match(rf"(\d{{1,2}})\s+{re.escape(month_name)}\b", t)
        if pat_a:
            day = int(pat_a.group(1))
            return _resolve_day_month(day, month_num, today)

        # "February 20" / "March 5th"
        pat_b = re.match(rf"{re.escape(month_name)}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", t)
        if pat_b:
            day = int(pat_b.group(1))
            return _resolve_day_month(day, month_num, today)

    return None


def _resolve_day_month(day: int, month: int, today: date) -> date:
    """Resolve DD+month to a date, rolling to next year if already passed."""
    year = today.year
    try:
        result = date(year, month, day)
    except ValueError:
        raise ValueError("invalid_date")
    if result <= today:
        try:
            result = date(year + 1, month, day)
        except ValueError:
            raise ValueError("invalid_date")
    return result


def parse_date(text: str, *, tz: ZoneInfo = _TZ) -> date:
    """
    Parse a date from user input — supports DD.MM, DD.MM.YYYY,
    and natural language (Phase 15).

    Also accepts ``/`` and ``-`` as separators for DD.MM formats.

    Raises :class:`ValueError` with one of:
    ``"format"``  — unrecognised format
    ``"invalid_date"`` — non-existent calendar date (e.g. 31 Feb)
    ``"too_soon"``  — date is earlier than tomorrow
    ``"too_far"``  — date is more than 60 days out
    """
    cleaned = norm(text).replace("/", ".").replace("-", ".")

    # Try DD.MM.YYYY first
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", cleaned)
    has_year = m is not None
    if not m:
        # Try DD.MM (no year)
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", cleaned)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        today = _dt.now(tz).date()

        if has_year:
            year = int(m.group(3))
        else:
            year = today.year

        try:
            result = date(year, month, day)
        except ValueError:
            raise ValueError("invalid_date")

        # DD.MM without year: if the date already passed, roll to next year
        if not has_year and result <= today:
            try:
                result = date(year + 1, month, day)
            except ValueError:
                raise ValueError("invalid_date")

        return _validate_date_range(result, tz)

    # Try natural language date (Phase 15)
    natural = _parse_natural_date(text, tz=tz)
    if natural is not None:
        return _validate_date_range(natural, tz)

    raise ValueError("format")


def _validate_date_range(result: date, tz: ZoneInfo = _TZ) -> date:
    """Validate that a parsed date is within acceptable range."""
    today = _dt.now(tz).date()
    tomorrow = today + timedelta(days=1)
    if result < tomorrow:
        raise ValueError("too_soon")

    max_date = today + timedelta(days=_MAX_DAYS_AHEAD)
    if result > max_date:
        raise ValueError("too_far")

    return result


def parse_exact_time(text: str) -> str:
    """
    Parse ``HH:MM`` (24-hour) from user input.

    Also accepts ``.`` as separator (``14.30`` -> ``14:30``).

    Returns normalised ``"HH:MM"`` string.
    Raises :class:`ValueError` on invalid input.
    """
    cleaned = norm(text).replace(".", ":").replace("-", ":")
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", cleaned)
    if not m:
        raise ValueError("format")

    hour, minute = int(m.group(1)), int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("invalid_time")

    return f"{hour:02d}:{minute:02d}"


# ---------------------------------------------------------------------------
# Item extraction from cargo descriptions (Phase 10)
# ---------------------------------------------------------------------------

# Separator pattern for splitting cargo descriptions into fragments
_ITEM_SEPARATORS = re.compile(
    r"[,\n]+|"        # commas, newlines
    r"\s+и\s+|"       # Russian "и" (and)
    r"\s+and\s+|"     # English "and"
    r"\s*\+\s*",      # plus sign
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Quantity detection (EPIC D1 — attribute-safe)
# ---------------------------------------------------------------------------
#
# Quantity is recognised ONLY via explicit markers:
#   x5 / 5x / 5 шт / 5 штук / 5 pcs / 5 pieces / qty:5 / qty=5
# All other digits in the remainder are treated as attributes
# (e.g. "5 дверный", "200кг", "615л") and must NOT affect qty.
#
# Sanity cap: parsed qty > 20 without an explicit marker -> 1.
# ---------------------------------------------------------------------------

# Explicit quantity markers (order matters: longest first isn't needed here,
# but we anchor each alternative carefully).
_EXPLICIT_QTY_PATTERN = re.compile(
    r"(?:"
    r"(\d+)\s*[xх×]"           # "5x", "5х", "5×"  (number before x)
    r"|[xх×]\s*(\d+)"          # "x5", "х5", "×5"  (x before number)
    r"|(\d+)\s*(?:шт\.?|штук)" # "5 шт", "5шт.", "5 штук"
    r"|(\d+)\s*(?:pcs|pieces)" # "5 pcs", "5 pieces"
    r"|qty\s*[:=]\s*(\d+)"     # "qty:5", "qty=5"
    r")",
    re.IGNORECASE,
)

# Attribute-like patterns that suppress bare-number qty detection.
# If the remainder contains a number adjacent to any of these suffixes,
# the number is an attribute (doors, weight, volume, dimensions), not qty.
_ATTR_SUFFIXES = re.compile(
    r"\d+[\s\-]*(?:"
    r"двер|door"              # doors: "5-дверный", "5 door", "5дверный"
    r"|кг|kg"                 # weight
    r"|г\b|g\b"               # grams (word boundary to avoid false hits)
    r"|л\b|l\b|литр|liter"    # liters
    r"|см|cm|мм|mm|м\b|m\b"  # dimensions (cm, mm, m)
    r")",
    re.IGNORECASE,
)

# Bare number fallback (used only when no explicit marker and no attributes)
_BARE_QTY_PATTERN = re.compile(r"(\d+)")

# Max reasonable qty without an explicit marker (sanity cap)
_QTY_SANITY_CAP = 20

# Unit words between quantity and item: "5 шт коробок", "5шт. коробок", "5 штук коробок"
_UNIT_STRIP = re.compile(r"(\d+)\s*(?:шт\.?|штук)\s*", re.IGNORECASE)


def extract_items(
    text: str,
    alias_lookup: dict[str, str] | None = None,
) -> list[dict]:
    """Extract structured items from a cargo description.

    Best-effort extraction — unknown words are silently ignored.
    Returns a list of ``{"key": canonical_key, "qty": int}`` dicts.

    Handles:
    - Multilingual aliases (RU/EN/HE) via ``ITEM_ALIAS_LOOKUP``
    - Quantities: ``"5 коробок"``, ``"boxes 3"``, ``"3 קרטונים"``
    - Multi-word aliases: ``"стиральная машина"``, ``"dining table"``
    - Deduplication: same key -> quantities summed
    """
    if alias_lookup is None:
        from app.core.bots.moving_bot_v1.pricing import ITEM_ALIAS_LOOKUP
        alias_lookup = ITEM_ALIAS_LOOKUP

    if not text or not alias_lookup:
        return []

    # Split into fragments by separators
    fragments = _ITEM_SEPARATORS.split(text.strip())

    # Accumulate: canonical_key -> total qty
    found: dict[str, int] = {}

    for fragment in fragments:
        fragment = fragment.strip().lower()
        if not fragment:
            continue

        # Normalize unit words: "5 шт коробок" -> "5 коробок"
        fragment = _UNIT_STRIP.sub(r"\1 ", fragment).strip()

        # Try to find a matching alias (longest-first from sorted lookup)
        matched_key = None
        for alias, canonical_key in alias_lookup.items():
            if alias in fragment:
                matched_key = canonical_key
                # Remove the alias from fragment to isolate quantity
                remainder = fragment.replace(alias, "", 1).strip()
                break

        if matched_key is None:
            continue  # no match — skip

        # Extract quantity from the remainder (text left after removing alias)
        qty = 1
        if remainder:
            # 1) Try explicit markers first (x5, 5шт, qty:5, etc.)
            explicit_match = _EXPLICIT_QTY_PATTERN.search(remainder)
            if explicit_match:
                # Groups are mutually exclusive; pick the one that matched
                raw = next(g for g in explicit_match.groups() if g is not None)
                parsed_qty = int(raw)
                if parsed_qty > 0:
                    qty = parsed_qty
            else:
                # 2) Check for attribute-like numbers -> suppress qty
                if not _ATTR_SUFFIXES.search(remainder):
                    # 3) Bare number fallback with sanity cap
                    bare_match = _BARE_QTY_PATTERN.search(remainder)
                    if bare_match:
                        parsed_qty = int(bare_match.group(1))
                        if 0 < parsed_qty <= _QTY_SANITY_CAP:
                            qty = parsed_qty

        # Accumulate
        found[matched_key] = found.get(matched_key, 0) + qty

    return [{"key": k, "qty": v} for k, v in found.items()]


# ---------------------------------------------------------------------------
# Room-based volume auto-detection (Phase 12)
# ---------------------------------------------------------------------------

# Room keyword patterns — multilingual (RU/EN/HE)
# Each tuple: (compiled_regex, room_type)
_ROOM_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Studio (immediate -> "small")
    (re.compile(r"(?:студи[оя]|studio|סטודיו)", re.IGNORECASE), "studio"),
    # N-room apartment — "3-комнатная квартира", "4 комнатная", "3 room apartment"
    (re.compile(r"(\d+)\s*[-–]?\s*(?:комнатн|room\s*apart)", re.IGNORECASE), "apartment_rooms"),
    # Bedrooms — "3 спальни", "2 bedrooms", "3 חדרי שינה"
    (re.compile(r"(\d+)\s*(?:спальн|bedroom)", re.IGNORECASE), "bedroom"),
    (re.compile(r"(\d+)\s*חדר(?:י|ей)?\s*שינה", re.IGNORECASE), "bedroom"),
    # Generic rooms — "3 комнаты", "2 rooms", "3 חדרים"
    (re.compile(r"(\d+)\s*комнат", re.IGNORECASE), "room"),
    (re.compile(r"(\d+)\s*rooms?\b", re.IGNORECASE), "room"),
    (re.compile(r"(\d+)\s*חדרים", re.IGNORECASE), "room"),
    # Living room / salon (counts as 1 major room)
    (re.compile(r"(?:салон|гостин|living\s*room|סלון)", re.IGNORECASE), "living"),
    # Kitchen (minor — detected but NOT counted)
    (re.compile(r"(?:кухн|kitchen|מטבח)", re.IGNORECASE), "kitchen"),
]

# Volume mapping: room_count -> volume_category
_ROOM_COUNT_TO_VOLUME: dict[int, str] = {
    1: "small",
    2: "medium",
    3: "large",
}
# 4+ rooms -> "xl"


def detect_volume_from_rooms(text: str) -> str | None:
    """Detect volume category from room keywords in cargo text.

    Scans for room-related keywords in Russian, English, and Hebrew.
    Returns ``"small"``, ``"medium"``, ``"large"``, ``"xl"``
    or ``None`` if no room keywords found.

    Priority: studio > N-room apartment > individual room counting.
    Bedrooms + living rooms count; kitchens/bathrooms do not.
    """
    if not text:
        return None

    t = text.lower()

    # 1. Studio check (highest priority, immediate)
    for pattern, room_type in _ROOM_PATTERNS:
        if room_type == "studio" and pattern.search(t):
            return "small"

    # 2. N-room apartment (self-contained count, immediate return)
    for pattern, room_type in _ROOM_PATTERNS:
        if room_type == "apartment_rooms":
            m = pattern.search(t)
            if m:
                count = int(m.group(1))
                return _ROOM_COUNT_TO_VOLUME.get(count, "xl")

    # 3. Count individual room mentions
    major_room_count = 0
    found_any = False

    for pattern, room_type in _ROOM_PATTERNS:
        if room_type in ("bedroom", "room"):
            m = pattern.search(t)
            if m:
                count = int(m.group(1))
                major_room_count += count
                found_any = True
        elif room_type == "living":
            if pattern.search(t):
                major_room_count += 1
                found_any = True

    if not found_any or major_room_count <= 0:
        return None

    return _ROOM_COUNT_TO_VOLUME.get(major_room_count, "xl")


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def detect_intent(text: str) -> str | None:
    """
    Detect user intent using ``MOVING_BOT_CONFIG.intent_patterns``.

    Returns:
        ``"reset"``, ``"done_photos"``, ``"no"`` or ``None``.
    """
    from app.core.bots.moving_bot_v1.config import MOVING_BOT_CONFIG
    from app.core.engine.bot_types import Intent, detect_universal_intent

    intent = detect_universal_intent(text, MOVING_BOT_CONFIG.intent_patterns)
    if intent is None:
        return None

    _MAP = {
        Intent.RESET: "reset",
        Intent.CONFIRM: "done_photos",
        Intent.DECLINE: "no",
    }
    return _MAP.get(intent)


# ---------------------------------------------------------------------------
# Landing page pre-fill parsing
# ---------------------------------------------------------------------------

@dataclass
class LandingPrefill:
    """Parsed fields from a landing page pre-fill message."""

    move_type: str | None = None
    addr_from: str | None = None
    addr_to: str | None = None
    date_text: str | None = None
    details: str | None = None


_LANDING_SIGNATURE = "здравствуйте! хочу узнать стоимость переезда."

_LANDING_FIELDS: dict[str, str] = {
    "тип:": "move_type",
    "откуда:": "addr_from",
    "куда:": "addr_to",
    "дата:": "date_text",
    "детали:": "details",
}

_VALID_MOVE_TYPES: set[str] = {
    "квартира",
    "офис",
    "только машина + водитель",
    "подъёмник / window lift",
}

# Per-field max lengths for sanitisation
_FIELD_MAX: dict[str, int] = {
    "move_type": 100,
    "addr_from": 200,
    "addr_to": 200,
    "date_text": 100,
    "details": 500,
}


def parse_landing_prefill(text: str) -> LandingPrefill | None:
    """Detect and parse a landing page pre-fill message.

    The landing form builds a structured WhatsApp message whose first
    line matches :data:`_LANDING_SIGNATURE`.  Subsequent lines carry
    ``"Key: value"`` pairs.

    Returns a :class:`LandingPrefill` with parsed (and individually
    sanitised) field values, or ``None`` if the message does not match
    the landing signature.
    """
    try:
        cleaned = sanitize_text(text, max_length=2000)
    except ValueError:
        return None

    if not cleaned:
        return None

    lines = cleaned.split("\n")
    first_line = lines[0].strip().lower()

    # Must start with the exact landing greeting
    if not first_line.startswith(_LANDING_SIGNATURE):
        return None

    result = LandingPrefill()

    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        stripped_lower = stripped.lower()

        for prefix, attr in _LANDING_FIELDS.items():
            if stripped_lower.startswith(prefix):
                raw_value = stripped[len(prefix):].strip()
                if not raw_value:
                    break
                # Sanitise each field value individually
                try:
                    safe_value = sanitize_text(raw_value, max_length=_FIELD_MAX.get(attr, 200))
                except ValueError:
                    # Entire field was a payload — discard
                    break
                if not safe_value:
                    break
                setattr(result, attr, safe_value)
                break

    # Validate move_type against allowlist
    if result.move_type and result.move_type.lower() not in _VALID_MOVE_TYPES:
        result.move_type = None

    return result
