-- Migration 006: Multi-Tenant Foundation
-- Adds tenants table and channel_bindings table for multi-tenant support.
-- Credentials are stored encrypted (Fernet) in channel_bindings.credentials_enc.

CREATE TABLE IF NOT EXISTS tenants (
    id            text        PRIMARY KEY,                -- e.g. "investor_01"
    display_name  text        NOT NULL DEFAULT '',
    is_active     boolean     NOT NULL DEFAULT true,
    config_json   jsonb       NOT NULL DEFAULT '{}',      -- quotas, feature flags, notification prefs
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS channel_bindings (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           text        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    provider            text        NOT NULL,                  -- 'meta', 'telegram', 'twilio'
    provider_account_id text        NOT NULL DEFAULT '',       -- e.g. phone_number_id, bot_id, twilio_number
    credentials_enc     bytea       NOT NULL,                  -- Fernet-encrypted JSON blob
    config_json         jsonb       NOT NULL DEFAULT '{}',     -- phone_number_id, graph_api_version, etc.
    is_active           boolean     NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_channel_bindings_tenant_provider UNIQUE (tenant_id, provider),
    CONSTRAINT chk_channel_bindings_provider CHECK (provider IN ('meta', 'telegram', 'twilio'))
);

-- Prevent the same provider account from being bound to multiple tenants
CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_bindings_provider_account
    ON channel_bindings (provider, provider_account_id)
    WHERE provider_account_id != '' AND is_active = true;

-- Index for looking up active bindings by tenant
CREATE INDEX IF NOT EXISTS idx_channel_bindings_tenant
    ON channel_bindings (tenant_id) WHERE is_active = true;

-- Seed the default tenant (backward compatibility with single-tenant deployments)
INSERT INTO tenants (id, display_name, is_active)
VALUES ('default', 'Default Tenant', true)
ON CONFLICT DO NOTHING;
