# app/admin/service.py
"""
Admin Application Service — the single orchestration point for all
tenant-management operations.

Responsibilities:
    1. Validate requests (via Pydantic models)
    2. Call repository for persistence
    3. Emit audit events
    4. Refresh the in-memory tenant registry where needed
    5. Return redacted DTOs — **never** raw config or credentials

The transport layer (http_app.py admin routes) becomes a thin adapter:
    parse request → call service → map AdminError → return JSON.
"""
from __future__ import annotations

from app.admin.errors import ValidationError, NotFoundError, ConflictError
from app.admin.models import (
    CreateTenantRequest,
    UpdateTenantRequest,
    UpsertChannelRequest,
    TenantSummary,
    TenantDetail,
    OkResponse,
)
from app.infra.pg_tenant_repo_async import (
    AsyncPostgresTenantRepository,
    get_tenant_repo,
    TenantNotFoundError,
    TenantAlreadyExistsError,
    ChannelBindingNotFoundError,
    ChannelBindingConflictError,
)
from app.infra.credential_schemas import (
    CredentialValidationError,
    extract_provider_account_id,
)
from app.infra.audit_log import audit_event
from app.infra.tenant_registry import get_all_tenants, reload_tenants
from app.infra.logging_config import get_logger

logger = get_logger(__name__)


class AdminApplicationService:
    """
    Orchestrates all admin-facing tenant operations.

    Thread-safety: stateless — safe to use as a singleton.
    """

    def __init__(self, repo: AsyncPostgresTenantRepository | None = None) -> None:
        self._repo = repo

    @property
    def repo(self) -> AsyncPostgresTenantRepository:
        if self._repo is None:
            self._repo = get_tenant_repo()
        return self._repo

    # ------------------------------------------------------------------
    # Tenants
    # ------------------------------------------------------------------

    async def list_tenants(self) -> list[TenantSummary]:
        """
        List all tenants from the in-memory registry.

        Returns lightweight summaries with channel presence
        (credentials_configured bool, no secrets, no raw config).
        """
        tenants = get_all_tenants()
        return [
            TenantSummary(
                id=t.tenant_id,
                display_name=t.display_name,
                is_active=t.is_active,
                channels=[
                    {
                        "provider": ch.provider,
                        "credentials_configured": bool(ch.credentials),
                    }
                    for ch in t.channels.values()
                ],
            )
            for t in tenants
        ]

    async def get_tenant(self, tenant_id: str) -> TenantDetail:
        """
        Get a single tenant with its channel bindings.

        Config is redacted (repo handles allow-listing).
        Credentials are never returned.
        """
        try:
            tenant_dto, binding_dtos = await self.repo.get_tenant(tenant_id)
        except TenantNotFoundError:
            raise NotFoundError(f"Tenant '{tenant_id}' not found")

        return TenantDetail(
            id=tenant_dto.id,
            display_name=tenant_dto.display_name,
            is_active=tenant_dto.is_active,
            config=tenant_dto.config,
            created_at=tenant_dto.created_at,
            updated_at=tenant_dto.updated_at,
            channels=[
                {
                    "id": b.id,
                    "provider": b.provider,
                    "provider_account_id": b.provider_account_id,
                    "config": b.config,
                    "credentials_configured": b.credentials_configured,
                    "is_active": b.is_active,
                    "created_at": b.created_at,
                    "updated_at": b.updated_at,
                }
                for b in binding_dtos
            ],
        )

    async def create_tenant(self, req: CreateTenantRequest) -> OkResponse:
        """
        Create a new tenant.

        Emits audit event on success.
        """
        display = req.display_name or req.id

        try:
            await self.repo.create_tenant(req.id, display, req.config)
        except TenantAlreadyExistsError:
            raise ConflictError(f"Tenant '{req.id}' already exists")

        audit_event("tenant.create", tenant_id=req.id, detail=f"display_name={display}")
        return OkResponse(tenant_id=req.id)

    async def update_tenant(self, tenant_id: str, req: UpdateTenantRequest) -> OkResponse:
        """
        Update a tenant's mutable fields.

        Emits audit event on success.
        """
        if not req.has_updates():
            raise ValidationError("No fields to update")

        try:
            await self.repo.update_tenant(
                tenant_id,
                display_name=req.display_name,
                is_active=req.is_active,
                config=req.config,
            )
        except TenantNotFoundError:
            raise NotFoundError(f"Tenant '{tenant_id}' not found")

        changed = [k for k, v in req.model_dump(exclude_none=True).items()]
        audit_event("tenant.update", tenant_id=tenant_id, detail=f"fields={changed}")
        return OkResponse(tenant_id=tenant_id)

    # ------------------------------------------------------------------
    # Channel bindings
    # ------------------------------------------------------------------

    async def upsert_channel(self, tenant_id: str, req: UpsertChannelRequest) -> OkResponse:
        """
        Add or update a channel binding.

        1. Extract provider_account_id from credentials/config.
        2. Validate credential + config schemas (repo delegates to infra).
        3. Encrypt credentials with context binding.
        4. Persist via repo (with cross-tenant conflict check).
        5. Emit audit event.
        """
        provider_account_id = extract_provider_account_id(
            req.provider, req.credentials, req.config,
        )

        try:
            await self.repo.upsert_channel(
                tenant_id,
                req.provider,
                provider_account_id,
                req.credentials,
                req.config,
            )
        except TenantNotFoundError:
            raise NotFoundError(f"Tenant '{tenant_id}' not found")
        except CredentialValidationError as exc:
            raise ValidationError(str(exc))
        except ChannelBindingConflictError as exc:
            raise ConflictError(str(exc))

        audit_event("channel.upsert", tenant_id=tenant_id, provider=req.provider)
        return OkResponse(tenant_id=tenant_id, provider=req.provider)

    async def delete_channel(self, tenant_id: str, provider: str) -> OkResponse:
        """
        Remove a channel binding.

        Emits audit event on success.
        """
        try:
            await self.repo.delete_channel(tenant_id, provider)
        except ChannelBindingNotFoundError:
            raise NotFoundError(f"Channel binding not found for tenant '{tenant_id}', provider '{provider}'")

        audit_event("channel.delete", tenant_id=tenant_id, provider=provider)
        return OkResponse(tenant_id=tenant_id, provider=provider)

    # ------------------------------------------------------------------
    # Registry reload
    # ------------------------------------------------------------------

    async def reload_tenant_registry(self) -> OkResponse:
        """
        Refresh the in-memory tenant cache from the database.

        Emits audit event on success.
        """
        count = await reload_tenants()
        audit_event("tenants.reload", detail=f"loaded={count}")
        return OkResponse(tenants_loaded=count)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_svc: AdminApplicationService | None = None


def get_admin_service() -> AdminApplicationService:
    """Get the global AdminApplicationService singleton."""
    global _svc
    if _svc is None:
        _svc = AdminApplicationService()
    return _svc


def reset_admin_service() -> None:
    """Reset the singleton (for testing)."""
    global _svc
    _svc = None
