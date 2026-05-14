# Kytran Legal Watch — Master Project Document

**Created**: 2026-05-14
**Product**: Kytran Legal Watch
**URL**: legal.kytranempowerment.com (port 8100)
**Accent**: #818cf8 (indigo/purple)
**AI Director**: G.A.V.E.L. (Governance, Adjudication, Verdict Evaluation & Legal Intelligence)
**Source**: `/mnt/standalone/kytran-legal-watch/` | VPS: `/opt/archie-products/kytran-legal-watch/`

---

## Executive Summary

Kytran Legal Watch is an AI-powered Canadian legal and regulatory intelligence product targeting businesses, legal professionals, and compliance teams. It monitors federal and provincial legislation, court decisions, regulatory changes, and compliance requirements across all Canadian jurisdictions in real time. G.A.V.E.L. — the platform's dedicated AI legal director — synthesizes this data into actionable intelligence: alerts, summaries, risk signals, and trend analysis. The product is sold à la carte at $99/month and integrates with the Kytran platform SSO and KBS billing.

---

## Current Features (from codebase)

### Blueprints registered in `app.py`

| Blueprint | Domain |
|-----------|--------|
| `auth_bp` | Kytran SSO OAuth login/logout |
| `health_bp` | `/api/health` endpoint |
| `events_bp` | Legal events feed |
| `regulations_bp` | Regulatory data ingestion & display |
| `canlii_bp` | CanLII (Canadian Legal Information Institute) integration |

### What ships today
- **Kytran SSO**: OAuth login via platform.kytranempowerment.com — session-based auth
- **Landing page**: Public marketing page with features, pricing, coming-soon roadmap
- **Dashboard**: Authenticated view served at `/dashboard`
- **Regulations feed**: Regulatory change monitoring via `regulations_bp`
- **CanLII integration**: Court decision indexing via `canlii_bp` (Canadian Legal Information Institute)
- **Events feed**: Legal events tracker via `events_bp`
- **Background ingest**: `_background_ingest()` in `app.py` — runs on startup for data freshness
- **i18n**: EN/FR/ES via `/static/js/i18n.js` + `/static/data/translations.json`

---

## Gaps / Known Issues

| Gap | Priority | Notes |
|-----|----------|-------|
| No G.A.V.E.L. chat surface | High | AI director exists in platform but no dispatch path from legal-watch to hub |
| No email digest/alert delivery | High | Advertised on pricing card but no implementation visible |
| No compliance calendar UI | High | Listed as pricing feature, not shipped |
| No CanLII coverage breadth | Medium | Depth of CanLII integration (which courts, how far back) unverified |
| No subscription gating | Medium | Pricing page present but no paywall enforced on dashboard |
| No per-user alert preferences | Medium | Cannot personalize alert topics/jurisdictions |
| BRIDGE_URL not verified | Medium | VPS must use `http://192.168.1.200:3000` (never public hostname) for hub dispatch |
| No QA suite registered | Low | No P.R.O.B.E. suite for this product |
| No compliance scan profile | Low | Not registered in standalone compliance scanner |

---

## Pricing

| Tier | Price | Includes |
|------|-------|---------|
| Full Access (À La Carte) | $99/mo | Court decision tracker, regulatory change alerts, compliance calendar, AI legal summaries, legislation tracker, email digests & alerts |

Checkout URL: `https://business.kytranempowerment.com/billing/checkout?product=legal-watch&return_url=https://legal.kytranempowerment.com`

---

## Roadmap (Upcoming Features)

| Feature | Target | Description |
|---------|--------|-------------|
| Custom Alert Rules | Q2 2026 | Keyword, jurisdiction, and topic filters for personalized legal alerts |
| AI Case Summarizer | Q2 2026 | One-click G.A.V.E.L. summaries with key holdings, precedent impact, relevance scores |
| Compliance Dashboard | Q3 2026 | Track regulatory obligations; proactive alerts when requirements change |
| Multi-User Workspaces | Q3 2026 | Team accounts with shared watchlists, annotations, collaborative research |
| API Access | Q4 2026 | RESTful API for integrating intelligence into client legal tech stacks |
| Industry Benchmarking | Q4 2026 | Compare compliance posture against sector peers |

---

## Pre-Launch Checklist

### Tier 1 — Blocking
- [ ] Subscription paywall enforced on `/dashboard` (gate by `subscription_tier`)
- [ ] Email digest delivery wired (Stalwart SMTP via hub)
- [ ] G.A.V.E.L. chat overlay added (dispatch via `http://192.168.1.200:3000`, capability=`legal_analysis`)
- [ ] CanLII ingest verified — confirm breadth (courts, date range, update frequency)
- [ ] `/api/health` returns `{status, version, db_ok}`
- [ ] BRIDGE_URL env var set to `http://192.168.1.200:3000` on VPS (not public hostname)
- [ ] Container joins `archie-outpost_archie_net` (Caddy reachability — KB #261670)
- [ ] DNS `legal.kytranempowerment.com` → VPS 76.13.107.109 (verify active)

### Tier 2 — Within 30 Days
- [ ] P.R.O.B.E. QA suite created and registered
- [ ] Compliance scan profile registered in `STANDALONE_PRODUCTS` (code_metrics_service.py)
- [ ] Per-user alert preferences (jurisdiction, topic, keyword filters)
- [ ] Compliance calendar UI shipped
- [ ] G.A.V.E.L. capability added to `CAPABILITY_DEPARTMENT_MAP` in department_coordinator.py
- [ ] `legal_watch` added to KBS billing checkout product catalog

### Tier 3 — 90-Day Roadmap
- [ ] Custom Alert Rules engine (Q2 2026)
- [ ] AI Case Summarizer via G.A.V.E.L. dispatch (Q2 2026)
- [ ] Multi-user workspace schema + UI (Q3 2026)
- [ ] RESTful API with bearer token auth (Q4 2026)

---

## Tech Notes

### Architecture
- **Runtime**: Flask (Python), containerized via Docker on VPS (76.13.107.109)
- **Auth**: Kytran OAuth SSO — `_select_oauth_client()` picks client based on env, redirects to hub
- **Data storage**: Own database (PostgreSQL or SQLite — verify via `docker-compose.yml`)
- **AI dispatch**: Must route through `http://192.168.1.200:3000` (hub BRIDGE_URL via Headscale mesh)
- **Container networking**: Must be on `archie-outpost_archie_net` for Caddy reverse proxy (port 8100)

### VPS Deployment Rules (CRITICAL)
- Source lives at `/opt/archie-products/kytran-legal-watch/` on VPS — NO git on VPS
- Code changes require: `scp` files → VPS then `docker compose up -d --build` (NOT restart — Dockerfile uses `COPY .`)
- Quick hotfix: `docker cp <file> <container>:/app/...` + `docker compose restart`
- Rebuilt containers can break iptables NAT → `docker compose down && docker compose up -d` if 502s appear

### Key Files
```
app.py                          — Flask app, routes, SSO, background ingest
templates/landing.html          — Public landing page (updated 2026-05-14)
templates/dashboard.html        — Authenticated dashboard
blueprints/auth/                — Kytran OAuth flow
blueprints/health/              — /api/health
blueprints/events/              — Legal events feed
blueprints/regulations/         — Regulatory data
blueprints/canlii/              — CanLII court decision integration
static/js/i18n.js               — EN/FR/ES internationalization
static/data/translations.json  — Translation strings
```

### G.A.V.E.L. Chat Overlay (not yet shipped)
When added, follow the module-agent pattern from Backup Manager:
- Briefing: `legal_watch_briefing.py` (new file)
- Action injection: `_inject_gavel_action()` in hub `archie_chat/api_routes.py`
- Capability: `legal_analysis` (add to `CAPABILITY_DEPARTMENT_MAP` → Legal & Regulatory dept)
- Agent: G.A.V.E.L. (#id TBD — verify in agents table, worker_type='ai')
- Chat JS: `static/js/legal-watch-chat.js`, accent red `#ef4444` (standard overlay accent)

---

*Last updated: 2026-05-14 | Source: subagent task, landing page redesign session*
