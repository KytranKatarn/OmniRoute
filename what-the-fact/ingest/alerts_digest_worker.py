"""alerts_digest_worker.py — Custom alerts digest (#2913).

Subscriber-configured alerts (wtf.user_alerts) → matched articles → email
digest. Designed for once-per-cycle drains; idempotent (last_sent_at floor
prevents duplicate sends).

Default OFF. Set WTF_ALERTS_ENABLED=true once Stalwart SMTP relay is wired
into wtf-ingest. Until then, run logs would-have-sent diagnostics to stdout
so we can verify match logic before turning on email delivery.
"""

import logging
import os
import smtplib
from email.message import EmailMessage

from sqlalchemy import text

logger = logging.getLogger("wtf-ingest")

_ENABLED = os.environ.get("WTF_ALERTS_ENABLED", "false").lower() == "true"
_MAX_ALERTS_PER_RUN = int(os.environ.get("WTF_ALERTS_MAX_PER_RUN", "200"))
_MAX_ARTICLES_PER_ALERT = int(os.environ.get("WTF_ALERTS_MAX_ARTICLES", "10"))

# Stalwart SMTP — reachable from VPS via mesh (hub mesh IP 100.64.0.4)
_SMTP_HOST = os.environ.get("WTF_ALERTS_SMTP_HOST", "100.64.0.4")
_SMTP_PORT = int(os.environ.get("WTF_ALERTS_SMTP_PORT", "587"))
_SMTP_USER = os.environ.get("WTF_ALERTS_SMTP_USER", "")
_SMTP_PASS = os.environ.get("WTF_ALERTS_SMTP_PASS", "")
_FROM_ADDR = os.environ.get("WTF_ALERTS_FROM", "alerts@what-the-fact.com")
_PUBLIC_BASE = os.environ.get("WTF_PUBLIC_BASE", "https://what-the-fact.com")

_ALLOWED_SCHEMAS = frozenset({"wtf"})


def _fetch_active_alerts(engine, schema: str, limit: int) -> list[dict]:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_fetch_active_alerts: disallowed schema {schema!r}")
    with engine.connect() as c:
        rows = c.execute(text(f"""
            SELECT id, user_email, keyword, source_slug, bias_band,
                   province_code, last_sent_at, sent_count
            FROM {schema}.user_alerts
            WHERE active = TRUE
            ORDER BY COALESCE(last_sent_at, '1970-01-01'::timestamp) ASC
            LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def _find_matches(engine, schema: str, alert: dict) -> list[dict]:
    """Return articles matching this alert since last_sent_at (or last 24h)."""
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_find_matches: disallowed schema {schema!r}")
    pat = "%" + (alert["keyword"] or "").lower() + "%"
    floor = alert["last_sent_at"]  # may be None
    sql = f"""
        SELECT a.id, a.title, a.url, a.published_at, s.slug AS source_slug,
               b.band AS bias_band
        FROM {schema}.articles a
        JOIN {schema}.sources s ON s.id = a.source_id
        LEFT JOIN {schema}.bias_scores b ON b.article_id = a.id
        WHERE (LOWER(a.title) LIKE :pat OR LOWER(LEFT(a.body, 3000)) LIKE :pat)
          AND a.published_at > {{floor_clause}}
    """
    params = {"pat": pat, "limit": _MAX_ARTICLES_PER_ALERT}
    if floor:
        sql = sql.replace("{floor_clause}", ":floor")
        params["floor"] = floor
    else:
        sql = sql.replace("{floor_clause}", "NOW() - INTERVAL '24 hours'")
    if alert.get("source_slug"):
        sql += " AND s.slug = :src"
        params["src"] = alert["source_slug"]
    if alert.get("bias_band"):
        sql += " AND b.band = :bias"
        params["bias"] = alert["bias_band"]
    if alert.get("province_code"):
        sql += " AND a.province_code = :prov"
        params["prov"] = alert["province_code"]
    sql += " ORDER BY a.published_at DESC LIMIT :limit"
    with engine.connect() as c:
        rows = c.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def _render_email_body(alert: dict, matches: list[dict]) -> str:
    """Plain-text digest. HTML version is a follow-up."""
    filters = []
    if alert.get("source_slug"):
        filters.append(f"source={alert['source_slug']}")
    if alert.get("bias_band"):
        filters.append(f"bias={alert['bias_band']}")
    if alert.get("province_code"):
        filters.append(alert["province_code"])
    filter_str = " · ".join(filters) or "any source/bias/province"

    lines = [
        f"WTF Alert digest — '{alert['keyword']}'",
        f"Filters: {filter_str}",
        f"{len(matches)} new match(es) since your last digest.",
        "",
    ]
    for m in matches:
        lines.append(f"  · {m['title']}")
        lines.append(f"    {m['source_slug']}"
                     + (f" · {m['bias_band']}" if m.get('bias_band') else '')
                     + f" · {_PUBLIC_BASE}/article/{m['id']}")
        lines.append("")
    lines.append("---")
    lines.append(f"Manage your alerts: {_PUBLIC_BASE}/alerts")
    return "\n".join(lines)


def _send_email(to_addr: str, subject: str, body: str) -> tuple[bool, str | None]:
    """Send via Stalwart SMTP. Returns (sent, error_or_skip_reason)."""
    if not _ENABLED:
        logger.info("[alerts_digest] WOULD send to=%s subject=%r len=%d",
                    to_addr, subject, len(body))
        return False, "disabled"
    if not _SMTP_USER or not _SMTP_PASS:
        return False, "smtp_creds_missing"
    msg = EmailMessage()
    msg["From"] = _FROM_ADDR
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as s:
            s.starttls()
            s.login(_SMTP_USER, _SMTP_PASS)
            s.send_message(msg)
        return True, None
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _mark_sent(engine, schema: str, alert_id: int, last_match_id: int | None) -> None:
    if schema not in _ALLOWED_SCHEMAS:
        raise ValueError(f"_mark_sent: disallowed schema {schema!r}")
    with engine.begin() as c:
        c.execute(text(f"""
            UPDATE {schema}.user_alerts
            SET last_sent_at = NOW(),
                sent_count = sent_count + 1,
                last_match_id = COALESCE(:mid, last_match_id)
            WHERE id = :id
        """), {"id": alert_id, "mid": last_match_id})


def run_digest(engine, schema: str = "wtf") -> dict:
    """One pass: scan active alerts, match articles, dispatch emails.

    Returns counters for observability ({alerts_scanned, matched, sent, skipped, errors}).
    Caller (ingest/run.py) treats this like any other backlog worker — call once
    per cycle, log the result.
    """
    if not _ENABLED:
        # Still scan + log to verify match logic; don't actually send.
        logger.debug("[alerts_digest] WTF_ALERTS_ENABLED=false — match-only mode")

    scanned = 0
    matched = 0
    sent = 0
    skipped = 0
    errors = 0

    alerts = _fetch_active_alerts(engine, schema, _MAX_ALERTS_PER_RUN)
    for alert in alerts:
        scanned += 1
        try:
            hits = _find_matches(engine, schema, alert)
        except Exception as exc:
            errors += 1
            logger.warning("[alerts_digest] match query failed alert=%s: %s",
                           alert["id"], exc)
            continue
        if not hits:
            skipped += 1
            continue
        matched += 1
        subject = f"[WTF] {len(hits)} new match(es) — '{alert['keyword']}'"
        body = _render_email_body(alert, hits)
        ok, err = _send_email(alert["user_email"], subject, body)
        if ok:
            sent += 1
            _mark_sent(engine, schema, alert["id"], hits[0]["id"])
        else:
            # Still advance last_sent_at when only thing missing is the SMTP
            # creds — we don't want to keep re-finding the same articles on
            # every cycle while creds are pending. Skip-only on transient errs.
            if err in ("disabled", "smtp_creds_missing"):
                _mark_sent(engine, schema, alert["id"], hits[0]["id"])
                skipped += 1
            else:
                errors += 1
                logger.warning("[alerts_digest] send failed alert=%s: %s",
                               alert["id"], err)

    return {
        "alerts_scanned": scanned,
        "matched": matched,
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
        "enabled": _ENABLED,
    }
