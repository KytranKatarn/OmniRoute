"""
Overseerr/Jellyseerr Client
===========================
Client for interacting with Overseerr/Jellyseerr API.
Works with both Overseerr and Jellyseerr as they share the same API.
"""

import requests
import logging
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
from ..services import RequestServiceInterface, MediaItem, MediaRequest, MediaType

logger = logging.getLogger(__name__)


class OverseerrClient(RequestServiceInterface):
    """Client for Overseerr/Jellyseerr request management"""

    def __init__(self, host: str, port: int, api_key: str, use_ssl: bool = False):
        """
        Initialize Overseerr client.

        Args:
            host: Overseerr server host
            port: Overseerr server port (usually 5055)
            api_key: Overseerr API key
            use_ssl: Use HTTPS
        """
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{host}:{port}/api/v1"
        self.api_key = api_key
        self.timeout = 10

    def _request(
        self,
        endpoint: str,
        params: Optional[Dict] = None,
        method: str = "GET",
        json_data: Optional[Dict] = None,
    ) -> Optional[Any]:
        """Make authenticated request to Overseerr API"""
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        headers = {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=json_data, timeout=self.timeout)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=self.timeout)
            else:
                response = requests.request(method, url, headers=headers, json=json_data, timeout=self.timeout)

            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.RequestException as e:
            logger.error(f"Overseerr API request failed: {e}")
            return None

    def probe(self) -> tuple[bool, str]:
        """Two-stage reachability + auth probe.

        `/status` needs no key so it tells us server-up vs server-down.
        Then `/settings/main` with key tells us key-valid vs key-invalid —
        without the split, a bad key looks identical to a dead server.
        """
        status_url = urljoin(self.base_url + "/", "status")
        try:
            resp = requests.get(status_url, timeout=self.timeout)
            if resp.status_code != 200:
                return False, f"Overseerr unreachable: /status returned HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, f"Overseerr unreachable at {self.base_url}: {e}"

        if not self.api_key:
            return False, "Overseerr reachable but no API key configured"

        try:
            resp = requests.get(
                urljoin(self.base_url + "/", "settings/main"),
                headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return False, f"Overseerr /settings/main request failed: {e}"

        if resp.status_code in (401, 403):
            return False, "Overseerr API key invalid — re-paste key in Media Hub settings"
        if resp.status_code != 200:
            return False, f"Overseerr /settings/main returned HTTP {resp.status_code}"
        return True, "Connection successful"

    def test_connection(self) -> bool:
        """Backward-compatible boolean check. Use probe() for detail."""
        ok, _ = self.probe()
        return ok

    def _build_poster_url(self, poster_path: Optional[str]) -> Optional[str]:
        """Build TMDB poster URL"""
        if poster_path:
            return f"https://image.tmdb.org/t/p/w500{poster_path}"
        return None

    def _parse_search_result(self, item: Dict) -> MediaItem:
        """Parse Overseerr search result to unified format"""
        media_type_str = item.get("mediaType", "movie")
        media_type = MediaType.MOVIE if media_type_str == "movie" else MediaType.SHOW

        # Check if in library
        media_info = item.get("mediaInfo")
        in_library = media_info is not None and media_info.get("status", 0) in [
            4,
            5,
        ]  # 4=available, 5=partially available

        return MediaItem(
            id=str(item.get("id", "")),
            title=item.get("title") or item.get("name", "Unknown"),
            media_type=media_type,
            year=(
                int(item.get("releaseDate", item.get("firstAirDate", ""))[:4])
                if (item.get("releaseDate") or item.get("firstAirDate", ""))
                else None
            ),
            overview=item.get("overview", ""),
            poster_url=self._build_poster_url(item.get("posterPath")),
            backdrop_url=self._build_poster_url(item.get("backdropPath")),
            rating=item.get("voteAverage"),
            rating_source="tmdb",
            genres=[],  # Would need additional API call for genre names
            runtime_minutes=None,
            tmdb_id=item.get("id"),
            in_library=in_library,
            metadata={
                "mediaType": media_type_str,
                "popularity": item.get("popularity"),
                "voteCount": item.get("voteCount"),
                "status": media_info.get("status") if media_info else None,
            },
        )

    def search(self, query: str) -> List[MediaItem]:
        """Search TMDB/TVDB for media"""
        result = self._request("/search", {"query": query, "page": 1, "language": "en"})
        items = []

        if result and "results" in result:
            for item in result["results"][:20]:  # Limit to 20 results
                items.append(self._parse_search_result(item))

        return items

    def get_requests(self, status: Optional[str] = None) -> List[MediaRequest]:
        """
        Get media requests.

        Args:
            status: Filter by status ('pending', 'approved', 'declined', 'available', 'processing')
        """
        params = {"take": 50, "skip": 0}
        if status:
            params["filter"] = status

        result = self._request("/request", params)
        requests_list = []

        if result and "results" in result:
            for item in result["results"]:
                media = item.get("media", {})

                # Determine status
                # Request status: 1=pending, 2=approved, 3=declined, 4=failed
                req_status = "pending"
                if item.get("status") == 1:
                    req_status = "pending"
                elif item.get("status") == 2:
                    req_status = "approved"
                elif item.get("status") == 3:
                    req_status = "declined"
                elif item.get("status") == 4:
                    req_status = "failed"

                # Media status overrides request status for available/processing
                media_status = media.get("status", 0)
                if media_status in (4, 5):  # 4=PARTIALLY_AVAILABLE, 5=AVAILABLE
                    req_status = "available"
                elif media_status == 3:
                    req_status = "processing"

                # Get requester info
                requested_by = None
                requester = item.get("requestedBy", {})
                if requester:
                    requested_by = (
                        requester.get("displayName") or requester.get("email") or requester.get("plexUsername")
                    )

                requests_list.append(
                    MediaRequest(
                        id=str(item.get("id", "")),
                        media_type=item.get("type", "movie"),
                        title=media.get("title") or media.get("name", "Unknown"),
                        year=(
                            media.get("releaseDate", media.get("firstAirDate", ""))[:4]
                            if media.get("releaseDate") or media.get("firstAirDate")
                            else None
                        ),
                        poster_url=self._build_poster_url(media.get("posterPath")),
                        tmdb_id=media.get("tmdbId"),
                        status=req_status,
                        requested_by=requested_by,
                        requested_at=item.get("createdAt"),
                        seasons_requested=[s.get("seasonNumber") for s in item.get("seasons", [])],
                    )
                )

        return requests_list

    def create_request(self, media_type: str, tmdb_id: int, seasons: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Create a new media request.

        Args:
            media_type: 'movie' or 'tv'
            tmdb_id: TMDB ID of the media
            seasons: List of season numbers (for TV shows)

        Returns:
            API response
        """
        data = {"mediaType": media_type, "mediaId": tmdb_id}

        if media_type == "tv" and seasons:
            data["seasons"] = seasons

        result = self._request("/request", method="POST", json_data=data)
        return result if result else {"success": False, "error": "Request failed"}

    def get_media_status(self, tmdb_id: int, media_type: str = "movie") -> Optional[Dict[str, Any]]:
        """
        Get the status of a specific media item.

        Args:
            tmdb_id: TMDB ID
            media_type: 'movie' or 'tv'

        Returns:
            Media status information
        """
        endpoint = f"/{media_type}/{tmdb_id}"
        return self._request(endpoint)

    def get_discover(self, media_type: str = "movie", page: int = 1) -> List[MediaItem]:
        """
        Get discover results (trending/popular).

        Args:
            media_type: 'movie' or 'tv'
            page: Page number

        Returns:
            List of media items
        """
        result = self._request(f"/discover/{media_type}", {"page": page})
        items = []

        if result and "results" in result:
            for item in result["results"]:
                items.append(self._parse_search_result(item))

        return items

    def delete_request(self, request_id: int) -> bool:
        """Delete a media request"""
        result = self._request(f"/request/{request_id}", method="DELETE")
        return result is not None

    def get_trending(self, media_type: str = "all") -> List[MediaItem]:
        """
        Get trending media.

        Args:
            media_type: 'movie', 'tv', or 'all'

        Returns:
            List of trending media items
        """
        result = self._request("/discover/trending")
        items = []

        if result and "results" in result:
            for item in result["results"]:
                item_type = item.get("mediaType", "movie")
                if media_type == "all" or item_type == media_type:
                    items.append(self._parse_search_result(item))

        return items
