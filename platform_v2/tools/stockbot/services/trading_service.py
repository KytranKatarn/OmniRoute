"""
Trading Service — StockBot Phase 3
Handles paper trading: accounts, buy/sell, PnL, and account reset.
"""

import logging
import sys

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from database import get_db_cursor
from .market_data_service import get_quote

logger = logging.getLogger(__name__)


def get_or_create_paper_account(user_id: int) -> dict:
    """Return existing paper account or create a new $100K account."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT balance, starting_balance FROM stock_paper_accounts WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            return {"balance": float(row[0]), "starting_balance": float(row[1])}
        cur.execute(
            """
            INSERT INTO stock_paper_accounts (user_id, balance, starting_balance)
            VALUES (%s, 100000, 100000)
            RETURNING balance, starting_balance
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return {"balance": float(row[0]), "starting_balance": float(row[1])}


def paper_buy(user_id: int, ticker: str, shares: float) -> dict:
    """Buy shares in the paper account."""
    ticker = ticker.upper().strip()
    quote = get_quote(ticker)
    price = quote.get("price")
    if price is None:
        return {"success": False, "error": f"Could not fetch price for {ticker}"}

    total = float(shares) * float(price)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT balance FROM stock_paper_accounts WHERE user_id = %s FOR UPDATE",
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            # auto-create
            cur.execute(
                "INSERT INTO stock_paper_accounts (user_id, balance, starting_balance) VALUES (%s, 100000, 100000) RETURNING balance",
                (user_id,),
            )
            row = cur.fetchone()

        balance = float(row[0])
        if balance < total:
            return {
                "success": False,
                "error": f"Insufficient funds. Need ${total:.2f}, have ${balance:.2f}",
            }

        new_balance = balance - total
        cur.execute(
            "UPDATE stock_paper_accounts SET balance = %s WHERE user_id = %s",
            (new_balance, user_id),
        )

        # Record transaction
        cur.execute(
            """
            INSERT INTO stock_transactions (user_id, ticker, action, shares, price, total, paper_trade)
            VALUES (%s, %s, 'buy', %s, %s, %s, TRUE)
            RETURNING id, executed_at
            """,
            (user_id, ticker, shares, price, total),
        )
        tx = cur.fetchone()
        tx_id, executed_at = tx[0], tx[1]

        # UPSERT portfolio
        cur.execute(
            """
            INSERT INTO stock_portfolio (user_id, ticker, shares, avg_cost, current_price)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id, ticker) DO UPDATE SET
                avg_cost = (stock_portfolio.avg_cost * stock_portfolio.shares + EXCLUDED.avg_cost * EXCLUDED.shares)
                           / (stock_portfolio.shares + EXCLUDED.shares),
                shares = stock_portfolio.shares + EXCLUDED.shares,
                current_price = EXCLUDED.current_price,
                updated_at = NOW()
            """,
            (user_id, ticker, shares, price, price),
        )

    return {
        "success": True,
        "balance": new_balance,
        "transaction": {
            "id": tx_id,
            "ticker": ticker,
            "action": "buy",
            "shares": float(shares),
            "price": float(price),
            "total": total,
            "executed_at": executed_at.isoformat() if executed_at else None,
        },
    }


def paper_sell(user_id: int, ticker: str, shares: float) -> dict:
    """Sell shares from the paper account."""
    ticker = ticker.upper().strip()

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT shares, avg_cost FROM stock_portfolio WHERE user_id = %s AND ticker = %s FOR UPDATE",
            (user_id, ticker),
        )
        pos = cur.fetchone()
        if not pos or float(pos[0]) < float(shares):
            held = float(pos[0]) if pos else 0
            return {
                "success": False,
                "error": f"Insufficient shares. Have {held}, trying to sell {shares}",
            }

        held_shares = float(pos[0])
        avg_cost = float(pos[1])

        quote = get_quote(ticker)
        price = quote.get("price")
        if price is None:
            return {"success": False, "error": f"Could not fetch price for {ticker}"}

        total = float(shares) * float(price)
        realized_pnl = (float(price) - avg_cost) * float(shares)

        # Update balance
        cur.execute(
            "UPDATE stock_paper_accounts SET balance = balance + %s WHERE user_id = %s RETURNING balance",
            (total, user_id),
        )
        bal_row = cur.fetchone()
        new_balance = float(bal_row[0]) if bal_row else None

        # Record transaction
        cur.execute(
            """
            INSERT INTO stock_transactions (user_id, ticker, action, shares, price, total, paper_trade)
            VALUES (%s, %s, 'sell', %s, %s, %s, TRUE)
            RETURNING id, executed_at
            """,
            (user_id, ticker, shares, price, total),
        )
        tx = cur.fetchone()
        tx_id, executed_at = tx[0], tx[1]

        # Update or remove portfolio position
        remaining = held_shares - float(shares)
        if remaining <= 0:
            cur.execute(
                "DELETE FROM stock_portfolio WHERE user_id = %s AND ticker = %s",
                (user_id, ticker),
            )
        else:
            cur.execute(
                "UPDATE stock_portfolio SET shares = %s, current_price = %s, updated_at = NOW() WHERE user_id = %s AND ticker = %s",
                (remaining, price, user_id, ticker),
            )

    return {
        "success": True,
        "balance": new_balance,
        "realized_pnl": realized_pnl,
        "transaction": {
            "id": tx_id,
            "ticker": ticker,
            "action": "sell",
            "shares": float(shares),
            "price": float(price),
            "total": total,
            "executed_at": executed_at.isoformat() if executed_at else None,
        },
    }


def get_pnl_summary(user_id: int) -> dict:
    """Return PnL summary for the paper account."""
    account = get_or_create_paper_account(user_id)
    balance = account["balance"]
    starting = account["starting_balance"]

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT ticker, shares, avg_cost, current_price FROM stock_portfolio WHERE user_id = %s AND shares > 0",
            (user_id,),
        )
        positions = cur.fetchall()

    position_value = 0.0
    unrealized_pnl = 0.0
    position_details = []

    for ticker, shares, avg_cost, current_price in positions:
        shares = float(shares)
        avg_cost = float(avg_cost)
        # Try to get fresh price; fall back to stored current_price
        if current_price:
            price = float(current_price)
        else:
            quote = get_quote(ticker)
            price = quote.get("price") or avg_cost

        market_value = shares * price
        position_value += market_value
        unr = (price - avg_cost) * shares
        unrealized_pnl += unr
        position_details.append(
            {
                "ticker": ticker,
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": price,
                "market_value": market_value,
                "unrealized_pnl": unr,
            }
        )

    total_value = balance + position_value
    total_return = total_value - starting
    total_return_pct = (total_return / starting * 100) if starting else 0.0

    return {
        "balance": balance,
        "starting_balance": starting,
        "position_value": position_value,
        "total_value": total_value,
        "unrealized_pnl": unrealized_pnl,
        "realized_pnl": total_return - unrealized_pnl,
        "total_return": total_return,
        "total_return_pct": total_return_pct,
        "positions": position_details,
    }


def reset_paper_account(user_id: int) -> dict:
    """Reset paper account to $100K and clear all positions/transactions."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE stock_paper_accounts SET balance = 100000, starting_balance = 100000 WHERE user_id = %s",
            (user_id,),
        )
        cur.execute(
            "DELETE FROM stock_portfolio WHERE user_id = %s",
            (user_id,),
        )
        cur.execute(
            "DELETE FROM stock_transactions WHERE user_id = %s AND paper_trade = TRUE",
            (user_id,),
        )
    return {"success": True, "balance": 100000.0}
