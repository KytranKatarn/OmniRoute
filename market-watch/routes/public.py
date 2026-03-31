"""Public API routes — no authentication required."""

from flask import Blueprint, jsonify

from db import get_db

public_bp = Blueprint("public", __name__)


@public_bp.route("/api/public/track-record")
def track_record():
    """Return W.A.T.C.H. agent's paper trading performance summary."""
    conn = get_db()
    try:
        # Overall stats from paper account
        account = conn.execute(
            "SELECT cash_balance, initial_balance FROM paper_account WHERE id = 1"
        ).fetchone()

        # Recent completed cycles
        cycles = conn.execute(
            """SELECT COUNT(*) as total_cycles,
                      SUM(trades_made) as total_trades,
                      SUM(stocks_analyzed) as total_analyzed
               FROM cycle_log WHERE status = 'completed'"""
        ).fetchone()

        # Trade count
        sell_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM transactions WHERE action = 'sell'"
        ).fetchone()

        # Recent analyses (last 5)
        recent = conn.execute(
            """SELECT ticker, recommendation, director_sentiment,
                      director_confidence, oracle_confidence, created_at
               FROM analyses ORDER BY created_at DESC LIMIT 5"""
        ).fetchall()

        cash = account["cash_balance"] if account else 100000.0
        initial = account["initial_balance"] if account else 100000.0
        total_return = ((cash - initial) / initial) * 100 if initial > 0 else 0.0

        return jsonify({
            "success": True,
            "track_record": {
                "total_return_pct": round(total_return, 2),
                "cash_balance": round(cash, 2),
                "initial_balance": round(initial, 2),
                "total_trades": sell_count["cnt"] if sell_count else 0,
                "total_cycles": cycles["total_cycles"] or 0,
                "total_analyzed": cycles["total_analyzed"] or 0,
                "recent_calls": [
                    {
                        "ticker": r["ticker"],
                        "recommendation": r["recommendation"],
                        "sentiment": r["director_sentiment"],
                        "confidence": r["director_confidence"],
                        "oracle_confidence": r["oracle_confidence"],
                        "date": r["created_at"],
                    }
                    for r in recent
                ],
            },
        })
    finally:
        conn.close()
