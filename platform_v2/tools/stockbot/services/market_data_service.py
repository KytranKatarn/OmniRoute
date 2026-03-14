"""
Market Data Service — StockBot Phase 1
Handles yfinance data fetching, price caching, and technical indicators.
"""

import logging
from datetime import datetime, timezone, timedelta

import sys

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from database import get_db_cursor

logger = logging.getLogger(__name__)

try:
    import yfinance as yf

    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    logger.warning("yfinance not installed — market data unavailable until Docker rebuild")

PRICE_CACHE_TTL = 300  # 5 minutes
INTRADAY_HISTORY_TTL = 3600  # 1 hour
DAILY_HISTORY_TTL = 86400  # 24 hours


def _now_utc():
    return datetime.now(timezone.utc)


def get_quote(ticker: str) -> dict:
    """Return latest quote for ticker. Checks cache first (5min TTL)."""
    ticker = ticker.upper().strip()

    # Check cache
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT price, change_pct, volume, market_cap, pe_ratio, dividend_yield, "
            "high_52w, low_52w, data, cached_at FROM stock_price_cache WHERE ticker = %s",
            (ticker,),
        )
        row = cur.fetchone()
        if row:
            cached_at = row[9]
            if cached_at and (_now_utc() - cached_at).total_seconds() < PRICE_CACHE_TTL:
                return {
                    "ticker": ticker,
                    "price": float(row[0]) if row[0] else None,
                    "change_pct": float(row[1]) if row[1] else None,
                    "volume": row[2],
                    "market_cap": row[3],
                    "pe_ratio": float(row[4]) if row[4] else None,
                    "dividend_yield": float(row[5]) if row[5] else None,
                    "high_52w": float(row[6]) if row[6] else None,
                    "low_52w": float(row[7]) if row[7] else None,
                    "cached": True,
                }

    if not YFINANCE_AVAILABLE:
        return {"ticker": ticker, "error": "yfinance not available", "cached": False}

    try:
        info = yf.Ticker(ticker).info
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        change_pct = None
        if price and prev_close and prev_close != 0:
            change_pct = round((price - prev_close) / prev_close * 100, 4)

        quote = {
            "ticker": ticker,
            "price": price,
            "change_pct": change_pct,
            "volume": info.get("volume") or info.get("regularMarketVolume"),
            "market_cap": info.get("marketCap"),
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "dividend_yield": info.get("dividendYield"),
            "high_52w": info.get("fiftyTwoWeekHigh"),
            "low_52w": info.get("fiftyTwoWeekLow"),
            "cached": False,
        }

        import psycopg2.extras

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO stock_price_cache
                    (ticker, price, change_pct, volume, market_cap, pe_ratio, dividend_yield,
                     high_52w, low_52w, data, cached_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    price = EXCLUDED.price,
                    change_pct = EXCLUDED.change_pct,
                    volume = EXCLUDED.volume,
                    market_cap = EXCLUDED.market_cap,
                    pe_ratio = EXCLUDED.pe_ratio,
                    dividend_yield = EXCLUDED.dividend_yield,
                    high_52w = EXCLUDED.high_52w,
                    low_52w = EXCLUDED.low_52w,
                    data = EXCLUDED.data,
                    cached_at = NOW()
                """,
                (
                    ticker,
                    quote["price"],
                    quote["change_pct"],
                    quote["volume"],
                    quote["market_cap"],
                    quote["pe_ratio"],
                    quote["dividend_yield"],
                    quote["high_52w"],
                    quote["low_52w"],
                    psycopg2.extras.Json(info),
                ),
            )
        return quote

    except Exception as e:
        logger.error(f"get_quote({ticker}) error: {e}")
        return {"ticker": ticker, "error": str(e), "cached": False}


def get_history(ticker: str, period: str = "1mo") -> list:
    """Return OHLCV history. Cache TTL: 1h for intraday periods, 24h for daily+."""
    ticker = ticker.upper().strip()
    intraday_periods = {"1d", "5d"}
    ttl = INTRADAY_HISTORY_TTL if period in intraday_periods else DAILY_HISTORY_TTL

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT ohlcv, cached_at FROM stock_history_cache WHERE ticker = %s AND period = %s",
            (ticker, period),
        )
        row = cur.fetchone()
        if row and row[0] and row[1]:
            if (_now_utc() - row[1]).total_seconds() < ttl:
                return row[0]

    if not YFINANCE_AVAILABLE:
        return []

    try:
        hist = yf.Ticker(ticker).history(period=period)
        if hist.empty:
            return []

        records = []
        for ts, row in hist.iterrows():
            records.append(
                {
                    "date": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row["Volume"]),
                }
            )

        import psycopg2.extras

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO stock_history_cache (ticker, period, ohlcv, cached_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (ticker, period) DO UPDATE SET
                    ohlcv = EXCLUDED.ohlcv, cached_at = NOW()
                """,
                (ticker, period, psycopg2.extras.Json(records)),
            )
        return records

    except Exception as e:
        logger.error(f"get_history({ticker}, {period}) error: {e}")
        return []


def get_company_info(ticker: str) -> dict:
    """Return company name, sector, industry, description from yfinance."""
    ticker = ticker.upper().strip()
    if not YFINANCE_AVAILABLE:
        return {"ticker": ticker, "error": "yfinance not available"}
    try:
        info = yf.Ticker(ticker).info
        return {
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName", ticker),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "description": info.get("longBusinessSummary"),
            "website": info.get("website"),
            "employees": info.get("fullTimeEmployees"),
            "country": info.get("country"),
        }
    except Exception as e:
        logger.error(f"get_company_info({ticker}) error: {e}")
        return {"ticker": ticker, "error": str(e)}


def batch_update_prices(tickers: list) -> int:
    """Fetch and cache latest quotes for a list of tickers. Returns count updated."""
    updated = 0
    for ticker in tickers:
        try:
            result = get_quote(ticker)
            if result.get("price") is not None:
                updated += 1
        except Exception as e:
            logger.error(f"batch_update_prices: error updating {ticker}: {e}")
    return updated


def search_tickers(query: str) -> list:
    """Basic ticker search via yfinance. Returns [{symbol, name}]."""
    if not YFINANCE_AVAILABLE:
        return []
    query = query.upper().strip()
    try:
        info = yf.Ticker(query).info
        name = info.get("longName") or info.get("shortName")
        if name and info.get("regularMarketPrice") is not None or info.get("currentPrice") is not None:
            return [{"symbol": query, "name": name}]
    except Exception:
        pass
    return []


def calculate_indicators(ohlcv: list, indicators: list) -> dict:
    """
    Compute technical indicators from OHLCV data.
    Supported: SMA(period), EMA(period), RSI(14), MACD(12,26,9), Bollinger(20,2)
    Returns dict of {indicator_name: [values aligned with dates]}
    """
    if not ohlcv:
        return {}

    closes = [r["close"] for r in ohlcv]
    dates = [r["date"] for r in ohlcv]
    result = {}

    for indicator in indicators:
        key = indicator.upper()
        try:
            if key.startswith("SMA"):
                period = int(key.replace("SMA", "").strip("()") or 20)
                values = _sma(closes, period)
                result[indicator] = [{"date": d, "value": v} for d, v in zip(dates, values)]

            elif key.startswith("EMA"):
                period = int(key.replace("EMA", "").strip("()") or 20)
                values = _ema(closes, period)
                result[indicator] = [{"date": d, "value": v} for d, v in zip(dates, values)]

            elif key.startswith("RSI"):
                values = _rsi(closes, 14)
                result[indicator] = [{"date": d, "value": v} for d, v in zip(dates, values)]

            elif key.startswith("MACD"):
                macd_line, signal_line, histogram = _macd(closes)
                result[indicator] = [
                    {"date": d, "macd": m, "signal": s, "histogram": h}
                    for d, m, s, h in zip(dates, macd_line, signal_line, histogram)
                ]

            elif key.startswith("BOLLINGER"):
                upper, middle, lower = _bollinger(closes)
                result[indicator] = [
                    {"date": d, "upper": u, "middle": m, "lower": l} for d, u, m, l in zip(dates, upper, middle, lower)
                ]
        except Exception as e:
            logger.error(f"calculate_indicators: error for {indicator}: {e}")
            result[indicator] = []

    return result


# ─── Indicator helpers ────────────────────────────────────────────────────────


def _sma(closes: list, period: int) -> list:
    result = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        result[i] = round(sum(closes[i - period + 1 : i + 1]) / period, 4)
    return result


def _ema(closes: list, period: int) -> list:
    result = [None] * len(closes)
    if len(closes) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = sum(closes[:period]) / period
    for i in range(period, len(closes)):
        result[i] = round(closes[i] * k + result[i - 1] * (1 - k), 4)
    return result


def _rsi(closes: list, period: int = 14) -> list:
    result = [None] * len(closes)
    if len(closes) < period + 1:
        return result
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        result[i] = round(100 - (100 / (1 + rs)), 4)
    return result


def _macd(closes: list, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [round(f - s, 4) if f is not None and s is not None else None for f, s in zip(ema_fast, ema_slow)]
    # Signal line = EMA(9) of MACD line (skip Nones)
    valid_start = next((i for i, v in enumerate(macd_line) if v is not None), None)
    signal_line = [None] * len(macd_line)
    if valid_start is not None:
        macd_valid = [v if v is not None else 0 for v in macd_line]
        sig = _ema(macd_valid[valid_start:], signal)
        for i, v in enumerate(sig):
            signal_line[valid_start + i] = v
    histogram = [round(m - s, 4) if m is not None and s is not None else None for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, histogram


def _bollinger(closes: list, period: int = 20, std_dev: float = 2.0):
    import math

    upper = [None] * len(closes)
    middle = _sma(closes, period)
    lower = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mean = middle[i]
        variance = sum((x - mean) ** 2 for x in window) / period
        sd = math.sqrt(variance)
        upper[i] = round(mean + std_dev * sd, 4)
        lower[i] = round(mean - std_dev * sd, 4)
    return upper, middle, lower
