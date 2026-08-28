"""Backup Manager — webhook CRUD + test + history routes.

Split from the original backup_manager_routes.py monolith (Task #2699).
All routes are registered via register_webhooks_routes(bp, admin_required).
"""

from flask import jsonify, request, current_app
import json
import hashlib
import hmac
import requests
from datetime import datetime


# Pull every shared helper / constant / programmatic function into module scope
from ._shared import (
    get_backup_db_cursor,
)


def register_webhooks_routes(bp, admin_required):  # noqa: F811
    """Register webhook CRUD + test + history routes onto the supplied blueprint."""

    @bp.route("/api/webhooks")
    @admin_required
    def list_webhooks():
        """List all configured webhooks"""
        try:
            with get_backup_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT id, url, event_types, active, created_at, last_triggered, last_status
                    FROM backup_webhooks
                    ORDER BY created_at DESC
                """
                )
                webhooks = cur.fetchall()

            return jsonify(
                {
                    "success": True,
                    "webhooks": [
                        {
                            "id": w[0],
                            "url": w[1],
                            "event_types": w[2],
                            "active": w[3],
                            "created_at": w[4].isoformat() if w[4] else None,
                            "last_triggered": w[5].isoformat() if w[5] else None,
                            "last_status": w[6],
                        }
                        for w in webhooks
                    ],
                }
            )
        except Exception as e:
            # Table might not exist yet
            current_app.logger.warning(f"Failed to list webhooks (table may not exist): {e}")
            return jsonify({"success": True, "webhooks": [], "note": str(e)})

    @bp.route("/api/webhooks", methods=["POST"])
    @admin_required
    def create_webhook():
        """Create a new webhook"""
        try:
            data = request.get_json() or {}
            url = data.get("url")
            event_types = data.get("event_types", ["backup_complete", "backup_failed"])
            secret_key = data.get("secret_key")

            if not url:
                return jsonify({"success": False, "error": "URL is required"}), 400

            with get_backup_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO backup_webhooks (url, event_types, secret_key, active)
                    VALUES (%s, %s, %s, TRUE)
                    RETURNING id
                """,
                    (url, event_types, secret_key),
                )
                webhook_id = cur.fetchone()[0]

            return jsonify({"success": True, "webhook_id": webhook_id})

        except Exception as e:
            current_app.logger.error(f"Failed to create webhook: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/webhooks/<int:webhook_id>", methods=["DELETE"])
    @admin_required
    def delete_webhook(webhook_id):
        """Delete a webhook"""
        try:
            with get_backup_db_cursor() as (conn, cur):
                cur.execute("DELETE FROM backup_webhooks WHERE id = %s", (webhook_id,))

            return jsonify({"success": True, "message": f"Webhook {webhook_id} deleted"})

        except Exception as e:
            current_app.logger.error(f"Failed to delete webhook {webhook_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/webhooks/<int:webhook_id>/test", methods=["POST"])
    @admin_required
    def test_webhook(webhook_id):
        """Send a test webhook"""
        try:
            with get_backup_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT url, secret_key FROM backup_webhooks WHERE id = %s",
                    (webhook_id,),
                )
                webhook = cur.fetchone()

            if not webhook:
                return jsonify({"success": False, "error": "Webhook not found"}), 404

            url, secret_key = webhook

            payload = {
                "event": "test",
                "message": "This is a test webhook from A.R.C.H.I.E. Backup Manager",
                "timestamp": datetime.now().isoformat(),
            }

            headers = {"Content-Type": "application/json"}
            if secret_key:
                signature = hmac.new(
                    secret_key.encode(),
                    json.dumps(payload).encode(),
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Archie-Signature"] = signature

            response = requests.post(url, json=payload, headers=headers, timeout=10)

            return jsonify(
                {
                    "success": True,
                    "status_code": response.status_code,
                    "response": response.text[:500] if response.text else None,
                }
            )

        except Exception as e:
            current_app.logger.error(f"Failed to test webhook {webhook_id}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
