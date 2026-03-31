# Market Watch — Phase B2: Enhanced Data Sources Design

**Date:** 2026-03-31
**Project:** Market Watch — Full Product, Phase B2
**Status:** Approved
**Depends on:** Phase A (autonomous trading loop) — COMPLETE

---

## Overview

Upgrade Market Watch's news and sentiment pipeline from basic keyword scoring to a multi-source news aggregation system with VADER local scoring and Pulse agent deep analysis via Bridge dispatch. Three news sources (yfinance free, Alpha Vantage free tier, future Kytran News coordination). Background ingest every 15 min keeps data fresh. Public API exposes headlines for the landing page and potential Kytran News integration.

## Requirements

- Multiple news sources: yfinance (always) + Alpha Vantage (when API key provided)
- Two-tier sentiment: VADER for all headlines (fast, local), Pulse agent for top stories (deep, via Bridge)
- Background news ingest every 15 min for all watchlist tickers
- Trading cycle checks freshness inline and fetches if stale
- Dashboard news feed for subscribers (per-ticker)
- Public headlines endpoint for landing page + Kytran News coordination
- Existing pipeline interface (`fetch_and_score_news(ticker)`) preserved — no pipeline changes needed

---

## 1. Data Source Architecture

### Three News Sources (layered)

| Layer | Source | Cost | What it provides |
|-------|--------|------|-----------------|
| 1 | yfinance | Free | Headlines + URLs per ticker via `yf.Ticker().news` |
| 2 | Alpha Vantage | Free (25 req/day) | Headlines + pre-scored sentiment via NEWS_SENTIMENT endpoint |
| 3 | Kytran News | Future | Market Watch exposes `/api/public/news` that Kytran News frontend can consume |

### Two-Tier Sentiment Scoring

| Tier | Method | When | Speed |
|------|--------|------|-------|
| 1 | VADER (vaderSentiment) | Every headline during ingest | Instant, local |
| 2 | Pulse agent via Bridge | Top stories during trading cycle only | Slower, LLM-powered, deep analysis |

### Data Flow

```
Background ingest (every 15 min):
    → Fetch headlines from yfinance + Alpha Vantage for all watchlist tickers
    → VADER score each headline
    → Store in news_cache table (deduplicated by ticker+headline)

Trading cycle:
    → Read cached news for ticker
    → If stale (>30min), fetch fresh inline
    → Send top 5 headlines to Pulse agent via Bridge for deep analysis
    → Pulse returns sentiment + summary → stored in news_cache
    → Aggregated sentiment feeds into W.A.T.C.H. pipeline recommendation
```

---

## 2. Database Schema

### New Table: `news_cache`

```sql
CREATE TABLE IF NOT EXISTS news_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('yfinance', 'alphavantage', 'manual')),
    headline TEXT NOT NULL,
    url TEXT,
    published_at TIMESTAMP,
    vader_score REAL,
    vader_sentiment TEXT CHECK (vader_sentiment IN ('positive', 'negative', 'neutral')),
    pulse_score REAL,
    pulse_summary TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(ticker, headline)
);
CREATE INDEX IF NOT EXISTS idx_news_cache_ticker ON news_cache(ticker, fetched_at DESC);
```

Existing `sentiment_scores` table stays — aggregated per-ticker sentiment used by pipeline.

---

## 3. Services + API

### New: `services/news_service.py`

| Function | Purpose |
|----------|---------|
| `fetch_yfinance_news(ticker)` | Fetch headlines from yfinance, return list of dicts |
| `fetch_alphavantage_news(ticker)` | Fetch from Alpha Vantage NEWS_SENTIMENT endpoint |
| `fetch_all_news(ticker)` | Combine sources, deduplicate by headline |
| `score_headlines(headlines)` | Add VADER compound score + sentiment label to each |
| `store_headlines(ticker, headlines)` | Upsert into news_cache |
| `get_cached_news(ticker, max_age_minutes=30)` | Return cached headlines, None if stale |

### Modified: `services/sentiment.py`

Replace keyword scoring with VADER aggregation:
- `get_sentiment_summary(ticker)` — aggregates VADER scores from news_cache
- `fetch_and_score_news(ticker)` — fetch fresh if stale, VADER score, return summary (same signature as current — pipeline unchanged)

### New: `ingest/news_ingest.py`

Background thread function `run_news_ingest()`:
- Reads watchlist tickers
- Calls `fetch_all_news()` + `score_headlines()` + `store_headlines()` for each
- Runs every 15 min (configurable via `NEWS_INGEST_INTERVAL` env var)

### Modified: `app.py`

Start news ingest background thread alongside existing price ingest.

### New API Endpoints

| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| GET | `/api/news/<ticker>` | viewer | Last 30 headlines + sentiment for a ticker |
| GET | `/api/public/news` | none | Last 20 headlines across all watchlist tickers |

### Modified: Landing Page

Add "Latest Market Signals" section showing 5 recent headlines with VADER sentiment badges.

---

## 4. Pipeline Integration

**No changes to `run_pipeline()` or `run_full_cycle()`** — the existing call to `fetch_and_score_news(ticker)` in `sentiment.py` is preserved. Only the internals change.

**Pulse agent deep analysis** (during trading cycle):
1. Pipeline fetches cached news for ticker
2. Top 5 headlines sent to Pulse via `hub_client.dispatch_to_agent("Pulse", prompt)`
3. Pulse returns deep sentiment + market impact summary
4. Stored in `news_cache.pulse_score` and `news_cache.pulse_summary`
5. Pipeline uses Pulse result for recommendation

---

## 5. Configuration

```bash
# Alpha Vantage (optional — enhances news quality)
ALPHAVANTAGE_API_KEY=
ALPHAVANTAGE_NEWS_ENABLED=true

# News Ingest
NEWS_INGEST_INTERVAL=900        # 15 min default (seconds)
NEWS_MAX_AGE_MINUTES=30         # Staleness threshold
```

---

## 6. Files to Create / Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/news_service.py` | Multi-source news fetch, VADER scoring, cache CRUD |
| Create | `ingest/news_ingest.py` | Background news ingest thread |
| Create | `routes/news.py` | News API endpoints (public + authenticated) |
| Modify | `services/sentiment.py` | Replace keyword scoring with VADER + news_cache aggregation |
| Modify | `app.py` | Register news blueprint, start news ingest thread |
| Modify | `schema.sql` | Add news_cache table |
| Modify | `requirements.txt` | Add vaderSentiment |
| Modify | `templates/landing.html` | Add "Latest Market Signals" section |
| Modify | `docker-compose.yml` | Add ALPHAVANTAGE_* env vars |
| Modify | `.env.example` | Document new env vars |

## Out of Scope

- Transformer-based sentiment models (Phase B future)
- Kytran News backend API (separate product)
- Real-time WebSocket news streaming
- News source beyond yfinance + Alpha Vantage
