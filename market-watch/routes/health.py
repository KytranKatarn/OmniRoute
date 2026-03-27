"""Health check endpoint for Market Watch."""

import os
from flask import Blueprint, jsonify
from db import get_db, DB_PATH

health_bp = Blueprint("health", __name__)


@health_bp.route("/api/health")
def health():
    """Health check with DB stats."""
    try:
        conn = get_db()
        watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        last_ingest = conn.execute(
            "SELECT source, status, created_at FROM ingest_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()

        db_size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0

        return jsonify({
            "status": "healthy",
            "service": "kytran-market-watch",
            "agent": "M.A.R.K.E.T.",
            "watchlist_count": watchlist_count,
            "last_ingest": {
                "source": last_ingest["source"],
                "status": last_ingest["status"],
                "timestamp": last_ingest["created_at"],
            } if last_ingest else None,
            "db_size_bytes": db_size,
        })
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500
