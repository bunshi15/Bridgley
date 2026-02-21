-- 007_add_scheduling_and_estimate_steps.sql
-- Phase 2: add structured scheduling steps (date, specific_date, time_slot, exact_time)
-- Phase 3: add estimate step (pricing confirmation before done)

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS chk_sessions_step;

ALTER TABLE sessions
  ADD CONSTRAINT chk_sessions_step
  CHECK (step IN (
    'welcome','cargo',
    'addr_from','floor_from','addr_to','floor_to',
    'addresses',  -- legacy (pre-Phase 1)
    'time',       -- legacy (pre-Phase 2)
    'date','specific_date','time_slot','exact_time',  -- Phase 2
    'photo_menu','photo_wait','extras',
    'estimate',   -- Phase 3
    'done'
  ));
