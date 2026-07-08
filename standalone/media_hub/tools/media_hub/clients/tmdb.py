"""
TMDB Client
===========
Client for The Movie Database (TMDB) API.
Used for external search, trending content, and metadata enrichment.

Get a free API key at: https://www.themoviedb.org/settings/api
"""

import os
import requests
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Cache for API responses (in-memory, short-lived)
_cache = {}
_cache_ttl = 300  # 5 minutes


class TMDBClient:
    """Client for TMDB API"""

    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize TMDB client.

        Args:
            api_key: TMDB API key (falls back to TMDB_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("TMDB_API_KEY")
        self.timeout = 10

    def is_configured(self) -> bool:
        """Check if TMDB API key is configured"""
        return bool(self.api_key)

    def _get_cache_key(self, endpoint: str, params: Dict) -> str:
        """Generate cache key for request"""
        param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{endpoint}?{param_str}"

    def _get_cached(self, cache_key: str) -> Optional[Dict]:
        """Get cached response if still valid"""
        if cache_key in _cache:
            data, timestamp = _cache[cache_key]
            if datetime.now().timestamp() - timestamp < _cache_ttl:
                return data
            del _cache[cache_key]
        return None

    def _set_cached(self, cache_key: str, data: Dict):
        """Cache response"""
        _cache[cache_key] = (data, datetime.now().timestamp())

    def _request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make request to TMDB API"""
        if not self.api_key:
            logger.warning("TMDB API key not configured")
            return None

        url = f"{self.BASE_URL}/{endpoint}"
        request_params = {"api_key": self.api_key}
        if params:
            request_params.update(params)

        # Check cache
        cache_key = self._get_cache_key(endpoint, request_params)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            response = requests.get(url, params=request_params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            self._set_cached(cache_key, data)
            return data
        except requests.RequestException as e:
            logger.error(f"TMDB API request failed: {e}")
            return None

    def get_poster_url(self, path: str, size: str = "w500") -> Optional[str]:
        """Get full poster URL"""
        if not path:
            return None
        return f"{self.IMAGE_BASE_URL}/{size}{path}"

    def get_backdrop_url(self, path: str, size: str = "w1280") -> Optional[str]:
        """Get full backdrop URL"""
        if not path:
            return None
        return f"{self.IMAGE_BASE_URL}/{size}{path}"

    def search_multi(self, query: str, page: int = 1) -> Dict[str, Any]:
        """
        Search for movies and TV shows.

        Args:
            query: Search query
            page: Page number

        Returns:
            Search results with movies and shows
        """
        result = self._request("search/multi", {"query": query, "page": page, "include_adult": "false"})

        if not result:
            return {"results": [], "total_results": 0, "total_pages": 0}

        # Filter to only movies and TV shows, enrich with poster URLs
        items = []
        for item in result.get("results", []):
            media_type = item.get("media_type")
            if media_type not in ("movie", "tv"):
                continue

            items.append(self._format_search_result(item))

        return {
            "results": items,
            "total_results": result.get("total_results", 0),
            "total_pages": result.get("total_pages", 0),
            "page": result.get("page", 1),
        }

    def search_movies(self, query: str, page: int = 1, year: Optional[int] = None) -> Dict[str, Any]:
        """Search for movies"""
        params = {"query": query, "page": page}
        if year:
            params["year"] = year

        result = self._request("search/movie", params)
        if not result:
            return {"results": [], "total_results": 0}

        return {
            "results": [self._format_movie(m) for m in result.get("results", [])],
            "total_results": result.get("total_results", 0),
            "total_pages": result.get("total_pages", 0),
        }

    def search_tv(self, query: str, page: int = 1, year: Optional[int] = None) -> Dict[str, Any]:
        """Search for TV shows"""
        params = {"query": query, "page": page}
        if year:
            params["first_air_date_year"] = year

        result = self._request("search/tv", params)
        if not result:
            return {"results": [], "total_results": 0}

        return {
            "results": [self._format_tv(t) for t in result.get("results", [])],
            "total_results": result.get("total_results", 0),
            "total_pages": result.get("total_pages", 0),
        }

    def get_trending(self, media_type: str = "all", time_window: str = "week") -> List[Dict[str, Any]]:
        """
        Get trending movies/shows.

        Args:
            media_type: 'all', 'movie', or 'tv'
            time_window: 'day' or 'week'

        Returns:
            List of trending items
        """
        result = self._request(f"trending/{media_type}/{time_window}")
        if not result:
            return []

        items = []
        for item in result.get("results", [])[:20]:
            items.append(self._format_search_result(item))

        return items

    def get_movie_details(self, movie_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed movie information"""
        result = self._request(
            f"movie/{movie_id}",
            {"append_to_response": "credits,videos,external_ids,recommendations"},
        )

        if not result:
            return None

        return self._format_movie_details(result)

    def get_tv_details(self, tv_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed TV show information"""
        result = self._request(
            f"tv/{tv_id}",
            {"append_to_response": "credits,videos,external_ids,recommendations"},
        )

        if not result:
            return None

        return self._format_tv_details(result)

    def get_popular_movies(self, page: int = 1) -> List[Dict[str, Any]]:
        """Get popular movies"""
        result = self._request("movie/popular", {"page": page})
        if not result:
            return []
        return [self._format_movie(m) for m in result.get("results", [])]

    def get_popular_tv(self, page: int = 1) -> List[Dict[str, Any]]:
        """Get popular TV shows"""
        result = self._request("tv/popular", {"page": page})
        if not result:
            return []
        return [self._format_tv(t) for t in result.get("results", [])]

    def get_upcoming_movies(self, page: int = 1) -> List[Dict[str, Any]]:
        """Get upcoming movies"""
        result = self._request("movie/upcoming", {"page": page})
        if not result:
            return []
        return [self._format_movie(m) for m in result.get("results", [])]

    def _format_search_result(self, item: Dict) -> Dict[str, Any]:
        """Format a multi-search result"""
        media_type = item.get("media_type", "movie")

        if media_type == "movie":
            return self._format_movie(item)
        else:
            return self._format_tv(item)

    def _format_movie(self, movie: Dict) -> Dict[str, Any]:
        """Format movie data"""
        return {
            "id": movie.get("id"),
            "tmdb_id": movie.get("id"),
            "media_type": "movie",
            "title": movie.get("title", ""),
            "original_title": movie.get("original_title", ""),
            "overview": movie.get("overview", ""),
            "poster_url": self.get_poster_url(movie.get("poster_path")),
            "backdrop_url": self.get_backdrop_url(movie.get("backdrop_path")),
            "release_date": movie.get("release_date", ""),
            "year": (int(movie.get("release_date", "0000")[:4]) if movie.get("release_date") else None),
            "rating": movie.get("vote_average"),
            "vote_count": movie.get("vote_count", 0),
            "popularity": movie.get("popularity", 0),
            "genre_ids": movie.get("genre_ids", []),
            "original_language": movie.get("original_language", ""),
            "in_library": False,  # Will be set by comparison with local library
        }

    def _format_tv(self, tv: Dict) -> Dict[str, Any]:
        """Format TV show data"""
        return {
            "id": tv.get("id"),
            "tmdb_id": tv.get("id"),
            "media_type": "tv",
            "title": tv.get("name", ""),
            "original_title": tv.get("original_name", ""),
            "overview": tv.get("overview", ""),
            "poster_url": self.get_poster_url(tv.get("poster_path")),
            "backdrop_url": self.get_backdrop_url(tv.get("backdrop_path")),
            "first_air_date": tv.get("first_air_date", ""),
            "year": (int(tv.get("first_air_date", "0000")[:4]) if tv.get("first_air_date") else None),
            "rating": tv.get("vote_average"),
            "vote_count": tv.get("vote_count", 0),
            "popularity": tv.get("popularity", 0),
            "genre_ids": tv.get("genre_ids", []),
            "original_language": tv.get("original_language", ""),
            "in_library": False,
        }

    def _format_movie_details(self, movie: Dict) -> Dict[str, Any]:
        """Format detailed movie data"""
        # Get trailer
        trailer_url = None
        videos = movie.get("videos", {}).get("results", [])
        for video in videos:
            if video.get("type") == "Trailer" and video.get("site") == "YouTube":
                trailer_url = f"https://www.youtube.com/watch?v={video.get('key')}"
                break

        # Get cast
        credits = movie.get("credits", {})
        cast = [
            {
                "name": c.get("name"),
                "character": c.get("character"),
                "profile_url": self.get_poster_url(c.get("profile_path"), "w185"),
            }
            for c in credits.get("cast", [])[:10]
        ]

        # Get director
        director = None
        for crew in credits.get("crew", []):
            if crew.get("job") == "Director":
                director = crew.get("name")
                break

        # External IDs
        external_ids = movie.get("external_ids", {})

        return {
            **self._format_movie(movie),
            "runtime_minutes": movie.get("runtime"),
            "genres": [g.get("name") for g in movie.get("genres", [])],
            "tagline": movie.get("tagline", ""),
            "status": movie.get("status", ""),
            "budget": movie.get("budget"),
            "revenue": movie.get("revenue"),
            "imdb_id": external_ids.get("imdb_id"),
            "trailer_url": trailer_url,
            "cast": cast,
            "director": director,
            "recommendations": [self._format_movie(r) for r in movie.get("recommendations", {}).get("results", [])[:6]],
        }

    def _format_tv_details(self, tv: Dict) -> Dict[str, Any]:
        """Format detailed TV show data"""
        # Get trailer
        trailer_url = None
        videos = tv.get("videos", {}).get("results", [])
        for video in videos:
            if video.get("type") == "Trailer" and video.get("site") == "YouTube":
                trailer_url = f"https://www.youtube.com/watch?v={video.get('key')}"
                break

        # Get cast
        credits = tv.get("credits", {})
        cast = [
            {
                "name": c.get("name"),
                "character": c.get("character"),
                "profile_url": self.get_poster_url(c.get("profile_path"), "w185"),
            }
            for c in credits.get("cast", [])[:10]
        ]

        # External IDs
        external_ids = tv.get("external_ids", {})

        return {
            **self._format_tv(tv),
            "number_of_seasons": tv.get("number_of_seasons"),
            "number_of_episodes": tv.get("number_of_episodes"),
            "episode_run_time": (tv.get("episode_run_time", [None])[0] if tv.get("episode_run_time") else None),
            "genres": [g.get("name") for g in tv.get("genres", [])],
            "tagline": tv.get("tagline", ""),
            "status": tv.get("status", ""),
            "networks": [n.get("name") for n in tv.get("networks", [])],
            "imdb_id": external_ids.get("imdb_id"),
            "tvdb_id": external_ids.get("tvdb_id"),
            "trailer_url": trailer_url,
            "cast": cast,
            "created_by": [c.get("name") for c in tv.get("created_by", [])],
            "recommendations": [self._format_tv(r) for r in tv.get("recommendations", {}).get("results", [])[:6]],
        }


# Genre ID mappings for display
MOVIE_GENRES = {
    28: "Action",
    12: "Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    14: "Fantasy",
    36: "History",
    27: "Horror",
    10402: "Music",
    9648: "Mystery",
    10749: "Romance",
    878: "Sci-Fi",
    10770: "TV Movie",
    53: "Thriller",
    10752: "War",
    37: "Western",
}

TV_GENRES = {
    10759: "Action & Adventure",
    16: "Animation",
    35: "Comedy",
    80: "Crime",
    99: "Documentary",
    18: "Drama",
    10751: "Family",
    10762: "Kids",
    9648: "Mystery",
    10763: "News",
    10764: "Reality",
    10765: "Sci-Fi & Fantasy",
    10766: "Soap",
    10767: "Talk",
    10768: "War & Politics",
    37: "Western",
}


def get_genre_names(genre_ids: List[int], media_type: str = "movie") -> List[str]:
    """Convert genre IDs to names"""
    genres = MOVIE_GENRES if media_type == "movie" else TV_GENRES
    return [genres.get(gid, "Unknown") for gid in genre_ids if gid in genres]
