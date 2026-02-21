-- 002_add_leads_updated_at.sql
-- Add updated_at column to leads table for upsert support

ALTER TABLE leads ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_leads_updated_at ON leads(updated_at);
