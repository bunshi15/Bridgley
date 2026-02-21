# tests/test_crypto.py
"""Tests for Fernet encryption module (v0.8 Multi-Tenant)."""
import pytest

from app.infra.crypto import (
    FernetCrypto,
    CryptoError,
    CryptoNotConfiguredError,
    CryptoContextMismatchError,
    get_crypto,
    reset_crypto,
)


# ---------------------------------------------------------------------------
# FernetCrypto — Unit Tests (plain encrypt/decrypt)
# ---------------------------------------------------------------------------

class TestFernetCrypto:
    """Test FernetCrypto encrypt/decrypt."""

    def setup_method(self):
        self.key = FernetCrypto.generate_key()
        self.crypto = FernetCrypto(self.key)

    def test_encrypt_decrypt_round_trip(self):
        """Encrypt then decrypt should return the original dict."""
        original = {"access_token": "secret123", "phone_number_id": "12345"}
        encrypted = self.crypto.encrypt(original)
        assert isinstance(encrypted, bytes)
        assert encrypted != b""

        decrypted = self.crypto.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_decrypt_empty_dict(self):
        """Encrypting an empty dict should work."""
        encrypted = self.crypto.encrypt({})
        decrypted = self.crypto.decrypt(encrypted)
        assert decrypted == {}

    def test_encrypt_decrypt_nested_dict(self):
        """Nested and complex values should survive round-trip."""
        original = {
            "token": "abc",
            "nested": {"a": 1, "b": [1, 2, 3]},
            "flag": True,
            "count": 42,
        }
        encrypted = self.crypto.encrypt(original)
        decrypted = self.crypto.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_decrypt_unicode(self):
        """Unicode strings should survive round-trip."""
        original = {"name": "Привет мир", "emoji": "🔐"}
        encrypted = self.crypto.encrypt(original)
        decrypted = self.crypto.decrypt(encrypted)
        assert decrypted == original

    def test_decrypt_with_wrong_key_fails(self):
        """Decrypting with a different key should fail."""
        encrypted = self.crypto.encrypt({"secret": "data"})

        other_key = FernetCrypto.generate_key()
        other_crypto = FernetCrypto(other_key)

        with pytest.raises(CryptoError, match="invalid token"):
            other_crypto.decrypt(encrypted)

    def test_decrypt_corrupted_data_fails(self):
        """Decrypting corrupted data should fail."""
        with pytest.raises(CryptoError):
            self.crypto.decrypt(b"definitely_not_a_valid_fernet_token")

    def test_invalid_key_raises(self):
        """Invalid Fernet key should raise CryptoError."""
        with pytest.raises(CryptoError, match="Invalid Fernet key"):
            FernetCrypto("not-a-valid-fernet-key")

    def test_generate_key_format(self):
        """Generated key should be a non-empty ASCII string."""
        key = FernetCrypto.generate_key()
        assert isinstance(key, str)
        assert len(key) > 0
        # Fernet keys are URL-safe base64, should be ASCII
        key.encode("ascii")

    def test_generate_key_unique(self):
        """Each call to generate_key should produce a unique key."""
        keys = {FernetCrypto.generate_key() for _ in range(10)}
        assert len(keys) == 10

    def test_decrypt_memoryview(self):
        """Decrypting from a memoryview (asyncpg returns these) should work."""
        encrypted = self.crypto.encrypt({"key": "value"})
        mv = memoryview(encrypted)
        decrypted = self.crypto.decrypt(mv)
        assert decrypted == {"key": "value"}


# ---------------------------------------------------------------------------
# Context-bound encrypt/decrypt (anti-replay)
# ---------------------------------------------------------------------------

class TestContextBoundCrypto:
    """Test encrypt_bound / decrypt_bound for anti-replay."""

    def setup_method(self):
        self.key = FernetCrypto.generate_key()
        self.crypto = FernetCrypto(self.key)

    def test_bound_round_trip(self):
        """encrypt_bound → decrypt_bound returns original credentials."""
        creds = {"access_token": "secret", "app_secret": "s3cr3t"}
        encrypted = self.crypto.encrypt_bound(
            creds, tenant_id="t1", provider="meta"
        )
        decrypted = self.crypto.decrypt_bound(
            encrypted, tenant_id="t1", provider="meta"
        )
        assert decrypted == creds

    def test_bound_wrong_tenant_raises(self):
        """Decrypting under a different tenant_id should fail."""
        encrypted = self.crypto.encrypt_bound(
            {"token": "x"}, tenant_id="t1", provider="meta"
        )
        with pytest.raises(CryptoContextMismatchError, match="context mismatch"):
            self.crypto.decrypt_bound(
                encrypted, tenant_id="t2", provider="meta"
            )

    def test_bound_wrong_provider_raises(self):
        """Decrypting under a different provider should fail."""
        encrypted = self.crypto.encrypt_bound(
            {"token": "x"}, tenant_id="t1", provider="meta"
        )
        with pytest.raises(CryptoContextMismatchError, match="context mismatch"):
            self.crypto.decrypt_bound(
                encrypted, tenant_id="t1", provider="telegram"
            )

    def test_bound_context_stripped_from_output(self):
        """Context keys (__ctx_*) should not appear in decrypted output."""
        creds = {"bot_token": "abc"}
        encrypted = self.crypto.encrypt_bound(
            creds, tenant_id="t1", provider="telegram"
        )
        decrypted = self.crypto.decrypt_bound(
            encrypted, tenant_id="t1", provider="telegram"
        )
        assert "__ctx_tenant_id" not in decrypted
        assert "__ctx_provider" not in decrypted
        assert decrypted == {"bot_token": "abc"}

    def test_plain_decrypt_of_bound_includes_context(self):
        """Plain decrypt of bound data should include context fields."""
        encrypted = self.crypto.encrypt_bound(
            {"key": "val"}, tenant_id="t1", provider="twilio"
        )
        # Plain decrypt reveals context fields (backward compat path)
        raw = self.crypto.decrypt(encrypted)
        assert raw["__ctx_tenant_id"] == "t1"
        assert raw["__ctx_provider"] == "twilio"
        assert raw["key"] == "val"

    def test_bound_decrypt_of_plain_falls_through(self):
        """decrypt_bound of plain-encrypted data (no context) raises mismatch."""
        encrypted = self.crypto.encrypt({"key": "val"})
        with pytest.raises(CryptoContextMismatchError):
            self.crypto.decrypt_bound(
                encrypted, tenant_id="t1", provider="meta"
            )


# ---------------------------------------------------------------------------
# get_crypto() singleton
# ---------------------------------------------------------------------------

class TestGetCrypto:
    """Test the global crypto singleton."""

    def setup_method(self):
        reset_crypto()

    def teardown_method(self):
        reset_crypto()

    def test_not_configured_raises(self, monkeypatch):
        """get_crypto() should raise when TENANT_ENCRYPTION_KEY is not set."""
        monkeypatch.setattr("app.config.settings.tenant_encryption_key", None)
        with pytest.raises(CryptoNotConfiguredError, match="TENANT_ENCRYPTION_KEY"):
            get_crypto()

    def test_configured_returns_instance(self, monkeypatch):
        """get_crypto() should return a FernetCrypto when key is set."""
        key = FernetCrypto.generate_key()
        monkeypatch.setattr("app.config.settings.tenant_encryption_key", key)
        crypto = get_crypto()
        assert isinstance(crypto, FernetCrypto)

    def test_singleton_returns_same_instance(self, monkeypatch):
        """get_crypto() should return the same instance on repeated calls."""
        key = FernetCrypto.generate_key()
        monkeypatch.setattr("app.config.settings.tenant_encryption_key", key)
        c1 = get_crypto()
        c2 = get_crypto()
        assert c1 is c2
