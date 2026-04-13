"""Directory module helpers — name derivation, email generation, status mapping."""


def derive_full_name(agent):
    """Get display name with fallback chain."""
    if agent.get("first_name") and agent.get("last_name"):
        return f"{agent['first_name']} {agent['last_name']}"
    return agent.get("display_name") or agent.get("name") or "Unknown"


def derive_email(agent):
    """Get or generate email address."""
    if agent.get("email"):
        return agent["email"]
    name = agent.get("display_name") or agent.get("name") or "agent"
    if " " in name:
        return name.lower().replace(" ", ".") + "@kytranempowerment.com"
    return name.lower() + "@kytranempowerment.com"


def map_agent_status(crew_member):
    """Map Bridge crew manifest state to directory status.

    Uses llm_status (loaded/swap/cloud/barracked) and shift_state from
    get_crew_manifest() to determine online/chat availability.
    """
    if not crew_member:
        return {"status": "Off Duty", "is_online": False, "chat_available": False}
    shift_state = crew_member.get("shift_state", "off_duty")
    llm_status = crew_member.get("llm_status", "barracked")
    activity = crew_member.get("status", "idle")
    llm_ready = llm_status in ("loaded", "swap", "cloud")
    on_shift = shift_state in ("active", "deployed")
    is_online = on_shift and llm_ready
    if activity == "resting":
        return {"status": "Resting", "is_online": False, "chat_available": False}
    if is_online and activity == "working":
        return {"status": "Busy", "is_online": True, "chat_available": True}
    if is_online:
        return {"status": "Online", "is_online": True, "chat_available": True}
    if on_shift:
        return {"status": "Standby", "is_online": True, "chat_available": False}
    return {"status": "Off Duty", "is_online": False, "chat_available": False}
