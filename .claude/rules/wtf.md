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

🔴 **`KytranKatarn/what-the-fact-site` is NOT the app.** It is the pre-app static marketing
page (`website/what-the-fact.com/`, 5 files, last touched 2026-04-14), per the `*-site` naming
convention. `what-the-fact.com` resolves to Citadel and is served by the **Flask app**, so that
repo serves nothing. Pointing a coding agent at it means editing a dead repo — this nearly
happened with Claude Design on 2026-09-01. Retire-or-keep is task **#6255**.

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
