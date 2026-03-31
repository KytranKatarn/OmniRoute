# Market Watch — Phase B4: Advanced Risk/Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kelly criterion dynamic sizing, portfolio VaR, correlation-adjusted sizing, sector beta, and a risk grading system with admin/viewer/public exposure.

**Architecture:** New `quant_service.py` handles all calculations with caching in `risk_metrics` table. Execution engine uses Kelly + correlation for sizing. New `routes/risk.py` exposes metrics at three visibility levels.

**Tech Stack:** Flask 3.1, numpy (for correlation/VaR calculations), yfinance, SQLite

**Spec:** `docs/superpowers/specs/2026-03-31-market-watch-phase-b4-quant-risk-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/quant_service.py` | Kelly, VaR, correlations, beta, diversification, risk grade |
| Create | `routes/risk.py` | 4 risk API endpoints (admin + viewer + public) |
| Modify | `services/execution_engine.py` | Kelly sizing + correlation adjustment + beta gate |
| Modify | `schema.sql` | Add risk_metrics table |
| Modify | `requirements.txt` | Add numpy |
| Modify | `static/index.html` | Admin risk panel + viewer risk summary |
| Modify | `templates/landing.html` | Public risk grade badge |
| Modify | `app.py` | Register risk blueprint |
| Modify | `docker-compose.yml` | Quant env vars |
| Modify | `.env.example` | Document quant env vars |

---

### Task 1: Schema + numpy Dependency

**Files:**
- Modify: `schema.sql`
- Modify: `requirements.txt`

- [ ] **Step 1: Add risk_metrics table to schema.sql**

Append to end of `/mnt/archie_brain/market-watch/schema.sql`:

```sql
-- Risk metrics cache (VaR, correlations, beta, Kelly params)
CREATE TABLE IF NOT EXISTS risk_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_type TEXT NOT NULL,
    ticker TEXT,
    data JSON NOT NULL,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(metric_type, ticker)
);
```

- [ ] **Step 2: Add numpy to requirements.txt**

Add to `/mnt/archie_brain/market-watch/requirements.txt`:

```
numpy==2.2.4
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/schema.sql market-watch/requirements.txt
git commit -m "feat(quant): add risk_metrics table and numpy dependency"
```

---

### Task 2: Quant Service — Kelly, VaR, Correlations, Beta, Grade

**Files:**
- Create: `services/quant_service.py`

- [ ] **Step 1: Create quant_service.py**

Create `/mnt/archie_brain/market-watch/services/quant_service.py`:

```python
"""Quant service — Kelly criterion, VaR, correlations, beta, risk grading."""

import json
import logging
import os
from datetime import datetime, timedelta

import numpy as np
import yfinance as yf

from db import get_db

logger = logging.getLogger(__name__)

# Config
KELLY_ENABLED = os.environ.get("MW_KELLY_ENABLED", "true").lower() in ("true", "1")
KELLY_FRACTION = float(os.environ.get("MW_KELLY_FRACTION", 0.5))
KELLY_MIN_TRADES = int(os.environ.get("MW_KELLY_MIN_TRADES", 10))
MAX_PORTFOLIO_BETA = float(os.environ.get("MW_MAX_PORTFOLIO_BETA", 1.5))
CORRELATION_THRESHOLD = float(os.environ.get("MW_CORRELATION_THRESHOLD", 0.7))
RISK_METRICS_TTL_DAYS = int(os.environ.get("MW_RISK_METRICS_TTL_DAYS", 7))


def _get_cached_metric(metric_type, ticker=None):
    """Return cached metric if not expired, else None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT data, expires_at FROM risk_metrics WHERE metric_type = ? AND ticker IS ?",
            (metric_type, ticker),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] and datetime.utcnow() > datetime.fromisoformat(str(row["expires_at"])):
            return None
        data = row["data"]
        return json.loads(data) if isinstance(data, str) else data
    finally:
        conn.close()


def _cache_metric(metric_type, data, ticker=None):
    """Cache a metric with TTL."""
    expires = (datetime.utcnow() + timedelta(days=RISK_METRICS_TTL_DAYS)).isoformat()
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO risk_metrics (metric_type, ticker, data, calculated_at, expires_at)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
               ON CONFLICT(metric_type, ticker) DO UPDATE SET
                   data = excluded.data, calculated_at = CURRENT_TIMESTAMP, expires_at = excluded.expires_at""",
            (metric_type, ticker, json.dumps(data), expires),
        )
        conn.commit()
    finally:
        conn.close()


def _get_daily_returns(ticker, days=252):
    """Fetch daily returns from yfinance."""
    try:
        data = yf.Ticker(ticker).history(period=f"{days}d")
        if data.empty or len(data) < 20:
            return np.array([])
        returns = data["Close"].pct_change().dropna().values
        return returns
    except Exception as e:
        logger.warning("Failed to get returns for %s: %s", ticker, e)
        return np.array([])


# --- Kelly Criterion ---

def calculate_kelly_fraction():
    """Calculate Kelly fraction from trade history.

    Returns dict: {kelly_full, kelly_half, win_rate, avg_win, avg_loss, ratio, sufficient_data}
    """
    cached = _get_cached_metric("kelly_params")
    if cached:
        return cached

    conn = get_db()
    try:
        trades = conn.execute(
            "SELECT pnl, pnl_pct FROM trade_journal WHERE action = 'sell' AND pnl IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    if len(trades) < KELLY_MIN_TRADES:
        result = {
            "kelly_full": 0.0, "kelly_half": 0.0,
            "win_rate": 0.0, "avg_win": 0.0, "avg_loss": 0.0, "ratio": 0.0,
            "sufficient_data": False, "trade_count": len(trades),
        }
        return result

    wins = [t["pnl_pct"] for t in trades if t["pnl"] > 0]
    losses = [abs(t["pnl_pct"]) for t in trades if t["pnl"] <= 0]

    win_rate = len(wins) / len(trades) if trades else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 1

    ratio = avg_win / avg_loss if avg_loss > 0 else 0
    kelly_full = (win_rate - ((1 - win_rate) / ratio)) if ratio > 0 else 0
    kelly_full = max(0, min(kelly_full, 1.0))
    kelly_half = kelly_full * KELLY_FRACTION

    result = {
        "kelly_full": round(kelly_full, 4),
        "kelly_half": round(kelly_half, 4),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "ratio": round(ratio, 2),
        "sufficient_data": True,
        "trade_count": len(trades),
    }
    _cache_metric("kelly_params", result)
    return result


def get_kelly_position_size(portfolio_value, max_position_pct):
    """Return position size using Kelly criterion.

    Falls back to equal-weight if insufficient trade data.
    """
    if not KELLY_ENABLED:
        return None  # Caller uses default sizing

    kelly = calculate_kelly_fraction()
    if not kelly["sufficient_data"]:
        return None

    kelly_size = portfolio_value * kelly["kelly_half"]
    max_size = portfolio_value * (max_position_pct / 100)
    return min(kelly_size, max_size)


# --- Value at Risk ---

def calculate_var(confidence=0.95, lookback_days=252):
    """Calculate portfolio VaR from historical daily returns.

    Returns dict: {var_95_pct, var_95_dollar, var_99_pct, var_99_dollar, portfolio_volatility, positions_used}
    """
    cached = _get_cached_metric("var_portfolio")
    if cached:
        return cached

    conn = get_db()
    try:
        positions = conn.execute(
            "SELECT ticker, quantity, entry_price FROM open_positions WHERE status = 'open'"
        ).fetchall()
    finally:
        conn.close()

    if not positions:
        result = {
            "var_95_pct": 0.0, "var_95_dollar": 0.0,
            "var_99_pct": 0.0, "var_99_dollar": 0.0,
            "portfolio_volatility": 0.0, "positions_used": 0,
        }
        return result

    # Get portfolio value
    total_value = sum(p["quantity"] * p["entry_price"] for p in positions)
    if total_value <= 0:
        return {"var_95_pct": 0.0, "var_95_dollar": 0.0, "var_99_pct": 0.0, "var_99_dollar": 0.0, "portfolio_volatility": 0.0, "positions_used": 0}

    # Calculate weighted portfolio returns
    all_returns = []
    weights = []
    for pos in positions:
        returns = _get_daily_returns(pos["ticker"], lookback_days)
        if len(returns) > 0:
            pos_value = pos["quantity"] * pos["entry_price"]
            all_returns.append(returns)
            weights.append(pos_value / total_value)

    if not all_returns:
        return {"var_95_pct": 0.0, "var_95_dollar": 0.0, "var_99_pct": 0.0, "var_99_dollar": 0.0, "portfolio_volatility": 0.0, "positions_used": 0}

    # Align return lengths
    min_len = min(len(r) for r in all_returns)
    aligned = np.array([r[-min_len:] for r in all_returns])
    weights_arr = np.array(weights)

    # Portfolio returns = weighted sum
    portfolio_returns = np.dot(weights_arr, aligned)

    var_95 = float(np.percentile(portfolio_returns, 5))
    var_99 = float(np.percentile(portfolio_returns, 1))
    volatility = float(np.std(portfolio_returns) * np.sqrt(252))

    result = {
        "var_95_pct": round(var_95 * 100, 2),
        "var_95_dollar": round(var_95 * total_value, 2),
        "var_99_pct": round(var_99 * 100, 2),
        "var_99_dollar": round(var_99 * total_value, 2),
        "portfolio_volatility": round(volatility * 100, 2),
        "positions_used": len(all_returns),
    }
    _cache_metric("var_portfolio", result)
    return result


# --- Correlations ---

def calculate_correlations(tickers=None, lookback_days=90):
    """Calculate pairwise correlation matrix for given tickers.

    Returns dict: {matrix: {ticker: {ticker: corr}}, avg_correlation, tickers}
    """
    if not tickers:
        conn = get_db()
        try:
            rows = conn.execute("SELECT DISTINCT ticker FROM open_positions WHERE status = 'open'").fetchall()
            tickers = [r["ticker"] for r in rows]
        finally:
            conn.close()

    if len(tickers) < 2:
        return {"matrix": {}, "avg_correlation": 0.0, "tickers": tickers}

    cached = _get_cached_metric("correlations")
    if cached and set(cached.get("tickers", [])) == set(tickers):
        return cached

    returns_map = {}
    for t in tickers:
        r = _get_daily_returns(t, lookback_days)
        if len(r) > 0:
            returns_map[t] = r

    valid_tickers = list(returns_map.keys())
    if len(valid_tickers) < 2:
        return {"matrix": {}, "avg_correlation": 0.0, "tickers": valid_tickers}

    min_len = min(len(returns_map[t]) for t in valid_tickers)
    aligned = np.array([returns_map[t][-min_len:] for t in valid_tickers])

    corr_matrix = np.corrcoef(aligned)

    matrix = {}
    pair_corrs = []
    for i, t1 in enumerate(valid_tickers):
        matrix[t1] = {}
        for j, t2 in enumerate(valid_tickers):
            corr_val = round(float(corr_matrix[i][j]), 4)
            matrix[t1][t2] = corr_val
            if i < j:
                pair_corrs.append(corr_val)

    avg_corr = round(sum(pair_corrs) / len(pair_corrs), 4) if pair_corrs else 0.0

    result = {"matrix": matrix, "avg_correlation": avg_corr, "tickers": valid_tickers}
    _cache_metric("correlations", result)
    return result


def calculate_diversification_score():
    """Calculate portfolio diversification score 0-100."""
    corr_data = calculate_correlations()
    avg_corr = corr_data.get("avg_correlation", 0)
    score = round((1 - abs(avg_corr)) * 100, 1)
    return max(0, min(100, score))


def get_correlation_for_ticker(ticker):
    """Check if a ticker is highly correlated with any open position.

    Returns (is_correlated: bool, max_correlation: float, correlated_with: str)
    """
    conn = get_db()
    try:
        rows = conn.execute("SELECT DISTINCT ticker FROM open_positions WHERE status = 'open'").fetchall()
        open_tickers = [r["ticker"] for r in rows]
    finally:
        conn.close()

    if not open_tickers:
        return False, 0.0, None

    for open_t in open_tickers:
        try:
            r1 = _get_daily_returns(ticker, 90)
            r2 = _get_daily_returns(open_t, 90)
            if len(r1) < 20 or len(r2) < 20:
                continue
            min_len = min(len(r1), len(r2))
            corr = float(np.corrcoef(r1[-min_len:], r2[-min_len:])[0][1])
            if abs(corr) > CORRELATION_THRESHOLD:
                return True, round(corr, 4), open_t
        except Exception:
            continue

    return False, 0.0, None


# --- Sector Beta ---

def calculate_sector_beta(ticker, benchmark="SPY"):
    """Calculate beta of ticker vs benchmark."""
    cached = _get_cached_metric("beta", ticker)
    if cached:
        return cached

    r_ticker = _get_daily_returns(ticker, 90)
    r_bench = _get_daily_returns(benchmark, 90)

    if len(r_ticker) < 20 or len(r_bench) < 20:
        return {"ticker": ticker, "beta": 1.0, "benchmark": benchmark, "sufficient_data": False}

    min_len = min(len(r_ticker), len(r_bench))
    r_t = r_ticker[-min_len:]
    r_b = r_bench[-min_len:]

    covariance = float(np.cov(r_t, r_b)[0][1])
    variance = float(np.var(r_b))
    beta = round(covariance / variance, 4) if variance > 0 else 1.0

    result = {"ticker": ticker, "beta": beta, "benchmark": benchmark, "sufficient_data": True}
    _cache_metric("beta", result, ticker)
    return result


def get_portfolio_beta():
    """Calculate weighted average beta for the portfolio."""
    conn = get_db()
    try:
        positions = conn.execute(
            "SELECT ticker, quantity, entry_price FROM open_positions WHERE status = 'open'"
        ).fetchall()
    finally:
        conn.close()

    if not positions:
        return 0.0

    total_value = sum(p["quantity"] * p["entry_price"] for p in positions)
    if total_value <= 0:
        return 0.0

    weighted_beta = 0.0
    for pos in positions:
        beta_data = calculate_sector_beta(pos["ticker"])
        weight = (pos["quantity"] * pos["entry_price"]) / total_value
        weighted_beta += beta_data["beta"] * weight

    return round(weighted_beta, 4)


# --- Risk Grade ---

def calculate_risk_grade():
    """Calculate composite risk grade A+ through F.

    Returns dict: {grade, score, components}
    """
    from services.portfolio_service import get_portfolio_state

    state = get_portfolio_state()
    var_data = calculate_var()
    div_score = calculate_diversification_score()
    port_beta = get_portfolio_beta()

    # Component scores (0-100 each)
    var_score = max(0, 100 - abs(var_data["var_95_pct"]) * 50) if var_data["var_95_pct"] != 0 else 100
    div_component = min(100, div_score)
    beta_score = max(0, 100 - max(0, (port_beta - 1.0)) * 100) if port_beta > 0 else 100
    win_score = min(100, state["win_rate"] * 2) if state["total_trades"] > 0 else 50
    dd_score = max(0, 100 - state["drawdown_pct"] * 33)

    composite = (
        var_score * 0.30 +
        div_component * 0.25 +
        beta_score * 0.20 +
        win_score * 0.15 +
        dd_score * 0.10
    )
    composite = round(composite, 1)

    if composite >= 95: grade = "A+"
    elif composite >= 90: grade = "A"
    elif composite >= 85: grade = "B+"
    elif composite >= 80: grade = "B"
    elif composite >= 70: grade = "C"
    elif composite >= 60: grade = "D"
    else: grade = "F"

    labels = {"A+": "Excellent", "A": "Very Good", "B+": "Good", "B": "Above Average", "C": "Average", "D": "Below Average", "F": "Poor"}

    return {
        "grade": grade,
        "label": labels.get(grade, ""),
        "score": composite,
        "components": {
            "var": round(var_score, 1),
            "diversification": round(div_component, 1),
            "beta": round(beta_score, 1),
            "win_rate": round(win_score, 1),
            "drawdown": round(dd_score, 1),
        },
    }


def refresh_all_metrics():
    """Force recalculate all risk metrics (clears cache)."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM risk_metrics")
        conn.commit()
    finally:
        conn.close()

    calculate_kelly_fraction()
    calculate_var()
    calculate_correlations()

    # Beta for each open position
    conn = get_db()
    try:
        positions = conn.execute("SELECT DISTINCT ticker FROM open_positions WHERE status = 'open'").fetchall()
    finally:
        conn.close()
    for pos in positions:
        calculate_sector_beta(pos["ticker"])

    return calculate_risk_grade()
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.quant_service import calculate_kelly_fraction, calculate_var, calculate_correlations, calculate_risk_grade, get_kelly_position_size, get_correlation_for_ticker, get_portfolio_beta, refresh_all_metrics; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/services/quant_service.py
git commit -m "feat(quant): Kelly criterion, VaR, correlations, beta, risk grading"
```

---

### Task 3: Risk API Routes

**Files:**
- Create: `routes/risk.py`
- Modify: `app.py`

- [ ] **Step 1: Create risk routes**

Create `/mnt/archie_brain/market-watch/routes/risk.py`:

```python
"""Risk API routes — quant metrics at admin/viewer/public levels."""

from flask import Blueprint, jsonify

from auth import tier_required, admin_required
from services.quant_service import (
    calculate_kelly_fraction, calculate_var, calculate_correlations,
    calculate_diversification_score, get_portfolio_beta,
    calculate_risk_grade, refresh_all_metrics,
)

risk_bp = Blueprint("risk", __name__)


@risk_bp.route("/api/trading/risk-metrics")
@tier_required("ai")
@admin_required
def get_risk_metrics():
    """Full quant detail — admin only."""
    kelly = calculate_kelly_fraction()
    var_data = calculate_var()
    corr_data = calculate_correlations()
    div_score = calculate_diversification_score()
    port_beta = get_portfolio_beta()
    grade = calculate_risk_grade()

    return jsonify({
        "success": True,
        "kelly": kelly,
        "var": var_data,
        "correlations": corr_data,
        "diversification_score": div_score,
        "portfolio_beta": port_beta,
        "risk_grade": grade,
    })


@risk_bp.route("/api/trading/risk-metrics/refresh", methods=["POST"])
@tier_required("ai")
@admin_required
def refresh_risk():
    """Force recalculate all risk metrics."""
    grade = refresh_all_metrics()
    return jsonify({"success": True, "message": "Risk metrics refreshed", "risk_grade": grade})


@risk_bp.route("/api/trading/risk-summary")
@tier_required("viewer")
def get_risk_summary():
    """Simplified risk summary — viewer tier."""
    var_data = calculate_var()
    div_score = calculate_diversification_score()
    port_beta = get_portfolio_beta()
    grade = calculate_risk_grade()

    div_label = "Excellent" if div_score >= 80 else "Good" if div_score >= 60 else "Fair" if div_score >= 40 else "Poor"

    return jsonify({
        "success": True,
        "risk_grade": grade["grade"],
        "risk_label": grade["label"],
        "var_95_pct": var_data["var_95_pct"],
        "var_95_dollar": var_data["var_95_dollar"],
        "diversification_score": div_score,
        "diversification_label": div_label,
        "portfolio_beta": port_beta,
    })


@risk_bp.route("/api/public/risk-grade")
def get_public_risk_grade():
    """Public risk grade — no auth."""
    grade = calculate_risk_grade()
    return jsonify({
        "success": True,
        "grade": grade["grade"],
        "label": grade["label"],
        "score": grade["score"],
    })
```

- [ ] **Step 2: Register blueprint in app.py**

Add to `create_app()` in `/mnt/archie_brain/market-watch/app.py`, after the news_bp registration:

```python
    from routes.risk import risk_bp
    app.register_blueprint(risk_bp)
```

- [ ] **Step 3: Verify**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from routes.risk import risk_bp; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/routes/risk.py market-watch/app.py
git commit -m "feat(quant): risk API routes — admin detail, viewer summary, public grade"
```

---

### Task 4: Wire Kelly + Correlation into Execution Engine

**Files:**
- Modify: `services/execution_engine.py`

- [ ] **Step 1: Read current execution_engine.py**

Read `/mnt/archie_brain/market-watch/services/execution_engine.py` to see the current position sizing logic and risk gates.

- [ ] **Step 2: Update position sizing to use Kelly**

Find the section in `evaluate()` where quantity is calculated (after Gate 5, around the position size cap). Replace the sizing logic:

Find:
```python
    suggested_size = analysis.get("suggested_position_size")
    if suggested_size and suggested_size > 0:
        order_value = min(suggested_size, max_order_value)
    else:
        order_value = min(portfolio_value / rc.MAX_POSITIONS, max_order_value)
```

Replace with:
```python
    # Kelly-based sizing (falls back to equal-weight if insufficient data)
    from services.quant_service import get_kelly_position_size
    kelly_size = get_kelly_position_size(portfolio_value, rc.MAX_POSITION_PCT)

    suggested_size = analysis.get("suggested_position_size")
    if kelly_size is not None:
        order_value = min(kelly_size, max_order_value)
    elif suggested_size and suggested_size > 0:
        order_value = min(suggested_size, max_order_value)
    else:
        order_value = min(portfolio_value / rc.MAX_POSITIONS, max_order_value)
```

- [ ] **Step 3: Add correlation gate after Gate 9 (sector concentration)**

Find the Gate 9 section and add a new gate after it, before Gate 10:

```python
    # Gate 9b: Correlation check
    from services.quant_service import get_correlation_for_ticker
    is_correlated, max_corr, corr_with = get_correlation_for_ticker(ticker)
    if is_correlated:
        # Halve the position size instead of blocking
        order_value = order_value / 2
        quantity = int(order_value / current_price)
        gate("correlation_adjustment", True, max_corr,
             f"Correlated with {corr_with} ({max_corr}), size halved")
        if quantity <= 0:
            return _reject(f"Failed: correlation with {corr_with} reduced size to 0", gates_log)
    else:
        gate("correlation_adjustment", True, max_corr, "No high correlations")

    # Gate 9c: Portfolio beta check
    from services.quant_service import get_portfolio_beta, MAX_PORTFOLIO_BETA
    port_beta = get_portfolio_beta()
    ticker_beta = calculate_sector_beta(ticker).get("beta", 1.0) if 'calculate_sector_beta' in dir() else 1.0
    from services.quant_service import calculate_sector_beta
    ticker_beta = calculate_sector_beta(ticker).get("beta", 1.0)
    if not gate("portfolio_beta", port_beta < MAX_PORTFOLIO_BETA or ticker_beta < 1.0, port_beta,
                f"portfolio={port_beta}, ticker={ticker_beta}, limit={MAX_PORTFOLIO_BETA}"):
        return _reject(f"Failed: portfolio beta {port_beta} >= {MAX_PORTFOLIO_BETA}", gates_log)
```

- [ ] **Step 4: Verify syntax**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "import ast; ast.parse(open('services/execution_engine.py').read()); print('Syntax OK')"
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/services/execution_engine.py
git commit -m "feat(quant): Kelly sizing + correlation adjustment + beta gate in execution engine"
```

---

### Task 5: Frontend — Risk Panels + Landing Badge

**Files:**
- Modify: `static/index.html`
- Modify: `templates/landing.html`

- [ ] **Step 1: Add admin risk panel to dashboard**

Add to the admin Trading Ops panel in `static/index.html` (after Last Cycle Results section):

An admin-only section showing: Kelly fraction, VaR 95%/99%, portfolio beta, diversification score, risk grade, and a "Refresh Risk Metrics" button. Use safe DOM creation (textContent only). Fetch from `/api/trading/risk-metrics`. Include a `loadRiskMetrics()` function called from `loadAdminPanel()`.

- [ ] **Step 2: Add viewer risk summary to dashboard**

Add a "Portfolio Risk" section visible to all authenticated users (not just admin). Fetch from `/api/trading/risk-summary`. Show: risk grade badge, VaR statement, diversification label, portfolio beta. Use `data-tier="viewer"` attribute.

- [ ] **Step 3: Add public risk grade badge to landing page**

In `templates/landing.html`, add a risk grade badge next to the track record stats. Fetch from `/api/public/risk-grade`. Show grade letter + label. Use textContent for rendering.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/static/index.html market-watch/templates/landing.html
git commit -m "feat(quant): risk panels — admin detail, viewer summary, public grade badge"
```

---

### Task 6: Docker Config + Rebuild + Deploy

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add quant env vars to docker-compose.yml**

Add to environment section:

```yaml
      # Quant Risk
      - MW_KELLY_ENABLED=${MW_KELLY_ENABLED:-true}
      - MW_KELLY_FRACTION=${MW_KELLY_FRACTION:-0.5}
      - MW_KELLY_MIN_TRADES=${MW_KELLY_MIN_TRADES:-10}
      - MW_MAX_PORTFOLIO_BETA=${MW_MAX_PORTFOLIO_BETA:-1.5}
      - MW_CORRELATION_THRESHOLD=${MW_CORRELATION_THRESHOLD:-0.7}
      - MW_RISK_METRICS_TTL_DAYS=${MW_RISK_METRICS_TTL_DAYS:-7}
```

- [ ] **Step 2: Add to .env.example**

```bash

# Quant Risk
MW_KELLY_ENABLED=true
MW_KELLY_FRACTION=0.5
MW_KELLY_MIN_TRADES=10
MW_MAX_PORTFOLIO_BETA=1.5
MW_CORRELATION_THRESHOLD=0.7
MW_RISK_METRICS_TTL_DAYS=7
```

- [ ] **Step 3: Rebuild + restart local**

```bash
cd /mnt/archie_brain/market-watch
docker compose build --no-cache && docker compose up -d
```

- [ ] **Step 4: Test endpoints**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
import json
app = create_app()
with app.test_client() as c:
    r1 = c.get('/api/public/risk-grade')
    d1 = json.loads(r1.data)
    print(f'Public risk grade: {r1.status_code} grade={d1.get(\"grade\")} label={d1.get(\"label\")}')
    r2 = c.get('/api/trading/risk-summary')
    print(f'Risk summary (no auth): {r2.status_code}')
    r3 = c.get('/api/trading/risk-metrics')
    print(f'Risk metrics (no auth): {r3.status_code}')
"
```

Expected: Public grade 200, summary 401, metrics 401.

- [ ] **Step 5: Deploy to VPS**

```bash
sshpass -p 'ArchieOutpost2026' rsync -az --exclude='.env' --exclude='market.db' --exclude='__pycache__' --exclude='.git' /mnt/archie_brain/market-watch/ kytran@76.13.107.109:/opt/kytran-market-watch/
sshpass -p 'ArchieOutpost2026' ssh kytran@76.13.107.109 "cd /opt/kytran-market-watch && docker compose build --no-cache && docker compose up -d"
```

- [ ] **Step 6: Commit config**

```bash
cd /mnt/archie_brain
git add market-watch/docker-compose.yml market-watch/.env.example
git commit -m "feat(config): quant risk env vars — Kelly, beta, correlation, TTL"
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Schema + numpy | schema.sql, requirements.txt | 1 |
| 2 | Quant service (Kelly, VaR, corr, beta, grade) | services/quant_service.py | 1 |
| 3 | Risk API routes (4 endpoints) | routes/risk.py, app.py | 1 |
| 4 | Wire Kelly + correlation into execution engine | services/execution_engine.py | 1 |
| 5 | Frontend risk panels + landing badge | static/index.html, templates/landing.html | 1 |
| 6 | Docker config + rebuild + VPS deploy | docker-compose.yml, .env.example | 1 |

**Total: 6 tasks, ~6 commits, 2 new files, 8 modified files**
