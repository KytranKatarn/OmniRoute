"""Fleet triage — lightweight agent capability check.

Used by both Bridge (Starbase) and remote nodes to determine
if a task can be handled locally before escalating to Bridge dispatch.

This module must stay dependency-light (no Flask, no DB imports).
Callers provide agent state as dicts.
"""

# Mirror of CAPABILITY_STATION_MAP from bridge_dispatcher.py
# Synced to nodes via capability_map config sync
CAPABILITY_STATION_MAP = {
    "COMMAND": [
        "conversation",
        "dispatch",
        "governance",
        "orchestration",
    ],
    "ANALYTICS": [
        "classify",
        "sentiment",
        "tagging",
        "anomaly_detection",
        "pattern_recognition",
        "embedding",
        "vision",
        "translate",
        "detect_language",
    ],
    "ENGINEERING": [
        "code",
        "code_analysis",
        "code_review",
        "testing",
        "debugging",
        "schema_design",
        "api_design",
        "deployment",
    ],
    "OPERATIONS": [
        "operations",
        "system_monitoring",
        "backup",
        "health_check",
        "security_analysis",
        "telegram",
        "email",
        "notification",
        "webhook",
        "ha_integration",
        "automation",
    ],
    "CREATIVE": [
        "content_writing",
        "email_composition",
        "chat_styling",
        "voice",
        "ux_writing",
        "social_media",
        "image_generation",
        "video_generation",
    ],
    "RESEARCH": [
        "knowledge_analysis",
        "summarize",
        "document_analysis",
        "fact_checking",
        "semantic_search",
        "context_retrieval",
    ],
}

# Reverse map: capability -> station
_CAPABILITY_TO_STATION = {}
for _station, _caps in CAPABILITY_STATION_MAP.items():
    for _cap in _caps:
        _CAPABILITY_TO_STATION[_cap] = _station


def capability_to_station(capability):
    """Map a capability string to its home station code."""
    return _CAPABILITY_TO_STATION.get(capability)


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
            name, station_codes, status, shift_state, stress, energy,
            task_count, task_limit, model_loaded (bool)

    Returns:
        Best agent dict, or None if escalation needed.
    """
    station = capability_to_station(capability)
    if not station:
        return None  # Unknown capability — escalate

    candidates = []
    for agent in local_agents:
        # Must serve the right station
        if station not in agent.get("station_codes", []):
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
