-- Migration 040: Senate of Canada — senators' quarterly expenditures
-- Project #348 / "What Parliament Costs Canadians" Phase 2.
--   WTF already has parliament.mp_expenses (House proactive disclosure) but had
--   NO senator expense data.  The Senate publishes senators' expenditures
--   quarterly on sencanada.ca (Public Disclosure → Quarterly Expenditure
--   Reports).  ingest/parliament/senator_expenses.py fetches + parses those
--   reports and upserts here, matched to parliament.senators by name.
-- Run: psql $WTF_DATABASE_URL < 040_senator_expenses.sql   (idempotent)
--
-- Source columns (per-senator, per quarter) from the Senate summary table:
--   Office / Living / Hospitality / Travel Expenses (all $ amounts) +
--   Contract(s) Awarded (a "Details" drill-down link, NOT a summary $ figure).
-- Mirrors parliament.mp_expenses (mp_id, period, travel/hospitality/contracts/
-- salaries/total_cad).  NOTE: the Senate breaks out LIVING expenses separately
-- from Office (living allowance for the National Capital Region residence — a
-- material ~$4k-$10k/quarter/senator).  Folding it into office_cad would
-- misrepresent the Office figure, so living_cad is its own column and total_cad
-- is the sum of ALL components.  contracts_cad is NULL when the amount is only
-- available behind the per-senator "Details" drill-down (deferred to a later
-- pass); "N/A" (no contracts) is recorded as 0.00.

CREATE TABLE IF NOT EXISTS parliament.senator_expenses (
    id               BIGSERIAL PRIMARY KEY,
    senator_id       BIGINT REFERENCES parliament.senators(id) ON DELETE CASCADE,
    period           TEXT NOT NULL,          -- 'YYYY-Qn' (mirrors mp_expenses)
    travel_cad       NUMERIC,
    hospitality_cad  NUMERIC,
    contracts_cad    NUMERIC,                -- NULL = amount behind "Details" drill-down; 0 = "N/A"
    office_cad       NUMERIC,
    living_cad       NUMERIC,                -- Senate "Living Expenses" (NCR residence allowance)
    total_cad        NUMERIC,                -- office + living + hospitality + travel + COALESCE(contracts,0)
    source_url       TEXT,
    synced_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE (senator_id, period)
);

CREATE INDEX IF NOT EXISTS ix_senator_expenses_senator ON parliament.senator_expenses (senator_id);
CREATE INDEX IF NOT EXISTS ix_senator_expenses_period  ON parliament.senator_expenses (period);

-- The wtf-ingest app connects as `wtfuser` (not the table owner), so a NEW table
-- MUST grant to wtfuser or the ingest aborts with "permission denied for table
-- senator_expenses" (KB #280976).
--
-- LEAST PRIVILEGE: the ingest UPSERTs (INSERT ... ON CONFLICT DO UPDATE), so it
-- needs INSERT + UPDATE + SELECT — but NEVER DELETE/TRUNCATE (it never removes a
-- disclosed figure; a bug or compromise must not be able to erase the public
-- financial record).  The REVOKE self-heals any DB that previously received a
-- broader grant.  Idempotent.
REVOKE DELETE, TRUNCATE ON parliament.senator_expenses FROM wtfuser;
GRANT SELECT, INSERT, UPDATE ON parliament.senator_expenses TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE parliament.senator_expenses_id_seq TO wtfuser;
