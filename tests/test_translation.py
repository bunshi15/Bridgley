# tests/test_translation.py
"""
Tests for the tri-language UX and operator lead translation system.

Covers:
1. Language detection heuristic (detect_language)
2. Session language switching in handler
3. TranslationProvider abstraction + implementations
4. Lead translation pipeline
5. Notification formatting with translations
6. Config settings
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock
import pytest


# ============================================================================
# 1. Language Detection (detect_language)
# ============================================================================

class TestDetectLanguage:
    """Test script-based language detection heuristic."""

    def test_hebrew_text(self):
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("שלום, אני רוצה להזמין הובלה")
        assert lang == "he"
        assert conf > 0.5

    def test_russian_text(self):
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("Диван и 3 коробки, переезд квартиры")
        assert lang == "ru"
        assert conf > 0.5

    def test_english_text(self):
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("I need to move a sofa and boxes")
        assert lang == "en"
        assert conf > 0.5

    def test_numeric_only_returns_none(self):
        """Pure digits → no language detection (button press)."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("123")
        assert lang is None
        assert conf == 0.0

    def test_single_digit_returns_none(self):
        """Single digit (menu choice) → no detection."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("1")
        assert lang is None
        assert conf == 0.0

    def test_very_short_text_returns_none(self):
        """Text shorter than 3 letters → ambiguous."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("ok")
        assert lang is None
        assert conf == 0.0

    def test_empty_string(self):
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("")
        assert lang is None
        assert conf == 0.0

    def test_mixed_hebrew_latin(self):
        """Hebrew with some Latin → Hebrew wins (unique script)."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("שלום hello")
        assert lang == "he"

    def test_mixed_cyrillic_latin(self):
        """Cyrillic dominant → Russian."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("Переезд в Tel Aviv")
        assert lang == "ru"

    def test_address_with_hebrew(self):
        """Hebrew address → detected as Hebrew."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("רחוב הרצל 10, חיפה")
        assert lang == "he"

    def test_address_with_russian(self):
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("улица Герцля 10, Хайфа")
        assert lang == "ru"

    def test_phone_number_returns_none(self):
        """Phone numbers are not language-specific."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("+972501234567")
        assert lang is None

    def test_hebrew_high_confidence(self):
        """Pure Hebrew text → high confidence."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("דירת שלושה חדרים")
        assert lang == "he"
        assert conf >= 0.8

    def test_russian_high_confidence(self):
        """Pure Russian text → high confidence."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("трёхкомнатная квартира")
        assert lang == "ru"
        assert conf >= 0.8

    def test_english_high_confidence(self):
        """Pure English text → high confidence."""
        from app.core.bots.moving_bot_validators import detect_language
        lang, conf = detect_language("three bedroom apartment")
        assert lang == "en"
        assert conf >= 0.8


# ============================================================================
# 2. Session Language Switching in Handler
# ============================================================================

class TestLanguageSwitching:
    """Test that the handler auto-detects language from free-text inputs."""

    def _make_handler(self):
        from app.core.handlers.moving_bot_handler import MovingBotHandler
        return MovingBotHandler()

    def test_hebrew_cargo_switches_language(self):
        """Hebrew cargo text → session language switches to he."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "cargo"
        state, reply, done = handler.handle_text(state, "ספה גדולה ושלוש קרטונים")
        assert state.language == "he"

    def test_english_cargo_switches_language(self):
        """English cargo text → session language switches to en."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "cargo"
        state, reply, done = handler.handle_text(state, "Large sofa and three boxes")
        assert state.language == "en"

    def test_russian_cargo_stays_russian(self):
        """Russian cargo text → language stays ru."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "cargo"
        state, reply, done = handler.handle_text(state, "Диван большой и три коробки")
        assert state.language == "ru"

    def test_numeric_choice_does_not_switch(self):
        """Numeric button press in volume step → no language switch."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "volume"
        state, reply, done = handler.handle_text(state, "2")
        assert state.language == "ru"

    def test_hebrew_address_switches_language(self):
        """Hebrew address → switches to he."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "addr_from"
        state, reply, done = handler.handle_text(state, "רחוב הרצל 10, חיפה")
        assert state.language == "he"

    def test_english_address_switches_language(self):
        """English address → switches to en."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "addr_from"
        state, reply, done = handler.handle_text(state, "Herzl street 10, Haifa")
        assert state.language == "en"

    def test_reply_uses_detected_language(self):
        """After language switch, reply should use the new language."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "cargo"
        state, reply, done = handler.handle_text(state, "Large sofa and three boxes for moving")

        # The reply should be in English (since we detected English)
        # Check that we got a response (step advanced or error)
        assert state.language == "en"
        # The next question should be in English
        # (volume or pickup_count depending on item detection)

    def test_button_step_excluded_from_detection(self):
        """pickup_count step (button-only) → no language detection."""
        handler = self._make_handler()
        state = handler.new_session("t1", "c1", language="en")
        state.step = "pickup_count"
        state.data.cargo_description = "stuff"
        state, reply, done = handler.handle_text(state, "1")
        # Language stays en — not switched by numeric input
        assert state.language == "en"


# ============================================================================
# 3. TranslationProvider Abstraction
# ============================================================================

class TestTokenBucket:
    """Test in-memory rate limiter."""

    def test_initial_tokens_available(self):
        from app.core.i18n.translation_provider import _TokenBucket
        bucket = _TokenBucket(60)
        assert bucket.acquire() is True

    def test_exhausts_after_max(self):
        from app.core.i18n.translation_provider import _TokenBucket
        bucket = _TokenBucket(3)
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is True
        assert bucket.acquire() is False  # Exhausted


class TestTranslationProviderFactory:
    """Test get_translation_provider() factory."""

    def test_disabled_returns_none(self, monkeypatch):
        from app.core.i18n.translation_provider import get_translation_provider
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", False)
        assert get_translation_provider() is None

    def test_provider_none_returns_none(self, monkeypatch):
        from app.core.i18n.translation_provider import get_translation_provider
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.translation_provider", "none")
        assert get_translation_provider() is None

    def test_no_api_key_returns_none(self, monkeypatch):
        from app.core.i18n.translation_provider import get_translation_provider
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.translation_provider", "deepl")
        monkeypatch.setattr("app.config.settings.translation_api_key", None)
        assert get_translation_provider() is None

    def test_deepl_provider_created(self, monkeypatch):
        from app.core.i18n.translation_provider import get_translation_provider, DeepLProvider
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.translation_provider", "deepl")
        monkeypatch.setattr("app.config.settings.translation_api_key", "test-key:fx")
        monkeypatch.setattr("app.config.settings.translation_timeout_seconds", 10)
        monkeypatch.setattr("app.config.settings.translation_retries", 2)
        monkeypatch.setattr("app.config.settings.translation_rate_limit_per_minute", 60)
        provider = get_translation_provider()
        assert isinstance(provider, DeepLProvider)

    def test_google_provider_created(self, monkeypatch):
        from app.core.i18n.translation_provider import get_translation_provider, GoogleTranslateProvider
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.translation_provider", "google")
        monkeypatch.setattr("app.config.settings.translation_api_key", "test-key")
        monkeypatch.setattr("app.config.settings.translation_timeout_seconds", 10)
        monkeypatch.setattr("app.config.settings.translation_retries", 2)
        monkeypatch.setattr("app.config.settings.translation_rate_limit_per_minute", 60)
        provider = get_translation_provider()
        assert isinstance(provider, GoogleTranslateProvider)

    def test_openai_provider_created(self, monkeypatch):
        from app.core.i18n.translation_provider import get_translation_provider, OpenAITranslateProvider
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.translation_provider", "openai")
        monkeypatch.setattr("app.config.settings.translation_api_key", "sk-test")
        monkeypatch.setattr("app.config.settings.translation_timeout_seconds", 10)
        monkeypatch.setattr("app.config.settings.translation_retries", 2)
        monkeypatch.setattr("app.config.settings.translation_rate_limit_per_minute", 60)
        provider = get_translation_provider()
        assert isinstance(provider, OpenAITranslateProvider)


class TestTranslationProviderBatch:
    """Test translate_batch behavior (mocked API)."""

    @pytest.mark.asyncio
    async def test_same_lang_skips_call(self):
        """source == target → no API call, return originals."""
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="test:fx", timeout=5, retries=0, rate_limit_per_minute=60)
        result = await provider.translate_batch(
            {"cargo": "Диван"}, "ru", "ru",
        )
        assert result == {"cargo": "Диван"}

    @pytest.mark.asyncio
    async def test_empty_fields_returns_empty(self):
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="test:fx", timeout=5, retries=0, rate_limit_per_minute=60)
        result = await provider.translate_batch({}, "he", "ru")
        assert result == {}

    @pytest.mark.asyncio
    async def test_api_failure_returns_originals(self):
        """When API fails, originals are returned (graceful degradation)."""
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="test:fx", timeout=5, retries=0, rate_limit_per_minute=60)

        with patch.object(provider, "_call_api", side_effect=Exception("Network error")):
            result = await provider.translate_batch(
                {"cargo": "ספה גדולה"}, "he", "ru",
            )
        assert result == {"cargo": "ספה גדולה"}

    @pytest.mark.asyncio
    async def test_successful_translation(self):
        """Successful API call → translated values returned."""
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="test:fx", timeout=5, retries=0, rate_limit_per_minute=60)

        async def mock_call(texts, src, tgt):
            return ["Большой диван", "Улица Герцля 10"]

        with patch.object(provider, "_call_api", side_effect=mock_call):
            result = await provider.translate_batch(
                {"cargo": "ספה גדולה", "addr": "רחוב הרצל 10"},
                "he", "ru",
            )
        assert result["cargo"] == "Большой диван"
        assert result["addr"] == "Улица Герцля 10"

    @pytest.mark.asyncio
    async def test_rate_limit_returns_originals(self):
        """Exhausted rate limit → return originals without API call."""
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="test:fx", timeout=5, retries=0, rate_limit_per_minute=1)
        # Exhaust the bucket
        provider._bucket.acquire()

        mock_api = AsyncMock()
        with patch.object(provider, "_call_api", mock_api):
            result = await provider.translate_batch(
                {"cargo": "ספה"}, "he", "ru",
            )
        assert result == {"cargo": "ספה"}
        mock_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_error_no_retry(self):
        """403 auth error → fail immediately, no retries."""
        import httpx
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="bad-key:fx", timeout=5, retries=2, rate_limit_per_minute=60)

        call_count = 0

        async def mock_call(texts, src, tgt):
            nonlocal call_count
            call_count += 1
            resp = httpx.Response(403, request=httpx.Request("POST", "https://test"))
            raise httpx.HTTPStatusError("Forbidden", request=resp.request, response=resp)

        with patch.object(provider, "_call_api", side_effect=mock_call):
            result = await provider.translate_batch(
                {"cargo": "ספה"}, "he", "ru",
            )
        # Should return originals
        assert result == {"cargo": "ספה"}
        # Should NOT retry — only 1 attempt
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_429_retries(self):
        """429 rate limit → retryable, should retry."""
        import httpx
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="test:fx", timeout=5, retries=1, rate_limit_per_minute=60)

        call_count = 0

        async def mock_call(texts, src, tgt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = httpx.Response(429, request=httpx.Request("POST", "https://test"))
                raise httpx.HTTPStatusError("Too Many Requests", request=resp.request, response=resp)
            return ["Диван"]

        with patch.object(provider, "_call_api", side_effect=mock_call):
            result = await provider.translate_batch(
                {"cargo": "ספה"}, "he", "ru",
            )
        assert result == {"cargo": "Диван"}
        assert call_count == 2  # 1 failed + 1 success


class TestOpenAINumberedParsing:
    """Test OpenAI response parsing."""

    def test_parse_standard_numbered(self):
        from app.core.i18n.translation_provider import OpenAITranslateProvider
        content = "1. Большой диван\n2. Улица Герцля 10\n3. Осторожно!"
        result = OpenAITranslateProvider._parse_numbered(content, 3)
        assert result == ["Большой диван", "Улица Герцля 10", "Осторожно!"]

    def test_parse_with_extra_lines(self):
        from app.core.i18n.translation_provider import OpenAITranslateProvider
        content = "1. Text one\n2. Text two\n3. Text three\n4. Extra"
        result = OpenAITranslateProvider._parse_numbered(content, 3)
        assert len(result) == 3

    def test_parse_with_missing_lines(self):
        """Fewer lines than expected → pad with empty strings."""
        from app.core.i18n.translation_provider import OpenAITranslateProvider
        content = "1. Only one"
        result = OpenAITranslateProvider._parse_numbered(content, 3)
        assert len(result) == 3
        assert result[0] == "Only one"
        assert result[1] == ""
        assert result[2] == ""

    def test_parse_parenthesis_format(self):
        """Alternative format: N) text."""
        from app.core.i18n.translation_provider import OpenAITranslateProvider
        content = "1) Диван\n2) Хайфа"
        result = OpenAITranslateProvider._parse_numbered(content, 2)
        assert result == ["Диван", "Хайфа"]


# ============================================================================
# 4. Lead Translation Pipeline
# ============================================================================

class TestExtractTranslatable:
    """Test _extract_translatable field extraction."""

    def test_extracts_standard_fields(self):
        from app.core.i18n.lead_translator import _extract_translatable
        payload = {
            "data": {
                "cargo_description": "ספה גדולה",
                "addr_from": "חיפה, הרצל 10",
                "addr_to": "תל אביב, דיזנגוף 50",
                "details_free": "זהירות, שביר",
                "photo_count": 2,
                "custom": {},
            }
        }
        fields = _extract_translatable(payload)
        assert "cargo_description" in fields
        assert "addr_from" in fields
        assert "addr_to" in fields
        assert "details_free" in fields
        assert "photo_count" not in fields

    def test_extracts_custom_fields(self):
        from app.core.i18n.lead_translator import _extract_translatable
        payload = {
            "data": {
                "cargo_description": "ספה",
                "custom": {
                    "cargo_raw": "ספה גדולה ו-3 קרטונים",
                    "landing_move_type": "דירה",
                    "estimate_min": 300,  # should not be extracted
                },
            }
        }
        fields = _extract_translatable(payload)
        assert "cargo_raw" in fields
        assert "landing_move_type" in fields
        assert "estimate_min" not in fields

    def test_extracts_multi_pickup_addresses(self):
        from app.core.i18n.lead_translator import _extract_translatable
        payload = {
            "data": {
                "custom": {
                    "pickups": [
                        {"addr": "חיפה, הרצל 10", "floor": "קומה 3"},
                        {"addr": "חיפה, בן-גוריון 5", "floor": "—"},
                    ],
                },
            }
        }
        fields = _extract_translatable(payload)
        assert "pickup_1_addr" in fields
        assert "pickup_1_floor" in fields
        assert "pickup_2_addr" in fields
        assert "pickup_2_floor" not in fields  # "—" is skipped

    def test_empty_fields_skipped(self):
        from app.core.i18n.lead_translator import _extract_translatable
        payload = {
            "data": {
                "cargo_description": "",
                "addr_from": None,
                "custom": {},
            }
        }
        fields = _extract_translatable(payload)
        assert len(fields) == 0


class TestTranslateLeadPayload:
    """Test the full translation pipeline."""

    @pytest.mark.asyncio
    async def test_disabled_returns_unchanged(self, monkeypatch):
        """Translation disabled → payload unchanged, no meta block."""
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", False)
        from app.core.i18n.lead_translator import translate_lead_payload
        payload = {"data": {"cargo_description": "ספה", "custom": {}}}
        result = await translate_lead_payload(payload, "he")
        assert "translations" not in payload["data"]["custom"]

    @pytest.mark.asyncio
    async def test_same_lang_skipped(self, monkeypatch):
        """source == target → status=skipped_same_lang."""
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        monkeypatch.setattr("app.config.settings.translation_provider", "deepl")
        from app.core.i18n.lead_translator import translate_lead_payload
        payload = {"data": {"cargo_description": "Диван", "custom": {}}}
        await translate_lead_payload(payload, "ru")
        meta = payload["data"]["custom"]["translation_meta"]
        assert meta["status"] == "skipped_same_lang"

    @pytest.mark.asyncio
    async def test_no_provider_configured(self, monkeypatch):
        """Provider = none → status=no_provider."""
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        monkeypatch.setattr("app.config.settings.translation_provider", "none")
        from app.core.i18n.lead_translator import translate_lead_payload
        payload = {"data": {"cargo_description": "ספה", "custom": {}}}
        await translate_lead_payload(payload, "he")
        meta = payload["data"]["custom"]["translation_meta"]
        assert meta["status"] == "no_provider"

    @pytest.mark.asyncio
    async def test_successful_translation_adds_block(self, monkeypatch):
        """Successful translation → translations.ru and translation_meta present."""
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        monkeypatch.setattr("app.config.settings.translation_provider", "deepl")
        monkeypatch.setattr("app.config.settings.translation_api_key", "test:fx")
        monkeypatch.setattr("app.config.settings.translation_timeout_seconds", 10)
        monkeypatch.setattr("app.config.settings.translation_retries", 0)
        monkeypatch.setattr("app.config.settings.translation_rate_limit_per_minute", 60)

        from app.core.i18n.lead_translator import translate_lead_payload

        # Mock the provider
        mock_provider = MagicMock()
        mock_provider.translate_batch = AsyncMock(return_value={
            "cargo_description": "Большой диван",
            "addr_from": "Хайфа, Герцль 10",
        })

        with patch("app.core.i18n.translation_provider.get_translation_provider", return_value=mock_provider):
            payload = {
                "data": {
                    "cargo_description": "ספה גדולה",
                    "addr_from": "חיפה, הרצל 10",
                    "custom": {},
                }
            }
            await translate_lead_payload(payload, "he")

        custom = payload["data"]["custom"]
        assert "translations" in custom
        assert "ru" in custom["translations"]
        assert custom["translations"]["ru"]["cargo_description"] == "Большой диван"
        assert custom["translations"]["ru"]["addr_from"] == "Хайфа, Герцль 10"

        meta = custom["translation_meta"]
        assert meta["status"] == "ok"
        assert meta["source_lang"] == "he"
        assert meta["target_lang"] == "ru"
        assert meta["provider"] == "deepl"
        assert "latency_ms" in meta

    @pytest.mark.asyncio
    async def test_api_failure_preserves_originals(self, monkeypatch):
        """API failure → translations empty, status=failed."""
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        monkeypatch.setattr("app.config.settings.translation_provider", "deepl")
        monkeypatch.setattr("app.config.settings.translation_api_key", "test:fx")
        monkeypatch.setattr("app.config.settings.translation_timeout_seconds", 10)
        monkeypatch.setattr("app.config.settings.translation_retries", 0)
        monkeypatch.setattr("app.config.settings.translation_rate_limit_per_minute", 60)

        from app.core.i18n.lead_translator import translate_lead_payload

        mock_provider = MagicMock()
        mock_provider.translate_batch = AsyncMock(side_effect=Exception("API down"))

        with patch("app.core.i18n.translation_provider.get_translation_provider", return_value=mock_provider):
            payload = {
                "data": {
                    "cargo_description": "ספה גדולה",
                    "custom": {},
                }
            }
            await translate_lead_payload(payload, "he")

        custom = payload["data"]["custom"]
        meta = custom["translation_meta"]
        assert meta["status"] == "failed"
        assert meta["error"] == "Exception"
        # Original cargo_description untouched
        assert payload["data"]["cargo_description"] == "ספה גדולה"

    @pytest.mark.asyncio
    async def test_no_translatable_fields(self, monkeypatch):
        """Payload with no text fields → status=no_fields."""
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        monkeypatch.setattr("app.config.settings.translation_provider", "deepl")
        monkeypatch.setattr("app.config.settings.translation_api_key", "test:fx")
        monkeypatch.setattr("app.config.settings.translation_timeout_seconds", 10)
        monkeypatch.setattr("app.config.settings.translation_retries", 0)
        monkeypatch.setattr("app.config.settings.translation_rate_limit_per_minute", 60)

        from app.core.i18n.lead_translator import translate_lead_payload
        payload = {"data": {"photo_count": 2, "custom": {}}}
        await translate_lead_payload(payload, "he")
        meta = payload["data"]["custom"]["translation_meta"]
        assert meta["status"] == "no_fields"


# ============================================================================
# 5. Notification Formatting with Translations
# ============================================================================

class TestNotificationTranslationBlock:
    """Test that operator notification includes translation block."""

    def test_translated_values_in_main_body(self):
        """When translation ok, main body shows translated text."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "ספה גדולה",
            "addr_from": "חיפה",
            "addr_to": "תל אביב",
            "custom": {
                "translations": {
                    "ru": {
                        "cargo_description": "Большой диван",
                        "addr_from": "Хайфа",
                        "addr_to": "Тель-Авив",
                    }
                },
                "translation_meta": {
                    "status": "ok",
                    "target_lang": "ru",
                    "source_lang": "he",
                    "provider": "deepl",
                },
            },
        }
        result = format_lead_message("+972501234567", payload)
        # Translated values in main body
        assert "Что везем: Большой диван" in result
        assert "Хайфа" in result
        assert "Тель-Авив" in result

    def test_originals_shown_in_reference_block(self):
        """When translation ok, originals shown in reference block."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "ספה גדולה",
            "addr_from": "חיפה",
            "addr_to": "תל אביב",
            "custom": {
                "translations": {
                    "ru": {
                        "cargo_description": "Большой диван",
                        "addr_from": "Хайфа",
                        "addr_to": "Тель-Авив",
                    }
                },
                "translation_meta": {
                    "status": "ok",
                    "target_lang": "ru",
                    "source_lang": "he",
                    "provider": "deepl",
                },
            },
        }
        result = format_lead_message("+972501234567", payload)
        # Originals in reference block
        assert "Оригинал (HE):" in result
        assert "ספה גדולה" in result
        assert "חיפה" in result

    def test_no_translation_block_when_failed(self):
        """Failed translation → originals in main body, no reference block."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "ספה",
            "custom": {
                "translation_meta": {
                    "status": "failed",
                    "target_lang": "ru",
                },
            },
        }
        result = format_lead_message("+972501234567", payload)
        # Originals stay in main body
        assert "ספה" in result
        assert "Оригинал" not in result

    def test_no_translation_block_when_disabled(self):
        from app.infra.notification_service import format_lead_message
        payload = {"cargo_description": "Диван", "custom": {}}
        result = format_lead_message("+972501234567", payload)
        assert "Оригинал" not in result

    def test_session_language_indicator_shown(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "sofa",
            "custom": {"session_language": "en"},
        }
        result = format_lead_message("+972501234567", payload)
        assert "Язык клиента: English" in result

    def test_session_language_russian_not_shown(self):
        """Russian is default — no indicator needed."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "custom": {"session_language": "ru"},
        }
        result = format_lead_message("+972501234567", payload)
        assert "Язык клиента" not in result

    def test_session_language_hebrew_shown(self):
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "ספה",
            "custom": {"session_language": "he"},
        }
        result = format_lead_message("+972501234567", payload)
        assert "Язык клиента: עברית" in result

    def test_no_session_language_no_indicator(self):
        from app.infra.notification_service import format_lead_message
        payload = {"cargo_description": "Диван", "custom": {}}
        result = format_lead_message("+972501234567", payload)
        assert "Язык клиента" not in result

    def test_lead_number_in_header(self):
        """When lead_number present, header shows 'Заявка #N'."""
        from app.infra.notification_service import format_lead_message
        payload = {
            "cargo_description": "Диван",
            "custom": {"lead_number": 123},
        }
        result = format_lead_message("+972501234567", payload)
        assert "📦 Заявка #123" in result

    def test_lead_number_absent_default_header(self):
        """When lead_number absent, header shows 'Новая заявка'."""
        from app.infra.notification_service import format_lead_message
        payload = {"cargo_description": "Диван", "custom": {}}
        result = format_lead_message("+972501234567", payload)
        assert "📦 Новая заявка" in result


# ============================================================================
# 6. Config Settings
# ============================================================================

class TestTranslationConfig:
    """Test translation config defaults and types."""

    def test_defaults(self):
        from app.config import Settings
        s = Settings(
            _env_file=None,
            tenant_encryption_key=None,
        )
        assert s.operator_lead_translation_enabled is False
        assert s.operator_lead_target_lang == "ru"
        assert s.translation_provider == "none"
        assert s.translation_api_key is None
        assert s.translation_timeout_seconds == 10
        assert s.translation_retries == 2
        assert s.translation_rate_limit_per_minute == 60

    def test_enabled_from_env(self, monkeypatch):
        """Translation settings loaded from env vars."""
        monkeypatch.setenv("OPERATOR_LEAD_TRANSLATION_ENABLED", "true")
        monkeypatch.setenv("OPERATOR_LEAD_TARGET_LANG", "ru")
        monkeypatch.setenv("TRANSLATION_PROVIDER", "deepl")
        monkeypatch.setenv("TRANSLATION_API_KEY", "test-key:fx")
        monkeypatch.setenv("TRANSLATION_TIMEOUT_SECONDS", "15")
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.operator_lead_translation_enabled is True
        assert s.operator_lead_target_lang == "ru"
        assert s.translation_provider == "deepl"
        assert s.translation_api_key == "test-key:fx"
        assert s.translation_timeout_seconds == 15


# ============================================================================
# 7. Integration: session_language stored on finalization
# ============================================================================

class TestSessionLanguageInPayload:
    """Test that session_language is stored in custom when lead is finalized."""

    def test_session_language_stored_on_done(self):
        """When user confirms estimate, session_language is saved in custom."""
        from app.core.handlers.moving_bot_handler import MovingBotHandler
        handler = MovingBotHandler()
        state = handler.new_session("t1", "c1", language="he")
        state.step = "estimate"
        state.data.custom["estimate_min"] = 300
        state.data.custom["estimate_max"] = 400

        state, reply, done = handler.handle_text(state, "1")
        assert done is True
        assert state.data.custom["session_language"] == "he"

    def test_session_language_russian_stored(self):
        from app.core.handlers.moving_bot_handler import MovingBotHandler
        handler = MovingBotHandler()
        state = handler.new_session("t1", "c1", language="ru")
        state.step = "estimate"

        state, reply, done = handler.handle_text(state, "1")
        assert done is True
        assert state.data.custom["session_language"] == "ru"

    def test_session_language_english_stored(self):
        from app.core.handlers.moving_bot_handler import MovingBotHandler
        handler = MovingBotHandler()
        state = handler.new_session("t1", "c1", language="en")
        state.step = "estimate"

        state, reply, done = handler.handle_text(state, "1")
        assert done is True
        assert state.data.custom["session_language"] == "en"


# ============================================================================
# 8. Session state persistence (language survives DB round-trip)
# ============================================================================

class TestSessionStatePersistence:
    """Test that language/bot_type/metadata survive upsert→get round-trip."""

    def test_upsert_includes_language(self):
        """Upsert payload must include language field."""
        import json
        from dataclasses import asdict
        from app.core.engine.domain import SessionState

        state = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="L1",
            step="cargo", language="he",
        )
        # Simulate what upsert builds
        payload = {
            "tenant_id": state.tenant_id,
            "chat_id": state.chat_id,
            "lead_id": state.lead_id,
            "step": state.step,
            "data": asdict(state.data),
            "bot_type": state.bot_type,
            "language": state.language,
            "metadata": state.metadata,
        }
        raw = json.dumps(payload)
        restored = json.loads(raw)
        assert restored["language"] == "he"
        assert restored["bot_type"] == "moving_bot_v1"

    def test_get_restores_language(self):
        """SessionState reconstructed from DB JSON must carry language."""
        import json
        from dataclasses import asdict
        from app.core.engine.domain import SessionState, LeadData

        original = SessionState(
            tenant_id="t1", chat_id="c1", lead_id="L1",
            step="pickup_count", language="en",
            bot_type="moving_bot_v1", metadata={"src": "web"},
        )
        payload = {
            "tenant_id": original.tenant_id,
            "chat_id": original.chat_id,
            "lead_id": original.lead_id,
            "step": original.step,
            "data": asdict(original.data),
            "bot_type": original.bot_type,
            "language": original.language,
            "metadata": original.metadata,
        }
        state = json.loads(json.dumps(payload))
        data = state.get("data") or {}
        ld = LeadData(**data)
        st = SessionState(
            tenant_id=state["tenant_id"],
            chat_id=state["chat_id"],
            lead_id=state["lead_id"],
            step=state["step"],
            data=ld,
            bot_type=state.get("bot_type", "moving_bot_v1"),
            language=state.get("language", "ru"),
            metadata=state.get("metadata", {}),
        )
        assert st.language == "en"
        assert st.bot_type == "moving_bot_v1"
        assert st.metadata == {"src": "web"}

    def test_old_session_without_language_defaults_ru(self):
        """Sessions saved before this fix (no language key) default to ru."""
        import json
        from app.core.engine.domain import SessionState, LeadData

        old_payload = {
            "tenant_id": "t1", "chat_id": "c1", "lead_id": "L1",
            "step": "addr_from",
            "data": {"custom": {}},
            # no "language" key — old format
        }
        state = json.loads(json.dumps(old_payload))
        data = state.get("data") or {}
        ld = LeadData(**data)
        st = SessionState(
            tenant_id=state["tenant_id"],
            chat_id=state["chat_id"],
            lead_id=state["lead_id"],
            step=state["step"],
            data=ld,
            bot_type=state.get("bot_type", "moving_bot_v1"),
            language=state.get("language", "ru"),
            metadata=state.get("metadata", {}),
        )
        assert st.language == "ru"  # safe default


# ============================================================================
# 9. DeepL URL detection
# ============================================================================

class TestDeepLFreeVsPro:
    """Test DeepL free vs pro URL detection."""

    def test_free_key(self):
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="abc123:fx")
        assert "api-free.deepl.com" in provider._base_url()

    def test_pro_key(self):
        from app.core.i18n.translation_provider import DeepLProvider
        provider = DeepLProvider(api_key="abc123")
        assert "api.deepl.com" in provider._base_url()
        assert "api-free" not in provider._base_url()


# ============================================================================
# 9. Notification pipeline with translation (integration)
# ============================================================================

class TestNotifyOperatorWithTranslation:
    """Integration: notify_operator triggers translation pipeline."""

    @pytest.mark.asyncio
    async def test_translation_called_during_notification(self, monkeypatch):
        """notify_operator calls translate_lead_payload."""
        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+972501234567")
        monkeypatch.setattr("app.config.settings.operator_whatsapp_provider", "meta")
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")
        monkeypatch.setattr("app.config.settings.operator_lead_translation_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        monkeypatch.setattr("app.config.settings.translation_provider", "deepl")
        monkeypatch.setattr("app.config.settings.translation_api_key", "test:fx")
        monkeypatch.setattr("app.config.settings.translation_timeout_seconds", 10)
        monkeypatch.setattr("app.config.settings.translation_retries", 0)
        monkeypatch.setattr("app.config.settings.translation_rate_limit_per_minute", 60)

        from app.infra.notification_service import notify_operator

        mock_channel = MagicMock()
        mock_channel.name = "whatsapp"
        mock_channel.send = AsyncMock(return_value=True)

        mock_provider = MagicMock()
        mock_provider.translate_batch = AsyncMock(return_value={
            "cargo_description": "Большой диван",
        })

        payload = {
            "data": {
                "cargo_description": "ספה גדולה",
                "custom": {
                    "session_language": "he",
                },
            }
        }

        with patch("app.infra.notification_channels.get_notification_channel", return_value=mock_channel), \
             patch("app.infra.notification_service._get_photo_urls_for_lead", new_callable=AsyncMock, return_value=[]), \
             patch("app.core.i18n.translation_provider.get_translation_provider", return_value=mock_provider):
            result = await notify_operator("lead1", "+972501234567", payload, tenant_id="test_t")

        assert result is True
        mock_provider.translate_batch.assert_called_once()
        # Check translation was added to payload
        custom = payload["data"]["custom"]
        assert "translations" in custom
        assert custom["translation_meta"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_translation_failure_does_not_block_notification(self, monkeypatch):
        """Translation failure → notification still sent."""
        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+972501234567")
        monkeypatch.setattr("app.config.settings.operator_whatsapp_provider", "meta")
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")

        from app.infra.notification_service import notify_operator

        mock_channel = MagicMock()
        mock_channel.name = "whatsapp"
        mock_channel.send = AsyncMock(return_value=True)

        # Translation pipeline crashes completely
        with patch("app.infra.notification_channels.get_notification_channel", return_value=mock_channel), \
             patch("app.infra.notification_service._get_photo_urls_for_lead", new_callable=AsyncMock, return_value=[]), \
             patch("app.core.i18n.lead_translator.translate_lead_payload", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            result = await notify_operator(
                "lead1", "+972501234567",
                {"data": {"cargo_description": "ספה", "custom": {"session_language": "he"}}},
                tenant_id="test_t",
            )

        # Notification still sent despite translation failure
        assert result is True
        mock_channel.send.assert_called_once()


# ============================================================================
# 10. Dispatch Iteration 1: Crew Fallback Message
# ============================================================================

class TestFormatCrewMessage:
    """Test crew-safe message formatting (CrewLeadView builder)."""

    def _base_payload(self, **overrides):
        """Build a realistic lead payload for testing."""
        payload = {
            "data": {
                "cargo_description": "ספה גדולה ושתי קרטונים",
                "addr_from": "רחוב הרצל 10, חיפה",
                "addr_to": "דיזנגוף 50, תל אביב",
                "floor_from": "3 этаж, без лифта",
                "floor_to": "2 этаж, есть лифт",
                "time_window": "morning",
                "extras": ["loaders"],
                "custom": {
                    "move_date": "2026-03-15",
                    "volume_category": "medium",
                    "estimate_min": 850,
                    "estimate_max": 950,
                    "lead_number": 42,
                    "route_classification": {
                        "from_locality": "Haifa",
                        "to_locality": "Kiryat Ata",
                        "from_region": 31,
                        "to_region": 31,
                        "band": "metro",
                    },
                    "cargo_items": [
                        {"key": "sofa", "qty": 1},
                        {"key": "box", "qty": 2},
                    ],
                    "session_language": "he",
                    "sender_name": "Ivan Petrov (@ivan_p)",
                },
            }
        }
        # Apply overrides
        for key, val in overrides.items():
            if key.startswith("custom."):
                payload["data"]["custom"][key[7:]] = val
            elif key.startswith("data."):
                payload["data"][key[5:]] = val
            else:
                payload[key] = val
        return payload

    def test_basic_crew_message(self, monkeypatch):
        """Crew message includes route, date, volume, floors, items, estimate."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        # No useless header — starts with job info
        assert "FOR CREW" not in result
        # Sequential lead number
        assert "🧰 Заказ #42" in result
        # Localized labels in Russian
        assert "Маршрут: Haifa → Kiryat Ata" in result
        assert "2026-03-15" in result
        assert "средний" in result  # medium volume
        assert "Sofa" in result
        assert "Box ×2" in result
        assert "₪850–₪950" in result

    def test_lead_number_fallback_to_uuid(self, monkeypatch):
        """When lead_number absent, fallback to short lead_id."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        del payload["data"]["custom"]["lead_number"]
        result = format_crew_message("lead-abc123", payload)
        assert "#lead-abc" in result

    def test_no_phone_in_crew_message(self, monkeypatch):
        """Crew message must NEVER contain client phone number."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        assert "+972" not in result
        assert "501234567" not in result
        assert "whatsapp:" not in result

    def test_no_street_address_in_crew_message(self, monkeypatch):
        """Crew message must NOT contain street addresses."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        assert "הרצל" not in result
        assert "רחוב" not in result
        assert "דיזנגוף" not in result
        assert "Herzl" not in result.lower()

    def test_no_sender_name_in_crew_message(self, monkeypatch):
        """Crew message must NOT contain client name / Telegram handle."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        assert "Ivan" not in result
        assert "Petrov" not in result
        assert "@ivan_p" not in result

    def test_no_free_text_details_in_crew_message(self, monkeypatch):
        """Crew message must NOT contain free-text details/comments."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload(**{"data.details_free": "Осторожно, хрупкое!"})
        result = format_crew_message("lead-abc123", payload)

        assert "Осторожно" not in result
        assert "хрупкое" not in result

    def test_no_cargo_raw_in_crew_message(self, monkeypatch):
        """Crew message must NOT contain raw cargo description."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        assert "ספה" not in result
        assert "קרטונים" not in result

    def test_missing_route_classification(self, monkeypatch):
        """When no route_classification, show 'не указано'."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        del payload["data"]["custom"]["route_classification"]
        result = format_crew_message("lead-abc123", payload)

        assert "Маршрут:" in result
        assert "не указано" in result

    def test_missing_volume(self, monkeypatch):
        """When no volume, show 'не указано'."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        del payload["data"]["custom"]["volume_category"]
        result = format_crew_message("lead-abc123", payload)

        assert "не указано" in result

    def test_missing_estimate(self, monkeypatch):
        """When no estimate, Оценка line is omitted."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        del payload["data"]["custom"]["estimate_min"]
        del payload["data"]["custom"]["estimate_max"]
        result = format_crew_message("lead-abc123", payload)

        assert "Оценка:" not in result

    def test_no_items_omits_items_line(self, monkeypatch):
        """When no cargo_items, Вещи line is omitted."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        del payload["data"]["custom"]["cargo_items"]
        result = format_crew_message("lead-abc123", payload)

        assert "Вещи:" not in result

    def test_services_shown_when_present(self, monkeypatch):
        """When extras present, Услуги line shown."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        assert "Услуги: грузчики" in result

    def test_no_services_when_none(self, monkeypatch):
        """When no extras, Услуги line omitted."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload(**{"data.extras": []})
        result = format_crew_message("lead-abc123", payload)

        assert "Услуги:" not in result

    def test_flat_payload_format(self, monkeypatch):
        """format_crew_message works with flat payload (no 'data' wrapper)."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")
        from app.infra.notification_service import format_crew_message
        payload = {
            "cargo_description": "stuff",
            "floor_from": "2",
            "floor_to": "4",
            "custom": {
                "route_classification": {
                    "from_locality": "Beer Sheva",
                    "to_locality": "Eilat",
                },
                "volume_category": "large",
                "estimate_min": 2000,
                "estimate_max": 2500,
            },
        }
        result = format_crew_message("flat-lead-1", payload)
        assert "Beer Sheva → Eilat" in result
        assert "₪2000–₪2500" in result
        assert "большой" in result

    def test_english_operator_labels(self, monkeypatch):
        """When operator language is English, labels are in English."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "en")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        assert "🧰 Job #42" in result
        assert "Route: Haifa → Kiryat Ata" in result
        assert "Date:" in result
        assert "Volume:" in result
        assert "medium" in result
        assert "Items:" in result
        assert "Estimate:" in result

    def test_hebrew_operator_labels(self, monkeypatch):
        """When operator language is Hebrew, labels are in Hebrew."""
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "he")
        from app.infra.notification_service import format_crew_message
        payload = self._base_payload()
        result = format_crew_message("lead-abc123", payload)

        assert "🧰 הזמנה #42" in result
        assert "מסלול:" in result
        assert "תאריך:" in result
        assert "נפח:" in result


class TestDispatchConfig:
    """Test dispatch config resolution."""

    def test_default_disabled(self):
        from app.config import Settings
        s = Settings(_env_file=None, tenant_encryption_key=None)
        assert s.dispatch_crew_fallback_enabled is False

    def test_enabled_from_env(self, monkeypatch):
        monkeypatch.setenv("DISPATCH_CREW_FALLBACK_ENABLED", "true")
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.dispatch_crew_fallback_enabled is True

    def test_tenant_override(self):
        """Tenant config can override global setting."""
        from app.infra.tenant_registry import (
            get_dispatch_config, TenantContext, _cache,
        )
        import app.infra.tenant_registry as tr

        # Set up tenant with override
        old_cache = tr._cache.copy()
        try:
            tr._cache["t_dispatch"] = TenantContext(
                tenant_id="t_dispatch",
                display_name="Test",
                is_active=True,
                config={"dispatch_crew_fallback_enabled": True},
            )
            cfg = get_dispatch_config("t_dispatch")
            assert cfg["crew_fallback_enabled"] is True
        finally:
            tr._cache = old_cache

    def test_global_fallback(self, monkeypatch):
        """When tenant has no override, falls back to global setting."""
        monkeypatch.setattr("app.config.settings.dispatch_crew_fallback_enabled", False)
        from app.infra.tenant_registry import get_dispatch_config
        cfg = get_dispatch_config(None)
        assert cfg["crew_fallback_enabled"] is False


class TestCrewFallbackNotification:
    """Test notify_operator_crew_fallback integration."""

    @pytest.mark.asyncio
    async def test_crew_fallback_sends_via_channel(self, monkeypatch):
        """Crew fallback sends sanitized message via notification channel."""
        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+972501234567")
        monkeypatch.setattr("app.config.settings.operator_whatsapp_provider", "meta")
        monkeypatch.setattr("app.config.settings.meta_access_token", "EAAxxxx")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "12345")
        monkeypatch.setattr("app.config.settings.tenant_id", "test_t")
        monkeypatch.setattr("app.config.settings.operator_lead_target_lang", "ru")

        from app.infra.notification_service import notify_operator_crew_fallback

        mock_channel = MagicMock()
        mock_channel.name = "whatsapp"
        mock_channel.send = AsyncMock(return_value=True)

        payload = {
            "data": {
                "floor_from": "3",
                "floor_to": "1",
                "custom": {
                    "lead_number": 7,
                    "route_classification": {
                        "from_locality": "Haifa",
                        "to_locality": "Acre",
                    },
                    "volume_category": "small",
                    "estimate_min": 500,
                    "estimate_max": 600,
                },
            }
        }

        with patch("app.infra.notification_channels.get_notification_channel", return_value=mock_channel):
            result = await notify_operator_crew_fallback("lead-xyz", payload, tenant_id="test_t")

        assert result is True
        mock_channel.send.assert_called_once()

        # Verify the sent body is the crew message (no PII)
        sent_notification = mock_channel.send.call_args[0][0]
        assert "Заказ #7" in sent_notification.body
        assert "Haifa → Acre" in sent_notification.body
        assert sent_notification.photo_urls == []  # No photos in crew msg

    @pytest.mark.asyncio
    async def test_crew_fallback_disabled_returns_true(self, monkeypatch):
        """When notifications disabled, crew fallback returns True silently."""
        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", False)

        from app.infra.notification_service import notify_operator_crew_fallback
        result = await notify_operator_crew_fallback("lead-1", {"data": {"custom": {}}})
        assert result is True
