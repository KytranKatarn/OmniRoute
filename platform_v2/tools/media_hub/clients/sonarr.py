"""
Sonarr Client
=============
Client for interacting with Sonarr API.
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin
from ..services import ArrServiceInterface, CalendarServiceInterface, UpcomingEpisode

logger = logging.getLogger(__name__)


class SonarrClient(ArrServiceInterface, CalendarServiceInterface):
    """Client for Sonarr TV show management"""

    def __init__(self, host: str, port: int, api_key: str, use_ssl: bool = False):
        """
        Initialize Sonarr client.

        Args:
            host: Sonarr server host
            port: Sonarr server port (usually 8989)
            api_key: Sonarr API key
            use_ssl: Use HTTPS
        """
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{host}:{port}/api/v3"
        self.api_key = api_key
        self.timeout = 10

    def _request(self, endpoint: str, params: Optional[Dict] = None, method: str = "GET") -> Optional[Any]:
        """Make authenticated request to Sonarr API"""
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
            logger.error(f"Sonarr API request failed: {e}")
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
                return False, f"Sonarr unreachable: /ping returned HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, f"Sonarr unreachable at {ping_url}: {e}"

        if not self.api_key:
            return False, "Sonarr reachable but no API key configured"

        try:
            resp = requests.get(
                urljoin(self.base_url + "/", "system/status"),
                headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return False, f"Sonarr /system/status request failed: {e}"

        if resp.status_code == 401:
            return False, "Sonarr API key invalid — re-paste key in Media Hub settings"
        if resp.status_code != 200:
            return False, f"Sonarr /system/status returned HTTP {resp.status_code}"
        try:
            if "version" not in resp.json():
                return False, "Sonarr responded but payload missing version"
        except ValueError:
            return False, "Sonarr responded with non-JSON body"
        return True, "Connection successful"

    def test_connection(self) -> bool:
        """Backward-compatible boolean check. Use probe() for detail."""
        ok, _ = self.probe()
        return ok

    def get_queue(self) -> List[Dict[str, Any]]:
        """Get current download queue"""
        result = self._request("/queue", {"includeEpisode": True, "includeSeries": True})
        if result and "records" in result:
            return result["records"]
        return []

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search for TV shows"""
        result = self._request("/series/lookup", {"term": query})
        if isinstance(result, list):
            return result
        return []

    def get_series(self) -> List[Dict[str, Any]]:
        """Get all monitored series"""
        result = self._request("/series")
        if isinstance(result, list):
            return result
        return []

    def get_series_by_id(self, series_id: int) -> Optional[Dict[str, Any]]:
        """Get series details by ID"""
        return self._request(f"/series/{series_id}")

    def get_upcoming_episodes(self, days: int = 7, start_date: str = None) -> List[UpcomingEpisode]:
        """Get upcoming episodes for the next N days from the given start date"""
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            start = datetime.now()
        start_date_str = start.strftime("%Y-%m-%d")
        end_date = (start + timedelta(days=days)).strftime("%Y-%m-%d")

        result = self._request(
            "/calendar",
            {
                "start": start_date_str,
                "end": end_date,
                "includeSeries": True,
                "includeEpisodeFile": True,
            },
        )

        episodes = []
        if isinstance(result, list):
            for item in result:
                series = item.get("series", {})
                poster_url = None

                # Get poster from series images
                for image in series.get("images", []):
                    if image.get("coverType") == "poster":
                        poster_url = image.get("remoteUrl") or image.get("url")
                        break

                air_date_str = item.get("airDateUtc", item.get("airDate", ""))
                air_date = air_date_str.split("T")[0] if air_date_str else ""
                air_time = air_date_str.split("T")[1][:5] if "T" in air_date_str else None

                episodes.append(
                    UpcomingEpisode(
                        series_id=item.get("seriesId", 0),
                        series_title=series.get("title", item.get("series", {}).get("title", "Unknown")),
                        season_number=item.get("seasonNumber", 0),
                        episode_number=item.get("episodeNumber", 0),
                        episode_title=item.get("title"),
                        air_date=air_date,
                        air_time=air_time,
                        overview=item.get("overview"),
                        poster_url=poster_url,
                        runtime_minutes=series.get("runtime"),
                        has_file=item.get("hasFile", False),
                        monitored=item.get("monitored", True),
                    )
                )

        return episodes

    def get_missing_episodes(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get missing episodes"""
        result = self._request(
            "/wanted/missing",
            {
                "pageSize": limit,
                "sortKey": "airDateUtc",
                "sortDirection": "descending",
                "includeSeries": True,
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
                "includeSeries": True,
                "includeEpisode": True,
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

    def refresh_series(self, series_id: int) -> bool:
        """Trigger a series refresh"""
        result = self._request("/command", {"name": "RefreshSeries", "seriesId": series_id}, "POST")
        return result is not None

    def search_series(self, series_id: int) -> bool:
        """Trigger a series search"""
        result = self._request("/command", {"name": "SeriesSearch", "seriesId": series_id}, "POST")
        return result is not None
