"""Hub connector — REST API client for ARCHIE platform."""

import logging
import aiohttp
from archie_engine.hub.auth import HubAuth

logger = logging.getLogger(__name__)


class HubConnector:
    """REST client for the ARCHIE Hub platform."""

    def __init__(self, hub_url: str, auth: HubAuth, timeout: int = 10):
        self.hub_url = hub_url.rstrip("/")
        self.auth = auth
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def get(self, path: str, params: dict | None = None) -> dict:
        """HTTP GET with auth headers. Returns parsed JSON or error dict."""
        url = f"{self.hub_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=self.auth.get_headers(), params=params) as resp:
                    data = await resp.json()
                    if resp.status >= 400:
                        return {"error": data.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    return data
        except Exception as e:
            logger.warning("Hub GET %s failed: %s", path, e)
            return {"error": str(e), "status": 0}

    async def post(self, path: str, data: dict | None = None) -> dict:
        """HTTP POST with auth headers. Returns parsed JSON or error dict."""
        url = f"{self.hub_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(url, headers=self.auth.get_headers(), json=data) as resp:
                    result = await resp.json()
                    if resp.status >= 400:
                        return {"error": result.get("error", f"HTTP {resp.status}"), "status": resp.status}
                    return result
        except Exception as e:
            logger.warning("Hub POST %s failed: %s", path, e)
            return {"error": str(e), "status": 0}
