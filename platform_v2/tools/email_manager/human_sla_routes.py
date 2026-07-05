"""Email HQ — per-human-agent reply SLA dashboard route (#3282).

Distinct from sla_routes.py (which is per-MAILBOX read-latency): this surfaces per-HUMAN-AGENT
reply-time metrics captured in email_reply_events.
"""

from __future__ import annotations

import logging

from flask import jsonify, request
from flask_login import current_user, login_required

from .access_control import get_visible_mailbox_ids
from .human_sla_service import per_agent_stats

logger = logging.getLogger(__name__)


def register_human_sla_routes(bp, access_required) -> None:
    @bp.route("/api/email/human-sla/stats", methods=["GET"])
    @login_required
    @access_required
    def email_human_sla_stats():
        """Per-human-agent reply SLA for the look-back window.

        Query params: days = 7 | 30 | 90 (default 7).
        Returns {sla_target_hours, days, agents:[{agent_id, agent_name, address,
        reply_count, avg_response_seconds, avg_response_display, within_sla_pct,
        open_threads, inbound_count, reply_rate_pct}]}. Scoped to the caller's visible mailboxes.
        """
        try:
            days = int(request.args.get("days", 7))
        except (ValueError, TypeError):
            days = 7
        if days not in (7, 30, 90):
            days = 7

        visible = get_visible_mailbox_ids(current_user)
        try:
            data = per_agent_stats(days=days, visible_mailbox_ids=visible)
        except Exception as exc:
            logger.error("[human-sla] stats failed: %s", exc)
            return jsonify({"error": "stats unavailable"}), 500
        return jsonify(data)
