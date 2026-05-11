"""Email HQ — Rules engine for Phase 6.

Evaluates email_rules against a newly synced message and applies
configured actions (set_priority, archive, star, skip_triage).

Rules are evaluated in id order; first matching rule wins.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_OPS = {
    "contains": lambda field, val: val.lower() in field.lower(),
    "not_contains": lambda field, val: val.lower() not in field.lower(),
    "equals": lambda field, val: field.lower() == val.lower(),
    "starts_with": lambda field, val: field.lower().startswith(val.lower()),
    "ends_with": lambda field, val: field.lower().endswith(val.lower()),
}


def _matches(rule: dict, msg: dict) -> bool:
    field_val = str(msg.get(rule["condition_field"]) or "")
    op_fn = _OPS.get(rule["condition_op"])
    if not op_fn:
        return False
    try:
        return op_fn(field_val, rule["condition_value"])
    except Exception:
        return False


def apply_rules(message_id: int, mailbox_id: int, msg: dict) -> dict:
    """Evaluate active rules for this mailbox against msg fields.

    msg dict must contain: from_address, subject, to_address, body_preview.

    Returns {action_type, action_value, rule_name} of the first matching rule,
    or {} if no rule matches. Updates email_messages in-place on match.
    """
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, name, condition_field, condition_op, condition_value,
                      action_type, action_value
               FROM email_rules
               WHERE is_active = TRUE
                 AND (mailbox_id IS NULL OR mailbox_id = %s)
               ORDER BY id""",
            (mailbox_id,),
        )
        rules = [dict(r) for r in cur.fetchall()]

    for rule in rules:
        if not _matches(rule, msg):
            continue

        action_type = rule["action_type"]
        action_value = rule.get("action_value") or ""
        logger.info(
            "[email_rules] rule '%s' matched msg=%d → %s(%s)",
            rule["name"],
            message_id,
            action_type,
            action_value,
        )

        with get_db_cursor(commit=True) as (conn, cur):
            if action_type == "set_priority":
                cur.execute(
                    "UPDATE email_messages SET ai_priority=%s WHERE id=%s",
                    (action_value, message_id),
                )
            elif action_type == "archive":
                cur.execute(
                    "UPDATE email_messages SET is_archived=TRUE, is_read=TRUE WHERE id=%s",
                    (message_id,),
                )
            elif action_type == "star":
                cur.execute(
                    "UPDATE email_messages SET is_starred=TRUE WHERE id=%s",
                    (message_id,),
                )
            elif action_type == "skip_triage":
                pass  # caller checks return value and skips triage

        return {"action_type": action_type, "action_value": action_value, "rule_name": rule["name"]}

    return {}
