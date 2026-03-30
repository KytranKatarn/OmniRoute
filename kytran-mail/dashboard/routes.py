"""Kytran Mail dashboard routes + API endpoints."""

from flask import jsonify, render_template, request

from . import stalwart_client


def register_routes(app):

    @app.route("/dashboard")
    def dashboard():
        return render_template(
            "dashboard.html",
            domain=app.config["MAIL_DOMAIN"],
            hostname=app.config["MAIL_HOSTNAME"],
        )

    @app.route("/api/health")
    def api_health():
        status = stalwart_client.get_server_status()
        return jsonify({
            "status": "healthy" if status.get("online") else "unhealthy",
            "mail_server": status,
            "domain": app.config["MAIL_DOMAIN"],
        }), 200 if status.get("online") else 503

    @app.route("/api/status")
    def api_status():
        server = stalwart_client.get_server_status()
        queue = stalwart_client.get_queue_status()
        mailboxes = stalwart_client.list_mailboxes()
        return jsonify({
            "success": True,
            "server": server,
            "queue": queue,
            "mailbox_count": len(mailboxes),
            "domain": app.config["MAIL_DOMAIN"],
        })

    @app.route("/api/mailboxes")
    def api_list_mailboxes():
        mailboxes = stalwart_client.list_mailboxes()
        return jsonify({"success": True, "mailboxes": mailboxes, "count": len(mailboxes)})

    @app.route("/api/mailboxes", methods=["POST"])
    def api_create_mailbox():
        data = request.get_json() or {}
        name = data.get("name", "").strip().lower()
        display_name = data.get("display_name", name)
        password = data.get("password", "")
        quota_mb = data.get("quota_mb", 0)

        if not name:
            return jsonify({"success": False, "error": "Name is required"}), 400
        if not password or len(password) < 8:
            return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400

        result = stalwart_client.create_mailbox(name, display_name, password, quota_mb)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        return jsonify({"success": True, "message": f"Mailbox {name}@{app.config['MAIL_DOMAIN']} created"})

    @app.route("/api/mailboxes/<name>", methods=["DELETE"])
    def api_delete_mailbox(name):
        result = stalwart_client.delete_mailbox(name)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        return jsonify({"success": True, "message": f"Mailbox {name} deleted"})

    @app.route("/api/mailboxes/<name>/password", methods=["POST"])
    def api_reset_password(name):
        data = request.get_json() or {}
        password = data.get("password", "")
        if not password or len(password) < 8:
            return jsonify({"success": False, "error": "Password must be at least 8 characters"}), 400
        result = stalwart_client.reset_password(name, password)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        return jsonify({"success": True, "message": f"Password reset for {name}"})

    @app.route("/api/mailboxes/<name>/toggle", methods=["POST"])
    def api_toggle_mailbox(name):
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
        result = stalwart_client.toggle_mailbox(name, enabled)
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        state = "enabled" if enabled else "disabled"
        return jsonify({"success": True, "message": f"Mailbox {name} {state}"})

    @app.route("/api/queue")
    def api_queue():
        queue = stalwart_client.get_queue_status()
        return jsonify({"success": True, "queue": queue})
