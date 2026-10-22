"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

def _arr_base(cfg):
    scheme = "https" if cfg.get("use_ssl") else "http"
    return f"{scheme}://{cfg['host']}:{cfg['port']}/api/v3"

def _delete_library_item(media_type, tmdb_id=None, title=None, year=None, dry_run=False):
    """Resolve + delete a movie (Radarr) or show (Sonarr) INCLUDING its files.

    Returns {success, deleted|would_delete|error, ...}. A normal 'not found' comes
    back as success=False (not an exception) so callers can surface it cleanly.
    """
    import requests as _rq

    mt = (media_type or "").lower()
    tmdb_id = int(tmdb_id) if str(tmdb_id or "").strip().isdigit() else None

    if mt == "movie":
        cfg = get_service_config("radarr")
        if not cfg or not cfg.get("api_key"):
            return {"success": False, "error": "Radarr not configured"}
        cl = get_service_client("radarr", cfg["host"], cfg["port"], cfg["api_key"], cfg["use_ssl"])
        movie = cl.get_movie_by_tmdb_id(tmdb_id) if tmdb_id else None
        if not movie:
            return {"success": False, "error": "Movie not found in Radarr (not managed here?)"}
        mid, mtitle = movie.get("id"), movie.get("title", title)
        if dry_run:
            return {"success": True, "would_delete": {"type": "movie", "id": mid, "title": mtitle}}
        r = _rq.delete(
            f"{_arr_base(cfg)}/movie/{mid}", headers={"X-Api-Key": cfg["api_key"]},
            params={"deleteFiles": "true", "addImportExclusion": "false"}, timeout=30,
        )
        ok = r.status_code in (200, 202)
        return {"success": ok, "deleted": {"type": "movie", "id": mid, "title": mtitle},
                "status": r.status_code}

    if mt in ("tv", "show", "series"):
        cfg = get_service_config("sonarr")
        if not cfg or not cfg.get("api_key"):
            return {"success": False, "error": "Sonarr not configured"}
        cl = get_service_client("sonarr", cfg["host"], cfg["port"], cfg["api_key"], cfg["use_ssl"])
        series_list = cl.get_series() or []
        match = None
        if tmdb_id:
            match = next((s for s in series_list if str(s.get("tmdbId") or "") == str(tmdb_id)), None)
        if not match and title:
            t = title.strip().lower()
            # Collect ALL title matches (year-filtered when a year is given) and REFUSE
            # on ambiguity instead of deleting the FIRST hit — two same-titled shows
            # ('The Office' US/UK, 'Battlestar Galactica' 1978/2003) must never resolve
            # to the wrong series + deleteFiles=true. The admin gate / Telegram approval
            # verify a title LABEL, not the resolved id, so the guard belongs HERE.
            # (Adversarial review, project #385 task #4745 — wrong-item deletion.)
            cands = [
                s for s in series_list
                if (s.get("title") or "").strip().lower() == t
                and (not year or str(s.get("year") or "") == str(year))
            ]
            if len(cands) > 1:
                return {"success": False,
                        "error": "Ambiguous title — multiple shows match; specify tmdb_id or year"}
            match = cands[0] if cands else None
        if not match:
            return {"success": False, "error": "Show not found in Sonarr (not managed here?)"}
        sid, stitle = match.get("id"), match.get("title", title)
        if dry_run:
            return {"success": True, "would_delete": {"type": "series", "id": sid, "title": stitle}}
        r = _rq.delete(
            f"{_arr_base(cfg)}/series/{sid}", headers={"X-Api-Key": cfg["api_key"]},
            params={"deleteFiles": "true", "addImportListExclusion": "false"}, timeout=30,
        )
        ok = r.status_code in (200, 202)
        return {"success": ok, "deleted": {"type": "series", "id": sid, "title": stitle},
                "status": r.status_code}

    return {"success": False, "error": "media_type must be 'movie' or 'tv'"}

@media_hub_bp.route("/api/library/delete", methods=["POST"])
@media_hub_admin_required
def api_library_delete():
    """Remove a movie/show from the library — deletes the arr record AND its files.
    ADMIN ONLY. Destructive: the UI enforces a DOUBLE 'are you sure?' before calling.
    Body: {media_type:'movie'|'tv', tmdb_id?, title?, year?, dry_run?}."""
    data = request.get_json() or {}
    res = _delete_library_item(
        media_type=data.get("media_type"),
        tmdb_id=data.get("tmdb_id"),
        title=data.get("title"),
        year=data.get("year"),
        dry_run=bool(data.get("dry_run")),
    )
    err = (res.get("error") or "").lower()
    code = 200 if res.get("success") else (404 if "not found" in err else 400)
    if res.get("deleted"):
        logger.warning("library delete performed: %s", res["deleted"])
    return jsonify(res), code

@media_hub_bp.route("/api/maven/remove", methods=["POST"])
@media_hub_admin_required
def api_maven_remove():
    """Ask M.A.V.E.N. to remove a movie/show — routes through an A.R.C.H.I.E.
    Telegram approval BEFORE anything is deleted (agent-initiated destructive
    action). Returns the approval_id; the maven_removal_executor job performs the
    delete once you approve. Body: {media_type, tmdb_id?, title?, year?, reason?}."""
    data = request.get_json() or {}
    try:
        from maven_manager import request_removal
    except Exception as e:
        return jsonify({"success": False, "error": f"maven_manager unavailable: {e}"}), 500
    res = request_removal(
        media_type=data.get("media_type"),
        tmdb_id=data.get("tmdb_id"),
        title=data.get("title"),
        year=data.get("year"),
        reason=data.get("reason") or "M.A.V.E.N. removal request",
    )
    return jsonify(res), (200 if res.get("success") else 400)

@media_hub_bp.route("/api/library/remove", methods=["POST"])
@login_required
def api_library_remove():
    """Role-aware removal — available to ANY authenticated user (task #4746).

      • admin        → deletes the movie/show + files immediately (_delete_library_item).
      • regular user → raises an A.R.C.H.I.E. Telegram approval to Kytran
        (maven_manager.request_removal). NOTHING is deleted until Kytran approves;
        the maven_removal_executor job performs the delete on approval.

    The item is dry-run-resolved first so a bad title/id returns 404 to the user
    instead of pinging Kytran with a phantom approval. Body: {media_type, tmdb_id?,
    title?, year?}. Returns {mode:'deleted'|'requested', ...}."""
    data = request.get_json() or {}
    media_type = data.get("media_type")
    tmdb_id = data.get("tmdb_id")
    title = data.get("title")
    year = data.get("year")

    # Admin → delete immediately.
    if getattr(current_user, "is_admin", False):
        res = _delete_library_item(media_type=media_type, tmdb_id=tmdb_id, title=title, year=year)
        if res.get("deleted"):
            logger.warning("library remove (admin direct): %s", res["deleted"])
        res["mode"] = "deleted"
        err = (res.get("error") or "").lower()
        code = 200 if res.get("success") else (404 if "not found" in err else 400)
        return jsonify(res), code

    # Regular user → validate the item resolves, THEN raise a Telegram approval.
    check = _delete_library_item(
        media_type=media_type, tmdb_id=tmdb_id, title=title, year=year, dry_run=True
    )
    if not check.get("success"):
        err = (check.get("error") or "").lower()
        return jsonify({"success": False, "mode": "requested", "error": check.get("error")}), (
            404 if "not found" in err else 400
        )
    try:
        from maven_manager import request_removal
    except Exception as e:  # noqa: BLE001
        return jsonify({"success": False, "error": f"approval unavailable: {e}"}), 500
    who = getattr(current_user, "username", None) or getattr(current_user, "id", "a user")
    res = request_removal(
        media_type=media_type, tmdb_id=tmdb_id, title=title, year=year,
        reason=f"Removal requested by {who}",
    )
    res["mode"] = "requested"
    return jsonify(res), (200 if res.get("success") else 400)

@media_hub_bp.route("/api/tdarr/status")
@login_required
def api_tdarr_status():
    """Tdarr engine status + the node farm (hub CPU + Starship GPUs)."""
    import tdarr_client

    return jsonify({
        "success": True,
        "up": tdarr_client.is_up(),
        "status": tdarr_client.status(),
        "nodes": tdarr_client.nodes(),
    })

@media_hub_bp.route("/api/tdarr/review", methods=["POST"])
@media_hub_admin_required
def api_tdarr_review():
    """Scan the Tdarr library + report space-optimize candidates (admin). Notifies A.R.C.H.I.E."""
    from maven_manager import video_review

    data = request.get_json(silent=True) or {}
    res = video_review(min_gb=float(data.get("min_gb", 4.0)))
    return jsonify(res), (200 if res.get("success") else 400)

@media_hub_bp.route("/api/tdarr/optimize", methods=["POST"])
@login_required
def api_tdarr_optimize():
    """Request a space-saving HEVC transcode of a file — ALWAYS Telegram-approved
    (destructive: replaces the original), for admins and regular users alike. Kytran
    approves; the maven_optimize_executor job then queues it on Tdarr. Body:
    {file_id, title?, resolution?, est_savings_gb?}."""
    from maven_manager import request_optimize

    data = request.get_json() or {}
    who = getattr(current_user, "username", None) or getattr(current_user, "id", "a user")
    res = request_optimize(
        file_id=data.get("file_id"),
        title=data.get("title"),
        resolution=data.get("resolution"),
        est_savings_gb=data.get("est_savings_gb"),
        reason=f"Optimize requested by {who}",
    )
    return jsonify(res), (200 if res.get("success") else 400)
