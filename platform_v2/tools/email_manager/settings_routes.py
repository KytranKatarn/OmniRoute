"""Email HQ — Slice 5 settings endpoints (drives the Mail HQ Settings modal).

GET  /api/email/settings  → current values for every tunable Smart Inbox knob.
POST /api/email/settings  → validate + persist a subset (notify/digest/quiet-hours/
                            digest time). Admin-only.
"""

from __future__ import annotations

import logging

from flask import jsonify, request
from flask_login import login_required

from . import mailhq_settings

logger = logging.getLogger(__name__)


def register_settings_routes(bp, admin_required):
    @bp.route("/api/email/settings", methods=["GET"])
    @login_required
    @admin_required
    def email_settings_get():
        return jsonify({"settings": mailhq_settings.get_all()})

    @bp.route("/api/email/settings", methods=["POST"])
    @login_required
    @admin_required
    def email_settings_post():
        data = request.get_json(silent=True) or {}
        result = mailhq_settings.set_many(data)
        # Always 200 — the {ok, errors} body conveys validation outcome (the client's
        # fetch helper throws on non-2xx, which would hide per-field errors).
        return jsonify(result), 200
