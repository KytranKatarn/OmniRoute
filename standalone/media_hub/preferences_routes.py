"""Per-user preferences — key/value store (language, etc.)."""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from database import get_db_cursor

preferences_bp = Blueprint("preferences", __name__)

ALLOWED_KEYS = {"language"}
ALLOWED_VALUES = {"language": {"en", "fr", "es"}}


@preferences_bp.route("/api/preferences", methods=["GET"])
@login_required
def get_preferences():
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT key, value FROM user_preferences WHERE user_id = %s",
            (current_user.id,),
        )
        rows = cur.fetchall()
    return jsonify({r["key"]: r["value"] for r in rows})


@preferences_bp.route("/api/preferences", methods=["POST"])
@login_required
def set_preference():
    data = request.get_json(silent=True) or {}
    key = (data.get("key") or "").strip().lower()
    value = (data.get("value") or "").strip().lower()

    if key not in ALLOWED_KEYS:
        return jsonify({"error": f"Unknown preference key '{key}'"}), 400
    if key in ALLOWED_VALUES and value not in ALLOWED_VALUES[key]:
        return jsonify({"error": f"Invalid value '{value}' for '{key}'"}), 400

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO user_preferences (user_id, key, value)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value
            """,
            (current_user.id, key, value),
        )
    return jsonify({"saved": True, "key": key, "value": value})
