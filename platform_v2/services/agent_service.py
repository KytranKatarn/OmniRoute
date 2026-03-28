"""Agent Service — THE single authority for all agent operations.

No other file should INSERT/UPDATE/DELETE on agents, agent_skills,
agent_emotional_state, agent_identity, or node_agents directly.
All mutations go through this service.

Import:
    from services.agent_service import (
        get_agent, list_agents, create_agent, update_agent, delete_agent,
        activate, barracks, deploy_to_node, return_from_node,
        get_org_chart, get_department_summary,
    )
"""

import json
import logging
import os
from database import get_db_cursor

logger = logging.getLogger(__name__)

DEPARTMENT_FLOOR_MAP = {
    "Executive Office": "BRIDGE",
    "Operations & Infrastructure": "OPERATIONS",
    "Logistics & Supply Chain": "OPERATIONS",
    "Finance & Accounting": "OPERATIONS",
    "Engineering & Technology": "ENGINEERING",
    "Security & Compliance": "ENGINEERING",
    "Research & Development": "ENGINEERING",
    "Creative & Design": "CREATIVE",
    "Marketing & Communications": "CREATIVE",
    "Documentation & Knowledge": "CREATIVE",
    "Customer Success & Support": "SERVICES",
    "Human Resources & Culture": "SERVICES",
    "Medical & Wellness": "SERVICES",
    "Legal & Regulatory": "SERVICES",
    "Diplomatic & External Relations": "SERVICES",
    "Analytics & Intelligence": "SERVICES",
}

VALID_SHIFT_STATES = ("active", "deployed", "barracked", "off_duty", "winding_down", "cooldown")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def get_agent(agent_id):
    """Get full agent profile by ID. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT a.*,
                      aes.stress_level, aes.energy_level, aes.mood, aes.mood_intensity
               FROM agents a
               LEFT JOIN agent_emotional_state aes ON aes.agent_id = a.id
               WHERE a.id = %s""",
            (agent_id,),
        )
        return dict(cur.fetchone()) if cur.rowcount else None


def get_agent_by_name(name):
    """Get agent by code name. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM agents WHERE name = %s", (name,))
        return dict(cur.fetchone()) if cur.rowcount else None


def list_agents(
    department=None, floor=None, shift_state=None, skill=None, search=None, is_department_ai=None, limit=200
):
    """List agents with optional filters. Returns list of dicts."""
    conditions = []
    params = []

    if department:
        conditions.append("a.department = %s")
        params.append(department)
    if floor:
        conditions.append("a.floor = %s")
        params.append(floor)
    if shift_state:
        conditions.append("a.shift_state = %s")
        params.append(shift_state)
    if is_department_ai is not None:
        conditions.append("a.is_department_ai = %s")
        params.append(is_department_ai)
    if search:
        conditions.append("(a.name ILIKE %s OR a.display_name ILIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    params.append(limit)

    with get_db_cursor() as (conn, cur):
        cur.execute(
            f"""SELECT a.id, a.name, a.display_name, a.department, a.floor,
                       a.model, a.status, a.shift_state, a.is_department_ai,
                       a.temperature, a.max_tokens, a.system_prompt,
                       a.capabilities, a.metadata
                FROM agents a {where}
                ORDER BY a.floor, a.department, a.is_department_ai DESC, a.name
                LIMIT %s""",
            params,
        )
        return [dict(r) for r in cur.fetchall()]


def create_agent(name, display_name, department, model, **kwargs):
    """Create a new agent. Returns agent_id.

    Required: name, display_name, department, model
    Optional kwargs: system_prompt, temperature, max_tokens, capabilities,
                     is_department_ai, shift_state, tier, worker_type
    """
    floor = DEPARTMENT_FLOOR_MAP.get(department, "SERVICES")
    shift_state = kwargs.get("shift_state", "barracked")

    if department not in DEPARTMENT_FLOOR_MAP:
        raise ValueError(f"Invalid department: {department}")
    if shift_state not in VALID_SHIFT_STATES:
        raise ValueError(f"Invalid shift_state: {shift_state}")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agents
               (name, display_name, department, floor, model, shift_state,
                system_prompt, temperature, max_tokens, capabilities,
                is_department_ai, tier, worker_type, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
               RETURNING id""",
            (
                name,
                display_name,
                department,
                floor,
                model,
                shift_state,
                kwargs.get("system_prompt", ""),
                kwargs.get("temperature", 0.7),
                kwargs.get("max_tokens", 2048),
                json.dumps(kwargs.get("capabilities", {})),
                kwargs.get("is_department_ai", False),
                kwargs.get("tier", 3),
                kwargs.get("worker_type", "internal"),
            ),
        )
        agent_id = cur.fetchone()["id"]

        # Create initial emotional state
        cur.execute(
            """INSERT INTO agent_emotional_state (agent_id, stress_level, energy_level, mood, mood_intensity)
               VALUES (%s, 0.1, 0.9, 'neutral', 0.5)""",
            (agent_id,),
        )

    logger.info("Created agent #%d: %s (%s) in %s", agent_id, name, display_name, department)
    return agent_id


def update_agent(agent_id, **fields):
    """Update agent fields. Auto-derives floor if department changes.

    Returns True on success, False if agent not found.
    """
    if not fields:
        return True

    # Auto-derive floor when department changes
    if "department" in fields:
        dept = fields["department"]
        if dept not in DEPARTMENT_FLOOR_MAP:
            raise ValueError(f"Invalid department: {dept}")
        fields["floor"] = DEPARTMENT_FLOOR_MAP[dept]

    if "shift_state" in fields and fields["shift_state"] not in VALID_SHIFT_STATES:
        raise ValueError(f"Invalid shift_state: {fields['shift_state']}")

    # Build dynamic UPDATE
    set_clauses = []
    params = []
    for key, val in fields.items():
        if key in ("capabilities", "metadata") and isinstance(val, dict):
            set_clauses.append(f"{key} = %s::jsonb")
            params.append(json.dumps(val))
        else:
            set_clauses.append(f"{key} = %s")
            params.append(val)

    set_clauses.append("updated_at = NOW()")
    params.append(agent_id)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE agents SET {', '.join(set_clauses)} WHERE id = %s RETURNING id",
            params,
        )
        updated = cur.fetchone() is not None

    if updated:
        logger.info("Updated agent #%d: %s", agent_id, list(fields.keys()))
    return updated


def delete_agent(agent_id, hard=False):
    """Delete agent. Soft-delete by default (status=inactive, shift_state=off_duty)."""
    if hard:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM agents WHERE id = %s", (agent_id,))
        logger.warning("Hard-deleted agent #%d", agent_id)
    else:
        update_agent(agent_id, status="inactive", shift_state="off_duty")
        logger.info("Soft-deleted agent #%d", agent_id)


# ---------------------------------------------------------------------------
# Shift Lifecycle
# ---------------------------------------------------------------------------


def activate(agent_id):
    """Set agent to active duty."""
    return update_agent(agent_id, shift_state="active")


def barracks(agent_id):
    """Return agent to barracks (reserve)."""
    return update_agent(agent_id, shift_state="barracked")


def wind_down(agent_id):
    """Begin wind-down cycle."""
    return update_agent(agent_id, shift_state="winding_down")


def cooldown(agent_id):
    """Put agent in cooldown."""
    return update_agent(agent_id, shift_state="cooldown")


def deploy_to_node(agent_id, node_id):
    """Deploy agent to a remote node."""
    with get_db_cursor(commit=True) as (conn, cur):
        # Get agent info
        cur.execute("SELECT name, department, model FROM agents WHERE id = %s", (agent_id,))
        agent = cur.fetchone()
        if not agent:
            return False

        # Update shift state
        cur.execute(
            "UPDATE agents SET shift_state = 'deployed' WHERE id = %s",
            (agent_id,),
        )

        # Create or reactivate node_agent
        cur.execute(
            """INSERT INTO node_agents (hub_agent_id, node_id, name, department, model, status)
               VALUES (%s, %s, %s, %s, %s, 'active')
               ON CONFLICT (hub_agent_id, node_id)
               DO UPDATE SET status = 'active', department = EXCLUDED.department""",
            (agent_id, node_id, agent["name"], agent["department"], agent["model"]),
        )

    logger.info("Deployed agent #%d to node #%d", agent_id, node_id)
    return True


def return_from_node(agent_id):
    """Return agent from node to barracks."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE agents SET shift_state = 'barracked' WHERE id = %s AND shift_state = 'deployed'",
            (agent_id,),
        )
        cur.execute(
            "UPDATE node_agents SET status = 'inactive' WHERE hub_agent_id = %s AND status = 'active'",
            (agent_id,),
        )
    logger.info("Returned agent #%d from node to barracks", agent_id)
    return True


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def get_skills(agent_id):
    """Get agent's skills with levels. Returns list of dicts."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT skill_name, category, level FROM agent_skills WHERE agent_id = %s ORDER BY level DESC",
            (agent_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def add_skill(agent_id, skill_name, level=1, category="general"):
    """Add or update a skill for an agent."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO agent_skills (agent_id, skill_name, level, category)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (agent_id, skill_name) DO UPDATE SET level = EXCLUDED.level""",
            (agent_id, skill_name, level, category),
        )
    logger.info("Agent #%d skill %s set to level %d", agent_id, skill_name, level)


def update_skill_from_benchmark(agent_id, skill_name, score):
    """Update skill level from benchmark score (0.0-1.0). Auto-levels 1-5."""
    level = max(1, min(5, int(score * 5) + 1))
    add_skill(agent_id, skill_name, level=level, category="benchmarked")


def match_capability(capability):
    """Find agents who have a matching skill, ranked by level. Returns list of (agent_id, level)."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT a.id, a.name, a.display_name, a.department, a.model,
                      a.shift_state, s.level
               FROM agent_skills s
               JOIN agents a ON a.id = s.agent_id
               WHERE s.skill_name = %s AND a.status = 'active'
               ORDER BY s.level DESC, a.is_department_ai DESC""",
            (capability,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Welfare
# ---------------------------------------------------------------------------


def get_welfare(agent_id):
    """Get agent's current emotional state. Returns dict or None."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT stress_level, energy_level, mood, mood_intensity
               FROM agent_emotional_state WHERE agent_id = %s
               ORDER BY id DESC LIMIT 1""",
            (agent_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_welfare(agent_id, stress=None, energy=None, mood=None, mood_intensity=None):
    """Update agent welfare metrics."""
    updates = {}
    if stress is not None:
        updates["stress_level"] = max(0.0, min(1.0, stress))
    if energy is not None:
        updates["energy_level"] = max(0.0, min(1.0, energy))
    if mood is not None:
        updates["mood"] = mood
    if mood_intensity is not None:
        updates["mood_intensity"] = max(0.0, min(1.0, mood_intensity))

    if not updates:
        return

    set_clauses = [f"{k} = %s" for k in updates]
    params = list(updates.values()) + [agent_id]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE agent_emotional_state SET {', '.join(set_clauses)} WHERE agent_id = %s",
            params,
        )


def check_welfare_threshold(agent_id):
    """Check if agent is healthy enough to work. Returns (ok: bool, reason: str)."""
    welfare = get_welfare(agent_id)
    if not welfare:
        return True, "no welfare data"

    stress = float(welfare.get("stress_level", 0))
    energy = float(welfare.get("energy_level", 1))

    if stress >= 0.8:
        return False, f"stress too high ({stress:.2f})"
    if energy <= 0.2:
        return False, f"energy too low ({energy:.2f})"
    return True, "healthy"


def recover_idle(agent_id, energy_boost=0.2, stress_reduction=0.15):
    """Recover an idle agent's welfare."""
    welfare = get_welfare(agent_id)
    if not welfare:
        return

    new_energy = min(1.0, float(welfare.get("energy_level", 0.5)) + energy_boost)
    new_stress = max(0.0, float(welfare.get("stress_level", 0.5)) - stress_reduction)
    update_welfare(agent_id, stress=new_stress, energy=new_energy)


# ---------------------------------------------------------------------------
# Org Chart & Department Summary
# ---------------------------------------------------------------------------


def get_org_chart():
    """Get full org chart: floors -> departments -> agents."""
    agents = list_agents(limit=500)
    floors = {}

    for agent in agents:
        floor = agent["floor"]
        dept = agent["department"]
        if floor not in floors:
            floors[floor] = {}
        if dept not in floors[floor]:
            floors[floor][dept] = {"director": None, "staff": []}

        if agent.get("is_department_ai"):
            floors[floor][dept]["director"] = agent
        else:
            floors[floor][dept]["staff"].append(agent)

    return floors


def get_department_summary():
    """Get per-department agent counts and health."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT department, floor,
                      COUNT(*) as total,
                      COUNT(*) FILTER (WHERE shift_state = 'active') as active,
                      COUNT(*) FILTER (WHERE shift_state = 'deployed') as deployed,
                      COUNT(*) FILTER (WHERE shift_state = 'barracked') as barracked,
                      COUNT(*) FILTER (WHERE is_department_ai = true) as directors
               FROM agents
               WHERE status = 'active'
               GROUP BY department, floor
               ORDER BY floor, department"""
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def get_performance(agent_id, period_days=7):
    """Get agent performance metrics for a period."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT COUNT(*) FILTER (WHERE status = 'completed') as jobs_completed,
                      COUNT(*) FILTER (WHERE status = 'failed') as jobs_failed,
                      AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) as avg_seconds
               FROM bridge_jobs
               WHERE agent_name = (SELECT name FROM agents WHERE id = %s)
                 AND created_at > NOW() - INTERVAL '%s days'""",
            (agent_id, period_days),
        )
        row = cur.fetchone()
        if not row:
            return {"jobs_completed": 0, "jobs_failed": 0, "avg_response_ms": 0, "success_rate": 0}

        completed = row["jobs_completed"] or 0
        failed = row["jobs_failed"] or 0
        total = completed + failed
        return {
            "jobs_completed": completed,
            "jobs_failed": failed,
            "avg_response_ms": int((row["avg_seconds"] or 0) * 1000),
            "success_rate": round(completed / total * 100, 1) if total > 0 else 100,
        }


# ---------------------------------------------------------------------------
# Hardware-Aware Recommendations
# ---------------------------------------------------------------------------


def get_agents_for_hardware(gpu_vram_gb, ram_gb):
    """Return agents whose models fit the given hardware, ranked by benchmark score."""
    # Rough model size estimates (can be refined with actual data)
    agents = list_agents(shift_state="active")
    compatible = []

    for agent in agents:
        model = agent.get("model", "")
        # Estimate VRAM need from model name
        if "1.5b" in model or "3b" in model:
            vram_need = 2.0
        elif "7b" in model:
            vram_need = 5.0
        elif "12b" in model or "14b" in model:
            vram_need = 10.0
        elif "16b" in model:
            vram_need = 12.0
        elif ":cloud" in model:
            vram_need = 0  # cloud models don't need local VRAM
        else:
            vram_need = 5.0  # default estimate

        if vram_need <= gpu_vram_gb or vram_need <= ram_gb * 0.8:
            agent["estimated_vram_gb"] = vram_need
            compatible.append(agent)

    return sorted(compatible, key=lambda a: a.get("is_department_ai", False), reverse=True)


def recommend_node_deployment(node_id):
    """Recommend agents for a specific node based on its hardware."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT gpu_vram_gb, ram_gb, gpu_model FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        node = cur.fetchone()

    if not node:
        return []

    return get_agents_for_hardware(
        gpu_vram_gb=float(node.get("gpu_vram_gb") or 0),
        ram_gb=float(node.get("ram_gb") or 0),
    )
