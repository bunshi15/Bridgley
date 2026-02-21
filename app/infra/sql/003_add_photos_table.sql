-- 003_add_photos_table.sql
-- Store photos with S3 or database storage

CREATE TABLE IF NOT EXISTS photos (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      text        NOT NULL,
  lead_id        text        NULL,           -- Linked to lead when finalized
  chat_id        text        NOT NULL,
  filename       text        NOT NULL,       -- UUID.ext
  content_type   text        NOT NULL,       -- image/jpeg, etc.
  size_bytes     integer     NOT NULL,
  width          integer     NOT NULL,
  height         integer     NOT NULL,
  s3_url         text        NULL,           -- S3 public URL (when using S3 storage)
  data           bytea       NULL,           -- Image binary data (when using DB storage)
  created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_photos_tenant_chat ON photos(tenant_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_photos_tenant_lead ON photos(tenant_id, lead_id);
CREATE INDEX IF NOT EXISTS idx_photos_created_at ON photos(created_at);
