# platform_v2/tools/security_network/ntopng_service.py
"""ntopng REST API client — bandwidth, flows, hosts, protocol data.

Uses cookie-based session auth (POST /authorize.html) since ntopng
does not support basic auth for REST API endpoints.
"""

import logging
import os
import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("NTOPNG_HOST", "192.168.1.200")
DEFAULT_PORT = int(os.getenv("NTOPNG_PORT", "3001"))
DEFAULT_USER = os.getenv("NTOPNG_USER", "admin")
DEFAULT_PASS = os.getenv("NTOPNG_ADMIN_PASSWORD", "admin")
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
        self._authenticated = False

    def _ensure_auth(self):
        """Authenticate via cookie-based session if not already done."""
        if self._authenticated:
            return
        try:
            resp = self.session.post(
                f"{self.base_url}/authorize.html",
                data={"user": self.user, "password": self.password},
                allow_redirects=True,
                timeout=TIMEOUT,
            )
            # Auth fails if we land on login or wrong-credentials page
            if "login" in resp.url or "wrong" in resp.url:
                logger.error("ntopng auth failed — wrong credentials")
                return
            self._authenticated = True
        except Exception as e:
            logger.error(f"ntopng auth error: {e}")

    def _get(self, endpoint: str, params: dict = None) -> dict:
        """Make a GET request to ntopng API with session auth."""
        self._ensure_auth()
        try:
            url = f"{self.base_url}{endpoint}"
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct or resp.text.strip().startswith("{"):
                return resp.json()
            # Got HTML instead of JSON — auth may have expired
            if self._authenticated:
                self._authenticated = False
                self._ensure_auth()
                resp = self.session.get(url, params=params, timeout=TIMEOUT)
                if "json" in resp.headers.get("Content-Type", ""):
                    return resp.json()
            logger.warning(f"ntopng returned HTML for {endpoint}")
            return {"rc": -1}
        except Exception as e:
            logger.error(f"ntopng API error: {endpoint} — {e}")
            return {"rc": -1}

    def is_healthy(self) -> bool:
        """Healthy only if ntopng returns AUTHENTICATED JSON.

        ntopng serves its login page with HTTP 200 when auth fails/expires, so a
        bare ``status_code == 200`` check reported healthy while every data call
        returned nothing (fail-open). Require a successful authenticated reply:
        _ensure_auth must have authenticated, and _get (which distinguishes the
        HTML login page from a JSON payload) must return rc == 0.
        """
        try:
            self._ensure_auth()
            if not self._authenticated:
                return False
            data = self._get("/lua/rest/v2/get/ntopng/interfaces.lua")
            return isinstance(data, dict) and data.get("rc", -1) == 0
        except Exception:
            return False

    def get_interfaces(self) -> list:
        data = self._get("/lua/rest/v2/get/ntopng/interfaces.lua")
        return data.get("rsp", [])

    def get_hosts(self, ifid: int = 0) -> list:
        data = self._get("/lua/rest/v2/get/host/active.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_local_hosts(self, ifid: int = 0) -> list:
        """Fetch all local-network hosts (192.168.x.x) from ntopng.

        Paginates through all results using perPage=100 and filters client-side
        to local IPs. ntopng's localHost param is not supported in community edition.
        """
        all_hosts = []
        page = 1
        per_page = 100
        while True:
            data = self._get(
                "/lua/rest/v2/get/host/active.lua",
                {"ifid": ifid, "currentPage": page, "perPage": per_page},
            )
            rsp = data.get("rsp", {})
            if isinstance(rsp, dict) and "data" in rsp:
                hosts = rsp["data"]
            elif isinstance(rsp, list):
                hosts = rsp
            else:
                hosts = []

            all_hosts.extend(hosts)

            # Stop when we get a partial page (last page) or nothing
            if len(hosts) < per_page:
                break
            page += 1
            # Safety cap — max 20 pages (2000 hosts)
            if page > 20:
                break

        # Filter to local LAN devices only
        return [
            h for h in all_hosts if isinstance(h, dict) and str(h.get("ip") or h.get("name", "")).startswith("192.168.")
        ]

    def get_host_details(self, host_ip: str, ifid: int = 0) -> dict:
        data = self._get("/lua/rest/v2/get/host/data.lua", {"ifid": ifid, "host": host_ip})
        return data.get("rsp", {})

    def get_interface_stats(self, ifid: int = 0) -> dict:
        data = self._get("/lua/rest/v2/get/interface/data.lua", {"ifid": ifid})
        return data.get("rsp", {})

    def get_top_talkers(self, ifid: int = 0) -> list:
        data = self._get("/lua/rest/v2/get/host/top.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_flows(self, ifid: int = 0) -> list:
        data = self._get("/lua/rest/v2/get/flow/active.lua", {"ifid": ifid})
        return data.get("rsp", [])

    def get_l7_stats(self, ifid: int = 0) -> dict:
        data = self._get("/lua/rest/v2/get/interface/l7/stats.lua", {"ifid": ifid})
        return data.get("rsp", {})

    def get_host_traffic_history(self, host_ip: str, ifid: int = 0) -> list:
        data = self._get("/lua/rest/v2/get/host/ts.lua", {"ifid": ifid, "host": host_ip})
        return data.get("rsp", [])
