# S.C.O.U.T. Browser Intelligence Platform — Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Deploy S.C.O.U.T. (agent #364, News & Media) as a fully operational browser-fleet intelligence agent with a dedicated scraper container, multi-egress proxy rotation, DHQ tab, KBS client plugin, and Claude Code skill.

**Architecture:** Job-queue-first. Jobs submitted to `scout_jobs` table → worker thread pulls → browser pool processes via archie_scraper container (port 4243) → screenshots/data stored → DHQ tab + KBS plugin surface results. Automated scrapes (procurement, news) bypass approval; visual/UX reports require human review before client delivery.

**Tech Stack:** Flask + Playwright (Chromium), Python 3.11, PostgreSQL `scout_jobs` table, archie_brain docker-compose, KBS plugin framework, Claude Code skill (.claude/skills/)

---

## System Architecture

```
CALLERS
  ├── DHQ Scout tab (Run Now, manual job)
  ├── Agent loop jobs (nightly procurement sync, alert checks)
  ├── VPS products → hub API /api/scout/dispatch (via mesh 192.168.1.200:3000)
  ├── Claude Code /scout skill
  └── KBS kbs_scout plugin (client submits site for audit)

          ↓  dispatch(capability='web_scraping' | 'ux_audit' | ...)

S.C.O.U.T. agent (#364, qwen2.5:7b)
  └── routes job → POST http://archie_scraper:4243/jobs

ARCHIE_SCRAPER CONTAINER (port 4243)
  ├── Flask HTTP API
  ├── scout_job_worker thread (polls scout_jobs every 5s)
  └── Browser Pool (3 Chromium contexts)
        ├── Browser 0 — Egress: Hub residential (153.68.192.63)  [default]
        ├── Browser 1 — Egress: VPS outpost SOCKS5 (100.64.0.2:1080)
        └── Browser 2 — Egress: External proxy (SCOUT_PROXY_URL env)

EGRESS TIERS (assigned per-job by proxy_selector.py)
  Tier 1 — Hub residential      : gov sites, anything needing residential IP
  Tier 2 — VPS outpost          : non-gov HTTPS, high-volume scrapes
  Tier 3 — External pool        : sites blocking both hub + VPS (Smartproxy/BrightData)
  Tier 4 — Fleet nodes          : .245/.246 when online, future expansion

STORAGE
  ├── scout_jobs table (archie DB)        — job queue + results
  ├── /mnt/data2/scout/screenshots/       — PNG files, named {job_id}/{step}.png
  └── knowledge_base (vault_note)         — automated scrape results indexed for search

SURFACES
  ├── DHQ Scout tab                       — internal ops view (all jobs, raw logs, approve visual reports)
  ├── KBS kbs_scout plugin                — client-facing: submit URL, view approved report
  └── Claude Code /scout skill            — dispatch from CLI, view results in terminal
```

---

## 1. Database — `scout_jobs` Table

```sql
CREATE TABLE scout_jobs (
    id              SERIAL PRIMARY KEY,
    job_type        VARCHAR(50) NOT NULL,
    -- Types: web_scrape | ux_audit | login_test | signup_flow
    --        network_inspect | visual_report | procurement_sync | accessibility_check

    target_url      TEXT NOT NULL,
    params          JSONB DEFAULT '{}',
    -- web_scrape:  {selector, pagination, max_pages}
    -- ux_audit:    {flows: ["homepage","signup","login"], viewport: "1280x800"}
    -- login_test:  {username, password_hint, expected_redirect}
    -- signup_flow: {fields: {name,email,...}, check_confirmation_email: bool}

    egress_tier     INTEGER DEFAULT 1,  -- 1=hub, 2=vps, 3=external, 4=fleet
    egress_ip       VARCHAR(50),        -- actual IP used (recorded after dispatch)

    status          VARCHAR(20) DEFAULT 'pending',
    -- pending | running | completed | failed | needs_review | approved | rejected

    requested_by    VARCHAR(100),       -- 'agent_loop' | 'claude' | 'kbs_client:{org_id}' | username
    agent_id        INTEGER REFERENCES agents(id),

    -- Results
    data            JSONB,              -- structured extracted data
    screenshots     JSONB DEFAULT '[]', -- [{step, path, caption}]
    network_log     JSONB DEFAULT '[]', -- [{url, method, status, size_bytes}]
    findings        TEXT,               -- LLM-generated summary from S.C.O.U.T.
    error_log       TEXT,

    -- Timing
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     VARCHAR(100),

    -- Auto-approve flag: procurement/news scrapes skip review
    auto_approve    BOOLEAN DEFAULT FALSE
);

CREATE INDEX idx_scout_jobs_status ON scout_jobs(status, created_at DESC);
CREATE INDEX idx_scout_jobs_type   ON scout_jobs(job_type, status);
```

---

## 2. archie_scraper Container

**Location:** `/mnt/archie_brain/archie-scraper/`
**Port:** 4243
**Image:** custom (python:3.11-slim + playwright chromium)

### Directory Structure
```
archie-scraper/
├── Dockerfile
├── docker-compose.yml          -- standalone, added to main compose
├── app.py                      -- Flask app, job queue worker thread
├── browser_pool.py             -- 3-slot Chromium pool, claim/release
├── proxy_selector.py           -- egress tier selection logic + node discovery
├── job_worker.py               -- pulls scout_jobs, dispatches to pool
├── screenshot_store.py         -- save PNGs to /mnt/data2/scout/screenshots/
├── skills/
│   │
│   │  — CORE DATA COLLECTION —
│   ├── web_scrape.py           -- general page scraping (selector-based)
│   ├── multi_page_scrape.py    -- pagination-aware multi-page extraction
│   ├── authenticated_fetch.py  -- login session + fetch (Toronto Star, La Presse, paywalls)
│   ├── search_scrape.py        -- Google/gov search results as real browser
│   ├── site_change_monitor.py  -- diff a URL vs stored snapshot, alert on change
│   ├── pdf_extract.py          -- navigate → click → download PDF → extract text
│   ├── document_download.py    -- any file download requiring browser session
│   │
│   │  — CLIENT SITE INTELLIGENCE (KBS kbs_scout) —
│   ├── ux_audit.py             -- multi-flow screenshot walk-through
│   ├── login_test.py           -- auth flow tester + error state capture
│   ├── signup_flow.py          -- registration automation + confirmation check
│   ├── network_inspect.py      -- XHR/API intercept + log
│   ├── accessibility_check.py  -- WCAG basic pass/fail (contrast, labels, headings)
│   ├── seo_snapshot.py         -- meta tags, h1-h6, page speed, alt texts
│   ├── broken_link_check.py    -- spider site, report 404s + dead links
│   ├── screenshot_diff.py      -- visual regression vs stored baseline
│   ├── form_audit.py           -- field types, validation gaps, mobile-friendliness
│   ├── competitor_snapshot.py  -- pricing, features, careers, tech stack fingerprint
│   │
│   │  — DOMAIN-SPECIFIC —
│   ├── procurement_sync.py     -- CanadaBuys + PSPC tender listings + RFP PDFs
│   ├── ancestry_research.py    -- Ancestry.com behind login (family tree module)
│   ├── crm_enrich.py           -- LinkedIn company/person profile scraping (KBS CRM)
│   ├── contact_harvest.py      -- extract emails, phones, team from business sites (KBS CRM)
│   ├── social_profile_check.py -- public LinkedIn/X/Instagram snapshot (KBS + S.I.G.N.A.L.)
│   └── price_monitor.py        -- track product/competitor prices over time (Market Watch)
└── requirements.txt
```

### Full Skill Inventory (21 skills)

| # | Skill | Capabilities | Primary Modules |
|---|-------|-------------|-----------------|
| 1 | `web_scrape` | Selector-based structured extraction | All |
| 2 | `multi_page_scrape` | Pagination-aware, follows next-page | Gov-watch, WTF |
| 3 | `authenticated_fetch` | Login + session + fetch behind paywall | WTF (Star, La Presse) |
| 4 | `search_scrape` | Navigate search engines as real browser | All research |
| 5 | `site_change_monitor` | Diff URL vs snapshot, alert on change | Gov-watch, Market |
| 6 | `pdf_extract` | Navigate → download PDF → extract text | Gov-watch (RFPs), Legal |
| 7 | `document_download` | Any file download requiring browser session | Gov-watch, Legal |
| 8 | `ux_audit` | Multi-flow screenshot walk-through | KBS kbs_scout |
| 9 | `login_test` | Auth flow test + error state capture | KBS kbs_scout |
| 10 | `signup_flow` | Registration automation + confirmation | KBS kbs_scout |
| 11 | `network_inspect` | XHR/API intercept + full network log | KBS kbs_scout |
| 12 | `accessibility_check` | WCAG contrast, labels, headings pass/fail | KBS kbs_scout |
| 13 | `seo_snapshot` | Meta tags, h1-h6, page speed, alt texts | KBS kbs_scout |
| 14 | `broken_link_check` | Spider site, report 404s + dead links | KBS kbs_scout |
| 15 | `screenshot_diff` | Visual regression vs stored baseline | KBS + platform health |
| 16 | `form_audit` | Field types, validation, mobile-friendliness | KBS kbs_scout |
| 17 | `competitor_snapshot` | Pricing, features, careers, tech fingerprint | KBS + Market Watch |
| 18 | `procurement_sync` | CanadaBuys + PSPC tender listings + PDFs | Gov-watch |
| 19 | `ancestry_research` | Ancestry.com behind login | Family Tree |
| 20 | `crm_enrich` | LinkedIn company/person profile scraping | KBS CRM |
| 21 | `contact_harvest` | Emails, phones, team from business sites | KBS CRM |
| 22 | `social_profile_check` | Public LinkedIn/X/Instagram snapshot | KBS + S.I.G.N.A.L. |
| 23 | `price_monitor` | Track product/competitor prices over time | Market Watch + KBS |

> **Note on Human Agent expansion:** This skill architecture is the template for every
> human agent's browser toolkit. Each internal or contractor agent will inherit a
> curated subset of these skills scoped to their domain. S.C.O.U.T.'s 23-skill inventory
> is the master reference — future agents request skill grants, S.C.O.U.T. trains them.

### Flask API Endpoints
```
POST /jobs                      -- submit new job {job_type, target_url, params, egress_tier}
GET  /jobs/{id}                 -- poll job status + results
GET  /jobs?status=pending       -- list jobs
GET  /pool/status               -- browser pool slot availability
GET  /health                    -- health check
```

### Browser Pool (`browser_pool.py`)
```python
class BrowserPool:
    POOL_SIZE = 3  # configurable via SCOUT_POOL_SIZE env

    # Each slot pre-configured with its egress proxy
    SLOT_EGRESS = {
        0: None,                          # Direct — hub residential IP
        1: "socks5://100.64.0.2:1080",   # VPS outpost via Tailscale
        2: os.getenv("SCOUT_PROXY_URL"), # External (Smartproxy/BrightData)
    }
    # claim(egress_tier) → returns slot_id or blocks until available
    # release(slot_id)   → returns slot to pool
```

### Proxy Selector (`proxy_selector.py`)
```python
TIER_RULES = {
    "gov":        1,   # .gc.ca, .canada.ca → hub residential always
    "provincial": 1,   # seao.ca, bcbid.gov.bc.ca → hub residential
    "news":       2,   # general news sites → VPS fine
    "unknown":    1,   # default safe — hub residential
}

def select_egress(target_url: str, requested_tier: int = None) -> int:
    if requested_tier:
        return requested_tier
    domain = urlparse(target_url).netloc
    if any(x in domain for x in [".gc.ca", ".canada.ca", ".gouv.qc.ca"]):
        return 1
    return TIER_RULES.get("unknown", 1)
```

---

## 3. DHQ S.C.O.U.T. Tab

**File:** `platform_v2/tools/department_hq/scout_routes.py`
**Pattern:** Mirrors `social_routes.py` (S.I.G.N.A.L.) exactly.

### Endpoints
```
GET  /api/scout/overview            -- agent status, pool slots, job counts by status
GET  /api/scout/jobs                -- paginated job list with filters (status, type, date)
GET  /api/scout/jobs/{id}           -- full job detail: data, screenshots, network_log, findings
POST /api/scout/jobs                -- submit manual job from DHQ
POST /api/scout/jobs/{id}/approve   -- mark visual report approved → visible in KBS
POST /api/scout/jobs/{id}/reject    -- reject with note
POST /api/scout/run-now             -- trigger procurement_sync immediately
GET  /api/scout/pool                -- live browser pool slot status (proxied from :4243)
```

### Tab Subtabs (7, mirrors S.I.G.N.A.L.)
```
Overview      -- S.C.O.U.T. agent card, pool live status, Run Now, recent job summary
Jobs          -- all jobs table: type, target, status, egress IP, duration
Reports       -- completed visual reports needing review (approve/reject)
Procurement   -- procurement_sync results: tenders by date, department, value
Network Logs  -- raw XHR captures from network_inspect jobs
Egress        -- proxy pool health: hub/VPS/external/fleet node status + success rates
Skills        -- which skills are available, last used, success rate per skill
```

---

## 4. KBS Plugin — `kbs_scout`

**Location:** `/mnt/archie_brain/kytran-business-suite/plugins/kbs_scout/`
**Client surface:** "Site Intelligence" — clients submit their URL, get a visual UX report.

### Client Flow
1. Client navigates to KBS → Site Intelligence tab
2. Enters target URL + selects audit type (UX Audit / Login Test / Accessibility)
3. KBS submits to hub `POST /api/scout/jobs` with `requested_by='kbs_client:{org_id}'`
4. Job runs on archie_scraper; when completed, status → `needs_review`
5. Kytran reviews in DHQ Scout → Reports tab, clicks Approve
6. KBS client sees report: screenshots, findings, network summary, recommendations
7. Client can download PDF report

### Plugin Endpoints
```
POST /scout/submit                  -- submit audit job
GET  /scout/reports                 -- list org's reports (approved only)
GET  /scout/reports/{id}            -- full report view with screenshots
GET  /scout/reports/{id}/pdf        -- PDF export
```

---

## 5. Claude Code Skill — `/scout`

**Location:** `.claude/skills/scout/SKILL.md`

### Usage
```
/scout ux-audit https://clientsite.com
/scout login-test https://gov-portal.ca
/scout procurement-sync                     -- trigger CanadaBuys + PSPC now
/scout status                               -- show recent jobs + pool status
/scout report {job_id}                      -- show findings for a completed job
```

### Skill behaviour
- Submits job via `POST http://192.168.1.200:3000/api/scout/jobs`
- Polls `/api/scout/jobs/{id}` every 5s until completed (max 120s)
- Prints findings + screenshot paths to terminal
- For visual reports: prints "Pending review in DHQ → Scout → Reports"

---

## 6. Multi-Egress Strategy — Geographic Intelligence

When `multi_egress: true` is set on a job, archie_scraper fires the same request from all available egress tiers simultaneously, then diffs the responses:

```python
# Used by WTF geographic bias detection
results = await asyncio.gather(
    run_skill(skill, url, egress=1),   # Hub residential (Montreal)
    run_skill(skill, url, egress=2),   # VPS outpost (US)
    run_skill(skill, url, egress=3),   # External proxy (variable)
)
diff = compare_responses(results)
# diff → fed to B.I.A.S. agent for geographic bias scoring
```

**Use cases:**
- WTF: same news article from 3 IPs → detect geo-filtered content
- Gov portals: redundancy (if hub IP gets blocked mid-scrape, VPS takes over)
- Client UX audits: "does your site look different to US vs Canadian visitors?"

### Node-Aware Egress Expansion (Future-Proof)

The browser pool is **dynamically sized** based on available cluster nodes. At startup and every 5 minutes, `proxy_selector.py` queries `remote_nodes` for online fleet nodes with a fresh heartbeat and a Tailscale mesh IP, then registers each as an additional Tier 4 egress slot:

```python
def discover_fleet_egress() -> list[dict]:
    """Query remote_nodes for online nodes — each becomes an egress slot."""
    rows = db.query("""
        SELECT node_name, mesh_ip, region
        FROM remote_nodes
        WHERE status = 'online'
          AND heartbeat > NOW() - INTERVAL '2 minutes'
          AND mesh_ip IS NOT NULL
        ORDER BY node_name
    """)
    return [
        {"tier": 4, "proxy": f"socks5://{r['mesh_ip']}:1080", "label": r['node_name']}
        for r in rows
    ]
```

As nodes `.245`, `.246`, and future Starships come online, they automatically appear as egress options — no config change needed. Each node's residential ISP IP becomes a distinct geographic doorway. Pool size grows from 3 → 3 + N online nodes.

**Example cluster at full scale:**
```
Slot 0 — Hub residential (Rogers Montreal)          Tier 1
Slot 1 — VPS outpost-us (Hostinger Chicago)         Tier 2
Slot 2 — External proxy (Smartproxy rotating)       Tier 3
Slot 3 — Node .245 residential (Bell Montreal)      Tier 4 [when online]
Slot 4 — Node .246 residential (Rogers Montreal)    Tier 4 [when online]
Slot N — Future nodes...                            Tier 4
```

`SCOUT_POOL_SIZE` env var sets the **minimum** reserved slots. Fleet nodes expand beyond it automatically.

---

## 7. Agent Loop Jobs

Two new scheduled jobs added to `department_hq/jobs.py`:

```python
# Job: nightly procurement sync (02:00 AM EDT)
scout_procurement_sync:
    capability = 'procurement_research'
    dispatches to S.C.O.U.T. → archie_scraper → procurement_sync.py skill
    targets: CanadaBuys tender listings, PSPC contract awards
    auto_approve = True → results written directly to KB + gov-watch DB
    egress_tier = 1 (hub residential — gov sites)

# Job: weekly UX health check (Sunday 09:00 AM EDT)
scout_platform_ux_check:
    capability = 'ux_audit'
    targets: platform.kytranempowerment.com, each watch product landing page
    auto_approve = False → DHQ review before sharing
    screenshots stored for regression comparison
```

---

## 8. docker-compose.yml Addition

```yaml
archie_scraper:
  build:
    context: ./archie-scraper
    dockerfile: Dockerfile
  container_name: archie_scraper
  restart: unless-stopped
  ports:
    - "4243:4243"
  environment:
    - DB_HOST=archie_database
    - DB_NAME=archie
    - DB_USER=archie
    - DB_PASSWORD=${DB_PASSWORD}
    - SCOUT_POOL_SIZE=3
    - SCOUT_PROXY_URL=${SCOUT_PROXY_URL:-}        # External proxy (optional)
    - SCOUT_VPS_SOCKS=${SCOUT_VPS_SOCKS:-socks5://100.64.0.2:1080}
    - SCREENSHOT_DIR=/mnt/screenshots
    - PLATFORM_API_URL=http://archie_platform:3000
    - PLATFORM_API_KEY=${CLUSTER_PROXY_KEY}
  volumes:
    - /mnt/data2/scout/screenshots:/mnt/screenshots
  networks:
    - archie_net
  depends_on:
    - archie_database
    - archie_platform
  mem_limit: 2g                                   # 3 Chromium × ~400MB + Flask
  dns:
    - 192.168.1.200
    - 1.1.1.1
```

---

## Build Sequence

1. **Migration** — `scout_jobs` table + indexes
2. **archie_scraper container** — Dockerfile, Flask app, browser_pool, proxy_selector, job_worker
3. **Skills** — web_scrape, ux_audit, login_test, signup_flow, network_inspect, procurement_sync, accessibility_check
4. **DHQ Scout tab** — scout_routes.py + template subtabs + JS
5. **Agent loop jobs** — procurement_sync + ux_check in jobs.py
6. **KBS kbs_scout plugin** — submit form + report viewer + PDF export
7. **Claude Code /scout skill** — SKILL.md
8. **Multi-egress** — proxy_selector + parallel egress for WTF bias detection
9. **Wire gov-watch** — feeds.py uses scout_jobs instead of direct requests

---

## Key Constraints

- archie_scraper container **never calls open.canada.ca directly** — procurement_sync.py navigates CanadaBuys HTML (browser bypasses TLS fingerprint block)
- Screenshots stored to `/mnt/data2/scout/` — same data2 drive as ComfyUI models, roomy
- Pool slot 2 (external proxy) optional — `SCOUT_PROXY_URL` empty = pool runs 2 slots until configured
- Auto-approved jobs (procurement, news) never surface in KBS — internal only
- KBS clients only see their own org's reports (scoped by `org_id`)
- VPS → hub API always via `http://192.168.1.200:3000` (mesh) — never public CDN URL
