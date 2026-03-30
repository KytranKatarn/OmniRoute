"""Agent-aware routing — maps task types to ARCHIE departments and selects best agent."""

import logging
import time
import re

logger = logging.getLogger(__name__)

# Maps task type → department name (matches agents.department in the platform)
TASK_DEPARTMENT_MAP = {
    "code_review": "Engineering & Technology",
    "code_generation": "Engineering & Technology",
    "bug_fix": "Engineering & Technology",
    "writing": "Creative & Design",
    "documentation": "Documentation & Knowledge",
    "analysis": "Analytics & Intelligence",
    "security": "Security & Compliance",
    "research": "Research & Development",
    "translation": "Creative & Design",
}

# Keyword patterns → task type (checked in order, first match wins)
_TASK_PATTERNS = [
    ("security", re.compile(r"\b(secur|vulnerabilit|CVE|exploit|pentest|harden)\w*", re.I)),
    ("bug_fix", re.compile(r"\b(fix|bug|error|crash|exception|traceback|broken)\w*", re.I)),
    ("code_review", re.compile(r"\b(review|audit|check|inspect|lint|critique)\w*", re.I)),
    ("documentation", re.compile(r"\b(document|docstring|readme|explain|describe)\w*", re.I)),
    ("analysis", re.compile(r"\b(analyz|investigat|diagnos|profile|benchmark|measur)\w*", re.I)),
    ("research", re.compile(r"\b(research|study|survey|compar|evaluat)\w*", re.I)),
    ("writing", re.compile(r"\b(write|draft|compos|essay|blog|article|copy)\w*", re.I)),
    ("translation", re.compile(r"\b(translat|locali[sz]|i18n|l10n)\w*", re.I)),
    ("code_generation", re.compile(r"\b(generat|creat|build|implement|scaffold|add)\w*", re.I)),
]

_AGENT_CACHE_TTL = 300  # 5 minutes


def detect_task_type(prompt: str) -> str | None:
    """Return the best-matching task type for a prompt, or None if no match."""
    for task_type, pattern in _TASK_PATTERNS:
        if pattern.search(prompt):
            return task_type
    return None


class AgentRouter:
    """Caches the hub agent list and resolves the best agent for a task type."""

    def __init__(self, hub_connector=None):
        self.hub_connector = hub_connector
        self._agents: list[dict] = []
        self._cache_ts: float = 0.0

    async def refresh_agents(self, force: bool = False) -> None:
        """Fetch the agent list from hub if cache is stale."""
        if not self.hub_connector:
            return
        now = time.monotonic()
        if not force and (now - self._cache_ts) < _AGENT_CACHE_TTL and self._agents:
            return
        try:
            result = await self.hub_connector.list_agents()
            # list_agents may return {"agents": [...]} or a raw list
            if isinstance(result, list):
                self._agents = result
            elif isinstance(result, dict):
                self._agents = result.get("agents", result.get("result", []))
            else:
                self._agents = []
            self._cache_ts = now
            logger.debug("AgentRouter: cached %d agents", len(self._agents))
        except Exception as e:
            logger.warning("AgentRouter: failed to fetch agents: %s", e)

    def _active_agents_for_department(self, department: str) -> list[dict]:
        """Return active/deployed agents in the given department."""
        return [
            a for a in self._agents
            if (a.get("department") or "").lower() == department.lower()
            and a.get("shift_state") in ("active", "deployed")
        ]

    async def resolve(self, prompt: str) -> dict:
        """Return routing hints: task_type, department, agent_name, agent_model.

        All fields may be None if no match or hub not connected.
        """
        task_type = detect_task_type(prompt)
        if not task_type:
            return {"task_type": None, "department": None, "agent_name": None, "agent_model": None}

        department = TASK_DEPARTMENT_MAP.get(task_type)
        if not department:
            return {"task_type": task_type, "department": None, "agent_name": None, "agent_model": None}

        await self.refresh_agents()
        candidates = self._active_agents_for_department(department)

        agent_name = None
        agent_model = None
        if candidates:
            # Prefer agents with a loaded/warm model; otherwise take the first active one
            warm = [a for a in candidates if a.get("current_model")]
            pick = warm[0] if warm else candidates[0]
            agent_name = pick.get("display_name") or pick.get("name")
            agent_model = pick.get("current_model") or pick.get("model")

        return {
            "task_type": task_type,
            "department": department,
            "agent_name": agent_name,
            "agent_model": agent_model,
        }
