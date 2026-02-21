# app/core/bots/moving_bot_v1/localities.py
"""
Israeli locality dataset — static JSON loader + normalized lookup.

Loads ``data/localities.json`` at import time and builds
a normalized name->Locality lookup for Hebrew, English, and Russian names.

Used by the route-band classifier (``geo.classify_route``)
to resolve free-text addresses to known localities without any external API.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Locality",
    "LOCALITIES",
    "LOCALITY_BY_CODE",
    "LOCALITY_LOOKUP",
    "find_locality",
    # Private but used by tests:
    "_normalize_name",
    "_RU_ALIASES",
    "_load_localities",
    "_load_ru_aliases",
    "_build_lookup",
    "_is_word_boundary",
    "_NAME_ALIASES",
    "_BOUNDARY_CHARS",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Locality:
    """A single Israeli locality from CBS data."""

    code: int
    he: str
    en: str | None
    ru: str | None
    region: int


# ---------------------------------------------------------------------------
# Load JSON dataset (once at import time)
# ---------------------------------------------------------------------------

_LOCALITIES_PATH = Path(__file__).parent / "data" / "localities.json"
_RU_ALIASES_PATH = Path(__file__).parent / "data" / "localities_ru_aliases.auto.json"


def _load_localities() -> list[Locality]:
    """Load locality dataset from JSON file."""
    with open(_LOCALITIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    result: list[Locality] = []
    for entry in data["localities"]:
        result.append(Locality(
            code=entry["code"],
            he=entry["he"],
            en=entry.get("en"),
            ru=entry.get("ru"),
            region=entry["region"],
        ))
    return result


def _load_ru_aliases() -> dict[str, int]:
    """Load extra RU aliases (variant spellings) -> locality code."""
    if not _RU_ALIASES_PATH.exists():
        return {}
    with open(_RU_ALIASES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Accept either {"alias": 1234} or {"alias": "1234"}
    out: dict[str, int] = {}
    for k, v in data.items():
        try:
            out[str(k)] = int(v)
        except Exception:
            continue
    return out


LOCALITIES: list[Locality] = _load_localities()
LOCALITY_BY_CODE: dict[int, Locality] = {loc.code: loc for loc in LOCALITIES}
_RU_ALIASES: dict[str, int] = _load_ru_aliases()


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

# Characters to strip during normalization
_STRIP_CHARS_RE = re.compile(r"[\"'`\u2018\u2019\u201c\u201d\u05f3\u05f4().]")
# Collapse whitespace
_MULTI_WS_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    """Normalize a locality name for lookup.

    - Lowercase
    - Normalize hyphens/dashes to a single hyphen
    - Remove quotes, apostrophes, parentheses, periods
    - Collapse whitespace

    Note: we do NOT strip combining marks via NFD decomposition
    because Cyrillic ``й`` (и + combining breve) and Hebrew nikud
    would be corrupted.  Instead, we just lowercase and strip
    punctuation — this is sufficient for our use case.
    """
    if not name:
        return ""
    t = name.lower()
    t = t.replace("ё", "е")
    # Normalize various dashes to hyphen
    t = t.replace("–", " ").replace("—", " ").replace("\u2011", " ").replace("-", " ")
    # Strip quotes, apostrophes, parentheses, periods
    t = _STRIP_CHARS_RE.sub("", t)
    # Collapse whitespace
    t = _MULTI_WS_RE.sub(" ", t).strip()
    return t


# ---------------------------------------------------------------------------
# Build lookup index
# ---------------------------------------------------------------------------

# Common short-form aliases for cities whose official CBS name includes
# an extra qualifier (e.g. "TEL AVIV - YAFO" -> "Tel Aviv").
# Maps alias -> city_code.
_NAME_ALIASES: dict[str, int] = {
    "tel aviv": 5000,
    "тель авив": 5000,
    "תל אביב": 5000,
    "beer sheva": 9000,
    "be'er sheva": 9000,
    "באר שבע": 9000,
    "rishon lezion": 8300,
    "rishon le-zion": 8300,
    "ришон ле-цион": 8300,
    "ראשון לציון": 8300,
    "petah tikva": 7900,
    "פתח תקוה": 7900,
    "kiryat ata": 6800,
    "kiryat bialik": 9500,
    "kiryat motzkin": 8200,
    "kiryat yam": 9600,
    "kiryat shmona": 2800,
    "kiryat gat": 2630,
    "kiryat ono": 2620,
    "eilat": 2600,
    "beit shemesh": 2610,
    "bat yam": 6200,
    "bnei brak": 6100,
    "kfar saba": 6900,
    "ramat gan": 8600,
    "ramat hasharon": 2650,
    "rosh haayin": 2640,
    "migdal haemek": 874,
    "nof hagalil": 1061,
    "modiin": 1200,
    "or akiva": 1020,
}


def _build_lookup(
    localities: list[Locality],
    ru_aliases: dict[str, int] | None = None,
) -> dict[str, Locality]:
    """Build a normalized-name -> Locality lookup.

    For each locality, index all non-empty names (he, en, ru).
    Also adds common aliases (short forms, transliterations) and
    auto-generated Russian variant spellings from ``ru_aliases``.
    On collision, the first entry wins (no duplicates expected).
    Returned dict is sorted longest-key-first so that multi-word names
    match before shorter substrings.
    """
    raw: dict[str, Locality] = {}
    code_to_loc = {loc.code: loc for loc in localities}

    for loc in localities:
        for name in (loc.he, loc.en, loc.ru):
            if not name:
                continue
            key = _normalize_name(name)
            if not key or len(key) < 2:
                continue  # skip degenerate names
            if key not in raw:
                raw[key] = loc

    # Add manual short-form aliases
    for alias, code in _NAME_ALIASES.items():
        key = _normalize_name(alias)
        if key and key not in raw and code in code_to_loc:
            raw[key] = code_to_loc[code]

    # Add auto-generated Russian aliases (variant spellings)
    if ru_aliases:
        for alias, code in ru_aliases.items():
            key = _normalize_name(alias)
            if key and len(key) >= 2 and key not in raw and code in code_to_loc:
                raw[key] = code_to_loc[code]

    # Sort longest-first for greedy matching
    return dict(sorted(raw.items(), key=lambda kv: -len(kv[0])))


LOCALITY_LOOKUP: dict[str, Locality] = _build_lookup(LOCALITIES, ru_aliases=_RU_ALIASES)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Word-boundary characters (space, comma, hyphen, start/end)
_BOUNDARY_CHARS = frozenset(" ,-/")


def _is_word_boundary(text: str, start: int, end: int) -> bool:
    """Check if a substring match is at word boundaries.

    A match is considered word-boundary-aligned if the character
    before ``start`` and after ``end`` is either a boundary char
    or a string edge.
    """
    if start > 0 and text[start - 1] not in _BOUNDARY_CHARS:
        return False
    if end < len(text) and text[end] not in _BOUNDARY_CHARS:
        return False
    return True


def find_locality(text: str) -> Locality | None:
    """Find the best-matching locality in a text string.

    Scans the normalized lookup for the longest matching substring.
    Requires word-boundary alignment to prevent false positives
    (e.g. "רחוב" matching locality "REHOV").

    Returns ``None`` if no known city name is found.

    Examples::

        find_locality("Хайфа, ул. Герцль 10")  -> Locality(code=4000, ...)
        find_locality("Haifa")                   -> Locality(code=4000, ...)
        find_locality("חיפה")                    -> Locality(code=4000, ...)
        find_locality("random gibberish")        -> None
    """
    if not text:
        return None
    normalized = _normalize_name(text)
    if not normalized:
        return None

    # Longest-first scan: check if lookup key appears in normalized text
    for key, loc in LOCALITY_LOOKUP.items():
        idx = normalized.find(key)
        if idx >= 0 and _is_word_boundary(normalized, idx, idx + len(key)):
            return loc

    return None
