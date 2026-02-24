-- 011_add_media_assets_table.sql
-- Generic media assets table for photos, videos, audio, documents.
-- Part of EPIC G: Secure Media Intake + Optimized Operator Delivery.

CREATE TABLE IF NOT EXISTS media_assets (
  id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id           text        NOT NULL,
  lead_id             text        NULL,
  chat_id             text        NOT NULL,
  provider            text        NOT NULL,
  message_id          text        NULL,
  kind                text        NOT NULL,   -- 'image', 'video', 'audio', 'document'
  content_type        text        NOT NULL,
  size_bytes          integer     NOT NULL,
  filename            text        NOT NULL,   -- UUID-based
  s3_key              text        NOT NULL,
  expires_at          timestamptz NULL,
  -- G5: future transcription hook (nullable placeholders)
  transcript_text     text        NULL,
  transcript_status   text        NULL,
  transcript_provider text        NULL,
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_media_assets_tenant_lead ON media_assets(tenant_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_tenant_chat ON media_assets(tenant_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_expires ON media_assets(expires_at) WHERE expires_at IS NOT NULL;
