-- 001_init.sql

CREATE TABLE IF NOT EXISTS sessions (
  tenant_id      text        NOT NULL,
  chat_id        text        NOT NULL,
  state_json     jsonb       NOT NULL,
  step           text        NOT NULL,
  updated_at     timestamptz NOT NULL DEFAULT now(),
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
  ON sessions (updated_at);

CREATE TABLE IF NOT EXISTS leads (
  tenant_id      text        NOT NULL,
  lead_id        text        NOT NULL,
  chat_id        text        NOT NULL,
  status 		 text 		 NOT NULL DEFAULT 'new',
  payload_json   jsonb       NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at 	 timestamptz NULL,
  PRIMARY KEY (tenant_id, lead_id)
);

CREATE INDEX IF NOT EXISTS idx_leads_created_at
  ON leads (created_at);

-- Для идемпотентности: Twilio иногда ретраит вебхуки, чтобы не обработать один и тот же вход дважды
CREATE TABLE IF NOT EXISTS inbound_messages (
  tenant_id      text        NOT NULL,
  provider       text        NOT NULL,
  message_id     text        NOT NULL,
  chat_id        text        NOT NULL,
  received_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, provider, message_id)
);

-- Add constraint only if it doesn't exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_sessions_step'
  ) THEN
    ALTER TABLE sessions
      ADD CONSTRAINT chk_sessions_step
      CHECK (step IN ('welcome','cargo','addresses','time','photo_menu','photo_wait','extras','done'));
  END IF;
END $$;

-- Add constraint only if it doesn't exist
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_leads_status'
  ) THEN
    ALTER TABLE leads
      ADD CONSTRAINT chk_leads_status
      CHECK (status IN ('new','in_progress','done','rejected'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_leads_status_created_at ON leads(status, created_at DESC);
