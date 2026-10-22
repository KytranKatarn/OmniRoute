"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

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
