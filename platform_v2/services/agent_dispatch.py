"""Agent Dispatch Service — candidate selection, scoring, escalation support.

Bridge dispatcher calls these to find the best agent for a task.
Selection logic is centralized here instead of scattered through the dispatcher.

Import:
    from services.agent_dispatch import (
        get_candidates, score_agent, get_best_agent, get_fleet_roster,
    )
"""

import logging
from database import get_db_cursor
from services.agent_service import (
    list_agents,
    get_skills,
    get_welfare,
    check_welfare_threshold,
    DEPARTMENT_FLOOR_MAP,
)

logger = logging.getLogger(__name__)

# Scoring weights (from bridge_dispatcher SELECTION_WEIGHTS)
WEIGHTS = {
    "skills": 0.30,
    "specialization": 0.25,
    "welfare": 0.15,
    "availability": 0.15,
    "budget": 0.05,
    "tier_match": 0.10,
}

FLOOR_DEPARTMENTS = {}
for _dept, _flr in DEPARTMENT_FLOOR_MAP.items():
    FLOOR_DEPARTMENTS.setdefault(_flr, []).append(_dept)


def score_agent(agent, capability):
    """Score an agent for a capability. Returns float 0.0-1.0."""
    score = 0.0
    agent_id = agent.get("id")

    # Skills score (0.30 weight)
    skills = get_skills(agent_id)
    skill_match = next((s for s in skills if s["skill_name"] == capability), None)
    skill_score = (skill_match["level"] / 5.0) if skill_match else 0.3
    score += skill_score * WEIGHTS["skills"]

    # Welfare score (0.15 weight)
    welfare = get_welfare(agent_id)
    if welfare:
        stress = float(welfare.get("stress_level", 0))
        energy = float(welfare.get("energy_level", 1))
        welfare_score = (1.0 - stress) * energy
    else:
        welfare_score = 0.7
    score += welfare_score * WEIGHTS["welfare"]

    # Availability (0.15 weight) — active agents score higher
    shift = agent.get("shift_state", "barracked")
    avail_score = 1.0 if shift == "active" else 0.5 if shift == "deployed" else 0.0
    score += avail_score * WEIGHTS["availability"]

    # Director bonus (0.25 weight for specialization)
    is_director = agent.get("is_department_ai", False)
    spec_score = 0.8 if is_director else 0.5
    score += spec_score * WEIGHTS["specialization"]

    # Budget (0.05 weight) — placeholder
    score += 0.8 * WEIGHTS["budget"]

    # Tier match (0.10 weight) — placeholder
    score += 0.5 * WEIGHTS["tier_match"]

    return round(score, 4)


def get_candidates(capability, department, include_cross_department=False):
    """Get scored candidate agents for a capability+department.

    Returns list of (agent_dict, score) sorted by score descending.
    """
    # Primary: agents in the target department
    agents = list_agents(department=department, shift_state="active")

    # Cross-department: same floor first, then all floors
    if include_cross_department and not agents:
        floor = DEPARTMENT_FLOOR_MAP.get(department)
        if floor:
            for sibling in FLOOR_DEPARTMENTS.get(floor, []):
                if sibling != department:
                    agents.extend(list_agents(department=sibling, shift_state="active"))
        if not agents:
            # All departments
            agents = list_agents(shift_state="active")

    # Filter out welfare-blocked agents
    healthy = []
    for agent in agents:
        ok, reason = check_welfare_threshold(agent["id"])
        if ok:
            healthy.append(agent)

    # Score and rank
    scored = [(agent, score_agent(agent, capability)) for agent in healthy]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def get_best_agent(capability, department):
    """Get the single best agent for a capability. Returns (agent_dict, score) or (None, 0)."""
    candidates = get_candidates(capability, department, include_cross_department=True)
    if candidates:
        return candidates[0]
    return None, 0.0


def get_fleet_roster():
    """Get full fleet view: hub agents + node-deployed agents."""
    with get_db_cursor() as (conn, cur):
        # Hub agents
        cur.execute(
            """SELECT a.id, a.name, a.display_name, a.department, a.floor,
                      a.model, a.shift_state, a.is_department_ai
               FROM agents a
               WHERE a.status = 'active' AND a.shift_state != 'deployed'
               ORDER BY a.floor, a.department"""
        )
        hub_agents = [dict(r) for r in cur.fetchall()]

        # Node-deployed agents
        cur.execute(
            """SELECT a.id, a.name, a.display_name, a.department, a.floor,
                      a.model, a.shift_state, na.node_id,
                      rn.node_name, rn.hostname
               FROM agents a
               JOIN node_agents na ON na.hub_agent_id = a.id AND na.status = 'active'
               JOIN remote_nodes rn ON rn.id = na.node_id
               WHERE a.shift_state = 'deployed'
               ORDER BY rn.node_name, a.department"""
        )
        node_agents = [dict(r) for r in cur.fetchall()]

    return {"hub": hub_agents, "nodes": node_agents}
