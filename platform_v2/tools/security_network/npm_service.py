"""
Nginx Proxy Manager API Service
================================
Client for NPM REST API proxy host and SSL management.
"""

import os
import logging
import requests
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class NPMService:
    """Nginx Proxy Manager API client."""

    def __init__(self):
        self.base_url = os.getenv("NPM_API_URL", "http://nginx_proxy_manager:81/api")
        self.email = os.getenv("NPM_ADMIN_EMAIL", "")
        self.password = os.getenv("NPM_ADMIN_PASSWORD", "")
        self.token = None

    @property
    def available(self) -> bool:
        return bool(self.email and self.password)

    def _auth(self):
        """Authenticate and get JWT token."""
        if self.token:
            return
        resp = requests.post(
            f"{self.base_url}/tokens",
            json={"identity": self.email, "secret": self.password},
            timeout=15,
        )
        resp.raise_for_status()
        self.token = resp.json()["token"]

    def _headers(self) -> Dict[str, str]:
        self._auth()
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, endpoint: str, data: Any = None, timeout: int = 15) -> Optional[Any]:
        """Make an authenticated request to NPM API."""
        try:
            url = f"{self.base_url}/{endpoint}"
            resp = requests.request(method, url, headers=self._headers(), json=data, timeout=timeout)
            resp.raise_for_status()
            return resp.json() if resp.content else {"status": "ok"}
        except Exception as e:
            logger.error("NPM API error (%s %s): %s", method, endpoint, e)
            return {"error": str(e)}

    STREAMING_ADVANCED_CONFIG = "proxy_buffering off;\n" "proxy_request_buffering off;\n" "proxy_cache off;"

    # --- Proxy Hosts ---
    def list_proxy_hosts(self) -> List[Dict]:
        """List all proxy hosts."""
        result = self._request("GET", "nginx/proxy-hosts")
        logger.info(
            "NPM list_proxy_hosts raw result type=%s len=%s",
            type(result).__name__,
            len(result) if isinstance(result, list) else "n/a",
        )
        if isinstance(result, dict) and "error" in result:
            logger.warning("NPM list_proxy_hosts returned error: %s", result.get("error"))
            return []
        return result or []

    def get_proxy_host(self, host_id: int) -> Optional[Dict]:
        """Get a single proxy host by ID."""
        return self._request("GET", f"nginx/proxy-hosts/{host_id}")

    def create_proxy_host(
        self,
        domain: str,
        forward_host: str,
        forward_port: int,
        ssl: bool = True,
        streaming: bool = False,
        advanced_config: str = "",
    ) -> Dict:
        """Create a proxy host in NPM.

        Args:
            streaming: If True, disables proxy buffering/caching for SSE/WebSocket endpoints.
            advanced_config: Raw nginx config (overrides streaming if non-empty).
        """
        resolved_config = advanced_config or (self.STREAMING_ADVANCED_CONFIG if streaming else "")

        payload = {
            "domain_names": [domain],
            "forward_scheme": "http",
            "forward_host": forward_host,
            "forward_port": forward_port,
            "block_exploits": True,
            "allow_websocket_upgrade": True,
            "access_list_id": 0,
            "certificate_id": 0,
            "ssl_forced": False,
            "meta": {"letsencrypt_agree": True},
            "advanced_config": resolved_config,
            "locations": [],
            "http2_support": True,
            "hsts_enabled": False,
            "hsts_subdomains": False,
        }

        result = self._request("POST", "nginx/proxy-hosts", payload)
        if isinstance(result, dict) and "error" in result:
            return result

        if ssl and result and "id" in result:
            try:
                self.request_ssl(result["id"], domain)
            except Exception as e:
                logger.warning("SSL request failed for %s: %s", domain, e)

        return result

    def update_proxy_host(self, host_id: int, data: Dict) -> Optional[Dict]:
        """Update a proxy host."""
        return self._request("PUT", f"nginx/proxy-hosts/{host_id}", data)

    def delete_proxy_host(self, host_id: int) -> Optional[Dict]:
        """Delete a proxy host."""
        return self._request("DELETE", f"nginx/proxy-hosts/{host_id}")

    # --- Certificates ---
    def list_certificates(self) -> List[Dict]:
        """List all SSL certificates."""
        result = self._request("GET", "nginx/certificates")
        if isinstance(result, dict) and "error" in result:
            return []
        return result or []

    def request_ssl(self, proxy_host_id: int, domain: str) -> Optional[Dict]:
        """Request Let's Encrypt SSL and attach to proxy host."""
        cert_result = self._request(
            "POST",
            "nginx/certificates",
            {
                "domain_names": [domain],
                "meta": {},
                "provider": "letsencrypt",
            },
        )
        if isinstance(cert_result, dict) and "error" in cert_result:
            return cert_result

        if cert_result and "id" in cert_result:
            self._request(
                "PUT",
                f"nginx/proxy-hosts/{proxy_host_id}",
                {
                    "certificate_id": cert_result["id"],
                    "ssl_forced": True,
                    "http2_support": True,
                },
            )

        return cert_result

    def check_health(self) -> bool:
        """Verify NPM API connectivity."""
        if not self.available:
            return False
        try:
            result = self.list_proxy_hosts()
            return isinstance(result, list)
        except Exception:
            return False
