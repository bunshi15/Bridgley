# tests/test_tenant_registry.py
"""Tests for tenant registry (v0.8 Multi-Tenant)."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.infra.tenant_registry import (
    TenantContext,
    ChannelBinding,
    get_tenant,
    get_tenant_for_channel,
    get_all_tenants,
    load_tenants,
    reload_tenants,
    reset_cache,
    _build_fallback_cache,
    _cache,
)


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------

class TestTenantContext:
    """Test TenantContext and ChannelBinding dataclasses."""

    def test_tenant_context_creation(self):
        ctx = TenantContext(
            tenant_id="t1",
            display_name="Test",
            is_active=True,
            config={"quota": 100},
            channels={},
        )
        assert ctx.tenant_id == "t1"
        assert ctx.is_active is True
        assert ctx.config == {"quota": 100}

    def test_channel_binding_creation(self):
        binding = ChannelBinding(
            provider="meta",
            credentials={"access_token": "abc"},
            config={"phone_number_id": "123"},
        )
        assert binding.provider == "meta"
        assert binding.credentials["access_token"] == "abc"

    def test_tenant_with_channels(self):
        meta = ChannelBinding("meta", {"token": "x"}, {"pid": "1"})
        tg = ChannelBinding("telegram", {"bot_token": "y"}, {})
        ctx = TenantContext(
            tenant_id="t2",
            display_name="Multi",
            is_active=True,
            config={},
            channels={"meta": meta, "telegram": tg},
        )
        assert len(ctx.channels) == 2
        assert ctx.channels["meta"].credentials["token"] == "x"

    def test_frozen_dataclass(self):
        ctx = TenantContext("t", "T", True, {}, {})
        with pytest.raises(AttributeError):
            ctx.tenant_id = "changed"  # type: ignore


# ---------------------------------------------------------------------------
# Cache lookup tests
# ---------------------------------------------------------------------------

class TestCacheLookup:
    """Test get_tenant, get_tenant_for_channel, get_all_tenants."""

    def setup_method(self):
        reset_cache()
        # Manually populate cache for testing
        import app.infra.tenant_registry as reg
        meta_binding = ChannelBinding("meta", {"access_token": "tok"}, {"pid": "123"})
        reg._cache = {
            "t1": TenantContext("t1", "Tenant 1", True, {}, {"meta": meta_binding}),
            "t2": TenantContext("t2", "Tenant 2", True, {"quota": 50}, {}),
            "t3": TenantContext("t3", "Inactive", False, {}, {}),
        }

    def teardown_method(self):
        reset_cache()

    def test_get_tenant_found(self):
        ctx = get_tenant("t1")
        assert ctx is not None
        assert ctx.tenant_id == "t1"
        assert ctx.display_name == "Tenant 1"

    def test_get_tenant_not_found(self):
        ctx = get_tenant("nonexistent")
        assert ctx is None

    def test_get_tenant_for_channel_found(self):
        binding = get_tenant_for_channel("t1", "meta")
        assert binding is not None
        assert binding.provider == "meta"
        assert binding.credentials["access_token"] == "tok"

    def test_get_tenant_for_channel_wrong_provider(self):
        binding = get_tenant_for_channel("t1", "telegram")
        assert binding is None

    def test_get_tenant_for_channel_wrong_tenant(self):
        binding = get_tenant_for_channel("nonexistent", "meta")
        assert binding is None

    def test_get_all_tenants(self):
        tenants = get_all_tenants()
        assert len(tenants) == 3
        ids = {t.tenant_id for t in tenants}
        assert ids == {"t1", "t2", "t3"}


# ---------------------------------------------------------------------------
# Fallback cache tests
# ---------------------------------------------------------------------------

class TestFallbackCache:
    """Test _build_fallback_cache (settings-based single-tenant)."""

    def test_fallback_meta_provider(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.tenant_id", "my_tenant")
        monkeypatch.setattr("app.config.settings.channel_provider", "meta")
        monkeypatch.setattr("app.config.settings.meta_access_token", "tok123")
        monkeypatch.setattr("app.config.settings.meta_app_secret", "secret")
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "pid1")
        monkeypatch.setattr("app.config.settings.meta_waba_id", "waba1")
        monkeypatch.setattr("app.config.settings.meta_webhook_verify_token", "vt1")
        monkeypatch.setattr("app.config.settings.meta_graph_api_version", "v20.0")

        cache = _build_fallback_cache()
        assert "my_tenant" in cache
        ctx = cache["my_tenant"]
        assert ctx.is_active is True
        assert "meta" in ctx.channels
        assert ctx.channels["meta"].credentials["access_token"] == "tok123"
        assert ctx.channels["meta"].config["phone_number_id"] == "pid1"

    def test_fallback_telegram_provider(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.tenant_id", "tg_tenant")
        monkeypatch.setattr("app.config.settings.channel_provider", "telegram")
        # telegram_channel_token is a property reading telegram_channel_bot_token
        monkeypatch.setattr("app.config.settings.telegram_channel_bot_token", "bot:tok")
        monkeypatch.setattr("app.config.settings.telegram_webhook_secret", "sec")
        monkeypatch.setattr("app.config.settings.telegram_channel_mode", "webhook")

        cache = _build_fallback_cache()
        assert "tg_tenant" in cache
        ctx = cache["tg_tenant"]
        assert "telegram" in ctx.channels
        assert ctx.channels["telegram"].credentials["bot_token"] == "bot:tok"

    def test_fallback_twilio_provider(self, monkeypatch):
        monkeypatch.setattr("app.config.settings.tenant_id", "tw_tenant")
        monkeypatch.setattr("app.config.settings.channel_provider", "twilio")
        monkeypatch.setattr("app.config.settings.twilio_account_sid", "AC123")
        monkeypatch.setattr("app.config.settings.twilio_auth_token", "auth_tok")
        monkeypatch.setattr("app.config.settings.twilio_phone_number", "+1234")
        monkeypatch.setattr("app.config.settings.twilio_webhook_url", "https://example.com")

        cache = _build_fallback_cache()
        ctx = cache["tw_tenant"]
        assert "twilio" in ctx.channels
        assert ctx.channels["twilio"].credentials["account_sid"] == "AC123"


# ---------------------------------------------------------------------------
# load_tenants() tests (DB mocked)
# ---------------------------------------------------------------------------

class TestLoadTenants:
    """Test load_tenants with mocked DB and crypto."""

    def setup_method(self):
        reset_cache()

    def teardown_method(self):
        reset_cache()

    @pytest.mark.asyncio
    async def test_load_falls_back_when_no_encryption_key(self, monkeypatch):
        """When TENANT_ENCRYPTION_KEY is not set, load should use fallback."""
        monkeypatch.setattr("app.config.settings.tenant_encryption_key", None)
        monkeypatch.setattr("app.config.settings.tenant_id", "fallback_t")
        monkeypatch.setattr("app.config.settings.channel_provider", "meta")
        monkeypatch.setattr("app.config.settings.meta_access_token", "tok")
        monkeypatch.setattr("app.config.settings.meta_app_secret", None)
        monkeypatch.setattr("app.config.settings.meta_phone_number_id", "pid")
        monkeypatch.setattr("app.config.settings.meta_waba_id", None)
        monkeypatch.setattr("app.config.settings.meta_webhook_verify_token", "vt")
        monkeypatch.setattr("app.config.settings.meta_graph_api_version", "v20.0")

        # Reset crypto singleton too
        from app.infra.crypto import reset_crypto
        reset_crypto()

        count = await load_tenants()
        assert count == 1
        assert get_tenant("fallback_t") is not None

    @pytest.mark.asyncio
    async def test_reload_delegates_to_load(self, monkeypatch):
        """reload_tenants should call load_tenants."""
        monkeypatch.setattr("app.config.settings.tenant_encryption_key", None)
        monkeypatch.setattr("app.config.settings.tenant_id", "rel_t")
        monkeypatch.setattr("app.config.settings.channel_provider", "telegram")
        monkeypatch.setattr("app.config.settings.telegram_channel_bot_token", "tok")
        monkeypatch.setattr("app.config.settings.telegram_webhook_secret", None)
        monkeypatch.setattr("app.config.settings.telegram_channel_mode", "polling")

        from app.infra.crypto import reset_crypto
        reset_crypto()

        count = await reload_tenants()
        assert count >= 1


# ---------------------------------------------------------------------------
# Meta sender credential override integration
# ---------------------------------------------------------------------------

class TestMetaSenderOverride:
    """Test that meta_sender accepts credential overrides."""

    def test_graph_url_override(self):
        from app.transport.meta_sender import _graph_url
        url = _graph_url("123/messages", graph_api_version="v19.0")
        assert "v19.0" in url
        assert "123/messages" in url

    def test_graph_url_default(self):
        from app.transport.meta_sender import _graph_url
        url = _graph_url("456/messages")
        # Should use settings default
        assert "456/messages" in url

    def test_auth_headers_override(self):
        from app.transport.meta_sender import _auth_headers
        headers = _auth_headers(access_token="override_tok")
        assert headers["Authorization"] == "Bearer override_tok"

    def test_auth_headers_default(self):
        from app.transport.meta_sender import _auth_headers
        headers = _auth_headers()
        # Should use settings default (may be None in test env)
        assert "Authorization" in headers


# ---------------------------------------------------------------------------
# get_operator_config() tests (v0.8.1)
# ---------------------------------------------------------------------------

class TestGetOperatorConfig:
    """Test per-tenant operator notification config resolution."""

    def setup_method(self):
        reset_cache()

    def teardown_method(self):
        reset_cache()

    def test_none_tenant_uses_global_settings(self, monkeypatch):
        """tenant_id=None → all values from settings.*"""
        from app.infra.tenant_registry import get_operator_config

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+79990001122")

        result = get_operator_config(None)
        assert result["enabled"] is True
        assert result["channel"] == "whatsapp"
        assert result["operator_whatsapp"] == "+79990001122"

    def test_tenant_with_full_override(self, monkeypatch):
        """Tenant config overrides all operator settings."""
        from app.infra.tenant_registry import get_operator_config
        import app.infra.tenant_registry as reg

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+79990001122")

        reg._cache = {
            "t_custom": TenantContext(
                "t_custom", "Custom", True,
                config={
                    "operator_notifications_enabled": False,
                    "operator_notification_channel": "telegram",
                    "operator_whatsapp": "+79998887766",
                },
            ),
        }

        result = get_operator_config("t_custom")
        assert result["enabled"] is False
        assert result["channel"] == "telegram"
        assert result["operator_whatsapp"] == "+79998887766"

    def test_tenant_with_partial_override(self, monkeypatch):
        """Tenant overrides operator_whatsapp only; rest falls back to settings.*"""
        from app.infra.tenant_registry import get_operator_config
        import app.infra.tenant_registry as reg

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "whatsapp")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+79990001122")

        reg._cache = {
            "t_partial": TenantContext(
                "t_partial", "Partial", True,
                config={"operator_whatsapp": "+79991112233"},
            ),
        }

        result = get_operator_config("t_partial")
        assert result["enabled"] is True  # from settings
        assert result["channel"] == "whatsapp"  # from settings
        assert result["operator_whatsapp"] == "+79991112233"  # from tenant

    def test_tenant_not_in_cache_uses_global(self, monkeypatch):
        """Unknown tenant_id → falls back to settings.*"""
        from app.infra.tenant_registry import get_operator_config

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", False)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "email")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "")

        result = get_operator_config("nonexistent_tenant")
        assert result["enabled"] is False
        assert result["channel"] == "email"

    def test_tenant_with_empty_config(self, monkeypatch):
        """Tenant exists but config is empty → falls back to settings.*"""
        from app.infra.tenant_registry import get_operator_config
        import app.infra.tenant_registry as reg

        monkeypatch.setattr("app.config.settings.operator_notifications_enabled", True)
        monkeypatch.setattr("app.config.settings.operator_notification_channel", "telegram")
        monkeypatch.setattr("app.config.settings.operator_whatsapp", "+79990001122")

        reg._cache = {
            "t_empty": TenantContext("t_empty", "Empty", True, config={}),
        }

        result = get_operator_config("t_empty")
        assert result["enabled"] is True
        assert result["channel"] == "telegram"
        assert result["operator_whatsapp"] == "+79990001122"
