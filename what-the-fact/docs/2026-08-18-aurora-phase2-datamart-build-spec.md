# A.U.R.O.R.A. Phase 2 — BUILD SPEC
## MSC Datamart city observations + forecasts → city cards on what-the-fact.com/weather
**Task #5760 · project #393 · repo `/mnt/archie_brain/what-the-fact` · migration 054**

---

## 0. Ground truth this spec is built on

Everything below rests on facts that survived adversarial re-probing on 2026-08-18, plus four
additional first-hand probes I ran while writing this spec (marked **[new]**). Refuted and
unverified claims are excluded from the design and appear in §7.

**Path (load-bearing, all confirmed twice):**

```
https://dd.weather.gc.ca/{YYYYMMDD}/WXO-DD/citypage_weather/{PROV}/{HH}/
    {YYYYMMDD}T{HHMMSS}.{mmm}Z_MSC_CitypageWeather_{sNNNNNNN}_{en|fr}.xml
```

- `https://dd.weather.gc.ca/robots.txt` → **HTTP 404** (no restriction). ADR-001 satisfied.
- `https://dd.weather.gc.ca/citypage_weather/` → **404**. There is no root-level topic path.
- `https://dd.weather.gc.ca/{date}/citypage_weather/...` → **404**. The `WXO-DD` segment is mandatory.
- There is **no `xml/` segment** (`.../citypage_weather/xml/` → 404).
- **The dated archive path is a COMPLETE, self-sufficient mirror of `today/`** — 18 entries
  including `siteList.xml` (110,595 bytes, 855 sites) and `schema/`. The recon report claimed
  these were absent from the archive path; that was **refuted**. Consequence: **pin everything
  to `/{YYYYMMDD}/WXO-DD/`, including the site index.** Never use `today/` (it flips wholesale
  at 00:00Z and is not reproducible).
- One **completed** hour directory per province contains **every** site for that province:
  855/855, 0 missing, 0 extra, verified independently twice.
- Conditional GET works: `ETag` + `Last-Modified` present, re-GET returns **304**.
- `siteList.xml` `Last-Modified: Wed, 25 Jun 2025 12:40:15 GMT` — effectively static.
- ~30 days of genuinely populated retention (oldest dated dir returned full ON coverage).

**[new] Four facts I verified myself, which shape the schema:**

1. **`forecastGroup/dateTime[@name="forecastIssue"][@zone="UTC"]` EXISTS.** Toronto s0000458 →
   `20260818150000`; s0000696 → `20260818153000`. Forecasts therefore have a real issue time and
   can be keyed on it. (Was previously unverified; the design would otherwise have had to guess.)
2. **Republishes within one hour carry BOTH same and different observation timestamps.**
   s0000022 / s0000411 / s0000528 / s0000529 / s0000530 republished with an *identical* `obsUTC`
   (true duplicates); s0000024 went `180000 → 183800` and s0000696 went `180000 → 180100 → 181000`
   (genuinely new readings). **`UNIQUE (site_code, observed_utc)` is correct in both cases** — it
   collapses the duplicates and preserves the new readings.
3. **`max(filename timestamp)` ⇒ `max(observation timestamp)`** in 8/8 multi-publish sites sampled
   (never regressed). Selecting the lexicographically largest filename within one hour dir is safe.
4. **An hour directory can contain an observation from the PREVIOUS hour.** s0000479's first file in
   `ON/18/` carried `obsUTC 20260818174900`. **The observation time must be read from the XML,
   never inferred from the directory name.**

**[new] Publish frequency is highly variable, not ~3×:** in `ON/18/`, **137 of 170 sites published
exactly once**; 33 published more (one site 15×). The recon's "1,016 files / ~3× per site" was a
2× measurement bug (Apache autoindex prints each filename twice — once in `href=`, once as link
text). The true figure is **254 `_en` files for 170 sites**. Any listing parser must count **href
attributes**, not substring occurrences.

---

## 1. Tables — migration `054_aurora_citypage.sql`

Header must carry the ADR-001 justification verbatim, in the style of 053:

```sql
-- 054: A.U.R.O.R.A. Phase 2 — MSC Datamart citypage_weather city observations
-- and forecasts (project #393, task #5760).
--
-- SOURCE GOVERNANCE (ADR-001): fed ONLY from dd.weather.gc.ca, which serves NO
-- robots.txt (HTTP 404, verified first-hand 2026-08-18) and is therefore
-- unrestricted. api.weather.gc.ca/collections/*/items is DISALLOWED by its
-- robots.txt; dd.alpha.weather.gc.ca is "Disallow: /". Do not repoint.
--
-- PATH: /{YYYYMMDD}/WXO-DD/citypage_weather/{PROV}/{HH}/ — the DATED archive
-- path, which is a complete mirror of today/ INCLUDING siteList.xml (verified).
-- /citypage_weather/ at the root is a 404; there is no xml/ segment; omitting
-- WXO-DD is a 404. Filenames are millisecond-timestamped and NOT constructible.
--
-- ⚠️ GRANTs are mandatory: WTF apps connect as wtfuser, NOT as the owner. A new
-- table without them fails at runtime, not at migration time (migration 047).
```

### 1.1 `wtf.aurora_city_site` — curated city registry

```sql
CREATE TABLE IF NOT EXISTS wtf.aurora_city_site (
    id                bigserial PRIMARY KEY,
    site_code         text NOT NULL UNIQUE,   -- 's' + 7 digits, e.g. 's0000458'
    source_prov       text NOT NULL,          -- MSC provinceCode VERBATIM, incl. 'HEF'
    name_en           text NOT NULL,          -- from siteList.xml
    name_fr           text,
    display_name      text,                   -- editorial override (see Ottawa note)
    is_city           boolean NOT NULL DEFAULT true,
    sort_order        integer NOT NULL DEFAULT 100,
    lat               double precision,       -- from the per-site XML; siteList has NO coords
    lon               double precision,
    last_seen_utc     timestamptz,            -- last successful fetch+parse of this site's file
    last_obs_status   text,                   -- 'ok'|'no_observations'|'parse_error'|'fetch_error'
    fetched_at        timestamptz NOT NULL DEFAULT now()
);
```

**`source_prov` is stored VERBATIM and is never canonicalised here.** Canonicalisation happens at
exactly one boundary — `consumer/aurora_map._canon_prov` — matching the CWFIS precedent (cwfis.py
stores the legacy `NF`; only the payload builder renames it). Adding a second canon site is how a
province goes missing.

`is_city` is the **HEF exclusion lever**: HEF's 11 entries are BC highway corridor segments
("Coquihalla Highway - Hope to Merritt"), not cities. They are excluded by data, not by code.

**Seed rows (migration `INSERT ... ON CONFLICT (site_code) DO NOTHING`) — verified codes ONLY:**

| site_code | name_en | source_prov | display_name |
|---|---|---|---|
| s0000458 | Toronto | ON | |
| s0000635 | Montréal | QC | |
| s0000141 | Vancouver | BC | |
| s0000047 | Calgary | AB | |
| s0000045 | Edmonton | AB | |
| s0000430 | Ottawa (Kanata - Orléans) | ON | **Ottawa** |
| s0000193 | Winnipeg | MB | |
| s0000620 | Québec | QC | |
| s0000549 | Hamilton | ON | |
| s0000318 | Halifax | NS | |
| s0000797 | Saskatoon | SK | |
| s0000788 | Regina | SK | |
| s0000280 | St. John's | NL | |
| s0000775 | Victoria | BC | |
| s0000687 | Saint John | NB | |

**Do not add a row for any code not in this table.** NT, NU, YT, PE have **no verified site code**
(§7). There is **no plain "Ottawa" site** — `s0000430` is chosen deliberately and carries a
`display_name`. Surrey and Burnaby **do not exist** in the feed at all — a population-derived list
would produce permanently-empty cards.

### 1.2 `wtf.aurora_city_obs` — current conditions

```sql
CREATE TABLE IF NOT EXISTS wtf.aurora_city_obs (
    id                  bigserial PRIMARY KEY,
    site_code           text        NOT NULL,
    observed_utc        timestamptz NOT NULL,   -- dateTime[@name='observation'][@zone='UTC']
    observed_local_ts   text,                   -- the LOCAL dateTime's timeStamp, verbatim
    local_zone          text,                   -- 'EDT' | 'CDT' | 'PDT' ... (varies per site)
    local_utc_offset    integer,                -- -4, -5, -7 ...
    station_code        text,
    station_name        text,
    station_lat         double precision,       -- the STATION's coords, not the city's
    station_lon         double precision,
    condition_text      text,                   -- NULL when empty (52/60 sites)
    icon_code           text,
    temp_c              double precision,
    dewpoint_c          double precision,
    rel_humidity_pct    double precision,
    humidex             double precision,       -- element ABSENT in 36/60 sites
    wind_chill          double precision,       -- ABSENT in 60/60 summer sites
    pressure_kpa        double precision,
    pressure_change_kpa double precision,       -- NULL when change=""
    pressure_tendency   text,                   -- NULL when the attribute is dropped
    visibility_km       double precision,       -- ABSENT in 52/60 sites — NORMAL, not an error
    wind_speed_kmh      double precision,       -- NULL when the source says 'calm'
    wind_is_calm        boolean NOT NULL DEFAULT false,
    wind_gust_kmh       double precision,       -- NULL when present-but-empty
    wind_dir            text,
    wind_bearing_deg    double precision,
    source_file         text NOT NULL,          -- exact filename this row came from
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    UNIQUE (site_code, observed_utc)
);
CREATE INDEX IF NOT EXISTS idx_aurora_cityobs_site ON wtf.aurora_city_obs (site_code, observed_utc DESC);
CREATE INDEX IF NOT EXISTS idx_aurora_cityobs_time ON wtf.aurora_city_obs (observed_utc DESC);
```

**`wind_speed_kmh` + `wind_is_calm` is the honest encoding of a measured calm.** The XSD enumerates
`Calm/Calme/calm/calme` as *valid wind speeds*, and a live site reports `calm` with `qaValue="100"`.
`float()` on it crashes. Writing `0` would assert a measurement of zero km/h that was not taken —
and would render identically to a missing reading. Calm is a **measurement**; missing is **absence**;
the two get different columns.

**A self-closed `<currentConditions/>` writes NO row at all.** It has no observation timestamp, so
it cannot key. The absence is recorded on the registry (`last_obs_status='no_observations'`,
`last_seen_utc` still advanced) so the UI can say *"MSC published no observations for this site"*
rather than *"we could not reach the source"* — two different facts.

### 1.3 `wtf.aurora_city_forecast` — daily forecast periods

```sql
CREATE TABLE IF NOT EXISTS wtf.aurora_city_forecast (
    id              bigserial PRIMARY KEY,
    site_code       text        NOT NULL,
    issued_utc      timestamptz NOT NULL,  -- forecastGroup/dateTime[@name='forecastIssue'][@zone='UTC']
    period_index    integer     NOT NULL,  -- 0-based document order
    period_label    text,                  -- <period textForecastName> ATTRIBUTE: 'Today','Tonight'
    period_weekday  text,                  -- <period> element TEXT: 'Tuesday','Tuesday night'
    temp_high_c     double precision,      -- temperature[@class='high']
    temp_low_c      double precision,      -- temperature[@class='low']
    text_summary    text,
    abbrev_summary  text,
    pop_pct         double precision,      -- NULL when empty; the daily feed NEVER emits 0
    wind_summary    text,
    wind_gust_kmh   double precision,      -- NULL when the literal '00' sentinel
    uv_index        double precision,
    uv_category     text,
    source_file     text NOT NULL,
    fetched_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (site_code, issued_utc, period_index)
);
CREATE INDEX IF NOT EXISTS idx_aurora_cityfcst_latest
    ON wtf.aurora_city_forecast (site_code, issued_utc DESC, period_index);
```

`temp_high_c` **and** `temp_low_c` as separate columns — the XSD allows `maxOccurs="2"`, so a single
`(temp_c, temp_class)` pair cannot represent a period carrying both.

History is retained (≈15 cities × 13 periods × ~4 issues/day ≈ 780 rows/day — trivial) and the UI
selects `WHERE issued_utc = (SELECT max(issued_utc) FROM ... WHERE site_code = ...)`. No
delete-stale sweep is needed because `issued_utc` is a real key, not a rolling slot.

### 1.4 GRANTs — mandatory, tables **and** sequences

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_site     TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_obs      TO wtfuser;
GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.aurora_city_forecast TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_city_site_id_seq     TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_city_obs_id_seq      TO wtfuser;
GRANT USAGE, SELECT ON SEQUENCE wtf.aurora_city_forecast_id_seq TO wtfuser;
```

---

## 2. Layer-status view addition

The view gains a **new column, `stale_after_hours`**, because the route's hardcoded 48h staleness
window is wrong for an hourly feed — a card showing 40-hour-old "current conditions" as fresh is
precisely the class of dishonesty this project keeps fixing. Every existing branch must be
back-filled with `48`, and the route updated in the same PR (breaking change to the view contract).

```sql
CREATE OR REPLACE VIEW wtf.aurora_layer_status AS
SELECT 'firewx'::text AS layer_key,
       'Fire-weather stations'::text AS layer_label,
       'Canadian Wildland Fire Information System (NRCan)'::text AS issuing_body,
       'public:firewx_stns_current'::text AS dataset_id,
       'https://cwfis.cfs.nrcan.gc.ca/'::text AS source_url,
       (SELECT max(rep_date)   FROM wtf.aurora_firewx_obs) AS data_latest,
       (SELECT max(fetched_at) FROM wtf.aurora_firewx_obs) AS last_pull,
       (SELECT count(*)        FROM wtf.aurora_firewx_obs) AS record_count,
       48::integer AS stale_after_hours
UNION ALL
SELECT 'hotspots', ... , 48
UNION ALL
SELECT 'perimeters', ... , 48
UNION ALL
SELECT 'city_observations', 'City current conditions',
       'Meteorological Service of Canada (Environment and Climate Change Canada)',
       'MSC Datamart citypage_weather',
       'https://dd.weather.gc.ca/today/citypage_weather/',
       (SELECT max(observed_utc) FROM wtf.aurora_city_obs),
       (SELECT max(fetched_at)   FROM wtf.aurora_city_obs),
       (SELECT count(*)          FROM wtf.aurora_city_obs),
       3
UNION ALL
SELECT 'city_forecasts', 'City forecasts',
       'Meteorological Service of Canada (Environment and Climate Change Canada)',
       'MSC Datamart citypage_weather',
       'https://dd.weather.gc.ca/today/citypage_weather/',
       (SELECT max(issued_utc)  FROM wtf.aurora_city_forecast),
       (SELECT max(fetched_at)  FROM wtf.aurora_city_forecast),
       (SELECT count(*)         FROM wtf.aurora_city_forecast),
       12;

GRANT SELECT ON wtf.aurora_layer_status TO wtfuser;   -- re-issued; do not omit
```

Notes:
- `observed_utc` / `issued_utc` are already `timestamptz` — no `::timestamptz` cast needed (unlike
  the `date`-typed hotspot/perimeter branches).
- Only the **first** branch carries `::text` casts and aliases; the rest are bare literals in the
  same positional order — a type mismatch fails at `CREATE OR REPLACE` time, but a branch silently
  returning `NULL` for `last_pull` makes `is_stale` permanently true, which looks like a dead feed.
- `source_url` deliberately points at the human-browsable `today/` path (that is what a reader
  should click); the **ingest** pins the dated path. These are different things and both are correct.
- Re-issue the `GRANT` after `CREATE OR REPLACE VIEW`. Postgres is believed to preserve it, but
  that was never verified in this repo and the statement is free.

Route change (`consumer/routes.py`, weather()):

```sql
SELECT layer_key, layer_label, issuing_body, dataset_id, source_url,
       data_latest, last_pull, record_count, stale_after_hours,
       (last_pull IS NULL
        OR last_pull < now() - make_interval(hours => stale_after_hours)) AS is_stale
FROM wtf.aurora_layer_status ORDER BY layer_key
```

---

## 3. Ingest module shape

Two modules. The split exists so the honesty logic can be unit-tested without a DB or Flask —
"a skipped test is indistinguishable from a passing one in the summary line."

### 3.1 `ingest/weather/citypage_parse.py` — **stdlib only**

No `sqlalchemy`, no `requests`, no network. Imports limited to `re`, `datetime`,
`xml.etree.ElementTree`. Loaded in tests via `importlib.util.spec_from_file_location`.

| Function | Responsibility | Defect it prevents |
|---|---|---|
| `parse_listing(html) -> list[str]` | Extract `.xml` names by matching **`href="..."` attributes**, not substring occurrences. Returns `[]` only when there were genuinely no matches. | The 2× miscount (Apache prints each name twice). |
| `parse_filename(name) -> (ts, site_code, lang) \| None` | `^(\d{8}T\d{6}\.\d{3}Z)_MSC_CitypageWeather_(s\d{7})_(en\|fr)\.xml$` | Legacy `<code>_e.xml` guessing (0 matches in a 508-file listing). |
| `select_latest(names, site_codes, lang="en")` | Per site, keep `max()` of the timestamp string **within one hour dir**. Drops other languages and unregistered codes. | `_fr` twins doubling row count; stale snapshot from a cached URL. |
| `_text(el) -> str \| None` | Strip; empty/whitespace → `None`. | Missing-Form-1 (present-but-empty). |
| `_num(el) -> float \| None` | `None` when el is `None` **or** text is empty. Never `or 0`. | `int(x or 0)` fabricating a zero reading. |
| `_coord(s) -> float \| None` | `'43.65N'→43.65`, `'79.38W'→-79.38`. Negates `W` and `S`. | Naive `rstrip('N')` putting Toronto in Kazakhstan. |
| `_dt_utc(parent, name) -> datetime \| None` | Selects `dateTime[@name=name][@zone='UTC']` **explicitly by attribute**; parses `timeStamp` `YYYYMMDDHHMMSS` as UTC-aware. | `findtext(...)` returning the first of two `dateTime`s and mixing local with UTC across sites (zones observed: EDT/CDT/PDT). |
| `_dt_local(parent, name) -> (zone, offset, ts)` | The non-UTC twin, kept as text + offset. | — |
| `wind_speed(el) -> (float\|None, bool)` | `'calm'/'Calm'/'calme'/'Calme'` → `(None, True)`. | `float('calm')` crash; calm written as 0. |
| `obs_gust(el) -> float \| None` | Empty → `None`. | Eureka NU: wind 32 km/h with empty gust → "gusts 0 km/h". |
| `forecast_gust(el) -> float \| None` | Literal **`'00'` → `None`** (sentinel); empty → `None`. | The single most dangerous value in the feed — it parses cleanly as `0` and defeats every `if not text` guard. 300 of 354 forecast gusts were `'00'`. |
| `pop(el) -> float \| None` | Empty → `None`. **Never 0.** | The daily feed emits 0 exactly never (755 empties, zero `'0'`s) while the hourly feed *does* emit a real `<lop category="Nil">0</lop>` — proof that empty ≠ zero. |
| `parse_current_conditions(root) -> dict \| None` | `None` when `<currentConditions/>` has zero children. | `NoneType` crash on an entire site instead of graceful degradation. |
| `parse_forecast_periods(root) -> (issued_utc, [dict])` | Label from the `textForecastName` **attribute**, weekday from element text. | Heading "Tuesday" on a period that is actually tonight. |
| `parse_site(xml_bytes) -> dict` | Top-level. **Takes BYTES** and hands them to `ET.fromstring` so the parser honours the declared encoding. | Decoding as UTF-8 mangles accented Québec/Acadian names (`siteList.xml` declares ISO-8859-1). |

Attribute access uses `el.get(...)` throughout — **never `el.attrib['units']`**. Measured: `humidex`
carries `unitType` with **no** `units`; `relativeHumidity` carries `units` with **no** `unitType`.
Neither attribute is guaranteed.

`qaValue` is **not** a presence flag and must not be used as one — pressure carried a real value
with no `qaValue` 71 times out of 119.

### 3.2 `ingest/weather/citypage.py` — DB + network

Mirrors `cwfis.py` exactly: stdlib `urllib`, `_HEADERS` with the same
`WTFIngest/1.0 (+https://what-the-fact.com; contact@what-the-fact.com)` UA, `_TIMEOUT`,
`engine.begin()` + `text()` executemany upserts.

| Function | Responsibility |
|---|---|
| `_archive_root(dt) -> str` | `https://dd.weather.gc.ca/{dt:%Y%m%d}/WXO-DD/citypage_weather/`. **Uses the target hour's own date** — at 00:xxZ the previous completed hour is 23 of *yesterday*. Never `today/`. |
| `_get(url, etag=None, last_mod=None)` | Conditional GET (`If-None-Match` / `If-Modified-Since`); returns `(status, body\|None, headers)`. 304 is a success, not an error. |
| `_pick_hour(now_utc) -> datetime` | Previous **completed** UTC hour. The current hour fills progressively and reading it early silently under-covers cities. |
| `refresh_site_registry(engine, dry_run)` | Fetches `siteList.xml` from the **dated archive path**, skips on unchanged `Last-Modified`. Validates every registered `site_code` still exists and still reports the same `source_prov`; refreshes `name_en`/`name_fr`. **Never auto-adds a city** — curation is an owner decision. Reports `unknown_codes` / `province_moved`. |
| `fetch_city_documents(hour_dt, sites)` | One directory listing per **distinct `source_prov`** (≤14, typically 6–8 for the city set), then one file per site via `select_latest`. **Asserts HTTP 200 AND a non-zero href count** before concluding a province published nothing. Any site missing from hour *H* is retried once at *H−1*. |
| `_upsert_obs(conn, rows)` | `ON CONFLICT (site_code, observed_utc) DO UPDATE ... fetched_at = now()`. |
| `_upsert_forecast(conn, rows)` | `ON CONFLICT (site_code, issued_utc, period_index) DO UPDATE ... fetched_at = now()`. |
| `_touch_registry(conn, statuses)` | Writes `last_seen_utc` + `last_obs_status` per site, including the failure statuses. |
| `run_citypage_sync(engine, dry_run=False) -> dict` | Orchestrates. Returns `{"fetched", "upserted", "obs_rows", "forecast_rows", "sites_no_observations", "sites_missing", "fetch_errors", "parse_errors", "hour"}` **or** `{"error": ...}`. |
| `_heartbeat(engine, task, result, exc)` | **Copied verbatim from `cwfis.py`.** Its counter chain reads `result.get("fetched")` and `result.get("upserted")` — this module deliberately reuses those exact key names so the heartbeat cannot log a truthful-looking 0/0. |
| `run_aurora_citypage(engine, dry_run=False) -> dict` | Single entry point. **Never raises.** Writes a heartbeat on the success path, the swallowed-`{"error": ...}` path, and the exception path. |
| `if __name__ == "__main__":` | `create_engine(os.environ["WTF_DATABASE_URL"])`, `--dry-run`. |

**Zero-result is a FAILURE, not an empty success** (the cwfis precedent):
- a listing returning 200 with **zero** `.xml` hrefs → `{"error": "citypage {PROV}/{HH} listing had 0 xml files — path or partition changed?"}`
- **all** registered sites missing from the listing → `{"error": ...}`. A *partial* miss is reported per-site and is not an error.

**Every drop is reported per category**, never silently swallowed: `sites_missing`,
`sites_no_observations`, `fetch_errors`, `parse_errors`. An unexpected category count moving is how
we learn the feed changed.

**Volume:** ~15 city files (~36 KB each) + ~7 province listings (~100 KB) ≈ **1.4 MB/hour**.
Sequential, `time.sleep(0.2)` between fetches, conditional GET on listings. Rate limits on this
host are **unverified** (§7) — keep the city list small and do not fan out to all 855 sites.

---

## 4. Schedule

No cron, no APScheduler. `ingest/run.py` `main()`, the same `while True:` loop that drives CWFIS
(`WTF_POLL_SECS`, default 1800).

1. Add `_last_citypage_hour = None` beside the existing `_last_aurora_date = None` initialiser.
2. Insert the block **immediately after** the CWFIS aurora block and **before** the drift-guard
   block — ordering is load-bearing, so the guard evaluates a heartbeat written *this pass*.

```python
        # A.U.R.O.R.A. Phase 2 — MSC city observations + forecasts, HOURLY.
        # Reads the PREVIOUS COMPLETED UTC hour from the dated archive path
        # (/YYYYMMDD/WXO-DD/...), which is reproducible; today/ flips wholesale
        # at 00:00Z. run_aurora_citypage never raises and writes its own
        # heartbeat on the success, swallowed-error and exception paths.
        hour_key = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H")
        if _last_citypage_hour != hour_key:
            try:
                from ingest.weather.citypage import run_aurora_citypage
                log.info("aurora citypage: %s", run_aurora_citypage(engine))
            except Exception:
                log.exception("aurora citypage crashed")
            _last_citypage_hour = hour_key
```

### drift_guard registration (both halves — one is not enough)

```python
    # A.U.R.O.R.A. Phase 2 city weather (#5760). HOURLY feed, so the threshold is
    # sub-day: 1 day would mean 24 consecutive missed pulls before anything says so.
    "aurora_citypage": float(os.environ.get("WTF_DRIFT_AURORA_CITYPAGE_DAYS", "0.25")),  # 6h
}

_REQUIRED_TASKS = {"aurora_firewx", "aurora_fire", "aurora_citypage"}
```

⚠️ **Two contained changes to `drift_guard.py` ship in the same PR or the alarm text lies:**
1. This is the first **float** entry in `_MAX_AGE_DAYS` (all others use `int(...)`). The comparison
   `float(age_days) > max_days` already handles floats correctly — no logic change needed.
2. The problem string formats the threshold with `%dd`, which renders `0.25` as **`0d`**. Replace
   with a helper: `"6h"` when `max_days < 1`, `"%dd"` otherwise. Without this, the alarm reads
   "last success 0d ago (> 0d threshold)".

Registering in `_MAX_AGE_DAYS` **without** `_REQUIRED_TASKS` is the documented failure mode: a task
with zero `ingest_log` rows is skipped as "not yet tracked", so a puller that is never actually
wired into `run.py` reports green forever.

---

## 5. UI surface

### 5.1 Pure payload builder — extend `consumer/aurora_map.py`

Add `_aurora_cities_payload(site_rows, obs_rows, forecast_rows, now_utc)` to the **existing**
stdlib-only module rather than creating a new one. Reason: a new module would need
`from .aurora_map import _canon_prov, _r`, and a relative import breaks the
`spec_from_file_location` test harness that exists precisely so these tests cannot skip. One
module, one `_canon_prov`, one `_r`, one harness.

Also extend the canon map:

```python
_PROV_CANON = {"NF": "NL", "PQ": "QC", "NF ": "NL", "HEF": None}
#                                                   ^ MSC highway-corridor pseudo-province:
#   11 BC road segments, NOT a province. Mapped to None so a stray row can never
#   render a 14th province on the map. Safe for CWFIS, which never emits HEF.
```

Payload rules, all inherited from the Phase 1 contract:
- `_r(v, nd)` for the wire; **`None` stays `None`, never `0.0`**.
- A city absent from a layer is **absent**, never zero.
- Counts present are `int(x or 0)`; measurements are never coerced.
- `wind_is_calm` travels as its own boolean — the template renders "Calm", not "0 km/h".

### 5.2 Route (`consumer/routes.py`, `weather()`)

Three additional queries inside the existing `with _db().begin() as c:` block:

```sql
-- registry
SELECT site_code, source_prov, name_en, name_fr, display_name, lat, lon,
       last_seen_utc, last_obs_status
FROM wtf.aurora_city_site WHERE is_city ORDER BY sort_order, name_en;

-- latest observation per site (DISTINCT ON, not a correlated subquery)
SELECT DISTINCT ON (site_code) *
FROM wtf.aurora_city_obs ORDER BY site_code, observed_utc DESC;

-- latest forecast issue, first 3 periods
SELECT f.* FROM wtf.aurora_city_forecast f
JOIN (SELECT site_code, max(issued_utc) AS iss
      FROM wtf.aurora_city_forecast GROUP BY site_code) m
  ON m.site_code = f.site_code AND m.iss = f.issued_utc
WHERE f.period_index < 3
ORDER BY f.site_code, f.period_index;
```

### 5.3 Template (`consumer/templates/weather.html`)

A **Cities** section above the existing fire panels, rendering one card per registry row:

- **Header** — `display_name or name_en`, plus the province label resolved from `_canon_prov` →
  `_PROV_NAMES`. Never `source_prov` raw (a card reading "HEF" is the map-province bug in miniature).
- **Temperature** — `temp_c`, or `—` when `None`.
- **Condition** — `condition_text`, or `—`. Empty is the *normal* case for 52 of 60 sites.
- **Feels like** — `humidex` if not `None`, else `wind_chill` if not `None`, else the row is
  **omitted entirely**. Both absent is normal (summer/winter respectively).
- **Wind** — `Calm` when `wind_is_calm`; otherwise speed + direction. The **gust line renders only
  when `wind_gust_kmh is not None`** — never "gusts 0".
- **Humidity / dewpoint / pressure** — pressure tendency arrow only when `pressure_tendency` is not
  `None` (the attribute is dropped when `change=""`).
- **Visibility** — row rendered **only** when not `None`.
- **Observed** — local string + zone + `(HH:MMZ)`, with `data-utc` for client-side formatting.
- **Station attribution (mandatory)** — *"Observed at {station_name}"* with the station's own
  coordinates. Toronto's reading comes from Pearson, ~20 km from the city point; attributing it to
  the city coordinates misstates provenance.
- **No-observation state** — when there is no obs row, the card says which it is, driven by
  `last_obs_status`: *"MSC published no observations for this site"* vs *"we could not reach the
  source"*. These must not collapse into one grey box.
- **Staleness** — badge when `observed_utc` is older than the `city_observations` row's
  `stale_after_hours`.
- **Forecast strip** — 3 periods. Heading from `period_label` (the **attribute**). High/low from the
  two columns. **POP rendered only when `pop_pct is not None`** — never "0% chance of rain", which
  would invent a forecast the source declined to make. Gust only when not `None`.
- **Provenance** — unchanged. The existing `{% for L in layers %}` strip picks up
  `city_observations` and `city_forecasts` automatically. **No source name is written into the
  template.** Note that the existing guard forbids the literal `Environment Canada` in
  `weather.html`; the issuing body travels through the view row, which the textual test cannot see
  and must not need to.

---

## 6. Guard tests

New file `tests/test_aurora_citypage.py`, loading `citypage_parse.py` and `aurora_map.py` via
`importlib.util.spec_from_file_location` — **no Flask, no SQLAlchemy import anywhere in the test
path**, so nothing can silently skip.

**Parser honesty (fixture-driven, offline):**

| Test | Pins |
|---|---|
| `test_empty_gust_is_none_not_zero` | `<gust unitType="metric" units="km/h"></gust>` beside `speed 32` → `None`, and the row does not read "gusts 0". |
| `test_forecast_gust_00_sentinel_is_none` | `<gust ...>00</gust>` → `None`. The value parses cleanly as `0` and defeats every empty-check. |
| `test_empty_pop_is_none_not_zero` | Daily `<pop units="%"/>` → `None`; hourly `<lop category="Nil">0</lop>` → `0.0`. Both in one test — the contrast *is* the property. |
| `test_calm_wind_does_not_crash_and_is_not_zero` | `'calm'` → `(None, True)`. |
| `test_absent_visibility_returns_none` | No `<visibility>` element → `None`, no `AttributeError`. Absence is normal, not an anomaly to log. |
| `test_self_closed_current_conditions_yields_no_row` | `<currentConditions/>` → `parse_current_conditions` returns `None`; the sync records `no_observations` and writes no obs row. |
| `test_datetime_selected_by_zone_attribute` | Fixture with the **local** `dateTime` first → still returns the UTC one. |
| `test_coordinates_negate_west_and_south` | `'79.38W'` → `-79.38`; `'43.65N'` → `43.65`. |
| `test_period_label_comes_from_the_attribute` | `<period textForecastName="Tonight">Tuesday night</period>` → label `Tonight`, weekday `Tuesday night`. |
| `test_unit_attributes_may_be_absent` | `<humidex unitType="metric">28</humidex>` (no `units`) and `<relativeHumidity units="%">44</relativeHumidity>` (no `unitType`) both parse. |
| `test_listing_parser_counts_hrefs_not_substrings` | Apache-autoindex fixture where each filename appears twice → each file counted **once**. Direct regression for the 2× miscount. |
| `test_select_latest_picks_max_timestamp_and_drops_fr` | Three `_en` + three `_fr` for one site → one `_en`, the largest timestamp. |

**Structural / governance:**

| Test | Pins |
|---|---|
| `test_ingest_targets_only_the_approved_host` | `"dd.weather.gc.ca" in src`; `"api.weather.gc.ca/collections" not in src`; `"dd.alpha.weather.gc.ca" not in src`. ADR-001. |
| `test_ingest_uses_the_dated_archive_path` | `"WXO-DD" in src` and the module does **not** contain `"/today/citypage_weather"` as a fetch target. |
| `test_ingest_does_not_use_the_legacy_paths` | `"citypage_weather/xml/"` and `"_e.xml"` absent — both are 404s on this host. |
| `test_drift_guard_watches_citypage` | `"aurora_citypage"` present in **both** `_MAX_AGE_DAYS` and `_REQUIRED_TASKS`. |
| `test_drift_guard_threshold_message_handles_sub_day` | The threshold formatter renders `0.25` as `6h`, not `0d`. |
| `test_heartbeat_fires_on_swallowed_error` | `run_aurora_citypage` with a stubbed sync returning `{"error": ...}` writes the **error** branch, not a success row. The exact defect that let lobbying and ethics rot green for months. |
| `test_result_keys_match_the_heartbeat_vocabulary` | The sync's result dict uses `fetched`/`upserted`, the keys `_heartbeat` actually reads. |
| `test_hef_never_becomes_a_province` | `_canon_prov("HEF") is None`. |
| `test_registry_seed_has_no_unverified_codes` | Every seeded `site_code` in migration 054 appears in a checked-in allowlist of codes verified against `siteList.xml`. Blocks guessed capitals. |

**Migration lint — new file `tests/test_migration_grants.py`** (no such test exists today; the
invariant is currently only prose):

| Test | Pins |
|---|---|
| `test_every_new_table_grants_to_wtfuser` | For each `CREATE TABLE ... wtf.<name>` in `migrations/0[5-9]*.sql`, the same file contains `GRANT SELECT, INSERT, UPDATE, DELETE ON wtf.<name> TO wtfuser`. |
| `test_every_bigserial_table_grants_its_sequence` | …and `GRANT USAGE, SELECT ON SEQUENCE wtf.<name>_id_seq TO wtfuser`. A missing sequence grant fails at **runtime** on `nextval`, long after the migration reported success. |
| `test_view_replacement_reissues_its_grant` | Any file containing `CREATE OR REPLACE VIEW wtf.aurora_layer_status` also contains `GRANT SELECT ON wtf.aurora_layer_status TO wtfuser`. |

*(Scoped to migrations ≥ 050 so legacy files do not turn the suite red on day one; widening the
scope is a follow-up task.)*

**Extend the existing `tests/test_aurora_provenance.py`:**
- `test_weather_template_names_no_data_source_directly` — unchanged, now also covers the city section.
- New `test_route_supplies_stale_after_hours` — `"stale_after_hours"` in `routes.py`, so the 48h
  literal cannot survive for an hourly layer.

---

## 7. open_questions

**Blocking a complete city list:**
1. **No verified site code exists for NT, NU, YT or PE.** Yellowknife, Iqaluit, Whitehorse and
   Charlottetown were never looked up. Fredericton and Moncton likewise. **Resolve by querying
   `siteList.xml` and pinning the exact code — do not guess by name.** `Ottawa` proves why: there is
   no bare-name entry at all. Until resolved, four territories/provinces have no card.
2. **Substring name matching is unsafe.** `Victoria` matches 6 rows across two provinces; `John`
   collides `St. John's` NL / `Saint John` NB / `Fort St. John` BC; `Toronto` also matches
   `Toronto Island`. Airport/park variants exist beside city entries (Calgary s0000047 vs s0000126
   Olympic Park; Edmonton s0000045 vs s0000510 Int'l Aprt). The "lower-numbered bare-name code is
   the city" is an *observed pattern*, not a guaranteed rule — pin codes, never resolve by name at
   runtime.

**Unverified upstream behaviour:**
3. **Rate limits / throttling on dd.weather.gc.ca were never probed.** The design is sized for ~22
   requests/hour. Do not scale toward 855 sites without measuring first.
4. **How early in a UTC hour full province coverage is reached is unknown.** The design sidesteps
   this by reading the previous *completed* hour, but the H−1 retry path is untested against a real
   partial hour.
5. **Whether `siteList.xml` ever changes** (sites added/retired) and at what cadence. Its
   `Last-Modified` is 2025-06-25, i.e. unchanged for over a year — but that is one observation.
   `refresh_site_registry` is designed to *detect* a change, not to assume one won't happen.
6. **The exact retention window.** 31 dated dirs were listed and the oldest (20260720) was confirmed
   genuinely populated, implying ~30 days. The boundary was not tested.
7. **`HEF`'s expansion is unknown.** All 11 entries are demonstrably BC highway segments; no official
   definition was retrieved. The design treats it as data (`is_city=false`) rather than encoding a
   meaning we cannot cite.
8. **`docs/` and `forecastFull.xsd` were never read.** `schema/` returns 200 with 6 entries;
   `weather.xsd` and `general.xsd` were read, the rest were not.
9. **`currentConditions/temperature`, `dewpoint` and `relativeHumidity` were never observed
   empty-but-present** in 120 files — but the XSD unions the empty string into every numeric type,
   so the parser must still handle it. `_num` does.
10. **Whether a genuine `0` is ever emitted for current-conditions wind speed** (as opposed to
    `calm`) is unknown. `wind_speed_kmh=0` with `wind_is_calm=false` would be the honest encoding
    if it occurs.
11. **Winter behaviour is inferred, not observed.** All sampling was one summer hour, which is why
    `windChill` was absent in 60/60 files. `humidex` present / `windChill` absent will invert.
12. **The `_fr` documents were never parsed for content** (only confirmed genuinely French by a
    header string). Phase 2 ingests `_en` only.

**Design decisions requiring an owner call:**
13. **Weather warnings are NOT ingested.** `<warnings />` was only ever observed **empty**; the
    populated shape has never been seen. Building a warnings table on a guessed schema is exactly
    the failure this project keeps fixing — but a city card that silently omits an active weather
    warning is a real editorial risk. **A live warning must be captured and its markup recorded
    before this is designed.** Flag as a known Phase 2 gap on the page itself.
14. **Hourly forecasts (24 per site) and `regionalNormals` are out of scope.** Both are verified to
    exist and parse; neither has a table. Phase 3 candidates.
15. **The sub-day drift threshold (`0.25`) is the first float in `_MAX_AGE_DAYS`** and requires the
    message-formatting fix in §4. Alternative: leave the guard at `1` day and accept that 24 missed
    hourly pulls go unreported. Recommendation is the float; the trade-off is a two-line change to a
    shared module.
16. **The view gains `stale_after_hours`, a breaking contract change.** The route and any other
    consumer must ship in the same PR. Alternative is leaving the hardcoded 48h, which would render
    a 40-hour-old "current conditions" card as fresh.

**Repo-level, unresolved from Phase 1:**
17. **How migrations are actually applied is still unknown** — no runner, nothing in `deploy.sh`,
    nothing in `scripts/`. Assume manual `psql -f` against the hub `wtf` database until confirmed.
    It is also unconfirmed whether migration 053 has been applied to the live DB.
18. **Whether `CREATE OR REPLACE VIEW` preserves the existing `GRANT`** was never tested. The
    migration re-issues it unconditionally, so this is de-risked rather than answered.
19. **Whether the drift guard's existing aurora thresholds are currently passing in production** was
    not checked (`parliament.ingest_log` was never queried).