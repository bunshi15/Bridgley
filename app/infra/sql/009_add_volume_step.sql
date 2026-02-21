-- 009_add_volume_step.sql
-- Phase 9: add volume category step between cargo and pickup_count

ALTER TABLE sessions DROP CONSTRAINT IF EXISTS chk_sessions_step;

ALTER TABLE sessions
  ADD CONSTRAINT chk_sessions_step
  CHECK (step IN (
    'welcome','cargo',
    'volume',                                              -- Phase 9
    'pickup_count',                                        -- Phase 4
    'addr_from','floor_from',
    'addr_from_2','floor_from_2',                          -- Phase 4
    'addr_from_3','floor_from_3',                          -- Phase 4
    'addr_to','floor_to',
    'addresses',  -- legacy (pre-Phase 1)
    'time',       -- legacy (pre-Phase 2)
    'date','specific_date','time_slot','exact_time',       -- Phase 2
    'photo_menu','photo_wait','extras',
    'estimate',                                            -- Phase 3
    'done'
  ));
