# platform_v2/tools/security_network/nagios_service.py
"""Nagios CGI API client — host/service status, check results."""

import logging
import os
import requests

logger = logging.getLogger(__name__)

DEFAULT_HOST = os.getenv("NAGIOS_HOST", "192.168.1.200")
DEFAULT_PORT = int(os.getenv("NAGIOS_PORT", "8082"))
DEFAULT_USER = os.getenv("NAGIOS_USER", "nagiosadmin")
DEFAULT_PASS = os.getenv("NAGIOS_PASS", "")
TIMEOUT = 10


class NagiosService:
    """REST client for Nagios CGI API."""

    def __init__(self, host=None, port=None, user=None, password=None):
        self.host = host or DEFAULT_HOST
        self.port = port or DEFAULT_PORT
        self.user = user or DEFAULT_USER
        self.password = password or DEFAULT_PASS
        self.base_url = f"http://{self.host}:{self.port}/nagios/cgi-bin"
        self.session = requests.Session()
        self.session.auth = (self.user, self.password)

    def _get(self, endpoint: str, params: dict = None) -> dict:
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = self.session.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Nagios API error: {endpoint} — {e}")
            return {}

    def is_healthy(self) -> bool:
        try:
            resp = self.session.get(
                f"{self.base_url}/statusjson.cgi",
                params={"query": "hostcount"},
                timeout=5,
            )
            return resp.status_code == 200
        except Exception:
            return False

    def get_host_status(self) -> dict:
        data = self._get("statusjson.cgi", {"query": "hostlist", "details": "true"})
        return data.get("data", {}).get("hostlist", {})

    def get_service_status(self, host: str = None) -> dict:
        params = {"query": "servicelist", "details": "true"}
        if host:
            params["hostname"] = host
        data = self._get("statusjson.cgi", params)
        return data.get("data", {}).get("servicelist", {})

    def get_host_count(self) -> dict:
        data = self._get("statusjson.cgi", {"query": "hostcount"})
        return data.get("data", {})

    def get_service_count(self) -> dict:
        data = self._get("statusjson.cgi", {"query": "servicecount"})
        return data.get("data", {})

    def get_problems(self) -> dict:
        hosts = self.get_host_status()
        services = self.get_service_status()
        problems = {"hosts": {}, "services": {}}
        for name, info in hosts.items():
            if info.get("status", 0) != 2:
                problems["hosts"][name] = info
        for host, svcs in services.items():
            for svc_name, svc_info in svcs.items():
                if svc_info.get("status", 0) != 2:
                    if host not in problems["services"]:
                        problems["services"][host] = {}
                    problems["services"][host][svc_name] = svc_info
        return problems

    def get_all_for_cache(self) -> list:
        """Get all host/service data for caching in nagios_check_results table."""
        results = []
        hosts = self.get_host_status()
        for name, info in hosts.items():
            results.append(
                {
                    "host_name": name,
                    "service_description": "",
                    "status": self._status_text(info.get("status", 0), is_host=True),
                    "output": info.get("plugin_output", ""),
                    "performance_data": info.get("performance_data", ""),
                    "last_check": info.get("last_check", 0),
                }
            )
        services = self.get_service_status()
        for host, svcs in services.items():
            for svc_name, svc_info in svcs.items():
                results.append(
                    {
                        "host_name": host,
                        "service_description": svc_name,
                        "status": self._status_text(svc_info.get("status", 0), is_host=False),
                        "output": svc_info.get("plugin_output", ""),
                        "performance_data": svc_info.get("performance_data", ""),
                        "last_check": svc_info.get("last_check", 0),
                    }
                )
        return results

    @staticmethod
    def _status_text(code: int, is_host: bool) -> str:
        if is_host:
            return {1: "PENDING", 2: "UP", 4: "DOWN", 8: "UNREACHABLE"}.get(code, "UNKNOWN")
        return {1: "PENDING", 2: "OK", 4: "WARNING", 8: "UNKNOWN", 16: "CRITICAL"}.get(code, "UNKNOWN")
