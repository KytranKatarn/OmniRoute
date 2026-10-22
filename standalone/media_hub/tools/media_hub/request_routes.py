"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

@media_hub_bp.route("/api/requests")
def api_requests():
    """Get media requests from Overseerr/Jellyseerr, enriched with TMDB data and deduplicated"""
    status = request.args.get("status")  # 'pending', 'approved', 'available', etc.

    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if not overseerr_config or not overseerr_config.get("api_key"):
        return jsonify({"success": False, "error": "Overseerr not configured", "requests": []})

    try:
        from .clients.overseerr import OverseerrClient
        from .clients.tmdb import TMDBClient

        overseerr = OverseerrClient(
            host=overseerr_config["host"],
            port=overseerr_config["port"],
            api_key=overseerr_config["api_key"],
            use_ssl=overseerr_config["use_ssl"],
        )
        requests_list = overseerr.get_requests(status)
        requests_dict = [r.to_dict() for r in requests_list]

        # Deduplicate by tmdb_id, keeping the most recent request
        seen_tmdb_ids = {}
        deduplicated = []
        for req in requests_dict:
            tmdb_id = req.get("tmdb_id")
            if tmdb_id:
                if tmdb_id not in seen_tmdb_ids:
                    seen_tmdb_ids[tmdb_id] = req
                    deduplicated.append(req)
                else:
                    # Keep the one with better status or more recent
                    existing = seen_tmdb_ids[tmdb_id]
                    status_priority = {
                        "completed": 5,
                        "available": 4,
                        "processing": 3,
                        "approved": 2,
                        "pending": 1,
                        "declined": 0,
                    }
                    if status_priority.get(req.get("status"), 0) > status_priority.get(existing.get("status"), 0):
                        deduplicated.remove(existing)
                        seen_tmdb_ids[tmdb_id] = req
                        deduplicated.append(req)
            else:
                deduplicated.append(req)

        # Enrich requests with TMDB data
        tmdb = TMDBClient()
        if tmdb.is_configured():
            for req in deduplicated:
                tmdb_id = req.get("tmdb_id")
                if tmdb_id:
                    try:
                        if req["media_type"] == "movie":
                            details = tmdb.get_movie_details(tmdb_id)
                        else:
                            details = tmdb.get_tv_details(tmdb_id)

                        if details:
                            if req.get("title") == "Unknown":
                                req["title"] = details.get("title", "Unknown")
                            if not req.get("year"):
                                req["year"] = details.get("year")
                            if not req.get("poster_url"):
                                req["poster_url"] = details.get("poster_url")
                            if not req.get("backdrop_url"):
                                req["backdrop_url"] = details.get("backdrop_url")
                            # Always update these for richer display
                            req["overview"] = details.get("overview", "")
                            req["rating"] = details.get("rating")
                            req["runtime"] = details.get("runtime")
                            req["genres"] = details.get("genres", [])
                            req["tagline"] = details.get("tagline", "")
                    except Exception as e:
                        logger.debug(f"TMDB enrichment failed for request {req.get('id')}: {e}")

        # Fallback: fetch poster from Overseerr detail endpoint for items
        # still missing poster_url (happens when TMDB API key is not configured)
        for req in deduplicated:
            if not req.get("poster_url") and req.get("tmdb_id"):
                try:
                    media_type = "tv" if req.get("media_type") in ("show", "tv") else "movie"
                    detail = overseerr.get_media_status(req["tmdb_id"], media_type)
                    if detail and detail.get("posterPath"):
                        req["poster_url"] = f"https://image.tmdb.org/t/p/w342{detail['posterPath']}"
                    if detail and not req.get("title") or req.get("title") == "Unknown":
                        req["title"] = detail.get("title") or detail.get("name") or req.get("title", "Unknown")
                except Exception:
                    pass

        return jsonify({"success": True, "requests": deduplicated})
    except Exception as e:
        logger.error(f"Error getting requests: {e}")
        return jsonify({"success": False, "error": str(e), "requests": []})

@media_hub_bp.route("/api/requests/queue-progress")
def api_requests_queue_progress():
    """Return download percentage per tmdb_id for items currently in
    Radarr/Sonarr queues. Used by the requests tab to show progress bars."""
    progress = {}

    for service_type, arr_type in [("radarr", "movie"), ("sonarr", "tv")]:
        cfg = get_service_config(service_type)
        if not cfg or not cfg.get("api_key"):
            continue
        try:
            import requests as req_lib

            scheme = "https" if cfg["use_ssl"] else "http"
            r = req_lib.get(
                f"{scheme}://{cfg['host']}:{cfg['port']}/api/v3/queue"
                "?pageSize=50&includeMovie=true&includeSeries=true",
                headers={"X-Api-Key": cfg["api_key"]},
                timeout=5,
            )
            if r.status_code != 200:
                continue
            for item in r.json().get("records", []):
                tmdb_id = (item.get("movie") or {}).get("tmdbId") or (item.get("series") or {}).get("tmdbId")
                size = item.get("size", 0)
                sizeleft = item.get("sizeleft", 0)
                if tmdb_id and size > 0:
                    pct = round((1 - sizeleft / size) * 100)
                    progress[str(tmdb_id)] = {
                        "percent": max(0, min(100, pct)),
                        "eta": item.get("timeleft"),
                        "status": item.get("trackedDownloadState"),
                    }
        except Exception as e:
            logger.debug(f"queue-progress {service_type} error: {e}")

    return jsonify({"success": True, "progress": progress})

@media_hub_bp.route("/api/requests", methods=["POST"])
def api_create_request():
    """Create a new media request"""
    data = request.get_json() or {}
    media_type = data.get("media_type")  # 'movie' or 'tv'
    tmdb_id = data.get("tmdb_id")
    seasons = data.get("seasons")  # List of season numbers for TV

    if not media_type or not tmdb_id:
        return (
            jsonify({"success": False, "error": "media_type and tmdb_id required"}),
            400,
        )

    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if not overseerr_config or not overseerr_config.get("api_key"):
        return jsonify({"success": False, "error": "Overseerr not configured"}), 400

    try:
        from .clients.overseerr import OverseerrClient

        overseerr = OverseerrClient(
            host=overseerr_config["host"],
            port=overseerr_config["port"],
            api_key=overseerr_config["api_key"],
            use_ssl=overseerr_config["use_ssl"],
        )
        result = overseerr.create_request(media_type, tmdb_id, seasons)
        if not result or result.get("error"):
            err = result.get("error", "Overseerr rejected the request") if result else "No response from Overseerr"
            logger.error(f"Overseerr create_request failed: {err}")
            return jsonify({"success": False, "error": err}), 502
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error(f"Error creating request: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@media_hub_bp.route("/api/requests/<int:request_id>", methods=["DELETE"])
@media_hub_admin_required
def api_delete_request(request_id):
    """Delete a media request"""
    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if not overseerr_config or not overseerr_config.get("api_key"):
        return jsonify({"success": False, "error": "Overseerr not configured"}), 400

    try:
        from .clients.overseerr import OverseerrClient

        overseerr = OverseerrClient(
            host=overseerr_config["host"],
            port=overseerr_config["port"],
            api_key=overseerr_config["api_key"],
            use_ssl=overseerr_config["use_ssl"],
        )
        if overseerr.delete_request(request_id):
            return jsonify({"success": True})
        else:
            return jsonify({"success": False, "error": "Failed to delete request"}), 500
    except Exception as e:
        logger.error(f"Error deleting request: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@media_hub_bp.route("/api/requests/history")
@login_required
def api_requests_history():
    """Completed/available requests from Overseerr — used by the History tab."""
    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if not overseerr_config or not overseerr_config.get("api_key"):
        return jsonify({"success": False, "error": "Overseerr not configured", "requests": []})

    try:
        from .clients.overseerr import OverseerrClient
        from .clients.tmdb import TMDBClient

        overseerr = OverseerrClient(
            host=overseerr_config["host"],
            port=overseerr_config["port"],
            api_key=overseerr_config["api_key"],
            use_ssl=overseerr_config["use_ssl"],
        )

        # Fetch all requests; filter client-side to available/completed
        all_requests = overseerr.get_requests()
        history = [r.to_dict() for r in all_requests if r.status in ("available", "completed")]

        # Enrich with TMDB metadata
        tmdb = TMDBClient()
        if tmdb.is_configured():
            for req in history:
                tmdb_id = req.get("tmdb_id")
                if not tmdb_id:
                    continue
                try:
                    details = (
                        tmdb.get_movie_details(tmdb_id)
                        if req["media_type"] == "movie"
                        else tmdb.get_tv_details(tmdb_id)
                    )
                    if details:
                        for field in ("poster_url", "backdrop_url", "overview", "rating", "genres", "runtime"):
                            if details.get(field) and not req.get(field):
                                req[field] = details[field]
                except Exception:
                    pass

        history.sort(key=lambda r: r.get("requested_at") or "", reverse=True)
        return jsonify({"success": True, "requests": history, "total": len(history)})
    except Exception as e:
        logger.error(f"Error getting request history: {e}")
        return jsonify({"success": False, "error": str(e), "requests": []})

@media_hub_bp.route("/api/requests/<int:request_id>/retry", methods=["POST"])
def api_retry_request(request_id):
    """Trigger a search retry for a request in Radarr/Sonarr"""
    import requests as http_requests

    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if not overseerr_config:
        return jsonify({"success": False, "error": "Overseerr not configured"}), 400

    try:
        # Get request details from Overseerr to find media type and IDs
        from .clients.overseerr import OverseerrClient

        overseerr = OverseerrClient(
            host=overseerr_config["host"],
            port=overseerr_config["port"],
            api_key=overseerr_config["api_key"],
            use_ssl=overseerr_config["use_ssl"],
        )

        # Get all requests and find the one we need
        all_requests = overseerr.get_requests()
        target_req = None
        for req in all_requests:
            if str(req.id) == str(request_id):
                target_req = req
                break

        if not target_req:
            return jsonify({"success": False, "error": "Request not found"}), 404

        # Trigger search in appropriate *arr service
        if target_req.media_type == "movie":
            radarr_config = get_service_config("radarr")
            if not radarr_config:
                return (
                    jsonify({"success": False, "error": "Radarr not configured"}),
                    400,
                )

            # Find movie in Radarr by TMDB ID
            base_url = f"http://{radarr_config['host']}:{radarr_config['port']}"
            headers = {"X-Api-Key": radarr_config["api_key"]}

            movies_resp = http_requests.get(f"{base_url}/api/v3/movie", headers=headers, timeout=10)
            movies = movies_resp.json()

            movie_id = None
            for m in movies:
                if m.get("tmdbId") == target_req.tmdb_id:
                    movie_id = m.get("id")
                    break

            if not movie_id:
                return (
                    jsonify({"success": False, "error": "Movie not found in Radarr"}),
                    404,
                )

            # Trigger search
            search_resp = http_requests.post(
                f"{base_url}/api/v3/command",
                headers=headers,
                json={"name": "MoviesSearch", "movieIds": [movie_id]},
                timeout=10,
            )
            if search_resp.status_code == 201:
                return jsonify({"success": True, "message": "Search triggered"})
            else:
                return (
                    jsonify({"success": False, "error": "Failed to trigger search"}),
                    500,
                )
        else:
            # TV show - use Sonarr
            sonarr_config = get_service_config("sonarr")
            if not sonarr_config:
                return (
                    jsonify({"success": False, "error": "Sonarr not configured"}),
                    400,
                )

            base_url = f"http://{sonarr_config['host']}:{sonarr_config['port']}"
            headers = {"X-Api-Key": sonarr_config["api_key"]}

            # Find series by TVDB ID
            series_resp = http_requests.get(f"{base_url}/api/v3/series", headers=headers, timeout=10)
            series_list = series_resp.json()

            series_id = None
            for s in series_list:
                if s.get("tvdbId") == target_req.tvdb_id or s.get("tmdbId") == target_req.tmdb_id:
                    series_id = s.get("id")
                    break

            if not series_id:
                return (
                    jsonify({"success": False, "error": "Series not found in Sonarr"}),
                    404,
                )

            # Trigger search
            search_resp = http_requests.post(
                f"{base_url}/api/v3/command",
                headers=headers,
                json={"name": "SeriesSearch", "seriesId": series_id},
                timeout=10,
            )
            if search_resp.status_code == 201:
                return jsonify({"success": True, "message": "Search triggered"})
            else:
                return (
                    jsonify({"success": False, "error": "Failed to trigger search"}),
                    500,
                )

    except Exception as e:
        logger.error(f"Error retrying request: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@media_hub_bp.route("/api/requests/<int:request_id>/check-library", methods=["POST"])
def api_check_library_status(request_id):
    """Check if a requested item is in the library and update Overseerr status"""
    import requests as http_requests

    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if not overseerr_config:
        return jsonify({"success": False, "error": "Overseerr not configured"}), 400

    try:
        base_url = f"http://{overseerr_config['host']}:{overseerr_config['port']}"
        headers = {
            "X-Api-Key": overseerr_config["api_key"],
            "Content-Type": "application/json",
        }

        # Get all requests and find the target (individual endpoint requires session auth)
        resp = http_requests.get(
            f"{base_url}/api/v1/request",
            headers=headers,
            params={"take": 100},
            timeout=10,
        )
        resp.raise_for_status()
        all_requests = resp.json().get("results", [])

        # Find the target request
        req_data = None
        for req in all_requests:
            if req.get("id") == request_id:
                req_data = req
                break

        if not req_data:
            return jsonify({"success": False, "error": "Request not found"}), 404

        media = req_data.get("media", {})
        media_id = media.get("id")
        media_type = req_data.get("type", "movie")
        tmdb_id = media.get("tmdbId")
        current_media_status = media.get("status", 0)

        # Get title from TMDB since Overseerr doesn't include it in raw response
        title = "Unknown"
        if tmdb_id:
            try:
                from .clients.tmdb import TMDBClient

                tmdb = TMDBClient()
                if tmdb.is_configured():
                    if media_type == "movie":
                        details = tmdb.get_movie_details(tmdb_id)
                    else:
                        details = tmdb.get_tv_details(tmdb_id)
                    if details:
                        title = details.get("title") or details.get("name") or "Unknown"
            except Exception as e:
                logger.debug(f"TMDB title lookup failed: {e}")

        if not media_id:
            return (
                jsonify({"success": False, "error": "No media ID found in request"}),
                400,
            )

        # Check if request has failed (status 4) - re-request it
        request_status = req_data.get("status", 0)
        if request_status == 4:  # FAILED
            # Delete the failed request
            delete_resp = http_requests.delete(f"{base_url}/api/v1/request/{request_id}", headers=headers, timeout=10)

            if delete_resp.status_code == 200:
                # Create a new request
                new_req_resp = http_requests.post(
                    f"{base_url}/api/v1/request",
                    headers=headers,
                    json={"mediaType": media_type, "mediaId": tmdb_id},
                    timeout=10,
                )

                if new_req_resp.status_code in (200, 201):
                    new_req = new_req_resp.json()
                    return jsonify(
                        {
                            "success": True,
                            "re_requested": True,
                            "new_request_id": new_req.get("id"),
                            "message": f"'{title}' was re-requested. New request created.",
                        }
                    )
                else:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": f"Failed to create new request: {new_req_resp.text}",
                            }
                        ),
                        500,
                    )
            else:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Failed to delete old request: {delete_resp.text}",
                        }
                    ),
                    500,
                )

        # If already available, no need to update
        if current_media_status == 5:
            return jsonify(
                {
                    "success": True,
                    "in_library": True,
                    "already_available": True,
                    "message": f"'{title}' is already marked as available",
                }
            )

        # Check library for this item
        media_server, server_type = get_primary_media_server()
        if not media_server:
            return (
                jsonify({"success": False, "error": "No media server configured"}),
                400,
            )

        found_in_library = False
        search_type = "movie" if media_type == "movie" else "show"

        results = media_server.search_library(title, media_type=search_type)
        for item in results:
            title_match = item.title.lower().strip() == title.lower().strip()
            tmdb_match = item.tmdb_id and tmdb_id and str(item.tmdb_id) == str(tmdb_id)
            if title_match or tmdb_match:
                found_in_library = True
                break

        if found_in_library:
            # Directly update media status to AVAILABLE (5) using POST /media/{mediaId}/status
            status_resp = http_requests.post(
                f"{base_url}/api/v1/media/{media_id}/status",
                headers=headers,
                json={"status": 5},  # 5 = AVAILABLE
                timeout=10,
            )

            if status_resp.status_code == 200:
                return jsonify(
                    {
                        "success": True,
                        "in_library": True,
                        "status_updated": True,
                        "message": f"'{title}' found in library and marked as available!",
                    }
                )
            else:
                logger.warning(f"Failed to update media status: {status_resp.status_code} - {status_resp.text}")
                return jsonify(
                    {
                        "success": True,
                        "in_library": True,
                        "status_updated": False,
                        "message": f"'{title}' found in library but status update failed: {status_resp.text}",
                    }
                )
        else:
            return jsonify(
                {
                    "success": True,
                    "in_library": False,
                    "message": f"'{title}' not found in library yet",
                }
            )

    except Exception as e:
        logger.error(f"Error checking library status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
