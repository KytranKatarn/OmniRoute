-- 082_aurora_aqhi_alerts.sql
-- A.U.R.O.R.A. weather: AQHI layer + EC alerts (Dev HQ #6621 item 5).
-- Both confirmed live against dd.weather.gc.ca 2026-09-06 (ADR-001 host, same
-- dated-directory pattern as ingest/weather/citypage.py and cwfis.py).

-- AQHI observations. Per-station GeoJSON points, no province in the payload
-- itself (the 5 region codes — atl/ont/pnr/pyr/que — are meteorological
-- super-regions, not provinces; deliberately NOT mapped to a province here to
-- avoid fabricating a code this feed does not provide). Plotted by lat/lon
-- only, same as a city-observation pin.
CREATE TABLE IF NOT EXISTS wtf.aurora_aqhi_obs (
    id                  SERIAL PRIMARY KEY,
    location_id         TEXT NOT NULL,
    location_name       TEXT,
    region              TEXT NOT NULL,   -- atl/ont/pnr/pyr/que (Datamart region, not a province)
    lat                 DOUBLE PRECISION,
    lon                 DOUBLE PRECISION,
    aqhi_value          NUMERIC(4,2),
    observed_utc        TIMESTAMPTZ NOT NULL,
    source_file         TEXT,
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (location_id, observed_utc)
);
CREATE INDEX IF NOT EXISTS idx_aurora_aqhi_obs_time ON wtf.aurora_aqhi_obs(observed_utc DESC);

-- EC public alerts (CAP 1.2). office_code is an ECCC weather-office code
-- (e.g. CWHX, CWWG) — NOT a province code; the real geographic scope per
-- alert lives in coverage_name (the CAP "Alert_Coverage" parameter, a plain
-- English province/region name) and area_desc (a finer county/zone name).
-- Neither is canonicalised against _canon_prov's 2-letter codes — they are
-- free-text from the source and displayed as-is, not bucketed into a choropleth.
CREATE TABLE IF NOT EXISTS wtf.aurora_alerts (
    id                  SERIAL PRIMARY KEY,
    identifier          TEXT NOT NULL UNIQUE,   -- CAP <identifier>, globally unique per alert
    office_code         TEXT NOT NULL,
    status              TEXT,       -- Actual/Exercise/Test/Draft
    msg_type            TEXT,       -- Alert/Update/Cancel/Ack/Error
    event               TEXT,
    urgency             TEXT,
    severity            TEXT,
    certainty           TEXT,
    headline            TEXT,
    description         TEXT,
    coverage_name       TEXT,       -- Alert_Coverage parameter, e.g. "Nova Scotia"
    area_desc           TEXT,       -- <area><areaDesc>, e.g. "Victoria County"
    location_status     TEXT,       -- Alert_Location_Status parameter: e.g. "ended", "in effect"
    sent_utc            TIMESTAMPTZ,
    effective_utc       TIMESTAMPTZ,
    expires_utc         TIMESTAMPTZ,
    source_file         TEXT,
    fetched_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_aurora_alerts_sent ON wtf.aurora_alerts(sent_utc DESC);
-- The "is this currently a live warning" query: Actual status, not ended,
-- not an all-clear, not expired. Computed at query time (routes.py), not
-- stored, so a stale row never has to be re-written just because a clock
-- ticked past `expires_utc`.
CREATE INDEX IF NOT EXISTS idx_aurora_alerts_active
    ON wtf.aurora_alerts(status, location_status, expires_utc DESC);
