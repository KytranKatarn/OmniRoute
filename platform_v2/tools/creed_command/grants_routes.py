"""C.R.E.E.D. Command — grants pipeline routes (P2, #3611).

CRUD over creed_grants (migration 412). All admin-only. Registered from
__init__.py via register_grants_routes(bp, admin_required).
"""

import logging

import psycopg2
from flask import jsonify, request
from flask_login import login_required

from database import get_db_cursor

logger = logging.getLogger(__name__)

_STATUSES = {"prospect", "drafting", "submitted", "awarded", "declined"}
# Columns a client may set on create/update.
_EDITABLE = (
    "title",
    "funder",
    "amount_cad",
    "deadline",
    "fit_score",
    "status",
    "url",
    "notes",
    "owner_agent",
    "mailbox_ref",
)


def _row_to_dict(r):
    d = dict(r)
    for k in ("created_at", "updated_at", "deadline"):
        if d.get(k) is not None and not isinstance(d[k], str):
            d[k] = d[k].isoformat()
    if d.get("amount_cad") is not None:
        d["amount_cad"] = float(d["amount_cad"])
    return d


def _clean(body):
    """Return a validated dict of editable fields present in body."""
    out = {}
    for k in _EDITABLE:
        if k not in body:
            continue
        v = body[k]
        if k == "status":
            v = (v or "").strip().lower()
            if v not in _STATUSES:
                continue
        elif k == "fit_score":
            try:
                v = int(v) if v not in (None, "") else None
            except (ValueError, TypeError):
                continue
            if v is not None and not (0 <= v <= 100):
                v = max(0, min(100, v))
        elif k in ("title", "funder", "url", "notes", "owner_agent", "mailbox_ref"):
            v = (v.strip() if isinstance(v, str) else v) or None
        elif k in ("amount_cad", "deadline"):
            v = v or None  # let psycopg2 cast; empty -> NULL
        out[k] = v
    return out


def register_grants_routes(bp, admin_required):
    @bp.route("/api/grants", methods=["GET"])
    @login_required
    @admin_required
    def grants_list():
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT * FROM creed_grants "
                    "ORDER BY deadline ASC NULLS LAST, fit_score DESC NULLS LAST, created_at DESC"
                )
                grants = [_row_to_dict(r) for r in cur.fetchall() or []]
            return jsonify({"grants": grants, "count": len(grants)})
        except Exception as e:
            logger.error("grants_list failed: %s", e)
            return jsonify({"grants": [], "count": 0, "error": "load failed"}), 500

    @bp.route("/api/grants", methods=["POST"])
    @login_required
    @admin_required
    def grants_create():
        body = request.get_json(silent=True) or {}
        fields = _clean(body)
        if not fields.get("title") or not fields.get("funder"):
            return jsonify({"error": "title and funder are required"}), 400
        fields.setdefault("status", "prospect")
        cols = list(fields.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    f"INSERT INTO creed_grants ({', '.join(cols)}) " f"VALUES ({placeholders}) RETURNING *",
                    [fields[c] for c in cols],
                )
                row = cur.fetchone()
            return jsonify(_row_to_dict(row)), 201
        except psycopg2.errors.UniqueViolation:
            return jsonify({"error": "a grant with this funder + title already exists"}), 409
        except Exception as e:
            logger.error("grants_create failed: %s", e)
            return jsonify({"error": "could not create grant (check amount/deadline format)"}), 400

    @bp.route("/api/grants/<int:grant_id>", methods=["PATCH"])
    @login_required
    @admin_required
    def grants_update(grant_id):
        body = request.get_json(silent=True) or {}
        fields = _clean(body)
        if not fields:
            return jsonify({"error": "no editable fields supplied"}), 400
        set_clause = ", ".join(f"{c} = %s" for c in fields) + ", updated_at = NOW()"
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    f"UPDATE creed_grants SET {set_clause} WHERE id = %s RETURNING *",
                    [fields[c] for c in fields] + [grant_id],
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"error": "grant not found"}), 404
            return jsonify(_row_to_dict(row))
        except psycopg2.errors.UniqueViolation:
            return jsonify({"error": "a grant with this funder + title already exists"}), 409
        except Exception as e:
            logger.error("grants_update failed: %s", e)
            return jsonify({"error": "could not update grant"}), 400

    @bp.route("/api/grants/<int:grant_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def grants_delete(grant_id):
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute("DELETE FROM creed_grants WHERE id = %s", (grant_id,))
                deleted = cur.rowcount
            if not deleted:
                return jsonify({"error": "grant not found"}), 404
            return jsonify({"deleted": grant_id})
        except Exception as e:
            logger.error("grants_delete failed: %s", e)
            return jsonify({"error": "could not delete grant"}), 500
