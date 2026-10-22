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



__all__ = [name for name in globals() if not name.startswith("__")]
