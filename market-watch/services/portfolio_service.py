"""Portfolio service — computes portfolio state, P&L, drawdown on demand."""

import logging
from datetime import date

from db import get_db
from services.market_data import get_quote

logger = logging.getLogger(__name__)


def get_portfolio_state():
    """Compute current portfolio state including unrealized P&L.

    Returns dict with: cash, portfolio_value, daily_pnl, drawdown_pct,
    open_positions_count, peak_value, total_trades, winning_trades, win_rate, total_pnl.
    """
    conn = get_db()
    try:
        account = conn.execute(
            "SELECT cash_balance, initial_balance FROM paper_account WHERE id = 1"
        ).fetchone()
        cash = account["cash_balance"] if account else 100000.0
        initial = account["initial_balance"] if account else 100000.0

        positions = conn.execute(
            "SELECT ticker, quantity, entry_price, sector FROM open_positions WHERE status = 'open'"
        ).fetchall()

        unrealized = 0.0
        position_details = []
        for pos in positions:
            quote = get_quote(pos["ticker"])
            current_price = quote.get("price", pos["entry_price"])
            pos_pnl = (current_price - pos["entry_price"]) * pos["quantity"]
            unrealized += pos_pnl
            position_details.append({
                "ticker": pos["ticker"],
                "quantity": pos["quantity"],
                "entry_price": pos["entry_price"],
                "current_price": current_price,
                "pnl": round(pos_pnl, 2),
                "sector": pos["sector"],
            })

        portfolio_value = cash + sum(
            p["current_price"] * p["quantity"] for p in position_details
        ) if position_details else cash

        today = date.today().isoformat()
        daily_row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) as daily_pnl FROM trade_journal WHERE date(created_at) = ?",
            (today,),
        ).fetchone()
        daily_realized = daily_row["daily_pnl"] if daily_row else 0.0
        daily_pnl = daily_realized + unrealized

        metrics = conn.execute(
            "SELECT peak_value, total_trades, winning_trades, total_pnl FROM portfolio_metrics WHERE id = 1"
        ).fetchone()
        peak_value = metrics["peak_value"] if metrics else initial
        total_trades = metrics["total_trades"] if metrics else 0
        winning_trades = metrics["winning_trades"] if metrics else 0
        total_pnl = metrics["total_pnl"] if metrics else 0.0

        if portfolio_value > peak_value:
            peak_value = portfolio_value
            conn.execute(
                "UPDATE portfolio_metrics SET peak_value = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (peak_value,),
            )
            conn.commit()

        drawdown_pct = ((peak_value - portfolio_value) / peak_value * 100) if peak_value > 0 else 0.0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        return {
            "cash": round(cash, 2),
            "initial_balance": round(initial, 2),
            "portfolio_value": round(portfolio_value, 2),
            "unrealized_pnl": round(unrealized, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round((daily_pnl / portfolio_value * 100) if portfolio_value > 0 else 0.0, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "peak_value": round(peak_value, 2),
            "total_return_pct": round(((portfolio_value - initial) / initial * 100) if initial > 0 else 0.0, 2),
            "open_positions_count": len(positions),
            "open_positions": position_details,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
        }
    finally:
        conn.close()


def update_metrics_after_trade(pnl):
    """Update portfolio_metrics after a trade closes."""
    conn = get_db()
    try:
        is_win = 1 if pnl > 0 else 0
        conn.execute(
            """UPDATE portfolio_metrics SET
                total_trades = total_trades + 1,
                winning_trades = winning_trades + ?,
                total_pnl = total_pnl + ?,
                updated_at = CURRENT_TIMESTAMP
               WHERE id = 1""",
            (is_win, pnl),
        )
        conn.commit()
    finally:
        conn.close()


def get_sector_counts():
    """Return dict of sector -> open position count."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT sector, COUNT(*) as cnt FROM open_positions WHERE status = 'open' AND sector IS NOT NULL GROUP BY sector"
        ).fetchall()
        return {row["sector"]: row["cnt"] for row in rows}
    finally:
        conn.close()
