-- 053: A.U.R.O.R.A. Phase 1 — CWFIS wildfire + fire-weather layers (project #393).
--
-- SOURCE GOVERNANCE (ADR-001, owner decision 2026-08-18): these tables are fed
-- ONLY from cwfis.cfs.nrcan.gc.ca, whose robots.txt is a bare "Disallow:"
-- (allow-all, verified). api.weather.gc.ca is deliberately NOT used — its
-- robots.txt disallows /collections/*/items. Do not repoint these ingests at
-- GeoMet without revisiting that decision.
--
-- ⚠️ GRANTs are mandatory: WTF apps connect as wtfuser, NOT as the owner. A new
-- table without them fails at runtime, not at migration time (migration 047).

CREATE TABLE IF NOT EXISTS wtf.aurora_firewx_obs (
    id              bigserial PRIMARY KEY,
    station_key     text        NOT NULL,   -- wmo id, or aes when wmo is absent
    station_name    text,
    prov            text,
    agency          text,
    lat             double precision,
    lon             double precision,
    rep_date        timestamptz NOT NULL,
    temp_c          double precision,
    rel_humidity    double precision,
    wind_speed_kmh  double precision,       -- ws
    wind_gust_kmh   double precision,       -- wg
    wind_dir_deg    double precision,       -- wdir
    precip_mm       double precision,
    pressure_kpa    double precision,
    visibility_km   double precision,
    -- Canadian Fire Weather Index system components, carried verbatim
    ffmc double precision, dmc double precision, dc double precision,
    isi  double precision, bui double precision, fwi double precision,
    dsr  double precision,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (station_key, rep_date)
);
CREATE INDEX IF NOT EXISTS idx_aurora_firewx_repdate ON wtf.aurora_firewx_obs (rep_date DESC);
CREATE INDEX IF NOT EXISTS idx_aurora_firewx_prov    ON wtf.aurora_firewx_obs (prov, rep_date DESC);

-- Hotspots are rolled up on ingest: the raw layer is ~10k features/day and
-- spans the US + Mexico. We keep the Canadian per-province daily aggregate,
-- which is what the page actually shows.
CREATE TABLE IF NOT EXISTS wtf.aurora_fire_hotspot_daily (
    id             bigserial PRIMARY KEY,
    obs_date       date NOT NULL,
    prov           text NOT NULL,
    hotspot_count  integer NOT NULL,
    max_fwi        double precision,
    mean_frp       double precision,   -- fire radiative power
    dominant_fuel  text,
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (obs_date, prov)
);
CREATE INDEX IF NOT EXISTS idx_aurora_hotspot_date ON wtf.aurora_fire_hotspot_daily (obs_date DESC);

-- m3_polygons_current carries no province/name attribute (verified), so a
-- national daily summary is the honest granularity — do NOT invent per-fire
-- identity the source does not publish.
CREATE TABLE IF NOT EXISTS wtf.aurora_fire_perimeters (
    id               bigserial PRIMARY KEY,
    snapshot_date    date NOT NULL UNIQUE,
    perimeter_count  integer NOT NULL,
    total_area       double precision,   -- source units undocumented; see ingest note
    max_area         double precision,
    earliest_start   timestamptz,
    fetched_at       timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_firewx_obs          TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_fire_hotspot_daily  TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_fire_perimeters     TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_firewx_obs_id_seq         TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_fire_hotspot_daily_id_seq TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_fire_perimeters_id_seq    TO wtfuser;

-- The provenance strip renders by LOOPING this view. No source name is ever
-- hardcoded in a template — that is exactly how the site came to advertise
-- Environment Canada / NASA / NOAA data it did not hold (KB #290491).
CREATE OR REPLACE VIEW wtf.aurora_layer_status AS
SELECT 'firewx'::text AS layer_key,
       'Fire-weather stations'::text AS layer_label,
       'Canadian Wildland Fire Information System (NRCan)'::text AS issuing_body,
       'public:firewx_stns_current'::text AS dataset_id,
       'https://cwfis.cfs.nrcan.gc.ca/'::text AS source_url,
       (SELECT max(rep_date)   FROM wtf.aurora_firewx_obs) AS data_latest,
       (SELECT max(fetched_at) FROM wtf.aurora_firewx_obs) AS last_pull,
       (SELECT count(*)        FROM wtf.aurora_firewx_obs) AS record_count
UNION ALL
SELECT 'hotspots', 'Satellite hotspots (24h)',
       'Canadian Wildland Fire Information System (NRCan)',
       'public:hotspots_last24hrs', 'https://cwfis.cfs.nrcan.gc.ca/',
       (SELECT max(obs_date)::timestamptz FROM wtf.aurora_fire_hotspot_daily),
       (SELECT max(fetched_at) FROM wtf.aurora_fire_hotspot_daily),
       (SELECT count(*) FROM wtf.aurora_fire_hotspot_daily)
UNION ALL
SELECT 'perimeters', 'Active fire perimeters',
       'Canadian Wildland Fire Information System (NRCan)',
       'public:m3_polygons_current', 'https://cwfis.cfs.nrcan.gc.ca/',
       (SELECT max(snapshot_date)::timestamptz FROM wtf.aurora_fire_perimeters),
       (SELECT max(fetched_at) FROM wtf.aurora_fire_perimeters),
       (SELECT count(*) FROM wtf.aurora_fire_perimeters);

GRANT SELECT ON wtf.aurora_layer_status TO wtfuser;
