"""Backtest endpoints."""

import json
from flask import Blueprint, jsonify, request
from db import get_db
from services.backtest_engine import run_backtest
from auth import tier_required

backtest_bp = Blueprint("backtest", __name__)


@backtest_bp.route("/api/backtest/run", methods=["POST"])
@tier_required("ai")
def run():
    """Run a backtest."""
    data = request.get_json() or {}
    tickers = data.get("tickers", [])
    strategy = data.get("strategy", "sma_crossover")
    initial_capital = data.get("initial_capital", 100000)

    if not tickers:
        return jsonify({"success": False, "error": "Tickers required"}), 400

    result = run_backtest(tickers, strategy, initial_capital=initial_capital)

    # Save to DB
    if result["success"]:
        conn = get_db()
        for r in result.get("results", []):
            conn.execute(
                """INSERT INTO backtest_results (strategy, tickers, start_date, end_date, initial_capital,
                   final_value, total_return, sharpe_ratio, max_drawdown, win_rate, trade_count,
                   equity_curve, trade_log)
                   VALUES (?, ?, '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    strategy, r["ticker"], r["initial_capital"], r.get("final_value"),
                    r.get("total_return"), r.get("sharpe_ratio"), r.get("max_drawdown"),
                    r.get("win_rate"), r.get("trade_count"),
                    json.dumps(r.get("equity_curve", [])), json.dumps(r.get("trades", [])),
                ),
            )
        conn.commit()
        conn.close()

    return jsonify(result)


@backtest_bp.route("/api/backtest/results")
@tier_required("ai")
def results():
    """Get past backtest results."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM backtest_results ORDER BY created_at DESC LIMIT 20").fetchall()
    conn.close()
    return jsonify({"success": True, "results": [dict(r) for r in rows]})
