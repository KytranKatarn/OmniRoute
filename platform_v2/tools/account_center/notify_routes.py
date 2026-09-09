"""Internal notify endpoint — ``/tools/account-center/api/internal/notify`` (KBS calls this path).

#6657: this handler used to read ``ARCHIE_INTERNAL_KEY`` at IMPORT time (no rotation
without a restart), compare with ``!=`` and — when the variable was unset — accept
EVERY request. It now goes through the one scoped gate and the one notify body.
"""

import logging
import threading

from flask import jsonify, request

from services.internal_auth import require_internal_scope
from services.internal_notify import send_internal_notify

logger = logging.getLogger(__name__)


def register_notify_routes(bp):

    @bp.route("/api/internal/notify", methods=["POST"])
    @require_internal_scope("notify")
    def internal_notify():
        """Forward a message to Telegram. Called by KBS (kbs_signal, kbs_call_center)."""
        data = request.get_json(force=True, silent=True) or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "message is required"}), 400
        payload = {
            "title": (data.get("title") or "[KBS] Internal Notify"),
            "message": message,
            "priority": data.get("priority") or "normal",
            "source": data.get("source") or "kbs",
            "telegram": True,  # this path always spoke on Telegram; keep that contract
        }

        def _fire():
            try:
                send_internal_notify(payload, default_source="kbs", default_title="[KBS] Internal Notify")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[InternalNotify] delivery failed: %s", exc)

        threading.Thread(target=_fire, daemon=True).start()
        return jsonify({"ok": True})
