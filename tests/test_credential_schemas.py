# tests/test_credential_schemas.py
"""Tests for provider-specific credential/config validation schemas."""
import pytest

from app.infra.credential_schemas import (
    validate_credentials,
    validate_config,
    validate_channel_payload,
    CredentialValidationError,
)


# ---------------------------------------------------------------------------
# validate_credentials
# ---------------------------------------------------------------------------

class TestValidateCredentials:
    """Test credential validation per provider."""

    def test_meta_valid(self):
        errors = validate_credentials("meta", {"access_token": "tok123"})
        assert errors == []

    def test_meta_with_optional(self):
        errors = validate_credentials("meta", {
            "access_token": "tok", "app_secret": "sec"
        })
        assert errors == []

    def test_meta_missing_required(self):
        errors = validate_credentials("meta", {"app_secret": "sec"})
        assert any("access_token" in e for e in errors)

    def test_meta_unknown_key_rejected(self):
        errors = validate_credentials("meta", {
            "access_token": "tok", "rogue_field": "bad"
        })
        assert any("Unknown credential keys" in e for e in errors)

    def test_telegram_valid(self):
        errors = validate_credentials("telegram", {"bot_token": "123:ABC"})
        assert errors == []

    def test_telegram_missing_required(self):
        errors = validate_credentials("telegram", {})
        assert any("bot_token" in e for e in errors)

    def test_twilio_valid(self):
        errors = validate_credentials("twilio", {
            "account_sid": "AC123", "auth_token": "tok"
        })
        assert errors == []

    def test_twilio_missing_one_required(self):
        errors = validate_credentials("twilio", {"account_sid": "AC123"})
        assert any("auth_token" in e for e in errors)

    def test_unknown_provider(self):
        errors = validate_credentials("discord", {"token": "x"})
        assert any("Unknown provider" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

class TestValidateConfig:
    """Test config validation per provider."""

    def test_meta_valid(self):
        errors = validate_config("meta", {"phone_number_id": "123"})
        assert errors == []

    def test_meta_with_optional(self):
        errors = validate_config("meta", {
            "phone_number_id": "123",
            "graph_api_version": "v20.0",
            "webhook_verify_token": "vt",
        })
        assert errors == []

    def test_meta_missing_required(self):
        errors = validate_config("meta", {})
        assert any("phone_number_id" in e for e in errors)

    def test_meta_unknown_config_key(self):
        errors = validate_config("meta", {
            "phone_number_id": "123", "rogue": "bad"
        })
        assert any("Unknown config keys" in e for e in errors)

    def test_secret_in_config_rejected(self):
        """Detect secret fields accidentally placed in config."""
        errors = validate_config("meta", {
            "phone_number_id": "123",
            "access_token": "LEAKED_SECRET",
        })
        assert any("Secret fields must be in 'credentials'" in e for e in errors)

    def test_telegram_empty_config_ok(self):
        """Telegram has no required config fields."""
        errors = validate_config("telegram", {})
        assert errors == []

    def test_twilio_empty_config_ok(self):
        errors = validate_config("twilio", {})
        assert errors == []


# ---------------------------------------------------------------------------
# validate_channel_payload (integration)
# ---------------------------------------------------------------------------

class TestValidateChannelPayload:
    """Test combined credential + config validation."""

    def test_valid_meta_payload(self):
        """Valid Meta payload should not raise."""
        validate_channel_payload(
            "meta",
            {"access_token": "tok", "app_secret": "sec"},
            {"phone_number_id": "123", "webhook_verify_token": "vt"},
        )

    def test_valid_telegram_payload(self):
        validate_channel_payload(
            "telegram",
            {"bot_token": "123:ABC"},
            {"channel_mode": "webhook"},
        )

    def test_valid_twilio_payload(self):
        validate_channel_payload(
            "twilio",
            {"account_sid": "AC1", "auth_token": "tok"},
            {"phone_number": "+1234"},
        )

    def test_invalid_raises_with_all_errors(self):
        """Multiple errors should be accumulated and reported."""
        with pytest.raises(CredentialValidationError) as exc_info:
            validate_channel_payload(
                "meta",
                {},  # missing access_token
                {"access_token": "leaked"},  # secret in config + missing phone_number_id
            )
        msg = str(exc_info.value)
        assert "access_token" in msg
        assert "phone_number_id" in msg
        assert "Secret fields" in msg
