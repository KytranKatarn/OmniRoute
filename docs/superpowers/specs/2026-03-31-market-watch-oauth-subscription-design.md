# Market Watch — OAuth + Subscription Gating Design

**Date:** 2026-03-31
**Project:** Market Watch — Full Product (StockBot Migration), Sub-project 2
**Status:** Approved
**Approach:** KytranAuth SDK + Middleware Layer (Approach A)

---

## Overview

Add authentication and tiered subscription gating to Market Watch standalone product. Uses the existing KytranAuth SDK for "Sign in with Kytran" OAuth flow, with three access tiers (Free, Viewer, AI Trader) controlled by entitlements in ARCHIE's `billing_subscriptions` table. The AI agent's paper trading track record is publicly visible as a product showcase. Designed for VPS deployment with agent dispatch back to the hub.

## Requirements

- Single-owner data model — no per-user isolation. Auth gates access, not data.
- AI (W.A.T.C.H.) paper trades are public content — the product's showcase.
- AI Trader tier users can run their own pipeline (Sub-project 3 scope, bridge wired here).
- Real Alpaca trading toggle is internal (admin only, Kytran team).
- Must work on VPS (public internet) with agents dispatched from Department HQ on the hub.

---

## 1. Auth Architecture

```
User → Market Watch (Flask)
         │
         ├── /  (teaser landing — no auth)
         ├── /auth/kytran/login → redirects to ARCHIE OAuth
         ├── /auth/kytran/callback → token exchange + entitlement check
         ├── /auth/logout → clear session
         │
         ├── /api/me → returns user profile + tier
         ├── /api/public/* → unauthenticated public endpoints
         ├── /api/* (viewer routes) → @tier_required("viewer")
         └── /api/* (ai routes) → @tier_required("ai")

ARCHIE Hub
         ├── /oauth/authorize
         ├── /oauth/token
         └── /oauth/userinfo → returns entitlements list
```

### Key Pieces

- `KytranAuth` SDK wired into `app.py` with `KYTRAN_CLIENT_ID=market-watch`
- **SDK entitlement check override:** The SDK checks `client_id in entitlements`, but our entitlements are `market-watch-viewer` and `market-watch-ai` (not bare `market-watch`). Override the callback to accept any entitlement starting with `market-watch-`. Alternatively, set `KYTRAN_CLIENT_ID=market-watch-viewer` (the minimum tier) and handle AI tier in the app layer.
- New `auth.py` module with `@tier_required(min_tier)` decorator
- Tier resolution: `market-watch-ai` > `market-watch-viewer` > none (free)
- Admin detection: `role == "admin"` from userinfo (enables real Alpaca toggle)
- Session stores user profile + tier, cached locally in `users` SQLite table
- `SECRET_KEY` set via env var for secure Flask sessions

### VPS Deployment

- `KYTRAN_AUTH_URL` points to ARCHIE over mesh (`http://100.64.0.1:3000`) or public URL
- `KYTRAN_REDIRECT_URI` uses public subdomain (e.g., `https://market.kytranempowerment.com/auth/kytran/callback`)

---

## 2. Tier System & Route Protection

### Tiers

| Tier | Entitlement | Access |
|------|-------------|--------|
| **Free** | None (no login) | Teaser landing + AI public track record |
| **Viewer** | `market-watch-viewer` | Full dashboard read access — analyses, strategies, charts, sentiment, trade log with reasoning |
| **AI Trader** | `market-watch-ai` | Everything + own W.A.T.C.H. pipeline, custom watchlists, alerts, backtesting |
| **Admin** | `market-watch-ai` + `role: admin` | Everything + real Alpaca trading toggle |

### Route Mapping

| Route Group | Free | Viewer | AI Trader | Admin |
|------------|------|--------|-----------|-------|
| `GET /` teaser landing | yes | yes | yes | yes |
| `GET /api/public/track-record` | yes | yes | yes | yes |
| `GET /dashboard` (full SPA) | no | yes | yes | yes |
| `GET /api/stocks/*`, `/api/charts/*` | no | yes | yes | yes |
| `GET /api/analysis/*`, `/api/strategies/*` | no | yes | yes | yes |
| `GET /api/portfolio/*`, `/api/watchlist/*` | no | yes | yes | yes |
| `POST /api/watchlist/*`, `/api/alerts/*` | no | no | yes | yes |
| `POST /api/trading/*`, `/api/backtest/*` | no | no | yes | yes |
| `POST /api/trading/toggle-live` | no | no | no | yes |

### Decorator Usage

```python
@tier_required("viewer")   # viewer + ai + admin
@tier_required("ai")       # ai + admin only
@admin_required             # admin only
```

### Tier Resolution Logic

1. No session → free (teaser only)
2. Session has `market-watch-ai` entitlement → AI Trader
3. Session has `market-watch-viewer` entitlement → Viewer
4. Session has `role: admin` → Admin (all access + real trading)

---

## 3. Database Changes

### New Table: `users` (local cache)

```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kytran_sub TEXT NOT NULL UNIQUE,
    username TEXT,
    email TEXT,
    name TEXT,
    role TEXT DEFAULT 'user',
    tier TEXT DEFAULT 'viewer',
    last_login TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Updated on each login via the `on_login` SDK callback. Avoids hitting ARCHIE `/oauth/userinfo` on every request.

### Existing Tables — No Changes

All existing tables remain global (no `user_id` column added):

- `watchlist`, `portfolio`, `transactions`, `analyses`, `paper_account`, `strategies`, `sentiment_scores`, `alerts`, `backtest_results`, `cycle_log`, `market_cache`, `ingest_log`, `agent_dispatch_log`

### ARCHIE Side

No migration needed. Insert `market-watch-viewer` and `market-watch-ai` as products in `billing_subscriptions` for entitled users.

---

## 4. Frontend Changes

### Current State

Single-page app at `/static/index.html` — vanilla HTML + JS with lightweight-charts.js.

### New: Teaser Landing Page (`/`)

- LCARS-themed landing with Market Watch branding
- Hero section: W.A.T.C.H. agent track record (win rate, total return, recent calls)
- Data from `/api/public/track-record`
- Prominent "Sign in with Kytran" button

### Dashboard Behind Auth (`/dashboard`)

- Current SPA becomes the authenticated dashboard
- On load, calls `/api/me` to get user tier
- Tier-based UI:
  - **Viewer:** All tabs visible, action buttons (add watchlist, create alert, run backtest, execute trade) hidden/disabled with "Upgrade to AI Trader" tooltip
  - **AI Trader:** Full interactive access
  - **Admin:** Everything + "Live Trading" toggle in settings

### User Menu (top-right)

- Shows user name + tier badge
- Dropdown: Profile, Subscription tier, Logout
- Tier badge: cyan for Viewer, gold for AI Trader (LCARS style)

### CORS

- Remove `Access-Control-Allow-Origin: *`
- SPA served from same Flask app, CORS not needed for same-origin

---

## 5. Agent Dispatch & VPS Connectivity

### Hub Dispatch Bridge

```
Market Watch (VPS)
    → /api/analysis/run-cycle
    → services/watch_orchestrator.py
        → hub_client.py → HTTP to ARCHIE Hub dispatch API
            → Hub routes to Department HQ agents
            → Results returned to Market Watch
            → Stored in local SQLite (analyses table)
```

### New: `services/hub_client.py`

- Authenticated with a **service token** (machine-to-machine, not user OAuth)
- Calls ARCHIE's `/api/bridge/dispatch` endpoint
- Passes agent name + prompt, gets structured response
- Falls back to local mock analysis if hub unreachable (graceful degradation)

### Config (env vars)

```
ARCHIE_HUB_URL=http://100.64.0.1:3000     # mesh IP on VPS
ARCHIE_SERVICE_TOKEN=<machine token>        # for agent dispatch
```

Dev (LAN):
```
ARCHIE_HUB_URL=http://192.168.1.200:3000
```

The AI's continuous trading loop (Sub-project 3) will use the same `hub_client.py`. This sub-project wires the bridge only.

---

## 6. Security Hardening

### Session Security

- `SECRET_KEY` from env var (cryptographically random)
- `SESSION_COOKIE_SECURE=True` (HTTPS only)
- `SESSION_COOKIE_HTTPONLY=True` (no JS access)
- `SESSION_COOKIE_SAMESITE="Lax"` (CSRF protection)
- Session timeout: 24 hours

### CORS

- Remove wildcard `*`
- Whitelist: `https://market.kytranempowerment.com`, `http://192.168.1.200:8080` (dev)

### Rate Limiting

- Public endpoints (`/api/public/*`): 30 req/min per IP
- Auth endpoints (`/auth/*`): 10 req/min per IP
- API endpoints: 60 req/min per authenticated user
- `flask-limiter` with in-memory store

### Docker Compliance (VPS)

- `read_only: true` rootfs
- Resource limits (CPU + memory)
- No `--privileged`
- Pinned base image tag
- Tmpfs for `/tmp`

### Service Token

- `ARCHIE_SERVICE_TOKEN` in `.env` only
- Validated per request on ARCHIE side
- Rotatable without redeployment

---

## Files to Create / Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `auth.py` | `@tier_required()`, `@admin_required`, tier resolution, `/api/me`, `/auth/logout` |
| Create | `services/hub_client.py` | Machine-to-machine dispatch bridge to ARCHIE hub |
| Create | `templates/landing.html` | LCARS teaser landing page |
| Modify | `app.py` | Wire KytranAuth SDK, session config, register auth routes, landing route |
| Modify | `schema.sql` | Add `users` table |
| Modify | `db.py` | Run new migration |
| Modify | `static/index.html` | Add `/api/me` call, tier-based UI gating, user menu |
| Modify | `routes/*.py` | Add `@tier_required()` decorators to protected routes |
| Create | `.env.example` | Document all env vars |
| Copy | `kytran_auth.py` | Copy SDK into Market Watch (or pip install if packaged) |

## Out of Scope (Sub-project 3+)

- Per-user paper accounts and watchlists
- Autonomous trading loop scheduler
- Real Alpaca brokerage integration wiring
- Stripe checkout flow for purchasing tiers
