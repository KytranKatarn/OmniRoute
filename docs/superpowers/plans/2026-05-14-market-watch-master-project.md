# Kytran Market Watch — Master Project Document
**Date:** 2026-05-14
**URL:** https://market.kytranempowerment.com (port 8101, VPS)
**Accent:** #f59e0b (amber/gold)
**Status:** Live on VPS outpost-us

---

## Executive Summary

Kytran Market Watch is an AI-powered autonomous trading intelligence platform. Six specialized W.A.T.C.H. agents run continuous market analysis across equities, crypto, and commodities — building multi-agent consensus across quantitative signals, fundamental value, sentiment, risk assessment, and macro intelligence. The platform delivers autonomous paper trading recommendations 24/7, with a public landing page and gated authenticated dashboard (Kytran SSO).

The product targets active individual investors and traders who want institutional-grade AI analysis without the cost of a Bloomberg terminal. It differentiates by combining multi-agent consensus scoring with autonomous paper trading and a live track record.

---

## Current Features

### Agent Layer (6 W.A.T.C.H. Agents)
- **QUANT** — Quantitative signals, technical analysis, pattern detection
- **VALUE** — Fundamental value analysis, earnings, intrinsic value estimates
- **PULSE** — Market sentiment analysis, news flow, social signals
- **SHIELD** — Risk assessment, drawdown protection, portfolio risk scoring
- **ORACLE** — Macro intelligence, economic indicators, cross-asset correlations
- **M.A.R.K.E.T.** — Director/orchestrator agent, consensus aggregation, final recommendation

### Live Data Pipeline
- Price ingestion every 5 minutes (`ingest/price_ingest.py`, background thread)
- News ingestion on its own configurable interval (`ingest/news_ingest.py`)
- Real-time position monitoring for open paper trades (`ingest/position_monitor.py`)

### Authenticated Dashboard (`/dashboard`, SSO-gated)
- Live AI recommendation feed with confidence scores and sentiment
- 6-agent analysis breakdowns per ticker
- Watchlist management (personalized)
- Historical analysis archive
- Performance track record (W.A.T.C.H. paper portfolio)
- **AI Trader tier**: autonomous trade execution, custom risk parameters, real-time P&L, strategy configuration, priority analysis cycles

### Public Landing Page (`/`)
- Live track record stats (win rate, total return, Sharpe ratio, trade count) via `/api/public/track-record`
- Recent market signals via `/api/public/news`
- Backtest showcase via `/api/public/backtest-showcase`
- Risk grade display via `/api/public/risk-grade`
- Subscription tier comparison (Viewer: free / AI Trader: pro)
- Amber/gold design system matching kytranempowerment.com

### Routes / API Surface
- `routes/stocks.py` — stock data, analysis
- `routes/watchlist.py` — watchlist CRUD
- `routes/charts.py` — charting data
- `routes/alerts.py` — price/volume alerts
- `routes/analysis.py` — AI analysis requests
- `routes/backtest.py` — strategy backtesting
- `routes/trading.py` — paper trading execution
- `routes/portfolio.py` — portfolio tracking
- `routes/strategy_routes.py` — strategy configuration
- `routes/risk.py` — risk grade and exposure
- `routes/news.py` — market news feed
- `routes/public.py` — unauthenticated endpoints
- `routes/health.py` — `/api/health` for monitoring

### Auth
- Kytran SSO (OAuth via KytranAuth SDK)
- `market-watch-viewer` client ID (public access)
- LAN client ID override when accessed via VPS IP directly
- Local user upsert on login with tier resolution

### Subscription Tiers
- **Viewer** (Free): Read-only dashboard, recommendation feed, 6-agent breakdowns, watchlist, historical archive, track record
- **AI Trader** (Pro): Everything in Viewer + autonomous execution, custom risk params, real-time P&L, strategy config, priority cycles

### Pricing (from website)
- À la carte: $99/month — Full Access (TSX + Canadian market data, AI sector analysis, economic indicators, watchlists, earnings alerts, portfolio performance)
- Checkout via KBS: `business.kytranempowerment.com/billing/checkout?product=market-watch`

---

## Known Gaps

| Gap | Impact | Priority |
|-----|--------|----------|
| No Stripe/KBS subscription enforcement in-app | Users can access dashboard regardless of tier | High |
| No real brokerage integration — paper trading only | Can't execute real trades | Medium |
| Pricing card on website says $99/mo but landing page shows Viewer=Free / AI Trader=Pro with no dollar amounts | Inconsistent pricing messaging | Medium |
| No email alerts/notifications for price triggers | Users must actively check dashboard | Medium |
| No mobile app / PWA | Desktop-only experience | Low |
| Backtest showcase endpoint may return empty if no strategies seeded in DB | Public page shows "data coming soon" | Low |
| Risk grade JS color assignment still uses `var(--mw-cyan)` when grade is neutral | Minor visual inconsistency | Low |
| No rate limit on `/api/public/*` endpoints (only 30/min on public_bp globally) | Potential scraping exposure | Low |

---

## Roadmap — Suggested Next Features

### 1. Subscription Gate Enforcement (P8 — Pre-launch blocker)
Wire the KBS subscription tier into the dashboard render. Users without an active `market-watch` subscription should see an upgrade prompt rather than the full dashboard. Use the `subscription_tier` field already injected into the Kytran OAuth token.

### 2. Canadian Market Focus — TSX Data Integration (P7)
The website advertises TSX + Canadian market data and economic indicator tracking. The current data pipeline needs explicit TSX ticker support. Integrate a Canadian market data source (Alpha Vantage CA, TMX, or Yahoo Finance CA) and seed the watchlist with major TSX constituents.

### 3. Real-time Price Alerts via Email/Telegram (P6)
The `routes/alerts.py` module exists but alert delivery is unverified. Wire price/volume alert triggers to Stalwart SMTP (`mail.kytranempowerment.com`) for email delivery. Optionally pipe critical alerts to A.R.C.H.I.E. Telegram for owner-side visibility.

### 4. Earnings Calendar + Fundamental Scorecard (P6)
Add an earnings calendar view showing upcoming earnings dates for watched tickers, with AI pre-earnings analysis from the VALUE agent. Post-earnings surprise scoring feeds back into the recommendation consensus.

### 5. Portfolio Performance Export (P5)
Allow authenticated users to export their paper portfolio history as CSV or PDF — wins/losses, Sharpe, max drawdown, monthly breakdown. Positions Market Watch as a serious backtesting/research tool, not just a signal feed.

---

## Pre-Launch Checklist

- [ ] Subscription gate enforcement wired (KBS tier check on dashboard load)
- [ ] Pricing messaging consistent between website ($99/mo) and in-app landing
- [ ] TSX market data source confirmed and seeded
- [ ] Paper trading track record populated with real backtest data (not zeroes)
- [ ] `/api/public/backtest-showcase` returns real strategy results
- [ ] SSL confirmed on market.kytranempowerment.com (NPM proxy)
- [ ] `/api/health` returns 200 with version
- [ ] Rate limit audit on public endpoints
- [ ] Email alert delivery tested end-to-end
- [ ] Mobile responsiveness verified at 480px / 768px

---

## Technical Notes

### Stack
- **Backend:** Python / Flask, gunicorn (VPS container)
- **Database:** SQLite (local to container) — tables: `portfolio_metrics`, `paper_account`, `open_positions`, `cycle_log`, `trade_journal`, `analyses`
- **Auth:** KytranAuth SDK — Kytran SSO OAuth (client: `market-watch-viewer`)
- **Rate limiting:** Flask-Limiter (in-memory storage)
- **Background threads:** price ingest (5min), news ingest (configurable), position monitor (configurable `MW_POSITION_CHECK_INTERVAL`)

### VPS Deployment
- **Host:** outpost-us (76.13.107.109), container: `kytran_market_api`
- **Port:** 8101
- **Source:** `/opt/archie-products/kytran-market-watch/` on VPS (no git — scp to deploy)
- **Network:** must be on `archie-outpost_archie_net` for Caddy reachability
- **Rebuild:** `scp` changed files → `docker compose up -d --build` (never restart for code changes — Dockerfile uses COPY)
- **Hot-fix:** `docker cp <file> kytran_market_api:/app/...` + `docker compose restart kytran_market_api`
- **Source (hub):** `/mnt/standalone/kytran-market-watch/`
- **BRIDGE_URL:** `http://192.168.1.200:3000` (mesh, never public hostname)

### Design System
- Background: `#0a0a1a`
- Primary accent: `#f59e0b` (amber/gold) — `--mw-accent`
- Secondary: `#00e5ff` (cyan) — used for Viewer tier differentiation only
- Fonts: Orbitron (headlines, nav brand, badges), IBM Plex Mono (body, code, labels)
- Hero: gradient text `linear-gradient(135deg, #fff 30%, #f59e0b)`
- Badge: `border: 1px solid #f59e0b; border-radius: 999px;`
- Feature cards: glassmorphism — `background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); backdrop-filter: blur(12px);`
- Pricing card: `background: linear-gradient(135deg, rgba(17,24,39,1) 0%, #f59e0b22 100%); border: 1px solid #f59e0b44;`
