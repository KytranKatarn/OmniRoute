"""COO consult — resolve a consult target (agent code-name or department) to a
dispatchable agent, and list the consultable crew. Pure resolution; the endpoint
in app.py does the DHQ dispatch. Slice 1 of the COO command surface."""

from __future__ import annotations


def _list_agents(**kwargs):
    from services.agent_service import list_agents

    return list_agents(**kwargs)


def _capability_department_map() -> dict:
    from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

    return CAPABILITY_DEPARTMENT_MAP


def list_consultable_agents() -> list[dict]:
    """Department directors (is_department_ai) — the crew Kytran consults through her."""
    rows = _list_agents(is_department_ai=True, status="active", limit=200)
    out = []
    for a in rows:
        out.append(
            {
                "name": a.get("name"),
                "department": a.get("department"),
                "is_department_ai": bool(a.get("is_department_ai")),
                "title": a.get("title") or "Director",
            }
        )
    return [a for a in out if a["name"] and a["department"]]


def _dept_capability(department: str) -> str:
    for cap, dep in _capability_department_map().items():
        if dep == department:
            return cap
    return "conversation"


def resolve_consult_target(target: str) -> dict | None:
    """target (agent code-name OR department) -> {agent_name, department, capability} or None."""
    t = (target or "").strip()
    if not t:
        return None
    tl = t.lower()
    # 1. Agent code-name (case-insensitive), among active agents.
    for a in _list_agents(status="active", limit=500):
        if (a.get("name") or "").lower() == tl:
            dep = a.get("department")
            return {"agent_name": a["name"], "department": dep, "capability": _dept_capability(dep)}
    # 2. Department name (exact or substring, case-insensitive) -> its director.
    for dep in set(_capability_department_map().values()):
        if tl == dep.lower() or tl in dep.lower():
            directors = _list_agents(department=dep, is_department_ai=True, status="active", limit=1)
            if directors:
                return {
                    "agent_name": directors[0]["name"],
                    "department": dep,
                    "capability": _dept_capability(dep),
                }
    return None
