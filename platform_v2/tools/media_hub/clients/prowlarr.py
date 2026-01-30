"""
Prowlarr Client
===============
Client for interacting with Prowlarr indexer manager API.

Prowlarr manages indexers and syncs them to Sonarr/Radarr.
This client is mainly for health checks and indexer status.
"""

import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ProwlarrClient:
    """Client for Prowlarr indexer manager"""

    def __init__(self, host: str, port: int, api_key: str, use_ssl: bool = False):
        """
        Initialize Prowlarr client.

        Args:
            host: Prowlarr server host
            port: Prowlarr server port (usually 9696)
            api_key: Prowlarr API key
            use_ssl: Use HTTPS
        """
        protocol = "https" if use_ssl else "http"
        self.base_url = f"{protocol}://{host}:{port}/api/v1"
        self.api_key = api_key
        self.headers = {"X-Api-Key": api_key}
        self.timeout = 10

    def _request(self, endpoint: str, method: str = "GET", data: Optional[Dict] = None) -> Optional[Dict]:
        """Make request to Prowlarr API"""
        url = f"{self.base_url}/{endpoint}"

        try:
            if method == "GET":
                response = requests.get(url, headers=self.headers, timeout=self.timeout)
            elif method == "POST":
                response = requests.post(url, headers=self.headers, json=data, timeout=self.timeout)
            else:
                return None

            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Prowlarr API request failed: {e}")
            return None

    def test_connection(self) -> bool:
        """Test connection to Prowlarr server"""
        try:
            result = self._request("system/status")
            return result is not None and "version" in result
        except Exception as e:
            logger.error(f"Prowlarr connection test failed: {e}")
            return False

    def get_system_status(self) -> Optional[Dict[str, Any]]:
        """Get Prowlarr system status"""
        return self._request("system/status")

    def get_indexers(self) -> List[Dict[str, Any]]:
        """Get all configured indexers"""
        result = self._request("indexer")
        return result if result else []

    def get_indexer_stats(self) -> Dict[str, Any]:
        """Get indexer statistics"""
        indexers = self.get_indexers()

        enabled = [i for i in indexers if i.get("enable", False)]

        return {
            "total_indexers": len(indexers),
            "enabled_indexers": len(enabled),
            "disabled_indexers": len(indexers) - len(enabled),
            "indexers": [
                {
                    "id": i.get("id"),
                    "name": i.get("name"),
                    "protocol": i.get("protocol"),
                    "enabled": i.get("enable", False),
                    "priority": i.get("priority", 25),
                }
                for i in indexers
            ],
        }

    def test_indexer(self, indexer_id: int) -> bool:
        """Test a specific indexer"""
        result = self._request(f"indexer/{indexer_id}/test", method="POST")
        return result is not None

    def get_health(self) -> List[Dict[str, Any]]:
        """Get health check issues"""
        result = self._request("health")
        return result if result else []
