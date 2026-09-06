-- 084_aurora_evacuations.sql
-- A.U.R.O.R.A. weather: evacuation-order layer (Dev HQ #6624).
-- Two independent sources, confirmed live 2026-09-06 — see
-- ingest/weather/evacuations.py's module docstring for the full scope
-- decision (decision #1082/#1083): a real national source (NAAD/Alert
-- Ready) exists, so this is NOT a province-by-province patchwork.

-- 1. NAAD/Alert Ready — national CAP-CP evacuation-shaped alerts.
-- identifier is the CAP <identifier>, globally unique per alert, same
-- upsert-key pattern as wtf.aurora_alerts. matched_keyword records which
-- regex/language actually classified this as an evacuation, so a human can
-- audit WHY a row is here, not just trust a boolean.
CREATE TABLE IF NOT EXISTS wtf.aurora_evacuations (
    id                  SERIAL PRIMARY KEY,
    identifier          TEXT NOT NULL UNIQUE,
    event               TEXT,
    status              TEXT,       -- Actual/Exercise/Test/Draft
    msg_type            TEXT,       -- Alert/Update/Cancel/Ack/Error
    urgency             TEXT,
    severity            TEXT,
    certainty           TEXT,
    headline            TEXT,
    description         TEXT,
    instruction         TEXT,
    area_desc           TEXT,
    matched_keyword     TEXT,       -- which evacuation regex/language hit
    issuing_authority   TEXT,       -- CAP <sender>
    sent_utc            TIMESTAMPTZ,
    effective_utc       TIMESTAMPTZ,
    expires_utc         TIMESTAMPTZ,
    source_url          TEXT,
    fetched_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_aurora_evacuations_sent ON wtf.aurora_evacuations(sent_utc DESC);
-- Same "is this currently active" shape as aurora_alerts: computed at query
-- time from status/expires_utc, never stored as a boolean that a clock could
-- silently invalidate.
CREATE INDEX IF NOT EXISTS idx_aurora_evacuations_active
    ON wtf.aurora_evacuations(status, expires_utc DESC);

-- 2. BC DataBC — "Evacuation Orders and Alerts" (EMRG_ORDER_AND_ALERT_AREAS_SP).
-- event_number is BC's own unique event identifier. order_alert_status
-- ("Order" = mandatory evacuation vs "Alert" = be-ready warning) is kept as
-- its own column deliberately — the single most operationally important
-- field this source provides; do not collapse it into a generic status.
-- geometry is the raw GeoJSON polygon, stored as JSONB — no PostGIS needed,
-- this layer is rendered as list cards, not choropleth-plotted.
CREATE TABLE IF NOT EXISTS wtf.aurora_bc_evacuations (
    id                  SERIAL PRIMARY KEY,
    event_number        TEXT NOT NULL UNIQUE,
    event_name          TEXT,
    event_type          TEXT,       -- Fire/Landslide/Flood/etc.
    order_alert_name    TEXT,
    order_alert_status  TEXT,       -- "Order" or "Alert"
    issuing_agency      TEXT,
    preoc_code          TEXT,
    population          NUMERIC,
    homes               NUMERIC,
    date_modified       TIMESTAMPTZ,
    event_start_date    TIMESTAMPTZ,
    geometry            JSONB,
    fetched_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_aurora_bc_evac_modified ON wtf.aurora_bc_evacuations(date_modified DESC);
CREATE INDEX IF NOT EXISTS idx_aurora_bc_evac_status ON wtf.aurora_bc_evacuations(order_alert_status);

-- 3. wtf.aurora_layer_status — re-state ALL existing branches (migration 083
-- has 6: firewx, hotspots, perimeters, city_obs, city_forecast, aqhi — NOT 7;
-- 'alerts' is rendered as a banner strip, not a selectable layer, and was
-- never added here) PLUS the 2 new evacuation branches. Postgres has no
-- "ALTER VIEW ... ADD UNION" — this view must be fully re-stated each time,
-- and it is THE ONLY source of layer names the templates loop over.
CREATE OR REPLACE VIEW wtf.aurora_layer_status AS
SELECT 'firewx'::text AS layer_key,
    'Fire-weather stations'::text AS layer_label,
    'Canadian Wildland Fire Information System (NRCan)'::text AS issuing_body,
    'public:firewx_stns_current'::text AS dataset_id,
    'https://cwfis.cfs.nrcan.gc.ca/'::text AS source_url,
    (SELECT max(rep_date) FROM wtf.aurora_firewx_obs) AS data_latest,
    (SELECT max(fetched_at) FROM wtf.aurora_firewx_obs) AS last_pull,
    (SELECT count(*) FROM wtf.aurora_firewx_obs) AS record_count,
    48 AS stale_after_hours
UNION ALL
SELECT 'hotspots'::text, 'Satellite hotspots (24h)'::text,
    'Canadian Wildland Fire Information System (NRCan)'::text,
    'public:hotspots_last24hrs'::text, 'https://cwfis.cfs.nrcan.gc.ca/'::text,
    (SELECT max(obs_date)::timestamptz FROM wtf.aurora_fire_hotspot_daily),
    (SELECT max(fetched_at) FROM wtf.aurora_fire_hotspot_daily),
    (SELECT count(*) FROM wtf.aurora_fire_hotspot_daily),
    48
UNION ALL
SELECT 'perimeters'::text, 'Active fire perimeters'::text,
    'Canadian Wildland Fire Information System (NRCan)'::text,
    'public:m3_polygons_current'::text, 'https://cwfis.cfs.nrcan.gc.ca/'::text,
    (SELECT max(snapshot_date)::timestamptz FROM wtf.aurora_fire_perimeters),
    (SELECT max(fetched_at) FROM wtf.aurora_fire_perimeters),
    (SELECT count(*) FROM wtf.aurora_fire_perimeters),
    48
UNION ALL
SELECT 'city_obs'::text, 'City current conditions'::text,
    'Meteorological Service of Canada (ECCC)'::text,
    'citypage_weather/currentConditions'::text, 'https://dd.weather.gc.ca/'::text,
    (SELECT max(observed_utc) FROM wtf.aurora_city_obs),
    (SELECT max(fetched_at) FROM wtf.aurora_city_obs),
    (SELECT count(*) FROM wtf.aurora_city_obs),
    3
UNION ALL
SELECT 'city_forecast'::text, 'City forecasts'::text,
    'Meteorological Service of Canada (ECCC)'::text,
    'citypage_weather/forecastGroup'::text, 'https://dd.weather.gc.ca/'::text,
    (SELECT max(issued_utc) FROM wtf.aurora_city_forecast),
    (SELECT max(fetched_at) FROM wtf.aurora_city_forecast),
    (SELECT count(*) FROM wtf.aurora_city_forecast),
    12
UNION ALL
SELECT 'aqhi'::text, 'Air Quality Health Index'::text,
    'Meteorological Service of Canada (ECCC)'::text,
    'air_quality/aqhi/observation/realtime'::text, 'https://dd.weather.gc.ca/'::text,
    (SELECT max(observed_utc)::timestamptz FROM wtf.aurora_aqhi_obs),
    (SELECT max(fetched_at) FROM wtf.aurora_aqhi_obs),
    (SELECT count(*) FROM wtf.aurora_aqhi_obs),
    3
UNION ALL
-- New (#6624): NAAD/Alert Ready evacuation-shaped alerts. 2h stale-after —
-- the feed is a rolling live window polled hourly; 2h gives one missed cycle
-- of slack before alarming, tighter than the 48h fire layers since this is
-- life-safety content that should be caught fast if the puller stalls.
SELECT 'evacuations_naad'::text, 'Evacuation orders (Alert Ready)'::text,
    'Pelmorex Corp. (NAAD / Alert Ready)'::text,
    'rss.naad-adna.pelmorex.com'::text, 'https://www.alertready.ca/'::text,
    (SELECT max(sent_utc) FROM wtf.aurora_evacuations),
    (SELECT max(fetched_at) FROM wtf.aurora_evacuations),
    (SELECT count(*) FROM wtf.aurora_evacuations),
    2
UNION ALL
-- New (#6624): BC's own structured Order/Alert layer. BC loads this hourly
-- (10 min past the hour per the dataset's own data_quality note) — 2h gives
-- the same one-missed-cycle slack.
SELECT 'evacuations_bc'::text, 'BC evacuation orders & alerts'::text,
    'Emergency Management BC'::text,
    'WHSE_HUMAN_CULTURAL_ECONOMIC.EMRG_ORDER_AND_ALERT_AREAS_SP'::text,
    'https://catalogue.data.gov.bc.ca/dataset/evacuation-orders-and-alerts'::text,
    (SELECT max(date_modified) FROM wtf.aurora_bc_evacuations),
    (SELECT max(fetched_at) FROM wtf.aurora_bc_evacuations),
    (SELECT count(*) FROM wtf.aurora_bc_evacuations),
    2;
