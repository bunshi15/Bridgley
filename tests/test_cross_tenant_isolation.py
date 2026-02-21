# tests/test_cross_tenant_isolation.py
"""
Cross-tenant isolation tests — enforce the multi-tenant security invariants.

These tests prove that:
1. Credentials encrypted for tenant A cannot be decrypted under tenant B.
2. Credentials encrypted for provider X cannot be decrypted under provider Y.
3. provider_account_id conflicts across tenants are blocked by the repo.
4. Admin service returns proper errors for cross-tenant violations.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.infra.crypto import FernetCrypto, CryptoContextMismatchError


# ---------------------------------------------------------------------------
# 1. Credential replay: tenant A → tenant B is blocked
# ---------------------------------------------------------------------------

class TestCredentialReplayBlocked:
    """Prove that ciphertext cannot be replayed across tenants or providers."""

    def setup_method(self):
        self.key = FernetCrypto.generate_key()
        self.crypto = FernetCrypto(self.key)

    def test_credential_replay_across_tenants_blocked(self):
        """
        Invariant 2.5: Credentials encrypted for tenant_A/meta MUST NOT
        decrypt under tenant_B/meta — even with the same encryption key.
        """
        creds = {"access_token": "super_secret_token", "app_secret": "s3cr3t"}

        # Encrypt for tenant A
        encrypted = self.crypto.encrypt_bound(
            creds, tenant_id="tenant_alpha", provider="meta"
        )

        # Decrypt under tenant A succeeds
        decrypted = self.crypto.decrypt_bound(
            encrypted, tenant_id="tenant_alpha", provider="meta"
        )
        assert decrypted == creds

        # Decrypt under tenant B MUST fail
        with pytest.raises(CryptoContextMismatchError, match="context mismatch"):
            self.crypto.decrypt_bound(
                encrypted, tenant_id="tenant_beta", provider="meta"
            )

    def test_credential_replay_across_providers_blocked(self):
        """
        Invariant 2.2: Credentials encrypted for tenant_A/meta MUST NOT
        decrypt under tenant_A/telegram.
        """
        creds = {"access_token": "tok"}

        encrypted = self.crypto.encrypt_bound(
            creds, tenant_id="tenant_alpha", provider="meta"
        )

        with pytest.raises(CryptoContextMismatchError, match="context mismatch"):
            self.crypto.decrypt_bound(
                encrypted, tenant_id="tenant_alpha", provider="telegram"
            )

    def test_credential_replay_across_both_blocked(self):
        """
        Credentials encrypted for (tenant_A, meta) MUST NOT decrypt
        under (tenant_B, telegram) — double mismatch.
        """
        creds = {"access_token": "tok"}

        encrypted = self.crypto.encrypt_bound(
            creds, tenant_id="tenant_alpha", provider="meta"
        )

        with pytest.raises(CryptoContextMismatchError):
            self.crypto.decrypt_bound(
                encrypted, tenant_id="tenant_beta", provider="telegram"
            )

    def test_context_fields_never_leak_in_output(self):
        """
        Invariant 2.3: Internal context fields (__ctx_*) must never
        appear in the decrypted credential dict returned to callers.
        """
        creds = {"bot_token": "123:ABC"}

        encrypted = self.crypto.encrypt_bound(
            creds, tenant_id="t1", provider="telegram"
        )
        decrypted = self.crypto.decrypt_bound(
            encrypted, tenant_id="t1", provider="telegram"
        )

        assert "__ctx_tenant_id" not in decrypted
        assert "__ctx_provider" not in decrypted
        assert decrypted == creds

    def test_plain_encrypt_cannot_pass_bound_decrypt(self):
        """
        Plain-encrypted credentials (no context) must raise
        CryptoContextMismatchError when decrypt_bound is called
        (because __ctx fields are absent → None != expected).
        """
        creds = {"access_token": "tok"}
        encrypted = self.crypto.encrypt(creds)

        with pytest.raises(CryptoContextMismatchError):
            self.crypto.decrypt_bound(
                encrypted, tenant_id="t1", provider="meta"
            )


# ---------------------------------------------------------------------------
# 2. Provider account ID conflict across tenants
# ---------------------------------------------------------------------------

class TestProviderAccountIdConflict:
    """
    Prove that the same provider_account_id cannot be active
    in two different tenants simultaneously.
    """

    @pytest.mark.asyncio
    async def test_provider_account_id_conflict_across_tenants(self):
        """
        Invariant 4.1: If phone_number_id '12345' is bound to tenant_A/meta,
        then binding it to tenant_B/meta must raise ChannelBindingConflictError.
        """
        from app.infra.pg_tenant_repo_async import (
            AsyncPostgresTenantRepository,
            ChannelBindingConflictError,
        )

        repo = AsyncPostgresTenantRepository()

        # Mock DB connection context
        mock_conn = AsyncMock()

        # Simulate: tenant exists, but conflict found
        mock_conn.fetchrow = AsyncMock(side_effect=[
            # First call: SELECT id FROM tenants WHERE id = $1 → tenant exists
            {"id": "tenant_beta"},
            # Second call: SELECT tenant_id FROM channel_bindings WHERE provider = ... → conflict!
            {"tenant_id": "tenant_alpha"},
        ])

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.infra.pg_tenant_repo_async.safe_db_conn", return_value=mock_ctx):
            # Also need to mock crypto
            mock_crypto = MagicMock()
            mock_crypto.encrypt_bound = MagicMock(return_value=b"encrypted_blob")

            with patch("app.infra.pg_tenant_repo_async.get_crypto", return_value=mock_crypto):
                with patch("app.infra.pg_tenant_repo_async.validate_channel_payload"):
                    with pytest.raises(ChannelBindingConflictError) as exc_info:
                        await repo.upsert_channel(
                            tenant_id="tenant_beta",
                            provider="meta",
                            provider_account_id="12345",
                            credentials={"access_token": "tok"},
                            config={"phone_number_id": "12345"},
                        )

                    assert "tenant_alpha" in str(exc_info.value)
                    assert "12345" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. Admin service error mapping
# ---------------------------------------------------------------------------

class TestAdminServiceIsolation:
    """
    Prove that the admin service correctly maps repo-level
    isolation errors to typed domain errors.
    """

    @pytest.mark.asyncio
    async def test_get_nonexistent_tenant_returns_not_found(self):
        """Service must raise NotFoundError for missing tenants."""
        from app.admin.service import AdminApplicationService
        from app.admin.errors import NotFoundError
        from app.infra.pg_tenant_repo_async import TenantNotFoundError

        mock_repo = AsyncMock()
        mock_repo.get_tenant = AsyncMock(
            side_effect=TenantNotFoundError("Tenant 'ghost' not found")
        )

        svc = AdminApplicationService(repo=mock_repo)

        with pytest.raises(NotFoundError) as exc_info:
            await svc.get_tenant("ghost")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_duplicate_tenant_returns_conflict(self):
        """Service must raise ConflictError for duplicate tenant IDs."""
        from app.admin.service import AdminApplicationService
        from app.admin.errors import ConflictError
        from app.admin.models import CreateTenantRequest
        from app.infra.pg_tenant_repo_async import TenantAlreadyExistsError

        mock_repo = AsyncMock()
        mock_repo.create_tenant = AsyncMock(
            side_effect=TenantAlreadyExistsError("Tenant 'dup' already exists")
        )

        svc = AdminApplicationService(repo=mock_repo)
        req = CreateTenantRequest(id="dup", display_name="Duplicate")

        with pytest.raises(ConflictError) as exc_info:
            await svc.create_tenant(req)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_upsert_channel_conflict_returns_409(self):
        """
        Service must raise ConflictError when provider_account_id
        is already bound to another tenant.
        """
        from app.admin.service import AdminApplicationService
        from app.admin.errors import ConflictError
        from app.admin.models import UpsertChannelRequest
        from app.infra.pg_tenant_repo_async import ChannelBindingConflictError

        mock_repo = AsyncMock()
        mock_repo.upsert_channel = AsyncMock(
            side_effect=ChannelBindingConflictError(
                "provider_account_id '12345' is already bound to tenant 'tenant_alpha'"
            )
        )

        svc = AdminApplicationService(repo=mock_repo)
        req = UpsertChannelRequest(
            provider="meta",
            credentials={"access_token": "tok"},
            config={"phone_number_id": "12345"},
        )

        with pytest.raises(ConflictError) as exc_info:
            await svc.upsert_channel("tenant_beta", req)
        assert exc_info.value.status_code == 409
        assert "tenant_alpha" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_update_with_no_fields_returns_validation_error(self):
        """Service must raise ValidationError when no fields to update."""
        from app.admin.service import AdminApplicationService
        from app.admin.errors import ValidationError
        from app.admin.models import UpdateTenantRequest

        svc = AdminApplicationService(repo=AsyncMock())
        req = UpdateTenantRequest()  # all None

        with pytest.raises(ValidationError) as exc_info:
            await svc.update_tenant("t1", req)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# 4. Pydantic model validation
# ---------------------------------------------------------------------------

class TestAdminModelValidation:
    """Prove that admin request models enforce input constraints."""

    def test_tenant_id_must_be_slug(self):
        """Tenant IDs with spaces or special chars are rejected."""
        from app.admin.models import CreateTenantRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CreateTenantRequest(id="bad tenant id!", display_name="Test")

        with pytest.raises(ValidationError):
            CreateTenantRequest(id="has spaces", display_name="Test")

        # Valid slugs should pass
        req = CreateTenantRequest(id="my-tenant_123", display_name="Test")
        assert req.id == "my-tenant_123"

    def test_provider_must_be_known(self):
        """Unknown provider names are rejected."""
        from app.admin.models import UpsertChannelRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UpsertChannelRequest(
                provider="discord",
                credentials={"token": "x"},
            )

    def test_credentials_must_not_be_empty(self):
        """Empty credentials dict is rejected."""
        from app.admin.models import UpsertChannelRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            UpsertChannelRequest(
                provider="meta",
                credentials={},
            )

    def test_update_has_updates_check(self):
        """UpdateTenantRequest.has_updates() returns False when all None."""
        from app.admin.models import UpdateTenantRequest

        empty = UpdateTenantRequest()
        assert empty.has_updates() is False

        with_name = UpdateTenantRequest(display_name="New")
        assert with_name.has_updates() is True
