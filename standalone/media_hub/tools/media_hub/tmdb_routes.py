"""Media Hub API routes."""

from . import media_hub_bp
from .routes_shared import *  # noqa: F401,F403

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
