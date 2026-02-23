# tests/test_moving_bot.py
"""
Tests for the moving bot bundle modules (Phase 1 — bot engine isolation).

Covers:
- moving_bot_texts     — get_text(key, lang) accessor
- moving_bot_choices   — choice mappings
- moving_bot_validators — input validators + intent detection
- moving_bot_pricing   — pricing catalog placeholder
- moving_bot_handler   — full conversation flow + language switching
"""
from __future__ import annotations

import pytest
from app.core.bots.moving_bot_texts import get_text
from app.core.bots.moving_bot_choices import TIME_CHOICES_DICT, EXTRA_OPTIONS, VALUE_NONE
from unittest.mock import patch
from app.core.bots.moving_bot_validators import (
    norm, lower, looks_too_short, parse_choices, parse_extras_input, detect_intent,
    extract_items, detect_volume_from_rooms, detect_volume_from_items,
    sanitize_text, parse_landing_prefill, LandingPrefill,
    _ATTR_SUFFIXES,
)
from app.core.bots.moving_bot_pricing import (
    PricingConfig, HAIFA_METRO_PRICING, ITEM_CATALOG, EXTRAS_ADJUSTMENTS, estimate_price,
    ITEM_ALIAS_LOOKUP, _build_alias_lookup, COMPLEXITY_GUARDS,
    VOLUME_FROM_ITEMS_CONFIG, ITEM_LABELS,
)
from app.core.handlers.moving_bot_handler import MovingBotHandler


# ============================================================================
# TestMovingBotTexts
# ============================================================================

class TestMovingBotTexts:
    """Tests for get_text() accessor."""

    def test_get_text_russian_default(self):
        text = get_text("welcome")
        assert "Привет" in text

    def test_get_text_russian_explicit(self):
        text = get_text("welcome", "ru")
        assert "Привет" in text

    def test_get_text_english(self):
        text = get_text("welcome", "en")
        assert "Hello" in text

    def test_get_text_hebrew(self):
        text = get_text("welcome", "he")
        assert "שלום" in text

    def test_get_text_unknown_key_returns_key(self):
        assert get_text("nonexistent_key_xyz") == "nonexistent_key_xyz"

    def test_get_text_all_question_keys(self):
        """All question keys must resolve (not return key itself)."""
        keys = [
            "q_cargo", "q_addr_from", "q_floor_from",
            "q_addr_to", "q_floor_to", "q_time",
            "q_photo_menu", "q_photo_wait", "q_extras",
        ]
        for key in keys:
            text = get_text(key, "ru")
            assert text != key, f"Key {key!r} not found in translations"

    def test_get_text_all_error_keys(self):
        """All error keys must resolve."""
        keys = [
            "err_cargo_too_short", "err_addr_too_short", "err_floor_too_short",
            "err_time_format", "err_photo_menu", "err_extras_empty",
        ]
        for key in keys:
            text = get_text(key, "ru")
            assert text != key, f"Key {key!r} not found in translations"

    def test_get_text_all_info_keys(self):
        """All info/hint keys must resolve."""
        keys = [
            "done", "info_photo_wait", "info_photo_received_first",
            "info_photo_received_late", "info_already_done",
            "hint_can_reset", "hint_stale_resume",
        ]
        for key in keys:
            text = get_text(key, "ru")
            assert text != key, f"Key {key!r} not found in translations"

    def test_all_keys_have_en_and_he(self):
        """Phase 7.1: every translation key must have EN and HE equivalents."""
        from app.core.bots.moving_bot_config import MOVING_TRANSLATIONS

        missing = []
        for key, translation in MOVING_TRANSLATIONS.items():
            if translation.en is None:
                missing.append(f"{key}: missing en")
            if translation.he is None:
                missing.append(f"{key}: missing he")
        assert not missing, f"Missing translations:\n" + "\n".join(missing)

    def test_all_keys_resolve_in_all_languages(self):
        """Phase 7.1: get_text() returns non-empty for every key in ru/en/he."""
        from app.core.bots.moving_bot_config import MOVING_TRANSLATIONS

        for key in MOVING_TRANSLATIONS:
            for lang in ("ru", "en", "he"):
                text = get_text(key, lang)
                assert text != key, f"get_text({key!r}, {lang!r}) returned key itself"
                assert len(text) > 0, f"get_text({key!r}, {lang!r}) returned empty string"

    def test_en_he_not_same_as_ru(self):
        """EN and HE translations should differ from RU (catch copy-paste errors)."""
        from app.core.bots.moving_bot_config import MOVING_TRANSLATIONS

        for key, t in MOVING_TRANSLATIONS.items():
            if t.en is not None:
                assert t.en != t.ru, f"Key {key!r}: en is identical to ru"
            if t.he is not None:
                assert t.he != t.ru, f"Key {key!r}: he is identical to ru"


# ============================================================================
# TestMovingBotChoices
# ============================================================================

class TestMovingBotChoices:
    """Tests for choice mappings."""

    def test_time_choices_has_expected_keys(self):
        assert set(TIME_CHOICES_DICT.keys()) == {"1", "2", "3"}

    def test_time_choices_values(self):
        assert TIME_CHOICES_DICT["1"] == "today"
        assert TIME_CHOICES_DICT["2"] == "tomorrow"
        assert TIME_CHOICES_DICT["3"] == "soon"

    def test_extra_options_has_expected_keys(self):
        assert set(EXTRA_OPTIONS.keys()) == {"1", "2", "3", "4"}

    def test_extra_options_values(self):
        assert EXTRA_OPTIONS["1"] == "loaders"
        assert EXTRA_OPTIONS["2"] == "assembly"
        assert EXTRA_OPTIONS["3"] == "packing"
        assert EXTRA_OPTIONS["4"] == "none"

    def test_value_none(self):
        assert VALUE_NONE == "none"


# ============================================================================
# TestMovingBotValidators
# ============================================================================

class TestMovingBotValidatorsNorm:
    """Tests for norm() and lower()."""

    def test_norm_strips_whitespace(self):
        assert norm("  hello  ") == "hello"

    def test_norm_empty_string(self):
        assert norm("") == ""

    def test_norm_none_safe(self):
        assert norm(None) == ""

    def test_lower_normalizes_and_lowercases(self):
        assert lower("  HeLLo  ") == "hello"


class TestMovingBotValidatorsShort:
    """Tests for looks_too_short()."""

    def test_short_string(self):
        assert looks_too_short("ab", 5) is True

    def test_long_enough_string(self):
        assert looks_too_short("hello world", 5) is False

    def test_junk_ok(self):
        assert looks_too_short("ok", 1) is True

    def test_junk_da(self):
        assert looks_too_short("да", 1) is True

    def test_junk_dots(self):
        assert looks_too_short("...", 1) is True

    def test_junk_question_mark(self):
        assert looks_too_short("?", 1) is True

    def test_not_junk(self):
        assert looks_too_short("hello", 3) is False


class TestMovingBotValidatorsParseChoices:
    """Tests for parse_choices()."""

    def test_single_digit(self):
        assert parse_choices("1") == {"1"}

    def test_multiple_digits(self):
        assert parse_choices("1 3") == {"1", "3"}

    def test_no_valid_digits(self):
        assert parse_choices("abc") == set()

    def test_mixed_with_text(self):
        assert parse_choices("1abc2") == {"1", "2"}


class TestMovingBotValidatorsParseExtras:
    """Tests for parse_extras_input()."""

    def test_pure_numeric(self):
        choices, details = parse_extras_input("1 3")
        assert choices == {"1", "3"}
        assert details is None

    def test_pure_numeric_with_commas(self):
        choices, details = parse_extras_input("1,2,3")
        assert choices == {"1", "2", "3"}
        assert details is None

    def test_text_only(self):
        choices, details = parse_extras_input("5 этаж без лифта")
        assert choices == set()
        assert details == "5 этаж без лифта"

    def test_numbers_plus_text(self):
        choices, details = parse_extras_input("1 3 + 5 этаж")
        assert choices == {"1", "3"}
        assert details == "5 этаж"

    def test_comma_separator(self):
        # "1, 3, срочно": regex matches first comma (space is non-digit),
        # so before="1", after="3, срочно" — only "1" is extracted as choice.
        choices, details = parse_extras_input("1, 3, срочно")
        assert choices == {"1"}
        assert details == "3, срочно"

    def test_and_separator_ru(self):
        choices, details = parse_extras_input("1 и 2 и нужен лифт")
        assert choices == {"1", "2"}
        assert details == "нужен лифт"

    def test_empty_string(self):
        choices, details = parse_extras_input("")
        assert choices == set()
        assert details is None

    def test_single_choice(self):
        choices, details = parse_extras_input("4")
        assert choices == {"4"}
        assert details is None


class TestMovingBotValidatorsIntent:
    """Tests for detect_intent()."""

    def test_reset_russian(self):
        assert detect_intent("заново") == "reset"

    def test_reset_english(self):
        assert detect_intent("restart") == "reset"

    def test_done_photos_russian(self):
        assert detect_intent("готово") == "done_photos"

    def test_done_photos_english(self):
        assert detect_intent("done") == "done_photos"

    def test_no_russian(self):
        assert detect_intent("нет") == "no"

    def test_no_english(self):
        assert detect_intent("no") == "no"

    def test_no_intent_random_text(self):
        assert detect_intent("перевезти диван") is None

    def test_start_command(self):
        assert detect_intent("/start") == "reset"


# ============================================================================
# TestMovingBotPricing
# ============================================================================

class TestMovingBotPricing:
    """Tests for pricing placeholder module."""

    def test_haifa_metro_defaults(self):
        assert HAIFA_METRO_PRICING.base_callout == 150
        assert HAIFA_METRO_PRICING.no_elevator_per_floor == 50
        assert HAIFA_METRO_PRICING.extra_pickup == 70
        assert HAIFA_METRO_PRICING.estimate_margin == 0.15

    def test_item_catalog_has_entries(self):
        assert len(ITEM_CATALOG) > 0
        assert "fridge_single_door" in ITEM_CATALOG
        assert "box_standard" in ITEM_CATALOG

    def test_item_catalog_values_are_ranges(self):
        for key, (low, high) in ITEM_CATALOG.items():
            assert low <= high, f"Item {key}: min ({low}) > max ({high})"
            assert low > 0, f"Item {key}: min price must be positive"

    def test_extras_adjustments_has_entries(self):
        assert len(EXTRAS_ADJUSTMENTS) > 0
        assert "narrow_stairs" in EXTRAS_ADJUSTMENTS
        assert "client_helps" in EXTRAS_ADJUSTMENTS

    def test_client_helps_is_negative(self):
        assert EXTRAS_ADJUSTMENTS["client_helps"] < 0

    def test_estimate_price_base_only(self):
        """Base case: no floors, no extras → base callout with margin."""
        result = estimate_price()
        assert result["currency"] == "ILS"
        assert result["estimate_min"] < result["estimate_max"]
        # Default base is 150 ±15%: 127–173
        assert result["estimate_min"] == 127
        assert result["estimate_max"] == 173

    def test_pricing_config_custom_values(self):
        custom = PricingConfig(base_callout=300, no_elevator_per_floor=80)
        assert custom.base_callout == 300
        assert custom.no_elevator_per_floor == 80
        assert custom.extra_pickup == 70  # default
        assert custom.estimate_margin == 0.15  # default


# ============================================================================
# TestMovingBotHandlerFlow
# ============================================================================

class TestMovingBotHandlerFlow:
    """Full conversation flow test — same flow as before, validates no regression."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_new_session_creates_valid_state(self):
        state = self.handler.new_session("t1", "chat1")
        assert state.tenant_id == "t1"
        assert state.chat_id == "chat1"
        assert state.step == "welcome"
        assert state.bot_type == "moving_bot_v1"
        assert state.language == "ru"
        assert len(state.lead_id) == 12

    def test_new_session_custom_language(self):
        state = self.handler.new_session("t1", "chat1", language="en")
        assert state.language == "en"

    def test_full_flow_happy_path(self):
        """Complete conversation flow: welcome → cargo → ... → done."""
        state = self.handler.new_session("t1", "chat1")

        # WELCOME → CARGO
        state, reply, done = self.handler.handle_text(state, "привет")
        assert state.step == "cargo"
        assert not done
        # Reply should contain welcome + hint + cargo question (in Russian)
        assert "Привет" in reply
        assert "перевезти" in reply.lower() or "Что нужно" in reply

        # CARGO → PICKUP_COUNT (items detected → volume skipped)
        state, reply, done = self.handler.handle_text(state, "Диван, холодильник, 5 коробок")
        assert state.step == "pickup_count"
        assert state.data.cargo_description == "Диван, холодильник, 5 коробок"
        assert not done

        # PICKUP_COUNT → ADDR_FROM (single pickup)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "addr_from"
        assert state.data.custom["pickup_count"] == 1
        assert not done

        # ADDR_FROM → FLOOR_FROM
        state, reply, done = self.handler.handle_text(state, "Хайфа, ул. Герцль 10")
        assert state.step == "floor_from"
        assert state.data.addr_from == "Хайфа, ул. Герцль 10"
        assert not done

        # FLOOR_FROM → ADDR_TO
        state, reply, done = self.handler.handle_text(state, "3 этаж, лифт есть")
        assert state.step == "addr_to"
        assert state.data.floor_from == "3 этаж, лифт есть"
        assert not done

        # ADDR_TO → FLOOR_TO
        state, reply, done = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"
        assert state.data.addr_to == "Тель-Авив, Дизенгоф 50"
        assert not done

        # FLOOR_TO → DATE (Phase 2: structured scheduling)
        state, reply, done = self.handler.handle_text(state, "5 этаж, без лифта")
        assert state.step == "date"
        assert state.data.floor_to == "5 этаж, без лифта"
        assert not done

        # DATE → TIME_SLOT (choice "1" = tomorrow)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "time_slot"
        assert state.data.custom["move_date_label"] == "tomorrow"
        assert state.data.custom["move_date"]  # ISO date string
        assert not done

        # TIME_SLOT → PHOTO_MENU (choice "1" = morning)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"
        assert state.data.time_window == "morning"
        assert state.data.custom["time_slot"] == "morning"
        assert not done

        # PHOTO_MENU → EXTRAS (no photos)
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "extras"
        assert state.data.has_photos is False
        assert not done

        # EXTRAS → ESTIMATE
        state, reply, done = self.handler.handle_text(state, "1 3")
        assert state.step == "estimate"
        assert not done
        assert "loaders" in state.data.extras
        assert "packing" in state.data.extras
        # Reply shows price estimate
        assert "₪" in reply

        # ESTIMATE → DONE (confirm)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "done"
        assert done is True
        assert "Спасибо" in reply or "оператору" in reply

    def test_flow_with_photos(self):
        """Test photo upload path: photo_menu → photo_wait → extras."""
        state = self.handler.new_session("t1", "chat1")

        # Fast-forward to photo_menu
        state.step = "photo_menu"

        # Choose "1" (send photos)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_wait"
        assert state.data.has_photos is True

        # Send a photo
        state, reply = self.handler.handle_media(state)
        assert state.data.photo_count == 1
        assert reply is not None  # first photo gets a confirmation

        # Send another photo
        state, reply = self.handler.handle_media(state)
        assert state.data.photo_count == 2
        assert reply is None  # subsequent photos are silent

        # Say "done"
        state, reply, done = self.handler.handle_text(state, "готово")
        assert state.step == "extras"
        assert not done

    def test_cargo_too_short_error(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"

        state, reply, done = self.handler.handle_text(state, "ok")
        assert state.step == "cargo"  # stays on same step
        assert not done

    def test_addr_too_short_error(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"

        state, reply, done = self.handler.handle_text(state, "да")
        assert state.step == "addr_from"
        assert not done

    def test_time_choice_today(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time"

        state, reply, done = self.handler.handle_text(state, "1")
        assert state.data.time_window == "today"

    def test_time_free_text(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time"

        state, reply, done = self.handler.handle_text(state, "завтра в 14:00")
        assert state.data.time_window == "завтра в 14:00"

    def test_extras_none_choice(self):
        """Choice "4" means no extras needed → transitions to estimate."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"

        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert not done
        assert state.data.extras == []
        assert state.data.details_free == "none"
        assert "₪" in reply  # estimate shown

    def test_extras_free_text(self):
        """Free text in extras step → transitions to estimate."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"

        state, reply, done = self.handler.handle_text(state, "нужна помощь с подъёмом на 5 этаж")
        assert state.step == "estimate"
        assert not done
        assert state.data.details_free == "нужна помощь с подъёмом на 5 этаж"

    def test_extras_numbers_plus_text(self):
        """Numbers + text in extras step → transitions to estimate."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"

        state, reply, done = self.handler.handle_text(state, "1 3 + без лифта")
        assert state.step == "estimate"
        assert not done
        assert "loaders" in state.data.extras
        assert "packing" in state.data.extras
        assert state.data.details_free == "без лифта"

    def test_reset_intent(self):
        """Reset mid-flow creates a new session."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        old_lead = state.lead_id

        state, reply, done = self.handler.handle_text(state, "заново")
        assert state.step == "cargo"
        assert state.lead_id != old_lead  # new session → new lead_id
        assert not done

    def test_done_step_returns_already_done(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "done"

        state, reply, done = self.handler.handle_text(state, "hello")
        assert state.step == "done"
        assert not done

    def test_media_outside_photo_wait(self):
        """Photos received outside photo_wait still get counted."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"

        state, reply = self.handler.handle_media(state)
        assert state.data.photo_count == 1
        assert state.data.has_photos is True
        assert reply is not None  # late photo gets a reply

    def test_get_payload(self):
        state = self.handler.new_session("t1", "chat1")
        state.data.cargo_description = "test"
        state.step = "done"

        payload = self.handler.get_payload(state)
        assert payload["tenant_id"] == "t1"
        assert payload["chat_id"] == "chat1"
        assert payload["bot_type"] == "moving_bot_v1"
        assert payload["step"] == "done"
        assert payload["data"]["cargo_description"] == "test"

    def test_photo_menu_invalid_input(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "photo_menu"

        state, reply, done = self.handler.handle_text(state, "maybe")
        assert state.step == "photo_menu"  # stays on same step
        assert not done

    def test_photo_wait_non_done_text(self):
        """Non-done text in photo_wait prompts user to send more or say done."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "photo_wait"

        state, reply, done = self.handler.handle_text(state, "ещё фото будут")
        assert state.step == "photo_wait"
        assert not done

    def test_extras_decline_with_no(self):
        """Saying 'no' in extras step → transitions to estimate."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"

        state, reply, done = self.handler.handle_text(state, "нет")
        assert state.step == "estimate"
        assert not done
        assert state.data.details_free == "none"


# ============================================================================
# TestMovingBotHandlerLanguage
# ============================================================================

class TestMovingBotHandlerLanguage:
    """Verify handler returns texts in the session language."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_welcome_english(self):
        state = self.handler.new_session("t1", "chat1", language="en")
        state, reply, done = self.handler.handle_text(state, "hi")
        assert "Hello" in reply
        assert "Привет" not in reply

    def test_welcome_russian(self):
        state = self.handler.new_session("t1", "chat1", language="ru")
        state, reply, done = self.handler.handle_text(state, "привет")
        assert "Привет" in reply

    def test_cargo_error_english(self):
        state = self.handler.new_session("t1", "chat1", language="en")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, "ok")
        assert "specific" in reply.lower() or "more" in reply.lower()

    def test_done_message_english(self):
        state = self.handler.new_session("t1", "chat1", language="en")
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # Confirm the estimate
        state, reply, done = self.handler.handle_text(state, "1")
        assert "Thank you" in reply

    def test_done_message_hebrew(self):
        state = self.handler.new_session("t1", "chat1", language="he")
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # Confirm the estimate
        state, reply, done = self.handler.handle_text(state, "1")
        assert "תודה" in reply


# ============================================================================
# Phase 2: Scheduling tests
# ============================================================================

from datetime import date, timedelta, datetime as _dt
from unittest.mock import patch
from zoneinfo import ZoneInfo
from app.core.bots.moving_bot_validators import parse_date, parse_exact_time
from app.core.bots.moving_bot_choices import DATE_CHOICES_DICT, TIME_SLOT_CHOICES_DICT

_TZ = ZoneInfo("Asia/Jerusalem")


class TestParseDate:
    """Tests for parse_date() validator."""

    def _tomorrow(self):
        return _dt.now(_TZ).date() + timedelta(days=1)

    def _future(self, days=10):
        return _dt.now(_TZ).date() + timedelta(days=days)

    def test_valid_dd_mm(self):
        future = self._future(10)
        text = f"{future.day:02d}.{future.month:02d}"
        result = parse_date(text)
        assert result == future

    def test_valid_dd_mm_yyyy(self):
        future = self._future(10)
        text = f"{future.day:02d}.{future.month:02d}.{future.year}"
        result = parse_date(text)
        assert result == future

    def test_slash_separator(self):
        future = self._future(10)
        text = f"{future.day:02d}/{future.month:02d}/{future.year}"
        result = parse_date(text)
        assert result == future

    def test_dash_separator(self):
        future = self._future(10)
        text = f"{future.day:02d}-{future.month:02d}-{future.year}"
        result = parse_date(text)
        assert result == future

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="format"):
            parse_date("abc")

    def test_invalid_format_too_many_parts(self):
        with pytest.raises(ValueError, match="format"):
            parse_date("1.2.3.4")

    def test_invalid_date_feb_30(self):
        with pytest.raises(ValueError, match="invalid_date"):
            parse_date("30.02.2026")

    def test_too_soon_today(self):
        today = _dt.now(_TZ).date()
        text = f"{today.day:02d}.{today.month:02d}.{today.year}"
        with pytest.raises(ValueError, match="too_soon"):
            parse_date(text)

    def test_too_far(self):
        far = _dt.now(_TZ).date() + timedelta(days=100)
        text = f"{far.day:02d}.{far.month:02d}.{far.year}"
        with pytest.raises(ValueError, match="too_far"):
            parse_date(text)

    def test_auto_roll_next_year(self):
        """DD.MM that already passed this year should roll to next year.
        The rolled date (next year) will almost always be >90 days away,
        so it raises too_far — that's correct behavior. We verify the
        auto-roll logic by checking it doesn't raise too_soon."""
        today = _dt.now(_TZ).date()
        yesterday = today - timedelta(days=1)
        text = f"{yesterday.day:02d}.{yesterday.month:02d}"
        # Rolled to next year → typically >90 days → too_far
        with pytest.raises(ValueError, match="too_far"):
            parse_date(text)

    def test_tomorrow_is_valid(self):
        tomorrow = self._tomorrow()
        text = f"{tomorrow.day:02d}.{tomorrow.month:02d}.{tomorrow.year}"
        result = parse_date(text)
        assert result == tomorrow

    def test_60_days_boundary(self):
        """Exactly 60 days out should be valid (Phase 15: reduced from 90)."""
        target = _dt.now(_TZ).date() + timedelta(days=60)
        text = f"{target.day:02d}.{target.month:02d}.{target.year}"
        result = parse_date(text)
        assert result == target

    def test_61_days_is_too_far(self):
        """61 days out is too far (Phase 15: reduced from 90)."""
        target = _dt.now(_TZ).date() + timedelta(days=61)
        text = f"{target.day:02d}.{target.month:02d}.{target.year}"
        with pytest.raises(ValueError, match="too_far"):
            parse_date(text)

    def test_single_digit_day_month(self):
        future = self._future(10)
        text = f"{future.day}.{future.month}.{future.year}"
        result = parse_date(text)
        assert result == future


class TestNaturalDateParser:
    """Tests for natural language date parsing (Phase 15)."""

    # -- Relative days --

    def test_tomorrow_russian(self):
        result = parse_date("завтра")
        assert result == _dt.now(_TZ).date() + timedelta(days=1)

    def test_tomorrow_english(self):
        result = parse_date("tomorrow")
        assert result == _dt.now(_TZ).date() + timedelta(days=1)

    def test_tomorrow_hebrew(self):
        result = parse_date("מחר")
        assert result == _dt.now(_TZ).date() + timedelta(days=1)

    def test_day_after_tomorrow_russian(self):
        result = parse_date("послезавтра")
        assert result == _dt.now(_TZ).date() + timedelta(days=2)

    def test_day_after_tomorrow_english(self):
        result = parse_date("day after tomorrow")
        assert result == _dt.now(_TZ).date() + timedelta(days=2)

    def test_day_after_tomorrow_hebrew(self):
        result = parse_date("מחרתיים")
        assert result == _dt.now(_TZ).date() + timedelta(days=2)

    def test_today_rejected_as_too_soon(self):
        """Today is too soon — must be at least tomorrow."""
        with pytest.raises(ValueError, match="too_soon"):
            parse_date("сегодня")

    def test_today_english_rejected(self):
        with pytest.raises(ValueError, match="too_soon"):
            parse_date("today")

    # -- Weekday names --

    def test_weekday_russian(self):
        """'пятница' → next Friday."""
        result = parse_date("пятница")
        assert result.weekday() == 4  # Friday

    def test_weekday_english(self):
        result = parse_date("Friday")
        assert result.weekday() == 4

    def test_weekday_with_prefix_russian(self):
        """'в среду' → next Wednesday."""
        result = parse_date("в среду")
        # Should be Wednesday, but 'в' not stripped by _NEXT_PREFIX_RE
        # Actually the prefix handles 'в следующую'; just 'в' alone won't match
        # Let me test the actual weekday directly:
        assert result.weekday() == 2  # Wednesday

    def test_next_weekday_english(self):
        """'next Monday' → Monday of next week."""
        today = _dt.now(_TZ).date()
        result = parse_date("next Monday")
        assert result.weekday() == 0  # Monday
        # "next" adds 7 days to the natural occurrence
        # It should be at least 8 days out (next week's Monday)
        assert (result - today).days >= 7

    def test_next_weekday_russian(self):
        """'в следующую пятницу' → Friday of next week."""
        today = _dt.now(_TZ).date()
        result = parse_date("в следующую пятницу")
        assert result.weekday() == 4
        assert (result - today).days >= 7

    def test_weekday_hebrew(self):
        """'יום חמישי' → next Thursday."""
        result = parse_date("יום חמישי")
        assert result.weekday() == 3

    def test_weekday_short_english(self):
        result = parse_date("wed")
        assert result.weekday() == 2

    # -- Day + month name --

    def test_day_month_russian(self):
        """'15 марта' → March 15."""
        result = parse_date("15 марта")
        assert result.month == 3
        assert result.day == 15

    def test_day_month_english(self):
        """'March 5' → March 5."""
        result = parse_date("March 5")
        assert result.month == 3
        assert result.day == 5

    def test_day_month_english_suffix(self):
        """'March 5th' → March 5."""
        result = parse_date("March 5th")
        assert result.month == 3
        assert result.day == 5

    def test_day_month_hebrew(self):
        """Hebrew day+month parsing."""
        # Use a date within the next 60 days
        today = _dt.now(_TZ).date()
        target = today + timedelta(days=20)
        _HE_MONTHS = {1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל",
                      5: "מאי", 6: "יוני", 7: "יולי", 8: "אוגוסט",
                      9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר"}
        text = f"{target.day} {_HE_MONTHS[target.month]}"
        result = parse_date(text)
        assert result.month == target.month
        assert result.day == target.day

    def test_day_month_russian_genitive(self):
        """'5 марта' → March 5."""
        result = parse_date("5 марта")
        assert result.month == 3
        assert result.day == 5

    def test_day_month_rolls_to_next_year(self):
        """Date in the past rolls to next year (tested at raw parsing level)."""
        from app.core.bots.moving_bot_validators import _parse_natural_date
        today = _dt.now(_TZ).date()
        # Pick a date 30 days in the past
        past = today - timedelta(days=30)
        month_names = {
            1: "января", 2: "февраля", 3: "марта", 4: "апреля",
            5: "мая", 6: "июня", 7: "июля", 8: "августа",
            9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
        }
        text = f"{past.day} {month_names[past.month]}"
        # _parse_natural_date does NOT validate range, just resolves
        result = _parse_natural_date(text)
        assert result is not None
        assert result.year == today.year + 1
        assert result.month == past.month
        assert result.day == past.day
        # But parse_date() rejects it as too_far (>60 days)
        with pytest.raises(ValueError, match="too_far"):
            parse_date(text)

    def test_invalid_day_month_raises(self):
        """'31 февраля' → invalid_date."""
        with pytest.raises(ValueError, match="invalid_date"):
            parse_date("31 февраля")

    def test_too_far_natural(self):
        """Date > 60 days out raises too_far."""
        today = _dt.now(_TZ).date()
        far = today + timedelta(days=65)
        month_names = {
            1: "January", 2: "February", 3: "March", 4: "April",
            5: "May", 6: "June", 7: "July", 8: "August",
            9: "September", 10: "October", 11: "November", 12: "December",
        }
        text = f"{month_names[far.month]} {far.day}"
        with pytest.raises(ValueError, match="too_far"):
            parse_date(text)

    # -- Format fallback --

    def test_dd_mm_still_works(self):
        """Original DD.MM format still works."""
        future = _dt.now(_TZ).date() + timedelta(days=10)
        text = f"{future.day:02d}.{future.month:02d}"
        result = parse_date(text)
        assert result == future

    def test_unrecognised_text_raises_format(self):
        """Gibberish raises ValueError('format')."""
        with pytest.raises(ValueError, match="format"):
            parse_date("когда-нибудь потом")

    def test_russian_month_abbreviation(self):
        """Short Russian month abbreviations work."""
        today = _dt.now(_TZ).date()
        target = today + timedelta(days=15)
        _RU_MONTHS_SHORT = {1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "мая",
                            6: "июн", 7: "июл", 8: "авг", 9: "сен", 10: "окт",
                            11: "ноя", 12: "дек"}
        text = f"{target.day} {_RU_MONTHS_SHORT[target.month]}"
        result = parse_date(text)
        assert result.month == target.month
        assert result.day == target.day

    def test_english_month_abbreviation(self):
        """Short English month abbreviations work."""
        today = _dt.now(_TZ).date()
        target = today + timedelta(days=15)
        _EN_MONTHS_SHORT = {1: "jan", 2: "feb", 3: "mar", 4: "apr", 5: "may",
                            6: "jun", 7: "jul", 8: "aug", 9: "sep", 10: "oct",
                            11: "nov", 12: "dec"}
        text = f"{_EN_MONTHS_SHORT[target.month]} {target.day}"
        result = parse_date(text)
        assert result.month == target.month
        assert result.day == target.day


class TestNaturalDateInHandler:
    """Test natural date parsing at the handler DATE step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_natural_date_at_date_step(self):
        """'завтра' at date step skips specific_date, goes to time_slot."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "завтра")
        assert state.step == "time_slot"
        expected = (_dt.now(_TZ).date() + timedelta(days=1)).isoformat()
        assert state.data.custom["move_date"] == expected

    def test_dd_mm_at_date_step(self):
        """'15.03' at date step accepted directly."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        future = _dt.now(_TZ).date() + timedelta(days=10)
        text = f"{future.day:02d}.{future.month:02d}"
        state, reply, done = self.handler.handle_text(state, text)
        assert state.step == "time_slot"
        assert state.data.custom["move_date"] == future.isoformat()

    def test_english_weekday_at_date_step(self):
        """'Friday' at date step."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "Friday")
        assert state.step == "time_slot"

    def test_menu_choices_still_work(self):
        """Numeric menu choices still work as before."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "time_slot"
        assert state.data.custom["move_date_label"] == "tomorrow"


class TestParseExactTime:
    """Tests for parse_exact_time() validator."""

    def test_valid_time(self):
        assert parse_exact_time("14:30") == "14:30"

    def test_valid_morning(self):
        assert parse_exact_time("08:00") == "08:00"

    def test_dot_separator(self):
        assert parse_exact_time("14.30") == "14:30"

    def test_midnight(self):
        assert parse_exact_time("0:00") == "00:00"

    def test_invalid_hour(self):
        with pytest.raises(ValueError):
            parse_exact_time("25:00")

    def test_invalid_minute(self):
        with pytest.raises(ValueError):
            parse_exact_time("14:61")

    def test_malformed(self):
        with pytest.raises(ValueError):
            parse_exact_time("abc")

    def test_no_minutes(self):
        with pytest.raises(ValueError):
            parse_exact_time("14")


class TestDateStepFlow:
    """Tests for the DATE step in the handler."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_choice_1_tomorrow(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "time_slot"
        assert state.data.custom["move_date_label"] == "tomorrow"
        assert state.data.custom["move_date"]  # non-empty ISO string
        assert state.data.custom["timezone"] == "Asia/Jerusalem"

    def test_choice_2_2_3_days(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "time_slot"
        assert state.data.custom["move_date_label"] == "2_3_days"

    def test_choice_3_this_week(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "3")
        assert state.step == "time_slot"
        assert state.data.custom["move_date_label"] == "this_week"

    def test_choice_4_specific(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "specific_date"
        assert state.data.custom["move_date_label"] == "specific"

    def test_invalid_choice(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "5")
        assert state.step == "date"  # stays
        assert not done

    def test_natural_date_accepted(self):
        """Phase 15: natural language dates accepted at date step."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "завтра")
        assert state.step == "time_slot"  # accepted via natural date parser
        assert state.data.custom["move_date_label"] == "natural"

    def test_gibberish_rejected(self):
        """Non-date text still rejected at date step."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_text(state, "скоро когда-нибудь")
        assert state.step == "date"  # stays — unrecognised text


class TestSpecificDateStepFlow:
    """Tests for the SPECIFIC_DATE step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_valid_date(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "specific_date"
        future = _dt.now(_TZ).date() + timedelta(days=10)
        text = f"{future.day:02d}.{future.month:02d}.{future.year}"
        state, reply, done = self.handler.handle_text(state, text)
        assert state.step == "time_slot"
        assert state.data.custom["move_date"] == future.isoformat()

    def test_invalid_format_stays(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "specific_date"
        state, reply, done = self.handler.handle_text(state, "abc")
        assert state.step == "specific_date"

    def test_too_soon_stays(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "specific_date"
        today = _dt.now(_TZ).date()
        text = f"{today.day:02d}.{today.month:02d}.{today.year}"
        state, reply, done = self.handler.handle_text(state, text)
        assert state.step == "specific_date"

    def test_too_far_stays(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "specific_date"
        far = _dt.now(_TZ).date() + timedelta(days=100)
        text = f"{far.day:02d}.{far.month:02d}.{far.year}"
        state, reply, done = self.handler.handle_text(state, text)
        assert state.step == "specific_date"

    def test_invalid_date_stays(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "specific_date"
        state, reply, done = self.handler.handle_text(state, "30.02.2026")
        assert state.step == "specific_date"


class TestTimeSlotStepFlow:
    """Tests for the TIME_SLOT step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_choice_1_morning(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"
        assert state.data.custom["time_slot"] == "morning"
        assert state.data.time_window == "morning"  # backward compat

    def test_choice_2_afternoon(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "photo_menu"
        assert state.data.custom["time_slot"] == "afternoon"

    def test_choice_3_evening(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "3")
        assert state.step == "photo_menu"
        assert state.data.custom["time_slot"] == "evening"

    def test_choice_4_goes_to_exact_time(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "exact_time"

    def test_choice_5_flexible(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "5")
        assert state.step == "photo_menu"
        assert state.data.custom["time_slot"] == "flexible"
        assert state.data.time_window == "flexible"

    def test_invalid_choice(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "6")
        assert state.step == "time_slot"  # stays

    def test_exact_time_is_none_for_non_exact(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.data.custom["exact_time"] is None


class TestExactTimeStepFlow:
    """Tests for the EXACT_TIME step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_valid_time(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "exact_time"
        state, reply, done = self.handler.handle_text(state, "14:30")
        assert state.step == "photo_menu"
        assert state.data.custom["time_slot"] == "exact"
        assert state.data.custom["exact_time"] == "14:30"
        assert state.data.time_window == "exact:14:30"  # backward compat

    def test_invalid_time_stays(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "exact_time"
        state, reply, done = self.handler.handle_text(state, "abc")
        assert state.step == "exact_time"

    def test_dot_separator_works(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "exact_time"
        state, reply, done = self.handler.handle_text(state, "09.00")
        assert state.step == "photo_menu"
        assert state.data.custom["exact_time"] == "09:00"


class TestFullFlowNewScheduling:
    """End-to-end flow with Phase 2 scheduling steps."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_happy_path_tomorrow_morning(self):
        """Full flow: DATE(tomorrow) → TIME_SLOT(morning) → PHOTO_MENU → EXTRAS → ESTIMATE → DONE."""
        state = self.handler.new_session("t1", "chat1")

        # Fast-forward to date step
        state.step = "date"

        # DATE → TIME_SLOT (choice 1 = tomorrow)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "time_slot"

        # TIME_SLOT → PHOTO_MENU (choice 1 = morning)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"

        # PHOTO_MENU → EXTRAS (no photos)
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "extras"

        # EXTRAS → ESTIMATE
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert not done
        assert "₪" in reply

        # ESTIMATE → DONE (confirm)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "done"
        assert done is True

        # Verify scheduling data in custom dict
        assert state.data.custom["move_date_label"] == "tomorrow"
        assert state.data.custom["move_date"]
        assert state.data.custom["time_slot"] == "morning"
        assert state.data.time_window == "morning"
        # Verify estimate data stored
        assert state.data.custom["estimate_min"] > 0
        assert state.data.custom["estimate_max"] > state.data.custom["estimate_min"]
        assert state.data.custom["estimate_currency"] == "ILS"

    def test_specific_date_with_exact_time(self):
        """Full flow: DATE(specific) → SPECIFIC_DATE → TIME_SLOT(exact) → EXACT_TIME → PHOTO_MENU."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"

        # DATE → SPECIFIC_DATE (choice 4)
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "specific_date"

        # SPECIFIC_DATE → TIME_SLOT
        future = _dt.now(_TZ).date() + timedelta(days=15)
        state, reply, done = self.handler.handle_text(state, f"{future.day:02d}.{future.month:02d}.{future.year}")
        assert state.step == "time_slot"
        assert state.data.custom["move_date"] == future.isoformat()

        # TIME_SLOT → EXACT_TIME (choice 4)
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "exact_time"

        # EXACT_TIME → PHOTO_MENU
        state, reply, done = self.handler.handle_text(state, "14:30")
        assert state.step == "photo_menu"
        assert state.data.custom["exact_time"] == "14:30"
        assert state.data.time_window == "exact:14:30"

    def test_2_3_days_flexible(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"

        # DATE(2-3 days) → TIME_SLOT
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "time_slot"
        assert state.data.custom["move_date_label"] == "2_3_days"

        # TIME_SLOT(flexible) → PHOTO_MENU
        state, reply, done = self.handler.handle_text(state, "5")
        assert state.step == "photo_menu"
        assert state.data.custom["time_slot"] == "flexible"


class TestBackwardCompatTimeStep:
    """Verify the legacy TIME step still works for sessions mid-flow at deploy."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_legacy_time_choice_today(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"
        assert state.data.time_window == "today"

    def test_legacy_time_free_text(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time"
        state, reply, done = self.handler.handle_text(state, "next friday afternoon")
        assert state.step == "photo_menu"
        assert state.data.time_window == "next friday afternoon"


class TestSchedulingTranslationKeys:
    """Verify all Phase 2 translation keys exist."""

    def test_all_phase2_keys_resolve(self):
        keys = [
            "q_date", "q_specific_date", "q_time_slot", "q_exact_time",
            "err_date_choice", "err_date_format", "err_date_invalid",
            "err_date_too_soon", "err_date_too_far",
            "err_time_slot_choice", "err_exact_time_format",
        ]
        for key in keys:
            for lang in ("ru", "en", "he"):
                text = get_text(key, lang)
                assert text != key, f"Key {key!r} not found for lang={lang}"


class TestSchedulingChoices:
    """Tests for Phase 2 choice mappings."""

    def test_date_choices_keys(self):
        assert set(DATE_CHOICES_DICT.keys()) == {"1", "2", "3", "4"}

    def test_date_choices_values(self):
        assert DATE_CHOICES_DICT["1"] == "tomorrow"
        assert DATE_CHOICES_DICT["2"] == "2_3_days"
        assert DATE_CHOICES_DICT["3"] == "this_week"
        assert DATE_CHOICES_DICT["4"] == "specific"

    def test_time_slot_choices_keys(self):
        assert set(TIME_SLOT_CHOICES_DICT.keys()) == {"1", "2", "3", "4", "5"}

    def test_time_slot_choices_values(self):
        assert TIME_SLOT_CHOICES_DICT["1"] == "morning"
        assert TIME_SLOT_CHOICES_DICT["2"] == "afternoon"
        assert TIME_SLOT_CHOICES_DICT["3"] == "evening"
        assert TIME_SLOT_CHOICES_DICT["4"] == "exact"
        assert TIME_SLOT_CHOICES_DICT["5"] == "flexible"


# ============================================================================
# Phase 3: Pricing tests
# ============================================================================

from app.core.bots.moving_bot_validators import parse_floor_info


class TestEstimatePrice:
    """Tests for the estimate_price() function."""

    def test_base_only(self):
        """No extras, ground floors → base ±15%."""
        result = estimate_price()
        assert result["currency"] == "ILS"
        assert result["estimate_min"] < result["estimate_max"]
        # Default base is 150 ±15%: 127–173
        assert result["estimate_min"] == 127
        assert result["estimate_max"] == 173

    def test_floor_surcharge_no_elevator(self):
        """Floor 4, no elevator → (4-1)*50 = 150 surcharge."""
        result = estimate_price(floor_from=4, has_elevator_from=False)
        # base=150 + 150 = 300  → 300*0.85=255, 300*1.15=345
        assert result["estimate_min"] == 255
        assert result["estimate_max"] == 345

    def test_floor_surcharge_with_elevator_no_charge(self):
        """Floor 4 with elevator → no surcharge."""
        result = estimate_price(floor_from=4, has_elevator_from=True)
        assert result["estimate_min"] == 127
        assert result["estimate_max"] == 173

    def test_floor_1_no_elevator_no_charge(self):
        """Floor 1 without elevator → no surcharge (ground level)."""
        result = estimate_price(floor_from=1, has_elevator_from=False)
        assert result["estimate_min"] == 127
        assert result["estimate_max"] == 173

    def test_both_floors_no_elevator(self):
        """Both floors without elevator → surcharge on both sides.

        floor_to=5 triggers high-floor guard (threshold=5, ×1.5).
        from: (3-1)*50=100, to: (5-1)*50=200 → raw=300
        After ×1.5: ceil(300*1.5)=450 → base+surcharge=150+450=600
        600*0.85=510, 600*1.15=690
        """
        result = estimate_price(
            floor_from=3, has_elevator_from=False,
            floor_to=5, has_elevator_to=False,
        )
        assert result["estimate_min"] == 510
        assert result["estimate_max"] == 690
        assert "high_floor_surcharge" in result["breakdown"]["guards_applied"]

    def test_extra_pickups(self):
        """Extra pickup fee adds to estimate."""
        result = estimate_price(extra_pickups=2)
        # 150 + 2*70 = 290 → 290*0.85=246, 290*1.15=334
        assert result["estimate_min"] == 246
        assert result["estimate_max"] == 334

    def test_with_items(self):
        """Items use midpoint-based estimate (v1.1)."""
        result = estimate_price(items=["fridge_single_door", "box_standard"])
        # refrigerator mid=(200+280)/2=240, box_standard mid=(15+20)/2=17.5
        # items_mid=257.5, fixed=150, mid=407.5
        # 407.5*0.85=346.375→346, 407.5*1.15=468.625→469
        assert result["estimate_min"] == 346
        assert result["estimate_max"] == 469

    def test_with_unknown_item_ignored(self):
        """Unknown items in the list are silently ignored."""
        result = estimate_price(items=["unknown_item"])
        assert result["estimate_min"] == 127  # same as base-only

    def test_extras_assembly(self):
        """Assembly extra maps to disassembly adjustment (+80)."""
        result = estimate_price(extras=["assembly"])
        # 150 + 80 = 230 → 230*0.85=195, 230*1.15=265
        assert result["estimate_min"] == 195
        assert result["estimate_max"] == 265

    def test_extras_client_helps_discount(self):
        """Client-helps gives a discount."""
        result = estimate_price(extras=["client_helps"])
        # 150 + (-60) = 90 → 90*0.85=76, 90*1.15=104
        assert result["estimate_min"] == 76
        assert result["estimate_max"] == 104

    def test_extras_unknown_ignored(self):
        """Unknown extras are ignored (e.g. 'loaders' has no price adjustment)."""
        result = estimate_price(extras=["loaders"])
        assert result["estimate_min"] == 127  # same as base-only

    def test_custom_pricing_config(self):
        """Custom pricing config overrides defaults."""
        custom = PricingConfig(base_callout=300, estimate_margin=0.10)
        result = estimate_price(pricing=custom)
        # 300 * 0.90 = 270, 300 * 1.10 = 330
        assert result["estimate_min"] == 270
        assert result["estimate_max"] == 330

    def test_breakdown_returned(self):
        """Breakdown dict is included in the result."""
        result = estimate_price(
            floor_from=3, has_elevator_from=False,
            extras=["assembly"],
        )
        bd = result["breakdown"]
        assert bd["base"] == 150
        assert bd["floor_surcharge"] == 100  # (3-1)*50
        assert bd["extras_adj"] == 80  # assembly → disassembly
        assert bd["pickup_fee"] == 0
        assert bd["items_mid"] == 0.0
        assert bd["distance_factor"] == 1.0

    def test_estimate_min_never_negative(self):
        """With a large discount, estimate_min should never go below 0."""
        custom = PricingConfig(base_callout=30, estimate_margin=0.50)
        result = estimate_price(extras=["client_helps"], pricing=custom)
        assert result["estimate_min"] >= 0


class TestParseFloorInfo:
    """Tests for parse_floor_info() helper."""

    def test_empty_string_defaults(self):
        floor, elev = parse_floor_info("")
        assert floor == 1
        assert elev is True

    def test_floor_number_with_elevator(self):
        floor, elev = parse_floor_info("3 этаж, лифт есть")
        assert floor == 3
        assert elev is True

    def test_floor_number_no_elevator(self):
        floor, elev = parse_floor_info("5 этаж, без лифта")
        assert floor == 5
        assert elev is False

    def test_floor_number_english(self):
        floor, elev = parse_floor_info("floor 4, no elevator")
        assert floor == 4
        assert elev is False

    def test_private_house(self):
        floor, elev = parse_floor_info("частный дом")
        assert floor == 1
        assert elev is True

    def test_private_house_english(self):
        floor, elev = parse_floor_info("private house")
        assert floor == 1
        assert elev is True

    def test_just_number(self):
        """Bare number → that's the floor."""
        floor, elev = parse_floor_info("3")
        assert floor == 3
        assert elev is True  # default: assume elevator

    def test_elevator_no_mention(self):
        """Floor mentioned but no elevator info → assume elevator."""
        floor, elev = parse_floor_info("4 этаж")
        assert floor == 4
        assert elev is True

    def test_no_elevator_hebrew(self):
        floor, elev = parse_floor_info("קומה 3 בלי מעלית")
        assert floor == 3
        assert elev is False

    def test_elevator_yes_hebrew(self):
        floor, elev = parse_floor_info("קומה 2 יש מעלית")
        assert floor == 2
        assert elev is True

    def test_ground_english(self):
        floor, elev = parse_floor_info("ground floor")
        assert floor == 1
        assert elev is True


class TestEstimateStepFlow:
    """Tests for the ESTIMATE step in the handler."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def _state_at_estimate(self):
        """Create a state positioned at the estimate step with sample data."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"
        state.data.floor_from = "3 этаж, без лифта"
        state.data.floor_to = "5 этаж, лифт есть"
        # Go through extras to estimate
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        return state, reply

    def test_estimate_shows_price_range(self):
        state, reply = self._state_at_estimate()
        assert "₪" in reply
        assert state.data.custom["estimate_min"] > 0
        assert state.data.custom["estimate_max"] > 0

    def test_confirm_goes_to_done(self):
        state, _ = self._state_at_estimate()
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "done"
        assert done is True

    def test_restart_goes_to_cargo(self):
        state, _ = self._state_at_estimate()
        old_lead = state.lead_id
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "cargo"
        assert state.lead_id != old_lead  # new session
        assert not done

    def test_invalid_input_stays(self):
        state, _ = self._state_at_estimate()
        state, reply, done = self.handler.handle_text(state, "maybe")
        assert state.step == "estimate"
        assert not done

    def test_estimate_with_floor_surcharge(self):
        """Floor 3 without elevator → surcharge reflected in estimate."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"
        state.data.floor_from = "3 этаж, без лифта"
        state.data.floor_to = "1 этаж, лифт есть"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # Floor from: (3-1)*50=100 surcharge
        # base=150+100=250 → 250*0.85=212, 250*1.15=288
        assert state.data.custom["estimate_min"] == 212
        assert state.data.custom["estimate_max"] == 288

    def test_estimate_with_assembly_extra(self):
        """Assembly extra → +80 reflected in estimate."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "estimate"
        # base=150 + disassembly=80 = 230 → 195–265
        assert state.data.custom["estimate_min"] == 195
        assert state.data.custom["estimate_max"] == 265

    def test_estimate_stored_in_custom(self):
        state, _ = self._state_at_estimate()
        assert "estimate_min" in state.data.custom
        assert "estimate_max" in state.data.custom
        assert state.data.custom["estimate_currency"] == "ILS"
        assert isinstance(state.data.custom["estimate_breakdown"], dict)
        assert "base" in state.data.custom["estimate_breakdown"]

    def test_estimate_english(self):
        state = self.handler.new_session("t1", "chat1", language="en")
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert "Estimated" in reply
        assert "₪" in reply

    def test_estimate_hebrew(self):
        state = self.handler.new_session("t1", "chat1", language="he")
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert "₪" in reply
        assert "עלות" in reply


class TestPhase3TranslationKeys:
    """Verify all Phase 3 translation keys exist."""

    def test_all_phase3_keys_resolve(self):
        keys = ["estimate_summary", "err_estimate_choice"]
        for key in keys:
            for lang in ("ru", "en", "he"):
                text = get_text(key, lang)
                assert text != key, f"Key {key!r} not found for lang={lang}"


class TestFullFlowWithEstimate:
    """Complete end-to-end flow with Phase 3 estimate step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_complete_flow_with_estimate(self):
        """WELCOME → ... → EXTRAS → ESTIMATE → DONE."""
        state = self.handler.new_session("t1", "chat1")

        # WELCOME → CARGO
        state, reply, done = self.handler.handle_text(state, "привет")
        assert state.step == "cargo"

        # CARGO → PICKUP_COUNT (items detected → volume skipped)
        state, reply, done = self.handler.handle_text(state, "Диван, холодильник, 5 коробок")
        assert state.step == "pickup_count"

        # PICKUP_COUNT → ADDR_FROM (single pickup)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "addr_from"

        # ADDR_FROM → FLOOR_FROM
        state, reply, done = self.handler.handle_text(state, "Хайфа, ул. Герцль 10")
        assert state.step == "floor_from"

        # FLOOR_FROM → ADDR_TO
        state, reply, done = self.handler.handle_text(state, "3 этаж, без лифта")
        assert state.step == "addr_to"

        # ADDR_TO → FLOOR_TO
        state, reply, done = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"

        # FLOOR_TO → DATE
        state, reply, done = self.handler.handle_text(state, "5 этаж, лифт есть")
        assert state.step == "date"

        # DATE → TIME_SLOT (tomorrow)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "time_slot"

        # TIME_SLOT → PHOTO_MENU (morning)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"

        # PHOTO_MENU → EXTRAS (no photos)
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "extras"

        # EXTRAS → ESTIMATE
        state, reply, done = self.handler.handle_text(state, "1 3")
        assert state.step == "estimate"
        assert not done
        assert "₪" in reply
        # Floor from: 3 этаж, без лифта → floor=3, no elevator → (3-1)*50=100
        # Floor to: 5 этаж, лифт есть → floor=5, elevator → no surcharge
        # Volume: inferred "large" from items (2 heavy: sofa+fridge) → surcharge=350
        # Extras: loaders (no pricing adj), packing (no pricing adj) → 0
        # Items (Phase 10): Диван→sofa_large_3_seat(225) + холодильник→fridge_single_door(240) + 5 коробок→box_standard(87.5)
        # Route: Хайфа→Тель-Авив = inter_region_short → route_fee=500, route_minimum=1000
        # fixed=150+100+350+500=1100, items_mid=552.5, mid=1652.5
        # G6 complexity: score=2 (volume_large + route), multiplier=1.18, risk=1.08
        # mid=1652.5*1.18*1.08=2105.946 → min=floor(2105.946*0.85)=1790, max=ceil(2105.946*1.15)=2422
        assert state.data.custom["estimate_min"] == 1790
        assert state.data.custom["estimate_max"] == 2422

        # ESTIMATE → DONE (confirm)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "done"
        assert done is True

        # Verify payload contains estimate
        payload = self.handler.get_payload(state)
        custom = payload["data"]["custom"]
        assert custom["estimate_min"] == 1790
        assert custom["estimate_max"] == 2422
        assert custom["estimate_currency"] == "ILS"


# ============================================================================
# Phase 4: Multi-pickup tests
# ============================================================================


class TestPickupCountStep:
    """Tests for the PICKUP_COUNT step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_valid_count_1(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "addr_from"
        assert state.data.custom["pickup_count"] == 1
        assert state.data.custom["pickups"] == []
        assert not done

    def test_valid_count_2(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "addr_from"
        assert state.data.custom["pickup_count"] == 2

    def test_valid_count_3(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, reply, done = self.handler.handle_text(state, "3")
        assert state.step == "addr_from"
        assert state.data.custom["pickup_count"] == 3

    def test_invalid_count_0(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, reply, done = self.handler.handle_text(state, "0")
        assert state.step == "pickup_count"  # stays
        assert not done

    def test_invalid_count_4(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "pickup_count"  # stays

    def test_invalid_count_text(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, reply, done = self.handler.handle_text(state, "two")
        assert state.step == "pickup_count"

    def test_cargo_with_items_skips_volume(self):
        """CARGO → PICKUP_COUNT when items detected (volume not needed)."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, "Диван и коробки")
        assert state.step == "pickup_count"

    def test_cargo_vague_goes_to_volume(self):
        """CARGO → VOLUME when no rooms AND no items detected."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, "Всякие вещи и мебель")
        assert state.step == "volume"


class TestSinglePickupFlow:
    """Single-pickup (count=1) should be identical to the old flow."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_single_pickup_no_regression(self):
        """count=1: same as before — addr_from → floor_from → addr_to."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"

        # PICKUP_COUNT → ADDR_FROM
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "addr_from"
        assert state.data.custom["pickup_count"] == 1

        # ADDR_FROM → FLOOR_FROM
        state, reply, done = self.handler.handle_text(state, "Хайфа, Герцль 10")
        assert state.step == "floor_from"
        assert state.data.addr_from == "Хайфа, Герцль 10"

        # FLOOR_FROM → ADDR_TO (skips addr_from_2/3)
        state, reply, done = self.handler.handle_text(state, "3 этаж, лифт есть")
        assert state.step == "addr_to"
        assert state.data.floor_from == "3 этаж, лифт есть"
        # First pickup stored in pickups list
        assert len(state.data.custom["pickups"]) == 1
        assert state.data.custom["pickups"][0]["addr"] == "Хайфа, Герцль 10"
        assert state.data.custom["pickups"][0]["floor"] == "3 этаж, лифт есть"

    def test_backward_compat_no_pickup_count(self):
        """Session at addr_from without pickup_count → defaults to 1."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        # No pickup_count in custom → _get_pickup_count returns 1

        state, reply, done = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        assert state.step == "floor_from"

        state, reply, done = self.handler.handle_text(state, "2 этаж, лифт есть")
        # Should go to addr_to (count defaults to 1)
        assert state.step == "addr_to"


class TestTwoPickupFlow:
    """Full 2-pickup flow end-to-end."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_two_pickup_flow(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"

        # PICKUP_COUNT (2)
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "addr_from"
        assert state.data.custom["pickup_count"] == 2

        # ADDR_FROM (first pickup)
        state, reply, done = self.handler.handle_text(state, "Хайфа, Герцль 10")
        assert state.step == "floor_from"

        # FLOOR_FROM (first pickup) → should go to ADDR_FROM_2
        state, reply, done = self.handler.handle_text(state, "3 этаж, без лифта")
        assert state.step == "addr_from_2"
        assert len(state.data.custom["pickups"]) == 1

        # ADDR_FROM_2 (second pickup)
        state, reply, done = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        assert state.step == "floor_from_2"

        # FLOOR_FROM_2 → ADDR_TO
        state, reply, done = self.handler.handle_text(state, "1 этаж, лифт есть")
        assert state.step == "addr_to"
        assert len(state.data.custom["pickups"]) == 2
        assert state.data.custom["pickups"][1]["addr"] == "Хайфа, Бен-Гурион 5"
        assert state.data.custom["pickups"][1]["floor"] == "1 этаж, лифт есть"

        # ADDR_TO
        state, reply, done = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"

        # FLOOR_TO → DATE
        state, reply, done = self.handler.handle_text(state, "5 этаж, лифт есть")
        assert state.step == "date"

    def test_two_pickup_estimate_includes_extra_fee(self):
        """2 pickups → extra_pickups=1 → +70 ILS + route fee."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"

        state, _, _ = self.handler.handle_text(state, "2")
        state, _, _ = self.handler.handle_text(state, "Хайфа, Герцль 10")
        state, _, _ = self.handler.handle_text(state, "1 этаж, лифт есть")
        state, _, _ = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        state, _, _ = self.handler.handle_text(state, "1 этаж, лифт есть")
        state, _, _ = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        state, _, _ = self.handler.handle_text(state, "2 этаж, лифт есть")

        # Fast-forward through scheduling
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # base=150 + extra_pickup=70 + route_fee=500 (Хайфа→Тель-Авив, inter_region_short) = 720
        # 720*0.85=612, 720*1.15=828 → route_minimum=1000 applies
        assert state.data.custom["estimate_min"] == 1000
        assert state.data.custom["estimate_max"] == 1000


class TestThreePickupFlow:
    """Full 3-pickup flow end-to-end."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_three_pickup_flow(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"

        # PICKUP_COUNT (3)
        state, reply, done = self.handler.handle_text(state, "3")
        assert state.step == "addr_from"

        # Pickup 1
        state, reply, done = self.handler.handle_text(state, "Хайфа, Герцль 10")
        assert state.step == "floor_from"
        state, reply, done = self.handler.handle_text(state, "3 этаж, без лифта")
        assert state.step == "addr_from_2"

        # Pickup 2
        state, reply, done = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        assert state.step == "floor_from_2"
        state, reply, done = self.handler.handle_text(state, "1 этаж, лифт есть")
        assert state.step == "addr_from_3"

        # Pickup 3
        state, reply, done = self.handler.handle_text(state, "Кармиэль, центр")
        assert state.step == "floor_from_3"
        state, reply, done = self.handler.handle_text(state, "2 этаж, без лифта")
        assert state.step == "addr_to"

        # Verify all 3 pickups stored
        assert len(state.data.custom["pickups"]) == 3
        assert state.data.custom["pickups"][0]["addr"] == "Хайфа, Герцль 10"
        assert state.data.custom["pickups"][1]["addr"] == "Хайфа, Бен-Гурион 5"
        assert state.data.custom["pickups"][2]["addr"] == "Кармиэль, центр"

    def test_three_pickup_estimate_fee_and_floor_surcharges(self):
        """3 pickups → extra_pickups=2 → +140 ILS; floor surcharges + route fee."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"

        state, _, _ = self.handler.handle_text(state, "3")
        # Pickup 1: floor 3, no elevator → (3-1)*50 = 100
        state, _, _ = self.handler.handle_text(state, "Хайфа, Герцль 10")
        state, _, _ = self.handler.handle_text(state, "3 этаж, без лифта")
        # Pickup 2: floor 1, with elevator → 0
        state, _, _ = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        state, _, _ = self.handler.handle_text(state, "1 этаж, лифт есть")
        # Pickup 3: floor 4, no elevator → (4-1)*50 = 150
        state, _, _ = self.handler.handle_text(state, "Кармиэль, центр")
        state, _, _ = self.handler.handle_text(state, "4 этаж, без лифта")
        # Delivery: floor 2, with elevator → 0
        state, _, _ = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        state, _, _ = self.handler.handle_text(state, "2 этаж, лифт есть")

        # Skip scheduling to extras
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # base=150 + floor_surcharge=(100+0+150)=250 + extra_pickups=2*70=140
        # Route: Хайфа→Тель-Авив = inter_region_short → route_fee=500, route_minimum=1000
        # total=150+250+140+500=1040 → 1040*0.85=884, 1040*1.15=1196
        # route_minimum=1000 → estimate_min=1000
        assert state.data.custom["estimate_min"] == 1000
        assert state.data.custom["estimate_max"] == 1196


class TestMultiPickupEstimatePricing:
    """Test estimate_price() with pickup_floors parameter."""

    def test_single_pickup_floor(self):
        """Single pickup floor → same as legacy floor_from behavior."""
        result = estimate_price(
            pickup_floors=[(3, False)],
            floor_to=1,
            has_elevator_to=True,
        )
        # (3-1)*50=100 surcharge, base=150+100=250 → 212–288
        assert result["estimate_min"] == 212
        assert result["estimate_max"] == 288

    def test_multiple_pickup_floors(self):
        """Multiple pickup floors: each contributes a surcharge (high-floor guard on floor 5)."""
        result = estimate_price(
            pickup_floors=[(3, False), (5, False)],
            floor_to=1,
            has_elevator_to=True,
            extra_pickups=1,
        )
        # pickup1: (3-1)*50=100, pickup2: (5-1)*50=200 → total floor=300
        # High-floor guard: floor 5 ≥ threshold 5, no elevator → ×1.5 → 300*1.5=450
        # extra_pickups: 1*70=70
        # base=150+450+70=670 → 670*0.85=569, 670*1.15=771 (ceil)
        assert result["estimate_min"] == 569
        assert result["estimate_max"] == 771

    def test_pickup_floors_with_elevator_no_charge(self):
        """Pickup floors with elevator → no surcharge."""
        result = estimate_price(
            pickup_floors=[(5, True), (3, True)],
            floor_to=1,
            has_elevator_to=True,
            extra_pickups=1,
        )
        # No floor surcharge (all have elevator), +70 for extra pickup
        # 150+70=220 → 220*0.85=187, 220*1.15=253
        assert result["estimate_min"] == 187
        assert result["estimate_max"] == 253

    def test_pickup_floors_mixed(self):
        """Mix of elevator and no-elevator pickups."""
        result = estimate_price(
            pickup_floors=[(4, False), (2, True), (3, False)],
            floor_to=1,
            has_elevator_to=True,
            extra_pickups=2,
        )
        # pickup1: (4-1)*50=150, pickup2: elevator→0, pickup3: (3-1)*50=100
        # floor_surcharge=250, extra_pickups=2*70=140
        # 150+250+140=540 → 459–621
        assert result["estimate_min"] == 459
        assert result["estimate_max"] == 621

    def test_backward_compat_no_pickup_floors(self):
        """When pickup_floors is None, uses legacy floor_from/has_elevator_from."""
        result = estimate_price(
            floor_from=4,
            has_elevator_from=False,
            floor_to=1,
            has_elevator_to=True,
        )
        # (4-1)*50=150, base=150+150=300 → 255–345
        assert result["estimate_min"] == 255
        assert result["estimate_max"] == 345

    def test_delivery_floor_surcharge_with_pickup_floors(self):
        """Delivery floor surcharge is independent of pickup_floors."""
        result = estimate_price(
            pickup_floors=[(1, True)],
            floor_to=4,
            has_elevator_to=False,
        )
        # pickup: no surcharge (floor 1), delivery: (4-1)*50=150
        # 150+150=300 → 255–345
        assert result["estimate_min"] == 255
        assert result["estimate_max"] == 345


class TestMultiPickupValidationErrors:
    """Test validation on multi-pickup steps."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_addr_from_2_too_short(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from_2"
        state, reply, done = self.handler.handle_text(state, "ok")
        assert state.step == "addr_from_2"  # stays

    def test_floor_from_2_too_short(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "floor_from_2"
        state.data.custom["_pending_addr_2"] = "Test addr"
        state, reply, done = self.handler.handle_text(state, "")
        assert state.step == "floor_from_2"  # stays

    def test_addr_from_3_too_short(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from_3"
        state, reply, done = self.handler.handle_text(state, "da")
        assert state.step == "addr_from_3"  # stays

    def test_floor_from_3_too_short(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "floor_from_3"
        state.data.custom["_pending_addr_3"] = "Test addr"
        state, reply, done = self.handler.handle_text(state, "")
        assert state.step == "floor_from_3"  # stays


class TestMultiPickupNumberedQuestions:
    """Test that multi-pickup steps show numbered questions."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_addr_from_2_shows_number(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, _, _ = self.handler.handle_text(state, "2")
        state, _, _ = self.handler.handle_text(state, "Хайфа, Герцль 10")
        state, reply, _ = self.handler.handle_text(state, "3 этаж, лифт есть")
        assert state.step == "addr_from_2"
        assert "#2" in reply  # {n} replaced with 2

    def test_floor_from_2_shows_number(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from_2"
        state, reply, _ = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        assert state.step == "floor_from_2"
        assert "#2" in reply

    def test_addr_from_3_shows_number(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, _, _ = self.handler.handle_text(state, "3")
        state, _, _ = self.handler.handle_text(state, "Хайфа, Герцль 10")
        state, _, _ = self.handler.handle_text(state, "3 этаж, лифт есть")
        state, _, _ = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        state, reply, _ = self.handler.handle_text(state, "1 этаж, лифт есть")
        assert state.step == "addr_from_3"
        assert "#3" in reply

    def test_floor_from_3_shows_number(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from_3"
        state, reply, _ = self.handler.handle_text(state, "Кармиэль, центр")
        assert state.step == "floor_from_3"
        assert "#3" in reply


class TestPhase4TranslationKeys:
    """Verify all Phase 4 translation keys exist."""

    def test_all_phase4_keys_resolve(self):
        keys = ["q_pickup_count", "err_pickup_count", "q_addr_from_n", "q_floor_from_n"]
        for key in keys:
            for lang in ("ru", "en", "he"):
                text = get_text(key, lang)
                assert text != key, f"Key {key!r} not found for lang={lang}"

    def test_numbered_question_has_placeholder(self):
        """q_addr_from_n and q_floor_from_n must contain {n} placeholder."""
        for key in ("q_addr_from_n", "q_floor_from_n"):
            for lang in ("ru", "en", "he"):
                text = get_text(key, lang)
                assert "{n}" in text, f"{key} for lang={lang} missing {{n}} placeholder"


class TestFullFlowTwoPickupsWithEstimate:
    """Full end-to-end flow: 2 pickups through to DONE."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_two_pickup_complete_flow(self):
        state = self.handler.new_session("t1", "chat1")

        # WELCOME → CARGO
        state, reply, done = self.handler.handle_text(state, "привет")
        assert state.step == "cargo"

        # CARGO → PICKUP_COUNT (items detected → skip volume)
        state, reply, done = self.handler.handle_text(state, "Диван и 3 коробки")
        assert state.step == "pickup_count"

        # PICKUP_COUNT (2)
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "addr_from"

        # Pickup 1: address + floor
        state, reply, done = self.handler.handle_text(state, "Хайфа, Герцль 10")
        assert state.step == "floor_from"
        state, reply, done = self.handler.handle_text(state, "3 этаж, без лифта")
        assert state.step == "addr_from_2"

        # Pickup 2: address + floor
        state, reply, done = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        assert state.step == "floor_from_2"
        state, reply, done = self.handler.handle_text(state, "1 этаж, лифт есть")
        assert state.step == "addr_to"

        # Delivery: address + floor
        state, reply, done = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"
        state, reply, done = self.handler.handle_text(state, "2 этаж, лифт есть")
        assert state.step == "date"

        # Scheduling: tomorrow + morning
        state, reply, done = self.handler.handle_text(state, "1")  # tomorrow
        assert state.step == "time_slot"
        state, reply, done = self.handler.handle_text(state, "1")  # morning
        assert state.step == "photo_menu"

        # No photos
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "extras"

        # No extras → ESTIMATE
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert "₪" in reply
        # pickup1: (3-1)*50=100, pickup2: floor 1→0, delivery: floor 2→0
        # extra_pickups=1 → 70, volume: None → 0
        # Items (Phase 10): Диван→sofa_large_3_seat(225) + 3 коробки→box_standard(52.5)
        # Route: Хайфа→Тель-Авив = inter_region_short → route_fee=500, route_minimum=1000
        # fixed=150+100+70+500=820, items_mid=277.5, mid=1097.5
        # 1097.5*0.85=932, 1097.5*1.15=1263 (ceil)
        # route_minimum=1000 → estimate_min=1000
        assert state.data.custom["estimate_min"] == 1000
        assert state.data.custom["estimate_max"] == 1263

        # ESTIMATE → DONE
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "done"
        assert done is True

        # Verify pickups in payload
        payload = self.handler.get_payload(state)
        pickups = payload["data"]["custom"]["pickups"]
        assert len(pickups) == 2
        assert pickups[0]["addr"] == "Хайфа, Герцль 10"
        assert pickups[1]["addr"] == "Хайфа, Бен-Гурион 5"


# ============================================================================
# Phase 5: Geo location support tests
# ============================================================================


class TestHandleLocationAddrFrom:
    """Test handle_location() on ADDR_FROM step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_geo_on_addr_from_stores_and_advances(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "floor_from"
        assert not done
        assert "32.79400" in state.data.addr_from
        assert "34.98900" in state.data.addr_from
        assert state.data.custom["geo_points"]["pickup_1"]["lat"] == 32.794
        assert state.data.custom["geo_points"]["pickup_1"]["lon"] == 34.989

    def test_geo_on_addr_from_with_name(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_location(
            state, 32.794, 34.989, name="Haifa Port"
        )
        assert "Haifa Port" in state.data.addr_from
        assert state.data.custom["geo_points"]["pickup_1"]["name"] == "Haifa Port"

    def test_geo_on_addr_from_with_address(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_location(
            state, 32.794, 34.989, address="Herzl St 10"
        )
        # address used as fallback for name in text representation
        assert "Herzl St 10" in state.data.addr_from
        assert state.data.custom["geo_points"]["pickup_1"]["address"] == "Herzl St 10"

    def test_geo_reply_contains_location_saved(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        # Should contain the "location saved" confirmation
        assert "📍" in reply


class TestHandleLocationAddrTo:
    """Test handle_location() on ADDR_TO step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_geo_on_addr_to_stores_and_advances(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_to"
        state, reply, done = self.handler.handle_location(state, 32.080, 34.780)
        assert state.step == "floor_to"
        assert not done
        assert "32.08000" in state.data.addr_to
        assert state.data.custom["geo_points"]["delivery"]["lat"] == 32.080
        assert state.data.custom["geo_points"]["delivery"]["lon"] == 34.780


class TestHandleLocationMultiPickup:
    """Test handle_location() on ADDR_FROM_2 and ADDR_FROM_3 steps."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_geo_on_addr_from_2(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from_2"
        state.data.custom["pickups"] = [{"addr": "first", "floor": "1"}]
        state, reply, done = self.handler.handle_location(state, 32.800, 35.000)
        assert state.step == "floor_from_2"
        assert "32.80000" in state.data.custom["_pending_addr_2"]
        assert state.data.custom["geo_points"]["pickup_2"]["lat"] == 32.800

    def test_geo_on_addr_from_3(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from_3"
        state, reply, done = self.handler.handle_location(state, 32.900, 35.100)
        assert state.step == "floor_from_3"
        assert "32.90000" in state.data.custom["_pending_addr_3"]
        assert state.data.custom["geo_points"]["pickup_3"]["lat"] == 32.900


class TestHandleLocationIgnoredSteps:
    """Test that handle_location() is ignored on non-address steps."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_geo_on_cargo_ignored(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "cargo"  # stays
        assert not done

    def test_geo_on_floor_from_ignored(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "floor_from"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "floor_from"

    def test_geo_on_date_ignored(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "date"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "date"

    def test_geo_on_extras_ignored(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "extras"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "extras"

    def test_geo_on_pickup_count_ignored(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "pickup_count"

    def test_geo_on_welcome_ignored(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "welcome"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "welcome"


class TestGeoFlowEndToEnd:
    """Full flow mixing text and geo input."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_geo_pickup_text_delivery(self):
        """Pickup via geo, delivery via text."""
        state = self.handler.new_session("t1", "chat1")

        # WELCOME → CARGO → PICKUP_COUNT (items detected → skip volume)
        state, _, _ = self.handler.handle_text(state, "привет")
        state, _, _ = self.handler.handle_text(state, "Диван и 3 коробки")
        assert state.step == "pickup_count"

        # Single pickup
        state, _, _ = self.handler.handle_text(state, "1")
        assert state.step == "addr_from"

        # Pickup 1: geo location
        state, reply, _ = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "floor_from"
        assert "📍" in state.data.addr_from

        # Floor
        state, _, _ = self.handler.handle_text(state, "3 этаж, лифт есть")
        assert state.step == "addr_to"

        # Delivery: text address
        state, _, _ = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"
        state, _, _ = self.handler.handle_text(state, "2 этаж, лифт есть")
        assert state.step == "date"

        # Verify geo stored
        assert "geo_points" in state.data.custom
        assert "pickup_1" in state.data.custom["geo_points"]
        assert "delivery" not in state.data.custom["geo_points"]  # text, no geo

    def test_text_pickup_geo_delivery(self):
        """Pickup via text, delivery via geo."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"

        state, _, _ = self.handler.handle_text(state, "1")
        state, _, _ = self.handler.handle_text(state, "Хайфа, Герцль 10")
        state, _, _ = self.handler.handle_text(state, "3 этаж, лифт есть")
        assert state.step == "addr_to"

        # Delivery via geo
        state, reply, _ = self.handler.handle_location(state, 32.080, 34.780, name="Tel Aviv")
        assert state.step == "floor_to"
        assert "Tel Aviv" in state.data.addr_to

        assert "delivery" in state.data.custom["geo_points"]
        assert state.data.custom["geo_points"]["delivery"]["lat"] == 32.080

    def test_two_pickups_with_geo(self):
        """Two pickups, first with geo, second with text."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "pickup_count"

        state, _, _ = self.handler.handle_text(state, "2")
        assert state.step == "addr_from"

        # Pickup 1: geo
        state, _, _ = self.handler.handle_location(state, 32.794, 34.989)
        assert state.step == "floor_from"
        state, _, _ = self.handler.handle_text(state, "3 этаж, лифт есть")
        assert state.step == "addr_from_2"

        # Pickup 2: text
        state, _, _ = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")
        assert state.step == "floor_from_2"
        state, _, _ = self.handler.handle_text(state, "1 этаж, лифт есть")
        assert state.step == "addr_to"

        # Verify only pickup_1 has geo
        assert "pickup_1" in state.data.custom["geo_points"]
        assert "pickup_2" not in state.data.custom.get("geo_points", {})


class TestPhase5TranslationKeys:
    """Verify all Phase 5 translation keys exist."""

    def test_all_phase5_keys_resolve(self):
        keys = ["info_location_saved", "info_location_ignored"]
        for key in keys:
            for lang in ("ru", "en", "he"):
                text = get_text(key, lang)
                assert text != key, f"Key {key!r} not found for lang={lang}"


# ============================================================================
# Phase 6: Calculator v1.1 — midpoint-based estimate + distance_factor
# ============================================================================


class TestPricingV11Midpoint:
    """Test the v1.1 midpoint-based estimate calculation (Phase 6.2)."""

    def test_single_item_midpoint(self):
        """Single item uses midpoint of (min, max) range."""
        # refrigerator: (200, 280) → mid = 240
        result = estimate_price(items=["fridge_single_door"])
        # fixed=150 + items_mid=240 = 390
        # 390*0.85=331.5→331, 390*1.15=448.5→449
        assert result["estimate_min"] == 331
        assert result["estimate_max"] == 449

    def test_multiple_items_midpoint(self):
        """Multiple items: sum of midpoints."""
        # sofa_2seat (150,200) mid=175, desk (100,150) mid=125
        result = estimate_price(items=["sofa_small_2_seat", "desk"])
        # fixed=150 + items_mid=300 = 450
        # 450*0.85=382.5→382, 450*1.15=517.5→518
        assert result["estimate_min"] == 382
        assert result["estimate_max"] == 518

    def test_items_with_floor_surcharge(self):
        """Items + floor surcharge → both in midpoint."""
        # box_standard (15,20) mid=17.5
        result = estimate_price(
            items=["box_standard"],
            floor_from=3, has_elevator_from=False,
        )
        # fixed=150 + (3-1)*50=100 = 250, items_mid=17.5, mid=267.5
        # 267.5*0.85=227.375→227, 267.5*1.15=307.625→308
        assert result["estimate_min"] == 227
        assert result["estimate_max"] == 308

    def test_items_with_extras_and_pickups(self):
        """Items + extras + extra pickups → all combined in midpoint."""
        # chair (20,40) mid=30
        result = estimate_price(
            items=["chair"],
            extras=["assembly"],
            extra_pickups=1,
        )
        # fixed=150 + assembly=80 + pickup=70 = 300
        # items_mid=30, mid=330
        # 330*0.85=280.5→280, 330*1.15=379.5→380
        assert result["estimate_min"] == 280
        assert result["estimate_max"] == 380

    def test_large_item_set_midpoint(self):
        """Many items — midpoint reduces spread vs old v1.0 approach."""
        items = ["fridge_single_door", "sofa_large_3_seat", "wardrobe_3_doors", "bed_double"]
        result = estimate_price(items=items)
        # refrigerator mid=240, sofa_3seat mid=225, wardrobe_large mid=325, bed_double mid=215
        # items_mid = 1005
        # fixed=150, mid=1155
        # floor(1155*0.85)=floor(981.75)=981, ceil(1155*1.15)=ceil(1328.25)=1329
        assert result["estimate_min"] == 981
        assert result["estimate_max"] == 1329

    def test_symmetric_margin(self):
        """Margin is symmetric: same % above and below midpoint."""
        result = estimate_price(items=["fridge_single_door"])
        # mid=390
        mid = 390
        assert mid - result["estimate_min"] <= mid * 0.15 + 1  # allow rounding
        assert result["estimate_max"] - mid <= mid * 0.15 + 1

    def test_no_items_unchanged(self):
        """Without items, result is identical to v1.0 (base ±margin)."""
        result = estimate_price()
        assert result["estimate_min"] == 127
        assert result["estimate_max"] == 173


class TestDistanceFactor:
    """Test the distance_factor pricing multiplier (Phase 6.3)."""

    def test_default_factor_is_one(self):
        """Default distance_factor is 1.0 — no change."""
        assert HAIFA_METRO_PRICING.distance_factor == 1.0

    def test_factor_one_same_as_default(self):
        """Explicit factor=1.0 gives same result as default."""
        result_default = estimate_price()
        result_explicit = estimate_price(pricing=PricingConfig(distance_factor=1.0))
        assert result_default["estimate_min"] == result_explicit["estimate_min"]
        assert result_default["estimate_max"] == result_explicit["estimate_max"]

    def test_factor_above_one_increases(self):
        """distance_factor > 1 increases the estimate."""
        cfg = PricingConfig(distance_factor=1.2)
        result = estimate_price(pricing=cfg)
        # mid = 150 * 1.2 = 180
        # 180*0.85=153, 180*1.15=207
        assert result["estimate_min"] == 153
        assert result["estimate_max"] == 207

    def test_factor_with_items(self):
        """distance_factor applies to the total mid (fixed + items)."""
        cfg = PricingConfig(distance_factor=1.5)
        result = estimate_price(items=["fridge_single_door"], pricing=cfg)
        # fixed=150 + items_mid=240 = 390
        # 390 * 1.5 = 585
        # 585*0.85=497.25→497, 585*1.15=672.75→673
        assert result["estimate_min"] == 497
        assert result["estimate_max"] == 673

    def test_factor_in_breakdown(self):
        """distance_factor appears in the breakdown dict."""
        cfg = PricingConfig(distance_factor=1.25)
        result = estimate_price(pricing=cfg)
        assert result["breakdown"]["distance_factor"] == 1.25

    def test_factor_with_floor_surcharges(self):
        """distance_factor multiplies the entire mid including surcharges."""
        cfg = PricingConfig(distance_factor=1.3)
        result = estimate_price(
            pickup_floors=[(3, False)],
            floor_to=1,
            has_elevator_to=True,
            pricing=cfg,
        )
        # base=150 + floor=(3-1)*50=100 = 250
        # 250 * 1.3 = 325
        # 325*0.85=276.25→276, 325*1.15=373.75→374
        assert result["estimate_min"] == 276
        assert result["estimate_max"] == 374

    def test_haifa_metro_classification_values(self):
        """Verify expected distance_factor tiers can be used."""
        # same-city: 1.0, metro edge: 1.1, outside metro: 1.25
        for factor in (1.0, 1.1, 1.25):
            cfg = PricingConfig(distance_factor=factor)
            result = estimate_price(pricing=cfg)
            assert result["estimate_min"] > 0
            assert result["estimate_max"] > result["estimate_min"]

    def test_items_mid_in_breakdown(self):
        """items_mid (not items_range) appears in v1.1 breakdown."""
        result = estimate_price(items=["fridge_single_door", "box_standard"])
        bd = result["breakdown"]
        assert "items_mid" in bd
        # refrigerator mid=240, box_standard mid=17.5
        assert bd["items_mid"] == 257.5
        assert "items_range" not in bd  # v1.0 key removed


# ============================================================================
# Reverse geocoding: handler integration tests
# ============================================================================


class TestGeocodedAddressDisplay:
    """Test handler behavior when geocoded address is provided."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_addr_from_with_geocoded_address(self):
        """Geocoded address becomes the addr_from text (no raw coords)."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_location(
            state, 32.794, 34.989, address="Herzl 10, Haifa"
        )
        assert state.step == "floor_from"
        # Address shown without raw coordinates
        assert state.data.addr_from == "📍 Herzl 10, Haifa"
        assert "32.794" not in state.data.addr_from
        # Coordinates still stored in geo_points
        assert state.data.custom["geo_points"]["pickup_1"]["lat"] == 32.794
        assert state.data.custom["geo_points"]["pickup_1"]["address"] == "Herzl 10, Haifa"

    def test_addr_to_with_geocoded_address(self):
        """Delivery address shows geocoded text."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_to"
        state, reply, done = self.handler.handle_location(
            state, 32.080, 34.780, address="Dizengoff 50, Tel Aviv"
        )
        assert state.step == "floor_to"
        assert state.data.addr_to == "📍 Dizengoff 50, Tel Aviv"
        assert state.data.custom["geo_points"]["delivery"]["address"] == "Dizengoff 50, Tel Aviv"

    def test_addr_from_no_address_shows_coords(self):
        """Without geocoded address, raw coordinates are shown (fallback)."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_location(state, 32.794, 34.989)
        assert "32.79400" in state.data.addr_from
        assert "34.98900" in state.data.addr_from

    def test_name_takes_priority_over_address(self):
        """When both name and address provided, name is used for display."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_location(
            state, 32.794, 34.989, name="Haifa Port", address="Port Rd 1"
        )
        # name is used in format (handler passes name or address, name wins)
        assert "Haifa Port" in state.data.addr_from
        # Both stored in geo_points
        assert state.data.custom["geo_points"]["pickup_1"]["name"] == "Haifa Port"
        assert state.data.custom["geo_points"]["pickup_1"]["address"] == "Port Rd 1"

    def test_multi_pickup_geocoded_address(self):
        """Geocoded address on addr_from_2 step."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from_2"
        state.data.custom["pickups"] = [{"addr": "first", "floor": "1"}]
        state, reply, done = self.handler.handle_location(
            state, 32.800, 35.000, address="Ben Gurion 5, Haifa"
        )
        assert state.step == "floor_from_2"
        assert state.data.custom["_pending_addr_2"] == "📍 Ben Gurion 5, Haifa"
        assert state.data.custom["geo_points"]["pickup_2"]["address"] == "Ben Gurion 5, Haifa"

    def test_full_flow_geo_with_geocoded_address(self):
        """End-to-end: geo pickup with address, text delivery."""
        state = self.handler.new_session("t1", "chat1")

        # WELCOME → CARGO → PICKUP_COUNT (items detected → skip volume)
        state, _, _ = self.handler.handle_text(state, "привет")
        state, _, _ = self.handler.handle_text(state, "Диван и 3 коробки")
        assert state.step == "pickup_count"
        state, _, _ = self.handler.handle_text(state, "1")  # 1 pickup
        assert state.step == "addr_from"

        # Pickup via geo with geocoded address
        state, reply, _ = self.handler.handle_location(
            state, 32.794, 34.989, address="Herzl 10, Haifa"
        )
        assert state.step == "floor_from"
        assert state.data.addr_from == "📍 Herzl 10, Haifa"

        # Floor
        state, _, _ = self.handler.handle_text(state, "3 этаж, лифт есть")
        assert state.step == "addr_to"

        # Delivery via text
        state, _, _ = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"

        # Verify geo_points has address
        gp = state.data.custom["geo_points"]["pickup_1"]
        assert gp["lat"] == 32.794
        assert gp["address"] == "Herzl 10, Haifa"


# ============================================================================
# Phase 8: Regional classification integration tests
# ============================================================================


class TestRegionClassificationIntegration:
    """Phase 8: regional classification integrated into estimate."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def _build_state_at_extras(self, geo_points=None):
        """Walk through the flow to reach the extras step, optionally with geo."""
        state = self.handler.new_session("t1", "chat1")
        state, _, _ = self.handler.handle_text(state, "привет")
        state, _, _ = self.handler.handle_text(state, "Диван и 3 коробки")
        # Items detected → skip volume, go to pickup_count
        state, _, _ = self.handler.handle_text(state, "1")  # 1 pickup

        if geo_points and "pickup_1" in geo_points:
            pt = geo_points["pickup_1"]
            state, _, _ = self.handler.handle_location(
                state, pt["lat"], pt["lon"]
            )
        else:
            state, _, _ = self.handler.handle_text(state, "Хайфа, Герцль 10")

        state, _, _ = self.handler.handle_text(state, "3 этаж, лифт есть")

        if geo_points and "delivery" in geo_points:
            pt = geo_points["delivery"]
            state, _, _ = self.handler.handle_location(
                state, pt["lat"], pt["lon"]
            )
        else:
            state, _, _ = self.handler.handle_text(state, "Хайфа, Бен-Гурион 5")

        state, _, _ = self.handler.handle_text(state, "2 этаж, лифт есть")
        state, _, _ = self.handler.handle_text(state, "1")  # tomorrow
        state, _, _ = self.handler.handle_text(state, "1")  # morning
        state, _, _ = self.handler.handle_text(state, "2")  # no photos

        assert state.step == "extras"
        return state

    def test_no_geo_default_factor(self):
        """Text-only addresses -> distance_factor stays 1.0."""
        state = self._build_state_at_extras()
        state, reply, _ = self.handler.handle_text(state, "4")  # no extras
        assert state.step == "estimate"
        bd = state.data.custom["estimate_breakdown"]
        assert bd["distance_factor"] == 1.0
        assert "region_classifications" not in state.data.custom

    def test_inside_metro_geo_factor_1_0(self):
        """Geo points inside Haifa -> distance_factor 1.0."""
        geo = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},
            "delivery": {"lat": 32.810, "lon": 35.010},
        }
        state = self._build_state_at_extras(geo)
        state, reply, _ = self.handler.handle_text(state, "4")
        bd = state.data.custom["estimate_breakdown"]
        assert bd["distance_factor"] == 1.0
        rc = state.data.custom["region_classifications"]
        assert rc["pickup_1"]["inside_metro"] is True
        assert rc["delivery"]["inside_metro"] is True

    def test_outside_metro_geo_factor_1_2(self):
        """Delivery outside Haifa -> distance_factor 1.2, higher estimate."""
        geo_inside = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},
            "delivery": {"lat": 32.810, "lon": 35.010},
        }
        geo_outside = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},
            "delivery": {"lat": 32.080, "lon": 34.780},  # Tel Aviv
        }

        state_in = self._build_state_at_extras(geo_inside)
        state_in, _, _ = self.handler.handle_text(state_in, "4")
        est_in_max = state_in.data.custom["estimate_max"]

        state_out = self._build_state_at_extras(geo_outside)
        state_out, _, _ = self.handler.handle_text(state_out, "4")
        est_out_max = state_out.data.custom["estimate_max"]

        assert state_out.data.custom["estimate_breakdown"]["distance_factor"] == 1.2
        assert est_out_max > est_in_max

    def test_region_classifications_stored(self):
        """Region info is stored in custom for payload/notification."""
        geo = {
            "pickup_1": {"lat": 32.794, "lon": 34.989},
            "delivery": {"lat": 32.080, "lon": 34.780},
        }
        state = self._build_state_at_extras(geo)
        state, _, _ = self.handler.handle_text(state, "4")
        rc = state.data.custom["region_classifications"]
        assert "pickup_1" in rc
        assert "delivery" in rc
        assert rc["pickup_1"]["inside_metro"] is True
        assert rc["delivery"]["inside_metro"] is False
        assert rc["delivery"]["distance_km"] > 15


# ============================================================================
# Phase 9: Volume category + JSON pricing tests
# ============================================================================


class TestVolumeStepFlow:
    """Tests for the VOLUME step in the handler."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_valid_choice_small(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "pickup_count"
        assert state.data.custom["volume_category"] == "small"
        assert not done

    def test_valid_choice_medium(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "pickup_count"
        assert state.data.custom["volume_category"] == "medium"

    def test_valid_choice_large(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "3")
        assert state.step == "pickup_count"
        assert state.data.custom["volume_category"] == "large"

    def test_valid_choice_xl(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "pickup_count"
        assert state.data.custom["volume_category"] == "xl"

    def test_invalid_choice_0(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "0")
        assert state.step == "volume"  # stays
        assert not done

    def test_invalid_choice_5(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "5")
        assert state.step == "volume"  # stays
        assert not done

    def test_invalid_choice_text(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "big truck")
        assert state.step == "volume"
        assert not done

    def test_cargo_with_items_skips_volume_2(self):
        """CARGO with recognized items → PICKUP_COUNT (skip volume)."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, "Диван и 3 коробки")
        assert state.step == "pickup_count"

    def test_cargo_vague_goes_to_volume_2(self):
        """CARGO with truly vague text (no rooms, no items) → VOLUME."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, "Разные вещи и мебель")
        assert state.step == "volume"
        assert "объём" in reply.lower() or "volume" in reply.lower()

    def test_volume_handler_still_works_for_inflight_sessions(self):
        """VOLUME handler still works for sessions already in 'volume' step."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "volume"
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "pickup_count"
        assert state.data.custom["volume_category"] == "medium"


class TestVolumePricingImpact:
    """Tests that volume category correctly affects pricing."""

    def test_small_volume_no_surcharge(self):
        """Small volume → surcharge = 0."""
        result = estimate_price(volume_category="small")
        assert result["breakdown"]["volume_surcharge"] == 0
        # base only: 150*0.85=127.5→127, 150*1.15=172.5→173
        assert result["estimate_min"] == 127
        assert result["estimate_max"] == 173

    def test_medium_volume_surcharge(self):
        """Medium volume → surcharge = 150."""
        result = estimate_price(volume_category="medium")
        assert result["breakdown"]["volume_surcharge"] == 150
        # 150+150=300 → 300*0.85=255, 300*1.15=345
        assert result["estimate_min"] == 255
        assert result["estimate_max"] == 345

    def test_large_volume_surcharge(self):
        """Large volume → surcharge = 350."""
        result = estimate_price(volume_category="large")
        assert result["breakdown"]["volume_surcharge"] == 350
        # 150+350=500 → 500*0.85=425, 500*1.15=575
        assert result["estimate_min"] == 425
        assert result["estimate_max"] == 575

    def test_xl_volume_surcharge(self):
        """XL volume → surcharge = 500, XL guard floor = 700."""
        result = estimate_price(volume_category="xl")
        assert result["breakdown"]["volume_surcharge"] == 500
        # 150+500=650 → 650*0.85=552.5→552, 650*1.15=747.5→748
        # XL guard floor=700 → estimate_min bumped to 700
        assert result["estimate_min"] == 700
        assert result["estimate_max"] == 748

    def test_no_volume_backward_compat(self):
        """No volume category → surcharge = 0 (backward compat)."""
        result = estimate_price()
        assert result["breakdown"]["volume_surcharge"] == 0

    def test_unknown_volume_category_ignored(self):
        """Unknown volume category → surcharge = 0."""
        result = estimate_price(volume_category="unknown_size")
        assert result["breakdown"]["volume_surcharge"] == 0

    def test_volume_with_floor_surcharge(self):
        """Volume surcharge combines with floor surcharge."""
        result = estimate_price(
            volume_category="large",
            pickup_floors=[(3, False)],
            floor_to=1,
            has_elevator_to=True,
        )
        # floor: (3-1)*50=100, volume: 350
        # 150+100+350=600 → 600*0.85=510, 600*1.15=690
        assert result["breakdown"]["floor_surcharge"] == 100
        assert result["breakdown"]["volume_surcharge"] == 350
        assert result["estimate_min"] == 510
        assert result["estimate_max"] == 690

    def test_volume_in_handler_estimate(self):
        """Volume category set in handler flows into estimate calculation."""
        handler = MovingBotHandler()
        state = handler.new_session("t1", "chat1")
        # Set volume category as handler would
        state.data.custom["volume_category"] = "xl"
        state.step = "extras"
        state, reply, done = handler.handle_text(state, "4")
        assert state.step == "estimate"
        # base=150 + xl=500 = 650
        # XL guard floor=700 → estimate_min bumped to 700
        assert state.data.custom["estimate_breakdown"]["volume_surcharge"] == 500
        assert state.data.custom["estimate_min"] == 700
        assert state.data.custom["estimate_max"] == 748


class TestVolumeTranslationKeys:
    """Verify all Phase 9 translation keys exist."""

    def test_all_phase9_keys_resolve(self):
        keys = ["q_volume", "err_volume_choice"]
        for key in keys:
            for lang in ("ru", "en", "he"):
                text = get_text(key, lang)
                assert text != key, f"Key {key!r} not found for lang={lang}"

    def test_volume_question_english(self):
        text = get_text("q_volume", "en")
        assert "volume" in text.lower()
        assert "small" in text.lower()

    def test_volume_question_hebrew(self):
        text = get_text("q_volume", "he")
        assert "נפח" in text  # volume in Hebrew

    def test_volume_error_russian(self):
        text = get_text("err_volume_choice", "ru")
        assert "1" in text and "4" in text


class TestVolumeChoices:
    """Verify volume choice mappings."""

    def test_volume_choices_keys(self):
        from app.core.bots.moving_bot_choices import VOLUME_CHOICES_DICT
        assert set(VOLUME_CHOICES_DICT.keys()) == {"1", "2", "3", "4"}

    def test_volume_choices_values(self):
        from app.core.bots.moving_bot_choices import VOLUME_CHOICES_DICT
        assert VOLUME_CHOICES_DICT["1"] == "small"
        assert VOLUME_CHOICES_DICT["2"] == "medium"
        assert VOLUME_CHOICES_DICT["3"] == "large"
        assert VOLUME_CHOICES_DICT["4"] == "xl"


class TestPricingConfigJSON:
    """Verify pricing_config.json is correctly loaded."""

    def test_config_loads(self):
        from app.core.bots.moving_bot_pricing import _RAW_CONFIG
        assert "_version" in _RAW_CONFIG
        assert "base" in _RAW_CONFIG
        assert "volume_categories" in _RAW_CONFIG
        assert "extras_adjustments" in _RAW_CONFIG
        assert "item_catalog" in _RAW_CONFIG

    def test_base_values_match(self):
        assert HAIFA_METRO_PRICING.base_callout == 150
        assert HAIFA_METRO_PRICING.no_elevator_per_floor == 50
        assert HAIFA_METRO_PRICING.extra_pickup == 70
        assert HAIFA_METRO_PRICING.estimate_margin == 0.15

    def test_volume_categories_loaded(self):
        from app.core.bots.moving_bot_pricing import VOLUME_CATEGORIES
        assert VOLUME_CATEGORIES["small"] == 0
        assert VOLUME_CATEGORIES["medium"] == 150
        assert VOLUME_CATEGORIES["large"] == 350
        assert VOLUME_CATEGORIES["xl"] == 500

    def test_extras_adjustments_loaded(self):
        assert EXTRAS_ADJUSTMENTS["narrow_stairs"] == 60
        assert EXTRAS_ADJUSTMENTS["no_parking"] == 40
        assert EXTRAS_ADJUSTMENTS["disassembly"] == 80
        assert EXTRAS_ADJUSTMENTS["extra_movers"] == 80
        assert EXTRAS_ADJUSTMENTS["client_helps"] == -60

    def test_item_catalog_loaded(self):
        assert "fridge_single_door" in ITEM_CATALOG
        assert ITEM_CATALOG["fridge_single_door"] == (200, 280)
        assert "box_standard" in ITEM_CATALOG
        assert ITEM_CATALOG["box_standard"] == (15, 20)

    def test_extras_service_mapping_loaded(self):
        from app.core.bots.moving_bot_pricing import _EXTRAS_TO_ADJUSTMENTS
        assert _EXTRAS_TO_ADJUSTMENTS["assembly"] == "disassembly"


class TestFullFlowWithVolume:
    """Complete end-to-end flow with Phase 9 volume step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_complete_flow_xl_volume(self):
        """Full flow with XL volume → higher estimate."""
        state = self.handler.new_session("t1", "chat1")

        # WELCOME → CARGO
        state, reply, done = self.handler.handle_text(state, "привет")
        assert state.step == "cargo"

        # CARGO → PICKUP_COUNT (Phase 11: volume skipped, set manually)
        state, reply, done = self.handler.handle_text(state, "Квартира 3 комнаты, вся мебель")
        assert state.step == "pickup_count"
        # Simulate in-flight volume selection (xl, surcharge=500)
        state.data.custom["volume_category"] = "xl"

        # PICKUP_COUNT → ADDR_FROM (single pickup)
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "addr_from"

        # ADDR_FROM → FLOOR_FROM
        state, reply, done = self.handler.handle_text(state, "Хайфа, ул. Герцль 10")
        assert state.step == "floor_from"

        # FLOOR_FROM → ADDR_TO
        state, reply, done = self.handler.handle_text(state, "1 этаж, лифт есть")
        assert state.step == "addr_to"

        # ADDR_TO → FLOOR_TO
        state, reply, done = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"

        # FLOOR_TO → DATE
        state, reply, done = self.handler.handle_text(state, "1 этаж, лифт есть")
        assert state.step == "date"

        # DATE → TIME_SLOT
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "time_slot"

        # TIME_SLOT → PHOTO_MENU
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"

        # PHOTO_MENU → EXTRAS
        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "extras"

        # EXTRAS → ESTIMATE
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert "₪" in reply
        # base=150 + xl volume=500 + route_fee=500 (Хайфа→Тель-Авив, inter_region_short) = 1150
        # G6 complexity: score=2 (volume_xl + route_inter_region_short) >= threshold 2
        # mid = 1150 * 1.18 * 1.08 = 1465.56
        # 1465.56*0.85=1245.726→1245, 1465.56*1.15=1685.394→1686
        assert state.data.custom["estimate_min"] == 1245
        assert state.data.custom["estimate_max"] == 1686
        assert state.data.custom["estimate_breakdown"]["volume_surcharge"] == 500

        # ESTIMATE → DONE
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "done"
        assert done is True


# ============================================================================
# Phase 10: Multilingual item recognition tests
# ============================================================================


class TestItemAliasLoading:
    """Tests for ITEM_ALIAS_LOOKUP and _build_alias_lookup."""

    def test_lookup_populated(self):
        """Alias lookup should have many entries."""
        assert len(ITEM_ALIAS_LOOKUP) > 50

    def test_alias_reversed_correctly(self):
        """Each alias maps to a valid catalog key."""
        assert ITEM_ALIAS_LOOKUP["fridge"] == "fridge_single_door"
        assert ITEM_ALIAS_LOOKUP["sofa"] == "sofa_large_3_seat"
        assert ITEM_ALIAS_LOOKUP["box"] == "box_standard"
        assert ITEM_ALIAS_LOOKUP["desk"] == "desk"

    def test_all_keys_in_catalog(self):
        """Every canonical key in alias lookup must exist in ITEM_CATALOG."""
        for alias, key in ITEM_ALIAS_LOOKUP.items():
            assert key in ITEM_CATALOG, f"Alias {alias!r} maps to unknown key {key!r}"

    def test_no_duplicate_aliases(self):
        """No alias should map to multiple keys (validated at load time)."""
        seen: dict[str, str] = {}
        for alias, key in ITEM_ALIAS_LOOKUP.items():
            if alias in seen:
                assert False, f"Duplicate alias {alias!r}: {seen[alias]} vs {key}"
            seen[alias] = key

    def test_longest_first_order(self):
        """Aliases should be sorted longest-first for correct matching."""
        keys = list(ITEM_ALIAS_LOOKUP.keys())
        for i in range(len(keys) - 1):
            assert len(keys[i]) >= len(keys[i + 1]), (
                f"Alias order wrong: {keys[i]!r} ({len(keys[i])}) before "
                f"{keys[i + 1]!r} ({len(keys[i + 1])})"
            )

    def test_missing_catalog_key_skipped(self):
        """Aliases referring to unknown catalog keys are silently skipped."""
        result = _build_alias_lookup(
            {"nonexistent_item": ["foo", "bar"]},
            ITEM_CATALOG,
        )
        assert len(result) == 0

    def test_duplicate_alias_raises(self):
        """Duplicate aliases across different keys raise ValueError."""
        with pytest.raises(ValueError, match="Duplicate"):
            _build_alias_lookup(
                {
                    "fridge_single_door": ["fridge"],
                    "dryer": ["fridge"],  # duplicate!
                },
                ITEM_CATALOG,
            )


class TestExtractItems:
    """Tests for extract_items() — multilingual cargo parsing."""

    def test_russian_single_item(self):
        result = extract_items("холодильник")
        assert len(result) == 1
        assert result[0]["key"] == "fridge_single_door"
        assert result[0]["qty"] == 1

    def test_russian_multiple_items(self):
        result = extract_items("холодильник, стол, шкаф")
        keys = {item["key"] for item in result}
        assert "fridge_single_door" in keys
        assert "dining_table" in keys
        assert "wardrobe_3_doors" in keys  # generic "шкаф" → wardrobe_large

    def test_english_items(self):
        result = extract_items("sofa, fridge, desk")
        keys = {item["key"] for item in result}
        assert "sofa_large_3_seat" in keys
        assert "fridge_single_door" in keys
        assert "desk" in keys

    def test_hebrew_items(self):
        result = extract_items("מקרר, ספה, כיסא")
        keys = {item["key"] for item in result}
        assert "fridge_single_door" in keys
        assert "sofa_large_3_seat" in keys
        assert "chair" in keys

    def test_quantity_before_item_russian(self):
        result = extract_items("5 коробок")
        assert len(result) == 1
        assert result[0]["key"] == "box_standard"
        assert result[0]["qty"] == 5

    def test_quantity_with_comma_separated(self):
        result = extract_items("диван, 10 коробок, 2 стула")
        items = {item["key"]: item["qty"] for item in result}
        assert items["sofa_large_3_seat"] == 1
        assert items["box_standard"] == 10
        assert items["chair"] == 2

    def test_english_quantity(self):
        result = extract_items("3 boxes and 2 chairs")
        items = {item["key"]: item["qty"] for item in result}
        assert items["box_standard"] == 3
        assert items["chair"] == 2

    def test_multi_word_alias(self):
        result = extract_items("стиральная машина")
        assert len(result) == 1
        assert result[0]["key"] == "washing_machine"

    def test_multi_word_english(self):
        result = extract_items("washing machine and dining table")
        keys = {item["key"] for item in result}
        assert "washing_machine" in keys
        assert "dining_table" in keys

    def test_no_matches_returns_empty(self):
        result = extract_items("ничего особенного, просто вещи")
        assert result == []

    def test_empty_string(self):
        assert extract_items("") == []

    def test_none_safe(self):
        """Should handle None-ish input gracefully."""
        assert extract_items("") == []

    def test_unknown_words_skipped(self):
        result = extract_items("something random and a fridge")
        assert len(result) == 1
        assert result[0]["key"] == "fridge_single_door"

    def test_russian_and_separator(self):
        """Russian 'и' separator works."""
        result = extract_items("диван и холодильник")
        keys = {item["key"] for item in result}
        assert "sofa_large_3_seat" in keys
        assert "fridge_single_door" in keys

    def test_dedup_sums_quantities(self):
        """Same item mentioned twice -> quantities summed."""
        result = extract_items("3 коробки, 2 коробки")
        assert len(result) == 1
        assert result[0]["key"] == "box_standard"
        assert result[0]["qty"] == 5

    def test_mixed_languages(self):
        """Items from different languages in one input."""
        result = extract_items("fridge, диван, כיסא")
        keys = {item["key"] for item in result}
        assert "fridge_single_door" in keys
        assert "sofa_large_3_seat" in keys
        assert "chair" in keys

    def test_custom_alias_lookup(self):
        """Can pass custom alias lookup for testing."""
        custom_lookup = {"my_item": "fridge_single_door"}
        result = extract_items("my_item", alias_lookup=custom_lookup)
        assert len(result) == 1
        assert result[0]["key"] == "fridge_single_door"


class TestUnitWordExtraction:
    """Phase 11: шт/штук/шт. unit word parsing in extract_items()."""

    def test_sht_before_item(self):
        """'5 шт коробок' → qty=5, box_standard."""
        result = extract_items("5 шт коробок")
        assert len(result) == 1
        assert result[0]["key"] == "box_standard"
        assert result[0]["qty"] == 5

    def test_shtuk_before_item(self):
        """'5 штук коробок' → qty=5, box_standard."""
        result = extract_items("5 штук коробок")
        assert len(result) == 1
        assert result[0]["key"] == "box_standard"
        assert result[0]["qty"] == 5

    def test_sht_dot_before_item(self):
        """'5шт. коробок' → qty=5, box_standard."""
        result = extract_items("5шт. коробок")
        assert len(result) == 1
        assert result[0]["key"] == "box_standard"
        assert result[0]["qty"] == 5

    def test_sht_with_bags(self):
        """'3 шт сумок' → qty=3, bag_suitcase."""
        result = extract_items("3 шт сумок")
        assert len(result) == 1
        assert result[0]["key"] == "bag_suitcase"
        assert result[0]["qty"] == 3

    def test_sht_mixed_items(self):
        """'10 шт коробок, диван' → box qty=10 + sofa qty=1."""
        result = extract_items("10 шт коробок, диван")
        items = {item["key"]: item["qty"] for item in result}
        assert items["box_standard"] == 10
        assert items["sofa_large_3_seat"] == 1


class TestNewItemCatalogEntries:
    """Extended item catalog — gas stove, large sofas, shelving, etc."""

    def test_gas_stove(self):
        """'газовая плита' → gas_stove."""
        result = extract_items("газовая плита")
        assert result[0]["key"] == "gas_stove"

    def test_gas_stove_short(self):
        """'плита' → gas_stove."""
        result = extract_items("плита")
        assert result[0]["key"] == "gas_stove"

    def test_sofa_4seat(self):
        """'четырехместный диван' → sofa_4seat."""
        result = extract_items("четырехместный диван")
        assert result[0]["key"] == "sofa_4seat"

    def test_sofa_4seat_bolshoy(self):
        """'большой диван' → sofa_4seat (moved from sofa_3seat)."""
        result = extract_items("большой диван")
        assert result[0]["key"] == "sofa_4seat"

    def test_sofa_5seat(self):
        """'пятиместный диван' → sofa_5seat."""
        result = extract_items("пятиместный диван")
        assert result[0]["key"] == "sofa_5seat"

    def test_sofa_3seat_still_works(self):
        """'диван' → sofa_3seat (regular sofa unchanged)."""
        result = extract_items("диван")
        assert result[0]["key"] == "sofa_large_3_seat"

    def test_shelving_unit(self):
        """'стеллаж' → shelving_unit."""
        result = extract_items("стеллаж")
        assert result[0]["key"] == "shelving_unit"

    def test_shelving_unit_misspelled(self):
        """'стелаж' (one л) → shelving_unit."""
        result = extract_items("стелаж")
        assert result[0]["key"] == "shelving_unit"

    def test_exercise_machine(self):
        """'тренажер' → exercise_machine."""
        result = extract_items("тренажер")
        assert result[0]["key"] == "home_gym"

    def test_exercise_machine_yo(self):
        """'тренажёр' (with ё) → exercise_machine."""
        result = extract_items("тренажёр")
        assert result[0]["key"] == "home_gym"

    def test_garden_furniture(self):
        """'садовая мебель' → garden_furniture."""
        result = extract_items("садовая мебель")
        assert result[0]["key"] == "garden_furniture"

    def test_fridge_small(self):
        """'маленький холодильник' → refrigerator_small."""
        result = extract_items("маленький холодильник")
        assert result[0]["key"] == "fridge_single_door"

    def test_fridge_large(self):
        """'большой холодильник' → refrigerator_large."""
        result = extract_items("большой холодильник")
        assert result[0]["key"] == "fridge_double_door"

    def test_fridge_double_door(self):
        """'двухдверный холодильник' → refrigerator_large."""
        result = extract_items("двухдверный холодильник")
        assert result[0]["key"] == "fridge_double_door"

    def test_fridge_plain_unchanged(self):
        """'холодильник' → refrigerator (mid-tier still default)."""
        result = extract_items("холодильник")
        assert result[0]["key"] == "fridge_single_door"

    def test_mixed_new_items(self):
        """Multiple new items in one string."""
        result = extract_items("газовая плита, тренажер, 2 стеллажа, садовая мебель")
        keys = {r["key"] for r in result}
        assert "gas_stove" in keys
        assert "home_gym" in keys
        assert "garden_furniture" in keys

    def test_new_items_labels(self):
        """Item labels loaded for all new items."""
        for key in ["gas_stove", "sofa_4seat", "sofa_5seat", "shelving_unit",
                     "home_gym", "garden_furniture",
                     "fridge_single_door", "fridge_double_door"]:
            assert key in ITEM_LABELS, f"{key} missing from ITEM_LABELS"
            assert "ru" in ITEM_LABELS[key], f"{key} missing 'ru' label"


class TestWardrobeSizing:
    """Phase 11: wardrobe split into small/large with door aliases."""

    def test_generic_shkaf_is_large(self):
        """Generic 'шкаф' → wardrobe_large (default big)."""
        result = extract_items("шкаф")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"

    def test_shifonier_is_large(self):
        """'шифонер' → wardrobe_large."""
        result = extract_items("шифонер")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"

    def test_shifonyer_is_large(self):
        """'шифоньер' → wardrobe_large."""
        result = extract_items("шифоньер")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"

    def test_shkaf_3_doors_is_large(self):
        """'шкаф 3 двери' → wardrobe_large, qty=1 (not 3)."""
        result = extract_items("шкаф 3 двери")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"
        assert result[0]["qty"] == 1

    def test_shkaf_4_doors_is_4_doors(self):
        """'шкаф 4 двери' → wardrobe_4_doors, qty=1."""
        result = extract_items("шкаф 4 двери")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_4_doors"
        assert result[0]["qty"] == 1

    def test_shifonier_3_doors_is_large(self):
        """'шифонер 3 двери' → wardrobe_large, qty=1 (not 3)."""
        result = extract_items("шифонер 3 двери")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"
        assert result[0]["qty"] == 1

    def test_shkaf_soldatik_is_small(self):
        """'шкаф-солдатик' → wardrobe_small."""
        result = extract_items("шкаф-солдатик")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_2_doors"

    def test_shkaf_1_door_is_small(self):
        """'шкаф 1 дверь' → wardrobe_small, qty=1."""
        result = extract_items("шкаф 1 дверь")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_2_doors"
        assert result[0]["qty"] == 1

    def test_shkaf_2_doors_is_small(self):
        """'шкаф 2 двери' → wardrobe_small, qty=1."""
        result = extract_items("шкаф 2 двери")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_2_doors"
        assert result[0]["qty"] == 1

    def test_wardrobe_small_price_range(self):
        """wardrobe_small should have correct price range."""
        result = estimate_price(items=["wardrobe_2_doors"])
        # wardrobe_small [150, 200], mid=175
        assert result["breakdown"]["items_mid"] == 175.0

    def test_wardrobe_large_price_range(self):
        """wardrobe_large should have correct price range."""
        result = estimate_price(items=["wardrobe_3_doors"])
        # wardrobe_large [250, 400], mid=325
        assert result["breakdown"]["items_mid"] == 325.0

    def test_shkaf_kupe_is_4_doors(self):
        """'шкаф-купе' → wardrobe_4_doors."""
        result = extract_items("шкаф-купе")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_4_doors"


class TestExtractItemsAttributeSafe:
    """EPIC D1: Attribute-like numbers must NOT be treated as quantity."""

    # --- Attribute suppression: doors, weight, volume, dimensions ---

    def test_5_door_wardrobe_qty_1(self):
        """'5 дверный шкаф' — 5 is doors, not qty."""
        result = extract_items("5 дверный шкаф")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"
        assert result[0]["qty"] == 1

    def test_5_hyphen_door_wardrobe_qty_1(self):
        """'5-дверный шкаф' — hyphenated attribute."""
        result = extract_items("5-дверный шкаф")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"
        assert result[0]["qty"] == 1

    def test_fridge_200kg_615l_qty_1(self):
        """'холодильник 200кг 615л' — weight+volume attributes, qty=1."""
        result = extract_items("холодильник 200кг 615л")
        assert len(result) == 1
        assert result[0]["key"] == "fridge_single_door"
        assert result[0]["qty"] == 1

    def test_fridge_200kg_qty_1(self):
        """'холодильник 200кг' — weight attribute only."""
        result = extract_items("холодильник 200кг")
        assert len(result) == 1
        assert result[0]["key"] == "fridge_single_door"
        assert result[0]["qty"] == 1

    def test_wardrobe_180cm_qty_1(self):
        """'шкаф 180см' — dimension attribute."""
        result = extract_items("шкаф 180см")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"
        assert result[0]["qty"] == 1

    def test_table_120cm_qty_1(self):
        """'стол 120cm' — English dimension suffix."""
        result = extract_items("стол 120cm")
        assert len(result) == 1
        assert result[0]["key"] == "dining_table"
        assert result[0]["qty"] == 1

    def test_wardrobe_2m_qty_1(self):
        """'шкаф 2м' — meter dimension."""
        result = extract_items("шкаф 2м")
        assert len(result) == 1
        assert result[0]["key"] == "wardrobe_3_doors"
        assert result[0]["qty"] == 1

    # --- Explicit markers: must still work ---

    def test_explicit_x5(self):
        """'шкаф x5' → qty=5."""
        result = extract_items("шкаф x5")
        assert len(result) == 1
        assert result[0]["qty"] == 5

    def test_explicit_5x(self):
        """'коробки 3x' → qty=3."""
        result = extract_items("коробки 3x")
        assert len(result) == 1
        assert result[0]["qty"] == 3

    def test_explicit_cyrillic_x(self):
        """'шкаф х5' — Cyrillic х should work like Latin x."""
        result = extract_items("шкаф х5")
        assert len(result) == 1
        assert result[0]["qty"] == 5

    def test_explicit_sht(self):
        """'шкаф 5шт' → qty=5."""
        result = extract_items("шкаф 5шт")
        assert len(result) == 1
        assert result[0]["qty"] == 5

    def test_explicit_shtuk(self):
        """'шкаф 5 штук' → qty=5."""
        result = extract_items("шкаф 5 штук")
        assert len(result) == 1
        assert result[0]["qty"] == 5

    def test_explicit_pcs(self):
        """'boxes 5 pcs' → qty=5."""
        result = extract_items("boxes 5 pcs")
        assert len(result) == 1
        assert result[0]["qty"] == 5

    def test_explicit_qty_colon(self):
        """'box qty:3' → qty=3."""
        result = extract_items("box qty:3")
        assert len(result) == 1
        assert result[0]["qty"] == 3

    def test_explicit_qty_equals(self):
        """'box qty=4' → qty=4."""
        result = extract_items("box qty=4")
        assert len(result) == 1
        assert result[0]["qty"] == 4

    # --- Bare numbers: small values still work, large values capped ---

    def test_bare_small_number(self):
        """'5 коробок' — bare number ≤20 → qty=5."""
        result = extract_items("5 коробок")
        assert len(result) == 1
        assert result[0]["qty"] == 5

    def test_bare_number_sanity_cap(self):
        """'300 коробок' — bare number >200 → qty=1 (sanity cap)."""
        result = extract_items("300 коробок")
        assert len(result) == 1
        assert result[0]["qty"] == 1

    def test_bare_20_is_accepted(self):
        """'20 коробок' — boundary: 20 is within cap."""
        result = extract_items("20 коробок")
        assert len(result) == 1
        assert result[0]["qty"] == 20

    def test_bare_21_accepted(self):
        """'21 коробок' — now within raised cap (200)."""
        result = extract_items("21 коробок")
        assert len(result) == 1
        assert result[0]["qty"] == 21

    def test_bare_80_boxes(self):
        """'80 коробок' — real scenario: 80 boxes."""
        result = extract_items("80 коробок")
        assert len(result) == 1
        assert result[0]["key"] == "box_standard"
        assert result[0]["qty"] == 80

    def test_80_sht_boxes(self):
        """'80 шт коробок' — explicit marker, no cap."""
        result = extract_items("80 шт коробок")
        assert len(result) == 1
        assert result[0]["key"] == "box_standard"
        assert result[0]["qty"] == 80

    def test_bare_200_boundary(self):
        """'200 коробок' — boundary: 200 is within cap."""
        result = extract_items("200 коробок")
        assert len(result) == 1
        assert result[0]["qty"] == 200

    def test_bare_201_capped(self):
        """'201 коробок' — boundary: 201 exceeds cap → qty=1."""
        result = extract_items("201 коробок")
        assert len(result) == 1
        assert result[0]["qty"] == 1

    # --- Combined scenario from EPIC D spec ---

    def test_fridge_and_5door_wardrobe(self):
        """'Холодильник, 5 дверный шкаф' — fridge qty=1, wardrobe qty=1."""
        result = extract_items("Холодильник, 5 дверный шкаф")
        keys = {r["key"]: r["qty"] for r in result}
        assert keys["fridge_single_door"] == 1
        # Generic "шкаф" with "5 дверный" attribute → wardrobe_3_doors (default)
        assert keys["wardrobe_3_doors"] == 1

    def test_fridge_and_wardrobe_x2(self):
        """'Холодильник, шкаф x2' — fridge qty=1, wardrobe qty=2."""
        result = extract_items("Холодильник, шкаф x2")
        keys = {r["key"]: r["qty"] for r in result}
        assert keys["fridge_single_door"] == 1
        # Generic "шкаф" → wardrobe_3_doors (default)
        assert keys["wardrobe_3_doors"] == 2


class TestEstimatePriceWithQty:
    """Tests for estimate_price() with dict-based items (qty support)."""

    def test_single_item_qty_1(self):
        result = estimate_price(items=[{"key": "fridge_single_door", "qty": 1}])
        # base=150 + items_mid=(200+280)/2=240 -> mid=390
        # 390*0.85=331.5→331, 390*1.15=448.5→449
        assert result["estimate_min"] == 331
        assert result["estimate_max"] == 449
        assert result["breakdown"]["items_mid"] == 240.0

    def test_item_qty_multiplied(self):
        result = estimate_price(items=[{"key": "box_standard", "qty": 10}])
        # items_mid = (15+20)/2 * 10 = 175
        # mid = 150 + 175 = 325
        assert result["breakdown"]["items_mid"] == 175.0

    def test_multiple_items_with_qty(self):
        result = estimate_price(items=[
            {"key": "fridge_single_door", "qty": 1},
            {"key": "box_standard", "qty": 5},
        ])
        # items_mid = 240 + 87.5 = 327.5
        assert result["breakdown"]["items_mid"] == 327.5

    def test_backward_compat_list_str(self):
        """Old list[str] format still works."""
        result = estimate_price(items=["fridge_single_door", "desk"])
        # items_mid = 240 + 125 = 365
        assert result["breakdown"]["items_mid"] == 365.0

    def test_unknown_key_in_dict_ignored(self):
        result = estimate_price(items=[{"key": "nonexistent", "qty": 5}])
        assert result["breakdown"]["items_mid"] == 0.0

    def test_items_with_volume_and_floors(self):
        """Items combine correctly with volume surcharge and floors."""
        result = estimate_price(
            items=[{"key": "sofa_large_3_seat", "qty": 1}],
            volume_category="large",
            pickup_floors=[(3, False)],
            floor_to=1,
            has_elevator_to=True,
        )
        # floor: (3-1)*50=100, volume: 350, items_mid: (200+250)/2=225
        # fixed=150+100+350=600, mid=600+225=825
        # 825*0.85=701.25→701, 825*1.15=948.75→949
        assert result["estimate_min"] == 701
        assert result["estimate_max"] == 949


# ============================================================================
# G6: Complexity scoring guard tests
# ============================================================================


class TestComplexityGuards:
    """G6: Complexity scoring guard — multiplier + hard floor for premium moves."""

    def test_config_loaded(self):
        """Complexity config section is loaded from JSON."""
        assert "complex_multiplier" in COMPLEXITY_GUARDS
        assert "complex_min_floor" in COMPLEXITY_GUARDS
        assert "score_threshold" in COMPLEXITY_GUARDS
        assert COMPLEXITY_GUARDS["complex_multiplier"] == 1.18
        assert COMPLEXITY_GUARDS["complex_min_floor"] == 7500

    # -- Exemptions: small / None / medium never trigger complexity ----------

    def test_no_complexity_small_volume(self):
        """Small volume is exempt even with many other triggers."""
        result = estimate_price(
            volume_category="small",
            extras=["assembly"],
            route_band="inter_region_short",
            extra_pickups=1,
            pickup_floors=[(5, False)],
            floor_to=5, has_elevator_to=False,
        )
        assert result["breakdown"]["complexity_applied"] is False
        assert result["breakdown"]["complexity_score"] == 0

    def test_no_complexity_no_volume(self):
        """No volume category → complexity never triggers."""
        result = estimate_price(
            volume_category=None,
            extras=["assembly"],
            route_band="inter_region_short",
        )
        assert result["breakdown"]["complexity_applied"] is False
        assert result["breakdown"]["complexity_score"] == 0

    def test_no_complexity_medium_volume(self):
        """Medium volume is not in eligible list → no complexity."""
        result = estimate_price(
            volume_category="medium",
            extras=["assembly"],
            route_band="inter_region_short",
        )
        assert result["breakdown"]["complexity_applied"] is False
        assert result["breakdown"]["complexity_score"] == 0

    # -- Score below threshold -----------------------------------------------

    def test_score_below_threshold(self):
        """XL volume alone → score=1, below threshold 2 → no multiplier."""
        result = estimate_price(volume_category="xl")
        assert result["breakdown"]["complexity_score"] == 1
        assert result["breakdown"]["complexity_applied"] is False
        # base=150+xl=500=650, *0.85=552, *1.15=748, xl_floor=700
        assert result["estimate_min"] == 700
        assert result["estimate_max"] == 748

    def test_large_volume_only_score_1(self):
        """Large volume alone → score=1 < threshold, no complexity."""
        result = estimate_price(volume_category="large")
        assert result["breakdown"]["complexity_score"] == 1
        assert result["breakdown"]["complexity_applied"] is False
        # base=150+large=350=500, *0.85=425, *1.15=575
        assert result["estimate_min"] == 425
        assert result["estimate_max"] == 575

    # -- Score at threshold (2): multiplier YES, floor NO --------------------

    def test_score_2_xl_route(self):
        """XL + inter_region → score=2 → multiplier applied, floor NOT."""
        result = estimate_price(
            volume_category="xl",
            route_band="inter_region_short",
        )
        # base=150 + xl=500 + route=500 = 1150
        # G6: score=2 (volume_xl, route_inter_region_short), multiplier
        # mid = 1150 * 1.18 * 1.08 = 1465.56
        # 1465.56*0.85=1245.726→1245, 1465.56*1.15=1685.394→1686
        # score=2 < min_floor_threshold=3 → no 7500 floor
        assert result["breakdown"]["complexity_applied"] is True
        assert result["breakdown"]["complexity_score"] == 2
        assert "volume_xl" in result["breakdown"]["complexity_triggers"]
        assert "route_inter_region_short" in result["breakdown"]["complexity_triggers"]
        assert result["estimate_min"] == 1245
        assert result["estimate_max"] == 1686
        assert "complexity_guard" in result["breakdown"]["guards_applied"]
        assert "complex_min_floor" not in result["breakdown"]["guards_applied"]

    def test_score_2_large_assembly(self):
        """Large + assembly → score=2 → multiplier applied."""
        result = estimate_price(
            volume_category="large",
            extras=["assembly"],
        )
        # base=150 + large=350 + assembly→disassembly=80 = 580
        # G6: score=2 (volume_large, assembly)
        # mid = 580 * 1.18 * 1.08 = 739.224
        # 739.224*0.85=628.34→628, 739.224*1.15=850.11→851
        assert result["breakdown"]["complexity_applied"] is True
        assert result["breakdown"]["complexity_score"] == 2
        assert result["estimate_min"] == 628
        assert result["estimate_max"] == 851

    # -- Score at 3: multiplier + hard floor ---------------------------------

    def test_score_3_triggers_min_floor(self):
        """XL + assembly + route → score=3 → min_floor=7500 applied."""
        result = estimate_price(
            volume_category="xl",
            extras=["assembly"],
            route_band="inter_region_short",
        )
        # base=150 + xl=500 + assembly→disassembly=80 + route=500 = 1230
        # G6: score=3 (volume_xl, assembly, route_inter_region_short)
        # mid = 1230 * 1.18 * 1.08 = 1567.08
        # But score=3 >= min_floor_threshold=3 → complex_min_floor=7500 applies
        assert result["breakdown"]["complexity_applied"] is True
        assert result["breakdown"]["complexity_score"] == 3
        assert result["estimate_min"] == 7500
        assert result["estimate_max"] == 7500
        assert "complex_min_floor" in result["breakdown"]["guards_applied"]
        assert "complexity_guard" in result["breakdown"]["guards_applied"]

    def test_score_4_triggers(self):
        """XL + assembly + route + multi-pickup → score=4."""
        result = estimate_price(
            volume_category="xl",
            extras=["assembly"],
            route_band="inter_region_short",
            extra_pickups=1,
        )
        # base=150 + xl=500 + assembly=80 + route=500 + pickup=70 = 1300
        # G6: score=4 (volume_xl, assembly, multi_pickup, route)
        # min_floor_score=3 met → complex_min_floor=7500
        assert result["breakdown"]["complexity_score"] == 4
        assert result["breakdown"]["complexity_applied"] is True
        assert result["estimate_min"] == 7500
        assert "complex_min_floor" in result["breakdown"]["guards_applied"]

    def test_score_5_all_triggers(self):
        """All 5 triggers → score=5, items push estimate above floor."""
        result = estimate_price(
            volume_category="xl",
            extras=["assembly"],
            route_band="inter_region_long",
            extra_pickups=1,
            pickup_floors=[(6, False)],
            floor_to=2, has_elevator_to=True,
            items=[
                {"key": "wardrobe_3_doors", "qty": 4},
                {"key": "sofa_large_3_seat", "qty": 2},
                {"key": "fridge_single_door", "qty": 1},
                {"key": "bed_double", "qty": 1},
                {"key": "washing_machine", "qty": 1},
                {"key": "box_standard", "qty": 10},
                {"key": "bag_suitcase", "qty": 35},
            ],
        )
        assert result["breakdown"]["complexity_score"] == 5
        assert result["breakdown"]["complexity_applied"] is True
        assert len(result["breakdown"]["complexity_triggers"]) == 5
        # With so many items + multiplier, estimate_min should be >= 7500
        assert result["estimate_min"] >= 7500
        assert result["estimate_max"] >= result["estimate_min"]
        assert "complexity_guard" in result["breakdown"]["guards_applied"]

    # -- Risk buffer only on complex -----------------------------------------

    def test_risk_buffer_only_complex(self):
        """Simple move (score<2) gets NO risk buffer."""
        # score=0 (no volume)
        result_simple = estimate_price()
        # base=150, mid=150, no buffer
        # 150*0.85=127.5→127, 150*1.15=172.5→173
        assert result_simple["estimate_min"] == 127
        assert result_simple["estimate_max"] == 173
        assert result_simple["breakdown"]["complexity_applied"] is False

    # -- Breakdown fields ----------------------------------------------------

    def test_breakdown_includes_complexity_fields(self):
        """Breakdown always includes complexity fields, even when not applied."""
        result = estimate_price()
        bd = result["breakdown"]
        assert "complexity_score" in bd
        assert "complexity_triggers" in bd
        assert "complexity_applied" in bd
        assert bd["complexity_score"] == 0
        assert bd["complexity_triggers"] == []
        assert bd["complexity_applied"] is False

    # -- Items combine with complexity multiplier ----------------------------

    def test_complexity_with_items(self):
        """XL + assembly + items → items_mid is multiplied by complexity."""
        result = estimate_price(
            volume_category="xl",
            extras=["assembly"],
            items=[{"key": "wardrobe_3_doors", "qty": 2}],
        )
        # base=150 + xl=500 + assembly=80 = 730
        # items_mid = (250+400)/2 * 2 = 650
        # fixed=730, mid=730+650=1380
        # G6: score=2 (volume_xl, assembly)
        # mid = 1380 * 1.18 * 1.08 = 1758.672
        # floor(1758.672*0.85)=floor(1494.8712)=1494
        # ceil(1758.672*1.15)=ceil(2022.4728)=2023
        assert result["breakdown"]["complexity_applied"] is True
        assert result["breakdown"]["complexity_score"] == 2
        assert result["breakdown"]["items_mid"] == 650.0
        assert result["estimate_min"] == 1494
        assert result["estimate_max"] == 2023

    # -- Route band edge cases -----------------------------------------------

    def test_same_city_xl_no_route_trigger(self):
        """XL + same_city route → route NOT in trigger list → score=1."""
        result = estimate_price(
            volume_category="xl",
            route_band="same_city",
        )
        assert result["breakdown"]["complexity_score"] == 1
        assert result["breakdown"]["complexity_applied"] is False

    # -- Floor trigger edge cases --------------------------------------------

    def test_floor_4_no_trigger(self):
        """Floor 4 without elevator → below floor threshold 5 → no trigger."""
        result = estimate_price(
            volume_category="xl",
            pickup_floors=[(4, False)],
            floor_to=1, has_elevator_to=True,
        )
        # score=1 (volume_xl only), floor 4 < 5
        assert result["breakdown"]["complexity_score"] == 1
        assert "high_floor_no_elevator" not in result["breakdown"]["complexity_triggers"]

    def test_floor_5_triggers(self):
        """Floor 5 without elevator → triggers high_floor complexity."""
        result = estimate_price(
            volume_category="xl",
            pickup_floors=[(5, False)],
            floor_to=1, has_elevator_to=True,
        )
        # score=2 (volume_xl + high_floor_no_elevator)
        assert result["breakdown"]["complexity_score"] == 2
        assert "high_floor_no_elevator" in result["breakdown"]["complexity_triggers"]
        assert result["breakdown"]["complexity_applied"] is True


class TestDetectVolumeFromItems:
    """G6 fix: infer volume_category from extracted cargo items."""

    def test_config_loaded(self):
        """volume_from_items config section is loaded from JSON."""
        assert "heavy_keys" in VOLUME_FROM_ITEMS_CONFIG
        assert "xl_items_mid" in VOLUME_FROM_ITEMS_CONFIG
        assert "large_heavy_count" in VOLUME_FROM_ITEMS_CONFIG

    def test_xl_by_items_mid(self):
        """items_mid >= 1400 → 'xl'."""
        # 4 sofa_large_3_seat (mid=225 each) + 4 wardrobe_3_doors (mid=325 each)
        # items_mid = 4*225 + 4*325 = 900 + 1300 = 2200 >= 1400
        items = [
            {"key": "sofa_large_3_seat", "qty": 4},
            {"key": "wardrobe_3_doors", "qty": 4},
        ]
        assert detect_volume_from_items(items) == "xl"

    def test_xl_by_heavy_count(self):
        """4 heavy items → 'xl'."""
        items = [
            {"key": "sofa_large_3_seat", "qty": 1},
            {"key": "fridge_single_door", "qty": 1},
            {"key": "washing_machine", "qty": 1},
            {"key": "bed_double", "qty": 1},
        ]
        assert detect_volume_from_items(items) == "xl"

    def test_large_by_items_mid(self):
        """items_mid >= 600 → 'large'."""
        # sofa_large_3_seat mid=225, wardrobe_3_doors mid=325, fridge_single_door mid=240,
        # box x5 mid=87.5 → total = 877.5 >= 600
        items = [
            {"key": "sofa_large_3_seat", "qty": 1},
            {"key": "wardrobe_3_doors", "qty": 1},
            {"key": "fridge_single_door", "qty": 1},
            {"key": "box_standard", "qty": 5},
        ]
        # Also has 3 heavy items → xl by heavy count (3 >= 2? yes, but
        # need to check: heavy_count=3 >= xl_heavy_count=4? No → large)
        assert detect_volume_from_items(items) == "large"

    def test_large_by_heavy_count(self):
        """2 heavy items → 'large'."""
        items = [
            {"key": "sofa_large_3_seat", "qty": 1},
            {"key": "fridge_single_door", "qty": 1},
        ]
        assert detect_volume_from_items(items) == "large"

    def test_medium_by_items_mid(self):
        """items_mid >= 300 → 'medium'."""
        # 20 boxes: mid = 20 * 17.5 = 350 >= 300
        items = [{"key": "box_standard", "qty": 20}]
        assert detect_volume_from_items(items) == "medium"

    def test_none_below_threshold(self):
        """Small item total → None."""
        items = [{"key": "box_standard", "qty": 2}]
        assert detect_volume_from_items(items) is None

    def test_empty_items(self):
        """Empty or None → None."""
        assert detect_volume_from_items([]) is None
        assert detect_volume_from_items(None) is None

    def test_item_labels_loaded(self):
        """item_labels config section is loaded for crew localization."""
        assert "sofa_large_3_seat" in ITEM_LABELS
        assert ITEM_LABELS["sofa_large_3_seat"]["ru"] == "Диван"
        assert ITEM_LABELS["box_standard"]["en"] == "Box"


class TestCargoItemExtraction:
    """Test that item extraction flows from handler into estimate."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_cargo_stores_items_and_raw(self):
        """CARGO step stores both cargo_raw and cargo_items in custom."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, "Диван и 5 коробок")
        assert state.data.custom["cargo_raw"] == "Диван и 5 коробок"
        items = state.data.custom["cargo_items"]
        assert len(items) >= 1
        keys = {item["key"] for item in items}
        assert "sofa_large_3_seat" in keys

    def test_items_flow_into_estimate(self):
        """Extracted items affect the pricing estimate."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        # Cargo with recognizable items
        state, _, _ = self.handler.handle_text(state, "Холодильник и 10 коробок")
        assert len(state.data.custom["cargo_items"]) >= 1
        # Fast-forward to estimate
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # items_mid should be non-zero
        assert state.data.custom["estimate_breakdown"]["items_mid"] > 0

    def test_no_items_estimate_suppressed(self):
        """Cargo with no recognizable items and long text -> estimate suppressed."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, _, _ = self.handler.handle_text(state, "Разные мелкие вещи для переезда")
        assert state.data.custom["cargo_items"] == []
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # Long raw, no items, no volume → estimate suppressed
        assert state.data.custom.get("estimate_suppressed") is True
        assert "estimate_min" not in state.data.custom
        assert "estimate_max" not in state.data.custom

    def test_no_items_short_raw_estimate_normal(self):
        """Cargo with no recognizable items but short text -> estimate shown."""
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["cargo_raw"] = "мелочь"  # short: 6 chars
        state.data.custom["cargo_items"] = []
        state.data.custom["volume_category"] = "small"
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.data.custom.get("estimate_suppressed") is not True
        assert "estimate_min" in state.data.custom


# ============================================================================
# Phase 12: Operator phone in welcome message
# ============================================================================

_OP_CFG_PATCH = "app.core.handlers.moving_bot_handler.get_operator_config"


def _op_cfg_with_phone(phone):
    return {
        "enabled": True,
        "channel": "whatsapp",
        "operator_whatsapp": phone,
        "operator_whatsapp_provider": "twilio",
        "twilio_content_sid": None,
    }


class TestWelcomeOperatorPhone:
    """Phase 12: Operator phone number in welcome message."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    @patch(_OP_CFG_PATCH)
    def test_welcome_includes_phone_when_configured(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone("+972501234567")
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, "привет")
        assert "+972501234567" in reply
        assert "оператором" in reply

    @patch(_OP_CFG_PATCH)
    def test_welcome_no_phone_when_none(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone(None)
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, "привет")
        assert "оператором" not in reply
        assert "Привет" in reply
        assert "перевезти" in reply

    @patch(_OP_CFG_PATCH)
    def test_welcome_no_phone_when_empty_string(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone("")
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, "привет")
        assert "оператором" not in reply

    @patch(_OP_CFG_PATCH)
    def test_reset_includes_phone(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone("+972509876543")
        state = self.handler.new_session("t1", "chat1")
        state.step = "addr_from"
        state, reply, done = self.handler.handle_text(state, "заново")
        assert "+972509876543" in reply
        assert state.step == "cargo"

    @patch(_OP_CFG_PATCH)
    def test_estimate_restart_includes_phone(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone("+972501111111")
        state = self.handler.new_session("t1", "chat1")
        state.step = "estimate"
        state, reply, done = self.handler.handle_text(state, "2")
        assert "+972501111111" in reply
        assert state.step == "cargo"

    @patch(_OP_CFG_PATCH)
    def test_welcome_phone_english(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone("+972501234567")
        state = self.handler.new_session("t1", "chat1", language="en")
        state, reply, done = self.handler.handle_text(state, "hi")
        assert "+972501234567" in reply
        assert "Contact operator" in reply


# ============================================================================
# Phase 12: detect_volume_from_rooms — unit tests
# ============================================================================

class TestDetectVolumeFromRooms:
    """Phase 12: Room-based volume auto-detection."""

    # --- Russian ---
    def test_3_bedrooms_and_salon_ru(self):
        text = "3 спальные комнаты, салон и 30 коробок с вещами"
        assert detect_volume_from_rooms(text) == "xl"  # 3+1=4

    def test_2_bedrooms_ru(self):
        assert detect_volume_from_rooms("2 спальни и кухня") == "medium"

    def test_1_bedroom_ru(self):
        assert detect_volume_from_rooms("1 спальня") == "small"

    def test_studio_ru(self):
        assert detect_volume_from_rooms("Студия, мебель и коробки") == "small"

    def test_3_room_apartment_ru(self):
        assert detect_volume_from_rooms("3-комнатная квартира") == "large"

    def test_4_room_apartment_ru(self):
        assert detect_volume_from_rooms("4 комнатная квартира") == "xl"

    def test_salon_only_ru(self):
        assert detect_volume_from_rooms("Салон и кухня") == "small"

    def test_gostinaya_ru(self):
        assert detect_volume_from_rooms("гостиная и 2 спальни") == "large"  # 1+2=3

    # --- English ---
    def test_3_bedrooms_en(self):
        assert detect_volume_from_rooms("3 bedrooms and living room") == "xl"

    def test_2_rooms_en(self):
        assert detect_volume_from_rooms("2 rooms") == "medium"

    def test_studio_en(self):
        assert detect_volume_from_rooms("Studio apartment, some boxes") == "small"

    # --- Hebrew ---
    def test_salon_he(self):
        assert detect_volume_from_rooms("סלון ומטבח") == "small"

    def test_studio_he(self):
        assert detect_volume_from_rooms("סטודיו עם ריהוט") == "small"

    # --- Edge cases ---
    def test_no_rooms_returns_none(self):
        assert detect_volume_from_rooms("Диван, холодильник, 5 коробок") is None

    def test_empty_string(self):
        assert detect_volume_from_rooms("") is None

    def test_none_input(self):
        assert detect_volume_from_rooms(None) is None

    def test_kitchen_only_does_not_count(self):
        assert detect_volume_from_rooms("Кухня и ванная") is None

    # --- User's full example ---
    def test_users_full_example(self):
        text = ("Добрый день! Хотела узнать стоимость ваших услуг. "
                "Мы готовимся к переезду через месяц. "
                "Мы живёт в Хайфе и хотим переехать не дальше чем 20 километров "
                "от нашего на данный момент дома. "
                "У нас 3 спальные комнаты, салон и я думаю что будут "
                "около 30 коробок с вещами. 3 этаж без лифта")
        assert detect_volume_from_rooms(text) == "xl"


# ============================================================================
# Phase 12: Cargo step room volume detection — integration tests
# ============================================================================

class TestCargoRoomVolumeDetection:
    """Phase 12: Room volume detection in cargo step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    @patch(_OP_CFG_PATCH)
    def test_cargo_with_rooms_sets_volume_category(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone(None)
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(
            state, "3 спальные комнаты, салон и 30 коробок"
        )
        assert state.step == "pickup_count"
        assert state.data.custom["volume_category"] == "xl"
        assert state.data.custom["volume_from_rooms"] is True

    @patch(_OP_CFG_PATCH)
    def test_cargo_with_items_skips_volume(self, mock_op_cfg):
        """CARGO with heavy items → PICKUP_COUNT + volume inferred from items."""
        mock_op_cfg.return_value = _op_cfg_with_phone(None)
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(
            state, "Диван, холодильник, 5 коробок"
        )
        assert state.step == "pickup_count"
        # Volume is now inferred from items (sofa + fridge = 2 heavy → "large")
        assert state.data.custom["volume_category"] == "large"
        assert state.data.custom["volume_from_items"] is True
        assert "volume_from_rooms" not in state.data.custom
        # Items ARE extracted
        assert len(state.data.custom.get("cargo_items", [])) > 0

    @patch(_OP_CFG_PATCH)
    def test_cargo_items_also_extracted_with_rooms(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone(None)
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, _, _ = self.handler.handle_text(
            state, "2 спальни и 10 коробок"
        )
        assert state.data.custom["volume_category"] == "medium"
        items = state.data.custom["cargo_items"]
        keys = {i["key"] for i in items}
        assert "box_standard" in keys

    @patch(_OP_CFG_PATCH)
    def test_room_volume_affects_estimate(self, mock_op_cfg):
        mock_op_cfg.return_value = _op_cfg_with_phone(None)
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, _, _ = self.handler.handle_text(
            state, "3 спальные комнаты и салон"
        )
        assert state.data.custom["volume_category"] == "xl"
        # Fast-forward to estimate
        state.step = "extras"
        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert state.data.custom["estimate_breakdown"]["volume_surcharge"] == 500


# ============================================================================
# Phase 12: Photo menu rooms push — stronger photo encouragement
# ============================================================================

class TestPhotoMenuRoomsPush:
    """Phase 12: Stronger photo encouragement for room-based moves."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_photo_menu_rooms_variant_shown(self):
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["volume_from_rooms"] = True
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"
        assert "📸" in reply
        assert "квартир" in reply.lower()

    def test_photo_menu_normal_without_rooms(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"
        assert "Фото груза есть?" in reply

    def test_photo_menu_rooms_english(self):
        state = self.handler.new_session("t1", "chat1", language="en")
        state.data.custom["volume_from_rooms"] = True
        state.step = "time_slot"
        state, reply, done = self.handler.handle_text(state, "1")
        assert "apartment" in reply.lower()
        assert "📸" in reply

    def test_photo_menu_rooms_still_accepts_choices(self):
        """The rooms photo menu uses same 1/2 choices."""
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["volume_from_rooms"] = True
        state.step = "photo_menu"
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_wait"
        assert state.data.has_photos is True


# ===================================================================
# Phase 13: Input sanitisation
# ===================================================================


class TestSanitizeText:
    """Tests for sanitize_text() — input sanitisation."""

    def test_normal_text_unchanged(self):
        assert sanitize_text("Хайфа, ул. Герцль 10") == "Хайфа, ул. Герцль 10"

    def test_russian_hebrew_preserved(self):
        assert "переезд" in sanitize_text("Нужен переезд из Хайфы")
        assert "דירה" in sanitize_text("העברת דירה")

    def test_strips_html_tags(self):
        result = sanitize_text("hello <script>alert(1)</script> world")
        assert "<script>" not in result
        assert "hello" in result
        assert "world" in result

    def test_strips_bold_tags(self):
        result = sanitize_text("Диван <b>большой</b> и стол")
        assert "<b>" not in result
        assert "Диван" in result
        assert "стол" in result

    def test_strips_http_urls(self):
        result = sanitize_text("visit http://evil.com now")
        assert "http" not in result
        assert "visit" in result

    def test_strips_https_urls(self):
        result = sanitize_text("go https://evil.com/payload please")
        assert "https" not in result

    def test_strips_www_urls(self):
        result = sanitize_text("go to www.evil.com please")
        assert "www" not in result

    def test_strips_javascript_uri(self):
        result = sanitize_text("text javascript:alert(1) more")
        assert "javascript:" not in result

    def test_strips_data_uri(self):
        result = sanitize_text("text data:text/html,<h1>hi</h1> more")
        assert "data:" not in result

    def test_strips_control_chars(self):
        result = sanitize_text("hello\x00\x01\x02world")
        assert result == "helloworld"

    def test_preserves_newlines(self):
        result = sanitize_text("line1\nline2\nline3")
        assert "\n" in result
        assert "line1" in result

    def test_enforces_max_length(self):
        long_text = "а" * 1000
        result = sanitize_text(long_text, max_length=200)
        assert len(result) <= 200

    def test_rejects_pure_url(self):
        with pytest.raises(ValueError, match="rejected"):
            sanitize_text("http://evil.com/payload")

    def test_rejects_pure_html(self):
        # Pure tags with no text content between them → rejected
        with pytest.raises(ValueError, match="rejected"):
            sanitize_text("<div><span></span></div>")

    def test_pure_html_with_inner_text_keeps_text(self):
        # Tags stripped but inner text survives
        result = sanitize_text("<script>alert('xss')</script>")
        assert result == "alert('xss')"

    def test_rejects_pure_script_uri(self):
        # Only the scheme prefix is stripped; need pure scheme to reject
        with pytest.raises(ValueError, match="rejected"):
            sanitize_text("javascript:  ")

    def test_mixed_content_keeps_text(self):
        result = sanitize_text("Диван <b>большой</b> и http://spam.com холодильник")
        assert "Диван" in result
        assert "холодильник" in result
        assert "<b>" not in result
        assert "http" not in result

    def test_empty_string(self):
        assert sanitize_text("") == ""

    def test_whitespace_only(self):
        assert sanitize_text("   ") == ""

    def test_collapses_multiple_spaces(self):
        result = sanitize_text("a   b     c")
        assert result == "a b c"


# ===================================================================
# Phase 13: Landing page pre-fill parsing
# ===================================================================

_FULL_LANDING_MSG = (
    "Здравствуйте! Хочу узнать стоимость переезда.\n"
    "Тип: Квартира\n"
    "Откуда: Хайфа, Нешер\n"
    "Куда: Тель-Авив\n"
    "Дата: 15 марта\n"
    "Детали: 2 комнаты, 3 этаж без лифта, холодильник, диван"
)


class TestParseLandingPrefill:
    """Tests for parse_landing_prefill() — landing message detection."""

    def test_full_message_parsed(self):
        result = parse_landing_prefill(_FULL_LANDING_MSG)
        assert result is not None
        assert result.move_type == "Квартира"
        assert result.addr_from == "Хайфа, Нешер"
        assert result.addr_to == "Тель-Авив"
        assert result.date_text == "15 марта"
        assert "2 комнаты" in result.details
        assert "холодильник" in result.details

    def test_partial_message_missing_fields(self):
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Офис\n"
            "Откуда: Нетания"
        )
        result = parse_landing_prefill(msg)
        assert result is not None
        assert result.move_type == "Офис"
        assert result.addr_from == "Нетания"
        assert result.addr_to is None
        assert result.details is None
        assert result.date_text is None

    def test_non_landing_message_returns_none(self):
        assert parse_landing_prefill("Привет, хочу переехать") is None

    def test_empty_string_returns_none(self):
        assert parse_landing_prefill("") is None

    def test_signature_only_no_fields(self):
        result = parse_landing_prefill("Здравствуйте! Хочу узнать стоимость переезда.")
        assert result is not None
        assert result.move_type is None
        assert result.addr_from is None
        assert result.details is None

    def test_malicious_html_in_fields_sanitised(self):
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Откуда: <script>alert('xss')</script>Хайфа\n"
            "Детали: диван <b>тяжёлый</b> и стол"
        )
        result = parse_landing_prefill(msg)
        assert result is not None
        assert "<script>" not in (result.addr_from or "")
        assert "Хайфа" in (result.addr_from or "")
        assert "<b>" not in (result.details or "")
        assert "диван" in (result.details or "")

    def test_url_in_field_stripped(self):
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Откуда: Хайфа http://evil.com\n"
            "Куда: Тель-Авив"
        )
        result = parse_landing_prefill(msg)
        assert result is not None
        assert "http" not in (result.addr_from or "")
        assert "Хайфа" in (result.addr_from or "")

    def test_pure_url_field_discarded(self):
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Куда: http://evil.com/steal-data"
        )
        result = parse_landing_prefill(msg)
        assert result is not None
        assert result.addr_to is None

    def test_unknown_move_type_discarded(self):
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Пиратский корабль"
        )
        result = parse_landing_prefill(msg)
        assert result is not None
        assert result.move_type is None

    def test_field_length_limits(self):
        long_addr = "А" * 500
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            f"Откуда: {long_addr}"
        )
        result = parse_landing_prefill(msg)
        assert result is not None
        assert len(result.addr_from) <= 200

    def test_case_insensitive_signature(self):
        msg = "здравствуйте! хочу узнать стоимость переезда.\nТип: Квартира"
        result = parse_landing_prefill(msg)
        assert result is not None
        assert result.move_type == "Квартира"

    def test_truck_only_move_type(self):
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Только машина + водитель"
        )
        result = parse_landing_prefill(msg)
        assert result is not None
        assert result.move_type == "Только машина + водитель"


# ===================================================================
# Phase 13: Handler landing pre-fill integration
# ===================================================================


class TestHandlerLandingPrefill:
    """Tests for landing pre-fill integration in MovingBotHandler."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_with_addresses_goes_to_confirm(self, _mock):
        """Landing with both addresses → confirm_addresses step."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.step == "confirm_addresses"
        assert state.data.cargo_description is not None
        assert "2 комнаты" in state.data.cargo_description
        assert state.data.custom.get("source") == "landing_prefill"
        assert "Хайфа" in reply
        assert "Тель-Авив" in reply
        assert not done

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_stores_addresses_and_date(self, _mock):
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.data.addr_from == "Хайфа, Нешер"
        assert state.data.addr_to == "Тель-Авив"
        assert state.data.custom.get("landing_date_hint") == "15 марта"
        assert state.data.custom.get("landing_move_type") == "Квартира"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_without_details_asks_volume(self, _mock):
        """Landing with move_type but no details → cargo from move_type, then volume."""
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Квартира\n"
            "Откуда: Хайфа"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        # move_type used as cargo fallback → volume enforcement (Phase 15)
        assert state.step == "volume"
        assert state.data.cargo_description == "Квартира"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_signature_only_asks_cargo(self, _mock):
        """Signature with no fields and no type → cargo step."""
        msg = "Здравствуйте! Хочу узнать стоимость переезда."
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        assert state.step == "cargo"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_normal_message_at_welcome_follows_normal_flow(self, _mock):
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, "привет")
        assert state.step == "cargo"
        assert state.data.custom.get("source") != "landing_prefill"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_at_non_welcome_step_ignored(self, _mock):
        """Landing signature at cargo step is not treated as prefill."""
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        # Treated as normal cargo text (long enough to pass)
        assert state.step == "pickup_count"
        assert state.data.custom.get("source") != "landing_prefill"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_with_xss_sanitised(self, _mock):
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Детали: <script>document.cookie</script> диван и стол"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        assert "<script>" not in (state.data.cargo_description or "")
        assert "диван" in (state.data.cargo_description or "")

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_ack_message_shown(self, _mock):
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert "заявку с сайта" in reply.lower() or "сайта" in reply.lower()

    def test_pure_url_at_cargo_rejected(self):
        state = self.handler.new_session("t1", "chat1")
        state.step = "cargo"
        state, reply, done = self.handler.handle_text(state, "http://evil.com/malware")
        assert state.step == "cargo"  # stays on same step
        assert "ссылок" in reply.lower() or "ссылок" in reply


# ===================================================================
# Phase 15: Landing prefill normalization (structured parsing)
# ===================================================================


class TestLandingPrefillNormalization:
    """Tests for structured date/route parsing in landing prefill."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_date_parsed_structurally(self, _mock):
        """'15 марта' in landing → parsed as ISO date."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.data.custom.get("landing_date_parsed") is True
        move_date = state.data.custom.get("move_date")
        assert move_date is not None
        # Should be Mar 15 (2026 or 2027 depending on timing)
        assert "-03-15" in move_date

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_route_classified(self, _mock):
        """Хайфа→Тель-Авив in landing → route classification stored."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        rc = state.data.custom.get("route_classification")
        assert rc is not None
        assert rc["band"] == "inter_region_short"
        assert rc["from_region"] is not None
        assert rc["to_region"] is not None

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_unparseable_date_stored_as_hint(self, _mock):
        """Non-parseable date text stored as hint, marked as not parsed."""
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Квартира\n"
            "Дата: как можно скорее\n"
            "Детали: 2 комнаты, диван"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        assert state.data.custom.get("landing_date_hint") == "как можно скорее"
        assert state.data.custom.get("landing_date_parsed") is False
        assert "move_date" not in state.data.custom

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_no_addr_to_no_route(self, _mock):
        """Landing without addr_to → no route classification."""
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Квартира\n"
            "Откуда: Хайфа\n"
            "Детали: 2 комнаты"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        assert "route_classification" not in state.data.custom

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_same_city_route(self, _mock):
        """Landing with both addresses in same city → same_city band."""
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Квартира\n"
            "Откуда: Хайфа, Кармель\n"
            "Куда: Хайфа, центр\n"
            "Детали: 2 комнаты, стол"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        rc = state.data.custom.get("route_classification")
        assert rc is not None
        assert rc["band"] == "same_city"


# ===================================================================
# Landing prefill: confirm_addresses & date-skip flow
# ===================================================================


class TestLandingConfirmAddresses:
    """Landing with addresses → confirm_addresses step."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_confirm_yes_goes_to_pickup_count(self, _mock):
        """User chooses '1' (yes) → pickup_count → normal address flow."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.step == "confirm_addresses"

        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "pickup_count"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_confirm_no_skips_to_time_slot(self, _mock):
        """User chooses '2' (no) with parsed date → skip addresses AND date → time_slot."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.step == "confirm_addresses"
        # Date '20 февраля' was parsed successfully
        assert state.data.custom.get("landing_date_parsed") is True

        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "time_slot"
        # Addresses kept from landing
        assert state.data.addr_from == "Хайфа, Нешер"
        assert state.data.addr_to == "Тель-Авив"
        assert state.data.custom.get("landing_addresses_kept") is True
        # Pickup stored with placeholder floor
        assert len(state.data.custom["pickups"]) == 1
        assert state.data.custom["pickups"][0]["addr"] == "Хайфа, Нешер"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_confirm_no_unparsed_date_goes_to_date(self, _mock):
        """User chooses '2' (no) with unparseable date → skip addresses → date step."""
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Тип: Квартира\n"
            "Откуда: Хайфа\n"
            "Куда: Тель-Авив\n"
            "Дата: как можно скорее\n"
            "Детали: 2 комнаты, диван"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        assert state.step == "confirm_addresses"
        assert state.data.custom.get("landing_date_parsed") is False

        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "date"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_confirm_invalid_choice_stays(self, _mock):
        """Invalid input at confirm_addresses → stays on same step."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.step == "confirm_addresses"

        state, reply, done = self.handler.handle_text(state, "hello")
        assert state.step == "confirm_addresses"
        assert not done

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_confirm_yes_full_flow_with_date_skip(self, _mock):
        """User says '1' → goes through addresses → floor_to skips date → time_slot."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.step == "confirm_addresses"
        assert state.data.custom.get("landing_date_parsed") is True

        # Confirm yes → pickup_count
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "pickup_count"

        # 1 pickup
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "addr_from"

        # Full address
        state, reply, done = self.handler.handle_text(state, "Хайфа, Герцль 10")
        assert state.step == "floor_from"

        state, reply, done = self.handler.handle_text(state, "3 этаж, без лифта")
        assert state.step == "addr_to"

        state, reply, done = self.handler.handle_text(state, "Тель-Авив, Дизенгоф 50")
        assert state.step == "floor_to"

        # After floor_to with parsed date → skip date → time_slot
        state, reply, done = self.handler.handle_text(state, "5 этаж, лифт есть")
        assert state.step == "time_slot"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_confirm_no_then_time_slot_continues(self, _mock):
        """After skipping addresses, time_slot → photo_menu works normally."""
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, _FULL_LANDING_MSG)
        assert state.step == "confirm_addresses"

        state, reply, done = self.handler.handle_text(state, "2")
        assert state.step == "time_slot"

        # Choose morning
        state, reply, done = self.handler.handle_text(state, "1")
        assert state.step == "photo_menu"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_without_addresses_skips_confirm(self, _mock):
        """Landing with details but no addresses → no confirm step, straight to pickup_count."""
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Детали: 2 комнаты, диван и стол"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        # No addresses → no confirm_addresses → pickup_count
        assert state.step == "pickup_count"

    @patch("app.core.handlers.moving_bot_handler.get_operator_config",
           return_value={})
    def test_landing_one_address_only_skips_confirm(self, _mock):
        """Landing with only addr_from (no addr_to) → no confirm step."""
        msg = (
            "Здравствуйте! Хочу узнать стоимость переезда.\n"
            "Откуда: Хайфа\n"
            "Детали: 2 комнаты, диван и стол"
        )
        state = self.handler.new_session("t1", "chat1")
        state, reply, done = self.handler.handle_text(state, msg)
        assert state.step == "pickup_count"


# ===================================================================
# Phase 15: Structured logging
# ===================================================================


class TestEstimateStructuredLogging:
    """Verify structured logging on estimate computation."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_estimate_emits_log(self):
        """_transition_to_estimate emits a structured log message."""
        import logging
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["volume_category"] = "small"
        state.step = "extras"

        with patch("app.core.handlers.moving_bot_handler.logger") as mock_logger:
            state, reply, done = self.handler.handle_text(state, "4")
            assert state.step == "estimate"
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args
            assert call_args[0][0] == "estimate_computed"
            extra = call_args[1]["extra"]
            assert "estimate_min" in extra
            assert "estimate_max" in extra
            assert extra["volume_category"] == "small"
            assert extra["event"] == "estimate_computed"
            assert extra["lead_id"] == state.lead_id
            assert extra["tenant_id"] == "t1"
            assert "route_band" in extra
            assert "guards_applied" in extra
            assert "pickup_count" in extra


# ===================================================================
# Fix: Sofa space-variant aliases ("5 местный диван" → sofa_5seat)
# ===================================================================


class TestSofaSpaceVariantAliases:
    """Verify '5 местный диван' (space, not hyphen) maps correctly."""

    def test_5_mestny_space(self):
        """'5 местный диван' → sofa_5seat x1."""
        items = extract_items("5 местный диван")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_5seat") == 1
        assert "sofa_large_3_seat" not in found

    def test_4_mestny_space(self):
        """'4 местный диван' → sofa_4seat x1."""
        items = extract_items("4 местный диван")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_4seat") == 1
        assert "sofa_large_3_seat" not in found

    def test_3_mestny_space(self):
        """'3 местный диван' → sofa_3seat x1."""
        items = extract_items("3 местный диван")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_large_3_seat") == 1

    def test_2_mestny_space(self):
        """'2 местный диван' → sofa_2seat x1."""
        items = extract_items("2 местный диван")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_small_2_seat") == 1
        assert "sofa_large_3_seat" not in found

    def test_plain_divan_no_regression(self):
        """Plain 'диван' still maps to sofa_3seat x1 (no regression)."""
        items = extract_items("диван")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_large_3_seat") == 1

    def test_attr_suffix_mestny(self):
        """_ATTR_SUFFIXES matches '5 местный' so bare 5 is not qty."""
        assert _ATTR_SUFFIXES.search("5 местный")
        assert _ATTR_SUFFIXES.search("5-местный")

    def test_5_seater_sofa(self):
        """'5-seater sofa' → sofa_5seat x1."""
        items = extract_items("5-seater sofa")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_5seat") == 1

    def test_attr_suffix_seater(self):
        """_ATTR_SUFFIXES matches '5-seater' so bare 5 is not qty."""
        assert _ATTR_SUFFIXES.search("5-seater")
        assert _ATTR_SUFFIXES.search("5 seater")


# ===================================================================
# Fix: Children's bed aliases ("детская кровать" → bed_single)
# ===================================================================


class TestChildrenBedAliases:
    """Verify 'детская кровать' maps to bed_single, not bed_double."""

    def test_detskaya_krovat(self):
        """'детская кровать' → bed_single x1."""
        items = extract_items("детская кровать")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("bed_single") == 1
        assert "bed_double" not in found

    def test_detskaya_krovatka(self):
        """'детская кроватка' → bed_single x1."""
        items = extract_items("детская кроватка")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("bed_single") == 1
        assert "bed_double" not in found

    def test_detskaya_and_plain_separate(self):
        """'детская кровать и кровать' → bed_single x1 + bed_double x1."""
        items = extract_items("детская кровать и кровать")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("bed_single") == 1
        assert found.get("bed_double") == 1

    def test_kids_bed_english(self):
        """'kids bed' → bed_single x1."""
        items = extract_items("kids bed")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("bed_single") == 1

    def test_children_bed_hebrew(self):
        """'מיטת ילדים' → bed_single x1."""
        items = extract_items("מיטת ילדים")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("bed_single") == 1


# ===================================================================
# Fix: Mattress item (new in catalog)
# ===================================================================


class TestMattressItem:
    """Verify mattress is in catalog and recognised."""

    def test_matras(self):
        """'матрас' → mattress x1."""
        items = extract_items("матрас")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("mattress") == 1

    def test_matras_double_s(self):
        """'матрасс' (common misspelling) → mattress x1."""
        items = extract_items("матрасс")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("mattress") == 1

    def test_matrats(self):
        """'матрац' (alternative form) → mattress x1."""
        items = extract_items("матрац")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("mattress") == 1

    def test_2_matrasy(self):
        """'2 матрасы' → mattress x2."""
        items = extract_items("2 матрасы")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("mattress") == 2

    def test_mattress_in_catalog(self):
        """Mattress price range is (60, 120)."""
        assert "mattress" in ITEM_CATALOG
        lo, hi = ITEM_CATALOG["mattress"]
        assert lo == 60
        assert hi == 120

    def test_mattress_not_heavy(self):
        """Mattress is NOT a heavy item."""
        heavy_keys = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "mattress" not in heavy_keys

    def test_mattress_label(self):
        """Mattress has labels in all 3 languages."""
        assert "mattress" in ITEM_LABELS
        assert ITEM_LABELS["mattress"]["ru"] == "Матрас"
        assert ITEM_LABELS["mattress"]["en"] == "Mattress"
        assert ITEM_LABELS["mattress"]["he"] == "מזרן"

    def test_mattress_english(self):
        """'mattress' (English) → mattress x1."""
        items = extract_items("mattress")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("mattress") == 1

    def test_mattress_hebrew(self):
        """'מזרן' (Hebrew) → mattress x1."""
        items = extract_items("מזרן")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("mattress") == 1


# ===================================================================
# Fix: Combined scenario (all four bugs together)
# ===================================================================


class TestCombinedItemExtractionFixes:
    """Verify the exact user scenario that triggered the bug report."""

    def test_combined_5_mestny_detskaya_matras(self):
        """'5 местный диван, детская кровать, 2 матрасы, кровать' →
        sofa_5seat x1, bed_single x1, mattress x2, bed_double x1."""
        items = extract_items("5 местный диван, детская кровать, 2 матрасы, кровать")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_5seat") == 1, f"Expected sofa_5seat=1, got {found}"
        assert found.get("bed_single") == 1, f"Expected bed_single=1, got {found}"
        assert found.get("mattress") == 2, f"Expected mattress=2, got {found}"
        assert found.get("bed_double") == 1, f"Expected bed_double=1, got {found}"
        # Must NOT have sofa_3seat or duplicate beds
        assert "sofa_large_3_seat" not in found

    def test_original_bug_report(self):
        """The original report: '5 местный диван, детская кровать, кровать, матрас'.
        Should NOT be sofas x5 + bed x2 + no mattress."""
        items = extract_items("5 местный диван, детская кровать, кровать, матрас")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("sofa_5seat") == 1
        assert found.get("bed_single") == 1
        assert found.get("bed_double") == 1
        assert found.get("mattress") == 1
        # Total unique items: 4
        assert len(found) == 4


# ===================================================================
# Estimate suppression fallback
# ===================================================================


class TestEstimateSuppression:
    """Verify estimate is suppressed when parsing quality is low."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_estimate_suppressed_when_no_items(self):
        """Long cargo_raw with 0 extracted items → estimate suppressed."""
        state = self.handler.new_session("t1", "chat1")
        # Simulate: user wrote lots of unrecognised text
        state.data.custom["cargo_raw"] = "у нас много всякого барахла и разных штук которые нужно перевезти в другой город"
        state.data.custom["cargo_items"] = []
        # No volume_category
        state.step = "extras"

        # Go through extras → estimate
        state, reply, done = self.handler.handle_text(state, "4")  # none extras
        assert state.step == "estimate"
        assert state.data.custom.get("estimate_suppressed") is True
        assert "estimate_min" not in state.data.custom
        assert "estimate_max" not in state.data.custom
        # Reply should be the no-price message
        assert "менеджер" in reply.lower() or "manager" in reply.lower() or "מנהל" in reply

    def test_estimate_shown_when_items_extracted(self):
        """Cargo with recognised items → normal estimate (not suppressed)."""
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["cargo_raw"] = "диван, холодильник, 5 коробок"
        state.data.custom["cargo_items"] = extract_items("диван, холодильник, 5 коробок")
        state.data.custom["volume_category"] = "large"
        state.step = "extras"

        state, reply, done = self.handler.handle_text(state, "4")  # none extras
        assert state.step == "estimate"
        assert state.data.custom.get("estimate_suppressed") is not True
        assert "estimate_min" in state.data.custom
        assert "estimate_max" in state.data.custom

    def test_estimate_shown_when_short_raw(self):
        """Short cargo_raw (≤30 chars) → normal estimate even with 0 items."""
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["cargo_raw"] = "всякое барахло"  # 14 chars
        state.data.custom["cargo_items"] = []
        state.data.custom["volume_category"] = "small"
        state.step = "extras"

        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        # Not suppressed because cargo_raw ≤ 30 chars (and has volume_category)
        assert state.data.custom.get("estimate_suppressed") is not True
        assert "estimate_min" in state.data.custom

    def test_estimate_shown_when_volume_exists(self):
        """Long raw but volume_category set → estimate shown (rooms detection worked)."""
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["cargo_raw"] = "переезд из трёхкомнатной квартиры, много всего разного"
        state.data.custom["cargo_items"] = []
        state.data.custom["volume_category"] = "large"  # inferred from rooms
        state.step = "extras"

        state, reply, done = self.handler.handle_text(state, "4")
        assert state.step == "estimate"
        assert state.data.custom.get("estimate_suppressed") is not True
        assert "estimate_min" in state.data.custom


# ===================================================================
# Crew view: estimate suppression
# ===================================================================


class TestCrewViewEstimateSuppression:
    """Verify crew message omits estimate when suppressed."""

    def test_crew_view_no_estimate_when_suppressed(self):
        from app.core.dispatch.crew_view import format_crew_message

        payload = {
            "data": {
                "floor_from": "3",
                "floor_to": "2",
                "time_window": "morning",
                "extras": [],
                "custom": {
                    "lead_number": 42,
                    "volume_category": None,
                    "route_classification": {
                        "from_locality": "Tel Aviv",
                        "to_locality": "Haifa",
                    },
                    "cargo_items": [],
                    "estimate_suppressed": True,
                    # No estimate_min / estimate_max
                },
            },
        }
        msg = format_crew_message("test-lead-id", payload)
        # Should NOT contain estimate line
        assert "₪" not in msg
        # Should still contain other info
        assert "#42" in msg

    def test_crew_view_shows_estimate_normally(self):
        from app.core.dispatch.crew_view import format_crew_message

        payload = {
            "data": {
                "floor_from": "3",
                "floor_to": "2",
                "time_window": "morning",
                "extras": [],
                "custom": {
                    "lead_number": 43,
                    "volume_category": "large",
                    "route_classification": {
                        "from_locality": "Tel Aviv",
                        "to_locality": "Haifa",
                    },
                    "cargo_items": [],
                    "estimate_min": 1500,
                    "estimate_max": 2000,
                },
            },
        }
        msg = format_crew_message("test-lead-id", payload)
        assert "₪1500–₪2000" in msg
        assert "#43" in msg


# ===================================================================
# New catalog items: vanity_table, shoe_cabinet
# ===================================================================


class TestVanityTableItem:
    """Verify vanity_table is in catalog and recognised."""

    def test_buduar(self):
        """'будуар' → vanity_table x1."""
        items = extract_items("будуар")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("vanity_table") == 1

    def test_buduar_so_stulom(self):
        """'будуар со стулом' → vanity_table x1."""
        items = extract_items("будуар со стулом")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("vanity_table") == 1

    def test_zhenskiy_stol(self):
        """'женский стол с зеркалом' → vanity_table x1."""
        items = extract_items("женский стол с зеркалом")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("vanity_table") == 1

    def test_tualetny_stolik(self):
        """'туалетный столик' → vanity_table x1."""
        items = extract_items("туалетный столик")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("vanity_table") == 1

    def test_tryumo(self):
        """'трюмо' → vanity_table x1."""
        items = extract_items("трюмо")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("vanity_table") == 1

    def test_vanity_table_in_catalog(self):
        """Vanity table price range is (100, 180)."""
        assert "vanity_table" in ITEM_CATALOG
        lo, hi = ITEM_CATALOG["vanity_table"]
        assert lo == 100
        assert hi == 180

    def test_vanity_table_not_heavy(self):
        """Vanity table is NOT a heavy item."""
        heavy_keys = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "vanity_table" not in heavy_keys

    def test_vanity_table_label(self):
        """Vanity table has labels in all 3 languages."""
        assert "vanity_table" in ITEM_LABELS
        assert ITEM_LABELS["vanity_table"]["ru"] == "Будуар"
        assert ITEM_LABELS["vanity_table"]["en"] == "Vanity table"
        assert ITEM_LABELS["vanity_table"]["he"] == "שולחן איפור"

    def test_vanity_table_english(self):
        """'vanity table' → vanity_table x1."""
        items = extract_items("vanity table")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("vanity_table") == 1

    def test_vanity_table_hebrew(self):
        """'שולחן איפור' → vanity_table x1."""
        items = extract_items("שולחן איפור")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("vanity_table") == 1


class TestShoeCabinetItem:
    """Verify shoe_cabinet is in catalog and recognised."""

    def test_obuvnitsa(self):
        """'обувница' → shoe_cabinet x1."""
        items = extract_items("обувница")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shoe_cabinet") == 1

    def test_shkaf_dlya_obuvi(self):
        """'шкаф для обуви' → shoe_cabinet x1 (not wardrobe)."""
        items = extract_items("шкаф для обуви")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shoe_cabinet") == 1
        assert "wardrobe_2_doors" not in found
        assert "wardrobe_3_doors" not in found

    def test_komod_dlya_obuvi(self):
        """'комод для обуви' → shoe_cabinet x1."""
        items = extract_items("комод для обуви")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shoe_cabinet") == 1

    def test_polka_dlya_obuvi(self):
        """'полка для обуви' → shoe_cabinet x1 (not shelving_unit)."""
        items = extract_items("полка для обуви")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shoe_cabinet") == 1
        assert "shelving_unit" not in found

    def test_tumba_dlya_obuvi(self):
        """'тумба для обуви' → shoe_cabinet x1."""
        items = extract_items("тумба для обуви")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shoe_cabinet") == 1

    def test_shoe_cabinet_in_catalog(self):
        """Shoe cabinet price range is (60, 120)."""
        assert "shoe_cabinet" in ITEM_CATALOG
        lo, hi = ITEM_CATALOG["shoe_cabinet"]
        assert lo == 60
        assert hi == 120

    def test_shoe_cabinet_not_heavy(self):
        """Shoe cabinet is NOT a heavy item."""
        heavy_keys = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "shoe_cabinet" not in heavy_keys

    def test_shoe_cabinet_label(self):
        """Shoe cabinet has labels in all 3 languages."""
        assert "shoe_cabinet" in ITEM_LABELS
        assert ITEM_LABELS["shoe_cabinet"]["ru"] == "Обувница"
        assert ITEM_LABELS["shoe_cabinet"]["en"] == "Shoe cabinet"
        assert ITEM_LABELS["shoe_cabinet"]["he"] == "ארון נעליים"

    def test_shoe_cabinet_english(self):
        """'shoe cabinet' → shoe_cabinet x1."""
        items = extract_items("shoe cabinet")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shoe_cabinet") == 1

    def test_shoe_cabinet_hebrew(self):
        """'ארון נעליים' → shoe_cabinet x1."""
        items = extract_items("ארון נעליים")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shoe_cabinet") == 1

    def test_plain_polka_still_shelving(self):
        """'полка' alone still matches shelving_unit (no regression)."""
        items = extract_items("полка")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("shelving_unit") == 1

    def test_plain_shkaf_still_wardrobe(self):
        """'шкаф' alone still matches wardrobe_3_doors (default)."""
        items = extract_items("шкаф")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("wardrobe_3_doors") == 1


# ===================================================================
# Estimate display toggle (ESTIMATE_DISPLAY_ENABLED setting)
# ===================================================================


class TestEstimateDisplayToggle:
    """Verify estimate_display_enabled=False hides price from user/crew
    but operator data (estimate_min/max) is still stored."""

    def setup_method(self):
        self.handler = MovingBotHandler()

    def test_user_sees_no_price_when_disabled(self):
        """When estimate_display_enabled=False, user gets estimate_no_price text."""
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["cargo_raw"] = "диван, холодильник"
        state.data.custom["cargo_items"] = extract_items("диван, холодильник")
        state.data.custom["volume_category"] = "large"
        state.step = "extras"

        with patch("app.core.handlers.moving_bot_handler._app_settings") as mock_s:
            mock_s.estimate_display_enabled = False
            state, reply, done = self.handler.handle_text(state, "4")

        assert state.step == "estimate"
        # Estimate data IS stored (for operator)
        assert "estimate_min" in state.data.custom
        assert "estimate_max" in state.data.custom
        assert state.data.custom.get("estimate_display_disabled") is True
        # But user sees no-price message
        assert "₪" not in reply

    def test_user_sees_price_when_enabled(self):
        """When estimate_display_enabled=True (default), user sees price."""
        state = self.handler.new_session("t1", "chat1")
        state.data.custom["cargo_raw"] = "диван, холодильник"
        state.data.custom["cargo_items"] = extract_items("диван, холодильник")
        state.data.custom["volume_category"] = "large"
        state.step = "extras"

        with patch("app.core.handlers.moving_bot_handler._app_settings") as mock_s:
            mock_s.estimate_display_enabled = True
            state, reply, done = self.handler.handle_text(state, "4")

        assert state.step == "estimate"
        assert "estimate_min" in state.data.custom
        assert state.data.custom.get("estimate_display_disabled") is not True
        assert "₪" in reply

    def test_crew_no_estimate_when_display_disabled(self):
        """Crew message omits estimate when estimate_display_disabled flag is set."""
        from app.core.dispatch.crew_view import format_crew_message

        payload = {
            "data": {
                "floor_from": "3",
                "floor_to": "2",
                "time_window": "morning",
                "extras": [],
                "custom": {
                    "lead_number": 50,
                    "volume_category": "large",
                    "route_classification": {
                        "from_locality": "Tel Aviv",
                        "to_locality": "Haifa",
                    },
                    "cargo_items": [],
                    "estimate_min": 1500,
                    "estimate_max": 2000,
                    "estimate_display_disabled": True,
                },
            },
        }
        msg = format_crew_message("test-lead-id", payload)
        # Should NOT contain estimate line despite data being present
        assert "₪" not in msg
        assert "#50" in msg

    def test_crew_shows_estimate_normally(self):
        """Default: crew sees estimate when display is not disabled."""
        from app.core.dispatch.crew_view import format_crew_message

        payload = {
            "data": {
                "floor_from": "3",
                "floor_to": "2",
                "time_window": "morning",
                "extras": [],
                "custom": {
                    "lead_number": 51,
                    "volume_category": "large",
                    "route_classification": {
                        "from_locality": "Tel Aviv",
                        "to_locality": "Haifa",
                    },
                    "cargo_items": [],
                    "estimate_min": 1500,
                    "estimate_max": 2000,
                },
            },
        }
        msg = format_crew_message("test-lead-id", payload)
        assert "₪1500–₪2000" in msg
        assert "#51" in msg


# ===================================================================
# New catalog items: armchair, dresser, nightstand, carpet, mirror, oven
# ===================================================================


class TestArmchairItem:
    """Verify armchair is in catalog and recognised."""

    def test_kreslo(self):
        items = extract_items("кресло")
        assert {i["key"]: i["qty"] for i in items}.get("armchair") == 1

    def test_kresla(self):
        items = extract_items("кресла")
        assert {i["key"]: i["qty"] for i in items}.get("armchair") == 1

    def test_2_kresla(self):
        items = extract_items("2 кресла")
        assert {i["key"]: i["qty"] for i in items}.get("armchair") == 2

    def test_armchair_catalog(self):
        assert "armchair" in ITEM_CATALOG
        assert ITEM_CATALOG["armchair"] == (120, 180)

    def test_armchair_not_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "armchair" not in heavy

    def test_armchair_label(self):
        assert ITEM_LABELS["armchair"]["ru"] == "Кресло"
        assert ITEM_LABELS["armchair"]["en"] == "Armchair"

    def test_armchair_english(self):
        items = extract_items("armchair")
        assert {i["key"]: i["qty"] for i in items}.get("armchair") == 1


class TestDresserItem:
    """Verify dresser (комод) is in catalog and recognised."""

    def test_komod(self):
        items = extract_items("комод")
        assert {i["key"]: i["qty"] for i in items}.get("dresser") == 1

    def test_komod_not_shoe_cabinet(self):
        """Plain 'комод' → dresser, NOT shoe_cabinet."""
        items = extract_items("комод")
        found = {i["key"]: i["qty"] for i in items}
        assert "shoe_cabinet" not in found

    def test_komod_dlya_obuvi_still_shoe(self):
        """'комод для обуви' → shoe_cabinet (no regression)."""
        items = extract_items("комод для обуви")
        assert {i["key"]: i["qty"] for i in items}.get("shoe_cabinet") == 1

    def test_dresser_catalog(self):
        assert "dresser" in ITEM_CATALOG
        assert ITEM_CATALOG["dresser"] == (150, 250)

    def test_dresser_is_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "dresser" in heavy

    def test_dresser_label(self):
        assert ITEM_LABELS["dresser"]["ru"] == "Комод"

    def test_dresser_english(self):
        items = extract_items("dresser")
        assert {i["key"]: i["qty"] for i in items}.get("dresser") == 1


class TestNightstandItem:
    """Verify nightstand (тумбочка) is in catalog and recognised."""

    def test_tumbochka(self):
        items = extract_items("тумбочка")
        assert {i["key"]: i["qty"] for i in items}.get("nightstand") == 1

    def test_tumbochki(self):
        items = extract_items("тумбочки")
        assert {i["key"]: i["qty"] for i in items}.get("nightstand") == 1

    def test_2_tumbochki(self):
        items = extract_items("2 тумбочки")
        assert {i["key"]: i["qty"] for i in items}.get("nightstand") == 2

    def test_tumba(self):
        items = extract_items("тумба")
        assert {i["key"]: i["qty"] for i in items}.get("nightstand") == 1

    def test_tumba_dlya_obuvi_still_shoe(self):
        """'тумба для обуви' → shoe_cabinet (no regression)."""
        items = extract_items("тумба для обуви")
        assert {i["key"]: i["qty"] for i in items}.get("shoe_cabinet") == 1

    def test_nightstand_catalog(self):
        assert "nightstand" in ITEM_CATALOG
        assert ITEM_CATALOG["nightstand"] == (60, 80)

    def test_nightstand_not_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "nightstand" not in heavy

    def test_nightstand_label(self):
        assert ITEM_LABELS["nightstand"]["ru"] == "Тумбочка"


class TestCarpetItem:
    """Verify carpet (ковёр) is in catalog and recognised."""

    def test_kover_yo(self):
        items = extract_items("ковёр")
        assert {i["key"]: i["qty"] for i in items}.get("carpet") == 1

    def test_kover_e(self):
        items = extract_items("ковер")
        assert {i["key"]: i["qty"] for i in items}.get("carpet") == 1

    def test_kovry(self):
        items = extract_items("ковры")
        assert {i["key"]: i["qty"] for i in items}.get("carpet") == 1

    def test_6_kovrov(self):
        items = extract_items("6 ковров")
        assert {i["key"]: i["qty"] for i in items}.get("carpet") == 6

    def test_carpet_catalog(self):
        assert "carpet" in ITEM_CATALOG
        assert ITEM_CATALOG["carpet"] == (30, 50)

    def test_carpet_not_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "carpet" not in heavy

    def test_carpet_label(self):
        assert ITEM_LABELS["carpet"]["ru"] == "Ковёр"

    def test_carpet_english(self):
        items = extract_items("carpet")
        assert {i["key"]: i["qty"] for i in items}.get("carpet") == 1


class TestMirrorItem:
    """Verify mirror (зеркало) is in catalog and recognised."""

    def test_zerkalo(self):
        items = extract_items("зеркало")
        assert {i["key"]: i["qty"] for i in items}.get("mirror") == 1

    def test_zerkala(self):
        items = extract_items("зеркала")
        assert {i["key"]: i["qty"] for i in items}.get("mirror") == 1

    def test_mirror_catalog(self):
        assert "mirror" in ITEM_CATALOG
        assert ITEM_CATALOG["mirror"] == (40, 80)

    def test_mirror_not_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "mirror" not in heavy

    def test_mirror_label(self):
        assert ITEM_LABELS["mirror"]["ru"] == "Зеркало"

    def test_mirror_english(self):
        items = extract_items("mirror")
        assert {i["key"]: i["qty"] for i in items}.get("mirror") == 1


class TestOvenItem:
    """Verify oven (духовка) is in catalog and recognised."""

    def test_duhovka(self):
        items = extract_items("духовка")
        assert {i["key"]: i["qty"] for i in items}.get("oven") == 1

    def test_duhovoy_shkaf(self):
        items = extract_items("духовой шкаф")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("oven") == 1
        assert "wardrobe_2_doors" not in found
        assert "wardrobe_3_doors" not in found

    def test_pech(self):
        items = extract_items("печь")
        assert {i["key"]: i["qty"] for i in items}.get("oven") == 1

    def test_oven_catalog(self):
        assert "oven" in ITEM_CATALOG
        assert ITEM_CATALOG["oven"] == (150, 200)

    def test_oven_is_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "oven" in heavy

    def test_oven_label(self):
        assert ITEM_LABELS["oven"]["ru"] == "Духовка"

    def test_oven_english(self):
        items = extract_items("oven")
        assert {i["key"]: i["qty"] for i in items}.get("oven") == 1


# ===================================================================
# Fix: bed_double plural alias ("кровати" → bed_double)
# ===================================================================


class TestBedPluralFix:
    """Verify 'кровати' and 'кроватей' map to bed_double."""

    def test_krovati(self):
        items = extract_items("кровати")
        assert {i["key"]: i["qty"] for i in items}.get("bed_double") == 1

    def test_2_krovati(self):
        items = extract_items("2 кровати")
        assert {i["key"]: i["qty"] for i in items}.get("bed_double") == 2

    def test_krovatey(self):
        items = extract_items("кроватей")
        assert {i["key"]: i["qty"] for i in items}.get("bed_double") == 1

    def test_detskie_krovatki(self):
        """'детские кроватки' → bed_single."""
        items = extract_items("детские кроватки")
        assert {i["key"]: i["qty"] for i in items}.get("bed_single") == 1

    def test_krovat_singular_no_regression(self):
        """'кровать' still → bed_double (no regression)."""
        items = extract_items("кровать")
        assert {i["key"]: i["qty"] for i in items}.get("bed_double") == 1


# ===================================================================
# Full cargo scenario (the exact user input that triggered the report)
# ===================================================================


class TestFullCargoScenario:
    """The exact 20-item user input should extract 17 unique keys."""

    def test_full_20_item_input(self):
        text = ("2 кресла, обеденный стол, 5 стульев, 5 местный диван, "
                "комод, телевизор, большой холодильник, холодильник, "
                "газовая плита, шкаф, комод, зеркало, 2 тумбочки, "
                "диван, большой шкаф, 2 тумбочки, диван, 6 ковров, "
                "2 кровати, 2 матраса")
        items = extract_items(text)
        found = {i["key"]: i["qty"] for i in items}
        assert len(found) == 17
        assert found["armchair"] == 2
        assert found["dining_table"] == 1
        assert found["chair"] == 5
        assert found["sofa_5seat"] == 1
        assert found["dresser"] == 2
        assert found["tv_monitor"] == 1
        assert found["fridge_double_door"] == 1       # "большой холодильник"
        assert found["fridge_single_door"] == 1       # "холодильник"
        assert found["gas_stove"] == 1
        assert found["wardrobe_3_doors"] == 1         # "шкаф" (generic → 3-doors)
        assert found["wardrobe_4_doors"] == 1         # "большой шкаф" → 4-doors
        assert found["mirror"] == 1
        assert found["nightstand"] == 4
        assert found["sofa_large_3_seat"] == 2
        assert found["carpet"] == 6
        assert found["bed_double"] == 2
        assert found["mattress"] == 2


# ===================================================================
# Catalog Restructuring v3.0: Fridge split
# ===================================================================


class TestFridgeSplit:
    """Verify fridge_single_door, fridge_double_door, fridge_side_by_side."""

    def test_plain_holodilnik(self):
        """'холодильник' → fridge_single_door (default)."""
        items = extract_items("холодильник")
        assert {i["key"]: i["qty"] for i in items}.get("fridge_single_door") == 1

    def test_bolshoy_holodilnik(self):
        """'большой холодильник' → fridge_double_door."""
        items = extract_items("большой холодильник")
        assert {i["key"]: i["qty"] for i in items}.get("fridge_double_door") == 1

    def test_dvuhdverny(self):
        """'двухдверный холодильник' → fridge_double_door."""
        items = extract_items("двухдверный холодильник")
        assert {i["key"]: i["qty"] for i in items}.get("fridge_double_door") == 1

    def test_side_by_side(self):
        """'side by side' → fridge_side_by_side."""
        items = extract_items("side by side")
        assert {i["key"]: i["qty"] for i in items}.get("fridge_side_by_side") == 1

    def test_said_bay_said(self):
        """'сайд бай сайд' → fridge_side_by_side."""
        items = extract_items("сайд бай сайд")
        assert {i["key"]: i["qty"] for i in items}.get("fridge_side_by_side") == 1

    def test_fridge_single_door_price(self):
        assert ITEM_CATALOG["fridge_single_door"] == (200, 280)

    def test_fridge_double_door_price(self):
        assert ITEM_CATALOG["fridge_double_door"] == (280, 380)

    def test_fridge_side_by_side_price(self):
        assert ITEM_CATALOG["fridge_side_by_side"] == (350, 500)

    def test_all_fridges_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "fridge_single_door" in heavy
        assert "fridge_double_door" in heavy
        assert "fridge_side_by_side" in heavy

    def test_fridge_labels(self):
        assert ITEM_LABELS["fridge_single_door"]["ru"] == "Холодильник"
        assert ITEM_LABELS["fridge_double_door"]["en"] == "Double-door fridge"
        assert ITEM_LABELS["fridge_side_by_side"]["en"] == "Side-by-side fridge"


# ===================================================================
# Catalog Restructuring v3.0: Sofa corner
# ===================================================================


class TestSofaCorner:
    """Verify sofa_corner extraction."""

    def test_uglovoy_divan(self):
        """'угловой диван' → sofa_corner."""
        items = extract_items("угловой диван")
        assert {i["key"]: i["qty"] for i in items}.get("sofa_corner") == 1

    def test_g_obrazny(self):
        """'г-образный диван' → sofa_corner."""
        items = extract_items("г-образный диван")
        assert {i["key"]: i["qty"] for i in items}.get("sofa_corner") == 1

    def test_corner_sofa_en(self):
        """'corner sofa' → sofa_corner."""
        items = extract_items("corner sofa")
        assert {i["key"]: i["qty"] for i in items}.get("sofa_corner") == 1

    def test_sofa_corner_price(self):
        assert ITEM_CATALOG["sofa_corner"] == (280, 400)

    def test_sofa_corner_is_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "sofa_corner" in heavy

    def test_sofa_corner_label(self):
        assert ITEM_LABELS["sofa_corner"]["ru"] == "Угловой диван"
        assert ITEM_LABELS["sofa_corner"]["he"] == "ספה פינתית"


# ===================================================================
# Catalog Restructuring v3.0: Wardrobe 4-doors
# ===================================================================


class TestWardrobe4Doors:
    """Verify wardrobe_4_doors extraction."""

    def test_bolshoy_shkaf(self):
        """'большой шкаф' → wardrobe_4_doors."""
        items = extract_items("большой шкаф")
        assert {i["key"]: i["qty"] for i in items}.get("wardrobe_4_doors") == 1

    def test_shkaf_kupe(self):
        """'шкаф-купе' → wardrobe_4_doors."""
        items = extract_items("шкаф-купе")
        assert {i["key"]: i["qty"] for i in items}.get("wardrobe_4_doors") == 1

    def test_shkaf_4_dveri(self):
        """'шкаф 4 двери' → wardrobe_4_doors, qty=1."""
        items = extract_items("шкаф 4 двери")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("wardrobe_4_doors") == 1

    def test_large_wardrobe_en(self):
        """'large wardrobe' → wardrobe_4_doors."""
        items = extract_items("large wardrobe")
        assert {i["key"]: i["qty"] for i in items}.get("wardrobe_4_doors") == 1

    def test_wardrobe_4_doors_price(self):
        assert ITEM_CATALOG["wardrobe_4_doors"] == (350, 500)

    def test_wardrobe_4_doors_is_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "wardrobe_4_doors" in heavy

    def test_wardrobe_4_doors_label(self):
        assert ITEM_LABELS["wardrobe_4_doors"]["ru"] == "Шкаф (4-двер.)"


# ===================================================================
# Catalog Restructuring v3.0: Bed with storage
# ===================================================================


class TestBedWithStorage:
    """Verify bed_with_storage extraction."""

    def test_krovat_s_yaschkami(self):
        """'кровать с ящиками' → bed_with_storage."""
        items = extract_items("кровать с ящиками")
        assert {i["key"]: i["qty"] for i in items}.get("bed_with_storage") == 1

    def test_krovat_s_podyomnym(self):
        """'кровать с подъёмным механизмом' → bed_with_storage."""
        items = extract_items("кровать с подъёмным механизмом")
        assert {i["key"]: i["qty"] for i in items}.get("bed_with_storage") == 1

    def test_storage_bed_en(self):
        """'storage bed' → bed_with_storage."""
        items = extract_items("storage bed")
        assert {i["key"]: i["qty"] for i in items}.get("bed_with_storage") == 1

    def test_bed_with_storage_price(self):
        assert ITEM_CATALOG["bed_with_storage"] == (250, 350)

    def test_bed_with_storage_is_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "bed_with_storage" in heavy

    def test_bed_with_storage_label(self):
        assert ITEM_LABELS["bed_with_storage"]["ru"] == "Кровать с ящиками"


# ===================================================================
# Catalog Restructuring v3.0: Exercise split (treadmill + home_gym)
# ===================================================================


class TestExerciseSplit:
    """Verify treadmill and home_gym extraction."""

    def test_begovaya_dorozhka(self):
        """'беговая дорожка' → treadmill."""
        items = extract_items("беговая дорожка")
        assert {i["key"]: i["qty"] for i in items}.get("treadmill") == 1

    def test_treadmill_en(self):
        """'treadmill' → treadmill."""
        items = extract_items("treadmill")
        assert {i["key"]: i["qty"] for i in items}.get("treadmill") == 1

    def test_trenazher(self):
        """'тренажер' → home_gym."""
        items = extract_items("тренажер")
        assert {i["key"]: i["qty"] for i in items}.get("home_gym") == 1

    def test_home_gym_en(self):
        """'home gym' → home_gym."""
        items = extract_items("home gym")
        assert {i["key"]: i["qty"] for i in items}.get("home_gym") == 1

    def test_treadmill_price(self):
        assert ITEM_CATALOG["treadmill"] == (150, 250)

    def test_home_gym_price(self):
        assert ITEM_CATALOG["home_gym"] == (200, 350)

    def test_both_are_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "treadmill" in heavy
        assert "home_gym" in heavy


# ===================================================================
# Catalog Restructuring v3.0: New heavy items
# ===================================================================


class TestNewHeavyItems:
    """Verify piano_upright, safe_small, safe_large, marble_table."""

    def test_pianino(self):
        items = extract_items("пианино")
        assert {i["key"]: i["qty"] for i in items}.get("piano_upright") == 1

    def test_royal(self):
        items = extract_items("рояль")
        assert {i["key"]: i["qty"] for i in items}.get("piano_upright") == 1

    def test_piano_price(self):
        assert ITEM_CATALOG["piano_upright"] == (500, 800)

    def test_seyf(self):
        items = extract_items("сейф")
        assert {i["key"]: i["qty"] for i in items}.get("safe_small") == 1

    def test_bolshoy_seyf(self):
        items = extract_items("большой сейф")
        assert {i["key"]: i["qty"] for i in items}.get("safe_large") == 1

    def test_safe_small_price(self):
        assert ITEM_CATALOG["safe_small"] == (200, 350)

    def test_safe_large_price(self):
        assert ITEM_CATALOG["safe_large"] == (350, 600)

    def test_mramorny_stol(self):
        items = extract_items("мраморный стол")
        assert {i["key"]: i["qty"] for i in items}.get("marble_table") == 1

    def test_marble_table_price(self):
        assert ITEM_CATALOG["marble_table"] == (250, 400)

    def test_all_are_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "piano_upright" in heavy
        assert "safe_small" in heavy
        assert "safe_large" in heavy
        assert "marble_table" in heavy

    def test_heavy_labels(self):
        assert ITEM_LABELS["piano_upright"]["ru"] == "Пианино"
        assert ITEM_LABELS["safe_small"]["ru"] == "Сейф"
        assert ITEM_LABELS["safe_large"]["ru"] == "Сейф большой"
        assert ITEM_LABELS["marble_table"]["ru"] == "Мраморный стол"


# ===================================================================
# Catalog Restructuring v3.0: Aquarium
# ===================================================================


class TestAquariumItem:
    """Verify aquarium_large extraction."""

    def test_akvarium(self):
        items = extract_items("аквариум")
        assert {i["key"]: i["qty"] for i in items}.get("aquarium_large") == 1

    def test_aquarium_en(self):
        items = extract_items("aquarium")
        assert {i["key"]: i["qty"] for i in items}.get("aquarium_large") == 1

    def test_aquarium_price(self):
        assert ITEM_CATALOG["aquarium_large"] == (200, 350)

    def test_aquarium_is_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "aquarium_large" in heavy

    def test_aquarium_label(self):
        assert ITEM_LABELS["aquarium_large"]["ru"] == "Аквариум"


# ===================================================================
# Catalog Restructuring v3.0: Kitchen items
# ===================================================================


class TestKitchenItems:
    """Verify dishwasher, microwave, coffee_machine, kettle, mixer, juicer, kitchenware."""

    def test_posudomoyka(self):
        items = extract_items("посудомойка")
        assert {i["key"]: i["qty"] for i in items}.get("dishwasher") == 1

    def test_posudomoechnaya_mashina(self):
        items = extract_items("посудомоечная машина")
        assert {i["key"]: i["qty"] for i in items}.get("dishwasher") == 1

    def test_dishwasher_price(self):
        assert ITEM_CATALOG["dishwasher"] == (180, 250)

    def test_dishwasher_is_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "dishwasher" in heavy

    def test_mikrovolnovka(self):
        items = extract_items("микроволновка")
        assert {i["key"]: i["qty"] for i in items}.get("microwave") == 1

    def test_svch(self):
        items = extract_items("свч")
        assert {i["key"]: i["qty"] for i in items}.get("microwave") == 1

    def test_microwave_price(self):
        assert ITEM_CATALOG["microwave"] == (30, 60)

    def test_kofemashina(self):
        items = extract_items("кофемашина")
        assert {i["key"]: i["qty"] for i in items}.get("coffee_machine") == 1

    def test_coffee_machine_price(self):
        assert ITEM_CATALOG["coffee_machine"] == (30, 60)

    def test_chaynik(self):
        items = extract_items("чайник")
        assert {i["key"]: i["qty"] for i in items}.get("kettle") == 1

    def test_kettle_price(self):
        assert ITEM_CATALOG["kettle"] == (10, 20)

    def test_mikser(self):
        items = extract_items("миксер")
        assert {i["key"]: i["qty"] for i in items}.get("mixer") == 1

    def test_blender(self):
        items = extract_items("блендер")
        assert {i["key"]: i["qty"] for i in items}.get("mixer") == 1

    def test_mixer_price(self):
        assert ITEM_CATALOG["mixer"] == (15, 30)

    def test_sokovyzhimalka(self):
        items = extract_items("соковыжималка")
        assert {i["key"]: i["qty"] for i in items}.get("juicer") == 1

    def test_juicer_price(self):
        assert ITEM_CATALOG["juicer"] == (20, 40)

    def test_posuda(self):
        items = extract_items("посуда")
        assert {i["key"]: i["qty"] for i in items}.get("kitchenware") == 1

    def test_kastryuli(self):
        items = extract_items("кастрюли")
        assert {i["key"]: i["qty"] for i in items}.get("kitchenware") == 1

    def test_kitchenware_price(self):
        assert ITEM_CATALOG["kitchenware"] == (40, 80)

    def test_kitchen_not_heavy(self):
        """Microwave, coffee machine, kettle, mixer, juicer, kitchenware are NOT heavy."""
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "microwave" not in heavy
        assert "coffee_machine" not in heavy
        assert "kettle" not in heavy
        assert "mixer" not in heavy
        assert "juicer" not in heavy
        assert "kitchenware" not in heavy

    def test_kitchen_labels(self):
        assert ITEM_LABELS["dishwasher"]["ru"] == "Посудомойка"
        assert ITEM_LABELS["microwave"]["ru"] == "Микроволновка"
        assert ITEM_LABELS["coffee_machine"]["ru"] == "Кофемашина"
        assert ITEM_LABELS["kettle"]["ru"] == "Чайник"
        assert ITEM_LABELS["mixer"]["ru"] == "Миксер"
        assert ITEM_LABELS["juicer"]["ru"] == "Соковыжималка"
        assert ITEM_LABELS["kitchenware"]["ru"] == "Посуда/утварь"


# ===================================================================
# Catalog Restructuring v3.0: TV stand
# ===================================================================


class TestTvStand:
    """Verify tv_stand extraction."""

    def test_tumba_pod_televizor(self):
        """'тумба под телевизор' → tv_stand (not tv_monitor)."""
        items = extract_items("тумба под телевизор")
        found = {i["key"]: i["qty"] for i in items}
        assert found.get("tv_stand") == 1
        assert "tv_monitor" not in found

    def test_podstavka_pod_televizor(self):
        items = extract_items("подставка под телевизор")
        assert {i["key"]: i["qty"] for i in items}.get("tv_stand") == 1

    def test_tv_stand_en(self):
        items = extract_items("tv stand")
        assert {i["key"]: i["qty"] for i in items}.get("tv_stand") == 1

    def test_tv_stand_price(self):
        assert ITEM_CATALOG["tv_stand"] == (60, 120)

    def test_tv_stand_not_heavy(self):
        heavy = set(VOLUME_FROM_ITEMS_CONFIG.get("heavy_keys", []))
        assert "tv_stand" not in heavy

    def test_tv_stand_label(self):
        assert ITEM_LABELS["tv_stand"]["ru"] == "Тумба под ТВ"
        assert ITEM_LABELS["tv_stand"]["en"] == "TV stand"

    def test_televizor_still_tv_monitor(self):
        """'телевизор' still maps to tv_monitor (no regression)."""
        items = extract_items("телевизор")
        assert {i["key"]: i["qty"] for i in items}.get("tv_monitor") == 1
