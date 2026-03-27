# Canadian Civic Intelligence — Design Spec

**Date:** 2026-03-27
**Project:** Kytran News + Civic Intelligence Platform
**Agent:** W.A.T.C.H. (Watchdog for Accountability, Transparency, Civic Health)
**Status:** Approved

---

## Overview

Add Canadian civic data (government contracts, parliamentary activity, public spending) to Kytran News as map layers, backed by a dedicated W.A.T.C.H. API service and AI agent. Expand into a standalone civic dashboard at civic.kytranempowerment.com, with a long-term path to WhatTheFact.ca as a public accountability brand.

## Goals

1. Centralize federal, provincial, and municipal civic data on a single map
2. Create W.A.T.C.H. as the 17th AI Director for civic intelligence
3. Ship 3 new map layers on thenews.kytranempowerment.com
4. Build a civic deep-dive dashboard at civic.kytranempowerment.com
5. Architect for eventual WhatTheFact.ca brand expansion

## Non-Goals (This Spec)

- Public response / voting system (Phase 3)
- WhatTheFact.ca domain purchase or branding (Phase 3)
- Real-time parliamentary streaming (no API supports this)
- Paid data sources (all sources must be free, no API keys)

---

## Architecture

### Three Tiers

| Tier | What | Where | Phase |
|------|------|-------|-------|
| Map Layers | 3 new data layers on Kytran News | thenews.kytranempowerment.com | 1 |
| Civic Dashboard | Deep-dive civic intelligence with W.A.T.C.H. analysis | civic.kytranempowerment.com (Hostinger) | 2 |
| WhatTheFact | Public accountability brand with community response | whatthefact.ca (future) | 3 |

### System Diagram

```
Open Canada / OpenParliament / Provincial / Municipal APIs
        |
        v (agent loop: federal 6h, provincial 24h, municipal 24h)
  W.A.T.C.H. ingestion + normalization + AI analysis
        |
        v
  SQLite DB (civic_events, contracts, bills, votes, spending)
        |
        v
  W.A.T.C.H. API (kytran_watch_api, port 8099)
        |
        +---> thenews.kytranempowerment.com (3 map layers via fetcher.js)
        |
        +---> civic.kytranempowerment.com (deep-dive dashboard, Hostinger static)
```

---

## W.A.T.C.H. Agent

- **Full name:** Watchdog for Accountability, Transparency, Civic Health
- **Department:** Analytics & Intelligence (S.P.E.C.T.R.A.'s floor — SERVICES)
- **Role:** 17th AI Director
- **Agent ID:** Next available in `agents` table
- **Shift state:** active
- **Station:** SERVICES floor

### Capabilities

- Summarize Hansard debates in plain language via Bridge dispatch
- Flag spending anomalies (contracts significantly above estimates, sole-source awards over $1M)
- Connect legislative chains: bill passed -> budget allocated -> contracts awarded -> news coverage
- Generate normalized civic event cards with multi-source context
- Provincial/municipal data normalization (different schemas -> unified format)

### Agent Loop Jobs

| Job | Frequency | What |
|-----|-----------|------|
| Federal data pull | Every 6 hours | Open Canada contracts, OpenParliament bills/votes/debates |
| Provincial data pull | Every 24 hours | ON, BC, AB, QC open data portals |
| Municipal data pull | Every 24 hours | Toronto, Vancouver, Montreal, Ottawa |
| Anomaly scan | Every 12 hours | Flag sole-source contracts >$1M, spending spikes, unusual patterns |
| Event chain linking | Every 12 hours | Connect bills -> budgets -> contracts -> news via keyword matching |

---

## Data Sources

### Federal (Phase 1a)

| Source | API Endpoint | Data | Format | Rate Limit |
|--------|-------------|------|--------|-----------|
| Open Canada CKAN | `open.canada.ca/data/en/api/3/action/package_search` | Contracts >$10K, grants, spending | JSON | No key, GET only |
| OpenParliament.ca | `api.openparliament.ca/bills/`, `/votes/`, `/debates/` | Bills, votes, Hansard transcripts | JSON | No key, be polite |
| House of Commons | `ourcommons.ca` XML feeds | Hansard, committees, sitting calendar | XML | No key |
| GDELT Canada | `api.gdeltproject.org/api/v2/doc/doc?query=sourcecountry:CA` | Canadian news | JSON | 5s rate limit (already queued) |

### Provincial (Phase 1c)

| Province | Portal | API Base | Data |
|----------|--------|----------|------|
| Ontario | data.ontario.ca | CKAN API | Contracts, spending, transfer payments |
| British Columbia | catalogue.data.gov.bc.ca | CKAN API | Contracts, public accounts |
| Alberta | open.alberta.ca | CKAN API | Contracts, grants, capital spending |
| Quebec | donneesquebec.ca | CKAN API | Contracts (SEAO), budget data |

### Municipal (Phase 1d)

| City | Portal | API Base | Data |
|------|--------|----------|------|
| Toronto | open.toronto.ca | CKAN API | Contracts, budget, council votes |
| Vancouver | opendata.vancouver.ca | CKAN API | Contracts, budget, permits |
| Montreal | donnees.montreal.ca | CKAN API | Contracts, budget, council decisions |
| Ottawa | open.ottawa.ca | CKAN API | Contracts, budget |

---

## W.A.T.C.H. API Service

### Infrastructure

| Component | Detail |
|-----------|--------|
| Container | `kytran_watch_api` |
| Port | 8099 (mapped to internal 8080) |
| Framework | Flask |
| Database | SQLite (standalone, not ARCHIE's Postgres) |
| Docker | docker-compose.yml in `watch-api/` directory |
| Subdomain | `civic.kytranempowerment.com` via NPM proxy + SSL |
| Compliance | read_only rootfs, resource limits, pinned tags |

### Database Schema

```sql
-- Normalized civic events (all levels)
CREATE TABLE civic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,          -- contract, bill, vote, spending, debate
    level TEXT NOT NULL,               -- federal, provincial, municipal
    jurisdiction TEXT NOT NULL,        -- Canada, Ontario, Toronto, etc.
    title TEXT NOT NULL,
    description TEXT,
    amount REAL,                       -- dollar value (contracts/spending)
    department TEXT,                   -- issuing department/ministry
    vendor TEXT,                       -- contract recipient (if applicable)
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    source_url TEXT,
    source_name TEXT,
    raw_id TEXT,                       -- original ID from source API
    event_date TEXT NOT NULL,          -- ISO 8601
    ingested_at TEXT NOT NULL,
    metadata TEXT,                     -- JSON blob for source-specific fields
    UNIQUE(raw_id, source_name)
);

-- Parliament-specific
CREATE TABLE parliament_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_number TEXT NOT NULL,         -- e.g. C-42, S-15
    title TEXT NOT NULL,
    summary TEXT,                      -- W.A.T.C.H. AI-generated plain language summary
    sponsor TEXT,
    status TEXT,                       -- introduced, committee, passed, royal_assent, defeated
    introduced_date TEXT,
    last_activity_date TEXT,
    session TEXT,                      -- e.g. 44-1
    source_url TEXT,
    UNIQUE(bill_number, session)
);

CREATE TABLE parliament_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vote_number INTEGER,
    bill_number TEXT,
    description TEXT,
    result TEXT,                       -- passed, defeated
    yeas INTEGER,
    nays INTEGER,
    paired INTEGER,
    vote_date TEXT NOT NULL,
    session TEXT,
    source_url TEXT
);

-- Spending tracking
CREATE TABLE spending_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    jurisdiction TEXT NOT NULL,
    department TEXT NOT NULL,
    category TEXT,                     -- operating, capital, grants, transfer
    amount REAL NOT NULL,
    fiscal_year TEXT,                  -- e.g. 2025-2026
    description TEXT,
    source_url TEXT,
    ingested_at TEXT NOT NULL
);

-- Event chain linking (bill -> budget -> contract -> news)
CREATE TABLE event_chains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_name TEXT NOT NULL,          -- human-readable chain description
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE event_chain_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain_id INTEGER REFERENCES event_chains(id),
    civic_event_id INTEGER REFERENCES civic_events(id),
    link_order INTEGER NOT NULL,
    link_type TEXT,                    -- bill, budget, contract, news
    confidence REAL DEFAULT 0.5       -- W.A.T.C.H. confidence in the link
);

CREATE INDEX idx_civic_events_type ON civic_events(event_type);
CREATE INDEX idx_civic_events_level ON civic_events(level);
CREATE INDEX idx_civic_events_jurisdiction ON civic_events(jurisdiction);
CREATE INDEX idx_civic_events_date ON civic_events(event_date);
CREATE INDEX idx_spending_jurisdiction ON spending_records(jurisdiction);
CREATE INDEX idx_bills_status ON parliament_bills(status);
```

### API Endpoints

```
GET /api/contracts
    ?level=federal|provincial|municipal
    &jurisdiction=Ontario|Toronto|...
    &department=Transport+Canada
    &min_amount=100000
    &max_amount=10000000
    &timespan=7d|30d|90d|1y
    &limit=50&offset=0

GET /api/parliament/bills
    ?session=current
    &status=active|passed|defeated
    &keyword=housing
    &limit=20

GET /api/parliament/votes
    ?recent=true
    &bill=C-42
    &limit=20

GET /api/parliament/debates
    ?date=2026-03-27
    &keywords=housing,infrastructure
    &limit=10

GET /api/spending
    ?level=federal|provincial|municipal
    &jurisdiction=Ontario
    &department=Transport+Canada
    &fiscal_year=2025-2026
    &category=capital
    &min_amount=100000

GET /api/events
    ?type=contract|bill|vote|spending|debate
    &level=federal|provincial|municipal
    &region=ON|BC|AB|QC
    &timespan=7d|30d
    &limit=100

GET /api/events/:id/chain
    Returns the event chain (bill -> budget -> contract -> news)

GET /api/stats
    Summary counts for map layer badges:
    { contracts: 1234, bills_active: 45, votes_recent: 12, spending_total: "1.2B" }

GET /health
    { status: "ok", last_federal_pull: "...", last_provincial_pull: "...", db_size: "..." }
```

All endpoints return JSON with CORS headers. No authentication required (read-only public data).

---

## Map Layers (Kytran News)

### 3 New Layers

| # | Layer Key | Label | Color | Icon | Default |
|---|-----------|-------|-------|------|---------|
| 19 | `contracts` | Gov Contracts | `#00bfa5` (teal) | briefcase | false |
| 20 | `parliament` | Parliament | `#ffd740` (gold) | landmark | false |
| 21 | `spending` | Public Spending | `#69f0ae` (green) | dollar | false |

### Layer Implementation

Each follows the existing IIFE pattern in `js/layers/`:

**contracts.js:**
- Fetches from W.A.T.C.H. API `/api/events?type=contract&timespan={timespan}`
- ScatterplotLayer with radius proportional to contract value
- Color intensity by level (federal=bright, provincial=medium, municipal=dim)
- Click shows: vendor, department, amount, date, source link

**parliament.js:**
- Fetches from W.A.T.C.H. API `/api/events?type=bill,vote,debate&timespan={timespan}`
- Points at Ottawa (federal) + provincial capitals
- Pulse animation on active votes
- Click shows: bill title, status, vote result, W.A.T.C.H. summary

**spending.js:**
- Fetches from W.A.T.C.H. API `/api/events?type=spending&timespan={timespan}`
- ScatterplotLayer with radius proportional to dollar amount
- Color by category (capital=blue, operating=green, grants=yellow, transfer=orange)
- Click shows: department, amount, fiscal year, category

### Coordinate Mapping

Events are placed on the map using:
- Federal: Ottawa (45.4215, -75.6972) with jitter
- Provincial: capital city coordinates (13 provinces/territories)
- Municipal: city center coordinates
- Contracts with vendor addresses: geocode to lat/lon when available

```javascript
var CANADIAN_COORDS = {
    /* Federal */
    'FEDERAL': [-75.70, 45.42],
    /* Provincial capitals */
    'ONTARIO': [-79.38, 43.65], 'BRITISH COLUMBIA': [-123.12, 49.28],
    'ALBERTA': [-113.49, 53.54], 'QUEBEC': [-71.21, 46.81],
    'MANITOBA': [-97.14, 49.90], 'SASKATCHEWAN': [-104.62, 50.45],
    'NOVA SCOTIA': [-63.57, 44.65], 'NEW BRUNSWICK': [-66.65, 45.96],
    'NEWFOUNDLAND': [-52.71, 47.56], 'PEI': [-63.13, 46.24],
    'NORTHWEST TERRITORIES': [-114.37, 62.45],
    'YUKON': [-135.05, 60.72], 'NUNAVUT': [-68.52, 63.75],
    /* Major cities */
    'TORONTO': [-79.38, 43.65], 'VANCOUVER': [-123.12, 49.28],
    'MONTREAL': [-73.57, 45.50], 'OTTAWA': [-75.70, 45.42],
    'CALGARY': [-114.07, 51.05], 'EDMONTON': [-113.49, 53.54],
    'WINNIPEG': [-97.14, 49.90], 'HALIFAX': [-63.57, 44.65],
    'VICTORIA': [-123.37, 48.43], 'QUEBEC CITY': [-71.21, 46.81]
};
```

### Fallback Data

Each layer gets a fallback JSON file with sample data in the W.A.T.C.H. API response format:
- `data/fallback-contracts.json` — 10 sample federal contracts
- `data/fallback-parliament.json` — 5 active bills + 5 recent votes
- `data/fallback-spending.json` — 10 department spending records

### Config Changes

Add to `js/config.js`:
```javascript
/* W.A.T.C.H. Civic API */
var WATCH_API = 'https://civic.kytranempowerment.com/api';

/* New layer entries in LAYERS object */
contracts:  { label: 'Gov Contracts',   color: '#00bfa5', icon: 'briefcase', default: false },
parliament: { label: 'Parliament',      color: '#ffd740', icon: 'landmark',  default: false },
spending:   { label: 'Public Spending', color: '#69f0ae', icon: 'dollar',    default: false },

/* New intervals */
contracts: 600000,   /* 10 min */
parliament: 600000,  /* 10 min */
spending: 600000,    /* 10 min */

/* New fallbacks */
contracts:  'data/fallback-contracts.json',
parliament: 'data/fallback-parliament.json',
spending:   'data/fallback-spending.json',
```

---

## Civic Dashboard (Phase 2)

### civic.kytranempowerment.com

Static site deployed to Hostinger via `hosting_deployStaticWebsite`. Same vanilla JS + LCARS dark theme as Kytran News.

### Pages

1. **Dashboard** — Hero stats (active contracts, bills in progress, total spending), recent events timeline, embedded Kytran News map filtered to Canada
2. **Contracts** — Searchable/filterable table: department, vendor, amount, level, date. Sort by amount, date. Export CSV.
3. **Parliament** — Active bills with status tracker, recent votes with yea/nay breakdown, Hansard debate summaries (W.A.T.C.H. AI-generated)
4. **Spending** — Department-by-department breakdown, provincial comparison charts, fiscal year trends
5. **Events** — Chronological feed with chain view (bill -> budget -> contract -> news). Filter by level, type, jurisdiction.

### Infrastructure

- Deployed as static site on Hostinger
- Calls W.A.T.C.H. API at civic.kytranempowerment.com/api (NPM proxy routes /api to port 8099)
- LCARS dark theme matching Kytran News aesthetic
- Responsive: 480px / 768px / 1024px breakpoints

---

## Phase Plan

| Phase | Scope | Deliverables |
|-------|-------|-------------|
| **1a** | W.A.T.C.H. agent + API container + federal data ingestion | Docker container, SQLite schema, Open Canada + OpenParliament ingestion, /api endpoints, health check |
| **1b** | 3 map layers on thenews | contracts.js, parliament.js, spending.js, fallback JSONs, config updates, deploy to Hostinger |
| **1c** | Provincial data sources | ON, BC, AB, QC CKAN ingestion jobs, province-level coordinate mapping |
| **1d** | Municipal data sources | Toronto, Vancouver, Montreal, Ottawa ingestion jobs, city-level coordinates |
| **2** | Civic dashboard | civic.kytranempowerment.com — 5 pages, LCARS theme, Hostinger deploy, NPM subdomain |
| **3** | WhatTheFact.ca | Domain, branding, public response system, full W.A.T.C.H. automation, community features |

---

## Testing Strategy

- API endpoints: curl tests against each endpoint after data ingestion
- Map layers: Playwright browser test — verify layer toggles, data points render, click detail works
- Data quality: agent loop job logs ingestion counts, flags zero-result pulls
- Fallback: disconnect API, verify layers fall back to local JSON gracefully

---

## Open Questions (Resolved)

- ~~Backend approach~~ → Lightweight Flask API (Option 2)
- ~~User auth for public response~~ → Deferred to Phase 3
- ~~Domain for civic dashboard~~ → civic.kytranempowerment.com (subdomain)
- ~~Government level scope~~ → All three: federal + provincial + municipal
- ~~Agent identity~~ → W.A.T.C.H. — Watchdog for Accountability, Transparency, Civic Health
