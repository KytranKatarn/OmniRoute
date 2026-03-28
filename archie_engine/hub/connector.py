"""Hub connector — REST API client for ARCHIE platform."""

import logging
import aiohttp
from archie_engine.hub.auth import HubAuth

logger = logging.getLogger(__name__)


class HubConnector:
    """REST client for the ARCHIE Hub platform.

    Uses the API Gateway (/api/v1/) for tool execution,
    giving the CLI the same capabilities as Claude's MCP access.
    """

    def __init__(self, hub_url: str, auth: HubAuth, timeout: int = 10):
        self.hub_url = hub_url.rstrip("/")
        self.auth = auth
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def get(self, path: str, params: dict | None = None) -> dict:
        """HTTP GET with auth headers."""
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
        """HTTP POST with auth headers."""
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

    # ─────────────────────────────────────────────
    # Generic MCP tool execution (API Gateway)
    # ─────────────────────────────────────────────

    async def call_tool(self, tool_name: str, params: dict | None = None) -> dict:
        """Execute any MCP tool by name via the API Gateway.

        This is the primary method — gives CLI access to all 81 MCP tools.
        """
        result = await self.post(f"/api/v1/tools/{tool_name}", data=params or {})
        if "error" not in result and "result" in result:
            return result["result"]
        return result

    async def list_available_tools(self, category: str | None = None) -> dict:
        """List all available MCP tools from the hub."""
        params = {"category": category} if category else None
        return await self.get("/api/v1/tools", params=params)

    # ─────────────────────────────────────────────
    # Node registration + heartbeat
    # ─────────────────────────────────────────────

    async def register_node(self, hostname: str, gpu_model: str | None = None,
                            ram_gb: int | None = None, engine_version: str = "0.1.0") -> dict:
        return await self.post("/api/v1/nodes/register", data={
            "hostname": hostname,
            "gpu_model": gpu_model,
            "ram_gb": ram_gb,
            "engine_version": engine_version,
        })

    async def send_heartbeat(self, node_id: str, metrics: dict | None = None) -> dict:
        return await self.post(f"/api/v1/nodes/{node_id}/heartbeat", data={
            "metrics": metrics or {},
        })

    async def health_check(self) -> dict:
        return await self.get("/api/v1/health")

    # ─────────────────────────────────────────────
    # Convenience methods (wrap call_tool)
    # ─────────────────────────────────────────────

    async def search_knowledge(self, query: str, types: list[str] | None = None,
                               limit: int = 10) -> dict:
        return await self.call_tool("search_knowledge", {
            "query": query, "types": types, "limit": limit,
        })

    async def store_memory(self, content: str, knowledge_type: str = "vault_note",
                           title: str = "", tags: list[str] | None = None) -> dict:
        return await self.call_tool("store_memory", {
            "content": content, "knowledge_type": knowledge_type,
            "title": title, "tags": tags or [],
        })

    async def recall_context(self, topic: str) -> dict:
        return await self.call_tool("recall_context", {"topic": topic})

    async def log_decision(self, title: str, decision: str, context: str = "",
                           project_id: int | None = None) -> dict:
        params = {"title": title, "decision": decision, "context": context}
        if project_id:
            params["project_id"] = project_id
        return await self.call_tool("log_decision", params)

    async def create_task(self, project_id: int, title: str, description: str = "",
                          priority: int = 5) -> dict:
        return await self.call_tool("create_task", {
            "project_id": project_id, "title": title,
            "description": description, "priority": priority,
        })

    async def complete_task(self, task_id: int, notes: str = "") -> dict:
        return await self.call_tool("complete_task", {
            "task_id": task_id, "notes": notes,
        })

    async def get_projects(self) -> dict:
        return await self.call_tool("get_projects", {})

    async def get_my_tasks(self, status: str = "pending") -> dict:
        return await self.call_tool("get_my_tasks", {"status": status})

    async def list_agents(self) -> dict:
        return await self.call_tool("list_agents", {})

    async def get_quick_summary(self) -> dict:
        return await self.call_tool("get_quick_summary", {})

    async def session_briefing(self, topic: str = "platform status") -> dict:
        return await self.call_tool("session_briefing", {"topic": topic})

    async def search_mistakes(self) -> dict:
        return await self.call_tool("search_mistakes", {})

    async def dispatch(self, prompt: str, model: str | None = None,
                       agent_target: str | None = None, user_context: dict | None = None) -> dict:
        """Dispatch through Bridge — uses generate_code tool for inference."""
        return await self.call_tool("generate_code", {
            "prompt": prompt, "model": model or "",
            "agent_target": agent_target or "",
            "context": user_context or {},
        })

    async def get_skills(self) -> dict:
        return await self.call_tool("get_skills_matrix", {})

    # ─────────────────────────────────────────────
    # Department HQ Skills API
    # ─────────────────────────────────────────────

    async def list_hub_skills(self) -> dict | list:
        """List all skills via Department HQ API."""
        return await self.get("/tools/department-hq/api/skills/list")

    async def get_hub_skill(self, skill_name: str) -> dict:
        """Get a single skill definition from Department HQ."""
        return await self.get(f"/tools/department-hq/api/skills/{skill_name}")

    async def execute_hub_skill(self, skill_name: str, user_input: str,
                                context: str = "") -> dict:
        """Execute a skill via Department HQ Bridge dispatch."""
        return await self.post(f"/tools/department-hq/api/skills/{skill_name}/execute", data={
            "input": user_input,
            "context": context,
        })

    async def get_model_state(self) -> dict:
        return await self.call_tool("get_llm_health", {})

    async def update_project_understanding(self, project_id: int,
                                           understanding_level: int = 50) -> dict:
        return await self.call_tool("update_project_understanding", {
            "project_id": project_id,
            "understanding_level": understanding_level,
        })
