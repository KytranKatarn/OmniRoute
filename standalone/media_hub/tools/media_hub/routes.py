"""
Media Hub Routes
================
API endpoints for Media Hub module.

Provides unified access to Plex/Jellyfin library, Sonarr/Radarr management,
Overseerr requests, and SABnzbd downloads.
"""

import re
import threading

from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from . import media_hub_bp
from .auth import media_hub_admin_required
from .encryption import encrypt_api_key, decrypt_api_key, get_key_source
from .discovery import discover_all_api_keys
from .services import get_service_client
from database import get_db_cursor
import logging
import traceback
import time

# Allowlist for Plex thumbnail paths — blocks path traversal / SSRF
_PLEX_PATH_RE = re.compile(r"^/library/[a-zA-Z0-9/_.-]+$")
# Jellyfin item ids are 32-hex GUIDs (dashless canonical form; some deployments
# emit the dashed 8-4-4-4-12 variant). Anchored + charset-limited so a crafted
# `id` cannot inject `/`, `?`, `#` or `..` into the upstream Jellyfin URL path
# (SSRF / path-traversal against the media server's own API with its api_key).
_JELLYFIN_ID_RE = re.compile(r"^[0-9a-fA-F]{32}$|^[0-9a-fA-F-]{36}$")
# Jellyfin image types — allowlist (the only values the UI ever requests).
_JELLYFIN_IMG_TYPES = frozenset(
    {"Primary", "Backdrop", "Thumb", "Logo", "Banner", "Art", "Disc", "Box", "Menu"}
)

logger = logging.getLogger(__name__)

# Host configuration
MEDIA_HOST = "192.168.1.200"

# Cache for library stats (reduces API calls to media server)
_stats_cache = {
    "data": None,
    "timestamp": 0,
    "ttl": 3600,  # 1 hour cache TTL
}

# Cache for the comprehensive /api/stats breakdown (quality/genres/HDR/size).
# That endpoint fetches up to 500 movies + iterates — expensive — so a short TTL
# keeps the Stats tab's background refresh cheap. ?refresh=true bypasses. #4746.
_full_stats_cache = {
    "data": None,
    "timestamp": 0,
    "ttl": 300,  # 5 min
}

# Cache for TMDB metadata enrichment
_tmdb_enrichment_cache = {}

# Generic per-endpoint TTL cache so tab switches don't re-hit Plex/Jellyfin on
# every navigation. Keyed on endpoint name + query string; safe to keep
# process-local per gunicorn worker because Plex/Jellyfin responses don't vary
# by Flask user session.
_response_cache = {}  # {key: (timestamp, (body, status, mimetype))}

# Image proxy cache — avoids hitting Plex/Jellyfin on every page load.
# Bounded to 500 entries; images are 50–500KB so worst-case ~250MB.
_proxy_cache = {}  # {cache_key: (timestamp, bytes, content_type)}
_proxy_cache_lock = threading.Lock()
_PROXY_CACHE_TTL = 86400  # 24h
_PROXY_CACHE_MAX = 500


def cached_response(ttl_seconds):
    """Decorator that caches a view's JSON/Response output for `ttl_seconds`."""
    import json as _json
    import time as _time
    from functools import wraps as _wraps

    from flask import Response as _Response
    from flask import request as _request

    def decorator(fn):
        @_wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{fn.__name__}:{_request.query_string.decode('utf-8', 'replace')}"
            now = _time.time()
            hit = _response_cache.get(key)
            if hit and (now - hit[0]) < ttl_seconds:
                body, status, mimetype = hit[1]
                return _Response(body, status=status, mimetype=mimetype)

            result = fn(*args, **kwargs)

            # Normalise to (payload, status) — view may return Response, dict,
            # tuple, or plain body
            status = 200
            payload = result
            if isinstance(result, tuple):
                payload = result[0]
                if len(result) > 1 and isinstance(result[1], int):
                    status = result[1]

            if isinstance(payload, _Response):
                body = payload.get_data(as_text=True)
                status = payload.status_code
                mimetype = payload.mimetype or "application/json"
            elif isinstance(payload, (dict, list)):
                body = _json.dumps(payload)
                mimetype = "application/json"
            else:
                body = str(payload)
                mimetype = "text/plain"

            # Only cache 2xx so we don't stamp failures into memory
            if 200 <= status < 300:
                _response_cache[key] = (now, (body, status, mimetype))
            return _Response(body, status=status, mimetype=mimetype)

        return wrapper

    return decorator


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
        # Check if item needs enrichment (missing poster, overview, or tmdb_id)
        needs_enrichment = (
            not item.get("poster_url")
            or not item.get("overview")
            or item.get("overview") == ""
            or not item.get("tmdb_id")
        )

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


def get_service_config(service_type: str) -> dict:
    """Get service configuration from database"""
    try:
        with get_db_cursor(cursor_factory=None, commit=False) as (conn, cur):
            cur.execute(
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
            row = cur.fetchone()

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
        with get_db_cursor(cursor_factory=None, commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT id, service_type, name, host, port, use_ssl, api_key_encrypted,
                       is_primary, is_enabled, config_path, health_status, health_message,
                       last_health_check
                FROM media_hub_services
                ORDER BY service_type
            """
            )
            rows = cur.fetchall()

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
                        host=config["host"],
                        port=config["port"],
                        api_key=config["api_key"],
                        use_ssl=config["use_ssl"],
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
                    host=config["host"],
                    port=config["port"],
                    api_key=config["api_key"],
                    use_ssl=config["use_ssl"],
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
                    host=config["host"],
                    port=config["port"],
                    api_key=config["api_key"],
                    use_ssl=config["use_ssl"],
                ),
                "jellyfin",
            )
        except Exception as e:
            logger.error(f"Failed to create Jellyfin client: {e}")

    return None, None


def get_all_media_servers() -> list:
    """Return [(client, server_type)] for ALL enabled Plex/Jellyfin servers.
    Primary server first; used for federated search."""
    from .clients.plex import PlexClient
    from .clients.jellyfin import JellyfinClient

    servers = []
    try:
        all_svcs = get_all_services()
    except Exception:
        return servers

    seen_types: set = set()
    # Primary first, then remaining
    ordered = sorted(all_svcs, key=lambda s: (not s.get("is_primary"), s.get("id", 0)))
    for svc in ordered:
        stype = svc.get("service_type")
        if stype not in ("plex", "jellyfin") or not svc.get("is_enabled"):
            continue
        if stype in seen_types:
            continue  # one client per type is enough for search
        seen_types.add(stype)
        config = get_service_config(stype)
        if not config or not config.get("api_key"):
            continue
        try:
            if stype == "plex":
                client = PlexClient(
                    host=config["host"],
                    port=config["port"],
                    api_key=config["api_key"],
                    use_ssl=config["use_ssl"],
                )
            else:
                client = JellyfinClient(
                    host=config["host"],
                    port=config["port"],
                    api_key=config["api_key"],
                    use_ssl=config["use_ssl"],
                )
            servers.append((client, stype))
        except Exception as e:
            logger.warning(f"get_all_media_servers: could not build {stype} client: {e}")

    return servers


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


# =============================================================================
# LIBRARY ENDPOINTS
# =============================================================================


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


# =============================================================================
# LIBRARY REMOVE (delete a movie/show + its files)  — project #385, task #4745
# =============================================================================
# Destructive. Two entry points share _delete_library_item():
#   • POST /api/library/delete  — ADMIN ONLY (media_hub_admin_required). Human-
#     initiated from the UI, which enforces a DOUBLE "are you sure?" before calling.
#   • M.A.V.E.N. (maven_manager.request_removal) — agent-initiated; routes through
#     an A.R.C.H.I.E. Telegram approval before this helper is ever reached.
# Resolves the arr record from tmdb_id/title, then DELETE ...?deleteFiles=true so
# the file(s) are removed and Plex/Jellyfin drop the item on their next scan.


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


# =============================================================================
# TDARR — video review + optimize (project #385 Phase 3)
# =============================================================================


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


# =============================================================================
# REQUEST ENDPOINTS
# =============================================================================


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


# =============================================================================
# CALENDAR ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/calendar/upcoming")
def api_calendar_upcoming():
    """Get upcoming episodes from Sonarr"""
    days = request.args.get("days", 7, type=int)
    start_date = request.args.get("start")  # Optional: YYYY-MM-DD format

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
        episodes = sonarr.get_upcoming_episodes(days, start_date)
        return jsonify(
            {
                "success": True,
                "episodes": [ep.to_dict() for ep in episodes],
                "days": days,
                "start": start_date,
            }
        )
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
        return jsonify(
            {
                "success": False,
                "error": "SABnzbd not configured",
                "queue": [],
                "history": [],
            }
        )

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
    return jsonify(
        {
            "success": True,
            "services": services,
            "encryption_key_source": get_key_source(),
        }
    )


@media_hub_bp.route("/api/settings/services", methods=["POST"])
@media_hub_admin_required
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
        return (
            jsonify({"success": False, "error": "service_type and port are required"}),
            400,
        )

    try:
        # Encrypt API key if provided
        api_key_encrypted = encrypt_api_key(api_key) if api_key else None

        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            # Check if service exists
            cur.execute(
                "SELECT id FROM media_hub_services WHERE service_type = %s AND host = %s AND port = %s",
                (service_type, host, port),
            )
            existing = cur.fetchone()

            if existing:
                # Update existing
                cur.execute(
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
                    (
                        name,
                        use_ssl,
                        api_key_encrypted,
                        is_primary,
                        is_enabled,
                        config_path,
                        existing[0],
                    ),
                )
                service_id = existing[0]
            else:
                # Insert new
                cur.execute(
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
                service_id = cur.fetchone()[0]

            return jsonify(
                {
                    "success": True,
                    "service_id": service_id,
                    "message": f"{service_type} configuration saved",
                }
            )
    except Exception as e:
        logger.error(f"Error saving service: {e}")
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@media_hub_bp.route("/api/settings/discover", methods=["POST"])
@media_hub_admin_required
def api_discover_services():
    """Auto-discover API keys from config files"""
    try:
        discovered = discover_all_api_keys()
        saved_count = 0

        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            for service_type, info in discovered.items():
                if info["found"] and info["api_key"]:
                    # Encrypt the discovered API key
                    api_key_encrypted = encrypt_api_key(info["api_key"])

                    # Update or insert
                    cur.execute(
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
@media_hub_admin_required
def api_test_service(service_id):
    """Test connection to a specific service"""
    try:
        # Read service config
        with get_db_cursor(cursor_factory=None, commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT service_type, host, port, use_ssl, api_key_encrypted
                FROM media_hub_services WHERE id = %s
            """,
                (service_id,),
            )
            row = cur.fetchone()

        if not row:
            return jsonify({"success": False, "error": "Service not found"}), 404

        service_type, host, port, use_ssl, api_key_encrypted = row
        api_key = decrypt_api_key(api_key_encrypted) if api_key_encrypted else None

        if not api_key:
            return jsonify({"success": False, "error": "No API key configured"})

        # Test connection — prefer probe() for a real error message
        client = get_service_client(service_type, host, port, api_key, use_ssl)
        if hasattr(client, "probe"):
            is_healthy, health_message = client.probe()
        else:
            is_healthy = client.test_connection()
            health_message = "Connection successful" if is_healthy else "Connection failed"

        # Update health status in database
        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE media_hub_services SET
                    health_status = %s,
                    health_message = %s,
                    last_health_check = CURRENT_TIMESTAMP
                WHERE id = %s
            """,
                (
                    "healthy" if is_healthy else "unhealthy",
                    health_message,
                    service_id,
                ),
            )

        return jsonify(
            {
                "success": True,
                "healthy": is_healthy,
                "message": ("Connection successful" if is_healthy else "Connection failed"),
            }
        )
    except Exception as e:
        logger.error(f"Error testing service: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@media_hub_bp.route("/api/settings/services/<int:service_id>", methods=["DELETE"])
@media_hub_admin_required
def api_delete_service(service_id):
    """Delete a service configuration"""
    try:
        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM media_hub_services WHERE id = %s RETURNING service_type",
                (service_id,),
            )
            deleted = cur.fetchone()

            if deleted:
                return jsonify({"success": True, "message": f"{deleted[0]} deleted"})
            else:
                return jsonify({"success": False, "error": "Service not found"}), 404
    except Exception as e:
        logger.error(f"Error deleting service: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@media_hub_bp.route("/api/settings/set-primary/<int:service_id>", methods=["POST"])
@media_hub_admin_required
def api_set_primary_server(service_id):
    """Set a service as the primary media server"""
    try:
        with get_db_cursor(cursor_factory=None, commit=True) as (conn, cur):
            # Get service type
            cur.execute("SELECT service_type FROM media_hub_services WHERE id = %s", (service_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Service not found"}), 404

            service_type = row[0]
            if service_type not in ("plex", "jellyfin"):
                return (
                    jsonify({"success": False, "error": "Only Plex or Jellyfin can be primary"}),
                    400,
                )

            # Unset all other primaries for media servers
            cur.execute(
                """
                UPDATE media_hub_services SET is_primary = FALSE
                WHERE service_type IN ('plex', 'jellyfin')
            """
            )

            # Set this one as primary
            cur.execute(
                "UPDATE media_hub_services SET is_primary = TRUE WHERE id = %s",
                (service_id,),
            )

            return jsonify({"success": True, "message": f"{service_type} set as primary media server"})
    except Exception as e:
        logger.error(f"Error setting primary: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# CONTINUE WATCHING ENDPOINT
# =============================================================================


@media_hub_bp.route("/api/library/continue-watching")
@cached_response(30)
def api_continue_watching():
    """Get on-deck / continue watching items from ALL media servers"""
    from .clients.plex import PlexClient
    from .clients.jellyfin import JellyfinClient

    limit = request.args.get("limit", 10, type=int)

    # Items to exclude from continue watching (user preference)
    excluded_titles = {"the paper"}

    def should_exclude(item_dict):
        """Check if item should be excluded from continue watching"""
        title = item_dict.get("title", "").lower()
        show_title = item_dict.get("metadata", {}).get("show_title", "").lower()
        return title in excluded_titles or show_title in excluded_titles

    all_items = []
    seen_titles = set()

    # Get from Plex (priority source for continue watching)
    plex_config = get_service_config("plex")
    if plex_config and plex_config.get("api_key"):
        try:
            plex = PlexClient(
                host=plex_config["host"],
                port=plex_config["port"],
                api_key=plex_config["api_key"],
                use_ssl=plex_config.get("use_ssl", False),
            )
            plex_items = plex.get_on_deck(limit=limit * 2)  # Get extra for deduplication
            for item in plex_items:
                item_dict = item.to_dict()
                item_dict["source"] = "plex"
                # Skip excluded items
                if should_exclude(item_dict):
                    continue
                # Dedup key based on title (normalized)
                title_key = item.title.lower().strip()
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_items.append(item_dict)
        except Exception as e:
            logger.error(f"Error getting Plex continue watching: {e}")

    # Get from Jellyfin (secondary source)
    jelly_config = get_service_config("jellyfin")
    if jelly_config and jelly_config.get("api_key"):
        try:
            jelly = JellyfinClient(
                host=jelly_config["host"],
                port=jelly_config["port"],
                api_key=jelly_config["api_key"],
                use_ssl=jelly_config.get("use_ssl", False),
            )
            jelly_items = jelly.get_on_deck(limit=limit)
            for item in jelly_items:
                item_dict = item.to_dict()
                item_dict["source"] = "jellyfin"
                # Skip excluded items
                if should_exclude(item_dict):
                    continue
                # Dedup key based on title (normalized)
                title_key = item.title.lower().strip()
                if title_key not in seen_titles:
                    seen_titles.add(title_key)
                    all_items.append(item_dict)
        except Exception as e:
            logger.error(f"Error getting Jellyfin continue watching: {e}")

    if not all_items:
        return jsonify({"success": False, "error": "No media server configured", "items": []})

    # Sort by watch progress descending (higher progress = closer to finishing)
    all_items.sort(key=lambda x: x.get("metadata", {}).get("watch_progress", 0), reverse=True)

    return jsonify({"success": True, "items": all_items[:limit], "source": "combined"})


# =============================================================================
# COLLECTIONS ENDPOINTS
# =============================================================================


@media_hub_bp.route("/api/library/collections")
@cached_response(300)
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
        return jsonify(
            {
                "success": True,
                "items": [item.to_dict() for item in items],
                "source": server_type,
            }
        )
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
        return jsonify(
            {
                "success": True,
                "items": [item.to_dict() for item in items],
                "source": server_type,
            }
        )
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

    Supports both Jellyfin IDs directly and Plex IDs with title fallback.
    For movies: ?title=X&year=Y&type=movie
    For episodes: ?show_title=X&season=N&episode=M&type=episode
    """
    direct = request.args.get("direct", "true").lower() == "true"
    title = request.args.get("title")
    year = request.args.get("year", type=int)
    media_type = request.args.get("type", "movie")  # movie or episode
    # Episode-specific params
    show_title = request.args.get("show_title")
    season_num = request.args.get("season", type=int)
    episode_num = request.args.get("episode", type=int)

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

        # Try direct ID first
        stream_info = client.get_stream_url(media_id, direct=direct)

        # If direct ID fails, try title-based lookup
        if not stream_info and (title or show_title):
            logger.info(f"Direct ID {media_id} failed, searching by title")

            # Episode lookup: search show, then find episode by season/episode number
            if media_type == "episode" and show_title and season_num is not None and episode_num is not None:
                logger.info(f"Episode lookup: {show_title} S{season_num}E{episode_num}")
                results = client.search_library(show_title, media_type="show")
                for show in results:
                    if show.title.lower().strip() == show_title.lower().strip():
                        # Found matching show, now get the episode
                        episodes = client.get_episodes(show.id, season_num)
                        for ep in episodes:
                            if ep.get("episode_number") == episode_num:
                                logger.info(f"Found episode: {show.title} S{season_num}E{episode_num} -> {ep['id']}")
                                stream_info = client.get_stream_url(ep["id"], direct=direct)
                                break
                        if stream_info:
                            break
            # Movie lookup: search by title and year
            elif media_type == "movie" and title:
                logger.info(f"Movie lookup: {title} ({year})")
                results = client.search_library(title, media_type="movie")
                for item in results:
                    title_match = item.title.lower().strip() == title.lower().strip()
                    if year:
                        # Allow 1 year variance for movies
                        year_match = item.year and abs(item.year - year) <= 1
                        if title_match and year_match:
                            logger.info(f"Found matching movie: {item.title} ({item.year}) -> {item.id}")
                            stream_info = client.get_stream_url(item.id, direct=direct)
                            break
                    elif title_match:
                        logger.info(f"Found matching movie: {item.title} -> {item.id}")
                        stream_info = client.get_stream_url(item.id, direct=direct)
                        break

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
# CHROMECAST CAST URL ENDPOINT (T3302)
# =============================================================================

_CAST_LAN_HOST = "192.168.1.200"


@media_hub_bp.route("/api/cast/stream-url")
@login_required
def api_cast_stream_url():
    """Return a LAN-accessible stream URL for Chromecast (T3302).

    Chromecast is on the same LAN (192.168.1.0/24) as the hub, so we must
    use the hub's LAN IP rather than a Docker-internal hostname or the public
    subdomain (which hits Hostinger CDN with a 60 s timeout).

    Query params:
        item_id    - Jellyfin item ID (required)
        title      - Optional title for fallback lookup
        year       - Optional year for movie lookup
        type       - 'movie' or 'episode' (default 'movie')
        show_title, season, episode - Episode lookup params
    """
    import re as _re

    item_id = request.args.get("item_id", "").strip()
    title = request.args.get("title")
    year = request.args.get("year", type=int)
    media_type = request.args.get("type", "movie")
    show_title = request.args.get("show_title")
    season_num = request.args.get("season", type=int)
    episode_num = request.args.get("episode", type=int)

    if not item_id:
        return jsonify({"success": False, "error": "item_id is required"}), 400

    jellyfin_config = get_service_config("jellyfin")
    if not jellyfin_config or not jellyfin_config.get("api_key"):
        return jsonify({"success": False, "error": "Jellyfin not configured"})

    try:
        from .clients.jellyfin import JellyfinClient

        client = JellyfinClient(
            host=jellyfin_config["host"],
            port=jellyfin_config["port"],
            api_key=jellyfin_config["api_key"],
            use_ssl=jellyfin_config["use_ssl"],
        )

        stream_info = client.get_stream_url(item_id, direct=True)

        # Title-based fallback (mirrors api_stream_info logic)
        if not stream_info and (title or show_title):
            if media_type == "episode" and show_title and season_num is not None and episode_num is not None:
                results = client.search_library(show_title, media_type="show")
                for show in results:
                    if show.title.lower().strip() == show_title.lower().strip():
                        episodes = client.get_episodes(show.id, season_num)
                        for ep in episodes:
                            if ep.get("episode_number") == episode_num:
                                stream_info = client.get_stream_url(ep["id"], direct=True)
                                break
                        if stream_info:
                            break
            elif title:
                results = client.search_library(title, media_type="movie")
                for item_r in results:
                    if item_r.title.lower().strip() == title.lower().strip():
                        if not year or (item_r.year and abs(item_r.year - year) <= 1):
                            stream_info = client.get_stream_url(item_r.id, direct=True)
                            break

        if not stream_info:
            return jsonify({"success": False, "error": "Could not resolve stream URL"})

        # Rewrite host in stream_url to LAN IP so Chromecast can reach it.
        # Jellyfin base_url uses configured host (may be Docker-internal like
        # 'media_jellyfin') which is not resolvable from the Chromecast device.
        raw_url = stream_info["stream_url"]
        jellyfin_port = jellyfin_config["port"]
        lan_url = _re.sub(
            r"^https?://[^/]+",
            f"http://{_CAST_LAN_HOST}:{jellyfin_port}",
            raw_url,
        )

        cast_title = title or show_title or item_id
        if media_type == "episode" and show_title and season_num is not None and episode_num is not None:
            cast_title = f"{show_title} — S{season_num:02d}E{episode_num:02d}"

        # Poster via this server's proxy endpoint (LAN-accessible at port 8105)
        poster_url = (
            f"http://{_CAST_LAN_HOST}:8105/tools/media-hub/api/proxy/thumb" f"?s=jellyfin&id={item_id}&type=Primary"
        )

        return jsonify(
            {
                "success": True,
                "url": lan_url,
                "title": cast_title,
                "poster": poster_url,
                "container": stream_info.get("container", "mp4"),
            }
        )

    except Exception as exc:
        logger.error(f"[Cast] Error building cast URL: {exc}")
        import traceback

        traceback.print_exc()
        return jsonify({"success": False, "error": str(exc)})


# =============================================================================
# IMAGE PROXY ENDPOINT
# =============================================================================


@media_hub_bp.route("/api/proxy/thumb")
@login_required
def api_proxy_thumb():
    """Server-side proxy for Plex/Jellyfin thumbnails.

    Fetches images from the LAN media server and streams them back through our
    domain, so browsers on HTTPS (media.kytranempowerment.com) can load them
    without hitting a mixed-content block or a private LAN IP directly.

    Query params:
        s    — source: 'plex' or 'jellyfin'
        path — Plex: /library/metadata/<id>/thumb/<thumb>
        id   — Jellyfin: item UUID
        type — Jellyfin: image type (default: Primary)
    """
    import requests as _requests
    from flask import Response as _Response

    source = request.args.get("s", "plex")
    cache_key = (
        f"{source}:{request.args.get('path', '')}" f"{request.args.get('id', '')}{request.args.get('type', 'Primary')}"
    )

    # Return cached image if still fresh
    cached = _proxy_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < _PROXY_CACHE_TTL:
        return _Response(
            cached[1],
            content_type=cached[2],
            headers={"Cache-Control": "public, max-age=86400", "X-Cache": "HIT"},
        )

    try:
        if source == "plex":
            config = get_service_config("plex")
            if not config or not config.get("api_key"):
                return "", 404
            path = request.args.get("path", "")
            if not path or not _PLEX_PATH_RE.match(path):
                return "", 400
            scheme = "https" if config["use_ssl"] else "http"
            url = f"{scheme}://{config['host']}:{config['port']}{path}?X-Plex-Token={config['api_key']}"

        elif source == "jellyfin":
            config = get_service_config("jellyfin")
            if not config or not config.get("api_key"):
                return "", 404
            item_id = request.args.get("id", "")
            img_type = request.args.get("type", "Primary")
            # Validate BOTH before interpolating into the upstream path — a crafted
            # id/type could otherwise inject `/`, `?`, `#` or `..` to reach other
            # Jellyfin endpoints (SSRF / path-traversal) carrying the admin api_key.
            if not _JELLYFIN_ID_RE.match(item_id):
                return "", 400
            if img_type not in _JELLYFIN_IMG_TYPES:
                return "", 400
            scheme = "https" if config["use_ssl"] else "http"
            url = (
                f"{scheme}://{config['host']}:{config['port']}"
                f"/Items/{item_id}/Images/{img_type}"
                f"?api_key={config['api_key']}&maxWidth=400"
            )
        else:
            return "", 400

        resp = _requests.get(url, timeout=8, verify=False)
        if resp.status_code != 200:
            return "", 404

        content_type = resp.headers.get("Content-Type", "image/jpeg")
        image_bytes = resp.content

        # Evict oldest entry when cache is full, then store (lock for thread safety)
        with _proxy_cache_lock:
            if len(_proxy_cache) >= _PROXY_CACHE_MAX:
                oldest = min(_proxy_cache, key=lambda k: _proxy_cache[k][0])
                _proxy_cache.pop(oldest, None)
            _proxy_cache[cache_key] = (time.time(), image_bytes, content_type)

        return _Response(
            image_bytes,
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=86400", "X-Cache": "MISS"},
        )
    except Exception as e:
        logger.debug(f"proxy/thumb error: {e}")
        return "", 502


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
        return jsonify(
            {
                "success": result,
                "message": "Queue paused" if result else "Failed to pause",
            }
        )
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
        return jsonify(
            {
                "success": result,
                "message": "Queue resumed" if result else "Failed to resume",
            }
        )
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
@media_hub_admin_required
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
            "message": ("TMDB API configured" if client.is_configured() else "Add TMDB_API_KEY to environment"),
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

        return jsonify(
            {
                "success": True,
                "items": items,
                "media_type": media_type,
                "time_window": time_window,
            }
        )
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
    """Get comprehensive library statistics (server-side TTL cached — #4746)."""
    force_refresh = request.args.get("refresh", "false").lower() == "true"
    now = time.time()
    if (
        not force_refresh
        and _full_stats_cache["data"] is not None
        and (now - _full_stats_cache["timestamp"]) < _full_stats_cache["ttl"]
    ):
        return jsonify({
            **_full_stats_cache["data"],
            "cached": True,
            "cache_age": int(now - _full_stats_cache["timestamp"]),
        })

    media_server, server_type = get_primary_media_server()
    if not media_server:
        return jsonify({"success": False, "error": "No media server configured"})

    try:
        # Basic stats
        stats = media_server.get_library_stats()

        # Get quality breakdown from movies
        movies = media_server.get_all_movies(500)
        quality_breakdown = {"4K": 0, "1080p": 0, "720p": 0, "SD": 0}
        hdr_count = 0
        atmos_count = 0
        dolby_vision_count = 0
        genres = {}

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
            if movie.metadata.get("is_dolby_vision"):
                dolby_vision_count += 1

            # Count genres
            for genre in movie.genres or []:
                genres[genre] = genres.get(genre, 0) + 1

        # Size breakdown by library type
        size_breakdown = {"movies": 0, "shows": 0}

        for movie in movies:
            size_breakdown["movies"] += movie.file_size_bytes or 0

        # Note: TV size would need episode iteration which is expensive
        # For now we'll estimate based on total - movies
        size_breakdown["shows"] = max(0, stats.total_size_bytes - size_breakdown["movies"])

        payload = {
            "success": True,
            "stats": stats.to_dict(),
            "quality_breakdown": quality_breakdown,
            "hdr_count": hdr_count,
            "atmos_count": atmos_count,
            "dolby_vision_count": dolby_vision_count,
            "size_breakdown": size_breakdown,
            "genres": genres,
            "source": server_type,
        }
        _full_stats_cache["data"] = payload
        _full_stats_cache["timestamp"] = now
        return jsonify({**payload, "cached": False})
    except Exception as e:
        logger.error(f"Error getting statistics: {e}")
        traceback.print_exc()
        # Serve stale cache on error rather than a bare failure, if we have any.
        if _full_stats_cache["data"] is not None:
            return jsonify({**_full_stats_cache["data"], "cached": True, "stale": True})
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/library/recent-activity")
def api_library_recent_activity():
    """Get recently added content grouped by day for stats"""
    days = request.args.get("days", 7, type=int)
    media_server, server_type = get_primary_media_server()

    if not media_server:
        return jsonify({"success": False, "error": "No media server configured"})

    try:
        from datetime import datetime, timedelta

        # Get recent movies
        movies = media_server.get_all_movies(limit=100, sort="added")
        shows = media_server.get_all_shows(limit=100, sort="added")

        cutoff = datetime.now() - timedelta(days=days)
        by_day = {}
        movies_count = 0
        episodes_count = 0

        def _parse_added_at(value):
            """Parse added_at from either a Unix timestamp (int/float) or ISO string."""
            if value is None:
                return None
            try:
                if isinstance(value, (int, float)):
                    return datetime.fromtimestamp(value)
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, OSError, OverflowError):
                return None

        for movie in movies:
            if movie.added_at:
                added = _parse_added_at(movie.added_at)
                if added and added >= cutoff:
                    date_str = added.strftime("%Y-%m-%d")
                    by_day[date_str] = by_day.get(date_str, 0) + 1
                    movies_count += 1

        for show in shows:
            if show.added_at:
                added = _parse_added_at(show.added_at)
                if added and added >= cutoff:
                    date_str = added.strftime("%Y-%m-%d")
                    by_day[date_str] = by_day.get(date_str, 0) + 1
                    episodes_count += 1

        return jsonify(
            {
                "success": True,
                "by_day": by_day,
                "movies_count": movies_count,
                "episodes_count": episodes_count,
                "source": server_type,
            }
        )
    except Exception as e:
        logger.error(f"Error getting recent additions: {e}")
        return jsonify({"success": False, "error": str(e)})


@media_hub_bp.route("/api/library/top-rated")
def api_library_top_rated():
    """Get top rated content from library"""
    limit = request.args.get("limit", 10, type=int)
    media_server, server_type = get_primary_media_server()

    if not media_server:
        return jsonify({"success": False, "error": "No media server configured"})

    try:
        # Get movies sorted by rating
        movies = media_server.get_all_movies(limit=100, sort="rating")
        shows = media_server.get_all_shows(limit=50, sort="rating")

        # Combine and sort by rating
        all_items = []
        for movie in movies:
            if movie.rating and movie.rating > 0:
                all_items.append(movie.to_dict())

        for show in shows:
            if show.rating and show.rating > 0:
                all_items.append(show.to_dict())

        # Sort by rating descending
        all_items.sort(key=lambda x: x.get("rating", 0) or 0, reverse=True)

        return jsonify(
            {
                "success": True,
                "items": all_items[:limit],
                "source": server_type,
            }
        )
    except Exception as e:
        logger.error(f"Error getting top rated: {e}")
        return jsonify({"success": False, "error": str(e)})
