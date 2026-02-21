# tests/test_tenant_repo.py
"""Tests for AsyncPostgresTenantRepository (v0.8 refactored)."""
import pytest
from dataclasses import asdict

from app.infra.pg_tenant_repo_async import (
    TenantDTO,
    ChannelBindingDTO,
    _redact_config,
    _parse_jsonb,
    _SAFE_TENANT_CONFIG_KEYS,
    _SAFE_CHANNEL_CONFIG_KEYS,
)
from app.infra.credential_schemas import extract_provider_account_id


# ---------------------------------------------------------------------------
# DTO tests
# ---------------------------------------------------------------------------

class TestTenantDTO:
    """Test TenantDTO creation."""

    def test_basic_creation(self):
        dto = TenantDTO(id="t1", display_name="Test", is_active=True, config={})
        assert dto.id == "t1"
        assert dto.is_active is True

    def test_with_timestamps(self):
        dto = TenantDTO(
            id="t1", display_name="T", is_active=True, config={},
            created_at="2024-01-01T00:00:00", updated_at="2024-01-02T00:00:00",
        )
        assert dto.created_at == "2024-01-01T00:00:00"


class TestChannelBindingDTO:
    """Test ChannelBindingDTO creation."""

    def test_basic_creation(self):
        dto = ChannelBindingDTO(
            id="uuid", tenant_id="t1", provider="meta",
            provider_account_id="123456",
            config={"phone_number_id": "123456"},
            credentials_configured=True, is_active=True,
        )
        assert dto.provider == "meta"
        assert dto.provider_account_id == "123456"
        assert dto.credentials_configured is True


# ---------------------------------------------------------------------------
# Config redaction tests
# ---------------------------------------------------------------------------

class TestRedactConfig:
    """Test _redact_config allow-listing."""

    def test_only_allowed_keys_pass(self):
        config = {"quota": 100, "secret_stuff": "bad", "language": "en"}
        result = _redact_config(config, _SAFE_TENANT_CONFIG_KEYS)
        assert result == {"quota": 100, "language": "en"}
        assert "secret_stuff" not in result

    def test_empty_config(self):
        result = _redact_config({}, _SAFE_TENANT_CONFIG_KEYS)
        assert result == {}

    def test_meta_channel_config_redaction(self):
        config = {
            "phone_number_id": "123",
            "waba_id": "w1",
            "webhook_verify_token": "should_be_stripped",
        }
        safe_keys = _SAFE_CHANNEL_CONFIG_KEYS["meta"]
        result = _redact_config(config, safe_keys)
        assert "phone_number_id" in result
        assert "waba_id" in result
        assert "webhook_verify_token" not in result

    def test_telegram_channel_config_redaction(self):
        config = {"channel_mode": "webhook", "rogue_key": "x"}
        safe_keys = _SAFE_CHANNEL_CONFIG_KEYS["telegram"]
        result = _redact_config(config, safe_keys)
        assert result == {"channel_mode": "webhook"}

    def test_twilio_channel_config_redaction(self):
        config = {"phone_number": "+1234", "webhook_url": "https://x.com"}
        safe_keys = _SAFE_CHANNEL_CONFIG_KEYS["twilio"]
        result = _redact_config(config, safe_keys)
        assert result == {"phone_number": "+1234"}


# ---------------------------------------------------------------------------
# parse_jsonb tests
# ---------------------------------------------------------------------------

class TestParseJsonb:
    """Test _parse_jsonb helper."""

    def test_dict_passthrough(self):
        assert _parse_jsonb({"a": 1}) == {"a": 1}

    def test_str_parsed(self):
        assert _parse_jsonb('{"b": 2}') == {"b": 2}

    def test_none_returns_empty(self):
        assert _parse_jsonb(None) == {}

    def test_other_returns_empty(self):
        assert _parse_jsonb(42) == {}


# ---------------------------------------------------------------------------
# extract_provider_account_id tests
# ---------------------------------------------------------------------------

class TestExtractProviderAccountId:
    """Test provider_account_id extraction."""

    def test_meta_from_config(self):
        result = extract_provider_account_id(
            "meta",
            {"access_token": "tok"},
            {"phone_number_id": "12345"},
        )
        assert result == "12345"

    def test_telegram_from_credentials_prefix(self):
        result = extract_provider_account_id(
            "telegram",
            {"bot_token": "123456:ABCdefGHIjklMNOpqr"},
            {},
        )
        assert result == "123456"

    def test_twilio_from_config(self):
        result = extract_provider_account_id(
            "twilio",
            {"account_sid": "AC1", "auth_token": "tok"},
            {"phone_number": "+14155551234"},
        )
        assert result == "+14155551234"

    def test_missing_key_returns_empty(self):
        result = extract_provider_account_id("meta", {}, {})
        assert result == ""

    def test_unknown_provider_returns_empty(self):
        result = extract_provider_account_id("discord", {}, {})
        assert result == ""
