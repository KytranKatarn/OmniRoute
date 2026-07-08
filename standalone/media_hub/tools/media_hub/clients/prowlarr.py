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

    def probe(self) -> tuple[bool, str]:
        """Two-stage reachability + auth probe.

        `/ping` (served at root, not under /api/v1) needs no key so it
        tells us server-up vs server-down. Then `/system/status` with
        key tells us key-valid vs key-invalid — without the split, a
        bad key looks identical to a dead server.
        """
        ping_url = f"{self.base_url.rsplit('/api/v1', 1)[0]}/ping"
        try:
            resp = requests.get(ping_url, timeout=self.timeout)
            if resp.status_code != 200:
                return False, f"Prowlarr unreachable: /ping returned HTTP {resp.status_code}"
        except requests.RequestException as e:
            return False, f"Prowlarr unreachable at {ping_url}: {e}"

        if not self.api_key:
            return False, "Prowlarr reachable but no API key configured"

        try:
            resp = requests.get(
                f"{self.base_url}/system/status",
                headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            return False, f"Prowlarr /system/status request failed: {e}"

        if resp.status_code == 401:
            return False, "Prowlarr API key invalid — re-paste key in Media Hub settings"
        if resp.status_code != 200:
            return False, f"Prowlarr /system/status returned HTTP {resp.status_code}"
        try:
            if "version" not in resp.json():
                return False, "Prowlarr responded but payload missing version"
        except ValueError:
            return False, "Prowlarr responded with non-JSON body"
        return True, "Connection successful"

    def test_connection(self) -> bool:
        """Backward-compatible boolean check. Use probe() for detail."""
        ok, _ = self.probe()
        return ok

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
