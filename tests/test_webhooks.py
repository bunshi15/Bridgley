# tests/test_webhooks.py
"""Tests for webhook signature validation in meta_webhook, telegram_webhook, twilio_webhook."""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ============================================================================
# Meta signature verification
# ============================================================================

class TestMetaSignatureVerification:
    """Tests for _verify_signature() in meta_webhook.py."""

    def _make_request(self, signature_header: str | None = None) -> MagicMock:
        request = MagicMock()
        request.headers = {}
        if signature_header is not None:
            request.headers["X-Hub-Signature-256"] = signature_header
        return request

    @patch("app.transport.meta_webhook.settings")
    def test_valid_signature(self, mock_settings):
        mock_settings.meta_app_secret = "test-secret"
        from app.transport.meta_webhook import _verify_signature

        body = b'{"test": "data"}'
        sig = hmac_mod.new(b"test-secret", body, hashlib.sha256).hexdigest()
        request = self._make_request(f"sha256={sig}")

        assert _verify_signature(request, body) is True

    @patch("app.transport.meta_webhook.settings")
    def test_invalid_signature(self, mock_settings):
        mock_settings.meta_app_secret = "test-secret"
        from app.transport.meta_webhook import _verify_signature

        body = b'{"test": "data"}'
        request = self._make_request("sha256=0000000000000000000000000000000000000000000000000000000000000000")

        assert _verify_signature(request, body) is False

    @patch("app.transport.meta_webhook.settings")
    def test_missing_signature_header(self, mock_settings):
        mock_settings.meta_app_secret = "test-secret"
        from app.transport.meta_webhook import _verify_signature

        request = self._make_request(None)
        assert _verify_signature(request, b"body") is False

    @patch("app.transport.meta_webhook.settings")
    def test_wrong_format(self, mock_settings):
        mock_settings.meta_app_secret = "test-secret"
        from app.transport.meta_webhook import _verify_signature

        request = self._make_request("md5=abc123")
        assert _verify_signature(request, b"body") is False

    @patch("app.transport.meta_webhook.settings")
    def test_no_secret_configured_skips(self, mock_settings):
        mock_settings.meta_app_secret = None
        from app.transport.meta_webhook import _verify_signature

        request = self._make_request(None)
        assert _verify_signature(request, b"body") is True


class TestMetaWebhookVerify:
    """Tests for meta_webhook_verify() GET handler."""

    @pytest.mark.asyncio
    @patch("app.transport.meta_webhook.settings")
    async def test_successful_verification(self, mock_settings):
        mock_settings.meta_webhook_verify_token = "my-verify-token"
        from app.transport.meta_webhook import meta_webhook_verify

        request = MagicMock()
        request.query_params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "my-verify-token",
            "hub.challenge": "challenge-value-123",
        }

        response = await meta_webhook_verify(request)
        assert response.status_code == 200
        assert response.body == b"challenge-value-123"

    @pytest.mark.asyncio
    @patch("app.transport.meta_webhook.settings")
    async def test_wrong_verify_token(self, mock_settings):
        mock_settings.meta_webhook_verify_token = "correct-token"
        from app.transport.meta_webhook import meta_webhook_verify
        from fastapi import HTTPException

        request = MagicMock()
        request.query_params = {
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "challenge-value",
        }

        with pytest.raises(HTTPException) as exc_info:
            await meta_webhook_verify(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch("app.transport.meta_webhook.settings")
    async def test_missing_params(self, mock_settings):
        mock_settings.meta_webhook_verify_token = "token"
        from app.transport.meta_webhook import meta_webhook_verify
        from fastapi import HTTPException

        request = MagicMock()
        request.query_params = {}

        with pytest.raises(HTTPException) as exc_info:
            await meta_webhook_verify(request)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    @patch("app.transport.meta_webhook.settings")
    async def test_wrong_mode(self, mock_settings):
        mock_settings.meta_webhook_verify_token = "token"
        from app.transport.meta_webhook import meta_webhook_verify
        from fastapi import HTTPException

        request = MagicMock()
        request.query_params = {
            "hub.mode": "unsubscribe",
            "hub.verify_token": "token",
            "hub.challenge": "c",
        }

        with pytest.raises(HTTPException) as exc_info:
            await meta_webhook_verify(request)
        assert exc_info.value.status_code == 403


# ============================================================================
# Telegram secret token verification
# ============================================================================

class TestTelegramSecretToken:
    """Tests for _verify_secret_token() in telegram_webhook.py."""

    @patch("app.transport.telegram_webhook.settings")
    def test_valid_secret_token(self, mock_settings):
        mock_settings.telegram_webhook_secret = "my-secret-abc"
        from app.transport.telegram_webhook import _verify_secret_token

        request = MagicMock()
        request.headers = {"X-Telegram-Bot-Api-Secret-Token": "my-secret-abc"}

        assert _verify_secret_token(request) is True

    @patch("app.transport.telegram_webhook.settings")
    def test_invalid_secret_token(self, mock_settings):
        mock_settings.telegram_webhook_secret = "correct-secret"
        from app.transport.telegram_webhook import _verify_secret_token

        request = MagicMock()
        request.headers = {"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"}

        assert _verify_secret_token(request) is False

    @patch("app.transport.telegram_webhook.settings")
    def test_missing_header(self, mock_settings):
        mock_settings.telegram_webhook_secret = "my-secret"
        from app.transport.telegram_webhook import _verify_secret_token

        request = MagicMock()
        request.headers = {}

        assert _verify_secret_token(request) is False

    @patch("app.transport.telegram_webhook.settings")
    def test_no_secret_configured_skips(self, mock_settings):
        mock_settings.telegram_webhook_secret = None
        from app.transport.telegram_webhook import _verify_secret_token

        request = MagicMock()
        request.headers = {}

        assert _verify_secret_token(request) is True
