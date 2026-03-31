# Market Watch Feature Gap Fill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Market Watch from a 4-role agent pipeline to W.A.T.C.H.-orchestrated 6-agent system with sentiment analysis, strategy management, and LCARS UI polish.

**Architecture:** Rewrite agent_pipeline.py to dispatch 6 named agents (Quant, Value, Pulse, Shield, Oracle, M.A.R.K.E.T.) via A.R.C.H.I.E. Bridge. Add sentiment and strategy services. Migrate SQLite schema for new agent report columns. Enhance existing LCARS UI to display 5-agent analysis reports.

**Tech Stack:** Flask, SQLite, yfinance, A.R.C.H.I.E. Bridge API, LCARS CSS

**Important context:** Market Watch already has RSI, SMA, MACD, Bollinger Bands in `market_data.py calculate_indicators()`. Already has 8 tabs in UI. The work is upgrading the agent pipeline and adding missing features, not rebuilding from scratch.

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `market-watch/services/sentiment.py` | News sentiment scoring per ticker |
| `market-watch/services/strategy_service.py` | Strategy CRUD + rules engine |
| `market-watch/routes/strategy_routes.py` | Strategy API endpoints |
| `market-watch/migrations/002_add_agents_and_strategies.sql` | Schema migration |

### Modified Files
| File | Change |
|------|--------|
| `market-watch/services/agent_pipeline.py` | Replace 4-role with W.A.T.C.H. 6-agent dispatch |
| `market-watch/routes/analysis_routes.py` | Update for 6-agent response format |
| `market-watch/routes/stock_routes.py` | Add sentiment endpoint |
| `market-watch/db.py` | Run new migration on startup |
| `market-watch/app.py` | Register strategy blueprint |
| `market-watch/schema.sql` | Add new tables + columns (canonical schema) |
| `market-watch/static/index.html` | LCARS polish + 6-agent analysis display + strategy tab |
| `market-watch/static/js/app.js` | Strategy tab JS + enhanced analysis display |
| `market-watch/static/css/style.css` | LCARS theme enhancements |

---

### Task 1: Schema Migration — New Agent Columns + Tables

**Files:**
- Create: `market-watch/migrations/002_add_agents_and_strategies.sql`
- Modify: `market-watch/schema.sql` (canonical schema)
- Modify: `market-watch/db.py` (run migration)

- [ ] **Step 1: Create the migration file**

Create `market-watch/migrations/002_add_agents_and_strategies.sql`:

```sql
-- 002: Add 6-agent analysis columns + strategy/sentiment tables

-- Expand analyses table for 6-agent reports
ALTER TABLE analyses ADD COLUMN value_report TEXT;
ALTER TABLE analyses ADD COLUMN value_score REAL;
ALTER TABLE analyses ADD COLUMN pulse_report TEXT;
ALTER TABLE analyses ADD COLUMN pulse_score REAL;
ALTER TABLE analyses ADD COLUMN oracle_synthesis TEXT;
ALTER TABLE analyses ADD COLUMN oracle_confidence REAL;
ALTER TABLE analyses ADD COLUMN market_execution TEXT;
ALTER TABLE analyses ADD COLUMN suggested_position_size REAL;
ALTER TABLE analyses ADD COLUMN stop_loss REAL;
ALTER TABLE analyses ADD COLUMN target_price REAL;

-- Strategies table
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    rules TEXT NOT NULL,  -- JSON: entry_conditions, exit_conditions, position_sizing
    is_active INTEGER DEFAULT 1,
    backtest_count INTEGER DEFAULT 0,
    last_backtest_id INTEGER,
    win_rate REAL,
    total_return REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sentiment scores
CREATE TABLE IF NOT EXISTS sentiment_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,  -- 'news', 'social', 'analyst'
    headline TEXT,
    score REAL NOT NULL,  -- -1.0 to 1.0
    summary TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sentiment_ticker ON sentiment_scores(ticker, created_at);

-- Agent dispatch log (track which agents ran and their timing)
CREATE TABLE IF NOT EXISTS agent_dispatch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER REFERENCES analyses(id),
    agent_name TEXT NOT NULL,
    agent_id INTEGER,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    status TEXT DEFAULT 'success',  -- success, failed, timeout
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 2: Update schema.sql with the new tables**

Read `market-watch/schema.sql` and append the new CREATE TABLE statements (strategies, sentiment_scores, agent_dispatch_log) and the new columns to the analyses CREATE TABLE definition. The migration file handles existing DBs; schema.sql is for fresh installs.

- [ ] **Step 3: Update db.py to run migrations**

Read `market-watch/db.py`. Add migration runner logic after the initial schema creation. The pattern:

```python
def _run_migrations(conn):
    """Run any pending SQL migrations from migrations/ directory."""
    import glob
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    if not os.path.exists(migrations_dir):
        return

    # Create migrations tracking table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    applied = {row[0] for row in conn.execute("SELECT filename FROM _migrations").fetchall()}

    for path in sorted(glob.glob(os.path.join(migrations_dir, "*.sql"))):
        filename = os.path.basename(path)
        if filename not in applied:
            with open(path) as f:
                sql = f.read()
            try:
                conn.executescript(sql)
                conn.execute("INSERT INTO _migrations (filename) VALUES (?)", (filename,))
                conn.commit()
                logger.info("Applied migration: %s", filename)
            except Exception as e:
                logger.warning("Migration %s failed (may be already applied): %s", filename, e)
```

Call `_run_migrations(conn)` after `init_db()` creates the base schema.

- [ ] **Step 4: Create the migrations directory**

```bash
mkdir -p /mnt/archie_brain/market-watch/migrations
```

- [ ] **Step 5: Test migration locally**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "
import db
conn = db.get_db()
# Check new columns exist
cursor = conn.execute('PRAGMA table_info(analyses)')
cols = [row[1] for row in cursor.fetchall()]
assert 'value_report' in cols, f'Missing value_report, cols: {cols}'
assert 'oracle_synthesis' in cols, f'Missing oracle_synthesis, cols: {cols}'
# Check new tables
tables = [row[0] for row in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
assert 'strategies' in tables, f'Missing strategies table'
assert 'sentiment_scores' in tables, f'Missing sentiment_scores table'
print('Migration OK — all columns and tables present')
"
```

- [ ] **Step 6: Commit**

```bash
git add market-watch/migrations/ market-watch/schema.sql market-watch/db.py
git commit -m "feat(market-watch): add 6-agent schema migration + strategies + sentiment tables"
```

---

### Task 2: Sentiment Service

**Files:**
- Create: `market-watch/services/sentiment.py`
- Modify: `market-watch/routes/stock_routes.py` (add endpoint)

- [ ] **Step 1: Create sentiment.py**

Create `market-watch/services/sentiment.py`:

```python
"""Sentiment analysis service — scores news headlines per ticker."""

import logging
import json
from datetime import datetime, timedelta

import yfinance as yf

from db import get_db

logger = logging.getLogger(__name__)


def fetch_and_score_news(ticker, limit=20):
    """
    Fetch recent news for a ticker via yfinance and score sentiment.

    Uses simple keyword-based scoring as a baseline.
    When dispatched through Bridge, Pulse agent provides LLM-based scoring.

    Returns list of dicts: headline, source, score (-1 to 1), url, published.
    """
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
    except Exception as e:
        logger.warning("Failed to fetch news for %s: %s", ticker, e)
        return []

    scored = []
    for item in news[:limit]:
        headline = item.get("title", "")
        url = item.get("link", "")
        source = item.get("publisher", "news")
        published = item.get("providerPublishTime", "")

        score = _keyword_score(headline)

        scored.append({
            "headline": headline,
            "source": source,
            "score": round(score, 2),
            "url": url,
            "published": published,
        })

        # Store in DB
        _store_score(ticker, source, headline, score, url)

    return scored


def _keyword_score(text):
    """Simple keyword-based sentiment scoring (-1 to 1)."""
    text_lower = text.lower()

    positive = ["surge", "soar", "beat", "upgrade", "bullish", "record", "growth",
                "profit", "gain", "rally", "boom", "strong", "outperform", "buy",
                "breakout", "dividend", "innovation", "partnership", "expansion"]
    negative = ["crash", "plunge", "miss", "downgrade", "bearish", "loss", "decline",
                "sell", "warning", "layoff", "debt", "lawsuit", "investigation",
                "recall", "bankruptcy", "fraud", "cut", "weak", "underperform"]

    pos_count = sum(1 for w in positive if w in text_lower)
    neg_count = sum(1 for w in negative if w in text_lower)
    total = pos_count + neg_count

    if total == 0:
        return 0.0
    return (pos_count - neg_count) / total


def _store_score(ticker, source, headline, score, url):
    """Store sentiment score in DB."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO sentiment_scores (ticker, source, headline, score, url) VALUES (?, ?, ?, ?, ?)",
            (ticker, source, headline, score, url),
        )
        conn.commit()
    except Exception as e:
        logger.debug("Failed to store sentiment: %s", e)


def get_sentiment_summary(ticker, days=7):
    """
    Get aggregate sentiment for a ticker over the last N days.

    Returns dict: avg_score, positive_count, negative_count, neutral_count, total, headlines.
    """
    conn = get_db()
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    rows = conn.execute(
        "SELECT headline, source, score, url, created_at FROM sentiment_scores "
        "WHERE ticker = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 50",
        (ticker, cutoff),
    ).fetchall()

    if not rows:
        # Try fetching fresh news
        fetch_and_score_news(ticker)
        rows = conn.execute(
            "SELECT headline, source, score, url, created_at FROM sentiment_scores "
            "WHERE ticker = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 50",
            (ticker, cutoff),
        ).fetchall()

    scores = [r[2] for r in rows]
    avg = sum(scores) / len(scores) if scores else 0.0

    return {
        "ticker": ticker,
        "avg_score": round(avg, 2),
        "positive_count": sum(1 for s in scores if s > 0.1),
        "negative_count": sum(1 for s in scores if s < -0.1),
        "neutral_count": sum(1 for s in scores if -0.1 <= s <= 0.1),
        "total": len(scores),
        "headlines": [
            {"headline": r[0], "source": r[1], "score": r[2], "url": r[3], "date": r[4]}
            for r in rows[:10]
        ],
    }
```

- [ ] **Step 2: Add sentiment endpoint to stock_routes.py**

Read `market-watch/routes/stock_routes.py`. Add after existing routes:

```python
@bp.route("/api/stocks/<ticker>/sentiment")
def get_sentiment(ticker):
    from services.sentiment import get_sentiment_summary
    result = get_sentiment_summary(ticker.upper())
    return jsonify(result)
```

- [ ] **Step 3: Test**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "
from services.sentiment import fetch_and_score_news, get_sentiment_summary
news = fetch_and_score_news('AAPL', limit=5)
print(f'Fetched {len(news)} headlines')
for n in news[:3]:
    print(f'  {n[\"score\"]:+.2f} | {n[\"headline\"][:60]}')
summary = get_sentiment_summary('AAPL')
print(f'Avg sentiment: {summary[\"avg_score\"]:+.2f} ({summary[\"total\"]} headlines)')
"
```

- [ ] **Step 4: Commit**

```bash
git add market-watch/services/sentiment.py market-watch/routes/stock_routes.py
git commit -m "feat(market-watch): add sentiment service — news scoring + /api/stocks/<ticker>/sentiment"
```

---

### Task 3: Strategy Service + Routes

**Files:**
- Create: `market-watch/services/strategy_service.py`
- Create: `market-watch/routes/strategy_routes.py`
- Modify: `market-watch/app.py` (register blueprint)

- [ ] **Step 1: Create strategy_service.py**

Create `market-watch/services/strategy_service.py`:

```python
"""Strategy management — CRUD for named trading strategies with rules."""

import json
import logging
from datetime import datetime

from db import get_db

logger = logging.getLogger(__name__)


def get_strategies(active_only=False):
    """Return all strategies, optionally filtered to active only."""
    conn = get_db()
    sql = "SELECT * FROM strategies"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_strategy(strategy_id):
    """Return a single strategy by ID."""
    conn = get_db()
    row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    return _row_to_dict(row) if row else None


def create_strategy(name, rules, description=""):
    """Create a new strategy. Rules should be a dict with entry/exit conditions."""
    conn = get_db()
    rules_json = json.dumps(rules) if isinstance(rules, dict) else rules
    conn.execute(
        "INSERT INTO strategies (name, description, rules) VALUES (?, ?, ?)",
        (name, description, rules_json),
    )
    conn.commit()
    return get_strategies()[-1] if get_strategies() else None


def update_strategy(strategy_id, **kwargs):
    """Update strategy fields."""
    allowed = {"name", "description", "rules", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return None
    if "rules" in fields and isinstance(fields["rules"], dict):
        fields["rules"] = json.dumps(fields["rules"])
    fields["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [strategy_id]
    conn = get_db()
    conn.execute(f"UPDATE strategies SET {set_clause} WHERE id = ?", values)
    conn.commit()
    return get_strategy(strategy_id)


def delete_strategy(strategy_id):
    """Delete a strategy."""
    conn = get_db()
    conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
    conn.commit()


def _row_to_dict(row):
    """Convert sqlite3.Row to dict with parsed rules JSON."""
    if row is None:
        return None
    d = dict(row)
    if "rules" in d and isinstance(d["rules"], str):
        try:
            d["rules"] = json.loads(d["rules"])
        except (json.JSONDecodeError, TypeError):
            pass
    return d
```

- [ ] **Step 2: Create strategy_routes.py**

Create `market-watch/routes/strategy_routes.py`:

```python
"""Strategy management API routes."""

from flask import Blueprint, jsonify, request

from services.strategy_service import (
    get_strategies,
    get_strategy,
    create_strategy,
    update_strategy,
    delete_strategy,
)

bp = Blueprint("strategies", __name__)


@bp.route("/api/strategies")
def list_strategies():
    active_only = request.args.get("active") == "true"
    return jsonify(get_strategies(active_only=active_only))


@bp.route("/api/strategies/<int:sid>")
def get_one(sid):
    s = get_strategy(sid)
    if not s:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify(s)


@bp.route("/api/strategies", methods=["POST"])
def create():
    data = request.get_json() or {}
    name = data.get("name")
    rules = data.get("rules", {})
    description = data.get("description", "")
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not rules:
        return jsonify({"error": "rules is required"}), 400
    s = create_strategy(name, rules, description)
    return jsonify(s), 201


@bp.route("/api/strategies/<int:sid>", methods=["PUT"])
def update(sid):
    data = request.get_json() or {}
    s = update_strategy(sid, **data)
    if not s:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify(s)


@bp.route("/api/strategies/<int:sid>", methods=["DELETE"])
def delete(sid):
    delete_strategy(sid)
    return jsonify({"success": True})
```

- [ ] **Step 3: Register blueprint in app.py**

Read `market-watch/app.py`. Add alongside existing blueprint imports:

```python
from routes.strategy_routes import bp as strategy_bp
app.register_blueprint(strategy_bp)
```

- [ ] **Step 4: Commit**

```bash
git add market-watch/services/strategy_service.py market-watch/routes/strategy_routes.py market-watch/app.py
git commit -m "feat(market-watch): add strategy service — CRUD + /api/strategies endpoints"
```

---

### Task 4: Upgrade Agent Pipeline — W.A.T.C.H. + 6 Agents

**Files:**
- Modify: `market-watch/services/agent_pipeline.py` (full rewrite)

This is the core task. Replace the 4-role Director/Quant/Risk/Execute pipeline with W.A.T.C.H. orchestrating 6 named agents.

- [ ] **Step 1: Read the current agent_pipeline.py**

Read the full file to understand the Bridge dispatch pattern, circuit breakers, and how results are stored.

- [ ] **Step 2: Rewrite agent_pipeline.py**

Keep the same Bridge dispatch mechanism and circuit breakers. Replace the role functions with named agent dispatches. The new pipeline:

```python
"""
W.A.T.C.H. Agent Pipeline — 6-agent market analysis + execution
================================================================
W.A.T.C.H. (#152) orchestrates:
  Quant (#39)   — technical analysis (RSI, MACD, SMA, volume)
  Value (#40)   — fundamental analysis (P/E, earnings, margins)
  Pulse (#30)   — market sentiment (news, social, sector)
  Shield (#42)  — risk management (position sizing, stop-loss)
  Oracle (#43)  — synthesis + recommendation (buy/sell/hold)
  M.A.R.K.E.T. (#32) — execution (paper trades via Alpaca)
"""

import json
import logging
import os
import time
from datetime import datetime

import requests

from db import get_db

logger = logging.getLogger(__name__)

BRIDGE_URL = os.getenv("ARCHIE_HUB_URL", "http://192.168.1.200:3000")
BRIDGE_DISPATCH = f"{BRIDGE_URL}/api/bridge/dispatch"

# Circuit breakers
MAX_TRADES_PER_DAY = 10
MAX_PORTFOLIO_EXPOSURE = 0.8
MAX_SINGLE_POSITION = 0.2
MAX_CONSECUTIVE_LOSSES = 5
MAX_DAILY_LOSS_PCT = 5.0

# Agent definitions
AGENTS = {
    "quant": {"id": 39, "name": "Quant", "display": "Raj Mehta (Quant)"},
    "value": {"id": 40, "name": "Value", "display": "Diego Castillo (Value)"},
    "pulse": {"id": 30, "name": "Pulse", "display": "Alexei Ivanovich (Pulse)"},
    "shield": {"id": 42, "name": "Shield", "display": "Suki Taniguchi (Shield)"},
    "oracle": {"id": 43, "name": "Oracle", "display": "Olivia Oduya (Oracle)"},
    "market": {"id": 32, "name": "MARKET", "display": "M.A.R.K.E.T."},
}


def run_pipeline(ticker, market_data=None, news_data=None):
    """
    Run the full W.A.T.C.H. analysis pipeline for a ticker.

    1. Quant — technical analysis
    2. Value — fundamental analysis
    3. Pulse — sentiment analysis
    4. Shield — risk assessment
    5. Oracle — synthesis + recommendation
    6. M.A.R.K.E.T. — execution (if recommendation is buy/sell)

    Returns analysis dict with all agent reports.
    """
    conn = get_db()
    start_time = time.time()

    # Create analysis record
    conn.execute(
        "INSERT INTO analyses (ticker, created_at) VALUES (?, ?)",
        (ticker, datetime.utcnow().isoformat()),
    )
    conn.commit()
    analysis_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Gather context
    if market_data is None:
        from services.market_data import get_quote, get_history, get_fundamentals, calculate_indicators
        market_data = {
            "quote": get_quote(ticker),
            "history": get_history(ticker, period="3mo"),
            "fundamentals": get_fundamentals(ticker),
            "indicators": calculate_indicators(ticker),
        }

    if news_data is None:
        from services.sentiment import fetch_and_score_news, get_sentiment_summary
        news_data = {
            "headlines": fetch_and_score_news(ticker, limit=10),
            "summary": get_sentiment_summary(ticker),
        }

    context = {"ticker": ticker, "market_data": market_data, "news": news_data}

    # Run agents sequentially
    quant_result = _dispatch_agent("quant", context, analysis_id,
        "Analyze the technical indicators for {ticker}. Review RSI, MACD, SMA crossovers, Bollinger Band position, and volume patterns. Provide a technical score (1-10) and outlook.")

    value_result = _dispatch_agent("value", context, analysis_id,
        "Analyze the fundamentals for {ticker}. Review P/E ratio, earnings growth, revenue trends, margins, and debt levels. Provide a value score (1-10) and assessment.")

    pulse_result = _dispatch_agent("pulse", context, analysis_id,
        "Analyze market sentiment for {ticker}. Review recent news headlines, sentiment scores, sector momentum, and social buzz. Provide a sentiment score (1-10) and mood assessment.")

    # Shield gets all previous reports for risk context
    shield_context = dict(context)
    shield_context["prior_reports"] = {
        "quant": quant_result, "value": value_result, "pulse": pulse_result,
    }
    shield_result = _dispatch_agent("shield", shield_context, analysis_id,
        "Assess risk for a potential {ticker} position. Review the technical, fundamental, and sentiment reports. Recommend position sizing (0-20% of portfolio), stop-loss level, and risk rating.")

    # Oracle gets everything
    oracle_context = dict(context)
    oracle_context["all_reports"] = {
        "quant": quant_result, "value": value_result,
        "pulse": pulse_result, "shield": shield_result,
    }
    oracle_result = _dispatch_agent("oracle", oracle_context, analysis_id,
        "Synthesize all analysis for {ticker}. You have technical (Quant), fundamental (Value), sentiment (Pulse), and risk (Shield) reports. Provide a final recommendation (buy/sell/hold), confidence score (0-1), target price, and synthesis.")

    # Store results
    recommendation = "hold"
    confidence = 0.0
    if oracle_result:
        recommendation = oracle_result.get("recommendation", "hold")
        confidence = oracle_result.get("confidence", 0.0)

    conn.execute("""
        UPDATE analyses SET
            quant_report = ?, quant_score = ?,
            value_report = ?, value_score = ?,
            pulse_report = ?, pulse_score = ?,
            risk_assessment = ?, risk_approved = ?,
            oracle_synthesis = ?, oracle_confidence = ?,
            recommendation = ?,
            suggested_position_size = ?, stop_loss = ?, target_price = ?,
            director_thesis = ?, director_sentiment = ?
        WHERE id = ?
    """, (
        json.dumps(quant_result) if quant_result else None,
        quant_result.get("score") if quant_result else None,
        json.dumps(value_result) if value_result else None,
        value_result.get("score") if value_result else None,
        json.dumps(pulse_result) if pulse_result else None,
        pulse_result.get("score") if pulse_result else None,
        json.dumps(shield_result) if shield_result else None,
        1 if shield_result and shield_result.get("approved", True) else 0,
        json.dumps(oracle_result) if oracle_result else None,
        confidence,
        recommendation,
        shield_result.get("position_size", 0) if shield_result else 0,
        shield_result.get("stop_loss") if shield_result else None,
        oracle_result.get("target_price") if oracle_result else None,
        oracle_result.get("synthesis", "") if oracle_result else "",
        oracle_result.get("sentiment", "neutral") if oracle_result else "neutral",
        analysis_id,
    ))
    conn.commit()

    # M.A.R.K.E.T. executes if recommendation is buy or sell
    execution_result = None
    if recommendation in ("buy", "sell") and confidence >= 0.6:
        if _check_circuit_breakers(ticker, recommendation):
            market_context = dict(context)
            market_context["recommendation"] = recommendation
            market_context["confidence"] = confidence
            market_context["position_size"] = shield_result.get("position_size", 0.05) if shield_result else 0.05
            market_context["stop_loss"] = shield_result.get("stop_loss") if shield_result else None
            execution_result = _dispatch_agent("market", market_context, analysis_id,
                "Execute a {recommendation} order for {ticker}. Position size: {position_size:.1%} of portfolio. Stop-loss: {stop_loss}. Confidence: {confidence:.0%}. This is PAPER TRADING only.")

            conn.execute(
                "UPDATE analyses SET market_execution = ?, executed = 1 WHERE id = ?",
                (json.dumps(execution_result) if execution_result else None, analysis_id),
            )
            conn.commit()

    elapsed = time.time() - start_time
    logger.info("Pipeline complete for %s in %.1fs — recommendation: %s (%.0f%%)",
                ticker, elapsed, recommendation, confidence * 100)

    return {
        "analysis_id": analysis_id,
        "ticker": ticker,
        "quant": quant_result,
        "value": value_result,
        "pulse": pulse_result,
        "shield": shield_result,
        "oracle": oracle_result,
        "execution": execution_result,
        "recommendation": recommendation,
        "confidence": confidence,
        "elapsed_seconds": round(elapsed, 1),
    }


def _dispatch_agent(agent_key, context, analysis_id, prompt_template):
    """Dispatch a single agent via A.R.C.H.I.E. Bridge."""
    agent = AGENTS[agent_key]
    ticker = context.get("ticker", "")

    # Format prompt with context values
    prompt = prompt_template.format(
        ticker=ticker,
        recommendation=context.get("recommendation", ""),
        confidence=context.get("confidence", 0),
        position_size=context.get("position_size", 0),
        stop_loss=context.get("stop_loss", "N/A"),
    )

    # Build full prompt with data context
    full_prompt = f"{prompt}\n\nMarket Data:\n```json\n{json.dumps(context.get('market_data', {}), indent=2, default=str)[:3000]}\n```"

    if context.get("news"):
        news_summary = context["news"].get("summary", {})
        full_prompt += f"\n\nSentiment: avg={news_summary.get('avg_score', 'N/A')}, headlines={news_summary.get('total', 0)}"

    if context.get("prior_reports"):
        full_prompt += f"\n\nPrior Reports:\n```json\n{json.dumps(context['prior_reports'], indent=2, default=str)[:2000]}\n```"

    if context.get("all_reports"):
        full_prompt += f"\n\nAll Reports:\n```json\n{json.dumps(context['all_reports'], indent=2, default=str)[:3000]}\n```"

    start = time.time()
    try:
        resp = requests.post(
            BRIDGE_DISPATCH,
            json={
                "prompt": full_prompt,
                "agent_name": agent["name"],
                "agent_id": agent["id"],
                "response_format": "json",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("response") or data.get("result") or data

        # Try to parse as JSON if string
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                result = {"text": result, "score": 5.0}

        duration = int((time.time() - start) * 1000)
        _log_dispatch(analysis_id, agent["name"], agent["id"], duration, "success")

        return result

    except Exception as e:
        duration = int((time.time() - start) * 1000)
        logger.error("Agent %s dispatch failed: %s", agent["name"], e)
        _log_dispatch(analysis_id, agent["name"], agent["id"], duration, "failed")
        return {"error": str(e), "score": 0}


def _log_dispatch(analysis_id, agent_name, agent_id, duration_ms, status):
    """Log agent dispatch to agent_dispatch_log table."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO agent_dispatch_log (analysis_id, agent_name, agent_id, duration_ms, status) VALUES (?, ?, ?, ?, ?)",
            (analysis_id, agent_name, agent_id, duration_ms, status),
        )
        conn.commit()
    except Exception as e:
        logger.debug("Failed to log dispatch: %s", e)


def _check_circuit_breakers(ticker, action):
    """Check if trade is allowed by circuit breaker rules."""
    conn = get_db()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Max trades per day
    day_trades = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE date(executed_at) = ?", (today,)
    ).fetchone()[0]
    if day_trades >= MAX_TRADES_PER_DAY:
        logger.warning("Circuit breaker: max trades/day (%d)", MAX_TRADES_PER_DAY)
        return False

    # Max portfolio exposure
    account = conn.execute("SELECT cash_balance, initial_balance FROM paper_account LIMIT 1").fetchone()
    if account:
        cash = account[0]
        initial = account[1]
        exposure = 1.0 - (cash / initial) if initial > 0 else 0
        if exposure >= MAX_PORTFOLIO_EXPOSURE:
            logger.warning("Circuit breaker: max exposure (%.0f%%)", exposure * 100)
            return False

    return True
```

- [ ] **Step 3: Commit**

```bash
git add market-watch/services/agent_pipeline.py
git commit -m "feat(market-watch): upgrade to W.A.T.C.H. 6-agent pipeline — Quant/Value/Pulse/Shield/Oracle/M.A.R.K.E.T."
```

---

### Task 5: Update Analysis Routes

**Files:**
- Modify: `market-watch/routes/analysis_routes.py`

- [ ] **Step 1: Read analysis_routes.py**

Read the full file to understand the current route structure.

- [ ] **Step 2: Update the run analysis route**

Update the route that triggers analysis to use the new pipeline and return the expanded 6-agent format. The main route should:

1. Accept `POST /api/analysis/run` with `{"ticker": "AAPL"}`
2. Call `run_pipeline(ticker)` from the updated agent_pipeline
3. Return the full result including all 6 agent reports

Also update `GET /api/analysis/<id>` to return the new columns (value_report, pulse_report, oracle_synthesis, etc.).

And update `GET /api/analysis` (list) to include the new fields in the response.

- [ ] **Step 3: Commit**

```bash
git add market-watch/routes/analysis_routes.py
git commit -m "feat(market-watch): update analysis routes for 6-agent response format"
```

---

### Task 6: LCARS Theme Polish

**Files:**
- Modify: `market-watch/static/css/style.css`
- Modify: `market-watch/static/index.html`

- [ ] **Step 1: Read current CSS and HTML**

Read both files to understand current styling and structure.

- [ ] **Step 2: Enhance CSS with LCARS elements**

Add to style.css:
- Import Orbitron + IBM Plex Mono fonts
- LCARS elbow corners on main panels (use border-radius + pseudo-elements)
- Cyan (#00e5ff) as primary accent
- Dark background (#0a0a1a)
- Station-colored section accents (match A.R.C.H.I.E. dashboard)
- Agent report cards with color-coded borders per agent
- Responsive breakpoints (480/768/1024px)

Key classes to add:
```css
.lcars-panel { border: 1px solid rgba(0,229,255,0.2); border-radius: 0 16px 0 16px; background: rgba(0,0,0,0.3); }
.lcars-header { font-family: 'Orbitron', monospace; color: #00e5ff; }
.agent-card { border-left: 3px solid var(--agent-color); padding: 1rem; margin: 0.5rem 0; }
.agent-card.quant { --agent-color: #fbbf24; }
.agent-card.value { --agent-color: #8b5cf6; }
.agent-card.pulse { --agent-color: #f472b6; }
.agent-card.shield { --agent-color: #ef4444; }
.agent-card.oracle { --agent-color: #10b981; }
.agent-card.market { --agent-color: #00e5ff; }
```

- [ ] **Step 3: Update HTML for analysis display**

In the analysis tab section of index.html, update the analysis results display to show 6 agent report cards:
- Each agent gets a color-coded card
- Card shows: agent name + persona, score (if applicable), report text
- Oracle card is larger/prominent with recommendation badge
- M.A.R.K.E.T. card shows execution status

- [ ] **Step 4: Add strategy tab content to HTML**

Add a Strategies section/tab in index.html with:
- Strategy list (name, description, active status, win rate)
- Create strategy form (name, description, rules JSON editor)
- Edit/delete buttons
- Link to backtest

- [ ] **Step 5: Update app.js for strategy tab**

Add strategy tab loading in app.js:
- `loadStrategies()` — fetch /api/strategies, render list
- `createStrategy()` — POST /api/strategies
- `deleteStrategy(id)` — DELETE /api/strategies/:id
- `toggleStrategy(id)` — PUT /api/strategies/:id with is_active toggle

- [ ] **Step 6: Commit**

```bash
git add market-watch/static/
git commit -m "feat(market-watch): LCARS theme polish + 6-agent analysis cards + strategy tab"
```

---

### Task 7: Deploy and Verify

- [ ] **Step 1: Rebuild and restart Market Watch container**

```bash
cd /mnt/archie_brain/market-watch
docker compose down
docker compose up -d --build
```

- [ ] **Step 2: Check logs for errors**

```bash
docker logs --tail 30 kytran_market_api 2>&1 | grep -iE "error|migration|traceback"
```

Expected: Migration applied, no errors.

- [ ] **Step 3: Test schema migration**

```bash
docker exec kytran_market_api python3 -c "
from db import get_db
conn = get_db()
cols = [r[1] for r in conn.execute('PRAGMA table_info(analyses)').fetchall()]
print('analyses columns:', cols)
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print('tables:', tables)
assert 'oracle_synthesis' in cols
assert 'strategies' in tables
assert 'sentiment_scores' in tables
print('Schema OK')
"
```

- [ ] **Step 4: Test sentiment API**

```bash
curl -s http://192.168.1.200:8101/api/stocks/AAPL/sentiment | python3 -m json.tool | head -20
```

Expected: JSON with avg_score, headline list.

- [ ] **Step 5: Test strategy API**

```bash
# Create
curl -s -X POST http://192.168.1.200:8101/api/strategies \
  -H "Content-Type: application/json" \
  -d '{"name":"RSI Oversold Bounce","description":"Buy when RSI<30, sell when RSI>70","rules":{"entry":"rsi < 30","exit":"rsi > 70","position_size":0.05}}'

# List
curl -s http://192.168.1.200:8101/api/strategies | python3 -m json.tool
```

- [ ] **Step 6: Browser test**

Open `http://192.168.1.200:8101` (or market.kytranempowerment.com):
- LCARS theme visible (dark, cyan accents, Orbitron headers)
- All 8 tabs work
- Strategies tab shows created strategy
- Analysis tab shows 6-agent report layout (empty until analysis is run)

- [ ] **Step 7: Test analysis pipeline (if Bridge is accessible)**

```bash
curl -s -X POST http://192.168.1.200:8101/api/analysis/run \
  -H "Content-Type: application/json" \
  -d '{"ticker":"AAPL"}' | python3 -m json.tool | head -30
```

Note: This requires A.R.C.H.I.E. Bridge to be reachable from the Market Watch container. If it fails, check ARCHIE_HUB_URL env var in docker-compose.yml.

- [ ] **Step 8: Final commit**

```bash
git add -A
git commit -m "feat(market-watch): Sub-project 1 complete — 6-agent pipeline, sentiment, strategies, LCARS"
```
