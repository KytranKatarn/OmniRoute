# Civic Transparency — Phase 1: GEDS Directory Ingestion

**Date**: 2026-05-04
**Status**: Design — pending user approval
**Parent**: Civic Transparency — Federal Accountability Dashboard (master)
**Owner**: Civic Watch product (VPS, port 8099)
**Schema**: new `civic_transparency` schema on hub Postgres (shared with `gov_watch`)

## Goal

Build a self-refreshing, queryable registry of every public servant listed in the Government of Canada's GEDS-SAGE directory (https://geds-sage.gc.ca), plus the four "quick link" lists (Ministers, Deputy Ministers, Senators, MP Offices). Phase 1 delivers:

1. **Internal dataset** — usable from A.R.C.H.I.E. dispatch, hub queries, drafting bot.
2. **Public registry view** at `civic.kytranempowerment.com/transparency/registry` — searchable, departmentally-scoped, citation-disciplined.

Phase 1 does **not** include spending, demographics, or the bias-thesis dashboards — those are Phases 2–5.

## Scope

### In scope
- Walk the full GEDS organization tree (departments → branches → units → people).
- Ingest the four `pgid=016` quick lists (`fid=10`/`11`/`12`/`13`).
- Daily diff-aware refresh: track new/departed/title-changed records.
- Per-department coverage flag (`full | partial | none | opted_out`).
- Public web routes: registry index + per-department drilldown.
- Citation discipline: every rendered number carries a "source: GEDS — fetched YYYY-MM-DD" attribution.

### Out of scope (deferred)
- Salaries, contracts, spending (Phase 2–3).
- Demographic / employment-equity overlay (Phase 4).
- Cross-cutting analytical dashboards (Phase 5).
- Anything requiring inference beyond what GEDS publishes verbatim.

## Data sources

| Endpoint | Purpose | Format |
|---|---|---|
| `GET /en/GEDS?pgid=012` | Master department listing | HTML, list of `<a href="?pgid=014&dn=<base64-DN>">Name</a>` |
| `GET /en/GEDS?pgid=014&dn=<base64-DN>` | Walk tree (org → branch → unit → person) | HTML, recursive |
| `GET /en/GEDS?pgid=011&sv=&sf=5&sc=1&...` | Free-text search by Organization | HTML paginated |
| `GET /en/GEDS?pgid=016&fid=10` | Honourable Ministers | HTML pre-rendered list |
| `GET /en/GEDS?pgid=016&fid=11` | Deputy Ministers | HTML |
| `GET /en/GEDS?pgid=016&fid=12` | Honourable Senators | HTML |
| `GET /en/GEDS?pgid=016&fid=13` | MP Offices | HTML |

The `dn` parameter is base64-encoded LDAP-style DN, e.g. `OU=CSIS-SCRS,O=GC,C=CA`. Trivially encoded/decoded.

## Architecture

```
                                   ┌─────────────────────────────┐
                                   │  archie_scheduler (sidecar) │
                                   │  job: civic_geds_refresh    │
                                   │  cron: 03:30 UTC daily      │
                                   └─────────────┬───────────────┘
                                                 │ triggers
                                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                  civic_transparency.geds_scraper                 │
│                                                                  │
│  Pass A: tree walk                                               │
│    pgid=012 → org list                                           │
│    pgid=014&dn=... → recursive walk to leaves                    │
│    Output: org_units rows (idempotent upsert by dn)              │
│                                                                  │
│  Pass B: people sweep                                            │
│    For each leaf org_unit, paginate person listing               │
│    Output: federal_employees rows (upsert by source_dn)          │
│                                                                  │
│  Pass C: quick lists                                             │
│    pgid=016&fid=10/11/12/13 → enrich existing records w/ role    │
│                                                                  │
│  Diff: compare snapshot vs prior, emit movement records          │
└────────────────────────────────┬─────────────────────────────────┘
                                 │ writes
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  civic_transparency schema (hub Postgres)                        │
│  org_units · federal_employees · geds_snapshots · geds_movements │
└────────────────────────────────┬─────────────────────────────────┘
                                 │ reads
                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│  Civic Watch Flask app (VPS :8099)                               │
│  /transparency/registry              — index                     │
│  /transparency/registry/<abbr>       — department drilldown      │
│  /transparency/registry.json?...     — JSON API                  │
│  /transparency/movements             — daily diff feed           │
└──────────────────────────────────────────────────────────────────┘
```

### Stack
- **Language**: Python 3.11 (matches civic-watch stack)
- **HTTP**: `httpx` (async, HTTP/2)
- **HTML parsing**: `selectolax` (Modest-engine, ~10× faster than BeautifulSoup; handles GEDS's mixed Latin-1/UTF-8 cleanly with `decode='auto'`)
- **DB**: `psycopg2` against existing hub Postgres
- **Scheduler**: existing `archie_scheduler` sidecar — add `civic_transparency_geds_refresh` to job registry
  - **No new docker volume mounts required**. This job does HTTP-out + DB-write only; no filesystem reads. This is intentional — KB mistake_learned #263320/#263319 documented the silent-failure mode where `archie_scheduler` lost code-health visibility because its mounts drifted from `archie_platform`. Spec is free of that footgun by construction.
- **Throttle pattern**: if a manual "scrape now" button is added to the Civic Watch admin UI in a future phase, follow the WTF-hub pattern (KB mistake_learned #261657) — module-level per-task timestamp dict in routes, returning `{ok: true, rate_limited: true}` on cooldown. Default cooldown 1h for manual triggers (the nightly job is canonical).

### Throttling & politeness
- Single User-Agent: `ARCHIE-CivicWatch/1.0 (+https://civic.kytranempowerment.com/about)` — identifies us, links back.
- Rate ceiling: **2 req/sec hard cap**, single-host concurrency 1 (asyncio.Semaphore).
- Retry: 3 attempts with exponential backoff (1s/4s/16s) on 5xx and timeouts. Hard fail on 4xx (logged, item skipped).
- Total runtime budget: ≤ 12 hours per nightly run. If exceeded, persist progress and resume next night.
- Adaptive backoff: any 429 → pause 60s, halve rate.

### Charset handling
- All HTML decoded with `httpx`'s charset-detection then re-encoded to UTF-8 at fetch boundary.
- Raw response body stored in `geds_raw_pages` (TTL 7 days) so a parser change can be re-played without re-crawling.

## Schema

```sql
CREATE SCHEMA IF NOT EXISTS civic_transparency;

CREATE TABLE civic_transparency.org_units (
    id              SERIAL PRIMARY KEY,
    parent_id       INTEGER REFERENCES civic_transparency.org_units(id),
    dn              TEXT NOT NULL UNIQUE,            -- decoded LDAP DN
    dn_b64          TEXT NOT NULL,                   -- as appears in URLs
    level           SMALLINT NOT NULL,               -- 0=dept, 1=branch, ...
    name_en         TEXT NOT NULL,
    name_fr         TEXT,
    abbreviation_en TEXT,                            -- e.g., "CSIS"
    abbreviation_fr TEXT,                            -- e.g., "SCRS"
    coverage        TEXT NOT NULL DEFAULT 'unknown'  -- full|partial|none|opted_out|unknown
                    CHECK (coverage IN ('full','partial','none','opted_out','unknown')),
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_org_units_parent ON civic_transparency.org_units(parent_id);
CREATE INDEX idx_org_units_abbr_en ON civic_transparency.org_units(abbreviation_en);

CREATE TABLE civic_transparency.federal_employees (
    id               SERIAL PRIMARY KEY,
    source_dn        TEXT NOT NULL UNIQUE,           -- stable identity in GEDS
    org_unit_id      INTEGER NOT NULL REFERENCES civic_transparency.org_units(id),
    surname          TEXT NOT NULL,
    given_name       TEXT,
    title_en         TEXT,
    title_fr         TEXT,
    classification   TEXT,                           -- "EX-03", "PM-06", etc. when present
    role_tag         TEXT,                           -- minister | deputy_minister | senator | mp | NULL
    phone            TEXT,
    email            TEXT,
    location_en      TEXT,
    manager_dn       TEXT,                           -- forward ref; resolved post-pass
    manager_id       INTEGER REFERENCES civic_transparency.federal_employees(id),
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen        TIMESTAMPTZ NOT NULL DEFAULT now(),
    departed_at      TIMESTAMPTZ                     -- set when no longer in directory
);
CREATE INDEX idx_fed_emp_org ON civic_transparency.federal_employees(org_unit_id);
CREATE INDEX idx_fed_emp_role ON civic_transparency.federal_employees(role_tag) WHERE role_tag IS NOT NULL;
CREATE INDEX idx_fed_emp_classification ON civic_transparency.federal_employees(classification);
CREATE INDEX idx_fed_emp_active ON civic_transparency.federal_employees(departed_at) WHERE departed_at IS NULL;

CREATE TABLE civic_transparency.geds_snapshots (
    id                  SERIAL PRIMARY KEY,
    run_started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_finished_at     TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN ('running','completed','partial','failed')),
    org_units_seen      INTEGER NOT NULL DEFAULT 0,
    employees_seen      INTEGER NOT NULL DEFAULT 0,
    employees_new       INTEGER NOT NULL DEFAULT 0,
    employees_departed  INTEGER NOT NULL DEFAULT 0,
    employees_changed   INTEGER NOT NULL DEFAULT 0,
    error_message       TEXT
);

CREATE TABLE civic_transparency.geds_movements (
    id              SERIAL PRIMARY KEY,
    snapshot_id     INTEGER NOT NULL REFERENCES civic_transparency.geds_snapshots(id),
    employee_id     INTEGER REFERENCES civic_transparency.federal_employees(id),
    movement_type   TEXT NOT NULL CHECK (movement_type IN ('new','departed','title_changed','org_changed','classification_changed')),
    before_value    JSONB,
    after_value     JSONB,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_geds_movements_snapshot ON civic_transparency.geds_movements(snapshot_id);
CREATE INDEX idx_geds_movements_emp ON civic_transparency.geds_movements(employee_id);

CREATE TABLE civic_transparency.geds_raw_pages (
    id           BIGSERIAL PRIMARY KEY,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    url          TEXT NOT NULL,
    status_code  SMALLINT NOT NULL,
    body         BYTEA,                              -- raw, gzipped
    purge_after  TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '7 days')
);
CREATE INDEX idx_geds_raw_purge ON civic_transparency.geds_raw_pages(purge_after);
```

## Public surface (week 1)

All routes on Civic Watch (`civic.kytranempowerment.com`):

| Route | Purpose |
|---|---|
| `GET /transparency/` | Landing — explains methodology, citation, limitations (esp. "some depts opt out") |
| `GET /transparency/registry` | Searchable index: department, abbr, headcount, EX/SM count, coverage flag, last_updated |
| `GET /transparency/registry/<abbr>` | Per-dept drilldown: full org tree, headcount-by-classification breakdown, link to GEDS source |
| `GET /transparency/registry.json` | JSON API with filters (`?dept=`, `?role=`, `?classification=`) |
| `GET /transparency/movements` | Daily diff feed: who joined, who left, who changed title (24h / 7d / 30d windows) |
| `GET /transparency/about` | Methodology, source attribution, last refresh timestamp, refresh cadence, caveats |

**Rendering rules**:
- Every numeric claim shows `(source: GEDS, fetched 2026-05-04)`.
- "Coverage: partial — agency does not list all employees" banner on any dept where applicable.
- No editorial framing. Data renders; analysis lives in user's own posts/threads.

## Failure modes & mitigations

| Failure | Mitigation |
|---|---|
| GEDS rate-limits us (429) | Adaptive backoff, halve rate, retry next day |
| GEDS HTML structure changes | Raw-page table allows replay against new parser; selector-based parser logged with version |
| Charset corruption on edge pages | UTF-8 normalization at fetch; failed records logged to `geds_raw_pages` for manual review |
| Phantom departures (transient parse failure flags everyone as departed) | A `departed_at` is only set if the employee is missing in **two consecutive** snapshots |
| Identity drift (DN reused for different person) | Surname mismatch detection: if `source_dn` matches but surname changes, treat as new person, retire old record |
| Hub Postgres write contention with `gov_watch` workload | New schema isolates tables; runs at 03:30 UTC (off-peak) |

## Acceptance criteria

Phase 1 is complete when:

1. ✅ `civic_transparency.geds_snapshots` has at least 2 successful consecutive `completed` runs.
2. ✅ `org_units` count matches GEDS `pgid=012` department count ±2 (allows for in-flight changes).
3. ✅ `federal_employees` count is non-zero for every department flagged `coverage='full'`.
4. ✅ Quick-list roles are populated: Ministers, DMs, Senators, MP Offices have `role_tag` set.
5. ✅ `/transparency/registry` renders on civic-watch with department list + headcounts + last_updated.
6. ✅ `/transparency/registry/<abbr>` renders per-dept drilldown with classification breakdown.
7. ✅ Movement feed shows non-empty diff after second run.
8. ✅ Citation banner present on all rendered numbers.
9. ✅ Coverage flags accurately distinguish full vs partial vs opted-out depts (verified against ~5 known cases: TBS=full, CSIS=partial, RCMP=partial).
10. ✅ Daily refresh job registered in archie_scheduler and observed firing for 3 consecutive nights.

## Open questions (must resolve before writing the implementation plan)

1. **VPS civic-watch → hub Postgres connection path.** Civic Watch runs on VPS (76.13.107.109, port 8099) but this spec puts `civic_transparency` schema on hub Postgres. The Phase 1 implementer must verify either: (a) civic-watch already has a Tailscale-mesh DB connection to hub Postgres (likely — gov-watch does, per KB), or (b) we ingest hub-side and serve the public routes via a hub→VPS proxy or via Tailscale-direct query from VPS. Cheapest answer: replicate gov-watch's connection pattern. Implementation plan must verify before writing migrations.
2. **Manager DN resolution timing.** GEDS leaf person rows include a manager_dn pointing to another row. We can't resolve manager_id during the same pass without keeping the whole graph in memory. The implementation plan should either (a) two-pass: first pass writes manager_dn, second pass resolves, or (b) defer resolution to a downstream job. (a) is simpler; recommend (a).
3. **Where exactly does the scraper service run?** Hub-side (next to the schema) is simplest and matches the no-new-mounts policy. VPS-side would require opening a hub-Postgres connection from VPS. Recommend hub-side (`platform_v2/services/civic_transparency_scraper.py`), invoked nightly by `archie_scheduler`.

## Risks beyond data quality

- **Public scrutiny**: Once `/transparency/registry` is public, GoC may contact us. Have an `/about` page ready with methodology + opt-out contact (anyone listed can request removal — though source is public). Mitigation: store explicit `redacted_by_request` flag column; log redaction reasons; honour requests within 48h.
- **Legal**: Public data, public methodology. Pre-launch sanity check by Kytran before flipping the public route on. Internal dataset can be ingested without legal review since it's just data we hold.
- **GEDS terms-of-use**: Page footer says "Government of Canada open license" applies. We should reproduce the open-license attribution on `/transparency/about`.

## Out of Phase 1 (so we don't sprawl)

- Spending cross-reference (Phase 2)
- Contract / consultant data (Phase 3)
- Equity / demographic overlay (Phase 4)
- Cross-cutting analytical dashboards: NCR-vs-regions, exec-rank skew, consultant leakage rankings (Phase 5)
- ML / clustering / org-chart visualization
- Salary band imputation from classification (deferred to Phase 2)
