"""
Strategy Service — StockBot Phase 3
Automated trading strategies: create, list, delete, toggle, evaluate.
"""

import logging
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from database import get_db_cursor
from .market_data_service import get_quote, get_history, calculate_indicators

logger = logging.getLogger(__name__)

# ── Condition evaluators ─────────────────────────────────────────────────────

CONDITION_TYPES = {
    "rsi_below": lambda indicators, threshold: indicators.get("rsi", 50) < threshold,
    "rsi_above": lambda indicators, threshold: indicators.get("rsi", 50) > threshold,
    "price_above_sma": lambda indicators, threshold: indicators.get("price", 0)
    > indicators.get("sma_" + str(int(threshold)), 0),
    "price_below_sma": lambda indicators, threshold: indicators.get("price", 0)
    < indicators.get("sma_" + str(int(threshold)), 0),
    "macd_crossover": lambda indicators, threshold: indicators.get("macd_signal", "none") == "bullish",
    "price_change_above": lambda indicators, threshold: indicators.get("change_pct", 0) > threshold,
    "price_change_below": lambda indicators, threshold: indicators.get("change_pct", 0) < -threshold,
}


# ── CRUD ──────────────────────────────────────────────────────────────────────


def create_strategy(user_id: int, name: str, ticker: str, rules: dict) -> int:
    """Create a new strategy. rules = {conditions: [{type, threshold}], action: {type, shares}}"""
    ticker = ticker.upper().strip()
    with get_db_cursor(commit=True) as (conn, cur):
        import psycopg2.extras

        cur.execute(
            """
            INSERT INTO stock_strategies (user_id, name, ticker, rules, is_active)
            VALUES (%s, %s, %s, %s, TRUE)
            RETURNING id
            """,
            (user_id, name, ticker, psycopg2.extras.Json(rules)),
        )
        return cur.fetchone()[0]


def list_strategies(user_id: int) -> list:
    """List all strategies for a user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, name, ticker, rules, is_active, last_evaluated_at, created_at
            FROM stock_strategies
            WHERE user_id = %s
            ORDER BY created_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "ticker": r[2],
            "rules": r[3],
            "is_active": r[4],
            "last_evaluated_at": r[5].isoformat() if r[5] else None,
            "created_at": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


def delete_strategy(strategy_id: int, user_id: int) -> dict:
    """Delete a strategy (verifies ownership)."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM stock_strategies WHERE id = %s AND user_id = %s RETURNING id",
            (strategy_id, user_id),
        )
        deleted = cur.fetchone()
    if not deleted:
        return {"success": False, "error": "Strategy not found or not owned by user"}
    return {"success": True}


def toggle_strategy(strategy_id: int, user_id: int) -> dict:
    """Flip is_active for a strategy."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE stock_strategies
            SET is_active = NOT is_active
            WHERE id = %s AND user_id = %s
            RETURNING id, is_active
            """,
            (strategy_id, user_id),
        )
        row = cur.fetchone()
    if not row:
        return {"success": False, "error": "Strategy not found or not owned by user"}
    return {"success": True, "strategy_id": row[0], "is_active": row[1]}


# ── Evaluation engine ─────────────────────────────────────────────────────────


def _get_indicators_for_strategy(ticker: str) -> dict:
    """Fetch price + compute RSI, SMA20/50/200, MACD signal, change_pct."""
    quote = get_quote(ticker)
    price = quote.get("price") or 0
    change_pct = quote.get("change_pct") or 0

    indicators = {"price": float(price), "change_pct": float(change_pct)}

    try:
        ohlcv = get_history(ticker, period="1y")
        if ohlcv:
            ind = calculate_indicators(ohlcv, ["RSI(14)", "SMA(20)", "SMA(50)", "SMA(200)", "MACD(12,26,9)"])

            # RSI — last value
            rsi_data = ind.get("RSI(14)", [])
            if rsi_data:
                last = rsi_data[-1]
                indicators["rsi"] = float(last.get("value", last) if isinstance(last, dict) else last)

            # SMAs — last value of each
            for period in [20, 50, 200]:
                key = f"SMA({period})"
                sma_data = ind.get(key, [])
                if sma_data:
                    last = sma_data[-1]
                    val = float(last.get("value", last) if isinstance(last, dict) else last)
                    indicators[f"sma_{period}"] = val

            # MACD signal — compare macd_line vs signal_line at last point
            macd_data = ind.get("MACD(12,26,9)", [])
            if len(macd_data) >= 2:
                prev = macd_data[-2]
                curr = macd_data[-1]
                prev_hist = float(prev.get("histogram", 0) if isinstance(prev, dict) else 0)
                curr_hist = float(curr.get("histogram", 0) if isinstance(curr, dict) else 0)
                if curr_hist > 0 and prev_hist <= 0:
                    indicators["macd_signal"] = "bullish"
                elif curr_hist < 0 and prev_hist >= 0:
                    indicators["macd_signal"] = "bearish"
                else:
                    indicators["macd_signal"] = "none"
    except Exception as e:
        logger.warning(f"_get_indicators_for_strategy({ticker}) partial failure: {e}")

    return indicators


def evaluate_strategies() -> int:
    """
    Evaluate all active strategies. Called by APScheduler.
    Returns count of strategies evaluated.
    """
    from .trading_service import paper_buy, paper_sell

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, user_id, ticker, rules
                FROM stock_strategies
                WHERE is_active = TRUE
                ORDER BY ticker
                """
            )
            rows = cur.fetchall()
    except Exception as e:
        logger.error(f"evaluate_strategies: failed to load strategies: {e}")
        return 0

    if not rows:
        return 0

    # Group by ticker to minimise API calls
    ticker_cache: dict = {}
    evaluated = 0

    for strategy_id, user_id, ticker, rules in rows:
        try:
            if ticker not in ticker_cache:
                ticker_cache[ticker] = _get_indicators_for_strategy(ticker)
            indicators = ticker_cache[ticker]

            conditions = rules.get("conditions", [])
            action = rules.get("action", {})

            # Evaluate all conditions (AND logic)
            all_met = True
            for cond in conditions:
                ctype = cond.get("type")
                threshold = float(cond.get("threshold", 0))
                evaluator = CONDITION_TYPES.get(ctype)
                if evaluator is None:
                    logger.warning(f"Unknown condition type: {ctype}")
                    all_met = False
                    break
                if not evaluator(indicators, threshold):
                    all_met = False
                    break

            action_taken = "no_action"
            details: dict = {"indicators_snapshot": {k: v for k, v in indicators.items() if k != "macd_signal" or True}}

            if all_met and action:
                atype = action.get("type")
                shares = float(action.get("shares", 1))
                try:
                    if atype == "buy":
                        result = paper_buy(user_id, ticker, shares)
                        action_taken = "buy" if result.get("success") else "buy_failed"
                        details["result"] = result
                    elif atype == "sell":
                        result = paper_sell(user_id, ticker, shares)
                        action_taken = "sell" if result.get("success") else "sell_failed"
                        details["result"] = result
                    elif atype == "sell_all":
                        # Fetch current holding
                        with get_db_cursor() as (c2, cur2):
                            cur2.execute(
                                "SELECT shares FROM stock_portfolio WHERE user_id = %s AND ticker = %s",
                                (user_id, ticker),
                            )
                            pos = cur2.fetchone()
                        if pos and float(pos[0]) > 0:
                            result = paper_sell(user_id, ticker, float(pos[0]))
                            action_taken = "sell_all" if result.get("success") else "sell_all_failed"
                            details["result"] = result
                        else:
                            action_taken = "sell_all_skipped_no_position"
                except Exception as exec_err:
                    logger.error(f"Strategy {strategy_id} action execution error: {exec_err}")
                    action_taken = "execution_error"
                    details["error"] = str(exec_err)

            # Log + update timestamp
            import psycopg2.extras

            with get_db_cursor(commit=True) as (conn2, cur2):
                cur2.execute(
                    """
                    INSERT INTO stock_strategy_logs (strategy_id, action_taken, details)
                    VALUES (%s, %s, %s)
                    """,
                    (strategy_id, action_taken, psycopg2.extras.Json(details)),
                )
                cur2.execute(
                    "UPDATE stock_strategies SET last_evaluated_at = NOW() WHERE id = %s",
                    (strategy_id,),
                )
            evaluated += 1

        except Exception as e:
            logger.error(f"evaluate_strategies: error on strategy {strategy_id}: {e}")

    return evaluated
