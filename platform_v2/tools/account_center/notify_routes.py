"""Internal notify endpoint — accepts POST from standalone products and forwards to Telegram."""

import logging
import os
import threading

from flask import jsonify, request

logger = logging.getLogger(__name__)

_INTERNAL_KEY = os.getenv("ARCHIE_INTERNAL_KEY", "")


def register_notify_routes(bp):

    @bp.route("/api/internal/notify", methods=["POST"])
    def internal_notify():
        """Forward a message to Telegram. Called by KBS, media hub, etc."""
        key = request.headers.get("X-Internal-Key", "")
        if _INTERNAL_KEY and key != _INTERNAL_KEY:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

        data = request.get_json(force=True, silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "message is required"}), 400

        def _fire():
            try:
                from services.telegram_service import send_info

                send_info("[KBS] Internal Notify", message)
            except Exception as exc:
                logger.warning("[InternalNotify] Telegram send failed: %s", exc)

        threading.Thread(target=_fire, daemon=True).start()
        return jsonify({"ok": True})
