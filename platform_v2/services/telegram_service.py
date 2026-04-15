"""Centralized Telegram notification service.

All Telegram alerts should route through this service for:
- Consistent formatting with category icons + labels
- Category-based priority and throttling
- Audit logging via Python logger
- Simple opt-in/opt-out per category (future)

Usage:
    from services.telegram_service import send, send_forge, send_agent

    send("forge", "PR Merged", "#42 feat: add widget")
    send_forge("Scan complete", "12 findings, 3 critical")
    send_agent("Tier 2 Escalation", "Agent NEXUS requests cloud approval")
    send("security", "Intrusion detected", "IP 1.2.3.4 failed 20 times", force=True)

Categories:
    security — critical alerts (failed logins, intrusion, compliance violations)
    system   — infrastructure alerts (node offline, disk full, container restart)
    forge    — F.O.R.G.E. pipeline (PR, CodeRabbit, scan, self-heal)
    agent    — agent lifecycle (Tier 2 escalation, training, welfare)
    sync     — background sync jobs (GitHub, tender, skill discovery)
    info     — briefings, reminders, scheduled reports

# =============================================================================
# MIGRATION GUIDE — files to move to this service (incremental, not urgent):
# =============================================================================
#
# Priority 1 (direct api.telegram.org callers — replace fully):
#   platform_v2/tools/repair_bay/services/forge_self_heal.py
#       def _send_telegram(text) → send("forge", title, text)
#   platform_v2/tools/repair_bay/services/forge_pipeline.py
#       inline requests.post(...sendMessage) → send("forge", title, body)
#   platform_v2/tools/repair_bay/github_routes.py
#       inline requests.post(...sendMessage) → send("forge", title, body)
#
# Priority 2 (Telegram-aware but routing through other layers):
#   platform_v2/tools/security_network/security_alerts.py
#       send_telegram flag logic → send("security", ...) or send("system", ...)
#   platform_v2/tools/dev_hq/routes.py
#       tg_token references → use init() + send()
#   platform_v2/tools/consciousness/github_routes.py
#       gateway._application.bot.send_message → send("sync", ...)
#   platform_v2/tools/starbase/node_routes.py
#       any telegram calls → send("system", ...)
#   platform_v2/tools/autonomy/telegram_routes.py
#       already manages Telegram gateway — keep, but use send() for outbound alerts
#   platform_v2/tools/autonomy/ops_routes.py
#       telegram_token status check — no change needed (config check only)
#   platform_v2/tools/user_profile/routes.py
#       any telegram calls → use send()
#   platform_v2/tools/pool_management/routes.py
#       any telegram calls → send("system", ...)
#   platform_v2/app.py
#       TelegramGateway init stays — call init() after gateway is created
#
# =============================================================================
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------
CATEGORIES = {
    "security": {"icon": "🔴", "priority": "critical", "label": "SECURITY"},
    "system": {"icon": "🟡", "priority": "high", "label": "SYSTEM"},
    "forge": {"icon": "🔧", "priority": "medium", "label": "F.O.R.G.E."},
    "agent": {"icon": "🤖", "priority": "medium", "label": "AGENT"},
    "sync": {"icon": "📡", "priority": "low", "label": "SYNC"},
    "info": {"icon": "📋", "priority": "low", "label": "INFO"},
}

# Throttle: minimum seconds between sends per category
# 0 = no throttle (critical), positive = minimum gap in seconds
THROTTLE = {
    "critical": 0,  # always send
    "high": 60,  # max 1 per minute
    "medium": 300,  # max 1 per 5 minutes
    "low": 86400,  # max 1 per day (daily digest pattern)
}

# ---------------------------------------------------------------------------
# Module state — populated by init() or lazy from env vars
# ---------------------------------------------------------------------------
_bot_token: str = ""
_default_chat_id: str = ""
_last_sent: dict = {}  # category -> float timestamp


def init(bot_token: str = None, chat_id: str = None) -> None:
    """Initialize with bot token and default chat ID.

    Call this once at app startup (e.g. after TelegramGateway is created in app.py).
    Falls back to env vars if not provided.

    Args:
        bot_token: Telegram bot token. Defaults to TELEGRAM_BOT_TOKEN env var.
        chat_id: Default chat/channel ID. Defaults to TELEGRAM_CHAT_ID env var.
    """
    global _bot_token, _default_chat_id
    _bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
    _default_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
    if _bot_token:
        logger.info("telegram_service: initialized (chat_id=%s)", _default_chat_id or "unset")
    else:
        logger.debug("telegram_service: no bot token — notifications disabled")


def _get_token() -> str:
    """Lazy-load token from env if init() was never called."""
    global _bot_token
    if not _bot_token:
        _bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    return _bot_token


def _get_chat_id() -> str:
    """Lazy-load chat ID from env if init() was never called."""
    global _default_chat_id
    if not _default_chat_id:
        _default_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    return _default_chat_id


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------
def send(
    category: str,
    title: str,
    message: str,
    source_agent: str = None,
    source_department: str = None,
    source_module: str = None,
    chat_id: str = None,
    force: bool = False,
) -> dict:
    """Send a categorized Telegram notification as A.R.C.H.I.E.

    A.R.C.H.I.E. is the sole voice to Kytran. When source_agent is provided,
    the message is framed as A.R.C.H.I.E. relaying intelligence from that
    agent/department (e.g., "V.I.G.I.L. flagged a compliance issue...").

    Args:
        category:          One of CATEGORIES keys (security/system/forge/agent/sync/info).
        title:             Short title for the message.
        message:           Notification body text.
        source_agent:      Who originated this (e.g., 'V.I.G.I.L.', 'K.I.N.', 'P.R.O.B.E.').
        source_department: Originating department (e.g., 'Security & Compliance').
        source_module:     Code module that triggered the send (for migration tracking).
        chat_id:           Override the default chat ID.
        force:             If True, bypass throttle.

    Returns:
        dict: {sent: bool, reason: str (if not sent), log_id: int (if logged)}
    """
    token = _get_token()
    if not token:
        _log_message(
            category,
            title,
            message,
            source_agent,
            source_department,
            source_module,
            "failed",
            "no bot token configured",
        )
        return {"sent": False, "reason": "no bot token configured"}

    cat = CATEGORIES.get(category, CATEGORIES["info"])
    priority = cat["priority"]

    # Throttle check (skip for force=True or critical)
    if not force and priority != "critical":
        throttle_secs = THROTTLE.get(priority, 300)
        if throttle_secs > 0:
            last = _last_sent.get(category, 0.0)
            elapsed = time.time() - last
            if elapsed < throttle_secs:
                remaining = int(throttle_secs - elapsed)
                reason = f"throttled ({priority}, {remaining}s remaining)"
                _log_message(
                    category, title, message, source_agent, source_department, source_module, "throttled", reason
                )
                logger.debug("telegram_service: throttled [%s] '%s' (%ds)", category, title, remaining)
                return {"sent": False, "reason": reason}

    # Format as A.R.C.H.I.E.'s voice — relaying from source agent
    text = _format_archie_voice(cat, title, message, source_agent)

    target = chat_id or _get_chat_id()
    if not target:
        _log_message(
            category, title, message, source_agent, source_department, source_module, "failed", "no chat_id configured"
        )
        return {"sent": False, "reason": "no chat_id configured"}

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": target,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        _last_sent[category] = time.time()

        if resp.ok:
            tg_msg_id = resp.json().get("result", {}).get("message_id")
            log_id = _log_message(
                category,
                title,
                message,
                source_agent,
                source_department,
                source_module,
                "sent",
                None,
                target,
                tg_msg_id,
                text,
            )
            logger.info("telegram_service: sent [%s] '%s' from %s", category, title, source_agent or "system")
            return {"sent": True, "log_id": log_id}
        else:
            reason = f"HTTP {resp.status_code}: {resp.text[:100]}"
            _log_message(
                category, title, message, source_agent, source_department, source_module, "failed", reason, target
            )
            logger.warning("telegram_service: send failed [%s] %s", category, reason)
            return {"sent": False, "reason": reason}

    except requests.Timeout:
        _log_message(
            category,
            title,
            message,
            source_agent,
            source_department,
            source_module,
            "failed",
            "request timeout",
            target,
        )
        logger.error("telegram_service: timeout sending [%s] '%s'", category, title)
        return {"sent": False, "reason": "request timeout"}
    except Exception as exc:
        _log_message(
            category, title, message, source_agent, source_department, source_module, "failed", str(exc), target
        )
        logger.error("telegram_service: error sending [%s] '%s': %s", category, title, exc)
        return {"sent": False, "reason": str(exc)}


def _format_archie_voice(cat: dict, title: str, message: str, source_agent: str = None) -> str:
    """Format message in A.R.C.H.I.E.'s executive voice.

    When source_agent is provided, frames as A.R.C.H.I.E. relaying from that agent.
    When not provided, A.R.C.H.I.E. speaks directly.
    """
    icon = cat["icon"]

    if source_agent:
        # A.R.C.H.I.E. relaying from another agent
        text = f"{icon} *{title}*\n\n" f"{source_agent} reports:\n" f"{message}\n\n" f"_— A.R.C.H.I.E._"
    else:
        # A.R.C.H.I.E. speaking directly
        text = f"{icon} *{title}*\n\n" f"{message}\n\n" f"_— A.R.C.H.I.E._"

    return text


def _log_message(
    category,
    title,
    message,
    source_agent=None,
    source_department=None,
    source_module=None,
    status="sent",
    error_message=None,
    chat_id=None,
    telegram_message_id=None,
    formatted_message=None,
):
    """Log message to telegram_message_log table. Returns log ID or None."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO telegram_message_log
                   (category, title, message, formatted_message, source_agent,
                    source_department, source_module, priority, status,
                    error_message, chat_id, telegram_message_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (
                    category,
                    title,
                    message,
                    formatted_message,
                    source_agent,
                    source_department,
                    source_module,
                    CATEGORIES.get(category, CATEGORIES["info"])["priority"],
                    status,
                    error_message,
                    chat_id,
                    telegram_message_id,
                ),
            )
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as exc:
        logger.debug("telegram_service: log failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Convenience shortcuts
# ---------------------------------------------------------------------------
def send_security(title: str, message: str, **kwargs) -> dict:
    """Send a critical security alert via V.I.G.I.L. (never throttled)."""
    kwargs.setdefault("source_agent", "V.I.G.I.L.")
    kwargs.setdefault("source_department", "Security & Compliance")
    return send("security", title, message, force=True, **kwargs)


def send_system(title: str, message: str, **kwargs) -> dict:
    """Send a system/infrastructure alert via B.A.S.E."""
    kwargs.setdefault("source_agent", "B.A.S.E.")
    kwargs.setdefault("source_department", "Operations & Infrastructure")
    return send("system", title, message, **kwargs)


def send_forge(title: str, message: str, **kwargs) -> dict:
    """Send a F.O.R.G.E. pipeline notification."""
    kwargs.setdefault("source_agent", "F.O.R.G.E.")
    kwargs.setdefault("source_department", "Engineering & Technology")
    return send("forge", title, message, **kwargs)


def send_agent(title: str, message: str, **kwargs) -> dict:
    """Send an agent lifecycle notification via K.I.N."""
    kwargs.setdefault("source_agent", "K.I.N.")
    kwargs.setdefault("source_department", "Human Resources & Culture")
    return send("agent", title, message, **kwargs)


def send_sync(title: str, message: str, **kwargs) -> dict:
    """Send a background sync notification via C.O.D.E.X."""
    kwargs.setdefault("source_agent", "C.O.D.E.X.")
    kwargs.setdefault("source_department", "Documentation & Knowledge")
    return send("sync", title, message, **kwargs)


def send_info(title: str, message: str, **kwargs) -> dict:
    """Send an informational notification from A.R.C.H.I.E. directly."""
    kwargs.setdefault("source_agent", "A.R.C.H.I.E.")
    kwargs.setdefault("source_department", "Executive Office")
    return send("info", title, message, **kwargs)
