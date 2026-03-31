"""Alert CRUD endpoints."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.alert_engine import check_alerts
from auth import tier_required

alerts_bp = Blueprint("alerts", __name__)


@alerts_bp.route("/api/alerts")
@tier_required("viewer")
def list_alerts():
    """Get all alerts."""
    conn = get_db()
    alerts = conn.execute("SELECT * FROM alerts ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify({"success": True, "alerts": [dict(a) for a in alerts]})


@alerts_bp.route("/api/alerts", methods=["POST"])
@tier_required("ai")
def create_alert():
    """Create a new alert."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    alert_type = data.get("alert_type", "price_above")
    threshold = data.get("threshold")
    message = data.get("message", "")

    if not ticker or threshold is None:
        return jsonify({"success": False, "error": "Ticker and threshold required"}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO alerts (ticker, alert_type, threshold, message) VALUES (?, ?, ?, ?)",
        (ticker, alert_type, threshold, message),
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True, "ticker": ticker, "alert_type": alert_type})


@alerts_bp.route("/api/alerts/<int:alert_id>", methods=["DELETE"])
@tier_required("ai")
def delete_alert(alert_id):
    """Delete an alert."""
    conn = get_db()
    conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@alerts_bp.route("/api/alerts/check", methods=["POST"])
@tier_required("ai")
def trigger_check():
    """Manually check all alerts."""
    triggered = check_alerts()
    return jsonify({"success": True, "triggered": triggered, "count": len(triggered)})
