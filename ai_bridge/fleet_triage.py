"""Fleet triage — lightweight agent capability check.

Used by both Bridge (Starbase) and remote nodes to determine
if a task can be handled locally before escalating to Bridge dispatch.

This module must stay dependency-light (no Flask, no DB imports).
Callers provide agent state as dicts.
"""

# Import the canonical capability->department map from bridge_dispatcher
try:
    from tools.department_hq.services.department_dispatcher import CAPABILITY_DEPARTMENT_MAP
except ImportError:
    # Fallback for nodes that don't have bridge_dispatcher
    CAPABILITY_DEPARTMENT_MAP = {
        "conversation": "Executive Office",
        "code": "Engineering & Technology",
        "code_review": "Engineering & Technology",
        "operations": "Operations & Infrastructure",
        "classify": "Analytics & Intelligence",
        "content_writing": "Creative & Design",
        "knowledge_analysis": "Research & Development",
    }


def capability_to_department(capability):
    """Map a capability string to its home department."""
    return CAPABILITY_DEPARTMENT_MAP.get(capability)


def can_agent_handle(agent):
    """Check if an agent passes triage hard-block conditions.

    Mirrors Bridge dispatcher hard-blocks from _score_agent().
    Agent dict must have: status, shift_state, stress, energy,
    task_count, task_limit.
    """
    if agent.get("status") != "active":
        return False

    shift = agent.get("shift_state", "active")
    if shift in ("cooldown", "off_duty"):
        return False

    stress = agent.get("stress", 0.0)
    energy = agent.get("energy", 1.0)

    # Critical welfare block — mirrors dispatcher exactly
    if stress >= 0.9 and energy <= 0.15:
        return False

    task_count = agent.get("task_count", 0)
    task_limit = agent.get("task_limit", 10)
    if task_count >= task_limit:
        return False

    return True


def triage_local(capability, local_agents):
    """Find the best local agent for a capability.

    Args:
        capability: The task capability (e.g., 'code_review')
        local_agents: List of agent dicts with keys:
            name, department, status, shift_state, stress, energy,
            task_count, task_limit, model_loaded (bool)

    Returns:
        Best agent dict, or None if escalation needed.
    """
    department = capability_to_department(capability)
    if not department:
        return None  # Unknown capability — escalate

    candidates = []
    for agent in local_agents:
        # Must serve the right department
        if agent.get("department") != department:
            continue

        # Must pass hard-block checks
        if not can_agent_handle(agent):
            continue

        # Must have model loaded locally
        if not agent.get("model_loaded", False):
            continue

        candidates.append(agent)

    if not candidates:
        return None  # Escalate to Bridge

    # Pick agent with lowest current task count
    candidates.sort(key=lambda a: a.get("task_count", 0))
    return candidates[0]
