# app/infra/pg_tenant_repo_async.py
"""
Async Postgres repository for tenant and channel binding CRUD.

All DB operations for the multi-tenant system live here.
The transport layer (http_app.py) delegates to this repository
and never touches SQL directly.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.infra.db_resilience_async import safe_db_conn
from app.infra.crypto import get_crypto
from app.infra.credential_schemas import validate_channel_payload, CredentialValidationError
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs returned by the repository (transport-safe, no secrets)
# ---------------------------------------------------------------------------

@dataclass
class TenantDTO:
    """Tenant data for API responses (never contains secrets)."""
    id: str
    display_name: str
    is_active: bool
    config: dict
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class ChannelBindingDTO:
    """Channel binding data for API responses (never contains secrets)."""
    id: str
    tenant_id: str
    provider: str
    provider_account_id: str
    config: dict
    credentials_configured: bool
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class TenantNotFoundError(Exception):
    """Raised when a tenant is not found."""


class TenantAlreadyExistsError(Exception):
    """Raised when trying to create a duplicate tenant."""


class ChannelBindingNotFoundError(Exception):
    """Raised when a channel binding is not found."""


class ChannelBindingConflictError(Exception):
    """Raised when a provider_account_id is already bound to another tenant."""


# ---------------------------------------------------------------------------
# Allow-listed config keys that are safe to return in API responses
# ---------------------------------------------------------------------------

_SAFE_TENANT_CONFIG_KEYS = {
    "quota", "feature_flags", "bot_type", "language", "timezone",
    # v0.8.1: per-tenant operator notification settings
    "operator_whatsapp", "operator_notifications_enabled",
    "operator_notification_channel",
}

_SAFE_CHANNEL_CONFIG_KEYS = {
    "meta": {"phone_number_id", "waba_id", "graph_api_version"},
    "telegram": {"channel_mode"},
    "twilio": {"phone_number"},
}


def _redact_config(config: dict, allowed_keys: set[str]) -> dict:
    """Return only allow-listed keys from config."""
    return {k: v for k, v in config.items() if k in allowed_keys}


def _parse_jsonb(raw: Any) -> dict:
    """Parse a jsonb column value (may be dict or str)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return {}


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class AsyncPostgresTenantRepository:
    """Async Postgres repository for tenant + channel binding CRUD."""

    # ------------------------------------------------------------------
    # Tenant CRUD
    # ------------------------------------------------------------------

    async def list_tenants(self) -> list[TenantDTO]:
        """List all tenants (minimal fields, no secrets)."""
        async with safe_db_conn() as conn:
            rows = await conn.fetch(
                "SELECT id, display_name, is_active FROM tenants ORDER BY id"
            )
        return [
            TenantDTO(
                id=r["id"],
                display_name=r["display_name"],
                is_active=r["is_active"],
                config={},  # never return raw config in list
            )
            for r in rows
        ]

    async def get_tenant(self, tenant_id: str) -> tuple[TenantDTO, list[ChannelBindingDTO]]:
        """
        Get a single tenant with its channel bindings.

        Raises TenantNotFoundError if not found.
        Returns (TenantDTO, list[ChannelBindingDTO]) — never includes secrets.
        """
        async with safe_db_conn() as conn:
            row = await conn.fetchrow(
                "SELECT id, display_name, is_active, config_json, created_at, updated_at "
                "FROM tenants WHERE id = $1",
                tenant_id,
            )
            if not row:
                raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

            binding_rows = await conn.fetch(
                "SELECT id, tenant_id, provider, provider_account_id, config_json, "
                "is_active, created_at, updated_at "
                "FROM channel_bindings WHERE tenant_id = $1 ORDER BY provider",
                tenant_id,
            )

        raw_config = _parse_jsonb(row["config_json"])

        tenant = TenantDTO(
            id=row["id"],
            display_name=row["display_name"],
            is_active=row["is_active"],
            config=_redact_config(raw_config, _SAFE_TENANT_CONFIG_KEYS),
            created_at=row["created_at"].isoformat(),
            updated_at=row["updated_at"].isoformat(),
        )

        bindings = []
        for b in binding_rows:
            b_config = _parse_jsonb(b["config_json"])
            safe_keys = _SAFE_CHANNEL_CONFIG_KEYS.get(b["provider"], set())
            bindings.append(ChannelBindingDTO(
                id=str(b["id"]),
                tenant_id=b["tenant_id"],
                provider=b["provider"],
                provider_account_id=b["provider_account_id"] or "",
                config=_redact_config(b_config, safe_keys),
                credentials_configured=True,
                is_active=b["is_active"],
                created_at=b["created_at"].isoformat(),
                updated_at=b["updated_at"].isoformat(),
            ))

        return tenant, bindings

    async def create_tenant(
        self,
        tenant_id: str,
        display_name: str,
        config: dict | None = None,
    ) -> TenantDTO:
        """
        Create a new tenant.

        Raises TenantAlreadyExistsError if duplicate.
        """
        config = config or {}
        async with safe_db_conn() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO tenants (id, display_name, is_active, config_json)
                    VALUES ($1, $2, true, $3::jsonb)
                    """,
                    tenant_id,
                    display_name,
                    json.dumps(config),
                )
            except Exception as exc:
                if "duplicate key" in str(exc).lower() or "unique" in str(exc).lower():
                    raise TenantAlreadyExistsError(f"Tenant '{tenant_id}' already exists") from exc
                raise

        return TenantDTO(id=tenant_id, display_name=display_name, is_active=True, config=config)

    async def update_tenant(
        self,
        tenant_id: str,
        *,
        display_name: str | None = None,
        is_active: bool | None = None,
        config: dict | None = None,
    ) -> None:
        """
        Update tenant fields.

        Raises TenantNotFoundError if tenant doesn't exist.
        """
        async with safe_db_conn() as conn:
            existing = await conn.fetchrow("SELECT id FROM tenants WHERE id = $1", tenant_id)
            if not existing:
                raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

            updates = []
            params: list[Any] = [tenant_id]
            idx = 2

            if display_name is not None:
                updates.append(f"display_name = ${idx}")
                params.append(display_name)
                idx += 1

            if is_active is not None:
                updates.append(f"is_active = ${idx}")
                params.append(is_active)
                idx += 1

            if config is not None:
                updates.append(f"config_json = ${idx}::jsonb")
                params.append(json.dumps(config))
                idx += 1

            if not updates:
                return  # nothing to update

            updates.append("updated_at = now()")
            await conn.execute(
                f"UPDATE tenants SET {', '.join(updates)} WHERE id = $1",
                *params,
            )

    # ------------------------------------------------------------------
    # Channel binding CRUD
    # ------------------------------------------------------------------

    async def upsert_channel(
        self,
        tenant_id: str,
        provider: str,
        provider_account_id: str,
        credentials: dict,
        config: dict,
    ) -> None:
        """
        Add or update a channel binding.

        Validates schemas, encrypts credentials with context binding,
        and checks for provider_account_id conflicts across tenants.

        Raises:
            TenantNotFoundError: if tenant doesn't exist
            CredentialValidationError: if payload fails schema validation
            ChannelBindingConflictError: if provider_account_id is bound to another tenant
        """
        # Schema validation
        validate_channel_payload(provider, credentials, config)

        # Encrypt with context binding (anti-replay)
        crypto = get_crypto()
        encrypted = crypto.encrypt_bound(credentials, tenant_id=tenant_id, provider=provider)

        async with safe_db_conn() as conn:
            # Verify tenant exists
            existing = await conn.fetchrow("SELECT id FROM tenants WHERE id = $1", tenant_id)
            if not existing:
                raise TenantNotFoundError(f"Tenant '{tenant_id}' not found")

            # Check for provider_account_id conflict with another tenant
            if provider_account_id:
                conflict = await conn.fetchrow(
                    """
                    SELECT tenant_id FROM channel_bindings
                    WHERE provider = $1 AND provider_account_id = $2 AND tenant_id != $3
                    """,
                    provider, provider_account_id, tenant_id,
                )
                if conflict:
                    raise ChannelBindingConflictError(
                        f"provider_account_id '{provider_account_id}' is already bound "
                        f"to tenant '{conflict['tenant_id']}'"
                    )

            # Upsert
            await conn.execute(
                """
                INSERT INTO channel_bindings
                    (tenant_id, provider, provider_account_id, credentials_enc, config_json)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                ON CONFLICT (tenant_id, provider)
                DO UPDATE SET
                    provider_account_id = EXCLUDED.provider_account_id,
                    credentials_enc = EXCLUDED.credentials_enc,
                    config_json = EXCLUDED.config_json,
                    updated_at = now()
                """,
                tenant_id,
                provider,
                provider_account_id,
                encrypted,
                json.dumps(config),
            )

    async def delete_channel(self, tenant_id: str, provider: str) -> None:
        """
        Delete a channel binding.

        Raises ChannelBindingNotFoundError if not found.
        """
        async with safe_db_conn() as conn:
            result = await conn.execute(
                "DELETE FROM channel_bindings WHERE tenant_id = $1 AND provider = $2",
                tenant_id, provider,
            )
            deleted = int(result.split()[-1]) if result else 0

        if deleted == 0:
            raise ChannelBindingNotFoundError(
                f"No channel binding found for tenant '{tenant_id}', provider '{provider}'"
            )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_repo: AsyncPostgresTenantRepository | None = None


def get_tenant_repo() -> AsyncPostgresTenantRepository:
    """Get the global tenant repository singleton."""
    global _repo
    if _repo is None:
        _repo = AsyncPostgresTenantRepository()
    return _repo
