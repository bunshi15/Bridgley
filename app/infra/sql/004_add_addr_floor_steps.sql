-- 004_add_addr_floor_steps.sql
-- Split "addresses" step into addr_from, floor_from, addr_to, floor_to

-- Drop old constraint and re-create with new step values
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS chk_sessions_step;

ALTER TABLE sessions
  ADD CONSTRAINT chk_sessions_step
  CHECK (step IN (
    'welcome','cargo',
    'addr_from','floor_from','addr_to','floor_to',
    'addresses',  -- keep old value for backward compat with existing sessions
    'time','photo_menu','photo_wait','extras','done'
  ));
