"""
Radarr Client
=============
Client for interacting with Radarr API.
"""

import requests
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
from ..services import ArrServiceInterface

logger = logging.getLogger(__name__)


class RadarrClient(ArrServiceInterface):
    """Client for Radarr movie management"""

    def __init__(self, host: str, port: int, api_key: str, use_ssl: bool = False):
        """
        Initialize Radarr client.

        Args:
            host: Radarr server host
            port: Radarr server port (usually 7878)
            api_key: Radarr API key
            use_ssl: Use HTTPS
        """
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{host}:{port}/api/v3"
        self.api_key = api_key
        self.timeout = 10

    def _request(self, endpoint: str, params: Optional[Dict] = None, method: str = "GET") -> Optional[Any]:
        """Make authenticated request to Radarr API"""
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=params, timeout=self.timeout)
            else:
                response = requests.request(method, url, headers=headers, json=params, timeout=self.timeout)

            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.RequestException as e:
            logger.error(f"Radarr API request failed: {e}")
            return None

    def probe(self) -> tuple[bool, str]:
        """Two-stage reachability + auth probe.

        `/ping` (served at root, not under /api/v3) needs no key so it
        tells us server-up vs server-down. Then `/system/status` with
        key tells us key-valid vs key-invalid — without the split, a
        bad key looks identical to a dead server.
        """
        ping_url = f"{self.base_url.rsplit('/api/v3', 1)[0]}/ping"
        try:
            resp = requests.get(ping_url, timeout=self.timeout)
            if resp.status_code != 200:
                return False, f"Radarr unreachable: /ping returned HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, f"Radarr unreachable at {ping_url}: {e}"

        if not self.api_key:
            return False, "Radarr reachable but no API key configured"

        try:
            resp = requests.get(
                urljoin(self.base_url + "/", "system/status"),
                headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return False, f"Radarr /system/status request failed: {e}"

        if resp.status_code == 401:
            return False, "Radarr API key invalid — re-paste key in Media Hub settings"
        if resp.status_code != 200:
            return False, f"Radarr /system/status returned HTTP {resp.status_code}"
        try:
            if "version" not in resp.json():
                return False, "Radarr responded but payload missing version"
        except ValueError:
            return False, "Radarr responded with non-JSON body"
        return True, "Connection successful"

    def test_connection(self) -> bool:
        """Backward-compatible boolean check. Use probe() for detail."""
        ok, _ = self.probe()
        return ok

    def get_queue(self) -> List[Dict[str, Any]]:
        """Get current download queue"""
        result = self._request("/queue", {"includeMovie": True})
        if result and "records" in result:
            return result["records"]
        return []

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search for movies"""
        result = self._request("/movie/lookup", {"term": query})
        if isinstance(result, list):
            return result
        return []

    def get_movies(self) -> List[Dict[str, Any]]:
        """Get all monitored movies"""
        result = self._request("/movie")
        if isinstance(result, list):
            return result
        return []

    def get_movie_by_id(self, movie_id: int) -> Optional[Dict[str, Any]]:
        """Get movie details by ID"""
        return self._request(f"/movie/{movie_id}")

    def get_movie_by_tmdb_id(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        """Get movie details by TMDB ID"""
        movies = self.get_movies()
        for movie in movies:
            if movie.get("tmdbId") == tmdb_id:
                return movie
        return None

    def get_missing_movies(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get missing movies (wanted but not downloaded)"""
        result = self._request(
            "/wanted/missing",
            {
                "pageSize": limit,
                "sortKey": "movieMetadata.sortTitle",
                "sortDirection": "ascending",
            },
        )
        if result and "records" in result:
            return result["records"]
        return []

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent history"""
        result = self._request(
            "/history",
            {
                "pageSize": limit,
                "sortKey": "date",
                "sortDirection": "descending",
                "includeMovie": True,
            },
        )
        if result and "records" in result:
            return result["records"]
        return []

    def get_disk_space(self) -> List[Dict[str, Any]]:
        """Get disk space info"""
        result = self._request("/diskspace")
        if isinstance(result, list):
            return result
        return []

    def refresh_movie(self, movie_id: int) -> bool:
        """Trigger a movie refresh"""
        result = self._request("/command", {"name": "RefreshMovie", "movieId": movie_id}, "POST")
        return result is not None

    def search_movie(self, movie_id: int) -> bool:
        """Trigger a movie search"""
        result = self._request("/command", {"name": "MoviesSearch", "movieIds": [movie_id]}, "POST")
        return result is not None

    def add_movie(
        self,
        tmdb_id: int,
        quality_profile_id: int,
        root_folder_path: str,
        monitored: bool = True,
        search_for_movie: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Add a movie to Radarr"""
        # First lookup the movie
        lookup_result = self._request("/movie/lookup/tmdb", {"tmdbId": tmdb_id})
        if not lookup_result:
            return None

        movie_data = lookup_result if isinstance(lookup_result, dict) else lookup_result[0] if lookup_result else None
        if not movie_data:
            return None

        # Prepare the add request
        add_data = {
            "title": movie_data.get("title"),
            "tmdbId": tmdb_id,
            "year": movie_data.get("year"),
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "addOptions": {"searchForMovie": search_for_movie},
            "images": movie_data.get("images", []),
            "titleSlug": movie_data.get("titleSlug", ""),
        }

        return self._request("/movie", add_data, "POST")

    def get_quality_profiles(self) -> List[Dict[str, Any]]:
        """Get available quality profiles"""
        result = self._request("/qualityprofile")
        if isinstance(result, list):
            return result
        return []

    def get_root_folders(self) -> List[Dict[str, Any]]:
        """Get available root folders"""
        result = self._request("/rootfolder")
        if isinstance(result, list):
            return result
        return []
