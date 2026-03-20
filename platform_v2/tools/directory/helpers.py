"""Directory module helpers — name derivation, email generation, status mapping."""

import time


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
    """Map Starbase roster state to directory status."""
    if not crew_member:
        return {"status": "Off Duty", "is_online": False, "chat_available": False}
    shift_state = crew_member.get("shift_state", "")
    model_loaded = crew_member.get("model_loaded", False)
    if shift_state == "active" and model_loaded:
        return {"status": "Online", "is_online": True, "chat_available": True}
    return {"status": "Off Duty", "is_online": False, "chat_available": False}


class RateLimiter:
    """Simple in-memory rate limiter for chat endpoints."""

    def __init__(self, per_user_limit=10, global_limit=50, window=60):
        self.per_user_limit = per_user_limit
        self.global_limit = global_limit
        self.window = window
        self.user_counts = {}
        self.global_count = 0
        self.global_window_start = time.time()

    def check(self, user_id):
        """Check if request is allowed. Returns (allowed, error_message)."""
        now = time.time()
        if now - self.global_window_start > self.window:
            self.global_count = 0
            self.global_window_start = now
        user_data = self.user_counts.get(user_id, (0, now))
        if now - user_data[1] > self.window:
            user_data = (0, now)
        if self.global_count >= self.global_limit:
            return False, "Chat system is busy. Please wait a moment."
        if user_data[0] >= self.per_user_limit:
            return False, "Please wait before sending another message."
        self.global_count += 1
        self.user_counts[user_id] = (user_data[0] + 1, user_data[1])
        return True, None


chat_rate_limiter = RateLimiter()
