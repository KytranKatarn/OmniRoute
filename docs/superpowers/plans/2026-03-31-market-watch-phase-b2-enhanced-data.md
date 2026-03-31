# Market Watch — Phase B2: Enhanced Data Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Market Watch's news and sentiment pipeline from keyword scoring to multi-source news aggregation (yfinance + Alpha Vantage) with VADER local scoring and Pulse agent deep analysis via Bridge dispatch.

**Architecture:** New `news_service.py` fetches from multiple sources and scores with VADER. Rewritten `sentiment.py` aggregates from `news_cache` table. Background `news_ingest.py` keeps data fresh every 15 min. New API endpoints expose news to dashboard and public landing page. Pulse agent provides deep analysis during trading cycles.

**Tech Stack:** Flask 3.1, vaderSentiment, yfinance, Alpha Vantage API, SQLite, ARCHIE Bridge dispatch

**Spec:** `docs/superpowers/specs/2026-03-31-market-watch-phase-b2-enhanced-data-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/news_service.py` | Multi-source news fetch, VADER scoring, news_cache CRUD |
| Create | `ingest/news_ingest.py` | Background news ingest thread (every 15 min) |
| Create | `routes/news.py` | News API endpoints (public + authenticated) |
| Modify | `services/sentiment.py` | Replace keyword scoring with VADER + news_cache aggregation |
| Modify | `schema.sql` | Add `news_cache` table |
| Modify | `requirements.txt` | Add `vaderSentiment` |
| Modify | `app.py` | Register news blueprint, start news ingest thread |
| Modify | `templates/landing.html` | Add "Latest Market Signals" section |
| Modify | `docker-compose.yml` | Add ALPHAVANTAGE env vars |
| Modify | `.env.example` | Document new env vars |

---

### Task 1: Schema + Dependencies

**Files:**
- Modify: `schema.sql`
- Modify: `requirements.txt`

- [ ] **Step 1: Add news_cache table to schema.sql**

Append to the end of `/mnt/archie_brain/market-watch/schema.sql`:

```sql
-- News cache — headlines from multiple sources with sentiment scores
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

- [ ] **Step 2: Add vaderSentiment to requirements.txt**

Add this line to `/mnt/archie_brain/market-watch/requirements.txt`:

```
vaderSentiment==3.3.2
```

- [ ] **Step 3: Install vaderSentiment**

```bash
pip install vaderSentiment==3.3.2 --break-system-packages -q
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add schema.sql requirements.txt
git commit -m "feat(news): add news_cache table and vaderSentiment dependency"
```

---

### Task 2: News Service — Multi-Source Fetch + VADER Scoring

**Files:**
- Create: `services/news_service.py`

- [ ] **Step 1: Create news_service.py**

Create `/mnt/archie_brain/market-watch/services/news_service.py`:

```python
"""News service — multi-source news fetch with VADER sentiment scoring."""

import os
import logging
from datetime import datetime, timedelta

import requests
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from db import get_db

logger = logging.getLogger(__name__)

_vader = SentimentIntensityAnalyzer()

ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "")
ALPHAVANTAGE_NEWS_ENABLED = os.environ.get("ALPHAVANTAGE_NEWS_ENABLED", "true").lower() in ("true", "1")
NEWS_MAX_AGE_MINUTES = int(os.environ.get("NEWS_MAX_AGE_MINUTES", 30))


def fetch_yfinance_news(ticker):
    """Fetch headlines from yfinance.

    Returns list of dicts: [{headline, url, published_at, source}]
    """
    try:
        t = yf.Ticker(ticker)
        news = t.news or []
        results = []
        for item in news[:20]:
            headline = item.get("title", "")
            if not headline:
                continue
            published = None
            pub_ts = item.get("providerPublishTime")
            if pub_ts:
                try:
                    published = datetime.fromtimestamp(pub_ts).isoformat()
                except (ValueError, TypeError, OSError):
                    pass
            results.append({
                "headline": headline,
                "url": item.get("link", ""),
                "published_at": published,
                "source": "yfinance",
            })
        return results
    except Exception as e:
        logger.warning("yfinance news fetch failed for %s: %s", ticker, e)
        return []


def fetch_alphavantage_news(ticker):
    """Fetch headlines from Alpha Vantage NEWS_SENTIMENT endpoint.

    Returns list of dicts: [{headline, url, published_at, source, av_sentiment}]
    """
    if not ALPHAVANTAGE_API_KEY or not ALPHAVANTAGE_NEWS_ENABLED:
        return []

    try:
        resp = requests.get(
            "https://www.alphavantage.co/query",
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ticker,
                "apikey": ALPHAVANTAGE_API_KEY,
                "limit": 10,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            logger.warning("Alpha Vantage news failed for %s: HTTP %d", ticker, resp.status_code)
            return []

        data = resp.json()
        feed = data.get("feed", [])
        results = []
        for item in feed:
            headline = item.get("title", "")
            if not headline:
                continue
            published = item.get("time_published", "")
            if published and len(published) >= 8:
                try:
                    published = datetime.strptime(published[:15], "%Y%m%dT%H%M%S").isoformat()
                except ValueError:
                    published = None

            av_sentiment = None
            for ts in item.get("ticker_sentiment", []):
                if ts.get("ticker", "").upper() == ticker.upper():
                    try:
                        av_sentiment = float(ts.get("ticker_sentiment_score", 0))
                    except (ValueError, TypeError):
                        pass
                    break

            results.append({
                "headline": headline,
                "url": item.get("url", ""),
                "published_at": published,
                "source": "alphavantage",
                "av_sentiment": av_sentiment,
            })
        return results
    except Exception as e:
        logger.warning("Alpha Vantage news failed for %s: %s", ticker, e)
        return []


def fetch_all_news(ticker):
    """Combine news from all sources, deduplicate by headline.

    Returns list of dicts with: headline, url, published_at, source
    """
    all_news = []
    seen_headlines = set()

    for item in fetch_yfinance_news(ticker):
        key = item["headline"].lower().strip()
        if key not in seen_headlines:
            seen_headlines.add(key)
            all_news.append(item)

    for item in fetch_alphavantage_news(ticker):
        key = item["headline"].lower().strip()
        if key not in seen_headlines:
            seen_headlines.add(key)
            all_news.append(item)

    return all_news


def score_headlines(headlines):
    """Add VADER sentiment scores to each headline dict.

    Mutates in-place, adds: vader_score, vader_sentiment
    """
    for item in headlines:
        scores = _vader.polarity_scores(item["headline"])
        compound = scores["compound"]
        item["vader_score"] = round(compound, 4)
        if compound >= 0.05:
            item["vader_sentiment"] = "positive"
        elif compound <= -0.05:
            item["vader_sentiment"] = "negative"
        else:
            item["vader_sentiment"] = "neutral"
    return headlines


def store_headlines(ticker, headlines):
    """Upsert scored headlines into news_cache.

    Args:
        ticker: stock ticker
        headlines: list of dicts with headline, url, published_at, source, vader_score, vader_sentiment
    """
    conn = get_db()
    try:
        for item in headlines:
            conn.execute(
                """INSERT INTO news_cache (ticker, source, headline, url, published_at, vader_score, vader_sentiment, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(ticker, headline) DO UPDATE SET
                       vader_score = excluded.vader_score,
                       vader_sentiment = excluded.vader_sentiment,
                       fetched_at = CURRENT_TIMESTAMP""",
                (
                    ticker.upper(),
                    item.get("source", "yfinance"),
                    item["headline"],
                    item.get("url", ""),
                    item.get("published_at"),
                    item.get("vader_score"),
                    item.get("vader_sentiment"),
                ),
            )
        conn.commit()
        logger.debug("Stored %d headlines for %s", len(headlines), ticker)
    finally:
        conn.close()


def get_cached_news(ticker, max_age_minutes=None):
    """Return cached headlines for a ticker, or None if stale.

    Args:
        ticker: stock ticker
        max_age_minutes: staleness threshold (default from env var)

    Returns:
        list of dicts or None if no fresh data
    """
    if max_age_minutes is None:
        max_age_minutes = NEWS_MAX_AGE_MINUTES

    conn = get_db()
    try:
        cutoff = (datetime.utcnow() - timedelta(minutes=max_age_minutes)).isoformat()
        rows = conn.execute(
            """SELECT headline, url, source, published_at, vader_score, vader_sentiment,
                      pulse_score, pulse_summary, fetched_at
               FROM news_cache
               WHERE ticker = ? AND fetched_at > ?
               ORDER BY fetched_at DESC LIMIT 30""",
            (ticker.upper(), cutoff),
        ).fetchall()

        if not rows:
            return None

        return [
            {
                "headline": r["headline"],
                "url": r["url"],
                "source": r["source"],
                "published_at": r["published_at"],
                "vader_score": r["vader_score"],
                "vader_sentiment": r["vader_sentiment"],
                "pulse_score": r["pulse_score"],
                "pulse_summary": r["pulse_summary"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def update_pulse_analysis(ticker, headline, pulse_score, pulse_summary):
    """Store Pulse agent deep analysis result for a headline."""
    conn = get_db()
    try:
        conn.execute(
            """UPDATE news_cache SET pulse_score = ?, pulse_summary = ?
               WHERE ticker = ? AND headline = ?""",
            (pulse_score, pulse_summary, ticker.upper(), headline),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.news_service import fetch_all_news, score_headlines, store_headlines, get_cached_news, update_pulse_analysis; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/news_service.py
git commit -m "feat(news): multi-source news service — yfinance + Alpha Vantage + VADER scoring"
```

---

### Task 3: Rewrite Sentiment Service

**Files:**
- Modify: `services/sentiment.py`

- [ ] **Step 1: Read current sentiment.py**

Read `/mnt/archie_brain/market-watch/services/sentiment.py`.

- [ ] **Step 2: Replace with VADER + news_cache aggregation**

Replace the entire contents of `/mnt/archie_brain/market-watch/services/sentiment.py` with:

```python
"""Sentiment service — VADER-based aggregation from news_cache.

Preserves the same interface the W.A.T.C.H. pipeline uses:
    - fetch_and_score_news(ticker) -> list of scored items
    - get_sentiment_summary(ticker) -> aggregated summary dict
"""

import logging
from datetime import datetime, timedelta

from db import get_db
from services.news_service import (
    fetch_all_news,
    score_headlines,
    store_headlines,
    get_cached_news,
    NEWS_MAX_AGE_MINUTES,
)

logger = logging.getLogger(__name__)


def fetch_and_score_news(ticker, limit=20):
    """Fetch news for ticker, score with VADER, store in cache.

    Returns list of dicts: [{headline, url, source, vader_score, vader_sentiment, published_at}]
    """
    # Check cache first
    cached = get_cached_news(ticker)
    if cached:
        logger.debug("Using cached news for %s (%d items)", ticker, len(cached))
        return cached[:limit]

    # Fetch fresh from all sources
    headlines = fetch_all_news(ticker)
    if not headlines:
        logger.info("No news found for %s", ticker)
        return []

    # VADER score
    scored = score_headlines(headlines)

    # Store in cache
    store_headlines(ticker, scored)

    return scored[:limit]


def get_sentiment_summary(ticker, days=7):
    """Aggregate sentiment from news_cache for a ticker.

    Returns dict with: ticker, avg_score, positive_count, negative_count,
    neutral_count, total, sentiment (overall label), headlines (top 10)
    """
    conn = get_db()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = conn.execute(
            """SELECT headline, source, vader_score, vader_sentiment, url, published_at
               FROM news_cache
               WHERE ticker = ? AND fetched_at > ?
               ORDER BY fetched_at DESC""",
            (ticker.upper(), cutoff),
        ).fetchall()

        if not rows:
            return {
                "ticker": ticker,
                "avg_score": 0.0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "total": 0,
                "sentiment": "neutral",
                "headlines": [],
            }

        scores = [r["vader_score"] for r in rows if r["vader_score"] is not None]
        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

        positive = sum(1 for r in rows if r["vader_sentiment"] == "positive")
        negative = sum(1 for r in rows if r["vader_sentiment"] == "negative")
        neutral = sum(1 for r in rows if r["vader_sentiment"] == "neutral")

        if avg_score >= 0.05:
            overall = "positive"
        elif avg_score <= -0.05:
            overall = "negative"
        else:
            overall = "neutral"

        headlines = [
            {
                "headline": r["headline"],
                "source": r["source"],
                "score": r["vader_score"],
                "url": r["url"],
                "date": r["published_at"],
            }
            for r in rows[:10]
        ]

        return {
            "ticker": ticker,
            "avg_score": avg_score,
            "positive_count": positive,
            "negative_count": negative,
            "neutral_count": neutral,
            "total": len(rows),
            "sentiment": overall,
            "headlines": headlines,
        }
    finally:
        conn.close()
```

- [ ] **Step 3: Verify same interface**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.sentiment import fetch_and_score_news, get_sentiment_summary; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/sentiment.py
git commit -m "feat(news): rewrite sentiment — VADER + news_cache aggregation (same interface)"
```

---

### Task 4: News Ingest Background Thread

**Files:**
- Create: `ingest/news_ingest.py`
- Modify: `app.py`

- [ ] **Step 1: Create news_ingest.py**

Create `/mnt/archie_brain/market-watch/ingest/news_ingest.py`:

```python
"""Background news ingest — fetches and scores headlines for all watchlist tickers."""

import os
import time
import logging

from db import get_db
from services.news_service import fetch_all_news, score_headlines, store_headlines

logger = logging.getLogger(__name__)

NEWS_INGEST_INTERVAL = int(os.environ.get("NEWS_INGEST_INTERVAL", 900))


def run_news_ingest():
    """Fetch and score news for all watchlist tickers."""
    start = time.time()
    conn = get_db()
    try:
        tickers = conn.execute("SELECT ticker FROM watchlist").fetchall()
    finally:
        conn.close()

    if not tickers:
        logger.debug("News ingest: no tickers in watchlist")
        return

    count, errors = 0, 0
    for row in tickers:
        ticker = row["ticker"]
        try:
            headlines = fetch_all_news(ticker)
            if headlines:
                scored = score_headlines(headlines)
                store_headlines(ticker, scored)
                count += len(scored)
            time.sleep(1)  # Rate limit between tickers
        except Exception as e:
            logger.error("News ingest failed for %s: %s", ticker, e)
            errors += 1

    duration_ms = int((time.time() - start) * 1000)

    # Log to ingest_log
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO ingest_log (source, status, records_count, error_message, duration_ms)
               VALUES (?, ?, ?, ?, ?)""",
            (
                "news",
                "success" if errors == 0 else "failure",
                count,
                f"{errors} errors" if errors > 0 else None,
                duration_ms,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("News ingest: %d headlines for %d tickers in %dms (%d errors)",
                count, len(tickers), duration_ms, errors)
```

- [ ] **Step 2: Add news ingest thread to app.py**

Read `/mnt/archie_brain/market-watch/app.py` and find the `_background_ingest` function. Add a second background function and thread after it:

```python
def _background_news_ingest(app):
    """Background thread for news ingestion."""
    time.sleep(20)  # Wait for app + price ingest to settle
    with app.app_context():
        logger.info("Background news ingest thread started")
        while True:
            try:
                from ingest.news_ingest import run_news_ingest, NEWS_INGEST_INTERVAL
                run_news_ingest()
                time.sleep(NEWS_INGEST_INTERVAL)
            except Exception as e:
                logger.error("News ingest failed: %s", e)
                time.sleep(60)  # Retry after 1 min on error
```

In the `if __name__ == "__main__":` block, add:

```python
    news_thread = threading.Thread(target=_background_news_ingest, args=(app,), daemon=True)
    news_thread.start()
```

- [ ] **Step 3: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from ingest.news_ingest import run_news_ingest; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add ingest/news_ingest.py app.py
git commit -m "feat(news): background news ingest thread — every 15 min for all watchlist tickers"
```

---

### Task 5: News API Routes

**Files:**
- Create: `routes/news.py`
- Modify: `app.py`

- [ ] **Step 1: Create news routes**

Create `/mnt/archie_brain/market-watch/routes/news.py`:

```python
"""News API routes — public headlines + authenticated per-ticker news."""

from flask import Blueprint, jsonify, request

from db import get_db
from auth import tier_required

news_bp = Blueprint("news", __name__)


@news_bp.route("/api/news/<ticker>")
@tier_required("viewer")
def get_ticker_news(ticker):
    """Return recent headlines + sentiment for a specific ticker."""
    ticker = ticker.upper()
    conn = get_db()
    try:
        limit = request.args.get("limit", 30, type=int)
        rows = conn.execute(
            """SELECT headline, url, source, published_at, vader_score, vader_sentiment,
                      pulse_score, pulse_summary, fetched_at
               FROM news_cache
               WHERE ticker = ?
               ORDER BY fetched_at DESC LIMIT ?""",
            (ticker, limit),
        ).fetchall()

        # Aggregate sentiment
        scores = [r["vader_score"] for r in rows if r["vader_score"] is not None]
        avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

        return jsonify({
            "success": True,
            "ticker": ticker,
            "avg_sentiment": avg_score,
            "total_headlines": len(rows),
            "headlines": [
                {
                    "headline": r["headline"],
                    "url": r["url"],
                    "source": r["source"],
                    "published_at": r["published_at"],
                    "vader_score": r["vader_score"],
                    "vader_sentiment": r["vader_sentiment"],
                    "pulse_score": r["pulse_score"],
                    "pulse_summary": r["pulse_summary"],
                }
                for r in rows
            ],
        })
    finally:
        conn.close()


@news_bp.route("/api/public/news")
def get_public_news():
    """Return latest headlines across all watchlist tickers (public)."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT ticker, headline, url, source, published_at, vader_score, vader_sentiment, fetched_at
               FROM news_cache
               ORDER BY fetched_at DESC LIMIT 20"""
        ).fetchall()

        return jsonify({
            "success": True,
            "total": len(rows),
            "headlines": [
                {
                    "ticker": r["ticker"],
                    "headline": r["headline"],
                    "url": r["url"],
                    "source": r["source"],
                    "published_at": r["published_at"],
                    "vader_score": r["vader_score"],
                    "vader_sentiment": r["vader_sentiment"],
                }
                for r in rows
            ],
        })
    finally:
        conn.close()
```

- [ ] **Step 2: Register news blueprint in app.py**

Add to `app.py` in the `create_app()` function, after the public_bp registration:

```python
    from routes.news import news_bp
    app.register_blueprint(news_bp)
```

- [ ] **Step 3: Verify**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from routes.news import news_bp; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add routes/news.py app.py
git commit -m "feat(news): news API routes — public headlines + per-ticker authenticated"
```

---

### Task 6: Landing Page — Latest Market Signals

**Files:**
- Modify: `templates/landing.html`

- [ ] **Step 1: Read current landing.html**

Read `/mnt/archie_brain/market-watch/templates/landing.html` and find the "RECENT AI CALLS" section. The new "LATEST MARKET SIGNALS" section goes after it.

- [ ] **Step 2: Add Market Signals section**

After the Recent AI Calls section, add a new section. Use the same styling patterns (section divider, dark panel, LCARS theme). The section should:

- Show a "LATEST MARKET SIGNALS" header
- Fetch `/api/public/news` on page load
- Render up to 5 headlines with:
  - Ticker badge (cyan)
  - Headline text (textContent, not innerHTML)
  - VADER sentiment badge: green for positive, red for negative, gray for neutral
  - Source label (yfinance/alphavantage)
- If no news yet, show "No market signals yet"
- Use safe DOM methods (createElement + appendChild + textContent) — no innerHTML with API data

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add templates/landing.html
git commit -m "feat(ui): Latest Market Signals section on landing page"
```

---

### Task 7: Docker Config + Env Vars

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add env vars to docker-compose.yml**

Add these to the `environment:` section in `/mnt/archie_brain/market-watch/docker-compose.yml`:

```yaml
      # News / Alpha Vantage
      - ALPHAVANTAGE_API_KEY=${ALPHAVANTAGE_API_KEY:-}
      - ALPHAVANTAGE_NEWS_ENABLED=${ALPHAVANTAGE_NEWS_ENABLED:-true}
      - NEWS_INGEST_INTERVAL=${NEWS_INGEST_INTERVAL:-900}
      - NEWS_MAX_AGE_MINUTES=${NEWS_MAX_AGE_MINUTES:-30}
```

- [ ] **Step 2: Add to .env.example**

Append to `/mnt/archie_brain/market-watch/.env.example`:

```bash

# News / Alpha Vantage
ALPHAVANTAGE_API_KEY=
ALPHAVANTAGE_NEWS_ENABLED=true
NEWS_INGEST_INTERVAL=900
NEWS_MAX_AGE_MINUTES=30
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add docker-compose.yml .env.example
git commit -m "feat(config): Alpha Vantage + news ingest env vars"
```

---

### Task 8: Rebuild + Test + VPS Deploy

- [ ] **Step 1: Rebuild Docker**

```bash
cd /mnt/archie_brain/market-watch
docker compose build --no-cache
docker compose up -d
```

- [ ] **Step 2: Verify container starts**

```bash
sleep 5 && docker logs kytran_market_api 2>&1 | tail -5
```

Expected: Flask running, no import errors.

- [ ] **Step 3: Test public news endpoint**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
import json
app = create_app()
with app.test_client() as c:
    r = c.get('/api/public/news')
    d = json.loads(r.data)
    print(f'Public news: {r.status_code} total={d.get(\"total\", 0)}')
"
```

Expected: 200 with total (0 initially, populated after first ingest).

- [ ] **Step 4: Test authenticated news endpoint**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
import json
app = create_app()
with app.test_client() as c:
    r = c.get('/api/news/AAPL')
    print(f'Ticker news (no auth): {r.status_code}')
"
```

Expected: 401.

- [ ] **Step 5: Test news ingest manually**

```bash
docker exec kytran_market_api python3 -c "
from ingest.news_ingest import run_news_ingest
run_news_ingest()
print('Ingest complete')
"
```

Expected: Headlines fetched and stored (check logs).

- [ ] **Step 6: Deploy to VPS**

```bash
sshpass -p 'ArchieOutpost2026' rsync -az --exclude='.env' --exclude='market.db' --exclude='__pycache__' --exclude='.git' /mnt/archie_brain/market-watch/ kytran@76.13.107.109:/opt/kytran-market-watch/
sshpass -p 'ArchieOutpost2026' ssh kytran@76.13.107.109 "cd /opt/kytran-market-watch && docker compose build --no-cache && docker compose up -d"
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Schema + vaderSentiment dep | schema.sql, requirements.txt | 1 |
| 2 | News service (fetch + VADER + cache) | services/news_service.py | 1 |
| 3 | Rewrite sentiment (VADER aggregation) | services/sentiment.py | 1 |
| 4 | News ingest background thread | ingest/news_ingest.py, app.py | 1 |
| 5 | News API routes | routes/news.py, app.py | 1 |
| 6 | Landing page Market Signals | templates/landing.html | 1 |
| 7 | Docker + env config | docker-compose.yml, .env.example | 1 |
| 8 | Rebuild + test + VPS deploy | Docker + rsync | 0 |

**Total: 8 tasks, ~7 commits, 3 new files, 7 modified files**
