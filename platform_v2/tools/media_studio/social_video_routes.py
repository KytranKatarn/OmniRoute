"""Social Video Routes — queue, templates, generate, approve, schedule, budget."""

from datetime import datetime

from flask import jsonify, request

from .services import social_video_service as svs


def register_social_video_routes(bp, admin_required):
    """Register all social video routes on the Media Studio blueprint (ADR-045)."""

    # ── Templates ────────────────────────────────────────────────────────────

    @bp.route("/api/social-video/templates", methods=["GET"])
    @admin_required
    def sv_get_templates():
        content_type = request.args.get("content_type")
        templates = svs.get_templates(content_type=content_type)
        return jsonify(templates)

    @bp.route("/api/social-video/templates/<int:template_id>/render", methods=["POST"])
    @admin_required
    def sv_render_template(template_id):
        body = request.get_json() or {}
        variables = body.get("variables", {})
        result = svs.render_template(template_id, variables)
        if result is None:
            return jsonify({"error": "Template not found"}), 404
        return jsonify(result)

    # ── Queue ─────────────────────────────────────────────────────────────────

    @bp.route("/api/social-video/queue", methods=["GET"])
    @admin_required
    def sv_get_queue():
        status = request.args.get("status")
        content_type = request.args.get("content_type")
        try:
            limit = min(int(request.args.get("limit", 50)), 100)
        except (ValueError, TypeError):
            limit = 50
        try:
            offset = int(request.args.get("offset", 0))
        except (ValueError, TypeError):
            offset = 0
        items = svs.get_queue_items(status=status, content_type=content_type, limit=limit, offset=offset)
        return jsonify(items)

    @bp.route("/api/social-video/queue/<int:item_id>", methods=["GET"])
    @admin_required
    def sv_get_queue_item(item_id):
        item = svs.get_queue_item(item_id)
        if item is None:
            return jsonify({"error": "Queue item not found"}), 404
        return jsonify(item)

    @bp.route("/api/social-video/queue/<int:item_id>", methods=["PATCH"])
    @admin_required
    def sv_update_queue_item(item_id):
        body = request.get_json() or {}
        result = svs.update_queue_item(item_id, **body)
        if result is None:
            return jsonify({"error": "Queue item not found"}), 404
        return jsonify(result)

    # ── Actions ───────────────────────────────────────────────────────────────

    @bp.route("/api/social-video/queue/<int:item_id>/approve", methods=["POST"])
    @admin_required
    def sv_approve_item(item_id):
        result = svs.approve_item(item_id)
        if result is None:
            return jsonify({"error": "Queue item not found"}), 404
        return jsonify(result)

    @bp.route("/api/social-video/queue/<int:item_id>/reject", methods=["POST"])
    @admin_required
    def sv_reject_item(item_id):
        body = request.get_json() or {}
        reason = body.get("reason")
        result = svs.reject_item(item_id, reason=reason)
        if result is None:
            return jsonify({"error": "Queue item not found"}), 404
        return jsonify(result)

    @bp.route("/api/social-video/queue/<int:item_id>/schedule", methods=["POST"])
    @admin_required
    def sv_schedule_item(item_id):
        body = request.get_json() or {}
        scheduled_at_raw = body.get("scheduled_at")
        if not scheduled_at_raw:
            return jsonify({"error": "scheduled_at is required (ISO format)"}), 400
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_raw)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid scheduled_at format — use ISO 8601"}), 400
        result = svs.schedule_item(item_id, scheduled_at=scheduled_at)
        if result is None:
            return jsonify({"error": "Queue item not found"}), 404
        return jsonify(result)

    # ── Generate ──────────────────────────────────────────────────────────────

    QUALITY_PARAMS = {
        "draft": {"width": 256, "height": 256, "frames": 9, "fps": 8, "steps": 15},
        "standard": {"width": 512, "height": 512, "frames": 24, "fps": 8, "steps": 20},
        "high": {"width": 768, "height": 512, "frames": 48, "fps": 24, "steps": 25},
    }

    @bp.route("/api/social-video/generate", methods=["POST"])
    @admin_required
    def sv_generate():
        body = request.get_json() or {}

        content_type = body.get("content_type")
        if not content_type:
            return jsonify({"error": "content_type is required"}), 400

        prompt = body.get("prompt")
        template_id = body.get("template_id")
        template_variables = body.get("template_variables", {})

        # If template provided but no prompt, render template to get prompt
        if template_id and not prompt:
            rendered = svs.render_template(template_id, template_variables)
            if rendered is None:
                return jsonify({"error": "Template not found"}), 404
            prompt = rendered.get("prompt") or rendered.get("text") or str(rendered)

        if not prompt:
            return jsonify({"error": "prompt or template_id is required"}), 400

        caption = body.get("caption", "")
        hashtags = body.get("hashtags", [])
        target_platforms = body.get("target_platforms", [])
        agent_id = body.get("agent_id")
        quality = body.get("quality", "standard")

        if quality not in QUALITY_PARAMS:
            quality = "standard"
        video_params = QUALITY_PARAMS[quality]

        # Budget check for non-draft generations
        if quality != "draft":
            budget_ok = svs.check_budget()
            if not budget_ok.get("allowed", True) is False:
                pass  # allowed — proceed
            if budget_ok.get("allowed") is False:
                return jsonify({"error": "Budget limit reached", "budget": budget_ok}), 429

        approval_tier = "manual"
        if agent_id:
            if svs.should_auto_approve(agent_id, content_type):
                approval_tier = "auto"
        elif content_type == "motivational":
            approval_tier = "auto"

        gen_params = dict(video_params)
        gen_params["quality"] = quality

        item = svs.create_queue_item(
            content_type=content_type,
            prompt=prompt,
            caption=caption,
            hashtags=hashtags,
            target_platforms=target_platforms,
            agent_id=agent_id,
            template_id=template_id,
            approval_tier=approval_tier,
            generation_params=gen_params,
        )

        svs.update_queue_item(item["id"], status="generating")
        item["status"] = "generating"

        return jsonify(item), 201

    # ── Stats & Budget ────────────────────────────────────────────────────────

    @bp.route("/api/social-video/stats", methods=["GET"])
    @admin_required
    def sv_get_stats():
        stats = svs.get_queue_stats()
        budget = svs.check_budget()
        return jsonify({"stats": stats, "budget": budget})

    @bp.route("/api/social-video/budget", methods=["GET"])
    @admin_required
    def sv_get_budget():
        budget = svs.check_budget()
        return jsonify(budget)
