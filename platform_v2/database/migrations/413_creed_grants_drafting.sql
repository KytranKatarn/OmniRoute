-- Migration 413: grant drafting + deadline reminders (task #3612)
--
-- Adds E.T.H.O.S. draft storage + a reminder-dedup timestamp to creed_grants.
-- draft            : the latest E.T.H.O.S.-drafted application narrative
-- draft_generated_at: when it was drafted
-- last_reminder_at : last time a deadline reminder fired (dedup for the daily job)

ALTER TABLE creed_grants ADD COLUMN IF NOT EXISTS draft TEXT;
ALTER TABLE creed_grants ADD COLUMN IF NOT EXISTS draft_generated_at TIMESTAMPTZ;
ALTER TABLE creed_grants ADD COLUMN IF NOT EXISTS last_reminder_at TIMESTAMPTZ;
