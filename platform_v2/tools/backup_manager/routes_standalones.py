"""Backup Manager — standalone products backup routes."""

import os
import threading
import logging
from datetime import datetime
from flask import jsonify, request
from psycopg2.extras import RealDictCursor
from tools.backup_manager._shared import (
    STANDALONE_PRODUCTS,
    backup_standalone,
    get_backup_db_cursor,
)

logger = logging.getLogger(__name__)


def register_standalone_routes(bp, admin_required):

    @bp.route("/api/standalones/list")
    @admin_required
    def list_standalones():
        """List all standalone products with their last backup info."""
        try:
            with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
                cur.execute(
                    """SELECT DISTINCT ON (standalone_name)
                         standalone_name, file_path, size_bytes, status, created_at
                       FROM backup_log
                       WHERE standalone_name IS NOT NULL
                       ORDER BY standalone_name, created_at DESC"""
                )
                last_backups = {r["standalone_name"]: r for r in cur.fetchall()}

            result = []
            for p in STANDALONE_PRODUCTS:
                last = last_backups.get(p["name"])
                last_name = os.path.basename(last["file_path"]) if last and last["file_path"] else None
                result.append(
                    {
                        "name": p["name"],
                        "display_name": p["display_name"],
                        "code_path": p["code_path"],
                        # .get(), not [] — gov_watch / civic_watch / legal_watch /
                        # market_watch dropped this key when they moved to the `db_kind`
                        # dispatcher, and ONE KeyError 500s the WHOLE list, so the tab
                        # rendered blank for all 9 products. `_shared.py` already reads it
                        # defensively (`product.get("db_schema")`, ~L1104); this call site
                        # was the one that didn't. Absent == None == "own DB" in the UI,
                        # which is what these four actually have — they hold no schema
                        # inside the hub database. (#5124)
                        "db_schema": p.get("db_schema"),
                        # Additive: the field that REPLACED db_schema for those four, so a
                        # caller can tell "own Postgres container" from "sqlite over mesh"
                        # instead of flattening both to "own DB".
                        "db_kind": p.get("db_kind"),
                        "backup_type": p["backup_type"],
                        "code_path_exists": os.path.exists(p["code_path"]),
                        "last_backup_name": last_name,
                        "last_backup_at": last["created_at"].isoformat() if last and last["created_at"] else None,
                        "last_backup_size_bytes": last["size_bytes"] if last else None,
                        "last_backup_status": last["status"] if last else None,
                    }
                )
            return jsonify({"success": True, "standalones": result})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/standalones/backup", methods=["POST"])
    @admin_required
    def backup_standalones():
        """Async backup for one or more standalones. Returns job_id immediately."""
        data = request.get_json() or {}
        names = data.get("standalone_names", [p["name"] for p in STANDALONE_PRODUCTS])
        invalid = [n for n in names if not any(p["name"] == n for p in STANDALONE_PRODUCTS)]
        if invalid:
            return jsonify({"success": False, "error": f"Unknown standalones: {invalid}"}), 400

        job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_standalone_" + os.urandom(4).hex()

        def _run():
            for name in names:
                try:
                    result = backup_standalone(name)
                    logger.info(
                        "Standalone backup %s: %s", name, "ok" if result["success"] else str(result.get("errors"))
                    )
                except Exception as e:
                    logger.error("Standalone backup %s error: %s", name, e)

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({"success": True, "job_id": job_id, "standalone_names": names})

    @bp.route("/api/standalones/history/<standalone_name>")
    @admin_required
    def standalone_backup_history(standalone_name):
        """Last 10 backups for a specific standalone."""
        try:
            with get_backup_db_cursor(commit=False, cursor_factory=RealDictCursor) as (conn, cur):
                cur.execute(
                    "SELECT file_path, size_bytes, status, created_at FROM backup_log "
                    "WHERE standalone_name = %s ORDER BY created_at DESC LIMIT 10",
                    (standalone_name,),
                )
                rows = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "history": rows})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
