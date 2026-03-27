"""Agent analysis endpoints."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.agent_pipeline import run_pipeline, run_full_cycle

analysis_bp = Blueprint("analysis", __name__)


@analysis_bp.route("/api/analysis")
def list_analyses():
    """Get recent analyses."""
    ticker = request.args.get("ticker")
    limit = request.args.get("limit", 20, type=int)

    conn = get_db()
    if ticker:
        rows = conn.execute(
            "SELECT * FROM analyses WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
            (ticker.upper(), limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return jsonify({"success": True, "analyses": [dict(r) for r in rows]})


@analysis_bp.route("/api/analysis/run", methods=["POST"])
def run_analysis():
    """Run M.A.R.K.E.T. pipeline for a single ticker."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    if not ticker:
        return jsonify({"success": False, "error": "Ticker required"}), 400
    result = run_pipeline(ticker)
    return jsonify(result)


@analysis_bp.route("/api/analysis/cycle", methods=["POST"])
def run_cycle():
    """Run full M.A.R.K.E.T. cycle for all watchlist stocks."""
    result = run_full_cycle()
    return jsonify(result)


@analysis_bp.route("/api/analysis/cycles")
def list_cycles():
    """Get cycle history."""
    conn = get_db()
    cycles = conn.execute("SELECT * FROM cycle_log ORDER BY started_at DESC LIMIT 20").fetchall()
    conn.close()
    return jsonify({"success": True, "cycles": [dict(c) for c in cycles]})
