# Kytran Market Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Kytran Market Watch — a standalone autonomous trading dashboard with M.A.R.K.E.T. multi-agent pipeline, LCARS green theme, yfinance data, Alpaca paper trading, and autonomy-governed cycles.

**Architecture:** Flask standalone on port 8101 with SQLite (WAL mode), following the Watch product template (same as Civic Watch :8099 / Legal Watch :8100). 4-agent pipeline (Director → Quant → Risk → Executor) dispatched via Bridge to local Ollama models. Agent loop job governs trading cycles through Autonomy module.

**Tech Stack:** Python 3.12, Flask, SQLite3, yfinance, alpaca-py, lightweight-charts, LCARS CSS, Docker

**Spec:** `docs/superpowers/specs/2026-03-27-market-watch-design.md`

---

## File Structure

### New Files (all under `market-watch/`)
| File | Responsibility |
|------|---------------|
| `app.py` | Flask app, CORS, blueprint registration, background ingest thread |
| `db.py` | SQLite connection, WAL mode, schema init |
| `schema.sql` | All 10 tables |
| `requirements.txt` | Dependencies |
| `Dockerfile` | Python 3.12-alpine container |
| `docker-compose.yml` | Port 8101, volumes, resource limits |
| `routes/health.py` | Health check + manual ingest trigger |
| `routes/stocks.py` | Stock quotes and search |
| `routes/watchlist.py` | Watchlist CRUD |
| `routes/portfolio.py` | Paper positions and P&L |
| `routes/alerts.py` | Alert CRUD and triggers |
| `routes/analysis.py` | Agent pipeline reports |
| `routes/trading.py` | Manual + agent order execution |
| `routes/backtest.py` | Strategy simulation |
| `routes/charts.py` | OHLCV data for frontend charts |
| `services/market_data.py` | yfinance wrapper |
| `services/alpaca_client.py` | Alpaca paper trading |
| `services/agent_pipeline.py` | M.A.R.K.E.T. 4-role orchestration |
| `services/backtest_engine.py` | Historical strategy simulation |
| `services/alert_engine.py` | Alert evaluation |
| `ingest/price_ingest.py` | Background price refresh |
| `static/index.html` | LCARS single-page dashboard |
| `static/css/lcars.css` | LCARS green theme |
| `static/css/dashboard.css` | Layout, tables, cards |
| `static/js/app.js` | Tab routing, DOM init |
| `static/js/api.js` | Fetch wrapper |
| `static/js/dashboard.js` | Overview tab |
| `static/js/watchlist.js` | Watchlist tab |
| `static/js/portfolio.js` | Portfolio tab |
| `static/js/analysis.js` | Analysis tab |
| `static/js/trading.js` | Trading tab |
| `static/js/charts.js` | Charts tab (lightweight-charts) |
| `static/js/alerts.js` | Alerts tab |
| `static/js/backtest.js` | Backtest tab |

### Modified Files (A.R.C.H.I.E. platform)
| File | Change |
|------|--------|
| `docker-compose.yml` | Add `kytran_market_api` service |
| `ai_bridge/agent_loop.py` | Register `market_watch_cycle` job |
| `platform_v2/services/code_metrics_service.py` | Add to `STANDALONE_PRODUCTS` |

---

## Phase 1: Scaffold + Data Layer (Tasks 1-6)

### Task 1: Project Scaffold — Dockerfile, requirements, docker-compose

**Files:**
- Create: `market-watch/Dockerfile`
- Create: `market-watch/requirements.txt`
- Create: `market-watch/docker-compose.yml`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p market-watch
```

- [ ] **Step 2: Create requirements.txt**

Create `market-watch/requirements.txt`:

```
flask==3.1.0
yfinance==0.2.54
alpaca-py==0.38.0
requests==2.33.0
gunicorn==23.0.0
```

- [ ] **Step 3: Create Dockerfile**

Create `market-watch/Dockerfile`:

```dockerfile
FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "app.py"]
```

- [ ] **Step 4: Create docker-compose.yml**

Create `market-watch/docker-compose.yml`:

```yaml
services:
  kytran_market_api:
    build: .
    container_name: kytran_market_api
    ports:
      - "8101:8080"
    volumes:
      - market_data:/app/data
    environment:
      - ARCHIE_HUB_URL=http://192.168.1.200:3000
      - ALPACA_API_KEY=${ALPACA_API_KEY:-}
      - ALPACA_SECRET_KEY=${ALPACA_SECRET_KEY:-}
      - ALPACA_BASE_URL=https://paper-api.alpaca.markets
    read_only: true
    tmpfs:
      - /tmp
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M
    restart: unless-stopped

volumes:
  market_data:
```

- [ ] **Step 5: Commit**

```bash
git add market-watch/Dockerfile market-watch/requirements.txt market-watch/docker-compose.yml
git commit -m "feat(market-watch): project scaffold — Dockerfile, requirements, docker-compose"
```

---

### Task 2: Database Layer — db.py + schema.sql

**Files:**
- Create: `market-watch/db.py`
- Create: `market-watch/schema.sql`

- [ ] **Step 1: Create schema.sql**

Create `market-watch/schema.sql`:

```sql
-- Kytran Market Watch — M.A.R.K.E.T. Database Schema

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    notes TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL NOT NULL,
    opened_by TEXT DEFAULT 'manual',
    thesis_id INTEGER,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thesis_id) REFERENCES analyses(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    order_type TEXT DEFAULT 'market',
    executed_by TEXT DEFAULT 'manual',
    thesis_id INTEGER,
    alpaca_order_id TEXT,
    status TEXT DEFAULT 'filled' CHECK (status IN ('pending', 'filled', 'cancelled', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thesis_id) REFERENCES analyses(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('price_above', 'price_below', 'volume', 'agent')),
    threshold REAL,
    message TEXT,
    triggered INTEGER DEFAULT 0,
    triggered_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    cycle_id INTEGER,
    director_thesis TEXT,
    director_sentiment TEXT CHECK (director_sentiment IN ('bullish', 'bearish', 'neutral')),
    director_confidence REAL,
    quant_report TEXT,
    quant_score REAL,
    quant_indicators TEXT,
    risk_assessment TEXT,
    risk_approved INTEGER DEFAULT 0,
    risk_position_size REAL,
    risk_stop_loss REAL,
    recommendation TEXT CHECK (recommendation IN ('buy', 'sell', 'hold', 'skip')),
    executed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cycle_id) REFERENCES cycle_log(id)
);

CREATE TABLE IF NOT EXISTS market_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK (data_type IN ('quote', 'history', 'fundamentals', 'news')),
    data TEXT NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(ticker, data_type)
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    tickers TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_value REAL,
    total_return REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    win_rate REAL,
    trade_count INTEGER,
    equity_curve TEXT,
    trade_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    stocks_analyzed INTEGER DEFAULT 0,
    trades_made INTEGER DEFAULT 0,
    trades_skipped INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'breaker_tripped')),
    details TEXT
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failure')),
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cash_balance REAL NOT NULL DEFAULT 100000.0,
    initial_balance REAL NOT NULL DEFAULT 100000.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed paper account if empty
INSERT OR IGNORE INTO paper_account (id, cash_balance, initial_balance) VALUES (1, 100000.0, 100000.0);
```

- [ ] **Step 2: Create db.py**

Create `market-watch/db.py`:

```python
"""SQLite database connection and initialization for Market Watch."""

import os
import sqlite3

DB_PATH = os.environ.get("MW_DB_PATH", "/app/data/market.db")


def get_db():
    """Get a database connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database with schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        conn.executescript(f.read())
    conn.close()
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/db.py market-watch/schema.sql
git commit -m "feat(market-watch): database layer — SQLite schema + WAL connection"
```

---

### Task 3: Flask App + Health Route

**Files:**
- Create: `market-watch/app.py`
- Create: `market-watch/routes/__init__.py`
- Create: `market-watch/routes/health.py`

- [ ] **Step 1: Create routes/__init__.py**

```bash
mkdir -p market-watch/routes
touch market-watch/routes/__init__.py
```

- [ ] **Step 2: Create health.py**

Create `market-watch/routes/health.py`:

```python
"""Health check endpoint for Market Watch."""

import os
from flask import Blueprint, jsonify
from db import get_db, DB_PATH

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/health")
def health():
    """Health check with DB stats."""
    try:
        conn = get_db()
        watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        last_ingest = conn.execute(
            "SELECT source, status, created_at FROM ingest_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

        return jsonify({
            "status": "healthy",
            "service": "kytran-market-watch",
            "agent": "M.A.R.K.E.T.",
            "watchlist_count": watchlist_count,
            "last_ingest": {
                "source": last_ingest["source"],
                "status": last_ingest["status"],
                "timestamp": last_ingest["created_at"],
            } if last_ingest else None,
            "db_size_bytes": db_size,
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500
```

- [ ] **Step 3: Create app.py**

Create `market-watch/app.py`:

```python
"""Kytran Market Watch — M.A.R.K.E.T. Autonomous Trading Dashboard."""

import os
import time
import threading
import logging
from flask import Flask, send_from_directory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
    )

    from db import init_db
    init_db()

    from routes.health import health_bp
    app.register_blueprint(health_bp)

    @app.after_request
    def add_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, PATCH"
        return response

    @app.route("/")
    def index():
        return send_from_directory("static", "index.html")

    return app


def _background_ingest(app):
    """Background thread for market data ingestion."""
    time.sleep(10)
    with app.app_context():
        logger.info("Background ingest thread started")
        while True:
            try:
                from ingest.price_ingest import run_price_ingest
                run_price_ingest()
            except Exception as e:
                logger.error("Price ingest failed: %s", e)
            time.sleep(300)  # 5 minutes


if __name__ == "__main__":
    app = create_app()
    ingest_thread = threading.Thread(target=_background_ingest, args=(app,), daemon=True)
    ingest_thread.start()
    app.run(host="0.0.0.0", port=8080, debug=False)
```

- [ ] **Step 4: Commit**

```bash
git add market-watch/app.py market-watch/routes/__init__.py market-watch/routes/health.py
git commit -m "feat(market-watch): Flask app + health endpoint"
```

---

### Task 4: Market Data Service (yfinance)

**Files:**
- Create: `market-watch/services/__init__.py`
- Create: `market-watch/services/market_data.py`

- [ ] **Step 1: Create services directory**

```bash
mkdir -p market-watch/services
touch market-watch/services/__init__.py
```

- [ ] **Step 2: Create market_data.py**

Create `market-watch/services/market_data.py`:

```python
"""yfinance wrapper for market data."""

import json
import logging
import time
from datetime import datetime, timedelta
from db import get_db

logger = logging.getLogger(__name__)

CACHE_TTL_QUOTE = 60  # 1 minute
CACHE_TTL_HISTORY = 3600  # 1 hour
CACHE_TTL_FUNDAMENTALS = 86400  # 24 hours


def _get_cached(ticker, data_type):
    """Return cached data if not expired."""
    conn = get_db()
    row = conn.execute(
        "SELECT data, expires_at FROM market_cache WHERE ticker = ? AND data_type = ?",
        (ticker, data_type),
    ).fetchone()
    conn.close()
    if row and row["expires_at"]:
        if datetime.fromisoformat(row["expires_at"]) > datetime.utcnow():
            return json.loads(row["data"])
    return None


def _set_cache(ticker, data_type, data, ttl_seconds):
    """Store data in cache with TTL."""
    expires = (datetime.utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
    conn = get_db()
    conn.execute(
        """INSERT INTO market_cache (ticker, data_type, data, fetched_at, expires_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
           ON CONFLICT(ticker, data_type) DO UPDATE SET
           data = excluded.data, fetched_at = CURRENT_TIMESTAMP, expires_at = excluded.expires_at""",
        (ticker, data_type, json.dumps(data), expires),
    )
    conn.commit()
    conn.close()


def get_quote(ticker):
    """Get current quote for a ticker."""
    cached = _get_cached(ticker, "quote")
    if cached:
        return cached

    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info
        quote = {
            "ticker": ticker,
            "price": info.get("currentPrice") or info.get("regularMarketPrice", 0),
            "change": info.get("regularMarketChange", 0),
            "change_percent": info.get("regularMarketChangePercent", 0),
            "volume": info.get("regularMarketVolume", 0),
            "market_cap": info.get("marketCap", 0),
            "name": info.get("shortName", ticker),
            "currency": info.get("currency", "USD"),
        }
        _set_cache(ticker, "quote", quote, CACHE_TTL_QUOTE)
        return quote
    except Exception as e:
        logger.error("Failed to fetch quote for %s: %s", ticker, e)
        return {"ticker": ticker, "price": 0, "error": str(e)}


def get_history(ticker, period="3mo", interval="1d"):
    """Get OHLCV history for charting."""
    cache_key = f"{period}_{interval}"
    cached = _get_cached(ticker, "history")
    if cached and cached.get("_cache_key") == cache_key:
        return cached

    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period, interval=interval)
        records = []
        for idx, row in hist.iterrows():
            records.append({
                "time": int(idx.timestamp()),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            })
        result = {"ticker": ticker, "period": period, "interval": interval, "data": records, "_cache_key": cache_key}
        _set_cache(ticker, "history", result, CACHE_TTL_HISTORY)
        return result
    except Exception as e:
        logger.error("Failed to fetch history for %s: %s", ticker, e)
        return {"ticker": ticker, "data": [], "error": str(e)}


def get_fundamentals(ticker):
    """Get fundamental data for analysis."""
    cached = _get_cached(ticker, "fundamentals")
    if cached:
        return cached

    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        info = stock.info
        fundamentals = {
            "ticker": ticker,
            "name": info.get("shortName", ticker),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "market_cap": info.get("marketCap"),
            "revenue": info.get("totalRevenue"),
            "profit_margin": info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "roe": info.get("returnOnEquity"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "avg_volume": info.get("averageVolume"),
            "target_price": info.get("targetMeanPrice"),
        }
        _set_cache(ticker, "fundamentals", fundamentals, CACHE_TTL_FUNDAMENTALS)
        return fundamentals
    except Exception as e:
        logger.error("Failed to fetch fundamentals for %s: %s", ticker, e)
        return {"ticker": ticker, "error": str(e)}


def search_tickers(query):
    """Search for tickers by name or symbol."""
    try:
        import yfinance as yf
        results = []
        # Try direct ticker lookup
        stock = yf.Ticker(query.upper())
        info = stock.info
        if info.get("shortName"):
            results.append({
                "ticker": query.upper(),
                "name": info.get("shortName", ""),
                "exchange": info.get("exchange", ""),
                "type": info.get("quoteType", ""),
            })
        return results
    except Exception:
        return []


def calculate_indicators(ticker, period="6mo"):
    """Calculate technical indicators from history data."""
    history = get_history(ticker, period=period)
    data = history.get("data", [])
    if len(data) < 20:
        return {"ticker": ticker, "error": "Insufficient data"}

    closes = [d["close"] for d in data]

    # SMA
    sma_20 = sum(closes[-20:]) / 20
    sma_50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    sma_200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else None

    # RSI (14-period)
    gains, losses = [], []
    for i in range(1, min(15, len(closes))):
        diff = closes[-i] - closes[-i - 1]
        if diff > 0:
            gains.append(diff)
        else:
            losses.append(abs(diff))
    avg_gain = sum(gains) / 14 if gains else 0
    avg_loss = sum(losses) / 14 if losses else 0.001
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    def ema(values, window):
        if len(values) < window:
            return values[-1] if values else 0
        multiplier = 2 / (window + 1)
        result = sum(values[:window]) / window
        for val in values[window:]:
            result = (val - result) * multiplier + result
        return result

    ema_12 = ema(closes, 12)
    ema_26 = ema(closes, 26)
    macd_line = ema_12 - ema_26

    current_price = closes[-1]

    return {
        "ticker": ticker,
        "price": current_price,
        "sma_20": round(sma_20, 2),
        "sma_50": round(sma_50, 2) if sma_50 else None,
        "sma_200": round(sma_200, 2) if sma_200 else None,
        "rsi": round(rsi, 2),
        "macd": round(macd_line, 4),
        "above_sma_20": current_price > sma_20,
        "above_sma_50": current_price > sma_50 if sma_50 else None,
    }
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/services/__init__.py market-watch/services/market_data.py
git commit -m "feat(market-watch): yfinance market data service with caching + indicators"
```

---

### Task 5: Stock + Watchlist + Charts Routes

**Files:**
- Create: `market-watch/routes/stocks.py`
- Create: `market-watch/routes/watchlist.py`
- Create: `market-watch/routes/charts.py`

- [ ] **Step 1: Create stocks.py**

Create `market-watch/routes/stocks.py`:

```python
"""Stock quote and search endpoints."""

from flask import Blueprint, jsonify, request
from services.market_data import get_quote, get_fundamentals, search_tickers

stocks_bp = Blueprint("stocks", __name__)


@stocks_bp.route("/api/stocks/<ticker>")
def stock_quote(ticker):
    """Get current quote for a ticker."""
    quote = get_quote(ticker.upper())
    return jsonify({"success": True, **quote})


@stocks_bp.route("/api/stocks/<ticker>/fundamentals")
def stock_fundamentals(ticker):
    """Get fundamental data for a ticker."""
    data = get_fundamentals(ticker.upper())
    return jsonify({"success": True, **data})


@stocks_bp.route("/api/stocks/search")
def stock_search():
    """Search for tickers."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"success": False, "error": "Query required"}), 400
    results = search_tickers(q)
    return jsonify({"success": True, "results": results})
```

- [ ] **Step 2: Create watchlist.py**

Create `market-watch/routes/watchlist.py`:

```python
"""Watchlist CRUD endpoints."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.market_data import get_quote

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/api/watchlist")
def list_watchlist():
    """Get all watchlist items with current prices."""
    conn = get_db()
    items = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    conn.close()

    result = []
    for item in items:
        quote = get_quote(item["ticker"])
        result.append({
            "id": item["id"],
            "ticker": item["ticker"],
            "notes": item["notes"],
            "added_at": item["added_at"],
            "price": quote.get("price", 0),
            "change_percent": quote.get("change_percent", 0),
            "name": quote.get("name", item["ticker"]),
        })
    return jsonify({"success": True, "items": result, "count": len(result)})


@watchlist_bp.route("/api/watchlist", methods=["POST"])
def add_to_watchlist():
    """Add a ticker to the watchlist."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper().strip()
    notes = data.get("notes", "")

    if not ticker:
        return jsonify({"success": False, "error": "Ticker required"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO watchlist (ticker, notes) VALUES (?, ?)",
            (ticker, notes),
        )
        conn.commit()
        return jsonify({"success": True, "ticker": ticker})
    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"success": False, "error": f"{ticker} already in watchlist"}), 409
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@watchlist_bp.route("/api/watchlist/<int:item_id>", methods=["DELETE"])
def remove_from_watchlist(item_id):
    """Remove a ticker from the watchlist."""
    conn = get_db()
    conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@watchlist_bp.route("/api/watchlist/bulk", methods=["POST"])
def bulk_add():
    """Add multiple tickers at once (comma-separated)."""
    data = request.get_json() or {}
    tickers_str = data.get("tickers", "")
    tickers = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    conn = get_db()
    added = []
    skipped = []
    for ticker in tickers:
        try:
            conn.execute("INSERT INTO watchlist (ticker) VALUES (?)", (ticker,))
            added.append(ticker)
        except Exception:
            skipped.append(ticker)
    conn.commit()
    conn.close()
    return jsonify({"success": True, "added": added, "skipped": skipped})
```

- [ ] **Step 3: Create charts.py**

Create `market-watch/routes/charts.py`:

```python
"""OHLCV chart data endpoints."""

from flask import Blueprint, jsonify, request
from services.market_data import get_history, calculate_indicators

charts_bp = Blueprint("charts", __name__)


@charts_bp.route("/api/charts/<ticker>")
def chart_data(ticker):
    """Get OHLCV data for charting."""
    period = request.args.get("period", "3mo")
    interval = request.args.get("interval", "1d")
    history = get_history(ticker.upper(), period=period, interval=interval)
    return jsonify({"success": True, **history})


@charts_bp.route("/api/charts/<ticker>/indicators")
def chart_indicators(ticker):
    """Get technical indicators."""
    indicators = calculate_indicators(ticker.upper())
    return jsonify({"success": True, **indicators})
```

- [ ] **Step 4: Register blueprints in app.py**

Add to `market-watch/app.py` inside `create_app()`, after the health blueprint registration:

```python
    from routes.stocks import stocks_bp
    from routes.watchlist import watchlist_bp
    from routes.charts import charts_bp
    app.register_blueprint(stocks_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(charts_bp)
```

- [ ] **Step 5: Commit**

```bash
git add market-watch/routes/stocks.py market-watch/routes/watchlist.py market-watch/routes/charts.py market-watch/app.py
git commit -m "feat(market-watch): stock quotes, watchlist CRUD, chart data routes"
```

---

### Task 6: Price Ingest Background Thread

**Files:**
- Create: `market-watch/ingest/__init__.py`
- Create: `market-watch/ingest/price_ingest.py`

- [ ] **Step 1: Create ingest directory**

```bash
mkdir -p market-watch/ingest
touch market-watch/ingest/__init__.py
```

- [ ] **Step 2: Create price_ingest.py**

Create `market-watch/ingest/price_ingest.py`:

```python
"""Background price data ingestion for watchlist tickers."""

import time
import logging
from db import get_db
from services.market_data import get_quote

logger = logging.getLogger(__name__)


def run_price_ingest():
    """Refresh quotes for all watchlist tickers."""
    start = time.time()
    conn = get_db()
    tickers = conn.execute("SELECT ticker FROM watchlist").fetchall()
    conn.close()

    if not tickers:
        return

    count = 0
    errors = 0
    for row in tickers:
        try:
            get_quote(row["ticker"])
            count += 1
            time.sleep(0.5)  # Rate limit
        except Exception as e:
            logger.error("Ingest failed for %s: %s", row["ticker"], e)
            errors += 1

    duration_ms = int((time.time() - start) * 1000)

    conn = get_db()
    conn.execute(
        "INSERT INTO ingest_log (source, status, records_count, error_message, duration_ms) VALUES (?, ?, ?, ?, ?)",
        ("price_refresh", "success" if errors == 0 else "failure", count, f"{errors} errors" if errors else None, duration_ms),
    )
    conn.commit()
    conn.close()
    logger.info("Price ingest: %d tickers refreshed in %dms (%d errors)", count, duration_ms, errors)
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/ingest/__init__.py market-watch/ingest/price_ingest.py
git commit -m "feat(market-watch): background price ingest for watchlist tickers"
```

---

## Phase 2: Trading + Portfolio (Tasks 7-10)

### Task 7: Alpaca Paper Trading Client

**Files:**
- Create: `market-watch/services/alpaca_client.py`

- [ ] **Step 1: Create alpaca_client.py**

Create `market-watch/services/alpaca_client.py`:

```python
"""Alpaca paper trading client."""

import os
import logging

logger = logging.getLogger(__name__)

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def _get_client():
    """Get Alpaca trading client. Returns None if not configured."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return None
    try:
        from alpaca.trading.client import TradingClient
        return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    except Exception as e:
        logger.error("Alpaca client init failed: %s", e)
        return None


def get_account():
    """Get paper trading account info."""
    client = _get_client()
    if not client:
        return {"configured": False, "error": "Alpaca API keys not set"}
    try:
        account = client.get_account()
        return {
            "configured": True,
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "buying_power": float(account.buying_power),
            "equity": float(account.equity),
            "status": account.status,
        }
    except Exception as e:
        return {"configured": True, "error": str(e)}


def place_order(ticker, qty, side, order_type="market", limit_price=None):
    """Place a paper trade order."""
    client = _get_client()
    if not client:
        return {"success": False, "error": "Alpaca not configured"}
    try:
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        if order_type == "limit" and limit_price:
            req = LimitOrderRequest(
                symbol=ticker, qty=qty, side=order_side,
                time_in_force=TimeInForce.DAY, limit_price=limit_price,
            )
        else:
            req = MarketOrderRequest(
                symbol=ticker, qty=qty, side=order_side,
                time_in_force=TimeInForce.DAY,
            )

        order = client.submit_order(req)
        return {
            "success": True,
            "order_id": str(order.id),
            "status": str(order.status),
            "ticker": ticker,
            "side": side,
            "qty": qty,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_positions():
    """Get all open positions."""
    client = _get_client()
    if not client:
        return []
    try:
        positions = client.get_all_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": float(p.qty),
                "avg_cost": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in positions
        ]
    except Exception as e:
        logger.error("Failed to get positions: %s", e)
        return []


def get_orders(status="all"):
    """Get recent orders."""
    client = _get_client()
    if not client:
        return []
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        status_map = {"all": QueryOrderStatus.ALL, "open": QueryOrderStatus.OPEN, "closed": QueryOrderStatus.CLOSED}
        req = GetOrdersRequest(status=status_map.get(status, QueryOrderStatus.ALL), limit=50)
        orders = client.get_orders(req)
        return [
            {
                "order_id": str(o.id),
                "ticker": o.symbol,
                "side": str(o.side),
                "qty": float(o.qty) if o.qty else 0,
                "filled_qty": float(o.filled_qty) if o.filled_qty else 0,
                "type": str(o.type),
                "status": str(o.status),
                "created_at": str(o.created_at),
            }
            for o in orders
        ]
    except Exception as e:
        logger.error("Failed to get orders: %s", e)
        return []
```

- [ ] **Step 2: Commit**

```bash
git add market-watch/services/alpaca_client.py
git commit -m "feat(market-watch): Alpaca paper trading client"
```

---

### Task 8: Portfolio Route

**Files:**
- Create: `market-watch/routes/portfolio.py`

- [ ] **Step 1: Create portfolio.py**

Create `market-watch/routes/portfolio.py`:

```python
"""Portfolio and paper trading account endpoints."""

from flask import Blueprint, jsonify
from db import get_db
from services.market_data import get_quote
from services.alpaca_client import get_account, get_positions

portfolio_bp = Blueprint("portfolio", __name__)


@portfolio_bp.route("/api/portfolio")
def portfolio_overview():
    """Get portfolio positions with current P&L."""
    positions = get_positions()
    account = get_account()

    # Also get local transaction history
    conn = get_db()
    transactions = conn.execute(
        "SELECT * FROM transactions ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()

    return jsonify({
        "success": True,
        "account": account,
        "positions": positions,
        "recent_transactions": [dict(t) for t in transactions],
    })


@portfolio_bp.route("/api/portfolio/summary")
def portfolio_summary():
    """Quick portfolio summary for dashboard."""
    account = get_account()
    positions = get_positions()

    total_pl = sum(p.get("unrealized_pl", 0) for p in positions)
    position_count = len(positions)

    return jsonify({
        "success": True,
        "portfolio_value": account.get("portfolio_value", 0),
        "cash": account.get("cash", 0),
        "total_unrealized_pl": round(total_pl, 2),
        "position_count": position_count,
        "configured": account.get("configured", False),
    })
```

- [ ] **Step 2: Register in app.py**

Add to `create_app()`:

```python
    from routes.portfolio import portfolio_bp
    app.register_blueprint(portfolio_bp)
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/routes/portfolio.py market-watch/app.py
git commit -m "feat(market-watch): portfolio route with Alpaca positions + P&L"
```

---

### Task 9: Trading Route

**Files:**
- Create: `market-watch/routes/trading.py`

- [ ] **Step 1: Create trading.py**

Create `market-watch/routes/trading.py`:

```python
"""Trading endpoints — manual and agent orders."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.alpaca_client import place_order, get_orders
from services.market_data import get_quote

trading_bp = Blueprint("trading", __name__)


@trading_bp.route("/api/trading/buy", methods=["POST"])
def buy():
    """Place a buy order."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    qty = data.get("qty", 0)
    order_type = data.get("order_type", "market")
    limit_price = data.get("limit_price")

    if not ticker or qty <= 0:
        return jsonify({"success": False, "error": "Valid ticker and qty required"}), 400

    result = place_order(ticker, qty, "buy", order_type, limit_price)

    if result["success"]:
        quote = get_quote(ticker)
        conn = get_db()
        conn.execute(
            """INSERT INTO transactions (ticker, action, quantity, price, order_type, executed_by, alpaca_order_id, status)
               VALUES (?, 'buy', ?, ?, ?, 'manual', ?, 'filled')""",
            (ticker, qty, quote.get("price", 0), order_type, result.get("order_id")),
        )
        conn.commit()
        conn.close()

    return jsonify(result)


@trading_bp.route("/api/trading/sell", methods=["POST"])
def sell():
    """Place a sell order."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    qty = data.get("qty", 0)
    order_type = data.get("order_type", "market")
    limit_price = data.get("limit_price")

    if not ticker or qty <= 0:
        return jsonify({"success": False, "error": "Valid ticker and qty required"}), 400

    result = place_order(ticker, qty, "sell", order_type, limit_price)

    if result["success"]:
        quote = get_quote(ticker)
        conn = get_db()
        conn.execute(
            """INSERT INTO transactions (ticker, action, quantity, price, order_type, executed_by, alpaca_order_id, status)
               VALUES (?, 'sell', ?, ?, ?, 'manual', ?, 'filled')""",
            (ticker, qty, quote.get("price", 0), order_type, result.get("order_id")),
        )
        conn.commit()
        conn.close()

    return jsonify(result)


@trading_bp.route("/api/trading/orders")
def order_history():
    """Get order history."""
    status = request.args.get("status", "all")
    orders = get_orders(status)
    return jsonify({"success": True, "orders": orders})
```

- [ ] **Step 2: Register in app.py**

Add to `create_app()`:

```python
    from routes.trading import trading_bp
    app.register_blueprint(trading_bp)
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/routes/trading.py market-watch/app.py
git commit -m "feat(market-watch): trading routes — buy/sell/order history via Alpaca"
```

---

### Task 10: Alerts Route

**Files:**
- Create: `market-watch/routes/alerts.py`
- Create: `market-watch/services/alert_engine.py`

- [ ] **Step 1: Create alert_engine.py**

Create `market-watch/services/alert_engine.py`:

```python
"""Alert evaluation engine."""

import logging
from db import get_db
from services.market_data import get_quote

logger = logging.getLogger(__name__)


def check_alerts():
    """Evaluate all untriggered alerts against current prices."""
    conn = get_db()
    alerts = conn.execute("SELECT * FROM alerts WHERE triggered = 0").fetchall()

    triggered = []
    for alert in alerts:
        quote = get_quote(alert["ticker"])
        price = quote.get("price", 0)
        if not price:
            continue

        fire = False
        if alert["alert_type"] == "price_above" and price >= alert["threshold"]:
            fire = True
        elif alert["alert_type"] == "price_below" and price <= alert["threshold"]:
            fire = True
        elif alert["alert_type"] == "volume":
            volume = quote.get("volume", 0)
            if volume >= alert["threshold"]:
                fire = True

        if fire:
            conn.execute(
                "UPDATE alerts SET triggered = 1, triggered_at = CURRENT_TIMESTAMP WHERE id = ?",
                (alert["id"],),
            )
            triggered.append(dict(alert))

    conn.commit()
    conn.close()
    return triggered
```

- [ ] **Step 2: Create alerts.py route**

Create `market-watch/routes/alerts.py`:

```python
"""Alert CRUD endpoints."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.alert_engine import check_alerts

alerts_bp = Blueprint("alerts", __name__)


@alerts_bp.route("/api/alerts")
def list_alerts():
    """Get all alerts."""
    conn = get_db()
    alerts = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify({"success": True, "alerts": [dict(a) for a in alerts]})


@alerts_bp.route("/api/alerts", methods=["POST"])
def create_alert():
    """Create a new alert."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    alert_type = data.get("alert_type", "price_above")
    threshold = data.get("threshold")
    message = data.get("message", "")

    if not ticker or threshold is None:
        return jsonify({"success": False, "error": "Ticker and threshold required"}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO alerts (ticker, alert_type, threshold, message) VALUES (?, ?, ?, ?)",
        (ticker, alert_type, threshold, message),
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "ticker": ticker, "alert_type": alert_type})


@alerts_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
def delete_alert(alert_id):
    """Delete an alert."""
    conn = get_db()
    conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@alerts_bp.route("/api/alerts/check", methods=["POST"])
def trigger_check():
    """Manually check all alerts."""
    triggered = check_alerts()
    return jsonify({"success": True, "triggered": triggered, "count": len(triggered)})
```

- [ ] **Step 3: Register in app.py**

Add to `create_app()`:

```python
    from routes.alerts import alerts_bp
    app.register_blueprint(alerts_bp)
```

- [ ] **Step 4: Commit**

```bash
git add market-watch/services/alert_engine.py market-watch/routes/alerts.py market-watch/app.py
git commit -m "feat(market-watch): alerts engine + CRUD routes"
```

---

## Phase 3: Agent Pipeline (Tasks 11-13)

### Task 11: M.A.R.K.E.T. Agent Pipeline Service

**Files:**
- Create: `market-watch/services/agent_pipeline.py`

- [ ] **Step 1: Create agent_pipeline.py**

Create `market-watch/services/agent_pipeline.py`:

```python
"""M.A.R.K.E.T. 4-role agent pipeline orchestration via Bridge dispatcher."""

import json
import logging
import os
import requests
from db import get_db
from services.market_data import get_quote, get_fundamentals, calculate_indicators

logger = logging.getLogger(__name__)

ARCHIE_HUB_URL = os.environ.get("ARCHIE_HUB_URL", "http://192.168.1.200:3000")

# Circuit breaker limits
MAX_TRADES_PER_DAY = 10
MAX_PORTFOLIO_EXPOSURE = 0.8
MAX_SINGLE_POSITION = 0.2
MAX_DAILY_LOSS_PCT = 0.05
MAX_CONSECUTIVE_LOSSES = 5


def _dispatch_to_bridge(capability, prompt, system_prompt):
    """Dispatch a prompt to A.R.C.H.I.E. Bridge for LLM inference."""
    try:
        resp = requests.post(
            f"{ARCHIE_HUB_URL}/api/bridge/dispatch",
            json={
                "capability": capability,
                "prompt": prompt,
                "module_id": "market_watch",
                "system_prompt": system_prompt,
                "json_mode": True,
            },
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"success": True, "response": data.get("response", "")}
        return {"success": False, "error": f"Bridge returned {resp.status_code}"}
    except Exception as e:
        logger.error("Bridge dispatch failed: %s", e)
        return {"success": False, "error": str(e)}


def _check_circuit_breaker():
    """Check if circuit breaker should trip."""
    conn = get_db()

    # Check trades today
    today_trades = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE date(created_at) = date('now') AND executed_by != 'manual'"
    ).fetchone()[0]
    if today_trades >= MAX_TRADES_PER_DAY:
        conn.close()
        return False, f"Max daily trades reached ({MAX_TRADES_PER_DAY})"

    # Check consecutive losses
    recent = conn.execute(
        "SELECT * FROM transactions WHERE executed_by != 'manual' ORDER BY created_at DESC LIMIT ?",
        (MAX_CONSECUTIVE_LOSSES,),
    ).fetchall()
    conn.close()

    # More sophisticated checks would go here
    return True, "OK"


def run_director(ticker, market_data):
    """Step 1: Director generates trading thesis."""
    prompt = f"""Analyze {ticker} for a trading opportunity.

Current Price: ${market_data.get('price', 0)}
Change: {market_data.get('change_percent', 0):.2f}%
RSI: {market_data.get('rsi', 'N/A')}
SMA 20: {market_data.get('sma_20', 'N/A')}
SMA 50: {market_data.get('sma_50', 'N/A')}
MACD: {market_data.get('macd', 'N/A')}
PE Ratio: {market_data.get('pe_ratio', 'N/A')}
Market Cap: {market_data.get('market_cap', 'N/A')}

Provide a JSON response with:
{{"sentiment": "bullish|bearish|neutral", "confidence": 0.0-1.0, "thesis": "your analysis", "entry_price": number_or_null, "target_price": number_or_null}}"""

    system = (
        "You are M.A.R.K.E.T.'s Director Agent. You analyze stocks and generate trading theses. "
        "Be data-driven. Consider both technical and fundamental factors. "
        "Respond ONLY with valid JSON."
    )
    return _dispatch_to_bridge("thesis", prompt, system)


def run_quant(ticker, market_data, thesis):
    """Step 2: Quant validates thesis with technical analysis."""
    prompt = f"""Validate this trading thesis for {ticker}:

Director's Thesis: {thesis}

Technical Data:
Price: ${market_data.get('price', 0)}
RSI: {market_data.get('rsi', 'N/A')}
SMA 20: {market_data.get('sma_20', 'N/A')}
SMA 50: {market_data.get('sma_50', 'N/A')}
MACD: {market_data.get('macd', 'N/A')}
Above SMA 20: {market_data.get('above_sma_20', 'N/A')}
Above SMA 50: {market_data.get('above_sma_50', 'N/A')}

Provide a JSON response with:
{{"score": -1.0_to_1.0, "confirms_thesis": true|false, "technical_summary": "analysis", "key_signals": ["signal1", "signal2"]}}"""

    system = (
        "You are M.A.R.K.E.T.'s Quant Agent. You validate trading theses with technical analysis. "
        "Score from -1.0 (strong sell) to 1.0 (strong buy). Be rigorous. "
        "Respond ONLY with valid JSON."
    )
    return _dispatch_to_bridge("quant_analysis", prompt, system)


def run_risk(ticker, market_data, thesis, quant_score, portfolio_value):
    """Step 3: Risk Manager assesses position sizing and risk."""
    prompt = f"""Assess risk for a potential {ticker} trade:

Thesis: {thesis}
Quant Score: {quant_score}
Current Price: ${market_data.get('price', 0)}
Portfolio Value: ${portfolio_value}
Max Single Position: {MAX_SINGLE_POSITION * 100}%
Max Portfolio Exposure: {MAX_PORTFOLIO_EXPOSURE * 100}%

Provide a JSON response with:
{{"approved": true|false, "position_size_pct": 0.0-0.2, "stop_loss_pct": 0.0-0.1, "reason": "explanation", "max_shares": integer}}"""

    system = (
        "You are M.A.R.K.E.T.'s Risk Manager. You protect the portfolio from excessive risk. "
        "You have VETO power. If the trade is too risky, reject it. "
        "Position sizes must respect max limits. Always set a stop-loss. "
        "Respond ONLY with valid JSON."
    )
    return _dispatch_to_bridge("risk_assessment", prompt, system)


def run_pipeline(ticker):
    """Run the full M.A.R.K.E.T. pipeline for a single ticker."""
    # Check circuit breaker first
    ok, reason = _check_circuit_breaker()
    if not ok:
        return {"success": False, "action": "breaker_tripped", "reason": reason}

    # Gather market data
    quote = get_quote(ticker)
    indicators = calculate_indicators(ticker)
    fundamentals = get_fundamentals(ticker)
    market_data = {**quote, **indicators, **fundamentals}

    # Start cycle log
    conn = get_db()
    cur = conn.execute("INSERT INTO cycle_log (status) VALUES ('running')")
    cycle_id = cur.lastrowid
    conn.commit()
    conn.close()

    result = {"ticker": ticker, "cycle_id": cycle_id, "steps": {}}

    # Step 1: Director
    director = run_director(ticker, market_data)
    result["steps"]["director"] = director
    if not director["success"]:
        _complete_cycle(cycle_id, "failed", 1, 0, 0, 1)
        return {**result, "success": False, "action": "director_failed"}

    thesis_text = director["response"]
    try:
        thesis_data = json.loads(thesis_text)
    except (json.JSONDecodeError, TypeError):
        thesis_data = {"sentiment": "neutral", "confidence": 0.5, "thesis": thesis_text}

    # Step 2: Quant
    quant = run_quant(ticker, market_data, thesis_text)
    result["steps"]["quant"] = quant
    if not quant["success"]:
        _complete_cycle(cycle_id, "failed", 1, 0, 0, 1)
        return {**result, "success": False, "action": "quant_failed"}

    try:
        quant_data = json.loads(quant["response"])
    except (json.JSONDecodeError, TypeError):
        quant_data = {"score": 0, "confirms_thesis": False}

    # Step 3: Risk
    portfolio_value = 100000  # Default; would come from Alpaca account
    risk = run_risk(ticker, market_data, thesis_text, quant_data.get("score", 0), portfolio_value)
    result["steps"]["risk"] = risk
    if not risk["success"]:
        _complete_cycle(cycle_id, "failed", 1, 0, 0, 1)
        return {**result, "success": False, "action": "risk_failed"}

    try:
        risk_data = json.loads(risk["response"])
    except (json.JSONDecodeError, TypeError):
        risk_data = {"approved": False, "reason": "Failed to parse risk response"}

    # Save analysis
    conn = get_db()
    conn.execute(
        """INSERT INTO analyses (ticker, cycle_id, director_thesis, director_sentiment, director_confidence,
           quant_report, quant_score, quant_indicators, risk_assessment, risk_approved, risk_position_size,
           risk_stop_loss, recommendation)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ticker, cycle_id, thesis_text,
            thesis_data.get("sentiment", "neutral"),
            thesis_data.get("confidence", 0.5),
            quant["response"], quant_data.get("score", 0),
            json.dumps(quant_data.get("key_signals", [])),
            risk["response"], 1 if risk_data.get("approved") else 0,
            risk_data.get("position_size_pct", 0),
            risk_data.get("stop_loss_pct", 0),
            "buy" if risk_data.get("approved") and thesis_data.get("sentiment") == "bullish"
            else "sell" if risk_data.get("approved") and thesis_data.get("sentiment") == "bearish"
            else "skip",
        ),
    )
    conn.commit()
    conn.close()

    # Step 4: Execute (if approved)
    if risk_data.get("approved"):
        from services.alpaca_client import place_order, get_account
        account = get_account()
        max_shares = risk_data.get("max_shares", 1)
        side = "buy" if thesis_data.get("sentiment") == "bullish" else "sell"

        order_result = place_order(ticker, max_shares, side)
        result["steps"]["execution"] = order_result

        if order_result.get("success"):
            conn = get_db()
            conn.execute(
                """INSERT INTO transactions (ticker, action, quantity, price, executed_by, thesis_id, alpaca_order_id)
                   VALUES (?, ?, ?, ?, 'M.A.R.K.E.T.', (SELECT MAX(id) FROM analyses WHERE ticker = ?), ?)""",
                (ticker, side, max_shares, market_data.get("price", 0), ticker, order_result.get("order_id")),
            )
            conn.commit()
            conn.close()
            _complete_cycle(cycle_id, "completed", 1, 1, 0, 0)
            return {**result, "success": True, "action": "executed", "recommendation": side}

    _complete_cycle(cycle_id, "completed", 1, 0, 1, 0)
    return {**result, "success": True, "action": "skipped", "reason": risk_data.get("reason", "Risk rejected")}


def _complete_cycle(cycle_id, status, analyzed, trades, skipped, errors):
    """Update cycle_log with results."""
    conn = get_db()
    conn.execute(
        """UPDATE cycle_log SET completed_at = CURRENT_TIMESTAMP, status = ?,
           stocks_analyzed = ?, trades_made = ?, trades_skipped = ?, errors = ?
           WHERE id = ?""",
        (status, analyzed, trades, skipped, errors, cycle_id),
    )
    conn.commit()
    conn.close()


def run_full_cycle():
    """Run pipeline for all watchlist stocks."""
    conn = get_db()
    tickers = conn.execute("SELECT ticker FROM watchlist").fetchall()
    conn.close()

    if not tickers:
        return {"success": True, "message": "Watchlist empty", "results": []}

    results = []
    for row in tickers:
        result = run_pipeline(row["ticker"])
        results.append(result)

    return {
        "success": True,
        "stocks_analyzed": len(results),
        "trades": sum(1 for r in results if r.get("action") == "executed"),
        "skipped": sum(1 for r in results if r.get("action") == "skipped"),
        "failed": sum(1 for r in results if not r.get("success")),
        "results": results,
    }
```

- [ ] **Step 2: Commit**

```bash
git add market-watch/services/agent_pipeline.py
git commit -m "feat(market-watch): M.A.R.K.E.T. 4-role agent pipeline via Bridge dispatch"
```

---

### Task 12: Analysis Route

**Files:**
- Create: `market-watch/routes/analysis.py`

- [ ] **Step 1: Create analysis.py**

Create `market-watch/routes/analysis.py`:

```python
"""Agent analysis endpoints."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.agent_pipeline import run_pipeline, run_full_cycle

analysis_bp = Blueprint("analysis", __name__)


@analysis_bp.route("/api/analysis")
def list_analyses():
    """Get recent analyses."""
    ticker = request.args.get("ticker")
    limit = request.args.get("limit", 20, type=int)

    conn = get_db()
    if ticker:
        rows = conn.execute(
            "SELECT * FROM analyses WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
            (ticker.upper(), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return jsonify({"success": True, "analyses": [dict(r) for r in rows]})


@analysis_bp.route("/api/analysis/run", methods=["POST"])
def run_analysis():
    """Run M.A.R.K.E.T. pipeline for a single ticker."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    if not ticker:
        return jsonify({"success": False, "error": "Ticker required"}), 400
    result = run_pipeline(ticker)
    return jsonify(result)


@analysis_bp.route("/api/analysis/cycle", methods=["POST"])
def run_cycle():
    """Run full M.A.R.K.E.T. cycle for all watchlist stocks."""
    result = run_full_cycle()
    return jsonify(result)


@analysis_bp.route("/api/analysis/cycles")
def list_cycles():
    """Get cycle history."""
    conn = get_db()
    cycles = conn.execute("SELECT * FROM cycle_log ORDER BY started_at DESC LIMIT 20").fetchall()
    conn.close()
    return jsonify({"success": True, "cycles": [dict(c) for c in cycles]})
```

- [ ] **Step 2: Register in app.py**

Add to `create_app()`:

```python
    from routes.analysis import analysis_bp
    app.register_blueprint(analysis_bp)
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/routes/analysis.py market-watch/app.py
git commit -m "feat(market-watch): analysis routes — run pipeline, view reports, cycle history"
```

---

### Task 13: Backtest Engine + Route

**Files:**
- Create: `market-watch/services/backtest_engine.py`
- Create: `market-watch/routes/backtest.py`

- [ ] **Step 1: Create backtest_engine.py**

Create `market-watch/services/backtest_engine.py`:

```python
"""Historical strategy backtesting engine."""

import json
import logging
import math
from services.market_data import get_history

logger = logging.getLogger(__name__)


def run_backtest(tickers, strategy="sma_crossover", start_date=None, end_date=None, initial_capital=100000):
    """Run a backtest simulation."""
    if strategy == "sma_crossover":
        return _sma_crossover_backtest(tickers, initial_capital)
    return {"success": False, "error": f"Unknown strategy: {strategy}"}


def _sma_crossover_backtest(tickers, initial_capital):
    """Simple SMA 20/50 crossover strategy backtest."""
    results = []
    for ticker in tickers:
        history = get_history(ticker, period="1y")
        data = history.get("data", [])
        if len(data) < 50:
            results.append({"ticker": ticker, "error": "Insufficient data"})
            continue

        closes = [d["close"] for d in data]
        cash = initial_capital / len(tickers)
        shares = 0
        trades = []
        equity_curve = []

        for i in range(50, len(closes)):
            sma_20 = sum(closes[i - 20:i]) / 20
            sma_50 = sum(closes[i - 50:i]) / 50
            price = closes[i]

            portfolio_value = cash + shares * price
            equity_curve.append({"time": data[i]["time"], "value": round(portfolio_value, 2)})

            # Buy signal: SMA 20 crosses above SMA 50
            if sma_20 > sma_50 and shares == 0:
                shares = int(cash / price)
                if shares > 0:
                    cash -= shares * price
                    trades.append({"action": "buy", "price": price, "shares": shares, "time": data[i]["time"]})

            # Sell signal: SMA 20 crosses below SMA 50
            elif sma_20 < sma_50 and shares > 0:
                cash += shares * price
                trades.append({"action": "sell", "price": price, "shares": shares, "time": data[i]["time"]})
                shares = 0

        final_value = cash + shares * closes[-1]
        total_return = (final_value - initial_capital / len(tickers)) / (initial_capital / len(tickers))

        # Calculate Sharpe ratio
        returns = []
        for i in range(1, len(equity_curve)):
            r = (equity_curve[i]["value"] - equity_curve[i - 1]["value"]) / equity_curve[i - 1]["value"]
            returns.append(r)
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 1
        sharpe = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0

        # Max drawdown
        peak = equity_curve[0]["value"]
        max_dd = 0
        for point in equity_curve:
            if point["value"] > peak:
                peak = point["value"]
            dd = (peak - point["value"]) / peak
            if dd > max_dd:
                max_dd = dd

        wins = sum(1 for i in range(1, len(trades), 2) if i < len(trades) and trades[i]["price"] > trades[i - 1]["price"])
        total_trades = len(trades) // 2

        results.append({
            "ticker": ticker,
            "initial_capital": initial_capital / len(tickers),
            "final_value": round(final_value, 2),
            "total_return": round(total_return * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            "trade_count": total_trades,
            "equity_curve": equity_curve,
            "trades": trades,
        })

    return {"success": True, "strategy": "sma_crossover", "results": results}
```

- [ ] **Step 2: Create backtest.py route**

Create `market-watch/routes/backtest.py`:

```python
"""Backtest endpoints."""

import json
from flask import Blueprint, jsonify, request
from db import get_db
from services.backtest_engine import run_backtest

backtest_bp = Blueprint("backtest", __name__)


@backtest_bp.route("/api/backtest/run", methods=["POST"])
def run():
    """Run a backtest."""
    data = request.get_json() or {}
    tickers = data.get("tickers", [])
    strategy = data.get("strategy", "sma_crossover")
    initial_capital = data.get("initial_capital", 100000)

    if not tickers:
        return jsonify({"success": False, "error": "Tickers required"}), 400

    result = run_backtest(tickers, strategy, initial_capital=initial_capital)

    # Save to DB
    if result["success"]:
        conn = get_db()
        for r in result.get("results", []):
            conn.execute(
                """INSERT INTO backtest_results (strategy, tickers, start_date, end_date, initial_capital,
                   final_value, total_return, sharpe_ratio, max_drawdown, win_rate, trade_count,
                   equity_curve, trade_log)
                   VALUES (?, ?, '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    strategy, r["ticker"], r["initial_capital"], r.get("final_value"),
                    r.get("total_return"), r.get("sharpe_ratio"), r.get("max_drawdown"),
                    r.get("win_rate"), r.get("trade_count"),
                    json.dumps(r.get("equity_curve", [])), json.dumps(r.get("trades", [])),
                ),
            )
        conn.commit()
        conn.close()

    return jsonify(result)


@backtest_bp.route("/api/backtest/results")
def results():
    """Get past backtest results."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM backtest_results ORDER BY created_at DESC LIMIT 20").fetchall()
    conn.close()
    return jsonify({"success": True, "results": [dict(r) for r in rows]})
```

- [ ] **Step 3: Register in app.py**

Add to `create_app()`:

```python
    from routes.backtest import backtest_bp
    app.register_blueprint(backtest_bp)
```

- [ ] **Step 4: Commit**

```bash
git add market-watch/services/backtest_engine.py market-watch/routes/backtest.py market-watch/app.py
git commit -m "feat(market-watch): backtest engine + routes — SMA crossover strategy"
```

---

## Phase 4: UI + Autonomy + Deploy (Tasks 14-17)

### Task 14: LCARS Frontend — HTML + CSS + Core JS

**Files:**
- Create: `market-watch/static/index.html`
- Create: `market-watch/static/css/lcars.css`
- Create: `market-watch/static/css/dashboard.css`
- Create: `market-watch/static/js/app.js`
- Create: `market-watch/static/js/api.js`

This is the largest task. The implementer should:

1. Read the existing Legal Watch or Civic Watch `index.html` and CSS to match the LCARS pattern exactly
2. Create a single-page app with 8 tabs: Dashboard, Watchlist, Portfolio, Alerts, Analysis, Trading, Charts, Backtest
3. Use green accent color (`#10b981`) throughout
4. Brand as "Kytran Market Watch" with M.A.R.K.E.T. agent name
5. Include the LCARS header with elbow corner, tab navigation with active states, live pulse indicator
6. Use `textContent` for user data, DOM creation methods for structured HTML

**The implementer should reference these existing files for exact patterns:**
- `legal-watch/static/index.html` — tab structure, LCARS header
- `legal-watch/static/css/lcars.css` — theme variables, header, tab styles
- `watch-api/static/index.html` — alternative reference

**API endpoints to consume (all already implemented in Tasks 3-13):**
- `GET /api/health`
- `GET /api/watchlist`, `POST /api/watchlist`, `DELETE /api/watchlist/<id>`, `POST /api/watchlist/bulk`
- `GET /api/stocks/<ticker>`, `GET /api/stocks/<ticker>/fundamentals`, `GET /api/stocks/search`
- `GET /api/portfolio`, `GET /api/portfolio/summary`
- `GET /api/alerts`, `POST /api/alerts`, `DELETE /api/alerts/<id>`, `POST /api/alerts/check`
- `GET /api/analysis`, `POST /api/analysis/run`, `POST /api/analysis/cycle`, `GET /api/analysis/cycles`
- `POST /api/trading/buy`, `POST /api/trading/sell`, `GET /api/trading/orders`
- `GET /api/charts/<ticker>`, `GET /api/charts/<ticker>/indicators`
- `POST /api/backtest/run`, `GET /api/backtest/results`

**For charts:** Use lightweight-charts from CDN: `https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js`

- [ ] **Step 1: Create CSS directory and files**

```bash
mkdir -p market-watch/static/css market-watch/static/js
```

- [ ] **Step 2: Create lcars.css, dashboard.css, index.html, app.js, api.js**

Follow the existing Watch product patterns. Green accent `#10b981`. 8 tabs. LCARS header with elbow. Live pulse. Responsive layout.

- [ ] **Step 3: Commit**

```bash
git add market-watch/static/
git commit -m "feat(market-watch): LCARS green dashboard — 8-tab UI with charts"
```

---

### Task 15: Tab-Specific JavaScript (7 files)

**Files:**
- Create: `market-watch/static/js/dashboard.js`
- Create: `market-watch/static/js/watchlist.js`
- Create: `market-watch/static/js/portfolio.js`
- Create: `market-watch/static/js/analysis.js`
- Create: `market-watch/static/js/trading.js`
- Create: `market-watch/static/js/alerts.js`
- Create: `market-watch/static/js/backtest.js`

Each JS file handles data loading and rendering for its tab. The implementer should:

1. Use the `api.js` fetch wrapper from Task 14
2. Use `textContent` for all user-supplied values
3. Use DOM creation methods (createElement/appendChild) for structured content
4. Each file exports a `load{TabName}()` function called by `app.js` on tab switch
5. Follow the patterns established in Legal Watch / Civic Watch JS files

- [ ] **Step 1: Create all 7 JS files**

Each file follows this pattern:
```javascript
// dashboard.js
async function loadDashboard() {
    const summary = await api('/api/portfolio/summary');
    // Render portfolio value, P&L, cycle status
}
```

- [ ] **Step 2: Create charts.js with lightweight-charts**

```javascript
// charts.js
async function loadCharts(ticker) {
    const data = await api(`/api/charts/${ticker}`);
    // Render candlestick chart using LightweightCharts
}
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/static/js/
git commit -m "feat(market-watch): tab JS — dashboard, watchlist, portfolio, analysis, trading, charts, alerts, backtest"
```

---

### Task 16: Agent Loop Job + Docker Compose Integration

**Files:**
- Modify: `ai_bridge/agent_loop.py`
- Modify: `docker-compose.yml` (root)

- [ ] **Step 1: Add market watch cycle function to agent_loop.py**

Find `_run_dependabot_scan` and add nearby:

```python
def _run_market_watch_cycle(self):
    """Agent Loop Job: M.A.R.K.E.T. autonomous trading cycle."""
    try:
        import requests
        hub_url = "http://localhost:3000"

        # Trigger full cycle via Market Watch API
        resp = requests.post(
            "http://kytran_market_api:8080/api/analysis/cycle",
            timeout=600,
        )
        if resp.status_code == 200:
            data = resp.json()
            self._log_autonomy_action(
                action_type="market_watch_cycle",
                details={
                    "stocks_analyzed": data.get("stocks_analyzed", 0),
                    "trades": data.get("trades", 0),
                    "skipped": data.get("skipped", 0),
                    "failed": data.get("failed", 0),
                },
                success=True,
            )
            logger.info(
                "M.A.R.K.E.T. cycle: %d analyzed, %d traded, %d skipped",
                data.get("stocks_analyzed", 0),
                data.get("trades", 0),
                data.get("skipped", 0),
            )
        else:
            logger.error("M.A.R.K.E.T. cycle failed: HTTP %d", resp.status_code)
            self._log_autonomy_action(
                action_type="market_watch_cycle",
                details={"error": f"HTTP {resp.status_code}"},
                success=False,
            )
    except Exception as e:
        logger.error("M.A.R.K.E.T. cycle job failed: %s", e)
        self._log_autonomy_action(
            action_type="market_watch_cycle",
            details={"error": str(e)},
            success=False,
        )
```

- [ ] **Step 2: Register the job**

```python
self.scheduler.add_job(
    with_app_context(self._run_market_watch_cycle),
    trigger=IntervalTrigger(hours=4),
    id="market_watch_cycle",
    name="Agent Loop: M.A.R.K.E.T. Trading Cycle",
    replace_existing=True,
)
```

- [ ] **Step 3: Add to root docker-compose.yml**

Add the `kytran_market_api` service to the root `docker-compose.yml`:

```yaml
  kytran_market_api:
    build: ./market-watch
    container_name: kytran_market_api
    ports:
      - "8101:8080"
    volumes:
      - ./market-watch/data:/app/data
    environment:
      - ARCHIE_HUB_URL=http://192.168.1.200:3000
      - ALPACA_API_KEY=${ALPACA_API_KEY:-}
      - ALPACA_SECRET_KEY=${ALPACA_SECRET_KEY:-}
      - ALPACA_BASE_URL=https://paper-api.alpaca.markets
    read_only: true
    tmpfs:
      - /tmp
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M
    restart: unless-stopped
```

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/agent_loop.py docker-compose.yml
git commit -m "feat(market-watch): agent loop job + docker-compose integration"
```

---

### Task 17: Build, Deploy, and Verify

**Files:** None (deployment + testing)

- [ ] **Step 1: Build and start the container**

```bash
docker compose build kytran_market_api
docker compose up -d kytran_market_api
```

- [ ] **Step 2: Check container logs**

```bash
docker logs kytran_market_api --tail 20
```

Expected: Flask startup, DB init, no errors

- [ ] **Step 3: Verify health endpoint**

```bash
curl -s http://192.168.1.200:8101/api/health | python3 -m json.tool
```

Expected: `"status": "healthy", "service": "kytran-market-watch"`

- [ ] **Step 4: Test watchlist**

```bash
curl -s -X POST http://192.168.1.200:8101/api/watchlist -H "Content-Type: application/json" -d '{"ticker": "AAPL"}'
curl -s http://192.168.1.200:8101/api/watchlist | python3 -m json.tool
```

Expected: AAPL added with current price

- [ ] **Step 5: Test stock quote**

```bash
curl -s http://192.168.1.200:8101/api/stocks/AAPL | python3 -m json.tool
```

Expected: Current AAPL quote with price, change, volume

- [ ] **Step 6: Test chart data**

```bash
curl -s http://192.168.1.200:8101/api/charts/AAPL | python3 -m json.tool | head -20
```

Expected: OHLCV data array

- [ ] **Step 7: Browser test dashboard**

Navigate to `http://192.168.1.200:8101` and verify:
- LCARS green theme loads
- All 8 tabs switch correctly
- Watchlist shows AAPL with price
- Charts render candlesticks

- [ ] **Step 8: Restart platform for agent loop**

```bash
docker compose restart archie_platform
```

- [ ] **Step 9: Register in Code Health**

Add Market Watch to `STANDALONE_PRODUCTS` in `platform_v2/services/code_metrics_service.py`.

- [ ] **Step 10: Push**

```bash
git push
```

- [ ] **Step 11: Log in Dev HQ**

Use MCP:
- `log_decision` — Market Watch architecture (standalone, Bridge dispatch, Alpaca paper trading)
- `update_project_understanding` for project #198
- `complete_task` with verification notes
