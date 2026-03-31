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
            "kelly_full": 0.0,
            "kelly_half": 0.0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "ratio": 0.0,
            "sufficient_data": False,
            "trade_count": len(trades),
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
            "var_95_pct": 0.0,
            "var_95_dollar": 0.0,
            "var_99_pct": 0.0,
            "var_99_dollar": 0.0,
            "portfolio_volatility": 0.0,
            "positions_used": 0,
        }
        return result

    # Get portfolio value
    total_value = sum(p["quantity"] * p["entry_price"] for p in positions)
    if total_value <= 0:
        return {
            "var_95_pct": 0.0,
            "var_95_dollar": 0.0,
            "var_99_pct": 0.0,
            "var_99_dollar": 0.0,
            "portfolio_volatility": 0.0,
            "positions_used": 0,
        }

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
        return {
            "var_95_pct": 0.0,
            "var_95_dollar": 0.0,
            "var_99_pct": 0.0,
            "var_99_dollar": 0.0,
            "portfolio_volatility": 0.0,
            "positions_used": 0,
        }

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
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM open_positions WHERE status = 'open'"
            ).fetchall()
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
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM open_positions WHERE status = 'open'"
        ).fetchall()
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
        var_score * 0.30
        + div_component * 0.25
        + beta_score * 0.20
        + win_score * 0.15
        + dd_score * 0.10
    )
    composite = round(composite, 1)

    if composite >= 95:
        grade = "A+"
    elif composite >= 90:
        grade = "A"
    elif composite >= 85:
        grade = "B+"
    elif composite >= 80:
        grade = "B"
    elif composite >= 70:
        grade = "C"
    elif composite >= 60:
        grade = "D"
    else:
        grade = "F"

    labels = {
        "A+": "Excellent",
        "A": "Very Good",
        "B+": "Good",
        "B": "Above Average",
        "C": "Average",
        "D": "Below Average",
        "F": "Poor",
    }

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
        positions = conn.execute(
            "SELECT DISTINCT ticker FROM open_positions WHERE status = 'open'"
        ).fetchall()
    finally:
        conn.close()
    for pos in positions:
        calculate_sector_beta(pos["ticker"])

    return calculate_risk_grade()
