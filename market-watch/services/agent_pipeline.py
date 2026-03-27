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
