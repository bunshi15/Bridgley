# tests/test_security.py
"""Tests for app/transport/security.py — security utilities."""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to patch settings inside the security module
# ---------------------------------------------------------------------------

def _make_mock_settings(**overrides):
    """Return a MagicMock that behaves like app.config.settings."""
    defaults = {
        "admin_token": "aA1" * 11,  # 33 chars, mixed case + digits
        "metrics_token": None,
        "is_production": False,
        "is_staging": False,
        "trust_proxy_headers": False,
        "internal_networks": "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128",
        "media_url_ttl_seconds": 3600,
        "admin_auth_mode": "both",
        "app_env": "dev",
        "admin_host": None,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


# ============================================================================
# Token validation
# ============================================================================

class TestTokenValidation:
    def test_strong_token_no_warnings(self):
        from app.transport.security import validate_token_strength
        # 32+ chars, mixed case + digits
        token = "aB3cD5eF7gH9iJ1kL3mN5oP7qR9sT1uX"  # 33 chars
        warnings = validate_token_strength(token, "TEST_TOKEN")
        assert warnings == []

    def test_short_token_warning(self):
        from app.transport.security import validate_token_strength
        warnings = validate_token_strength("shortAa1", "TEST_TOKEN")
        assert any("too short" in w for w in warnings)

    def test_weak_pattern_warning(self):
        from app.transport.security import validate_token_strength
        token = "A1" * 20 + "password"  # long enough but contains 'password'
        warnings = validate_token_strength(token, "TEST_TOKEN")
        assert any("weak pattern" in w for w in warnings)

    def test_low_diversity_warning(self):
        from app.transport.security import validate_token_strength
        token = "a" * 40  # only lowercase
        warnings = validate_token_strength(token, "TEST_TOKEN")
        assert any("character diversity" in w.lower() or "diversity" in w.lower() for w in warnings)


class TestSecureTokenGeneration:
    def test_correct_length(self):
        from app.transport.security import generate_secure_token
        token = generate_secure_token(32)
        # URL-safe base64 of 32 bytes → ~43 chars
        assert len(token) >= 32

    def test_url_safe_chars(self):
        from app.transport.security import generate_secure_token
        import re
        token = generate_secure_token(32)
        assert re.match(r'^[A-Za-z0-9_-]+$', token)

    def test_uniqueness(self):
        from app.transport.security import generate_secure_token
        t1 = generate_secure_token()
        t2 = generate_secure_token()
        assert t1 != t2


# ============================================================================
# HMAC request signing
# ============================================================================

class TestRequestSignature:
    def test_compute_and_verify_roundtrip(self):
        from app.transport.security import compute_request_signature, verify_request_signature
        secret = "my-secret-key"
        ts = str(int(time.time()))
        sig = compute_request_signature(secret, ts, "GET", "/admin/cleanup")
        valid, err = verify_request_signature(secret, ts, sig, "GET", "/admin/cleanup")
        assert valid is True
        assert err is None

    def test_verify_expired_timestamp(self):
        from app.transport.security import compute_request_signature, verify_request_signature
        secret = "my-secret-key"
        old_ts = str(int(time.time()) - 600)  # 10 min ago
        sig = compute_request_signature(secret, old_ts, "GET", "/test")
        valid, err = verify_request_signature(secret, old_ts, sig, "GET", "/test")
        assert valid is False
        assert "expired" in err.lower()

    def test_verify_invalid_signature(self):
        from app.transport.security import verify_request_signature
        ts = str(int(time.time()))
        valid, err = verify_request_signature("secret", ts, "badhex", "GET", "/test")
        assert valid is False
        assert "signature" in err.lower()

    def test_verify_invalid_timestamp_format(self):
        from app.transport.security import verify_request_signature
        valid, err = verify_request_signature("secret", "not-a-number", "anysig", "GET", "/test")
        assert valid is False
        assert "timestamp" in err.lower()

    def test_verify_with_body(self):
        from app.transport.security import compute_request_signature, verify_request_signature
        secret = "body-secret"
        ts = str(int(time.time()))
        body = b'{"key": "value"}'
        sig = compute_request_signature(secret, ts, "POST", "/api", body)
        valid, err = verify_request_signature(secret, ts, sig, "POST", "/api", body)
        assert valid is True

    def test_verify_tampered_body(self):
        from app.transport.security import compute_request_signature, verify_request_signature
        secret = "body-secret"
        ts = str(int(time.time()))
        sig = compute_request_signature(secret, ts, "POST", "/api", b'original')
        valid, err = verify_request_signature(secret, ts, sig, "POST", "/api", b'tampered')
        assert valid is False


# ============================================================================
# Media URL signatures
# ============================================================================

class TestMediaSignature:
    @patch("app.transport.security.settings")
    def test_roundtrip(self, mock_settings):
        mock_settings.admin_token = "test-admin-token-1234567890123456"
        mock_settings.media_url_ttl_seconds = 3600
        from app.transport.security import generate_media_signature, verify_media_signature
        photo_id = "abc-123"
        exp = int(time.time()) + 3600
        sig = generate_media_signature(photo_id, exp)
        valid, err = verify_media_signature(photo_id, sig, str(exp))
        assert valid is True
        assert err is None

    @patch("app.transport.security.settings")
    def test_expired(self, mock_settings):
        mock_settings.admin_token = "test-admin-token-1234567890123456"
        from app.transport.security import generate_media_signature, verify_media_signature
        photo_id = "abc-123"
        exp = int(time.time()) - 10  # already expired
        sig = generate_media_signature(photo_id, exp)
        valid, err = verify_media_signature(photo_id, sig, str(exp))
        assert valid is False
        assert "expired" in err.lower()

    @patch("app.transport.security.settings")
    def test_tampered_signature(self, mock_settings):
        mock_settings.admin_token = "test-admin-token-1234567890123456"
        from app.transport.security import verify_media_signature
        exp = str(int(time.time()) + 3600)
        valid, err = verify_media_signature("abc-123", "tampered_sig_xxx", exp)
        assert valid is False
        assert "signature" in err.lower()

    @patch("app.transport.security.settings")
    def test_tampered_photo_id(self, mock_settings):
        mock_settings.admin_token = "test-admin-token-1234567890123456"
        from app.transport.security import generate_media_signature, verify_media_signature
        exp = int(time.time()) + 3600
        sig = generate_media_signature("original-id", exp)
        valid, err = verify_media_signature("different-id", sig, str(exp))
        assert valid is False

    @patch("app.transport.security.settings")
    def test_invalid_expiration(self, mock_settings):
        mock_settings.admin_token = "test-admin-token-1234567890123456"
        from app.transport.security import verify_media_signature
        valid, err = verify_media_signature("abc", "sig", "not-a-number")
        assert valid is False
        assert "expiration" in err.lower()

    @patch("app.transport.security.settings")
    def test_no_admin_token_verify(self, mock_settings):
        mock_settings.admin_token = None
        from app.transport.security import verify_media_signature
        valid, err = verify_media_signature("abc", "sig", "12345")
        assert valid is False
        assert "misconfigured" in err.lower()

    @patch("app.transport.security.settings")
    def test_no_admin_token_generate_raises(self, mock_settings):
        mock_settings.admin_token = None
        from app.transport.security import generate_media_signature
        with pytest.raises(RuntimeError):
            generate_media_signature("abc", 12345)

    @patch("app.transport.security.settings")
    def test_signed_url_format(self, mock_settings):
        mock_settings.admin_token = "test-admin-token-1234567890123456"
        mock_settings.media_url_ttl_seconds = 3600
        from app.transport.security import generate_signed_media_url
        url = generate_signed_media_url("https://example.com", "photo-uuid")
        assert "/media/photo-uuid?" in url
        assert "sig=" in url
        assert "exp=" in url


# ============================================================================
# Client IP / Internal network
# ============================================================================

class TestClientIP:
    @patch("app.transport.security.settings")
    def test_direct_connection(self, mock_settings):
        mock_settings.trust_proxy_headers = False
        from app.transport.security import _get_client_ip
        request = MagicMock()
        request.client.host = "1.2.3.4"
        request.headers = {}
        assert _get_client_ip(request) == "1.2.3.4"

    @patch("app.transport.security.settings")
    def test_x_forwarded_for(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        from app.transport.security import _get_client_ip
        request = MagicMock()
        request.client.host = "172.17.0.1"
        request.headers = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
        assert _get_client_ip(request) == "203.0.113.5"

    @patch("app.transport.security.settings")
    def test_x_real_ip_fallback(self, mock_settings):
        mock_settings.trust_proxy_headers = True
        from app.transport.security import _get_client_ip
        request = MagicMock()
        request.client.host = "172.17.0.1"
        request.headers = {"X-Real-IP": "198.51.100.10"}
        assert _get_client_ip(request) == "198.51.100.10"

    @patch("app.transport.security.settings")
    def test_proxy_headers_not_trusted(self, mock_settings):
        mock_settings.trust_proxy_headers = False
        from app.transport.security import _get_client_ip
        request = MagicMock()
        request.client.host = "10.0.0.5"
        request.headers = {"X-Forwarded-For": "evil.spoofed.ip"}
        assert _get_client_ip(request) == "10.0.0.5"


class TestInternalIP:
    def setup_method(self):
        from app.transport.security import _get_internal_networks
        _get_internal_networks.cache_clear()

    def teardown_method(self):
        from app.transport.security import _get_internal_networks
        _get_internal_networks.cache_clear()

    @patch("app.transport.security.settings")
    def test_rfc1918_10_range(self, mock_settings):
        mock_settings.internal_networks = "10.0.0.0/8,127.0.0.0/8"
        from app.transport.security import _is_internal_ip
        assert _is_internal_ip("10.0.0.1") is True

    @patch("app.transport.security.settings")
    def test_rfc1918_172_range(self, mock_settings):
        mock_settings.internal_networks = "172.16.0.0/12,127.0.0.0/8"
        from app.transport.security import _is_internal_ip
        assert _is_internal_ip("172.16.0.1") is True

    @patch("app.transport.security.settings")
    def test_rfc1918_192_range(self, mock_settings):
        mock_settings.internal_networks = "192.168.0.0/16,127.0.0.0/8"
        from app.transport.security import _is_internal_ip
        assert _is_internal_ip("192.168.1.1") is True

    @patch("app.transport.security.settings")
    def test_localhost(self, mock_settings):
        mock_settings.internal_networks = "127.0.0.0/8"
        from app.transport.security import _is_internal_ip
        assert _is_internal_ip("127.0.0.1") is True

    @patch("app.transport.security.settings")
    def test_external_ip(self, mock_settings):
        mock_settings.internal_networks = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8"
        from app.transport.security import _is_internal_ip
        assert _is_internal_ip("8.8.8.8") is False

    @patch("app.transport.security.settings")
    def test_invalid_ip_format(self, mock_settings):
        mock_settings.internal_networks = "10.0.0.0/8"
        from app.transport.security import _is_internal_ip
        assert _is_internal_ip("not-an-ip") is False


# ============================================================================
# Security headers
# ============================================================================

class TestSecurityHeaders:
    @patch("app.transport.security.settings")
    def test_owasp_headers_present(self, mock_settings):
        mock_settings.is_production = False
        mock_settings.is_staging = False
        from app.transport.security import SecurityHeaders
        response = MagicMock()
        response.headers = {}
        SecurityHeaders.add_security_headers(response)
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-XSS-Protection"] == "1; mode=block"
        assert "Content-Security-Policy" in response.headers

    @patch("app.transport.security.settings")
    def test_hsts_in_production(self, mock_settings):
        mock_settings.is_production = True
        mock_settings.is_staging = False
        from app.transport.security import SecurityHeaders
        response = MagicMock()
        response.headers = {}
        SecurityHeaders.add_security_headers(response)
        assert "Strict-Transport-Security" in response.headers

    @patch("app.transport.security.settings")
    def test_no_hsts_in_dev(self, mock_settings):
        mock_settings.is_production = False
        mock_settings.is_staging = False
        from app.transport.security import SecurityHeaders
        response = MagicMock()
        response.headers = {}
        SecurityHeaders.add_security_headers(response)
        assert "Strict-Transport-Security" not in response.headers


# ============================================================================
# Data masking / header sanitization
# ============================================================================

class TestMaskSensitiveData:
    def test_password_redacted(self):
        from app.transport.security import mask_sensitive_data
        result = mask_sensitive_data({"password": "s3cret", "name": "John"})
        assert result["password"] == "***REDACTED***"
        assert result["name"] == "John"

    def test_nested_dict_redacted(self):
        from app.transport.security import mask_sensitive_data
        result = mask_sensitive_data({"config": {"api_key": "abc123"}})
        assert result["config"]["api_key"] == "***REDACTED***"

    def test_non_sensitive_preserved(self):
        from app.transport.security import mask_sensitive_data
        result = mask_sensitive_data({"host": "example.com", "port": 8080})
        assert result == {"host": "example.com", "port": 8080}


class TestSanitizeHeaders:
    def test_authorization_redacted(self):
        from app.transport.security import sanitize_headers_for_logging
        result = sanitize_headers_for_logging({"Authorization": "Bearer xyz"})
        assert result["Authorization"] == "***REDACTED***"

    def test_cookie_redacted(self):
        from app.transport.security import sanitize_headers_for_logging
        result = sanitize_headers_for_logging({"cookie": "session=abc"})
        assert result["cookie"] == "***REDACTED***"

    def test_normal_headers_preserved(self):
        from app.transport.security import sanitize_headers_for_logging
        result = sanitize_headers_for_logging({"Content-Type": "application/json"})
        assert result["Content-Type"] == "application/json"


# ============================================================================
# Error message sanitization
# ============================================================================

class TestSanitizeErrorMessage:
    def test_dev_shows_detail(self):
        from app.transport.security import sanitize_error_message
        err = ValueError("detailed info")
        assert "detailed info" in sanitize_error_message(err, is_production=False)

    def test_production_generic_message(self):
        from app.transport.security import sanitize_error_message
        err = ValueError("detailed info")
        result = sanitize_error_message(err, is_production=True)
        assert "detailed" not in result
        assert result == "Invalid input"

    def test_production_unknown_error_type(self):
        from app.transport.security import sanitize_error_message
        err = RuntimeError("internal")
        result = sanitize_error_message(err, is_production=True)
        assert result == "An error occurred"
