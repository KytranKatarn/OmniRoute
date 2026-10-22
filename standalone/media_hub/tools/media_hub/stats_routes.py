"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

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
