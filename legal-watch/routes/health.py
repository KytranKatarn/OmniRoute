"""GET /health and ingestion triggers."""
import os
from flask import Blueprint, jsonify
from db import get_db

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
def health():
    try:
        conn = get_db()
        events = conn.execute("SELECT COUNT(*) as c FROM legal_events").fetchone()["c"]
        regs = conn.execute("SELECT COUNT(*) as c FROM regulations").fetchone()["c"]
        last = conn.execute(
            "SELECT source, completed_at, status FROM ingest_log ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        db_path = os.environ.get("LEGAL_DB_PATH", "/app/data/legal.db")
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        conn.close()
        return jsonify({
            "status": "ok",
            "service": "Kytran Legal Watch",
            "agent": "G.A.V.E.L.",
            "events_count": events,
            "regulations_count": regs,
            "last_ingest": {
                "source": last["source"] if last else None,
                "completed_at": last["completed_at"] if last else None,
                "status": last["status"] if last else None,
            },
            "db_size_bytes": db_size,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@health_bp.route("/ingest/gazette", methods=["POST"])
def trigger_gazette():
    try:
        from ingest.gazette import run_gazette_ingest
        result = run_gazette_ingest()
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@health_bp.route("/ingest/news", methods=["POST"])
def trigger_news():
    try:
        from ingest.legal_news import run_legal_news_ingest
        result = run_legal_news_ingest()
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
