"""Portfolio and paper trading account endpoints."""

from flask import Blueprint, jsonify
from db import get_db
from services.market_data import get_quote
from services.alpaca_client import get_account, get_positions
from auth import tier_required

portfolio_bp = Blueprint("portfolio", __name__)


@portfolio_bp.route("/api/portfolio")
@tier_required("viewer")
def portfolio_overview():
    """Get portfolio positions with current P&L."""
    positions = get_positions()
    account = get_account()

    # Also get local transaction history
    conn = get_db()
    transactions = conn.execute(
        "SELECT * FROM portfolio ORDER BY opened_at DESC LIMIT 20"
    ).fetchall()

    return jsonify({
        "success": True,
        "account": account,
        "positions": positions,
        "recent_transactions": [dict(t) for t in transactions],
    })


@portfolio_bp.route("/api/portfolio/summary")
@tier_required("viewer")
def portfolio_summary():
    """Quick portfolio summary for dashboard."""
    account = get_account()
    positions = get_positions()

    total_pl = sum(p.get("unrealized_pl", 0) for p in positions)
    position_count = len(positions)

    return jsonify({
        "success": True,
        "portfolio_value": account.get("portfolio_value", 0),
        "cash": account.get("cash", 0),
        "total_unrealized_pl": round(total_pl, 2),
        "position_count": position_count,
        "configured": account.get("configured", False),
    })
