"""Per-user watchlist — save and retrieve media items."""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from database import get_db_cursor

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/api/watchlist", methods=["GET"])
@login_required
def list_watchlist():
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id, media_id, media_type, title, poster_url, year, added_at "
            "FROM user_watchlist WHERE user_id = %s ORDER BY added_at DESC",
            (current_user.id,),
        )
        rows = cur.fetchall()
    items = [
        {
            "id": r["id"],
            "media_id": r["media_id"],
            "media_type": r["media_type"],
            "title": r["title"],
            "poster_url": r["poster_url"],
            "year": r["year"],
            "added_at": r["added_at"].isoformat() if r["added_at"] else None,
        }
        for r in rows
    ]
    return jsonify({"items": items})


@watchlist_bp.route("/api/watchlist", methods=["POST"])
@login_required
def add_to_watchlist():
    data = request.get_json(silent=True) or {}
    media_id = (data.get("media_id") or "").strip()
    media_type = (data.get("media_type") or "").strip().lower()
    title = (data.get("title") or "").strip()
    poster_url = (data.get("poster_url") or "").strip() or None
    year = data.get("year")

    if not media_id or media_type not in ("movie", "tv") or not title:
        return jsonify({"error": "media_id, media_type (movie|tv), and title required"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO user_watchlist (user_id, media_id, media_type, title, poster_url, year)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id, media_id, media_type) DO NOTHING
            RETURNING id
            """,
            (current_user.id, media_id, media_type, title, poster_url, year),
        )
        row = cur.fetchone()

    if row:
        return jsonify({"id": row["id"], "added": True}), 201
    return jsonify({"added": False, "reason": "already in watchlist"}), 200


@watchlist_bp.route("/api/watchlist/<int:item_id>", methods=["DELETE"])
@login_required
def remove_from_watchlist(item_id):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM user_watchlist WHERE id = %s AND user_id = %s RETURNING id",
            (item_id, current_user.id),
        )
        deleted = cur.fetchone()
    if not deleted:
        return jsonify({"error": "not found"}), 404
    return jsonify({"removed": True})
