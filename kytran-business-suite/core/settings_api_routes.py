"""Settings routes for API keys and webhooks — tenant-scoped."""

import logging

from flask import Blueprint, g, jsonify, request
from flask_login import login_required

from core.api_keys import check_rate_limit, generate_api_key, list_api_keys, revoke_api_key
from core.webhook_manager import delete_webhook, list_webhooks, register_webhook

logger = logging.getLogger(__name__)

settings_api_bp = Blueprint("settings_api", __name__, url_prefix="/api/settings")


@settings_api_bp.route("/api-keys", methods=["GET"])
@login_required
def get_api_keys():
    keys = list_api_keys(g.tenant_id)
    return jsonify({"api_keys": keys})


@settings_api_bp.route("/api-keys", methods=["POST"])
@login_required
def create_api_key():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    key_data = generate_api_key(
        tenant_id=g.tenant_id,
        name=name,
        permissions=data.get("permissions", ["read"]),
        rate_limit=data.get("rate_limit", 1000),
    )
    return jsonify(key_data), 201


@settings_api_bp.route("/api-keys/<int:key_id>/revoke", methods=["POST"])
@login_required
def revoke_key(key_id):
    result = revoke_api_key(key_id)
    if not result:
        return jsonify({"error": "Key not found"}), 404
    return jsonify({"revoked": True, "id": key_id})


@settings_api_bp.route("/webhooks", methods=["GET"])
@login_required
def get_webhooks():
    hooks = list_webhooks(g.tenant_id)
    return jsonify({"webhooks": hooks})


@settings_api_bp.route("/webhooks", methods=["POST"])
@login_required
def create_webhook():
    data = request.get_json(force=True)
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    events = data.get("events", ["*"])
    webhook = register_webhook(
        tenant_id=g.tenant_id,
        url=url,
        events=events,
    )
    return jsonify(webhook), 201


@settings_api_bp.route("/webhooks/<int:webhook_id>", methods=["DELETE"])
@login_required
def remove_webhook(webhook_id):
    result = delete_webhook(webhook_id, g.tenant_id)
    if not result:
        return jsonify({"error": "Webhook not found"}), 404
    return jsonify({"deleted": True, "id": webhook_id})
