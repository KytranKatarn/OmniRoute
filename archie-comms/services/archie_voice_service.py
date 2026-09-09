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
    """Load voice system prompt from archie_personality table, enriched with
    relationship context and personality traits. Cached with TTL."""
    now = time.time()
    if _prompt_cache["text"] and (now - _prompt_cache["loaded_at"]) < _PROMPT_TTL:
        return _prompt_cache["text"]

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            # Base voice prompt
            cur.execute("SELECT trait_value FROM archie_personality WHERE trait_name = 'voice_system_prompt'")
            row = cur.fetchone()
            if not row:
                return None
            base_prompt = row["trait_value"] if isinstance(row, dict) else row[0]

            # Enrich with relationship context (Kytran's preferred name, trust level)
            enrichment = ""
            cur.execute(
                "SELECT preferred_name, trust_level, notes FROM archie_relationships WHERE user_id = 2 LIMIT 1"
            )
            rel = cur.fetchone()
            if rel:
                name = rel["preferred_name"] if isinstance(rel, dict) else rel[0]
                notes = rel["notes"] if isinstance(rel, dict) else rel[2]
                if name:
                    enrichment += f"\nAddress the user as '{name}' when appropriate (not every message)."
                if notes:
                    enrichment += f"\nRelationship context: {notes}"

            # Add personality traits for richer voice
            cur.execute(
                "SELECT trait_name, trait_value FROM archie_personality "
                "WHERE trait_name IN ('humor_level', 'greeting_style', 'communication_style', 'formality')"
            )
            traits = cur.fetchall()
            if traits:
                trait_lines = []
                for t in traits:
                    tn = t["trait_name"] if isinstance(t, dict) else t[0]
                    tv = t["trait_value"] if isinstance(t, dict) else t[1]
                    trait_lines.append(f"- {tn}: {tv}")
                if trait_lines:
                    enrichment += "\n\nPersonality traits:\n" + "\n".join(trait_lines)

            full_prompt = base_prompt + enrichment
            _prompt_cache["text"] = full_prompt
            _prompt_cache["loaded_at"] = now
            return full_prompt

    except Exception as e:
        logger.warning("archie_voice: failed to load system prompt: %s", e)

    return None


def get_script_response(user_message):
    """Check if user message matches any archie_scripts trigger pattern.
    Returns the response template if matched, None otherwise.
    Used by chat service for quick scripted responses (greetings, farewells).
    """
    try:
        import re
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT trigger_pattern, response_template FROM archie_scripts "
                "WHERE active = TRUE ORDER BY priority DESC"
            )
            scripts = cur.fetchall()
            for script in scripts:
                pattern = script["trigger_pattern"] if isinstance(script, dict) else script[0]
                response = script["response_template"] if isinstance(script, dict) else script[1]
                if pattern and re.search(pattern, user_message.strip(), re.IGNORECASE):
                    return response
    except Exception as e:
        logger.warning("archie_voice: script lookup failed: %s", e)
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
        voice_text = _dhq_notify_voice(system_prompt, user_prompt)
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


def _dhq_notify_voice(system_prompt, user_prompt):
    """Rewrite a notification in A.R.C.H.I.E.'s voice THROUGH the dispatcher
    (#6654 - no direct inference; everything goes through DHQ, ADR-013).

    Flask-free (works standalone in the archie_comms container): a plain HTTP
    POST to the platform's internal DHQ chat endpoint with capability
    'notification' (kept off the cloud allowlist - stays local/sovereign).
    Returns the voiced text, or None on any failure so format_message falls
    back to its static template (never a fabricated reply).
    """
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        return None
    platform_url = os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")
    try:
        import requests

        resp = requests.post(
            f"{platform_url}/api/internal/dhq/chat",
            json={
                "prompt": user_prompt,
                "system_prompt": system_prompt,
                "capability": "notification",
            },
            headers={"Authorization": f"Bearer {key}"},
            timeout=float(os.getenv("DHQ_NOTIFY_TIMEOUT", "30")),
        )
        if resp.status_code != 200:
            logger.warning("archie_voice: DHQ notify returned %s - template fallback", resp.status_code)
            return None
        data = resp.json()
        if data.get("success") and (data.get("response") or "").strip():
            return data["response"].strip()
        return None
    except Exception as exc:
        logger.warning("archie_voice: DHQ notify unreachable (%s) - template fallback", exc)
        return None


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
