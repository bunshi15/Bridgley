# app/admin/models.py
"""
Pydantic request/response models for the admin API.

These live *outside* the transport layer so the service can
validate payloads without depending on FastAPI.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Any


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateTenantRequest(BaseModel):
    """Create a new tenant."""

    id: str = Field(..., min_length=1, max_length=128, description="Unique tenant identifier")
    display_name: str = Field(default="", max_length=256, description="Human-readable name")
    config: dict[str, Any] = Field(default_factory=dict, description="Non-secret tenant config")

    @field_validator("id")
    @classmethod
    def id_must_be_slug(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError("id must contain only alphanumeric, hyphen, or underscore characters")
        return v


class UpdateTenantRequest(BaseModel):
    """Update an existing tenant (partial)."""

    display_name: str | None = Field(default=None, max_length=256)
    is_active: bool | None = None
    config: dict[str, Any] | None = None

    def has_updates(self) -> bool:
        return any(v is not None for v in (self.display_name, self.is_active, self.config))


class UpsertChannelRequest(BaseModel):
    """Add or update a channel binding for a tenant."""

    provider: str = Field(..., description="Channel provider: meta, telegram, twilio")
    credentials: dict[str, Any] = Field(..., description="Provider credentials (encrypted at rest)")
    config: dict[str, Any] = Field(default_factory=dict, description="Non-secret channel config")

    @field_validator("provider")
    @classmethod
    def provider_must_be_known(cls, v: str) -> str:
        allowed = {"meta", "telegram", "twilio"}
        if v not in allowed:
            raise ValueError(f"provider must be one of {sorted(allowed)}")
        return v

    @field_validator("credentials")
    @classmethod
    def credentials_must_be_nonempty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("credentials must not be empty")
        return v


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class TenantSummary(BaseModel):
    """Lightweight tenant info for list responses."""

    id: str
    display_name: str
    is_active: bool
    channels: list[dict[str, Any]] = Field(default_factory=list)


class TenantDetail(BaseModel):
    """Full tenant info (config redacted, no secrets)."""

    id: str
    display_name: str
    is_active: bool
    config: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None
    channels: list[dict[str, Any]] = Field(default_factory=list)


class OkResponse(BaseModel):
    """Generic success response."""

    ok: bool = True
    tenant_id: str | None = None
    provider: str | None = None
    tenants_loaded: int | None = None
