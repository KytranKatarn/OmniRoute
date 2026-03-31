# Standalone Module Extraction Plan — Design Spec

**Date:** 2026-03-30
**Project:** #193 — Kytran System Operations (Task #1405)
**Status:** Approved

---

## Purpose

Shrink the A.R.C.H.I.E. monolith by deleting modules already absorbed into standalone products, then migrate StockBot into Market Watch as a full autonomous trading machine.

## Phase 1: Monolith Cleanup — Delete KBS Duplicates

Hard delete 7 modules from `platform_v2/tools/` that are already replicated (and improved) in Kytran Business Suite (port 8091, 26 plugins).

| Module to Delete | KBS Plugin Replacement | Approximate Size |
|-----------------|----------------------|-----------------|
| `tools/crm/` | `kbs_crm` | 40+ routes |
| `tools/invoicing/` | `kbs_invoicing` | ~15 routes |
| `tools/store_builder/` | `kbs_store` | ~20 routes |
| `tools/website_studio/` | `kbs_website_builder` | ~20 routes |
| `tools/social_media/` | `kbs_social_media` | 86KB routes.py |
| `tools/call_center/` | `kbs_call_center` | ~10 routes |
| `tools/content_studio/` | `kbs_content_studio` | ~15 routes |

Also evaluate for deletion:
- `tools/google_work_suite/` — if KBS covers this or it's unused
- `tools/google_workspace/` — duplicate of above?
- Any other dead/placeholder modules

### Steps per module:
1. Remove directory from `tools/`
2. Remove Blueprint import/registration (check `__init__.py`, `app.py`, or wherever Blueprints are registered)
3. Remove from `module_registry.py`
4. Remove from `rbac.py`
5. Remove templates at `templates/tools/{module_name}/` if they exist outside the module dir
6. Remove any static assets at `static/css/{module}` or `static/js/{module}` if module-specific

### Verification:
- Platform restarts without import errors
- Dashboard loads without broken module cards
- No 500 errors on any remaining routes
- Module count in registry matches actual tools/ directories

## Phase 2: StockBot → Market Watch Migration

Migrate StockBot's full UI, data capabilities, and trading logic into Market Watch standalone at market.kytranempowerment.com (port 8101).

### What moves to Market Watch:
- All StockBot views: watchlists, portfolio tracker, stock detail pages
- Charts and technical indicators (candle patterns, moving averages, RSI, MACD)
- News sentiment display and analysis results
- Alert management and price targets
- Stock concept explanations (educational content)
- Real-time data feed integration

### What stays in A.R.C.H.I.E.:
- 5 AI agents: Quant, Value, Pulse, Shield, Oracle
- Agent Modelfiles and personality/training configuration
- Bridge dispatch infrastructure — agents are dispatched like any other A.R.C.H.I.E. agent
- The analysis execution engine — runs on A.R.C.H.I.E.'s GPU/LLM infrastructure

### How they connect:
- Market Watch calls A.R.C.H.I.E. API endpoints to trigger agent analysis
- API contract: POST analysis request → agents run → return structured results (buy/sell signals, confidence scores, reasoning text)
- Market Watch displays results and manages the portfolio
- Agent loop job for autonomous scanning:
  - Scheduled market scans (pre-market, mid-day, post-close)
  - Alert triggers (price breakouts, volume spikes, news events)
  - Results pushed to Market Watch DB or fetched on demand

### Data Sources:
- **Alpha Vantage** — existing integration, daily/historical data
- **Real-time feed** — Polygon.io free tier or Finnhub free WebSocket plan (cheapest option with real-time-ish candle data)
- **News** — existing news feeds already in Market Watch, plus agent-driven sentiment analysis

### Paper Trading System:
- Virtual portfolio with configurable starting balance (default $100,000)
- Agents generate signals → auto-execute paper trades or queue for approval (configurable)
- Track: P&L, win rate, Sharpe ratio, max drawdown, average hold time
- Position sizing rules (e.g., max 5% per position, max 20% in one sector)
- All paper — no real money until the system proves profitable over a meaningful period
- Dashboard showing agent performance comparison (which agent generates best signals)

### Market Watch DB tables (new):
- `paper_portfolio` — positions, cost basis, current value
- `paper_trades` — trade history with agent attribution
- `agent_signals` — raw buy/sell signals from each agent with reasoning
- `market_scans` — scheduled scan results and alerts triggered

## Phase 3: Delete StockBot from Monolith

After Market Watch migration is verified and live:
1. Same hard delete process as Phase 1
2. Remove `tools/stockbot/` directory
3. Remove from `module_registry.py` and `rbac.py`
4. Remove StockBot-specific DB tables from A.R.C.H.I.E. (data migrated to Market Watch)
5. Keep the 5 agent definitions in A.R.C.H.I.E.'s agent table — they now serve Market Watch remotely

## Out of Scope
- Real money trading (paper only for now)
- Extracting platform-internal modules (Starbase, Consciousness, Dev HQ, Department HQ, etc.)
- KBS plugin improvements (that's KBS's own roadmap)
- Media Studio extraction (stays in monolith for now — Social Video Engine just built)

## Dependencies
- Market Watch standalone already running at :8101
- A.R.C.H.I.E. API gateway for agent dispatch
- Polygon.io or Finnhub account for real-time data (free tier)
- StockBot's Alpha Vantage API key transfers to Market Watch
