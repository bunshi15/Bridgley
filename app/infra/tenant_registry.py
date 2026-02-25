# app/infra/tenant_registry.py
"""
In-memory tenant registry loaded from the DB at startup.

Provides fast, lock-free lookups of tenant config and decrypted channel
credentials.  The cache is refreshed by calling ``reload_tenants()``
(typically from an admin endpoint).

Backward compatibility:
- If no tenants exist in the DB (or TENANT_ENCRYPTION_KEY is not set),
  a synthetic ``TenantContext`` is built from ``settings.*`` so the
  single-tenant deployment path keeps working unchanged.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.infra.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChannelBinding:
    """Decrypted channel binding for one provider."""
    provider: str           # "meta" / "telegram" / "twilio"
    credentials: dict       # decrypted credentials (access_token, bot_token, …)
    config: dict            # non-secret config (phone_number_id, graph_api_version, …)


@dataclass(frozen=True)
class TenantContext:
    """Immutable snapshot of a tenant's configuration."""
    tenant_id: str
    display_name: str
    is_active: bool
    config: dict                                          # quotas, feature flags
    channels: dict[str, ChannelBinding] = field(default_factory=dict)  # keyed by provider


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, TenantContext] = {}


def get_tenant(tenant_id: str) -> TenantContext | None:
    """
    Look up a tenant by ID (from in-memory cache).

    Returns None if the tenant is not found.
    """
    return _cache.get(tenant_id)


def get_tenant_for_channel(tenant_id: str, provider: str) -> ChannelBinding | None:
    """
    Convenience: look up a specific channel binding for a tenant.

    Returns None if the tenant or the provider binding is not found.
    """
    ctx = _cache.get(tenant_id)
    if ctx is None:
        return None
    return ctx.channels.get(provider)


def get_all_tenants() -> list[TenantContext]:
    """Return all cached tenants (for admin listing)."""
    return list(_cache.values())


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

async def load_tenants() -> int:
    """
    Load all active tenants + their channel bindings from the DB.

    Decrypts credentials using ``get_crypto()``.  If the encryption key
    is not configured, falls back to synthesizing a single tenant from
    ``settings.*``.

    Returns the number of tenants loaded into cache.
    """
    global _cache

    try:
        from app.infra.crypto import get_crypto, CryptoNotConfiguredError

        try:
            crypto = get_crypto()
        except CryptoNotConfiguredError:
            logger.info("TENANT_ENCRYPTION_KEY not set — using settings-based fallback tenant")
            _cache = _build_fallback_cache()
            return len(_cache)

        from app.infra.db_resilience_async import safe_db_conn

        new_cache: dict[str, TenantContext] = {}

        async with safe_db_conn() as conn:
            # Load tenants
            tenant_rows = await conn.fetch(
                "SELECT id, display_name, is_active, config_json FROM tenants WHERE is_active = true"
            )

            if not tenant_rows:
                logger.info("No active tenants in DB — using settings-based fallback tenant")
                _cache = _build_fallback_cache()
                return len(_cache)

            # Load all active bindings
            # NOTE: only select columns actually used by the cache builder.
            # provider_account_id is NOT selected — it may be absent in
            # databases created before migration 006 added the column,
            # and it is not needed for runtime lookups.
            binding_rows = await conn.fetch(
                """
                SELECT cb.tenant_id, cb.provider,
                       cb.credentials_enc, cb.config_json
                FROM channel_bindings cb
                JOIN tenants t ON t.id = cb.tenant_id
                WHERE cb.is_active = true AND t.is_active = true
                """
            )

        # Index bindings by tenant
        bindings_by_tenant: dict[str, list[dict]] = {}
        for row in binding_rows:
            tid = row["tenant_id"]
            bindings_by_tenant.setdefault(tid, []).append(row)

        # Build TenantContext for each tenant
        for trow in tenant_rows:
            tid = trow["id"]
            channels: dict[str, ChannelBinding] = {}

            for brow in bindings_by_tenant.get(tid, []):
                try:
                    # Use context-bound decryption (anti-replay).
                    # Falls back to plain decrypt for credentials encrypted
                    # before context binding was added (backward compat).
                    from app.infra.crypto import CryptoContextMismatchError
                    raw_bytes = bytes(brow["credentials_enc"])
                    try:
                        creds = crypto.decrypt_bound(
                            raw_bytes,
                            tenant_id=tid,
                            provider=brow["provider"],
                        )
                    except CryptoContextMismatchError:
                        # Context fields absent or mismatched → legacy encryption
                        logger.warning(
                            f"Legacy (unbound) credentials for tenant={tid}, "
                            f"provider={brow['provider']} — re-encrypt via admin API"
                        )
                        creds = crypto.decrypt(raw_bytes)
                except Exception as exc:
                    logger.error(
                        f"Failed to decrypt credentials for tenant={tid}, "
                        f"provider={brow['provider']}: {exc}"
                    )
                    continue  # skip this binding, don't crash

                config_raw = brow["config_json"]
                config = config_raw if isinstance(config_raw, dict) else json.loads(config_raw)

                channels[brow["provider"]] = ChannelBinding(
                    provider=brow["provider"],
                    credentials=creds,
                    config=config,
                )

            tenant_config_raw = trow["config_json"]
            tenant_config = (
                tenant_config_raw
                if isinstance(tenant_config_raw, dict)
                else json.loads(tenant_config_raw)
            )

            new_cache[tid] = TenantContext(
                tenant_id=tid,
                display_name=trow["display_name"],
                is_active=trow["is_active"],
                config=tenant_config,
                channels=channels,
            )

        _cache = new_cache
        logger.info(f"Tenant registry loaded: {len(_cache)} tenants, {sum(len(t.channels) for t in _cache.values())} bindings")
        return len(_cache)

    except Exception as exc:
        logger.error(f"Failed to load tenant registry: {exc}", exc_info=True)
        # If cache was previously populated, keep it (stale > empty)
        if _cache:
            logger.warning("Keeping stale tenant cache after reload failure")
        else:
            _cache = _build_fallback_cache()
        return len(_cache)


async def reload_tenants() -> int:
    """Refresh the in-memory cache from DB. Returns count of tenants loaded."""
    return await load_tenants()


# ---------------------------------------------------------------------------
# Fallback: synthesize a TenantContext from settings.*
# ---------------------------------------------------------------------------

def _build_fallback_cache() -> dict[str, TenantContext]:
    """
    Build a single-tenant cache from app settings.

    Used when TENANT_ENCRYPTION_KEY is not configured or no tenants
    exist in the DB.  This keeps single-tenant deployments working
    without any multi-tenant setup.
    """
    from app.config import settings

    # Build a pseudo-ChannelBinding from settings for the active provider
    channels: dict[str, ChannelBinding] = {}
    provider = settings.channel_provider

    if provider == "meta" and settings.meta_access_token:
        channels["meta"] = ChannelBinding(
            provider="meta",
            credentials={
                "access_token": settings.meta_access_token,
                "app_secret": settings.meta_app_secret or "",
            },
            config={
                "phone_number_id": settings.meta_phone_number_id or "",
                "waba_id": settings.meta_waba_id or "",
                "webhook_verify_token": settings.meta_webhook_verify_token or "",
                "graph_api_version": settings.meta_graph_api_version,
            },
        )
    elif provider == "telegram" and settings.telegram_channel_token:
        channels["telegram"] = ChannelBinding(
            provider="telegram",
            credentials={
                "bot_token": settings.telegram_channel_token,
                "webhook_secret": settings.telegram_webhook_secret or "",
            },
            config={
                "channel_mode": settings.telegram_channel_mode,
            },
        )
    elif provider == "twilio" and settings.twilio_account_sid:
        channels["twilio"] = ChannelBinding(
            provider="twilio",
            credentials={
                "account_sid": settings.twilio_account_sid,
                "auth_token": settings.twilio_auth_token or "",
            },
            config={
                "phone_number": settings.twilio_phone_number or "",
                "webhook_url": settings.twilio_webhook_url or "",
            },
        )

    tenant_id = settings.tenant_id
    cache = {
        tenant_id: TenantContext(
            tenant_id=tenant_id,
            display_name="Default (from settings)",
            is_active=True,
            config={},
            channels=channels,
        )
    }

    logger.info(f"Fallback tenant cache built: tenant={tenant_id}, channels={list(channels.keys())}")
    return cache


# ---------------------------------------------------------------------------
# Operator config resolution (v0.8.1)
# ---------------------------------------------------------------------------

def get_operator_config(tenant_id: str | None) -> dict:
    """
    Resolve operator notification config for a tenant.

    Checks the tenant's ``config`` dict first; falls back to
    ``settings.*`` for any key not present.

    Returns::

        {
            "enabled": bool,
            "channel": "whatsapp" | "telegram" | "email",
            "operator_whatsapp": str | None,
            "operator_whatsapp_provider": "twilio" | "meta",
            "twilio_content_sid": str | None,
        }
    """
    from app.config import settings

    # Defaults from global settings
    enabled = settings.operator_notifications_enabled
    channel = settings.operator_notification_channel
    operator_whatsapp = settings.operator_whatsapp
    operator_whatsapp_provider = settings.operator_whatsapp_provider
    twilio_content_sid = settings.twilio_content_sid

    if tenant_id is not None:
        ctx = _cache.get(tenant_id)
        if ctx is not None:
            cfg = ctx.config
            if "operator_notifications_enabled" in cfg:
                enabled = bool(cfg["operator_notifications_enabled"])
            if "operator_notification_channel" in cfg:
                channel = str(cfg["operator_notification_channel"])
            if "operator_whatsapp" in cfg:
                operator_whatsapp = str(cfg["operator_whatsapp"]) or operator_whatsapp
            if "operator_whatsapp_provider" in cfg:
                operator_whatsapp_provider = str(cfg["operator_whatsapp_provider"])
            if "twilio_content_sid" in cfg:
                twilio_content_sid = str(cfg["twilio_content_sid"])

    return {
        "enabled": enabled,
        "channel": channel,
        "operator_whatsapp": operator_whatsapp,
        "operator_whatsapp_provider": operator_whatsapp_provider,
        "twilio_content_sid": twilio_content_sid,
    }


def get_dispatch_config(tenant_id: str | None) -> dict:
    """
    Resolve dispatch layer config for a tenant.

    Checks the tenant's ``config`` dict first; falls back to
    ``settings.*`` for any key not present.

    Returns::

        {
            "crew_fallback_enabled": bool,
        }
    """
    from app.config import settings

    crew_fallback_enabled = settings.dispatch_crew_fallback_enabled

    if tenant_id is not None:
        ctx = _cache.get(tenant_id)
        if ctx is not None:
            cfg = ctx.config
            if "dispatch_crew_fallback_enabled" in cfg:
                crew_fallback_enabled = bool(cfg["dispatch_crew_fallback_enabled"])

    return {
        "crew_fallback_enabled": crew_fallback_enabled,
    }


def reset_cache() -> None:
    """Reset the tenant cache (for testing)."""
    global _cache
    _cache = {}
