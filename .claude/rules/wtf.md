# What The Fact (WTF) Rules

**Creating new file** — no prior state. Documents 3-container VPS architecture, XSS rule, deploy patterns, DB location.

## ⚠️ WTF is IN the platform monorepo — it is NOT its own repo

**Source: `KytranKatarn/archie-platform`, path `what-the-fact/`.** Verify with
`git -C what-the-fact rev-parse --show-toplevel` → `/mnt/archie_brain`.

WTF is the **only** watch product not in its own repo — gov/legal/market/civic each have one
(sources under `/mnt/standalone/kytran-*-watch/`). Reason: WTF was created by folding
`kytran_news` INTO the platform (2026-04-18, "WTF + TheNews consolidation", #143), so it never
went through extraction. Deliberate today, not drift — in-tree it gets F.O.R.G.E. auto-review,
a write token, and the full merge pipeline, which the standalone watch repos do NOT have
(they are review-only / human-merge). Split decision: task **#6254** (recommendation: not yet).

| You want | Look in |
|---|---|
| Consumer pages (`/blindspot`, `/divergence`, `/economy`, `/municipal`, `/weather`, `/entity/<id>`, `/map`) | `what-the-fact/consumer/routes.py` — ONE large file; `/map` ≈ L4933, `/blindspot` renders ≈ L4715 |
| Page markup / tier gating | `what-the-fact/consumer/templates/*.html` — gates are often a bare `{% if is_subscriber %}` in the TEMPLATE while the route itself is ungated |
| Ingest, clustering, scoring | `what-the-fact/ingest/` |
| Migrations | `what-the-fact/migrations/` |

🟢 **`KytranKatarn/what-the-fact-site` naming trap — RESOLVED 2026-09-02 (task #6255,
completed).** It is the pre-app static marketing page (`website/what-the-fact.com/`, 5 files,
last touched 2026-04-14), per the `*-site` naming convention. `what-the-fact.com` resolves to
Citadel and is served by the **Flask app**, so that repo serves nothing — but its README used
to open with *"Official website for What The Fact"* and claim it was "hosted on Hostinger at
what-the-fact.com", both false. A Claude Design session was connected to it for an entire WTF
newsroom review, found no app, and had to work from the deployed site by hand instead (2026-09-01).
The repo was actively misleading, not merely stale — a rules-file note alone was never going to
fix it, since no external tool reads `.claude/rules/`.

**Fix (commit `7b76059`, verified live via the GitHub API): the README was rewritten** with an
unmissable "this is NOT the website" banner + a pointer to what-the-fact.com, and **the repo was
formally archived on GitHub** (`isArchived: true` — read-only + GitHub's own banner). It
deliberately does not name the private `archie-platform` repo; that pointer lives in
`what-the-fact/.design-sync/conventions.md` (ships with the design-sync bundle, reaching external
design tooling) and here. Confirmed both false claims are gone and the archive flag is live —
re-verify with `gh repo view KytranKatarn/what-the-fact-site --json isArchived,pushedAt` before
trusting this note, per the file's own regeneration discipline.

**Not addressed by this fix, still sitting untouched (no owner decision on record):** the LOCAL
`website/what-the-fact.com/` copy inside `archie-platform` (same 5 files, last commit 2026-04-14,
git-clean). It isn't misleading anyone the way the GitHub repo was, but it is a real marketing
asset — **do not delete it without an explicit owner decision.**

**Point a design/coding agent at `KytranKatarn/archie-platform`, path `what-the-fact/`.**
Now also stated in `what-the-fact/.design-sync/conventions.md`, which ships as the design-sync
bundle's `readmeHeader` — so the answer travels WITH the bundle instead of living only here.

📦 **The Design handoff is committed at `what-the-fact/design-handoff/`** (39 pages + shell CSS
+ nav + 5 JS + logo + 3 reference docs). They are **design references in HTML, not production
code** — recreate as Jinja templates reading Postgres, replacing `wtf-corpus.js` (241 sample
rows). Its README carries a 10-item corrections table of real live-site defects (Senate 96 vs
93 rendered; "232 fact-checked" counts outlet rows not stories → 23/24; verdict-green used for
geography on the map; lean shown for provinces with <20 articles; the LIVE pill was a dead span).
⚠️ **MP ridings/provinces are deliberately blank for 338 of 343** — an earlier draft derived them
from a slug hash and produced confident false claims about named MPs (Elizabeth May in Alberta).
Fill from the DB; **never re-derive**. Same principle as `shared/city_identity.py` (#6174).

⚠️ `deploy_drift_check.py` already handles the in-tree placement (`repo=_ARCHIE`,
`path="what-the-fact"`, path-aware like media_hub). Do not "fix" it to point at a WTF repo.

## 3-Container Architecture (Citadel / boston-2)

| Container | Port | Domain | Purpose |
|-----------|------|--------|---------|
| `wtf-consumer` | 8103 | what-the-fact.com | Public news feed, OAuth paywall |
| `wtf-tech` | 8104 | what-the-fact.tech | Tech-focused news variant |
| `wtf-ingest` | internal | — | RSS fetch, clustering, scoring (2GB RAM) |

All 3 on **Citadel/boston-2** (`2.25.133.122`, SSH `root@100.64.0.10`, dir `/opt/archie-products/what-the-fact/`) — DB stays the hub `wtf` database (100.64.0.4). Migrated off outpost-us per the fleet-product-migration plan; the old outpost-us stack was DR-repointed into the boston-2 fork during the 06-05 window, zombified, and REMOVED 2026-06-11 (#4032 — archive: outpost-us `/opt/archie-products/what-the-fact-RETIRED-20260611.tar.gz`, Caddy blocks excised, backup `Caddyfile.bak-4032`). Networks: `default` + `archie_net` (required for Caddy reachability).

## Critical Path Rules

### Deployment (image-baked — COPY . in Dockerfile)
```bash
# REBUILD — required for ANY code change (no volume mount on VPS):
docker compose up -d --build wtf-consumer
docker compose up -d --build wtf-tech
docker compose up -d --build wtf-ingest

# NEVER use `docker compose restart` for code changes — stale image stays

# Hot-fix single file (avoids full rebuild):
docker cp /path/to/file.py wtf-consumer:/app/path/to/file.py
docker compose restart wtf-consumer
```

### VPS Path — ALWAYS use `what-the-fact/`
```bash
# CORRECT:
/opt/archie-products/what-the-fact/

# WRONG (empty dir, silently does nothing):
/opt/archie-products/wtf/
```

### WTF DB — separate database on HUB postgres
```bash
# WTF uses its own `wtf` DB on hub postgres (NOT a VPS container database):
docker exec archie_database psql -U archie -d wtf
```

Schema tables:
- `wtf.sources` — news outlets
- `wtf.articles` — ingested articles
- `wtf.story_clusters` — Jaccard-clustered stories
- `wtf.summaries` — extractive summaries
- `wtf.bias_scores` — per-article bias
- `wtf.outlet_bias_scores` — per-outlet aggregate
- `wtf.fact_checks` — fact-check results

## XSS Rule (MANDATORY — never violate)

**ALL external news content MUST use `element.textContent = value`. Never set `element.innerHTML` with dynamic data from RSS/external sources.**

This applies to: headlines, summaries, article bodies, outlet names, author names — anything from an RSS feed or scraped source.

Using the `textContent` property is safe. Using the `innerHTML` property with untrusted external content is a critical XSS vulnerability. The hook system will flag this. If you need formatted HTML from trusted internal data only, use `escHtml()` first.

## WTF_TECH_URL — Server-Side Proxy Rule (KB #267314)

**NEVER pass `WTF_TECH_URL` to browser JavaScript.** Always add a server-side proxy route first.

The env var is an internal URL. Exposing it to the browser leaks infra details, breaks CORS, and bypasses the proxy. Always proxy server-side:

```python
# Add a proxy route in the consumer app:
@consumer_bp.route('/api/tech/proxy/<path:endpoint>')
def proxy_to_tech(endpoint):
    resp = requests.get(f"{os.getenv('WTF_TECH_URL')}/{endpoint}")
    return jsonify(resp.json())
```

## Hub Dispatch (from wtf_hub module)

Hub module: `tools/wtf_hub/wtf_hub.html`, teal accent `#00ffff`

Dispatch capabilities → agents:
- `bias_analysis` → B.I.A.S.
- `fact_check` → V.E.R.I.F.Y.
- `geo_extraction` → L.O.C.A.L.

**Hub routes (`wtf_hub/routes.py`) are volume-mounted — restart `archie_platform` to pick up changes. VPS containers are NOT volume-mounted — they require a full `--build` rebuild.**

## OAuth / Paywall Tiers

| Feature | Free | Paid |
|---------|------|------|
| News feed + story clusters | ✅ | ✅ |
| Bias scores | ✅ | ✅ |
| Bias rationale | ❌ | ✅ |
| Deep Dive analysis | ❌ | ✅ |

OAuth SSO via Kytran Empowerment identity provider (same as other Watch products).

## Ingest Pipeline

- 46 Canadian news sources
- RSS poll: every 30 minutes (`wtf-ingest`)
- **Sitemap sources (#4909, PR #2282)**: sources whose publisher removed RSS
  (Postmedia: montreal_gazette / regina_leaderpost / saskatoon_starphoenix)
  set `wtf.sources.rss_feed = 'sitemap:<index url>'` — the generic loop routes
  the prefix to `ingest/sources/sitemap_generic.py` (newest 2 day-sitemaps,
  page-fetched og:titles for NEW urls only, body left for the scout backlog).
  Reviving another RSS-less source = one UPDATE, no code. GOTCHA: the slug
  must NOT also be in run.py's hardcoded SOURCES list (`handled_slugs`
  shadows the DB-driven path).
- **Hub analyze contract (PRs #2276/#2283/#2285)**: workers calling
  `/tools/wtf-hub/api/analyze` MUST honor `retry_after` on rate_limited
  (never abandon the run); the hub paces per-task at `WTF_ANALYZE_INTERVAL`
  (live=5s). Fact-check verdicts are enum-constrained
  (verified|mostly_true|mixed|disputed|unverifiable|descriptive_reporting);
  `mostly_true` = attributed + internally consistent. `_parse_llm_json`
  tolerates fence-wrapped model JSON. After `archie_platform` restart the
  endpoint needs ~3-5 min warmup (boot-race 500s are noise).
- **Bank of Canada overnight rate (#6272, PR #3174, 2026-09-04)**: `ingest/market/boc_rates.py`
  `run_boc_rates(engine)` now runs **weekly** in `ingest/run.py` (reuses the `_elec_week`
  ISO-week cadence key) and writes a `parliament.ingest_log` heartbeat, registered in
  `ingest/parliament/drift_guard.py` `_MAX_AGE_DAYS` (10d) + `_REQUIRED_TASKS` (brand-new
  puller, must alarm on zero rows not just staleness). Before this it was a manual
  one-off script with no schedule and no heartbeat — `market_watch.boc_rate_decisions`
  silently went 5 months stale (stuck at 2026-04-01) with nothing watching it. Feeds the
  `/economy` page's one real indicator card + the existing `/rates` page.
- Clustering: Jaccard similarity on headlines/keywords
- Summarization: extractive (no LLM required for basic)
- Bias scoring: `wtf.bias_scores` + `wtf.outlet_bias_scores` aggregate
- LLM backlog: `WTF_LLM_BACKLOG_ENABLED=true`, max 14 days, max 100 runs/night
- **Newsletter + digest (#4899, PRs #2278/#2279)**: footer signup →
  `wtf.newsletter_subscribers` (migration 047 incl. **wtfuser GRANTs** — new
  wtf tables MUST grant to wtfuser, apps don't connect as the owner);
  tokenized `/newsletter/unsubscribe`; Monday digest = user_alerts ∪
  newsletter list, sends via the **outpost-us SMTP egress relay
  100.64.0.2:25 unauth** (hub Stalwart :587 unreachable from Citadel,
  ADR-014); subscribers sync to KBS CRM via
  `ingest/newsletter_kbs_sync.py` → `POST {KBS}/plugins/crm/api/internal/upsert-contact`
  (X-Internal-Key, tenant 1, ADR-015).

## Container Resource Limits

| Container | Mem | CPU |
|-----------|-----|-----|
| wtf-ingest | 2GB | 1.0 |
| wtf-consumer | 512MB | 0.5 |
| wtf-tech | 512MB | 0.5 |

All containers: `read_only: true`, `cap_drop: [ALL]`, `tmpfs: /tmp`

## Gotchas

- `WTF_TECH_URL` is an internal URL — never expose in browser JS (KB #267314)
- WTF DB is on HUB postgres (`wtf` database), NOT a VPS container database
- `wtf-ingest` has no exposed port — internal only, no direct API access
- VPS path is `what-the-fact/` not `wtf/` — wrong path is empty, silently fails
- Images from `ghcr.io/kytrankatarn/wtf-*:0.1.0` — always `--build` to pick up Dockerfile changes
- Hub wtf_hub module: volume-mounted (restart picks up changes)
- VPS containers: image-baked (full rebuild required for code changes)
- BRIDGE_URL in WTF config must be `http://100.64.0.4:3000` (Headscale mesh — never the public CDN hostname)
