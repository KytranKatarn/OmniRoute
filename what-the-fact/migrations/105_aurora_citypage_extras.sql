-- 105: store the parts of the MSC city-page XML we already download every cycle and used to throw away (Dev HQ 7234, S2 of the weather port).
--
--   * hourly forecast  - 24 entries per issue (condition, ECCC icon_code, temperature, chance of precipitation, wind)
--   * regional normals - the normal daily high/low for the date
--   * yesterday        - high/low, precip / rain / snow, wind gust of the previous LOCAL day
--   * sunrise/sunset   - per local date
--   * forecast periods - icon_code, humidex, relative humidity (UV already existed)
--
-- APPLIES TO CITADEL'S wtf DATABASE ONLY (see migrations/README.md). Idempotent. Every absent value stays NULL: a blank element is not a zero.
-- ORDER OF ROLLOUT: apply this BEFORE deploying the ingest that writes to it. The ingest's core observation/forecast insert does NOT depend on the new
-- forecast columns (they are written by a separate guarded UPDATE), so a wrong order loses the new data but never breaks the existing feed.

-- forecast periods: the three new columns (written by a guarded UPDATE, never by the core insert)
ALTER TABLE wtf.aurora_city_forecast
    ADD COLUMN IF NOT EXISTS icon_code        text,
    ADD COLUMN IF NOT EXISTS humidex          double precision,
    ADD COLUMN IF NOT EXISTS rel_humidity_pct double precision;

-- hourly forecast: next 24 hours of each issue. History is NOT needed (the consumer reads the latest issue), so the ingest prunes rows older than 3 days.
CREATE TABLE IF NOT EXISTS wtf.aurora_city_hourly (
    id              bigserial PRIMARY KEY,
    site_code       text        NOT NULL,
    issued_utc      timestamptz NOT NULL,          -- hourlyForecastGroup / forecastIssue (UTC)
    hour_utc        timestamptz NOT NULL,          -- hourlyForecast@dateTimeUTC
    condition       text,
    icon_code       text,
    temp_c          double precision,
    lop_pct         double precision,              -- chance of precipitation; the feed writes 0 with category 'Nil'
    lop_category    text,
    wind_speed_kmh  double precision,
    wind_is_calm    boolean     NOT NULL DEFAULT false,   -- calm is a measurement with no number, distinct from a missing reading
    wind_dir        text,
    wind_gust_kmh   double precision,              -- NULL for the '00' no-gust sentinel
    wind_chill      double precision,
    humidex         double precision,
    source_file     text        NOT NULL,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (site_code, issued_utc, hour_utc)
);
CREATE INDEX IF NOT EXISTS idx_aurora_cityhourly_latest ON wtf.aurora_city_hourly (site_code, issued_utc DESC, hour_utc);
CREATE INDEX IF NOT EXISTS idx_aurora_cityhourly_issued ON wtf.aurora_city_hourly (issued_utc);   -- the retention prune

-- regional normals: only the latest per site matters
CREATE TABLE IF NOT EXISTS wtf.aurora_city_normals (
    site_code     text PRIMARY KEY,
    issued_utc    timestamptz NOT NULL,
    normal_high_c double precision,
    normal_low_c  double precision,
    text_summary  text,
    source_file   text NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now()
);

-- yesterday: one row per site per LOCAL day (small: 25/day). A trace amount is stored as 0 WITH its flag, not as a measured 0.
CREATE TABLE IF NOT EXISTS wtf.aurora_city_yesterday (
    site_code        text NOT NULL,
    obs_date         date NOT NULL,                -- the city's local date, = local forecast-issue date - 1
    high_c           double precision,
    low_c            double precision,
    precip_mm        double precision,
    precip_trace     boolean,
    rain_mm          double precision,
    rain_trace       boolean,
    snow_cm          double precision,
    snow_trace       boolean,
    gust_kmh         double precision,
    gust_bearing_deg double precision,
    gust_dir         text,
    source_file      text NOT NULL,
    fetched_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (site_code, obs_date)
);

-- sunrise / sunset per site per LOCAL date (the sunset's UTC date can be the next day for a western city, so the local date is the key)
CREATE TABLE IF NOT EXISTS wtf.aurora_city_sun (
    site_code   text NOT NULL,
    sun_date    date NOT NULL,
    sunrise_utc timestamptz NOT NULL,
    sunset_utc  timestamptz NOT NULL,
    source_file text NOT NULL,
    fetched_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (site_code, sun_date)
);

-- the apps connect as wtfuser, not the table owner: every new table must grant to it (migrations/README.md)
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_hourly    TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_normals   TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_yesterday TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_sun       TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_city_hourly_id_seq TO wtfuser;

INSERT INTO public.schema_migrations (version, filename, description, applied_at)
VALUES ('105', '105_aurora_citypage_extras.sql', 'MSC city-page extras: hourly forecast, regional normals, yesterday, sunrise/sunset, forecast icon/humidex/humidity', now())
ON CONFLICT (version) DO NOTHING;
