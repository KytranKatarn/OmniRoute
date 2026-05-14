# Kytran Civic Watch — Master Project Document

**Date**: 2026-05-14
**Product**: Civic Watch
**URL**: civic.kytranempowerment.com (port 8099)
**Container**: kytran_watch_api (VPS — 76.13.107.109)
**Source**: /mnt/standalone/kytran-civic-watch/
**Accent**: #10b981 (emerald green)
**AI Director**: W.A.T.C.H. (Watchdog Analysis & Transparency Civic Hub)

---

## Executive Summary

Civic Watch is Kytran Empowerment's Canadian civic intelligence platform. It gives citizens, journalists, researchers, and government affairs professionals real-time AI-powered monitoring of parliamentary activity, government contracts, public spending, and accountability data across federal and provincial jurisdictions.

The product is a VPS-hosted Flask standalone at civic.kytranempowerment.com. Authentication uses Kytran SSO (OAuth 2.0). W.A.T.C.H. is the platform's AI director agent for civic analytics, dispatched through the A.R.C.H.I.E. hub via the DHQ dispatcher.

Priced at $99/mo (à la carte), sold via KBS billing checkout. Platform members on Starter+ tiers receive bundled access.

---

## Current Features

| Feature | Status | Notes |
|---------|--------|-------|
| Parliament Tracker | Live | Bills, votes, committee activity (federal + provincial) |
| Contract Monitor | Live | Government procurement contracts and tender awards |
| Spending Analysis | Live | Department budgets, expenditure trends |
| Public Accountability | Live | Cross-reference officials, contracts, spending |
| Kytran SSO | Live | OAuth login via platform.kytranempowerment.com |
| Multi-language UI | Live | EN / FR / ES via i18n.js + translations.json |
| Health endpoint | Live | /health for ARCHIE monitoring |
| W.A.T.C.H. AI Director | Stubbed | Hub dispatch endpoint present, UI not wired |

### Routes registered
- `events_bp` — public events and consultations
- `contracts_bp` — procurement contract search and tracking
- `parliament_bp` — bill/vote/MP tracking
- `spending_bp` — expenditure visualization
- `health_bp` — /health JSON endpoint
- `auth_bp` — Kytran OAuth SSO flow

### Data ingestion
- `ingest/federal.py` — CanadaBuys / federal procurement feeds
- `ingest/provincial.py` — provincial sources
- Background thread at startup; no scheduled re-ingest (gap — see below)

---

## Gaps

| # | Gap | Priority | Notes |
|---|-----|----------|-------|
| 1 | W.A.T.C.H. chat overlay not wired | High | Agent exists in DHQ; landing shows callout but no live chat |
| 2 | No scheduled re-ingest | High | Data goes stale after startup — needs APScheduler or cron |
| 3 | No paywall enforcement | High | $99/mo price exists in landing/website but no subscription gate in routes |
| 4 | Voting records not surfaced | Medium | Parliament route exists but voting history UI is thin |
| 5 | FOI tracker not implemented | Medium | Advertised on website but no backend route |
| 6 | Public consultations feed | Medium | Events route present but consultation-specific filtering missing |
| 7 | Email alerts / digests | Medium | Advertised in pricing card — not implemented |
| 8 | Custom politician watchlists | Medium | Advertised — no DB table or UI |
| 9 | Mobile responsiveness audit | Low | Breakpoints defined; untested on actual devices |
| 10 | CORS wildcard (*) | Low | `add_cors_headers` allows all origins — should scope to known domains |

---

## Pricing

| Plan | Price | Access | Sold via |
|------|-------|--------|---------|
| Full Access (à la carte) | $99/mo | All features | KBS billing checkout |
| Platform Starter+ bundle | Included | All features | KBS subscription tier |

Checkout URL: `https://business.kytranempowerment.com/billing/checkout?product=civic-watch&return_url=https://civic.kytranempowerment.com`

---

## Roadmap — Next 5 Features

### 1. W.A.T.C.H. Chat Overlay (Q2 2026, High)
Wire the W.A.T.C.H. AI director into a live chat overlay on the dashboard. Use the existing `archie_chat` pattern — proxy to hub DHQ dispatcher with `capability='civic_analysis'` or `capability='analyze'`. The agent should brief the user on spending anomalies, active bills relevant to their watchlist, and flag accountability gaps on demand.

### 2. Subscription Gate (Q2 2026, High)
Add `@subscription_required('civic-watch')` decorator (pattern from WTF freemium paywall, PR #466). Check `subscription_tier` from the Kytran OAuth token. Redirect unsubscribed users to KBS checkout. Free preview: landing page + one featured contract/bill summary per day.

### 3. Scheduled Data Re-ingestion (Q2 2026, High)
Replace one-shot startup thread with APScheduler running:
- Federal procurement feed: every 4 hours
- Parliamentary Hansard + bills: daily at 06:00 EDT
- Provincial events: every 12 hours
Store last-ingest timestamp in DB; expose `/api/ingest/status` for monitoring.

### 4. Politician Watchlists (Q3 2026, Medium)
Allow logged-in users to follow specific MPs, MLAs, or senators. DB table: `civic_watchlists (user_id, politician_id, created_at)`. Dashboard shows a "Your Politicians" panel with recent votes, bill activity, and spending attributions. Email digest job (weekly) via Stalwart SMTP.

### 5. FOI Request Tracker (Q3 2026, Medium)
Ingest Access to Information request logs from the federal Open Government portal and select provincial ATI registries. Surface as a searchable table with status (pending / released / refused), institution, subject, and linked released documents. W.A.T.C.H. can summarize released document sets on request.

---

## Pre-Launch Checklist

### Must-ship before paid launch
- [ ] Subscription gate enforced on all dashboard routes
- [ ] W.A.T.C.H. chat overlay live (basic Q&A + briefing)
- [ ] Scheduled re-ingest running (data freshness < 6h)
- [ ] Health endpoint monitored by ARCHIE agent loop
- [ ] CORS restricted to kytranempowerment.com + civic.kytranempowerment.com
- [ ] Privacy policy and terms linked in footer
- [ ] KBS checkout flow tested end-to-end (subscribe → OAuth → dashboard)
- [ ] Mobile breakpoints verified at 480px / 768px

### Nice-to-have before launch
- [ ] FR translation coverage for dashboard UI (EN/FR toggle works on landing)
- [ ] Email digest opt-in (even if weekly manual send for v1)
- [ ] Coming Soon section removed or replaced with accurate roadmap items
- [ ] Sitemap and robots.txt for SEO

---

## Tech Notes

### Deployment (VPS — outpost-us)
```
# Code change deploy (Dockerfile uses COPY . so restart alone won't pick up changes)
scp -r /mnt/standalone/kytran-civic-watch/ root@76.13.107.109:/opt/archie-products/kytran-civic-watch/
ssh root@76.13.107.109 "cd /opt/archie-products/kytran-civic-watch && docker compose up -d --build"

# Quick single-file hot-patch
docker cp templates/landing.html kytran_watch_api:/app/templates/landing.html
docker compose restart kytran_watch_api
```

Container must stay on `archie-outpost_archie_net` for Caddy reachability (KB #261670).

### BRIDGE_URL
Must be `http://192.168.1.200:3000` — NOT the public platform hostname. CDN/openresty caps at 60s and hides from task_execution_log.

### Auth
`KYTRAN_CLIENT_ID=civic-watch` + `KYTRAN_CLIENT_ID_LAN` for direct IP access.
OAuth token includes `subscription_tier` claim (added PR #466).

### Database
SQLite default (`/app/civic_watch.db`). Schema in `schema.sql`. Tables: events, contracts, parliament_members, bills, votes, spending_records, civic_watchlists (planned).

### AI Agent
W.A.T.C.H. agent in DHQ — Analytics & Intelligence department (alongside S.P.E.C.T.R.A.). Dispatch via `capability='analyze'` or `capability='civic_analysis'` once added to CAPABILITY_DEPARTMENT_MAP.

---

## Related Documents
- `/mnt/archie_brain/docs/superpowers/plans/2026-03-27-canadian-civic-intelligence-phase1.md`
- `/mnt/archie_brain/docs/superpowers/plans/2026-05-04-civic-transparency-phase1-geds.md`
- KB #260096 — Watch Products VPS deploy ADR
- KB #261670 — WTF VPS Deployment Architecture (network rules apply equally to civic-watch)
- KB #261506 — VPS Product Deployment Guide
