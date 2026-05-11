"""Email HQ — Phase 6 email rules CRUD routes."""

from __future__ import annotations

import logging

from database import get_db_cursor
from flask import jsonify, request
from flask_login import login_required

logger = logging.getLogger(__name__)

_VALID_FIELDS = {"from_address", "subject", "to_address", "body_preview"}
_VALID_OPS = {"contains", "not_contains", "equals", "starts_with", "ends_with"}
_VALID_ACTIONS = {"set_priority", "archive", "star", "skip_triage"}
_VALID_PRIORITIES = {"action", "review", "info"}


def register_email_rules_routes(bp, admin_required):

    @bp.route("/api/email/rules", methods=["GET"])
    @login_required
    @admin_required
    def email_list_rules():
        """List all email rules."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT r.id, r.name, r.mailbox_id, mb.address AS mailbox_address,
                          r.condition_field, r.condition_op, r.condition_value,
                          r.action_type, r.action_value, r.is_active, r.created_at
                   FROM email_rules r
                   LEFT JOIN email_mailboxes mb ON mb.id = r.mailbox_id
                   ORDER BY r.id"""
            )
            rules = []
            for row in cur.fetchall():
                r = dict(row)
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
                rules.append(r)
        return jsonify({"rules": rules})

    @bp.route("/api/email/rules", methods=["POST"])
    @login_required
    @admin_required
    def email_create_rule():
        """Create a new email rule."""
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        mailbox_id = data.get("mailbox_id")
        condition_field = data.get("condition_field", "")
        condition_op = data.get("condition_op", "contains")
        condition_value = (data.get("condition_value") or "").strip()
        action_type = data.get("action_type", "")
        action_value = (data.get("action_value") or "").strip() or None

        if not name:
            return jsonify({"error": "name is required"}), 400
        if condition_field not in _VALID_FIELDS:
            return jsonify({"error": f"condition_field must be one of {sorted(_VALID_FIELDS)}"}), 400
        if condition_op not in _VALID_OPS:
            return jsonify({"error": f"condition_op must be one of {sorted(_VALID_OPS)}"}), 400
        if not condition_value:
            return jsonify({"error": "condition_value is required"}), 400
        if action_type not in _VALID_ACTIONS:
            return jsonify({"error": f"action_type must be one of {sorted(_VALID_ACTIONS)}"}), 400
        if action_type == "set_priority" and action_value not in _VALID_PRIORITIES:
            return jsonify({"error": "action_value must be action/review/info for set_priority"}), 400

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO email_rules
                   (name, mailbox_id, condition_field, condition_op, condition_value,
                    action_type, action_value)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (name, mailbox_id or None, condition_field, condition_op, condition_value, action_type, action_value),
            )
            new_id = cur.fetchone()["id"]

        logger.info("[email_rules] created rule #%d: %s", new_id, name)
        return jsonify({"success": True, "id": new_id})

    @bp.route("/api/email/rules/<int:rule_id>", methods=["PATCH"])
    @login_required
    @admin_required
    def email_toggle_rule(rule_id):
        """Toggle is_active on a rule."""
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT is_active FROM email_rules WHERE id=%s", (rule_id,))
            row = cur.fetchone()
        if not row:
            return jsonify({"error": "Rule not found"}), 404

        new_active = not row["is_active"]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("UPDATE email_rules SET is_active=%s WHERE id=%s", (new_active, rule_id))
        return jsonify({"success": True, "is_active": new_active})

    @bp.route("/api/email/rules/<int:rule_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def email_delete_rule(rule_id):
        """Delete a rule."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM email_rules WHERE id=%s", (rule_id,))
            if not cur.rowcount:
                return jsonify({"error": "Rule not found"}), 404
        return jsonify({"success": True})
