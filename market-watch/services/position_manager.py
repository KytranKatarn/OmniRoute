"""Position manager — open position lifecycle with 4 exit triggers."""

import json
import logging
from datetime import datetime, timedelta

from db import get_db
from services.market_data import get_quote
from services.alpaca_client import place_order
from services.portfolio_service import update_metrics_after_trade
from services import risk_config as rc

logger = logging.getLogger(__name__)


def check_price_exits():
    """Check open positions for stop-loss, target, and time expiry exits.

    Returns list of closed position summaries.
    """
    conn = get_db()
    closed = []
    try:
        positions = conn.execute(
            "SELECT * FROM open_positions WHERE status = 'open'"
        ).fetchall()

        for pos in positions:
            quote = get_quote(pos["ticker"])
            current_price = quote.get("price", 0)
            if current_price <= 0:
                logger.warning("Cannot get price for %s, skipping exit check", pos["ticker"])
                continue

            exit_reason = None

            # Trigger 1: Stop-loss
            if current_price <= pos["stop_loss"]:
                exit_reason = "stopped"
            # Trigger 2: Target hit
            elif current_price >= pos["target_price"]:
                exit_reason = "target_hit"
            # Trigger 3: Time expiry
            else:
                opened_at = datetime.fromisoformat(str(pos["opened_at"]))
                hold_days = (datetime.utcnow() - opened_at).days
                if hold_days >= pos["max_hold_days"]:
                    exit_reason = "expired"

            if exit_reason:
                result = _close_position(conn, pos, current_price, exit_reason)
                if result:
                    closed.append(result)

        conn.commit()
    finally:
        conn.close()

    return closed


def check_reeval_exits(cycle_analyses):
    """Check open positions against new analysis results.

    Args:
        cycle_analyses: list of dicts from run_full_cycle() results,
                       each with "ticker" and "recommendation"

    Returns list of closed position summaries.
    """
    analysis_map = {}
    for a in cycle_analyses:
        if a.get("ticker") and a.get("recommendation"):
            analysis_map[a["ticker"]] = a["recommendation"]

    conn = get_db()
    closed = []
    try:
        positions = conn.execute(
            "SELECT * FROM open_positions WHERE status = 'open'"
        ).fetchall()

        for pos in positions:
            rec = analysis_map.get(pos["ticker"])
            if rec in ("sell", "skip"):
                quote = get_quote(pos["ticker"])
                current_price = quote.get("price", pos["entry_price"])
                result = _close_position(conn, pos, current_price, "reeval")
                if result:
                    closed.append(result)

        conn.commit()
    finally:
        conn.close()

    return closed


def open_position(order, alpaca_order_id=None):
    """Record a new open position from an approved execution decision.

    Args:
        order: dict from ExecutionDecision.order
        alpaca_order_id: optional Alpaca order ID

    Returns position ID.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO open_positions
               (ticker, quantity, entry_price, stop_loss, target_price, max_hold_days, sector, thesis_id, alpaca_order_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order["ticker"],
                order["quantity"],
                order["price"],
                order["stop_loss"],
                order["target_price"],
                order.get("max_hold_days", rc.DEFAULT_HOLD_DAYS),
                order.get("sector"),
                order.get("thesis_id"),
                alpaca_order_id,
            ),
        )
        position_id = cur.lastrowid

        # Log entry in trade journal
        conn.execute(
            """INSERT INTO trade_journal
               (ticker, action, quantity, price, position_id, thesis_id, risk_gates_log)
               VALUES (?, 'buy', ?, ?, ?, ?, ?)""",
            (
                order["ticker"],
                order["quantity"],
                order["price"],
                position_id,
                order.get("thesis_id"),
                json.dumps(order.get("gates_log", [])),
            ),
        )

        # Deduct cash
        total_cost = order["quantity"] * order["price"]
        conn.execute(
            "UPDATE paper_account SET cash_balance = cash_balance - ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (total_cost,),
        )

        conn.commit()
        return position_id
    finally:
        conn.close()


def _close_position(conn, pos, sell_price, exit_reason):
    """Close a position (called within an existing connection/transaction).

    Returns summary dict or None on error.
    """
    ticker = pos["ticker"]
    quantity = pos["quantity"]
    entry_price = pos["entry_price"]

    pnl = (sell_price - entry_price) * quantity
    pnl_pct = ((sell_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0

    # Execute sell (unless dry run)
    if not rc.DRY_RUN:
        result = place_order(ticker, quantity, "sell")
        if not result.get("success"):
            logger.error("Failed to sell %s: %s", ticker, result.get("error"))
            return None
    else:
        logger.info("[DRY RUN] Would sell %d %s at %.2f (reason: %s)", quantity, ticker, sell_price, exit_reason)

    # Update position status
    conn.execute(
        "UPDATE open_positions SET status = ? WHERE id = ?",
        (exit_reason, pos["id"]),
    )

    # Log exit in trade journal
    conn.execute(
        """INSERT INTO trade_journal
           (ticker, action, quantity, price, position_id, thesis_id, exit_reason, pnl, pnl_pct)
           VALUES (?, 'sell', ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, quantity, sell_price, pos["id"], pos["thesis_id"], exit_reason, round(pnl, 2), round(pnl_pct, 2)),
    )

    # Return cash
    conn.execute(
        "UPDATE paper_account SET cash_balance = cash_balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (sell_price * quantity,),
    )

    # Update metrics
    update_metrics_after_trade(pnl)

    logger.info("Closed %s: %s %.2f → %.2f, P&L: $%.2f (%.1f%%), reason: %s",
                ticker, exit_reason, entry_price, sell_price, pnl, pnl_pct, exit_reason)

    return {
        "ticker": ticker,
        "exit_reason": exit_reason,
        "entry_price": entry_price,
        "sell_price": sell_price,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
    }
