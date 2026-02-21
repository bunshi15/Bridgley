# tests/test_localities.py
"""
Tests for the locality dataset and lookup module (Phase 1).
"""
from __future__ import annotations

import pytest
from app.core.bots.moving_bot_localities import (
    Locality,
    LOCALITIES,
    LOCALITY_BY_CODE,
    LOCALITY_LOOKUP,
    find_locality,
    _normalize_name,
    _RU_ALIASES,
)


# ============================================================================
# Dataset loading
# ============================================================================

class TestLocalityDataset:
    """Verify the localities.json dataset loads correctly."""

    def test_dataset_not_empty(self):
        assert len(LOCALITIES) > 1000

    def test_dataset_has_expected_count(self):
        """CBS dataset should have ~1298 localities."""
        assert 1200 <= len(LOCALITIES) <= 1400

    def test_locality_by_code_populated(self):
        assert len(LOCALITY_BY_CODE) == len(LOCALITIES)

    def test_haifa_exists(self):
        loc = LOCALITY_BY_CODE.get(4000)
        assert loc is not None
        assert loc.he == "חיפה"
        assert loc.en == "HAIFA"
        assert loc.ru == "Хайфа"
        assert loc.region == 31

    def test_tel_aviv_exists(self):
        loc = LOCALITY_BY_CODE.get(5000)
        assert loc is not None
        assert loc.he == "תל אביב - יפו"
        assert loc.ru == "Тель-Авив"
        assert loc.region == 51

    def test_jerusalem_exists(self):
        loc = LOCALITY_BY_CODE.get(3000)
        assert loc is not None
        assert loc.he == "ירושלים"
        assert loc.ru == "Иерусалим"
        assert loc.region == 11

    def test_beer_sheva_exists(self):
        loc = LOCALITY_BY_CODE.get(9000)
        assert loc is not None
        assert loc.region == 62

    def test_eilat_exists(self):
        loc = LOCALITY_BY_CODE.get(2600)
        assert loc is not None
        assert loc.ru == "Эйлат"
        assert loc.region == 62

    def test_all_localities_have_hebrew_name(self):
        for loc in LOCALITIES:
            assert loc.he, f"Locality {loc.code} has no Hebrew name"

    def test_all_localities_have_region(self):
        for loc in LOCALITIES:
            assert loc.region > 0, f"Locality {loc.code} has region=0"


# ============================================================================
# Name normalization
# ============================================================================

class TestNormalizeName:
    """Tests for the _normalize_name() function."""

    def test_lowercase(self):
        assert _normalize_name("HAIFA") == "haifa"

    def test_hebrew_unchanged(self):
        assert _normalize_name("חיפה") == "חיפה"

    def test_russian_lowercase(self):
        assert _normalize_name("Хайфа") == "хайфа"

    def test_strip_quotes(self):
        assert _normalize_name("BE'ER SHEVA") == "beer sheva"

    def test_normalize_dash(self):
        assert _normalize_name("Тель–Авив") == "тель авив"

    def test_collapse_whitespace(self):
        assert _normalize_name("Tel  Aviv   Yafo") == "tel aviv yafo"

    def test_strip_parentheses(self):
        assert _normalize_name("YOQNE'AM(MOSHAVA)") == "yoqneammoshava"

    def test_empty_string(self):
        assert _normalize_name("") == ""


# ============================================================================
# Lookup index
# ============================================================================

class TestLocalityLookup:
    """Tests for the LOCALITY_LOOKUP index."""

    def test_lookup_not_empty(self):
        assert len(LOCALITY_LOOKUP) > 0

    def test_lookup_has_hebrew_names(self):
        assert "חיפה" in LOCALITY_LOOKUP

    def test_lookup_has_english_names(self):
        assert "haifa" in LOCALITY_LOOKUP

    def test_lookup_has_russian_names(self):
        assert "хайфа" in LOCALITY_LOOKUP

    def test_lookup_sorted_longest_first(self):
        """Keys should be sorted longest-first for greedy matching."""
        keys = list(LOCALITY_LOOKUP.keys())
        for i in range(len(keys) - 1):
            assert len(keys[i]) >= len(keys[i + 1])


# ============================================================================
# find_locality()
# ============================================================================

class TestFindLocality:
    """Tests for the find_locality() function."""

    def test_hebrew_exact(self):
        loc = find_locality("חיפה")
        assert loc is not None
        assert loc.code == 4000

    def test_english_exact(self):
        loc = find_locality("Haifa")
        assert loc is not None
        assert loc.code == 4000

    def test_russian_exact(self):
        loc = find_locality("Хайфа")
        assert loc is not None
        assert loc.code == 4000

    def test_russian_address_with_street(self):
        loc = find_locality("Хайфа, ул. Герцль 10")
        assert loc is not None
        assert loc.code == 4000

    def test_hebrew_city_alone(self):
        loc = find_locality("חיפה")
        assert loc is not None
        assert loc.code == 4000

    def test_russian_city_with_district(self):
        # Russian address with city + district
        loc = find_locality("Иерусалим, район Тальпиот")
        assert loc is not None
        assert loc.code == 3000

    def test_tel_aviv_russian(self):
        loc = find_locality("Тель-Авив")
        assert loc is not None
        assert loc.code == 5000

    def test_beer_sheva_russian(self):
        loc = find_locality("Беэр-Шева, район 9")
        assert loc is not None
        assert loc.code == 9000

    def test_eilat_russian(self):
        loc = find_locality("Эйлат")
        assert loc is not None
        assert loc.code == 2600

    def test_jerusalem_english(self):
        loc = find_locality("Jerusalem, Old City")
        assert loc is not None
        assert loc.code == 3000

    def test_unknown_text_returns_none(self):
        assert find_locality("random gibberish text") is None

    def test_empty_returns_none(self):
        assert find_locality("") is None

    def test_none_safe(self):
        # Passing None should not crash
        assert find_locality("") is None

    def test_case_insensitive_english(self):
        loc = find_locality("haifa")
        assert loc is not None
        assert loc.code == 4000

    def test_nesher(self):
        loc = find_locality("Нешер")
        assert loc is not None
        assert loc.code == 2500
        assert loc.region == 31

    def test_nahariya_english(self):
        loc = find_locality("Nahariyya")
        assert loc is not None
        assert loc.region == 24

    def test_ashdod_hebrew(self):
        loc = find_locality("אשדוד")
        assert loc is not None
        assert loc.code == 70


# ============================================================================
# RU aliases integration
# ============================================================================

class TestRuAliases:
    """Tests for auto-generated Russian aliases."""

    def test_ru_aliases_loaded(self):
        """The RU aliases file should load with many entries."""
        assert len(_RU_ALIASES) > 1000

    def test_ru_aliases_in_lookup(self):
        """RU aliases should expand the lookup beyond base names."""
        # Lookup should be bigger than just localities count
        assert len(LOCALITY_LOOKUP) > len(LOCALITIES) * 2

    def test_abu_gosh_via_alias(self):
        """'абу гош' from aliases resolves to Abu Ghosh (code 472)."""
        loc = find_locality("абу гош")
        assert loc is not None
        assert loc.code == 472

    def test_alias_variant_without_hyphen(self):
        """Aliases without hyphens should work (e.g. 'абугош')."""
        loc = find_locality("абугош")
        assert loc is not None
        assert loc.code == 472

    def test_alias_maps_to_valid_locality(self):
        """Every alias code should map to a valid locality."""
        for alias, code in _RU_ALIASES.items():
            assert code in LOCALITY_BY_CODE, (
                f"RU alias {alias!r} maps to code {code} not in dataset"
            )

    def test_lookup_still_sorted_longest_first(self):
        """After adding RU aliases, lookup must remain longest-first."""
        keys = list(LOCALITY_LOOKUP.keys())
        for i in range(len(keys) - 1):
            assert len(keys[i]) >= len(keys[i + 1])
