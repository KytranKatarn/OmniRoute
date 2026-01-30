"""
Media Hub Routes
================
API endpoints for Media Hub module.

Provides unified access to Plex/Jellyfin library, Sonarr/Radarr management,
Overseerr requests, and SABnzbd downloads.
"""

from flask import render_template, jsonify, request
from . import media_hub_bp
from .encryption import encrypt_api_key, decrypt_api_key, get_key_source
from .discovery import discover_all_api_keys
from .services import get_service_client
import logging
import traceback
import time

logger = logging.getLogger(__name__)

# Host configuration
MEDIA_HOST = "192.168.1.200"

# Cache for library stats (reduces API calls to media server)
_stats_cache = {
    "data": None,
    "timestamp": 0,
    "ttl": 3600,  # 1 hour cache TTL
}

# Cache for TMDB metadata enrichment
_tmdb_enrichment_cache = {}


def enrich_items_with_tmdb(items: list) -> list:
    """
    Enrich items with missing metadata from TMDB.
    Checks if items are missing poster/overview and fetches from TMDB.
    """
    from .clients.tmdb import TMDBClient

    tmdb = TMDBClient()
    if not tmdb.is_configured():
        return items

    enriched = []
    for item in items:
        # Check if item needs enrichment (missing poster or overview)
        needs_enrichment = not item.get("poster_url") or not item.get("overview") or item.get("overview") == ""

        if needs_enrichment and item.get("title"):
            # Clean title for search (remove suffixes like "(US)")
            title = item.get("title", "")
            clean_title = title.replace(" (US)", "").replace(" (UK)", "").strip()
            cache_key = f"{item.get('media_type', 'movie')}:{clean_title}"

            # Check cache first
            if cache_key in _tmdb_enrichment_cache:
                cached = _tmdb_enrichment_cache[cache_key]
                if cached:
                    item = {**item, **cached}
                    logger.debug(f"Using cached TMDB data for '{title}'")
            else:
                # Search TMDB
                try:
                    media_type = item.get("media_type", "movie")

                    if media_type == "show":
                        results = tmdb.search_tv(clean_title, year=item.get("year"))
                    else:
                        results = tmdb.search_movies(clean_title, year=item.get("year"))

                    if results and results.get("results"):
                        # Find best match (first result usually best)
                        match = results["results"][0]
                        enrichment = {}

                        # TMDB client already formats poster_url/backdrop_url
                        if not item.get("poster_url") and match.get("poster_url"):
                            enrichment["poster_url"] = match["poster_url"]

                        if not item.get("backdrop_url") and match.get("backdrop_url"):
                            enrichment["backdrop_url"] = match["backdrop_url"]

                        if (not item.get("overview") or item.get("overview") == "") and match.get("overview"):
                            enrichment["overview"] = match["overview"]

                        if not item.get("rating") and match.get("rating"):
                            enrichment["rating"] = match["rating"]
                            enrichment["rating_source"] = "tmdb"

                        if not item.get("year") and match.get("year"):
                            enrichment["year"] = match["year"]

                        if not item.get("tmdb_id") and match.get("tmdb_id"):
                            enrichment["tmdb_id"] = match["tmdb_id"]

                        # Cache the enrichment
                        _tmdb_enrichment_cache[cache_key] = enrichment if enrichment else None

                        if enrichment:
                            item = {**item, **enrichment}
                            logger.info(f"Enriched '{title}' with TMDB metadata: {list(enrichment.keys())}")
                    else:
                        _tmdb_enrichment_cache[cache_key] = None
                        logger.debug(f"No TMDB results for '{clean_title}'")
                except Exception as e:
                    logger.warning(f"TMDB enrichment failed for '{title}': {e}")
                    _tmdb_enrichment_cache[cache_key] = None

        enriched.append(item)

    return enriched


def get_db():
    """Get database connection"""
    from database import get_db as db_get_db

    return db_get_db()


def get_service_config(service_type: str) -> dict:
    """Get service configuration from database"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, service_type, name, host, port, use_ssl, api_key_encrypted,
                   is_primary, is_enabled, config_path, health_status
            FROM media_hub_services
            WHERE service_type = %s AND is_enabled = TRUE
            ORDER BY is_primary DESC
            LIMIT 1
        """,
            (service_type,),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row:
            return {
                "id": row[0],
                "service_type": row[1],
                "name": row[2],
                "host": row[3],
                "port": row[4],
                "use_ssl": row[5],
                "api_key": decrypt_api_key(row[6]) if row[6] else None,
                "is_primary": row[7],
                "is_enabled": row[8],
                "config_path": row[9],
                "health_status": row[10],
            }
    except Exception as e:
        logger.error(f"Error getting service config: {e}")

    return None


def get_all_services() -> list:
    """Get all service configurations"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, service_type, name, host, port, use_ssl, api_key_encrypted,
                   is_primary, is_enabled, config_path, health_status, health_message,
                   last_health_check
            FROM media_hub_services
            ORDER BY service_type
        """
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        services = []
        for row in rows:
            services.append(
                {
                    "id": row[0],
                    "service_type": row[1],
                    "name": row[2],
                    "host": row[3],
                    "port": row[4],
                    "use_ssl": row[5],
                    "has_api_key": row[6] is not None,
                    "is_primary": row[7],
                    "is_enabled": row[8],
                    "config_path": row[9],
                    "health_status": row[10],
                    "health_message": row[11],
                    "last_health_check": row[12].isoformat() if row[12] else None,
                }
            )
        return services
    except Exception as e:
        logger.error(f"Error getting services: {e}")
        return []


def get_primary_media_server():
    """Get the primary media server client (Plex or Jellyfin)"""
    from .clients.plex import PlexClient
    from .clients.jellyfin import JellyfinClient

    # Check which server is marked as primary
    services = get_all_services()
    primary_type = None
    for svc in services:
        if svc.get("is_primary") and svc.get("service_type") in ("plex", "jellyfin"):
            primary_type = svc.get("service_type")
            break

    # Try primary server first
    if primary_type == "jellyfin":
        config = get_service_config("jellyfin")
        if config and config.get("api_key"):
            try:
                return (
                    JellyfinClient(
                        host=config["host"], port=config["port"], api_key=config["api_key"], use_ssl=config["use_ssl"]
                    ),
                    "jellyfin",
                )
            except Exception as e:
                logger.error(f"Failed to create Jellyfin client: {e}")

    # Try Plex (either as primary or fallback)
    config = get_service_config("plex")
    if config and config.get("api_key"):
        try:
            return (
                PlexClient(
                    host=config["host"], port=config["port"], api_key=config["api_key"], use_ssl=config["use_ssl"]
                ),
                "plex",
            )
        except Exception as e:
            logger.error(f"Failed to create Plex client: {e}")

    # Try Jellyfin as fallback
    config = get_service_config("jellyfin")
    if config and config.get("api_key"):
        try:
            return (
                JellyfinClient(
                    host=config["host"], port=config["port"], api_key=config["api_key"], use_ssl=config["use_ssl"]
                ),
                "jellyfin",
            )
        except Exception as e:
            logger.error(f"Failed to create Jellyfin client: {e}")

    return None, None


# =============================================================================
# PAGE ROUTES
# =============================================================================


@media_hub_bp.route("/")
def index():
    """Media Hub main page"""
    services = get_all_services()
    return render_template("tools/media_hub.html", services=services, host=MEDIA_HOST)


# =============================================================================
# HEALTH & STATUS ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/health")
def api_health():
    """Health check endpoint for module registry"""
    return jsonify(
        {"module": "media_hub", "status": "active", "healthy": True, "message": "Media Hub module operational"}
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
                    service_type, config["host"], config["port"], config["api_key"], config["use_ssl"]
                )
                status["online"] = client.test_connection()
                status["health_status"] = "healthy" if status["online"] else "unhealthy"
            except Exception as e:
                logger.error(f"Error testing {service_type}: {e}")
                status["health_message"] = str(e)

        statuses[service_type] = status

    return jsonify({"success": True, "services": statuses, "encryption_key_source": get_key_source()})


# =============================================================================
# SEARCH ENDPOINTS
# =============================================================================


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
    library_ids = set()  # Track items found in library

    # 1. Search local library first (Plex/Jellyfin)
    media_server, server_type = get_primary_media_server()
    if media_server:
        try:
            library_results = media_server.search_library(query, media_type)
            for item in library_results[:20]:
                item_dict = item.to_dict()
                item_dict["source"] = server_type
                item_dict["in_library"] = True
                results.append(item_dict)

                # Track by TMDB ID for deduplication
                if item.tmdb_id:
                    library_ids.add(item.tmdb_id)
        except Exception as e:
            logger.error(f"Library search error: {e}")

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
                # Skip if already in library
                if item.tmdb_id and item.tmdb_id in library_ids:
                    continue

                item_dict = item.to_dict()
                item_dict["source"] = "overseerr"
                results.append(item_dict)

                # Limit total results
                if len(results) >= 30:
                    break

        except Exception as e:
            logger.error(f"Overseerr search error: {e}")

    # Enrich results with missing metadata from TMDB
    results = enrich_items_with_tmdb(results)

    return jsonify({"success": True, "query": query, "results": results, "total": len(results)})


# =============================================================================
# LIBRARY ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/library/recent")
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
    global _stats_cache
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
                "stats": {"movie_count": 0, "show_count": 0, "episode_count": 0, "total_size_bytes": 0},
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
    global _stats_cache
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
def api_library_movies():
    """Get all movies with pagination"""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_all_movies(limit, offset)
        return jsonify(
            {
                "success": True,
                "items": [item.to_dict() for item in items],
                "source": server_type,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        logger.error(f"Error getting movies: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})


@media_hub_bp.route("/api/library/shows")
def api_library_shows():
    """Get all TV shows with pagination"""
    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_all_shows(limit, offset)
        return jsonify(
            {
                "success": True,
                "items": [item.to_dict() for item in items],
                "source": server_type,
                "limit": limit,
                "offset": offset,
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


# =============================================================================
# REQUEST ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/requests")
def api_requests():
    """Get media requests from Overseerr/Jellyseerr"""
    status = request.args.get("status")  # 'pending', 'approved', 'available', etc.

    overseerr_config = get_service_config("overseerr") or get_service_config("jellyseerr")
    if not overseerr_config or not overseerr_config.get("api_key"):
        return jsonify({"success": False, "error": "Overseerr not configured", "requests": []})

    try:
        from .clients.overseerr import OverseerrClient

        overseerr = OverseerrClient(
            host=overseerr_config["host"],
            port=overseerr_config["port"],
            api_key=overseerr_config["api_key"],
            use_ssl=overseerr_config["use_ssl"],
        )
        requests_list = overseerr.get_requests(status)
        return jsonify({"success": True, "requests": [r.to_dict() for r in requests_list]})
    except Exception as e:
        logger.error(f"Error getting requests: {e}")
        return jsonify({"success": False, "error": str(e), "requests": []})


@media_hub_bp.route("/api/requests", methods=["POST"])
def api_create_request():
    """Create a new media request"""
    data = request.get_json() or {}
    media_type = data.get("media_type")  # 'movie' or 'tv'
    tmdb_id = data.get("tmdb_id")
    seasons = data.get("seasons")  # List of season numbers for TV

    if not media_type or not tmdb_id:
        return jsonify({"success": False, "error": "media_type and tmdb_id required"}), 400

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
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error(f"Error creating request: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# CALENDAR ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/calendar/upcoming")
def api_calendar_upcoming():
    """Get upcoming episodes from Sonarr"""
    days = request.args.get("days", 7, type=int)

    sonarr_config = get_service_config("sonarr")
    if not sonarr_config or not sonarr_config.get("api_key"):
        return jsonify({"success": False, "error": "Sonarr not configured", "episodes": []})

    try:
        from .clients.sonarr import SonarrClient

        sonarr = SonarrClient(
            host=sonarr_config["host"],
            port=sonarr_config["port"],
            api_key=sonarr_config["api_key"],
            use_ssl=sonarr_config["use_ssl"],
        )
        episodes = sonarr.get_upcoming_episodes(days)
        return jsonify({"success": True, "episodes": [ep.to_dict() for ep in episodes], "days": days})
    except Exception as e:
        logger.error(f"Error getting calendar: {e}")
        return jsonify({"success": False, "error": str(e), "episodes": []})


# =============================================================================
# DOWNLOAD ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/downloads")
def api_downloads():
    """Get current downloads from SABnzbd"""
    sabnzbd_config = get_service_config("sabnzbd")
    if not sabnzbd_config or not sabnzbd_config.get("api_key"):
        return jsonify({"success": False, "error": "SABnzbd not configured", "queue": [], "history": []})

    try:
        from .clients.sabnzbd import SABnzbdClient

        sabnzbd = SABnzbdClient(
            host=sabnzbd_config["host"],
            port=sabnzbd_config["port"],
            api_key=sabnzbd_config["api_key"],
            use_ssl=sabnzbd_config["use_ssl"],
        )

        queue = sabnzbd.get_queue()
        history = sabnzbd.get_history(10)
        speed = sabnzbd.get_speed()

        return jsonify(
            {
                "success": True,
                "queue": [item.to_dict() for item in queue],
                "history": [item.to_dict() for item in history],
                "speed": speed,
            }
        )
    except Exception as e:
        logger.error(f"Error getting downloads: {e}")
        return jsonify({"success": False, "error": str(e), "queue": [], "history": []})


# =============================================================================
# SETTINGS ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/settings")
def api_settings():
    """Get all service configurations (without decrypted API keys)"""
    services = get_all_services()
    return jsonify({"success": True, "services": services, "encryption_key_source": get_key_source()})


@media_hub_bp.route("/api/settings/services", methods=["POST"])
def api_add_service():
    """Add or update a service configuration"""
    data = request.get_json() or {}

    service_type = data.get("service_type")
    name = data.get("name")
    host = data.get("host", MEDIA_HOST)
    port = data.get("port")
    use_ssl = data.get("use_ssl", False)
    api_key = data.get("api_key")
    is_primary = data.get("is_primary", False)
    is_enabled = data.get("is_enabled", True)
    config_path = data.get("config_path")

    if not service_type or not port:
        return jsonify({"success": False, "error": "service_type and port are required"}), 400

    try:
        # Encrypt API key if provided
        api_key_encrypted = encrypt_api_key(api_key) if api_key else None

        conn = get_db()
        cursor = conn.cursor()

        # Check if service exists
        cursor.execute(
            "SELECT id FROM media_hub_services WHERE service_type = %s AND host = %s AND port = %s",
            (service_type, host, port),
        )
        existing = cursor.fetchone()

        if existing:
            # Update existing
            cursor.execute(
                """
                UPDATE media_hub_services SET
                    name = COALESCE(%s, name),
                    use_ssl = %s,
                    api_key_encrypted = COALESCE(%s, api_key_encrypted),
                    is_primary = %s,
                    is_enabled = %s,
                    config_path = COALESCE(%s, config_path),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
                (name, use_ssl, api_key_encrypted, is_primary, is_enabled, config_path, existing[0]),
            )
            service_id = existing[0]
        else:
            # Insert new
            cursor.execute(
                """
                INSERT INTO media_hub_services
                (service_type, name, host, port, use_ssl, api_key_encrypted, is_primary, is_enabled, config_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    service_type,
                    name or service_type.title(),
                    host,
                    port,
                    use_ssl,
                    api_key_encrypted,
                    is_primary,
                    is_enabled,
                    config_path,
                ),
            )
            service_id = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"success": True, "service_id": service_id, "message": f"{service_type} configuration saved"})
    except Exception as e:
        logger.error(f"Error saving service: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@media_hub_bp.route("/api/settings/discover", methods=["POST"])
def api_discover_services():
    """Auto-discover API keys from config files"""
    try:
        discovered = discover_all_api_keys()
        saved_count = 0

        conn = get_db()
        cursor = conn.cursor()

        for service_type, info in discovered.items():
            if info["found"] and info["api_key"]:
                # Encrypt the discovered API key
                api_key_encrypted = encrypt_api_key(info["api_key"])

                # Update or insert
                cursor.execute(
                    """
                    INSERT INTO media_hub_services
                    (service_type, name, host, port, use_ssl, api_key_encrypted, config_path)
                    VALUES (%s, %s, %s, %s, FALSE, %s, %s)
                    ON CONFLICT (service_type, host, port) DO UPDATE SET
                        api_key_encrypted = EXCLUDED.api_key_encrypted,
                        config_path = EXCLUDED.config_path,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    (
                        service_type,
                        service_type.title(),
                        MEDIA_HOST,
                        info["port"],
                        api_key_encrypted,
                        info["config_path"],
                    ),
                )
                saved_count += 1

        conn.commit()
        cursor.close()
        conn.close()

        # Build response without exposing actual keys
        results = {}
        for service_type, info in discovered.items():
            results[service_type] = {
                "found": info["found"],
                "config_path": info["config_path"],
                "port": info["port"],
                "note": info.get("note"),
            }

        return jsonify(
            {
                "success": True,
                "discovered": results,
                "saved_count": saved_count,
                "message": f"Discovered and saved {saved_count} API keys",
            }
        )
    except Exception as e:
        logger.error(f"Error discovering services: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@media_hub_bp.route("/api/settings/test/<int:service_id>", methods=["POST"])
def api_test_service(service_id):
    """Test connection to a specific service"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT service_type, host, port, use_ssl, api_key_encrypted
            FROM media_hub_services WHERE id = %s
        """,
            (service_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row:
            return jsonify({"success": False, "error": "Service not found"}), 404

        service_type, host, port, use_ssl, api_key_encrypted = row
        api_key = decrypt_api_key(api_key_encrypted) if api_key_encrypted else None

        if not api_key:
            return jsonify({"success": False, "error": "No API key configured"})

        # Test connection
        client = get_service_client(service_type, host, port, api_key, use_ssl)
        is_healthy = client.test_connection()

        # Update health status in database
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE media_hub_services SET
                health_status = %s,
                health_message = %s,
                last_health_check = CURRENT_TIMESTAMP
            WHERE id = %s
        """,
            (
                "healthy" if is_healthy else "unhealthy",
                "Connection successful" if is_healthy else "Connection failed",
                service_id,
            ),
        )
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify(
            {
                "success": True,
                "healthy": is_healthy,
                "message": "Connection successful" if is_healthy else "Connection failed",
            }
        )
    except Exception as e:
        logger.error(f"Error testing service: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@media_hub_bp.route("/api/settings/services/<int:service_id>", methods=["DELETE"])
def api_delete_service(service_id):
    """Delete a service configuration"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM media_hub_services WHERE id = %s RETURNING service_type", (service_id,))
        deleted = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        if deleted:
            return jsonify({"success": True, "message": f"{deleted[0]} deleted"})
        else:
            return jsonify({"success": False, "error": "Service not found"}), 404
    except Exception as e:
        logger.error(f"Error deleting service: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@media_hub_bp.route("/api/settings/set-primary/<int:service_id>", methods=["POST"])
def api_set_primary_server(service_id):
    """Set a service as the primary media server"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        # Get service type
        cursor.execute("SELECT service_type FROM media_hub_services WHERE id = %s", (service_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Service not found"}), 404

        service_type = row[0]
        if service_type not in ("plex", "jellyfin"):
            return jsonify({"success": False, "error": "Only Plex or Jellyfin can be primary"}), 400

        # Unset all other primaries for media servers
        cursor.execute(
            """
            UPDATE media_hub_services SET is_primary = FALSE
            WHERE service_type IN ('plex', 'jellyfin')
        """
        )

        # Set this one as primary
        cursor.execute("UPDATE media_hub_services SET is_primary = TRUE WHERE id = %s", (service_id,))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"success": True, "message": f"{service_type} set as primary media server"})
    except Exception as e:
        logger.error(f"Error setting primary: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# CONTINUE WATCHING ENDPOINT
# =============================================================================


@media_hub_bp.route("/api/library/continue-watching")
def api_continue_watching():
    """Get on-deck / continue watching items"""
    limit = request.args.get("limit", 10, type=int)

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_on_deck(limit)
        return jsonify({"success": True, "items": [item.to_dict() for item in items], "source": server_type})
    except Exception as e:
        logger.error(f"Error getting continue watching: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})


# =============================================================================
# COLLECTIONS ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/library/collections")
def api_collections():
    """Get all collections from library"""
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "collections": []})

    try:
        collections = media_server.get_collections()
        return jsonify({"success": True, "collections": collections, "source": server_type})
    except Exception as e:
        logger.error(f"Error getting collections: {e}")
        return jsonify({"success": False, "error": str(e), "collections": []})


@media_hub_bp.route("/api/library/collections/<collection_id>")
def api_collection_items(collection_id):
    """Get items in a specific collection"""
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_collection_items(collection_id)
        return jsonify({"success": True, "items": [item.to_dict() for item in items], "source": server_type})
    except Exception as e:
        logger.error(f"Error getting collection items: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})


# =============================================================================
# QUALITY INFO ENDPOINT
# =============================================================================


@media_hub_bp.route("/api/media/<media_id>/quality")
def api_media_quality(media_id):
    """Get detailed quality information for a media item"""
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured"})

    try:
        quality_info = media_server.get_quality_info(media_id)
        return jsonify({"success": True, "quality": quality_info, "source": server_type})
    except Exception as e:
        logger.error(f"Error getting quality info: {e}")
        return jsonify({"success": False, "error": str(e)})


# =============================================================================
# WATCH HISTORY ENDPOINT
# =============================================================================


@media_hub_bp.route("/api/library/history")
def api_watch_history():
    """Get recently watched items"""
    limit = request.args.get("limit", 50, type=int)

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    try:
        items = media_server.get_watch_history(limit)
        return jsonify({"success": True, "items": [item.to_dict() for item in items], "source": server_type})
    except Exception as e:
        logger.error(f"Error getting watch history: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})


# =============================================================================
# STREAMING ENDPOINT
# =============================================================================


@media_hub_bp.route("/api/stream/<media_id>")
def api_stream_info(media_id):
    """
    Get streaming URL for a media item.
    Returns direct stream URL for HTML5 video player.
    """
    direct = request.args.get("direct", "true").lower() == "true"

    # Get Jellyfin client specifically (streaming only supported for Jellyfin currently)
    jellyfin_config = get_service_config("jellyfin")
    if not jellyfin_config or not jellyfin_config.get("api_key"):
        return jsonify({"success": False, "error": "Jellyfin not configured for streaming"})

    try:
        from .clients.jellyfin import JellyfinClient

        client = JellyfinClient(
            host=jellyfin_config["host"],
            port=jellyfin_config["port"],
            api_key=jellyfin_config["api_key"],
            use_ssl=jellyfin_config["use_ssl"],
        )

        stream_info = client.get_stream_url(media_id, direct=direct)
        if stream_info:
            return jsonify({"success": True, "stream": stream_info})
        else:
            return jsonify({"success": False, "error": "Could not get stream URL"})

    except Exception as e:
        logger.error(f"Error getting stream URL: {e}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


# =============================================================================
# DOWNLOAD CONTROL ENDPOINTS
# =============================================================================


def get_sabnzbd_client():
    """Get SABnzbd client instance"""
    sabnzbd_config = get_service_config("sabnzbd")
    if not sabnzbd_config or not sabnzbd_config.get("api_key"):
        return None

    from .clients.sabnzbd import SABnzbdClient

    return SABnzbdClient(
        host=sabnzbd_config["host"],
        port=sabnzbd_config["port"],
        api_key=sabnzbd_config["api_key"],
        use_ssl=sabnzbd_config["use_ssl"],
    )


@media_hub_bp.route("/api/downloads/pause", methods=["POST"])
def api_downloads_pause_all():
    """Pause all downloads"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.pause_queue()
        return jsonify({"success": result, "message": "Queue paused" if result else "Failed to pause"})
    except Exception as e:
        logger.error(f"Error pausing downloads: {e}")
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/downloads/resume", methods=["POST"])
def api_downloads_resume_all():
    """Resume all downloads"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.resume_queue()
        return jsonify({"success": result, "message": "Queue resumed" if result else "Failed to resume"})
    except Exception as e:
        logger.error(f"Error resuming downloads: {e}")
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/downloads/<nzo_id>/pause", methods=["POST"])
def api_download_pause(nzo_id):
    """Pause a specific download"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.pause_item(nzo_id)
        return jsonify({"success": result})
    except Exception as e:
        logger.error(f"Error pausing download: {e}")
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/downloads/<nzo_id>/resume", methods=["POST"])
def api_download_resume(nzo_id):
    """Resume a specific download"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.resume_item(nzo_id)
        return jsonify({"success": result})
    except Exception as e:
        logger.error(f"Error resuming download: {e}")
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/downloads/<nzo_id>", methods=["DELETE"])
def api_download_delete(nzo_id):
    """Delete a download from queue"""
    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.delete_item(nzo_id)
        return jsonify({"success": result})
    except Exception as e:
        logger.error(f"Error deleting download: {e}")
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/downloads/speed", methods=["POST"])
def api_set_speed_limit():
    """Set download speed limit"""
    data = request.get_json() or {}
    limit_kbps = data.get("limit", 0)  # 0 = unlimited

    client = get_sabnzbd_client()
    if not client:
        return jsonify({"success": False, "error": "SABnzbd not configured"})

    try:
        result = client.set_speed_limit(limit_kbps)
        return jsonify({"success": result, "limit_kbps": limit_kbps})
    except Exception as e:
        logger.error(f"Error setting speed limit: {e}")
        return jsonify({"success": False, "error": str(e)})


# =============================================================================
# TMDB ENDPOINTS (External Discovery)
# =============================================================================


def get_tmdb_client():
    """Get TMDB client instance"""
    import os
    from .clients.tmdb import TMDBClient

    return TMDBClient(api_key=os.environ.get("TMDB_API_KEY"))


@media_hub_bp.route("/api/tmdb/status")
def api_tmdb_status():
    """Check if TMDB is configured"""
    client = get_tmdb_client()
    return jsonify(
        {
            "success": True,
            "configured": client.is_configured(),
            "message": "TMDB API configured" if client.is_configured() else "Add TMDB_API_KEY to environment",
        }
    )


@media_hub_bp.route("/api/tmdb/search")
def api_tmdb_search():
    """Search TMDB for movies and TV shows"""
    query = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)

    if not query:
        return jsonify({"success": False, "error": "Query required", "results": []})

    client = get_tmdb_client()
    if not client.is_configured():
        return jsonify({"success": False, "error": "TMDB not configured", "results": []})

    try:
        results = client.search_multi(query, page)

        # Mark items that are in our library
        media_server, _ = get_primary_media_server()
        if media_server:
            library_results = media_server.search_library(query)
            library_titles = {item.title.lower() for item in library_results}

            for item in results.get("results", []):
                if item.get("title", "").lower() in library_titles:
                    item["in_library"] = True

        return jsonify({"success": True, **results})
    except Exception as e:
        logger.error(f"TMDB search error: {e}")
        return jsonify({"success": False, "error": str(e), "results": []})


@media_hub_bp.route("/api/tmdb/trending")
def api_tmdb_trending():
    """Get trending movies and TV shows from TMDB"""
    media_type = request.args.get("type", "all")  # 'all', 'movie', 'tv'
    time_window = request.args.get("window", "week")  # 'day', 'week'

    client = get_tmdb_client()
    if not client.is_configured():
        return jsonify({"success": False, "error": "TMDB not configured", "items": []})

    try:
        items = client.get_trending(media_type, time_window)

        # Mark items in our library
        media_server, _ = get_primary_media_server()
        if media_server:
            # Get library titles for comparison
            movies = media_server.get_all_movies(200)
            shows = media_server.get_all_shows(100)
            library_titles = {item.title.lower() for item in movies + shows}

            for item in items:
                if item.get("title", "").lower() in library_titles:
                    item["in_library"] = True

        return jsonify({"success": True, "items": items, "media_type": media_type, "time_window": time_window})
    except Exception as e:
        logger.error(f"TMDB trending error: {e}")
        return jsonify({"success": False, "error": str(e), "items": []})


@media_hub_bp.route("/api/tmdb/movie/<int:movie_id>")
def api_tmdb_movie_details(movie_id):
    """Get detailed movie information from TMDB"""
    client = get_tmdb_client()
    if not client.is_configured():
        return jsonify({"success": False, "error": "TMDB not configured"})

    try:
        details = client.get_movie_details(movie_id)
        if details:
            return jsonify({"success": True, "movie": details})
        else:
            return jsonify({"success": False, "error": "Movie not found"}), 404
    except Exception as e:
        logger.error(f"TMDB movie details error: {e}")
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/tmdb/tv/<int:tv_id>")
def api_tmdb_tv_details(tv_id):
    """Get detailed TV show information from TMDB"""
    client = get_tmdb_client()
    if not client.is_configured():
        return jsonify({"success": False, "error": "TMDB not configured"})

    try:
        details = client.get_tv_details(tv_id)
        if details:
            return jsonify({"success": True, "show": details})
        else:
            return jsonify({"success": False, "error": "Show not found"}), 404
    except Exception as e:
        logger.error(f"TMDB TV details error: {e}")
        return jsonify({"success": False, "error": str(e)})


# =============================================================================
# STATISTICS ENDPOINT
# =============================================================================


@media_hub_bp.route("/api/stats")
def api_statistics():
    """Get comprehensive library statistics"""
    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured"})

    try:
        # Basic stats
        stats = media_server.get_library_stats()

        # Get quality breakdown
        movies = media_server.get_all_movies(500)
        quality_breakdown = {"4K": 0, "1080p": 0, "720p": 0, "SD": 0}
        hdr_count = 0
        atmos_count = 0

        for movie in movies:
            badges = movie.metadata.get("quality_badges", [])
            if "4K" in badges:
                quality_breakdown["4K"] += 1
            elif "1080p" in badges:
                quality_breakdown["1080p"] += 1
            elif "720p" in badges:
                quality_breakdown["720p"] += 1
            else:
                quality_breakdown["SD"] += 1

            if movie.metadata.get("is_hdr"):
                hdr_count += 1
            if movie.metadata.get("is_atmos"):
                atmos_count += 1

        # Size breakdown by library type
        size_breakdown = {"movies": 0, "shows": 0}

        for movie in movies:
            size_breakdown["movies"] += movie.file_size_bytes or 0

        # Note: TV size would need episode iteration which is expensive
        # For now we'll estimate based on total - movies
        size_breakdown["shows"] = stats.total_size_bytes - size_breakdown["movies"]

        return jsonify(
            {
                "success": True,
                "stats": stats.to_dict(),
                "quality_breakdown": quality_breakdown,
                "hdr_count": hdr_count,
                "atmos_count": atmos_count,
                "size_breakdown": size_breakdown,
                "source": server_type,
            }
        )
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})
