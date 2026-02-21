-- 005_add_jobs_table.sql
-- DB-backed job queue for reliable background processing (v0.7)
--
-- Replaces asyncio.create_task() fire-and-forget with persistent,
-- retryable jobs: outbound replies, media processing, operator notifications.

CREATE TABLE IF NOT EXISTS jobs (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      text        NOT NULL,
  job_type       text        NOT NULL,
  payload        jsonb       NOT NULL,
  status         text        NOT NULL DEFAULT 'pending',
  priority       smallint    NOT NULL DEFAULT 0,
  attempts       smallint    NOT NULL DEFAULT 0,
  max_attempts   smallint    NOT NULL DEFAULT 5,
  error_message  text        NULL,
  scheduled_at   timestamptz NOT NULL DEFAULT now(),
  created_at     timestamptz NOT NULL DEFAULT now(),
  started_at     timestamptz NULL,
  completed_at   timestamptz NULL,

  CONSTRAINT chk_jobs_status
    CHECK (status IN ('pending', 'running', 'completed', 'failed'))
);

-- Primary polling query: fetch due pending jobs ordered by priority then age
-- Partial index keeps this near-zero cost when no pending jobs exist
CREATE INDEX IF NOT EXISTS idx_jobs_poll
  ON jobs (scheduled_at, priority, created_at)
  WHERE status = 'pending';

-- Admin/monitoring: find failed or running jobs
CREATE INDEX IF NOT EXISTS idx_jobs_status_created
  ON jobs (status, created_at DESC);

-- Cleanup: find old completed jobs for TTL purge
CREATE INDEX IF NOT EXISTS idx_jobs_completed_at
  ON jobs (completed_at)
  WHERE status = 'completed';

-- Per-tenant monitoring
CREATE INDEX IF NOT EXISTS idx_jobs_tenant_status
  ON jobs (tenant_id, status);
