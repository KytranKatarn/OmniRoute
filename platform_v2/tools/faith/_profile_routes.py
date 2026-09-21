"""Faith page + profile routes — index page, status, and user faith profile CRUD."""

from __future__ import annotations

import logging

from flask import Response, jsonify, render_template, request
from flask_login import current_user, login_required
from psycopg2 import Error as PsycopgError

from . import faith_bp, routes as _R
from ._constants import FAITH_AGENT_ID, JsonDict, JsonResponse

logger = logging.getLogger(__name__)


@faith_bp.route("/")
@login_required
def index() -> str:
    return render_template("tools/faith.html")


@faith_bp.route("/api/status")
@faith_bp.route("/api/faith/status")
@login_required
def status() -> Response:
    return jsonify(
        {
            "status": "online",
            "agent": "F.A.I.T.H.",
            "agent_id": FAITH_AGENT_ID,
            "bridge_available": _R.BRIDGE_AVAILABLE,
            "module": "faith",
        }
    )


@faith_bp.route("/api/profile", methods=["GET"])
@faith_bp.route("/api/faith/profile", methods=["GET"])
@login_required
def get_profile() -> JsonResponse:
    try:
        _R._ensure_tables()
        with _R.get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                SELECT user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                FROM faith_profiles
                WHERE user_id = %s
                """,
                (current_user.id,),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO faith_profiles (user_id)
                    VALUES (%s)
                    RETURNING user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                    """,
                    (current_user.id,),
                )
                row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to load profile")
        return jsonify({"success": False, "error": "Failed to load profile"}), 500

    return jsonify(
        {
            "success": True,
            "profile": {
                "user_id": _R._row_value(row, "user_id", 0),
                "tradition_preference": _R._row_value(row, "tradition_preference", 1, "christian"),
                "prayer_style": _R._row_value(row, "prayer_style", 2, "guided"),
                "scripture_translation": _R._row_value(row, "scripture_translation", 3, "web"),
                "updated_at": (
                    _R._row_value(row, "updated_at", 4).isoformat() if _R._row_value(row, "updated_at", 4) else None
                ),
            },
        }
    )


@faith_bp.route("/api/profile", methods=["POST"])
@faith_bp.route("/api/faith/profile", methods=["POST"])
@login_required
def save_profile() -> JsonResponse:
    data: JsonDict = request.get_json(force=True, silent=True) or {}
    tradition = (data.get("tradition_preference") or data.get("tradition") or "christian").strip().lower()
    prayer_style = (data.get("prayer_style") or "guided").strip().lower()
    translation = (data.get("scripture_translation") or "web").strip().lower()
    allowed_traditions = {
        "christian",
        "catholic",
        "orthodox",
        "protestant",
        "jewish",
        "muslim",
        "buddhist",
        "hindu",
        "interfaith",
        "unspecified",
    }
    if tradition not in allowed_traditions:
        return jsonify({"success": False, "error": "Unsupported tradition preference"}), 400

    try:
        _R._ensure_tables()
        with _R.get_db_cursor(commit=True) as (_conn, cur):
            cur.execute(
                """
                UPDATE faith_profiles
                SET tradition_preference = %s,
                    prayer_style = %s,
                    scripture_translation = %s,
                    updated_at = NOW()
                WHERE user_id = %s
                RETURNING user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                """,
                (tradition, prayer_style, translation, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO faith_profiles (
                        user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                    )
                    VALUES (%s, %s, %s, %s, NOW())
                    RETURNING user_id, tradition_preference, prayer_style, scripture_translation, updated_at
                    """,
                    (current_user.id, tradition, prayer_style, translation),
                )
                row = cur.fetchone()
    except PsycopgError:
        logger.exception("[Faith] Failed to save profile")
        return jsonify({"success": False, "error": "Failed to save profile"}), 500

    return jsonify(
        {
            "success": True,
            "profile": {
                "user_id": _R._row_value(row, "user_id", 0),
                "tradition_preference": _R._row_value(row, "tradition_preference", 1),
                "prayer_style": _R._row_value(row, "prayer_style", 2),
                "scripture_translation": _R._row_value(row, "scripture_translation", 3),
                "updated_at": (
                    _R._row_value(row, "updated_at", 4).isoformat() if _R._row_value(row, "updated_at", 4) else None
                ),
            },
        }
    )