"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

@media_hub_bp.route("/")
def index():
    """Media Hub main page"""
    services = get_all_services()
    return render_template("tools/media_hub.html", services=services, host=MEDIA_HOST)

@media_hub_bp.route("/api/health")
def api_health():
    """Health check endpoint — queries real service status from DB"""
    try:
        with get_db_cursor(cursor_factory=None, commit=False) as (conn, cur):
            cur.execute(
                """SELECT service_type, health_status, health_message, last_health_check
                   FROM media_hub_services WHERE is_enabled = true"""
            )
            columns = [desc[0] for desc in cur.description] if cur.description else []
            services = [dict(zip(columns, row)) for row in cur.fetchall()]

            if not services:
                return jsonify(
                    {
                        "module": "media_hub",
                        "status": "active",
                        "healthy": True,
                        "message": "No services configured",
                        "services": [],
                    }
                )

            unhealthy = [s for s in services if s["health_status"] != "healthy"]
            healthy = len(unhealthy) == 0
            service_summary = [
                {
                    "type": s["service_type"],
                    "status": s["health_status"],
                    "message": s["health_message"],
                }
                for s in services
            ]

            return jsonify(
                {
                    "module": "media_hub",
                    "status": "active",
                    "healthy": healthy,
                    "message": f"{len(services) - len(unhealthy)}/{len(services)} services healthy",
                    "services": service_summary,
                }
            )
    except Exception as e:
        return jsonify(
            {
                "module": "media_hub",
                "status": "error",
                "healthy": False,
                "message": str(e),
            }
        )

@media_hub_bp.route("/api/status")
def api_status():
    """Get status of all media services"""
    services = get_all_services()
    statuses = {}

    for service in services:
        service_type = service["service_type"]
        config = get_service_config(service_type)

        status = {
            "id": service["id"],
            "name": service["name"],
            "host": service["host"],
            "port": service["port"],
            "is_enabled": service["is_enabled"],
            "is_primary": service["is_primary"],
            "has_api_key": service["has_api_key"],
            "health_status": service["health_status"],
            "health_message": service["health_message"],
            "online": False,
            "url": f"http{'s' if service['use_ssl'] else ''}://{service['host']}:{service['port']}",
        }

        # Test connection if API key exists
        if config and config.get("api_key") and service["is_enabled"]:
            try:
                client = get_service_client(
                    service_type,
                    config["host"],
                    config["port"],
                    config["api_key"],
                    config["use_ssl"],
                )
                if hasattr(client, "probe"):
                    status["online"], status["health_message"] = client.probe()
                else:
                    status["online"] = client.test_connection()
                status["health_status"] = "healthy" if status["online"] else "unhealthy"
            except Exception as e:
                logger.error(f"Error testing {service_type}: {e}")
                status["health_message"] = str(e)

        statuses[service_type] = status

    return jsonify(
        {
            "success": True,
            "services": statuses,
            "encryption_key_source": get_key_source(),
        }
    )

@media_hub_bp.route("/api/search")
def api_search():
    """
    Smart search - searches local library first, then discovery services.
    Returns results with 'in_library' flag.
    """
    query = request.args.get("q", "").strip()
    media_type = request.args.get("type")  # 'movie', 'tv', or None for all

    if not query or len(query) < 2:
        return jsonify({"success": False, "error": "Query too short", "results": []})

    results = []
    library_tmdb_ids: set = set()
    library_title_keys: set = set()  # (title.lower(), year) fallback dedup
    library_results_by_tkey: dict = {}  # tkey -> index in results (for tmdb_id merge)

    def _tkey(d: dict) -> tuple:
        return (str(d.get("title") or "").lower(), d.get("year"))

    # 1. Search ALL configured media servers (Plex + Jellyfin), primary first
    for media_server, server_type in get_all_media_servers():
        try:
            library_results = media_server.search_library(query, media_type)
            for item in library_results[:20]:
                item_dict = item.to_dict()
                tkey = _tkey(item_dict)
                if (item.tmdb_id and item.tmdb_id in library_tmdb_ids) or tkey in library_title_keys:
                    continue  # already found on another server
                item_dict["source"] = server_type
                item_dict["in_library"] = True
                library_results_by_tkey[tkey] = len(results)
                results.append(item_dict)
                if item.tmdb_id:
                    library_tmdb_ids.add(item.tmdb_id)
                library_title_keys.add(tkey)
        except Exception as e:
            logger.error(f"Library search error ({server_type}): {e}")

    # 2. Search Overseerr/Jellyseerr for discovery
    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if overseerr_config and overseerr_config.get("api_key"):
        try:
            from .clients.overseerr import OverseerrClient

            overseerr = OverseerrClient(
                host=overseerr_config["host"],
                port=overseerr_config["port"],
                api_key=overseerr_config["api_key"],
                use_ssl=overseerr_config["use_ssl"],
            )
            discovery_results = overseerr.search(query)

            for item in discovery_results:
                item_dict_check = item.to_dict()
                tkey_check = _tkey(item_dict_check)
                if item.tmdb_id and item.tmdb_id in library_tmdb_ids:
                    continue  # already in library with correct tmdb_id

                if tkey_check in library_title_keys:
                    # Library item exists but may lack tmdb_id — merge it in
                    if item.tmdb_id:
                        idx = library_results_by_tkey.get(tkey_check)
                        if idx is not None:
                            results[idx]["tmdb_id"] = item.tmdb_id
                            if item.imdb_id:
                                results[idx]["imdb_id"] = item.imdb_id
                            library_tmdb_ids.add(item.tmdb_id)
                    continue

                item_dict_check["source"] = "overseerr"
                results.append(item_dict_check)

                # Limit total results
                if len(results) >= 30:
                    break

        except Exception as e:
            logger.error(f"Overseerr search error: {e}")

    # Enrich results with missing metadata from TMDB
    results = enrich_items_with_tmdb(results)

    return jsonify({"success": True, "query": query, "results": results, "total": len(results)})

@media_hub_bp.route("/api/library/recent")
@cached_response(60)
def api_library_recent():
    """Get recently added items from library"""
    limit = request.args.get("limit", 20, type=int)

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_recent_additions(limit)
        items_dict = [item.to_dict() for item in items]

        # Enrich items with missing metadata from TMDB
        items_dict = enrich_items_with_tmdb(items_dict)

        return jsonify({"success": True, "items": items_dict, "source": server_type})
    except Exception as e:
        logger.error(f"Error getting recent additions: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})

@media_hub_bp.route("/api/library/stats")
def api_library_stats():
    """Get library statistics with caching"""
    force_refresh = request.args.get("refresh", "false").lower() == "true"
    current_time = time.time()

    # Check cache validity
    cache_valid = (
        _stats_cache["data"] is not None
        and (current_time - _stats_cache["timestamp"]) < _stats_cache["ttl"]
        and not force_refresh
    )

    if cache_valid:
        return jsonify(
            {
                "success": True,
                "stats": _stats_cache["data"]["stats"],
                "source": _stats_cache["data"]["source"],
                "cached": True,
                "cache_age": int(current_time - _stats_cache["timestamp"]),
            }
        )

    # Fetch fresh stats
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify(
            {
                "success": False,
                "error": "No media server configured",
                "stats": {
                    "movie_count": 0,
                    "show_count": 0,
                    "episode_count": 0,
                    "total_size_bytes": 0,
                },
            }
        )

    try:
        stats = media_server.get_library_stats()
        stats_dict = stats.to_dict()

        # Update cache
        _stats_cache["data"] = {"stats": stats_dict, "source": server_type}
        _stats_cache["timestamp"] = current_time

        return jsonify(
            {
                "success": True,
                "stats": stats_dict,
                "source": server_type,
                "cached": False,
            }
        )
    except Exception as e:
        logger.error(f"Error getting library stats: {e}")
        # Return cached data if available, even if stale
        if _stats_cache["data"] is not None:
            return jsonify(
                {
                    "success": True,
                    "stats": _stats_cache["data"]["stats"],
                    "source": _stats_cache["data"]["source"],
                    "cached": True,
                    "stale": True,
                }
            )
        return jsonify({"success": False, "error": str(e), "stats": {}})

@media_hub_bp.route("/api/cache/clear", methods=["POST"])
def api_clear_cache():
    """Clear library stats cache"""
    _stats_cache["data"] = None
    _stats_cache["timestamp"] = 0
    return jsonify({"success": True, "message": "Cache cleared"})

@media_hub_bp.route("/api/cache/status")
def api_cache_status():
    """Get cache status"""
    current_time = time.time()
    if _stats_cache["data"] is None:
        return jsonify(
            {
                "success": True,
                "cached": False,
                "message": "No cached data",
            }
        )

    age = int(current_time - _stats_cache["timestamp"])
    ttl_remaining = max(0, _stats_cache["ttl"] - age)

    return jsonify(
        {
            "success": True,
            "cached": True,
            "age_seconds": age,
            "ttl_remaining": ttl_remaining,
            "ttl_total": _stats_cache["ttl"],
            "expires_in": f"{ttl_remaining // 60}m {ttl_remaining % 60}s",
        }
    )

@media_hub_bp.route("/api/library/movies")
@cached_response(120)
def api_library_movies():
    """Get all movies with pagination and sorting, enriched with TMDB data"""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    sort = request.args.get("sort", "added")  # added, title, year, rating

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_all_movies(limit, offset, sort)
        items_data = [item.to_dict() for item in items]

        # Enrich items missing poster/overview with TMDB data
        items_data = enrich_items_with_tmdb(items_data)

        return jsonify(
            {
                "success": True,
                "items": items_data,
                "source": server_type,
                "limit": limit,
                "offset": offset,
                "sort": sort,
            }
        )
    except Exception as e:
        logger.error(f"Error getting movies: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})

@media_hub_bp.route("/api/library/shows")
@cached_response(120)
def api_library_shows():
    """Get all TV shows with pagination and sorting, enriched with TMDB data"""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    sort = request.args.get("sort", "added")  # added, title, year, rating

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_all_shows(limit, offset, sort)
        items_data = [item.to_dict() for item in items]

        # Enrich items missing poster/overview with TMDB data
        items_data = enrich_items_with_tmdb(items_data)

        return jsonify(
            {
                "success": True,
                "items": items_data,
                "source": server_type,
                "limit": limit,
                "offset": offset,
                "sort": sort,
            }
        )
    except Exception as e:
        logger.error(f"Error getting shows: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})

@media_hub_bp.route("/api/shows/<series_id>/seasons")
def api_show_seasons(series_id):
    """Get seasons for a TV series"""
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "seasons": []})

    try:
        # Check if the client has get_seasons method (Jellyfin)
        if hasattr(media_server, "get_seasons"):
            seasons = media_server.get_seasons(series_id)
            return jsonify({"success": True, "seasons": seasons, "source": server_type})
        else:
            return jsonify({"success": False, "error": "Seasons not supported", "seasons": []})
    except Exception as e:
        logger.error(f"Error getting seasons: {e}")
        return jsonify({"success": False, "error": str(e), "seasons": []})

@media_hub_bp.route("/api/shows/<series_id>/episodes")
def api_show_episodes(series_id):
    """Get episodes for a TV series, optionally filtered by season"""
    season = request.args.get("season", type=int)

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "episodes": []})

    try:
        # Check if the client has get_episodes method (Jellyfin)
        if hasattr(media_server, "get_episodes"):
            episodes = media_server.get_episodes(series_id, season)
            return jsonify({"success": True, "episodes": episodes, "source": server_type})
        else:
            return jsonify({"success": False, "error": "Episodes not supported", "episodes": []})
    except Exception as e:
        logger.error(f"Error getting episodes: {e}")
        return jsonify({"success": False, "error": str(e), "episodes": []})

@media_hub_bp.route("/api/episodes/<episode_id>/next")
def api_next_episode(episode_id):
    """Resolve the next episode after the given one, for autoplay-next-episode."""
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "episode": None})

    try:
        if hasattr(media_server, "get_next_episode"):
            next_ep = media_server.get_next_episode(episode_id)
            return jsonify({"success": True, "episode": next_ep, "source": server_type})
        return jsonify({"success": False, "error": "Not supported", "episode": None})
    except Exception as e:
        logger.error(f"Error getting next episode: {e}")
        return jsonify({"success": False, "error": str(e), "episode": None})

@media_hub_bp.route("/api/episodes/<episode_id>/watched", methods=["POST"])
def api_toggle_episode_watched(episode_id):
    """Toggle watched status for an episode - syncs to all configured servers"""
    from .clients.plex import PlexClient
    from .clients.jellyfin import JellyfinClient

    data = request.get_json() or {}
    watched = data.get("watched", True)
    results = {"plex": None, "jellyfin": None}

    # Try to update Plex
    plex_config = get_service_config("plex")
    if plex_config and plex_config.get("api_key"):
        try:
            plex_client = PlexClient(
                host=plex_config["host"],
                port=plex_config["port"],
                api_key=plex_config["api_key"],
                use_ssl=plex_config.get("use_ssl", False),
            )
            results["plex"] = plex_client.mark_watched(episode_id, watched)
        except Exception as e:
            logger.warning(f"Failed to sync watched to Plex: {e}")
            results["plex"] = False

    # Try to update Jellyfin
    jellyfin_config = get_service_config("jellyfin")
    if jellyfin_config and jellyfin_config.get("api_key"):
        try:
            jellyfin_client = JellyfinClient(
                host=jellyfin_config["host"],
                port=jellyfin_config["port"],
                api_key=jellyfin_config["api_key"],
                use_ssl=jellyfin_config.get("use_ssl", False),
            )
            results["jellyfin"] = jellyfin_client.mark_watched(episode_id, watched)
        except Exception as e:
            logger.warning(f"Failed to sync watched to Jellyfin: {e}")
            results["jellyfin"] = False

    # Success if at least one server was updated
    success = any(r is True for r in results.values())
    return jsonify(
        {
            "success": success,
            "watched": watched,
            "sync_results": results,
        }
    )

@media_hub_bp.route("/api/media/<media_type>/<media_id>")
def api_media_details(media_type, media_id):
    """Get detailed information about a specific media item"""
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured"})

    try:
        item = media_server.get_media_details(media_id)
        if item:
            return jsonify({"success": True, "item": item.to_dict(), "source": server_type})
        else:
            return jsonify({"success": False, "error": "Media not found"}), 404
    except Exception as e:
        logger.error(f"Error getting media details: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
