-- 055: A.U.R.O.R.A. Phase 2 — MSC Datamart citypage_weather city observations
-- and forecasts (project #393, task #5760).
--
-- (Numbered 055, not the 054 the build spec assumed: 054 was taken by the
-- source-language correction that shipped first.)
--
-- SOURCE GOVERNANCE (ADR-001): fed ONLY from dd.weather.gc.ca, which serves NO
-- robots.txt (HTTP 404, verified first-hand 2026-08-18) and is therefore
-- unrestricted. api.weather.gc.ca/collections/*/items is DISALLOWED by its
-- robots.txt; dd.alpha.weather.gc.ca is "Disallow: /". Do not repoint.
--
-- PATH: /{YYYYMMDD}/WXO-DD/citypage_weather/{PROV}/{HH}/ — the DATED archive
-- path, which is a complete mirror of today/ INCLUDING siteList.xml (verified
-- first-hand). /citypage_weather/ at the root is a 404; there is no xml/
-- segment; omitting WXO-DD is a 404. Filenames are millisecond-timestamped and
-- NOT constructible from the site code — list the hour dir and take max().
--
-- ⚠️ GRANTs are mandatory: WTF apps connect as wtfuser, NOT as the owner. A new
-- table without them fails at runtime, not at migration time (migration 047).

-- ── registry ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wtf.aurora_city_site (
    id                bigserial PRIMARY KEY,
    site_code         text NOT NULL UNIQUE,   -- 's' + 7 digits, e.g. 's0000458'
    source_prov       text NOT NULL,          -- MSC provinceCode VERBATIM, incl. 'HEF'
    name_en           text NOT NULL,
    name_fr           text,
    display_name      text,                   -- editorial override (see Ottawa)
    is_city           boolean NOT NULL DEFAULT true,
    sort_order        integer NOT NULL DEFAULT 100,
    lat               double precision,       -- from the per-site XML; siteList has NO coords
    lon               double precision,
    last_seen_utc     timestamptz,
    last_obs_status   text,                   -- ok|no_observations|parse_error|fetch_error
    fetched_at        timestamptz NOT NULL DEFAULT now()
);

-- source_prov is stored VERBATIM and is NEVER canonicalised here. Canon happens
-- at exactly ONE boundary — consumer/aurora_map._canon_prov — matching the CWFIS
-- precedent (cwfis.py stores the legacy 'NF'; only the payload builder renames
-- it). A second canon site is how a province goes missing.
--
-- NOTE the two feeds disagree: CWFIS emits NF for Newfoundland, Datamart emits
-- NL. Both land on the GeoJSON's NL via that one helper.
--
-- is_city is the HEF exclusion lever: HEF's 11 entries are BC highway corridor
-- segments ("Coquihalla Highway - Hope to Merritt"), not cities. Excluded by
-- DATA, not by code.

-- ── current conditions ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wtf.aurora_city_obs (
    id                  bigserial PRIMARY KEY,
    site_code           text        NOT NULL,
    observed_utc        timestamptz NOT NULL,
    observed_local_ts   text,
    local_zone          text,
    local_utc_offset    integer,
    station_code        text,
    station_name        text,
    station_lat         double precision,   -- the STATION's coords, not the city's
    station_lon         double precision,
    condition_text      text,
    icon_code           text,
    temp_c              double precision,
    dewpoint_c          double precision,
    rel_humidity_pct    double precision,
    humidex             double precision,
    wind_chill          double precision,
    pressure_kpa        double precision,
    pressure_change_kpa double precision,
    pressure_tendency   text,
    visibility_km       double precision,
    wind_speed_kmh      double precision,   -- NULL when the source says 'calm'
    wind_is_calm        boolean NOT NULL DEFAULT false,
    wind_gust_kmh       double precision,
    wind_dir            text,
    wind_bearing_deg    double precision,
    source_file         text NOT NULL,
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (site_code, observed_utc)
);
CREATE INDEX IF NOT EXISTS idx_aurora_cityobs_site ON wtf.aurora_city_obs (site_code, observed_utc DESC);
CREATE INDEX IF NOT EXISTS idx_aurora_cityobs_time ON wtf.aurora_city_obs (observed_utc DESC);

-- wind_speed_kmh + wind_is_calm is the honest encoding of a MEASURED calm. The
-- XSD enumerates Calm/Calme/calm/calme as valid wind speeds and live sites emit
-- it with qaValue="100". float() on it crashes; writing 0 asserts a measurement
-- of zero km/h that was never taken, and renders identically to a missing
-- reading. Calm is a MEASUREMENT, missing is ABSENCE — different columns.
--
-- UNIQUE (site_code, observed_utc) is correct for BOTH republish shapes,
-- verified live: a site may republish with an IDENTICAL observation time (true
-- duplicate — collapses) or an ADVANCED one (genuinely new reading — preserved).
--
-- A self-closed <currentConditions/> writes NO row: it has no observation
-- timestamp, so it cannot key. That absence is recorded on the registry
-- (last_obs_status='no_observations' with last_seen_utc still advanced) so the
-- UI can say "MSC published no observations for this site" rather than "we could
-- not reach the source" — two different facts.

-- ── forecasts ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wtf.aurora_city_forecast (
    id              bigserial PRIMARY KEY,
    site_code       text        NOT NULL,
    issued_utc      timestamptz NOT NULL,
    period_index    integer     NOT NULL,   -- 0-based document order
    period_label    text,                   -- <period textForecastName> ATTRIBUTE
    period_weekday  text,                   -- <period> element TEXT
    temp_high_c     double precision,
    temp_low_c      double precision,
    text_summary    text,
    abbrev_summary  text,
    pop_pct         double precision,
    wind_summary    text,
    wind_gust_kmh   double precision,       -- NULL when the literal '00' sentinel
    uv_index        double precision,
    uv_category     text,
    source_file     text NOT NULL,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (site_code, issued_utc, period_index)
);
CREATE INDEX IF NOT EXISTS idx_aurora_cityfcst_latest
    ON wtf.aurora_city_forecast (site_code, issued_utc DESC, period_index);

-- temp_high_c AND temp_low_c as separate columns: the XSD allows maxOccurs="2",
-- so a single (temp, class) pair cannot represent a period carrying both.
--
-- ⚠️ wind_gust_kmh: the daily forecast emits the LITERAL string '00' to mean NO
-- GUST. It parses cleanly as the integer 0 — no exception, no empty-check
-- triggered — so `int(x or 0)` silently turns "no gust" into "a measured 0 km/h".
-- That is one of FIVE distinct encodings of absence in this feed and the only
-- one that defeats a truthiness guard.

GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_site     TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_obs      TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_forecast TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_city_site_id_seq     TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_city_obs_id_seq      TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_city_forecast_id_seq TO wtfuser;

-- ── seed: 25 cities, EVERY code verified against the live siteList.xml ──────
-- (name_en and provinceCode matched exactly, 25/25, 2026-08-18.)
--
-- These are the cities the feed ACTUALLY has, not the cities a population
-- ranking would suggest. Surrey and Burnaby — Canada's 12th and 22nd largest —
-- do NOT exist in this feed at all; seeding them from a population list would
-- create permanently-empty cards.
--
-- There is no plain "Ottawa" site: s0000430 is "Ottawa (Kanata - Orléans)" and
-- carries a display_name so the card can read "Ottawa" without the stored
-- source name being falsified.
--
-- All 13 provinces + territories are covered. That is deliberate: the Phase 1
-- fire map has to grey out five provinces because CWFIS has no stations there,
-- and a national weather page that silently omitted the North would repeat the
-- same coverage dishonesty in a new place.
INSERT INTO wtf.aurora_city_site (site_code, source_prov, name_en, display_name, sort_order) VALUES
    ('s0000458', 'ON', 'Toronto',                   NULL,      10),
    ('s0000635', 'QC', 'Montréal',                  NULL,      20),
    ('s0000141', 'BC', 'Vancouver',                 NULL,      30),
    ('s0000047', 'AB', 'Calgary',                   NULL,      40),
    ('s0000045', 'AB', 'Edmonton',                  NULL,      50),
    ('s0000430', 'ON', 'Ottawa (Kanata - Orléans)', 'Ottawa',  60),
    ('s0000193', 'MB', 'Winnipeg',                  NULL,      70),
    ('s0000620', 'QC', 'Québec',                    NULL,      80),
    ('s0000549', 'ON', 'Hamilton',                  NULL,      90),
    ('s0000318', 'NS', 'Halifax',                   NULL,     100),
    ('s0000797', 'SK', 'Saskatoon',                 NULL,     110),
    ('s0000788', 'SK', 'Regina',                    NULL,     120),
    ('s0000280', 'NL', 'St. John''s',               NULL,     130),
    ('s0000775', 'BC', 'Victoria',                  NULL,     140),
    ('s0000687', 'NB', 'Saint John',                NULL,     150),
    ('s0000326', 'ON', 'London',                    NULL,     160),
    ('s0000646', 'ON', 'Windsor',                   NULL,     170),
    ('s0000592', 'BC', 'Kelowna',                   NULL,     180),
    ('s0000654', 'NB', 'Moncton',                   NULL,     190),
    ('s0000250', 'NB', 'Fredericton',               NULL,     200),
    ('s0000670', 'NS', 'Sydney',                    NULL,     210),
    ('s0000583', 'PE', 'Charlottetown',             NULL,     220),
    ('s0000366', 'NT', 'Yellowknife',               NULL,     230),
    ('s0000825', 'YT', 'Whitehorse',                NULL,     240),
    ('s0000394', 'NU', 'Iqaluit',                   NULL,     250)
ON CONFLICT (site_code) DO NOTHING;

-- ── layer-status view: add the two city layers + a per-layer staleness window ─
-- NEW COLUMN stale_after_hours. The route's hardcoded 48h window is wrong for an
-- hourly feed: a card showing 40-hour-old "current conditions" as fresh is
-- exactly the class of dishonesty this project keeps fixing. Existing branches
-- are back-filled with 48 so their behaviour is unchanged.
CREATE OR REPLACE VIEW wtf.aurora_layer_status AS
SELECT 'firewx'::text AS layer_key,
       'Fire-weather stations'::text AS layer_label,
       'Canadian Wildland Fire Information System (NRCan)'::text AS issuing_body,
       'public:firewx_stns_current'::text AS dataset_id,
       'https://cwfis.cfs.nrcan.gc.ca/'::text AS source_url,
       (SELECT max(rep_date)   FROM wtf.aurora_firewx_obs) AS data_latest,
       (SELECT max(fetched_at) FROM wtf.aurora_firewx_obs) AS last_pull,
       (SELECT count(*)        FROM wtf.aurora_firewx_obs) AS record_count,
       48 AS stale_after_hours
UNION ALL
SELECT 'hotspots', 'Satellite hotspots (24h)',
       'Canadian Wildland Fire Information System (NRCan)',
       'public:hotspots_last24hrs', 'https://cwfis.cfs.nrcan.gc.ca/',
       (SELECT max(obs_date)::timestamptz FROM wtf.aurora_fire_hotspot_daily),
       (SELECT max(fetched_at) FROM wtf.aurora_fire_hotspot_daily),
       (SELECT count(*) FROM wtf.aurora_fire_hotspot_daily),
       48
UNION ALL
SELECT 'perimeters', 'Active fire perimeters',
       'Canadian Wildland Fire Information System (NRCan)',
       'public:m3_polygons_current', 'https://cwfis.cfs.nrcan.gc.ca/',
       (SELECT max(snapshot_date)::timestamptz FROM wtf.aurora_fire_perimeters),
       (SELECT max(fetched_at) FROM wtf.aurora_fire_perimeters),
       (SELECT count(*) FROM wtf.aurora_fire_perimeters),
       48
UNION ALL
SELECT 'city_obs', 'City current conditions',
       'Meteorological Service of Canada (ECCC)',
       'citypage_weather/currentConditions',
       'https://dd.weather.gc.ca/',
       (SELECT max(observed_utc) FROM wtf.aurora_city_obs),
       (SELECT max(fetched_at)   FROM wtf.aurora_city_obs),
       (SELECT count(*)          FROM wtf.aurora_city_obs),
       -- hourly feed: 3h is already several missed cycles
       3
UNION ALL
SELECT 'city_forecast', 'City forecasts',
       'Meteorological Service of Canada (ECCC)',
       'citypage_weather/forecastGroup',
       'https://dd.weather.gc.ca/',
       (SELECT max(issued_utc) FROM wtf.aurora_city_forecast),
       (SELECT max(fetched_at) FROM wtf.aurora_city_forecast),
       (SELECT count(*)        FROM wtf.aurora_city_forecast),
       -- MSC issues ~4x/day; 12h means at least two issues missed
       12;

GRANT SELECT ON wtf.aurora_layer_status TO wtfuser;
