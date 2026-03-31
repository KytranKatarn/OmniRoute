"""Agent analysis endpoints."""

import json

from flask import Blueprint, jsonify, request
from db import get_db
from services.agent_pipeline import run_pipeline, run_full_cycle
from auth import tier_required

analysis_bp = Blueprint("analysis", __name__)


@analysis_bp.route("/api/analysis")
@tier_required("viewer")
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
    return jsonify({"success": True, "analyses": [_parse_analysis_row(r) for r in rows]})


def _parse_analysis_row(row):
    """Convert a DB row to dict, parsing JSON columns."""
    d = dict(row)
    for col in ("value_report", "pulse_report", "oracle_synthesis", "market_execution"):
        if d.get(col) and isinstance(d[col], str):
            try:
                d[col] = json.loads(d[col])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


@analysis_bp.route("/api/analysis/<int:analysis_id>")
@tier_required("viewer")
def get_analysis(analysis_id):
    """Get a single analysis by ID, including all 6-agent report columns."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM analyses WHERE id = ?", (analysis_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"success": False, "error": "Analysis not found"}), 404
    return jsonify({"success": True, "analysis": _parse_analysis_row(row)})


@analysis_bp.route("/api/analysis/run", methods=["POST"])
@tier_required("ai")
def run_analysis():
    """Run M.A.R.K.E.T. pipeline for a single ticker."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    if not ticker:
        return jsonify({"success": False, "error": "Ticker required"}), 400
    result = run_pipeline(ticker)
    return jsonify(result)


@analysis_bp.route("/api/analysis/cycle", methods=["POST"])
@tier_required("ai")
def run_cycle():
    """Run full M.A.R.K.E.T. cycle for all watchlist stocks."""
    result = run_full_cycle()
    return jsonify(result)


@analysis_bp.route("/api/analysis/cycles")
@tier_required("viewer")
def list_cycles():
    """Get cycle history."""
    conn = get_db()
    cycles = conn.execute("SELECT * FROM cycle_log ORDER BY started_at DESC LIMIT 20").fetchall()
    conn.close()
    return jsonify({"success": True, "cycles": [dict(c) for c in cycles]})
