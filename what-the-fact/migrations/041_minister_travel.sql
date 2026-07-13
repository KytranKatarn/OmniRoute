-- Migration 041: Ministerial (departmental) travel & hospitality — the cost borne CENTRALLY
-- Project #348 / "What Parliament Costs Canadians".
--   parliament.mp_expenses covers a member's HOUSE OF COMMONS office budget. It does NOT
--   include a cabinet minister's DEPARTMENTAL travel (government aircraft, official trips) or
--   hospitality — those are borne by the department/PCO and disclosed separately under the
--   federal proactive-publication regime, NOT against the MP budget. That is exactly why the
--   PM shows ~$0 travel in mp_expenses: his official travel never touches his MP office budget.
--
--   This table holds that missing ministerial piece, matched to the minister's parliament.mps
--   row, so a cabinet minister's cost can be shown as MP-budget PLUS the centrally-borne
--   ministerial travel/hospitality (clearly labelled as a separate, floor-lifting line).
--
-- Source: open.canada.ca TBS proactive disclosure —
--   Travel      dataset 009f9a49-c2d9-4d29-a6d4-1a228da335ce (travelq.csv, ~70MB)
--   Hospitality dataset b9f51ef4-4605-4ef2-8231-62a2edda1b54 (hospitalityq.csv, ~28MB)
--   ingest/parliament/minister_travel.py streams both (CKAN-resolved URLs), matches `name`
--   to parliament.mps, aggregates itemized trips/events to the fiscal quarter, and upserts here.
-- Run: psql $WTF_DATABASE_URL < 041_minister_travel.sql   (idempotent)

CREATE TABLE IF NOT EXISTS parliament.minister_travel (
    id               BIGSERIAL PRIMARY KEY,
    mp_id            INTEGER REFERENCES parliament.mps(id) ON DELETE CASCADE,
    period           TEXT NOT NULL,          -- 'YYYY-Qn' (SAME fiscal-quarter key as mp_expenses)
    travel_cad       NUMERIC DEFAULT 0,      -- sum of disclosed travel 'total' in the quarter
    hospitality_cad  NUMERIC DEFAULT 0,      -- sum of disclosed hospitality 'total' in the quarter
    total_cad        NUMERIC DEFAULT 0,      -- travel + hospitality
    trips            INTEGER DEFAULT 0,      -- # travel disclosures in the quarter
    events           INTEGER DEFAULT 0,      -- # hospitality disclosures in the quarter
    title            TEXT,                   -- ministerial title_en at the time (most recent seen)
    owner_org        TEXT,                   -- disclosing department (owner_org_title)
    source           TEXT DEFAULT 'open.canada.ca proactive disclosure (travel + hospitality)',
    synced_at        TIMESTAMPTZ DEFAULT now(),
    UNIQUE (mp_id, period)
);

CREATE INDEX IF NOT EXISTS ix_minister_travel_mp     ON parliament.minister_travel (mp_id);
CREATE INDEX IF NOT EXISTS ix_minister_travel_period ON parliament.minister_travel (period);

-- The wtf-ingest app connects as `wtfuser` (not the table owner), so a NEW table MUST grant to
-- wtfuser or the ingest aborts with "permission denied" (KB #280976).
-- LEAST PRIVILEGE: the ingest UPSERTs, so it needs INSERT + UPDATE + SELECT — but NEVER
-- DELETE/TRUNCATE (a public financial record must not be erasable by a bug or compromise).
-- The REVOKE self-heals any DB that previously received a broader grant. Idempotent.
REVOKE DELETE, TRUNCATE ON parliament.minister_travel FROM wtfuser;
GRANT SELECT, INSERT, UPDATE ON parliament.minister_travel TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE parliament.minister_travel_id_seq TO wtfuser;
