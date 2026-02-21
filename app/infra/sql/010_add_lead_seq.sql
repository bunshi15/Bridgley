-- 010_add_lead_seq.sql
-- Dispatch Layer: add sequential lead number for human-readable job IDs.
-- Shared across tenants — all moving_bot_v1 leads get a global sequence.

-- Use a BIGSERIAL column (auto-increment, never gaps in normal operation).
ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_seq BIGSERIAL;

-- Index for fast "next number" lookups (optional, SERIAL handles this)
CREATE INDEX IF NOT EXISTS idx_leads_seq ON leads (lead_seq);
