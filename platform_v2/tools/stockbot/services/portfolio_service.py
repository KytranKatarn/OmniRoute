"""
Portfolio Service — StockBot Phase 1
Handles watchlist, portfolio, transactions, and alerts.
"""

import logging
from datetime import datetime, timezone

import sys

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from database import get_db_cursor
from .market_data_service import get_quote

logger = logging.getLogger(__name__)


def get_watchlist(user_id: int) -> list:
    """Return watchlist for user, joined with latest cached prices."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT w.id, w.ticker, w.added_at, w.notes, w.alert_above, w.alert_below,
                   p.price, p.change_pct, p.cached_at
            FROM stock_watchlist w
            LEFT JOIN stock_price_cache p ON p.ticker = w.ticker
            WHERE w.user_id = %s
            ORDER BY w.added_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "ticker": r[1],
            "added_at": r[2].isoformat() if r[2] else None,
            "notes": r[3],
            "alert_above": float(r[4]) if r[4] else None,
            "alert_below": float(r[5]) if r[5] else None,
            "price": float(r[6]) if r[6] else None,
            "change_pct": float(r[7]) if r[7] else None,
            "price_updated": r[8].isoformat() if r[8] else None,
        }
        for r in rows
    ]


def add_to_watchlist(user_id: int, ticker: str, notes: str = None) -> dict:
    """Add ticker to watchlist and fetch an initial quote."""
    ticker = ticker.upper().strip()
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO stock_watchlist (user_id, ticker, notes)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, ticker) DO UPDATE SET notes = EXCLUDED.notes
            RETURNING id
            """,
            (user_id, ticker, notes),
        )
        row = cur.fetchone()
        wid = row[0] if row else None

    # Fetch initial quote in background (best-effort)
    try:
        get_quote(ticker)
    except Exception as e:
        logger.warning(f"add_to_watchlist: initial quote fetch failed for {ticker}: {e}")

    return {"id": wid, "ticker": ticker, "success": True}


def remove_from_watchlist(user_id: int, ticker: str) -> bool:
    """Remove ticker from user's watchlist."""
    ticker = ticker.upper().strip()
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM stock_watchlist WHERE user_id = %s AND ticker = %s",
            (user_id, ticker),
        )
        return cur.rowcount > 0


def get_portfolio(user_id: int) -> list:
    """Return portfolio holdings with current prices and P&L."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT po.id, po.ticker, po.shares, po.avg_cost, po.updated_at,
                   pc.price, pc.change_pct
            FROM stock_portfolio po
            LEFT JOIN stock_price_cache pc ON pc.ticker = po.ticker
            WHERE po.user_id = %s AND po.shares > 0
            ORDER BY po.ticker
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    holdings = []
    for r in rows:
        shares = float(r[2]) if r[2] else 0
        avg_cost = float(r[3]) if r[3] else 0
        current_price = float(r[5]) if r[5] else avg_cost
        cost_basis = shares * avg_cost
        market_value = shares * current_price
        pnl = market_value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis != 0 else 0

        holdings.append(
            {
                "id": r[0],
                "ticker": r[1],
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": current_price,
                "change_pct": float(r[6]) if r[6] else None,
                "cost_basis": round(cost_basis, 4),
                "market_value": round(market_value, 4),
                "pnl": round(pnl, 4),
                "pnl_pct": round(pnl_pct, 4),
                "updated_at": r[4].isoformat() if r[4] else None,
            }
        )
    return holdings


def record_transaction(
    user_id: int,
    ticker: str,
    action: str,
    shares: float,
    price: float,
    paper_trade: bool = True,
) -> dict:
    """Record a buy/sell transaction and update portfolio holding."""
    ticker = ticker.upper().strip()
    action = action.lower()
    if action not in ("buy", "sell"):
        return {"success": False, "error": "action must be buy or sell"}

    total = round(shares * price, 4)

    with get_db_cursor(commit=True) as (conn, cur):
        # Insert transaction
        cur.execute(
            """
            INSERT INTO stock_transactions (user_id, ticker, action, shares, price, total, paper_trade)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, ticker, action, shares, price, total, paper_trade),
        )
        txn_id = cur.fetchone()[0]

        if action == "buy":
            # Upsert portfolio: update avg_cost and shares
            cur.execute(
                """
                INSERT INTO stock_portfolio (user_id, ticker, shares, avg_cost, current_price, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, ticker) DO UPDATE SET
                    avg_cost = (
                        (stock_portfolio.shares * stock_portfolio.avg_cost + EXCLUDED.shares * EXCLUDED.avg_cost)
                        / (stock_portfolio.shares + EXCLUDED.shares)
                    ),
                    shares = stock_portfolio.shares + EXCLUDED.shares,
                    current_price = EXCLUDED.current_price,
                    updated_at = NOW()
                """,
                (user_id, ticker, shares, price, price),
            )
        elif action == "sell":
            cur.execute(
                """
                UPDATE stock_portfolio
                SET shares = GREATEST(shares - %s, 0), updated_at = NOW()
                WHERE user_id = %s AND ticker = %s
                """,
                (shares, user_id, ticker),
            )

    return {"success": True, "transaction_id": txn_id, "ticker": ticker, "action": action, "total": total}


def get_transactions(user_id: int, ticker: str = None, limit: int = 50) -> list:
    """Return transaction history for a user, optionally filtered by ticker."""
    with get_db_cursor() as (conn, cur):
        if ticker:
            cur.execute(
                """
                SELECT id, ticker, action, shares, price, total, paper_trade, executed_at
                FROM stock_transactions
                WHERE user_id = %s AND ticker = %s
                ORDER BY executed_at DESC LIMIT %s
                """,
                (user_id, ticker.upper().strip(), limit),
            )
        else:
            cur.execute(
                """
                SELECT id, ticker, action, shares, price, total, paper_trade, executed_at
                FROM stock_transactions
                WHERE user_id = %s
                ORDER BY executed_at DESC LIMIT %s
                """,
                (user_id, limit),
            )
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "ticker": r[1],
            "action": r[2],
            "shares": float(r[3]),
            "price": float(r[4]),
            "total": float(r[5]),
            "paper_trade": r[6],
            "executed_at": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]


def get_portfolio_summary(user_id: int) -> dict:
    """Aggregate portfolio: total value, cost basis, P&L, and allocation %."""
    holdings = get_portfolio(user_id)
    if not holdings:
        return {
            "total_value": 0,
            "total_cost": 0,
            "total_pnl": 0,
            "total_pnl_pct": 0,
            "holdings_count": 0,
            "holdings": [],
        }

    total_value = sum(h["market_value"] for h in holdings)
    total_cost = sum(h["cost_basis"] for h in holdings)
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost != 0 else 0

    # Add allocation %
    for h in holdings:
        h["allocation_pct"] = round(h["market_value"] / total_value * 100, 2) if total_value else 0

    return {
        "total_value": round(total_value, 4),
        "total_cost": round(total_cost, 4),
        "total_pnl": round(total_pnl, 4),
        "total_pnl_pct": round(total_pnl_pct, 4),
        "holdings_count": len(holdings),
        "holdings": holdings,
    }


def create_alert(user_id: int, ticker: str, condition: str, threshold: float) -> dict:
    """Create a price alert for a ticker."""
    ticker = ticker.upper().strip()
    valid_conditions = ("above", "below", "change_pct_up", "change_pct_down")
    if condition not in valid_conditions:
        return {"success": False, "error": f"condition must be one of {valid_conditions}"}

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO stock_alerts (user_id, ticker, condition, threshold)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, ticker, condition, threshold),
        )
        alert_id = cur.fetchone()[0]

    return {"success": True, "alert_id": alert_id, "ticker": ticker, "condition": condition, "threshold": threshold}


def get_alerts(user_id: int) -> list:
    """Return all alerts for a user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.ticker, a.condition, a.threshold, a.triggered, a.triggered_at, a.created_at,
                   p.price
            FROM stock_alerts a
            LEFT JOIN stock_price_cache p ON p.ticker = a.ticker
            WHERE a.user_id = %s
            ORDER BY a.created_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "ticker": r[1],
            "condition": r[2],
            "threshold": float(r[3]),
            "triggered": r[4],
            "triggered_at": r[5].isoformat() if r[5] else None,
            "created_at": r[6].isoformat() if r[6] else None,
            "current_price": float(r[7]) if r[7] else None,
        }
        for r in rows
    ]


def check_alerts() -> int:
    """Check untriggered alerts against cached prices. Mark triggered. Returns count triggered."""
    triggered_count = 0
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT a.id, a.ticker, a.condition, a.threshold, p.price, p.change_pct
            FROM stock_alerts a
            JOIN stock_price_cache p ON p.ticker = a.ticker
            WHERE a.triggered = FALSE
            """
        )
        alerts = cur.fetchall()

    to_trigger = []
    for alert_id, ticker, condition, threshold, price, change_pct in alerts:
        if price is None:
            continue
        price = float(price)
        threshold = float(threshold)
        fire = False
        if condition == "above" and price >= threshold:
            fire = True
        elif condition == "below" and price <= threshold:
            fire = True
        elif condition == "change_pct_up" and change_pct is not None and float(change_pct) >= threshold:
            fire = True
        elif condition == "change_pct_down" and change_pct is not None and float(change_pct) <= -threshold:
            fire = True
        if fire:
            to_trigger.append(alert_id)

    if to_trigger:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE stock_alerts SET triggered = TRUE, triggered_at = NOW() WHERE id = ANY(%s)",
                (to_trigger,),
            )
            triggered_count = cur.rowcount

    return triggered_count
