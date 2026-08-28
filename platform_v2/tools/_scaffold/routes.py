"""
[MODULE_NAME] Routes - ADMIN-ONLY
==================================
Main routes for the [MODULE_NAME] module.

Pattern: register_*_routes(bp, admin_required) for sub-route files (ADR-045).
"""

import logging

from flask import Blueprint, render_template, jsonify
from flask_login import login_required
from database import get_db_cursor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blueprint — RENAME 'scaffold' to your module name everywhere
# ---------------------------------------------------------------------------
scaffold_bp = Blueprint(
    "scaffold",
    __name__,
    url_prefix="/tools/scaffold",
    template_folder="templates",
)


# ============================================================================
# MAIN PAGE
# ============================================================================


@scaffold_bp.route("/")
@login_required
def index():
    """Render the main module page."""
    return render_template("tools/scaffold.html")


# ============================================================================
# API ENDPOINTS
# ============================================================================


@scaffold_bp.route("/api/status")
@login_required
def api_status():
    """Return module status — example API endpoint."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT 1")
            return jsonify({"ok": True, "message": "Module operational"})
    except Exception:
        logger.exception("Status check failed")
        return jsonify({"ok": False, "error": "Internal error"}), 500


@scaffold_bp.route("/api/data")
@login_required
def api_data():
    """Example data endpoint with DB access pattern."""
    try:
        with get_db_cursor() as (conn, cur):
            # Replace with your actual query
            cur.execute(
                """
                SELECT id, created_at
                FROM knowledge_base
                LIMIT 10
                """
            )
            rows = cur.fetchall()
            return jsonify({"ok": True, "data": rows})
    except Exception:
        logger.exception("Data fetch failed")
        return jsonify({"ok": False, "error": "Internal error"}), 500


# ============================================================================
# SUB-ROUTE REGISTRATION TEMPLATE
# ============================================================================
# Copy this into a new file (e.g. data_routes.py) for route splitting:
#
# def register_data_routes(bp, admin_required):
#     @bp.route("/api/data/items")
#     @admin_required
#     def data_items():
#         ...
