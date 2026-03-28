"""Hub Skill Loader — pulls and executes skills from the A.R.C.H.I.E. hub.

The hub at http://HUB_URL has 48+ branded /archie-* skills.
This module fetches skill definitions and executes them via the hub's Bridge dispatch.

Works with the existing HubConnector (async aiohttp) for authenticated requests,
and provides a standalone sync client for non-engine use (e.g., CLI auth commands).

Usage (async, with engine):
    # Engine already has hub_connector wired
    loader = HubSkillLoader(engine.hub_connector)
    skills = await loader.list_skills()
    result = await loader.execute("archie-fix", "Fix the login bug", context="file content")

Usage (sync, standalone):
    from archie_engine.hub_skills import HubSkillClient
    client = HubSkillClient("http://192.168.1.200:3000", api_key="archie_xxx")
    skills = client.list_skills()
    result = client.execute("archie-fix", "Fix the login bug", context="file content here")
"""

import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_HUB_URL = "http://192.168.1.200:3000"
CONFIG_PATH = Path.home() / ".archie" / "credentials"

# Department HQ API base path
_DEPT_HQ = "/tools/department-hq"


# ─────────────────────────────────────────────────────────────
# Async loader — integrates with Engine's HubConnector
# ─────────────────────────────────────────────────────────────


class HubSkillLoader:
    """Async hub skill loader using the existing HubConnector."""

    def __init__(self, connector):
        """Accept a HubConnector instance (from engine)."""
        self.connector = connector
        self._skill_cache: list[dict] | None = None

    async def list_skills(self, use_cache: bool = True) -> list[dict]:
        """Get all available skills from hub Department HQ API."""
        if use_cache and self._skill_cache is not None:
            return self._skill_cache
        result = await self.connector.get(f"{_DEPT_HQ}/api/skills/list")
        if isinstance(result, dict) and "error" in result:
            logger.warning("Hub skill list failed: %s", result["error"])
            return []
        if isinstance(result, list):
            self._skill_cache = result
            return result
        # Some APIs wrap in {"skills": [...]}
        if isinstance(result, dict) and "skills" in result:
            self._skill_cache = result["skills"]
            return self._skill_cache
        return []

    async def get_skill(self, skill_name: str) -> dict:
        """Get a single skill definition from hub."""
        result = await self.connector.get(f"{_DEPT_HQ}/api/skills/{skill_name}")
        if isinstance(result, dict):
            return result
        return {"error": "Unexpected response format"}

    async def execute(self, skill_name: str, user_input: str, context: str = "") -> dict:
        """Execute a skill via hub Bridge dispatch. Returns response dict."""
        result = await self.connector.post(
            f"{_DEPT_HQ}/api/skills/{skill_name}/execute",
            data={"input": user_input, "context": context},
        )
        return result

    async def find_skill(self, name: str) -> dict | None:
        """Find a skill by name (supports archie-* prefix matching)."""
        skills = await self.list_skills()
        # Exact match first
        for s in skills:
            if s.get("name") == name:
                return s
        # Try without archie- prefix
        bare = name.removeprefix("archie-")
        for s in skills:
            if s.get("name", "").removeprefix("archie-") == bare:
                return s
        return None

    def invalidate_cache(self) -> None:
        """Clear the skill cache to force a re-fetch."""
        self._skill_cache = None


# ─────────────────────────────────────────────────────────────
# Sync client — for CLI auth and standalone usage
# ─────────────────────────────────────────────────────────────


class HubSkillClient:
    """Synchronous hub skill client using urllib (no aiohttp needed).

    Used by CLI auth commands and any context that doesn't have
    an async event loop.
    """

    def __init__(self, hub_url: str | None = None, api_key: str | None = None):
        self.hub_url = (hub_url or os.getenv("ARCHIE_HUB_URL", "") or DEFAULT_HUB_URL).rstrip("/")
        self.api_key = api_key or self._load_api_key()
        self._skill_cache: list[dict] | None = None

    def _load_api_key(self) -> str:
        """Load API key from env or ~/.archie/credentials."""
        key = os.getenv("ARCHIE_HUB_API_KEY", "") or os.getenv("ARCHIE_API_KEY", "")
        if key:
            return key
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text())
                return data.get("api_key", "")
        except Exception:
            pass
        return ""

    def _request(self, method: str, path: str, data: dict | None = None) -> dict | list:
        """Make authenticated request to hub."""
        url = f"{self.hub_url}{_DEPT_HQ}{path}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            logger.error("Hub API error %d: %s", e.code, error_body[:200])
            return {"error": f"HTTP {e.code}: {error_body[:200]}"}
        except Exception as e:
            logger.error("Hub request failed: %s", e)
            return {"error": str(e)}

    def list_skills(self, use_cache: bool = True) -> list[dict]:
        """Get all available skills from hub."""
        if use_cache and self._skill_cache is not None:
            return self._skill_cache
        result = self._request("GET", "/api/skills/list")
        if isinstance(result, list):
            self._skill_cache = result
            return result
        if isinstance(result, dict) and "skills" in result:
            self._skill_cache = result["skills"]
            return self._skill_cache
        return []

    def get_skill(self, skill_name: str) -> dict:
        """Get a single skill definition."""
        result = self._request("GET", f"/api/skills/{skill_name}")
        return result if isinstance(result, dict) else {"error": "Unexpected response"}

    def execute(self, skill_name: str, user_input: str, context: str = "") -> dict:
        """Execute a skill via hub Bridge dispatch. Returns response dict."""
        result = self._request(
            "POST",
            f"/api/skills/{skill_name}/execute",
            {"input": user_input, "context": context},
        )
        return result if isinstance(result, dict) else {"error": "Unexpected response"}

    def search_knowledge(self, query: str, limit: int = 10) -> dict | list:
        """Search the hub's knowledge base."""
        q = urllib.parse.quote(query)
        return self._request("GET", f"/api/knowledge/search?q={q}&limit={limit}")

    def register_device(self, device_name: str, device_type: str = "cli") -> dict:
        """Register this device with the hub. Returns pending status."""
        import socket

        hostname = socket.gethostname()
        result = self._request(
            "POST",
            "/api/auth/register",
            {
                "device_name": device_name,
                "device_type": device_type,
                "hostname": hostname,
                "purpose": "A.R.C.H.I.E. CLI skill execution",
            },
        )
        return result if isinstance(result, dict) else {"error": "Unexpected response"}

    def save_api_key(self, api_key: str) -> None:
        """Save API key to ~/.archie/credentials."""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps({"api_key": api_key, "hub_url": self.hub_url}, indent=2))
        try:
            os.chmod(CONFIG_PATH, 0o600)
        except OSError:
            pass  # Windows
        self.api_key = api_key


def get_hub_client() -> HubSkillClient:
    """Get a standalone (sync) hub client."""
    return HubSkillClient()
