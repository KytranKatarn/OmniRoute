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

import hashlib as _hashlib
import json as _json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_COMMS_SERVICE_TOKEN = os.getenv("ARCHIE_COMMS_SERVICE_TOKEN", "")

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
    """Resolve chat ID: cached value → TELEGRAM_CHAT_ID env → telegram_users DB fallback.

    DB fallback picks the first `telegram_users.telegram_id` where `is_authorized=true`,
    so delivery keeps working even when env drifts. Result is cached for the process.
    """
    global _default_chat_id
    if _default_chat_id:
        return _default_chat_id
    _default_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if _default_chat_id:
        return _default_chat_id
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute("SELECT telegram_id FROM telegram_users " "WHERE is_authorized = true ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if row:
                _default_chat_id = str(row["telegram_id"])
                logger.info("telegram_service: chat_id resolved from telegram_users fallback")
    except Exception as exc:
        logger.debug("telegram_service: DB chat_id fallback failed: %s", exc)
    return _default_chat_id


# ---------------------------------------------------------------------------
# Core send function
# ---------------------------------------------------------------------------
# Callers that may send directly to Telegram (bypass the inbox redirect).
# All other callers are routed to the director_reports inbox for triage.
_PRIVILEGED_SOURCES = frozenset({"A.R.C.H.I.E.", "archie_triage_consumer", "system_bootstrap"})


def _audit_send(
    category: str,
    title: str,
    source_agent: str,
    route: str,
    suppressed: bool,
) -> None:
    """Write a send-attempt row to governance_audit_log. Non-blocking."""
    try:
        from database import get_db_cursor

        msg_hash = _hashlib.sha256(f"{title}{source_agent}".encode()).hexdigest()[:16]
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO governance_audit_log
                  (event_category, event_type, action, details, timestamp)
                VALUES ('telegram_send', %s, %s, %s::jsonb, NOW())
                """,
                (
                    category,
                    source_agent or "unknown",
                    _json.dumps(
                        {
                            "title": title,
                            "route": route,
                            "suppressed": suppressed,
                            "msg_hash": msg_hash,
                        }
                    ),
                ),
            )
    except Exception as _e:
        logger.warning("telegram audit log failed (non-blocking): %s", _e)


def send(
    category: str,
    title: str,
    message: str,
    source_agent: str = None,
    source_department: str = None,
    source_module: str = None,
    chat_id: str = None,
    force: bool = False,
    _privileged: bool = False,
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
    # ── Privilege check ──────────────────────────────────────────────────────
    # Only A.R.C.H.I.E. / triage consumer / system_bootstrap may send directly
    # to Telegram. All other callers are redirected to the director_reports
    # inbox where A.R.C.H.I.E. triages and escalates if warranted.
    caller_is_privileged = _privileged or (source_agent in _PRIVILEGED_SOURCES)

    if not caller_is_privileged:
        raise PermissionError(
            f"telegram_service.send() called by unprivileged source '{source_agent}'. "
            f"Use director_report_service.submit_via_inbox() instead. "
            f"Add to _PRIVILEGED_SOURCES only if this caller IS A.R.C.H.I.E.'s voice."
        )
    # ─────────────────────────────────────────────────────────────────────────

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

    # Format as A.R.C.H.I.E.'s voice — personality engine with LLM fallback
    try:
        from services.archie_voice_service import format_message as _voice_format

        text = _voice_format(
            category=category,
            title=title,
            raw_message=message,
            source_agent=source_agent,
            source_department=source_department,
        )
    except Exception as _voice_err:
        logger.debug("telegram_service: voice service unavailable (%s), using template", _voice_err)
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
            _audit_send(category, title, source_agent, route="direct", suppressed=False)
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
# Convenience shortcuts — route to director_reports inbox (not Telegram directly)
# ---------------------------------------------------------------------------


def _inbox_send(
    category: str,
    title: str,
    message: str,
    source_agent: str,
    severity: str,
    department: str,
    cooldown_hours: float = 0,
) -> dict:
    """Shared helper: submit_via_inbox + governance audit log."""
    from services.director_report_service import submit_via_inbox

    result = submit_via_inbox(
        category=category,
        title=title,
        message=message,
        source_agent=source_agent,
        severity=severity,
        department=department,
        cooldown_hours=cooldown_hours,
    )
    suppressed = result.get("routed_to") == "suppressed_duplicate"
    _audit_send(category, title, source_agent, route="inbox", suppressed=suppressed)
    return result


def send_security(title: str, message: str, **kwargs) -> dict:
    """Critical security alert via V.I.G.I.L. — writes to director_reports inbox."""
    return _inbox_send(
        category="security",
        title=title,
        message=message,
        source_agent=kwargs.get("source_agent", "V.I.G.I.L."),
        severity="critical",
        department=kwargs.get("source_department", "Security & Compliance"),
    )


def send_system(title: str, message: str, **kwargs) -> dict:
    """Infrastructure alert via B.A.S.E. — writes to director_reports inbox.

    Persistent conditions (same title + source) are suppressed after the first
    report within the cooldown window (default 2h) to prevent watchdog floods.
    Pass cooldown_hours=0 to disable dedup for one-shot events.
    """
    return _inbox_send(
        category="system",
        title=title,
        message=message,
        source_agent=kwargs.get("source_agent", "B.A.S.E."),
        severity="warning",
        department=kwargs.get("source_department", "Operations & Infrastructure"),
        cooldown_hours=kwargs.get("cooldown_hours", 2.0),
    )


def send_forge(title: str, message: str, **kwargs) -> dict:
    """F.O.R.G.E. pipeline notification — writes to director_reports inbox."""
    return _inbox_send(
        category="forge",
        title=title,
        message=message,
        source_agent=kwargs.get("source_agent", "F.O.R.G.E."),
        severity="info",
        department=kwargs.get("source_department", "Engineering & Technology"),
    )


def send_agent(title: str, message: str, **kwargs) -> dict:
    """Agent lifecycle notification via K.I.N. — writes to director_reports inbox."""
    return _inbox_send(
        category="agent",
        title=title,
        message=message,
        source_agent=kwargs.get("source_agent", "K.I.N."),
        severity="info",
        department=kwargs.get("source_department", "Human Resources & Culture"),
    )


def send_sync(title: str, message: str, **kwargs) -> dict:
    """Background sync notification via C.O.D.E.X. — writes to director_reports inbox."""
    return _inbox_send(
        category="sync",
        title=title,
        message=message,
        source_agent=kwargs.get("source_agent", "C.O.D.E.X."),
        severity="info",
        department=kwargs.get("source_department", "Documentation & Knowledge"),
    )


def send_info(title: str, message: str, **kwargs) -> dict:
    """Informational notification from A.R.C.H.I.E. directly (privileged — bypasses inbox)."""
    kwargs.setdefault("source_agent", "A.R.C.H.I.E.")
    kwargs.setdefault("source_department", "Executive Office")
    return send("info", title, message, **kwargs)


def send_with_buttons(
    category: str,
    title: str,
    message: str,
    buttons: list,
    source_agent: str = "A.R.C.H.I.E.",
    source_department: str = "Executive Office",
) -> dict:
    """Send a Telegram message with an inline keyboard (reply_markup).

    This is a privileged call — callers must be A.R.C.H.I.E. or an
    authorized dispatcher component that sends escalation approval buttons.
    All other notification needs must use submit_via_inbox().

    Args:
        category:          Notification category (e.g. 'agent', 'system').
        title:             Short title for the message.
        message:           Body text (Markdown supported).
        buttons:           List of InlineKeyboardButton dicts for one button row,
                           e.g. [{"text": "Approve", "callback_data": "esc_approve_1"}].
        source_agent:      Sending agent name (must be privileged).
        source_department: Originating department.

    Returns:
        dict: {sent: bool, reason: str (if failed)}
    """
    token = _get_token()
    if not token:
        return {"sent": False, "reason": "no bot token configured"}

    cat_info = CATEGORIES.get(category, CATEGORIES["info"])
    emoji = cat_info["icon"]
    tg_text = f"{emoji} *{title}*\n\n{message}"

    target = _get_chat_id()
    if not target:
        logger.debug("send_with_buttons: no chat_id configured")
        return {"sent": False, "reason": "no chat_id configured"}

    # Fetch all authorized users so escalation buttons reach every admin
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT telegram_id FROM telegram_users " "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
            )
            rows = cur.fetchall()
        chat_ids = [r[0] for r in rows] if rows else [target]
    except Exception:
        chat_ids = [target]

    payload_base = {
        "text": tg_text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": [buttons]},
    }

    sent_count = 0
    for cid in chat_ids:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={**payload_base, "chat_id": cid},
                timeout=15,
            )
            if resp.ok:
                sent_count += 1
        except Exception as exc:
            logger.debug("send_with_buttons to %s failed: %s", cid, exc)

    logger.info(
        "[telegram_service] send_with_buttons category=%s title=%r sent_to=%d/%d",
        category,
        title,
        sent_count,
        len(chat_ids),
    )
    return {"sent": sent_count > 0, "sent_count": sent_count}
