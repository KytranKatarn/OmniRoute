"""A.R.C.H.I.E. Voice Service — Personality Engine.

Transforms raw alert/notification data into natural-language messages
in A.R.C.H.I.E.'s voice by routing through her LLM (dolphin3-8k).

DESIGN: Zero Flask dependencies — pure Python with direct DB + Ollama access.
This service runs both inside archie_platform and independently in archie_comms.

Usage:
    from services.archie_voice_service import format_message

    text = format_message(
        category="security",
        title="SSH Brute Force",
        raw_message="47 attempts from 3 IPs, blocked by fail2ban",
        source_agent="V.I.G.I.L.",
        source_department="Security & Compliance",
    )
"""

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

# Cache the system prompt (refreshed every 5 minutes)
_prompt_cache = {"text": None, "loaded_at": 0.0}
_PROMPT_TTL = 300  # 5 minutes

# Category → severity mapping for the LLM prompt
_CATEGORY_SEVERITY = {
    "security": "CRITICAL",
    "system": "HIGH",
    "forge": "MEDIUM",
    "agent": "MEDIUM",
    "sync": "LOW",
    "info": "LOW",
}


def _get_system_prompt():
    """Load voice system prompt from archie_personality table, with TTL cache."""
    now = time.time()
    if _prompt_cache["text"] and (now - _prompt_cache["loaded_at"]) < _PROMPT_TTL:
        return _prompt_cache["text"]

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT trait_value FROM archie_personality WHERE trait_name = 'voice_system_prompt'")
            row = cur.fetchone()
            if row:
                _prompt_cache["text"] = row["trait_value"] if isinstance(row, dict) else row[0]
                _prompt_cache["loaded_at"] = now
                return _prompt_cache["text"]
    except Exception as e:
        logger.warning("archie_voice: failed to load system prompt: %s", e)

    return None


def _build_user_prompt(category, title, raw_message, source_agent, source_department):
    """Build the user prompt containing the raw data for A.R.C.H.I.E. to rewrite."""
    severity = _CATEGORY_SEVERITY.get(category, "MEDIUM")
    data = {
        "category": category,
        "title": title,
        "raw_message": raw_message,
        "severity": severity,
    }
    if source_agent:
        data["source_agent"] = source_agent
    if source_department:
        data["source_department"] = source_department
    return json.dumps(data)


def format_message(
    category,
    title,
    raw_message,
    source_agent=None,
    source_department=None,
    context=None,
):
    """Format a message in A.R.C.H.I.E.'s voice using her LLM.

    Args:
        category: One of security/system/forge/agent/sync/info.
        title: Short title for the alert.
        raw_message: The raw notification text to rewrite.
        source_agent: Who originated this (e.g., 'V.I.G.I.L.').
        source_department: Originating department.
        context: Optional dict with project_id, task_id, needs_response, etc.

    Returns:
        str: The message in A.R.C.H.I.E.'s voice, or template fallback if LLM fails.
    """
    system_prompt = _get_system_prompt()
    if not system_prompt:
        logger.debug("archie_voice: no system prompt, using template fallback")
        return _template_fallback(category, title, raw_message, source_agent)

    user_prompt = _build_user_prompt(category, title, raw_message, source_agent, source_department)

    try:
        voice_text = _call_ollama(system_prompt, user_prompt)
        if voice_text:
            # Append platform link for non-critical alerts that might need follow-up
            if context and context.get("needs_response") and category not in ("security",):
                voice_text += "\n\nMore details at archie.kytranempowerment.com"
            return voice_text
        else:
            logger.warning("archie_voice: empty LLM response, using fallback")
            return _template_fallback(category, title, raw_message, source_agent)

    except Exception as e:
        logger.warning("archie_voice: LLM call failed (%s), using fallback", e)
        return _template_fallback(category, title, raw_message, source_agent)


def _call_ollama(system_prompt, user_prompt):
    """Call Ollama directly via HTTP — no Flask, no dispatcher dependency.

    This is intentionally Flask-free so it works both inside archie_platform
    and independently in the archie_comms container.
    """
    import urllib.request

    ollama_host = os.getenv("OLLAMA_HOST", "http://192.168.1.200:11434")
    # Ensure scheme prefix — container env often has bare host:port
    if ollama_host and not ollama_host.startswith("http"):
        ollama_host = f"http://{ollama_host}"
    model = os.getenv("ARCHIE_VOICE_MODEL", "dolphin3-8k:latest")

    payload = json.dumps(
        {
            "model": model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "options": {"num_predict": 150, "temperature": 0.7, "num_gpu": 0},
            "keep_alive": "5m",
        }
    ).encode()

    req = urllib.request.Request(
        f"{ollama_host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read())
        return result.get("response", "").strip() or None


def _template_fallback(category, title, raw_message, source_agent=None):
    """Original template format — used when LLM is unavailable.
    Inline icon map to avoid importing telegram_service (keeps Flask-free).
    """
    icons = {
        "security": "🔴",
        "system": "🟡",
        "forge": "🔧",
        "agent": "🤖",
        "sync": "📡",
        "info": "📋",
    }
    icon = icons.get(category, "📋")

    if source_agent:
        return f"{icon} *{title}*\n\n{source_agent} reports:\n{raw_message}\n\n_— A.R.C.H.I.E._"
    else:
        return f"{icon} *{title}*\n\n{raw_message}\n\n_— A.R.C.H.I.E._"
