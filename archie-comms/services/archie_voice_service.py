"""A.R.C.H.I.E. unified voice formatting service.

Pure functions — no Flask, no DB, no external deps.
Used by telegram_service and any future notification channel to produce
consistent A.R.C.H.I.E. executive-voice messages.

Usage:
    from services.archie_voice_service import format_message, _CATEGORY_SEVERITY

    text = format_message("security", "Intrusion detected", "IP 1.2.3.4 blocked",
                          source_agent="V.I.G.I.L.")
"""

# ---------------------------------------------------------------------------
# Category metadata (mirrors telegram_service.CATEGORIES)
# ---------------------------------------------------------------------------
_CATEGORIES: dict[str, dict] = {
    "security": {"icon": "🔴", "priority": "critical", "label": "SECURITY"},
    "system":   {"icon": "🟡", "priority": "high",     "label": "SYSTEM"},
    "forge":    {"icon": "🔧", "priority": "medium",   "label": "F.O.R.G.E."},
    "agent":    {"icon": "🤖", "priority": "medium",   "label": "AGENT"},
    "sync":     {"icon": "📡", "priority": "low",      "label": "SYNC"},
    "info":     {"icon": "📋", "priority": "low",      "label": "INFO"},
}

# Severity ordering for callers that need to compare priorities
_CATEGORY_SEVERITY: dict[str, int] = {
    "critical": 4,
    "high":     3,
    "medium":   2,
    "low":      1,
}


def _template_fallback(category: str) -> dict:
    """Return the category dict, falling back to 'info' if unknown."""
    return _CATEGORIES.get(category, _CATEGORIES["info"])


def _build_user_prompt(title: str, message: str, source_agent: str | None) -> str:
    """Build the human-readable body without icon/signature.

    Extracted so callers can compose prompts for LLM-based voice enhancement.
    """
    if source_agent:
        return f"{source_agent} reports:\n{message}"
    return message


def format_message(
    category: str,
    title: str,
    message: str,
    source_agent: str | None = None,
) -> str:
    """Format a message in A.R.C.H.I.E.'s executive voice.

    When source_agent is provided, frames as A.R.C.H.I.E. relaying from that agent.
    When not provided, A.R.C.H.I.E. speaks directly.

    Args:
        category:     One of: security, system, forge, agent, sync, info.
        title:        Short subject line (shown in bold).
        message:      Notification body text.
        source_agent: Originating agent acronym (e.g. "V.I.G.I.L.").

    Returns:
        Telegram Markdown-compatible string.
    """
    cat = _template_fallback(category)
    icon = cat["icon"]
    body = _build_user_prompt(title, message, source_agent)

    return f"{icon} *{title}*\n\n{body}\n\n_— A.R.C.H.I.E._"
