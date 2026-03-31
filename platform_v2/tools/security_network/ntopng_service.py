# platform_v2/tools/security_network/ntopng_service.py
"""ntopng REST API client — bandwidth, flows, hosts, protocol data."""
import logging
import os
import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("NTOPNG_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("NTOPNG_PORT", "3001"))
DEFAULT_USER = os.getenv("NTOPNG_USER", "admin")
DEFAULT_PASS = os.getenv("NTOPNG_ADMIN_PASSWORD", "")
TIMEOUT = 10


class NtopngService:
    """REST API client for ntopng traffic monitoring."""

    def __init__(self, host=None, port=None, user=None, password=None):
        self.host = host or DEFAULT_HOST
        self.port = port or DEFAULT_PORT
        self.user = user or DEFAULT_USER
        self.password = password or DEFAULT_PASS
        self.base_url = f"http://{self.host}:{self.port}"
        self.session = requests.Session()
        self.session.auth = (self.user, self.password)

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request to ntopng API."""
        try:
            url = f"{self.base_url}{endpoint}"
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"ntopng API error: {endpoint} — {e}")
            return {"rc": -1}

    def is_healthy(self) -> bool:
        """Check if ntopng is reachable."""
        try:
            resp = self.session.get(f"{self.base_url}/lua/rest/v2/get/ntopng/interfaces.lua", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def get_interfaces(self) -> list[dict]:
        data = self._get("/lua/rest/v2/get/ntopng/interfaces.lua")
        return data.get("rsp", [])

    def get_hosts(self, ifid: int = 0) -> list[dict]:
        data = self._get("/lua/rest/v2/get/host/active.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_host_details(self, host_ip: str, ifid: int = 0) -> dict:
        data = self._get("/lua/rest/v2/get/host/data.lua", {"ifid": ifid, "host": host_ip})
        return data.get("rsp", {})

    def get_interface_stats(self, ifid: int = 0) -> dict:
        data = self._get("/lua/rest/v2/get/interface/data.lua", {"ifid": ifid})
        return data.get("rsp", {})

    def get_top_talkers(self, ifid: int = 0) -> list[dict]:
        data = self._get("/lua/rest/v2/get/host/top.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_flows(self, ifid: int = 0) -> list[dict]:
        data = self._get("/lua/rest/v2/get/flow/active.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_l7_stats(self, ifid: int = 0) -> dict:
        data = self._get("/lua/rest/v2/get/interface/l7/stats.lua", {"ifid": ifid})
        return data.get("rsp", {})

    def get_host_traffic_history(self, host_ip: str, ifid: int = 0) -> list[dict]:
        data = self._get("/lua/rest/v2/get/host/ts.lua", {"ifid": ifid, "host": host_ip})
        return data.get("rsp", [])
