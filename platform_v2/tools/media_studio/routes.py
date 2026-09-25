"""Media Studio API routes — thin HTTP handlers calling services.

All generation routes through Bridge dispatcher. Gallery with
per-user ownership. ComfyUI fleet status with GPU tiering.
"""

import logging
import os

from flask import current_app, jsonify, request, render_template
from flask_login import login_required, current_user

from . import admin_required, media_studio_bp

logger = logging.getLogger(__name__)


# ─── Page Route ─────────────────────────────────────────────────────


@media_studio_bp.route("/")
@login_required
def index():
    """Render the Media Studio LCARS UI."""
    return render_template("tools/media_studio/media_studio.html")


# ─── Dashboard ──────────────────────────────────────────────────────


@media_studio_bp.route("/api/dashboard")
@login_required
def api_dashboard():
    """Dashboard stats, recent generations, fleet GPU status."""
    from .services.generation_service import get_dashboard_stats
    from .services.comfyui_manager import get_fleet_comfyui_status

    stats = get_dashboard_stats(current_user.id)
    try:
        fleet = get_fleet_comfyui_status()
    except Exception as exc:
        logger.warning("dashboard ComfyUI status unavailable: %s", exc)
        fleet = []

    return jsonify({**stats, "fleet": fleet})


# ─── Roster / Agent Picker ──────────────────────────────────────────


@media_studio_bp.route("/api/agents/picker")
@login_required
def api_agents_picker():
    from .services.roster_service import get_agent_picker

    return jsonify(get_agent_picker())


@media_studio_bp.route("/api/agents/gallery-subjects")
@login_required
def api_gallery_subjects():
    from .services.roster_service import get_gallery_subjects

    return jsonify(get_gallery_subjects())


@media_studio_bp.route("/api/gallery/<int:media_id>/asset-type", methods=["PUT"])
@login_required
def api_set_asset_type(media_id):
    import psycopg2.extras
    from database import get_db_cursor

    data = request.get_json() or {}
    asset_type = data.get("asset_type", "")
    if asset_type not in ("headshot", "lifestyle", "social", "brand", "portrait"):
        return jsonify({"error": "invalid asset_type"}), 400
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE media_library SET metadata = metadata || %s WHERE id = %s AND is_deleted = false",
            (psycopg2.extras.Json({"asset_type": asset_type}), media_id),
        )
        if cur.rowcount == 0:
            return jsonify({"error": "not found"}), 404
    return jsonify({"asset_type": asset_type})


@media_studio_bp.route("/api/gallery/<int:media_id>/featured", methods=["PUT"])
@login_required
def api_set_featured(media_id):
    import psycopg2.extras
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT owner_type, owner_id FROM media_library WHERE id = %s AND is_deleted = false",
            (media_id,),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        cur.execute(
            "UPDATE media_library SET metadata = metadata - 'featured' "
            "WHERE owner_type = %s AND owner_id = %s AND is_deleted = false",
            (row["owner_type"], row["owner_id"]),
        )
        cur.execute(
            "UPDATE media_library SET metadata = metadata || %s WHERE id = %s",
            (psycopg2.extras.Json({"featured": True}), media_id),
        )
    return jsonify({"featured": True})


@media_studio_bp.route("/api/portraits/<int:agent_id>/identity")
@login_required
def api_portrait_identity(agent_id):
    """Returns identity_prompt for an agent — used by Generate tab pre-fill."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COALESCE(NULLIF(a.avatar_generation_prompt, ''), NULLIF(a.portrait_prompt, ''), NULLIF(ap.identity_prompt, '')) "
            "AS identity_prompt, a.display_name, a.name "
            "FROM agents a LEFT JOIN agent_portraits ap ON ap.agent_id = a.id "
            "WHERE a.id = %s",
            (agent_id,),
        )
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "identity_prompt": row["identity_prompt"] or "",
            "agent_name": row["display_name"] or row["name"],
        }
    )


# ─── Generation ─────────────────────────────────────────────────────


@media_studio_bp.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    """Submit a generation request."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    media_type = data.get("media_type", "image")
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    result = submit_generation(
        user_id=current_user.id,
        media_type=media_type,
        prompt=prompt,
        negative_prompt=data.get("negative_prompt", ""),
        params={
            **{k: data[k] for k in ("model", "width", "height", "steps", "sampler", "seed") if k in data},
            "cfg": data.get("cfg") or data.get("cfg_scale"),  # JS sends cfg_scale, service uses cfg
        },
    )

    if "error" in result:
        return jsonify(result), 400 if "Unsupported" in result["error"] else 500

    return jsonify(result), 201


# ─── Queue ──────────────────────────────────────────────────────────


@media_studio_bp.route("/api/queue")
@login_required
def api_queue():
    """Get generation queue — user jobs + agent portrait jobs (platform-wide for this tenant).

    Supports ?status=pending|dispatched|generating|failed|completed and ?per_page=N
    for the Queue tab status-filtered views.
    """
    from .services.generation_service import get_queue_status

    status = request.args.get("status") or None
    limit = request.args.get("per_page", request.args.get("limit", 20), type=int)
    user_jobs = get_queue_status(owner_type="user", owner_id=current_user.id, limit=limit, status=status)
    agent_jobs = get_queue_status(owner_type="agent", owner_id=None, limit=limit, status=status)
    all_jobs = sorted(user_jobs + agent_jobs, key=lambda j: j.get("created_at") or "", reverse=True)[:limit]
    # Return both 'jobs' (legacy) and 'items' (Queue tab loadQueueItems expects items)
    return jsonify({"jobs": all_jobs, "items": all_jobs})


@media_studio_bp.route("/api/queue/<int:queue_id>/cancel", methods=["POST"])
@login_required
def api_cancel_job(queue_id):
    """Cancel a pending/dispatched generation job."""
    from .services.generation_service import cancel_generation

    ok = cancel_generation(queue_id, current_user.id)
    if ok:
        return jsonify({"status": "cancelled"})
    return jsonify({"error": "Job not found or not cancellable"}), 404


# ─── Gallery ────────────────────────────────────────────────────────


@media_studio_bp.route("/api/gallery")
@login_required
def api_gallery():
    """Paginated gallery for current user, or shared agent gallery."""
    from database import get_db_cursor

    from .services.gallery_service import get_gallery

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    media_type = request.args.get("type")
    favorites = request.args.get("favorites", "false").lower() == "true"
    req_owner_type = request.args.get("owner_type")
    agent_name = request.args.get("agent_name")

    show_versions = request.args.get("show_versions", "false") == "true"

    if req_owner_type in ("agent", "agents"):
        # Shared agent gallery — bypass per-user ownership filter
        conditions = [
            "is_deleted = false",
            "owner_type = 'agent'",
            "gallery_visibility = 'shared'",
        ]
        if not show_versions:
            conditions.append("parent_id IS NULL")
        params: list = []
        req_owner_id = request.args.get("owner_id", type=int)
        if req_owner_id:
            conditions.append("owner_id = %s")
            params.append(req_owner_id)
        asset_type = request.args.get("asset_type")
        if asset_type:
            conditions.append("metadata->>'asset_type' = %s")
            params.append(asset_type)
        if agent_name:
            conditions.append("metadata->>'agent_name' = %s")
            params.append(agent_name)
        if media_type:
            conditions.append("media_type = %s")
            params.append(media_type)
        where = " AND ".join(conditions)
        # Honor the sort param via the same whitelist as the user gallery
        # (never interpolate raw user input into SQL).
        from .services.gallery_service import _GALLERY_SORTS

        order_by = _GALLERY_SORTS.get(
            (request.args.get("sort", "newest") or "newest").lower(),
            _GALLERY_SORTS["newest"],
        )
        with get_db_cursor() as (conn, cur):
            cur.execute(f"SELECT COUNT(*) as total FROM media_library WHERE {where}", params)
            total = cur.fetchone()["total"]
            cur.execute(
                f"""
                SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                       provider, seed, width, height, duration_ms, cost,
                       is_favorite, metadata, created_at
                FROM media_library
                WHERE {where}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                params + [per_page, (page - 1) * per_page],
            )
            from .services.gallery_service import _serialize_row

            items = [_serialize_row(row) for row in cur.fetchall()]

            # Mark canonical portrait as featured — add synthetic row if not in media_library,
            # or tag the existing media_library item if it matches the canonical path
            if req_owner_id and (not asset_type or asset_type == "portrait"):
                cur.execute(
                    """SELECT ap.id, ap.canonical_image_path, ap.updated_at, a.display_name
                       FROM agent_portraits ap JOIN agents a ON a.id = ap.agent_id
                       WHERE ap.agent_id = %s AND ap.canonical_image_path IS NOT NULL AND ap.approved = true""",
                    (req_owner_id,),
                )
                portrait_row = cur.fetchone()
                if portrait_row:
                    path = portrait_row["canonical_image_path"]
                    matched = False
                    for it in items:
                        if (it.get("url") or it.get("file_path")) == path:
                            if not it.get("metadata"):
                                it["metadata"] = {}
                            it["metadata"]["featured"] = True
                            matched = True
                            break
                    if not matched:
                        items.insert(
                            0,
                            {
                                "id": "portrait_" + str(portrait_row["id"]),
                                "media_type": "image",
                                "url": path,
                                "file_path": path,
                                "thumbnail_path": path,
                                "prompt": "Canonical portrait — " + (portrait_row["display_name"] or ""),
                                "metadata": {"asset_type": "portrait", "featured": True},
                                "created_at": (
                                    portrait_row["updated_at"].isoformat() if portrait_row["updated_at"] else None
                                ),
                            },
                        )
                        total += 1
        return jsonify(
            {
                "items": items,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page if per_page else 1,
            }
        )

    if req_owner_type == "brand":
        # Shared brand gallery — brand-level assets (owner_type='brand', owner_id=brand id)
        conditions = ["is_deleted = false", "owner_type = 'brand'"]
        if not show_versions:
            conditions.append("parent_id IS NULL")
        params = []
        req_owner_id = request.args.get("owner_id", type=int)
        if req_owner_id:
            conditions.append("owner_id = %s")
            params.append(req_owner_id)
        asset_type = request.args.get("asset_type")
        if asset_type:
            conditions.append("metadata->>'asset_type' = %s")
            params.append(asset_type)
        if media_type:
            conditions.append("media_type = %s")
            params.append(media_type)
        where = " AND ".join(conditions)
        from .services.gallery_service import _GALLERY_SORTS, _serialize_row

        order_by = _GALLERY_SORTS.get(
            (request.args.get("sort", "newest") or "newest").lower(),
            _GALLERY_SORTS["newest"],
        )
        with get_db_cursor() as (conn, cur):
            cur.execute(f"SELECT COUNT(*) as total FROM media_library WHERE {where}", params)
            total = cur.fetchone()["total"]
            cur.execute(
                f"""
                SELECT id, media_type, file_path, thumbnail_path, prompt, model,
                       provider, seed, width, height, duration_ms, cost,
                       is_favorite, metadata, created_at
                FROM media_library
                WHERE {where}
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
                """,
                params + [per_page, (page - 1) * per_page],
            )
            items = [_serialize_row(row) for row in cur.fetchall()]
        return jsonify(
            {
                "items": items,
                "total": total,
                "page": page,
                "per_page": per_page,
                "pages": (total + per_page - 1) // per_page if per_page else 1,
            }
        )

    result = get_gallery(
        owner_type="user",
        owner_id=current_user.id,
        media_type=media_type,
        favorites_only=favorites,
        page=page,
        per_page=per_page,
        show_versions=show_versions,
        asset_type=request.args.get("asset_type"),
        search=request.args.get("q") or request.args.get("search"),
        sort=request.args.get("sort", "newest"),
    )
    return jsonify(result)


@media_studio_bp.route("/api/gallery/<int:media_id>")
@login_required
def api_gallery_detail(media_id):
    """Single media detail with full metadata."""
    from .services.gallery_service import get_media_detail

    item = get_media_detail(media_id, "user", current_user.id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    return jsonify(item)


@media_studio_bp.route("/api/gallery/<int:media_id>/favorite", methods=["POST"])
@login_required
def api_toggle_favorite(media_id):
    """Toggle favorite on a media item."""
    from .services.gallery_service import toggle_favorite

    new_state = toggle_favorite(media_id, "user", current_user.id)
    if new_state is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"is_favorite": new_state})


@media_studio_bp.route("/api/gallery/<int:media_id>", methods=["DELETE"])
@login_required
def api_delete_media(media_id):
    """Soft delete a media item."""
    from .services.gallery_service import delete_media

    ok = delete_media(media_id, "user", current_user.id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "deleted"})


# ─── Models + ComfyUI Status ───────────────────────────────────────


@media_studio_bp.route("/api/models")
@login_required
def api_models():
    """Available ComfyUI models across fleet."""
    from .services.comfyui_manager import get_available_models

    return jsonify({"models": get_available_models()})


@media_studio_bp.route("/api/comfyui/status")
@login_required
def api_comfyui_status():
    """Fleet ComfyUI health with GPU tiers."""
    from .services.comfyui_manager import get_fleet_comfyui_status

    return jsonify({"nodes": get_fleet_comfyui_status()})


@media_studio_bp.route("/api/comfyui/rescue", methods=["POST"])
@login_required
def api_comfyui_rescue():
    """Download any ComfyUI completed images not yet in media_library.

    Uses get_comfyui_service() which handles cold boot (ensure_running)
    and future fleet node routing via Department HQ.
    """
    from database import get_db_cursor
    from .services.gallery_service import create_media_entry
    from ai_bridge.comfyui_service import get_comfyui_service

    try:
        svc = get_comfyui_service()
        svc.ensure_running()
        comfyui_url = svc.host
    except Exception as exc:
        return jsonify({"rescued": 0, "error": f"ComfyUI unavailable: {exc}"}), 503

    try:
        import requests as _requests

        r = _requests.get(f"{comfyui_url}/history?max_items=50", timeout=10)
        history = r.json()
    except Exception as exc:
        return jsonify({"rescued": 0, "error": f"ComfyUI unreachable: {exc}"}), 503

    # Collect all output filenames from history
    all_filenames = {}
    for prompt_id, job in history.items():
        if not job.get("status", {}).get("completed"):
            continue
        for node_out in job.get("outputs", {}).values():
            for img in node_out.get("images", []):
                fname = img.get("filename")
                if fname:
                    all_filenames[fname] = prompt_id

    if not all_filenames:
        return jsonify({"rescued": 0})

    # Check which are already in media_library
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT file_path FROM media_library WHERE file_path LIKE %s",
            ("%/recovered/%",),
        )
        existing = {row["file_path"] for row in cur.fetchall()}

    rescue_dir = os.path.join(os.path.dirname(__file__), "..", "..", "static", "media", "recovered")
    os.makedirs(rescue_dir, exist_ok=True)

    rescued = 0
    for filename, prompt_id in all_filenames.items():
        rel_path = f"/static/media/recovered/{filename}"
        if rel_path in existing:
            continue
        dest = os.path.join(rescue_dir, filename)
        try:
            img_url = f"{comfyui_url}/view?filename={filename}&type=output"
            img_r = _requests.get(img_url, timeout=10)
            img_r.raise_for_status()
            with open(dest, "wb") as f:
                f.write(img_r.content)
            create_media_entry(
                owner_type="user",
                owner_id=current_user.id,
                media_type="image",
                file_path=rel_path,
                thumbnail_path=rel_path,
                prompt=f"Rescued from ComfyUI (prompt_id: {prompt_id[:8]})",
            )
            rescued += 1
        except Exception as exc:
            logger.warning("rescue: failed to fetch %s: %s", filename, exc)
            if os.path.exists(dest):
                os.remove(dest)

    return jsonify({"rescued": rescued})


@media_studio_bp.route("/api/comfyui/queue")
@login_required
def api_comfyui_queue():
    """Proxy ComfyUI /queue — returns running + pending job counts and items.

    Routes through get_comfyui_service() for consistent host resolution
    and future fleet node routing via Department HQ.
    """
    from ai_bridge.comfyui_service import get_comfyui_service
    import requests as _requests

    try:
        svc = get_comfyui_service()
        comfyui_url = svc.host
        r = _requests.get(f"{comfyui_url}/queue", timeout=5)
        data = r.json()
        running = data.get("queue_running", [])
        pending = data.get("queue_pending", [])

        def _parse_item(item, status):
            # ComfyUI format: [queue_number, prompt_id, workflow_dict, extra_data, ...]
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                return {"position": item[0], "prompt_id": item[1], "status": status}
            if isinstance(item, dict):
                return {
                    "position": item.get("queue_number", 0),
                    "prompt_id": item.get("prompt_id", ""),
                    "status": status,
                }
            return {"position": 0, "prompt_id": str(item), "status": status}

        items = [_parse_item(i, "running") for i in running] + [_parse_item(i, "pending") for i in pending]
        return jsonify({"running": len(running), "pending": len(pending), "items": items})
    except Exception as exc:
        return jsonify({"running": 0, "pending": 0, "items": [], "error": str(exc)})


# ─── Assignments ────────────────────────────────────────────────────


@media_studio_bp.route("/api/assignments/<target_type>/<int:target_id>")
@login_required
def api_get_assignment(target_type, target_id):
    """Get active media assignments for a target."""
    from .services.gallery_service import get_active_assignment

    assignment_type = request.args.get("type", "")
    if not assignment_type:
        return jsonify({"error": "type parameter required"}), 400

    result = get_active_assignment(assignment_type, target_type, target_id)
    return jsonify({"assignment": result})


@media_studio_bp.route("/api/assignments", methods=["POST"])
@login_required
def api_create_assignment():
    """Assign media to a UI location."""
    from .services.gallery_service import assign_media

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    required = ["media_id", "assignment_type", "target_type"]
    if not all(k in data for k in required):
        return jsonify({"error": f"Required: {', '.join(required)}"}), 400

    assignment_id = assign_media(
        media_id=data["media_id"],
        assignment_type=data["assignment_type"],
        target_type=data["target_type"],
        target_id=data.get("target_id"),
    )
    return jsonify({"id": assignment_id}), 201


# ─── Portraits ──────────────────────────────────────────────────────


@media_studio_bp.route("/api/portraits")
@login_required
def api_portraits():
    """All agents with portrait status for grid view."""
    from .services.portrait_service import get_all_agent_portraits

    return jsonify({"agents": get_all_agent_portraits()})


@media_studio_bp.route("/api/portraits/identity-audit")
@admin_required
def api_portrait_identity_audit():
    from .services.portrait_service import get_identity_audit

    return jsonify(get_identity_audit())


@media_studio_bp.route("/api/image-providers")
@login_required
def api_image_providers():
    """Merged list of local checkpoints + active cloud image-gen contractors.

    Returns {auto, local[], cloud_free[], cloud_paid[]} for the Media Studio
    model selector dropdown. Local entries enumerate the ComfyUI checkpoints
    directory; cloud entries come from contractor_providers WHERE capabilities ?
    'image_gen'. See spec ~/.claude/plans/2026-05-16-image-provider-selector.md.
    """
    from .services.generation_service import get_image_providers
    from .services.portrait_service import DEFAULT_PORTRAIT_MODEL

    providers = get_image_providers()
    providers["portrait_default_model"] = DEFAULT_PORTRAIT_MODEL
    return jsonify(providers)


@media_studio_bp.route("/api/portraits/<int:agent_id>")
@login_required
def api_portrait_detail(agent_id):
    """Agent portrait detail with variant gallery."""
    from .services.portrait_service import get_agent_portrait

    result = get_agent_portrait(agent_id)
    if not result:
        return jsonify({"error": "Agent not found"}), 404
    return jsonify(result)


@media_studio_bp.route("/api/portraits/<int:agent_id>/generate-canonical", methods=["POST"])
@login_required
def api_generate_canonical(agent_id):
    """Generate initial canonical portrait."""
    from .services.portrait_service import generate_canonical
    from database import get_db_cursor

    # Gate: block generation if agent has no identity_prompt
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COALESCE(NULLIF(a.avatar_generation_prompt, ''), NULLIF(a.portrait_prompt, ''), NULLIF(ap.identity_prompt, '')) "
            "AS identity_prompt "
            "FROM agents a LEFT JOIN agent_portraits ap ON ap.agent_id = a.id "
            "WHERE a.id = %s",
            (agent_id,),
        )
        _portrait_row = cur.fetchone()
        _has_prompt = bool(
            _portrait_row and _portrait_row.get("identity_prompt") and _portrait_row["identity_prompt"].strip()
        )
    if not _has_prompt:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "No identity prompt set for this agent. Add a prompt in the portrait editor before generating.",
                }
            ),
            400,
        )

    # Duplicate guard — block if a pending/dispatched job already exists for this agent
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id FROM media_generation_queue
            WHERE owner_type = 'agent' AND owner_id = %s
              AND status IN ('pending', 'dispatched')
            LIMIT 1
            """,
            (agent_id,),
        )
        existing = cur.fetchone()
    if existing:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "A portrait generation is already queued for this agent. Wait for it to complete before submitting another.",
                }
            ),
            409,
        )

    data = request.get_json() or {}
    result = generate_canonical(
        agent_id,
        prompt_override=data.get("prompt"),
        model=data.get("model"),
        model_override=data.get("model_override"),
        identity_mode=data.get("identity_mode", "auto"),
        identity_weight=data.get("identity_weight"),
    )
    if "error" in result or not result.get("queue_id"):
        return jsonify({"success": False, "error": result.get("error", "Portrait queue was not created")}), 400
    return jsonify(result), 202


@media_studio_bp.route("/api/portraits/<int:agent_id>/generate-variant", methods=["POST"])
@login_required
def api_generate_variant(agent_id):
    """Generate face-consistent variant using IP-Adapter."""
    from .services.portrait_service import generate_variant

    data = request.get_json() or {}
    result = generate_variant(
        agent_id,
        style=data.get("style"),
        pose=data.get("pose"),
        model=data.get("model"),  # may be bare filename, "provider:<key>", or None (Auto)
        model_override=data.get("model_override"),  # per-provider model picker (#2942)
        identity_mode=data.get("identity_mode", "auto"),
        identity_weight=data.get("identity_weight"),
    )
    if "error" in result or not result.get("queue_id"):
        return jsonify({"success": False, "error": result.get("error", "Variant queue was not created")}), 400
    return jsonify(result), 202


@media_studio_bp.route("/api/portraits/<int:agent_id>/generate-fanout", methods=["POST"])
@login_required
def api_generate_fanout(agent_id):
    """Fan-out portrait generation — submits N jobs with style variations in one click."""
    from .services.portrait_service import generate_fanout

    data = request.get_json() or {}
    result = generate_fanout(
        agent_id,
        prompt_override=data.get("prompt"),
        model=data.get("model"),  # may be bare filename, "provider:<key>", or None (Auto)
        model_override=data.get("model_override"),  # per-provider model picker (#2942)
        identity_mode=data.get("identity_mode", "auto"),
        identity_weight=data.get("identity_weight"),
    )
    if not result.get("success") or not result.get("queue_ids"):
        return jsonify({"success": False, "error": result.get("error", "Portrait queue was not created")}), 400
    return jsonify(result), 202


@media_studio_bp.route("/api/portraits/<int:agent_id>/refine-prompt", methods=["POST"])
@login_required
def api_refine_prompt(agent_id):
    """Queue a M.U.S.E. portrait refinement job in Department HQ.

    JSON body: { "feedback": "...", "history": [...] }
    Returns immediately: { "task_id": N, "status": "queued" }
    Poll GET /api/portraits/<id>/refine-status/<task_id> for result.
    """
    import psycopg2.extras
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    feedback = (data.get("feedback") or "").strip()
    if not feedback:
        return jsonify({"error": "feedback is required"}), 400

    job_meta = psycopg2.extras.Json(
        {
            "agent_id": agent_id,
            "feedback": feedback,
            "history": data.get("history") or [],
        }
    )

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO unified_tasks
               (title, task_type, status, priority, metadata, tags)
               VALUES (%s, 'portrait_refinement', 'pending', 8, %s, ARRAY['portrait_refinement'])
               RETURNING id""",
            (f"[Portrait Refine] Agent {agent_id}: {feedback[:60]}", job_meta),
        )
        task_id = cur.fetchone()["id"]

    return jsonify({"task_id": task_id, "status": "queued"})


@media_studio_bp.route("/api/portraits/<int:agent_id>/agent-refine", methods=["POST"])
def api_agent_initiated_refine(agent_id):
    """Agent-initiated portrait revision — 3-way collaborative voice.

    The agent provides their own perspective (drawn from their system_prompt),
    moondream describes the current portrait, and M.U.S.E. synthesises all three.
    No login required — called internally by agents or the delegation worker.
    Result is queued for Kytran approval via Telegram.

    JSON body: { "feedback": "optional extra context", "agent_token": "..." }
    Returns: { "task_id": N, "status": "queued", "agent_voice": "..." }
    """
    import psycopg2.extras
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    extra_feedback = (data.get("feedback") or "").strip()

    # Fetch agent identity
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, name, display_name, system_prompt FROM agents WHERE id = %s",
            (agent_id,),
        )
        agent = cur.fetchone()

    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    # Build agent voice from their system_prompt — what they'd say about their ideal portrait
    system_prompt = (agent.get("system_prompt") or "").strip()
    agent_voice = (
        f"I am {agent.get('display_name') or agent.get('name')}. "
        f"Based on my identity and role, my portrait should reflect: {system_prompt[:300]}"
        if system_prompt
        else f"I am {agent.get('display_name') or agent.get('name')}. "
        f"I want my portrait to reflect my unique character and role."
    )
    if extra_feedback:
        agent_voice += f" Additional direction: {extra_feedback}"

    job_meta = psycopg2.extras.Json(
        {
            "agent_id": agent_id,
            "feedback": agent_voice,
            "history": [],
            "agent_initiated": True,
            "agent_voice": agent_voice,
            "extra_feedback": extra_feedback,
        }
    )

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO unified_tasks
               (title, task_type, status, priority, metadata, tags)
               VALUES (%s, 'portrait_refinement', 'pending', 8, %s,
                       ARRAY['portrait_refinement','agent_initiated'])
               RETURNING id""",
            (
                f"[Agent Identity] {agent.get('display_name') or agent.get('name')} requests portrait revision",
                job_meta,
            ),
        )
        task_id = cur.fetchone()["id"]

    # Notify Kytran via Telegram
    try:
        from services.telegram_service import send_info

        send_info(
            f"🎨 Agent Identity Evolution\n"
            f"{agent.get('display_name') or agent.get('name')} has requested a portrait revision.\n"
            f"Voice: {agent_voice[:200]}\n"
            f"Review in Media Studio → Portraits tab (task #{task_id})"
        )
    except Exception as exc:
        current_app.logger.warning("[agent-refine] Telegram alert failed: %s", exc)

    return jsonify(
        {
            "task_id": task_id,
            "status": "queued",
            "agent_voice": agent_voice,
            "message": "Portrait revision queued for M.U.S.E. synthesis and Kytran approval",
        }
    )


@media_studio_bp.route("/api/portraits/<int:agent_id>/refine-status/<int:task_id>")
@login_required
def api_refine_status(agent_id, task_id):
    """Poll a queued portrait refinement job.

    Returns: { status: pending|running|completed|failed, result: {...} }
    """
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT status, metadata FROM unified_tasks WHERE id = %s",
            (task_id,),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({"error": "Task not found"}), 404

    meta = row["metadata"] or {}
    resp = {"status": row["status"]}
    if row["status"] == "completed" and "result" in meta:
        resp.update(meta["result"])
    elif row["status"] == "failed":
        resp["error"] = meta.get("error", "Refinement failed")
    return jsonify(resp)


@media_studio_bp.route("/api/portraits/<int:agent_id>/refinement-draft", methods=["PUT"])
@login_required
def api_save_refinement_draft(agent_id):
    """Save the user's in-progress feedback draft to agent_portraits.refinement_draft.

    JSON body: { "draft": "keep the blue eyes but make it more 3D..." }
    Persists across browsers and sessions — lives on the agent's profile.
    """
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    draft = data.get("draft", "")
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_portraits (agent_id, refinement_draft)
               VALUES (%s, %s)
               ON CONFLICT (agent_id) DO UPDATE SET refinement_draft = EXCLUDED.refinement_draft""",
            (agent_id, draft),
        )
    return jsonify({"saved": True})


@media_studio_bp.route("/api/portraits/<int:agent_id>/refine-pending")
@login_required
def api_refine_pending(agent_id):
    """Check if there's an active refinement job for this agent (pending or in_progress).

    Returns { task_id, status, started_ago } or { task_id: null } if none.
    Used by the UI to auto-resume polling when the user returns to a portrait.
    """
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, status,
                      EXTRACT(EPOCH FROM (NOW() - created_at))::int AS age_secs
               FROM unified_tasks
               WHERE task_type = 'portrait_refinement'
                 AND status IN ('pending', 'in_progress')
                 AND metadata->>'agent_id' = %s
               ORDER BY id DESC LIMIT 1""",
            (str(agent_id),),
        )
        row = cur.fetchone()

    if not row:
        return jsonify({"task_id": None})

    age = row["age_secs"] or 0
    if age < 60:
        started_ago = f"{age}s ago"
    elif age < 3600:
        started_ago = f"{age // 60}m ago"
    else:
        started_ago = f"{age // 3600}h ago"

    return jsonify({"task_id": row["id"], "status": row["status"], "started_ago": started_ago})


@media_studio_bp.route("/api/portraits/<int:agent_id>/refine-stream", methods=["POST"])
@login_required
def api_refine_stream(agent_id):
    """SSE streaming M.U.S.E. refinement — yields each step as it completes.

    JSON body: { "feedback": "...", "history": [...] }
    Returns text/event-stream — each event: data: <json>\\n\\n
    Steps: vision → agent → muse → complete
    """
    import json as _json
    from flask import stream_with_context, Response
    from .services.portrait_service import (
        _load_refinement_context,
        _step_vision_analysis,
        _step_consult_agent,
        _step_muse_synthesize,
    )

    data = request.get_json(silent=True) or {}
    feedback = (data.get("feedback") or "").strip()
    history = data.get("history") or []

    if not feedback:
        return jsonify({"error": "feedback is required"}), 400

    ctx = _load_refinement_context(agent_id)
    if not ctx:
        return jsonify({"error": "Agent portrait not found"}), 404

    current_prompt = ctx.get("identity_prompt") or ""
    if not current_prompt:
        return jsonify({"error": "No identity prompt set — add one in DHQ Roster"}), 400

    agent_name = ctx.get("display_name") or ctx.get("name") or f"Agent {agent_id}"

    def _evt(obj):
        return f"data: {_json.dumps(obj)}\n\n"

    def generate():
        # Step 1 — Vision analysis
        yield _evt(
            {
                "step": "vision",
                "status": "running",
                "label": f"M.U.S.E. analyzing {agent_name}'s portrait... (DHQ booting vision model if cold — up to 90s)",
            }
        )
        vision_desc = _step_vision_analysis(ctx.get("canonical_image_path") or "")
        yield _evt(
            {"step": "vision", "status": "done", "result": vision_desc or "(portrait file not found — skipping)"}
        )

        # Step 2 — Agent self-consultation
        yield _evt({"step": "agent", "status": "running", "label": f"Consulting {agent_name} about their identity..."})
        agent_perspective = _step_consult_agent(
            agent_name=agent_name,
            model=ctx.get("model") or "qwen2.5:7b",
            system_prompt=ctx.get("system_prompt") or "",
            title=ctx.get("title") or "",
            department=ctx.get("department") or "",
            current_prompt=current_prompt,
            vision_desc=vision_desc,
            feedback=feedback,
        )
        yield _evt({"step": "agent", "status": "done", "result": agent_perspective or "(agent unavailable — skipping)"})

        # Step 3 — M.U.S.E. synthesis
        yield _evt({"step": "muse", "status": "running", "label": "M.U.S.E. synthesizing all perspectives..."})
        synthesis = _step_muse_synthesize(
            agent_name=agent_name,
            current_prompt=current_prompt,
            vision_desc=vision_desc,
            agent_perspective=agent_perspective,
            feedback=feedback,
            history=history,
        )
        if "error" in synthesis:
            yield _evt({"step": "error", "error": synthesis["error"]})
            return

        yield _evt(
            {
                "step": "complete",
                "refined_prompt": synthesis.get("refined_prompt", ""),
                "explanation": synthesis.get("explanation", ""),
                "vision_description": vision_desc,
                "agent_perspective": agent_perspective,
                "agent_name": agent_name,
                "original_prompt": current_prompt,
            }
        )

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@media_studio_bp.route("/api/portraits/<int:agent_id>/refinement-log", methods=["GET"])
@login_required
def api_refinement_log_get(agent_id):
    """Return all refinement rounds for this agent, newest first."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT id, round_number, feedback, vision_description,
                      agent_perspective, refined_prompt, explanation,
                      accepted, created_at
               FROM portrait_refinement_log
               WHERE agent_id = %s
               ORDER BY created_at DESC LIMIT 50""",
            (agent_id,),
        )
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            rows.append(row)
    return jsonify({"rounds": rows})


@media_studio_bp.route("/api/portraits/<int:agent_id>/refinement-log", methods=["POST"])
@login_required
def api_refinement_log_save(agent_id):
    """Persist a completed refinement round with timestamp.

    JSON: { feedback, vision_description, agent_perspective, refined_prompt, explanation, accepted }
    """
    from database import get_db_cursor

    data = request.get_json(silent=True) or {}
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT COALESCE(MAX(round_number),0)+1 AS next_round FROM portrait_refinement_log WHERE agent_id=%s",
            (agent_id,),
        )
        round_num = cur.fetchone()["next_round"]
        cur.execute(
            """INSERT INTO portrait_refinement_log
               (agent_id, round_number, feedback, vision_description, agent_perspective,
                refined_prompt, explanation, accepted)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (
                agent_id,
                round_num,
                data.get("feedback", ""),
                data.get("vision_description", ""),
                data.get("agent_perspective", ""),
                data.get("refined_prompt", ""),
                data.get("explanation", ""),
                bool(data.get("accepted", False)),
            ),
        )
        row_id = cur.fetchone()[0]
    return jsonify({"id": row_id, "round_number": round_num})


@media_studio_bp.route("/api/portraits/<int:agent_id>/approve", methods=["POST"])
@login_required
def api_approve_canonical(agent_id):
    """Approve an image as the canonical portrait."""
    from .services.portrait_service import approve_canonical

    data = request.get_json()
    if not data or "media_id" not in data:
        return jsonify({"error": "media_id is required"}), 400
    result = approve_canonical(agent_id, data["media_id"])
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/portraits/<int:agent_id>/identity-prompt", methods=["PUT"])
@admin_required
def api_update_identity_prompt(agent_id):
    """Update the identity prompt for an agent."""
    from .services.portrait_service import update_identity_prompt

    data = request.get_json()
    if not data or "prompt" not in data:
        return jsonify({"error": "prompt is required"}), 400
    result = update_identity_prompt(agent_id, data["prompt"])
    if result.get("error"):
        return jsonify(result), 404
    return jsonify(result)


@media_studio_bp.route("/api/portraits/<int:agent_id>/upload", methods=["POST"])
@login_required
def api_upload_portrait(agent_id):
    """Upload an image as the canonical portrait for an agent.

    multipart/form-data body:
      file              — the image (jpeg/png/webp, <= 10 MB)
      identity_prompt   — required; describes the person for variant generation
                          (typically auto-filled via /api/portraits/describe
                          and reviewed/edited by the user before submit)

    Creates a media_library record, inserts/upserts agent_portraits with
    approved=true, and updates agents.avatar_url through agent_service
    (single-writer). Returns the new avatar_url + dimensions on success.
    """
    from .services.portrait_service import (
        ALLOWED_UPLOAD_TYPES,
        MAX_UPLOAD_BYTES,
        upload_canonical,
    )

    if "file" not in request.files:
        return jsonify({"error": "file field required"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "empty file"}), 400
    content_type = (f.mimetype or "").lower()
    if content_type not in ALLOWED_UPLOAD_TYPES:
        return jsonify({"error": f"content_type must be one of {sorted(ALLOWED_UPLOAD_TYPES)}"}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return jsonify({"error": f"file too large (max {MAX_UPLOAD_BYTES} bytes)"}), 413

    identity_prompt = (request.form.get("identity_prompt") or "").strip()
    if not identity_prompt:
        return jsonify({"error": "identity_prompt required"}), 400

    result = upload_canonical(
        agent_id=agent_id,
        file_bytes=file_bytes,
        content_type=content_type,
        identity_prompt=identity_prompt,
        original_filename=f.filename,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@media_studio_bp.route("/api/portraits/describe", methods=["POST"])
@login_required
def api_describe_portrait():
    """Generate an identity_prompt for an uploaded/imported portrait.

    Body: {"image": "<base64>"} OR {"image_path": "<filesystem path>"}
    Returns: {"success": bool, "prompt": str, "model": str, "error": str}

    Used by the #1917 upload flow so imported portraits have an
    identity_prompt (required by IP-Adapter variant generation).
    """
    from .services.portrait_service import describe_portrait

    data = request.get_json(silent=True) or {}
    source = data.get("image") or data.get("image_path") or data.get("image_b64")
    if not source:
        return jsonify({"success": False, "error": "image or image_path required"}), 400

    result = describe_portrait(source)
    status = 200 if result.get("success") else 502
    return jsonify(result), status


# ─── Video ───────────────────────────────────────────────────────────


@media_studio_bp.route("/api/video/generate", methods=["POST"])
@login_required
def api_generate_video():
    """Submit a video generation request (AnimateDiff or external)."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    params = {}
    for k in (
        "model",
        "motion_model",
        "width",
        "height",
        "duration",
        "fps",
        "steps",
        "cfg",
        "sampler",
        "seed",
        "motion_strength",
        "ref_image",
        "provider",
    ):
        if k in data:
            params[k] = data[k]

    result = submit_generation(
        user_id=current_user.id,
        media_type="video",
        prompt=prompt,
        negative_prompt=data.get("negative_prompt", ""),
        params=params,
    )

    if "error" in result:
        return jsonify(result), 400 if "Unsupported" in result["error"] else 500
    return jsonify(result), 201


@media_studio_bp.route("/api/video/providers")
@login_required
def api_video_providers():
    """Get available video providers with configuration status."""
    from .services.generation_service import get_video_providers

    providers = get_video_providers()
    configured = [p for p in providers if p.get("configured")]
    return jsonify(
        {
            "providers": providers,
            "configured_count": len(configured),
            "total_count": len(providers),
        }
    )


# ─── Audio ────────────────────────────────────────────────────────────


@media_studio_bp.route("/api/audio/generate", methods=["POST"])
@login_required
def api_generate_audio():
    """Submit an audio generation request (speech/sfx/music)."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Prompt is required"}), 400

    audio_mode = data.get("audio_mode", "speech")
    if audio_mode not in ("speech", "sfx", "music"):
        return jsonify({"error": "audio_mode must be speech, sfx, or music"}), 400

    if audio_mode == "speech" and not data.get("voice_id"):
        return jsonify({"error": "voice_id is required for speech mode"}), 400

    params = {}
    for k in ("audio_mode", "voice_id", "speed", "language", "duration", "provider", "seed"):
        if k in data:
            params[k] = data[k]

    result = submit_generation(
        user_id=current_user.id,
        media_type="audio",
        prompt=prompt,
        negative_prompt="",
        params=params,
    )

    if "error" in result:
        return jsonify(result), 400 if "Unsupported" in result["error"] else 500
    return jsonify(result), 201


@media_studio_bp.route("/api/audio/voices")
@login_required
def api_audio_voices():
    """Get available TTS voices (presets + custom agent voices)."""
    from .services.tts_service import list_voices

    return jsonify({"voices": list_voices()})


@media_studio_bp.route("/api/audio/voices/upload", methods=["POST"])
@login_required
def api_upload_voice_sample():
    """Upload a custom voice sample for an agent."""
    from .services.tts_service import save_voice_sample

    agent_name = request.form.get("agent_name", "").strip()
    if not agent_name:
        return jsonify({"error": "agent_name is required"}), 400

    if "audio" not in request.files:
        return jsonify({"error": "audio file is required"}), 400

    audio_file = request.files["audio"]
    if not audio_file.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(audio_file.filename)[1].lower()
    if ext not in (".wav", ".mp3"):
        return jsonify({"error": "Only .wav and .mp3 files accepted"}), 400

    result = save_voice_sample(agent_name, audio_file.read(), ext)
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result), 201


@media_studio_bp.route("/api/audio/providers")
@login_required
def api_audio_providers():
    """Get available external audio providers for a mode."""
    from .services.generation_service import get_audio_providers

    mode = request.args.get("mode", "sfx")
    return jsonify({"providers": get_audio_providers(mode)})


# ─── Environments ───────────────────────────────────────────────────


@media_studio_bp.route("/api/environments/generate", methods=["POST"])
@login_required
def api_generate_environment():
    """Generate hub or node background art."""
    from .services.portrait_service import generate_environment

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    target_type = data.get("target_type")
    if target_type not in ("hub", "node"):
        return jsonify({"error": "target_type must be 'hub' or 'node'"}), 400

    result = generate_environment(
        target_type=target_type,
        target_id=data.get("target_id"),
        prompt=data.get("prompt", ""),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201


@media_studio_bp.route("/api/environments/prompts")
@login_required
def api_environment_prompts():
    """Get default environment prompt templates."""
    from .services.portrait_service import get_environment_prompts

    return jsonify({"prompts": get_environment_prompts()})


# ─── Tags ────────────────────────────────────────────────────────────


@media_studio_bp.route("/api/tags")
@login_required
def api_tags():
    """List all tags, optionally filtered by type."""
    from .services.tagging_service import get_tags

    tag_type = request.args.get("type")
    return jsonify({"tags": get_tags(tag_type)})


@media_studio_bp.route("/api/tags", methods=["POST"])
@login_required
def api_create_tag():
    """Create a new tag."""
    from .services.tagging_service import create_tag

    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    tag_type = data.get("tag_type", "user")
    if tag_type not in ("user", "shared"):
        return jsonify({"error": "tag_type must be user or shared"}), 400

    tag_id = create_tag(data["name"], tag_type, current_user.id)
    return jsonify({"id": tag_id, "name": data["name"], "tag_type": tag_type}), 201


@media_studio_bp.route("/api/gallery/<int:media_id>/tags", methods=["POST"])
@login_required
def api_add_tags(media_id):
    """Add tags to a media item."""
    from .services.tagging_service import tag_media

    data = request.get_json()
    if not data or not data.get("tag_ids"):
        return jsonify({"error": "tag_ids is required"}), 400

    tag_media(media_id, data["tag_ids"], "user", current_user.id)
    return jsonify({"status": "tagged"})


@media_studio_bp.route("/api/gallery/<int:media_id>/tags/remove", methods=["POST"])
@login_required
def api_remove_tags(media_id):
    """Remove tags from a media item."""
    from .services.tagging_service import untag_media

    data = request.get_json()
    if not data or not data.get("tag_ids"):
        return jsonify({"error": "tag_ids is required"}), 400

    untag_media(media_id, data["tag_ids"], "user", current_user.id)
    return jsonify({"status": "untagged"})


@media_studio_bp.route("/api/gallery/bulk/tags", methods=["POST"])
@login_required
def api_bulk_tags():
    """Bulk add tags to multiple media items."""
    from .services.tagging_service import bulk_tag

    data = request.get_json()
    if not data or not data.get("media_ids") or not data.get("tag_ids"):
        return jsonify({"error": "media_ids and tag_ids are required"}), 400

    count = bulk_tag(data["media_ids"], data["tag_ids"], "user", current_user.id)
    return jsonify({"count": count})


# ─── Collections ─────────────────────────────────────────────────────


@media_studio_bp.route("/api/collections")
@login_required
def api_collections():
    """List user's collections + shared."""
    from .services.collection_service import list_collections

    include_shared = request.args.get("include_shared", "true").lower() == "true"
    return jsonify({"collections": list_collections("user", current_user.id, include_shared)})


@media_studio_bp.route("/api/collections", methods=["POST"])
@login_required
def api_create_collection():
    """Create a new collection."""
    from .services.collection_service import create_collection

    data = request.get_json()
    if not data or not data.get("name"):
        return jsonify({"error": "name is required"}), 400

    cid = create_collection(
        name=data["name"],
        owner_type="user",
        owner_id=current_user.id,
        description=data.get("description", ""),
        is_shared=data.get("is_shared", False),
    )
    return jsonify({"id": cid, "name": data["name"]}), 201


@media_studio_bp.route("/api/collections/<int:collection_id>", methods=["PUT"])
@login_required
def api_update_collection(collection_id):
    """Update a collection."""
    from .services.collection_service import update_collection

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    ok = update_collection(collection_id, "user", current_user.id, **data)
    if not ok:
        return jsonify({"error": "Not found or no changes"}), 404
    return jsonify({"status": "updated"})


@media_studio_bp.route("/api/collections/<int:collection_id>", methods=["DELETE"])
@login_required
def api_delete_collection(collection_id):
    """Delete a collection (not the media inside)."""
    from .services.collection_service import delete_collection

    ok = delete_collection(collection_id, "user", current_user.id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "deleted"})


@media_studio_bp.route("/api/collections/<int:collection_id>/items")
@login_required
def api_collection_items(collection_id):
    """Paginated items in a collection."""
    from .services.collection_service import get_collection_items

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    return jsonify(get_collection_items(collection_id, "user", current_user.id, page, per_page))


@media_studio_bp.route("/api/collections/<int:collection_id>/items", methods=["POST"])
@login_required
def api_add_to_collection(collection_id):
    """Add media items to a collection."""
    from .services.collection_service import add_to_collection

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = add_to_collection(collection_id, data["media_ids"], "user", current_user.id)
    return jsonify({"count": count}), 201


@media_studio_bp.route("/api/collections/<int:collection_id>/items/remove", methods=["POST"])
@login_required
def api_remove_from_collection(collection_id):
    """Remove media items from a collection."""
    from .services.collection_service import remove_from_collection

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = remove_from_collection(collection_id, data["media_ids"], "user", current_user.id)
    return jsonify({"count": count})


# ─── Smart Collections ───────────────────────────────────────────────


@media_studio_bp.route("/api/smart-collections")
@login_required
def api_smart_collections():
    """List user's smart collections."""
    from .services.collection_service import list_smart_collections

    return jsonify({"smart_collections": list_smart_collections("user", current_user.id)})


@media_studio_bp.route("/api/smart-collections", methods=["POST"])
@login_required
def api_create_smart_collection():
    """Create a smart collection (saved filter preset)."""
    from .services.collection_service import create_smart_collection

    data = request.get_json()
    if not data or not data.get("name") or not data.get("filters"):
        return jsonify({"error": "name and filters are required"}), 400

    sid = create_smart_collection(data["name"], data["filters"], "user", current_user.id)
    return jsonify({"id": sid, "name": data["name"]}), 201


@media_studio_bp.route("/api/smart-collections/<int:smart_id>", methods=["DELETE"])
@login_required
def api_delete_smart_collection(smart_id):
    """Delete a smart collection."""
    from .services.collection_service import delete_smart_collection

    ok = delete_smart_collection(smart_id, "user", current_user.id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"status": "deleted"})


@media_studio_bp.route("/api/smart-collections/<int:smart_id>/results")
@login_required
def api_smart_collection_results(smart_id):
    """Execute a smart collection and return matching media."""
    from .services.collection_service import execute_smart_collection

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    return jsonify(execute_smart_collection(smart_id, "user", current_user.id, page, per_page))


# ─── Search ──────────────────────────────────────────────────────────


@media_studio_bp.route("/api/search")
@login_required
def api_search():
    """Faceted + text + semantic search."""
    from .services.search_service import search_media

    query = request.args.get("q", "").strip()
    filters = {}
    if request.args.get("type"):
        filters["media_type"] = request.args["type"]
    if request.args.get("model"):
        filters["model"] = request.args["model"]
    if request.args.get("provider"):
        filters["provider"] = request.args["provider"]
    if request.args.get("date_from"):
        filters["date_from"] = request.args["date_from"]
    if request.args.get("date_to"):
        filters["date_to"] = request.args["date_to"]
    if request.args.get("min_width"):
        filters["min_width"] = request.args.get("min_width", type=int)
    if request.args.get("min_height"):
        filters["min_height"] = request.args.get("min_height", type=int)
    if request.args.get("tags"):
        try:
            filters["tags"] = [int(t) for t in request.args["tags"].split(",")]
        except ValueError:
            pass
    if request.args.get("collection_id"):
        filters["collection_id"] = request.args.get("collection_id", type=int)

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    return jsonify(search_media("user", current_user.id, query or None, filters or None, page, per_page))


@media_studio_bp.route("/api/search/facets")
@login_required
def api_search_facets():
    """Available filter values for dropdowns."""
    from .services.search_service import get_search_facets

    return jsonify(get_search_facets("user", current_user.id))


# ─── Bulk Operations ─────────────────────────────────────────────────


@media_studio_bp.route("/api/gallery/bulk/favorite", methods=["POST"])
@login_required
def api_bulk_favorite():
    """Bulk set/unset favorite on multiple items."""
    from .services.gallery_service import bulk_set_favorite

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = bulk_set_favorite(data["media_ids"], data.get("state", True), "user", current_user.id)
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/delete", methods=["POST"])
@login_required
def api_bulk_delete():
    """Bulk soft-delete multiple items."""
    from .services.gallery_service import bulk_soft_delete

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    count = bulk_soft_delete(data["media_ids"], "user", current_user.id)
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/move", methods=["POST"])
@login_required
def api_bulk_move():
    """Bulk add items to a collection."""
    from .services.collection_service import add_to_collection

    data = request.get_json()
    if not data or not data.get("media_ids") or not data.get("collection_id"):
        return jsonify({"error": "media_ids and collection_id are required"}), 400

    count = add_to_collection(data["collection_id"], data["media_ids"], "user", current_user.id)
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/reassign", methods=["POST"])
@login_required
def api_bulk_reassign():
    """Bulk reassign media ownership. Admin only."""
    from .services.gallery_service import bulk_reassign

    if not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Admin access required"}), 403

    data = request.get_json()
    if not data or not data.get("media_ids") or not data.get("owner_type"):
        return jsonify({"error": "media_ids, owner_type are required"}), 400

    count = bulk_reassign(data["media_ids"], data["owner_type"], data.get("owner_id"))
    return jsonify({"count": count})


@media_studio_bp.route("/api/gallery/bulk/regenerate", methods=["POST"])
@login_required
def api_bulk_regenerate():
    """Re-queue media items with original generation params."""
    from .services.generation_service import submit_generation

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    from database import get_db_cursor

    queued = 0
    skipped = 0

    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT id, media_type, prompt, negative_prompt, model, seed, width, height, metadata
            FROM media_library
            WHERE id = ANY(%s) AND owner_type = 'user' AND owner_id = %s AND is_deleted = false
            """,
            (data["media_ids"], current_user.id),
        )
        rows = cur.fetchall()

    for row in rows:
        if not row["prompt"]:
            skipped += 1
            continue

        params = {}
        if row["model"]:
            params["model"] = row["model"]
        if row["width"]:
            params["width"] = row["width"]
        if row["height"]:
            params["height"] = row["height"]
        # Merge stored metadata params
        meta = row["metadata"] or {}
        for k in ("steps", "cfg", "sampler", "audio_mode", "voice_id", "duration", "fps"):
            if k in meta:
                params[k] = meta[k]

        result = submit_generation(
            user_id=current_user.id,
            media_type=row["media_type"],
            prompt=row["prompt"],
            negative_prompt=row.get("negative_prompt", ""),
            params=params,
        )
        if "error" not in result:
            queued += 1
        else:
            skipped += 1

    return jsonify({"queued": queued, "skipped": skipped})


# ─── Export ──────────────────────────────────────────────────────────


@media_studio_bp.route("/api/export", methods=["POST"])
@login_required
def api_create_export():
    """Start a ZIP export job."""
    from .services.export_service import create_export_job

    data = request.get_json()
    if not data or not data.get("media_ids"):
        return jsonify({"error": "media_ids is required"}), 400

    job_id = create_export_job(data["media_ids"], "user", current_user.id)
    if not job_id:
        return jsonify({"error": "Invalid media IDs or ownership mismatch"}), 400
    return jsonify({"job_id": job_id}), 201


@media_studio_bp.route("/api/export/<int:job_id>")
@login_required
def api_export_status(job_id):
    """Get export job status."""
    from .services.export_service import get_export_status

    result = get_export_status(job_id, "user", current_user.id)
    if not result:
        return jsonify({"error": "Not found"}), 404
    return jsonify(result)


# ─── Batch Generation ────────────────────────────────────────────────


@media_studio_bp.route("/api/batches", methods=["POST"])
@login_required
def api_create_batch():
    """Create a batch generation job."""
    from .services.batch_service import create_batch

    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    result = create_batch(
        name=data.get("name", ""),
        owner_type="user",
        owner_id=current_user.id,
        media_type=data.get("media_type", "image"),
        prompts=data.get("prompts", []),
        base_params=data.get("base_params", {}),
        sweep_param=data.get("sweep_param"),
        sweep_values=data.get("sweep_values"),
    )
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result), 201


@media_studio_bp.route("/api/batches", methods=["GET"])
@login_required
def api_list_batches():
    """List user's batches."""
    from .services.batch_service import list_batches

    status = request.args.get("status")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 10))
    return jsonify(list_batches("user", current_user.id, status=status, page=page, per_page=per_page))


@media_studio_bp.route("/api/batches/<int:batch_id>", methods=["GET"])
@login_required
def api_get_batch(batch_id):
    """Get batch details with items."""
    from .services.batch_service import get_batch, get_batch_items

    batch = get_batch(batch_id, "user", current_user.id)
    if not batch:
        return jsonify({"error": "Batch not found"}), 404
    items = get_batch_items(batch_id, "user", current_user.id)
    return jsonify({"batch": batch, "items": items})


@media_studio_bp.route("/api/batches/<int:batch_id>/cancel", methods=["POST"])
@login_required
def api_cancel_batch(batch_id):
    """Cancel remaining items in a batch."""
    from .services.batch_service import cancel_batch

    cancelled = cancel_batch(batch_id, "user", current_user.id)
    return jsonify({"cancelled": cancelled})


@media_studio_bp.route("/api/batches/<int:batch_id>/retry", methods=["POST"])
@login_required
def api_retry_batch(batch_id):
    """Retry failed items in a batch."""
    from .services.batch_service import retry_batch_failed

    retried = retry_batch_failed(batch_id, "user", current_user.id)
    return jsonify({"retried": retried})


# ─── Queue Management ────────────────────────────────────────────────


@media_studio_bp.route("/api/queue", methods=["GET"])
@login_required
def api_get_queue():
    """Get paginated queue entries."""
    from .services.batch_service import get_queue_entries

    status = request.args.get("status")
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    return jsonify(get_queue_entries("user", current_user.id, status=status, page=page, per_page=per_page))


@media_studio_bp.route("/api/queue/<int:queue_id>/retry", methods=["POST"])
@login_required
def api_retry_queue_item(queue_id):
    """Retry a single failed queue entry."""
    from .services.batch_service import retry_single

    success = retry_single(queue_id, "user", current_user.id)
    if not success:
        return jsonify({"error": "Item not found or not failed"}), 404
    return jsonify({"status": "retried"})


@media_studio_bp.route("/api/queue/<int:queue_id>/cancel", methods=["POST"])
@login_required
def api_cancel_queue_item(queue_id):
    """Cancel a single pending/dispatched queue entry."""
    from .services.batch_service import cancel_single

    success = cancel_single(queue_id, "user", current_user.id)
    if not success:
        return jsonify({"error": "Item not found or not cancellable"}), 404
    return jsonify({"status": "cancelled"})


@media_studio_bp.route("/api/queue/stats", methods=["GET"])
@login_required
def api_queue_stats():
    """Get queue statistics."""
    from .services.batch_service import get_queue_stats

    return jsonify(get_queue_stats("user", current_user.id))


@media_studio_bp.route("/api/queue/clear-completed", methods=["POST"])
@login_required
def api_clear_completed():
    """Clear completed queue entries older than 1 hour."""
    from .services.batch_service import clear_completed

    cleared = clear_completed("user", current_user.id)
    return jsonify({"cleared": cleared})


# ── S21  Agent Config & Gallery ─────────────────────────────────────────


@media_studio_bp.route("/api/agent-config", methods=["GET"])
@login_required
def api_get_agent_config():
    """List all agent media configurations."""
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM media_agent_config ORDER BY agent_name")
        cols = [d[0] for d in cur.description]
        configs = [dict(zip(cols, row)) for row in cur.fetchall()]
    for c in configs:
        for k, v in c.items():
            if hasattr(v, "isoformat"):
                c[k] = v.isoformat()
    return jsonify(configs)


@media_studio_bp.route("/api/agent-config/<agent_name>", methods=["PUT"])
@login_required
def api_update_agent_config(agent_name):
    """Update or create agent media config."""
    import psycopg2.extras
    from database import get_db_cursor

    data = request.get_json() or {}
    allowed = [
        "enabled",
        "media_type",
        "schedule_cron",
        "default_prompt",
        "default_negative",
        "default_params",
        "daily_cap",
        "gallery_visibility",
    ]
    sets = []
    vals = []
    for key in allowed:
        if key in data:
            sets.append(f"{key} = %s")
            val = data[key]
            if key == "default_params":
                val = psycopg2.extras.Json(val)
            vals.append(val)
    if not sets:
        return jsonify({"error": "No valid fields to update"}), 400

    sets.append("updated_at = NOW()")
    vals.append(agent_name)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE media_agent_config SET {', '.join(sets)} " f"WHERE agent_name = %s RETURNING id",
            vals,
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                """INSERT INTO media_agent_config (agent_name, enabled, media_type,
                   schedule_cron, default_prompt, default_negative, default_params,
                   daily_cap, gallery_visibility)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    agent_name,
                    data.get("enabled", False),
                    data.get("media_type", "image"),
                    data.get("schedule_cron", "0 */4 * * *"),
                    data.get("default_prompt", ""),
                    data.get("default_negative", ""),
                    psycopg2.extras.Json(data.get("default_params", {})),
                    data.get("daily_cap", 10),
                    data.get("gallery_visibility", "private"),
                ),
            )
    return jsonify({"success": True})


@media_studio_bp.route("/api/agent-config/<agent_name>/trigger", methods=["POST"])
@login_required
def api_trigger_agent_generation(agent_name):
    """Manually trigger agent media generation."""
    from tools.media_studio.services.agent_media_service import agent_generate

    result = agent_generate(agent_name)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route(
    "/api/agent-config/<agent_name>/publish/<int:generation_id>",
    methods=["POST"],
)
@login_required
def api_publish_agent_generation(agent_name, generation_id):
    """Publish an agent generation to shared gallery."""
    from tools.media_studio.services.agent_media_service import publish_generation

    result = publish_generation(generation_id, agent_name)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


# ── S22  Image Editing ──


@media_studio_bp.route("/api/media-studio/edit", methods=["POST"])
@login_required
def api_submit_edit():
    from tools.media_studio.services.edit_service import submit_edit

    data = request.get_json() or {}
    source_id = data.get("source_id")
    edit_type = data.get("edit_type")
    params = data.get("params", {})
    mask_data = data.get("mask_data")
    if not source_id or not edit_type:
        return jsonify({"error": "source_id and edit_type are required"}), 400
    result = submit_edit(
        source_id=source_id,
        edit_type=edit_type,
        params=params,
        mask_data=mask_data,
        owner_type="user",
        owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/edit/<int:edit_id>", methods=["GET"])
@login_required
def api_get_edit_status(edit_id):
    from tools.media_studio.services.edit_service import get_edit_status

    result = get_edit_status(edit_id)
    if result is None:
        return jsonify({"error": "Edit not found"}), 404
    for k, v in list(result.items()):
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/versions/<int:media_id>", methods=["GET"])
@login_required
def api_get_versions(media_id):
    from tools.media_studio.services.edit_service import get_versions

    versions = get_versions(media_id)
    for v in versions:
        for k, val in list(v.items()):
            if hasattr(val, "isoformat"):
                v[k] = val.isoformat()
    return jsonify(versions)


@media_studio_bp.route("/api/media-studio/edit/upload-mask", methods=["POST"])
@login_required
def api_upload_mask():
    import base64

    from tools.media_studio.services.edit_service import _save_mask

    if "mask" not in request.files:
        return jsonify({"error": "No mask file provided"}), 400
    mask_file = request.files["mask"]
    mask_b64 = base64.b64encode(mask_file.read()).decode("utf-8")
    mask_path = _save_mask(mask_b64, source_id=0)
    return jsonify({"mask_path": mask_path})


# ── S23  Workflow Templates ──


@media_studio_bp.route("/api/media-studio/templates", methods=["POST"])
@login_required
def api_create_template():
    from tools.media_studio.services.template_service import create_template

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    result = create_template(
        name=name,
        description=data.get("description", ""),
        steps=data.get("steps", []),
        owner_type="user",
        owner_id=current_user.id,
        visibility=data.get("visibility", "private"),
        tags=data.get("tags"),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/templates", methods=["GET"])
@login_required
def api_list_templates():
    from tools.media_studio.services.template_service import list_templates

    visibility = request.args.get("visibility")
    owner_type = request.args.get("owner_type")
    tag = request.args.get("tag")
    templates = list_templates(
        owner_type=owner_type or "user",
        owner_id=current_user.id,
        visibility_filter=visibility,
        tag_filter=tag,
    )
    for t in templates:
        for k, v in list(t.items()):
            if hasattr(v, "isoformat"):
                t[k] = v.isoformat()
    return jsonify(templates)


@media_studio_bp.route("/api/media-studio/templates/<int:template_id>", methods=["GET"])
@login_required
def api_get_template(template_id):
    from tools.media_studio.services.template_service import get_template

    result = get_template(template_id)
    if result is None:
        return jsonify({"error": "Template not found"}), 404
    for k, v in list(result.items()):
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    if "steps" in result:
        for s in result["steps"]:
            for k, v in list(s.items()):
                if hasattr(v, "isoformat"):
                    s[k] = v.isoformat()
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/templates/<int:template_id>", methods=["PUT"])
@login_required
def api_update_template(template_id):
    from tools.media_studio.services.template_service import update_template

    data = request.get_json() or {}
    result = update_template(template_id, "user", current_user.id, data)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/templates/<int:template_id>", methods=["DELETE"])
@login_required
def api_delete_template(template_id):
    from tools.media_studio.services.template_service import delete_template

    result = delete_template(template_id, "user", current_user.id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/templates/<int:template_id>/clone", methods=["POST"])
@login_required
def api_clone_template(template_id):
    from tools.media_studio.services.template_service import clone_template

    result = clone_template(template_id, "user", current_user.id)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/templates/<int:template_id>/run", methods=["POST"])
@login_required
def api_run_pipeline(template_id):
    from tools.media_studio.services.pipeline_executor import execute_pipeline

    data = request.get_json() or {}
    result = execute_pipeline(
        template_id=template_id,
        overrides=data.get("overrides"),
        owner_type="user",
        owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/pipeline/<int:execution_id>", methods=["GET"])
@login_required
def api_get_pipeline_status(execution_id):
    from tools.media_studio.services.pipeline_executor import get_pipeline_status

    result = get_pipeline_status(execution_id)
    if result is None:
        return jsonify({"error": "Execution not found"}), 404
    for k, v in list(result.items()):
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    return jsonify(result)


# ── S24  Media Analytics ──


@media_studio_bp.route("/api/media-studio/analytics/realtime", methods=["GET"])
@login_required
def api_analytics_realtime():
    from tools.media_studio.services.analytics_service import get_realtime_stats

    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_realtime_stats(date_from=date_from, date_to=date_to)
    else:
        result = get_realtime_stats(
            owner_type="user",
            owner_id=current_user.id,
            date_from=date_from,
            date_to=date_to,
        )
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/analytics/trends", methods=["GET"])
@login_required
def api_analytics_trends():
    from tools.media_studio.services.analytics_service import get_trend_data

    period = request.args.get("period", "hourly")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_trend_data(period, "global", 0, date_from, date_to)
    else:
        result = get_trend_data(period, "user", current_user.id, date_from, date_to)
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/analytics/models", methods=["GET"])
@login_required
def api_analytics_models():
    from tools.media_studio.services.analytics_service import get_model_breakdown

    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_model_breakdown("global", 0, date_from, date_to)
    else:
        result = get_model_breakdown("user", current_user.id, date_from, date_to)
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/analytics/costs", methods=["GET"])
@login_required
def api_analytics_costs():
    from tools.media_studio.services.analytics_service import get_cost_summary

    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    mode = request.args.get("mode", "fixed")
    scope = request.args.get("scope", "user")
    if scope == "global" and getattr(current_user, "is_admin", False):
        result = get_cost_summary("global", 0, date_from, date_to, mode)
    else:
        result = get_cost_summary("user", current_user.id, date_from, date_to, mode)
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/analytics/cost-rates", methods=["GET"])
@login_required
def api_get_cost_rates():
    if not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Admin access required"}), 403
    from tools.media_studio.services.analytics_service import get_cost_rates

    rates = get_cost_rates()
    for r in rates:
        for k, v in list(r.items()):
            if hasattr(v, "isoformat"):
                r[k] = v.isoformat()
    return jsonify(rates)


@media_studio_bp.route("/api/media-studio/analytics/cost-rates/<model_name>", methods=["PUT"])
@login_required
def api_update_cost_rate(model_name):
    if not getattr(current_user, "is_admin", False):
        return jsonify({"error": "Admin access required"}), 403
    from tools.media_studio.services.analytics_service import update_cost_rate

    data = request.get_json() or {}
    result = update_cost_rate(
        model_name,
        cost_per_generation=data.get("cost_per_generation"),
        vram_gb_per_sec=data.get("vram_gb_per_sec"),
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


# ── S25  Social Media Publishing ──


@media_studio_bp.route("/api/media-studio/share", methods=["POST"])
@login_required
def api_share_to_social():
    from tools.social_media.publishing_service import publish_from_media_studio

    data = request.get_json() or {}
    media_library_id = data.get("media_library_id")
    platforms = data.get("platforms", [])
    caption = data.get("caption")
    schedule_at = data.get("schedule_at")
    if not media_library_id:
        return jsonify({"error": "media_library_id is required"}), 400
    if not platforms:
        return jsonify({"error": "At least one platform is required"}), 400
    result = publish_from_media_studio(
        media_library_id=media_library_id,
        platforms=platforms,
        caption=caption,
        schedule_at=schedule_at,
        owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@media_studio_bp.route("/api/media-studio/share/bulk", methods=["POST"])
@login_required
def api_bulk_share_to_social():
    from tools.social_media.publishing_service import bulk_publish_from_media_studio

    data = request.get_json() or {}
    media_library_ids = data.get("media_library_ids", [])
    platforms = data.get("platforms", [])
    if not media_library_ids:
        return jsonify({"error": "media_library_ids is required"}), 400
    if not platforms:
        return jsonify({"error": "At least one platform is required"}), 400
    result = bulk_publish_from_media_studio(
        media_library_ids=media_library_ids,
        platforms=platforms,
        owner_id=current_user.id,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


# ---------------------------------------------------------------------------
# AutoShorts — social_video_queue routes
# ---------------------------------------------------------------------------


@media_studio_bp.route("/api/social-video/queue")
@login_required
def api_sv_queue():
    """List social video queue items."""
    from .services.social_video_service import svq_list

    status = request.args.get("status") or None
    return jsonify({"items": svq_list(status=status)})


@media_studio_bp.route("/api/social-video/queue", methods=["POST"])
@login_required
def api_sv_create():
    """Create a new social video queue item."""
    from .services.social_video_service import svq_create

    data = request.get_json() or {}
    if not data.get("quote_text") and not data.get("title"):
        return jsonify({"error": "title or quote_text required"}), 400
    item = svq_create(
        title=data.get("title", "Untitled"),
        quote_text=data.get("quote_text", ""),
        media_ids=data.get("media_ids", []),
        audio_mode=data.get("audio_mode", "music"),
        platform=data.get("platform", "linkedin"),
        scheduled_at=data.get("scheduled_at"),
        user_id=current_user.id,
        theme_id=data.get("theme_id"),
    )
    return jsonify(item), 201


@media_studio_bp.route("/api/social-video/queue/<int:item_id>/status", methods=["PUT"])
@login_required
def api_sv_update_status(item_id):
    """Update status of a social video queue item."""
    from .services.social_video_service import svq_update_status

    data = request.get_json() or {}
    ok = svq_update_status(item_id, data.get("status", ""))
    if not ok:
        return jsonify({"error": "invalid status or not found"}), 400
    return jsonify({"status": data.get("status")})


# ─── Content Themes ─────────────────────────────────────────────────


@media_studio_bp.route("/api/themes")
@login_required
def api_get_themes():
    """Return all active content themes with curator name and scene count."""
    from .services.theme_service import get_all_themes

    return jsonify({"themes": get_all_themes()})


@media_studio_bp.route("/api/themes/<int:theme_id>/scenes")
@login_required
def api_get_theme_scenes(theme_id):
    """Return a theme and all its scenes."""
    from .services.theme_service import get_scenes_for_theme, get_theme

    theme = get_theme(theme_id)
    if not theme:
        return jsonify({"error": "not found"}), 404
    return jsonify({"theme": theme, "scenes": get_scenes_for_theme(theme_id)})


@media_studio_bp.route("/api/themes/<int:theme_id>", methods=["PATCH"])
@login_required
def api_update_theme(theme_id):
    """Update theme tone, hashtags, music_mood, accent_color, or is_active."""
    from .services.theme_service import update_theme

    data = request.get_json() or {}
    updated = update_theme(theme_id, **data)
    if not updated:
        return jsonify({"error": "not found or no valid fields"}), 400
    return jsonify(updated)


# ─── Lifestyle / Social Content Generation ───────────────────────


@media_studio_bp.route("/api/generate/lifestyle", methods=["POST"])
@login_required
def api_generate_lifestyle():
    """Generate a lifestyle/selfie/announcement image for an agent using a theme scene.

    Body: {agent_id, scene_id, generation_type: lifestyle|selfie|announcement, refine: bool}
    Returns: {queue_id, status, prompt, refined_prompt, caption, agent, scene, generation_type}
    """
    from .services.lifestyle_service import generate_lifestyle_content

    data = request.get_json() or {}
    agent_id = data.get("agent_id")
    scene_id = data.get("scene_id")
    generation_type = data.get("generation_type", "lifestyle")
    refine = data.get("refine", True)

    if not agent_id or not scene_id:
        return jsonify({"error": "agent_id and scene_id required"}), 400
    if generation_type not in ("lifestyle", "selfie", "announcement"):
        return jsonify({"error": "generation_type must be lifestyle, selfie, or announcement"}), 400

    result = generate_lifestyle_content(
        user_id=current_user.id,
        agent_id=int(agent_id),
        scene_id=int(scene_id),
        generation_type=generation_type,
        refine=refine,
    )
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result), 201
