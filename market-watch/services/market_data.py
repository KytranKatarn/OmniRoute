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
