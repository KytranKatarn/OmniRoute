"""Interactive operational alerts — inline Telegram buttons + their actions.

The watchdog/HR alerts (disk pressure, queue zombie reaper, HR counter drift) used to
go out as plain text via ``telegram_service.send_system`` (inbox-relayed, no buttons).
This service sends them DIRECTLY with an inline keyboard so Kytran can act from the
phone, and implements the button actions the gateway callback dispatches.

Buttons are deliberately SAFE — read-only diagnostics, a benign acknowledge, and a
time-boxed snooze. Nothing here deletes data or runs a destructive op on one tap;
anything state-changing (e.g. a real backup prune) stays on the approval path.

callback_data scheme (parsed in ai_bridge/telegram_gateway.py :: _alert_callback):
    alert_<action>_<alert_key>      e.g.  alert_snooze_disk_primary
                                          alert_details_zombie_reaper
                                          alert_ack_hr_1234
``alert_key`` may itself contain underscores; the gateway splits with maxsplit=2 so
the key is preserved verbatim.

Everything here is fail-open / fail-safe: a DB hiccup must never stop an alert from
firing, and an action that errors returns a friendly string rather than raising.
"""

from __future__ import annotations

import logging
import shutil

logger = logging.getLogger(__name__)

# Default snooze when Kytran taps "🔕 Snooze 24h".
DEFAULT_SNOOZE_HOURS = 24

# Disk mounts the watchdog reports on (mirrors ai_bridge/agent_loop.py _platform_watchdog).
_DISK_MOUNTS = [("primary", "/mnt/data2"), ("usb", "/mnt/external-backup")]


# ── snooze state ────────────────────────────────────────────────────────────
def is_snoozed(alert_key: str) -> bool:
    """True if this alert_key is currently snoozed. Fail-OPEN (False on any error)
    so a DB problem never silences a real alert."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT 1 FROM alert_snoozes WHERE alert_key = %s AND snoozed_until > NOW()",
                (alert_key,),
            )
            return cur.fetchone() is not None
    except Exception as exc:
        logger.debug("alert_actions.is_snoozed(%s) check failed (fail-open): %s", alert_key, exc)
        return False


def snooze(alert_key: str, hours: int = DEFAULT_SNOOZE_HOURS, by: str = "Kytran") -> str:
    """Suppress this alert_key for `hours`. Returns a human confirmation string."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO alert_snoozes (alert_key, snoozed_until, created_by, updated_at)
                VALUES (%s, NOW() + (%s || ' hours')::interval, %s, NOW())
                ON CONFLICT (alert_key) DO UPDATE
                   SET snoozed_until = EXCLUDED.snoozed_until,
                       created_by    = EXCLUDED.created_by,
                       updated_at    = NOW()
                """,
                (alert_key, str(int(hours)), by),
            )
        return f"🔕 Snoozed *{alert_key}* for {int(hours)}h — I won't re-alert on this until then."
    except Exception as exc:
        logger.warning("alert_actions.snooze(%s) failed: %s", alert_key, exc)
        return "⚠️ Couldn't record the snooze (logged). The alert may re-fire."


# ── acknowledge (HR alerts) ─────────────────────────────────────────────────
def acknowledge_hr(alert_id: int, by: str = "Kytran") -> str:
    """Resolve an agent_alerts row (the ✓ Acknowledge button on HR alerts)."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE agent_alerts
                   SET resolved = TRUE, resolved_at = NOW(), resolved_by = %s
                 WHERE id = %s AND resolved = FALSE
             RETURNING alert_type
                """,
                (by, alert_id),
            )
            row = cur.fetchone()
        if row:
            atype = row[0] if not isinstance(row, dict) else row.get("alert_type")
            return f"✅ Acknowledged HR alert #{alert_id} ({atype}). Marked resolved."
        return f"✅ HR alert #{alert_id} was already resolved."
    except Exception as exc:
        logger.warning("alert_actions.acknowledge_hr(%s) failed: %s", alert_id, exc)
        return "⚠️ Couldn't acknowledge that alert (logged)."


# ── details (read-only diagnostics per alert family) ────────────────────────
def alert_details(alert_key: str) -> str:
    """Return a short, read-only diagnostic for the 📊 Details button, chosen by
    the alert_key family. Always returns a string (never raises)."""
    try:
        if alert_key.startswith("disk") or alert_key.startswith("backup"):
            return _disk_details()
        if alert_key.startswith("zombie"):
            return _zombie_details()
        if alert_key.startswith("hr_"):
            return _hr_details(alert_key)
        if alert_key.startswith("wtf"):
            return _wtf_ingest_details()
        return f"No extra detail available for {alert_key}."
    except Exception as exc:
        logger.debug("alert_actions.alert_details(%s) failed: %s", alert_key, exc)
        return "⚠️ Detail lookup failed (logged)."


def _wtf_ingest_details() -> str:
    """WTF ingest diagnostic from the PUBLIC API (no DB credential). Read-only; never raises. (#4890, #7372)

    The hub `wtf` database was retired on 2026-10-02, so this can no longer report minutes-since-newest-ingest or the
    settled-cohort classifier coverage; both need a read-only Citadel role. It says so instead of failing."""
    try:
        from services import wtf_remote

        lines = ["📊 *WTF ingest freshness*", ""]
        lines.append(f"Published articles: {wtf_remote.article_count():,}")
        heads = wtf_remote.latest_headlines(limit=3, days=1)
        if heads:
            lines.append("Latest headlines: " + " · ".join(f"{t[:60]} ({o})" for t, o in heads))
        lines += [
            "",
            "ℹ️ Coarse view only: the watchdog alerts after 4h with no change in the article count. Real ingest gaps "
            "of up to ~3.4h occur (task #7374). Minutes-since-ingest and beat/geo coverage need a read-only Citadel "
            "DB role (the hub wtf DB was retired 2026-10-02).",
            "Check `wtf-ingest` on Citadel: `docker logs what-the-fact-wtf-ingest-1`.",
        ]
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("alert_actions._wtf_ingest_details failed: %s", type(exc).__name__)
        return "⚠️ WTF ingest detail unavailable (public API unreachable; logged)."


def _disk_details() -> str:
    lines = ["📊 *Disk / backup detail*", ""]
    for name, path in _DISK_MOUNTS:
        try:
            u = shutil.disk_usage(path)
            free_gb = u.free / 1e9
            total_gb = u.total / 1e9
            pct_free = 100.0 * u.free / u.total if u.total else 0.0
            lines.append(f"• {name} ({path}): {free_gb:.0f}G free / {total_gb:.0f}G ({pct_free:.1f}% free)")
        except FileNotFoundError:
            lines.append(f"• {name} ({path}): mount missing")
        except Exception:
            lines.append(f"• {name} ({path}): unavailable")
    # Backup activity per tier from the ledger (last 30d) — what the pruner manages.
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT tier,
                       COUNT(*) FILTER (WHERE status = 'success')             AS ok,
                       MAX(created_at) FILTER (WHERE status = 'success')::date AS last_ok
                  FROM backup_log
                 WHERE created_at > NOW() - INTERVAL '30 days'
                   AND tier IS NOT NULL
              GROUP BY tier
              ORDER BY tier
                """
            )
            rows = cur.fetchall() or []
        if rows:
            lines.append("")
            lines.append("Backup success (30d):")
            for r in rows:
                tier = r[0] if not isinstance(r, dict) else r.get("tier")
                ok = r[1] if not isinstance(r, dict) else r.get("ok")
                last_ok = r[2] if not isinstance(r, dict) else r.get("last_ok")
                lines.append(f"• {tier}: {ok} ok · last {last_ok or 'never'}")
    except Exception:
        lines.append("")
        lines.append("Backup ledger: unavailable")
    lines += ["", "_Deletes stay manual/approval-gated — this is read-only._"]
    return "\n".join(lines)


def _zombie_details() -> str:
    """Show current non-terminal dispatch work (the 'active work' canonical filter)."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT status, COUNT(*) AS n
                  FROM bridge_jobs
                 WHERE status NOT IN ('completed', 'failed', 'cancelled')
              GROUP BY status
              ORDER BY n DESC
                 LIMIT 8
                """
            )
            rows = cur.fetchall() or []
        if not rows:
            return "📊 *Queue detail*\n\nNo non-terminal dispatch jobs right now — queue is clean."
        parts = []
        for r in rows:
            st = r[0] if not isinstance(r, dict) else r.get("status")
            n = r[1] if not isinstance(r, dict) else r.get("n")
            parts.append(f"• {st}: {n}")
        return "📊 *Queue detail* — active (non-terminal) jobs:\n\n" + "\n".join(parts)
    except Exception as exc:
        logger.debug("alert_actions._zombie_details failed: %s", exc)
        return "⚠️ Queue detail unavailable (logged)."


def _hr_details(alert_key: str) -> str:
    """alert_key = 'hr_<agent_alerts.id>' → the alert + the agent's live counters."""
    try:
        alert_id = int(alert_key.split("_", 1)[1])
    except (IndexError, ValueError):
        return "⚠️ Malformed HR alert key."
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """
                SELECT aa.agent_id, aa.alert_type, aa.message, aa.resolved,
                       a.name AS agent_name, ab.current_task_count
                  FROM agent_alerts aa
             LEFT JOIN agents a        ON a.id = aa.agent_id
             LEFT JOIN agent_budgets ab ON ab.agent_id = aa.agent_id
                 WHERE aa.id = %s
                """,
                (alert_id,),
            )
            r = cur.fetchone()
        if not r:
            return f"HR alert #{alert_id} not found."

        def _g(row, idx, key):
            return row[idx] if not isinstance(row, dict) else row.get(key)

        name = _g(r, 4, "agent_name") or f"agent #{_g(r, 0, 'agent_id')}"
        atype = _g(r, 1, "alert_type")
        msg = _g(r, 2, "message")
        resolved = _g(r, 3, "resolved")
        ctc = _g(r, 5, "current_task_count")
        state = "resolved" if resolved else "open"
        return (
            f"📊 *HR alert #{alert_id}* ({state})\n\n"
            f"Agent: {name}\nType: {atype}\n"
            f"current_task_count: {ctc}\n\n{msg}"
        )
    except Exception as exc:
        logger.debug("alert_actions._hr_details failed: %s", exc)
        return "⚠️ HR detail unavailable (logged)."


# ── the send wrapper (snooze-gated, buttons attached) ───────────────────────
def _build_buttons(alert_key: str, actions) -> list:
    """Map action keywords → one row of inline-keyboard button dicts."""
    labels = {
        "ack": ("✓ Acknowledge", "ack"),
        "details": ("📊 Details", "details"),
        "snooze": ("🔕 Snooze 24h", "snooze"),
    }
    row = []
    for a in actions or []:
        spec = labels.get(a)
        if not spec:
            continue
        text, verb = spec
        row.append({"text": text, "callback_data": f"alert_{verb}_{alert_key}"})
    return row


def send_alert(
    alert_key: str,
    title: str,
    message: str,
    actions=("details", "snooze"),
    category: str = "system",
    source_agent: str = "A.R.C.H.I.E.",
    source_department: str = "Executive Office",
    cooldown_hours: float = 2.0,
) -> dict:
    """Send an operational alert with interactive buttons — UNLESS it's snoozed.

    Returns telegram_service.send_with_buttons' dict, or {sent:False, reason:'snoozed'}.
    Callers already wrap this in try/except; it also never raises on its own.
    """
    try:
        if is_snoozed(alert_key):
            logger.info("alert_actions.send_alert: %s is snoozed — skipping send", alert_key)
            return {"sent": False, "reason": "snoozed"}

        # A standing condition must not be re-announced every job cycle. `send_system` has
        # had this dedup for ages via submit_via_inbox; send_alert never did, which is why
        # 486 of 842 daily deliveries were watchdogs repeating themselves. Pass
        # cooldown_hours=0 for a genuine one-shot event.
        from services.telegram_service import _recently_delivered

        if _recently_delivered(category, title, cooldown_hours):
            logger.info(
                "alert_actions.send_alert: %s within %.1fh cooldown — skipping send",
                alert_key,
                cooldown_hours,
            )
            return {"sent": False, "reason": "cooldown"}

        buttons = _build_buttons(alert_key, actions)
        from services.telegram_service import send_with_buttons

        return send_with_buttons(
            category=category,
            title=title,
            message=message,
            buttons=buttons,
            source_agent=source_agent,
            source_department=source_department,
        )
    except Exception as exc:
        logger.warning("alert_actions.send_alert(%s) failed: %s", alert_key, exc)
        return {"sent": False, "reason": str(exc)[:120]}
