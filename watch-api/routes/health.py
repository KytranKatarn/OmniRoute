"""GET /health — service health check."""
import os
from flask import Blueprint, jsonify
from db import get_db

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
def health():
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM civic_events"
        ).fetchone()
        last_ingest = conn.execute(
            "SELECT source, completed_at, status FROM ingest_log "
            "ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        conn.close()

        db_path = os.environ.get("WATCH_DB_PATH", "/app/data/watch.db")
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        return jsonify({
            "status": "ok",
            "service": "W.A.T.C.H. Civic API",
            "events_count": row["cnt"],
            "last_ingest": {
                "source": last_ingest["source"] if last_ingest else None,
                "completed_at": last_ingest["completed_at"] if last_ingest else None,
                "status": last_ingest["status"] if last_ingest else None,
            },
            "db_size_bytes": db_size,
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@health_bp.route("/ingest/federal", methods=["POST"])
def trigger_federal_ingest():
    try:
        from ingest.federal import run_federal_ingest
        result = run_federal_ingest()
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@health_bp.route("/ingest/provincial", methods=["POST"])
def trigger_provincial_ingest():
    try:
        from ingest.provincial import run_provincial_ingest
        result = run_provincial_ingest()
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@health_bp.route("/ingest/municipal", methods=["POST"])
def trigger_municipal_ingest():
    try:
        from ingest.municipal import run_municipal_ingest
        result = run_municipal_ingest()
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500
