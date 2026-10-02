-- 087_election_calendar_derived.sql — rule-derived ("projected") calendar dates.
-- derived_at is set by ingest/elections/calendar.py when it computes next_latest_date
-- from a fixed-date statute rule. verified_at is untouched: a projection is NOT a
-- verification, and the page labels it so.
ALTER TABLE parliament.election_calendar ADD COLUMN IF NOT EXISTS derived_at timestamptz;
