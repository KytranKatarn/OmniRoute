-- 083_aurora_aqhi_layer_status.sql
-- Add the 'aqhi' layer to wtf.aurora_layer_status (Dev HQ #6621 item 5).
-- This view is THE only source of layer names the templates loop over
-- (CLAUDE.md's own note: hardcoding one is how a page once advertised a
-- source it didn't have) — a new layer MUST be added here, never as a
-- hardcoded template entry. CREATE OR REPLACE VIEW re-states the 5 existing
-- UNION branches verbatim (from migrations 053/055) plus the new one, since
-- Postgres has no "ALTER VIEW ... ADD UNION" — this is the only way to add
-- a branch to an existing view.
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
-- New (#6621): AQHI observations. 1h stale-after — same reasoning as
-- city_obs's 3h but tighter, since AQHI actually publishes ~hourly per
-- station (verified live) vs citypage's occasional multi-per-hour bursts.
SELECT 'aqhi'::text, 'Air Quality Health Index'::text,
    'Meteorological Service of Canada (ECCC)'::text,
    'air_quality/aqhi/observation/realtime'::text, 'https://dd.weather.gc.ca/'::text,
    (SELECT max(observed_utc)::timestamptz FROM wtf.aurora_aqhi_obs),
    (SELECT max(fetched_at) FROM wtf.aurora_aqhi_obs),
    (SELECT count(*) FROM wtf.aurora_aqhi_obs),
    3;
