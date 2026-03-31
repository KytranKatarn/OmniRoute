"""Public API routes — no authentication required."""

from flask import Blueprint, jsonify

from db import get_db

public_bp = Blueprint("public", __name__)


@public_bp.route("/api/public/track-record")
def track_record():
    """Return W.A.T.C.H. agent's paper trading performance summary."""
    conn = get_db()
    try:
        # Portfolio metrics
        metrics = conn.execute(
            "SELECT peak_value, total_trades, winning_trades, total_pnl FROM portfolio_metrics WHERE id = 1"
        ).fetchone()

        # Paper account
        account = conn.execute(
            "SELECT cash_balance, initial_balance FROM paper_account WHERE id = 1"
        ).fetchone()

        cash = account["cash_balance"] if account else 100000.0
        initial = account["initial_balance"] if account else 100000.0
        total_trades = metrics["total_trades"] if metrics else 0
        winning_trades = metrics["winning_trades"] if metrics else 0
        total_pnl = metrics["total_pnl"] if metrics else 0.0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # Open positions value
        positions = conn.execute(
            "SELECT COUNT(*) as cnt FROM open_positions WHERE status = 'open'"
        ).fetchone()
        open_count = positions["cnt"] if positions else 0

        # Cycle stats
        cycles = conn.execute(
            """SELECT COUNT(*) as total_cycles, SUM(stocks_analyzed) as total_analyzed
               FROM cycle_log WHERE status = 'completed'"""
        ).fetchone()

        # Recent trades from journal (last 10)
        recent_trades = conn.execute(
            """SELECT ticker, action, quantity, price, exit_reason, pnl, pnl_pct, created_at
               FROM trade_journal ORDER BY created_at DESC LIMIT 10"""
        ).fetchall()

        # Recent analyses (last 5)
        recent_analyses = conn.execute(
            """SELECT ticker, recommendation, director_sentiment,
                      director_confidence, oracle_confidence, created_at
               FROM analyses ORDER BY created_at DESC LIMIT 5"""
        ).fetchall()

        total_return = ((cash + total_pnl - initial) / initial * 100) if initial > 0 else 0.0

        return jsonify({
            "success": True,
            "track_record": {
                "total_return_pct": round(total_return, 2),
                "cash_balance": round(cash, 2),
                "initial_balance": round(initial, 2),
                "total_pnl": round(total_pnl, 2),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate_pct": round(win_rate, 1),
                "open_positions": open_count,
                "total_cycles": cycles["total_cycles"] or 0,
                "total_analyzed": cycles["total_analyzed"] or 0,
                "recent_trades": [
                    {
                        "ticker": t["ticker"],
                        "action": t["action"],
                        "quantity": t["quantity"],
                        "price": t["price"],
                        "exit_reason": t["exit_reason"],
                        "pnl": t["pnl"],
                        "pnl_pct": t["pnl_pct"],
                        "date": t["created_at"],
                    }
                    for t in recent_trades
                ],
                "recent_calls": [
                    {
                        "ticker": r["ticker"],
                        "recommendation": r["recommendation"],
                        "sentiment": r["director_sentiment"],
                        "confidence": r["director_confidence"],
                        "oracle_confidence": r["oracle_confidence"],
                        "date": r["created_at"],
                    }
                    for r in recent_analyses
                ],
            },
        })
    finally:
        conn.close()
