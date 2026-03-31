"""W.A.T.C.H. 6-agent pipeline orchestration via A.R.C.H.I.E. Bridge dispatcher.

Agents: Quant, Value, Pulse, Shield, Oracle, M.A.R.K.E.T.
Orchestrator: W.A.T.C.H. (#152) — this module IS the orchestration logic.
"""

import json
import logging
import os
import time
import requests
from db import get_db
from services.market_data import (
    get_quote,
    get_history,
    get_fundamentals,
    calculate_indicators,
)
from services.sentiment import fetch_and_score_news, get_sentiment_summary

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BRIDGE_URL = os.environ.get("ARCHIE_HUB_URL", "http://192.168.1.200:3000")
BRIDGE_DISPATCH = f"{BRIDGE_URL}/api/bridge/dispatch"

# Circuit breakers
MAX_TRADES_PER_DAY = 10
MAX_PORTFOLIO_EXPOSURE = 0.8
MAX_SINGLE_POSITION = 0.2
MAX_CONSECUTIVE_LOSSES = 5

# W.A.T.C.H. agent roster — keyed for pipeline use
AGENTS = {
    "quant": {"id": 39, "name": "Quant", "display": "Quant"},
    "value": {"id": 40, "name": "Value", "display": "Value"},
    "pulse": {"id": 30, "name": "Pulse", "display": "Pulse"},
    "shield": {"id": 42, "name": "Shield", "display": "Shield"},
    "oracle": {"id": 43, "name": "Oracle", "display": "Oracle"},
    "market": {"id": 32, "name": "M.A.R.K.E.T.", "display": "M.A.R.K.E.T."},
}

# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------


def run_pipeline(ticker, market_data=None, news_data=None):
    """Run the full W.A.T.C.H. 6-agent pipeline for a single ticker.

    Returns a dict with all agent reports and execution outcome.
    """
    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO analyses (ticker) VALUES (?)", (ticker,))
        analysis_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # ------------------------------------------------------------------
    # 1. Gather market data
    # ------------------------------------------------------------------
    if market_data is None:
        quote = get_quote(ticker)
        indicators = calculate_indicators(ticker)
        fundamentals = get_fundamentals(ticker)
        market_data = {**quote, **indicators, **fundamentals}

    # ------------------------------------------------------------------
    # 2. Gather news / sentiment
    # ------------------------------------------------------------------
    if news_data is None:
        news_articles = fetch_and_score_news(ticker)
        sentiment_summary = get_sentiment_summary(ticker)
        news_data = {
            "articles": news_articles if isinstance(news_articles, list) else [],
            "summary": sentiment_summary if isinstance(sentiment_summary, dict) else {},
        }

    context = {
        "ticker": ticker,
        "market_data": market_data,
        "news": news_data,
    }

    reports = {}

    # ------------------------------------------------------------------
    # 3. Quant — technical analysis
    # ------------------------------------------------------------------
    quant_prompt = (
        "Analyze technical indicators for {ticker}. "
        "Review RSI, MACD, SMA crossovers, Bollinger Bands, volume. "
        "Provide technical score (1-10) and outlook."
    )
    quant_result = _dispatch_agent("quant", context, analysis_id, quant_prompt)
    reports["quant"] = quant_result

    # ------------------------------------------------------------------
    # 4. Value — fundamental analysis
    # ------------------------------------------------------------------
    value_prompt = (
        "Analyze fundamentals for {ticker}. "
        "Review P/E, earnings growth, revenue, margins, debt. "
        "Provide value score (1-10) and assessment."
    )
    value_result = _dispatch_agent("value", context, analysis_id, value_prompt)
    reports["value"] = value_result

    # ------------------------------------------------------------------
    # 5. Pulse — sentiment analysis
    # ------------------------------------------------------------------
    pulse_prompt = (
        "Analyze market sentiment for {ticker}. "
        "Review news headlines, sentiment scores, sector momentum. "
        "Provide sentiment score (1-10) and mood."
    )
    pulse_result = _dispatch_agent("pulse", context, analysis_id, pulse_prompt)
    reports["pulse"] = pulse_result

    # ------------------------------------------------------------------
    # 6. Shield — risk assessment (gets prior reports)
    # ------------------------------------------------------------------
    context["prior_reports"] = {
        "quant": quant_result,
        "value": value_result,
        "pulse": pulse_result,
    }
    shield_prompt = (
        "Assess risk for {ticker} position. "
        "Review technical, fundamental, sentiment reports. "
        "Recommend position sizing (0-20%), stop-loss, risk rating."
    )
    shield_result = _dispatch_agent("shield", context, analysis_id, shield_prompt)
    reports["shield"] = shield_result

    # ------------------------------------------------------------------
    # 7. Oracle — synthesis (gets ALL reports)
    # ------------------------------------------------------------------
    context["all_reports"] = {
        "quant": quant_result,
        "value": value_result,
        "pulse": pulse_result,
        "shield": shield_result,
    }
    oracle_prompt = (
        "Synthesize all analysis for {ticker}. "
        "Provide final recommendation (buy/sell/hold), confidence (0-1), "
        "target price, synthesis."
    )
    oracle_result = _dispatch_agent("oracle", context, analysis_id, oracle_prompt)
    reports["oracle"] = oracle_result

    # ------------------------------------------------------------------
    # Extract oracle decision values
    # ------------------------------------------------------------------
    recommendation = oracle_result.get("recommendation", "hold")
    if recommendation not in ("buy", "sell", "hold", "skip"):
        recommendation = "hold"
    confidence = float(oracle_result.get("confidence", 0))
    target_price = oracle_result.get("target_price")
    oracle_sentiment = oracle_result.get("sentiment", "neutral")

    position_size = float(shield_result.get("position_size_pct", 0))
    stop_loss = float(shield_result.get("stop_loss_pct", shield_result.get("stop_loss", 0)))

    # ------------------------------------------------------------------
    # 8. Store all results in analyses table
    # ------------------------------------------------------------------
    conn = get_db()
    try:
        conn.execute(
            """UPDATE analyses SET
                quant_report = ?, quant_score = ?, quant_indicators = ?,
                value_report = ?, value_score = ?,
                pulse_report = ?, pulse_score = ?,
                risk_assessment = ?, risk_approved = ?, risk_position_size = ?, risk_stop_loss = ?,
                oracle_synthesis = ?, oracle_confidence = ?,
                director_thesis = ?, director_sentiment = ?, director_confidence = ?,
                recommendation = ?, suggested_position_size = ?, stop_loss = ?, target_price = ?
               WHERE id = ?""",
            (
                json.dumps(quant_result), float(quant_result.get("score", 0)),
                json.dumps(quant_result.get("key_signals", [])),
                json.dumps(value_result), float(value_result.get("score", 0)),
                json.dumps(pulse_result), float(pulse_result.get("score", 0)),
                json.dumps(shield_result),
                1 if shield_result.get("approved", False) else 0,
                position_size, stop_loss,
                json.dumps(oracle_result), confidence,
                # Backward compat: director_* columns map to oracle
                json.dumps(oracle_result), oracle_sentiment, confidence,
                recommendation, position_size, stop_loss, target_price,
                analysis_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # ------------------------------------------------------------------
    # 9. Execute via M.A.R.K.E.T. if conditions met
    # ------------------------------------------------------------------
    execution_result = None
    if recommendation in ("buy", "sell") and confidence >= 0.6:
        breaker_ok = _check_circuit_breakers(ticker, recommendation)
        if breaker_ok:
            market_prompt = (
                "Execute {recommendation} for {ticker}. "
                "Position size: {position_size_pct}%. "
                "Stop-loss: {stop_loss_pct}%. "
                "PAPER TRADING only."
            )
            context["recommendation"] = recommendation
            context["position_size_pct"] = round(position_size * 100, 1)
            context["stop_loss_pct"] = round(stop_loss * 100, 1)
            execution_result = _dispatch_agent(
                "market", context, analysis_id, market_prompt
            )
            reports["market"] = execution_result

            # Persist execution
            conn = get_db()
            try:
                conn.execute(
                    "UPDATE analyses SET executed = 1, market_execution = ? WHERE id = ?",
                    (json.dumps(execution_result), analysis_id),
                )
                conn.commit()
            finally:
                conn.close()
        else:
            logger.warning("Circuit breaker blocked %s trade for %s", recommendation, ticker)

    return {
        "success": True,
        "ticker": ticker,
        "analysis_id": analysis_id,
        "recommendation": recommendation,
        "confidence": confidence,
        "target_price": target_price,
        "reports": reports,
        "executed": execution_result is not None,
    }


# ---------------------------------------------------------------------------
# Agent dispatch
# ---------------------------------------------------------------------------


def _dispatch_agent(agent_key, context, analysis_id, prompt_template):
    """Dispatch a single agent via A.R.C.H.I.E. Bridge.

    Returns a parsed result dict. On failure returns {"error": ..., "score": 0}.
    """
    agent = AGENTS[agent_key]
    ticker = context.get("ticker", "???")

    # Format prompt with context values
    prompt_text = prompt_template.format(
        ticker=ticker,
        recommendation=context.get("recommendation", ""),
        position_size_pct=context.get("position_size_pct", ""),
        stop_loss_pct=context.get("stop_loss_pct", ""),
    )

    # Build full prompt with supporting data
    parts = [prompt_text, ""]

    # Market data context (truncated)
    md = context.get("market_data", {})
    md_json = json.dumps(md, default=str)
    if len(md_json) > 3000:
        md_json = md_json[:3000] + "..."
    parts.append(f"Market Data:\n{md_json}")

    # News summary
    news = context.get("news", {})
    summary = news.get("summary", {})
    if summary:
        parts.append(f"\nNews Sentiment Summary:\n{json.dumps(summary, default=str)}")
    articles = news.get("articles", [])
    if articles:
        headlines = [a.get("title", "") for a in articles[:10] if isinstance(a, dict)]
        if headlines:
            parts.append(f"\nRecent Headlines:\n" + "\n".join(f"- {h}" for h in headlines))

    # Prior reports (for Shield)
    prior = context.get("prior_reports")
    if prior:
        parts.append(f"\nPrior Agent Reports:\n{json.dumps(prior, default=str)[:2000]}")

    # All reports (for Oracle)
    all_reps = context.get("all_reports")
    if all_reps:
        parts.append(f"\nAll Agent Reports:\n{json.dumps(all_reps, default=str)[:3000]}")

    full_prompt = "\n".join(parts)

    start_ms = time.time() * 1000
    try:
        resp = requests.post(
            BRIDGE_DISPATCH,
            json={
                "prompt": full_prompt,
                "agent_name": agent["name"],
                "agent_id": agent["id"],
                "module_id": "market_watch",
                "response_format": "json",
                "json_mode": True,
            },
            timeout=120,
        )
        duration_ms = int(time.time() * 1000 - start_ms)

        if resp.status_code != 200:
            _log_dispatch(analysis_id, agent["name"], agent["id"], duration_ms, "error")
            return {"error": f"Bridge returned {resp.status_code}", "score": 0}

        data = resp.json()
        raw = data.get("response", "")

        # Try to parse JSON from response
        try:
            result = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            result = {"text": str(raw), "score": 5.0}

        _log_dispatch(analysis_id, agent["name"], agent["id"], duration_ms, "success")
        return result

    except Exception as e:
        duration_ms = int(time.time() * 1000 - start_ms)
        logger.error("Agent %s dispatch failed: %s", agent["name"], e)
        _log_dispatch(analysis_id, agent["name"], agent["id"], duration_ms, "error")
        return {"error": str(e), "score": 0}


# ---------------------------------------------------------------------------
# Dispatch logging
# ---------------------------------------------------------------------------


def _log_dispatch(analysis_id, agent_name, agent_id, duration_ms, status):
    """Record an agent dispatch in the log table."""
    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO agent_dispatch_log
               (analysis_id, agent_name, agent_id, duration_ms, status)
               VALUES (?, ?, ?, ?, ?)""",
            (analysis_id, agent_name, agent_id, duration_ms, status),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("Failed to log dispatch for %s: %s", agent_name, e)


# ---------------------------------------------------------------------------
# Circuit breakers
# ---------------------------------------------------------------------------


def _check_circuit_breakers(ticker, action):
    """Return True if the trade is allowed, False if a breaker trips."""
    conn = get_db()
    try:
        # Check MAX_TRADES_PER_DAY
        row = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE date(created_at) = date('now') AND executed_by != 'manual'"
        ).fetchone()
        today_trades = row[0] if row else 0
        if today_trades >= MAX_TRADES_PER_DAY:
            logger.warning("Circuit breaker: max daily trades reached (%d)", MAX_TRADES_PER_DAY)
            return False

        # Check MAX_PORTFOLIO_EXPOSURE
        acct = conn.execute(
            "SELECT cash_balance, initial_balance FROM paper_account WHERE id = 1"
        ).fetchone()
        if acct:
            cash, initial = acct[0], acct[1]
            exposure = 1.0 - (cash / initial) if initial > 0 else 0
            if exposure >= MAX_PORTFOLIO_EXPOSURE:
                logger.warning(
                    "Circuit breaker: portfolio exposure %.1f%% >= %.1f%%",
                    exposure * 100, MAX_PORTFOLIO_EXPOSURE * 100,
                )
                return False

        # Check MAX_CONSECUTIVE_LOSSES
        recent = conn.execute(
            """SELECT action, price FROM transactions
               WHERE executed_by != 'manual'
               ORDER BY created_at DESC LIMIT ?""",
            (MAX_CONSECUTIVE_LOSSES,),
        ).fetchall()
        # Simple consecutive-loss detection placeholder
        if len(recent) >= MAX_CONSECUTIVE_LOSSES:
            # All recent are sells (liquidations) could signal losses
            all_sells = all(r[0] == "sell" for r in recent)
            if all_sells:
                logger.warning("Circuit breaker: %d consecutive sells detected", MAX_CONSECUTIVE_LOSSES)
                return False

        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Full cycle (all watchlist tickers)
# ---------------------------------------------------------------------------


def run_full_cycle():
    """Run the W.A.T.C.H. pipeline for all watchlist stocks."""
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
        "trades": sum(1 for r in results if r.get("executed")),
        "skipped": sum(1 for r in results if not r.get("executed")),
        "failed": sum(1 for r in results if not r.get("success")),
        "results": results,
    }
