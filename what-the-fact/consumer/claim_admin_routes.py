"""WTF Consumer — Admin CRUD for Election Claim Tracker (#3013)."""
import logging

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from .routes import _db, _schema

claim_admin_bp = Blueprint("claim_admin", __name__)
logger = logging.getLogger(__name__)


def _require_admin():
    """Owner's logged-in session OR a matching X-Admin-Key; fail-closed (see auth.admin_gate).
    Replaces the old allow-if-unset gate (#4216)."""
    from .auth import admin_gate
    return admin_gate()


# ───────────────────────────────────────────────────────────────────────────
# GET /admin/claims — list all claims, optional ?mp_id= and ?status= filters
# ───────────────────────────────────────────────────────────────────────────

@claim_admin_bp.get("/admin/claims")
def list_claims():
    err = _require_admin()
    if err:
        return err

    mp_id = request.args.get("mp_id", type=int)
    status = request.args.get("status")
    S = _schema()

    where_clauses = []
    params = {}
    if mp_id is not None:
        where_clauses.append("mp_id = :mp_id")
        params["mp_id"] = mp_id
    if status:
        where_clauses.append("status = :status")
        params["status"] = status

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        with _db().begin() as c:
            rows = c.execute(
                text(
                    f"""
                    SELECT id, mp_id, politician_slug, politician_name,
                           claim_text, claim_date, source_url, status,
                           verdict_summary, article_ids, created_at, updated_at
                    FROM {S}.claim_tracker
                    {where_sql}
                    ORDER BY created_at DESC
                    LIMIT 500
                    """
                ),
                params,
            ).mappings().all()
        claims = []
        for r in rows:
            d = dict(r)
            if d.get("claim_date"):
                d["claim_date"] = str(d["claim_date"])
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            if d.get("updated_at"):
                d["updated_at"] = d["updated_at"].isoformat()
            claims.append(d)
        return jsonify({"claims": claims, "count": len(claims)})
    except Exception:
        logger.exception("claim_tracker list failed")
        return jsonify({"error": "DB error"}), 500


# ───────────────────────────────────────────────────────────────────────────
# POST /admin/claims — create a new claim
# ───────────────────────────────────────────────────────────────────────────

@claim_admin_bp.post("/admin/claims")
def create_claim():
    err = _require_admin()
    if err:
        return err

    body = request.get_json(force=True, silent=True) or {}
    required = ("mp_id", "politician_slug", "politician_name", "claim_text")
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing required fields: {missing}"}), 400

    S = _schema()
    try:
        with _db().begin() as c:
            row = c.execute(
                text(
                    f"""
                    INSERT INTO {S}.claim_tracker
                        (mp_id, politician_slug, politician_name, claim_text,
                         claim_date, source_url, status, verdict_summary, article_ids)
                    VALUES
                        (:mp_id, :politician_slug, :politician_name, :claim_text,
                         :claim_date, :source_url, :status, :verdict_summary, :article_ids)
                    RETURNING id, created_at
                    """
                ),
                {
                    "mp_id": body["mp_id"],
                    "politician_slug": body["politician_slug"],
                    "politician_name": body["politician_name"],
                    "claim_text": body["claim_text"],
                    "claim_date": body.get("claim_date"),
                    "source_url": body.get("source_url"),
                    "status": body.get("status", "pending"),
                    "verdict_summary": body.get("verdict_summary"),
                    "article_ids": body.get("article_ids"),
                },
            ).mappings().first()
        return jsonify({"id": row["id"], "created_at": row["created_at"].isoformat()}), 201
    except Exception:
        logger.exception("claim_tracker create failed")
        return jsonify({"error": "DB error"}), 500


# ───────────────────────────────────────────────────────────────────────────
# PUT /admin/claims/<id> — update any field
# ───────────────────────────────────────────────────────────────────────────

@claim_admin_bp.put("/admin/claims/<int:claim_id>")
def update_claim(claim_id: int):
    err = _require_admin()
    if err:
        return err

    body = request.get_json(force=True, silent=True) or {}
    allowed = {
        "politician_slug", "politician_name", "claim_text", "claim_date",
        "source_url", "status", "verdict_summary", "article_ids",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        return jsonify({"error": "No updatable fields provided"}), 400

    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["claim_id"] = claim_id
    updates["updated_at_val"] = "NOW()"
    S = _schema()

    try:
        with _db().begin() as c:
            result = c.execute(
                text(
                    f"""
                    UPDATE {S}.claim_tracker
                    SET {set_clauses}, updated_at = NOW()
                    WHERE id = :claim_id
                    RETURNING id
                    """
                ),
                updates,
            ).mappings().first()
        if not result:
            return jsonify({"error": "Claim not found"}), 404
        return jsonify({"id": result["id"], "updated": True})
    except Exception:
        logger.exception("claim_tracker update failed for id=%s", claim_id)
        return jsonify({"error": "DB error"}), 500


# ───────────────────────────────────────────────────────────────────────────
# DELETE /admin/claims/<id> — soft-delete (set status='contested')
# ───────────────────────────────────────────────────────────────────────────

@claim_admin_bp.delete("/admin/claims/<int:claim_id>")
def delete_claim(claim_id: int):
    err = _require_admin()
    if err:
        return err

    S = _schema()
    try:
        with _db().begin() as c:
            result = c.execute(
                text(
                    f"""
                    UPDATE {S}.claim_tracker
                    SET status = 'contested', updated_at = NOW()
                    WHERE id = :id
                    RETURNING id
                    """
                ),
                {"id": claim_id},
            ).mappings().first()
        if not result:
            return jsonify({"error": "Claim not found"}), 404
        return jsonify({"id": result["id"], "status": "contested"})
    except Exception:
        logger.exception("claim_tracker soft-delete failed for id=%s", claim_id)
        return jsonify({"error": "DB error"}), 500


# ───────────────────────────────────────────────────────────────────────────
# GET /admin/claims/mp/<slug> — all claims for a politician slug
# ───────────────────────────────────────────────────────────────────────────

@claim_admin_bp.get("/admin/claims/mp/<slug>")
def claims_by_slug(slug: str):
    err = _require_admin()
    if err:
        return err

    S = _schema()
    try:
        with _db().begin() as c:
            rows = c.execute(
                text(
                    f"""
                    SELECT id, mp_id, politician_slug, politician_name,
                           claim_text, claim_date, source_url, status,
                           verdict_summary, article_ids, created_at, updated_at
                    FROM {S}.claim_tracker
                    WHERE politician_slug = :slug
                    ORDER BY created_at DESC
                    """
                ),
                {"slug": slug},
            ).mappings().all()
        claims = []
        for r in rows:
            d = dict(r)
            if d.get("claim_date"):
                d["claim_date"] = str(d["claim_date"])
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            if d.get("updated_at"):
                d["updated_at"] = d["updated_at"].isoformat()
            claims.append(d)
        return jsonify({"slug": slug, "claims": claims, "count": len(claims)})
    except Exception:
        logger.exception("claim_tracker by-slug failed for slug=%s", slug)
        return jsonify({"error": "DB error"}), 500
