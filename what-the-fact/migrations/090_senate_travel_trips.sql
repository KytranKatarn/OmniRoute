-- 090_senate_travel_trips.sql — itemized Senate travel, one row per trip leg.
--
-- ⚠️ APPLIES TO CITADEL (what-the-fact-wtf-postgres-1, wtfuser/wtf), NOT the hub. See README.md.
--
-- WHY: parliament.senator_expenses holds one quarterly TOTAL per senator, with travel as a single
-- number (domestic + international + designated travellers together). That cannot answer "how much
-- did senators spend on INTERNATIONAL travel between 2023-01-16 and 2026-03-17" (a National Post /
-- CTF claim, 2026-10-06) because the window needs trip dates and the question needs a destination.
-- The Senate publishes exactly that behind each travel amount in its summary
-- (sencanada.ca/umbraco/surface/ProActiveAjax/GetProActiveData?displayFor=Details&Expense=Travel
--  &MemberId=..&Year=..&Quarter=..): per trip start/end, itinerary, purpose and six cost columns,
-- plus designated travellers (a second person accompanying the senator) and a grand total.
--
-- ONE ROW PER LEG. Designated-traveller legs are kept SEPARATE from the senator's own
-- (traveller_kind) so a figure can be stated either way and never double-counted.
--
-- is_international is deliberately THREE-VALUED: true / false / NULL. NULL means the itinerary has a
-- place the classifier does not recognise (or one that is ambiguous, e.g. "London", "Kingston") and a
-- human has not reviewed it. A claim check must report how many NULLs it had to leave out; it must
-- never count them as domestic.
--
-- senate_travel_checks records, per (senator, quarter), whether the itemized rows add up to the
-- Senate's own grand total AND to the summary figure we already store. A quarter that does not
-- reconcile is a quarter we may have mis-parsed — it is the accuracy audit for this whole feed.
--
-- Rows for a (senator, period) are REPLACED as a set by the ingest (the Senate amends reports),
-- never patched row by row, so UNIQUE(senator_id, period, seq) is positional within that set.
--
-- Re-runnable: IF NOT EXISTS + ON CONFLICT DO NOTHING, like 085-089.

CREATE TABLE IF NOT EXISTS parliament.senate_travel_trips (
    id                bigserial    PRIMARY KEY,
    senator_id        integer      NOT NULL REFERENCES parliament.senators(id) ON DELETE CASCADE,
    period            text         NOT NULL,   -- the Senate's own "<Year>-Q<Quarter>", same label as senator_expenses
    seq               integer      NOT NULL,   -- position within the (senator, period) detail page
    traveller_name    text,
    traveller_kind    text         NOT NULL CHECK (traveller_kind IN ('senator', 'designated', 'other')),
    trip_start        date,
    trip_end          date,
    itinerary         text,
    purpose           text,
    air_bus_train_cad numeric(12,2),
    ground_cad        numeric(12,2),
    per_diem_cad      numeric(12,2),
    accommodation_cad numeric(12,2),
    other_cad         numeric(12,2),
    total_cad         numeric(12,2) NOT NULL,  -- "Total Amount (before tax)" as published
    is_international  boolean,                 -- NULL = unclassified / ambiguous, NOT domestic
    intl_basis        text,                    -- why: 'foreign:Strasbourg', 'canadian', 'unreviewed:Xyzville'
    source_url        text,
    synced_at         timestamptz  NOT NULL DEFAULT now(),
    UNIQUE (senator_id, period, seq)
);

CREATE INDEX IF NOT EXISTS idx_senate_travel_start   ON parliament.senate_travel_trips (trip_start);
CREATE INDEX IF NOT EXISTS idx_senate_travel_intl    ON parliament.senate_travel_trips (is_international, trip_start);
CREATE INDEX IF NOT EXISTS idx_senate_travel_senator ON parliament.senate_travel_trips (senator_id);

CREATE TABLE IF NOT EXISTS parliament.senate_travel_checks (
    senator_id         integer      NOT NULL REFERENCES parliament.senators(id) ON DELETE CASCADE,
    period             text         NOT NULL,
    rows_total_cad     numeric(12,2) NOT NULL,  -- sum of the itemized rows we parsed
    grand_total_cad    numeric(12,2),           -- the Senate's own "Grand Total" line (NULL if absent)
    summary_travel_cad numeric(12,2),           -- the amount on the quarterly summary link
    reconciled         boolean      NOT NULL,   -- rows == grand total (and == summary when both present)
    row_count          integer      NOT NULL,
    checked_at         timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (senator_id, period)
);

-- Apps do not connect as the owner. Conditional so the file still applies where the role does not exist.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wtfuser') THEN
        GRANT ALL ON parliament.senate_travel_trips, parliament.senate_travel_checks TO wtfuser;
        GRANT USAGE, SELECT ON SEQUENCE parliament.senate_travel_trips_id_seq TO wtfuser;
    END IF;
END $$;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('090', '090_senate_travel_trips.sql',
        'Itemized Senate travel (one row per leg) + per-quarter reconciliation against the Senate grand total', now())
ON CONFLICT (version) DO NOTHING;
