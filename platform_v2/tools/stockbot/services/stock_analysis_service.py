"""
StockBot Analysis Service
5-agent parallel analysis engine: Technical, Fundamental, Sentiment, Risk, Synthesizer
Created: 2026-03-14
"""

import json
import logging
import re
import sys
import threading
from datetime import datetime, timedelta, timezone

import psycopg2.extras

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from archie_bridge import archie_bridge as ai_bridge

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

from database import get_db_cursor

logger = logging.getLogger(__name__)

# ─── Agent system prompts ────────────────────────────────────────────────────

TECHNICAL_PROMPT = """You are Quinn Park, a precise technical analyst. Analyze the provided market data
and return ONLY a JSON object with these exact keys:
{
  "signal": "BUY|SELL|HOLD|STRONG_BUY|STRONG_SELL",
  "support": <float price level>,
  "resistance": <float price level>,
  "pattern": "<detected chart pattern or 'none'>",
  "rsi_interpretation": "<oversold|neutral|overbought>",
  "macd_interpretation": "<bullish|neutral|bearish>",
  "confidence": <integer 0-100>,
  "reasoning": "<1-2 sentence technical summary>"
}
Base your analysis on price action, momentum indicators, support/resistance levels."""

FUNDAMENTAL_PROMPT = """You are Victor Chen, a fundamental analyst focused on intrinsic value.
Analyze the provided company and financial data and return ONLY a JSON object:
{
  "valuation": "undervalued|fairly_valued|overvalued",
  "pe_assessment": "<cheap|fair|expensive>",
  "revenue_trend": "growing|stable|declining",
  "debt_concern": <boolean>,
  "dividend_appeal": <boolean>,
  "outlook": "bullish|neutral|bearish",
  "confidence": <integer 0-100>,
  "reasoning": "<1-2 sentence fundamental summary>"
}"""

SENTIMENT_PROMPT = """You are Priya Sharma, a sentiment and momentum analyst. Analyze the provided
market context and return ONLY a JSON object:
{
  "sentiment": "very_bullish|bullish|neutral|bearish|very_bearish",
  "momentum_score": <integer -100 to 100>,
  "volume_signal": "accumulation|neutral|distribution",
  "trend_strength": "strong|moderate|weak",
  "market_phase": "markup|distribution|markdown|accumulation",
  "confidence": <integer 0-100>,
  "reasoning": "<1-2 sentence sentiment summary>"
}"""

RISK_PROMPT = """You are Sam Torres, a conservative risk manager. Assess the position risk for the
provided stock data and return ONLY a JSON object:
{
  "risk_level": "low|medium|high|very_high",
  "max_position_pct": <float 0-100 recommended max portfolio %>,
  "stop_loss_pct": <float suggested stop loss % below entry>,
  "take_profit_pct": <float suggested take profit % above entry>,
  "volatility_assessment": "low|moderate|high|extreme",
  "key_risk": "<single biggest risk factor>",
  "confidence": <integer 0-100>,
  "reasoning": "<1-2 sentence risk summary>"
}"""

SYNTHESIZER_PROMPT = """You are Olivia Reed, Chief Strategist. You receive analysis from 4 specialist
agents and must synthesize into a final actionable recommendation. Return ONLY a JSON object:
{
  "overall_signal": "STRONG_BUY|BUY|HOLD|SELL|STRONG_SELL",
  "confidence": <integer 0-100>,
  "price_target": <float or null>,
  "entry_zone": "<price range string or 'current price'>",
  "stop_loss": <float price>,
  "primary_thesis": "<2-3 sentence investment thesis>",
  "key_risks": ["<risk1>", "<risk2>"],
  "time_horizon": "short_term|medium_term|long_term",
  "reasoning": "<2-3 sentence synthesis of all agent inputs>"
}"""


# ─── JSON parsing helper ─────────────────────────────────────────────────────


def _parse_json_response(text: str) -> dict:
    """Try json.loads first, then regex-extract ```json blocks, then fallback {}."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # Try to extract ```json ... ``` block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    # Try to find any {...} object in the text
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


# ─── Single agent dispatcher ─────────────────────────────────────────────────


def _run_agent(agent_name: str, system_prompt: str, user_prompt: str, results: dict, key: str):
    """Run one agent via ai_bridge and store parsed JSON result in results[key]."""
    try:
        if not BRIDGE_AVAILABLE:
            results[key] = {"error": "Bridge unavailable", "confidence": 0}
            return
        result = ai_bridge(
            prompt=user_prompt,
            system_prompt=system_prompt,
            agent_id=agent_name,
            task_type="stock_analysis",
            enable_memory=False,
            try_local_first=True,
        )
        raw = result.get("response", "") if isinstance(result, dict) else str(result)
        results[key] = _parse_json_response(raw) or {"raw": raw[:500], "confidence": 0}
    except Exception as e:
        logger.error(f"Agent {agent_name} error: {e}")
        results[key] = {"error": str(e), "confidence": 0}


# ─── Main analysis function ──────────────────────────────────────────────────


def run_full_analysis(ticker: str, user_id: int) -> dict:
    """
    Run 5-agent parallel analysis for a ticker.
    Returns full analysis dict and persists to stock_analyses table.
    """
    ticker = ticker.upper().strip()
    logger.info(f"run_full_analysis: starting for {ticker} (user={user_id})")

    # 1. Fetch market data
    try:
        from .market_data_service import get_company_info, get_history, get_quote

        quote = get_quote(ticker)
        history = get_history(ticker, "3mo")
        company = get_company_info(ticker)
    except Exception as e:
        logger.error(f"run_full_analysis: market data fetch failed for {ticker}: {e}")
        return {"ticker": ticker, "error": f"Market data unavailable: {e}"}

    # 2. Build market context string
    price = quote.get("price", "N/A")
    change_pct = quote.get("change_pct", "N/A")
    volume = quote.get("volume", "N/A")
    market_cap = quote.get("market_cap", "N/A")
    pe_ratio = quote.get("pe_ratio", "N/A")
    high_52w = quote.get("high_52w", "N/A")
    low_52w = quote.get("low_52w", "N/A")
    div_yield = quote.get("dividend_yield", "N/A")

    # Summarize recent price history
    history_summary = "No history available"
    if history:
        closes = [h.get("close") for h in history[-20:] if h.get("close")]
        if closes:
            history_summary = (
                f"Last 20 closes: min={min(closes):.2f}, max={max(closes):.2f}, "
                f"latest={closes[-1]:.2f}, 20-period trend={'up' if closes[-1] > closes[0] else 'down'}"
            )

    market_context = f"""TICKER: {ticker}
Company: {company.get('name', ticker)} | Sector: {company.get('sector', 'N/A')} | Industry: {company.get('industry', 'N/A')}
Current Price: ${price} | Change: {change_pct}% | Volume: {volume:,} | Market Cap: {market_cap}
P/E Ratio: {pe_ratio} | Dividend Yield: {div_yield} | 52W High: {high_52w} | 52W Low: {low_52w}
Recent Price History: {history_summary}
Description: {str(company.get('description', ''))[:300]}"""

    # 3. Dispatch 4 specialist agents in parallel
    agent_results: dict = {}
    threads = [
        threading.Thread(
            target=_run_agent,
            args=("quant", TECHNICAL_PROMPT, f"Analyze {ticker}:\n{market_context}", agent_results, "technical"),
        ),
        threading.Thread(
            target=_run_agent,
            args=("value", FUNDAMENTAL_PROMPT, f"Evaluate {ticker}:\n{market_context}", agent_results, "fundamental"),
        ),
        threading.Thread(
            target=_run_agent,
            args=(
                "pulse",
                SENTIMENT_PROMPT,
                f"Assess sentiment for {ticker}:\n{market_context}",
                agent_results,
                "sentiment",
            ),
        ),
        threading.Thread(
            target=_run_agent,
            args=("shield", RISK_PROMPT, f"Assess risk for {ticker}:\n{market_context}", agent_results, "risk"),
        ),
    ]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join(timeout=30)

    # 4. Synthesize — feed all 4 results to Synthesizer agent
    synthesis_input = f"""Ticker: {ticker} @ ${price}

TECHNICAL ANALYSIS (Quinn Park):
{json.dumps(agent_results.get('technical', {}), indent=2)}

FUNDAMENTAL ANALYSIS (Victor Chen):
{json.dumps(agent_results.get('fundamental', {}), indent=2)}

SENTIMENT ANALYSIS (Priya Sharma):
{json.dumps(agent_results.get('sentiment', {}), indent=2)}

RISK ASSESSMENT (Sam Torres):
{json.dumps(agent_results.get('risk', {}), indent=2)}

Synthesize the above into a final actionable recommendation."""

    synthesis_results: dict = {}
    synth_thread = threading.Thread(
        target=_run_agent,
        args=("oracle", SYNTHESIZER_PROMPT, synthesis_input, synthesis_results, "synthesis"),
    )
    synth_thread.daemon = True
    synth_thread.start()
    synth_thread.join(timeout=30)

    synthesis = synthesis_results.get("synthesis", {})
    overall_signal = synthesis.get("overall_signal", "HOLD")
    confidence = synthesis.get("confidence", 0)
    price_target = synthesis.get("price_target")

    # 5. Persist to stock_analyses
    analysis_id = None
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO stock_analyses
                    (user_id, ticker, technical, fundamental, sentiment, risk, synthesis,
                     overall_signal, confidence, price_target, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    user_id,
                    ticker,
                    psycopg2.extras.Json(agent_results.get("technical", {})),
                    psycopg2.extras.Json(agent_results.get("fundamental", {})),
                    psycopg2.extras.Json(agent_results.get("sentiment", {})),
                    psycopg2.extras.Json(agent_results.get("risk", {})),
                    psycopg2.extras.Json(synthesis),
                    overall_signal,
                    confidence,
                    price_target,
                ),
            )
            row = cur.fetchone()
            analysis_id = row[0] if row else None
    except Exception as e:
        logger.error(f"run_full_analysis: DB insert failed for {ticker}: {e}")

    result = {
        "analysis_id": analysis_id,
        "ticker": ticker,
        "price": price,
        "technical": agent_results.get("technical", {}),
        "fundamental": agent_results.get("fundamental", {}),
        "sentiment": agent_results.get("sentiment", {}),
        "risk": agent_results.get("risk", {}),
        "synthesis": synthesis,
        "overall_signal": overall_signal,
        "confidence": confidence,
        "price_target": price_target,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"run_full_analysis: complete for {ticker} — signal={overall_signal}, confidence={confidence}")
    return result


# ─── Query helpers ───────────────────────────────────────────────────────────


def get_latest_analysis(ticker: str) -> dict | None:
    """Return the most recent analysis for a ticker, or None."""
    ticker = ticker.upper().strip()
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, user_id, ticker, technical, fundamental, sentiment, risk, synthesis,
                       overall_signal, confidence, price_target, created_at
                FROM stock_analyses
                WHERE ticker = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (ticker,),
            )
            row = cur.fetchone()
        if not row:
            return None
        return {
            "analysis_id": row[0],
            "user_id": row[1],
            "ticker": row[2],
            "technical": row[3] or {},
            "fundamental": row[4] or {},
            "sentiment": row[5] or {},
            "risk": row[6] or {},
            "synthesis": row[7] or {},
            "overall_signal": row[8],
            "confidence": row[9],
            "price_target": float(row[10]) if row[10] else None,
            "created_at": row[11].isoformat() if row[11] else None,
        }
    except Exception as e:
        logger.error(f"get_latest_analysis({ticker}) error: {e}")
        return None


def get_analysis_history(ticker: str, limit: int = 10) -> list:
    """Return recent analyses for a ticker (newest first)."""
    ticker = ticker.upper().strip()
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, ticker, overall_signal, confidence, price_target, created_at
                FROM stock_analyses
                WHERE ticker = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (ticker, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "analysis_id": r[0],
                "ticker": r[1],
                "overall_signal": r[2],
                "confidence": r[3],
                "price_target": float(r[4]) if r[4] else None,
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_analysis_history({ticker}) error: {e}")
        return []


# ─── Auto-scan watchlist ─────────────────────────────────────────────────────


def auto_scan_watchlist() -> int:
    """
    Scan all unique watchlist tickers that haven't been analysed in the last 4 hours.
    Caps at 5 per cycle. Stores scan results. Returns count of analyses run.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
        with get_db_cursor() as (conn, cur):
            # Get all unique tickers from watchlist
            cur.execute("SELECT DISTINCT ticker FROM stock_watchlist")
            watchlist_tickers = [r[0] for r in cur.fetchall()]

            if not watchlist_tickers:
                return 0

            # Filter out tickers with recent analysis
            cur.execute(
                """
                SELECT DISTINCT ticker FROM stock_analyses
                WHERE ticker = ANY(%s) AND created_at > %s
                """,
                (watchlist_tickers, cutoff),
            )
            recently_analysed = {r[0] for r in cur.fetchall()}

        stale = [t for t in watchlist_tickers if t not in recently_analysed][:5]
        if not stale:
            logger.debug("auto_scan_watchlist: all tickers have recent analysis")
            return 0

        count = 0
        for ticker in stale:
            try:
                analysis = run_full_analysis(ticker, user_id=1)
                signal = analysis.get("overall_signal", "HOLD")
                confidence = analysis.get("confidence", 0)
                summary = analysis.get("synthesis", {}).get("primary_thesis", "")[:500]

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        INSERT INTO stock_scan_results (ticker, scan_type, signal, confidence, summary, scanned_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        """,
                        (ticker, "watchlist_auto", signal, confidence, summary),
                    )
                count += 1
                logger.info(f"auto_scan_watchlist: {ticker} → {signal} ({confidence}%)")
            except Exception as e:
                logger.error(f"auto_scan_watchlist: error scanning {ticker}: {e}")

        return count

    except Exception as e:
        logger.error(f"auto_scan_watchlist error: {e}")
        return 0
