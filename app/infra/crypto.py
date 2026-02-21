# app/infra/crypto.py
"""
Fernet symmetric encryption for tenant credentials.

Used to encrypt/decrypt channel binding credentials stored in the DB.
Key is loaded from TENANT_ENCRYPTION_KEY environment variable (Fernet key format).

Context binding (anti-replay):
    encrypt_bound / decrypt_bound embed (tenant_id, provider) into the
    encrypted payload so ciphertext cannot be replayed under a different
    tenant or provider.

Usage:
    crypto = get_crypto()

    # Context-bound encryption (recommended for channel bindings):
    encrypted = crypto.encrypt_bound(
        {"access_token": "secret123"},
        tenant_id="t1",
        provider="meta",
    )
    decrypted = crypto.decrypt_bound(encrypted, tenant_id="t1", provider="meta")

    # Plain encryption (for backward compat / generic use):
    encrypted = crypto.encrypt({"key": "value"})
    decrypted = crypto.decrypt(encrypted)

Key generation:
    python scripts/generate_encryption_key.py
"""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.infra.logging_config import get_logger

logger = get_logger(__name__)


# Internal key for the context binding fields inside the encrypted blob
_CTX_TENANT_KEY = "__ctx_tenant_id"
_CTX_PROVIDER_KEY = "__ctx_provider"


class CryptoError(Exception):
    """Raised when encryption/decryption fails."""


class CryptoNotConfiguredError(CryptoError):
    """Raised when encryption key is not configured."""


class CryptoContextMismatchError(CryptoError):
    """Raised when decrypt context (tenant/provider) doesn't match encrypted context."""


class FernetCrypto:
    """Fernet-based encryption for credential blobs."""

    def __init__(self, key: str):
        """
        Initialize with a Fernet key.

        Args:
            key: URL-safe base64-encoded 32-byte key (use generate_key() to create one)

        Raises:
            CryptoError: If the key is invalid
        """
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as exc:
            raise CryptoError(f"Invalid Fernet key: {exc}") from exc

    # ------------------------------------------------------------------
    # Plain encrypt/decrypt (no context binding)
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: dict[str, Any]) -> bytes:
        """
        Encrypt a dict as a Fernet token.

        Args:
            plaintext: Dictionary to encrypt (must be JSON-serializable)

        Returns:
            Fernet-encrypted bytes

        Raises:
            CryptoError: If serialization or encryption fails
        """
        try:
            json_bytes = json.dumps(plaintext, ensure_ascii=False).encode("utf-8")
            return self._fernet.encrypt(json_bytes)
        except Exception as exc:
            raise CryptoError(f"Encryption failed: {exc}") from exc

    def decrypt(self, ciphertext: bytes) -> dict[str, Any]:
        """
        Decrypt a Fernet token back to a dict.

        Args:
            ciphertext: Fernet-encrypted bytes

        Returns:
            Decrypted dictionary

        Raises:
            CryptoError: If decryption or deserialization fails
        """
        try:
            if isinstance(ciphertext, memoryview):
                ciphertext = bytes(ciphertext)
            json_bytes = self._fernet.decrypt(ciphertext)
            return json.loads(json_bytes)
        except InvalidToken:
            raise CryptoError("Decryption failed: invalid token (wrong key or corrupted data)")
        except json.JSONDecodeError as exc:
            raise CryptoError(f"Decryption succeeded but JSON parsing failed: {exc}") from exc
        except Exception as exc:
            raise CryptoError(f"Decryption failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Context-bound encrypt/decrypt (anti-replay)
    # ------------------------------------------------------------------

    def encrypt_bound(
        self,
        plaintext: dict[str, Any],
        *,
        tenant_id: str,
        provider: str,
    ) -> bytes:
        """
        Encrypt with embedded context binding (tenant_id + provider).

        The context is stored inside the encrypted blob so it cannot be
        tampered with. On decrypt_bound, the context is verified and
        stripped from the returned dict.

        This prevents ciphertext replay: credentials encrypted for
        tenant A / provider meta cannot be decrypted under tenant B
        or provider telegram.

        Args:
            plaintext: Dictionary to encrypt (must be JSON-serializable)
            tenant_id: Tenant ID to bind
            provider: Provider name to bind ("meta", "telegram", "twilio")

        Returns:
            Fernet-encrypted bytes with embedded context
        """
        # Embed context fields into a copy of the payload
        bound = {
            _CTX_TENANT_KEY: tenant_id,
            _CTX_PROVIDER_KEY: provider,
            **plaintext,
        }
        return self.encrypt(bound)

    def decrypt_bound(
        self,
        ciphertext: bytes,
        *,
        tenant_id: str,
        provider: str,
    ) -> dict[str, Any]:
        """
        Decrypt and verify context binding (tenant_id + provider).

        Raises CryptoContextMismatchError if the embedded context
        doesn't match the expected (tenant_id, provider).

        Args:
            ciphertext: Fernet-encrypted bytes (from encrypt_bound)
            tenant_id: Expected tenant ID
            provider: Expected provider name

        Returns:
            Decrypted dictionary (context fields stripped)

        Raises:
            CryptoContextMismatchError: If context doesn't match
            CryptoError: If decryption fails
        """
        data = self.decrypt(ciphertext)

        # Verify context
        stored_tenant = data.pop(_CTX_TENANT_KEY, None)
        stored_provider = data.pop(_CTX_PROVIDER_KEY, None)

        if stored_tenant != tenant_id or stored_provider != provider:
            raise CryptoContextMismatchError(
                "Credential context mismatch: the ciphertext was encrypted "
                "for a different tenant/provider pair"
            )

        return data

    @staticmethod
    def generate_key() -> str:
        """
        Generate a new Fernet key.

        Returns:
            URL-safe base64-encoded 32-byte key string

        Usage:
            key = FernetCrypto.generate_key()
            # Set as TENANT_ENCRYPTION_KEY in .env
        """
        return Fernet.generate_key().decode("ascii")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_crypto: FernetCrypto | None = None


def get_crypto() -> FernetCrypto:
    """
    Get the global FernetCrypto singleton.

    Lazily initialized from settings.tenant_encryption_key.

    Returns:
        FernetCrypto instance

    Raises:
        CryptoNotConfiguredError: If TENANT_ENCRYPTION_KEY is not set
    """
    global _crypto
    if _crypto is None:
        from app.config import settings

        if not settings.tenant_encryption_key:
            raise CryptoNotConfiguredError(
                "TENANT_ENCRYPTION_KEY is not configured. "
                "Generate a key using the provided script and set it in .env"
            )
        _crypto = FernetCrypto(settings.tenant_encryption_key)
        logger.info("Fernet crypto initialized")

    return _crypto


def reset_crypto() -> None:
    """Reset the global crypto singleton (for testing)."""
    global _crypto
    _crypto = None
